# Plan: Unified `estimate_cacheable_tokens` — 4-tier hierarchy + brownfield + trace correctness (REVISED post-`/code-review`)

> **Revision note**: this plan reflects 14 confirmed findings from a 4-agent review pass (review-plan, review-silent-failures, review-feature-interactions, review-test-fidelity). See "Findings from `/code-review` pass" at the bottom.

## Context

**Why this change.** The Stage 2 Anthropic smoke test (`scratchpads/stage2-verification/anthropic-smoke/REPORT.md`) confirmed the cache rendering layer works end-to-end (cache_creation=1599 / cache_read=1599 on Sonnet 4.5; -73% rerun savings). It ALSO surfaced a class of bugs in `pflow analyze-cache` that affects the analyzer's value-prop in steady-state — both with and without a 2.1.0 trace.

**Empirical mismatch on the smoke fixture (1393 token reference body):**

| Surface | Empirical | Analyzer reports | Off by |
|---|---|---|---|
| with-cache, first run savings | $0.00296 | $0.00003 | ~100× |
| with-cache, rerun savings | $0.00856 | $0.00008 | ~100× |
| no-cache, optimization potential (trace mode) | -25% to -73% achievable | 0% | qualitatively wrong |
| Cacheable tokens per call | 1599 (trace truth) | 14 (literal `${context}` token count) | ~115× |

**Single root cause** (verified by 3 parallel pflow-codebase-searcher agents): pflow has 4-tier hierarchy for `input_tokens_estimated` (`trace → memo → estimator → heuristic`) and 2-tier for `output_tokens_estimated` (`trace → memo → unavailable`), but `cacheable_tokens_estimated` uses a single static heuristic that operates on the prompt template literal. It never reads trace cache fields. It never tokenizes resolved chunk values from memo. The "fix" for the no-cache+memo case is implemented as a post-hoc `_enrich_with_projected_cacheable` overlay — a structural patch on top of the broken stub, not the symmetric tier hierarchy used by the other two metrics.

**Brownfield investigation result:** **No production code path** tokenizes resolved chunk values from memo for `cacheable_tokens_estimated` when `## Cache` is declared. The static heuristic is the only path. `_estimate_ref_tokens` exists and works (used by `_populate_suggested_blocks` for greenfield candidate detection), but its semantics are not reused for the declared-subset case.

**Top-10% lens.** mypy / rustc / clippy / ruff / TypeScript-with-cache all share one pattern: when ground truth exists (cache file, trace, log), READ IT; estimate only when ground truth is absent. The function that produces a number is responsible for picking the highest-fidelity source available. Today's `cacheable` path violates this — three scattered mechanisms (stub + overlay + brownfield blind spot) where one tiered function would be enough.

**Outcome.** A single `estimate_cacheable_tokens` function in `token_estimation.py` mirroring the established `estimate_tokens` and `estimate_output_tokens` patterns. Replaces both `_estimate_cacheable_tokens` (static stub) and `_enrich_with_projected_cacheable` (post-hoc overlay). Cacheable values become correct in ALL four cases — with-cache+trace, with-cache+memo (brownfield), no-cache+memo (post-run greenfield), no-data (returns None, renderer hides via Option C). Net production LOC: roughly even (~80 LOC moved/refactored, structurally simpler).

---

## The function

**Location:** `src/pflow/core/cache_analysis/token_estimation.py` alongside the existing pair.

**Signature** (mirrors `estimate_tokens` / `estimate_output_tokens`):

```python
def estimate_cacheable_tokens(
    *,
    declared_subset: list[str] | None,    # node has prompt_cache: [...]
    candidate_subset: list[str] | None,   # greenfield candidate from suggested_blocks
    trace_event: dict[str, Any] | None,   # per-event llm_call dict (from _find_llm_event)
    memo_cache: _MemoCacheLike | None,
    model: str,
    workflow_path: str | None,
    prompt: str = "",                     # used by Tier 3 only
) -> tuple[int | None, str]:
    """Return (cacheable_tokens, source) using highest-fidelity available data.

    Sources: "trace", "memo", "estimator", "unavailable".

    Asymmetric fall-through (load-bearing):
    - For DECLARED subsets: partial memo data → falls through to Tier 3
      (heuristic) to preserve cache.below-min-predicted warning fidelity.
    - For CANDIDATE-only (greenfield projection): partial memo data →
      returns (None, "unavailable") (Option C — honest unmeasurable).

    Tier 1 fall-through: when declared subset has trace_event with
    cache_creation+cache_read == 0 (cache declared but didn't fire —
    sub-threshold etc.), fall through to Tier 2/3. Downstream
    cache.below-min-predicted warning is gated on cacheable_data_source !=
    "trace" so it fires correctly for the fallthrough cases without
    contradicting trace evidence when cache demonstrably worked.
    """

    # Tier 1: trace ground truth — only meaningful for declared cache that fired
    if declared_subset and trace_event is not None:
        creation = int(trace_event.get("cache_creation_input_tokens") or 0)
        read = int(trace_event.get("cache_read_input_tokens") or 0)
        if creation + read > 0:
            return (creation + read, "trace")
        # Fall through: declared but didn't fire. Tier 2/3 computes
        # "what was attempted" so cache.below-min-predicted fires correctly.

    # Tier 2: memo-resolved chunk tokenization (declared OR candidate)
    chunks = declared_subset or candidate_subset
    if chunks and memo_cache is not None and model:
        total = _sum_resolved_chunk_tokens(chunks, model, memo_cache, workflow_path)
        if total is not None:
            return (total, "memo")
        # Fall through to Tier 3 for declared (preserves below-min-predicted fidelity).
        # For candidate-only, fall through to Tier 4 (Option C — honest unmeasurable).

    # Tier 3: estimator (declared subset only — heuristic; preserves below-min-predicted)
    if declared_subset:
        return (max(0, len(prompt) * 75 // 400), "estimator")

    # Tier 4: nothing to project — honest unavailable
    return (None, "unavailable")
```

**Tier 2 helper** (also in `token_estimation.py`):

```python
def _sum_resolved_chunk_tokens(
    chunks: list[str],
    model: str,
    memo_cache: _MemoCacheLike,
    workflow_path: str | None,
) -> int | None:
    """Sum memo-resolved chunk token counts. None if any chunk has no memo data."""
    total = 0
    for ref in chunks:
        tokens = _estimate_ref_tokens(ref, model=model, memo_cache=memo_cache, workflow_path=workflow_path)
        if tokens is None:
            return None
        total += tokens
    return total
```

**New trace-walking helper** (also in `token_estimation.py`):

```python
def _find_llm_event(trace: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    """Return the first matching ``llm_call`` event dict for the given node_id,
    or None. Non-recursive (top-level events only — sub_workflow_events and
    batch_items[i].events out of scope per existing _llm_call_field_from_trace
    contract at lines 142-149)."""
    events = trace.get("nodes")
    if not isinstance(events, list):
        return None
    for event in events:
        if not isinstance(event, dict) or event.get("node_id") != node_id:
            continue
        llm_call = event.get("llm_call")
        if isinstance(llm_call, dict):
            return llm_call
    return None
```

Refactor `_llm_call_field_from_trace` (`token_estimation.py:137`) to consume `_find_llm_event` for symmetry:

```python
def _llm_call_field_from_trace(trace, node_id, field):
    llm_call = _find_llm_event(trace, node_id)
    if llm_call is None:
        return None
    value = llm_call.get(field)
    return value if isinstance(value, int) else None
```

**Move:** `_estimate_ref_tokens` and `_latest_value_for_ref` migrate from `analyze.py:1416, 1438` to `token_estimation.py`. They are token-estimation primitives. Lazy-imports `TemplateResolver` to keep the layer-policy clean (`token_estimation.py` already lazy-imports `litellm`).

**Internal-to-module import in `analyze.py`**: after the move, `analyze.py` adds `from .token_estimation import _estimate_ref_tokens, _latest_value_for_ref`. The two existing in-module callers (`_check_root_for_consolidation:1291,1306` consolidate-to-root advisory; `_populate_suggested_blocks:1091` chunk sizing) resolve `_estimate_ref_tokens` through `analyze.py`'s namespace, which keeps the import binding. **This is critical for the monkeypatch contract** — see "Tests" section below.

**`__all__` updates**: `token_estimation.py:215` becomes `["estimate_cacheable_tokens", "estimate_output_tokens", "estimate_tokens"]`. Private helpers (`_sum_resolved_chunk_tokens`, `_find_llm_event`, `_estimate_ref_tokens`, `_latest_value_for_ref`) stay out of `__all__`.

---

## The four cases (verification matrix)

| # | Case | Trace? | Memo? | declared | candidate | Tier fires | Result |
|---|---|---|---|---|---|---|---|
| 1 | Pure greenfield, pre-run | — | — | — | — | 4 | None / `unavailable` (row hidden) |
| 2 | Greenfield, post-run, candidate detected | — | ✓ | — | ✓ | 2 | int / `memo` ✓ FIXES Bug D |
| 3 | Greenfield, post-run, no candidate | — | ✓ | — | — | 4 | None / `unavailable` (row hidden) |
| 4 | Greenfield + trace, candidate detected | ✓ | ✓ | — | ✓ | 2 | int / `memo` (Tier 1 N/A — no declared) ✓ FIXES Bug D in trace mode |
| 5 | Declared, pre-run | — | — | ✓ | — | 3 | int / `estimator` (heuristic; below-min-predicted may fire spuriously — pre-first-run; resolves on memo population) |
| 6 | Declared, post-run, no trace | — | ✓ | ✓ | — | 2 | int / `memo` ✓ FIXES brownfield bug (silent gap) |
| 7 | Declared + trace, cache fired | ✓ | ✓ | ✓ | — | 1 | int / `trace` ✓ FIXES smoke-test Bug A,B,C |
| 8a | **Declared + heterogeneous batch** (`model=""`) | — | — | ✓ | — | 3 | int / `estimator` (Tier 2 short-circuits on `not model`; Tier 3 fires for declared) |
| 8b | **Greenfield + heterogeneous batch** (`model=""`) | — | — | — | — | 4 | None / `unavailable` (Tier 2 gate fails on `not model`; Tier 3 requires declared) — **JSON shape changes from `0` to `null`** for these rows; documented as additive 2.x |
| 9 | Declared + trace, cache didn't fire | ✓ | ✓ | ✓ | — | 2 (after fall-through) | int / `memo` (preserves below-min-predicted warning correctly) |
| 10 | Declared, partial memo (one chunk no data) | — | partial | ✓ | — | 3 (after fall-through) | int / `estimator` (declared falls through; below-min works) |
| 11 | Declared + trace fired, partial memo | ✓ | partial | ✓ | — | 1 | int / `trace` (Tier 1 wins; partial memo doesn't matter) |
| 12 | Candidate + partial memo | — | partial | — | ✓ | 4 | None / `unavailable` (candidate-only does NOT fall through — honest Option C) |

**Coverage proof:** every (data state × declared/candidate state × heterogeneous state) combination resolves to a deterministic tier. No silent zeros. No fabricated numbers. No missing branches.

---

## Files modified

### Production

#### `src/pflow/core/cache_analysis/token_estimation.py`

- ADD `estimate_cacheable_tokens(...)` — the new tiered function (above).
- ADD `_sum_resolved_chunk_tokens(...)` — Tier 2 helper.
- ADD `_find_llm_event(trace, node_id) -> dict | None` — trace-walker helper. Refactor `_llm_call_field_from_trace` to consume it (symmetry).
- MOVE `_estimate_ref_tokens` (currently `analyze.py:1416-1435`) here.
- MOVE `_latest_value_for_ref` (currently `analyze.py:1438-1455`) here. Lazy-import `TemplateResolver` inside (mirrors existing `litellm` lazy-import pattern).
- Module docstring extended with the 4-tier hierarchy for `estimate_cacheable_tokens`.
- `__all__` updated.

#### `src/pflow/core/cache_analysis/analyze.py`

**Deletes:**
- DELETE `_estimate_cacheable_tokens` (`:970-983`) — replaced by unified function.
- DELETE `_enrich_with_projected_cacheable` (`:693-726`) — folded into one-pass row building.
- DELETE `_estimate_ref_tokens` (`:1416-1435`) — moved.
- DELETE `_latest_value_for_ref` (`:1438-1455`) — moved.

**New imports:**
```python
from .token_estimation import (
    _estimate_ref_tokens,        # consumed by _check_root_for_consolidation, _populate_suggested_blocks
    _latest_value_for_ref,       # transitively used
    _find_llm_event,             # consumed by _build_per_call_row
    estimate_cacheable_tokens,   # consumed by _build_per_call_row
)
```

**`_build_per_call_row` refactor (`:591-680`):**

Add `candidate_subset: list[str] | None = None` keyword-only param. Replace the static-stub call. Find trace event and call new function. **Explicit 3-way clamp/ratio block** (load-bearing — distinguishes None from 0 for Option C row-hide):

```python
trace_event = _find_llm_event(trace_data, node_id) if trace_data else None
cacheable_tokens, cacheable_source = estimate_cacheable_tokens(
    declared_subset=declared_subset,
    candidate_subset=candidate_subset,
    trace_event=trace_event,
    memo_cache=memo_cache,
    model=model,
    workflow_path=workflow_path,
    prompt=prompt,
)

# Explicit 3-way: None / 0 / positive (preserves Option C visibility contract)
cacheable_with_clamp: int | None
ratio: int | None
if cacheable_tokens is None:
    cacheable_with_clamp = None
    ratio = None
elif cacheable_tokens > 0:
    cacheable_with_clamp = min(cacheable_tokens, input_tokens)
    ratio = _safe_pct(cacheable_with_clamp, input_tokens)
else:
    cacheable_with_clamp = 0
    ratio = 0

return PerCallRow(
    ...,
    cacheable_tokens_estimated=cacheable_with_clamp,
    cache_ratio_pct=ratio,
    cacheable_data_source=cacheable_source,
    ...,
)
```

**`_per_node_warnings` gate update (`:752-764`)** — load-bearing per review-silent-failures C2 (NOT deferred):

```python
cacheable = row.cacheable_tokens_estimated
# Gate on cacheable_data_source != "trace": when source is trace AND cacheable is
# nonzero, cache demonstrably worked at this size; the warning would contradict
# trace evidence. When source is memo/estimator, the warning fires correctly.
# This consumption is ANALYZER-SIDE (not renderer); cannot be deferred.
if (
    row.declared_prompt_cache
    and cacheable is not None
    and cacheable > 0
    and row.model
    and row.cacheable_data_source != "trace"
):
    min_tokens = get_min_cache_tokens(row.model)
    if cacheable < min_tokens:
        diagnostics.append(
            make_diagnostic("cache.below-min-predicted", ...)
        )
```

**`analyze()` refactor (`:312-328`) — explicit two-pass ordering:**

Two-pass split (load-bearing — `_populate_suggested_blocks` STILL needs `model` from rows; the cheap candidate-detection runs alone before rows):

```python
# Pass 1 (cheap): walk IR for shared template references.
# NO tokenization here — that needs `model` from rows (Pass 2).
candidate_subsets_by_node = _detect_candidate_subsets(workflow_ir)

# Build per-call rows in ONE pass; cacheable computed via tiered estimator.
per_call_rows = [
    _build_per_call_row(
        node,
        ...,
        candidate_subset=candidate_subsets_by_node.get(node["id"]),
        trace_data=trace_data,
        memo_cache=memo_cache,
        ...
    )
    for node in nodes
]
rows_by_node = {row.node_path: row for row in per_call_rows}

# Pass 2 (heavy): build paste-ready blocks. Uses `model` from rows + tokenization
# for chunk sizes. Brownfield early-return preserved.
suggested_blocks, shared_warnings = _populate_suggested_blocks(
    workflow_ir=workflow_ir,
    rows_by_node=rows_by_node,
    memo_cache=memo_cache,
    workflow_path=workflow_path,
    notes=notes,
)
# NOTE: _populate_suggested_blocks no longer returns cacheable_by_node (3rd tuple
# element). The post-hoc _enrich_with_projected_cacheable call is GONE.
```

`_detect_candidate_subsets(workflow_ir)` is a new helper that wraps the existing `_collect_llm_template_references` walker, filters for shared refs (≥2 nodes), and returns `dict[node_id → list[str]]` — pure refs, no tokenization. Lives next to `_collect_llm_template_references`.

**`PerCallRow` schema update:**

Add `cacheable_data_source: str = "unavailable"` field. Mirrors existing `data_source` (input) and `output_data_source`. **Three independent confidence labels for three independent metrics** — they may diverge legitimately (e.g., `data_source="trace"` AND `cacheable_data_source="memo"` in Tier 1 fall-through scenarios).

#### Other production files (read-only verification)

The fan-out is **fully contained within `src/pflow/core/cache_analysis/`** (verified by Agent 1 audit). These files have ZERO consumer references and need NO changes:
- `src/pflow/cli/commands/analyze_cache.py`
- `src/pflow/mcp_server/` (entire tree — JSON shape stays compatible per `startswith("2.")` rule; see "JSON_FORMAT_VERSION" below)
- `src/pflow/execution/runner.py`

#### Cost estimation, renderers — VERIFIED unchanged behavior

- `cost_estimation.py`: 4 sites use `or 0` coercion (None-tolerant). Verified structurally safe — Tier 4 (None) only fires on rows that don't reach cost math (subset is None → filtered before iteration).
- `render_text.py:744` visibility filter: explicit `if row.cache_ratio_pct is None: return True`. Honors None.
- `render_json.py:185-186`: pass-through; serializes None as JSON null cleanly.

`PerCallRow.cacheable_data_source` field is added to JSON output via `_per_call_to_dict` — additive, no version bump.

### Tests

#### Monkeypatch site direction — REVISED per review (review-plan C1, review-test-fidelity W1)

**Plan claim was inverted.** Correct contract:

- **5 EXISTING monkeypatch sites STAY pointing at `analyze_module._estimate_ref_tokens`** — do NOT change them.
  - `tests/test_core/test_cache_analysis_per_id_emission.py:1929, 1979, 2019, 2059`
  - `tests/test_core/test_cache_analysis_per_id_coverage.py:431`
  - These tests exercise `_consolidate_to_root_advisories` (analyze.py-resident). After the move, `analyze.py` re-imports `_estimate_ref_tokens` into its namespace. Patches via `monkeypatch.setattr(analyze_module, "_estimate_ref_tokens", ...)` STILL work — Python resolves the unqualified name through analyze.py's module dict, which holds the imported binding.

- **NEW Tier 2 unit tests** (in `test_cache_analysis_token_estimation.py`) — patch `token_estimation_module._estimate_ref_tokens` directly. They invoke `estimate_cacheable_tokens` which calls `_estimate_ref_tokens` from its own module's globals.

**Following the plan's original "5 mechanical updates" claim would BREAK 5 existing tests.** Confirm zero churn for the 5 existing sites.

#### Autouse fixture update — `test_per_id_emission.py:26-31`

The `deterministic_tokens` autouse fixture currently patches `analyze_module.estimate_tokens = _word_count`. After the move, `_estimate_ref_tokens` (now in `token_estimation.py`) calls `estimate_tokens` from its own module — bypasses the analyze.py patch. Tests in this file relying on word-count tokenization see real `litellm.token_counter` values post-refactor.

**Required extension:**

```python
@pytest.fixture(autouse=True)
def deterministic_tokens(monkeypatch):
    def _word_count(model, text):
        return len((text or "").split())
    monkeypatch.setattr("pflow.core.cache_analysis.analyze.estimate_tokens", _word_count)
    monkeypatch.setattr("pflow.core.cache_analysis.token_estimation.estimate_tokens", _word_count)
```

Both patches needed: analyze.py-resident callers see the first; `token_estimation.py`-resident callers (the moved `_estimate_ref_tokens`, the new `_sum_resolved_chunk_tokens`) see the second.

#### Fixture helper updates

Per Agent 1 + review-test-fidelity S1: add `cacheable_data_source: str = "unavailable"` default to test helpers. Default value is `"unavailable"` (NOT `"memo"`) — matches Tier 4 and avoids artificially inflating cost-confidence aggregates in tests that don't intend to.

Specific sites:
- `tests/test_core/test_cache_analysis_analyze.py:34, 416, 435, 526` (`_row` and `_summary_row`)
- `tests/test_core/test_cache_analysis_renderers.py:430` (`_row`)
- `tests/test_core/test_cache_analysis_cost_estimation.py:35` (`_row`)

#### `tests/test_core/test_cache_analysis_token_estimation.py` (extend, ~12 tier-coverage tests)

Mirror the existing tier-coverage pattern at `:61-206`:

| # | Test name | Mutation contract |
|---|---|---|
| 1 | `test_cacheable_tier_1_trace_returns_creation_plus_read_with_asymmetric_values` | trace_event with **cache_creation=1000, cache_read=599** (asymmetric, sum=1599) → returns (1599, "trace"). Mutation: revert `creation + read` → `creation` alone → returns 1000, fails. ALSO assert reversed asymmetry (creation=599, read=1000) returns 1599 (defends against returning either field alone). |
| 2 | `test_cacheable_tier_1_falls_through_when_zero` | declared + trace_event with creation=0, read=0 → falls through. **Assert source != "trace" AND tokens != 0 (or None)**. Mutation: keep `>= 0` instead of `> 0` → returns (0, "trace") — both assertions catch. |
| 3 | `test_cacheable_tier_2_memo_sums_resolved_chunk_tokens` | declared = ["a", "b"]; memo returns "X"=100, "Y"=200 → returns (300, "memo"). Mutation: revert summation to first-only → returns 100. |
| 4 | `test_cacheable_tier_2_for_declared_partial_memo_falls_through_to_estimator` | declared=["a","b"], prompt non-empty, memo has "a" only → returns (int, "estimator"). **Pinned to estimator** — not "either Tier 3 or None." Mutation: drop fall-through → returns (None, "unavailable"), test fails on source assertion. |
| 5 | `test_cacheable_tier_3_estimator_for_declared_no_history` | declared, no trace, no memo, prompt='X'*1000 → returns (187, "estimator"). **Comment**: "Formula `len(prompt) * 75 // 400` intentionally locked here. Refactoring the heuristic requires updating this value AND its docstring rationale." |
| 6 | `test_cacheable_tier_3_skips_for_candidate_only` | candidate (no declared), no memo → returns (None, "unavailable"). Mutation: apply heuristic to candidate → fabricates. |
| 7 | `test_cacheable_tier_4_returns_none_for_pure_greenfield` | nothing declared, nothing candidate → (None, "unavailable"). |
| 8 | `test_cacheable_tier_2_short_circuits_when_model_empty` | heterogeneous (`model=""`), declared, memo populated → falls through to Tier 3 estimator. Verifies the gate `if chunks and memo_cache is not None and model:`. |
| 9 | `test_cacheable_tier_1_does_not_fire_without_declared` | candidate set, trace populated → Tier 2 path (Tier 1 only fires for declared). Mutation: drop the `declared_subset and` precondition → Tier 1 fires for candidate, fails. |
| 10 | `test_sum_resolved_chunk_tokens_returns_none_on_unmeasurable_chunk` | 3 chunks, **chunk 2** is None (mid-list, not first) → returns None. Verifies the early-exit isn't dependent on chunk position. |
| 11 (NEW) | `test_cacheable_tier_2_for_candidate_with_full_memo_fires` | candidate=["a","b"], no declared, memo full → returns (int, "memo"). **Closes the unit-test gap** — existing tests cover declared+memo (#3) and candidate+no-memo (#6) but not candidate+memo. Mutation: break the `declared_subset or candidate_subset` precedence → returns None for candidate path. |
| 12 (NEW) | `test_find_llm_event_returns_first_matching_event` | trace with two `llm_call` events for same node_id → returns first. Locks deterministic event selection (cf. needs-decision item B about batch averaging). |

#### `tests/test_core/test_cache_analysis_analyze.py` (extend, ~5 end-to-end tests — Pitfall #19 defense)

Each drives `analyze(...)` end-to-end with REAL `MemoizationCache` (mirrors `test_memo_tier_reachable_via_default_construct_in_analyze` at `tests/test_core/test_cache_analysis_token_estimation.py:209-267`):

| # | Test name | Mutation contract |
|---|---|---|
| 13 | `test_brownfield_memo_populates_cacheable_via_memo_tier` | Workflow with `## Cache` + `prompt_cache: [context]`; seed memo with deterministic value (use `monkeypatch.setattr` on `litellm.token_counter` to return fixed 1500); run `analyze()` → assert `row.cacheable_tokens_estimated == 1500` AND `row.cacheable_data_source == "memo"` AND `row.data_source == "memo"`. **Both load-bearing**: value (defends against silent Tier-3 fall-through) AND source (defends against tier-mislabel). Mutation: revert to `_estimate_cacheable_tokens` → cacheable becomes heuristic value (≠ 1500). |
| 14 | `test_brownfield_trace_populates_cacheable_via_trace_tier_with_asymmetric_values` | Workflow with `## Cache` declared + 2.1.0 trace with **cache_creation=1000, cache_read=599** (asymmetric). Drive `analyze()` → assert `row.cacheable_tokens_estimated == 1599` AND `row.cacheable_data_source == "trace"`. **Asymmetric values defend against `creation+read` → `creation` alone mutation.** |
| 15 | `test_no_cache_trace_with_memo_projects_via_candidate` | No-cache workflow with shared `${context}` reference + 2.1.0 trace + memo data → assert `row.cacheable_tokens_estimated > 0`, `row.cacheable_data_source == "memo"`, AND verify candidate detection: `cache.shared-context-undeclared` warning fires with the expected chunk in context. **Three assertions** defend against (a) value miss, (b) tier mislabel, (c) candidate-walker breakage. |
| 16 (NEW) | `test_heterogeneous_batch_with_declared_cache_uses_estimator_tier` | Workflow with batch sub-workflow `model: ${item.model}` + declared `prompt_cache: [...]`. Assert `row.model_is_heterogeneous == True`, `row.cacheable_tokens_estimated > 0`, `row.cacheable_data_source == "estimator"`. **Closes Case 8a end-to-end gap** — unit test #8 covers the gate; this verifies the full path through `analyze()`. |
| 17 (NEW) | `test_declared_partial_memo_falls_through_to_estimator_end_to_end` | Workflow with declared subset of 2 chunks; memo populated for one only. Drive `analyze()` end-to-end. Assert `row.cacheable_data_source == "estimator"` AND `row.cacheable_tokens_estimated > 0`. **Closes Case 10 end-to-end gap** — exercises the declared-fall-through-to-Tier-3 path through full `analyze()`. |

#### Existing test strengthening

**`test_analyze_summary_counts_warnings_and_info` (`test_cache_analysis_analyze.py:147-163`)** — review-test-fidelity W5. Tighten:

```python
# Replace:
assert summary.warnings_count + summary.info_count >= 1
# With:
assert any(
    w.id == "cache.below-min-predicted"
    for w in result.warnings
), f"Expected cache.below-min-predicted; got: {[w.id for w in result.warnings]}"
```

This catches both "warning disappears" AND "different warning fires for the wrong reason."

#### Removed-code-path test gaps verified clean

Agent 3 confirmed no DIRECT tests reference `_estimate_cacheable_tokens` or `_enrich_with_projected_cacheable`. Indirect coverage at `test_per_call_cache_ratio_never_exceeds_100_pct` (`:111-144`) asserts only the `cacheable <= input` clamp invariant — survives the refactor.

---

## Brownfield + edge-case verification matrix

| Mode | Pre-refactor cacheable source | Post-refactor source | Verification |
|---|---|---|---|
| Greenfield, 0 LLM nodes | N/A (no rows) | N/A | Already verified — no change |
| Greenfield with opportunities, post-run + memo | Static heuristic OR `_enrich_with_projected_cacheable` overlay | Tier 2 memo via candidate_subset | Test #13/#15; lyrics-generator song-creator smoke |
| Steady-state (`## Cache` declared) + no trace + no memo | Static heuristic | Tier 3 estimator (same formula) | Test #5; existing `test_analyze_summary_counts_warnings_and_info` |
| Steady-state + memo (no trace) | **STATIC HEURISTIC — broken silently** | Tier 2 memo | Test #13 (the silent gap) |
| Steady-state + 2.1 trace, cache fired | **STATIC HEURISTIC — broken** | Tier 1 trace | Test #14 (smoke fixture) |
| Steady-state + 2.1 trace, cache didn't fire (sub-threshold) | Static heuristic | Tier 1 falls through → Tier 2/3 → `cache.below-min-predicted` fires (gated on `source != "trace"`) | Test #2 + Case 9 row |
| `--from-trace` with discrepancies (existing path) | Discrepancy-detection unchanged | Same — discrepancy logic untouched | Existing `test_discrepancy_*` |
| 2.0.0 trace fallback | Discrepancy emission suppressed; static heuristic | Tier 1 sees 0+0 fields → falls to Tier 2/3 (correct) | Existing 2.0.0 fallback test |
| **Heterogeneous + declared** (`model=""` + `prompt_cache:`) | Static heuristic | Tier 3 (Tier 2 short-circuits on `not model`) — Case 8a | Test #16 (NEW end-to-end) |
| **Heterogeneous + greenfield** (`model=""`, no cache) | Static heuristic returns 0 | Tier 4 (None) — Case 8b — **JSON shape: `0` → `null`** for these rows; additive 2.x change | Existing `_row_has_real_data` keeps row visible; new test confirms field is null |
| `--all-rows` flag | Visibility unchanged | Unchanged | No new test |
| Per-call section hidden (Option C) | None propagation via overlay | None propagation via Tier 4 + explicit 3-way clamp | Existing Option C tests |

---

## Existing functions/utilities reused

- `estimate_tokens` and `estimate_output_tokens` (`token_estimation.py:34, 87`) — patterns mirrored exactly.
- `_estimate_ref_tokens` and `_latest_value_for_ref` — moved to `token_estimation.py` and reused as Tier 2's per-chunk primitive.
- `TemplateResolver.extract_root_node_id` and `TemplateResolver.resolve_template` — already used by `_latest_value_for_ref`; lazy-imported in new home.
- `_collect_llm_template_references` (`analyze.py:1140`) — refs map walker reused by new `_detect_candidate_subsets`.
- `_llm_call_field_from_trace` (`token_estimation.py:137`) — refactored to consume new `_find_llm_event` helper for symmetry.

---

## Verification (end-to-end)

### Test suite

```bash
make test                      # expect 6,025 + ~17 new = ~6,042 passing
make check                     # ruff + ruff-format + mypy + deptry green
```

### Regression gates that MUST stay green

- `tests/test_execution/test_plan_drift.py` (34 tests) — planner ↔ runtime parity.
- `tests/test_runtime/test_prompt_cache_hash.py::test_golden_baseline_hashes_match` (DD#19).

### Smoke fixture verification

```bash
cd scratchpads/stage2-verification/anthropic-smoke

# Pre-refactor BASELINE (run BEFORE editing — capture for diff):
uv run pflow analyze-cache smoke-with-cache.pflow.md --from-trace RUN3-rerun-trace.json --format=json > PRE-FIX-with-cache-trace.json
uv run pflow analyze-cache smoke-no-cache.pflow.md --from-trace RUN1-no-cache-trace.json --format=json > PRE-FIX-no-cache-trace.json
uv run pflow analyze-cache smoke-with-cache.pflow.md --no-trace-autoload --format=json > PRE-FIX-with-cache-no-trace.json
uv run pflow analyze-cache smoke-no-cache.pflow.md --no-trace-autoload --format=json > PRE-FIX-no-cache-no-trace.json

# Post-refactor: compare to verify expected shifts:

# With-cache + trace (Bug A/B/C fix verification)
uv run pflow analyze-cache smoke-with-cache.pflow.md --from-trace RUN3-rerun-trace.json --format=json | \
  jq '.per_call[] | {node, cacheable: .cacheable_tokens_estimated, ratio: .cache_ratio_pct, source: .cacheable_data_source}'
# Pre-fix: cacheable=14, ratio=1, source missing
# Post-fix: cacheable=1599, ratio≈98, source="trace" ✓

# No-cache + trace (Bug D verification)
uv run pflow analyze-cache smoke-no-cache.pflow.md --from-trace RUN1-no-cache-trace.json --format=json | \
  jq '.summary.savings_pct_first_run'
# Pre-fix: 0
# Post-fix: ~25% (the achievable savings if user adds ## Cache) ✓

# Brownfield no-trace (post-run state)
uv run pflow analyze-cache smoke-with-cache.pflow.md --no-trace-autoload --format=json | \
  jq '.per_call[] | {cacheable: .cacheable_tokens_estimated, source: .cacheable_data_source}'
# Pre-fix: cacheable=14, source missing
# Post-fix: cacheable≈1450 (memo-derived), source="memo" ✓
```

### Lyrics-generator regression

```bash
# Greenfield reference
uv run pflow analyze-cache /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md --no-trace-autoload

# Diff against POST-STAGE1-FINAL-song-creator.txt — should differ ONLY in
# cacheable column for nodes with memo data (most have none on a fresh checkout
# → output should be byte-identical or near-identical).
```

### JSON_FORMAT_VERSION rationale (NO bump — additive only)

`cacheable_data_source` is an additive field. Per the consumer rule documented at `render_json.py:31-78` (`format_version.startswith("2.")`), additive fields don't trigger a minor bump. Precedent: Stage C.1 added `model_is_heterogeneous`, `heterogeneous_model_node_count`, `heterogeneous_model_node_paths` without bumping from 2.0. Document the addition in the version-history block; keep `JSON_FORMAT_VERSION = "2.0"`.

### Cross-workflow boundary findings — out of scope

`cache.shared-context-undeclared` boundary findings (`node_id=None`) consume `_count_llm_nodes_referencing_path` to compute consumer counts. They do not consume `cacheable_tokens_estimated`. The new function does not affect cross-workflow diagnostics; cost math for boundary findings stays as-is.

### MCP parity

Existing `test_analyze_cache_tool.py` covers MCP↔CLI JSON shape parity. With additive-only field changes, no MCP-side updates required; tests stay green.

---

## Implementation order

Single PR with a `/code-review` checkpoint between production refactor and test churn (per review-plan S5):

1. **Move helpers** — `_estimate_ref_tokens` + `_latest_value_for_ref` → `token_estimation.py`. Add internal-import in `analyze.py`. Run suite — verify 5 existing monkeypatch sites STILL PASS unchanged (mechanical check; if they fail, the import-binding contract is wrong).

2. **Add new function + helper** — `estimate_cacheable_tokens` + `_sum_resolved_chunk_tokens` + `_find_llm_event` in `token_estimation.py`. Refactor `_llm_call_field_from_trace` to consume `_find_llm_event`.

3. **Restructure `analyze()`** — pre-compute `candidate_subsets_by_node` via new `_detect_candidate_subsets` walker; update `_build_per_call_row` (new param, explicit 3-way clamp); delete `_enrich_with_projected_cacheable`; simplify `_populate_suggested_blocks` (drop `cacheable_by_node` return value); delete `_estimate_cacheable_tokens`.

4. **Add `cacheable_data_source` field** on `PerCallRow`. Wire through to JSON output. Update `_per_node_warnings` gate to consume the new field.

   **— `/code-review` checkpoint here —** (production refactor complete, internally consistent, before test churn)

5. **Update fixture helpers** — add `cacheable_data_source="unavailable"` defaults at 6 sites.

6. **Update autouse fixture** in `test_per_id_emission.py` to patch BOTH module bindings.

7. **Add new tests** — 12 tier-coverage unit tests (#1-12) + 5 end-to-end production-shape tests (#13-17).

8. **Strengthen existing tests** — `test_analyze_summary_counts_warnings_and_info` to assert specific `cache.below-min-predicted` ID.

9. **Run smoke fixtures + lyrics-generator regression + load-bearing gates.**

   **— `/code-review` checkpoint here —** (final state before commit)

---

## Out of scope

- **Trace `template_resolutions.prompt.{template, resolved}` diff-based fallback** for the rare no-cache + trace + no-memo edge case. ~80 LOC + edge-case tests for diff parsing. Defer to v1.x.

- **`AnalysisSummary.total_cacheable_tokens_estimated: int → int | None`** flip. Producer at `:2272` already coerces None → 0 via `or 0`. Per W6 audit — Tier 4 only fires on rows that don't reach this aggregate (already filtered upstream). Behavior byte-identical to today for the 100%-None case. Keep as int.

- **Renderer changes to surface `cacheable_data_source` in text output**. JSON exposes the field for agents who care; text renderer omits for compactness. Defer.

- **Caching `_estimate_ref_tokens` results** (LRU on (ref, model, workflow_path)). Memo + tokenization is fast; lyrics-generator overhead <1s.

- **Aggregate `_aggregate_cacheable_confidence`** parallel to existing `_aggregate_confidence` (input). Existing aggregator reads `data_source` only; cacheable confidence stays per-row in JSON. Renderer-level aggregation deferred.

- **`warnings` → `findings` rename** — cosmetic; out of scope.

---

## Test strategy — Pitfall #19 defense (production-shape testing)

Per the progress log: "Pitfall #19 has bitten Task 159 EIGHT times" — synthetic fixtures matching buggy code shapes; production paths differing; tests passing against fakes.

**Defense pattern:** all end-to-end tests (#13-17) drive `analyze()` against a real-shape IR with REAL `MemoizationCache.put(...)` calls (NOT synthetic dicts) and REAL trace dicts (NOT Mock). Mirrors verified pattern at `test_memo_tier_reachable_via_default_construct_in_analyze:209-267`.

**Mutation contract per test** (documented in test docstring with explicit revert-and-fail expectation):

- **Value AND source assertions** (load-bearing for #13-17): each E2E test asserts BOTH `cacheable_tokens_estimated == <deterministic_value>` AND `cacheable_data_source == "<expected_tier>"`. The deterministic value defends against tier-mislabel masquerading as success; the source defends against value-coincidence.

- **Asymmetric trace values for Tier 1** (#1, #14): `cache_creation=1000, cache_read=599` (sum=1599). Defends against `creation + read` → `creation` alone mutation that would pass if either field were 0.

- **Mid-list None for Tier 2 helper** (#10): chunk position 2 is None (not first). Defends against `if i == 0: early-exit` mutations that would only catch the first-chunk case.

---

## Open user decisions (deferred per `/code-review`)

These came up during review; each can be deferred without blocking implementation but should be on the radar:

### A. `cache_ratio_pct` (cacheable/input) vs `cache.discrepancy.actual_pct` (cache_read/total) — semantic clarity

Two different cache-related percentages with similar names. Pre-fix the static heuristic made the row's ratio obviously low-fidelity (1%) so divergence was clear. Post-fix both look authoritative. Renderer note? Docstring? Column rename?

**Recommend**: defer. Renderer polish; not a correctness bug. Add to v1.x text-pass.

### B. Batch event selection (first-match vs averaging) for Tier 1

For batch nodes, trace has multiple events. `_find_llm_event` picks first-match (deterministic). For prewarm flows where chunk membership shifts mid-batch, this may not be representative.

**Recommend**: document deterministic first-match behavior in `_find_llm_event` docstring. Real-world impact unclear without prewarm trace data; revisit when prewarm hits Stage 2.

### C. Implementation timing — fix before or after Stage 2.1 song-creator?

This refactor + Stage 2.1 (song-creator real-LLM run) are independent. Fix-first means Stage 2.1 sees the corrected analyzer. Fix-after means Stage 2.1 may surface MORE bugs that share the same fix shape and bundle them.

**Recommend**: fix first. Stage 2.1 will produce a no-cache baseline trace; the agent's natural follow-up is "how much would I save if I added `## Cache`?" — exactly the case this refactor addresses (Bug D).

---

## Findings from `/code-review` pass

Reviewed by 4 agents in parallel: review-plan, review-silent-failures, review-feature-interactions, review-test-fidelity.

### Confirmed (incorporated above)

| # | Finding | Found by | Where addressed |
|---|---|---|---|
| 1 | Tri-state clamp block must explicitly distinguish None / 0 / positive | review-plan, review-silent-failures | "_build_per_call_row refactor" — explicit 3-way code block |
| 2 | `cache.below-min-predicted` warning emitter must consume `cacheable_data_source` | review-silent-failures | "_per_node_warnings gate update" — analyzer-side, NOT deferred |
| 3 | Monkeypatch site direction was inverted | review-plan, review-test-fidelity | "Tests — Monkeypatch site direction" — 5 existing sites STAY at analyze_module |
| 4 | Autouse `deterministic_tokens` fixture bypass | review-test-fidelity | "Autouse fixture update" — patch BOTH module bindings |
| 5 | `_find_trace_event` helper signature must be specified | review-plan, review-feature-interactions | "Function — `_find_llm_event`" — explicit spec; refactor `_llm_call_field_from_trace` to consume |
| 6 | Two-pass ordering must be explicit | review-feature-interactions | "_analyze() refactor — explicit two-pass ordering" — Pass 1 cheap walker, Pass 2 chunk sizing |
| 7 | Heterogeneous + greenfield mislabeled in matrix | review-plan | "Four cases" — split Case 8 into 8a/8b; documented JSON shape change |
| 8 | Test #11 (now #13) assertion strength | review-test-fidelity | Test #13 asserts deterministic value AND source |
| 9 | Test #12 (now #14) asymmetric trace values | review-test-fidelity | Test #14 uses creation=1000, read=599 |
| 10 | Test #5 lock-formula comment | review-test-fidelity | Test #5 includes explicit comment in mutation contract |
| 11 | `test_analyze_summary_counts_warnings_and_info` tighten | review-test-fidelity | "Existing test strengthening" — assert specific ID |
| 12 | Add E2E test for heterogeneous + declared | review-test-fidelity | Test #16 (NEW) |
| 13 | Add E2E test for Tier 2 partial-memo fall-through | review-test-fidelity | Test #17 (NEW) |
| 14 | Add unit test for candidate + full memo → Tier 2 | review-test-fidelity | Test #11 (NEW) |
| 15 | JSON_FORMAT_VERSION no-bump rationale | review-plan, review-feature-interactions | "Verification — JSON_FORMAT_VERSION rationale" |
| 16 | Cross-workflow boundary findings out of scope (one-liner) | review-feature-interactions | "Verification — Cross-workflow boundary findings" |
| 17 | Internal-to-module import update | review-feature-interactions | "Function — Internal-to-module import" |

### Disputed

#### review-silent-failures C1 — Tier 1 fall-through behavior
- **Claimed issue**: returning `(0, "trace")` short-circuit instead of fall-through to Tier 2/3.
- **Why disputed**: `(0, "trace")` would suppress `cache.below-min-predicted` even for genuine fall-through cases where cache didn't fire (provider sub-threshold). The right fix is review-silent-failures C2's gate-on-source pattern (action item #2 above) — which is more surgical and DOES suppress the false-positive case (trace nonzero but below-min) without sacrificing the warning's diagnostic value.

#### review-test-fidelity C1 — Test #2 mutation contract wording
- **Claimed issue**: "mutation `> 0` → `>= 0` impossible to introduce."
- **Why disputed**: The mutation IS introducible and the test catches it; reviewer's wording is overly precise. Cosmetic. The strengthening at action item #2 (assert source != "trace" AND tokens != 0) makes the contract more explicit anyway.

### Needs decision (deferred to "Open user decisions" above)

- A: `cache_ratio_pct` vs `cache.discrepancy.actual_pct` semantic clarity
- B: Batch event first-match vs averaging
- C: Fix-first vs fix-after for Stage 2.1 ordering

### Areas verified clean by reviews

- `cost_estimation.py` `or 0` coercions structurally safe (Tier 4 doesn't reach cost math).
- `total_cacheable_tokens_estimated: int` aggregate stays int via `or 0`; behavior byte-identical to today.
- 2.0.0 trace fallback still works via Tier 1 fall-through.
- Padding advisory and consolidate-to-root advisory unaffected.
- Cross-workflow boundary findings unaffected.
- Trace auto-load threading correct.
- `_aggregate_first_run_savings` math IS the intended fix (not double-counting); verified against smoke empirical numbers.
