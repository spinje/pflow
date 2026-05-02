# Plan: Fix `pflow analyze-cache` projections to match actual savings

> **Revision history**:
> - v1: initial plan
> - v2: incorporated 4-agent review (review-plan, review-impact-completeness,
>   review-silent-failures, review-feature-interactions). 14 critical findings
>   confirmed and folded in.

## Context

**The problem**: `pflow analyze-cache --from-trace` projections diverge from
actual savings observed at runtime. On the Gemini smoke fixture (verified
2026-05-01):

| Metric | Reality | Analyzer projection | Drift |
|---|---|---|---|
| Per-call cacheable tokens (steady-state) | 4682 | 4682 | ✅ Exact |
| Per-call cache ratio | 99% | 99% | ✅ Exact |
| `current_cost_per_run_usd` (RUN1 baseline) | $0.00210 | $0.0032 | ❌ +53% overestimate |
| `optimized_cost_per_run_usd` (RUN2) | $0.00068 | $0.0023 | ❌ +240% overestimate |
| `savings_pct_first_run` | −67.6% | −28% | ❌ −40pp understated |
| `cacheable_tokens_estimated` for greenfield workflow inputs | (would be 4682) | `null` | ❌ Tier 4 unavailable |
| `input_tokens_estimated` for greenfield workflow inputs | 4713 | ~32 (template literal `${context}` chars) | ❌ ~99% understated |

**Root cause**: three orthogonal bugs share a common architectural axis — the
analyzer doesn't carry **resolved values** through its pipeline.

1. **Cost ignores trace's recorded `cost_usd`** — recomputes from
   `tokens × full_rate`, missing both implicit caching (Gemini) and any other
   discount the actual paid cost reflects.
2. **Tier-2 memo lookup can't see workflow inputs** — only queries
   `MemoizationCache.get_latest_for_node`, which never has rows for inputs.
3. **`estimate_tokens` tokenizes raw IR template** — counts the literal
   `${context}` (~5 chars) instead of the resolved value.

**Outcome**: agents who consult `pflow analyze-cache --from-trace` to see
"how much would I save" get wrong numbers. Greenfield projection is unusable
on workflows whose cache opportunities live on workflow inputs.

**Intended outcome**: after this fix,
`pflow analyze-cache --from-trace <baseline.json>` predicts current/optimized/rerun
costs that match actual paid costs within tokenization tolerance (±5%
typically). Greenfield projection lights up when `--inputs` are provided for
workflow-input cache chunks.

---

## Architecture

### Decision 1 — Introduce `AnalysisContext` (frozen dataclass)

Bundle the threaded inputs into one immutable object:

```python
# src/pflow/core/cache_analysis/context.py  (NEW MODULE)

@dataclass(frozen=True)
class AnalysisContext:
    """Read-only inputs threaded through the analyzer's helper graph.

    Replaces the 5-tuple ``(workflow_ir, parameters, memo_cache, trace_data,
    workflow_path, base_path)`` that today is passed by-keyword to ~30 call
    sites. Same pattern as ``execution/plan.py::_WalkerState`` — bundle the
    invariant inputs, reduce signature noise.

    Parameters reach this object **post type-coercion** (via
    ``coerce_workflow_input`` at the CLI boundary). Raw CLI strings are NOT
    stored here — int-typed inputs are int, string-typed inputs are string.
    """
    workflow_ir: Mapping[str, Any]
    parameters: Mapping[str, Any]            # post-coercion workflow input values
    memo_cache: Any | None                   # MemoizationCache or duck-typed
    trace_data: Mapping[str, Any] | None     # Loaded trace JSON, or None
    workflow_path: str | None                # File path or "ir-hash:<md5>"
    base_path: Path | None                   # For sub-workflow resolution

    def trace_event_for(self, node_id: str) -> Mapping[str, Any] | None:
        """Top-level trace event for ``node_id``, or None.

        Mirrors ``token_estimation._find_llm_event`` — non-recursive.
        Sub-workflow / batch-item events are accessed via dedicated walkers.
        """

    def cost_usd_for_node(self, node_id: str) -> tuple[float | None, str]:
        """Per-node recorded cost from trace (4-state).

        Returns ``(cost, source)``:
          - ``(float, "trace")``: priced; sum of llm_call + batch_items[*].llm_call
            costs. Cached events contribute 0.0 explicitly.
          - ``(float, "trace_partial")``: AT LEAST ONE leaf had cost_usd=None
            (unpriced model). The float is the priced subset; caller upgrades
            to recompute for unpriced leaves OR surfaces partial.
          - ``(None, "unavailable")``: no event found for this node_id.

        Recursion: top-level llm_call + batch_items[*].llm_call. Does NOT
        descend into sub_workflow_events (per-call rows iterate type:llm only;
        sub-workflow internals out of scope at this layer).

        Cached events contribute 0.0 to the sum (this run paid 0 for that
        item) — NOT excluded as "unavailable." If ALL events for a node are
        cached, returns (0.0, "trace") — unambiguous "this run paid 0."
        """

    def resolve_ref_value(self, ref: str) -> Any | None:
        """Resolve a single template ref to its latest known value.

        Tier order DEPENDS on whether root is a workflow input or a node:
          - **Root in workflow_ir["inputs"]**: parameters WINS over memo.
            Agent's --inputs represent their CURRENT question; memo from a
            prior run with different inputs MUST NOT override.
          - **Root is a node id**: memo only. Parameters never reach here
            because node outputs aren't passable as --inputs.

        Empty-value handling: returns ``None`` for empty string, empty dict,
        empty list. Distinct from "we have a real value" — propagates as
        Tier-4 unavailable to avoid false ~0-token projections.
        """
```

### Decision 2 — Reuse `cache_render._resolve_static_prefix_for_cache` for prompt resolution

`core/cache_render.py:213-245` already does prompt-template resolution with
cache-byte-identity (uses `deterministic_serialize`). Existing helper, no
new template code.

**Synthetic context construction**: build `shared = dict(ctx.parameters)`
(workflow inputs) merged with `{node_id: memo_output_for_node}` for each
referenced node id. The helper expects standard pflow shared-store shape.

### Decision 3 — Per-node cost extraction: bounded recursive walker

Clone the recursion shape from `core/trace_report.py::_compute_event_cost`
(top-level llm_call + batch_items[*].llm_call). DO NOT descend into
sub_workflow_events from within the per-node walker — sub-workflow internals
have their own analyze-cache invocation. Sibling events with different
node_ids are NOT walked by this method (`cost_usd_for_node(X)` matches X
only).

For each leaf:
- `cached: True` event → contributes 0.0 to sum (this run paid 0)
- `cost_usd: None` (unpriced model) → marks the result as `"trace_partial"`,
  caller decides recompute vs surface
- `cost_usd: float` → contributes to sum

### Decision 4 — Why NOT a `RefResolver` class

pflow's convention is **stateless static methods + explicit context**.
Instance-bound resolvers would be a net-new pattern (Subagent 3 confirmed).
`AnalysisContext` already encapsulates the resolution policy via methods —
adding a separate `RefResolver` would double the abstraction count.

### Decision 5 — `cost_data_source` 4-state field

Mirror existing `data_source` / `cacheable_data_source` / `output_data_source`
pattern but with 4 states for richer transparency:

| State | Meaning |
|---|---|
| `"trace"` | Cost from trace; all leaves priced. High confidence. |
| `"trace_partial"` | Cost from trace + recompute mix; at least one leaf had unpriced model. Medium-high confidence. |
| `"recomputed"` | No trace; computed from `tokens × LiteLLM rate`. Medium confidence. |
| `"unavailable"` | Pricing missing AND no trace data. Low confidence. |

Renderer surfaces inline annotation per state (parity with sibling fields —
PROMOTED from "optional" to required).

### Decision 6 — Track B parameters/inputs asymmetry

Per Decision 1's `resolve_ref_value` semantics:
- Workflow input refs → parameters wins over memo (current question wins)
- Node output refs → memo only (parameters can't refer to node outputs)

This asymmetry mirrors runtime behavior — workflow inputs come from the user
at runtime; node outputs come from prior execution.

---

## Three Tracks — what changes, where

### Track A — Cost honors trace's recorded `cost_usd`

**Why**: kill the +53% / +240% overestimate on RUN1 / RUN2 baseline costs.

**Touch points** (expanded per impact-completeness review):

| File | Change |
|---|---|
| `core/cache_analysis/context.py` | NEW: `AnalysisContext.cost_usd_for_node(node_id)` — bounded recursion, cached-event = 0.0, partial-pricing detection |
| `core/cache_analysis/analyze.py` | `PerCallRow`: add `cost_usd: float \| None = None` and `cost_data_source: str = "recomputed"` (4-state) |
| `core/cache_analysis/analyze.py` | `_build_per_call_row`: populate `cost_usd` via `ctx.cost_usd_for_node(node_id)` |
| `core/cache_analysis/cost_estimation.py` | `_per_call_current_cost`: when `row.cost_usd is not None`, return it directly. Add `_per_call_current_cost_recomputed` for the recompute fallback path used by `_aggregate_optimized_cost`. |
| `core/cache_analysis/cost_estimation.py` | `compute_aggregate_costs`: heterogeneous-batch rows now contribute their `row.cost_usd` (when set) to `current_usd` even though they're excluded from `priced_rows` (priced_rows is for projection math; recorded cost is independent of pricing data). |
| `core/cache_analysis/render_text.py` | **Required** (not optional): cost rendering shows tier annotation per `cost_data_source` state |
| `core/cache_analysis/render_json.py` | Add `per_call[].cost_usd`, `per_call[].cost_data_source`. Bump `JSON_FORMAT_VERSION` minor (additive). |

**Invariants**:
- `optimized_cost_per_run_usd` and `rerun_cost_per_run_usd` are projections —
  always recomputed (no trace path because trace doesn't have hypothetical
  alternative scenarios).
- `savings_first_run_usd` and `savings_rerun_usd` are input-only (output
  cancels). Unchanged.
- **`row.input_tokens_estimated` is always per-call** (one invocation's
  worth), regardless of whether `row.cost_usd` is per-call or aggregated.
  This invariant prevents future drift when `_aggregate_optimized_cost`
  reads per-call tokens × invocations from rows that have aggregated cost.
- Cached events contribute 0.0 (NOT skipped as "unavailable").
- Heterogeneous batch sub-workflows: recorded cost surfaces in `current_cost`
  via row.cost_usd path even when `model_is_heterogeneous=True`.

**Estimated LOC**: ~120 production, ~50 tests.

---

### Track B — Tier-2 falls back to `parameters` for workflow inputs

**Why**: greenfield projection currently shows `cacheable=null` on
workflow-input chunks. Fixing this lets agents see real numbers on greenfield
analysis when they pass `--inputs`.

**Touch points** (expanded per impact-completeness review):

| File | Change |
|---|---|
| `core/cache_analysis/context.py` | `AnalysisContext.resolve_ref_value(ref)` — input-vs-node-output asymmetry per Decision 6; empty-value handling per Decision 1 |
| `core/cache_analysis/token_estimation.py` | `_latest_value_for_ref(ref, *, ctx)` — replace `(memo_cache, workflow_path)` with `ctx`; consult `ctx.resolve_ref_value(ref)` |
| `core/cache_analysis/token_estimation.py` | `_estimate_ref_tokens(ref, *, model, ctx)` — same replacement |
| `core/cache_analysis/token_estimation.py` | `_sum_resolved_chunk_tokens` and `estimate_cacheable_tokens` accept `ctx` |
| `core/cache_analysis/analyze.py` | Construct `ctx = AnalysisContext(...)` once at top of `analyze()`; thread to all consumers |
| `core/cache_analysis/analyze.py` | These helpers (NOW EXPLICITLY ENUMERATED per impact-completeness) accept `ctx`: `_build_per_call_rows_and_warnings`, `_build_per_call_row`, `_populate_suggested_blocks`, `_consolidate_to_root_advisories`, `_emit_discrepancy_diagnostics`, `_predict_cache_keys`, `_attribute_root_cause`, `_check_root_for_consolidation` |
| `core/cache_analysis/cross_workflow.py` | Receives `ctx` for sub-workflow walker context |
| Tests (~25 sites in 3 files) | Backward-compat shim: helpers accept `*, ctx=None, memo_cache=None, workflow_path=None`; when `ctx is None` reconstitute synthetic context from legacy kwargs. Allows phased test migration. |

**Invariants**:
- Workflow-input refs: parameters wins over memo (current question wins)
- Node-output refs: memo only
- Empty values (`""`, `{}`, `[]`, `None`) → return None (Tier-4 unavailable)

**Estimated LOC**: ~150 production (signature changes mechanical but spread),
~70 tests.

---

### Track C — `estimate_tokens` resolves prompt template before tokenizing

**Why**: greenfield input_tokens_estimated currently reflects raw template
character count.

**Touch points**:

| File | Change |
|---|---|
| `core/cache_analysis/analyze.py` | `_build_per_call_row`: before calling `estimate_tokens(...)`, resolve template via `cache_render._resolve_static_prefix_for_cache(prompt, dict(ctx.parameters) merged with memo_outputs_by_root_node_id)`. Then scan resolved string for remaining `${...}` patterns. |
| `core/cache_analysis/token_estimation.py` | `estimate_tokens` accepts a resolved-prompt parameter. Returns `data_source: "estimator-partial"` (NEW) when at least one `${...}` echoed through after resolution. |

**Invariants**:
- When `ctx.parameters` is empty AND no memo data: prompt remains the raw
  template (existing behavior). `data_source = "estimator-partial"` flags
  low fidelity.
- When parameters AND/OR memo provide all referenced values: resolved prompt
  → realistic token count. `data_source = "estimator"`.
- Tier-1 trace path is unchanged — reads `event.llm_call.input_tokens`
  directly; doesn't go through prompt resolution.
- Batch alias `${item.X}` ALWAYS unresolved by `_resolve_static_prefix_for_cache`
  → triggers "estimator-partial" — correct, batch items are inherently dynamic.

**Estimated LOC**: ~50 production, ~30 tests.

---

## Implementation Phasing

### Phase 0 — Plumb `AnalysisContext` (foundational refactor)

Add `AnalysisContext` and refactor existing signatures to use it. **Net
signature reduction**.

**Phase 0 verification gate** (per review-plan W3):
- Capture `render_json(analyze(...))` output for representative fixtures
  BEFORE refactor (gemini-smoke greenfield + with-cache + brownfield + a
  declared-cache lyrics-generator excerpt).
- After Phase 0, assert byte-equivalent output. If anything diverges,
  investigation is required before proceeding.
- Refactor includes test fixture migration via shim semantics
  (Track B touch points).

### Phase A — Cost honors trace

After Phase 0, focused diff on `cost_usd_for_node`, `PerCallRow.cost_usd`,
and `_per_call_current_cost` branch.

**Investigation step** (per review-feature-interactions Critical-2): before
Phase A implementation, inspect a real prewarm trace fixture to verify
where prewarm-write costs land in the event tree. If they land at
sibling/synthetic node_ids, `cost_usd_for_node` walker needs widening
(prefix match or whitelist of related synthetic ids).

### Phase B — Tier-2 parameters fallback + workflow-input/node-output asymmetry

### Phase C — Resolved prompt for tokenization + partial-resolution detection

---

## Brownfield vs greenfield matrix (expanded)

| Scenario | Trace | Memo | ## Cache | Inputs | Behavior post-fix |
|---|---|---|---|---|---|
| Pure greenfield | ❌ | ❌ | ❌ | ❌ | Per-call rows hidden (Option C). Suggested block emitted. Cost: unavailable. |
| Greenfield + inputs | ❌ | ❌ | ❌ | ✓ | Tier-2 parameters fallback fires; `cacheable_data_source="parameters"`. `input_tokens` reflects resolved prompt. |
| Designed (no run) + declared cache | ❌ | ❌ | ✓ | ✓ | Tier-2 parameters fallback for declared chunks; `input_tokens` reflects resolved prompt. |
| Designed + declared cache + memo | ❌ | ✓ | ✓ | maybe | Memo data primary; parameters fallback for inputs; `input_tokens` reflects substitutions. |
| Post-run greenfield | ❌ | ✓ | ❌ | maybe | Tier-2 memo for node-output refs; **parameters wins for input refs** when provided (current question wins over historical). |
| Post-run with cache | ✓ | ✓ | ✓ | maybe | Tier-1 trace for cacheable. **`current_cost` from recorded `cost_usd`**, `cost_data_source="trace"`. |
| Pre-existing trace, fresh inputs (parameters/trace divergence) | ✓ | maybe | maybe | ✓ (different from trace) | **Known limitation** (deferred to v1.x): trace cost reflects old inputs; cacheable projection reflects new inputs. Mixed comparison. Document in `analyze-cache --help`. |
| Heterogeneous batch + trace | ✓ | maybe | maybe | maybe | `current_cost` includes recorded heterogeneous batch costs (Track A handles this). Projections (`optimized`/`rerun`) skip heterogeneous rows (no pricing). |

---

## Testing Strategy (per user "high-value, no coverage chasing" guidance)

### High-value tests (mutation-tested)

Each test below: reverts of the production fix produce specific assertion
failures with clear messages. Tests delegated to `test-writer-fixer`
subagent unless full context is required.

**Test 1 — Cost from trace matches recorded cost**
- Fixture: `RUN1-no-cache-trace.json` (Gemini smoke, total $0.00210)
- Assertion: `summary.current_cost_per_run_usd ≈ 0.00210` (within ±5%)
- Mutation: revert Track A trace branch → fails with `0.0032 != 0.00210`

**Test 2 — Greenfield Tier-2 parameters fallback (workflow inputs)**
- Fixture: synthetic 2-node workflow sharing `${context}`; no cache; no memo
- Assertion: `cacheable_tokens_estimated > 0` AND `cacheable_data_source == "parameters"`
- Mutation: revert parameters branch → `cacheable_tokens_estimated == None`

**Test 3 — Resolved prompt for tokenization**
- Fixture: same as Test 2; `--inputs context=<5000-token doc>`
- Assertion: `input_tokens_estimated >= 4500`
- Mutation: revert template-resolution call → `input_tokens_estimated < 100`

**Test 4 — Brownfield end-to-end (Gemini smoke trio)**
- Fixture: full Gemini smoke RUN2 trace
- Assertions:
  - `summary.current_cost_per_run_usd ≈ $0.00068` (RUN2 actual)
  - `summary.rerun_cost_per_run_usd` within ±20% of $0.00068 (sanity check;
    NOT strict equality — projection vs reality)
- Mutation: cost honoring path break → assertion failure with concrete number

**Test 5 — Cached events contribute 0.0 (NOT unavailable)**
- Fixture: trace with N=2 events, one cached carrying original `cost_usd`,
  one regular
- Action: `ctx.cost_usd_for_node(node_with_only_cached_events)`
- Assertion: returns `(0.0, "trace")` — unambiguous "this run paid 0"
- Mutation: if walker returns `(None, "unavailable")` → recompute fallback
  fabricates fictional cost → test fails

**Test 6 — Sub-workflow scoping**
- Fixture: workflow with `type: workflow` node containing LLM calls
- Assertion: aggregate `current_cost` covers ONLY top-level type:llm nodes
- Mutation: walker accidentally descends into sub_workflow_events → inflated
  cost

**Test 7 — `cost_usd: None` propagation (4-state)**
- Fixture: trace with one priced node + one unpriced model node
- Assertion: priced row `cost_data_source == "trace"`; unpriced row
  `cost_data_source == "recomputed"` (fell through to recompute);
  `summary.partial_cost_usd == True`
- Mutation: 3-state (no `"trace_partial"`) → can't distinguish pure trace
  from mixed → assertion fails

**Test 8 — Heterogeneous batch + recorded cost (NEW per feature-interactions)**
- Fixture: workflow with `model: ${item.model}` heterogeneous batch + real trace
- Assertion: heterogeneous row's `row.cost_usd` is populated; aggregate
  `current_cost` includes it (despite `model_is_heterogeneous=True`)
- Mutation: if heterogeneous rows skip cost extraction → silent undercount

**Test 9 — Empty-string parameter (NEW per silent-failures)**
- Fixture: greenfield workflow + `--inputs context=""`
- Assertion: `cacheable_tokens_estimated == None`, `cacheable_data_source == "unavailable"`
- Mutation: empty value treated as real → `cacheable_tokens_estimated == 0`
  but `data_source == "parameters"` → false signal

**Test 10 — Partial-resolution detection (NEW per silent-failures)**
- Fixture: prompt has TWO refs; only one has parameters/memo data
- Assertion: `data_source == "estimator-partial"`; warning emitted listing
  unresolved refs
- Mutation: no partial detection → `data_source == "estimator"` looks
  authoritative

**Test 11 — Phase 0 byte-equivalence regression (NEW per review-plan W3)**
- Fixture: pre-Phase-0 captured `render_json(analyze(...))` outputs for 4
  representative fixtures (gemini-smoke greenfield/with-cache/brownfield +
  declared-cache excerpt)
- Assertion: post-Phase-0 byte-equivalent
- Mutation: any unintended semantic drift in refactor → test fails

**Test 12 — Workflow-input parameters wins over memo (NEW per review-plan C4)**
- Fixture: memo populated for `context` from prior run; parameters provides
  different value for `context`
- Assertion: `cacheable_tokens_estimated` reflects parameters' value, NOT
  memo's
- Mutation: memo-wins-rule → fails

### Test delegation pattern

Per user instruction:
- Use `test-writer-fixer` subagent for each test with full context
  (fixture, expected values, mutation contract)
- Write manually only when surfacing unexpected coupling needing in-context
  investigation

### Tests NOT to add

- Unit tests for every helper signature change — Test 11 (regression
  baseline) covers Phase 0
- Per-state combinatorial parametrization — pick representatives that
  exercise distinct code paths
- Coverage-driven additions

---

## Critical files

### New files
- `src/pflow/core/cache_analysis/context.py` — `AnalysisContext` dataclass + methods

### Modified production
- `src/pflow/core/cache_analysis/analyze.py` — `PerCallRow` extension,
  `_build_per_call_row`, ALL helpers thread `ctx` (enumerated above)
- `src/pflow/core/cache_analysis/cost_estimation.py` —
  `_per_call_current_cost` branches on `row.cost_usd`; heterogeneous batch
  rows surface recorded cost
- `src/pflow/core/cache_analysis/token_estimation.py` —
  `_latest_value_for_ref`, `_estimate_ref_tokens` accept `ctx`; partial-
  resolution detection
- `src/pflow/core/cache_analysis/render_text.py` — **required**
  `cost_data_source` annotation (parity with sibling fields)
- `src/pflow/core/cache_analysis/render_json.py` — `per_call[].cost_usd`,
  `per_call[].cost_data_source`; `JSON_FORMAT_VERSION` minor bump
- `src/pflow/core/cache_analysis/cross_workflow.py` — accepts `ctx`

### Modified call sites
- `src/pflow/cli/commands/analyze_cache.py` — caller untouched (still passes
  `(parameters, workflow_path, ...)`); `analyze()` builds `AnalysisContext`
  internally
- `src/pflow/mcp_server/services/execution_service.py` — same
- `src/pflow/execution/runner.py` — same

### Reused existing utilities (no changes)
- `cache_render._resolve_static_prefix_for_cache` — prompt resolution
- `cache_render.deterministic_serialize` — value serialization
- `runtime/template_resolver.TemplateResolver` — single-ref resolution
- `core/trace_report._compute_event_cost` — clone reference (recursion shape)

### Tests
- `tests/test_core/test_cache_analysis_cost_estimation.py` — Tests 1, 4, 6, 7, 8
- `tests/test_core/test_cache_analysis_token_estimation.py` — Tests 2, 5, 9, 10, 12
- `tests/test_core/test_cache_analysis_analyze.py` — Test 3 + Test 11 (Phase 0 regression)
- `tests/test_core/test_cache_analysis_per_id_emission.py` — shim migration (no new tests)
- `tests/test_core/test_cache_analysis_per_id_coverage.py` — shim migration

---

## Risks and trust boundaries

**Verified by parallel pflow-codebase-searcher subagents (4 agents)**:
- Trace data shapes and extraction paths
- TemplateResolver permissive behavior + helper reuse
- pflow conventions for context bundling (`_WalkerState` precedent)
- Helper enumeration — confirmed 4 helpers were missing from initial plan

**Verified by parallel review subagents (4 agents)**:
- Plan structural integrity
- Impact completeness across consumers
- Silent-failure categories
- Feature interaction matrix

**Assumed correct, will verify in implementation**:
- Prewarm event cost shape (review-feature-interactions Critical-2) —
  empirical inspection of a prewarm trace required before Phase A
- Batch nodes have NO top-level `event.llm_call` (Subagent 1 high-confidence
  read; one sentinel test catches if wrong)
- Phase 0 byte-equivalence achievable (Test 11 verifies)

**Out of scope (deferred to v1.x)**:
- Multi-walker consolidation (4 walkers with divergent `cached` filter)
- Sub-workflow cost rollup at analyze-cache scope
- Parameters/trace divergence detection (document as known limitation)
- JSON auto-parse interaction (document as known)

---

## Acceptance criteria

1. All 12 high-value tests pass (mutation-test verified).
2. `make test` passes (current 6,046+ test count, no regressions).
3. `make check` clean.
4. `test_plan_drift.py` 33/33+ green.
5. `test_golden_baseline_hashes_match` (DD#19) green.
6. **Test 11 byte-equivalence**: Phase 0 produces identical analyze() output
   to pre-refactor on captured fixtures.
7. Gemini smoke re-verification: `analyze-cache --from-trace` projections
   match RUN1/2/3 actual costs within ±5%.
8. Stage 2.1 (song-creator standalone) becomes meaningful.

After acceptance criteria met, resume Stage 2.1 song-creator verification.
