# Braindump — Walker Consolidation (#364 + #365 + related)

**Read `agent-brief-walker-consolidation.md` first.** It's the structured
mission brief. THIS file is what's in my head that isn't anywhere else.

The brief tells you WHAT to do. This tells you what the user actually cares
about, what almost broke, and what context I built up that would otherwise
vanish.

## Where I am right now

I just finished verifying the Tracks A/B/C cost-projection fixes against the
Gemini smoke fixtures (those fixes themselves were done before me — see
recent commit `ec7c7d2a`). Then I did a one-line label fix
(`render_text.py:208`: "Optimized cost per run" → "Cost without caching")
because the user pointed out it confused agents.

Two specific things that mattered in the last hour and may not be in the
files:

1. The label fix's commit message explanation lives only in the comment I
   added at lines 200-208 of `render_text.py`. Read it. The variable name is
   `no_cache_str` (not `optimized_str`) and the comment explains the field's
   actual semantics. Don't undo it.

2. The user explicitly rejected my framing of "JSON consumers will see this"
   when I was discussing UX. Their exact pushback: *"when you say agents read
   this are you talking about when they read json, not the actual cli output?
   because the json output won't be used very much i think."* This shapes the
   priority order: **text mode > JSON mode** for any UX decisions.

## User's mental model — load-bearing

These are direct quotes that shaped my approach. Don't paraphrase; use their
words when you reason.

> *"prioritize simplicity of the FINAL code, not how easy it is to get there.
> Aim for a solution that the top 10% of codebases similar to this would
> implement"*

This is the standing bar. Every architectural decision filters through "is
this what rustc/mypy/clippy/ruff would do." The user has applied this to
multiple turns; they re-ask it when I propose something.

> *"we cannot defer things that SHOULD be working. Its not just adhering to a
> spec we are trying to give a TOOL to agents that is as usable as possible
> in the first version"*

Standing directive. **Don't file v1.x issues as a defer mechanism for things
that are broken now.** v1.x is for things genuinely out of scope, not for
"we noticed this UX is broken." The user explicitly retrains me on this when
I propose deferrals.

> *"What does this mean to an agent? How are an agent supposed to understand
> it or interpret it?"*

Their forcing function for UX decisions. When in doubt, read the rendered
text as if you're an agent who doesn't know the codebase. If the message
needs reverse-engineering, it needs work.

> *"can you make sure that the analyze estimates are the same as the actual
> savings"*

This is the question that drove the whole Tracks A/B/C cost-projection fix.
The user's underlying ask is: **the analyzer must not lie about cost.** If
projections diverge from reality, that's a correctness bug, not a polish item.

The user does NOT phrase things as "v1 should ship" or "this is good
enough." They phrase things as questions that test whether the system is
actually working. Treat their questions as forensic, not exploratory.

## The walker claim — UNVERIFIED

The progress log claims "5+ walkers, 3 distinct cached policies." **I have
not verified this count.** I read the GH #364 description and the loose-end
fix description, but I didn't grep the codebase to count walkers myself.

The agent brief says "verify the count — it may be higher." I mean it.
Possible candidates I'm AWARE of (not exhaustive):

| Walker | Location | I've seen it |
|---|---|---|
| `_collect_llm_calls_from_events` | `runtime/workflow_trace.py:283` | Yes (line 312 has the cached-skip) |
| `_collect_llm_summary` | `runtime/workflow_trace.py` | Mentioned in comment at line 296 — didn't find directly |
| `_walk_event_for_cost` | `core/cache_analysis/context.py` | Mentioned in progress log; didn't read |
| `_iter_llm_events` | `core/cache_analysis/analyze.py` | Mentioned in progress log |
| `core/trace_report.py` walkers | multiple | Didn't read |

The "+plus" in #364's "5+ walkers" worried me — there might be more than
the progress log enumerates. The agent brief's research step 1 is
non-negotiable for this reason.

## Things the user almost asked but didn't

The user asked "why aren't we just using the same recursive code" about
walkers. They were channeling visitor-pattern intuition without using the
term. Their framing was:

> *"why isnt the workflows using the EXACT same code as the parent, just
> recursively?"*

I had to clarify that they were asking about TRACE walkers (which duplicate)
not WORKFLOW execution (which is already recursive via `WorkflowExecutor`).
**Be precise with this distinction in your replies.** Mixing them confuses
the user.

The user did NOT explicitly approve the visitor pattern. They approved the
DIRECTION (consolidate, single recursive code). The agent brief lists
visitor / generator / single-recursive-with-policy as candidates and tells
you to justify your choice. Don't assume visitor is the answer just because
I floated it.

## What I think might be the right shape (suspicion, not verified)

A **generator-based traversal** in Python may be the cleanest fit:

```python
def walk_events(events, *, descend_sub_workflows=True, include_cached="recorded"):
    for event in events:
        yield event
        if event.get("cached") and include_cached == "skip":
            continue
        for item in event.get("batch_items", []):
            yield from walk_events([item], descend_sub_workflows=descend_sub_workflows, include_cached=include_cached)
        if descend_sub_workflows:
            yield from walk_events(event.get("sub_workflow_events", []), descend_sub_workflows=True, include_cached=include_cached)
```

Each walker becomes:
```python
def collect_llm_calls(events):
    return [e["llm_call"] for e in walk_events(events, include_cached="skip") if "llm_call" in e]
```

Generator + policy kwargs feels Pythonic. But I'm not 100%. Maybe a small
class with explicit policies is better. Maybe a strategy pattern wins. **The
research phase exists for you to figure this out, not for me to pre-decide.**

What I'm CONFIDENT about: the abstraction needs to express
- `cached: True` policy as an enum / string ("skip" / "include-recorded" / "include-zero")
- Sub-workflow recursion as a boolean
- Possibly batch-item recursion as a boolean (always true today; may not need to be policy)

## The gemini-smoke fixtures — reuse them

I built smoke fixtures at `scratchpads/stage2-verification/gemini-smoke/`:
- `reference.md` — 4310-token MERIDIAN protocol spec (above Gemini's 4096
  threshold; I had to extend it from 3531 tokens after first attempt)
- `smoke-no-cache.pflow.md` — control (2 sequential LLM calls, no `## Cache`)
- `smoke-with-cache.pflow.md` — `## Cache` declared
- `RUN1-no-cache-trace.json` — actual paid $0.00210
- `RUN2-with-cache-trace.json` — actual paid $0.00068
- `RUN3-rerun-trace.json` — actual paid $0.00068
- `RUN4-memo-hit-trace.json` — full memo hit (cached: true with llm_call populated)

These are **gold for verification**. Don't rebuild them. The cost figures are
the ground truth. Walker consolidation must produce identical numbers.

**Specifically use RUN4-memo-hit-trace.json** to verify your handling of
`cached: True` events. Note: that trace has `cached: true` AND `llm_call`
populated — different shape from the synthetic test M3 in the verification
specialist pass. The progress log is imprecise about this; see the next
section.

## Cached event shape — actual production behavior

The progress log says:
> cached events (`cached: True` with no `llm_call` — produced by the runtime's
> memoization fast-path at `workflow_trace.py:312`) fell through to
> `(None, "unavailable")`

**This wording is misleading.** When I produced a memo-hit trace by running
smoke-with-cache twice, the trace shows:
- `cached: true` ✓
- `llm_call` POPULATED with all 13 fields including `cost_usd`, `cache_source`,
  `cache_age_sec` ✓

So the production memo-hit shape for LLM nodes has llm_call. The "no llm_call"
case fires for **non-LLM nodes** (shell, code, file) that get memoized — they
don't have llm_call to begin with.

**Worth fixing the progress log entry's wording while you're touching the
area** (one-line edit). Otherwise future readers will think production traces
have a different shape than they actually do.

`workflow_trace.py:312` is the cost-collection skip line, NOT the production
site of cached events. The progress log conflates "where cached events are
filtered out" with "where they're produced."

## What I would tell myself if starting over

1. **Run a real workflow before believing the spec.** I spent significant
   time reasoning about chorus-chooser's cache opportunity (~1.6k token
   rubric) before I noticed Gemini's threshold is 4096. The rubric is below
   threshold; chorus-chooser would be a poor cache test. Should have run
   `analyze-cache` against it FIRST and read the per-call output.

2. **Don't trust progress log claims about counts.** "5 walkers, 3 policies"
   was claimed. I didn't verify. The user explicitly asked about ALL related
   simplification opportunities — that requires actual grep.

3. **The user's pattern: they ask before correcting.** When I proposed
   complex fixes, the user asked questions like "isn't this a huge limitation"
   and "what did you mean by X" instead of saying "you're wrong." Treat their
   questions as forensic; they're testing your reasoning. If you can't
   defend the choice cleanly, the answer is "you're right, let me reconsider."

## Stage 2 verification was queued but blocked

The original plan was to run `song-creator` standalone. Files prepared but
NOT yet used:
- `scratchpads/stage2-verification/song-creator/concept.json`
- `scratchpads/stage2-verification/song-creator/creative_direction.md`
- `scratchpads/stage2-verification/song-creator/architecture.md`
- `scratchpads/stage2-verification/song-creator/creative_brief.md`

These were extracted from `/Users/andfal/projects/music-generation/output/0043-20260423-1128/song-A/`.

The Stage 2 spend gate is blocked on:
- The cost-projection bugs (FIXED in `ec7c7d2a`)
- The walker consolidation + sub-workflow rollup (YOUR WORK)
- The label fix (FIXED, this commit)

After your work lands, the user will likely run Stage 2.1 (song-creator
standalone) to verify the spec's ≥40% input-cost reduction target end-to-end
on Gemini Flash. **Your verification step #2 (multi-workflow rollup test) is
basically a dry-run of that.**

## ASSUMPTION I made

ASSUMPTION: the agent doing this work will use the `Plan` agent for research
phase, then a `code-implementer` agent for implementation. I didn't specify
this in the brief because I didn't want to over-prescribe. Make your own
choice but **the research phase IS mandatory** — don't skip it because the
agent type doesn't naturally do research.

NEEDS VERIFICATION: I claimed "the discrepancy detection still works" as a
constraint. I didn't actually trace through whether the discrepancy walker
in `_iter_llm_events` is one of the walkers being consolidated. If it is,
discrepancy detection's behavior depends on the consolidation. **Verify
during research.**

## UNEXPLORED — things I didn't check

UNEXPLORED: **trace 2.1.0 vs 2.0.0 differences in walker behavior.** Some
walkers may handle 2.0.0 traces; others may not. The format-version-gate is
`startswith("2.")` per the consumer rule. If walkers diverge in 2.0.0
handling, consolidation needs to preserve that.

CONSIDER: **the Tier 2 cross-workflow walker** in `cache_analysis/cross_workflow.py`
DOES recurse into sub-workflows, but for FINDINGS not COST. The asymmetry is
intentional today (the analyzer "enters" sub-workflows for rename/prose
detection but "doesn't enter" them for cost rollup). The walker consolidation
might tempt you to unify these too. **Don't, unless you've thought it
through.** They have different return types and different consumer needs.
The user explicitly cares about cost rollup; the cross-workflow walker
already does what it needs to do.

MIGHT MATTER: **the `_should_write_cache_metadata` allowlist.** Currently
LLMNode-only. If a future LLM-producing node type lands (e.g., a hypothetical
`OllamaNode`), the allowlist needs extending. The walker consolidation
shouldn't bake this into the walker itself; keep it at the augmentation
site. The progress log entry "Stage-1 final UX pass" has tacit knowledge
about this.

UNEXPLORED: **what happens to `_aggregate_optimized_cost`'s "no-declared-subset
path uses `_per_call_current_cost_recomputed` directly"** when sub-workflow
rollup lands. Sub-workflow LLM nodes don't have parent-declared subsets. The
aggregation logic needs to think about whether sub-workflow rows are
projected or recorded. **Could surface as a deviation #5 successor.**

## Open threads

- **Cost summary line ordering** in text mode — the lines render in this order:
  Current / Cost without caching / Cost on rerun. After your refactor, with
  sub-workflow rollup, the numbers will be larger (lyrics-generator scale).
  Watch for cosmetic issues at $X.XX vs $0.00XX scales.

- **Header line accuracy** — `2 LLM nodes using gemini/gemini-2.5-flash` is
  correct in smoke tests, but `7 LLM nodes using 2 models` for song-creator
  is wrong (should be ~41). Your fix should update this. Ensure the header's
  models-in-use list ALSO includes models from sub-workflow nodes.

- **The "Estimated savings if applied" line** uses input-only math from
  `aggregate_savings_first_run_usd` and `aggregate_savings_rerun_usd`. These
  are NOT recomputed from `current` and `optimized` — they're derived from
  per-row token deltas. After sub-workflow rollup, these aggregates need to
  include sub-workflow contributions. **Verify with a multi-workflow fixture.**

## Relevant files I touched

- `src/pflow/core/cache_analysis/render_text.py` — label rename + comment
- `scratchpads/stage2-verification/gemini-smoke/*` — built smoke fixtures
- `scratchpads/stage2-verification/song-creator/*` — staged song-A inputs (not used yet)
- `.taskmaster/tasks/task_159/implementation/agent-brief-walker-consolidation.md` — your mission brief

## Files NOT to read directly (use subagents)

- `implementation-progress-log.md` — 4914 lines. Last 500 only via direct read;
  everything else via subagent.
- Each walker source file individually — grep first, then read the specific
  function ranges you need.

## For the next agent

Start by:
1. Reading the agent brief end-to-end
2. Quoting back the three goals + research-first contract (per the brief's
   Final Ask)
3. Running `git status` and `git log --oneline -5` to confirm tree state
4. Running `make test` to confirm baseline (6,061 passing)
5. Running `cat scratchpads/stage2-verification/gemini-smoke/RUN2-with-cache-output.txt`
   to see what working output looks like before you touch anything

Don't:
- Read the full progress log
- Trust the "5 walkers" claim without verifying
- Skip mutation testing
- Defer items to v1.x
- Undo the label fix in `render_text.py`
- Touch the discrepancy / Tier 2 walkers unless structurally entangled

The user cares most about: **agent-actionable rendered output that doesn't
lie about cost, on real multi-workflow pipelines.** Every UX and structural
decision filters through that.

---

**Note to next agent**: Read this document fully before taking any action.
Then read `.taskmaster/tasks/task_159/implementation/agent-brief-walker-consolidation.md`.
When ready, confirm you've read both by summarizing the three goals + the
research-first methodology + the user's standing rules ("top 10%
codebases", "no v1.x deferrals"), then state you're ready to proceed.
