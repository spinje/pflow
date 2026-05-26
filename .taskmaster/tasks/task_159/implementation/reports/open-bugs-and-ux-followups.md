# Task 159 Follow-ups: Open Bugs and UX Issues

Forward-looking backlog of unresolved cache/analyzer/CLI UX items after the
prompt-caching follow-ups-2 PR merges. Closed items are not duplicated here
— see `follow-ups-2-progress-log.md` for shipped-work chronology and
closeout reasoning.

Scope rules:

- Includes only items with a clear user/agent failure mode and a plausible
  fix.
- Excludes anything that shipped in Task 159 or the follow-ups-1 / -2 PRs.
- Excludes very minor polish or speculative ideas where it is not clear
  changing behavior would improve pflow.
- Groups related observations into actionable backlog items rather than
  preserving original scratchpad numbering.

## GitHub Tracking

Items below cross-reference GitHub issues where tracking already exists.
Items without a GH link have no standalone tracking; the PR that closes
follow-ups-2 will reference this doc as the catch-all backlog.

Actively-tracked related issues (left open after this PR):

- **[#369](https://github.com/spinje/pflow/issues/369)** — within-batch
  heterogeneous-model fragmentation (covers item 4 below; narrower).
- **[#400](https://github.com/spinje/pflow/issues/400)** — `-o` flag +
  `--only` batch UX (covers item 13 below; explicitly externalized from
  the prompt-cache branch in Bundle 9).
- **[#368](https://github.com/spinje/pflow/issues/368)** — Opus 4.7
  reasoning-effort constraint (related to item 5 below; needs constraint
  shape before it can be implemented).
- **[#366](https://github.com/spinje/pflow/issues/366)** — Trace 2.2
  per-event `workflow_path` stamping (substrate for future cross-workflow
  attribution work; Bundle 8 used `_pflow_child_workflow_paths` runtime
  field as a tactical workaround, but #366's forward-compat investment
  remains valid).

## Priority Map

Highest-value open items, ranked by agent impact:

1. Cross-consumer prompt-file index (item 12) — biggest new-coverage win.
2. Cross-workflow repeated root-value discovery (item 12a) — biggest
   missed real-workflow savings opportunity found after the follow-ups-2
   fixes.
3. Per-item `prompt_cache` for batch items (item 12b) — removes a
   real split-node workaround and recovers cleaner parallel workflow shape.
4. Heterogeneous-model fragmentation actionability (item 4) — biggest
   accuracy win for batch-with-mixed-models workflows.
5. Provider TTL expiry / static TTL risk detection (item 1) — last big
   correctness gap in `--from-trace` output.
6. Dynamic-before-static late-tail scanning (item 2) — partial fix
   shipped in Cache-ready-opportunity Phase 4; this item is the
   remaining late-tail discovery work.

Everything else is feature expansion, polish, or deferred-to-own-task.

## Analyze-cache Correctness

### 1. Provider prompt-cache TTL expiry detection + static TTL risk prediction

Two related gaps in TTL-awareness. Currently the analyzer has no way to
flag when a workflow is likely to outrun its declared cache TTL —
neither at runtime (no provider TTL expiry detection) nor statically (no
duration-vs-TTL comparison).

**Static side**: a workflow with `## Cache - ttl: 5m` but expected
runtime of many minutes will write cache that expires before later reads
fire. Users only learn after a run, and long paid workflows may waste
cache writes.

**Trace side**: an old analyzer branch tried to infer provider
prompt-cache TTL expiry from local memo-cache age. That wrong inference
was removed (Task 159 base). There is no replacement using actual trace
write/read timestamps for the same provider cache prefix.

Desired fix:

- Static: compare declared TTL against trace-backed duration when a
  trace exists; conservative heuristics when no trace exists; warn when
  later cache consumers are likely to read after the declared TTL.
- Trace: use trace write/read timestamps for the same provider cache
  prefix; emit a new catalog ID when reads occur after declared/provider
  TTL windows.

Keep these separate from local memo-cache age — that conflation was the
historical bug.

### 2. Dynamic-before-static scanning can miss later opportunities

Partial fix shipped: Cache-ready-opportunity Phase 4 added structural
opportunities for batch dynamic-ref reorder cases via the
`cache_opportunity` component model. The remaining gap is the
late-tail scanning case.

`_find_batch_static_tail_after_dynamic` returns after the first per-item
reference. If the first stable tail after that reference is
unmeasurable, later measurable stable sections remain hidden.

Trigger shape: prompts with multiple dynamic refs interleaved with
stable sections, where the first post-dynamic section cannot be
measured but a later section could be.

Why it matters: the analyzer can under-report prompt-reordering
opportunities in complex batch prompts.

Desired fix:

- Continue advisory scanning after unmeasurable suffixes.
- Preserve exact projection conservatism: do not fabricate exact savings
  from unmeasurable regions.

### 3. Greenfield cost projection can say unavailable despite enough data

In small greenfield experiments, the Summary block can report `Cost per
run: unavailable` even when the analyzer appears to know the model,
static batch size, and input token estimate.

Trigger shape:

- No trace.
- Statically priced model.
- Static batch items.
- Resolved token estimates.

Why it matters: users receive less cost feedback than the analyzer may
be able to provide.

Desired fix:

- Audit summary cost gating for estimator-tier evidence.
- Emit no-cache hypothetical cost when model pricing, input estimates,
  output assumptions, and batch size are sufficient.
- If output tokens are the blocker, say that directly.

### 4. Heterogeneous-model cache fragmentation is not actionable enough

Output can report heterogeneous models in a batch without clearly tying
that fact to provider-cache fragmentation or a recommendation.

Trigger shape: a batch where items use different models, such as a mix
of Gemini variants.

Why it matters: users may not understand that provider prompt caches
are model-scoped. Cross-model batch items cannot share the same
provider cache prefix.

Desired fix:

- Strengthen or emit `cache.heterogeneous-models-fragment-cache` when
  batch model variation materially fragments cache reuse.
- Include token-weighted impact where possible.
- Explain that each model writes/reads its own cache.

A draft implementation fragment lives at
`.taskmaster/tasks/task_159/implementation/reports/cache-heterogeneous-models-fragment.md`.

GitHub tracking:
[#369](https://github.com/spinje/pflow/issues/369) tracks within-batch
heterogeneous-model fragmentation; this item additionally covers the
agent-UX side of making the output actionable when heterogeneity is
already known.

### 5. Provider-specific constraint validation beyond Anthropic+thinking

Bundle 3 closed the most-cited case
(`llm.thinking-temperature-mismatch`, Anthropic + extended thinking +
non-1 temperature) and explicitly scoped the broader item to "needs
empirically-verified failure modes."

Specific sub-cases without empirical grounding in this codebase:

- **GH [#368](https://github.com/spinje/pflow/issues/368) — Opus 4.7
  reasoning-parameter constraint**: referenced by issue number only; the
  specific constraint shape (which parameter, which failure mode, which
  provider error string) is not documented anywhere actionable. Cannot
  implement without knowing the actual constraint.
- **OpenAI reasoning models** (`gpt-5*` / `o1*` / `o3*` / `o4*`)
  rejecting `temperature`: industry knowledge but zero
  documentation/tests/examples in this codebase. Exact behavior varies
  by model and version (o1 series originally hard-rejected non-1 temp;
  newer models may silently downgrade). Adding a validator without
  empirical verification risks false positives.
- **Gemini constraints**: general generation parameters remain permissive
  in existing tests, but below-min explicit cache/prewarm behavior now has
  an empirically verified UX gap; see item 5a.
- **`max_tokens` caps**: no awareness anywhere; would need
  provider-specific tables.

Reopen criteria for any sub-case:

- A specific failure mode reported with verbatim provider error string.
- A reproducible failing combination in a small `.pflow.md`.
- The constraint verified across multiple model versions within the
  affected provider family.

Then mirror the Bundle 3 pattern: new catalog row, `_extract_X_violation`
helper in `data_flow.py`, wire into `_validate_data_flow`, per-id
sample, emission test, baseline case, MCP docstring update,
`_is_cache_focused_for_advisory` predicate update.

### 5a. Dry-run does not surface below-min Gemini prewarm fallback

Runtime now handles a below-min `prewarm: true` batch prefix much better:
it attempts the synthetic warmup, catches Gemini's "Cached content is too
small" error, disables prewarm for that node, completes the batch, and emits
`cache.prewarm-disabled-below-min`.

The remaining UX gap is that `--dry-run` still does not warn even when the
static batch prefix is already known to be below the provider threshold.

Trigger shape:

- Gemini-backed batch LLM node.
- `prewarm: true`.
- Stable prefix before the first `${item.*}` reference is below Gemini's
  explicit cache minimum.

Why it matters: users run `--dry-run` specifically to learn what will happen
before spending on a workflow. In this case the runtime already diagnoses the
issue, but only after an actual run.

Desired fix:

- Make dry-run emit the same cache-focused warning class, or a dry-run
  equivalent, when static analysis can prove the prewarm prefix is below the
  relevant provider minimum.
- Validation can remain permissive if desired; the important fix is that
  dry-run previews "prewarm will be disabled / will not help" before runtime.

Verified repro:

```bash
pflow scratchpads/pflow-cache-repros/repro-01-prewarm-below-min.pflow.md --dry-run
pflow scratchpads/pflow-cache-repros/repro-01-prewarm-below-min.pflow.md --no-cache --report
```

Current behavior on 2026-05-20:

- `--dry-run`: no warning.
- Runtime: completes with `cache.prewarm-disabled-below-min`.

## Analyze-cache Evidence and Iteration UX

### 6. No diff view for recommendation changes across iterations

Recommendation counts can shrink, grow, or change category as the user
edits workflows. This is correct behavior, but the analyzer does not
show what changed since the previous analysis.

Trigger shape: optimization loops where the user repeatedly changes
workflow cache declarations, reruns, and re-analyzes.

Why it matters: agents cannot easily tell which edits fixed prior
findings and which new findings were introduced.

Desired fix:

- Add `analyze-cache --diff <prior-report-or-trace>` or similar.
- Report recommendations added, removed, and changed.
- Keep stable IDs/locations so agents can track progress across
  iterations.

### 7. Richer `--list-traces` drift status enums and structured stale-memo arrays

Bundle 6 shipped `--list-traces` with counts and a per-trace
drift-count field. Two follow-on polish items were noted as deferred
during the Bundle 6 review pass because they expand the public JSON
schema beyond the additive contract used for the initial ship:

- Richer drift status enum (e.g.
  `fresh` / `stale_memo` / `model_drift` / `partial_match` instead of
  the current count + null).
- Structured stale-memo node arrays so consumers can target which
  specific nodes are stale, not just how many.

Defer until a real consumer needs them; the current contract covers the
common autoload + listing case.

### 8. Template-reference skipped-analysis notes need clearer guidance

Notes such as "template reference couldn't be resolved at analysis
time" are repeated without explaining whether this is concerning,
whether runtime cache still works, or what the user should do.

Trigger shape: static analysis paths that cannot resolve runtime-produced
values.

Why it matters: agents can overreact to normal static-analysis limits or
miss the fact that cache declarations can still work at runtime.

Desired fix:

- Classify these notes as informational when the workflow is otherwise
  valid.
- Explain that runtime cache can still fire if declarations are correct.
- Point to `pflow guide prompt-caching` for the relevant pattern.

### 8a. Local memo-cache traces still use "executed" / "calls" terminology inconsistently

The local memo-cache vs provider-cache summary is now much clearer than the
original behavior: it separates local pflow memo-cache reuse from provider
prompt-cache reads and tells users to run with `--no-cache` for a clean
provider-cache measurement.

Residual issue: the same trace-backed report can still say:

```text
Evidence: complete trace (1 LLM nodes executed)
...
calls 1
```

while the Summary correctly says:

```text
Local pflow cache reuse:     skipped 1 memo LLM call(s)
Provider cache in this run:  0 provider LLM call(s), 0 cache-read tokens
```

Trigger shape:

- Run a workflow once normally or with `--no-cache`.
- Run it again with pflow local memo-cache enabled so the LLM node is skipped.
- Analyze the second trace with `analyze-cache --from-trace`.

Why it matters: the Summary is now accurate, but agents often scan the header
and per-call table. Calling a memo-cache hit an "executed" LLM node or `calls 1`
can still lead users to over-read local memo-cache reuse as provider behavior.

Desired fix:

- Use distinct terms for historical/memoized LLM rows versus provider calls
  made during this trace.
- In the header, count provider-executed LLM calls separately from memoized
  LLM nodes represented by historical usage metadata.
- In the table, avoid `calls 1` for a provider call that did not happen in
  the analyzed trace, or mark it explicitly as `memoized`.

Verified repro:

```bash
pflow scratchpads/pflow-cache-repros/repro-07-local-memo-vs-provider-cache.pflow.md --no-cache --report -o answer_text
pflow scratchpads/pflow-cache-repros/repro-07-local-memo-vs-provider-cache.pflow.md --report -o answer_text
pflow analyze-cache scratchpads/pflow-cache-repros/repro-07-local-memo-vs-provider-cache.pflow.md --from-trace <second-trace> --all-rows
```

Current behavior on 2026-05-20: Summary says `0 provider LLM call(s)` while
header/table still report `1 LLM nodes executed` / `calls 1`.

### 9. Gemini cache telemetry caveat may still be too low-visibility

Gemini reports cache reads in telemetry, but writes may not show the
same way. The note explaining this can appear low in a Notes section.

Trigger shape: Gemini-backed workflows with prompt caching and trace
telemetry.

Why it matters: users may wrongly conclude caching is not working when
they do not see write telemetry.

Desired fix:

- Promote provider-specific telemetry caveats near Summary or the
  per-call table when relevant.
- Keep the wording provider-specific so non-Gemini workflows do not
  inherit Gemini caveats.

### 10. Recommendation language can still lead agents to write cache-aware prompt prose

After following advice to remove `${var}` from prompt bodies, an agent
may replace it with wording such as "see cached context above" or "as
cached above." The model does not see a cache boundary; it sees one
prompt.

Trigger shape: agent applies a mechanically correct cache edit but
writes prose that exposes pflow's implementation detail to the model.

Why it matters: cache edits can degrade prompt quality or confuse the
model.

Desired fix:

- Add guide examples showing how to refer to cached content by semantic
  label, not by cache mechanics.
- Optionally add an informational analyzer lint for phrases such as
  "cached above", "in the cache", or "context above."

### 11. "without recorded model" phrase is borderline-opaque to fresh agents

Bundle 7 flagged this during the fresh-agent cold-read review. The
phrase appears in the cost summary when LLM calls were made but no
model was recorded in `llm_usage`. The wording could mean either "API
didn't return it" or "pflow failed to record it" — neither is
self-explanatory.

Trigger shape: any LLM call where `llm_usage["model"]` is empty or
missing despite the call having happened.

Why it matters: agents triaging an unpriced cost summary cannot tell
whether to investigate the provider response, pflow's recording path,
or accept it as expected for a particular adapter.

Desired fix:

- Rewrite to name the source of the gap, e.g. `pricing unavailable for
  N call(s) where the model field was not returned by the provider`.
- Keep "we don't know" honest where genuinely unknown; do not fabricate.

## Cross-workflow / multi-workflow detection

### 12. Cross-consumer prompt-file index

Currently the analyzer cannot answer:

- "Which other workflows consume this `.prompt.md` file?"
- "If I add `prompt_cache` to one consumer, do other consumers also
  benefit / need a matching declaration?"
- "For `prompt: ${item.prompt}` with item values pointing at local
  prompt files, do those files share template variables that could be
  hoisted into cached context?"

Originally three scratchpad findings (S#15, S#17, S#20). All three
share a root cause: there is no `prompt_file → [consuming_node_ids]`
index, and no detector for shared variables across item-resolved prompt
files. Bundle 7 and Bundle 8 closeouts both explicitly defer this work
to its own task because the scope is larger than a single follow-up
bundle.

Trigger shapes:

- Multi-workflow project where two workflows reference the same
  external `.prompt.md` file, but only one declares `prompt_cache`.
- Batch LLM node with `prompt: ${item.prompt}` and item values pointing
  at multiple shared-template prompt files.
- Parallel sub-workflow fan-out where ≥2 children share overlapping
  `prompt_cache` declarations — should the parent emit a single warm
  node?

Desired fix (own task, est. 2–3 days):

- Cross-workflow walker extension in
  `core/cache_analysis/cross_workflow.py` to build a
  `prompt_file → [consuming_node_ids]` index across workflows discovered
  by the same walker traversal.
- Detect shared template variables across item-resolved prompt files.
- New catalog warning when one consumer adds `prompt_cache` but other
  consumers lack a matching declaration.
- New catalog warning recommending a parent warm node when ≥2 parallel
  sub-workflow children share overlapping `prompt_cache`.

### Inlined repros

Both originally lived under `scratchpads/pflow-cache-repros/`
(throwaway by design — preserved here so the bug shape doesn't die
with the scratchpads).

**Repro A — opaque prompt-file batch.** The batch LLM node references
`prompt: ${item.prompt}` where each item value is a local prompt file.
Both prompt files reference the same `${source_text}` variable. The
analyzer does not currently inspect the referenced prompt files, so the
shared variable is invisible to it.

```markdown
# Repro: Opaque Prompt-File Batch

## Inputs

### source_text

Shared text used by both prompt files.

- type: string
- required: false
- default: "This is shared source text. Repeat it mentally as if it were much larger."

## Steps

### analyze

Run two prompt files that both reference `${source_text}`.

- type: llm
- temperature: 0
- reasoning_effort: none
- max_tokens: 16
- prompt: ${item.prompt}

\`\`\`yaml batch
items:
  - prompt: ./prompt-a.md
  - prompt: ./prompt-b.md
parallel: true
\`\`\`

## Outputs

### results

- source: ${analyze.results}
```

Where `prompt-a.md` and `prompt-b.md` both contain:

```markdown
Shared source:

${source_text}

Task A / B: reply with one sentence about the source.
```

Verification: `pflow analyze-cache <wrapper>.pflow.md --no-trace-autoload --all-rows`.
Observed: `Cost data unavailable: run the workflow once for cost figures.`
No static recommendation that `prompt: ${item.prompt}` points at
local prompt files which share `${source_text}`.

**Repro B — shared prompt missing surrounding context.** A
`shared-context.prompt.md` was refactored to rely on context supplied
by the surrounding workflow (via `## Cache`/`prompt_cache:`). A second
workflow uses the same prompt file but doesn't declare the matching
`prompt_cache`. Both workflows validate; both execute and return `OK`.
The broken consumer fails silently — the prompt assumes context that
isn't there.

**The shared prompt** (`shared-context.prompt.md`):

```markdown
Use the source material from the surrounding context.

Return exactly:

OK
```

**The well-behaved consumer:**

```markdown
# With-Context Wrapper

## Inputs

### source_text

- type: string
- required: false
- default: "This source text is supplied as surrounding context."

## Cache

- ttl: 5m

\`\`\`cache
Source material:

${source_text}
\`\`\`

## Steps

### answer

- type: llm
- prompt_cache: [source_text]
- temperature: 0
- reasoning_effort: none
- max_tokens: 8
- prompt: ./shared-context.prompt.md
```

**The broken consumer** (missing `## Cache` + `prompt_cache:`):

```markdown
# Missing-Context Wrapper

## Steps

### answer

- type: llm
- temperature: 0
- reasoning_effort: none
- max_tokens: 8
- prompt: ./shared-context.prompt.md
```

Verification: `pflow <broken-consumer>.pflow.md --validate-only` passes;
runtime succeeds; neither validator nor analyzer flags that the prompt
prose assumes context the workflow does not supply. This is a
semantic/context-contract bug, not a template-variable bug — the fix
needs the cross-consumer prompt-file index described above to detect
which workflows consume each prompt file and compare their declared
`prompt_cache` against the prompt's prose assumptions.

### 12a. Cross-workflow repeated root-value discovery

The analyzer can still miss large repeated values when each individual
child workflow sees only one local use. This is distinct from the
prompt-file index above: the repeated content is visible only by following
root dataflow across multiple child workflows in sequence.

Real trigger from the lyrics workflow:

- `concept-chooser/generate-full-concepts` consumed the complete source
  analysis brief.
- `enforce-diversity/assign-diversity` consumed the same source analyses
  shortly afterward.
- Each child workflow looked locally reasonable: `concept-chooser` had one
  full-analysis call, and `enforce-diversity` had one huge call.
- Root/static analysis did not recommend the cross-workflow reuse because
  the repeated value was split across child workflow boundaries.

Why it matters: this was the largest late optimization found manually after
the analyzer-driven pass. After adding matching declared chunks to both
children, a targeted wrapper measured:

- `generate-full-concepts`: `284,865` input tokens, `284,480` cached.
- `assign-diversity`: `287,030` input tokens, `284,480` cached.
- Cost dropped from `$0.1183` to `$0.0156`.
- Runtime dropped from `150.433s` to `37.469s`.

Desired fix:

- Add a root-value lineage pass that detects large values passed into two
  or more child LLM workflows in sequence, even when each child has only one
  local consumer.
- Report candidate reuse keyed by rendered/root value lineage, not just
  local child workflow prompt structure.
- When direct proof requires trace data, emit a static warning with a
  paste-ready targeted replay/analyze command rather than staying silent.

Current verification:

```bash
pflow analyze-cache workflows/lyrics-generator/lyrics-generator.pflow.md --no-trace-autoload --all-rows
pflow analyze-cache workflows/lyrics-generator/concept-chooser/concept-chooser.pflow.md --no-trace-autoload --all-rows
pflow analyze-cache workflows/lyrics-generator/enforce-diversity/enforce-diversity.pflow.md --no-trace-autoload --all-rows
```

Current output shows the large rows as cache-ready/active after the manual
fix, but the original discovery still required a human audit. Preserve this
as a regression target by constructing a small parent workflow with two child
workflows that each consume the same large root input once.

### 12b. Per-item `prompt_cache` lists for batch LLM nodes

`prompt_cache:` is statically typed as an array today. That prevents a batch
item from selecting its own declared cache chunks:

````markdown
### generate

- type: llm
- prompt_cache: ${item.chunks}
- prompt: ${item.prompt}

```yaml batch
items:
  - prompt: ./focused.prompt.md
    chunks: []
  - prompt: ./full.prompt.md
    chunks: [brief]
parallel: true
```
````

Real trigger from the lyrics workflow:

- The ideal `concept-chooser` shape would keep Heart/Mind/Body/Full concept
  generation in one parallel batch.
- Only the Full item should receive the full source-analysis chunk.
- Adding `prompt_cache: [brief]` to the whole batch would leak the full
  source analysis into Heart/Mind/Body, breaking lens isolation.
- Because `prompt_cache: ${item.chunks}` does not validate, the Full item had
  to be split into its own LLM node.

Why it matters: the split-node workaround works and produced a large cost
drop, but it is structurally heavier and adds a sequential step. Per-item
cache lists would recover the cleaner parallel shape without changing model
semantics.

Desired fix:

- Support templated list-valued node parameters for batch items where the
  resolved value is an array, at least for `prompt_cache`.
- Preserve the existing chunk-order validation after template resolution.
- If this remains unsupported by design, replace the current type error with
  a direct message: `prompt_cache must be a static array; per-item prompt_cache
  is not supported`.

Verified repro:

```bash
pflow scratchpads/pflow-cache-repros/repro-14-dynamic-prompt-cache-list.pflow.md --validate-only
```

Current behavior on 2026-05-26:

```text
'${item.chunks}' is not of type 'array'
  At: nodes[0].prompt_cache

  → Change type from 'str' to 'array'
```

## Run Output and General CLI UX

### 13. `-o` flag dotted paths / `--only` batch UX

Tracked at [GH #400](https://github.com/spinje/pflow/issues/400) (S#13
externalized in Bundle 9). Three compounding issues for batch and
dict-output nodes:

1. `-o <node>.<subkey>` does not support dotted-path traversal.
2. Warning on miss gives no hint about which keys would resolve.
3. Default `--only <batch-node>` (no `-o`) streams the full `results`
   payload to stdout — high context cost for agents.

Out of scope for the prompt-cache branch (general CLI/iteration UX,
owned by Task 106). The companion failure-path UX shipped in this
branch (compact batch-item summaries for FAILED items); this issue is
the success-path equivalent.

### 14. Validation failures may not save partial traces consistently

Runtime failures save partial traces, but a validation failure after a
background run has begun may not save a trace.

Trigger shape: workflow starts or is queued for execution, then
validation fails before normal runtime trace finalization.

Why it matters: trace availability feels inconsistent, and
`analyze-cache` has no failed trace candidate to inspect.

Desired fix:

- Define the trace-saving policy for validation failures vs runtime
  failures.
- Make behavior consistent and document it.
- If validation failures intentionally do not save traces, make that
  explicit in output.

## Iteration / Measurement Workflow

### 15. Replay sub-workflow from trace inputs

(S#8.) When iterating on a single LLM node deep in a workflow, agents
must re-run the full upstream pipeline (long-running creative nodes,
multi-minute concept generation) before reaching the node they care
about. `--from-trace` exists for analysis but not for replay.

Trigger shape: optimization loops where the same sub-workflow node is
re-measured repeatedly with the same upstream inputs.

Why it matters: clean `--no-cache` measurement of a single deep node
is currently very expensive because most time is spent on unrelated
upstream work.

Desired fix (own task / feature, est. >1 week):

- New `pflow run --replay-node <node-id> --from-trace <trace>` flag
  that loads captured inputs for the target node from the trace and
  skips all upstream execution.
- Reports include a copy-pasteable replay command for failed batch items
  or downstream sub-workflows.

Defer until a real iteration loop hits this often enough to justify the
implementation cost.

## Documentation and Maintenance

### 16. Cache chunk byte boundaries are undocumented

Whitespace between chunks inside `## Cache` contributes to chunk bytes,
which can create parent/child prose mismatches such as leading blank
lines.

Trigger shape: users manually align parent and child cache chunks and
expect visual whitespace outside `${var}` lines not to affect chunk
identity.

Why it matters: small whitespace differences can break cache boundary
matching, but users do not have a precise model of what bytes belong to
each chunk.

Desired fix:

- Document exact cache chunk byte boundaries and whitespace behavior.
- Include examples with blank lines before/after `${var}`.
- Distinguish substantial model prompts (separate `.prompt.md` files
  appropriate) from tiny operational warmup prompts (S#18 — inline next
  to `prompt_cache` for auditability).
- If the current behavior is too surprising, consider an explicit
  delimiter or normalization strategy as a future design decision.

### 17. Stale CLAUDE.md trace-drift references

Some internal CLAUDE.md docs still reference `_trace_aligns_with_ir`
after the whole-trace drift gate was removed in Task 159 base.

Trigger shape: future agents reading implementation guidance for cache
analysis or runtime trace behavior.

Why it matters: stale docs point agents toward nonexistent code and the
old coarse trace-validity model.

Desired fix:

- Update affected CLAUDE.md docs to describe the current per-row trace
  evidence model.
- Remove references to `_trace_aligns_with_ir`.
- Prefer doing this during the Task 160 cache-analysis architectural
  refactor sweep.

## Internal Hygiene

Two small refactors flagged as deferred during Bundle 6's pre-merge
review pass. Both are non-blocking for users but affect future agent
review.

### 18. DRY the two `_*_memo_for_freshness_check` helpers

The three-state memo-freshness logic duplicates between `context.py`
and `token_estimation.py`. `token_estimation`'s variant could call
`context`'s and discard the unused `created_at` return slot.

Not a correctness bug; safe to consolidate during any future
cache-analysis refactor pass.

### 19. Remove `hasattr` fallback for `get_latest_for_node_with_cache_key`

Bundle 6 added the new `MemoizationCache` method as additive on top of
the legacy `get_latest_for_node()`. The new freshness-check path uses
`hasattr(memo_cache, "get_latest_for_node_with_cache_key")` and falls
back when the method is absent — load-bearing for legacy test mocks
that don't implement the new method.

Once all test mocks implement the new method, the `hasattr` fallback
and the `ctx is None` paths can be removed.
