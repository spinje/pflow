"""Shared probe error construction for CLI and MCP.

Returns Diagnostic objects, not text. Callers render via format_diagnostic().
"""

from __future__ import annotations

from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity, exception_to_diagnostics


def build_node_not_found_diagnostic(node_type: str, available_nodes: list[str]) -> Diagnostic:
    """Build a Diagnostic for a node not found in the registry.

    Falls back to showing available nodes when no fuzzy match exists.
    """
    from pflow.core.suggestion_utils import find_similar_items

    similar = find_similar_items(node_type, available_nodes, max_results=5, method="substring")
    if not similar:
        similar = sorted(available_nodes)[:10]

    suggestions = _node_discovery_suggestions(node_type)
    return Diagnostic(
        severity=Severity.ERROR,
        message=f"Node '{node_type}' not found in registry.",
        title="Node Not Found",
        suggestions=suggestions,
        source="registry",
        context={"category": "not_found", "similar_names": similar},
    )


def enrich_for_probe(
    exc: Exception,
    node_type: str,
) -> list[Diagnostic]:
    """Convert an exception to Diagnostics enriched with probe context.

    Adds node_type as location and context-aware suggestions based on
    exception type. The call site has the node_type context that the
    generic exception_to_diagnostics() pipeline lacks.
    """
    from dataclasses import replace

    diagnostics = exception_to_diagnostics(exc)
    enriched = []
    for d in diagnostics:
        node_id = d.node_id or node_type
        suggestions = _probe_suggestions(d, node_type, exc)
        enriched.append(replace(d, node_id=node_id, suggestions=suggestions))
    return enriched


def _node_discovery_suggestions(node_type: str) -> list[str]:
    """Build suggestions appropriate for the node type (MCP vs core)."""
    if node_type.startswith("mcp-"):
        return [
            "Use 'pflow mcp find' to search MCP tools by intent",
            "Use 'pflow mcp list' to see all available MCP tools",
        ]
    return [
        "Core node types: shell, http, llm, code, read-file, write-file",
        "Use 'pflow mcp list' to see available MCP tools",
    ]


def _describe_suggestion(node_type: str) -> str:
    """Return the appropriate describe command for the node type."""
    if node_type.startswith("mcp-"):
        return f"Use 'pflow mcp describe {node_type}' to see required parameters"
    return f"Use 'pflow probe {node_type} --help' for usage information"


def _probe_suggestions(d: Any, node_type: str, exc: Exception) -> list[str]:
    """Build context-aware suggestions for probe errors."""
    suggestions = list(d.suggestions or [])
    if isinstance(exc, (FileNotFoundError, PermissionError)):
        return suggestions  # already have good suggestions from _builtin_exception_diagnostic
    if isinstance(exc, ValueError) and "required" in str(exc).lower():
        suggestions.append(_describe_suggestion(node_type))
    elif "timeout" in str(exc).lower():
        suggestions.append("Try increasing timeout if supported")
        suggestions.append(_describe_suggestion(node_type))
    else:
        suggestions.append(_describe_suggestion(node_type))
    return suggestions
