# CURRENT-STATE.md (last verified: 2026-07-15)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Updated when the RESUME PICTURE changes. How-it-got-here: latest `sessions/session-NN.md`.
Every claim here is a pointer to verify, not a fact._

## Process

- **Orchestration restructured 2026-07-11/12** (DECISIONS #1–#14): agent hierarchy with
  `ORCHESTRATION.md` canonical; this file + `sessions/` are the dated state layer.
- Hierarchy proven end to end across Codex and Claude lane-B work. Task 177 shipped with the full
  task artifact set; no session record establishes which orchestration lane launched it.
- **Model routing** (DECISIONS #3, amended through PR #595): every dynamic launch passes the
  runner-specific model; Codex also passes explicit `reasoning_effort`. Root `AGENTS.md` is the
  live launch contract; full-history forks cannot override routing.
- **Merge policy** (DECISIONS #4/#14): orchestrator merges when fully ready — CI green + the
  implementing agent has acted on auto-reviewer comments.

## Recently shipped (since session-04; verified 2026-07-15)

- **PR #591** — worktree creator gained implement mode + phase scope.
- **Task 177** → PR **#593** MERGED (`642b3957`): unified `agent` node with Claude + Codex
  backends; read `task_177/task-review.md` before agent-node/backend work. Spawned **#592**
  (parameter validators still raise vanilla `ValueError`/`TypeError`).
- **PR #595** MERGED (`81ccb547`): hardened Codex agent generation, model/effort routing, asset
  synchronization, sandbox-testing naming, and task-status validation.
- **PR #596** MERGED (`4e946aab`, closes #590): `pflow describe` supports local workflow files;
  typed paths remain visible and copyable, including paths with spaces. Mandatory manual
  verification exposed and closed the shared run-routing/copyability seam; no follow-ups.

## Current arc

- Resume/HITL remains closed: 125 ✅ → 164 ✅ → 174 ✅ → 171 ✅ → 176 ✅. Read
  `task_171/task-review.md` + `task_176/task-review.md` before resume/gate/trace work.
- No task, issue, PR, or child agent is in flight. **Tasks 142 and 46 are parked in Later by user
  ruling 2026-07-15.**
  Task 142's observed bugs are fixed and explicit dependency edges remain necessary. Task 46's
  planner/wrapper premises were removed by Tasks 92/135; modern runtime parity would duplicate
  the runtime without observed demand. Its spec carries the full stale/parked warning.
- **Recommended next, not approved or started: #592** — lane B, Opus/high; it closes Task 177's
  deferred structured-error gap before Task 99 builds on the agent seam. Task 94's provider half
  already shipped and its remaining model-catalog design is stale/open; reframe before launch.
  #589 is real but a memory-threshold fix would not stop an infinite pipe without a separate hard-
  ceiling decision. **Task 99 predates Task 177's `claude-code` → `agent` replacement and must be
  refreshed against the shipped backend seam before consideration.**

## Parallel-lane candidates (open issues, re-scanned 2026-07-15)

- New: **#589** bounded-memory inconsistency in text stdin · **#592** agent param errors should
  use `PflowError`. Both verified, low severity, lane-B
  shaped; no priority claim beyond observed correctness/UX.
- **#542** trace retention · **#562** resumable inline workflows — both touch trace format;
  serialize.
- **#546** pinned-run resolve race · **#568** track/cancel detached UI runs (ADR-0008) · **#538**
  liveness backstop (check #566 overlap) · **#544** `llm_*` canonicalization · **#549** post-#539
  visibility · **#528** `--output-format` · **#561** TTS clip cache (backlog).
- **#550/#551/#552** MCP `evaluate_script` cluster · **#580** UI run-value unwrap (Fable) ·
  **#553** misleading "Workflow Not Found" · **#520/#521** validator/parser ·
  **#566/#567/#572/#574/#575** Windows/test-infra tail.

## Watch list (non-obvious, easy to miss)

- **Trace-format seam is hot**: #562 + #542 touch trailer semantics — serialize; run the Task-159
  baseline (`task_159/baseline/verify.sh`) for trace-touching work.
- Conflation attractor: `is_trace_locked` (probe, `ui/run_tailer.py`) vs `_lock_trace_handle`
  (writer flock, `workflow_trace.py`) — distrust docs that place the probe in `workflow_trace.py`.
- Windows is a **blocking CI gate** (`tests-windows`); ADR-0013 governs shell semantics.
- Real-browser verification requires killing stale `pflow ui` servers first.
- Treat old spec file:line references as stale: Task 177 moved 133 files after the last bulk
  refresh.
- Worktrees: only `main`; no live subagents. `main == origin/main == 4e946aab`; session-05
  orchestration state/reconciliation edits are intentionally uncommitted.
