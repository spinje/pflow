# Task 176: Web-UI Approval Bridge — approve/deny paused gates from the browser

## Description

Close the approval loop in the browser: once Task 125 ships the gate primitive and Task 171 ships
durable pause/resume, the live overlay will *show* a paused gate (the `gate` trace event) but offer
no way to *act* on it — this task adds approve/deny controls that spawn `pflow resume
<execution-id> --approve yes|no`, the same ADR-0008-conformant observe-and-spawn pattern as the
shipped `POST /api/run`. It also owns the **Resume button on failed/interrupted runs** (folded in
2026-07-04 — same UI→`pflow resume` plumbing, different entry arm; see the section below).

> **Deliberately thin draft (2026-07-02).** This task exists so the bridge has a home and a place in
> the build order — NOT as a design. Every mechanism named below is ASSUMED from the 2026-07-02
> spec refresh of Tasks 125/164/171; **design this against the SHIPPED 125/171 code at task start,
> not against their specs** (the Task-171-carve lesson: specs written ahead of their substrate go
> stale; re-verify everything).

## Status

not started

> Draft — blocked on Tasks 125 → 164 → 171 (see Dependencies).

## Priority

low (immediately after 171; small)

## Problem

Browser-launched runs are non-TTY by construction (`POST /api/run` spawns with
`stdin=subprocess.DEVNULL` — `src/pflow/ui/server.py:853-858`). So the moment gates ship: a gated
workflow launched from `pflow ui` pauses durably (171), the overlay renders "waiting for approval"
(125's `gate` event) — and the user must leave the browser for a terminal to answer. An observable
gap that is hit on day one of 125+171, on the product's own primary demo surface.

## Solution (the pattern — canonical statement in task-171.md "Consumers & synergies")

Any approval surface = **read the gate → render `GateRequest` → deliver the answer via
`pflow resume`**. For the web UI:

1. Overlay already shows the paused gate (`gate` event / `paused` trailer) — Task 125/171 work,
   not this task's.
2. Detail panel renders the `GateRequest` payload (self-contained by contract — a remote human can
   decide from the payload alone) with Approve/Deny controls.
3. `POST /api/approve` → server spawns `pflow resume <execution-id> --approve yes|no` as a detached
   subprocess. The server stays a pure observer (ADR-0008); this is its second sanctioned spawn,
   structurally identical to `/api/run`. Guarded by the shared `_require_local_origin` Host-header
   check like every mutating POST (Task 175 precedent).

Earlier sizing estimate: ~50 lines of bridge. If it grows past "small," something is wrong — the
engine and payload were designed so surfaces are cheap (the payload is the seam).

## The agent-operated run (added 2026-07-02 — from the 125 planning session)

The scenario this bridge really serves: the run's *operator* is an AI agent (Claude Code via
shell, or the MCP server), but the gate's *approver* must be the human behind it. Named
honestly during 125 planning:

- **The gate is not a security boundary against the operating agent.** An agent with shell
  access under the user's account can pass `--auto-approve=<node-id>`, run `pflow resume
  <token> --approve`, or simply edit the workflow to delete the gate. No local design
  prevents this — true prevention needs a secret outside the agent's reach, which doesn't
  exist within one account.
- What the design provides instead is **deliberate + visible + auditable** bypass: the flag
  names the exact gate (and appears verbatim in the command the agent's own harness asks the
  human to approve, one layer up); every gate resolution event carries `resolved_via:
  prompt | flag | ui` (125 ships `prompt|flag`; this task adds `ui`), so "which gates were
  self-approved by an agent" is a trivial trace audit; and 125's non-TTY gate error
  explicitly instructs agents to ask their human before using `--auto-approve`.
- This task's UI button is the **convenient human path** for agent-operated runs: the agent
  relays the link, the human clicks approve in a surface the agent isn't driving. That's the
  practical answer to "how does the human stay in the loop when an agent runs the workflow"
  — convenience + audit, not enforcement.

## Resume button on failed/interrupted runs (folded in from the 164 wrap-up, owner decision 2026-07-04)

164 shipped resume as CLI-only; 171 makes chains *visible* in the UI (its "UI attempt-chain
rendering" section); this task makes them *actionable* — a Resume control on a run whose
`final_status` is `failed` or `incomplete`, spawning `pflow resume <execution-id>` via the same
observe-and-spawn seam as the approval controls (one spawn helper serves both; that's why the
button lives here and not in 171).

Design notes recorded now so the designer doesn't hit them cold (verify against shipped code at
task start, per this draft's standing caveat):

- **The spawn is non-TTY by construction** (`stdin=subprocess.DEVNULL`), so a side-effecting
  entry step K makes bare `pflow resume` hard-error (`ResumeSideEffectConfirmationError`,
  Decision 4 — deliberate agent-safety posture). The browser confirmation dialog therefore IS
  the confirmation: render K + its registry type + "its side effects may fire again" (the same
  what/why the CLI confirm shows), and spawn with `--force` only after explicit user ack. Never
  pass `--force` without the dialog. Same handling for the stale-workflow gate
  (`ResumeStaleWorkflowError`): surface "edited since the failed run" and require the ack.
- **Refusals are the UX, not errors to swallow**: the loader's typed refusal family
  (superseded → offer the newer attempt; gate-stopped/denied; nothing-to-resume; still-running)
  maps to specific panel states. Exit-code-1 spawn output must reach the panel (the 175
  "spawn failures surface, never a silent no-op" rule).
- **Idempotent K (llm) resumes without a dialog** — mirror the CLI's silent path; don't
  blanket-confirm every resume.
- Whether the button also serves `paused` runs (171's arm) with approve/deny folded into one
  control is a task-start design call — the plumbing is shared either way.

## Canvas truth for paused runs: ⏸ frontier badge + un-run greying (owner idea, folded in 2026-07-05)

Proposed by the owner while driving 171's shipped UI: a paused run's canvas is nearly mute about
the pause — completed nodes wear their badges, but the gated node looks identical to any node
that never ran; the pause position lives only in the callout text and banner. Two additions,
scoped here because the ⏸ badge is the natural ANCHOR the approval controls (this task's core)
attach to:

1. **⏸ badge on the frontier node** — the paused-at node gets an amber pause badge on the same
   corner `StatusBadge` surface (mirroring ✓/!/spinner). Data already exists: the paused trailer
   carries `paused_node_id` (+ the full `gate_request`), and the tailer forwards trailer keys
   generically — verify the join at task start, but no producer change is expected. This is a
   CLIENT-synthesized per-node status derived from the banner, NOT a new trace event status —
   `events.ts` `RUN_STATUSES` (the per-node EVENT allowlist) stays untouched (the 171-plan rule).
   Clicking the ⏸ node is then the natural entry to the gate panel → Approve/Deny.
2. **Grey out the not-yet-run region** — dim nodes and edges the pinned run never executed, so
   the canvas reads: bright = ran, ⏸/! = frontier, grey = still owed. Design this as generic
   "run-replay truth", not a paused-only feature: failed runs have the same shape, and on a
   success replay the not-taken branches greying is genuinely informative. Owner-aligned scoping
   call (2026-07-05 discussion): pinned terminal replays ONLY, never live runs (a live shrinking
   grey region duplicates what the badges animate and would flicker). Reuse the existing cheap
   restyle machinery (the focus-dim pass — no re-layout); the care point is composition with
   focus-dimming, hover marks, and both densities.

Sizing: the badge is small (a day-ish with tests + real-browser check); the greying is the larger
half (composition testing). Both are presentation-only — zero engine/trace changes, consistent
with this task's "if the bridge needs engine changes, escalate" rule.

## Explicitly out of scope

- **Slack / email / webhook / any external surface.** Deliberately NOT tasked (Core Directive:
  solve observed problems, not theorized ones). The generalized pattern + the two constraints for
  whoever builds the first external bridge (the additive `on_pause` notification hook; bridges own
  their own authn — pflow's trust boundary stays "can run the CLI locally") are recorded in
  `task-171.md` "Consumers & synergies". Write that task when a real need is observed.
- Any engine/payload changes — if the bridge needs them, the 125/171 contracts failed; escalate
  rather than patch around.

## Dependencies

- **Task 125** — the gate primitive, `GateRequest`, the `gate` trace event.
- **Task 164** — the resume machinery (`load_resume_source`, engine re-entry, attempt chains).
  **Read `.taskmaster/tasks/task_164/task-review.md` first** (shipped-substrate handoff:
  refusal family, side-effect policy, invariants). One fact for the merged-control design call
  above, written nowhere else UI-adjacent: `--auto-approve` pre-approves APPROVAL gates only
  (`gate_prompt.py`, kind-checked) — escalations always need a delivered decision, so an
  escalation-paused run can never be resumed by a flag alone.
- **Task 171** — durable pause (`paused` trailer), `execution_id` token, the `pflow resume` verb.
- Shipped substrate: Task 169 SSE + #529 robustness; Task 175 `/api/run` spawn pattern +
  `_require_local_origin`.

## Verification (sketch — firm up at task start)

- Gated workflow launched from `pflow ui` → pauses; overlay shows the gate; Approve in the browser
  → run continues as a new attempt (`resumed_from` chain) and completes; Deny → clean cancellation
  surfaced in the UI.
- The approve POST is rejected without a local Host header; spawn failures surface in the panel,
  never a silent no-op.
- Failed-run Resume button: side-effecting K → confirmation dialog naming K + type, then resumes
  (spawn carries `--force`); idempotent K resumes without a dialog; a superseded source surfaces
  the newer attempt instead of resuming; refusals render as panel states, never silent.
- Real-browser verification required (CLI cannot see the UI) — same posture as Tasks 173/175.

## References

- `task-171.md` "Consumers & synergies" (the canonical bridge pattern + external-surface notes).
- `task-125.md` "Phasing → Web approval" + "Decision payload: `GateRequest`".
- ADR-0008 (observe, never host), ADR-0007 (WebSocket pre-authorized if ever needed).
- `src/pflow/ui/server.py` (`/api/run` spawn + `_require_local_origin` precedents).
