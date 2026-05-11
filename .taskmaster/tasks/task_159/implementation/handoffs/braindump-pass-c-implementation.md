# Braindump: Pass C Implementation (Cross-Workflow → Per-Call Row Plumbing)

> Audience: the agent picking up `.taskmaster/tasks/task_159/implementation/fix-plans/pass-c-cross-workflow-row-plumbing-plan.md`.
>
> The plan is grounded by 6 parallel verification agents. File:line citations are accurate as of commit `ef158169` (Pass A + Pass B just landed). What follows is what's in MY head that's NOT in the plan.

---

## Where I am

Pass A + Pass B are committed (`ef158169`, 32 files, 5491 LOC, 96 deletions). Pass C is the user's pushback fix — they were unhappy that the v2 plan deferred the canonical select-chorus visible gap and labeled it "permanent." The Pass C plan now in `fix-plans/` is the comprehensive answer.

The user's exact words for the pushback: *"I thought the point of this implementation was to make it so that could_cache column would be populated? I thought we would solve the big issues in the two research files?"* That's the bar. The select-chorus row showing `41` (or `164` post-Pass-A regen) instead of a meaningful number is the canary that proves whether Pass C succeeded.

---

## User's Mental Model

Direct quotes worth preserving verbatim — these are how the user talks about this system:

- **"Of course we want the broad fix that fixes this for everything, not just this workflow but all similar to it"** — when I framed Pass C in terms of select-chorus, they pushed back on narrowness. The fix is universal by construction; the canary just exposes it.
- **"This is about more simple code that is optimized for AI agents to understand and add features to"** — direct quote. They reject overengineering. Reuse existing primitives. Don't add classes/abstractions when a function works.
- **"Top 10% of codebases similar to this one"** — invoked as a heuristic, but they immediately clarified "this isn't about overengineering and overfitting to top 10%". It means: simple, obvious code. Not framework patterns.
- **"This is staged"** / **"the json is not important here"** / **"actionable and easy to understand information"** — agent UX > JSON shape. Always. Unless asked.

What they value (priority order, derived):
1. **Correctness of agent-facing output** — the per-call row's numbers must mean what they appear to mean.
2. **Universal fix > narrow patch** — Pass C must apply to any workflow with the pattern, not be hard-coded for lyrics-generator.
3. **Simple final code** — they will reject the cleverest path if a boring path works.
4. **Verified assumptions** — they specifically asked me to verify before writing the plan. Speculation gets pushback fast.
5. **Honest unmeasurable** — `?` is sacred. Don't replace it with fabricated numbers. The F-04 fix (deleted Tier 3 heuristic) is the canonical precedent.

---

## Why my v2 plan was wrong about N2

Plan v2 (the partial-declaration plan) marked cross-workflow → per-call row plumbing as **"deferred permanently"** with this rationale:

> would require distinguishing "would cache today by declaring" from "would cache after declaration AND prompt edit" via a `requires_prompt_shape_change` row field — that's the row-model split this plan rejects.

That reasoning conflated two separate questions:

1. **Data plumbing complexity** — "is it hard to push the walker's data into per-call rows?"
2. **Row-data semantic completeness** — "does the row's `could_cache` number tell the agent the full action shape?"

I used (2) as a reason to skip (1). But:
- (1) is mechanical — walker has the data, row constructor has access to `cw_result`. ~30 LOC.
- (2) is solved separately via the cleanup-hint extension to `cache.sub-workflow-cache-undeclared` (Pass C step C5). The recommendation now tells the agent BOTH "declare X" AND "remove these body refs". The row's `could_cache` doesn't need to encode prompt-shape-change semantics — it just needs to surface the magnitude.

The implementing agent should know this so they don't relapse into "but what about the prompt shape change?" anxiety. The cleanup-hint clause handles it. The row's number is just magnitude.

---

## Things I almost got wrong (in the plan)

### Precedence between `batch_prefix` and `cross_workflow_candidate`

I wrestled with this. The two tiers measure DIFFERENT things:
- **`batch_prefix`** — literal byte prefix repeated across calls. Caches TODAY without prompt edits. Strong evidence.
- **`cross_workflow_candidate`** — hypothetical projection assuming the agent applies the recommendation. Weaker evidence (requires action).

**My initial instinct**: only populate when no other source has data. Then I flipped to max-merge (mirroring `_prefer_batch_prefix_cacheable_tokens`). I committed to max-merge in the plan.

**ASSUMPTION I'm 70% confident in, NEEDS VERIFICATION during implementation**: max-merge is the right semantic. For score-choruses with `batch_prefix=144k` and `cross_workflow_candidate=~680k` (if all 136 calls share concept), max-merge would FLIP the row's source label to `cross_workflow_candidate`. The visual change might not actually improve agent UX — `batch_prefix` was already telling a story.

**If max-merge produces weird visual flips** post-implementation, fall back to: "populate cross_workflow_candidate ONLY when no other source." Test the canary both ways and pick the one that reads better.

The implementer should REGENERATE THE LYRICS-GENERATOR CANARY FIRST and read it as a fresh agent. If max-merge wins on score-choruses but the row reads worse than before, that's a sign to flip to fallback-only.

### The clamp at `analyze.py:1567` (`cacheable_with_clamp = min(cacheable, input)`)

This is a SUBTLE GOTCHA the plan understated. After Pass A.A2, `input_tokens_estimated` is per-call for static-list batch trace rows. Pass C computes `cohort_tokens = sum × observed_call_count`. Then the clamp `min(cacheable, input)` operates per-call vs cohort. **CLAMP TRUNCATES.**

For non-batch repeated rows (select-chorus): `input` stays cohort, `cohort_tokens` is cohort, clamp works correctly.

For static-list batch rows (score-choruses): `input` is per-call after Pass A.A2, `cohort_tokens` is cohort. Clamp truncates cacheable to per-call. **Display becomes wrong.**

**Fix options I considered but didn't lock in**:
- (a) Compute Pass C as PER-CALL not cohort. Store per-call. Cost helpers' `× _row_invocation_count` recovers cohort. Clamp `min(per_call_cacheable, per_call_input)` is consistent.
- (b) Compute cohort, clamp against `input × _row_invocation_count` (cohort comparison).

**RECOMMENDATION**: (a) is cleaner — matches the per-call semantic Pass A.A2 established. Implementer should:
1. Store `estimated_tokens_per_call` on `_RowCrossWorkflowCandidate` (it already does).
2. At the insertion point (analyze.py:1562), compute `pass_c_per_call = sum(c.estimated_tokens_per_call for c in candidates)`.
3. For non-batch rows where `input_tokens_estimated` is cohort, `pass_c_cohort = pass_c_per_call × observed_call_count`. Compare against current `cacheable_tokens`.
4. For static-list batch rows where `input_tokens_estimated` is per-call (post-Pass-A.A2), use `pass_c_per_call` directly. Compare against current `cacheable_tokens` (which is also per-call after Pass A.A2 for these rows).

The plan's pseudocode says `cohort_tokens = sum × max(1, observed_call_count)` — this is WRONG for static-list batch rows. The implementer needs to gate on row type (use the existing `_is_static_batch_trace_row` predicate at `analyze.py:1645-1652`).

This is the single most likely correctness bug in Pass C if not handled carefully. Test #6 (`test_per_call_row_cross_workflow_candidate_observed_call_count_multiplier`) needs a static-batch-row companion test that asserts the per-call vs cohort behavior.

---

## What the user expects post-Pass-C

For the canary at `10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`:

| Row | After Pass C |
|---|---|
| `select-chorus` | `could_cache` populated with substantial tokens (~5k–20k range) |
| `review` (review-rhyme) | `could_cache` populated from `creative_direction`/`song_architecture` |
| `review` (review-stranger-summary) | populated similarly |
| `generate-concepts` (concept-chooser) | populated |
| `select-concepts` (concept-chooser) | populated |
| `assign-diversity` (enforce-diversity) | populated |
| `analyze` (analyze-source) | depends on whether non-batch-alias inputs flow in |
| `score-choruses` | depends on max-merge decision (see above) |
| `generate-chorus-options` | stays `?` (opaque prompt) |
| `curate-briefs`, `evaluate-songs` | stay `?` (root workflow, no parent) |

**Verification ritual**: regenerate the canary, then read it as a fresh agent. Specifically check select-chorus's row. If it shows a meaningful number AND the recommendation cleanup-hint clause appears, Pass C succeeded.

---

## The dedup risk N4 (5th occurrence)

`Diagnostic.__hash__` is `(severity, source, node_id, id or message)`. Four existing catalog IDs (`cache.sub-workflow-cache-undeclared`, `cache.cross-workflow-rename-detected`, `cache.cross-workflow-prose-mismatch`, `cache.consolidate-to-root-recommended`) emit with `node_id=None` and same severity/source/id. They survive multi-emission only because the analyzer's warnings list is never run through `deduplicate_diagnostics`.

Pass C's `cache.prompt-cache-incomplete` (Pass B) and any new IDs Pass C touches inherit this. Test #11 in the plan locks current behavior. **DO NOT** try to "fix" the dedup mechanism in Pass C — it's cross-cutting (affects all 5 IDs) and explicitly out of scope per N4. If you do fix it, all 5 IDs collapse to one diagnostic each per analyze() call.

If a future PR ever adds `deduplicate_diagnostics(analysis.warnings)`, it must coordinate the fix across all 5 IDs simultaneously.

---

## What's NOT in the plan but matters

### The `41 vs 164` mystery

The user/implementer reported select-chorus shows `41` post-Pass-A. Verifier #3 confirmed Pass A.A2 added Tier 2 chunk × `resolved_chunk_call_count` multiplication. So select-chorus SHOULD show 164 (4 × 41 per-chunk).

**ASSUMPTION**: the canary baseline file at `10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt` hasn't been regenerated yet. The staged change includes Pass A's source code but the canary's expected-stdout might still reflect pre-fix output. The implementer should regenerate FIRST to know the actual post-Pass-A state.

```bash
.taskmaster/tasks/task_159/baseline/regenerate.sh 10-live-recordings/05-gemini-lyrics-generator
.taskmaster/tasks/task_159/baseline/verify.sh
```

If select-chorus post-regen shows 164, that's the post-Pass-A baseline. Pass C will further change it (to ~5k–20k via cross-workflow `concept` candidate).

If post-regen still shows 41, something in Pass A's Tier 2 multiplication didn't fire for that row — investigate before doing Pass C. Possible cause: select-chorus's Tier 2 candidate path isn't triggering because chorus-chooser has no `## Cache` block (no chunk declarations), so the candidate-resolution path returns `cacheable_data_source = "unavailable"` instead of resolving via memo/parameters. That would mean `41` came from somewhere else (literal token count of `${concept.title}` operand string?). NEEDS VERIFICATION.

### The handoff appendices over-promised

Original handoff at `select-chorus-and-tier2-scope-gap-handoff.md` has an appendix claiming select-chorus would show `~28,000 / 77%` after fixes. Verifier #4 walked the actual prompt content and proved this was wrong — the prompt has refs interleaved with static text, so prefix-based caching can only capture the first ~25-30 tokens (lines 1-4 rubric), not 28k. **DO NOT take handoff numerical claims as ground truth.** The structural defect descriptions ARE accurate; the magnitude estimates were optimistic.

For Pass C, the realistic select-chorus magnitude depends on `_estimate_parent_value_tokens` resolving `concept` via the 4-tier resolver. For lyrics-generator, `concept` is a workflow-input passthrough (NOT a node output), so Tier 0/1/2 fail and Tier 3 (input-passthrough at parent invocation site) handles it. That tier was added in commit `bd005d28`. It reads `event["node_params"]["inputs"][child_input_name]` from the parent's workflow-node trace event.

### Subpath body refs in the canary

select-chorus uses `${concept.title}` and `${concept.core_idea}` — subpath access. After the user follows the recommendation "add `concept` to chorus-chooser's `## Cache`", the cache prefix sends the WHOLE concept object. The body still has the subpath refs → `cache.prompt-body-shadows-cache` WARNING fires post-edit.

That's exactly what Pass C step C5 (cleanup-hint extension) addresses. The cleanup hint should list `${concept.title}` and `${concept.core_idea}` as body refs to remove or rewrite. The convention from Pass B is "remove from prompt body OR rewrite to literal text" — DO NOT recommend "restructure to bare `${concept}`" (no precedent, would cause its own duplicate-cache issue).

### The `_resolve_input_at_workflow_node_invocation` Tier 3 is load-bearing

For the canary to actually produce numbers (not `?`), Tier 3 of `_estimate_parent_value_tokens` must fire. This reads `event["node_params"]["inputs"][child_input_name]` from the trace. The lyrics-generator trace fixture is TRIMMED (`template_resolutions` stripped, `llm_prompt` trimmed for size) — but `node_params.inputs` is preserved. Tier 3 works against this.

If your test fixtures don't preserve `node_params.inputs`, Tier 3 won't fire and Pass C produces `?`. The existing 16 tests for `cache.sub-workflow-cache-undeclared` show the right pattern — pre-populate `MemoizationCache` (Tier 1) OR construct trace with intact `node_params.inputs` (Tier 3) OR pass `parameters={...}` (Tier 0) to `analyze()`.

### The `is_batch_alias_root` filter is critical

Without it, Pass C emits bogus candidates for batch-iteration values. `parent_batch_alias` is the root segment of `parent_value_expr` when the value comes from a batch-iteration substitution (e.g., parent has `batch.items: [{a:1},{a:2}]` and passes `${item}` to child). Those values vary per call → not cache candidates.

This was added recently (commit `cc3c32c0`, "per-call table split + batch-alias propagation"). The plan calls it out at C2; don't omit the gate.

---

## Open threads / things I'd verify if I had more time

1. **Score-choruses post-Pass-C visual**: max-merge could produce visual confusion. Sanity check: read the canary as a fresh agent. If `score-choruses` row reads worse than pre-Pass-C, fall back to "populate only when no other source."

2. **Multi-candidate sum vs max for cohort total**: I locked sum in the plan. The reasoning: independent prefix chunks cache independently. But there's an ASSUMPTION here that I didn't fully verify — whether Anthropic/Gemini cache_control markers can fire on multiple non-contiguous chunks within a single prompt. If they only fire on a contiguous prefix, sum overestimates. NEEDS VERIFICATION (probably via reading `pflow guide caching` or the cache_render.py `_build_cache_control_marker` helper).

3. **The unrelated untracked file**: `prompt-shape-recommended-actions-plan.md` appeared in git status before the move. I have no idea what's in it. Probably a draft from a parallel agent. Check it before assuming it's safe to ignore — it might be a competing/overlapping plan.

4. **CLAUDE.md tier list update site**: the plan says "(find tier list)" because I didn't pin the exact line. `grep -n "cacheable_data_source" src/pflow/core/cache_analysis/CLAUDE.md` finds it. Probably ~line 120 area per Searcher 2.

5. **Confidence-footer message phrasing**: I wrote "*projects savings from cross-workflow shared inputs (see Recommended actions); declare prompt_cache and remove inline body refs to confirm.*" That's fine but could be sharper. The user might prefer a tighter phrasing. If unsure, ask. Pattern to mirror: existing batch_prefix message is *"projects savings from the prompt's static prefix repeated across observed calls; declare prompt_cache to confirm."*

6. **Heterogeneous-models edge case for representative model**: I added `_representative_model_for_edge` helper with first-non-empty-model rule. If a child workflow has 2 LLM nodes with different models (e.g., one uses Sonnet, one uses Haiku), the threshold check uses the first node's model. If different thresholds apply, the projection is wrong for one node. The plan documents this as following the existing `_consolidate_to_root_advisories` precedent. Acceptable v1 simplification.

7. **What if a candidate's tokens = 0**? I gate on `token_estimate is None or token_estimate <= 0`. Token estimates of 0 are rare but possible (empty input value). The gate skips them. Test this edge case.

---

## What I'd tell myself starting over

1. **Re-verify file:line references before coding**. The codebase shifts every commit. Searchers grounded the plan AS OF commit `ef158169`, but if you start coding several commits later, line numbers may have moved. Do a quick `rg` or grep of the helper names; trust the names, not the line numbers.

2. **Regenerate canary FIRST**. The lyrics-generator canary's pre-Pass-C state is ambiguous (41 vs 164 mystery above). Regenerate, read as fresh agent, confirm baseline post-Pass-A state. THEN start Pass C.

3. **Read the user's own words** in this conversation if you have access — their pushback was the catalyst for Pass C. The "I thought we'd solve the big issues" framing matters. Don't lose sight of the canary fix.

4. **Use the 16 existing `cache.sub-workflow-cache-undeclared` tests as templates**. They're well-shaped. Inline IR construction, monkeypatch resolve_sub_workflow, optional MemoizationCache pre-population. Don't invent new test patterns.

5. **Mutation contracts are non-negotiable**. Every test MUST have a docstring saying what mutation breaks it. Pattern: *"Mutation contract: revert X in Y::Z; this test fails because <observable consequence>."*

6. **Don't try to fix the latent dedup risk**. It's cross-cutting and explicitly out of scope. If you accidentally fix it, all 5 affected IDs collapse to one diagnostic each per workflow. Add the regression test that LOCKS current behavior (test #11 in the plan).

7. **Land in one PR**. The plan describes 5 sub-steps (C1-C5). They're tightly coupled. Don't try to ship C2 separately from C5 — the cleanup-hint extension is what makes C2's projections actionable.

---

## Relevant files

### Plan docs (read in order)
- `.taskmaster/tasks/task_159/implementation/fix-plans/pass-c-cross-workflow-row-plumbing-plan.md` — the implementation plan (this is your spec).
- `/Users/andfal/.claude/plans/yes-verify-every-assumption-cheeky-wand.md` — the v2 plan for Pass A/B (just landed). Useful for design history; you don't need to read fully.
- `.taskmaster/tasks/task_159/implementation/fix-plans/partial-declaration-detector-plan.md` — Pass B's plan. Reuse patterns: cleanup-first ordering, per-node findings block.

### Original handoffs (skim, don't trust numerical claims)
- `.taskmaster/tasks/task_159/implementation/handoffs/task-159-partial-declaration-detection-handoff.md`
- `.taskmaster/tasks/task_159/implementation/handoffs/select-chorus-and-tier2-scope-gap-handoff.md`

### Critical source files
- `src/pflow/core/cache_analysis/analyze.py` — main analyzer; the seam is at line 1562 (after `_prefer_batch_prefix_cacheable_tokens`, before `cacheable_with_clamp`).
- `src/pflow/core/cache_analysis/cross_workflow.py` — walker producing `CrossWorkflowResult` at line 135-153. `CrossWorkflowEdge.is_batch_alias_root` is a property at lines 84-98.
- `src/pflow/core/cache_analysis/token_estimation.py` — `_sum_resolved_chunk_tokens`, `estimate_cacheable_tokens`. Pass A.A2 added `resolved_chunk_call_count` kwarg.
- `src/pflow/core/cache_analysis/cost_estimation.py` — 5 cost helpers gate on `declared_prompt_cache`. Pass C does NOT need to touch this file.
- `src/pflow/core/cache_analysis/render_text.py` — `_cell_could_cache` at 1402-1413, `_per_call_confidence_footer` at 1501-1524. Both need extension for new tier.
- `src/pflow/core/cache_analysis/warning_catalog.py` — catalog at line 136-275 (existing) and 276+ (cache.prompt-cache-incomplete). Pass C extends the existing entry.
- `src/pflow/core/cache_overlap.py` — `compute_overlaps` at 150-187. Don't touch; just call.

### Test files (templates)
- `tests/test_core/test_cache_analysis_per_id_emission.py:293-1278` — 16 existing tests for `cache.sub-workflow-cache-undeclared`. Use the structure verbatim.
- `tests/test_core/test_cache_analysis_renderers.py:3183` — confidence-footer template for new tier label.
- `tests/test_core/test_cache_analysis_per_id_coverage.py:43-258` — `_kwargs_for` map; extend for new context key.

### Baselines that will drift
- `04-warning-catalog/05-cache.sub-workflow-cache-undeclared/` — recommendation gains cleanup-hint clause; per-call section gains populated could_cache.
- `04-warning-catalog/21-cache.prompt-cache-incomplete/` — Pass B's baseline; might gain cross-workflow projections in its per-call section if applicable.
- `12-real-world-lyrics-generator/{01-text, 02-json, 03-song-creator-text}` — multi-row drift.
- `10-live-recordings/05-gemini-lyrics-generator/` — the canonical canary; 5-7 rows drift.
- New baseline needed: `04-warning-catalog/05b-...subpath/` OR extend existing 05- with subpath shape (see C5 plan).

---

## For the next agent

**Start by**:
1. Read the plan in `fix-plans/pass-c-cross-workflow-row-plumbing-plan.md` end-to-end.
2. Run `git log --oneline -10` and check if commits have landed since `ef158169`. If yes, do a quick spot-check on the file:line citations in the plan via `rg <helper_name>` — trust names, re-verify lines.
3. Run baseline regeneration on the lyrics-generator canary BEFORE writing any Pass C code. Read the post-Pass-A state to ground your expectations.
4. Implement C1 → C2 → C3 → C4 → C5 in order. Each is independent in code but they tell the user-facing story together.

**Don't bother with**:
- Reading the v2 plan in detail. The plan has all the verified facts already extracted.
- Trying to consolidate `_invocation_count` / `_row_invocation_count` duplicates. Pre-existing tech debt; out of scope.
- Heuristic A non-batch prefix projection. Permanently deferred (verified to not help select-chorus due to interleaved refs).
- Fixing the dedup mechanism. Cross-cutting, out of scope.

**The user cares most about**:
- The select-chorus row showing a meaningful number. Verify the lyrics-generator canary post-regen.
- The fix being universal (works on any workflow with the pattern).
- Simple final code. If you find yourself adding a class hierarchy, you've drifted.
- Honest output. `?` stays `?` for opaque prompts and root workflows. Don't fabricate.

**Watch out for**:
- The clamp interaction at `analyze.py:1567`. Static-list batch rows have per-call input post-Pass-A.A2. Pass C's cohort candidate would truncate. See "What I almost got wrong" above for the fix.
- The `41 vs 164` mystery. Regenerate before assuming.
- Max-merge possibly producing visually weird flips on score-choruses. If so, fall back to fallback-only semantic.
- Multi-candidate sum vs max for cache_control markers. Verify provider behavior before sum vs max.

---

## Note to next agent

> Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.

The plan is grounded; the gotchas above are NOT in the plan. Both matter.
