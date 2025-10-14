"""Shared formatter for registry search display.

This module provides formatting for node search results across CLI and MCP interfaces.
Returns markdown-formatted text matching CLI table output.

Usage:
    >>> from pflow.execution.formatters.registry_search_formatter import format_search_results
    >>> matches = [{"node_id": "read-file", "description": "Read file", "match_type": "exact"}]
    >>> print(format_search_results("file", matches))
    Found 1 nodes matching 'file':
    ...
"""

from typing import Any


def format_search_results(pattern: str, matches: list[dict[str, Any]]) -> str:
    """Format search results as markdown table (CLI parity).

    Args:
        pattern: Search pattern used
        matches: List of match dicts with node_id, description, match_type, metadata

    Returns:
        Formatted markdown string with table

    Example:
        >>> matches = [
        ...     {"node_id": "read-file", "description": "Read files", "match_type": "node_id", "metadata": {}},
        ...     {"node_id": "write-file", "description": "Write files", "match_type": "node_id", "metadata": {}}
        ... ]
        >>> result = format_search_results("file", matches)
        >>> "Found 2 nodes" in result
        True
        >>> "read-file" in result
        True
    """
    if not matches:
        return f"No nodes found matching '{pattern}'"

    lines = [
        f"Found {len(matches)} nodes matching '{pattern}':\n",
        "Name                 Type    Match   Description",
        "─" * 60,
    ]

    # Show top 10 results
    for match in matches[:10]:
        node_id = match["node_id"]
        desc = match.get("description", "")[:35]
        if len(match.get("description", "")) > 35:
            desc = desc[:32] + "..."

        # Determine match type display
        match_type = match.get("match_type", "")
        if match_type == "exact":
            match_display = "exact"
        elif match_type == "prefix":
            match_display = "prefix"
        elif match_type == "node_id":
            match_display = "name"
        elif match_type == "description":
            match_display = "desc"
        else:
            match_display = "match"

        # Determine type using proper logic (same as CLI)
        metadata = match.get("metadata", {})
        type_display = _get_node_type(node_id, metadata)

        # Format line with padding
        line = f"{node_id:<20} {type_display:<7} {match_display:<7} {desc}"
        lines.append(line)

    if len(matches) > 10:
        remaining = len(matches) - 10
        lines.append(f"\n... and {remaining} more {'result' if remaining == 1 else 'results'}")

    return "\n".join(lines)


def _get_node_type(name: str, metadata: dict[str, Any]) -> str:
    """Determine node type from name and metadata.

    This uses the same logic as CLI's registry.py to ensure consistency.

    Args:
        name: Node name
        metadata: Node metadata dict

    Returns:
        Node type: "core", "user", or "mcp"
    """
    # Check if explicitly marked
    if "type" in metadata:
        return str(metadata["type"])

    # Check for MCP pattern
    if name.startswith("mcp-"):
        return "mcp"

    # Check for virtual path (MCP)
    file_path = metadata.get("file_path", "")
    if "virtual://mcp" in file_path:
        return "mcp"

    # Check for core node path
    if "/src/pflow/nodes/" in file_path:
        return "core"

    # Default to user
    return "user"
