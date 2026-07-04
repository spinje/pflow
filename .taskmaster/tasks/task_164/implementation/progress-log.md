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
