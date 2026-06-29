# D1 — Run-Event Schema

> **Status: SHIPPED + validated end-to-end (producer Task 172, PR #530; consumer-derivation Task 173).**
> The producer/disk facts below are **as-built and pinned by tests** (`tests/test_runtime/test_emit_time_trace.py`,
> `tests/test_core/test_trace_io.py`, `-m trace_files`). The *consumer-derivation* contract (how the overlay
> maps events → display state + the `sameRef` join) is now **validated by the shipped, browser-verified
> overlay** and pinned — see ADR-0008 (accepted).
>
> **The on-disk JSONL shape DID change from Task 133 A–C** (bounded, no-back-compat — there are no external
> readers): per-node `status` **enum** replaces `success: bool`+`cached`; blobs are **inline first-occurrence
> `blob` lines** (no `blobs` trailer); `ancestor_path`/`port` are emit-stamped (stripped on read); correlation
> is assigned at *emit* time and the file **streams** one line per node as the run executes. The span
> *taxonomy* (separate `llm`/`gate` events, batch-ITEM `node.start`, batch-item promotion) is deferred until the shipped
> overlay validates it.

## Why this exists

The single contract every consumer cites instead of re-inferring a shape: the **producer** (Task 133
Phase D engine), the durable JSONL writer, the post-hoc `report` / `analyze-cache`, the **live overlay**
(server tailer + frontend), crash-resume (Task 164), and a future OTel export. "One event source, many
renderers."

## Trust boundary

- **As-built (Task 172), pinned by tests:** the line structure, the `status` enum, inline `blob` lines,
  emit-time correlation, and `ancestor_path` on the wire.
- **Shipped:** `ancestor_path` as the graph-join field (stripped on read); the in-memory store is **flat
  (events carry `id`/`seq`/`parent_id`) with a derived `tree()` view**; v1 streams at **node granularity**
  (batch items inline); per-node `status` is an explicit **enum** (`success`/`cached`/`failed`) — the
  one-time `~15-site` reader migration is done.
- **Validated (Task 173):** the consumer-derivation contract (display-state mapping + the `sameRef` join) —
  pinned producer-side by `test_runtime_event_refs_join_onto_the_static_graph` and confirmed end-to-end by
  the shipped, browser-verified overlay (running/success/failed/cached; the non-empty-`ancestor_path`
  sub-workflow join; host-group lighting; loop flipbook; crash→stopped).
- **Deferred** (pin against the shipped overlay): the span taxonomy + the OTel exporter (see end).

## The model in one sentence

One JSON object per line, **streamed as the run executes**: a `meta` line, then — interleaved in emit order
— one `event` line per node execution and an inline `blob` line before the first event that references each
large payload, then a `run.complete` trailer at finalize. (No `blobs` trailer: blobs are inline and
backward-only, so a forward tailer / crash-truncated prefix stays self-consistent.)

---

## Line kinds

`pflow_trace: "jsonl/1"` marks the first (`meta`) line. The `kind` discriminator is one of:

| `kind` | Role | Notes |
|---|---|---|
| `meta` | run identity, first line | written **eagerly at run start** (`start_streaming`) so an in-flight run is discoverable from t=0 |
| `node.start` | a node BEGAN (live-only marker) | SHIPPED Task 173: a disk-only line flushed when a (main-thread) node starts, sharing the node's `id`/`seq` so the terminal `event` supersedes it (last-wins). The post-hoc reader (`_partition_trace_lines`) **drops** it, so on-disk `event` seqs stay byte-identical to a no-node.start run. Carries the same join keys as `event` (overlay reads `running` off it). |
| `event` | one node execution | the bulk; see below |
| `blob` | one interned payload | **inline**, `{kind, md5, value}`, written **before** the first event that references it (backward-only); replaces the A–C `blobs` trailer |
| `run.complete` | run aggregates | trailer; **absence = crash-tail** (the resume discriminator) |

> **meta is written EAGERLY (SHIPPED).** The producer opens the file at run start via `start_streaming()`
> (after `only_node` is stamped), NOT lazily on first completion — so a still-running first node is
> discoverable from t=0 and a crash mid-first-node still leaves a readable `meta`-only file. The newest-by-mtime
> consumers that could now meet a contentless trace (`report.py` auto-detect; analyze-cache's "found other
> traces" disclosure) were guarded to prefer a COMPLETE trace — see the Task 173 slice-hardening progress-log
> entry. (Historical: the original v1 plan wrote `meta` lazily on first node completion.)

**`meta`** (verbatim `_META_KEYS`, `trace_io.py`): `format_version`, `execution_id` (**= `run_id`**),
`workflow_name`, `workflow_path`, `start_time`, `only_node`, `content_hash`. (`only_node` rides *here*, so a
head-only reader can reject `--only` traces early.) **`content_hash`** (Task 173) is the workflow-version
fingerprint — `workflow_content_hash` of the *resolved* IR: its `canonical_ir_digest` with source-LOCATION
provenance (`_source_line`/`_source_lines`/`_source_files`) stripped, so the fingerprint tracks the LOGICAL
workflow, not its byte layout (a comment/whitespace edit that only shifts line numbers is NOT a "different
version"). The replay tailer compares it to the current file's `workflow_content_hash` to flag a stale run.
For a dict-inline run (no provenance) it equals the digest inside the `ir-hash:` `workflow_path`. `null` on a
run that didn't supply it (an old trace) → "can't verify version".

**`run.complete`** (folded at finalize, `workflow_trace.py:913-948`): always `end_time`, `duration_ms`,
`final_status` (**this is where `degraded` lives** — a *run* outcome), `nodes_executed`, `nodes_failed`,
`failed_node_ids`; conditional `llm_summary`, `warnings`, `json_output`.

---

## The `event` line

### a. Correlation — assigned at **emit** time in Phase D (OTel-aligned)

| Field | OTel | Meaning |
|---|---|---|
| `id` | `span_id` | the event's own `seq` token — **never `node_id`** (loop revisits / cross-subworkflow collisions) |
| `parent_id` | `parent_span_id` | enclosing event's `id`; `null` at top level |
| `run_id` | `trace_id` | `= meta.execution_id` |
| `seq` | — | monotonic, global, gap-free |

These four already exist on disk (A–C derives them at *save* time; Phase D assigns them at *emit* time,
which requires the **host-descent stack** the producer must build — see Producer notes). They are for
**reconstruction + ordering** and are stripped on read so disk readers see the same nested dict. Reserved
against collision by `_RESERVED_LINE_KEYS` (`trace_io.py:33`).

### b. Graph-join identity — **the new join field** (for the overlay)

The overlay joins each event onto the static graph's `RFRef` via `sameRef()`, which compares **exactly**:

| Field | Source | Notes |
|---|---|---|
| `node_id` | already present | authored node id |
| `ancestor_path` | **NEW** | ordered list of `{node_id, batch_index}` — one per real host descent (sub-workflow / batch). `batch_index` is the inline batch item's index, `null` for dynamic batches. |
| `port` | emit-stamped | the producer writes `"port": null` on **every** body event (not omitted); the graph's never-traced IO nodes carry `"in"/"out"`, but no `event` ever does → the join always uses `port = null` |

`ancestor_path` is **NOT derivable from anything that exists today** — there is no runtime host stack
(`_pflow_stack` is file-path cycle detection; batch host-descent has no runtime carrier). Phase D must
**build** a host-descent stack and stamp `ancestor_path` (and emit-time `parent_id`) as each event
records. It mirrors `NodeId.ancestor_path` (`graph/model.py`, emitted as `RFRef` in
`react_flow.py:232-238`; compared in `web/src/graph/remap.ts` `sameRef`).

> **`parent_id` ≠ `ancestor_path`.** `parent_id` links an event to its enclosing *event* (tree rebuild,
> ordering). `ancestor_path` is the structural *graph* identity (overlay join). An event carries both.
> The overlay reads `ancestor_path` off the **live stream**; it is **stripped on read** from the
> reconstructed dict (add it to `_RESERVED_LINE_KEYS`; disk readers don't need it — the nesting already
> encodes the structure). Because Phase D stamps it at emit, the **writer must own it** (like
> `id`/`seq`/`parent_id`/`run_id`), not have the flatten collision-guard reject a producer-set value.

### c. Node payload (refines A–C; verified field sets)

- **Always:** `node_id`, `node_type`, `duration_ms`, `status`, `timestamp`.
- **Per-node completion status** — `status` is an explicit **enum**: `"success" | "cached" | "failed"`
  (SHIPPED in Task 172 — `success: bool`/`cached` no longer appear on an `event`). The consumer reads
  `status` directly; no derivation. `error` (message) accompanies a `"failed"` status. **`degraded` is NOT
  a node status — it is a *run* outcome** (`run.complete.final_status`, computed from `__warnings__`): a node
  that fails-then-recovers is `"failed"` at the node level, while the *run* is degraded. (Recovery is decided
  at engine step 17.5, *after* `record_trace` at step 16 — so an emit-time per-node `degraded` isn't
  achievable regardless.)
- **Conditional:** `error` (message, on failure), `node_params`, `template_resolutions`, `node_output`,
  `mutations`, `batch_items` (inline — **v1 does not promote** them; each carries its own `status` inline
  too), `sub_workflow_events` (on disk these become child `event` lines via `parent_id`, not an inline key).
- **LLM siblings (conditional):** `llm_prompt` (str), `llm_system` (str | list[dict]), `llm_response`
  (str), `llm_call` (dict — below). Canonical post-#382: redundant prompt/system copies in
  `node_output`/`template_resolutions`/`node_params` are stripped.
- **Note:** `node_type` is the Python class name (`LLMNode`, `WorkflowExecutor`); the consumer must not
  surface it raw to agents (authoring-surface rule).

### d. `llm_call` payload (what the overlay's detail panel renders)

The retry-aggregated `llm_usage` dict. **LLMNode** carries (all always unless noted): `model`,
`input_tokens` (**cache-inclusive**), `uncached_input_tokens`, `output_tokens`, `total_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`, `has_cache_telemetry`, `input_token_accounting`,
`thinking_tokens`, `thinking_budget`, `cache_chunks_skipped`, `cache_skipped_reason`,
`prewarm_disabled_reason`; conditional `cost_usd` (`float | None`). Engine-augmented, **LLMNode-only**:
`cache_source`, `cache_key`, `cache_age_sec`.

> **ClaudeCode omits ALL the LLMNode-only fields** — not just the cache trio. Its `llm_call` is:
> `model`, `input_tokens`, `uncached_input_tokens`, `cache_creation_input_tokens`,
> `cache_read_input_tokens`, `input_token_accounting` (always `"split_cache_fields"`), `output_tokens`,
> `total_tokens`, `cost_usd`, an inner `duration_ms`, `num_turns` (agent marker), `session_id`, and
> `retries` (conditional). A consumer must treat the LLMNode-only fields as optional.

- **#492 (resolved, consistent across producers):** `input_tokens == uncached_input_tokens +
  cache_creation_input_tokens + cache_read_input_tokens`. `input_token_accounting`
  (`"total_includes_cache" | "split_cache_fields"`) names how the total was derived. (`core/llm_usage.py`)
- **OTel:** the token fields map to `gen_ai.usage.*` (a *rename*, **not yet applied** — current on-disk
  names are the pflow names above); `cost_usd` is non-standard and kept as-is.
- **`is_warmup` is NOT an llm field** — it sits on the synthetic prewarm *batch item*; never expect it on
  a normal `event`.

---

## Consumer-derivation contract (the overlay)

- **Status:** the overlay reads the `event.status` **enum** directly (`"success" | "cached" | "failed"`) —
  no derivation. `running` comes from a **`node.start` line** (SHIPPED, Task 173): a disk-only marker the
  producer flushes when a node BEGINS, sharing the node's `id`/`seq` so the terminal `event` supersedes it
  (last-wins); the post-hoc reader (`_partition_trace_lines`) drops it, leaving on-disk `event` seqs
  byte-identical. `pending` = no line yet for that node. **`degraded` is a run banner**, read from
  `run.complete.final_status`, not per-node.
- **Join:** match `event` → graph node by `(node_id, ancestor_path)`, `port = null`, via `sameRef`. **Read
  these off the RAW stream — NOT through `load_trace_file`/`reconstruct`, which STRIPS `ancestor_path`/`port`
  (`_RESERVED_LINE_KEYS`).** A re-flushed correction (routing dead-end) repeats an `id` → key on `id`,
  last-wins. See the consumer-handoff braindump in `task_173/starting-context/` for the full tailer trap list.
- **Liveness level:** L1.5 — per-completion `event` + emit-at-start `node.start` for every **main-thread**
  node (leaf nodes via `begin_node` at engine step 8.5; sub-workflow and batch-of-LEAF hosts via
  `descend`, sharing the host frame's seq). **Known v1 limitation:** a parallel/sequential
  batch-OF-SUB-WORKFLOWS host and the individual batch ITEMS get NO `node.start` — they run off the owner
  thread, and the no-lock rule forbids emitting to the run-scoped collector there → they show
  pending-until-done; batch-item granularity stays deferred. Rich detail (resolved IO, cost, tokens) comes
  from the event payload (`node_output`, `llm_call`).

---

## Producer notes (Task 172 — AS-BUILT; the constraints that make this work)

- **In-memory store is flat (events carry `id`/`seq`/`parent_id`); nested is a derived view.** One
  run-scoped collector produces the flat list and **eliminates the per-child collectors** (and their
  child→parent embed). The nested tree is exposed via a single **`tree()` accessor** reusing A–C's
  `_rebuild_event_tree`. In-memory readers split: the **cost readers** (`collect_llm_calls` — CLI + MCP —
  and `_collect_llm_summary`) walk `tree()` recursively (else they under-count sub-workflow cost);
  **`final_events_by_node`** (and the status/`failed_node_ids` it feeds) uses **top-level-only scoping**
  (`parent_id is None`) — on a flat list a child's `node_id` can overwrite a parent's → wrong `final_status`.
- **Streaming + inline blobs + two-pass reconstruct (all shipped).** The collector **streams** one line per
  node during the run (`_flush_event`), gated by `RunnerConfig.trace_enabled` (CLI=on / MCP=off / `--no-trace`=off).
  Large leaves intern to **inline `blob` lines** written before their first reference (backward-only). The
  reader's `_rebuild_event_tree` is **two-pass**: dedup-by-`id` last-wins (a routing-dead-end re-flush wins) +
  lenient **transitive** orphan-drop when there's no `run.complete` (crash mid-sub-workflow recovers the
  well-formed prefix). `load_trace_file` tolerates a **single truncated final line** → `incomplete`. The
  streamed file is a **best-effort tail**: an I/O fault disables streaming, never alters the run.
- **No-lock `seq` is a routing rule:** worker threads never *call* the run-scoped collector's recording/`seq`
  methods (it's reachable from a worker via the shallow-copied `shared`). They route to worker-local buffers
  (`_batch_trace`, child events) folded in, with `seq` assigned, at the **main-thread drain** — enforced by the
  `__index__`/`is_run_scoped` gate + a main-thread assert. Break it and a parallel-batch-of-sub-workflows run
  races `seq` AND corrupts the shared file handle.
- **Host-descent stack:** the run-scoped collector's `descend`/`ascend` (reserve-`seq`-at-descent = DFS
  pre-order); supplies emit-time `parent_id` + `ancestor_path`.
- **MCP does NOT stream** (`trace_enabled=False`): only CLI / spawned `pflow run` / library-callers-with-`finalize_trace`
  produce a watchable trace. An agent run via the MCP server tool is **not** watchable; an agent run via the CLI is.
- **Verification (the as-built pins):** `test_emit_time_trace.py` (equivalence + the wire/join contracts:
  `test_runtime_event_refs_join_onto_the_static_graph`, `test_streamed_wire_*`), `test_trace_io.py` (reader),
  `-m trace_files` (the format oracle). Task 172 `task-review.md` is the producer's forward-reference.

---

## Deferred — pin against the shipped overlay, NOT in v1

- **`node.start` for batch ITEMS + the batch-of-sub-workflow HOST (L2):** the emit-at-start marker
  SHIPPED for every main-thread node (Task 173 — see the Consumer-derivation section), so flat nodes plus
  sub-workflow and batch-of-leaf hosts light `running` live. Still deferred: per-ITEM "running" inside a
  parallel/sequential batch, and the batch-OF-sub-workflow host — both execute off the owner thread (the
  no-lock rule forbids emitting there), so they stay pending-until-done. Couples to batch-item promotion
  below.
- **`llm` as its own child-span `kind`** (today nested as `llm_call`); **batch-item promotion** to
  first-class events (today inline) — which also requires teaching `_rebuild_event_tree`/`tree()` to
  re-nest `batch_items` (today only `sub_workflow_events`), so batch-promotion and the `tree()` view are
  coupled — and the **parallel-batch `seq` ordering** choice (completion vs index order).
- **`gate`/escalation `kind`** for Task 125 HITL (a non-result event — schema must allow it).
- **OTel exporter:** align field names so export is a rename; build only when a second real consumer
  appears.

*(The per-node `status` enum — formerly an open producer-task decision — is now SHIPPED, see §c.)*

## References

- **ADR-0008** (the architecture this schema serves); ADR-0003 (NodeId / Runtime Overlay Join Contract);
  ADR-0007 (trace/cache separation).
- **Task 172** (the producer that shipped this): `task_172/task-review.md` (forward-reference),
  `task_172/implementation/progress-log.md` (the journey); **consumer-handoff braindump:**
  `task_173/starting-context/braindump-producer-handoff-2026-06-23.md` (the tailer trap list).
- As-built format: `core/trace_io.py` (`_META_KEYS`, `_RESERVED_LINE_KEYS`, `substitute_refs`,
  `intern_event_leaves`, `reconstruct_trace_from_lines`/`_rebuild_event_tree`, `load_trace_file`).
- Verified field sets (this session): `runtime/workflow_trace.py`, `nodes/llm/llm.py`,
  `nodes/claude/claude_code.py`, `core/llm_client.py`, `core/llm_usage.py`,
  `runtime/engine/instrumentation.py`, `core/workflow/graph/model.py`,
  `core/workflow/graph/renderers/react_flow.py`, `web/src/graph/remap.ts`.
- Consumers: Task 133 Phase D (producer), Task 169 (transport), the live-overlay task (consumer),
  Task 164 (resume), Task 125 (HITL).
