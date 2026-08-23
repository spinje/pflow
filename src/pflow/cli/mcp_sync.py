"""MCP server auto-discovery at CLI startup."""

from __future__ import annotations

import logging
from typing import Any, cast

import click

from pflow.core.output_controller import OutputController

logger = logging.getLogger(__name__)


def _get_output_controller(ctx: click.Context) -> OutputController:
    """Get the OutputController from context, creating it if needed.

    Args:
        ctx: Click context

    Returns:
        OutputController instance
    """
    if ctx.obj and "output_controller" in ctx.obj:
        return cast(OutputController, ctx.obj["output_controller"])

    # Fallback: create one if not in context (shouldn't happen normally)
    return OutputController(
        print_flag=ctx.obj.get("print_flag", False) if ctx.obj else False,
    )


def _registry_reconciliation_needed(
    nodes: dict[str, dict[str, Any]],
    configs: dict[str, dict[str, Any]],
    stored_fingerprints: dict[str, Any],
) -> bool:
    """Return whether full reconciliation has cleanup work beyond discovery."""
    from pflow.mcp import MCPRegistrar

    removals = MCPRegistrar.full_reconciliation_removals(nodes, set(configs))
    return bool(removals or set(stored_fingerprints) - set(configs))


def _show_sync_result(batch: Any, *, show_progress: bool, verbose: bool) -> None:
    """Render interactive auto-sync results without contaminating structured output."""
    if not show_progress:
        return
    if batch.aborted_reason:
        click.echo(f"⚠ {batch.aborted_reason}", err=True)
        return

    successful = [result for result in batch.servers if result.error is None]
    failed = [result.server for result in batch.servers if result.error is not None]
    if verbose:
        for result in successful:
            click.echo(f"  ✓ Discovered {result.tools_discovered} tool(s) from {result.server}", err=True)
    elif successful:
        total_tools = sum(result.tools_discovered for result in successful)
        click.echo(f"✓ Synced {total_tools} MCP tool(s) from {len(successful)} server(s)", err=True)
    if failed:
        click.echo(f"⚠ Failed to connect to MCP server(s): {', '.join(failed)}", err=True)


def _auto_discover_mcp_servers(ctx: click.Context, verbose: bool) -> None:
    """Reconcile only MCP servers whose persisted configuration changed."""
    try:
        from pflow.mcp import MCPDiscovery, MCPRegistrar, MCPServerManager
        from pflow.mcp.sync_state import (
            MCP_SERVER_FINGERPRINTS_KEY,
            fingerprint_server_configs,
            parse_server_fingerprints,
        )
        from pflow.registry import Registry

        output_controller = _get_output_controller(ctx)
        show_progress = output_controller.is_interactive()
        manager = MCPServerManager()
        configs = manager.get_all_servers_if_configured()
        if configs is None:
            return

        current_fingerprints = fingerprint_server_configs(configs)
        registry = Registry()
        missing = object()
        raw_fingerprints = registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY, missing)
        stored_fingerprints, fingerprints_valid = parse_server_fingerprints(raw_fingerprints)
        due_servers = [name for name in configs if stored_fingerprints.get(name) != current_fingerprints[name]]

        inspection_nodes = registry.load(include_filtered=True)
        cleanup_needed = _registry_reconciliation_needed(
            inspection_nodes,
            configs,
            stored_fingerprints,
        )
        if not due_servers and fingerprints_valid and not cleanup_needed:
            return

        if show_progress and not verbose:
            click.echo("🔄 MCP configuration changed, syncing servers...", err=True)

        discovery = MCPDiscovery(manager)
        registrar = MCPRegistrar(registry=registry, manager=manager, discovery=discovery)

        def show_server_start(server_name: str) -> None:
            if show_progress and verbose:
                click.echo(f"Discovering tools from MCP server '{server_name}'...", err=True)

        batch = registrar.sync_servers(
            due_servers,
            reconcile_all=True,
            verbose=verbose,
            on_server_start=show_server_start,
        )

        _show_sync_result(batch, show_progress=show_progress, verbose=verbose)

    except ImportError as error:
        logger.debug(f"MCP modules not available: {error}")
    except Exception as error:
        logger.debug(f"Failed to auto-discover MCP servers: {error}")
