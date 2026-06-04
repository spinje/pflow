You are analyzing an implementation plan to decide where to place agent-handoff
breakpoints — the points where one fresh agent stops and the next fresh agent (with no
memory of the first) picks up by reading the plan, the code committed so far, and a progress
log.

Group the plan's phases into ordered SEGMENTS. Each segment is implemented by one fresh
agent in a single sitting, then the context resets before the next segment. Your job is to
choose the segment boundaries well.

## The core question for every boundary between adjacent phases

Can a fresh agent pick up the next phase from written artifacts alone (the plan + committed
code + progress log), or does the earlier phase build up tacit "I just wired this, here's
what feels fragile" knowledge that would be expensive to re-derive?

- Put a boundary (split into separate segments) where the handoff is clean: the earlier
  phase produces a typed interface, a locked schema, a regression test, or otherwise
  transfers fully through artifacts.
- Keep phases together (one segment) where tacit knowledge accumulates: a shared invariant
  built incrementally, fixture vocabulary informing later design, subtle cross-phase coupling.

## What counts as a "phase"

Group only the plan's TOP-LEVEL phases — the major numbered/titled units (e.g.
"Phase 1: Package rename", "Phase 2: trace_loading extraction"). Do NOT list sub-steps
(e.g. "Step 1.1", "Step 2.3") in your output — those live in the plan for the implementing
agent to read. Each segment's `phases` is a list of top-level phase TITLES only, exactly as
written in the plan. If the plan has no explicit phases (just a flat list of work), treat the
whole plan as a single segment.

## How many segments — your judgment, no fixed number

There is no target count. Make the real tradeoff for THIS plan:

- **Larger segments** mean more work — and so more accumulated context — inside one agent
  sitting. Too much accumulated context degrades the agent's quality. This is the main cost
  of merging phases.
- **Smaller segments** mean cleaner resets between fresh agents, but each new agent must
  re-establish context from artifacts, and splitting two phases that share tacit knowledge
  (an invariant built incrementally, fixture vocabulary informing later design) forces that
  knowledge to be re-derived.
- Note the handoff itself is CHEAP here (a fresh agent reads the plan + committed code + a
  progress log — no human in the loop), so don't merge phases just to avoid handoffs. Merge
  only when phases are genuinely coupled; split wherever the handoff is clean.

A small, tightly-coupled plan may be one segment. A large plan with clean phase boundaries
may be many. Let the coupling and the per-segment size decide — not a quota.

## Rules

- Cover EVERY top-level phase exactly once, in plan order. Segments must be contiguous and
  non-overlapping. Do not reorder or rename phases.
- Never split the single highest-risk / most-load-bearing phase across two segments. If it is
  large, it can be its own segment.

## The plan

Read the implementation plan at this path (read it in full before grouping):

`${plan_path}`

For each segment, give the list of top-level phase titles it covers, a short label, and a
one-line rationale for why these phases belong together and why the boundary after them is a
clean handoff. Return the `segments` array defined by the required schema (`phases`, `label`,
`rationale` per item).
