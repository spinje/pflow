"""Cache analysis package — Tier 2 + Tier 3 verification per Task 159 DD#36.

Surfaces:

- ``analyze(workflow, parameters)`` — full analysis (CLI ``pflow analyze-cache`` +
  MCP ``analyze_cache`` tool).
- ``summarize(workflow, parameters)`` — one-line dry-run nudge.
- ``CacheAnalysis`` — structured result.

JSON evolution policy: ``format_version`` follows semver-ish. Minor bumps
(``2.0`` → ``2.1``) are additive (new fields, new warning IDs); consumers using
``format_version.startswith("2.")`` keep working. Major bumps (``2.x`` →
``3.x``) are breaking. Mirrors the trace ``2.x`` consumer policy at
``trace_report.py`` (note: distinct namespace — analyze-cache JSON and trace
JSON share major-version vocabulary but are independent schemas).
"""

from __future__ import annotations

from .analyze import CacheAnalysis, analyze
from .render_json import JSON_FORMAT_VERSION, JSON_FORMAT_VERSION_MAJOR, render_json
from .render_text import render_text
from .summarize import summarize, summarize_from_analysis

__all__ = [
    "JSON_FORMAT_VERSION",
    "JSON_FORMAT_VERSION_MAJOR",
    "CacheAnalysis",
    "analyze",
    "render_json",
    "render_text",
    "summarize",
    "summarize_from_analysis",
]
