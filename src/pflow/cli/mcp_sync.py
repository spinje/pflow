"""MCP server auto-discovery at CLI startup."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
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
        output_format=ctx.obj.get("output_format", "text") if ctx.obj else "text",
    )


def _check_mcp_sync_needed(config_path: Path, registry: Any, servers: list[str]) -> tuple[bool, str]:
    """Check if MCP sync is needed based on config changes.

    Args:
        config_path: Path to MCP configuration file
        registry: Registry instance for metadata storage
        servers: List of configured server names

    Returns:
        Tuple of (needs_sync, current_hash)
    """
    config_mtime = config_path.stat().st_mtime
    last_sync = registry.get_metadata("mcp_last_sync_time", 0)
    last_sync_hash = registry.get_metadata("mcp_servers_hash", "")

    # Calculate current servers hash using SHA256 for security
    current_servers = sorted(servers)
    current_hash = hashlib.sha256(json.dumps(current_servers).encode()).hexdigest()

    # Skip sync if config hasn't changed AND server list is same
    if config_mtime <= last_sync and current_hash == last_sync_hash:
        logger.debug(
            f"MCP config unchanged since last sync (mtime={config_mtime}, last_sync={last_sync}), skipping discovery"
        )
        return False, current_hash

    return True, current_hash


def _clean_old_mcp_entries(registry: Any) -> None:
    """Remove all existing MCP entries from registry for clean sync.

    Args:
        registry: Registry instance to clean
    """
    all_nodes = registry.list_nodes()
    existing_mcp_count = len([n for n in all_nodes if n.startswith("mcp-")])

    if existing_mcp_count > 0:
        # Load full registry including filtered nodes
        nodes = registry.load(include_filtered=True)
        removed = 0
        for node_name in list(nodes.keys()):
            if node_name.startswith("mcp-"):
                del nodes[node_name]
                removed += 1

        if removed > 0:
            registry.save(nodes)
            logger.debug(f"Removed {removed} old MCP entries for clean sync")


def _discover_and_register_servers(
    servers: list[str], discovery: Any, registrar: Any, show_progress: bool, verbose: bool
) -> tuple[int, list[str]]:
    """Discover tools from MCP servers and register them.

    Args:
        servers: List of server names to discover
        discovery: MCPDiscovery instance
        registrar: MCPRegistrar instance
        show_progress: Whether to show progress messages
        verbose: Whether to show verbose output

    Returns:
        Tuple of (total_tools_discovered, failed_servers)
    """
    total_tools = 0
    failed_servers = []

    for server_name in servers:
        try:
            if show_progress and verbose:
                click.echo(f"Discovering tools from MCP server '{server_name}'...", err=True)

            # Discover tools (pass verbose to control stderr output)
            tools = discovery.discover_tools(server_name, verbose=verbose)

            if tools:
                # Register the discovered tools
                registrar.register_tools(server_name, tools)
                total_tools += len(tools)

                if show_progress and verbose:
                    click.echo(f"  ✓ Discovered {len(tools)} tool(s) from {server_name}", err=True)
        except Exception as e:
            logger.debug(f"Failed to discover tools from {server_name}: {e}")
            failed_servers.append(server_name)
            if show_progress and verbose:
                click.echo(f"  ⚠ Failed to connect to {server_name}", err=True)

    return total_tools, failed_servers


def _auto_discover_mcp_servers(ctx: click.Context, verbose: bool) -> None:
    """Smart auto-discovery that only syncs when MCP config changes.

    Checks config file modification time and server list hash to determine
    if sync is needed. This eliminates unnecessary overhead on every pflow run.
    """
    try:
        from pflow.mcp import MCPDiscovery, MCPRegistrar, MCPServerManager
        from pflow.registry import Registry

        # Check if we should show progress messages
        output_controller = _get_output_controller(ctx)
        show_progress = output_controller.is_interactive()

        # Load MCP server configuration
        manager = MCPServerManager()
        config_path = manager.config_path

        # Check if config exists
        if not config_path.exists():
            # No config, nothing to sync
            return

        servers = manager.list_servers()
        if not servers:
            # No servers configured, nothing to do
            return

        # Check if sync is needed
        registry = Registry()
        needs_sync, current_hash = _check_mcp_sync_needed(config_path, registry, servers)

        if not needs_sync:
            return

        # Config changed or first run - do full sync
        if show_progress and not verbose:
            click.echo("🔄 MCP config changed, syncing servers...", err=True)

        # CRITICAL: Remove ALL existing MCP entries first
        # This handles renames cleanly
        _clean_old_mcp_entries(registry)

        # Now discover and register from all servers
        discovery = MCPDiscovery(manager)
        registrar = MCPRegistrar(registry=registry, manager=manager)

        total_tools, failed_servers = _discover_and_register_servers(
            servers, discovery, registrar, show_progress, verbose
        )

        # Update metadata for next run
        registry.set_metadata("mcp_last_sync_time", time.time())
        registry.set_metadata("mcp_servers_hash", current_hash)

        # Show summary
        if show_progress and total_tools > 0 and not verbose:
            click.echo(
                f"✓ Synced {total_tools} MCP tool(s) from {len(servers) - len(failed_servers)} server(s)", err=True
            )

        if show_progress and failed_servers and verbose:
            click.echo(f"⚠ Failed to connect to {len(failed_servers)} server(s): {', '.join(failed_servers)}", err=True)

    except ImportError as e:
        # MCP modules not available
        logger.debug(f"MCP modules not available: {e}")
    except Exception as e:
        # Log auto-discovery failure at debug level - this is optional functionality
        logger.debug(f"Failed to auto-discover MCP servers: {e}")
