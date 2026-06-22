# Task 172 Review: Streamable trace event log (emit-time producer)

## Metadata
- Implemented 2026-06-22 (Phase 1+2: `858db139`; Phase 3 + follow-ups: `75dafe41` → `851b774e`).
- Branch `feat/streamable-trace-event-log-emit-time-producer` (not yet merged/pushed at review time).
- Reviewed by manual 4-specialist round + a 5-agent `/deep-review`; no Critical/High.
- Project stakes: **no external users** (format changes are cheap), but **the test suite + the in-repo
  consumers ARE the contract** — weight behavior preservation and consumer correctness, not migration.
- The chronological journey (decisions, dead ends, the boundary re-cut) lives in
  `implementation/progress-log.md`. This review is the distilled forward-reference.

## Read First — the load-bearing block

**What exists now:** the run-scoped `WorkflowTraceCollector` assigns correlation at *emit* time and
**streams one JSONL line per node as the run executes** (CLI only), with inline-first-occurrence blobs and
a `finalize()` trailer; the reader does a two-pass reconstruct + crash-tail tolerance. One flat in-memory
store; the nested tree is a derived `tree()` view.

**Read these first (file · symbol):**
- `runtime/workflow_trace.py` · `WorkflowTraceCollector` — `record_node_execution` (stamps correlation +
  `_flush_event`), `descend`/`ascend`/`_HostFrame` (reserve-seq-at-descent), `_open_stream`/`_flush_line`/
  `finalize` (streaming), `mark_last_event_failed` (re-flush), `_top_level_events`/`_aggregates` (scoping),
  `save_to_file` (dual dispatch).
- `core/trace_io.py` · `_rebuild_event_tree` (two-pass), `reconstruct_trace_from_lines`, `load_trace_file`
  (crash-tail), `_partition_trace_lines` (`blob` arm), `intern_event_leaves`/`_inline_blobs`, `_RESERVED_LINE_KEYS`.
- `execution/runner.py:~141` · `stream_to_disk=config.trace_enabled` — the production streaming gate.
- `tests/conftest.py` · `disable_trace_file_writes_by_default` — the test gate (no-ops `_open_stream` + `save_to_file`).
- Consumers (read-only, but the contract this serves): `workflow_trace._iter_workflow_traces` /
  `load_full_run_events`, `prompt_cache_analysis/trace_loading.py::_collect_candidate_traces`,
  `core/trace_report.generate_report`.

**Invariants that must NOT break (rule → consequence):**
1. **Streaming is main-thread-only.** A worker thread must never reach the run collector's `_flush_event`/
   `_next_seq`/`descend`. Enforced by the `__index__`/`is_run_scoped` routing gate in
   `workflow_executor.py::_open_child_trace` (the SAME gate that protects no-lock `seq`) + `_assert_owner_thread`.
   Break it → shared-file-handle corruption + `seq` race.
2. **`_iter_workflow_traces` MUST NOT filter `final_status`.** Each consumer owns its own status policy. Move a
   filter in → breaks analyze-cache's failed-bucket fallback AND lets a crash (`incomplete`) trace be trusted.
3. **Status/count aggregations scope to `_top_level_events()` (`parent_id is None`), never raw `self.events`.**
   Else a sub-workflow child's `node_id` shadows a same-id top-level node → wrong `final_status`/`failed_node_ids`.
4. **`_RESERVED_LINE_KEYS` is the single shared constant** — the producer asserts none are pre-set, the reader
   strips them. Add a correlation field → add it here and have the producer own (stamp) it; never emit a reserved
   key as real data.
5. **One on-disk blob representation: inline `blob` lines** (no `blobs` trailer). Both writers go through
   `intern_event_leaves`. A reader/writer that reintroduces a `blobs` trailer line is corruption (unknown kind).
6. **MCP must not stream** (`RunnerConfig(trace_enabled=False)`). Else MCP runs write to `~/.pflow/debug` and
   become unintended `--only`/analyze-cache snapshot sources.

## What Was Built (actual vs. planned)

- **KEPT `flatten_trace_to_lines` (plan said remove it).** It's the A-C round-trip oracle in `test_trace_io.py`
  AND the buffer/test whole-file writer used across 9 files. Instead of removing it, **unified the blob
  representation**: both `flatten` and the streaming path emit inline `blob` lines via one shared
  `intern_event_leaves`/`_inline_blobs`. Achieves the plan's "one representation" intent (one reader arm, one
  disk shape) without gutting coverage.
- **MCP needed explicit `trace_enabled=False` (plan said "no MCP changes").** MCP free-rides on the
  `RunnerConfig` default (`True`); without the opt-out, the new streaming would start writing MCP traces. Two
  `run()` sites in `execution_service.py`. Verified MCP never persisted a trace before (the `WorkflowTraceCollector`
  has no `trace_path` attr; the MCP error path reads `hasattr(..., "trace_path")` → always False). The docs
  claiming "MCP traces always saved" were stale (pre-existing) — fixed 3 agent-facing spots.
- **DELETED `emit_flat_events_to_lines`** (added in step 2). Callerless once run-scoped saves stream; its one
  canary test was re-pointed at the real streaming path (stronger — drives `finalize()` + `load_trace_file`).
- **Two-layer test gate** (plan named only the conftest extension): production `stream_to_disk` flag + the
  conftest `_open_stream` no-op. Both are needed — streaming now happens *during* `record_node_execution`, not at
  an end-of-run save, so the old `save_to_file`-only no-op no longer suppresses it.
- **Added `__del__` (defensive stream close) + `_assert_owner_thread()` on `_flush_event`** — from self-audit +
  concurrency review, not the plan.

## Patterns & Anti-Patterns

**Patterns to reuse:**
- **One interning primitive for streaming + whole-file.** `intern_event_leaves(obj, declared, emit_blob)`
  (streaming counterpart of `intern_blobs`) is shared by `_flush_line` (per-event) and `_inline_blobs`
  (whole-file). Persist `declared` across calls → blob declared once, backward-only refs.
- **Two-pass reconstruct makes flush order immaterial.** Pass 1 dedup-by-`id` last-wins; pass 2 link in `seq`
  order. ONE mechanism serves three needs: dead-end re-flush (corrected line wins), crash-tail transitive
  orphan-drop (incomplete only), and host-after-ascend ordering. `parent.seq < child.seq` (reserve-at-descent)
  guarantees parents link before children.
- **Shared aggregate computation.** `_aggregates()`/`_meta_fields()` feed both streaming `finalize` and buffer
  `save_to_file` (`_build_trace_data`), so the two writers can't drift on a field's value or scoping.
- **Two-layer gate** for any "write during a run" feature: a production config flag + a test-fixture no-op.

**Anti-patterns (tried/considered, rejected):**
- Don't bend `intern_blobs` (whole-tree → one trailer map) into streaming — per-event can't see future events.
- Don't gate streaming on `config.trace_enabled` without making MCP explicitly opt out (free-riding default).
- Don't `os.fsync` per event — `file.flush()` (to OS page cache) is enough; measured 8.9 µs/event.
- Don't promote batch items to spans without teaching `_rebuild_event_tree` to re-nest `batch_items` (today it
  only re-nests `sub_workflow_events`; `tree()` and "batch inline" are coupled).

## Gotchas & Non-Obvious Coupling

- **The `__index__`/`is_run_scoped` gate is doubly load-bearing.** It routes batch-item sub-workflows to a
  buffer collector (`is_run_scoped=False` → `stream_to_disk=False` → `_flush_event` no-ops AND `seq` untouched).
  It protects BOTH no-lock `seq` and streaming-main-thread-only. Lives in `workflow_executor.py::_open_child_trace`.
- **`finalize()` ordering:** `_finalized=True` is set AFTER `_open_stream()` (so a zero-event run still writes
  meta), and `_open_stream` guards on `_finalized` to never reopen a closed stream.
- **`mark_last_event_failed` re-flushes via `_flush_event`** — the ONLY post-flush correction (api-warning flips
  at *construction* via `record_trace(error=...)`). It scans ALL events `reversed(self.events)` (not top-level),
  so a sub-workflow-internal dead-end (GH #250) is reached; the dedup-by-id makes the corrected line win on disk
  regardless of the host line flushing later.
- **Filename uses `self.start_time` (construction), not save-time** — stable from first flush; `%f` preserves
  the #443 `--only` collision entropy. `_trace_recency_key` parses it identically.
- **`ancestor_path`/`port` are written then STRIPPED on read** (reserved). Equivalence tests assert them on
  `collector.events` (raw, never stripped), NOT on `tree()` — that's why they survive Piece 5.1's strip.
- **`incomplete` traces are NOW a real, loadable artifact** (crash-tail). Before Task 172 a crash left no file.
  Consumers must reject them as truth (they do) — this is a genuinely new interaction.
- **A streamed-but-unfinalized collector leaks an open handle until GC** (`__del__` closes it). Production always
  finalizes via the CLI; only matters for tests. Real `~/.pflow/debug` is untouched by the suite (isolated tmp homes).

## Integration Points

- **New dependents on the producer:** CLI `cli/commands/run.py::_save_trace_file` → `finalize()`;
  `execution/runner.py` → constructs the collector with `stream_to_disk=config.trace_enabled`.
- **Contract changed — on-disk trace format:** `blobs` trailer line → inline `blob` lines; a crash-truncated
  file now reconstructs-as-`incomplete` (was: whole-trace skip). No external readers (no users); all in-repo
  consumers funnel through the single `core/trace_io.load_trace_file` seam, so they inherited the change for free.
- **`_RESERVED_LINE_KEYS` gained `ancestor_path`/`port`** — shared by the producer collision guard, the reader
  strip, and `flatten`'s guard.
- **MCP:** `RunnerConfig(trace_enabled=False)` at `execution_service.py` execute + registry_run sites.
- **Downstream tasks this unblocks:** Task 169 (SSE transport) and Task 173 (live overlay consumer) — they meet
  the producer only at the D1 event schema + the `NodeId=(node_id, ancestor_path)` join key (ADR-0008/ADR-0003).

## Tests That Matter

Run when touching this subsystem: `uv run pytest -m trace_files` (the authoritative format oracle) +
`tests/test_runtime/test_emit_time_trace.py` + `tests/test_core/test_trace_io.py`.

- **`test_subworkflow_child_id_collision_does_not_corrupt_top_level_status`** — MUTATION-VERIFIED: regress
  `_top_level_events()` → raw `self.events` and `final_status` flips to success. Guards invariant #3.
- **`test_crash_truncated_streamed_trace_is_rejected_as_truth_by_consumers`** — MUTATION-VERIFIED: regress
  crash-tail `incomplete`→`success` and the test fails. Guards invariants #2 + the consumer policy.
- **`test_emit_equivalence_*` (incl. `_cached_node_inside_subworkflow`)** — assert `tree()==reconstruct(disk)`
  + **hardcoded cost literals** (the anti-"equal but wrong" guard: both views feed the same `TraceTree`, so a
  missed `cached`→`status` reader leaves them equal-but-wrong; only the independent literal catches it).
- **`test_old_path_parallel_batch_of_subworkflows_stays_nested`** — the empirical proof that streaming stays
  main-thread-only: a parallel batch of sub-workflows yields `len(collector.events)==1` (workers never flatten
  into the run collector). Guards invariant #1.
- **`test_streaming_dead_end_re_flush_corrects_on_disk`** + `_inside_subworkflow_reflushes_to_disk` — the
  re-flush + dedup (asserts both on-disk lines `["success","failed"]` AND the deduped reconstruct).
- **`test_host_recorded_after_ascend_with_frame_keeps_children_linked`** — the canary: a host recorded AFTER
  ascend (api-warning timing) must reuse its reserved frame or children orphan and reconstruct raises.
- **`test_streamed_trace_is_read_by_all_disk_consumers`** — all three disk consumers (`generate_report`,
  `_iter_workflow_traces`, `analyze()`) read a real streamed trace.
- **`test_load_trace_file_tolerates_truncated_final_line`** + `test_reconstruct_incomplete_drops_dangling_subtree_and_recovers_prefix`
  — crash-tail + transitive orphan-drop (full-structure assertion, not top-level-only).

## Performance (observed, not theorized)
Per-event flush overhead = **8.9 µs/event** (17.8 ms for 2000 trivial nodes). It's `file.flush()` to the OS
page cache, not `os.fsync`, so it's noise for any real run. If a pathological huge-trivial-node run ever needs
it, batched-flush-with-periodic-fsync is the lever.

---
*Distilled from the implementation context of Task 172. The chronological journey lives in
`implementation/progress-log.md` — this review is the durable forward-reference, not a re-narration of it.*
