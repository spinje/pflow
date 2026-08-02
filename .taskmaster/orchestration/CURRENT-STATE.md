# CURRENT-STATE.md (last verified: 2026-07-15 — main @ 573718cb, session-06)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Updated when the RESUME PICTURE changes. How-it-got-here: latest `sessions/session-NN.md`.
Every claim here is a pointer to verify, not a fact._

## Process

- **Orchestration restructured 2026-07-11/12** (DECISIONS #1–#14): agent hierarchy with
  `ORCHESTRATION.md` canonical; this file + `sessions/` are the dated state layer.
- **ROUTING OVERRIDE (2026-07-15, user ruling, DECISIONS #3 amendment): Fable AND Sonnet are
  banned for all subagents — Opus everywhere, every launch (UI phases included), until lifted.**
- Hierarchy proven end to end across Codex and Claude lane-B work. Task 177 shipped with the full
  task artifact set; no session record establishes which orchestration lane launched it.
- **Model routing** (DECISIONS #3, amended through PR #595): every dynamic launch passes the
  runner-specific model; Codex also passes explicit `reasoning_effort`. Root `AGENTS.md` is the
  live launch contract; full-history forks cannot override routing.
- **Merge policy** (DECISIONS #4/#14): orchestrator merges when fully ready — CI green + the
  implementing agent has acted on auto-reviewer comments.

## Recently shipped (since session-04; verified 2026-07-15)

- **PR #597** MERGED (`573718cb`, closes **#592**): agent-node param validators now raise
  `AgentValidationError(PflowError)` (new `src/pflow/nodes/agent/exceptions.py`) instead of vanilla
  `ValueError`/`TypeError`; static-validator catch narrowed to it (validate==run preserved).
  Codex-P1 caught + fixed: kept `retriable=True` so a bad param in an `error_handling: continue`
  batch stays a per-item error, not a whole-batch abort (mutation-verified regression tests).
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
- **Between sessions (2026-08-02, no session record):** filed **#602** (pip on 3.14 silently
  installs pflow-cli 0.12.0 — `litellm==1.86.1` caps `Requires-Python <3.14`; blocked on upstream
  macOS wheels, BerriAI/litellm#31261) and **#603** (CI never real-`pip install`s the wheel).
  #603's `pip-install-smoke` job (3.10/3.13) is written + verified; in review (PR linked from #603).
- **Task 94 spec REWRITTEN + design LOCKED (session-06); not yet started.** Original spec was
  substantially stale (targeted the removed `registry describe` surface; false "no detection"
  premise; obsolete `llm`-library). Refreshed `task_94/task-94.md` in place with provenance. Locked
  v1 design: a new **`pflow settings llm models [KEYWORDS…] [--output-format]`** command (sibling to
  `settings llm providers`) — enumerates chat-mode models per provider from LiteLLM, key-conditioned,
  **network-first with offline-bundled fallback (source labeled)**, self-guiding output (multi-
  provider caps → single-provider full list), no curation, no `--all`/`--filter`; plus a network-
  free node-describe hint. Design decisions + the PR-#424 `register_model(dict)` landmine are IN the
  spec. Ready for lane A (single task-orchestrator, plan-and-implement, Opus). Task 99 still predates
  Task 177's `claude-code`→`agent` replacement; refresh before consideration.
- **#589** (unbounded text-stdin read) real but a memory-threshold fix alone won't stop an infinite
  pipe without a separate hard-ceiling decision.
- **CI hygiene noticed (not filed):** Windows CI installs GNU Make via `choco install make` from
  the Chocolatey community feed (`main.yml:160-162`) with no retry/cache — a transient feed `499`
  blocked #597's Windows gate (recovered on its own). Top-10% fix (per user discussion) is removing
  the feed from the critical path (have Windows CI call the `uv run` commands directly), NOT a
  retry band-aid — gated on confirming the flake is recurrent, not a one-off.

## Parallel-lane candidates (open issues, re-scanned 2026-07-15)

- **#589** bounded-memory inconsistency in text stdin — verified, low severity, lane-B shaped; no
  priority claim beyond observed correctness/UX. (#592 SHIPPED — see Recently shipped.)
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
- Worktrees: only `main`; no live subagents. `main == origin/main` at the session-06 close commit
  (Task 94 spec + DECISIONS #3 Fable/Sonnet-ban amendment + this file + BRAINDUMP + session-06.md);
  code tip is `573718cb` (#597/#592). Session-06 CLOSED — user-authorized commit+push. Nothing
  uncommitted; one branch in review since (see Current arc, between-sessions bullet).
