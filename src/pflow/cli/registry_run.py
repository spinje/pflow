"""Implementation of registry run command for single node execution."""

import json
import sys
import time
from typing import Any

import click

from pflow.cli.main import parse_workflow_params
from pflow.core.user_errors import MCPError
from pflow.core.validation_utils import is_valid_parameter_name
from pflow.registry import Registry
from pflow.runtime.compiler import _inject_special_parameters, import_node_class
from pflow.runtime.template_validator import TemplateValidator


def execute_single_node(
    node_type: str,
    params: tuple[str, ...],
    output_format: str,
    show_structure: bool,
    timeout: int,
    verbose: bool,
) -> None:
    """Execute a single node with provided parameters.

    Args:
        node_type: Node type from registry (e.g., "read-file", "SLACK_SEND_MESSAGE")
        params: Tuple of parameter strings in key=value format
        output_format: Output format - "text" or "json"
        show_structure: Whether to show flattened structure for templates
        timeout: Execution timeout in seconds (currently unused)
        verbose: Whether to show detailed execution information
    """
    # Step 1: Parse and validate parameters
    execution_params = _validate_parameters(params)

    # Step 2: Resolve node type to actual node ID
    registry = Registry()
    resolved_node = _resolve_node_type(node_type, registry, verbose)

    # Step 3: Prepare node for execution
    node, enhanced_params = _prepare_node_execution(resolved_node, execution_params, registry)

    # Step 4: Execute node and display results
    _execute_and_display_results(
        node=node,
        resolved_node=resolved_node,
        execution_params=execution_params,
        enhanced_params=enhanced_params,
        output_format=output_format,
        show_structure=show_structure,
        registry=registry,
        verbose=verbose,
    )


def _validate_parameters(params: tuple[str, ...]) -> dict[str, Any]:
    """Parse and validate parameters from key=value format.

    Args:
        params: Tuple of parameter strings in key=value format

    Returns:
        Dictionary of parsed parameters

    Exits:
        With code 1 if parameter validation fails
    """
    execution_params = parse_workflow_params(params)

    # Validate parameter names (security check)
    invalid_keys = [k for k in execution_params if not is_valid_parameter_name(k)]
    if invalid_keys:
        click.echo(f"❌ Invalid parameter name(s): {', '.join(invalid_keys)}", err=True)
        click.echo("   Parameter names cannot contain shell special characters ($, |, >, <, &, ;, etc.)", err=True)
        sys.exit(1)

    return execution_params


def _resolve_node_type(node_type: str, registry: Registry, verbose: bool) -> str:
    """Resolve node type to actual node ID, handling MCP variations.

    Args:
        node_type: Node type from user input
        registry: Registry instance
        verbose: Whether to show resolution feedback

    Returns:
        Resolved node ID

    Exits:
        With code 1 if node cannot be resolved
    """
    nodes = registry.load()
    available_nodes = set(nodes.keys())

    # Normalize node ID using existing logic (handles MCP variations)
    from pflow.cli.registry import _normalize_node_id

    resolved_node = _normalize_node_id(node_type, available_nodes)

    # Handle normalization results
    if not resolved_node:
        # Check if it was ambiguous (multiple matches)
        normalized_check = node_type.replace("-", "_")
        matches = [n for n in available_nodes if n.endswith(node_type) or n.endswith(normalized_check)]

        if len(matches) > 1:
            # Ambiguous - show all matches
            _handle_ambiguous_node(node_type, matches)
            sys.exit(1)
        else:
            # Not found at all
            _handle_unknown_node(node_type, nodes)
            sys.exit(1)

    # Show resolution if different from input (verbose mode only)
    if verbose and resolved_node != node_type:
        click.echo(f"📝 Resolved '{node_type}' to '{resolved_node}'")

    return resolved_node


def _prepare_node_execution(
    resolved_node: str, execution_params: dict[str, Any], registry: Registry
) -> tuple[Any, dict[str, Any]]:
    """Prepare node instance for execution.

    Args:
        resolved_node: Resolved node ID
        execution_params: User-provided parameters
        registry: Registry instance

    Returns:
        Tuple of (node instance, enhanced parameters)

    Exits:
        With code 1 if node loading fails
    """
    # Import node class
    try:
        node_class = import_node_class(resolved_node, registry)
    except Exception as e:
        click.echo(f"❌ Failed to load node '{resolved_node}': {e}", err=True)
        sys.exit(1)

    # Create node instance
    node = node_class()

    # Inject special parameters (for MCP and workflow nodes)
    enhanced_params = _inject_special_parameters(
        resolved_node,
        resolved_node,
        execution_params,
        registry,  # node_id same as node_type
    )

    # Set parameters on node
    if enhanced_params:
        node.set_params(enhanced_params)

    return node, enhanced_params


def _execute_and_display_results(
    node: Any,
    resolved_node: str,
    execution_params: dict[str, Any],
    enhanced_params: dict[str, Any],
    output_format: str,
    show_structure: bool,
    registry: Registry,
    verbose: bool,
) -> None:
    """Execute node and display results based on output mode.

    Args:
        node: Node instance to execute
        resolved_node: Resolved node ID
        execution_params: User-provided parameters
        enhanced_params: Enhanced parameters with special injections
        output_format: Output format - "text" or "json"
        show_structure: Whether to show flattened structure
        registry: Registry instance
        verbose: Whether to show detailed execution information

    Exits:
        With code 1 if execution fails
    """
    # Create minimal shared store
    shared_store = {}
    # Add execution params to shared (nodes can read from either params or shared)
    shared_store.update(execution_params)

    # Execute node with timing
    start_time = time.perf_counter()

    if verbose:
        click.echo(f"🔄 Running node '{resolved_node}'...")
        if execution_params:
            click.echo("   Parameters:")
            for key, value in execution_params.items():
                click.echo(f"     {key}: {_format_param_value(value)}")

    try:
        # Execute node
        action = node.run(shared_store)

        # Calculate execution time
        execution_time_ms = int((time.perf_counter() - start_time) * 1000)

        # Extract outputs (node writes to shared_store by convention)
        # Try node type key first, then check for common output keys
        outputs = shared_store.get(resolved_node, {})
        if not outputs:
            # Fallback: collect any non-input keys as outputs (excluding internal keys)
            outputs = {k: v for k, v in shared_store.items() if k not in execution_params and not k.startswith("__")}

        # Display results based on mode
        _display_results(
            node_type=resolved_node,
            action=action,
            outputs=outputs,
            shared_store=shared_store,
            execution_time_ms=execution_time_ms,
            output_format=output_format,
            show_structure=show_structure,
            registry=registry,
            verbose=verbose,
        )

    except MCPError as e:
        # MCP-specific user-friendly errors
        click.echo(e.format_for_cli(verbose=verbose), err=True)
        sys.exit(1)
    except Exception as e:
        # Generic execution errors
        _handle_execution_error(resolved_node, e, verbose)
        sys.exit(1)


def _display_results(
    node_type: str,
    action: str,
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    execution_time_ms: int,
    output_format: str,
    show_structure: bool,
    registry: Registry,
    verbose: bool,
) -> None:
    """Display execution results based on output format and options."""
    # Check for error action
    if action == "error":
        error_msg = shared_store.get("error", "Unknown error")
        if output_format == "json":
            _display_json_error(node_type, error_msg, execution_time_ms)
        else:
            _display_text_error(node_type, error_msg, execution_time_ms)
        sys.exit(1)

    # Success cases
    if show_structure:
        _display_structure_output(node_type, outputs, shared_store, registry, execution_time_ms)
    elif output_format == "json":
        _display_json_output(node_type, outputs, execution_time_ms)
    else:
        _display_text_output(node_type, outputs, execution_time_ms, action, verbose)


def _display_text_output(
    node_type: str, outputs: dict[str, Any], execution_time_ms: int, action: str, verbose: bool
) -> None:
    """Display results in human-readable text format."""
    click.echo("✓ Node executed successfully\n")

    if outputs:
        click.echo("Outputs:")
        for key, value in outputs.items():
            # Format value for display (pretty-print JSON if it's a dict/list)
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, indent=2, ensure_ascii=False)
                # Indent each line for better formatting
                indented = "\n  ".join(value_str.split("\n"))
                click.echo(f"  {key}:")
                click.echo(f"  {indented}")
            elif isinstance(value, str) and value.strip().startswith(("{", "[")):
                # Try to parse and pretty-print JSON strings
                try:
                    parsed = json.loads(value)
                    value_str = json.dumps(parsed, indent=2, ensure_ascii=False)
                    indented = "\n  ".join(value_str.split("\n"))
                    click.echo(f"  {key}:")
                    click.echo(f"  {indented}")
                except (json.JSONDecodeError, ValueError):
                    # Not valid JSON, show as-is
                    click.echo(f"  {key}: {value}")
            else:
                click.echo(f"  {key}: {value}")
    else:
        click.echo("No outputs returned")

    click.echo(f"\nExecution time: {execution_time_ms}ms")

    if verbose:
        click.echo(f"Action returned: '{action}'")


def _display_json_output(node_type: str, outputs: dict[str, Any], execution_time_ms: int) -> None:
    """Display results in JSON format for programmatic consumption."""
    result = {
        "success": True,
        "node_type": node_type,
        "outputs": outputs,
        "execution_time_ms": execution_time_ms,
    }

    # Custom serializer for special types
    def json_serializer(obj: Any) -> Any:
        """Handle non-standard types in JSON serialization."""
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

    try:
        output = json.dumps(result, indent=2, ensure_ascii=False, default=json_serializer)
        click.echo(output)
    except (TypeError, ValueError) as e:
        # Fallback for serialization issues
        error_result = {
            "success": False,
            "error": f"JSON serialization failed: {e!s}",
            "node_type": node_type,
        }
        click.echo(json.dumps(error_result, indent=2))
        sys.exit(1)


def _display_structure_output(
    node_type: str,
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    registry: Registry,
    execution_time_ms: int,
) -> None:
    """Display flattened output structure for template variable discovery."""
    click.echo("✓ Node executed successfully\n")

    # Show full output values (same as text mode)
    _display_output_values(outputs)

    # Get metadata and extract template paths
    metadata_paths, has_any_type = _extract_metadata_paths(node_type, registry)
    if metadata_paths is None:
        # No metadata available
        click.echo("Note: Output structure information not available for this node")
        click.echo(f"\nExecution time: {execution_time_ms}ms")
        return

    # Display paths based on whether we have runtime data or use metadata
    if has_any_type and outputs:
        runtime_paths = _extract_runtime_paths(outputs)
        _display_template_paths(runtime_paths, "from actual output")
    elif metadata_paths:
        _display_template_paths(metadata_paths, None)
    else:
        click.echo("No structured outputs defined for this node")

    click.echo(f"\nExecution time: {execution_time_ms}ms")


def _display_output_values(outputs: dict[str, Any]) -> None:
    """Display full output values in human-readable format.

    Args:
        outputs: Dictionary of output values to display
    """
    if not outputs:
        return

    click.echo("Outputs:")
    for key, value in outputs.items():
        # Show full output (pretty-print JSON if it's a dict/list)
        if isinstance(value, (dict, list)):
            value_str = json.dumps(value, indent=2, ensure_ascii=False)
            # Indent each line for better formatting
            indented = "\n  ".join(value_str.split("\n"))
            click.echo(f"  {key}:")
            click.echo(f"  {indented}")
        elif isinstance(value, str) and value.strip().startswith(("{", "[")):
            # Try to parse and pretty-print JSON strings
            try:
                parsed = json.loads(value)
                value_str = json.dumps(parsed, indent=2, ensure_ascii=False)
                indented = "\n  ".join(value_str.split("\n"))
                click.echo(f"  {key}:")
                click.echo(f"  {indented}")
            except (json.JSONDecodeError, ValueError):
                # Not valid JSON, show as-is
                click.echo(f"  {key}: {value}")
        else:
            click.echo(f"  {key}: {value}")
    click.echo()


def _extract_metadata_paths(node_type: str, registry: Registry) -> tuple[list[tuple[str, str]] | None, bool]:
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


def _extract_runtime_paths(outputs: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract template paths from actual runtime output values.

    Args:
        outputs: Dictionary of output values

    Returns:
        List of (path, type) tuples
    """
    runtime_paths: list[tuple[str, str]] = []
    seen_structures: dict[str, str] = {}  # Track structures we've already shown

    for key, value in outputs.items():
        # Check if this value is identical to one we've already processed
        # (MCP nodes often return both 'result' and 'server_TOOL_result' with same data)
        value_hash = _get_value_hash(value)

        if value_hash in seen_structures:
            # Skip duplicate structure, but note it exists
            original_key = seen_structures[value_hash]
            click.echo(
                f"\nNote: '{key}' contains the same data as '{original_key}' (showing paths for '{original_key}' only)\n"
            )
            continue

        seen_structures[value_hash] = key

        # Recursively flatten the actual runtime value (handles JSON strings too)
        # Use just the key as prefix (not full node_type) for shorter paths
        flattened = _flatten_runtime_value(key, value)
        runtime_paths.extend(flattened)

    return runtime_paths


def _display_template_paths(paths: list[tuple[str, str]], source_description: str | None) -> None:
    """Display template paths in a formatted list.

    Args:
        paths: List of (path, type) tuples
        source_description: Optional description of the source (e.g., "from actual output")
    """
    MAX_DISPLAYED_FIELDS = 500  # Allow up to 500 lines for full structure discovery

    if source_description:
        click.echo(f"Available template paths ({source_description}):")
    else:
        click.echo("Available template paths:")

    for path, type_str in paths[:MAX_DISPLAYED_FIELDS]:
        click.echo(f"  ✓ ${{{path}}} ({type_str})")

    if len(paths) > MAX_DISPLAYED_FIELDS:
        remaining = len(paths) - MAX_DISPLAYED_FIELDS
        click.echo(f"  ... and {remaining} more paths")

    click.echo("\nUse these paths in workflow templates.")


def _get_value_hash(value: Any) -> str:
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


def _flatten_runtime_value(prefix: str, value: Any, depth: int = 0, max_depth: int = 5) -> list[tuple[str, str]]:
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

    paths = []

    # Try to parse JSON strings (common with MCP nodes)
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            parsed_value = json.loads(value)
            # Recursively flatten the parsed JSON
            return _flatten_runtime_value(prefix, parsed_value, depth, max_depth)
        except (json.JSONDecodeError, ValueError):
            # Not valid JSON, treat as string
            paths.append((prefix, "str"))
            return paths

    if isinstance(value, dict):
        paths.append((prefix, "dict"))
        for key, val in value.items():
            # Skip large nested structures to avoid overwhelming output
            if isinstance(val, (dict, list)) and len(str(val)) > 1000:
                paths.append((f"{prefix}.{key}", type(val).__name__ + " (large)"))
            else:
                paths.extend(_flatten_runtime_value(f"{prefix}.{key}", val, depth + 1, max_depth))
    elif isinstance(value, list):
        paths.append((prefix, "list"))
        if value:  # Show first element structure
            paths.append((f"{prefix}[0]", type(value[0]).__name__))
            if isinstance(value[0], (dict, list)):
                paths.extend(_flatten_runtime_value(f"{prefix}[0]", value[0], depth + 1, max_depth))
    else:
        paths.append((prefix, type(value).__name__))

    return paths


def _handle_ambiguous_node(node_type: str, matches: list[str]) -> None:
    """Handle ambiguous node name with helpful error message."""
    click.echo(f"❌ Ambiguous node name '{node_type}'. Found in multiple servers:", err=True)
    for match in sorted(matches):
        click.echo(f"  - {match}", err=True)

    click.echo("\nPlease specify the full node ID or use format: {{server}}-{{tool}}", err=True)

    # Show examples if possible
    if matches:
        click.echo("\nExamples:", err=True)
        example = matches[0]
        parts = example.split("-")
        if len(parts) >= 3 and parts[0] == "mcp":
            # MCP node - show different formats
            server_parts = parts[1:-1]
            tool = parts[-1]
            click.echo(f"  pflow registry run {example}  # Full format", err=True)
            click.echo(f"  pflow registry run {'-'.join(server_parts)}-{tool}  # Server-qualified", err=True)


def _handle_unknown_node(node_type: str, nodes: dict[str, Any]) -> None:
    """Handle unknown node with helpful suggestions."""
    click.echo(f"❌ Unknown node type: '{node_type}'", err=True)

    # Find similar nodes
    similar = []
    search_term = node_type.lower()

    for name in nodes:
        if search_term in name.lower():
            similar.append(name)
            if len(similar) >= 5:
                break

    if similar:
        click.echo("\nDid you mean:", err=True)
        for name in similar:
            click.echo(f"  - {name}", err=True)
    else:
        # Show first 10 available nodes
        click.echo("\nAvailable nodes:", err=True)
        for i, name in enumerate(sorted(nodes.keys())):
            if i >= 10:
                click.echo(f"  ... and {len(nodes) - 10} more", err=True)
                break
            click.echo(f"  - {name}", err=True)

    # Suggest discovery commands
    click.echo("\nTo find the right node:", err=True)
    click.echo('  pflow registry discover "describe what you want to do"', err=True)
    click.echo("  pflow registry list  # See all available nodes", err=True)


def _handle_execution_error(node_type: str, exc: Exception, verbose: bool) -> None:
    """Handle node execution errors with context."""
    error_type = type(exc).__name__

    # Common error patterns with specific guidance
    if isinstance(exc, FileNotFoundError):
        click.echo(f"❌ File not found: {exc}", err=True)
        click.echo("\nVerify the file path exists and is accessible.", err=True)
    elif isinstance(exc, PermissionError):
        click.echo(f"❌ Permission denied: {exc}", err=True)
        click.echo("\nCheck file permissions and access rights.", err=True)
    elif isinstance(exc, ValueError) and "required" in str(exc).lower():
        click.echo(f"❌ Missing required parameter: {exc}", err=True)
        click.echo(f"\nUse 'pflow registry describe {node_type}' to see required parameters.", err=True)
    elif "timeout" in str(exc).lower():
        click.echo("❌ Node execution timed out", err=True)
        click.echo("\nTry increasing timeout with --timeout option.", err=True)
    else:
        # Generic error
        click.echo("❌ Node execution failed", err=True)
        click.echo(f"\nNode: {node_type}", err=True)
        click.echo(f"Error: {exc}", err=True)

        if verbose:
            click.echo(f"Error type: {error_type}", err=True)

            # For MCP nodes, provide specific guidance
            if node_type.startswith("mcp-"):
                click.echo("\nFor MCP nodes:", err=True)
                click.echo("  1. Check if server is configured: pflow mcp list", err=True)
                click.echo("  2. Sync the server: pflow mcp sync <server-name>", err=True)
                click.echo("  3. Verify credentials are set (environment variables)", err=True)


def _display_text_error(node_type: str, error_msg: str, execution_time_ms: int) -> None:
    """Display error in text format."""
    click.echo("❌ Node execution failed\n", err=True)
    click.echo(f"Node: {node_type}", err=True)
    click.echo(f"Error: {error_msg}", err=True)
    click.echo(f"\nExecution time: {execution_time_ms}ms", err=True)


def _display_json_error(node_type: str, error_msg: str, execution_time_ms: int) -> None:
    """Display error in JSON format."""
    error_output = {
        "success": False,
        "node_type": node_type,
        "error": error_msg,
        "execution_time_ms": execution_time_ms,
    }
    click.echo(json.dumps(error_output, indent=2))


def _format_param_value(value: Any) -> str:
    """Format parameter value for display."""
    if isinstance(value, bool):
        return str(value).lower()
    elif isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    elif isinstance(value, str) and len(value) > 50:
        return f"{value[:47]}..."
    return str(value)


def _format_output_value(value: Any, max_length: int = 200) -> str:
    """Format output value for display, truncating if needed."""
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
