"""Shared utilities for generating suggestions ("did you mean" logic).

This module provides unified suggestion logic used across CLI, MCP server, and runtime
for generating helpful "did you mean" messages when user input doesn't match available options.

Functions:
    find_similar_items: Find items similar to a query using substring or fuzzy matching
    format_did_you_mean: Format suggestions as user-friendly message
"""

from typing import Literal


def find_similar_items(
    query: str,
    items: list[str],
    *,
    max_results: int = 5,
    method: Literal["substring", "fuzzy"] = "substring",
    cutoff: float = 0.4,
    sort_by_length: bool = False,
) -> list[str]:
    """Find items similar to query.

    Supports two matching methods:
    - substring: Fast case-insensitive substring matching (default)
    - fuzzy: Typo-tolerant matching using difflib.get_close_matches

    Args:
        query: Search query to match against items
        items: List of available items to search
        max_results: Maximum number of suggestions to return (default: 5)
        method: Matching method to use:
            - "substring": Case-insensitive substring matching (faster)
            - "fuzzy": difflib fuzzy matching (typo-tolerant)
        cutoff: Similarity threshold for fuzzy matching (0.0-1.0, default: 0.4)
        sort_by_length: Sort matches by length (shorter first, default: False)

    Returns:
        List of matching items (up to max_results)

    Examples:
        >>> # Substring matching (default)
        >>> find_similar_items("file", ["read-file", "write-file", "llm"])
        ["read-file", "write-file"]

        >>> # Fuzzy matching (typo-tolerant)
        >>> find_similar_items("reed", ["read", "write"], method="fuzzy")
        ["read"]

        >>> # Sort by length
        >>> find_similar_items("file", ["very-long-file", "file", "medium-file"],
        ...                     sort_by_length=True)
        ["file", "medium-file", "very-long-file"]
    """
    if method == "fuzzy":
        import difflib

        return difflib.get_close_matches(query, items, n=max_results, cutoff=cutoff)

    # Substring matching (default)
    query_lower = query.lower()
    matches = []

    for item in items:
        if query_lower in item.lower():
            matches.append(item)
            if len(matches) >= max_results:
                break

    if sort_by_length:
        matches.sort(key=len)

    return matches


def format_did_you_mean(
    query: str,
    suggestions: list[str],
    *,
    item_type: str = "item",
    fallback_items: list[str] | None = None,
    max_fallback: int = 10,
) -> str:
    """Format suggestions as user-friendly message.

    Generates helpful "did you mean" messages when user input doesn't match.
    Supports two modes:
    1. Suggestions available: Shows "Did you mean one of these {type}s?"
    2. No suggestions: Shows available items (up to max_fallback)

    Args:
        query: Original query that failed to match
        suggestions: List of suggested items (can be empty)
        item_type: Type of item being suggested (e.g., "node", "workflow", "tool")
        fallback_items: Items to show if no suggestions (optional)
        max_fallback: Maximum fallback items to show (default: 10)

    Returns:
        Formatted suggestion message

    Examples:
        >>> # With suggestions
        >>> format_did_you_mean("fil", ["file", "filter"], item_type="node")
        'Did you mean one of these nodes?\\n  - file\\n  - filter'

        >>> # Without suggestions, with fallback
        >>> format_did_you_mean("xyz", [], item_type="node",
        ...                      fallback_items=["read", "write", "llm"])
        'No similar nodes found. Available nodes:\\n  - read\\n  - write\\n  - llm'

        >>> # Without suggestions, no fallback
        >>> format_did_you_mean("xyz", [], item_type="workflow")
        "No workflows found matching 'xyz'"
    """
    if suggestions:
        lines = [f"Did you mean one of these {item_type}s?"]
        for suggestion in suggestions:
            lines.append(f"  - {suggestion}")
        return "\n".join(lines)

    if fallback_items:
        items_to_show = fallback_items[:max_fallback]
        lines = [f"No similar {item_type}s found. Available {item_type}s:"]
        for item in items_to_show:
            lines.append(f"  - {item}")

        if len(fallback_items) > max_fallback:
            remaining = len(fallback_items) - max_fallback
            lines.append(f"  ... and {remaining} more")

        return "\n".join(lines)

    return f"No {item_type}s found matching '{query}'"
