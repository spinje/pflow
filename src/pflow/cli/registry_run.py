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
            from pflow.execution.formatters.node_output_formatter import format_param_value

            click.echo("   Parameters:")
            for key, value in execution_params.items():
                click.echo(f"     {key}: {format_param_value(value)}")

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
    # Use shared formatter for all output formatting
    from pflow.execution.formatters.node_output_formatter import format_node_output

    # Determine format type
    format_type = "structure" if show_structure else output_format  # "text" or "json"

    # Format result using shared formatter
    result = format_node_output(
        node_type=node_type,
        action=action,
        outputs=outputs,
        shared_store=shared_store,
        execution_time_ms=execution_time_ms,
        registry=registry,
        format_type=format_type,
        verbose=verbose,
    )

    # Display result
    if output_format == "json" and not show_structure:
        # JSON mode - result is dict
        click.echo(json.dumps(result, indent=2))
    else:
        # Text/structure mode - result is string
        click.echo(result)

    # Exit with error code if execution failed
    if action == "error":
        sys.exit(1)


def _handle_ambiguous_node(node_type: str, matches: list[str]) -> None:
    """Handle ambiguous node name with helpful error message."""
    # Use shared formatter for CLI/MCP parity
    from pflow.execution.formatters.registry_run_formatter import format_ambiguous_node_error

    error_msg = format_ambiguous_node_error(node_type, matches)
    click.echo(error_msg, err=True)


def _handle_unknown_node(node_type: str, nodes: dict[str, Any]) -> None:
    """Handle unknown node with helpful suggestions."""
    # Use shared formatter for CLI/MCP parity
    from pflow.execution.formatters.registry_run_formatter import format_node_not_found_error

    error_msg = format_node_not_found_error(node_type, list(nodes.keys()))
    click.echo(error_msg, err=True)


def _handle_execution_error(node_type: str, exc: Exception, verbose: bool) -> None:
    """Handle node execution errors with context."""
    # Use shared formatter for CLI/MCP parity
    from pflow.execution.formatters.registry_run_formatter import format_execution_error

    error_msg = format_execution_error(node_type, exc, verbose=verbose)
    click.echo(error_msg, err=True)
