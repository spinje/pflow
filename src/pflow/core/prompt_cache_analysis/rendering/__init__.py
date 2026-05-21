"""Output projections for prompt-cache analysis results."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .json import render_json
    from .summarize import summarize, summarize_from_analysis
    from .text import render_text

__all__ = [
    "render_json",
    "render_text",
    "summarize",
    "summarize_from_analysis",
]


def __getattr__(name: str) -> Any:
    if name == "render_json":
        from .json import render_json

        return render_json
    if name == "render_text":
        from .text import render_text

        return render_text
    if name == "summarize":
        from .summarize import summarize

        return summarize
    if name == "summarize_from_analysis":
        from .summarize import summarize_from_analysis

        return summarize_from_analysis
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
