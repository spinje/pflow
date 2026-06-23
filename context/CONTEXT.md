# pflow

CLI-first system where AI agents author Markdown workflows (`.pflow.md`) chaining
**steps** that communicate through a shared store. This glossary fixes shared vocabulary.

## Language

**Step** — one authored unit of work in a `.pflow.md` (a `### name` heading under `## Steps`);
the authoring-surface noun. Each Step compiles to a *node* — a registered type instance the
engine executes. Same concept, two surfaces: agent-facing text says step, code/IR/registry say
node. _Avoid_: task, stage, action.

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

**Template** — a string in a Step's params containing `${…}` expressions, resolved against the
shared store at runtime and checked against declared output structure at validation — one parse
serves both surfaces. _Avoid_: placeholder, interpolation, substitution.

**Reference** — a path inside a template expression — a root (step, input, or batch alias) plus
field/index segments — naming data in the shared store. _Avoid_: variable, pointer, path
(unqualified).

**Coalesce** — the `??` operator in a template expression: Operands tried left to right, the
first present one wins; an absent root *or* an absent field falls through. _Avoid_: fallback,
default, or-else.

**Operand** — one alternative in a Coalesce chain: a Reference or a JSON literal. A literal
always resolves, ending the chain. _Avoid_: argument, branch.

**Retry** — re-running a *single step's own work* after a **transient** failure, capped by a
maximum attempt count, same inputs each time. A *deterministic* failure (e.g. bad config) is
not retried. A retry that eventually succeeds leaves no trace — the run is a clean Success.
_Avoid_: loop (advances across iterations), fallback, recursion.

**Backoff** — the growing wait between Retry attempts, either *fixed* (constant) or
*exponential* (doubling, clamped to a ceiling). _Avoid_: delay, sleep, cooldown.

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

**Run** — one execution of a Workflow from start to finish, producing a trace and ending in one
terminal status (Success, Degraded, or Failed). One Workflow definition yields many Runs; Runs of
the same Workflow may execute concurrently. _Avoid_: invocation, execution, session.

**Snapshot** — the frozen prior-run state that `--only <step>` runs a single step against:
every *prior* step's output reused from the most recent full run, so only the target
re-executes and upstream side effects never re-fire. Requires a prior full run.
_Avoid_: replay, restore, checkpoint.

**Prompt cache** — provider-side reuse of a static prompt *prefix* across LLM calls, declared
in a workflow's `## Cache` block (or per-step `prompt_cache:`). Discounts input tokens; the
step still executes and calls the provider every time. _Avoid_: cache (unqualified), KV cache.

**Graph model** — the renderer-agnostic semantic structure of a workflow: its nodes, edges,
and Containers as pure data, carrying no rendering syntax. Built once from the IR by a single
walk; every renderer (mermaid, react-flow, JSON) consumes it. _Avoid_: diagram, AST, scene.

**IR** — the compiled, *executable* representation of a workflow (nodes, edges, params) the
engine runs. The Graph model is the *structural* view derived from it: the IR is for running,
the Graph model is for showing. _Avoid_: AST, graph model.

**Container** — a named grouping of nodes in the Graph model: a sub-workflow, a Batch fan-out,
an input/output wrapper, or (future) a detected cycle. One record type for every grouping kind,
carrying its members, nesting depth, and parent. A Loop is metadata on its node, not a
Container. _Avoid_: subgraph, cluster, box, group.

### Viewer & agent interaction

**Viewer** — an open `pflow ui` browser window showing one workflow. Several Viewers can show
the same workflow at once; an agent's Point reaches all of them. _Avoid_: window, tab, canvas
(the canvas is the diagram drawn *inside* a Viewer).

**Point** — the agent action of focusing, framing, or clearing a target (a node, port, container,
or edge) in every Viewer showing a workflow, reusing the exact selection a user's click produces.
The agent-side counterpart to a user click — the "hands" half of the shared canvas.
_Avoid_: highlight, navigate; select (select is the user's click).

**Watch** — reading the recent, bounded history of the user's *deliberate* interactions in the
Viewers (clicks, focus changes, workflow switches — never hover/pan/zoom), most-recent-first.
The agent's read-only "eyes" onto what the user is doing; the CLI surface is `user-activity`.
_Avoid_: monitor, track, observe; auto-update (a different "watch", below).

**Auto-update** — the Viewer rebuilding its canvas in place when the workflow's `.pflow.md`
changes on disk, preserving view state. On by default; frozen with `pflow ui --no-auto-update`.
_Avoid_: watch, live-reload, hot-reload.

## Ambiguity

**Batch vs Loop** — both repeat a step. Discriminator: can you write the list of runs
before starting (Batch), or only know you're done by inspecting what just happened (Loop).

**Retry vs Loop** — both re-run a step. Retry re-runs the *same attempt* after a transient
failure (same inputs, capped, invisible once it succeeds). Loop re-runs across *iterations*,
each building on the last, until a condition goes falsy.

**Retry vs Fallback** — both are failure responses. Retry re-runs the *same* step hoping it
succeeds (→ Success). Fallback routes to a *different* step because the original failed
(→ Degraded).

**Cache vs Prompt cache** — both cut cost on repeat work. Discriminator: a (memoization) Cache
hit skips executing the step entirely, reusing its prior output; a Prompt cache hit still runs
the step and calls the provider — only the static prefix's input tokens are discounted.

**Snapshot vs Cache** — both reuse prior output. Cache reuses a step's *own* output when
its declared inputs are unchanged (correctness-gated, per-step, can still re-run the step).
Snapshot reuses *other* steps' outputs to isolate one step for iteration (`--only`),
regardless of whether their inputs changed, and never runs the frozen steps at all.

**Carry vs Seed** — both supply a carried input's value. Discriminator: the Seed is the value
for round 1 only (before the body has produced output); the Carry is the value for every round
after (the prior Iteration's output). One input key carries both roles.

**Graph model vs IR** — both represent a whole workflow. Discriminator: the IR is what the
engine *executes* (run-oriented, the source of truth for behavior); the Graph model is what a
renderer *draws* (structure-oriented, derived from the IR, never executed). They also identify
nodes differently — see ADR-0003.

**Watch vs Auto-update** — both involve "watching". Discriminator: Auto-update is the *Viewer*
watching the *source file* to live-rebuild the canvas (the `--no-auto-update` flag freezes it);
Watch is the *agent* watching the *user's* interactions (the `user-activity` command reads them).
Different watcher, different watched.

**Workflow vs Run** — both name "the thing that ran." Discriminator: the Workflow is the reusable
`.pflow.md` *definition* (authored once); a Run is one *execution* of it (one per `pflow run`). One
Workflow → many Runs (1→N); concurrent Runs of one Workflow are normal.
