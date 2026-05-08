"""F2.3 — text and JSON renderer tests.

Locks the agent-facing format contracts:
- Empty-array contract for derived-view arrays.
- Tri-state cost rendering (priced / partial / unavailable — never silent ``$0.00``).
- Default-hide-clean per-call rule + ``--all-rows`` override.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from pflow.core.cache_analysis import (
    render_json,
    render_text,
)
from pflow.core.cache_analysis.analyze import (
    AnalysisSummary,
    CacheAnalysis,
    CostDelta,
    CrossWorkflowFindings,
    PerCallRow,
    ProjectionExclusion,
    SubWorkflowRollup,
    SubWorkflowRollupEntry,
    TraceUnexecutedLLMRow,
    _format_workflow_run_command,
)
from pflow.core.cache_analysis.cost_estimation import CostTier
from pflow.core.diagnostic import Diagnostic, Severity


def _make_analysis(
    *,
    rows: list[PerCallRow] | None = None,
    warnings: list[Diagnostic] | None = None,
    notes: list[str] | None = None,
    actually_paid: float | None = None,
    no_cache: float | None = None,
    first_run_with_cache: float | None = None,
    rerun: float | None = None,
    partial: bool = False,
    unavailable: tuple[str, ...] = (),
    projection_exclusions: tuple[ProjectionExclusion, ...] = (),
    actual_delta_unavailable_reason: str | None = None,
    workflow_path: str = "/abs/x.pflow.md",
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
    first_run_delta = _test_delta(no_cache, first_run_with_cache, "no_cache", "first_run")
    rerun_delta = _test_delta(no_cache, rerun, "no_cache", "rerun")
    actual_delta = _test_delta(no_cache, actually_paid, "no_cache", "actual")
    if actual_delta_unavailable_reason is not None:
        actual_delta = CostDelta(
            None,
            None,
            "unavailable",
            "no_cache",
            "actual",
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
        trace_path=None,
        summary=AnalysisSummary(
            actually_paid_usd=actually_paid,
            actually_paid_tier=CostTier.TRACE if actually_paid is not None else CostTier.UNAVAILABLE,
            no_cache_hypothetical_usd=no_cache,
            first_run_with_cache_hypothetical_usd=first_run_with_cache,
            rerun_within_ttl_hypothetical_usd=rerun,
            first_run_delta=first_run_delta,
            rerun_delta=rerun_delta,
            actual_vs_no_cache_delta=actual_delta,
            trace_coverage="complete" if actually_paid is not None else "none",
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
            total_input_tokens_estimated=sum(r.input_tokens_estimated for r in rows),
            total_cacheable_tokens_estimated=sum(r.cacheable_tokens_estimated or 0 for r in rows),
            models_in_use=tuple(sorted({r.model for r in rows if r.model})),
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
    "evidence_scope",
    "observed_models_in_trace",
    "unavailable_models_by_workflow",
    "heterogeneous_model_node_count",
    "heterogeneous_model_node_paths",
    "sub_workflow_rollup",
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
                    id="cache.below-min-tokens",
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
            actual_delta_unavailable_reason="trace_coverage_partial",
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
        from pflow.core.cache_analysis.analyze import analyze
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
    from pflow.core.cache_analysis import JSON_FORMAT_VERSION

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
        id="cache.below-min-tokens",
        message="X: declared cache content is ~512 tokens, below claude/min of 1024",
        suggestions=["Add chunks"],
        context={"category": "cache_warning", "model": "claude-sonnet-4-5"},
    )
    result = render_json(_make_analysis(warnings=[diag]))
    assert result["warnings"][0]["id"] == "cache.below-min-tokens"
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
    from pflow.core.cache_analysis.analyze import AnalysisSummary

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
    from pflow.core.cache_analysis.analyze import AnalysisSummary

    base = _make_analysis(workflow_path="/abs/x.pflow.md")
    summary = AnalysisSummary(**{
        **base.summary.__dict__,
        "first_run_delta": CostDelta(0.50, None, "savings", "no_cache", "first_run"),
    })
    analysis = CacheAnalysis(**{**base.__dict__, "summary": summary})
    text = render_text(analysis)

    assert "Absolute cost figures need a prior run." in text
    assert "Suggested:  pflow run /abs/x.pflow.md" in text


def test_text_summary_renders_blocking_errors_categorically() -> None:
    """Top-10% pattern (mypy / rustc / clippy / ruff): errors render
    categorically separate from opportunities. The data model already
    separates ``blocking_errors`` from ``actionable_opportunities``;
    the renderer must match. An agent skimming the count needs to see
    "blocking" categorically — lumping errors into the opportunity count
    hides them.

    Mutation test: drop the ``if s.blocking_errors > 0`` block in
    ``_render_summary``; this test fails because "1 error blocking" no
    longer appears, and an agent could read "2 opportunities" and miss
    the structural blocker.
    """
    from pflow.core.cache_analysis.analyze import AnalysisSummary
    from pflow.core.diagnostic import Diagnostic, Severity

    base = _make_analysis()
    summary = AnalysisSummary(**{
        **base.summary.__dict__,
        "blocking_errors": 1,
        "actionable_opportunities": 2,
        "warnings_count": 2,
        "info_count": 0,
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

    # Blocking-errors line surfaces categorically.
    assert "1 error blocking" in text, (
        "Summary should render '1 error blocking' on its own line when "
        "blocking_errors > 0. Without this, agents skimming the count see "
        "'2 opportunities' and miss the ERROR-severity finding entirely."
    )
    assert "## Blocking errors (must fix before save and run)" in text
    # Opportunity line still present, distinct from the error line.
    assert "2 opportunities (2 warnings, 0 info)" in text
    # The blocking line precedes the opportunity line (errors first).
    assert text.index("1 error blocking") < text.index("2 opportunities")


def test_text_summary_omits_blocking_line_when_no_errors() -> None:
    """Conditional emission: greenfield workflows (zero ERRORs) must not
    show "0 errors blocking" — that's noise, not signal.

    Mutation test: change the conditional to an unconditional emission;
    this test fails on a greenfield analysis.
    """
    from pflow.core.cache_analysis.analyze import AnalysisSummary

    base = _make_analysis()
    summary = AnalysisSummary(**{
        **base.summary.__dict__,
        "blocking_errors": 0,
        "actionable_opportunities": 1,
        "warnings_count": 0,
        "info_count": 1,
    })
    analysis = CacheAnalysis(**{**base.__dict__, "summary": summary})
    text = render_text(analysis)

    assert "blocking" not in text
    assert "1 opportunity (0 warnings, 1 info)" in text


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
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

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
    from pflow.core.cache_analysis.analyze import analyze

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
    from pflow.core.cache_analysis.analyze import _starter_prose_for_ref

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
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

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

    The parser rejects any value other than ``5m`` or ``1h``; surfacing that
    beside the generated ``- ttl:`` line prevents authoring-time guesses.
    """
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

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
    assert "`ttl` accepts only `5m` or `1h`" in text


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


def test_text_default_hides_clean_rows_above_80_pct() -> None:
    rows = [_row("clean1", 90), _row("clean2", 95), _row("dirty", 30)]
    text = render_text(_make_analysis(rows=rows))
    assert "dirty" in text
    assert "clean1" not in text
    assert "clean2" not in text
    assert "Hidden: 2 nodes" in text


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

    assert "tokens=    ?" in text
    assert "tokens=    3" not in text


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

    assert "tokens=    3" in text
    assert "tokens=    ?" not in text


def test_text_partial_trace_labels_executed_scope() -> None:
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
            "trace_coverage": "partial",
            "evidence_scope": "partial_trace_executed_subset",
            "trace_llm_nodes_static": 2,
            "trace_llm_nodes_executed": 1,
            "trace_unexecuted_llm_rows": (TraceUnexecutedLLMRow("/abs/x.pflow.md", "skipped"),),
        }),
    })

    text = render_text(analysis)

    assert "Evidence: partial trace (1 of 2 LLM nodes executed)" in text
    assert "Trace-backed costs below cover executed nodes only." in text
    assert "Actually paid (executed trace):" in text
    assert "Cost without caching (executed):" in text
    assert "Cost on rerun (executed, within TTL):" in text
    assert "Showing 1 executed LLM node; 1 unexecuted row hidden (--all-rows shows everything)." in text
    assert "all-clean rows hidden" not in text
    assert "Workflow-design recommendations suppressed for partial trace evidence." in text


def test_json_partial_trace_exposes_evidence_scope_and_observed_models(tmp_path: Path) -> None:
    from pflow.core.cache_analysis.analyze import analyze
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
        trace_path=_write_trace(tmp_path / "partial-trace.json", trace_data),
        auto_load_trace=False,
        memo_cache=None,
    )

    payload = render_json(analysis)

    assert payload["summary"]["evidence_scope"] == "partial_trace_executed_subset"
    assert payload["summary"]["observed_models_in_trace"] == ["gemini/a", "gemini/b"]
    assert payload["per_call"][0]["observed_models"] == ["gemini/a", "gemini/b"]
    assert payload["per_call"][0]["observed_call_count"] == 2
    unexecuted = payload["summary"]["trace_unexecuted_llm_rows"]
    assert any(row["node_path"] == "review" for row in unexecuted)


def test_json_summary_exposes_projection_exclusions_and_delta_reason(tmp_path: Path) -> None:
    from pflow.core.cache_analysis.analyze import analyze

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
    assert delta["kind"] == "unavailable"
    assert delta["unavailable_reason"] == "projection_exclusions"
    assert payload["summary"]["heterogeneous_model_node_count"] >= 1
    assert "generate" in payload["summary"]["heterogeneous_model_node_paths"]


def test_text_summary_explains_projection_excluded_actual_delta() -> None:
    exclusion = ProjectionExclusion(
        workflow_path="/abs/x.pflow.md",
        node_path="generate",
        reason="heterogeneous_model",
        actual_cost_usd=0.03,
    )
    analysis = _make_analysis(
        actually_paid=0.05,
        no_cache=0.02,
        partial=True,
        projection_exclusions=(exclusion,),
        actual_delta_unavailable_reason="projection_exclusions",
    )

    text = render_text(analysis)

    assert "Actually paid (trace):       ~$0.05 (trace)" in text
    assert "Actually paid (trace):       ~$0.05 (partial) (trace)" not in text
    assert "Cost without caching (projected subset):" in text
    assert "Cost on rerun (within TTL, projected subset):" in text
    assert "Actual trace delta:         unavailable (projection excludes generate)" in text
    assert "Actual trace delta:         adds" not in text


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
    review_lines = [line for line in text.splitlines() if "review" in line and "model=" in line]
    assert review_lines, "expected a per-call row line for review"
    assert "dynamic-before-static" in review_lines[0]
    # Critical: the redundant ``cache.`` prefix is gone from the inline column.
    assert "cache.dynamic-before-static" not in review_lines[0]


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
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

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
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        make_diagnostic(
            "cache.below-min-tokens",
            node_id="draft",
            affected_workflow="/abs/workflows/parent.pflow.md",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
            evidence_kind="predicted",
            provider_note="",
        ),
        make_diagnostic(
            "cache.below-min-tokens",
            node_id="draft",
            affected_workflow="/abs/workflows/child.pflow.md",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
            evidence_kind="predicted",
            provider_note="",
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))
    assert "draft in parent.pflow.md" in text
    assert "draft in child.pflow.md" in text


def test_text_recommended_actions_single_workflow_omits_scope_suffix() -> None:
    """Root-workflow findings keep the old compact ``<node>`` scope line."""
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        make_diagnostic(
            "cache.below-min-tokens",
            node_id="rewrite",
            affected_workflow="/abs/x.pflow.md",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
            evidence_kind="predicted",
            provider_note="",
        ),
    ]
    text = render_text(_make_analysis(warnings=warnings))
    assert "     rewrite\n" in f"{text}\n"
    assert "rewrite in " not in text


def test_json_recommended_actions_per_node_finding_carries_scope_workflow() -> None:
    """JSON keeps both the symbol and its workflow location for consumers that
    dispatch on same-id nodes across parent/child workflows.
    """
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    warnings = [
        make_diagnostic(
            "cache.below-min-tokens",
            node_id="draft",
            affected_workflow="/abs/workflows/parent.pflow.md",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
            evidence_kind="predicted",
            provider_note="",
        ),
        make_diagnostic(
            "cache.below-min-tokens",
            node_id="draft",
            affected_workflow="/abs/workflows/child.pflow.md",
            model="claude-sonnet-4-5",
            cacheable_tokens=512,
            min_tokens=1024,
            evidence_kind="predicted",
            provider_note="",
        ),
    ]
    result = render_json(_make_analysis(warnings=warnings))
    action_scopes = {
        (action["node_id"], action["scope_workflow"])
        for action in result["recommended_actions"]
        if action["warning_id"] == "cache.below-min-tokens"
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
            id="cache.below-min-tokens",
            node_id="test-call",
            message="Below minimum",
        ),
    ]
    result = render_json(_make_analysis(warnings=warnings))
    assert [a["warning_id"] for a in result["blocking_errors"]] == ["cache.order-mismatch"]
    assert [a["rank"] for a in result["blocking_errors"]] == [1]


def test_json_blocking_errors_preserve_message_and_suggestions() -> None:
    warnings = [
        Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            node_id="deep-think",
            message="Unknown parameter 'thinking_effort' on node 'deep-think' (type: llm).",
            suggestions=["Did you mean 'reasoning_effort'?"],
        ),
    ]
    result = render_json(_make_analysis(warnings=warnings))
    assert result["blocking_errors"][0]["message"] == warnings[0].message
    assert result["blocking_errors"][0]["suggestions"] == ["Did you mean 'reasoning_effort'?"]


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
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

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
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

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
    # Above-threshold value renders the dollar figure on its rank line.
    assert "saves ~$0.42/run" in text
    assert "-$0.42/run" not in text
    # Bug D regression: NO "-$0.00/run" placeholder anywhere. (Note: a broad
    # "$0.00" check would false-trigger on "$0.0012" — match the precise
    # placeholder string instead.)
    assert "-$0.00/run" not in text
    # Stage-1 UX pass: the ``[cache.X]`` bracket prefix is gone from rank lines.
    assert "[cache.shared-context-undeclared]" not in text
    assert "[cache.dynamic-before-static]" not in text
    assert "[cache.batch-prewarm-recommended]" not in text


# ---------------------------------------------------------------------------
# Text renderer — notes
# ---------------------------------------------------------------------------


def test_text_renders_notes_in_locked_order() -> None:
    notes = [
        "Found 2 2.0.0 traces matching this workflow but skipped...",
        "Found 1 unparseable trace files in ~/.pflow/debug/...",
        "Gemini telemetry note: ...",
    ]
    text = render_text(_make_analysis(notes=notes))
    # Each note appears in order in the text output.
    pos_2_0 = text.find("2.0.0 traces")
    pos_unparseable = text.find("unparseable")
    pos_gemini = text.find("Gemini telemetry")
    assert pos_2_0 < pos_unparseable < pos_gemini


# ---------------------------------------------------------------------------
# CP2 (#11) — Cross-workflow rendering surfaces node_id + chunks
# ---------------------------------------------------------------------------


def _make_sub_workflow_cache_diag(
    node_id: str,
    child_input_name: str,
    child_workflow: str = "/abs/child.pflow.md",
) -> Diagnostic:
    """Build the child-scoped sub-workflow cache diagnostic."""
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    child_basename = child_workflow.rsplit("/", 1)[-1] if "/" in child_workflow else child_workflow
    return make_diagnostic(
        "cache.sub-workflow-cache-undeclared",
        node_count=6,
        affected_workflow=child_workflow,
        savings_usd=None,
        parent_workflow="/abs/parent.pflow.md",
        child_workflow=child_workflow,
        child_workflow_basename=child_basename,
        parent_value_expr=child_input_name,
        child_input_name=child_input_name,
        parent_node_id=node_id,
        line_in_parent=0,
    )


def test_text_cross_workflow_section_uses_sub_workflow_boundaries_header() -> None:
    """CP5 #3 — section renamed from 'Cross-workflow alignment (Tier 2)' to
    'Sub-workflow boundaries' so agents don't have to know what 'Tier 2' is.

    Stage 0.2: cross-workflow section renders rename + prose-mismatch findings
    only; value-flow surfaces in Recommended actions. Use a rename diag to
    trigger the section.

    Mutation test: revert the header in ``_render_cross_workflow``; this test
    fails because the agent-facing section name regresses to internal pflow
    architecture jargon.
    """
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.cross-workflow-rename-detected",
        parent_workflow="/abs/song-creator.pflow.md",
        child_workflow="/abs/chorus-chooser.pflow.md",
        parent_value_expr="concept_brief",
        child_input_name="creative_brief",
        line_in_parent=42,
        parent_node_id="parent-step",
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
    assert "sub-workflows do not inherit the parent cache block" in text
    assert "either workflow's ## Cache" not in text
    assert "share cached bytes across the boundary" not in text
    # Stage-1 UX pass: per-finding ``[cache.X]`` footer is gone.
    assert "[cache.sub-workflow-cache-undeclared]" not in text


def test_text_cross_workflow_rename_finding_full_format() -> None:
    """Stage-1 final UX pass: rename findings render as headline + scope + reason.

    Layout: rank line is the catalog headline (e.g. ``Cross-workflow rename
    — `concept_brief` ↔ `creative_brief```), scope line is ``parent → child
     (line N)``, reason paragraph is the descriptive message body.

    Pre-fix: 4-line block with bullet ``→ Rename`` action + ``[cache.X]``
    footer. Post-fix: catalog-driven headline + scope + reason. Same
    Diagnostic data, restructured presentation.

    Mutation test: revert ``_format_boundary_finding`` to drop the headline
    source; this test fails because the discriminator-bearing rename arrow
    (``↔``) disappears from the rank line.
    """
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.cross-workflow-rename-detected",
        parent_workflow="/abs/song-creator.pflow.md",
        child_workflow="/abs/chorus-chooser.pflow.md",
        parent_value_expr="concept_brief",
        child_input_name="creative_brief",
        line_in_parent=42,
        parent_node_id="parent-step",
    )
    text = render_text(_make_analysis(warnings=[diag]))
    # Headline rank line carries the rename arrow + both names.
    assert "Cross-workflow rename" in text
    assert "`concept_brief`" in text
    assert "`creative_brief`" in text
    # Scope line: parent → child  (line N).
    assert "song-creator → chorus-chooser" in text
    assert "(line 42)" in text
    # Stage-1 UX pass: bullet ``→ Rename`` action and ``[cache.X]`` footer
    # are gone — the headline carries the action and section context disambiguates.
    assert "→ Rename" not in text
    assert "[cache.cross-workflow-rename-detected]" not in text


def test_text_cross_workflow_prose_mismatch_finding_full_format() -> None:
    """Stage-1 final UX pass: prose-mismatch findings render as headline +
    scope + reason.

    Layout: rank line is the catalog headline (``Cross-workflow prose
    mismatch — align `concept` in both ## Cache blocks``), scope line is
    ``parent → child`` (no ``(line N)`` for prose mismatches), reason
    paragraph is the descriptive message body.

    Pre-fix: 4-line block with ``Chunk `X```, ``→ Pick one prose label``
    action + ``[cache.X]`` footer. Post-fix: catalog-driven headline +
    scope + reason.

    Mutation test: revert ``_format_boundary_finding`` to drop the headline
    source; this test fails because the discriminator (chunk_name in the
    headline) disappears from the rank line.
    """
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

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
    # Headline rank line carries the discriminator-bearing chunk name.
    assert "Cross-workflow prose mismatch" in text
    assert "`concept`" in text
    # Scope line: parent → child (no `(line N)` for prose mismatch).
    assert "song-creator → chorus-chooser" in text
    # Stage-1 UX pass: ``→ Pick one prose label`` bullet + ``[cache.X]``
    # footer are gone — the headline carries the action.
    assert "→ Pick one prose label" not in text
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
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

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
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

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
    """CP5 #6 — when 2+ models, header lists them comma-separated.

    Mutation test: revert to count-only rendering; this test fails because
    individual model names disappear from the header.
    """
    row_a = PerCallRow(**{**_row("a", 50).__dict__, "model": "anthropic/claude-sonnet-4-5"})
    row_b = PerCallRow(**{**_row("b", 50).__dict__, "model": "gemini/gemini-3.1-pro-preview"})
    text = render_text(_make_analysis(rows=[row_a, row_b]))
    assert "2 models:" in text
    assert "anthropic/claude-sonnet-4-5" in text
    assert "gemini/gemini-3.1-pro-preview" in text


def test_text_header_shows_static_batch_invocations() -> None:
    row = PerCallRow(**{**_row("batch-review", 50).__dict__, "is_batch": True, "batch_size_estimated": 8})
    text = render_text(_make_analysis(rows=[row]))
    assert "1 LLM node, ~8 invocations using anthropic/claude-sonnet-4-5" in text


def test_text_header_shows_dynamic_batch_invocation_unknown() -> None:
    row = PerCallRow(**{**_row("batch-review", 50).__dict__, "is_batch": True, "batch_size_estimated": None})
    text = render_text(_make_analysis(rows=[row]))
    assert ("1 LLM node, invocation count unavailable (1 dynamic batch node) using anthropic/claude-sonnet-4-5") in text


def test_text_header_handles_no_model_resolved() -> None:
    """CP5 #6 — when LLM nodes exist but no model resolves, surface the
    actionable hint inline with the count.

    Mutation test: drop the empty-models branch from ``_format_scale_line``;
    this test fails because the hint text doesn't appear.
    """
    row = PerCallRow(**{**_row("n1", 50).__dict__, "model": ""})
    text = render_text(_make_analysis(rows=[row]))
    assert "1 LLM node (no model resolved" in text
    assert "settings.default_model" in text


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
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

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
            id="cache.below-min-tokens",
            node_id="test-call",
            message="Below minimum",
        ),
    ]
    text = render_text(_analysis_with_warnings(warnings))
    assert text.index("## Summary") < text.index("## Blocking errors")
    assert text.index("## Blocking errors") < text.index("## Recommended actions")


def test_text_blocking_errors_section_omitted_when_no_errors() -> None:
    warnings = [
        Diagnostic(
            severity=Severity.WARNING,
            source="cache_analyzer",
            id="cache.below-min-tokens",
            node_id="test-call",
            message="Below minimum",
        )
    ]
    text = render_text(_analysis_with_warnings(warnings))
    assert "## Blocking errors" not in text
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
    blocking = _section(text, "## Blocking errors")
    assert "Order mismatch" in blocking
    assert "cache.order-mismatch" in blocking
    assert "-$2.00/run" not in blocking
    assert "savings unavailable" not in blocking


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
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

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
    from pflow.core.cache_analysis import analyze

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
    assert "## Blocking errors (must fix before save and run)" in text
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
    blocking = _section(text, "## Blocking errors")
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


def test_text_per_call_src_renders_as_confidence_labels() -> None:
    """CP4 #9 — internal data_source values map to user-facing confidence labels.

    JSON keeps the granular 4-tier (`per_call[].data_source` is unchanged
    machine consumers).

    Option C note: ``estimator`` and ``heuristic`` rows fail
    ``_row_has_real_data`` and would normally be hidden — pin them visible by
    setting ``declared_prompt_cache=["foo"]`` (steady-state branch passes the
    filter regardless of data_source).

    Mutation test: revert ``_data_source_display`` mapping to passthrough;
    this test fails because ``src=estimator`` re-appears in the rendered text.
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
    assert "src=high" in text  # trace + memo
    assert "src=medium" in text  # estimator
    assert "src=low" in text  # heuristic
    # Internal values must NOT leak into rendered text:
    assert "src=estimator" not in text
    assert "src=heuristic" not in text
    assert "src=trace" not in text
    assert "src=memo" not in text


def test_text_per_call_src_passes_through_unknown_values() -> None:
    """CP4 #9 — unknown source values pass through unmapped (fail-loud).

    A future tier (e.g. ``inferred``) surfaces verbatim until the map gains a
    row. This is intentional: silently mapping unknown values to a default
    confidence would mislead agents during the rollout window.

    Option C note: ``mystery`` is an unknown data_source so the row would be
    filtered out — pin it visible via ``declared_prompt_cache=["foo"]``
    (steady-state branch passes the filter regardless of data_source).

    Mutation test: replace the dict ``.get(value, value)`` with ``.get(value,
    "low")`` (a permissive default); this test fails because ``src=mystery``
    becomes ``src=low``, hiding the new tier.
    """
    rows = [_row("X", 50)]
    rows[0] = PerCallRow(**{**rows[0].__dict__, "data_source": "mystery", "declared_prompt_cache": ["foo"]})
    text = render_text(_make_analysis(rows=rows))
    assert "src=mystery" in text  # passes through unchanged


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
    # Mode-specific explainers must NOT render either (the section is gone).
    assert "Actual cache ratios" not in text
    assert "Projected cache ratios" not in text
    assert "No shared context detected" not in text


def test_text_per_call_explainer_post_run_greenfield_says_projected() -> None:
    """Option C: post-run greenfield workflows (no ``prompt_cache:`` declared
    but rows have memo/trace data) show the "Projected cache ratios from prior
    run data." explainer.

    Two explainer modes survive Option C's row filter:
    - **Steady-state** (any row has ``declared_prompt_cache``):
      "Actual cache ratios from declared `prompt_cache:` subsets."
    - **Post-run greenfield** (memo/trace rows, no declared):
      "Projected cache ratios from prior run data."

    The pure-greenfield "no shared context" branch was removed — those rows
    are filtered out before reaching the explainer (see
    ``test_text_pure_greenfield_hides_per_call_section_with_explanatory_note``).

    Mutation test: invert ``is_steady_state`` detection or change the
    post-run explainer string; this test fails because the wrong explainer
    renders for a memo-data row with no declared subset.
    """
    # ``_row("n1", 50)`` defaults to data_source="memo", declared_prompt_cache=None
    # — the post-run greenfield path that survives the Option C filter.
    rows = [_row("n1", 50)]
    text = render_text(_make_analysis(rows=rows))
    assert "## Per-call cache report" in text
    assert "Projected cache ratios from prior run data." in text
    # Other modes' explainers must NOT render here.
    assert "Actual cache ratios" not in text
    assert "No shared context detected" not in text


def test_text_per_call_explainer_steady_state_says_actual_ratios() -> None:
    """CP4 #7 — steady-state workflows (≥1 node has declared prompt_cache)
    show the "Actual cache ratios" explainer.

    Mutation test: invert the ``is_steady_state`` detection; this test fails.
    """
    rows = [_row("n1", 0), _row("n2", 75)]
    rows[1] = PerCallRow(**{**rows[1].__dict__, "declared_prompt_cache": ["concept", "concept_brief"]})
    text = render_text(_make_analysis(rows=rows))
    assert "Actual cache ratios" in text
    assert "Current ratios" not in text or "pre-cache" not in text


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
    assert "Confidence: medium_from_memo" in text
    assert "(2 of 2 nodes)" in text


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
    assert "(1 in parent.pflow.md, 1 in 1 sub-workflow: child)" in text
    assert "## Sub-workflow drill-in" in text
    assert "pflow analyze-cache /abs/child.pflow.md" in text


def test_render_text_drill_in_omitted_for_single_workflow() -> None:
    text = render_text(_make_analysis(rows=[_row("draft", 30)]), all_rows=True)
    assert "## Sub-workflow drill-in" not in text
    assert "(called by" not in text


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
    from pflow.core.cache_analysis.analyze import analyze
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
    from pflow.core.cache_analysis.warning_catalog import make_diagnostic

    diag = make_diagnostic(
        "cache.discrepancy",
        node_id="draft",
        trace_path="/trace.json",
        workflow_path_short="child",
        affected_workflow="/abs/child.pflow.md",
        predicted_pct=100,
        predicted_label="hit",
        actual_pct=0,
        root_cause="key_mismatch",
        root_cause_summary="Upstream value changed",
        cache_age_sec=None,
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

    from pflow.core.cache_analysis.analyze import analyze
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
    assert "(1 in parent-3deep.pflow.md, 2 in 2 sub-workflows: child-3deep, grandchild)" in text


# ----------------------------------------------------------------------
# Task 159 follow-up — prompt-body cleanup hint surfacing
# ----------------------------------------------------------------------


def test_suggested_block_carries_prompt_body_cleanup_for_greenfield() -> None:
    """End-to-end: drive ``analyze()`` against a greenfield workflow whose
    LLM nodes share a template ref. The analyzer should suggest declaring the
    ref in ## Cache AND surface that the same ref still appears in each
    node's prompt body (so agents pasting the suggestion know to also
    remove the inline reference)."""
    from pflow.core.cache_analysis.analyze import analyze

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


def test_suggested_block_skips_prompt_body_cleanup_when_cache_already_declared() -> None:
    """When the workflow already has a ``## Cache`` block,
    ``_populate_suggested_blocks`` short-circuits — no SuggestedBlock at all,
    so prompt_body_cleanup never gets populated. Pins the documented scope
    boundary (Phase 2 covers greenfield only; brownfield is covered by the
    Phase 1 validator ERROR at validate time)."""
    from pflow.core.cache_analysis.analyze import analyze

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
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

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
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

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
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

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
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

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
    from pflow.core.cache_analysis.analyze import SuggestedBlock, SuggestedBlockChunk

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
    # cache-related fields. Plan specified placement after cache_ratio_pct
    # and before data_source.
    keys = list(row_dict.keys())
    assert keys.index("cache_creation_input_tokens") == keys.index("cache_ratio_pct") + 1
    assert keys.index("cache_read_input_tokens") == keys.index("cache_creation_input_tokens") + 1
    assert keys.index("data_source") == keys.index("cache_read_input_tokens") + 1


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
