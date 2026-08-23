"""MCP (Model Context Protocol) CLI commands for pflow.

Registered as a subgroup of the PflowCLI group in main.py via cli.add_command(mcp).
Click handles subcommand routing natively.
"""

import json
import logging
import sys
from typing import ClassVar

import click

from pflow.core.suggestion_utils import find_similar_items, format_did_you_mean
from pflow.mcp import MCPRegistrar, MCPServerManager

logger = logging.getLogger(__name__)


class MCPGroup(click.Group):
    """MCP command group with migration hints for removed subcommands."""

    _removed_commands: ClassVar[dict[str, str]] = {
        "tools": "Replaced by: pflow mcp list [keyword...]",
        "info": "Replaced by: pflow mcp describe <tool>",
    }

    def resolve_command(
        self,
        ctx: click.Context,
        args: list[str],
    ) -> tuple[str | None, click.Command | None, list[str]]:
        if args and args[0] in self._removed_commands:
            click.echo(f"Error: 'mcp {args[0]}' command was removed.\n{self._removed_commands[args[0]]}", err=True)
            ctx.exit(1)
        return super().resolve_command(ctx, args)


@click.group(name="mcp", cls=MCPGroup)
def mcp() -> None:
    """Manage MCP server connections."""
    pass


def _is_json_string(value: str) -> bool:
    """Check if a string looks like JSON (starts with { or [)."""
    stripped = value.strip()
    return stripped.startswith("{") or stripped.startswith("[")


def _is_server_config(config: dict) -> bool:
    """Check if a dict looks like a server config (has command/url, not nested servers)."""
    return "command" in config or "url" in config


def _add_from_json_string(manager: MCPServerManager, json_str: str) -> list[str]:
    """Add servers from a raw JSON string.

    Supports three formats:
    1. Full MCP format: {"mcpServers": {"name": {...}}}
    2. Direct server map: {"name": {"command": ...}}
    3. Single server (name as key): {"github": {"command": "npx", ...}}

    Args:
        manager: MCPServerManager instance
        json_str: Raw JSON string with MCP config

    Returns:
        List of added server names

    Raises:
        ValueError: If JSON is invalid or missing required fields
    """
    try:
        config = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    # Format 1: Full MCP format with mcpServers wrapper
    if "mcpServers" in config:
        return manager.add_servers_from_config(config)

    # Format 2 & 3: Direct server map (one or more servers)
    # Check if all values are server configs (have command or url)
    if all(isinstance(v, dict) and _is_server_config(v) for v in config.values()):
        wrapped = {"mcpServers": config}
        return manager.add_servers_from_config(wrapped)

    raise ValueError(
        "Invalid JSON format. Expected one of:\n"
        '  {"mcpServers": {"name": {...}}}  - Full MCP format\n'
        '  {"name": {"command": "...", ...}}  - Direct server config'
    )


def _validate_timeout_flags(timeout: int | None, sse_timeout: int | None) -> None:
    """Validate timeout CLI flags before any config is saved.

    Args:
        timeout: HTTP connection timeout in seconds
        sse_timeout: SSE read timeout in seconds

    Raises:
        click.BadParameter: If timeout values are invalid
    """
    if timeout is not None:
        if timeout <= 0:
            raise click.BadParameter("Timeout must be a positive number", param_hint="'--timeout'")
        if timeout > 600:
            raise click.BadParameter("Timeout cannot exceed 600 seconds (10 minutes)", param_hint="'--timeout'")
    if sse_timeout is not None and sse_timeout <= 0:
        raise click.BadParameter("SSE timeout must be a positive number", param_hint="'--sse-timeout'")


def _apply_http_timeouts(
    manager: MCPServerManager,
    server_names: list[str],
    timeout: int | None,
    sse_timeout: int | None,
) -> None:
    """Apply timeout overrides to newly added HTTP servers.

    Args:
        manager: MCPServerManager instance
        server_names: Names of servers to update
        timeout: HTTP connection timeout in seconds
        sse_timeout: SSE read timeout in seconds
    """
    config = manager.load()
    servers = config.get("mcpServers", {})
    updated = False
    for name in server_names:
        server = servers.get(name, {})
        if server.get("type") == "http":
            if timeout is not None:
                server["timeout"] = timeout
            if sse_timeout is not None:
                server["sse_timeout"] = sse_timeout
            updated = True
    if updated:
        manager.save(config)
    else:
        click.echo("⚠ --timeout/--sse-timeout flags only apply to HTTP servers, ignored for stdio servers", err=True)


@mcp.command(name="add")
@click.argument("config_sources", nargs=-1, required=True)
@click.option(
    "--timeout", type=int, default=None, help="HTTP connection timeout in seconds (applies to HTTP servers only)"
)
@click.option(
    "--sse-timeout", type=int, default=None, help="SSE read timeout in seconds (applies to HTTP servers only)"
)
def add(config_sources: tuple, timeout: int | None, sse_timeout: int | None) -> None:
    """Add MCP servers from config files or raw JSON.

    Examples:
        # Add from config file:
        pflow mcp add ./github.mcp.json

        # Add from raw JSON (simple format):
        pflow mcp add '{"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}}'

        # Add HTTP server with custom timeout:
        pflow mcp add '{"slack": {"type": "http", "url": "https://mcp.example.com/slack"}}' --timeout 60

        # Add from raw JSON (full MCP format, compatible with Claude Desktop):
        pflow mcp add '{"mcpServers": {"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}}}'

    Supported JSON formats:
        # Simple (recommended for CLI):
        {"server-name": {"command": "...", "args": [...]}}

        # Full MCP format (compatible with config files):
        {"mcpServers": {"server-name": {...}}}
    """
    from pathlib import Path

    # Validate timeout flags before saving anything
    _validate_timeout_flags(timeout, sse_timeout)

    manager = MCPServerManager()
    total_added = []

    for config_source in config_sources:
        try:
            # Check if it's a JSON string or a file path
            if _is_json_string(config_source):
                # Handle raw JSON string
                added_servers = _add_from_json_string(manager, config_source)
                source_name = "JSON input"
            else:
                # Handle file path
                config_path = Path(config_source)
                if not config_path.exists():
                    click.echo(f"Error: File not found: {config_path}", err=True)
                    sys.exit(1)
                added_servers = manager.add_servers_from_file(config_path)
                source_name = config_path.name

            total_added.extend(added_servers)

            if added_servers:
                click.echo(f"✓ Added/updated {len(added_servers)} server(s) from {source_name}:")
                for server_name in added_servers:
                    click.echo(f"  - {server_name}")
            else:
                click.echo(f"⚠ No servers found in {source_name}")

        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"Error: Failed to add servers: {e}", err=True)
            sys.exit(1)

    # Apply timeout overrides to newly added HTTP servers
    if total_added and (timeout is not None or sse_timeout is not None):
        _apply_http_timeouts(manager, total_added, timeout, sse_timeout)

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
    if config.get("sse_timeout"):
        lines.append(f"    SSE Timeout: {config['sse_timeout']}s")

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


@mcp.command(name="servers")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def servers(output_json: bool) -> None:
    """List all configured MCP servers."""
    manager = MCPServerManager()

    try:
        servers = manager.get_all_servers()

        if output_json:
            click.echo(json.dumps(servers, indent=2))
            return

        if not servers:
            click.echo("No MCP servers configured.")
            click.echo("Add one with: pflow mcp add ./server-config.json")
            return

        click.echo("Configured MCP servers:")
        for name, config in servers.items():
            _format_server_output(name, config)

    except Exception as e:
        click.echo(f"Error: Failed to list servers: {e}", err=True)
        sys.exit(1)


def _load_mcp_registry_entries(registrar: MCPRegistrar) -> dict[str, dict]:
    nodes = registrar.registry.load()
    return {
        node_name: entry
        for node_name, entry in nodes.items()
        if node_name.startswith("mcp-") and isinstance(entry.get("interface"), dict)
    }


def _matches_keyword(keyword: str, text: str) -> bool:
    if keyword == keyword.lower():
        return keyword in text.lower()
    return keyword in text


def _matches_all_keywords(entry: dict, keywords: tuple[str, ...]) -> bool:
    interface = entry.get("interface", {})
    description = str(interface.get("description", ""))
    metadata = interface.get("mcp_metadata", {})
    server = str(metadata.get("server", ""))
    tool = str(metadata.get("tool", ""))
    return all(
        any(
            _matches_keyword(keyword, candidate)
            for candidate in (tool, description, server, str(entry.get("node_name", "")))
        )
        for keyword in keywords
    )


def _highlight_matches(text: str, keywords: tuple[str, ...]) -> str:
    highlighted = text
    for keyword in keywords:
        highlighted = _highlight_keyword(highlighted, keyword)
    return highlighted


def _highlight_keyword(text: str, keyword: str) -> str:
    if not keyword:
        return text

    haystack = text if keyword != keyword.lower() else text.lower()
    needle = keyword if keyword != keyword.lower() else keyword.lower()
    index = 0
    parts: list[str] = []
    while True:
        match_index = haystack.find(needle, index)
        if match_index == -1:
            parts.append(text[index:])
            break
        parts.append(text[index:match_index])
        parts.append(click.style(text[match_index : match_index + len(keyword)], bold=True))
        index = match_index + len(keyword)
    return "".join(parts)


def _group_entries_by_server(entries: dict[str, dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for node_name, entry in entries.items():
        interface = entry.get("interface", {})
        metadata = interface.get("mcp_metadata", {})
        server = str(metadata.get("server", "unknown"))
        grouped.setdefault(server, []).append({
            "node_name": node_name,
            "description": str(interface.get("description", "")),
            "tool": str(metadata.get("tool", node_name)),
        })
    return grouped


def _format_tool_summary(grouped_entries: dict[str, list[dict]], configured_servers: list[str]) -> str:
    total_tools = sum(len(entries) for entries in grouped_entries.values())
    server_count = len(configured_servers) if configured_servers else len(grouped_entries)
    lines = [f"MCP Tools ({total_tools} total across {server_count} servers)"]

    all_servers = sorted(set(configured_servers) | set(grouped_entries))
    for server in all_servers:
        server_entries = grouped_entries.get(server, [])
        lines.append("")
        lines.append(f"{server} ({len(server_entries)} tools)")
        if not server_entries:
            lines.append(f"  No registered tools. Run: pflow mcp sync {server}")
            continue
        tool_hints = ", ".join(entry["tool"] for entry in server_entries[:5])
        if len(server_entries) > 5:
            tool_hints += "..."
        lines.append(f"  {tool_hints}")
    return "\n".join(lines)


def _format_filtered_tools(grouped_entries: dict[str, list[dict]], keywords: tuple[str, ...]) -> str:
    total_matches = sum(len(entries) for entries in grouped_entries.values())
    lines = [f"Matching MCP tools ({total_matches} results):"]
    for server, entries in sorted(grouped_entries.items()):
        lines.append("")
        lines.append(f"{server}:")
        for entry in entries:
            tool_name = _highlight_matches(entry["node_name"], keywords)
            description = _highlight_matches(entry["description"], keywords)
            lines.append(f"  {tool_name} — {description}")
    return "\n".join(lines)


@mcp.command(name="list")
@click.argument("keywords", nargs=-1)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_tools(keywords: tuple[str, ...], output_json: bool) -> None:
    """List MCP tools, optionally filtered by keywords.

    Without keywords, shows a grouped-by-server summary with tool counts
    and sample tool names. With keywords, shows matching tools with full
    details (name + description), filtered by AND logic across all keywords.

    \b
    Examples:
        pflow mcp list                 # Summary of all servers + tool counts
        pflow mcp list slack           # Tools matching "slack"
        pflow mcp list slack send      # Tools matching both "slack" AND "send"
    """
    registrar = MCPRegistrar()
    manager = MCPServerManager()

    try:
        entries = _load_mcp_registry_entries(registrar)
        configured_servers = manager.list_servers()

        if output_json:
            if not keywords:
                click.echo(
                    json.dumps(
                        {
                            "total_tools": len(entries),
                            "servers": _group_entries_by_server(entries),
                        },
                        indent=2,
                    )
                )
                return

            filtered_entries = {
                node_name: entry
                for node_name, entry in entries.items()
                if _matches_all_keywords({"node_name": node_name, **entry}, keywords)
            }
            click.echo(json.dumps(_group_entries_by_server(filtered_entries), indent=2))
            return

        if not keywords:
            click.echo(_format_tool_summary(_group_entries_by_server(entries), configured_servers))
            return

        filtered_entries = {
            node_name: entry
            for node_name, entry in entries.items()
            if _matches_all_keywords({"node_name": node_name, **entry}, keywords)
        }
        if not filtered_entries:
            click.echo("No MCP tools match those keywords.", err=True)
            click.echo("Try: pflow mcp list", err=True)
            click.echo('Or: pflow mcp find "what you want to do"', err=True)
            return
        click.echo(_format_filtered_tools(_group_entries_by_server(filtered_entries), keywords))
    except Exception as e:
        click.echo(f"Error: Failed to list tools: {e}", err=True)
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
        registered_tools = registrar.list_registered_tools(name, include_filtered=True)

        # Confirm removal
        if not force:
            msg = f"Remove server '{name}'?"
            if registered_tools:
                msg += f" This will also remove {len(registered_tools)} registered tools."
            if not click.confirm(msg):
                click.echo("Cancelled.")
                return

        # Remove exact owned tools and the server fingerprint before config removal.
        removed = registrar.remove_server_tools(name)
        if removed:
            click.echo(f"  Removed {removed} tools from registry")

        # Remove server configuration
        if manager.remove_server(name):
            click.echo(f"✓ Removed MCP server '{name}'")
        else:
            click.echo(f"Warning: Server '{name}' was not found", err=True)

    except Exception as e:
        click.echo(f"Error: Failed to remove server: {e}", err=True)
        sys.exit(1)


def _validate_sync_arguments(name: str | None, all_servers: bool) -> None:
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


def _sync_all_servers(manager: MCPServerManager, registrar: MCPRegistrar, verbose: bool = False) -> None:
    """Sync tools from all configured servers.

    Args:
        manager: MCPServerManager instance
        registrar: MCPRegistrar instance
        verbose: Whether to show technical error details
    """
    click.echo("Syncing all configured servers...")
    batch = registrar.sync_servers(None, reconcile_all=True)
    if batch.config_missing and not batch.aborted_reason:
        click.echo("No MCP server configuration found.")
        return
    if batch.aborted_reason:
        click.echo(f"Error: {batch.aborted_reason}", err=True)
        sys.exit(1)

    total_discovered = 0
    total_registered = 0
    has_failures = False

    for result in batch.servers:
        server = result.server
        discovered = result.tools_discovered
        registered = result.tools_registered

        total_discovered += discovered
        total_registered += registered

        if result.error is not None:
            has_failures = True
            click.echo(f"  ✗ {server}: {result.error}", err=True)
            diagnostic = result.diagnostic
            if diagnostic:
                if diagnostic.suggestions:
                    for suggestion in diagnostic.suggestions:
                        click.echo(f"    → {suggestion}", err=True)
                context = diagnostic.context or {}
                technical = context.get("technical_details")
                if verbose and technical:
                    click.echo(f"    Detail: {technical[:200]}", err=True)
        else:
            click.echo(f"  ✓ {server}: {discovered} discovered, {registered} registered")

    click.echo(f"\nTotal: {total_discovered} tools discovered, {total_registered} registered")

    if has_failures and not verbose:
        click.echo("Run with --verbose for technical error details.", err=True)


def _sync_single_server(name: str, manager: MCPServerManager, registrar: MCPRegistrar, verbose: bool = False) -> None:
    """Sync tools from a single server.

    Args:
        name: Server name to sync
        manager: MCPServerManager instance
        registrar: MCPRegistrar instance
        verbose: Whether to show technical error details

    Raises:
        SystemExit: If server not found or sync fails
    """
    if manager.get_server(name) is None:
        click.echo(f"Error: Server '{name}' not found", err=True)
        sys.exit(1)

    click.echo(f"Syncing server '{name}'...")
    batch = registrar.sync_servers([name], reconcile_all=False)
    if batch.aborted_reason:
        click.echo(f"Error: {batch.aborted_reason}", err=True)
        sys.exit(1)
    result = batch.servers[0]

    if result.error is not None:
        diagnostic = result.diagnostic
        if diagnostic:
            from pflow.core.diagnostic_render import format_diagnostic

            click.echo(format_diagnostic(diagnostic, verbose=verbose), err=True)
        else:
            click.echo(f"Error: {result.error}", err=True)
        sys.exit(1)

    discovered = result.tools_discovered
    registered = result.tools_registered

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
@click.option("--verbose", "-v", is_flag=True, help="Show technical error details for failed servers")
def sync(name: str | None, all_servers: bool, verbose: bool) -> None:
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
            _sync_all_servers(manager, registrar, verbose=verbose)
        else:
            if name:
                _sync_single_server(name, manager, registrar, verbose=verbose)
            else:
                click.echo("Error: No server name provided", err=True)
                return

    except Exception as e:
        click.echo(f"Error: Failed to sync: {e}", err=True)
        sys.exit(1)


@mcp.command(name="find")
@click.argument("query")
def find_tools(query: str) -> None:
    """Search MCP tools by intent using LLM."""
    from pflow.cli.find_errors import handle_discovery_error, validate_discovery_query
    from pflow.core.llm_config import inject_settings_env_vars
    from pflow.registry.discovery import find_components

    inject_settings_env_vars()
    validated_query = validate_discovery_query(query, "mcp find")
    registrar = MCPRegistrar()
    entries = _load_mcp_registry_entries(registrar)

    if not entries:
        click.echo("No MCP tools are registered yet.")
        click.echo("Run 'pflow mcp sync --all' to discover tools.")
        return

    try:
        result = find_components(validated_query, registry_metadata=entries, include_workflows=False)
    except Exception as exception:
        handle_discovery_error(
            exception,
            discovery_type="registry",
            alternative_commands=[
                ("pflow mcp list", "Browse registered MCP tools"),
                ("pflow mcp describe <tool>", "Show detailed MCP tool info"),
            ],
        )
        sys.exit(1)

    if not result.node_ids:
        click.echo("No MCP tools matched that description.")
        click.echo("Try 'pflow mcp list' or a broader description.", err=True)
        return

    selected_entries = {node_id: entries[node_id] for node_id in result.node_ids if node_id in entries}
    click.echo(_format_filtered_tools(_group_entries_by_server(selected_entries), ()))
    if result.reasoning:
        click.echo("")
        click.echo(f"Reasoning: {result.reasoning}")


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
            required = " (required)" if param.get("required", True) else ""
            desc = f" - {param.get('description', '')}" if param.get("description") else ""
            click.echo(f"  - {param['key']}: {param['type']}{required}{desc}")
    else:
        click.echo(f"\n{title}: None")


_MAX_DECLARED_OUTPUT_DEPTH = 10
_MAX_DECLARED_OUTPUT_PATHS = 100


def _schema_type_label(schema: dict) -> str:
    """Return a readable JSON Schema type label."""
    schema_type = schema.get("type")
    if schema_type is None:
        if "properties" in schema:
            schema_type = "object"
        elif "items" in schema:
            schema_type = "array"
        else:
            schema_type = "any"
    if isinstance(schema_type, list):
        return " | ".join(str(item) for item in schema_type)
    if schema_type == "any":
        for keyword in ("anyOf", "oneOf"):
            alternatives = schema.get(keyword)
            if isinstance(alternatives, list):
                labels = [_schema_type_label(item) for item in alternatives if isinstance(item, dict)]
                if labels:
                    return " | ".join(dict.fromkeys(labels))
    return str(schema_type)


def _resolve_schema_pointer(root_schema: dict, ref: str) -> dict | None:
    """Resolve one local JSON Pointer target."""
    if ref == "#":
        return root_schema
    if not ref.startswith("#/"):
        return None
    target: object = root_schema
    for raw_segment in ref[2:].split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or segment not in target:
            return None
        target = target[segment]
    return target if isinstance(target, dict) else None


def _resolve_local_schema_ref(root_schema: dict, field_schema: dict) -> dict:
    """Resolve chained local JSON Pointer references with a cycle guard."""
    current = field_schema
    visited: set[str] = set()
    while isinstance(ref := current.get("$ref"), str) and ref not in visited:
        visited.add(ref)
        target = _resolve_schema_pointer(root_schema, ref)
        if target is None:
            break
        current = target
    return current


def _schema_array_items(schema: dict) -> dict | None:
    """Return an array's item schema when its type declaration includes array."""
    schema_type = schema.get("type")
    is_array = schema_type == "array" or (isinstance(schema_type, list) and "array" in schema_type)
    items = schema.get("items")
    return items if is_array and isinstance(items, dict) else None


def _schema_combinator_branches(schema: dict) -> list[dict]:
    """Return object-like branches from JSON Schema union combinators."""
    branches: list[dict] = []
    for keyword in ("anyOf", "oneOf"):
        alternatives = schema.get(keyword)
        if isinstance(alternatives, list):
            branches.extend(item for item in alternatives if isinstance(item, dict))
    return branches


def _schema_children(field_schema: dict, path: str) -> list[tuple[dict, str, bool]]:
    """Return nested schemas with their display paths and path-emission flag."""
    children: list[tuple[dict, str, bool]] = []
    properties = field_schema.get("properties")
    if isinstance(properties, dict):
        children.extend(
            (child_schema, f"{path}.{name}", True)
            for name, child_schema in properties.items()
            if isinstance(child_schema, dict)
        )

    items = _schema_array_items(field_schema)
    if items is not None:
        children.append((items, f"{path}[0]", True))

    # Union branches describe the same parent path, so only emit their children.
    children.extend((branch, path, False) for branch in _schema_combinator_branches(field_schema))
    return children


def _flatten_declared_output_paths(schema: dict, prefix: str = "result") -> tuple[list[tuple[str, str]], bool]:
    """Flatten reliable JSON Schema properties into result-prefixed hints."""
    paths: list[tuple[str, str]] = []
    seen_paths: set[str] = set()
    truncated = False

    def walk(field_schema: dict, path: str, *, include_path: bool = True, depth: int = 0) -> None:
        nonlocal truncated
        # Bound recursive/branching schemas while keeping ordinary nested tool
        # results useful and terminal output predictable.
        if depth > _MAX_DECLARED_OUTPUT_DEPTH:
            truncated = True
            return
        field_schema = _resolve_local_schema_ref(schema, field_schema)

        if include_path and path not in seen_paths:
            if len(paths) >= _MAX_DECLARED_OUTPUT_PATHS:
                truncated = True
                return
            paths.append((path, _schema_type_label(field_schema)))
            seen_paths.add(path)

        # Optional structured values are commonly represented as an object
        # branch plus a null branch. Traverse branches without repeating the
        # parent path so their nested properties remain statically discoverable.
        for child_schema, child_path, emit_path in _schema_children(field_schema, path):
            walk(child_schema, child_path, include_path=emit_path, depth=depth + 1)

    walk(schema, prefix, include_path=False)
    return paths, truncated


def _format_outputs(outputs: list[dict], output_schema: dict | None = None) -> None:
    """Format runtime outputs and side-effect-free schema path hints."""
    if outputs:
        click.echo("\nOutputs:")
        for output in outputs:
            desc = f" - {output.get('description', '')}" if output.get("description") else ""
            click.echo(f"  - {output['key']}: {output['type']}{desc}")

    declared_paths, truncated = _flatten_declared_output_paths(output_schema or {})
    if declared_paths:
        click.echo("\nDeclared output paths (from server schema):")
        for path, type_label in declared_paths:
            click.echo(f"  - {path}: {type_label}")
        if truncated:
            click.echo("  - ... (truncated)")
        click.echo(
            "  Hints only; server declarations may differ. `pflow probe` executes the tool to show observed paths."
        )


def _suggest_similar_tools(registrar: MCPRegistrar, tool: str) -> None:
    """Suggest similar tools when a tool is not found."""
    all_tools = registrar.list_registered_tools()

    # Find similar tools using shared utility
    suggestions = find_similar_items(tool, all_tools, max_results=5, method="substring")

    # Format and display message
    message = format_did_you_mean(tool, suggestions, item_type="tool", fallback_items=all_tools, max_fallback=10)

    click.echo(f"\n{message}")


def _resolve_tool_id(tool: str, registrar: MCPRegistrar) -> str:
    """Resolve a user-provided tool ID, handling ambiguity."""
    from pflow.registry.node_id import normalize_node_id

    available_nodes = set(registrar.registry.load().keys())
    resolved = normalize_node_id(tool, available_nodes)

    if resolved is not None:
        return resolved

    # normalize_node_id returns None for both not-found and ambiguous.
    # Check for ambiguity so we can show candidates instead of a generic error.
    normalized_check = tool.replace("-", "_")
    matches = [node_id for node_id in available_nodes if node_id.endswith(tool) or node_id.endswith(normalized_check)]
    if len(matches) > 1:
        click.echo(f"Error: Ambiguous tool '{tool}'", err=True)
        click.echo("  Matches:", err=True)
        for match in sorted(matches):
            click.echo(f"  - {match}", err=True)
        sys.exit(1)

    return tool


@mcp.command(name="describe")
@click.argument("tool")
def describe_tool(tool: str) -> None:
    """Show detailed information about an MCP tool.

    \b
    Shows: parameters (name, type, required/optional), output type,
    and .pflow.md usage snippet.
    \b
    Interpreting results:
      Parameters with defaults   → usually optional
      Parameters without defaults → always required
      Output type "Any"          → probe to discover actual structure
    \b
    Example:
        pflow mcp describe mcp-slack-SEND_MESSAGE
    """
    registrar = MCPRegistrar()
    lookup_id = _resolve_tool_id(tool, registrar)

    try:
        tool_info = registrar.get_tool_info(lookup_id)

        if not tool_info:
            click.echo(f"Error: Tool '{tool}' not found", err=True)
            _suggest_similar_tools(registrar, tool)
            sys.exit(1)

        _format_tool_header(tool_info)
        _format_parameters(tool_info["params"])
        _format_outputs(tool_info["outputs"], tool_info.get("output_schema"))

        # Add .pflow.md usage snippet
        tool_name = tool_info["node_name"]
        click.echo("\nUsage in .pflow.md:\n")
        click.echo("    ### step-name")
        click.echo("")
        click.echo("    Describe what this step does and why.")
        click.echo("")
        click.echo(f"    - type: {tool_name}")
        params = tool_info.get("params", [])
        shown = 0
        for param in params[:3]:
            key = param.get("key", "")
            if key:
                # First param gets a literal, subsequent get template refs
                ptype = param.get("type", "str").lower()
                if shown == 0:
                    placeholder = "value"
                elif ptype in ("int", "integer", "number"):
                    placeholder = "0"
                elif ptype in ("bool", "boolean"):
                    placeholder = "true"
                else:
                    placeholder = "${previous-step.response}"
                click.echo(f"    - {key}: {placeholder}")
                shown += 1

    except Exception as e:
        click.echo(f"Error: Failed to get tool info: {e}", err=True)
        sys.exit(1)


@mcp.command(name="serve")
@click.option("--debug", is_flag=True, help="Enable debug logging")
def serve(debug: bool) -> None:
    """Run pflow as an MCP server (stdio transport).

    This starts an MCP server that exposes pflow's workflow building and
    execution capabilities as programmatic tools for AI agents.

    The server uses stdio transport where:
    - stdin: Receives JSON-RPC requests from clients
    - stdout: Sends JSON-RPC responses (protocol only)
    - stderr: All logging output

    Example:
        # Start the server (usually done by AI agents automatically)
        pflow mcp serve

        # With debug logging
        pflow mcp serve --debug

    The server exposes 13 tools for agents to:
    - Discover existing workflows and nodes
    - Execute workflows with structured output
    - Validate workflows before execution
    - Save workflows to the global library
    - Configure settings and API keys

    Note: This command is typically invoked by AI agents/clients,
    not directly by users.
    """
    try:
        from pflow.mcp_server.main import main as mcp_server_main
    except ImportError:
        click.echo(
            "Error: MCP server dependencies not installed.\n"
            "Install with: uv tool install pflow-cli (or pip install 'mcp[cli]>=1.17.0').",
            err=True,
        )
        sys.exit(1)

    # Run the MCP server (synchronous - FastMCP manages its own event loop)
    try:
        mcp_server_main(debug=debug)
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C
        sys.exit(0)
    except Exception as e:
        click.echo(f"Error: MCP server failed: {e}", err=True)
        sys.exit(1)
