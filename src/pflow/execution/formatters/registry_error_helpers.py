"""Shared registry-run error construction for CLI and MCP.

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
    return Diagnostic(
        severity=Severity.ERROR,
        message=f"Node '{node_type}' not found in registry.",
        title="Node Not Found",
        suggestions=[
            "Use 'pflow registry discover' to search for nodes",
            "Use 'pflow registry list' to see all available nodes",
        ],
        source="registry",
        context={"category": "not_found", "similar_names": similar},
    )


def enrich_for_registry_run(
    exc: Exception,
    node_type: str,
) -> list[Diagnostic]:
    """Convert an exception to Diagnostics enriched with registry-run context.

    Adds node_type as location and context-aware suggestions based on
    exception type. The call site has the node_type context that the
    generic exception_to_diagnostics() pipeline lacks.
    """
    from dataclasses import replace

    diagnostics = exception_to_diagnostics(exc)
    enriched = []
    for d in diagnostics:
        node_id = d.node_id or node_type
        suggestions = _registry_run_suggestions(d, node_type, exc)
        enriched.append(replace(d, node_id=node_id, suggestions=suggestions))
    return enriched


def _registry_run_suggestions(d: Any, node_type: str, exc: Exception) -> list[str]:
    """Build context-aware suggestions for registry run errors."""
    suggestions = list(d.suggestions or [])
    if isinstance(exc, (FileNotFoundError, PermissionError)):
        return suggestions  # already have good suggestions from _builtin_exception_diagnostic
    if isinstance(exc, ValueError) and "required" in str(exc).lower():
        suggestions.append(f"Use 'pflow registry describe {node_type}' to see required parameters")
    elif "timeout" in str(exc).lower():
        suggestions.append("Try increasing timeout if supported")
        suggestions.append(f"Use 'pflow registry describe {node_type}' to check parameters")
    else:
        suggestions.append(f"Use 'pflow registry describe {node_type}' to see required parameters")
    return suggestions
