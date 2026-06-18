# Task 133 — Implementation Handoff: Streamable Span-Model Trace Event Log

> **Audience:** the agent implementing the remaining (deferred) half of Task 133.
> **Directive from the task owner:** do the **full** work — pin the D1/D2/D3 event-model contract,
> run the spikes, build the streamable span-shaped append-only event log, migrate the readers, and
> fold in #370 and #366. **Do NOT defer or minimize to unblock other tasks.** This is the
> foundation those tasks stand on; build it properly.
>
> **Provenance / trust boundary:** All "current state" claims below are **VERIFIED against `main`
> on 2026-06-18** via four parallel code searches (file:line cited). The design (D1/D2/D3) is from
> `task-133.md` + `starting-context/braindump-storage-architecture-session.md`, refined by those
> searches. Where the 2026-06-07 braindump and the current code diverge (because #382 merged after
> it), the **current code wins** and the divergence is flagged. Sizes/figures are illustrative
> unless re-measured.

---

## 0. TL;DR — what you are building and why now

pflow's trace is today an **accumulate-in-memory, dump-once-at-end nested JSON file**. You are
replacing it with a **streamable, span-shaped, append-only JSONL event log**: one typed event per
line, nesting by `parent_id` reference (not structural embedding), blobs inline at first occurrence,
a `run.complete` trailer, and a global monotonic `seq`. This single event stream becomes the **one
contract point** that the live UI overlay, Task 164 (resume), Task 125 (HITL), and Task 171
(durable tokens) all cite — instead of five consumers each re-inferring a shape.

**Why this is unblocked *now* (all gates lifted):**
- **Task 155** (static GraphModel) — ✅ done 2026-06-06.
- **Task 168** (initial React Flow UI) — ✅ merged (`#496`). Per Task 133's own roadmap, the
  sequence is *initial UI → this task (the event stream) → live overlay*. Task 168 merging is the
  trigger.
- **#492** (`input_tokens` semantics) — ✅ merged (prereq for a consistent `llm` event).
- **#382** (honest event model + per-run interning, the "now" stream of 133) — ✅ merged. The
  observed 100MB disk pain is already solved; what remains is *purely* the liveness/contract
  foundation.

**The single load-bearing bet** (from the braindump): *the event model must be streamable
(span-shaped) from the start.* Everything else is incremental and reversible. You are paying that
one expensive-to-retrofit decision now, because the live overlay + resume + HITL are the real
consumers that make the "one event source, many renderers" seam *earned*, not speculative.

---

## 1. The decision is already made — do NOT relitigate

Task 133 began as *"merge trace + cache into one content-addressed per-node store."* **That was
rejected.** Do not rebuild the merge. The reasoning (verified):

- The user's pain was a 100MB+ trace; the trace↔cache overlap is only **~3MB**. Merging removes the
  *smallest* cost center. The 100MB was **within-trace** duplication (53MB → ~12MB after stripping
  duplicated text), solved by #382's per-run interning.
- Trace and cache have genuinely different shapes and lifecycles and **stay separate**:

| | Trace | Cache (memoization) |
|---|---|---|
| Access | sequential, run-scoped read | random keyed lookup `hash(config+inputs)` |
| Lifecycle | accumulates for debugging; delete freely | current-state; TTL-evicted (24h) |
| Substrate | per-run JSON in `~/.pflow/debug/` | one SQLite DB `~/.pflow/cache/cache.db` (zlib BLOBs) |

The only thing they legitimately share is **content** (the node-output blob), and we deliberately
**accept** the ~3MB cross-system duplication in exchange for fully decoupled lifecycles and zero
cross-subsystem GC. **The cache keeps its own compressed copy.** See §7.

---

## 2. Scope

### In scope
- The **D1 event schema** — defined in **one place** all consumers cite. **Subsumes #370** (typed
  trace contract for llm_call payloads). **Folds in #366** (per-event `workflow_path`).
- The **write side**: a span-context writer that emits `run.start` / `node.start` / `node`(complete)
  / `llm` / `blob` / `run.complete` events with `id` / `parent_id` / `run_id` / `seq`.
- The **D2 `run.complete` trailer** (run aggregates; the resume discriminator).
- **D3 blob ordering**: inline at **first occurrence** in stream order (flip from today's trailer),
  global `seq` via a single append lock.
- The **read side**: a JSONL loader that reconstructs the tree, plus a **live-tailing** reader for
  the overlay.
- **Migrating every reader** (full map in §5 / Spike #1) and the **test suite + committed fixtures**.

### Out of scope (gated / separate tasks that CITE this contract)
- **Global content-addressed blob store + GC** — far-future, gated on *observed* cross-run dedup.
  Per-run scope wins on simplicity/portability/reversibility until then.
- **Building the actual features**: resume (Task 164), HITL gates (Task 125), durable tokens
  (Task 171), the live UI overlay rendering. You define the *event vocabulary* they consume; you do
  not build them. Design the schema to satisfy their needs (§6).
- **An OTel exporter** — align field *names* so a future export is a rename; do **not** build the
  exporter (build it only when a second real consumer appears).
- **The Task 169 transport** — Task 169 (agent↔browser SSE channel) is the *transport* and
  explicitly "defines no run-event schema (Task 133 boundary)." The event vocabulary is **yours**;
  the wire/SSE plumbing is Task 169's. They meet at the schema.
- **#382 / #357** — #382 already shipped; #357 (cache-key drift) is a separate bug now in its own
  worktree (`fix/fix-cache-key-drift`). Do not entangle.

---

## 3. Verified current state (post-#382) — the foundation you're changing

### 3.1 Write side
- `WorkflowTraceCollector` — `src/pflow/runtime/workflow_trace.py:427`. Accumulates events in a
  plain in-memory list `self.events` (`:497`); per-node LLM content in side-dicts `self.llm_prompts`
  / `self.llm_systems` (`:498-502`). No ring buffer, no intermediate flush.
- `TRACE_FORMAT_VERSION = "2.5.0"` (`workflow_trace.py:28`).
- **Emit funnel:** all four engine paths reach `instrumentation.py:record_trace()` (`:520`) →
  `collector.record_node_execution()` (`workflow_trace.py:514`): normal success (engine step 16),
  **cached** (`handle_cached_execution`, `instrumentation.py:667`), **api_warning**
  (`handle_api_warning`, `:747`, records at `:785` before archiving to `__failures__`), and the
  **exception** path (`record_trace(error=e)` then re-raise).
- **Timestamps are RECORD time, not start time:** `event["timestamp"] = datetime.now().isoformat()`
  stamped inside `record_node_execution` (`workflow_trace.py:551`). `duration_ms` is accurate
  (`(perf_counter() - start_time) * 1000`, `instrumentation.py:547`).

### 3.2 Sub-workflow trace handling (a write-side choke point)
- Each sub-workflow gets its **own** `WorkflowTraceCollector` if the parent has one
  (`workflow_executor.py:352-364`); a fresh `WorkflowEngine(trace_collector=child_trace, ...)` runs
  the child (`:389`). The engine save/restores `shared["__trace_collector__"]` around the child run.
- Child events are stitched into the parent by **structural embedding**:
  `self._child_trace_events = child_trace.events` (`workflow_executor.py:394-396`) →
  `record_node_execution(..., sub_workflow_events=child_trace_events)` →
  `event["sub_workflow_events"] = ...` (`workflow_trace.py:568`). Exception path captures partial
  child events (`:404-405`).
- **D1 implication:** this per-sub-workflow collector pattern is what must unify into
  span-context correlation (`parent_id` chaining across the workflow boundary).

### 3.3 File write path
- `WorkflowTraceCollector.save_to_file()` (`workflow_trace.py:873`), single call site
  `cli/commands/run.py:_save_trace_file()` (`:137-151`), idempotent — **written exactly once at
  end**. `json.dump(intern_blobs(trace_data), f, indent=2, default=str)` (~`workflow_trace.py:952`).
  Pretty-printed, **uncompressed**.
- Filename: `workflow-trace-{wf_hash}-{safe_name}-{timestamp-µs}.json` in `~/.pflow/debug/`
  (`wf_hash` = 8-char md5 of workflow_path; `:31-63, 895-896`).
- **`default=str` is a fidelity hazard:** non-JSON-native values resurrect as `str()`. This is a
  **schema-gate decision** for resume (§6, Task 164) — caveat loudly or use a faithful store.

### 3.4 Content interning — what #382 changed (the most important current-state fact)
- `src/pflow/core/trace_io.py`: `intern_blobs()` (`:19`), `resolve_blobs()` (`:67`),
  `INTERN_MIN_BYTES = 1024` (`:15`).
- Strings ≥1KB are replaced by `{"$pflow_blob": "<md5>"}`; bodies go in a `blobs: {md5: str}` map.
  `blobs.setdefault(digest, value)` (`:55`) dedups identical content.
- **Blobs are a TRAILER** — `interned.pop("blobs", None); interned["blobs"] = blobs` makes it the
  **last** key (`:62-63`). **D3 requires flipping this to inline-first-occurrence** (see §4).
- **str-only** (`:49`); `__`-prefixed subtrees are deep-copied via `copy_without_interning` (`:40`)
  — they appear in output but their string leaves are **not** interned (so a large `__metrics__`
  string would not intern).
- **Single read seam:** `load_trace_file()` (`trace_io.py:108`) parses then calls `resolve_blobs()`
  (no-op when `blobs` absent → backward compatible). **THE hook for you:** an explicit TODO at
  `trace_io.py:100-101` — *"Future jsonl reader: build the blob map from inline declarations instead
  of trace['blobs'], then reuse this substitution walk."* The substitution walk already exists and
  works; you build the blob map differently and reuse it.
- **#382 also added canonical `llm_prompt`/`llm_system`** and **strips** redundant
  prompt/system copies from `node_output`/`template_resolutions`/`node_params.prompt` for llm node
  types (`_strip_redundant_llm_trace_fields`, `workflow_trace.py:165`, gated `:572-573`). This was
  **not** purely additive — keep that in mind for the format-version bump.

### 3.5 Event-shape gaps (still old — what you must add)
| Gap | Current state | file:line |
|---|---|---|
| Per-event unique `id` | **None.** Only `node_id` (the author step name) | — |
| `parent_id` | **None.** Nesting is structural embedding | `sub_workflow_events` `:568`, `batch_items` `:566` |
| Streaming | **None.** Written once at end | `save_to_file` `:873` |
| `node.start` signal | **None** in trace (only in the progress channel) | see §6 |
| Batch-item events | keyed by `index` (warmup `index=-1`), **no timestamp**, no `node_id` | `batch_executor._capture_item_trace` |
| Loop dedup | `final_events_by_node` last-wins by `node_id` (order-dependent w/o `id`) | `workflow_trace.py:346` |

---

## 4. Target design (D1/D2/D3) — refined by the verified findings

### D1 — span granularity / event taxonomy (the real spec work)
- **One typed event per JSONL line.** Identity/correlation fields: `id` (↔ OTel `span_id`),
  `parent_id` (↔ `parent_span_id`), `run_id` (↔ `trace_id`), `seq` (monotonic, global).
- **`kind`** discriminated union: `run.start` / `node.start` / `node` (complete) / `llm` / `blob` /
  `run.complete` / a **HITL/gate** kind for Task 125.
- **Recommendation:** per-execution span; **batch items → child spans** (promote from today's
  degenerate index-keyed, timestamp-less shape to first-class events with `id`/`parent_id`/timestamp);
  **LLM calls → child spans**; **nested sub-workflows → `parent_id` chaining across the boundary**
  (replaces structural embedding); **retries** — be precise: graph-loop re-execution → new span
  (≈free, events are per-visit today); internal `max_retries` retries are **untraced today** →
  modeling them as sub-span "attempts" is **NEW emit points**, not free. Decide explicitly.
- **Two choke points** (not one): **read** = `TraceTree.from_dict` (today reads already-nested
  structure; flat-log reassembly is the change). **write** = the per-sub-workflow collector
  (`workflow_executor.py:352-396`) must unify into span-context correlation — a collector +
  `WorkflowExecutor` change, not just a format change.

### D2 — run aggregates are a trailer, not a header
- `final_status`, `llm_summary`, `nodes_executed`, `failed_node_ids` are unknown at stream start.
  A **`run.complete` trailer** carries them; readers compute partial aggregates from events when the
  trailer is absent (crash).
- **This is Task 164's failure discriminator for free:** trailer present + `failed` = graceful,
  **resumable**; trailer absent = hard crash, **not** resumable.

### D3 — interning + liveness ordering + global seq
- Emit blob content at **first occurrence, in stream order** (flip from the current trailer at
  `trace_io.py:62-63`). Makes refs **backward-only** → a forward live tailer never hits an undefined
  ref, **and** any crash-truncated log is self-consistent (post-crash reader == live tailer). This
  also gives **#255 / partial-trace resume** self-consistency for free.
- Liveness forces one tailable stream → serialized appends → a **single lock around (assign seq,
  append, flush)** yields a global monotonic `seq` for free. Per-writer buffers fragment the stream
  and are **out**. Single-process / multi-thread only (batch parallelism is `ThreadPoolExecutor`,
  not subprocesses), so a lock suffices — promote to a queue + writer-thread **only if contention is
  observed** (Spike #3). The writer must **flush frequently** or a crash loses the tail.

### The one contract point
Write the schema **once**, in one module all consumers import/cite. OTel-aligned names so a future
export is a rename (not an exporter). `gen_ai.usage.*` token names + `cost_usd` on `llm` events.
**Consumers are renderers of this one stream:** durable JSONL writer, stderr progress display, live
overlay, (future) OTel export. This subsumes **#370** and folds in **#366**.

---

## 5. The spikes — RUN THESE *BEFORE* PINNING THE SCHEMA

The build **starts with the spikes, not the schema.** Record results in this `research/` folder.

### Spike #1 — Migration blast radius (HIGH) — **already mapped below**
Changing the on-disk format from nested-JSON-once to flat JSONL touches every reader. The full
per-consumer map (verified file:line):

| Consumer | file:line | Coupling | Effort |
|---|---|---|---|
| `TraceTree` / `from_dict` | `core/trace_tree.py:89-102` + walk methods | **Max** — entire API navigates embedded `batch_items`/`events`/`sub_workflow_events` | **High** |
| `trace_io` load/intern/resolve | `core/trace_io.py:19-113` | **Max** — single-JSON-object + `blobs` trailer | **High** |
| `save_to_file` (write side) | `workflow_trace.py:873-954` | builds nested list, one `json.dump` | **High** |
| `_iter_workflow_traces` (candidate iterator) | `workflow_trace.py:83-122` | filename glob (survives) + 3 top-level key gates + `.json` ext | **Med** |
| `--only` snapshot restore (`load_full_run_events` / `seed_snapshot_into_shared`) | `workflow_trace.py:~179-253, 383-424` | reads `data["nodes"]`, iterates flat top-level events for `node_output` | **High** |
| `trace_report.generate_report` / `_write_node_files` | `core/trace_report.py:620-698` | report dir tree mirrors the nested event tree | **High** |
| `final_events_by_node` / `_collect_errors` | `workflow_trace.py:346-372` | flat top-level iteration (algorithm survives; input source changes) | **Low** |
| `prompt_cache_analysis` (`trace_loading`, `TraceTree.from_dict` calls) | `core/prompt_cache_analysis/trace_loading.py:148-168, 450, 696-790` | hard `startswith("2.")` gate + drives output from `tree.walk()` | **High** |
| `pflow report` / `analyze-cache` CLI | `cli/commands/report.py:34-76`, `cli/commands/analyze_cache.py` | `glob("*.json")` + delegate | **Low** (glue) |
| `metrics.py` | `core/metrics.py` | indirect via `TraceTree` (survives if in-memory stays plain dicts) | **Low** |
| Test infra: `TraceFixtureBuilder`, 4 committed `tests/fixtures/cache_analysis/*.json`, `test_workflow_trace.py` (~2060 ln), `test_trace_report.py` (~3101 ln), `test_trace_tree.py`, `test_only_snapshot.py`, `test_trace_format_2_1/2_2.py` | various | encode the nested shape as **format-contract pins** | **High** |

**Long poles:** (1) `TraceTree` — every consumer funnels through it; rebuild it to reconstruct a tree
from `parent_id`-referenced JSONL first. (2) the test suite + committed fixtures + `TraceFixtureBuilder`.

**KEY STRATEGIC FINDING — the minimal-blast path (recommended):**
> Keep the **in-memory** representation unchanged (`WorkflowTraceCollector.events` stays a Python
> dict tree). Change **only the I/O boundary**: `save_to_file` emits JSONL; `load_trace_file`
> reconstructs the nested tree from JSONL (blobs inline first-occurrence, reusing the existing
> `resolve_blobs` substitution walk per the `trace_io.py:100` TODO); `TraceTree.from_dict` accepts
> either shape. This isolates the blast to `trace_io.py` + `save_to_file` and leaves the other ~22
> consumers **unchanged** — at the cost of materializing the full tree in memory on load (same as
> today).

**The tension to resolve in the spike:** the minimal-blast path gives JSONL-on-disk + tree-in-memory,
but a *live* overlay needs a true **streaming** reader (no full materialization). Resolve by
**layering**: ship JSONL-on-disk + tree-in-memory first (minimal blast, satisfies all post-hoc
consumers + resume), then add the **live-tailing reader additively** for the overlay (reads events
as they append; never needs the whole tree). Don't block the migration on the streaming reader.

### Spike #2 — Unify-vs-parallel emission + concurrency (HIGH)
Two live channels exist and buffer differently under parallel batch:
- **Progress callback** — display signals only (`output_controller.py:362`,
  `shared["__progress_callback__"]`). Payload: `node_id, event, duration_ms, depth, error_message,
  is_error, batch_*` — **no resolved params, no node_output, no cost**. Fires `node_start` (before
  exec, `instrumentation.py:601`) and `node_complete` (after, `:610`), plus `node_cached`/
  `node_warning`/`batch_progress`. Parallel batch: **per-thread `buffered_events` list drained
  transcript-atomically** by the main thread as futures complete (`batch_executor.py:759-765`).
- **Trace collector** — full data, **completion only** (`record_trace`, `instrumentation.py:520`).
  Parallel batch: **`shared["_batch_trace"][node_id]` list, GIL-protected appends, drained once**
  after all futures (`batch_executor.py:247-249`).

**The models differ fundamentally**: progress drains *per-item as it finishes*; trace drains *after
all items*. **Recommendation (confirm, don't pre-decide):** *share the event schema, keep two
emission points* (the fallback 133 explicitly names). The `node.start` the overlay needs lives only
in the progress channel; the `node_output`/resolved-io the overlay needs lives only in the trace
channel. A unified span writer would emit `node.start` (before) + `node.complete` (after) under the
**same `id`** — that *is* the span model. The spike measures whether to fully unify the two writers
or keep the progress callback as a display-only sidecar over the unified stream.

### Spike #3 — Per-node append+flush performance (MED-HIGH)
D3's single-lock-around-(seq, append, flush) under batch `ThreadPoolExecutor` is **unmeasured**.
Measure throughput/contention on a real parallel-batch workflow. Fallback: queue + dedicated
writer-thread **only if** contention is observed.

### Spike #4 — Overlay/HITL actual data needs (MED)
Is the progress payload sufficient, or does the overlay need resolved inputs/outputs (which live in
the trace, not the callback)? Verified: the callback carries **only display signals** — so the
overlay almost certainly needs the trace channel's data. Resolves concretely as the UI work begins.

### Spike #5 — OTel export round-trips as a rename (LOW)
Never prototyped. Align field names only; don't build the exporter. The "export is cheap later"
claim is unproven — confirm field-name alignment is sufficient, no more.

---

## 6. Downstream consumer requirements (design the schema to satisfy these)

### Task 164 — Resume From a Failed Node
- Keys on **`node_id`** (author name), not span id. Restores upstream outputs via
  `seed_snapshot_into_shared` (`workflow_trace.py:347/383`) reading `event["node_output"]`.
- **Reuses `seed_snapshot_into_shared` unchanged.** The new work is a *resume-scoped loader that
  ACCEPTS a `failed` trace* — today `load_full_run_events` (~`:179-183`) rejects failed via an
  allowlist. The **D2 `run.complete` trailer** is the resumable-vs-crashed discriminator.
- Needs **execution order preserved** → monotonic `seq`. The `only_node` field must survive (so
  `--only` runs are excluded as resume sources).
- **Serialization fidelity is a schema gate:** `default=str` loses type fidelity; resume needs
  faithful `node_output`. Decide: loud caveat vs faithful snapshot store.
- **#255** (folding into 164): reconstruct the store even from a **partially-written** trace — D3's
  backward-only refs make any prefix self-consistent (good — design for it).

### Task 125 — Approval Gates / HITL
- A new **gate/escalation `kind`**, distinct from `node`/`llm`/`run.*`.
- A **structured decision payload** (NOT a printed string): gate type (`action_approval` vs
  `decision_escalation`), the gated `node_id`, resolved inputs (action) or options/tradeoffs/
  recommendation (escalation). "Structured data, not a printed string" is what makes Task 171's
  durable token a thin layer over the same payload.
- The gate event fires **before** the gated node's `node` event → it has **no `node_output`**. The
  schema must allow non-result events.
- Dry-run parity: `approval:` exposed via `NodeConfig` (compile-time), not a runtime event.

### Task 171 — Durable Resume Tokens & Non-TTY Gates
- The checkpoint is a **purpose-built state file, NOT the debug trace** (faithful serialization).
  Persists: shared-store snapshot (completed outputs), pause `node_id`, workflow identity + def hash
  (stale-resume detection), original input params, protocol version, and the Task 125 structured
  decision payload.
- **One restore reader, two sources:** restore reuses 164's `seed_snapshot_into_shared`-shaped
  semantics reading *either* a failed-run trace *or* the resume-state file → both must share a common
  `node_output` envelope shape.

### Task 169 / live overlay
- Needs: a **`node.start`** signal (absent in trace today), a **stable per-event `id`**, **resolved
  inputs/outputs** (in trace, not the callback), a **tailable JSONL stream**, **forward-referenced
  blobs** (D3). OTel is **not** the live source (spans export on end only).
- **Task 169 is not a 133 dependency** — it's the SSE transport and "defines no run-event schema."
  You own the vocabulary; 169 plumbs it to the browser.

---

## 7. The cache stays separate — do not re-couple (reference)
- SQLite `~/.pflow/cache/cache.db`, WAL; `cache_entries(cache_key PK, node_id, workflow_path,
  action, output BLOB, output_hash, created_at)` + 3 indexes; zlib-compressed output;
  `DEFAULT_TTL_SECONDS = 86400` (`cache.py:19`), eviction every 50 writes.
- `cache_key = md5(config_hash + "|" + deterministic_json(filtered_resolved_inputs))`
  (`cache.py:91-126`); `config_hash` from `instrumentation.py:compute_node_config` (`:141-185`).
- **`output_hash` is WRITTEN but NEVER READ** (`cache.py:400/408`; schema comment "reserved for
  future trace unification (Task 133)"). It is the **cache's own** content hash — **not** a mandate
  to merge stores. Do not treat it as one.
- Only **`llm`** nodes cache by default (`compiler.py:~641-649`) → the cache is a **sparse subset**
  of the trace. Reserved keys `__pflow_stats__` / `__pflow_warnings__` ride inside the blob, stripped
  on restore (`instrumentation.py:396-402, 459-514`).
- **Decision:** the cache keeps its own ~3MB compressed copy; accept the cross-system dup for
  decoupled lifecycles. #357 (cache-key drift) is a **separate** bug — own worktree, don't touch.

---

## 8. Recommended build sequence
1. **Run Spikes #1–#3** (scope #4/#5). Record results in this folder. Decide: unify-vs-parallel
   emission (#2), serialization fidelity for resume (#6/164), append/flush lock vs writer-thread (#3).
2. **Pin the D1 event schema** in one module all consumers cite. Subsume #370; fold #366
   (per-event `workflow_path`). Get sign-off before mass migration.
3. **Write side:** span-context writer; `run.start` / `node.start` / `node` / `llm` / `blob` /
   `run.complete`; `id`/`parent_id`/`run_id`/`seq`; unify the per-sub-workflow collector
   (`workflow_executor.py:352-396`) into `parent_id` chaining; inline-first-occurrence blobs (flip
   `trace_io.py:62-63`); single append lock + frequent flush.
4. **Read side:** JSONL loader reconstructing the tree (reuse the `resolve_blobs` walk per the
   `trace_io.py:100` TODO); `TraceTree.from_dict` accepts either shape (minimal-blast §5). Then add
   the **live-tailing** reader additively for the overlay.
5. **Migrate readers + tests.** With the minimal-blast path, code changes concentrate in
   `trace_io.py` + `save_to_file`; the bulk of effort is the test suite + 4 committed fixtures +
   `TraceFixtureBuilder` regeneration.
6. **Bump `TRACE_FORMAT_VERSION` to `3.0.0`** (breaking — flat JSONL). Update every
   `startswith("2.")` gate to handle 3.x (or a new convention). Decide whether to keep a 2.x reader
   for old traces or drop it (no external users — a hard break is acceptable per project policy).
7. **Verify** (see §9).

---

## 9. Acceptance criteria / Definition of Done
- [ ] One event schema, defined in one place, cited by all consumers; **#370 subsumed**, **#366
      folded in**.
- [ ] **Streamable:** a live tailer reads a *running* trace; blob refs resolve **backward-only**; a
      crash-truncated log is self-consistent (post-crash reader == live tailer).
- [ ] **D2 `run.complete` trailer** present on graceful runs; its absence = hard crash (the resume
      discriminator). `seed_snapshot_into_shared` works from a `failed` trace.
- [ ] **Global monotonic `seq`**; single append lock; frequent flush (or writer-thread if Spike #3
      shows contention).
- [ ] `node.start` events emitted; per-event `id`/`parent_id`; batch items + LLM calls + sub-
      workflows are first-class spans via `parent_id` (no structural embedding).
- [ ] All readers migrated; **`make test` + `make check` green** (capture a baseline first per
      CLAUDE.md, report the delta).
- [ ] Cache and trace remain decoupled (no shared store, no global blob GC introduced).
- [ ] Spikes #1–#3 results recorded in `task_133/research/`.

---

## 10. Trust boundary & open decisions
- **Verified (file:line, 2026-06-18):** all of §3, §5 (the migration map), §6's code refs, §7.
- **Design, not yet code (pin after spikes):** the exact D1 event schema (§4), and the three
  decisions in step 1 of §8.
- **Already decided by the task owner (do not reopen):** (a) the trace↔cache merge is rejected;
  (b) **do the full span-log build now — do not defer/minimize.**
- **Recommendations you may still overturn with spike evidence:** minimal-blast I/O-boundary
  migration (§5); share-schema-keep-two-emission-points (§5 Spike #2); lock-first concurrency (§4).

---

## 11. References
- `task-133.md` (the decision record) and `starting-context/braindump-storage-architecture-session.md`
  (the full reasoning trail + 2026-06-07 verified findings; note: predates #382).
- Root-cause size measurement: Task 159 `BASELINE-AUDIT.md` L-8 (53MB → ~12MB; re-measure before
  leaning on numbers).
- Related issues: **#370** (typed trace contract → subsumed), **#366** (per-event `workflow_path` →
  folded), #382 (shipped), #492 (shipped prereq), #357 (separate cache bug, own worktree).
- Related tasks: 106 (memo cache / SQLite / `output_hash` hook), 108 (trace = tree, no truncation),
  155 (static GraphModel ✅), 168 (initial UI ✅), 164 (resume), 125 (HITL), 171 (durable tokens),
  169 (agent↔browser transport).
- Key source files: `src/pflow/runtime/workflow_trace.py`, `src/pflow/core/trace_io.py`,
  `src/pflow/core/trace_tree.py`, `src/pflow/core/trace_report.py`,
  `src/pflow/runtime/engine/instrumentation.py`, `src/pflow/runtime/workflow_executor.py`,
  `src/pflow/runtime/cache.py`, `src/pflow/core/output_controller.py`,
  `src/pflow/runtime/engine/batch_executor.py`, `src/pflow/core/prompt_cache_analysis/trace_loading.py`.
