"""Cache analysis package — Tier 2 + Tier 3 verification per Task 159 DD#36.

Surfaces:

- ``analyze(workflow, parameters)`` — full analysis (CLI ``pflow analyze-cache`` +
  MCP ``analyze_cache`` tool).
- ``summarize(workflow, parameters)`` — one-line dry-run nudge.
- ``CacheAnalysis`` — structured result.
"""

from __future__ import annotations

from .analyze import CacheAnalysis, analyze
from .render_json import render_json
from .render_text import render_text
from .summarize import summarize, summarize_from_analysis

__all__ = [
    "CacheAnalysis",
    "analyze",
    "render_json",
    "render_text",
    "summarize",
    "summarize_from_analysis",
]
