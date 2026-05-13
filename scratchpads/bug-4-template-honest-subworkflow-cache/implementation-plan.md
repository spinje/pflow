# Bug 4 Implementation Plan — Template-Honest Sub-Workflow Cache Recommendations

## Purpose

Fix Task 159 Bug 4 correctly, not just cosmetically: `pflow analyze-cache`
must stop recommending full-object cache declarations when a child workflow's
LLM prompts only use subfields of that object.

The current analyzer can say, effectively:

```text
Cache `concept` because `${concept.core_idea}` and `${concept.title}` are used.
```

That is wrong. Provider prompt caching is byte-level prompt content, not a
hidden variable store. Caching `${concept}` sends the full serialized object to
the model in cached context. If the prompt currently uses only
`${concept.core_idea}` and `${concept.title}`, recommending `${concept}` changes
both cost and prompt semantics.

The right model is simpler:

```text
The cache unit is the actual prompt reference, not the workflow input root.
```

So sub-workflow recommendations should say:

```text
Cache `concept.core_idea` and `concept.title`.
```

Only recommend full `concept` when a prompt actually uses `${concept}` directly,
or when the analyzer explicitly labels full-object caching as a tradeoff the
workflow author must choose.

## Trust Boundary

Verified against current source:

- Dotted cache chunks are valid. `## Cache` parses each `${var}` verbatim; the
  chunk name equals the variable expression. `${concept.title}` becomes a cache
  chunk named `concept.title`.
  - `src/pflow/core/markdown_parser.py::_parse_cache_code_block`
  - `src/pflow/core/markdown_parser.py::_build_cache_dict`
  - `src/pflow/runtime/compilation/compiler.py::_build_cache_chunk`
- Same-workflow greenfield suggestions already preserve subpaths instead of
  auto-collapsing them to the root.
  - `tests/test_core/test_cache_analysis_per_id_emission.py::test_template_honest_default_keeps_subpaths_separate`
- The sub-workflow path still works from child input roots.
  - `src/pflow/core/cache_analysis/analyze.py::_sub_workflow_cache_candidate`
  - `src/pflow/core/cache_analysis/analyze.py::_estimate_parent_value_tokens`
  - `src/pflow/core/cache_analysis/analyze.py::_grouped_consumer_projections`
- The analyzer already knows the actual prompt refs by node, but currently uses
  them mostly as cleanup text.
  - `src/pflow/core/cache_analysis/analyze.py::_per_input_var_refs`
- The bad current output is visible in:
  - `.taskmaster/tasks/task_159/baseline/04-warning-catalog/05b-cache.sub-workflow-cache-undeclared-subpath/expected-stdout.txt`
  - `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`
- Existing Bug 4 body-only disclosure is a separate brownfield overlap fix. It
  does not solve undeclared sub-workflow recommendations.
  - `src/pflow/core/cache_analysis/analyze.py::_enrich_shadow_warnings_with_costs`
  - `src/pflow/core/cache_analysis/render_text.py::_format_shadow_cache_cost_comparison`

Assumed correct, not re-proven in this plan:

- Provider cache markers are applied to rendered cache blocks, and provider
  behavior depends on those rendered bytes, not pflow variable names. This was
  verified during Task 159 and is covered by cache rendering tests.
- Deterministic serialization is the right way to count non-string cached values
  for analysis.

Unable to verify without implementation:

- The exact baseline drift count. The `05b` warning-catalog baseline will drift;
  lyrics-generator output likely drifts. The number depends on final renderer
  wording.

## Problem Shape

Current data flow:

```text
parent workflow input or node output
  -> workflow node input: concept: ${concept}
  -> child prompt refs: ${concept.core_idea}, ${concept.title}
  -> analyzer candidate: child input `concept`
  -> analyzer token count: full serialized ${concept}
  -> recommendation: declare `concept`
```

This conflates two different things:

- Boundary transport name: `concept`
- Prompt bytes that should be cached: `concept.core_idea`, `concept.title`

This is the source of both the overstated savings and the semantic leak.

Correct data flow:

```text
parent workflow input or node output
  -> workflow node input: concept: ${concept}
  -> child prompt refs: ${concept.core_idea}, ${concept.title}
  -> analyzer candidates: `concept.core_idea`, `concept.title`
  -> analyzer token count: those exact values
  -> recommendation: declare those exact chunks
```

## Design Decision

### Recommendation

Implement template-honest sub-workflow candidates, and make that the only model
used by both:

- grouped Recommended actions, and
- per-call `cross_workflow_projection` rows.

Each cache candidate should represent one actual child prompt reference. Keep
the boundary input root as metadata, but do not use it as the cache chunk unless
the prompt uses the root directly.

Candidate shape should move from:

```python
_SubWorkflowCacheCandidate(
    child_input_name="concept",
    parent_value_expr="concept",
    child_node_ids=("score", "select"),
)
```

to the conceptual shape:

```python
_SubWorkflowCacheCandidate(
    child_input_name="concept",
    child_cache_ref="concept.core_idea",
    parent_value_expr="concept",
    parent_cache_ref="concept.core_idea",
    child_node_ids=("score", "select"),
)
```

For a direct root prompt ref, the fields are identical:

```python
child_input_name="concept"
child_cache_ref="concept"
parent_value_expr="concept"
```

### Why This Is The Simple Solution

It removes the wrong abstraction instead of adding compensating warnings.

The larger alternative would carry both "full root size" and "used subfield
size" through projection, classification, rendering, and JSON. That would make
the code harder for future agents to reason about because the analyzer would
still be built around the wrong candidate and then patch over it downstream.

The small durable rule is:

```text
Sub-workflow cache candidates are derived from prompt refs.
```

This matches same-workflow behavior and makes future features like suggested
blocks, cleanup hints, and threshold checks reuse one mental model.

### Simplicity Constraint

Do not implement this as "root input plus subpath correction" in multiple
places. The final code should have one helper that answers:

```text
For this child input, which prompt refs under that input are actually consumed,
and by which child LLM nodes?
```

Both the grouped recommendation path and the per-call row projection path should
consume that helper. If they each inspect prompt refs independently, this bug
can reappear in one path while tests pass in the other.

The parallel review pass tightened this further:

- Centralize path containment and suffix mapping first. Do not scatter
  `startswith(".")` / `startswith("[")` checks across the analyzer.
- Carry prompt-body refs from the shared helper too, so cleanup text does not
  re-scan prompts with slightly different rules.
- Audit every old `child_input_name` join. The risky paths are not only the
  numbered recommendation body; they include no-trace notes, per-call row notes,
  JSON/MCP output, and baseline fixtures.

### Final Code Shape Gate

Before coding, and again before finalizing, apply this gate:

```text
Can a future agent explain the implementation as:
"Find the child prompt refs once, map each ref across the parent boundary once,
then every output surface reads that same fact"?
```

If the answer is no, the patch is probably preserving the old root-input model
too deeply.

Final-code priorities:

- Prefer one extractor plus small path helpers over scattered local fixes.
- Prefer updating existing candidate/row structures over adding parallel
  "correction" structures. `_ChildCacheRefUse` is the single extraction result,
  not a parallel correction layer.
- Keep renderer logic dumb: render facts produced by analysis; do not
  recompute prompt-ref semantics in text rendering.
- Keep JSON additive and boring. Do not let JSON concerns drive the analyzer
  shape.
- Delete or replace obsolete root-input helpers if their old semantics become
  misleading. Do not leave wrappers that make future agents wonder which helper
  is canonical.
- If a guardrail requires many special cases, stop and ask whether path
  semantics or candidate extraction is in the wrong place.

Expected implementation should still feel like a small correction to the
cross-workflow candidate model, not a new analyzer subsystem.

### Fixed Implementation Decisions

These are not open questions for the implementing agent:

1. **Add `_ChildCacheRefUse`.**
   It is mandatory, not optional. It is the single prompt-ref extraction result
   used by grouped recommendations, row-level projections, cleanup text, and
   no-trace structural checks.

2. **Keep path helpers private to `analyze.py` for this patch.**
   Do not create a new module unless implementation proves reuse outside cache
   analysis is needed. Align behavior with `cache_overlap` where useful, but do
   not broaden this bug fix into a shared path library refactor.

3. **Use minimal cache-block edit text.**
   Do not invent prose labels like "Article title:" unless the analyzer already
   has a trustworthy label. The exact edit block should prefer a minimal valid
   cache block:

   ````text
   Add or extend ## Cache:
     ```cache
     ${article.title}

     ${article.body}
     ```
   ````

   This avoids adding semantic text to the cached prompt on the agent's behalf.

4. **Multiple parent origins for the same child cache entry are unmeasurable.**
   If the same `(child_workflow, child_cache_ref)` is reached from more than one
   distinct parent origin, keep one recommended child edit, list or count the
   origins in the body/context, and set token/savings estimates for that entry
   to `None` unless all resolved token estimates are identical. Do not choose a
   lexicographic origin as truth.

5. **Root and subpath candidates are per node.**
   If one node uses `${concept}` and another node uses `${concept.title}`, emit
   root cleanup/cache guidance for the first node and subpath cleanup/cache
   guidance for the second. Do not globally collapse the whole input to root.

6. **No new warning ID.**
   Keep using `cache.sub-workflow-cache-undeclared`; this is a correction to
   its candidate model and renderer context.

7. **Do not bump JSON format unless tests reveal required policy.**
   Additive fields are the intended JSON change. If existing format-version
   policy requires a bump for additive fields, bump it mechanically and update
   the version-note tests in the same patch.

## User-Facing Target

For the current `05b` baseline, replace this kind of output:

```text
Sub-workflow cache undeclared in child.pflow.md — declare 1 input saves ~$0.02/run
...
Node `summarize`:
  • `article` ~3,207 tokens — uses `${article.title}`
Node `translate`:
  • `article` ~3,207 tokens — uses `${article.body}`
```

with output that names the actual cache entries and exact edits:

````text
Sub-workflow cache missing in child.pflow.md — add 2 entries to ## Cache
...
Only these listed values are used by prompts. Do not cache full objects like
`article` unless you intentionally want every field in that object sent to the
model.

Edit child.pflow.md:
  Add or extend ## Cache:
    ```cache
    ${article.title}

    ${article.body}
    ```

  Add prompt_cache entries:
    summarize: prompt_cache: [article.title]
    translate: prompt_cache: [article.body]

  Then remove these prompt-body templates:
    summarize: ${article.title}
    translate: ${article.body}

  Keep useful plain-text labels such as "Title:" or "Body:", but do not repeat
  the cached value in the prompt body.
→ Edit: .../child.pflow.md
````

For lyrics-generator, the risky `concept` line should stop saying the analyzer
will cache the full `concept` object merely because consumers use
`${concept.core_idea}` and `${concept.title}`. It should list the actual
subpaths, or mark full-object consolidation as an explicit tradeoff if that
path remains useful.

Do not introduce internal terms such as "candidate", "root collapse",
"projection tier", "cache_ref", or JSON field names into text output.

## Implementation Steps

### 0. Centralize Path Semantics First

Add small path helpers before changing candidate extraction:

```python
def _path_is_equal_or_descendant(path: str, root: str) -> bool:
    """True for `concept`, `concept.title`, and `concept[0]` under root `concept`."""

def _path_is_ancestor_or_equal(ancestor: str, child: str) -> bool:
    """True when ancestor is the same path or a path-segment ancestor of child."""

def _append_child_suffix(parent_ref: str, child_input_name: str, child_ref: str) -> str:
    """Map child ref `concept.title` through parent expr `song.concept` -> `song.concept.title`."""

def _child_suffix(child_input_name: str, child_ref: str) -> str:
    """Return `.title` or `[0].title` for refs under `concept`."""
```

These helpers should be segment-aware:

- `concept` covers `concept.title` and `concept[0].title`.
- `concept` does not cover `conceptual.title`.
- `concept.title` does not cover `concept.title_suffix`.

Prefer reusing or aligning with `src/pflow/core/cache_overlap.py` path
canonicalization if that keeps semantics shared. The goal is one path rule
used by prompt-ref extraction, declaration coverage, row projection,
trace-fallback suffix resolution, and tests.

### 1. Introduce Prompt-Ref-Level Candidate Data

Update `_SubWorkflowCacheCandidate` in
`src/pflow/core/cache_analysis/analyze.py`.

Add fields:

```python
child_cache_ref: str
parent_cache_ref: str
```

Keep existing fields initially:

```python
child_input_name: str
parent_value_expr: str
```

Rationale:

- `child_input_name` is still needed to understand the boundary.
- `parent_value_expr` is still needed for origin text and trace fallback.
- `child_cache_ref` is the actual chunk name to recommend in the child.
- `parent_cache_ref` is the value to resolve/tokenize in parent scope.
- `child_cache_ref` should become the primary grouping/matching key. Do not keep
  using `child_input_name` as the candidate identity.

Expected impact: local dataclass updates and call-site updates.

Also update `CrossWorkflowInputContribution` and `_RowCrossWorkflowCandidate`
with the same `child_cache_ref` / `parent_cache_ref` fields. Row-level
cross-workflow projection currently has its own candidate type; leaving it
root-based would preserve the misleading per-call table even if Recommended
actions become correct.

Add one internal extracted-use shape so prompt usage and cleanup instructions
come from the same source:

```python
@dataclass(frozen=True)
class _ChildCacheRefUse:
    child_cache_ref: str
    consumer_node_ids: tuple[str, ...]
    body_refs_by_node: Mapping[str, tuple[str, ...]]
```

`body_refs_by_node` stores the actual prompt-body templates to remove. This
matters for `params.inputs` indirection: if a node prompt says `${title}` and
`params.inputs.title: ${concept.title}`, the cache entry is `concept.title` but
the prompt-body template to remove is `${title}`.

### 2. Replace Root Candidate Extraction With Prompt-Ref Extraction

Current `_sub_workflow_cache_candidate(...)` and
`_row_cross_workflow_candidate_for_edge(...)` each reason from the boundary
input root. Replace that with one shared prompt-ref helper:

```python
def _child_cache_ref_consumers(
    child_ir: dict[str, Any],
    child_input_name: str,
) -> tuple[_ChildCacheRefUse, ...]:
    """Return prompt refs under the input, grouped by cache entry."""
```

Then build grouped and row-level candidates from that same mapping.

`_sub_workflow_cache_candidate(...)` should become a multi-candidate builder:

```python
def _sub_workflow_cache_candidates_for_edge(...) -> list[_SubWorkflowCacheCandidate]:
```

Algorithm:

1. Skip when `edge.parent_value_expr is None`.
2. Inspect child LLM prompt refs rooted at `edge.child_input_name`.
3. For each unique operand:
   - If operand is `concept`, candidate cache ref is `concept`.
   - If operand is `concept.core_idea`, candidate cache ref is
     `concept.core_idea`.
4. Compute the parent-side ref:
   - If parent passes `${concept}` to child input `concept`, and child uses
     `concept.core_idea`, parent ref is `concept.core_idea`.
   - If parent passes `${song.concept}` to child input `concept`, and child uses
     `concept.core_idea`, parent ref is `song.concept.core_idea`.
   - If child uses the root `concept`, parent ref is the existing parent value
     expr, `concept` or `song.concept`.
5. Suppress candidates already declared by child `## Cache`.
6. Suppress candidates with no consumer nodes.

Suggested small helpers:

```python
def _append_child_suffix(parent_ref: str, child_input_name: str, child_ref: str) -> str:
    """Map child ref `concept.title` through parent expr `song.concept` -> `song.concept.title`."""

def _cache_ref_is_declared_or_covered(child_ref: str, declared: set[str]) -> bool:
    """True if child_ref itself or an ancestor ref is already declared."""
```

Important constraints:

- Use `classify_prompt_refs()` as the only prompt-ref scanner. It already
  exposes coalesce operands and one-level `params.inputs` dealiasing.
- Support coalesce operands in child prompt bodies when the classifier can
  identify concrete operand paths. Stay conservative for parent boundary
  expressions containing `??`; `_estimate_parent_value_tokens()` should keep
  returning `None` there.
- Preserve source-order where possible, then sort only at the grouping boundary.
- Do not infer subfields from object structure. Use prompt refs only.
- Treat bracket suffixes like dotted suffixes: `concept[0].title` is under
  `concept`, and parent `${song.concept}` maps to `song.concept[0].title`.
- Root and subpath refs are per-consumer facts. If node A uses `${concept}` and
  node B uses `${concept.title}`, do not tell node B to cache full `concept`.
  Recommend the root entry for root-consuming nodes and subpath entries for
  subpath-only nodes. If a single node uses both root and descendants, root
  covers that node's descendants.
- If the child already declares the exact cache entry, suppress the
  sub-workflow-undeclared recommendation for that entry; the existing
  `cache.prompt-cache-incomplete` path should handle missing per-node
  `prompt_cache:` assignments.
- If the child declares an ancestor such as `concept` while prompts use
  `concept.title`, suppress the undeclared warning for now and rely on existing
  duplicate/shadow/incomplete diagnostics. Do not introduce a full-root
  refactor recommendation in this patch.
- If raw prompt text clearly references a child input but the classifier cannot
  produce usable refs, do not silently drop the opportunity. Emit an
  unmeasurable/manual-review diagnostic with `savings_usd=None`.

### 3. Group By Cache Ref, Not Child Input Root

Current `_aggregate_sub_workflow_cache_candidates_by_child` deduplicates by
`child_input_name`. Change it to dedupe by `child_cache_ref`.

The group still represents one child workflow:

```python
_SubWorkflowCacheGroup(
    child_workflow=...,
    candidates=(article.title, article.body, ...)
)
```

Tie-break rule should remain deterministic. Use:

```python
(candidate.child_cache_ref, candidate.parent_node_id, candidate.parent_workflow)
```

Rationale:

- Multiple subpaths under one input must remain distinct.
- Same subpath discovered via multiple parent edges should be stable and
  deterministic.

Do not silently choose one parent origin when multiple different parent edges
feed the same `(child_workflow, child_cache_ref)`. If all measured token
estimates agree, using one displayed estimate is acceptable. If origins differ
or estimates are unavailable/inconsistent, keep the recommendation but mark
tokens/savings as unmeasurable rather than presenting one lexicographic winner
as truth.

### 4. Tokenize Candidate Cache Refs

Update `_tokens_per_group_input` into a cache-ref-based helper:

```python
def _tokens_per_group_ref(...) -> dict[str, int | None]
```

Key by `candidate.child_cache_ref`.

Use `_estimate_parent_value_tokens` with `candidate.parent_cache_ref`, not the
full `candidate.parent_value_expr`.

This is the critical Bug 4 fix. Savings, threshold checks, and text now use the
same exact bytes the recommendation tells the agent to cache.

Important trace fallback detail:

`_estimate_parent_value_tokens` currently has a final fallback that reads the
resolved parent workflow-node invocation value from:

```text
node_params["inputs"][child_input_name]
```

That value is the full child input. For subpath candidates, the fallback must
resolve the child suffix inside that already-resolved value before tokenizing.

Examples:

- parent passes `concept: ${concept}`, child ref `concept.title`:
  fallback reads full `inputs["concept"]`, then tokenizes its `.title`.
- parent passes `concept: ${song.concept}`, child ref `concept.title`:
  fallback still reads full `inputs["concept"]`, then tokenizes its `.title`.

Without this, trace-backed recommendations can keep counting the full object
even after `parent_cache_ref` is added.

Do not collapse token-estimation failures to zero. If any consumed cache entry
for a consumer is `None`, the consumer projection should be unmeasurable or
clearly partial, not "0 tokens" or "below threshold." Zero means measured empty;
`None` means not measured.

### 5. Sum Per Consumer Over Cache Refs

Update `_inputs_by_consumer` to become cache-ref-based:

```python
def _cache_refs_by_consumer(group) -> dict[str, list[str]]
```

Each consumer's `per_call_prefix_tokens` should be the sum of the cache refs
used by that consumer.

Example:

```text
score:
  concept.core_idea

select:
  concept.core_idea
  concept.title
  architecture
```

Threshold gating remains per call, exactly as current code already enforces.

Apply the same rule in row-level projection:

- `_build_cross_workflow_candidates_by_row` should attach one row candidate per
  consumed child cache ref, not one per child input root.
- `_apply_cross_workflow_projection` should sum `estimated_tokens_per_call` for
  those cache refs.
- `CrossWorkflowInputContribution` should expose the user-facing ref name used
  in the child workflow. Text can still call these "values" or "cache entries";
  JSON can carry both names.
- `_tokens_from_cross_workflow_rows` must match by `child_cache_ref`, not
  `child_input_name`, so grouped diagnostics cannot reuse full-object row
  estimates for subpath candidates.
- Row-level projection should dedupe only identical row contributions. Use a
  deterministic key such as `(workflow_path, node_id, child_cache_ref,
  parent_workflow, parent_node_id, parent_cache_ref)` and sort rendered
  contributions by `(child_cache_ref, parent_node_id, parent_workflow)`.
- Preserve the existing `is_batch_alias_root` skip for row-level projection.
  Batch sub-workflow values vary per item and are easy to over-project.
- Update `_has_structural_cross_workflow_projection_candidate()` to use the
  same prompt-ref helper and declaration suppression. Static/no-trace notes
  must not keep reasoning from the old child input root.

### 6. Update Text Formatting

Update:

- `_format_grouped_body_block`
- `_format_per_consumer_input_lines`
- `_format_single_consumer_input_lines`
- `_grouped_inputs_context`
- `_unavailable_notes_by_row_key`
- `_format_cross_workflow_inputs_note`
- the Recommended-actions intro for sub-workflow cache findings

Text rules:

- Say "entries in ## Cache" or "values", not "inputs", when candidates are subpaths.
  "Inputs" is still accurate only when every candidate is a direct child input.
- If all candidates are direct child inputs, existing wording can stay close to
  current output.
- If any candidate is a subpath, include one plain sentence:

```text
Only these listed values are used by prompts. Do not cache full objects like
`concept` unless you intentionally want every field in that object sent to the
model.
```

This sentence is agent-facing and important. It explains why the recommendation
changed without exposing implementation internals.

Avoid telling agents to write "cached above" in prompts. Use wording like:

```text
After adding a value to ## Cache, remove the `${...}` template from the prompt
body. Keep useful plain-text labels such as `Title:` or `Core idea:`, but do
not repeat the cached value.
```

If that gets too long for this fix, keep the renderer terse and rely on the
guide follow-up.

Headline derivation:

- Keep JSON/context field names stable where practical, but do not let the text
  headline say "declare 1 input" when the actual edit is two subpath cache
  entries.
- `warning_catalog.resolve_headline_for` currently derives `inputs_phrase` from
  `affected_input_count`. Update that derivation so subpath findings render as
  "entry in ## Cache" / "entries in ## Cache" or another plain user-facing
  phrase.
- Default text should show exact edits: file, `## Cache` entries to add, and
  per-node `prompt_cache:` entries to add, and prompt-body templates to remove
  per node. This is more useful to first-contact agents than
  provider/cache-prefix mechanics.

### 7. Keep Full-Root Consolidation Out Of The First Patch

Do not implement "if subpaths are too small, suggest caching full root" in this
Bug 4 patch.

Rationale:

- It is a tradeoff, not a safe default.
- It has semantic implications that need careful wording.
- Same-workflow has `cache.consolidate-to-root-recommended`; sub-workflow
  parity can be a follow-up once template-honest correctness is restored.

For this patch:

- If subpaths are below threshold, classify honestly as `refactor` or
  `model_switch` based on the subpath total.
- Do not use the full root size to upgrade the recommendation.

### 8. JSON Contract

JSON is lower priority, but keep it coherent.

Existing `inputs[]` objects can gain fields without a format bump only if the
project's current format policy allows additive fields. If not, bump the JSON
format version.

Suggested additive fields:

```json
{
  "child_input_name": "concept",
  "child_cache_ref": "concept.core_idea",
  "parent_value_expr": "concept",
  "parent_cache_ref": "concept.core_idea",
  "tokens_estimated": 1234
}
```

Do not optimize JSON polish in this task. Make text correct first.

JSON compatibility note:

If keeping `child_input_name` for existing consumers, do not overload it to mean
the cache ref. Add `child_cache_ref` and update text renderers to prefer it.
Overloading one field would make the code harder for future agents to reason
about than a small additive field.

Impact surfaces to update:

- `src/pflow/core/cache_analysis/render_json.py`: include
  `child_cache_ref` / `parent_cache_ref` in both warning context inputs and
  `per_call[].cross_workflow_inputs[]`.
- `src/pflow/core/cache_analysis/__init__.py`: update format/version notes that
  currently describe `child_input_name` as the recommended cache name.
- `src/pflow/mcp_server/tools/execution_tools.py`: update the MCP tool
  docstring so agents do not learn the old root-input interpretation.

## Tests

### Unit / Analyzer Tests

Add or update tests in `tests/test_core/test_cache_analysis_per_id_emission.py`.

1. **Sub-workflow subpaths stay subpaths**

Scenario:

- Parent passes `concept: ${concept}`.
- Child has two LLM nodes:
  - `draft`: `Draft ${concept.title}`
  - `review`: `Review ${concept.core_idea}`
- `concept` parameter includes a large unused `private_notes` field.

Assertions:

- `cache.sub-workflow-cache-undeclared` emits candidates for
  `concept.title` and `concept.core_idea`.
- `diag.context["inputs"]` includes `child_cache_ref` values for the subpaths.
- `diag.context["savings_usd"]` is based on subpath tokens, not full object
  tokens, or is `None` if subpaths are below threshold.
- Rendered text does not suggest caching the full `concept` object.
- Per-call rows, when trace evidence is present, do not show full-object
  `concept` as `could_cache` for consumers that only use subpaths.

2. **Direct root use remains root**

Scenario:

- Child prompt uses `${concept}` directly.

Assertions:

- Recommendation still names `concept`.
- This preserves existing behavior for workflows that genuinely send the full
  object today.

3. **Mixed root and subpath use**

Scenario:

- One consumer uses `${concept}`.
- Another uses `${concept.title}`.

Assertions:

- Root cache entry `concept` is recommended for the root-consuming node.
- Subpath cache entry `concept.title` is still recommended for the subpath-only
  node.
- The subpath-only node is not told to cache full `concept`.

Rationale:

- Full-object exposure is current semantics only for the node that already uses
  `${concept}`. It is not honest to expand that exposure to other nodes that
  only use `${concept.title}`.

4. **Renamed parent expression maps suffix correctly**

Scenario:

- Parent passes `concept: ${song.concept}`.
- Child prompt uses `${concept.title}`.

Assertion:

- Parent token resolution uses `${song.concept.title}`, not full
  `${song.concept}`.

5. **Trace invocation fallback resolves child suffix**

Scenario:

- Parent passes `concept: ${song.concept}`.
- Trace contains the resolved workflow-node invocation input:
  `node_params.inputs.concept = {"title": "...", "unused": "huge..."}`.
- Child prompt uses `${concept.title}`.

Assertions:

- Token estimate uses `title`, not the full invocation input object.
- This should fail if `_resolve_input_at_workflow_node_invocation` continues to
  return the full `inputs[child_input_name]` without applying the child suffix.

6. **Row-level cross-workflow projection uses subpaths**

Scenario:

- Same as test 1, but with a trace that creates per-call child rows.

Assertions:

- `PerCallRow.cacheable_tokens_estimated` for `draft` is based on
  `concept.title`.
- `CrossWorkflowInputContribution` includes `child_cache_ref="concept.title"`.
- The per-call table note names the used value, not full `concept`.

7. **Duplicate parent origins do not silently pick one estimate**

Scenario:

- Two parent workflow nodes call the same child with different parent refs:
  `concept: ${small.concept}` and `concept: ${large.concept}`.
- Child prompt uses `${concept.title}`.

Assertions:

- The recommendation does not claim one precise token/savings number unless the
  estimates agree.
- Output names that multiple parent origins feed the same child cache entry, or
  marks the estimate unmeasurable.

8. **Unresolvable subpath remains unmeasurable**

Scenario:

- One subpath resolves and one subpath cannot be resolved from parameters, memo,
  or trace.

Assertions:

- The consumer projection does not treat the missing subpath as `0`.
- Text says the estimate is incomplete/unmeasurable rather than below-minimum
  with a precise total.

9. **Path-aware declaration coverage**

Assertions:

- Declared `concept` suppresses an undeclared recommendation for
  `concept.title` in this patch.
- Declared `concept.title` does not suppress `concept.body`.
- Declared `concept` does not suppress `conceptual.title`.
- Declared `concept.title` does not suppress `concept.title_suffix`.

10. **`params.inputs` indirection cleanup**

Scenario:

- Child node has `params.inputs: {title: ${concept.title}}` and prompt body
  uses `${title}`.

Assertions:

- Recommended cache entry is `concept.title`.
- Prompt-body cleanup tells the agent to remove `${title}` from that node.

11. **No-trace structural projection stays subpath-aware**

Scenario:

- Static/no-trace analysis with repeated subpath consumers.

Assertions:

- The trace-needed note still appears when appropriate.
- It does not reason from full `concept` when the relevant refs are
  `concept.title` / `concept.body`.

12. **Prompt-cache-incomplete takes over for declared subpaths**

Scenario:

- Child has `## Cache` entry `concept.title`, but consumer nodes omit
  `prompt_cache: [concept.title]`.

Assertions:

- `cache.sub-workflow-cache-undeclared` is suppressed for `concept.title`.
- Existing `cache.prompt-cache-incomplete` carries the action.

### Existing Canary Update

Extend:

- `tests/test_core/test_cache_analysis_analyze.py::test_per_call_could_cache_populated_for_score_choruses_with_real_trace`

Assertions:

- The chorus-chooser recommendation should not treat `concept` as a full-value
  cache chunk when the relevant consumer only uses subpaths.
- If `concept.core_idea` and `concept.title` are present, they are named in
  the structured context or rendered body.

### Renderer Tests

Add a renderer-level guard in `tests/test_core/test_cache_analysis_renderers.py`.

Input:

- Synthetic `cache.sub-workflow-cache-undeclared` diagnostic with subpath
  candidates.

Assertions:

- Text says subfields are used.
- Text includes exact edit instructions: add these entries to `## Cache`, then
  add these `prompt_cache:` entries, then remove these templates from these
  prompt bodies.
- Text does not read as a clean "cache full input, saves X" instruction.
- Text remains agent-facing, with no `child_cache_ref` or internal field names.

Also add at least one integrated `analyze(...) -> render_text(...)` test for
the `05b` shape. Synthetic diagnostics are not enough; they can pass while
analyzer-produced context still says `child_input_name=concept` and the
headline still says "1 input."

### Baseline

Update:

- `.taskmaster/tasks/task_159/baseline/04-warning-catalog/05b-cache.sub-workflow-cache-undeclared-subpath/expected-stdout.txt`

Likely update:

- "declare 1 input" becomes "add 2 entries to ## Cache" or similar.
- Bullets list `article.title` and `article.body`, not full `article`.

Re-run or inspect lyrics-generator baseline after implementation:

- `.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`
- `.taskmaster/tasks/task_159/baseline/12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt`
- `.taskmaster/tasks/task_159/baseline/12-real-world-lyrics-generator/02-analyze-cache-json/expected-stdout.txt`

Keep direct-root behavior covered:

- `.taskmaster/tasks/task_159/baseline/04-warning-catalog/05-cache.sub-workflow-cache-undeclared/expected-stdout.txt`

Do not blindly regenerate. Read the drift as a fresh agent first.

After implementation, run a targeted grep and inspect each hit:

```bash
rg "child_input_name|cacheable inputs|declare .*input|input\\(s\\)" tests/test_core src/pflow/core/cache_analysis src/pflow/mcp_server/tools/execution_tools.py
```

Update only assertions and docs whose meaning changed. Keep direct child-input
root cases asserting the old wording where it remains correct.

## Non-Goals

- Do not rewrite global summary math for already-declared cache rows.
- Do not implement sub-workflow full-root consolidation tradeoffs in this patch.
- Do not add a new warning ID unless a warning is truly needed. This is a
  correction to an existing recommendation path.
- Do not change provider cache rendering.
- Do not change parser syntax.
- Do not make JSON perfect at the expense of text clarity.

## Verification Commands

Use the sandbox-safe skill guidance:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest \
  tests/test_core/test_cache_analysis_per_id_emission.py \
  tests/test_core/test_cache_analysis_analyze.py \
  tests/test_core/test_cache_analysis_renderers.py \
  -q
```

Then run targeted baseline or manual CLI checks:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  .taskmaster/tasks/task_159/baseline/04-warning-catalog/05b-cache.sub-workflow-cache-undeclared-subpath/workflow.pflow.md \
  article='<representative json>'
```

For lyrics-generator fixture:

```bash
SOURCE_JSON=$(.venv/bin/python -c 'import json, pathlib; print(json.dumps([pathlib.Path(".taskmaster/tasks/task_159/baseline/_shared/long-stable-text.txt").read_text()[:3000]]))')

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  .taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md \
  --from-trace .taskmaster/tasks/task_159/baseline/_shared/fixtures/live-gemini-lyrics-generator.trace.json \
  sources="$SOURCE_JSON"
```

Before finalizing, read the changed text output directly and ask:

```text
Would a fresh AI agent know exactly what to edit without learning pflow internals?
Would following the recommendation expose more prompt content than the workflow
currently exposes?
```

## Expected Implementation Size

Target production size: 150-300 LOC.

If the patch grows far beyond that, pause and inspect whether the old root-input
abstraction is still being preserved too deeply. The intended simplification is
to make prompt refs the candidate source, not to carry a parallel correction
model throughout the analyzer.

Target tests: 200-400 LOC.

Baseline churn is expected but should be read manually.

## Rollback / Safety

This is a static-analysis recommendation change. It should not affect runtime
execution, provider cache rendering, memo cache keys, or workflow parsing.

If implementation becomes risky, the reversible fallback is:

- Keep current recommendations for direct root refs.
- Suppress savings and add semantic warning text for subpath-only refs.

That fallback is safe but less useful. Prefer the template-honest candidate
fix unless implementation reveals an integration blocker.
