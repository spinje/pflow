# Task 176: Web-UI Approval Bridge — approve/deny paused gates from the browser

## Description

Close the approval loop in the browser: 125 shipped the gate primitive, 171 shipped durable
pause/resume — so a gated run launched from `pflow ui` pauses durably and the UI *shows* it
(amber banner, ⏸ selector mark), but offers no way to *act* on it. This task adds the gate panel
(Approve/Deny for approvals, option-choose for escalations) that spawns
`pflow resume <execution-id> --approve yes|no` / `--choose "<answer>"` — the same
ADR-0008-conformant observe-and-spawn pattern as the shipped `POST /api/run`. It also owns the
**Resume button on failed/interrupted runs**, the **⏸ frontier-node badge**, and the **un-run
region greying** on pinned terminal replays.

> **Refreshed 2026-07-11 against main (post-171 `e55f0d30`, post-116 `646fdae7`)** — three
> parallel code audits + personal spot-checks; every claim below is verified against current code
> unless marked otherwise. Line numbers are a snapshot; file + symbol are the load-bearing
> identifiers. The 2026-07-02 draft's mechanisms were assumptions; the load-bearing ones that
> proved FALSE are called out inline. **Read `task_171/task-review.md` before touching anything
> resume/gate/trace.**

## Status

done

## Completed

2026-07-12

> All phases (0–5) implemented on `feat/web-ui-approval-bridge`, deep-reviewed and
> browser-verified. See `implementation/progress-log.md` + `task-review.md`.

## Decision ledger

1. **Escalation answering in the browser — DECIDED IN (owner, 2026-07-11).** The gate panel is
   kind-switched: `action_approval` → Approve/Deny; `decision_escalation` → options + free-text
   answer delivered via `pflow resume <id> --choose`. Rationale: the agent-operated run is the
   scenario this bridge exists for, and escalations are its centerpiece; `--choose` works fully
   non-TTY and the payload is self-contained by contract.
2. **Un-run greying (canvas replay truth) — DECIDED IN (owner, 2026-07-11)**, phased LAST with an
   explicit cut-line: if it drags, it ships as a follow-up issue — it is presentation-only and
   touches nothing the other deliverables need.
3. **`resolved_via: "ui"` — DECIDED OUT for v1 (owner, 2026-07-11).** The bridge's answers record
   `"flag"` — truthful (the answer IS delivered via `pflow resume --approve`, which primes the
   flag mechanism). Plain-language rationale the decision was approved on: a `"ui"` marker would
   be **self-reported and spoofable** (an agent can pass the same hidden flag/env), **nothing
   consumes the label today** (no report or UI filters on `resolved_via`), and it needs a
   three-layer plumbing channel whose only job is carrying one word into a log line — it fails
   the deletion test. Provenance already exists in a stronger, structural form: the answering
   resume creates a separate attempt trace linked by `resumed_from`. Reversible: adding `"ui"`
   later is additive; wait for the first real consumer (an actual audit view) and then decide
   whether self-reported provenance is even the right mechanism. Do NOT re-derive this in-task.
4. **One `POST /api/resume` — DECIDED (owner, 2026-07-11, plan session).** A single endpoint
   mirroring the CLI verb — body `{run, approve?, choose?, force?}` — instead of this spec's
   sketch of a separate `POST /api/approve` + resume trigger. One pre-flight, one spawn path;
   the CLI's own flag-exclusivity rules map 1:1. ADR-0009's "`POST /api/approve`" example
   carries an amendment note. Contract details: `implementation/implementation-plan.md` §P2-3.
5. **Gate panel = NodeCallout anchored at the ⏸ node — DECIDED (owner, 2026-07-11, plan
   session).** The kind-switched controls live in a `NodeCallout` at the paused frontier node
   (auto-shown, dismissible, reopened by clicking the ⏸ node — two entry points, deliberately
   no third); the failed-run Resume button is a separate `ResumeControl` under `RunProgress` in
   the existing run callout. Chosen over a RunPanel-style side panel for reuse and to stay out
   of the right-panel budget.

## Corrections from the 2026-07-11 plan session (verified against worktree `276672a4`)

> The implementation plan (`implementation/implementation-plan.md`, deep-reviewed 2026-07-11)
> supersedes this spec where they disagree. Three claims below were verified FALSE or stale;
> the affected sections carry inline `[CORRECTED]` markers.

1. **`PFLOW_EXECUTION_ID` already works for `resume` — no CLI change.** This spec claimed
   "resume ignores it today". Verified false: `_dispatch_resume` (resume.py:420) dispatches
   through the shared `execute_json_workflow`, whose `RunnerConfig` pops the env var
   (run.py:301), and `runner.py:193` threads `config.execution_id` into the collector on every
   path. Deliverable is a **pin test only** (plan §P2-T4).
2. **ADR-0013 does not govern the spawn helper** — it is scoped to the shell *node's* POSIX-sh
   dialect. The Windows contract for new subprocess code is the existing `/api/run` detach
   branch (server.py:1098-1101) + the blocking `tests-windows` CI job.
3. **Actual non-UI code touched** (replacing "the one CLI change" scope sentence): a
   behavior-preserving extraction of the four click-free refusal gates from `resume.py` into
   `execution/resume_preflight.py` (the 171 "extract the rule when the second consumer appears"
   pattern — the server pre-flight is that second consumer), one line in `core/exceptions.py`
   (`ResumeStaleWorkflowError` gains `self.hash_known`), and a compile step in the server's
   pre-flight wrapper (mirroring `/api/run`'s, closing the pre-trace-failure vanish on
   force-resume of an edited-broken workflow). None are engine or trace-format changes — the
   escalate clause is not triggered.

## Priority

medium (next on the critical path; the resume/HITL arc's closing piece)

## Problem

Browser-launched runs are non-TTY by construction — `POST /api/run` spawns with
`stdin=subprocess.DEVNULL` (`src/pflow/ui/server.py:1102-1109`; the draft's `:853-858` ref
drifted). So a gated workflow launched from `pflow ui` pauses durably (171), the UI shows the
paused fact — and the user must leave the browser for a terminal to answer. Hit on day one of
gates, on the product's own primary demo surface.

## What already shipped vs. what this task builds (verified 2026-07-11)

**Already shipped by 171 Phase 4 — do NOT rebuild:** the run-level paused surfaces. `RunProgress`
paused arm (amber "Run paused" banner, `RunProgress.tsx:24-41`), `RunSelector` ⏸ mark +
`⤷ resumed from` jump-link chain marker (`RunSelector.tsx:33-35, 136-165`),
`RunInfo.resumed_from` (`types.ts:96-98`, emitted at `server.py:1197`). All unit-tested.

**Genuinely new (the four deliverables):**
1. The gate panel — render the `GateRequest` payload, kind-switched controls (ledger #1).
2. Resume button on failed/interrupted runs.
3. ⏸ badge on the paused frontier node.
4. Un-run region greying on pinned terminal replays (ledger #2 — phased last, cut-line).

## The wire gap (the draft's biggest false assumption)

The draft said "the tailer forwards trailer keys generically — no producer change expected."
**FALSE.** Both server read paths are *deliberate* allowlists, built to keep bulky payloads off
the SSE wire (their own comments say so — PR #543 review):

- SSE / live overlay: `_RUN_COMPLETE_FIELDS` (`ui/run_tailer.py:611-618`) — no `paused_node_id`,
  no `gate_request`.
- `GET /api/runs`: `_run_entry` (`ui/server.py:1178-1198`) — same; and its cheap tail reader
  `read_run_status` extracts only `final_status` from the trailer.

Zero code in `ui/` or `web/` reads `paused_node_id`/`gate_request` today (grep-verified). So the
bridge has a real server-side half. **Recommended wire shape (plan-level, orchestrator-owned):**
put `paused_node_id` (a small string) on the light wires (`_RUN_COMPLETE_FIELDS` + `_run_entry`,
extending the tail parser to extract it), and fetch the full `gate_request` (can exceed 64KB)
**on demand** when the panel opens — a dedicated read endpoint, or server-side reuse of the
trailer read. Do not spread the payload onto the SSE wire; the allowlist exists precisely to
prevent that. Apply `masked_gate_dict` (`core/gate.py:141-152`) before serving the payload to the
browser — masking is display-surface policy, and the browser is a display surface.

Layering is already sanctioned: `ui/ → runtime/` imports are legal (the rule is one-way,
`runtime/ ↛ ui/`; precedent `server.py:1023` imports `compile_workflow`), so the server may use
`runtime/resume_source.py` (`list_paused_runs`, `PausedRun`) directly.

## Solution (the pattern — canonical statement in task-171.md "Consumers & synergies")

Any approval surface = **read the gate → render `GateRequest` → deliver the answer via
`pflow resume`**. For the web UI:

1. Panel/callout renders the (masked) `GateRequest`, kind-switched (ledger #1). Natural homes,
   both shipped and content-agnostic: `NodeCallout` (flow-space box anchored at the paused node —
   already hosts `RunProgress` and the say bubbles) and/or a boolean-gated panel like `RunPanel`
   (deliberately *outside* the `selectedId` three-panel selection model — copy that precedent to
   avoid racing it).
2. `POST /api/approve` (and the resume trigger) `[ledger #4: shipped as ONE POST /api/resume]`
   → server spawns `pflow resume ...` detached.
   Second sanctioned spawn, structurally identical to `/api/run`. **Extract the spawn helper** —
   `/api/run`'s spawn is inline (`server.py:1102-1109`) and this task makes three consumers
   (run / approve / resume): a real seam by the project's own rule. The helper MUST carry the
   win32 detach branch Task 116 added (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` vs
   `start_new_session=True`).
3. Origin guarding is **automatic**: the draft's `_require_local_origin` never existed — the real
   guard is the global `_LoopbackOnly` ASGI middleware (`server.py:542-567`, installed at
   `:1364`), which covers every new route with no per-handler call.

**Two hard rules from the step-back audit (both verified gaps, not theory):**

- **No silent no-ops.** The `/api/run` spawn is fire-and-forget with all streams DEVNULL — a
  *refused* resume (superseded, stale, still-running, answer-required…) would exit 1 invisibly.
  Mirror `/api/run`'s pre-flight pattern: validate **in-process** (via `load_resume_source` /
  the refusal family) and return 4xx with diagnostics BEFORE spawning; only a validated answer
  spawns. (Task-175 rule: "spawn failures surface, never a silent no-op.")
- **Pin the resumed attempt.** `[CORRECTED 2026-07-11 — see Corrections #1]` The env hook
  already exists on the resume path: `_dispatch_resume` flows through the shared
  `execute_json_workflow`, which pops `PFLOW_EXECUTION_ID` into `RunnerConfig.execution_id`
  (`cli/commands/run.py:301`). The server mints the new attempt's id and the browser pins it
  immediately, exactly like `/api/run` launches. The only deliverable is a regression pin test
  (nothing guards this today and the bridge depends on it).

## The resume surface, as a machine caller sees it (verified 2026-07-11)

- `pflow resume` and `pflow resume list` both support `--output-format json` — refusals included
  (`output_error` → `format_error_json`), and a JSON-mode `ResumeAnswerRequiredError` carries the
  masked gate payload in `context["gate"]`. `resume list --output-format json` emits
  `execution_id`, `workflow_name`, `paused_node_id`, `gate_kind`, `paused_at`, `resume_command`.
- Exit codes: 0 success · 1 refusal OR resumed-run failure · 2 usage · 3 denied (`--approve no`
  re-fires the gate deny-primed — a real denied attempt trace that consumes the token) · 4 the
  resumed tail paused again · 130 interrupt. **Trap: exit 1 conflates refusal with downstream
  failure** — the bridge distinguishes via JSON diagnostics, never via exit code alone.
- A paused-gate answer **never** hits the side-effect confirmation — paused sources skip it
  (`resume.py:575-582`; the answer flag is itself consent). The side-effect dialog matters only
  for the failed-run Resume button (below).
- `--auto-approve`/`--approve` resolve APPROVAL gates only (kind-checked,
  `gate_prompt.py:77-85`); escalations need `--choose`, which is validated + folded at LOAD time
  (the escalating step is never re-run, so no fresh gate-resolution line appears — don't build UI
  that waits for one). `--approve` and `--choose` are mutually exclusive.
- Answer refusals a paused run can hit (map each to a panel state): `ResumeAnswerRequiredError`
  (missing/wrong flag), `ResumeStaleWorkflowError`, `ResumeSupersededError` (offer the newer
  attempt), `ResumeStillRunningError`, `ResumeFidelityError`.

## Resume button on failed/interrupted runs

Same spawn helper, different entry arm. Verified design facts:

- Bare `pflow resume` on a failed run with a side-effecting entry K hard-errors non-TTY with
  `ResumeSideEffectConfirmationError` naming **K's id + registry type** (`exceptions.py:1332`),
  so the browser confirmation dialog is buildable from the pre-flight refusal alone: render K +
  type + "its side effects may fire again", then spawn with `--force` only after explicit ack.
  Never pass `--force` without the dialog. Same ack pattern for `ResumeStaleWorkflowError`
  ("edited since the original run").
- Idempotent K (`llm`) resumes with no dialog — mirror the CLI's silent path.
- Refusals are the UX: superseded → offer the newer attempt; nothing-to-resume; still-running;
  gate-stopped — panel states, never silence.
- Whether the failed-run button and the paused-gate controls share one panel is a build-time
  call — the spawn helper and pre-flight are shared either way.

## Canvas truth: ⏸ frontier badge + un-run greying

1. **⏸ badge** — a CLIENT-synthesized per-node status derived from `paused_node_id` (once it's on
   the wire), NOT a new trace event status. The pipeline already synthesizes exactly this way
   twice (`unrecorded` via `applyStatus`/`markUnmatched`, `stopped` on flock-death —
   `graph/focus.ts:33-72`); follow that pattern: add `paused` to the `NodeStatus` union
   (`types.ts:30`), a `GLYPH` + label + CSS arm in `StatusBadge.tsx`, light the node matching
   `paused_node_id`. `events.ts` `RUN_STATUSES` (the per-node EVENT allowlist, `events.ts:64`)
   stays untouched — the 171-plan rule, still binding. Clicking the ⏸ node is the natural entry
   to the gate panel.
2. **Greying** — a third restyle pass beside `applyFocus`/`applyStatus` (`graph/focus.ts`): pure
   style-pass over the laid-out React Flow snapshot, NO re-layout. Pinned terminal replays ONLY,
   never live runs (owner scoping 2026-07-05 — a live shrinking grey region duplicates the badge
   animation and would flicker). Care points: CSS-order composition with `.node.dimmed` /
   `.node.hover-mark` (equal specificity, order decides — `index.css:952` comment) and both
   densities. Phased last, cut-line per ledger #2.

## The agent-operated run (unchanged framing, one correction)

The scenario this bridge serves: the run's operator is an AI agent, the gate's approver is the
human behind it. The gate is not a security boundary against the operating agent — the design
provides deliberate + visible + auditable bypass, and this task's UI is the convenient human
path (the agent relays the link; the human clicks in a surface the agent isn't driving).
**Correction to the draft:** the audit story rests on attempt-chain lineage (`resumed_from`) and
the gate-resolution lines' existing `prompt|flag` vocabulary — NOT on a `resolved_via: "ui"`
value (ledger #3, OUT).

## Explicitly out of scope

- **Slack / email / webhook / any external surface** (observed-problems rule). The generalized
  pattern + constraints for the first external bridge live in `task-171.md` "Consumers &
  synergies" (`on_pause` hook is additive-later; bridges own their authn).
- Engine or trace-format changes. The wire work is UI-server projection only (allowlists +
  endpoint). `[CORRECTED 2026-07-11 — see Corrections #1/#3]` The "one CLI change" is gone (the
  env hook already works — pin test only); the non-UI touches are the `resume_preflight`
  extraction, one `exceptions.py` line, and the server-side compile — none engine/trace-format.
  If the bridge needs more than that, the 125/171 contracts failed — escalate rather than patch
  around.
- Process cancel / PID tracking (#568's scope). Note: a durably paused run has NO live process
  (it exited 4) — deny is a trace operation, not a kill.

## Windows / platform notes (post-116, all verified)

- A paused run writes a terminal `run.complete` trailer → `complete=True` → the liveness probe
  short-circuits before the lock check. **The bridge is immune to the Windows "unknown lock =
  live" weakness (#566).** Favorable and load-bearing — don't re-open it.
- The spawn helper carries the win32 detach branch (above). Windows CI (`tests-windows`) is a
  blocking gate — any new subprocess/encoding/path code must clear it.
  `[CORRECTED 2026-07-11 — see Corrections #2]` ADR-0013 does NOT govern this (it is the shell
  node's dialect contract); the binding precedent is the `/api/run` detach branch itself.

## Collisions & sequencing (verified 2026-07-11)

- **#546** (pinned-run resolve race) and **#568** (detached-run lifecycle) live on exactly this
  task's surfaces (`RunTailer._resolve_pinned`, the `/api/run` spawn) — **serialized behind 176**,
  never parallel. The resumed-attempt pin inherits #546's cold-start race; tolerate, don't fix
  here.
- **#542** (trace retention): no file collision, one semantic rule recorded both places —
  retention must treat `paused` traces as un-prunable live obligations, and must not be
  *implemented* while 176's trailer-reading surface is in flight.
- **#562** (inline resumable) touches `resume_source.py` + engine conjuncts and flips the
  `TestInlinePausePromise` pins — keep serialized with any trace-format work; mostly disjoint
  from 176 but do not run both against `resume_source.py` concurrently.

## Verification

- Gated workflow launched from `pflow ui` → pauses; ⏸ badge on the frontier node; panel renders
  the masked payload; Approve → new attempt pinned immediately (`resumed_from` chain) and
  completes; Deny → denied attempt surfaced (exit 3 is success-shaped for "user said no").
- Escalation-paused run → options render; choose (numeric and free text) → run continues from
  the decision.
- Every refusal (superseded / stale / still-running / answer-required) surfaces as a panel state
  with diagnostics — spawn only after in-process pre-flight passes; prove the no-silent-no-op
  rule with a deliberate refusal.
- Failed-run Resume: side-effecting K → dialog naming K + type → `--force` spawn; idempotent K →
  no dialog; superseded → offers the newer attempt.
- Approve POST rejected for non-loopback Host (middleware — verify, don't re-implement).
- Greying: pinned terminal replay dims un-run nodes/edges; composes with focus-dim + hover marks
  in both densities; never active on a live run.
- **Real-browser verification required** (CLI cannot see the UI — Tasks 173/175 posture; use
  `screenshot-pflow-web-ui`; kill any stale `pflow ui` server first — the reuse-if-up probe
  serves old code, a recorded 171 gotcha).
- Regression nets: the 171 test battery (`test_resume_source.py`, `test_gate_pause.py`,
  `test_paused_cli.py`, `test_resume_list_cli.py`), vitest, and the Task-159 baseline
  (`task_159/baseline/verify.sh`) if anything trace-adjacent moves.

## Dependencies (all shipped)

- **Task 125** — gate primitive, `GateRequest`, ADR-0009 (payload is the seam).
- **Task 164** — resume machinery. Read `task_164/task-review.md` for the refusal family +
  side-effect policy.
- **Task 171** — durable pause. **Read `task_171/task-review.md` FIRST** — invariants
  (pause-is-a-promise, one consumption policy, `is_durable_pause`), gotchas (trailer keys ride
  generic round-trip, NOT `META_KEYS`; oversized trailers), and the answer-delivery patterns.
- Shipped substrate: Task 169 SSE + #529; Task 175 `/api/run` spawn + pre-flight +
  typed-client error surfacing (`web/src/api/client.ts:126-140` `runWorkflow` → `ApiError` →
  inline diagnostics — copy this pattern verbatim for approve/resume).

## References

- `task-171.md` "Consumers & synergies" (canonical bridge pattern); `task_171/task-review.md`.
- ADR-0008 (observe, never host — incl. the "MCP runs stream too" 171 update), ADR-0009
  (approval-surface bridges), ADR-0013 (Windows shell contract).
- Key files: `ui/server.py` (spawn `:1102`, `_LoopbackOnly` `:542`, `_run_entry` `:1178`),
  `ui/run_tailer.py` (`_RUN_COMPLETE_FIELDS` `:611`, `read_run_status` `:107`),
  `runtime/resume_source.py` (`list_paused_runs`, refusal raises), `cli/commands/resume.py`,
  `core/gate.py` (`masked_gate_dict`, `option_labels`), `web/src/api/{client,events}.ts`,
  `web/src/components/{NodeCallout,RunPanel,nodes/StatusBadge}.tsx`, `web/src/graph/focus.ts`,
  `web/src/types.ts`.
