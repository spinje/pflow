# Task 157 Progress Log — Design Journey

## 2026-04-20 — Design session

### Phase 1: Problem space mapping

Read all four related issues (#318, #323, #321, #297) plus the detailed investigation comment on #318. The investigation comment (from the music-generation pipeline) was the most valuable artifact — it included:
- Minimal repro workflows proving the exact boundary (batch sub-workflow, nothing else)
- A results matrix showing which combinations work vs break
- Evidence that #323 is a downstream consequence of #318, not a separate bug
- A partial finding about cache key stability through sub-workflow re-entry (separate issue, not blocking)

Read task reviews for 156 (dry-run implementation), 96 (batch processing), 131 (batch error handling), 153 (undeclared inputs), and 147 (validator diagnostics). Key takeaways:
- Task 156 review: the `plan_node()` shared primitive, state machine architecture, `_execute_entry` chokepoint, "Option E" pattern. The review explicitly documents the batch-of-sub-workflow gap as TD2 with two candidate approaches.
- Task 96 review: wrapper chain position (batch OUTSIDE namespace), per-item shallow copy pattern, `item_alias` injection at ROOT level
- Task 153 review: `inputs:` is the single canonical form, `ALLOWED_PARAMS` closed schema, heterogeneous batch IR cache
- Task 147 review: "prioritize simplicity of final code, not how easy it is to get there" — Option D (full conversion) over phased approaches. This principle directly applied to our design decisions.

### Phase 2: Initial approach (wrong framing)

First proposed three options:
- **A**: Full per-item recursion (~450 LOC)
- **B**: Representative-item recursion (~200 LOC)
- **C**: Opaque with aggregate stats (~80 LOC)

Recommended **Option B** based on: smaller delta, reuses existing machinery, honest approximation, overestimates (safe for cost-gating).

**This framing was wrong.** It treated the problem as "which approximation strategy for batch sub-workflows" — a patch to bolt onto the existing code. The user's pushback ("prioritize simplicity of final code") forced a reframe.

### Phase 3: Architectural reframe (the real insight)

The actual problem is structural: the planner's dispatch has a hole in a 2×2 matrix.

```
                    non-batch           batch
                    ─────────           ─────
standard node       _plan_standard      _plan_standard (plan_node handles batch keys)
WorkflowExecutor    _plan_sub_workflow   ??? ← hole
```

The engine solves this cleanly: batch is an OUTER concern that wraps per-item execution. `_execute_node` dispatches on batch at the top level; `_execute_single_node` is batch-unaware. This orthogonality is the engine's architecture.

The planner should mirror it: batch dispatch at `_plan_sub_workflow` entry, with per-item planning reusing `_plan_sub_workflow`'s infrastructure.

**Key decision**: The dispatch belongs inside `_plan_sub_workflow` (3-line check at the top) rather than at `_plan_one_node`, because only WorkflowExecutor nodes reach `_plan_sub_workflow`. Standard batch nodes are already handled by `plan_node`'s batch cache key computation.

### Phase 4: Representative vs full per-item (the elderberry argument)

Initially classified full per-item as "overengineering." User challenged: "is it really overengineering if it's correct?"

The decisive example: You run a batch of 5 items, then change "elderberry" to "strawberry" and run `--dry-run`. Representative-item plans with items[0] ("apple") → cached → reports "all cached." But "strawberry" has never been seen — it would execute. The agent proceeds thinking it's free.

**This is not an edge case — it's THE use case for `--dry-run`**: "I changed something, what would re-execute?"

The LOC delta between representative and full per-item is ~50 lines, not 300 as initially estimated. The architecture (dispatch, PlanEntry fields, formatter, aggregation) is the same either way. The inner loop is the only difference.

**Decision**: Full per-item recursion. The ~50 LOC delta buys correctness for the primary use case. And with it, we don't need multiplier heuristics — the aggregated plan reflects real per-item data.

### Phase 5: Display format iteration

Checked actual current output by running `--dry-run` on the lyrics-generator workflow. Discoveries:
- Current cached format: `↻ node  (5s ago)` — recycle symbol + age, NO `✓`
- Current execute format: `▸ node  [type]  ≈ $X · ~Ys (last run Xm ago)`
- Sub-workflow header: `▸ node  [sub-workflow './path' (N nodes)]`
- Batch sub-workflows in BFS mode DO get sub-plans (via `_make_downstream_entry` → `_plan_sub_workflow(cause="downstream")`), but as single iterations
- The pre-boundary batch sub-workflow (`fetch-sources`) shows NO recursion — just flat `[workflow]`

User pointed out: if we show "× 10 items", each child node should show its per-item breakdown. With full per-item data available, the natural display is `M/N would execute` per node.

**Key display decisions:**
- All-cached nodes: normal `↻` format (M/N is redundant when M=N)
- All-execute nodes: normal `▸` format (M/N is redundant when M=0)
- Partial: `▸ node [type]  M/N would execute  ≈ $avg · ~avg_time`
- Only show M/N when it adds information (the partial case)

### Phase 6: Cost and duration semantics

User asked: "if one of the parallel sub-workflows costs differently, we ignore that?"

No — with full per-item recursion we have each item's actual cost from its own cache entry. The per-node cost shown is the average (representative of "what one call costs"), and the summary shows the real sum.

**Cost**: Always additive (parallel doesn't reduce cost). Per-node line shows per-execution average. Summary shows real total.

**Duration**: Depends on execution mode. Per-node line shows per-execution average (how long one call takes — unambiguous). Summary shows parallel-aware total (max for parallel, sum for sequential). This avoids the ambiguity of "does this per-node number represent wall-clock for the batch?"

Decision: Per-execution averages on per-node lines (consistent with non-batch format). Summary handles the batch-level math. The reader understands "2/4 would execute ≈ $0.28 · ~30.6s" as "each execution costs $0.28 and takes 30.6s, and 2 items need it."

### Phase 7: Plan review findings

Deployed 4 review agents (silent-failures, feature-interactions, validation-consistency, impact-completeness). Key findings that changed the implementation:

**1. Dict unpacking order** (silent-failures) — Would have silently used wrong per-item values. `{alias: item, **shared}` puts item first, then shared overwrites it. Must be `{**shared, alias: item}`.

**2. Aggregate by node_id, not position** (silent-failures + feature-interactions) — Branching children produce different entry sequences per item. Positional aggregation would silently mix nodes.

**3. `resolve_templates` directly instead of `plan_node`** (validation-consistency) — Using `plan_node` with stripped `batch_config` computes a meaningless config hash (WorkflowExecutor is never memoized anyway). Calling `resolve_templates` directly is honest about intent and avoids dead computation.

**4. `*_including_nested` must be explicitly computed** (impact-completeness) — Without these, `_summarize` falls back to per-level values and the parent rollup silently under-reports. This was the most complex piece of the aggregation and the plan was hand-waving it.

**5. `_has_any_cached_recursive` needs extending** (feature-interactions) — Without checking `batch_items_cached > 0`, the "nothing cached" divider appears when batch items are partially cached. Cosmetic but directly undermines fix #2 (the cascade symptom).

**6. Per-item output extraction must use declared-output logic** (silent-failures) — Raw `child_shared` includes internal keys that would pollute the batch output shape and cause downstream templates to resolve against keys absent at runtime.

### Phase 8: #321 compatibility verification

Ran a dedicated searcher to verify our approach doesn't conflict with GH #321 (extending shared-primitive pattern to sub-workflow output population + cycle detection).

**Finding**: Our batch wrapper operates ABOVE the abstraction boundary #321 targets. It reads `parent_shared[node_id]` AFTER `_populate_sub_workflow_outputs` writes it. If #321 replaces that function with a shared `compute_child_exposure()` helper, our wrapper is unaffected. **Neutral to #321's goals.**

### Critical insights for the implementer

1. **The `plan_node` batch_config skip is CORRECT for standard batch nodes** — the engine also skips top-level resolution for batch. The fix is NOT "remove the skip" — it's "add a dispatch that handles WE batch nodes before reaching the skip."

2. **`_build_plan_with_shared` creates its own scratch shared** — each per-item call is isolated. No cross-contamination between items. The parent shared is only modified for output population (once, after the loop).

3. **Compile once is safe** because `compile_workflow` validates input PRESENCE, not VALUES. All items use the same child topology — only the input values (and thus cache keys) differ.

4. **The downstream path (`cause="downstream"`) is intentionally left unchanged** — items templates in downstream mode usually depend on would-execute upstream → `resolve_batch_items` returns None → opaque. The fix targets the pre-boundary state-machine path where upstream cached data makes item resolution possible.

5. **Task 147's principle applies directly**: "Task 143 took the pragmatic shortcut and Task 144 had to fix it. The lesson is in the codebase history." We chose full per-item over representative because the "shortcut" (representative) gives wrong answers for the primary use case and would need fixing later.

6. **The `_summarize` NO-CHANGES claim is verified** but depends on the aggregated plan having correct `*_including_nested` fields. If those are wrong or missing, `_summarize` silently under-reports. This is why the review agents flagged it as the most critical piece to get right.

### Rejected alternatives (and why)

| Alternative | Why rejected |
|---|---|
| Representative-item (items[0] × N) | Wrong for "edit one item" scenario — THE primary use case for dry-run |
| `plan_node` with stripped `batch_config` | Computes meaningless config hash for WE nodes. `resolve_templates` directly is cleaner |
| Batch dispatch at `_plan_one_node` level | Only WE nodes need it — standard batch already handled. Dispatch inside `_plan_sub_workflow` is more focused |
| Aggregate by entry position | Breaks for branching children with different entry sequences per item |
| Scale child plan summary (mutate Plan) | Less clean than aggregating from real data. Child plan becomes inaccurate as standalone object |
| `batch_count` multiplier on PlanEntry (without per-item recursion) | Can't detect which specific items are cached/miss. Gives wrong answers |
| Lifting the `WorkflowExecutor` memo cache skip | Fights a documented invariant ("sub-workflow files may change"). Inner nodes already cached individually |
| Phased approach (fix validation error first, cost later) | Task 147's lesson: "phased approaches accrue debt the next task has to fix" |

### Open questions resolved during session

| Question | Answer | Evidence |
|---|---|---|
| Does `resolve_batch_items` work with planner's scratch shared? | Yes — uses TemplateResolver against shared dict. Upstream cached outputs are in shared via `apply_memo_hit`. | batch_executor.py:32-55, confirmed by searcher |
| Can we `dataclasses.replace(config, batch_config=None)`? | Yes — NodeConfig is regular `@dataclass`, not frozen | types.py:37 |
| Does `_summarize` need changes? | No — reads `sub_plan.summary.*_including_nested` which our aggregation correctly populates | Verified by 2 review agents |
| Does our fix break existing batch drift tests? | No — those test standard batch nodes (ShellNode/LLMNode), our dispatch only fires for WorkflowExecutor | Confirmed by searcher |
| Circular import risk? | None — `batch_executor.py` never imports from `execution/` | Confirmed by searcher |
| Is #321 affected? | Neutral — we operate above the level #321 targets | Confirmed by dedicated searcher |

### Session metrics

- ~3 hours of design discussion
- 4 parallel searcher deployments for verification
- 4 parallel review agents for plan review
- 8 review findings incorporated
- 3 rejected alternatives documented
- 6 open questions resolved empirically (not by assumption)

## 2026-04-20 — Implementation

### Step 1: Planner core + result model

Implemented the planner-side batch sub-workflow path:
- Extended `PlanEntry` with batch metadata fields used by parent headers and per-node partial-cache rendering.
- Added the `_plan_sub_workflow()` batch dispatch and implemented `_plan_batch_sub_workflow()`.
- Added `_aggregate_batch_child_plans()` and `_build_batch_output_shape()`.

Verified the edited Python files compile with:
- `python3 -m py_compile src/pflow/execution/plan.py src/pflow/execution/result.py`

Critical implementation notes:
- **Batch output shape intentionally mirrors runtime more closely than the written plan**. The design doc's minimal `{results, count, ...}` sketch omitted runtime-populated keys that downstream templates may already rely on. The planner now writes `item`, `original_index`, and the same `batch_metadata` keys runtime exposes (`parallel`, `max_concurrent`, `max_retries`, `retry_wait`, `execution_mode`, `timing=None`). This keeps plan-time downstream resolution aligned with runtime shape instead of only solving `${node.results}`.
- **Synthetic entry ordering is first-seen across ALL item plans, not only item[0]**. The written pseudocode preserved order from `child_plans[0]`, but that drops branch-only nodes that appear in later items. The implementation preserves first-seen order while still aggregating by `node_id`.
- **Synthetic cached-count logic treats fully-cached nested sub-workflows as cached items**. Counting only `entry.status == "cached"` would incorrectly mark nested `sub_workflow` entries as misses even when their child plans are fully cached.
- **Opaque counts are aggregated explicitly** in the synthetic `PlanSummary`. The implementation plan called out `*_including_nested` rollups but did not mention `opaque_count`; omitting it would silently under-report unresolved nested work in parent summaries.

Known limitation introduced by the current aggregation:
- For child nodes that appear only on some per-item branches, the per-node `batch_items_total` currently remains the full outer batch size because that is the task's display contract (`M/N` over total items). This is conservative, but it means branch-specific nodes are displayed against the full batch, not only the items that traverse that branch.

### Step 2: Formatter + tests

Implemented the display layer and pinned the new behavior with tests:
- Updated `plan_formatter.py` for batch parent headers, partial-cache child lines, JSON batch fields, and the recursive cached-divider guard.
- Added `tests/test_execution/test_plan_batch_sub_workflow.py` for the new planner path.
- Added a drift-catcher to `tests/test_execution/test_plan_drift.py` that compares partial batch-sub-workflow planning against a real second execution.
- Extended formatter tests with the new batch-specific rendering/JSON expectations.

Verification:
- `.venv/bin/python -m pytest tests/test_execution/test_plan_batch_sub_workflow.py tests/test_execution/formatters/test_plan_formatter.py tests/test_execution/test_plan_drift.py -q`
- Result: `51 passed`

Critical notes from this step:
- **The opaque-items unit test must bypass `WorkflowRunner.plan()`**. The validator correctly rejects `${missing.items}` before the planner runs, so the opaque fallback is only reachable when testing `build_plan()` directly on compiled IR. This is a test-shape constraint, not a planner bug.
- **Cached formatter assertions need to account for ANSI styling**. Cached icons are rendered through `click.style(...)`, so tests should assert on the semantic payload (`(5s ago)`, absence/presence of `M/N would execute`) rather than a raw unstyled line match.

### Step 3: Documentation + broader verification

Completed the docs pass and ran broader execution-surface verification:
- Updated `src/pflow/execution/CLAUDE.md` with a dedicated "Batch sub-workflow planning" subsection covering the new dispatch, compile-once/plan-N-times pattern, aggregation by `node_id`, output-shape parity, and formatter fields.
- Kept the display string source ASCII-safe by using `\u00d7` in code/tests while preserving the required rendered output (`×`).
- Refactored the two planner functions into smaller helper primitives instead of suppressing `C901`.

Verification:
- `.venv/bin/ruff check --target-version py310 src/pflow/execution/plan.py src/pflow/execution/result.py src/pflow/execution/formatters/plan_formatter.py tests/test_execution/test_plan_batch_sub_workflow.py tests/test_execution/test_plan_drift.py tests/test_execution/formatters/test_plan_formatter.py`
- `.venv/bin/mypy src/pflow/execution/plan.py src/pflow/execution/result.py src/pflow/execution/formatters/plan_formatter.py`
- `.venv/bin/python -m pytest tests/test_execution -q`
- Result: `ruff` clean, `mypy` clean, `417 passed`

Environment note for future agents:
- `uv run ...` was not usable in this sandbox because `uv` attempted to access a cache path outside the writable roots (`~/.cache/uv/...`) and failed with `Operation not permitted`. Local verification was run through the repo's `.venv/bin/*` tools instead.

### Step 4: Remove `C901` suppressions

User explicitly rejected the temporary `# noqa: C901` markers. Removed them by further decomposing `src/pflow/execution/plan.py`:
- Added `_precheck_sub_workflow()`, `_prepare_sub_workflow()`, `_prepare_batch_sub_workflow_params()`, `_plan_batch_sub_workflow_items()`, and a few smaller support helpers.
- Moved the downstream placeholder-input substitution into `_prepare_sub_workflow()` so the standard sub-workflow path keeps the old behavior without carrying the branching in `_plan_sub_workflow()` itself.
- Restored full inherited `visited_paths` propagation in the per-item batch child loop after the extraction. This was the only subtle regression risk introduced by the refactor.

Verification:
- `python3 -m py_compile src/pflow/execution/plan.py`
- `.venv/bin/ruff check --target-version py310 src/pflow/execution/plan.py`
- `.venv/bin/mypy src/pflow/execution/plan.py`
- `rg -n "# noqa: C901" src/pflow/execution/plan.py`
- `.venv/bin/python -m pytest tests/test_execution -q`
- Result: no `# noqa: C901` remain in the planner file; `417 passed`

### Step 5: Code review fixes + regression tests

Two code reviews (8 agents total) found 6 actionable issues in the staged implementation. All fixed in this step:

**Critical fixes:**
1. **Branching denominator**: `batch_items_total` was hardcoded to `batch_count` (total items). For conditional child workflows, branch-local nodes appeared as partial misses even when fully cached for their respective items. Fix: use `len(entries_for_node)` (items that actually traversed this node) as the denominator.
2. **Silent fallback on non-dict per-item inputs**: When `TemplateResolver.resolve_nested` returned a non-dict for one item's inputs, the planner silently fell back to item[0]'s inputs. Runtime would raise `ValueError`. Fix: still fall back (so other items can proceed) but emit a WARNING diagnostic surfacing the likely runtime failure.
3. **Duplicated resolver warnings**: Child workflow warnings were attached per item (N copies). Fix: attach once to `child_plans[0]` only — warnings describe the child workflow, not individual items.

**Defensive improvements:**
4. **`except ValueError` → `except Exception`**: The planner should never crash on malformed templates. Broadened catch with type-specific dispatch: `ValueError` → `_template_error_entry`, others → `_sub_workflow_error_entry` with log.
5. **Missing `age_sec`**: All-cached synthetic entries had no cache age. Fix: aggregate `max(age_values)` from per-item entries (shows stalest cache — conservative).
6. **3-way merge parity**: Batch path skipped `curr.params` seed that the non-batch path uses. Fix: mirror the 3-way merge pattern (`curr.params` → `static_params` → `resolved_params`).

**Structural improvement (also resolves C901 on `_aggregate_batch_child_plans`):**
- Extracted `_nested_or_level` helper and `_aggregate_batch_summary` function. Eliminates seven near-identical list comprehensions and keeps the aggregation function under complexity budget.

**Regression tests added:**
- `test_plan_batch_sub_workflow_branching_child_reports_correct_per_node_status`: Conditional child with 2 branches, verifies branch-local nodes show correct `batch_items_total` and `status="cached"`.
- `test_plan_batch_sub_workflow_non_dict_per_item_inputs_emits_warning`: One item resolves inputs to non-dict, verifies WARNING diagnostic surfaces.

Verification:
- `uv run make check` — clean (ruff + format + mypy + deptry)
- `uv run pytest tests/test_execution/` — `419 passed`
- `uv run make test` — `5206 passed`
- Manual: re-ran the simple repro (parent.pflow.md + child.pflow.md) — all 3 scenarios (fresh/cached/partial) produce correct output

### Step 6: PR review fixes + end-to-end verification

PR review (#332 comment) identified 3 warnings:
1. Unused `batch_count` parameter in `_aggregate_batch_child_plans` — became dead after the `len(entries_for_node)` fix. Removed.
2. Redundant nested `if config.template_config:` check — copy-paste artifact from the 3-way merge fix. Removed.
3. Broad `except Exception` — reviewer suggested narrowing. Kept intentionally (planner must never crash). Removed the `# noqa: BLE001` comment that ruff auto-stripped anyway.

End-to-end verification on lyrics-generator pipeline:
- Ran the full pipeline ($2.43, ~7 min) to populate fresh cache entries
- Dry-run immediately after: `fetch-sources` (batch) and `analyze-sources` (batch) correctly show `↻` cached
- 12 cached · 33 would execute (vs the old "0 cached · 47 would execute")
- No validation error

### Step 7: Root-cause investigation of pre-existing cache key drift

The lyrics-generator dry-run showed `assign-diversity` (inside `enforce-diversity`) as a cache miss even though it was just written 6 minutes ago. Investigated to determine if this was our bug or pre-existing.

**Attempted repros (all PASSED — no drift):**
1. Complex nested Python data (20 items, unicode, floats, nested dicts) — stable
2. LLM structured output through sub-workflow boundary — stable
3. Chained LLM sub-workflows (step1 → step2, structured JSON crossing boundary) — stable

**Root cause found by comparing runtime trace vs planner cache data:**

The runtime trace showed `assign-diversity`'s resolved `concepts` input with dict keys in INSERTION ORDER (as the LLM produced them): `['title', 'core_idea', 'angle', 'why_compelling', ...]`. The planner's version (read from cache via `json.loads`) had keys in ALPHABETICAL ORDER: `['angle', 'core_idea', 'emotional_core', ...]`.

**The bug**: `cache.py` stores output blobs with `json.dumps(sort_keys=True)`. This is correct for cache KEY computation (deterministic hashing) but WRONG for cache VALUE storage — it destroys insertion order. When cached structured output is restored and stringified into a downstream prompt template via `str()` or `json.dumps()`, the alphabetical key order produces a different string → different cache key → false miss.

**Filed as GH #333** with full repro steps, diagnostic evidence, and suggested fix (separate `sort_keys=True` for hashing from `sort_keys=False` for storage — one-line change in `cache.py`).

**Confirmed NOT caused by our batch fix** — affects non-batch sub-workflows identically. The batch sub-workflow nodes (`fetch-sources`, `analyze-sources`) correctly show as cached. Only `assign-diversity` (a non-batch node downstream of a non-batch sub-workflow) drifts.

### Final state

- PR #332 open with all review fixes
- 5206 tests pass, `make check` clean
- GH #333 filed for the pre-existing cache key drift (separate fix)
- All three original symptoms fixed for the documented scope:
  - ✅ No false validation error
  - ✅ Batch sub-workflow nodes show per-item cache status
  - ✅ Downstream nodes resolve templates (no "nothing cached" cascade)
