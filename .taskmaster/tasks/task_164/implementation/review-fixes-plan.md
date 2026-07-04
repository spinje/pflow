# Task 164 — Post-implementation review fixes plan (2026-07-04)

> **STATUS: EXECUTED 2026-07-04** — all phases landed; see the progress-log entry "Review-fixes batch COMPLETE".

_Basis: the 2026-07-04 review session. Three REAL bugs proven by failing probes in
`tests/test_runtime/test_probe_resume_semantics.py` (temporary file — each probe asserts the
CORRECT semantics, so its failure IS the bug; probes graduate into the suite as each fix lands,
then the probe file is deleted). Plus four agent-UX findings from the `review-agent-ux` pass.
Written to be implementable in isolation; where a choice existed, it is made here, with the
reason. Baseline at plan time: `make test` 8482 passed, `make check` green._

## The issues

- **Bug A (silent wrong data, severity: high).** `seed_snapshot_into_shared`
  (workflow_trace.py:859) has no status filter, so a recovered failure upstream of entry K
  (K'-failed→on-error→F-succeeded→K-failed) seeds K''s FAILED `node_output` into `shared[K']`.
  In the original run that data lived in `__failures__` (absent from the store), so
  `${K'.x ?? F.x}` fell through to F. Proven: resumed run computed `used=` where original
  semantics give `used=fallback-data`. The docstring's safety claim ("a failed node forces the
  trace to failed → already rejected by the loader") is TRUE for `--only`, FALSE for resume —
  and `--only` against a DEGRADED snapshot has the identical latent divergence today.
- **Bug B (wrong-branch continuation, severity: medium).** Neither `_resolve_incomplete_entry`
  (loader) nor `_resolve_between_nodes_entry` (CLI) consults the last completed event's STATUS.
  - B1: incomplete tail ending in an UNRECOVERED failure (killed after the failure flushed,
    before `run.complete`) → resumes at the failure's default successor — past an unhandled
    failure as if it succeeded. Proven: entry resolved to `after`, not `boom`.
  - B2: killed between a recovered failure and its on-error handler's start → the taken route
    was the ERROR edge, but resolution picks the single DEFAULT successor — provably the wrong
    branch, skipping the fallback. Proven: entry resolved to `use`, not `fallback`/refusal.
- **UX-1 (Warning).** The resume affordance on failure is a stderr prose line only
  (`run.py::_maybe_echo_resume_hint` via `_echo_trace`, which early-returns under `-p`); the
  JSON failure document carries no `execution_id`/resume field. A `-p` or JSON agent cannot
  obtain the resume target programmatically (fallback `pflow resume <workflow>` exists, so
  Warning not Critical).
- **UX-2 (internals leak).** `src/pflow/guide/features/resume.md` names trace internals:
  `meta.inputs` (line ~28), `content_hash` (~43), `llm_prompt`/`llm_system` (~53/57),
  "engine-ephemeral (never traced)" (~44). Zero actionable value; violates the no-internals rule.
- **UX-3 (accuracy).** Guide (~36) quotes the confirm prompt as `Run this step again? [y/N]`;
  the real prompt (resume.py:245) reads "Resuming re-runs step 'X' (a shell step) and its side
  effects may fire again. Continue? [y/N]".
- **UX-4 (nit).** `ResumeStillRunningError` message says "its trace is held by a live writer"
  (flock mechanics). "This run is still in progress" suffices.
- **Done already:** workflow_trace.py accretion noted in task-171.md (extract
  `runtime/resume_source.py` when the `paused` arm lands).

## Owner sign-off items (flag at review; the plan proceeds on all three)

1. **Fix A changes `--only` degraded-snapshot seeding too** (recovered-failed upstream no longer
   seeded) — deliberate: same latent bug, same fix, store reconstructed as it actually was.
   Refines Decision 6's letter: a failed-recovered upstream node is neither seeded nor
   re-recorded (the attempt trace stops flipping it to cached-success — the Phase-2 logged wart
   dissolves). Rationale preserved: the attempt trace is self-contained w.r.t. the store state
   resume actually reconstructs.
2. **Fix B refines Decision 7's letter**: an incomplete tail ending in a FAILURE re-enters at
   the failure region's root (same frontier rule as the failed arm); the between-nodes
   successor resolution now applies ONLY to tails ending in success/cached. Intent preserved
   ("never a wrong-branch guess"); strictly fewer wrong continuations, strictly more resumable
   cases than refusing.
3. **UX-1 is additive surface change**: one stderr line on FAILURE under `-p`, and
   `execution_id` + `resume_command` fields in the JSON failure document (gated on a trace
   having been written).

---

## Phase F1 — Bug A: seed fidelity (store reconstructed as it was)

1. `seed_snapshot_into_shared` (workflow_trace.py:859): build `final` EXCLUDING events whose
   `status == "failed"` — filter once at construction so the RETURNED map changes too; all four
   consumers inherit consistently (`_run_only_snapshot` restored_nodes, `_prepare_resume`
   restored_nodes + Decision-6 re-record loop, planner resume restored list). Do NOT filter at
   call sites (policy stays at the single seam).
2. Rewrite its docstring: delete the false "already rejected by the loader" claim; state the
   invariant — *seeding reconstructs the shared store as it existed in the source run: a failed
   node's data lived in `__failures__`, never in the store, so it is not seeded; a coalesce
   that fell through to a fallback falls through again on resume.* Note the `--only` degraded
   case explicitly.
3. Graduate probe A → `test_resume_engine.py::test_recovered_failure_upstream_is_not_seeded`
   (assert `used=fallback-data` AND `"primary" not in resumed restored_nodes` AND the attempt
   trace carries NO re-recorded `primary` event — pins the re-record dissolution).
4. Sweep for tests encoding the old behavior: `make test`; expected suspects are `--only`
   degraded-seeding tests and any resume test asserting a recovered node in `restored_nodes`.
   Update each WITH a comment naming this fix (pitfall #18 justification: deliberate behavior
   change, not assertion-weakening).
5. Mutation-verify: revert the filter → the graduated probe fails; revert clean.
6. Docs: ADR-0010 amendment (seed-fidelity rule + Decision-6 refinement); task-164.md Decision 6
   annotation (same style as the Decision 9 annotation); runtime/CLAUDE.md seed bullet.

## Phase F2 — Bug B: incomplete tails ending in a failure use the frontier rule

1. Extract module-level `_terminal_failure_root(events) -> str | None` in workflow_trace.py
   from `_resolve_resume_entry`'s frontier block (last_index + frontier + candidates + min;
   returns None when no failed event sits after the frontier). `_resolve_resume_entry` keeps
   its EXACT current order: unrecovered-set check FIRST (load-bearing for
   gate-stopped-after-recovered-failure — pinned by
   `test_gate_stop_at_the_on_error_handler_refuses_naming_the_gate`), then
   `root = _terminal_failure_root(events)`, `None` → `_raise_gate_stopped_or_generic` (the
   totality guard, pinned by the crafted-trace test).
2. `_resolve_incomplete_entry`: after the dangling-start check (unchanged),
   `root = _terminal_failure_root(events)`; if root → `(root, None, "incomplete")`; else the
   existing between-nodes / meta-only logic. NOTE: incomplete traces have NO warnings (trailer
   absent) — the frontier rule needs none; do not attempt a recovered/unrecovered distinction
   here. B2 semantics fall out correctly: re-entering at the recovered primary re-runs it
   (at-least-once, side-effect-gated by node type as usual) and its error edge re-routes to the
   fallback.
3. Graduate probes B1/B2 with updated expectations: loader now returns
   `entry_node_id == "boom"` / `== "primary"` directly (between-nodes CLI resolution never
   runs). Keep the truncation helper with them (`test_resume_engine.py`, since they drive real
   runs). Existing trailing-success between-nodes tests (loader + CLI) must pass UNCHANGED.
4. Mutation-verify: bypass the root check in `_resolve_incomplete_entry` → exactly the two
   graduated tests fail; revert clean.
5. Docs: ADR-0010 + task-164.md Decision 7 annotation; guide's interrupted-run paragraph — only
   if its wording contradicts the new behavior (check, don't assume).
6. Delete `tests/test_runtime/test_probe_resume_semantics.py` (all three probes graduated).

## Phase F3 — Agent-UX fixes

1. **UX-1 failure-path affordance**:
   a. `_maybe_echo_resume_hint` (run.py): emit the hint line to STDERR even under `-p` when the
      run FAILED and a trace was written (stdout stays data-only; failure diagnostics belong on
      stderr — the existing doctrine). Success/`--no-trace`/MCP suppression unchanged.
   b. JSON failure document: add `"execution_id"` and `"resume_command": "pflow resume <id>"`
      to the failure payload, gated on trace existence. Impl note: locate the builder on the
      `--output-format json` failure path (error formatter / `workflow_output` failure branch —
      verify the exact seam at impl time; the hint site already holds `trace.execution_id`).
      MCP output must NOT gain these fields (no trace → gate never fires; verify with the
      existing MCP formatter tests).
   c. Tests: `-p` failed run → hint on stderr, stdout clean; JSON failed run → both fields
      present; success/`--no-trace` → absent in both modes.
2. **UX-2 guide leak scrub** (`src/pflow/guide/features/resume.md`): apply the reviewed
   rewrites — "reused from the inputs the failed run used" (drop `meta.inputs`); drop the
   `content_hash` parenthetical; caveat sections lose `llm_prompt`/`llm_system` field names
   (keep the actionable advice verbatim); soften "engine-ephemeral (never traced)" to
   "loop position is not part of the saved run".
3. **UX-3**: quote the real confirm prompt or drop the backtick quote (prefer dropping — the
   exact wording then can't drift again).
4. **UX-4**: `ResumeStillRunningError` message → "This run is still in progress." (suggestion
   line unchanged); update its message-pinning test.
5. Re-run `test_docs` + guide tests.

## Phase F4 — close-out

1. Progress-log entry (bugs, fixes, mutation ledger, UX items) + this plan marked done.
2. Full gates vs baseline: `make test` (expect 8482 + graduated/new − deleted-probe deltas,
   0 failed), `make check`, `pytest -m trace_files`.
3. Confirm zero stray mutations (`grep -rn MUTATION src/ tests/` shows only the 5 pre-existing
   hits).

## Invariants to hold while editing (from the merged review)

- The unrecovered-set check in `_resolve_resume_entry` runs BEFORE frontier selection — never
  fold it into candidates-emptiness (gate-after-recovered-failure regresses silently; the pin
  test exists but keep the ordering comment intact).
- `_iter_workflow_traces` gains NO status filter; seed-status policy lives ONLY in
  `seed_snapshot_into_shared`.
- `runtime/` does not import `ui/`; the loader's raw-line reader and flock probe stay local.
- Restored events remain `cached=True` (+`restored`) — cost/UI consumers unchanged.
- Every behavior-encoding test updated in F1/F2 carries a one-line comment naming the fix.
