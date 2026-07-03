"""Compatibility shim for Mermaid workflow visualization."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pflow.core.workflow.graph import build_graph, render_mermaid
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult


def generate_mermaid(
    ir: dict[str, Any],
    *,
    resolve_child: Callable[[dict[str, Any], Path | None], SubWorkflowResult | None] | None = None,
    base_path: Path | None = None,
    source_file: Path | None = None,
    max_depth: int = 1,
    direction: str = "LR",
    descriptions: bool = False,
) -> str:
    """Generate a Mermaid flowchart from workflow IR.

    The IR walk now lives in ``workflow.graph.build_graph``; this legacy
    package path remains as the stable public entry point for existing callers.
    """
    graph = build_graph(
        ir,
        resolve_child=resolve_child,
        base_path=base_path,
        source_file=source_file,
        max_depth=max_depth,
    )
    return render_mermaid(graph, direction=direction, descriptions=descriptions)


__all__ = ["generate_mermaid"]
