# Task 171: Durable Resume Tokens & Non-TTY Gates

## Description

The durable half of human-in-the-loop gates: when a gate fires (or an agent escalates) and
no human is at the TTY, persist the run's state to disk, emit a self-contained resume token,
and exit — the human answers hours or days later with `pflow resume <token> --approve yes|no`
and the run continues without re-executing completed nodes. Carved out of Task 125's
"durable phase" (2026-06-12) so each task ships as one PR; it is a thin trigger over the
checkpoint→restore→continue substrate Task 164 builds.

## Status

not started

## Priority

medium

## Problem

Task 125's blocking gates require a human present during the run — the pause lives in-process
and dies with it. That excludes the contexts where gates matter most: CI, scheduled/cron runs,
long-running agent harnesses where the human checks in asynchronously, and any non-TTY caller
(MCP, pipes). Without durability, a gate in an unattended run is a hang or a hard stop, and
the decision the human owed the workflow is lost with the process.

## Solution

At an unanswerable gate (non-TTY, or `--no-block`-style policy TBD):

1. Checkpoint: serialize the shared store (completed node outputs), the pause position, the
   workflow identity (path/name + definition hash), and the original input params to
   `~/.pflow/resume/<execution-id>.json`.
2. Emit a compact, self-contained resume token referencing that state; exit cleanly with a
   parseable message.
3. `pflow resume <token> --approve yes|no` loads the state, reconstructs the shared store,
   and — via Task 164's restore+continue substrate — runs the gated node and everything after
   (approve) or exits with a clear cancellation message (deny).

The gate trigger and the structured decision payload come from Task 125; the
restore-and-continue mechanics come from Task 164; this task adds only the durable seam:
the checkpoint writer, the token, the resume-state lifecycle, and the `pflow resume` CLI.

## Design Decisions

- **Why this is its own task (2026-06-12):** the original build order was a sandwich
  (125-blocking → 164 → 125-durable), which contradicts the one-PR-per-task convention —
  half a task shipping twice. Decision: split. Build order is now **125 → 164 → 171**.
- **Thin trigger over 164's substrate, not its own machinery:** restore-and-continue is built
  exactly once (Task 164); this task must not grow a second serialization/walk-entry path.
  If implementation pressure pushes toward a parallel mechanism, that's a design smell — stop
  and revisit with 164's substrate.
- **Resume tokens are self-contained** (carried from 125): token encodes workflow identity,
  pause position, completed outputs reference, and a protocol version. A future session with
  no prior context resumes from the token alone.
- **State goes to `~/.pflow/resume/`** (carried from 125): serialized shared store at the
  pause point; tokens reference this state; cleanup after successful resume or configurable TTL.
- **The checkpoint is a purpose-built state file, NOT the debug trace.** This is the key
  structural difference from Task 164: 164 restores from a *failed run's trace* (sanitized:
  bytes → placeholder, `default=str`), because failure is uncontrolled. A gate pause is
  CONTROLLED — the checkpoint is written deliberately at a clean point (before the gated node
  runs), so this task can write faithful state and avoid the trace's lossy-serialization
  caveats. The *restore* side should still share 164's seed semantics (one restore reader,
  two state sources) — coordinate the format with 164's snapshot-fidelity decision so the
  substrate's restore half reads both.
- **One decision surface** (carried from 125): the persisted decision payload is the same
  structured data the blocking gate renders — parseable for CLI prompt and the planned web UI
  (Task 155), never a printed string.

## Dependencies

- **Task 164: Resume Workflow From a Failed Node** — builds the restore+continue substrate
  (shared walk-entry helper, resume-scoped seeding) this task triggers. Also owns the
  snapshot-fidelity decision the checkpoint format must coordinate with.
- **Task 125: Human-in-the-Loop Approval Gates (blocking)** — the gate primitive
  (`approval:` on NodeConfig), the agent-escalation trigger, and the structured decision
  payload this task persists.
- **CLI surface — resolve jointly with 164:** `pflow resume` must serve BOTH "resume a paused
  gate" (this task, token-addressed) and "resume a failed run" (164, workflow-addressed).
  Decide one coherent surface (e.g. `pflow resume <token>` vs `pflow <workflow> --resume`)
  before either task ships its CLI. Flagged unresolved in both sibling specs.

## Requirements

### Checkpoint & token
- A gate firing in a non-TTY context emits a resume token to stdout in a parseable form and
  exits with a distinct, documented exit code (not the failure exit code).
- The checkpoint contains everything resume needs: shared store snapshot, pause position,
  workflow path/name + definition hash, original input params, protocol version.
- Checkpoint write is atomic (no torn state file on kill mid-write).

### Resume
- `pflow resume <token> --approve yes` continues from the gated node without re-executing
  completed nodes; final outputs match an uninterrupted approved run.
- `pflow resume <token> --approve no` exits cleanly with a message naming the cancelled step
  ("Workflow cancelled at step 'notify-slack'"); no side effects fire.
- Workflow definition changed between pause and resume (hash mismatch): warn and require
  `--force` to proceed.
- Multiple gates: resuming past gate 1 runs until gate 2 pauses again (each gate is an
  independent checkpoint/token).
- Unknown/expired/cleaned-up token: clear, agent-actionable error — never a silent fresh run.

### Lifecycle
- `pflow resume list` shows pending checkpoints (workflow, gated step, age).
- Cleanup after successful resume; configurable TTL for abandoned checkpoints; no auto-cancel
  by default.

### Security (decide, don't default silently)
- Token/state tamper-resistance was raised in the original discussion (signed/encrypted
  tokens — `task_125/starting-context/braindump-openclaw-discussion.md`) and never resolved.
  The state file approves real-world actions; at minimum make an explicit, recorded decision
  on whether v1 trusts the local filesystem (likely fine — single-user CLI) or signs tokens.

### Out of scope (v1)
- Resuming into a sub-workflow child (same dotted-path limitation as 164/`--only`; child
  plumbing dormant under #443).
- Escalation raised inside a parallel batch item (rejected loudly per task-125 v1 scoping).
- Hard-kill recovery (no checkpoint exists if the process was SIGKILLed before a gate fired).

## Implementation Notes

- The pause point is 125's inline gate check in `WorkflowEngine._execute_node` (after template
  resolution, before exec) — this task adds the "can't block → checkpoint and exit" branch.
- Restore should reuse 164's seed semantics (`seed_snapshot_into_shared`-shaped) reading the
  resume-state file instead of a trace. One restore reader, two sources — do not fork the
  seeding logic (the planner-mirror lesson, issue #504: re-forked copies drift; PR #505's
  mutation experiment showed 43 green tests missing a visibly drifted fork).
- Dry-run parity: `--dry-run` on a resume should be consistent with whatever 164 decided for
  `--dry-run --resume` (recorded decision in task-164.md "Engine/planner parity plan" §2).
- Original durable-phase notes (state serialization steps, edge cases, CLI sketch) were
  drafted in task-125.md pre-split — preserved here in Requirements/Solution; the CLI sketch:

```bash
pflow my-workflow param=value
# Output: Paused at 'notify-slack'. Resume token: pflow-resume-abc123
pflow resume pflow-resume-abc123 --approve yes
pflow resume pflow-resume-abc123 --approve no
pflow resume list
```

## Verification

- **Resume flow**: paused workflow resumes from token without re-executing completed nodes;
  shared-store integrity verified (all pre-pause outputs addressable post-resume).
- **Non-TTY mode**: token emitted to stdout, parseable by a calling process; distinct exit code.
- **Deny flow**: denied approval exits cleanly with the named step; no side effects.
- **Stale resume**: definition changed → warning; `--force` proceeds; without it, refusal.
- **Multiple gates**: 2+ gates checkpoint/resume in sequence.
- **Durable escalation**: an agent-raised escalation in a non-TTY run produces a token whose
  payload carries the structured decision (options/tradeoffs/recommendation); answering it
  continues from the decision.
- **Lifecycle**: `pflow resume list` shows pending; TTL cleanup removes abandoned state;
  resumed token is consumed (second resume of the same token errors clearly).

## References

- **Origin spec**: `.taskmaster/tasks/task_125/task-125.md` — Architecture (the three-trigger
  substrate), Phasing (blocking vs durable — the split this task formalizes).
- **Substrate**: `.taskmaster/tasks/task_164/task-164.md` — Reuse, The delta, Engine/planner
  parity plan (Phase-0 shared walk-entry helper; snapshot-fidelity decision).
- **Braindumps**: `task_125/starting-context/braindump-escalation-and-resume-substrate.md`
  (CLI collision, token security, nested escalation — lines ~170-182),
  `task_164/starting-context/braindump-planner-mirror-session.md` (parity discipline,
  mutation-test recipe).
- **Prior art**: `.taskmaster/tasks/task_73/` (deprecated checkpoint persistence; idempotency
  analysis), ADR-0002 (`context/adr/0002-443-only-snapshot-source.md` — trace-vs-store
  tradeoffs the checkpoint format must answer differently).
