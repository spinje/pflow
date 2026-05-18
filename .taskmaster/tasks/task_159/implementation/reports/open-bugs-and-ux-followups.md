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

Checked against GitHub issues on 2026-05-13 (later updates 2026-05-16, 2026-05-18).
Exact matches and genuinely related issues are linked inline below. Most items in
this file are not yet tracked as standalone GitHub issues; issue #395 is
intentionally not counted as tracking because it only catalogs fixed PR #396 work.

Exact or substantially matching tracking found:

- Item 3: [#394](https://github.com/spinje/pflow/issues/394) tracks the
  remaining `PerCallRow.input_tokens_estimated` mixed-unit contract.
- Item 16: [#385](https://github.com/spinje/pflow/issues/385) tracks the
  provider-error-first and large batch-payload formatting problem.
- S#13 (scratchpad-only — `-o` keys unclear for `--only` batch nodes; out of
  scope for Task 159 prompt-caching): [#400](https://github.com/spinje/pflow/issues/400)
  tracks the full `-o`/`--only` UX gap (no dotted-path support, no key hints
  on miss, default streams full batch payload). Filed during Bundle 9
  closeout (2026-05-18) with inlined repro, implementation surface, and
  splitability guidance.

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

1. Combined `prewarm: true` + `prompt_cache` hides additive prewarm evidence
   (will be subsumed by cache-ready-opportunity plan Phase 1).
2. Run output still hides the actionable provider error behind large payloads.

Closed:

- ~~F#4 — Prewarm recommendation can ignore provider minimum~~ — closed in
  Bundle 9 (2026-05-16). The user's reframe was load-bearing: not "suppress
  the recommendation when below-min," but "show the recommendation and give
  notes about the limitation so the agent knows how close they are to min
  threshold, can change model etc." The per-call row already did this via
  `_prewarm_opportunity_projection_component`; the Recommended-Actions
  block was silently suppressing at two sites
  (`_confident_batch_prewarm_recommendation` and the lower-bound branch of
  `_batch_prewarm_recommendations`). Bundle 9 routed all three call sites
  through a new shared producer `_emit_batch_prewarm_below_min` and
  augmented the `cache.batch-prewarm-below-min` catalog with a third
  suggestion bullet for model-switch. Convergence is now complete: per-call
  row + Recommended-Actions show the same structural blocker on the same
  evidence, with three actionable remediations (grow, remove prewarm,
  switch model). Known minor wart: the model-switch bullet names Sonnet 4.5
  as the floor; degenerate when the user is already on Sonnet 4.5. Flagged
  for a future catalog-polish pass — not actively misleading, just self-
  referential. **Reopen criteria**: if a real workflow on Sonnet 4.5 with a
  sub-1,024-token prefix surfaces user confusion from the degenerate bullet,
  add a `_select_message_template`-style conditional emission gate.
- ~~S#5 — Failed-batch trace drops completed nested LLM events~~ — closed in
  Bundle 8 (2026-05-15). Runtime trace-capture bug: ``execute_batch`` popped
  per-item trace items into a local before raising for fail_fast errors,
  losing them on the engine's except path. Fix moved the drain from producer
  (``batch_executor``) to consumer (``engine._execute_node``), using the
  shared store as the recovery channel symmetric with the success path.
- ~~S#9 — Parent-trace redirect hint missed non-batch sub-workflows~~ —
  closed in Bundle 8 (2026-05-15). Bundle 4 shipped the redirect-hint logic
  but only exercised it via homogeneous-batch fixtures; the production
  ``sub_workflow_events`` path silently failed because
  ``_workflow_appears_as_child`` called ``TraceTree.walk`` without an
  ``edges`` map. Fix moved edge derivation into ``TraceTree`` itself: the
  trace's own ``_pflow_child_workflow_paths`` field now drives a
  ``default_edges`` map merged into every ``walk()`` at top-level entry.
- ~~Full shadowed-cache summary math~~ — closed as misframed in Bundle 1
  (2026-05-14). See section 1 below for the reasoning.
- ~~`PerCallRow.input_tokens_estimated` still has mixed units~~ — closed in
  follow-ups-2 (per-call unit contract normalized; JSON 4.3).
- ~~Validation-time provider constraints (GH #385 case)~~ — closed in Bundle 3
  (2026-05-15). Most-cited case is already shipped as
  `llm.thinking-temperature-mismatch`; Bundle 3 tightened gaps (CLI integration
  test, sub-workflow baseline, stale doc count). Remaining sub-cases (GH #368,
  OpenAI reasoning) gated on empirically-verified failure modes — see section
  21 for reopen criteria.
- ~~Runtime cost summary `pricing unavailable for: unknown`~~ — closed in
  Bundle 7 (2026-05-15). Bundle 4 surfaced model names + unnamed counts;
  Bundle 7 added per-model call counts (`(N calls)` per model) and a
  `Total LLM calls: N` sibling line on CLI + success_formatter for parity
  with `trace_report.py`. See section 17 below.
- ~~"Blocking errors" can include fallback/error-path nodes~~ — closed as
  misframed in Bundle 7 (2026-05-15). The cache-vs-other split already
  exists (Task 159 Stage 0 / JSON 4.1); unsynced MCP fallback nodes are
  genuinely blocking for save/run; F#22 makes the diagnostic actionable.
  See section 19 below.

## Analyze-cache Correctness

### 1. Full shadowed-cache summary math — CLOSED AS MISFRAMED (Bundle 1, 2026-05-14)

**Status: closed.** Investigation showed the followups doc's framing
conflated two different counterfactuals:

- **Counterfactual #1** ("same prompt, no discount"): if you keep the
  prompt exactly as written and turn off the cache discount, the cost is
  `input_tokens × rate`. This is what the summary baseline computes today,
  and it is the honest answer to *"is the cache discount earning its
  keep?"*
- **Counterfactual #2** ("no cache declaration at all"): if you delete the
  `## Cache` block and the chunk bytes never get inserted into the prompt,
  the cost is `body_tokens × rate`. This is what the followups doc thought
  the summary should compute. It is the honest answer to a different
  question: *"do I need this content in my prompt at all?"*

The original framing assumed #2 was the right baseline because the body
references only a sub-path of the cached value. But the cache chunks ARE
part of the prompt the model sees — the user opted in via `prompt_cache:`
on the node because they want that content prepended. The body's
sub-path reference is additional, focused content. The analyzer cannot
tell whether the rest of the cached object is "unused dead weight" or
"intentional context the agent wanted the model to have."

The summary baseline is correct as-is for counterfactual #1. The local
`cache.prompt-body-shadows-cache` recommendation correctly discloses the
counterfactual-#2 cost (per-call body-only vs with-cache cost) so an
agent who suspects over-broad caching can act on it.

**What changed in Bundle 1:**

- Reframed `cache.prompt-body-shadows-cache` message text to ask a
  duplication question (`"may be sending the same value twice in each
  call"`) instead of asserting *"the rest is sent to the model but unused
  by your prompt"* (unprovable from workflow shape).
- Reframed `cache.prompt-body-duplicates-cache` to rhyme with shadow:
  `"sends the same value twice in each call"`.
- Dropped the shadow render hook's footnote *"Note: the summary's 'saves
  N%' compares against inlining the full chunk uncached — a different
  baseline than your body actually uses"* — it was a hedge that conceded
  the bug we now believe doesn't exist.
- Collapsed the summary `Actual cost delta` and `Rerun delta` lines into
  parentheticals on the `Actually paid` and `Cost on rerun` cost lines:
  `Actually paid: ~$0.0087  (saves 26% vs cost without caching)`. Closes
  the label-fragmentation issue (5 different strings for the same
  baseline concept, including F#20's "Actual savings ... adds ~$X" sign
  confusion).
- Unified terminology: the baseline is consistently called `"cost without
  caching"` across cost-block labels and delta parentheticals.

**Future contributors:** if you find yourself wanting to reopen this as
"the summary baseline is wrong," first map your scenario to one of the
two counterfactuals above. If the user's workflow uses cache chunks they
genuinely want in the prompt, baseline #1 is correct. If the analyzer
detects clear over-caching, the local recommendation surfaces the
counterfactual-#2 cost. The summary-level baseline should NOT be
re-routed to body-only — doing so answers a different question than the
summary advertises.

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

### 4. Prewarm recommendation can ignore provider minimum — CLOSED (Bundle 9, 2026-05-16)

**Status: closed.** Investigation found the doc's framing inverted what the
user actually wanted. The original framing was *"suppress the recommendation
when below-min — the analyzer should not tell users to add prewarm for a
prefix that won't fire."* The user's reframe (during Bundle 9 triage) was:

> "Show the recommendation and give notes about the limitation so the agent
> knows how close they are to min threshold, can change model etc."

This matches Bundle 5's Option B reasoning: structural recommendations stay
visible with explicit blocker fields so the agent retains the insight and
the actionable next steps. The cache-ready/opportunity refactor
(2026-05-15) already shipped this at the **per-call row level** via
`_prewarm_opportunity_projection_component` — `meets_provider_min=False`,
`blocked_reason="below_provider_min"`, `action="add_prewarm"`,
`affects_cost_projection=False`. The row table renders `add prewarm; below
provider min (need ≥4,096 for this model)` and the Gemini live recording
baseline (`10-live-recordings/05-gemini-lyrics-generator`) demonstrates the
intended UX.

The remaining gap was that the **Recommended-Actions block** was silent for
the below-min case. Two production sites silently suppressed:

- `_confident_batch_prewarm_recommendation`: `if is_below_min_cache(...): return []`
- `_batch_prewarm_recommendations` lower-bound branch: same `return []`
  shape with unresolved refs

An agent reading only the actions block would miss the structural blocker
that the per-call row was already showing.

**What Bundle 9 changed:**

- New shared producer `_emit_batch_prewarm_below_min(node_id, model,
  prefix_tokens, batch_alias, workflow_path)` in `analyze.py`. All three
  call sites (the existing declared-prewarm site in `_per_node_warnings`,
  plus the two previously-silent undeclared sites) now route through it.
  Catalog ID stays `cache.batch-prewarm-below-min` — no new ID, no DD#29
  design review needed.
- Predicate stays `is_below_min_cache` (honest-unmeasurable, returns False
  for unknown/empty model). Bundle 5 Option B scope preserved — the new
  sibling `is_likely_below_min_cache` remains at internal cost-math gates
  only.
- Catalog `cache.batch-prewarm-below-min` gains a third suggestion bullet
  for model-switch:

  > "OR switch `- model:` on {node_id} to one with a lower cache minimum —
  > e.g. `anthropic/claude-sonnet-4-5` caches at 1,024 tokens. See
  > `pflow guide prompt-caching` for the per-model threshold table."

  Provider-aware in the safe direction: always names the published floor
  (1,024 tokens), never a model that would worsen the minimum.

The convergence story is now complete: per-call row + Recommended-Actions
block surface the same structural blocker on the same evidence with three
actionable remediations (grow prefix / remove prewarm / switch model). The
biggest visible payoff is the Gemini live recording — Recommended-Actions
count went 12 → 14 with two new full entries for `curate-briefs` and
`score-choruses` that were previously suppressed silently.

**Known minor wart (deferred):** the third suggestion bullet names Sonnet
4.5 as the floor. When the user is *already* on Sonnet 4.5, the bullet is
self-referential ("switch to anthropic/claude-sonnet-4-5" from
anthropic/claude-sonnet-4-5). Not actively misleading — the bullet stays
factually correct, the user simply already has the recommended model — but
a UX wart. Two refinement options for a future catalog-polish pass:

- Catalog-level conditional emission: drop the bullet when
  `min_tokens <= 1024` (requires `_select_message_template`-style
  filtering not currently in the catalog framework).
- Soften the wording: "if a different model fits your workflow, see
  `pflow guide prompt-caching`; lowest published min is 1,024 tokens
  (`anthropic/claude-sonnet-4-5`)." Loses the directive verb but
  degenerate-safe.

**Reopen criteria:**

- If a real workflow on Sonnet 4.5 with sub-1,024-token prefix surfaces
  user confusion from the degenerate self-reference, apply one of the two
  refinement options above.
- If `is_below_min_cache`'s "honest unmeasurable" semantics produce a
  user-visible regression (empty/unknown model rows silently missing the
  recommendation when a real prefix is below min), reconsider migrating
  this site to `is_likely_below_min_cache` — but check Bundle 5's
  documented trade-off first (the conservative predicate suppresses
  structurally-useful "savings unavailable" recommendations on unresolved-
  model workflows).

GitHub tracking (historical): related issue
[#393](https://github.com/spinje/pflow/issues/393) covered the runtime-side
prewarm below-min defense. The runtime pre-dispatch strip shipped in this
sprint (2026-05-14, see `follow-ups-2-progress-log.md` first entry) closed
that. Bundle 9 closes the analyzer-side recommendation symmetry.

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

### 19. "Blocking errors" can include fallback/error-path nodes — CLOSED AS MISFRAMED (Bundle 7, 2026-05-15)

**Status: closed.** Investigation showed two reasons the original framing
no longer applies:

**1. The cache-vs-other split already exists.** The analyzer's JSON output
already exposes two separate arrays for ERROR-severity diagnostics: one
holds cache-domain errors that block save and run (cache catalog IDs plus
`llm.thinking-temperature-mismatch`); the other holds non-cache validator
errors surfaced for awareness. The text renderer adapts its section
header accordingly — `## Other blocking errors (surfaced for awareness)`
when cache-blocking errors are also present, `## Blocking errors`
otherwise. The original framing assumed all ERROR-severity diagnostics
collapsed into one undifferentiated "Blocking errors" bucket. They do
not.

A concrete example: an unknown-MCP-node-type diagnostic on a fallback
node (e.g. `fetch-youtube-mcp` referenced via `- on-error:`) lands in
the second array, not the first. An agent consuming JSON can tell them
apart by which array the diagnostic appears in; an agent reading text
sees the adaptive header.

**2. "Conditional path" understates the actual risk.** An unsynced MCP
fallback node IS genuinely blocking for both `pflow save` (validator
rejects) and `pflow run` (compilation will fail when the error edge is
exercised). Treating it as a soft "conditional-path" warning would mask a
failure mode that fires the moment a fallback path is taken. The current
ERROR-severity treatment is correct.

**3. Once F#22 lands, the diagnostic is actionable.** Bundle 7's F#22 fix
adds the `pflow mcp sync <server>` hint to the existing diagnostic for
the specific failure mode the original framing cited. The agent UX
problem the framing wanted to solve — "I see a blocking error but can't
act on it" — is resolved at the suggestion-text layer, not by
reclassifying severity.

**Reopen criteria** (the closeout is not absolute):

- A concrete failure mode where a non-cache validator ERROR on a node
  reachable only via an `action="error"` edge genuinely should NOT block
  `pflow save` / `pflow run`. The fallback-MCP case is not such a mode —
  the workflow really does break when the error path fires.
- A reproducible workflow showing user-visible friction the existing
  two-array split + F#22 suggestion text together do not resolve.

Without those: keep closed.

### 20. Negative "Actual savings" wording is confusing — CLOSED in Bundle 1 (2026-05-14)

**Status: closed.** Bundle 1's summary-block UX rewrite collapsed the
`Actual cost delta` / `Rerun delta` lines into parentheticals on the
cost lines they describe. The parenthetical uses verb-encoded direction:
`(saves N% vs cost without caching)` when cache reduces cost,
`(adds N% vs cost without caching)` when cache increases cost, and
`(no meaningful cost change)` for break-even. No standalone "Savings"
label appears that could flip semantic meaning under sign change. See
the Bundle 1 closeout under section 1 above.

### 21. Validation-time provider constraints — CLOSED in Bundle 3 (2026-05-15) for the verified case; broader item remains scoped to "needs empirically-verified failure modes"

**Status: closed for the most-cited case (GH #385); remaining sub-cases gated on empirical verification.**

#### What shipped

The GH #385 case — Anthropic + extended thinking (`reasoning_effort ∈ {xhigh, high, medium, low, minimal}`) + literal `temperature ≠ 1.0` — is already fully wired:

- Catalog entry: `cache_analysis/warning_catalog.py:916-939` (`llm.thinking-temperature-mismatch`, severity ERROR, source `"validator"`).
- Validator: `_extract_thinking_temp_violation` (`data_flow.py:1103-1141`) + `_validate_thinking_temperature_compatibility` (`:1144-1181`). Skips templated values; defers to runtime if model is `${...}`.
- Wired into `WorkflowValidator.validate()` (step 4 — `_validate_data_flow`), `pflow run` (blocking via `WorkflowRunner._validate()`), `pflow analyze-cache` (Blocking errors via `_is_cache_focused_for_advisory` predicate), MCP tool docstring.
- Empirically verified across Opus 4.1/4.5/4.7, Sonnet 4.5/4.6, Haiku 4.5 (`data_flow.py:1154-1156`).

Bundle 3 tightened the gaps around this existing implementation:

- New CLI integration test (`tests/test_cli/test_validation_before_execution.py::test_thinking_temperature_mismatch_blocks_before_any_execution`) — proves end-to-end that `pflow run` halts before any node executes when this constraint fires. Uses the marker-file pattern from the canonical `test_unknown_node_caught_before_any_execution`. No real LLM call (the validator halts before any dispatch).
- New sub-workflow baseline (`.taskmaster/tasks/task_159/baseline/04-warning-catalog/20b-llm.thinking-temperature-mismatch-subworkflow/`) — locks parent→child propagation via `_add_child_provenance` for THIS specific catalog ID, preventing silent loss of the `"In step '...' sub-workflow:"` prefix during future child-IR resolution refactors.
- Stale CLAUDE.md count fix in `cache_analysis/CLAUDE.md` (was hand-counted 26; now references the auto-derived `EXPECTED_CATALOG_COUNT` constant).

#### Why the broader F#21 remains open-but-scoped

The original framing of F#21 (*"This item remains broader than both [#385, #368]"*) implied additional provider-constraint validation gaps beyond the Anthropic case. Investigation found no empirically-grounded specifics in this codebase for the remaining sub-cases:

- **GH #368 — Opus 4.7 reasoning-parameter constraint**: referenced by issue number only. The specific constraint shape (which parameter, which failure mode, which provider error string) is not documented in source, tests, or `.taskmaster/`. Cannot implement without knowing the actual constraint.
- **OpenAI reasoning models (`gpt-5*`/`o1*`/`o3*`/`o4*`) rejecting `temperature`**: industry knowledge but **zero** documentation/tests/examples in this codebase. `tests/test_core/test_prompt_cache_validation.py:1144` explicitly notes that Gemini accepts non-1 temperature; no symmetric OpenAI note exists. Exact behavior varies by model and version (o1 series originally hard-rejected non-1 temp; newer models may silently downgrade). Adding a validator without empirical verification risks false positives — the opposite of the agent UX win this work is supposed to deliver.
- **Gemini constraints**: explicitly noted as permissive in existing tests; no known constraints worth validating.
- **`max_tokens` caps**: no awareness anywhere; would need provider-specific tables.
- **`model_options={"thinking": ...}` direct passthrough**: already runtime-rejected by `_REASONING_MODEL_OPTION_KEYS` deny-list at `llm_client.py:670-682`.

The bar set by GH #385 — empirically verified across multiple model versions before shipping — is the right bar. Adding speculative constraints would erode trust in validator output.

#### Reopen criteria

Reopen with a concrete sub-case when:
- A specific failure mode is reported with the verbatim provider error string,
- The failing combination is reproducible with a small `.pflow.md`,
- The constraint is verified across multiple model versions within the affected provider family.

Then mirror the GH #385 pattern: new catalog row, `_extract_X_violation` helper in `data_flow.py`, wire into `_validate_data_flow`, per-id sample, emission test, baseline case, MCP docstring update, `_is_cache_focused_for_advisory` predicate update.

GitHub tracking: closed for [#385](https://github.com/spinje/pflow/issues/385); [#368](https://github.com/spinje/pflow/issues/368) needs constraint specifics before it can be implemented.

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
