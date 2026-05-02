"""F2.1 — analyzer engine tests: confidence, note ordering, summary shape."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from pflow.core.cache_analysis.analyze import (
    CacheAnalysis,
    PerCallRow,
    _aggregate_confidence,
    _build_summary,
    _maybe_append_gemini_note,
    analyze,
)
from pflow.core.diagnostic import Diagnostic, Severity

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


def test_per_call_cache_ratio_never_exceeds_100_pct() -> None:
    """Bug C regression — ``cacheable_tokens_estimated`` and
    ``input_tokens_estimated`` come from independent estimators (75%-of-char
    heuristic vs ``litellm.token_counter``). For repetitive text the
    char-heuristic can exceed token_counter; without clamping this rendered
    as ``ratio=103%`` in production, mathematically nonsense.

    Mutation test: drop the ``cacheable_tokens = min(cacheable_tokens, input_tokens)``
    line in ``_build_per_call_row``; this test fails (ratio > 100% surfaces).
    """
    # Repetitive text where ``len(text)//4 * 0.75`` exceeds litellm.token_counter's
    # estimate. The exact balance depends on the tokenizer; we assert the
    # invariant rather than try to hit the precise overshoot threshold.
    long_repetitive = "abcd " * 2000
    workflow_ir = {
        "cache": {"items": [{"name": "concept", "var": "concept", "prose_before": "P:\n"}]},
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "x",
                "type": "llm",
                "model": "anthropic/claude-sonnet-4-5",
                "prompt_cache": ["concept"],
                "params": {"prompt": long_repetitive + "${concept}"},
            }
        ],
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False, memo_cache=None)
    for row in result.per_call:
        assert row.cache_ratio_pct <= 100, f"row {row.node_path} has nonsense ratio {row.cache_ratio_pct}%"
        assert row.cacheable_tokens_estimated <= row.input_tokens_estimated, (
            f"cacheable={row.cacheable_tokens_estimated} > input={row.input_tokens_estimated} "
            "violates the 'cache cannot exceed total' invariant"
        )


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
    # Tighter assertion: lock the specific id so a different warning firing
    # for the wrong reason fails the test (not just total count).
    assert any(w.id == "cache.below-min-tokens" for w in result.warnings), (
        f"Expected cache.below-min-tokens; got: {[w.id for w in result.warnings]}"
    )
    sum_ = result.summary
    assert sum_.warnings_count + sum_.info_count >= 1


def test_analyze_surfaces_cache_order_mismatch() -> None:
    workflow_ir = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "gen",
                "type": "llm",
                "prompt_cache": ["b", "a"],
                "params": {"prompt": "go"},
            }
        ],
        "edges": [],
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    diag = next(d for d in result.warnings if d.id == "cache.order-mismatch")
    assert diag.severity == Severity.ERROR


def test_analyze_surfaces_cache_unused_chunk() -> None:
    workflow_ir = {
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "gen",
                "type": "llm",
                "prompt_cache": ["a"],
                "params": {"prompt": "go"},
            }
        ],
        "edges": [],
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    assert "cache.unused-chunk" in {d.id for d in result.warnings}


def test_analyze_surfaces_cache_invalid_on_non_llm() -> None:
    workflow_ir = {
        "inputs": {"a": {"type": "string"}},
        "cache": {"items": [{"name": "a", "var": "a", "prose_before": "A:\n"}]},
        "nodes": [
            {
                "id": "echo",
                "type": "shell",
                "prompt_cache": ["a"],
                "params": {"command": "echo hi"},
            }
        ],
        "edges": [],
    }
    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    diag = next(d for d in result.warnings if d.id == "cache.invalid-on-non-llm")
    assert diag.severity == Severity.ERROR


def test_analyze_filters_non_cache_data_flow_diagnostics() -> None:
    """Negative control for A.6: validate_data_flow's non-cache diagnostics
    (here: a forward template reference to an undeclared node) MUST be
    filtered out by ``_cache_validator_findings`` so analyze() doesn't surface
    workflow-health concerns under the cache-analyzer label.

    Mutation-test: removing the ``d.id and d.id.startswith("cache.")`` filter
    in ``_cache_validator_findings`` makes the non-cache diagnostic leak
    through and fails the final assertion.
    """
    from pflow.core.workflow.data_flow import validate_data_flow

    # Forward-reference shape: shell node 'a' references 'b' which appears
    # after it in document order. validate_data_flow(check_inputs=False)
    # still emits this ERROR (it's an order-of-execution problem, not an
    # input-dependent check), and the diagnostic has id=None — which is
    # exactly what the cache-namespaced filter is designed to drop.
    workflow_ir = {
        "nodes": [
            {"id": "a", "type": "shell", "params": {"command": "echo ${b.stdout}"}},
            {"id": "b", "type": "shell", "params": {"command": "echo hi"}},
        ],
        "edges": [],
    }
    # Sanity-check the fixture: the validator MUST emit at least one
    # non-cache diagnostic, otherwise the assertion below is vacuous.
    raw = validate_data_flow(workflow_ir, check_inputs=False)
    has_non_cache = any((d.id is None) or not d.id.startswith("cache.") for d in raw)
    assert has_non_cache, "Test fixture must produce at least one non-cache diagnostic to be a valid negative control."

    result = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)
    # The actual A.6 contract: analyze.warnings carries ONLY cache.* IDs.
    assert all(d.id and d.id.startswith("cache.") for d in result.warnings)


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


# ---------------------------------------------------------------------------
# _build_recommended_actions sort priority (Tier 1 #1)
#
# Mutation contract: drop the ``priority`` dimension from the sort key in
# ``_build_recommended_actions._key`` and the priority test fails — the
# alphabetical tie-break re-buries actionable findings under informational
# ones (the lyrics-generator regression we observed).
# ---------------------------------------------------------------------------


def _make_diag(diag_id: str, severity: Severity, savings_usd: float | None = None) -> Diagnostic:
    """Synthetic Diagnostic for sort-key tests."""
    context: dict[str, Any] = {}
    if savings_usd is not None:
        context["savings_usd"] = savings_usd
    return Diagnostic(
        severity=severity,
        message=f"test {diag_id}",
        title="Test",
        id=diag_id,
        node_id=None,
        source="cache_analyzer",
        context=context,
    )


def test_recommended_actions_prioritize_actionable_over_informational() -> None:
    """When two warnings share severity AND have no savings, detection-class
    priority decides the order. Tier 1 IDs (shared-context-undeclared,
    priority 10) sort ahead of Tier 5 IDs (unused-chunk, priority 30).

    Pre-fix: alphabetical tie-break could bury actionable findings under
    informational ones. Agent reading top of "Recommended actions" got noise
    instead of the real opportunity.

    (Pre-Stage-0 used cross-workflow-rename-detected to demonstrate the
    sort; that ID is now filtered OUT of Recommended actions entirely — see
    ``test_recommended_actions_filters_cross_workflow_alignment_ids`` for
    that contract.)
    """
    from pflow.core.cache_analysis.analyze import _build_recommended_actions

    actions = _build_recommended_actions([
        _make_diag("cache.unused-chunk", Severity.INFO),
        _make_diag("cache.shared-context-undeclared", Severity.INFO),
    ])
    # shared-context-undeclared MUST come first (priority 10 < 30).
    assert actions[0].warning_id == "cache.shared-context-undeclared"
    assert actions[1].warning_id == "cache.unused-chunk"


def test_recommended_actions_filters_cross_workflow_alignment_ids() -> None:
    """Cross-workflow alignment findings (rename, prose-mismatch) are
    EXCLUDED from Recommended actions — they render in the "Sub-workflow
    boundaries" section. This keeps each finding visible in exactly ONE
    section (Stage 0 + B.3).

    Mutation contract: remove the ``_CROSS_WORKFLOW_ALIGNMENT_IDS`` filter
    in ``view_helpers.build_recommended_actions``; this test fails because
    the rename diag enters the ranked list.
    """
    from pflow.core.cache_analysis.analyze import _build_recommended_actions

    actions = _build_recommended_actions([
        _make_diag("cache.cross-workflow-rename-detected", Severity.INFO),
        _make_diag("cache.cross-workflow-prose-mismatch", Severity.INFO),
        _make_diag("cache.shared-context-undeclared", Severity.INFO),
    ])
    # Only the non-alignment finding survives.
    ids = [a.warning_id for a in actions]
    assert ids == ["cache.shared-context-undeclared"], f"alignment IDs leaked into recommended actions: {ids}"


def test_recommended_actions_severity_overrides_priority() -> None:
    """ERROR severity always wins over priority — structural blockers come first."""
    from pflow.core.cache_analysis.analyze import _build_recommended_actions

    actions = _build_recommended_actions([
        _make_diag("cache.shared-context-undeclared", Severity.INFO),  # priority 10
        _make_diag("cache.order-mismatch", Severity.ERROR),  # priority 5, ERROR
    ])
    # ERROR severity ranks above INFO regardless of priority dimension.
    assert actions[0].warning_id == "cache.order-mismatch"
    assert actions[1].warning_id == "cache.shared-context-undeclared"


def test_recommended_actions_savings_orders_within_priority_tier() -> None:
    """Within a priority tier, dollar savings break ties ahead of alphabetical.

    Two same-priority IDs (priority 10) with different savings — higher
    savings ranks first.
    """
    from pflow.core.cache_analysis.analyze import _build_recommended_actions

    actions = _build_recommended_actions([
        _make_diag("cache.dynamic-before-static", Severity.INFO, savings_usd=0.50),
        _make_diag("cache.shared-context-undeclared", Severity.INFO, savings_usd=2.10),
    ])
    # Higher savings first, even though alphabetical would put dynamic-before-static first.
    assert actions[0].warning_id == "cache.shared-context-undeclared"
    assert actions[1].warning_id == "cache.dynamic-before-static"


def test_recommended_actions_unknown_id_falls_back_to_default_priority() -> None:
    """An ID not in RECOMMENDED_ACTION_PRIORITY (e.g. a future addition that
    hasn't been added to the dict) gets ``DEFAULT_RECOMMENDED_ACTION_PRIORITY``
    (100 — lowest). Defensive: graceful degradation rather than KeyError.
    """
    from pflow.core.cache_analysis.analyze import _build_recommended_actions

    actions = _build_recommended_actions([
        _make_diag("cache.future-unknown-id", Severity.INFO),  # no priority entry
        _make_diag("cache.shared-context-undeclared", Severity.INFO),  # priority 10
    ])
    # Known priority wins over default.
    assert actions[0].warning_id == "cache.shared-context-undeclared"
    assert actions[1].warning_id == "cache.future-unknown-id"


# ---------------------------------------------------------------------------
# CP1 (#8) — Effective model resolution
# ---------------------------------------------------------------------------


def test_effective_model_falls_back_to_workflow_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A node without per-node ``model:`` picks up ``get_default_workflow_model()``.

    Mutation-test: if the fallback in ``_build_per_call_row`` (``analyze.py:499``)
    is reverted to ``str(node.get("params", {}).get("model") or node.get("model") or "")``,
    this test fails with ``model == ""`` instead of the patched default. The
    lyrics-generator parent workflow's ``~2 LLM calls · 0 models in use`` bug
    would re-appear.
    """
    # ``pflow.core.cache_analysis.analyze`` resolves to the FUNCTION via
    # ``__init__.py``'s ``from .analyze import analyze`` re-export, shadowing the
    # submodule. Reach the actual module via ``sys.modules`` for monkeypatch.
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(
        analyze_module,
        "get_default_workflow_model",
        lambda: "anthropic/claude-sonnet-4-5",
    )
    workflow_ir = {
        "nodes": [
            {
                "id": "creative-direction",
                "type": "llm",
                "params": {"prompt": "hello"},  # no model
            }
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    assert len(result.per_call) == 1
    assert result.per_call[0].model == "anthropic/claude-sonnet-4-5"
    assert result.summary.models_in_use == ("anthropic/claude-sonnet-4-5",)


def test_effective_model_explicit_wins_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-node ``model:`` always wins; default is only the fallback."""
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "should-not-be-used")
    workflow_ir = {
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "params": {"model": "gemini/gemini-3.1-pro-preview", "prompt": "x"},
            }
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    assert result.per_call[0].model == "gemini/gemini-3.1-pro-preview"


def test_effective_model_empty_when_no_default_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_default_workflow_model()`` returns None → row.model is empty string.

    This matches the pre-fix behavior for the case where neither per-node
    model nor settings/auto-detect yields anything. The renderer then shows
    ``model=`` empty (CP4 will improve to ``(default)``); the summary's
    ``models_in_use`` is correctly empty (not undercounted).
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    workflow_ir = {
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "params": {"prompt": "x"},  # no model
            }
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    assert result.per_call[0].model == ""
    assert result.summary.models_in_use == ()


def test_summary_message_zero_llm_nodes() -> None:
    """Zero LLM nodes → message says exactly that, doesn't mention pricing.

    Mutation-test: if the renderer's branch logic in
    ``render_text._render_summary`` re-conflates the three sub-cases, this
    test fails because the message would mention LLM nodes.
    """
    from pflow.core.cache_analysis.render_text import _render_summary

    workflow_ir = {"nodes": [{"id": "shell", "type": "shell", "params": {"command": "echo"}}]}
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = _render_summary(result)
    assert "workflow has no LLM nodes" in rendered
    assert "model resolved" not in rendered
    assert "run the workflow once" not in rendered


def test_summary_message_no_model_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM nodes exist but no model resolves → message says so explicitly.

    This is the lyrics-generator parent workflow case: 2 LLM nodes, neither
    has per-node ``model:``, no default configured → before CP1 the message
    said "workflow has no LLM nodes" (factually wrong with 2 visible in the
    table below). Mutation-test: reverting either the analyzer fallback OR
    the renderer branch produces the wrong message.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    from pflow.core.cache_analysis.render_text import _render_summary

    workflow_ir = {
        "nodes": [
            {"id": "n1", "type": "llm", "params": {"prompt": "hi"}},
            {"id": "n2", "type": "llm", "params": {"prompt": "bye"}},
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = _render_summary(result)
    assert "no model resolved" in rendered
    assert "workflow has no LLM nodes" not in rendered


def test_summary_message_priced_no_run_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM nodes with priced models but no run history → 'run the workflow once'.

    This case fires when models resolve and pricing is available, but
    ``current_cost_per_run_usd`` is None (output tokens unavailable) AND
    aggregate savings is None (no shared context detected).
    """
    # ``pflow.core.cache_analysis.analyze`` resolves to the FUNCTION via
    # ``__init__.py``'s ``from .analyze import analyze`` re-export, shadowing the
    # submodule. Reach the actual module via ``sys.modules`` for monkeypatch.
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(
        analyze_module,
        "get_default_workflow_model",
        lambda: "anthropic/claude-sonnet-4-5",
    )
    from pflow.core.cache_analysis.render_text import _render_summary

    # Single LLM node — no shared context → no aggregate-savings → falls into
    # the third sub-branch.
    workflow_ir = {
        "nodes": [
            {"id": "n1", "type": "llm", "params": {"prompt": "lonely call"}},
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = _render_summary(result)
    # Either the priced-no-history branch fires, or (if savings detection
    # produces an aggregate figure even for one node) the greenfield run-once
    # hint fires. Both forms are correct; only the wrong "no LLM nodes" or
    # "no model resolved" branches should be excluded.
    assert "workflow has no LLM nodes" not in rendered
    assert "no model resolved" not in rendered


# ---------------------------------------------------------------------------
# Stage C.1 — heterogeneous batch sub-workflow model detection
# ---------------------------------------------------------------------------


def test_heterogeneous_model_detected_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """A node with ``model: ${item.model}`` is flagged heterogeneous, not leaked.

    Pitfall #19 defense: drives ``analyze(...)`` end-to-end. Synthetic
    ``PerCallRow(...)`` construction would bypass the upstream detection at
    ``analyze.py:_build_per_call_row``.

    Mutation contract: dropping the ``"${" in raw_model`` check causes the
    literal ``${item.model}`` to land in ``models_in_use``. This test fails
    with that string in the aggregate.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    workflow_ir = {
        "nodes": [
            {
                "id": "score-choruses",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "score this chorus"},
            },
            {
                "id": "creative-direction",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "set direction"},
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)

    assert len(result.per_call) == 2
    by_node = {r.node_path: r for r in result.per_call}
    # Heterogeneous row — model emptied, flag set.
    assert by_node["score-choruses"].model == ""
    assert by_node["score-choruses"].model_is_heterogeneous is True
    # Homogeneous row — flag stays False.
    assert by_node["creative-direction"].model_is_heterogeneous is False

    # ``models_in_use`` excludes heterogeneous; the literal template never
    # leaks into the aggregate.
    assert "${item.model}" not in result.summary.models_in_use
    assert "anthropic/claude-sonnet-4-5" in result.summary.models_in_use
    assert result.summary.heterogeneous_model_node_count == 1
    assert result.summary.heterogeneous_model_node_paths == ("score-choruses",)


def test_heterogeneous_model_excluded_from_pricing_aggregation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Heterogeneous rows don't fabricate cost figures.

    Mutation contract: enabling cost lookup on heterogeneous rows would
    produce a non-None ``current_cost_per_run_usd`` even though the model
    is unresolvable. This test asserts the cost figure stays unavailable.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    # All-heterogeneous workflow — every row is unpriceable.
    workflow_ir = {
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "p"},
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)

    # No priced rows → all cost figures are None (matches cost_estimation
    # contract — heterogeneous rows skipped before pricing lookup).
    assert result.summary.current_cost_per_run_usd is None
    assert result.summary.optimized_cost_per_run_usd is None
    # Heterogeneous models DO NOT enter unavailable_models (they have model="")
    # so the "all 1 models lack pricing" branch doesn't fire.
    assert result.summary.unavailable_models == ()


def test_heterogeneous_only_summary_renders_explicit_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """All-heterogeneous workflow renders the right cause, not the wrong one.

    Mutation contract: removing the ``heterogeneous_model_node_count ==
    total_llm_calls_estimated`` branch in ``_render_summary`` causes the
    "set settings.default_model" hint to fire. That hint is wrong here —
    model resolution isn't the problem; per-batch-item models can't be
    aggregated as one model. This test fails if that branch reverts.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    from pflow.core.cache_analysis.render_text import _render_summary

    workflow_ir = {
        "nodes": [
            {"id": "n1", "type": "llm", "params": {"model": "${item.model}", "prompt": "p1"}},
            {"id": "n2", "type": "llm", "params": {"model": "${item.model}", "prompt": "p2"}},
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = _render_summary(result)

    assert "all LLM nodes use models that vary per batch item" in rendered
    # The wrong-cause messages must NOT fire here.
    assert "set settings.default_model" not in rendered
    assert "workflow has no LLM nodes" not in rendered


def test_heterogeneous_row_survives_option_c_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-call section shows heterogeneous rows even on pure greenfield.

    Without this, heterogeneous nodes would be hidden by Option C (no memo,
    no declared subset → would normally fail ``_row_has_real_data``). The
    agent would only see ``+ N nodes with model varying`` in the header
    and have no place to grep for which node varies.

    Mutation contract: removing the ``model_is_heterogeneous`` clause from
    ``_row_has_real_data`` causes the section to be hidden entirely (all
    rows fail the predicate), this test fails with no per-call section in
    the rendered output.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    from pflow.core.cache_analysis.render_text import render_text

    workflow_ir = {
        "nodes": [
            {"id": "score-choruses", "type": "llm", "params": {"model": "${item.model}", "prompt": "p"}},
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = render_text(result)

    assert "## Per-call cache report" in rendered
    assert "score-choruses" in rendered
    # Renderer uses ``<varies>``, not the literal ``${item.model}``.
    assert "model=<varies>" in rendered
    assert "${item.model}" not in rendered


def test_heterogeneous_node_named_in_scale_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Header names which nodes have varying models, not just the count.

    Mutation contract: dropping the ``heterogeneous_node_paths`` kwarg
    propagation in the header caller (``_render_header``) causes the
    name to disappear; agent would have to scan per-call to find which
    node varies. This test asserts the name is in the rendered scale line.
    """
    import sys

    analyze_module = sys.modules["pflow.core.cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    from pflow.core.cache_analysis.render_text import render_text

    workflow_ir = {
        "nodes": [
            {
                "id": "score-choruses",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "p"},
            },
            {
                "id": "creative-direction",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "p"},
            },
        ]
    }
    result = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    rendered = render_text(result)

    # Scale line names the heterogeneous node + tag.
    assert "score-choruses" in rendered
    assert "model varies per batch item" in rendered
    # Literal template MUST NOT leak.
    assert "${item.model}" not in rendered


# ---------------------------------------------------------------------------
# Stage C.2 — _format_cost grammar / N=1 model name
# ---------------------------------------------------------------------------


def test_format_cost_names_single_unpriced_model() -> None:
    """When exactly one model lacks pricing, name it directly.

    Mutation contract: reverting the N==1 branch to the plural phrasing
    would render ``"all 1 models lack pricing data"`` — agent can't tell
    which model from the summary alone. Test asserts the model name is
    surfaced.
    """
    from pflow.core.cache_analysis.render_text import _format_cost

    rendered = _format_cost(value=None, partial=False, unavailable_models=("ollama/llama3.2:8b",))

    assert "ollama/llama3.2:8b lacks pricing data" in rendered
    assert "all 1 models" not in rendered  # Old buggy phrasing must NOT appear.


def test_format_cost_keeps_plural_phrasing_for_multiple_unpriced() -> None:
    """N>1 keeps the count phrasing — naming each would clutter the summary line.

    The footer ``Unpriced models: ...`` (rendered separately by
    ``_render_summary`` when ``partial_cost_usd``) lists them all, so this
    line stays terse.
    """
    from pflow.core.cache_analysis.render_text import _format_cost

    rendered = _format_cost(
        value=None,
        partial=False,
        unavailable_models=("ollama/llama3.2:8b", "custom/foo", "custom/bar"),
    )

    assert "all 3 models lack pricing data" in rendered


# ---------------------------------------------------------------------------
# Unified ``estimate_cacheable_tokens`` — end-to-end production-shape tests
# (Pitfall #19 defense: drive ``analyze()`` end-to-end with real
# ``MemoizationCache.put`` calls / real trace dicts; assert BOTH
# ``cacheable_tokens_estimated`` value AND ``cacheable_data_source`` tier.)
# ---------------------------------------------------------------------------


def test_brownfield_memo_populates_cacheable_via_memo_tier(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brownfield (`## Cache` declared) + memo data → cacheable from memo tier.

    Closes the silent-gap regression class: pre-fix ``_estimate_cacheable_tokens``
    was a static heuristic on the prompt template, ignoring memo data even
    when present. Post-fix Tier 2 fires.

    Mutation: revert to static heuristic → cacheable becomes ~187 (heuristic
    value) and source becomes ``"estimator"`` instead of ``"memo"``.
    """
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    # Lock token counter to a deterministic value (defends against tokenizer drift).
    monkeypatch.setattr("litellm.token_counter", lambda model, text: 1500)

    workflow_path = "/abs/brownfield.pflow.md"
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    cache.put(
        cache_key="seeded-context",
        node_id="context",
        workflow_path=workflow_path,
        action="default",
        output={"response": "long context body that the analyzer will tokenize"},
    )

    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context.response", "prose_before": "Context:\n"}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {"model": "claude-sonnet-4-5", "prompt": "${context.response}\n\nSummarize."},
                "prompt_cache": ["context.response"],
            }
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False)
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    assert row.cacheable_data_source == "memo", (
        f"expected memo tier for brownfield + memo data; got {row.cacheable_data_source!r}"
    )
    assert row.cacheable_tokens_estimated == 1500, (
        f"expected 1500 (deterministic memo value); got {row.cacheable_tokens_estimated}"
    )
    # Note: ``data_source`` (input tokens) and ``cacheable_data_source``
    # (cacheable tokens) are independent. The memo entry was seeded for
    # ``context`` (the chunk's root); ``estimate_tokens`` looks up the LLM
    # node's own ID (``summarize``) which has no memo entry → estimator
    # tier for input. Tier 2 for cacheable resolves the ``context.response``
    # ref via ``_latest_value_for_ref`` → memo. Two metrics, two labels.


def test_brownfield_trace_populates_cacheable_via_trace_tier_with_asymmetric_values(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brownfield + 2.1.0 trace with asymmetric cache_creation+cache_read.

    Asymmetric values (1000 + 599 = 1599) defend against
    ``creation + read`` → ``creation`` alone mutation.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_path = "/abs/withtrace.pflow.md"
    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {"model": "claude-sonnet-4-5", "prompt": "${context}\n\nDo work."},
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }

    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": workflow_path,
            "nodes": [
                {
                    "node_id": "summarize",
                    "llm_call": {
                        "input_tokens": 1599,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 1000,
                        "cache_read_input_tokens": 599,
                    },
                }
            ],
        })
    )

    analysis = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
    )
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    assert row.cacheable_data_source == "trace"
    assert row.cacheable_tokens_estimated == 1599


def test_no_cache_trace_with_memo_projects_via_candidate(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-cache workflow with shared ``${context}`` reference + memo data:
    the candidate-detection walker collects the shared ref and Tier 2 of
    ``estimate_cacheable_tokens`` projects from memo.

    Three assertions defend against (a) value miss, (b) tier mislabel,
    (c) candidate-walker breakage.
    """
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("litellm.token_counter", lambda model, text: 800)

    workflow_path = "/abs/no_cache_with_memo.pflow.md"
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    cache.put(
        cache_key="ctx-key",
        node_id="context",
        workflow_path=workflow_path,
        action="default",
        output={"response": "long context"},
    )

    workflow_ir = {
        "inputs": {},
        "nodes": [
            {
                "id": "context",
                "type": "code",
                "params": {"code": "result = {'response': 'something'}"},
            },
            {
                "id": "node_a",
                "type": "llm",
                "params": {"model": "claude-sonnet-4-5", "prompt": "${context.response}\n\nA"},
            },
            {
                "id": "node_b",
                "type": "llm",
                "params": {"model": "claude-sonnet-4-5", "prompt": "${context.response}\n\nB"},
            },
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False)
    llm_rows = [r for r in analysis.per_call if r.node_path in ("node_a", "node_b")]
    assert len(llm_rows) == 2
    for row in llm_rows:
        assert row.cacheable_tokens_estimated is not None and row.cacheable_tokens_estimated > 0, (
            f"row {row.node_path!r} should have projected cacheable tokens; got {row.cacheable_tokens_estimated}"
        )
        assert row.cacheable_data_source == "memo", (
            f"row {row.node_path!r} expected memo tier; got {row.cacheable_data_source!r}"
        )

    # Candidate-detection signal: shared-context-undeclared warning fires
    # AND shared chunks include context.response.
    shared = [d for d in analysis.warnings if d.id == "cache.shared-context-undeclared"]
    assert shared, "expected cache.shared-context-undeclared for shared ${context.response}"
    chunks_seen: list[str] = []
    for diag in shared:
        ctx = diag.context or {}
        chunks_seen.extend(ctx.get("shared_chunks", []) or [])
    assert "context.response" in chunks_seen, f"expected 'context.response' in shared chunks; got {chunks_seen}"


def test_heterogeneous_batch_with_declared_cache_uses_estimator_tier(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heterogeneous batch (``model: ${item.model}``) + declared
    ``prompt_cache`` → Tier 2 short-circuits on empty model; Tier 3 fires.

    Closes Case 8a end-to-end gap: unit test #8 covers the gate; this
    verifies the full path through ``analyze()``.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_ir = {
        "inputs": {"items": {"type": "array"}},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "score",
                "type": "llm",
                "batch": {"items": "${items}", "as": "item"},
                "params": {
                    "model": "${item.model}",
                    "prompt": "${context}\n\nScore the thing." + ("x" * 1000),
                },
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path="/abs/het.pflow.md", auto_load_trace=False)
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    assert row.model_is_heterogeneous is True
    assert row.cacheable_tokens_estimated is not None and row.cacheable_tokens_estimated > 0
    assert row.cacheable_data_source == "estimator", (
        f"heterogeneous declared row should fall through to estimator; got {row.cacheable_data_source!r}"
    )


def test_below_min_tokens_suppressed_when_trace_evidence_shows_cache_fired(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cache.below-min-tokens`` MUST NOT fire when ``cacheable_data_source``
    is ``"trace"``: trace evidence (cache_creation + cache_read > 0) shows
    the cache demonstrably worked at this size, so the warning would
    contradict reality.

    Mutation contract: remove the ``row.cacheable_data_source != "trace"``
    clause in ``_per_node_warnings`` and the warning fires anyway —
    breaking the trace-evidence-respects-itself contract. This test
    catches that mutation.

    Fixture: trace event with cache_creation=600, cache_read=200 (sum=800)
    AND model has min_cache_tokens=1024 (anthropic). Without the gate,
    the warning would fire because 800 < 1024. With the gate, it
    correctly suppresses.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_path = "/abs/below_min_with_trace.pflow.md"
    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "${context}\n\nDo work."},
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }

    # Trace shows cache fired but below the model's claimed min — exactly
    # the case where the analyzer's static threshold check would falsely
    # contradict trace evidence.
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": workflow_path,
            "nodes": [
                {
                    "node_id": "summarize",
                    "llm_call": {
                        "input_tokens": 800,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 600,
                        "cache_read_input_tokens": 200,
                    },
                }
            ],
        })
    )

    analysis = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
    )
    row = analysis.per_call[0]
    # Sanity: this is the trace-evidence path.
    assert row.cacheable_data_source == "trace"
    assert row.cacheable_tokens_estimated == 800
    # The contract: warning MUST NOT fire when trace shows cache worked.
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-tokens"]
    assert not below_min, (
        f"cache.below-min-tokens fired despite trace showing cache fired (cacheable=800, "
        f"src=trace). Gate ``cacheable_data_source != 'trace'`` regression. "
        f"warnings: {[w.id for w in analysis.warnings]}"
    )


def test_below_min_tokens_still_fires_when_estimator_says_below_min(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Companion to the suppression test: when source is NOT trace,
    the warning still fires correctly. Locks the inverse contract —
    suppression is keyed on ``"trace"`` specifically, not on cacheable
    > 0 alone.

    Mutation: change the gate to ``cacheable_data_source != "memo"`` (or
    any other tier name) → this test fails because the warning would
    suppress for estimator/memo too.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context", "var": "context", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "tiny prompt"},
                "prompt_cache": ["context"],
            }
        ],
        "edges": [],
    }
    # No trace, no memo — Tier 3 estimator fires; tiny prompt → small
    # cacheable < anthropic's 1024 min → warning SHOULD fire.
    analysis = analyze(workflow_ir, workflow_path="/abs/x.pflow.md", auto_load_trace=False)
    row = analysis.per_call[0]
    assert row.cacheable_data_source == "estimator"
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-tokens"]
    assert below_min, (
        f"cache.below-min-tokens did NOT fire for estimator-tier row below min_tokens. "
        f"Gate suppression mis-keyed. warnings: {[w.id for w in analysis.warnings]}"
    )


def test_declared_with_zero_creation_zero_read_falls_through_to_memo_e2e(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared subset + 2.1.0 trace recording cache_creation=0, cache_read=0
    (cache declared but didn't fire — sub-threshold etc.). Tier 1 MUST fall
    through; Tier 2 fires via memo; ``cache.below-min-tokens`` MUST fire
    because the gate's ``cacheable_data_source != "trace"`` clause is now
    True.

    This is the matrix Case 9 — the case that exists specifically to
    preserve ``cache.below-min-tokens`` fidelity when cache fails to engage.
    Without Tier 1 fall-through (e.g., short-circuit returning
    ``(0, "trace")`` per the disputed review-silent-failures C1 finding),
    cacheable_data_source would be ``"trace"``, the gate would suppress the
    warning, and agents would not learn that their declared chunks are
    sub-threshold.

    Mutation contracts:
      A. Replace Tier 1 fall-through with ``return (0, "trace")`` —
         cacheable_data_source becomes ``"trace"``, the gate at
         ``analyze.py:778`` suppresses, ``cache.below-min-tokens`` fails to
         fire. This test catches it.
      B. Drop the ``> 0`` precondition (use ``>= 0``) — cacheable becomes
         0 with source ``"trace"`` for the 0+0 case, same outcome as A.
      C. Drop the gate clause ``cacheable_data_source != "trace"`` —
         spurious; this test wouldn't catch it (companion test 1485
         catches that direction).
    """
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    # Lock memo tokenization to a deterministic value BELOW Sonnet 4.5's
    # 1024-token threshold so cache.below-min-tokens fires for genuine
    # sub-threshold cache content.
    monkeypatch.setattr("litellm.token_counter", lambda model, text: 500)

    workflow_path = "/abs/zero_zero_falls_through.pflow.md"
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    cache.put(
        cache_key="context-key",
        node_id="context",
        workflow_path=workflow_path,
        action="default",
        output={"response": "context body that tokenizes to 500 (mocked)"},
    )

    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [{"name": "context.response", "var": "context.response", "prose_before": ""}],
        },
        "nodes": [
            {
                "id": "summarize",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "${context.response}\n\nDo work."},
                "prompt_cache": ["context.response"],
            }
        ],
        "edges": [],
    }

    # Trace records cache declared but didn't fire — Tier 1 MUST fall through.
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps({
            "format_version": "2.1.0",
            "workflow_path": workflow_path,
            "nodes": [
                {
                    "node_id": "summarize",
                    "llm_call": {
                        "input_tokens": 510,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                }
            ],
        })
    )

    analysis = analyze(
        workflow_ir,
        workflow_path=workflow_path,
        trace_path=trace_path,
        auto_load_trace=False,
    )
    row = analysis.per_call[0]
    # Tier 1 falls through — source MUST NOT be ``"trace"``.
    assert row.cacheable_data_source == "memo", (
        f"Tier 1 should fall through when creation+read==0; got "
        f"cacheable_data_source={row.cacheable_data_source!r} (expected 'memo' from Tier 2)"
    )
    # Memo tokenization returned 500 (mocked); clamps to input_tokens (510).
    assert row.cacheable_tokens_estimated == 500, (
        f"expected memo-tier value of 500; got {row.cacheable_tokens_estimated}"
    )
    # The whole point of the fall-through: warning fires correctly.
    below_min = [w for w in analysis.warnings if w.id == "cache.below-min-tokens"]
    assert below_min, (
        f"cache.below-min-tokens did NOT fire for declared-but-cache-didn't-fire "
        f"sub-threshold case. Tier 1 fall-through regression. "
        f"warnings: {[w.id for w in analysis.warnings]}"
    )


def test_declared_partial_memo_falls_through_to_estimator_end_to_end(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared subset of 2 chunks; memo populated for one only. End-to-end
    fall-through to Tier 3 estimator (preserves ``cache.below-min-tokens``
    fidelity for declared-but-incomplete-memo case).
    """
    from pflow.runtime.cache import MemoizationCache

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    workflow_path = "/abs/partial_memo.pflow.md"
    cache_db_path = tmp_path / ".pflow" / "cache" / "cache.db"
    cache = MemoizationCache(db_path=cache_db_path)
    # Only seed chunk_a's source; chunk_b is missing — partial memo.
    cache.put(
        cache_key="a-key",
        node_id="chunk_a",
        workflow_path=workflow_path,
        action="default",
        output={"response": "value-a"},
    )

    workflow_ir = {
        "inputs": {},
        "cache": {
            "ttl": "5m",
            "items": [
                {"name": "chunk_a.response", "var": "chunk_a.response", "prose_before": "A:\n"},
                {"name": "chunk_b.response", "var": "chunk_b.response", "prose_before": "B:\n"},
            ],
        },
        "nodes": [
            {
                "id": "consumer",
                "type": "llm",
                "params": {
                    "model": "claude-sonnet-4-5",
                    "prompt": "${chunk_a.response} ${chunk_b.response}" + ("x" * 1000),
                },
                "prompt_cache": ["chunk_a.response", "chunk_b.response"],
            }
        ],
        "edges": [],
    }

    analysis = analyze(workflow_ir, workflow_path=workflow_path, auto_load_trace=False)
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    assert row.cacheable_data_source == "estimator", (
        f"declared partial-memo should fall through to estimator; got {row.cacheable_data_source!r}"
    )
    assert row.cacheable_tokens_estimated is not None and row.cacheable_tokens_estimated > 0


# ---------------------------------------------------------------------------
# Track A / B / C end-to-end through ``analyze()`` (Pitfall #19 defense —
# drives the public API, not internal helpers).
# ---------------------------------------------------------------------------


def test_analyze_end_to_end_resolves_prompt_template_for_tokenization() -> None:
    """Test 3 — Resolved prompt for tokenization.

    Mutation contract: revert ``_resolve_prompt_for_tokenization`` to pass
    the raw prompt to ``estimate_tokens`` → input_tokens reflects the
    template literal (~50 tokens for the prompt prose + ``${context}`` as
    5 chars) instead of the resolved 5000-char value.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"context": {"type": "string"}},
        "nodes": [
            {
                "id": "answer",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Reference document follows.\n\n${context}\n\nAnswer briefly.",
                },
            }
        ],
        "edges": [],
    }
    # 2000 unique-ish words generate a real (uncompressed) token count.
    # Repeating chars compress through any tokenizer's BPE / WordPiece —
    # use distinct tokens so the post-resolution count is observable.
    big_context = " ".join(f"word{i}" for i in range(2000))
    analysis = analyze(workflow_ir, parameters={"context": big_context}, auto_load_trace=False)
    assert len(analysis.per_call) == 1
    row = analysis.per_call[0]
    # Pre-fix: tokenization on raw template ~30 tokens.
    # Post-fix: resolved prompt has ~2000+ distinct tokens.
    assert row.input_tokens_estimated > 1000


def test_analyze_end_to_end_current_cost_honors_recorded_trace_cost() -> None:
    """Test 4 — Brownfield end-to-end (Track A through analyze()).

    Drives the public ``analyze()`` API with synthetic trace data carrying
    a known ``cost_usd``. Verifies that ``summary.current_cost_per_run_usd``
    reflects the recorded cost, NOT the recompute fallback.

    Mutation contract: revert ``cost_usd_for_node`` to always return None
    -> analyzer falls back to ``tokens x full_rate`` recompute -> assertion
    on the smaller recorded cost fails.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "answer-a",
                "type": "llm",
                "params": {"model": "gemini/gemini-2.5-flash", "prompt": "What is 2+2?"},
            }
        ],
        "edges": [],
    }
    # Fake a 2.1 trace with a recorded cost much lower than tokens x full_rate.
    trace = {
        "format_version": "2.1.0",
        "workflow_path": "ir-hash:fake",
        "nodes": [
            {
                "node_id": "answer-a",
                "node_type": "LLMNode",
                "llm_call": {
                    "model": "gemini/gemini-2.5-flash",
                    "input_tokens": 4709,
                    "output_tokens": 76,
                    "cost_usd": 0.00210488,  # The number recorded by the actual trace.
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            }
        ],
    }
    # Bypass auto-load by passing trace_data directly via internal API.
    # ``analyze`` doesn't have a trace_data kwarg, so simulate by building
    # a temp file. Simpler: the analyzer accepts trace_path, so we'd need
    # a real file. Instead, drive via an explicit test-only path: write
    # the trace JSON to tmp.
    import json
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(trace, f)
        trace_file = f.name

    try:
        analysis = analyze(
            workflow_ir,
            trace_path=Path(trace_file),
            auto_load_trace=False,
        )
    finally:
        Path(trace_file).unlink(missing_ok=True)

    assert analysis.summary.current_cost_per_run_usd is not None
    # Within ±5% of recorded cost (no recompute drift).
    assert abs(analysis.summary.current_cost_per_run_usd - 0.00210488) / 0.00210488 < 0.05
    # Cost data source on the row reflects trace tier.
    assert analysis.per_call[0].cost_data_source == "trace"
    assert analysis.per_call[0].cost_usd is not None
