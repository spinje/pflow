"""Shared formatters for node execution output.

This module provides formatting functions for displaying node execution results
across CLI and MCP interfaces. All formatters return strings or structured data
instead of printing directly, allowing different consumers to handle display.

Usage:
    >>> from pflow.execution.formatters.node_output_formatter import format_node_output
    >>> result = format_node_output(
    ...     node_type="shell",
    ...     action="default",
    ...     outputs={"stdout": "hello"},
    ...     shared_store={},
    ...     execution_time_ms=45,
    ...     registry=Registry(),
    ...     format_type="text",
    ... )
    >>> print(result)
    ✓ Node executed successfully
    ...
"""

import json
from typing import Any, Optional

from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.template_validator import TemplateValidator

# Constants
MAX_DISPLAYED_FIELDS = 500  # Allow up to 500 template paths

# Smart output truncation thresholds
SMART_MAX_STRING_LENGTH = 200  # Truncate strings longer than this
SMART_MAX_DICT_KEYS = 5  # Show summary for dicts with more keys
SMART_MAX_LIST_ITEMS = 5  # Show summary for lists with more items

# Sentinel to distinguish "path not found" from actual None value
_NOT_FOUND = object()


def _resolve_template_value(path: str, outputs: dict[str, Any], shared_store: dict[str, Any]) -> Any:
    """Resolve a template path to its actual value.

    Returns _NOT_FOUND sentinel if path doesn't exist in either dict,
    allowing distinction between "not found" and legitimate None values.
    """
    value = TemplateResolver.resolve_value(path, outputs)
    if value is not None:
        return value
    # Value is None - check shared_store as fallback
    value = TemplateResolver.resolve_value(path, shared_store)
    if value is not None:
        return value
    # Both returned None - but is None the actual value or path not found?
    # Check if path exists in either dict by looking for the root key
    root_key = path.split(".")[0].split("[")[0]
    if root_key in outputs or root_key in shared_store:
        # Path root exists, so None is the actual value
        return None
    return _NOT_FOUND


def format_node_output(
    node_type: str,
    action: str,
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    execution_time_ms: int,
    registry: Registry,
    format_type: str = "text",
    verbose: bool = False,
    execution_id: Optional[str] = None,
    output_mode: str = "smart",
) -> str | dict[str, Any]:
    """Format node execution results for display.

    This is the main entry point for formatting node outputs. It delegates to
    specific formatters based on format_type and action.

    Args:
        node_type: Node type identifier
        action: Node execution action ("default", "error", etc.)
        outputs: Node output dictionary
        shared_store: Complete shared store
        execution_time_ms: Execution duration in milliseconds
        registry: Registry instance for metadata
        format_type: Output format - "text", "json", "structure"
        verbose: Include verbose details (for text mode)
        execution_id: Optional execution ID for field retrieval
        output_mode: For structure format - "smart", "structure", or "full"

    Returns:
        - str for text/structure modes
        - dict for json mode

    Example:
        >>> result = format_node_output(
        ...     node_type="shell",
        ...     action="default",
        ...     outputs={"stdout": "hello", "exit_code": 0},
        ...     shared_store={},
        ...     execution_time_ms=45,
        ...     registry=Registry(),
        ...     format_type="text",
        ... )
        >>> "✓ Node executed successfully" in result
        True
    """
    # Handle errors
    if action == "error":
        error_msg = shared_store.get("error", "Unknown error")
        if format_type == "json":
            return format_json_error(node_type, error_msg, execution_time_ms)
        else:
            return format_text_error(node_type, error_msg, execution_time_ms)

    # Handle success cases
    if format_type == "structure":
        return format_structure_output(
            node_type,
            outputs,
            shared_store,
            registry,
            execution_time_ms,
            verbose,
            execution_id=execution_id,
            output_mode=output_mode,
        )
    elif format_type == "json":
        return format_json_output(node_type, outputs, execution_time_ms)
    else:  # text
        return format_text_output(node_type, outputs, execution_time_ms, action, verbose)


def format_text_output(
    node_type: str, outputs: dict[str, Any], execution_time_ms: int, action: str, verbose: bool
) -> str:
    """Format results in human-readable text format.

    Args:
        node_type: Node type identifier
        outputs: Node output dictionary
        execution_time_ms: Execution duration
        action: Node action string
        verbose: Show verbose details

    Returns:
        Formatted text string
    """
    lines = ["✓ Node executed successfully\n"]

    if outputs:
        lines.append("Outputs:")
        for key, value in outputs.items():
            # Format value for display (pretty-print JSON if it's a dict/list)
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, indent=2, ensure_ascii=False)
                # Indent each line for better formatting
                indented = "\n  ".join(value_str.split("\n"))
                lines.append(f"  {key}:")
                lines.append(f"  {indented}")
            elif isinstance(value, str) and value.strip().startswith(("{", "[")):
                # Try to parse and pretty-print JSON strings
                try:
                    parsed = json.loads(value)
                    value_str = json.dumps(parsed, indent=2, ensure_ascii=False)
                    indented = "\n  ".join(value_str.split("\n"))
                    lines.append(f"  {key}:")
                    lines.append(f"  {indented}")
                except (json.JSONDecodeError, ValueError):
                    # Not valid JSON, show as-is
                    lines.append(f"  {key}: {value}")
            else:
                lines.append(f"  {key}: {value}")
    else:
        lines.append("No outputs returned")

    lines.append(f"\nExecution time: {execution_time_ms}ms")

    if verbose:
        lines.append(f"Action returned: '{action}'")

    return "\n".join(lines)


def format_json_output(node_type: str, outputs: dict[str, Any], execution_time_ms: int) -> dict[str, Any]:
    """Format results in JSON format for programmatic consumption.

    Custom serialization handles datetime, Path, and bytes types.

    Args:
        node_type: Node type identifier
        outputs: Node output dictionary
        execution_time_ms: Execution duration

    Returns:
        Dictionary ready for JSON serialization

    Raises:
        Includes serialization errors in result dict if encoding fails
    """
    result = {
        "success": True,
        "node_type": node_type,
        "outputs": outputs,
        "execution_time_ms": execution_time_ms,
    }

    # Try to serialize outputs, catching any serialization errors
    try:
        # Test serialization by encoding
        json.dumps(result, ensure_ascii=False, default=json_serializer)
        return result
    except (TypeError, ValueError) as e:
        # Return error result
        return {
            "success": False,
            "error": f"JSON serialization failed: {e!s}",
            "node_type": node_type,
        }


def _apply_smart_filtering(
    paths: list[tuple[str, str]], source_desc: str | None, original_count: int
) -> tuple[list[tuple[str, str]], str | None]:
    """Apply smart filtering to paths and update source description."""
    from pflow.core.smart_filter import smart_filter_fields_cached

    paths_tuple = tuple(paths)
    filtered_tuple = smart_filter_fields_cached(paths_tuple, threshold=25)
    filtered_paths = list(filtered_tuple)

    # Update description if filtering occurred
    if len(filtered_paths) < original_count:
        filter_info = f"{len(filtered_paths)} of {original_count} shown"
        source_desc = f"{source_desc} ({filter_info})" if source_desc else filter_info

    return filtered_paths, source_desc


def _get_paths_to_display(
    node_type: str, outputs: dict[str, Any], registry: Registry, verbose: bool
) -> tuple[list[tuple[str, str]] | None, str | None, list[str]]:
    """Extract paths to display from runtime outputs or metadata."""
    warnings: list[str] = []

    metadata_paths, has_any_type = extract_metadata_paths(node_type, registry)
    if metadata_paths is None:
        return None, None, warnings

    if has_any_type and outputs:
        paths, warnings = extract_runtime_paths(outputs)
        return paths, "from actual output", warnings if verbose else []

    if metadata_paths:
        return metadata_paths, None, warnings

    return None, None, warnings


def format_structure_output(
    node_type: str,
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    registry: Registry,
    execution_time_ms: int,
    verbose: bool = False,
    include_values: bool = False,
    execution_id: Optional[str] = None,
    output_mode: str = "smart",
) -> str:
    """Format flattened output structure for template variable discovery.

    Args:
        output_mode: "smart" (values+filtering), "structure" (paths only), "full" (all values)
    """
    lines = ["✓ Node executed successfully\n"]

    if execution_id:
        lines.append(f"Execution ID: {execution_id}\n")

    if include_values:
        lines.extend(format_output_values(outputs))

    # Get paths to display
    paths_to_display, source_desc, warnings = _get_paths_to_display(node_type, outputs, registry, verbose)
    lines.extend(warnings)

    if paths_to_display is None:
        lines.append("Note: Output structure information not available for this node")
        lines.append(f"\nExecution time: {execution_time_ms}ms")
        return "\n".join(lines)

    if not paths_to_display:
        lines.append("No structured outputs defined for this node")
        lines.append(f"\nExecution time: {execution_time_ms}ms")
        return "\n".join(lines)

    original_count = len(paths_to_display)

    # Format based on output mode
    if output_mode == "full":
        path_lines = format_full_paths_with_values(paths_to_display, outputs, shared_store)
    elif output_mode == "smart":
        paths_to_display, source_desc = _apply_smart_filtering(paths_to_display, source_desc, original_count)
        path_lines, _ = format_smart_paths_with_values(
            paths_to_display, outputs, shared_store, source_desc, execution_id or ""
        )
    else:  # structure mode - skip LLM filtering, show all paths
        path_lines = format_template_paths(paths_to_display, source_desc)

    lines.extend(path_lines)
    lines.append(f"\nExecution time: {execution_time_ms}ms")
    return "\n".join(lines)


def format_output_values(outputs: dict[str, Any]) -> list[str]:
    """Format full output values in human-readable format.

    Args:
        outputs: Dictionary of output values

    Returns:
        List of formatted output lines
    """
    if not outputs:
        return []

    lines = ["Outputs:"]
    for key, value in outputs.items():
        # Show full output (pretty-print JSON if it's a dict/list)
        if isinstance(value, (dict, list)):
            value_str = json.dumps(value, indent=2, ensure_ascii=False)
            # Indent each line for better formatting
            indented = "\n  ".join(value_str.split("\n"))
            lines.append(f"  {key}:")
            lines.append(f"  {indented}")
        elif isinstance(value, str) and value.strip().startswith(("{", "[")):
            # Try to parse and pretty-print JSON strings
            try:
                parsed = json.loads(value)
                value_str = json.dumps(parsed, indent=2, ensure_ascii=False)
                indented = "\n  ".join(value_str.split("\n"))
                lines.append(f"  {key}:")
                lines.append(f"  {indented}")
            except (json.JSONDecodeError, ValueError):
                # Not valid JSON, show as-is
                lines.append(f"  {key}: {value}")
        else:
            lines.append(f"  {key}: {value}")
    lines.append("")  # Empty line after outputs
    return lines


def extract_metadata_paths(node_type: str, registry: Registry) -> tuple[list[tuple[str, str]] | None, bool]:
    """Extract template paths from node metadata.

    Args:
        node_type: Node type to get metadata for
        registry: Registry instance

    Returns:
        Tuple of (paths list or None if no metadata, has_any_type flag)
    """
    # Get node metadata for interface structure
    nodes_metadata = registry.get_nodes_metadata([node_type])
    if node_type not in nodes_metadata:
        return None, False

    interface = nodes_metadata[node_type].get("interface", {})
    outputs_spec = interface.get("outputs", [])

    # Flatten output structure from metadata
    all_paths = []
    has_any_type = False

    for output in outputs_spec:
        if isinstance(output, dict):
            key = str(output.get("key") or output.get("name") or "unknown")
            output_type = str(output.get("type", "any"))
            structure = output.get("structure", {})

            # Add base path
            all_paths.append((key, output_type))

            # Check if this is an Any type - we'll need to inspect actual data
            if output_type.lower() in ("any", "dict", "object") and not structure:
                has_any_type = True

            # Flatten nested structure if present
            if structure:
                nested_paths = TemplateValidator._flatten_output_structure(
                    base_key=key, base_type=output_type, structure=structure
                )
                # Skip first as it's the base key we already added
                all_paths.extend(nested_paths[1:])

    return all_paths, has_any_type


def extract_runtime_paths(outputs: dict[str, Any]) -> tuple[list[tuple[str, str]], list[str]]:
    """Extract template paths from actual runtime output values.

    Args:
        outputs: Dictionary of output values

    Returns:
        Tuple of (paths list, warning messages list)
    """
    runtime_paths: list[tuple[str, str]] = []
    warnings: list[str] = []
    seen_structures: dict[str, str] = {}  # Track structures we've already shown

    for key, value in outputs.items():
        # Check if this value is identical to one we've already processed
        # (MCP nodes often return both 'result' and 'server_TOOL_result' with same data)
        value_hash = get_value_hash(value)

        if value_hash in seen_structures:
            # Skip duplicate structure, but note it exists
            original_key = seen_structures[value_hash]
            warnings.append(
                f"\nNote: '{key}' contains the same data as '{original_key}' (showing paths for '{original_key}' only)\n"
            )
            continue

        seen_structures[value_hash] = key

        # Recursively flatten the actual runtime value (handles JSON strings too)
        # Use just the key as prefix (not full node_type) for shorter paths
        flattened = flatten_runtime_value(key, value)
        runtime_paths.extend(flattened)

    return runtime_paths, warnings


def format_template_paths(paths: list[tuple[str, str]], source_description: str | None) -> list[str]:
    """Format template paths in a formatted list.

    Args:
        paths: List of (path, type) tuples
        source_description: Optional description of source (e.g., "from actual output")

    Returns:
        List of formatted lines
    """
    lines = []

    if source_description:
        lines.append(f"Available template paths ({source_description}):")
    else:
        lines.append("Available template paths:")

    for path, type_str in paths[:MAX_DISPLAYED_FIELDS]:
        lines.append(f"  ✓ ${{{path}}} ({type_str})")

    if len(paths) > MAX_DISPLAYED_FIELDS:
        remaining = len(paths) - MAX_DISPLAYED_FIELDS
        lines.append(f"  ... and {remaining} more paths")

    lines.append("\nUse these paths in workflow templates.")
    return lines


def get_value_hash(value: Any) -> str:
    """Get a hash of a value for deduplication.

    Args:
        value: Value to hash

    Returns:
        Hash string for comparing values
    """
    # Convert to JSON string for hashing (handles dicts, lists, etc.)
    try:
        if isinstance(value, str):
            # If it's already a string, use it directly
            return hash(value).__str__()
        else:
            # Convert to JSON for consistent hashing
            json_str = json.dumps(value, sort_keys=True, default=str)
            return hash(json_str).__str__()
    except (TypeError, ValueError):
        # Fallback to string representation
        return hash(str(value)).__str__()


def _try_parse_json_string(prefix: str, value: str, depth: int, max_depth: int) -> list[tuple[str, str]] | None:
    """Try to parse a string as JSON and flatten if successful.

    Args:
        prefix: Current path prefix
        value: String value to try parsing
        depth: Current recursion depth
        max_depth: Maximum recursion depth

    Returns:
        Flattened paths if JSON parse succeeds, None otherwise
    """
    from pflow.core.json_utils import try_parse_json

    success, parsed_value = try_parse_json(value)
    if success:
        # Recursively flatten the parsed JSON
        return flatten_runtime_value(prefix, parsed_value, depth, max_depth)
    return None


def _flatten_dict(prefix: str, value: dict[str, Any], depth: int, max_depth: int) -> list[tuple[str, str]]:
    """Flatten a dictionary value to show available template paths.

    Args:
        prefix: Current path prefix
        value: Dictionary to flatten
        depth: Current recursion depth
        max_depth: Maximum recursion depth

    Returns:
        List of (path, type) tuples
    """
    paths = [(prefix, "dict")]

    for key, val in value.items():
        # Skip large nested structures to avoid overwhelming output
        if isinstance(val, (dict, list)) and len(str(val)) > 1000:
            # Show count for lists/dicts instead of just "large"
            if isinstance(val, list):
                count = len(val)
                count_str = "empty" if count == 0 else f"{count} item{'s' if count != 1 else ''}"
                paths.append((f"{prefix}.{key}", f"list, {count_str}"))

                # Extract sample fields from first item for smart filtering context
                # This allows LLM to see what fields exist in array items
                if val and isinstance(val[0], dict):
                    # Limit to first 8 fields to avoid explosion
                    sample_keys = list(val[0].keys())[:8]
                    for sample_key in sample_keys:
                        sample_val = val[0][sample_key]
                        # Go only 1 level deep for large arrays (no deep recursion)
                        if isinstance(sample_val, (dict, list)):
                            # Just show the type, don't recurse further
                            type_name = "dict" if isinstance(sample_val, dict) else "list"
                            paths.append((f"{prefix}.{key}[0].{sample_key}", type_name))
                        else:
                            paths.append((f"{prefix}.{key}[0].{sample_key}", type(sample_val).__name__))
            else:
                # Show count for large dicts
                count = len(val)
                count_str = "empty" if count == 0 else f"{count} field{'s' if count != 1 else ''}"
                paths.append((f"{prefix}.{key}", f"dict, {count_str}"))
        else:
            paths.extend(flatten_runtime_value(f"{prefix}.{key}", val, depth + 1, max_depth))

    return paths


def _flatten_list(prefix: str, value: list[Any], depth: int, max_depth: int) -> list[tuple[str, str]]:
    """Flatten a list value to show available template paths.

    Args:
        prefix: Current path prefix
        value: List to flatten
        depth: Current recursion depth
        max_depth: Maximum recursion depth

    Returns:
        List of (path, type) tuples
    """
    paths = []

    # Show item count for lists
    count = len(value)
    if count == 0:
        paths.append((prefix, "list, empty"))
    elif count == 1:
        paths.append((prefix, "list, 1 item"))
    else:
        paths.append((prefix, f"list, {count} items"))

    if value:  # Show first element structure
        paths.append((f"{prefix}[0]", type(value[0]).__name__))
        if isinstance(value[0], (dict, list)):
            paths.extend(flatten_runtime_value(f"{prefix}[0]", value[0], depth + 1, max_depth))

    return paths


def flatten_runtime_value(prefix: str, value: Any, depth: int = 0, max_depth: int = 5) -> list[tuple[str, str]]:
    """Flatten actual runtime values to show available template paths.

    Args:
        prefix: Current path prefix
        value: Value to flatten
        depth: Current recursion depth
        max_depth: Maximum recursion depth

    Returns:
        List of (path, type) tuples
    """
    if depth > max_depth:
        return [(prefix, type(value).__name__)]

    # Try to parse JSON strings (common with MCP nodes)
    json_result = _try_parse_json_string(prefix, value, depth, max_depth)
    if json_result is not None:
        return json_result

    # Handle as regular string if JSON parse failed
    if isinstance(value, str):
        return [(prefix, "str")]

    # Dispatch to type-specific handlers
    if isinstance(value, dict):
        return _flatten_dict(prefix, value, depth, max_depth)
    elif isinstance(value, list):
        return _flatten_list(prefix, value, depth, max_depth)
    else:
        # Primitive types (int, float, bool, None, bytes, etc.)
        return [(prefix, type(value).__name__)]


def format_text_error(node_type: str, error_msg: str, execution_time_ms: int) -> str:
    """Format error in text format.

    Args:
        node_type: Node type identifier
        error_msg: Error message
        execution_time_ms: Execution duration

    Returns:
        Formatted error string
    """
    lines = [
        "❌ Node execution failed\n",
        f"Node: {node_type}",
        f"Error: {error_msg}",
        f"\nExecution time: {execution_time_ms}ms",
    ]
    return "\n".join(lines)


def format_json_error(node_type: str, error_msg: str, execution_time_ms: int) -> dict[str, Any]:
    """Format error in JSON format.

    Args:
        node_type: Node type identifier
        error_msg: Error message
        execution_time_ms: Execution duration

    Returns:
        Error dictionary
    """
    return {
        "success": False,
        "node_type": node_type,
        "error": error_msg,
        "execution_time_ms": execution_time_ms,
    }


def format_param_value(value: Any) -> str:
    """Format parameter value for display.

    Args:
        value: Parameter value

    Returns:
        Formatted string representation
    """
    if isinstance(value, bool):
        return str(value).lower()
    elif isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    elif isinstance(value, str) and len(value) > 50:
        return f"{value[:47]}..."
    return str(value)


def format_output_value(value: Any, max_length: int = 200) -> str:
    """Format output value for display, truncating if needed.

    Args:
        value: Output value
        max_length: Maximum length before truncation

    Returns:
        Formatted string representation
    """
    if isinstance(value, dict):
        if len(value) > 3:
            return f"dict with {len(value)} keys"
        return str(value)
    elif isinstance(value, list):
        if len(value) > 3:
            return f"list with {len(value)} items"
        return str(value)
    elif isinstance(value, str):
        if len(value) > max_length:
            return f"{value[: max_length - 3]}..."
        return value
    else:
        value_str = str(value)
        if len(value_str) > max_length:
            return f"{value_str[: max_length - 3]}..."
        return value_str


def _is_summary_format(formatted_value: str) -> bool:
    """Check if a formatted value is a collection summary like {...N keys} or [...N items].

    These summaries may not need a read-fields hint if children are visible in the output.
    """
    return formatted_value.startswith("{...") or formatted_value.startswith("[...")


def _has_visible_children(parent_path: str, all_paths: set[str]) -> bool:
    """Check if a parent path has any visible child paths in the output.

    Args:
        parent_path: The parent path (e.g., "llm_usage")
        all_paths: Set of all paths displayed in output

    Returns:
        True if any child path like "parent.x" or "parent[0]" exists
    """
    for path in all_paths:
        if path != parent_path and (path.startswith(f"{parent_path}.") or path.startswith(f"{parent_path}[")):
            return True
    return False


def _format_collection_smart(value: dict | list) -> tuple[str, bool]:
    """Format dict or list for smart display.

    Returns (formatted_string, was_summarized) where was_summarized=True
    means the user can't see actual data and may want to use read-fields.
    """
    is_dict = isinstance(value, dict)
    count = len(value)
    threshold = SMART_MAX_DICT_KEYS if is_dict else SMART_MAX_LIST_ITEMS
    summary = f"{{...{count} keys}}" if is_dict else f"[...{count} items]"

    if count > threshold:
        return summary, True  # Summarized - user can't see data, show hint

    # Try compact JSON for small collections
    try:
        compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(compact) > SMART_MAX_STRING_LENGTH:
            return summary, True  # Too long to display fully
        return compact, False  # Full data shown
    except (TypeError, ValueError):
        return summary, True  # Can't serialize, show hint


def format_value_for_smart_display(value: Any) -> tuple[str, bool]:
    """Format a value for smart display mode with truncation tracking.

    Returns:
        Tuple of (formatted_string, was_truncated)
    """
    # Handle None first
    if value is None:
        return "null", False

    # Handle primitives (no truncation possible)
    if isinstance(value, bool):
        return str(value).lower(), False
    if isinstance(value, (int, float)):
        return str(value), False
    if isinstance(value, bytes):
        return f"<binary data, {len(value)} bytes>", False

    # Handle strings with potential truncation
    if isinstance(value, str):
        if len(value) > SMART_MAX_STRING_LENGTH:
            truncated = value[: SMART_MAX_STRING_LENGTH - 3] + "..."
            return f'"{truncated}" (truncated)', True
        return f'"{value}"', False

    # Handle collections
    if isinstance(value, (dict, list)):
        return _format_collection_smart(value)

    # Fallback for other types
    value_str = str(value)
    if len(value_str) > SMART_MAX_STRING_LENGTH:
        return f"{value_str[: SMART_MAX_STRING_LENGTH - 3]}..." + " (truncated)", True
    return value_str, False


def format_smart_paths_with_values(
    paths: list[tuple[str, str]],
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    source_description: str | None,
    execution_id: str,
) -> tuple[list[str], bool]:
    """Format template paths with their actual values (smart mode).

    Resolves each path to its value and formats with truncation rules.

    The hint for read-fields is only shown when there's genuinely hidden data:
    - Actual value truncation (string too long, showing "(truncated)")
    - Collection summary ({...N keys}) where children are NOT visible

    If a collection is summarized but all its children are visible in the output,
    the hint is suppressed since the user can already see all the data.

    Args:
        paths: List of (path, type) tuples
        outputs: Node output dictionary
        shared_store: Complete shared store
        source_description: Description of path source (e.g., "8 of 54 shown")
        execution_id: Execution ID for read-fields hint

    Returns:
        Tuple of (formatted_lines, any_value_hidden)
    """
    lines: list[str] = []
    all_paths_set: set[str] = set()
    truncated_paths: list[str] = []  # Actual data truncation (string cut off)
    summarized_paths: list[str] = []  # Collection summaries ({...N keys})

    # Header
    if source_description:
        lines.append(f"Output ({source_description}):")
    else:
        lines.append("Output:")

    # Format each path with its value
    for path, type_str in paths[:MAX_DISPLAYED_FIELDS]:
        all_paths_set.add(path)

        # Resolve the actual value using helper that handles None vs not-found
        value = _resolve_template_value(path, outputs, shared_store)

        # Format the value
        if value is _NOT_FOUND:
            formatted_value = "<not found>"
            truncated = False
        else:
            formatted_value, truncated = format_value_for_smart_display(value)

        if truncated:
            # Distinguish between collection summaries and actual truncation
            if _is_summary_format(formatted_value):
                summarized_paths.append(path)
            else:
                truncated_paths.append(path)

        lines.append(f"  ✓ ${{{path}}} ({type_str}) = {formatted_value}")

    # Show overflow message if needed
    if len(paths) > MAX_DISPLAYED_FIELDS:
        remaining = len(paths) - MAX_DISPLAYED_FIELDS
        lines.append(f"  ... and {remaining} more paths")

    # Filter summarized paths: only count those without visible children
    # If children are visible, the user can already see the data
    hidden_summarized = [p for p in summarized_paths if not _has_visible_children(p, all_paths_set)]

    # Determine if there's genuinely hidden data
    any_hidden = bool(truncated_paths or hidden_summarized)

    # Add read-fields hint only if there's hidden data
    if any_hidden and execution_id:
        # Prefer showing a truly truncated path as example
        if truncated_paths:
            example_path = truncated_paths[0]
        elif hidden_summarized:
            example_path = hidden_summarized[0]
        else:
            example_path = paths[0][0] if paths else "path"
        lines.append(f"\nUse `pflow read-fields {execution_id} {example_path}` for full values.")

    return lines, any_hidden


def _format_value_full(value: Any) -> str:
    """Format a value for full display mode (no truncation)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, bytes):
        return f"<binary data, {len(value)} bytes>"
    if isinstance(value, (dict, list)):
        try:
            formatted = json.dumps(value, ensure_ascii=False, indent=2)
            if "\n" in formatted:
                indented = "\n    ".join(formatted.split("\n"))
                return f"\n    {indented}"
            return formatted
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def format_full_paths_with_values(
    paths: list[tuple[str, str]],
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
) -> list[str]:
    """Format all template paths with full values (full mode, no truncation)."""
    lines: list[str] = [f"Output (all {len(paths)} fields):"]

    for path, type_str in paths:
        # Resolve the actual value using helper that handles None vs not-found
        value = _resolve_template_value(path, outputs, shared_store)

        # Format value
        formatted_value = "<not found>" if value is _NOT_FOUND else _format_value_full(value)
        lines.append(f"  ✓ ${{{path}}} ({type_str}) = {formatted_value}")

    return lines


def json_serializer(obj: Any) -> Any:
    """Handle non-standard types in JSON serialization.

    Args:
        obj: Object to serialize

    Returns:
        JSON-serializable representation
    """
    from datetime import datetime
    from pathlib import Path

    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, Path):
        return str(obj)
    elif isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return f"<binary data: {len(obj)} bytes>"
    return str(obj)
