# Braindump: Task 172 Phase 3 (streaming) handoff — 2026-06-22

> Phases 1+2 are **done, reviewed (4 specialists), gap-closed, and verified** (full suite 8014 green,
> `make check` clean, manual e2e green). This file is ONLY the tacit Phase-3 knowledge not in
> `implementation-plan.md` (Pieces 4+5 mechanics), `progress-log.md` (what landed + the review round), the
> task spec, ADR-0008, or the D1 schema. Read those first; then this for the seams + hazards they don't name.

## The single most important thing: Phase 3 EVOLVES the Phase-2 writer, it doesn't start fresh

Phase 2 left you a **whole-file emit-direct writer** that is the exact seam Piece 4 streaming converts:

- `core/trace_io.py::emit_flat_events_to_lines(trace_data)` — builds `meta` + one `event` line per flat
  (already-stamped) event + `run.complete` + a `blobs` **trailer** (via `intern_blobs`). This is the
  counterpart to A–C's `flatten_trace_to_lines`.
- `runtime/workflow_trace.py::save_to_file` is now **dual-path**: run-scoped → `emit_flat_events_to_lines`;
  buffer/test collectors (`is_run_scoped=False`) → the old `flatten_trace_to_lines`.

Piece 4 says "finalize() replaces save_to_file's body" and "remove flatten_trace_to_lines." **The tacit
catch the plan doesn't spell out:** `flatten_trace_to_lines` is still used by the **buffer/test** path. In
*production* only the run-scoped root ever saves (sub-workflow buffers never write to disk) — so flatten's
only remaining callers after streaming lands are **tests that construct a bare `WorkflowTraceCollector` and
call `save_to_file()`** (several `@trace_files` tests do this). So Piece 4 "remove flatten" forces a choice:
(a) keep the dual-path and leave flatten for buffer collectors, or (b) remove flatten and migrate those tests.
Decide this consciously; don't half-remove it (a mid-state breaks every bare-collector save test).

## Streaming can't reuse `intern_blobs` — that's the real Piece-4 rewrite

`emit_flat_events_to_lines` interns blobs across the WHOLE tree at once (`intern_blobs` over meta+events+
run_complete → one trailer). **Per-event streaming cannot do that** — you flush each event as it's recorded,
before you've seen later events. So inline-first-occurrence (Piece 4 / D3) is a genuinely different interning
model: per event, intern its ≥`INTERN_MIN_BYTES` string leaves, and for each digest NOT already in a
`self._declared_blobs` set, write a `{"kind":"blob","md5":...,"value":...}` line FIRST, then the event line.
Refs are backward-only (that's what makes a crash-truncated tail self-consistent for Task 173's tailer).
Don't try to bend `intern_blobs` into this; build the per-event path (the plan's Piece 4 describes it) and
leave `intern_blobs`/`substitute_refs` for the trailer/legacy round-trip.

## Writer↔reader blob arms must land in ONE commit, or all trace loading breaks

`_partition_trace_lines` has a terminal `else: raise json.JSONDecodeError("unknown kind")`. The moment the
writer emits a singular `blob` line, the reader (still on the plural `blobs` arm) hits that `else` → **every
streamed trace fails to load**, and the 3 readers (`_iter_workflow_traces`, analyze-cache autoload,
`generate_report`) all degrade/skip. Add the `elif kind == "blob": blob_map[line["md5"]] = line["value"]` arm
and REMOVE the `elif kind == "blobs"` arm in the same change as the writer switch. (Piece 5.2 says this; the
tacit part is *how loud the failure is* if you stage them apart.)

## `_RESERVED_LINE_KEYS` does NOT yet strip `ancestor_path`/`port` — and that's fine until Piece 5.1

Phase 2 WRITES `ancestor_path`/`port` onto events but `reconstruct` does NOT strip them yet (Piece 5.1 is
yours). So today the reconstructed dict carries them (NOT A–C-byte-identical — intentional, per the gate).
When you add them to `_RESERVED_LINE_KEYS`:
- `tree()` calls the SAME `_rebuild_event_tree`, so it will strip them too → `tree() == reconstruct(disk)`
  **still holds** (both strip). My equivalence tests assert correlation/`ancestor_path` on `collector.events`
  (the raw flat store, never stripped), NOT on `tree()` — so **they should survive Piece 5.1 unchanged**.
  VERIFY this rather than assume; if a test asserts `ancestor_path` on `tree()` output it'll need adjusting.

## The two-pass reconstruct is ONE mechanism serving THREE Phase-3 needs — internalize that before coding

`mark_last_event_failed` (dead-end re-flush, Piece 5.4), crash-tail (Piece 5), and the *already-shipped*
api-warning/host-after-ascend ordering all rely on the SAME `_rebuild_event_tree` rewrite (sort-by-`seq` +
dedup-by-`id` last-wins + lenient transitive orphan-drop when incomplete). Concretely:
- A sub-workflow host's line flushes AFTER its children (host records at completion). The dead-end re-flush
  flushes a corrected child line AFTER the host. Both are handled by sort-by-seq + dedup-by-id — flush order
  is immaterial. I already pinned the collector-level invariant in
  `test_host_recorded_after_ascend_with_frame_keeps_children_linked` (api-warning timing): a host recorded
  after `ascend()` reusing its reserved frame keeps children linked and `reconstruct` survives. **That test is
  your canary** — if your two-pass rewrite breaks, it'll fail.
- `mark_last_event_failed` currently only MUTATES `self.events` in place. For streaming it must ALSO re-flush
  the corrected line (same `id`/`seq`, now `status="failed"`) to the open stream. It's the ONLY post-flush
  correction (api-warning flips at construction → covered by the normal flush). It needs access to the stream
  / a flush path — that coupling is new; design it deliberately.

## conftest gate + my driver tests — concrete obligations

- `tests/conftest.py::disable_trace_file_writes_by_default` patches `save_to_file` only. Extend it to no-op
  the new lazy stream-open entry point too, behind the same `trace_files` marker — or non-`trace_files` tests
  that run a workflow will start writing real streamed files. The braindump-handoff flagged this as
  "specified, untested — I/O timing reveals things." Believe it.
- `tests/test_runtime/test_emit_time_trace.py` (the Phase-2 contract, 8 tests) calls `collector.save_to_file()`
  in several places. When `finalize()`/streaming replaces it, **update those call sites** and add the Phase-3
  tests (incremental-flush one-line-per-event, blob-line-precedes-ref, D3 crash-tail, streaming dead-end
  re-flush, transitive orphan-drop). The crash-tail test **REPLACES** A–C's
  `test_load_trace_file_skips_truncated_tail_line` in `tests/test_core/test_trace_io.py` — DELETE that one
  (it pins the old whole-trace-skip behavior Phase 3 inverts; leaving it = two contradictory pins).

## Filename + meta-line timing (small but easy to get subtly wrong)

Piece 4: switch `format_trace_filename`'s timestamp from save-time `datetime.now()` to `self.start_time`
(`%f` granularity preserved — that's the #443 collision entropy; don't drop the microseconds). The streaming
writer opens lazily on first flush and writes `meta` first. `meta` needs `only_node`, which the engine stamps
at `run()` start — and (Phase-2 fix) ONLY on the **root** (`_pflow_depth == 0`). Root stamp happens before any
node records, so before first flush, `only_node` is correct. Zero-event runs still must get meta+run.complete
(finalize opens the stream even with no events).

## Verification order (the residual ~15% — write these tests FIRST, they're never-run logic)

1. Two-pass reconstruct (dedup last-wins + transitive orphan-drop) — the one piece reviewed but never run.
2. Streaming dead-end re-flush (`tree() == reconstruct(disk)` on a dead-end run — the only path where events
   flush BEFORE the correction, exercising re-flush + dedup together).
3. D3 crash-tail (truncated final line → `incomplete`; malformed earlier line → raises).
4. Streaming + conftest-gate I/O timing.
Per-event flush PERFORMANCE on a big run was never measured (the lyrics-generator fixture, mocked, is the
at-scale asset). Don't pre-optimize; if it's bad, batched-flush-with-periodic-fsync is the lever.

## How THIS user operates (observed across this session — steers HOW you work)

- **Tight review→fix→review loops, ≤4 reviewers.** They explicitly asked for "the 4 most relevant subagents."
  The proven set here, by risk dimension: silent-failures, impact-completeness, feature-interactions,
  concurrency-safety (I dropped test-fidelity and covered known test gaps myself). Iterate, don't one-shot.
- **They distrust "unreachable"/"can't happen."** A reviewer DISPROVED my plan's "the `_echo` trigger is
  unreachable" claim (it was reachable via `--only <sub-workflow> --report`). The earlier `only_node` bug was
  also a "currently harmless" path that was one step from real. **In Phase 3, verify edge reachability; never
  hand-wave it.**
- **They will ask "are you FULLY happy? any loose ends?"** — and they mean it as a prompt to hunt your own
  holes, not reassure. Have a calibrated number + a concrete list. My introspection found the only_node bug;
  that's the bar.
- **Reproducible verification** (copy-paste commands, real numbers, named baseline delta) > "tests pass."
- **They stage changes explicitly** ("stage all changes before deploying reviews") and stop-and-discuss at
  decision points / plan deviations (I re-cut the Phase-1/2 boundary and they approved). Flag Phase-3
  sequencing decisions the same way; lead with reasoning + a recommendation, not a menu.
- **North star: "simplicity of the FINAL code, not how easy it is to get there."**

## Git / state notes

- 36 files staged, working tree clean. `context/CONTEXT.md` (the "Run" domain-noun addition) is staged — it
  was NOT my edit (a pre-existing uncommitted change I flagged twice); the user said "stage all changes," so
  it's in. `baseline-named.txt`/`baseline-trace_files.txt` are the captured pre-change baseline (verification
  artifacts). No commit has been made — the user controls commits.
- `node_id` is declared on `WorkflowExecutor` ONLY (class attr `node_id: str = ""`), deliberately NOT on
  `BaseNode` — declaring it globally broke 2 ClaudeCode tests that distinguish an ABSENT node_id. Don't
  "tidy" it onto BaseNode.

## Deferred / acceptable gaps (don't re-litigate, but know they exist)

- 2-deep OLD-path test (sub-wf→batch→sub-wf) not written — clause-2 (buffer `is_run_scoped=False`) is
  independently sufficient and the ADR-0008 checkpoint + reasoning cover it. Cheap to add if you want it.
- `--only <sub-workflow>` was the only_node-bug trigger; fixed + regression-tested. If Phase 3 changes
  `engine.run`'s collector install/save-restore (it shouldn't need to), preserve the `_pflow_depth == 0`
  `only_node` guard at `engine.py:~649`.

## Relevant files (the ones Phase 3 actually touches)

- `core/trace_io.py` — `emit_flat_events_to_lines`, `_partition_trace_lines`, `_rebuild_event_tree`,
  `reconstruct_trace_from_lines`, `load_trace_file`, `intern_blobs`/`substitute_refs`, `_RESERVED_LINE_KEYS`,
  `BLOB_SENTINEL`/`INTERN_MIN_BYTES`. (The whole reader/writer surface.)
- `runtime/workflow_trace.py` — `save_to_file` (→ finalize/stream), `mark_last_event_failed` (→ re-flush),
  `format_trace_filename`, the `_HostFrame`/descend/ascend machinery (don't touch — Phase 2 solid),
  `_stream`/`_declared_blobs` are the fields Piece 4 adds.
- `cli/commands/run.py::_save_trace_file` (`:147`) — the single CLI call site to swap to `finalize()`.
- `tests/conftest.py` (the gate), `tests/test_runtime/test_emit_time_trace.py` (Phase-2 contract — extend +
  update save calls), `tests/test_core/test_trace_io.py` (delete the A–C crash-tail test, add D3).

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read
> and understood by summarizing the key points, then state you're ready to proceed.
