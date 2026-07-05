# Task 171 Implementation Progress Log

> Companion documents — read in this order, no content is repeated between them:
> 1. `task-171.md` (spec — WHAT and WHY; its Design Decisions banner points here)
> 2. `implementation/implementation-plan.md` (HOW — full file:line-anchored specification,
>    deep-review fixes already folded in; this is the build contract)
> 3. This log (WHEN/WHO — session chronology, decision provenance, state at handoff)
> 4. `starting-context/braindump-2026-07-05-planning-session.md` (tacit knowledge — dead ends,
>    trust calibration, traps the plan's text alone won't protect against)

## 2026-07-04 — Session start: brief + canonical docs + baseline

- Read the launch brief (`scratchpads/task-171-durable-resume/BRIEF.md`), the spec, and the 164
  review directly; fanned out 3 `pflow-codebase-searcher` agents for the 125 gate seam, the
  resume-loader surfaces, and the ADR/braindump rationale.
- **Baseline captured**: `test_resume_source.py` + `test_resume_engine.py` + `test_resume_cli.py`
  + `test_plan_drift.py` → **165 passed** (8.66s). Branch confirmed on main `2e2eb9e8`.
  Full-suite reference from 164 close: 8489 passed. NO code has been written — the working tree
  at handoff contains only doc changes (CONTEXT.md, spec banner, plan, this log, braindump).
- Key research discovery that shaped everything: a non-TTY gate TODAY already writes the full
  `GateRequest` to disk and finalizes `failed`; `load_resume_source` already *recognizes*
  gate-stopped runs (to refuse them). 171 flips a refusal into an arm, not builds a system.

## 2026-07-04 — Owner decision session (the 5 open decisions)

Owner answered via interactive questions; recorded in the spec's Design Decisions banner +
plan's Decision Ledger. Provenance notes only:
- Decisions 1 (paused-on-trailer) and 3 (escalation restore+fold) accepted as recommended.
- Decision 2 (trace source): owner's simplicity lens ("simplest FINAL code") **changed my
  recommendation mid-session** — the spec's option (a) auto-enable was beaten by option (c)
  delete-the-MCP-special-case, which the spec never listed. Owner confirmed (c).
- Decision 3 initially confused the owner; re-explained in plain language (the "10-minute agent
  step" framing) before they chose. If this resurfaces in review, that framing worked.
- Decisions 4 (exit 4) and 5 (trust-local-fs) were low-stakes recs, proceeded + recorded.

## 2026-07-04 — CONTEXT.md updated inline

Added **Paused**, **Resume token**; extended **Resume**; added **Paused vs Denial** ambiguity
entry. Done during the session per start-work protocol — do not re-add at ship time, just
re-read for drift.

## 2026-07-05 — Plan hardened for isolated implementation

Owner directive: plan must be implementable by an isolated agent with zero ambiguity. Fanned out
4 more searchers (engine/collector seam, CLI surfaces, loader/list mechanics, MCP blast radius).
Every "verify-at-edit-time" item from the first draft was resolved and folded in. Discoveries
that changed the plan (details live IN the plan, listed here for provenance):
- `--approve yes` = existing `auto_approve` set; only deny is a new resolver param.
- No side-effect confirm needed for ANY paused resume (entry node never ran) — simplification.
- Denied attempts wouldn't consume the token (zero-step trap) → consumption clause (a).
- `WorkflowTraceCollector.trace_path` doesn't exist; MCP's `hasattr` guards are always-False
  (pre-existing latent bug, fix included in scope).
- The "ADR-0008 says trace streaming is CLI-only" claim in mcp_server/CLAUDE.md is a
  MISATTRIBUTION — ADR-0008 supports any-run streaming; the CLI-only rule was a Task-172
  code-comment scoping decision. Our change aligns WITH the ADR.

## 2026-07-05 — Deep review (plan mode, 5 agents) + fixes folded

Battery: review-plan, review-silent-failures, review-impact-completeness,
review-feature-interactions, review-agent-ux. Verdict: **ship** after fixes; all confirmed
findings are ALREADY FOLDED into the plan (each marked "deep-review" inline). Inventory with
disposition — the fixes themselves are specified in the plan, not here:
1. **Critical (interactions)**: producer paused loop/code/terminal escalations the resume path
   refuses → `_gate_pausable` at the engine arm. CONFIRMED, folded (plan 1a).
2. **W (silent-failures)**: parent/child node-id collision falsely pauses a child gate.
   CONFIRMED — **different fix than the agent proposed**: agent suggested `host_frame is None`
   (leaves the batch-hosted collision open); I verified only 2 `WorkflowEngine(` sites exist and
   replaced the id-match heuristic entirely with `nested=True` flag + first-seen exception tag
   (plan 1a). If an implementer wonders why not host_frame: that's why.
3. **W (review-plan + silent-failures, converged)**: `config` not in scope in
   `_exception_to_result`; the `trace_enabled` conjunct is the ONLY `--no-trace` bogus-token
   defense. CONFIRMED, folded (plan 1c).
4. **W (review-plan)**: first-node pause invisible to by-name selection. CONFIRMED — **different
   fix**: consumption clause (b) `paused ⇒ consumed` instead of a selection-rule special case;
   also closes a chain-fork hole no agent had named (plan 3c).
5. **W (impact)**: `RunProgress.runBadgeStatus` renders paused as green ✓ (verified reachable —
   regression vs the pre-171 failed badge). CONFIRMED, folded (plan Phase 4).
6. **W ×3 (agent-ux)**: text output must render gate content; paused JSON needs
   `errors`/`diagnostics` arrays; group help must enumerate flags hidden by the subcommand.
   All CONFIRMED, folded (plan 1d, 3a).
7. ~14 suggestions adopted (version-assert test, CSS, defensive arms, `(exit 4)` in-band,
   fall-through normalization, list hints, `--no-trace` naming, threading/label-mapping notes,
   dry-run pin, contradictory-flag UsageError, doc staleness). One UX finding (wasted `--choose`
   on final-step pause) became MOOT by construction via fix 1.
8. Disputed: none. Errored agents: none — all five returned; their clean-verified areas are
   listed at the end of the plan review summary (extraction fan-out, trailer round-trip,
   version gates, MCP test sweep, batch/only/nested/caching interactions).

## 2026-07-05 — Orchestration map added to the plan (owner-approved)

Owner discussed phase sizing / model tiers / agent-handoff seams; the agreed map is recorded in
the plan ("Orchestration map" section, before Phase 0) — including the do-not-split rule for
Phases 2+3 and the optional Phase-4 parallel lane.

## State at handoff

- **Done**: planning complete; 5 decisions settled + recorded; plan deep-reviewed with fixes
  folded; CONTEXT.md updated; baseline captured.
- **Not started**: ALL code. First action = plan Phase 0 (loader extraction, own commit).
- **Uncommitted files** (nothing has been committed — repo rule: never commit unless told):
  `context/CONTEXT.md`, `.taskmaster/tasks/task_171/task-171.md` (banner),
  `implementation/implementation-plan.md`, this log, the braindump.
- **Update this log as you work** — phase gates, deviations from the plan (with rationale),
  mutation-test results (which pin failed under which mutation), and the baseline deltas
  (165 / 8489) at each gate.

## 2026-07-05 — Phase 0 implemented (loader extraction) — DONE, awaiting human review

Extracted the resume loader from `runtime/workflow_trace.py` into a new
`runtime/resume_source.py`. Zero behavior change; own (uncommitted) change set.

**What moved** (verbatim, one cluster so the ONE `_seedable_final_events` derivation stays
shared by seeder + guards): `ResumeSource`, `_is_trace_locked`, `_iter_raw_trace_lines`,
`_read_trace_meta_line`, `_dangling_top_level_starts`, `_attempt_consumed_work`,
`_raise_resume_source_missing`, `_select_resume_trace`, `_seedable_final_events`,
`_apply_gate_resolutions`, `_contains_binary_placeholder`/`_BINARY_PLACEHOLDER_RE`,
`_raise_gate_stopped_or_generic`, `_terminal_failure_root`, `_resolve_resume_entry`,
`_resolve_incomplete_entry`, `_guard_seed_scope`, `load_resume_source`, `_SNAPSHOT_RESERVED`,
`seed_snapshot_into_shared`, and the "Resume loader" header comment.

**What stayed** (shared infra / non-resume): `_iter_workflow_traces` (cache-analysis autoload
co-consumer — its no-`final_status`-filter invariant untouched), `_trace_recency_key`,
`final_events_by_node`, `_unrecovered_failed_node_ids`, `load_snapshot_or_raise`,
`load_full_run_events`, the collector, `_HostFrame`, `_LLMSummaryAccumulator`.
`resume_source.py` imports those four helpers back from `workflow_trace` — no cycle
(`workflow_trace` never imports `resume_source`). `runtime/` still never imports `ui/`
(duplicated `_is_trace_locked` came along, docstring intact).

**Import redirects** — the plan's fan-out was exact, plus ONE it missed:
- Production (4): `engine.py:571` (`seed_snapshot_into_shared`), `resume.py:32` + `:90`
  (`ResumeSource` TYPE_CHECKING, `load_resume_source`), `runner.py:36` (`ResumeSource`
  TYPE_CHECKING). `engine.py`'s `seed_walk_entry` was already a lazy in-function import —
  re-pointed to `resume_source`.
- Tests (5): `test_resume_engine.py`, `test_resume_source.py`, `test_plan_drift.py`,
  `test_resume_cli.py` (2 sites) — all named in the plan. **Plan miss:**
  `test_only_snapshot.py:30` imports `seed_snapshot_into_shared` (not in the plan's test
  fan-out — the plan's grep keyed on "resume" and this one is an `--only`/seeder test). Split
  its import too. Mixed-symbol import lines (moved + stayed) were split, not blindly redirected.
- Two stale PROSE pointers fixed for accuracy (not imports, not logic): `runner.py:126`
  docstring and `test_only_snapshot.py:564` comment (`workflow_trace.py` → `resume_source.py`).

**Unused imports removed from `workflow_trace.py`**: `NoReturn`, `Iterable`, and 7 `Resume*`
exceptions (kept only `OnlySnapshotMissingError`, still used by `load_snapshot_or_raise`).

**Mechanics note**: the 608-line excision was done by a verified line-range script
(scratchpad `excise.py`, boundary asserts on 10 anchor lines) rather than a 535-line exact-match
Edit — safer and reviewable. Both seams left at PEP8 two-blank spacing.

**Gates**:
- Baseline (pre-change): 4 resume suites = 165 passed. Post-change: 165 + `test_only_snapshot`
  32 = **197 passed**.
- `make check`: fully green (ruff, format, mypy 246 src files, deptry). ZERO test-logic edits
  beyond import paths.
- Mutation-verify (Edit + revert, never stash): re-forked the engine's `_run_only_snapshot`
  seed (`shared[_nid]["_mutation_probe"]=True` after `seed_walk_entry`) →
  `test_engine_and_planner_walk_entry_state_match` failed ALONE at the seeded-VALUES equality
  assert (line 2542). Reverted; test green; probe confirmed gone. The parity net still bites
  post-move.
- `make test`: 8583 passed, 1 failed — `test_cache.py::test_get_latest_for_node_returns_newest_entry`,
  a `time.sleep(0.01)` timestamp-ordering test in the SQLite cache that collides under `-n 4`;
  passes in isolation. Pre-existing flake, unrelated to this change (touches no cache code).
  Effective: **8584 green**.

**Handoff (plan's "After Phase 0 (strong)" seam)**: the `workflow_trace.py:NNN` refs in the
plan's Phases 1-3 now describe the PRE-extraction file — dead offsets. Re-grep symbol names in
`resume_source.py` before Phase 2/3. Nothing committed (repo rule).

### Post-review follow-ups (same session, owner-requested)

Fidelity double-check before these: reconstructed the moved line-ranges from git HEAD and
diffed against `resume_source.py` — **byte-identical (30304 chars, empty diff)**. Swept for
string-path `patch()`/`monkeypatch`/attribute access at the old location — none.

1. **CLAUDE.md location-accuracy fix (`runtime/CLAUDE.md`)** — the extraction split symbols
   across two files; fixed only the two spots that assert WHERE they live (not the Phase-5
   module section, deliberately): added a `resume_source.py` line to the File Structure map
   (naming `load_resume_source`/`seed_snapshot_into_shared`), corrected the `--only` bullet
   heading (finders stay in `workflow_trace`; seeder + loader moved), and the closing
   engine-import sentence (`runtime.workflow_trace` → `runtime.resume_source`). Task spec's
   "extract FIRST … ~400 lines beside the collector" left as-is (historical pre-impl directive,
   not misleading).

2. **Flaky cache test fixed (`test_cache.py::test_get_latest_for_node_returns_newest_entry`)** —
   root cause: two sub-10ms `put()`s + `time.sleep(0.01)` left recency ordering to `time.time()`
   resolution; `get_latest_for_node` orders `created_at DESC` with NO tiebreaker, so a tie
   (coarse clock) or backward step under `-n 4` returned the older row. Fix = make the test
   clock-independent via the file's own explicit-`created_at` idiom (the TTL tests already do
   this), offsets within the 24h TTL; strengthened the final assert (`== now - 5` vs
   `isinstance float`). Deliberately did NOT change production `cache.py` ordering in this
   extraction diff — a `created_at DESC, rowid DESC` tiebreak would be a legit real-world
   hardening (deterministic recency on ties) but is out of scope here; flagged for the owner.
   Verified: 20/20 hammer runs pass; full `make test` = **8584 passed** (flake gone).

3. **New HIGH-VALUE test — `test_import_hygiene.py::test_runtime_does_not_import_ui`.** Not
   coverage-chasing: it guards the `runtime/ ↛ ui/` invariant that (a) is the reason
   `_is_trace_locked` is DUPLICATED (I just relocated that duplication into `resume_source.py`),
   (b) the plan's "Invariants that must survive" list names, (c) Phase 1/3 will be tempted to
   violate (the plan orders `resume list` to DUPLICATE `ui/run_tailer` logic, not import it),
   and (d) **no existing test can catch** — a `runtime→ui` import passes every test because the
   UI deps (Starlette) are installed in the test env; it breaks only headless/MCP/minimal
   installs the suite never simulates, and inverts the layering (`ui/server.py` imports
   `from pflow.runtime import compile_workflow`). AST scan over `src/pflow/runtime/**`, mirroring
   the file's existing `test_no_src_package_imports`; catches module-level, lazy, and
   TYPE_CHECKING forms. Mutation-verified (Edit + revert): injected a lazy
   `from pflow.ui.run_tailer import is_trace_locked` into `resume_source.py` → the test failed
   naming the exact site; reverted; `resume_source.py` re-confirmed byte-identical to HEAD.
   Full `make test` = **8585 passed**.

   Considered but NOT added (respecting "don't optimize for coverage"): a behavioral test that
   `_iter_workflow_traces` never filters `final_status` — second-tier (the risk is real per its
   docstring, but cache-analysis autoload tests already exercise the failed-bucket path). And no
   shallow tests were found among what this task touched (the resume suites run real workflows
   through `WorkflowRunner`; the rewritten cache test asserts the real created_at contract).

4. **Production hardening — `get_latest_for_node` rowid tiebreak (owner-requested).** Both
   ORDER BY arms in `get_latest_for_node_with_cache_key` now read
   `ORDER BY created_at DESC, rowid DESC LIMIT 1`. `created_at` is a wall-clock `time.time()`
   stamp; two writes can tie (coarse clock) or invert (NTP step), leaving "newest" ambiguous —
   SQLite then returns an arbitrary tie row (empirically the OLDER one: the
   `idx_node_id_created_at` index orders a tie by rowid ASC). rowid is the monotonic insertion
   counter, so the last-WRITTEN entry wins — the planner's "most recent run" contract. This is
   the root-cause fix for the flake class (§2 fixed the test; this makes production
   deterministic too). Pinned by new test
   `test_get_latest_for_node_breaks_created_at_ties_by_insertion_order` (forces an exact
   created_at tie, asserts the newer insert on BOTH the node-only and workflow-scoped arms);
   mutation-verified — stripping the tiebreak makes it fail returning the older row. Full
   `make test` = **8586 passed**.

## 2026-07-05 — Phase 1 implemented (producer: paused trailer, PAUSED status, exit 4, MCP flip)

Phase 0 was committed by the owner (`a8066f15`) before this session. Baseline re-confirmed:
4 resume suites = 165 passed on a clean tree.

**Plan re-verification deltas** (plans are point-in-time; code is truth):

1. **REAL BUG in the plan's 1a snippet — `action` is unbound at the gate arm for approvals.**
   The plan claims "_gate_pausable's approval early-return keeps the arm safe at step 7.5
   where `action` is not yet assigned" — but Python evaluates call ARGUMENTS eagerly, so
   `_gate_pausable(..., action)` raises `UnboundLocalError` inside the except arm for any
   approval gate (raised at step 7.5; `action` is first assigned at step 9). Fix: bind
   `action: Any = None` in `_execute_node`'s existing pre-try defaults block (engine.py,
   beside `host_frame`/`start_frame` — same established pattern), with a comment explaining
   why. Side effect: the explicit `Any` surfaced mypy's pre-existing looseness on the happy
   `return action` — suppressed with `# type: ignore[no-any-return]` + comment.
2. **Plan's "batch-HOST approval → pauses (fires at 7.5 in the root engine)" is UNPRODUCIBLE.**
   `approval:` on a batch step is rejected at compile/validation by
   `check_approval_allowed` (core/workflow/gate_validation.py, Task 125 — the preview would
   show unresolved `${item}` templates). Dropped the planned test; the arm's
   originating/nested logic is unaffected. The plan's reasoning bullet stands as dead
   reassurance only.
3. Everything else verified as written: exactly 2 `WorkflowEngine(` sites; `PythonCodeNode`
   class name; `node.successors` is a plain dict; GATE_KIND constants; `parallel_batch` only
   on GateNotInteractiveError; `record_gate`'s writes precede the arm; `_exception_to_result`
   signature/call-site as the plan's W1 note says.

**What was built** (per plan 1a–1f):
- Engine (1a): `nested: bool = False` on `WorkflowEngine.__init__`; `nested=True` at the ONE
  child site (`workflow_executor.py`); gate arm rewritten — first-seen `_pflow_gate_seen` tag,
  `originating ∧ not nested ∧ not parallel_batch ∧ _gate_pausable(...)` → `gate_outcome=
  "paused"` + `pause_request` stash; module helper `_gate_pausable` with per-clause comments
  mirroring the CLI refusal arms.
- Collector (1b): `pause_request` field; `paused` arm in `_determine_trace_status` (between
  denied and failed); `_aggregates` emits `paused_node_id`+`gate_request` on the trailer (with
  the atomicity-stance comment); `TRACE_FORMAT_VERSION` 2.6.0 → **2.7.0** (+history comment,
  exact-match test updated); `trace_path` property (fixes the always-False MCP `hasattr`
  latent bug).
- Status/runner (1c): `WorkflowStatus.PAUSED` (+exit-4 docstring); `_exception_to_result`
  gains keyword-only `trace_enabled` threaded from the sole call site; three-way status
  mapping with the both-gates-required comment.
- CLI (1d): PAUSED branch in `_display_execution_result` (exit 4); `_durable_pause` (reads
  `_stream_failed`, cites the `_resumable_execution_id` precedent); `_display_paused_result`
  (stdout token line with in-band `(exit 4)`; stderr gate content + exact answer command; JSON
  doc with REQUIRED empty `errors`/`diagnostics`; preview masked with the denied-doc policy);
  stream-fault fall-through normalizes status to FAILED via `dataclasses.replace`;
  `_maybe_echo_resume_hint` paused early-return.
- Gate rendering seam (1d prerequisite): `execution/gate_prompt.py` gains
  `format_gate_lines(gate_request_dict)` (ONE render shape: approval = masked preview;
  escalation = question + numbered options, labels via the same extraction the prompt's
  digit-answer uses) and `format_resume_answer_command` (kind→verb pairing, single home) —
  `_echo_options` refactored onto the shared `_format_option_lines`. Both are what Phase 2's
  `ResumeAnswerRequiredError` should reuse.
- MCP (1e): `RunnerConfig()` (streams; registry probe stays traceless); paused branch returns
  `_format_paused_text` (grep-parseable `key: value` scalars + rendered gate + resume_command)
  instead of raising; `_trace_path_str` helper folds the four always-False `hasattr` sites;
  success dict + text gain `execution_id` (+ real `trace_path` line in
  `format_success_as_text` — MCP-only renderer).
- Stale messages (1f): `GateNotInteractiveError.to_diagnostics()` suggestion replaced (names
  `--no-trace` as the removable blocker + the unsupported positions); gate_prompt module
  docstring notes the durable-pause path.

**Behavior-change test updates** (3 tests encoded the pre-171 contract):
- `test_gate_trace.py::test_noninteractive_gate_trailer_says_failed_not_success` → renamed
  `..._says_paused_not_success`, asserts the pause record round-trips the trailer.
- `test_resume_engine.py::test_non_interactive_gate_stop_refuses_naming_the_gate_e2e` →
  renamed `..._pauses_and_loader_refuses_pending_answer_e2e`; the top-level scenario now
  trails `paused`; INTERIM (Phase 1) the loader refuses via the generic not-resumable arm —
  the docstring marks it for a Phase-2 update to `ResumeAnswerRequiredError`. The original
  `ResumeGateStoppedError` chain stays covered via a NEW child-gate test (below) — that path
  is still real for gate stops that remain `failed`.
- `test_resume_cli.py::test_gate_stopped_run_omits_resume_hint` → renamed
  `test_gate_paused_run_omits_failure_resume_hint`; exit 4; asserts the failure-resume hint
  is absent and the answer affordance replaces it.

**New tests**: `tests/test_runtime/test_gate_pause.py` (producer battery: mid-graph escalation
pauses with full payload; code/loop/terminal escalations stay failed; "end"-action clause
unit-pinned — no non-code node can produce it in a real graph; ★id-collision child gate;
parallel-batch child gate; has_resumable_step pin; child-gate ResumeGateStoppedError chain;
torn-trailer degradation → incomplete → 164 resume). `tests/test_cli/test_paused_cli.py`
(exit 4 + parseable token resolving to a real trace file; secret-masked gate content on
stderr; `-p` keeps token; JSON doc shape incl. masked preview + empty errors/diagnostics;
`--no-trace` → exit 1 + message naming the flag). `test_gate_prompt.py` gains
`TestPausedGateRendering` (format_gate_lines parity with the prompt rendering; kind→verb
command pairing). `test_execution_workflow.py` (MCP) gains `TestExecuteWorkflowPaused`
(paused text carries token/resume_command/gate content; auto-approve still succeeds; success
text carries execution_id; ★real streamed+finalized trace file under trace_files).

**Escalation test-node note**: mid-graph non-code escalations need a node that writes
`result.escalation` — no core non-code node does in tests (code nodes are refused by
`_gate_pausable` by design), so `test_gate_pause.py` registers a local `EscalatingNode`
(registry-injection pattern from `test_compiler_integration.py`). The plan's "escalation on a
plain mid-graph node → `--choose` succeeds" parity pin is HALF-covered here (producer emits
the token); the resume-accepts half needs Phase 3's `--choose` — flagged in the test class
docstring.

**Two more pre-existing tests updated to the new contract** (found by the full-suite gate):
- `test_cli_mcp_parity.py::test_mcp_gated_workflow_fails_loudly_with_remediation_ladder` →
  `test_mcp_gated_workflow_pauses_with_resume_token` (MCP gated run now returns paused text;
  the remediation-ladder rendering stays pinned by the `--no-trace` CLI test + gate unit
  tests). Section comment updated too.
- Pre-flight warning wording (found during REAL e2e, not by any plan item): run.py's
  `_prepare_gate_resolver` warned "will FAIL at approval gate(s)" — post-171 the run PAUSES
  (fails only under `--no-trace`). Now says "pause at"/"fail at" keyed on `ctx.obj["trace"]`;
  new-wording assert added to `test_paused_cli.py`; the `--no-trace` "fail" wording stays
  pinned by `test_approval_gate_cli.py` (which runs `--no-trace` throughout).

**Mutation verification (Edit + revert, never stash)** — each ★pin bites:
1. Naive `request.node_id == config.node_id` heuristic in the gate arm →
   `test_child_gate_with_id_colliding_parent_host_stays_failed` fails ALONE (19 others green)
   — exactly the "passes every other test" trap the pin exists for.
2. `_gate_pausable` escalation clauses → `True` → all four refusal pins fail
   (terminal/loop/code/end-action).
3. Runner `trace_enabled` conjunct dropped →
   `test_no_trace_gate_keeps_hard_failure_with_updated_message` fails (bogus token would print).
4. `_aggregates` pause-record emission dropped → trailer round-trip test + the runner e2e fail.
5. `has_resumable_step` forced True on paused → its pin fails.

**Real-surface e2e** (actual `uv run pflow` subprocess, non-TTY): exit 4; stdout exactly
`Paused at 'guarded'. Resume token: <uuid> (exit 4)`; stderr carries the resolved masked
preview + `To answer: pflow resume <uuid> --approve yes|no`; the on-disk trailer reads
`final_status: "paused"` + `paused_node_id` + full `gate_request`; `pflow resume <token>`
refuses with the interim "status 'paused' is not resumable" (Phase 2 replaces this).
Temp trace in the real `~/.pflow/debug` deleted after inspection.

**Phase-1 gates (all green)**:
- `make check`: fully green (ruff, format, mypy 246 files, deptry).
- Four resume suites: **165 passed** (baseline unchanged).
- Full `make test`: **8608 passed, 0 failed** (Phase-0 baseline 8586; +22 net new tests).
- `make test-e2e`: 44 passed.

**Not done (deliberately, scope)**: Phases 2–5 untouched. Interim seam for Phase 2: paused
traces refuse via the loader's generic `final_status != "failed"` arm; two tests carry
explicit "update in Phase 2" notes (`test_resume_engine.py` e2e, and the pause-promise
resume-accepts half). Phase 2 should reuse `format_gate_lines` +
`format_resume_answer_command` from `execution/gate_prompt.py` for
`ResumeAnswerRequiredError` rendering — built here as the shared render seam.

## 2026-07-05 — Post-review hardening pass (owner-requested loose-end sweep)

Owner directive: fix the identified niggles, record the interim states in the PLAN, skip the
MCP-traces-as-snapshot-sources concern (item 9 — intended consequence of Decision 2), and add
only tests that catch REAL bugs ("the bar isn't passing, it's passing the right thing").

**Fixes applied:**
1. **Gate arm tag made unconditional** (engine.py): `_pflow_gate_seen` is now applied OUTSIDE
   the `if self.trace is not None` guard. Verified the old placement was safe today
   (`_open_child_trace` returns a None child collector only when the parent had none, and
   `engine.run` installs the collector into shared — presence is uniform down the tree), but
   the pause decision must not depend on that NON-LOCAL invariant; the comment records both
   facts. Also folded the stale batch-HOST sentence out of the arm comment (unproducible —
   delta #2 above).
2. **`runner.py` stream_to_disk comment corrected** ("MCP passes trace_enabled=False" was now
   false). Pulled forward from Phase 5 because it sits on the exact line 1e changed; plan's
   Phase 5 updated to "verify, don't redo".
3. **`_display_paused_result` dropped its unused `ctx` param** (was kept for symmetry with
   `_display_denied_result`, which actually uses it — dead symmetry loses to simplicity).
4. **Skipped-test rationale recorded (was an unlogged skip):** the plan's "MCP concurrent
   two-run filename uniqueness (smoke)" test was NOT written. Rationale: the microsecond
   filename suffix predates 171 (issue #443, `format_trace_filename`) and is what the plan
   itself calls "the existing mechanism"; a sequential two-run check is tautological (different
   timestamps by construction) and a true concurrent race test is flaky-by-design. The
   MCP-side change is covered by `test_mcp_run_streams_a_real_trace` (real finalized file +
   identity cross-check). If real concurrent-MCP collisions ever surface, the fix lives in
   `format_trace_filename`, not the MCP layer.
5. **`has_resumable_step` docstring** now names the paused case.

**Plan updated (items 6–8):** Phase 2 gained an "interim state inherited from Phase 1" banner
(misleading generic refusal, the two flagged tests, the gate_prompt render seam to reuse);
Phase 4 gained a banner that the RunProgress green-✓ regression EXISTS IN TREE since Phase 1
(must merge together); Phase 5's CLAUDE.md list gained `runtime/engine/CLAUDE.md` (except-arm
description still enumerates gate_outcome as denied/failed) and the runner.py:184-186 note.

**Item 10 (analyze-cache × paused) — found a real, small bug:** `_collect_candidate_traces`
correctly buckets paused as non-reusable, but `_non_reusable_outcome_label` disclosed a paused
run as a **"failed run"** — the exact misattribution that function exists to prevent (its own
docstring: "an interrupted run is not a failed run"; same argument, the agent's next step is
ANSWER THE GATE). Fixed: `paused` → "paused run". Pinned by
`test_autoload_skip_note_labels_paused_run_not_failed` (selection unchanged — older success
still wins; only the disclosure wording).

**High-value tests added (each closes a REAL unpinned bug class, both mutation-verified):**
- ★ **Paused trace is not a `--only` snapshot source** (added to the gate-trace trailer test,
  mirroring the denied pin): a paused run's upstream is PARTIAL. `load_full_run_events` is
  allowlist-based today (verified), but NOTHING pinned that for paused — mutating the allowlist
  to a "reject failed" denylist made this (and the denied pin) fail; no other test caught it.
- ★ **First-node pause status-ladder ordering** (`test_first_node_pause_reads_paused_not_failed`):
  a gate on the FIRST node pauses with ZERO events, and `_determine_trace_status` has a
  zero-events → "failed" arm. Every other paused test had ≥1 event, so the paused-check-first
  ordering was completely unpinned — moving the paused check below the empty-events arm failed
  ONLY this test. Ordering now also documented in a comment at the ladder. (Load-bearing for
  Phase 3's by-name selection of first-node pauses.)

**Shallow-test strengthening (same sweep):**
- `test_parallel_batch_child_gate_stays_failed`: broad `pytest.raises(Exception)` +
  `gate_outcome != "paused"` tightened to `pytest.raises(GateNotInteractiveError)` +
  `parallel_batch is True` + `gate_outcome == "failed"` — now also PROVES gate exceptions
  propagate untouched through the parallel-batch machinery (previously assumed).
- MCP `test_success_text_carries_execution_id`: presence-only assert → parses the value and
  `uuid.UUID()`s it (guards a rendered "None"); `test_mcp_run_streams_a_real_trace` gained the
  identity cross-check (text's execution_id == the trace meta line's) so the id an agent
  captures provably resolves against that exact file.
- Stream-fault CLI test: also asserts `resume_command` absent from the error document (no
  dead-end affordance).
- Reviewed and deliberately left as-is: `test_end_action_refused_by_gate_pausable` (fake-object
  unit test — justified and documented: no non-code node can produce action "end" with an
  escalation in a real graph); the interim loader-refusal e2e (asserts the CURRENT contract
  with an explicit Phase-2 update note — right thing for now).

**Gates re-run:** `make check` green; full `make test` **8610 passed, 0 failed** (+2 from the
previous 8608: the paused-autoload disclosure test and the first-node ordering pin; the other
additions folded into existing tests).

## 2026-07-05 — Phase 2 session start (scope clarified by owner)

Owner initially wrote "continue with phase 3 only"; since Phase 2 was not implemented and
Phase 3's CLI is built on Phase 2's loader contract, I flagged the contradiction — owner
corrected mid-session: **Phase 2 ONLY, then stop for human review.** The plan's
"do-not-split 2+3" rule targets contract drift between DIFFERENT agents; mitigation for the
split: this entry freezes the exact Phase-2 contract Phase 3 must consume (see the
"Phase-2 → Phase-3 contract" section at the end of this session's entry).

- Phases 0+1 committed by owner (`a8066f15`, `cf60b197`). Clean tree confirmed.
- **Baseline captured**: 4 resume suites + `test_gate_pause.py` + `test_paused_cli.py` =
  **181 passed** (the four alone were 165 at Phase-1 close; full suite 8610).
- Plan re-verification (code is truth): all Phase-2 symbols re-grepped in
  `runtime/resume_source.py` post-extraction — `_resolve_resume_entry`'s `!= "failed"`
  catch-all at resume_source.py:391, `_apply_gate_resolutions` at :266, superseded scan at
  :546-562, `_guard_seed_scope` at :458. Trailer keys confirmed to land FLAT on the loaded
  `data` dict (`reconstruct_trace_from_lines` copies non-`kind` trailer keys verbatim,
  trace_io.py:243). `core → execution` lazy-import precedent for
  `ResumeAnswerRequiredError.to_diagnostics()` confirmed: `core/trace_report.py:1126`
  already lazily imports `pflow.execution.formatters`.

## 2026-07-05 — Phase 2 implemented (loader: paused arm + answer fold) — DONE, awaiting review

**What was built** (per plan 2a–2f):
- **2f — `ResumeAnswerRequiredError`** (`core/exceptions.py`, after `ResumeStaleWorkflowError`):
  three modes (`missing_answer` / `wrong_flag` / `not_paused`), messages BUILT IN THE CLASS
  keyed on mode (callers stay one-line). The paused modes render the gate content INTO the
  multi-line message (question + numbered options with `(rec)`, or the secret-masked approval
  preview) via `format_gate_lines`, and the suggestion carries the exact kind-correct command
  via `format_resume_answer_command` (both lazy-imported from `execution/gate_prompt` at raise
  time — the Phase-1 render seam, reused as planned). `to_diagnostics()` adds the masked
  `context["gate"]` payload (same policy as `GateNotInteractiveError`). Instance-level `_TITLE`
  override for `not_paused` ("No paused gate to answer").
- **2a — `ResumeSource` fields**: `paused_node_id` + `gate_request` (default `None`); no
  separate kind field (read `gate_request["kind"]` — one source of truth, per plan).
- **2c — `_resolve_resume_entry` paused arm** (before the `!= "failed"` catch-all):
  corrupt/missing pause record → `ResumeNotResumableError("…no pause record")`; escalation →
  `(None, paused_node_id)` (between-nodes, CLI resolves successor); approval →
  `(paused_node_id, None)` (the gated node never ran — no event, seed scope excludes it by
  construction).
- **2d — answer validation + fold**: `_fold_decision_into_event` EXTRACTED from
  `_apply_gate_resolutions`' loop body (refactor-in-place, one fold shape, two callers);
  `_map_choose_answer` mirrors `_prompt_escalation`'s strip + digit→label rule;
  `_validate_gate_answer` (missing answer / wrong flag) runs BEFORE the seed guards.
- **2b + 2e** — `load_resume_source(..., gate_answer=None)`; the whole answer policy lives in
  ONE new seam `_apply_paused_answer(path, data, events, gate_answer, execution_id)` called
  between `_apply_gate_resolutions` and `_guard_seed_scope` (extraction forced by ruff C901,
  and better anyway: one function owns validate + not_paused + map + fold).
- **Shared label rule**: `option_labels()` added to `core/gate.py`;
  `gate_prompt._format_option_lines` refactored onto it — the prompt's digit answer, the pause
  output's numbering, and the loader's `--choose N` mapping now literally share one function.

**Deviations from the plan (with rationale — none are shortcuts):**
1. **`not_paused` check ordering**: plan 2e didn't pin where the check fires. Placed AFTER
   `_resolve_resume_entry`, so status refusals win: `resume <succeeded-id> --approve yes` says
   "nothing to resume" (the more fundamental fact), and the `not_paused` answer error fires
   only for sources that are otherwise RESUMABLE (failed/incomplete). Both orderings satisfy
   the plan text; this one never buries a status refusal under a flag-usage complaint.
2. **Numeric `--choose`→label mapping lives LOADER-side**, not in the CLI (plan 3b's text put
   it there): the mapping needs `gate_request["options"]`, which only the loader has at answer
   time — and the plan's own Phase-2 test list includes the mapping, confirming the placement.
   Phase 3 passes `{"chosen": <raw flag value>}` and the loader maps.
3. **`option_labels` in `core/gate.py`** (small touch on Phase-1's `gate_prompt.py`): the plan
   said "mirror `_echo_options`' label extraction"; mirroring by copy would be a second home
   for the ONE rule. `core/` is importable by both `execution/` and `runtime/` — single home,
   no layering violation.
4. **Parity pins added in Phase 2** (plan's test list put them under Phase 3, but the Phase-2
   header says parity "holds by construction — but pin it"): approval variant drives the REAL
   `WorkflowRunner` resume + planner; escalation variant drives the engine directly (the
   custom `EscalatingNode` isn't in the runner's registry) + planner with the same compiled
   workflow. The escalation pin asserts the FOLDED decision seeds identically on both sides.

**Phase-2 → Phase-3 contract (FROZEN — Phase 3 must consume exactly this):**
- `load_resume_source(..., gate_answer=...)` shapes: `{"approve": True|False}` from
  `--approve yes|no`; `{"chosen": "<raw --choose value>", "notes": None}` from `--choose`
  (loader strips/maps numerics; CLI passes the raw string). Both flags given → CLI-side
  `click.UsageError` (never reaches the loader).
- `ResumeSource.paused_node_id is not None` ⟺ paused source (the CLI's skip-side-effect-confirm
  discriminator, plan 3c); approval entry == `paused_node_id`; escalation entry `None` +
  `last_completed_node_id == paused_node_id` → route through `_resolve_between_nodes_entry`.
- `--approve yes` delivery = prime the resolver's `auto_approve` with `source.paused_node_id`
  (verified end-to-end in the updated e2e keystone, which does exactly that);
  `--approve no` delivery = the new `deny` resolver param (plan 3c, NOT built yet).
- `ResumeAnswerRequiredError.mode` values: `missing_answer` / `wrong_flag` / `not_paused`
  (CLI needs no mode-specific handling — the messages are self-contained).

**INTERIM STATE (dangling affordance until Phase 3 lands — deliberate, owner-scoped):**
a paused `pflow resume <token>` now refuses with the correct pending-gate rendering and the
exact command `pflow resume <id> --approve yes|no` / `--choose "…"` — but those flags DON'T
EXIST on the CLI yet (click rejects them with "no such option"). Same for `pflow resume list`
mentioned nowhere yet. Unreleased branch, review gap only; Phase 3 closes it.

**DISCOVERED ISSUE (not Phase-2 scope — for owner/Phase-3 attention):** an INLINE gated run
can now emit an unhonorable token — MCP `execute_workflow` accepts an IR dict (and CLI accepts
content-string workflows), whose `workflow_path` is `ir-hash:<md5>`; post-Phase-1 those runs
stream traces, so a gate pauses them and prints a token — but `load_resume_source` refuses
inline sources BEFORE the paused arm ("Inline or piped workflows cannot be resumed… no source
file to re-resolve"). A pause-promise gap at the producer for inline sources. Options when it's
addressed: (a) producer keeps inline gated runs `failed` (mirroring `--no-trace`), or (b) a
paused-specific inline refusal message ("re-run with --auto-approve"). Phase 3's `resume list`
must also decide whether to show inline paused runs (recommendation: exclude `ir-hash:` +
record why). NOT fixed here — producer territory, needs an owner call.

**Behavior-change test updates** (1 test encoded the interim Phase-1 contract, its docstring
said to update it here): `test_resume_engine.py::test_non_interactive_gate_stop_pauses_and_
loader_refuses_pending_answer_e2e` → renamed `test_non_interactive_gate_pause_loads_with_
answer_and_resumes_e2e` and EXTENDED into the approval keystone: no-answer →
`ResumeAnswerRequiredError` with gate content + exact command; `{"approve": True}` → entry =
the gated node; real resume with a primed resolver → upstream restored, gated node runs once.

**New tests** (+18 net; full suite 8610 → 8628):
- `test_resume_source.py` (+13): paused-approval/escalation entries, deny-shaped answer loads
  identically (loader is verdict-agnostic), corrupt pause record, ★missing-answer renders gate
  content and NOT the guard's message (fold-order pin, real-id in the suggestion),
  wrong-flag both directions, not_paused on a failed source, ★`--choose` mapping matrix
  (digit / strip / label-less "option 3" / out-of-range / free text), fold-decides-marker,
  superseded-paused-token-with-answer.
- `test_gate_pause.py` (+1): ★escalation keystone on a REAL producer trace — numeric answer
  maps through producer-written options, fold + between-nodes entry, engine resume at the
  successor: escalating node restored NOT re-executed, decided marker re-recorded into the
  attempt trace (self-containment), successor runs, attempt trails success.
- `test_plan_drift.py` (+2): ★paused-approval parity (the distinct seed-boundary case — entry
  has NO event, scope = ALL events) and ★paused-escalation parity (folded decision seeds
  identically on both sides).

**Mutation verification (Edit + revert, never stash)** — each bites:
1. `_apply_paused_answer` moved AFTER `_guard_seed_scope` → 11 tests fail (fold-order pin,
   mapping matrix, both keystones, escalation parity).
2. Escalation entry flipped to the approval shape `(K, None)` → 3 fail (entry pin, keystone,
   parity).
3. Numeric→label mapping dropped (return raw) → 4 fail (matrix digits + keystone).
4. Wrong-flag kind check disabled → both wrong-flag pins fail.

**Gates (all green):** `make check` fully green (ruff, format, mypy, deptry); resume-adjacent
suites 254 passed; full `make test` **8628 passed, 0 failed**; `make test-e2e` 44 passed.
Nothing committed (repo rule).

**Not done (scope):** Phases 3–5 untouched. Phase 4's RunProgress green-✓ regression still
EXISTS IN TREE (since Phase 1 — see that phase's banner). Next action = plan Phase 3 (CLI),
consuming the frozen contract above; re-grep nothing — Phase 2 touched only
`resume_source.py`, `exceptions.py`, `gate.py`, `gate_prompt.py`.

**Post-review addition (same session, pre-commit):** owner review surfaced one tightening —
an empty/whitespace `--choose` would have "decided" the escalation with an empty ``chosen``,
a shape the blocking prompt cannot produce (click re-prompts on empty input).
`_validate_gate_answer` now treats it as ``missing_answer``; pinned by
`test_empty_choose_answer_is_treated_as_missing` (both `""` and `"   "`). Suites re-run green;
Phase 2 committed by owner instruction ("commit phase 2") as `8125454a`.

## 2026-07-05 — Phase 3 implemented (CLI: group, --approve/--choose, resume list) — DONE, awaiting review

Owner authorized delegation (incl. same-model forks). Orchestration actually used:
- **Wave 0 (parallel):** a `code-implementer` spike burned down the braindump's 70%-sure
  click-routing risk (scratchpad prototype, 11 invocations × 4 configs); two
  `pflow-codebase-searcher` sweeps (registration/help fan-out; dry-run path + age helpers +
  tail-seek mechanics). I read `test_resume_cli.py` in full meanwhile.
- **Wave 1 (me):** 3a group restructure, 3b flags, 3c resolver deny + priming + consumption
  clauses + `_find_consuming_attempt` extraction, 3d message parameterization, the e2e
  answer-flow battery, deny unit pins.
- **Wave 2 (parallel):** a FORK (full-context subagent) implemented 3e (`resume list`) end to
  end — including its own mutation verification of the oversized-trailer pin — while I wrote
  the battery. File-ownership split held (fork: resume_source.py + resume.py appends + new
  test_resume_list_cli.py; me: everything else). I reviewed the fork's full diff before
  accepting it.

**Spike findings that shaped 3a (recorded because the plan flagged them 70%-sure):**
`ignore_unknown_options = True` as a CLASS ATTR on `ResumeGroup` is the one load-bearing
setting; `allow_interspersed_args` belongs on the hidden `run` SUBCOMMAND (a group-level
setting is inert); `invoke_without_command` stays default. Verified consequences: options
before the target work; unknown flags forward to `_split_target_and_params`'s existing
UsageError (the GH#454 pattern, same as the root group); `resume <target> --help` shows the
run option list; workflows literally named `run`/`list` are reserved (resume by path/id —
documented in the group help).

**What was built (per plan 3a–3e):**
- 3a: `ResumeGroup` + `resume` group whose docstring IS the discoverability surface (forms,
  full flag inventory, a worked paused-gate example, the reserved-names note); hidden `run`
  subcommand = the old `resume_cmd` body; `main.py` imports/registers `resume`.
- 3b: `--approve [yes|no]` / `--choose ANSWER`; `_build_gate_answer` (mutual-exclusion
  UsageError + the frozen Phase-2 shapes); `gate_answer` threaded through ALL THREE
  `load_resume_source` call sites in `_load_source_and_workflow`.
- 3c: `build_gate_resolver(..., deny=frozenset())` keyword-only (all 17 existing call sites
  unaffected — verified by sweep); deny checked BEFORE auto-approve (backstop; CLI rejects the
  contradiction up front); `_prime_approval_delivery` (yes → auto_approve + paused node;
  no → gate_deny tuple; contradiction → UsageError); `ctx.obj["gate_deny"]` set in BOTH
  `_dispatch_resume` and run.py per plan; `_prepare_gate_resolver` reads it;
  `_attempt_consumed_work` gained clause (a) (gate VERDICT lines `approved`/`denied`/`choice`
  — never `non_interactive`/`error`) and clause (b) (`paused ⇒ consumed`); superseded scan
  extracted to `_find_consuming_attempt` (one policy, loader + list); paused sources skip
  `_confirm_or_refuse_side_effect` (ledger rationale in a comment).
- 3d: `_resolve_between_nodes_entry` speaks the source's real state ("is paused" vs "was
  interrupted"); paused terminal-step case gets the plan's specific refusal ("was the final
  step — its answer has nothing left to run"), reachable only via edit+`--force`.
- 3e (fork): `PausedRun`, `_scan_tail_for_trailer`/`_read_trailer_line` (64KB tail +
  oversized-trailer full re-read, mirroring `run_tailer.read_run_status` — the accepted
  `runtime/ ↛ ui/` duplication, documented), `list_paused_runs` (skips --only, `ir-hash:`
  inline [pause-promise gap comment points here], corrupt records, consumed tokens);
  `resume list` renderer (aligned columns TOKEN/WORKFLOW/PAUSED AT/GATE/AGE, local
  `_format_age` s/m/h/d — no shared helper exists, verified — per-kind footer via
  `format_resume_answer_command`, JSON array with kind-correct `resume_command`, empty state
  `No paused runs.` / literal `[]`).

**Behavior change (deliberate, replaces a pinned contract):** bare `pflow resume` now renders
the GROUP HELP (exit 0) instead of "Missing TARGET" (exit 2) — consistent with sibling groups
(mcp/settings/skill) and it puts the flag inventory where an agent lands first;
`resume --force` (flag, no target) still hard-errors "Missing TARGET" exit 2. Test renamed
`test_bare_resume_shows_group_help_with_answer_flags` and pins both halves.

**Test-writing discoveries (recorded for the next agent):**
- Registry injection for CLI-level custom nodes needs the full scanner entry shape — the
  runner pipeline reads `entry["interface"]` (bare `compile_workflow` does not). Pattern in
  `test_paused_cli.py::escalating_registry`. NOTE: outside pytest, `Registry()` hits the REAL
  `~/.pflow/registry.json` — never run the injection snippet in a bare `uv run python`.
- Output auto-detect's `result > stdout` priority surfaces a restored escalation marker over
  the consumer's stdout — identical to an uninterrupted run, so the e2e fixtures declare
  `## Outputs` to pin the consumer's line.

**New/updated tests (+27 net; full suite 8628 → 8655):** the e2e answer battery in
`test_paused_cli.py` (16 tests: ★approve keystone with uninterrupted-run stdout equality,
★deny + ★double-deny-superseded, answer-required rendering, wrong-flag both directions,
both-flags UsageError, deny-vs-auto-approve UsageError, ★dry-run-without-answer pin,
dry-run-with-answer plans-only, stale-hash + --force, ★first-node pause by-path,
multi-gate 3-trace chain, ★escalation --choose keystone through the REAL CLI incl.
numeric→label mapping, ★restored-only-paused-attempt chain-fork prevention,
edited-final-step paused refusal); `TestDeny` unit pins in `test_gate_prompt.py` (4);
fork's `test_resume_list_cli.py` (6, incl. ★oversized-trailer); bare-resume group-help pin.

**Mutation verification (Edit + revert):** clause (b) dropped → exactly the first-node-by-name
+ chain-fork pins fail; clause (a) dropped → exactly the double-deny pin fails (the
"passes-every-other-test" trap it exists for); resolver deny check dropped → 2 unit pins + the
deny e2e fail; fork independently mutation-verified the oversized-trailer re-read (its pin
fails alone). All reverted; `git diff` carries zero mutation residue.

**Real-surface e2e** (actual `uv run pflow` subprocesses, isolated HOME): gated run → exit 4 +
token; `resume list` renders the row (age `7s`, approval footer); `--approve yes` → upstream
restored, gated executed, `⤷ Resumed from` indicator, exit 0; `resume list` → "No paused
runs."; `--output-format json` → `[]`. Plus the pre-existing real-subprocess routing test
(`test_resume_no_hang_subprocess`) green through the new group.

**Gates (all green):** `make check` fully green; full `make test` **8655 passed, 0 failed**;
`make test-e2e` 44 passed. Nothing committed (Phase-3 commit not yet authorized).

**Not done (scope):** Phases 4–5 untouched. Phase 4's RunProgress green-✓ regression still in
tree (must merge with this work — see the Phase-1/Phase-4 banners). Phase 5 docs inventory is
ready-made: the registration-sweep agent enumerated every `pflow resume` usage line in
guide/docs/CLAUDE.md files (no tests validate those snippets).

## 2026-07-05 — Inline pause-promise gap CLOSED (owner decision: option a) + issue #562

Owner picked option (a): an INLINE run's gate never pauses — pause is a promise, and resume
ALWAYS refuses an inline token (no source file to re-resolve). Option (b) — make inline runs
resumable by storing the workflow content in the trace — is filed as **GH issue #562** with
the design sketch, interactions (#542 retention, Task 176), and the two pins that flip when
it lands.

**What changed:**
- Engine pause arm (the ONLY producer decision point) gained two conjuncts:
  `workflow_path is not None` and `not workflow_path.startswith("ir-hash:")` — same principle
  as `_gate_pausable`'s loop/code/terminal refusals; comment points at #562. The root engine
  always receives `workflow_path` from the runner (`_workflow_path_id(resolved)` — verified),
  so `None` occurs only in direct-engine embedding, which also has no re-resolvable identity.
- `GateNotInteractiveError.to_diagnostics()` suggestion now names the inline cause with its
  remedy ("save it and run by name/path to pause instead") beside `--no-trace`.
- `resume list` already excluded `ir-hash:` traces (fork's 3e); no change needed there.

**Test fallout (the change surfaced a harness gap, not a behavior bug):** engine-level
producer tests constructed ROOT engines without `workflow_path` — a shape production never
produces (the runner always passes it). All such constructions in `test_gate_pause.py`,
`test_gate_trace.py`, and the plan-drift escalation parity now pass `workflow_path`,
which also keeps the id-collision pin honest (with `None` it would have read `failed` for
the WRONG reason and gone dead — re-verified: the naive-id-heuristic mutation still fails
EXACTLY that pin post-change).
- `test_cli_mcp_parity.py::test_mcp_gated_workflow_pauses_with_resume_token` encoded the gap
  itself (dict-IR inline pause with an unhonorable token) → rewritten as
  `test_mcp_gated_workflow_pauses_by_path_but_fails_inline`: file-based MCP run pauses with a
  token; the SAME workflow inline gets the ladder naming the inline cause.

**New pins** (`test_gate_pause.py::TestInlinePausePromise`, both mutation-verified — dropping
the inline conjuncts fails exactly these two): inline gated run through the REAL runner
(ir-hash synthesis path) → FAILED, no `pause_request`; rootless engine (workflow_path=None) →
never pauses.

**Gates:** `make check` green; full `make test` **8657 passed, 0 failed** (+2);
`make test-e2e` 44 passed. Phase-3 work remains uncommitted.

## 2026-07-05 — DRAFT task review written (owner-requested, ahead of Phase 4/5)

`task-review.md` drafted by the Phase-2/3 implementer while the tacit context was live —
covers Phases 0–3 + the inline decision; carries a DRAFT banner and a "Pending" section with
explicit instructions for the Phase-4/5 finisher (fill their sections, THEN flip the spec
status to done and drop the banner). The task spec status was deliberately NOT changed —
the task is not done.

## 2026-07-05 — Phase 4 implemented (UI: resumed_from chain + paused status) — DONE, awaiting review

Implemented per plan Phase 4, no deviations. All file:line refs from the plan verified live
before editing.

**Server/API:**
- `ui/server.py::_run_entry` — projects `"resumed_from": meta.get("resumed_from")` (the meta
  line carries it since 2.6.0; `run_tailer._read_meta` verified to pass it through — only
  `inputs` is popped). `ui/CLAUDE.md`'s `/api/runs` contract updated in the same edit (field
  list + `paused` in the final_status vocabulary + the resumed_from sentence); the broader
  status-vocab doc sweep (run_tailer docstring, ui/CLAUDE.md:105 elsewhere) stays Phase 5.

**Frontend (all four plan items):**
- `web/src/types.ts` `RunInfo` gains `resumed_from: string | null` (4 test fixtures updated:
  RunSelector/RunPanel/CatalogView/GraphView tests).
- `RunProgress.tsx::runBadgeStatus` — the REQUIRED regression fix: `paused` arm before the
  success fallthrough, mirroring the denied arm (amber "stopped" badge; outcome text carries
  the word). Without it a UI-launched gated run rendered the green ✓.
- `RunSelector.tsx::runMark` — `paused` branch before the grey stale fallback: `⏸` /
  `run-paused` / "paused". Chain marker: a resumed run renders `⤷ resumed from <first-8>`
  under its label; when the source run is in the current list the marker is a jump link
  (stopPropagation → pick(source)); absent source → plain text, click falls through to the
  row's own pick. No grouping/collapsing (v1 scope per plan).
- `index.css` — `.run-paused` beside each of the three verified `.run-denied` sites
  (run-banner ~:737 / run-mark ~:871 / run-progress-outcome ~:2553, all amber) +
  `.run-menu-resumed`/-link styles. `events.ts` RUN_STATUSES untouched (per-NODE allowlist).
- Defensive `paused` arms beside the denied arms in
  `execution/formatters/success_formatter.py` (⏸ line) and
  `cli/workflow_output.py::_format_workflow_completion_status` (⏸ line + docstring
  vocabulary) — same "never render a pending question as ✓" intent.

**Tests (all green):**
- API: `test_ui.py::test_run_entry_projects_resumed_from_chain_lineage` (`_write_trace` grew a
  `resumed_from` kwarg; pins set→id, absent→None, and `paused` riding the raw-fact projection).
- Components: RunSelector paused-mark test (amber ⏸, never stale), chain-marker jump test
  (stopPropagation → source id, not the row's own), marker-plain-when-source-absent test;
  RunProgress paused-never-green test (mirrors the Task-125 denied test).
- Full suites: `npx tsc --noEmit` clean; vitest 727 passed (51 files, was 723 — +4);
  `make check` green.

**Real-surface check (screenshot-pflow-web-ui skill, headless Chrome, rebuilt bundle):**
Real traces produced by a real run (approval-gated workflow, non-TTY → exit 4 + token
d398bef5…; `resume <id> --approve yes` → completed attempt 2c1e178c… with
`resumed_from` on its meta). Verified in-browser:
1. `/api/runs` returns `resumed_from: "d398bef5…"` on the attempt, null on the source
   (first probe hit a STALE pre-edit server process on 8765 — killed and restarted; worth
   remembering: the reuse-if-up probe happily reuses an old-code server).
2. Run-selector menu screenshot: amber ⏸ "paused" mark on the source run + "⤷ resumed from
   d398bef5" secondary line on the attempt.
3. Pinned paused run (`&run=d398bef5…`): canvas banner "Run paused · 1 nodes" AMBER
   (run-paused border), RunProgress callout amber ■ badge + "Run paused" text, `gated` step
   "pending" — the green-✓ regression is gone.

**Gates:** `make check` green; full `make test` **8658 passed, 0 failed** (+1 vs the 8657
Phase-3 baseline — the new `/api/runs` lineage test). Phase 5 (docs) remains.

## 2026-07-05 — Phase 4 owner-testing fix: chain marker swallowed row clicks

Owner drove the live UI and couldn't switch FROM the paused run TO its resumed attempt via
the run menu. Cause: `.run-menu-label` is a column flex whose children STRETCH — the
"⤷ resumed from" jump-link span filled the row's full width, so clicks on the attempt row's
lower half hit the LINK (jump to the source = the already-pinned run → no-op, menu closes)
instead of the row. Fix: `align-self: flex-start` on `.run-menu-resumed` (span shrinks to its
text; the comment in index.css records the trap). New pin:
`RunSelector.test.tsx::clicking a resumed row's OWN label picks that run` (pinned-to-source →
click "success" → onSelect(attempt), never the source). Vitest 9/9 in file (728 total),
bundle rebuilt, menu re-screenshotted (visually identical — only the hit box shrank).

## 2026-07-05 — Steer-latch trap found during owner testing + fixed (events.ts, UNCOMMITTED)

Owner testing surfaced a PRE-EXISTING Task-175/#539 bug that 171's chain UX makes acute: after an
agent steers a tab (`select-run` — latched server-side, replayed on every subscribe), the user can
NEVER manually switch runs in that tab. Mechanism (reproduced headlessly both ways): GraphView
re-subscribes on every run switch; the client's epoch-dedup baselines (`applied`) lived INSIDE the
subscribe() closure, so each re-subscribe reset them and the replayed latch was admitted as new —
selectRun(steered-run) reverted every manual pick within ~100ms, until a server restart cleared
the per-process latch.

Fix (`web/src/api/events.ts`): hoisted the baselines to MODULE scope, keyed per workflow
(`appliedByWorkflow` Map) — keyed because the server stamps ALL workflows' latches from ONE
process-wide counter (`_point_epoch`, server.py:156), so a flat baseline would let workflow A's
high epoch reject workflow B's older-but-unseen latch after SPA navigation. `serverBootId` also
module-scoped; a boot change resets every workflow's baselines IN PLACE (never Map.clear() — live
subscriptions hold references). `_resetEpochBaselines()` exported test-only. Three new pins in
`events.test.ts` (re-subscribe keeps baseline / per-workflow keying / boot re-base across
re-subscribe) + `_resetEpochBaselines()` in the file's beforeEach (module state now deliberately
survives re-subscribes — tests need explicit resets). Vitest 731 passed (+3), tsc clean.

E2E proof: latch armed via bare `POST /api/command` select-run on a fresh server, then the
click-success browser repro — pre-fix the pick reverted to the steered run; post-fix urlAfter
carries the picked run + "Run success" banner.

Also this session (both UNCOMMITTED per owner instruction; the earlier fix-commit was
`git reset` back into the working tree): the chain-marker click-target fix + its pin, and the
owner's ⏸-frontier-badge + un-run-greying idea folded into task-176.md as a scoped section
(canvas truth for paused/replayed runs — the badge is the anchor 176's approve controls attach to).

## 2026-07-05 — Phase 5 (docs) — context-optimized subset done, three items DEFERRED (all UNCOMMITTED)

Audit first (pflow-codebase-searcher, thorough): findings that corrected the plan — the plan's
"engine/CLAUDE.md except-arm already updated post-Phase-1, verify don't redo" was FALSE (still
denied/failed only); the Phase-3 "resume usage-line inventory" was never actually transcribed
into this log (the entry only asserts it exists — the audit reconstructed it by grep, list in
the audit output); a NEW stale spot outside every checklist: runner.py:234 "MCP's trace never
streams". Also: 164 DID ship user docs (docs/reference/cli/index.mdx "Resume a failed run"), so
docs/ coverage for 171 is a genuine gap, not convention.

**Done this session** (owner directive: do what this context is optimized for — the implementer
ran the real pause/approve/choose flows live, so behavior claims are first-hand):
- Stale "MCP never streams" family, all 7 sites: `mcp_server/tools/execution_tools.py` (Field
  description + Built-in behaviors + a new Paused arm in Returns — matched to the REAL
  `_format_paused_text` shape), `mcp_server/CLAUDE.md` (:76 tool line + the Agent-Optimized
  Defaults bullet incl. the ADR-0008 misattribution correction), `execution/CLAUDE.md`
  (RunnerConfig finalize comment + a PAUSED/exit-4/render-shape note beside the DENIED one in
  the gate_prompt.py block), `runtime/CLAUDE.md` (Task-172 bullet ×2: trace_enabled gate +
  "finalize CLI-only"), `runner.py:234` comment, `runtime/engine/CLAUDE.md` (except-arm:
  denied/paused/failed + the full pause-conjunct description).
- `runtime/CLAUDE.md`: new **2.7.0** trace-format bullet (paused trailer, producer decision
  point, resume_source consumers, consumption policy, exit 4).
- `cli/CLAUDE.md` exit-code paragraph: exit 4 + the paused branch's output shape + ResumeGroup
  pointer. `cli/commands/CLAUDE.md` resume row: group routing, --approve/--choose, resume list,
  bare-resume help, and the stale `workflow_trace.load_resume_source` pointer →
  `resume_source.load_resume_source`/`list_paused_runs`.
- `ui/run_tailer.py:110` docstring: + denied/paused.
- ADR-0008: "Update — MCP runs stream too (Task 171)" section (aligns with A1's "any run is
  watchable"; names the Task-172 misattribution).
- Guide prose: `features/resume.md` retitled ("failed, interrupted, or paused at a gate") + new
  "Answering a paused gate" section (token line verbatim from a real run, JSON fields, all four
  answer commands, nothing-re-runs/consumption/no-answer-refusal/hash-gate bullets);
  `features/approval.md` — playbook item 1's now-false "re-executes everything upstream on
  retry" replaced, the "fails loudly (exit 1) … cannot yet hold a gate open" paragraph rewritten
  to the durable-pause reality (with the exact non-pausable list: --no-trace, parallel-batch
  item, sub-workflow child, inline), the escalation bullet rewritten (pauses, --choose, work
  never re-paid, loop/code/final-step refusals), Observability gains the paused line;
  `entry.md` resume topic line updated. Rendering verified via real `pflow guide resume|approval`.

**Gates**: make check green; make test 8658 passed (unchanged baseline — doc-only).

**DEFERRED (not lack of importance — lack of loaded context / owner decisions):**
1. `docs/` Mintlify user docs — owner scope call (extend docs/reference/cli/index.mdx with the
   pause flow + move roadmap.mdx:39 out of planned). 164 set the precedent that resume IS
   documented there.
2. Optional #542 "171 landed" confirmation comment (substance already on the issue).
3. Task close bookkeeping — root CLAUDE.md roadmap tick, task-171.md Status flip, task-review
   DRAFT banner drop + Phase-5 section — blocked on item 1's decision (can't close with docs/
   undecided).

## State at 2026-07-05 session end (Phase 4 + 5 sessions, one implementer)

- **Committed** (branch `feat/durable-resume-tokens`, unpushed): phases 0–4 as one commit each
  (`a8066f15` / `cf60b197` / `8125454a` / `ddb078e5` / `3db03f0e`). NOTHING after `3db03f0e` —
  owner instructed no further commits without explicit go-ahead (a fix-commit made in between
  was `git reset` back into the working tree on that instruction).
- **Uncommitted working tree** (all green together: make check ✓, make test 8658 ✓, vitest 731 ✓,
  tsc ✓), three logical change sets awaiting owner review + commit-shaping:
  1. **Chain-marker click-target fix** (Phase-4 followup, owner-caught): `web/src/index.css`
     (.run-menu-resumed align-self) + `RunSelector.test.tsx` pin.
  2. **Steer-latch fix** (pre-existing Task-175/#539 bug, owner-caught): `web/src/api/events.ts`
     (module-scoped per-workflow epoch baselines + `_resetEpochBaselines`) + `events.test.ts`
     (+3 pins). Suggested commit shape: separate from 171 phases (it's 175 territory).
  3. **Phase 5 docs subset**: guide (entry.md, features/resume.md, features/approval.md),
     CLAUDE.mds (cli, cli/commands, execution, runtime, runtime/engine, mcp_server), ADR-0008
     update note, `execution_tools.py` docstrings, `runner.py:234` comment,
     `run_tailer.py:110` docstring — plus `task-176.md` (owner's ⏸-badge/greying idea folded
     in) and this log.
- **UI bundle**: rebuilt with the fixes; `pflow ui` on :8765 may still be running locally
  (throwaway demo traces for `paused-ui-demo` live in ~/.pflow/debug — harmless).
- **Open owner decisions** (blocking task close): (a) docs/ Mintlify scope — extend
  `docs/reference/cli/index.mdx` with the pause flow + move `roadmap.mdx:39` out of planned,
  or explicitly let docs/ lag; (b) commit shaping/timing for the three change sets above.
  After (a): roadmap tick in root CLAUDE.md, task-171.md Status → done, task-review.md
  Phase-5 section + DRAFT banner removal (Phase-4 section is already written).
- **Read-first for a fresh agent**: task-review.md (load-bearing block) → this log's Phase-4,
  steer-latch, and Phase-5 entries.
- **The resume usage-line inventory, transcribed at last** (the Phase-3 claim it was already
  here was wrong; the Phase-5 audit reconstructed it by grep — state AFTER this session's edits):
  - `src/pflow/guide/entry.md:60` — UPDATED (topic line covers paused answers).
  - `src/pflow/guide/features/resume.md` — UPDATED (retitled; "Answering a paused gate" section).
  - `src/pflow/guide/features/approval.md:42,46,70,101ff` — UPDATED (pause reality; the stale
    "cannot hold a gate open" / "work is discarded" claims are gone).
  - `src/pflow/cli/CLAUDE.md` exit-code paragraph — UPDATED (exit 4 + ResumeGroup pointer).
  - `src/pflow/cli/commands/CLAUDE.md:10` resume row — UPDATED (group, flags, list; fixed the
    stale `workflow_trace.load_resume_source` pointer).
  - `src/pflow/runtime/CLAUDE.md` — UPDATED (2.7.0 bullet + Task-172 bullet corrections).
  - `docs/reference/cli/index.mdx:72–90` ("Resume a failed run") — **PENDING, owner scope call**.
  - `docs/roadmap.mdx:39` ("durable resume tokens" listed as planned) — **PENDING, owner call**.

## 2026-07-05 — Phase 5 finished + task closed (the two deferred docs + bookkeeping)

Owner chose "write the docs/ Mintlify pages now" (over letting docs/ lag). Closes the last two
deferred items and the close-out bookkeeping. Doc-only — no code, no test changes.

**docs/ Mintlify (the deferred owner-scope items):**
- `docs/reference/cli/index.mdx` — new **"Answer a paused gate"** section after "Resume a
  failed run": the exit-4 token line, the stderr/JSON gate content, the three answer forms
  (`--approve yes|no`, `--choose`, `resume list`) as runnable commands + an options table, the
  nothing-re-runs / token-consumption / no-answer-refusal behavior, and a `<Note>` listing the
  non-pausable positions (`--no-trace`, batch item, sub-workflow child, inline). Links
  `/how-it-works/approval-gates`. Voice matches the surrounding failed-resume prose.
- `docs/roadmap.mdx` — durable resume moved **Now → Current status** (a shipped bullet pairing
  resume + durable gate pause); **Now** repointed to "Approval gates in the browser" (Task 176,
  the documented follow-on). Per docs/CLAUDE.md's "update Current status when major features
  ship."
- Deliberately NOT touched: `changelog.mdx` — version-tied, driven by `/release`; unreleased on
  this branch. #542 retention comment skipped (substance already on the issue).

**Bookkeeping (task close):**
- `task-171.md` `## Status` `not started` → **done** + a `## Completed` block (phase list,
  commit span `a8066f15`→`fde74150`, #562 / Task 176 follow-ons).
- `task-review.md` — DRAFT banner → COMPLETE; the "Pending" section replaced with the shipped
  **Phase 5 (docs)** record (both sessions).
- Root `CLAUDE.md` — Task 171 moved from Planned Features "Next?" into Recently Completed (✅);
  "Next?" now leads with Task 176.

**Gate:** doc/markdown-only; no code touched, so `make test` baseline (8658) is unaffected.
Nothing committed (repo rule — awaiting owner go-ahead; suggested as its own "phase 5 / docs +
close" commit).

**Live doc-verification (docs/CLAUDE.md mandates runnable examples — drove the REAL CLI, not
just tests):** `uv run pflow resume --help` matches the documented surface verbatim
(`--approve yes|no`, `--choose "ANSWER"`, `list`, deny-exits-3, the reserved run/list names).
Full round-trip on a real gated shell workflow (non-TTY via `</dev/null`; NOT an empty pipe —
that trips stdin-routing):
- Pause → **EXIT 4**, stdout `Paused at 'notify'. Resume token: <id> (exit 4)`; stderr carried
  the `command:` gate preview + `To answer: pflow resume <id> --approve yes|no`.
- `pflow resume list` → the documented `TOKEN  WORKFLOW  PAUSED AT  GATE  AGE` row (AGE `0s`,
  GATE `approval`) + per-kind footer; empty state `No paused runs.` / `[]`.
- `pflow resume <id> --approve yes` → **EXIT 0**, gated step ran once (`sending notification`);
  `resume list` afterward empty (token consumed by the resumed attempt).
Confirms the new `docs/reference/cli/index.mdx` "Answer a paused gate" section and the guide
prose are accurate. Gotcha recorded for the next agent: `.pflow.md` shell nodes take the
command via a ```command fence (```bash → "Unknown parameter 'bash'"); nodes live under
`## Steps` with `- type:`/`- approval: required` attributes. Throwaway `gated` demo traces
(+ two stale `gated-demo` ones from prior sessions) cleaned from `~/.pflow/debug`.
