# Task 172 Review: Streamable trace event log (emit-time producer)

## Metadata
- Implemented 2026-06-22 (Phases 1-3); **hardened + PR-reviewed + handed off 2026-06-23.** Shipped in **PR #530**
  (base `main`) — see the PR for commits/diffs/review threads (hashes aren't cited here: the branch was rebased
  once already, and a squash-merge will replace them all; PR #530 + file·symbol are the durable anchors).
- **Refreshed 2026-06-23** (code-verified via 4 parallel searchers) to fold in the PR #530 review fixes, the
  error-path hardening, and the Task 173 consumer handoff — the original 2026-06-22 review predated all three.
- Reviewed: manual 4-specialist + 5-agent `/deep-review` (Phase 3); then **PR #530** (Codex 5×P2 + claude[bot])
  + 3 **blind** `/deep-review` rounds → 5 fixes (C3/C4/C5/W1/S2) + error-path hardening. No Critical/High survives.
- Project stakes: **no external users** (format changes are cheap), but **the test suite + the in-repo
  consumers ARE the contract** — weight behavior preservation and consumer correctness, not migration.
- The chronological journey (decisions, dead ends, the boundary re-cut, the PR-review round — with commits) lives
  in `implementation/progress-log.md`. This review is the distilled forward-reference.

## Read First — the load-bearing block

**What exists now:** the run-scoped `WorkflowTraceCollector` assigns correlation at *emit* time and
**streams one JSONL line per node as the run executes** (CLI only), with inline-first-occurrence blobs and
a `finalize()` trailer; the reader does a two-pass reconstruct + crash-tail tolerance. One flat in-memory
store; the nested tree is a derived `tree()` view.

**Read these first (file · symbol):**
- `runtime/workflow_trace.py` · `WorkflowTraceCollector` — `record_node_execution` (stamps correlation +
  `_check_reserved_collision` guard + `_flush_event`), `descend`/`ascend`/`_HostFrame` (reserve-seq-at-descent),
  `_open_stream`/`_flush_line`/`finalize` (streaming; **OSError → `_disable_streaming`, best-effort tail**),
  `_assert_owner_thread` (no-lock guard — `if/raise`, not `assert`), `mark_last_event_failed` (re-flush),
  `_add_llm_data` (**pops** captured prompt/system — C4 anti-bleed), `_top_level_events`/`_aggregates` (scoping),
  `__del__` (defensive close), `save_to_file` (dual dispatch).
- `core/trace_io.py` · `_rebuild_event_tree` (two-pass), `reconstruct_trace_from_lines`, `load_trace_file`
  (crash-tail; raises on content **after** `run.complete`), `_partition_trace_lines` (`blob` arm — raises on
  missing `md5`/`value`), `intern_event_leaves`/`_inline_blobs`, `_RESERVED_LINE_KEYS`.
- `execution/runner.py` · `stream_to_disk=config.trace_enabled` (`:150`, the streaming gate) **+ runner-owned
  `finalize()` in `run()`'s `finally`** (`:179-189`, gated on `config.finalize_trace`, `contextlib.suppress`).
- `execution/result.py` · `RunnerConfig` — `trace_enabled` + `finalize_trace` (both default `True`).
- `core/trace_report.py` · `_resolve_final_status` (`:751`, **dual-read** `status=="failed" or success is False` — W1).
- `tests/conftest.py` · `disable_trace_file_writes_by_default` — the test gate (no-ops `_open_stream` + `save_to_file`).
- Consumers (read-only, but the contract this serves): `workflow_trace._iter_workflow_traces` /
  `load_full_run_events`, `prompt_cache_analysis/trace_loading.py::_collect_candidate_traces`,
  `core/trace_report.generate_report`.

**Invariants that must NOT break (rule → consequence):**
1. **Streaming is main-thread-only.** A worker thread must never reach the run collector's `_flush_event`/
   `_next_seq`/`descend`. Enforced by the `__index__`/`is_run_scoped` routing gate in
   `workflow_executor.py::_open_child_trace` (`:342-354`, the SAME gate that protects no-lock `seq`) +
   `_assert_owner_thread` (now an **`if/raise RuntimeError`**, not a bare `assert` — survives `python -O`; S2).
   Break it → shared-file-handle corruption + `seq` race.
2. **`_iter_workflow_traces` MUST NOT filter `final_status`.** Each consumer owns its own status policy. Move a
   filter in → breaks analyze-cache's failed-bucket fallback AND lets a crash (`incomplete`) trace be trusted.
3. **Status/count aggregations scope to `_top_level_events()` (`parent_id is None`), never raw `self.events`.**
   Else a sub-workflow child's `node_id` shadows a same-id top-level node → wrong `final_status`/`failed_node_ids`.
4. **`_RESERVED_LINE_KEYS` is the single shared constant** — the producer's `_check_reserved_collision`
   **raises** (`if/raise`, survives `-O`; S2) if any are pre-set, the reader strips them. Add a correlation
   field → add it here and have the producer own (stamp) it; never emit a reserved key as real data.
5. **One on-disk blob representation: inline `blob` lines** (no `blobs` trailer). Both writers go through
   `intern_event_leaves`. A reader/writer that reintroduces a `blobs` trailer line is corruption (unknown kind);
   a `blob` line missing `md5`/`value` also raises (silent-failures fix).
6. **MCP must not stream** (`RunnerConfig(trace_enabled=False)`). Else MCP runs write to `~/.pflow/debug` and
   become unintended `--only`/analyze-cache snapshot sources.
7. **Trace I/O is best-effort and must NEVER alter execution** (the post-review #1 fix — the one genuine bug).
   `_open_stream`/`_flush_line` catch `OSError` → `_disable_streaming` (logs once, sets `_stream_failed`, keeps
   the in-memory trace complete); a disk-full / read-only `~/.pflow/debug` can't turn a successful node into a
   failure or mask a real error. The owner-thread + reserved-key guards stay **OUTSIDE** the catch (programming
   errors stay loud; only disk faults are tolerated). `finalize()` is `try/finally` (always closes, returns
   `None` when gated/disabled). Reader half: `run.complete` must be the **last** line — content after it raises.

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
  concurrency review, not the plan. (S2 later made both this and the reserved-key guard `if/raise`, not `assert`.)

## Post-review hardening (PR #530 + 3 blind `/deep-review` rounds — all AFTER the first review)

Five behavior-preserving error-path / correctness fixes landed after the build; **none changed the contract.**
Their durable forward-facts are folded into the sections above — **C3** (runner-owned finalize) in Gotchas +
Integration, **C4** (prompt-bleed pop-consume) + **C5** (large-meta `intern=False`) in Gotchas, **W1**
(`_resolve_final_status` dual-read) in Read-First, **S2** (guards → `if/raise`) in invariants #1/#4, and the
**I/O-isolation bug** as invariant #7. The per-fix narrative + commits live in the progress-log (PR #530 round). *Disputed/deferred on purpose — C1 (old `blobs`-trailer → `JSONDecodeError`, readers skip gracefully),
C2 (legacy `cached:true` over-count), S3 (`node_id=""`→`descend("")`, unreachable): tracked in GH #531.*

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
- **The `meta` line is flushed with `intern=False` (C5).** A >1KB meta field (e.g. a long `workflow_path`) must
  not emit a `blob` line *before* the `pflow_trace` marker on line 1 — that hides the marker → unreadable trace.
  Don't route the meta line through the interning `_flush_line` default.
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
- **Finalization is RUNNER-owned (C3), not CLI-only.** `run()`'s `finally` finalizes for *any* caller (CLI,
  MCP-no-op, or a library caller that just inspects the result), gated on `config.finalize_trace` (default
  `True`), `contextlib.suppress`-wrapped + idempotent. The CLI is the exception: it sets `finalize_trace=False`
  and finalizes *itself* after `set_json_output` mutates the trace post-run. `__del__` is now only the
  last-resort for a collector that streamed but was never finalized (a raw test collector). Real `~/.pflow/debug`
  is untouched by the suite (isolated tmp homes).
- **One run-scoped collector ⇒ `llm_prompts`/`llm_systems` are shared and keyed by BARE `node_id` (C4).** A
  parent node sharing a child sub-workflow LLM node's id would inherit its prompt — so `_add_llm_data` **pops**
  (consume-on-read): a captured prompt belongs only to the node execution that triggered the hook. Don't revert
  `.pop`→`.get`; mutation-proven to bleed.

## Integration Points

- **New dependents on the producer:** `execution/runner.py` constructs the collector with
  `stream_to_disk=config.trace_enabled` (`:150`) **and finalizes it** in `run()`'s `finally` (`:179-189`, gated
  on `config.finalize_trace`); CLI `cli/commands/run.py::_save_trace_file` → `finalize()` (CLI opts the runner
  out via `finalize_trace=False` and finalizes itself). `RunnerConfig` gained `finalize_trace` (`result.py:28`).
- **Contract changed — on-disk trace format:** `blobs` trailer line → inline `blob` lines; a crash-truncated
  file now reconstructs-as-`incomplete` (was: whole-trace skip). No external readers (no users); all in-repo
  consumers funnel through the single `core/trace_io.load_trace_file` seam, so they inherited the change for free.
- **`_RESERVED_LINE_KEYS` gained `ancestor_path`/`port`** — shared by the producer collision guard, the reader
  strip, and `flatten`'s guard.
- **MCP:** `RunnerConfig(trace_enabled=False)` at `execution_service.py` execute + registry_run sites.
- **Downstream tasks this unblocks:** Task 169 (SSE transport) and Task 173 (live overlay consumer) — they meet
  the producer only at the D1 event schema + the `NodeId=(node_id, ancestor_path)` join key (ADR-0008/ADR-0003).
- **Handoff artifacts (2026-06-23, for Task 173):** the **D1 schema is now corrected to as-built**
  (`task_133/design/d1-event-schema.md` — was stale: `blobs` trailer, `status` "open decision", `success:bool`),
  and a **consumer-handoff braindump** (`task_173/starting-context/braindump-producer-handoff-2026-06-23.md`)
  lists the tailer traps a producer review can't carry (read-raw-not-`load_trace_file`, truncated-final-line-is-
  normal, same-`id`-last-wins, the two-derivation join risk, MCP-doesn't-stream, eager-`meta`).

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

*Added after the first review (the producer↔consumer seam + the PR-#530 hardening — run these too):*
- **`test_runtime_event_refs_join_onto_the_static_graph`** — MUTATION-VERIFIED, **the highest-value pin**:
  the producer's emit-time `ancestor_path` and the renderer's `RFRef.ancestor_path` are independent
  derivations; this asserts every runtime event JOINS onto a static-graph node (ADR-0003). Regress the
  producer's `batch_index` → the nested child won't join → fails. The silent-overlay bug both component suites
  miss. (+ `test_streamed_wire_is_joinable_and_blob_resolvable_by_a_tailer` and
  `test_streamed_wire_dead_end_correction_is_last_wins_by_id_for_a_tailer` — read the RAW wire as a tailer:
  join key survives, blobs resolve backward-only, same-`id` re-flush is last-wins.)
- **`test_streaming_io_fault_*`** (4: disables-streaming, doesn't-fail-the-run, preserves-original-node-error,
  finalize-fault-returns-none) — guard invariant #7 (trace I/O never alters execution).
- **`test_runner_finalizes_streamed_trace_for_library_callers`** + `_defers_finalize_when_opted_out` +
  `_finalizes_a_complete_trace_when_the_run_fails` (MUTATION-VERIFIED) — guard C3 (runner-owned finalize).
- **`test_child_llm_prompt_does_not_bleed_into_same_id_parent_node`** (MUTATION-VERIFIED end-to-end) +
  `test_add_llm_data_consumes_prompt_so_it_cannot_bleed_to_same_id_node` — guard C4 (prompt bleed).
- **`test_streaming_large_meta_field_stays_readable`** (C5) and, in `test_core/test_trace_report.py`,
  **`test_resolve_final_status_does_not_flip_failed_legacy_trace_to_success`** (W1).

## Performance (observed, not theorized)
Per-event flush overhead = **8.9 µs/event** (17.8 ms for 2000 trivial nodes). It's `file.flush()` to the OS
page cache, not `os.fsync`, so it's noise for any real run. If a pathological huge-trivial-node run ever needs
it, batched-flush-with-periodic-fsync is the lever.

## Deferred work + honest ceiling
- **eager-`meta` write → Task 173.** The producer opens the file **lazily on the first node completion**
  (`_open_stream` ← `_flush_event`), so an in-flight first node is undiscoverable and a crash mid-first-node
  leaves no file — directly undercutting "watch a run live." The fix (write `meta` at run start) is a small
  producer change scoped to 173 because its ripple (`report.py` newest-by-mtime + analyze-cache disclosure would
  then see `meta`-only files) must be guarded against the consumer that needs discoverability. Spelled out in
  `task-173.md` Requirements + the consumer braindump.
- **GH #531 — drop pre-Task-172 format support + consolidate to one writer/reader.** The legacy single-object
  reader (`resolve_blobs`/`intern_blobs` + the `load_trace_file` branch), the dual/dead writer
  (`flatten_trace_to_lines`, kept alive by ~60 bare-collector `save_to_file()` tests), the W1 dual-read, and C2.
  NOT a trivial delete — entangled with analyze-cache's single-object-JSON fixtures (~9 files + 4 fixtures →
  JSONL migration). Codex #4 (dedup immutable-field validation) + claude S3 (`node_id=""` guard) noted there.
- **Honest ceiling (unchanged):** the producer is shipped ahead of its consumer (Task 173), so the streamed
  *shape* is validated only producer-side — incl. the new join pin — until Task 173 tails it live. No
  producer-side test can close the SSE-transport + frontend-render gap; that's 173's to validate.

---
*Distilled from the implementation context of Task 172. The chronological journey lives in
`implementation/progress-log.md` — this review is the durable forward-reference, not a re-narration of it.*
