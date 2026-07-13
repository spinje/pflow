# CURRENT-STATE.md (last verified: 2026-07-13)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Updated when the RESUME PICTURE changes. How-it-got-here: latest `sessions/session-NN.md`.
Every claim here is a pointer to verify, not a fact._

## Process

- **Orchestration restructured 2026-07-11/12** (DECISIONS #1–#11): agent-hierarchy system
  adopted (ORCHESTRATION.md canonical; planner/task-orchestrator/implementer agent defs live;
  command rewritten; close ritual + rolling braindump in the boot stack; this file + `sessions/`
  replace `orchestrator-progress-log.md`, converted to `sessions/session-01.md`). Codex routing
  now follows the user's explicit constraint: dynamic child launches inherit the runtime model
  and reasoning effort; no override parameters (DECISIONS #3).
- The hierarchy has now run three Codex lane-B builds end to end (#565/#581/#585), including
  worktrees with `open_cli=false open_cursor=false`. Local `main` is synchronized with
  `origin/main` as of this close.
  Proven: nested search/review agents, handbacks, PR/CI loops, `[skip review]`, and teardown.
- **Planner routing changed 2026-07-13** (user commit `647d86f9`): task planners now route
  **Opus**, not Fable — scope is planners only; #8 (UI phases → Fable) and #9 (lane-B Fable
  opt-in) stand. DECISIONS #3 amended; ORCHESTRATION + agent def reconciled.

## In flight

- ~~**#565 (MCP probe output paths)**~~ — MERGED via PR #583 as `bd6f520a`; all merged-result gates
  green after #581, worktree/branch safely pruned.
- ~~**#581 (flaky Windows caplog tests)**~~ — MERGED via PR #584 as `08b319ca`; issue-specific Windows
  gate passed, authorized unrelated-flake rerun passed, worktree/branch safely pruned.
- ~~**#585 (Windows MCP config replace WinError 5)**~~ — MERGED via PR #586 as `2ee5fefc`; all
  Windows gates green, worktree/branch safely pruned. Verified cause: Windows replacement can
  transiently reject despite existing process-wide `RLock`; fix narrowly retries WinError 5/32.

## Current arc

Resume/HITL: 125 ✅ → 164 ✅ → 174 ✅ → 171 ✅ → 176 ✅ (#579). Read
`task_171/task-review.md` and `task_176/task-review.md` before resume/gate/trace work.

## Parallel-lane candidates (re-scanned 2026-07-13)

- **#542** trace retention — UNBLOCKED (gate was 171). Paused traces are live obligations, never
  prunable; `resume list` depends on trailer scan. Trace seam → serialize.
- **#562** resumable inline workflows — 171 follow-on; touches trace format → serialize.
- ~~**#565**~~ shipped via #583; remove from future picks.
- **#546** pinned-run resolve race · **#568** track/cancel detached UI runs (respect ADR-0008) ·
  **#561** TTS clip cache (backlog) · **#538** liveness backstop (check
  overlap with #566 first) · **#544** `llm_*` canonicalization · **#549** post-#539 visibility ·
  **#528** `--output-format` stragglers · **#566/#567/#572/#574/#575** Windows/test-infra tail.
- **#357** memo-cache drift — issue state UNVERIFIED since 2026-06-23; check before acting.
- ~~**#581**~~ shipped via #584. ~~**#585**~~ shipped via #586.

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
- Worktrees: only `main` (verified after #565/#581/#585 teardown).
