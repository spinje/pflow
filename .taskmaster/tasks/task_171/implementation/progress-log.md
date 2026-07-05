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
Phase 2 committed by owner instruction ("commit phase 2").
