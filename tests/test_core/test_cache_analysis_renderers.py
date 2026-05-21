"""F2.3 — text and JSON renderer tests.

Locks the agent-facing format contracts:
- Empty-array contract for derived-view arrays.
- Tri-state cost rendering (priced / partial / unavailable — never silent ``$0.00``).
- Default-hide-clean per-call rule + ``--all-rows`` override.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.prompt_cache_analysis import (
    render_json,
    render_text,
)
from pflow.core.prompt_cache_analysis.analyze import _format_workflow_run_command
from pflow.core.prompt_cache_analysis.cost_estimation import CostTier
from pflow.core.prompt_cache_analysis.types import (
    AnalysisSummary,
    CacheAnalysis,
    CostDelta,
    CrossWorkflowFindings,
    CrossWorkflowInputContribution,
    PerCallRow,
    ProjectionExclusion,
    SubWorkflowRollup,
    SubWorkflowRollupEntry,
    TraceUnexecutedLLMRow,
    invocation_count_for,
)


def _make_analysis(
    *,
    rows: list[PerCallRow] | None = None,
    warnings: list[Diagnostic] | None = None,
    notes: list[str] | None = None,
    actually_paid: float | None = None,
    actually_paid_tier: CostTier | None = None,
    no_cache: float | None = None,
    first_run_with_cache: float | None = None,
    rerun: float | None = None,
    partial: bool = False,
    unavailable: tuple[str, ...] = (),
    projection_exclusions: tuple[ProjectionExclusion, ...] = (),
    actual_delta_unavailable_reason: str | None = None,
    workflow_path: str = "/abs/x.pflow.md",
    ir_default_model: str | None = None,
    trace_path: str | None = None,
    trace_final_status: str | None | type(Ellipsis) = Ellipsis,
    trace_workflow_relationship: str | None = None,
    trace_model_drift_count: int = 0,
    trace_recorded_at: str | None | type(Ellipsis) = Ellipsis,
    trace_provider_llm_call_count: int = 0,
    trace_local_memo_llm_hit_count: int = 0,
    trace_local_in_process_llm_hit_count: int = 0,
    trace_local_cache_input_tokens: int = 0,
    trace_provider_cache_creation_input_tokens: int = 0,
    trace_provider_cache_read_input_tokens: int = 0,
    stale_memo_skipped_count: int = 0,
    stale_memo_uncheckable_count: int = 0,
) -> CacheAnalysis:
    """Construct a renderable analysis with atomic cost primitives.

    Each cost knob populates exactly one atom on ``AnalysisSummary``. Tests
    set whichever atoms they exercise:

    - ``actually_paid`` populates ``actually_paid_usd`` + a ``TRACE`` tier
      (else ``UNAVAILABLE``). When set, the renderer takes the trace-path
      layout (``Actually paid``/``Cost without caching``/``Cost on rerun``).
    - ``no_cache`` populates ``no_cache_hypothetical_usd``. The "Cost
      without caching" line in BOTH trace and greenfield layouts reads from
      this atom. Greenfield-no-declared-cache shows just this on a single
      "Cost per run" line (collapsed when first_run_with_cache equals it).
    - ``first_run_with_cache`` populates
      ``first_run_with_cache_hypothetical_usd``. Greenfield-with-cache
      layout shows it as "Cost on first run (cache)".
    - ``rerun`` populates ``rerun_within_ttl_hypothetical_usd`` — the
      "Cost on rerun (within TTL)" line.
    """
    rows = rows or []
    warnings = warnings or []
    # Mirror analyze._build_summary's split: rows whose workflow_path matches
    # the analysis path are root rows; everything else is sub-workflow.
    # Rows with workflow_path=None count as root (matches the analyzer's
    # ``or root_workflow_path`` pattern for inline-IR cases).
    root_count = sum(1 for r in rows if r.workflow_path is None or r.workflow_path == workflow_path)
    sub_count = len(rows) - root_count
    dynamic_batch_count = sum(1 for r in rows if r.is_batch and r.batch_size_estimated is None)
    total_invocations = (
        None
        if dynamic_batch_count
        else sum(r.batch_size_estimated if r.is_batch and r.batch_size_estimated is not None else 1 for r in rows)
    )
    first_run_delta = _test_delta(
        no_cache, first_run_with_cache, "no_cache_hypothetical_usd", "first_run_with_cache_hypothetical_usd"
    )
    rerun_delta = _test_delta(no_cache, rerun, "no_cache_hypothetical_usd", "rerun_within_ttl_hypothetical_usd")
    actual_delta = _test_delta(no_cache, actually_paid, "no_cache_hypothetical_usd", "actually_paid_usd")
    if actual_delta_unavailable_reason is not None:
        actual_delta = CostDelta(
            None,
            None,
            "unavailable",
            "no_cache_hypothetical_usd",
            "actually_paid_usd",
            actual_delta_unavailable_reason,
        )
    return CacheAnalysis(
        workflow_path=workflow_path,
        analyzed_at="2026-04-29T12:00:00Z",
        estimate_confidence="low_no_data",
        estimate_confidence_coverage={
            "trace": 0,
            "memo": 0,
            "estimator": len(rows),
            "heuristic": 0,
            "total": len(rows),
        },
        trace_path=trace_path,
        summary=AnalysisSummary(
            actually_paid_usd=actually_paid,
            actually_paid_tier=(
                actually_paid_tier
                if actually_paid_tier is not None
                else (CostTier.TRACE if actually_paid is not None else CostTier.UNAVAILABLE)
            ),
            no_cache_hypothetical_usd=no_cache,
            first_run_with_cache_hypothetical_usd=first_run_with_cache,
            rerun_within_ttl_hypothetical_usd=rerun,
            first_run_delta=first_run_delta,
            rerun_delta=rerun_delta,
            actual_vs_no_cache_delta=actual_delta,
            trace_coverage="complete" if actually_paid is not None else "none",
            evidence_scope="complete_trace" if actually_paid is not None else "static_analysis",
            trace_llm_nodes_static=len(rows),
            trace_llm_nodes_executed=len(rows) if actually_paid is not None else 0,
            trace_unexecuted_llm_rows=(),
            blocking_errors=sum(1 for d in warnings if d.severity == Severity.ERROR),
            actionable_opportunities=sum(1 for d in warnings if d.severity != Severity.ERROR),
            warnings_count=sum(1 for d in warnings if d.severity == Severity.WARNING),
            info_count=sum(1 for d in warnings if d.severity == Severity.INFO),
            total_llm_nodes_estimated=len(rows),
            total_llm_invocations_estimated=total_invocations,
            dynamic_batch_node_count=dynamic_batch_count,
            # Mirror production summary totals: row token fields are per-call,
            # so workflow totals multiply by the row invocation count.
            total_input_tokens_estimated=sum(r.input_tokens_estimated * invocation_count_for(r) for r in rows),
            total_cacheable_tokens_estimated=sum(
                (r.cacheable_tokens_estimated or 0) * invocation_count_for(r) for r in rows
            ),
            total_cache_active_tokens_estimated=sum(
                (r.cache_active.tokens_estimated or 0) * invocation_count_for(r) for r in rows
            ),
            total_cache_ready_tokens_estimated=sum(
                (r.cache_ready.tokens_estimated or 0) * invocation_count_for(r) for r in rows
            ),
            total_cache_opportunity_tokens_estimated=sum(
                (r.cache_opportunity.tokens_estimated or 0) * invocation_count_for(r) for r in rows
            ),
            total_cache_ready_confidence="exact" if any(r.cache_ready.tokens_estimated for r in rows) else "unknown",
            total_cache_opportunity_confidence=(
                "exact" if any(r.cache_opportunity.tokens_estimated for r in rows) else "unknown"
            ),
            unknown_cache_ready_row_count=sum(
                1
                for r in rows
                if r.cache_ready.data_source not in {"not_applicable", "unavailable"}
                and r.cache_ready.tokens_estimated is None
            ),
            unknown_cache_opportunity_row_count=sum(
                1
                for r in rows
                if r.cache_opportunity.data_source not in {"not_applicable", "unavailable"}
                and r.cache_opportunity.tokens_estimated is None
            ),
            lower_bound_cache_ready_row_count=sum(1 for r in rows if r.cache_ready.confidence == "lower_bound"),
            lower_bound_cache_opportunity_row_count=sum(
                1 for r in rows if r.cache_opportunity.confidence == "lower_bound"
            ),
            models_in_use=tuple(sorted({r.model for r in rows if r.model})),
            ir_default_model=ir_default_model,
            partial_cost_usd=partial,
            unavailable_models=unavailable,
            projection_exclusions=projection_exclusions,
            root_llm_node_count=root_count,
            sub_workflow_llm_node_count=sub_count,
            # Mirrors production: the field is populated whenever the
            # workflow has a non-inline path, regardless of cost-branch.
            # Builder doesn't model declared inputs, so the command shape
            # is the no-inputs variant.
            suggested_run_command=_format_workflow_run_command(workflow_path, None),
            # Mirrors production: when a trace contributed evidence
            # (``actually_paid is not None``), default the trace status to
            # "success" + an arbitrary recorded timestamp unless the test
            # opted in to a specific value (including explicit None).
            # Ellipsis sentinel distinguishes "caller didn't specify" from
            # "caller wants None" — needed by tests exercising the
            # legacy-trace-missing-timestamp path.
            trace_final_status=(
                cast(str | None, trace_final_status)
                if trace_final_status is not Ellipsis
                else ("success" if actually_paid is not None else None)
            ),
            trace_workflow_relationship=trace_workflow_relationship,
            trace_model_drift_count=trace_model_drift_count,
            trace_recorded_at=(
                cast(str | None, trace_recorded_at)
                if trace_recorded_at is not Ellipsis
                else ("2026-04-29T12:00:00" if actually_paid is not None else None)
            ),
            trace_provider_llm_call_count=trace_provider_llm_call_count,
            trace_local_memo_llm_hit_count=trace_local_memo_llm_hit_count,
            trace_local_in_process_llm_hit_count=trace_local_in_process_llm_hit_count,
            trace_local_cache_input_tokens=trace_local_cache_input_tokens,
            trace_provider_cache_creation_input_tokens=trace_provider_cache_creation_input_tokens,
            trace_provider_cache_read_input_tokens=trace_provider_cache_read_input_tokens,
            stale_memo_skipped_count=stale_memo_skipped_count,
            stale_memo_uncheckable_count=stale_memo_uncheckable_count,
        ),
        suggested_blocks=(),
        per_call=tuple(rows),
        cross_workflow=CrossWorkflowFindings(0),
        warnings=tuple(warnings),
        notes=tuple(notes or []),
    )


# Fields where _make_analysis intentionally relies on the AnalysisSummary
# dataclass default while production analyze() overwrites a computed value.
# Tests asserting on these fields must drive analyze(...) end-to-end.
#
# When AnalysisSummary grows a field, either populate it in _make_analysis or
# add it here after migrating any tests that assert on the field. See Pitfall
# #19 in tests/CLAUDE.md and TestMakeAnalysisShapeParity below.
_BUILDER_DOCUMENTED_DEFAULTS: frozenset[str] = frozenset({
    "observed_models_in_trace",
    "unavailable_models_by_workflow",
    "heterogeneous_model_node_count",
    "heterogeneous_model_node_paths",
    "sub_workflow_rollup",
    "total_cache_active_tokens_estimated",
    "unknown_cache_ready_row_count",
    "unknown_cache_opportunity_row_count",
    "lower_bound_cache_ready_row_count",
    "lower_bound_cache_opportunity_row_count",
})


class TestMakeAnalysisShapeParity:
    """Locks _make_analysis against drift from production analyze().

    When AnalysisSummary grows a field, this class fails noisily so a
    contributor must either populate it in _make_analysis or add it to
    _BUILDER_DOCUMENTED_DEFAULTS. Tests asserting on documented-default fields
    must drive analyze(...) end-to-end. See Pitfall #19 in tests/CLAUDE.md.
    """

    def test_builder_field_set_matches_dataclass_minus_documented_defaults(
        self,
    ) -> None:
        empty = _make_analysis()
        loaded = _make_analysis(
            rows=[
                PerCallRow(
                    node_path="root",
                    model="anthropic/claude-sonnet-4-5",
                    is_batch=True,
                    batch_size_estimated=2,
                    input_tokens_estimated=100,
                    cacheable_tokens_estimated=50,
                    cache_ratio_pct=50,
                    data_source="trace",
                    declared_prompt_cache=None,
                    workflow_path="/abs/x.pflow.md",
                ),
                PerCallRow(
                    node_path="child",
                    model="anthropic/claude-sonnet-4-5",
                    is_batch=False,
                    batch_size_estimated=None,
                    input_tokens_estimated=100,
                    cacheable_tokens_estimated=50,
                    cache_ratio_pct=50,
                    data_source="trace",
                    declared_prompt_cache=None,
                    workflow_path="/abs/child.pflow.md",
                ),
            ],
            warnings=[
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    id="cache.order-mismatch",
                    message="x",
                ),
                Diagnostic(
                    severity=Severity.WARNING,
                    source="cache_analyzer",
                    id="cache.below-min-predicted",
                    message="x",
                ),
                Diagnostic(
                    severity=Severity.INFO,
                    source="cache_analyzer",
                    id="cache.first-call-write-penalty",
                    message="x",
                ),
            ],
            actually_paid=0.05,
            no_cache=0.10,
            first_run_with_cache=0.07,
            rerun=0.03,
            partial=True,
            unavailable=("custom/model",),
            projection_exclusions=(_make_exclusion(),),
            actual_delta_unavailable_reason="trace_coverage_truncated",
            ir_default_model="anthropic/claude-sonnet-4-5",
            trace_provider_llm_call_count=2,
            trace_local_memo_llm_hit_count=1,
            trace_local_in_process_llm_hit_count=1,
            trace_local_cache_input_tokens=100,
            trace_provider_cache_creation_input_tokens=50,
            trace_provider_cache_read_input_tokens=25,
            trace_workflow_relationship="same_drifted",
            trace_model_drift_count=1,
            stale_memo_skipped_count=1,
            stale_memo_uncheckable_count=1,
        )

        def _at_default(summary: AnalysisSummary, field: dataclasses.Field[Any]) -> bool:
            value = getattr(summary, field.name)
            if field.default is not dataclasses.MISSING:
                return cast(bool, value == field.default)
            if field.default_factory is not dataclasses.MISSING:
                factory = cast(Callable[[], object], field.default_factory)
                return cast(bool, value == factory())
            return False

        unrepresented = {
            field.name
            for field in dataclasses.fields(AnalysisSummary)
            if _at_default(empty.summary, field) and _at_default(loaded.summary, field)
        }

        assert unrepresented == _BUILDER_DOCUMENTED_DEFAULTS, (
            f"Synthetic builder shape drift detected.\n"
            f"  Unrepresented by _make_analysis: {sorted(unrepresented)}\n"
            f"  Documented (allowlist):          {sorted(_BUILDER_DOCUMENTED_DEFAULTS)}\n"
            f"  Newly drifted (add a kwarg or document): "
            f"{sorted(unrepresented - _BUILDER_DOCUMENTED_DEFAULTS)}\n"
            f"  Stale entries (remove from allowlist):   "
            f"{sorted(_BUILDER_DOCUMENTED_DEFAULTS - unrepresented)}\n"
            f"\n"
            f"Fix: either extend _make_analysis (near the top of "
            f"test_cache_analysis_renderers.py) to populate the new field, "
            f"or add it to _BUILDER_DOCUMENTED_DEFAULTS and migrate any "
            f"test asserting on the field to drive analyze(...) end-to-end. "
            f"See Pitfall #19 in tests/CLAUDE.md."
        )

    def test_documented_defaults_get_overwritten_by_production(self, tmp_path: Path) -> None:
        from pflow.core.prompt_cache_analysis.analyze import analyze
        from pflow.execution.workflow_resolver import resolve_workflow
        from tests.shared.trace_fixture_builder import TraceFixtureBuilder

        builder = TraceFixtureBuilder()

        wf_path = str(tmp_path / "x.pflow.md")
        ir_inline = {
            "ir_version": "0.1.0",
            "inputs": {"topic": {"type": "string"}},
            "nodes": [
                {
                    "id": "generate",
                    "type": "llm",
                    "params": {"model": "${item.model}", "prompt": "About ${topic}"},
                    "batch": {"items": [{"model": "gemini/a"}, {"model": "gemini/b"}]},
                },
                {
                    "id": "local",
                    "type": "llm",
                    "params": {"model": "ollama/local", "prompt": "Local ${topic}"},
                },
            ],
        }
        trace_inline = {
            "format_version": "2.2.0",
            "workflow_path": wf_path,
            "nodes": [
                builder.batch_event(
                    "generate",
                    [
                        {
                            "index": 0,
                            "success": True,
                            "duration_ms": 1.0,
                            "node_output": {"response": "ok"},
                            "llm_call": {
                                "model": "gemini/a",
                                "input_tokens": 100,
                                "output_tokens": 10,
                                "cost_usd": 0.001,
                            },
                        },
                        {
                            "index": 1,
                            "success": True,
                            "duration_ms": 1.0,
                            "node_output": {"response": "ok"},
                            "llm_call": {
                                "model": "gemini/b",
                                "input_tokens": 100,
                                "output_tokens": 10,
                                "cost_usd": 0.001,
                            },
                        },
                    ],
                ),
                builder.llm_event(
                    "local",
                    model="ollama/local",
                    input_tokens=100,
                    output_tokens=10,
                    cost_usd=None,
                ),
            ],
        }
        result = analyze(
            ir_inline,
            parameters={"topic": "x"},
            trace_path=_write_trace(tmp_path / "inline-trace.json", trace_inline),
            workflow_path=wf_path,
            auto_load_trace=False,
            memo_cache=None,
        )
        assert result.summary.evidence_scope != "static_analysis", "evidence_scope production overwrite missing"
        assert result.summary.observed_models_in_trace, "observed_models_in_trace production overwrite missing"
        assert result.summary.unavailable_models_by_workflow, (
            "unavailable_models_by_workflow production overwrite missing"
        )
        assert result.summary.heterogeneous_model_node_count > 0, (
            "heterogeneous_model_node_count production overwrite missing"
        )
        assert result.summary.heterogeneous_model_node_paths, (
            "heterogeneous_model_node_paths production overwrite missing"
        )

        fixture_dir = Path("tests/fixtures/cache_analysis")
        parent_path = fixture_dir / "parent-3deep.pflow.md"
        trace_path = fixture_dir / "parent-child-grandchild-trace.json"
        resolved = resolve_workflow(str(parent_path))
        result_subwf = analyze(
            resolved.ir,
            parameters={"topic": "hello"},
            workflow_path=resolved.file_path,
            base_path=parent_path.parent,
            trace_path=trace_path,
            memo_cache=None,
            auto_load_trace=False,
        )
        assert result_subwf.summary.sub_workflow_rollup is not None, "sub_workflow_rollup production overwrite missing"


def _make_exclusion() -> ProjectionExclusion:
    return ProjectionExclusion(
        workflow_path="/abs/x.pflow.md",
        node_path="generate",
        reason="heterogeneous_model",
        actual_cost_usd=0.03,
    )


def _write_trace(path: Path, trace_data: object) -> Path:
    path.write_text(json.dumps(trace_data), encoding="utf-8")
    return path


def _test_delta(
    baseline_value: float | None,
    compared_value: float | None,
    baseline: str,
    compared_to: str,
) -> CostDelta:
    if baseline_value is None or compared_value is None or baseline_value <= 0:
        return CostDelta(None, None, "unavailable", baseline, compared_to)
    raw = baseline_value - compared_value
    if abs(raw) < 0.0000001:
        return CostDelta(0.0, 0, "break_even", baseline, compared_to)
    return CostDelta(
        abs(raw),
        round(100 * abs(raw) / baseline_value),
        "savings" if raw > 0 else "cost_increase",
        baseline,
        compared_to,
    )


def _trace_path(
    tmp_path: Path,
    *,
    workflow_path: str,
    nodes: list[dict[str, Any]],
    name: str = "trace.json",
    final_status: str | None = None,
) -> Path:
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    return _write_trace(
        tmp_path / name,
        builder.trace(workflow_path=workflow_path, nodes=nodes, final_status=final_status),
    )


def _llm_event(
    node_id: str,
    *,
    model: str,
    input_tokens: int = 2000,
    output_tokens: int = 100,
    cost_usd: float = 0.001,
) -> dict[str, Any]:
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    builder = TraceFixtureBuilder()
    return builder.llm_event(
        node_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------


def test_json_cross_workflow_empty_arrays_are_present() -> None:
    """Empty-array contract — agents treat absence as a positive signal."""
    result = render_json(_make_analysis())
    cw = result["cross_workflow"]
    assert cw["rename_detections"] == []
    assert cw["prose_mismatches"] == []
    assert cw["value_flow_opportunities"] == []
    assert cw["boundaries_analyzed"] == 0


def test_json_action_view_empty_arrays_are_present() -> None:
    """Derived action views are always present, even when empty."""
    result = render_json(_make_analysis())
    assert result["blocking_errors"] == []
    assert result["recommended_actions"] == []


def test_json_format_version_present_and_first_key() -> None:
    """JSON consumers version-gate via ``format_version.startswith("4.")``.
    The field MUST be present (deliberately absent in earlier 4.0 builds —
    re-added per Task 159 PR #378 review). Position-as-first-key is best-
    effort (Python dicts preserve insertion order); the load-bearing contract
    is presence + value matching the package constant.

    Mutation contract: removing the ``"format_version": JSON_FORMAT_VERSION``
    line in ``render_json`` makes this test fail with the package constant
    diff so the regression class is observable.
    """
    from pflow.core.prompt_cache_analysis import JSON_FORMAT_VERSION

    result = render_json(_make_analysis())
    assert "format_version" in result
    assert result["format_version"] == JSON_FORMAT_VERSION
    # First-key invariant — agents reading the JSON top-down see the version
    # discriminator immediately.
    assert next(iter(result)) == "format_version"


def test_json_round_trips_through_dumps_loads() -> None:
    """Catches non-serializable values leaking into the response."""
    result = render_json(_make_analysis())
    round_tripped = json.loads(json.dumps(result))
    assert round_tripped == result


def test_json_summary_emits_suggested_run_command() -> None:
    """JSON consumers (MCP, structured tools) get the same paste-ready
    command the text renderer surfaces — typed string, not free-form text.

    Mutation contract: removing ``"suggested_run_command": ...`` from
    ``_summary_to_dict`` fails this test.
    """
    result = render_json(_make_analysis(workflow_path="/abs/x.pflow.md"))
    assert result["summary"]["suggested_run_command"] == "pflow run /abs/x.pflow.md"


def test_json_summary_includes_ir_default_model_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from pflow.core.prompt_cache_analysis.analyze import analyze

    analyze_module = sys.modules["pflow.core.prompt_cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-haiku-4-5")
    analysis = analyze(
        {"nodes": [{"id": "generate", "type": "llm", "params": {"prompt": "Hello"}}]},
        workflow_path="x",
        auto_load_trace=False,
    )

    assert render_json(analysis)["summary"]["ir_default_model"] == "anthropic/claude-haiku-4-5"


def test_json_summary_ir_default_model_null_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from pflow.core.prompt_cache_analysis.analyze import analyze

    analyze_module = sys.modules["pflow.core.prompt_cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: None)
    analysis = analyze(
        {"nodes": [{"id": "generate", "type": "llm", "params": {"prompt": "Hello"}}]},
        workflow_path="x",
        auto_load_trace=False,
    )

    assert render_json(analysis)["summary"]["ir_default_model"] is None


def test_json_summary_suggested_run_command_null_for_inline_workflow() -> None:
    """Inline IR has no runnable file path; JSON serializes ``null``.

    Mutation contract: dropping the ``ir-hash:`` guard or the ``None``
    return in ``_format_workflow_run_command`` fails this test.
    """
    # ir-hash: prefix mirrors the inline-IR lookup-key convention.
    result = render_json(_make_analysis(workflow_path="ir-hash:abc123"))
    assert result["summary"]["suggested_run_command"] is None


def test_json_warnings_use_diagnostic_to_dict_shape() -> None:
    diag = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.below-min-predicted",
        message="X: declared cache content is ~512 tokens, below claude/min of 1024",
        suggestions=["Add chunks"],
        context={"category": "cache_warning", "model": "claude-sonnet-4-5"},
    )
    result = render_json(_make_analysis(warnings=[diag]))
    assert result["warnings"][0]["id"] == "cache.below-min-predicted"
    assert result["warnings"][0]["severity"] == "warning"


# ---------------------------------------------------------------------------
# Text renderer — cost tri-state
# ---------------------------------------------------------------------------


def test_text_renders_priced_cost_normally() -> None:
    """Trace path: actually_paid + no_cache_hypothetical + rerun all render."""
    text = render_text(_make_analysis(actually_paid=2.18, no_cache=0.84, rerun=0.42, partial=False))
    assert "~$2.18" in text  # actually_paid
    assert "~$0.84" in text  # no_cache
    assert "~$0.42" in text  # rerun
    assert "$0.00" not in text


def test_text_renders_unavailable_cost_explicitly_not_zero() -> None:
    """All unpriced models → ``unavailable`` (NEVER ``$0.00``)."""
    text = render_text(_make_analysis())
    assert "$0.00" not in text
    assert "unavailable" in text.lower()


def test_text_render_shows_trace_header_line_when_loaded() -> None:
    """Bug 1 follow-up: when a trace was loaded, the header includes a
    ``Trace: <filename> (<status>, recorded <ts>)`` line so the agent can
    see which trace produced the evidence without inspecting JSON output.

    Mutation contract: deleting the ``if analysis.trace_path is not None``
    branch in ``_render_header`` removes the line → assertion fails.
    """
    analysis = _make_analysis(
        actually_paid=2.18,
        no_cache=0.84,
        rerun=0.42,
        trace_path="/home/user/.pflow/debug/workflow-trace-abc12345-lyrics-generator-20260511-153228.json",
        trace_final_status="success",
        trace_recorded_at="2026-05-11T15:32:28.123456",
    )
    text = render_text(analysis)
    assert "Trace: workflow-trace-abc12345-lyrics-generator-20260511-153228.json" in text
    assert "(success, recorded 2026-05-11 15:32)" in text


def test_text_render_trace_header_shows_same_drifted_relationship() -> None:
    analysis = _make_analysis(
        trace_path="/abs/workflow-trace-stale.json",
        trace_final_status="success",
        trace_workflow_relationship="same_drifted",
        trace_model_drift_count=1,
    )

    text = render_text(analysis)

    assert "Trace: workflow-trace-stale.json (success)" in text
    assert "stale: 1 model difference" in text
    assert "this workflow appears as a sub-workflow" not in text


def test_text_render_trace_header_shows_parent_redirect_relationship() -> None:
    analysis = _make_analysis(
        trace_path="/abs/workflow-trace-parent.json",
        trace_final_status="success",
        trace_workflow_relationship="parent_redirect",
    )

    text = render_text(analysis)

    assert "this workflow appears as a sub-workflow; use --from-trace on the root" in text
    assert "stale:" not in text


def test_text_render_omits_trace_header_when_no_trace_loaded() -> None:
    """When ``trace_path`` is None (greenfield or autoload-rejected), no
    ``Trace:`` line appears."""
    analysis = _make_analysis(trace_path=None)
    text = render_text(analysis)
    assert "Trace:" not in text


def test_text_render_trace_header_drops_recorded_suffix_when_timestamp_missing() -> None:
    """Defensive: legacy traces from before 2.1.0 may lack ``start_time``.
    The ``Trace:`` line still renders, just without the ``recorded ...``
    suffix."""
    analysis = _make_analysis(
        actually_paid=2.18,
        no_cache=0.84,
        rerun=0.42,
        trace_path="/abs/trace.json",
        trace_final_status="success",
        trace_recorded_at=None,
    )
    text = render_text(analysis)
    assert "Trace: trace.json (success)" in text
    assert "recorded" not in text.split("Trace:")[1].split("\n")[0]


def test_text_render_trace_header_shows_failed_status_honestly() -> None:
    """Bug 10 cousin: when autoload picked a failed trace (no success
    existed), the agent learns the status in the header — not just the
    Notes section."""
    analysis = _make_analysis(
        actually_paid=2.18,
        no_cache=0.84,
        rerun=0.42,
        trace_path="/abs/workflow-trace-bad.json",
        trace_final_status="failed",
        trace_recorded_at="2026-05-11T16:30:27",
    )
    text = render_text(analysis)
    assert "Trace: workflow-trace-bad.json (failed, recorded 2026-05-11 16:30)" in text


def test_text_render_confidence_footer_shows_stale_memo_counts() -> None:
    analysis = _make_analysis(
        rows=[_row("draft", 50)],
        stale_memo_skipped_count=1,
        stale_memo_uncheckable_count=2,
    )

    text = render_text(analysis)

    assert "1 memoized value skipped as stale" in text
    assert "using fresh estimates instead" in text
    assert "2 memoized values used but freshness could not be verified" in text
    # Negative: pflow internals must not leak into agent-facing output (CLAUDE.md Priority #4)
    assert "estimator-tier" not in text
    assert "cache_key" not in text


def test_text_renders_partial_cost_with_marker() -> None:
    text = render_text(
        _make_analysis(
            actually_paid=0.84,
            no_cache=1.20,
            rerun=0.42,
            partial=True,
            unavailable=("ollama/llama3.2:8b",),
        )
    )
    assert "~$1.20 (partial)" in text
    assert "ollama/llama3.2:8b" in text


def test_text_summary_greenfield_cost_note_drops_pflow_internals() -> None:
    """Stage A.1 — the greenfield "absolute cost figures need a prior run"
    note must not leak pflow-internals language ("memo cache", "2.1.0 trace")
    that requires agent context to interpret. The actionable bit ("run once,
    re-run analyze-cache") survives; the parenthetical pointing at internal
    storage layers is replaced with the agent-readable "real cost figures
    and cacheable projections" symmetric with the Notes string.

    Mutation test: revert ``_render_summary`` at ``render_text.py:185-188`` to
    the old wording; both negative assertions fire — "memo cache" and
    "2.1.0 trace" return to the rendered output.
    """
    from pflow.core.prompt_cache_analysis.types import AnalysisSummary

    # Greenfield path: no current cost, but first-run delta is set so the
    # branch fires.
    base = _make_analysis()
    summary = AnalysisSummary(**{
        **base.summary.__dict__,
        "first_run_delta": CostDelta(0.50, None, "savings", "no_cache", "first_run"),
    })
    analysis = CacheAnalysis(**{**base.__dict__, "summary": summary})
    text = render_text(analysis)

    # NEW agent-readable wording is present.
    assert "Absolute cost figures need a prior run." in text
    assert "real cost figures and cacheable projections" in text
    # OLD pflow-internals language is gone — agent doesn't need to know
    # about pflow's two cache layers or trace format versioning to act.
    assert "memo cache" not in text
    assert "2.1.0 trace" not in text


def test_text_summary_priced_with_savings_branch_emits_suggested_line() -> None:
    """The priced-greenfield-with-savings branch (sibling of the
    cost-data-unavailable branch) also surfaces the paste-ready
    ``Suggested:`` line. Both branches share the same UX problem
    ("run once, re-run analyze-cache") and agents benefit from the
    exact command at either site.

    Mutation contract: removing the ``if s.suggested_run_command``
    block at the priced-with-savings branch in ``render_text.py`` fails
    this test. The companion test above
    (``test_text_summary_greenfield_cost_note_drops_pflow_internals``)
    locks the upstream "Absolute cost figures need a prior run" message
    that this branch precedes.
    """
    from pflow.core.prompt_cache_analysis.types import AnalysisSummary

    base = _make_analysis(workflow_path="/abs/x.pflow.md")
    summary = AnalysisSummary(**{
        **base.summary.__dict__,
        "first_run_delta": CostDelta(0.50, None, "savings", "no_cache", "first_run"),
    })
    analysis = CacheAnalysis(**{**base.__dict__, "summary": summary})
    text = render_text(analysis)

    assert "Absolute cost figures need a prior run." in text
    assert "Suggested:  pflow run /abs/x.pflow.md" in text


def test_text_renderer_shows_relative_workflow_path_without_mutating_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Text output should lead with short workflow labels and cwd-relative paths.

    JSON keeps canonical paths for machine consumers; only the text renderer
    compresses filesystem noise for agents reading the report.
    """
    workflow_path = tmp_path / "workflows" / "lyrics-generator.pflow.md"
    workflow_path.parent.mkdir()
    monkeypatch.chdir(tmp_path)

    analysis = _make_analysis(rows=[_row("draft", 30)], workflow_path=str(workflow_path))
    text = render_text(analysis)
    payload = render_json(analysis)

    assert "# Cache Analysis: lyrics-generator.pflow.md" in text
    assert "  File: workflows/lyrics-generator.pflow.md" in text
    assert "Suggested:  pflow run workflows/lyrics-generator.pflow.md" in text
    assert str(workflow_path) not in text
    assert payload["workflow_path"] == str(workflow_path)
    assert payload["summary"]["suggested_run_command"] == f"pflow run {workflow_path}"


def test_text_summary_renders_blocking_errors_categorically() -> None:
    """Top-10% pattern (mypy / rustc / clippy / ruff): errors render
    categorically separate from opportunities. ``blocking_errors`` lands
    on its own line so an agent skimming counts sees structural blockers
    before optimization advice.

    Mutation test: drop the ``if s.blocking_errors > 0`` block in
    ``_append_summary_counts``; this test fails because "1 error blocking"
    no longer appears.
    """
    from pflow.core.diagnostic import Diagnostic, Severity
    from pflow.core.prompt_cache_analysis.types import AnalysisSummary

    base = _make_analysis()
    summary = AnalysisSummary(**{
        **base.summary.__dict__,
        "blocking_errors": 1,
    })
    err = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Cache Failure",
        node_id="bad-call",
        message="Order mismatch",
        id="cache.order-mismatch",
    )
    analysis = CacheAnalysis(**{**base.__dict__, "summary": summary, "warnings": (err,)})
    text = render_text(analysis)

    assert "1 error blocking" in text
    assert "## Cache blocking errors (must fix before save and run)" in text


def test_text_summary_omits_blocking_line_when_no_errors() -> None:
    """Conditional emission: greenfield workflows (zero ERRORs) must not
    show "0 errors blocking" — that's noise, not signal.

    Mutation test: change the conditional to an unconditional emission;
    this test fails on a greenfield analysis.
    """
    from pflow.core.prompt_cache_analysis.types import AnalysisSummary

    base = _make_analysis()
    summary = AnalysisSummary(**{
        **base.summary.__dict__,
        "blocking_errors": 0,
    })
    analysis = CacheAnalysis(**{**base.__dict__, "summary": summary})
    text = render_text(analysis)

    assert "blocking" not in text


def test_text_renders_suggested_block_placeholder_verbatim() -> None:
    """The renderer outputs the chunk's ``prose_placeholder`` verbatim into
    the cache code fence. This locks the RENDERER side: given a
    SuggestedBlockChunk with placeholder X, X appears in the output.

    NOT an end-to-end test for production placeholder shape — see
    ``test_analyze_emits_starter_prose_placeholder_end_to_end`` below for
    the end-to-end mutation gate that catches production-side changes.

    Mutation test: change the renderer at ``_render_suggested_blocks`` to
    skip ``chunk.prose_placeholder`` (e.g. emit a hardcoded string instead);
    this test fails because the placeholder is missing from output.
    """
    from pflow.core.prompt_cache_analysis.types import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(
            SuggestedBlockChunk(
                name="concept",
                var="${concept}",
                size_tokens_est=500,
                prose_placeholder="The concept:",
            ),
        ),
        per_node_assignments={"write-lyrics": ["concept"]},
        estimated_savings_usd=None,
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})
    text = render_text(analysis)

    # Renderer outputs the placeholder verbatim.
    assert "The concept:" in text


def test_analyze_emits_starter_prose_placeholder_end_to_end() -> None:
    """End-to-end — drive ``analyze()`` against a workflow with shared LLM
    context so ``_populate_suggested_blocks`` emits a real SuggestedBlock.

    The chunk's ``prose_placeholder`` must read as auto-generated starter
    prose (``The X:`` for single-segment refs, ``The Y from X:`` for dotted).
    No leftover ``<TODO>`` markers, no ``<DESCRIBE>`` markers, no
    ``appears verbatim`` pflow-internals language.

    This is the production-side mutation gate. Reverting
    ``_starter_prose_for_ref`` to a TODO/DESCRIBE shape causes this test
    to fail because the placeholder bytes change.

    Why end-to-end matters (Pitfall #19): the renderer-only test above
    constructs a SuggestedBlockChunk with the placeholder string directly,
    so reverting the analyze-side production code wouldn't break it. This
    test drives analyze() so the production placeholder shape is what
    flows into the assertion.
    """
    from pflow.core.prompt_cache_analysis.analyze import analyze

    # Two LLM nodes referencing the same input so ``_populate_suggested_blocks``
    # detects shared context and emits a SuggestedBlock with a chunk for ``topic``.
    workflow_ir = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "node-a",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "About ${topic}: ..."},
            },
            {
                "id": "node-b",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "More on ${topic}: ..."},
            },
        ],
    }
    result = analyze(workflow_ir, parameters={"topic": "x " * 6000}, workflow_path="/abs/x.pflow.md")

    assert result.suggested_blocks, "Analyzer should detect shared context"
    placeholders = [c.prose_placeholder for b in result.suggested_blocks for c in b.chunks]
    # Starter prose form: "The <ref>:" — natural-language label, byte-valid.
    assert all(p.startswith("The ") and p.endswith(":") for p in placeholders), placeholders
    # No leftover marker conventions.
    assert not any("TODO" in p for p in placeholders), placeholders
    assert not any("DESCRIBE" in p for p in placeholders), placeholders
    assert not any("appears verbatim" in p for p in placeholders), placeholders


def test_starter_prose_for_dotted_path_renders_field_from_node() -> None:
    """Dotted refs (``creative-direction.response``) render as
    ``The Y from X:`` form — ``Y`` is the field, ``X`` is the node id.
    Underscores in the field segment become spaces.

    Mutation test: revert ``_starter_prose_for_ref`` to the simpler
    ``The {ref}:`` form for dotted paths; the assertion fails because
    ``creative-direction.response`` would render as
    ``The creative-direction.response:`` instead.
    """
    from pflow.core.prompt_cache_analysis.analyze import _starter_prose_for_ref

    assert _starter_prose_for_ref("concept") == "The concept:"
    assert _starter_prose_for_ref("concept_brief") == "The concept brief:"
    assert _starter_prose_for_ref("creative-direction.response") == "The response from creative-direction:"
    assert _starter_prose_for_ref("chorus-chooser.winning_chorus") == "The winning chorus from chorus-chooser:"


def test_text_suggested_block_intro_explains_starter_prose_audience() -> None:
    """The block-level intro above the cache code fence tells the agent
    that the labels are auto-generated starters they should replace, AND
    that the LLM reads the prose. Per-chunk placeholders are short; this
    intro carries the WHY/HOW once.

    Mutation test: drop the intro lines from ``_render_suggested_blocks``;
    every assertion below fires.
    """
    from pflow.core.prompt_cache_analysis.types import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(
            SuggestedBlockChunk(
                name="concept.core_idea",
                var="${concept.core_idea}",
                size_tokens_est=500,
                prose_placeholder="The core idea from concept:",
            ),
        ),
        per_node_assignments={"write-lyrics": ["concept.core_idea"]},
        estimated_savings_usd=None,
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})
    text = render_text(analysis)

    # Intro names the labels as starters the agent should replace.
    assert "auto-generated starters" in text
    assert "replace each" in text
    # Intro establishes the LLM as the audience.
    assert "The LLM reads this" in text
    # Intro lives ABOVE the ``## Cache`` heading.
    intro_pos = text.find("auto-generated starters")
    cache_heading_pos = text.find("  ## Cache")
    assert intro_pos < cache_heading_pos, "Block-level intro must precede the ## Cache heading"


def test_text_suggested_block_documents_ttl_allowed_values() -> None:
    """Suggested blocks should tell agents the complete accepted TTL vocabulary.

    The parser rejects provider wire strings and out-of-range durations;
    surfacing the accepted pflow syntax beside the generated ``- ttl:`` line
    prevents authoring-time guesses.
    """
    from pflow.core.prompt_cache_analysis.types import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(
            SuggestedBlockChunk(
                name="concept.core_idea",
                var="${concept.core_idea}",
                size_tokens_est=500,
                prose_placeholder="The core idea from concept:",
            ),
        ),
        per_node_assignments={},
        estimated_savings_usd=None,
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})
    text = render_text(analysis)

    assert "  - ttl: 5m" in text
    assert "`ttl` accepts `1m` through `60m`; `1h` is also accepted." in text


# ---------------------------------------------------------------------------
# Text renderer — default-hide-clean per-call rule
# ---------------------------------------------------------------------------


def _row(node_path: str, ratio: int) -> PerCallRow:
    """Build a PerCallRow that survives the Option C real-data filter.

    Default ``data_source="memo"`` makes the row visible in the per-call cache
    report — the section is hidden entirely when no row has real data
    (``data_source in {"trace", "memo"}`` OR ``declared_prompt_cache`` set).
    Tests that specifically exercise the data-source display mapping override
    this with ``"estimator"``/``"heuristic"`` AND set ``declared_prompt_cache``
    so the row passes the filter via the steady-state branch.

    Stage 0.3 (Task 159): the inline ``warnings`` parameter is gone — the
    field was vestigial and its only test exercised the dead fallback path.
    Per-row warning markers in production are derived from
    ``analysis.warnings`` filtered by ``node_id``; tests inject Diagnostics
    via ``warnings=[diag]`` on ``_make_analysis``.
    """
    return PerCallRow(
        node_path=node_path,
        model="anthropic/claude-sonnet-4-5",
        is_batch=False,
        batch_size_estimated=None,
        input_tokens_estimated=10_000,
        cacheable_tokens_estimated=int(10_000 * ratio / 100),
        cache_ratio_pct=ratio,
        data_source="memo",
        declared_prompt_cache=None,
    )


def _per_call_cells(text: str, node_path: str) -> list[str]:
    for line in text.splitlines():
        if line.lstrip().startswith(f"{node_path}  "):
            return re.split(r" {2,}", line.strip(), maxsplit=7)
    raise AssertionError(f"expected per-call row for {node_path!r} in:\n{text}")


def _per_call_cells_by_header(text: str, node_path: str) -> dict[str, str]:
    headers: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("node  "):
            headers = re.split(r" {2,}", stripped)
            continue
        if headers is not None and line.lstrip().startswith(f"{node_path}  "):
            cells = re.split(r" {2,}", stripped, maxsplit=len(headers) - 1)
            if len(cells) < len(headers):
                cells.extend([""] * (len(headers) - len(cells)))
            return dict(zip(headers, cells, strict=True))
    raise AssertionError(f"expected per-call row for {node_path!r} in:\n{text}")


def _per_call_header(text: str) -> list[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("node  "):
            return re.split(r" {2,}", stripped)
    raise AssertionError(f"expected per-call header in:\n{text}")


def test_text_default_hides_clean_rows_above_80_pct() -> None:
    rows = [_row("clean1", 90), _row("clean2", 95), _row("dirty", 30)]
    text = render_text(_make_analysis(rows=rows))
    assert "dirty" in text
    assert "clean1" not in text
    assert "clean2" not in text
    assert "Hidden: 2 low-signal nodes" in text


def test_text_all_rows_flag_shows_everything() -> None:
    rows = [_row("clean1", 90), _row("clean2", 95), _row("dirty", 30)]
    text = render_text(_make_analysis(rows=rows), all_rows=True)
    assert "clean1" in text
    assert "clean2" in text
    assert "dirty" in text
    assert "Hidden:" not in text


def test_per_call_row_renders_tokens_unmeasurable_for_opaque_prompt_with_no_data() -> None:
    row = PerCallRow(**{
        **_row("generate-chorus-options", 50).__dict__,
        "input_tokens_estimated": 3,
        "cacheable_tokens_estimated": None,
        "cache_ratio_pct": None,
        "data_source": "heuristic",
        "declared_prompt_cache": ["prompt"],
        "cacheable_data_source": "unavailable",
    })
    warning = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.opaque-prompt",
        node_id="generate-chorus-options",
        message="Opaque prompt.",
    )

    text = render_text(_make_analysis(rows=[row], warnings=[warning]))

    cells = _per_call_cells(text, "generate-chorus-options")
    assert cells[2] == "?"
    assert cells[2] != "3"


def test_per_call_row_keeps_tokens_for_opaque_prompt_with_cacheable_data() -> None:
    row = PerCallRow(**{
        **_row("generate-chorus-options", 50).__dict__,
        "input_tokens_estimated": 3,
        "cacheable_tokens_estimated": 2,
        "cache_ratio_pct": 67,
        "data_source": "memo",
        "declared_prompt_cache": ["prompt"],
        "cacheable_data_source": "memo",
    })
    warning = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.opaque-prompt",
        node_id="generate-chorus-options",
        message="Opaque prompt.",
    )

    text = render_text(_make_analysis(rows=[row], warnings=[warning]))

    cells = _per_call_cells(text, "generate-chorus-options")
    assert cells[2] == "3"
    assert cells[2] != "?"


def test_text_truncated_trace_labels_executed_scope() -> None:
    row = PerCallRow(**{
        **_row("ran", 90).__dict__,
        "data_source": "trace",
        "cost_usd": 0.001,
        "cost_data_source": "trace",
    })
    skipped = PerCallRow(**{
        **_row("skipped", 90).__dict__,
        "did_not_execute_in_trace": True,
        "data_source": "estimator",
    })
    base = _make_analysis(rows=[row, skipped], actually_paid=0.001, no_cache=0.01, rerun=0.002)
    analysis = CacheAnalysis(**{
        **base.__dict__,
        "summary": AnalysisSummary(**{
            **base.summary.__dict__,
            "trace_coverage": "truncated",
            "evidence_scope": "truncated_trace_executed_subset",
            "trace_llm_nodes_static": 2,
            "trace_llm_nodes_executed": 1,
            "trace_unexecuted_llm_rows": (TraceUnexecutedLLMRow("/abs/x.pflow.md", "skipped"),),
        }),
    })

    text = render_text(analysis)

    assert "Evidence: trace truncated (1 of 2 LLM nodes executed)" in text
    assert "Trace-backed costs below cover executed nodes only." in text
    assert "Actually paid (executed trace):" in text
    assert "Cost without caching (executed):" in text
    assert "Cost on rerun (executed, within TTL):" in text
    assert "Showing 1 executed LLM node; 1 unexecuted row hidden (--all-rows shows everything)." in text
    assert "all-clean rows hidden" not in text
    assert "Trace-dependent optimization recommendations suppressed because the trace is truncated" in text


def test_json_truncated_trace_exposes_evidence_scope_and_observed_models(tmp_path: Path) -> None:
    from pflow.core.prompt_cache_analysis.analyze import analyze
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    wf_path = str(tmp_path / "x.pflow.md")
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "About ${topic}"},
                "batch": {"items": [{"model": "gemini/a"}, {"model": "gemini/b"}]},
            },
            {
                "id": "review",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Review ${generate.response}",
                },
            },
        ],
    }
    builder = TraceFixtureBuilder()
    trace_data = {
        "format_version": "2.2.0",
        "workflow_path": wf_path,
        # Truncated coverage: workflow died before "review" ran.
        "final_status": "failed",
        "nodes": [
            builder.batch_event(
                "generate",
                [
                    {
                        "index": 0,
                        "success": True,
                        "duration_ms": 1.0,
                        "node_output": {"response": "ok"},
                        "llm_call": {
                            "model": "gemini/a",
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "cost_usd": 0.001,
                        },
                    },
                    {
                        "index": 1,
                        "success": True,
                        "duration_ms": 1.0,
                        "node_output": {"response": "ok"},
                        "llm_call": {
                            "model": "gemini/b",
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "cost_usd": 0.001,
                        },
                    },
                ],
            ),
        ],
    }
    analysis = analyze(
        workflow_ir,
        parameters={"topic": "x"},
        workflow_path=wf_path,
        trace_path=_write_trace(tmp_path / "truncated-trace.json", trace_data),
        auto_load_trace=False,
        memo_cache=None,
    )

    payload = render_json(analysis)

    assert payload["summary"]["evidence_scope"] == "truncated_trace_executed_subset"
    assert payload["summary"]["observed_models_in_trace"] == ["gemini/a", "gemini/b"]
    assert payload["per_call"][0]["observed_models"] == ["gemini/a", "gemini/b"]
    assert payload["per_call"][0]["observed_call_count"] == 2
    unexecuted = payload["summary"]["trace_unexecuted_llm_rows"]
    assert any(row["node_path"] == "review" for row in unexecuted)


def test_json_summary_exposes_projection_exclusions_and_delta_reason(tmp_path: Path) -> None:
    from pflow.core.prompt_cache_analysis.analyze import analyze

    workflow_ir = {
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "${item.prompt}"},
                "batch": {"items": "${items}"},
            },
            {
                "id": "static-call",
                "type": "llm",
                "params": {"model": "anthropic/claude-haiku-4-5", "prompt": "Score the options."},
            },
        ]
    }
    trace_data = {
        "format_version": "2.2.0",
        "workflow_path": "x",
        "nodes": [
            {
                "node_id": "generate",
                "node_type": "LLMNode",
                "success": True,
                "batch_items": [
                    {
                        "index": 0,
                        "success": True,
                        "llm_call": {
                            "model": "gemini/gemini-2.5-flash-lite",
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "cost_usd": 0.01,
                        },
                    },
                    {
                        "index": 1,
                        "success": True,
                        "llm_call": {
                            "model": "gemini/gemini-3-flash-preview",
                            "input_tokens": 200,
                            "output_tokens": 20,
                            "cost_usd": 0.02,
                        },
                    },
                ],
            },
            {
                "node_id": "static-call",
                "node_type": "LLMNode",
                "success": True,
                "llm_call": {
                    "model": "anthropic/claude-haiku-4-5",
                    "input_tokens": 500,
                    "output_tokens": 50,
                    "cost_usd": 0.05,
                },
            },
        ],
    }
    analysis = analyze(
        workflow_ir,
        parameters={"items": [{"model": "a", "prompt": "x"}, {"model": "b", "prompt": "y"}]},
        workflow_path="x",
        trace_path=_write_trace(tmp_path / "heterogeneous-trace.json", trace_data),
        auto_load_trace=False,
        memo_cache=None,
    )

    payload = render_json(analysis)

    exclusions = payload["summary"]["projection_exclusions"]
    assert any(exclusion["reason"] == "heterogeneous_model" for exclusion in exclusions)
    assert any(exclusion["node_path"] == "generate" for exclusion in exclusions)
    delta = payload["summary"]["actual_vs_no_cache_delta"]
    # Priced-cohort path: total_paid - excluded.actual_cost_usd is computed
    # because every exclusion has a trace-recorded cost. The renderer surfaces
    # the excluded nodes so JSON consumers can show what was left out.
    assert delta["kind"] != "unavailable"
    assert delta["unavailable_reason"] is None
    assert delta["compared_to"] == "actually_paid_priced_cohort_usd"
    assert delta["excluded_nodes"] == ["generate"]
    assert payload["summary"]["heterogeneous_model_node_count"] >= 1
    assert "generate" in payload["summary"]["heterogeneous_model_node_paths"]


def test_text_summary_explains_projection_excluded_actual_delta() -> None:
    """Renderer surfaces the ``Excluded from analysis`` line and bare
    ``unavailable`` savings when an exclusion lacks ``actual_cost_usd``.

    Production hits this state when an excluded row's ``cost_usd`` is None —
    typically an ``unpriced_model`` exclusion where LiteLLM didn't recognize
    the model so the trace event also lacks a cost figure. Without a number
    to subtract, the priced-cohort math is genuinely incomparable, but the
    agent still needs to know which node and why — the explicit excluded
    line carries that context (without the dollar figure since none is
    available).
    """
    exclusion = ProjectionExclusion(
        workflow_path="/abs/x.pflow.md",
        node_path="generate",
        reason="unpriced_model",
        actual_cost_usd=None,
    )
    analysis = _make_analysis(
        actually_paid=0.05,
        no_cache=0.02,
        partial=True,
        projection_exclusions=(exclusion,),
        actual_delta_unavailable_reason="projection_exclusions",
    )

    text = render_text(analysis)

    assert "Actually paid:               ~$0.05 (from trace)" in text
    assert "Actually paid:               ~$0.05 (partial) (from trace)" not in text
    # Label is bare ``Actually paid:`` — the value's parenthetical
    # (``(from trace)`` / ``(from partial trace)``) carries the tier
    # signal; repeating it on the label would be redundant. Truncated
    # branch keeps ``(executed trace)`` because "executed" is the unique
    # signal there. Raw snake_case enum values (``trace_partial``) must
    # NOT leak into stdout.
    assert "Actually paid (from trace):" not in text
    assert "trace_partial" not in text
    # Excluded node + reason render even without a dollar figure (cost is None).
    assert "Excluded from analysis:      generate: no pricing data for model" in text
    # Cohort qualifiers on no-cache/rerun labels are gone — the explicit
    # excluded line above establishes which nodes are out of the cohort.
    assert "Cost without caching:" in text
    assert "Cost without caching (projected subset):" not in text
    assert "Cost on rerun (within TTL):" in text
    assert "Cost on rerun (within TTL, projected subset):" not in text
    # Candidate A: when the actual delta is ``unavailable`` (here because the
    # exclusion lacks pricing data), the parenthetical drops entirely — no
    # dangling "(saves N% vs ...)" on the Actually paid line, no separate
    # ``Actual cost delta (this run): unavailable`` line. The excluded line
    # above carries the "why."
    actually_paid_line = next(line for line in text.splitlines() if "Actually paid:" in line)
    assert "(saves" not in actually_paid_line
    assert "(adds" not in actually_paid_line
    assert "unavailable" not in actually_paid_line
    # Legacy delta lines must not appear anywhere in the output.
    assert "Actual cost delta" not in text
    assert "Actual trace delta:" not in text


def test_trace_mode_folds_excluded_passthrough_into_projections() -> None:
    """Fix 7: when all projection_exclusions carry a trace-recorded
    actual_cost_usd, the renderer FOLDS that cost into the no-cache /
    rerun projections so the cost block reconciles in-place without the
    agent doing subtraction. The standalone ``Excluded from analysis:``
    line is replaced by a footnote.

    Math reconciliation: paid $2.31 < no-cache (folded) $2.43 — natural
    direction. Excluded $0.27 = $2.43 - $2.16 (the analyzer's priced
    cohort no-cache value). Agent reads top-to-bottom without subtraction.

    Mutation contract: drop the ``can_fold`` branch in
    ``_render_trace_cost_lines`` → the cost block reverts to showing
    the Excluded line + priced-cohort no-cache value, breaking the
    cohort reconciliation.
    """
    exclusion = ProjectionExclusion(
        workflow_path="/abs/x.pflow.md",
        node_path="generate-chorus-options",
        reason="heterogeneous_model",
        actual_cost_usd=0.27,
    )
    analysis = _make_analysis(
        actually_paid=2.31,
        no_cache=2.16,  # analyzer's priced-cohort value
        rerun=2.07,
        partial=True,
        projection_exclusions=(exclusion,),
    )

    text = render_text(analysis)
    # No-cache is folded: $2.16 + $0.27 = $2.43 — now larger than paid.
    assert "Cost without caching:        ~$2.43" in text
    # Rerun is folded: $2.07 + $0.27 = $2.34.
    assert "Cost on rerun (within TTL):  ~$2.34" in text
    # The old standalone Excluded line is GONE in the folded case.
    assert "Excluded from analysis:" not in text
    # Footnote names the excluded node + amount + honest framing (Bug 13: no
    # "pass-through" jargon; "couldn't be analyzed" is the agent-readable form).
    assert "~$0.27 of the above was paid by generate-chorus-options" in text
    assert "couldn't be analyzed for cache savings" in text
    assert "model varies per call" in text
    assert "Caching may still apply at runtime" in text
    # Negative assertion: lock the jargon-free wording.
    assert "pass-through" not in text


def test_trace_mode_separates_local_memo_reuse_from_provider_prompt_cache() -> None:
    analysis = _make_analysis(
        actually_paid=0.09,
        no_cache=0.37,
        rerun=0.12,
        trace_provider_llm_call_count=3,
        trace_local_memo_llm_hit_count=56,
        trace_local_cache_input_tokens=551_454,
        trace_provider_cache_read_input_tokens=12_345,
    )

    text = render_text(analysis)
    payload = render_json(analysis)

    # Candidate A: ``incl. local cache reuse`` moves into the
    # ``Actually paid`` parenthetical so the qualifier appears on the
    # same line as the dollar figure. The separate cache-layer lines
    # below still spell out the underlying counts.
    actually_paid_line = next(line for line in text.splitlines() if "Actually paid:" in line)
    assert "incl. local cache reuse" in actually_paid_line
    assert "Local pflow cache reuse:     skipped 56 memo LLM call(s) (551,454 historical input tokens)" in text
    assert "Provider cache in this run:  3 provider LLM call(s), 12,345 cache-read tokens" in text
    assert "run with --no-cache to measure provider prompt caching cleanly" in text
    assert payload["summary"]["trace_local_memo_llm_hit_count"] == 56
    assert payload["summary"]["trace_provider_cache_read_input_tokens"] == 12_345


def test_rerun_label_includes_warm_trace_suffix_when_trace_already_cached() -> None:
    """S#14: when the loaded trace already shows provider cache reads,
    the ``Cost on rerun (within TTL)`` line carries a clarifying suffix so
    agents recognize that the projection models a different scenario than
    the trace itself (the trace was already warm-cache).

    Mutation contract: drop the warm-trace branch in ``_rerun_label`` →
    the suffix assertion fails. Drop the suffix gating on
    ``trace_provider_cache_read_input_tokens > 0`` → the
    ``test_trace_mode_separates_local_memo_reuse_from_provider_prompt_cache``
    text assertions still pass, but any other trace test would falsely
    show the suffix.
    """
    analysis = _make_analysis(
        actually_paid=0.09,
        no_cache=0.37,
        rerun=0.12,
        trace_provider_cache_read_input_tokens=12_345,
    )

    text = render_text(analysis)
    assert "Cost on rerun (within TTL), modeled rerun vs warm-cache trace:" in text


def test_rerun_label_truncated_trace_includes_warm_trace_suffix_when_cached() -> None:
    """S#14 truncated-trace variant: the truncated cost-line layout uses
    the ``(executed, within TTL)`` form, and the warm-cache suffix still
    appends when the trace already showed provider cache reads."""
    base = _make_analysis(
        actually_paid=0.09,
        no_cache=0.37,
        rerun=0.12,
        trace_provider_cache_read_input_tokens=12_345,
    )
    analysis = CacheAnalysis(**{
        **base.__dict__,
        "summary": AnalysisSummary(**{
            **base.summary.__dict__,
            "trace_coverage": "truncated",
            "evidence_scope": "truncated_trace_executed_subset",
            "trace_llm_nodes_static": 2,
            "trace_llm_nodes_executed": 1,
            "trace_unexecuted_llm_rows": (TraceUnexecutedLLMRow("/abs/x.pflow.md", "skipped"),),
        }),
    })

    text = render_text(analysis)
    assert "Cost on rerun (executed, within TTL), modeled rerun vs warm-cache trace:" in text


def test_rerun_label_greenfield_never_includes_warm_trace_suffix() -> None:
    """S#14 boundary: greenfield mode (no trace) never carries the
    warm-cache suffix even when the field is non-zero (greenfield setup
    shouldn't produce that field, but defending the helper's contract)."""
    analysis = _make_analysis(
        no_cache=0.10,
        first_run_with_cache=0.09,
        rerun=0.04,
        trace_provider_cache_read_input_tokens=12_345,
    )

    text = render_text(analysis)
    assert "Cost on rerun (within TTL):" in text
    assert "modeled rerun vs warm-cache trace" not in text


def test_trace_mode_falls_back_to_excluded_line_when_excluded_cost_unknown() -> None:
    """Fix 7 fallback: when any excluded row has ``actual_cost_usd=None``
    (honest-unmeasurable), we can't pass through what we didn't measure.
    Keep the original ``Excluded from analysis:`` line + priced-cohort
    projections.

    Mutation contract: make the fold branch unconditional (ignore the
    None check) → the assertion that the Excluded line is present fails
    AND the pass-through math becomes wrong (under-counting unpriced
    exclusion). Either way, the test fails.
    """
    exclusion = ProjectionExclusion(
        workflow_path="/abs/x.pflow.md",
        node_path="ghost-node",
        reason="unpriced_model",
        actual_cost_usd=None,  # honest unmeasurable
    )
    analysis = _make_analysis(
        actually_paid=2.31,
        no_cache=2.16,
        rerun=2.07,
        partial=True,
        projection_exclusions=(exclusion,),
    )
    text = render_text(analysis)
    # Excluded line falls back to render without dollar amount.
    assert "Excluded from analysis:" in text
    assert "ghost-node" in text
    # Original no-cache value (priced cohort, unchanged) — NOT folded.
    assert "Cost without caching:        ~$2.16" in text
    # No footnote in this branch — nothing was folded.
    assert "was paid by" not in text
    assert "pass-through" not in text


def test_trace_mode_no_exclusions_renders_clean_cost_block() -> None:
    """Fix 7 baseline: when no exclusions exist, the cost block is the
    simplest case — no Excluded line, no footnote, no fold.

    Mutation contract: emit the Excluded line or footnote unconditionally
    → either negative assertion fails.
    """
    analysis = _make_analysis(actually_paid=2.31, no_cache=2.53)
    text = render_text(analysis)
    assert "Excluded from analysis:" not in text
    assert "was paid by" not in text
    assert "pass-through" not in text
    assert "Cost without caching:        ~$2.53" in text


def test_trace_mode_folds_multi_node_exclusions_into_footnote() -> None:
    """Fix 7 multi-exclusion: when multiple nodes are excluded and all
    have trace-recorded costs, the footnote names them comma-separated
    and the projection lines fold the summed pass-through.

    Mutation contract: drop multi-exclusion handling in
    ``_format_passthrough_footnote`` → the multi-node CSV form fails.
    """
    exclusions = (
        ProjectionExclusion(
            workflow_path="/abs/x.pflow.md",
            node_path="alpha",
            reason="heterogeneous_model",
            actual_cost_usd=0.10,
        ),
        ProjectionExclusion(
            workflow_path="/abs/x.pflow.md",
            node_path="beta",
            reason="unpriced_model",
            actual_cost_usd=0.05,
        ),
    )
    analysis = _make_analysis(
        actually_paid=1.00,
        no_cache=1.20,
        partial=True,
        projection_exclusions=exclusions,
    )
    text = render_text(analysis)
    # Folded no-cache: $1.20 + $0.10 + $0.05 = $1.35.
    assert "Cost without caching:        ~$1.35" in text
    # Footnote names both nodes inline with their exclusion reason
    # (Bug 13: no "pass-through" jargon; inline reasons are agent-readable).
    assert "~$0.15 of the above was paid by nodes that couldn't be analyzed" in text
    assert "alpha (model varies per call)" in text
    assert "beta (no pricing data for model)" in text
    # Negative assertion: lock the jargon-free wording.
    assert "pass-through" not in text
    # No standalone Excluded line.
    assert "Excluded from analysis:" not in text


def test_greenfield_with_cache_drops_partial_qualifier_when_excluded_line_renders() -> None:
    """Fix A — greenfield-with-cache branch: the ``(projected subset)`` label
    suffix already conveys "this is over a partial cohort" when
    projection_exclusions is populated. The ``(partial)`` parenthetical on
    the value side is redundant and gets dropped.

    Mutation contract: revert ``projection_partial_marker`` in
    ``_render_greenfield_with_cache_lines`` to ``s.partial_cost_usd`` →
    label-and-value lines re-acquire ``(partial)`` and the negative
    assertion fails.
    """
    exclusion = ProjectionExclusion(
        workflow_path="/abs/x.pflow.md",
        node_path="generate",
        reason="heterogeneous_model",
        actual_cost_usd=None,
    )
    analysis = _make_analysis(
        no_cache=1.20,
        first_run_with_cache=0.95,
        rerun=0.80,
        partial=True,
        projection_exclusions=(exclusion,),
    )

    text = render_text(analysis)

    # Label still carries (projected subset) — the cohort is genuinely partial.
    assert "Cost without caching (projected subset):" in text
    # But the value-side (partial) marker is gone — redundant with the
    # label suffix and the Excluded line above.
    assert "(partial)" not in text


def test_greenfield_no_cache_keeps_partial_qualifier_no_other_signal() -> None:
    """Fix A — greenfield-no-cache (single ``Cost per run:`` line) MUST keep
    ``(partial)``: there's no Excluded-from-analysis line, no ``(projected
    subset)`` label suffix, and no ``(executed)`` qualifier in this branch.
    The parenthetical is the only signal that the projection cohort is
    incomplete.

    Mutation contract: extend the projection_partial_marker suppression to
    ``_render_greenfield_no_cache_lines`` → this assertion fails (the cohort
    signal vanishes silently).
    """
    analysis = _make_analysis(
        no_cache=0.50,
        partial=True,
    )

    text = render_text(analysis)

    # Single-line greenfield-no-cache case — preserve (partial) qualifier.
    assert "Cost per run:                ~$0.50 (partial)" in text


def test_per_call_explainer_renders_multi_line_block_without_divide_by_calls() -> None:
    """``_per_call_scope_explainer`` returns a multi-line block — a "How to
    read each row:" header plus two column bullets, each explaining its own
    placeholders inline (``?`` / ``—``). The prior "divide by calls for
    per-call values" advice was structurally wrong after Pass A2 normalized
    static-list batch trace rows to per-call units, and the prior
    ``"tier"`` phrasing leaked internal vocabulary into stdout.

    Mutation contract: revert the function to return a single string with
    the run-on text → the multi-line shape assertions fail AND the
    ``divide by calls`` negative assertion fails. Re-introduce ``"tier"``
    in the prose → the negative assertion below fires.
    """
    rows = [
        PerCallRow(
            node_path="generate",
            model="anthropic/claude-sonnet-4-5",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=2000,
            cacheable_tokens_estimated=1500,
            cache_ratio_pct=75,
            data_source="trace",
            declared_prompt_cache=("article",),
            workflow_path="/abs/x.pflow.md",
            cacheable_data_source="trace",
            observed_call_count=4,
        ),
        PerCallRow(
            node_path="rewrite",
            model="anthropic/claude-sonnet-4-5",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=2000,
            cacheable_tokens_estimated=1200,
            cache_ratio_pct=60,
            data_source="trace",
            declared_prompt_cache=None,
            workflow_path="/abs/x.pflow.md",
            cacheable_data_source="memo",
            observed_call_count=4,
        ),
    ]
    analysis = _make_analysis(rows=rows, actually_paid=0.10, no_cache=0.20)

    text = render_text(analysis)

    # Header and column bullets each on their own line — standalone substrings.
    assert "How to read each row:" in text
    assert "· cached_now: tokens served from cache during this run (requires trace)." in text
    assert "· ready: tokens already active or unlockable by a direct cache edit" in text
    assert "· upside: unrealized cache opportunity" in text
    # Run-on form with semicolon separators must NOT appear.
    assert "cached_now: tokens served from cache during this run; could_cache:" not in text
    # The wrong-after-Pass-A2 advice is gone.
    assert "divide by calls" not in text
    assert "Numbers aggregate across all calls" not in text
    # The prior "tier" jargon and "sibling column" abstraction must NOT leak.
    assert "this row's tier" not in text
    assert "sibling column" not in text
    # The collapsed block replaces the old steady-state / greenfield split.
    assert "Actual cache ratios from declared" not in text
    assert "Projected cache ratios from prior run data" not in text


def test_cell_calls_renders_em_dash_in_static_mode_only() -> None:
    """Fix C: ``_cell_calls`` renders ``—`` instead of ``0`` when the
    workflow was analyzed standalone (no trace evidence). In trace mode,
    ``observed_call_count == 0`` is a real signal (conditional branch not
    taken) and MUST render as ``0``.

    Mutation contract: drop the ``static_mode`` gate → static-analysis mode
    renders ``0``, fresh agents reading a sub-workflow analyzed standalone
    misread it as "this node never runs".
    """
    from pflow.core.prompt_cache_analysis.render_text import _cell_calls

    row_unobserved = PerCallRow(
        node_path="generate",
        model="anthropic/claude-sonnet-4-5",
        is_batch=False,
        batch_size_estimated=None,
        input_tokens_estimated=100,
        cacheable_tokens_estimated=None,
        cache_ratio_pct=None,
        data_source="estimator",
        declared_prompt_cache=None,
        workflow_path="/abs/x.pflow.md",
        observed_call_count=0,
    )
    row_observed = dataclasses.replace(row_unobserved, observed_call_count=4)

    # Static-analysis mode: zero is rendered as em-dash (no execution evidence).
    assert _cell_calls(row_unobserved, static_mode=True) == "—"
    # Even nonzero counts can't appear in static mode (by construction —
    # static analysis has no trace, so observed_call_count is always 0 —
    # but defense-in-depth keeps the gate symmetric).
    assert _cell_calls(row_observed, static_mode=True) == "—"
    # Trace mode: integer renders directly, including a real 0.
    assert _cell_calls(row_unobserved, static_mode=False) == "0"
    assert _cell_calls(row_observed, static_mode=False) == "4"


def test_static_mode_per_call_table_renders_em_dash_for_calls_column_e2e() -> None:
    """Fix C end-to-end: when ``evidence_scope == "static_analysis"`` the
    rendered per-call table hides the calls column entirely.
    The ``calls=0`` rendering previously masqueraded as "this node never
    runs" for fresh agents running ``pflow analyze-cache`` on a sub-
    workflow standalone (which is what ``## Per-child analyze-cache
    commands`` instructs them to do).

    Mutation contract: revert ``_append_per_call_rows``'s ``static_mode``
    threading → calls render as ``0`` and the negative ``" 0  "``
    assertion still tolerates it (kept for column-position robustness).
    The positive ``—`` assertion does the load-bearing check.
    """
    rows = [
        PerCallRow(
            node_path="generate",
            model="anthropic/claude-sonnet-4-5",
            is_batch=False,
            batch_size_estimated=None,
            input_tokens_estimated=2000,
            cacheable_tokens_estimated=1500,
            cache_ratio_pct=75,
            data_source="memo",
            declared_prompt_cache=("article",),
            workflow_path="/abs/x.pflow.md",
            cacheable_data_source="memo",
            observed_call_count=0,
        ),
    ]
    # Note: _make_analysis sets evidence_scope="static_analysis" when
    # actually_paid is None — so omitting the trace-cost knob is the
    # builder's path into static mode.
    analysis = _make_analysis(rows=rows, no_cache=0.05)

    text = render_text(analysis)
    lines = text.splitlines()
    header = _per_call_header(text)
    assert "calls" not in header
    # Locate the per-call data row (after `node`/`---` header lines).
    data_lines = [line for line in lines if "generate" in line and "anthropic" in line]
    assert data_lines, f"per-call data row missing — text was:\n{text}"
    row_text = data_lines[0]
    assert "  0" not in row_text


def test_header_discloses_ir_default_when_overridden_by_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pflow.core.prompt_cache_analysis.analyze import analyze

    analyze_module = sys.modules["pflow.core.prompt_cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-haiku-4-5")
    workflow_ir = {"nodes": [{"id": "generate", "type": "llm", "params": {"prompt": "Hello"}}]}
    analysis = analyze(
        workflow_ir,
        workflow_path="x",
        trace_path=_trace_path(
            tmp_path,
            workflow_path="x",
            nodes=[_llm_event("generate", model="gemini/gemini-2.5-flash")],
        ),
        auto_load_trace=False,
    )

    assert "IR/settings declares: anthropic/claude-haiku-4-5 (overridden by trace evidence)" in render_text(analysis)


def test_header_does_not_disclose_when_ir_matches_observed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pflow.core.prompt_cache_analysis.analyze import analyze

    analyze_module = sys.modules["pflow.core.prompt_cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-haiku-4-5")
    workflow_ir = {"nodes": [{"id": "generate", "type": "llm", "params": {"prompt": "Hello"}}]}
    analysis = analyze(
        workflow_ir,
        workflow_path="x",
        trace_path=_trace_path(
            tmp_path,
            workflow_path="x",
            nodes=[_llm_event("generate", model="anthropic/claude-haiku-4-5")],
        ),
        auto_load_trace=False,
    )

    assert "IR/settings declares:" not in render_text(analysis)


def test_header_does_not_disclose_when_no_observed(monkeypatch: pytest.MonkeyPatch) -> None:
    from pflow.core.prompt_cache_analysis.analyze import analyze

    analyze_module = sys.modules["pflow.core.prompt_cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-haiku-4-5")
    workflow_ir = {"nodes": [{"id": "generate", "type": "llm", "params": {"prompt": "Hello"}}]}
    analysis = analyze(workflow_ir, workflow_path="x", auto_load_trace=False)

    assert "IR/settings declares:" not in render_text(analysis)


def test_trace_mode_attaches_delta_parenthetical_to_actually_paid_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Candidate A: trace mode embeds the actual-vs-no-cache delta as a
    parenthetical on the ``Actually paid`` line and the rerun delta as a
    parenthetical on the ``Cost on rerun`` line. No separate ``Actual
    cost delta`` / ``Rerun delta`` lines; no greenfield-only
    ``First-run delta`` line in trace mode.

    Mutation contract: restoring the deleted ``_render_trace_deltas`` →
    a separate ``Actual cost delta`` line reappears.
    """
    from pflow.core.prompt_cache_analysis.analyze import analyze

    analyze_module = sys.modules["pflow.core.prompt_cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-sonnet-4-5")
    workflow_ir = {"nodes": [{"id": "generate", "type": "llm", "params": {"prompt": "Hello"}}]}
    analysis = analyze(
        workflow_ir,
        workflow_path="x",
        trace_path=_trace_path(
            tmp_path,
            workflow_path="x",
            nodes=[_llm_event("generate", model="anthropic/claude-sonnet-4-5")],
        ),
        auto_load_trace=False,
    )

    text = render_text(analysis)
    # Legacy delta-line labels must not appear.
    assert "Actual cost delta" not in text
    assert "Rerun delta" not in text
    assert "First-run delta" not in text
    # The actually-paid line carries the savings parenthetical (the synthetic
    # trace's measured cost is below the no-cache hypothetical).
    actually_paid_line = next(line for line in text.splitlines() if "Actually paid:" in line)
    rerun_line = next(line for line in text.splitlines() if "Cost on rerun (within TTL):" in line)
    assert "vs cost without caching" in actually_paid_line
    # Rerun line carries a parenthetical too (kind depends on the synthetic
    # trace's numbers — savings, cost_increase, or break_even). Locking that
    # SOME parenthetical attaches; the per-kind shape is covered by the
    # dedicated _format_delta_parenthetical unit tests above.
    assert "(" in rerun_line and ")" in rerun_line


def test_trace_mode_parentheticals_use_consistent_baseline_phrase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parenthetical phrase ``vs cost without caching`` is consistent
    across priced and heterogeneous-batch traces (where the actual delta
    may be unavailable, but the rerun delta is still computed). The
    legacy ``Actual trace delta:`` label must NOT reappear.
    """
    from pflow.core.prompt_cache_analysis.analyze import analyze

    analyze_module = sys.modules["pflow.core.prompt_cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-sonnet-4-5")
    priced = analyze(
        {"nodes": [{"id": "generate", "type": "llm", "params": {"prompt": "Hello"}}]},
        workflow_path="x",
        trace_path=_trace_path(
            tmp_path,
            workflow_path="x",
            nodes=[_llm_event("generate", model="anthropic/claude-sonnet-4-5")],
            name="priced-trace.json",
        ),
        auto_load_trace=False,
    )
    unavailable_workflow = {
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "${item.prompt}"},
                "batch": {"items": "${items}"},
            }
        ]
    }
    unavailable_trace = {
        "format_version": "2.2.0",
        "workflow_path": "x",
        "final_status": "success",
        "nodes": [
            {
                "node_id": "generate",
                "node_type": "LLMNode",
                "success": True,
                "batch_items": [
                    {
                        "index": 0,
                        "success": True,
                        "llm_call": {
                            "model": "gemini/gemini-2.5-flash",
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "cost_usd": 0.01,
                        },
                    },
                    {
                        "index": 1,
                        "success": True,
                        "llm_call": {
                            "model": "anthropic/claude-haiku-4-5",
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "cost_usd": 0.01,
                        },
                    },
                ],
            }
        ],
    }
    unavailable = analyze(
        unavailable_workflow,
        parameters={"items": [{"model": "a", "prompt": "a"}, {"model": "b", "prompt": "b"}]},
        workflow_path="x",
        trace_path=_write_trace(tmp_path / "unavailable-trace.json", unavailable_trace),
        auto_load_trace=False,
    )

    priced_text = render_text(priced)
    unavailable_text = render_text(unavailable)
    assert "Actual trace delta:" not in priced_text
    assert "Actual trace delta:" not in unavailable_text
    assert "Actual cost delta" not in priced_text
    assert "Actual cost delta" not in unavailable_text
    # Priced workflow's Actually paid line carries the parenthetical.
    priced_actually_paid = next(line for line in priced_text.splitlines() if "Actually paid:" in line)
    assert "vs cost without caching" in priced_actually_paid


def test_truncated_trace_attaches_parentheticals_without_executed_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Truncated trace mode: the executed-subset cost lines (with ``(executed)``
    label suffixes) still carry parentheticals on Actually paid + Cost on
    rerun. The legacy ``Actual cost delta (this run, executed):`` /
    ``Rerun delta (executed):`` separate lines do NOT appear — those were
    retired alongside Candidate A.

    The first-run delta still has no rendering surface in trace mode (no
    ``Cost on first run`` cost line in trace mode at all), so we just
    confirm the legacy label doesn't appear.
    """
    from pflow.core.prompt_cache_analysis.analyze import analyze

    analyze_module = sys.modules["pflow.core.prompt_cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-sonnet-4-5")
    workflow_ir = {
        "nodes": [
            {"id": "ran", "type": "llm", "params": {"prompt": "Hello"}},
            {"id": "skipped", "type": "llm", "params": {"prompt": "Skipped"}},
        ]
    }
    analysis = analyze(
        workflow_ir,
        workflow_path="x",
        trace_path=_trace_path(
            tmp_path,
            workflow_path="x",
            nodes=[_llm_event("ran", model="anthropic/claude-sonnet-4-5")],
            name="truncated-priced-trace.json",
            final_status="failed",
        ),
        auto_load_trace=False,
    )

    text = render_text(analysis)
    # Truncated cost label suffix stays — "(executed)" still distinguishes
    # the partial-cohort lines from a complete trace.
    assert "Actually paid (executed trace):" in text
    assert "Cost on rerun (executed, within TTL):" in text
    # Legacy delta-line labels must not appear.
    assert "Actual cost delta" not in text
    assert "Rerun delta" not in text
    assert "First-run delta" not in text


def test_greenfield_attaches_parentheticals_to_cache_cost_lines() -> None:
    """Greenfield mode (no trace data) renders parentheticals on the
    ``Cost on first run (cache)`` and ``Cost on rerun (within TTL)`` cost
    lines instead of separate delta lines. The ``Cost without caching``
    baseline line stays bare — it's the reference against which the others
    compare.
    """
    analysis = _make_analysis(
        no_cache=0.10,
        first_run_with_cache=0.09,
        rerun=0.04,
    )

    text = render_text(analysis)
    # Legacy delta-line labels removed.
    assert "First-run delta:" not in text
    assert "Rerun delta:" not in text
    assert "Actual cost delta" not in text
    # Cost-line labels still here.
    first_run_line = next(line for line in text.splitlines() if "Cost on first run (cache):" in line)
    rerun_line = next(line for line in text.splitlines() if "Cost on rerun (within TTL):" in line)
    no_cache_line = next(line for line in text.splitlines() if "Cost without caching:" in line)
    # Parentheticals attach to first-run and rerun (both have deltas);
    # the baseline stays bare (no self-comparison).
    assert "vs cost without caching" in first_run_line
    assert "vs cost without caching" in rerun_line
    assert "vs cost without caching" not in no_cache_line


def test_actual_savings_falls_back_to_unavailable_when_no_priced_rows_remain(tmp_path: Path) -> None:
    """When every row is excluded from the projection cohort (so
    ``no_cache_hypothetical_usd`` is None / 0), the priced-cohort math has
    no comparison baseline and the delta stays unavailable. Renderer
    surfaces ``unavailable (projection excludes ...)`` so the agent still
    sees what was left out.

    Mutation contract: drop the ``no_cache > 0`` gate in ``analyze.py`` →
    ``_cost_delta`` returns unavailable without a reason → renderer's
    elif branch doesn't fire → the ``Actual cost delta (this run):`` label
    disappears from text → assertion fails.
    """
    from pflow.core.prompt_cache_analysis.analyze import analyze

    workflow_ir = {
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {"model": "${item.model}", "prompt": "${item.prompt}"},
                "batch": {"items": "${items}"},
            }
        ]
    }
    trace_data = {
        "format_version": "2.2.0",
        "workflow_path": "x",
        "final_status": "success",
        "nodes": [
            {
                "node_id": "generate",
                "node_type": "LLMNode",
                "success": True,
                "batch_items": [
                    {
                        "index": 0,
                        "success": True,
                        "llm_call": {
                            "model": "gemini/gemini-2.5-flash",
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "cost_usd": 0.01,
                        },
                    },
                ],
            },
        ],
    }
    analysis = analyze(
        workflow_ir,
        parameters={"items": [{"model": "a", "prompt": "x"}]},
        workflow_path="x",
        trace_path=_write_trace(tmp_path / "all-excluded-trace.json", trace_data),
        auto_load_trace=False,
        memo_cache=None,
    )

    # All rows are heterogeneous-excluded, so no_cache_hypothetical_usd is
    # None (no priced cohort to compare against).
    assert analysis.summary.no_cache_hypothetical_usd is None
    delta = analysis.summary.actual_vs_no_cache_delta
    assert delta.kind == "unavailable"
    assert delta.unavailable_reason == "projection_exclusions"
    assert delta.excluded_nodes == ()  # not populated when fallback fires

    text = render_text(analysis)
    # Candidate A: when the actual delta is unavailable, the parenthetical
    # drops entirely — no dangling "(saves N% vs ...)" on Actually paid,
    # no separate ``Actual cost delta (this run): unavailable`` line.
    # The ``Excluded from analysis`` line in the cost block carries the
    # node + reason context.
    actually_paid_line = next(line for line in text.splitlines() if "Actually paid:" in line)
    assert "(saves" not in actually_paid_line
    assert "(adds" not in actually_paid_line
    assert "unavailable" not in actually_paid_line
    assert "Actual cost delta" not in text
    assert "unavailable (projection excludes" not in text
    # Excluded node + reason render in the cost block.
    assert "Excluded from analysis:" in text
    assert "generate: model varies per call" in text


def test_format_delta_parenthetical_translates_baseline_identifier_to_human_phrase() -> None:
    """Candidate A: the typed ``CostDelta.baseline`` field carries
    ``"no_cache_hypothetical_usd"``; ``_format_delta_parenthetical``
    translates it via ``_BASELINE_LABELS`` to ``"cost without caching"`` so
    the parenthetical reads ``(saves N% vs cost without caching)`` —
    anchored to the ``Cost without caching`` line above it. Unknown
    identifiers fall back to ``baseline`` (won't crash if a future producer
    adds a new value before the map is updated).

    Mutation contract: drop the ``_BASELINE_LABELS`` lookup → ``vs baseline``
    reappears for the known producer value, this test fails on the explicit
    ``not in`` assertion.
    """
    from pflow.core.prompt_cache_analysis.render_text import _format_delta_parenthetical
    from pflow.core.prompt_cache_analysis.types import CostDelta

    savings = CostDelta(
        amount_usd=0.10,
        pct_of_baseline=20,
        kind="savings",
        baseline="no_cache_hypothetical_usd",
        compared_to="actually_paid_usd",
    )
    rendered = _format_delta_parenthetical(savings)
    assert rendered == "(saves 20% vs cost without caching)"
    assert "vs baseline" not in rendered

    # Cost increases route through the same translation, with the ``adds`` verb.
    cost_increase = CostDelta(
        amount_usd=0.05,
        pct_of_baseline=10,
        kind="cost_increase",
        baseline="no_cache_hypothetical_usd",
        compared_to="actually_paid_priced_cohort_usd",
    )
    rendered = _format_delta_parenthetical(cost_increase)
    assert rendered == "(adds 10% vs cost without caching)"

    # Unknown baseline identifiers fall back to "baseline" (defense against
    # future producer adding a new value without updating the map).
    unknown = CostDelta(
        amount_usd=0.10,
        pct_of_baseline=20,
        kind="savings",
        baseline="future_unknown_baseline_usd",
        compared_to="actually_paid_usd",
    )
    rendered = _format_delta_parenthetical(unknown)
    assert rendered == "(saves 20% vs baseline)"


def test_format_delta_parenthetical_drops_dollar_and_excluded_nodes() -> None:
    """Candidate A drops the per-run dollar figure from the parenthetical:
    it's derivable by subtraction from the two cost lines and re-emitting it
    creates a third number that has to stay in sync. ``excluded_nodes`` also
    stays out of the parenthetical — the ``Excluded from analysis`` cost-block
    line establishes the cohort once.

    The ``excluded_nodes`` data field is preserved for JSON consumers
    (``render_json.py``) — only the text parenthetical is minimal.

    Mutation contract: re-add a dollar amount or ``(excludes ...)`` qualifier
    to ``_format_delta_parenthetical`` → these ``not in`` assertions fail.
    """
    from pflow.core.prompt_cache_analysis.render_text import _format_delta_parenthetical
    from pflow.core.prompt_cache_analysis.types import CostDelta

    with_excludes = CostDelta(
        amount_usd=0.49,
        pct_of_baseline=19,
        kind="savings",
        baseline="no_cache_hypothetical_usd",
        compared_to="actually_paid_priced_cohort_usd",
        excluded_nodes=("generate-chorus-options", "score-choruses"),
    )
    rendered = _format_delta_parenthetical(with_excludes)
    assert rendered == "(saves 19% vs cost without caching)"
    assert "$" not in rendered
    assert "excludes" not in rendered


def test_format_delta_parenthetical_unavailable_returns_empty() -> None:
    """``kind == "unavailable"`` returns empty string so the cost line is
    rendered bare (no trailing whitespace, no dangling parenthetical).
    Same for missing ``pct_of_baseline`` — the parenthetical leans on the
    percentage as the load-bearing signal, so without it there's nothing
    useful to render.
    """
    from pflow.core.prompt_cache_analysis.render_text import _format_delta_parenthetical
    from pflow.core.prompt_cache_analysis.types import CostDelta

    unavailable = CostDelta(
        amount_usd=None,
        pct_of_baseline=None,
        kind="unavailable",
        baseline="no_cache_hypothetical_usd",
        compared_to="actually_paid_usd",
        unavailable_reason="no_trace",
    )
    assert _format_delta_parenthetical(unavailable) == ""

    no_pct = CostDelta(
        amount_usd=0.05,
        pct_of_baseline=None,
        kind="savings",
        baseline="no_cache_hypothetical_usd",
        compared_to="actually_paid_usd",
    )
    assert _format_delta_parenthetical(no_pct) == ""


def test_format_delta_parenthetical_break_even_returns_neutral_phrase() -> None:
    """``break_even`` renders ``(no meaningful cost change)`` so an agent
    reading the cost line knows the delta WAS computed (vs. ``unavailable``
    which means we couldn't compute it). Different signal from absent.
    """
    from pflow.core.prompt_cache_analysis.render_text import _format_delta_parenthetical
    from pflow.core.prompt_cache_analysis.types import CostDelta

    break_even = CostDelta(
        amount_usd=0.0,
        pct_of_baseline=0,
        kind="break_even",
        baseline="no_cache_hypothetical_usd",
        compared_to="actually_paid_usd",
    )
    assert _format_delta_parenthetical(break_even) == "(no meaningful cost change)"


def test_format_delta_parenthetical_local_cache_reuse_qualifier() -> None:
    """When the trace recorded local pflow memo reuse, the parenthetical
    suffixes ``, incl. local cache reuse`` so an agent reading the
    "Actually paid" line knows the discount mixes provider prompt caching
    with pflow's local memo cache. Without the qualifier the agent might
    over-attribute savings to provider caching alone.
    """
    from pflow.core.prompt_cache_analysis.render_text import _format_delta_parenthetical
    from pflow.core.prompt_cache_analysis.types import CostDelta

    delta = CostDelta(
        amount_usd=0.1,
        pct_of_baseline=26,
        kind="savings",
        baseline="no_cache_hypothetical_usd",
        compared_to="actually_paid_usd",
    )
    assert _format_delta_parenthetical(delta, local_cache_reuse=False) == ("(saves 26% vs cost without caching)")
    assert _format_delta_parenthetical(delta, local_cache_reuse=True) == (
        "(saves 26% vs cost without caching, incl. local cache reuse)"
    )


def test_baseline_labels_map_covers_every_producer_value() -> None:
    """Every ``CostDelta.baseline`` value emitted by ``analyze.py`` must be
    in ``_BASELINE_LABELS``; otherwise the renderer falls back to the
    uninformative ``"of baseline"`` phrase a future fresh agent can't
    interpret. This test enumerates the production producer surface and
    locks the map in lockstep.

    Today there is exactly ONE producer value
    (``"no_cache_hypothetical_usd"``); if a new value is added without
    updating ``_BASELINE_LABELS``, this test fires.
    """
    from pflow.core.prompt_cache_analysis.render_text import _BASELINE_LABELS

    producer_values = {
        "no_cache_hypothetical_usd",
    }
    missing = producer_values - _BASELINE_LABELS.keys()
    assert not missing, (
        f"Producer adds baseline values without _BASELINE_LABELS entry: {missing}. "
        f"Add to render_text.py::_BASELINE_LABELS so rendered text reads correctly."
    )


def test_fragmentation_grouping_uses_effective_model_in_trace_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pflow.core.prompt_cache_analysis.analyze import analyze

    analyze_module = sys.modules["pflow.core.prompt_cache_analysis.analyze"]
    monkeypatch.setattr(analyze_module, "get_default_workflow_model", lambda: "anthropic/claude-haiku-4-5")
    big_context = "shared context " * 3000
    workflow_ir = {
        "inputs": {"context": {"type": "string"}},
        "cache": {"items": [{"name": "context", "var": "context", "prose_before": "Context:"}]},
        "nodes": [
            {
                "id": "a",
                "type": "llm",
                "prompt_cache": ["context"],
                "params": {"model": "anthropic/claude-haiku-4-5", "prompt": "Use context."},
            },
            {
                "id": "b",
                "type": "llm",
                "prompt_cache": ["context"],
                "params": {"model": "anthropic/claude-haiku-4-5", "prompt": "Use context again."},
            },
        ],
    }
    analysis = analyze(
        workflow_ir,
        parameters={"context": big_context},
        workflow_path="x",
        trace_path=_trace_path(
            tmp_path,
            workflow_path="x",
            nodes=[
                _llm_event("a", model="anthropic/claude-haiku-4-5"),
                _llm_event("b", model="gemini/gemini-2.5-flash"),
            ],
            name="fragmentation-trace.json",
        ),
        auto_load_trace=False,
    )

    assert any(warning.id == "cache.heterogeneous-models-fragment-cache" for warning in analysis.warnings)


def test_text_rows_with_analysis_wide_warning_show_even_above_threshold() -> None:
    """Bug B regression — a row at ≥80% ratio with NO inline warnings but a
    matching ``analysis.warnings`` Diagnostic (the production shape; analytical
    detections emit Diagnostics, not row-inline tuples) must NOT be hidden.

    Mutation test: remove the ``row.node_path in nodes_with_warnings`` clause
    from ``_is_row_visible_by_default``; this test must fail.
    """
    rows = [_row("review", 95)]  # row.warnings = () — empty inline tuple
    diag = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.dynamic-before-static",
        message="x",
        node_id="review",
    )
    text = render_text(_make_analysis(rows=rows, warnings=[diag]))
    assert "review" in text
    assert "Hidden: 1" not in text


def test_text_per_call_inline_marker_includes_analysis_wide_warning_id() -> None:
    """When a row has an analysis-wide warning, render its ID inline next to
    the row (so agents reading the per-call report see WHY the row is shown).

    Stage-1 final UX pass: the ``cache.`` namespace prefix is stripped from
    inline markers since every ID in this column is namespaced ``cache.*``
    — the prefix is 100% redundant in the per-call notes column. Full IDs
    stay in JSON for machine consumers (DD#27).
    """
    rows = [_row("review", 30)]  # already visible due to ratio
    diag = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.dynamic-before-static",
        message="x",
        node_id="review",
    )
    text = render_text(_make_analysis(rows=rows, warnings=[diag]))
    # The warning ID surfaces inline on the row line — without ``cache.`` prefix.
    review_lines = [line for line in text.splitlines() if line.lstrip().startswith("review  ")]
    assert review_lines, "expected a per-call row line for review"
    assert "dynamic-before-static" in review_lines[0]
    # Critical: the redundant ``cache.`` prefix is gone from the inline column.
    assert "cache.dynamic-before-static" not in review_lines[0]


def test_text_hides_single_call_unavailable_rows_by_default() -> None:
    single = PerCallRow(**{
        **_row("evaluate-songs", 0).__dict__,
        "data_source": "trace",
        "cacheable_tokens_estimated": None,
        "cache_ratio_pct": None,
        "cacheable_data_source": "unavailable",
        "observed_call_count": 1,
    })
    repeated = PerCallRow(**{
        **_row("curate-briefs", 0).__dict__,
        "data_source": "trace",
        "cacheable_tokens_estimated": None,
        "cache_ratio_pct": None,
        "cacheable_data_source": "unavailable",
        "observed_call_count": 4,
    })

    text = render_text(_make_analysis(rows=[single, repeated]))

    assert "curate-briefs" in text
    assert "no stable 1,024-token repeated prefix found" in text
    assert "evaluate-songs" not in text
    assert "low-signal rows hidden" in text

    all_rows_text = render_text(_make_analysis(rows=[single, repeated]), all_rows=True)
    assert "evaluate-songs" in all_rows_text
    assert "single call; no repeated cache use observed" in all_rows_text


def test_text_unavailable_row_notes_below_min_cross_workflow_candidate() -> None:
    child_workflow = "/abs/child.pflow.md"
    row = PerCallRow(**{
        **_row("review", 0).__dict__,
        "workflow_path": child_workflow,
        "data_source": "trace",
        "cacheable_tokens_estimated": None,
        "cache_ratio_pct": None,
        "cacheable_data_source": "unavailable",
        "observed_call_count": 4,
    })
    diag = Diagnostic(
        severity=Severity.INFO,
        source="cache_analyzer",
        id="cache.sub-workflow-cache-undeclared",
        message="lyrics is below threshold",
        context={
            "child_workflow": child_workflow,
            "case": "refactor",
            "inputs": [
                {
                    "child_input_name": "lyrics",
                    "tokens_estimated": 474,
                    "consumer_node_ids": ["review"],
                }
            ],
        },
    )

    text = render_text(_make_analysis(rows=[row], warnings=[diag]))

    assert "review" in text
    assert "below cache minimum: lyrics ~474" in text
    # Internal classification taxonomy (`case=...`) does not leak to agent-facing text.
    assert "case=refactor" not in text
    assert "case=model_switch" not in text
    assert "no stable" not in text


@pytest.mark.parametrize(
    "model",
    [
        pytest.param("anthropic/claude-sonnet-4-5", id="model-resolved"),
        pytest.param("", id="model-unresolved"),
    ],
)
def test_text_unavailable_row_notes_static_mode_zero_calls(model: str) -> None:
    """Static-mode rows (no trace, ``observed_call_count == 0``) with an
    unavailable projection had no fallback note before — the row rendered
    ``cached_now: —``, ``could_cache: ?``, ``ratio: ?%``, ``calls: —`` with
    an empty notes column. A fresh agent saw only placeholders with no
    explanation and no next step.

    The new fallback names the cause (``no trace recorded``) and the
    unblocking action (``run with --report``). The note fires regardless
    of whether the model resolved statically — the model column shows
    ``<unresolved>`` or the model name; the action is identical.

    The row passes the visibility filter via ``declared_prompt_cache`` —
    static-mode lyrics-generator rows pass via the same path because
    ``song-creator.pflow.md`` and friends declare cache that hasn't been
    measured yet.

    Mutation contract: remove the ``observed_call_count == 0`` branch from
    ``_unavailable_could_cache_note`` → the note disappears.
    """
    row = PerCallRow(**{
        **_row("write-lyrics", 0).__dict__,
        "model": model,
        "data_source": "estimator",
        "cacheable_tokens_estimated": None,
        "cache_ratio_pct": None,
        "cacheable_data_source": "unavailable",
        "observed_call_count": 0,
        "declared_prompt_cache": ("article",),
    })

    text = render_text(_make_analysis(rows=[row]))

    assert "write-lyrics" in text
    assert "no trace recorded — run with --report to populate this row" in text
    # Existing fallbacks for ``observed_call_count`` of 1 or ≥2 must NOT fire here.
    assert "single call" not in text
    assert "no stable" not in text


def test_text_cost_tier_annotation_renders_plain_english() -> None:
    """``actually_paid_usd``'s tier parenthetical is rendered as plain
    English via ``_TIER_LABELS`` so agents read ``(from trace)`` /
    ``(from partial trace)`` rather than the raw snake_case enum value.

    Mutation contract: revert ``_format_cost`` to pass ``tier_annotation``
    through unchanged → the negative assertion on ``trace_partial`` fires.
    """
    analysis = _make_analysis(
        actually_paid=0.05,
        no_cache=0.10,
        partial=True,
        actually_paid_tier=CostTier.TRACE_PARTIAL,
    )
    text = render_text(analysis)

    assert "(from partial trace)" in text
    # Raw enum value must NOT leak.
    assert "trace_partial" not in text


def test_text_recommended_actions_render_workflow_scope_for_workflow_level_findings() -> None:
    """When a finding has ``node_id is None`` AND ``affected_workflow`` set,
    the renderer surfaces the workflow basename on its scope line so
    workflow-level findings are distinguishable from per-node ones (the GH #2
    surface).

    Stage 0: ``recommended_actions`` is a renderer-derived view; tests build
    warnings via ``make_diagnostic`` and trust the production derivation
    (``view_helpers.build_recommended_actions``) — Pitfall #19 defense.

    Mutation test: comment out the ``elif action.scope_workflow:`` branch in
    ``render_text._render_recommended_actions`` and this test fails — the
    workflow-level finding renders with no scope line, indistinguishable
    from a fully-unscoped finding.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        # Workflow-scope finding (no node_id; affected_workflow is the path).
        make_diagnostic(
            "cache.shared-context-undeclared",
            node_count=2,
            shared_chunks=["concept"],
            affected_workflow="/abs/path/song-creator.pflow.md",
            savings_usd=None,
        ),
        # Per-node finding alongside (existing rendering preserved).
        make_diagnostic(
            "cache.shared-context-undeclared",
            node_id="emotional-reviews",
            node_count=2,
            shared_chunks=["concept"],
            affected_workflow="/abs/path/song-creator.pflow.md",
            savings_usd=None,
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))
    # The headline is the rank-line title.
    assert "Shared context undeclared" in text
    # Workflow-level finding gets the basename on its scope line. Suggestions
    # may include the full path because they are paste-ready edit targets.
    assert "song-creator.pflow.md" in text
    # Per-node finding renders the node_id on its scope line.
    assert "emotional-reviews" in text
    # The bracketed ID prefix is GONE from rank lines — top-10% codebases
    # don't visually code long namespaced descriptors as error codes.
    assert "[cache.shared-context-undeclared]" not in text


def test_text_recommended_actions_per_node_finding_includes_workflow_scope_in_multi_workflow_analysis() -> None:
    """Same-id per-node findings render as ``<node> in <workflow>`` when the
    warning context identifies different workflow files.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        make_diagnostic(
            "cache.below-min-predicted",
            node_id="draft",
            affected_workflow="/abs/workflows/parent.pflow.md",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
            provider_note="",
        ),
        make_diagnostic(
            "cache.below-min-predicted",
            node_id="draft",
            affected_workflow="/abs/workflows/child.pflow.md",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
            provider_note="",
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))
    assert "draft in parent.pflow.md" in text
    assert "draft in child.pflow.md" in text


def test_text_recommended_actions_single_workflow_omits_scope_suffix() -> None:
    """Root-workflow findings keep the old compact ``<node>`` scope line."""
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        make_diagnostic(
            "cache.below-min-predicted",
            node_id="rewrite",
            affected_workflow="/abs/x.pflow.md",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
            provider_note="",
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))
    assert "     rewrite\n" in f"{text}\n"
    assert "rewrite in " not in text


def test_shadow_warning_text_renders_cost_comparison_with_ratio() -> None:
    """The shadow warning's per-call cost evidence still renders as a single
    line (``Removing prompt_cache: ... would drop per-call cost from X to Y``)
    so an agent can see the dollar impact of narrowing or removing the cache
    declaration. The old "The body only references a sub-path..." prose and
    the "compares against inlining the full chunk uncached" footnote were
    removed in Bundle 1 \u2014 they asserted "unused" (unprovable) and conceded
    a "different baseline" framing that F#1 reframing closed out.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    warning = make_diagnostic(
        "cache.prompt-body-shadows-cache",
        node_id="use-tiny-field",
        shadowing_pairs=[{"chunk_name": "bundle", "body_ref": "bundle.tiny_field", "direction": "cache_contains_body"}],
        overlap_lines="  - cached `${bundle}` overlaps inline `${bundle.tiny_field}` (cache_contains_body)",
        affected_workflow="/abs/x.pflow.md",
    )
    warning.context["body_only_cost_usd_per_call"] = 3.1e-6
    warning.context["with_cache_cost_usd_per_call"] = 4.96e-4
    warning.context["shadowed_chunk_names"] = ("bundle",)

    text = render_text(_make_analysis(warnings=[warning]))

    assert "Removing `prompt_cache:` for `bundle` from `use-tiny-field` would drop per-call cost" in text
    assert "160\u00d7 more expensive" in text
    # Bundle 1 negative assertions: the old "unused" and "different baseline"
    # phrases were removed. Mutation contract: restoring either string to
    # ``_format_shadow_cache_cost_comparison`` \u2192 these assertions fail.
    assert "unused by your prompt" not in text
    assert "different baseline than your body" not in text
    assert "compares against inlining the full chunk uncached" not in text


def test_json_recommended_actions_per_node_finding_carries_scope_workflow() -> None:
    """JSON keeps both the symbol and its workflow location for consumers that
    dispatch on same-id nodes across parent/child workflows.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        make_diagnostic(
            "cache.below-min-predicted",
            node_id="draft",
            affected_workflow="/abs/workflows/parent.pflow.md",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
            provider_note="",
        ),
        make_diagnostic(
            "cache.below-min-predicted",
            node_id="draft",
            affected_workflow="/abs/workflows/child.pflow.md",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
            provider_note="",
        ),
    ]
    result = render_json(_make_analysis(warnings=warnings))
    action_scopes = {
        (action["node_id"], action["scope_workflow"])
        for action in result["recommended_actions"]
        if action["warning_id"] == "cache.below-min-predicted"
    }
    assert ("draft", "/abs/workflows/parent.pflow.md") in action_scopes
    assert ("draft", "/abs/workflows/child.pflow.md") in action_scopes


def test_json_blocking_errors_array_present_and_excludes_warnings() -> None:
    warnings = [
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            id="cache.order-mismatch",
            node_id="test-call",
            message="Order mismatch",
        ),
        Diagnostic(
            severity=Severity.WARNING,
            source="cache_analyzer",
            id="cache.below-min-predicted",
            node_id="test-call",
            message="Below minimum",
        ),
    ]
    result = render_json(_make_analysis(warnings=warnings))
    assert [a["warning_id"] for a in result["blocking_errors"]] == ["cache.order-mismatch"]
    assert [a["rank"] for a in result["blocking_errors"]] == [1]


def test_json_blocking_errors_preserve_message_and_suggestions() -> None:
    """Cache-domain ERRORs preserve message + suggestions in JSON output."""
    warnings = [
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            id="llm.thinking-temperature-mismatch",
            node_id="deep-think",
            message="Unknown parameter 'thinking_effort' on node 'deep-think' (type: llm).",
            suggestions=["Did you mean 'reasoning_effort'?"],
        ),
    ]
    result = render_json(_make_analysis(warnings=warnings))
    assert result["blocking_errors"][0]["message"] == warnings[0].message
    assert result["blocking_errors"][0]["suggestions"] == ["Did you mean 'reasoning_effort'?"]


def test_json_other_blocking_errors_preserve_message_and_suggestions() -> None:
    """Non-cache ERRORs preserve message + suggestions in
    ``other_blocking_errors[]`` (B-9 split parity for the new array).

    Mutation contract: stop projecting suggestions in ``_action_to_dict`` —
    this test fails because ``suggestions`` becomes empty.
    """
    warnings = [
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            id=None,
            node_id="deep-think",
            message="Unknown parameter 'thinking_effort' on node 'deep-think' (type: llm).",
            suggestions=["Did you mean 'reasoning_effort'?"],
        ),
    ]
    result = render_json(_make_analysis(warnings=warnings))
    assert result["blocking_errors"] == []
    assert result["other_blocking_errors"][0]["message"] == warnings[0].message
    assert result["other_blocking_errors"][0]["suggestions"] == ["Did you mean 'reasoning_effort'?"]


def test_json_recommended_actions_excludes_errors_after_split() -> None:
    warnings = [
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            id="cache.order-mismatch",
            node_id="test-call",
            message="Order mismatch",
        ),
        Diagnostic(
            severity=Severity.INFO,
            source="cache_analyzer",
            id="cache.first-call-write-penalty",
            node_id="test-call",
            message="Single-call penalty",
        ),
    ]
    result = render_json(_make_analysis(warnings=warnings))
    assert [a["warning_id"] for a in result["recommended_actions"]] == ["cache.first-call-write-penalty"]
    assert [a["rank"] for a in result["recommended_actions"]] == [1]


def test_text_blocking_errors_render_suggestions() -> None:
    warnings = [
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            node_id="deep-think",
            message="Unknown parameter 'thinking_effort' on node 'deep-think' (type: llm).",
            suggestions=["Did you mean 'reasoning_effort'?"],
        ),
    ]
    rendered = render_text(_make_analysis(warnings=warnings))
    assert "Did you mean 'reasoning_effort'?" in rendered


def test_text_recommended_actions_inline_label_passes_through() -> None:
    """Non-path scope identifiers (``<inline>``, ``ir-hash:abc123``) pass through
    unchanged — they're not filesystem paths, so basename extraction shouldn't
    chop a meaningful prefix off them.

    Stage-1 final UX pass: the ``Workflow:`` prefix label was dropped — the
    scope-line basename/identifier alone is the discriminator. The
    load-bearing contract is that ``<inline>`` survives intact (no
    accidental basename chopping).
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        make_diagnostic(
            "cache.shared-context-undeclared",
            node_count=2,
            shared_chunks=["concept"],
            affected_workflow="<inline>",
            savings_usd=None,
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))
    # ``<inline>`` survives intact on its scope line — no basename chopping.
    assert "<inline>" in text


def test_text_recommended_actions_unscoped_finding_omits_scope_line() -> None:
    """When neither node_id nor affected_workflow is set (defensive fallback),
    the renderer omits the scope line entirely rather than showing an empty
    line.

    Stage 0: this test uses raw ``Diagnostic(...)`` (not ``make_diagnostic``)
    because the catalog REQUIRES ``affected_workflow`` for
    ``cache.shared-context-undeclared``. The defensive fallback path
    represents a non-catalog diagnostic that flows through the renderer; the
    contract is "no spurious blank scope line for fully-unscoped findings."
    """
    from pflow.core.diagnostic import Diagnostic, Severity

    headline = "Shared context undeclared — declare `concept` in ## Cache"
    warnings = [
        Diagnostic(
            severity=Severity.INFO,
            source="cache_analyzer",
            id="cache.shared-context-undeclared",
            node_id=None,
            message="Used by 2 LLM nodes. Chunks: concept.",
            context={"shared_chunks": ["concept"], "category": "cache_advisory"},
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))
    # Headline renders as the rank line (catalog-derived via resolve_headline_for).
    assert headline in text
    # The bracketed ID prefix is GONE (Stage-1 UX pass).
    assert "[cache.shared-context-undeclared]" not in text
    # Locate the rank line, then verify nothing follows it that looks like a
    # scope line (i.e. no indented content immediately under the headline).
    lines = text.splitlines()
    rank_line_idx = next(i for i, line in enumerate(lines) if headline in line)
    # Whatever is on the next non-empty line should NOT be a stray scope line
    # belonging to this action — the message indents under the rank line as
    # the "reason paragraph", but there should be no scope-line ALONE between
    # the rank line and the message. Verify by checking the immediate next
    # line: it should be the message indent (5 spaces + "Used by..."), not
    # a bare path/node_id scope line.
    next_line = lines[rank_line_idx + 1] if rank_line_idx + 1 < len(lines) else ""
    # The reason paragraph IS rendered (message != headline), but there should
    # be NO scope line preceding it. The reason starts with "Used by".
    assert next_line.strip().startswith("Used by") or next_line.strip() == "", (
        f"Expected message line or blank after unscoped rank entry; got: {next_line!r}"
    )


def test_text_recommended_actions_render_savings_with_adaptive_precision() -> None:
    """Sub-cent UX gap fix — savings tri-state with adaptive precision.

    Pre-fix sub-cent values (< $0.005) collapsed to "savings unavailable",
    which on Gemini-shaped workflows hid every real recommendation behind
    the placeholder. Post-fix uses 4-decimal precision for sub-cent so
    agents see the actual magnitude in text mode (matches JSON contract).

    The Bug D regression invariant — "no -$0.00/run anywhere" — is still
    enforced (the < $0.0001 cutoff drops the figure for truly negligible
    values; 4-decimal rendering covers the $0.0001-$0.01 range).

    Stage-1 final UX pass: the ``[cache.X]`` bracket prefix is gone from
    rank lines.

    Stage 0: warnings are built via ``make_diagnostic``; ``recommended_actions``
    is renderer-derived via ``view_helpers.build_recommended_actions``.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        # Sub-cent savings (0.0012) — renders with 4-decimal precision.
        make_diagnostic(
            "cache.shared-context-undeclared",
            node_count=2,
            shared_chunks=["concept"],
            affected_workflow="/abs/wf.pflow.md",
            savings_usd=0.0012,
        ),
        # None savings — renders as "savings unavailable" (genuinely unknown).
        make_diagnostic(
            "cache.dynamic-before-static",
            node_id="x",
            affected_workflow="/abs/wf.pflow.md",
            dynamic_ref="ref",
            dynamic_line=3,
            cacheable_tokens=1000,
            affected_calls=10,
            projected_ratio_pct=85,
            savings_usd=None,
        ),
        # Below-display ($0.00005) — renders as "savings unavailable".
        make_diagnostic(
            "cache.padding-advisory",
            node_id="z",
            affected_workflow="/abs/wf.pflow.md",
            current_subset=["concept"],
            suggested_subset=["concept", "concept_brief"],
            savings_usd=0.00005,
        ),
        # Above-threshold ($0.42) — renders with 2-decimal precision.
        make_diagnostic(
            "cache.batch-prewarm-recommended",
            node_id="y",
            affected_workflow="/abs/wf.pflow.md",
            batch_size=8,
            prefix_tokens_estimated=2000,
            savings_pct=89,
            savings_usd=0.42,
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))

    # Sub-cent ($0.0012) renders with 4-decimal precision.
    assert "saves ~$0.0012/run" in text, f"expected sub-cent savings to render as savings text; text:\n{text}"
    assert "-$0.0012/run" not in text
    # None and below-display ($0.00005) both render as "savings unavailable".
    savings_unavailable_count = text.count("savings unavailable")
    assert savings_unavailable_count >= 2, (
        f"expected ≥2 'savings unavailable' (None + below-display); got {savings_unavailable_count}"
    )
    # Batch prewarm renders the per-run dollar tag with the same `/run` unit
    # the rest of the analyzer uses; the `/workflow run` qualifier was retired
    # because both branches express savings per pflow run and the divergent
    # label read as inconsistent. The aggregate-batch nuance lives in the
    # action body ("projected savings are aggregate for the batch, not per
    # item.") so the headline doesn't need to encode it.
    assert "saves ~$0.42/run" in text
    assert "saves ~$0.42/workflow run" not in text
    assert "-$0.42/run" not in text
    # Bug D regression: NO "-$0.00/run" placeholder anywhere. (Note: a broad
    # "$0.00" check would false-trigger on "$0.0012" — match the precise
    # placeholder string instead.)
    assert "-$0.00/run" not in text
    # Stage-1 UX pass: the ``[cache.X]`` bracket prefix is gone from rank lines.
    assert "[cache.shared-context-undeclared]" not in text
    assert "[cache.dynamic-before-static]" not in text
    assert "[cache.batch-prewarm-recommended]" not in text


def test_batch_prewarm_recommended_discloses_wall_clock_tradeoff() -> None:
    """Bug 17: the prewarm recommendation surfaces the cost/latency trade-off
    so agents can make an informed decision.

    Pre-fix output framed ``prewarm: true`` as pure upside (``saves ~$X/run``)
    with no mention of the synthetic warmup call overhead. For
    latency-sensitive workflows this could make the recommendation a net loss.

    A provider-specific Gemini implicit-cache caveat was considered and
    rejected: it would need per-row model dispatch to apply cleanly, and
    the "measure end-to-end duration" guidance already covers the same
    reasoning agents would do on Gemini.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.batch-prewarm-recommended",
        node_id="score",
        affected_workflow="/abs/wf.pflow.md",
        batch_size=8,
        prefix_tokens_estimated=2000,
        savings_pct=89,
        savings_usd=0.42,
    )

    text = render_text(_make_analysis(warnings=[diag]))

    # Positive: savings still rendered (Bug 17 doesn't suppress savings, just
    # contextualizes them).
    assert "saves ~$0.42/run" in text
    # Positive: synthetic warmup trade-off is surfaced with the actionable hint.
    assert "synthetic" in text
    assert "Measure end-to-end duration" in text
    # Positive: the framing names this as a trade-off, not pure upside.
    assert "Trade-off" in text
    # Negative regression: the provider-specific implicit-cache caveat is
    # NOT rendered. It used to fire unconditionally for every batch node;
    # an agent reading it for an Anthropic workflow would treat the
    # ``On Gemini, ...`` prefix as noise. Re-introducing the caveat
    # requires per-row model dispatch, not a static suggestion bullet.
    assert "implicit cache" not in text
    assert "cache_read_input_tokens" not in text


def test_batch_prewarm_lower_bound_renders_at_least_savings_and_verification() -> None:
    """Lower-bound recommendations must not look like confident savings.

    Mutation contract: route the diagnostic through the default savings
    formatter; this test fails because the text says ``saves`` or
    ``savings unavailable`` instead of the lower-bound wording.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    priced = make_diagnostic(
        "cache.batch-prewarm-lower-bound-recommended",
        node_id="score",
        affected_workflow="/abs/wf.pflow.md",
        measurable_tokens=1200,
        batch_alias="item",
        unresolved_refs=("concept.core_idea",),
        savings_lower_bound_usd=0.012,
        batch_size=8,
    )
    unpriced = make_diagnostic(
        "cache.batch-prewarm-lower-bound-recommended",
        node_id="review",
        affected_workflow="/abs/wf.pflow.md",
        measurable_tokens=1300,
        batch_alias="item",
        unresolved_refs=("concept.genre",),
        savings_lower_bound_usd=None,
        batch_size=8,
    )

    text = render_text(_make_analysis(warnings=[priced, unpriced]))

    assert "savings at least ~$0.01/run" in text
    assert "savings need verification" in text
    assert "Run once with `--report`" in text
    assert "Unresolved refs (concept.core_idea)" in text
    assert "saves ~$0.01/run" not in text


def test_batch_prewarm_below_min_renders_prewarm_remediation_not_declared_cache() -> None:
    """The new ``cache.batch-prewarm-below-min`` ID must render the
    prewarm-specific remediation path (restructure the prompt, OR remove
    ``- prewarm: true``) — NOT the declared-cache remediation path
    (``Increase cache content`` / ``remove prompt_cache:``).

    Agents reading this ID have NO ``prompt_cache:`` declaration to remove,
    so leaking declared-cache vocabulary would mislead.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.batch-prewarm-below-min",
        node_id="score-choruses",
        affected_workflow="/abs/wf.pflow.md",
        model="anthropic/claude-sonnet-4-5",
        prefix_tokens=27,
        min_tokens=1024,
        batch_alias="item",
        provider_note="cache_control markers will silently no-op at the provider",
    )

    text = render_text(_make_analysis(warnings=[diag]))

    # Headline + message render with the prewarm boundary vocabulary.
    assert "Batch prewarm prefix below provider minimum" in text
    assert "static prefix" in text
    assert "${item.X}" in text
    assert "1024" in text
    # Provider note flows through.
    assert "cache_control markers" in text
    # Suggestions name the three prewarm remediation paths (grow / remove /
    # switch model — model-switch bullet added in F#4 follow-ups-2).
    assert "Grow the static prefix" in text
    assert "remove `- prewarm: true`" in text
    assert "switch `- model:`" in text
    assert "anthropic/claude-sonnet-4-5" in text
    # Negative regression: lock declared-cache vocabulary OUT of this code path.
    # The agent has no ``prompt_cache:`` to remove; mentioning it would
    # mislead about the remediation.
    assert "Increase cache content" not in text
    assert "remove `prompt_cache:`" not in text


# ---------------------------------------------------------------------------
# Text renderer — notes
# ---------------------------------------------------------------------------


def test_text_renders_notes_in_locked_order() -> None:
    notes = [
        "Found 2 2.0.0 traces matching this workflow but skipped...",
        "Found 1 unparseable trace files in ~/.pflow/debug/...",
        "Gemini caching: ...",
    ]
    text = render_text(_make_analysis(notes=notes))
    # Each note appears in order in the text output.
    pos_2_0 = text.find("2.0.0 traces")
    pos_unparseable = text.find("unparseable")
    pos_gemini = text.find("Gemini caching")
    assert pos_2_0 < pos_unparseable < pos_gemini


def test_text_notes_shorten_workflow_paths_in_prose() -> None:
    workflow_path = "/abs/project/workflows/root.pflow.md"
    child_path = "/abs/project/workflows/sub/child.pflow.md"
    notes = [
        f"Cache fidelity check skipped for {child_path}.draft: a template reference couldn't be resolved at analysis time. Chunk-skip detection still applies."
    ]
    row = PerCallRow(**{**_row("draft", 30).__dict__, "workflow_path": child_path})
    text = render_text(_make_analysis(rows=[row], workflow_path=workflow_path, notes=notes))

    assert "child.pflow.md.draft" in text
    assert child_path not in text


# ---------------------------------------------------------------------------
# CP2 (#11) — Cross-workflow rendering surfaces node_id + chunks
# ---------------------------------------------------------------------------


def _make_sub_workflow_cache_diag(
    node_id: str,
    child_input_name: str,
    child_workflow: str = "/abs/child.pflow.md",
) -> Diagnostic:
    """Build the child-scoped sub-workflow cache diagnostic."""
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    child_basename = child_workflow.rsplit("/", 1)[-1] if "/" in child_workflow else child_workflow
    return make_diagnostic(
        "cache.sub-workflow-cache-undeclared",
        affected_workflow=child_workflow,
        savings_usd=None,
        child_workflow=child_workflow,
        child_workflow_basename=child_basename,
        affected_input_count=1,
        inputs=[
            {
                "child_input_name": child_input_name,
                "parent_value_expr": child_input_name,
                "parent_workflow": "/abs/parent.pflow.md",
                "parent_node_id": node_id,
                "line_in_parent": 0,
                "tokens_estimated": 2048,
                "consumer_node_ids": ["child-llm-a", "child-llm-b"],
                "consumer_node_ids_csv": "`child-llm-a`, `child-llm-b`",
            }
        ],
        body_block=(
            f"Template variables to remove:\n"
            f"  • `{child_input_name}` ~2,048 tokens — node(s) `child-llm-a`, "
            f"`child-llm-b` use `${{{child_input_name}}}`"
        ),
        case="actionable",
    )


def test_text_recommended_action_suggestion_uses_relative_child_edit_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_path = tmp_path / "lyrics-generator.pflow.md"
    child_path = tmp_path / "song-creator" / "chorus-chooser" / "chorus-chooser.pflow.md"
    child_path.parent.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    text = render_text(
        _make_analysis(
            rows=[_row("draft", 30)],
            workflow_path=str(root_path),
            warnings=[_make_sub_workflow_cache_diag("choose-chorus", "concept", str(child_path))],
        )
    )

    assert "→ Edit: song-creator/chorus-chooser/chorus-chooser.pflow.md" in text
    assert str(child_path) not in text


def test_text_edit_target_anchors_at_cwd_not_at_workflow_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit-target paths render relative to the invocation cwd, not relative
    to the analyzed workflow's directory. The agent's cwd is the only frame
    they can navigate paths from — anchoring at the workflow's directory
    produced strings that were invalid from the agent's actual cwd.

    Fixture diverges the two anchors: cwd is ``tmp_path`` and the analyzed
    workflow lives at ``tmp_path/deep/sub/lyrics-generator.pflow.md``. The
    workflow-dir anchor would produce ``song-creator/chorus-chooser/...``;
    the cwd anchor produces ``deep/sub/song-creator/chorus-chooser/...``.

    Mutation contract: revert ``_display_edit_target`` to the workflow-dir
    primary anchor; the assertion on the cwd-relative path fails because
    the shorter workflow-dir-relative form re-appears instead.
    """
    monkeypatch.chdir(tmp_path)
    root_path = tmp_path / "deep" / "sub" / "lyrics-generator.pflow.md"
    child_path = tmp_path / "deep" / "sub" / "song-creator" / "chorus-chooser" / "chorus-chooser.pflow.md"
    child_path.parent.mkdir(parents=True)
    root_path.parent.mkdir(parents=True, exist_ok=True)

    text = render_text(
        _make_analysis(
            rows=[_row("draft", 30)],
            workflow_path=str(root_path),
            warnings=[_make_sub_workflow_cache_diag("choose-chorus", "concept", str(child_path))],
        )
    )

    assert "→ Edit: deep/sub/song-creator/chorus-chooser/chorus-chooser.pflow.md" in text
    assert "→ Edit: song-creator/chorus-chooser/chorus-chooser.pflow.md" not in text


def test_text_cross_workflow_section_uses_sub_workflow_boundaries_header() -> None:
    """CP5 #3 — section renamed from 'Cross-workflow alignment (Tier 2)' to
    'Sub-workflow boundaries' so agents don't have to know what 'Tier 2' is.

    Cross-workflow section text now renders prose-mismatch findings only;
    value-flow surfaces in Recommended actions and rename diagnostics stay
    JSON-only.

    Mutation test: revert the header in ``_render_cross_workflow``; this test
    fails because the agent-facing section name regresses to internal pflow
    architecture jargon.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.cross-workflow-prose-mismatch",
        node_id=None,
        parent_workflow="/abs/song-creator.pflow.md",
        child_workflow="/abs/chorus-chooser.pflow.md",
        chunk_name="concept",
        parent_prose="Parent prose",
        child_prose="Different prose",
    )
    text = render_text(_make_analysis(warnings=[diag]))
    assert "## Sub-workflow boundaries" in text
    assert "Cross-workflow alignment" not in text
    assert "Tier 2" not in text


def test_text_sub_workflow_cache_findings_are_distinguishable() -> None:
    """Child-scoped cache findings name both the child workflow and input."""
    diag1 = _make_sub_workflow_cache_diag("choose-chorus", "concept", child_workflow="/abs/chorus-chooser.pflow.md")
    diag2 = _make_sub_workflow_cache_diag(
        "emotional-reviews",
        "concept_brief",
        child_workflow="/abs/review-emotional.pflow.md",
    )
    diag3 = _make_sub_workflow_cache_diag(
        "craft-reviews",
        "concept_other",
        child_workflow="/abs/review-craft.pflow.md",
    )

    text = render_text(_make_analysis(warnings=[diag1, diag2, diag3]))

    # Three distinct rec entries appear (rank 1/2/3).
    assert "1. " in text
    assert "2. " in text
    assert "3. " in text
    # Each child input appears as a discriminator in the rendered output.
    assert "`concept`" in text
    assert "`concept_brief`" in text
    assert "`concept_other`" in text
    assert "chorus-chooser.pflow.md" in text
    assert "review-emotional.pflow.md" in text
    assert "review-craft.pflow.md" in text


def test_text_sub_workflow_cache_finding_emits_child_action_line() -> None:
    """Sub-workflow cache findings render as child-scoped Recommended actions."""
    diag = _make_sub_workflow_cache_diag("choose-chorus", "concept")
    text = render_text(_make_analysis(warnings=[diag]))
    # Headline surfaces in Recommended actions section.
    assert "Sub-workflow cache undeclared" in text
    assert "`concept`" in text
    assert "apply ALL THREE edits" in text
    assert "Remove the `${var}` references" in text
    assert "either workflow's ## Cache" not in text
    assert "share cached bytes across the boundary" not in text
    # Stage-1 UX pass: per-finding ``[cache.X]`` footer is gone.
    assert "[cache.sub-workflow-cache-undeclared]" not in text


def test_indent_message_preserves_blank_lines() -> None:
    """`_indent_message` must keep blank lines from the source message verbatim.

    Several diagnostic message templates (notably
    ``cache.prompt-cache-incomplete`` and the paste-ready ``## Cache`` block
    rendered by ``cache.sub-workflow-cache-undeclared``) embed ``\\n\\n`` to
    visually separate sections. If the renderer silently filters those out,
    the catalog author's intent never reaches the agent.

    Mutation contract: re-introduce ``if line.strip()`` in
    ``_indent_message`` and the blank-indented row between the prose lines
    disappears, this assertion fails.
    """
    from pflow.core.prompt_cache_analysis.render_text import _indent_message

    rendered = _indent_message("alpha\n\nbeta", prefix=">>>")

    assert rendered == [">>>alpha", ">>>", ">>>beta"]


def test_text_sub_workflow_boundaries_omits_rename_diagnostics() -> None:
    """Rename diagnostics remain in the analysis data but are text-silent."""
    rename = _rename_diag(
        source="concept_brief",
        target="creative_brief",
        parent="/abs/song-creator.pflow.md",
        child="/abs/chorus-chooser.pflow.md",
        line=42,
    )
    prose = _prose_mismatch_diag(
        parent="/abs/song-creator.pflow.md",
        child="/abs/review-rhyme.pflow.md",
        chunk="concept",
    )
    analysis = _make_analysis(warnings=[rename, prose])
    text = render_text(analysis)

    assert any(d.id == "cache.cross-workflow-rename-detected" for d in analysis.warnings)
    assert "## Sub-workflow boundaries (1)" in text
    assert "review-rhyme, chunk `concept`:" in text
    assert "concept_brief" not in text
    assert "creative_brief" not in text
    assert "chorus-chooser" not in text
    assert "line 42" not in text


def test_text_sub_workflow_boundaries_section_omitted_when_only_renames_present() -> None:
    """JSON-only rename diagnostics must not create an empty text section."""
    rename = _rename_diag(
        source="concept_brief",
        target="creative_brief",
        parent="/abs/song-creator.pflow.md",
        child="/abs/chorus-chooser.pflow.md",
        line=42,
    )

    text = render_text(_make_analysis(warnings=[rename]))

    assert "## Sub-workflow boundaries" not in text
    assert "concept_brief" not in text
    assert "creative_brief" not in text
    assert "chorus-chooser" not in text


def test_text_sub_workflow_boundaries_renders_prose_mismatches_only() -> None:
    """Mixed rename/prose input renders only the cache-fidelity finding."""
    rename = _rename_diag(
        source="lyrics",
        target="song_lyrics",
        parent="/abs/song-creator.pflow.md",
        child="/abs/review-rhyme.pflow.md",
        line=239,
    )
    prose = _prose_mismatch_diag(
        parent="/abs/song-creator.pflow.md",
        child="/abs/review-rhyme.pflow.md",
        chunk="lyrics",
    )

    text = render_text(_make_analysis(warnings=[rename, prose]))

    assert "## Sub-workflow boundaries (1)" in text
    assert "Prose mismatches in song-creator:" in text
    assert "review-rhyme, chunk `lyrics`:" in text
    assert "song_lyrics" not in text
    assert "line 239" not in text


def test_text_cross_workflow_prose_mismatch_finding_full_format() -> None:
    """Prose-mismatches render in their own parent-grouped sub-section after
    the rename block (different schema — keyed by ``chunk_name``, no line).

    Layout: ``Prose mismatches in <parent>:`` header + per-finding entry with
    child basename + chunk name + the two prose values labeled.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.cross-workflow-prose-mismatch",
        node_id=None,
        parent_workflow="/abs/song-creator.pflow.md",
        child_workflow="/abs/chorus-chooser.pflow.md",
        chunk_name="concept",
        parent_prose="Parent prose",
        child_prose="Different prose",
    )
    text = render_text(_make_analysis(warnings=[diag]))
    # Sub-section header anchors the prose-mismatches under their parent.
    assert "Prose mismatches in song-creator:" in text
    # Entry shows child + chunk + both prose values labeled.
    assert "chorus-chooser, chunk `concept`:" in text
    assert 'parent prose: "Parent prose"' in text
    assert 'child prose:  "Different prose"' in text
    # The bracketed catalog ID is not exposed.
    assert "[cache.cross-workflow-prose-mismatch]" not in text


# ---------------------------------------------------------------------------
# CP5 Pass 3 — per-node .pflow.md syntax + header phrasing (#4, #6)
# ---------------------------------------------------------------------------


def test_text_per_node_assignments_render_as_pflow_md_syntax() -> None:
    """CP5 #4 — per-node section shows ``- prompt_cache: [a, b, c]`` syntax,
    NOT Python repr ``['a', 'b']``. The agent can copy-paste the exact lines
    they need to add to their workflow file.

    Mutation test: revert ``_render_suggested_blocks`` to the prior format
    (``f"    {node_id}: {assignment}"``); this test fails because Python
    repr brackets/quotes return.
    """
    from pflow.core.prompt_cache_analysis.types import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(
            SuggestedBlockChunk(
                name="concept", var="${concept}", size_tokens_est=500, prose_placeholder="<DESCRIBE concept>"
            ),
            SuggestedBlockChunk(
                name="brief", var="${brief}", size_tokens_est=300, prose_placeholder="<DESCRIBE brief>"
            ),
        ),
        per_node_assignments={
            "write-lyrics": ["concept", "brief"],
        },
        estimated_savings_usd=None,
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})
    text = render_text(analysis)

    # Actual .pflow.md syntax — agent copy-pastes this directly.
    assert "### write-lyrics" in text
    assert "- prompt_cache: [concept, brief]" in text
    # The Python repr shape is GONE — no quotes around chunk names.
    assert "['concept', 'brief']" not in text
    assert "write-lyrics: ['concept'" not in text


def test_text_per_node_assignments_include_order_warning() -> None:
    """CP5 #4 — per-node section includes a brief explainer about the strict
    order requirement. Without this, agents pasting the lines might reorder
    them and trip cache.order-mismatch ERROR.

    Mutation test: drop the explainer block from ``_render_suggested_blocks``;
    this test fails because the order-warning text disappears.
    """
    from pflow.core.prompt_cache_analysis.types import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(SuggestedBlockChunk(name="x", var="${x}", size_tokens_est=100, prose_placeholder="<x>"),),
        per_node_assignments={"node1": ["x"]},
        estimated_savings_usd=None,
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})
    text = render_text(analysis)
    # Order-warning explainer present.
    assert "Order MUST match" in text
    assert "cache.order-mismatch" in text


def test_text_header_lists_models_when_one_resolved() -> None:
    """CP5 #6 — when 1 model is in use, header reads
    ``"7 LLM nodes using anthropic/claude-sonnet-4-5"``.

    Mutation test: revert to ``"X LLM calls · Y models in use"``; this test
    fails because models_in_use[0] doesn't surface.
    """
    rows = [_row("n1", 50)]  # has model="anthropic/claude-sonnet-4-5" via _row
    text = render_text(_make_analysis(rows=rows))
    assert "1 LLM node using anthropic/claude-sonnet-4-5" in text


def test_text_header_lists_models_when_two_resolved() -> None:
    """Cluster D N-3 — 2+ models break out to a dedicated ``Models:`` header
    line. The scale line carries node count + invocation status only; the
    "using N models:" inline form is gone. Single source of truth for the
    model list in the header.

    Mutation contract: revert ``_format_scale_line`` to inline "using N
    models:" form — this test fails because "Models: " line is missing
    AND model names appear on the scale line.
    """
    row_a = PerCallRow(**{**_row("a", 50).__dict__, "model": "anthropic/claude-sonnet-4-5"})
    row_b = PerCallRow(**{**_row("b", 50).__dict__, "model": "gemini/gemini-3.1-pro-preview"})
    text = render_text(_make_analysis(rows=[row_a, row_b]))
    # Positive — models break out to their own line.
    assert "  Models: anthropic/claude-sonnet-4-5, gemini/gemini-3.1-pro-preview" in text
    # Negative — the old inline "using N models:" form must NOT appear.
    assert "using 2 models:" not in text
    # Defense — the scale line itself doesn't carry model names.
    scale_line = next(line for line in text.splitlines() if line.startswith("  Workflow:"))
    assert "anthropic/" not in scale_line
    assert "gemini/" not in scale_line


def test_text_header_drops_observed_models_line_when_trace_loaded() -> None:
    """Cluster D N-2 — the standalone ``Observed models:`` header line is
    dropped. ``models_in_use`` (rendered on the scale or ``Models:`` line)
    is a superset of ``observed_models_in_trace`` in complete trace mode,
    so the second line was a strict duplicate.

    Mutation contract: re-add ``lines.append(f"  Observed models: ...")``
    in ``_render_header``; this test fails because the line reappears.
    """
    base = _make_analysis(
        rows=[_row("n1", 50)],  # model=anthropic/claude-sonnet-4-5 via _row
        actually_paid=0.10,
    )
    # Override observed_models_in_trace to simulate trace-mode population
    # (the synthetic builder defaults this field to () per Pitfall #19).
    summary_with_observed = dataclasses.replace(
        base.summary,
        observed_models_in_trace=("anthropic/claude-sonnet-4-5",),
    )
    analysis = dataclasses.replace(base, summary=summary_with_observed)
    text = render_text(analysis)
    # Negative — the standalone "Observed models:" line must NOT appear.
    assert "Observed models:" not in text
    # Positive — the model still surfaces via the scale line.
    assert "anthropic/claude-sonnet-4-5" in text


def test_text_header_shows_static_batch_invocations() -> None:
    row = PerCallRow(**{**_row("batch-review", 50).__dict__, "is_batch": True, "batch_size_estimated": 8})
    text = render_text(_make_analysis(rows=[row]))
    assert "1 LLM node, ~8 invocations using anthropic/claude-sonnet-4-5" in text


def test_text_header_shows_dynamic_batch_invocation_unknown() -> None:
    row = PerCallRow(**{**_row("batch-review", 50).__dict__, "is_batch": True, "batch_size_estimated": None})
    text = render_text(_make_analysis(rows=[row]))
    assert ("1 LLM node, invocation count unavailable (1 dynamic batch node) using anthropic/claude-sonnet-4-5") in text


def test_text_header_handles_no_model_resolved() -> None:
    """When LLM nodes exist but no model resolves, the header promotes the
    actionable hint to its own ``Models:`` line — symmetric with the
    multi-model case (which also breaks out to ``Models: A, B, C``).

    Mutation test: drop the ``elif not s.models_in_use and ...`` branch from
    ``_format_scale_line``; this test fails because the ``Models: not
    resolved`` line doesn't appear.
    """
    row = PerCallRow(**{**_row("n1", 50).__dict__, "model": ""})
    text = render_text(_make_analysis(rows=[row]))
    # Primary line is bare (no inline parenthetical).
    assert "Workflow: 1 LLM node\n" in text
    # The actionable hint lives on its own ``Models:`` line.
    assert "Models: not resolved (set settings.default_model)" in text
    # Old shape (parenthetical glommed onto the count line) must not return.
    assert "1 LLM node (no model resolved" not in text


def test_per_call_row_renders_unresolved_when_model_empty() -> None:
    """When a per-call row's model can't be resolved (empty string from the
    analyzer), the renderer surfaces ``model=<unresolved>`` instead of an
    empty value with padding. Mirrors the header's "no model resolved"
    vocabulary so agents see the same signal at both layers.

    Mutation test: revert the empty-string branch in ``_format_per_call_row``
    (drop the ``<unresolved>`` else-clause); this test fails because the
    row renders ``model=`` followed by 35 chars of whitespace instead.
    """
    row = PerCallRow(**{**_row("n1", 50).__dict__, "model": ""})
    text = render_text(_make_analysis(rows=[row]))
    cells = _per_call_cells(text, "n1")
    assert cells[1] == "<unresolved>"
    assert "model=" not in text


def test_text_header_handles_zero_llm_nodes() -> None:
    """CP5 #6 — workflow with no LLM nodes renders simply.

    Mutation test: drop the zero-nodes branch from ``_format_scale_line``;
    this test would fail with a divide-by-zero or odd output.
    """
    text = render_text(_make_analysis())  # no rows
    assert "0 LLM nodes" in text


def test_shared_chunks_csv_typed_alias_in_make_diagnostic() -> None:
    """make_diagnostic computes ``shared_chunks_csv`` from ``shared_chunks`` so
    every catalog template has a join-free way to render the discriminator.

    Mutation test: revert the format_dict population in warning_catalog.py;
    the message renders ``{shared_chunks_csv}`` literally (KeyError-free
    because str.format is permissive — but the typed alias would be missing).
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.shared-context-undeclared",
        node_id="X",
        node_count=3,
        shared_chunks=["a", "b", "c"],
        affected_workflow="/abs/x.pflow.md",
        savings_usd=None,
    )
    assert "a, b, c" in diag.message


# ---------------------------------------------------------------------------
# CP4 — rendering polish (#16 #9 #7 #6+#13)
# ---------------------------------------------------------------------------


def _analysis_with_warnings(warnings: list) -> CacheAnalysis:
    """Build an analysis with the given warnings.

    Stage 0: ``recommended_actions`` is renderer-derived from ``warnings``.
    Tests inject scenario data via warnings (production code path).
    """
    return _make_analysis(warnings=warnings)


def _section(text: str, header: str) -> str:
    start = text.index(header)
    next_header = text.find("\n\n## ", start + len(header))
    if next_header == -1:
        return text[start:]
    return text[start:next_header]


def test_text_blocking_errors_section_appears_between_summary_and_recommended_actions() -> None:
    warnings = [
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            id="cache.order-mismatch",
            node_id="test-call",
            message="Order mismatch",
        ),
        Diagnostic(
            severity=Severity.WARNING,
            source="cache_analyzer",
            id="cache.below-min-predicted",
            node_id="test-call",
            message="Below minimum",
        ),
    ]
    text = render_text(_analysis_with_warnings(warnings))
    assert text.index("## Summary") < text.index("## Cache blocking errors")
    assert text.index("## Cache blocking errors") < text.index("## Recommended actions")


def test_text_blocking_errors_section_omitted_when_no_errors() -> None:
    warnings = [
        Diagnostic(
            severity=Severity.WARNING,
            source="cache_analyzer",
            id="cache.below-min-predicted",
            node_id="test-call",
            message="Below minimum",
        )
    ]
    text = render_text(_analysis_with_warnings(warnings))
    assert "## Cache blocking errors" not in text
    assert "## Other blocking errors" not in text
    assert "## Recommended actions" in text


def test_text_blocking_errors_does_not_render_savings_column() -> None:
    warning = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        id="cache.order-mismatch",
        node_id="test-call",
        message="Order mismatch",
        context={"savings_usd": 2.0},
    )
    text = render_text(_analysis_with_warnings([warning]))
    blocking = _section(text, "## Cache blocking errors")
    assert "Order mismatch" in blocking
    assert "cache.order-mismatch" in blocking
    assert "-$2.00/run" not in blocking
    assert "savings unavailable" not in blocking


def test_text_other_blocking_errors_section_renders_when_non_cache_errors_present() -> None:
    """B-9 split: cache-domain ERRORs render under ``## Cache blocking
    errors``; non-cache validator ERRORs (e.g. unknown node type, schema
    errors) render under ``## Other blocking errors (surfaced for
    awareness)``. Agents distinguish caching work from env-config issues.

    Mutation contract: drop the ``not _is_cache_focused_for_advisory(d)``
    clause from ``build_other_blocking_errors`` — both errors render in
    Other and the cache-domain partition collapses; this test fails because
    the cache error appears in BOTH sections.
    """
    cache_error = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        id="cache.order-mismatch",
        node_id="bad-node",
        message="Order mismatch in cache",
    )
    non_cache_error = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        id=None,
        node_id="missing-mcp",
        message="Unknown node type: 'mcp-klavis-youtube-foo'",
        context={"category": "node_type_error"},
    )
    text = render_text(_analysis_with_warnings([cache_error, non_cache_error]))

    assert "## Cache blocking errors (must fix before save and run)" in text
    assert "## Other blocking errors (surfaced for awareness)" in text

    cache_section = _section(text, "## Cache blocking errors")
    other_section = _section(text, "## Other blocking errors")

    # Cache error in cache section, NOT in other section.
    assert "Order mismatch in cache" in cache_section
    assert "Order mismatch in cache" not in other_section
    # Non-cache error in other section, NOT in cache section.
    assert "Unknown node type" in other_section
    assert "Unknown node type" not in cache_section


def test_text_other_blocking_errors_section_omitted_when_only_cache_errors() -> None:
    """When all blocking errors are cache-domain, only the cache section
    renders. The Other section stays hidden — empty section would be noise.

    Mutation contract: render the Other section unconditionally; this test
    fails because the empty header appears.
    """
    warnings = [
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            id="cache.order-mismatch",
            node_id="bad-node",
            message="Order mismatch",
        ),
    ]
    text = render_text(_analysis_with_warnings(warnings))
    assert "## Cache blocking errors (must fix before save and run)" in text
    assert "## Other blocking errors" not in text


def test_text_cache_blocking_errors_section_omitted_when_only_other_errors() -> None:
    """Symmetric: when all blocking errors are non-cache, only the
    blocking-errors section renders. The Cache section stays hidden.

    N-10: when no cache-domain blocking errors render alongside, drop the
    ``Other`` qualifier — it reads as orphan ("other than what?") with no
    sibling section. Bare ``## Blocking errors`` reads as standalone.

    Mutation contract: drop the ``and _is_cache_focused_for_advisory(d)``
    clause in ``build_blocking_errors`` — the non-cache error leaks into
    the Cache section; this test fails because both sections appear.
    """
    warnings = [
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            id=None,
            node_id="missing-mcp",
            message="Unknown node type: 'mcp-klavis-youtube-foo'",
        ),
    ]
    text = render_text(_analysis_with_warnings(warnings))
    assert "## Blocking errors" in text
    assert "## Other blocking errors" not in text
    assert "## Cache blocking errors" not in text


def test_text_other_blocking_errors_section_keeps_qualifier_when_both_render() -> None:
    """When BOTH cache-domain and non-cache blocking errors render, the
    ``Other`` qualifier carries useful relational info (it's "other" relative
    to the cache section above). Keep it in that case.

    Mutation contract: emit ``## Blocking errors`` even when cache-domain
    is present; this test fails because the ``Other`` qualifier disappears.
    """
    warnings = [
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            id="cache.order-mismatch",
            node_id="bad-node",
            message="Order mismatch in cache",
        ),
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            id=None,
            node_id="missing-mcp",
            message="Unknown node type: 'mcp-klavis-youtube-foo'",
        ),
    ]
    text = render_text(_analysis_with_warnings(warnings))
    assert "## Cache blocking errors (must fix before save and run)" in text
    assert "## Other blocking errors (surfaced for awareness)" in text


def test_json_other_blocking_errors_array_excludes_cache_errors() -> None:
    """JSON parity for the B-9 split. ``blocking_errors[]`` carries cache-
    domain ERRORs only; ``other_blocking_errors[]`` carries the rest. Both
    arrays always present (empty-array contract).

    Mutation contract: drop the ``and _is_cache_focused_for_advisory(d)``
    clause in ``build_blocking_errors`` — non-cache error appears in both
    arrays; this test fails because ``blocking_errors`` count grows.
    """
    cache_error = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        id="cache.order-mismatch",
        node_id="bad-node",
        message="Order mismatch",
    )
    non_cache_error = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        id=None,
        node_id="missing-mcp",
        message="Unknown node type: 'mcp-klavis-youtube-foo'",
    )
    result = render_json(_make_analysis(warnings=[cache_error, non_cache_error]))

    assert [a["warning_id"] for a in result["blocking_errors"]] == ["cache.order-mismatch"]
    other_ids = [a.get("warning_id") for a in result["other_blocking_errors"]]
    other_messages = [a.get("message") for a in result["other_blocking_errors"]]
    # Non-cache error has id=None — surfaces by message.
    assert any("Unknown node type" in (m or "") for m in other_messages)
    assert "cache.order-mismatch" not in other_ids


def test_json_blocking_errors_count_matches_summary_blocking_errors() -> None:
    """B-9 alignment: ``len(blocking_errors[])`` matches
    ``summary.blocking_errors`` (the cache-focused headline count).

    Pre-fix, ``blocking_errors[]`` was a superset that included non-cache
    validator errors, while the summary count was already cache-focused —
    so ``len(blocking_errors)`` could exceed ``summary.blocking_errors``.

    Mutation contract: drop the ``and _is_cache_focused_for_advisory(d)``
    clause in ``build_blocking_errors`` — the array gains the non-cache
    error and the lengths diverge.
    """
    cache_error = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        id="cache.order-mismatch",
        node_id="bad-node",
        message="Order mismatch",
    )
    non_cache_error = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        id=None,
        node_id="missing-mcp",
        message="Unknown node type",
    )
    # _make_analysis computes summary.blocking_errors over the *raw* warning
    # ERROR count (not the cache-domain subset) — that's a builder quirk we
    # can't change without ripping through the test surface. Use a fixture
    # with cache-only ERRORs so the builder's count is by construction the
    # cache-focused count.
    result = render_json(_make_analysis(warnings=[cache_error]))
    assert len(result["blocking_errors"]) == result["summary"]["blocking_errors"]

    # Same fixture with an additional non-cache ERROR: blocking_errors[]
    # MUST stay at 1 (cache-focused), even though raw ERROR count is 2.
    result = render_json(_make_analysis(warnings=[cache_error, non_cache_error]))
    assert len(result["blocking_errors"]) == 1
    assert len(result["other_blocking_errors"]) == 1


def test_text_does_NOT_render_all_warnings_section() -> None:
    """CP4 #16 — the "## All warnings" section is dropped from text output.

    Recommended Actions IS the canonical warnings view (sorted by impact).
    JSON output (``warnings[]``) keeps the full machine-readable list for
    consumers who want raw access via ``--format=json``.

    Stage-1 final UX pass: the ``[cache.X]`` bracket prefix and ``Node:``
    label are also gone. The contract that matters: agent visibility into
    the warning is preserved through Recommended Actions (now via headline
    + scope-line node_id).

    Mutation test: re-add the ``warnings = _render_warnings(analysis)``
    branch to ``render_text()``; this test fails because "## All warnings"
    re-appears in the text output.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.shared-context-undeclared",
        node_id="some-node",
        node_count=3,
        shared_chunks=["concept"],
        affected_workflow="/abs/x.pflow.md",
        savings_usd=None,
    )
    text = render_text(_analysis_with_warnings([diag]))
    assert "## All warnings" not in text, "All warnings section should be dropped from text output"
    # Recommended Actions IS the warnings view — agent visibility into the
    # warning MUST still surface there. The new shape carries this via
    # headline (rank line) + node_id (scope line).
    assert "Shared context undeclared" in text  # headline
    assert "some-node" in text  # scope-line node_id
    # Stage-1 UX pass: brackets gone, ``Node:`` label gone.
    assert "[cache.shared-context-undeclared]" not in text
    assert "Node: some-node" not in text


def test_text_brownfield_error_diagnostic_visible_in_blocking_errors_not_recommended_actions() -> None:
    """Brownfield safety (CP4 #16): ERROR-severity diagnostics MUST stay
    visible after dropping "## All warnings".

    A workflow with ``cache.order-mismatch`` (ERROR) had its sole text-mode
    rendering path through the now-deleted "## All warnings" section if
    action views skipped errors. Mutation test: drop the ERROR severity filter
    from ``build_blocking_errors`` or route ERRORs back into
    ``build_recommended_actions``; this test fails because the order-mismatch
    either becomes invisible or lands in the wrong section.

    This is the load-bearing brownfield contract: workflows with declared
    ``## Cache`` blocks may have validator-emitted ERRORs that previously
    appeared ONLY in the now-deleted ``## All warnings`` view. The test
    drives the analyzer through a real production-shape workflow that
    triggers ``cache.order-mismatch``, then asserts the diagnostic survives
    in Blocking errors and is absent from Recommended actions.
    """
    from pflow.core.prompt_cache_analysis import analyze

    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"a": {"type": "string"}, "b": {"type": "string"}},
        "cache": {
            "items": [
                {"name": "a", "var": "a", "prose_before": "A:\n"},
                {"name": "b", "var": "b", "prose_before": "B:\n"},
            ]
        },
        "nodes": [
            {
                "id": "write-lyrics",
                "type": "llm",
                "prompt_cache": ["b", "a"],  # wrong order — fires cache.order-mismatch ERROR
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "${a} ${b}",
                },
            }
        ],
        "edges": [],
    }
    analysis = analyze(workflow_ir, auto_load_trace=False)
    text = render_text(analysis)
    assert "## Cache blocking errors (must fix before save and run)" in text
    # Stage-1 final UX pass: ``[cache.order-mismatch]`` brackets are gone,
    # while the diagnostic ID remains visible in a quieter inline form.
    # The load-bearing brownfield contract: the ERROR-severity diagnostic
    # surfaces in Blocking errors with enough discriminator for the
    # agent to act on it. The order-mismatch message body carries the
    # exact fix (``expected:``/``you wrote:``/``fix:`` lines), so the
    # agent sees both WHAT failed and HOW to fix without ID brackets.
    #
    # Verified:
    # - Blocking errors section renders the diagnostic
    # - Node ID is visible (so the agent knows which node failed)
    # - The fix lines from the message body are visible
    # - Brackets are gone (the visual coding regression we deliberately
    #   removed in this UX pass)
    blocking = _section(text, "## Cache blocking errors")
    assert "write-lyrics" in blocking
    assert "cache.order-mismatch" in blocking
    assert "expected:" in blocking  # one of the message body's fix lines
    assert "you wrote:" in blocking  # ditto — confirms full message rendered
    assert "[cache.order-mismatch]" not in blocking  # brackets dropped
    if "## Recommended actions" in text:
        recommended = _section(text, "## Recommended actions")
        assert "expected:" not in recommended
        assert "you wrote:" not in recommended
    # Crucially, "## All warnings" is gone — the ERROR's ONLY rendering
    # path is now Blocking errors.
    assert "## All warnings" not in text


def test_per_call_confidence_footer_lists_low_confidence_nodes() -> None:
    """Low-confidence input token estimates move from per-row ``src=`` cells
    into one footer.

    Mutation contract: remove ``_per_call_confidence_footer`` from
    ``_render_per_call``; this test fails because the estimator/heuristic rows
    have no human-readable confidence signal.
    """
    rows = [
        _row("trace-row", 50),
        _row("memo-row", 50),
        _row("estim-row", 50),
        _row("heur-row", 50),
    ]
    rows[0] = PerCallRow(**{**rows[0].__dict__, "data_source": "trace"})
    rows[1] = PerCallRow(**{**rows[1].__dict__, "data_source": "memo"})
    # ``estimator``/``heuristic`` rows need declared_prompt_cache to survive
    # the Option C visibility filter — without it they're hidden.
    rows[2] = PerCallRow(**{**rows[2].__dict__, "data_source": "estimator", "declared_prompt_cache": ["foo"]})
    rows[3] = PerCallRow(**{**rows[3].__dict__, "data_source": "heuristic", "declared_prompt_cache": ["foo"]})
    text = render_text(_make_analysis(rows=rows))
    # Multi-line bullet block (Fix 5+6): header + indented bullet.
    assert "Token estimate confidence:" in text
    assert "Projected input tokens for: estim-row, heur-row." in text
    assert "src=" not in text


def test_per_call_confidence_footer_flags_batch_exemplar_projections() -> None:
    """Batch rows resolved from parameters are single-item exemplars and the
    footer names that approximation.

    Mutation contract: drop the ``cacheable_data_source == "parameters" and
    row.is_batch`` branch from ``_per_call_confidence_footer``; this test
    fails because the representative-sample caveat disappears.
    """
    row = PerCallRow(**{
        **_row("batched-review", 50).__dict__,
        "is_batch": True,
        "batch_size_estimated": 4,
        "data_source": "memo",
        "cacheable_data_source": "parameters",
    })
    text = render_text(_make_analysis(rows=[row]))
    assert "Token estimate confidence:" in text
    assert (
        "batched-review: tokens estimated from the first batch item as a representative sample. "
        "Actual tokens may vary for later items."
    ) in text


def test_per_call_confidence_footer_uses_distinct_message_for_batch_prefix_projection() -> None:
    """Batch-prefix projection is structurally different from the parameters-tier
    batch exemplar case: no batch item content participates in the projection.
    The footer message must say "static prefix repeated across the batch",
    NOT "first batch item as a representative sample" — the latter would be a
    factual misrepresentation of what the analyzer measured.

    Mutation contract: revert ``_prefer_batch_prefix_cacheable_tokens`` to return
    ``"parameters"`` instead of ``"batch_prefix"``; this test fails because the
    footer routes through the exemplar branch instead and emits the wrong prose.
    """
    row = PerCallRow(**{
        **_row("score-choruses", 1000).__dict__,
        "is_batch": True,
        "batch_size_estimated": 0,
        "data_source": "trace",
        "cacheable_data_source": "batch_prefix",
        "observed_call_count": 136,
    })
    text = render_text(_make_analysis(rows=[row]))
    assert "Token estimate confidence:" in text
    assert (
        "score-choruses: savings projected from a stable prompt prefix repeated across the batch. "
        "Use `--report` to confirm with a real run."
    ) in text
    assert "first batch item as a representative sample" not in text


def test_per_call_confidence_footer_uses_distinct_message_for_cross_workflow_projection() -> None:
    """Cross-workflow projection footer must name affected rows and route agents
    to the section that carries the required edits.

    Mutation contract: route ``cross_workflow_projection`` through the generic
    future-tier path or mention only Recommended actions; this test fails
    because the row-specific routing prose disappears.
    """
    row = PerCallRow(**{
        **_row("select-chorus", 20).__dict__,
        "data_source": "trace",
        "cacheable_data_source": "cross_workflow_projection",
        "cross_workflow_inputs": (CrossWorkflowInputContribution("concept", 20, "test/model"),),
        "observed_call_count": 4,
    })
    text = render_text(_make_analysis(rows=[row]))
    assert "Token estimate confidence:" in text
    assert "select-chorus: savings projected from values flowing in" in text
    assert "See Recommended actions for the per-boundary fix." in text
    assert "Sub-workflow boundaries" not in text
    # Pre-fix wording falsely implied the parent had cache declarations; the
    # whole point of the row is that nothing is declared yet.
    assert "shared inputs declared in parent workflow" not in text
    # Cleanup-first guidance lives in Recommended actions (the bullet routes
    # the agent there); the footer no longer duplicates that prose.
    assert "static prefix repeated across the batch" not in text


def test_per_call_confidence_footer_aggregates_duplicate_node_names() -> None:
    """Fix 5: when the same ``node_path`` repeats across rows from
    different sub-workflows (lyrics-generator has 8 review sub-workflows
    each containing a node literally named ``review``), the footer would
    previously render ``"review, review, review, ..."`` — reads as a
    string-join bug. Aggregate to ``"8 review nodes"``.

    Mutation contract: drop the ``Counter``-based aggregation in
    ``_format_node_list`` → "review, review, ..." returns.
    """
    rows = [
        PerCallRow(**{
            **_row("review", 20).__dict__,
            "data_source": "trace",
            "cacheable_data_source": "cross_workflow_projection",
            "cross_workflow_inputs": (CrossWorkflowInputContribution("creative_direction", 20, "test/model"),),
            "observed_call_count": 4,
        })
        for _ in range(8)
    ]
    # Add one unique-name row so the aggregate test exercises mixing.
    rows.append(
        PerCallRow(**{
            **_row("select-chorus", 20).__dict__,
            "data_source": "trace",
            "cacheable_data_source": "cross_workflow_projection",
            "cross_workflow_inputs": (CrossWorkflowInputContribution("concept", 20, "test/model"),),
            "observed_call_count": 4,
        })
    )
    text = render_text(_make_analysis(rows=rows))
    # Aggregated form: "8 review nodes" (reviews come first in row order).
    assert "8 review nodes" in text
    assert "select-chorus" in text
    # Old buggy form is gone — no "review, review" duplication.
    assert "review, review" not in text


def test_per_call_confidence_footer_renders_multi_line_bullet_block() -> None:
    """Fix 6: the footer renders as a multi-line bullet block, not a single
    semicolon-chained paragraph. Header line + one bullet per tier.

    Mutation contract: change ``_per_call_confidence_footer`` back to
    ``str | None`` returning a joined paragraph → multi-line bullet
    assertions fail.
    """
    rows = [
        PerCallRow(**{
            **_row("score-choruses", 1000).__dict__,
            "is_batch": True,
            "batch_size_estimated": 0,
            "data_source": "trace",
            "cacheable_data_source": "batch_prefix",
            "observed_call_count": 136,
        }),
        PerCallRow(**{
            **_row("select-chorus", 20).__dict__,
            "data_source": "trace",
            "cacheable_data_source": "cross_workflow_projection",
            "cross_workflow_inputs": (CrossWorkflowInputContribution("concept", 20, "test/model"),),
            "observed_call_count": 4,
        }),
    ]
    text = render_text(_make_analysis(rows=rows))
    # Header line standalone (no inline content after the colon).
    assert "  Token estimate confidence:\n" in text
    # Each tier is its own indented bullet.
    assert "    · score-choruses: savings projected from a stable prompt prefix" in text
    assert "    · select-chorus: savings projected from values flowing in" in text
    # Old semicolon-chained form is gone.
    assert "Token estimate confidence: score-choruses" not in text


def test_per_call_row_renders_multi_candidate_notes_when_inputs_count_gt_1() -> None:
    """Rows with multiple cross-workflow contributors should show compact
    decomposition in the notes column; single-input rows should stay quiet.

    Mutation contract: remove the ``cross_workflow_inputs`` note branch from
    ``_cell_notes``; this test fails because the summed row becomes opaque.
    """
    multi = PerCallRow(**{
        **_row("review", 20).__dict__,
        "data_source": "trace",
        "cacheable_data_source": "cross_workflow_projection",
        "cross_workflow_inputs": (
            CrossWorkflowInputContribution("creative_direction", 20, "test/model"),
            CrossWorkflowInputContribution("song_architecture", 20, "test/model"),
        ),
    })
    single = PerCallRow(**{
        **_row("select", 20).__dict__,
        "data_source": "trace",
        "cacheable_data_source": "cross_workflow_projection",
        "cross_workflow_inputs": (CrossWorkflowInputContribution("concept", 20, "test/model"),),
    })
    many = PerCallRow(**{
        **_row("many", 20).__dict__,
        "data_source": "trace",
        "cacheable_data_source": "cross_workflow_projection",
        "cross_workflow_inputs": (
            CrossWorkflowInputContribution("a", 20, "test/model"),
            CrossWorkflowInputContribution("b", 20, "test/model"),
            CrossWorkflowInputContribution("c", 20, "test/model"),
            CrossWorkflowInputContribution("d", 20, "test/model"),
        ),
    })
    text = render_text(_make_analysis(rows=[multi, single, many]))
    assert "cacheable values: creative_direction, song_architecture" in text
    assert "cacheable values: concept" not in text
    assert "cacheable values: a, b, c, +1 more" in text


def test_per_call_hides_universally_empty_cache_columns_in_static_mode() -> None:
    rows = [
        PerCallRow(**{
            **_row("write-lyrics", 0).__dict__,
            "model": "",
            "input_tokens_estimated": 3684,
            "cacheable_tokens_estimated": None,
            "cache_ratio_pct": None,
            "cacheable_data_source": "unavailable",
        }),
        PerCallRow(**{
            **_row("song-architecture", 0).__dict__,
            "model": "",
            "input_tokens_estimated": 2886,
            "cacheable_tokens_estimated": None,
            "cache_ratio_pct": None,
            "cacheable_data_source": "unavailable",
        }),
    ]

    text = render_text(_make_analysis(rows=rows))

    header = _per_call_header(text)
    assert header == ["node", "model", "input", "notes"]
    assert "cached_now" not in header
    assert "could_cache" not in header
    assert "ratio" not in header
    assert "calls" not in header


def test_per_call_keeps_all_columns_in_mixed_mode() -> None:
    rows = [
        PerCallRow(**{
            **_row("cached", 75).__dict__,
            "data_source": "trace",
            "declared_prompt_cache": ["prefix"],
            "cacheable_data_source": "trace",
            "observed_call_count": 2,
        }),
        PerCallRow(**{
            **_row("projected", 25).__dict__,
            "data_source": "trace",
            "cacheable_data_source": "memo",
            "observed_call_count": 2,
        }),
    ]

    text = render_text(_make_analysis(rows=rows, actually_paid=0.01, no_cache=0.02))

    assert _per_call_header(text) == [
        "node",
        "model",
        "input",
        "cached_now",
        "ready",
        "upside",
        "ratio",
        "calls",
        "notes",
    ]
    cached = _per_call_cells_by_header(text, "cached")
    projected = _per_call_cells_by_header(text, "projected")
    assert cached["cached_now"] == "7,500"
    assert cached["ready"] == "7,500"
    assert projected["cached_now"] == "—"
    assert projected["ready"] == "2,500"
    assert projected["upside"] == "2,500"


def test_per_call_dedups_repeated_notes_into_footer() -> None:
    rows = [
        PerCallRow(**{
            **_row(f"n{i}", 0).__dict__,
            "cacheable_tokens_estimated": None,
            "cache_ratio_pct": None,
            "cacheable_data_source": "unavailable",
        })
        for i in range(3)
    ]

    text = render_text(_make_analysis(rows=rows))

    assert "Per-call notes:" in text
    assert "3 nodes lack trace data — run with --report to populate cache columns." in text
    assert text.count("no trace recorded — run with --report to populate this row") == 0
    assert _per_call_cells_by_header(text, "n0")["notes"] == ""


def test_per_call_dedup_handles_row_with_dedup_note_plus_inline_note() -> None:
    rows = [
        PerCallRow(**{
            **_row(f"n{i}", 0).__dict__,
            "cacheable_tokens_estimated": None,
            "cache_ratio_pct": None,
            "cacheable_data_source": "unavailable",
        })
        for i in range(6)
    ]
    rows.append(
        PerCallRow(**{
            **_row("special", 0).__dict__,
            "cacheable_tokens_estimated": None,
            "cache_ratio_pct": None,
            "cacheable_data_source": "unavailable",
        })
    )
    warning = Diagnostic(
        severity=Severity.WARNING,
        source="cache_analyzer",
        id="cache.dynamic-before-static",
        node_id="special",
        message="Dynamic before static.",
    )

    text = render_text(_make_analysis(rows=rows, warnings=[warning]))

    assert "7 nodes lack trace data — run with --report to populate cache columns." in text
    assert _per_call_cells_by_header(text, "special")["notes"] == "dynamic-before-static"


def test_per_call_inline_renders_unique_notes() -> None:
    row = PerCallRow(**{
        **_row("unique", 0).__dict__,
        "cacheable_tokens_estimated": None,
        "cache_ratio_pct": None,
        "cacheable_data_source": "unavailable",
    })

    text = render_text(_make_analysis(rows=[row]))

    assert "Per-call notes:" not in text
    assert (
        _per_call_cells_by_header(text, "unique")["notes"]
        == "no trace recorded — run with --report to populate this row"
    )


def test_per_call_explainer_adapts_to_visible_columns() -> None:
    projected = PerCallRow(**{
        **_row("projected", 50).__dict__,
        "declared_prompt_cache": ["prefix"],
        "cacheable_data_source": "memo",
    })
    unavailable = PerCallRow(**{
        **_row("unavailable", 0).__dict__,
        "cacheable_tokens_estimated": None,
        "cache_ratio_pct": None,
        "cacheable_data_source": "unavailable",
    })

    projected_text = render_text(_make_analysis(rows=[projected]))
    unavailable_text = render_text(_make_analysis(rows=[unavailable]))

    assert "cached_now: tokens served from cache during this run" not in projected_text
    assert "ready: tokens already active" in projected_text
    assert "cached_now: tokens served from cache during this run" not in unavailable_text
    assert "could_cache: extra tokens" not in unavailable_text


def test_per_call_explainer_returns_empty_when_no_cache_columns_visible() -> None:
    row = PerCallRow(**{
        **_row("unavailable", 0).__dict__,
        "cacheable_tokens_estimated": None,
        "cache_ratio_pct": None,
        "cacheable_data_source": "unavailable",
    })

    text = render_text(_make_analysis(rows=[row]))

    assert "How to read each row:" not in text
    assert "cached_now:" not in text
    assert "could_cache:" not in text


def test_per_call_calls_column_hidden_in_static_mode() -> None:
    row = PerCallRow(**{
        **_row("projected", 50).__dict__,
        "cacheable_data_source": "memo",
    })

    static_text = render_text(_make_analysis(rows=[row]))
    trace_text = render_text(_make_analysis(rows=[dataclasses.replace(row, data_source="trace")], actually_paid=0.01))

    assert "calls" not in _per_call_header(static_text)
    assert "calls" in _per_call_header(trace_text)


def test_per_call_all_rows_can_reexpose_hidden_columns() -> None:
    visible_row = PerCallRow(**{
        **_row("visible", 30).__dict__,
        "cacheable_tokens_estimated": None,
        "cache_ratio_pct": None,
        "cacheable_data_source": "unavailable",
    })
    hidden_row = PerCallRow(**{
        **_row("hidden", 90).__dict__,
        "declared_prompt_cache": ["prefix"],
        "cacheable_data_source": "trace",
    })
    analysis = _make_analysis(rows=[visible_row, hidden_row])

    default_text = render_text(analysis)
    all_rows_text = render_text(analysis, all_rows=True)

    assert "cached_now" not in _per_call_header(default_text)
    assert "cached_now" in _per_call_header(all_rows_text)
    with pytest.raises(AssertionError):
        _per_call_cells_by_header(default_text, "hidden")
    assert _per_call_cells_by_header(all_rows_text, "hidden")["cached_now"] == "9,000"


def test_per_call_table_divider_excludes_notes_column_width() -> None:
    """The horizontal divider between header and data rows must size to the
    structured columns (``node`` through ``calls``), NOT to the unbounded
    trailing ``notes`` column. Without this gate, one row with a long
    ``observed=...; warning-id`` notes cell stretches the divider far beyond
    every other row's visible width — visually overshooting the table.

    Mutation contract: change ``_structured_columns_width`` to use the full
    ``len(header)`` (i.e., include the notes column); this test fails because
    the divider becomes ~50+ chars longer than the row's structured prefix.
    """
    long_observed_models = ("gemini/gemini-2.5-flash-lite", "gemini/gemini-3-flash-preview")
    long_notes_row = PerCallRow(**{
        **_row("opaque-batch", 50).__dict__,
        "model": "",
        "observed_models": long_observed_models,
        "model_is_heterogeneous": True,
        "is_batch": True,
        "batch_size_estimated": 4,
    })
    short_row = PerCallRow(**{
        **_row("plain-row", 50).__dict__,
        "data_source": "trace",
    })
    text = render_text(_make_analysis(rows=[long_notes_row, short_row]))
    lines = text.split("\n")
    divider_lines = [line for line in lines if set(line.strip()) == {"-"}]
    assert divider_lines, "expected a horizontal divider in per-call section"
    divider = divider_lines[0]
    # The longest data row — the one with long observed= notes — must be
    # strictly longer than the divider. If the divider tracked notes-column
    # width, it would equal the full row length.
    long_data_rows = [line for line in lines if "observed=" in line and "opaque-batch" in line]
    assert long_data_rows, "expected the long-notes row to be rendered"
    assert len(long_data_rows[0]) > len(divider), (
        "divider should be SHORTER than the long-notes row "
        f"(divider={len(divider)} chars, row={len(long_data_rows[0])} chars)"
    )


def test_text_pure_greenfield_hides_per_call_section_with_explanatory_note() -> None:
    """Option C: pure-greenfield workflows (no ``prompt_cache:`` declared AND
    no memo/trace data) hide the entire ``## Per-call cache report`` section.

    Pure-greenfield rows fail ``_row_has_real_data`` — their input_tokens
    column shows TEMPLATE size (with ``${var}`` references counted as ~5-token
    literals — NOT actual runtime size) and their cacheable column is
    unprojectable. Both columns mislead, so the section disappears entirely.

    The analyzer mirrors the renderer's filter at analyze-time and appends a
    Notes entry explaining the absence so agents understand it's intentional.
    The renderer must surface that note even though the per-call section is
    suppressed — the note IS the agent's signal to run the workflow once.

    Mutation test: remove the section-hide branch in ``_render_per_call``
    (return early when ``not real_data_rows``); this test fails because the
    misleading per-call table renders again.
    """
    # data_source="estimator" + declared_prompt_cache=None → fails filter.
    raw_rows = [_row("n1", 0), _row("n2", 0)]
    rows = [PerCallRow(**{**r.__dict__, "data_source": "estimator"}) for r in raw_rows]
    # The analyzer would append this note; mirror that here so the renderer
    # surfaces the agent-facing explanation.
    hidden_note = (
        "Per-call cache report hidden — workflow has no run data yet. "
        "Run once, then re-run analyze-cache for real per-node token "
        "estimates and cacheable projections."
    )
    text = render_text(_make_analysis(rows=rows, notes=[hidden_note]))
    # Per-call section is hidden entirely.
    assert "## Per-call cache report" not in text
    # Notes entry surfaces the explanatory message.
    assert "Per-call cache report hidden" in text
    assert "no run data yet" in text
    # The collapsed explainer must NOT render (the section is gone).
    assert "How to read each row:" not in text
    # Legacy mode-specific explainer phrases must NOT render either.
    assert "Actual cache ratios" not in text
    assert "Projected cache ratios" not in text
    assert "No shared context detected" not in text


def test_text_per_call_explainer_renders_unified_block_for_post_run_greenfield() -> None:
    """The per-call explainer collapses post-run-greenfield and steady-state
    into one shared "How to read each row:" block — both modes need the same
    column documentation, and the prior split-leads (``"Actual cache ratios
    from declared prompt_cache: subsets."`` vs ``"Projected cache ratios from
    prior run data."``) required agents to understand the steady-state vs
    greenfield distinction before they could read the table.

    Mutation test: re-introduce the split lead path → both post-run and
    steady-state tests below fire because the new header is missing.
    """
    # ``_row("n1", 50)`` defaults to data_source="memo", declared_prompt_cache=None
    # — the post-run greenfield path.
    rows = [PerCallRow(**{**_row("n1", 50).__dict__, "cacheable_data_source": "memo"})]
    text = render_text(_make_analysis(rows=rows))
    assert "## Per-call cache report" in text
    assert "How to read each row:" in text
    # Old split-lead phrasings must NOT render.
    assert "Actual cache ratios from declared" not in text
    assert "Projected cache ratios from prior run data" not in text
    assert "No shared context detected" not in text


def test_text_per_call_explainer_renders_unified_block_for_steady_state() -> None:
    """Same collapsed block applies when ≥1 node has declared ``prompt_cache``.
    The new header doesn't differentiate steady-state vs greenfield because
    the column documentation is identical for both — and the per-row data
    already signals which mode this run is in (a populated ``cached_now``
    means a trace fired).

    Mutation test: re-introduce the ``is_steady_state`` branch → the negative
    assertion on the old "Actual cache ratios" string fires.
    """
    rows = [_row("n1", 0), _row("n2", 75)]
    rows[1] = PerCallRow(**{
        **rows[1].__dict__,
        "declared_prompt_cache": ["concept", "concept_brief"],
        "cacheable_data_source": "memo",
    })
    text = render_text(_make_analysis(rows=rows))
    assert "How to read each row:" in text
    assert "Actual cache ratios" not in text


def test_text_header_drops_low_no_data_confidence() -> None:
    """CP4 #6+#13 — header omits ``Confidence: low_no_data`` line.

    The cost-section call-to-action ("run the workflow once") communicates
    the same info actionably; the header line was a redundant signal.

    Mutation test: revert ``_render_header`` to always emit the confidence
    line; this test fails because ``low_no_data`` re-appears.
    """
    text = render_text(_make_analysis())
    assert "low_no_data" not in text


def test_text_header_keeps_medium_from_memo_with_coverage() -> None:
    """CP4 #6+#13 — header KEEPS confidence label for medium/high tiers.

    These labels carry coverage info that helps agents reason about how much
    to trust the per-call numbers. Suppressing ALL confidence labels would
    hide actionable fidelity info; we only suppress the no-info ``low_no_data``.

    Mutation test: drop the ``if label in {medium..., high...}:`` branch from
    ``_render_header``; this test fails because the actionable label
    disappears alongside the redundant one.
    """
    rows = [_row("n1", 50), _row("n2", 50)]
    analysis = _make_analysis(rows=rows)
    # Override confidence label for testing
    analysis = CacheAnalysis(**{
        **analysis.__dict__,
        "estimate_confidence": "medium_from_memo",
        "estimate_confidence_coverage": {"trace": 0, "memo": 2, "estimator": 0, "heuristic": 0, "total": 2},
    })
    text = render_text(analysis)
    # Bug 15: enum is replaced with plain English; JSON keeps the raw label.
    assert "Confidence: medium — token counts from memoized prior runs" in text
    assert "(2 of 2 nodes)" in text
    # Negative assertion: no analyzer-internal taxonomy leaks to text.
    assert "medium_from_memo" not in text


def test_text_header_suppresses_confidence_when_redundant_with_evidence() -> None:
    """Fix 4: ``Confidence: high_from_trace (N of N nodes)`` is redundant
    when the Evidence line above already says ``complete trace (N LLM
    nodes executed)`` and nothing was unreached.

    The lyrics-generator capture surfaced this: lines 7 + 9 said the same
    thing in different words. A fresh agent reads the second one as
    leaking an enum (``high_from_trace`` looks like an internal label).
    Drop it when tautological.

    Mutation contract: remove the ``suppress`` gate (always-emit the
    Confidence line) → this test fails because the redundant line returns.
    """
    rows = [_row("n1", 50), _row("n2", 50)]
    analysis = _make_analysis(rows=rows)
    analysis = CacheAnalysis(**{
        **analysis.__dict__,
        "estimate_confidence": "high_from_trace",
        "estimate_confidence_coverage": {"trace": 2, "memo": 0, "estimator": 0, "heuristic": 0, "total": 2},
        "summary": AnalysisSummary(**{
            **analysis.summary.__dict__,
            "evidence_scope": "complete_trace",
            "trace_llm_nodes_static": 2,
            "trace_llm_nodes_executed": 2,
        }),
    })
    text = render_text(analysis)
    # Evidence still emitted (carries the same info actionably).
    assert "complete trace (2 LLM nodes executed)" in text
    # Confidence suppressed — the redundant tautology is gone.
    assert "Confidence: high" not in text
    assert "(2 of 2 nodes)" not in text
    # Negative assertion: enum doesn't leak even when line is present elsewhere.
    assert "high_from_trace" not in text


def test_text_header_keeps_confidence_when_unreached_nodes_present() -> None:
    """Fix 4 inverse: when Evidence says ``N of M executed; K not reached``,
    Confidence's denominator (analyzed rows) differs from Evidence's
    (static IR nodes) and the line carries genuine signal — keep it.

    Mutation contract: tighten the suppression to fire even with unreached
    nodes → this test fails because Confidence disappears here.
    """
    rows = [_row("n1", 50), _row("n2", 50)]
    analysis = _make_analysis(rows=rows)
    analysis = CacheAnalysis(**{
        **analysis.__dict__,
        "estimate_confidence": "high_from_trace",
        "estimate_confidence_coverage": {"trace": 2, "memo": 0, "estimator": 0, "heuristic": 0, "total": 2},
        "summary": AnalysisSummary(**{
            **analysis.summary.__dict__,
            "evidence_scope": "complete_trace",
            "trace_llm_nodes_static": 3,  # 3 IR nodes
            "trace_llm_nodes_executed": 2,  # 2 actually ran (1 unreached)
        }),
    })
    text = render_text(analysis)
    # Evidence says X executed; Z not reached.
    assert "not reached" in text
    # Confidence still emitted — the denominators are different.
    # Bug 15: enum → plain text.
    assert "Confidence: high — token counts from this run's trace" in text
    assert "high_from_trace" not in text


def test_text_header_keeps_confidence_for_truncated_trace() -> None:
    """Fix 4 inverse: truncated traces report different signal classes on
    the two lines — Evidence describes the truncation, Confidence describes
    per-tier sources over executed rows. Keep both.

    Mutation contract: extend suppression to truncated branch → this test
    fails because the truncated case loses its Confidence signal.
    """
    rows = [_row("n1", 50)]
    analysis = _make_analysis(rows=rows)
    analysis = CacheAnalysis(**{
        **analysis.__dict__,
        "estimate_confidence": "high_from_trace",
        "estimate_confidence_coverage": {"trace": 1, "memo": 0, "estimator": 0, "heuristic": 0, "total": 1},
        "summary": AnalysisSummary(**{
            **analysis.summary.__dict__,
            "evidence_scope": "truncated_trace_executed_subset",
            "trace_llm_nodes_static": 2,
            "trace_llm_nodes_executed": 1,
        }),
    })
    text = render_text(analysis)
    assert "trace truncated" in text
    # Bug 15: enum → plain text.
    assert "Confidence: high — token counts from this run's trace" in text
    assert "high_from_trace" not in text


# ---------------------------------------------------------------------------
# Sub-cent cost rendering (Track A follow-up)
# ---------------------------------------------------------------------------


def test_text_renders_sub_cent_cost_with_four_decimals() -> None:
    """Track A surfaces sub-cent costs; the renderer must show them with
    enough precision to be useful. ``:.2f`` unconditionally would render
    sub-cent costs as ``$0.00`` and decorate them with ``(trace)``.
    """
    text = render_text(_make_analysis(actually_paid=0.0021, no_cache=0.0023, rerun=0.0017, partial=False))
    assert "~$0.0021" in text
    assert "~$0.0023" in text
    # Genuine zero stays in 2-decimal format (cleaner with annotations).
    text_zero = render_text(_make_analysis(actually_paid=0.0, no_cache=0.0, rerun=0.0, partial=False))
    assert "~$0.00" in text_zero
    # Below-threshold values render as a less-than indicator.
    text_tiny = render_text(_make_analysis(actually_paid=0.00001, no_cache=0.00002, rerun=0.00001, partial=False))
    assert "~<$0.0001" in text_tiny


def test_render_text_groups_per_call_by_workflow_path_with_called_by() -> None:
    """Defends: workflow-path grouping in ``render_text`` produces the
    ``### child.pflow.md (called by ...)`` subheader; reverting it
    collapses per-call rows back into a flat list.
    """
    rows = [
        PerCallRow(**{**_row("draft", 30).__dict__, "workflow_path": "/abs/parent.pflow.md"}),
        PerCallRow(**{**_row("review", 30).__dict__, "workflow_path": "/abs/child.pflow.md"}),
    ]
    base = _make_analysis(rows=rows, workflow_path="/abs/parent.pflow.md")
    rollup = SubWorkflowRollup(
        workflows_included=("/abs/child.pflow.md",),
        max_depth_walked=1,
        truncated=False,
        per_workflow=(
            SubWorkflowRollupEntry(
                workflow_path="/abs/child.pflow.md",
                called_by_node_id="call-child",
                llm_node_count=1,
                actually_paid_usd=0.07,
                no_cache_hypothetical_usd=0.10,
                first_run_with_cache_hypothetical_usd=0.09,
                rerun_within_ttl_hypothetical_usd=0.05,
            ),
        ),
    )
    analysis = CacheAnalysis(**{
        **base.__dict__,
        "summary": AnalysisSummary(**{**base.summary.__dict__, "sub_workflow_rollup": rollup}),
    })

    text = render_text(analysis, all_rows=True)

    assert "### parent.pflow.md" in text
    assert "### child.pflow.md (called by call-child)" in text
    assert "(1 in parent.pflow.md, 1 in 1 sub-workflow)" in text
    assert "## Per-child analyze-cache commands" in text
    # Self-contained commands only — no `cd`. Paths render cwd-relative
    # when the workflow lives under cwd, absolute otherwise; here the
    # workflow is outside the test's cwd so the absolute form renders.
    assert "    cd " not in text
    assert "pflow analyze-cache /abs/child.pflow.md" in text


def test_render_text_drill_in_omitted_for_single_workflow() -> None:
    text = render_text(_make_analysis(rows=[_row("draft", 30)]), all_rows=True)
    assert "## Per-child analyze-cache commands" not in text
    assert "(called by" not in text


def test_render_text_drill_in_emits_cwd_relative_path_when_workflow_under_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-child drill-in renders paths cwd-relative when the workflow
    lives under the invocation cwd. Self-contained commands runnable from
    the agent's cwd — no ``cd``.

    Mutation contract: revert ``_render_sub_workflow_drill_in`` to the
    ``cd <parent>`` + relpath shape; the ``cd`` substring re-appears and
    the self-contained ``pflow analyze-cache parent/sub/child.pflow.md``
    line goes missing.
    """
    monkeypatch.chdir(tmp_path)
    parent_path = tmp_path / "parent" / "parent.pflow.md"
    child_path = tmp_path / "parent" / "sub" / "child.pflow.md"
    child_path.parent.mkdir(parents=True)

    rows = [
        PerCallRow(**{**_row("draft", 30).__dict__, "workflow_path": str(parent_path)}),
        PerCallRow(**{**_row("review", 30).__dict__, "workflow_path": str(child_path)}),
    ]
    base = _make_analysis(rows=rows, workflow_path=str(parent_path))
    rollup = SubWorkflowRollup(
        workflows_included=(str(child_path),),
        max_depth_walked=1,
        truncated=False,
        per_workflow=(
            SubWorkflowRollupEntry(
                workflow_path=str(child_path),
                called_by_node_id="call-child",
                llm_node_count=1,
                actually_paid_usd=0.07,
                no_cache_hypothetical_usd=0.10,
                first_run_with_cache_hypothetical_usd=0.09,
                rerun_within_ttl_hypothetical_usd=0.05,
            ),
        ),
    )
    analysis = CacheAnalysis(**{
        **base.__dict__,
        "summary": AnalysisSummary(**{**base.summary.__dict__, "sub_workflow_rollup": rollup}),
    })
    text = render_text(analysis, all_rows=True)

    assert "    cd " not in text
    assert "pflow analyze-cache parent/sub/child.pflow.md" in text
    assert str(child_path) not in text


def test_render_text_drill_in_filters_zero_llm_node_children() -> None:
    """Children with ``llm_node_count == 0`` (e.g., MCP/shell-only orchestrators)
    produce no LLM cache findings under ``analyze-cache`` — emitting a command
    for them is noise. Filter at the renderer; the breakdown count must move
    in lockstep so the header doesn't claim ``N sub-workflows`` while the
    block lists ``N-1`` commands.

    Mutation contract: drop the ``llm_node_count > 0`` filter in
    ``_llm_bearing_rollup_entries``; both negative substring assertions fail
    (the 0-LLM child reappears in the drill-in, and the breakdown count
    drifts up to include it).
    """
    rows = [
        PerCallRow(**{**_row("draft", 30).__dict__, "workflow_path": "/abs/parent.pflow.md"}),
        PerCallRow(**{**_row("review", 30).__dict__, "workflow_path": "/abs/llm-child.pflow.md"}),
    ]
    base = _make_analysis(rows=rows, workflow_path="/abs/parent.pflow.md")
    rollup = SubWorkflowRollup(
        workflows_included=("/abs/llm-child.pflow.md", "/abs/mcp-only-child.pflow.md"),
        max_depth_walked=1,
        truncated=False,
        per_workflow=(
            SubWorkflowRollupEntry(
                workflow_path="/abs/llm-child.pflow.md",
                called_by_node_id="call-llm-child",
                llm_node_count=1,
            ),
            SubWorkflowRollupEntry(
                workflow_path="/abs/mcp-only-child.pflow.md",
                called_by_node_id="call-mcp-child",
                llm_node_count=0,
            ),
        ),
    )
    analysis = CacheAnalysis(**{
        **base.__dict__,
        "summary": AnalysisSummary(**{**base.summary.__dict__, "sub_workflow_rollup": rollup}),
    })

    text = render_text(analysis, all_rows=True)

    # Drill-in lists only the LLM-bearing child.
    assert "pflow analyze-cache /abs/llm-child.pflow.md" in text
    assert "mcp-only-child.pflow.md" not in text
    # Breakdown count says "1 sub-workflow", not "2 sub-workflows".
    assert "in 1 sub-workflow)" in text
    assert "in 2 sub-workflows)" not in text


def test_render_text_drill_in_suppressed_when_all_children_have_zero_llm_nodes() -> None:
    """When every cross-workflow child has ``llm_node_count == 0``, the drill-in
    section emits nothing (not even the ``cd`` line — a paste-ready block with
    no commands is worse than absence).

    Mutation contract: drop the ``if not llm_bearing: return ""`` early-out;
    the section emits a header + ``cd`` line with no commands, and the
    "## Per-child analyze-cache commands" substring reappears.
    """
    rows = [PerCallRow(**{**_row("draft", 30).__dict__, "workflow_path": "/abs/parent.pflow.md"})]
    base = _make_analysis(rows=rows, workflow_path="/abs/parent.pflow.md")
    rollup = SubWorkflowRollup(
        workflows_included=("/abs/mcp-only-child.pflow.md",),
        max_depth_walked=1,
        truncated=False,
        per_workflow=(
            SubWorkflowRollupEntry(
                workflow_path="/abs/mcp-only-child.pflow.md",
                called_by_node_id="call-mcp-child",
                llm_node_count=0,
            ),
        ),
    )
    analysis = CacheAnalysis(**{
        **base.__dict__,
        "summary": AnalysisSummary(**{**base.summary.__dict__, "sub_workflow_rollup": rollup}),
    })

    text = render_text(analysis, all_rows=True)

    assert "## Per-child analyze-cache commands" not in text
    # Breakdown line correctly reports "0 in 0 sub-workflows".
    assert "in 0 sub-workflows)" in text


def test_render_text_unpriced_model_includes_child_workflow_attribution() -> None:
    row = PerCallRow(**{
        **_row("draft", 30).__dict__,
        "model": "ollama/local",
        "workflow_path": "/abs/child.pflow.md",
    })
    base = _make_analysis(rows=[row], actually_paid=0.1, no_cache=0.1, partial=True, unavailable=("ollama/local",))
    summary = AnalysisSummary(**{
        **base.summary.__dict__,
        "unavailable_models_by_workflow": {"/abs/child.pflow.md": ("ollama/local",)},
    })
    text = render_text(CacheAnalysis(**{**base.__dict__, "summary": summary}))
    assert "ollama/local (in child)" in text


def test_render_json_includes_rollup_workflow_paths_and_unavailable_models_by_workflow(
    tmp_path: Path,
) -> None:
    from pflow.core.prompt_cache_analysis.analyze import analyze
    from tests.shared.markdown_utils import write_workflow_file
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    parent_path = tmp_path / "parent.pflow.md"
    child_path = tmp_path / "child.pflow.md"
    child_path_str = str(child_path)
    parent_path_str = str(parent_path)

    child_ir = {
        "inputs": {"topic": {"type": "string", "description": "Topic"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "params": {
                    "model": "ollama/local",
                    "prompt": "Make a draft about ${topic}",
                },
            },
        ],
    }
    write_workflow_file(child_ir, child_path, title="Child")

    parent_ir = {
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "draft",
                "type": "llm",
                "params": {
                    "model": "anthropic/claude-sonnet-4-5",
                    "prompt": "Brief: ${topic}",
                },
            },
            {
                "id": "call-child",
                "type": "workflow",
                "params": {
                    "workflow": child_path_str,
                    "inputs": {"topic": "${topic}"},
                },
            },
        ],
    }

    builder = TraceFixtureBuilder()
    trace_data = {
        "format_version": "2.2.0",
        "workflow_path": parent_path_str,
        "nodes": [
            builder.llm_event(
                "draft",
                model="anthropic/claude-sonnet-4-5",
                input_tokens=1000,
                output_tokens=100,
                cost_usd=0.05,
            ),
            builder.workflow_event(
                "call-child",
                [
                    builder.llm_event(
                        "draft",
                        model="ollama/local",
                        input_tokens=900,
                        output_tokens=90,
                        cost_usd=None,
                    ),
                ],
                workflow_path=child_path_str,
            ),
        ],
    }
    analysis = analyze(
        parent_ir,
        parameters={"topic": "hello"},
        workflow_path=parent_path_str,
        base_path=tmp_path,
        trace_path=_write_trace(tmp_path / "parent-child-unpriced-trace.json", trace_data),
        auto_load_trace=False,
        memo_cache=None,
    )

    payload = render_json(analysis)

    rollup = payload["summary"]["sub_workflow_rollup"]
    assert rollup is not None
    assert any(entry["workflow_path"].endswith("child.pflow.md") for entry in rollup["per_workflow"])
    unavailable = payload["summary"]["unavailable_models_by_workflow"]
    assert unavailable is not None
    child_key = next(key for key in unavailable if key and key.endswith("child.pflow.md"))
    assert "ollama/local" in unavailable[child_key]
    assert any(row["workflow_path"] and row["workflow_path"].endswith("child.pflow.md") for row in payload["per_call"])


def test_discrepancy_message_includes_workflow_scope() -> None:
    """Defends: the discrepancy diagnostic template includes
    ``workflow_path_short`` so the rendered message names the child
    scope (``draft in child``).
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.discrepancy",
        node_id="draft",
        workflow_path_short="child",
        affected_workflow="/abs/child.pflow.md",
        root_cause="key_mismatch",
        root_cause_summary="Upstream value changed",
        suggestion="Re-run analyze-cache.",
        predicted_cache_key="a",
        actual_cache_key="b",
    )
    assert "draft in child" in diag.message


# ---------------------------------------------------------------------------
# Phase 6 (4.x minor-additive): root vs sub-workflow LLM node count split
# in JSON. Single source of truth — text and JSON renderers both read from
# ``summary.root_llm_node_count`` / ``summary.sub_workflow_llm_node_count``.
# ---------------------------------------------------------------------------


def test_json_emits_root_and_sub_workflow_llm_node_counts() -> None:
    """JSON consumers see the same root/sub-workflow count split that text
    renders — text was computing this on-the-fly from ``analysis.per_call``,
    silently dropping the breakdown when serializing.

    End-to-end via ``analyze()`` on the committed 3-deep fixture so the
    test exercises ``_build_summary``'s real assignment, not a hand-built
    ``AnalysisSummary``. Mutation contract: drop the field assignment in
    ``_build_summary`` and both JSON and text fall back to defaults
    (``root_llm_node_count == 0``) — this test fails on the JSON side.
    """
    from pathlib import Path

    from pflow.core.prompt_cache_analysis.analyze import analyze
    from pflow.execution.workflow_resolver import resolve_workflow

    fixture_dir = Path("tests/fixtures/cache_analysis")
    parent_path = fixture_dir / "parent-3deep.pflow.md"
    trace_path = fixture_dir / "parent-child-grandchild-trace.json"
    resolved = resolve_workflow(str(parent_path))
    analysis = analyze(
        resolved.ir,
        parameters={"topic": "hello"},
        workflow_path=resolved.file_path,
        base_path=parent_path.parent,
        trace_path=trace_path,
        memo_cache=None,
    )

    payload = render_json(analysis)
    assert payload["summary"]["total_llm_nodes_estimated"] == 3
    assert payload["summary"]["total_llm_invocations_estimated"] == 3
    assert payload["summary"]["dynamic_batch_node_count"] == 0
    assert "total_llm_calls_estimated" not in payload["summary"]
    assert payload["summary"]["root_llm_node_count"] == 1
    assert payload["summary"]["sub_workflow_llm_node_count"] == 2

    # Text renderer reads from the same fields — single source of truth.
    text = render_text(analysis, all_rows=True)
    assert "(1 in parent-3deep.pflow.md, 2 in 2 sub-workflows)" in text


# ----------------------------------------------------------------------
# Task 159 follow-up — prompt-body cleanup hint surfacing
# ----------------------------------------------------------------------


def test_suggested_block_carries_prompt_body_cleanup_for_greenfield() -> None:
    """End-to-end: drive ``analyze()`` against a greenfield workflow whose
    LLM nodes share a template ref. The analyzer should suggest declaring the
    ref in ## Cache AND surface that the same ref still appears in each
    node's prompt body (so agents pasting the suggestion know to also
    remove the inline reference)."""
    from pflow.core.prompt_cache_analysis.analyze import analyze

    workflow_ir = {
        "inputs": {"concept": {"type": "string"}},
        "nodes": [
            {
                "id": "node-a",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "About ${concept}: ..."},
            },
            {
                "id": "node-b",
                "type": "llm",
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "More on ${concept}: ..."},
            },
        ],
    }
    result = analyze(workflow_ir, parameters={"concept": "x " * 6000}, workflow_path="/abs/x.pflow.md")

    assert result.suggested_blocks, "Analyzer should detect shared context"
    block = result.suggested_blocks[0]
    # Both nodes are getting prompt_cache: [concept], and both still have
    # ${concept} inline — cleanup hint should fire for both.
    assert block.prompt_body_cleanup == {
        "node-a": ["concept"],
        "node-b": ["concept"],
    }


def test_declared_cache_workflow_does_not_emit_suggested_blocks_note() -> None:
    """When a workflow already declares ``## Cache``, the analyzer used to
    emit a Note reading ``Suggested-blocks: workflow already declares
    ## Cache; steady-state (partial-block) suggestions deferred to v1.x.``
    That string leaks analyzer-internal vocabulary (``Suggested-blocks``,
    ``partial-block``, ``v1.x``) into agent-facing output without giving
    the agent any actionable signal. Workflows with a declared ``## Cache``
    block simply skip suggestion emission — neutral state, not Notes
    content.

    Mutation test: re-add the ``notes.append("Suggested-blocks: workflow
    already declares ## Cache; ...")`` line in
    ``_skip_suggested_blocks_for_declared_cache``; this test fails because
    the literal returns to the rendered Notes section.
    """
    from pflow.core.prompt_cache_analysis.analyze import analyze

    workflow_ir = {
        "inputs": {"concept": {"type": "string"}},
        "cache": {
            "items": [{"name": "concept", "var": "concept", "prose_before": "Concept:\n"}],
        },
        "nodes": [
            {
                "id": "node-a",
                "type": "llm",
                "prompt_cache": ["concept"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "About ${concept}: ..."},
            },
            {
                "id": "node-b",
                "type": "llm",
                "prompt_cache": ["concept"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "More on ${concept}: ..."},
            },
        ],
    }
    result = analyze(workflow_ir, parameters={"concept": "x"}, workflow_path="/abs/x.pflow.md")
    text = render_text(result)

    assert "Suggested-blocks:" not in text
    assert "partial-block" not in text
    assert "deferred to v1.x" not in text
    # Defense: the workflow still skips suggestion emission. If a future
    # change re-enables suggestions for declared-cache workflows, the
    # test above would still pass — assert the documented short-circuit
    # behavior holds.
    assert not result.suggested_blocks


def test_suggested_block_skips_prompt_body_cleanup_when_cache_already_declared() -> None:
    """When the workflow already has a ``## Cache`` block,
    ``_populate_suggested_blocks`` short-circuits — no SuggestedBlock at all,
    so prompt_body_cleanup never gets populated. Pins the documented scope
    boundary (Phase 2 covers greenfield only; brownfield is covered by the
    Phase 1 validator ERROR at validate time)."""
    from pflow.core.prompt_cache_analysis.analyze import analyze

    workflow_ir = {
        "inputs": {"concept": {"type": "string"}},
        "cache": {
            "items": [{"name": "concept", "var": "concept", "prose_before": "Concept:\n"}],
        },
        "nodes": [
            {
                "id": "node-a",
                "type": "llm",
                "prompt_cache": ["concept"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "About ${concept}: ..."},
            },
            {
                "id": "node-b",
                "type": "llm",
                "prompt_cache": ["concept"],
                "params": {"model": "anthropic/claude-sonnet-4-5", "prompt": "More on ${concept}: ..."},
            },
        ],
    }
    result = analyze(workflow_ir, parameters={"concept": "x"}, workflow_path="/abs/x.pflow.md")

    # Brownfield short-circuits suggested_blocks; the validator's ERROR is
    # what catches the bug in this case (covered by Phase 1 tests).
    assert not result.suggested_blocks


def test_render_text_emits_also_remove_from_prompt_body_line() -> None:
    """Renderer surfaces the cleanup hint inline under each
    ``- prompt_cache: [...]`` line."""
    from pflow.core.prompt_cache_analysis.types import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(
            SuggestedBlockChunk(
                name="concept",
                var="${concept}",
                size_tokens_est=500,
                prose_placeholder="The concept:",
            ),
        ),
        per_node_assignments={"write": ["concept"]},
        estimated_savings_usd=None,
        prompt_body_cleanup={"write": ["concept"]},
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})
    text = render_text(analysis)

    assert "- prompt_cache: [concept]" in text
    assert "also remove from prompt body: ${concept}" in text


def test_render_text_omits_cleanup_line_when_no_overlaps() -> None:
    """When prompt_body_cleanup is empty for a node, the renderer does NOT
    emit the cleanup line — keeps the suggested block clean for greenfield
    workflows that don't need cleanup."""
    from pflow.core.prompt_cache_analysis.types import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(
            SuggestedBlockChunk(
                name="concept",
                var="${concept}",
                size_tokens_est=500,
                prose_placeholder="The concept:",
            ),
        ),
        per_node_assignments={"write": ["concept"]},
        estimated_savings_usd=None,
        prompt_body_cleanup={},
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})
    text = render_text(analysis)

    assert "- prompt_cache: [concept]" in text
    assert "also remove from prompt body" not in text


def test_render_json_includes_prompt_body_cleanup_key() -> None:
    """JSON shape carries ``prompt_body_cleanup`` per suggested block (MCP
    consumers read the same shape; agents acting on suggested_blocks[] see
    the cleanup hint without round-tripping through the text renderer)."""
    from pflow.core.prompt_cache_analysis.types import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(
            SuggestedBlockChunk(
                name="concept",
                var="${concept}",
                size_tokens_est=500,
                prose_placeholder="The concept:",
            ),
        ),
        per_node_assignments={"write": ["concept"]},
        estimated_savings_usd=None,
        prompt_body_cleanup={"write": ["concept"]},
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})
    payload = render_json(analysis)

    assert "suggested_blocks" in payload
    block_dict = payload["suggested_blocks"][0]
    assert "prompt_body_cleanup" in block_dict
    assert block_dict["prompt_body_cleanup"] == {"write": ["concept"]}


def test_render_text_includes_per_node_threshold_statuses() -> None:
    from pflow.core.prompt_cache_analysis.types import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(
            SuggestedBlockChunk(
                name="concept",
                var="${concept}",
                size_tokens_est=512,
                prose_placeholder="The concept:",
            ),
        ),
        per_node_assignments={
            "above": ["concept"],
            "below": ["concept"],
            "varies": ["concept"],
            "unknown": ["concept"],
        },
        estimated_savings_usd=0.0,
        per_node_thresholds={
            "above": {
                "model": "anthropic/claude-sonnet-4-5",
                "model_state": "resolved",
                "min_tokens": 1024,
                "total_tokens": 1500,
                "meets_threshold": True,
            },
            "below": {
                "model": "anthropic/claude-sonnet-4-5",
                "model_state": "resolved",
                "min_tokens": 1024,
                "total_tokens": 512,
                "meets_threshold": False,
            },
            "varies": {
                "model": None,
                "model_state": "heterogeneous",
                "min_tokens": None,
                "total_tokens": None,
                "meets_threshold": None,
            },
            "unknown": {
                "model": None,
                "model_state": "unknown",
                "min_tokens": None,
                "total_tokens": None,
                "meets_threshold": None,
            },
        },
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})

    text = render_text(analysis)

    assert "threshold: 1500 tokens / 1024 (anthropic/claude-sonnet-4-5)" in text
    assert "threshold: 512 tokens / 1024 (anthropic/claude-sonnet-4-5)" in text
    assert "BELOW THRESHOLD" in text
    assert "threshold: varies per item (heterogeneous model)" in text
    assert "threshold: unable to estimate (no run data; first run will populate)" in text


def test_render_json_includes_per_node_thresholds() -> None:
    from pflow.core.prompt_cache_analysis.types import SuggestedBlock, SuggestedBlockChunk

    block = SuggestedBlock(
        target_file="/abs/x.pflow.md",
        ttl="5m",
        chunks=(
            SuggestedBlockChunk(
                name="concept", var="${concept}", size_tokens_est=512, prose_placeholder="The concept:"
            ),
        ),
        per_node_assignments={"write": ["concept"]},
        estimated_savings_usd=0.0,
        per_node_thresholds={
            "write": {
                "model": "anthropic/claude-sonnet-4-5",
                "model_state": "resolved",
                "min_tokens": 1024,
                "total_tokens": 512,
                "meets_threshold": False,
            }
        },
    )
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "suggested_blocks": (block,)})

    block_dict = render_json(analysis)["suggested_blocks"][0]

    assert block_dict["per_node_thresholds"] == {
        "write": {
            "model": "anthropic/claude-sonnet-4-5",
            "model_state": "resolved",
            "min_tokens": 1024,
            "total_tokens": 512,
            "meets_threshold": False,
        }
    }


def test_render_json_includes_cache_creation_and_read_tokens() -> None:
    """Per_call rows surface raw trace cache token splits."""
    row = PerCallRow(**{
        **_row("cached-call", 80).__dict__,
        "cache_creation_input_tokens": 1500,
        "cache_read_input_tokens": 8062,
        "data_source": "trace",
    })
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "per_call": (row,)})
    payload = render_json(analysis)
    row_dict = payload["per_call"][0]

    assert row_dict["cache_creation_input_tokens"] == 1500
    assert row_dict["cache_read_input_tokens"] == 8062

    # Pin key adjacency so future dict refactors don't silently scatter the
    # cache-related fields. JSON 5.0 places raw trace splits before projections.
    keys = list(row_dict.keys())
    assert keys.index("cache_creation_input_tokens") == keys.index("output_data_source") + 1
    assert keys.index("cache_read_input_tokens") == keys.index("cache_creation_input_tokens") + 1
    assert keys.index("cached_now_tokens_estimated") == keys.index("cache_read_input_tokens") + 1
    assert keys.index("cache_configured") == keys.index("cached_now_tokens_estimated") + 1
    assert keys.index("cache_active") == keys.index("cache_configured") + 1
    assert keys.index("cache_ready") == keys.index("cache_active") + 1
    assert keys.index("cache_opportunity") == keys.index("cache_ready") + 1
    assert keys.index("data_source") == keys.index("cache_opportunity") + 1


def test_render_json_per_call_cache_tokens_null_on_greenfield() -> None:
    """No trace data means cache token fields are null."""
    row = PerCallRow(**{
        **_row("greenfield-call", 80).__dict__,
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": None,
        "data_source": "estimator",
    })
    base = _make_analysis()
    analysis = CacheAnalysis(**{**base.__dict__, "per_call": (row,)})
    payload = render_json(analysis)
    row_dict = payload["per_call"][0]

    assert row_dict["cache_creation_input_tokens"] is None
    assert row_dict["cache_read_input_tokens"] is None


# ---------------------------------------------------------------------------
# B-6: conditional "ordered by impact" header
# ---------------------------------------------------------------------------


def test_recommended_actions_drops_ordered_by_impact_when_no_savings() -> None:
    """B-6: header must not claim ordering when no action has positive savings.

    Greenfield-without-resolved-models (every savings_usd=None) used to render
    "## Recommended actions (ordered by impact)" — agents reading "ordered"
    next to "savings unavailable" lose trust in the ranking. Mutation contract:
    hardcode header to the qualified form → this test fails.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        make_diagnostic(
            "cache.shared-context-undeclared",
            node_count=2,
            shared_chunks=["concept"],
            affected_workflow="/abs/path/song-creator.pflow.md",
            savings_usd=None,
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))
    assert "## Recommended actions" in text
    assert "(ordered by impact)" not in text


def test_recommended_actions_keeps_ordered_by_impact_when_priced() -> None:
    """B-6 negative: header retains qualifier when at least one action has savings.

    Mutation contract: hardcode header to unqualified → this test fails.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        make_diagnostic(
            "cache.shared-context-undeclared",
            node_count=2,
            shared_chunks=["concept"],
            affected_workflow="/abs/path/song-creator.pflow.md",
            savings_usd=0.05,
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))
    assert "## Recommended actions" in text
    assert "ordered by impact)" in text


# ---------------------------------------------------------------------------
# A-4: section-mapped headline counts + inline section header counts
# ---------------------------------------------------------------------------


def _rename_diag(*, source: str, target: str, parent: str, child: str, line: int):
    """Build a single ``cache.cross-workflow-rename-detected`` diagnostic."""
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    return make_diagnostic(
        "cache.cross-workflow-rename-detected",
        parent_workflow=parent,
        child_workflow=child,
        parent_value_expr=source,
        child_input_name=target,
        line_in_parent=line,
        parent_node_id="parent-step",
    )


def _prose_mismatch_diag(*, parent: str, child: str, chunk: str):
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    return make_diagnostic(
        "cache.cross-workflow-prose-mismatch",
        node_id=None,
        parent_workflow=parent,
        child_workflow=child,
        chunk_name=chunk,
        parent_prose="Parent prose",
        child_prose="Child prose",
    )


def test_summary_renders_section_mapped_counts_when_both_present() -> None:
    """Headline groups by section so the count maps to what the agent will see.

    Mutation contract: hardcode the headline back to the legacy
    ``N opportunities (X warnings, Y info)`` shape; this test fails because
    "recommended action" / "cross-workflow boundary finding" no longer
    appear and the agent can't anchor to either downstream section.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        make_diagnostic(
            "cache.shared-context-undeclared",
            node_count=2,
            shared_chunks=["concept"],
            affected_workflow="/abs/path/song-creator.pflow.md",
            savings_usd=0.05,
        ),
        _prose_mismatch_diag(
            parent="/abs/song-creator.pflow.md",
            child="/abs/chorus-chooser.pflow.md",
            chunk="concept",
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))

    # Headline groups by section.
    assert "1 recommended action + 1 cross-workflow boundary finding" in text
    # Severity-keyed legacy shape gone.
    assert "opportunities (" not in text
    assert " info)" not in text
    # Section-anchor counts surface in each header.
    assert "## Recommended actions (1, ordered by impact)" in text
    assert "## Sub-workflow boundaries (1)" in text


def test_summary_suppresses_count_line_on_clean_workflow() -> None:
    """No findings, no blocking, no truncation note → no count line at all.

    The legacy renderer always emitted ``0 opportunities (0 warnings, 0 info)``
    even when there was nothing to surface; that line is pure noise.

    Mutation contract: re-add an unconditional ``opportunities`` line; this
    test fails because the substring leaks back in on clean workflows.
    """
    text = render_text(_make_analysis())

    assert "recommended action" not in text
    assert "cross-workflow boundary finding" not in text
    assert "opportunities" not in text


def test_summary_renders_blocking_only_when_no_opportunities() -> None:
    """Blocking-errors line stands on its own when no recs / boundaries fire.

    Mutation contract: drop the ``has_opportunities`` gate (always emit the
    count line); this test fails because ``0 recommended actions`` would
    leak under the blocking line.
    """
    from pflow.core.diagnostic import Diagnostic, Severity
    from pflow.core.prompt_cache_analysis.types import AnalysisSummary

    base = _make_analysis()
    summary = AnalysisSummary(**{**base.summary.__dict__, "blocking_errors": 1})
    err = Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Cache Failure",
        node_id="bad-call",
        message="Order mismatch",
        id="cache.order-mismatch",
    )
    analysis = CacheAnalysis(**{**base.__dict__, "summary": summary, "warnings": (err,)})
    text = render_text(analysis)

    assert "1 error blocking" in text
    # No count line — only the blocking line should appear in the count block.
    assert "recommended action" not in text
    assert "cross-workflow boundary finding" not in text


def test_section_header_drops_rollup_for_prose_mismatch_only() -> None:
    """Prose-mismatches don't collapse (1-per-finding) — section header
    shows the rendered count only, no rollup.

    Mutation contract: include prose-mismatches in the rollup count K; this
    test fails because ``covering`` leaks in even when no rename collapse
    happened.
    """
    diags = [
        _prose_mismatch_diag(
            parent="/abs/song-creator.pflow.md",
            child=f"/abs/{child_name}.pflow.md",
            chunk="concept",
        )
        for child_name in ("chorus-chooser", "review-emotional-architecture")
    ]
    text = render_text(_make_analysis(warnings=diags))

    assert "## Sub-workflow boundaries (2)" in text
    assert "covering" not in text


def test_section_header_counts_only_prose_mismatches_when_renames_present() -> None:
    """Rename diagnostics do not affect the text section count."""
    children = [
        ("/abs/chorus-chooser.pflow.md", 97),
        ("/abs/review-emotional-architecture.pflow.md", 124),
        ("/abs/review-ai-tells.pflow.md", 239),
        ("/abs/review-cliche.pflow.md", 239),
        ("/abs/review-genre.pflow.md", 239),
        ("/abs/review-accuracy.pflow.md", 239),
        ("/abs/review-rhyme.pflow.md", 239),
        ("/abs/review-narrative.pflow.md", 124),
        ("/abs/review-imagery.pflow.md", 124),
        ("/abs/review-stranger.pflow.md", 124),
    ]
    rename_diags = [
        _rename_diag(
            source="creative-direction.response",
            target="creative_direction",
            parent="/abs/song-creator.pflow.md",
            child=child_path,
            line=line,
        )
        for child_path, line in children
    ]
    # Add 7 more renames sharing the same source to push raw count to 17 and
    # keep the group count at 1 (single (source, target) pair).
    for child_path, line in children[:7]:
        rename_diags.append(
            _rename_diag(
                source="creative-direction.response",
                target="creative_direction",
                parent="/abs/song-creator.pflow.md",
                child=child_path,
                line=line,
            )
        )
    prose_diags = [
        _prose_mismatch_diag(
            parent="/abs/song-creator.pflow.md",
            child=f"/abs/{child}.pflow.md",
            chunk="concept",
        )
        for child in ("review-narrative", "review-imagery")
    ]
    text = render_text(_make_analysis(warnings=rename_diags + prose_diags))

    assert "## Sub-workflow boundaries (2)" in text
    assert "covering" not in text
    assert "creative_direction" not in text
    assert "line 239" not in text


def test_summary_singular_form_for_one_boundary_finding() -> None:
    """Singular ``1 cross-workflow boundary finding`` renders when only one
    rendered prose-mismatch entry exists (no recs).

    Mutation contract: drop the singular branch in ``_append_summary_counts``;
    this test fails because the headline would emit
    ``1 cross-workflow boundary findings`` (plural) for the single-entry case.
    """
    diag = _prose_mismatch_diag(
        parent="/abs/song-creator.pflow.md",
        child="/abs/chorus-chooser.pflow.md",
        chunk="concept",
    )
    text = render_text(_make_analysis(warnings=[diag]))

    assert "1 cross-workflow boundary finding" in text
    assert "1 cross-workflow boundary findings" not in text


def test_recommended_actions_header_includes_count() -> None:
    """Section header always carries an inline count when it renders.

    Mutation contract: drop ``count`` from either branch in
    ``_render_recommended_actions``; this test fails on the relevant case.
    """
    from pflow.core.prompt_cache_analysis.warning_catalog import make_diagnostic

    # No-savings branch: ``(N)`` only.
    no_savings = [
        make_diagnostic(
            "cache.shared-context-undeclared",
            node_count=2,
            shared_chunks=["concept"],
            affected_workflow="/abs/path/song-creator.pflow.md",
            savings_usd=None,
        ),
    ]
    text = render_text(_make_analysis(warnings=no_savings))
    assert "## Recommended actions (1)" in text
    assert "(1, ordered by impact)" not in text

    # With-savings branch: ``(N, ordered by impact)``.
    with_savings = [
        make_diagnostic(
            "cache.shared-context-undeclared",
            node_count=2,
            shared_chunks=["concept"],
            affected_workflow="/abs/path/song-creator.pflow.md",
            savings_usd=0.05,
        ),
    ]
    text = render_text(_make_analysis(warnings=with_savings))
    assert "## Recommended actions (1, ordered by impact)" in text


# ---------------------------------------------------------------------------
# B-11: heterogeneous suffix uses "; plus" separator
# ---------------------------------------------------------------------------


def _analysis_with_heterogeneous_paths(rows: list[PerCallRow], paths: tuple[str, ...]) -> CacheAnalysis:
    """Override ``heterogeneous_model_node_paths`` on a synthetic analysis.

    The synthetic ``_make_analysis`` builder defaults this field to () per
    Pitfall #19 (production code overwrites it). Tests that exercise the
    "Heterogeneous:" header line populate it explicitly via this helper.
    """
    base = _make_analysis(rows=rows)
    summary = dataclasses.replace(
        base.summary,
        heterogeneous_model_node_paths=paths,
        heterogeneous_model_node_count=len(paths),
    )
    return dataclasses.replace(base, summary=summary)


def test_heterogeneous_renders_on_dedicated_line_single_node() -> None:
    """Cluster D N-3: heterogeneous batch sub-workflows render on their own
    ``Heterogeneous:`` header line — not appended to the scale line as a
    "; plus ..." suffix. Always-on-its-own-line keeps the heterogeneous
    concept findable everywhere.

    Mutation contract: revert ``_format_heterogeneous_line`` to inline
    suffix concatenation → "Heterogeneous:" disappears from output.
    """
    row = PerCallRow(**{**_row("generate-chorus-options", 50).__dict__, "model_is_heterogeneous": True, "model": ""})
    analysis = _analysis_with_heterogeneous_paths([row], ("generate-chorus-options",))
    text = render_text(analysis)
    assert "  Heterogeneous: generate-chorus-options (model varies per batch item)" in text
    # Negative — the old "; plus ..." suffix shape must NOT appear.
    assert "; plus " not in text


def test_heterogeneous_renders_on_dedicated_line_multi_node() -> None:
    """Cluster D N-3: multi-node case renders all heterogeneous nodes on
    one ``Heterogeneous:`` line via plain ``', '.join`` — no separate
    "1 vs N" code path or "with N nodes" prose.

    Mutation contract: re-introduce a count word (e.g., "with 3 nodes
    with") → assertion fails.
    """
    rows = [
        PerCallRow(**{**_row(name, 50).__dict__, "model_is_heterogeneous": True, "model": ""})
        for name in ("a", "b", "c")
    ]
    analysis = _analysis_with_heterogeneous_paths(rows, ("a", "b", "c"))
    text = render_text(analysis)
    assert "  Heterogeneous: a, b, c (model varies per batch item)" in text
    # Negative — the older count-word prose must NOT appear.
    assert "with 3 nodes with" not in text
    assert "; plus 3 nodes" not in text


def test_no_heterogeneous_line_when_no_heterogeneous_nodes() -> None:
    """Cluster D N-3 edge case: the ``Heterogeneous:`` line is suppressed
    entirely when no heterogeneous batch sub-workflow exists — the empty
    case must NOT render an empty stub line.
    """
    text = render_text(_make_analysis(rows=[_row("homogeneous-node", 50)]))
    assert "Heterogeneous:" not in text


# ---------------------------------------------------------------------------
# B-8 + L-7: tokens column thousands separator + 7-char width
# ---------------------------------------------------------------------------


def test_per_call_row_tokens_use_thousands_separator() -> None:
    """B-8 + L-7: 6-digit token counts render with comma separator and align
    in a stable 7-char column.

    Lyrics-generator showed `tokens=266728` (raw 6-digit) blowing past the
    pre-fix 5-char column. Fix: `:>7,` covers up to 999,999 with comma.

    Mutation contract: drop ',' from format spec → assertion fails.
    """
    # all_rows=True so the 80%-ratio row isn't hidden by the default filter.
    row = PerCallRow(**{**_row("write-lyrics", 80).__dict__, "input_tokens_estimated": 266_728})
    text = render_text(_make_analysis(rows=[row]), all_rows=True)
    cells = _per_call_cells(text, "write-lyrics")
    assert cells[2] == "266,728"
    # Negative — raw integer must NOT appear.
    assert "tokens=266728" not in text


def test_below_provider_min_note_renders_for_projected_undeclared_rows() -> None:
    """Projected undeclared cacheable bytes below the provider minimum need row context.

    Mutation contract: removing the projected-tier predicate from
    ``_below_provider_min_note_by_row_key`` makes this note leak to trace rows,
    while removing the helper entirely makes this assertion fail.
    """
    row = PerCallRow(**{
        **_row("summarize", 0).__dict__,
        "model": "anthropic/claude-haiku-4-5",
        "cacheable_tokens_estimated": 1,
        "cacheable_data_source": "parameters",
        "declared_prompt_cache": None,
    })

    text = render_text(_make_analysis(rows=[row]), all_rows=True)
    cells = _per_call_cells_by_header(text, "summarize")
    assert cells["notes"] == "declare prompt_cache; below provider min (need ≥4,096 for this model)"


def test_below_provider_min_note_silent_when_cache_declared() -> None:
    row = PerCallRow(**{
        **_row("summarize", 0).__dict__,
        "model": "anthropic/claude-haiku-4-5",
        "cacheable_tokens_estimated": 1,
        "cacheable_data_source": "parameters",
        "declared_prompt_cache": ["article"],
    })

    text = render_text(_make_analysis(rows=[row]), all_rows=True)
    cells = _per_call_cells_by_header(text, "summarize")
    assert "below provider min" not in cells["notes"]


def test_below_provider_min_note_silent_when_tokens_above_min() -> None:
    row = PerCallRow(**{
        **_row("summarize", 0).__dict__,
        "model": "anthropic/claude-haiku-4-5",
        "cacheable_tokens_estimated": 5000,
        "cacheable_data_source": "parameters",
        "declared_prompt_cache": None,
    })

    text = render_text(_make_analysis(rows=[row]), all_rows=True)
    cells = _per_call_cells_by_header(text, "summarize")
    assert "below provider min" not in cells["notes"]


def test_below_provider_min_note_silent_for_trace_tier() -> None:
    row = PerCallRow(**{
        **_row("summarize", 0).__dict__,
        "model": "anthropic/claude-haiku-4-5",
        "cacheable_tokens_estimated": 1,
        "cacheable_data_source": "trace",
        "declared_prompt_cache": None,
    })

    text = render_text(_make_analysis(rows=[row]), all_rows=True)
    cells = _per_call_cells_by_header(text, "summarize")
    assert "below provider min" not in cells["notes"]


def test_per_call_explainer_mentions_provider_minimum() -> None:
    row = PerCallRow(**{
        **_row("summarize", 0).__dict__,
        "cacheable_tokens_estimated": 1,
        "cacheable_data_source": "parameters",
    })

    text = render_text(_make_analysis(rows=[row]), all_rows=True)
    assert "below provider min" in text


def test_per_call_row_renders_cached_now_for_tier_1_active() -> None:
    """Tier 1 active provider-cache evidence renders in ``cached_now``.

    Mutation contract: make ``_cell_cached_now`` always return em dash; this
    test fails because the trace-backed cache token count disappears.
    """
    row = PerCallRow(**{
        **_row("write-lyrics", 80).__dict__,
        "input_tokens_estimated": 266_728,
        "cacheable_tokens_estimated": 213_382,
        "declared_prompt_cache": ["prefix"],
        "cacheable_data_source": "trace",
    })
    text = render_text(_make_analysis(rows=[row]), all_rows=True)
    cells = _per_call_cells_by_header(text, "write-lyrics")
    assert cells["cached_now"] == "213,382"
    assert cells["ready"] == "213,382"


def test_per_call_row_renders_could_cache_for_tier_2_potential() -> None:
    """Tier 2 candidate projections render in ``could_cache``.

    Mutation contract: make ``_cell_could_cache`` return em dash for memo
    source rows; this test fails because the projected opportunity vanishes.
    """
    row = PerCallRow(**{
        **_row("score-choruses", 80).__dict__,
        "input_tokens_estimated": 266_728,
        "cacheable_tokens_estimated": 213_382,
        "cacheable_data_source": "memo",
    })
    text = render_text(_make_analysis(rows=[row]), all_rows=True)
    cells = _per_call_cells_by_header(text, "score-choruses")
    assert "cached_now" not in cells
    assert cells["ready"] == "213,382"
    assert cells["upside"] == "213,382"


def test_per_call_row_renders_em_dash_for_inactive_tier() -> None:
    """Rows populate only the applicable cache-token tier today.

    Mutation contract: render zero or question mark instead of em dash for
    inactive tier cells; this test fails because inactive tiers no longer have
    a distinct visual contract.
    """
    row = PerCallRow(**{
        **_row("rewrite-emotional", 80).__dict__,
        "input_tokens_estimated": 266_728,
        "cacheable_tokens_estimated": 63_009,
        "declared_prompt_cache": ["prefix"],
        "cacheable_data_source": "trace",
    })
    text = render_text(_make_analysis(rows=[row]), all_rows=True)
    cells = _per_call_cells_by_header(text, "rewrite-emotional")
    assert cells["cached_now"] == "63,009"
    assert cells["ready"] == "63,009"


def test_per_call_row_unmeasurable_cacheable_renders_question_mark() -> None:
    """Unmeasurable cacheable tokens render as a plain question mark in the
    ``could_cache`` column; table widths handle alignment.

    Mutation contract: return em dash for unavailable cacheable evidence; this
    test fails because honest-unmeasurable and inactive-tier become conflated.
    """
    row = PerCallRow(**{
        **_row("greenfield", 50).__dict__,
        "cacheable_tokens_estimated": None,
        "cache_ratio_pct": None,
    })
    text = render_text(_make_analysis(rows=[row]), all_rows=True)
    cells = _per_call_cells_by_header(text, "greenfield")
    assert "could_cache" not in cells
    assert cells["notes"].endswith("no trace recorded — run with --report to populate this row")


def test_renderer_never_emits_cd_commands() -> None:
    """pflow never tells agents to ``cd``: every suggested command must run
    from the invocation cwd.

    Agents fire parallel Bash calls and cannot reliably share cwd state
    across invocations; even sequentially the agent's cwd tracker is the
    only frame they can navigate paths from. To point at a file or a
    workflow, use ``_display_path_from_cwd`` to get a cwd-relative (or
    absolute, when outside cwd) path. To point at an edit target, use
    ``_display_edit_target``. Both already anchor at cwd.

    Mutation contract: re-add a ``lines.append(f"    cd ...")`` shape to
    any renderer module under ``prompt_cache_analysis/``; this test fails because
    the literal string ``"    cd "`` reappears in production rendering
    source.
    """
    cache_analysis_dir = Path(__file__).resolve().parents[2] / "src" / "pflow" / "core" / "prompt_cache_analysis"
    forbidden = re.compile(r'["\']\s{0,8}cd\s+[^"\']*["\']')
    offenders: list[str] = []
    for source_file in sorted(cache_analysis_dir.glob("*.py")):
        text = source_file.read_text()
        # Strip triple-quoted docstrings/comments so historical references
        # explaining WHY we don't emit cd don't trip the check.
        stripped = re.sub(r'""".*?"""', "", text, flags=re.DOTALL)
        stripped = re.sub(r"'''.*?'''", "", stripped, flags=re.DOTALL)
        for line_no, line in enumerate(stripped.splitlines(), 1):
            code, _, _ = line.partition("#")
            if forbidden.search(code):
                offenders.append(f"{source_file.name}:{line_no}: {line.strip()}")
    assert not offenders, (
        "Renderer emits ``cd`` commands; agents cannot track cwd state across calls. "
        "Use ``_display_path_from_cwd`` for cwd-relative paths instead:\n  " + "\n  ".join(offenders)
    )
