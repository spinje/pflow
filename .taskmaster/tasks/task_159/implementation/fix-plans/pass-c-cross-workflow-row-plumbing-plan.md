# Pass C: Cross-Workflow → Per-Call Row Plumbing + Recommendation Cleanup-Hint Extension

> **Branch**: `feat/prompt-caching` (Task 159 follow-up).
> **Plan version**: 1.2 (post Pass A/B landing + 4-searcher correctness audit + 4-reviewer plan review).
> **Scope**: ~180-220 LOC. One PR (C0-C5 land together; C0 is the recommendation-gate fold-in added in v1.2).
> **Verification status**: v1.0 had 6 searchers; v1.1 added a 4-searcher correctness audit; v1.2 adds a 4-agent plan review (`review-plan` + `review-silent-failures` + `review-feature-interactions` + `review-agent-ux`) that surfaced 9 confirmed defects in v1.1, 1 disputed (verified — plan was wrong), and 1 scope decision that landed as the C0 fold-in below.
>
> **What changed in v1.2** (load-bearing — read these even if skipping the rest):
>
> 1. **Tier label rename**: `cross_workflow_candidate` (v1.1 name) → **`cross_workflow_projection`**. Every existing tier name describes evidence SOURCE (`trace`, `memo`, `parameters`, `estimator`, `heuristic`, `batch_prefix`); the v1.1 name described a HYPOTHESIS, breaking the column's vocabulary pattern. `cross_workflow_projection` is parallel to `batch_prefix`/`estimator` (both projection-tier names).
> 2. **`_RowCrossWorkflowCandidate` field count corrected from 4 → 5.** The v1.1 plan claimed the dataclass needed 4 fields matching `_SubWorkflowCacheCandidate`; verification (review agent + direct read of `analyze.py:4159-4170`) showed `_estimate_parent_value_tokens` reads `candidate.parent_node_id` for Tier 3 input-passthrough. **Tier 3 is exactly the canary's success path** — `concept` is a workflow-input passthrough. Without `parent_node_id`, every Tier-3-exercising test crashes with `AttributeError`.
> 3. **`_estimate_parent_value_tokens` refactor — take 5 explicit fields, NOT a candidate object.** The duck-typed candidate contract was the root cause of #2 above and remains fragile against future `isinstance` checks. v1.2 refactors the helper signature to take `parent_workflow`, `parent_value_expr`, `parent_node_id`, `child_workflow`, `child_input_name` directly. Single existing caller (`_emit_sub_workflow_cache_findings`) updated; eliminates duck-type contract entirely.
> 4. **`ctx.iter_llm_leaves()` does NOT exist.** Real primitive is `ctx.trace.iter_llm_leaves(edges=..., workflow_path=...)` per `analyze.py:1110`. v1.1 pseudocode is wrong; would AttributeError at first run.
> 5. **Call-counting key needs the `leaf.tier` conditional.** Canonical keying at `analyze.py:1114-1115`: `node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id`. v1.1's `(workflow_path, event_node_id)` is incomplete and silently mis-attributes leaves with `tier != "sub_workflow_descendant"` to wrong rows, breaking the total-invocations gate.
> 6. **C0 — recommendation-gate fold-in (NEW SUB-STEP)**. v1.1 documented the row-vs-recommendation gate divergence (row uses total-invocations; recommendation uses consumer-count) as a "known follow-up." All 4 review agents flagged it as a real UX gap. **v1.2 folds the recommendation gate into Pass C scope**: loosen `_sub_workflow_cache_candidate`'s gate from `consumer_count >= 2` to `total_invocations >= 2` so row + recommendation stay in lockstep universally. Pass C creates the divergence by introducing the universal row gate; fixing it in the same PR preserves the user's "broad fix that fixes this for everything" directive.
> 7. **Static-batch clamp guard promoted from optional → MANDATORY.** Three reviews and the braindump converged on this. C3 must gate the cohort multiplier on `not _is_static_batch_trace_row(...)`.
> 8. **Heterogeneous-children threshold: max across child models, not first-only.** First-child sampling silently over-admits (e.g., Sonnet floor 1024 passes for a candidate that fails Opus's 4096). v1.2 takes `max(get_min_cache_tokens(m) for m in child_models)` for the threshold check.
> 9. **Footer prose names affected rows + points at BOTH sections.** v1.1's "see Recommended actions" mis-routes for rows whose cross-workflow inputs only surface in `## Sub-workflow boundaries`. v1.2 footer enumerates the affected rows and references both sections.
> 10. **Cleanup-hint clause preserves "or rewrite to literal text"** (Pass B convention) **and adds the missing "Before declaring X in Y" antecedent.**
> 11. **Multi-candidate row notes column** lists contributing inputs (`cw=creative_direction+song_architecture`) when candidates > 1. Otherwise the agent sees one summed number with no decomposition.
> 12. **Greenfield asymmetry note** — when trace is absent but cross-workflow recommendations would fire, emit a Notes line routing the agent to `--from-trace`. Without it, recommendation says "$0.20/run" while affected rows show `?` — agent self-diagnoses incorrectly.
> 13. **`_representative_model_for_edge` filters `${...}` template strings** as unresolved (mirror `_resolve_effective_row_model` precedent). Unfiltered, `get_min_cache_tokens("${model}")` chokes.
> 14. **Risk-register text fix**: v1.1 said "boundary skips entirely (not partial sum)" when partial sums actually fire. Per-edge skip with row populating from resolving edges is the correct semantic. Documentation bug.
> 15. **Test #17 (1-line parametrize extension) REMOVED — DEAD WORK.** Verified at `tests/test_core/test_cache_analysis_warnings.py:744-753`: the existing parametrize already includes `cache.sub-workflow-cache-undeclared`. C5 only adds context fields (identity tuple unchanged) → existing test already covers Pass C's regression. v1.2 test count: 16 numbered + auto-derived per-id-coverage stub = 17 total touched. Plus 6 NEW tests added (canary positive lock, Pass B × C co-emission, partial-resolve sum, static-batch clamp, 3-level nesting, conditional-dispatch unreached).
>
> **What v1.1 still got right** (preserved verbatim):
> - **Precedence**: fallback-only (`cacheable_tokens is None or cacheable_data_source == "unavailable"`). Avoids score-choruses double-count where `${concept.core_idea}` is inside batch_prefix's static prefix.
> - **SUM combinator** for multi-candidate (DD#11 single-breakpoint marker layout — chunks contiguous, body separate).
> - **Already-declared gate** in C2 (skip when `child_input_name in child_declared`).
> - **Below-min-tokens gate** (cohort_total >= threshold).
>
> **Plan line numbers are stale by ~80-120 lines** (verified pre-v1.2). Re-verify by name (`rg <helper_name>`) before coding; trust names, not line numbers.

---

## Context

Pass A and Pass B shipped (commits in the staged tree). They fix:
- Cohort-vs-per-call discipline for static-list batch trace rows (Pass A.A2).
- Visibility predicate parity (Pass A.A1).
- Partial-declaration detection inside `## Cache`-declared workflows (Pass B / `cache.prompt-cache-incomplete`).

But the canonical agent-UX gap from `select-chorus-and-tier2-scope-gap-handoff.md` remains visible:

```
### chorus-chooser.pflow.md (called by choose-chorus)
  select-chorus            gemini/gemini-2.5-flash   36,289           —           41     0%      4
```

After Pass A's Tier-2 chunk × call_count fix, this row may now show `~164` instead of `41` (depending on baseline regen state) — but the agent UX is still misleading. The actionable cache opportunity is the cross-workflow `concept` input flowing in from song-creator (recommendation #1, `~$0.20/run` projected). The per-call row doesn't reflect that.

Plan v2 (the partial-declaration plan) marked cross-workflow → per-call row plumbing as "deferred permanently" with the rationale that doing it naively misleads (rows would project tokens that only cache after a prompt-body restructure). That framing was wrong: the plumbing IS clean if (a) the row signals a `cross_workflow_projection` tier label, (b) the existing `cache.sub-workflow-cache-undeclared` recommendation gains a cleanup-hint extension so agents who apply it don't subsequently trigger `cache.prompt-body-shadows-cache` warnings.

This plan ships both halves together. By construction, the fix applies to ANY workflow with cross-workflow boundaries — not just lyrics-generator. Estimated ~5-7 rows in the lyrics-generator canary will gain meaningful `could_cache` projections.

---

## Out of scope (unchanged from plan v2)

- **N1**: Heuristic A non-batch prefix projection. Verifier #4 confirmed sub-threshold for canonical select-chorus case. Stays deferred.
- **N3**: 5-field PerCallRow split. Still no current consumer.
- **N4**: Diagnostic dedup hash extension (cross-cutting). Still deferred. Pass C inherits the same latent risk as 4 existing IDs; locks current behavior with regression test.
- **N5**: Tier 2 chunk × call_count for non-batch repeated rows ALREADY landed via Pass A.A2 changes. Confirmed by Searcher 3 in `token_estimation.py::estimate_cacheable_tokens` (`resolved_chunk_call_count` parameter).

**Removed from out-of-scope**: cross-workflow → per-call row plumbing. That's the body of this plan.

---

## Verified facts (from 6 parallel searchers, post-Pass-A/B landing)

### Codebase state

| Fact | Source | Citation |
|---|---|---|
| `cw_result` built at `analyze.py:566` BEFORE per-call rows at `analyze.py:604` | Searcher 1 | `analyze.py:566` |
| `_build_per_call_rows_and_warnings` already takes `cw_result` as a parameter | Searcher 1 + 4 | `analyze.py:1395-1424` |
| `_SubWorkflowCacheCandidate` constructed AFTER per-call rows (inside `_build_cross_workflow_findings`) — must be lifted earlier or recomputed inline | Searcher 1 | `analyze.py:3737-3796` |
| `_estimate_parent_value_tokens` is 4-tier: parameters → memo → trace-by-node-id → parent-invocation input-passthrough. Returns None if all fail | Searcher 1 | `analyze.py:4008-4052` |
| `_collect_llm_nodes_referencing_path` uses literal-or-dotted-prefix matching | Searcher 1 | `analyze.py:4213-4252` |
| `_project_sub_workflow_cache_savings` already returns `(savings_usd, tokens_estimated, threshold_model)`. Picks first child's model only (heterogeneous-children limitation acknowledged in code) | Searcher 1 | `analyze.py:4055-4106` |
| `_prefer_batch_prefix_cacheable_tokens` uses max-merge (`prefix > (current or 0)`) | Searcher 1 | `analyze.py:2139-2164` |
| `cacheable_data_source` is a documented-only `str` (NOT type-enforced). 5 current values | Searcher 2 | `analyze.py:130-142` |
| **No cost helper references `cacheable_data_source`**. Cost gates exclusively on `declared_prompt_cache` (5 sites verified) | Searcher 3 | `cost_estimation.py:267-291, 510-545, 548-564, 474-507` |
| Pass A.A2 landed with `_is_static_batch_trace_row` + `_divide_static_batch_trace_tokens` helpers. Uses `round()` | Searcher 3 | `analyze.py:1518-1529, 1645-1669` |
| Pass A.A1 landed with thin shim in `render_text.py:1527-1530` (`_row_has_real_data` delegates to `view_helpers.per_call_row_has_real_data`) | Searcher 3 | `view_helpers.py:59-73` |
| Pass B landed with cleanup-first ordering, `_compute_prompt_body_cleanup` reuse | Searcher 3 + 6 | `analyze.py:3060-3115, 3280-3334` |
| `_build_summary` (NOT `_build_summary_for_rows`) multiplies per-call by `_row_invocation_count` | Searcher 3 | `analyze.py:4905, 4952` |
| `rows_by_node_path = {(row.workflow_path, row.node_path): row for row in per_call_rows}` precedent (Pass B) | Searcher 4 | `analyze.py:693` |
| `_compute_prompt_body_cleanup` is a function in two flavors: greenfield (`analyze.py:3060-3095`) returns `dict[str, list[str]]`; per-node Pass B variant `_prompt_body_cleanup_for_node` (`analyze.py:3098-3115`) returns `tuple[str, ...]`. **Pass C reuses the per-node variant** | Searcher 6 | `analyze.py:3098-3115` |
| `compute_overlaps` returns 3 kinds: `duplicate`, `cache_contains_body`, `body_contains_cache`. NO subpath skipping. `${concept.title}` against cache item `concept` → `cache_contains_body` (warns post-edit as `cache.prompt-body-shadows-cache`) | Searcher 6 | `cache_overlap.py:137-187` |
| Existing baseline at `04-warning-catalog/05-cache.sub-workflow-cache-undeclared/` uses bare `${article}` in child prompts — does NOT exercise subpath body refs. **Pass C needs new baseline coverage for subpath case** | Searcher 6 | `04-warning-catalog/05-...` |
| Multi-candidate per-row: existing precedent emits ONE diagnostic per `(child_workflow, child_input_name)` boundary. For row-level token estimation, **SUM tokens across candidates** (independent prefix chunks) | Searcher 4 | `analyze.py:4159-4210` |
| `observed_call_count` for child-workflow rows correctly equals trace event count via `iter_llm_leaves` keying on `(workflow_path, event_node_id)` | Searcher 4 | `analyze.py:1100-1111, 1486` |

### Precedence between `batch_prefix` and `cross_workflow_projection` (FALLBACK-ONLY — v1.1)

Both can fire on the same node (e.g., `score-choruses` has its own `batch:` config AND receives cross-workflow `concept`). v1.0 picked max-merge after weighing the trade-offs. v1.1's correctness audit (4 searchers, 2026-05-10) overturned that decision.

**Decision (v1.1, locked)**: Pass C populates only when no other source has data:

```python
if cacheable_tokens is None or cacheable_data_source == "unavailable":
    # ... compute cross-workflow cohort, populate ...
```

When `batch_prefix`, `parameters`, `memo`, `trace`, `estimator`, or any other tier has data, Pass C does NOT overwrite.

**Why fallback-only (grounded in audit findings)**:

1. **Score-choruses' prompt body uses `${concept.core_idea}` INSIDE the static prefix that `batch_prefix` already detects.** Reading `score-chorus.prompt.md` directly (audit searcher 4):
   - Static prefix: ~1,061 tokens × 136 calls = 144,296 (matches the canary's `batch_prefix` value)
   - The `${concept.core_idea}` reference (line 7) is part of that prefix
   - `concept` chunk content is therefore **already counted** in the 144k batch_prefix
   - Max-merge would inflate by `concept_tokens × 136` ≈ 3,000-7,000 token double-count
   - Worse: the row's source label would flip from `batch_prefix` → `cross_workflow_projection`, and the confidence-footer prose ("remove inline body refs") would tell the agent to do the wrong thing — the body refs are *inside* the prefix that `batch_prefix` already captures.

2. **`score-choruses` already has a clean recommendation story** (post-prompt-shape Tiers 1+2 landing): `cache.batch-prewarm-recommended` action surfaces it; the row carries a `batch-prewarm-recommended` note. Inserting a `cross_workflow_projection` overlay creates competing signals where there was one.

3. **`cross_workflow_projection` is by construction a weaker evidence tier than `batch_prefix`/`memo`/`parameters`/`trace`**: it's a hypothetical projection that requires the agent to apply a recommendation (declare in child's `## Cache` + clean body refs). Honest unmeasurable convention says: defer to stronger evidence when it exists.

**Effect on the canary** (post-Pass-C, fallback-only):

| Row | Current state | Pass C effect |
|---|---|---|
| `select-chorus` | `could_cache=164` (Tier 2 chunk × call_count, tiny) | populated `cross_workflow_projection` (~5,000+) — `concept` × 4 calls × min-threshold gate |
| `review` rows in `review-rhyme`, `review-stranger-summary` | `?` | populated from `creative_direction` + `song_architecture` |
| `concept-chooser` children, `enforce-diversity`, `analyze-source` | `?` | populated where parent value resolves |
| `score-choruses` | `batch_prefix=144,296`, note=`batch-prewarm-recommended` | **unchanged** (batch_prefix wins; no overlay) |
| `generate-chorus-options` | `?` (opaque) | unchanged |
| Root workflow nodes (`curate-briefs`, `evaluate-songs`) | `?` | unchanged |

**Trade-off (accepted)**: For workflows where `batch_prefix` and `cross_workflow_projection` would point at *truly disjoint* prefix segments, fallback-only undercounts. This case is structurally rare in practice — when both fire, the cross-workflow input is almost always referenced inside the static prefix the heuristic detects. If a real workflow surfaces where the under-count is misleading, revisit precedence; do NOT speculatively design for it now.

### Multi-candidate row semantics

A child node can consume multiple cross-workflow inputs (e.g., `review-rhyme` receives both `creative_direction` and `song_architecture`). Pass C's per-row token estimate = `sum(candidate.estimated_tokens_per_call for candidate in row_candidates) × observed_call_count`. Independent prefix chunks; sum reflects the TOTAL cacheable opportunity. Renderer/notes can list them individually.

**SUM verified correct (v1.1 audit, searcher 3)**: pflow's `_build_system_blocks` (`src/pflow/nodes/llm/llm.py:540-609`) renders each declared chunk as a contiguous content block at the head of the `system` message; the prompt body lives in a separate `user` message; one `cache_control` marker is attached to the LAST block only (DD#11 single-breakpoint). The cached prefix is contiguous; chunks cannot be fragmented by body interleaves; ABSENT chunks are filtered out without splitting the prefix. Therefore `SUM(tokens(a) + tokens(b))` is the correct combinator across N declared chunks; `MAX` would underestimate.

### Boundary-level economic gate (v1.2 — applied to BOTH row and recommendation paths)

For a given cross-workflow boundary `(parent_workflow, parent_value_expr, child_workflow, child_input_name)`, the analyzer computes:

```python
total_invocations = sum(observed_call_count_for(child_workflow, consumer_node_id)
                        for consumer_node_id in consumer_node_ids)
```

If `total_invocations < 2`, skip the boundary entirely (no row populates AND no recommendation fires). Caching the same content sent only once is a net loss (cache write costs ~25% extra; no read ever amortizes it).

**v1.2 (C0 fold-in)**: this gate now applies to BOTH the row path AND the recommendation path. v1.0's `len(consumer_node_ids) >= 2` gate inside `_sub_workflow_cache_candidate` is REMOVED; replaced by the same total-invocations gate at the recommendation emission site (`_emit_sub_workflow_cache_findings`). v1.1 had documented this as a known follow-up; the four-agent v1.2 plan review converged on folding it in. The new gate is strictly more accurate:

| Scenario | Old gate (`consumer_count >= 2`) | New gate (`total_invocations >= 2`) | Caching pays off? |
|---|---|---|---|
| 2 consumers × 1 call each | ✓ pass | ✓ pass | yes (sum=2; same content sent twice across consumers) |
| 1 consumer × 4 calls | ✗ fail | ✓ pass | yes (sum=4; same content sent 4 times) |
| 1 consumer × 1 call | ✗ fail | ✗ fail | no (sum=1; no reuse) |
| 2 consumers × 0 calls each | ✓ pass (incorrectly) | ✗ fail (correctly) | no (no observed evidence) |

**Effect on existing emission tests**: the 16 existing `cache.sub-workflow-cache-undeclared` tests at `tests/test_core/test_cache_analysis_per_id_emission.py:293-1278` may include cases that asserted suppression-by-consumer-count. Walk each pre-coding; tighten any test that would silently break under the new gate. Test #8 explicitly locks the new gate for both row and recommendation.

For the canary, the gate change is moot — `concept` has 2 consumers (`score-choruses`, `select-chorus`) and is sent 140× total → both old and new gates pass; recommendation #1 fires as today.

The shared `call_counts_by_node` dict (computed once in C2's pre-loop walk) feeds both gate evaluations — no double-walking, no drift between universes.

### Below-min-tokens gate (existing convention, applied to row path)

In addition to the total-invocations gate, Pass C applies the existing min-cache-tokens threshold from the recommendation path (`_below_threshold_clause` precedent at `_emit_sub_workflow_cache_findings`):

```python
child_models = _resolved_models_for_child(child_ir)  # filters ${...} templates
if not child_models:
    continue  # honest unmeasurable; no resolved-model LLM node in child
threshold_floor = max(get_min_cache_tokens(m) for m in child_models)  # v1.2: max across children
cohort_total = token_estimate_per_call * total_invocations
if cohort_total < threshold_floor:
    continue  # below provider minimum; cache wouldn't fire
```

**v1.2 changes from v1.1**:
- `_resolved_models_for_child` returns the FULL list (filters `${...}` template strings as unresolved), not a single first-only model.
- Threshold uses `max` across child models, not first-only. Avoids silently admitting candidates that would fail for the strictest child model (e.g., Sonnet 1024 floor passes a 2000-token cohort that would fail Opus's 4096 floor).
- Token estimation still uses `child_models[0]` (first-resolved) for the actual `_estimate_parent_value_tokens` call — only the threshold check is max-aware. Single estimate per boundary (same content for every consumer); the threshold check is the per-child-model gate.

---

## Implementation

### C0. Recommendation-gate fold-in (v1.2 NEW — ~25 LOC)

Loosen `_sub_workflow_cache_candidate` to use the same total-invocations gate as the row path. Eliminates the v1.1 row-vs-recommendation divergence (where 1-consumer-many-calls boundaries populate a row but emit no recommendation).

**Changes**:

1. **Refactor `_estimate_parent_value_tokens` signature** — takes 5 explicit fields instead of `candidate: _SubWorkflowCacheCandidate`:

   ```python
   def _estimate_parent_value_tokens(
       *,
       parent_workflow: str,
       parent_value_expr: str,
       parent_node_id: str,
       child_workflow: str,
       child_input_name: str,
       model: str,
       ctx: AnalysisContext,
       cw_result: Any,
   ) -> int | None:
       ...  # body unchanged; replace `candidate.X` → bare field access
   ```

   Update the single existing caller (`_emit_sub_workflow_cache_findings`) to pass the fields directly from its candidate. Remove the duck-type contract.

2. **Remove `len(child_node_ids) >= 2` gate from `_sub_workflow_cache_candidate`** at `analyze.py:3906`. The constructor now returns a candidate for any (parent_value_expr non-empty, child_input_name not already declared) boundary regardless of consumer count.

3. **Add total-invocations gate at the recommendation emission site** (`_emit_sub_workflow_cache_findings`):

   ```python
   total_invocations = sum(
       call_counts_by_node.get((candidate.child_workflow, node_id), 0)
       for node_id in candidate.child_node_ids
   )
   if total_invocations < 2:
       continue  # caching loses money or is unobservable
   ```

4. **Thread `call_counts_by_node` from `_build_per_call_rows_and_warnings` through to `_emit_sub_workflow_cache_findings`.** C2 already pre-computes this dict (see C2 below); the recommendation site reuses the same dict — single source of truth, no double-walking.

**Existing emission tests update**: tests that exercise 1-consumer cases historically expected NO emission (gate dropped them). With C0, they expect emission IF total-invocations ≥ 2. Affected tests at `tests/test_core/test_cache_analysis_per_id_emission.py:293-1278` — review the 16 existing `cache.sub-workflow-cache-undeclared` tests; tighten any that asserted suppression-by-consumer-count to instead assert suppression-by-total-invocations. New positive test added in §Tests covering the 1-consumer-many-calls case.

**Documentation update**: `cache_analysis/CLAUDE.md` and the catalog entry's docstring should note the gate is now total-invocations. The "no_parent_expr / child_already_declares / fewer-than-two-LLM-consumers" docstring at `analyze.py:3886-3895` (per audit searcher 2) becomes "no_parent_expr / child_already_declares / fewer-than-two-total-invocations."

**Why this is in scope**: Pass C *creates* the divergence by introducing the universal row gate. All 4 v1.2 review agents flagged it as a real UX gap. User directive: "Of course we want the broad fix that fixes this for everything, not just this workflow."

---

### C1. New thin row-level dataclass (~6 LOC)

**v1.2: 5 fields, not 4.** v1.1 missed `parent_node_id` which `_estimate_parent_value_tokens` reads at `analyze.py:4159-4170` for Tier 3 (`_resolve_input_at_workflow_node_invocation`). Tier 3 is exactly the canary's success path (`concept` is a workflow-input passthrough, not a node output). Without `parent_node_id`, every Tier-3 test crashes with `AttributeError`.

Add a frozen dataclass in `analyze.py` near `_SubWorkflowCacheCandidate`. **Do NOT reuse `_SubWorkflowCacheCandidate`** — its constructor `_sub_workflow_cache_candidate(...)` carries the `consumer_count >= 2` gate (now folded into Pass C scope at C0 — see below) plus other dedup machinery. The row path applies its own gates explicitly.

**v1.2: `_estimate_parent_value_tokens` is being refactored to take 5 explicit fields, NOT a candidate object.** This eliminates the duck-type contract entirely (rationale: review-silent-failures S3 — duck-type is fragile against future isinstance checks). With the explicit-fields refactor, `_RowCrossWorkflowCandidate` no longer needs to "match" `_SubWorkflowCacheCandidate`'s shape — it's a self-contained row-level data carrier.

```python
@dataclass(frozen=True)
class _RowCrossWorkflowCandidate:
    """Per-row cache opportunity from a cross-workflow boundary.

    Distinct from `_SubWorkflowCacheCandidate`:
      - `_SubWorkflowCacheCandidate` is for recommendation emission. Its
        constructor `_sub_workflow_cache_candidate(...)` historically gated
        on `len(child_node_ids) >= 2`; v1.2 (Pass C C0) replaces that with
        `total_invocations >= 2` so row + recommendation stay in lockstep.
      - `_RowCrossWorkflowCandidate` is for per-call row population.
        Stores enough to call _estimate_parent_value_tokens directly via
        explicit-fields call (post-v1.2 refactor).
    """
    parent_workflow: str
    parent_value_expr: str
    parent_node_id: str            # v1.2 ADDED — required for Tier 3 input-passthrough
    child_workflow: str
    child_input_name: str
    estimated_tokens_per_call: int
```

`edge.parent_node_id` is already on `CrossWorkflowEdge` (mirrors `_SubWorkflowCacheCandidate.parent_node_id` per `analyze.py:3871`). C2 populates from the edge.

### C2. Per-row candidate dict builder (v1.2 — ~70 LOC)

**v1.2 changes from v1.1**:
- Use `ctx.trace.iter_llm_leaves(edges=..., workflow_path=...)` (NOT `ctx.iter_llm_leaves()` which doesn't exist).
- Apply the canonical leaf-tier conditional when keying call counts: `node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id` (mirrors `analyze.py:1114-1115`).
- Call `_estimate_parent_value_tokens` with explicit fields (post-C0 refactor), NOT a candidate object.
- Use `max(get_min_cache_tokens(m) for m in child_models)` for the threshold check (NOT first-only — first-only silently over-admits in heterogeneous-children case).
- Filter `${...}` template strings as unresolved in `_representative_model_for_edge` (mirror `_resolve_effective_row_model` precedent).
- Add `from dataclasses import replace` import at the top of `analyze.py` (or use a small constructor pattern; see code below).
- The `cross_workflow_candidates_by_row` dict is shared with the C0 recommendation-emission path — single source of truth.

In `_build_per_call_rows_and_warnings` (find by name, ~`analyze.py:1395`), BEFORE the workflow-IR walk loop, compute call counts once and build the lookup dict.

```python
# Pre-compute observed call counts per (workflow_path, node_id) for the
# total-invocations economic gate. Walking the trace once here is cheaper
# than re-walking per boundary inside the candidate loop. The same dict
# feeds the recommendation-emission path (C0) so row + recommendation
# share one source of truth for the gate.
call_counts_by_node: dict[tuple[str | None, str], int] = {}
if ctx.trace is not None:
    edges_map = _edge_child_paths(cw_result)
    for leaf in ctx.trace.iter_llm_leaves(edges=edges_map, workflow_path=ctx.workflow_path):
        # Canonical keying conditional — see analyze.py:1114-1115. Leaves
        # under a sub-workflow descendant key by event_node_id; other leaves
        # key by owner_node_id. Without this conditional, leaves silently
        # mis-attribute and the total-invocations gate breaks.
        node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id
        key = (leaf.workflow_path, node_id)
        call_counts_by_node[key] = call_counts_by_node.get(key, 0) + 1

# Walk cross-workflow edges to build per-row candidate map.
# Per-edge: token-estimate once, gate at boundary level (total_invocations,
# threshold), populate ALL consumer rows for the boundary if the gates pass.
cross_workflow_candidates_by_row: dict[
    tuple[str | None, str], list[_RowCrossWorkflowCandidate]
] = {}

for edge in cw_result.edges:
    # Gate 1: skip batch-alias-root edges (handled by batch_prefix tier).
    if edge.is_batch_alias_root:
        continue

    child_ir = cw_result.irs_by_workflow.get(edge.child_workflow)
    if not child_ir:
        continue

    # Gate 2 (already-declared): skip if the child workflow already lists
    # this input as a cache item — Tier 2 chunk-path handles it.
    child_declared = set(_items_by_name(
        cw_result.cache_items_by_workflow.get(edge.child_workflow, ())
    ))
    if edge.child_input_name in child_declared:
        continue

    consumer_node_ids = _collect_llm_nodes_referencing_path(child_ir, edge.child_input_name)
    if not consumer_node_ids:
        continue

    # Gate 3 (total-invocations economic gate): same gate as the
    # recommendation path (post-C0 fold-in). Caching only pays off when
    # the same cross-workflow content is sent ≥2 times across all consumer
    # rows. The shared call_counts_by_node dict ensures row + recommendation
    # see identical numbers — no drift between universes.
    total_invocations = sum(
        call_counts_by_node.get((edge.child_workflow, node_id), 0)
        for node_id in consumer_node_ids
    )
    if total_invocations < 2:
        continue  # N=1 or no trace evidence — caching loses money or is unobservable

    # Resolve representative model. Use max-threshold across heterogeneous
    # children (NOT first-only — first-only silently over-admits when later
    # children have stricter min-cache thresholds, e.g. Sonnet 1024 vs Opus 4096).
    child_models = _resolved_models_for_child(child_ir)  # filters ${...} templates
    if not child_models:
        continue  # honest unmeasurable; no LLM node has a resolved model
    representative_model = child_models[0]  # for token estimation only — pricing reuses
    threshold_floor = max(
        get_min_cache_tokens(m) for m in child_models
    )

    # Token estimate once per boundary (same content for every consumer).
    # Post-C0, _estimate_parent_value_tokens takes explicit fields — no
    # candidate object, no duck-type contract.
    token_estimate = _estimate_parent_value_tokens(
        parent_workflow=edge.parent_workflow,
        parent_value_expr=edge.parent_value_expr or "",
        parent_node_id=edge.parent_node_id,
        child_workflow=edge.child_workflow,
        child_input_name=edge.child_input_name,
        model=representative_model,
        ctx=ctx,
        cw_result=cw_result,
    )
    if token_estimate is None or token_estimate <= 0:
        continue

    # Gate 4 (below-threshold): use the MAX threshold across heterogeneous
    # child models so we don't admit candidates that fail for any consumer.
    cohort_total = token_estimate * total_invocations
    if cohort_total < threshold_floor:
        continue

    # All gates passed — populate every consumer row for this boundary.
    candidate = _RowCrossWorkflowCandidate(
        parent_workflow=edge.parent_workflow,
        parent_value_expr=edge.parent_value_expr or "",
        parent_node_id=edge.parent_node_id,
        child_workflow=edge.child_workflow,
        child_input_name=edge.child_input_name,
        estimated_tokens_per_call=token_estimate,
    )
    for node_id in consumer_node_ids:
        cross_workflow_candidates_by_row.setdefault(
            (edge.child_workflow, node_id), []
        ).append(candidate)
```

**New helper `_resolved_models_for_child(child_ir) -> list[str]`** (~12 LOC, replaces v1.1's `_representative_model_for_edge`): walks `child_ir["nodes"]` filtering `type == "llm"`. For each, reads `node.get("params", {}).get("model") or node.get("model")`. **Filters out values containing `${`** (template strings — unresolved; would choke `get_min_cache_tokens`). Returns the resolved-model strings in source order. Empty list means honest-unmeasurable; caller skips the boundary.

**Greenfield mode (no trace)**: `call_counts_by_node` stays empty → `total_invocations` is 0 for every boundary → gate 3 fails → Pass C populates nothing. **Correct behavior**: without trace evidence we can't claim cohort caching pays off; honest unmeasurable. C4 emits a Notes line routing the agent to `--from-trace` when this happens (see C4 below — greenfield asymmetry note).

**Sharing with C0**: the `call_counts_by_node` and `cross_workflow_candidates_by_row` dicts are made available to `_emit_sub_workflow_cache_findings` (the recommendation path). Same gate evaluation, same numbers, no drift. Implementation: thread both dicts through the analyzer flow OR (simpler) compute them once in `_build_per_call_rows_and_warnings` and pass to subsequent stages via the existing `_AnalyzePass` / context primitive (verify the actual shape pre-coding).

### C3. Plumbing into `_build_per_call_row` (v1.2 — ~25 LOC)

**v1.2 changes from v1.1**:
- Tier label rename `cross_workflow_candidate` → **`cross_workflow_projection`** (per v1.2 header §1).
- Static-batch clamp guard is now **MANDATORY**, not optional. Gate the cohort multiplier on `not _is_static_batch_trace_row(...)` to avoid silently truncating cohort tokens against per-call `input_tokens` for inline-list batch rows.

Pass `cross_workflow_candidates_by_row` through to `_build_per_call_row` as a keyword parameter; pass at the call site inside `_build_per_call_rows_and_warnings`.

```python
def _build_per_call_row(
    ...,
    cross_workflow_candidates_by_row: dict[
        tuple[str | None, str], list[_RowCrossWorkflowCandidate]
    ] | None = None,
) -> PerCallRow:
```

Insertion point: AFTER `_prefer_batch_prefix_cacheable_tokens` resolves precedence (find by name, ~`analyze.py:2261-2286` per audit) and BEFORE the clamp at `analyze.py:1583` (`cacheable_with_clamp = min(cacheable_tokens, input_tokens)`).

```python
# Pass C: cross-workflow projection (FALLBACK-ONLY).
# Fires when this row's node consumes a cross-workflow input that's not
# declared in the child workflow's ## Cache, AND no other tier produced
# evidence for the row. Audit confirmed score-choruses' batch_prefix
# already captures `${concept.core_idea}` — max-merge would double-count
# and mis-route the confidence-footer prose.
if (
    cross_workflow_candidates_by_row is not None
    and (cacheable_tokens is None or cacheable_data_source == "unavailable")
):
    candidates = cross_workflow_candidates_by_row.get((workflow_path, node_id), [])
    if candidates:
        per_call_sum = sum(c.estimated_tokens_per_call for c in candidates)

        # Per-row cohort math depends on whether the row's input_tokens is
        # cohort or per-call. Pass A.A2's _is_static_batch_trace_row predicate
        # divides input_tokens to per-call for inline-list batch trace rows.
        # If we cohort-multiply here, the line-1583 clamp will truncate to
        # the per-call input. Gate the multiplier on the same predicate.
        # Verified narrow-case-only by audit but mandatory v1.2 — silent
        # truncation is exactly the failure mode the user pushed back on.
        if _is_static_batch_trace_row(...):  # mirror Pass A.A2 invocation site
            cohort_tokens = per_call_sum  # per-call to match per-call input
        else:
            cohort_tokens = per_call_sum * max(1, observed_call_count)

        if cohort_tokens > 0:
            cacheable_tokens = cohort_tokens
            cacheable_data_source = "cross_workflow_projection"
```

**Pre-coding note**: read `analyze.py:1655-1679` (`_is_static_batch_trace_row` and `_divide_static_batch_trace_tokens` per audit) to confirm the predicate's signature. The C3 call site needs the same arguments (likely `node`, `observed_call_count`, `data_source`) — copy the existing call site's argument list verbatim.

**Why fallback-only is correct**: when `batch_prefix`/`memo`/`parameters`/`trace`/`estimator` already populated the row, that evidence is stronger than a hypothetical projection requiring two edits. Fallback-only avoids the score-choruses double-count and preserves the row's existing `batch-prewarm-recommended` story.

### C4. New tier label + renderer extensions (v1.2 — ~50 LOC)

**v1.2 changes from v1.1**:
- Tier label is **`cross_workflow_projection`** (NOT v1.1's `cross_workflow_candidate` — see header §1).
- Confidence-footer prose **names the affected rows** AND **points at BOTH `## Recommended actions` and `## Sub-workflow boundaries`** (NOT just Recommended actions). v1.1's footer mis-routed agents whose rows' inputs only surface in the boundaries section.
- **Multi-candidate row notes column** lists contributing inputs when candidates > 1.
- **Greenfield asymmetry note** — when `cw_result.edges` would have produced rows but trace is absent, emit a Notes line.
- `view_helpers.py` added to file list (comment update — `per_call_row_has_real_data` already classifies the new tier as real data via `!= "unavailable"`).

**Files to update**:

| File | Change |
|---|---|
| `analyze.py` ~`130-142` | Add `"cross_workflow_projection"` to `PerCallRow.cacheable_data_source` docstring enum list. |
| `render_text.py` `_cell_could_cache` ~`1406` | Extend `if row.cacheable_data_source in {"memo", "parameters", "batch_prefix"}:` to include `"cross_workflow_projection"`. |
| `render_text.py` `_per_call_confidence_footer` ~`1501-1524` | Add new branch (see §"Confidence-footer prose" below). |
| `render_text.py` `_format_per_call_row` (find by name) | Append `cw=<expr1>+<expr2>+...` to notes column when row has `cacheable_data_source == "cross_workflow_projection"` AND multiple `parent_value_expr` contribute. (See §"Multi-candidate notes" below.) |
| `render_text.py` `_render_notes` (find by name) | Add greenfield-asymmetry note generator (see §"Greenfield routing note" below). |
| `render_json.py` ~`237-241` | Update stale comment to list all 7 values (was 4 in comment, plus `batch_prefix`, `cross_workflow_projection` → 7 total). Drive-by fix. |
| `__init__.py` ~`32-40` | Add JSON format-version note for additive enum value. NO version bump per CLAUDE.md additive convention. |
| `mcp_server/tools/execution_tools.py` ~`509-517` | Add bullet for new tier in tool docstring (existing list of 5 → 6). |
| `cache_analysis/CLAUDE.md` | Add `cross_workflow_projection` tier with brief explanation. Note: row populates per fallback-only precedence. |
| `view_helpers.py` (comment update only) | Note in module-level comment that `per_call_row_has_real_data` covers the new tier automatically (no code change needed; explicit for future contributor extending the visibility heuristic). |

**Confidence-footer prose** (replaces v1.1's mis-routed prose):

When ≥1 row has `cacheable_data_source == "cross_workflow_projection"`, the footer becomes:

```
Cross-workflow projection: <row_id_1>, <row_id_2>, ... project savings from
cross-workflow shared inputs declared in their parent workflow(s). To
enable caching: declare the listed values in the receiving sub-workflow's
## Cache and remove inline body refs (see Recommended actions for the
boundary's recommended fix and Sub-workflow boundaries for any source-side
renames).
```

**Why both sections**: Recommendation #1 (`cache.sub-workflow-cache-undeclared`) covers ONE boundary at a time. For the canary, that's `concept`. But `review-rhyme:review` and `review-stranger-summary:review` rows also have populated `cross_workflow_projection` from `creative_direction` / `song_architecture` — boundaries that surface in `## Sub-workflow boundaries`, NOT Recommended actions. Pointing at only one section misroutes the agent for those rows.

**Multi-candidate notes** (when multi-candidate row hit):

```python
# In _format_per_call_row, after the existing notes accumulation:
if row.cacheable_data_source == "cross_workflow_projection":
    cw_inputs = [c.parent_value_expr for c in row_candidates_for(row)]
    if len(cw_inputs) > 1:
        # Truncate at 3 names + `+N more` if necessary to keep notes column readable.
        if len(cw_inputs) <= 3:
            note = f"cw={'+'.join(cw_inputs)}"
        else:
            note = f"cw={'+'.join(cw_inputs[:3])}+{len(cw_inputs) - 3} more"
        notes.append(note)
```

The candidates list per row is preserved on `PerCallRow` as a new optional field `cross_workflow_inputs: tuple[str, ...]` (parent_value_expr strings) populated alongside the cacheable assignment in C3. JSON shape gains the additive field.

**Greenfield routing note** (rendered in `## Notes`):

When ALL of the following hold:
- `ctx.trace is None` (no trace data)
- `cw_result.edges` is non-empty
- At least one edge would have passed gates 1+2 (already-declared, child has consumers)
- `len(cross_workflow_candidates_by_row) == 0` (Pass C populated nothing because total-invocations gate failed for every boundary)

Emit:

```
· Cross-workflow projections require trace evidence to populate per-call rows.
  Recommended actions still surface (computed from declared cache items and
  parameters); run with `--from-trace <path>` for per-call attribution.
```

This closes the v1.1 silent gap where agents see "$0.20/run" in recommendations next to `?` rows and self-diagnose incorrectly. Implementation: a small helper (`_should_emit_greenfield_cw_note(ctx, cw_result)`) called from `_render_notes` or `_collect_notes`.

**Read-only checks (no change needed)**:
- `_cell_cached_now` at render_text.py:1396 (`row.cacheable_data_source == "trace" and row.declared_prompt_cache`) — Pass C rows have `declared_prompt_cache=None` so they correctly fall through to `could_cache`. No change.
- `_is_row_visible_by_default` at render_text.py:1577 (`row.cacheable_data_source != "unavailable" and not row.declared_prompt_cache`) — automatically promotes Pass C rows. No change.
- `view_helpers.per_call_row_has_real_data` (`row.cacheable_data_source != "unavailable"`) — automatic classification. No change (just comment).

### C5. Cleanup-hint extension to `cache.sub-workflow-cache-undeclared` (~30 LOC)

Per Searcher 6, the existing recommendation has NO body-shape advice. Following the recommendation as-rendered today produces `cache.prompt-body-duplicates-cache` ERROR (or `cache.prompt-body-shadows-cache` WARNING for subpath cases) post-edit. Pass C extends to mirror Pass B's pattern.

**Catalog template change** (`warning_catalog.py:136-150` headline + `:249-275` message):

Add `{cleanup_hint_clause}` to the message template (parallel to existing `{below_threshold_clause}`):

```python
"cache.sub-workflow-cache-undeclared": CacheWarningSpec(
    ...
    message_template=(
        "`{parent_value_expr}` flows into `{child_workflow_basename}` as "
        "`{child_input_name}` and is used by {node_count} LLM nodes there "
        "({child_node_ids_csv}). Add `{child_input_name}` to that sub-workflow's "
        "## Cache; sub-workflows do not inherit the parent cache block."
        "{below_threshold_clause}{cleanup_hint_clause}"
    ),
    suggestions_templates=(
        # Reorder per Pass B convention: cleanup first.
        "Apply both edits together — declaring without cleaning fires "
        "`cache.prompt-body-duplicates-cache` ERROR or "
        "`cache.prompt-body-shadows-cache` WARNING.",
        "First, remove the listed body refs from the affected nodes' prompts "
        "(or rewrite to literal text) so the chunks aren't sent twice.",
        "Then, in `{child_workflow}`, add a ## Cache chunk for `${{{child_input_name}}}`.",
        "Finally, add `{child_input_name}` to `prompt_cache:` on the child LLM nodes that reuse it.",
    ),
    required_context_keys=(
        ...,
        ("cleanup_hint_clause", str),
    ),
    ...
)
```

**Emission site change** (`analyze.py:4193-4209` per Searcher 6):

```python
def _build_cleanup_hint_clause(
    candidate: _SubWorkflowCacheCandidate,
    cw_result: CrossWorkflowResult,
) -> str:
    """Build the per-child-node body-ref cleanup clause for the cross-workflow recommendation.

    Mirrors Pass B's _prompt_body_cleanup_for_node but with synthetic cache_item_names
    = {child_input_name} since the child's ## Cache is currently empty.
    """
    child_ir = cw_result.irs_by_workflow.get(candidate.child_workflow)
    if not child_ir:
        return ""

    cache_item_names = {candidate.child_input_name}
    corrected = (candidate.child_input_name,)

    findings: list[str] = []
    for node_id in candidate.child_node_ids:
        node = next(
            (n for n in child_ir.get("nodes", []) if n.get("id") == node_id),
            None,
        )
        if node is None:
            continue
        cleanup = _prompt_body_cleanup_for_node(node, corrected, cache_item_names)
        if cleanup:
            cleanup_csv = ", ".join(f"`${{{ref}}}`" for ref in cleanup)
            findings.append(f"  • `{node_id}`: {cleanup_csv}")

    if not findings:
        return ""

    # v1.2: explicit antecedent (what's being declared, in which workflow)
    # + preserve Pass B's "remove OR rewrite to literal text" alternative.
    child_basename = _basename_for_workflow(candidate.child_workflow)  # use existing helper
    return (
        f"\n\nBefore declaring `{candidate.child_input_name}` in "
        f"`{child_basename}`'s ## Cache, the following body refs need cleanup "
        f"(remove from prompt body OR rewrite to literal text):\n"
        + "\n".join(findings)
    )
```

Wire at the existing emit site:
```python
cleanup_hint_clause = _build_cleanup_hint_clause(candidate, cw_result)
diagnostics.append(make_diagnostic(
    "cache.sub-workflow-cache-undeclared",
    ...,
    cleanup_hint_clause=cleanup_hint_clause,  # NEW
))
```

**Critical**: convention from Pass B is "remove from prompt body OR rewrite to literal text". Do NOT recommend restructuring to bare `${concept}` — there's no precedent and it would just trigger `cache.prompt-body-duplicates-cache` post-edit per Searcher 6.

---

## Tests (v1.2 — 16 numbered + 1 per-id-coverage stub = 17 total touched)

**v1.2 changes from v1.1**:
- **REMOVED test #17 (parametrize extension)**: VERIFIED at `tests/test_core/test_cache_analysis_warnings.py:744-753` — the existing parametrize already includes `cache.sub-workflow-cache-undeclared`. C5 only adds context fields (identity tuple unchanged) → existing test already covers Pass C's regression. Adding to the parametrize would be DEAD WORK.
- **NEW canary positive lock**: assert `select-chorus` actually populates ≥5,000 cohort tokens (the user's stated success criterion; v1.1 only locked the negative case `score-choruses` doesn't flip).
- **NEW Pass B × Pass C co-emission test**: locks the cleanup-hints-don't-contradict invariant when both warnings fire on the same node.
- **NEW partial-resolve test**: locks the per-edge skip semantic where some edges return None and the row populates from resolving edges.
- **NEW static-batch clamp test**: locks the v1.2 mandatory clamp guard.
- **NEW 3-level nesting test**: locks correct call-count attribution through parent → child → grandchild.
- **NEW conditional-dispatch unreached test**: locks `total_invocations` aggregation when some consumer nodes have `observed_call_count=0`.
- **REWRITTEN existing emission tests for `cache.sub-workflow-cache-undeclared` (C0 ripple)**: tests asserting suppression-by-consumer-count must instead assert suppression-by-total-invocations. ~3-5 existing tests at `tests/test_core/test_cache_analysis_per_id_emission.py:293-1278` need review.

### Pass C tests (v1.2 — 25 numbered + 1 per-id-coverage stub)

In `tests/test_core/test_cache_analysis_per_id_emission.py` (template: existing `test_sub_workflow_cache_undeclared_*` tests):

1. `test_per_call_row_populates_cross_workflow_projection_when_undeclared`
   - Parent + child IR with cross-workflow boundary; child has no `## Cache`; `MemoizationCache` populated for parent's source value; trace event count for the consumer node ≥ 2.
   - Assert per-call row has `cacheable_tokens_estimated > 0` AND `cacheable_data_source == "cross_workflow_projection"`.
   - Mutation contract: revert C2's per-row dict builder → cacheable stays None; test fails.

2. `test_per_call_row_cross_workflow_projection_sums_multiple_inputs`
   - Child node consumes 2 cross-workflow inputs (e.g., `${a}` and `${b}` flowing in from parent); both gate-passing.
   - Assert `cacheable_tokens_estimated == (tokens(a) + tokens(b)) * observed_call_count`.
   - Mutation contract: change `sum` → `max` in C3; test fails.

3. **(v1.1 INVERTED)** `test_per_call_row_cross_workflow_projection_does_not_overwrite_batch_prefix`
   - Row has BOTH a `batch_prefix` source value (e.g., 144,296) AND a hypothetical cross-workflow candidate that would otherwise produce a larger cohort total (e.g., 680k).
   - Assert `cacheable_data_source == "batch_prefix"` AND `cacheable_tokens_estimated == 144296`.
   - Companion: same fixture with `cacheable_data_source == "unavailable"` and same cross-workflow candidate; assert it DOES populate as `cross_workflow_projection`.
   - Mutation contract: change C3's gate from `(cacheable_tokens is None or cacheable_data_source == "unavailable")` to `cohort_tokens > (cacheable_tokens or 0)` (the v1.0 max-merge); test fails.

4. **(NEW v1.1)** `test_score_choruses_canary_keeps_batch_prefix_label_post_pass_c` (NEGATIVE canary lock)
   - End-to-end on the lyrics-generator canary trace fixture.
   - Assert the `score-choruses` row's `cacheable_data_source == "batch_prefix"` AND `cacheable_tokens_estimated == 144296` (or whatever the regenerated baseline shows; lock the value once regen runs).
   - Mutation contract: re-introduce v1.0 max-merge in C3; test fails (label flips to `cross_workflow_projection`). Regression gate against re-introducing max-merge.

4b. **(NEW v1.2)** `test_select_chorus_canary_populates_cross_workflow_projection` (POSITIVE canary lock — review-plan W8)
   - End-to-end on the lyrics-generator canary trace fixture.
   - Assert `select-chorus` row has `cacheable_data_source == "cross_workflow_projection"` AND `cacheable_tokens_estimated > 5000`.
   - Mutation contract: revert C2's per-row dict builder OR the C3 fallback-only branch; test fails. **This is the user's stated success criterion** (braindump: "the canary that proves whether Pass C succeeded"). Without this, regressions silently revert select-chorus to `?` with only baseline-diff catching it.

5. `test_per_call_row_cross_workflow_projection_skips_batch_alias_root_edges`
   - Edge has `is_batch_alias_root=True`; assert no candidate produced.
   - Mutation contract: drop the gate; test fails.

6. `test_per_call_row_cross_workflow_projection_returns_none_for_unmeasurable`
   - All 4 tiers of `_estimate_parent_value_tokens` return None — explicit fixture: empty parameters dict, empty `MemoizationCache`, no parent trace events for that node, parent workflow-node trace event has `node_params.inputs={}`.
   - Assert row's `cacheable_data_source` stays at the preceding source (does NOT flip).
   - Mutation contract: drop the `token_estimate is None` skip in C2; row would falsely populate with `cacheable_tokens_estimated=0`.

7. **(NEW v1.1)** `test_per_call_row_cross_workflow_projection_skipped_when_total_invocations_lt_2`
   - Boundary with 1 consumer and 1 trace event (`observed_call_count=1`).
   - Assert no candidate is added to `cross_workflow_candidates_by_row` for the boundary; consumer row's `cacheable_data_source` stays at preceding source.
   - Mutation contract: drop the `total_invocations < 2: continue` gate in C2; row populates with single-invocation case.

8. **(NEW v1.1)** `test_per_call_row_cross_workflow_projection_populates_for_single_consumer_with_multiple_calls` (post-C0 row + recommendation parity)
   - Boundary with 1 consumer node × 4 calls (the canonical select-chorus economic case).
   - Assert the row populates as `cross_workflow_projection`. **AND assert the recommendation `cache.sub-workflow-cache-undeclared` ALSO fires** for the same boundary (post-C0 fold-in: row + recommendation use the same total-invocations gate).
   - Mutation contract for row: revert C2's gate to `len(consumer_node_ids) >= 2`; test fails on row assertion.
   - Mutation contract for recommendation (locks C0): revert C0 (restore `len(child_node_ids) >= 2` gate in `_sub_workflow_cache_candidate`); test fails on recommendation assertion.

9. **(NEW v1.1, EXTENDED v1.2)** `test_per_call_row_cross_workflow_projection_skipped_when_below_min_threshold`
   - Boundary with `cohort_total = token_estimate × total_invocations < get_min_cache_tokens(model)` (e.g., 100 tokens × 4 calls = 400 vs Anthropic Sonnet's 1024 floor).
   - Assert no row populates; cacheable stays at preceding source.
   - **Heterogeneous-children companion** (NEW v1.2): 2 child consumers with different models (Sonnet 1024 floor + Opus 4096 floor); cohort_total = 2000. Sonnet alone would pass; max-threshold (4096) correctly fails. Assert no row populates.
   - Mutation contract: drop the threshold gate in C2 → below-threshold row falsely populates; test fails. Companion mutation: change `max(get_min_cache_tokens(m) for m in child_models)` → `get_min_cache_tokens(child_models[0])` (revert v1.2 max-threshold fix); heterogeneous case incorrectly admits; companion test fails.

10. `test_per_call_row_cross_workflow_projection_observed_call_count_multiplier`
    - Row with `observed_call_count=4`; per-call candidate tokens=2000 (above threshold).
    - Assert per-row cohort tokens = 8,000.
    - Mutation contract: change C3's multiplier from `max(1, observed_call_count)` to `1`; test fails.

10b. **(NEW v1.2)** `test_per_call_row_cross_workflow_projection_static_batch_inline_clamp_does_not_truncate` (review-plan W5 / silent-failures W4 / feature-interactions C2 — 3-way convergence)
    - Inline-list batch row (`batch: { items: [literal, list, here] }`) with ≥2 calls; trace mode active; cacheable falls through to `unavailable` (no batch_prefix detection); cross-workflow candidate populates.
    - Assert `cacheable_tokens_estimated` matches per-call sum (NOT cohort that would truncate against per-call input via `analyze.py:1583` clamp).
    - Mutation contract: drop the `_is_static_batch_trace_row` gate in C3 (always cohort-multiply); the line-1583 clamp truncates to per-call input; test fails because `cacheable_tokens_estimated < expected`.

10c. **(NEW v1.2)** `test_per_call_row_cross_workflow_projection_partial_resolve_sums_resolving_edges` (silent-failures C-2 — locks per-edge skip semantic that v1.1 risk register mis-described)
    - 3 cross-workflow boundaries flow into one row; 2 boundaries have resolving `_estimate_parent_value_tokens`; 1 returns None.
    - Assert `cacheable_tokens_estimated == (tokens(a) + tokens(b)) * observed_call_count` (the None edge contributes nothing; the resolving edges sum).
    - Mutation contract: change C2's per-edge skip to "skip the whole row when any tier returns None" (boundary-level skip); test fails because the row stays at preceding source instead of partial sum.

10d. **(NEW v1.2)** `test_per_call_row_cross_workflow_projection_3_level_nesting_attributes_calls_correctly` (feature-interactions W2)
    - 3-level nesting fixture: parent → child → grandchild; cross-workflow input flows from child → grandchild.
    - Assert grandchild's LLM consumer row populates with the correct `cacheable_tokens_estimated`. Verifies `call_counts_by_node` correctly attributes events through the 2-level edge map and `iter_llm_leaves` walks the full tree.
    - Mutation contract: drop `edges=_edge_child_paths(cw_result)` from the `iter_llm_leaves` call in C2; grandchild events fall back to root workflow_path; gate fails; test fails.

10e. **(NEW v1.2)** `test_per_call_row_cross_workflow_projection_conditional_dispatch_unreached_consumer_excluded` (feature-interactions W4)
    - Boundary with 2 consumer nodes; one executes 4 times, the other unreached (`observed_call_count=0`) due to conditional branch.
    - Assert `total_invocations` correctly sums to 4 (NOT 4+? when unreached is treated as something other than 0). Row populates correctly for the executed consumer.
    - Mutation contract: change `call_counts_by_node.get(..., 0)` to `call_counts_by_node.get(..., 1)` (treat missing as 1); unreached consumer's "1" pollutes the sum; gate evaluation differs.

10f. **(NEW v1.2)** `test_pass_b_and_pass_c_cleanup_hints_do_not_contradict_on_same_node` (feature-interactions C1)
    - Fixture: parent declares `[creative_direction]` in `## Cache`; child declares `[song_architecture]` in `## Cache` (missing `concept`) AND receives cross-workflow `${concept}` from parent. The same child node is both Pass B's `cache.prompt-cache-incomplete` AND Pass C's `cache.sub-workflow-cache-undeclared` target.
    - Assert: both diagnostics fire. Each carries a cleanup_hint listing body refs to clean. The two cleanup-hints' refs (a) don't overlap on the same body ref claiming different actions, AND (b) cover their respective scopes (Pass B covers missing-chunk refs; Pass C covers cross-workflow-input refs).
    - Mutation contract: change Pass C's synthetic `cache_item_names = {child_input_name}` to `cache_item_names = parent_declared_chunks` (wrong scope); Pass C's clause then claims Pass B's body refs; test fails on overlap assertion.

11. `test_sub_workflow_cache_undeclared_emits_cleanup_hint_when_body_uses_subpath`
    - Child node prompt uses `${concept.title}` (subpath of recommended cache item `concept`).
    - Assert `diag.context["cleanup_hint_clause"]` contains:
      - the subpath ref (`` `${concept.title}` ``)
      - explicit antecedent (`` Before declaring `concept` in `<child basename>`'s ## Cache ``)
      - the "remove from prompt body OR rewrite to literal text" alternative (Pass B convention)
    - Mutation contract: revert C5's clause builder → clause stays empty; test fails.
    - Mutation contract (v1.2 antecedent): drop the `Before declaring X in Y` antecedent from the clause prose; test fails on antecedent substring.
    - Mutation contract (v1.2 alternative): drop "OR rewrite to literal text" → test fails on alternative substring.

12. `test_sub_workflow_cache_undeclared_cleanup_hint_empty_when_body_uses_bare_ref`
    - Child node prompt uses bare `${concept}` (no overlap post-edit).
    - Assert `diag.context["cleanup_hint_clause"] == ""`.
    - Mutation contract: emit clause unconditionally; test fails.

13. `test_sub_workflow_cache_undeclared_cleanup_hint_lists_per_node_refs`
    - 2 child nodes, one uses `${concept.title}`, the other uses `${concept.core_idea}`.
    - Assert both nodes' refs appear in the clause, grouped per-node.
    - Mutation contract: drop per-node loop; test fails.

14. `test_sub_workflow_cache_undeclared_suggestions_use_cleanup_first_ordering`
    - Render the diagnostic.
    - Assert "Apply both edits together" appears before "First, remove" before "Then, in" before "Finally, add".
    - Mutation contract: revert suggestion order; test fails.

15. `test_per_call_row_cross_workflow_projection_no_cost_projection_leak`
    - Workflow with cross-workflow candidate populated row.
    - Compute `actually_paid_usd - rerun_within_ttl_hypothetical_usd` and `first_run_delta.amount_usd`. Assert no contradiction (cross-workflow candidate doesn't shrink rerun cost — relies on existing `declared_prompt_cache` gate).
    - Mutation contract: re-introduce a hypothetical that consumes `cacheable_tokens_estimated` for `cross_workflow_projection` rows in cost helpers; cost contradiction surfaces.

In `tests/test_core/test_cache_analysis_renderers.py` (template: `test_per_call_confidence_footer_uses_distinct_message_for_batch_prefix_projection`):

16. **(v1.2 EXPANDED)** `test_per_call_confidence_footer_uses_distinct_message_for_cross_workflow_projection`
    - Construct PerCallRow with `cacheable_data_source="cross_workflow_projection"` and an explicit `node_id`.
    - Render via `render_text(_make_analysis(rows=[row]))`.
    - Assert footer (a) names the row by `node_id` (NOT generic), (b) references BOTH `## Recommended actions` AND `## Sub-workflow boundaries` (NOT just one — review-agent-ux C2), (c) contains "remove inline body refs" prose, AND (d) the wrong-tier prose (batch_prefix's "static prefix" wording) is NOT present.
    - Mutation contract: revert the new footer branch → routes through batch_prefix prose; test fails.
    - Mutation contract (v1.2 routing): change the prose to reference only "Recommended actions" (drop the boundaries reference); test fails on second-section assertion.

16b. **(NEW v1.2)** `test_per_call_row_renders_multi_candidate_notes_when_inputs_count_gt_1`
    - PerCallRow with 2 contributing cross-workflow inputs (`creative_direction` + `song_architecture`); single contributing input fixture for negative case.
    - Assert the multi-input row's notes column contains `cw=creative_direction+song_architecture`. Single-input case has NO `cw=` note.
    - Companion: 4-input fixture; assert `cw=a+b+c+1 more` truncation.
    - Mutation contract: drop the multi-candidate notes append in `_format_per_call_row`; test fails.

16c. **(NEW v1.2)** `test_render_notes_emits_greenfield_cw_routing_when_trace_absent_and_recommendations_present` (silent-failures W1 / agent-ux W1)
    - Fixture: workflow with cross-workflow opportunities, NO trace data passed to `analyze()`. Recommendation `cache.sub-workflow-cache-undeclared` fires (memo/parameters resolve); per-call rows show `?` for the affected nodes (Pass C populates nothing — `total_invocations=0`).
    - Render via `render_text(...)`. Assert `## Notes` contains the routing line: *"Cross-workflow projections require trace evidence to populate per-call rows. Recommended actions still surface; run with `--from-trace <path>` for per-call attribution."*
    - Companion: same fixture but no cross-workflow edges OR same fixture with trace present; assert the note is NOT emitted.
    - Mutation contract: drop the `_should_emit_greenfield_cw_note` helper invocation in `_render_notes`; test fails.

In `tests/test_core/test_cache_analysis_warnings.py`:

**Note: v1.1's "Test #17 parametrize extension" REMOVED in v1.2.** Verified at `tests/test_core/test_cache_analysis_warnings.py:744-753` — `test_workflow_level_same_id_diagnostics_would_collapse_under_generic_dedup` already parametrizes `cache.sub-workflow-cache-undeclared`. C5 only adds context fields (identity tuple `(severity, source, node_id, id or message)` unchanged); existing test already covers Pass C's regression. Adding to the parametrize is dead work.

In `tests/test_core/test_cache_analysis_per_id_coverage.py`:

17. Add `cleanup_hint_clause` to `_kwargs_for("cache.sub-workflow-cache-undeclared")` entry. Auto-derived count test stays green.

### C0 ripple — review existing `cache.sub-workflow-cache-undeclared` emission tests

After C0 lands, the recommendation gate is `total_invocations >= 2` (NOT `consumer_count >= 2`). The 16 existing tests at `tests/test_core/test_cache_analysis_per_id_emission.py:293-1278` may include cases that asserted suppression-by-consumer-count. Walk each pre-coding; tighten any test that would silently break under the new gate. Test #8 above explicitly locks the new gate behavior with mutation contracts.

**Pass A.A2 + C0 interaction**: existing test `test_per_call_row_cross_workflow_projection_observed_call_count_multiplier` (test #10) and the new static-batch-clamp test (#10b) both depend on Pass A.A2 helper behavior. Verify no test fixture was depending on the v1.0/v1.1 max-merge precedence semantic (any such test should now invert per the v1.1 changes already documented).

---

## Baselines

### Existing baseline drift (regenerate)

| Baseline | Drift | Why |
|---|---|---|
| `04-warning-catalog/05-cache.sub-workflow-cache-undeclared/` | text + JSON | (a) Per-call section: rows that previously had `?`/`unavailable` and have ≥2 trace invocations gain populated `could_cache` with `cross_workflow_projection` source. (b) Recommendation rendering: cleanup-hint clause (empty for this fixture's bare-ref shape, but suggestions reorder to cleanup-first). |
| `12-real-world-lyrics-generator/01-analyze-cache-text/` | text | static-mode (no trace) → call counts default to 0 → Pass C populates nothing for this case. Drift is from C5 cleanup-hint suggestion reordering only. **Verify** during regen — if more rows drift than expected, investigate. |
| `12-real-world-lyrics-generator/02-analyze-cache-json/` | JSON | Same as above; additive field changes. |
| `12-real-world-lyrics-generator/03-analyze-cache-song-creator-text/` | text | Same as above; static-mode. |
| `10-live-recordings/05-gemini-lyrics-generator/` | text | trace mode → Pass C fires. Expected drift: `select-chorus` 164 → ~5k+ (cross_workflow_projection); `review-rhyme:review` and `review-stranger-summary:review` `?` → populated; `concept-chooser`/`enforce-diversity`/`analyze-source` children `?` → populated where parent value resolves AND total-invocations ≥ 2. **`score-choruses` row stays unchanged** (batch_prefix wins under fallback-only) — `cacheable_data_source=batch_prefix`, `cacheable_tokens_estimated=144,296`, `batch-prewarm-recommended` note retained. |
| `04-warning-catalog/21-cache.prompt-cache-incomplete/` | text + JSON | Pass B's baseline; might gain cross-workflow projections in its per-call section if applicable. **Verify** — if not applicable, no drift. |

Estimated ~6-8 baselines drift in total. All strict-improvement (additive new tier label, stronger projections, cleanup-hint clause).

**Greenfield-mode static analysis caveat**: workflows analyzed without trace data (no `--from-trace`, no auto-loaded trace) get `call_counts_by_node = {}` from C2's pre-loop walk. Total-invocations gate fails for every boundary → Pass C populates nothing. The static-mode baselines (`12-real-world-lyrics-generator/01`, `02`, `03`) drift only from C5's cleanup-hint suggestion reordering, not from row population. This is the intended behavior — without trace evidence, we can't claim cohort caching pays off; honest unmeasurable.

### New baseline (subpath cleanup case)

`.taskmaster/tasks/task_159/baseline/04-warning-catalog/05b-cache.sub-workflow-cache-undeclared-subpath/`

OR extend the existing `05-` directory with a subpath fixture child workflow.

Per Searcher 6, no current baseline exercises subpath body refs at the cross-workflow boundary. Pass C's cleanup-hint extension needs fixture coverage to lock the rendered text.

Files: `command.sh`, `expected-exit-code.txt`, `expected-stderr.txt`, `expected-stdout.txt`, `README.md`, `workflow.pflow.md`, `sub/child.pflow.md`. Workflow shape: parent has `## Cache: [article]` and passes `${article}` as input; child node prompt uses `${article.title}` (subpath access).

---

## Verification

```bash
# Focused unit suite:
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest \
  tests/test_core/test_cache_analysis_per_id_emission.py \
  tests/test_core/test_cache_analysis_per_id_coverage.py \
  tests/test_core/test_cache_analysis_renderers.py \
  tests/test_core/test_cache_analysis_analyze.py -q

# Targeted baseline regen + verify:
.taskmaster/tasks/task_159/baseline/regenerate.sh 04-warning-catalog
.taskmaster/tasks/task_159/baseline/regenerate.sh 12-real-world-lyrics-generator
.taskmaster/tasks/task_159/baseline/regenerate.sh 10-live-recordings
.taskmaster/tasks/task_159/baseline/verify.sh

# Full verification:
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest \
  tests/test_core/test_cache_analysis_*.py -q

HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff check src tests
HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff format --check src tests
HOME=/private/tmp/pflow-test-home .venv/bin/python -m mypy src
```

Manual smoke:

```bash
# Lyrics-generator canary should show:
# - select-chorus: could_cache populated (~20k+)
# - review-rhyme/review-stranger-summary: could_cache populated
# - concept-chooser children: could_cache populated
# - score-choruses: could_cache stays at batch_prefix value OR upgrades to cross_workflow_projection (whichever is larger)
uv run pflow analyze-cache .taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md --from-trace
```

---

## Critical files to modify (v1.2)

> Line numbers are stale by ~80-120 lines. Trust helper/symbol names; verify by `rg <name>` pre-coding.

| Pass C step | File | Change |
|---|---|---|
| **C0** | `src/pflow/core/cache_analysis/analyze.py` (`_estimate_parent_value_tokens`) | Refactor signature: take 5 explicit fields (`parent_workflow`, `parent_value_expr`, `parent_node_id`, `child_workflow`, `child_input_name`) instead of `candidate: _SubWorkflowCacheCandidate`. Body unchanged (just bare-field access). |
| **C0** | `src/pflow/core/cache_analysis/analyze.py` (`_sub_workflow_cache_candidate`, ~`3906`) | Remove `if len(child_node_ids) < 2: return None` gate. Constructor now returns a candidate for any (parent_value_expr non-empty, child_input_name not already declared) boundary. Update docstring. |
| **C0** | `src/pflow/core/cache_analysis/analyze.py` (`_emit_sub_workflow_cache_findings`, ~`4281-4332`) | Accept `call_counts_by_node` param. Add `total_invocations >= 2` gate before emit. Update single existing `_estimate_parent_value_tokens` caller to pass 5 explicit fields. |
| **C0** | `src/pflow/core/cache_analysis/CLAUDE.md` | Update gate documentation: `_sub_workflow_cache_candidate` no longer gates on consumer count; recommendation gate is now `total_invocations >= 2`. |
| C1 | `src/pflow/core/cache_analysis/analyze.py` (near `_SubWorkflowCacheCandidate`) | Add `_RowCrossWorkflowCandidate` dataclass with **5 fields including `parent_node_id`**. |
| C2 | `src/pflow/core/cache_analysis/analyze.py` (`_build_per_call_rows_and_warnings`, ~`1395`) | Pre-loop: walk `ctx.trace.iter_llm_leaves(edges=..., workflow_path=...)` with leaf-tier conditional keying to build `call_counts_by_node`. Then per-edge gates → `cross_workflow_candidates_by_row` dict. |
| C2 | `src/pflow/core/cache_analysis/analyze.py` (new helper) | Add `_resolved_models_for_child(child_ir) -> list[str]` (filters `${...}` template strings, returns first-non-empty resolved-model strings). |
| C2 | `src/pflow/core/cache_analysis/analyze.py` (top of file) | Add `from dataclasses import dataclass, field, replace` (likely already imported; verify). |
| C2 | `src/pflow/core/cache_analysis/analyze.py` (`_build_per_call_rows_and_warnings` return) | Return `call_counts_by_node` (or thread via context) so C0's `_emit_sub_workflow_cache_findings` can read the same dict. |
| C3 | `src/pflow/core/cache_analysis/analyze.py` (`_build_per_call_row` signature) | Add `cross_workflow_candidates_by_row` kwarg. |
| C3 | `src/pflow/core/cache_analysis/analyze.py` (post-`_prefer_batch_prefix_cacheable_tokens`, pre-clamp ~`1583`) | Insertion point for fallback-only cross-workflow projection logic with **mandatory `_is_static_batch_trace_row` clamp guard**. |
| C3 | `src/pflow/core/cache_analysis/analyze.py` (`PerCallRow`) | Add optional `cross_workflow_inputs: tuple[str, ...] = ()` field for multi-candidate notes-column rendering. |
| C3 | `src/pflow/core/cache_analysis/analyze.py` (call site of `_build_per_call_row`) | Pass kwarg through. |
| C4 | `src/pflow/core/cache_analysis/analyze.py` (`PerCallRow.cacheable_data_source` docstring, ~`130-142`) | Add `"cross_workflow_projection"` to enum list. |
| C4 | `src/pflow/core/cache_analysis/render_text.py` (`_cell_could_cache`, ~`1406`) | Extend tier set to include `"cross_workflow_projection"`. |
| C4 | `src/pflow/core/cache_analysis/render_text.py` (`_format_per_call_row`) | Append `cw=<expr1>+<expr2>+...` (truncated at 3 + `+N more`) to notes column when row has `cacheable_data_source == "cross_workflow_projection"` AND `len(row.cross_workflow_inputs) > 1`. |
| C4 | `src/pflow/core/cache_analysis/render_text.py` (`_per_call_confidence_footer`, ~`1501-1524`) | Add new branch: name affected rows by `node_id`; reference BOTH `## Recommended actions` AND `## Sub-workflow boundaries`; preserve "remove inline body refs" prose. |
| C4 | `src/pflow/core/cache_analysis/render_text.py` (`_render_notes` or `_collect_notes`) | Add greenfield-asymmetry routing note when `ctx.trace is None` AND `cw_result.edges` is non-empty AND `len(cross_workflow_candidates_by_row) == 0`. |
| C4 | `src/pflow/core/cache_analysis/render_text.py` (new helper) | `_should_emit_greenfield_cw_note(ctx, cw_result, cross_workflow_candidates_by_row) -> bool`. |
| C4 | `src/pflow/core/cache_analysis/render_json.py` (~`237-241`) | Update stale enum comment to list all 7 values (`trace`/`memo`/`parameters`/`estimator`/`heuristic`/`batch_prefix`/`cross_workflow_projection`/`unavailable`). |
| C4 | `src/pflow/core/cache_analysis/render_json.py` (PerCallRow serialization) | Add `cross_workflow_inputs` field to JSON shape (additive). |
| C4 | `src/pflow/core/cache_analysis/__init__.py` (~`32-40`) | Additive enum-value + new field note in version history. NO version bump. |
| C4 | `src/pflow/mcp_server/tools/execution_tools.py` (~`509-517`) | Add bullet for `cross_workflow_projection` tier in tool docstring. |
| C4 | `src/pflow/core/cache_analysis/CLAUDE.md` | Add tier with brief explanation. Note: row populates per fallback-only precedence; greenfield-mode emits a routing note. |
| C4 | `src/pflow/core/cache_analysis/view_helpers.py` (comment update only) | Note in module-level comment that `per_call_row_has_real_data` covers the new tier automatically (`!= "unavailable"` check). No code change needed. |
| C5 | `src/pflow/core/cache_analysis/warning_catalog.py` (~`136-275`) | Add `{cleanup_hint_clause}` to `cache.sub-workflow-cache-undeclared` message template; reorder suggestions to cleanup-first; add `cleanup_hint_clause: str` to `required_context_keys`. |
| C5 | `src/pflow/core/cache_analysis/analyze.py` (new helper) | Add `_build_cleanup_hint_clause(candidate, cw_result) -> str` with v1.2 antecedent (`Before declaring \`X\` in \`Y\`'s ## Cache`) + Pass B's "remove OR rewrite to literal text" alternative. |
| C5 | `src/pflow/core/cache_analysis/analyze.py` (`_emit_sub_workflow_cache_findings`, ~`4304-4332`) | Pass `cleanup_hint_clause` to `make_diagnostic` at the existing emit site. |
| Tests | `tests/test_core/test_cache_analysis_per_id_emission.py` | 22 production-shape tests (numbered 1, 2, 3, 4, 4b, 5, 6, 7, 8, 9, 10, 10b, 10c, 10d, 10e, 10f, 11, 12, 13, 14, 15, 21). Mutation contracts on all. |
| Tests | `tests/test_core/test_cache_analysis_renderers.py` | 3 production-shape tests (numbered 16, 16b, 16c). |
| Tests | `tests/test_core/test_cache_analysis_per_id_coverage.py` | Extend `_kwargs_for("cache.sub-workflow-cache-undeclared")` entry with `cleanup_hint_clause` (test #17). |
| Tests (C0 ripple) | `tests/test_core/test_cache_analysis_per_id_emission.py:293-1278` | Walk existing 16 `cache.sub-workflow-cache-undeclared` tests; tighten any that asserted suppression-by-consumer-count to assert suppression-by-total-invocations. |
| Baseline | `.taskmaster/tasks/task_159/baseline/04-warning-catalog/05-cache.sub-workflow-cache-undeclared/` | Regen — strict-improvement diff. |
| Baseline | `.taskmaster/tasks/task_159/baseline/12-real-world-lyrics-generator/` | Regen — strict-improvement diff (C5 cleanup-hint + C4 greenfield routing note where applicable). |
| Baseline | `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/` | Regen — strict-improvement diff. select-chorus populates; score-choruses unchanged. |
| Baseline | `.taskmaster/tasks/task_159/baseline/04-warning-catalog/21-cache.prompt-cache-incomplete/` | Verify; regen if Pass B+Pass C interaction surfaces. |
| Baseline (NEW) | `.taskmaster/tasks/task_159/baseline/04-warning-catalog/05b-...subpath/` (or extension to `05-`) | New baseline: subpath cleanup-hint coverage with v1.2 antecedent + alternative prose. |

---

## Reuse map (v1.2 — existing helpers to call)

- `_estimate_parent_value_tokens` (4-tier resolver, ~`analyze.py:4130-4174` per audit). **v1.2 refactor**: takes 5 explicit fields (`parent_workflow`, `parent_value_expr`, `parent_node_id`, `child_workflow`, `child_input_name`) plus `model`, `ctx`, `cw_result`. Single existing caller updated.
- `_collect_llm_nodes_referencing_path` (~`analyze.py:4335-4370`): identifies child LLM consumers of a cross-workflow input. **Pre-existing limitation**: doesn't match `${X[0]}` bracket-index refs (out of scope for Pass C; file as separate issue).
- `ctx.trace.iter_llm_leaves(edges=..., workflow_path=...)`: trace tree walker. Used by C2's pre-loop call-counts walk. Apply leaf-tier conditional keying: `node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id`.
- `_edge_child_paths(cw_result)`: produces the `edges` map needed by `iter_llm_leaves` for sub-workflow attribution.
- `_is_static_batch_trace_row(...)` (~`analyze.py:1655-1662` per audit): predicate for inline-list batch trace rows. **Mandatory v1.2 in C3** to gate the cohort multiplier.
- `get_min_cache_tokens(model)` (`llm_capabilities.py`): per-model min-cache threshold. **v1.2** uses `max` across heterogeneous child models (NOT first-only).
- `_prompt_body_cleanup_for_node` (~`analyze.py:3098-3115`): per-node cleanup hint via `cache_overlap.compute_overlaps`. **Pass C reuses for C5's cleanup hint** with synthetic `cache_item_names = {child_input_name}` (child's `## Cache` is empty for this candidate by construction).
- `cache_overlap.compute_overlaps` (`cache_overlap.py:150-187`): canonical overlap detector. Returns 3 kinds; subpath body refs ARE flagged. Bracket-index refs ARE handled here (asymmetric with `_collect_llm_nodes_referencing_path`).
- `make_diagnostic` (`warning_catalog.py:1016-1132`): catalog-dispatch factory. Validates context keys.
- `_resolve_effective_row_model` precedent: `${...}` template-string filtering pattern that `_resolved_models_for_child` (new C2 helper) mirrors.
- Existing `deterministic_tokens` autouse fixture for tests.

**Helpers NOT to reuse** (with reasons):
- `_sub_workflow_cache_candidate` (the constructor) for the row path: post-C0 it no longer has the consumer-count gate, but it still applies `_dedupe_sub_workflow_cache_candidates` and other recommendation-emission machinery. Row path needs a leaner data carrier: use `_RowCrossWorkflowCandidate` directly built inline in C2.
- `_compute_prompt_body_cleanup` (the greenfield variant ~`analyze.py:3060-3095`): returns `dict[str, list[str]]` for assignments mapping. Pass B uses the per-node variant `_prompt_body_cleanup_for_node`; Pass C C5 should too.
- v1.1's `_representative_model_for_edge`: replaced by `_resolved_models_for_child(child_ir) -> list[str]` in v1.2 because C2 needs the FULL list (for max-threshold) plus the first (for token estimation), not a single representative.

---

## Risk register (v1.1)

| Risk | Mitigation |
|---|---|
| Cross-workflow projection over-claims when child workflow already declares the input | C2 gate 2: skip when `edge.child_input_name in child_declared` (inline copy of the gate that lives inside `_sub_workflow_cache_candidate`; explicit because Pass C bypasses that helper). Tier 2 chunk-path handles already-declared cases. |
| ~~Cross-workflow candidate overrides legitimate Tier 2 chunk-path values~~ | **Eliminated by v1.1 fallback-only precedence.** When any tier (`trace`, `memo`, `parameters`, `estimator`, `batch_prefix`) has populated `cacheable_tokens`, Pass C's gate fails and the existing source persists. Tests #3 + #4 lock. |
| ~~Score-choruses' row label flips misleadingly~~ | **Eliminated by v1.1 fallback-only.** `score-choruses` keeps `batch_prefix` source label and the existing `batch-prewarm-recommended` note story. Test #4 (canary lock) is the regression gate. |
| Multi-candidate sum produces unrealistically large numbers | SUM is verified correct (audit searcher 3): pflow renders chunks contiguously at HEAD of `system` message, body in separate `user` message, single `cache_control` marker on last block (DD#11). Body cannot interleave; SUM is right. **v1.2 corrected risk-register text**: per-edge skip with row populating from resolving edges (NOT boundary-level skip). Test #10c locks the per-edge skip semantic; tests #2 + #6 lock SUM correctness. |
| Single-call boundary populates a row that shouldn't | C2 gate 3: `total_invocations >= 2` (sum of consumer call counts). N=1 boundaries skip entirely. Test #7 locks. |
| Below-threshold boundary populates a row that won't actually cache | C2 gate 4: `cohort_total >= get_min_cache_tokens(representative_model)`. Test #9 locks. |
| Static-batch input-vs-cohort clamp truncates Pass C cohort | **v1.2 PROMOTED to mandatory**: C3 gates the cohort multiplier on `not _is_static_batch_trace_row(...)`; for static-list batch trace rows, store per-call cacheable directly (matches per-call input post-Pass-A.A2). Three reviews + braindump converged. Test #10b locks. |
| Greenfield (no trace) mode fabricates cacheable values | C2's `call_counts_by_node` empty → `total_invocations=0` → all boundaries skip. Pass C produces nothing in static mode. Honest unmeasurable. |
| New tier label not threaded through all consumers | Audit searcher 2 verified: 8 reader sites, most slot in cleanly. Only `_cell_could_cache` set + `_per_call_confidence_footer` need explicit handling. Test #16 locks confidence footer. |
| Cleanup-hint clause empty when child uses bare ref (false-positive guard) | Test #12 locks the no-overlap case. |
| Cleanup-hint clause encodes subpath ref correctly | Tests #11 + #13 lock per-node + per-ref behavior. |
| Suggestion ordering regression | Test #14 locks cleanup-first ordering substring. |
| Pass C latent dedup risk (Nth occurrence of same shape) | **v1.2 NO ACTION NEEDED**: verified `cache.sub-workflow-cache-undeclared` is already in `test_workflow_level_same_id_diagnostics_would_collapse_under_generic_dedup` parametrize at `tests/test_core/test_cache_analysis_warnings.py:744-753`. C5 only adds context fields (identity tuple unchanged). Existing test covers Pass C's regression. N4 carry-over. |
| Cost projections inflate via cross-workflow candidate | Audit confirmed: cost gates exclusively on `declared_prompt_cache`. Pass C rows have `declared_prompt_cache=None` → already excluded. Test #15 locks. |
| Plan line numbers stale by ~80-120 lines | Re-verify by name (`rg <helper_name>`) before coding. Trust names, not line numbers. |
| ~~Row populates without recommendation in 1-consumer-many-calls case~~ | **v1.2 ELIMINATED via C0 fold-in.** Recommendation gate now also uses `total_invocations >= 2`; row + recommendation stay in lockstep universally. Test #8 locks both gates. |
| Pass B × Pass C cleanup-hint contradiction on same node | Both warnings can fire on the same node when the child declares an incomplete `## Cache` AND receives an undeclared cross-workflow input. Pass B uses `_compute_prompt_body_cleanup` greenfield path; Pass C uses `_prompt_body_cleanup_for_node` with synthetic `cache_item_names = {child_input_name}`. Different scopes (Pass B = missing chunks; Pass C = cross-workflow inputs) should NOT overlap. Test #10f locks. |
| Greenfield asymmetry — recommendation fires but rows show `?` | **v1.2 resolved**: C4 emits a Notes routing line when `cw_result.edges` is non-empty AND trace is absent AND `cross_workflow_candidates_by_row` is empty. Closes the silent gap where agents see "$0.20/run" recommendations next to `?` rows. Test #16c locks. |
| Heterogeneous-children threshold under-admission | **v1.2 resolved**: C2 uses `max(get_min_cache_tokens(m) for m in child_models)` for the threshold check (NOT first-only). Avoids silently admitting candidates that would fail for the strictest child model. Test #9 (heterogeneous companion) locks. |
| `_collect_llm_nodes_referencing_path` doesn't match `${X[0]}` bracket-index refs | **PRE-EXISTING limitation**, not introduced by Pass C. Affects both row path and recommendation path identically (same helper). File as separate issue; out of scope for Pass C. Document in `cache_analysis/CLAUDE.md` so future bracket-index work catches both call sites. |
| `_representative_model_for_edge` chokes on `${...}` template strings | **v1.2 resolved**: `_resolved_models_for_child` filters values containing `${` (mirrors `_resolve_effective_row_model` precedent). |
| Baseline drift cascades silently | Manual diff inspection per baseline. Each diff classified additive / cosmetic / strict-improvement. Behavioral change = abort. |

---

## Sequencing (v1.2)

Pass C is independent of Pass A/B (already shipped). Single PR (C0 + C5 bundled).

**Recommended internal order**:

1. **Pre-flight** (~15 min):
   - `git log --oneline -10` — if commits since v1.2 was written touched `cache_analysis/`, re-verify file:line citations.
   - `rg <helper_name>` for each helper the plan references (`_estimate_parent_value_tokens`, `_sub_workflow_cache_candidate`, `_emit_sub_workflow_cache_findings`, `_collect_llm_nodes_referencing_path`, `_is_static_batch_trace_row`, `_divide_static_batch_trace_tokens`, `_prefer_batch_prefix_cacheable_tokens`, `_prompt_body_cleanup_for_node`, `_edge_child_paths`, `iter_llm_leaves`). Trust names, not line numbers.
   - Read the lyrics-generator canary's current state — confirm `select-chorus=164` (post-Tier-2-multiplier) and `score-choruses=144,296` (post-prompt-shape Tier 1+2). If either differs, investigate before designing tests.
   - Read `_estimate_parent_value_tokens` body to confirm field access pattern (5 fields, attribute access). Plan v1.2 says to refactor to explicit fields.
2. **C0** (~25 LOC, NEW v1.2): refactor `_estimate_parent_value_tokens` to take 5 explicit fields; remove `consumer_count >= 2` gate from `_sub_workflow_cache_candidate`; add `total_invocations >= 2` gate at `_emit_sub_workflow_cache_findings` (consumes `call_counts_by_node` from C2). Walk existing 16 emission tests for ripple.
3. **C1** (~6 LOC): add `_RowCrossWorkflowCandidate` dataclass with **5 fields including `parent_node_id`**.
4. **C2** (~70 LOC): pre-loop call-counts walk via `ctx.trace.iter_llm_leaves(edges=..., workflow_path=...)` with leaf-tier conditional keying. Per-edge gates: skip-batch-alias-root, already-declared, consumer-collection, total-invocations ≥ 2, max-threshold across heterogeneous children, token-estimate. Add new `_resolved_models_for_child` helper (filters `${...}` templates). The shared `call_counts_by_node` dict feeds C0.
5. **C3** (~25 LOC): plumb kwarg into `_build_per_call_row`; insert fallback-only projection at the post-`_prefer_batch_prefix_cacheable_tokens` seam. **Mandatory** `_is_static_batch_trace_row` clamp guard.
6. **C4** (~50 LOC): tier label `cross_workflow_projection` threading — docstring enum, `_cell_could_cache` set, `_per_call_confidence_footer` branch (v1.2 prose names rows + references both sections), JSON comment, `__init__.py` version history note, MCP docstring, `cache_analysis/CLAUDE.md`, `view_helpers.py` comment update, multi-candidate `cw=` notes column, greenfield-asymmetry routing note generator.
7. **C5** (~40 LOC): `cache.sub-workflow-cache-undeclared` catalog template gains `{cleanup_hint_clause}`; suggestions reorder to cleanup-first; new `_build_cleanup_hint_clause` helper at emit site (v1.2 prose: explicit antecedent + "remove OR rewrite" alternative).
8. **Tests** (25 numbered + 1 per-id-coverage stub): per the v1.2 Tests section. Mutation contracts on every test except #17. Stash-and-fail-verify after writing each.
9. **Baseline regen** (single pass, after all code lands): targeted regen of the ~6-8 drifted baselines; manual diff inspection; classify each as additive / cosmetic / strict-improvement.

**Coupling notes**:

- **C0 ↔ C2**: both consume `call_counts_by_node`. C2 builds it; C0 reads it. Thread through the analyzer flow as a return value of `_build_per_call_rows_and_warnings` (or via the existing `_AnalyzePass` / context primitive — verify shape pre-coding).
- **C0 ↔ existing tests**: 16 existing `cache.sub-workflow-cache-undeclared` emission tests may include cases that asserted suppression-by-consumer-count. Walk each pre-coding; tighten as needed. Test #8 above explicitly locks the new gate.
- **C1 → C2 → C3**: standard dependency chain. C1's `_RowCrossWorkflowCandidate` shape feeds C2's dict; C2's dict feeds C3's per-row plumbing.
- **C4 ↔ C2/C3**: tier label string `"cross_workflow_projection"` is referenced in C2 (assignment), C3 (assignment), C4 (renderer/JSON/CLAUDE.md). Introduce as a module-level constant `_CROSS_WORKFLOW_PROJECTION_TIER = "cross_workflow_projection"` to avoid string-typo drift.
- **C5 mechanically independent of C0-C4** but ships together for the user-facing story coherence. Acceptable to land C5 as a separate commit on the same PR if reviewer prefers smaller commits.

---

## What "done" means (v1.2)

**Canary expectations** (`10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`):

- `select-chorus` row shows `could_cache` populated ≥ 5,000 cohort tokens. Source label: `cross_workflow_projection`. **Locked by test #4b (positive canary lock).**
- `review-rhyme:review` and `review-stranger-summary:review` rows: `?` → populated. Source label: `cross_workflow_projection`. Notes column shows `cw=creative_direction+song_architecture` (multi-candidate disclosure).
- `concept-chooser` children, `enforce-diversity`, `analyze-source` rows: `?` → populated where parent value resolves AND total-invocations ≥ 2.
- **`score-choruses` row stays unchanged** (regression gate — locked by test #4): `cacheable_data_source=batch_prefix`, `cacheable_tokens_estimated=144,296`, `batch-prewarm-recommended` note retained.
- `generate-chorus-options` row stays `?` (opaque-prompt; unchanged).
- `curate-briefs`, `evaluate-songs` (root workflow nodes) stay `?` (no parent invocation; unchanged).
- Confidence footer for cross_workflow_projection rows: names the affected rows by `node_id`; references BOTH `## Recommended actions` AND `## Sub-workflow boundaries`.

**Recommendation-side expectations** (`cache.sub-workflow-cache-undeclared`):

- Cleanup-hint clause renders when child node's prompt body uses subpath refs (e.g., `${concept.title}`, `${concept.core_idea}`); empty clause when child uses bare ref (`${concept}`).
- Clause prose v1.2 shape: *"Before declaring `concept` in `chorus-chooser.pflow.md`'s ## Cache, the following body refs need cleanup (remove from prompt body OR rewrite to literal text):\n  • `score-choruses`: `${concept.core_idea}`\n  • `select-chorus`: `${concept.title}`, `${concept.core_idea}`"*.
- Suggestions reorder to cleanup-first: "Apply both edits together" → "First, remove ..." → "Then, in ..." → "Finally, add ...".
- Headline + savings logic unchanged (Pass C doesn't touch the existing emission gates apart from C0's gate replacement).
- **C0 fold-in**: 1-consumer-many-calls boundaries also fire the recommendation (post-C0). Locked by test #8.

**Static-mode (greenfield) expectations**:

- Workflows analyzed without trace data: Pass C populates nothing in per-call section (honest unmeasurable).
- **Greenfield routing note** renders in `## Notes` when `cw_result.edges` is non-empty AND trace is absent AND `cross_workflow_candidates_by_row` is empty. Closes v1.1 silent asymmetry.
- Drift in the `12-real-world-lyrics-generator/01-03` baselines is from C5 cleanup-hint reordering + the new greenfield routing note (when applicable). If rows drift unexpectedly, investigate.

**New baseline coverage** (`04-warning-catalog/05b-...subpath/` OR extension to `05-`):

- Subpath body-ref fixture locks the cleanup-hint rendered text shape with v1.2 antecedent + alternative prose.
- Multi-node fixture (one `${concept.title}`, one `${concept.core_idea}`) locks the per-node grouping.

**Verification gates** (all must pass):

- `make test` (or sandbox-safe equivalent per progress log conventions) passes.
- `.taskmaster/tasks/task_159/baseline/verify.sh` passes 66/66 (or whatever count is current at PR time) after targeted regen.
- `ruff check`, `ruff format --check`, `mypy src/pflow/core/cache_analysis`, `git diff --check` clean.
- Manual diff inspection on each drifted baseline classifies the change as additive / cosmetic / strict-improvement. Any behavioral regression = abort.
- Mutation contracts verified by stash-and-fail for each test marked with one (24 of 25 numbered tests have explicit contracts; test #17 is auto-derived per-id-coverage).

**Pre-implementation checklist**:

- [ ] Run `git log --oneline -10`; if commits since plan was written touched cache-analysis, re-verify file:line citations.
- [ ] `rg <helper_name>` for each helper the plan references (line numbers are stale; trust names).
- [ ] Read the lyrics-generator canary's current state — confirm `select-chorus=164` (post-Tier-2-multiplier) and `score-choruses=144,296` (post-prompt-shape Tier 1+2). If either differs, investigate before designing tests.
- [ ] Read `_estimate_parent_value_tokens` body to confirm 5-field access pattern. Refactor to explicit fields (C0).
- [ ] Read `_sub_workflow_cache_candidate` to locate the `len(child_node_ids) >= 2` gate (~`analyze.py:3906`). Plan it to remove for C0 fold-in.
- [ ] Read `_emit_sub_workflow_cache_findings` (~`analyze.py:4281-4332`) — site to insert the new `total_invocations >= 2` gate.
- [ ] Read existing parametrize at `tests/test_core/test_cache_analysis_warnings.py:744-753` — confirm `cache.sub-workflow-cache-undeclared` is already listed; do NOT add (would be dead work).
- [ ] Read 16 existing `cache.sub-workflow-cache-undeclared` emission tests at `tests/test_core/test_cache_analysis_per_id_emission.py:293-1278`; flag any whose expectations would invert under C0.

---

## Decisions consolidated (v1.2 — locked)

- **Precedence vs other tiers**: **fallback-only**. Pass C populates only when `cacheable_tokens is None or cacheable_data_source == "unavailable"`. Honest-unmeasurable convention; cross_workflow_projection is structurally the weakest tier (hypothetical, requires recommendation application). Rationale: audit searcher 4 found `score-choruses` body refs are inside the `batch_prefix` it already detects, so max-merge would double-count and mis-route the confidence-footer prose.
- **Tier label**: **`cross_workflow_projection`** (NOT `cross_workflow_candidate` — v1.2 rename per agent-UX C1; parallel to `batch_prefix`/`estimator` projection-tier vocabulary).
- **Row gate**: `total_invocations = sum(observed_call_count)` over consumer node IDs ≥ 2. Replaces v1.0's `consumer_count >= 2`. Strictly more accurate economic threshold; admits the 1-consumer-many-calls case.
- **Recommendation gate (C0 fold-in v1.2)**: same total-invocations gate. v1.1 documented row-vs-recommendation divergence as a known follow-up; v1.2 folds the recommendation-gate loosening into Pass C scope so row + recommendation stay in lockstep universally.
- **Below-threshold gate**: `cohort_total >= max(get_min_cache_tokens(m) for m in child_models)` (v1.2 max-across-children, NOT v1.1 first-only). Avoids silent over-admission for heterogeneous-children boundaries.
- **Already-declared gate**: skip when `edge.child_input_name in child_declared` (inline copy of the gate inside `_sub_workflow_cache_candidate`). Tier 2 chunk-path handles those cases.
- **Multi-candidate semantics**: SUM (independent prefix chunks). Verified correct by audit searcher 3 — pflow renders chunks contiguously at HEAD of `system` message, body in separate `user` message, single `cache_control` marker on last block.
- **Partial-resolve semantics**: per-edge skip with row populating from the SUM of resolving edges. (v1.1 risk-register text was wrong — said "boundary skips entirely.") Test #10c locks.
- **Dataclass shape**: NEW `_RowCrossWorkflowCandidate` with **5 fields** (v1.1 said 4 — wrong; `parent_node_id` required for Tier 3). Don't reuse `_SubWorkflowCacheCandidate` itself.
- **Token estimator signature** (v1.2 refactor): `_estimate_parent_value_tokens` takes 5 explicit fields (`parent_workflow`, `parent_value_expr`, `parent_node_id`, `child_workflow`, `child_input_name`), NOT a candidate object. Eliminates the duck-type contract. Single existing caller (`_emit_sub_workflow_cache_findings`) updated.
- **Trace primitive**: `ctx.trace.iter_llm_leaves(edges=..., workflow_path=...)` — NOT `ctx.iter_llm_leaves()` (v1.1 was wrong; method doesn't exist).
- **Call-counting key**: `(workflow_path, node_id)` where `node_id = leaf.event_node_id if leaf.tier == "sub_workflow_descendant" else leaf.owner_node_id`. Mirrors canonical `analyze.py:1114-1115`.
- **Static-batch clamp guard (v1.2 mandatory)**: C3 gates the cohort multiplier on `not _is_static_batch_trace_row(...)`. For static-list batch rows, store per-call cacheable directly. Three reviews + braindump converged.
- **Heterogeneous-models representative model**: `_resolved_models_for_child(child_ir)` filters `${...}` template strings; threshold takes max across resolved models; token estimation uses first resolved model.
- **Greenfield (no trace) behavior**: Pass C populates nothing. `call_counts_by_node` empty → `total_invocations=0` → gate fails. **v1.2 adds Notes routing line** ("run with `--from-trace`") when recommendations would fire but rows are empty. Closes the v1.1 silent asymmetry.
- **Cleanup-hint helper**: reuse `_prompt_body_cleanup_for_node` (Pass B's per-node variant) with synthetic `cache_item_names = {child_input_name}`.
- **Cleanup-hint clause prose (v1.2)**: explicit antecedent (`Before declaring \`X\` in \`Y\`'s ## Cache`) + Pass B's "remove from prompt body OR rewrite to literal text" alternative preserved. (v1.1 dropped both.)
- **Cost-projection isolation**: rely on existing `declared_prompt_cache` gate. NO new gate code (audit searcher 3 verified 5 cost helpers gate exclusively on `declared_prompt_cache`).
- **Confidence footer prose (v1.2)**: names affected rows by `node_id`; references BOTH `## Recommended actions` AND `## Sub-workflow boundaries` (NOT just one). Closes v1.1 mis-routing.
- **Multi-candidate notes column (v1.2)**: when `>1` cross-workflow inputs contribute to a row, append `cw=<expr1>+<expr2>+...` (truncated at 3 + `+N more`) to the row's notes column. Lets agent see decomposition without re-reading boundary section.
- **Suggestion ordering**: cleanup-first per Pass B convention.
- **C0–C5 ship in same PR**: C0 (recommendation-gate fold-in) is required for the row-vs-recommendation parity user-UX story. C5 (cleanup-hint extension) addresses an existing UX gap. Bundling keeps the user-facing story coherent.
- **JSON_FORMAT_VERSION**: NO bump (additive within branch).
- **Backward-compat shims**: NONE.
- **Dedup risk (N4)**: NO test extension needed. Verified existing parametrize at `test_cache_analysis_warnings.py:744-753` already covers `cache.sub-workflow-cache-undeclared`; C5's context-only changes don't touch identity tuple.
- **Bracket-index limitation in `_collect_llm_nodes_referencing_path`**: pre-existing; out of scope for Pass C. File as separate issue.
