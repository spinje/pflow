# CURRENT-STATE.md (last verified: 2026-07-13)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Updated when the RESUME PICTURE changes. How-it-got-here: latest `sessions/session-NN.md`.
Every claim here is a pointer to verify, not a fact._

## Process

- **Orchestration restructured 2026-07-11/12** (DECISIONS #1–#11): agent-hierarchy system
  (ORCHESTRATION.md canonical; planner/task-orchestrator/implementer agent defs; close ritual +
  rolling `BRAINDUMP.md` in the boot stack; this file + `sessions/` replace the old single log).
- Hierarchy proven end to end: Codex lane-B (#565/#581/#585) + session-04's Claude lane-B
  (#413/#497). Nested searchers, handbacks, PR/CI loops, `[skip review]`, squash-merge, teardown.
- **Planner routing = Opus** (user `647d86f9`, DECISIONS #3 amended): planners only; #8 (UI→Fable)
  and #9 (lane-B Fable opt-in) stand.
- **Merge policy** (DECISIONS #4/#14): orchestrator merges when fully ready — CI green + the
  implementing agent has acted on auto-reviewer (claude-review/Codex) PR comments.

## Recently shipped (session-04, 2026-07-13)

Three issues picked from an open-issue scan; two shipped, one closed after investigation.

- ~~**#413**~~ (LiteLLM in-place mutation → trace corruption) → PR **#587** MERGED (`dcf757bf`).
- ~~**#497**~~ (sidecar breaks MCP-node fenced params) → PR **#588** MERGED (`c161c5ee`); also
  carried a fix for the stale `.agents/start-orchestration` mirror (now on main).
- ~~**#183**~~ (secrets in error output) → **CLOSED not-planned** — verified not a present-day leak.
  Full rationale + the correct future fix (declared-secret primitive + exact-known-secret masking)
  live in the **#183 close comment** and `core/CLAUDE.md` (`security_utils` note); **#516 re-scoped**
  to keychain-backend. No code change beyond two invariant/rationale doc notes (`runner.py`,
  `core/CLAUDE.md`).

## Current arc

Resume/HITL is closed: 125 ✅ → 164 ✅ → 174 ✅ → 171 ✅ → 176 ✅ (#579). Read
`task_171/task-review.md` + `task_176/task-review.md` before any resume/gate/trace work. No task
currently in flight — next pick is open (roadmap v0.14.0: Task 142 next, then 46/94/99/111/118/121).

## Parallel-lane candidates (open issues, re-scanned 2026-07-13)

- **#542** trace retention (paused traces are never prunable; `resume list` scans trailers) ·
  **#562** resumable inline workflows — both touch trace format → serialize.
- **#546** pinned-run resolve race · **#568** track/cancel detached UI runs (ADR-0008) · **#538**
  liveness backstop (check #566 overlap) · **#544** `llm_*` canonicalization · **#549** post-#539
  visibility · **#528** `--output-format` · **#561** TTS clip cache (backlog) ·
  **#566/#567/#572/#574/#575** Windows/test-infra tail.
- **#550/#551/#552** MCP `evaluate_script` cluster (JS UX; #550 = injection bug) · **#580** UI
  run-value unwrap (Fable) · **#553** misleading "Workflow Not Found" · **#520/#521** validator/parser.
- ~~#357~~ closed · ~~#565/#581/#585~~ shipped · ~~#413/#497~~ shipped · ~~#183~~ closed.

## Watch list (non-obvious, easy to miss)

- **Trace-format seam is hot**: #562 + #542 touch trailer semantics — serialize, never fan out.
  Trace-touching work: run the Task-159 baseline (`task_159/baseline/verify.sh`) as the free net.
- Conflation attractor: `is_trace_locked` (probe, `ui/run_tailer.py`) vs `_lock_trace_handle`
  (writer flock, `workflow_trace.py`) — two agents got this wrong; distrust docs placing the probe
  in `workflow_trace.py`.
- Windows is a **blocking CI gate** (`tests-windows`); ADR-0013 governs shell semantics.
- Real-browser verification requires killing stale `pflow ui` servers first (reuse-if-up serves old code).
- ALL spec file:line refs are stale (repo absorbed #557 + 116's diff + session-04 merges) — re-verify at use.
- **Local main was behind origin** (branches cut from an unpushed local commit); reconciled to
  `origin/main` = `c161c5ee` after the session-04 merges. Worktrees: only `main`.
