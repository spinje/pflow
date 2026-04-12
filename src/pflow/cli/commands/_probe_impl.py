"""Implementation of the `pflow probe` command."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import click

from pflow.cli.param_parsing import parse_workflow_params
from pflow.core.diagnostic import exception_to_diagnostics
from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.execution_cache import ExecutionCache
from pflow.core.param_coercion import coerce_param_for_node
from pflow.core.user_errors import MCPError
from pflow.core.validation_utils import is_valid_parameter_name
from pflow.registry import Registry
from pflow.registry.node_id import normalize_node_id
from pflow.runtime.compilation import import_node_class, inject_special_parameters


def execute_single_node(
    node_type: str,
    params: tuple[str, ...],
    output_format: str,
    show_structure: bool,
    verbose: bool,
) -> None:
    """Execute a single node with provided parameters."""
    execution_params = _validate_parameters(params)

    registry = Registry()
    resolved_node = _resolve_node_type(node_type, registry, verbose)
    node, enhanced_params = _prepare_node_execution(resolved_node, execution_params, registry)

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
    execution_params = parse_workflow_params(params)
    invalid_keys = [key for key in execution_params if not is_valid_parameter_name(key)]
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
    nodes = registry.load()
    node_info = nodes.get(node_id, {})
    interface = node_info.get("interface", {})
    param_schemas = interface.get("params", [])

    param_types: dict[str, str] = {}
    for param in param_schemas:
        if isinstance(param, dict):
            key = param.get("key")
            param_type = param.get("type")
            if key and param_type:
                param_types[key] = param_type

    coerced = {}
    for key, value in params.items():
        expected_type = param_types.get(key)
        coerced[key] = coerce_param_for_node(value, expected_type)

    return coerced


def _resolve_node_type(node_type: str, registry: Registry, verbose: bool) -> str:
    nodes = registry.load()
    available_nodes = set(nodes.keys())
    resolved_node = normalize_node_id(node_type, available_nodes)

    if not resolved_node:
        normalized_check = node_type.replace("-", "_")
        matches = [
            node_id for node_id in available_nodes if node_id.endswith(node_type) or node_id.endswith(normalized_check)
        ]

        if len(matches) > 1:
            _handle_ambiguous_node(node_type, matches)
            sys.exit(1)

        _handle_unknown_node(node_type, nodes)
        sys.exit(1)

    if verbose and resolved_node != node_type:
        click.echo(f"📝 Resolved '{node_type}' to '{resolved_node}'")

    return resolved_node


def _prepare_node_execution(
    resolved_node: str,
    execution_params: dict[str, Any],
    registry: Registry,
) -> tuple[Any, dict[str, Any]]:
    try:
        node_class = import_node_class(resolved_node, registry)
    except Exception as exception:
        click.echo(f"❌ Failed to load node '{resolved_node}': {exception}", err=True)
        sys.exit(1)

    node = node_class()
    enhanced_params = inject_special_parameters(
        resolved_node,
        resolved_node,
        execution_params,
        registry,
    )

    if enhanced_params:
        enhanced_params = _coerce_params_for_node(enhanced_params, resolved_node, registry)
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
    shared_store: dict[str, Any] = {}
    shared_store.update(execution_params)

    cache = ExecutionCache()
    execution_id = cache.generate_execution_id()
    start_time = time.perf_counter()

    if verbose:
        _display_execution_banner(resolved_node, execution_params)

    try:
        action = node.run(shared_store)
        execution_time_ms = int((time.perf_counter() - start_time) * 1000)
        outputs = _extract_node_outputs(resolved_node, shared_store, execution_params)

        if action != "error":
            _store_registry_execution(cache, execution_id, resolved_node, execution_params, outputs, verbose)
        output_mode = _load_registry_output_mode()

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
    except MCPError as exception:
        diagnostics = exception_to_diagnostics(exception)
        for diagnostic in diagnostics:
            click.echo(format_diagnostic(diagnostic, verbose=verbose), err=True)
        sys.exit(1)
    except Exception as exception:
        _handle_execution_error(resolved_node, exception, verbose)
        sys.exit(1)


def _display_execution_banner(resolved_node: str, execution_params: dict[str, Any]) -> None:
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
    try:
        cache.store(execution_id, resolved_node, execution_params, outputs)
        if verbose:
            click.echo(f"💾 Stored execution in cache: {execution_id}")
    except Exception as exception:
        if verbose:
            click.echo(f"⚠️  Warning: Failed to cache execution: {exception}", err=True)


def _load_registry_output_mode() -> str:
    from pflow.core.settings import SettingsManager

    try:
        settings = SettingsManager().load()
        return settings.registry.output_mode
    except Exception:
        return "smart"


def _display_results(
    node_type: str,
    action: Any,
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    execution_time_ms: int,
    output_format: str,
    show_structure: bool,
    registry: Registry,
    verbose: bool,
    execution_id: str,
    output_mode: str,
) -> None:
    from pflow.execution.formatters.node_output_formatter import format_node_output

    if output_format == "json":
        click.echo(
            json.dumps(
                {
                    "success": action != "error",
                    "node_type": node_type,
                    "outputs": outputs,
                    "shared_store": shared_store if verbose else None,
                    "execution_time_ms": execution_time_ms,
                    "execution_id": execution_id,
                },
                indent=2,
                default=str,
            )
        )
        return

    formatted = format_node_output(
        node_type=node_type,
        action=action,
        outputs=outputs,
        shared_store=shared_store,
        execution_time_ms=execution_time_ms,
        registry=registry,
        format_type="structure" if show_structure else "text",
        verbose=verbose,
        output_mode=output_mode,
        execution_id=execution_id,
    )
    click.echo(formatted)


def _handle_execution_error(node_type: str, exception: Exception, verbose: bool) -> None:
    if verbose:
        click.echo(format_diagnostic(exception_to_diagnostics(exception)[0], verbose=verbose), err=True)
        return
    click.echo(f"❌ Node '{node_type}' execution failed: {exception}", err=True)


def _handle_unknown_node(node_type: str, nodes: dict[str, Any]) -> None:
    available = sorted(nodes.keys())
    click.echo(f"❌ Unknown node: {node_type}", err=True)
    if available:
        click.echo("   Available nodes include:", err=True)
        for candidate in available[:10]:
            click.echo(f"   - {candidate}", err=True)


def _handle_ambiguous_node(node_type: str, matches: list[str]) -> None:
    click.echo(f"❌ Ambiguous node '{node_type}'", err=True)
    click.echo("   Matches:", err=True)
    for match in sorted(matches):
        click.echo(f"   - {match}", err=True)
