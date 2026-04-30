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
    _build_summary,
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
# Trace auto-load — hash-prefix glob (O(matches), not O(directory))
# ---------------------------------------------------------------------------


def _write_trace(
    debug_dir: Path,
    *,
    workflow_path: str,
    format_version: str,
    workflow_name: str = "x",
) -> Path:
    """Write a synthetic trace under the production filename schema.

    Uses ``format_trace_filename`` so the test fixture matches the same hash
    prefix the autoload reader globs by — without that, autoload skips the
    file even when contents match.
    """
    from pflow.runtime.workflow_trace import format_trace_filename

    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = f"20260430-{time.time_ns() % 1_000_000:06d}"
    name = format_trace_filename(workflow_path, workflow_name, timestamp)
    path = debug_dir / name
    path.write_text(
        json.dumps({"format_version": format_version, "workflow_path": workflow_path, "events": []}),
        encoding="utf-8",
    )
    return path


def test_autoload_finds_2_1_0_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    path = _write_trace(debug_dir, workflow_path="/abs/x.pflow.md", format_version="2.1.0")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path == str(path)


def test_autoload_skips_2_0_0_trace_silently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2.0.0 traces are not auto-loaded (DD#34). No advisory note —
    pre-2.1.0 traces age out naturally, and the 2.0.0 explicit-load path
    (via --from-trace) emits its own graceful note."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    _write_trace(debug_dir, workflow_path="/abs/x.pflow.md", format_version="2.0.0")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path is None


def test_autoload_skips_unparseable_files_silently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unparseable trace files in ~/.pflow/debug/ are skipped at debug log
    level. Disk corruption / aborted writes are rare; the producer side
    (WorkflowTraceCollector.save_to_file) is the right place to surface
    write failures, not every analyzer read."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"
    # Write a syntactically broken file under the new schema's hash prefix
    # so the autoload glob actually surfaces it (then skips).
    from pflow.runtime.workflow_trace import format_trace_filename

    debug_dir.mkdir(parents=True, exist_ok=True)
    name = format_trace_filename("/abs/x.pflow.md", "broken", "20260430-000001")
    (debug_dir / name).write_text("{invalid json", encoding="utf-8")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path is None


def test_autoload_skips_traces_for_other_workflows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hash-prefix glob narrows to candidates for *this* workflow_path.
    Traces for unrelated workflows aren't even read — their hash prefixes
    differ. Locks the O(matching), not O(directory), invariant."""
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    debug_dir = fake_home / ".pflow" / "debug"

    _write_trace(debug_dir, workflow_path="/abs/other.pflow.md", format_version="2.1.0")

    workflow_ir = {"nodes": []}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=True)
    assert result.trace_path is None


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


# ---------------------------------------------------------------------------
# cache.prewarm-no-prefix — boundary regex must match runtime gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt, should_emit",
    [
        # Dot-syntax batch ref at position 0 → emit (today's behavior).
        ("${item.text}\n\nrubric here", True),
        # Bracket-syntax at position 0 → MUST also emit (CR-1430 C1 — was silently
        # missed by the dot-only matcher; runtime gate at nodes/llm/llm.py:350
        # uses ``r"(\.|\[)"``).
        ("${item[0].text}\n\nrubric here", True),
        # Bracket without dot suffix at position 0 → emit (also batch-scoped).
        ("${item[0]}\n\nrubric", True),
        # Static prefix before batch ref → no emit (the auto-batch-prefix can fire).
        ("Some stable rubric content.\n\n${item.text}", False),
        ("Some stable rubric content.\n\n${item[0].text}", False),
        # No batch ref at all → no emit.
        ("Plain prompt with no ${item} reference at all.", False),
    ],
)
def test_prewarm_no_prefix_matches_runtime_gate_for_dot_AND_bracket_syntax(prompt: str, should_emit: bool) -> None:
    """The analyzer's prewarm-no-prefix detection must match the runtime
    auto-batch-prefix gate at ``nodes/llm/llm.py``: both ``${alias.X}`` and
    ``${alias[N]...}`` are batch-scoped references. Earlier dot-only matcher
    silently missed every bracket-syntax workflow (CR-1430 C1)."""
    workflow_ir = {
        "inputs": {"items": {"type": "list"}},
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prewarm": True,
                "batch": {"items": "${items}", "as": "item"},
                "params": {"prompt": prompt, "model": "anthropic/claude-sonnet-4-5"},
            }
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, auto_load_trace=False)
    emitted = [d for d in analysis.warnings if d.id == "cache.prewarm-no-prefix"]
    if should_emit:
        assert emitted, (
            f"Expected cache.prewarm-no-prefix for prompt={prompt!r} "
            f"(batch ref at position 0); got ids={[d.id for d in analysis.warnings]}"
        )
    else:
        assert not emitted, (
            f"Did NOT expect cache.prewarm-no-prefix for prompt={prompt!r}; got {len(emitted)} emission(s)"
        )


# ---------------------------------------------------------------------------
# CR-1430 C2: savings percentage must use a consistent rowset
# ---------------------------------------------------------------------------


def _summary_row(
    *,
    node_path: str,
    input_tokens: int = 10_000,
    cacheable_tokens: int,
    declared_prompt_cache: list[str] | None,
    output_tokens: int | None,
) -> PerCallRow:
    """Construct a PerCallRow at the granularity ``_build_summary`` consumes.

    Mixed ``output_tokens=int`` / ``output_tokens=None`` per row is the
    fixture shape that exercises the C2 bug: priced rows in different
    output-availability cohorts.
    """
    ratio = round(100 * cacheable_tokens / input_tokens) if input_tokens else 0
    return PerCallRow(
        node_path=node_path,
        model="claude-sonnet-4-5",
        is_batch=False,
        batch_size_estimated=None,
        input_tokens_estimated=input_tokens,
        cacheable_tokens_estimated=cacheable_tokens,
        cache_ratio_pct=ratio,
        data_source="estimator",
        declared_prompt_cache=declared_prompt_cache,
        output_tokens_estimated=output_tokens,
        output_data_source="memo" if output_tokens is not None else "unavailable",
    )


def test_savings_pct_uses_cohort_consistent_denominator_not_input_only_superset() -> None:
    """CR-1430 C2 regression — drives the buggy mixed-state cohort directly.

    Pre-fix bug: ``cost.savings_first_run_usd`` was input-only over ALL priced
    rows (superset); ``cost.current_usd`` was full-cost over rows-with-output
    (subset). When without-output rows contributed materially to savings, the
    division produced ``savings > current`` → percentages > 100% rendered as
    nonsensical ``-117%``.

    Mutation-test thought: revert the fix to
    ``_safe_pct_or_none(cost.savings_first_run_usd, cost.current_usd)`` and
    this test fails — the buggy formula yields a value > 100 for this fixture.
    Post-fix ``(current - optimized) / current`` is bounded by ≤ 100% by
    construction (assuming optimized ≥ 0).

    Fixture: 4 priced rows. Row A has output tokens AND no cache subset (so
    it dominates ``current_usd`` with full input+output cost but contributes
    zero to savings). Rows B/C/D have NO output tokens AND large cache
    subsets — they contribute substantial input-only savings to
    ``savings_first_run_usd`` but ZERO to ``current_usd``. The fixture's
    structural assertion (``aggregate_savings > current``) confirms the
    bug scenario IS exercised before the percentage check fires.
    """
    # Row A: tiny input (100) + tiny output (50), no cache subset. This is
    # the only row contributing to ``current_usd`` — and it's small.
    # Rows B/C/D/E/F: large cache-using rows with NO output. They populate
    # ``savings_first_run_usd`` (input-only superset) but NOT ``current_usd``.
    # Result: savings >> current → pre-fix pct > 100% → bug.
    rows = [
        _summary_row(
            node_path="A",
            input_tokens=100,
            cacheable_tokens=0,
            declared_prompt_cache=None,
            output_tokens=50,
        ),
        *[
            _summary_row(
                node_path=name,
                input_tokens=10_000,
                cacheable_tokens=8_000,
                declared_prompt_cache=["topic"],
                output_tokens=None,
            )
            for name in ("B", "C", "D", "E", "F")
        ],
    ]
    summary = _build_summary(rows, warnings=[], ttl="5m")

    # Sanity: fixture must induce the bug scenario before assertions fire.
    assert summary.current_cost_per_run_usd is not None, "Row A must populate current_usd"
    assert summary.aggregate_savings_first_run_usd is not None, "Rows B/C/D must populate savings"
    assert summary.aggregate_savings_first_run_usd > summary.current_cost_per_run_usd, (
        f"Fixture must induce ``savings > current`` to exercise the C2 bug: "
        f"savings={summary.aggregate_savings_first_run_usd}, "
        f"current={summary.current_cost_per_run_usd}. Adjust token sizes."
    )

    # Post-fix: percentage is cohort-consistent (rows-with-output only).
    # Row A has no cache subset → its ``(current - optimized)`` is 0 → pct == 0.
    # Pre-fix would render ``savings_first_run_usd / current_usd`` which is > 1
    # → > 100% → bug.
    pct = summary.savings_pct_first_run
    assert pct is not None, "current_usd is non-None → pct must be computable"
    assert pct <= 100, (
        f"savings_pct_first_run = {pct} > 100 — denominator mismatch reopened. "
        f"Numerator and denominator must be over the same rowset (rows-with-output)."
    )
    assert pct >= -100, f"savings_pct_first_run = {pct} < -100 — implausible; check cohort math"


def test_aggregate_savings_field_remains_input_only_superset_for_greenfield() -> None:
    """CR-1430 C2 fix preserves the load-bearing greenfield contract: the
    ``aggregate_savings_first_run_usd`` field continues to be input-only and
    superset-of-priced-rows so greenfield workflows still surface a positive
    absolute savings opportunity even when ``current_usd`` is None.

    The fix is local to ``savings_pct_first_run`` — the absolute aggregate
    savings figure is unchanged.
    """
    workflow_ir = {
        "inputs": {"topic": {"type": "string", "required": False}},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "topic", "var": "topic", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": f"node_{i}",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["topic"],
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": f"${{topic}}\n\nAnalyst {i}: " + ("x" * 6000),
                },
            }
            for i in range(2)
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, parameters={"topic": "alpha"}, auto_load_trace=False)
    # Greenfield: no memo cache → no output tokens → current_usd is None.
    assert analysis.summary.current_cost_per_run_usd is None
    # But the aggregate savings figure IS populated (input-only, output cancels).
    assert analysis.summary.aggregate_savings_first_run_usd is not None
    assert analysis.summary.aggregate_savings_first_run_usd > 0
