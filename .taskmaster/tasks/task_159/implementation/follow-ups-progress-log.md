## 2026-05-13 — Task 159 Followups — UX 10 fix: plain-English per-call explainer + static-mode trace hint + cost tier label

Three coordinated agent-UX polish fixes after a cold-reader pass over the
canonical lyrics-generator capture. Each had a different root cause but all
exposed pflow-internal vocabulary to fresh AI agents reading
`pflow analyze-cache` text output. Bundled because they all touched
`render_text.py` and shared one baseline-regen pass.

Durable user directive captured this session: **always apply the cold-reader
test to ALL CLI outputs**. Every fix below was validated by reading the
post-regen baseline as a fresh agent who has never read pflow source.

### Problem statement

Field-report UX 10 (`scratchpads/cache-analyzer-feedback-20260511.md`)
flagged the per-call table as "mostly blank ink" when no trace was loaded.
Investigation surfaced three distinct agent-UX failures stacked on the same
output region:

1. **Per-call explainer leaked `tier` jargon.** Line 1840 of `render_text.py`
   read `"— means the column does not apply to this row's tier"`. "Tier" is
   pflow-internal shorthand for the `data_source` / `cacheable_data_source`
   enum classification (values: `trace`, `memo`, `estimator`, `heuristic`,
   `parameters`, `batch_prefix`, `cross_workflow_projection`, `unavailable`).
   A fresh agent reading the stdout had no way to know what "tier" meant or
   which combinations made `—` "apply" — the column-by-column mapping is
   only readable from source. The full four-line explainer block was
   written for the implementer, not the agent.

2. **Static-mode rows had empty notes.** `_unavailable_could_cache_note`
   short-circuited to `None` when `observed_call_count == 0`. For workflows
   analyzed without a trace (the lyrics-generator's canonical case), every
   sub-workflow row rendered with `cached_now: —`, `could_cache: ?`,
   `ratio: ?%`, `calls: —`, and a blank notes column. The agent saw
   placeholders with no explanation and no next step. The fallback function
   handled `observed_call_count == 1` (`"single call …"`) and `≥ 2`
   (`"no stable N-token repeated prefix found"`) but treated `== 0` as
   "nothing to say."

3. **Cost block leaked snake_case enum.** `_format_cost`'s tier parenthetical
   passed `s.actually_paid_tier.value` through unchanged, producing
   `Actually paid: ~$2.31 (trace_partial)` for partial-trace cases. The
   `(trace)` variant happens to read cleanly as plain English; `(trace_partial)`
   reads as a raw `CostTier` enum value.

### Root-cause investigation

Three parallel `pflow-codebase-searcher` runs verified the bug landscape:

1. **Vocabulary audit** (stdout-bound strings only — code comments out of
   scope): one real jargon leak at `render_text.py:1840`, one enum leak at
   `render_text.py:779`, no other agent-facing strings used pflow-internal
   vocabulary. The "Confidence: high — …" line at `:229` was a false alarm
   (the word `tier` only appears in the Python variable name, not stdout).

2. **Row-state landscape**: enumerated 14 distinct row states across
   `(trace_loaded?, cacheable_data_source, observed_call_count, model-kind)`.
   Cases #11 (model resolved, 0 calls, no trace), #12 (model unresolved),
   and #13 (heterogeneous IR + no observed) all fell through every branch
   of `_unavailable_could_cache_note` to return `None`. The `<unresolved>` /
   `<varies>` model strings are render-time only; the underlying state lives
   in `(model_is_heterogeneous, observed_models, model)`. **Recommendation:
   extend the existing fallback function; do not introduce a new
   abstraction.** Six leaves is well within the size where one switch-style
   function is the most readable shape; top-10% CLI codebases (ruff, click,
   rich) use plain if-elif ladders at this scale.

3. **Blast radius scoping**: 17 baselines contain the explainer text,
   ~5 high-confidence baselines would gain the new note, 2 test functions
   in 1 file (`test_cache_analysis_renderers.py`) cover ~9 wording
   assertions. Regen harness exists (`regenerate.sh`).

### Architectural reasoning

The user-stated priority hierarchy this session:

1. Agent UX is the absolute highest priority.
2. Simplicity of FINAL code (not how easy it is to get there).
3. What would the top 10% of codebases similar to this one implement?

Applied to each fix:

- **Explainer**: collapsed steady-state (B2) and post-run-greenfield (B3)
  leads into one shared block. The prior split forced agents to know the
  steady-state-vs-greenfield distinction before they could read the column
  documentation — the column meaning is identical in both modes. The
  truncated-trace branch (B1) preserved verbatim because partial coverage
  changes how missing values should be interpreted. Dropped the dead
  `is_steady_state` local. Each `?` / `—` placeholder now explained in the
  column it appears in — no "sibling column" abstraction, no "tier"
  vocabulary.

- **Static-mode note**: added one branch before the `observed_call_count == 1`
  check. Names the cause (`no trace recorded`) AND the unblocking action
  (`run with --report to populate this row`). One unified note for cases
  #11 / #12 / #13 — the `model` column already shows `<unresolved>` /
  `<varies>` for the WHY; `--report` is the universal action regardless of
  model state. Removed the now-dead `observed_call_count < 2` check
  (unreachable after the `== 0` and `== 1` branches above it).

- **Cost tier label**: introduced `_TIER_LABELS = {"trace": "from trace",
  "trace_partial": "from partial trace"}` with `.get(tier, tier)` fallback.
  Defensive: unknown enum values pass through unchanged, preserving
  information if a new `CostTier` reaches this code path. Only `TRACE` and
  `TRACE_PARTIAL` reach `_format_cost` today (verified at the call site —
  `_render_trace_cost_lines` is only entered when `actually_paid_usd is not
  None`, which `RECOMPUTED` and `UNAVAILABLE` never produce).

**Rejected refactors** considered and dropped:

- `row_state_phrase(row) -> str` predicate centralizing all jargon
  translation. Would earn its keep if multiple consumers needed the same
  state phrasing — today exactly one (text render) does. Premature.
- Frozen-dataclass `RowState` enum at row-build time in `analyze.py`. JSON
  consumers can derive the same from existing fields. Task 160 may
  formalize this as part of `PerCallRow` taxonomy.
- Predicate→note registry. Adds dispatch indirection for one caller, one
  extension point per release, no ranking, no third-party registration.
  Warning catalog uses the registry shape correctly because warnings ARE
  data; per-row notes are render logic.

### Implementation

**Production (`src/pflow/core/cache_analysis/render_text.py`, +72/-79 LOC):**

1. `_per_call_scope_explainer` (lines 1810-1838): kept `truncated_trace_executed_subset`
   early return; merged B2/B3 into one shared block. Two column bullets,
   each explaining its own `?` / `—` placeholders inline.

   ```
   How to read each row:
     · cached_now: tokens served from cache during this run. `—` if no trace was recorded.
     · could_cache: extra cacheable tokens if you declared/extended `prompt_cache:`. `?` if the analyzer couldn't project; `—` if cached_now already has the measured number.
   ```

2. `_unavailable_could_cache_note` (lines 1757-1775): new branch:

   ```python
   if row.observed_call_count == 0:
       return "no trace recorded — run with --report to populate this row"
   ```

   Deleted the now-dead `if row.observed_call_count < 2: return None` check
   that previously sat between the `== 1` branch and the model-aware
   branches. With `== 0` and `== 1` both handled above, the `< 2` check
   only caught negative values — impossible for a count.

3. `_format_cost` (lines 754-797): added module-level `_TIER_LABELS` dict
   and `.get(tier_annotation, tier_annotation)` lookup. Single-line semantic
   change; the rest of the function unchanged.

**Tests (`tests/test_core/test_cache_analysis_renderers.py`, +180/-79 LOC):**

- Rewrote 4 explainer tests for the collapsed block with negative
  assertions locking out `this row's tier`, `sibling column`, and the
  legacy split-lead strings (`Actual cache ratios from declared`,
  `Projected cache ratios from prior run data`).
- Extended `_make_analysis` test helper to accept
  `actually_paid_tier: CostTier | None` so tests can exercise non-default
  tiers without contortion.
- Added parametrized
  `test_text_unavailable_row_notes_static_mode_zero_calls` covering
  both `model="anthropic/claude-sonnet-4-5"` and `model=""` (case #11 /
  #12 unification). Mutation contract documented inline: remove the
  `== 0` branch → note disappears.
- Added `test_text_cost_tier_annotation_renders_plain_english` for the
  `(from partial trace)` rendering. Negative assertion locks out raw
  `trace_partial`.
- Updated trace-mode parenthetical test for `(from trace)`.

### Baselines

Regenerated 21 baselines via `regenerate.sh`. Surfaces affected:

- Explainer rewrite: `01-parser-errors/{03,09}`, `02-validator-errors/{06,07,08}`,
  `03-analyze-cache-modes/{01,03,05,06,08}`, `04-warning-catalog/{08,12,14}`,
  `10-live-recordings/{03,05}`, `12-real-world-lyrics-generator/{01,03}`.
- Cost parenthetical: `15-run-flag-interactions/01-partial-trace-analyze-cache`
  (the canonical `trace_partial` repro).
- New static-mode note: `12-real-world-lyrics-generator/{01,03}` (the
  canonical lyrics-generator no-trace case — 7 rows under `song-creator`
  now show `no trace recorded — run with --report to populate this row`).

Three baselines that were drifting pre-existing (`01-parser-errors/{01,06,08}`
and `04-warning-catalog/12-cache.discrepancy`) also resolved in this regen
pass — incidental cleanup.

### Verification

- Focused renderer tests: **164 passed**.
- Cache-analysis + CLI suite (`tests/test_core/test_cache_analysis_*.py` +
  `tests/test_cli/test_analyze_cache.py`): **678 passed**.
- Broad sandbox-safe sweep (`tests/test_core/` + `tests/test_cli/`, excluding
  e2e): **3,233 passed, 0 failures, 41 deselected**.
- Baseline harness: **76 passed, 0 drifted, 0 harness errors**.
- `ruff check`, `ruff format --check`, `mypy src/pflow/core/cache_analysis/`
  — clean on all touched source files.
- **Cold-reader spot check** on
  `baseline/12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt`
  and `baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`:
  explainer reads cleanly with no "tier" / "sibling column" jargon; per-row
  notes carry both cause and action; trace-mode rows correctly skip the new
  note (existing `observed_call_count > 0` paths unchanged).

### Tacit knowledge

**The `<unresolved>` / `<varies>` model strings are render-only.** Producer
state is `(row.model_is_heterogeneous, len(row.observed_models), bool(row.model))`.
Any future note function consulting model state should check the underlying
tuple, not parse the rendered cell. Worth a docstring note on `_cell_model`
if a second consumer appears.

**The `_TIER_LABELS` map is closed on the public enum (`CostTier`).** New
enum values that reach `_format_cost` will render as raw strings (the
`.get()` fallback). This is intentional — silent dropping would be worse —
but means new enum values need a paired label entry. Test
`test_text_cost_tier_annotation_renders_plain_english` covers `TRACE_PARTIAL`;
adding new values requires extending the test.

**Residual visual density in static-mode rows.** Post-fix, the lyrics-generator
no-trace output still has two layers of repetition: 4 columns of
placeholder values (`—  ?  ?%  —`) repeated on every row, AND the new
note repeated verbatim on 7 contiguous rows. The cold-reader test on the
shipped output passes for clarity but flags repetition as residual noise.
Follow-up considered: column-hiding (Alternative A from the original UX 10
options) combined with note de-duplication (footer-style aggregation).
Together those would deliver a genuinely scannable static-mode table; either
in isolation leaves the other as residual noise. **Not in this PR** — see
"What's next" below.

**The cold-reader directive applies to all CLI surfaces going forward.**
This PR confined the audit to `analyze-cache` text output. UX 8 (`pricing
unavailable for: unknown` in post-run cost summary at `success_formatter.py`
and `cli/workflow_output.py`) is a confirmed separate-subsystem leak that
should be addressed in a `pflow run` polish pass.

### What's next (still open)

- **Column hiding + note de-dup bundle.** ~80–110 LOC, ~20 baseline regens,
  ~4 new tests. Combines Alternative A (hide universally-empty columns) and
  footer-style note aggregation. Cold-reader test on the post-fix output
  shows the repetition is the largest remaining UX gap; the bundle would
  close it.
- **`settings.default_model` in static mode.** The lyrics-generator no-trace
  baseline shows `<unresolved>` model for every static-mode row — investigate
  whether this is the analyzer not reading user settings, or expected
  behavior for the baseline harness (which runs in a clean environment).
  If the analyzer SHOULD read settings, case #12 (model unresolved) would
  collapse into case #11 for most real-world invocations.
- **UX 8 (post-run cost summary `pricing unavailable for: unknown`).**
  Different subsystem; not in this PR's scope. Confirmed leak at
  `success_formatter.py:278` and `cli/workflow_output.py:471`.
- **Concept 4 — guide section on per-item interleaved content.** Biggest
  empirical win in the field report (curate-briefs went from ~0 to ~30K
  cacheable after reorder), still undocumented as a pattern.

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

## 2026-05-13 — Task 159 Followups — Bug 4 fix: template-honest sub-workflow cache refs

Implemented `scratchpads/bug-4-template-honest-subworkflow-cache/implementation-plan.md`.
Sub-workflow cache recommendations now derive candidates from actual child
prompt refs, not from the boundary input root. A child prompt using
`${concept.core_idea}` and `${concept.title}` recommends `concept.core_idea`
and `concept.title`; it no longer recommends caching full `concept` unless a
prompt actually uses `${concept}`.

Key implementation points:

- Added path helpers and `_ChildCacheRefUse` in `analyze.py`. Both grouped
  recommendations and per-call `cross_workflow_projection` rows consume that
  shared prompt-ref extraction result.
- Extended `_SubWorkflowCacheCandidate`, `_RowCrossWorkflowCandidate`, and
  `CrossWorkflowInputContribution` with `child_cache_ref` / `parent_cache_ref`.
  `child_input_name` remains boundary metadata; it is no longer the candidate
  identity.
- Updated trace fallback to resolve the child suffix inside
  `node_params.inputs[child_input_name]`, so trace-backed subpath estimates
  tokenize `inputs.concept.title` instead of the full resolved object.
- Text recommendations now say "entries in ## Cache" / "values", include a
  full-object exposure warning for subpath cases, and show exact child edits:
  `## Cache` entries, per-node `prompt_cache`, and prompt-body templates to
  remove.
- JSON/MCP docs are additive: `inputs[]` and
  `per_call[].cross_workflow_inputs[]` now carry `child_cache_ref` and
  `parent_cache_ref` while preserving `child_input_name`.

Deviations / learnings:

- Kept direct-root behavior intact with compatibility defaults on the
  dataclasses. Existing callers/tests constructing `CrossWorkflowInputContribution`
  or `_SubWorkflowCacheCandidate` without the new fields still represent root
  candidates correctly.
- Multiple parent origins for the same child cache ref are not measured from a
  lexicographic winner. Aggregation marks those entries as multi-origin and
  leaves token estimates unmeasurable rather than presenting one origin as
  truth.
- The original no-trace gate had to change from "same ref consumed by at least
  two nodes" to "the group has at least two child consumers." That is required
  for the 05b shape where different subpaths under one input are consumed by
  different child nodes; otherwise the analyzer would silently drop the exact
  bug case this fix targets.
- The baseline harness uses `uv run`, which panics in this sandbox. For
  baseline verification only, used a temporary `/private/tmp` PATH wrapper that
  maps `uv run pflow ...` to the project virtualenv `pflow`, following the
  sandbox-testing skill's guidance to avoid Homebrew `uv`.

Verification:

- Focused requested tests:
  `tests/test_core/test_cache_analysis_per_id_emission.py`,
  `tests/test_core/test_cache_analysis_analyze.py`,
  `tests/test_core/test_cache_analysis_renderers.py`: 458 passed.
- Additional warning coverage: `tests/test_core/test_cache_analysis_warnings.py`:
  61 passed.
- Broader core suite, excluding three `/opt/homebrew/bin/uv` subprocess tests
  that panic before Python starts in this sandbox: 2,548 passed, 1 skipped,
  3 deselected.
- Affected baselines verified clean after regeneration:
  `04-warning-catalog/05`, `04-warning-catalog/05b`,
  `10-live-recordings/05-gemini-lyrics-generator`, and all
  `12-real-world-lyrics-generator` cases.
- `ruff check` on touched files and `mypy src/pflow/core/cache_analysis/`
  clean.

## 2026-05-13 — Task 159 Followups — FINDINGS Bug B + Bug 17: prewarm prefix-below-min + wall-clock disclosure

Two field-report items shipped together because they share `_provider_note`
and the "what does `prewarm: true` mean to the agent" mental model.

### Problem statement

**FINDINGS Bug B** (`scratchpads/experiments/prewarm-cache-interaction/FINDINGS.md`):
batch nodes with `prewarm: true` and a static prefix below the provider's
minimum produce `cache_ratio_pct = 100` in analyze-cache output with no
warning. At runtime the provider silently no-ops the `cache_control`
marker; the agent pays full price plus the prewarm wall-clock penalty.
The E3 experiment workflow (27-token prefix on Sonnet-4-5, 1024 min) is
the canonical first-contact agent failure case.

**FINDINGS Bug 17** (`cache-analyzer-feedback-part2-20260511.md`): the
existing `cache.batch-prewarm-recommended` action presents `prewarm: true`
as pure upside (`saves ~$0.0007/run`) without disclosing that it
serializes the first batch item, adding ~T(slowest item) of wall-clock to
every run. Verified 4.2–4.6× wall-clock penalty in isolation. For
latency-sensitive workflows the recommendation can be a net loss.

### Root cause investigation

`below_min_tokens_detector.detect` (the existing detector behind
`cache.below-min-tokens`) gates on `evidence.declared_prompt_cache`
non-empty. The outer call site at `analyze.py:_per_node_warnings` mirrors
that gate with `if row.declared_prompt_cache:`. Prewarm-only batches —
where there is no `## Cache` block but `prewarm: true` is declared — skip
both gates entirely. Post-Bug-A (per-call honest `cacheable_tokens_estimated`
for `batch_prefix` rows) the data needed to fire a below-min warning is
already on `PerCallRow`; the missing piece was an emission path.

`cache.batch-prewarm-recommended` is emitted by
`_batch_prewarm_recommendations` (`analyze.py:2566-2627`) only when
`"prewarm" not in node`. The savings formula is pure tokens × rate, no
wall-clock factor; no trace per-event duration ever flows into
`PerCallRow`.

### Architectural reasoning

**New catalog ID vs extending `cache.below-min-tokens`.** Considered both;
chose new ID `cache.batch-prewarm-below-min` because the remediation
prose differs fundamentally. `cache.below-min-tokens` suggests "Increase
cache content above {min_tokens} tokens by adding more chunks to
## Cache, OR remove `prompt_cache:` from {node_id}" — both phrases
assume declared cache. The prewarm path's agent has no `prompt_cache:`
to remove; their options are restructure the prompt prefix or drop
`prewarm: true`. Leaking declared-cache vocabulary into prewarm
diagnostics would mislead. DD#27/29 (closed catalog) is honored — this
counts as the design review for adding the new ID.

**Static caveat vs trace-backed wall-clock number.** Considered plumbing
`slowest_item_duration_ms` from trace into a new `PerCallRow` field and
rendering `adds ~9.2s wall-clock per run (from trace)` when available.
Rejected for this PR: prematurely adds a field nothing else consumes
("design for hypothetical future requirements" smell), and the
qualitative caveat already addresses the actively-misleading framing.
The wall-clock bullet's "Measure end-to-end duration before committing"
hint gives agents the same actionable reasoning a concrete number
would — without the plumbing risk. Trace-backed seconds can land later
when a second consumer for per-row latency shows up.

**Gemini implicit-cache caveat — considered and rejected.** First draft
included an "On Gemini, the provider's implicit cache may already capture
most prefix savings without `prewarm: true`" bullet. Removed after review
on three grounds: (1) it fired unconditionally for every batch node
because catalog suggestions don't dispatch on `row.model`, making it
noise for Anthropic/OpenAI agents; (2) it's based on one experimental
data point and Gemini's implicit-cache behavior isn't precisely
documented; (3) it effectively second-guesses the headline recommendation
("we recommend X, but maybe ignore it"), undermining its actionability.
If a stronger version is wanted later, it needs per-row provider dispatch
at emission time and ideally trace evidence — not a static suggestion.

**Shared `provider_clause` derivation.** Lifted the inline
`format_dict["provider_clause"] = "; " + provider_note` from
`_select_below_min_tokens_template` into `make_diagnostic` itself,
guarded by `if "provider_note" in context_kwargs`. Both catalog IDs share
it; any future provider-aware ID gets it automatically. Mirrors the
existing `node_count → nodes_phrase` and `affected_input_count →
inputs_phrase` derivations.

### Implementation

**Detector (`below_min_tokens_detector.py`, +47 LOC):**
- `BatchPrewarmBelowMinEvidence` (frozen dataclass) — fields `node_id`,
  `model`, `prefix_tokens`, `batch_alias`.
- `BatchPrewarmBelowMinFinding` — adds `min_tokens`, `provider_note`.
- `detect_batch_prewarm_below_min(evidence)` returns finding when
  `prefix_tokens > 0` AND `prefix_tokens < get_min_cache_tokens(model)`.
  Reuses the existing `_provider_note(model)` helper — no new
  provider-string vocabulary. The `prefix_tokens > 0` floor is
  load-bearing: the zero-prefix case is owned by `cache.prewarm-no-prefix`
  and the two warnings must be mutually exclusive.

**Catalog (`warning_catalog.py`, +50 LOC):**
- `_BATCH_PREWARM_BELOW_MIN_MESSAGE` template — message names the bytes
  before the first `${{<batch_alias>.X}}` reference (not "declared
  cache").
- `cache.batch-prewarm-below-min` spec — severity WARNING, category
  `CACHE_WARNING_CATEGORY`, required context
  `(node_id, model, prefix_tokens, min_tokens, batch_alias,
  provider_note)`, two suggestions (restructure prompt OR remove
  `- prewarm: true`).
- Priority slot 30 — Tier 5 (informational warnings that surface latent
  issues), peer with `cache.below-min-tokens` and
  `cache.prewarm-no-prefix`.
- `cache.batch-prewarm-recommended` `suggestions_template` extended with
  one wall-clock trade-off bullet between the existing "Add `- prewarm:
  true`" line and the "OR add `- prewarm: false`" line. No new context
  keys; no emission-side change.
- `make_diagnostic` shared `provider_clause` derivation (see
  Architectural reasoning).

**Emission (`analyze.py:_per_node_warnings`, +29 LOC):**
- Extended the existing prewarm block. Mutual exclusion is per
  `first_per_item_position(prompt, alias, node_inputs)`:
  - `first == 0` → `cache.prewarm-no-prefix` (existing).
  - `first > 0` AND `not row.declared_prompt_cache` →
    `cache.batch-prewarm-below-min` (new). The `not declared_prompt_cache`
    guard is critical: when `## Cache` is declared, prewarm writes the
    declared chunk via the serialized first call — the prompt-body prefix
    is irrelevant. Caught by the baseline harness on
    `13-happy-path-interactions/01-batch-cache-prewarm-happy` (the
    "already-optimal" case) before merging. `cache.below-min-tokens`
    owns the declared-cache below-min path.
- `prefix_tokens` computed via `estimate_tokens(row.model, prompt[:first])`
  — mirrors `_batch_prewarm_recommendations`'s own boundary tokenization,
  not the `PerCallRow.cacheable_tokens_estimated` field. More robust
  against future projection-tier changes.

**MCP docstring (`mcp_server/tools/execution_tools.py`, +1 LOC):** new
ID added to the public-API docstring list per the
`test_docstring_lists_every_catalog_id` contract.

### Tests added (+10)

**Detector unit tests (`test_below_min_tokens_detector.py`):**
- `test_prewarm_below_min_prefix_under_threshold_returns_finding`
- `test_prewarm_below_min_prefix_at_threshold_returns_none`
- `test_prewarm_below_min_prefix_above_threshold_returns_none`
- `test_prewarm_below_min_zero_or_negative_prefix_returns_none` —
  documents the mutual-exclusion floor.
- `test_prewarm_below_min_empty_model_returns_none`
- `test_prewarm_below_min_provider_notes_are_provider_specific` —
  Anthropic, Gemini, OpenAI distinct prose.
- `test_prewarm_below_min_threshold_varies_by_model` — Sonnet-4-5 (1024)
  vs Opus-4-7 (4096) on the same 2048-token prefix, verifies the
  threshold lookup isn't hardcoded.

**Catalog/make_diagnostic tests (`test_cache_analysis_warnings.py`):**
- Bumped `test_catalog_size_matches_v1_inventory` from 23 → 24 + added
  the new ID to the docstring inventory.
- `test_make_diagnostic_batch_prewarm_below_min_anthropic` — positive
  + negative substring assertions; locks declared-cache vocabulary
  (`declared cache`, `prompt_cache:`) OUT of this code path.
- `test_make_diagnostic_batch_prewarm_below_min_gemini_implicit_cache_note`
  — verifies the Gemini provider-note prose reaches the message.
- `test_make_diagnostic_batch_prewarm_below_min_omits_provider_clause_when_note_empty`
  — OpenAI / unknown providers produce empty notes; message must not
  render a stray `; ` separator.
- Added the new ID's sample context to the parametrized
  `test_every_id_round_trips_through_make_diagnostic` table.

**End-to-end emission tests (`test_cache_analysis_per_id_emission.py`):**
- `test_batch_prewarm_below_min_fires_when_prefix_truncated_below_provider_min`
  — the headline positive case.
- `test_batch_prewarm_below_min_silent_when_prefix_meets_provider_min`
- `test_batch_prewarm_below_min_silent_when_prewarm_not_declared`
- `test_batch_prewarm_below_min_silent_when_first_per_item_at_position_zero`
  — mutual exclusion vs `cache.prewarm-no-prefix`.
- `test_batch_prewarm_below_min_silent_when_declared_prompt_cache_present`
  — locks the `not row.declared_prompt_cache` guard discovered via
  baseline drift on `13-happy-path-interactions/01-batch-cache-prewarm-happy`.

**Round-trip test (`test_cache_analysis_per_id_coverage.py`):** added a
real-producer-path emission case for the new ID — drives `analyze()` on
a minimal workflow, asserts the diagnostic surfaces, JSON-round-trips
the result. Also added the new ID's sample to the parametrized samples
dict so `test_every_catalog_id_has_a_kwargs_sample` passes.

**Renderer tests (`test_cache_analysis_renderers.py`):**
- `test_batch_prewarm_recommended_discloses_wall_clock_tradeoff` —
  positive assertions on `wall-clock`, `Trade-off`, `Measure end-to-end
  duration`. Negative assertions lock out `implicit cache` and
  `cache_read_input_tokens` (the rejected Gemini caveat).
- `test_batch_prewarm_below_min_renders_prewarm_remediation_not_declared_cache`
  — positive on `Batch prewarm prefix below provider minimum`,
  `static prefix`, `${item.X}`, `Grow the static prefix`,
  `remove \`- prewarm: true\``; negative on `Increase cache content` and
  `remove \`prompt_cache:\`` (declared-cache vocabulary lockout).

### Baselines

- **New**: `04-warning-catalog/22-cache.batch-prewarm-below-min/` — minimal
  fixture mirroring the E3 experiment (Sonnet-4-5 + `prewarm: true` + ~5-
  token prompt prefix + 4-item static batch). README documents the
  mutation contract.
- **Regenerated**: `10-live-recordings/05-gemini-lyrics-generator/` —
  locks the Bug 17 wall-clock trade-off in the real lyrics-generator
  output. This is the canonical workflow this fix was motivated by.
- **Repaired**: `05-advisory-cases/03-prewarm-explicit-true-no-warning/`
  — the fixture README claimed "adequate static prefix" but the prompt
  was ~23 tokens, well below Sonnet's 1024. The new emission correctly
  fired here. Fixed the fixture to actually have an adequate prefix
  (added `${context}` input loaded from `_shared/long-stable-text.txt`)
  so the original "no warning when prewarm explicit + adequate prefix"
  contract holds. Test contract preserved: with adequate prefix, neither
  `cache.batch-prewarm-recommended` nor `cache.batch-prewarm-below-min`
  fires.
- **README**: surface-04 inventory updated to 23 cases, 20/23 trigger
  target ID; status table row updated to match.

### Verification

- Focused cache-analysis + CLI suite: 568 passed.
- Round-trip + per-id coverage tests: 7 passed.
- MCP analyze_cache tool tests (docstring contract): 11 passed.
- Full sandbox-safe suite (`-m "not e2e"`, excluding `uv`-spawning
  subprocess tests that panic before Python starts in this sandbox):
  **6,686 passed, 10 skipped, 43 deselected**.
- Baseline harness: 72 passed, 4 drifted — all 4 drifts confirmed
  pre-existing via `git stash` + rerun:
  `01-parser-errors/{01,06,08}` (TTL wording, ongoing) and
  `04-warning-catalog/12-cache.discrepancy` (uses `uv run python -` which
  the sandbox `uv` wrapper doesn't handle).
- `ruff check`, `ruff format --check`, `mypy src/pflow/core/cache_analysis/
  src/pflow/mcp_server/tools/` — clean on all 18 touched source files.

### Tacit knowledge

**The two-gate pattern in `_per_node_warnings`.** The outer `if
row.declared_prompt_cache:` block routes to `cache.below-min-tokens`; the
new `elif first > 0 and not row.declared_prompt_cache:` routes to
`cache.batch-prewarm-below-min`. The two paths are now symmetric in
shape and mutually exclusive on declared-cache presence. Future
prewarm/cache-tier diagnostics that want to distinguish "declared cache
agent" from "prewarm-only agent" can reuse the same gating predicate.

**`first_per_item_position` is the canonical boundary primitive.** Both
`cache.prewarm-no-prefix` and the new `cache.batch-prewarm-below-min`
read it. The unified `prompt_refs.classify_prompt_refs` helper covers
`- inputs:` dealiasing so the analyzer matches the runtime gate at
`nodes/llm/llm.py`. Three different prewarm-adjacent warnings now agree
on what "first per-item position" means.

**Adjacent threshold-gate asymmetry in `_batch_prewarm_recommendations`.**
Noted in plan review; not addressed in this PR. The function's
`uses_existing_prefix_evidence` branch (line 2594-2598) skips the
provider-min threshold check the prompt-walk branch enforces (line
2606). For a row with `cacheable_data_source == "batch_prefix"`,
`cacheable_tokens_estimated < min`, AND `prewarm not in node`, the
function would emit `cache.batch-prewarm-recommended` — recommending
prewarm for a prefix that would silently no-op. Narrow case (requires
batch_prefix evidence WITHOUT prewarm being declared, which the analyzer
sets when stable bytes exist regardless of prewarm). With Bug B in place
the same agent gets the new warning *after* they declare prewarm, but
catching it pre-declaration would be cleaner. Worth a small GH item.

**Rejected: Gemini-specific implicit-cache caveat.** First draft included
"On Gemini, the provider's implicit cache may already capture most
prefix savings without `prewarm: true`" as a third suggestion bullet.
Removed because catalog suggestions render unconditionally per
diagnostic ID — the bullet showed for Anthropic and OpenAI agents too,
where the prefix `On Gemini, ...` made it self-scoping but still noisy.
Stronger version would require per-row provider dispatch at emission
time, ideally with trace evidence showing the implicit cache is firing.
Negative-test assertions (`assert "implicit cache" not in text`,
`assert "cache_read_input_tokens" not in text`) lock the rejection in.

### What's next (still open)

- **Adjacent threshold-gate asymmetry** (above). File as a small GH item;
  fix shape is a one-line guard in `_batch_prewarm_recommendations`
  before line 2615.
- **Per-row trace-backed wall-clock estimate**. Deferred; would surface
  as `Trade-off: ... adds ~9.2s wall-clock per run (from trace)` when
  trace data is available. Requires `PerCallRow.duration_ms` (currently
  `duration_ms` lives only on trace LLM events). Second consumer for
  per-row latency would justify the plumbing.
- **Gemini implicit-cache caveat** (if wanted): needs per-row model
  dispatch + a `provider_specific_note` derivation in `make_diagnostic`.
  Probably best done alongside the trace-backed wall-clock number so the
  Gemini caveat can quote the agent's actual `cache_read_input_tokens`
  evidence instead of generic prose.

## 2026-05-13 — Task 159 Followups — parent prose in sub-workflow cache edits

Implemented parent-prose threading for sub-workflow cache recommendations.
When a parent `## Cache` chunk exactly matches the parent-side cache ref, the
suggested child `## Cache` block now renders the raw parent prose, including
blank lines before `${...}`; conflicting parent origins suppress prose.

Deviations: no prose is rendered for `${lyrics}` in the lyrics-generator
review cases because the parent has no `## Cache` chunk for
`write-lyrics.response`; the original 40-char preview idea was replaced because
the parsed parent prose includes newline separators that matter for byte shape.

Verification: raw `analyze-cache` output checked for agent-facing coherence;
focused cache tests 371 passed; analyzer/CLI/MCP suite 690 passed; affected
baselines regenerated and verified; near-full sandbox-safe suite 6,708 passed
after documented unrelated exclusions; `ruff`, format check, and focused mypy
clean.

## 2026-05-13 — Task 159 Followups — parent-prose preview correction

Same-day correction to the parent-prose work above. Code review revealed
the "render the raw parent prose, including line breaks" claim did not
survive the rendering pipeline: `_indent_message` in `render_text.py`
filtered out blank-indented lines via `if line.strip()`, so the parent's
`\n\n` chunk separators were silently stripped before reaching the user.
The renderer-side unit tests asserted blank-indented lines at the
`_format_exact_child_cache_edits` layer (intermediate output) and so
passed while the byte shape was lost end-to-end — a textbook Pitfall #19
case.

Two coupled fixes:

1. `render_text._indent_message` no longer filters whitespace-only lines.
   The function's job is to indent; filtering was an undocumented
   side-effect with one accidental beneficiary
   (`cache.prompt-cache-incomplete`'s template embeds `\n\n` between intro
   prose and findings — the catalog author's intent was being silently
   overridden). The grep for `lines.append("")` confirmed no other
   diagnostic body_block builder relies on the filter. The blank-line
   preservation in `cache.prompt-cache-incomplete`'s rendered output is
   a net UX improvement.
2. `analyze._exact_child_cache_block_content` rewritten to use the
   existing `_static_excerpt(prose, limit=40)` helper to render a
   single-line 40-char preview of parent prose above each `${...}` line,
   joined with `\n\n` between chunks. This matches the original plan
   (the deviation was retracted) and gives agents a scannable label per
   chunk without forcing them to read a 230-character paragraph per
   recommended entry. JSON still receives the full untruncated parent
   prose for machine consumers.

Combined rendered shape (lyrics-generator review-emotional-architecture):

```
       Add or extend ## Cache:
         ```cache
         The concept brief — material palette ta...

         ${concept_brief}

         The creative direction — genre choice w...

         ${creative_direction}

         ${lyrics}
         ```
```

40-char preview where the parent has a matching chunk by name; bare
`${var}` where it doesn't (e.g. `${lyrics}` — parent caches
`${write-lyrics.response}`, child renames to `lyrics`, no name match);
blank lines between chunks throughout. Mirrors the parent's visual
structure where it can, stays honest where it can't.

Test surgery:

- Dropped the 5 renderer tests that asserted against intermediate
  `_format_exact_child_cache_edits` output (Pitfall #19 — they passed
  while the end-to-end output failed). Replaced with one renderer-level
  unit test that locks `_indent_message`'s blank-line preservation
  (`test_indent_message_preserves_blank_lines`).
- Updated the per-id end-to-end test
  (`test_sub_workflow_cache_candidate_carries_parent_prose_from_matching_chunk`)
  to assert the truncated form, that the untruncated suffix does NOT
  appear, and that a blank line survives between prose and `${var}` via
  regex on the full rendered text. Mutation contracts in the test
  docstring cover both halves (truncation + blank preservation).
- Added an end-to-end assertion in
  `test_partial_prompt_cache_renderer_handles_many_affected_nodes`
  locking that the catalog template's `\n\n` between intro and findings
  block now reaches the user (mutation contract: restoring the
  blank-line filter collapses the regex match).
- `__init__.py` 4.2 docstring rewritten — replaced the inaccurate
  "render the exact parent prose, including line breaks" claim with
  the truthful "40-char single-line preview ... with blank lines
  between chunks to mirror the parent's visual structure. JSON
  consumers receive the full untruncated prose."

Baselines regenerated for both the text and JSON paths
(`10-live-recordings/05-gemini-lyrics-generator`,
`04-warning-catalog/05-cache.sub-workflow-cache-undeclared`,
`04-warning-catalog/05b-cache.sub-workflow-cache-undeclared-subpath`,
`12-real-world-lyrics-generator/{01,02,03}`). Baseline harness shows
3 pre-existing parser-error drifts only; everything cache-related is
clean.

Verification: focused cache suite 561 passed; broader
`tests/test_core/ tests/test_cli/` 3,270 passed with 1 unrelated
sandbox-only `uv run pflow` subprocess failure documented in earlier
progress logs; `ruff check`, `ruff format --check`, and focused `mypy
src/pflow/core/cache_analysis/` all clean.

## 2026-05-13 — Task 159 Followups — honest unmeasurable prompt-region tokenization

Implemented the F-04-style prompt-region tokenizer for analyzer cacheable
prompt slices. `token_estimation.tokenize_prompt_region(...)` resolves
`${...}` refs through `AnalysisContext`, serializes non-string simple-template
values deterministically, and returns `None` when any template bytes survive
resolution. The six raw prompt-slice tokenization sites in `analyze.py` now
route through it; `cache.batch-prewarm-below-min` and
`cache.batch-prewarm-recommended` suppress when required math is unmeasurable,
while `cache.dynamic-before-static` still emits when the stable suffix is
measurable and only display fields (`tokens_before_dynamic`,
`projected_ratio_pct`) are unknown.

Step 0 verification answers:

- Cross-workflow row projection is already honest-unmeasurable:
  `_estimate_parent_value_tokens` returns `None` before
  `_RowCrossWorkflowCandidate` construction, so `_apply_cross_workflow_projection`
  only sums concrete ints. No additional guard was needed.
- `cache.dynamic-before-static` did not allow null
  `projected_ratio_pct`; added `projected_ratio_pct` and
  `tokens_before_dynamic` to its nullable keys and render `?%` in suggestions.
- `TemplateResolver` resolves `${missing ?? fallback}` when `fallback` is
  present; helper coverage pins this behavior.
- `estimate_tokens("", text)` returns heuristic counts, including `0` for
  empty text; helper coverage pins empty-model rows.

Deviations / plan corrections:

- Moved `extract_unique_refs` and `build_shared_store_for_refs` into
  `token_estimation.py` as canonical helpers, imported back into `analyze.py`
  under the existing private names. This is simpler than lazy-importing
  `analyze.py` from `token_estimation.py` and avoids a reverse dependency.
- Did not invoke the planned `/code-review` checkpoint because no code-review
  skill is available in this Codex session. Substituted focused regression
  tests plus the baseline harness before full verification.
- The plan expected the lyrics-generator `curate-briefs` row to flip from
  `103 / 0%` to `? / ?%`. That row's measured prefix is literal text before
  the first per-item alias (`${concept_md}`), so the new unresolved-ref helper
  correctly has nothing to mark unmeasurable there. Forcing `?` would conflate
  this fix with the separate dynamic-before-static/interleaved-prefix problem.
- The live lyrics baseline instead dropped the `score-choruses`
  `cache.batch-prewarm-recommended` action. Its prefix contains unresolved
  upstream refs, so the old `~1061` prefix estimate was not honest enough for
  savings math. The row now shows the smaller parameter/cross-boundary
  projection (`41 / 0%`) but no prewarm recommendation.
- The 12-real-world lyrics-generator baselines did not drift after
  regeneration; only `10-live-recordings/05-gemini-lyrics-generator` changed.

Known limitations preserved:

- `input_tokens_estimated` still undercounts when prompt resolution is partial;
  fixing that requires widening the row/cost contracts to nullable input tokens.
- Existing sub-threshold `break` behavior in declared-cache
  dynamic-before-static scanning is unchanged; new unmeasurable suffixes use
  `continue` because they say nothing about later refs.
- `_find_batch_static_tail_after_dynamic` still returns after the first
  per-item ref, so an unmeasurable first tail can hide later opportunities.

Verification:

- New helper + CLI integration coverage added; focused cache-analysis suite:
  604 passed.
- Manual smoke checks: bug-16 indirection and 6-field variants now report
  `cacheable_tokens_estimated: null`; E3 below-min still emits
  `cache.batch-prewarm-below-min`; E2 interleaved is honest (`null`) rather
  than a fabricated 100% ratio.
- Baseline harness verified regenerated/adjacent cases:
  `10-live-recordings/05-gemini-lyrics-generator`,
  `12-real-world-lyrics-generator/{01,02,03}`,
  `04-warning-catalog/{06,07,13,22}`.
- Quality: `ruff check`, `ruff format --check`, and
  `mypy src/pflow/core/cache_analysis/` clean.
- Broad sandbox-safe run passed after excluding known `/opt/homebrew/bin/uv`
  panic tests plus four unrelated runtime/sub-workflow failures that reproduce
  independently: 6,719 passed, 19 skipped. The non-excluded first broad run
  showed those same unrelated failures before exclusion.

## 2026-05-13 — Task 159 Followups — adaptive per-call columns + note de-dup

Implemented adaptive text-only per-call table rendering in
`render_text.py`. Per-call columns are now name-based constants instead of
three synchronized hardcoded 8-column lists, and the renderer computes the
visible column set from the post-filter rows. Static/no-trace reports hide
placeholder-only columns (`cached_now`, `ratio`, `calls`, and sometimes
`could_cache`); trace-backed reports keep the established full column shape.

Row notes now stay as structured components until render time. Repeated
`no trace recorded — run with --report to populate this row` components are
removed from individual rows and summarized under a `Per-call notes:` footer,
while unique components remain inline. This preserves the mixed case where one
row has the repeated no-trace component plus a unique warning marker.

Deviations / plan corrections:

- Refined the raw visibility predicate after baseline inspection. The plan
  simultaneously said trace/truncated-trace output should stay unchanged and
  supplied a purely column-value predicate that would hide `could_cache` from
  trace-only tables. Preserved the stronger user-facing invariant: trace modes
  keep all columns; adaptive hiding is static-mode-only.
- Static `could_cache` remains visible for declared-cache rows with a resolved
  stable model, because the steady-state baseline needs `?` to explain that
  cacheable bytes are not statically projectable. It hides for unresolved or
  heterogeneous-model static rows, which is what removes the dead column from
  the lyrics-generator cold-reader case.
- Restored `15-run-flag-interactions/03-report-with-only` after full baseline
  regeneration because the sandbox rewrote it with the known `/dev/fd`
  process-substitution failure. That drift is unrelated to cache rendering and
  should not be committed as expected output.

Verification:

- Focused renderer suite: 173 passed.
- Focused cache-analysis + CLI suite: 699 passed.
- Broad sandbox-safe core/CLI sweep with documented `uv`-spawning exclusions:
  3,254 passed, 41 deselected.
- Baseline harness regenerated 76 cases with a temporary sandbox `uv run`
  wrapper. Verification after restoring the unrelated `/dev/fd` case: 75
  passed, 1 known sandbox drift (`15-run-flag-interactions/03-report-with-only`).
- `ruff check`, `ruff format --check`, and `mypy src/pflow/core/cache_analysis/`
  clean.

## 2026-05-13 — Task 159 Followups — lower-bound batch-prewarm advisory

Implemented `cache.batch-prewarm-lower-bound-recommended`. The analyzer now has
`tokenize_prompt_region_lower_bound(...)`, which resolves what it can, strips
unresolved `${...}` placeholders, and returns `(measurable_tokens,
unresolved_refs)`. `_batch_prewarm_recommendations` keeps the confident path
exact-only, then emits the lower-bound advisory only when the measurable prefix
alone clears the provider minimum and unresolved refs remain.

Key points:

- Added catalog/rendering/action projection support for
  `savings_lower_bound_usd` with "savings at least ..." wording and explicit
  `--report` verification guidance before adding `prewarm: true`. This is the
  Bug 17 wall-clock safety valve: unresolved refs may be stable, but prewarm
  still serializes the first item.
- Normalized `unresolved_refs` to a JSON list in diagnostic context while the
  tokenizer returns a tuple. Reason: `Diagnostic.to_dict()` round-trip tests
  require JSON-stable payloads; leaving a tuple in context serializes back as a
  list and breaks the machine contract.
- Kept site 4/site 5/cross-workflow paths exact-only. Those are load-bearing
  measurement paths, not advisory ranking paths; lower-bound advice there would
  mix "what can be safely measured" with "what might be worth trying."

Plan deviations with reasons:

- Did not restore the live lyrics-generator `score-choruses` action. Current
  code measures its lower bound at ~1,002 tokens, while
  `gemini/gemini-2.5-flash` uses the explicit cachedContents minimum of 4,096
  tokens. Emitting the advisory would contradict the provider-minimum gate and
  overstate the opportunity. `10-live-recordings/05-gemini-lyrics-generator`
  therefore remains byte-identical and was verified, not regenerated.
- Did not update the existing inputs-indirection test to expect the new ID.
  That fixture's prefix is exactly measurable; only the dynamic tail is
  unresolved. The plan's own branch says `prefix_tokens is not None` and
  `dynamic_tokens is None` should preserve the current short-circuit.
- Added a new `04-warning-catalog/23-cache.batch-prewarm-lower-bound-recommended`
  baseline instead of changing the lyrics baseline, so the new ID has
  end-to-end JSON coverage without fabricating the real-world canary.

Verification:

- Focused cache-analysis/CLI/per-ID suite: 631 passed.
- `04-warning-catalog` baseline surface regenerated and verified with sandbox
  `uv run` wrapper: 24 passed, 0 drifted; live lyrics case 05 verified clean.
- Manual smoke: E3 still emits `cache.batch-prewarm-below-min`; bug-16
  indirection still reports `cacheable_tokens_estimated: null` and no fabricated
  confident prewarm action.
- Broad sandbox-safe suite passed after excluding the documented Homebrew-`uv`
  subprocess panics plus four same-class subprocess tests:
  6,750 passed, 19 skipped.
- `ruff check`, `ruff format --check`, and `mypy src/pflow/core/cache_analysis/`
  clean.

## 2026-05-13 — Task 159 Followups — conditional shared-context advisory below provider minimum

Implemented `cache.shared-context-undeclared-conditional` for greenfield shared
`## Inputs` refs whose current resolved values are below provider cache
minimums. The confident `cache.shared-context-undeclared` path remains reserved
for paste-ready edits; below-threshold cases now emit a structured conditional
recommendation with no suggested block and no old "paste-ready" note.

Key points:

- Refactored suggested-block gating into explicit actionability states:
  actionable, below-threshold, evidence-incomplete, insufficient-nodes.
  Below-threshold dispatches to the new catalog ID; incomplete evidence keeps a
  plain note because the analyzer cannot know whether caching would fire.
- Added row-level `below provider min (need ≥N for this model)` notes for
  undeclared projected cacheable rows from `parameters`, `memo`, `batch_prefix`,
  and `cross_workflow_projection`; declared-cache rows stay owned by
  `cache.below-min-tokens`.
- Updated the per-call explainer so small `could_cache` numbers are not read as
  provider-cacheable unless they clear the model minimum.
- Added MCP docstring/catalog/sample coverage, production emission tests,
  renderer note tests, and baseline updates. The confident
  `04-warning-catalog/04-cache.shared-context-undeclared` baseline stayed
  byte-identical.

Deviations / learnings:

- Used the maximum provider minimum across consumer nodes for the conditional
  precondition. The plan text said "strictest consumer" but one code snippet
  used `min(...)`; using the lower threshold would understate mixed-model
  requirements and tell agents a cache edit can work before every consumer can
  actually write/read the provider cache.
- Current `anthropic/claude-haiku-4-5` resolves to a 4,096-token minimum in
  `llm_capabilities`, not the plan's 2,048-token example. Baselines and tests
  follow the live capability table rather than the stale example.
- Did not add the planned production-shaped "fewer than two nodes" note test.
  `_populate_suggested_blocks` only reaches actionability classification after
  `_collect_llm_template_references` finds refs used by at least two LLM nodes,
  so that state is defensive but unreachable through `analyze(...)` today.
  Added a single-node silence test instead to document the real integration
  boundary.

Verification:

- Focused cache-analysis/MCP suite: 580 passed.
- Full cache-analysis glob + analyze-cache CLI/MCP tests: 738 passed.
- Manual smoke: `article=hello` emits the conditional recommendation and row
  below-min notes; long `article` still emits the confident suggested block.
- Baseline harness with sandbox `uv run` wrapper: 77 passed, 1 known unrelated
  sandbox drift (`15-run-flag-interactions/03-report-with-only` `/dev/fd`).
- Near-full sandbox-safe suite: first run hit 4 additional Homebrew-`uv`
  subprocess panics before Python; rerun excluding those same-class sandbox
  tests plus documented exclusions passed: 6,760 passed, 19 skipped.
- `ruff check`, `ruff format --check`, and `mypy src/pflow/core/cache_analysis/
  src/pflow/mcp_server/tools/` clean.

## 2026-05-13 — Task 159 Followups — conditional advisory wording polish

Fixed the review-found agent-UX leaks in
`cache.shared-context-undeclared-conditional`:

- The representative-input example now uses the actual first shared chunk
  (`article=@./real-input.md`) instead of the abstract `<name>` placeholder.
- The threshold message now says "highest minimum across these nodes" instead
  of "strictest consumer".
- The conditional edit suggestion now says `declare `article` in ## Cache`
  via `shared_chunks_short`, avoiding awkward singular/plural "shared refs"
  wording.

Added `shared_chunks_first` as a catalog-format alias next to
`shared_chunks_csv` / `shared_chunks_short`, and extended the production-shaped
emission test with negative assertions for `<name>`, `strictest consumer`, and
`declare the shared refs`.

Verification: affected baselines regenerated and verified
(`03-analyze-cache-modes`: 8 passed; catalog case
`24-cache.shared-context-undeclared-conditional`: 1 passed); focused
cache-analysis/MCP subset: 413 passed; `ruff check`, `ruff format --check`,
and `mypy src/pflow/core/cache_analysis/ src/pflow/mcp_server/tools/` clean.

## 2026-05-13 — Task 159 Followups — Bug 1 + Bug 10: trace selection policy + transparency

Three coordinated changes to make `pflow analyze-cache` honest about which
trace it loaded, and to stop newer failed traces from shadowing older
successful ones.

### Problem statement

Two named agent-UX gaps in `_autoload_trace`:

- **Bug 10**: `_autoload_trace` (`analyze.py:950-1000`) picked the first
  healthy 2.x trace by filename-timestamp sort. It never inspected
  `trace["final_status"]`. An agent iterating (edit → run → fail → fix →
  re-run) had a newer failed run silently shadow an older success.
- **Bug 1**: auto-load decisions were invisible to text consumers.
  `analysis.trace_path` was JSON-only; `render_text.py` had no `Trace:`
  header line. When the post-row-build rejection gate fired
  (`analyze.py:683-700`) the Notes line said only "Auto-loaded trace did
  not cover all root LLM nodes; ignored for workflow-wide cache
  analysis." — no filename, no `final_status`.

### Architectural reasoning

The earlier "delete whole-trace drift gate" decision rejected walking back
to older traces on the principle that "older traces are monotonically more
drifted." That principle holds for *workflow source drift* (older nodes,
older prompts) and is exactly what the per-row `did_not_execute_in_trace`
gate already handles. **Bug 10 is on a different axis: run outcome.** A
newer failed run from the same workflow source is not "less drifted" than
an older successful run — they share structure, only run-outcome differs.

The fix collects all healthy 2.x candidates into success/failed buckets,
prefers success-or-degraded over failed, and within a tier picks
newest-by-filename. Absent `final_status` routes to success — mirrors the
existing `_trace_coverage_for_rows` fallback so legacy 2.1.0 traces and
synthetic test fixtures keep working unchanged. Per-row safety net still
fires if the chosen older success doesn't structurally match the current
IR; the rejection note now names the file.

Considered and rejected alternatives:

- **Hybrid γ (prefer success only when newest failure is "unusable")** —
  adds a third state ("usable failed" vs "unusable failed") for marginal
  additional safety. The per-row safety net already handles the case
  cleanly; the hybrid adds complexity without clear yield.
- **Bounded walk-back (Hybrid δ, time-windowed preference)** — arbitrary
  cutoff codifying "session" semantics nowhere else in pflow.
- **Walk-back through `did_not_execute_in_trace` rejection** — same case
  the prior decision explicitly rejected. Fix C just names the file.

### Implementation

**Production (`src/pflow/core/cache_analysis/`):**

1. `_autoload_trace` (analyze.py:984): two-pass collect-then-rank.
   `_collect_candidate_traces` extracted to keep C901 happy. Emits one
   of three Notes: "Skipped newer trace … (failed) in favor of … (success)"
   when ranking caused a non-newest pick, "Auto-loaded `…` (failed); no
   successful trace exists" when only failed traces match, or the existing
   rename-detection note for zero matches.
2. `AnalysisSummary` (analyze.py:546-555): two additive nullable fields,
   `trace_final_status` and `trace_recorded_at`. Populated in
   `_build_summary` from `trace_data["final_status"] or "success"` and
   `trace_data["start_time"]`. Mirrors the back-compat fallback at
   `_trace_coverage_for_rows`.
3. `render_text.py`: new `_format_trace_header_line` helper emits
   `  Trace: <filename> (<status>, recorded <YYYY-MM-DD HH:MM>)` whenever
   `analysis.trace_path is not None`. Drops the "recorded …" suffix when
   `start_time` is missing (defensive for pre-2.1 traces).
   `_format_recorded_timestamp` does ISO → `YYYY-MM-DD HH:MM` conversion
   with graceful fallback to None on any parse failure.
4. Rejection gate at `analyze.py:716-720` now delegates to a new
   `_format_rejection_note(used_trace_path, trace_data)` helper that
   includes the rejected filename + final_status. C901 decomposition.
5. `render_json.py`: additive `trace_final_status` and `trace_recorded_at`
   fields next to `trace_coverage`. No JSON major version bump (additive
   minor change).

**Tests (5 new in `test_cache_analysis_analyze.py`, 4 new in
`test_cache_analysis_renderers.py`, 1 updated):**

- `test_autoload_prefers_success_over_newer_failed` — Bug 10 canonical
  case with mutation contract.
- `test_autoload_uses_newest_when_all_successful` — same-tier ranking
  preserved.
- `test_autoload_uses_newest_failed_when_no_success_exists` — failed
  fallback disclosure.
- `test_autoload_treats_degraded_as_preferable_over_failed` —
  `final_status="degraded"` ranks with success.
- `test_autoload_treats_absent_final_status_as_success_for_backcompat`
  — mutation contract on the `or "success"` fallback (removing it
  regresses legacy 2.1.0 traces).
- `test_autoload_ignores_misaligned_trace_with_no_root_llm_activity`
  updated for the new rejection-note wording (filename + status).
- `test_text_render_shows_trace_header_line_when_loaded` — header line
  positive case.
- `test_text_render_omits_trace_header_when_no_trace_loaded` —
  greenfield negative case.
- `test_text_render_trace_header_drops_recorded_suffix_when_timestamp_missing`
  — legacy-trace defensive path.
- `test_text_render_trace_header_shows_failed_status_honestly` —
  failed-trace transparency.

The `_make_analysis` renderer helper grew `trace_path` /
`trace_final_status` / `trace_recorded_at` kwargs. Defaults use an
`Ellipsis` sentinel so tests can explicitly pass `None` for the
"legacy-trace missing start_time" case while still letting cost-branch
tests auto-populate the fields. Shape-parity test passes after migration.

`_write_trace` helper in `test_cache_analysis_analyze.py` grew
optional `final_status`, `failed_node_ids`, `start_time`, `timestamp`
kwargs. All default to absent, preserving back-compat with existing
autoload tests.

### Baselines

39 existing baselines regenerated + 3 new baselines added. Existing drifts
split between:

- Text outputs gaining the `Trace:` header line:
  `03-analyze-cache-modes/05`, `04-warning-catalog/12`,
  `10-live-recordings/03`, `10-live-recordings/05`,
  `15-run-flag-interactions/01`.
- JSON outputs gaining the two additive nullable fields
  (`trace_final_status`, `trace_recorded_at`): every JSON case that
  produces a `summary` block.

**Gap caught in post-implementation review and fixed.** Initial sweep
showed only the universal `Trace:` line in baselines — none of the existing
baselines exercised the multi-trace autoload selection path or the
post-row-build rejection-naming path. Every `analyze-cache` baseline uses
either `--from-trace` (bypasses autoload) or `--no-trace-autoload` (opts
out). The new Notes wording for Bug 10 (success-preference) and Bug 1
(rejection-naming) was unit-tested but not cold-reader-visible. Three new
baselines added to lock the agent-visible output:

- `03-analyze-cache-modes/07-autoload-prefers-success` — seeds older
  success + newer failed traces; locks `Skipped newer trace
  workflow-trace-…-163000.json (failed run) in favor of
  workflow-trace-…-153200.json (success). Pass --from-trace <path> to
  override.`
- `03-analyze-cache-modes/08-autoload-failed-only` — seeds only a failed
  trace; locks `Auto-loaded workflow-trace-…-163000.json (failed run); no
  successful trace exists for this workflow. Trace-dependent
  recommendations may be suppressed. Re-run the workflow to record a
  successful trace, or pass --from-trace <path> to use a specific trace.`
- `03-analyze-cache-modes/09-autoload-rejected-names-file` — seeds a
  trace whose root LLM events don't match the current IR (simulates
  post-edit workflow drift); locks `Auto-loaded trace
  workflow-trace-…-153200.json (success) did not cover all root LLM
  nodes (some root LLM nodes have no matching events — workflow may have
  been edited since the trace was recorded). Ignored for workflow-wide
  cache analysis. Pass --from-trace <path> to inspect a specific trace
  anyway.`

Each baseline's seed script computes the autoload-required
`hashlib.md5(workflow_path)[:8]` prefix so the synthetic traces match the
glob pattern at `_autoload_trace`. README in each baseline documents the
mutation contract so future regressions are caught loudly.

Cold-reader spot-check on the canonical lyrics-generator baseline
(`10-live-recordings/05-gemini-lyrics-generator`): the new line
`Trace: live-gemini-lyrics-generator.trace.json (success, recorded
2026-05-08 22:01)` reads cleanly with filename, run outcome, and recording
timestamp visible to a fresh agent without inspecting JSON. The failed-trace
baseline (`15-run-flag-interactions/01-partial-trace-analyze-cache`) shows
`Trace: partial-trace.json (failed, recorded 2026-05-08 21:51)` — the agent
immediately learns both that a trace was loaded AND that it captured a
failed run.

### Verification

- Focused cache-analysis + CLI suite: 736 passed.
- Mutation contracts on `test_autoload_prefers_success_over_newer_failed`
  and `test_autoload_treats_absent_final_status_as_success_for_backcompat`
  verified via `git stash` of `analyze.py`: both fail when production
  change is reverted.
- Broad sandbox-safe core/CLI sweep: 3,291 passed, 41 deselected.
- Baseline harness: 79 passed, 0 drifted (post-regen).
- `ruff check`, `ruff format --check`, `mypy
  src/pflow/core/cache_analysis/` clean on touched files.

### Tacit knowledge

**The `_BUILDER_DOCUMENTED_DEFAULTS` shape-parity test in
`test_cache_analysis_renderers.py` is load-bearing for additive
`AnalysisSummary` fields.** It fails noisily when a field is added without
populating it in `_make_analysis`. For trace-related fields specifically,
the natural pattern is conditional on `actually_paid is not None` (the
test helper's "a trace contributed evidence" signal) — but tests that need
to override the auto-fill (e.g., the legacy-trace defensive path) must use
the `Ellipsis` sentinel pattern. Future trace-related summary fields
should follow this convention rather than introducing a third pattern.

**The C901 threshold (10) hit both `analyze()` (which I didn't decompose
during the previous TTL-attribution deletion sweep, so 10→11 was the
last straw) and the rewritten `_autoload_trace`.** Both decomposed
cleanly into named helpers (`_format_rejection_note`,
`_collect_candidate_traces`) rather than adding `# noqa: C901`
suppressions. The decomposition shape matches the orchestrator+helper
pattern used by the other complex functions in `analyze.py`.

**`workflow_trace.py`'s `start_time` field is `datetime.now().isoformat()`
— microsecond-precision (`2026-05-11T15:32:28.123456`).** The renderer
strips microseconds via `time_part[:5]` (minute precision) for readability;
JSON keeps the raw ISO string for machine consumers. If a future
trace-format change drops microseconds or adds timezone, the slice-by-5
approach still works (the ISO format is positional).

### What's next (still open)

- **`--list-traces` CLI flag (F2)** — feature request; not first-contact
  UX harm. Would synergize with the new `Trace:` line ("here are the
  alternatives if you don't like this pick").
- **CLAUDE.md staleness re `_trace_aligns_with_ir`** — confirmed stale
  reference at `cache_analysis/CLAUDE.md:59` and in `runtime/CLAUDE.md`.
  The function was deleted in the earlier Bug 1 / drift-gate fix; the
  docs reference outlived the code. Task 160 sweep territory.
- **Validation-failure trace saving (Agent-UX 6)** — different
  subsystem (`cli/commands/run.py`); validation failures save no trace,
  so the new rank-aware autoload has no candidate to find. Not
  addressed here.
- **Provider-cache TTL detection from trace timestamps** — separate
  feature; needs new catalog ID per DD#29.

## 2026-05-13 — Task 159 Followups — split mixed sub-workflow cacheability recommendations

Fixed the lyrics-generator cold-reader failure where one `chorus-chooser`
recommendation said `~8,504 tokens per call` was "below the smallest provider
cache minimum (1,024)". The group mixed two consumer cases: `select-chorus`
could cache four values above Gemini's 4,096-token minimum, while
`score-choruses` only used `concept.core_idea` (~41 tokens), below every
provider tier. The renderer had to pick one representative token count for the
whole child workflow, which made the text logically impossible.

Implementation follows option 1 from triage: split mixed child-workflow
recommendations by per-consumer cacheability case before diagnostics are
created. Same-case groups still render as one child-scoped action. Mixed
groups now produce separate recommendations, each with:

- only the consumer nodes in that case in `prompt_cache:` edits,
- only the cache refs those consumers use,
- its own coherent provider-minimum story,
- actionable savings only for the `actionable` split.

The live lyrics-generator baseline now has two `chorus-chooser` actions:

- actionable `select-chorus`: four entries, `~8,504` tokens, above Gemini's
  4,096-token minimum, saves `~$0.0092/run`;
- below-min `score-choruses`: one entry, `concept.core_idea ~41` tokens,
  below the 1,024-token minimum.

Tradeoff accepted: a cache ref shared across cases can appear in both
recommendations. That is preferable to one incoherent recommendation because
each action is locally truthful and `Add or extend ## Cache` remains the edit
shape. A future UX pass could collapse duplicate cache-block lines across
split actions, but that is polish; the first-contact correctness bug is fixed.

Verification:

- Focused split + sibling tests: 4 passed.
- All `cache.sub-workflow-cache-undeclared` emission tests: 27 passed.
- Renderer + per-id emission suites: 331 passed.
- Cache-analysis + analyze-cache CLI suite: 737 passed.
- Baselines verified clean with the sandbox `uv run` wrapper:
  `10-live-recordings/05-gemini-lyrics-generator`,
  `04-warning-catalog/05-cache.sub-workflow-cache-undeclared`,
  `04-warning-catalog/05b-cache.sub-workflow-cache-undeclared-subpath`, and
  all `12-real-world-lyrics-generator` cases.
- `ruff check`, `ruff format --check`, and focused
  `mypy src/pflow/core/cache_analysis/` clean.
