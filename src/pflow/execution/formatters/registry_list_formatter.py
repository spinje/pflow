"""Shared formatter for registry list display.

This module provides formatting for node registry listings across CLI and MCP interfaces.
Returns markdown-formatted text matching CLI output.

Usage:
    >>> from pflow.execution.formatters.registry_list_formatter import format_registry_list
    >>> nodes = {"read-file": {...}, "write-file": {...}}
    >>> print(format_registry_list(nodes))
    Core Packages:
    ─────────────
    ...
"""

from typing import Any


def format_registry_list(nodes: dict[str, Any]) -> str:
    """Format registry node list as markdown (CLI parity).

    Args:
        nodes: Dictionary of nodes from Registry.load()

    Returns:
        Formatted markdown string

    Example:
        >>> nodes = {
        ...     "read-file": {"module": "pflow.nodes.file", "interface": {}},
        ...     "mcp-slack-SEND": {"module": "mcp.slack", "interface": {}}
        ... }
        >>> result = format_registry_list(nodes)
        >>> "Core Packages:" in result
        True
    """
    if not nodes:
        return "No nodes registered."

    # Filter out virtual mcp node
    filtered_nodes = {name: metadata for name, metadata in nodes.items() if name != "mcp"}

    # Group nodes by package
    grouped = _group_nodes_by_package(filtered_nodes)

    lines = []

    # Count totals
    total_core = sum(len(node_list) for node_list in grouped["core"].values())
    total_mcp = sum(len(node_list) for node_list in grouped["mcp"].values())
    total_user = sum(len(node_list) for node_list in grouped["user"].values())

    # Display Core Packages
    if grouped["core"]:
        lines.append("\nCore Packages:")
        lines.append("─" * 13)
        lines.extend(_format_package_section(grouped["core"], filtered_nodes, "core"))

    # Display MCP Servers
    if grouped["mcp"]:
        lines.append("\nMCP Servers:")
        lines.append("─" * 12)
        lines.extend(_format_package_section(grouped["mcp"], filtered_nodes, "mcp"))

    # Display User Nodes
    if grouped["user"]:
        lines.append("\nUser Nodes:")
        lines.append("─" * 11)
        lines.extend(_format_package_section(grouped["user"], filtered_nodes, "user"))

    # Summary
    lines.append(f"\nSummary: {total_core} core, {total_mcp} MCP, {total_user} user nodes")

    return "\n".join(lines)


def _group_nodes_by_package(nodes: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Group nodes by package type and name.

    Returns:
        Dict with 'core', 'mcp', 'user' keys containing package groups
    """
    grouped: dict[str, dict[str, list[str]]] = {
        "core": {},
        "mcp": {},
        "user": {},
    }

    for name, metadata in nodes.items():
        module = metadata.get("module", "")

        # Determine category - CHECK NODE NAME FIRST for MCP nodes
        # (MCP nodes have module "pflow.nodes.mcp.node" but we identify them by name)
        if name.startswith("mcp-"):
            category = "mcp"
            # Extract full server name from node ID (mcp-server-name-TOOL_NAME)
            # For mcp-composio-slack-SEND_MESSAGE -> "composio-slack"
            # For mcp-github-LIST_REPOS -> "github"
            parts = name.split("-")
            if len(parts) >= 3:
                # All parts between "mcp" and the tool name (last part, usually ALL_CAPS)
                # Check if last part looks like a tool name (contains uppercase or underscore)
                last_part = parts[-1]
                # Tool name is last part if uppercase/underscore, server is everything in between
                # Otherwise use everything after mcp-
                package = "-".join(parts[1:-1]) if (last_part.isupper() or "_" in last_part) else "-".join(parts[1:])
            else:
                package = "unknown"
        elif module.startswith("pflow.nodes."):
            category = "core"
            package = module.replace("pflow.nodes.", "").split(".")[0]
        else:
            category = "user"
            package = module.split(".")[0] if "." in module else "custom"

        if package not in grouped[category]:
            grouped[category][package] = []

        grouped[category][package].append(name)

    return grouped


def _format_package_section(
    packages: dict[str, list[str]], nodes: dict[str, Any], section_type: str = "core"
) -> list[str]:
    """Format a section of packages with full descriptions.

    Args:
        packages: Dict of package_name -> list of node names
        nodes: Full node metadata for description lookup
        section_type: "core", "mcp", or "user" (affects "nodes" vs "tools" label)

    Returns:
        List of formatted lines
    """
    lines = []

    for package, node_names in sorted(packages.items()):
        count = len(node_names)

        # MCP servers use "tools", others use "nodes"
        unit = ("tool" if count == 1 else "tools") if section_type == "mcp" else ("node" if count == 1 else "nodes")

        lines.append(f"\n{package} ({count} {unit})")

        for node in sorted(node_names):
            # Get description and truncate to 75 chars (CLI parity)
            desc = ""
            if node in nodes:
                full_desc = nodes[node].get("interface", {}).get("description", "")
                desc = full_desc[:72] + "..." if len(full_desc) > 75 else full_desc[:75]

            # Format with description inline (CLI parity)
            lines.append(f"  {node:25} {desc}")

    return lines
