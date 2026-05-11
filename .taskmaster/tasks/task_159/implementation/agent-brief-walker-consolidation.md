# Agent Brief — Walker Consolidation (#364) + Sub-Workflow Cost Rollup (#365) + Related

You are picking up Task 159 mid-stream. The cache rendering layer ships. The
analyze-cache feature is mostly working — but a structural duplication problem
makes it less correct than it should be on multi-workflow pipelines, and the
duplication itself is a code-health issue.

This brief is **self-contained**. Read it end-to-end before doing anything.

## Mission

Three primary goals, one related question, one coordinated landing:

1. **Consolidate trace walkers** (#364). At least 5 functions in the codebase
   re-implement the same trace-tree traversal (events → batch_items →
   sub_workflow_events) with slightly-different cached-event policies and
   aggregation rules. Replace the duplication with one shared primitive.

2. **Sub-workflow cost rollup** (#365). `pflow analyze-cache` currently
   underreports cost on multi-workflow pipelines because cost collection
   doesn't recurse into `sub_workflow_events`. Concrete impact:
   `analyze-cache song-creator.pflow.md` reports 7 LLM nodes for ~$0.10 when
   the actual run uses ~41 nodes for ~$0.45. The walker consolidation makes
   this fix near-trivial (one policy flag).

3. **Related simplification** found during research. Don't go hunting for
   tangential refactors, but if your research surfaces another duplication
   pattern that fits the same abstraction, fold it in.

4. **Cost-projection naming inversion** (related). See the dedicated section
   below — `optimized_cost_*` symbols across `analyze.py` and
   `cost_estimation.py` mean "no-cache hypothetical," NOT the optimization
   target. Two flavors of fix (minimal rename / deeper restructuring) are
   documented; YOUR decision based on research. Acceptable to defer via a
   filed GH issue if research shows it's not appropriate to fix here.

## Context Budget — read these ONLY

You have a tight context budget. Read:

1. `.taskmaster/tasks/task_159/task-159.md` — Task 159 spec (full document).
2. `.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`
   — **last 500 lines only**. Use `tail -500` or read with `offset` such that
   you read only the most recent entries.

Do NOT read the full progress log (~5000 lines). If you need historical
context (a specific decision, an earlier Diagnostic shape, why something was
deferred, etc.), DISPATCH A SUBAGENT:

```
Agent({
  description: "Find progress log entry on X",
  subagent_type: "Explore",
  prompt: "Search /Users/andfal/projects/pflow-feat-prompt-caching/.taskmaster/tasks/task_159/implementation/implementation-progress-log.md for [topic]. Return only the relevant section with line numbers, max 150 lines."
})
```

Use subagents liberally for context gathering. You waste your own context if
you read the log directly.

## Branch state

Work on the existing branch (`feat/prompt-caching`). Working tree should be
clean before you start; `git status` to confirm. Recent commits:

```
git log --oneline -10
```

The last commit just landed a label fix (rename "Optimized cost per run" →
"Cost without caching"). DO NOT undo that — it's correct.

## Mandatory research phase

You MUST complete research BEFORE writing any production code. Skipping
research is the most common way this kind of refactor gets shipped with
missed walkers and silent regressions.

### Step 1 — Find every trace walker

Grep patterns:
- `event.get("batch_items"`
- `event.get("sub_workflow_events"`
- `event["llm_call"]`
- `events.get("cached"` / `event.get("cached"`
- Function names matching `*_walk*`, `*_collect*`, `*_iter*` in `src/pflow/`

Files to inspect closely:
- `src/pflow/runtime/workflow_trace.py`
- `src/pflow/core/trace_report.py`
- `src/pflow/core/cache_analysis/analyze.py`
- `src/pflow/core/cache_analysis/context.py`
- `src/pflow/core/cache_analysis/token_estimation.py`

For each walker found, document:
- File + line range
- Inputs / outputs
- `cached: True` policy (skip / include-at-recorded / include-at-zero / etc.)
- Sub-workflow recursion (descend / skip)
- Aggregation logic
- Consumers (who calls this walker)

The progress log claims 5+ walkers with 3 distinct cached policies.
**Verify the count** — it may be higher.

### Step 2 — Find related tree-walking patterns

Look for patterns that aren't in #364 but smell similar — they may benefit
from the same consolidation:

- IR walkers in `core/cache_analysis/cross_workflow.py` (Tier 2 cross-workflow)
- Output declaration walkers (`runtime/output_resolver.py`)
- Validator walkers
- Anything else recursing over a tree-shaped IR

You do NOT have to refactor these. Identify which (if any) would benefit;
the user will decide scope.

### Step 3 — Find consumers of cached fields

What reads `cost_usd`, `cache_creation_input_tokens`, `cache_read_input_tokens`,
`cache_source`, `cache_age_sec`, `cache_key` from trace events? These are
indirect consumers of the walkers; they need to keep working post-refactor.

### Step 4 — Top-10% pattern selection

Read your research output, then choose the cleanest abstraction. Candidates:

- **Visitor pattern with policy callbacks** — rustc/mypy use this; explicit
  per-node-type dispatch.
- **Generator-based traversal** — Python idiomatic; clippy uses similar.
  Yields events with their context; consumer accumulates.
- **Single recursive function with policy struct** — simpler if all consumers
  fit a small set of policies.
- **Other** — propose if you find something better.

The user's bar (verbatim): "prioritize simplicity of the FINAL code, not how
easy it is to get there. Aim for a solution that the top 10% of codebases
similar to this would implement."

Document why you chose what you chose. Justify against alternatives.

### Step 5 — Plan output

Before any code changes, write a plan covering:
- Walker count + names + locations + per-walker policies (table)
- Chosen abstraction shape + justification
- Per-walker migration strategy (each walker becomes N lines of policy)
- How sub-workflow rollup (#365) fits in (likely a `recurse_into_sub_workflows: bool`
  policy, or a similarly cleanly-named flag)
- Test strategy (mutation tests for each consolidated path)
- Verification fixtures (smoke fixtures at `scratchpads/stage2-verification/`)
- Estimated LOC delta

## Implementation phase

Begin only after research + plan. Surface plan to user if scope is materially
larger than expected (>10 walkers, or you found a related issue worth folding
in).

### What MUST land

1. **One shared traversal primitive** — replaces every current walker.
2. **Sub-workflow cost rollup** — `analyze-cache` `current_cost_per_run_usd`
   includes sub-workflow LLM cost. Header line "N LLM nodes" includes
   sub-workflow nodes. Cost projections include sub-workflow nodes. The
   recommended-actions section accurately scopes findings (don't over-count).
3. **All current walkers refactored** to use the shared primitive — no remaining
   direct tree-walking code.
4. **Behavior preserved** for existing consumers:
   - Cost summary still excludes cached events for non-rolled-up totals where
     appropriate
   - Trace report still includes cached events with their recorded cost
   - Discrepancy detection still works
   - The `_should_write_cache_metadata(node_type_name)` allowlist still gates
     correctly (LLMNode only, ClaudeCodeNode excluded)

### Quality bar (non-negotiable)

- `make test` green throughout
- `make check` green throughout (ruff + ruff-format + mypy + deptry)
- `test_plan_drift.py` green
- `test_golden_baseline_hashes_match` (DD#19) green
- No `# noqa: C901` introductions — decompose into helpers if complexity > 10
- No backward-compatibility shims that aren't immediately cleaned up
- **Mutation-test each consolidated path**: revert the production fix, the new
  test must fail with a clear diagnostic. "Test passes" ≠ "test guards
  regression."

### Constraints to honor

Document and respect (search progress log via subagent if you need details):

- **DD#12**: each `.pflow.md` scopes its own `## Cache`; cross-workflow caching
  is incidental (byte-level only). Sub-workflow rollup is for COST tracking,
  not cache scoping.
- **DD#19**: hash-vs-prep render byte-identity. Walker consolidation MUST NOT
  alter how cache_render content reaches the hash. The golden baseline test
  catches this.
- **`_should_write_cache_metadata` allowlist**: gates trace cache-metadata
  writes to LLMNode only; ClaudeCodeNode intentionally excluded.
- **Heterogeneous batch sub-workflows**: workflow ref varies per item
  (`${item.workflow}`). Rollup must handle them; the existing walker code in
  `workflow_trace.py` does.
- **Trace 2.1.0 forward-compat**: the consumer rule is
  `format_version.startswith("2.")` — additive minor bumps don't break readers.

### Verification before claiming done

1. **Smoke fixtures** at `scratchpads/stage2-verification/gemini-smoke/`. Run:
   ```
   CONTEXT=$(cat scratchpads/stage2-verification/gemini-smoke/reference.md)
   uv run pflow analyze-cache scratchpads/stage2-verification/gemini-smoke/smoke-with-cache.pflow.md \
     --from-trace scratchpads/stage2-verification/gemini-smoke/RUN2-with-cache-trace.json \
     context="$CONTEXT"
   ```
   Expected: same dollar figures as before refactor (`current_cost: ~$0.0007 (trace)`).

2. **Multi-workflow rollup**. Run:
   ```
   uv run pflow analyze-cache /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md
   ```
   Expected post-fix:
   - Header reports total LLM nodes INCLUDING chorus-chooser + review sub-workflows
     (was 7 pre-fix; should be ~41 post-fix — exact count depends on graph traversal)
   - Cost projections include sub-workflow nodes when memo data exists
   - No regressions on parent-scope findings

3. **Mutation-test sub-workflow rollup**: revert the rollup logic; verification
   #2 must produce the wrong (low) count + cost. Restore: passes.

## Related — cost-projection naming inversion

While in `cost_estimation.py` / `analyze.py` for the consolidation work, there
is a naming/semantic issue worth assessing. **It's flagged for you to evaluate
during research** — fix it if it fits the consolidation cleanly, or file a
separate GH issue with concrete recommendations.

### The inversion

`AnalysisSummary.optimized_cost_per_run_usd`, `_aggregate_optimized_cost(...)`,
`AggregateCostBreakdown.optimized_first_run_usd`, JSON field
`optimized_cost_per_run_usd` — every name says **"optimized"** but every value
means **"no-cache hypothetical"** (recomputed full price as if no `## Cache`
were declared).

The user-facing label was renamed in the latest commit (now reads "Cost without
caching" in text mode). But the underlying variable / function names still
mislead. Future contributors reading `_aggregate_optimized_cost` will assume
they're computing the optimization target and will reproduce the bug class
elsewhere.

This connects to a deeper smell: `current_cost_per_run_usd` has THREE different
meanings depending on context (greenfield no-trace = full price / greenfield
+ trace = implicit-cache-only on Gemini / declared + trace = explicit + implicit
cache). The savings formula `(current - optimized) / current` produces
nonsensical signs (e.g., `-238%`) when the contexts don't match the model's
assumptions.

### Two flavors

**Minimal — name truth.** Rename misleading variables/functions/fields to
match what they actually mean:
- `optimized_cost_per_run_usd` → `cost_without_caching_usd` (or similar)
- `_aggregate_optimized_cost` → `_aggregate_no_cache_hypothetical_cost`
- `AggregateCostBreakdown.optimized_first_run_usd` → similar
- JSON field rename — bumps `format_version` 2.1 → 2.2 (additive consumer
  rule still holds via `startswith("2.")`)

Estimated scope: ~30 files (mostly tests reference these names).

**Deeper — fix the model.** Split into atomic primitives keyed by what they
actually represent:
- `cost_actually_paid_usd` (only when trace exists)
- `cost_no_cache_hypothetical_usd`
- `cost_first_run_with_cache_hypothetical_usd`
- `cost_rerun_within_ttl_hypothetical_usd`

Then context-aware presentation (greenfield vs declared) composes from the
atoms instead of overloading the same field. Eliminates the "current means
three different things" issue at its root.

Estimated scope: 4-6 hours; bigger blast radius across `cost_estimation.py`
and `render_text.py`.

### Your decision contract

During research:
1. Touch enough of the cost-projection code to assess whether the deeper
   restructuring is genuinely cleaner OR whether the minimal rename is
   sufficient.
2. Consider: does sub-workflow rollup (#365) interact with this? E.g., if
   atomic primitives compose more naturally across boundaries, the deeper
   fix becomes near-free as part of #365.

Then, in your plan output:
- **If minimal rename is enough**: include it in the consolidation plan,
  no extra surfacing needed.
- **If deeper restructuring is genuinely cleaner AND fits with the rollup
  work**: surface to user before implementing — describe the proposed
  shape, the JSON impact, and why the deeper fix is justified.
- **If neither fits this PR's scope** (e.g., research reveals the cost
  model is actually fine, or the restructuring is too entangled with
  unrelated work): file a separate GH issue with concrete recommendations
  (proposed shape, JSON impact, estimated scope) and proceed with the
  consolidation alone. Don't silently defer.

The user's standing principle (verbatim): "we cannot defer things that
SHOULD be working." But "SHOULD be working" is your judgement call after
seeing the code. The escape hatch is the GH issue — surface, don't sweep
under the rug.

## What NOT to do

- DON'T undo the label fix in `render_text.py` (rename "Optimized cost per run"
  → "Cost without caching"). It just landed and is correct.
- DON'T defer items to v1.x without surfacing them to the user. The standing
  user directive: "we cannot defer things that SHOULD be working."
- DON'T add complexity that isn't justified by current consumers (no
  multi-pass visitor frameworks if single-pass suffices).
- DON'T touch discrepancy detection, Tier 2 cross-workflow walker, or
  analyze-cache rendering UNLESS it's structurally entangled with the
  consolidation. If you encounter entanglement, surface to user before touching.
- DON'T skip mutation testing. The progress log calls Pitfall #19 ("synthetic
  fixture matches buggy code; tests pass against fake") at least 8 times in
  this branch's history. Every new test should drive `pflow analyze-cache`
  end-to-end on a real fixture, not just synthetic Diagnostic construction.
- DON'T call `git add` / `git commit` / `git push` unless the user explicitly
  asks. Standing project memory.

## Deliverables

A single coordinated commit (or small commit chain — surface intent first if
chaining) containing:

- Production refactor: shared walker primitive + all consumers migrated
- Sub-workflow cost rollup wired in
- Header count + cost projections fixed
- Tests (mutation-verified)
- Update to `implementation-progress-log.md` at the END (one new section
  documenting what shipped and WHY, critical insights, and learnings)

## Surface to user before committing if

- Research phase reveals materially larger scope (>10 walkers, related issue
  worth folding in)
- A non-obvious architectural decision arises (e.g., generator vs callback is
  genuinely close)
- You're recommending the **deeper** flavor of the cost-projection naming
  inversion fix (atomic primitives + context-aware presentation) — this has
  a JSON impact and broader blast radius; user reviews before you implement
- You're filing a GH issue for the cost-projection inversion instead of
  fixing it — surface the issue draft (problem statement, proposed shape,
  estimated scope) so the user can confirm the framing

## References

- **GH #364**: walker consolidation (filed)
- **GH #365**: sub-workflow cost rollup (filed)
- **Spec**: `.taskmaster/tasks/task_159/task-159.md`
- **Smoke fixtures**: `scratchpads/stage2-verification/gemini-smoke/` (smoke-with-cache.pflow.md, smoke-no-cache.pflow.md, RUN1/2/3 traces)
- **Real workflow**: `/Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/song-creator.pflow.md`
- **Test commands**: `make test` (full suite ~22s), `make check` (lint/type/deps)

## Final ask

Quote back to the user (in your reply when you start) the FOUR goals
(consolidation #364, rollup #365, related-simplification, cost-projection
naming inversion) + the research-first contract, so they know you understood
the scope and the methodology. Then begin research.
