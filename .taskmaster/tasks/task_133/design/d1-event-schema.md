# D1 — Run-Event Schema (DRAFT)

> **Status: DRAFT.** Validated *skeleton-first* against the live overlay (the real consumer) before
> pinning — see ADR-0008. **The on-disk JSONL format from Task 133 A–C does NOT change here.** D1 is the
> same line shape, with correlation assigned at *emit* time (Phase D) and **one new join field**
> (`ancestor_path`). The span *taxonomy* (separate `llm`/`gate` events, `node.start`, batch-item
> promotion) is deferred until the shipped overlay validates it.

## Why this exists

The single contract every consumer cites instead of re-inferring a shape: the **producer** (Task 133
Phase D engine), the durable JSONL writer, the post-hoc `report` / `analyze-cache`, the **live overlay**
(server tailer + frontend), crash-resume (Task 164), and a future OTel export. "One event source, many
renderers."

## Trust boundary

- **Verified against current code** (this session's probes; file:line in each): the A–C line structure
  and every payload field below.
- **Decided now:** `ancestor_path` as the graph-join field (stripped on read); the in-memory store goes
  **flat (events carry `id`/`seq`/`parent_id`) with a derived `tree()` view**; v1 streams at **node
  granularity** (batch items inline).
- **Open (low-stakes, producer task):** whether to promote `success: bool`+`cached` to an explicit
  per-node `status` enum (see §c).
- **Deferred** (pin against the shipped overlay): the span taxonomy + the OTel exporter (see end).

## The model in one sentence

One JSON object per line: a `meta` line, then one `event` line per node execution (emit order), then
`run.complete` and `blobs` trailer lines. (A–C already writes exactly this; D1 changes *when* correlation
is assigned and *adds the join field*.)

---

## Line kinds

`pflow_trace: "jsonl/1"` marks the first (`meta`) line. The `kind` discriminator is one of:

| `kind` | Role | Notes |
|---|---|---|
| `meta` | run identity, known at start | first line |
| `event` | one node execution | the bulk; see below |
| `run.complete` | run aggregates | trailer; **absence = crash-tail** (the resume discriminator) |
| `blobs` | interned blob map | trailer; `{md5: str}` |

**`meta`** (verbatim `_META_KEYS`, `trace_io.py:28`): `format_version`, `execution_id` (**= `run_id`**),
`workflow_name`, `workflow_path`, `start_time`, `only_node`. (`only_node` rides *here*, not the trailer,
so a head-only reader can reject `--only` traces early.)

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
| `port` | implicit | **always `null`** for any traced (body) node → omittable; only never-traced IO nodes carry `"in"/"out"` |

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

- **Always:** `node_id`, `node_type`, `duration_ms`, `success` (bool), `timestamp`.
- **Per-node completion status** — the node's own outcome is one of **`success` / `cached` / `failed`**,
  encoded today as `success: bool` + the `cached` flag (written *only when true*; absence = not cached) +
  `error` (message on failure). The overlay derives the three display states from these. **`degraded` is
  NOT a node status — it is a *run* outcome** (`run.complete.final_status`, computed from `__warnings__`):
  a node that fails-then-recovers is `failed` at the node level, while the *run* is degraded. (Confirmed:
  recovery is decided at engine step 17.5, *after* `record_trace` at step 16 — so an emit-time per-node
  `degraded` isn't achievable regardless.)
  - **Open decision (producer task):** optionally promote `success`+`cached` to an explicit `status` enum
    (`success`/`cached`/`failed`) — one producer-set field vs. derivation repeated across readers
    (cleaner), but a ~15-site reader migration (`trace_tree` cached-skip, ~10 `trace_report` sites,
    `_unrecovered_failed_node_ids`, `mark_last_event_failed`, batch items) + an old-trace map on read.
    Low-stakes; does not change this contract.
- **Conditional:** `error` (message, on failure), `node_params`, `template_resolutions`, `node_output`,
  `mutations`, `batch_items` (inline — **v1 does not promote** them; their own `success`/`cached` ride
  inline too), `sub_workflow_events` (on disk these become child `event` lines via `parent_id`, not an
  inline key).
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

- **Status:** the overlay maps a completed node to a display state — `failed` (`success=false`), else
  `cached` (the `cached` flag), else `success`. **`degraded` is a run banner**, read from
  `run.complete.final_status`, not per-node. `running` / `pending` are **inferred** from the static graph
  (an `event` exists only on completion; there is no `node.start` in v1).
- **Join:** match `event` → graph node by `(node_id, ancestor_path)`, `port = null`.
- **Liveness level:** L1 (per-completion) + the static graph. **Known v1 limitation:** for parallel/batch,
  the overlay can't show *which* of N is running until items complete — a per-completion flipbook there
  (the `node.start`/L2 fix is deferred). Rich detail (resolved IO, cost, tokens) comes from the event
  payload (`node_output`, `llm_call`).

---

## Producer notes (Phase D — the constraints that make this work)

- **In-memory store goes flat (events carry `id`/`seq`/`parent_id`); nested is a derived view.** One
  run-scoped collector naturally produces the flat list — and **eliminates the per-child collectors** (and
  their child→parent embed). The nested tree is exposed via a single **`tree()` accessor** reusing A–C's
  `_rebuild_event_tree` (which *requires* `id`/`seq`/`parent_id` on each event). In-memory readers split:
  the **cost readers** (`collect_llm_calls` — CLI + MCP — and `_collect_llm_summary`) walk `tree()`
  recursively (else they under-count sub-workflow cost); **`final_events_by_node`** (and the
  status/`failed_node_ids` it feeds) must use **top-level-only scoping** (`tree()` roots / `parent_id is
  None`) — on a flat list a child's `node_id` can overwrite a parent's → wrong `final_status`. The full
  reader set is Phase D implementation detail.
- **No-lock `seq` is a routing rule:** worker threads must never *call* the run-scoped collector's
  recording/`seq` methods (the collector is reachable from a worker via the shallow-copied `shared`). They
  route to worker-local buffers (`_batch_trace`, child events) folded in, with `seq` assigned, at the
  **main-thread drain**. Break it and a parallel-batch-of-sub-workflows run races `seq`.
- **Host-descent stack:** built by the collector unification; supplies emit-time `parent_id` +
  `ancestor_path`. Lives on the run-scoped collector, not the per-child engine.
- **Verification:** a live-engine → on-disk JSONL → existing-reader integration test (the round-trip
  oracle only covers `flatten`↔`reconstruct`, not the new emit path) + the intermediate
  sub-workflow-and-parallel-batch checkpoint.

---

## Deferred — pin against the shipped overlay, NOT in v1

- **`node.start` (L2):** light a node the instant it begins; the fix for real-time parallel/batch
  "running". New emit points.
- **`llm` as its own child-span `kind`** (today nested as `llm_call`); **batch-item promotion** to
  first-class events (today inline) — which also requires teaching `_rebuild_event_tree`/`tree()` to
  re-nest `batch_items` (today only `sub_workflow_events`), so batch-promotion and the `tree()` view are
  coupled — and the **parallel-batch `seq` ordering** choice (completion vs index order).
- **`gate`/escalation `kind`** for Task 125 HITL (a non-result event — schema must allow it).
- **OTel exporter:** align field names so export is a rename; build only when a second real consumer
  appears.

*(An explicit per-node `status` enum is an **optional** producer-task cleanup, not deferred-by-design —
see §c.)*

## References

- **ADR-0008** (the architecture this schema serves); ADR-0003 (NodeId / Runtime Overlay Join Contract);
  ADR-0007 (trace/cache separation).
- A–C format: `core/trace_io.py` (`_META_KEYS`, `_RESERVED_LINE_KEYS`, `flatten_trace_to_lines`,
  `reconstruct_trace_from_lines`/`_rebuild_event_tree`).
- Verified field sets (this session): `runtime/workflow_trace.py`, `nodes/llm/llm.py`,
  `nodes/claude/claude_code.py`, `core/llm_client.py`, `core/llm_usage.py`,
  `runtime/engine/instrumentation.py`, `core/workflow/graph/model.py`,
  `core/workflow/graph/renderers/react_flow.py`, `web/src/graph/remap.ts`.
- Consumers: Task 133 Phase D (producer), Task 169 (transport), the live-overlay task (consumer),
  Task 164 (resume), Task 125 (HITL).
