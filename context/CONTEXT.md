# pflow

CLI-first system where AI agents author Markdown workflows (`.pflow.md`) chaining
**steps** that communicate through a shared store. This glossary fixes shared vocabulary.

## Language

**Batch** — a step run once per element of a *known* collection (fan-out). Count fixed
before start; runs independent, may be parallel. _Avoid_: loop, map.

**Loop** — a step that *repeats until a condition over its own output goes falsy*, capped
by a maximum. Count not known up front; runs sequential, each builds on the last.
_Avoid_: batch, recursion, retry.

**Iteration** — one run of a Loop's step. Body counter `${__iteration__}` (1-based),
mirroring Batch's `${__index__}` (0-based item index). _Avoid_: cycle, pass, round.

**Loop condition** — the truthiness test deciding whether a Loop runs again. Reads a typed
output (list/number/boolean); stops when falsy (`[]`, `0`, `false`, `null`). Not an
expression language — richer conditions come from the body emitting a boolean. The polarity
lives in the keyword — *continue-while-truthy* vs *continue-until-truthy* — so the author
never mentally negates. _Avoid_: predicate, guard, filter.

**Carry** — state a Loop threads from one Iteration's output into the next Iteration's input,
declared explicitly so the output→input coupling is visible and checked. A *carried* input
changes each Iteration; a *constant* input is the same every Iteration. _Avoid_: accumulator,
feedback, recurrence, state-threading.

**Seed** — the round-1 value of a carried input: its starting value before any Iteration has
produced output. From round 2 on, the Carry supplies the value. A role, not a separate field —
a carried input's ordinary input value *is* its Seed. _Avoid_: initial, default, base.

**Snapshot** — the frozen prior-run state that `--only <step>` runs a single step against:
every *other* step's output reused from the most recent full run, so only the target
re-executes and upstream side effects never re-fire. Requires a prior full run.
_Avoid_: replay, restore, checkpoint.

## Ambiguity

**Batch vs Loop** — both repeat a step. Discriminator: can you write the list of runs
before starting (Batch), or only know you're done by inspecting what just happened (Loop).

**Snapshot vs Cache** — both reuse prior output. Cache reuses a step's *own* output when
its declared inputs are unchanged (correctness-gated, per-step, can still re-run the step).
Snapshot reuses *other* steps' outputs to isolate one step for iteration (`--only`),
regardless of whether their inputs changed, and never runs the frozen steps at all.

**Carry vs Seed** — both supply a carried input's value. Discriminator: the Seed is the value
for round 1 only (before the body has produced output); the Carry is the value for every round
after (the prior Iteration's output). One input key carries both roles.
