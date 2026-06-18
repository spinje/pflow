# Task 133 — Streamable Span-Model Trace Log: Implementation Plan

> **Status: DESIGN + GATED SPIKES — execution-ready, not yet cleared to code.**
> The *content* layer (#382 / Task 165) shipped; the *disk pain* is solved. The remaining buildable
> work is the streamable, span-shaped, append-only JSONL event log. It is **gated on the live-overlay
> consumer** — a deferred increment *after* the Task 168 static UI. Task 168 is **not** that consumer
> (static-only; zero runtime data). When the overlay work begins, **execute this plan** rather than
> re-deriving a week of investigation; the spike list below is the gate.
>
> **Decision of record:** ADR-0007 (stores stay separate; per-run interning, not a global blob store).
> **Why / what:** `task-133.md` (the decision record + D1/D2/D3). **This file:** the *how*.
> **Read before coding:** `.taskmaster/tasks/task_165/task-review.md` ("Dangerous Edges / Patterns /
> Gotchas") — the load-bearing distillate for trace internals.

---

## 0. Scope — what this plan builds, and what it deliberately defers

**Builds (transport + correlation):** turn the trace from one end-dumped *nested* JSON file into a
single run-scoped, append-only *flat* JSONL event log carrying `run_id` / per-event `id` /
`parent_id` / monotonic `seq`, with blobs declared inline at first occurrence and a `run.complete`
trailer — while keeping **every existing reader working unchanged** via a reconstruct-to-dict reader.

**Defers (the D1 span *taxonomy*):** the *granularity* refinements — promoting batch items to
first-class events with real ids/timestamps, modeling `max_retries` retries as sub-span "attempts",
loop visits as spans. These need the live overlay as their validator (spike #4). This plan **keeps
the current 2.5.0 event content shapes**; it only changes *transport* (nested→flat) and adds
*correlation* fields. The line: **structure + correlation now, granularity later.**

**Out of scope entirely:** the live tailer reader (it's the overlay's job), an OTel exporter
(field-name alignment only — spike #5), the global blob store + GC (gated on *observed* cross-run
dedup), Task 164 resume, Task 125 HITL.

---

## 1. Verified foundation (`file:line` — re-confirm before coding; docs go stale)

### 1.1 Read side — the seam is singular (spike #1, RESOLVED)
- **`load_trace_file` (`core/trace_io.py:108`) is the ONLY function that reads trace bytes off
  disk.** Exactly **3** content-callers; everything else is filename globs:
  - `runtime/workflow_trace.py:110` (`_iter_workflow_traces`) — snapshot loader + analyze-cache autoload
  - `core/prompt_cache_analysis/trace_loading.py:160` (`_load_trace_explicit`) — `--from-trace`
  - `core/trace_report.py:629` (`generate_report`) — `pflow report` / `--report`
- **Read-side choke point:** `TraceTree.from_dict` (`core/trace_tree.py:89`) reads top-level `nodes`
  (list) + `format_version`; recurses `batch_items` / `sub_workflow_events` / `events`. Callers:
  `prompt_cache_analysis/context.py:116`, `trace_loading.py:452,714`, `token_estimation.py:515`,
  `stages/discrepancy/diagnose.py:59`.
- **Other shape-dependent readers:** `trace_report.py` walks the raw dict directly (`generate_report`
  → recursive `_write_node_files`); the `--only` snapshot restore chain
  (`workflow_trace.py:383` `seed_snapshot_into_shared`, `load_full_run_events:183`,
  `load_snapshot_or_raise:226`) reads top-level `nodes` + `final_status`/`warnings`/`only_node` and
  slices `events[:target_idx]` by **execution order**; the whole `prompt_cache_analysis/` package.
- **`metrics.py` does NOT read the file** — it consumes the collector's in-memory `TraceTree`. Immune.
- **Trace-file version gates** (`format_version.startswith("2.")`): `trace_report.py:636`,
  `workflow_trace.py:118`, `trace_loading.py:166`, `stages/discrepancy/diagnose.py:38`. Producer
  constant `TRACE_FORMAT_VERSION = "2.5.0"` (`workflow_trace.py:28`). *(The `4.x`/`5.x` gates in
  `metrics.py`/`mcp_server`/`prompt_cache_analysis.__init__` are the JSON **output** schema — a
  different namespace. Do not touch.)*
- **Conclusion:** keep `load_trace_file(path) -> dict` returning the **same reconstructed nested
  dict**, and Readers 1–7 + `TraceTree` are untouched. That is the ~2-day path; a native-flat rewrite
  is the ~2-week path. **Take reconstruct-to-dict.**

### 1.2 Write side — per-collector, no run_id/seq, embedding (the invasive surface)
- **Collector = its own append log.** `WorkflowTraceCollector` (`workflow_trace.py:427`):
  `self.execution_id = uuid4()` (`:495`), `self.events: list[dict]` (`:497`). **No shared `seq`, no
  `run_id`, no parent pointer anywhere.** Ordering is Python append order.
- **The save/restore seam** (heart of per-sub-workflow isolation), in `WorkflowEngine.run()`:
  `engine.py:529` save parent collector → `:532` install `self.trace` → `:539` run → `:541` restore.
  (`__pflow_prompt_cache__` mirrors this save/restore at `:530/:538/:543` — a unification touching
  `run()` sits beside it.)
- **Child gets its OWN collector:** `workflow_executor.py:350` reads parent; `:359` constructs a
  *new* `WorkflowTraceCollector` keyed on the **child's** path; `:387`
  `WorkflowEngine(trace_collector=child_trace)`; `:392` harvest `self._child_trace_events =
  child_trace.events`.
- **Embedding chain (what flattening replaces):** `engine.py:1016` reads `node._child_trace_events`
  → `:1090` into `record_trace` → `instrumentation.py:593` `sub_workflow_events=` →
  `workflow_trace.py:567` `event["sub_workflow_events"] = ...`.
- **The single append site:** `workflow_trace.py:575` (`self.events.append` in
  `record_node_execution`), reached only via `record_trace` (`instrumentation.py:582`) at
  `engine.py:1082` (success) / `:1165` (except) / `:1029` (api-warning). **All on the main thread.**
- **LLM data is folded, not appended:** the adapter hook writes `self.llm_prompts[node_id]` /
  `self.llm_systems[node_id]` (`workflow_trace.py:969`) **on the inner LLM-pool worker thread**
  (`llm.py:1225` → `llm_client.py:410`), merged into the event later by `_add_llm_data` (`:638`) on
  the **main** thread. The hook touches **node_id-keyed dicts only, never `events`** — this is the
  invariant the no-lock `seq` rests on (§2 Spike #2). **Single canonical prompt field** post-#382
  (`llm_prompt`, `str|list[dict]`) + `llm_system`.

### 1.3 The two batch concurrency channels (the de-risking insight)
- **Channel (a) — progress buffer (display only, NOT trace data):** workers replace
  `__progress_callback__` with a thread-local buffer (`batch_executor.py:748`), return it as the 5th
  tuple element (`:768`), main thread drains via `_drain_worker_buffer` at `_collect_one_future`
  (`:695`). This is the **pattern to mirror**, not data to move.
- **Channel (b) — `shared["_batch_trace"]` accumulator (the actual trace data):** init
  `batch_executor.py:246`; per-item append `_capture_item_trace:918` ("GIL-protected"); warmup append
  `:803`; **drained on the MAIN THREAD** by `_collect_batch_trace` (`:128`, `pop`) at `engine.py:1081`
  (success) / `:1163` (except), then embedded as `event["batch_items"]`.
- **Thread-safety today = GIL-atomic `list.append`, NO lock, NO shared counter**, with a post-hoc
  `index` field (`:878`) for ordering (parallel appends land in **completion** order).
- **★ Load-bearing consequence:** *every* `collector.events` append is **already main-thread**; the
  only worker-touched structure is the per-node `_batch_trace` list, and it is **already drained on
  the main thread**. So a global monotonic `seq` needs **no new lock and no shared counter under
  worker threads** — assign `seq` at the existing main-thread append + drain points. This collapses
  most of spike #2/#3 (see §2).
- **"Bundle 8" invariant (do not break):** the `_batch_trace` shared-store buffer is the *recovery*
  channel — on a fail-fast raise, items completed before the failure survive into the except-path
  drain (`engine.py:1163`, comments `:997-1002,1157-1163`). Any change that moves trace appends out of
  `shared["_batch_trace"]` must replicate this success/except symmetry or it reintroduces the
  lost-items bug.
- **Two unrelated `execution_id`s — do not conflate:** trace (`workflow_trace.py:495`) vs probe
  (`execution_cache.py:37`, `exec-{ts}-{hex}`). Only the former is in scope.

### 1.4 The content layer (#382) already shipped — reuse, don't rebuild
- `core/trace_io.py`: `intern_blobs` writes blobs as a **trailer** (`:62-63`); `resolve_blobs`'s
  substitution `walk` is **inlined** (`:86-98`) with an explicit forward-compat note
  (`:100-101`: "Future jsonl reader: build the blob map from inline declarations … then reuse this
  substitution walk"). Ref convention `{"$pflow_blob": <md5>}`; string-only; ≥1 KB; skips `__`-keys.
- The interning walk is **shape-agnostic** (proven on `batch_items`/`sub_workflow_events`) — it
  survives nested→flat unchanged.

---

## 2. Spike resolutions

### Spike #1 — migration blast radius — **RESOLVED** (§1.1)
Singular seam; reconstruct-to-dict keeps all readers green. ~2-day vs ~2-week fork → take
reconstruct-to-dict.

### Spike #2 — global `seq` + concurrency reconciliation — **VERIFIED (adversarial audit, 2026-06)**
The scary version ("single lock around (assign seq, append, flush) under `ThreadPoolExecutor`") is
**not needed.** An adversarial audit confirmed the **only** mutating site on `self.events` is the
`events.append` at `workflow_trace.py:575` (`record_node_execution`), reached only via `record_trace`
at the three **main-thread** `_execute_node` sites (`engine.py:1082/1165/1029`). **Batch workers
never touch `events`** — they call `_execute_single_node` (no trace recording) and append only to the
GIL-safe `shared["_batch_trace"]` list, drained on the main thread (`engine.py:1081/1163`). So assign
`seq` at those existing main-thread points:
- Sequential / sub-workflow nodes: `record_node_execution` (main thread) → assign `seq`, append.
- Batch items: workers keep appending to `_batch_trace` **without** `seq`; the main thread assigns
  `seq` in completion order **at the drain** (`engine.py:1081`), mirroring progress channel (a).
- **No lock, no shared counter under worker threads. One seq counter, one main-thread writer.**

**⚠ The one invariant the no-lock `seq` rests on (do NOT violate):** the **LLM trace hook runs OFF
the main thread** — `LLMNode.exec` submits `_call_llm` to its own inner `ThreadPoolExecutor`
(`llm.py:1225`) and the hook fires there (`llm_client.py:410` → `workflow_trace.py:969`). Today it
writes only `llm_prompts[node_id]` / `llm_systems[node_id]` (node_id-keyed dicts; under a parallel LLM
batch those writes race **benignly**, last-writer-wins, already documented at `llm.py:893-912`) — it
**never touches `events`**. The no-lock `seq` is safe *only because event materialization stays at the
main-thread `record_trace` site.* **Hold the line: the hook writes node_id-keyed dicts only; events
are materialized main-thread.** If a future change lets the hook append an event or assign a `seq`
from that inner worker thread, the no-lock assumption breaks.
- *Fallback (only if off-main-thread emission is ever introduced — Task 87 subprocess sandboxing, or
  the invariant above being broken):* a `threading.Lock` around (assign seq, append), or a queue +
  single writer thread. Re-verify single-process/multi-thread still holds (`batch_executor.py:815` is
  a `ThreadPoolExecutor`, not subprocesses, today) before relying on no-lock.
- **The progress channel stays separate.** Folding progress+trace into one emission *adds* a richer
  intermediate type + reconciliation logic — it does not delete complexity. Share only the event
  *schema*; keep the two thin channels. (The spike's documented fallback, promoted to recommendation.)

### Spike #3 — append+flush performance — **RESOLVED (benchmarked, 2026-06)**
A throwaway isolated benchmark (`scratchpads/task-133/spike3_flush_benchmark.py`, no pflow code)
settled it. Representative post-interning event ≈ **800 bytes** (large strings are blob refs).
Per-event cost on local SSD: **~6 µs flush, ~23 µs fsync.** So a 1,000-event run = **6 ms flush /
23 ms fsync**; 10,000 events = **57 ms / 234 ms**. A real run is dominated by LLM calls (1–3 s each),
so writing the *entire* trace is **<0.01% of wall-clock**. The parallel-produce → main-thread-drain
pattern cost ~9 ms for 1,000 items / 16 workers.
- **Conclusion: flush every event for free; fsync every event if hard crash-durability is wanted.**
  No batched-flush, no writer thread, no cadence knob. The "flush frequently or lose the tail" caveat
  dissolves.
- *Caveat:* benchmarked on local SSD (where `~/.pflow/debug/` lives). On a network FS `fsync` would
  cost more, but plain `flush` (reaches the OS page cache — all a live tailer needs) stays cheap
  everywhere; only hard-crash durability is FS-dependent.

### Spike #4 — overlay's actual data needs — **deferred to the overlay (by design)**
Whether the overlay needs resolved inputs/outputs (which live in the trace, not the progress
callback) and whether it needs L2 node-`start` events resolves *as the UI work begins*. The 4-level
liveness ladder (L0 end-dump → L1 per-node-completion → L2 node-start → L3 in-node progress): a
serviceable overlay needs only **L1 + the static graph** (infer "next node running" from Task 155's
graph); L2 earns its keep only for **parallel/batch** (can't infer which of N is running) and **long
nodes** (heartbeat). **This plan delivers L1.** Do not pre-build L2/L3.

### Spike #5 — OTel export round-trip — **field-name alignment only, build nothing**
OTel traces export on span-end only (no in-progress span) → OTLP **cannot** feed a live overlay
(verified vs the SDK spec). So pflow's own stream is the live source of truth. **Borrow the data
model, not the wire envelope:** align field *names* (`id`↔span_id, `parent_id`↔parent_span_id,
`run_id`↔trace_id; `gen_ai.usage.*` token names; `cost_usd` is non-standard, keep as-is) so a *future*
export is a rename. **Do not build an exporter** (one hypothetical consumer).

---

## 3. The phased plan (each phase has its own green gate)

> **Approach (revised after reading the engine — see progress-log):** A–C is a **disk-boundary
> serialization transform**, NOT engine surgery. The in-memory collector already builds a correctly
> ordered nested tree; all correlation (`seq`/`parent_id`/`run_id`/`id`) is **derived from that tree at
> save time**. The *production* surface is small — `trace_io.py` + `workflow_trace.save_to_file` (the
> sole writer — verified one caller, `run.py:147`). **Zero engine changes, zero hot-path changes, zero
> collector-lifecycle changes.** BUT the full change is **NOT a 3-file change** (review correction):
> it also migrates ~7 test files that read the raw trace as a single JSON object (see Phase C gate),
> reconciles docs, and adds new round-trip/regression tests — that test surface, not the production
> code, is the bulk of the effort. The format A–C writes is **D-stable**: the deferred Phase D changes
> *when* correlation is assigned (save-time → emit-time) and *how* events are collected, never the
> on-disk format or the reader.

### Phase A — Extract `substitute_refs` ✅ DONE
Extracted the inlined substitution `walk` out of `resolve_blobs` into module-level
`substitute_refs(obj, blob_map)` in `trace_io.py`; `resolve_blobs` delegates (behavior-preserving).
The Phase-C reader reuses it with a map read from the `blobs` trailer.
- **Gate met:** `test_trace_io.py` 11/11 pass; ruff + mypy clean.

### Phase B — Flatten at the disk boundary (the writer) — PINNED CONTRACT (post-review)
`save_to_file` (sole writer, `workflow_trace.py:873`) walks the existing in-memory nested tree and
emits flat JSONL. **No engine/collector changes.** Every new trace is **≥ 2 lines**.

**Line structure:**
- `meta` (first line) — carries an **explicit transport marker** `{"pflow_trace": "jsonl/1", ...}`
  plus run-identity keys known at start (`_META_KEYS`: `execution_id`, `workflow_name`,
  `workflow_path`, `start_time`, and **`only_node`** — knowable-at-start AND a snapshot-source filter
  key, so a future head-only reader can reject `--only` traces without reading the trailer; B/C-checkpoint
  finding). **`format_version` STAYS `"2.5.0"`** (Decision 1: content is unchanged; the JSONL
  transport is identified by the `pflow_trace` marker, versioned independently — `"jsonl/1"`).
- one `event` line per flattened node event.
- `blobs` trailer line (interned via existing `intern_blobs` over the flat structure; stays a trailer
  for A–C — inline-first-occurrence is Phase D).
- `run.complete` trailer line (D-stable; computed at save, written as a trailer so A–C's format ==
  Phase D's streaming format and Task 164 gets its graceful-vs-crash discriminator for free).
- **Writer invariant (assert it):** always ≥ 2 lines, and the first line is always the marked `meta`.

**Generic top-level fold (fixes the `json_output` data-loss — finding D):** the union of meta-keys +
run.complete-keys MUST equal **every** top-level key `save_to_file` emits today (authoritative source:
`workflow_trace.py:913-948` — includes the conditional `json_output`, `llm_summary`, `warnings`). Meta
= keys knowable at start; run.complete = all the rest. **Do not hand-enumerate** — derive from the
built `trace_data` dict. A test asserts `set(meta)|set(run.complete) == set(today's top-level keys)`.

**Flatten granularity (pinned — finding G):** flatten **only top-level events and their
`sub_workflow_events`, recursively**, into lines. **`batch_items` — and everything nested under them,
including a batch item's own `events` sub-workflow tree (`batch_executor.py:914`) — stay INLINE** in
the host line. The synthetic warmup item stays inline. (A line is a node event; its `batch_items` ride
inline; only sub-workflow *node* events become their own lines.)

**Correlation (derived at save, single-threaded — findings F, H):**
- `seq` — assigned in **DFS pre-order** over `self.events` (parent before its children). Monotonic,
  gap-free, unique. Note this is *structural* order, not wall-clock (a parent's event is recorded
  after its children run) — correct for reconstruction.
- `id` — **the event's own `seq`** (synthetic unique token; **NEVER `node_id`** — loop revisits and
  same-id-across-sub-workflows collide).
- `parent_id` — the enclosing event's `id`; `null` at top level.
- `run_id` — the root collector's `execution_id`.
- No lock; save-time single-threaded → spike #2 N/A here.

**Extension stays `.json`** (Decision; globs key on the prefix; reader sniffs the marker, not the
extension).

**Gate:** writer unit test asserts — ≥2 lines + first line marked `meta`; `meta∪run.complete` ==
today's top-level key set **including `json_output` on a `--output-format json` run**; every event line
carries `id`/`parent_id`/`run_id`/`seq`; correct parent chains across (a) a nested sub-workflow and
(b) a **sub-workflow inside a parallel batch** (`heterogeneous_workflow_batch_event`); a loop-recovery
run (same `node_id` twice) yields two lines with **distinct `id`s**.

### Phase C — Reconstruct-to-dict reader — PINNED CONTRACT (post-review) — the critical phase
`load_trace_file` (`trace_io.py:108`) gains **marker-based** detection + reconstruction.

**Format detection (positive, not parse-inference — finding A / Decision 1):** read the **first line**;
if it parses as a JSON object carrying the `pflow_trace` marker → **new JSONL**; otherwise → **old**
(existing `resolve_blobs` path, unchanged). Dual-read; old `~/.pflow/debug` traces keep working. (No
reliance on "whole-file parses as one value" — that was the fragile bit.)

**Malformed vs incomplete (Decision 2):**
- **Unparseable** (bad JSON on any line, missing the marker-or-old-shape, broken structure) → **raise
  `json.JSONDecodeError`** so the 3 callers (`generate_report:630`, `_iter_workflow_traces:111`,
  `_load_trace_explicit:161`) keep their existing degrade/skip behavior. **Never return a half-dict.**
- **Trailer-absent but parseable** (crash before `run.complete`) → reconstruct with `final_status`
  left **absent / `"incomplete"`, NOT defaulted to success**. Fix the truthiness defaults so an
  incomplete run is not a reusable snapshot / clean success: `load_full_run_events:215` and
  `trace_loading.py:225` (`... or "success"`) must treat absent-`final_status` as ineligible (finding B).

**Reconstruction → exact 2.5.0 nested dict:**
- Group event lines on **`(id, parent_id)` identity, NEVER `node_id`** (finding F): top-level =
  `parent_id is null`; a parent's `sub_workflow_events` = its children, recursively.
- **Orphan `parent_id`** (no matching parent `id`) → **raise** (corruption signal), never silent-drop
  (finding I).
- Order top-level `nodes[]` by a **stable sort on `seq`**; order each parent's children by their
  `seq`. This reproduces `self.events` append order → `final_events_by_node` last-occurrence and
  `--only`'s `events[:target_idx]` slice stay correct (findings H, W2).
- **Empty children → OMIT `sub_workflow_events`** (match the writer's `if sub_workflow_events:`), never
  `[]` (finding L).
- Fold meta + `run.complete` back to top-level keys **generically** (all keys, mirroring the writer's
  generic fold).
- Resolve blobs via `substitute_refs` (Phase A); any **surviving `$pflow_blob` ref → log a warning**
  (corruption signal) (finding M).
- **Strip the FIVE line keys `kind`/`id`/`parent_id`/`seq`/`run_id`** when rebuilding events (the
  writer derives all five — `kind` was missing from the original list, B/C-checkpoint finding S1), and
  drop the `kind`/`pflow_trace` discriminators from the meta + trailer lines on fold-back. **PRESERVE
  everything else**, in particular `node_output._pflow_child_workflow_paths` (drives
  `_collect_default_edges` attribution — finding K). Correlation lives only on disk for the future
  overlay (reads flat natively).

**`TRACE_FORMAT_VERSION` stays `"2.5.0"`** (Decision 1) → the `== "2.5.0"` pin (`test_trace_format_2_2.py:26`)
stays green; no version churn.

**Gate (the transparency oracle — expanded per review):**
- **New `save_to_file`→`load_trace_file` round-trip test** driving a REAL `WorkflowTraceCollector` over
  a workflow with sub-workflow + parallel batch + loop + a 0-event branch + a **non-JSON-native leaf**
  (Path/datetime): reconstructed dict == in-memory tree **modulo `default=str` coercion**; assert
  **idempotence** (re-save is byte-stable) (finding J). Needs the `trace_files` marker (`conftest.py`).
- **Migrate raw-file test readers** → `load_trace_file` (or a `read_trace_lines` helper) and add to the
  gate (finding E / the scope correction): `test_workflow_trace.py` (~25 sites incl. the `blobs`-is-
  last-key assertions), `test_trace_format_2_1.py`, `test_trace_format_2_2.py`, `test_runner.py`,
  `test_failed_node_invariant.py`, `test_trace_integration.py`, `test_cli_mcp_parity.py`.
- **Dual-read regression:** keep the committed nested `cache_analysis` fixtures AS-IS (old branch) —
  `_generate.py` STAYS nested (do NOT flip to JSONL); they must still load via the old path.
- **`default_edges` parity** test (sub-workflow with `_pflow_child_workflow_paths`).
- Existing loader-based suites stay green unchanged: `test_trace_tree.py`, `test_cache_analysis_*`,
  `test_only_snapshot.py`, `test_dotted_only_path.py`.
- Identical `report` / `analyze-cache --from-trace` / `--only` output on a real recorded workflow.

### Deferred to Phase D (liveness — built WITH the overlay, NOT in A–C)
A–C establishes the on-disk format; Phase D makes it *tailable* without changing that format.
- **Collector unification + incremental append** — one run-scoped collector, `run_id`/`parent_id`/`seq`
  assigned at **emit** time (not derived at save), each line flushed as recorded. This is the invasive
  engine/hot-path change; it changes *when* correlation is assigned, **not** the on-disk shape A–C
  wrote. (This is where spike #2's no-lock main-thread `seq` design applies.)
- **D3 — blobs inline at first occurrence** (replaces the A–C `blobs` trailer) — backward-only refs so
  a live tailer never hits an undefined ref and a crash-truncated log stays self-consistent. The
  Phase-C reader's blob-map accumulation already supports this via `substitute_refs`.
- The `run.complete` trailer is **already** in A–C's format, so Phase D (and Task 164's
  graceful-vs-crash discriminator) inherit it for free.
- **Crash-tail gate (D):** kill a run mid-stream → the partial JSONL still loads (degraded, no
  trailer) and `report` renders what completed.

---

## 4. Open decisions — surfaced, NOT silently decided

1. **Dual-format reading of old `~/.pflow/debug` traces — DECIDED: dual-read.** `load_trace_file`
   sniffs format (whole-file `json.loads` succeeds → old nested; raises "extra data" → new JSONL) and
   branches to the existing `resolve_blobs` path or the new reconstruction. A few lines at the single
   seam; old traces (and in-flight `--only` / `analyze-cache` against recent runs) keep working. No
   clean break. Extension stays `.json` (see Phase B).
2. **D1 span taxonomy — left UNPINNED on purpose.** Batch-item promotion, retry-as-attempt, loop-as-
   span are **not** in this plan. Pin them against the live overlay (spike #4). The only fixed
   contract today is the identity join key `NodeId = (node_id, ancestor_path)` (ADR-0003 /
   graph/CLAUDE.md "Runtime Overlay Join Contract") — events must carry/derive it; the static UI (168)
   already emits the matching `ref`. *(Note: today's batch items have no `node_id`/timestamp/`id` —
   promoting them is real work, deferred.)*
3. **`max_retries` retries are still untraced** — two distinct "retries" exist: graph-loop re-exec
   (≈free, new visits today) vs node-internal `max_retries` (currently **no** emit points). "Retries
   as attempts" = NEW emit points in the Node lifecycle, not free. Deferred with the taxonomy.
4. **The synthetic prewarm warmup item** (`batch_executor.py:~803`, `index:-1`, `is_warmup:True`)
   bypasses the normal item path and is filtered at 8 call-counting sites. The reconstruction (Phase
   C) and any future span decision must not let it become a phantom span. Keep it inline in its host.

---

## 5. Verification strategy

- **`verify.sh` is a read-path oracle, NOT a forward gate, and is currently PRE-DRIFTED.** Read
  `task_159/baseline/verify.sh` + `run-case.sh` *before* trusting any run: it re-runs commands against
  **committed** fixtures under `env -i` (no API key) and diffs stdout — it does **not** re-record live
  traces. Its committed `expected-*.txt` predate an unrelated `analyze-cache` "Missing API key" change,
  so it shows false-alarm drift even on static greenfield cases. **Usage:** confirm your change adds
  *zero new* drift on the trace-reading cases beyond the immune-greenfield baseline. **Do NOT
  regenerate `expected-*.txt`** as part of this work — baseline reconciliation is a separate
  main-branch task the user owns by hand.
- **The transparency oracle** = the expanded **Phase C gate** above (round-trip with a non-JSON-native
  leaf + idempotence; migrated raw-file test readers; dual-read regression; `default_edges` parity;
  existing loader suites green; identical `report`/`analyze-cache`/`--only` on a real trace). This is
  how you prove transport changed but *meaning* didn't.
- **Manual e2e pass (REQUIRED — the suite isn't enough; this repo's bugs have surfaced from real runs,
  not the suite — tests/CLAUDE.md #19):** run a real workflow with a nested sub-workflow + a parallel
  batch + a loop, then `pflow report`, `pflow analyze-cache --from-trace`, and `pflow <wf> --only
  <mid-node>` against the saved JSONL trace — diff each against a pre-change baseline captured on `main`.
- **Doc updates (in scope):** `mcp_server/.../mcp-agent-instructions.md` `cat …json | jq '.'` →
  JSONL-aware (`jq -s`/per-line); reconcile `runtime/CLAUDE.md` ("blobs as top-level trailer",
  "Tree-structured events", the 2.5.0 section) and `prompt_cache_analysis/CLAUDE.md` "Runtime Trace
  Contract" with the JSONL transport.
- **`/code-review` checkpoint at the B/C boundary** (after the writer, before the reader is finalized) —
  Phase C's correctness depends on B's correlation being exactly invertible (the top risk).
- **Crash-tail test (Phase D):** truncate a JSONL log mid-stream → loads degraded, no trailer,
  `report` renders the completed prefix.
- **Real measurement to cite (not stale prose):** interning alone = ~33% / 3.1 MB on the committed
  9.44 MB cleaned fixture; round-trip identical (Task 165). Re-measure transport overhead on a real
  workflow before claiming numbers.

---

## 6. Risks / what could go wrong
- **Phase C reconstruction fidelity** is the top risk — the nested shape has subtle attribution rules
  (sub-workflow `workflow_path` threading, batch-item edges, last-occurrence collapse). Mitigation:
  the existing `TraceTree` recursion is the exact target spec; the round-trip + reader-parity tests
  are the oracle.
- **Flatten/reconstruct must be exact inverses.** Correlation is *derived at save* (A–C), so the
  reconstruction must invert the flatten precisely (parent grouping, `seq` ordering, trailer-fold,
  blob resolve, correlation strip). The round-trip + reader-parity tests are the oracle. *(The `run_id`
  threading / id-reservation ordering at the `engine.py:529-545` save-restore seam is a **Phase D**
  concern — A–C derives `run_id`/`parent_id` from the existing nesting at save time and touches no
  engine code.)*
- **Building ahead of the consumer** (the reason this is gated): if Phase D ships before the overlay,
  the inline-blob/trailer/`seq` machinery has no live reader validating it. Mitigation: Phases A–C are
  pure transparency (provable by existing tests); only Phase D adds unused-until-overlay liveness —
  consider stopping after C if the overlay slips.
- **Spike #2's no-lock `seq` rests on TWO invariants** (both verified 2026-06; both must still hold
  at build time): (1) **single-process / multi-thread only** — Task 87 sandboxing could introduce
  subprocesses; (2) **the LLM trace hook writes node_id-keyed dicts only** and never materializes an
  event / assigns a `seq` from its inner worker thread (`llm.py:1225`). Do not let the streamable
  design move event-append into the hook. Break either and you need the lock/queue fallback.

---

## 7. References
- **Decision:** `context/adr/0007-133-trace-cache-storage-separation.md`; ADR-0003 (NodeId identity).
- **Why/what + D1/D2/D3:** `.taskmaster/tasks/task_133/task-133.md`.
- **Reasoning trail + verified evidence:** `task_133/starting-context/*.md` (storage-architecture
  session; post-382 implementation; OTel verification & JSONL design).
- **Read before touching trace internals:** `task_165/task-review.md` (Dangerous Edges / Patterns /
  Gotchas); `runtime/engine/CLAUDE.md` ("Synthetic Cache Warmup Item", "Per-worker progress buffer",
  "Bundle 8").
- **Key source:** `core/trace_io.py`, `runtime/workflow_trace.py`, `runtime/engine/engine.py`,
  `runtime/engine/instrumentation.py`, `runtime/engine/batch_executor.py`,
  `runtime/workflow_executor.py`, `core/trace_tree.py`, `core/trace_report.py`,
  `core/prompt_cache_analysis/`.
- **Consumer (gates the build):** Task 168 static UI (`feat/workflow-visualization-static-viewer`) →
  then the live-overlay increment (the real consumer). Related: #492 (landed), #370 (folds into D1),
  Task 164 (resume; shares D2 trailer), Task 125 (HITL; adds an escalation event kind).
