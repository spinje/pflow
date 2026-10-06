# session-10 — 2026-10-05

## [2026-10-05] main orchestrator — boot + reality diff

- Booted per the role prompt; two sessions carry braindumps → boot fork (1b) skipped per its gate; no pflow
  predecessor session live. Reality vs CURRENT-STATE: no drift (main == origin/main == `e402a1e6`, the s09
  close commit; no worktrees, no open PRs, no issues newer than #683). `./scripts/tasks --check` clean.
- Correction to CURRENT-STATE: open issues = 143 (MEASURED `gh issue list --state open --limit 200`), not
  "~85" — the s09 count was from a truncated listing.
- User focus: *"lets carefully investigate the current state and examine where our highest value/leverage
  things to focus on right now lies, we might need to explore some because im not sure of the current state"*.
- Investigation wave 1 (read-only): freshness of the four `next`-slot specs (99, 111, 121, 179) against main;
  full open-issue audit (143) delegated to an Opus agent; MCP SDK pin vs upstream measured by me.
- MEASURED: `mcp` pinned `>=1.17.0,<2`, locked 1.26.0; PyPI latest 2.3.0. Last release v0.15.1 (2026-08-02);
  39 commits on main since, unreleased (Tasks 177, 94, 170 + ~20 fixes). CI on main green at `e402a1e6`.
- Task 111 freshness (searcher, cited): unbuilt; spec cites a deleted class (`PflowBatchNode.prep()`); the
  "default 3 for local files" conflicts with shipped behaviour (`run-review-lenses.pflow.md` batches >3 lenses;
  `test_progress_streaming_subprocess.py:361` 4-item batch; guide says batch "always runs all N"); `fail_fast`
  already cuts failing runs short. Only an opt-in flag survives. Memo-cache key must include the limit.
- Task 121 freshness (searcher, cited): unbuilt, need OBSERVED in the repo's own tests (three ad-hoc
  real-workflow tests: a hand-synced skeleton `test_plan_to_code_harness.py`, regex+`exec`, single-node run);
  spec's Implementation Notes stale (wrapper chain gone; the real hook is `apply_memo_hit` + the trace
  snapshot seeder `resume_source.py:810`); spec omits the `agent` node. No GH issue asks for it.
- Task 99 freshness (searcher, cited): unbuilt; spec targets the deleted `claude-code` node and
  `ExecutionService.run_workflow()` (now `execute_workflow`, pausable); never considers Codex; the folder holds
  three contradicting tool shapes (two tools / one tool / server-per-workflow). Task 177's review already said
  "re-scope to `agent`" (`task_177/task-review.md:90`). Needs a spec rewrite before any planner.
- Task 179 freshness (searcher, 60 claims): 0 wrong; ~15 citations drifted (Task 170 +12 in `engine.py`
  after ~270, `loop_control.py` −8, `run.py` +2); `_gate_pausable` unmoved; #659 still reproduces by code
  path. Corrections to fold if launched: Q2's cite (`resume_source.py:381-388, 594-601`) is binary-placeholder
  only — LLM prompt/system stripping lives in `workflow_trace.py` and resume does NOT refuse on it today;
  the "pinned" restart test (`test_resume_engine.py:736`) fails at iteration 1 so it cannot distinguish restart
  from continue; deletion list misses `guide/features/approval.md:34,52`, `runtime/engine/CLAUDE.md`,
  `docs/reference/cli/index.mdx:90`; `resume list` passes only `{"kind"}` (`resume.py:440`) — position must
  thread through `PausedRun`.
- Issue audit (Opus, all 143 read; report `scratchpads`-less: /private/tmp/…/scratchpad/issue-audit.md, local-only):
  T1=4 (#665 save --force data loss · #675 memo cache stale · #659 host frame · #458), T2=27, T3=74, T4=38.
  My re-rating: #458 is T2 (documented `--only` limitation; the ask is an advisory). The auditor's "one root
  cause" cluster for #675/#458/#659 does NOT hold on my read — three mechanisms (memo key, trace frame seq,
  snapshot semantics); relayed as three items. Verified-fixed, closable on the user's word: #215, #314, #513,
  #644-as-scoped. Plausibly fixed, unverified: #297 #186 #348 #359 #232 #184 #520 #92 #256 #408.
- Clusters worth more than any member: validate-only-passes/run-fails (#678 #520 #681 #297), misleading
  suggestions (#437 #553 #192 #285 #315), PflowError migration (#627 #503 #608 #609), cost rollup (#601 #436 #494),
  parser `- key: |` opacity (#521 #389 #150 #428), template-language ruling (#621 #550 #59 #92).

## [2026-10-05] [RULING] *"go ahead with this, skip 665, save isnt a top tier feature right now all uses ive had myself has been in a local repo"*

- Approved: Task 179 lane A (Q1 = (c), Q2 = continue unless unrestorable → refuse with guidance); lane B
  validate-only cluster as the parallel companion (#678 first; #520/#681 serialize behind it — same
  `template_validation/` seam); close #215 #314 #513 #644; demote Task 111 → `then`; mark 99/121 "spec rewrite
  required". NOT launched: #665 (user: save is not top-tier now — a priority ruling, issue stays open).
  Release (item 4) held — outside any grant; asked separately.
- Folded into specs: 179 (Q1 (c) + Q2 DECIDED, drift note, deletion-list additions, weak-pin test, `PausedRun`
  constraint) → prep commit `90b891cb` pushed (DECISIONS #5 — covers the approved launch). 111 → `then` with the
  withdrawn default; 99/121 carry "SPEC REWRITE REQUIRED" blocks (uncommitted — ride the close commit).
- Closed #215 #314 #513 #644 with code evidence (verified by me before closing). Open issues: 139.
- LAUNCHED (two worktrees, provisioned sequentially): Task 179 Fable planner (plan-only; engine+trace → plan-mode deep-review mandatory; UI
  phase marked Fable) · #678 Opus lane (STOP on engine contact; options hand-back on ≥2 field-check shapes;
  #520/#681 queued behind it).

## [2026-10-05] [RULING] *"go ahead then lets discuss 2"* (items 1, 3, 4, 6 of the "anything else" list)

- Provisioned sequentially + LAUNCHED: dogfood pass (Opus, scratch-only, `dogfood-*` saves, ≤10 LLM calls);
  #521 lane (may close #389 if one mechanism; STOP on validator/templates/engine); #437 lane (expected to hand
  back BEFORE/AFTER output shapes — show-before-code; `core/exceptions.py` edits additive only). QUEUED behind
  the first lane to finish (host-load cap 3 lanes + planner): #627 PflowError ratchet; #553 after #437;
  #520/#681 after #678.
- Answered the user's MCP question from the s08 record (#624 ruling comment, Task 178 research): sessionless
  spec 2026-07-28 → client risk narrow/one-directional (modern-only servers), server fine, #624 orthogonal;
  research pinned at SDK 2.2.0 — PyPI now 2.3.0 → refresh at 178's planner.
- #678 ESCALATED (2/5 ×2) → resolved here: (1a) edit all out-of-list test fixtures incl. `test_resume_engine.py`
  (179 is plan-only — no live collision); (2a) delete `examples/error-handling/typo-on-failed-node.pflow.md` + README
  row + e2e test (scenario no longer exists; unit coverage stays). Added: docs/guide/examples sweep is in-lane;
  the dynamic-index root gap (`typo.out_arr[${i}].x`) closes in the same PR. Lane EXECUTED the repro on main;
  found only one defensible shape (Pass 5 parity with params); prototype ~60 LOC / 4 files, 11 expected test flips.
- User: *"does it always include updating the cli surfaces, like guides and external docs when we implement a
  lane or task if applicable?"* — MEASURED: CLAUDE.md:184, ORCHESTRATION "Living documentation",
  `review-spec-conformance.md:45`, `task-orchestrator.md:119` all name CLAUDE.mds + agent defs + `pflow guide`;
  **`docs/` (mintlify) is named by NO standing rule** — only by individual specs (178) and packets (today's #678).

## [2026-10-05] [RULING] *"isnt the real fix to do 4. task 118 or?"* → *"yes to all"*

- OWNED: I proposed option 2 (surface tolerance) as an interim without stating it would be deleted by option 4
  for shell/code bodies — the s09 pattern again (RECURRENCE n=2 at close). The user caught it.
- Task 118 → `next`; spec refreshed with the decision ledger (shell body never templated, `inputs:` binding;
  residual tolerance only in MCP code-bearing params; `${var|json}` filter; linting = phase 2); Task 170's
  deferred paragraph points at it. ADR-0016 drafted (`context/adr/0016-118-shell-node-inputs-binding.md`) —
  conversation-born → context-free Opus review LAUNCHED (ADR-FORMAT rule); fold before the close commit.
  118's planner launches after #678 merges (validator surface).
- Docs rule gap closed (user's question): `docs/` added to root `CLAUDE.md:184`, ORCHESTRATION "Living
  documentation", `review-spec-conformance.md:45`, `lane-implementer.md` DoD; `make sync-claude-assets` run.
- Dogfood pass DONE (Opus, ~$0.00004 LLM spend, 8 calls; report + findings.md local-only under scratchpad/dogfood):
  0 BLOCKERS; 12 ranked frictions, 7 MISLEAD. My re-measure CONFIRMED F25: `settings show` prints a UUID-shaped
  key unmasked (prefix-shaped keys masked). F5 = #458 re-observed (+ `history` records ignored inputs).
  F1/F16 = Task 120's problem, now OBSERVED → promote 120 (proposed). Verification + issue drafting delegated
  (Opus); I file serially after reading. Left behind in ~/.pflow: 49 traces, 3 report dirs, cache rows.
- #437 lane HANDED BACK (3/5): headline symptom already fixed by PR #519 (2026-06-16, owner comment on the
  issue — the audit's stale pass missed it); residual = node failures have no structured suggestions channel
  (`executor_service.py:115-122` passes no `suggestions=`; `llm.py:75-76` flattens them to prose; report never
  sees them). Lane's option C (reserved `_diagnostic_suggestions` key, parity with `_diagnostic_title`) → user.
  Worktree parked clean @ `90b891cb`.
- #627 lane LAUNCHED (slot freed by #437): 49 vanilla raises MEASURED (was 45); hand-back if >1 new class or
  retry-contract change; `core/exceptions.py` additive only.
- ADR-0016 context-free review (Opus, EXECUTED repros): REFUTED my premise "the code body is literal" —
  `code.code` is scanned/interpolated like every param (`template_resolution.py:111-114`); the guide line is an
  authoring rule. I wrote the mechanism from the guide, not the code (RECURRENCE "read the cited function" → n=3).
  Folded: ADR rewritten (exemption is NEW machinery for both bodies; `env:` exists; `inputs:` already means
  template vars; env limits; shell checks that go dead; MCP identifier trade-off). Spec 118: two OPEN (user)
  items added — binding param (`env:` reuse vs `inputs:`; I recommend `env:`) and identifier-shaped `${…}` in
  MCP code params.

## [2026-10-05] [RULING] *"yes go ahead witht this"* — `env:` reuse (118), MCP code params tolerate all `${…}`, #437 → #684, Task 120 → next

- Recorded in the 118 ledger + ADR-0016. Task 120 → `next` with the dogfood evidence block. **Release NOT cut**
  (still needs an explicit yes — never inferred from a general go-ahead).
- Filed **#684** (node failures carry no structured suggestions; `_diagnostic_suggestions` parity with
  `_diagnostic_title`; show-before-code hand-back). Closed #437 (headline fixed by PR #519, EXECUTED by the lane).
  #437 worktree removed with `worktree rm -f` (the script refuses a branch with no merged PR; tree clean, 0 commits past main — MEASURED) and the local branch deleted by hand (never pushed).
- User FYI *"main on gh is failing"*: run 37362914656 on my docs-only prep commit `90b891cb` (main was green on
  the same code 10-01). MEASURED at the seam: `quality` → `uv sync --frozen` connection reset fetching `jiter`
  from files.pythonhosted.org + Actions cache 400 (infra); `tests-windows-mcp-smoke` → `pflow mcp sync everything`
  hit the 60 s discovery timeout AFTER a successful npx pre-warm and printed a bare `Error: Error`
  (`cli/commands/mcp.py:642` echoes `result.error`). Smoke flake now n=2 (s09 n=1). One `--failed` rerun issued.
  The bare error text is a diagnostics bug → issue after a searcher traces the source string.
- Filed **#685** (MCP discovery failure → bare `Error: Error`): searcher traced it to `diagnostic_render.py:150`
  fallback title + empty `describe_mcp_error` message (`errors.py:106-112`) — the leaf was NOT a TimeoutError;
  server stderr → devnull during discovery (`discovery.py:37-54`), `-v` doesn't change that. Hypothesis
  (UNVERIFIED): cleanup exception replaces the TimeoutError on 3.11+. Not launched — queued lane B.

## [2026-10-05] [RULING] *"great what we have running right now is enough for this session"*

- Read as: no new launches; drain 179 planner + lanes #678 #521 #627 + dogfood issue drafting; file issues as
  records; close. The 179 task-orchestrator launch = a new start → next session. Queued, not launched: #520 #681
  (behind #678), #553, #684, #685, Task 118 planner (after #678), Task 120.
- Dogfood verification (Opus, EXECUTED, 3 LLM calls): 14 findings hold. FILED (read by me first): #686 code-input
  auto-parse overrides `str` (NOT Task 120 — corrected my 120 evidence block) · #687 lossy CLI string round-trip
  (`02134`→`2134`, residual of closed #83) · #688 nested-field did-you-mean · #689 one ref → two validators ·
  #690 fix-then-resume refused twice (serialize w/ 179; pointer added to 179 spec) · #691 model did-you-mean +
  auto-detect hint · #692 product Q: delete saved workflow (rec. `pflow delete`) · #693 unknown command routed as
  workflow · #694 file-node `Writes: bool` docstrings wrong · #695 success JSON lacks run identity · #696
  `settings show` prints `<X>_KEY` unmasked (name-word rule, NOT the `:`) · #697 `pflow report` renders secret
  inputs raw; traces 0644 · #698 HTTP status failure omits URL · #699 exception failures drop metrics /
  `nodes_executed` two meanings · #700 error advice in JSON/flag syntax · #701 `_pflow_workflow_file` in
  describe/history · #702 `find` LLM call invisible · #703 probe --help stale. Task 120 evidence folded (draft 03).
  Commented #458 with the re-observation. Open issues now 158 (139 + #684 #685 + 17).
- CI: rerun attempt 2 of 37362914656 QUEUED since 19:57Z with no runner (checked 20:05Z); githubstatus.com:
  Actions = degraded_performance, open incident "Incident with Actions | investigating". The quality-job cache
  400 at 19:23Z fits the same outage. No further reruns until the incident resolves (external-feed rule, s06).
  Lanes merging into this should expect queue delays — not pflow failures.
- Task 179 PLANNER DONE (Fable, ~458k own + ~1.4M across 10 subagents per its report; metadata 457,895 own):
  plan at `feat/task-179-durable-loop-position` **`512ce632`** (GROUND-TRUTHED: `git log` shows it, tree clean, 804
  lines, base == origin/main `90b891cb`). Q3 (a) + `GateRequest.iteration`, trace 2.7.0 → 2.8.0; Q4 (step, iteration)
  entry, `_seedable_final_events(..., entry_iteration)` with `>=`; Q5 restore only `loop_counts[K]` + `shared[K]`;
  Q6 one field → six surfaces (TTY prompt header found as the sixth). Plan-mode deep-review: 5 Opus lenses, 2
  Criticals convergent, folded. Spec corrections by the planner: `_fully_answered_gate_ids` KEPT; Q2: a stripped
  LLM prompt is not a loader refusal (the strict carry guard is the loud failure). Size call: task orchestrator
  builds it — NOT launched this session (user: "what we have running is enough"). Keep this planner reachable.
- 179 ESCALATED (3/5, plan proceeds on (b)): a loop step whose escalation fires on the workflow's FINAL step
  cannot pause (default-successor conjunct). (a) drop for loop steps · (b) keep + document the recipe needs a next
  step · (c) drop for all escalations (`resume_after` subsumes the "engine resolves every between-nodes entry"
  follow-up). Planner recommends (b) now, (c) as its own ruling → user, at the next session's launch.
- Task-159 baseline MEASURED by the planner at `90b891cb`: 79/87, 8 drifts (#680's 7 + one Python-3.14
  `SyntaxWarning` in stderr) — #680 should note the eighth.

## [2026-10-05] [RULING] *"go ahead with your recommendations and implement"* → 179 build LAUNCHED

- Read as: final-step loop escalation = (b) (recorded on the BRANCH spec, commit `e67af2a2` — feature-branch docs
  commit, not main) + launch the Task 179 Opus task-orchestrator now (widens the earlier "enough for this session"
  for this one item; 118 planner / #692 / queued lanes stay queued on their triggers).

## [2026-10-05] [RULING] deep-review skill: *"yes to all"* (floors by trigger, per-seam targets, spec mode, dogfood pass, falsifier widened) → *"let me review changes locally before commiting"* → *"great, go ahead with this"*

- Rewrote `.claude/skills/deep-review/SKILL.md` (size tiers + 1–8 cap → trigger table; counts are floors; per-seam
  `{name,target}`; "Spec review mode"; "The standing dogfood pass" — cadence per release AND ~10 merges, spend
  capped); ORCHESTRATION Review policy (+3 bullets; main-orchestrator carve-out for spec review + dogfood);
  release skill pre-flight (dogfood after the clean-state check); lane-implementer + task-orchestrator gate
  wording; `review-simplicity` widened to any consolidation; `review-spec-conformance` = multi-phase tasks with a
  spec+plan (never a lane). Context-free Opus review of the rewrite: 7 internal contradictions + 4 stale docs +
  mechanism half-refuted → all folded; rulings (user: *"go ahead with this"*): bug-fix floor = test-fidelity
  never waived (docs-only is the only zero); sensitive-path falsifier runs even for a "pure refactor";
  simplicity on lanes yes, spec-conformance tasks-only. Filed **#706** (fan-out `collect` drops `target`; land
  in a quiet moment — shared tooling with live producers). All UNCOMMITTED — user reviews locally; close commit.
- User Q: *"didnt you have to commit the task file updates and docs related to it before launching those
  planners/worktrees or?"* — 179: yes, prep commit `90b891cb` before provisioning (DECISIONS #5); (b) ruling on the
  branch (`e67af2a2`). Lanes: nothing producer-facing changed → no prep commit. Nuance recorded: agents launched
  from THIS session read `.claude/` from the main checkout's WORKING TREE (uncommitted edits reach them; worktree
  checkouts are unaffected) — the 179 build will gate on the NEW deep-review skill (intended); #521 launched
  before the `docs/` lane rule → sent the docs sweep by message before its merge (PR #705).

## [2026-10-05] [RULING] *"yes 1 but we shouldnt close anything that could be important"* — issue triage launched

- Opus agent (read-only, no closes): Part A verifies the 10 plausibly-fixed (#297 #186 #348 #359 #232 #184 #520
  #92 #256 #408 + #321/#334 → #361) and drafts narrowing comments for #398 #622 #538; Part B triages the 38
  T4 issues with a KEEP-biased four-criterion bar (observed? roadmap/task/open-issue reference? security/data/
  correctness? design record with a revisit trigger?). The user approves the list before anything closes.
- CI: rerun attempt 2 — `tests-windows-mcp-smoke` PASSED (flake confirmed, n=2 → #685 holds the diagnosis),
  `quality` CANCELLED by the platform; githubstatus Actions = **major_outage** (20:4xZ). Holding all reruns.
  Lane PRs open: #704 (#678), #705 (#521), #707 (#627) — all waiting on CI; expect their "CI watch" handbacks to
  die with the outage (STANDING-KNOWLEDGE: I own the wait, resume each lane only for the merge click).
- #521 lane PARKED on the outage: PR #705 @ `c4e7c136` (closes #521 + #389 — one mechanism, intended), 11 checks
  green; `tests-and-type-check (3.10)` + `tests-windows (core-cli-nodes)` cancelled twice with no runner. RESUME:
  when Actions recovers → `gh run rerun 37369946437 --failed` → green → resume the lane for the merge click.
  Lane EXECUTED: the class was worse than filed — a `- prompt: |` containing `## Output format` SILENTLY dropped
  everything after it (no warning); falsifier broke the first fix (a whole step vanished). Docs sweep: none stale (greps in PR body). Filed **#708** (parser silent-loss class: the four main-side gaps the lane listed).

## [2026-10-05] MERGED #678 — PR #704 → `48a9d426` (closes #678 only — verified `closingIssuesReferences`)

- Lane: point fix (Pass 5 parity for output sources + the dynamic-index root gap); deleted the typo-on-failed-node
  example per my (2a). Runners were partially serving despite the status page's major_outage.
- Lane-reported rule break: `pkill -f "gh pr checks 704"` (kill by NAME) — RECURRENCE "kill by name" → n=2
  (s09 falsifier, s10 lane); the def says PID-only; promote at close. Also edited `tests/test_cli/test_resume_cli.py`
  (outside the ruled list, same shape as group 3 — accepted, noted in the PR body).
- Sent the 179 build the MEASURED file delta (two resume test fixtures changed one string each). Sent #521 the
  resume instruction (merge main, re-gate, rerun ≤2, merge).
- **Task 118 planner trigger (#678 merged) is now MET — HELD**: the user's session boundary ("enough for this
  session" — only 179 was widened) and the 118 spec + ADR-0016 are uncommitted under the user's local review; the
  next session prep-commits them (DECISIONS #5) and launches. Queued behind it on the same seam: #520, #681.

## [2026-10-05] Task 179 CHECKPOINT (3/5) — #656 "approve all remaining iterations" → user

- Build state at the checkpoint: P1–P4 committed and green on the merged result; baseline unchanged (the
  planner's 8th drift was environmental). Real-surface evidence lives in the progress log.
- Checkpoint page (6 real-browser screenshots @ `e10ba5cc`) published as an Artifact for the user; recommendation
  (planner + P4 implementer): A = not now (CLI `--auto-approve` covers unattended; panel shows no cap; design
  P4b stays written). Side finding: Task 176's gate header crowds with a long step id (buttons below the fold) —
  issue if the user wants.
- Accepted at the orchestrator's level (≤2): a mid-task reviewer's fix (approval after a recovered failure resumed
  at the wrong iteration — one function). #690/#458 NOT decided by Q2 → land after this PR.
- For me at merge: CONTEXT.md **Resume** definition += "a loop step re-enters at the Iteration where it stopped".
- Process break (logged, RECURRENCE n=1): the task orchestrator ran P3 and P4 implementers IN PARALLEL in one
  worktree ("sequentially, never two agents concurrently in one worktree") — side effect observed exactly as the
  rule predicts (P3's `make check` regenerated P4's `.agents/` copy). No damage; the def's rule is unambiguous.

## [2026-10-05] MERGED #521 + #389 — PR #705 → `baf2d73f` (closes both — verified; one mechanism, intended)

- Lane: block scalars opaque to fence+heading detection; the falsifier's first round showed the broad version
  silently deleted a step → narrowed to block scalars. The four main-side gaps → #708.
- Remaining live: Task 179 (parked on the #656 checkpoint, head `63b65e74`) · #627 lane (PR #707 @ `cf3cf755`,
  checks pending). Main moved twice under both (`48a9d426`, `baf2d73f`) — #627 touches `nodes/**` only; the parser
  merge is disjoint; the lane re-gates per its def before merging.

## [2026-10-05] [GRANT] *"go ahead and run this session end to end, when you are done and FULLY happy with no loose ends, close the session"*

- Scope read back: #656 = A (collapsed to the shared recommendation, 179 resumed to its completion gate → PR);
  triage posted (closed #33 #186 #359 verified-fixed; #12 #276 #346 #352 #363 #377 #409 #411 #419 #436 #479
  not-observed with reopen triggers; #370 KEPT — trace-contract drift matters while 179 bumps the format;
  narrowing comments #398 #622 #538 #184 #348 #520 #92; evidence comments #14 #76 #349 #297). Open issues: 143.
  Drain: 179 → merge; #627 → merge; reconcile; close ritual — everything but the close commit (DECISIONS #5; the
  user is reviewing the tree locally). OUT: release, new launches (118 planner stays queued), 4–5/5 forks park.

## [2026-10-05] MERGED #627 — PR #707 → `b59cf9e5` (closes #627 only; #503 = Refs, engine sites stay)

- Lane widened the class on evidence: an AST scan found 68 vanilla-exception sites (the issue's grep said 49) →
  one new `NodeError(message, *, param)` + a ratchet test. Also fixed in passing: the http timeout hint (#700).
- **Lane 1–2/5 rider to re-rate — FLAG FOR THE USER:** parameter errors now render as category `validation`
  (title "Validation Error") instead of `execution_failure`; the two code-node annotation errors now fail only
  their item in a `continue` batch instead of stopping the batch. Both are user-visible output changes shipped
  under the lane's own judgment (precedent cited: #592). Reasonable on the lens; the user sees them here.
- Rule break again: `pkill -f "gh pr checks 707"` — RECURRENCE "kill by name" → **n=3** (s09 falsifier, #678,
  #627 lanes). Mechanism: lanes background a `gh pr checks` poller and then kill it by name. Promote at close with
  the mechanism, not just the ban. Four one-line test edits outside ownership (listed in PR) — accepted.
- Reconciled: #700 narrowed (http fixed; python_code sites remain) · #503 comment (engine is the only remaining
  class instance; + `batch_executor.py:1190`; serialize w/ 179; extend the ratchet) · filed **https://github.com/spinje/pflow/issues/709** (probe
  non-verbose prints `str(exc)`) · **https://github.com/spinje/pflow/issues/710** (racy empty "Executor error" line, engine, serialize w/ 179).

## [2026-10-06] 179 ESCALATED (3/5, settled answer) → resolved here: **A** — lossy-seed marker + loader guard

- Falsifier (18 promises, 16 held): C1 Critical — resume seeds from the trace JSON, so int-keyed dicts / `__` keys
  / bytes make per-iteration approval give a DIFFERENT result than an uninterrupted run (10 vs 4 vs 7), exit 0,
  no warning; W1 — a loop with bytes upstream pauses but its token can never be answered (breaks Task 171's
  pause-is-a-promise). Both predate 179 for upstream steps; 179 widens them to the headline flow → "gap you
  widen is yours". Q2 decides the direction; ruled A with four fail-closed preconditions (marker scope = the 3
  proven transformations; zero false refusals over the repo corpus or STOP; one message family; pause tests
  listed). User-visible: some non-loop resumes that silently continued now refuse — flagged for the user.
- Falsifier hygiene: `pkill -9 -f "sleep 30"` machine-wide — kill-by-name **n=4** (falsifier ×2, lanes ×2);
  the falsifier def and the lane def get the mechanism fix at close (PID-only + "never background a poller you
  then kill by name"). Filed **https://github.com/spinje/pflow/issues/711** (`loop_stopped` not restored — reproduces on main) and **https://github.com/spinje/pflow/issues/712** (dry-run footer
  wording). Follow-up 1 (restore every loop counter) stays the documented ADR-0010 limit — no observed case.
- Baseline: 179 adds no drift; the 5 new drifts after #704 also drift on untouched `origin/main` → #680's.
- 179 STOPPED on precondition 1 (as designed): a 4th lossy transformation — `_flush_line` `json.dumps(default=str)`
  (`workflow_trace.py:992`) stringifies set/date/Decimal/Path/custom objects (EXECUTED, `probeA/`); a 5th —
  `_sanitize_for_json` drops `_debug_context`/`_batch_trace` (`:1335`); correction: non-string-key coercion happens
  in `json.dumps`, not the sanitizer. Precondition-2 risk pre-empted: the engine writes its own `__` keys into node
  namespaces. RULED (3/5, Q2 settled): **Option 1** — marker = anything the trace cannot round-trip, judged on
  AUTHOR-produced values only (engine-written keys exempt: `__metrics__` `__pflow_stats__` `__pflow_warnings__`
  `_debug_context` `_batch_trace`); refusal names step + key/type + remedy (make the result JSON-native). Zero
  false refusals over the corpus stays fail-closed. The fail-closed-precondition mechanism (s08/s09) stopped a
  guess at exactly the right point again.

## [2026-10-05 22:48Z] SHIPPED Task 179 — PR #713 → `3b342ce9` (closes #659; #615/#656 Refs — verified)

- Completion handback → task-review.md READ IN FULL (the integration contract: one reader of position, `>=`
  slice, `None` ≠ 1, fold by iteration, pause-is-a-promise incl. fidelity, author-only lossy marker). Squash-merged
  after JSON-verifying every check; my superseded local edit to main's 179 spec copy was discarded (the merged
  spec carried the same note).
- Reconciled: CONTEXT.md **Resume** += loop re-entry at the Iteration + fidelity refusal; #656 comment with the
  ruling + reopen trigger; spec Status done / Completed 2026-10-06 set by the producer. Trace format **2.8.0**.
- User-visible changes shipped under rulings (for the user's eye): per-iteration pause everywhere; resume refuses
  when a restored upstream value would have been coerced by the trace (per EVENT, not per field read — a
  `datetime` beside the data a step reads blocks failure-resume; remedy printed; revisit on complaint).
- Not built by ruling: #656 button (plan §4 P4b); final-step loop escalation pause (b). Serialize behind nothing
  now — the engine seam is quiet: #690, #458, #503 (+ `batch_executor.py:1190`), #710, #711 are unblocked.

## Braindump

_Tacit residue only — rulings, ships and board state live above, in CURRENT-STATE, the PR bodies and the task-review._

**The user this session — their words, and what they did with them**

- Opened with *"im not sure of the current state"* and *"we might need to explore some"*. The exploration they
  valued most was the one the issue tracker could not have produced: a fresh-eyes agent walking `pflow guide`
  → author → run → trace → save. Seventeen filed issues from one agent for $0.00004. When they say "explore",
  run the product as a stranger before auditing the backlog — the backlog is what previous sessions already
  thought of.
- *"isnt the real fix to do 4. task 118 or?"* — the second time in two sessions they caught me proposing an
  interim without its final-shape relationship (s09: the UI button). Same tell both times: I offered the cheap
  thing with a "later" clause and never said whether the cheap thing survives the final design. Promoted to the
  role prompt at this close. The deeper shape: they read every "now vs later" split as a question about the
  FINAL code, never about effort.
- *"we shouldnt close anything that could be important"* — on issue hygiene they lean conservative; the triage
  agent's KEEP-biased rubric satisfied them. They did not re-examine the 15 closes individually; they trusted
  the rubric + my re-read. Where I pulled one back (#370), I said why in one sentence and that was enough.
- *"let me review changes locally before commiting"* arrived mid-session with 20+ files edited by me. They
  want the working tree as the review surface — grouped by purpose, not by path. I never learned whether they
  finished reading (UNCLEAR below); the close commit waits regardless.
- *"didnt you have to commit the task file updates… before launching those planners/worktrees or?"* — they
  audit process mechanics, not just outcomes (s07/s08/s09 pattern: gates ran?, lanes used astra?, falsifier
  ran?). Answering with the exact commit and the DECISIONS #5 clause satisfied them; the nuance I surfaced
  (uncommitted `.claude/` edits reach session-launched agents) they accepted without comment.
- *"I dont think the deep review skill is up to date anymore… we should be generous here and there might be
  better triggers? lets discuss"* and then *"maybe per 'module'… different reviews should focus on different
  parts or?"* — they think about review as coverage by SEAM, not by count. "Generous" meant "every relevant
  lens", not "more agents". The per-seam targeting idea was theirs; it exposed the fan-out's dropped `target`
  (#706) within an hour.
- *"go ahead and run this session end to end, when you are done and FULLY happy with no loose ends, close the
  session"* — the second grant shape in two sessions; this one came with no in/out list because the boundary
  had been set an hour earlier (*"what we have running right now is enough"*) and then explicitly widened once
  (*"go ahead with your recommendations and implement"*). Grants here compose: a boundary, a named widening, a
  drain order. Read the sequence, not the last message.
- **They did not answer the release question** — asked three times across the day (recommendation each time:
  cut v0.16.0). Not a refusal; they moved to the next topic each time. Surface it ONCE next session with the
  dogfood pass attached as the pre-release gate, then drop it until they raise it.

**Overturned or corrected, owned**

- ADR-0016's premise "the code node's body is literal Python" came from the guide's authoring rule, not the
  code — `code.code` is scanned and interpolated like every param. Third instance of writing a mechanism from a
  summary (RECURRENCE n=3). The context-free ADR review caught it in 70 seconds of reading; I had not opened
  `template_resolution.py` once. The fix is cheap and I keep skipping it under time pressure.
- "F1 is Task 120's problem" — written into the Task 120 spec from the dogfood SUMMARY before the verifier ran;
  refuted (it is mis-coercion at template resolution, #686). Spec evidence blocks written before the
  verification pass are the same failure wearing a different hat.
- The issue audit's "stale candidates" missed #437's owner comment saying it was fixed in June. My brief told
  the auditor to read bodies, not comments. The planner rule ("every issue read is TWO calls") exists because of
  exactly this and I did not carry it into the audit brief.
- The audit's "one root cause" cluster (#675/#458/#659) was the auditor's framing; I caught it before relaying.
  Clusters an agent proposes are hypotheses about mechanism — check one member's body before repeating the frame.
- FAL_KEY "the colon breaks the masking" — my own hypothesis after one look; the verifier found the real rule
  (name-word matching; bare `KEY` is not sensitive). I had the key's value in my transcript for a moment because
  my own redaction sed was wrong. Never print a settings dump without piping EVERY value through a mask.

**Mechanisms that worked — reuse them**

- **Fail-closed preconditions attached to a ruling** (s08's mechanism, now proven on a Critical): "the marker
  fires ONLY for these three transformations; a fourth STOPs you" — the implementer found a fourth and a fifth
  and stopped instead of building a guard that claimed to close the class. Without the gate, Option A as first
  scoped would have shipped beside a documented silent-wrong path. The precondition that mattered was the one
  that named the SET, not the one that said "verify".
- **Context-free review of my own process docs** (ADR, then the skill rewrite): 1 refuted premise + 7
  contradictions + a half-refuted mechanism, all real. Cost: one Opus read each. Do it for every durable doc
  born in conversation, not just ADRs.
- **Verify → draft → read → file, as a pipeline**: dogfood agent observes; a second agent re-executes each
  finding on main, dedups against open issues, drafts bodies with class + mechanism + closing mechanism; I read
  every draft and file serially. Nineteen drafts, zero rejected at my read, filed in one pass. The dedup step
  found two duplicates (B → Task 120, F "printed twice" did not reproduce) that would have become noise issues.
- **Measured file deltas to live producers when main moves**: `git diff --name-only A..B` pasted, with the one
  or two files on the producer's surface named. 179 absorbed three merges of main with zero conflicts.
- **The KEEP-biased four-criterion triage rubric** (observed? referenced by roadmap/task/open issue? security/
  data/correctness? design record with a revisit trigger?). Reusable verbatim; the "code pointer" sub-criterion
  (a source comment names the issue) is what saved #321/#334/#358/#561.
- **Publishing a checkpoint page as an Artifact** with the screenshots as files — the implementer wrote the
  page; I copied it into the scratchpad (sources must sit under the working dir or scratchpad) and published.
  The user ruled from it in one line.

**Dead ends — don't repeat**

- `pflow-codebase-searcher` agents will NOT write a report file (their def forbids it); four briefs asked, four
  came back inline. Ask for inline reports; save them yourself if a file is needed.
- `gh run list --branch main` lied again (September runs for today's commit). Unfiltered list + `headSha`.
- The worktree script's `rm` refuses a branch with no merged PR (the parked #437 lane); `rm -f` removes the
  tree but keeps the branch — delete the branch by hand after checking `git log main..branch` is empty.
- `git merge --ff-only origin/main` aborts if I edited main's copy of a spec a branch also changed. Once a task
  has a worktree, its spec is edited on the branch only (RECURRENCE n=1).
- The triage agent reported `gh issue view --comments` printing nothing in its sandbox; it fell back to JSON
  (`gh issue view N --json comments`). If a subagent says comments are empty, that is the tool, not the issue.

**Seams noticed, not yet forced**

- The engine seam went quiet at 22:48Z when 179 merged. Five lanes were serialized behind it (#690, #458,
  #503+batch 1190, #710, #711). They are now the parallel-safe wins — but #690 and #458 touch
  `resume_preflight.py`/the snapshot surface that 179 just rewrote; the lane must read 179's task-review first
  (its "serialize behind this" list names them).
- Task 118 and Task 120 both reshape how values enter nodes (118: shell `env:` binding; 120: input coercion at
  `prepare_inputs()`); #686/#687 sit between them (coercion at template resolution; lossy CLI round-trip). One
  planner should see all four before either builds, or the type story forks again.
- The lossy-seed refusal (179) and the `--only` snapshot (ADR-0002) now disagree: resume refuses what `--only`
  silently seeds. Not a bug by ruling, but the first `--only` user to hit a coerced value will file it.
- The release skill now REQUIRES a dogfood pass; nobody has run the release skill since. Its first run is its
  first test (the s08 "first run is the test" pattern).
- #706 (fan-out drops `target`) makes the per-seam review rule unauditable until fixed — land it in a quiet
  moment, and until then treat "lenses ran per seam" in a PR body as a claim, not a measurement.

**Local-only artifacts**

- `scratchpad/` of this session (`/private/tmp/claude-501/…/scratchpad/`): `issue-audit.md` (143-issue audit),
  `dogfood/report.md` + `findings.md` (verbatim commands/outputs), `dogfood-issues/` (19 drafts + `created.json`
  number map), `issue-triage/report.md`, `adr-review/report.md`, `checkpoint-656/` (the published page). If gone:
  the issues carry the executed evidence; the triage verdicts are in the issue comments; the audit tiers are
  reconstructable only by re-running the audit.
- `~/.pflow/debug/` holds ~80 trace files from the dogfood + verification runs (two contain the fake values
  `FAKE-SECRET-VALUE-123` / `FAKE-SECRET-K-999`); `~/.pflow/reports/` has `csv-report/ repo-card/ tagline-batch/`.
  Harmless; delete if tidying.
- The Artifact page https://claude.ai/artifact/NUKdFNJnq794niPxaz2Hps (private) — the #656 checkpoint evidence.

**Markers**

- UNCLEAR: whether the user finished reviewing the 23 uncommitted paths; they said *"let me review changes
  locally"* and then approved the skill fixes by description. Ask once before the close commit — do not assume.
- ASKED-NOT-ANSWERED: the release (three times). Treated as "not now", not "no".
- ASSUMPTION: the `quality` job cancellation on the morning's main run was the Actions outage (status page
  said major_outage; the same job passed on every lane PR later). Not re-run; the push CI for `3b342ce9` was in
  progress at close — the successor verifies it green at boot.
- ASSUMPTION: the kill-by-name fix in the two defs is the right HOME (trigger-point); ratification pending.
- NEEDS VERIFICATION: #92 item 2 (array-typed MCP param not JSON-parsing a string) end to end against a real
  server; #685's "cleanup exception replaces the TimeoutError" hypothesis (Windows only).

## [2026-10-06, after close] User reviewed the #656 checkpoint page → [RULING] *"yes go ahead, file the issues and then update the relevant docs"*

- User, on the published page: *"it seems like the button is only visible if you scroll down, also im not sure I
  undertstand why we dont want an accept all button?"* + *"did we file this?"* (the long-id layout note). OWNED:
  (1) the checkpoint's own screenshot showed Approve/Deny hidden below the gate panel's scroll fold and I published
  it without calling it a headline-flow bug; (2) I left the layout note as "file if you want" and never asked;
  (3) my "not now" ruling, collapsed under the grant, rested on three weak reasons — the third ("the panel doesn't
  show the limit") argued for showing the limit, not against the button. The user's lens caught it on first read.
  Lesson shape (same family as the interim rule): a checkpoint collapsed under a grant still gets SHOWN to the user
  at the next contact, and a "side note" in a producer's page that makes the primary action invisible is not a
  side note.
- Filed **#714** (gate panel: buttons below the fold; long id crowds the header; ships first). REOPENED **#656**
  with the wider scope (iteration "of N" / "of up to N" + "Approve all remaining"; the limit needs a `GateRequest`
  field from the engine's gate builder → engine contact). Docs updated: 179 spec (outcome line), 179 task-review
  (ruling reversed, pointer), CURRENT-STATE (struck from "do not re-raise", added to the next-session fill).
  The user had already committed the session doc set as `0d935987`; these four edits are uncommitted.
