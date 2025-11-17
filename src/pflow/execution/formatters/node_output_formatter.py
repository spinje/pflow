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
from pflow.runtime.template_validator import TemplateValidator

# Constants
MAX_DISPLAYED_FIELDS = 500  # Allow up to 500 template paths


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
            node_type, outputs, shared_store, registry, execution_time_ms, execution_id=execution_id
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


def format_structure_output(
    node_type: str,
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    registry: Registry,
    execution_time_ms: int,
    include_values: bool = False,
    execution_id: Optional[str] = None,
) -> str:
    """Format flattened output structure for template variable discovery.

    This shows template paths like ${node.field} that agents can use when
    building workflows.

    Args:
        node_type: Node type identifier
        outputs: Node output dictionary
        shared_store: Complete shared store
        registry: Registry instance
        execution_time_ms: Execution duration
        include_values: If True, show actual data values before template paths.
                       If False (default), show only template paths (structure-only mode).
        execution_id: Optional execution ID to display for later field retrieval.

    Returns:
        Formatted text string with template paths
    """
    lines = ["✓ Node executed successfully\n"]

    # Show execution ID if provided (for structure-only mode)
    if execution_id:
        lines.append(f"Execution ID: {execution_id}\n")

    # Only show full output values if explicitly requested
    if include_values:
        output_lines = format_output_values(outputs)
        lines.extend(output_lines)

    # Get metadata and extract template paths
    metadata_paths, has_any_type = extract_metadata_paths(node_type, registry)
    if metadata_paths is None:
        # No metadata available
        lines.append("Note: Output structure information not available for this node")
        lines.append(f"\nExecution time: {execution_time_ms}ms")
        return "\n".join(lines)

    # Determine which paths to use (runtime vs metadata)
    if has_any_type and outputs:
        # Extract from actual runtime outputs (more accurate)
        paths_to_display, warnings = extract_runtime_paths(outputs)
        source_desc = "from actual output"
        if warnings:
            lines.extend(warnings)
    elif metadata_paths:
        # Use metadata paths from registry
        paths_to_display = metadata_paths
        source_desc = None
    else:
        lines.append("No structured outputs defined for this node")
        lines.append(f"\nExecution time: {execution_time_ms}ms")
        return "\n".join(lines)

    # Apply smart filtering to reduce large field sets (with caching)
    from pflow.core.smart_filter import smart_filter_fields_cached

    original_count = len(paths_to_display)

    # Convert to tuple for caching (LRU cache requires hashable args)
    paths_tuple = tuple(paths_to_display)
    filtered_tuple = smart_filter_fields_cached(paths_tuple, threshold=30)
    paths_to_display = list(filtered_tuple)

    # Adjust source description if filtering occurred
    if len(paths_to_display) < original_count:
        if source_desc:
            source_desc = f"{source_desc} ({len(paths_to_display)} of {original_count} shown)"
        else:
            source_desc = f"{len(paths_to_display)} of {original_count} shown"

    # Display filtered paths
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
    if not (isinstance(value, str) and value.strip().startswith(("{", "["))):
        return None

    try:
        parsed_value = json.loads(value)
        # Recursively flatten the parsed JSON
        return flatten_runtime_value(prefix, parsed_value, depth, max_depth)
    except (json.JSONDecodeError, ValueError):
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
                paths.append((f"{prefix}.{key}", "dict (large)"))
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
