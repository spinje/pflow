# Braindump: how Task 125's landing changed the trace contract under task-164.md's feet

> Written 2026-07-02 at the close of the Task 125 verification/fix sessions (PR #554 branch
> `feat/human-loop-approval-gates`), by the agent that ran the 6-agent plan-vs-code sweep and
> the post-review fixes. Everything durable from those sessions is in task_125's task-review
> and progress log — this file carries ONLY what is written nowhere and matters to 164.

## The headline: "failed" traces now come in two flavors, and task-164.md assumes one

`task-164.md:53` says failed runs persist `final_status:"failed"` + `failed_node_ids`, and
`:66` designs the resume-scoped loader as "accepts `failed` (entry = first of
`failed_node_ids`)". **Both statements predate Task 125 and are now incomplete:**

1. **Node failure** (164's designed case): trailer `failed`, non-empty `failed_node_ids`,
   the failed node has an error event. Loader design holds.
2. **Gate failure** (new): a non-interactive gate (`GateNotInteractiveError`) or resolver bug
   (`GateResolverError`) also yields trailer `failed` — but via the collector's
   `gate_outcome` field, with **EMPTY `failed_node_ids` and NO failed node event**. For a
   PRE-exec approval gate the gated node has **no events at all** (deliberate: no
   `node.start`, no completion — it never ran). "Entry = first of failed_node_ids" hits an
   empty list here. There is also a third terminal literal now, `final_status:"denied"`
   (clean human "no", exit 3), which the `--only` allowlist deliberately excludes.

What the loader should probably do (my recommendation, not decided anywhere): treat
empty-`failed_node_ids` `failed` traces and `denied` traces as *gate-stopped*, and either
(a) refuse with an actionable "this run stopped at gate '<id>' — re-run it" message, or
(b) treat the gated node as the re-entry point. The re-entry node_id is recoverable ONLY from
the raw `gate` JSONL lines (`kind:"gate"`, `phase:"pause"`, carries the full `GateRequest`)
— these are **disk-only and invisible to `load_trace_file`** (the reconstruct reader skips
the kind; reading them needs a raw line pass). Option (b) is literally Task 171's substrate
(resume-at-a-gate), which is the argument for designing the loader arm so 171 plugs in
rather than special-casing gate traces away. **Flag this in 164's plan phase and update
task-164.md's loader section** — I did not edit it (that's 164's planning call).

## NEEDS VERIFICATION: seeding can replay an undecided escalation silently

Decision 10 (task 125 plan) skips BOTH cache writes for escalating results because "a memo
hit silently replays the escalation as resolved-without-a-decision" — the cache-hit
early-return sits before the detection seam. **The generalization nobody wrote down: that
rationale applies to EVERY state-replay channel, and 164 is building a new one.**

Concrete scenario: a non-interactive escalation abort leaves the escalating node's SUCCESS
event in the trace with the undecided `result.escalation` marker inside `node_output`
(post-exec seam: the node completed and was traced before the pause failed). That trace is
trailer-`failed`, which today's `--only` allowlist rejects — but 164's resume-scoped loader
*accepts failed traces by design*. If `seed_snapshot_into_shared` seeds that node as
completed upstream, the undecided marker re-enters shared state where NO detection seam will
ever fire (detection runs only on fresh execution in `_execute_node` step 10.5) and flows
into downstream templates as if a human had decided. Rule to carry into the design: **an
undecided `escalation` marker means the node is NOT valid upstream state** — treat that node
as the re-entry point (re-run it) or refuse the resume. I'm ~85% sure the scenario is real
(verified each link separately; never ran the combination end-to-end).

## Smaller unwritten couplings 164 will trip on

- **The trailer trap has three doors and 164 may add a fourth.** `_determine_trace_status`
  has no signal for a run that stops without a failed node event; `gate_outcome` (stamped by
  `record_gate` AND re-stamped by the engine's gate-except arm at every nesting level, root
  last) is what keeps denied/gate-failed trailers honest. If 164's substrate introduces any
  new stop-without-node-failure point (e.g. a `paused` trailer), it needs its own channel of
  this shape or the trace self-reports `success`.
- **Any new generic `except Exception` between engine and runner must preserve the
  three-way gate exemption** (`GateDenied`/`GateNotInteractiveError`/`GateResolverError`,
  all `retriable=False`). 164's restore/continue code paths are exactly where a new
  conversion boundary tends to appear. The boundary inventory is in task_125's
  implementation-plan + task-review invariants — grep before adding a handler.
- **A resumed run through a gated node prompts again.** Gates are per-execution by design
  ("each iteration is a new action" — same rule as loop re-prompting). 164's
  resume-and-continue will run gated downstream nodes; say in the UX docs that resume does
  not inherit prior approvals (`--auto-approve` works as usual).
- **Escalation decisions are written into the marker BEFORE the walk's loop-re-entry check
  reads the store** (step 17.7 vs `_run_inner`'s re-entry). If 164's continue mechanism
  re-enters the walk through a new path, preserve that ordering or `loop:`+carry escalation
  workflows break.

## Context for reading the branch state

- At the time of writing, everything through commit `5f161e4e` is committed; the
  gate-preview masking rework (`core/gate.py::masked_preview`) + task-review accuracy pass
  may still be uncommitted — check `git log` before assuming file contents match a hash.
- The user's operating emphasis across these sessions, in their words: verify plan-vs-code
  independently, "note any contradictions... and if they lead to any bad outcomes in the
  code", fix everything found, and keep the durable docs "as accurate and relevant as
  possible for future agents". Expect the same bar for 164: mutation-verified pins,
  baseline-then-delta test reporting, deviations recorded as they happen.

> **Note to next agent**: Read this document fully before taking any action. When ready,
> confirm you've read and understood by summarizing the key points, then state you're ready
> to proceed.
