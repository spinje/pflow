# Task 172: Streamable trace event log — emit-time producer (Task 133 Phase D)

## Description

Make pflow's trace stream **incrementally, at emit time**, so a live UI overlay can tail it as a run
executes (and so crash-resume / observability inherit a self-consistent partial log). This is the
**producer** half of the live-execution-overlay architecture (ADR-0008) — the deferred "Phase D" of
Task 133. It **reuses** Task 133 A–C's JSONL reader/reconstruction machinery; the changes are *when*
correlation is assigned (save-time → emit-time), *how* events are collected (one run-scoped collector), and
a set of **bounded, intentional on-disk shape changes** enabled by the no-backward-compat decision below:
per-node `status` enum (replacing `success`/`cached`), inline-first-occurrence blobs (was a trailer), and a
new `ancestor_path`/`port` (stripped on read). See Design Decisions.

## Status

not started

## Priority

medium

## Problem

Task 133 A–C made the trace flat JSONL on disk, but it is still **written once at the end**: correlation
(`id`/`seq`/`parent_id`/`run_id`) is *derived at save time* by walking the in-memory nested tree, and each
sub-workflow gets its **own** collector whose events are embedded into the parent after it returns. A live
overlay can't tail an end-dumped file, and a hard crash leaves **no file at all**. To stream, the trace
must be emitted as each node completes, from a single run-scoped collector, with correlation assigned at
emit — which is the invasive engine change A–C deliberately avoided.

## Solution

Collector unification + emit-time streaming, keeping A–C's on-disk format and reader:

- **One run-scoped collector** (eliminate the per-sub-workflow collectors and their child→parent embed).
- **Host-descent stack** on that collector, pushed/popped as the engine descends into
  `WorkflowExecutor`/batch, supplying emit-time `parent_id` + `ancestor_path` (the graph-join field).
- **Flat in-memory store** whose events carry `id`/`seq`/`parent_id`; the nested tree becomes a **derived
  `tree()` view** reusing A–C's `_rebuild_event_tree`.
- **Incremental flush** (one JSONL line per event as recorded) + **inline-first-occurrence blobs** (D3,
  backward-only refs so a forward tailer / crash-truncated log stays self-consistent).

The D1 event schema (`.taskmaster/tasks/task_133/design/d1-event-schema.md`) is the contract. Estimated
~6–7/10 complexity, re-estimate from a ~300 LOC floor (the host-stack + in-memory-reader migration are
additional, bounded). The scary concurrency question is already retired (no-lock `seq` verified valid).

## Design Decisions

- **Flip in-memory to flat (not keep-nested).** One representation (flat + `parent_id`); the nested tree
  is a derived projection via the *existing* `_rebuild_event_tree`. Keep-nested would need new re-nesting
  logic *and* leave two maintained shapes — flat is less code and the cleaner end-state (ADR-0008).
- **`degraded` is run-level, not per-node.** Recovery is decided at engine step 17.5, *after*
  `record_trace` at step 16, so emit-time per-node `degraded` is impossible — and a failed-then-recovered
  node is honestly `failed` at the node level while the *run* is degraded (`final_status`, already
  computed). Per-node status = `success`/`cached`/`failed`.
- **DECIDED — adopt the explicit `status` enum** (`success`/`cached`/`failed`), replacing `success: bool` +
  `cached`. One producer-set field beats derivation repeated across ~15 reader sites; the no-backward-compat
  decision removes the only objection (an enum would otherwise coexist forever with legacy booleans). This
  *does* change the on-disk event shape + reconstructed dict — so the verification anchor is **`tree()` ≡
  on-disk reconstruct ≡ correct cost/`final_status`/`failed_node_ids`** (asserted via literals), **not**
  byte-identity to A–C.
- **DECIDED — no backward-compat with old traces.** Old on-disk traces need not be readable and test fixtures
  may be regenerated — this is what makes the `status` enum and inline blobs clean (no legacy dual-read).
  *Out of scope (left intact):* the `... or "success"` absent-`final_status` defaults and the legacy
  single-object reader path — entangled with `analyze-cache` reuse policy + synthetic fixtures, inert for
  modern traces, and removing them is a separate cleanup.
- **DECIDED — lenient reconstruct for *incomplete* (crash) traces only.** A dangling `parent_id` in a trace
  with no `run.complete` drops the dangling child **transitively** (recovering everything well-formed); the
  same in a *complete* trace still raises. This makes a crash-mid-sub-workflow trace recoverable (children
  flush before their host's completion event). Robust resume remains Task 164.
- **`ancestor_path`/`port` are writer-owned and stripped on read.** Add them to `_RESERVED_LINE_KEYS` so they
  don't appear in the reconstructed dict; the writer must *own* them (like `id`/`seq`/...) — the producer's
  collision-guard imports the same `_RESERVED_LINE_KEYS` constant the reader strips with (one source of truth).
- **No-lock `seq` is a routing rule, not absence.** The collector is reachable from workers via the
  shallow-copied `shared`; the discipline is workers never *call* its recording/`seq` methods — they route
  to worker-local buffers (`_batch_trace`, child events) folded in, with `seq` assigned, at the
  main-thread drain.

## Dependencies

- **Task 133 A–C** (shipped on `feat/unified-node-storage`) — the JSONL format, `flatten_trace_to_lines`,
  `reconstruct_trace_from_lines`/`_rebuild_event_tree`, the reader. This task reuses all of it.
- None blocking otherwise. Task 169 (transport) and Task 173 (consumer) depend on *this*, not vice versa.

## Requirements

### Correlation & identity
- Assign `id`/`seq`/`parent_id`/`run_id` at **emit** time from a host-descent stack on the run-scoped
  collector (not derived at save).
- Stamp `ancestor_path` (ordered `[{node_id, batch_index}]`) per event, mirroring `NodeId.ancestor_path`
  so it joins `RFRef`/`sameRef`. `port` is `null` for body nodes.
- Loop revisits keep distinct `id`/`seq`, same `(node_id, ancestor_path)` (no identity collision).

### In-memory representation
- `self.events` becomes a flat list; events carry `id`/`seq`/`parent_id`.
- A single `tree()` accessor reuses `_rebuild_event_tree` for the nested view.
- **Cost readers** (`collect_llm_calls` — the CLI + MCP summary seam — and `_collect_llm_summary`) walk
  `tree()` recursively (must not under-count sub-workflow LLM cost).
- **`final_events_by_node`** (and `_unrecovered_failed_node_ids`/`_determine_trace_status`/`failed_node_ids`)
  use **top-level-only scoping** (`tree()` roots / `parent_id is None`) — a flat list lets a child's
  `node_id` overwrite a parent's → wrong `final_status`.
- Migrate every in-memory reader of raw `self.events` (also: `nodes_executed` count semantics,
  `cli/commands/run.py::_echo_target_node_path`, `mark_last_event_failed`). The complete list is in the
  review findings.

### Concurrency
- No new lock/atomic; assign `seq` only on the main thread (record + batch drain). Re-verify spike #2's
  invariant against current code before relying on it.

### Streaming & format
- Flush each event as a JSONL line when recorded; finalize writes `run.complete` + `blobs` trailers.
- Inline-first-occurrence blobs (D3); a crash-truncated prefix must still load (no `run.complete` →
  `final_status="incomplete"`).
- **Trailing-line tolerance (deferred from A–C — PR #525 review).** `load_trace_file` must drop a
  single *truncated final line* and reconstruct-as-incomplete, while still raising on corruption
  anywhere earlier. This is **coherent only once D3 lands**: in A–C the last line is the `blobs`
  *trailer*, so tolerating a truncated tail would drop blobs → unresolved `$pflow_blob` refs, not
  `incomplete`. With inline-first-occurrence blobs the trailing line is an event/`run.complete`, so the
  tolerance yields a clean `incomplete`. Until then A–C eagerly parses every line (a truncated tail →
  `JSONDecodeError`, whole trace skipped); soften-only docs shipped in A–C. Add the real
  trailing-line-tolerance test here (see "Crash-tail" in Verification), replacing the A–C
  documenting test (`test_load_trace_file_skips_truncated_tail_*`) that pins today's skip behavior.
- The reconstruction *machinery* (`reconstruct_trace_from_lines`/`_rebuild_event_tree`/`substitute_refs`) is
  reused; the reconstructed nested dict changes only in the **bounded, intentional** ways above (`status`
  replaces `success`/`cached`; `ancestor_path`/`port` stripped on read; blobs relocate inline). The
  reader gains a two-pass rebuild (dedup-by-id last-wins + transitive lenient orphan-drop) — see the plan.

### Boundaries (do not break)
- **Leave the `__pflow_prompt_cache__` save/restore alone** — it is intentionally per-workflow; only the
  `__trace_collector__` half unifies.
- Keep the warmup item (`is_warmup`) inline and filtered from call-counting; don't let it become a span.

## Implementation Notes

- The engine surgery touches `runtime/workflow_trace.py`, `runtime/engine/engine.py`,
  `instrumentation.py`, `batch_executor.py`, `workflow_executor.py`. **file:line refs in the task-133
  implementation-plan are stale (main moved them) — re-verify before editing.**
- Step-16-before-step-17.5 ordering is load-bearing (`record_trace` must read `shared[node_id]` before
  `mark_node_failed` moves it). Don't reorder casually.
- Batch-item promotion is deferred — but note `tree()`/`_rebuild_event_tree` only re-nests
  `sub_workflow_events`, so a future promotion must teach it `batch_items` (they're coupled).

## Verification

> **The operational test plan + per-phase exit gates are in `implementation/implementation-plan.md`
> (§Verification, §Build order). This section is the *rationale* (why no separate baseline harness) — keep it.**

**No separate baseline harness for this task** (decided 2026-06-21). A golden-output baseline (like
Task 159's) earns its keep on a *wide, shallow, subtly-formatted* surface; Task 172 is the opposite —
a *deep, narrow* change behind one hard invariant: **the trace's *meaning* — cost / `final_status` /
`failed_node_ids` — stays identical**, while the reconstructed dict's *shape* changes only in bounded ways
(`status` enum, `ancestor_path`/`port` stripped, inline blobs). You assert it directly via **`tree()` ≡
on-disk reconstruct ≡ cost/status literals** (not byte-identity to A–C; `flatten_trace_to_lines` is removed,
so the old `flatten↔reconstruct` round-trip is replaced by the live-engine→JSONL→reader equivalence test). A bespoke harness would mostly re-test the unchanged reader/analyzer and duplicate
existing trace tests (fails the deletion test). The two real failure modes — **sub-workflow cost
under-count** and **wrong `final_status`** (child `node_id` overwriting a parent) — are loud and already
largely covered by the existing suite.

### 1. The existing trace suite IS the regression oracle — green before & after
Capture the pass/fail baseline on `main` first, re-run after the change, report the delta:
- `tests/test_core/test_trace_io.py` — flatten↔reconstruct round-trip (the byte-identical-dict invariant).
- `uv run pytest -m trace_files` (164 cases) + `test_workflow_trace.py`, `test_trace_format_2_1/2_2` — trace shape.
- `test_metrics_integration.py` — cost/token totals. `test_failed_node_invariant.py`, `test_only_snapshot.py` — status + snapshot restore.

### 2. Confirm the oracle covers the two risks — patch only if gapped
Verify an existing test exercises (a) **sub-workflow LLM cost aggregation** (so the `tree()`-walking cost
readers can't silently under-count) and (b) **parent/child `node_id` collision** for status (top-level
scoping). If either is a gap, add *that one targeted test* — not a baseline.

### 3. The headline NEW test — emit↔save equivalence
Run one realistic workflow (sub-workflow **+** parallel batch, **mocked LLM** via `tests/shared/llm_mock`
— do not live-call) through the new emit-time producer and assert the **reconstructed dict + cost totals
+ `final_status`/`failed_node_ids` equal the save-time result**. A–C's oracle does not cover the new
producer; this is the load-bearing contract for the whole A-C/Phase-D split.

### 4. Producer-internals unit tests (the genuinely new mechanics)
- No-lock `seq` correctness under a **parallel-batch-of-sub-workflows** run (the routing rule; re-verify
  the invariant against current code first).
- `ancestor_path` stamping (`[{node_id, batch_index}]`, mirrors `NodeId.ancestor_path`); stripped on read.
- Incremental flush (one line per event as recorded).
- **D3 crash-tail tolerance:** truncated *final* line drops to `final_status="incomplete"` while corruption
  anywhere earlier still raises — **replacing** the A–C documenting test
  (`test_load_trace_file_skips_truncated_tail_*`) that pins today's whole-trace-skip behavior.

### 5. Intermediate checkpoint (ADR-0008 — gate before consumer treats producer as "done")
One sub-workflow **and** one parallel batch end-to-end through the unified collector, asserting correct
`parent_id`/`ancestor_path`/`seq` and correct cost/`failed_node_ids`. (Reuse Task 159's
`_shared/workflows/lyrics-generator/` tree as a realistic at-scale execution fixture — the asset, not the
harness — but with mocked LLM, not the ~181-call live run.)

### 6. Free outer net (zero new work)
After baselining it on `main` (it may need a `regenerate.sh` post-A–C), run Task 159's
`baseline/verify.sh` once — its deliberately **un-normalized cost** diff is a cheap catch for the
cost-reader risk. Don't *build* anything for it; ~66/79 cases are static `analyze-cache` and pass
trivially, so treat green as a bonus, not proof.

- `make test` + `make check` green to finish.

## References

- **ADR-0008** (`context/adr/0008-live-execution-overlay.md`) — the architecture + consequences.
- **D1 schema** (`.taskmaster/tasks/task_133/design/d1-event-schema.md`) — the contract + Producer notes.
- Task 133: `task-133.md`, `implementation/implementation-plan.md` (§3 "Deferred to Phase D", §6 Risks),
  `implementation/progress-log.md` (the 6 gotchas), `starting-context/braindump-phase-d-handoff.md`.
- Key source: `core/trace_io.py`, `runtime/workflow_trace.py`, `runtime/engine/{engine,instrumentation,
  batch_executor}.py`, `runtime/workflow_executor.py`.
- Consumers: Task 173 (live overlay), Task 164 (resume), Task 125 (HITL).
