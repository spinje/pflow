# CURRENT-STATE.md (last verified: 2026-09-28, session-08 close — main @ 7d7ffd44)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Rewritten at close/park (ORCHESTRATION "Artifacts and ownership"); work done outside a
numbered session appends a dated `## Outside-session — folded at next rewrite` block at the top,
which the next boot folds. How-it-got-here: latest `sessions/session-NN.md` (+ the previous three
braindumps); routing: `sessions/INDEX.md`. Every claim here is a pointer to verify, not a fact._

## Process

- The post-parity-fold contract (ORCHESTRATION.md, the role prompt, DECISIONS.md — five rows)
  ran its first full session (session-08) and held: 12 lane-B merges, one Fable planner run,
  the worktree script live (`new` ×13, `rm` ×12, the #635 `-f` semantics shipped mid-session).
  Three sentence-sized process edits applied at close (session-08 log). Everything adopted
  09-27/09-28 is still imported-not-earned (#19).
- Codex runner model `gpt-6-astra` is VERIFIED live: every lane's completion gate ran through
  `workflows/review/run-review-lenses.pflow.md` on Codex. "Cost unavailable" for it is gone
  (#634: subscription-billed agent calls are labelled, API-equivalent shown).
- **mcp SDK is bounded `<2`** (#644 part 1). MCP spec 2026-07-28 removed sessions and
  `initialize`; SDK 2.x renames the streamable client. Migration = a task to file (#644 part 2).

## In flight

- **Task 170 — plan COMMITTED, build NOT started.** Worktree
  `../pflow-worktrees/feat-task-170-one-template-language`, branch tip `25e14b1f` (plan +
  ledger rulings + progress log; base includes main `7d7ffd44`). **Successor's first act:
  launch an Opus `task-orchestrator` on the committed plan** — packet: spec (rewritten
  09-28, decision ledger DECIDED ×9), `implementation/implementation-plan.md`, progress log's
  resume point, ADR-0006 (amended) + ADR-0015, the SUPERSEDED June plan is historical only;
  phase 4d needs `npm ci` in `web/`; engine-contact phases 2 and 4a serialize (never interleave
  #503); no new trace field (hand-back). The planner's window is spent (~600k) — never resume
  it to implement; ask it only for plan intent.
- No other worktrees, no live agents, no open PRs. `origin/main == main == 7d7ffd44`.

## Recently shipped / filed (session-08, all 2026-09-28)

- Merged (lane B): #631 (#622 bug) · #632 (#620 escape → literal) · #633 (#625
  `result_format: json_block`) · #637 (#635 worktree `rm`) · #638 (#623 MCP guide) · #640
  (#634 cost labels) · #641 (#636 SDK content blocks) · #642 (#629 docs snippet validation) ·
  #645 (#644 p1) · #646 (#639 screenshot suite + pinned server) · #647 (#624 long-lived
  pattern) · #649 (#628 `source` required). Prep commit `7dc5ad5d` (spec 170/118, ADRs).
- Filed, open: **#630** (engine unresolved check → Task 170 phase 2) · **#643** (save vs
  `--validate-only` params) · **#644** (p2 migration, task-shaped) · **#648** (namespacing-off
  output sources → after Task 170). #622 open for its parked feature; #621/#550 deferred by
  ruling to ONE language decision after Task 170 (spec "Out of scope"); #551 closed dup.

## Current arc

- **Next session, recommended order (user-agreed at s08 close):** (1) build Task 170 —
  launch the Opus task orchestrator on the committed plan; (2) beside it, ≤3 lane-B fixes
  disjoint from the template seam: #615 → #617 → #618 → #643 → the screenshot skill's silent
  pass after `settle` timeout (file it first); (3) Task 94 as the parallel lane-A run after a
  spec freshness check; (4) no language-semantics work (#621/#550/Task 118) until 170 phase 5
  lands; #644 part 2 (SDK 2.x migration) is a task to spec AFTER 170, not beside it (both
  touch the MCP node). Older open issues (~40) were carried, not re-read — scan once at boot.
- **Task 170 is the critical path** (moved to `next`); Task 118 moved to `then`, blocked by
  170 + the #621 ruling. Task 94 (locked, refreshed s06) is the second lane-A run — refresh
  against main first (Task 177 moved files; s08 merges touched validation).
- **Lane-B tail, user-approved 09-28, packets NOT written:** #615 (resume pre-approves loop
  iterations) · #617 (`delete-file` string false) · #618 (parallel code-batch streams). Bodies
  carry executable repros; the 09-21 audit report is `scratchpads/codebase-audit-2026-09-21/`
  (local). #643 and #648 are lane-B too; #648 waits for 170 phase 4.
- Resume/HITL arc closed (125→164→174→171→176). Tasks 142 and 46 parked in Later by ruling.

## Parallel-lane candidates (open issues; re-scan at pick)

- **Fresh:** #615 · #617 · #618 · #643 · #627 (task-shaped, class of #503) · #608 · #609.
- Candidate issues NOT yet filed (recorded in session-08 PR bodies): the screenshot suite's
  `settle` timeout returns a default viewport → `visual-invariants` passes with 0 checks
  (silent success in the verification tool); `--validate-only` misses a missing REQUIRED MCP
  param; single-node docs fragments unvalidated (#629 covers complete examples only);
  `use_api_key: true` agent runs labelled "subscription" (needs a trace field → task).
- Older: #589 · #542 · #562 (trace-format, serialize) · #546 · #568 · #538 · #544 · #549 ·
  #528 · #552 · #580 (Fable) · #553 · #520/#521 · #566/#567/#572/#574/#575 · #601 · #606 ·
  #602 (blocked upstream).

## Do not re-raise (declined, with the trigger that reopens each)

- pr-closer / RELEASE-BLOCK / batched releases / a docs-PR lane / automatic PR review / a
  cross-task knowledge base — reopens: never (user rulings, DECISIONS #5/#31).
- #624 shape 2 (a pflow-managed session holder) — reopens on a stateful server with neither a
  port nor a proxy path, or a second consumer showing the proxy setup burden (recorded on #624).
- Shell lint, H1-as-name check, PR-title gate, searcher eval harness, `Blocked by:` field,
  DECISIONS index split, agent-file fact checker beyond `test_agent_references.py` — triggers
  unchanged from 09-28 (see git history of this file if needed).

## Regime facts (dated — re-measure, never inherit)

- 2026-09-28: `make test` 9276–9277 passed on main (`ebdbd015`/`871ae780`); `make check` green;
  CI per-job ~2 min, runs on push to main AND on PRs; Windows blocking. Boot set per
  `./scripts/tasks --boot`. Fresh worktrees resolve to Python 3.14 (main's venv 3.13; CI covers).

## Watch list (non-obvious, easy to miss)

- **Template seam is the hot seam now**: #630, #643, #648, #621/#550, Task 118, Tasks 112/120
  all route through Task 170 — serialize anything touching `runtime/template_*`,
  `core/workflow/validator.py` output-source region, or `engine/template_resolution.py` while
  170 builds. Trace-format seam unchanged: #562 + #542 serialize; `task_159/baseline/verify.sh`.
- The user's local `chrome-devtools` registration is pinned `@1.10.1` (#639) — the screenshot
  skill requires ≥1.8; the `-isolated` one is 1.7.0 and REJECTS `pageId`. `mcp-proxy` needs
  `uvx --with 'mcp<2'` until upstream fixes #235.
- Real-browser verification kills stale `pflow ui` servers first; producers stop their own.
- Host load from many parallel agents flakes timing benchmarks (RECURRENCE s08) — keep ≤3
  local lanes plus one planner, or expect reruns.
- `rm -rf` inside a worktree is denied to agents and to you (outside the working dir); lane
  scratch lives under the worktree's gitignored `scratchpads/` (lane def, #635) — an ad-hoc
  dot-dir needs the user's `! rm -rf` before teardown.
- Imported-not-earned rules (#19): a fold rule failing against a pflow instance is a user
  escalation, never a silent keep or delete.
