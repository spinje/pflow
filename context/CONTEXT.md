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

**Retry** — re-running a *single step's own work* after a **transient** failure, capped by a
maximum attempt count, same inputs each time. A *deterministic* failure (e.g. bad config) is
not retried. A retry that eventually succeeds leaves no trace — the run is a clean Success.
_Avoid_: loop (advances across iterations), fallback, recursion.

**Backoff** — the growing wait between Retry attempts, either *fixed* (constant) or
*exponential* (doubling), clamped to a ceiling. _Avoid_: delay, sleep, cooldown.

**Fallback (on-error)** — routing to a *different* step when one fails, instead of re-running
it. The original step genuinely failed, so the run is Degraded (data may be lost) — distinct
from a Retry that makes the same step succeed. pflow recovery is forward-only: no rollback of
side effects already done. _Avoid_: catch, rescue, compensation.

**Degraded** — a run that *finished its work but flagged a non-fatal problem* (a Fallback
fired, a batch dropped failed items, output was salvaged). Completes successfully. Distinct
from **Failed** (a fatal error halted the run) and from a clean **Success**.
_Avoid_: partial, warning-state.

**Advisory** — information surfaced about a run that does **not**, on its own, mark it
Degraded (an empty batch, a Loop hitting its cap, a section typo parsed around). Contrast
with a degrading warning. _Avoid_: note, hint, info.

**Snapshot** — the frozen prior-run state that `--only <step>` runs a single step against:
every *other* step's output reused from the most recent full run, so only the target
re-executes and upstream side effects never re-fire. Requires a prior full run.
_Avoid_: replay, restore, checkpoint.

## Ambiguity

**Batch vs Loop** — both repeat a step. Discriminator: can you write the list of runs
before starting (Batch), or only know you're done by inspecting what just happened (Loop).

**Retry vs Loop** — both re-run a step. Retry re-runs the *same attempt* after a transient
failure (same inputs, capped, invisible once it succeeds). Loop re-runs across *iterations*,
each building on the last, until a condition goes falsy.

**Retry vs Fallback** — both are failure responses. Retry re-runs the *same* step hoping it
succeeds (→ Success). Fallback routes to a *different* step because the original failed
(→ Degraded).

**Snapshot vs Cache** — both reuse prior output. Cache reuses a step's *own* output when
its declared inputs are unchanged (correctness-gated, per-step, can still re-run the step).
Snapshot reuses *other* steps' outputs to isolate one step for iteration (`--only`),
regardless of whether their inputs changed, and never runs the frozen steps at all.

**Carry vs Seed** — both supply a carried input's value. Discriminator: the Seed is the value
for round 1 only (before the body has produced output); the Carry is the value for every round
after (the prior Iteration's output). One input key carries both roles.
