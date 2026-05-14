# Plan: Per-call cache report refactor + batch-alias parameter propagation

> **Revision note (2026-05-09)**: This plan was revised after a 4-agent code
> review (review-plan, review-silent-failures, review-feature-interactions,
> review-impact-completeness). The original Step 2 (cross-workflow walker →
> per-call candidate injection) was DROPPED — review surfaced that its scope
> overlaps the deferred partial-declaration PR and its cost-projection /
> dedup / semantic-framing risks compound. Step 2's scope is now part of the
> handoff doc at
> `.taskmaster/tasks/task_159/implementation/handoffs/task-159-partial-declaration-detection-handoff.md`.

## Context

Task 159's `pflow analyze-cache` produces a per-call cache report that has
two connected defects, both visible on the canonical real-world capture
`.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`:

1. The `cacheable=` column conflates **two different semantics** —
   "tokens that went through the cache mechanism this run" (Tier 1
   trace-driven) and "tokens that could be cached if you declared"
   (Tier 2 projection). Same column, no marker, agent can't tell which.

2. Sub-workflow LLM nodes (`score-choruses` in `chorus-chooser.pflow.md`)
   show `cacheable=?` even when the intra-workflow walker correctly
   identifies `${concept.title}` and `${concept.core_idea}` as candidates
   shared across `score-choruses` and `select-chorus`. Tier 2 chunk
   resolution falls through because `wf_ctx.parameters` is empty —
   `_build_parameters_by_workflow`'s propagation breaks at the first
   batch boundary (`${item}` from lyrics-generator → song-creator batch
   invocation can't resolve statically). Empirical sweep across all 65
   baselines confirms ZERO Tier 2 firings on any per-call row in any real
   workflow today.

8 parallel investigators verified each defect; a 4-agent code review
verified the fix shapes. The previously-proposed cross-workflow walker
plumbing (was Step 2) was retired from this PR's scope — it's redundant
with the intra-walker for cases where the intra-walker fires (chorus-chooser
example), and its remaining unique-value cases overlap the deferred
partial-declaration detection PR.

The deferred PR is fully captured in:
`.taskmaster/tasks/task_159/implementation/handoffs/task-159-partial-declaration-detection-handoff.md`

This PR ships the two unambiguous fixes.

---

## Scope

### What this PR does

1. **Renderer**: replace `_format_per_call_row`'s `key=value` row format
   with a column-headered table layout (one column-header line + one
   horizontal divider line, GLOBAL across all sections in the per-call
   report). Split the conflated `cacheable=` into two columns:
   `cached_now` (Tier 1 active caching) and `could_cache` (Tier 2
   projection of unrealized opportunity). Drop the `src=` column from
   each row; emit a confidence footer ONCE when ≥1 row's input-token
   `data_source` is below `high` OR ≥1 row has a batch-exemplar
   cacheable projection. Consolidate inline annotations
   (`opaque-prompt`, `[unexecuted]`, `observed_models=`, batch markers
   reframed as `batch_items=N`) into a single `notes` column.

2. **Batch-alias parameter propagation**: at `_resolve_child_input_value`
   (`analyze.py:1291-1306`), detect when the edge's value-expression
   roots on `parent_batch_alias`. When detected, resolve the parent's
   batch `items:` expression against parent context, take the first item
   (deterministic items[0] exemplar), bind it into the shared store as
   `{alias: first_item}` before delegating to TemplateResolver. Honest
   unmeasurable when items don't resolve (catch + log + return None,
   mirroring the existing exception-handling pattern in the same
   function).

### What this PR does NOT do

- **Does not** inject cross-workflow walker findings into per-call
  candidates. That work is now part of the deferred handoff (the
  partial-declaration PR's emission path is the right home).
- **Does not** add a new catalog ID or warning.
- **Does not** add an `output` token column (`output_tokens_estimated`
  is `null` in every current baseline; defer until output token data
  is more populated).
- **Does not** rebuild output token tracking, parameter propagation
  for non-batch shapes, or the cross-workflow walker's data model.
- **Does not** change JSON shape (`render_json.py:222-260` is decoupled
  from text format).

---

## Implementation steps

### Step 1 — Renderer column refactor

**File**: `src/pflow/core/cache_analysis/render_text.py`

**Current state**: `_format_per_call_row` (lines 1289-1333) emits a
single dense `key=value` line per row. `_DATA_SOURCE_DISPLAY` (line
1371) maps `data_source` to `high|medium|low`. No header, no divider.

**Target shape** (one global header + divider; per-section `### ...`
group headings remain):

```
## Per-call cache report
  Actual cache ratios from declared `prompt_cache:` subsets.
  cached_now: tokens that went through cache this run; — when inactive.
  could_cache: tokens that could be cached if you declare/extend prompt_cache:; — when no candidate.
  Showing 14 of 25 LLM nodes; all-clean rows hidden (--all-rows shows everything).

  node                       model                    input    cached_now  could_cache  ratio  calls  notes
  ------------------------------------------------------------------------------------------------------------

  ### chorus-chooser.pflow.md (called by choose-chorus)
  generate-chorus-options    <varies>                     ?            —            ?     ?%     32  opaque-prompt; observed=flash-lite,3-flash
  score-choruses             gemini/gemini-2.5-flash 158,704            —      158,704     ?%    136
  select-chorus              gemini/gemini-2.5-flash  36,289            —       36,289     ?%      4

  ### song-creator.pflow.md (called by create-songs)
  rewrite-emotional          gemini/gemini-2.5-flash  94,100       63,009            —    67%      4
  rewrite-craft              gemini/gemini-2.5-flash  84,124       56,785            —    68%      4

  Hidden: 4 nodes at ≥80% projected cache ratio with no warnings (rerun with --all-rows).
  Footer (only when applicable): Some token estimates are projected from estimator/heuristic, or from a single batch-iteration exemplar. Affected nodes: ...
```

**Key decisions** (all flagged as ambiguous in review; resolved here):

- **Header + divider placement**: ONCE GLOBALLY at the top of `## Per-call
  cache report`, BEFORE any `### file` group heading. Same column widths
  across all groups (computed globally from all rendered rows).
  Single-workflow mode (no `### file` headings) gets the same global
  header — no special-case handling needed.

- **Column widths**: GLOBAL across all rendered per-call rows. New helper
  `_compute_per_call_column_widths(rows: list[PerCallRow]) -> tuple[int, ...]`
  walks all rows once, returns max-width per column. Header line and data
  rows both use the same widths via `_format_table_row(cells, widths)`.

- **`_per_call_scope_explainer` text update**: extend the explainer (at
  `render_text.py:1388-1403`) to document `cached_now` / `could_cache`
  semantics. Specifically: "`—` means the column doesn't apply to this
  row's tier — `cached_now=—` means no Tier 1 evidence (no declared
  cache or cache didn't fire); `could_cache=—` means Tier 1 already
  fired, no further projection needed." This addresses the em-dash
  ambiguity surfaced in review.

- **`src=` column REMOVED from rows**. Replaced with confidence footer.

**Cell semantics**:

| Cell | Tier 1 (declared+fired) | Tier 2 (declared+resolved OR candidate+resolved) | Tier 3 (unmeasurable) |
|---|---|---|---|
| `cached_now` | `cache_creation+cache_read` (int) | `—` | `—` |
| `could_cache` | `—` | tokenized chunk total (int) | `?` |
| `ratio` | percent | percent | `?%` |

A node's row populates EITHER `cached_now` OR `could_cache`, never both,
in this PR. (The "both" case becomes possible when the deferred
partial-declaration PR ships; the column shape accommodates it natively.)

**Refactor pattern** (simplicity-first; AI-agent-maintainable):

Decompose `_format_per_call_row` into per-cell functions returning
strings. The row builder concatenates with widths. New columns become
a one-line addition; cell logic is testable in isolation.

```python
_cell_input(row)                  -> str
_cell_cached_now(row)             -> str   # populated only on Tier 1
_cell_could_cache(row)            -> str   # populated on Tier 2/3
_cell_ratio(row)                  -> str
_cell_notes(row, inline_warnings) -> str
```

**Cell rules**:

- `_cell_cached_now`: When `cacheable_data_source == "trace"` AND
  `declared_prompt_cache` is truthy, emit `cacheable_tokens_estimated`
  formatted with thousands. Else emit `—` (em-dash).
- `_cell_could_cache`: When `cacheable_data_source in {"memo",
  "parameters"}` AND `declared_prompt_cache` is FALSY (Tier 2 candidate
  projection), emit number. When `cacheable_data_source == "unavailable"`,
  emit `?`. When `cacheable_data_source == "trace"` (Tier 1 fired), emit
  `—`. When `cacheable_data_source in {"memo", "parameters"}` AND
  `declared_prompt_cache` is truthy (Tier 2 declared+resolved — node
  declares but trace shows zero firings), emit number (this is the
  "declared but didn't fire" case — agent should know there IS measurable
  potential even if nothing fired).

Drop `_DATA_SOURCE_DISPLAY` and `_data_source_display` — replaced by:

- **`_per_call_confidence_footer(rows)`** — emits one-line footer
  below the table when:
  - ≥1 row has input-token `data_source in {"estimator", "heuristic"}`, OR
  - ≥1 row has `cacheable_data_source == "parameters"` AND `is_batch ==
    True` (batch-exemplar projection — single-iteration-anchored)

  Footer text: lists affected node IDs, grouped by reason. Returns None
  when neither condition holds.

**Notes column** consolidates (in this order, semicolon-separated):
- `[unexecuted]` (when `did_not_execute_in_trace`)
- `opaque-prompt` (when present in inline_warnings)
- `batch_items=N` (replaces `(×N)` — same data, named for clarity)
- `observed=<comma-list>` (when `model_is_heterogeneous` or
  `len(observed_models) > 1`; truncate the `gemini/` prefix)
- Other inline catalog warning IDs (current behavior)

**Visibility filter extension** (`_row_has_real_data` at
`render_text.py:1406-1428`): extend predicate from
```python
return row.data_source in {"trace", "memo"} or bool(row.declared_prompt_cache) or row.model_is_heterogeneous
```
to
```python
return (
    row.data_source in {"trace", "memo"}
    or bool(row.declared_prompt_cache)
    or row.model_is_heterogeneous
    or row.cacheable_data_source != "unavailable"
)
```

**Why**: after Step 2 lights up `cacheable_data_source="parameters"` for
greenfield rows where Tier 2 successfully fires, those rows currently
get hidden by the visibility filter (which only consults `data_source`).
Without this extension, the canary's success would be invisible in
greenfield mode.

**Drop**: `_DATA_SOURCE_DISPLAY`, `_data_source_display`, the inline
`src=` formatting in the row template.

**JSON impact**: zero. `render_json.py:222-260` consumes the dataclass
fields directly. Text-only refactor.

**Test re-classification** (corrects the original plan's Step 4):

Each of the 9 substring-format renderer tests gets ONE classification:

| Test (line) | Action | Reason |
|---|---|---|
| `test_per_call_row_renders_tokens_unmeasurable_for_opaque_prompt_with_no_data` (`:938-960`) | **Migrate** | substring `tokens=      ?` → cell-position `?` in input column |
| `test_per_call_row_keeps_tokens_for_opaque_prompt_with_cacheable_data` (`:963-985`) | **Migrate** | substring `tokens=      3` → cell-position `3` in input column |
| `test_text_per_call_inline_marker_includes_analysis_wide_warning_id` (`:1839-1862`) | **Migrate** | change row anchor from `"model=" in line` to node-id prefix |
| `test_per_call_row_renders_unresolved_when_model_empty` (`:2698-2713`) | **Migrate** | substring `model=<unresolved>` → cell-position `<unresolved>` in model column |
| `test_text_per_call_src_renders_as_confidence_labels` (`:3129-3163`) | **DELETE** | tests removed `src=high\|medium\|low` column |
| `test_text_per_call_src_passes_through_unknown_values` (`:3166-3184`) | **DELETE** | tests removed `src=` column unknown-value pass-through |
| `test_per_call_row_tokens_use_thousands_separator` (`:4408-4423`) | **Migrate** | substring `tokens=266,728` → cell-position with thousands |
| `test_per_call_row_cacheable_tokens_use_thousands_separator` (`:4425-4433`) | **Migrate** (split into 2) | now: one assertion on `cached_now` cell + one on `could_cache` cell, depending on row tier |
| `test_per_call_row_unmeasurable_cacheable_uses_seven_char_padding` (`:4436-4457`) | **Migrate, simplify** | padding-width is now widths-table-driven; assert only that `?` appears in `could_cache` cell |

**Add** 5 new mutation-contract tests:

- `test_per_call_row_renders_cached_now_for_tier_1_active`
- `test_per_call_row_renders_could_cache_for_tier_2_potential`
- `test_per_call_row_renders_em_dash_for_inactive_tier`
- `test_per_call_confidence_footer_lists_low_confidence_nodes`
- `test_per_call_confidence_footer_flags_batch_exemplar_projections`

---

### Step 2 — Batch-alias parameter propagation

**File**: `src/pflow/core/cache_analysis/analyze.py`

**Current state**: `_resolve_child_input_value` at `analyze.py:1291-1306`
takes `(value: Any, parent_ctx: AnalysisContext) -> Any | None`. The
single caller at `analyze.py:1281` passes
`getattr(edge, "parent_input_value", None)`. When `value` is `${item}`
or `${item.field}`, the function builds a shared store from parent's
parameters/memo, calls `TemplateResolver.resolve_template`, and returns
None when the template stays unresolved (because `item` is a runtime
iteration variable, not a parameter or node output).

**Target**: change the function signature to take the edge directly.
Detect the batch-alias case via the existing `edge.is_batch_alias_root`
predicate (`cross_workflow.py:84-98`). When detected, resolve the
parent's batch `items:` expression against parent context, take items[0]
(deterministic exemplar), bind into the shared store as
`{edge.parent_batch_alias: first_item}`, and retry resolution.

**Critical correction** vs the original sketch: the existing function
takes a `value` parameter; the new function takes the edge. The single
caller MUST be updated in lockstep.

**New signature**:

```python
def _resolve_child_input_value(
    edge: CrossWorkflowEdge,
    parent_ctx: AnalysisContext,
) -> Any | None:
    """Resolve a child workflow input value from the parent's analysis context.

    Returns the resolved Python value (post-template-resolution) or None
    when resolution is impossible (literal None, multi-ref string,
    unresolved template). For batch sub-workflow edges where the value
    expression roots on the parent's batch alias (e.g. ${item} or
    ${item.field}), resolves the parent's batch items: expression and
    binds items[0] as a single-iteration exemplar before delegating to
    TemplateResolver.
    """
    value = edge.parent_input_value
    if not isinstance(value, str):
        return _normalize_empty(value)
    refs = _extract_unique_refs(value)
    if not refs:
        return _normalize_empty(value)
    shared = _build_shared_store_for_refs(refs, parent_ctx)
    # Batch-alias unbinding: when expr roots on the parent edge's
    # batch alias, resolve items: from the parent IR and bind first
    # element. _per_call_scope_explainer documents the exemplar nature.
    if edge.is_batch_alias_root:
        first_item = _resolve_first_batch_item(edge, parent_ctx)
        if first_item is None:
            return None
        shared[edge.parent_batch_alias] = first_item
    try:
        resolved = TemplateResolver.resolve_template(value, shared)
    except Exception:
        logger.debug("failed to resolve child workflow input value", exc_info=True)
        return None
    if isinstance(resolved, str) and TEMPLATE_PATTERN.search(resolved):
        return None
    return resolved
```

**Caller update at `analyze.py:1281`** (must change in lockstep — the
plan's "Files modified" section reflects this):

```python
# OLD:
resolved = _resolve_child_input_value(getattr(edge, "parent_input_value", None), parent_ctx)
# NEW:
resolved = _resolve_child_input_value(edge, parent_ctx)
```

**New helper `_resolve_first_batch_item`** (module-level, near
`_resolve_child_input_value`):

```python
def _resolve_first_batch_item(
    edge: CrossWorkflowEdge,
    parent_ctx: AnalysisContext,
) -> Any | None:
    """Resolve the parent batch's `items:` expression and return [0].

    Returns None if items_expr is missing, doesn't resolve via parent
    params/memo, isn't a non-empty list, or raises during resolution.
    Honest unmeasurable: agent sees `?` in the per-call row, not a
    fabricated value.
    """
    # Inline lookup matches existing pattern at analyze.py:1331
    nodes_by_id = {
        n["id"]: n
        for n in parent_ctx.workflow_ir.get("nodes", [])
        if isinstance(n, dict) and "id" in n
    }
    parent_node = nodes_by_id.get(edge.parent_node_id)
    if parent_node is None:
        return None
    items_expr = parent_node.get("batch", {}).get("items")
    if items_expr is None:
        return None
    if isinstance(items_expr, list):
        return items_expr[0] if items_expr else None
    if isinstance(items_expr, str):
        try:
            resolved = TemplateResolver.resolve_template(
                items_expr,
                _build_shared_store_for_refs(
                    _extract_unique_refs(items_expr), parent_ctx
                ),
            )
        except Exception:
            logger.debug("failed to resolve batch items expression", exc_info=True)
            return None
        if isinstance(resolved, list) and resolved:
            return resolved[0]
    return None
```

**Why exception-handling matters** (review finding C-2): without the
try/except in `_resolve_first_batch_item`, a malformed batch items
expression crashes the analyzer for one bad parent. Mirroring the
existing pattern in `_resolve_child_input_value` (try/except + DEBUG
log + return None) keeps the analyzer running and surfaces honest
unmeasurable in the per-call row.

**Why `is_batch_alias_root` predicate** (review finding): the existing
property at `cross_workflow.py:84-98` is the canonical detection
mechanism for this case. The original sketch reinvented it as
`_expr_roots_on_alias`. Use the existing one.

**Why no `_find_node_by_id` helper**: three inline `nodes_by_id`
constructions exist (`analyze.py:1331, 1956, 2825`). Inline this
pattern directly instead of adding a fourth helper.

**Tests**:

- `test_resolve_child_input_value_propagates_via_batch_alias` —
  positive: batch sub-workflow edge with `parent_value_expr=${item.concept_brief}`,
  parent items resolves via memo, returns first-item.concept_brief.
- `test_resolve_child_input_value_returns_none_when_batch_items_unresolvable` —
  negative: items expression is `${runtime.thing}` not in memo, returns None.
- `test_resolve_child_input_value_handles_inline_static_batch_items` —
  positive: items is a literal list, picks items[0].
- `test_resolve_child_input_value_swallows_resolve_exceptions` —
  guard: malformed items_expr raises, function returns None (not
  crash).
- `test_resolve_child_input_value_via_edge_signature_back_compat` —
  caller-site test: confirms the caller in `_build_parameters_by_workflow`
  still works after signature change.
- `test_per_call_could_cache_populated_for_score_choruses_with_real_trace` —
  end-to-end canary; uses the lyrics-generator trace fixture; asserts
  that `score-choruses` row's `could_cache` cell shows a non-`?`
  value (Pitfall #19 defended — drives `analyze()` end-to-end with real
  trace + memo).

---

### Step 3 — Tests + new fixtures

(Renumbered from original Step 4. Step 1 + Step 2 above replace the
former Steps 1 + 2 + 3; Step 2 [former Step 3 batch-alias] is the new
load-bearing fix.)

**Migrate** the renderer tests per the table in Step 1 (5 migrate, 2
delete, 2 migrate-and-split).

**Add** the new tests listed in Steps 1-2 above. Total: ~12 new tests
(5 renderer + 6 batch-alias + 1 end-to-end canary).

**Pitfall #19**: every new end-to-end test must drive `analyze()` with
real state (real IR, real memo cache, real parameters, real trace if
applicable). NO synthetic candidate_subset construction. The
lyrics-generator trace fixture already exists; reuse it.

**Add 1 new test fixture** (NOT baseline — fixture for unit tests):

- A 2-LLM-node workflow with a batch sub-workflow + the parent passing
  `${item.field}` to the child. Validates batch-alias propagation
  independently of lyrics-generator complexity.

  Place: `tests/test_core/fixtures/cache_analysis_batch_alias.pflow.md`
  (matches existing fixture layout under `tests/`).

**Mutation contracts**: every new test docstring describes what
reverting the production change would break. Verify by stash-and-fail:

1. Stash the production fix.
2. Run target test → assert it fails with locked diagnostic.
3. Pop stash → assert it passes.

Apply to all ~12 new tests.

---

### Step 4 — Baseline regenerate

**Affected baselines** (per Investigator 8): 11 cases with per-call rows.

```
01-parser-errors/03-two-vars-in-chunk
01-parser-errors/09-prompt-body-shadows-cache
02-validator-errors/06-cache-content-below-min-predicted
02-validator-errors/07-unused-chunk
02-validator-errors/08-analyze-cache-surfaces-undeclared-name
03-analyze-cache-modes/03-steady-state-text
03-analyze-cache-modes/06-no-trace-autoload
03-analyze-cache-modes/08-all-rows-flag
10-live-recordings/05-gemini-lyrics-generator         ← canary
12-real-world-lyrics-generator/01-analyze-cache-text
12-real-world-lyrics-generator/03-analyze-cache-song-creator-text
```

**Workflow**:

1. After Steps 1-2 land + tests pass, run `./regenerate.sh` per affected
   case from `.taskmaster/tasks/task_159/baseline/`.
2. Eyeball each diff. Confirm:
   - Header + divider emitted ONCE per `## Per-call cache report`.
   - Column shape correct, widths uniform across multi-workflow groups.
   - `score-choruses` in lyrics-generator capture now shows
     `could_cache=158,704` (or similar non-`?`) — load-bearing canary.
   - `rewrite-emotional` row shows `cached_now=63,009 could_cache=—` —
     locks Step 1's Tier 1 column semantics.
   - Confidence footer emitted only when applicable.
3. Run `./verify.sh` — expect 65/65 pass.

**Strict-improvement audit** (output format):

For each drifted baseline, list every unique line change. Classify:

- **Additive**: new lines (column header, divider, footer when
  applicable). Expected.
- **Cosmetic**: same data, new shape (column rename, width change).
  Expected.
- **Behavioral**: data changed (e.g., `?` → `158,704` for
  score-choruses). Each must trace to a documented Step 1 or Step 2
  intentional change.

Reference example: see the 2026-05-08 Tier A bundle's strict-improvement
audit in the implementation progress log for output format.

**Drift outside the listed 11 cases is a bug to investigate, not
auto-regenerate.** It means renderer changed unexpected paths or new
per-call rows appeared (Step 2 success); confirm intentionality before
regenerating.

---

## Files modified

| File | Reason |
|---|---|
| `src/pflow/core/cache_analysis/render_text.py` | Step 1 (column refactor, table layout, confidence footer, `_row_has_real_data` predicate extension, `_per_call_scope_explainer` text update) |
| `src/pflow/core/cache_analysis/analyze.py` | Step 2 (`_resolve_child_input_value` signature change + batch-alias branch; new `_resolve_first_batch_item` helper; caller update at line 1281) |
| `tests/test_core/test_cache_analysis_renderers.py` | Step 3 (5 migrate + 2 delete + 2 split + 5 new mutation tests) |
| `tests/test_core/test_cache_analysis_analyze.py` | Step 3 (6 batch-alias propagation tests + 1 end-to-end canary) |
| `tests/test_core/fixtures/cache_analysis_batch_alias.pflow.md` | NEW unit-test fixture |
| `.taskmaster/tasks/task_159/baseline/*/expected-stdout.txt` | Step 4 (11 baselines regenerated) |

**Files NOT modified**:

- `src/pflow/core/cache_analysis/render_json.py` — text-only refactor.
- `src/pflow/core/cache_analysis/warning_catalog.py` — no catalog
  changes.
- `src/pflow/core/cache_analysis/token_estimation.py` — Tier 2 plumbing
  is already correct.
- `src/pflow/core/cache_analysis/cross_workflow.py` — walker output
  unchanged. (Cross-walker findings → per-call candidates was Step 2;
  retired to deferred PR.)

---

## Existing functions / utilities reused

- `CrossWorkflowEdge.is_batch_alias_root` (`cross_workflow.py:84-98`) —
  Step 2 detection.
- `TemplateResolver.resolve_template`, `extract_root_node_id`,
  `TEMPLATE_PATTERN` — Step 2 resolution.
- `_build_shared_store_for_refs` — Step 2 augmentation point.
- `_extract_unique_refs`, `_normalize_empty` — existing helpers in
  `_resolve_child_input_value`'s body.
- `AnalysisContext.resolve_ref_value` (`context.py:150-203`) — already
  consumed by Tier 2; no changes.
- `nodes_by_id` inline pattern (matches `analyze.py:1331, 1956, 2825`).
- Existing try/except + `logger.debug` pattern in
  `_resolve_child_input_value` — mirrored in `_resolve_first_batch_item`.

---

## Verification

### Unit and integration tests

```bash
# Targeted suites
uv run pytest tests/test_core/test_cache_analysis_renderers.py -x
uv run pytest tests/test_core/test_cache_analysis_analyze.py -x
uv run pytest tests/test_core/test_cache_analysis_per_id_emission.py -x
uv run pytest tests/test_core/test_cache_analysis_token_estimation.py -x

# Full default suite
make test

# Quality gates
make check
```

Expected: 6,449+ pass (current baseline) + ~12 new tests; zero
regressions.

### Baseline harness

```bash
cd .taskmaster/tasks/task_159/baseline
./regenerate.sh    # regen affected cases (11 listed above)
./verify.sh        # 65/65 pass
```

If `verify.sh` reports drift in baselines OUTSIDE the 11 listed,
**investigate before regenerating**. That signals the renderer affected
an unexpected code path.

### End-to-end smoke (the canary)

Use the canary's actual command (corrected from the original plan
which mismatched lyrics-generator's declared inputs):

```bash
# From .taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/command.sh
SOURCE="https://www.youtube.com/watch?v=..."  # use the real value from command.sh
uv run pflow analyze-cache \
  .taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md \
  --from-trace .taskmaster/tasks/task_159/baseline/_shared/fixtures/live-gemini-lyrics-generator.trace.json \
  sources="[\"$SOURCE\"]"
```

Read `command.sh` directly for the exact invocation; do not invent
parameter values that aren't declared in the workflow's `## Inputs:`.

**Verify in output**:

- `## Per-call cache report` section emits header + divider lines ONCE.
- Column widths uniform across all `### file` group sections.
- `score-choruses` row has `could_cache=158,704` (or similar non-`?`).
- `rewrite-emotional` row has `cached_now=63,009` and `could_cache=—`.
- `write-lyrics`-style rows in song-creator child invocation show
  `model=<unresolved>` consistently (where applicable).
- Confidence footer emitted only when ≥1 row's input-data_source is
  below `high` OR ≥1 row has a batch-exemplar cacheable projection.
- Notes column correctly consolidates `opaque-prompt`, `observed=...`,
  `[unexecuted]`, `batch_items=N`.

### Greenfield smoke (validates `_row_has_real_data` extension)

Run the canary command WITHOUT `--from-trace` against a workflow with
declared `## Inputs` matching CLI parameters. Verify:

- Per-call rows are NOT hidden when `cacheable_data_source != "unavailable"`.
- Greenfield batch-sub-workflow descendants surface `could_cache` values
  via Step 2's batch-alias propagation.

### Mutation contracts (the discipline)

For each new test, document in the test docstring what reverting the
production change would break. Verify by stash-and-fail:

1. Stash the production fix.
2. Run the target test → assert it fails with a locked diagnostic.
3. Pop the stash → assert it passes.

This is the project's established Pitfall #19 defense. Apply to all
~12 new tests.

---

## Out of scope (deferred PR)

The cross-workflow walker → per-call candidate plumbing (was Step 2 in
the original plan) is retired to:

`.taskmaster/tasks/task_159/implementation/handoffs/task-159-partial-declaration-detection-handoff.md`

That doc captures:
- Why the cross-workflow plumbing was deferred (sub-path overlap dedup
  risk; cost-projection contradiction with `_per_call_rerun_cost`;
  semantic conflation between "would cache today" and "would cache
  after declaration + prompt edit").
- Three options for the partial-declaration detection ID (extend
  existing / new ID / per-node ID), with hard constraints (Diagnostic
  dedup hash excludes context).
- New baseline mandatory.
- DD#29 review needed for new catalog ID (if Option B/C).

The deferred handoff was authored before this revision; the implementer
of that PR should also add the cross-workflow → per-call candidate
plumbing concern as part of their scope (since it solves the same
underlying defect surface).

---

## Honest confidence

| Step | Confidence | Why |
|---|---|---|
| Step 1 (renderer + visibility filter + footer) | 92% | Source-grounded by Investigator 8 + plan reviewer; no end-to-end tests broken; JSON decoupled; em-dash semantic documented |
| Step 2 (batch-alias propagation) | 85% | Source-grounded by Investigator 5; signature mismatch fixed; exception policy explicit; reuses `is_batch_alias_root`; first-item-exemplar is principled |
| Combined LOC ~180 | 85% | Step 1 ~120 LOC; Step 2 ~50 LOC + caller update; smaller than original plan because Step 2 [cross-workflow plumbing] dropped |
| Baseline drift contained to 11 cases | 95% | Investigator 8 enumerated; canary case is lyrics-generator |
| Zero regression on existing tests | 90% | No direct unit tests of removed functionality; test impact contained |
| Canary `score-choruses` populates after fix | 80% | Depends on memo populating chorus-chooser's `wf_ctx.parameters` after Step 2's batch-alias resolution; verify with strict-improvement audit |

**Risk callout**: if the strict-improvement audit shows
`score-choruses` STILL displaying `?` after Step 2 lands, the
hypothesis "intra-walker provides candidates AND Step 2 unblocks Tier 2
resolution" is wrong — STOP and re-investigate. Possible alternate
causes: chorus-chooser's `### concept` input declaration not detected;
intra-walker's ≥2-node share rule not satisfied for `concept.title` /
`concept.core_idea`; trace fixture missing relevant memo data. Do not
ship without the canary number populating.

---

## Key revisions vs original plan (for the implementer)

For agents who read the original plan first: this revision differs from
the original on these points (each grounded in a 4-agent review finding):

1. **Step 2 (cross-workflow → per-call candidate plumbing) DROPPED**.
   Moved to deferred partial-declaration handoff. Resolves: sub-path
   double-count (C2), JSON shape drift (C3), cost-projection contradiction
   (C4), inline-static overwrite (C9), semantic conflation (C10),
   greenfield-gate asymmetry (W4), unexecuted-branch stale-memo (W6),
   recommendation savings shift (W7), filter duplication (S2).
2. **Step 2 signature corrected**: takes `edge`, not `value`. Caller updated.
3. **Step 2 reuses `edge.is_batch_alias_root`**: drops invented
   `_expr_roots_on_alias` helper.
4. **Step 2 exception policy explicit**: try/except + DEBUG log in
   `_resolve_first_batch_item`, mirroring existing pattern.
5. **Column header GLOBAL**: emitted once per `## Per-call cache report`,
   not per `### file` group. Single-workflow mode handled uniformly.
6. **`_row_has_real_data` predicate extended**: visibility filter consults
   `cacheable_data_source` so greenfield Tier 2 firings aren't hidden.
7. **Confidence footer reads BOTH** `data_source` AND
   `cacheable_data_source` (with `is_batch=True` for exemplar
   projections).
8. **Test classification corrected**: 9 tests split into migrate (5) /
   delete (2) / migrate-and-split (2).
9. **Smoke command corrected** to match canary `command.sh`.
10. **Em-dash semantic documented** in `_per_call_scope_explainer` text.
11. **`_find_node_by_id` helper NOT added**: inline `nodes_by_id` pattern
    matches existing precedent at `analyze.py:1331`.
12. **Strict-improvement audit format specified**: additive / cosmetic /
    behavioral classification with reference to Tier A bundle precedent.
