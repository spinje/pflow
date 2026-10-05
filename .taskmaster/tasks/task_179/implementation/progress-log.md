# Task 179 — progress log

Append-only. Entry format: ORCHESTRATION.md → "Progress-log entry format".

## [2026-10-05 22:40] task-planner (Fable) — planning complete, plan under self-review
- Did: investigated the loop/resume/gate seams (engine, loop_control, resume_source, resume_preflight read directly;
  five parallel searchers for trace recording, pause surfaces, #659/planner, test inventory, UI/MCP), wrote
  `implementation-plan.md`, corrected the spec in place (deletion list, Q3–Q6 decided, Q2 correction resolved).
- Changed: `implementation/implementation-plan.md` (new), `task-179.md` (Design Decisions bullet, Decisions section).
- Verified: base `90b891cb` == `origin/main`; `make install` ok; Task-159 baseline `verify.sh` on this base = 79 pass /
  8 drift (6 output-`source` required-property, 1 guide wording, 1 Python-3.14 `SyntaxWarning` in
  `01-parser-errors/01-empty-cache-block` — environment); no reference to `_loop_should_reenter`/`_mark_loop_stopped`/
  `_emit_loop_cap_advisory` outside `engine.py` (grep src+tests); `_fully_answered_gate_ids` has no direct test;
  `_host_frame` has exactly four writers/readers (`workflow_executor.py:86/383/448/484`, `engine.py:1337/1593`).
  | Assumed (verify in P4): the browser auto-chains across a second pause (code reading of `selectRun` re-arm +
  `key={gateRunId}`; no vitest covers it).
- Deviations/surprises: (1) `_fully_answered_gate_ids` is correct under continuation (multiplicity, not restart) —
  spec deletion list corrected; (2) #659's issue text expects "a gate event under a fresh seq" — gate lines carry no
  seq and a 7.5 gate records no host event; the regression asserts iteration 1's event survives and the host appears
  once; (3) the escalation-gate arm double-records a `workflow` host after step 16 (same defect class as #659; from
  reading) — D1's `not originating` conjunct closes both; (4) the planner can share the engine's re-entry decision only
  if it leaves the engine class → `loop_control.should_reenter` (mechanical move, two callers).
- Self-checks: plan-mode deep-review launching now (review-plan, architecture-fit, feature-interactions,
  impact-completeness, silent-failures); outcome appended below before commit.
- Next: fold confirmed Critical findings, commit plan + spec + log on the feature branch, hand back.

## [2026-10-05 23:55] task-planner (Fable) — plan self-review folded; committing
- Did: plan-mode deep-review, five direct Opus lenses (review-plan, architecture-fit, feature-interactions,
  impact-completeness, silent-failures); evaluated every finding against code; folded the confirmed ones.
- Changed: `implementation-plan.md` (D2 `>=` slice rule, D2 `entry_iteration: None` = no recorded position, D2b fold-by-
  iteration via `iteration` on gate lines, D4 counter keying + `--force`-edit guard, D7 condition, P2a/P2b/P3 files and
  tests, §6 ledger additions, §8 user question), `task-179.md` (baseline wording: "unchanged", not "green").
- Verified: Critical findings (convergent across 4 lenses) checked by me at `resume_source.py:310-356, 650-694`,
  `engine.py:597-626, 917-966`, `runtime/engine/gate.py:228-244` — (a) the `==` slice would make `--only` on a resumed-
  attempt snapshot seed the target's own output (restored event carries iteration N−1, no `== 1` event); (b) the
  resolution fold onto the all-events final event false-refuses an at-K resume after an answered loop escalation, and
  a fold onto the SEEDED event (my first fix) would apply iteration 1's answer to an unanswered iteration-2 question
  after a Ctrl-C — pairing by iteration is the only correct shape, and resolution lines carry no `request` today, so the
  line itself gains `iteration`. | Assumed: none new.
- Deviations/surprises: three lenses independently found (b); the silent-failures lens found the second scenario that
  invalidated my first fix. A plan-mode battery earned its cost here.
- Self-checks: no Critical left open. One 3/5 question handed up (§8): the default-successor conjunct for a loop step's
  escalation on a workflow's FINAL step (plan proceeds on "keep + document"). Warnings dispositioned: all folded except
  the "engine resolves every between-nodes entry" simplification (recorded follow-up, user-visible).
- Next: commit plan + spec + log on the feature branch; hand back to the main orchestrator.

## [2026-10-05 20:30] task-orchestrator (Opus) — bootstrap + launch P1→P2b
- Did: verified worktree (`e67af2a2`, clean; `origin/main` == `90b891cb`), `make install` ok; read ORCHESTRATION.md, spec
  (incl. "Rulings at launch"), plan, log, dependency reviews (164/171 fully; 125/162/166/170/176 load-bearing sections),
  issues #659/#656/#690/#458/#680 (body + comments).
- Rulings in force (main orchestrator, settled): Q1 (c); Q2 refuse-when-unrestorable (stripped LLM prompt = strict carry
  guard, not a loader refusal); Q3–Q6 per plan §3; final-step loop escalation = (b) — keep the conjunct, `approval.md`
  states the re-fork recipe needs a step after the loop.
- #690 / #458 disposition (the spec asks): **neither is decided by Q2; both stay behind this task.** Q2 governs seed
  fidelity (what the loader can restore), not workflow-edit staleness — the plan leaves `_check_content_hash` untouched,
  so #690(2) is open. #690(1) (pre-exec failure ⇒ no re-fire) is not addressed; this task edits `_side_effect_refusal`
  (pass-through entry, plan P2b review-fold), so #690 must land strictly after this PR. #458 (`--only` inputs) is
  independent of the (step, iteration) seed — `--only` stays byte-for-byte unchanged here — and should also land after
  (same snapshot surface).
- Collision note: `core/exceptions.py` is shared with lane #627 (additive). This task's exceptions.py edit is an in-place
  TEXT change to `GateNotInteractiveError`'s remediation (not additive) — conflicts only if #627 touches that class; to
  re-check at the pre-PR `origin/main` merge.
- Launch: ONE Opus `task-phase-implementer` (effort high — P2 is resume/gate seam work) for P1 → P1 mid-task review →
  P2a → P2b → P2 mid-task review, bundled (litmus: no gate outcome between them changes my next instruction; the
  implementer runs and evaluates the mid-task lenses via the pflow fan-out itself). test-reflect pre-directed for P1 and
  P2 (subtle, easy-to-cheat tests: #659 overwrite, the `>=` slice, D2b fold, parity).
- Next: on the relayed handback — read the P1/P2 log entries, confirm gates + baseline, ask "FULLY happy?", commit.

## [2026-10-05 22:05] phase-implementer (Opus) — P0 baseline
- Did: captured the pre-change baseline on `e67af2a2` (+ the orchestrator's uncommitted log entry only).
- Changed: nothing (scratch artifacts under `scratchpads/task-179/p0-*`).
- Verified: `make test` → **10232 passed, 0 failed** (ids in `scratchpads/task-179/p0-test-ids.txt`);
  `uv run pytest tests/test_runtime/test_resume_engine.py::test_loop_k_restarts_at_iteration_one` → 1 passed (the weak
  pin, recorded so its FLIP in P2a is evidenced); `verify.sh` → `summary: 80 passed, 7 drifted, 0 harness errors`.
  The 7: `03-analyze-cache-modes/{05-trace-from-trace,06-no-trace-autoload,07-autoload-prefers-success,
  08-autoload-failed-only,09-autoload-rejected-names-file}`, `10-live-recordings/03-gemini-translation` (the 6
  output-`source` required-property drifts) and `12-real-world-lyrics-generator/04-guide-auto-detect` (guide wording).
- Deviations/surprises: (1) the plan's 8th drift `01-parser-errors/01-empty-cache-block` (Python-3.14
  `SyntaxWarning` in stderr) did NOT reproduce — environmental and flaky (likely a cold `.pyc` cache); that case runs
  first in sort order. Net for this task = the 7 named above, and 01-empty-cache-block may flicker. (2) Process slip:
  I began P1 edits about a minute into the ~2-minute `verify.sh` run, so its later cases may have run against partial
  P1 edits. The drift set equals the planner's clean-base measurement name for name (minus the flaky env case), and
  the post-P1 run below matches it, so the baseline holds. Stated, not hidden.
- Self-checks: n/a (no code).
- Next: P1.

## [2026-10-05 22:25] phase-implementer (Opus) — P1 position recorded (#659, `iteration` on loop events/gates, 2.8.0)
- Did: D1 (`not originating` conjunct on the gate arm's host-frame record), D8 (`record_trace` stamps
  `iteration=shared.get("__iteration__")` → `record_node_execution(iteration=)`, key written only when set),
  `GateRequest.iteration` (+ builder kwargs; `run_approval_gate`/`run_escalation_gate` pass `__iteration__`),
  `record_gate(iteration=)` on pause AND resolution lines (D2b's pairing key), `TRACE_FORMAT_VERSION = "2.8.0"` + history.
- Changed: `src/pflow/core/gate.py`, `src/pflow/runtime/engine/{engine.py,gate.py,instrumentation.py}`,
  `src/pflow/runtime/workflow_trace.py`, `src/pflow/runtime/CLAUDE.md` (2.8.0 paragraph);
  tests: `test_gate_trace.py` (+`TestHostFrameRecordedOnlyForChildGates` ×2, +`TestGateIterationRecorded` ×3),
  `test_emit_time_trace.py::test_loop_node_events_carry_their_iteration_and_nothing_else_does`,
  `test_gate_pause.py` (pause-record `iteration` == 1 on the loop approval, `None` on the mid-graph escalation),
  `test_trace_format_2_2.py::test_format_version_is_2_7_0` → `…2_8_0`.
- Verified: `make check` green; `make test` → **10238 passed** (baseline 10232 + 6 new; 1 renamed; 0 failed);
  `verify.sh` → `summary: 80 passed, 7 drifted, 0 harness errors`, the same 7 names as P0, nothing new.
  Mutations (Edit + restore from snapshot, counted failures): drop `and not originating` → both #659/17.7 tests fail
  (2 failed); invert it to `and originating` → both orphan pins fail too (4 failed: the child-gate half of D1);
  always stamp `event["iteration"]` (None leak) → the event-field test + all 4 `TestTraceFixtureBuilderShapeParity`
  fail; drop `iteration` from resolution lines → both loop gate-line tests fail. | Assumed: none.
- Deviations/surprises: (1) the plan's 17.7 "stretch" test was cheap, but the obvious fixture (child output `result`
  = the child step's own `result`) escalates INSIDE the child (a child gate, so the old code was already right): the
  marker must sit one level down (`${emit.result.payload}`) so only the host's exposed `result` carries it. Built that
  way and mutation-verified. (2) The 2.7.0 literals in `test_resume_list_cli.py:114` and
  `test_cache_analysis_analyze.py:7743/7751` are fixture data (any valid 2.x), left unchanged. (3) `record_node_execution`
  crossed ruff C901 (11 > 10) with the one added `if`; suppressed at the site with a coded reason (a flat run of opt-in
  field stamps, 12 precedents in `src/`), not restructured. (4) The engine CLAUDE.md sentence "A sub-workflow host must
  still close the correlation frame reserved at descent" (§6 ledger: "only for a gate that originated in its child")
  is deferred to P2b's engine CLAUDE.md rewrite, the file P2b owns. (5) `iteration: null` is in every non-loop
  `gate_request` (plan's choice, `asdict`); the gate LINE's top-level key is opt-in.
- Self-checks: fully happy, one note: `GateRequest`'s "frozen shape" (Task 171 invariant) grows additively here,
  which the ADR-0010 amendment (P3) records. test-reflect (directed): no shallow test found, none deleted; every new test
  was mutation-killed (above); the non-loop absence test is paired with presence in the same line (`request.node_id`,
  `request.iteration is None`) and in the sibling loop test; deepened the event-field test from in-memory to the
  on-disk medium (what resume reads).
- Next: P1 mid-task review (`review-impact-completeness` + `review-silent-failures`).

## [2026-10-05 22:45] phase-implementer (Opus) — P1 mid-task review
- Did: pflow fan-out (codex), `review-impact-completeness` + `review-silent-failures`, per-lens targets on the
  uncommitted P1 diff; report `scratchpads/task-179/p1-midtask-review.md` read in full.
- Verified: coverage complete (both lenses received, exit 0). **0 Critical / 0 Warning / 0 Suggestion.** Both lenses
  independently cleared the host-frame conjunct (tag set before the collector check, so child gates of all three
  exception types still close ancestor frames; no path where `originating=True` skips a reservation made this visit),
  `__iteration__` isolation (child stores, on-error routing, `--only` = 1), the opt-in key and `RESERVED_LINE_KEYS`.
  Both confirmed `_prepare_resume`'s re-record omitting `iteration` is P2a's (planned), not a P1 omission.
- Deviations/surprises: none from the review; nothing to fix. (Both lenses were read-only, so the mutation evidence
  in the P1 entry is the executed half.)
- Next: P2a.

## [2026-10-05 23:30] phase-implementer (Opus) — P2a at-K continuation
- Did: D2 (`ResumeSource.entry_iteration`, `_entry_iteration` = the one reader of the events' field; seed slice
  `>=` rule threaded `_seedable_final_events` → `seed_snapshot_into_shared(exclude_iteration=)` →
  `seed_walk_entry(entry_iteration=)`), D2b fold-by-iteration (`_apply_gate_resolutions`; the seedable map is computed
  once and handed to the paused-answer fold and the guard), D4 (`loop_counts` created before the entry, restored to
  N−1), D5 (`restored_nodes` = seeded minus the entry; the re-record loop iterates ALL seeded events and copies
  `iteration`), D6 approval half (`_gate_pausable` approval → `True`, `iteration` param gone), D7
  (`build_loop_restart_diagnostic`, INFO `resume.loop-restart`, runtime `__warnings__["__resume_loop_restart__"]` +
  planner diagnostics), planner parity (`resume_iteration` through `build_plan`; `_annotate_entry` charges
  `cap − (__iteration__ − 1)`), runner threading, `GateNotInteractiveError` text.
- Changed: `src/pflow/runtime/{resume_source.py,engine/engine.py,engine/loop_control.py (docstring),engine/plan_node.py
  (docstring)}`, `src/pflow/execution/{plan.py,runner.py,resume_preflight.py}`, `src/pflow/core/exceptions.py` (in-place
  text only); tests: `test_resume_engine.py` (FLIP `test_loop_k_restarts_at_iteration_one` →
  `test_loop_k_resumes_at_the_failed_iteration`; + carry fidelity on the tournament host shape; + old-trace restart),
  `test_gate_pause.py` (FLIP `…after_first_iteration_stays_failed` → `…pauses_with_position`, 3-attempt chain with
  resume-of-a-resume + superseded token; + real-producer D2b (1); `test_end_action_refused_by_gate_pausable` call-site
  edit), `test_resume_source.py` (+7: kill mid-iteration, failed-arm seed, keyless → None, never-ran → 1, guard on K's
  prior iteration, D2b (1) loader half, D2b (2)), `test_only_snapshot.py` (+2 self-reference pins),
  `test_plan_drift.py` (+mid-loop parity), `test_paused_cli.py` (FLIP, see deviation 3).
- Verified: `make check` green; `make test` → **10251 passed, 0 failed**. Mutations (restore from snapshot, counted):
  `>=`→`==` → exactly the resumed-attempt `--only` pin fails (1 failed, 79 passed across 3 files); fold onto the final
  event → both D2b loader pins fail + the real-producer D2b test; planner walk at iteration 1 → parity fails; planner
  `restored = list(final)` → parity fails; engine `restored_nodes = list(final)` → 2 failed; engine `loop_counts[K] = 0`
  → 5 failed. | Assumed: none.
- Deviations/surprises: (1) **Plan inconsistency, resolved toward D2's decision text:** the P2a test bullet says "a
  non-loop K (no key) → 1", but D2 states "events WITHOUT the `iteration` key → `None`", and the loader cannot tell a
  non-loop step from a pre-2.8.0 loop step without the IR. Implemented D2 literally: keyless final event → `None` (=
  "no recorded position"); the engine/planner treat `None` as 1 and only a LOOP entry emits the D7 advisory, so
  runtime behaviour is identical. I rejected a format-version check (keyless + ≥2.8.0 → 1): under P2b's runner guard
  (`entry_iteration ≥ 2` for an after-K source) a `--force`-edited workflow that added `loop:` to K would yield 1 and
  hit the `ValueError` guard instead of the preflight's clean "predates loop position" refusal. Pinned by
  `test_step_without_recorded_position_has_no_entry_iteration`. Flag for the orchestrator. (2) `resume_preflight.py`
  touched in P2a (planned for P2b): `_resolve_between_nodes_entry`'s successor substitution now also resets
  `entry_iteration=1`, because `entry_iteration` described the LAST step, not the substituted successor (else a loop
  successor of a non-loop between-nodes source would seed by the wrong step's position and emit a false advisory).
  (3) `test_paused_cli.py::test_approve_yes_on_loop_gate_answers_one_iteration_then_fails_loudly` (a P3 FLIP) failed
  at P2a (the chain now pauses), so I flipped it now to
  `test_approve_yes_on_loop_gate_pauses_each_iteration_until_done` (3 answers, effects exactly 3, tokens distinct,
  all three refuse as superseded). P3 adds the `Loop iteration N` stderr/no-#615-warning assertions; the #615 warning
  text is still printed (and now false) until P3 deletes `run.py:468-480`. (4) Planner start iteration: instead of a
  `{node_id: start}` map on `_WalkerState`, `_resolve_walk_start` returns the start iteration as a third element and
  the walk applies it to the FIRST planned node only (the resume entry is always the walk's first node) — same
  semantics, no state field. (5) Carry fidelity uses a looping `workflow` host (Task 166's tournament shape, child
  fails at round 3 of 4) rather than a code node, so it also covers "a resumed iteration re-runs the whole child".
  (6) The plan's "carried inputs resolved at N" planner assertion is pinned via `loop_iterations == cap − (N−1)` +
  the seeded `shared["k"]` (the planner's `PlanEntry` exposes no resolved params; `__iteration__` is the same state
  `is_carry_iteration` reads). (7) `src/pflow/runtime/CLAUDE.md`'s resume paragraph ("never seeds the target …
  derive restored-node lists from its returned map") is now stale; P3 owns that file's resume paragraph per the plan —
  left for P3, noted here so it is not missed. (8) `_gate_pausable`'s escalation clause still carries its loop
  conjunct with a dangling "(see above)" comment until P2b.
- Self-checks: test-reflect deferred to the end of P2 (directed for P2 as a whole; recorded in the P2b entry).
- Next: P2b.

## [2026-10-06 00:20] phase-implementer (Opus) — P2b after-K continuation, escalation clause, preflight
- Did: D3 — `_loop_should_reenter`/`_mark_loop_stopped`/`_emit_loop_cap_advisory` moved verbatim to
  `loop_control.should_reenter`/`mark_loop_stopped`/`emit_loop_cap_advisory` (no residue in `engine.py`: grep src+tests
  empty); the after-K decision is ONE module-level function `engine.continue_after_step` (should_reenter → K, else the
  default successor, else `ResumeNotResumableError`) with two callers, `_prepare_resume` (ctor `resume_after`) and the
  planner's `_resolve_walk_start`; `restored_nodes`/`resume_entry_node` derive from the decided entry. D6 escalation
  half (`_gate_pausable` keeps code/`end`/successor conjuncts; docstring names the mirrors and ruling (b)). Preflight:
  loop arm removed from the refusal ladder; after the successor check a loop step passes through unchanged, or refuses
  "the saved run predates loop position" when `entry_iteration is None`; `_side_effect_refusal` checks
  `entry_node_id or last_completed_node_id` (W1). Runner: the two guards + two kwarg blocks fold into
  `_check_resume_entry` + `_resume_kwargs` (between-nodes source reaches the engine only with `entry_iteration >= 2`).
  Engine mutual-exclusion covers all three entry targets. `GateNotInteractiveError` text drops "loop-". Engine
  CLAUDE.md: Find-the-owner row, gate control flow (eligibility + the #659 host-frame sentence deferred from P1).
- Changed: `src/pflow/runtime/engine/{engine.py,loop_control.py,CLAUDE.md}`, `src/pflow/execution/{plan.py,runner.py,
  resume_preflight.py}`, `src/pflow/core/exceptions.py` (text only); tests: `test_gate_pause.py` (FLIP
  `test_loop_node_escalation_stays_failed` → `…pauses_with_position`; + `EscalateUntilDecidedNode`;
  + `TestResumeAfterLoopStep` ×2 (falsy exit, cap exit); + `test_escalation_pause_mirrors_the_preflight` ×5),
  `test_paused_cli.py` (+ re-fork recipe e2e), `test_resume_cli.py` (FLIP `test_between_nodes_loop_node_refused` →
  positioned passes through / unpositioned refuses / no-exit-successor refuses; + killed-between-iterations CLI e2e
  incl. W1 confirmation), `test_plan_drift.py` (+ after-K parity ×2), `test_resume_engine.py`
  (`test_engine_rejects_resume_from_with_only_node` → parametrized over the three target pairs).
- Verified: `make check` green; `make test` → **10266 passed, 0 failed** (P0 10232: +34 net; every P0 test id still
  present except the 5 renamed FLIPs + the one parametrized rename — no test deleted without replacement). Mutations
  (restore from snapshot, counted): `continue_after_step` never re-enters → 5 failed; loop conjunct back in
  `_gate_pausable` → 5 failed; preflight refuses every loop → 4 failed; side-effect check on `entry_node_id` only →
  the kill-between e2e fails; runner guard drops `entry_iteration >= 2` → both runner/planner reject pins fail;
  `_entry_iteration` off-by-one each way → 10 failed / 8 failed. **Real surface** (`uv run pflow`, `</dev/null`,
  isolated HOME, `scratchpads/task-179/smoke1/`): run → exit 4 (iteration 1 preview) → `resume --approve yes` ×3 →
  exit 4, 4, 0; effects file exactly `effect 1/2/3`; the superseded middle token refuses "A newer attempt exists".
  | Assumed: none.
- Deviations/surprises: (1) `continue_after_step` is a shared module-level function, not an engine method + planner
  copy as first written — the plan says "the planner calls the SAME should_reenter"; folding the successor routing too
  removed a duplicated refusal message (the `seed_walk_entry` pattern). (2) The runner pins
  `test_runner_rejects_unresolved_entry_node` / `test_planner_rejects_unresolved_entry_node` did NOT need the planned
  FLIP to `last_completed_node_id=None`: with `ResumeSource.entry_iteration` defaulting to 1 their existing source IS
  the "unpositioned between-nodes source skipping the preflight" the plan wanted closed — kept as the bypass pins
  (mutation-verified), docstring refreshed. (3) The kill-between test needed a step AFTER the looping host: under
  ruling (b) a final loop step keeps the no-successor refusal — confirmed by the new
  `test_between_nodes_loop_node_without_exit_successor_refused`. (4) The re-fork e2e uses the guide's exact shape
  (self-reference `${impl.result.escalation.decision ?? ""}`, no `carry:`) rather than the plan's carry wording — it is
  the documented recipe the spec's verification row names. (5) The kill-between and W1 tests are one CLI e2e: a
  looping `workflow` host cut after iteration 2 (a host emits no `node.start`, so a mid-iteration kill reads the same).
  (6) The #615 warning still prints "answers only the first iteration … later iterations fail" — now false; P3
  deletes it (`run.py:468-480`). (7) Planner's `should_reenter` writes `loop_stopped`/cap advisory into its scratch
  store only (docstring says so).
- Self-checks: fully happy with the mechanism; one note for P3: `src/pflow/runtime/CLAUDE.md`'s resume paragraph is
  stale (P2a deviation 7). test-reflect (directed, P2a+P2b): every new/flipped test was mutation-killed (counts above
  and in the P2a entry) — none shallow, none deleted; deepened: the replacement pin and loader tests were run against
  BOTH off-by-one directions of `_entry_iteration` (10/8 failures); the D2b fold has a real-producer pin beside the
  synthetic ones; the after-K exit tests assert exact `completed_nodes == ["after"]` (the "K did not run again"
  absence is the exact list, paired with `after`'s presence); the stale-token assertion in the CLI chain was
  tightened from an `or` hedge to the exact superseded message.
- Next: P2 mid-task review (`review-feature-interactions` + `review-validation-consistency`).

## [2026-10-06 00:55] phase-implementer (Opus) — P2 mid-task review
- Did: pflow fan-out (codex), `review-feature-interactions` + `review-validation-consistency` on the uncommitted P1+P2
  diff; `scratchpads/task-179/p2-midtask-review.md` read in full; coverage complete (both lenses, exit 0). 5 findings,
  each verified against code; 4 fixed, 1 skipped.
- Findings and dispositions:
  1. **Convergent (validation-consistency Critical C1 / feature-interactions Warning 3) — after-K decision ran without
     `${__iteration__}`** (the walk keeps it set across its decision; `while: ${__iteration__}` read falsy → early exit;
     a `max_iterations: ${__iteration__}` cap raised). Verified by reading `_run_inner` vs `continue_after_step`.
     **FIXED**: `continue_after_step` installs the completed iteration (`loop_counts[K]`) for the decision and pops it
     before the entry runs. One function, so engine and planner both. Pin:
     `TestResumeAfterLoopStep::test_decision_sees_the_completed_iteration` (mutation: drop the install → 1 failed).
  2. **Critical (feature-interactions C1) — approval after a recovered failure resumed the wrong iteration.**
     Reproduced with a real producer before fixing (K fails at 3 → on-error H → explicit-action back edge to K → gate
     pauses at 4; the loader derived 3, seeding K's iteration 2 without H). This is the shape plan §8 listed as a known
     exotic mismatch ("if it ever matters, prefer the pause record for paused approvals"). **FIXED differently from
     that note, in the one derivation:** `resume_iteration` (renamed from `_entry_iteration`, now public) treats a
     failed final event that a later success/cached event recovered as "the walk moved past it" → `iteration + 1`.
     Kind-independent, and it also covers a KILL after recovery (dangling `node.start` of K at 4), which a
     pause-record override for approvals would miss; the unrecovered terminal-failure shapes are unchanged (the
     failed arm's root has no later success by definition). Pins: real-producer
     `test_approval_after_a_recovered_failure_resumes_at_the_gated_iteration` (entry 4, live `[("k", 4)]`, H restored,
     next pause at 5; mutation: drop `and not recovered` → 1 failed) + loader
     `test_unrecovered_failure_reruns_its_iteration_even_with_a_failed_handler_after` (a later FAILED handler is not a
     recovery → 3).
  3. **Warning (feature-interactions W2) — preflight reset a re-visited loop successor to iteration 1** (`K(loop) → H →
     K` back edge, killed after H): my P2a `entry_iteration=1` reset was too blunt. **FIXED**: the substitution derives
     the successor's own position, `resume_iteration(source.events, successor)` (1 when it never ran). Pin:
     `test_between_nodes_successor_that_already_ran_continues_its_own_position` (3 after two iterations; 1 when
     never ran; mutation: constant 1 → 1 failed).
  4. **Warning (validation-consistency W1) — the planner's after-K cap advisory never reaches `Plan.diagnostics`.**
     **SKIPPED**: plan §4 P2b decides it ("the planner's `should_reenter` call writes `loop_stopped`/an INFO advisory
     into the PLANNER's scratch store only (not surfaced) — acceptable"); the `continue_after_step` call site says so.
     Cheap to surface if the orchestrator wants it (copy `shared["__warnings__"][K]` into the plan's diagnostics after
     the decision) — flagged, not done unilaterally.
  5. (Verified-clean sections of both lenses: no action.)
- Verified: `make check` green; `make test` → **10270 passed, 0 failed**; `verify.sh` → `summary: 80 passed, 7 drifted,
  0 harness errors`, the same 7 as P0/P1.
- Deviations/surprises: (a) Finding 2 overrides plan §8's "noted, not engineered" with a remedy the plan did not name;
  reasoning above. Flag for the orchestrator. (b) The reviewer's claim that the validator supports backward edges
  holds only with an explicit `action` on the back edge (`data_flow.build_execution_order`); an action-less back edge
  is a "Circular dependency" validation error. (c) **Correction to my P2b entry:** the P0→P2 test-id diff removed 7
  ids, not "5 + 1": 5 FLIPs (`…answers_one_iteration_then_fails_loudly`, `…loop_node_refused`,
  `…after_first_iteration_stays_failed`, `…loop_node_escalation_stays_failed`, `…restarts_at_iteration_one`), the
  parametrized `test_engine_rejects_resume_from_with_only_node`, and P1's `test_format_version_is_2_7_0` rename — every
  one replaced (`scratchpads/task-179/p{0,2}-test-ids.txt`).
- Self-checks: test-reflect applied to the 4 new tests (each mutation-killed above; the successor test pairs the
  re-visited case with the never-ran case in one test).
- Next: hand back P0–P2 to the orchestrator; P3 not started.

## [2026-10-06 01:10] task-orchestrator (Opus) — P0–P2 handback verified; committing
- Verified (my own runs): `make check` exit 0; `make test` 10270 passed, 0 failed (P0 baseline 10232; the seven removed
  ids are all replaced, per the 00:55 entry). Grep: no `_loop_should_reenter`/`_mark_loop_stopped`/
  `_emit_loop_cap_advisory` anywhere in src/tests; `_gate_pausable` has no loop clause (approval → True; escalation keeps
  code/`end`/successor, the successor conjunct citing ruling (b)). Baseline net: 80/7, same 7 names at P0, P1 and P2 —
  the 8th (Python-3.14 warning) is environmental and did not reproduce; the bar stays "no new drift".
- Dispositions of the implementer's flags (all importance ≤2, reversible — decided here, not escalated):
  (1) keyless final event → `entry_iteration None` (D2's decision text over the P2a test bullet) — ACCEPTED; runtime
  identical, and it keeps the preflight's "predates loop position" refusal reachable under `--force` edits.
  (2) recovered-failure fix in `resume_iteration` (plan §8 "noted, not engineered") — ACCEPTED: reproduced against a real
  producer before fixing, the fix lives in the one derivation, and unlike §8's pause-record idea it also covers a kill
  after recovery; the unrecovered terminal-failure shape is unchanged by construction.
  (3) planner after-K cap advisory not surfaced in dry-run — SKIP stands (plan §4 P2b accepts it; INFO only).
  (4) `continue_after_step` as one module-level function with two callers (engine + planner) — ACCEPTED (the
  `seed_walk_entry` pattern; removes a duplicated refusal).
  (5) P3 test flipped early + preflight touched in P2a — fine (forced by the behaviour change).
- Next: commit P1+P2; resume the implementer with "FULLY happy?" (post-review fixes), then P3.
