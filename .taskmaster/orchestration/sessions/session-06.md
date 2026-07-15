# session-06 — 2026-07-15

## [2026-07-15] main orchestrator — full-history boot (user-directed) + session-relevance audit

- User booted `start-orchestration` and required reading ALL five prior session logs (not the
  normal latest/thin-file window) plus the full boot stack, then grading each session's relevance.
- Reality verified: `main == origin/main == e2329980` (session-05 close commit), clean; no PRs,
  extra worktrees, or child agents. #592/#589 open.
- Relevance grading delivered: session-05 HIGH (live frontier); 04 MEDIUM (tacit #183 lessons,
  codified in BRAINDUMP); 03 LOW–MEDIUM (Codex approval-boundary gotcha still live); 02 LOW (system
  genesis, fully superseded by canonical docs); 01 LOW (archive/forensics). Confirmed the drain of
  forward-value facts into CURRENT-STATE/DECISIONS/BRAINDUMP was faithful — no orphaned live fact.
  One footnote: #516 (keychain, rescoped session-04) open but absent from candidate list; non-urgent.

## [2026-07-15] main orchestrator — routing ruling: Fable + Sonnet banned

- User ruling: **Fable is banned for all subagents right now; Opus for everything, never Sonnet.**
  Recorded as a DECISIONS #3 amendment (dormant Fable/Sonnet rows, not deleted) + a CURRENT-STATE
  Process line. Visible/uncommitted per DECISIONS #5. Applied immediately: #592 launched Opus.

## [2026-07-15] main orchestrator — #592 shipped (lane B, Opus) with a transient-failure recovery arc

- Provisioned worktree `fix-agent-node-param-validation-error` off `e2329980`; launched one Opus
  issue-mode task-orchestrator. Dependency: `task_177/task-review.md` (agent backend seam).
- **Agent died once on a transient API error** (connection closed mid-response, NOT tier
  exhaustion) mid-investigation, clean worktree/no commits → resumed the SAME agent via SendMessage
  (context intact). Correct call vs a replacement.
- **Chocolatey outage arc:** PR #597's two blocking `tests-windows` jobs failed at `choco install
  make` with HTTP `499` from the community feed — infra flake, no pflow test ran. Diagnosed at the
  seam; waited ~15m for feed recovery, reran → green. Verified the failure was identical on both
  jobs and not code. Lesson surfaced to user: retry is a band-aid; the top-10% fix is removing the
  feed from the CI critical path (Windows CI calls `uv run` directly) — gated on confirming
  recurrence. Recorded in CURRENT-STATE as noticed-not-filed.
- **Codex auto-review caught a real P1 the agent introduced:** first pass made
  `AgentValidationError` non-retriable, which would abort a whole `error_handling: continue` batch
  on one bad item (`batch_executor` re-raises non-retriable). Agent confirmed, fixed in `68730e6f`
  (inherit `retriable=True`, restoring pre-#592 batch behavior), added mutation-verified
  sequential+parallel regression tests. I spot-checked the disposition at the seam — sound and
  in-scope ("types not when/whether"). The `spinje`-authored review comment is the AGENT posting
  under the repo git identity, NOT the human user — noted to avoid future confusion.
- Merged (squash `573718cb`, #592 auto-closed). Squash-safe teardown: PR headRefOid == remote tip
  == worktree tip == `68730e6f`, clean → pruned worktree + local/remote branch; ff'd local main to
  `573718cb`. Gates at merge: `make check` + `make test-all-local` green (9063 passed / 2 skipped);
  4-specialist deep-review dispositioned; real-CLI evidence (bad `sandbox` → structured
  `PflowError`, no raw `TypeError`). Watched all CI via background poll loops (agent kept stopping
  while "watching" — its background watch can't outlive the agent; orchestrator owns the wait).

## [2026-07-15] main orchestrator — Task 94 evaluation (in progress)

- Two Opus searchers established ground truth (see CURRENT-STATE "Current arc" for the state).
  Original spec substantially STALE (removed `registry describe` surface, false "no detection"
  premise, obsolete `llm`-library). User reframed the live problem as **choice-support**.
- Design converging (NOT locked): curated big-3 guidance + key-aware + LiteLLM escape-hatch;
  completeness by pointing, not enumerating. User's question "what about all the other LiteLLM
  ways?" resolved the two-jobs split (opinionated guidance can't be auto-generated; mechanical
  reachability is already `settings llm providers`). Awaiting user: lock design → rewrite spec, or
  mock first. Do NOT redo this evaluation absent contradictory evidence.

## [2026-07-15] main orchestrator — Task 94 design LOCKED + spec rewritten

- Long Show-Before-Code design iteration with the user hardened the surface (see BRAINDUMP: the
  user pressure-tests CLI surfaces and demands verified consistency). Net decisions: **enumeration
  not curation for v1** (curation deferred — needs upkeep, doesn't scale); **network-by-default with
  offline fallback** (user overruled my offline-default — an unlisted model still runs, so offline
  under-reports); **drop `--filter` and `--all`** after grep proved the CLI filters via positional
  keyword only and naming a provider already inspects unconfigured ones; **cap only multi-provider
  views, single-provider is the "see all"**; status label `(configured)`/`(no key — set VAR)`.
- Rewrote `task_94/task-94.md` in place via `create-task` conventions (provenance banner marks the
  original SUPERSEDED). Full design rationale + the PR-#424 `register_model(dict)` landmine live in
  the spec. Ready for lane A (single Opus task-orchestrator, plan-and-implement).
- Updated BRAINDUMP (tacit only — background-watch-is-a-lie, transient-death≠exhaustion,
  `spinje`-review-is-the-agent, top-10%-test-applies-to-CI, stale-framing-hides-real-problems,
  CLI-surface pressure-testing) and CURRENT-STATE. All session-06 edits remain uncommitted per
  DECISIONS #5.
