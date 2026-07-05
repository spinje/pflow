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
