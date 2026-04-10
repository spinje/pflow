"""Implementation of registry run command for single node execution."""

import json
import sys
import time
from typing import Any

import click

from pflow.cli.param_parsing import parse_workflow_params
from pflow.core.diagnostic import exception_to_diagnostics, format_diagnostic
from pflow.core.execution_cache import ExecutionCache
from pflow.core.param_coercion import coerce_param_for_node
from pflow.core.user_errors import MCPError
from pflow.core.validation_utils import is_valid_parameter_name
from pflow.registry import Registry
from pflow.runtime.compilation import import_node_class, inject_special_parameters


def execute_single_node(
    node_type: str,
    params: tuple[str, ...],
    output_format: str,
    show_structure: bool,
    verbose: bool,
) -> None:
    """Execute a single node with provided parameters.

    Args:
        node_type: Node type from registry (e.g., "read-file", "SLACK_SEND_MESSAGE")
        params: Tuple of parameter strings in key=value format
        output_format: Output format - "text" or "json"
        show_structure: Whether to show flattened structure for templates
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


def _coerce_params_for_node(
    params: dict[str, Any],
    node_id: str,
    registry: Registry,
) -> dict[str, Any]:
    """Coerce parameter types based on node interface declaration.

    When a parameter is declared as 'str' but the value is dict/list,
    serialize it to a JSON string. This enables MCP tools that expect
    JSON-formatted string parameters.

    Args:
        params: Parameters to coerce
        node_id: Node ID for registry lookup
        registry: Registry instance

    Returns:
        Parameters with coerced types
    """
    # Get node interface metadata
    nodes = registry.load()
    node_info = nodes.get(node_id, {})
    interface = node_info.get("interface", {})
    param_schemas = interface.get("params", [])

    # Build type lookup
    param_types: dict[str, str] = {}
    for param in param_schemas:
        if isinstance(param, dict):
            key = param.get("key")
            param_type = param.get("type")
            if key and param_type:
                param_types[key] = param_type

    # Coerce each parameter
    coerced = {}
    for key, value in params.items():
        expected_type = param_types.get(key)
        coerced[key] = coerce_param_for_node(value, expected_type)

    return coerced


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
    from pflow.cli.commands.registry import normalize_node_id

    resolved_node = normalize_node_id(node_type, available_nodes)

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
    enhanced_params = inject_special_parameters(
        resolved_node,
        resolved_node,
        execution_params,
        registry,  # node_id same as node_type
    )

    # Coerce parameters to declared types (dict/list → str for str-typed params)
    if enhanced_params:
        enhanced_params = _coerce_params_for_node(enhanced_params, resolved_node, registry)

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

    # Generate execution ID for structure-only mode (Task 89)
    cache = ExecutionCache()
    execution_id = cache.generate_execution_id()

    # Execute node with timing
    start_time = time.perf_counter()

    if verbose:
        _display_execution_banner(resolved_node, execution_params)

    try:
        # Execute node
        action = node.run(shared_store)

        # Calculate execution time
        execution_time_ms = int((time.perf_counter() - start_time) * 1000)

        outputs = _extract_node_outputs(resolved_node, shared_store, execution_params)

        if action != "error":
            _store_registry_execution(cache, execution_id, resolved_node, execution_params, outputs, verbose)
        output_mode = _load_registry_output_mode()

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
            execution_id=execution_id,
            output_mode=output_mode,
        )

    except MCPError as e:
        # MCP-specific user-friendly errors
        diagnostics = exception_to_diagnostics(e)
        for diagnostic in diagnostics:
            click.echo(format_diagnostic(diagnostic, verbose=verbose), err=True)
        sys.exit(1)
    except Exception as e:
        # Generic execution errors
        _handle_execution_error(resolved_node, e, verbose)
        sys.exit(1)


def _display_execution_banner(resolved_node: str, execution_params: dict[str, Any]) -> None:
    """Display verbose execution metadata before running a node."""
    click.echo(f"🔄 Running node '{resolved_node}'...")
    if not execution_params:
        return

    from pflow.execution.formatters.node_output_formatter import format_param_value

    click.echo("   Parameters:")
    for key, value in execution_params.items():
        click.echo(f"     {key}: {format_param_value(value)}")


def _extract_node_outputs(
    resolved_node: str,
    shared_store: dict[str, Any],
    execution_params: dict[str, Any],
) -> dict[str, Any]:
    """Extract node outputs from shared storage."""
    outputs = shared_store.get(resolved_node, {})
    if isinstance(outputs, dict) and outputs:
        return outputs
    return {
        key: value for key, value in shared_store.items() if key not in execution_params and not key.startswith("__")
    }


def _store_registry_execution(
    cache: ExecutionCache,
    execution_id: str,
    resolved_node: str,
    execution_params: dict[str, Any],
    outputs: dict[str, Any],
    verbose: bool,
) -> None:
    """Cache a successful node execution without failing the command on cache errors."""
    try:
        cache.store(
            execution_id=execution_id,
            node_type=resolved_node,
            params=execution_params,
            outputs=outputs,
        )
    except Exception as cache_error:
        if verbose:
            click.echo(f"⚠️  Failed to cache execution: {cache_error}", err=True)


def _load_registry_output_mode() -> str:
    """Load the registry output mode from settings."""
    from pflow.core.settings import SettingsManager

    return SettingsManager().load().registry.output_mode


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
    execution_id: str,
    output_mode: str = "smart",
) -> None:
    """Display execution results based on output format and options.

    Args:
        output_mode: Display mode for structure format - "smart", "structure", or "full"
    """
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
        execution_id=execution_id if format_type == "structure" else None,
        output_mode=output_mode,
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
    from pflow.core.diagnostic import Diagnostic, Severity, format_diagnostic

    d = Diagnostic(
        severity=Severity.ERROR,
        message=f"Ambiguous node name '{node_type}'. Found in multiple servers.",
        title="Ambiguous Node Name",
        suggestions=[
            f"Specify the full node ID (e.g., '{matches[0]}')" if matches else "Specify the full node ID",
            "Use format: {server}-{tool}",
        ],
        source="registry",
        context={"category": "not_found", "similar_names": sorted(matches)},
    )
    click.echo(format_diagnostic(d), err=True)


def _handle_unknown_node(node_type: str, nodes: dict[str, Any]) -> None:
    """Handle unknown node with helpful suggestions."""
    from pflow.execution.formatters.registry_error_helpers import build_node_not_found_diagnostic

    d = build_node_not_found_diagnostic(node_type, list(nodes.keys()))
    click.echo(format_diagnostic(d), err=True)


def _handle_execution_error(node_type: str, exc: Exception, verbose: bool) -> None:
    """Handle node execution errors with registry-run context."""
    from pflow.execution.formatters.registry_error_helpers import enrich_for_registry_run

    for d in enrich_for_registry_run(exc, node_type):
        click.echo(format_diagnostic(d, verbose=verbose), err=True)
