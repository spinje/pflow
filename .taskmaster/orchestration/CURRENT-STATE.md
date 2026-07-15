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

- **PR #591** — worktree creator gained implement mode + phase scope; related open issue **#590**
  tracks `pflow describe` being unable to inspect an unsaved workflow file.
- **Task 177** → PR **#593** MERGED (`642b3957`): unified `agent` node with Claude + Codex
  backends; read `task_177/task-review.md` before agent-node/backend work. Spawned **#592**
  (parameter validators still raise vanilla `ValueError`/`TypeError`).
- **PR #595** MERGED (`81ccb547`): hardened Codex agent generation, model/effort routing, asset
  synchronization, sandbox-testing naming, and task-status validation.

## Current arc

- Resume/HITL remains closed: 125 ✅ → 164 ✅ → 174 ✅ → 171 ✅ → 176 ✅. Read
  `task_171/task-review.md` + `task_176/task-review.md` before resume/gate/trace work.
- No task or PR is in flight. **Tasks 142 and 46 are parked in Later by user ruling 2026-07-15.**
  Task 142's observed bugs are fixed and explicit dependency edges remain necessary. Task 46's
  planner/wrapper premises were removed by Tasks 92/135; modern runtime parity would duplicate
  the runtime without observed demand. Its spec carries the full stale/parked warning.
- **Approved next, not started: #590** — lane B, one Opus/high issue-mode orchestrator. Locked UX:
  preserve the typed file path in heading + copyable example; omit history silently for unsaved
  files; saved-workflow history/output and unknown-name suggestions stay unchanged; no formatter
  interface expansion. No worktree or agent exists. Apply DECISIONS #5 at the commit gate before
  provisioning; do not re-litigate the approved output unless new evidence contradicts it.
- After #590, Task 94 is the next feature to freshness/design-check; #592 is the next small cleanup.
  **Task 99 predates Task 177's `claude-code` → `agent` replacement and must be refreshed against
  the shipped backend seam before consideration.**

## Parallel-lane candidates (open issues, re-scanned 2026-07-15)

- New: **#589** bounded-memory inconsistency in text stdin · **#590** describe local workflow
  files · **#592** agent param errors should use `PflowError`. All verified, low severity, lane-B
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
- Worktrees: only `main`; no live subagents. After handover review, the user explicitly authorized
  committing the full staged session-05 reconciliation/process set and pushing it to `main`.
