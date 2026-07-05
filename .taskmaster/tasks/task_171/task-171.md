# Task 171: Durable Resume Tokens & Non-TTY Gates

> **Refreshed 2026-07-02 against main** — checkpoint design re-derived on the shipped trace
> substrate; the original purpose-built-state-file decision rested on now-false premises.
> Restore contract follows Task 164's implementation (standing rule from the split braindump).
>
> **164 SHIPPED 2026-07-04 (PR #559) — this spec absorbed the handoff.** The restore substrate now
> exists and is authoritative: read `task_164/task-review.md` FIRST and trust it over any
> pre-implementation phrasing below. Concrete integration points already folded in: the loader lives
> in `runtime/workflow_trace.py` (~400 lines) and must be **extracted to `runtime/resume_source.py`
> FIRST** (the `paused` arm is the extraction-trigger third consumer); the `paused` insertion point
> is `load_resume_source`'s gate-stopped refusal arm (entry = `paused_node_id`); `resume list` reuses
> `_attempt_consumed_work`; the **UI attempt-chain rendering is 171's** (owner decision 07-04, section
> below). Trace format shipped at **2.6.0** (`resumed_from` meta + `restored` events).

## Description

The durable half of human-in-the-loop gates: when a gate fires (or an agent escalates) and
no human is at the TTY, persist the run's state to disk, emit a resume token (the run's
`execution_id` under the recommended trace-as-checkpoint design), and exit — the human
answers hours or days later with `pflow resume <token> --approve yes|no`
and the run continues without re-executing completed nodes. Carved out of Task 125's
"durable phase" (2026-06-12) so each task ships as one PR; it is a thin trigger over the
checkpoint→restore→continue substrate Task 164 builds.

## Status

done

## Completed

2026-07-05 (branch `feat/durable-resume-tokens`, commits `a8066f15`→`fde74150`). All five
phases shipped: loader extraction, paused producer (exit 4 + token), loader answer arm,
`pflow resume --approve/--choose` + `resume list`, UI chain/paused rendering, and docs.
See `task-review.md` for the shipped surface and `implementation/progress-log.md` for the
chronology. Follow-on: #562 (resumable inline workflows), Task 176 (web-UI approval bridge).

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

1. Checkpoint: under the recommended trace-as-checkpoint design (see Design Decisions), the
   streamed trace already IS the checkpoint — completed node outputs, workflow identity,
   definition hash, original inputs, protocol version, and run identity are on disk before
   the gate fires. The only datum written at pause time is the pause position + decision
   payload, carried on the `run.complete` trailer (`final_status: "paused"` +
   `paused_node_id` + the Task-125 `GateRequest` payload).
2. Emit the resume token — the run's `execution_id` — in a parseable form; exit cleanly.
3. `pflow resume <execution-id> --approve yes|no` loads the paused trace via Task 164's
   `load_resume_source` (paused branch), reconstructs the shared store, and — via the same
   engine re-entry — runs the gated node first and everything after (approve) or exits with
   a clear cancellation message (deny).

The gate trigger and the structured decision payload come from Task 125; the
restore-and-continue mechanics come from Task 164; this task adds only the durable seam:
the pause-time trailer write, the token surface, paused-run lifecycle, and the `pflow resume`
CLI verb.

## Design Decisions

> **SETTLED AT PLAN TIME (2026-07-04, owner session — supersedes the open markers below):**
> (1) **Paused encoding**: `final_status: "paused"` on the `run.complete` trailer +
> `paused_node_id` + `gate_request` payload; no new line kind. (2) **Gated-runs-require-trace**:
> resolved by DELETING the MCP special case — `execute_workflow` streams traces like the CLI
> (registry probe stays traceless); `--no-trace` remains an explicit opt-out whose gates keep the
> hard error (message updated). Neither spec option (a)/(b) — simpler final code than both; amend
> ADR-0008's "CLI-only" sentence at ship. (3) **Escalation resume**: restore the completed
> escalating step, fold the `--choose` answer into its event (`_apply_gate_resolutions` shape),
> enter at its successor — the agent step is never re-paid. (4) **Pause exit code: 4**
> (0/1/2/3/130 taken). (5) **Token security**: explicit v1 trust-the-local-filesystem; no
> signing. Also confirmed: trace-as-checkpoint (the importance-4 confirm below); MCP token
> surface = paused status + `execution_id` + `gate_request` + `resume_command` in the structured
> result. Full rationale + plan: `implementation/implementation-plan.md`.

- **Why this is its own task (2026-06-12):** the original build order was a sandwich
  (125-blocking → 164 → 125-durable), which contradicts the one-PR-per-task convention —
  half a task shipping twice. Decision: split. Build order is now **125 → 164 → 171**.
- **Thin trigger over 164's substrate, not its own machinery:** restore-and-continue is built
  exactly once (Task 164); this task must not grow a second serialization/walk-entry path.
  If implementation pressure pushes toward a parallel mechanism, that's a design smell — stop
  and revisit with 164's substrate. **Trust calibration (reinforced 2026-07-02):** this spec
  is a carve — the mechanisms named here are ASSUMED, not verified against 164's eventual
  code. The restore contract is pinned BY Task 164's implementation; this task consumes it.
  If 164 implemented restore differently, follow 164.
- **The checkpoint IS the trace — no purpose-built state file (RECOMMENDED 2026-07-02;
  USER decision, importance 4 — confirm at task start).** The original decision here was
  "purpose-built state file at `~/.pflow/resume/<execution-id>.json`, NOT the debug trace";
  its premises are now false on the shipped trace substrate. Every field the checkpoint was
  spec'd to persist already exists in every streamed trace: per-node terminal outputs (event
  lines), workflow identity (`workflow_path`/`workflow_name`), definition hash
  (`content_hash`, meta line — `workflow_trace.py:575-583`), original inputs (`meta.inputs`,
  raw on disk — `workflow_trace.py:634-640`), protocol version (`format_version`), and run
  identity (`execution_id`, on meta AND trailer). The ONLY missing datum is the pause
  position + decision payload — carried on the `run.complete` trailer:
  `final_status: "paused"` + `paused_node_id` + the Task-125 `GateRequest` payload (the
  reader's "conditional trailer key is never silently dropped on round-trip" contract,
  `trace_io.py:24`, covers this). Consequences: **the resume token IS the `execution_id`**;
  `pflow resume <id> --approve yes|no` → Task 164's `load_resume_source` (paused branch) →
  the same engine re-entry, gated node first; `pflow resume list` is a status query over the
  debug dir. NO `~/.pflow/resume/`, no second serializer, no second reader: **one reader,
  one source (the trace), two terminal statuses (`failed`/`paused`)**.
- **Gated runs REQUIRE a trace — the MCP/`--no-trace` constraint (open sub-decision,
  2026-07-02; resolves the design's one real tension).** MCP and `--no-trace` runs write NO
  trace file at all (`stream_to_disk=False`, `runner.py:156`) — and this task exists
  precisely for the MCP/non-TTY case. A durably-pausing gate therefore requires the trace.
  Resolution (either way, NO second format): (a) auto-enable trace streaming for gated runs,
  or (b) flush-on-pause — materialize the file at pause time from the collector's in-memory
  flat event store. Recommendation: decide at task start; (a) is simpler.
- **Attempt-chain lineage (APPROVED 2026-07-02; canonical definition lives in task-164.md —
  cross-reference it, don't duplicate):** a resumed attempt is a new trace with a new
  `execution_id` and `resumed_from` on the meta line. Token-consumption semantics fall out
  of the chain — a newer attempt exists = token consumed. Pre-resume liveness is checked via
  the writer's flock (`is_trace_locked`).
- **Paused-status encoding (open decision, with recommendation):** `final_status: "paused"`
  on the `run.complete` trailer (recommended — no new line kind; the reader's "trailer is
  the final line" contract holds) vs a new `run.paused` kind (touches
  `_partition_trace_lines`, `trace_io.py:126-173`). Note `"incomplete"` is
  reader-synthesized only — `paused` would be the first non-terminal-ish status the PRODUCER
  writes; consumers (UI status rendering, the `--only` allowlist at
  `workflow_trace.py:259-261`) must handle it.
- **Retention interplay with #542:** open issue #542 wants to prune unbounded
  `~/.pflow/debug` growth. Under trace-as-checkpoint a `paused` trace is a LIVE OBLIGATION,
  not a debug artifact — retention must be status-aware (never prune `paused`; consider an
  explicit pause-expiry policy — approvals arguably should expire, like stale terraform
  plans). #542 must be designed WITH or AFTER this task.
- **One decision surface** (carried from 125): the persisted decision payload is the same
  structured data the blocking gate renders — parseable for CLI prompt and the planned web UI
  (Task 155), never a printed string.

## Dependencies

- **Task 164: Resume Workflow From a Failed Node** — builds the restore+continue substrate
  (shared walk-entry helper, resume-scoped seeding, `load_resume_source`) this task triggers.
  Under trace-as-checkpoint there is no separate format to coordinate: the trace is 164's
  source, and the restore contract is whatever 164 ships. **Read
  `.taskmaster/tasks/task_164/task-review.md` FIRST** — it is the shipped-substrate handoff
  (invariants that must not break, the `paused` insertion point, gotchas); 164 shipped, so
  trust it over any pre-implementation phrasing in this spec. One interplay noted here because
  it is written nowhere else: the seed scope EXCLUDES the entry node, so a paused gate's own
  undecided escalation marker is never scanned by the seed guards — the `paused` arm composes
  with the escalation-resolution fold (`_apply_gate_resolutions`) with zero changes.
- **Task 125: Human-in-the-Loop Approval Gates (blocking)** — the gate primitive
  (`approval:` on NodeConfig), the agent-escalation trigger, and the structured decision
  payload this task persists.
- **CLI surface — resolve jointly at 164 start:** `pflow resume` must serve BOTH "resume a
  paused gate" (this task) and "resume a failed run" (164). Trace-as-checkpoint softens the
  collision — both are execution-id-addressed reads of the same debug dir — but one coherent
  surface must still be decided before either task ships its CLI. Flagged unresolved in both
  sibling specs.

## Requirements

### Checkpoint & token
- A gate firing in a non-TTY context emits the resume token (the `execution_id`) to stdout
  in a parseable form. The distinct, documented exit code (not the failure exit code) was
  invented in the carve and never reviewed — **open decision**, settle it during this task.
- Everything resume needs is on the trace: per-node outputs, workflow path/name + definition
  hash (`content_hash`), original input params (`meta.inputs`), protocol version
  (`format_version`) are already streamed; the pause-time trailer adds `final_status:
  "paused"`, `paused_node_id`, and the `GateRequest` payload.
- The pause-time trailer write is atomic (no torn trailer on kill mid-write).
- MCP callers: `execution_service` must return the token in its structured result — the
  surface is still undesigned (flagged in the split braindump).

### Resume
- `pflow resume <execution-id> --approve yes` continues from the gated node without
  re-executing completed nodes; final outputs match an uninterrupted approved run.
- `pflow resume <execution-id> --approve no` exits cleanly with a message naming the
  cancelled step ("Workflow cancelled at step 'notify-slack'"); no side effects fire.
- Workflow definition changed between pause and resume (`content_hash` mismatch): warn and
  require `--force` to proceed.
- Multiple gates: resuming past gate 1 runs until gate 2 pauses again — each pause is a new
  attempt in the chain, with its own trace and `execution_id`.
- Unknown/consumed/pruned token: clear, agent-actionable error — never a silent fresh run.

### Lifecycle
- `pflow resume list` shows pending paused runs (workflow, gated step, age) — a status query
  over the debug dir, not a separate registry.
- Consumption via attempt-chain lineage (a newer attempt exists = consumed); retention is
  status-aware per the #542 interplay decision — never prune `paused` by default; an explicit
  pause-expiry policy may be added; no auto-cancel by default.

### UI attempt-chain rendering (folded in from 164, owner decision 2026-07-04)
Task 164 left `resumed_from` on the meta line and deliberately shipped NO chain UI — one
logical execution currently renders as separate, unlinked runs. This task owns closing that
(natural fit: it already touches run-status rendering for `paused` and builds the chain-walk
for `resume list` — render failed-chains and paused-chains in the same pass):
- Surface `resumed_from` in `/api/runs` (`ui/run_tailer.scan_traces` reads the meta line
  already; the field is a one-line addition — verified absent 2026-07-04).
- Run list/selector: mark resumed attempts (e.g. `⤷ resumed from <short-id>`) and group or
  visually link a chain's attempts; chain membership = walk `resumed_from` (reuse/port
  `_attempt_consumed_work` semantics for "which attempt is current").
- Consider an honest `restored` node style instead of piggybacking on `cached` (the frontend
  strips the event's `restored` flag in the tailer projection today; keeping cached-style is
  acceptable if a distinct style doesn't earn its keep).

### Security (decide, don't default silently)
- Token/state tamper-resistance was raised in the original discussion (signed/encrypted
  tokens — `task_125/starting-context/braindump-openclaw-discussion.md`) and never resolved.
  The paused trace approves real-world actions. **Open decision, with recommendation:** v1
  makes an explicit, recorded "trust the local filesystem" decision (likely fine —
  single-user CLI) rather than signing tokens; record it, don't default silently.

### Out of scope (v1)
- Resuming into a sub-workflow child (same dotted-path limitation as 164/`--only`; child
  plumbing dormant under #443).
- Escalation raised inside a parallel batch item (rejected loudly per task-125 v1 scoping).
- Hard-kill recovery (a SIGKILL before a gate fired leaves a trace with no paused trailer —
  that's 164's failed/crash territory, not a resumable pause).

## Implementation Notes

- The pause point is 125's inline gate check in `WorkflowEngine._execute_node` (after template
  resolution, before exec) — this task adds the "can't block → write paused trailer and exit"
  branch.
- Restore reuses 164's seed semantics (`seed_snapshot_into_shared`-shaped) via
  `load_resume_source`'s paused branch. One reader, one source (the trace), two terminal
  statuses (`failed`/`paused`) — do not fork the seeding logic (the planner-mirror lesson,
  issue #504: re-forked copies drift; PR #505's mutation experiment showed 43 green tests
  missing a visibly drifted fork).
- Dry-run parity: `--dry-run` on a resume should be consistent with whatever 164 decided for
  `--dry-run --resume` (recorded decision in task-164.md "Engine/planner parity plan" §2).
- **Module placement (164 post-review note, 2026-07-04):** `runtime/workflow_trace.py` has
  accreted the whole resume loader (`ResumeSource`, `load_resume_source`, entry resolvers,
  raw-line reader, flock probe — ~400 lines) beside the collector/readers/seeder. When this
  task adds the `paused` arm (and `resume list`), extract the loader into its own module
  (e.g. `runtime/resume_source.py`) FIRST — the paused arm is the third consumer-shaped
  growth spurt, which is the extraction trigger the 164 review deferred on. Also fold
  `_attempt_consumed_work` reuse for `resume list` (noted in its docstring).
- Original durable-phase notes (state serialization steps, edge cases, CLI sketch) were
  drafted in task-125.md pre-split — preserved here in Requirements/Solution; the CLI sketch:

```bash
pflow my-workflow param=value
# Output: Paused at 'notify-slack'. Resume token: <execution-id>
pflow resume <execution-id> --approve yes
pflow resume <execution-id> --approve no
pflow resume list
```

### Consumers & synergies (2026-07-02)

- Browser-launched runs are non-TTY by construction (`/api/run` spawns with `stdin=DEVNULL`,
  `server.py:853-858`) — this task is what unlocks gates for the web UI.
- Paused runs appear in `pflow ui` for free: the run list is trace-based, and a paused trace
  is just another trace in the debug dir.
- The post-171 web-approval bridge (defined in task-125's refresh: the overlay renders the
  gate event; `POST /api/approve` spawns `pflow resume`) is the follow-on, not in scope here.
- **External approval surfaces generalize the same pattern (noted 2026-07-02, all future
  follow-ons — build none now):** any surface (Slack buttons, email, webhook, phone app) is an
  out-of-process bridge doing read-the-gate → render-`GateRequest` → run
  `pflow resume <execution-id> --approve yes|no`. The engine stays surface-ignorant (the
  payload is the seam). Two notes for when the first bridge is built: (a) an optional
  `on_pause` notification hook (run a command / POST the payload) is additive at the single
  pause site — do not pre-build it (polling `pflow resume list` suffices until then); (b)
  bridges own their own authentication; pflow's trust boundary stays "whoever can run the CLI
  locally" (the v1 token-security decision is unchanged). This reinforces the existing
  requirement that `GateRequest` be self-contained — a remote human must be able to decide
  from the payload alone.

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
- **Lifecycle**: `pflow resume list` shows pending paused runs; retention never prunes
  `paused` traces; resumed token is consumed via attempt-chain lineage (a newer attempt
  exists → second resume of the same id errors clearly); a live writer (`is_trace_locked`)
  blocks premature resume.

## References

- **Origin spec**: `.taskmaster/tasks/task_125/task-125.md` — Architecture (the three-trigger
  substrate), Phasing (blocking vs durable — the split this task formalizes).
- **Substrate**: `.taskmaster/tasks/task_164/task-164.md` — Reuse, The delta, Engine/planner
  parity plan (Phase-0 shared walk-entry helper; snapshot-fidelity decision;
  **attempt-chain lineage — canonical definition**).
- **Trace substrate (verified 2026-07-02)**: `src/pflow/core/trace_io.py` (reader
  contracts — trailer round-trip `trace_io.py:24`, `_partition_trace_lines`
  `trace_io.py:126-173`), `src/pflow/ui/run_tailer.py:135` (`is_trace_locked`),
  `src/pflow/runtime/workflow_trace.py`
  (`content_hash` 575-583, raw `meta.inputs` 634-640, `--only` allowlist 259-261),
  `src/pflow/execution/runner.py:156` (`stream_to_disk=False` for MCP/`--no-trace`),
  `src/pflow/ui/server.py:853-858` (browser runs spawn `stdin=DEVNULL`).
- **Retention**: issue #542 (debug-dir pruning — must be status-aware, designed with/after
  this task).
- **Braindumps**: `task_125/starting-context/braindump-escalation-and-resume-substrate.md`
  (CLI collision, token security, nested escalation — lines ~170-182),
  `task_164/starting-context/braindump-planner-mirror-session.md` (parity discipline,
  mutation-test recipe).
- **Prior art**: `.taskmaster/tasks/task_73/` (deprecated checkpoint persistence; idempotency
  analysis), ADR-0002 (`context/adr/0002-443-only-snapshot-source.md` — trace-vs-store
  tradeoffs; the 2026-07-02 refresh resolves them in favor of the trace).
