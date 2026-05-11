# Handoff: select-chorus-class prefix gap + Tier 2 chunk-path scope inconsistency

> **Status**: Deferred. Two related agent-UX gaps in the per-call cache
> report. Both surface as misleading numbers on the same row classes; both
> are documented limitations locked via tests; both have non-trivial fix
> design questions worth thinking through before coding.
>
> **Authored**: 2026-05-10 by the agent who shipped the per-call refactor +
> follow-up review fixes. Both gaps surfaced during the 4-agent code review
> of the per-call refactor PR.
>
> **Audience**: An agent picking up this work fresh. Read this fully before
> opening source. Coordinate with the partial-declaration handoff
> (`task-159-partial-declaration-detection-handoff.md`) — the cases overlap.

---

## TL;DR

The per-call cache report has two distinct defects that BOTH affect rows
where a sub-workflow LLM node is invoked multiple times:

1. **Prefix-projection gate is too narrow** (`select-chorus`-class case).
   The static-prefix cache opportunity is captured for nodes that declare
   their OWN `batch:` config but missed for nodes invoked repeatedly because
   the parent sub-workflow is invoked from a parent's batch.

2. **Tier 2 chunk-path produces per-call cacheable while input is cohort.**
   `_sum_resolved_chunk_tokens` returns one chunk's tokenization without
   multiplying by call count, but `input_tokens_estimated` (from
   `_aggregate_trace_llm_calls`) sums across all trace calls. Rows where
   chunk-Tier-2 fires display per-call cacheable next to cohort input.

Both defects compound on the same row in the canary: `select-chorus` shows
`could_cache=41 ratio=0%` when the actual cache opportunity is the static
rubric/instruction prefix repeated across 4 calls. A fresh agent reading
this row alone concludes "no cache opportunity here" and skims past it.

The motivating user concern: agents reading the per-call section need to
trust that a low could_cache value actually means low opportunity. Today
that's not reliable for repeated-call non-batch nodes.

---

## The motivating row

From the lyrics-generator canary
(`.taskmaster/tasks/task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`):

```
### chorus-chooser.pflow.md (called by choose-chorus)
generate-chorus-options  <varies>                       ?           —            ?     ?%     32  opaque-prompt; ...
score-choruses           gemini/gemini-2.5-flash  158,704           —      144,296    91%    136
select-chorus            gemini/gemini-2.5-flash   36,289           —           41     0%      4
```

`score-choruses` and `select-chorus` are siblings in chorus-chooser. Both
share the same context refs (`concept.title`, `concept.core_idea`, etc.).
Both have substantial repeated-prefix opportunities (their prompts include
multi-paragraph rubrics + instructions repeated across N calls).

But `score-choruses` declares its own `batch:` config (it's a per-chorus
scoring node — N choruses fanned out). `select-chorus` is a single judge
call that runs once per parent invocation; it has NO `batch:` config. The
parent (chorus-chooser) is itself invoked 4× via `song-creator`'s batch.

Result:

- `score-choruses` lights up at `could_cache=144,296 (91%)` via the
  prefix-projection (gated on `node.batch` being present).
- `select-chorus` falls back to chunk-resolved Tier 2 (`concept.title` and
  `concept.core_idea` resolve via `wf_ctx.parameters` after batch-alias
  propagation), summing to ~41 tokens. Multiplied by 4 calls would be ~164
  but the chunk-path doesn't multiply — so the row shows 41.

Both numbers are wrong for different reasons.

---

## Defect 1: prefix-projection gate is too narrow (select-chorus case)

### Current behavior

`src/pflow/core/cache_analysis/analyze.py::_estimate_batch_prefix_cacheable_tokens`
at lines ~2038-2057 (verify before relying — file moves):

```python
def _estimate_batch_prefix_cacheable_tokens(
    *,
    node: dict[str, Any],
    model: str,
    resolved_prompt: str,
    declared_subset: list[str] | None,
    observed_call_count: int,
) -> int | None:
    batch = node.get("batch")
    if declared_subset or not isinstance(batch, dict) or observed_call_count < 2:
        return None
    alias = str(batch.get("as", "item"))
    match = re.compile(r"\$\{" + re.escape(alias) + r"(\.|\[)").search(resolved_prompt)
    if match is None or match.start() == 0:
        return None
    prefix_tokens = estimate_tokens(model, resolved_prompt[: match.start()])[0]
    if prefix_tokens <= 0:
        return None
    return prefix_tokens * observed_call_count
```

The gate `not isinstance(batch, dict)` is the load-bearing exclusion. It
makes sense for batch nodes (the alias `${item.X}` cleanly separates
static-prefix from per-call dynamic content). But it's overly restrictive
for repeated-call non-batch nodes whose static prefix is also reusable.

### Why the simple fix doesn't work

You might think "just remove the batch gate; use observed_call_count >= 2
as the only requirement". But the helper currently uses the alias to find
the per-call dynamic boundary:

```python
alias = str(batch.get("as", "item"))
match = re.compile(r"\$\{" + re.escape(alias) + r"(\.|\[)").search(resolved_prompt)
```

For a non-batch repeated-call node, there's no alias. We need a different
boundary detection.

### What "static prefix" actually means

The cache mechanism sees:

```
[static bytes][per-call dynamic bytes][... possibly more static, more dynamic ...]
```

The "static prefix" is the LONGEST PREFIX of bytes that's identical across
all N invocations. Provider prompt-caching can fire for that prefix when
declared.

For a batch node, `${alias.X}` marks the first per-call boundary (the alias
is GUARANTEED to vary per item). Everything before the first `${alias.X}`
ref is provably static across all batch items.

For a non-batch repeated-call node, NO syntactic marker is guaranteed to
vary. The boundary must be derived from semantic information (which refs
have values that differ across calls?).

### Heuristic candidates for non-batch case

**Heuristic A: First template ref of any kind**

Treat everything before the first `${...}` as static prefix.

- Pros: simple, no semantic reasoning required.
- Cons: many prompts have a static system message → `${context}` (constant
  across calls if passed once) → more static instructions → `${query}`
  (varies). Heuristic A would treat `${context}` as the boundary, but
  `${context}` and the instructions following it are also static. Fires
  too conservative — under-counts cacheable bytes.

**Heuristic B: First template ref whose value differs across calls**

Walk the trace's per-call invocations of this node. For each call, snapshot
the resolved value of each `${...}` ref in the prompt. The first ref whose
value differs across calls is the boundary.

- Pros: semantically correct.
- Cons: requires per-call template-resolution data in the trace, which
  pflow doesn't currently capture (only the final-resolved prompt or
  `node_params.inputs`). Implementation needs trace-format extension OR
  per-call IR-walk against `node_params.inputs` to reconstruct each call's
  resolved values. Significant complexity.

**Heuristic C: Static analysis of ref roots**

For each `${root.X}` in the prompt, classify root:

- Workflow input declared in `## Inputs` — constant if passed once via CLI.
- Memo cache for this node's prior outputs — different per call.
- Memo cache for upstream nodes — depends on whether the upstream is itself
  per-call.
- Batch alias from any enclosing batch boundary — varies per call.

The first ref whose root would vary marks the boundary.

- Pros: pure static analysis, no trace dependency.
- Cons: walking ref-root provenance through nested workflows is
  combinatorial; needs the cross-workflow walker's data. Same blocker as
  Defect 2 in the partial-declaration handoff.

**Heuristic D (pragmatic): Trace-driven empirical scan**

For each call's `node_params.inputs` recorded in the trace, render the
template against that call's params, and find the longest common prefix
across all rendered prompts. That's the static-prefix.

- Pros: deterministic, doesn't require semantic ref classification.
- Cons: requires N template-rendering passes per node (slow on workflows
  with many calls); the rendered prompts may differ in subtle ways
  (whitespace, ordering) that make the LCP too short to be useful.

### Recommended approach

Heuristic D is the cleanest first cut for trace mode. Heuristic A as a
greenfield fallback (no trace data). Combine:

1. If trace exists and ≥2 calls were recorded, use Heuristic D
   (longest-common-prefix across rendered prompts).
2. Else if `node.batch` is present (current code path), use the alias-based
   boundary.
3. Else if ≥2 calls projected via batch context (parent batch), use
   Heuristic A as a conservative fallback.

Each path returns `None` if the prefix tokens count is below some
threshold (current code uses `> 0` but a sensible minimum would be the
provider's min-cache-tokens).

### Risk: false positives

Pre-fix, the prefix-projection over-claims cache opportunities only when
the alias gate fires AND the prompt has a per-batch alias ref AND a
non-trivial static prefix. Three filters. Post-fix (broader gate), only
the longest-common-prefix or first-template-ref check stands between the
projection and false claims. Edge cases:

- Prompts with leading whitespace differences across calls (unlikely but
  possible if the template itself includes trace-time formatting).
- Prompts where the ENTIRE content is dynamic per call (no static prefix).
  Heuristic D returns "" → 0 tokens → returns None correctly.
- Prompts where the static prefix is trivially small (e.g., one fixed
  word). Below provider min-cache-tokens; should return None.

### Tests the implementer must add

- Positive: workflow with parent batch invoking a sub-workflow whose LLM
  node is single-call non-batch. After fix, the per-call row populates
  `could_cache` with the prefix-tokens × N value.
- Negative: same node but only 1 invocation in trace. Returns None.
- Negative: prompts with no static prefix (everything per-call). Returns
  None, NOT a fabricated value.
- Mutation contract: revert the broadened gate; the positive test fails.

---

## Defect 2: Tier 2 chunk-path scope inconsistency

### Current behavior

`token_estimation.py:190-208`:

```python
def _sum_resolved_chunk_tokens(chunks, model, memo_cache, workflow_path, *, ctx=None) -> int | None:
    total = 0
    for ref in chunks:
        tokens = _estimate_ref_tokens(ref, model=model, memo_cache=memo_cache,
                                      workflow_path=workflow_path, ctx=ctx)
        if tokens is None:
            return None
        total += tokens
    return total
```

This sums per-chunk byte tokenization. There is NO multiplication by
`observed_call_count`.

`input_tokens_estimated` for the same row, however, is cohort:

`analyze.py:1113-1144` `_aggregate_trace_llm_calls` sums `input_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens` across all trace
calls.

So for `select-chorus` with `chunks = ["concept.title", "concept.core_idea"]`
and `observed_call_count = 4`:

- `cacheable_tokens_estimated` = ~41 (per-call: ~10 tokens for title +
  ~30 tokens for core_idea, summed once)
- `input_tokens_estimated` = ~36,289 (cohort: 4 calls × ~9,072/call)
- Displayed `ratio = min(41, 36289) / 36289 ≈ 0%`

The ratio is misleading. If `cacheable` were also cohort (~41 × 4 = 164),
the ratio would still be ~0% because chunks-only cacheable is genuinely
small relative to per-call input. But the units mismatch is still a real
defect — for nodes where chunks ARE substantial relative to input, the
ratio would be inflated by 1/N.

### Comparison with Tier 1 trace path

| Path | `input_tokens_estimated` | `cacheable_tokens_estimated` | Consistent? |
|---|---|---|---|
| Tier 1 (`trace`) | cohort (`_aggregate_trace_llm_calls` sum) | cohort (`creation + Σ reads`) | ✅ |
| Tier 2 (`memo` / `parameters`) | cohort (same path) | per-call (`_sum_resolved_chunk_tokens`) | ❌ |
| Prefix-projection (`batch_prefix`) | cohort | cohort (`prefix × call_count`) | ✅ |

The fix: thread `observed_call_count` through `_sum_resolved_chunk_tokens`
and multiply at the end:

```python
def _sum_resolved_chunk_tokens(
    chunks, model, memo_cache, workflow_path, *, ctx=None,
    call_count: int = 1,
) -> int | None:
    ...
    return total * call_count if call_count >= 1 else total
```

Caller at `token_estimation.py:176`:

```python
total = _sum_resolved_chunk_tokens(chunks, model, memo_cache, workflow_path,
                                   ctx=ctx, call_count=observed_call_count)
```

But `observed_call_count` isn't currently a parameter of
`estimate_cacheable_tokens`. Need to thread it from `_build_per_call_row`
where it's computed.

### Why hasn't this bitten the canary?

The canary's Tier 2 chunk-path rows are:

- `select-chorus` (`could_cache=41 ratio=0%`) — undisplayed agent gap
  because the chunks ARE small.
- `evaluate-songs`, `select-concepts`, etc. (`could_cache=?`) — these have
  no resolvable candidate, so the Tier 2 path doesn't fire at all.

The defect is silent today because:

1. Most Tier 2 chunk-resolved rows in real workflows have small chunks.
2. The clamp `min(cacheable, input)` masks ratio>100% in pathological cases.
3. Investigator-confirmed empirical sweep across 65 baselines: zero rows
   show Tier 2 chunk-path producing a number that meaningfully misleads.

But the units mismatch is structurally wrong. A future workflow with
larger chunks (e.g., a 2000-token system message declared as a single
candidate) would expose the gap.

### Interaction with the cost-projection gate

The follow-up commit gated `_per_call_rerun_cost` on `declared_prompt_cache`.
For undeclared rows (which is where Tier 2 chunk-path mostly fires today,
since declared rows usually have trace evidence → Tier 1), the
`cacheable_tokens_estimated` no longer ripples into rerun cost. So the
unit mismatch doesn't currently affect cost numbers — only the displayed
row ratio.

If you fix Defect 2 (multiply chunk-path by call_count), and a node IS
declared AND chunk-path falls through (Tier 1 didn't fire because cache
didn't actually fire on this run), the new cohort cacheable will flow
into `_per_call_rerun_cost`. That's correct — the rerun cost projection
SHOULD be cohort.

### Tests the implementer must add

- Positive: end-to-end test where a chunk-resolved row has ≥2 invocations.
  Assert `cacheable_tokens_estimated == per_chunk_total * call_count`.
- Comparison: same workflow, ratio matches expected cohort/cohort.
- Mutation contract: revert the multiplication; test fails.

---

## Why these are "related" (shared root cause framing)

Both defects affect the same row class: **sub-workflow LLM nodes invoked
multiple times because their parent sub-workflow is invoked from a
parent's batch**. select-chorus is the canonical example.

For these rows:

- The structural reuse pattern is real (each invocation reuses the same
  prompt structure).
- The agent value of detecting that reuse is real (declaring prompt_cache
  enables provider caching across N calls).
- Both Defect 1 (prefix gate) and Defect 2 (chunk-path scope) cause the
  row's number to under-represent the opportunity:
  - Defect 1: prefix-projection doesn't fire → no large-prefix could_cache.
  - Defect 2: chunk-path falls back to per-call → small chunks-only
    could_cache that doesn't multiply.

Fixing only Defect 1 catches workflows where the static prefix is
substantial. Fixing only Defect 2 catches workflows where chunks (e.g.,
a single declared candidate ref) are substantial. Both fixes together
give the cleanest agent-facing UX.

But the fixes are mechanically independent — they touch different code
paths and can ship as separate commits.

---

## Recommended sequencing

If splitting:

**PR A — Defect 2 first (lower risk, smaller change)**:

- Thread `observed_call_count` into `_sum_resolved_chunk_tokens`.
- Multiply chunk-path total by `call_count`.
- Add unit test + lock-in regression.
- Estimated LOC: ~15-25.
- Baseline drift: probably 0-2 cases (chunks in current baselines are
  small enough that the clamp masks the change).

**PR B — Defect 1 second (higher complexity, broader impact)**:

- Implement Heuristic D (longest-common-prefix across trace-recorded
  rendered prompts).
- Broaden the prefix-projection gate to fire on non-batch repeated-call
  nodes via observed_call_count >= 2.
- Add positive + negative tests.
- Estimated LOC: ~50-80 (depending on heuristic depth).
- Baseline drift: 1-2 cases (lyrics-generator's select-chorus row
  populates non-trivially).

If shipping together:

- Estimated LOC: ~70-100.
- One regen pass.

---

## Hard constraints from the broader cache-analysis design

These are NOT introduced by these fixes, but they affect implementation
choices:

- **Cohort-vs-per-call naming**: section title is still "Per-call cache
  report" but values are cohort when calls > 1. The follow-up commit added
  an explainer line clarifying this. Don't introduce another
  per-call-shaped column in your fix without considering whether to flip
  to a per-call-or-cohort-toggle (probably not; explainer is sufficient).

- **Diagnostic dedup hash excludes context**. If you add new catalog IDs
  for these defects (e.g., `cache.repeated-call-prefix-detected`), beware
  the workflow-level `node_id=None` collapse risk. Prefer per-node
  emission (`path_template: nodes[id={node_id}]`).

- **Pitfall #19**: every regression test drives `analyze()` end-to-end
  with real state. Search "Pitfall #19" in the progress log for past
  instances. Synthetic-dict fixtures don't catch real bugs in this
  codebase.

- **The catalog is closed in v1 (DD#29)**. New catalog IDs need user/spec
  design review. These fixes don't strictly need new IDs (the existing
  recommendation `cache.shared-context-undeclared` would still be the
  right action surface).

---

## Reference: file:line index

| Path | Why |
|---|---|
| `src/pflow/core/cache_analysis/analyze.py` `_estimate_batch_prefix_cacheable_tokens` | Defect 1 gate site |
| `src/pflow/core/cache_analysis/analyze.py` `_prefer_batch_prefix_cacheable_tokens` | label assignment for prefix path |
| `src/pflow/core/cache_analysis/analyze.py` `_aggregate_trace_llm_calls` | cohort summation reference |
| `src/pflow/core/cache_analysis/analyze.py` `_build_per_call_row` | computes `observed_call_count` |
| `src/pflow/core/cache_analysis/token_estimation.py` `_sum_resolved_chunk_tokens` | Defect 2 fix site |
| `src/pflow/core/cache_analysis/token_estimation.py` `estimate_cacheable_tokens` | Tier 2 caller |
| `src/pflow/core/cache_analysis/render_text.py` `_per_call_scope_explainer` | explainer text for cohort note |
| `tests/test_core/test_cache_analysis_analyze.py` `test_batch_prefix_projection_does_not_fire_for_non_batch_repeated_call_nodes` | the lock-in test for Defect 1 limitation. After fix, this test's assertion needs reversal (it currently asserts the helper does NOT fire). |

---

## Test fixtures the implementer must add

1. **End-to-end positive (Defect 1 fix)**: a workflow with a parent batch
   invoking a sub-workflow whose only LLM node is single-call (no
   `batch:`). After fix, the per-call row's `could_cache` populates with
   prefix-projection.
2. **End-to-end positive (Defect 2 fix)**: a workflow with declared
   candidate refs that resolve via memo + observed call count >= 2.
   Assert `cacheable_tokens_estimated == sum_of_chunk_tokens × call_count`.
3. **End-to-end negative**: same shape but call_count = 1. Tier 2 returns
   per-call (multiplication is identity).
4. **End-to-end negative**: prompt with no static prefix detectable across
   calls. Defect 1's broader heuristic returns None (honest unmeasurable).
5. **Coverage**: at least one workflow that exercises BOTH defects on the
   same row, asserts the row populates with the larger of the two
   projections (chunk-path × calls vs prefix-projection).
6. **Mutation contracts**: each test's docstring describes what reverting
   the production fix would break.
7. **Lock-in inversion**: the existing test
   `test_batch_prefix_projection_does_not_fire_for_non_batch_repeated_call_nodes`
   asserts the LIMITATION. After the Defect 1 fix, its assertion direction
   must flip (or it should be replaced). Track this so the implementer
   doesn't see a passing test and assume nothing's broken.

---

## Decision points for the user (escalate before coding)

1. **Ship Defect 2 fix alone, or together with Defect 1?**
   Defect 2 is small + low-risk. Defect 1 is bigger and has heuristic
   design questions. If user wants the smaller win first, ship D2; revisit
   D1 separately.

2. **Heuristic D vs simpler fallback for Defect 1?**
   Heuristic D (LCP across rendered prompts) requires trace data. For
   greenfield workflows, fall back to Heuristic A (first `${...}` ref) or
   leave the row at chunks-only Tier 2. User picks.

3. **Should the section title rename happen alongside?**
   The "Per-call cache report" → "Cache report (per node)" rename is
   tracked elsewhere as a separate concern. If the user wants alignment
   between data semantics and title, bundle.

4. **Threshold for prefix-projection minimum?**
   Currently `prefix_tokens > 0` returns the value. A more honest gate
   would be `prefix_tokens >= provider_min_cache_tokens` (1024 for
   Sonnet, 4096 for Opus, etc.). Otherwise the projection over-claims for
   trivially-small prefixes.

---

## Honest confidence breakdown

| Claim | Confidence | Why |
|---|---|---|
| Defect 1 (prefix gate too narrow) is real | 100% | Source-grounded; reproduced on canary's select-chorus row |
| Defect 2 (chunk-path scope inconsistency) is real | 100% | Source-grounded; verified by reading `_sum_resolved_chunk_tokens` |
| Heuristic D is the right approach for Defect 1 | 70% | Solid in trace mode; greenfield fallback unverified |
| Multiplying chunk-path by `call_count` is the right Defect 2 fix | 85% | Mechanically symmetric with Tier 1 cohort semantics; cost-projection gate keeps it isolated |
| Combined LOC ~70-100 for both | 70% | Heuristic D's complexity dominates; spot-check before committing |

Treat 70% confidence claims as starting points. Verify file:line claims;
the codebase moves.

---

## What I'd tell myself starting over

1. **Read the prior PR + the follow-up review commit first.** The
   per-call refactor's column shape, the prefix-projection's gating, and
   the cost-projection isolation all matter for these fixes' design.

2. **Defect 2 is the cheaper win — start there.** It's a one-line
   semantic fix with a small test surface. Once it ships, the agent-UX
   improvement is small but the structural inconsistency is gone.

3. **Defect 1 is design-heavy.** Don't reach for the simple gate
   broadening — the heuristic question is real. Heuristic D is the
   cleanest path but requires careful test design.

4. **The lock-in test
   `test_batch_prefix_projection_does_not_fire_for_non_batch_repeated_call_nodes`
   is a CHEKHOV'S GUN.** When the Defect 1 fix lands, this test must be
   inverted or replaced. The current docstring documents the limitation
   as deliberate; the inversion must update the docstring AND the
   assertion. Don't just delete it — the inversion preserves the regression
   contract (a future agent removing the broader gate would see this test
   fail, restoring the limitation visibly).

5. **Run `pflow analyze-cache` on lyrics-generator after each fix.** The
   canary's `select-chorus` row is the agent-UX truth. Watching its
   `could_cache` value transition from 41 to a sensible projection is
   the load-bearing verification.

6. **The section title rename is OUT OF SCOPE.** Don't bundle it; ship
   the data-correctness fixes first. The explainer line is sufficient
   for now.

---

## Appendix: how select-chorus's row should look post-fix

Before:
```
select-chorus  gemini/gemini-2.5-flash  36,289  —  41  0%  4
```

After Defect 2 fix only (chunk-path × calls):
```
select-chorus  gemini/gemini-2.5-flash  36,289  —  164  0%  4
```
(Still ~0% because chunks-only is genuinely small.)

After Defect 1 fix only (prefix-projection broadens):
```
select-chorus  gemini/gemini-2.5-flash  36,289  —  ~28,000  77%  4
```
(Approximate — depends on the actual static prefix size; agent now sees
a real cache opportunity.)

After BOTH fixes (`max(prefix-projection, chunk-path × calls)` wins):
```
select-chorus  gemini/gemini-2.5-flash  36,289  —  ~28,000  77%  4
```
(Same as Defect 1 alone, because prefix-projection dominates here. Other
workflows might have different winners.)

The footer would then say something like:

```
Token estimate confidence: select-chorus projects savings from the prompt's
static prefix repeated across observed calls; declare prompt_cache to confirm.
```

That's the agent-actionable signal: "this node has a cache opportunity worth
$X; declare prompt_cache to capture it." Today the agent skims past
`could_cache=41` and the opportunity goes uncaptured.

Done. If anything is unclear when you start, ASK rather than guess —
ambiguity is a STOP signal.
