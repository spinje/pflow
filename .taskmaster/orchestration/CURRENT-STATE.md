# CURRENT-STATE.md (last verified: 2026-07-12)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Updated when the RESUME PICTURE changes. How-it-got-here: latest `sessions/session-NN.md`.
Every claim here is a pointer to verify, not a fact._

## Process

- **Orchestration restructured 2026-07-11/12** (DECISIONS #1–#11): agent-hierarchy system
  adopted (ORCHESTRATION.md canonical; planner/task-orchestrator/implementer agent defs live;
  command rewritten; close ritual + rolling braindump in the boot stack; this file + `sessions/`
  replace `orchestrator-progress-log.md`, converted to `sessions/session-01.md`). Codex routing
  metadata preservation shipped in #578; redundant planning commands were retired and the
  `create-plan` skill added in #582. Local `main` points to the orchestration-doc commit
  `342aac49`; fetched `origin/main` remains `ffaeb5a6`. Remote freshness and #565's open state
  were verified after permissions were restored on 2026-07-12.
- The hierarchy has NOT yet run a lane-A/B build — the first launch shakes it down; watch the
  worktree-workflow flags (`open_cli=false open_cursor=false`) and packet quality. Codex launch
  rule proven by #565: explicit role/model/effort requires `fork_turns: none`; a full-history fork
  inherits the parent route and is rejected when explicit routing is also supplied.

## In flight

- **#565 (MCP probe output paths)** — PARKED on Codex runtime failure. The Codex v1 replacement
  `/root/issue_565_v1` (`task-orchestrator`, `gpt-5.6-sol`, high, isolated context) reproduced
  the same immediate encrypted-function-output decode failure as the v2 agent. Per session 3's
  one-replacement limit, do not retry this shakedown unchanged. Worktree
  `/Users/andfal/projects/pflow-worktrees/fix-mcp-probe-output-paths` and branch
  `fix/mcp-probe-output-paths` remain clean at base `342aac49`; no implementation was attempted
  or lost. Resolution requires a Codex runtime/tooling change or a user-approved different
  execution route.

## Current arc

Resume/HITL: 125 ✅ → 164 ✅ → 174 ✅ → 171 ✅ → 176 ✅ (#579). Task 176's review confirms the
pre-flight no-silent-no-op invariant is mutation-tested, `PFLOW_EXECUTION_ID` already worked and
gained a pin test, and terminal-replay greying was real-browser verified. Its unfiled follow-up is
validator-only pre-trace failures after forced resume or UI launch. Read `task_171/task-review.md`
and `task_176/task-review.md` before resume/gate/trace work.

## Parallel-lane candidates (re-scanned 2026-07-12)

- **#542** trace retention — UNBLOCKED (gate was 171). Paused traces are live obligations, never
  prunable; `resume list` depends on trailer scan. Trace seam → serialize.
- **#562** resumable inline workflows — 171 follow-on; touches trace format → serialize.
- **#565** MCP probe advertises top-level `${success}` but values live under `result.*` — small,
  agent-facing correctness bug; lane B shakedown recommendation. Root cause verified locally:
  MCP registration publishes `outputSchema` fields bare while runtime's canonical success
  namespace is `result`.
- **#580** nested run-value rendering — deliberately wait for evidence that Task 176's modal
  document view is insufficient; do not build pre-emptively. **#581** flaky Windows caplog tests
  — hygiene lane; suggested global-logger cause remains unverified.
- **#546** pinned-run resolve race · **#568** track/cancel detached UI runs (respect ADR-0008) ·
  **#561** TTS clip cache (backlog) · **#538** liveness backstop (check
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
- Worktrees: `main` + `fix-mcp-probe-output-paths` (verified locally 2026-07-12).
