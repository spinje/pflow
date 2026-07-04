# Task 164 Implementation Progress Log

Scope of this session: **Phase 0 only** (parity test + `seed_walk_entry` extraction), then stop
for human review. Plan: `implementation/implementation-plan.md`. Context read in full:
`task-164.md`, `starting-context/braindump-2026-07-04-plan-session-handoff.md`.

## Implementation steps (Phase 0, from the plan)

1. Pre-flight: capture `make test` / `make check` baseline; re-verify plan anchors against HEAD.
2. Write `tests/test_execution/test_plan_drift.py::test_engine_and_planner_walk_entry_state_match`
   FIRST (recipe: `test_plan_batch_sub_workflow_output_shape_matches_engine`, PR #505).
3. Mutation-verify: temporarily re-fork one side via Edit (filter one key from the seed), confirm
   ONLY this test fails, revert. Never `git stash`.
4. Add module-level `seed_walk_entry` to `src/pflow/runtime/engine/engine.py`; rewire
   `_run_only_snapshot` and `plan._resolve_walk_start`. Parity suites green UNMODIFIED;
   `-m trace_files` green.
5. Record: run-query glob consolidation deliberately NOT done (4 sites disagree on sort key +
   scoping — folding is a behavior change, fails the pure-refactor gate; standalone follow-up).

## 2026-07-04 — Pre-flight: anchor re-verification vs HEAD e3b67186

All plan anchors verified against current code (symbols authoritative; line numbers matched
exactly at this HEAD):

- `engine.py:690` `curr = workflow.start_node`; `:686-687` guarded visit-count reset — **Verified**
  (Read engine.py:673-758).
- `_run_only_snapshot` at `engine.py:760`; prologue order seed (:783) →
  `initialize_execution_state` (:785) → `restored_nodes` stamp (:786) — **Verified**. Note the
  degraded-advisory emission (:788-789) sits BETWEEN the stamp and `find_node_by_id` (:791) —
  the extraction takes seed + locate only; advisory stays caller-side per plan §A.
- `plan.py:468-495` `_resolve_walk_start`: seed (:491-492) → degraded diagnostic append (:493-494)
  → `find_node_by_id` (:495) — **Verified**. Planner does NOT call `initialize_execution_state`
  here (it runs earlier in `create_planner_shared:527`) — the shared helper correctly excludes it.
- `validate_only_target:402`, `find_node_by_id:511` module-level in engine.py — **Verified**;
  established home for shared engine/planner rules, as the plan states.
- `load_snapshot_or_raise` (workflow_trace.py:270) returns `(events, source_status)`; engine
  threads `snapshot_events=self.snapshot_events`, planner is disk-only — **Verified**; loader
  stays caller-side per plan §A.
- Parity-test recipe `test_plan_batch_sub_workflow_output_shape_matches_engine` at
  test_plan_drift.py:2378 — **Verified**; uses `_runner_run` for the engine side and
  `_build_plan_with_shared` (exposing planner scratch shared) for the planner side.

Delta from plan: **none found**. Line refs at this HEAD match the plan's exactly.

## 2026-07-04 — Baseline capture (pre-edit, HEAD e3b67186)

- `make test`: **8384 passed, 0 failed** (27.79s). No pre-existing failures to carry.
- `make check`: fully green (pre-commit hooks, ruff check+format, mypy 243 files, deptry).

Delta target after Phase 0: 8384 + 1 (new parity test) passed, 0 failed, `make check` green.

## 2026-07-04 — Phase 0 step 1: parity test written + mutation-verified

Added `test_engine_and_planner_walk_entry_state_match` to `tests/test_execution/test_plan_drift.py`
(after the PR #505 recipe test, before the cost-parity section). `@pytest.mark.trace_files`
(both sides read a real on-disk snapshot trace). Shape: 3-node shell workflow, full run +
`save_to_file()`, then `--only middle` through the REAL `WorkflowRunner` (engine side) and the
REAL `_build_plan_with_shared` (planner side). Pins: entry-node id (engine `completed_nodes ==
["middle"]` vs plan single entry), seeded scope (`restored_nodes` vs planner scratch-shared
node keys, both `== ["first"]`), downstream not seeded, and FULL-DICT equality of the seeded
upstream value across sides.

Mutation verification (Edit + revert, never `git stash`):
- Mutation A — planner seed re-forked with `stdout` filtered: caught by the new test **plus**
  one pre-existing test (`test_planner_only_seeds_resolved_content_from_interned_trace`, which
  asserts seeded stdout content). Not "only this test" — recorded, not a failure of the net.
- Mutation B — planner seed re-forked with `exit_code` filtered (a key no other test asserts):
  **exactly 1 failed, 8384 passed** — only the new parity test catches it. This is the unique
  protection the plan asked for: full-dict seeded-value parity vs the existing tests'
  specific-key content assertions.
- Mutation reverted; `git diff src/` clean of mutation (verified below before extraction).

💡 Insight: the pre-existing interned-trace test gives the planner side partial content
coverage, so a *stdout*-level re-fork was already netted; the parity test's marginal value is
(a) any-key drift and (b) cross-side drift — exactly the resume-entry surface Phases 2/4 add to.

## 2026-07-04 — Phase 0 steps 2+3: `seed_walk_entry` extraction + rewire — COMPLETE

Extraction (plan §A, verbatim shape):
- `seed_walk_entry(shared, events, *, entry, start_node)` added module-level in
  `src/pflow/runtime/engine/engine.py`, after `find_node_by_id`, before
  `build_snapshot_degraded_diagnostic` (the established shared-rules home).
  `seed_snapshot_into_shared` imported function-level inside it — preserves the engine's
  existing lazy `workflow_trace` edge posture (`_run_only_snapshot` imports at function level;
  no module-level circularity exists, but the lazy convention is kept deliberately).
- `_run_only_snapshot` rewired: `load_snapshot_or_raise` (still caller-side, threads
  `snapshot_events`) → `seed_walk_entry` → `initialize_execution_state` → `restored_nodes`
  stamp → degraded advisory. The load-bearing seed→init→stamp ordering is preserved.
- `plan._resolve_walk_start` rewired: `load_snapshot_or_raise` (disk-only) → `seed_walk_entry`
  → degraded diagnostic append → return entry node. plan.py imports updated
  (`find_node_by_id`/`seed_snapshot_into_shared` dropped, `seed_walk_entry` added).

Noted micro-ordering shift (accepted, per plan "replacing its lines ~783+791"): on both sides
`find_node_by_id` now runs at the seed site, i.e. BEFORE the degraded advisory/diagnostic and
(engine side) before `initialize_execution_state`. `find_node_by_id` is a pure BFS lookup; the
only observable difference is the pathological unreachable-target `CompilationError` path
(compiler-bug path — the raise now precedes the advisory write into a store that's discarded
on that path anyway). No test pins the old ordering; full suite confirms.

Step 3 recorded: **run-query glob consolidation NOT done** (plan Phase 0.3, deliberate) — the
4 glob sites (`_iter_workflow_traces`, ui `scan_traces`, `report.py` newest-picker,
`trace_loading._autoload_trace` probe) disagree on sort key (mtime vs `_trace_recency_key`)
and scoping (bare vs hash-prefixed glob); folding them is a behavior change, which fails
Phase 0's pure-refactor gate. Standalone follow-up outside Task 164.

Docs: minimal accuracy edits to `runtime/engine/CLAUDE.md` (steps 2/4 of `_run_only_snapshot`)
and `execution/CLAUDE.md` (`--only` snapshot parity bullet) — both named the now-inlined call
shape at those call sites; stale references would mislead the Phase-2 implementer. Not a plan
deviation (plan defers user-facing docs to Phase 6; these are directory-doc hygiene required
by project convention).

Verification vs captured baseline:
- `make test`: **8385 passed, 0 failed** (baseline 8384 + exactly the 1 new parity test).
- `uv run pytest -m trace_files`: 219 passed.
- `make check`: green (ruff, mypy 243 files, deptry, hooks) — re-run after CLAUDE.md edits.
- Parity suites (existing tests in `test_plan_drift.py`, `test_only_snapshot.py`,
  `test_dotted_only_path.py`, `test_plan_classify.py`): passing UNMODIFIED — only a new test
  was appended to `test_plan_drift.py`; zero existing test lines touched (`git diff` confirms
  additions only).

Files changed: `src/pflow/runtime/engine/engine.py` (+seed_walk_entry, rewired
`_run_only_snapshot`), `src/pflow/execution/plan.py` (rewired `_resolve_walk_start`, imports),
`tests/test_execution/test_plan_drift.py` (+1 test), two CLAUDE.md accuracy edits, this log.

**Phase 0 complete. STOPPED for human review per session scope. Not committed (per standing
rule). Next: Phase 1 (loader — ResumeSource, load_resume_source, exceptions).**

## 2026-07-04 — Phase 1 start: anchor re-verification vs HEAD e3b67186

All §B/§D anchors verified against current code (symbols authoritative):
- `_iter_workflow_traces(debug_dir, workflow_path)` workflow_trace.py:110 — yields `(path, data)`
  newest-first; applies hash-prefix glob, `workflow_path` collision guard, `format_version.2.` gate,
  `only_node is not None` exclusion; MUST-NOT-filter-`final_status` invariant intact. **Verified**.
- `_unrecovered_failed_node_ids(final_events, execution_warnings)` :175, `final_events_by_node` :390,
  `_trace_recency_key` :93, `load_full_run_events` :227, `load_snapshot_or_raise` :270 — **Verified**.
- Meta line shape (`_meta_fields` :1009): `execution_id`, `workflow_path`, `content_hash`, `inputs`,
  `only_node`. `final_status`/`failed_node_ids`/`warnings`/`nodes` come from the `run.complete` trailer,
  merged into the flat reconstructed dict by `reconstruct_trace_from_lines` (trace_io.py:236-241).
  So `data.get("resumed_from")` finds it whether on meta OR trailer — the Phase-1 superseded scan works
  BEFORE Phase 2 adds `resumed_from` to META_KEYS. **Verified**.
- Gate line shape `{kind:"gate", node_id, phase("pause"|"resolution"), gate_kind, request?, resolution?}`
  (`record_gate` :678); reader treats `gate`/`node.start` as known-but-ignored sideband
  (`_partition_trace_lines` trace_io.py:151-159) — but ANY line after `run.complete` raises
  (`content after run.complete`), so gate fixtures must splice gate lines BEFORE the trailer. **Verified**.
- Binary placeholder `<binary data: N bytes>` (`_sanitize_for_json` :1276). **Verified**.
- `is_trace_locked` ui/run_tailer.py:136 (`LOCK_SH|LOCK_NB`, separate fd, True/False/None); `runtime/`
  cannot import `ui/` → local ~15-line copy `_is_trace_locked` per plan §B (accepted duplication).
  `_iter_trace_lines` semantics ui/run_node.py:231 (skip non-dict, tolerate 1 truncated final line,
  raise on earlier malformed). **Verified**.
- Exception model `OnlySnapshotMissingError` exceptions.py:908 (class default suggestion +
  `to_diagnostics()` → one ERROR diagnostic, `context={"category":"execution_failure"}`);
  `GateNotInteractiveError` :978 (agent-first what/why/how ladder — the model for
  `ResumeSideEffectConfirmationError`). **Verified**.

Delta from plan: **none**. Building the FULL §D exception family now (all 10 classes) even though
side-effect/stale are consumed in Phase 3 — they are one cohesive family and splitting the exception
file across phases would be worse. `load_resume_source` placed right after `load_snapshot_or_raise`
(plan §B "beside load_full_run_events"); forward refs to `final_events_by_node` (:390) are runtime
calls, so definition order is fine.

## 2026-07-04 — Phase 1 COMPLETE: loader + exceptions + tests

Built (all in one PR, per project convention — phases are commit milestones):

**§D exceptions** (`src/pflow/core/exceptions.py`, +234 lines) — the FULL family:
`ResumeSourceError` base (carries `execution_id`/`trace_path` in context; one ERROR diagnostic modeled
on `OnlySnapshotMissingError`) + 9 subclasses. `ResumeSideEffectConfirmationError` mirrors
`GateNotInteractiveError`'s what/why/how and names K + registry type + "side effects may fire again";
`ResumeStaleWorkflowError` has the two-message hash-differs-vs-unverifiable split;
`ResumeSupersededError.suggestions` is the literal `pflow resume <newer>`. Side-effect + stale are
Phase-3-consumed but built now (cohesive family; splitting the exception file across phases is worse).

**§B loader** (`src/pflow/runtime/workflow_trace.py`, +346 lines) — `ResumeSource` frozen dataclass
(NO node-type field, per the §B vocabulary rule) + `load_resume_source` + helpers: `_select_resume_trace`
(newest-for-workflow via `_iter_workflow_traces`; by-exec-id via bare glob + raw first-line meta check,
mirroring the `--only` exclusion), `_is_trace_locked` (local 15-line flock copy — `runtime/` can't import
`ui/`), `_iter_raw_trace_lines` (gate-line reader, `ui.run_node._iter_trace_lines` semantics),
`_read_trace_meta_line`, `_resolve_resume_entry` (status arms; failed-entry = earliest failed node in
EVENT order), `_raise_gate_stopped_or_generic`, `_seed_scope_events` + `_guard_seed_scope`
(escalation + binary-fidelity). The `incomplete` arm is the Phase-1 stub (refuses); Phase 5 replaces it.

**Tests** (`tests/test_runtime/test_resume_source.py`, 24 tests): selection (newest / by-exec-id /
only-node-skip / missing / one-selector-required), refusal ladder (inline, live-locked [flock held by
the test], superseded, success+degraded, denied, incomplete-stub, gate-stopped [spliced gate lines],
defensive-no-gate), entry derivation (multi-failure event-order = 'zeta' not alphabetical 'alpha';
recovered-failure skipped), seed-scope guards (undecided vs decided escalation; binary in-scope refused
vs downstream-of-K ignored), happy-path ResumeSource fields, null/missing meta.inputs + content_hash.

Mutation-verified (Edit + revert) the two subtle ones:
- entry `min(failed, key=event-index)` → `min(failed)` (alphabetical): only
  `test_multi_failure_enters_earliest_in_event_order` fails. ✅
- drop the by-exec-id `only_node` exclusion: only `test_by_execution_id_skips_only_node_run` fails. ✅
Both reverted; `grep MUTATION` = 0.

💡 Discoveries / decisions during impl:
- **`resumed_from` superseded scan works in Phase 1** even though `resumed_from` joins META_KEYS only in
  Phase 2: `reconstruct_trace_from_lines` merges meta + run.complete trailer into one flat dict, so
  `candidate.get("resumed_from")` finds it wherever the fixture routed it. Verified by the superseded test.
- **Gate fixtures must splice gate lines BEFORE `run.complete`** — `_partition_trace_lines` raises on any
  content after the trailer, and treats `gate`/`node.start` as known-but-ignored sideband. The test helper
  inserts at the run.complete index.
- **Superseded is tested via by-execution-id, not workflow_path**: the workflow_path arm selects the
  NEWEST trace (the resume attempt itself), so a superseded-source scenario is only reachable by naming
  the older attempt's exec id — which is exactly the real agent flow ("I have this old failed run's id").

Verification vs baseline: `make test` **8409 passed** (8385 after Phase 0 + 24 new), 0 failed.
`make check` green (ruff check+format, mypy 243 files, deptry). `test_only_snapshot.py` unaffected (55
passed with the new file). No existing tests modified.

## 2026-07-04 — Phase 1 post-review self-audit (loose-end sweep)

Three loose ends found and closed (all small, all mutation-verified where they touch logic):

1. **Exec-id / workflow_path asymmetry on corrupt traces (real robustness gap).** The workflow_path
   arm skips unparseable traces (via `_iter_workflow_traces`'s `except (JSONDecodeError, OSError)`), but
   the by-exec-id arm called `load_trace_file` bare — a mid-corrupted matched trace would escape as an
   uncaught `JSONDecodeError` traceback (worst outcome for an agent) instead of a clean typed refusal.
   Fixed: the exec-id arm now catches `(JSONDecodeError, OSError)` and skips (→ clean
   `ResumeSourceMissingError`), matching the iterator's posture exactly. Mutation-verified: reverting the
   try/except surfaces the raw `JSONDecodeError` the new test catches.
2. **`_iter_raw_trace_lines` semantics were only exercised on the happy path.** Added two direct tests:
   truncated-final-line tolerance (tail dropped, no raise) and earlier-malformed-line raises. This helper
   is a local copy of `ui.run_node._iter_trace_lines`; pinning its degrade behavior guards against drift.
3. **Built-but-unexercised exception classes.** I built the full §D family in Phase 1 including
   `ResumeSideEffectConfirmationError` + `ResumeStaleWorkflowError` (Phase-3-consumed). Since the code
   ships now, added smoke tests: side-effect names K + type + "side effects may fire again" + `--force` +
   carries execution_id; stale's two-message split (edited vs predates-hash-tracking), both suggesting
   `--force`. Superseded's literal-command suggestion was already pinned by the loader test.

Net: 24 → 29 resume tests. `make test` **8414 passed**, 0 failed. `make check` green. Zero stray mutations.

Deliberately NOT changed (considered, judged correct): the liveness `None`/`False` fall-through (the
failed arm always has `run.complete`, so proceeding is right; the no-fcntl + incomplete case is Phase 5's,
and the Phase-1 incomplete stub refuses regardless); the escalation guard ignoring non-dict/non-str
`escalation` shapes (matches the gate.py marker vocabulary); the `ValueError` for the exactly-one-selector
contract (library-misuse, not a user refusal — mirrors the engine's `resume_from`+`only_node` ValueError).

## 2026-07-04 — Phase 1 test-fidelity audit ("passing the right thing")

Challenge: are the Phase-1 tests catching real bugs, or are they synthetic fixtures encoding
bug-compatible shapes (tests/CLAUDE.md pitfall #19)? All 29 tests hand-built their traces via
`write_trace_jsonl` — so a loader that read a field a real run never writes would stay GREEN. I
verified the load-bearing shapes against the PRODUCERS instead of trusting my fixtures, and added
the keystone that de-risks the lot.

**Verified fixture shapes against producers (not assumed):**
- **on_error_recovery warning** — `set_warnings` stores `Diagnostic.to_display_dict()`, which merges
  `context` into top-level keys via `setdefault` (diagnostic.py:142). So `context["type"]=
  "on_error_recovery"` surfaces as TOP-LEVEL `type` on disk → my recovery fixture's top-level `type`
  is correct, and `_unrecovered_failed_node_ids`'s top-level `warning.get("type")` read is right.
  Was a candidate false-green; confirmed genuine.
- **escalation marker** — matched my guard line-by-line against `engine.gate.detect_escalation`
  (:104-149). Dict-branch (non-empty, no `decision`) and decided-branch (has `decision`) match. But
  found a REAL micro-divergence in the STRING branch (see fix below).

**Real bug found + fixed — escalation string over-permissiveness.** My guard used
`escalation.strip() != ""`; production `detect_escalation` only filters `marker == ""` (line 127), so
a whitespace-only escalation string PAUSES the run in production. My `.strip()` would treat it as
absent and SEED it — replaying an undecided escalation as decided, the exact thing Decision 8 forbids
(the unsafe direction). Aligned to `escalation != ""`. New test
`test_whitespace_only_escalation_string_refused` pins it; mutation-verified (revert to `.strip()` →
only that test fails).

**Keystone test added — a REAL failed run, not a fixture** (`test_real_failed_run_is_resumable_end_to_end`,
`@trace_files`): runs a 2-step shell workflow to failure through `WorkflowRunner`, saves the trace the
production collector actually writes, and loads it. Passes FIRST try — which is itself the proof: if a
real failed event carried `success: bool` instead of the `status` enum my loader reads,
`_unrecovered_failed_node_ids` would find zero failed nodes and the loader would REFUSE (gate-stopped),
so the test would error rather than return `entry="boom"`. It validates against reality: the failed-event
`status` key, the real `node_output` shape (`stdout: "ready"` seeds), a REAL `content_hash` on the meta
line (the synthetic tests use string literals like "hash-v1"), `meta.inputs`, execution order, and
trace-file discovery from a real `save_to_file` filename. This is the single test that makes the 29
synthetic tests trustworthy — without it, green told us nothing about production.

**Kept, not removed** — the synthetic refusal-arm tests (superseded/denied/gate-stopped/escalation/
fidelity/incomplete) test real BRANCHING logic that's hard/expensive to produce with live runs, and the
subtle ones are mutation-verified. They aren't shallow; the keystone de-risks the trace-shape assumption
they share. Residual (noted, not blocking): the gate-stopped arm's "failed + empty failed_node_ids"
claim (Decision 8) is tested with a synthetic trace whose gate-line shape I verified against `record_gate`
(:678) — a real non-interactive gate-stop e2e belongs where gate infra is exercised (Phase 3+).

Net: 29 → 31 resume tests (+ keystone, + whitespace escalation). `make test` **8416 passed**, 0 failed.
`make check` green. Zero stray mutations.

## 2026-07-04 — Verification-gap fix: commit blocked by ruff on the untracked test file

The user hit 3 ruff errors when committing that my `make check` runs did NOT catch. Root cause
(important, general): **`make check` runs `pre-commit run -a`, which only lints files git TRACKS —
it silently skips UNTRACKED files.** `test_resume_source.py` was brand-new/untracked through every
`make check`, so its lint errors were invisible to my gate until the user staged it (→ `A`) and
committed. Not a flake; a real hole in how I verified.

Errors + fixes (all in `tests/test_runtime/test_resume_source.py`):
- **S108** (flake8-bandit): the `WF = "/tmp/project/wf.pflow.md"` identifier tripped the
  hardcoded-temp-path rule. It's only an opaque `workflow_path` string (never a real file) → changed
  to `/work/project/wf.pflow.md`. All fixtures write to `tmp_path`; this constant is just the trace's
  stored path key, so the value is immaterial as long as write/read agree.
- **RUF043** ×2: `match="[Ii]nline"` / `match="[Ii]nterrupted"` contain regex metacharacters →
  made raw (`match=r"..."`). Intentional patterns; raw string makes intent explicit.

Verified the fix the RIGHT way this time — bypassing pre-commit's untracked blindness:
- `uv run --frozen ruff check` DIRECTLY on all 6 touched python files → All checks passed.
- `uv run pre-commit run --files <every changed file>` (lints named files regardless of tracked
  status — the true commit gate) → all hooks Passed.
- `make test` 8416 passed, mypy clean, resume tests 31 passed after the `WF` value change.

**Process note for future phases: after adding a NEW file, run `ruff check <file>` directly or
`pre-commit run --files <file>` — `make check` alone will not lint it until it is tracked.** The tree
is now commit-clean.

**Makefile fix — `make check` no longer has the untracked blind spot.** Root insight: the git-scoping
is a PRE-COMMIT behavior (it filters by `git ls-files`), not a ruff behavior — `ruff check .` is
git-agnostic and lints staged/unstaged/untracked alike. Added a git-agnostic ruff pass as `check`'s
FIRST lint step (before pre-commit), so a new file's lint errors fail the gate even before it's staged:
```
@uv run ruff check .
@uv run ruff format --check .
@uv run pre-commit run -a   # still runs the full non-ruff hook suite (yaml/json/MDX/…)
```
`make` stops on the first non-zero command, so an untracked lint error now fails fast. Verified: an
untracked file with an S108 error is caught by the new `ruff check .` step (pre-commit -a skipped it);
the clean tree still passes ruff + pre-commit + mypy + deptry. Cost: ruff runs twice (~instant).

**Phase 1 complete. STOPPED for human review per instruction. Not committed. Next: Phase 2 (engine
re-entry + self-contained attempt trace).**

## 2026-07-04 — Post-review self-audit (loose-end sweep)

- **Mutation C — ENGINE-side re-fork** (gap closed): the earlier mutations only re-forked the
  planner side; engine-side coverage was "by symmetry" of the full-dict equality. Verified
  empirically: re-inlined the old seed code in `_run_only_snapshot` with `exit_code` filtered →
  **exactly 1 failed, 8384 passed** (only the parity test). Reverted; suite back to 8385
  passed + `make check` green. The test docstring's "re-fork either side" claim is now
  verified in both directions.
- **Fixture assumption documented**: the planner-seeded-set derivation (`any workflow-node key
  in scratch shared was seeded`) holds because shell nodes are cache-disabled by default — a
  memo-hitting node type in this fixture would make `apply_memo_hit` write the target's key
  and false-fail. One-line comment added in the test so a future fixture edit fails with
  understanding, not confusion.
- Remaining known non-issues, deliberately left: micro-ordering shift (logged above, for
  reviewer sign-off); `make test-e2e` not run (not in the Phase-0 gate; no e2e-relevant
  surface touched — engine/planner paths are covered by the default suite); redundancy between
  the parity test's engine-side assertions and `test_only_snapshot.py` (intentional — the
  parity test needs its own oracle on both sides).

## 2026-07-04 — Phase 2 start: anchor re-verification vs HEAD 66652b83 (phases 0+1 committed)

Session scope: **Phase 2 only** (engine re-entry + self-contained attempt trace), then stop for
human review. All §C anchors verified against current code (symbols authoritative):

- `WorkflowEngine.__init__` (engine.py:607) — `only_node`/`workflow_path`/`snapshot_events`
  precedent for the three new resume params. **Verified**.
- `_run_inner` (:702): `--only` early-return (:711-712) → guarded visit-count reset (:715-716) →
  `curr = workflow.start_node` (:719) — the resume arm replaces exactly that assignment. **Verified**.
- `_run_only_snapshot` prologue (:807-815): `load_snapshot_or_raise` → `seed_walk_entry` →
  `initialize_execution_state` → `restored_nodes` stamp — the template `_prepare_resume` mirrors.
  **Verified** (Phase-0 shape).
- `record_node_execution` (workflow_trace.py:1042): event construction :1074-1095; `node_output`
  stamped only when truthy (:1088 `if node_output:`) — the §C step-4 `is not None` change site.
  `_check_reserved_collision` fires only on run-scoped correlation stamping (:1113) — a freshly
  built restored event (never a copied one) passes. **Verified**.
- `_aggregates` (:1375): `"nodes_executed": len(self._top_level_events())` (:1392) — the one
  inflating count. `_collect_llm_summary` filters `status=="cached"` at every tier via
  `iter_llm_leaves(descend_cached_subtrees=False)` (:1595 + trace_tree.py:164/179);
  `_determine_trace_status` reads final-event status (cached counts as success). **Verified** —
  no other cached-count aggregate exists (braindump check: searched `_aggregates` payload; only
  `nodes_executed` needs the exclusion).
- Collector `__init__` (:885) + `_meta_fields` (:1362) + `META_KEYS` (core/trace_io.py:35, with
  the fixture-builder routing note at :32-34 — `tests/shared/trace_jsonl.py:98` iterates it).
  **Verified** — both edits must land together, as the plan says.
- `TRACE_FORMAT_VERSION = "2.5.0"` (:45); `tests/test_runtime/test_trace_format_2_2.py:26` pins
  it. `_iter_workflow_traces` gates on `startswith("2.")` — 2.6.0 passes. **Verified**.
- `runner.run` (:91) / `_compile_and_execute` (:246): collector constructed at :154 (before
  engine), engine at :307 — `resumed_from` can be set at construction, before `start_streaming`
  (invariant: it rides `_meta_fields`). `gate_resolver` kwarg precedent at :98. **Verified**.
- Success surface: `format_execution_success` builds `execution_dict` with the `--only` block at
  success_formatter.py:120-126; `format_only_indicator` (:447) + `_append_execution_steps`
  (:526, MCP text); CLI mirrors via `workflow_output.py::_only_indicator_line` (:802) +
  `_display_execution_summary` (:834) + the `-p` gate (:774-776). `build_execution_steps`
  relabels `restored_nodes` → `not_executed` (execution_state.py:118) — already generic, works
  for resume unchanged (pin with a test). **Verified**.
- `_add_llm_data` (:1516) promotes `node_output["llm_usage"]` → `event["llm_call"]` — a restored
  LLM event WILL carry `llm_call` (from the source event's node_output), which is fine: cached
  status excludes it from run cost at every tier. (Note: plan §G's "restored upstream LLM nodes
  carry no `llm_call`" guide-wording is inaccurate on this point — flagged for Phase 6, where the
  guide text is written; the under-reporting caveat itself still holds because `llm_prompt`
  evidence is what cache analysis needs and that IS absent.)

Delta from plan: **one gap found** — §C step 7's indicator text `⤷ Resumed from <id> at '<K>' —
N upstream steps restored` requires K at the display layer, but the two locked §-step-3 stamps
(`restored_nodes`, `resumed_from`) don't carry K. Minimal fix consistent with plan intent and the
`only_node` precedent: stamp a third engine-only key `__execution__["resume_entry_node"]` in
`_prepare_resume` (never in `new_execution_state()`, same as the other two) and thread it through
`execution_dict` for the text renderers. JSON still carries the plan's two specified fields
(`resumed_from`, `nodes_restored`) plus `resume_entry_node` (machine-useful; the test asserts the
plan's two, and their absence on non-resumed runs).

## 2026-07-04 — Phase 2 COMPLETE: engine re-entry + self-contained attempt trace

Built (plan §C, all verbatim unless noted):

**Engine** (`src/pflow/runtime/engine/engine.py`):
- `WorkflowEngine.__init__` +3 params (`resume_from`/`resume_events`/`resume_source_id`,
  the only_node/snapshot_events precedent) + `ValueError` when `resume_from`+`only_node` both set.
- `_run_inner` walk entry now `curr = self._walk_entry(workflow, shared)` — a 4-line helper
  (start_node, or `_prepare_resume` when resuming). Extracted rather than inlined because the
  inline `if` pushed `_run_inner` over ruff C901 (10); the helper is the honest fold, not a noqa.
- `_prepare_resume`: `seed_walk_entry` (wrapped `except CompilationError → ResumeNotResumableError`
  naming K, carrying the source execution_id) → `initialize_execution_state` → stamps →
  Decision-6 re-record loop (`record_node_execution(cached=True, restored=True, duration 0)`,
  guarded `if self.trace is not None` for collector-less library engines). No `only_node` stamp,
  no `loop_runtime_scope`, per plan.

**Trace** (`src/pflow/runtime/workflow_trace.py` + `core/trace_io.py`):
- `record_node_execution(restored=False)`: `event["restored"]=True`; node_output stamp is
  `node_output or (restored and node_output is not None)` — the §C-step-4 empty-`{}` fidelity fix,
  restored-only so the pre-existing truthy stamp is byte-identical for every other caller.
- `_aggregates`: `nodes_executed` excludes `restored` events (the ONE inflating count — verified
  no other cached-count aggregate exists, closing the braindump's open check).
- Collector `__init__` + `_meta_fields` gain `resumed_from`; `META_KEYS` gains it (both together);
  `TRACE_FORMAT_VERSION` → `2.6.0` (additive; `startswith("2.")` gates unaffected — full suite +
  `-m trace_files` green). Fixture builder needs no edit (it iterates META_KEYS, skip-if-absent).
- C901 fold: the Task-172 correlation-stamping block extracted to `_stamp_correlation` (cohesive,
  comment preserved as docstring) — same reason as `_walk_entry`.

**Runner** (`execution/runner.py`): `run(..., resume_source: ResumeSource | None = None)` kwarg
(125 `gate_resolver` precedent; TYPE_CHECKING import only — no new runtime module edge);
collector gets `resumed_from` at CONSTRUCTION (before `start_streaming`, per the invariant);
engine gets the three resume params. Added a library-misuse `ValueError` when
`resume_source.entry_node_id is None` (mirrors the engine's mutual-exclusion ValueError) — a
None entry would silently run the whole workflow while claiming a resume.

**Success-path visibility (§C step 7)** — with the ONE logged deviation:
- DEVIATION (plan gap, logged in the Phase-2 pre-flight): the specified indicator text includes
  K, but the two locked §-step-3 stamps don't carry it → third engine-only stamp
  `__execution__["resume_entry_node"]` (mirrors the `only_node` precedent), threaded through the
  `execution` dict alongside the plan's two fields (`resumed_from`, `nodes_restored`).
- `format_resume_indicator` (success_formatter, beside `format_only_indicator`, same two-form
  shape) + MCP text emission in `_append_execution_steps`; CLI default summary +
  `-p` mode emission via `_resume_indicator_line` / `_emit_mode_indicators`
  (renamed from `_emit_only_indicator` — it now emits both mode flags; `-p` early-return gate
  extended to resumed runs, same mode-signal doctrine).

**Tests** (`tests/test_runtime/test_resume_engine.py`, 14 tests, `trace_files`; +format-version
bump in `test_trace_format_2_2.py`): all plan-listed scenarios — e2e llm re-entry (upstream llm
called ONCE across both runs, by mock call count), *--only-after-resume poisoning regression,
*resume-of-a-resume (seeds from attempt A's trace alone; direct pin that A's events include the
re-recorded step1), restored-event shape/cost/nodes_executed/meta-lineage/source-byte-identical,
superseded-after-attempt (pins META_KEYS routing feeds the Phase-1 scan), empty-`{}` re-record +
re-seed, visibility (JSON fields + ⤷ text + not_executed relabel + non-resumed carries neither),
`format_resume_indicator` forms, branch/coalesce (hand-written .pflow.md: code-node router,
K on branch A, converged `??` output reads the RESTORED a1 value; untaken branch absent),
K-removed typed refusal (added beyond plan list: new engine branch shipped now → smoke-tested,
the Phase-1 precedent), engine + runner ValueError guards.

Mutation verification (Edit + revert, never git stash; `grep MUTATION` = 0 after):
- Re-record loop disabled → exactly the 3 self-containment tests fail (poisoning regression,
  resume-of-a-resume, restored-events shape); 8469 others pass. ✅ (both starred tests)
- `nodes_executed` exclusion reverted → exactly 1 fails (restored-events/aggregates). ✅
- `is not None` stamp reverted to truthy → exactly 1 fails (empty-output fidelity). ✅

UI check: the plan's real-browser step remains MANUAL for the reviewer (`make ui-build` +
`pflow ui` against a resumed run). De-risked programmatically here: drove the REAL
`scan_traces` (/api/runs source) + `RunTailer._consume` projection over a real resumed attempt
trace — the attempt lists with `resumed_from` on meta; the restored node projects as
`status:"cached"` (frontend allowlist) with `restored` stripped by the projection (never reaches
SSE); `run-complete` reports the excluded `nodes_executed`. No tailer errors.

💡 Discoveries:
- Plan §G's guide wording "restored upstream LLM nodes carry no `llm_call`" is inaccurate:
  `_add_llm_data` re-promotes the source event's `node_output.llm_usage` → restored LLM events DO
  carry `llm_call` (cost-excluded via cached status — verified by the cost test asserting 0.5,
  not 1.0). The §G caveat itself still holds (`llm_prompt` evidence IS absent). Flag for Phase 6.
- Seed scope can include a recovered-failure node (failed final event + on_error warning);
  re-record flips it to cached-success in the attempt trace — the plan's locked step-4 shape;
  same semantics `--only` seeding already has for degraded snapshots. Noted for the reviewer,
  not changed.

Docs: minimal accuracy edits (Phase-0 hygiene precedent) — `runtime/CLAUDE.md` (2.6.0 bullet,
`nodes_executed` exclusion, `__execution__` resume stamps), `runtime/engine/CLAUDE.md` (walk
entry), `execution/formatters/CLAUDE.md` (`format_resume_indicator` + renamed emitter), and the
stale `_emit_only_indicator` references in success_formatter/test docstrings.

Verification vs baseline: `make test` **8430 passed, 0 failed** (8416 after Phase 1 + exactly the
14 new tests; format-version test renamed, not added). `uv run pytest -m trace_files`: 233 passed.
`make check` green (git-agnostic ruff first — the Phase-1 Makefile fix covers the new untracked
test file; also ran `pre-commit run --files` on every touched file directly). Zero existing test
lines changed except the two stale-reference docstring/version updates the plan called for.

**Phase 2 complete. STOPPED for human review per session scope. Not committed. Next: Phase 3
(CLI `pflow resume` + side-effect policy). Reviewer to-do: the manual browser check
(`make ui-build` + `pflow ui` over a resumed run).**

## 2026-07-04 — Phase 2 post-review self-audit (loose-end sweep, on request)

Re-audited the whole phase against the plan's invariant checklist + the braindump's
NEEDS-VERIFICATION list. One real gap found and closed; two probes run; the rest confirmed sound.

**Gap closed — restored re-record + blob interning was NOT actually covered.** The braindump
expected the resume-of-a-resume test to cover the "re-record re-interns blobs with a fresh
per-run declared set" assumption end-to-end — but every output in my tests was under
`INTERN_MIN_BYTES` (1024), so interning never fired. Added
`test_restored_large_output_reinterns_blob_and_round_trips`: a ≥2 KB upstream llm response →
resume (attempt A fails at step3) → asserts ON DISK that A's restored step1 event carries the
`$pflow_blob` sentinel REF (never the body) with the body declared in an inline `blob` line →
second resume resolves and seeds the FULL value, step3's stdout proves it. Passed first try;
the ref-shape assertion makes it non-vacuous (a re-record that bypassed `_flush_event`'s
interning would fail it). Suite now **8431 passed** (8430 + 1); `make check` green.

**Probes run (no code change needed):**
- `pflow report` over a resumed attempt trace: generates cleanly; the restored node renders as a
  `cached` pipeline row (the accepted Decision-6 labeling); fresh K renders `success`.
- (Earlier this session) UI `scan_traces` + `RunTailer._consume` — logged above.

**Confirmed sound, deliberately unchanged:**
- Refusal-path `shared_after` on K-removed carries seeded upstream but no `__execution__` —
  same discard-path shape as `--only`'s unreachable-target (Phase-0 log); harmless.
- `resume_events=None` library misuse → loud unresolved-reference failures downstream, never
  silent; the runner always threads real events.
- Memo-cache reachability for `handle_cached_execution`'s removed failure-clear: still
  unreachable under resume (fresh store has no `__failures__`; error results never cached).
- JSON `nodes_executed` (metrics/steps-derived) and the trace trailer agree — restored nodes
  never reach metrics, and steps relabel them not_executed.

**Known remaining gaps, accepted with rationale (for the reviewer):**
1. The real-browser UI check (`make ui-build` + `pflow ui`) — plan-designated MANUAL.
2. CLI-side indicator WIRING (`_resume_indicator_line` / `_emit_mode_indicators` /
   `_display_execution_summary` resume block) has no direct Phase-2 test — the CLI cannot reach
   a resumed run until Phase 3's `resume.py` exists. Text drift is impossible (single SSoT
   `format_resume_indicator`, unit-pinned + MCP-text-pinned); Phase 3's CliRunner tests must
   exercise the wiring e2e (noted as a Phase-3 test obligation).
3. A recovered-failure node in seed scope re-records as cached-success in the attempt trace
   (plan-locked §C step-4 shape; same semantics --only seeding has for degraded snapshots).
4. Plan §G's "restored LLM nodes carry no llm_call" wording — correct the guide text in Phase 6.

## 2026-07-04 — High-value test hunt (user-requested; hypothesis-driven, not coverage)

Enumerated production-failure hypotheses the suite couldn't see, verified each empirically.

**REAL BUG FOUND (unfixed, surfaced for owner decision) — refused-resume chain poisoning.**
A resume attempt that fails BEFORE K executes (reachable via --force-after-edit resume, a
library caller, or Ctrl+C-before-K until Phase 5 lands) streams its meta line (with
`resumed_from`) at run start, records ZERO events, and the runner's finalize writes a
`run.complete` whose `_determine_trace_status` on empty events returns **"success"**. Verified
end-to-end: the on-disk attempt claims `final_status: "success", nodes: 0,
resumed_from: <run1>`. Consequences (reproduced): `resume <run1>` → `ResumeSupersededError`
pointing at the empty attempt; `resume <attempt>` → `ResumeNothingToResumeError` ("the most
recent run already succeeded" — FALSE). The chain is permanently wedged; only manual trace
deletion or a from-scratch re-run escapes. Two distinct defects:
(a) chain policy — the superseded scan counts a zero-work attempt as consuming the chain;
(b) trace honesty — an exception-terminated run finalizes as "success" on disk (pre-existing
    for any zero-event run; resume makes it consequential because of `resumed_from`).
Options prepared for the owner (touches Decision-ledger rule "resume targets the newest
attempt", so NOT silently picked): (A) loader-side — an attempt with no non-restored events
never supersedes its source (consistent with the spec's own consumption rationale: nothing was
consumed); (B) producer-side — runner stamps the collector on its exception path so
zero-event exception runs finalize "failed" (more honest, but does NOT unwedge on its own);
(C) document-only. Recommendation: A now + B as a follow-up issue.

**Two high-value tests added (both audit-verified claims that were suite-untested):**
- `test_restored_subworkflow_and_batch_hosts_are_childless_and_reseed` — sub-workflow AND batch
  hosts upstream of K: attempt trace's restored host events carry NO
  `sub_workflow_events`/`batch_items` (the Decision-6 drop), reconstruct doesn't choke on
  childless cached hosts, and a resume-of-a-resume seeds both hosts' outputs
  (`${sub.final}`, `${fan.results[0].stdout}`) from the attempt trace alone.
- `test_loop_k_restarts_at_iteration_one` — Decision-9 pin: loop-K resume restarts at
  iteration 1 (iteration log reads ["1"] then ["1","1","2","3"]), never continues at 2.
  Bonus finding while writing it: the template validator REJECTS string-truthy `while:`
  conditions (footgun guard) — the test uses a `result: bool` code-node loop, the sanctioned
  shape.

**Shallow-test audit of the existing 15**: no removals. The two ValueError guard tests and the
indicator unit tests are intentionally small contract pins (the indicator SSoT is the CLI
anti-drift mechanism); everything else is e2e on real traces with mutation-verified assertions.
Known soft spot kept: the empty-`{}` fidelity test is unit-level (record+seed) because no real
node cleanly produces `{}` — the mechanism is mutation-pinned.

Verification: `make test` **8433 passed** (8431 + 2), `make check` green.

## 2026-07-04 — Wedge fix: writer honesty + chain-consumption predicate (owner-directed via the simplicity lens)

The owner answered the wedge surfacing with the project lens ("simplicity of the FINAL code —
what would the top 10% do; producers self-describing, readers dumb"). Re-derived under it, my
earlier Option-A recommendation was WRONG-SHAPED: a loader-only guard is reader-side
compensation for a writer-side lie. Implemented the two-layer fix, each one small change at the
layer that owns the truth:

1. **Writer honesty** (`_determine_trace_status`): a `run.complete` with ZERO node events now
   reports `failed`, never `success` — nothing executed (every workflow has ≥1 node; gate
   stops are handled first via `gate_outcome`). Fixes the on-disk lie for EVERY consumer: the
   UI run list showed a crashed pre-first-node run as ✓ success; `--only`'s snapshot loader
   was safe only by accident (empty-nodes no-match). Updated the one test that had encoded the
   lie (`test_streaming_zero_event_run_writes_meta_and_run_complete` — its real purpose is
   transport validity; the `success` assertion was incidental). Full suite confirms nothing
   else depended on it.
2. **Chain policy** (`load_resume_source` superseded scan): an attempt supersedes its source
   only when it CONSUMED the chain — `_attempt_consumed_work(candidate)` (≥1 non-`restored`
   event) OR the candidate is LIVE (`_is_trace_locked(candidate_path) is True` — mid-first-step
   an attempt has no terminal event yet; without the liveness clause the fix would have opened
   a minutes-wide double-resume race for the duration of K's first execution). This is not a
   reader nuance bolted on: "newest attempt supersedes" was always a proxy for consumption —
   the spec's own rationale ("a chain with a newer attempt = already consumed"). A dead
   zero-work attempt consumed nothing. **Ledger note for the reviewer:** this refines the
   LETTER of the lineage rule "resume targets the newest attempt in a chain" while preserving
   its stated rationale; flagged for explicit sign-off. Task 171's `resume list` should reuse
   `_attempt_consumed_work` (noted in its docstring).

Regression test `test_refused_attempt_does_not_wedge_the_chain` (the exact reproduced wedge):
refused --force-style resume after K rename → attempt trace says `failed` with zero events and
`resumed_from` intact → source resumes cleanly after the workflow is restored → the refused
attempt itself refuses via the Phase-1 defensive arm (now REACHABLE in production — its
"should be impossible today" comment no longer holds; message stays accurate).

Mutation-verified both halves independently: writer-honesty reverted → exactly the 2 status
tests fail; predicate reverted (unconditional supersede) → exactly the wedge test fails. Both
reverted, `grep MUTATION` = 0.

Verification: `make test` **8434 passed** (8433 + 1 wedge test), `make check` green.

Deferred, deliberately: the workflow-name arm (`pflow resume <wf>`) after a refused attempt
selects the zero-event trace as "newest" and gives the generic defensive refusal instead of
finding the older resumable run — NOT fixed here because a selection-skip on zero-events would
break Phase 5's killed-mid-first-node case (dangling `node.start`, zero terminal events, which
Phase 5 makes resumable); the by-execution-id arm works, and Phase 3/5 own selection messaging.
Left as a note for the Phase-5 implementer.

## 2026-07-04 — SESSION END STATE (Phase 2 + follow-ups, awaiting human review)

Supersedes the "STOPPED" line inside the Phase-2-COMPLETE entry above — three more entries
landed after it (self-audit, test hunt, wedge fix). Current truth:

- **Scope delivered**: Phase 2 in full, PLUS (owner-requested) the high-value-test hunt and the
  refused-attempt wedge fix (writer honesty + chain-consumption predicate).
- **Verification**: `make test` **8434 passed, 0 failed** (baseline 8416 at session start);
  `make check` green; `pytest -m trace_files` green; zero stray mutations.
- **Tests**: `tests/test_runtime/test_resume_engine.py` — 18 tests (the 14-test Phase-2
  battery + blob round-trip + host/loop interaction pins + wedge regression); 5 mutations
  run across the session, each killed by exactly the intended test(s).
- **Working tree (uncommitted, per standing rule)** — src: `runtime/engine/engine.py`,
  `runtime/workflow_trace.py`, `core/trace_io.py`, `execution/runner.py`,
  `execution/formatters/success_formatter.py`, `cli/workflow_output.py`; tests: NEW
  `test_resume_engine.py`, edits to `test_emit_time_trace.py` (zero-event status),
  `test_trace_format_2_2.py` (2.6.0), `test_success_formatter.py` (docstring ref); docs:
  `runtime/CLAUDE.md`, `runtime/engine/CLAUDE.md`, `execution/formatters/CLAUDE.md`; this log.
- **Reviewer sign-off wanted on**: (1) `resume_entry_node` third stamp (plan-gap deviation);
  (2) the superseded-rule refinement (letter of the lineage ledger rule; rationale preserved);
  (3) zero-event traces now `failed` (global trace-semantics change, 1 test updated);
  (4) manual browser check `make ui-build` + `pflow ui` over a resumed run.
- **Next**: Phase 3 (CLI `pflow resume` + side-effect policy). Phase-3 obligations noted in
  entries above: CliRunner tests must exercise the CLI indicator wiring; Phase-5 note on the
  workflow-name-arm selection after a refused attempt.

## 2026-07-04 — Phases 3-6 session start: scope + anchor re-verification vs HEAD 34324519

**Scope this session (per instruction "Implement the remaining phases, starting with phase 3"):**
Phases 3, 4, 5, 6 — one PR, phased commit milestones, each landing green. Phases 0/1/2 are
committed (`34324519 phase 2 completed`); working tree clean at session start.

**Baseline (committed HEAD 34324519):** `make test` **8434 passed, 0 failed** (18.4s). Target
after each phase = baseline + that phase's new tests, `make check` green.

**§E / §D / compiler anchors re-verified against current code (symbols authoritative):**
- `load_resume_source(workflow_path=None, execution_id=None, *, debug_dir=None) -> ResumeSource`
  at `workflow_trace.py:600`; `ResumeSource` frozen dataclass `:324` (fields path/execution_id/
  entry_node_id/last_completed_node_id/events/inputs/content_hash/final_status). Phase-1 `incomplete`
  arm is still the stub (`:530-540`) — so `entry_node_id` is NEVER None out of the loader until
  Phase 5. **Verified**. CLI §E step 4 (between-nodes) is therefore unreachable in Phase 3 — deferred
  to Phase 5 as the plan phases it.
- Full §D exception family present (`exceptions.py:1125-1357`): `ResumeSourceError` base +
  9 subclasses incl. `ResumeSideEffectConfirmationError(node_id, node_type, *, execution_id,
  trace_path)` and `ResumeStaleWorkflowError(*, hash_known, execution_id, trace_path)`. **Verified**.
- `_default_cache_for_node_type(node_type) = node_type == "llm"` (`compiler.py:643`) — the §E-step-5
  `is_side_effecting` promotion site. **Verified**.
- `WorkflowRunner.run(..., resume_source=None)` (`runner.py:104`) fully threads collector
  `resumed_from` + engine `resume_from`/`resume_events`/`resume_source_id`; guards `entry_node_id is
  None` (`:130-135`). **Verified** — CLI just builds the `ResumeSource` + merges inputs + calls run.
- `_workflow_path_id(resolved)` (`runner.py:58`); `resolve_workflow` (`workflow_resolver.py:66`);
  `workflow_content_hash(ir)` (`core/workflow_id.py:62`); `can_prompt(output_controller)`
  (`gate_prompt.py:37`); `_create_workflow_metadata` (`workflow_output.py:978`);
  `parse_workflow_params` (`param_parsing.py:49`, only processes `=`-bearing tokens). **Verified**.
- Phase-2 display wiring already reads the resume stamps: `success_formatter.py:132-136` populates
  `execution_dict` with `resumed_from`/`nodes_restored`/`resume_entry_node`;
  `workflow_output.py:820-903` emits the `⤷ Resumed` indicator. So a resume routed through
  `execute_json_workflow → runner.run(resume_source=)` displays the indicator with ZERO new display
  code — the CLI only needs to thread `resume_source`. **Verified**.
- `trace.execution_id` attribute (`workflow_trace.py:982`) — available for the §E-step-10 failed-run
  resume-hint. Registration point: `main.py:136-168` (imports + `cli.add_command`). **Verified**.

Delta from plan: **none**. Line refs matched at this HEAD.

**Phase-3 dry-run decision (recorded to avoid a lying surface):** the plan's §E signature lists
`--dry-run`, but its threading into `runner.plan`/`plan.py` is Phase 4 (§F). Shipping a `--dry-run`
flag in Phase 3 that routed to `runner.plan` WITHOUT resume threading would silently plan the whole
workflow from the start — a silent lie (the exact failure mode the plan warns against). So Phase 3's
`resume` command omits `--dry-run`; Phase 4 adds the flag together with its plan threading + the
parity test. No broken flag ships at any milestone (one PR).

## 2026-07-04 — Phase 3 COMPLETE: CLI `pflow resume` + side-effect policy

Built (plan §E steps 1-3, 5-10; step 4 is Phase 5):

**`is_side_effecting` promotion (§E step 5):** new public `is_side_effecting(node_type) = node_type
!= "llm"` in `compilation/compiler.py`; `_default_cache_for_node_type` now `return not
is_side_effecting(node_type)` (single source). Exported from `runtime/compilation/__init__.py`.

**`_workflow_path_id` → public `workflow_path_id`** (`execution/runner.py`) + back-compat alias —
the CLI needs the canonical workflow identifier to find the source trace.

**`ResumeSource.workflow_path` field added** (DEVIATION from plan §B's field list — recorded):
plan §E step 2a said the CLI reads the source's `workflow_path` from the trace meta. The loader
already parsed it (`data.get("workflow_path")`); carrying it on `ResumeSource` (the "readers stay
dumb / self-contained" doctrine) is cleaner than the CLI re-opening a file the loader just read.
One field, threaded from the existing `source_workflow_path` local; the one direct-construction
test (`test_resume_engine.py:144`) updated. Phase-1 tests assert individual fields (never the full
set) so they're unaffected. Rationale: simplest FINAL code, no re-read.

**`cli/commands/resume.py`** — the command. Flow: split TARGET + `key=value` (TARGET required →
usage error 2; stray `-flag` → usage error) → existence-based disambiguation (uuid-shaped: try
`load_resume_source(execution_id=)` first, fall back to workflow-name on `ResumeSourceMissingError`
ONLY, combined missing error if both miss so no wrong-namespace "did you mean" leaks) → content-hash
gate (`ResumeStaleWorkflowError`, two messages) → side-effect policy (llm silent; side-effecting +
non-TTY → `ResumeSideEffectConfirmationError`; TTY → `click.confirm` default-No, declined → clean
exit 1; `--force` bypasses both gates) → merge `{**source.inputs, **cli_params}` → dispatch through
`run.py`'s `execute_json_workflow` (resume rides `ctx.obj["resume_source"]`; the runner threads it —
one added line in `execute_json_workflow`'s `runner.run(...)` call). K's node type read from
`resolved.ir["nodes"]` (registry vocab), NEVER a trace event's class name (the §B trap; pinned).
Registered in `main.py`.

**Failed-run resume hint (§E step 10):** `_maybe_echo_resume_hint` in `run.py`, called in the run
`finally` after trace finalize — emits `To resume from the failed step: pflow resume <exec-id>` on a
FAILED run with a saved trace; skipped on success, on a clean gate DENIAL (exit 3), and under
`--no-trace` (gated on `ctx.obj["trace_file"]`). Respects `-p`.

**Display:** ZERO new display code — Phase-2 already wired the `⤷ Resumed` indicator + JSON
`resumed_from`/`nodes_restored`/`resume_entry_node` off the execution dict; routing a resume through
`execute_json_workflow` surfaces them for free.

**Tests** (`tests/test_cli/test_resume_cli.py`, 28 tests, `trace_files`, real `cli` group +
`Path.home`→tmp_path so trace write+read align): by-exec-id re-entry (upstream restored, indicator),
by-path, key=value override (pinned upstream-not-rerun), side-effect non-TTY hard error (names K +
type + `--force`), `--force` bypass, TTY confirm yes/no (patched `can_prompt`+`click.confirm`),
llm-K silent (flaky llm; `click.confirm` patched to `pytest.fail` — proves no prompt), stale-hash
refusal + `--force` override + unverifiable-message unit, mistyped-uuid combined error (no "did you
mean"), uuid-shaped saved-name existence precedence, nothing-to-resume on success, JSON refusal
shape (exit 1, execution_id in context), bare/stray usage errors (exit 2), failed-run hint present /
omitted-under-`--no-trace`, and the `is_side_effecting` vocabulary matrix (llm→False,
shell/code/http/mcp/claude-code/read-file/write-file→True, `LLMNode`→True = the class-name trap).

Mutation-verified (Edit + revert, `grep MUTATION`=0 after):
- `resume_source=None` in `run.py` threading → re-entry + llm-silent tests fail (whole workflow ran,
  no indicator). ✅ (also motivated strengthening the override test with an upstream-not-rerun pin.)
- skip `_confirm_or_refuse_side_effect` → non-TTY hard-error + confirm-no tests fail. ✅

Manual e2e smoke (real `pflow`, real `~/.pflow/debug`): fail-demo run → hint printed → resume by
exec-id (mode override + `--force`) restores step1, runs step2+step3, shows the indicator, correct
output; no-`--force` → side-effect refusal; edited workflow → stale refusal; mistyped uuid →
combined missing; bare resume → usage exit 2. All as designed.

Verification: `make test` **8462 passed, 0 failed** (8434 + 28). `make check` green (ruff
git-agnostic + format + pre-commit + mypy 244 files + deptry). Phase-1/2 resume suites unaffected
(77 passed together). No existing test lines changed except the one `ResumeSource(...)` construction.

**Next: Phase 4 (dry-run parity, Decision 2) — §F threading + `pflow resume --dry-run` + parity test.**

## 2026-07-04 — Phase 4 COMPLETE: dry-run parity (Decision 2)

Built (plan §F):

**Planner threading:** `resume_from`/`resume_events`/`resume_source_id` through `build_plan` →
`_build_plan_with_shared` → `_resolve_walk_start` (`execution/plan.py`). `_resolve_walk_start` now
returns `(walk_start_node, ResumePlanInfo | None)`; the resume arm calls the SAME `seed_walk_entry`
the engine's `_prepare_resume` uses (Phase-0 shared helper), wrapped in the IDENTICAL
`except CompilationError → ResumeNotResumableError` (K-removed guard, in lockstep on both paths).
Resume deliberately does NOT set `state.only_node` (the walk continues across the whole tail, unlike
`--only`). Recursion never passes resume params, so `_force_downstream` (sub-workflow BFS) is
unaffected — top-level K only, per scope.

**`ResumePlanInfo` + `Plan.resume`** (`execution/result.py`, new frozen dataclass): carries
`entry_node`, `restored_nodes`, `execution_id` — the honesty surface. `runner.plan(...,
resume_source=None)` kwarg threads it (same shape as `run`).

**Formatter (`plan_formatter.py`):** text gains a header line `Resuming from '<K>': N upstream steps
restored from <exec-id> (plan + cost cover this step onward).`; JSON gains a `resume` block
(`entry_node`/`restored_nodes`/`execution_id`). Extracted `_resume_header_line` + used
`filter(None, (header, ...))` to fold the line WITHOUT a new branch — `format_plan_text` was already
at the C901 budget (10); the fold keeps it there (honest, not a `# noqa`).

**CLI (`resume.py`):** `--dry-run` flag added; `_dispatch_resume` sets `ctx.obj["dry_run"]` so
`execute_json_workflow` → `_display_plan_result` → `runner.plan`. `_display_plan_result` (run.py)
threads `resume_source=ctx.obj.get("resume_source")`. DECISION (recorded): `--dry-run` KEEPS the
stale-workflow gate (preview mirrors what a real resume would refuse) but SKIPS the side-effect
confirmation (a dry-run never runs K, so nothing can fire — requiring `--force` there would be a lie).

**Tests:**
- `test_engine_and_planner_resume_entry_state_match` (`test_plan_drift.py`, extends the Phase-0
  parity test): real engine `run(resume_source=)` vs real `_build_plan_with_shared(resume_from=)` on
  the SAME source trace — pins the located entry (`resume_entry_node`=="middle" == `plan.entries[0]`
  == "middle"; tail continues to "last") and the seeded upstream (`restored_nodes` == planner-seeded
  == ["first"]; full-dict value equality). Mutation-verified: mislocating the planner resume entry
  (`entry_node = compiled.start_node`) fails EXACTLY this parity test + the 2 CLI dry-run entry tests,
  nothing else. Reverted clean.
- 3 CLI dry-run tests (`test_resume_cli.py`): plans the tail only (K-onward entries + resume header,
  no side-effect needed since dry-run skips the confirm), JSON `resume` block shape, stale-workflow
  still refuses without `--force`.

Manual e2e smoke (real `pflow`): `resume <wf> mode=ok --dry-run [--force]` → header "Resuming from
'step2': 1 upstream step restored from <id> (plan + cost cover this step onward)", plan lists
step2/step3 only (not step1); JSON `resume` = {entry_node, restored_nodes:[step1], execution_id};
no `--force` needed for the dry-run side-effect.

Verification: `make test` **8466 passed** (8462 + 4). `make check` green. Phase-3 CLI tests +
Phase-0/1/2 suites unaffected.

**Next: Phase 5 (incomplete-trace arm, Decision 7) — loader arm 3-incomplete + CLI step 4.**

## 2026-07-04 — Phase 5 COMPLETE: incomplete-trace resume (Decision 7)

Built:

**Loader arm (`_resolve_incomplete_entry`, `workflow_trace.py`)** replaces the Phase-1 stub. Raw-line
pass (`_iter_raw_trace_lines`): a TOP-LEVEL `node.start` (`parent_id is None`) whose `id` has no
matching `kind:"event"` line = killed-MID-node K (a leaf's terminal event REUSES the `node.start`'s
reserved seq via `begin_node`, so id-matching is exact; top-level scoping avoids the dangling CHILD
start a sub-workflow kill leaves). No dangling + ≥1 event → `entry=None` + `last_completed` = last
top-level event (CLI resolves the successor). No events (meta-only) → `ResumeNothingToResumeError`.
Liveness already runs FIRST in `load_resume_source`, so a flock-held incomplete trace refuses as
`ResumeStillRunningError` before this arm.

**CLI between-nodes resolution (`_resolve_between_nodes_entry` + `_single_default_successor`,
resume.py, §E step 4)** — runs when `source.entry_node_id is None`, after the hash gate, before the
side-effect gate. Refuses a dynamic router (last-completed is a `code` node — only code routes at
runtime and its taken route was never traced; DECISION: since `has_dynamic` is parse-only and NOT in
the IR, "is a `code` node" is the safe over-approximation — a non-code node routes purely
declaratively, so its single `default` edge is unambiguous), refuses 0/>1 default successors
(terminal / ambiguous) and a removed last-completed node; else `dataclasses.replace(entry_node_id=<the
one default successor>)`. Default successor read from IR edges (`action=="default"`, both
`from`/`to` + `source`/`target` spellings) — the compiled-graph fallback wasn't needed (IR edges
expose the distinction cleanly for file-based resumable runs).

**Tests:**
- Loader (`test_resume_source.py`, replaced the stub with a production-faithful incomplete-fixture
  helper — meta + events + dangling `node.start`, NO `run.complete` so the reader SYNTHESIZES
  `incomplete` exactly like a real SIGKILL): killed-mid-node enters at the dangling start;
  killed-between-nodes returns `entry=None`+`last_completed`; meta-only → nothing to resume;
  locked-incomplete → still-running (liveness first). Mutation-verified: inverting the dangling
  predicate (`sid in completed_ids`) fails ONLY the killed-mid-node test. Reverted clean.
- CLI (`test_resume_cli.py`): 4 unit tests for `_resolve_between_nodes_entry` (single default
  successor; code-router refused "dynamically"; terminal-node refused "ambiguous"; missing
  last-completed refused "no longer exists"), + 2 e2e (crafted incomplete trace with the real
  workflow_path, `--force` to bypass the stale hash): killed-between-nodes resumes at step1's
  successor step2 (step1 restored); killed-mid-node (dangling step2 start) resumes AT step2.

Verification: `make test` **8475 passed** (8466 + 9 net). `make check` green.

**Next: Phase 6 (docs + close-out) — guide topic, CLI reference, CHANGELOG, spec verification matrix.**

## 2026-07-04 — Phase 6 COMPLETE: docs + close-out

Built (§G):
- **Guide topic** `src/pflow/guide/features/resume.md` (`pflow guide resume`): at-least-once K + the
  confirm/`--force` policy; loop-K restarts at iteration 1; downstream gates re-prompt
  (`--auto-approve` works); top-level granularity (sub-workflow re-runs the whole host; memo softens);
  interrupted-run resumability; inline/piped not resumable; resume-by-exec-id is the cwd-safe form; the
  `${node.prompt}`/`${node.system}` strip caveat; the `analyze-cache` under-report caveat — WORDED
  CORRECTLY per the Phase-2 finding (restored LLM events carry no `llm_prompt` EVIDENCE, not "no
  `llm_call`" — they DO carry `llm_call`, cost-excluded). Registered: `RESERVED_WORKFLOW_NAMES` +
  `entry.md` menu (topic auto-discovered by `list_topics`).
- **Docs CLI reference** `docs/reference/cli/index.mdx`: a "Resume a failed run" section (mintlify
  voice — mechanism over evaluation, no banned words).
- **CHANGELOG**: an `## Unreleased` note (the release skill promotes it at release time).
- **Directory docs**: `cli/commands/CLAUDE.md` (resume.py row + test mapping), `execution/CLAUDE.md`
  (resume dry-run parity bullet — Phase 4), plus the Phase-3/4/5 accuracy edits logged above.
- **#255 close-out**: its pre-engine-failure cases are "no trace → clear refusal" — pinned by
  `test_failed_run_with_no_trace_is_a_clear_missing_error` (a `--no-trace` failed run → `pflow resume`
  → ResumeSourceMissingError, NOT a silent re-run) + the loader's `test_no_trace_for_workflow_raises_missing`.

**Spec Verification matrix (task-164.md → coverage):**
1. Failed idempotent (llm) K: upstream restored/not re-run, K+tail run, cost only re-run → Phase 2
   `test_resume_reenters_at_failed_node_and_skips_upstream` + cost/`nodes_executed` tests; Phase 3
   `test_llm_failed_node_resumes_without_confirmation`. ✅
2. Failed side-effecting K does not double-fire unacknowledged → Phase 3 side-effect confirm/refuse
   matrix (the at-least-once guard: TTY confirm / non-TTY refuse / `--force`). ✅
3. Conditional-branch resume onto the correct branch → Phase 2 branch/coalesce test. ✅
4. `restored_nodes` upstream = not_executed, K-onward executed → Phase 2 relabel test. ✅
5. No prior failed trace → clear error → loader `test_no_trace_for_workflow_raises_missing` + Phase 6
   #255 test. ✅
6. Incomplete (Ctrl+C/SIGKILL): killed-mid-node → that node; killed-between → unambiguous successor;
   ambiguous/meta-only/flock-live → clear error → Phase 5 loader + CLI tests. ✅
7. Self-contained attempt trace (Decision 6): restored zero-cost/excluded; `--only`-after-resume
   poisoning regression; resume-of-a-resume → Phase 2 tests. ✅
8. Gate-stopped/denied/undecided-escalation refusals (Decision 8) → Phase 1 loader tests. ✅
9. Multi-failure enters earliest in EVENT order → Phase 1 loader test. ✅
10. New trace + `resumed_from`, source never appended → Phase 2 tests. ✅
11. Still-running run rejected → Phase 1 + Phase 5 locked tests. ✅
12. `content_hash` mismatch → refuse + `--force` → Phase 3 stale-hash tests (both messages). ✅
13. Fidelity guard (binary placeholder) → Phase 1 loader test. ✅
14. Phase-0 extraction landed first, parity suites green unmodified, parity mutation-verified (both
    `--only` AND resume) → Phase 0 (committed) + Phase 4 resume parity. ✅

**Deliberately not run:** Task-159 `baseline/verify.sh` is a cache-analysis harness specific to Task
159, not a 164 gate; `analyze-cache` unit tests pass in the suite and the resumed-trace caveat is
documented — running the 159 harness adds no 164 coverage.

**Verification:** `make test` **8476 passed, 0 failed** (Phase-6 baseline 8434 + 42 net new resume
tests across Phases 3-6). `make check` green (ruff git-agnostic + format + pre-commit + mypy 244
files + deptry). `test_docs` (94) + `test_guide` green with the new topic.

## 2026-07-04 — ALL SCOPED PHASES (3-6) COMPLETE — awaiting human review

Phases 3, 4, 5, 6 implemented in one PR on top of the committed Phases 0/1/2. Nothing committed this
session (standing rule). `make test` 8476 / `make check` green throughout.

**What shipped this session:**
- Phase 3 — `pflow resume` CLI + side-effect policy (`is_side_effecting` promotion, `resume.py`,
  registration, failed-run hint, 28 tests).
- Phase 4 — dry-run parity: planner resume threading + `ResumePlanInfo`/`Plan.resume` + formatter +
  `pflow resume --dry-run` + the engine↔planner resume parity test (4 tests).
- Phase 5 — incomplete-trace resume (Decision 7): loader `_resolve_incomplete_entry` + CLI between-nodes
  successor resolution (9 net tests).
- Phase 6 — guide/docs/CHANGELOG + #255 close-out + spec verification matrix (1 test + docs).

**Reviewer sign-off wanted on (deviations from the plan, each with rationale above):**
1. `ResumeSource.workflow_path` field added (plan §B listed fields didn't include it) — the CLI needs
   the source workflow to re-resolve a by-exec-id resume; carrying it (self-contained/readers-dumb)
   beats re-opening the file the loader just parsed. One field, one construction site, one test updated.
2. Phase-3 `resume` omits `--dry-run` at the Phase-3 milestone; Phase 4 adds it WITH its plan threading
   (shipping a dry-run flag that plans the whole workflow would be a silent lie). End state has it.
3. `--dry-run` resume keeps the stale-workflow gate (preview↔real parity) but skips the side-effect
   confirm (nothing executes).
4. Between-nodes dynamic-router detection uses "last-completed is a `code` node" (has_dynamic is
   parse-only, not in the IR; only code nodes route at runtime) — the safe over-approximation.
5. Guide/docs correct the plan §G "restored LLM nodes carry no llm_call" wording to "no llm_prompt
   evidence" (the Phase-2 finding).

**Manual verification for the reviewer (unchanged from prior phases):** the real-browser UI check
(`make ui-build` + `pflow ui` over a resumed run) remains plan-designated MANUAL. All CLI/loader/engine/
planner behavior is covered by the automated suite + the manual `pflow` smokes logged in Phases 3-5.

## 2026-07-04 — Post-implementation loose-end sweep ("fully happy?" audit)

Audited the whole diff for gaps rather than trusting the summary. Findings + resolutions:

- **§E step 6 (required input absent on resume) — VERIFIED adequate, no code change.** Drove a
  resume of a workflow with a required input against a pre-175-style trace (`inputs=None`), no
  override → clean actionable `Validation Error: Workflow requires input 'mode'… At: inputs.mode`
  (exit 1, no crash). The agent passes `key=value`, which resume accepts. The plan's conditional
  "wrap if it doesn't mention resume" isn't needed — the standard message is already actionable.
- **Stray-flag guard in `_split_target_and_params` — was reachable but UNTESTED.** `--frobnicate`
  hits Click's parser (my test only proved exit 2 there); my guard fires only for a dash token
  forwarded past `--` (`resume -- --foo`), where it gives the nicer "inputs are key=value" message
  and rejects a dash-token target as a usage error (vs. a confusing "workflow not found"). Added
  `test_dash_token_target_after_separator_is_rejected` to exercise MY branch directly. Kept the
  guard (earns its keep on the `resume -- --foo` single-dash-target case).
- **Resume AT a sub-workflow host K — was UNTESTED (a real v1 product-stance scenario).** Verified
  end-to-end then locked it: `test_resume_at_a_sub_workflow_host_reruns_the_whole_host` — a failure
  INSIDE a sub-workflow makes K the top-level HOST; resume restores upstream (`pre`), re-runs the
  whole host (inner step now succeeds with the fixed input), tail continues. Confirms the
  "top-level granularity" stance holds and `is_side_effecting("workflow")=True` gates a host K
  correctly. Sound — no bug.
- **Considered and left as accepted scope (not gaps):** `--report` on resume (hardcoded off — not in
  spec); library-metadata "last used" not updated on by-exec-id resume (resolves as file source —
  cosmetic); the failed-run hint firing on a zero-event validation-failed resume attempt (points at
  an attempt that then gives the accurate Phase-1 defensive refusal — consistent with the wedge-fix
  design, message stays accurate). None affect correctness.

Net: 8476 → **8478 passed** (+2 loose-end tests). `make check` green. Nothing else outstanding.

## 2026-07-04 — HIGH-VALUE FINDING + FIX: resume entry selection contradicted locked Decision 9

Hunting for "passing the wrong thing" (owner-requested) surfaced a REAL implementation-vs-spec bug,
masked by two fictional synthetic fixtures.

**The bug.** In a `K --on-error--> F` chain where BOTH fail, the loader resumed at **F** (the
fallback), not **K** (the primary). Decision 9 (locked) says resume at K ("F never runs if K now
succeeds"). Root cause: entry was `min(_unrecovered_failed_node_ids(...), event-index)`; real
on-error routing tags the recovered primary K with an `on_error_recovery` warning, so
`_unrecovered_failed_node_ids` FILTERS K OUT → only F remains → entry=F. Verified end-to-end against
a real run (not a fixture): entry was `alpha`(F); resuming there re-ran the broken fallback and
failed again — useless for the common "I fixed the primary's cause" resume.

**Why the tests didn't catch it (the "passing wrong thing" part).** BOTH Phase-1 synthetic tests
used shapes production never writes:
- `test_multi_failure_enters_earliest_in_event_order` built two failed nodes with NO
  `on_error_recovery` warning — so both were "unrecovered", min gave zeta, green — but that shape
  can't occur for the K→on-error→F scenario its own docstring described (K IS recovered in reality).
- `test_recovered_failure_is_not_an_entry` had a recovered node then a failure with NO success
  between them — indistinguishable from the both-fail chain, yet asserted the (wrong-per-Decision-9)
  F answer.
Also: a linear/branching walk stops at its FIRST unrecovered failure, so
`_unrecovered_failed_node_ids` returns ≤1 in production — the `min(..., event-index)` tiebreak the
test exercised was effectively DEAD CODE.

**Industry check (owner asked "isn't this solved?").** Two families: Temporal = event-sourced
deterministic REPLAY to the frontier (never picks an entry node); Airflow/Dagster/n8n/GH Actions =
re-run the failed unit and let graph edges re-route. Shared principle: re-enter at the failure and
let the graph decide the path — don't pre-commit the downstream. Decision 9 is the correct member of
the second family; "resume at F" was the anomaly.

**The fix (owner chose spec intent).** New entry rule = **the earliest failed step with no
successful/cached step after it in event order** — the root of the terminal failure region
(Temporal's frontier, one pass, IR-free). `_unrecovered_failed_node_ids` is kept ONLY for the
gate-stopped emptiness check; entry selection is decoupled from it. Cases:
- K→F both fail → K (fixed K follows its success edge, F bypassed). Verified e2e:
  `completed == ["primary", "done"]`, fallback never ran.
- K→recovery-SUCCEEDS→L fails → L (a success sits after K, so K isn't re-run — more precise than
  Airflow's "re-run all reds").
- single failure / recovered-success cases: unchanged.

**Tests.** Rewrote the 2 fictional synthetic tests to REAL production shapes (recovered node carries
the `on_error_recovery` warning; the recovery-succeeded case has the intervening success). Added TWO
real e2e (`test_resume_engine.py`, real traces): the on-error double-failure resumes at the primary +
bypasses the fallback on fix; and — a separate verified win — a real non-interactive gate-stop
(`final_status=failed`, empty `failed_node_ids`) refuses via `ResumeGateStoppedError` naming the
gate (the synthetic gate-stopped test's shape now confirmed to match production).
Mutation-verified: reverting to the old `min(unrecovered)` fails EXACTLY the both-fail synthetic +
e2e tests (`- primary + fallback`), reverted clean.

**Documented** in ADR-0010 (amended 2026-07-04): the frontier entry rule + the known sharp edge —
resume is at-least-once over the WHOLE K-onward tail, so a both-fail resume at the primary can re-fire
the fallback F's side effects a second time if the primary still fails; the confirm/`--force` policy
gates K's type but does not separately warn about a downstream on-error fallback re-firing. Flagged
for Task 171+ (durable/exactly-once/saga) to revisit. Decision 9's ledger wording is unchanged — its
intent is now honored; the ADR carries the precise mechanism.

Net: **8480 passed** (+2 real e2e; 2 synthetic tests rewritten in place). `make check` green.

## 2026-07-04 — Independent review of the frontier entry fix (fresh session) — APPROVED + 2 hardening fixes

Owner-requested review of the unstaged frontier-rule change under the simplicity lens ("final code
the top 10% would ship"). Verdict: **the decision stands** — bug re-confirmed against the producers
(BOTH recovery channels stamp at routing time: `on_error_recovery` at engine step 17.5, and
`api_warning`'s `recovered` flag = handler-exists, instrumentation.py:858 — so a both-fail chain
always tags the primary "recovered"), the frontier rule verified sound over the closed per-node
status vocabulary (`success|cached|failed`; `cached` inclusion is load-bearing for attempt traces),
and the rewritten tests + 2 e2e now encode production shapes. The tempting further "simplification"
(frontier-only, drop the unrecovered-set check) was evaluated and REJECTED with a constructed
counterexample: **K fails → its on-error handler is GATED and gate-stopped** — K is then a failed
event after the frontier with nothing successful after it; only the warnings-based check routes it
to the gate refusal. The two-notion structure is earned, not vestigial.

Two hardening fixes applied (the review's only code findings):
1. **Totality**: guard set (unrecovered) and selection set (failed-after-frontier) were linked only
   by an unstated invariant ("an unrecovered failure stops the walk ⟹ it's the last event") — a
   crafted trace with a failed event followed by a success crashed `min()` with a raw `ValueError`
   (reproduced), violating the Phase-1 typed-refusal posture. Fixed: candidates collected first;
   empty → `_raise_gate_stopped_or_generic` (identical behavior on every engine-producible trace).
2. **The load-bearing check now has its pin**: `test_gate_stop_at_the_on_error_handler_refuses_
   naming_the_gate` — WITHOUT it, replacing the unrecovered check with a candidates-empty fallback
   passes the ENTIRE suite while regressing gate-after-recovered-failure to "resume at K"
   (mutation-verified: bypassing the check fails ONLY this test; removing the totality guard fails
   ONLY the new crafted-trace test). Comment updated to state WHY the check isn't redundant
   (was delete-bait: "only answers failure vs gate stop").

Also: task-164.md Decision 9 ledger wording annotated (mechanism refined → ADR-0010 pointer,
intent unchanged) so a future reader doesn't re-implement the stale "earliest failed in event
order" reading. Checked-and-sound, deliberately unchanged: recovered-K's failed `node_output`
being seeded in the K-recovered→L-failed case (pre-existing, logged in Phase 2, exposure SHRINKS
under the new rule); the loader staying IR-free (graph-aware entry rightly rejected).

Net: **8482 passed** (+2 loader tests), `make check` green (ruff/mypy/deptry), zero stray mutations.

## 2026-07-04 — Review-fixes batch COMPLETE (3 proven bugs + agent-UX findings; plan: review-fixes-plan.md)

Step-back audit ("passing the right thing", whole-picture) found THREE real bugs, each proven by a
temporary probe test asserting the CORRECT semantics against real runs (probe fails ⟺ bug exists),
then fixed with the probe graduated as the regression pin. Plus a `review-agent-ux` subagent pass
over every resume surface (guide / --help / exception family / hints / MCP-leak check).

**Bug A — seed fidelity (silent wrong data).** `seed_snapshot_into_shared` had no status filter, so
a RECOVERED failure in seed scope (primary-failed→on-error→fallback→…→K-failed) seeded the failed
primary's output into `shared[primary]`; a `${primary.x ?? fallback.x}` coalesce in the resumed tail
then resolved the failed data (proven: `used=` instead of `used=fallback-data`). Its docstring's
safety claim ("failed traces already rejected by the loader") was --only-era and false under resume.
Fix: `final_events_by_node` filtered to non-`failed` events at the single seam — the store is
reconstructed AS IT WAS (failed data lived in `__failures__`). Also fixes the identical latent
`--only`-degraded divergence, and dissolves the Phase-2 wart: failed-recovered upstream is neither
seeded, restored-listed, nor re-recorded (Decision 6 scope note added to spec + ADR). ZERO existing
tests encoded the old behavior (full suite green on first run after the fix).

**Bug B — incomplete tails ending in a FAILED event resumed down the wrong edge.** Neither
`_resolve_incomplete_entry` nor the CLI successor resolution consulted the last event's status:
(B1) kill after an unrecovered failure flushed → resumed at its DEFAULT successor, past the failure;
(B2) kill between a recovered failure and its handler's start → default successor = provably the
wrong branch (taken route was the ERROR edge; the fallback was skipped). Fix: extracted
`_terminal_failure_root(events)` (the frontier rule; needs no warnings — exactly what an
interrupted trace lacks) and gave the incomplete arm the same rule: failure-ending tail → re-enter
at the root; between-nodes successor applies ONLY to success-ending tails. Unifies the two arms
instead of adding a case. The failed arm's order is UNCHANGED (unrecovered-set check first — the
gate-stop discriminator — then root, with the totality fallback).

**Agent-UX fixes** (subagent findings; full report referenced in this log's session):
- The resume affordance now survives `-p` (stderr, failure only — a `-p` agent had NO path to the
  resume target) and the JSON failure document gains `execution_id` + `resume_command`
  (`_resumable_execution_id` in run.py → `output_error`/`format_error_json` kwarg; gated on
  trace-enabled + stream health because JSON mode finalizes the trace AFTER emission; MCP builds
  its payload via `format_execution_errors` directly — untouched by construction).
- Guide internals scrub (`meta.inputs`, `content_hash`, `llm_prompt`/`llm_system`,
  "engine-ephemeral (never traced)" → agent-vocabulary rewrites), the misquoted confirm prompt
  dropped, the interrupted-runs bullet extended with the failing-tail behavior, and
  `ResumeStillRunningError` trimmed of "held by a live writer" (flock vocabulary).
- Verified-clear by the UX pass (no change): exception family WHAT/WHY/HOW + literal recovery
  commands; `--help`; MCP never told to resume; discoverability; indicator/JSON honesty.

**Tests:** +6 (3 graduated bug pins in `test_resume_engine.py` — seed-fidelity coalesce,
incomplete-unrecovered-tail, incomplete-recovered-tail-error-edge; 3 UX pins in
`test_resume_cli.py` — `-p` hint survival, JSON resume fields, no-trace omission). Probe file
deleted after graduation. Mutation-verified: seed filter reverted → exactly the seed-fidelity test
fails; incomplete-root check bypassed → exactly the two tail tests fail. Docs: ADR-0010 amended
(both fixes), Decision 6/7 spec annotations (intent unchanged), guide, task-171 note
(resume-loader module extraction trigger + `_attempt_consumed_work` reuse).

**Verification:** `make test` **8488 passed, 0 failed** (8482 + 6), `make check` green, zero stray
mutations. Reviewer sign-off items: (1) seed-fidelity change reaches `--only` degraded snapshots;
(2) Decision 6/7 letter refinements (both intent-preserving, annotated in the ledger);
(3) the JSON failure document's two new fields (additive).

## 2026-07-04 — "Fully happy?" loose-end sweep (post review-fixes batch)

One REAL loose end found and closed, introduced by the seed-fidelity fix itself:
`_seed_scope_events`'s docstring claimed it "mirrors seed_snapshot_into_shared" — FALSE after the
fix (the seed additionally excludes failed-final-status nodes; the escalation/fidelity guards still
scanned them). Consequence: over-refusal — a binary placeholder inside a failed-recovered node's
output (never seeded) raised `ResumeFidelityError` and blocked a legitimate resume. Same smell
class as Bug A (a "mirrors X" claim drifting from X). Fixed: guard scope now drops nodes whose
final event in the slice is failed; docstring states it. Pin:
`test_binary_placeholder_in_unseeded_failed_node_is_ignored`; mutation-verified (filter removed →
exactly that test fails; reverted clean). Escalation semantics unaffected in practice (markers ride
SUCCESS events — Decision 8's seam is post-exec).

Doc staleness closed: `engine/CLAUDE.md` `_run_only_snapshot` step-2 seeding description (failed
exclusion added); guide gains one line documenting the JSON failure document's
`execution_id`/`resume_command` fields (they were shipped but documented nowhere).

Accepted, deliberately (for the reviewer):
- `_resumable_execution_id` reads the collector's private `_stream_failed` via defensive getattr —
  one consumer, documented in its docstring; a public accessor is not earned until a second reader.
- Guard scans remain PER-EVENT within the seedable node set (an earlier-iteration event of a
  final-success node is still scanned) — conservative direction, matches Decision 8's
  "anywhere in the seed scope" wording.
Carry-overs NOT from this batch (already recorded): manual browser UI check (plan-designated);
workflow-name-arm selection after a refused attempt (Phase-5 note); trace retention GH #542;
run-query glob consolidation (deferred, standalone); workflow_trace.py loader extraction
(task-171 note).

Verification: `make test` **8489 passed, 0 failed** (8488 + the alignment pin), `make check` green,
zero stray mutations.

## 2026-07-04 — Guide vocabulary scrub, round 2 (owner-caught: "K" leaked)

The owner caught what the agent-UX pass missed: `guide/features/resume.md` still used the spec's
internal shorthand **K** (×4) plus "seed"/"re-seeds", "memo cache", "host step", "re-resolve" —
internals vocabulary on the primary external-agent surface. Full rewrite pass against the bar
"external agent, zero pflow-internals knowledge": every occurrence now says "the failed step" /
"restores" / "cross-run cache" / "sub-workflow step" / plain language. Also swept the OTHER
agent-facing strings for the same class: exceptions messages had ONE leak
(`ResumeFidelityError`: "would seed corrupt state" → "would restore corrupt data"; no test pinned
the old text); resume.py's K/seed hits are all docstrings/comments (maintainer-facing — correct
home for spec shorthand); docs/reference/cli/index.mdx and the indicator/plan lines are clean.
Lesson recorded: the UX review checked messages for leaks but read the guide's PROSE with
spec-primed eyes — "K" was invisible to a reviewer who had just read the task spec. A vocabulary
lint of guide prose should grep for single-letter shorthand explicitly.

Verification: `make test` 8489 passed, `make check` green.

## 2026-07-04 — TASK CLOSED: review written, PR created

- Task review written: `.taskmaster/tasks/task_164/task-review.md` (the distilled forward
  reference — invariants, actual-vs-planned, gotchas, integration points, the tests that matter).
  Spec `## Status` → done, `## Completed` 2026-07-04.
- Review-fixes batch committed as `717fe445` (entry rule / seed fidelity / incomplete tails /
  agent UX); branch pushed.
- Retroactive problem-statement issue (project convention, #504 precedent): **GH #558**.
- **PR #559**: https://github.com/spinje/pflow/pull/559 — fixes #558 + #255. 43 files,
  +6632/−116, 6 commits. Verified on the exact pushed tree: `make test` 8489 passed / 0 failed,
  `make check` green.
- Still outstanding for the human reviewer (also listed in the PR + task-review): the four
  sign-off items (seed fidelity reaching `--only` degraded snapshots; Decision 6/7/9 letter
  refinements; JSON failure-doc fields; zero-event traces now `failed`) and the manual browser
  check (`make ui-build` + `pflow ui` over a resumed run).

## 2026-07-04 — Post-close adversarial CLI verification pass (real `pflow`, real traces)

Independent break-it verification: ~30 scenarios driven through the REAL `pflow` CLI on REAL
`.pflow.md` workflows (marker-file side-effect observation, not mocks), deliberately targeting the
silent-wrong-data / hang / crash classes the suite's synthetic fixtures can miss. Baseline confirmed
real (`make test` 8489). **Substrate held on every correctness path**; one LOW agent-UX gap found +
fixed; two red herrings chased and correctly dismissed.

**Verified end-to-end (held):** non-TTY side-effecting-K hard error (no hang, timeout-guarded);
upstream restored-not-rerun (marker stayed 1 line across resume, resume-of-resume, 3 attempts); seed
fidelity (recovered-failure primary NOT seeded into a downstream `??` coalesce → resolved
`fallback-data`); frontier entry rule (K→on-error→F both fail → resume at K, F never runs); wedge
(zero-event refused attempt via natural missing-input path does NOT poison the chain); fidelity guard
(raw-bytes upstream refuses, `--force` correctly can't bypass); incomplete tails (killed-mid-node /
between-nodes-successor / dynamic-router-ambiguity refusal / meta-only "nothing to resume"); loop-K
restart-at-iter-1 (observed via iteration log); branching divergence; nested sub-workflow host K
(top-level granularity); `--only`-after-resume poisoning regression; llm-K silent (no confirm/force);
large blob (>2KB) full round-trip restore; stale-hash + content_hash=None + K-removed refusals (all
typed, no compiler crash); liveness (still-running refusal via flock); superseded / nothing-to-resume
/ inline (`ir-hash:`) / missing-required-input; JSON stdout purity + `resumed_from`/`nodes_restored`/
`resume_entry_node`; `pflow report` renders restored node as `cached`/0-cost; `nodes_executed`
excludes restored; source trace byte-identical after resume (md5).

**Red herrings (correctly dismissed, NOT bugs):** (1) a surgical trace showed `resumed_from` pointing
at the wrong exec-id — my edit changed only the meta line's `execution_id`, not the `run.complete`
trailer's; the reconstructed dict merges trailer over meta. Real traces always agree (verified). (2)
`WARNING: Nested index must be integer, got str` — PRE-EXISTING (fires on normal full runs too, from
template `.stdout` access); not resume-related, out of 164 scope.

**LOW finding FIXED — resume hint on a non-interactive gate stop.** `_maybe_echo_resume_hint`
(`run.py`) skipped only `success` and `DENIED` (exit 3), but a non-interactive unapproved gate
finalizes **FAILED** (exit 1) with a `category:"gate"` diagnostic — so the failed-run output printed
`To resume from the failed step: pflow resume <id>`, yet `load_resume_source` refuses that trace
(`ResumeGateStoppedError`). The gate error already carries the `--auto-approve` remedy, so the resume
line was a dead-end affordance (self-correcting via a clean refusal, but wastes an agent round-trip —
against the agent-first bar). The authors reasoned about gate *denial* but missed gate *stop*. Fix:
one guard mirroring `_display_denied_result`'s gate detection —
`if any(d.context and d.context.get("category") == "gate" for d in (result.diagnostics or ())): return`
— skips the hint on any gate-caused failure. Docstring updated to state the gate-stop case.
Regression pin: `test_gate_stopped_run_omits_resume_hint` (`test_resume_cli.py`) — asserts the gate
run exits 1, IS a gate stop (`auto-approve` in stderr), and omits `pflow resume`. Mutation-verified:
removing the guard fails EXACTLY that test (1 failed, 42 passed in-file), reverted clean.

**Not reachable via CLI (flagged, rest on unit tests):** undecided-escalation refusal and `denied`-
trace refusal (both need a live agent escalation / interactive "no"); the gate-stopped arm — which I
DID exercise — shares the same raw-line machinery, partially corroborating them. Concurrency note (not
a bug, within the accepted at-least-once stance): two simultaneous `pflow resume` of the SAME failed
source aren't mutually excluded (the flock guards a live attempt, not the source), so both could run
K — consistent with at-least-once; worth a doc line if 171 ever tightens toward exactly-once.

**Verification:** `make test` **8490 passed, 0 failed** (8489 + the gate-stop hint pin); `make check`
green (ruff / ruff format / pre-commit / mypy 244 files / deptry); zero stray mutations. Files
changed: `src/pflow/cli/commands/run.py` (`_maybe_echo_resume_hint` guard + docstring),
`tests/test_cli/test_resume_cli.py` (`_GATE_WF` fixture + regression test). Uncommitted (standing
rule).

## 2026-07-04 — High-value test-fidelity pass ("passing the RIGHT thing", not coverage)

Stepped back with the whole picture and hunted for tests that catch bugs the suite is STRUCTURALLY
blind to (not coverage). First audited the existing crown-jewel test — the seed-fidelity coalesce
pin `test_recovered_failure_upstream_is_not_seeded` — and confirmed it is NOT shallow: it drives two
real `WorkflowRunner().run()` passes and asserts the OBSERVABLE downstream value
(`shared_after["use"]["stdout"] == "used=fallback-data"`), not internal seed state. Kept as-is.
Found and closed TWO genuine fidelity gaps, each probe-then-graduate + mutation-verified.

**Gap A — the agent-critical no-hang guarantee was structurally untested.** Decision 4 promises a
side-effecting resume in a non-interactive context "refuses, never a prompt or a hang." Every resume
test drives this through `CliRunner`, which is ALWAYS non-TTY with empty stdin — it exercises the
refusal branch but **cannot tell a correct refusal from a real hang** (there is no live stdin to
block on). The hang only manifests against a real process whose stdin is an OPEN, idle, non-TTY pipe
— exactly what an agent that spawns `pflow` with an unclosed stdin pipe produces.
`resume._confirm_or_refuse_side_effect` calls `click.confirm` only when `can_prompt`
(`stdin_tty and stderr_tty`) is true; drop that guard and `click.confirm` blocks on the idle pipe
forever. NEW e2e test `tests/test_cli/test_resume_no_hang_subprocess.py` (real `uv run pflow`
subprocess, stdin = `os.pipe()` read end with the write end held open, `timeout=45`): a correct
refusal exits in ~1s; a broken guard hangs → `TimeoutExpired` → `pytest.fail`.
**Mutation-verified:** replacing `if can_prompt(controller):` with `if True:` made resume HANG the
full 45s and the test caught it (`resume HUNG on a non-interactive side-effecting step`). This is the
catastrophic-and-silent failure mode the entire CliRunner suite cannot see. `e2e`-marked (excluded
from default `make test`, runs in `make test-e2e`); Unix-only; skips on the uv-sandbox-panic quirk.

**Gap B — the seed-fidelity filter is a SHARED seam with two consumers but only one pin.** The fix
(`workflow_trace.py`: `final = {… if ev.get("status") != "failed"}`) lives in
`seed_snapshot_into_shared`, reconstructing the store for BOTH resume AND `--only`. Only the resume
side had a test. `test_only_snapshot.py` covered the coalesce only for a SUCCEEDED primary
(`test_only_coalesce_silently_uses_snapshot_branch`), never a recovered-FAILURE primary — so a future
"this exclusion is resume-only" refactor would silently reopen the silent-wrong-data bug in `--only`
with every resume test still green (the review-impact-completeness class: shared pattern changed,
not all consumers guarded). NEW test `test_only_does_not_seed_a_recovered_failure_upstream`
(`test_only_snapshot.py`): a degraded full run (primary fails→on-error→fallback), then `--only report`
must resolve `got fallback-data`, not the failed primary's `got primary-junk`. Probe-then-graduate:
verified the correct `--only` behavior live first, then mutation-verified the filter removal yields
`got primary-junk` via the CLI. **Full-suite mutation-verified:** dropping the filter fails EXACTLY 2
tests — this new `--only` pin AND its resume sibling — nothing else (2 failed, 8489 passed), proving
the seam now has a pin on each consumer.

**Deliberately NOT added (judged low value / not "the right thing"):** the empty-`{}` re-record
fidelity test stays unit-level — no real node cleanly emits `{}` except a `code` node returning
`result: dict = {}`, and the mechanism is already mutation-pinned; an e2e wrapper would add wall-clock
without new bug-catching power. The concurrency double-resume race is within the accepted at-least-once
stance (not a bug). The undecided-escalation / `denied` refusal arms stay on their unit tests (no live
CLI path to produce them; the gate-stopped arm I exercised shares their machinery).

**Verification:** `make test` **8491 passed, 0 failed** (8490 + the `--only` seed-fidelity pin; the
no-hang test is `e2e`, verified separately — 1 passed in ~1s, and failed-as-designed under the guard
mutation); `make check` green (ruff / ruff format / pre-commit / mypy 244 files / deptry); zero stray
mutations. Files added: `tests/test_cli/test_resume_no_hang_subprocess.py`; files changed:
`tests/test_runtime/test_only_snapshot.py` (+1 test). Uncommitted (standing rule).

## 2026-07-04 — Deep-review batch (5-agent battery): escalation-fold fix + seed-scope consolidation

Owner-requested `/deep-review` over the full branch. Battery: review-impact-completeness,
review-silent-failures, review-feature-interactions, review-test-fidelity (owner-picked 4) +
review-simplicity (owner-added). Verdicts: **3 dimensions fully clean** (impact-completeness —
all 5 shared-pattern changes traced to every consumer; feature-interactions — all 7 combinations
pinned e2e; test-fidelity — fixtures production-faithful, the two previously-bitten shapes
verified), 1 confirmed Critical-adjacent Warning (silent-failures), 1 confirmed simplicity
Warning that turned out to be the same code region. Both fixed in this batch.

**Confirmed bug — escalation-gate resume false-refusal.** Every resume with a RESOLVED
escalation upstream refused with a message asserting the opposite of what happened. Mechanism +
landed fix (`_apply_gate_resolutions` load-time fold; Decision 8 intent preserved) are canonical
in the **ADR-0010 third amendment** — not restated here. The journey knowledge that lives only
in this log:
- Found by the silent-failures agent; its 3-file causal chain (record-freeze at engine 16 vs
  decision-write at 17.7, gate.py:175) was verified by a dedicated code-trace agent BEFORE being
  accepted — worth repeating for cross-layer claims.
- Masked by `test_decided_escalation_in_seed_scope_is_fine` — its hand-built decided shape was
  one production never writes to a live run's trace (pitfall #19, **third bite** this task).
- **First-derived fix was wrong-shaped and rejected under the owner lens** (simplicity of the
  FINAL code / writer honesty over reader compensation): a guard-side gate-line join would have
  re-joined on every chain hop and leaked stale markers into attempt traces. The load-time fold
  is one mechanism, N unchanged consumers — and Decision 6's re-record persists the decided
  marker for free (resume-of-a-resume stays join-free). Same re-derivation pattern as the wedge
  fix; the first instinct compensated at the reader again.
- Fold subtlety worth keeping: last resolution wins via UNCONDITIONAL overwrite — an
  only-if-undecided fold would stick resolution 1 to a looping node's iteration-2 marker.

**Simplicity Warning (same region) — guard/seeder scope consolidated** into
`_seedable_final_events` (see task-review.md invariants for the resulting rule). The guard had
scanned a SUPERSET of what seeding restores — a superseded loop iteration's undecided marker
could refuse a resume. Riders landed with it (recorded only here): dead
`ResumeSource.final_status` dropped (`_resolve_resume_entry` returns a pair now), and the
provably-dead `!= entry` filters at the three `restored = …` call sites collapsed to
`list(final)` (invariant stated on `seed_walk_entry`'s docstring).

**Tests: 5 new** (real-collector e2e + 3 synthetic fold pins + guard-scope pin — named in
task-review.md "Tests That Matter"). Mutation outcomes: fold disabled → exactly the 4 fold tests
fail; guard reverted to superset scan → exactly 2 fail (superseded-iteration + last-wins). Zero
stray mutations. `test_decided_escalation_in_seed_scope_is_fine` re-docstringed rather than
deleted: its decided shape is now the POST-FOLD / attempt-trace re-record shape —
production-real again.

⚠️ Process incident (own goal, logged for honesty): a mutation-verification shell one-liner
included `git checkout src/pflow/runtime/workflow_trace.py`, wiping the batch's uncommitted edits
to that file mid-session. All edits were reapplied from context and re-verified (the 4 new fold
tests failing against the reverted file was itself the confirmation the pins work). Rule
reinforced: mutations are applied AND reverted via Edit only — no git commands in mutation
scripts, ever.

**Deep-review suggestions deliberately deferred (non-gating, recorded here):** real-emission
coverage for the dangling-`node.start` mid-node branch (mitigated by seq-reuse pins in
test_emit_time_trace); a resume-AT-a-batch-host-K e2e (generic `_execute_node` path, gated by
`is_side_effecting`); S2's redundant exit-code-only assertion in
`test_side_effect_force_bypass_runs` (covered by its stdout-checking sibling).

**Verification vs baseline:** `make test` **8496 passed, 0 failed** (8491 + exactly the 5 new
tests); `make check` green; docs updated: ADR-0010 third amendment, task-164.md Decision 8
refinement annotation, task-review.md (seedable-set invariant bullet + escalation-fold invariant
+ tests list + metadata). Uncommitted (standing rule).

## 2026-07-04 — Deep-review batch loose-end sweep (owner asked "fully happy?")

Re-audited the batch; three loose ends found, all closed:
1. **Sub-workflow gate-line collision — verified structurally impossible, not just unlikely.**
   The fold's `final[node_id]` lookup could in theory cross-match a nested gate's node_id onto a
   same-named top-level node. Verified: child collectors are buffer collectors
   (`_stream_to_disk = stream_to_disk and is_run_scoped`, workflow_trace.py:1134) — nested gate
   resolution lines NEVER reach the file, so the fold only ever sees top-level lines. A nested
   escalation exposed through its host carries the DECIDED marker already (the host event records
   after the child resolved). Documented in runtime/CLAUDE.md.
2. **e2e gate not run this batch** — `test_resume_no_hang_subprocess.py` exercises the loader the
   batch changed; ran it: 1 passed.
3. **runtime/CLAUDE.md accuracy** (directory-doc convention): seed-fidelity bullet rewritten
   around `_seedable_final_events` as the single derivation + escalation-fold sentence added.

Accepted, deliberately (unchanged from the batch entry): fold gates on `phase=="resolution"` +
decision-dict presence rather than `gate_kind` (only escalation choice writes `decision` today;
docstring pins the mirror to `run_escalation_gate`); ResumeSource docstring doesn't restate the
fold (documented at the fold + loader); up to three raw-line passes per load (CLI-scale file, not
a hot path).

## 2026-07-04 — Owner verification: real-TTY escalation resume + the plan-designated browser check

Owner-driven, live (demo: `scratchpads/task-164-verify/escalation-resume-demo.pflow.md`):
- **Escalation fold, real TTY**: owner answered the escalation prompt with `hold` (deliberately
  NOT the recommendation), run failed at `deploy`, `pflow resume` (a) did NOT refuse (the
  pre-fix false-refusal), (b) fired the Decision-4 side-effect confirm naming step+type,
  (c) printed the ⤷ indicator, and (d) `announce` output carried `decision.chosen == "hold"` —
  the owner's answer restored from the gate-resolution fold, with `agent` never re-executed.
  Failure surface's `pflow resume <execution-id>` hint confirmed live.
- **Browser check (closes the Phase-2 reviewer to-do)**: `make ui-build` + `pflow ui`,
  screenshots over both attempts. Resumed attempt: pill "Run success · 2 nodes" with 3 steps
  listed (nodes_executed exclusion), restored `agent` at 0ms with cached/✓ styling, tail with
  real timings; source run: "Run failed · 2 nodes · 1 failed", untouched. `/api/runs` lists
  both attempts; `resumed_from` tolerated; no tailer/console errors. Attempts render as
  separate runs (chain-join = 171/176, expected).

All pending manual items are now closed. Demo kept in `scratchpads/task-164-verify/` (also
useful for Task 171 verification); `/tmp/pflow-164-demo.flag` is owner-local cleanup.

## 2026-07-04 — Scoping decision: UI attempt-chain rendering folded into Task 171

During the browser check the owner asked where richer resume UI lives (resumed badge, chain
grouping). Finding: it was pointed at "171/176" but owned by NEITHER spec — an unowned gap
(and `/api/runs` doesn't surface `resumed_from` yet). Owner decision: **fold into 171**
(it already touches run-status rendering for `paused` and builds the chain walk for
`resume list` — one pass renders failed- and paused-chains). Recorded: task-171.md gains a
"UI attempt-chain rendering" requirements section; the 164 plan's out-of-scope line and
task-review.md's 171 handoff bullet now point at it.

Follow-up (same sitting): a **Resume BUTTON** for failed runs is an ACTION, not rendering —
owner-decided into **176** (it already builds UI→`pflow resume` spawn plumbing for approvals;
one spawn helper serves both). task-176.md gains a "Resume button on failed/interrupted runs"
section carrying the non-obvious constraint discovered here: the UI server's spawn is non-TTY,
so a side-effecting K hard-errors by design (Decision 4) — the browser dialog IS the
confirmation and the spawn must carry `--force` after it. Layering: 164 = data, 171 = see
chains, 176 = act on them.

## 2026-07-04 — Handoff decision: NO braindump to 171/176; pointers + two tacit one-liners instead

Owner asked whether 171/176 need a /braindump handoff. Decision: no — this task distilled
contemporaneously into durable homes (spec annotations, ADR-0010, task-review, directory
CLAUDE.mds, forward sections written directly into 171/176), so a braindump would be ~90%
duplication of maintained artifacts (and braindumps go stale; 176's own header carries that
lesson). A tacit-knowledge inventory found exactly three unwritten items, each placed at its
point of use instead:
- 171 + 176 Dependencies now say "read 164's task-review.md FIRST" (the review declared itself
  the read-first handoff, but neither successor spec pointed at it — discoverability gap).
- 171: seed scope excludes the entry node, so a paused gate's own undecided marker never trips
  the seed guards — the `paused` arm composes with `_apply_gate_resolutions` unchanged.
- 176: `--auto-approve` is approval-kind-only (gate_prompt.py) — an escalation-paused run can
  never be resumed by flag alone; load-bearing for the merged resume/approve control call.
