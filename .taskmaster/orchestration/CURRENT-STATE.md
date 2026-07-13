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

## In flight (launched 2026-07-13, session-04 — 3 parallel lane-B Opus builds)

Surfaces verified against main by 3 searchers before launch; collision matrix confirmed disjoint
(files + semantics); none touch `runtime/engine/`/`workflow_executor` or trace format.

- **#413** LiteLLM mutates pflow's `system_blocks` in place → trace lies for OpenAI/Gemini cache
  runs. Fix = deep-copy at the one adapter boundary (`core/llm_client.py:358`, before
  `litellm.completion`); Option A (issue's Option C sidecar-refactor rejected as over-eng).
- **#497** `_*_source_line` sidecar leaks through MCP node's forward filter → `Unknown argument`.
  Fix = one line at `nodes/mcp/node.py:153` (`and not k.endswith("_source_line")`, matching the
  `instrumentation.py:166` precedent). No shared helper (one forwarding node → deletion test).
- **#183** secrets embedded in shell `command`/`stdout`/`stderr` leak to CLI **and** MCP error
  output. Single shared seam = `_enrich_error_from_node_output` (`executor_service.py:354-359`);
  covers both. TRAP: `sanitize_parameters` redacts by KEY — a secret inside a string value needs
  **value-level** substring redaction of known-secret values (env/sensitive param values). Scope
  = shell fields only (HTTP already redacted; consolidation is a separate follow-up).
  **Launched PLAN-FIRST** (user directive): investigate secret-value provenance + plumbing, write
  approach + failure scenarios, self-review the seam before coding; escalate if redaction must
  reach beyond the enrichment seam.

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
- ~~**#357**~~ memo-cache drift — verified CLOSED 2026-06-18; remove from picks.
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
