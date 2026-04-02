"""Context builder for node registry and component discovery.

Transforms node registry metadata into LLM-optimized markdown documentation
for component discovery and workflow authoring.
"""

import json
import logging
from typing import Any, Optional

from pflow.core.workflow.manager import WorkflowManager

logger = logging.getLogger(__name__)

# Constants
MAX_OUTPUT_SIZE = 200000  # 200KB limit for LLM context (increased for detailed format)
MAX_STRUCTURE_HINTS = 100  # Increased limit for structure display


def _process_nodes(registry_metadata: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int]:
    """Process registry metadata to extract and enrich node information.

    Args:
        registry_metadata: Dict mapping node types to metadata dicts

    Returns:
        Tuple of (processed nodes dict, skipped count)
    """
    processed_nodes = {}
    skipped_count = 0

    for node_type, node_info in registry_metadata.items():
        # Skip metadata entries that are not actual nodes
        if node_type.startswith("__") and node_type.endswith("__"):
            continue

        # Use pre-parsed interface data directly from registry
        interface = node_info.get("interface")
        if not interface:
            # This should never happen with new Node IR - all nodes have interface
            logger.error(f"context: Node '{node_type}' missing interface field - regenerate registry")
            raise ValueError(f"Node '{node_type}' missing interface data. Run registry update.")

        # Store processed node with interface data
        processed_nodes[node_type] = {
            "description": interface.get("description", "No description"),
            "inputs": interface.get("inputs", []),
            "outputs": interface.get("outputs", []),
            "params": interface.get("params", []),
            "actions": interface.get("actions", []),
            "registry_info": node_info,
        }

    # No more skipped nodes due to import errors - all data pre-parsed
    return processed_nodes, skipped_count


# Map of known pflow node categories to friendly names
_PFLOW_CATEGORY_NAMES = {
    "file": "File Operations",
    "ai": "AI/LLM Operations",  # Match module path pflow.nodes.ai.*
    "llm": "AI/LLM Operations",
    "shell": "System Operations",
}


def _get_mcp_node_category(registry_info: dict) -> str:
    """Determine category for MCP nodes based on server metadata.

    Args:
        registry_info: Node registry information containing MCP metadata

    Returns:
        Category string for the MCP node
    """
    mcp_metadata = registry_info.get("interface", {}).get("mcp_metadata", {})
    server = mcp_metadata.get("server", "unknown")
    # Capitalize server name and add "Tools" suffix for clarity
    return f"{server.title()} Tools"


def _get_pflow_node_category(module: str) -> str:
    """Determine category for pflow nodes based on module path.

    Args:
        module: Module path string (e.g., 'pflow.nodes.file.copy_file')

    Returns:
        Category string for the pflow node
    """
    if module.startswith("pflow.nodes."):
        # Extract category: pflow.nodes.file.copy_file -> "file"
        parts = module.split(".")
        if len(parts) >= 3:
            namespace = parts[2]
            # Use friendly name if known, otherwise capitalize namespace
            return _PFLOW_CATEGORY_NAMES.get(namespace, f"{namespace.title()} Operations")
        return "General Operations"

    if module:
        return "General Operations"

    return ""  # Empty module - will trigger fallback


def _get_category_from_node_name(node_type: str) -> str:
    """Infer category from node name patterns as fallback.

    Args:
        node_type: Node type/name string

    Returns:
        Category string based on name patterns
    """
    # Try to infer category from actual production node name patterns
    # Only include patterns that exist in real nodes
    if any(pattern in node_type for pattern in ["read-file", "write-file", "copy-file", "move-file", "delete-file"]):
        return "File Operations"

    if node_type == "llm" or "ai-" in node_type:
        return "AI/LLM Operations"

    if any(pattern in node_type for pattern in ["shell", "bash", "cmd"]):
        return "System Operations"

    return "General Operations"


def _group_nodes_by_category(nodes: dict[str, dict]) -> dict[str, list[str]]:
    """Group nodes by category based on namespace and metadata.

    For native pflow nodes: Extract category from module path (e.g., pflow.nodes.file.* -> "File Operations")
    For MCP nodes: Use the server name as category (e.g., filesystem -> "Filesystem Tools")
    """
    categories: dict[str, list[str]] = {}

    for node_type, node_data in nodes.items():
        # Get registry info if available (from processed nodes)
        registry_info = node_data.get("registry_info", node_data)

        # Check if it's an MCP node
        if registry_info.get("file_path") == "virtual://mcp":
            category = _get_mcp_node_category(registry_info)
        else:
            # Native pflow node - extract from module path
            module = registry_info.get("module", "")
            category = _get_pflow_node_category(module)

            # Fallback to name pattern matching if no category determined
            if not category:
                category = _get_category_from_node_name(node_type)

        if category not in categories:
            categories[category] = []
        categories[category].append(node_type)

    return categories


def _format_structure_combined(
    structure: dict[str, Any], parent_path: str = ""
) -> tuple[dict[str, Any], list[tuple[str, str, str]]]:
    """Transform nested structure into JSON representation and path list.

    This is the preferred method for displaying structures in discovery output.
    It produces a combined JSON + paths format that is optimal for LLM comprehension
    and enables accurate proxy mapping generation (e.g., "author": "issue_data.user.login").

    The dual representation (JSON for structure understanding, paths for direct copying)
    reduces LLM errors and improves accuracy when generating workflows.

    Args:
        structure: Nested structure dict from metadata
        parent_path: Parent path for recursion (e.g., "issue_data")

    Returns:
        Tuple of:
        - JSON dict with types only (for clean display)
        - List of (path, type, description) tuples
    """
    json_struct: dict[str, Any] = {}
    paths: list[tuple[str, str, str]] = []

    for field_name, field_info in structure.items():
        if isinstance(field_info, dict):
            field_type = field_info.get("type", "any")
            field_desc = field_info.get("description", "")

            # Build current path
            current_path = f"{parent_path}.{field_name}" if parent_path else field_name

            # Add to paths list
            paths.append((current_path, field_type, field_desc))

            # Handle nested structures
            if "structure" in field_info and isinstance(field_info["structure"], dict):
                # For JSON representation
                if field_type == "dict":
                    nested_json, nested_paths = _format_structure_combined(field_info["structure"], current_path)
                    json_struct[field_name] = nested_json
                    paths.extend(nested_paths)
                elif field_type in ("list", "list[dict]"):
                    # For lists, show the item structure
                    nested_json, nested_paths = _format_structure_combined(field_info["structure"], f"{current_path}[]")
                    json_struct[field_name] = [nested_json] if nested_json else []
                    paths.extend(nested_paths)
                else:
                    # Fallback for other types
                    json_struct[field_name] = field_type
            elif field_type in ("list", "list[dict]") and "items" in field_info:
                # Handle legacy list format with items
                items_struct = field_info["items"]
                if isinstance(items_struct, dict):
                    nested_json, nested_paths = _format_structure_combined(items_struct, f"{current_path}[]")
                    json_struct[field_name] = [nested_json] if nested_json else []
                    paths.extend(nested_paths)
                else:
                    json_struct[field_name] = [field_type]
            else:
                # Simple type
                json_struct[field_name] = field_type
        else:
            # Fallback for non-dict entries
            json_struct[field_name] = "any"

    return json_struct, paths


def build_nodes_context(
    node_ids: Optional[list[str]] = None,
    registry_metadata: Optional[dict[str, dict[str, Any]]] = None,
) -> str:
    """Build context containing only node information as a numbered list.

    Args:
        node_ids: List of node IDs to include (None = all nodes)
        registry_metadata: Optional registry metadata dict. If not provided,
                          will attempt to load from default registry.

    Returns:
        Numbered list of nodes with descriptions
    """
    # Get registry metadata if not provided
    if registry_metadata is None:
        from pflow.registry import Registry

        registry = Registry()
        registry_metadata = registry.load()  # Now returns filtered nodes by default

    # Process nodes to get metadata
    processed_nodes, _ = _process_nodes(registry_metadata)

    # Filter nodes if specific IDs provided
    if node_ids is not None:
        filtered_nodes = {nid: data for nid, data in processed_nodes.items() if nid in node_ids}
    else:
        filtered_nodes = processed_nodes

    # Create numbered list of nodes grouped by category
    sections = []
    counter = 1
    categories = _group_nodes_by_category(filtered_nodes)

    for category, nodes in sorted(categories.items()):
        # Add category as a comment for organization
        sections.append(f"# {category}")
        for node_id in sorted(nodes):
            node_data = filtered_nodes[node_id]
            description = node_data.get("description", "").strip()

            if description and description != "No description":
                sections.append(f"{counter}. {node_id} - {description}")
            else:
                sections.append(f"{counter}. {node_id}")
            counter += 1
        sections.append("")  # Empty line between categories

    return "\n".join(sections).strip()


def _check_missing_components(
    selected_node_ids: list[str],
    selected_workflow_names: list[str],
    registry_metadata: dict[str, dict[str, Any]],
    saved_workflows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Check for missing components and return error dict if any found.

    Args:
        selected_node_ids: Node IDs to check
        selected_workflow_names: Workflow names to check
        registry_metadata: Registry metadata to check against
        saved_workflows: Workflows to check against

    Returns:
        Error dict if components missing, None otherwise
    """
    missing_nodes = []
    missing_workflows = []

    # Check nodes
    for node_id in selected_node_ids:
        if node_id not in registry_metadata:
            missing_nodes.append(node_id)

    # Check workflows
    for workflow_name in selected_workflow_names:
        if not any(w["name"] == workflow_name for w in saved_workflows):
            missing_workflows.append(workflow_name)

    # Return error dict if any components missing
    if missing_nodes or missing_workflows:
        error_msg = "Missing components detected:\n"
        if missing_nodes:
            error_msg += f"- Unknown nodes: {', '.join(missing_nodes)}\n"
            error_msg += "  (Check spelling, use hyphens not underscores)\n"
        if missing_workflows:
            error_msg += f"- Unknown workflows: {', '.join(missing_workflows)}\n"

        return {
            "error": error_msg.strip(),
            "missing_nodes": missing_nodes,
            "missing_workflows": missing_workflows,
        }

    return None


def _validate_component_context_inputs(
    selected_node_ids: list[str],
    selected_workflow_names: list[str],
    registry_metadata: dict[str, dict[str, Any]],
    saved_workflows: Optional[list[dict[str, Any]]],
) -> None:
    """Validate inputs for build_component_context."""
    if not isinstance(selected_node_ids, list):
        raise TypeError(f"selected_node_ids must be a list, got {type(selected_node_ids).__name__}")
    if not isinstance(selected_workflow_names, list):
        raise TypeError(f"selected_workflow_names must be a list, got {type(selected_workflow_names).__name__}")
    if not isinstance(registry_metadata, dict):
        raise TypeError(f"registry_metadata must be a dict, got {type(registry_metadata).__name__}")
    if saved_workflows is not None and not isinstance(saved_workflows, list):
        raise TypeError(f"saved_workflows must be a list or None, got {type(saved_workflows).__name__}")


def _format_component_nodes(selected_node_ids: list[str], processed_nodes: dict[str, dict]) -> list[str]:
    """Format nodes section for component context."""
    markdown_sections = []

    for node_id in sorted(selected_node_ids):
        if node_id in processed_nodes:
            node_data = processed_nodes[node_id]
            section = _format_node_section_enhanced(node_id, node_data)
            markdown_sections.append(section)

    return markdown_sections


def _format_component_workflows(selected_workflows: list[dict[str, Any]]) -> list[str]:
    """Format workflows section for component context."""
    markdown_sections = []

    if selected_workflows:
        markdown_sections.append("## Selected Workflows\n")
        # Sort workflows by name
        sorted_workflows = sorted(selected_workflows, key=lambda w: w["name"])
        for workflow in sorted_workflows:
            section = _format_workflow_section(workflow)
            markdown_sections.append(section)

    return markdown_sections


def build_component_context(
    selected_node_ids: list[str],
    selected_workflow_names: list[str],
    registry_metadata: dict[str, dict[str, Any]],
    saved_workflows: Optional[list[dict[str, Any]]] = None,
    workflow_manager: Optional[WorkflowManager] = None,
) -> str | dict[str, Any]:
    """Build detailed component context for selected components.

    This function provides complete interface details for components selected
    during discovery, enabling accurate workflow authoring.

    Args:
        selected_node_ids: Node IDs to include (required)
        selected_workflow_names: Workflow names to include (required)
        registry_metadata: Full registry metadata dict
        saved_workflows: Pre-loaded workflow list (optional, will load if None)
        workflow_manager: Optional WorkflowManager instance (used when saved_workflows is None)

    Returns:
        Either:
        - Markdown formatted component context with full details
        - Error dict with keys: "error", "missing_nodes", "missing_workflows"
    """
    # Input validation
    _validate_component_context_inputs(selected_node_ids, selected_workflow_names, registry_metadata, saved_workflows)

    # Load workflows if not provided
    if saved_workflows is None:
        manager = workflow_manager if workflow_manager else WorkflowManager()
        saved_workflows = manager.list_all()

    # Check for missing components
    error_dict = _check_missing_components(
        selected_node_ids, selected_workflow_names, registry_metadata, saved_workflows
    )
    if error_dict:
        return error_dict

    # Process selected nodes to extract metadata
    selected_registry = {nid: registry_metadata[nid] for nid in selected_node_ids}
    processed_nodes, _ = _process_nodes(selected_registry)

    # Build markdown sections
    markdown_sections = ["## Selected Components\n"]

    # Add nodes
    markdown_sections.extend(_format_component_nodes(selected_node_ids, processed_nodes))

    # Add workflows
    selected_workflows = [w for w in saved_workflows if w["name"] in selected_workflow_names]
    markdown_sections.extend(_format_component_workflows(selected_workflows))

    return "\n".join(markdown_sections).strip()


def _collect_all_parameters(inputs: list, params: list) -> tuple[list[dict], set]:
    """Collect all parameters from inputs and params lists.

    Returns:
        Tuple of (all_params list, input_keys set)
    """
    all_params = []
    input_keys = set()

    # First, collect all inputs as parameters
    for inp in inputs:
        if isinstance(inp, dict):
            all_params.append(inp)
            input_keys.add(inp["key"])
        else:
            # Simple string input
            all_params.append({"key": inp, "type": "any"})
            input_keys.add(inp)

    # Then add any exclusive params not in inputs
    for param in params:
        if isinstance(param, str):
            if param not in input_keys:
                all_params.append({"key": param, "type": "any", "is_config": True})
        elif isinstance(param, dict) and param.get("key") not in input_keys:
            param["is_config"] = True
            all_params.append(param)

    return all_params, input_keys


def _format_single_param_line(param: dict) -> str:
    """Format a single parameter line with all its details."""
    key = param.get("key", param) if isinstance(param, dict) else param
    type_str = param.get("type", "any") if isinstance(param, dict) else "any"
    desc = param.get("description", "") if isinstance(param, dict) else ""
    default = param.get("default") if isinstance(param, dict) else None
    required = param.get("required", True) if isinstance(param, dict) else True
    is_config = param.get("is_config", False) if isinstance(param, dict) else False

    # Build parameter line
    line = f"- `{key}: {type_str}`"

    # Add description
    if desc:
        line += f" - {desc}"
    elif is_config:
        line += " - Configuration parameter"

    # Add optional/default info
    if not required or default is not None:
        if default is not None:
            line += f" (optional, default: {default})"
        else:
            line += " (optional)"

    return line


def _format_all_parameters_new(node_data: dict, lines: list[str]) -> None:
    """Format ALL parameters for the node with clear indication they go in params field.

    With namespacing enabled, nodes cannot read inputs from shared store directly.
    All data must be passed via parameters using template variables.

    Args:
        node_data: Node metadata containing inputs and params
        lines: List to append formatted lines to
    """
    inputs = node_data.get("inputs", [])
    params = node_data.get("params", [])

    # Collect all parameters
    all_params, _ = _collect_all_parameters(inputs, params)

    if all_params:
        lines.append("**Parameters**:")

        for param in all_params:
            line = _format_single_param_line(param)
            lines.append(line)

            # Add structure display for complex types
            if isinstance(param, dict):
                type_str = param.get("type", "any")
                if type_str in ("dict", "list", "list[dict]") and "structure" in param:
                    _add_enhanced_structure_display(lines, param["key"], param["structure"])
    else:
        lines.append("**Parameters**: none")


def _format_outputs_with_access(node_data: dict, lines: list[str]) -> None:
    """Format outputs with clear access pattern for namespacing.

    Args:
        node_data: Node metadata containing outputs
        lines: List to append formatted lines to
    """
    outputs = node_data.get("outputs", [])

    if outputs:
        lines.append("**Outputs**:")

        for out in outputs:
            if isinstance(out, dict):
                key = out["key"]
                type_str = out.get("type", "any")
                desc = out.get("description", "")

                line = f"- `{key}: {type_str}`"
                if desc:
                    line += f" - {desc}"
                lines.append(line)

                # Add structure display for complex types
                if type_str in ("dict", "list", "list[dict]") and "structure" in out:
                    _add_enhanced_structure_display(lines, key, out["structure"])
            else:
                # Simple string output
                lines.append(f"- `{out}`")
    else:
        lines.append("**Outputs**: none")


# Rich usage templates for core node types. Each is a list of indented lines
# (4-space indent) that form a valid .pflow.md node snippet.
_RICH_SNIPPETS: dict[str, list[str]] = {
    "shell": [
        "    ### step-name",
        "",
        "    Describe what this step does and why.",
        "",
        "    - type: shell",
        "    - stdin: ${previous-step.response}",
        "",
        "    ```shell command",
        "    your-command-here",
        "    ```",
    ],
    "llm": [
        "    ### step-name",
        "",
        "    Describe what this step does and why.",
        "",
        "    - type: llm",
        "",
        "    ```markdown prompt",
        "    Your prompt here.",
        "",
        "    Context: ${previous-step.stdout}",
        "    ```",
    ],
    "code": [
        "    ### step-name",
        "",
        "    Describe what this step does and why.",
        "",
        "    - type: code",
        "    - inputs:",
        "        data: ${previous-step.result}",
        "",
        "    ```python code",
        "    data: list = []",
        "    result: list = [item for item in data if item]",
        "    ```",
    ],
    "http": [
        "    ### step-name",
        "",
        "    Describe what this step does and why.",
        "",
        "    - type: http",
        "    - url: https://api.example.com/endpoint",
        "    - method: GET",
    ],
    "claude-code": [
        "    ### step-name",
        "",
        "    Describe what this step does and why.",
        "",
        "    - type: claude-code",
        "    - model: claude-sonnet-4-5",
        "",
        "    ```markdown prompt",
        "    Your task description here.",
        "    ```",
    ],
    "write-file": [
        "    ### step-name",
        "",
        "    Describe what this step does and why.",
        "",
        "    - type: write-file",
        "    - file_path: ./output.txt",
        "    - content: ${previous-step.response}",
    ],
}


def _format_usage_snippet(node_type: str, node_data: dict, lines: list[str]) -> None:
    """Append a .pflow.md usage snippet for the node.

    Uses hardcoded rich templates for 6 core node types. Falls back to a
    generic snippet built from the first 3 interface params for everything
    else (including MCP nodes).

    Args:
        node_type: The workflow type string (e.g. "shell", "mcp-slack-SEND")
        node_data: Node metadata dict with params, inputs, registry_info
        lines: List to append formatted lines to
    """
    lines.append("")
    lines.append("**Usage in .pflow.md:**")
    lines.append("")

    if node_type in _RICH_SNIPPETS:
        lines.extend(_RICH_SNIPPETS[node_type])
    else:
        # Generic snippet from interface params
        snippet_lines = [
            "    ### step-name",
            "",
            "    Describe what this step does and why.",
            "",
            f"    - type: {node_type}",
        ]

        # Collect first 3 params for the example
        all_params = node_data.get("params", []) or []
        inputs = node_data.get("inputs", []) or []
        combined = list(inputs) + list(all_params)
        shown = 0
        for param in combined:
            if shown >= 3:
                break
            if isinstance(param, dict):
                key = param.get("key", "")
                if not key:
                    continue
                # First param gets a literal placeholder, subsequent get template refs
                ptype = param.get("type", "str").lower()
                if shown == 0:
                    # First param is typically a target (channel, path, etc.) — literal
                    placeholder = "value"
                elif ptype in ("int", "integer", "number"):
                    placeholder = "0"
                elif ptype in ("bool", "boolean"):
                    placeholder = "true"
                else:
                    placeholder = "${previous-step.response}"
                snippet_lines.append(f"    - {key}: {placeholder}")
                shown += 1

        lines.extend(snippet_lines)


def _format_node_section_enhanced(node_type: str, node_data: dict) -> str:
    """Format a node with clear parameter and output information.

    With namespacing enabled by default (Task 9), nodes cannot read inputs
    from shared store directly. All data must be passed via parameters using
    template variables. This format makes that requirement clear.

    Args:
        node_type: The type/name of the node
        node_data: Node metadata dictionary

    Returns:
        Formatted markdown string for the node
    """
    lines = [f"### {node_type}"]

    # Add description
    description = node_data.get("description", "").strip()
    if not description:
        description = "No description available"
    lines.append(description)
    lines.append("")

    # Format ALL parameters (not just exclusive)
    _format_all_parameters_new(node_data, lines)
    lines.append("")

    # Format outputs with access pattern
    _format_outputs_with_access(node_data, lines)

    # Add .pflow.md usage snippet
    _format_usage_snippet(node_type, node_data, lines)

    lines.append("")
    return "\n".join(lines)


def _add_enhanced_structure_display(lines: list[str], key: str, structure: dict[str, Any]) -> None:
    """Add combined JSON + paths format for structure display.

    This method implements Decision 9 from task-15-context-builder-ambiguities.md,
    providing the dual representation format that enables LLMs to generate accurate
    proxy mappings. It's used by build_component_context() when rendering detailed component context.

    Args:
        lines: List to append formatted lines to
        key: The key name (e.g., "issue_data")
        structure: The structure dict to format
    """
    lines.append("")
    lines.append("Structure (JSON format):")
    lines.append("```json")

    # Generate JSON representation
    json_struct, paths = _format_structure_combined(structure)

    # Create wrapper object with the key
    wrapper = {key: json_struct}

    # Pretty print the JSON
    json_str = json.dumps(wrapper, indent=2)
    lines.append(json_str)
    lines.append("```")
    lines.append("")

    # Add paths list
    lines.append("Available paths:")
    for path, type_str, desc in paths:
        # Prepend the key to each path
        full_path = f"{key}.{path}" if path else key
        line = f"- {full_path} ({type_str})"
        if desc:
            line += f" - {desc}"
        lines.append(line)


def _format_workflow_inputs(workflow: dict[str, Any]) -> list[str]:
    """Format workflow inputs section.

    Args:
        workflow: Workflow metadata dict

    Returns:
        List of formatted input lines
    """
    lines: list[str] = []

    # Only use IR-level inputs
    ir = workflow.get("ir", {})
    ir_inputs = ir.get("inputs", {})

    if ir_inputs:
        # Use detailed format from IR
        lines.append("**Inputs**:")
        for name, spec in ir_inputs.items():
            # Build input description
            input_desc = f"- `{name}: {spec.get('type', 'any')}`"

            # Add description if available
            if spec.get("description"):
                input_desc += f" - {spec['description']}"

            # Add optional/default info
            if not spec.get("required", True):
                if "default" in spec:
                    input_desc += f" (optional, default: {spec['default']})"
                else:
                    input_desc += " (optional)"

            lines.append(input_desc)
    else:
        lines.append("**Inputs**: none")

    lines.append("")
    return lines


def _format_workflow_outputs(workflow: dict[str, Any]) -> list[str]:
    """Format workflow outputs section.

    Args:
        workflow: Workflow metadata dict

    Returns:
        List of formatted output lines
    """
    lines: list[str] = []

    # Only use IR-level outputs
    ir = workflow.get("ir", {})
    ir_outputs = ir.get("outputs", {})

    if ir_outputs:
        # Use detailed format from IR
        lines.append("**Outputs**:")
        for name, spec in ir_outputs.items():
            # Build output description
            output_desc = f"- `{name}: {spec.get('type', 'any')}`"

            # Add description if available
            if spec.get("description"):
                output_desc += f" - {spec['description']}"

            lines.append(output_desc)
    else:
        lines.append("**Outputs**: none")

    lines.append("")
    return lines


def _format_workflow_section(workflow: dict[str, Any]) -> str:
    """Format a workflow's information for component context.

    Args:
        workflow: Workflow metadata dict

    Returns:
        Formatted markdown string for the workflow
    """
    lines = [f"### {workflow['name']} (workflow)"]

    # Add description
    description = workflow.get("description", "").strip()
    if description:
        lines.append(description)
    else:
        lines.append("No description available")
    lines.append("")

    # Format inputs
    lines.extend(_format_workflow_inputs(workflow))

    # Format outputs
    lines.extend(_format_workflow_outputs(workflow))

    # Add metadata if available
    if "version" in workflow:
        lines.append(f"**Version**: {workflow['version']}")
    if workflow.get("tags"):
        lines.append(f"**Tags**: {', '.join(workflow['tags'])}")

    lines.append("")
    return "\n".join(lines)
