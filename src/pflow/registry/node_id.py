"""Helpers for resolving user-provided registry node identifiers."""

from __future__ import annotations


def normalize_node_id(user_input: str, available_nodes: set[str]) -> str | None:
    """Normalize a user-provided node ID to match the registry format.

    Matching tiers (first match wins):
    1. Exact match — ``user_input`` is already a valid node ID
    2. Hyphen → underscore — ``my-node`` matches ``my_node``
    3. Reverse (underscore → hyphen) — for MCP tools with multi-hyphen server names
    4. Suffix match — ``SEND_MESSAGE`` matches ``mcp-slack-SEND_MESSAGE``

    Returns the resolved node ID, or ``None`` if no match (not found) or if
    multiple nodes share the same suffix (ambiguous — caller should list candidates).
    """
    if user_input in available_nodes:
        return user_input

    normalized_all = user_input.replace("-", "_")
    if normalized_all in available_nodes:
        return normalized_all

    if "mcp-" in user_input or user_input.count("-") >= 2:
        for node_id in available_nodes:
            if user_input == node_id.replace("_", "-"):
                return node_id

    matches = [
        node_id for node_id in available_nodes if node_id.endswith(user_input) or node_id.endswith(normalized_all)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None

    return None
