# Phase 4 — Renderer Test Fidelity (Pitfall #19 Defense)

> **Atomic implementation plan for Task 159 PR #378 review-fix #4.**
> Optimized for an AI agent implementing in isolation. No ambiguity. Read end-to-end before starting.

---

## Context: Why This Change Exists

### The problem

`tests/test_core/test_cache_analysis_renderers.py` (2,280 LOC, 75 tests) has a synthetic builder `_make_analysis(...)` at lines 32–137 that constructs `CacheAnalysis` / `AnalysisSummary` dataclasses **directly**, bypassing the production `analyze(...)` entry point. **67 of the 75 tests** consume this builder; only ~5 drive `analyze(...)` end-to-end.

Five tests use the synthetic builder to assert on summary content the builder **doesn't faithfully model**. They override fields via `AnalysisSummary(**{**base.summary.__dict__, "evidence_scope": "partial_trace_executed_subset", ...})` — synthetically setting non-default values that production would compute. The tests pass against fictional-but-self-consistent state. If the production analyzer's logic for setting those fields drifts, the renderer tests **don't catch it.**

### Why it matters

This is the **most common bug class on this branch**. The implementation log catalogues 8+ instances under the name "Pitfall #19" — synthetic test fixtures matching a buggy code shape; production code path differs; tests pass against fake state; agents trust green tests. Every instance shipped silent breakage that only an adversarial CLI drill or paid smoke test caught:

1. `cache_source` mislabel (memo HITs reported as `in_process`)
2. `NamespacedSharedStore` type taxonomy (dotted-path chunks silently dropped)
3. `events`/`nodes` typo (Tier-1 trace data unreachable)
4. inline workflow `workflow_path` divergence (MCP-only)
5. `SchemaValidationError` propagation
6. per-call hide-clean ignored analysis-wide warnings
7. cache ratio > 100%
8. `child_count == 0` filter on unresolved IRs

The renderer test file is the **last unprotected surface**. Six fields on `AnalysisSummary` rely on dataclass defaults in the synthetic builder while production overwrites them with computed values. The fields are exactly the ones agents read first — `evidence_scope`, `observed_models_in_trace`, `unavailable_models_by_workflow`, `heterogeneous_model_node_count`, `heterogeneous_model_node_paths`, `sub_workflow_rollup`.

### Why the reviewer's prescription was overkill

The PR reviewer prescribed migrating all ~75 tests to drive `analyze(...)` end-to-end. That's wrong-shape: 67 of those tests are about layout, text format, and JSON shape — driving them through `analyze(...)` would slow the suite by ~30× without adding value. Renderers are pure projections; they should be unit-tested against synthetic data **as long as that synthetic data faithfully mirrors what production produces.**

The right shape per `tests/CLAUDE.md` Pitfall #19 doctrine is two layers:

1. **One shape-parity test class** (~80 LOC) that locks the contract structurally — if a new field is added to `AnalysisSummary` and the builder doesn't represent it, every test using the builder fails noisily. Mirrors the existing `TestTraceFixtureBuilderShapeParity` pattern (`tests/test_core/test_trace_tree.py:84-249`).
2. **Three targeted e2e migrations** (~60 LOC each) for the tests that assert on summary content the synthetic builder can't faithfully model. Two of the reviewer's five-test list are non-issues on inspection — see Verification Checkpoints below.

Total: ~260 LOC. Not a 75-test rewrite. Bounded, proportional, and idiomatic for this codebase.

### Intended outcome

After this change:
- **No test in `test_cache_analysis_renderers.py` asserts on `evidence_scope` / `observed_models_in_trace` / `unavailable_models_by_workflow` / `heterogeneous_model_node_*` / `sub_workflow_rollup` via the synthetic builder.** Tests that need these fields drive `analyze(...)`.
- **Adding a new field to `AnalysisSummary` triggers a parity-test failure with a fix message** that names the file, line range, and `_BUILDER_DOCUMENTED_DEFAULTS` constant.
- **The next "drift between synthetic test and production semantics" bug class is caught at unit-test time**, not by an adversarial CLI drill.

---

## Verification Checkpoints (do these BEFORE writing code)

Before touching any file, the implementing agent must confirm three things via read-only inspection. The rest of the plan assumes these hold.

### Checkpoint 1: Test #5 already drives `analyze()` end-to-end

The PR review listed `test_json_emits_root_and_sub_workflow_llm_node_counts` (line 1949) as a migration target. Read the function body. **Expected**: it already calls `analyze(resolved.ir, ...)` against `tests/fixtures/cache_analysis/parent-3deep.pflow.md` + `parent-child-grandchild-trace.json`. If true, **skip this test**; no migration needed.

### Checkpoint 2: Test #1 only asserts on builder-populated fields

The PR review listed `test_text_summary_renders_blocking_errors_categorically` (line 272) as a migration target. Read the function body. **Expected**: it asserts only on `blocking_errors`, `actionable_opportunities`, `warnings_count`, `info_count`. All four are populated correctly by `_make_analysis` from the `warnings` kwarg. The test does mutate `__dict__` to override these counts, but the override values are themselves what the builder would set if given the right `warnings`. If true, **skip this test**; no migration needed. Lock the test by ensuring it's covered by the parity test (any field divergence will show up there).

### Checkpoint 3: Committed parent-child fixture model is priced

For Migration #4 (line 1884), the test asserts on `unavailable_models_by_workflow={"/abs/child.pflow.md": ("ollama/local",)}`. This requires a child workflow using an unpriced model. Read `tests/fixtures/cache_analysis/parent-child-trace.json` — confirm the child's `llm_call.model` is **`anthropic/claude-sonnet-4-5`** (priced). If so, the existing fixture **cannot drive** `unavailable_models_by_workflow` directly. Migration #4 must either:
- (a) **Build IR + trace inline** (using `TraceFixtureBuilder` + `WorkflowTraceCollector`) with an unpriced model in the child, OR
- (b) **Extend `tests/fixtures/cache_analysis/_generate.py`** to add a new fixture variant (e.g., `parent-child-unpriced-trace.json`) and use it.

**Recommended: option (a).** Inline IR + builder is self-contained; the test reads top-to-bottom without forcing readers to chase fixture files. Use option (b) only if the inline shape exceeds ~80 LOC.

If Checkpoint 3 finds the child already uses an unpriced model, use the committed fixture (best case).

---

## Critical Files and Code References

### Files to be modified

| File | Lines | Change |
|---|---|---|
| `tests/test_core/test_cache_analysis_renderers.py` | 32–137 | Add `_BUILDER_DOCUMENTED_DEFAULTS` constant adjacent to `_make_analysis` |
| `tests/test_core/test_cache_analysis_renderers.py` | ~158 (after `_make_analysis`) | Insert `TestMakeAnalysisShapeParity` class (parity test, ~80 LOC) |
| `tests/test_core/test_cache_analysis_renderers.py` | 608–642 | Replace `test_json_partial_trace_exposes_evidence_scope_and_observed_models` body with e2e shape (~60 LOC) |
| `tests/test_core/test_cache_analysis_renderers.py` | 645–671 | Replace `test_json_summary_exposes_projection_exclusions_and_delta_reason` body with e2e shape (~60 LOC) |
| `tests/test_core/test_cache_analysis_renderers.py` | 1884–1914 | Replace `test_render_json_includes_rollup_workflow_paths_and_unavailable_models_by_workflow` body with e2e shape (~80 LOC) |

### Production code referenced (READ ONLY)

- `src/pflow/core/cache_analysis/analyze.py:336-415` — `AnalysisSummary` frozen dataclass (30 fields)
- `src/pflow/core/cache_analysis/analyze.py:419-441` — `CacheAnalysis` frozen dataclass
- `src/pflow/core/cache_analysis/analyze.py:312-324` — `CostDelta` frozen dataclass
- `src/pflow/core/cache_analysis/analyze.py:3562-3713` — `_build_summary` (production overwrite site)
- `src/pflow/core/cache_analysis/analyze.py:3690` — `evidence_scope` overwrite via `_evidence_scope_for_trace_coverage`
- `src/pflow/core/cache_analysis/analyze.py:3704` — `observed_models_in_trace` overwrite
- `src/pflow/core/cache_analysis/analyze.py:3707` — `unavailable_models_by_workflow` overwrite
- `src/pflow/core/cache_analysis/analyze.py:3708-3709` — heterogeneous fields overwrite
- `src/pflow/core/cache_analysis/analyze.py:651-661` — `sub_workflow_rollup` post-construction `dataclasses.replace()`
- `src/pflow/core/cache_analysis/analyze.py:1053` — `analyze(...)` public entry point
- `src/pflow/core/cache_analysis/analyze.py:3738-3743` — `_evidence_scope_for_trace_coverage` (3 enum values: `"static_analysis"` / `"partial_trace_executed_subset"` / `"complete_trace"`)
- `src/pflow/core/cache_analysis/cost_estimation.py:405-446` — `_partition_priced_rows` (4 `ProjectionExclusion.reason` values: `"heterogeneous_model"` / `"unresolved_model"` / `"unpriced_model"` / `"missing_output_tokens"`)

### Test references (READ FOR PATTERN)

- `tests/test_core/test_trace_tree.py:84-249` — `TestTraceFixtureBuilderShapeParity` — pattern reference for shape parity (uses hand-listed key sets because trace events are dicts; **our parity test must use `dataclasses.fields()` introspection** since `AnalysisSummary` is a frozen dataclass)
- `tests/test_core/test_cache_analysis_renderers.py:381` — `test_analyze_emits_starter_prose_placeholder_end_to_end` — existing inline-IR e2e pattern in the same file
- `tests/test_core/test_cache_analysis_renderers.py:1949` — `test_json_emits_root_and_sub_workflow_llm_node_counts` — existing committed-fixture e2e pattern (use as template for Migration #4 if Checkpoint 3 finds the existing fixture works)
- `tests/test_core/test_cache_analysis_renderers.py:1555` — `test_text_brownfield_error_diagnostic_visible_in_blocking_errors_not_recommended_actions` — existing inline-IR e2e with `auto_load_trace=False`
- `tests/CLAUDE.md` Pitfall #19 — doctrine reference

### Reusable utilities (READ + USE)

- `tests/shared/trace_fixture_builder.py::TraceFixtureBuilder` — methods:
  - `llm_event(node_id, *, cost_usd, input_tokens, cache_creation_input_tokens, cache_read_input_tokens, ...)` — fresh LLM call event
  - `cached_llm_event_with_call(...)` — memo hit (production shape; do NOT use the `cached_llm_event_thin` variant — flagged for renaming/removal in a sibling commit)
  - `batch_event(node_id, items=[...])` — dynamic batch wrapper
  - `heterogeneous_workflow_batch_event(node_id, items=[(child_path, sub_events), ...])` — sub-workflow batch
- `tests/shared/llm_mock.py::MockLLMClient.set_response(model, schema, response_dict, *, cache_creation_input_tokens, cache_read_input_tokens)` — staged provider telemetry (only needed if the migration drives a real workflow run, which Phase 4 does NOT — we only need `analyze(...)`)
- `src/pflow/runtime/cache.py::MemoizationCache(db_path)` — instantiate with `tmp_path / "cache.db"` for tests; populate via `memo_cache.put(cache_key, ..., output, ...)`
- `src/pflow/execution/workflow_resolver.py::resolve_workflow(path_str) -> ResolvedWorkflow` — reads `.pflow.md` files; for inline IR pass dict directly to `analyze()`

---

## Implementation

### Step 1: Add `_BUILDER_DOCUMENTED_DEFAULTS` constant

**Location**: `tests/test_core/test_cache_analysis_renderers.py`, immediately after the `_make_analysis` function ends (~line 138, before `_test_delta`).

```python
# Fields where _make_analysis intentionally relies on the AnalysisSummary
# dataclass default value while production analyze() overwrites with a computed
# value. Tests that assert on these fields MUST drive a real analyze(...) call
# rather than _make_analysis(...). See Pitfall #19 in tests/CLAUDE.md and the
# TestMakeAnalysisShapeParity class below.
#
# When you add a field to AnalysisSummary:
#   - If _make_analysis should populate it (e.g., new cost atom) → add a kwarg
#     and pass it through; do NOT add to this set.
#   - If production computes it from analyze() inputs (trace, IR, memo) and
#     the synthetic builder cannot faithfully model it → add to this set AND
#     migrate any test asserting on the field to drive analyze(...).
_BUILDER_DOCUMENTED_DEFAULTS: frozenset[str] = frozenset({
    "evidence_scope",                  # _evidence_scope_for_trace_coverage
    "observed_models_in_trace",        # aggregated from row.observed_models
    "unavailable_models_by_workflow",  # _unavailable_models_by_workflow(rows)
    "heterogeneous_model_node_count",  # detected from model_is_heterogeneous
    "heterogeneous_model_node_paths",  # detected from model_is_heterogeneous
    "sub_workflow_rollup",             # _build_sub_workflow_rollup post-replace
})
```

**Verify**: the set has exactly 6 entries matching the field names above. No `partial_cost_usd` (builder accepts it), no `root_llm_node_count` (builder computes it), no `projection_exclusions` (builder accepts it).

### Step 2: Add `TestMakeAnalysisShapeParity` class

**Location**: same file, immediately after the constant from Step 1.

The class has **two methods** with distinct mutation contracts:

```python
class TestMakeAnalysisShapeParity:
    """Locks _make_analysis against drift from production analyze().

    When AnalysisSummary grows a field, this class fails noisily so a
    contributor must either (a) populate it in _make_analysis or (b) add it
    to _BUILDER_DOCUMENTED_DEFAULTS (signaling that tests asserting on it
    must migrate to e2e). Mirrors TestTraceFixtureBuilderShapeParity in
    test_trace_tree.py:84-249, adapted for a frozen dataclass via
    dataclasses.fields() introspection.

    See Pitfall #19 in tests/CLAUDE.md for the doctrine.
    """

    def test_builder_field_set_matches_dataclass_minus_documented_defaults(
        self,
    ) -> None:
        """Every AnalysisSummary field must be either populated by
        _make_analysis OR in _BUILDER_DOCUMENTED_DEFAULTS.

        Mutation contract: add a new field to AnalysisSummary without
        updating _make_analysis or _BUILDER_DOCUMENTED_DEFAULTS — this test
        fails with a message naming the unrepresented field and pointing
        at line 32-137 of this file.
        """
        import dataclasses

        # Probe 1: empty kwargs. Reveals which fields the builder leaves at
        # the dataclass default (i.e., fields whose value happens to equal
        # the default when _make_analysis is called with no inputs).
        empty = _make_analysis()
        # Probe 2: all knobs set. Reveals which fields the builder controls
        # via kwargs (a kwarg-set field will diverge from default when set).
        loaded = _make_analysis(
            actually_paid=0.05,
            no_cache=0.10,
            first_run_with_cache=0.07,
            rerun=0.03,
            partial=True,
            unavailable=("custom/model",),
            projection_exclusions=(_make_exclusion(),),
            actual_delta_unavailable_reason="trace_coverage_partial",
        )

        all_fields = {f.name for f in dataclasses.fields(AnalysisSummary)}

        # A field is "represented by the builder" if either probe produces
        # a non-default value for it. Required fields (no default) are
        # always represented by definition.
        def _at_default(summary: AnalysisSummary, field: dataclasses.Field) -> bool:
            value = getattr(summary, field.name)
            if field.default is not dataclasses.MISSING:
                return value == field.default
            if field.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
                return value == field.default_factory()  # type: ignore[misc]
            return False  # required field; always populated

        unrepresented = {
            f.name
            for f in dataclasses.fields(AnalysisSummary)
            if _at_default(empty.summary, f) and _at_default(loaded.summary, f)
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
            f"Fix: either extend _make_analysis (lines 32-137 of "
            f"test_cache_analysis_renderers.py) to populate the new field, "
            f"or add it to _BUILDER_DOCUMENTED_DEFAULTS and migrate any "
            f"test asserting on the field to drive analyze(...) end-to-end. "
            f"See Pitfall #19 in tests/CLAUDE.md."
        )

    def test_documented_defaults_get_overwritten_by_production(
        self, tmp_path: Path
    ) -> None:
        """Drives a real analyze() against an IR contrived to exercise each
        documented-default field. Asserts that production produces a
        non-default value for each. Catches the case where a field was
        added to the allowlist and then the production overwrite was
        accidentally deleted — the allowlist would silently grow stale.

        Mutation contract: delete the assignment at analyze.py:3690
        (evidence_scope) — this test fails because evidence_scope reverts
        to "static_analysis" default.
        """
        # Per-field assertions; each uses a minimal IR/trace combination
        # that triggers production's overwrite logic.

        # 1. evidence_scope: any trace with at least one LLM event.
        # 2. observed_models_in_trace: trace events with llm_call.model set.
        # 3. unavailable_models_by_workflow: row with model not in
        #    litellm.model_cost (e.g., "ollama/local").
        # 4. heterogeneous_model_node_count + paths: IR node with
        #    params.model = "${item.model}" (template string).
        # 5. sub_workflow_rollup: parent IR with a `type: workflow` node
        #    pointing at a child .pflow.md file.

        # ----- single fixture exercising 1-4 (heterogeneous root LLM) -----
        from pflow.core.cache_analysis.analyze import analyze
        from tests.shared.trace_fixture_builder import TraceFixtureBuilder

        wf_path = str(tmp_path / "x.pflow.md")
        ir_inline = {
            "ir_version": "0.1.0",
            "inputs": {"topic": {"type": "string"}},
            "nodes": [
                {
                    "id": "generate",
                    "type": "llm",
                    "params": {
                        "model": "${item.model}",  # heterogeneous trigger
                        "prompt": "About ${topic}",
                    },
                    "batch": {"items": [{"model": "ollama/local"}]},
                },
            ],
        }
        builder = TraceFixtureBuilder()
        trace_inline = {
            "format_version": "2.2.0",
            "workflow_path": wf_path,
            "nodes": [
                builder.batch_event("generate", items=[
                    {"index": 0, "success": True, "duration_ms": 1.0,
                     "node_output": {"response": "ok"},
                     "llm_call": {"model": "ollama/local",
                                  "input_tokens": 100, "output_tokens": 10,
                                  "cost_usd": None}},
                ]),
            ],
        }
        result = analyze(
            ir_inline,
            parameters={"topic": "x"},
            trace_data=trace_inline,
            workflow_path=wf_path,
            auto_load_trace=False,
        )
        assert result.summary.evidence_scope != "static_analysis", (
            "evidence_scope production overwrite missing"
        )
        assert result.summary.observed_models_in_trace, (
            "observed_models_in_trace production overwrite missing"
        )
        assert result.summary.unavailable_models_by_workflow, (
            "unavailable_models_by_workflow production overwrite missing"
        )
        assert result.summary.heterogeneous_model_node_count > 0, (
            "heterogeneous_model_node_count production overwrite missing"
        )
        assert result.summary.heterogeneous_model_node_paths, (
            "heterogeneous_model_node_paths production overwrite missing"
        )

        # ----- separate fixture exercising sub_workflow_rollup (5) -----
        # Use the committed parent-3deep fixture which is known to produce
        # a non-default sub_workflow_rollup (verified by the existing test
        # at line 1949).
        from pathlib import Path as _P
        from pflow.execution.workflow_resolver import resolve_workflow

        fixture_dir = _P("tests/fixtures/cache_analysis")
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
        assert result_subwf.summary.sub_workflow_rollup is not None, (
            "sub_workflow_rollup production overwrite missing"
        )


def _make_exclusion() -> ProjectionExclusion:
    """Helper for parity test probe 2."""
    return ProjectionExclusion(
        workflow_path="/abs/x.pflow.md",
        node_path="generate",
        reason="heterogeneous_model",
        actual_cost_usd=0.03,
    )
```

**Why two methods**:
- Method 1 catches "new field added to dataclass without builder update."
- Method 2 catches "production overwrite logic deleted but allowlist stale." Without method 2, an entry in `_BUILDER_DOCUMENTED_DEFAULTS` could become a lie (production stops overwriting → field is at default everywhere → tests asserting on the default pass for the wrong reason).

**Imports needed at module top** (verify they exist; add if not):
- `import dataclasses`
- `from pathlib import Path`

### Step 3: Migrate `test_json_partial_trace_exposes_evidence_scope_and_observed_models` (line 608)

**Current**: synthetic `_make_analysis(...)` + `__dict__` override of `evidence_scope`, `observed_models_in_trace`, `trace_unexecuted_llm_rows`. Asserts on rendered JSON.

**Target**: drive `analyze(...)` with inline IR + a partial trace built via `TraceFixtureBuilder`. Trace must record exactly one of two declared LLM nodes executing (so `trace_coverage = "partial"` → `evidence_scope = "partial_trace_executed_subset"`), with the executed node's `llm_call.model` populated to drive `observed_models_in_trace`.

**Migration recipe**:

```python
def test_json_partial_trace_exposes_evidence_scope_and_observed_models(
    tmp_path: Path,
) -> None:
    """End-to-end: a 2-LLM-node IR with only 1 node executed in the trace
    drives evidence_scope = "partial_trace_executed_subset" and
    observed_models_in_trace = the executed node's models.

    Replaces a synthetic-builder version that hand-set evidence_scope and
    observed_models_in_trace via __dict__ override. The synthetic version
    passed even when production's _evidence_scope_for_trace_coverage logic
    drifted — see Pitfall #19.

    Mutation contract: delete the assignment at analyze.py:3704
    (observed_models_in_trace) — this test fails because the field reverts
    to ().
    """
    from pflow.core.cache_analysis.analyze import analyze
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    wf_path = str(tmp_path / "x.pflow.md")
    ir = {
        "ir_version": "0.1.0",
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {
                    "model": "${item.model}",
                    "prompt": "About ${topic}",
                },
                "batch": {"items": [
                    {"model": "gemini/a"},
                    {"model": "gemini/b"},
                ]},
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
            # Only "generate" runs; "review" is unexecuted in this trace.
            builder.batch_event("generate", items=[
                {"index": 0, "success": True, "duration_ms": 1.0,
                 "node_output": {"response": "ok"},
                 "llm_call": {"model": "gemini/a",
                              "input_tokens": 100, "output_tokens": 10,
                              "cost_usd": 0.001}},
                {"index": 1, "success": True, "duration_ms": 1.0,
                 "node_output": {"response": "ok"},
                 "llm_call": {"model": "gemini/b",
                              "input_tokens": 100, "output_tokens": 10,
                              "cost_usd": 0.001}},
            ]),
        ],
    }

    analysis = analyze(
        ir,
        parameters={"topic": "x"},
        trace_data=trace_data,
        workflow_path=wf_path,
        auto_load_trace=False,
    )
    payload = render_json(analysis)

    assert payload["summary"]["evidence_scope"] == "partial_trace_executed_subset"
    assert payload["summary"]["observed_models_in_trace"] == ["gemini/a", "gemini/b"]
    assert payload["per_call"][0]["observed_models"] == ["gemini/a", "gemini/b"]
    assert payload["per_call"][0]["observed_call_count"] == 2

    # trace_unexecuted_llm_rows: production computes from rows missing in
    # trace; the "review" node should appear here. Don't assert exact path
    # because production may use a different path representation; assert
    # the node_id appears.
    unexecuted = payload["summary"]["trace_unexecuted_llm_rows"]
    assert any(row["node_path"] == "review" for row in unexecuted)
```

**What the migration loses**:
- Surgical control over the exact `trace_unexecuted_llm_rows` path strings (the synthetic test asserted `"/abs/review-a.pflow.md"`). Replaced with structural assertion on `node_path == "review"`.

**What the migration gains**:
- The test now exercises the production code path that derives `evidence_scope` from `trace_coverage` (line 3690), the production code path that aggregates `observed_models_in_trace` from row data (line 3704), and the production code path that detects unexecuted nodes. Delete any of those three sites and the test fails.

### Step 4: Migrate `test_json_summary_exposes_projection_exclusions_and_delta_reason` (line 645)

**Current**: synthetic `_make_analysis(actually_paid=0.05, no_cache=0.02, partial=True, projection_exclusions=(exclusion,), actual_delta_unavailable_reason="projection_exclusions")`. The synthetic version constructs a `ProjectionExclusion(reason="heterogeneous_model")` in isolation, but production produces this exclusion as a side effect of a heterogeneous IR — the synthetic version doesn't exercise that coupling.

**Target**: drive `analyze(...)` with a heterogeneous IR (`model: ${item.model}` template) so production emits the `heterogeneous_model` `ProjectionExclusion` AND sets `heterogeneous_model_node_count > 0` AND sets `actual_vs_no_cache_delta.kind = "unavailable"` with `unavailable_reason = "projection_exclusions"` — three coupled overwrites in one fixture.

**Migration recipe**:

```python
def test_json_summary_exposes_projection_exclusions_and_delta_reason(
    tmp_path: Path,
) -> None:
    """End-to-end: a heterogeneous-model IR (model: ${item.model}) plus a
    trace with recorded cost_usd produces:
      - projection_exclusions[0].reason == "heterogeneous_model"
      - actual_vs_no_cache_delta.kind == "unavailable"
      - actual_vs_no_cache_delta.unavailable_reason == "projection_exclusions"
      - heterogeneous_model_node_count > 0  (free regression coverage)

    Replaces a synthetic-builder version that constructed a
    ProjectionExclusion in isolation, missing the coupling between
    heterogeneous-IR detection and projection-exclusion emission.

    Mutation contract: change the cohort key in
    cost_estimation.py::_partition_priced_rows to NOT exclude
    heterogeneous rows — this test fails because the projection
    exclusion no longer fires.
    """
    from pflow.core.cache_analysis.analyze import analyze
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    wf_path = str(tmp_path / "x.pflow.md")
    ir = {
        "ir_version": "0.1.0",
        "inputs": {"topic": {"type": "string"}},
        "nodes": [
            {
                "id": "generate",
                "type": "llm",
                "params": {
                    "model": "${item.model}",
                    "prompt": "About ${topic}",
                },
                "batch": {"items": [
                    {"model": "anthropic/claude-sonnet-4-5"},
                    {"model": "gemini/gemini-2.0-flash"},
                ]},
            },
        ],
    }
    builder = TraceFixtureBuilder()
    trace_data = {
        "format_version": "2.2.0",
        "workflow_path": wf_path,
        "nodes": [
            builder.batch_event("generate", items=[
                {"index": 0, "success": True, "duration_ms": 1.0,
                 "node_output": {"response": "ok"},
                 "llm_call": {"model": "anthropic/claude-sonnet-4-5",
                              "input_tokens": 1000, "output_tokens": 100,
                              "cost_usd": 0.05}},
                {"index": 1, "success": True, "duration_ms": 1.0,
                 "node_output": {"response": "ok"},
                 "llm_call": {"model": "gemini/gemini-2.0-flash",
                              "input_tokens": 1000, "output_tokens": 100,
                              "cost_usd": 0.001}},
            ]),
        ],
    }

    analysis = analyze(
        ir,
        parameters={"topic": "x"},
        trace_data=trace_data,
        workflow_path=wf_path,
        auto_load_trace=False,
    )
    payload = render_json(analysis)

    # Projection exclusion fires for heterogeneous-model row.
    exclusions = payload["summary"]["projection_exclusions"]
    assert any(e["reason"] == "heterogeneous_model" for e in exclusions)
    assert any(e["node_path"] == "generate" for e in exclusions)

    # actual_vs_no_cache_delta is unavailable due to projection exclusions.
    delta = payload["summary"]["actual_vs_no_cache_delta"]
    assert delta["kind"] == "unavailable"
    assert delta["unavailable_reason"] == "projection_exclusions"

    # Coupling: heterogeneous-IR detection populates the *_node_count
    # field too. (This is bonus regression coverage; the synthetic version
    # missed it entirely.)
    assert payload["summary"]["heterogeneous_model_node_count"] >= 1
    assert "generate" in payload["summary"]["heterogeneous_model_node_paths"]
```

**What the migration loses**:
- Exact dollar values (`actually_paid=0.05, no_cache=0.02`). Production computes these from trace `cost_usd` and per-row pricing. The migration trades synthetic precision for end-to-end coupling — exact dollar assertions would over-couple to LiteLLM pricing tables that drift across versions (a known anti-pattern in this codebase per `cost_estimation.py` history).

**What the migration gains**:
- Free regression coverage on `heterogeneous_model_node_count` and `heterogeneous_model_node_paths` (two of the documented-default fields).
- Exercises the actual coupling between heterogeneous-IR detection and projection-exclusion emission.

### Step 5: Migrate `test_render_json_includes_rollup_workflow_paths_and_unavailable_models_by_workflow` (line 1884)

**Current**: synthetic `SubWorkflowRollup(...)` and `unavailable_models_by_workflow={"/abs/child.pflow.md": ("ollama/local",)}` constructed inline. No coupling to production's rollup-build or unpriced-model detection logic.

**Target**: drive `analyze(...)` with a parent/child IR where the child uses an unpriced model. The committed `parent-child-trace.json` fixture uses `anthropic/claude-sonnet-4-5` (priced) per Checkpoint 3 — so the migration uses **inline IR + builder** (not the committed fixture).

**Migration recipe** (option A from Checkpoint 3 — inline IR):

```python
def test_render_json_includes_rollup_workflow_paths_and_unavailable_models_by_workflow(
    tmp_path: Path,
) -> None:
    """End-to-end: a parent/child IR where the child uses an unpriced
    model (ollama/local) produces:
      - sub_workflow_rollup.per_workflow with the child workflow_path
      - unavailable_models_by_workflow[child_path] == ("ollama/local",)

    Replaces a synthetic-builder version that hand-constructed both
    SubWorkflowRollup and unavailable_models_by_workflow, missing the
    coupling between rollup-build (analyze.py:651) and unpriced-model
    detection (_unavailable_models_by_workflow at analyze.py:3805).

    The committed parent-child-trace.json fixture cannot drive this test
    because its child uses anthropic/claude-sonnet-4-5 (priced). Inline
    IR + TraceFixtureBuilder gives this test self-containment.

    Mutation contract: delete _unavailable_models_by_workflow's call site
    at analyze.py:3707 — this test fails because the field reverts to None.
    """
    from pflow.core.cache_analysis.analyze import analyze
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    parent_path_str = str(tmp_path / "parent.pflow.md")
    child_path_str = str(tmp_path / "child.pflow.md")

    # Write a minimal child workflow file so resolve-time references work.
    # The child IR is what the parent's `type: workflow` node references.
    (tmp_path / "child.pflow.md").write_text(
        "# Child\n\n"
        "## Inputs\n\n### topic\n\n## Steps\n\n"
        "### draft\n- type: llm\n- model: ollama/local\n- prompt: |\n    Make a draft about ${topic}\n",
        encoding="utf-8",
    )
    parent_ir = {
        "ir_version": "0.1.0",
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
            {
                "node_id": "call-child",
                "node_type": "WorkflowExecutor",
                "duration_ms": 1.0,
                "success": True,
                "timestamp": "2026-05-08T00:00:00",
                "node_params": {"workflow": child_path_str},
                "sub_workflow_events": [
                    builder.llm_event(
                        "draft",
                        model="ollama/local",   # ← unpriced
                        input_tokens=900,
                        output_tokens=90,
                        cost_usd=None,
                    ),
                ],
            },
        ],
    }

    analysis = analyze(
        parent_ir,
        parameters={"topic": "hello"},
        trace_data=trace_data,
        workflow_path=parent_path_str,
        base_path=tmp_path,
        auto_load_trace=False,
    )
    payload = render_json(analysis)

    # sub_workflow_rollup populated by production _build_sub_workflow_rollup.
    rollup = payload["summary"]["sub_workflow_rollup"]
    assert rollup is not None
    assert any(
        entry["workflow_path"].endswith("child.pflow.md")
        for entry in rollup["per_workflow"]
    )

    # unavailable_models_by_workflow populated for the child's unpriced model.
    unavailable = payload["summary"]["unavailable_models_by_workflow"]
    assert unavailable is not None
    child_key = next(
        k for k in unavailable.keys()
        if k and k.endswith("child.pflow.md")
    )
    assert "ollama/local" in unavailable[child_key]
```

**What the migration loses**:
- Exact dollar values on rollup entries (`actually_paid_usd=0.07`, etc.). Production computes from trace `cost_usd`. Replaced with structural assertions on field presence and content.
- Synthetic precision: the test no longer asserts exact rollup numbers; if a future refactor changes how rollup costs are computed, this test won't catch the regression. **Mitigation**: the existing test at line 1949 (`test_json_emits_root_and_sub_workflow_llm_node_counts`) asserts on rollup structure with the committed 3-deep fixture; that's the right venue for cost-precision assertions.

**What the migration gains**:
- Exercises the production coupling: parent/child IR → sub-workflow trace → `_build_sub_workflow_rollup` → `_unavailable_models_by_workflow` aggregation. Delete any of those sites and the test fails.

### Step 6: Sequencing

**Implement in this order**:

1. **Add `_BUILDER_DOCUMENTED_DEFAULTS` constant** (Step 1) and **`TestMakeAnalysisShapeParity` class** (Step 2). Run `make test` — expect both methods to **pass** if the diagnosis is correct (the constant has the right 6 entries). If method 1 fails, the constant is wrong; debug by reading the failure message (it names the unrepresented fields). If method 2 fails, the production overwrite at one of the sites is broken; debug the named field.

2. **Migrate test #2** (Step 3 — `evidence_scope` / `observed_models_in_trace`). Run the single test. If it passes, commit.

3. **Migrate test #3** (Step 4 — `projection_exclusions` / heterogeneous coupling). Run the single test. If it passes, commit.

4. **Migrate test #4** (Step 5 — `sub_workflow_rollup` / `unavailable_models_by_workflow`). Run the single test. If it passes, commit.

5. **Final sweep**: `make test` (full suite) + `make check` (ruff + ruff-format + mypy + deptry). All green.

**Why parity test first**: it's the diagnostic. If the constant is wrong (e.g., misses a documented-default field, or includes one production actually populates), the parity test fails immediately and tells the implementing agent exactly which fields are at risk. Migrating tests before adding the parity test means the agent might silently leave the door open for the next field-addition drift.

**Why one migration per commit**: easier to bisect if a migration introduces a regression; reviewer can see each migration's e2e fixture in isolation.

---

## Verification

### Test commands

After each step:
```bash
# Run only the renderers test file (fastest feedback during iteration):
.venv/bin/python -m pytest tests/test_core/test_cache_analysis_renderers.py -v

# Run only the new parity class:
.venv/bin/python -m pytest tests/test_core/test_cache_analysis_renderers.py::TestMakeAnalysisShapeParity -v

# Run only one migration target:
.venv/bin/python -m pytest tests/test_core/test_cache_analysis_renderers.py::test_json_partial_trace_exposes_evidence_scope_and_observed_models -v
```

After all migrations land:
```bash
# Full default suite (must be green; ~6,250 tests):
make test

# Static checks (ruff + ruff-format + mypy + deptry):
make check

# DD#19 byte-identity gate (must remain green):
.venv/bin/python -m pytest tests/test_runtime/test_prompt_cache_hash.py::test_golden_baseline_hashes_match -v

# Plan ↔ engine parity gate (must remain green):
.venv/bin/python -m pytest tests/test_execution/test_plan_drift.py -v
```

### Mutation-test verification (manual, optional but high-value)

For each migrated test, verify the mutation contract by temporarily reverting the production fix and confirming the test fails:

| Migration | Mutation site | Expected failure |
|---|---|---|
| Step 2 method 1 | Add a new `extra_field: int = 99` field to `AnalysisSummary` | Parity test method 1 fails naming `extra_field` |
| Step 2 method 2 | Comment out `analyze.py:3704` (`observed_models_in_trace=...`) | Parity test method 2 fails on `observed_models_in_trace` assertion |
| Step 3 (test #2) | Comment out `analyze.py:3690` (`evidence_scope=...`) | Migrated test fails on `evidence_scope == "partial_trace_executed_subset"` |
| Step 4 (test #3) | Change `cost_estimation.py::_partition_priced_rows` to not exclude heterogeneous rows | Migrated test fails on `projection_exclusions` assertion |
| Step 5 (test #4) | Comment out `analyze.py:3707` (`unavailable_models_by_workflow=...`) | Migrated test fails on `unavailable_models_by_workflow` assertion |

Restore each mutation immediately after observing the failure. Do **not** commit any mutation. The mutation-test verification is informational — it proves the test is structurally sound. If a mutation does NOT cause failure, the test is too weak; tighten it before proceeding.

### Acceptance criteria

The change is complete when:

1. `tests/test_core/test_cache_analysis_renderers.py` has a `_BUILDER_DOCUMENTED_DEFAULTS` constant with exactly 6 entries.
2. `tests/test_core/test_cache_analysis_renderers.py::TestMakeAnalysisShapeParity` exists with two passing methods.
3. The three migrated tests (lines 608, 645, 1884) drive `analyze(...)` end-to-end and pass.
4. `make test` passes (~6,250 tests).
5. `make check` passes (ruff + ruff-format + mypy + deptry).
6. `test_golden_baseline_hashes_match` and `test_plan_drift.py` are green.
7. No `# noqa: C901` added to any function in this PR.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Parity method 1 fails on first run because the documented-default set has the wrong entries | M | L | Failure message names the divergent fields; iterate. The set's 6 entries are pre-verified by exploration. |
| `TraceFixtureBuilder.batch_event` signature differs from the recipe's `items=[{...}]` shape | M | M | Read `tests/shared/trace_fixture_builder.py` lines 47-108 before writing the migration; confirm the exact kwarg shape. If the builder doesn't support inline-dict items, fall back to `cached_llm_event_with_call` per item. |
| Inline child `.pflow.md` write in Step 5 fails parser validation | L | M | Use the exact shape from existing committed fixtures (`tests/fixtures/cache_analysis/child.pflow.md`); copy-paste rather than hand-writing. |
| `analyze()` with `auto_load_trace=False` doesn't accept `trace_data=` directly | L | H | Read `analyze.py:1053` signature; confirm `trace_data` parameter exists. If it doesn't, the migration must write the trace JSON to `tmp_path` and pass `trace_path=`. |
| `_build_sub_workflow_rollup` requires `base_path` to resolve the child IR | M | M | Pass `base_path=tmp_path` (where the child `.pflow.md` was written). The migration recipe in Step 5 already does this. |
| Migration test runtime exceeds 1s, slowing the renderer suite | L | L | Acceptable. Three migrated tests at ~250ms each = ~750ms added to a ~500ms suite. New total ~1.3s; well within reasonable bounds. |
| `dataclasses.fields(AnalysisSummary)` returns a different field set in CI vs locally | VL | H | Frozen dataclass; field set is deterministic. If CI Python differs (3.9 vs 3.10+), `field.default_factory` semantics may differ; the recipe handles both via `is dataclasses.MISSING` checks. |
| New `cached_llm_event_thin` rename (sibling commit) breaks the migration | L | L | Use `llm_event` and `cached_llm_event_with_call`, not `cached_llm_event` (the thin variant). Phase 4 does NOT depend on the thin variant. |
| Future field added to `AnalysisSummary` is a `dataclasses.field(default_factory=...)` and the parity test's `_at_default` helper mishandles it | L | M | The recipe's `_at_default` helper handles both `default` and `default_factory`. Verified against current `AnalysisSummary` (no factory fields today, but the helper is forward-compatible). |

---

## Top-10% Lens — Considered Alternatives (Rejected)

The user asked: "What's the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?" Three alternatives considered:

### Alt 1: Delete `_make_analysis` entirely; drive `analyze(...)` everywhere

**Considered, rejected.** Trade-off:
- Pro: zero drift risk by construction.
- Con: 75 renderer tests at ~250ms each = ~19s added to the renderer suite (currently ~0.5s; **38× slowdown**). Renderers are pure projections; unit-testing them with synthetic data is the **right shape per top-10% codebases** (mypy, ruff, rustc all do this — they unit-test their text/JSON formatters with hand-built input). Forcing every renderer test through the full analyzer conflates two layers.
- Con: surgical control loss. Tests like `test_text_summary_renders_blocking_errors_categorically` set exact integer counts (`blocking_errors=1, actionable_opportunities=2`) — driving `analyze()` to produce exactly those counts requires contriving an IR + warning-emission path that produces them. Brittle.

**Verdict**: keep the builder, lock with parity, migrate only the tests that need it.

### Alt 2: Code-generate `_BUILDER_DOCUMENTED_DEFAULTS` from a script

**Considered, rejected.** Trade-off:
- Pro: zero risk of the constant becoming stale.
- Con: 6 entries hand-listed is not maintenance burden (mypy, ruff don't codegen tiny constants either). Codegen pays off when N ≥ 50 or when the source is non-Python (CI, schema files). Here N = 6 and source is the dataclass itself.

**Verdict**: hand-list with `dataclasses.fields()` introspection in the parity test as the drift-catcher. The introspection is what catches new fields; the constant is what documents the rationale.

### Alt 3: Single shape-parity test method (skip method 2)

**Considered, rejected.** Trade-off:
- Pro: less code; one method.
- Con: an entry in `_BUILDER_DOCUMENTED_DEFAULTS` could become a lie if production stops overwriting. Method 2 catches that; method 1 doesn't.

**Verdict**: two methods. Mirrors `TestTraceFixtureBuilderShapeParity`'s 4-method pattern (4 because trace events have 4 distinct shapes; we have 1 dataclass with two failure modes).

---

## What This Plan Does NOT Cover

- Test bloat reduction (Suggestion #10 from the review). Out of scope; defer to a focused cleanup PR.
- Migration of synthetic builder tests that DON'T assert on documented-default fields (e.g., line 272). Verified safe; no work needed.
- Refactoring `_make_analysis` itself. The signature is already idiomatic; no change needed.
- New tests for `evidence_scope == "complete_trace"` mode (the third value). The parity test method 2 implicitly covers `"partial_trace_executed_subset"`; the existing committed-fixture test at line 1949 covers `"complete_trace"` indirectly (parent-child-grandchild trace has all nodes executed); `"static_analysis"` is the default (every test using `_make_analysis` without a trace produces it). All three values are covered without new tests.
- Updates to `tests/CLAUDE.md` Pitfall #19 documentation. The doctrine is already comprehensive; this plan is an instance of applying it.
