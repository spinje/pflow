# CURRENT-STATE.md (last verified: 2026-08-14 — main @ 15a36a0f, session-07)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Rewritten at close/park (DECISIONS #16). How-it-got-here: latest `sessions/session-NN.md`.
Every claim here is a pointer to verify, not a fact._

## Process

- **Cross-repo fold landed 2026-08-14 (DECISIONS #15–#20, session-07): the process contract
  moved substantially** — read ORCHESTRATION.md fresh, don't trust memory of the pre-fold text.
  Headlines: state-doc cadence (#16, this file rewritten at close/park); completion gate is one
  job owned by the gate-runner, dispatched via the pflow fan-out (#17); effort routing (#18);
  lane B runs on `lane-implementer`, task-orchestrator issue mode retired (#20);
  `review-falsifier` execution lens exists (direct launch only).
- **ROUTING OVERRIDE (2026-07-15, user ruling, DECISIONS #3): Fable AND Sonnet banned for all
  subagents — Opus everywhere, every launch, until lifted.**
- Model/effort on every launch: runner-specific `model` + explicit `effort` (Codex:
  `reasoning_effort`). Root `AGENTS.md` is the live launch contract.
- **Merge policy** (DECISIONS #4/#14): orchestrator merges when fully ready — CI green + the
  implementing agent has acted on auto-reviewer comments. Lane implementers merge their own PRs.
- New instruments, both shaken down live 2026-08-14: `workflows/review/run-review-lenses.pflow.md`
  (codex fan-out, FOREGROUND) · `workflows/search/run-searcher.pflow.md` (codex searcher offload).
  Known cosmetic gap: no pricing data for `gpt-5.6-sol` → fan-out runs print "cost unavailable".

## In flight / uncommitted

- **The ENTIRE fold is uncommitted** (37 files: orchestration docs, agent defs, skills,
  `workflows/`, ADR-FORMAT, one release-note scrub) — awaiting the user's commit ruling
  (DECISIONS #5). Nothing else is in flight; no worktrees, no live subagents.
- Session-07 close ritual (retrospect + braindump refresh) still owed when the user ends the
  session.

## Recently shipped / filed (verified 2026-08-14)

- **#608 + #609 filed** (executed-verified falsifier findings on the #592 fix: templated-inf
  OverflowError catch tuples; codex exec-path AgentValidationError swallow+retry). Both
  lane-B-shaped; either is a natural FIRST live launch for the new `lane-implementer`. #609's
  fix shape is a claim — the lane verifies the exec-path error inventory first.
- Correcting comment posted on PR #597 (body claims `retriable=False`; shipped code is
  `retriable=True` — execution confirms the code).
- Pre-fold state: PR #597 MERGED `573718cb` (closes #592) · Task 177 → PR #593 · PR #595 · PR
  #596 · #603's pip-install-smoke shipped (see `git log`); v0.15.1 released (`15a36a0f`).

## Current arc

- **Task 94 spec REWRITTEN + design LOCKED (session-06); not yet started.** Ready for lane A
  (single Opus task-orchestrator, plan-and-implement). Design decisions + the PR-#424
  `register_model(dict)` landmine are IN the spec. Task 99 predates Task 177's agent-node
  replacement; refresh before consideration.
- Resume/HITL arc remains closed (125→164→174→171→176 ✅). Read `task_171` + `task_176`
  task-reviews before resume/gate/trace work.
- Tasks 142 and 46 parked in Later by user ruling 2026-07-15.
- **CI hygiene noticed (not filed):** Windows CI installs GNU Make via Chocolatey with no
  retry/cache (`main.yml:160-162`); top-10% fix is removing the feed from the critical path —
  gated on confirming the flake recurs.

## Parallel-lane candidates (open issues; re-scan at pick)

- **#608 · #609** (above, fresh) · **#589** bounded-memory text stdin (needs a hard-ceiling
  decision) · **#542** trace retention · **#562** resumable inline workflows (both trace-format —
  serialize, lane-A excluded) · **#546** pinned-run resolve race · **#568** detached UI runs ·
  **#538** liveness backstop (check #566 overlap) · **#544** `llm_*` canonicalization · **#549**
  post-#539 visibility · **#528** `--output-format` · **#550/#551/#552** MCP `evaluate_script`
  cluster · **#580** UI run-value unwrap (Fable — banned; hold) · **#553** misleading "Workflow
  Not Found" · **#520/#521** validator/parser · **#566/#567/#572/#574/#575** Windows/test-infra
  tail · **#602** (blocked upstream: litellm 3.14 wheels).

## Watch list (non-obvious, easy to miss)

- **Trace-format seam is hot**: #562 + #542 — serialize; run `task_159/baseline/verify.sh` for
  trace-touching work. Engine + trace remain lane-A excluded regardless of size (DECISIONS #7).
- Conflation attractor: `is_trace_locked` (probe, `ui/run_tailer.py`) vs `_lock_trace_handle`
  (writer flock, `workflow_trace.py`).
- Windows is a **blocking CI gate**; ADR-0013 governs shell semantics.
- Real-browser verification requires killing stale `pflow ui` servers first.
- Treat old spec file:line refs as stale (Task 177 moved 133 files).
- **Imported-not-earned rules (#19): a fold rule failing against a pflow instance is a user
  escalation, never a silent keep or delete.**
- Worktrees: only `main`; no live subagents. `main == origin/main == 15a36a0f`; the fold sits
  uncommitted on top.
