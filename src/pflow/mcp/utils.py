"""Utility functions for MCP operations."""

from typing import Optional


def _find_known_server_match(parts: list[str], known_servers: list[str]) -> Optional[tuple[str, str]]:
    """Find the best matching server from known servers.

    Args:
        parts: List of name parts after removing "mcp-" prefix
        known_servers: List of known server names

    Returns:
        Tuple of (server_name, tool_name) if found, None otherwise
    """
    best_match = None
    best_match_length = 0

    # Try progressively longer server names to find the longest match
    for i in range(1, len(parts) + 1):
        possible_server = "-".join(parts[:i])
        if possible_server in known_servers and i > best_match_length:
            tool_name = "-".join(parts[i:]) if i < len(parts) else ""
            best_match = (possible_server, tool_name)
            best_match_length = i

    return best_match


def _looks_like_tool_part(part: str) -> bool:
    """Check if a part looks like a tool name component.

    Args:
        part: A single part of the node name

    Returns:
        True if the part appears to be part of a tool name
    """
    return part.isupper() or "_" in part or any(c.isupper() for c in part)


def _guess_server_tool_split(parts: list[str]) -> tuple[str, str]:
    """Guess the server/tool split based on naming patterns.

    Most tool names are UPPERCASE_WITH_UNDERSCORES
    Server names are typically lowercase-with-hyphens

    Args:
        parts: List of name parts after removing "mcp-" prefix

    Returns:
        Tuple of (server_name, tool_name)
    """
    # Find the first part that looks like a tool name
    for i, part in enumerate(parts):
        if _looks_like_tool_part(part) and i > 0:
            server = "-".join(parts[:i])
            tool = "-".join(parts[i:])
            return server, tool

    # Last resort: assume single-word server name
    if len(parts) > 1:
        return parts[0], "-".join(parts[1:])

    return "unknown", "-".join(parts)


def parse_mcp_node_name(node_name: str, known_servers: Optional[list[str]] = None) -> tuple[str, str]:
    """Parse an MCP node name into server and tool components.

    Handles server names that contain hyphens by checking against known servers.
    Format: mcp-<server-name>-<tool-name>

    Args:
        node_name: Full node name like "mcp-slack-http-remote-SEND_MESSAGE"
        known_servers: Optional list of known server names for validation

    Returns:
        Tuple of (server_name, tool_name)
        Returns ("unknown", node_name) if parsing fails
    """
    if not node_name.startswith("mcp-"):
        return "unknown", node_name

    # Remove "mcp-" prefix
    remainder = node_name[4:]
    parts = remainder.split("-")

    if not parts:
        return "unknown", node_name

    # If we have known servers, try progressive matching
    if known_servers:
        match = _find_known_server_match(parts, known_servers)
        if match:
            return match

    # Fallback: Try to intelligently guess based on common patterns
    return _guess_server_tool_split(parts)
