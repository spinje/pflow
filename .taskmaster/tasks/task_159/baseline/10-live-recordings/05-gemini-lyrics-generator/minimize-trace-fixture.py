#!/usr/bin/env python3
"""Build the committed lyrics-generator trace fixture from a raw live trace.

The raw Gemini trace is production-shaped but too large to commit directly:
it repeats full prompts, systems, inputs, and aggregate result objects across
multiple trace views. This script removes duplicate/debug-heavy fields while
preserving the analyzer facts this baseline is meant to exercise:

- nested batch/sub-workflow event structure
- per-item workflow attribution
- LLM usage/cost/cache telemetry
- one prompt source per LLM event (``llm_prompt``)
- producer values needed for cross-workflow cache projections

The committed fixture is Task-172 JSONL — the only on-disk format ``load_trace_file``
reads since #531 — so this tool reads the raw trace and writes the minimized fixture via
the shared JSONL helpers (``load_trace_file`` / ``tests.shared.trace_jsonl.write_trace_jsonl``).
Run from the repository root with ``uv run python`` (so pflow is importable), for example:

    uv run python .taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/minimize-trace-fixture.py \
      ~/.pflow/debug/workflow-trace-<hash>-lyrics-generator-<timestamp>.json \
      .taskmaster/tasks/task_159/baseline/_shared/fixtures/live-gemini-lyrics-generator.trace.json
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# One-shot authoring tool: it imports repo-internal helpers (pflow + tests.shared). Run via
# `uv run python` so pflow resolves; bootstrap the repo root onto sys.path so `tests.shared`
# resolves too (a `python <path>` run puts the SCRIPT dir on sys.path[0], not the repo root).
_REPO_ROOT = Path(__file__).resolve()
while not (_REPO_ROOT / "pyproject.toml").exists():
    if _REPO_ROOT.parent == _REPO_ROOT:
        raise SystemExit("minimize-trace-fixture.py: could not locate repo root (pyproject.toml)")
    _REPO_ROOT = _REPO_ROOT.parent
sys.path.insert(0, str(_REPO_ROOT))

from pflow.core.trace_io import load_trace_file  # noqa: E402 — needs the sys.path bootstrap above
from tests.shared.trace_jsonl import write_trace_jsonl  # noqa: E402 — needs the sys.path bootstrap above

DROP_STRING_KEYS = {
    # Direct LLM/request echoes duplicated elsewhere.
    "llm_response",
    "content",
    "prompt",
    # Source-analysis and aggregate text echoes not needed by analyze-cache.
    "analysis",
    "brief",
    "analyses_text",
    "all_analyses",
    "all_concepts_text",
    "selection_text",
    "judge_response",
    "judge_reasoning",
    "raw_source",
    "analysis_emotional",
    "analysis_sensory",
    "analysis_themes",
    "analysis_narrative",
    "analysis_musicality",
    "analysis_voice_tone",
    # Song/review derived text echoes. Structured producer values remain.
    "emotional_reviews",
    "craft_reviews",
    "song_architecture_text",
    "chorus_options_text",
    "creative_direction_text",
    "easter_eggs_text",
    "chorus_selection_text",
    "emotional_rewrite_deliberation",
    "revision_deliberation",
    "review_text",
    "rewrite_output",
    "deliberation",
    "cd_summary",
    "evaluation",
    "all_concepts",
    "concept_selection",
    "suno_style_prompt",
    "finished_song",
    "draft_lyrics",
    "chorus_text",
    "all_scored_text",
    "all_formatted",
    "top_formatted",
    "chorus_guide",
}


def minimize_trace(value: Any, path: tuple[str, ...] = ()) -> None:
    """Minimize trace data in place."""
    if isinstance(value, dict):
        _minimize_mapping(value, path)
        for key, child in list(value.items()):
            minimize_trace(child, (*path, str(key)))
        return

    if isinstance(value, list):
        for child in value:
            minimize_trace(child, (*path, "[]"))


def _minimize_mapping(value: dict[str, Any], path: tuple[str, ...]) -> None:
    # Keep generic template-resolution metadata, but remove materialized
    # resolved input copies and request echoes. The analyzer still has
    # workflow attribution, nested events, llm_prompt, and producer outputs.
    if path and path[-1] == "template_resolutions":
        value.pop("prompt", None)
        value.pop("system", None)
        inputs = value.get("inputs")
        if isinstance(inputs, dict):
            inputs.pop("resolved", None)

    # Runtime node params repeat full child inputs for many batch items.
    # Producer outputs and child node_output values preserve the data used
    # for cache projections.
    if path and path[-1] == "node_params":
        value.pop("inputs", None)
        value.pop("system", None)

    if path and path[-1] == "node_output":
        value.pop("system", None)

    value.pop("llm_system", None)

    for key in list(DROP_STRING_KEYS):
        if isinstance(value.get(key), str):
            value.pop(key, None)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: minimize-trace-fixture.py <raw-trace.json> <output.json>", file=sys.stderr)
        return 2

    source = Path(argv[1])
    output = Path(argv[2])
    data = load_trace_file(source)
    minimize_trace(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_trace_jsonl(output, data)
    print(f"wrote {output} ({output.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
