# Live execution overlay: the trace is the streamable event source; the UI tails it, never hosts the run

We want a live UI overlay that shows a workflow executing in real time — including runs launched by
agents/CLI in their own processes — and the trace already captures everything that happens, but is
written once at the end. **Decision:** make the trace a streamable, span-shaped, append-only event log
(Task 133 Phase D) that the engine flushes incrementally as it runs; the `pflow ui` server **tails that
file** and pushes events to the browser over SSE (Task 133's event schema riding Task 169's transport),
and the browser renders them by joining onto the static graph via `NodeId = (node_id, ancestor_path)`.
The UI **observes** runs — and may *launch* one by spawning a normal `pflow run` subprocess — but
**never hosts execution in-process**. Producer (engine) and consumer (UI) are decoupled by the trace
file; the only contracts between them are the **D1 event schema** and the **NodeId join key**.

## Status

proposed

## Considered options

- **A1 — incremental trace stream + file-tail (chosen).** One event source serves the live overlay,
  the post-hoc `report`/`analyze-cache`, crash-resume, and a future OTel export. The file decouples
  producer from consumer: any run (agent/CLI/UI-launched) is watchable, crash-safe, and replayable, and
  the run never depends on the UI being up.
- **A2 — thin live "lifecycle" log + write-once trace (two substrates).** Ships a lit-up graph faster
  with no engine surgery, but it is display-grade only (no live outputs/cost), it is a second event
  stream that drifts from the trace, and it does not serve observability — you outgrow it and rebuild as
  A1. Rejected.
- **A3 — the run POSTs events to the server.** Rejected: fragile for agent/CLI runs (the server may be
  down when the run starts, no replay if you open the UI mid-run, couples the run's lifecycle to the
  server).
- **Pipe (server spawns the run, reads its fd).** Clean, but only works for runs the UI *launched* — and
  we need to watch agent/CLI-launched runs. Kept as the *launch* convenience, not the transport.
- **UI hosts execution ("owns the run").** Rejected: shifts pflow from CLI-first to client-server, the
  run dies with the server, concurrency becomes the server's problem, and it collides with HITL
  (Task 125). Launching via a spawned subprocess gives "run from the UI" without any of this.

## Consequences

- **Phase D is the invasive piece, and harder than a first pass suggests.** It requires: (a) **building a
  host-descent stack** — *none exists today* (`_pflow_stack` is file-path cycle detection; batch
  host-descent has no runtime carrier) — to assign emit-time `parent_id` + `ancestor_path` as each node
  records; (b) flipping the **in-memory** event store to a flat list whose events carry
  `id`/`seq`/`parent_id` (the natural output of one run-scoped collector — which also **eliminates the
  per-child collectors** and their child→parent embed), exposing the nested tree as a **derived
  `tree()` view** that reuses A–C's `_rebuild_event_tree`; (c) incremental flush + inline-first-occurrence
  blobs. Re-estimate from the earlier ~300 LOC floor — the host-stack and the in-memory-reader migration
  are additional but bounded scope. The **on-disk format from A–C does not change** — only *when*
  correlation is assigned.
- **The no-lock `seq` holds only under a routing rule** (not mere absence): worker threads must never
  *call* the run-scoped collector's recording/`seq` methods — the collector object is reachable from a
  worker via the shallow-copied `shared`, so the discipline is that workers route to **worker-local
  buffers** (`_batch_trace`, child events) that are folded in, with `seq` assigned, at the **main-thread
  drain**. Break it and a parallel-batch item containing a sub-workflow corrupts `seq`.
- **The in-memory event shape is its own blast radius — wider than the disk format.** Consumers that read
  the *live collector* (not the file) must be migrated: the cost/token readers (`collect_llm_calls` — the
  CLI **and** MCP summary seam — and `_collect_llm_summary`) must walk the derived **`tree()` view** or
  they under-count sub-workflow LLM cost; while `final_events_by_node` (and the status it feeds) needs
  **top-level-only scoping** — on a flat list a child's `node_id` can overwrite a parent's, silently
  mis-keying `failed_node_ids`/`final_status` (a *wrong-status* bug, higher severity than the under-count).
  The full reader set is Phase D implementation detail. *(This corrects an earlier draft claim that
  "metrics stays green via disk reconstruction" — the metrics path never touches the disk seam.)*
- **Post-hoc *disk* readers stay unchanged** (`report`, `analyze-cache`, `--only`) iff
  `reconstruct_trace_from_lines` keeps producing the same nested dict — the `load_trace_file` →
  `TraceTree.from_dict` seam is the rail. `ancestor_path` is **stripped on read** (the overlay reads the
  live stream; the reconstructed dict stays byte-identical to today).
- **Task split, bound by two contracts.** Producer = Task 133 Phase D; transport = Task 169 (a
  vocabulary-agnostic SSE bus — its own spec carries no run schema); consumer = a new live-overlay task
  (server-side tailer + frontend rendering). They meet only at the **D1 event schema** and the read-only
  **`NodeId = (node_id, ancestor_path)`** contract (ADR-0003). Task 169's SSE bus is internal to the
  consumer side (server↔browser); the producer never touches it.
- **Build skeleton-first, with an intermediate checkpoint.** A thin slice (incrementally flush top-level
  node-completion events, `ancestor_path=[]` → minimal SSE → light up one node) validates the schema and
  pipe. But it sidesteps the hard part, so add an **intermediate checkpoint** that exercises one
  sub-workflow **and** one parallel batch end-to-end through the unified collector *before* the consumer
  task treats the producer as done.
- **Verification:** a **live-engine → on-disk JSONL → existing-reader** integration test. The A–C
  round-trip oracle only proves `flatten`↔`reconstruct` self-consistency; Phase D changes the *producer*
  (save-time → emit-time), so the new emit path needs its own end-to-end coverage.
- **Per-node status is `success`/`cached`/`failed`; `degraded` is run-level.** A node that fails-then-
  recovers is honestly `failed` *at the node level*; **`degraded` is a run outcome** (`final_status`,
  already computed from `__warnings__`) — confirmed, because recovery is decided at engine step 17.5,
  *after* `record_trace` at step 16, so an emit-time per-node `degraded` isn't achievable anyway. The
  overlay shows a failed node red **and** a degraded run-banner — both true. Whether to promote today's
  `success: bool` + `cached` flag to an explicit per-node `status` enum (cleaner, but a ~15-site reader
  migration) is a **low-stakes open decision for the producer task** — it does not change this
  architecture. `running`/`pending` stay overlay-inferred (no `node.start` in v1).
- **Crash-resume (Task 164) inherits the substrate.** Incremental write + backward-only blob refs make a
  crash-truncated file self-consistent and resumable from the last completed node — impossible today (a
  hard crash leaves no file at all). Caveat: `save_to_file`'s `default=str` stringifies non-JSON-native
  outputs one-way, so restoring them is not byte-faithful — Task 164 must choose loud-caveat vs. a
  faithful snapshot store.
- **Observability is a near-free follow-on, not new work now.** The span-shaped, OTel-aligned model
  (`id`↔span_id, `parent_id`↔parent_span_id, `run_id`↔trace_id, `gen_ai.usage.*` token names; `cost_usd`
  kept as a non-standard attribute) makes a future OTel export a rename. Live monitoring must come from
  pflow's own stream — OTLP exports traces on span-end only, so it cannot feed a live view. Do **not**
  build the exporter until a second real consumer appears.
- **Leave the prompt-cache half of `engine.run` alone.** The `__pflow_prompt_cache__` save/restore is
  structurally identical to the `__trace_collector__` one but semantically opposite — it is intentionally
  per-workflow (load-bearing for cache scoping + the `CacheBlockIR` freeze guarantee). Collector
  unification changes only the trace half. (Verified: no other site couples the trace-collector
  lifecycle.)
- **Known v1 limitation:** for parallel/batch, the overlay cannot show "running" until items complete
  (no `node.start` yet) — a per-completion flipbook there, not live progress. Acceptable for v1;
  `node.start` (L2) is the deferred fix.
- **Minor:** `node_type` on events is the Python class name (`LLMNode`, `WorkflowExecutor`); the
  consumer's detail panel must not surface it raw to agents (authoring-surface rule).

## Deferred — pin against the shipped overlay, NOT in v1

`node.start`/L2 events (and with them, real-time parallel/batch "running"); promoting batch items to
first-class spans — which also requires teaching `_rebuild_event_tree`/`tree()` to re-nest `batch_items`
(today only `sub_workflow_events`), so batch-promotion and the `tree()` view are coupled — and the
parallel-batch `seq` ordering choice (completion vs index order); `llm` and `gate` as their own `kind`s;
retry-as-attempt; the OTel exporter. *(An explicit per-node `status` enum is an **optional** producer-task
cleanup, not deferred-by-design — see Consequences.)*

## References

- Builds on: ADR-0005 (local server chosen *because* live streaming needs one), ADR-0003 (NodeId
  identity / Runtime Overlay Join Contract), ADR-0007 (trace and cache stay separate).
- Tasks: 133 (producer / event schema), 169 (SSE transport), 155 + 168 (static graph + join key),
  164 (resume), 125 (HITL).
- D1 schema draft: `.taskmaster/tasks/task_133/design/d1-event-schema.md`.
