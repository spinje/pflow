## 2026-05-13 — Task 159 Followups — Bug A fix: batch-prefix + cross-workflow per-call unit

Field-report Bug A (`scratchpads/experiments/prewarm-cache-interaction/FINDINGS.md`):
`pflow analyze-cache` reports `cache_ratio_pct = 100%` for prewarm batches even
when the per-item ref interleaves with stable content and truncates the
cacheable prefix. Verified end-to-end on the gemini lyrics-generator baseline:
`score-choruses` displayed `91%` ratio for what is actually `~1%` cacheable
per-call. Fresh agents reading the output see "optimized" when the layout is
broken.

### Root cause investigation

Four parallel `pflow-codebase-searcher` runs verified the bug pattern at
the source:

1. **`_estimate_batch_prefix_cacheable_tokens` (`analyze.py:2853`) returned
   `prefix_tokens * affected_call_count`** — cohort tokens stored in a
   `PerCallRow.cacheable_tokens_estimated` field that every downstream
   consumer (table render, ratio compute, JSON emit, cost projection ×3,
   below-min detector, summary aggregate, single-call penalty) reads as
   per-call.
2. **The clamp at `analyze.py:2105` (`min(cacheable_tokens, input_tokens)`)
   silently collapses cohort > per-call to per-call input** — that's the
   `100% ratio` symptom: for any batch_size ≥ 2 with a non-trivial prefix,
   `cohort > per_call_input` is almost always true, so the clamp pins
   `cacheable_with_clamp == input_tokens`.
3. **`_batch_prewarm_recommendations` (`analyze.py:2569`) did
   `round(row.cacheable_tokens_estimated / affected_calls)`** as a
   compensating divide — but the clamp had already collapsed cohort to
   per-call, so the divide produced `per_call_input / affected_calls`
   (wrong by `affected_calls`). Two bugs cancelling each other into a
   third wrong value.
4. **`_apply_cross_workflow_projection` (`analyze.py:2180`) had the same
   pattern** in the non-static-batch-trace branch:
   `per_call_sum if is_static_batch_trace else per_call_sum * max(1, observed_call_count)`.
   Same cohort-in-per-call-field shape, same clamp masking. Downstream
   consumer audit confirmed the visible scar was limited to the per-call
   table's `could_cache` column for cross-workflow-projection rows; cost
   projections were saved by the `declared_prompt_cache` gate (empty by
   construction for these rows) and aggregators by the same gate.

The cross-workflow analog had a latent edge case in
`total_cacheable_tokens_estimated` summary aggregate (analyze.py:6137):
`cacheable * _row_invocation_count(row)` double-multiplies when the
clamp didn't saturate. Same root cause.

### Architectural reasoning

The pre-fix architecture had two producers writing cohort tokens into a
per-call field and a clamp + consumer-side gates masking the lie. The
top-10% shape is to make the producers obey the contract every consumer
already follows: `PerCallRow.cacheable_tokens_estimated` is per-call by
definition (matches sibling fields). The fix is to delete the cohort
multipliers, drop the compensating divide, and let the clamp become a
defensive guard that fires only on real bugs.

Considered alternatives (and rejected):

- **`NewType("PerCallTokens", int)`** — viral typing convention used
  nowhere else in pflow for one localized fix. Asymmetric.
- **Suffix functions with `_per_call`** — sibling fields
  (`input_tokens_estimated`, `output_tokens_estimated`,
  `chunk_tokens_estimated`) are all per-call without suffix. Renaming
  just one is inconsistent.
- **Frozen dataclass `CacheablePrefix(tokens_per_call, call_count)`** —
  locally clean but adds a wrapper the codebase doesn't use elsewhere
  for token counts.
- **Delete the clamp entirely** — appealing as "dead code now", but
  rejected for this PR: `_apply_cross_workflow_projection`'s sibling
  bug needed fixing in the same pass (confirmed via parallel agent
  investigation), and deleting the clamp without ALSO fixing the
  unrelated `input_tokens_estimated` mixed-unit problem (filed as
  GH #394) would expose a latent failure mode in dynamic-batch trace
  rows.

### Implementation

**Production (5 sites, all in `src/pflow/core/cache_analysis/analyze.py`):**

1. `_estimate_batch_prefix_cacheable_tokens` (line 2853): dropped
   `* affected_call_count`. Returns per-call. Docstring rewritten to
   state the per-call return contract and that `affected_call_count`
   now only gates the `< 2` precondition.
2. `_batch_prewarm_recommendations` (line 2569): dropped the
   compensating `/ affected_calls` divide and `round()` for prefix.
   Replaced the 5-line justifying comment with a clear explanation of
   the remaining input-divide (which compensates for the *separate*
   `input_tokens_estimated` cohort-asymmetry bug — GH #394 — not Bug A).
3. `_prefer_batch_prefix_cacheable_tokens` (line 2874): dropped the
   misleading "per-call multiplier" phrase from the tier-label
   justification comment.
4. `_apply_cross_workflow_projection` (line 2180): collapsed
   `per_call_sum if is_static_batch_trace else per_call_sum * max(1, observed_call_count)`
   to `projected_tokens = sum(...)`. Dropped the `is_static_batch_trace`
   parameter from the function signature; updated the single call site.
   Added a docstring sentence committing to per-call return.

**Tests (4 existing + 1 new, all production-shape per Pitfall #19):**

- `test_batch_prefix_projection_uses_trace_call_count_for_dynamic_batch`
  (`test_cache_analysis_analyze.py:5219`): dropped `× 3` cohort assertion;
  docstring updated to name the per-call contract and explain that
  `observed_call_count` now only gates `< 2`.
- `test_per_call_could_cache_populated_for_score_choruses_with_real_trace`
  (`test_cache_analysis_analyze.py:5713-5728`): replaced cohort thresholds
  (`> 100_000`, `> 5_000`, `> 20_000`) with structural assertions —
  per-call cacheable should be `> 0` and `<= input_tokens_estimated`,
  with `> 500` only on the score-choruses row where the real per-call
  prefix is well above noise floor.
- `test_cross_workflow_projection_populates_row_and_recommendation_for_single_consumer_many_calls`
  (`test_cache_analysis_per_id_emission.py:1693`): cohort `120` → per-call
  `60` (the `CrossWorkflowInputContribution.tokens_per_call` field already
  showed 60).
- `test_cross_workflow_projection_sums_multiple_inputs_on_one_row`
  (`test_cache_analysis_per_id_emission.py:1784`): cohort `100` → per-call
  `50`. Docstring updated to call out the per-call sum (was "across observed
  calls").
- `test_cross_workflow_projection_skips_unreached_conditional_consumer_rows`
  (`test_cache_analysis_per_id_emission.py:1883`): cohort `120` → per-call
  `60`.
- New: `test_batch_prefix_cacheable_does_not_inflate_to_100pct_when_prefix_is_truncated`
  — FINDINGS E2 case. Interleaved per-item ref where prefix < input.
  Asserts `cache_ratio_pct < 100` and the per-call cacheable matches direct
  tokenization (mutation contract verified: restoring `* affected_call_count`
  causes the per-call sanity assertion to fail with cohort=57 instead of
  per-call=19).

**Baseline (1 regenerated, behavior-correct drift):**

- `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`:
  - `score-choruses` row: `144,296 / 91%` → `1,061 / 1%` (the canonical
    Bug A repro on a real workflow).
  - `select-chorus` row: `36,289 / 100%` (clipped to input) →
    `13,790 / 38%`.
  - `curate-briefs` row: `412 / 1%` → `103 / 0%`.
  - 6 review-* rows: per-call cacheable values (each value × 4 reduction).
  - `review-ai-tells` and `review-cliche`: were rendering fabricated cacheable
    values via the cohort multiplier; now correctly show `below cache minimum`
    because their per-call cross-workflow sums (~2,207 tokens each) are below
    Gemini's 4,096 cachedContents minimum. Honest "won't fire at the provider"
    output replaces misleading "8,828 cacheable" — the exact agent-UX
    improvement Bug A targets.
  - Footer count: "select-chorus, **8 review nodes**" → "select-chorus,
    **6 review nodes**" (ai-tells and cliche correctly excluded from the
    cross-workflow-projection set).

### Verification

- Focused cache-analysis + CLI suite: **532 passed**.
- Core + CLI tests (`tests/test_core/` + `tests/test_cli/`): **3,201 passed**.
- Near-full sandbox-safe suite (`-m "not e2e"`): **6,661 passed, 10 skipped**.
- e2e suite: **43 passed**.
- Baseline harness: **72 passed, 3 drifted** — all three drifts pre-existing
  on HEAD (`01-parser-errors/{01,06,08}`, unrelated TTL wording; verified via
  `git stash` comparison).
- `ruff check`, `ruff format --check`, `mypy src/pflow/core/cache_analysis/`
  clean on touched files.
- End-to-end CLI smoke test on `scratchpads/experiments/prewarm-cache-interaction/E2-per-item-interleaved.pflow.md`:
  ratio now `57%` (pre-fix: `100%`). Case A (no interleaving): `93%`
  (legitimate high ratio, not the Bug A symptom). Output now distinguishes
  truncated layouts from clean prefixes.

### Tacit knowledge

**The cross-workflow analog blast radius was narrower than batch_prefix.**
Per agent-2 consumer audit, cost projection (`_per_call_first_run_with_cache_cost`,
`_per_call_rerun_cost`) and aggregators are gated on `declared_prompt_cache`
which is empty by construction for cross-workflow-projection rows — the cohort
bug never reached cost arithmetic. The visible symptom was limited to the
per-call table's `could_cache` column and a latent edge-case in the summary
aggregate. Fixing it together with batch_prefix was strictly safer than not.

**The remaining divide in `_batch_prewarm_recommendations` is the visible
scar of a separate bug** — `PerCallRow.input_tokens_estimated` is mixed-unit
(per-call for static-list batch trace and greenfield; cohort for dynamic-batch
trace and non-batch repeated trace). Documented inline; filed as **GH #394**
for follow-up after Task 160. Task 160's CLAUDE.md should commit to per-call
as the documented `PerCallRow` contract; #394 then enforces it at the
producers.

**The clamp at `analyze.py:2105` is still load-bearing.** With `cacheable_tokens`
now uniformly per-call by producer contract, the clamp only fires defensively
when a future producer violates the contract. Deleting it would require also
fixing the `input_tokens_estimated` cohort-asymmetry (GH #394) — out of scope
here.

**Cross-workflow-projection rows below provider min now correctly fall through
to "below cache minimum" warnings.** Pre-fix, the cohort multiplier inflated
per-call cross-workflow sums above the threshold check at
`_apply_cross_workflow_projection:2183-2184`, projecting cacheable values that
the provider would silently no-op. Post-fix, sub-threshold per-call sums
correctly skip projection, and `below_min_tokens_detector` emits its
`cache.below-min-tokens` warning instead. (FINDINGS Bug B — the analogous
`batch_prefix`-source-below-min case — remains open; the detector still gates
on `declared_prompt_cache` and doesn't yet handle batch_prefix evidence.)

**Pitfall #19 hit count this branch: now ≥9.** Three of the four updated tests
in this fix encoded the cohort bug verbatim. Production-shape fixtures
matching wrong production code remains the dominant test-suite failure mode
on this branch.

### What's next (still open)

- **GH #394** — `PerCallRow.input_tokens_estimated` unit unification. Filed
  with row-type table, visible scar, proposed per-call invariant. Referenced
  from `task-160.md` "Adjacent work to consider after this lands".
- **FINDINGS Bug B** — prewarm-only below provider min silent. Extend
  `below_min_tokens_detector` to gate on `cacheable_data_source == "batch_prefix"`
  when per-call cacheable < provider min. Bug A's per-call fix made this
  detector-side fix straightforward (the field is now honest per-call); the
  curate-briefs `103 / 0%` row visible after baseline regen is the canonical
  case waiting for the fix.
- **FINDINGS Bug 17** — prewarm `wall-clock cost` disclosure in
  `cache.batch-prewarm-recommended`. Doc-only addition to the action body.
- **FINDINGS Bug C** — combined prewarm + declared cache: prewarm
  contribution invisible in `cacheable_tokens_estimated`. Lower priority
  (observability, not actively misleading).

## 2026-05-11 — Task 159 Followups — Fresh-eyes quick-win bundle (4 polish fixes)

Four small UX fixes after a fresh-eyes read of the canonical lyrics-generator
capture. Each had a different root cause and could land independently; bundled
because they all touched one or two files in lockstep.

- **#2 — Pluralize `declare N input(s)`.** Catalog headline
  `_SUB_WORKFLOW_CACHE_UNDECLARED_HEADLINE` now interpolates `{inputs_phrase}`
  instead of literal `input(s)`. `make_diagnostic` derives `inputs_phrase` from
  `affected_input_count` (mirrors the existing `nodes_phrase` plumbing), and
  `resolve_headline_for` mirrors the same derivation (since `diag.context` does
  not carry `format_dict` derivations, and the headline renderer is the
  catalog-as-SSoT seam in `view_helpers.build_recommended_actions`). Lyrics-
  generator action 11 flips `declare 1 input(s)` → `declare 1 input`; all
  multi-input actions flip to `declare N inputs`.
- **#3 — Normalize `/workflow run` → `/run`.** `_format_action_savings` for
  `cache.batch-prewarm-recommended` previously rendered `saves ~$0.04/workflow
  run` while every other action used `/run`. The aggregate-batch nuance is
  carried in the action body ("projected savings are aggregate for the batch,
  not per item."); the divergent `/workflow run` label in the headline added no
  semantic value and read as inconsistent next to `/run` peers.
- **#5 — Drop `(case=refactor)` jargon from per-call rows.**
  `_unavailable_notes_by_row_key` was rendering `below cache minimum
  (case=refactor): lyrics ~474` — the `case=` token is pflow-internal
  classification taxonomy (one of `actionable | model_switch | refactor |
  unmeasurable`). The classification still gates which rows get the note (only
  `model_switch` and `refactor` fire), but the taxonomy name no longer leaks to
  agent-facing text. The corresponding Recommended action explains what to do;
  the row's job is just to say *why* the projection is unavailable.
- **#6 — Rewrite cross-workflow footer wording.** The token-confidence footer
  previously read "savings projected from shared inputs **declared** in parent
  workflow(s)". The inputs are not declared as cache anywhere — that's exactly
  the opportunity. Renamed to "savings projected from values flowing in from
  parent workflow(s)" (matches the verb pattern used elsewhere in the analyzer,
  e.g. "Three values flow in from parent ...").

### Files

- `src/pflow/core/cache_analysis/warning_catalog.py` — headline template +
  `inputs_phrase` derivation in `make_diagnostic` + mirror derivation in
  `resolve_headline_for`.
- `src/pflow/core/cache_analysis/render_text.py` — `_format_action_savings`
  unit normalization, `_unavailable_notes_by_row_key` jargon drop,
  `_per_call_confidence_footer` wording rewrite.
- `tests/test_core/test_cache_analysis_warnings.py` — new
  `test_sub_workflow_cache_undeclared_headline_pluralizes_input_count` with
  verified mutation contract (drop the `resolve_headline_for` derivation →
  `template.format` raises KeyError, `resolve_headline_for`'s try/except
  falls back to empty string, `"declare 1 input" in singular_headline` fails).
- `tests/test_core/test_cache_analysis_renderers.py` — three substring
  assertions migrated to new wording + three negative assertions added to
  lock the regressions out (no `case=` leak, no `/workflow run` leak, no
  "shared inputs declared in parent workflow" leak).

### Verification

- Focused cache-analysis + CLI suite: 639 passed (+1 net new).
- Baseline harness: 67 passed, 0 drifted after regenerating 4 cases
  (`04-warning-catalog/05b-cache.sub-workflow-cache-undeclared-subpath`,
  `10-live-recordings/05-gemini-lyrics-generator`,
  `12-real-world-lyrics-generator/01-analyze-cache-text`,
  `12-real-world-lyrics-generator/03-analyze-cache-song-creator-text`).
  Diff is exclusively the four UX improvements above.
- Default test suite: 6,592 passed, 1 skipped, 3 deselected.
- Touched-file `ruff check`, `ruff format --check`, focused `mypy` clean.

## 2026-05-11 — Task 159 — Prompt-caching guide topic polish

Current staged guide polish renames the public guide topic from `caching` to
`prompt-caching`, while keeping `pflow guide caching` as an alias. All cache
diagnostic `see_also` pointers and prose links now point agents at
`pflow guide prompt-caching`, and workflow auto-detection emits the canonical
topic name.

The guide content was rewritten around first-contact agent actions: run
`pflow analyze-cache`, read `## Recommended actions`, avoid repeating cached
values in prompt bodies, and use the analyzer's paste-ready edits. The guide
now includes a compact second findings table for cache IDs that link to it but
were missing from the common-findings list (`cache.order-mismatch`,
`cache.invalid-on-non-llm`, `cache.unused-chunk`, `cache.padding-advisory`,
`cache.prewarm-no-prefix`, `cache.consolidate-to-root-recommended`,
`cache.heterogeneous-models-fragment-cache`,
`cache.first-call-write-penalty`, `cache.cross-workflow-prose-mismatch`, and
`cache.discrepancy`). `cache.cross-workflow-rename-detected` is documented as
informational so the Shape δ text-suppression decision does not regress.

## 2026-05-11 — Task 159 Followups — Bug 1 fix: delete whole-trace drift detector

Field-report Bug 1: `pflow analyze-cache` silently rejected an auto-loaded
trace as "root LLM context drifted" and fell through to greenfield analysis,
under-counting savings by ~60× on the lyrics-generator workflow.

### Root cause investigation

Parallel pflow-codebase-searcher subagents established three findings:

1. **The drift detector was producing false positives.** `_collect_root_trace_llm_context`
   called `iter_llm_leaves(descend_sub_workflows=False, descend_cached_subtrees=False)`,
   but `TraceTree.walk` (`core/trace_tree.py:153-190`) descends `batch_items`
   unconditionally. For `type: workflow` batches, each batch item IS a
   sub-workflow execution whose LLM events live under `item["events"]`, so the
   "root" collector pulled sub-workflow LLMs into the root set. On the
   lyrics-generator, `analyze-sources` (workflow-batch over `analyze-source`)
   leaked `analyze` and 9 other sub-workflow LLM ids into a set that should
   have contained only `{curate-briefs, evaluate-songs}`. Set inequality →
   reject → greenfield. **Any non-trivial successful run of any workflow-batch
   triggers this.**

2. **Per-row mechanism already handles structural drift cleanly.** Row build
   is IR-driven (`analyze.py:1471-1506`). Missing trace events produce
   `cost_value=None`, `did_not_execute_in_trace=True`, fall through to
   estimator. Orphan trace events (in trace, not in IR) get indexed but
   unused. The discrepancy stage explicitly skips them
   (`analyze.py:5449-5456`). No crashes, no misattribution.

3. **The drift detector was load-bearing for ONE narrow scenario only**:
   per-node `params.model:` literal change with a statically-resolvable new
   model. `_resolve_effective_row_model` (`analyze.py:1933-1947`) declares
   "trace wins when present and unambiguous," so `row.model` and downstream
   projections use trace-side pricing. If the workflow's model changed after
   the trace was recorded, projections silently misprice (actually-paid stays
   correct — it reads recorded `cost_usd` directly).

### Architectural reasoning (top 10% codebases lens)

The pre-fix architecture had **two layered validity mechanisms**:
- Coarse-grained whole-trace drift gate (this fix removes it).
- Fine-grained per-row `data_source` mechanism (already correct, unchanged).

Fine-grained is the right model — same pattern as per-file fingerprints in
rustc/cargo, action-level caching in bazel, per-test invalidation in pytest.
AI agents reading the code in 6 months see **one** validity mechanism, not
two overlapping ones; adding new analyzer features no longer needs to reason
about whether some new field affects whole-trace acceptance.

Retry/fall-through to older traces was considered (`analyze.py:_autoload_trace`
sorts reverse by filename; the rejection branch could iterate) but rejected
on principle: if the newest matching trace shows drift, older traces were
recorded against even older workflow versions and show *more* drift, not
less. Retry would only "succeed" in pathological cases (model toggled X →
Y → X). Real usage is monotonic.

### Implementation

**Deletions** (~80 lines):
- `_trace_aligns_with_ir` (predicate)
- `_collect_root_trace_llm_context` (the buggy tier-leaking collector)
- `_collect_ir_llm_node_ids`
- `_collect_ir_static_llm_models`
- The rejection branch at `analyze()` immediately after `_resolve_trace_data`.

**Additions** (~30 lines):
- `_resolve_ir_static_model_for_node(node, default_model) -> str | None` —
  per-node helper. Returns the static model from `params.model:` or
  `model:`, falls back to workflow default, returns `None` for templated
  `${var}` models.
- `_row_model_drift(row, irs_by_workflow, default_model) -> tuple | None` —
  per-row drift extraction. Skip conditions returned as `None` (heterogeneous
  row, ambiguous/missing trace model, missing IR, templated IR model).
  Decomposed out of the main function to keep C901 under threshold (the
  alternative would have been a `# noqa: C901` suppression; CLAUDE.md
  guidance is to decompose first).
- `_detect_per_node_model_drift(per_call_rows, irs_by_workflow, default_model) -> str | None` —
  walks per-call rows, accumulates drifts, emits a single grouped Notes
  string. Single-drift form names the trace and IR models inline; multi-drift
  form enumerates `node_id (trace → ir)` tuples.

Wired into `analyze()` after the per-row build (after the second coarse gate's
rebuild path so drift is evaluated on the FINAL per-call rows). Notes entry
wording:

> Trace was recorded with model `X` for node `N`; current workflow declares
> `Y`. Actually-paid is correct; cost projections use trace-side pricing.
> Re-record a trace to refresh.

### Test surgery (10 tests)

The grep for helper-name references returned no hits — the tests reference
drift behavior via the public `analyze()` API, not internal helpers. Five
tests locked the prior whole-trace-rejection contract; updated:

- `test_autoload_skips_when_trace_models_differ_from_ir` →
  `test_autoload_uses_trace_and_warns_when_model_drifts`. Asserts trace IS
  loaded AND model-drift Notes fires.
- `test_autoload_skips_when_root_node_ids_differ_from_ir` →
  `test_autoload_uses_trace_when_root_node_renamed`. Asserts the rejection
  still happens but via the orthogonal `did_not_execute_in_trace` gate
  (analyze.py:661-689), not the deleted drift gate.
- `test_autoload_skips_when_root_node_added_in_ir` →
  `test_autoload_uses_trace_when_root_node_added`. Same as above.
- `test_autoload_skips_when_root_node_removed_in_ir` →
  `test_autoload_uses_trace_when_root_node_removed_orphans_ignored`.
  Trace IS loaded; orphan in trace ignored per-row. The mutation contract
  (restore the deleted gate → set inequality fires → assertion fails)
  is documented in the test docstring.
- `test_autoload_skips_when_default_model_changed` →
  `test_autoload_uses_trace_and_warns_when_default_model_changed`.
- `test_autoload_drift_rejected_trace_appends_note` →
  `test_autoload_model_drift_appends_notes_entry`. Migrated from
  "rejection + specific Notes" to "loaded + model-drift Notes".

Three tests that survived as-is but had stale framing in their names:

- `test_autoload_excludes_cached_events_from_drift_signal` →
  `test_autoload_handles_cached_orphan_events`. Cached events for orphan
  node ids are now handled by the per-row mechanism, not the deleted gate.
- `test_explicit_from_trace_bypasses_drift_check` →
  `test_explicit_from_trace_loads_regardless_of_model`. The "bypass" concept
  doesn't exist post-fix — explicit and auto load identically.
- `test_autoload_ignores_sub_workflow_llm_events` kept (still locks correct
  behavior — sub-workflow events don't generate root-level rows).

**New regression test for the actual lyrics-generator false positive**:
`test_autoload_does_not_falsely_reject_workflow_batch_trace` builds a trace
with a `homogeneous_workflow_batch_event` whose batch items contain
sub-workflow LLM events. Mutation contract documented in docstring: restore
the deleted gate without the (also-deleted) tier filter → leaks `analyze`
into root set → `{ask, analyze} != {ask}` → rejection → test fails.

### Tacit knowledge

**Second coarse gate still exists** at `analyze.py:661-689` (now ~657-684
post-deletion). If any row has `did_not_execute_in_trace=True`, the analyzer
rebuilds with `trace_data=None`. This is the gate that now fires for the
renamed/added-node test cases. Worth examining in a follow-up — it's also
coarser than necessary; per-row data_source could mark individual rows as
estimator while keeping matched rows as trace. Out of scope for Bug 1.

**Notes entry vs catalog warning**: emitted as a Notes string (free-form
list[str]) rather than a structured `cache.model-drifted` catalog warning
(`warning_catalog.py`). DD#29 makes catalog IDs an agent-facing API requiring
design review; Notes is fine for v1. Promote to catalog if it becomes a
recurring agent question or if JSON consumers need structured access.

**Why we did NOT add fall-through to older traces**: older traces are
monotonically less aligned with the current workflow (recorded against older
versions). Falling back swaps one stale trace for a staler one. The retry
idea only made sense as a band-aid for the gate; with the gate gone, autoload
returns newest-matching and the per-row mechanism handles everything else.

**`row.model` is trace-side when trace populated `observed_models`**, IR-side
otherwise. The drift detector specifically compares against IR-static models
(reusing the deleted `_collect_ir_static_llm_models` logic per-node), not
against `row.model` directly — that would be self-referential when trace is
present.

**Three trace silencing scenarios remain after this fix**:
1. `did_not_execute_in_trace` gate (analyze.py:661-689) — see above.
2. Per-row data_source fall-through to estimator for unmatched events
   (intentional, correct).
3. The auto-loaded trace's `workflow_path` not matching the analyzed file
   (filtered at autoload time via filename hash; correct).

### Verification

- Focused autoload + workflow_batch + model_drift tests: 26 passed.
- Full cache-analysis suite (`tests/test_core/test_cache_analysis_*.py` +
  `tests/test_cli/test_analyze_cache.py`): 536 passed.
- Baseline harness: 75/75 passed, 0 drifted, 0 harness errors.
- Near-full sandbox-safe test suite (`uv run pytest -m "not e2e"`): 6,563
  passed, 10 skipped, 41 deselected.
- Quality: `ruff check`, `ruff format --check`, `mypy src/pflow/core/cache_analysis`
  all clean on touched files.

### What's next (other High-severity field-report bugs, not in this commit)

- **Bug 2** (Summary vs per-call table contradict): summary gates savings on
  `declared_prompt_cache`; table's `could_cache` shows `cross_workflow_projection`
  evidence. Same `PerCallRow`, opposite filters. The opportunity surfaces in
  `cache.sub-workflow-cache-undeclared` recommended actions but not in the
  summary headline. Fix shape is disclosure (label the gate, reference
  Recommended actions), not arithmetic. Independent of Bug 1.
- **Bug 3** (SchemaValidationError on validated workflows): discrepancy
  prediction stage `_build_predict_scaffold` (`analyze.py:5271-5305`) compiles
  child workflows with the cross-workflow walker's partial params, not
  dummy-padded params like `WorkflowValidator._validate_one_child_call`. When
  walker can't resolve an input (from upstream sub-workflow output),
  `prepare_inputs` raises `SchemaValidationError`, caught and demoted to a
  bare-type Notes entry. Fix: merge walker params with
  `generate_dummy_parameters` and preserve `exc.message`/`exc.path` in the
  skip note.
- **Second coarse gate** (`analyze.py:661-689`): same architectural smell as
  Bug 1's drift gate. Worth folding into a follow-up that lets partial-trace
  rows render with per-row `data_source` instead of discarding the whole
  trace.

## 2026-05-11 — Task 159 — Bug 3 fix: SchemaValidationError on validated sub-workflows

User-reported symptom (scratchpad `cache-analyzer-feedback-20260511.md` Bug 3):
`pflow analyze-cache` emits `Cache fidelity check skipped for concept-chooser.pflow.md:
workflow failed to compile (SchemaValidationError)` Notes for sub-workflows that
`pflow run` accepts and executes successfully end-to-end. Two workflows
(`concept-chooser`, `enforce-diversity`) affected on the lyrics-generator case.

Root cause: the discrepancy-prediction stage (`_build_predict_scaffold` in
`analyze.py:5283`) compiled each sub-workflow with the cross-workflow walker's
**partial** params dict — only inputs whose values flow statically from the
parent. Sub-workflow inputs that come from upstream node outputs (e.g.
`${analyze-sources.results}`) stayed empty; `compile_workflow → prepare_inputs`
raised `SchemaValidationError("Workflow requires input 'analyses'")`; the
catch site replaced the structured exception with `type(exc).__name__` and
emitted a misleading Note. The unified validator (`_run_full_validation`)
strictly precedes the prediction stage and pads with `__validation_placeholder__`
for every declared input — so it never sees this failure mode.

Fix (single architectural pattern, surgical scope):

- `_pad_inputs_for_prediction(known_params, declared_inputs)` merges walker-
  resolved values with `"__validation_placeholder__"` for missing declared
  inputs, returning the padded params + the set of dummied keys.
- `_build_predict_scaffold` now injects `_pflow_workflow_file=str(workflow_path)`
  into compile params (mirrors `WorkflowValidator._validate_one_child_call`)
  so relative `@./file.ext` refs resolve against the workflow's directory.
- Per-node check in `_predict_one_workflow` skips prediction silently when a
  node's `prompt_cache:` references a chunk whose `var` traces to a dummied
  key (`_dummied_cache_chunks` + `_node_prompt_cache_touches`) OR any
  `${var}` ref in the node's IR has a root in the dummied set
  (`_node_templates_touch`). Both checks are needed: cache chunks via
  `var:` and direct template refs are two independent paths to a
  placeholder-tainted predicted cache_key.
- Scaffold catch downgrade: kept broad (`CompilationError`, `MarkdownParseError`,
  `SchemaValidationError`, `WorkflowValidationError`, `FileNotFoundError`,
  `ValueError`) for defense-in-depth, but now debug-logs and silently
  returns `None`. The unified validator surfaces real structural errors
  through `blocking_errors[]` / `other_blocking_errors[]` earlier in
  `analyze()`, so user-facing Notes here are redundant at best, misleading
  at worst.
- `_predict_node_cache_key` (test helper) returns `(None, None)` on scaffold
  failure — matches the silent-skip contract.

Tradeoffs / trust boundary:

- Chose string sentinel (`"__validation_placeholder__"`) over a typed
  sentinel: it's the existing idiom (used by `generate_dummy_parameters`
  in 6 call sites including the validator's child-call boundary), is
  type-coercion-compatible for `string`/`any` inputs, and the detection
  problem ("does this node's cache_key consume a placeholder?") is solved
  statically by walking the node IR before compile — no need to detect
  placeholder values in resolved output. Static taint detection is more
  robust than string-sniffing post-resolution and doesn't depend on
  strict-vs-permissive template-resolution mode.
- Did not add a per-row or aggregated "predictions skipped for N nodes
  whose inputs depend on runtime values" Note. The existing per-call
  table's `cacheable inputs: ...` column and Recommended actions section
  already convey the actionable cache info for these nodes; a "couldn't
  predict" meta-note would be redundant. Observable-field attribution
  (TTL expiry, chunk-skipped) surfaces any actual cache miss on skipped
  nodes if one occurs.
- Did not delete the scaffold catch entirely. After the fix the catch is
  near-dead (the unified validator handles every structural error type
  it covers earlier in `analyze()`), but a `CompilationError` from
  compiler-internal failures the validator missed could still slip
  through — debug-logged silent return preserves the safety net without
  reintroducing the bug.

Per-node prediction is silent by design — the Notes section should only
carry information the agent can act on. Static-analysis tools that emit
"I skipped this for valid reasons" preemptively become noise floors;
pflow follows the "speak only when there's something to say" pattern.

Verification:

- 4 new focused tests + 3 updated regression tests (`tests/test_core/
  test_cache_analysis_per_id_emission.py`): all pass with mutation
  contracts documented in docstrings.
- Cache-analysis + CLI suite: 535 passed.
- Default test suite (`make test`, `-m "not e2e"`): 6,357 passed, 10
  skipped, 42 deselected. Integration suite: 218 passed. Total 6,575
  passing.
- Baseline harness: 75 passed, 0 drifted, 0 harness errors.
- Touched-file `ruff check`, `ruff format --check`, `mypy
  src/pflow/core/cache_analysis/` all clean.
- End-to-end on the user's reported workflow (lyrics-generator with
  `--from-trace ...153228.json`): the two misleading
  `concept-chooser.pflow.md / enforce-diversity.pflow.md ... workflow
  failed to compile (SchemaValidationError)` Notes are gone. Per-node
  skips for upstream node-output refs remain (correctly — those are
  honest `template_exception` cases for nodes whose templates touch
  runtime values like `${some-node.results}`).

## 2026-05-12 — Task 159 — Bug 3 post-implementation review

Reviewed `a15ca15d` against the root-cause findings. Verdict: solid,
surgical fix; no correctness issues. Architecture mirrors
`WorkflowValidator._validate_one_child_call` (placeholder padding +
`_pflow_workflow_file` injection); the truly-cold-vs-partial split at
`_predict_one_workflow` is the correct conceptual line.

Load-bearing insight the fix gets right: a node can be tainted by a
dummied input WITHOUT mentioning it directly, because
`cache.prompt-body-duplicates-cache` forbids inlining `${var}` when
declared as a cache chunk — so the only path from node to dummied input
is `prompt_cache: [name] → chunk var → root`. Without
`_dummied_cache_chunks` + `_node_prompt_cache_touches` the
lyrics-generator case would produce placeholder-tainted predictions
that silently never match the trace (worse than the original bug).
Locked by `test_node_references_any_detects_cache_chunk_chain`'s
mutation contract.

Minor observations (none blocking):

- `_predict_node_cache_key` is dead after the return-shape change
  (docstring says "kept for test callers" but no current callers).
- `_walk_strings` walks dict values only, not keys — correct in
  practice (pflow IR places templates in values), worth a docstring
  sentence.
- `_dummied_cache_chunks` handles dotted-path/bracket `var:` shapes
  the parser invariant currently rules out (`chunk.name == chunk.var_expr`,
  `markdown_parser.py:1754`) — over-general but cheap insurance.

## 2026-05-12 — Task 159 — Bug 5 fix: sub-workflow scope mismatch in actually-paid sum

Field-report Bug 5 (verified isolated repro in
`scratchpads/experiments/bug-5-scope-mismatch-{parent,child}.pflow.md`):
`pflow analyze-cache <child> --from-trace <parent-trace>` rendered nonsense
ratios like `adds ~$0.0048 vs no-cache, 130178% of no-cache cost` because
``actually_paid_usd`` summed every LLM cost in the parent trace while
``no_cache_hypothetical_usd`` was scoped to the analyzed child's IR rows.

### Root cause investigation

Three parallel `pflow-codebase-searcher` subagents + reading `trace_tree.py`
directly established:

1. **`compute_actually_paid`** (`cost_estimation.py:574-602`) called
   `trace.total_cost(descend_sub_workflows=True, ...)` which summed every LLM
   leaf in the trace via `iter_actual_cost_events` → `_sum_actual_cost_events`.
   No `workflow_path` filter applied; events outside the analyzed cohort
   contributed.
2. **`no_cache_hypothetical_usd`** (`cost_estimation.py:365-367`) iterated
   ``analysis.per_call`` rows scoped to the analyzed workflow's IR (rooted at
   ``lookup_path`` via `cw_result.irs_by_workflow`). Cohort: child only.
3. **Walker `workflow_path` parameter is attribution propagation, not a
   filter** — initial subagent finding asserted "every walker filters by
   workflow_path." Verified false by reading `trace_tree.py:106-210`:
   walkers yield every event unconditionally; `WalkEvent.workflow_path` is
   metadata threaded down for downstream attribution. The Plan agent caught
   the misread before I committed code.
4. **`_cost_delta` has no sanity cap** (`analyze.py:6156-6183`) — when
   numerator (parent total) is plugged in as `compared_value` and
   denominator (child slice) as `baseline_value`, the percentage blows up.
   Top-10% codebases trust their math after the cohort fix; the cap would
   paper over future scope bugs.

### Architectural reasoning

The codebase's established pattern (`iter_llm_leaves`, `iter_actual_cost_events`,
`walk`) accepts a `workflow_path` kwarg that propagates as attribution. ONLY
`total_cost` did not — so `compute_actually_paid` was the single consumer
unable to express scope intent. Initial plan was "scope at TraceTree
construction" (analogous to Path 1's `resolve_workflow` boundary fix), but
the Plan-agent review surfaced that walker behavior is attribution-only and
the codebase already had a per-method scope convention. The right shape was
to extend that existing pattern, not introduce a new one.

Filter location chosen at the consumer (`compute_actually_paid`), not inside
the walker:

- Walker stays general; only the cost-aggregation site needs scope policy.
- New consumers don't have to remember to filter — they get tree-wide
  semantics by default, opt into scoping when relevant.
- One place to test the filter contract.

### Implementation

**`src/pflow/core/trace_tree.py`** (~5 LOC):

- Renamed `_sum_actual_cost_events` → `sum_actual_cost_events` (4 internal
  callers + 1 new cross-module consumer). The underscore-by-convention was
  not load-bearing; the method is a useful primitive when working with
  filtered iterators.

**`src/pflow/core/cache_analysis/cost_estimation.py`** (~10 LOC):

- Added keyword-only `scope_workflow_paths: frozenset[str] | None = None`
  to `compute_actually_paid`. When set, iterate `iter_actual_cost_events`
  + filter `we.workflow_path in scope` + sum via `sum_actual_cost_events`.
  When `None`, today's tree-wide behavior preserved exactly.

**`src/pflow/core/cache_analysis/analyze.py`** (~50 LOC across three helpers):

- `_resolve_trace_scope(trace_data, lookup_path, notes) -> (seed, mismatch)`:
  Determines whether the trace was recorded for a different workflow than
  the one being analyzed AND chooses the walker seed correctly:
  - **Paths refer to the same workflow** (per path normalization): returns
    `(lookup_path, False)`. Walker seed matches row workflow_paths
    byte-exactly so per-row attribution works.
  - **Different workflows** (genuine Bug 5 case): returns
    `(trace's stored path, True)`. Walker seed is the trace's actual root
    so top-level parent events get attributed to the parent (not the
    analyzed child). The `True` flag activates per-workflow scope
    filtering and emits the disclosure Note.
- `_scope_workflow_paths(scope_mismatch, lookup_path, rows) -> frozenset | None`:
  Builds the scope set as `{lookup_path} ∪ {row.workflow_path}` when
  mismatched; returns `None` for tree-wide sum otherwise. Both helpers
  pulled out to keep `analyze()` under C901's complexity threshold.
- `_workflow_paths_refer_to_same(a, b)`: byte-exact short-circuit, then
  `os.path.realpath` for filesystem paths, with `ir-hash:` synthetic ids
  compared byte-exact (they cannot be resolved as filesystem paths).

Three call sites in `analyze()` and `_emit_discrepancy_diagnostics` now seed
walkers with `trace_root_workflow_path` (from `_resolve_trace_scope`) instead
of `lookup_path` directly. The seed only differs from `lookup_path` when
scope mismatch is detected; otherwise behavior is identical.

### Tests

Two new production-shape tests (Pitfall #19) at
`tests/test_core/test_cache_analysis_analyze.py`:

- `test_actually_paid_scopes_to_analyzed_workflow_when_trace_is_parent`:
  parent runs $1.00 padding LLM batch + invokes tiny $0.005 child 3× via
  `homogeneous_workflow_batch_event`. Pre-fix: `actually_paid` was ~$1.015
  (parent total). Post-fix: ~$0.015 (child's 3 invocations). Disclosure
  Note appears. Mutation contract: revert the filter in
  `compute_actually_paid` → assertion fails (jumps to parent total).
- `test_actually_paid_unchanged_when_trace_root_matches_analyzed_workflow`:
  parent IR + parent trace + child sub-workflow. Tree-wide sum: $0.15
  (parent's $0.05 + child's $0.10). No scope-mismatch Note. Mutation
  contract: unconditionally pass non-None scope_workflow_paths → tree-wide
  sum broken → assertion fails.

One existing test updated:
`test_analyze_end_to_end_current_cost_honors_recorded_trace_cost` was
relying on the pre-fix bug — it used a hardcoded `ir-hash:fake` trace
workflow_path that intentionally mismatched the synthesized lookup_path.
Updated to pass `workflow_path="ir-hash:fake"` so the trace aligns with
the analyzed identity; the test's intent ("trace cost flows through to
summary") is preserved without depending on the bug.

### Stage 2 — disclosure wording + trace fixture portability

After the initial code review (user noticed several baseline anomalies),
fixed two derived problems:

**Wording**: original Notes line "Trace was recorded for `X`; figures
scoped to events attributable to `Y`..." was ambiguous — "was recorded
for" could be parsed as "this analyze command recorded a trace" instead
of "the trace file you passed was previously recorded for X."
Rewrote to:

> "The trace file references workflow `<X>`, which differs from the
> analyzed workflow `<Y>`; cost figures show only events attributable
> to the analyzed workflow and its sub-workflows."

"References" is unambiguously passive — describes the file's stored
value, not an action taken by the command.

**Trace fixture portability**: three committed baseline trace fixtures
(`sample-2.1.0-trace.json`, `live-gemini-translation.trace.json`,
`live-gemini-lyrics-generator.trace.json`) stored absolute
`workflow_path` values from an older worktree
(`pflow-feat-prompt-caching`). After the Bug 5 fix, this triggered
scope-mismatch detection in baselines — `actually_paid` dropped to
unavailable, `curate-briefs` row hidden from per-call table, etc.

Changed each fixture's root `workflow_path` to a project-relative path
(e.g., `.taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md`).
Path normalization via `os.path.realpath` resolves the relative path
against the baseline runner's cwd (`BASELINE_REPO_ROOT`) → matches the
analyzed workflow's absolute path → `_workflow_paths_refer_to_same`
returns True → scope filter doesn't activate → baselines pass with no
expected-stdout changes.

### Walker seed correction — the path-identity subtlety

Initial attempt normalized the walker seed via `os.path.realpath`
unconditionally so that relative trace paths would produce events with
absolute attribution matching row keys. This broke inline tests where
`workflow_path="x"` (non-canonical, intentionally simple). Row keys had
`"x"`; walker emitted `realpath("x") = cwd/x`. Mismatch.

Final shape (correct): use `lookup_path` as the walker seed when paths
refer to the same workflow (so row keys match what the walker emits);
use the trace's stored path only when scope genuinely differs (so
top-level parent events get attributed to the parent, not the analyzed
child). This preserves row-matching for both:

- Inline tests (`lookup_path = "x"`, trace stores `"x"`): seed = `"x"`,
  rows = `"x"`, match.
- Baseline tests (`lookup_path = absolute`, trace stores relative path
  that resolves to same): seed = `absolute lookup_path`, rows =
  `absolute`, match.
- Bug 5 case (`lookup_path = child`, trace stores parent): seed =
  `parent`, top-level events tagged with parent. Rows have child path.
  Top-level events filtered out of `actually_paid` via scope set
  `{child} ∪ child's reachable workflows`. Child's sub-workflow events
  get attribution from batch_item / edges → match child rows.

### Verification

- Bug 5 repro at HEAD:
  - Pre-fix: `adds ~$0.0048 vs no-cache, 130178% of no-cache cost`.
  - Post-fix: `Actually paid: ~<$0.0001 (trace)`, `Actual savings: no
    meaningful cost change`. Disclosure Note names the parent trace.
- Focused cache-analysis + CLI + trace_tree suite: 690 passed.
- `make test` (default, `-m "not e2e"`): 6,583 passed, 1 skipped.
- Baseline harness: 74 passed, 1 drifted
  (`12-real-world-lyrics-generator/04-guide-auto-detect` — pre-existing
  unrelated drift, verified via `git stash` comparison).
- Touched-file `ruff check`, `ruff format --check`, focused `mypy` clean.

### Tacit knowledge

**Walker `workflow_path` is attribution, not filter.** `iter_*` methods
yield every event in the tree; `WalkEvent.workflow_path` is metadata
propagated through `edges` (and per-event fields on batch items / sub-
workflow events). Filtering by `workflow_path` happens at the consumer
(or doesn't happen at all). When extending these walkers, do not assume
the kwarg is a filter — it sets the seed for top-level events that lack
explicit attribution.

**Path identity is byte-exact at most key boundaries.** The per-row
`(workflow_path, node_id)` index does byte-exact lookup. `cw_result`
keys are byte-exact. The only normalized comparison is in
`_workflow_paths_refer_to_same` (used in `_resolve_trace_scope`). If
you change the walker seed to a normalized form, downstream per-row
matching breaks unless you ALSO normalize row workflow_paths — which
ripples into cw_result, file resolution, and a lot of test fixtures.
The chosen design avoids this by picking the seed at the boundary
(use `lookup_path` when paths refer to same; trace's raw value
otherwise) so byte-exact downstream matching keeps working.

**Trace fixtures should use project-relative paths.** Absolute paths
record the worktree they were generated in and silently break the
moment that worktree is renamed/moved. The portable shape is
`.taskmaster/.../*.pflow.md` (resolved against the baseline runner's
`BASELINE_REPO_ROOT` cwd at test time). For future trace fixtures,
either record with relative paths or post-process to relative after
generation.

**The Plan agent caught a load-bearing misread.** First Explore agent
asserted "every walker filters by workflow_path; consumers already
thread it" — which made the fix look like "just add the missing param
to `total_cost`." The Plan agent reviewed and noted the walker code
yields every event unconditionally. Verified by reading
`trace_tree.py:106-210` directly. If I'd shipped the fix as initially
designed (just add `workflow_path` to `total_cost`), the bug would not
have been fixed AND parent-analyzing-parent baselines would have
silently regressed. Reading the actual code beat subagent summaries
here.

**Out of scope / follow-ups**:

- `_build_trace_execution_index` (`analyze.py:1129`) and sub-workflow
  rollup pollution: same scope-pollution potential as
  `compute_actually_paid`. Seed correction helps (top-level parent
  events now attributed to parent), but the rollup's
  `current_cost_by_workflow` could still contain entries for workflow
  paths outside the analyzed scope. Not reported as a symptom yet;
  deferred until real cases surface.
- Auto-load gate at `analyze.py:933` keeps strict byte-exact comparison
  with `data.get("workflow_path") != workflow_path`. Could relax to
  use `_workflow_paths_refer_to_same` so traces stored with relative
  paths auto-load correctly. Not done because autoload's purpose is
  silent zero-friction default; relaxing creates a new failure mode
  (incorrect autoload pick) for marginal benefit.
- Defensive sanity cap on `_cost_delta` percentage — deliberately not
  added. The math is structurally correct after the scope fix; sprinkling
  defensive guards on outputs invites future regressions to pass silently.

## 2026-05-12 — Task 159 — Bug 4 fix: body-only cost disclosure for shadowed cache chunks

Implemented the `cache_contains_body` disclosure path without changing summary
math. `PerCallRow` now carries `chunk_tokens_estimated` and derives
`body_tokens_estimated`; JSON emits both. `_estimate_row_tokens` returns the
chunk/body split while preserving `input_tokens_estimated` as the billed total,
including trace rows by separately tokenizing declared chunks and clamping to
the normalized input total.

Analyzer-tier enrichment now mutates only `cache.prompt-body-shadows-cache`
diagnostics whose `shadowing_pairs[].direction == "cache_contains_body"` and
whose row has pricing plus output tokens. The text renderer prepends the
body-only vs with-cache cost comparison before the catalog suggestion; JSON
gets the optional context keys automatically. `RecommendedAction` now carries
a context snapshot because renderers build actions from diagnostics and the
cost evidence lives in diagnostic context, not in the catalog template.

Plan deviations, with reasons:

- Enrichment helper accepts `(rows, warnings, output_tokens_by_node)` rather
  than a partially constructed `CacheAnalysis`. Same mutation boundary, less
  artificial object construction before summary exists.
- `_per_call_first_run_with_cache_cost` mirrors
  `_aggregate_with_cache_projection` for static batches: one write, then read
  rates for remaining invocations. The plan pseudocode multiplied every batch
  invocation by write rate, which would diverge from the existing projection
  primitive.
- Manual `/private/tmp` reproducer file was not committed/kept; sandbox
  tooling rejected apply-patch writes outside the repo, and the production-
  shape tests cover the cost-enrichment path with trace output tokens.

Verification:

- New focused tests: 6 passed.
- Cache-analysis + analyze-cache CLI suite: 655 passed.
- Baseline harness with project-local `.venv/bin/uv`: 73 passed, 2 drifted.
  Remaining drifts are unrelated/pre-existing: guide auto-detect markdown
  formatting and `15-run-flag-interactions/03-report-with-only` sandbox
  `/dev/fd` behavior. Intended JSON drifts were regenerated and are limited
  to the additive per-call body/chunk fields.
- Near-full sandbox-safe suite: 6,607 passed, 19 skipped after excluding
  four subprocess tests that call `/opt/homebrew/bin/uv` and panic before
  Python starts in this sandbox.
- `ruff check`, `ruff format --check`, and focused `mypy
  src/pflow/core/cache_analysis/` clean.

### 2026-05-12 follow-up — TTL threading + manual repro

Closed the two loose ends from post-implementation review.

- Shadow-warning cost enrichment now prices with the row's workflow TTL, not
  `None`. The analyzer builds `ttl_by_workflow` from `cw_result.irs_by_workflow`
  so sub-workflow rows use their own `## Cache` TTL. Added a regression test
  proving Anthropic `ttl: 1h` warning context uses the 1h write-rate multiplier
  and is greater than the 5m/default figure.
- Manual Bug 4 cost-disclosure verification completed with an input-backed
  `/private/tmp` workflow plus trace fixture. The original plan's literal
  `prompt_cache: [bundle]` with cache `${make-bundle.result}` conflicts with
  the current parser invariant (`chunk.name == chunk.var_expr`), and code-node
  outputs are not available to greenfield analysis. The manual repro therefore
  used `bundle` as an input JSON string so the analyzer had resolved chunk
  bytes, plus `--from-trace` for output tokens. Output showed the expected
  cost-comparison lines while the summary remained on the inline-full-chunk
  baseline.

Verification after follow-up:

- Focused shadow/cost tests: 6 passed.
- Cache-analysis + analyze-cache CLI suite: 656 passed.
- Near-full sandbox-safe suite: 6,608 passed, 19 skipped.
- Baseline harness with project-local `.venv/bin/uv`: 73 passed, 2 drifted
  (same unrelated guide/report drifts as before).
- `ruff check`, `ruff format --check`, and focused `mypy
  src/pflow/core/cache_analysis/` clean.

### 2026-05-12 follow-up #2 — review-driven cleanup + end-to-end coverage

Tacit knowledge surfaced by post-implementation review; preserved here because
each item bites on first principles otherwise.

- **Lyrics-generator does NOT fire `cache.prompt-body-shadows-cache`.** Its
  `## Cache` chunks declare exactly the paths the body uses (matching, not
  parent paths), so `cache_contains_body` never triggers despite the workflow
  being full of object inputs and sub-path-style references. The canonical
  text baselines at `12-real-world-lyrics-generator/01,03` are correct to
  remain unchanged by Bug 4. Don't regenerate them expecting drift.
- **The ratio phrase is load-bearing, not cosmetic.** For Bug 4-scale rows
  both costs floor at `~<$0.0001` via `_format_dollar_amount`. Without the
  `caching is Nx more expensive` clause the warning reads as "X vs X" and
  the 160-300x signal disappears. Preserve the ratio computation in
  `_format_shadow_cache_cost_comparison` when touching the renderer.
- **`_cache_ttl_by_workflow` must seed `result[None]` with the fallback
  TTL.** Inline/synthesized workflows surface rows with `workflow_path=None`;
  without the `setdefault(None, fallback_ttl)` line, an Anthropic `ttl: 1h`
  declaration silently reverts to the default 5m write rate for those rows.
  Pure tuple-key map keyed by string paths is not enough.
- **`_output_tokens_for_row` once had a string-key fallback that never
  fired** because the map is built with tuple keys only. Removed; type
  narrowed to `Mapping[tuple[str | None, str], int | None]`. If a future
  change adds string keys, the fallback must come back AND the type widen
  in lockstep.
- **End-to-end coverage of the enrichment chain lives in the existing
  production-shape test**, not in a baseline case.
  `test_shadow_warning_enriched_with_costs_when_cache_contains_body` runs
  the full `analyze() → enrich → _build_actions → render_text` pipeline and
  asserts on the rendered output. New end-to-end tests for similar
  enrichment-style features should follow this pattern (call `render_text`
  on the analyze result) rather than introducing a new baseline case —
  baselines require CLI parameter passing for object inputs, which is
  operationally heavy for what is a unit-test-shaped invariant.

## 2026-05-12 — Task 159 Followups — Prompt-caching guide finalization

Followup pass on `src/pflow/guide/features/prompt-caching.md` after the
Bug 11 / 13 / 15 bundle landed and after verification work on prewarm ×
`## Cache` interaction (see
`scratchpads/experiments/prewarm-cache-interaction/FINDINGS.md`).

Three targeted edits to the Batch Nodes section:

- **Replaced the misleading example.** The previous `score-each-chorus`
  example used a tiny rubric placeholder (~15 tokens) without saying
  prewarm needs ≥1k–4k tokens to fire. Rewrote with a multi-paragraph
  rubric placeholder + an explicit size note. The cache-boundary rule
  now appears in prose right under the example: "The cache prefix ends
  at the first per-item reference. Everything before `${item.text}` —
  including static refs like `${rubric}` — is resolved into the cached
  prefix. If you mix per-item refs into the middle, the cached prefix
  is cut short, so put `${item.X}` content last." (Concept 4 from the
  field report — the highest-yield optimization pattern in the
  lyrics-generator session, previously documented nowhere.)
- **Deleted the `- inputs:` indirection paragraph.** The paragraph
  defensively explained why a previously-fixed bug (PR #390) now works.
  An agent reading it gains nothing actionable; an agent NOT using
  `- inputs:` is confused by it. The runtime behavior the paragraph
  described is correct and remains correct — the documentation just
  doesn't need to assure agents of it.
- **Added a "Combining `## Cache` with prewarm" subsection.** Three
  bullet decision-rule: "only prewarm" / "only `## Cache`" / "both"
  based on workflow shape. The combined case is verified mechanically
  (both render paths fire independently — `_build_user_message_blocks`
  for prewarm, `_build_system_blocks` for declared cache — producing
  two cache_control markers per call within Anthropic's 4-marker limit).

### Files

- `src/pflow/guide/features/prompt-caching.md` — Batch Nodes section
  rewrite (size guidance + revised example + boundary rule + combining
  subsection); `- inputs:` paragraph removed.
- `.taskmaster/tasks/task_159/baseline/12-real-world-lyrics-generator/04-guide-auto-detect/expected-stdout.txt`
  regenerated to match.

### Verification

- `pflow guide prompt-caching` renders the section as expected.
- Guide test suite: 61 passed.
- Baseline harness: 5 passed, 0 drifted after the one-case
  regeneration.

### Out of scope / known followups

Verification of the rewrite (`scratchpads/experiments/prewarm-cache-interaction/FINDINGS.md`)
surfaced 3 analyzer projection bugs that should be addressed
separately:

- **Bug A (HIGH)** — interleaved per-item ref: analyzer reports 100%
  cache ratio because `_estimate_batch_prefix_cacheable_tokens` returns
  cohort tokens (`prefix × call_count`) and the downstream clamp
  `min(cohort, input_per_call)` always loses to `input_per_call` for
  batch_size ≥ 2.
- **Bug B (HIGH)** — prewarm-only below provider min is silent:
  `below_min_tokens_detector` gates on `declared_prompt_cache` being
  non-empty, so auto-batch-prefix below threshold doesn't warn.
- **Bug C (MEDIUM)** — combined prewarm + declared: prewarm's
  contribution is invisible in `cacheable_tokens_estimated` (the two
  evidence tiers are mutually exclusive in `_prefer_batch_prefix_cacheable_tokens`).

The cache rendering layer itself is correct (verified via direct code
read + classifier isolation tests); these bugs only affect the
analyzer's projection numbers, not what actually goes on the wire.

## 2026-05-12 — Task 159 Followups — Bug 11 / 13 / 15 wording bundle

Three small wording fixes targeting analyzer-internal jargon in agent-facing
text. Bundled because each was a localized string change; no logic affected.

- **Bug 11 — `prewarm: false` reads as a behavior toggle.** Catalog suggestion
  for `cache.batch-prewarm-recommended` (`warning_catalog.py:337`) rewritten
  from "opt out explicitly (suppresses this warning)" to "silence this
  recommendation (use when you've decided not to prewarm — `false` is a marker
  for the analyzer, not a runtime toggle)." Added a 4-line clarification under
  Batch Nodes in `src/pflow/guide/features/prompt-caching.md` so agents
  arriving from the guide see the same framing.
- **Bug 13 — "pass-through" jargon.** `_format_passthrough_footnote`
  rewritten to lead with "~$X of the above was paid by {node} but couldn't be
  analyzed for cache savings ({reason})" and follow with "Caching may still
  apply at runtime if its content repeats across calls." Multi-node form
  inlines the per-node reason rather than CSV-only.
- **Bug 15 — `medium_from_memo` enum leaks to text.** Header Confidence line
  now renders plain English: `Confidence: medium — token counts from
  memoized prior runs (N of N nodes)` / `Confidence: high — token counts
  from this run's trace (N of N nodes)`. JSON `estimate_confidence` keeps the
  raw enum for machine consumers.

### Files

- `src/pflow/core/cache_analysis/warning_catalog.py` — Bug 11 suggestion.
- `src/pflow/core/cache_analysis/render_text.py` — Bug 13
  `_format_passthrough_footnote` + Bug 15 new `_format_confidence_line`.
- `src/pflow/guide/features/prompt-caching.md` — Bug 11 paragraph.
- `tests/test_core/test_cache_analysis_renderers.py` — 4 wording assertion
  updates + 4 negative assertions locking out `pass-through`,
  `medium_from_memo`, `high_from_trace`.
- `tests/test_core/test_cache_analysis_analyze.py` — 1 assertion migration.

### Verification

- Focused cache-analysis + CLI suite: 411 passed.
- Baseline harness: 72 passed, 3 drifted (all 3 pre-existing on HEAD —
  parser-error TTL wording; verified by stash-and-rerun). Regenerated
  `10-live-recordings/05-gemini-lyrics-generator` and
  `12-real-world-lyrics-generator/04-guide-auto-detect` to bundle these
  changes with the stale-but-correct guide updates from earlier sweeps.
- Touched-file `ruff check`, `ruff format --check`, focused `mypy` clean.

## 2026-05-12 — Task 159 Followups — Bug 8 fix: delete broken TTL discrepancy attribution

Removed `ttl_expiry` from `cache.discrepancy` because the analyzer only had
`cache_age_sec` from pflow's memo cache, not provider prompt-cache age. The
old recommendation (`Consider - ttl: 1h`) was therefore aimed at the wrong
cache layer. Discrepancy attribution now has two structural branches:
`chunk_skipped` and `key_mismatch`; events with missing actual/predicted keys
are silently skipped and rely on the existing prediction-skip notes.

Retired the `cache.discrepancy` dispatch maps and `make_diagnostic` special
case. The catalog row now uses the same flat `suggestions_template` path as
other warnings, and JSON format moved `4.1 -> 4.2` because per-diagnostic
context no longer carries `trace_path`, `predicted_pct`, `predicted_label`,
`actual_pct`, or `cache_age_sec`.

Deviations / learnings:

- `_ensure_discrepancy_workflow_scope` already backfilled
  `workflow_path_short`, but `_basename_for_workflow` did not strip
  `.pflow.md`. Updated that helper instead of re-adding duplicate
  call-site fields; it is only used for discrepancy scope.
- The JSON version bump intentionally drifted every JSON baseline, not only
  the discrepancy case. Regenerated the version line across JSON baselines;
  remaining baseline drift is unrelated pre-existing parser TTL wording plus
  the sandbox `/dev/fd` report case.
- No provider-TTL expiry detection ships here. Follow-up issue to file after
  merge: **Detect provider prompt-cache TTL expiry from trace timestamps**.
  It should use per-prefix write/read timestamps and add a new catalog ID
  after DD#29 review.

History references preserved as append-only context: task spec lines
`task-159.md:274, 492-499`; implementation-progress-log entries
`733, 1822, 5088, 6012, 6046, 6076`; recommendations plan lines
`fix-plans/recommendations-section-plan.md:91, 482, 571, 575, 612, 613, 700, 804`.

Verification:

- Focused cache-analysis + CLI suite: 652 passed.
- Baseline harness after expected JSON/version updates: 71 passed, 4 drifted
  (all unrelated/pre-existing: three parser TTL wording cases and
  `15-run-flag-interactions/03-report-with-only` sandbox `/dev/fd` drift).
- Near-full sandbox-safe suite: first run exposed 4 additional
  `/opt/homebrew/bin/uv` subprocess panics; rerun excluding those sandbox-only
  tests plus the known skill exclusions passed: 6,678 passed, 19 skipped.
- `ruff check`, `ruff format --check`, and focused `mypy
  src/pflow/core/cache_analysis` clean.