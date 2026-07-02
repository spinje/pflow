# Task 176: Web-UI Approval Bridge — approve/deny paused gates from the browser

## Description

Close the approval loop in the browser: once Task 125 ships the gate primitive and Task 171 ships
durable pause/resume, the live overlay will *show* a paused gate (the `gate` trace event) but offer
no way to *act* on it — this task adds approve/deny controls that spawn `pflow resume
<execution-id> --approve yes|no`, the same ADR-0008-conformant observe-and-spawn pattern as the
shipped `POST /api/run`.

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
- **Task 171** — durable pause (`paused` trailer), `execution_id` token, the `pflow resume` verb.
- Shipped substrate: Task 169 SSE + #529 robustness; Task 175 `/api/run` spawn pattern +
  `_require_local_origin`.

## Verification (sketch — firm up at task start)

- Gated workflow launched from `pflow ui` → pauses; overlay shows the gate; Approve in the browser
  → run continues as a new attempt (`resumed_from` chain) and completes; Deny → clean cancellation
  surfaced in the UI.
- The approve POST is rejected without a local Host header; spawn failures surface in the panel,
  never a silent no-op.
- Real-browser verification required (CLI cannot see the UI) — same posture as Tasks 173/175.

## References

- `task-171.md` "Consumers & synergies" (the canonical bridge pattern + external-surface notes).
- `task-125.md` "Phasing → Web approval" + "Decision payload: `GateRequest`".
- ADR-0008 (observe, never host), ADR-0007 (WebSocket pre-authorized if ever needed).
- `src/pflow/ui/server.py` (`/api/run` spawn + `_require_local_origin` precedents).
