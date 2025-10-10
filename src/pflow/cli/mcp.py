"""MCP (Model Context Protocol) CLI commands for pflow.

This Click group is invoked by main_wrapper.py when it detects "mcp" as the first
positional argument. The wrapper manipulates sys.argv to remove "mcp" before calling
this group, allowing normal Click command processing for the subcommands.

Architecture: main_wrapper.py -> mcp() group -> individual commands (add, list, sync, etc.)
"""

import hashlib
import json
import logging
import sys
import time
from typing import Optional

import click

from pflow.mcp import MCPRegistrar, MCPServerManager

logger = logging.getLogger(__name__)


@click.group(name="mcp")
def mcp() -> None:
    """Manage MCP server connections."""
    pass


@mcp.command(name="add")
@click.argument("config_files", nargs=-1, required=True, type=click.Path(exists=True))
def add(config_files: tuple) -> None:
    """Add MCP servers from standard JSON config files.

    Examples:
        # Add single config:
        pflow mcp add ./github.mcp.json

        # Add multiple configs:
        pflow mcp add ./github.mcp.json ./jira.mcp.json ./slack.mcp.json

    Config file format (standard MCP format):
    {
        "mcpServers": {
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
            },
            "composio": {
                "type": "http",
                "url": "https://api.composio.dev/mcp",
                "headers": {"Authorization": "Bearer ${COMPOSIO_API_KEY}"}
            }
        }
    }
    """
    from pathlib import Path

    manager = MCPServerManager()
    total_added = []

    for config_file in config_files:
        config_path = Path(config_file)

        try:
            # Add servers from this file
            added_servers = manager.add_servers_from_file(config_path)
            total_added.extend(added_servers)

            if added_servers:
                click.echo(f"✓ Added/updated {len(added_servers)} server(s) from {config_path.name}:")
                for server_name in added_servers:
                    click.echo(f"  - {server_name}")
            else:
                click.echo(f"⚠ No servers found in {config_path.name}")

        except FileNotFoundError:
            click.echo(f"Error: File not found: {config_path}", err=True)
            sys.exit(1)
        except ValueError as e:
            click.echo(f"Error in {config_path.name}: {e}", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"Error: Failed to add servers from {config_path.name}: {e}", err=True)
            sys.exit(1)

    if total_added:
        click.echo(f"\nSuccessfully configured {len(total_added)} MCP server(s).")
        click.echo("Run 'pflow mcp sync --all' to discover available tools from all servers.")
    else:
        click.echo("No servers were added.")


def _format_http_server(config: dict) -> list[str]:
    """Format HTTP server configuration for display.

    Args:
        config: Server configuration dictionary

    Returns:
        List of formatted output lines
    """
    lines = []
    lines.append(f"    URL: {config.get('url', 'N/A')}")

    if config.get("auth"):
        auth = config["auth"]
        lines.append(f"    Auth Type: {auth.get('type', 'N/A')}")

    if config.get("headers"):
        headers_str = ", ".join(f"{k}={v}" for k, v in config["headers"].items())
        lines.append(f"    Headers: {headers_str}")

    if config.get("timeout"):
        lines.append(f"    Timeout: {config['timeout']}s")

    return lines


def _format_stdio_server(config: dict) -> list[str]:
    """Format stdio server configuration for display.

    Args:
        config: Server configuration dictionary

    Returns:
        List of formatted output lines
    """
    command = config.get("command", "")
    args = " ".join(config.get("args", []))
    return [f"    Command: {command} {args}".rstrip()]


def _format_server_output(name: str, config: dict) -> None:
    """Format and display a single server's configuration.

    Args:
        name: Server name
        config: Server configuration dictionary
    """
    click.echo(f"\n  {name}:")
    transport = config.get("type", "stdio")
    click.echo(f"    Transport: {transport}")

    # Format transport-specific configuration
    lines = _format_http_server(config) if transport == "http" else _format_stdio_server(config)

    for line in lines:
        click.echo(line)

    # Format common configuration
    if config.get("env"):
        env_str = ", ".join(f"{k}={v}" for k, v in config["env"].items())
        click.echo(f"    Environment: {env_str}")

    if "created_at" in config:
        click.echo(f"    Created: {config['created_at']}")

    if "updated_at" in config:
        click.echo(f"    Updated: {config['updated_at']}")


@mcp.command(name="list")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_servers(output_json: bool) -> None:
    """List all configured MCP servers."""
    manager = MCPServerManager()

    try:
        servers = manager.get_all_servers()

        if output_json:
            click.echo(json.dumps(servers, indent=2))
            return

        if not servers:
            click.echo("No MCP servers configured.")
            click.echo("Add one with: pflow mcp add <name> <command>")
            return

        click.echo("Configured MCP servers:")
        for name, config in servers.items():
            _format_server_output(name, config)

    except Exception as e:
        click.echo(f"Error: Failed to list servers: {e}", err=True)
        sys.exit(1)


@mcp.command(name="remove")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Remove without confirmation")
def remove(name: str, force: bool) -> None:
    """Remove an MCP server configuration."""
    manager = MCPServerManager()
    registrar = MCPRegistrar(registry=None, manager=manager)

    try:
        # Check if server exists
        if not manager.get_server(name):
            click.echo(f"Error: Server '{name}' not found", err=True)
            sys.exit(1)

        # Count registered tools
        registered_tools = registrar.list_registered_tools(name)

        # Confirm removal
        if not force:
            msg = f"Remove server '{name}'?"
            if registered_tools:
                msg += f" This will also remove {len(registered_tools)} registered tools."
            if not click.confirm(msg):
                click.echo("Cancelled.")
                return

        # Remove tools from registry
        if registered_tools:
            removed = registrar.remove_server_tools(name)
            click.echo(f"  Removed {removed} tools from registry")

        # Remove server configuration
        if manager.remove_server(name):
            click.echo(f"✓ Removed MCP server '{name}'")
        else:
            click.echo(f"Warning: Server '{name}' was not found", err=True)

    except Exception as e:
        click.echo(f"Error: Failed to remove server: {e}", err=True)
        sys.exit(1)


def _validate_sync_arguments(name: Optional[str], all_servers: bool) -> None:
    """Validate sync command arguments.

    Args:
        name: Server name to sync
        all_servers: Whether to sync all servers

    Raises:
        SystemExit: If arguments are invalid
    """
    if not name and not all_servers:
        click.echo("Error: Specify a server name or use --all", err=True)
        sys.exit(1)

    if name and all_servers:
        click.echo("Error: Cannot specify both server name and --all", err=True)
        sys.exit(1)


def _sync_all_servers(manager: MCPServerManager, registrar: MCPRegistrar) -> None:
    """Sync tools from all configured servers.

    Args:
        manager: MCPServerManager instance
        registrar: MCPRegistrar instance
    """
    import json

    from pflow.registry import Registry

    servers = manager.list_servers()
    if not servers:
        click.echo("No MCP servers configured.")
        return

    click.echo(f"Syncing {len(servers)} servers...")
    results = registrar.sync_all_servers()

    total_discovered = 0
    total_registered = 0

    for result in results:
        server = result["server"]
        discovered = result["tools_discovered"]
        registered = result["tools_registered"]

        total_discovered += discovered
        total_registered += registered

        if "error" in result:
            click.echo(f"  ✗ {server}: {result['error']}", err=True)
        else:
            click.echo(f"  ✓ {server}: {discovered} discovered, {registered} registered")

    click.echo(f"\nTotal: {total_discovered} tools discovered, {total_registered} registered")

    # Update sync metadata after successful sync
    registry = Registry()
    registry.set_metadata("mcp_last_sync_time", time.time())

    # Store hash of current servers
    current_servers = sorted(servers)
    servers_hash = hashlib.sha256(json.dumps(current_servers).encode()).hexdigest()
    registry.set_metadata("mcp_servers_hash", servers_hash)


def _sync_single_server(name: str, manager: MCPServerManager, registrar: MCPRegistrar) -> None:
    """Sync tools from a single server.

    Args:
        name: Server name to sync
        manager: MCPServerManager instance
        registrar: MCPRegistrar instance

    Raises:
        SystemExit: If server not found or sync fails
    """
    if not manager.get_server(name):
        click.echo(f"Error: Server '{name}' not found", err=True)
        sys.exit(1)

    click.echo(f"Syncing server '{name}'...")
    result = registrar.sync_server(name)

    if "error" in result:
        click.echo(f"Error: {result['error']}", err=True)
        sys.exit(1)

    discovered = result["tools_discovered"]
    registered = result["tools_registered"]

    click.echo(f"✓ Discovered {discovered} tools")
    click.echo(f"✓ Registered {registered} tools in pflow registry")

    _display_registered_tools(name, registered, registrar)


def _display_registered_tools(server_name: str, registered_count: int, registrar: MCPRegistrar) -> None:
    """Display list of registered tools for a server.

    Args:
        server_name: Name of the server
        registered_count: Number of tools registered
        registrar: MCPRegistrar instance
    """
    if registered_count > 0:
        tools = registrar.list_registered_tools(server_name)
        click.echo("\nRegistered tools:")
        for tool_name in tools[:10]:  # Show first 10
            click.echo(f"  - {tool_name}")
        if len(tools) > 10:
            click.echo(f"  ... and {len(tools) - 10} more")


@mcp.command(name="sync")
@click.argument("name", required=False)
@click.option("--all", "-a", "all_servers", is_flag=True, help="Sync all configured servers")
def sync(name: Optional[str], all_servers: bool) -> None:
    """Discover and register tools from MCP servers.

    Examples:
        pflow mcp sync github        # Sync specific server
        pflow mcp sync --all         # Sync all servers
    """
    _validate_sync_arguments(name, all_servers)

    manager = MCPServerManager()
    registrar = MCPRegistrar(registry=None, manager=manager)

    try:
        if all_servers:
            _sync_all_servers(manager, registrar)
        else:
            if name:
                _sync_single_server(name, manager, registrar)
            else:
                click.echo("Error: No server name provided", err=True)
                return

    except Exception as e:
        click.echo(f"Error: Failed to sync: {e}", err=True)
        sys.exit(1)


def _get_tools_info_as_json(registrar: MCPRegistrar, tool_names: list[str]) -> str:
    """Get tools info and format as JSON."""
    tools_info = []
    for tool_name in tool_names:
        info = registrar.get_tool_info(tool_name)
        if info:
            tools_info.append(info)
    return json.dumps(tools_info, indent=2)


def _display_server_tools(registrar: MCPRegistrar, server: str, tool_names: list[str]) -> None:
    """Display tools for a specific server."""
    if not tool_names:
        click.echo(f"No tools registered for server '{server}'")
        click.echo(f"Run 'pflow mcp sync {server}' to discover tools")
        return

    click.echo(f"Registered tools for '{server}':")
    for tool_name in tool_names:
        info = registrar.get_tool_info(tool_name)
        if info:
            click.echo(f"\n  {tool_name}:")
            click.echo(f"    {info['description']}")
            if info["params"]:
                click.echo(f"    Parameters: {', '.join(p['key'] for p in info['params'])}")


def _group_tools_by_server(tool_names: list[str]) -> dict[str, list[str]]:
    """Group tool names by their server prefix."""
    tools_by_server: dict[str, list[str]] = {}
    for tool_name in tool_names:
        parts = tool_name.split("-", 2)
        if len(parts) >= 3:
            server_name = parts[1]
            if server_name not in tools_by_server:
                tools_by_server[server_name] = []
            tools_by_server[server_name].append(tool_name)
    return tools_by_server


def _display_all_tools_grouped(registrar: MCPRegistrar, tool_names: list[str]) -> None:
    """Display all tools grouped by server."""
    if not tool_names:
        click.echo("No MCP tools registered")
        click.echo("Run 'pflow mcp sync --all' to discover tools")
        return

    tools_by_server = _group_tools_by_server(tool_names)
    click.echo("Registered MCP tools:")

    for server_name, server_tools in sorted(tools_by_server.items()):
        click.echo(f"\n  {server_name} ({len(server_tools)} tools):")

        # Show first 5 tools
        for tool_name in server_tools[:5]:
            info = registrar.get_tool_info(tool_name)
            if info:
                click.echo(f"    - {tool_name}: {info['description'][:60]}...")

        # Show count of remaining tools
        if len(server_tools) > 5:
            click.echo(f"    ... and {len(server_tools) - 5} more")


@mcp.command(name="tools")
@click.argument("server", required=False)
@click.option("--all", "-a", "all_servers", is_flag=True, help="List tools from all servers")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def tools(server: Optional[str], all_servers: bool, output_json: bool) -> None:
    """List registered MCP tools.

    Examples:
        pflow mcp tools              # List all MCP tools
        pflow mcp tools github       # List tools from specific server
        pflow mcp tools --json       # Output as JSON
    """
    registrar = MCPRegistrar()

    try:
        if server:
            # List tools from specific server
            tool_names = registrar.list_registered_tools(server)

            if output_json:
                click.echo(_get_tools_info_as_json(registrar, tool_names))
            else:
                _display_server_tools(registrar, server, tool_names)
        else:
            # List all MCP tools
            tool_names = registrar.list_registered_tools()

            if output_json:
                click.echo(_get_tools_info_as_json(registrar, tool_names))
            else:
                _display_all_tools_grouped(registrar, tool_names)

    except Exception as e:
        click.echo(f"Error: Failed to list tools: {e}", err=True)
        sys.exit(1)


def _format_tool_header(tool_info: dict) -> None:
    """Format and display tool header information."""
    click.echo(f"Tool: {tool_info['node_name']}")
    click.echo(f"Server: {tool_info['server']}")
    click.echo(f"Tool Name: {tool_info['tool']}")
    click.echo(f"Description: {tool_info['description']}")
    click.echo(f"Module: {tool_info['module']}")
    click.echo(f"Class: {tool_info['class_name']}")


def _format_parameters(params: list[dict], title: str = "Parameters") -> None:
    """Format and display parameters or inputs."""
    if params:
        click.echo(f"\n{title}:")
        for param in params:
            required = " (required)" if param.get("required") else ""
            desc = f" - {param.get('description', '')}" if param.get("description") else ""
            click.echo(f"  - {param['key']}: {param['type']}{required}{desc}")
    else:
        click.echo(f"\n{title}: None")


def _format_outputs(outputs: list[dict]) -> None:
    """Format and display outputs."""
    if outputs:
        click.echo("\nOutputs:")
        for output in outputs:
            desc = f" - {output.get('description', '')}" if output.get("description") else ""
            click.echo(f"  - {output['key']}: {output['type']}{desc}")


def _suggest_similar_tools(registrar: MCPRegistrar, tool: str) -> None:
    """Suggest similar tools when a tool is not found."""
    all_tools = registrar.list_registered_tools()
    similar = [t for t in all_tools if tool.lower() in t.lower()]
    if similar:
        click.echo("\nSimilar tools:")
        for t in similar[:5]:
            click.echo(f"  - {t}")


@mcp.command(name="info")
@click.argument("tool")
def info(tool: str) -> None:
    """Show detailed information about an MCP tool.

    Example:
        pflow mcp info mcp-github-create-issue
    """
    registrar = MCPRegistrar()

    try:
        tool_info = registrar.get_tool_info(tool)

        if not tool_info:
            click.echo(f"Error: Tool '{tool}' not found", err=True)
            _suggest_similar_tools(registrar, tool)
            sys.exit(1)

        _format_tool_header(tool_info)
        _format_parameters(tool_info["params"])
        _format_outputs(tool_info["outputs"])

    except Exception as e:
        click.echo(f"Error: Failed to get tool info: {e}", err=True)
        sys.exit(1)
