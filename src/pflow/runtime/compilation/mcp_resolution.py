"""MCP node type resolution for the compilation pipeline.

Handles parsing of MCP node type strings (mcp-<server>-<tool>), registry
validation, and user-friendly error suggestions for missing MCP tools.
"""

import logging

from pflow.core.suggestion_utils import find_similar_items
from pflow.registry import Registry

logger = logging.getLogger(__name__)


def _check_registry_for_mcp(
    registry: Registry,
) -> tuple[bool, list[str]]:
    """Check if registry supports MCP validation.

    Args:
        registry: Registry instance to check

    Returns:
        Tuple of (should_validate, available_nodes)
    """
    try:
        # Try to get nodes from registry
        if hasattr(registry, "load"):
            nodes = registry.load()
            if nodes and isinstance(nodes, dict):
                available_nodes = list(nodes.keys())
                # Only validate if we have a real registry with actual nodes
                # Don't validate for test/mock registries
                return len(available_nodes) > 0, available_nodes
    except Exception:
        # If registry doesn't support load() or fails, skip validation
        # This happens in tests with mock registries
        logger.debug(
            "Registry does not support MCP validation",
            extra={"phase": "node_resolution"},
        )

    return False, []


def _create_mcp_error_suggestion(
    node_type: str,
    mcp_nodes: list[str],
) -> str:
    """Create helpful error suggestion for missing MCP node.

    Args:
        node_type: The MCP node type that wasn't found
        mcp_nodes: List of available MCP nodes

    Returns:
        Suggestion string for the error
    """
    if not mcp_nodes:
        # No MCP tools registered at all
        return (
            "No MCP tools are registered. You need to sync them first.\n\n"
            "Steps to enable MCP tools:\n"
            "  1. Check configured servers: pflow mcp list\n"
            "  2. Sync tools: pflow mcp sync --all\n"
            "  3. Verify registration: pflow registry list | grep mcp\n"
            "  4. Run your workflow again"
        )

    # MCP tools exist but not this one - suggest alternatives
    similar = find_similar_items(node_type, mcp_nodes, max_results=3, method="fuzzy", cutoff=0.4)

    if similar:
        suggestion_parts = [f"MCP tool '{node_type}' not found.\n\nDid you mean one of these?"]
        for s in similar:
            # Extract tool name for display
            tool_parts = s.split("-", 2)
            if len(tool_parts) >= 3:
                suggestion_parts.append(f"  \u2022 {s} ({tool_parts[1]} server: {tool_parts[2]})")
            else:
                suggestion_parts.append(f"  \u2022 {s}")
        return "\n".join(suggestion_parts)

    # No similar tools found - list available servers
    servers = set()
    for node in mcp_nodes:
        node_parts = node.split("-", 2)
        if len(node_parts) >= 2:
            servers.add(node_parts[1])

    return (
        f"MCP tool '{node_type}' not found.\n\n"
        f"Available MCP servers: {', '.join(sorted(servers))}\n"
        f"Total MCP tools: {len(mcp_nodes)}\n\n"
        f"Use 'pflow registry list' to see all available MCP tools."
    )


def _parse_mcp_node_type(node_type: str) -> tuple[str, str]:
    """Parse an MCP node type into server and tool names.

    Handles server names that contain dashes by checking against known MCP servers.
    Format: mcp-<server-name>-<tool-name>

    Args:
        node_type: Full node type like "mcp-local-test-echo"

    Returns:
        Tuple of (server_name, tool_name)

    Raises:
        CompilationError: If the server cannot be determined unambiguously
    """
    from .compiler import CompilationError

    parts = node_type.split("-")

    if len(parts) < 3:
        raise CompilationError(
            f"Invalid MCP node type format: {node_type}",
            phase="node_resolution",
            suggestion="MCP node types must be in format: mcp-<server>-<tool>",
        )

    try:
        from pflow.mcp.manager import MCPServerManager

        manager = MCPServerManager()
        servers = manager.list_servers()
    except Exception as e:
        # If we can't load servers, we can't parse reliably
        raise CompilationError(
            f"Failed to load MCP servers for parsing: {e}",
            phase="node_resolution",
            node_type=node_type,
            suggestion="Check MCP server configuration",
        ) from e

    # Try progressively longer server names to find the longest match
    # This ensures we get "test-with-dashes" instead of "test"
    best_match = None
    best_match_length = 0

    for i in range(2, len(parts) + 1):
        possible_server = "-".join(parts[1:i])
        # Keep track of the longest matching server name
        if possible_server in servers and i - 1 > best_match_length:
            best_match = (possible_server, "-".join(parts[i:]) if i < len(parts) else "")
            best_match_length = i - 1

    if best_match:
        server_name, tool_name = best_match
        if not tool_name:
            raise CompilationError(
                f"Invalid MCP node type: {node_type} - no tool name after server '{server_name}'",
                phase="node_resolution",
                suggestion=f"Format should be: mcp-{server_name}-<tool-name>",
            )
        return server_name, tool_name

    # No matching server found
    raise CompilationError(
        f"MCP server not found for node type: {node_type}",
        phase="node_resolution",
        node_type=node_type,
        suggestion=f"Could not find MCP server from: {parts[1]}. Available servers: {', '.join(sorted(servers))}",
    )
