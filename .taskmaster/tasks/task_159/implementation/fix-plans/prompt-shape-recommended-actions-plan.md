# Cache Analyzer: Prompt-Shape Recommended Actions

> **Task**: 159 Prompt Caching
> **Scope**: Tiers 1 and 2 implementable follow-up; Tier 3 deferred to GitHub issue.
> **Status**: Design plan, no code changes in this document.
> **Created**: 2026-05-10 after reviewing the Gemini lyrics-generator baseline,
> the select-chorus/Tier-2 handoff, and the partial-declaration handoff.

---

## Problem Statement

The per-call table now exposes `cached_now` and `could_cache`, but some
important prompt-shape opportunities still do not show up in a way an agent
can reliably act on.

The motivating discussion came from this row in the live Gemini
lyrics-generator baseline:

```text
### chorus-chooser.pflow.md (called by choose-chorus)
  score-choruses  ...  could_cache=144,296  ratio=91%  calls=136
  select-chorus   ...  could_cache=164      ratio=0%   calls=4
```

At first glance this looks inconsistent: both nodes are in the chorus chooser,
both run repeatedly across the full workflow, and both have stable judging /
scoring instructions. Why does only `score-choruses` show a large
`could_cache`?

The answer is that these are different shapes:

- `score-choruses` is an actual local `batch:` LLM node.
- `select-chorus` is not a local batch node. It executes four times only
  because its parent `chorus-chooser` sub-workflow is invoked four times by
  the parent song-creator batch.
- `score-choruses` places the per-item dynamic value late:
  `${item.chorus_text}` appears near the end of `score-chorus.prompt.md`.
- `select-chorus` places song-specific dynamic values early:
  `${concept.title}`, `${concept.core_idea}`, and
  `${rank-choruses.result.top_formatted}` appear before much of the stable
  judging rubric.

Current `could_cache` means "tokens that can be cached with the current prompt
shape by declaring/extending prompt cache, or by the current batch-prefix
projection." It should not silently include "tokens that could cache only after
moving dynamic values later." That second class is a prompt-shape refactor and
belongs in `## Recommended actions`.

---

## Existing Building Blocks

### `cache.dynamic-before-static`

There is already a warning ID for this general concept:

- Catalog entry: `src/pflow/core/cache_analysis/warning_catalog.py`
- Detector: `src/pflow/core/cache_analysis/analyze.py::_dynamic_before_static_warnings`
- Recommended-action routing:
  `src/pflow/core/cache_analysis/view_helpers.py::build_recommended_actions`
- Priority: `RECOMMENDED_ACTION_PRIORITY["cache.dynamic-before-static"] == 10`

The current detector is too narrow. It only fires when:

- the row already has `prompt_cache:`, and
- the workflow has declared cache chunks, and
- a non-declared template ref appears before a large cacheable suffix.

That misses greenfield prompt-shape cases where an LLM node has a local batch
alias and a large stable static tail after `${item...}` but no existing
`prompt_cache:`.

### Existing Batch-Prefix Projection

`_estimate_batch_prefix_cacheable_tokens` already detects safe static prefixes
for local batch nodes by finding the first `${item...}` reference and counting
tokens before it. This feeds `could_cache` with source `"batch_prefix"`.

That projection covers "this prompt could cache with the current shape."

The prompt-shape advisory in this plan covers the opposite layout:

```text
${item.dynamic}

large stable rubric / schema / instructions
```

This cannot cache as a provider prefix today, but it can after reordering.

---

## Tier 1: Generalize `cache.dynamic-before-static` For Local Batch Nodes

### Goal

Emit a recommended action when a local `batch:` LLM node has a per-item dynamic
reference before a large stable static tail.

Example shape:

```md
## Input

${item.text}

## Rubric

Large stable instructions...
Large stable output schema...
Large stable examples...
```

Recommended action:

```text
Dynamic ref blocks caching on score — move `${item.text}` after stable content
```

### Why Local Batch Nodes First

For local batch nodes, the dynamic boundary is syntactically reliable:

- `batch.as` defines the alias, defaulting to `item`.
- `${item}`, `${item.foo}`, and `${item[0].foo}` are per-item dynamic.
- Existing runtime/analyzer code already treats this alias as the prompt-cache
  boundary for batch prefix caching and prewarm checks.

This is the top-10% codebase version of the fix: use a proven local invariant,
not broad guessing.

### Detection Algorithm

Add a pure helper near `_dynamic_before_static_warnings`:

```python
@dataclass(frozen=True)
class _PromptStaticTailFinding:
    dynamic_ref: str
    dynamic_line: int
    stable_tail_tokens: int
    tokens_before_dynamic: int
    template_refs_after_dynamic: int
    static_tail_excerpt: str
```

Possible helper shape:

```python
def _find_batch_static_tail_after_dynamic(
    *,
    prompt: str,
    model: str,
    batch_alias: str,
) -> _PromptStaticTailFinding | None:
    ...
```

Rules:

1. Scan raw prompt with `TemplateResolver.TEMPLATE_PATTERN`.
2. Split coalesce operands with `TemplateResolver.split_coalesce_operands`.
3. Find the first template expression containing a batch-scoped operand:
   `operand == alias`, `operand.startswith(f"{alias}.")`, or
   `operand.startswith(f"{alias}[")`.
4. Build the candidate stable tail from literal spans after that dynamic ref.
5. Do **not** count unresolved later template refs as literal text.
6. Optionally count resolvable stable refs later, but only if resolved through
   existing `AnalysisContext` machinery. If this complicates the first pass,
   count literal spans only.
7. Emit only when `stable_tail_tokens >= get_min_cache_tokens(row.model)`.
8. Compute `affected_calls` as:
   - `row.batch_size_estimated` for static-list batch rows,
   - `row.observed_call_count` when trace observed multiple local batch calls,
   - otherwise no finding.

### Why Literal-Spans-Only Is Safer Than `prompt[match.end():]`

The existing detector estimates `prompt[match.end():]`. That can include later
`${...}` refs as literal placeholder text, which overstates stable bytes. For
the greenfield prompt-shape advisory, that would be a false positive risk.

The safe first pass is:

- literal text after the first batch dynamic ref counts;
- later dynamic refs do not count;
- unresolved stable refs do not count;
- resolved stable refs can be added later if needed.

This may undercount, but it preserves the analyzer's honest-unmeasurable
convention.

### Catalog / Rendering

Reuse `cache.dynamic-before-static` rather than adding a new ID.

Reasons:

- The catalog is closed by Task 159 DD#29.
- The existing ID already has correct recommended-action routing and priority.
- The semantic category is the same: dynamic content appears before cacheable
  stable content.

Catalog wording should be broadened slightly so it covers both existing
declared-cache and new greenfield local-batch cases:

Current spirit:

```text
dynamic `${ref}` precedes cacheable content; cache won't fire
```

Recommended wording:

```text
dynamic `${ref}` appears before ~N stable tokens; move stable instructions
before dynamic content so prefix caching can fire for M calls per run
```

Keep required context keys unchanged if possible:

- `node_id`
- `dynamic_ref`
- `dynamic_line`
- `cacheable_tokens`
- `affected_calls`
- `savings_usd`
- `projected_ratio_pct`

Add optional context keys for JSON consumers:

- `affected_workflow`
- `detection_mode`: `"declared_cache"` or `"batch_static_tail"`
- `min_cache_tokens`
- `model`
- `tokens_before_dynamic`
- `template_refs_after_dynamic`
- `static_tail_excerpt`

Extra context is safe: `make_diagnostic()` preserves context kwargs.

### Tests

Add end-to-end analyzer tests, not synthetic diagnostic-only tests:

1. **Positive local-batch static tail**
   - Node has `batch: {items: [a, b, c], as: item}`.
   - Prompt begins with `${item.text}` followed by a large stable literal
     rubric.
   - Assert `cache.dynamic-before-static` emits.
   - Assert it appears in recommended actions.

2. **Alias bracket form**
   - Use `${item[0].text}` or equivalent bracket syntax.
   - Assert same detector fires.

3. **Below threshold**
   - Dynamic ref followed by small stable tail.
   - Assert no warning.

4. **Later dynamic refs are not counted as stable**
   - Dynamic ref followed by small literal text + large `${item.other}` value
     placeholder.
   - Assert no warning if literal stable tail is below threshold.

5. **Existing declared-cache behavior preserved**
   - Existing `cache.dynamic-before-static` baseline/test remains green.
   - Add a regression test if current coverage is weak.

6. **No repeated-non-batch expansion**
   - Non-batch row with repeated trace calls and early `${context}` must not
     emit this batch-specific advisory.

### Expected Baseline Impact

Likely small. The existing live lyrics-generator baseline may not gain a new
Tier 1 warning because `score-choruses` is already correctly shaped
(`${item.chorus_text}` at the end), and `generate-chorus-options` is opaque
because the prompt is Python-assembled as `${item.prompt}`.

The warning-catalog fixture for `cache.dynamic-before-static` may need wording
updates if the catalog template changes.

---

## Tier 2: Promote High-Value Existing Batch-Prefix Opportunities To Recommended Actions

### Goal

When the per-call report already knows a local batch node has a large
cacheable static prefix (`cacheable_data_source == "batch_prefix"`), emit a
recommended action so agents do not need to infer actionability from the table.

This is the case currently visible in lyrics-generator:

```text
score-choruses  input=158,704  could_cache=144,296  ratio=91%  calls=136
```

The row is strong evidence. It should also appear in `## Recommended actions`.

### Action Semantics

This is different from Tier 1:

- Tier 1 says: "Your prompt shape blocks caching; reorder it."
- Tier 2 says: "Your prompt shape is already good; declare/prewarm the stable
  prefix so it can cache."

Potential wording:

```text
Batch prefix cacheable on score-choruses — declare/prewarm stable prompt prefix
```

But because the catalog is closed, prefer reusing an existing ID if the
semantics fit.

Candidate IDs:

1. `cache.batch-prewarm-recommended`
   - Existing, priority 10, already tied to local batch prefix savings.
   - Current detector only fires when `batch_size_estimated` is known and
     `prewarm` is absent.
   - It is about `prewarm`, not `prompt_cache`, but that may be acceptable for
     local batch prefix caching.

2. `cache.shared-context-undeclared`
   - Not a good fit. The opportunity is prompt-prefix layout, not a shared
     workflow input chunk.

3. New ID
   - Cleaner semantics, but catalog-growth cost. Avoid unless existing
     `batch-prewarm-recommended` cannot honestly represent the action.

Recommendation: extend `cache.batch-prewarm-recommended` if the implementation
can make the wording honest for both current and trace-observed dynamic batch
cases.

### Current Gap

`_batch_prewarm_recommendations()` currently requires:

```python
batch_size = row.batch_size_estimated
if batch_size is None or batch_size < 2:
    return []
```

For dynamic batch rows like `score-choruses`, `batch_size_estimated` can be
`None` even when trace observed 136 calls. The per-call table already knows
`observed_call_count == 136` and `cacheable_data_source == "batch_prefix"`.

Therefore, Tier 2 can be implemented by letting the prewarm recommendation use
observed call count when static batch size is unavailable.

### Detection Algorithm

Modify `_batch_prewarm_recommendations(node, row)`:

1. Keep `prewarm` opt-out semantics:
   - if `"prewarm" in node`, return `[]`.
2. Require `node.batch` to be a dict.
3. Compute:

```python
effective_calls = (
    row.batch_size_estimated
    if row.batch_size_estimated is not None
    else row.observed_call_count
)
```

4. Require `effective_calls >= 2`.
5. Prefer existing prefix evidence:
   - if `row.cacheable_data_source == "batch_prefix"` and
     `row.cacheable_tokens_estimated` is positive, use that as total cohort
     prefix tokens.
   - derive per-call prefix tokens as
     `round(row.cacheable_tokens_estimated / effective_calls)`.
6. Otherwise fall back to the existing prompt scan.
7. Apply current savings threshold (`savings_pct >= 5`).
8. Emit `cache.batch-prewarm-recommended`.

### Caveat: Cohort vs Per-Call Prefix Tokens

Existing `cache.batch-prewarm-recommended` context has
`prefix_tokens_estimated`. Historically this appears to mean per-call prefix
tokens. The `batch_prefix` row stores cohort tokens (`prefix * calls`).

Do not pass cohort tokens as `prefix_tokens_estimated` unless the catalog text
is updated to say cohort. Prefer:

- `prefix_tokens_estimated`: per-call prefix estimate.
- optional `prefix_tokens_cohort_estimated`: total over affected calls.

### Savings

For `batch-prewarm-recommended`, savings should use the repeated-call benefit,
not simply write/read savings for one call. Existing math estimates savings
ratio from prefix/dynamic tokens. Preserve that behavior.

If using row-level `batch_prefix` evidence:

- `prefix_tokens_per_call = round(row.cacheable_tokens_estimated / effective_calls)`
- `dynamic_tokens_per_call = max(0, round(row.input_tokens_estimated / effective_calls) - prefix_tokens_per_call)`
- savings ratio can reuse the existing formula.
- `savings_usd` should estimate repeated savings across `effective_calls - 1`
  or use the existing helper consistently with current behavior.

### Tests

1. **Dynamic batch with trace-observed calls emits prewarm recommendation**
   - `batch.items: ${items}`.
   - Trace has 4 LLM calls.
   - Prompt has large stable prefix before `${item.text}`.
   - Assert `cache.batch-prewarm-recommended` emits even though
     `batch_size_estimated is None`.

2. **Prewarm opt-out suppresses**
   - Same fixture with `prewarm: false`.
   - Assert no recommendation.

3. **Explicit prewarm true suppresses recommendation**
   - Existing behavior should remain.

4. **Below savings threshold suppresses**
   - Small prefix or low call count.

5. **Gemini lyrics-generator canary**
   - Assert `score-choruses` appears in recommended actions or warnings with
     `cache.batch-prewarm-recommended`.
   - This is the real user-facing target for Tier 2.

### Expected Baseline Impact

Likely the live Gemini lyrics-generator baseline gains one recommended action:

```text
Batch prewarm not declared — add `- prewarm: true` to score-choruses
```

That is desirable. It turns a buried per-call table signal into a ranked action.

Summary counts and dry-run nudge counts may increase automatically because
they use `build_recommended_actions()`.

---

## Tier 3: Deferred Repeated Non-Batch Provenance

### Problem

`select-chorus` is the canonical example:

- It has no local `batch:` block.
- It runs four times because its parent sub-workflow is invoked four times.
- Its prompt contains early dynamic refs followed by stable judging text.
- Humans can infer that `${concept.*}` and `${rank-choruses.*}` vary per
  parent song, but the local node has no alias like `${item...}` that proves
  the dynamic boundary.

Without stronger provenance, the analyzer cannot safely distinguish:

```text
${concept}        # varies per parent batch item
${style_guide}    # stable across all calls
${company_policy} # stable across all calls
```

Treating every early template ref as dynamic would catch some true positives
but would also create false prompt-shape recommendations.

### Why It Is Deferred

This requires a model of which refs differ across repeated invocations.
Possible solutions:

1. **Trace-level per-call prompt/ref capture**
   - Capture each LLM call's resolved prompt, or each template ref's resolved
     value, before trimming.
   - Compare values across calls to find the first ref that actually varies.
   - Then compute stable text after that boundary.

2. **Cross-workflow provenance propagation**
   - Thread parent batch alias/root provenance into child workflow parameters.
   - Mark child inputs derived from parent `${item...}` as varying per parent
     invocation.
   - Use that metadata in prompt-shape detection.

3. **Explicit workflow annotation**
   - Let workflow authors annotate a ref or section as per-call dynamic.
   - Lower implementation complexity, but increases author burden.

Each is larger than a local analyzer heuristic and should be implemented as a
separate task.

### Deferred Issue Scope

Create a GitHub issue for Tier 3 with this outcome:

- Detect prompt-shape opportunities for repeated non-batch nodes by identifying
  which template refs vary across observed calls.
- Avoid first-template-ref heuristics.
- Preserve the existing limitation test until the provenance-backed detector
  exists, then invert it.

---

## Implementation Order

Recommended order:

1. **Tier 2 first**: promote existing `batch_prefix` evidence to recommended
   actions through `cache.batch-prewarm-recommended`.
   - Highest immediate value.
   - Uses already-computed evidence.
   - Should make `score-choruses` actionable.

2. **Tier 1 second**: broaden `cache.dynamic-before-static` for local batch
   nodes with large stable tails after `${item...}`.
   - Safe because alias proves dynamic boundary.
   - Needs careful literal-span token counting.

3. **Tier 3 later**: provenance-backed repeated non-batch detection.
   - Separate issue.
   - Do not guess.

---

## Verification Plan

Use the sandbox testing skill commands:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest \
  tests/test_core/test_cache_analysis_analyze.py \
  tests/test_core/test_cache_analysis_renderers.py \
  tests/test_core/test_cache_analysis_per_id_emission.py \
  tests/test_core/test_cache_analysis_per_id_coverage.py \
  tests/test_core/test_cache_analysis_warnings.py -q
```

Baseline:

```bash
PATH="/private/tmp/pflow-uv-shim:$PATH" .taskmaster/tasks/task_159/baseline/verify.sh
```

Quality:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff check \
  src/pflow/core/cache_analysis tests/test_core/test_cache_analysis_*.py

HOME=/private/tmp/pflow-test-home .venv/bin/python -m ruff format --check \
  src/pflow/core/cache_analysis tests/test_core/test_cache_analysis_*.py

HOME=/private/tmp/pflow-test-home .venv/bin/python -m mypy src/pflow/core/cache_analysis
git diff --check
```

Manual smoke:

```bash
HOME=/private/tmp/pflow-test-home PATH="$PWD/.venv/bin:$PATH" \
  pflow analyze-cache \
  .taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md \
  --from-trace .taskmaster/tasks/task_159/baseline/_shared/fixtures/live-gemini-lyrics-generator.trace.json \
  sources="[\"$(head -c 3000 .taskmaster/tasks/task_159/baseline/_shared/long-stable-text.txt)\"]"
```

Expected after Tier 2:

- `score-choruses` appears in `## Recommended actions`.
- `select-chorus` remains low `could_cache` and does **not** receive a guessed
  static-tail recommendation.

Expected after Tier 1:

- Local batch prompts with dynamic-first/stable-tail shape receive
  `cache.dynamic-before-static`.
- No repeated non-batch false positives.

---

## Trust Boundary

Verified:

- `score-choruses` is a local batch LLM node and already shows large
  `batch_prefix` evidence in the live baseline.
- `select-chorus` is not a local batch LLM node; it repeats because its parent
  workflow repeats.
- `cache.dynamic-before-static` already exists and routes to Recommended
  actions.
- Recommended actions are renderer projections of `analysis.warnings`.

Assumed:

- Extending `cache.batch-prewarm-recommended` is semantically acceptable for
  trace-observed dynamic batch rows. If the wording becomes strained, create a
  new catalog ID only after explicit design review.

Deferred:

- Provenance-backed dynamic-boundary detection for repeated non-batch nodes.
- Any heuristic that treats the first arbitrary template ref as dynamic.

