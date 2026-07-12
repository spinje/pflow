# CURRENT-STATE.md (last verified: 2026-07-12)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Updated when the RESUME PICTURE changes. How-it-got-here: latest `sessions/session-NN.md`.
Every claim here is a pointer to verify, not a fact._

## Process

- **Orchestration restructured 2026-07-11/12** (DECISIONS #1–#11): agent-hierarchy system
  adopted (ORCHESTRATION.md canonical; planner/task-orchestrator/implementer agent defs live;
  command rewritten; close ritual + rolling braindump in the boot stack; this file + `sessions/`
  replace `orchestrator-progress-log.md`, converted to `sessions/session-01.md`). Committed to
  `main` 2026-07-12 (docs commit). **`main` is unpushed** (this commit + `eeba1e8e` +
  `276672a4`) — pushes are user-gated.
- The hierarchy has NOT yet run a lane-A/B build — the first launch shakes it down; watch the
  worktree-workflow flags (`open_cli=false open_cursor=false`) and packet quality. **Shakedown
  candidate: #565 (lane B).**

## In flight

- **Task 176 (Web-UI Approval Bridge)** — **lane C (manual)**, launched pre-restructure
  2026-07-11 on **fable** in worktree `feat-web-ui-approval-bridge` (branch
  `feat/web-ui-approval-bridge`, base `276672a4` = the refreshed-spec commit; brief verified
  in-tree at `scratchpads/task-176-web-approval-bridge/BRIEF.md`). Spec refresh + 3-item decision
  ledger LOCKED same day (escalation-answering IN · greying IN-phased-last · `resolved_via:"ui"`
  OUT — do not re-litigate). **On merge, verify personally**: the pre-flight no-silent-no-op rule
  and the resume `PFLOW_EXECUTION_ID` mirror hook (both orchestrator catches, not spec
  inheritance); check whether the greying cut-line was exercised (→ follow-up issue); reconcile
  roadmap (176 closes the resume/HITL arc); then #546/#568 unblock (serialized behind 176).

## Current arc

Resume/HITL: 125 ✅ → 164 ✅ → 174 ✅ → 171 ✅ → **176 in flight**. Read `task_171/task-review.md`
before any resume/gate/trace work — 171's beyond-spec deltas: MCP streams traces; exit 4 = paused;
trace format 2.7.0 (`final_status:"paused"` + `gate_request` on the trailer); loader extracted to
`runtime/resume_source.py`; `ExecutionResult.is_durable_pause` is the single durability home.

## Parallel-lane candidates (re-scanned 2026-07-11)

- **#542** trace retention — UNBLOCKED (gate was 171). Paused traces are live obligations, never
  prunable; `resume list` depends on trailer scan. Trace seam → serialize.
- **#562** resumable inline workflows — 171 follow-on; touches trace format → serialize.
- **#565** MCP probe advertises top-level `${success}` but values live under `result.*` — small,
  agent-facing correctness bug; likely lane B.
- **#546** pinned-run resolve race (behind 176) · **#568** track/cancel detached UI runs (behind
  176; respect ADR-0008) · **#561** TTS clip cache (backlog) · **#538** liveness backstop (check
  overlap with #566 first) · **#544** `llm_*` canonicalization · **#549** post-#539 visibility ·
  **#528** `--output-format` stragglers · **#566/#567/#572/#574/#575** Windows/test-infra tail.
- **#357** memo-cache drift — issue state UNVERIFIED since 2026-06-23; check before acting.

## Watch list (non-obvious, easy to miss)

- **Trace-format seam is hot**: 171 (2.7.0) + #562 + #542 all touch trailer semantics —
  serialize; never fan out. Trace-touching work: run the Task-159 baseline
  (`task_159/baseline/verify.sh`) as the free outer regression net.
- Recurring conflation attractor: `is_trace_locked` (probe, `ui/run_tailer.py`) vs
  `_lock_trace_handle` (writer flock, `workflow_trace.py`) — two agents got this wrong; distrust
  docs placing the probe in `workflow_trace.py`.
- Windows is a **blocking CI gate** (`tests-windows`); ADR-0013 governs shell semantics.
- Real-browser verification requires killing stale `pflow ui` servers first (reuse-if-up probe
  serves old code).
- Spec file:line refs last bulk-refreshed 2026-07-02; repo has since absorbed #557's format pass
  + 116's 117-file diff — treat ALL file:line refs as stale; re-verify at use.
- Worktrees: only `main` + `feat-web-ui-approval-bridge` exist (full sweep 2026-07-11).
