# CURRENT-STATE.md (last verified: 2026-09-28 outside any numbered session — main @ 02fcf160)

_Living state header — the ONE mandatory session-start read (~80-line budget; state + pointers
only). Rewritten at close/park (ORCHESTRATION "Artifacts and ownership"); work done outside a
numbered session appends a dated `## Outside-session — folded at next rewrite` block at the top,
which the next boot folds. How-it-got-here: latest `sessions/session-NN.md` (+ the previous three
braindumps); routing: `sessions/INDEX.md`. Every claim here is a pointer to verify, not a fact._

## Process

- **The process contract moved twice in two days — read ORCHESTRATION.md, the role prompt and
  DECISIONS.md fresh; nothing below restates them.** 2026-09-27: three-tier memory, routing
  policy (DECISIONS #24), `scripts/worktree`, CLAUDE.md restructure. 2026-09-28: the sibling
  programme's orchestration standard adopted IN FULL (user: *"make sure pflow is up to date to
  [the sibling's] orchestration standards in full"*) — delegation by default with path+summary
  returns; producer sets spec Status/Completed before the PR; closing-keyword and
  `closingIssuesReferences` discipline; dev servers stopped and declared at handback; tooling
  postmortems (screenshot skill); deep-review: empty-scope guard, read-in-full, counter-cited
  disputes, falsifier last and outside the cap, same-family fallback disclosure, sensitive-path
  minimum tier; searcher points at `context/`; test-reflect restore rule. Homes carry every rule.
- **DECISIONS.md is five rows** (#4 merge authority · #5 commit authority · #19 name ban +
  imported-not-earned · #24 routing · #31 no knowledge base) under the user's bar: *"decisions
  are things that will impact future sessions hard and are not inferrable through its home"*. No
  dates; numbers stable; removed rows live in git. Live citations were repointed at Homes;
  session logs and task archives keep theirs as history.
- **`.taskmaster/knowledge/` is deleted (#31).** 60 entries audited: 5 became one-line code
  comments, 1 became `context/adr/0014` (Task 135 engine + shared-store-only), the rest were
  already at their Homes, stale, or generic. The audit found and fixed #616 (copy/move-file
  shared-store `overwrite` fallback) on the PR branch.
- **Codex runner model is `gpt-6-astra` for every tier** (the two previous runner names are
  retired, per the sibling's swap); `tests/test_scripts/test_codex_model_names.py` sweeps live
  files for them. Root `AGENTS.md` is the live launch contract.
- **No automatic PR review** (workflow removed; reviews run before `create-pr`); the on-demand
  `@claude` mention workflow stays. Merge = CI green on the merged result (#4) + the user's word
  where #5 requires it.
- Instruments: `workflows/review/run-review-lenses.pflow.md` (codex fan-out, waited on in-turn)
  · `workflows/search/run-searcher.pflow.md` (codex searcher offload). Cosmetic: no pricing data
  for the runner model → fan-out runs print "cost unavailable".

## In flight

- **PR #626 open, CI green** (`chore/orchestration-fold-batch-3`; the 09-28 batch is committed
  at `7deaa77c` and pushed, user-authorized; body carries "Closes #616"). Merge waits on the
  user's word (#4/#5). After merge: `git checkout main && git pull`; `make install` in worktrees
  works from then on. Handover: `scratchpads/handoffs/handover-parity-fold-2026-09-28.md`.
- No worktrees beyond `main`, no live subagents. `origin/main == 02fcf160`.

## Recently shipped / filed

- Merged: PR #619 (09-21, CLAUDE-guidance audit) · #614 (08-23) · #613 (08-22) · #610 (08-14).
- Filed 09-21, no fixes except #616 (fixed on the PR branch, closes on merge): #615, #617
  (`delete-file` string `confirm_delete` — see also #448), #618.
- Filed 09-27, no fixes, triage is the orchestrator's + user's call: #620–#625 (MCP/template
  cluster; #620–#622/#625 extend #550/#551/#552). Notes: `scratchpads/handoffs/braindump-issues-620-625.md`.
- #608 + #609 (08-14, open): executed-verified falsifier findings on the #592 fix; lane-B-shaped.
- Filed 09-28 from the knowledge-base audit: **#627** (nodes raise vanilla exceptions at 45 sites —
  task-shaped, class of #503) · **#628** (sourceless declared output passes validation, produces
  nothing — needs the reject-vs-warn ruling). The simple finds were fixed on the PR branch.

## Current arc

- **Task 94 spec REWRITTEN + design LOCKED (session-06); not yet started.** First live run of
  the Fable-planner → Opus-orchestrator shape — freshness-check the spec against `main` first.
  Task 99 predates Task 177's agent-node replacement; refresh before consideration.
- Resume/HITL arc closed (125→164→174→171→176). Read `task_171` + `task_176` reviews before
  resume/gate/trace work. Tasks 142 and 46 parked in Later by user ruling.

## Parallel-lane candidates (open issues; re-scan at pick)

- **Fresh:** #615 · #617 · #618 · #620–#625 · **#608 · #609** · #628 (ruling first) · #627 (task-shaped).
- **#589** bounded-memory text stdin (needs a hard-ceiling decision) · **#542** trace retention ·
  **#562** resumable inline workflows (both trace-format — serialize, lane-A excluded) · **#546**
  pinned-run resolve race · **#568** detached UI runs · **#538** liveness backstop (check #566
  overlap) · **#544** `llm_*` canonicalization · **#549** post-#539 visibility · **#528**
  `--output-format` · **#550/#551/#552** MCP `evaluate_script` cluster · **#580** UI run-value
  unwrap (design-bearing → Fable) · **#553** misleading "Workflow Not Found" · **#520/#521**
  validator/parser · **#566/#567/#572/#574/#575** Windows/test-infra tail · **#601** batch cost
  roll-up · **#606** dual LLM provider tables · **#602** (blocked upstream: litellm wheels).

## Do not re-raise (declined, with the trigger that reopens each)

- pr-closer / RELEASE-BLOCK / HOLD-PUSH / batched releases / pure-docs self-merge / a docs-PR
  lane — pflow has no production; state lands per #5. Reopens: never (user: "no docs prs").
- Automatic PR review (any bot) — reviews run before the PR. Reopens: never.
- A cross-task knowledge base (#31). Reopens: never.
- DECISIONS index/archive split — moot at five rows.
- Agent-file fact checker beyond `tests/test_docs/test_agent_references.py` — reopens when a
  searcher def crosses ~30 KB (now ~15 KB).
- Shell lint (pinned shellcheck over `scripts/`) — reopens on a shell bug shellcheck would have
  caught. H1-as-name check for task specs — reopens when the board's width is a complaint.
  PR-title Conventional-Commit gate — reopens when a changelog entry reads wrong. Searcher eval
  harness — reopens at the next searcher-def edit larger than a paragraph. `Blocked by:` /
  `## Use cases` spec fields — reopen when the board parses them. `draft` task status — the
  check rejects it.
- Foreground review fan-out and rebase+force-with-lease — pflow's choices (background-to-file,
  merge-main) are deliberate; the sibling's differ for its own reasons.

## Regime facts (dated — re-measure, never inherit)

- 2026-09-28: `make test` 9190 passed; `make check` green; boot set per `./scripts/tasks --boot`
  (run it — the number is in the handover). CI per-job ~2 min; Windows is a blocking gate.

## Watch list (non-obvious, easy to miss)

- **Trace-format seam is hot**: #562 + #542 — serialize; run `task_159/baseline/verify.sh` for
  trace-touching work. Engine + trace remain lane-A excluded regardless of size (ORCHESTRATION
  "Lanes").
- Conflation attractor: `is_trace_locked` (probe, `ui/run_tailer.py`) vs `_lock_trace_handle`
  (writer flock, `workflow_trace.py`).
- Windows is a **blocking CI gate**; ADR-0013 governs shell semantics. Its two network fetches
  (Chocolatey `make`, the `npx` MCP smoke package) retry three times since 09-28 — the flake
  class hit n=2 (s06/s07 Chocolatey, 09-28 npx) and the retry is the record.
- Real-browser verification requires killing stale `pflow ui` servers first — and the producer
  now stops its own before handback.
- Treat old spec file:line refs as stale (Task 177 moved 133 files).
- **Imported-not-earned rules (#19): a fold rule failing against a pflow instance is a user
  escalation, never a silent keep or delete.** Everything adopted 09-27/09-28 is imported.
- Unattended `rm` denials (n=2 in RECURRENCE) were ruled: the user removed the `ask` rule on
  `rm` from `.claude/settings.json`; the counter is gone (the setting is the record).
