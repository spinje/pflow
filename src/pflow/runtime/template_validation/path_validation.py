"""Template path existence validation (Pass 5).

Validates that template references point to real outputs — node outputs,
workflow inputs, or initial parameters. Owns both the detection logic
and all error formatting for path-related issues.
"""

import logging
from typing import Any, Optional

from pflow.registry import Registry
from pflow.runtime.template_validation.utils import (
    MAX_DISPLAYED_FIELDS,
    ValidationWarning,
    build_paths_from_entries,
    find_similar_paths,
    get_node_ids,
    sanitize_for_display,
    split_template_path,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main pass function
# ---------------------------------------------------------------------------


def validate_template_paths(
    all_templates: set[str],
    available_params: dict[str, Any],
    node_outputs: dict[str, Any],
    workflow_ir: dict[str, Any],
    registry: Registry,
) -> tuple[list[str], list[ValidationWarning]]:
    """Validate each template path exists in available sources.

    Wraps the per-template loop: for every template, checks existence
    and generates an error message if missing.

    Args:
        all_templates: Set of all template variable names found
        available_params: Parameters available from workflow inputs or CLI
        node_outputs: Pre-computed node outputs from extraction
        workflow_ir: The workflow IR
        registry: Registry instance

    Returns:
        Tuple of (errors, warnings)
    """
    errors: list[str] = []
    warnings: list[ValidationWarning] = []

    for template in sorted(all_templates):
        is_valid, warning = validate_template_path(template, available_params, node_outputs, workflow_ir, registry)

        if warning:
            warnings.append(warning)

        if not is_valid:
            error = create_template_error(template, available_params, workflow_ir, node_outputs, registry)
            errors.append(error)

    return (errors, warnings)


# ---------------------------------------------------------------------------
# Path validation (detection)
# ---------------------------------------------------------------------------


def validate_template_path(
    template: str,
    initial_params: dict[str, Any],
    node_outputs: dict[str, Any],
    workflow_ir: dict[str, Any],
    registry: Registry,
) -> tuple[bool, Optional[ValidationWarning]]:
    """Validate a template path exists in available sources.

    With namespacing enabled, we need to distinguish between:
    1. Node output references (e.g., ${node_id.output_key})
    2. Root-level references (e.g., ${input_file} or ${config.nested.path})

    Args:
        template: Template string like "var" or "var.field.subfield"
        initial_params: Parameters provided before execution
        node_outputs: Full structure info from node interfaces
        workflow_ir: The workflow IR to check for node IDs
        registry: Registry instance (passed through for consistency)

    Returns:
        Tuple of (is_valid, optional_warning)
    """
    # Use smart split to preserve dots inside nested templates like ${item.field}
    parts = split_template_path(template)
    base_var = parts[0]
    enable_namespacing = workflow_ir.get("enable_namespacing", True)

    # When namespacing is enabled, check if base_var is a node ID
    if enable_namespacing:
        node_ids = get_node_ids(workflow_ir)

        if base_var in node_ids:
            # This is a namespaced node output reference
            return validate_namespaced_output(parts, base_var, node_outputs, template)

    # Not a node ID reference (or namespacing disabled), check as root-level reference

    # Check initial_params first (higher priority)
    if base_var in initial_params:
        # For nested paths in initial_params, we can't validate at compile time
        # since values are runtime-dependent. This is a limitation.
        return (True, None)

    # Check node outputs (for backward compatibility when namespacing is disabled)
    if base_var in node_outputs:
        if len(parts) == 1:
            return (True, None)

        # Validate nested path in structure
        output_key = base_var  # For non-namespaced, base_var is the output key
        return validate_nested_path(parts[1:], node_outputs[base_var], full_template=template, output_key=output_key)

    return (False, None)


def validate_namespaced_output(
    parts: list[str],
    base_var: str,
    node_outputs: dict[str, Any],
    template: str,
) -> tuple[bool, Optional[ValidationWarning]]:
    """Validate a namespaced node output reference with array index support.

    Handles patterns like:
    - node_id.output_key
    - node_id.results[0]
    - node_id.results[0].field
    """
    if len(parts) == 1:
        # Just the node ID without output key - invalid
        return (False, None)

    # Handle array indexing: parts[1] might be "results[0]" → base="results", index=0
    output_part = parts[1]
    array_index = None
    if "[" in output_part and output_part.endswith("]"):
        bracket_pos = output_part.index("[")
        base_output = output_part[:bracket_pos]
        array_index = output_part[bracket_pos + 1 : -1]
    else:
        base_output = output_part

    node_output_key = f"{base_var}.{base_output}"
    if node_output_key not in node_outputs:
        # Dynamic workflow nodes (outputs unknown at validation time) accept any output
        is_dynamic = base_var in node_outputs and node_outputs[base_var].get("is_workflow_dynamic")
        return (True, None) if is_dynamic else (False, None)

    output_info = node_outputs[node_output_key]

    # If array access, check if output has items structure
    if array_index is not None:
        items_info = output_info.get("items", {})
        if items_info:
            # Use items structure for nested validation
            if len(parts) == 2:
                return (True, None)
            return validate_nested_path(parts[2:], items_info, full_template=template, output_key=base_output)
        # No items info but array access requested
        output_type = output_info.get("type", "any")
        # Allow if type is array (native array access)
        if output_type == "array":
            return (True, None)
        # Also allow str types - they may contain JSON that gets auto-parsed at runtime
        # This matches the behavior of check_type_allows_traversal for field access
        if output_type in ["str", "string"]:
            # Generate warning about JSON auto-parsing requirement
            nested_path = f"[{array_index}]" + (".".join(parts[2:]) if len(parts) > 2 else "")
            warning = ValidationWarning(
                template=template if template.startswith("${") else f"${{{template}}}",
                node_id=output_info.get("node_id", "unknown"),
                node_type=output_info.get("node_type", "unknown"),
                output_key=base_output,
                output_type=output_type,
                reason=(
                    f"Array access on '{output_type}' requires valid JSON array at runtime. "
                    f"Non-JSON strings cause 'Unresolved variables' error."
                ),
                nested_path=nested_path,
            )
            return (True, warning)
        return (False, None)

    if len(parts) == 2:
        return (True, None)

    # Validate deeper nested path
    return validate_nested_path(parts[2:], output_info, full_template=template, output_key=base_output)


def validate_nested_path(
    path_parts: list[str], output_info: dict[str, Any], full_template: str = "", output_key: str = ""
) -> tuple[bool, Optional[ValidationWarning]]:
    """Validate a nested path exists in the output structure.

    Args:
        path_parts: List of path components after the base variable
        output_info: Output info dict with type and structure
        full_template: Full template string for warning context
        output_key: The output key being accessed (for warning)

    Returns:
        Tuple of (is_valid, optional_warning)
    """
    current_structure = output_info.get("structure", {})

    # If no structure info, check if type allows traversal
    if not current_structure:
        output_type = output_info.get("type", "any")
        return check_type_allows_traversal(output_type, path_parts, output_info, full_template, output_key)

    # Traverse the structure
    for i, part in enumerate(path_parts):
        if part not in current_structure:
            return (False, None)

        next_item = current_structure[part]
        if isinstance(next_item, dict):
            # Check if this is a type definition or nested structure
            if "type" in next_item:
                # This is a field definition
                if i < len(path_parts) - 1:
                    # More parts to traverse
                    current_structure = next_item.get("structure", {})
                    if not current_structure:
                        # Can't traverse further unless type allows it
                        # str/string allowed for JSON auto-parsing at runtime
                        field_type = next_item.get("type", "any").lower()
                        return (field_type in ["dict", "object", "any", "str", "string"], None)
                else:
                    # This is the final part - valid
                    return (True, None)
            else:
                # Direct nested structure
                current_structure = next_item
        else:
            # Reached a leaf type string, no more traversal possible
            return (i == len(path_parts) - 1, None)

    return (True, None)


def check_type_allows_traversal(
    output_type: str, path_parts: list[str], output_info: dict[str, Any], full_template: str, output_key: str
) -> tuple[bool, Optional[ValidationWarning]]:
    """Check if output type allows traversal and generate warning if needed.

    Args:
        output_type: The output type string (may be union like "dict|str")
        path_parts: List of path components for warning context
        output_info: Output info dict for warning context
        full_template: Full template string for warning context
        output_key: The output key being accessed

    Returns:
        Tuple of (is_valid, optional_warning)
    """
    # Parse union types (e.g., "dict|str" → ["dict", "str"])
    types_in_union = [t.strip().lower() for t in output_type.split("|")]

    # Check if ANY type in the union allows traversal
    # - dict/object: structured data, traversable (trusted, no warning)
    # - any: explicit "could be anything" declaration (trusted, no warning)
    # - str/string: might contain JSON, defer to runtime via JSON auto-parsing (WARNING)
    traversable_types = [t for t in types_in_union if t in ["dict", "object", "any", "str", "string"]]

    if not traversable_types:
        return (False, None)

    # dict/object and any types are trusted - no warning needed
    # - dict/object: structured data
    # - any: node author explicitly declared "this could be anything"
    trusted_types = [t for t in traversable_types if t in ["dict", "object", "any"]]
    if trusted_types:
        # At least one trusted type - allow without warning
        return (True, None)

    # Only str/string types remain - warn about JSON auto-parsing
    # This is the "surprising" case where nested access works via implicit parsing
    string_types = [t for t in traversable_types if t in ["str", "string"]]
    warning = None

    if string_types and len(path_parts) > 0:
        warning = ValidationWarning(
            template=full_template if full_template.startswith("${") else f"${{{full_template}}}",
            node_id=output_info.get("node_id", "unknown"),
            node_type=output_info.get("node_type", "unknown"),
            output_key=output_key,
            output_type=output_type,
            reason=(
                f"Nested access on '{output_type}' requires valid JSON at runtime. "
                f"Non-JSON strings cause 'Unresolved variables' error."
            ),
            nested_path=".".join(path_parts),
        )

    return (True, warning)


# ---------------------------------------------------------------------------
# Error dispatching
# ---------------------------------------------------------------------------


def create_template_error(
    template: str,
    available_params: dict[str, Any],
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    registry: Registry,
) -> str:
    """Create appropriate error message for missing template variable.

    Args:
        template: Template variable name
        available_params: Available parameters
        workflow_ir: The workflow IR
        node_outputs: Full structure info from node interfaces
        registry: Registry instance

    Returns:
        Error message string
    """
    # Use smart split to preserve dots inside nested templates like ${item.field}
    parts = split_template_path(template)
    base_var = parts[0]
    enable_namespacing = workflow_ir.get("enable_namespacing", True)

    # Check if this is a node ID reference when namespacing is enabled
    if enable_namespacing and "." in template:
        node_ids = get_node_ids(workflow_ir)
        if base_var in node_ids:
            return _create_node_reference_error(base_var, parts, template, workflow_ir, node_outputs, registry)

    # Handle path templates (with dots)
    if "." in template:
        return _create_path_template_error(template, base_var, available_params, workflow_ir)

    # Handle simple templates
    return _create_simple_template_error(template, workflow_ir)


# ---------------------------------------------------------------------------
# Error formatting helpers (internal)
# ---------------------------------------------------------------------------


def _get_input_description(variable: str, workflow_ir: dict[str, Any]) -> str:
    """Get description for an input variable if available.

    Args:
        variable: The variable name to look up
        workflow_ir: The workflow IR containing input declarations

    Returns:
        A descriptive string with input info, or empty string if not a declared input
    """
    inputs = workflow_ir.get("inputs", {})
    if variable in inputs:
        input_def = inputs[variable]
        desc = input_def.get("description", "")
        required = input_def.get("required", True)
        default = input_def.get("default")

        parts = []
        if desc:
            parts.append(desc)
        if not required and default is not None:
            parts.append(f"(optional, default: {default})")
        elif required:
            parts.append("(required)")

        return " - " + " ".join(parts) if parts else ""
    return ""


def _create_node_reference_error(
    base_var: str,
    parts: list[str],
    template: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    registry: Registry,
) -> str:
    """Create error for node output references.

    Args:
        base_var: The base variable (node ID)
        parts: Template parts split by dot
        template: Full template string
        workflow_ir: Workflow IR
        node_outputs: Pre-computed node outputs from validation
        registry: Registry instance

    Returns:
        Error message for node reference issues
    """
    # Missing output key
    if len(parts) == 1:
        return f"Invalid template ${{{template}}} - node ID '{base_var}' requires an output key (e.g., ${{{base_var}}}.output_key)"

    output_key = parts[1]

    # Find the node to get better error message
    node = next((n for n in workflow_ir.get("nodes", []) if n.get("id") == base_var), None)
    if node:
        return _get_node_outputs_description(node, output_key, node_outputs, registry)

    return f"Node '{base_var}' does not output '{output_key}'"


def _create_path_template_error(
    template: str, base_var: str, available_params: dict[str, Any], workflow_ir: dict[str, Any]
) -> str:
    """Create error for path templates (with dots) that aren't node references.

    Args:
        template: Full template string
        base_var: Base variable name
        available_params: Available parameters
        workflow_ir: Workflow IR

    Returns:
        Error message for path template issues
    """
    if base_var in available_params:
        return f"Template path ${{{template}}} cannot be validated - initial_params values are runtime-dependent"

    # Check if base variable is a declared input
    input_desc = _get_input_description(base_var, workflow_ir)
    path_component = template[len(base_var) + 1 :]

    if input_desc:
        return (
            f"Required input '${{{base_var}}}' not provided{input_desc} - attempted to access path '{path_component}'"
        )

    enable_namespacing = workflow_ir.get("enable_namespacing", True)
    if enable_namespacing:
        return (
            f"Template variable ${{{template}}} has no valid source - "
            f"'${{{base_var}}}' is neither a workflow input nor a node ID in this workflow"
        )
    else:
        return (
            f"Template variable ${{{template}}} has no valid source - "
            f"not provided in initial_params and path '{path_component}' "
            f"not found in outputs from any node in the workflow"
        )


def _create_simple_template_error(template: str, workflow_ir: dict[str, Any]) -> str:
    """Create error for simple templates without dots.

    Args:
        template: Template variable name
        workflow_ir: Workflow IR

    Returns:
        Error message for simple template issues
    """
    input_desc = _get_input_description(template, workflow_ir)

    if input_desc:
        return f"Required input '${{{template}}}' not provided{input_desc}"

    # Check if it might be a node ID used incorrectly
    enable_namespacing = workflow_ir.get("enable_namespacing", True)
    if enable_namespacing:
        node_ids = get_node_ids(workflow_ir)
        if template in node_ids:
            return (
                f"Invalid template ${{{template}}} - this is a node ID. "
                f"To reference node outputs, use ${{{template}}}.output_key format"
            )

    return (
        f"Template variable ${{{template}}} has no valid source - "
        f"not provided in initial_params and not written by any node"
    )


def format_enhanced_node_error(
    node_id: str, node_type: str, attempted_key: str, available_paths: list[tuple[str, str]], base_var: str
) -> str:
    """Create multi-section error with available outputs and suggestions.

    Args:
        node_id: Node ID where error occurred
        node_type: Type of the node
        attempted_key: The output key that was attempted
        available_paths: List of (path, type) tuples
        base_var: Base variable (node ID) for template construction

    Returns:
        Multi-line error message with sections for problem, available outputs, and suggestions
    """
    # Sanitize all user-controlled values to prevent template injection
    safe_node_id = sanitize_for_display(node_id)
    safe_node_type = sanitize_for_display(node_type)
    safe_attempted_key = sanitize_for_display(attempted_key)
    safe_base_var = sanitize_for_display(base_var)

    # Section 1: Problem statement
    lines = [f"Node '{safe_node_id}' (type: {safe_node_type}) does not output '{safe_attempted_key}'"]

    # Section 2: Available outputs (limit to 20 to avoid overwhelming)
    if available_paths:
        lines.append("")
        lines.append(f"Available outputs from '{safe_node_id}':")

        display_paths = available_paths[:MAX_DISPLAYED_FIELDS]  # Limit display
        for path, type_str in display_paths:
            # Sanitize path components for safety
            safe_path = sanitize_for_display(path)
            safe_type = sanitize_for_display(type_str)

            # Format with checkmark and type
            full_path = f"{safe_base_var}.{safe_path}" if safe_base_var not in safe_path else safe_path
            lines.append(f"  \u2713 ${{{full_path}}} ({safe_type})")

        # Show truncation message if needed
        if len(available_paths) > 20:
            remaining = len(available_paths) - 20
            lines.append(f"  ... and {remaining} more outputs")

    # Section 3: Suggestions (find similar paths)
    suggestions = find_similar_paths(attempted_key, available_paths)
    if suggestions:
        lines.append("")
        if len(suggestions) == 1:
            sugg_path, _ = suggestions[0]
            safe_sugg_path = sanitize_for_display(sugg_path)
            full_sugg = f"{safe_base_var}.{safe_sugg_path}" if safe_base_var not in safe_sugg_path else safe_sugg_path
            lines.append(f"Did you mean: ${{{full_sugg}}}?")
        else:
            lines.append("Did you mean one of these?")
            for sugg_path, _ in suggestions:
                safe_sugg_path = sanitize_for_display(sugg_path)
                full_sugg = (
                    f"{safe_base_var}.{safe_sugg_path}" if safe_base_var not in safe_sugg_path else safe_sugg_path
                )
                lines.append(f"  - ${{{full_sugg}}}")

    # Section 4: Common fix (use first suggestion if available, otherwise first available path)
    if suggestions:
        fix_path, _ = suggestions[0]
        full_fix = f"{base_var}.{fix_path}" if base_var not in fix_path else fix_path
        lines.append("")
        lines.append(f"Common fix: Change ${{{base_var}.{attempted_key}}} to ${{{full_fix}}}")
    elif available_paths:
        # No suggestions, but we have paths - suggest the first one as generic fix
        first_path, _ = available_paths[0]
        full_first = f"{base_var}.{first_path}" if base_var not in first_path else first_path
        lines.append("")
        lines.append(f"Tip: Try using ${{{full_first}}} instead")

    return "\n".join(lines)


def _get_node_outputs_description(
    node: dict[str, Any], output_key: str, node_outputs: dict[str, Any], registry: Registry
) -> str:
    """Get error message for missing node output with enhanced suggestions.

    Uses the pre-computed node_outputs dict (same source of truth as validation)
    to build accurate error messages. For batch nodes, detects whether the
    attempted key exists in the inner node's interface and provides targeted guidance.

    Args:
        node: Node dictionary from workflow IR
        output_key: The output key being accessed
        node_outputs: Pre-computed node outputs from validation
        registry: Registry instance for metadata lookup (fallback only)

    Returns:
        Error message describing what outputs are available with suggestions
    """
    node_type = node.get("type", "unknown")
    node_id = node.get("id")
    node_id_str = str(node_id) if node_id else "unknown"

    # Build available paths from pre-computed node_outputs (single source of truth)
    node_prefix = f"{node_id_str}."
    node_entries = {k[len(node_prefix) :]: v for k, v in node_outputs.items() if k.startswith(node_prefix)}

    if not node_entries:
        # Fallback to registry if node_outputs has no entries (shouldn't happen)
        return _get_node_outputs_from_registry(node, output_key, registry)

    # Detect batch: check if any entry has is_batch_output flag
    is_batch = any(entry.get("is_batch_output") for entry in node_entries.values())

    if is_batch:
        return _create_batch_error(node_id_str, node_type, output_key, node_entries)

    # Non-batch node: build available paths and use standard error formatter
    all_paths = build_paths_from_entries(node_entries)

    if all_paths:
        return format_enhanced_node_error(
            node_id=node_id_str,
            node_type=node_type,
            attempted_key=output_key,
            available_paths=all_paths,
            base_var=node_id_str,
        )

    return f"Node '{node_id_str}' (type: {node_type}) does not produce any outputs"


def _get_node_outputs_from_registry(node: dict[str, Any], output_key: str, registry: Registry) -> str:
    """Fallback when node_outputs has no entries for a node.

    This is a defensive fallback that should not be reached in practice —
    _extract_node_outputs() runs before error generation and registers
    outputs for all nodes. Intentionally simple to avoid re-introducing
    the registry-vs-batch divergence bug.
    """
    node_id = node.get("id", "unknown")
    logger.warning(
        f"node_outputs fallback reached for node '{node_id}' — this is unexpected",
        extra={"node_id": node_id, "output_key": output_key},
    )
    return f"Node '{node_id}' does not output '{output_key}'"


def _create_batch_error(node_id: str, node_type: str, attempted_key: str, node_entries: dict[str, Any]) -> str:
    """Create error message for batch node output access.

    Two cases:
    1. The attempted key exists in the inner node's interface (e.g., llm_usage for LLM nodes)
       → Show targeted "exists inside results" message with corrected path
    2. The attempted key doesn't exist at all
       → Show standard "not found" with actual batch outputs

    Args:
        node_id: Node ID
        node_type: Inner node type (e.g., "llm")
        attempted_key: The output key that was attempted
        node_entries: Dict of output_key -> output_info for this batch node

    Returns:
        Error message string
    """
    safe_node_id = sanitize_for_display(node_id)
    safe_key = sanitize_for_display(attempted_key)

    # Check if the attempted key exists in the inner node's output structure
    # The results entry has items.structure containing inner outputs
    results_entry = node_entries.get("results", {})
    items_info = results_entry.get("items", {})
    inner_structure = items_info.get("structure", {}) if isinstance(items_info, dict) else {}

    inner_field_exists = attempted_key in inner_structure

    if inner_field_exists:
        return _format_batch_inner_field_error(safe_node_id, safe_key, node_entries)

    # Field doesn't exist in inner interface either — show standard batch outputs
    all_paths = build_paths_from_entries(node_entries)
    return format_enhanced_node_error(
        node_id=safe_node_id,
        node_type=f"{node_type}, batch",
        attempted_key=attempted_key,
        available_paths=all_paths,
        base_var=safe_node_id,
    )


def _format_batch_inner_field_error(node_id: str, attempted_key: str, node_entries: dict[str, Any]) -> str:
    """Format error for accessing an inner node field on a batch node.

    This is the targeted message shown when an agent writes ${node.llm_usage}
    but the node has batch processing — the field exists, just nested inside results.

    Args:
        node_id: Sanitized node ID
        attempted_key: Sanitized output key that was attempted
        node_entries: Dict of output_key -> output_info for this batch node

    Returns:
        Multi-line error message with corrected path
    """
    results_path = f"${{{node_id}.results}}"
    item_path = f"${{{node_id}.results[0].{attempted_key}}}"
    col_width = max(len(results_path), len(item_path)) + 2

    lines = [
        f"Node '{node_id}' uses batch processing.",
        f"'{attempted_key}' is not available at the top level — batch wraps outputs in a 'results' array.",
        "",
        f"  {results_path:<{col_width}} \u2192 list of all results",
        f"  {item_path:<{col_width}} \u2192 first item's {attempted_key}",
        "",
        f"To aggregate across items, pass {results_path} to a code node and iterate.",
    ]

    # Also show all actual batch outputs for reference
    lines.append("")
    lines.append(f"Available top-level outputs from '{node_id}':")
    for key, info in node_entries.items():
        safe_key = sanitize_for_display(key)
        safe_type = sanitize_for_display(info.get("type", "any"))
        lines.append(f"  \u2713 ${{{node_id}.{safe_key}}} ({safe_type})")

    return "\n".join(lines)
