# Task 159 Follow-ups: Open Bugs and UX Issues

This file preserves unresolved issues from the Task 159 scratchpads before
those scratchpads are deleted.

Scope rules:

- Includes only issues with a clear user or agent failure mode and a plausible
  fix.
- Excludes fixed items already captured in GitHub issue #395.
- Excludes very minor polish, speculative ideas, and items where it is not
  clear that changing behavior would improve pflow.
- Groups related observations into actionable backlog items instead of
  preserving scratchpad numbering.

## GitHub Tracking Audit

Checked against GitHub issues on 2026-05-13. Exact matches and genuinely
related issues are linked inline below. Most items in this file are not yet
tracked as standalone GitHub issues; issue #395 is intentionally not counted as
tracking because it only catalogs fixed PR #396 work.

Exact or substantially matching tracking found:

- Item 3: [#394](https://github.com/spinje/pflow/issues/394) tracks the
  remaining `PerCallRow.input_tokens_estimated` mixed-unit contract.
- Item 16: [#385](https://github.com/spinje/pflow/issues/385) tracks the
  provider-error-first and large batch-payload formatting problem.

Related but not fully covering tracking found:

- Item 4: [#393](https://github.com/spinje/pflow/issues/393) tracks the
  runtime defense for below-min prewarm prefixes, but not the analyzer
  recommendation branch described here.
- Item 12: [#369](https://github.com/spinje/pflow/issues/369) tracks the
  narrower within-batch heterogeneous-model fragmentation detector.
- Item 17: [#123](https://github.com/spinje/pflow/issues/123) covers
  unknown-model pricing warnings and text cost-summary gaps, but not this exact
  `pricing unavailable for: unknown` runtime wording.
- Item 18: [#385](https://github.com/spinje/pflow/issues/385) overlaps because
  it covers concise batch failure context and avoiding huge item dumps.
- Item 21: [#385](https://github.com/spinje/pflow/issues/385) includes the
  Anthropic temperature/thinking validator gap as one concrete case, and
  [#368](https://github.com/spinje/pflow/issues/368) covers a related Opus 4.7
  reasoning-parameter provider constraint. Neither tracks the general provider
  constraint validation backlog item completely.

## Priority Map

Highest-value open items:

1. Full shadowed-cache summary math still uses an inflated baseline.
2. Combined `prewarm: true` + `prompt_cache` hides additive prewarm evidence.
3. `PerCallRow.input_tokens_estimated` still has mixed units.
4. Prewarm recommendation can still ignore provider minimum in one path.
5. Run output still hides the actionable provider error behind large payloads.
6. Runtime cost summary still says `pricing unavailable for: unknown`.

## Analyze-cache Correctness

### 1. Full shadowed-cache summary math remains deferred

Original failure: when a cache chunk contains a large object but the prompt body
uses only a tiny subfield, analyzer savings can still compare against a
strawman baseline: "send the full cache prefix uncached." The PR fixed the
local `cache.prompt-body-shadows-cache` recommendation by adding body-only vs
with-cache cost disclosure, but it did not rewrite the broader summary math.

Trigger shape:

- `## Cache` declares a parent object or large bundle.
- One or more prompt bodies reference only a small subpath, such as
  `${concept.core_idea}` or `${bundle.tiny_field}`.
- Summary/projection math treats the full cached object as the no-cache
  baseline.

Why it matters: the summary can still overstate savings or make cache look
beneficial when the real current prompt is much cheaper because it sends only
the referenced subfield. In correctness-sensitive prompts, caching the full
object can also expose context intentionally omitted from the prompt.

Desired fix:

- Compute the current prompt-body cost for the bytes actually used.
- Compare cache recommendations against that real current-state baseline.
- Suppress or clearly annotate summary-level savings when shadowed-cache
  evidence proves the summary comparison is not valid.

Trust boundary: the local recommendation disclosure is fixed and should be
kept. The open issue is the aggregate summary/projection model.

### 2. Combined `prewarm: true` + `prompt_cache` hides additive prewarm evidence

Original failure: when a batch node declares both `prompt_cache: [...]` and
`prewarm: true`, the analyzer reports the declared cache chunk but does not
show whether the prewarm prefix contributes additional cacheable bytes.

Trigger shape:

- Batch LLM node with declared `prompt_cache`.
- Same node also has `prewarm: true`.
- Prompt contains static bytes before the first per-item reference that are not
  already covered by the declared chunk.

Root cause: declared-cache evidence and batch-prefix evidence are treated as
competing sources for `cacheable_tokens_estimated`. If the declared chunk is
larger, the smaller prewarm-only contribution disappears from the row.

Why it matters: agents cannot verify whether `prewarm: true` is doing useful
work beyond the declared cache. This is especially important because prewarm
has a wall-clock cost.

Desired fix options:

- Add an explicit `batch_prefix_extra_tokens` or equivalent field for combined
  rows.
- Or sum declared-cache and prewarm-prefix contributions when they occupy
  distinct message regions and do not overlap.
- Render the combined evidence clearly in text and JSON so users can decide
  whether prewarm is worth keeping.

### 3. `PerCallRow.input_tokens_estimated` still has mixed units

Original failure: PR #396 fixed `cacheable_tokens_estimated` to be per-call,
but `input_tokens_estimated` still has mixed producer behavior. Some row types
store per-call input tokens, while some dynamic-batch trace and repeated-trace
paths can still behave like cohort totals.

Trigger shape: dynamic batch traces or repeated trace rows where input tokens
are produced from aggregate trace evidence.

Why it matters: compensating divides and defensive clamps remain in analyzer
code because not every producer obeys one unit contract. This makes future
cache math fragile and harder to reason about.

Desired fix:

- Declare `PerCallRow.input_tokens_estimated` as per-call by contract.
- Update all producers to honor that contract.
- Delete compensating divides that only exist because the field is mixed-unit.
- Update tests that currently encode the mixed-unit behavior.

GitHub tracking: exact match
[#394](https://github.com/spinje/pflow/issues/394).

### 4. Prewarm recommendation can still ignore provider minimum in one path

Original failure: after adding `cache.batch-prewarm-below-min`, one adjacent
recommendation path remains asymmetric. `_batch_prewarm_recommendations` has an
existing-prefix-evidence branch that can emit `cache.batch-prewarm-recommended`
without applying the provider-minimum threshold check used by the prompt-walk
branch.

Trigger shape:

- Analyzer has batch-prefix evidence for a node.
- `prewarm` is not declared yet.
- The inferred prefix is non-zero but below the model's explicit cache minimum.

Why it matters: the analyzer can still tell a user to add `prewarm: true` for a
prefix that would not fire at the provider. The below-min warning appears only
after the user adds prewarm, which is too late.

Desired fix:

- Apply the same provider-minimum guard in the existing-prefix-evidence branch
  before emitting `cache.batch-prewarm-recommended`.
- If the prefix is below minimum, emit the appropriate below-min or conditional
  advice instead of a confident prewarm recommendation.

GitHub tracking: related issue
[#393](https://github.com/spinje/pflow/issues/393) covers the runtime-side
prewarm below-min defense. It does not fully cover this analyzer-side
recommendation path.

### 5. Provider prompt-cache TTL expiry detection is still missing

Original failure: the old analyzer tried to infer provider prompt-cache TTL
expiry from local memo-cache age. That wrong inference was removed, but there
is not yet a replacement for real provider TTL expiry detection.

Trigger shape:

- Workflow declares a provider prompt-cache TTL.
- Trace contains enough timing data to compare cache writes and later reads.
- Later reads might occur after the provider cache entry should have expired.

Why it matters: users no longer get the wrong TTL recommendation, but they also
do not get a correct warning when a long workflow is likely to outrun its prompt
cache TTL.

Desired fix:

- Use trace write/read timestamps for the same provider cache prefix.
- Emit a new catalog ID when reads occur after declared/provider TTL windows.
- Keep this separate from local memo-cache age.

### 6. Static TTL risk prediction is still missing

Original failure: users can declare a short cache TTL on a workflow whose total
runtime is much longer, but the analyzer does not warn before a trace proves
the issue.

Trigger shape: a workflow with `## Cache - ttl: 5m` but expected runtime of
many minutes before later cache reads.

Why it matters: users only learn about likely TTL problems after a run, and
long paid workflows may waste cache writes.

Desired fix:

- Compare declared TTL against trace-backed duration when a trace exists.
- Use conservative heuristics when no trace exists.
- Warn when later cache consumers are likely to read after the declared TTL.

## Analyze-cache Evidence and Iteration UX

### 7. No `analyze-cache --list-traces`

Original failure: users have no direct command to inspect traces that
`analyze-cache` could load. They must know about `~/.pflow/debug/` and infer
which trace autoload selected.

Trigger shape: multiple traces exist for a workflow, especially after failed
and successful iteration runs.

Why it matters: trace transparency improved in PR #396, but users still lack a
discovery command when they want to choose a specific trace or understand
alternatives.

Desired fix:

- Add `pflow analyze-cache --list-traces <workflow>`.
- Show trace filename, recorded time, final status, workflow match, rough
  coverage, and whether autoload would choose it.
- Include suggested `--from-trace <path>` commands.

### 8. No diff view for recommendation changes across iterations

Original failure: recommendation counts can shrink, grow, or change category as
the user edits workflows. This is correct behavior, but the analyzer does not
show what changed since the previous analysis.

Trigger shape: optimization loops where the user repeatedly changes workflow
cache declarations, reruns, and re-analyzes.

Why it matters: agents cannot easily tell which edits fixed prior findings and
which new findings were introduced.

Desired fix:

- Add `analyze-cache --diff <prior-report-or-trace>` or similar.
- Report recommendations added, removed, and changed.
- Keep stable IDs/locations so agents can track progress across iterations.

### 9. Trace-backed projections can feel stale after workflow edits

Original observation: this is not a correctness bug. Trace data records what
happened before edits. However, after a user changes workflow source or a code
node's output shape, trace-backed projections can still reflect old data.

Trigger shape:

- User changes a workflow or upstream code node after recording a trace.
- Then runs `analyze-cache --from-trace <old-trace>`.

Why it matters: users may read trace-backed token sizes as current when they
actually describe the old run.

Desired fix:

- Compare trace capture time or recorded source fingerprints against workflow
  file modification times when available.
- Show a gentle hint such as "trace predates recent workflow changes; rerun for
  current projection."

### 10. Greenfield cost projection can say unavailable despite enough apparent data

Original failure: in small greenfield experiments, the Summary block reported
`Cost per run: unavailable` even when the analyzer appeared to know the model,
static batch size, and input token estimate.

Trigger shape:

- No trace.
- Statically priced model.
- Static batch items.
- Resolved token estimates.

Why it matters: users receive less cost feedback than the analyzer may be able
to provide.

Desired fix:

- Audit summary cost gating for estimator-tier evidence.
- Emit no-cache hypothetical cost when model pricing, input estimates, output
  assumptions, and batch size are sufficient.
- If output tokens are the blocker, say that directly.

### 11. Dynamic-before-static scanning can miss later opportunities

Original limitation: `_find_batch_static_tail_after_dynamic` returns after the
first per-item reference. If the first stable tail after that reference is
unmeasurable, later measurable stable sections can remain hidden.

Trigger shape: prompts with multiple dynamic refs interleaved with stable
sections, where the first post-dynamic section cannot be measured but a later
section could be.

Why it matters: the analyzer can under-report prompt reordering opportunities
in complex batch prompts.

Desired fix:

- Continue advisory scanning after unmeasurable suffixes.
- Preserve exact projection conservatism: do not fabricate exact savings from
  unmeasurable regions.

### 12. Heterogeneous-model cache fragmentation is not actionable enough

Original failure: output could report heterogeneous models in a batch without
clearly tying that fact to provider-cache fragmentation or a recommendation.

Trigger shape: a batch where items use different models, such as a mix of
Gemini variants.

Why it matters: users may not understand that provider prompt caches are model
scoped. Cross-model batch items cannot share the same provider cache prefix.

Desired fix:

- Strengthen or emit `cache.heterogeneous-models-fragment-cache` when batch
  model variation materially fragments cache reuse.
- Include token-weighted impact where possible.
- Explain that each model writes/reads its own cache.

GitHub tracking: related issue
[#369](https://github.com/spinje/pflow/issues/369) tracks within-batch
heterogeneous-model fragmentation. It is narrower than this item because this
item is also about making the user-facing output actionable when heterogeneity
is already known.

### 13. Template-reference skipped-analysis notes need clearer guidance

Original failure: Notes such as "template reference couldn't be resolved at
analysis time" were repeated without explaining whether this was concerning,
whether runtime cache still works, or what the user should do.

Trigger shape: static analysis paths that cannot resolve runtime-produced
values.

Why it matters: agents can overreact to normal static-analysis limits or miss
the fact that cache declarations can still work at runtime.

Desired fix:

- Classify these notes as informational when the workflow is otherwise valid.
- Explain that runtime cache can still fire if declarations are correct.
- Point to `pflow guide prompt-caching` for the relevant pattern.

### 14. Gemini cache telemetry caveat may still be too low-visibility

Original failure: Gemini reports cache reads in telemetry, but writes may not
show the same way. The note explaining this can appear low in a Notes section.

Trigger shape: Gemini-backed workflows with prompt caching and trace telemetry.

Why it matters: users may wrongly conclude caching is not working when they do
not see write telemetry.

Desired fix:

- Promote provider-specific telemetry caveats near Summary or the per-call
  table when relevant.
- Keep the wording provider-specific so non-Gemini workflows do not inherit
  Gemini caveats.

### 15. Recommendation language can still lead agents to write cache-aware prompt prose

Original failure: after following advice to remove `${var}` from prompt bodies,
an agent may replace it with wording such as "see cached context above" or "as
cached above." The model does not see a cache boundary; it sees one prompt.

Trigger shape: agent applies a mechanically correct cache edit but writes prose
that exposes pflow's implementation detail to the model.

Why it matters: cache edits can degrade prompt quality or confuse the model.

Desired fix:

- Add guide examples showing how to refer to cached content by semantic label,
  not by cache mechanics.
- Optionally add an informational analyzer lint for phrases such as
  "cached above", "in the cache", or "context above."

## Run Output and General CLI UX

### 16. Run-failure error format buries the provider message

Original failure: batch failures printed the entire batch item payload before
the actionable provider error. In the reported case, an Anthropic
temperature/thinking constraint was buried after several KB of batch data.

Trigger shape: LLM/provider error inside a batch item whose input object is
large.

Why it matters: the user needs the provider error and node location first, not
the full batch item. Large payloads delay diagnosis and make logs harder for
agents to parse.

Desired fix:

- Render provider/root-cause error first.
- Then render node ID, workflow path, and concise batch item identity.
- Replace huge item values with a short preview, index, and/or content hash.
- Keep full payload in trace/debug output.

GitHub tracking: substantial match
[#385](https://github.com/spinje/pflow/issues/385).

### 17. Runtime cost summary says `pricing unavailable for: unknown`

Original failure: after a paid run, output could show a partial cost with
`pricing unavailable for: unknown` instead of naming the model or call source.

Trigger shape: one or more LLM calls use a model missing pricing metadata,
often from per-item model overrides.

Why it matters: users cannot tell which model lacks pricing or how much of the
run is uncosted.

Desired fix:

- Name unknown-priced models.
- Count affected calls.
- Prefer wording like `pricing unavailable for: gemini/gemini-3-flash-preview
  (3 of 237 calls)`.

GitHub tracking: related issue
[#123](https://github.com/spinje/pflow/issues/123) covers unknown-model pricing
warnings and text-mode cost-summary gaps. It does not exactly track the current
runtime wording `pricing unavailable for: unknown`.

### 18. Batch warnings show count without cause

Original failure: batch output reported a count such as `1 error(s) out of 4
items` without showing the one-line cause for each failed item.

Trigger shape: batch node with one or more failed items.

Why it matters: users must scroll through earlier output to learn whether the
failure was a timeout, provider error, validation error, or something else.

Desired fix:

- Under the batch warning, render `[item N] cause: <one-line message>`.
- Keep large payloads out of the summary.

GitHub tracking: related issue
[#385](https://github.com/spinje/pflow/issues/385) overlaps on concise batch
failure context and replacing huge item dumps with a fingerprint/preview.

### 19. "Blocking errors" can include fallback/error-path nodes

Original failure: validation could report an unknown MCP fallback node under
`Blocking errors` even though that node was only reachable through `on-error`
and the primary path could run.

Trigger shape: fallback/error-path node is invalid or unavailable, but normal
path analysis can continue.

Why it matters: "Blocking" implies the whole workflow cannot be analyzed or
executed, which overstates conditional-path issues.

Desired fix:

- Split truly blocking errors from conditional/error-path limitations.
- Explain which path is affected.

### 20. Negative "Actual savings" wording is confusing

Original failure: output could say `Actual savings ... adds ~$X vs no-cache`.
The label says savings, while the value means overhead.

Trigger shape: cache costs more than the no-cache projection for that run,
often due to first-run write cost or low cache reuse.

Why it matters: users have to infer that a positive "adds" value means cache
was more expensive.

Desired fix:

- Render `Overhead vs no-cache: +$X` when cache increases cost.
- Render `Savings vs no-cache: -$X` or equivalent when cache reduces cost.
- Avoid using "savings" as the label for both signs.

### 21. Validation-time provider constraints are not caught

Original failure: a run can fail after expensive upstream work because a
provider rejects a statically knowable parameter combination, such as Anthropic
thinking/reasoning with an invalid temperature.

Trigger shape:

- Model is statically known or default model is known.
- Provider-specific parameter constraint is statically checkable.
- Invalid combination appears in the workflow.

Why it matters: users can spend money and time before a deterministic provider
constraint failure appears.

Desired fix:

- Add validation for high-confidence provider constraints when model and params
  are statically resolvable.
- Emit a structured diagnostic pointing to the node and offending fields.

GitHub tracking: related issues
[#385](https://github.com/spinje/pflow/issues/385) includes the Anthropic
temperature/thinking validator gap as one observed case, and
[#368](https://github.com/spinje/pflow/issues/368) covers a related Opus 4.7
reasoning-parameter provider constraint. This item remains broader than both.

### 22. MCP sync-required errors do not suggest `pflow mcp sync`

Original failure: validation reported an `mcp-<service>-<tool>` node type as
unknown even when the service was registered but had zero synced tools.

Trigger shape: MCP service exists locally but `pflow mcp sync <service>` has
not populated tool definitions.

Why it matters: the direct fix is known, but the diagnostic does not mention
it. Users have to discover `pflow mcp list` or sync behavior separately.

Desired fix:

- When an unknown MCP node type matches a registered service with zero tools,
  include `pflow mcp sync <service>` in the diagnostic.

### 23. Validation failures may not save partial traces consistently

Original failure: runtime failures saved partial traces, but a validation
failure after a background run had begun did not save a trace.

Trigger shape: workflow starts or is queued for execution, then validation
fails before normal runtime trace finalization.

Why it matters: trace availability feels inconsistent, and analyze-cache has no
failed trace candidate to inspect.

Desired fix:

- Define the trace-saving policy for validation failures vs runtime failures.
- Make behavior consistent and document it.
- If validation failures intentionally do not save traces, make that explicit
  in output.

## Documentation and Maintenance

### 24. Cache chunk byte boundaries are undocumented

Original failure: whitespace between chunks inside `## Cache` contributes to
chunk bytes, which can create parent/child prose mismatches such as leading
blank lines.

Trigger shape: users manually align parent and child cache chunks and expect
visual whitespace outside `${var}` lines not to affect chunk identity.

Why it matters: small whitespace differences can break cache boundary matching,
but users do not have a precise model of what bytes belong to each chunk.

Desired fix:

- Document exact cache chunk byte boundaries and whitespace behavior.
- Include examples with blank lines before/after `${var}`.
- If the current behavior is too surprising, consider an explicit delimiter or
  normalization strategy as a future design decision.

### 25. Stale docs still reference deleted trace drift helper

Original failure: some internal CLAUDE docs still referenced
`_trace_aligns_with_ir` after the whole-trace drift gate was removed.

Trigger shape: future agents reading implementation guidance for cache analysis
or runtime trace behavior.

Why it matters: stale docs point agents toward nonexistent code and the old
coarse trace-validity model.

Desired fix:

- Update affected CLAUDE docs to describe the current per-row trace evidence
  model.
- Remove references to `_trace_aligns_with_ir`.
- Prefer doing this during the Task 160 cache-analysis architecture sweep.
