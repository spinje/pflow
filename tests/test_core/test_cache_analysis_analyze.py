"""F2.1 — analyzer engine tests: confidence, note ordering, summary shape."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from pflow.core.cache_analysis.analyze import (
    CacheAnalysis,
    PerCallRow,
    _aggregate_confidence,
    _maybe_append_gemini_note,
    analyze,
)

# ---------------------------------------------------------------------------
# Confidence aggregation — STRICT semantics per DD#34 line 634 verbatim
# ---------------------------------------------------------------------------


def _row(source: str) -> PerCallRow:
    return PerCallRow(
        node_path="X",
        model="m",
        is_batch=False,
        batch_size_estimated=None,
        input_tokens_estimated=100,
        cacheable_tokens_estimated=50,
        cache_ratio_pct=50,
        data_source=source,
        declared_prompt_cache=None,
    )


def test_confidence_high_when_all_trace() -> None:
    """STRICT: all rows must be 'trace' for high. Mixed trace/memo → medium."""
    confidence, coverage = _aggregate_confidence([_row("trace"), _row("trace")])
    assert confidence == "high_from_trace"
    assert coverage == {"trace": 2, "memo": 0, "estimator": 0, "heuristic": 0, "total": 2}


def test_confidence_NOT_high_when_one_row_is_memo() -> None:
    """STRICT semantics — would be 'permissive' (any-trace) under the rejected
    alternative."""
    confidence, _ = _aggregate_confidence([_row("trace"), _row("memo")])
    assert confidence == "medium_from_memo"


def test_confidence_medium_when_all_in_trace_memo_set() -> None:
    confidence, _ = _aggregate_confidence([_row("memo"), _row("memo")])
    assert confidence == "medium_from_memo"


def test_confidence_low_when_any_estimator() -> None:
    """Any 'estimator' or 'heuristic' present → low_no_data."""
    confidence, _ = _aggregate_confidence([_row("trace"), _row("estimator")])
    assert confidence == "low_no_data"
    confidence, _ = _aggregate_confidence([_row("memo"), _row("heuristic")])
    assert confidence == "low_no_data"


def test_confidence_low_for_empty_rows() -> None:
    confidence, coverage = _aggregate_confidence([])
    assert confidence == "low_no_data"
    assert coverage["total"] == 0


# ---------------------------------------------------------------------------
# Top-level analyze — minimal smoke
# ---------------------------------------------------------------------------


def test_analyze_returns_cache_analysis_dataclass() -> None:
    workflow_ir = {
        "nodes": [
            {
                "id": "review",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "hello"},
            }
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    assert isinstance(result, CacheAnalysis)
    assert result.workflow_path == "/abs/x.pflow.md"
    assert result.estimate_confidence in {"high_from_trace", "medium_from_memo", "low_no_data"}
    assert len(result.per_call) == 1


def test_analyze_skips_non_llm_nodes_in_per_call() -> None:
    workflow_ir = {
        "nodes": [
            {"id": "shell-step", "type": "shell", "params": {"command": "echo"}},
            {
                "id": "llm-step",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "hi"},
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    assert {row.node_path for row in result.per_call} == {"llm-step"}


def test_analyze_summary_counts_warnings_and_info() -> None:
    """Summary tracks blocking_errors / warnings_count / info_count separately."""
    workflow_ir = {
        "nodes": [
            {
                "id": "step",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "x" * 100},
                "prompt_cache": ["concept"],
            }
        ],
        "cache": {"items": [{"name": "concept", "var": "concept", "prose_before": "P\n\n"}]},
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    # cache.below-min-tokens fires (small prompt, anthropic min=1024).
    sum_ = result.summary
    assert sum_.warnings_count + sum_.info_count >= 1


# ---------------------------------------------------------------------------
# Trace auto-load — note ordering (Round 5 fix)
# ---------------------------------------------------------------------------


def _write_trace(
    debug_dir: Path,
    *,
    workflow_path: str,
    format_version: str,
    suffix: str = "x",
) -> Path:
    """Helper to write a synthetic trace file with the given format_version."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    name = f"workflow-trace-{suffix}-{time.time_ns()}.json"
    path = debug_dir / name
    path.write_text(
        json.dumps({"format_version": format_version, "workflow_path": workflow_path, "events": []}),
        encoding="utf-8",
    )
    return path


def test_autoload_appends_2_0_0_skip_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 2.0.0 trace matching workflow_path is skipped + an info note appended."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    _write_trace(debug_dir, workflow_path="/abs/x.pflow.md", format_version="2.0.0")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path is None
    assert any("2.0.0" in note and "skipped" in note for note in result.notes)


def test_autoload_appends_unparseable_skip_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "workflow-trace-broken.json").write_text("{invalid json", encoding="utf-8")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert any("unparseable" in note for note in result.notes)


def test_autoload_note_ordering_2_0_0_first_unparseable_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When BOTH fire, lock the order: 2.0.0-skip note first, unparseable second."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    _write_trace(debug_dir, workflow_path="/abs/x.pflow.md", format_version="2.0.0")
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "workflow-trace-broken-1.json").write_text("{invalid", encoding="utf-8")
    (debug_dir / "workflow-trace-broken-2.json").write_text("not json", encoding="utf-8")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    indices = {note: i for i, note in enumerate(result.notes)}
    skipped_idx = next(i for n, i in indices.items() if "2.0.0" in n)
    unparseable_idx = next(i for n, i in indices.items() if "unparseable" in n)
    assert skipped_idx < unparseable_idx, "2.0.0-skip must come before unparseable"


def test_autoload_finds_2_1_0_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    path = _write_trace(debug_dir, workflow_path="/abs/x.pflow.md", format_version="2.1.0")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path == str(path)


def test_explicit_from_trace_2_0_0_emits_graceful_note(tmp_path: Path) -> None:
    path = tmp_path / "trace.json"
    path.write_text(
        json.dumps({"format_version": "2.0.0", "workflow_path": "/abs/x.pflow.md", "events": []}),
        encoding="utf-8",
    )
    workflow_ir = {"nodes": []}
    result = analyze(
        workflow_ir,
        workflow_path="/abs/x.pflow.md",
        auto_load_trace=False,
        trace_path=path,
    )
    assert result.trace_path == str(path)
    # Tighter match — 2.0.0 trace AND graceful "discrepancy analysis omitted" wording.
    # Substring-only would match a hypothetical "2.0.0.1" version note too.
    assert any("2.0.0" in note and "discrepancy analysis omitted" in note for note in result.notes)


def test_explicit_from_trace_missing_path_raises() -> None:
    workflow_ir = {"nodes": []}
    with pytest.raises(FileNotFoundError):
        analyze(
            workflow_ir,
            workflow_path="/abs/x.pflow.md",
            auto_load_trace=False,
            trace_path=Path("/does/not/exist.json"),
        )


def test_explicit_from_trace_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "trace.json"
    path.write_text("{not json", encoding="utf-8")
    workflow_ir = {"nodes": []}
    with pytest.raises(ValueError):
        analyze(
            workflow_ir,
            workflow_path="/abs/x.pflow.md",
            auto_load_trace=False,
            trace_path=path,
        )


# ---------------------------------------------------------------------------
# Gemini telemetry note (Spike 1 outcome) — last in note ordering
# ---------------------------------------------------------------------------


def test_gemini_note_appended_when_gemini_in_per_call() -> None:
    notes: list[str] = []
    rows = [
        PerCallRow(
            node_path="x",
            model="gemini/gemini-2.5-pro",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=80,
            cache_ratio_pct=80,
            data_source="trace",
            declared_prompt_cache=None,
        )
    ]
    _maybe_append_gemini_note(rows, notes)
    assert any("Gemini telemetry" in n for n in notes)


def test_gemini_note_NOT_appended_for_anthropic_only_rows() -> None:
    notes: list[str] = []
    rows = [
        PerCallRow(
            node_path="x",
            model="anthropic/claude-sonnet-4-5",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=100,
            cacheable_tokens_estimated=0,
            cache_ratio_pct=0,
            data_source="estimator",
            declared_prompt_cache=None,
        )
    ]
    _maybe_append_gemini_note(rows, notes)
    assert notes == []
