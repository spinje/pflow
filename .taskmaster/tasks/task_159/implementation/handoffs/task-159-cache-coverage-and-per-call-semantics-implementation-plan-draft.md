# Task 159 Handoff: Cache Coverage + Per-Call Semantics Plan

> **Status**: Planning handoff, no production code changed here.
> **Authored**: 2026-05-10 after reading the two deferred research handoffs,
> `task-review.md`, the last 1000 lines of `implementation-progress-log.md`,
> current source, current tests, and three full-context verification agents.
>
> **Purpose**: Give the next implementation agent a source-verified plan for
> solving the remaining Task 159 cache-analysis issues in at most two coherent
> passes, while prioritizing the simplicity of the final code over the ease of
> a quick patch.

---

## Executive summary

The remaining issues are not best understood as separate renderer bugs. The
root problem is that the analyzer lacks an explicit, honest model of **cache
coverage per LLM node**:

- what refs the prompt sends,
- what cache items the workflow declares,
- what each node includes in `prompt_cache:`,
- which missing items are shared enough to matter,
- whether a recommendation works by declaration alone or also requires prompt
  cleanup / prompt-shape edits,
- whether a per-call row number means actual cached tokens, declared-cache
  projection, or undeclared opportunity.

Today those meanings are split across `_detect_candidate_subsets`,
`estimate_cacheable_tokens`, `_SubWorkflowCacheCandidate`, `PerCallRow`, and
renderer interpretation. That split is why the two research files overlap but
do not collapse into one tiny fix.

### Recommended implementation split

**Pass 1 - semantic foundation + unit consistency**

1. Add explicit per-row fields for actual/declared cache vs projected
   opportunity, while keeping `cacheable_tokens_estimated` as a legacy
   compatibility field.
2. Fix analyze/render row visibility predicate parity.
3. Thread `observed_call_count` into Tier 2 chunk estimation so memo/parameter
   chunk projections use the same cohort scope as trace input tokens.

**Pass 2 - cache coverage detection**

1. Add a small explicit cache-coverage helper for declared workflows.
2. Emit a new per-node catalog diagnostic for incomplete `prompt_cache:`
   coverage.
3. Keep cross-workflow root/subpath opportunities primarily diagnostic unless
   the row model can honestly label "requires prompt edit".
4. Optionally wire only declaration-alone opportunities into row `could_cache`
   fields.

Do **not** broaden non-batch repeated-prefix projection by dropping the `batch:`
gate. That looks simple but is not correct; it requires a real dynamic-boundary
model. See "Deferred / explicit non-goals".

---

## Source of truth and trust boundary

### Files read directly

- `.taskmaster/tasks/task_159/implementation/handoffs/task-159-partial-declaration-detection-handoff.md`
- `.taskmaster/tasks/task_159/implementation/handoffs/select-chorus-and-tier2-scope-gap-handoff.md`
- `.taskmaster/tasks/task_159/task-review.md`
- Last 1000 lines of `.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`
- `src/pflow/core/cache_analysis/analyze.py`
- `src/pflow/core/cache_analysis/token_estimation.py`
- `src/pflow/core/cache_analysis/cost_estimation.py`
- `src/pflow/core/cache_analysis/render_text.py`
- `src/pflow/core/cache_analysis/render_json.py`
- `src/pflow/core/cache_analysis/warning_catalog.py`
- `src/pflow/core/diagnostic.py`
- `src/pflow/core/workflow/data_flow.py`
- `src/pflow/core/markdown_parser.py`
- selected cache-analysis tests and baseline harness docs

### Parallel verification performed

Three full-context verification agents checked:

1. `PerCallRow` data-model consumers, cost/render/json compatibility, and
   Tier 2 `observed_call_count` threading.
2. Partial-declaration detection details: cache item `name` vs `var`,
   `prompt_cache:` validation/order, diagnostic dedup/catalog implications,
   and cross-workflow root/subpath semantics.
3. Test/baseline plan, catalog count/per-ID coverage requirements, and sandbox
   verification commands.

Agents also ran focused tests using the sandbox-safe pattern:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest ...
```

Focused subsets reported:

- `6 passed` for current catalog/prefix/Tier2/render locks.
- `7 passed` for row model / prefix / cost-isolation locks.
- `9 passed` for brownfield/cross-workflow/catalog/dedup locks.

### Verified

- Partial-declaration detection is missing.
- Declared rows ignore `candidate_subset` today because token estimation uses
  `declared_subset or candidate_subset`.
- Cross-workflow child consumer data exists but is constructed after per-call
  rows and is used only for diagnostics.
- The old handoff's cost-projection contradiction is already fixed by gating
  rerun cost on `declared_prompt_cache`.
- Tier 2 chunk projections are one-call values next to cohort trace input
  tokens.
- Analyzer and renderer use different row-visibility predicates.
- `prompt_cache:` suggestions must use cache item `name`, not necessarily the
  prompt ref, while token estimation/rendering must resolve the item's `var`.
- `prompt_cache:` order is strict declaration order.
- Adding a cached chunk whose body remains inline can trigger duplicate/shadow
  diagnostics, so prompt cleanup must be included in partial-declaration
  advice.
- Diagnostic identity ignores context, so same severity/source/node/id
  collapses even if context differs.

### Not verified

- The old empirical claim that zero current baselines exercise partial
  declaration. We did not run the full 65-baseline sweep for this planning
  handoff.
- Full baseline drift. We identified likely drift surfaces but did not run the
  full baseline harness.
- A robust non-batch repeated-prefix algorithm on the live lyrics trace. The
  canonical fixture trims `template_resolutions` and `llm_prompt` for large
  calls, which makes trace-derived longest-common-prefix verification
  unavailable from that fixture as-is.
- Whether static batch trace rows already have an input/cost invocation-count
  ambiguity. One verification agent flagged this as a possible adjacent issue:
  trace input may already be cohort-summed while `_invocation_count()` can
  multiply for static batch rows. Audit before changing cost math broadly.

---

## Current behavior, with file-backed claims

### 1. Partial-declaration blind spot

`_detect_candidate_subsets()` is greenfield-only. It returns `{}` when the
workflow has any `## Cache` items, before looking at per-node `prompt_cache:`.

Source:

- `src/pflow/core/cache_analysis/analyze.py::_detect_candidate_subsets`

Why this matters:

```text
## Cache
article = ${article}
rubric = ${rubric}

node A prompt: ${article} ${rubric}
node A prompt_cache: [article]

node B prompt: ${article} ${rubric}
node B prompt_cache: [article, rubric]
```

Today the analyzer emits no advisory that node A omitted `rubric`.

Important: simply relaxing the gate does **not** fix declared rows. In
`estimate_cacheable_tokens()`, Tier 2 uses:

```python
chunks = declared_subset or candidate_subset
```

So a partially declared node still ignores candidates as long as it has any
declared subset.

Source:

- `src/pflow/core/cache_analysis/token_estimation.py::estimate_cacheable_tokens`

### 2. Cross-workflow child consumer data exists, but too late

`_SubWorkflowCacheCandidate` includes `child_node_ids`, built from
`_collect_llm_nodes_referencing_path()`. That data is used by
`_emit_sub_workflow_cache_findings()` to produce
`cache.sub-workflow-cache-undeclared`.

But per-call rows are built earlier in `analyze()` via
`_build_per_call_rows_and_warnings()`, which only calls
`_detect_candidate_subsets(workflow_ir)` for each workflow. There is no shared
coverage phase.

Sources:

- `src/pflow/core/cache_analysis/analyze.py::_build_per_call_rows_and_warnings`
- `src/pflow/core/cache_analysis/analyze.py::_SubWorkflowCacheCandidate`
- `src/pflow/core/cache_analysis/analyze.py::_build_cross_workflow_findings`
- `src/pflow/core/cache_analysis/analyze.py::_emit_sub_workflow_cache_findings`

### 3. Cross-workflow root/subpath semantics are not row-safe

The cross-workflow matcher intentionally treats a prompt ref like
`${concept.title}` as a consumer of child input `concept`.

This is correct for a diagnostic: "this child workflow uses the incoming
concept input in multiple LLM nodes."

It is not automatically correct for a per-call row number. If a row's prompt
only literally sends `${concept.title}`, injecting a `concept` root candidate
would estimate the full object as cacheable. That changes `could_cache` from
"declare what the prompt already sends" to "add/cache a root object and likely
edit prompt/cache shape."

Source:

- `src/pflow/core/cache_analysis/analyze.py::_collect_llm_nodes_referencing_path`
- `src/pflow/core/cache_analysis/token_estimation.py::_sum_resolved_chunk_tokens`

Do not hide this semantic difference behind the same `could_cache` number.

### 4. Cost-projection contradiction is already fixed

Older handoff text warns that populating undeclared rows'
`cacheable_tokens_estimated` would shrink rerun cost while savings aggregates
skip undeclared rows.

Current code already gates `_per_call_rerun_cost()`:

```python
cacheable = row.cacheable_tokens_estimated or 0 if row.declared_prompt_cache else 0
```

Source:

- `src/pflow/core/cache_analysis/cost_estimation.py::_per_call_rerun_cost`

Existing test:

- `tests/test_core/test_cache_analysis_analyze.py::test_batch_prefix_projection_does_not_ripple_into_rerun_cost_for_undeclared_rows`

Keep this invariant. Future opportunity fields must not be read by cost
projection unless they represent actual declared-cache content.

### 5. Tier 2 chunk scope mismatch

Trace input/cache telemetry is aggregated across calls in
`_aggregate_trace_llm_calls()`. `observed_call_count` is computed in
`_build_per_call_row()`.

But `estimate_cacheable_tokens()` has no call-count parameter and
`_sum_resolved_chunk_tokens()` sums chunk refs once.

Result: a repeated row can show cohort input beside one-call `could_cache`.

Sources:

- `src/pflow/core/cache_analysis/analyze.py::_aggregate_trace_llm_calls`
- `src/pflow/core/cache_analysis/analyze.py::_build_per_call_row`
- `src/pflow/core/cache_analysis/token_estimation.py::estimate_cacheable_tokens`
- `src/pflow/core/cache_analysis/token_estimation.py::_sum_resolved_chunk_tokens`

### 6. Analyze/render visibility predicate mismatch

Renderer considers any non-`unavailable` `cacheable_data_source` real data.
Analyze-time note logic does not.

Sources:

- `src/pflow/core/cache_analysis/render_text.py::_row_has_real_data`
- `src/pflow/core/cache_analysis/analyze.py::_row_has_real_data_in_analyze`

This can cause JSON/text notes to say the per-call report is hidden even when
rows have parameter-backed cacheable evidence.

### 7. Cache item name vs var

Parser-created cache items currently have `name == var`; this is locked.

However, validation and runtime semantics are distinct:

- `prompt_cache:` entries refer to cache item `name`.
- Runtime cache rendering resolves the cache item's `var`.

Sources:

- `src/pflow/core/markdown_parser.py` around cache item parsing
- `src/pflow/core/workflow/data_flow.py` cache validation
- `src/pflow/nodes/llm/llm.py` cache render prep

Do not write code that assumes `name == var` for all IRs. Tests use direct IRs
and can represent `name != var`.

### 8. Diagnostic dedup

Diagnostic identity is:

```python
(severity, source, node_id, id or message)
```

Context is ignored. If a new diagnostic emits one same-ID warning per missing
chunk for the same node, only one may survive dedup. Group all missing chunks
into one diagnostic per node.

Source:

- `src/pflow/core/diagnostic.py::Diagnostic.__eq__`
- `src/pflow/core/diagnostic.py::Diagnostic.__hash__`

---

## Problem definition

We are solving four related problems:

1. **Partial-declaration detection**
   Declared workflows can omit shared cache items from some nodes'
   `prompt_cache:` lists. The analyzer is silent.

2. **Cross-workflow coverage visibility**
   The analyzer can detect child workflows where an input is reused by
   multiple LLM nodes, but that data is not available as a clean row
   opportunity model.

3. **Per-call row semantic overload**
   `cacheable_tokens_estimated` means different things depending on source:
   actual cache evidence, declared-cache projection, undeclared opportunity, or
   batch-prefix projection. This blocks safe display of "cached now" and
   "could additionally cache" on the same row.

4. **Repeated-call scope mismatch**
   Tier 2 chunk estimates are one-call values while input tokens may be
   cohort totals. `select-chorus`-class rows also miss non-batch repeated
   static-prefix opportunities, but that requires a separate dynamic-boundary
   strategy.

---

## Design goal

Optimize for final code that a future agent can understand and safely extend:

- one row data model that distinguishes current declared cache from potential
  opportunity;
- one coverage helper that explains declared-workflow omissions;
- no hidden root/subpath inflation in row ratios;
- catalog-backed diagnostics with stable IDs and production-shape tests;
- honest `None` / `"unavailable"` when evidence is missing.

Avoid the tempting patch:

- relaxing `_detect_candidate_subsets()` globally,
- appending cross-workflow root candidates to candidate lists,
- overloading `cacheable_tokens_estimated`,
- reusing `cache.shared-context-undeclared` for a different action,
- dropping the prefix-projection `batch:` gate without a boundary model.

Those changes look small but create harder final code.

---

## Pass 1: Semantic foundation + unit consistency

### Goal

Make row semantics explicit before adding partial-declaration opportunities.

### Files likely touched

- `src/pflow/core/cache_analysis/analyze.py`
- `src/pflow/core/cache_analysis/token_estimation.py`
- `src/pflow/core/cache_analysis/render_text.py`
- `src/pflow/core/cache_analysis/render_json.py`
- `src/pflow/core/cache_analysis/cost_estimation.py`
- `src/pflow/core/cache_analysis/__init__.py` if JSON format bumps
- tests under `tests/test_core/`

### 1. Add explicit row fields

Keep `cacheable_tokens_estimated` and `cacheable_data_source` as legacy
compatibility fields during migration. They are still emitted in JSON and read
by tests/consumers.

Add fields to `PerCallRow`, names to settle during implementation:

```python
declared_cache_tokens_estimated: int | None = None
declared_cache_data_source: str = "unavailable"
could_cache_tokens_estimated: int | None = None
could_cache_data_source: str = "unavailable"
could_cache_requires_prompt_edit: bool = False
```

Why `declared_cache_tokens_estimated` instead of only
`cached_now_tokens_estimated`:

- trace source means cache actually fired this run;
- memo/parameters may estimate declared cache content when a declared cache did
  not fire or no trace exists;
- cost projection needs "declared cache content", not "actual hit this run" and
  not "additional opportunity".

Compatibility rule:

- `cacheable_tokens_estimated` remains the old display-compatible value for now.
- New renderer cells prefer explicit fields and fall back to legacy when new
  fields are `None`.
- JSON gains additive fields. Prefer bumping `JSON_FORMAT_VERSION` from `4.1`
  to `4.2` because machine consumers need a clear signal that the old field is
  now superseded by more precise fields.

### 2. Populate fields in `_build_per_call_row()`

Current `estimate_cacheable_tokens()` returns one `(tokens, source)` pair.
For Pass 1, keep that function but classify its output:

- If `cacheable_source == "trace"` and `declared_subset` exists:
  - `declared_cache_tokens_estimated = tokens`
  - text `cached_now` displays this.
- If `declared_subset` exists and source is `memo` / `parameters`:
  - `declared_cache_tokens_estimated = tokens`
  - text may still show this as declared-cache projection, but not as "actual
    provider hit". If current text cannot express this cleanly, keep the old
    behavior and document it in row source.
- If no declared subset and source is `memo` / `parameters` / `batch_prefix`:
  - `could_cache_tokens_estimated = tokens`
  - text `could_cache` displays this.
- Future partial-declaration opportunities go into `could_cache_*`, never into
  declared fields unless the workflow already declares them for that node.

### 3. Update renderer cells

`render_text._cell_cached_now()`:

- Prefer `declared_cache_tokens_estimated` only when source is trace actual
  cache evidence.
- Fallback to legacy behavior for compatibility during migration.

`render_text._cell_could_cache()`:

- Prefer `could_cache_tokens_estimated`.
- If unavailable, fallback to legacy projection behavior.
- If `could_cache_requires_prompt_edit` is true, do **not** silently render a
  plain number unless the notes/footer names the required edit.

Potential notes wording:

```text
requires prompt/cache cleanup
```

Keep it terse; no instructional essay in the table.

### 4. Update JSON additively

Add fields in `_per_call_to_dict()`:

```json
"declared_cache_tokens_estimated": ...,
"declared_cache_data_source": "...",
"could_cache_tokens_estimated": ...,
"could_cache_data_source": "...",
"could_cache_requires_prompt_edit": false
```

Keep old fields:

```json
"cacheable_tokens_estimated": ...,
"cacheable_data_source": "..."
```

Document in `__init__.py` JSON version history if bumped.

### 5. Cost estimation must read declared-cache content only

Cost code currently reads `row.cacheable_tokens_estimated` in several places.
After explicit fields exist:

- Use `row.declared_cache_tokens_estimated` when present.
- Fallback to `row.cacheable_tokens_estimated` only for compatibility.
- Never use `row.could_cache_tokens_estimated`.

Touchpoints:

- `cost_estimation.py::_per_call_rerun_cost`
- `_aggregate_with_cache_projection`
- `_aggregate_first_run_savings`
- `_aggregate_rerun_savings`

Preserve existing invariant:

- undeclared opportunities do not shrink rerun cost until declared.

### 6. Fix Tier 2 call-count multiplication

Add keyword-only/default parameter:

```python
def estimate_cacheable_tokens(..., observed_call_count: int = 1) -> tuple[int | None, str]:
```

Pass from `_build_per_call_row()`:

```python
observed_call_count=max(1, observed_call_count)
```

Add to `_sum_resolved_chunk_tokens()`:

```python
call_count: int = 1
```

Multiply only Tier 2 memo/parameters path:

```python
return total * max(1, call_count)
```

Do **not** multiply Tier 1 trace path. Trace already reports aggregated
`cache_creation + cache_read` across calls.

### 7. Fix analyze/render visibility parity

Update `_row_has_real_data_in_analyze()` to match renderer semantics:

```python
return (
    row.data_source in {"trace", "memo"}
    or bool(row.declared_prompt_cache)
    or row.model_is_heterogeneous
    or row.cacheable_data_source != "unavailable"
    or row.could_cache_data_source != "unavailable"  # if new field added
)
```

This removes stale "Per-call cache report hidden" notes when parameter-backed
cacheable evidence exists.

### Pass 1 tests

Add or update:

- `test_analyze_row_visibility_matches_renderer_for_parameter_cacheable_source`
- `test_cacheable_tier_2_multiplies_resolved_chunks_by_observed_call_count`
- `test_cacheable_tier_2_trace_path_does_not_multiply_by_call_count`
- `test_cacheable_tier_2_partial_resolution_still_unavailable_with_call_count`
- renderer tests for explicit fields:
  - actual trace cache -> `cached_now`
  - undeclared projection -> `could_cache`
  - both fields can exist on one row without cost using `could_cache`
- cost test:
  - `could_cache_tokens_estimated` must not reduce rerun cost unless declared

### Pass 1 likely baseline drift

- `03-analyze-cache-modes/02-greenfield-json` if visibility note changes.
- `03-analyze-cache-modes/03-steady-state-text`
- `03-analyze-cache-modes/04-steady-state-json`
- live lyrics-generator rows if Tier 2 multiplication changes visible values.

---

## Pass 2: Cache coverage detection

### Goal

Detect declared-workflow omissions and provide actionable diagnostics without
overloading greenfield suggested-block semantics or row cost semantics.

### Files likely touched

- `src/pflow/core/cache_analysis/analyze.py`
- `src/pflow/core/cache_analysis/warning_catalog.py`
- `src/pflow/core/cache_analysis/view_helpers.py` if recommended-action
  ordering/counting needs adjustment
- `src/pflow/core/cache_analysis/render_json.py`
- `src/pflow/core/cache_analysis/render_text.py`
- `src/pflow/guide/features/caching.md`
- `src/pflow/core/cache_analysis/CLAUDE.md`
- tests under `tests/test_core/`
- baseline warning-catalog cases

### 1. Add an internal opportunity model

Keep it small and local to analyzer. Suggested shape:

```python
@dataclass(frozen=True)
class CacheCoverageOpportunity:
    workflow_path: str | None
    node_id: str
    missing_names: tuple[str, ...]
    missing_vars: tuple[str, ...]
    corrected_prompt_cache: tuple[str, ...]
    prompt_body_cleanup: tuple[str, ...]
    source: str  # "brownfield_partial" | "cross_workflow_child_input"
    row_projectable: bool
    requires_prompt_shape_change: bool
```

Do not make this public API unless needed. The goal is to give analyzer code
a crisp internal language, not a framework.

### 2. Brownfield partial-declaration algorithm

Add helper, name flexible:

```python
def _detect_prompt_cache_coverage_opportunities(
    workflow_ir: dict[str, Any],
    workflow_path: str | None,
) -> list[CacheCoverageOpportunity]:
```

Algorithm:

1. Extract ordered cache items from `workflow_ir["cache"]["items"]`.
2. Build:
   - `items_by_name: dict[str, item]`
   - `name_order: list[str]`
   - `var_to_name: dict[str, str]`
3. Walk prompt refs with `_collect_llm_template_references(workflow_ir)`.
4. Keep only shared refs: refs used by at least two LLM nodes.
5. For each LLM node:
   - read current `prompt_cache` as list; skip invalid shape defensively
     because validation will separately report structural errors;
   - identify shared prompt refs whose exact ref equals a cache item `var`;
   - convert matching vars to item names;
   - `missing_names = used_shared_names - current_prompt_cache`;
   - if empty, no opportunity.
6. `corrected_prompt_cache` must be declaration-order-safe:

```python
corrected = tuple(
    name for name in name_order
    if name in set(current_prompt_cache) | set(missing_names)
)
```

7. `prompt_body_cleanup` should include the refs to remove or rewrite from the
   prompt to avoid prompt-body duplicate/shadow diagnostics after the user
   adds them to `prompt_cache:`.

Important matching rule:

- Match prompt refs to cache item `var`.
- Suggest `prompt_cache:` entries by cache item `name`.
- Estimate tokens from `var` or rendered cache item semantics.

Do not assume `name == var`, even though markdown parser-created items
currently lock equality.

### 3. Diagnostic ID

Add a new catalog ID. Recommended:

```text
cache.prompt-cache-incomplete
```

Rationale:

- clearer than `cache.partial-declaration-detected`;
- speaks in the surface language the user edits: `prompt_cache`;
- avoids reusing `cache.shared-context-undeclared`, whose contract is
  "paste a suggested ## Cache block".

Severity/category:

- `Severity.INFO`
- `source="cache_analyzer"`
- cache advisory category
- priority near `cache.shared-context-undeclared` and
  `cache.sub-workflow-cache-undeclared`

Required context:

```python
("affected_workflow", str),
("node_id", str),
("missing_chunks", list),
("missing_chunks_csv", str),
("corrected_prompt_cache", list),
("corrected_prompt_cache_inline", str),
("prompt_body_cleanup", list),
("prompt_body_cleanup_csv", str),
("savings_usd", float),  # nullable if included
("below_threshold_clause", str),  # optional empty string pattern
```

Keep one diagnostic per node, grouping all missing chunks. Do not emit one per
chunk because diagnostic identity ignores context.

Suggested text direction:

```text
Prompt cache incomplete - extend `node_id` prompt_cache with rubric

`node_id` uses shared cache chunk(s) rubric in its prompt, but its
prompt_cache list omits them. Set prompt_cache to [article, rubric].
Also remove or rewrite inline prompt refs: ${rubric}.
```

Keep this concise; agents need the edit, not a tutorial.

### 4. Threshold semantics

Use the cross-workflow precedent, not greenfield suppression:

- emit the diagnostic even if below threshold;
- set savings to `None`;
- include a below-threshold clause/note.

Why:

- this is not a paste-ready whole-block suggestion;
- the agent still needs to know the declared workflow's coverage is incomplete;
- suppressing would recreate silence.

Reuse or mirror `_below_threshold_clause()` if the token/model evidence is
available.

### 5. Where to call it

Call after rows are built, because rows carry model/token source information
needed for threshold/savings estimates. Good insertion point:

- after `_populate_suggested_blocks()`,
- before summary/recommended-action derivation,
- before `warnings` are filtered for trace coverage.

It should run for every workflow in `cw_result.irs_by_workflow`, not only root,
because child workflows can have their own declared cache blocks.

However, be careful with `node_id` dedup across workflows:

- Diagnostic identity ignores workflow path.
- Same node ID in two workflows with same new ID could dedup if both warnings
  have same severity/source/node/id.

Mitigation options:

1. Include workflow basename/path in `node_id`, e.g. `node_id=f"{workflow_path}:{node_id}"`.
   Bad for row matching.
2. Emit at workflow-level (`node_id=None`) and only one per workflow.
   Bad for row/action specificity.
3. Add one diagnostic per node and rely on normal analyzer flow not producing
   duplicate same-node IDs across workflows frequently.
   Simpler, but not perfect.
4. Change diagnostic identity. Do **not** do this for Task 159; it is
   cross-cutting.

Recommendation: use per-node `node_id` for row/action locality and include
`affected_workflow` in context. Add a test with same node ID in parent/child if
this risk appears in fixtures. If dedup actually collapses real findings, the
least invasive follow-up is to make the new diagnostic workflow-level and group
nodes in context.

### 6. Cross-workflow coverage integration

Keep existing `cache.sub-workflow-cache-undeclared` as the primary action for
child input declarations.

Do not inject root-level cross-workflow candidates into row `could_cache`
unless:

- the prompt literally sends the same ref that would be declared, or
- the row field explicitly sets `could_cache_requires_prompt_edit=True` and
  renderer/JSON disclose this.

Rule of thumb:

- `${concept}` in prompt and candidate `concept`: row-projectable.
- `${concept.title}` in prompt and candidate `concept`: diagnostic only, or
  row-projectable with `requires_prompt_shape_change=True`.

The simplest final code for Pass 2:

- implement brownfield partial-declaration diagnostics;
- leave cross-workflow row numeric plumbing out unless the row data model from
  Pass 1 has a clear `requires_prompt_shape_change` display;
- keep existing cross-workflow recommendation unchanged.

This still solves the core user question in the partial-declaration handoff.
It does not pretend cross-workflow root candidates are row-safe.

### Pass 2 tests

Add production-shape tests, not synthetic dataclass-only tests.

Minimum:

1. `test_partial_prompt_cache_declaration_emits_per_node_coverage_advisory`
   - workflow has `## Cache` chunks `article`, `rubric`;
   - two LLM prompts use both;
   - one node declares only `[article]`;
   - expect `cache.prompt-cache-incomplete`;
   - expect no `cache.shared-context-undeclared`.

2. `test_partial_prompt_cache_declaration_groups_missing_chunks_per_node`
   - one node omits two chunks;
   - exactly one diagnostic for that node;
   - context lists both chunks.

3. `test_partial_prompt_cache_suggestion_preserves_cache_order`
   - cache order `[a, b, c]`;
   - node has `[a]`, missing `c`;
   - corrected list `[a, c]`;
   - node has `[b]`, missing `a`, corrected `[a, b]`.

4. `test_partial_prompt_cache_matches_item_var_but_suggests_item_name`
   - direct IR with `name != var`;
   - prompt uses var;
   - suggestion uses name.

5. `test_partial_prompt_cache_includes_prompt_body_cleanup`
   - ensure context/suggestion tells agent to remove/rewrite inline refs.

6. `test_partial_prompt_cache_below_threshold_keeps_advisory_without_savings`
   - below threshold;
   - diagnostic still exists;
   - savings is null/None or note names threshold.

7. `test_partial_prompt_cache_does_not_reduce_rerun_cost_until_declared`
   - row opportunity exists;
   - cost projection unchanged until `prompt_cache:` includes missing item.

8. Cross-workflow guard:
   - child prompt uses `${concept.title}`;
   - cross-workflow candidate is `concept`;
   - no plain row `could_cache` inflation unless `requires_prompt_shape_change`
     is exposed.

Catalog tests:

- update catalog count from 21 to 22;
- add per-ID coverage entry;
- add production emission test in `test_cache_analysis_per_id_emission.py`;
- add warning-catalog constructor test.

### Pass 2 baselines

Add one warning-catalog baseline:

```text
.taskmaster/tasks/task_159/baseline/04-warning-catalog/21-cache.prompt-cache-incomplete/
```

Include:

- `README.md`
- `workflow.pflow.md`
- `command.sh`
- expected stdout/stderr/JSON as per harness convention

Likely existing baseline drift:

- `04-warning-catalog/04-cache.shared-context-undeclared`
- `04-warning-catalog/05-cache.sub-workflow-cache-undeclared`
- `03-analyze-cache-modes/03-steady-state-text`
- `03-analyze-cache-modes/04-steady-state-json`
- live lyrics-generator text/JSON if row fields or cross-workflow display
  change

---

## Deferred / explicit non-goals

### Non-batch repeated static-prefix projection

`select-chorus` is invoked repeatedly because its parent workflow is batched,
but the node itself has no `batch:` config. Current prefix projection uses the
node's own batch alias to find the first dynamic boundary:

```text
static prefix ... ${item.dynamic}
```

For a non-batch repeated node, there is no alias. Dropping the `batch:` gate is
wrong because the code would not know which template ref first varies across
calls.

Possible future approaches:

1. **Trace LCP across actual rendered prompts**
   - best semantic model when full prompts are available;
   - current large live fixtures trim `llm_prompt` and `template_resolutions`,
     so canary verification is not available without fixture changes or new
     trace data.

2. **First-template-ref heuristic**
   - simple and conservative;
   - undercounts prompts where early refs are constant across calls.

3. **Static provenance analysis**
   - likely overengineered for this branch;
   - overlaps with cross-workflow/data-flow graph work.

Recommendation:

- Do not include non-batch prefix projection in the two-pass root fix unless
  the implementer first proves full rendered prompts are available in traces
  for the target cases.
- Keep the existing limitation test until deliberately replaced:
  `test_batch_prefix_projection_does_not_fire_for_non_batch_repeated_call_nodes`.

### Full cross-workflow row numeric plumbing

Keep cross-workflow findings diagnostic-first unless row semantics can expose
`requires_prompt_shape_change`.

Do not silently turn root-level child input opportunities into row
`could_cache` values.

---

## Verification commands

Use the sandbox-safe skill pattern. Avoid `uv run` in this sandbox unless the
environment changes.

Focused unit suite:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest \
  tests/test_core/test_cache_analysis_analyze.py \
  tests/test_core/test_cache_analysis_token_estimation.py \
  tests/test_core/test_cache_analysis_warnings.py \
  tests/test_core/test_cache_analysis_renderers.py \
  tests/test_core/test_cache_analysis_per_id_emission.py \
  tests/test_core/test_cache_analysis_per_id_coverage.py -q
```

Baseline subsets most likely to drift:

```bash
.taskmaster/tasks/task_159/baseline/verify.sh 03-analyze-cache-modes
.taskmaster/tasks/task_159/baseline/verify.sh 04-warning-catalog
.taskmaster/tasks/task_159/baseline/verify.sh 12-real-world-lyrics-generator
```

Full baseline after intentional recaptures:

```bash
.taskmaster/tasks/task_159/baseline/verify.sh
```

Near-full sandbox suite:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py \
  -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete'
```

Quality checks:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff check src tests
HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff format --check src tests
HOME=/private/tmp/pflow-test-home .venv/bin/python -m mypy src
```

If the project normally uses `make check`, run it outside this restricted
sandbox or with the known sandbox exclusions documented in
`.agents/skills/pflow-sandbox-testing/SKILL.md`.

---

## Baseline harness references

Use the existing harness, not ad hoc captures:

- `.taskmaster/tasks/task_159/baseline/PLAN.md`
- `.taskmaster/tasks/task_159/baseline/run-case.sh`
- `.taskmaster/tasks/task_159/baseline/verify.sh`
- `.taskmaster/tasks/task_159/baseline/regenerate.sh`

The new warning-catalog case should follow sibling `04-warning-catalog`
patterns.

---

## Documentation updates if adding `cache.prompt-cache-incomplete`

Update:

- `src/pflow/core/cache_analysis/warning_catalog.py` module prose/count
- `tests/test_core/test_cache_analysis_warnings.py` catalog inventory/count
- `tests/test_core/test_cache_analysis_per_id_coverage.py`
- `tests/test_core/test_cache_analysis_per_id_emission.py`
- `src/pflow/guide/features/caching.md`
- `src/pflow/core/cache_analysis/CLAUDE.md`
- MCP/analyze-cache docstring if it lists catalog IDs

Search before editing:

```bash
rg "21|CACHE_WARNING_CATALOG|cache.sub-workflow-cache-undeclared|cache.shared-context-undeclared" \
  src tests docs .taskmaster/tasks/task_159
```

---

## Decision points for the user / implementer

### Decision 1: New diagnostic ID

Options:

1. **New ID `cache.prompt-cache-incomplete`** - recommended.
   - Pros: clear action, no `shared-context-undeclared` semantic overload,
     avoids workflow-level dedup ambiguity.
   - Cons: catalog grows; requires tests/docs/baseline.
   - Importance: 4.

2. Extend `cache.shared-context-undeclared`.
   - Pros: fewer catalog entries.
   - Cons: wrong action contract ("paste block" vs "extend node
     prompt_cache"), dedup risk, confusing future code.
   - Importance: 4.

Recommendation: choose new ID.

### Decision 2: Row numeric display for partial opportunities

Options:

1. Diagnostics only in Pass 2.
   - Pros: simplest final code, no misleading ratios.
   - Cons: row `could_cache` may still understate opportunity.
   - Reversible: easy to add row fields later.
   - Importance: 3.

2. Populate explicit `could_cache_*` fields for declaration-alone missing
   chunks only.
   - Pros: better row signal without root/subpath lies.
   - Cons: more renderer/JSON/cost test surface.
   - Reversible: moderate.
   - Importance: 3.

3. Populate row numbers for root/subpath cross-workflow opportunities.
   - Pros: table looks more complete.
   - Cons: high risk of misleading "requires prompt edit" numbers.
   - Reversible: hard once baselines/JSON consumers depend on it.
   - Importance: 4.

Recommendation: do option 1 first, or option 2 only after Pass 1 fields exist.
Do not do option 3 without explicit `requires_prompt_shape_change` display.

### Decision 3: JSON version

Options:

1. Add fields and bump `JSON_FORMAT_VERSION` to `4.2` - recommended.
   - Pros: honest machine-consumer signal.
   - Cons: baseline churn.
   - Importance: 3.

2. Add fields under `4.1`.
   - Pros: less version churn.
   - Cons: consumers cannot distinguish old overloaded row model from new
     precise row model.
   - Importance: 3.

Recommendation: bump to `4.2` if adding explicit row fields.

### Decision 4: Non-batch prefix projection

Options:

1. Defer until trace prompts are available - recommended.
   - Pros: avoids heuristic false confidence.
   - Cons: `select-chorus` prefix gap remains.
   - Importance: 4.

2. Implement first-template-ref heuristic.
   - Pros: simple.
   - Cons: can significantly undercount; may still not solve the canary well.
   - Importance: 4.

3. Implement trace LCP.
   - Pros: best semantics.
   - Cons: current large fixtures trim prompt data; requires trace data proof
     or trace format/storage change.
   - Importance: 4.

Recommendation: defer from the two-pass root fix unless a fresh trace fixture
with full prompts is added.

---

## What "done" means

Pass 1 is done when:

- row fields distinguish declared/current cache from opportunity;
- old JSON fields still exist or version bump is documented;
- cost projections never use undeclared opportunity tokens;
- Tier 2 chunk projections multiply by observed call count only outside trace
  Tier 1;
- analyze/render visibility predicates agree;
- focused tests and likely baseline subsets pass.

Pass 2 is done when:

- declared workflows with missing shared cache items emit a clear per-node
  advisory;
- suggestions use cache item `name`, estimate/cleanup by `var`, and preserve
  declaration order;
- diagnostics group missing chunks per node;
- below-threshold cases remain visible without fabricated savings;
- cross-workflow root/subpath opportunities are not silently rendered as plain
  row `could_cache`;
- new catalog ID has coverage/emission/tests/docs/baseline;
- full Task 159 baseline passes after intentional recapture.

---

## Short implementation checklist

1. Add explicit `PerCallRow` fields and JSON additive fields.
2. Update renderer cells with fallback to legacy `cacheable_tokens_estimated`.
3. Update cost estimation to read declared-cache field only.
4. Thread `observed_call_count` through Tier 2 cacheable estimation.
5. Fix `_row_has_real_data_in_analyze()` parity.
6. Add Pass 1 tests and update baselines if needed.
7. Add `CacheCoverageOpportunity` helper for declared workflows.
8. Add `cache.prompt-cache-incomplete` catalog entry and priority.
9. Emit one diagnostic per node with grouped missing chunks.
10. Include corrected `prompt_cache:` and prompt-body cleanup in context.
11. Add production-shape tests, per-ID coverage/emission, docs, baseline case.
12. Run focused tests, baseline subsets, full baseline, then near-full sandbox
    suite.

---

## Final recommendation

Implement in two passes:

1. **Pass 1: row semantics + Tier 2 scope**
   This is the foundation. It prevents future code from lying by accident.

2. **Pass 2: declared-workflow cache coverage diagnostics**
   This solves the partial-declaration research-file defect and gives a clean
   place to integrate cross-workflow opportunities without inflating row ratios.

Keep non-batch repeated-prefix projection out of these passes unless the agent
first proves full rendered prompts are available for trace-driven LCP. The
current `select-chorus` row remains a known limitation, but forcing it into the
same pass would overfit the report and make the final code less honest.
