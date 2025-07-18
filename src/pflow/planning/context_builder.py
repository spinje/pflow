"""Context builder for LLM-based workflow planning.

This module transforms node registry metadata into LLM-optimized markdown
documentation that enables natural language workflow composition.
"""

import importlib
import json
import logging
import os
import types
from pathlib import Path
from typing import Any, Optional

from pflow.registry.metadata_extractor import PflowMetadataExtractor

logger = logging.getLogger(__name__)

# Constants
MAX_OUTPUT_SIZE = 200000  # 200KB limit for LLM context (increased for detailed format)
MAX_STRUCTURE_HINTS = 100  # Increased limit for structure display


# TODO: Function complexity warning (C901) is suppressed but valid
# Consider refactoring into smaller functions:
# - _validate_inputs()
# - _process_single_node()
# - _build_markdown_output()
def _process_nodes(registry_metadata: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int]:
    """Process registry metadata to extract and enrich node information.

    Args:
        registry_metadata: Dict mapping node types to metadata dicts

    Returns:
        Tuple of (processed nodes dict, skipped count)
    """

    extractor = PflowMetadataExtractor()
    processed_nodes = {}
    skipped_count = 0
    module_cache: dict[str, types.ModuleType] = {}  # Cache imported modules for performance

    for node_type, node_info in registry_metadata.items():
        # Skip test nodes
        file_path = node_info.get("file_path", "")
        # TODO: Consider more sophisticated test detection:
        # - Check for __pycache__ directories
        # - Skip .pyc files
        # - Maybe check class name patterns (TestNode, MockNode, etc.)
        if "test" in file_path.lower():
            logger.debug(f"context: Skipping test node: {node_type}")
            skipped_count += 1
            continue

        # Phase 2: Import and metadata extraction
        try:
            # Import the node class using module path and class name
            # NOTE: Not using import_node_class() from runtime.compiler because:
            # 1. It requires a Registry instance, not a dict
            # 2. We already have the module path and class name
            # 3. This approach is simpler and avoids unnecessary dependencies
            module_path = node_info.get("module")
            class_name = node_info.get("class_name")

            if not module_path or not class_name:
                logger.warning(f"context: Missing module or class_name for node '{node_type}'")
                skipped_count += 1
                continue

            # Use cached module if available
            if module_path in module_cache:
                module = module_cache[module_path]
            else:
                module = importlib.import_module(module_path)
                module_cache[module_path] = module

            node_class = getattr(module, class_name)

            # Extract metadata
            # TODO: Future optimization - cache extracted metadata to disk
            # This is the main performance bottleneck for large registries
            metadata = extractor.extract_metadata(node_class)

            # Store successful extraction
            processed_nodes[node_type] = {
                "description": metadata.get("description", "No description"),
                "inputs": metadata.get("inputs", []),
                "outputs": metadata.get("outputs", []),
                "params": metadata.get("params", []),
                "actions": metadata.get("actions", []),
                "registry_info": node_info,
            }

        except ImportError as e:
            logger.warning(f"context: Failed to import module for node '{node_type}' (module: {module_path}): {e}")
            skipped_count += 1
            continue
        except AttributeError as e:
            logger.warning(
                f"context: Failed to find class '{class_name}' in module '{module_path}' for node '{node_type}': {e}"
            )
            skipped_count += 1
            continue
        except Exception as e:
            logger.warning(f"context: Unexpected error processing node '{node_type}': {type(e).__name__}: {e}")
            skipped_count += 1
            continue

    return processed_nodes, skipped_count


def build_context(registry_metadata: dict[str, dict[str, Any]]) -> str:
    """Build LLM-friendly context from registry metadata.

    Args:
        registry_metadata: Dict mapping node types to metadata dicts
                          (as returned by Registry.load())

    Returns:
        Formatted markdown string describing available nodes
    """
    # Input validation
    if registry_metadata is None:
        raise ValueError("registry_metadata cannot be None")
    if not isinstance(registry_metadata, dict):
        raise TypeError(f"registry_metadata must be a dict, got {type(registry_metadata).__name__}")

    # Process nodes to extract metadata
    processed_nodes, skipped_count = _process_nodes(registry_metadata)

    # Group by category
    categories = _group_nodes_by_category(processed_nodes)

    # Phase 4: Format as markdown
    markdown_sections = []

    for category, nodes in sorted(categories.items()):
        markdown_sections.append(f"## {category}\n")

        for node_type in sorted(nodes):
            node_data = processed_nodes[node_type]
            section = _format_node_section(node_type, node_data)
            markdown_sections.append(section)

    # Log summary
    total_nodes = len(registry_metadata)
    processed_count = len(processed_nodes)
    logger.info(f"context: Processed {processed_count}/{total_nodes} nodes ({skipped_count} skipped)")

    output = "\n".join(markdown_sections)
    output_size = len(output)

    # Truncate if output exceeds limit
    if output_size > MAX_OUTPUT_SIZE:
        logger.warning(f"context: Output truncated from {output_size} to {MAX_OUTPUT_SIZE} bytes")
        # TODO: Consider smarter truncation that respects node boundaries
        # Current approach might cut off in the middle of a node description
        # Better approach: track size while building and stop adding complete nodes
        output = output[:MAX_OUTPUT_SIZE] + "\n\n... (truncated)"
    elif output_size > 10000:  # 10KB warning threshold
        logger.warning(f"context: Large output size: {output_size} bytes")

    return output


def _extract_navigation_paths(
    structure: dict[str, Any], prefix: str = "", max_depth: int = 3, current_depth: int = 0
) -> list[str]:
    """Extract navigation paths from structure dict.

    Args:
        structure: Dict containing field definitions with optional nested structures
        prefix: Path prefix for recursive calls
        max_depth: Maximum depth to include in paths (default 3 for 3 levels)
        current_depth: Current recursion depth

    Returns:
        List of navigation paths (e.g., ["number", "user.login", "user.id"])
    """
    paths: list[str] = []
    if current_depth >= max_depth or not isinstance(structure, dict):
        return paths

    for field_name, field_info in structure.items():
        # Build the current path
        current_path = f"{prefix}.{field_name}" if prefix else field_name
        paths.append(current_path)

        # Recurse for nested structures if they exist
        if isinstance(field_info, dict) and "structure" in field_info:
            nested_structure = field_info["structure"]
            if isinstance(nested_structure, dict):
                nested_paths = _extract_navigation_paths(nested_structure, current_path, max_depth, current_depth + 1)
                # Limit nested paths to prevent explosion
                paths.extend(nested_paths[:5])

    # Limit total paths to keep output manageable
    return paths[:10]


def _format_structure(structure: dict[str, Any], indent_level: int = 2) -> list[str]:
    """Format nested structure with descriptions in hierarchical format.

    Args:
        structure: Dict containing field definitions with nested structures
        indent_level: Current indentation level (2 spaces per level)

    Returns:
        List of formatted lines showing structure hierarchy
    """
    lines = []
    indent = "  " * indent_level

    for field_name, field_info in structure.items():
        if isinstance(field_info, dict):
            type_str = field_info.get("type", "any")
            desc = field_info.get("description", "")

            # Format: "- field: type - description"
            line = f"{indent}- {field_name}: {type_str}"
            if desc:
                line += f" - {desc}"
            lines.append(line)

            # Recurse for nested structures
            if "structure" in field_info and isinstance(field_info["structure"], dict):
                nested_lines = _format_structure(field_info["structure"], indent_level + 1)
                lines.extend(nested_lines)

    return lines


def _group_nodes_by_category(nodes: dict[str, dict]) -> dict[str, list[str]]:
    """Group nodes by category based on simple pattern matching."""
    categories: dict[str, list[str]] = {}

    for node_type in nodes:
        # Simple pattern matching for categories
        if "file" in node_type or "read" in node_type or "write" in node_type:
            category = "File Operations"
        elif "llm" in node_type or "ai" in node_type:
            category = "AI/LLM Operations"
        elif "git" in node_type or "github" in node_type or "gitlab" in node_type:
            category = "Git Operations"
        elif "http" in node_type or "api" in node_type:
            category = "HTTP/API Operations"
        else:
            category = "General Operations"

        if category not in categories:
            categories[category] = []
        categories[category].append(node_type)

    return categories


def _validate_workflow_fields(workflow_data: dict[str, Any], filename: str) -> bool:
    """Validate required fields and types in workflow data.

    Args:
        workflow_data: The parsed workflow JSON data
        filename: Name of the file for error messages

    Returns:
        True if all validations pass, False otherwise
    """
    # Validate required fields presence
    required_fields = ["name", "description", "inputs", "outputs", "ir"]
    missing_fields = [field for field in required_fields if field not in workflow_data]

    if missing_fields:
        logger.warning(f"Workflow file {filename} missing required fields: {missing_fields}")
        return False

    # Validate field types
    validations = [
        ("name", str, "string"),
        ("description", str, "string"),
        ("inputs", list, "list"),
        ("outputs", list, "list"),
        ("ir", dict, "dict"),
    ]

    for field_name, expected_type, type_name in validations:
        if not isinstance(workflow_data[field_name], expected_type):
            logger.warning(f"Invalid '{field_name}' type in {filename}: expected {type_name}")
            return False

    return True


def _load_single_workflow(json_file: Path) -> Optional[dict[str, Any]]:
    """Load and validate a single workflow file.

    Args:
        json_file: Path to the JSON file

    Returns:
        Workflow data dict if valid, None otherwise
    """
    try:
        # Read and parse JSON
        content = json_file.read_text()

        # Handle empty files
        if not content.strip():
            logger.warning(f"Workflow file is empty: {json_file.name}")
            return None

        workflow_data = json.loads(content)

        # Validate the workflow
        if not _validate_workflow_fields(workflow_data, json_file.name):
            return None

        logger.debug(f"Loaded workflow '{workflow_data['name']}' from {json_file.name}")
        return workflow_data  # type: ignore[no-any-return]

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON from {json_file.name}: {e}")
        return None
    except PermissionError:
        logger.warning(f"Permission denied reading {json_file.name}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error reading {json_file.name}: {type(e).__name__}: {e}")
        return None


def _load_saved_workflows() -> list[dict[str, Any]]:
    """Load all workflow JSON files from ~/.pflow/workflows/ directory.

    Creates the directory if it doesn't exist. Skips invalid files with warnings.

    Returns:
        List of workflow metadata dicts with at least:
        - name: str
        - description: str
        - inputs: list[str]
        - outputs: list[str]
        - ir: dict (full workflow IR)

        Additional fields preserved if present:
        - ir_version, version, tags, created_at, updated_at
    """
    workflows_dir = Path.home() / ".pflow" / "workflows"

    # Create directory if it doesn't exist
    try:
        os.makedirs(workflows_dir, exist_ok=True)
        logger.debug(f"Ensured workflow directory exists at {workflows_dir}")
    except Exception as e:
        logger.warning(f"Failed to create workflow directory: {e}")
        return []

    # Check if directory is accessible
    if not workflows_dir.exists() or not workflows_dir.is_dir():
        logger.debug("Workflow directory does not exist or is not a directory")
        return []

    workflows = []

    try:
        # List all JSON files in the directory
        json_files = list(workflows_dir.glob("*.json"))

        if not json_files:
            logger.debug("No workflow JSON files found")
            return []

        logger.debug(f"Found {len(json_files)} JSON files to process")

        # Process each JSON file
        for json_file in json_files:
            workflow_data = _load_single_workflow(json_file)
            if workflow_data:
                workflows.append(workflow_data)

    except Exception as e:
        logger.warning(f"Error listing workflow files: {type(e).__name__}: {e}")
        return []

    logger.info(f"Loaded {len(workflows)} workflows from {workflows_dir}")
    return workflows


def _format_node_section(node_type: str, node_data: dict) -> str:  # noqa: C901
    """Format a single node's information as markdown with full structure details.

    Args:
        node_type: The type/name of the node
        node_data: Node metadata dictionary

    Returns:
        Formatted markdown string for the node
    """
    lines = [f"### {node_type}"]

    # Handle missing or empty description gracefully
    description = node_data.get("description", "").strip()
    if not description:
        description = "No description available"
    lines.append(description)
    lines.append("")

    # Format inputs (handle both string list and rich format)
    inputs = node_data["inputs"]
    if inputs:
        formatted_inputs = []
        structures_to_display = []  # Complex types that need structure sections

        for inp in inputs:
            # Handle rich format (dict) or simple format (string)
            if isinstance(inp, dict):
                key = inp["key"]
                type_str = inp.get("type", "any")
                desc = inp.get("description", "")

                # Format: key: type - description
                input_str = f"`{key}: {type_str}`" if type_str != "any" else f"`{key}`"

                if desc:
                    input_str += f" - {desc}"

                formatted_inputs.append(input_str)

                # Track complex types for structure display
                if type_str in ("dict", "list", "list[dict]") and "structure" in inp:
                    structures_to_display.append((key, inp["structure"]))
            else:
                # Backward compatibility for string format
                formatted_inputs.append(f"`{inp}`")

        lines.append(f"**Inputs**: {', '.join(formatted_inputs)}")

        # Add structure sections for complex inputs
        for key, structure in structures_to_display:
            lines.append(f"  Structure of {key}:")
            structure_lines = _format_structure(structure)
            lines.extend(structure_lines)
    else:
        lines.append("**Inputs**: none")

    # Format outputs with actions (handle both string list and rich format)
    outputs = node_data["outputs"]
    actions = node_data["actions"]
    if outputs:
        formatted_outputs = []
        structures_to_display = []  # Complex types that need structure sections

        for i, out in enumerate(outputs):
            # Handle rich format (dict) or simple format (string)
            if isinstance(out, dict):
                key = out["key"]
                type_str = out.get("type", "any")
                desc = out.get("description", "")

                # Format: key: type - description
                output_str = f"`{key}: {type_str}`" if type_str != "any" else f"`{key}`"

                if desc:
                    output_str += f" - {desc}"

                # Map outputs to actions if possible
                if i < len(actions) and actions[i] != "default":
                    output_str += f" ({actions[i]})"

                formatted_outputs.append(output_str)

                # Track complex types for structure display
                if type_str in ("dict", "list", "list[dict]") and "structure" in out:
                    structures_to_display.append((key, out["structure"]))
            else:
                # Backward compatibility for string format
                output_str = f"`{out}`"
                # Map outputs to actions if possible
                if i < len(actions) and actions[i] != "default":
                    output_str += f" ({actions[i]})"
                formatted_outputs.append(output_str)

        lines.append(f"**Outputs**: {', '.join(formatted_outputs)}")

        # Add structure sections for complex outputs
        for key, structure in structures_to_display:
            lines.append(f"  Structure of {key}:")
            structure_lines = _format_structure(structure)
            lines.extend(structure_lines)
    else:
        lines.append("**Outputs**: none")

    # Format exclusive parameters (params not in inputs)
    params = node_data["params"]
    # Build input keys set for exclusion check
    input_keys = set()
    for inp in inputs:
        if isinstance(inp, dict):
            input_keys.add(inp["key"])
        else:
            input_keys.add(inp)

    exclusive_params = []
    structures_to_display = []  # Complex params that need structure sections

    for param in params:
        # Handle rich format (dict) or simple format (string)
        if isinstance(param, dict):
            key = param["key"]
            if key not in input_keys:
                type_str = param.get("type", "any")
                desc = param.get("description", "")

                # Format: key: type - description
                param_str = f"`{key}: {type_str}`" if type_str != "any" else f"`{key}`"

                if desc:
                    param_str += f" - {desc}"

                exclusive_params.append(param_str)

                # Track complex types for structure display (rare for params)
                if type_str in ("dict", "list", "list[dict]") and "structure" in param:
                    structures_to_display.append((key, param["structure"]))
        else:
            # Backward compatibility for string format
            if param not in input_keys:
                exclusive_params.append(f"`{param}`")

    if exclusive_params:
        lines.append(f"**Parameters**: {', '.join(exclusive_params)}")

        # Add structure sections for complex params
        for key, structure in structures_to_display:
            lines.append(f"  Structure of {key}:")
            structure_lines = _format_structure(structure)
            lines.extend(structure_lines)
    else:
        lines.append("**Parameters**: none")

    lines.append("")  # Empty line between nodes
    return "\n".join(lines)


def _format_structure_combined(
    structure: dict[str, Any], parent_path: str = ""
) -> tuple[dict[str, Any], list[tuple[str, str, str]]]:
    """Transform nested structure into JSON representation and path list.

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


def build_discovery_context(
    node_ids: Optional[list[str]] = None,
    workflow_names: Optional[list[str]] = None,
    registry_metadata: Optional[dict[str, dict[str, Any]]] = None,
) -> str:
    """Build lightweight discovery context with names and descriptions only.

    This function provides a browsing-friendly view of available components,
    helping the planner understand what's available without overwhelming detail.

    Args:
        node_ids: List of node IDs to include (None = all nodes)
        workflow_names: List of workflow names to include (None = all workflows)
        registry_metadata: Optional registry metadata dict. If not provided,
                          will attempt to load from default registry.

    Returns:
        Markdown formatted discovery context showing names and descriptions
    """
    # Get registry metadata if not provided
    if registry_metadata is None:
        from pflow.registry import Registry

        registry = Registry()
        registry_metadata = registry.load()

    # Process nodes to get metadata
    processed_nodes, _ = _process_nodes(registry_metadata)

    # Filter nodes if specific IDs provided
    if node_ids is not None:
        filtered_nodes = {nid: data for nid, data in processed_nodes.items() if nid in node_ids}
    else:
        filtered_nodes = processed_nodes

    # Group nodes by category
    categories = _group_nodes_by_category(filtered_nodes)

    # Load workflows
    saved_workflows = _load_saved_workflows()

    # Filter workflows if specific names provided
    if workflow_names is not None:
        filtered_workflows = [w for w in saved_workflows if w["name"] in workflow_names]
    else:
        filtered_workflows = saved_workflows

    # Build markdown sections
    markdown_sections = ["## Available Nodes\n"]

    # Add nodes by category (lightweight format)
    for category, nodes in sorted(categories.items()):
        markdown_sections.append(f"### {category}")
        for node_id in sorted(nodes):
            node_data = filtered_nodes[node_id]
            markdown_sections.append(f"### {node_id}")

            # Only show description, omit if missing
            description = node_data.get("description", "").strip()
            if description and description != "No description":
                markdown_sections.append(description)

            markdown_sections.append("")  # Empty line

    # Add workflows section
    if filtered_workflows:
        markdown_sections.append("## Available Workflows\n")
        for workflow in sorted(filtered_workflows, key=lambda w: w["name"]):
            markdown_sections.append(f"### {workflow['name']} (workflow)")

            # Only show description, omit if missing
            description = workflow.get("description", "").strip()
            if description:
                markdown_sections.append(description)

            markdown_sections.append("")  # Empty line

    return "\n".join(markdown_sections).strip()


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


def build_planning_context(
    selected_node_ids: list[str],
    selected_workflow_names: list[str],
    registry_metadata: dict[str, dict[str, Any]],
    saved_workflows: Optional[list[dict[str, Any]]] = None,
) -> str | dict[str, Any]:
    """Build detailed planning context for selected components.

    This function provides complete interface details for components selected
    during the discovery phase, enabling accurate workflow generation.

    Args:
        selected_node_ids: Node IDs to include (required)
        selected_workflow_names: Workflow names to include (required)
        registry_metadata: Full registry metadata dict
        saved_workflows: Pre-loaded workflow list (optional, will load if None)

    Returns:
        Either:
        - Markdown formatted planning context with full details
        - Error dict with keys: "error", "missing_nodes", "missing_workflows"
    """
    # Load workflows if not provided
    if saved_workflows is None:
        saved_workflows = _load_saved_workflows()

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

    # Add detailed node information with enhanced structure display
    for node_id in sorted(selected_node_ids):
        if node_id in processed_nodes:
            node_data = processed_nodes[node_id]
            section = _format_node_section_enhanced(node_id, node_data)
            markdown_sections.append(section)

    # Add detailed workflow information
    selected_workflows = [w for w in saved_workflows if w["name"] in selected_workflow_names]
    if selected_workflows:
        markdown_sections.append("## Selected Workflows\n")
        for workflow in sorted(selected_workflows, key=lambda w: w["name"]):
            section = _format_workflow_section(workflow)
            markdown_sections.append(section)

    return "\n".join(markdown_sections).strip()


def _format_exclusive_parameters(node_data: dict, inputs: list, lines: list[str]) -> None:
    """Format parameters that are not in inputs (exclusive params).

    Args:
        node_data: Node metadata containing params
        inputs: List of inputs to exclude from params
        lines: List to append formatted lines to
    """
    params = node_data["params"]
    input_keys = set()
    for inp in inputs:
        if isinstance(inp, dict):
            input_keys.add(inp["key"])
        else:
            input_keys.add(inp)

    exclusive_params = []
    for param in params:
        if isinstance(param, dict):
            key = param["key"]
            if key not in input_keys:
                type_str = param.get("type", "any")
                desc = param.get("description", "")

                line = f"- `{key}: {type_str}`"
                if desc:
                    line += f" - {desc}"
                exclusive_params.append(line)
        else:
            if param not in input_keys:
                exclusive_params.append(f"- `{param}`")

    if exclusive_params:
        lines.append("**Parameters**:")
        lines.extend(exclusive_params)
    else:
        lines.append("**Parameters**: none")


def _format_interface_item(item: dict | str, item_type: str, lines: list[str]) -> None:
    """Format a single interface item (input/output/param).

    Args:
        item: The item to format (dict or string)
        item_type: Type of item ("input", "output", "param")
        lines: List to append formatted lines to
    """
    if isinstance(item, dict):
        key = item["key"]
        type_str = item.get("type", "any")
        desc = item.get("description", "")

        line = f"- `{key}: {type_str}`"
        if desc:
            line += f" - {desc}"
        lines.append(line)

        # Enhanced structure display for complex types
        if type_str in ("dict", "list", "list[dict]") and "structure" in item:
            _add_enhanced_structure_display(lines, key, item["structure"])
    else:
        lines.append(f"- `{item}`")


def _format_node_section_enhanced(node_type: str, node_data: dict) -> str:
    """Format a node with enhanced structure display (JSON + paths).

    This is similar to _format_node_section but uses the combined
    structure format for complex types.

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

    # Format inputs
    inputs = node_data["inputs"]
    if inputs:
        lines.append("**Inputs**:")
        for inp in inputs:
            _format_interface_item(inp, "input", lines)
    else:
        lines.append("**Inputs**: none")

    lines.append("")

    # Format outputs
    outputs = node_data["outputs"]
    if outputs:
        lines.append("**Outputs**:")
        for out in outputs:
            _format_interface_item(out, "output", lines)
    else:
        lines.append("**Outputs**: none")

    lines.append("")

    # Format exclusive parameters
    _format_exclusive_parameters(node_data, inputs, lines)

    lines.append("")
    return "\n".join(lines)


def _add_enhanced_structure_display(lines: list[str], key: str, structure: dict[str, Any]) -> None:
    """Add combined JSON + paths format for structure display.

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
    import json

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


def _format_workflow_section(workflow: dict[str, Any]) -> str:
    """Format a workflow's information for planning context.

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
    inputs = workflow.get("inputs", [])
    if inputs:
        lines.append("**Inputs**:")
        for inp in inputs:
            lines.append(f"- `{inp}`")
    else:
        lines.append("**Inputs**: none")
    lines.append("")

    # Format outputs
    outputs = workflow.get("outputs", [])
    if outputs:
        lines.append("**Outputs**:")
        for out in outputs:
            lines.append(f"- `{out}`")
    else:
        lines.append("**Outputs**: none")
    lines.append("")

    # Add metadata if available
    if "version" in workflow:
        lines.append(f"**Version**: {workflow['version']}")
    if workflow.get("tags"):
        lines.append(f"**Tags**: {', '.join(workflow['tags'])}")

    lines.append("")
    return "\n".join(lines)
