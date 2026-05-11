# Task 159 Cache Analyzer — Post-Merge Polish Plan

> **Audience**: A fresh agent picking up Task 159 polish work after the merge-block batch landed. You should be able to start implementation immediately from this document without reading the audit, the progress log, or talking to anyone first.
>
> **Supersedes**: `BASELINE-AUDIT.md` (now deprecated). That document is the historical record of how we got here; this document is the forward plan (do not read this document, unless targeting a specific section)
>
> **Written**: 2026-05-09 by triage agent, after a fresh-eyes review of the post-merge-block analyzer output and parallel source-grounded investigation.

---

## TL;DR

Task 159 (prompt caching) is feature-complete and merge-block bugs are shipped. The output of `pflow analyze-cache` on real workflows still has visible UX friction that a fresh AI agent would trip over. This document catalogs that friction with source-grounded fix complexity, organized into 5 PRs (~400 LOC total) that can land independently.

**If you have time for one PR**: ship Cluster A (cross-workflow rename grouping). Single biggest visible improvement.

**If you have time for two**: A + B (cost-savings honesty). Removes the most confusing contradictory output in the analyzer.

**Highest agent-action impact**: Cluster C (recommendation impact projection) — gets agents to actually fix the right caching opportunity instead of skimming past.

---

## How this document is organized

1. **State of the world** — what's been shipped, what the analyzer output currently looks like
2. **The fresh-eyes ground truth** — actual lyrics-generator capture annotated with friction points
3. **Primary fix queue (5 clusters)** — each with: WHAT, EVIDENCE, ROOT CAUSE, FIX SHAPE, COMPLEXITY, DEPENDENCIES
4. **Pre-flight verifications** — load-bearing assumptions to confirm before specific PRs
5. **Secondary backlog** — high-value items from the old audit not in the primary queue
6. **What NOT to fix** — explicit no-go list with reasoning
7. **File map + verification confidence** — what to know, what we're sure about

For every claim about code, file:line is cited. Where I write "verified" it means a parallel `pflow-codebase-searcher` agent confirmed the claim by reading source. Where I write "assumed" or "inferred" you should verify before acting.

---

## State of the world (2026-05-09)

### What shipped pre-merge

The merge-block batch closed 8 code bugs and most of a polish round. Quick reference:

| Cluster | Findings closed |
|---|---|
| Trace-mode evidence regression | L-1, L-2, L-3 (Option B), L-9 (dupe), L-10, L-11, L-12, A-3, B-18 |
| Tier-1 quick wins | A-1, A-6, B-12 + B-13, B-17 |
| Bonus polish round | B-5, B-6, B-7, B-8, B-9 (split blocking errors), B-11, B-20, L-4, L-7 |
| GH-filed for v1.x | C-1 (#381), L-8 (#382) |
| Removed as noise during triage | A-4 (later reactivated — see Cluster E), L-9 (pure dupe of A-1) |

The architectural defect L-10 (trace mode hiding static findings) is GONE. Lyrics-generator case 05 now correctly shows 19 opportunities through trace mode. Per-call model rendering uses observed-from-trace.

### What the analyzer output currently looks like

The canonical real-world test capture lives at:
`.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`

This is a $2.31, 9:40 wall-clock, 253-LLM-call run of the lyrics-generator workflow against Gemini. It exercises every analyzer code path agents will hit on real workflows: 25 LLM nodes across 15 sub-workflows, 3 levels of nesting, dynamic batches, heterogeneous models, conditional dispatch, opaque prompts.

Read this file before starting any PR. It's the ground truth.

### Test infrastructure

- 6,415 tests passing on default suite (`make test`).
- 65 baseline cases under `.taskmaster/tasks/task_159/baseline/` — `verify.sh` re-runs each case and diffs against `expected-stdout.txt`. After any fix, run `regenerate.sh` for affected cases, eyeball the diff, commit.
- Each fix below estimates baseline drift count.

---

## Fresh-eyes ground truth — the actual output, annotated

Here's what an agent reads when running `pflow analyze-cache --from-trace` on lyrics-generator. Annotations call out each friction point:

```
# Cache Analysis: <REPO_ROOT>/.../lyrics-generator.pflow.md

  Workflow: 25 LLM nodes, invocation count unavailable (3 dynamic batch nodes)
            using 3 models: A, B, C; plus generate-chorus-options (...)        ← N-3: 39-word run-on
  Evidence: complete trace (18 of 25 LLM nodes executed; 7 not reached ...)
  Observed models: A, B, C                                                     ← N-2: same list as line 3
  (2 in lyrics-generator.pflow.md, 23 in 15 sub-workflows: <15 names>)         ← N-9: enumeration filler

## Summary

  Actually paid (trace):       ~$2.31 (trace)                                  ← N-1: numbers say I saved ~$0.22
  Cost without caching (projected subset):        ~$2.53 (partial)             ←      but the "Actual savings"
  Cost on rerun (within TTL, projected subset):  ~$2.45 (partial)              ←      line below says "unavailable"
  Actual savings (this run):    unavailable (projection excludes ...)          ← N-1: contradictory headline
  Rerun delta (projected):      saves ~$0.09/run on rerun, 3% of baseline      ← N-4: baseline of WHAT?

  19 opportunities (0 warnings, 19 info)                                       ← A-4: no section has 19 entries

## Other blocking errors (surfaced for awareness)                              ← N-10: "Other" than what?
  ...

## Recommended actions
  1. Sub-workflow cache undeclared — add `concept` ...                         ← N-7: "savings unavailable" —
     ...                                                                        the BIGGEST cache opportunity
                                                                                in the workflow (21.5M tokens
                                                                                across 136 calls) and we don't
                                                                                quantify it
  2. Prompt opaque to static analysis on generate-chorus-options ...

## Sub-workflow boundaries                                                     ← B-2 + N-8: 75 lines of
  1. Cross-workflow rename — `creative-direction.response` ↔ ...                repetition; same logical
     song-creator → chorus-chooser  (line 97)                                   rename appears 7× across
     <REPO_ROOT>/.../song-creator.pflow.md → <REPO_ROOT>/.../...                7 different children
  ... 16 more entries, 4 lines each, paths repeated twice per entry ...

## Per-call cache report
  Showing 14 of 25 LLM nodes; all-clean rows hidden ...

### chorus-chooser.pflow.md (called by choose-chorus)
  generate-chorus-options ... model=<varies> ...                               ← N-6: (×N) vs calls=N
                                tokens=? cacheable=? src=high ... opaque-prompt   meaning unclear
  score-choruses          ... tokens=158,704 cacheable=? ratio=?% src=high    ← N-5: src=high but cacheable=?
                                                                  calls=136     reads contradictory
                                                                              ← L-6: no output token column
  ...                                                                         ← C-5: src= vocabulary
                                                                                unexplained

## Per-child analyze-cache commands                                            ← B-3: 15 absolute paths
    pflow analyze-cache <REPO_ROOT>/.../child1.pflow.md                          ~200 chars each
    pflow analyze-cache <REPO_ROOT>/.../child2.pflow.md
    ... 13 more ...

## Notes
  · Workflow batch fetch-sources ... uses items: ${sources}; sub-workflow ...  ← B-4: 3 near-identical
  · Workflow batch analyze-sources ... uses items: ...                          batch notes
  · Workflow batch create-songs ... uses items: ...
  · Discrepancy detection: predicted-key matching unavailable (memo ...)
  · Discrepancy detection: skipped attribution for 117 trace event(s) ...      ← L-5: coverage statement
                                                                                buried in Notes
```

12 distinct friction points in one capture. Some are duplicates (model list), some are correctness (savings contradiction), some are organization (count mismatch). What follows is the source-grounded fix plan.

---

## Primary fix queue

Five clusters. Each has its own PR. They don't depend on each other except where noted.

---

### Cluster A — Cross-workflow rename grouping (B-2 + N-8)

**Single biggest visible improvement to a fresh agent.** The 75-line wall of cross-workflow rename findings collapses to ~10 grouped entries.

#### Findings

**B-2** — Density disaster. The `## Sub-workflow boundaries` section is 17 entries × 4 lines each = 68 lines. Each entry has the parent and child absolute paths repeated TWICE. After entry 4 agents stop reading.

**N-8** — Source-side dedup missing. The same logical rename (`creative-direction.response ↔ creative_direction`) appears 7 times for 7 different children. As an agent: "fix the source name once" not "you have 7 identical issues."

#### Evidence

Lyrics-generator case 05, lines 40-114. Same pattern in case 12-01. See annotated output above.

#### Root cause (verified)

`src/pflow/core/cache_analysis/cross_workflow.py:38-64` defines `CrossWorkflowEdge` — one edge per `(parent invocation site, input key)`. Walker emits one edge per input mapping at `cross_workflow.py:331-344`. Equal-tail rename pairs from the same parent into N children produce N edges.

`src/pflow/core/cache_analysis/analyze.py:3063-3092` `_build_cross_workflow_findings` emits one Diagnostic per edge.

`src/pflow/core/cache_analysis/render_text.py:893-987` `_render_cross_workflow` + `_format_boundary_finding` renders 4 lines per Diagnostic with paths in BOTH the scope line AND the body message.

**Critical insight**: every Diagnostic context already carries `parent_workflow + child_workflow + line_in_parent + parent_value_expr + child_input_name` (`analyze.py:3085-3090`). The data is already groupable both ways. No analyzer changes needed.

#### Fix shape

**Renderer-only, two-pass grouping in `_render_cross_workflow`:**

1. **First pass**: group rename diagnostics by `(parent_workflow, parent_value_expr, child_input_name)` — collapses 7 identical renames into 1 logical entry with a children list.
2. **Second pass**: group by `(parent_workflow, child_workflow, line_in_parent)` — collapses multiple distinct renames at the same call-site into one boundary header.

**Order matters**: source-dedup first, then boundary grouping. Reverse order keeps the 7 different `(child, line)` pairs visible and defeats N-8.

Output shape becomes:

```
## Sub-workflow boundaries

  song-creator → chorus-chooser  (line 97):
      `creative-direction.response` → `creative_direction`
      `song-architecture.response`  → `architecture`
      `concept_brief`               → `creative_brief`

  song-creator → 6 reviews  (line 124, 239):
      `creative-direction.response` → `creative_direction`  in: review-emotional-architecture, review-ai-tells, review-cliche, review-genre, review-accuracy, review-rhyme
      `write-lyrics.response`       → `lyrics`              in: review-emotional-architecture, review-narrative, review-imagery, review-stranger-summary
      `song-architecture.response`  → `song_architecture`   in: review-narrative, review-imagery, review-genre, review-rhyme
```

**Catalog and JSON unchanged**. The diagnostics list keeps the per-call-site shape; renderer aggregates at display time. `render_json.py::_cross_workflow_to_dict` (`render_json.py:262-291`) is untouched.

#### Complexity

| Metric | Value |
|---|---|
| LOC | ~50 in `render_text.py` |
| Files touched | 1 (`render_text.py`) |
| Catalog changes | None |
| JSON shape changes | None |
| Existing tests broken | 0 |
| New tests needed | 1 multi-child fixture (verifies dedup) + 1 multi-rename-per-line fixture (verifies grouping) |
| Baselines drift | ~5 (lyrics-generator case 05, case 12-01, plus a few smaller) |

#### Composition

Independent of all other clusters. Land alone or in any order.

---

### Cluster B — Cost-savings honesty (N-1 + N-4)

Removes the most contradictory output in the analyzer. Headline numbers become trustworthy.

#### Findings

**N-1** — `Actual savings (this run): unavailable` while two adjacent lines display the numbers needed to compute it. The lyrics-generator capture says paid $2.31 + no-cache $2.53 → "savings unavailable." Reads as analyzer is broken.

**N-4** — `3% of baseline` doesn't say WHICH baseline ($2.53 no-cache vs $2.31 paid).

#### Evidence

Lyrics-generator case 05, lines 10-14.

#### Root cause (verified)

**N-1**: `src/pflow/core/cache_analysis/analyze.py:4002-4007` short-circuits `actual_vs_no_cache_delta` to "unavailable" whenever `projection_exclusions` is non-empty. The cohort-comparability invariant is over-conservative. `ProjectionExclusion.actual_cost_usd` (set at `cost_estimation.py:339, 415, 425, 440`) already carries each excluded row's trace-recorded cost — it was added precisely to enable subset arithmetic and is currently unused for this case.

The math `actually_paid_subset = total_paid − Σ excluded.actual_cost_usd` produces a paid figure on the priced cohort. Then `no_cache_hypothetical − actually_paid_subset` is the savings on the same cohort.

**N-4**: `render_text.py:526` writes literal `f", {delta.pct_of_baseline}% of baseline"`. The `baseline` field on `CostDelta` (`analyze.py:341`) is a typed identifier (`"no_cache_hypothetical_usd"`) but the renderer never consults it. Mechanical translation step missing.

#### Fix shape

**N-1 fix** (medium, data-model + renderer):

1. **`analyze.py:3996-4014`** — Replace the binary "all-or-unavailable" branch with three states:
   - All exclusions have `actual_cost_usd` populated → compute `actually_paid_subset`, emit a real `_cost_delta` with new `compared_to="actually_paid_priced_cohort_usd"` and an `excluded_nodes` field.
   - Any exclusion has `actual_cost_usd=None` → keep `_unavailable_delta` (genuinely incomparable).
2. **`analyze.py:331-343`** (`CostDelta`) — Add optional `excluded_nodes: tuple[str, ...] = ()` field.
3. **`render_text.py:486-504`** — Render `Actual savings (this run): saves ~$0.22 (excludes generate-chorus-options)` when the field is populated.
4. **`render_json.py`** — Surface the new field.

**N-4 fix** (small, renderer-only):

`render_text.py:518-529` — Map `delta.baseline` to a user-facing phrase. For the only baseline currently used (`"no_cache_hypothetical_usd"`), render `"3% of no-cache cost"`. Mechanical translation step that's already done for `kind` ("savings" → "saves $X/run").

#### Complexity

| Metric | N-1 | N-4 |
|---|---|---|
| LOC | 50-80 | 10-20 |
| Files touched | 4 (`analyze.py`, `cost_estimation.py` read, `render_text.py`, `render_json.py`) | 1 (`render_text.py`) |
| Renderer-only? | No | Yes |
| Existing tests broken | 1 (migrate `test_text_summary_explains_projection_excluded_actual_delta` at `tests/test_core/test_cache_analysis_renderers.py:1209`) | 0 |
| New tests needed | 1 priced-cohort path + 1 mixed (some `actual_cost_usd=None`) | 1 renderer test |
| Baselines drift | ~3-5 | ~2-3 |

#### Pre-flight risk (verify before implementing N-1)

The N-1 fix subtracts `excluded.actual_cost_usd` from `actually_paid.total_usd`. If `row.cost_usd` for batch sub-workflow rows reflects parent-only AND `actually_paid` sums all trace leaves (including children), subtraction is single. If `row.cost_usd` already includes children AND `actually_paid` also includes them, subtraction is single. If they're inconsistent, you'll double-subtract.

**One-test verification**: build a heterogeneous batch fixture, assert `row.cost_usd` equals the sum of its trace-recorded children. Investigator flagged this as the load-bearing assumption.

#### Composition

Independent. Can land any time. Mid-priority.

---

### Cluster C — Recommendation impact projection (N-7)

The single highest-leverage agent-action improvement. Recommendations get dollar-impact tags, agents see what to fix and why.

#### Finding

**N-7** — The analyzer doesn't surface the obvious caching wins on big-token-count high-call-count nodes. Lyrics-generator's `score-choruses` runs 136 times with 158K tokens (21.5M tokens total) with no `prompt_cache:` declared. Recommended Actions has 2 entries; neither says "cache score-choruses, that saves $X."

#### Original framing was wrong (important)

I initially classified this as "the analyzer doesn't detect this opportunity." The recommendation-gap investigator showed I was wrong: **the analyzer IS detecting it**. Recommendation #1 ("add `concept` in chorus-chooser.pflow.md's ## Cache") is exactly what would unlock caching the 158K-token shared prefix on score-choruses + select-chorus. The detection works.

The real problem is **framing + impact projection**. The recommendation says "add `concept` to chorus-chooser's ## Cache" — true but doesn't say "this saves you re-sending 21.5M tokens across 136 calls." Currently `savings_usd=None` (`analyze.py:3228`) so the action can't claim a dollar impact and gets passively ranked.

#### Root cause (verified)

`cache.sub-workflow-cache-undeclared` is emitted by `_emit_sub_workflow_cache_findings` at `analyze.py:3150-3238`. The savings field is hardcoded to `None`. The catalog template emits the headline without dollar info.

`RECOMMENDED_ACTION_PRIORITY` (`warning_catalog.py:753-784`) has a savings-descending tiebreak. Once `savings_usd` is populated, the recommendation auto-promotes to the top with a "saves ~$X/run" tag.

#### Fix shape

**Option A (recommended)** — Enrich the existing recommendation:

In `_emit_sub_workflow_cache_findings`, compute projected savings from the parent's per-call rows for the affected child nodes:
```
savings_usd = Σ over affected child nodes:
    calls × shared_token_estimate × input_rate(model) × cache_read_factor
```

Where:
- `calls` = parent's per-call observed count
- `shared_token_estimate` = the shared `${var}` content's token count (already estimated for `cacheable_tokens_estimated` upstream)
- `cache_read_factor` = (1 - 0.1) = 0.9 (prompt-cache reads are 0.1× input price for Anthropic)

Pass `savings_usd` through the `Diagnostic`. Renderer auto-displays "saves ~$X/run."

**Option B (rejected)** — New catalog ID `cache.high-leverage-uncached` with metric thresholds (calls > N AND tokens > min_cache_threshold). Would fire on solo nodes too (workflows where one node is called in a tight loop). ~250-300 LOC, requires DD#29 design review per the closed-catalog policy.

Option A is smaller, doesn't need spec review, and addresses the observed friction directly.

#### Complexity

| Metric | Value |
|---|---|
| LOC | ~150 in `analyze.py` + tests |
| Files touched | `analyze.py` (savings calc), `warning_catalog.py` (verify catalog header template tolerates savings), tests |
| Renderer-only? | No (analyzer enrichment) |
| Catalog changes | None (same ID, additive context field) |
| JSON shape changes | Additive (`savings_usd` already an optional field on Diagnostic) |
| DD#29 review needed | No (extending existing entry) |
| Existing tests broken | Minor (per-id-emission tests may need fixture updates if they assert on `savings_usd is None` literal) |
| Baselines drift | ~5-8 (anywhere `cache.sub-workflow-cache-undeclared` fires with measurable parent-row data) |

#### Risk

Pricing model assumes Anthropic's 0.1× cache-read factor. For Gemini and OpenAI, the factor differs. If the row's `model` is unknown or unpriced, fall back to `savings_usd=None` (current behavior). Don't fabricate.

Threshold tuning: at what token-count is "savings ~$0.0001/run" worth surfacing? Use the existing `padding_advisor` sensitivity floor ($0.005/advisory) for parity.

#### Composition

Independent. Land any time.

---

### Cluster D — Header + per-call clarity (N-2 / N-3 / N-9 / N-5 / N-6 / C-5 / L-6)

Seven small renderer-only fixes in one file. First-impression polish + persistent vocabulary clarity.

#### Findings

**Header (N-2/N-3/N-9)**:

- **N-2** — Model list duplicated. Line 3 says `using 3 models: A, B, C`. Line 5 says `Observed models: A, B, C`. Same data twice. Confirmed regression: two commits on consecutive days both added model rendering paths.
- **N-3** — Line 3 is a 39-word run-on packing 5 distinct facts (node count, invocation gap, gap reason, model list, heterogeneous caveat).
- **N-9** — Line 6 enumerates all 15 sub-workflow names that already appear in `## Per-child analyze-cache commands` and per-call section headings. Header filler.

**Per-call rows (N-5/N-6/C-5/L-6)**:

- **N-5** — `src=high` next to `cacheable=?` reads as contradictory. They're orthogonal: `src=` is input-tokens confidence, `cacheable=?` means "no `prompt_cache:` declared so nothing to measure." Row design conflates them.
- **N-6** — `(×N)` and `calls=N` appear on some rows. They're DISTINCT signals (IR-declared batch size vs trace-observed actual calls) but the labeling doesn't communicate this. Sometimes match coincidentally, sometimes diverge.
- **C-5** — `src=high|medium|low` magic strings have no rendered key. Agents can't tell what each level means.
- **L-6** — No output token column. For $2.31 of cost where output was 41% of total tokens (817K of 2M), agents can't see which node generates the most expensive output.

#### Root causes (verified)

| Finding | File | Line | Root cause |
|---|---|---|---|
| N-2 | `render_text.py` | 152-153 | `Observed models:` line was added by `e3238bb3` on 2026-05-07; `using N models:` was added by `573cc4b9` on 2026-05-06. Second commit didn't notice the first already promoted observed models into the scale line. |
| N-3 | `render_text.py` | 184-229 (`_format_scale_line`) | Historic accretion across feature additions. Five concerns chained additively. No backward-compat constraint forces single-line. |
| N-9 | `render_text.py` | 170-181 (`_format_sub_workflow_breakdown_line`) | Pure cosmetic prose. Same names enumerated in two structured sections downstream. |
| N-5 | `render_text.py` | 1190-1204 (`_DATA_SOURCE_DISPLAY` + render at 1134-1169) | `src=` and `cacheable=` are computed independently. `declared_prompt_cache: list[str] \| None` already distinguishes "no declaration" from "declared but unresolvable." |
| N-6 | `render_text.py` | 1139 (`(×N)` from `_estimate_batch_size`) and 1161 (`calls=N` from `observed_call_count`) | Distinct signals; label vocabulary doesn't communicate the difference. |
| C-5 | `render_text.py` | n/a (no key emitted) | Existing `_per_call_scope_explainer` (line 1207-1222) explains ratios, never src=. |
| L-6 | `render_text.py` | 1162-1168 (column template) | `output_tokens_estimated` already populated on `PerCallRow` at `analyze.py:1498`. Just not rendered. |

#### Fix shapes

**N-2**: Delete lines 152-153 in `render_text.py`. Keep the IR-divergence line at 154-155 (it has its own purpose). Trace-mode evidence is already in the `Evidence:` line + scale line.

**N-3**: Restructure `_format_scale_line` to return `list[str]` and emit 2-3 lines. Natural split:
```
  Workflow: 25 LLM nodes (3 dynamic batch nodes; invocation count unavailable)
  Models: gemini/gemini-2.5-flash, gemini/gemini-2.5-flash-lite, gemini/gemini-3-flash-preview
  Heterogeneous: generate-chorus-options (model varies per batch item)
```

**N-9**: Drop the CSV from `_format_sub_workflow_breakdown_line`. Keep `(2 in lyrics-generator.pflow.md, 23 in 15 sub-workflows)`. Drop `: name1, name2, ...` suffix.

**N-5**: When `declared_prompt_cache is None`, render `cacheable=n/a`. Reserve `?` for the rarer case (declared but Tier-2 chunk resolution returned None).

**N-6**: Rename `(×N)` → `batch_items=N` for clarity. The renaming makes it clear the marker is IR-derived (batch declaration) vs trace-observed (`calls=N`).

**C-5**: Append one line in `_render_per_call` after the existing scope explainer (around line 1056):
```
  src= high (trace/memo) | medium (estimator) | low (heuristic)
```

**L-6**: Add `out=` column to row template at `render_text.py:1162-1168`:
```
  ... tokens=NNN  out=NNN  cacheable=NNN  ratio=NN%  src=...
```

When `output_tokens_estimated is None`, render `out=    ?`.

#### Complexity

| Finding | LOC | Test drift | Baselines drift |
|---|---|---|---|
| N-2 | ~3 | 0 | ~5 |
| N-3 | ~30 | 0 | ~15 |
| N-9 | ~5 | 1 (line 3132 of `test_cache_analysis_renderers.py`) | ~5 |
| N-5 | ~5 | 0-3 | ~5 |
| N-6 | ~3 | 2-5 | ~5 |
| C-5 | ~3 | 0 | ~3 |
| L-6 | ~5 | 5-10 | ~10 |

**Combined**: ~54 LOC, 1 file (`render_text.py`), 8-19 substring test edits, ~15 unique baselines (heavy overlap — same captures hit by multiple changes).

#### Composition

All 7 fixes touch `render_text.py`. Bundle as one PR. No interactions, no ordering constraints. Single baseline regen pass.

---

### Cluster E — Section organization tidy (A-4 + N-10 + L-5 + B-3 + B-4)

Structural tidy-up. Each fix is small but they compose.

#### Findings

**A-4** — `19 opportunities` doesn't match any rendered section. Count includes 17 cross-workflow renames (in `## Sub-workflow boundaries`) plus 2 actionable (in `## Recommended actions`). I removed this from the original audit during triage; reading the post-fix output as a fresh agent, it's genuinely confusing. Reactivating.

**N-10** — `## Other blocking errors (surfaced for awareness)` reads as orphan when no `## Cache blocking errors` sibling renders. The B-9 split commit introduced both sections; "Other" only makes sense when both exist.

**L-5** — "117 events skipped" is a coverage statement (of 253 trace events, 136 in the per-call table, 117 are batch sub-workflow per-item children) buried in `## Notes` mixed with provider quirks. Belongs near the per-call report.

**B-3** — `## Per-child analyze-cache commands` emits 15 absolute paths × ~200 chars each. Same prefix on every line. Doesn't tell agents which children have findings worth checking.

**B-4** — `## Notes` has 3 near-identical batch lines (`fetch-sources`, `analyze-sources`, `create-songs`). Same prose, only batch name + items expression differ. Same pattern as L-4 (already collapsed).

#### Root causes (verified except B-4)

**A-4**: `analyze.py:3962-3966` computes `cache_focused = [d for d in warnings if _is_cache_focused(d)]` then `info_count = sum(1 for d in cache_focused if d.severity == Severity.INFO)`. Cross-workflow renames are catalog-IDed and count as INFO → included. But `view_helpers.py:44-47, 108-134` `build_recommended_actions` excludes them via `_CROSS_WORKFLOW_ALIGNMENT_IDS` → renamed to "boundary findings" in their own section. Count vs section-rendering diverge.

**N-10**: `render_text.py:56-62` conditionally renders both blocking-error sections. When cache-side list is empty, only `## Other blocking errors` renders — the "Other" qualifier becomes orphan.

**L-5**: `analyze.py:3681-3689` appends one prose note carrying just the count (`silent_skip_no_predicted_key`, an int counter). `_render_notes` (`render_text.py:1299-1305`) emits all `analysis.notes` verbatim at the bottom. The 253-event total population isn't captured anywhere — only the skip count.

**B-3**: `render_text.py:1172-1183` `_render_sub_workflow_drill_in` enumerates absolute paths from `SubWorkflowRollupEntry`. The entry doesn't carry per-child finding counts, and adding them would only surface boundary findings (per-child internal opportunities require running per-child analyze-cache anyway). Path-noise fix is feasible; findings-awareness is rejected as misleading.

**B-4** (assumed, not investigated): same mechanism as L-4's discrepancy-note collapse (commit `d5f61b24`). Renderer-only collapse using a similar `_format_skipped_workflows_note`-style helper.

#### Fix shapes

**A-4**: Split the count line in `_append_summary_counts` (`render_text.py:452-464`):
```
  2 actionable opportunities + 17 sub-workflow boundary findings (19 cache-domain info)
```
Honest about the existing two-section structure. Renderer-only. Need to expose `cross_workflow_alignment_count` either as a typed field or compute inline via `len([w for w in analysis.warnings if is_cross_workflow_alignment(w)])`.

**N-10**: In the orchestrator that decides which header to render, pass `cache_blocking_present: bool` into the section renderer. When False, drop the "Other" qualifier — render `## Blocking errors`.

**L-5**: Promote `silent_skip_no_predicted_key` to typed field on `CacheAnalysis`:
```python
unattributed_trace_event_count: int = 0
```
Drop the prose Note. Render in `## Per-call cache report` header alongside the existing `Showing N of M` line:
```
  Showing 14 of 25 LLM nodes; all-clean rows hidden (--all-rows shows everything).
  117 batch sub-workflow per-item events not separately attributed.
```

**B-3**: Emit `cd <repo-root>` preamble + relative paths via common-prefix detection. ~20 LOC. Don't try to make it findings-aware — investigator showed the honest signal isn't useful.

**B-4**: Mirror L-4's collapse pattern. Aggregate the 3 near-identical notes into one summary entry with batch names + items expressions enumerated. ~10 LOC.

#### Complexity

| Finding | LOC | Renderer-only? | Test drift | Baselines drift |
|---|---|---|---|---|
| A-4 | ~15 | Yes | ~2 | ~3 |
| N-10 | ~10 | Yes | 1-2 | ~3 |
| L-5 | ~25 | No (small data-model) | minor | ~3 |
| B-3 | ~20 | Yes | 1-2 | ~2 |
| B-4 | ~10 | Yes | 1-2 | ~2 |

**Combined**: ~80 LOC. A-4 and N-10 both edit summary section so batching saves churn. L-5 is the only data-model edit (small).

#### Composition

A-4 and N-10 interact (both edit summary section). Group them. L-5, B-3, B-4 are independent.

---

## Pre-flight verifications

These should land or be confirmed BEFORE the dependent PR is implemented.

### Before Cluster B (cost-savings)

**Verify `row.cost_usd` doesn't double-count batch sub-workflow children.** The N-1 fix subtracts excluded rows' costs from total paid. If `row.cost_usd` already includes children AND `actually_paid` sums all trace leaves, subtraction is correct. If they're inconsistent, you'll double-subtract.

**Test to write**: build a heterogeneous batch fixture where parent row has children. Assert `row.cost_usd == Σ row.children.cost_usd` (or whatever the actual contract is). If the test reveals the contract is parent-only, the N-1 fix needs to use a different aggregation path.

### Before Cluster C (recommendation impact)

**Verify the savings calculation uses correct pricing.** For each `model` in the savings sum, confirm:
- Anthropic: 0.1× input rate for cache reads
- Gemini: cached_tokens billed at separate rate (verify in `cost_estimation.py::get_model_pricing`)
- OpenAI: `prompt_cache_retention` rate (verify)

If any model is unpriced, fall back to `savings_usd=None`. Don't fabricate. Existing `_unavailable_delta` pattern is the precedent.

### Before any PR

**Run the full baseline harness twice**: once before your fix to capture pre-fix output, once after. The diff should match exactly your fix's expected behavior. Unexpected drifts = silent regressions.

---

## Secondary backlog (high-value items from old audit, not in primary queue)

These are real and worth doing eventually. They don't gate Task 159 merge or Task 160 start. Listed in rough priority order.

### Worth fixing in v1.x

- **C-4 — Suggested run command uses `<value>` literal placeholder.** `Suggested: pflow run <path> article=<value>`. Agents that copy and run literally pass `<value>` as input → wasted LLM call. Use input declaration's `type` to emit typed placeholder (`article=<string>` or `article=<your-article>`). ~15 LOC, renderer-only. Fix in same PR as Cluster D if convenient.

- **C-3 — `cache.prompt-cache-undeclared-name` validator error lacks `See also: pflow guide caching`.** Other cache validator errors carry it. Single-line consistency fix. Files: error producer in `core/workflow/data_flow.py`. ~5 LOC.

- **C-7 — Trace-mode Notes section verbose with internal jargon.** "Discrepancy detection: predicted-key matching unavailable..." reads dense. Investigator didn't explore; likely renderer-only shortening + move long explanation to `pflow guide caching`. ~20 LOC.

- **C-8 — Per-call header math is confusing when 0 visible.** When `--all-rows` would be needed, two header lines say similar things. Collapse to one line when visible-row count is 0. ~10 LOC.

- **B-15 — `cache.opportunities-available` mentioned but not explained.** Doc gap in `pflow guide caching`. ~5 LOC of doc.

- **B-16 — Notes section grouping.** Currently flat list mixing provider quirks with analyzer limitations. Two sub-headers (`### Provider notes` and `### Analyzer limitations`) or reorder by signal value. ~15 LOC.

### Lower priority

- **B-1 — `model=` empty string in static mode.** Need to verify if still present after the L-1 trace-mode fix. The trace-mode rendering uses observed_models now; static mode rendering may still show blank. Spot check with `pflow analyze-cache --no-trace-autoload <workflow>` on a workflow without `settings.default_model` configured. If still blank, render `model=<unresolved>`.

- **B-10 — `pflow guide <cache-using-workflow>` puts caching topic at line 286 of 1224.** Token-cost issue for agents loading the full guide. Add `--topic caching` flag for filtered retrieval, or order detected topics by feature density. ~30 LOC.

- **B-14 — `pflow guide caching` doesn't show example trace-mode rendered output.** Add a fenced example output under "Discovering Opportunities". ~15 lines of doc.

- **B-19 — "no predicted cache_key" message conflicts with cache_key visible in trace.** The B-18 fix changed adjacent wording; verify if still confusing in current output before fixing. May be partially solved.

- **C-2 — Error messages don't include workflow file path.** Real for CI/multi-workflow pipelines. For single-file invocations agent already knows the path from their command. Lower priority. ~20 LOC threading.

### JSON-only — deprioritized per user directive

You can ignore these unless someone specifically asks:

- **A-2** — Float precision artifacts in JSON savings/cost numbers. `round()` to 6 decimals in `cost_estimation.py` before serialization.
- **A-5** — `unavailable_models_by_workflow: {}` and `unavailable_models: []` redundancy.
- **C-6** — JSON error envelope for missing workflow has no `suggestion` field.
- **C-9** — `evidence_kind: "predicted"` opaque to JSON consumers.
- **D-1** — `projection_exclusions[*].reason` and `unavailable_reason` use different vocabularies.
- **D-2** — Top-level summary nullity carpet bombs JSON.
- **D-3** — `see_also: ["caching"]` only surfaced in JSON, not text warnings.

### Already filed externally

- **C-1** — Bracketed catalog ID inconsistency. GH #381. Referenced from Task 160's "Adjacent work" — defer to that refactor.
- **L-8** — Trace JSON prompt content duplicated 4× per LLM event. GH #382. Natural fit for Task 133.

---

## What NOT to fix

Explicit no-go list to save you time.

1. **Don't add new catalog IDs.** The catalog is closed in v1 per DD#29 — additions need user/spec design review. Cluster C (N-7) deliberately enriches an existing ID rather than adding a new one. If you find yourself reaching for `cache.high-leverage-uncached` or similar, stop and ask first.

2. **Don't make the per-call drill-in section "findings-aware."** Investigator analyzed this for B-3. Per-child internal opportunities only surface when running analyze-cache per child; the only data the parent has is boundary findings, which would mislead. Path-noise fix only.

3. **Don't try to predict savings without prices.** If a model is unpriced (no entry in `MODEL_CAPABILITIES` or `get_model_pricing` returns None), fall back to `savings_usd=None`. The "honest unmeasurable" convention is a load-bearing pattern across this codebase.

4. **Don't add `# noqa: C901`.** User directive — when complexity nudges past 10, decompose into helpers. The constants-driven-loop pattern is the canonical decomposition shape.

5. **Don't bump `JSON_FORMAT_VERSION` for additive changes within the same minor.** Per-branch staging discipline; consumers don't exist yet. Format version only bumps at minor for semantic shifts and major for breaking changes.

6. **Don't break the "evidence basis" principle.** Predictive warnings about state comparisons fire only when the state to compare against exists. If you're adding a new emission path, check that the "premise" is detectable from data on hand.

7. **Don't synthetic-fixture-test cache rendering or analyzer paths.** Pitfall #19 has bitten this branch 8+ times. Every regression gate test must drive `analyze(...)` (or `WorkflowRunner.run()`) end-to-end with real state (memo cache, NamespacedSharedStore wrap, real trace files).

8. **Don't touch the existing `_warnings_for_partial_trace` filter logic.** L-10's fix replaced the old severity-based filter with a catalog-flag filter (`requires_complete_trace`). This is a load-bearing invariant — adding a new warning that should suppress in truncated trace mode means setting the flag in the catalog spec, NOT touching the filter.

---

## File map for new agent

### Hot files (touched by ~all fixes)

- `src/pflow/core/cache_analysis/render_text.py` (~1300 lines) — most renderer changes happen here. Read the module docstring first.
- `src/pflow/core/cache_analysis/analyze.py` (~4000 lines) — analyzer entry point. Big file; use grep for specific functions.
- `src/pflow/core/cache_analysis/CLAUDE.md` — tacit knowledge for the cache-analysis module. Read before changing analyzer.

### Touched by some fixes

- `src/pflow/core/cache_analysis/cost_estimation.py` (~600 lines) — projection logic, exclusion handling.
- `src/pflow/core/cache_analysis/warning_catalog.py` (~1200 lines) — catalog SSoT. Frozen-dataclass pattern.
- `src/pflow/core/cache_analysis/cross_workflow.py` (~400 lines) — walker producing rename detections.
- `src/pflow/core/cache_analysis/view_helpers.py` (~150 lines) — derived projections from `analysis.warnings`.
- `src/pflow/core/cache_analysis/render_json.py` (~280 lines) — JSON shape (mostly stays unchanged).
- `src/pflow/core/cache_analysis/token_estimation.py` (~420 lines) — 4-tier token estimation.

### Test files

- `tests/test_core/test_cache_analysis_renderers.py` — renderer tests. Mostly substring assertions, tolerant of additive changes.
- `tests/test_core/test_cache_analysis_analyze.py` — analyzer tests.
- `tests/test_core/test_cache_analysis_per_id_emission.py` — per-id production-shape emission tests.
- `tests/test_core/test_cache_analysis_per_id_coverage.py` — per-id catalog round-trip tests.
- `tests/test_core/test_cache_analysis_token_estimation.py` — token estimator tests.

### Baseline harness

- `.taskmaster/tasks/task_159/baseline/` — 65 cases. After any fix:
  - `./regenerate.sh` (full) or `./regenerate.sh <surface>` (targeted)
  - eyeball `git diff` on `expected-stdout.txt` files
  - `./verify.sh` to confirm 65/65 pass

The lyrics-generator captures (`12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt` and `10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`) are the canonical real-world tests. Inspect them before AND after every fix.

---

## Verification confidence

Honest about what's grounded vs assumed.

**Verified by parallel `pflow-codebase-searcher` investigation** (high confidence):
- N-1, N-4 (cost-savings group) — investigator cited specific file:line, traced the data flow, identified the load-bearing assumption.
- N-2, N-3, N-9 (header group) — investigator confirmed regression source (commit `e3238bb3`) and verified test impact via grep.
- N-5, N-6, C-5, L-6 (per-call group) — investigator confirmed `output_tokens_estimated` already on PerCallRow, distinguished `(×N)` from `calls=N` semantics, identified the renderer-only fix paths.
- B-2, N-8 (cross-workflow group) — investigator analyzed the data model, confirmed it's groupable both ways, identified the composition order requirement.
- N-7 (recommendation gap) — investigator REFRAMED my original interpretation. Confirmed the analyzer detects the right opportunity; the gap is impact projection, not detection. Both Option A and Option B analyzed.
- A-4, N-10, L-5, B-3 (section organization) — investigator confirmed root causes at file:line, identified the data-model edit needed for L-5.

**Assumed / not investigated** (verify before acting):
- B-4 — assumed similar mechanism to L-4 based on the audit description. Investigator wasn't asked. ~10 LOC estimate is informed but unverified.
- The pre-flight risk for Cluster B (`row.cost_usd` batch double-count) — investigator flagged but did not confirm. Implementer should test before fixing.
- Pricing model assumptions for Cluster C — Anthropic 0.1× factor is documented; Gemini and OpenAI need verification in `get_model_pricing`.

**Original audit findings I downgraded that should stay downgraded**:
- A-2, A-5, C-6, C-9, D-1, D-2, D-3 — JSON-only, user-deprioritized.
- C-1, L-8 — already GH-filed.

**Original audit findings I marked as solved that may not be**:
- B-1 (`model=` empty in clean env) — was partially addressed by L-1's trace-mode model fix, but static mode rendering may still show blank. Verify with a no-trace + no-default-model invocation before acting.
- B-19 ("no predicted cache_key" wording) — the B-18 fix may have addressed this. Verify in current capture.

---

## How to start

If this is your first PR:

1. Read the lyrics-generator captures (both static `12-01` and trace `10-05`) to ground yourself in the actual output.
2. Run `make test` and `./.taskmaster/tasks/task_159/baseline/verify.sh` to confirm clean starting state.
3. Pick Cluster A (cross-workflow grouping). It's renderer-only, no test breakage, single biggest visible improvement, no compositions to worry about.
4. Implement, regenerate baselines for case 05 + 12-01, verify 65/65 still pass, write the new fixture tests for the dedup + grouping behavior, commit.
5. Pick the next cluster.

If you encounter ambiguity not covered by this document — ASK. Don't proceed on guesswork. Per the project's epistemic manifesto: "Ambiguity is a STOP signal."

The user's stated priorities (verbatim from the conversation that produced this plan):
- "Text output, agent UX, and correctness is what matters"
- "Actionable and easy to understand information"
- JSON shape is lower priority

If a fix has obvious tradeoffs, present them. Don't choose silently. The user's decision matters more than your judgment when stakes are non-trivial.

---

## Estimated total effort

| Cluster | LOC | Files | Tests | Baselines | Effort |
|---|---|---|---|---|---|
| A — Cross-workflow grouping | ~50 | 1 | 2 new | ~5 | 2-3 hours |
| B — Cost-savings honesty | ~70 | 4 | 1 migrate + 2 new | ~5 | 4-6 hours (incl. pre-flight) |
| C — Recommendation impact | ~150 | 2 | minor + 1-2 new | ~8 | 4-6 hours |
| D — Header + per-call clarity | ~54 | 1 | 8-19 substring edits | ~15 | 3-4 hours |
| E — Section organization | ~80 | 2-3 | 5-8 edits + 1 new | ~13 | 3-4 hours |
| **Total** | **~404** | **~5 unique** | **~25** | **~30 unique** | **16-23 hours** |

Heavy baseline overlap — same captures hit by multiple clusters. Rough rule: regenerate-and-eyeball is ~5 minutes per affected case; ~30 cases × 5 min = 2.5 hours of pure regeneration / inspection across all 5 PRs.

Done.
