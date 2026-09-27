# CURRENT-STATE.md (last verified: 2026-09-27 outside any numbered session — main @ 02fcf160)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Rewritten at close/park (DECISIONS #16); work done outside a numbered session appends a
dated `## Outside-session — folded at next rewrite` block at the top, which the next boot folds.
How-it-got-here: latest `sessions/session-NN.md` (+ the previous three braindumps); routing:
`sessions/INDEX.md`. Every claim here is a pointer to verify, not a fact._

## Process

- **Fold batch 3 landed 2026-09-27 (DECISIONS #23–#27) — the process contract moved again; read
  ORCHESTRATION.md fresh.** Headlines: three-tier memory (session `## Braindump` → `RECURRENCE.md`
  → `STANDING-KNOWLEDGE.md`, ex-BRAINDUMP; `sessions/INDEX.md` routing; `./scripts/tasks --boot`);
  routing policy #24 (Fable = main orchestrator / task planners / design-bearing UI; Opus =
  everything else; **Sonnet retired**; **every task gets a planner** — Fable planner → Opus task
  orchestrator); small instruction edits ≤2 applied at close (#25); step-back before a point fix
  + class filing bar (#26); no docs-PR lane, #5 stands (#27). Two new lenses:
  `review-spec-conformance` (code, full-tier) · `review-architecture-fit` (plan/spec).
  **Worktree provisioning is now `./scripts/worktree new | rm | list` (#28)** — the LLM-driven
  workflow runner and `start-work` / `implement-plan` / `manual-verification` /
  `test-writer-fixer` / `create-plan` are retired; `rm` owns the squash-safe teardown check.
  **`make install` FAILED in every worktree until now** (`core.hooksPath` in the shared
  `.git/config` makes `pre-commit install` refuse) — fixed in the Makefile, but a worktree
  checks out committed `main`, so the fix only works for worktrees once it has landed there.
  **Both batches are on PR #626** (`chore/orchestration-fold-batch-3`), user-authorized; merge
  waits on CI + the auto-reviewer comments acted on (#14) + the user's word. Comparison + plans:
  `scratchpads/orchestration-comparison/`; handover for the next agent:
  `scratchpads/handoffs/handover-orchestration-fold-2026-09-27.md` (both local-only).
- Earlier fold (2026-08-14/15, #15–#22, session-07): completion gate is one job owned by the
  gate-runner via the pflow fan-out (#17); effort routing (#18); lane B on `lane-implementer`
  (#20); `review-falsifier` (direct launch only).
- Model/effort on every launch: runner-specific `model` + explicit `effort` (Codex:
  `reasoning_effort`). Root `AGENTS.md` is the live launch contract.
- **Merge policy** (#4/#14): orchestrator merges when fully ready — CI green + the implementing
  agent has acted on auto-reviewer comments. Lane implementers merge their own PRs.
- Instruments: `workflows/review/run-review-lenses.pflow.md` (codex fan-out, waited on in-turn)
  · `workflows/search/run-searcher.pflow.md` (codex searcher offload). Known cosmetic gap: no
  pricing data for `gpt-5.6-sol` → fan-out runs print "cost unavailable".

## In flight

- **PR #626 open** (fold batch 3 + worktree script + CLAUDE.md restructure; 113 paths). No
  worktrees beyond `main`, no live subagents. `origin/main == 02fcf160`; the main checkout sits
  on the PR branch until it merges.

## Recently shipped / filed

- Merged: PR #619 (2026-09-21, CLAUDE-guidance audit) · #614 (08-23, closes #612) · #613
  (08-22, closes #611) · #610 (08-14, the cross-repo fold). No producer remains.
- Filed 2026-09-21, no fixes: #615–#618 (Astra-verified audit of `2ee91a77`; report
  `scratchpads/codebase-audit-2026-09-21/report.md`, local-only).
- Filed 2026-09-27, no fixes, **triage is the orchestrator's + user's call**: #620 (`$${…}`
  escape documented but broken) · #621 (non-template `${` rejected everywhere) · #622 (no code
  sharing; list `code` passes validate then crashes) · #623 (docs: choosing MCP tools for
  deterministic steps; undocumented MCP `timeout:` / `on-error` salvage) · #624 (MCP state lost
  between invocations) · #625 (prose-wrapped MCP JSON). #620–#622/#625 extend the
  #550/#551/#552 `evaluate_script` cluster. Tacit notes:
  `scratchpads/handoffs/braindump-issues-620-625.md` (local-only).
- #608 + #609 (filed 08-14, still open): executed-verified falsifier findings on the #592 fix;
  both lane-B-shaped. #609's fix shape is a claim — the lane verifies the exec-path error
  inventory first.

## Current arc

- **Task 94 spec REWRITTEN + design LOCKED (session-06); not yet started.** Under #24 it is the
  first live run of the Fable-planner → Opus-orchestrator shape — freshness-check the spec
  against `main` first (it predates #610–#619). Task 99 predates Task 177's agent-node
  replacement; refresh before consideration.
- Resume/HITL arc closed (125→164→174→171→176 ✅). Read `task_171` + `task_176` task-reviews
  before resume/gate/trace work.
- Tasks 142 and 46 parked in Later by user ruling 2026-07-15.

## Parallel-lane candidates (open issues; re-scan at pick)

- **Fresh:** #615–#618 · #620–#625 (cluster above) · **#608 · #609**.
- **#589** bounded-memory text stdin (needs a hard-ceiling decision) · **#542** trace retention ·
  **#562** resumable inline workflows (both trace-format — serialize, lane-A excluded) · **#546**
  pinned-run resolve race · **#568** detached UI runs · **#538** liveness backstop (check #566
  overlap) · **#544** `llm_*` canonicalization · **#549** post-#539 visibility · **#528**
  `--output-format` · **#550/#551/#552** MCP `evaluate_script` cluster · **#580** UI run-value
  unwrap (design-bearing → Fable per #8, now routable) · **#553** misleading "Workflow Not
  Found" · **#520/#521** validator/parser · **#566/#567/#572/#574/#575** Windows/test-infra
  tail · **#601** batch cost roll-up · **#606** dual LLM provider tables · **#602** (blocked
  upstream: litellm 3.14 wheels).

## Watch list (non-obvious, easy to miss)

- **Trace-format seam is hot**: #562 + #542 — serialize; run `task_159/baseline/verify.sh` for
  trace-touching work. Engine + trace remain lane-A excluded regardless of size (DECISIONS #7).
- Conflation attractor: `is_trace_locked` (probe, `ui/run_tailer.py`) vs `_lock_trace_handle`
  (writer flock, `workflow_trace.py`).
- Windows is a **blocking CI gate**; ADR-0013 governs shell semantics.
- Real-browser verification requires killing stale `pflow ui` servers first.
- Treat old spec file:line refs as stale (Task 177 moved 133 files).
- **Imported-not-earned rules (#19): a fold rule failing against a pflow instance is a user
  escalation, never a silent keep or delete.** Batch 3 (#23–#27) is imported too.
- Counters that used to live here (searcher-name ambiguity; Chocolatey CI flake) moved to
  `RECURRENCE.md` — recognize a repeat in the moment, increment at close.
