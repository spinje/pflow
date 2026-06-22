# Task 172 — Streamable trace event log (emit-time producer / Task 133 Phase D)

> **Implementer note:** Self-contained plan, every file:line re-verified against the current branch (older
> task-133 refs are STALE after a 23-commit rebase). Read `task-172.md`, `ADR-0008`, and
> `.taskmaster/tasks/task_133/design/d1-event-schema.md` for the contract. Build **skeleton-first**.
> This plan has passed two `/deep-review` rounds (round 1: review-plan + validation-consistency +
> impact-completeness; round 2: silent-failures + concurrency-safety + feature-interactions) — their
> findings are folded in below.

---

## Context — why this change

pflow's trace is the single event source for the live-execution overlay (ADR-0008). Today (Task 133 A–C)
it is a flat **JSONL** log on disk, but **written once at the very end**: correlation
(`id`/`seq`/`parent_id`/`run_id`) is derived at *save* time by walking the in-memory **nested** tree, and
each sub-workflow gets its **own** collector whose events are embedded into the parent after it returns.
A live UI can't tail an end-dumped file, and a hard crash leaves **no file at all**.

This task moves correlation **save-time → emit-time**: one run-scoped collector flushes one JSONL line per
node as it completes. **The on-disk format and the reconstructed nested dict do NOT change** (except
`ancestor_path`/`port` are added, stripped on read; blobs move from a trailer to inline-first-occurrence;
per-node status becomes an explicit `status` enum). Producer = this task; transport (Task 169) and the
overlay consumer (Task 173) depend on this, not vice versa.

### Decisions locked with the user (do not re-litigate)
1. **Flat in-memory store**, nested tree is a *derived* `tree()` view reusing A–C's `_rebuild_event_tree`.
2. **Explicit `status` enum** per node = `"success" | "cached" | "failed"`. `degraded` is **run-level only**
   (`final_status`), never per-node.
3. **No backward-compat with old traces** (may change the event shape, regenerate fixtures). This does NOT
   mean ripping out every legacy fallback — see Piece 5.5.
4. **Lenient reader for *incomplete* traces only:** a dangling `parent_id` in a trace with no `run.complete`
   drops the dangling child (transitively); the same in a **complete** trace still raises.
5. **No `node.start` / in-flight signals in v1** — deferred to L2 / Task 164. v1 is completion-only.

---

## The load-bearing invariant (the verification anchor)

For any **completed** run, these three are **identical**: the in-memory **`tree()`** view, the on-disk
**`reconstruct(load_trace_file(path))`** nested dict, and the **cost / `final_status` / `failed_node_ids`**
derived from each. *(Complete runs only. A crash/incomplete trace cannot satisfy it — in-memory `self.events`
keeps the dangling children while reconstruct drops them — so the crash test asserts **recovery**, never
`tree()==reconstruct()`.)*

> **⚠ ATOMICITY — the `status` enum is one shape change, not a trailing pass.** The instant the producer
> (Piece 1) writes `status` instead of `success`/`cached`, **every** reader (Piece 2: `trace_tree.py` cost
> boundaries, `trace_report.py` status/metadata, `_unrecovered_failed_node_ids`) and the central fixtures
> read `status` **in the same step**. A reader left on `cached`/`success` does **not** raise — it silently
> mis-computes cost/status and can pass CI on an all-fresh trace. The equivalence test therefore **must**
> include a cached node (and a cached batch-bearing sub-workflow). Pieces 1, 2, and the status half of
> Piece 6 land **together**.

---

## Architecture overview (build in this order)

| # | Piece | Primary files |
|---|---|---|
| 1 | Flat store + emit-time correlation + `status` WRITE + main-thread assert | `runtime/workflow_trace.py`, `runtime/engine/instrumentation.py` |
| 2 | Reader migration — **atomic with #1**: cost → `tree()`; status/count → top-level; `status` READS | `runtime/workflow_trace.py`, `core/trace_tree.py`, `core/trace_report.py`, `cli/commands/run.py` |
| 3 | Host-descent stack + collector unification (eliminate sequential child collectors) | `runtime/workflow_executor.py`, `runtime/engine/engine.py` |
| 4 | Incremental flush + inline-first-occurrence blobs + finalize | `runtime/workflow_trace.py`, `cli/commands/run.py`, `tests/conftest.py` |
| 5 | Reader: `ancestor_path`/`port` strip, `blob` dispatch arm, **two-pass reconstruct** (dedup + lenient) | `core/trace_io.py` |
| 6 | `status` enum write/read/**test** site checklist (the inventory for #1+#2) | many (see §6) |

Pieces 1+2(+6 status) are the skeleton. Piece 3 is the invasive core. Pieces 4–5 add streaming/crash-safety.

---

## Piece 1 — Flat store + emit-time correlation + `status` WRITE

**Collector state (`workflow_trace.py:468-512` `__init__`)** — add:
- `self.is_run_scoped: bool` (constructor arg, default `False`; the runner/CLI constructs the **root** with
  `is_run_scoped=True`; buffer collectors created in `WorkflowExecutor` pass `False` — this default is
  load-bearing for the routing signal, Piece 3).
- `self._seq_counter: int = 0`, `self._host_stack: list[_HostFrame] = []` (run-scoped only).
- **`self._owner_thread = threading.get_ident()` when `is_run_scoped`** — and `_next_seq`/`descend`/`ascend`
  `assert threading.get_ident() == self._owner_thread`. This converts the central "seq is assigned only on
  the main thread" invariant from a comment into a loud `AssertionError` if a future worker ever reaches the
  seq path (instead of a silent, non-deterministic `seq` gap the equivalence test might pass coincidentally).
- `self._stream` / `self._declared_blobs` (Piece 4).

**`record_node_execution` (`workflow_trace.py:514-575`)** — single append seam (`self.events.append` at :575):
- Replace the `success`/`cached` writes (`:549`, `:553-554`) with `event["status"] = _status(success, cached)`
  → `"cached" if cached else ("failed" if not success else "success")`.
- Add optional `frame: _HostFrame | None = None` (Piece 3, for sub-workflow hosts).
- **If `self.is_run_scoped`:** stamp correlation:
  - `seq = frame.seq if frame else self._next_seq()`.
  - `parent_id = frame.parent_id if frame else (self._host_stack[-1].seq if self._host_stack else None)`.
  - `ancestor_path = frame.ancestor_path if frame else self._current_ancestor_path()` (Piece 3).
  - `event |= {"id": seq, "seq": seq, "parent_id": parent_id, "run_id": self.execution_id,
    "ancestor_path": ancestor_path, "port": None}`.
  - **Every non-host record uses this `frame is None` path** — leaf nodes, cache hits
    (`handle_cached_execution` → `record_trace` with no frame), and API-warning records
    (`handle_api_warning` → `record_trace`). They all take `parent_id` from `self._host_stack[-1]`, so a
    cached/api-warning node **inside a sub-workflow** correctly nests under its host. Only the WorkflowExecutor
    host event passes a `frame` (Piece 3).
  - **Collision guard — import the SHARED constant.** Assert none of `_RESERVED_LINE_KEYS` (from
    `core/trace_io.py`, after Piece 5.1 expands it with `ancestor_path`/`port`) are already on `event` — do
    **not** re-list the keys inline (drift is what the existing guard at `trace_io.py:155` avoids).
  - Then `self.events.append(event)` and, if streaming, flush the line (Piece 4).
- **If not run-scoped (buffer collector):** behave exactly like today — append with `status` but **no**
  correlation keys; children embed via `sub_workflow_events`. (Inline content carries `status`, not reserved.)

**`instrumentation.py` `record_trace` (`:520-595`)** — thread the new `frame` through to
`record_node_execution` (parallel to `child_trace_events` at `:528/:593`). It already computes `success`
(`:586`) and `cached` (`:594`).

**Loop revisits of a leaf** need no special handling: distinct `record_node_execution` → distinct `seq`/`id`,
same `node_id`/`ancestor_path` (a looped *leaf* doesn't descend). *(A looped sub-workflow DOES re-descend each
iteration — see Edge Cases.)*

---

## Piece 2 — Reader migration (ATOMIC with Piece 1)

After Piece 1, `self.events` is flat, *will* contain sequential sub-workflow children (Piece 3) with
`parent_id != None`, and no event carries `success`/`cached` — only `status`. Three fixes, all landing with #1:

**A. Cost readers → walk `tree()`, guarded.** Add:
```python
def tree(self) -> list[dict]:
    return _rebuild_event_tree(self.events) if self.is_run_scoped else self.events
```
The `is_run_scoped` guard is **mandatory**: `_rebuild_event_tree` requires `seq`/`id`/`parent_id` and *raises*
on un-stamped events, and buffer/test collectors (default `is_run_scoped=False`) have none — `tree()` over
them would crash. The guard is also semantically correct: a buffer collector's children are already embedded
as `sub_workflow_events` (tree shape), so no rebuild is needed. **`tree()` uses the EXISTING single-pass
`_rebuild_event_tree` — the two-pass rewrite (Piece 5.3) is disk-only (incomplete/corrected traces) and lands
with streaming, so Pieces 1–2 build and pass their skeleton test before Piece 5 touches the reader.** Then
`collect_llm_calls` /
`_collect_llm_calls_from_events` (`workflow_trace.py:691/701`) and `_collect_llm_summary` (`:854`, called
`:938`) build their `TraceTree` over `self.tree()` instead of raw `self.events`. **Load-bearing:**
`collect_llm_calls` feeds the live-collector cost summary read by `success_formatter.py:82` (the CLI **and**
MCP seam) + `error_formatter.py:87` — these never touch disk, so a flat `self.events` here silently
under-counts sub-workflow cost.

**B. Status / count readers → top-level-only scope (`parent_id is None`)**, EXCEPT `mark_last_event_failed`.
`final_events_by_node` (`:346-372`) keys purely on `node_id`; a flat list lets a child overwrite a parent →
wrong `final_status`. Add `def _top_level_events(self) -> list[dict]: return [e for e in self.events if
e.get("parent_id") is None]` and feed it to:
- `final_events_by_node` in-memory callers: `workflow_trace.py:845` (`_determine_trace_status`), `:908`
  (`finalize`). *(Disk callers `trace_report.py:451/739` read already-nested reconstructed traces — leave them.)*
- `_unrecovered_failed_node_ids` (`:148/:910`): top-level input; migrate `not event.get("success")` →
  `status == "failed"`.
- `nodes_executed` (`:931`): `len(self._top_level_events())`.
- `cli/commands/run.py::_echo_target_node_path` (`:203`, called `:196`): enumerate top-level only.
  *(Defensive — the trigger is currently unreachable: `--only` executes just the target via the snapshot path,
  so no sequential descent populates `self.events` with children. Apply it anyway; don't hunt a repro.)*
- **`mark_last_event_failed` (`:797/823`) does NOT use top-level scope — keep `reversed(self.events)` (ALL
  events).** It flips the single most-recent event matching `node_id`, which is unambiguously the
  just-dead-ended node. A routing dead-end **inside a sub-workflow** (GH #250, `test_failed_node_invariant.py:1321`)
  targets a *child* (`parent_id != None`) — top-level scoping would silently miss it. There is no overwrite
  risk here (it finds one event, doesn't build a dict). It also re-flushes a correction — see Piece 5.4.
- **Verify exhaustive:** grep `final_events_by_node(` and `mark_last_event_failed` callers after the flip.

**C. `status`-enum reader collapses** (same readers, atomic): `core/trace_tree.py:48/164/179/397/453`
(`cached` → `status == "cached"` — cost boundaries / `descend_cached_subtrees`; miss one and cached cost is
mis-attributed) and `core/trace_report.py` ~13 sites. Full list in §6.

---

## Piece 3 — Host-descent stack + collector unification (the invasive core)

**Goal:** one run-scoped collector. Sequential sub-workflow children record *into it* with emit-time
`parent_id` + `ancestor_path` (no per-child collector, no embed). Batch-nested sub-workflows keep **today's**
buffer-and-embed path byte-for-byte unchanged.

**`_HostFrame`** (dataclass on the collector): `seq: int`, `node_id: str`, `parent_id: int | None`,
`ancestor_path: list[dict]`. Entries are `{"node_id": str, "batch_index": int | None}`, mirroring
`AncestorStep` (`core/workflow/graph/model.py:10`), matched positionally+strictly by
`web/src/graph/remap.ts::sameRef`. In v1 only sub-workflow descents push frames → `batch_index` always `None`;
keep the field for forward-compat + `sameRef` exactness. Emit `port: None` on every flat event.

**Collector methods (run-scoped only; all assert main-thread per Piece 1):**
- `descend(node_id) -> _HostFrame`: capture the host's OWN correlation *before* pushing —
  `parent_id = self._host_stack[-1].seq if self._host_stack else None`,
  `ancestor_path = self._current_ancestor_path()` (stack excluding the new host), `seq = self._next_seq()`;
  build frame, `self._host_stack.append(frame)`, return it.
- `ascend()`: `self._host_stack.pop()`.
- `_current_ancestor_path()`: `[{"node_id": f.node_id, "batch_index": f.batch_index} for f in self._host_stack]`.

Reproduces today's **DFS pre-order `seq`** exactly (host reserves `seq` at descent, children take the next
values, host line emitted at completion with the reserved `seq`) — verified for nested/sibling/sequential.

**`WorkflowExecutor.exec` (`workflow_executor.py:314`):**
```python
installed = parent_shared.get("__trace_collector__")
use_run_collector = bool(installed) and installed.is_run_scoped and "__index__" not in parent_shared
```
- **NEW path (`use_run_collector`):** `frame = installed.descend(node_id)` before the child run; child engine
  uses the **installed run collector** (`WorkflowEngine(trace_collector=installed, only_node=child_only)`,
  replacing `child_trace` at `:388-389`); wrap in `try/finally` (exits at `:402`/`:409`): `finally:
  installed.ascend()`; set `self._host_frame = frame`, `self._child_trace_events = None`.
- **OLD path (else):** unchanged (`:351-409`) — buffer `WorkflowTraceCollector(..., is_run_scoped=False)`,
  child engine with it, `self._child_trace_events = child_trace.events`, embed.
- **Add `self._host_frame = None` to the unconditional reset at `:324`** (next to the existing
  `self._child_trace_events = None`, which exists precisely because a *sequential* batch reuses one
  WorkflowExecutor instance across items). Without this, a NEW-path frame from a prior sequential iteration
  could leak into a later item's host event (or its `copy.deepcopy` in a parallel worker). No `__deepcopy__`
  hook is needed — `_HostFrame` is inert plain data and the deepcopy path is always the OLD (batch) path.

**Why the signal holds for ALL nesting — TWO independent clauses (verify BOTH):** `__index__` is set only on
item shared stores (`batch_executor.py:169/383/753`) and is **NOT in `_PROPAGATED_KEYS`**
(`workflow_executor.py:130-142`), so `_create_child_storage` (`:786-812`) never passes it to a grandchild.
So (clause 1) a batch-item sub-workflow sees `__index__` → OLD path → installs a buffer; and (clause 2) every
deeper node sees `installed.is_run_scoped == False` → OLD path **via the buffer's flag, not `__index__`**.
Sequential sub-workflows never set `__index__` and keep the run collector installed → NEW path all the way
down. **Re-verify BOTH:** grep `_PROPAGATED_KEYS` for `__index__` (must be absent) **and** confirm buffer
collectors are constructed with `is_run_scoped=False` (Piece 1 default). A regression in either clause would
route a worker onto the run collector's `_next_seq`/`_host_stack` — caught loudly by the Piece-1 thread assert.

**Parent engine step 16 (`engine.py:1108-1109`):** the `if config.node_type_name == "WorkflowExecutor"`
branch reads `_child_trace_events`. Add a sibling read of `_host_frame`, thread it into `record_trace`
(→ `record_node_execution(frame=...)`) so the host's completion event uses its **reserved** correlation.
`record_trace` is `:1181`; ordering vs `mark_node_failed` (`:1235`, step 17.5) is load-bearing — don't reorder.

**Engine `__trace_collector__` save/restore (`:639-655`):** unchanged; the child engine reusing the run
collector re-installs the same object (no-op). **Leave `__pflow_prompt_cache__` (`:640/648/653-655`) alone.**

**Concurrency (no-lock `seq`):** workers only touch **buffer** collectors (OLD path) and the GIL-safe
`shared["_batch_trace"]` list append (`batch_executor.py:929`); the run collector's `_seq_counter`/`_host_stack`
are main-thread-only (sequential descent + the batch-node drain at `:1180`), now backed by the Piece-1 assert.
*(Forward note, Task 87: `shared["_batch_trace"]` is the GIL-protected worker→main handoff channel; under
subprocess batch it no longer survives a process boundary and is the seam Task 87 must replace — `seq` stays
main-thread-assigned regardless.)*

---

## Piece 4 — Incremental flush + inline-first-occurrence blobs + finalize

- **Filename at run start:** `format_trace_filename` (`workflow_trace.py:31`) inputs are all known at
  construction; switch the timestamp source from save-time `datetime.now()` (`:895`) to **`self.start_time`**
  (`:496`), formatted `start_time.strftime("%Y%m%d-%H%M%S-%f")`. `start_time` is `datetime.now()` with `%f`
  granularity, so the #443 `--only`-vs-full-run collision entropy is preserved; only the *sample time* moves
  to construction (separate processes still start at different microseconds).
- **`self._stream`** opened **lazily on first flush** (write the `meta` line first), run-scoped only. Buffer
  collectors never open a stream (only the root run-scoped collector streams).
- **Per-event flush** (run-scoped, after append): build a line **copy** (never mutate `self.events`), intern
  string leaves ≥`INTERN_MIN_BYTES` (`trace_io.py:15`): for each digest not in `self._declared_blobs`, write a
  `{"kind": "blob", "md5": digest, "value": <full str>}` line and record the digest; replace the leaf with
  `{"$pflow_blob": digest}` (`BLOB_SENTINEL`, `:16`). Then write `{"kind": "event", ...}` and `flush()`. Refs
  are **backward-only**.
- **`finalize()`** (new; replaces `save_to_file`'s body): ensure the stream is open (zero-event runs still get
  meta); compute aggregates **from `self._top_level_events()`** (NOT raw `self.events` — same child-overwrites-
  parent bug as Piece 2.B); write `{"kind": "run.complete", ...}` (`end_time`, `duration_ms`, `final_status`,
  `nodes_executed`, `nodes_failed`, `failed_node_ids`, conditional `llm_summary`/`warnings`/`json_output`, same
  payload as `:912-948`); close.
- **Call site:** `cli/commands/run.py:147` (`_save_trace_file`, idempotency-guarded) calls `collector.finalize()`
  instead of `save_to_file()`. **Streaming-to-disk is CLI-only in v1** — the MCP path never sets `trace_path`
  (its cost summary comes from the in-memory `collect_llm_calls`, Piece 2.A), so this single call-site swap
  doesn't regress MCP.
- **pytest gate:** extend `disable_trace_file_writes_by_default` (`tests/conftest.py:255`, currently patches
  only `save_to_file` at `:271`) to also no-op the stream-open entry point, keyed on the `trace_files` marker.

`flatten_trace_to_lines` (`trace_io.py:128`) becomes obsolete — the producer emits lines directly from the flat
store. **Remove it** (its only non-test consumer is `save_to_file` at `:955`); move per-event first-occurrence
interning into the collector. Keep `substitute_refs` (`:84`) — it already supports an accumulated map.

---

## Piece 5 — Reader changes (`core/trace_io.py`)

Keep `substitute_refs` (`:84`). Change `reconstruct_trace_from_lines` (`:257`) and `_rebuild_event_tree`
(`:231`):
1. **`_RESERVED_LINE_KEYS` (`:33`):** add `"ancestor_path"` and `"port"` (stripped on read → reconstructed dict
   identical to A–C; `status` is real data, NOT reserved). This is the single shared constant Piece 1 imports.
2. **`blob` dispatch arm — add it, not just accumulation.** `_partition_trace_lines` (`:213-225`) has a
   terminal `else: raise json.JSONDecodeError(unknown kind)` at `:224`; a new `blob` kind hits it and **every
   streamed trace fails to load** unless you add `elif kind == "blob": blob_map[line["md5"]] = line["value"]`
   and **remove** the old plural `elif kind == "blobs":` arm (`:221-223`).
3. **`_rebuild_event_tree` → TWO-PASS (this subsumes both the lenient orphan-drop AND the correction re-flush):**
   ```
   Pass 1 — dedup by id (last-wins): deduped = {}; for ev in event_lines: deduped[ev["id"]] = ev
   Pass 2 — link in seq order: for ev in sorted(deduped.values(), key=seq):
       clean = strip _RESERVED_LINE_KEYS
       pid = ev["parent_id"]
       if pid is None: by_id[ev["id"]] = clean; nodes.append(clean)
       elif (parent := by_id.get(pid)) is not None: by_id[ev["id"]] = clean; parent.setdefault("sub_workflow_events", []).append(clean)
       elif is_incomplete: continue   # transitive drop: NOT inserted into by_id, so its descendants also dangle and drop
       else: raise json.JSONDecodeError(orphan)   # complete trace: orphan is corruption (today's behavior)
   ```
   - **Dedup (pass 1, last-wins)** makes a re-emitted correction line (same `id`, Piece 5.4) replace the
     original — exactly once in the tree, no duplicate.
   - **Transitive drop** (skip + do NOT insert into `by_id`) is why a dropped orphan's grandchildren also drop
     (their `parent_id` points at a never-inserted id). `parent.seq < child.seq` guarantees a parent is linked
     before its children, so the skip cascades.
   - Thread `is_incomplete` from `reconstruct_trace_from_lines` (`= not run_complete`, known at `:277`).
4. **Crash-tail tolerance in `load_trace_file` (`:283-303`):** the eager `[json.loads(ln) for ln ...]` (`:299`)
   drops a **single truncated final line** (catch `JSONDecodeError` on the last line only; raise on an earlier
   malformed line) → reconstruct-as-incomplete (`final_status="incomplete"` at `:278`).
5. **Scoped-OUT cleanups (do NOT do — flagged by review):** the `... or "success"` absent-`final_status`
   defaults span **6+ sites across 3 files** (`workflow_trace.py:215`, `trace_loading.py:183/228/633`,
   `summary.py:279/383`, `types.py:846`), are load-bearing for `analyze-cache`'s reuse policy + synthetic
   fixtures, and are **inert for modern traces** — **leave them.** The legacy single-object reader path
   (`load_trace_file:300-303` + `resolve_blobs`) is also separable — **leave it** (inert for JSONL).

---

## Piece 5.4 — Retroactive correction (the routing dead-end)

`mark_last_event_failed` (`workflow_trace.py:797`, sole caller `engine.py:983` `_handle_no_successor`) fires on
a rare routing dead-end **after** the node's event was recorded and (under streaming) already flushed. The flip
(`status="failed"`) is the **sole** signal feeding the trace file's `failed_node_ids`/`final_status` (the
run-level `__failures__`/`__execution__` state is never read at save time), and `test_failed_node_invariant.py`
(`:94`, `:1321`) pins it — so it must stay. Handling:
- **In-memory:** mutate the matched event in place (`status="failed"`, `error=...`) as today — but write
  `status`, and scan `reversed(self.events)` (ALL events, per Piece 2.B), so a sub-workflow-internal dead-end
  is reached.
- **On disk (streaming):** after mutating, **re-flush the corrected event's line** (a second `{"kind":
  "event", ...}` with the same `id`/`seq`, now `status="failed"`). The two-pass reconstruct (Piece 5.3, dedup
  last-wins) makes the corrected line win → `reconstruct(disk)` matches the mutated `tree()`. Flush/disk order
  is **immaterial** — for a sub-workflow-internal dead-end the host line flushes *last* (after the corrected
  child line), but reconstruct sorts by `seq` and dedups by `id`, so linking is order-independent. This is the
  ONLY post-flush correction (`handle_api_warning` flips at *construction* via `record_trace(error=...)`, so
  it's covered by the normal flush + the §6 status migration — no special handling).

---

## Piece 6 — `status` enum write/read/test checklist (the inventory for Pieces 1–2)

Promote `success: bool` + optional `cached: true` → one `status` field. **Lands atomically with Pieces 1–2.**
Exclude out-of-scope families: `final_status`, exec-result `{"success": ...}`, `PlanEntry.status`,
`execution_state.py` step dicts, `metrics.py:232` `nodes_executed`.

1. **Central fixtures first:** `tests/shared/trace_fixture_builder.py`, `_make_event` in `test_trace_report.py`.
   Static fixtures (`tests/fixtures/cache_analysis/parent-child*-trace.json`) regenerated with explicit
   `final_status` + the `status` shape.
2. **Producers:** `workflow_trace.py:549/553` (→ `status`), `:825` (`mark_last_event_failed` → `status="failed"`),
   `batch_executor.py:891` (item) + `:819` (warmup → `status="success"`), `instrumentation.py:586/594`,
   `engine.py:1192`.
3. **Readers → `status`:** `core/trace_tree.py:48/164/179/397/453` (`cached` → `status == "cached"`);
   `workflow_trace.py:152` (`not success` → `status == "failed"`);
   `core/trace_report.py:260/456/562/740/761/898/944-945/955/1016/1018/1360/1412/1489-1491/1500` (`:944-945`,
   `:1016/1018`, `:1489-1491` already hand-derive the enum string → collapse to direct reads);
   `prompt_cache_analysis/trace_loading.py:875/970` (via `WalkEvent.is_cached`, covered by `trace_tree.py:48`).
4. **Tests** asserting event/item `success`/`cached` → `status`: `test_trace_io.py`, `test_workflow_trace.py`,
   `test_metrics_integration.py`, `test_failed_node_invariant.py`, `test_trace_report.py`, `test_trace_tree.py`,
   `test_trace_format_2_1/2_2.py`, `test_trace_integration.py`, `test_batch_node.py`, `test_batch_prewarm.py`,
   **`test_engine_behavior.py:825/891/965`**, **`test_instrumented_wrapper.py:417/453`** (the last two assert
   `event["success"]` directly off `collector.events`). Also add the `tree()`-needs-`is_run_scoped` reason to
   the `test_workflow_trace.py` touch (it constructs bare collectors then calls `collect_llm_calls()`).
   (`test_only_snapshot.py`, `test_plan_batch_sub_workflow.py` touch only `PlanEntry.status` → no change.)

Keep `is_warmup` inline on the warmup item and filtered from call-counting (`_LLMSummaryAccumulator`).

---

## Edge cases (verify each)

- **Looped sub-workflow** (issue #445, supported): a looped *leaf* doesn't descend, but a looped
  **WorkflowExecutor re-descends each iteration** (`exec()` runs per visit; `enforce_loop_guard` invalidates
  its in-process cache, forcing re-execution). The `try/finally` keeps push/pop balanced; each visit gets a
  distinct host `seq` (distinct `id`), same `node_id`/`ancestor_path`. Correct by construction — but **test it**.
- **Cached node inside a sub-workflow:** records via `handle_cached_execution` with no `frame` → uses the
  `_host_stack[-1]` fallback → nests correctly. **Test it** (the headline fixture must place a cached node
  *inside* a sub-workflow, not only at top level).
- **Routing dead-end inside a sub-workflow** (GH #250): `mark_last_event_failed` must reach the child event
  (scan all events, Piece 2.B) and re-flush the correction (Piece 5.4).
- **Crash mid-sub-workflow:** children flushed, host line never written → dangling `parent_id` in an incomplete
  trace → lenient **transitive** drop recovers everything before the sub-workflow.
- **Zero-event run:** `finalize()` opens the stream and writes meta + run.complete.
- **`port`:** emit `"port": null` on every flat event; stripped on read.
- **`ancestor_path` always `batch_index=None` in v1**; batch internals stay inline; batch-item promotion
  (deferred) is coupled to teaching `_rebuild_event_tree` to re-nest `batch_items` (today only
  `sub_workflow_events`).
- **`default=str` lossiness** (`finalize` dump): equivalence test uses JSON-native node outputs only.

---

## What NOT to touch (boundaries)
- `__pflow_prompt_cache__` save/restore (`engine.py:640/648/653-655`) — per-workflow, leave alone.
- The OLD batch-nested embed path — preserve byte-for-byte.
- Step-16-before-step-17.5 ordering (`engine.py:1181` before `:1235`).
- `_pflow_stack` (`workflow_executor.py:177/800`) — file-path cycle detection.
- The `or "success"` defaults + legacy single-object reader (Piece 5.5).

---

## Verification

**Baseline first (capture pass/fail by name, re-run after, report the delta):**
```
uv run pytest -m trace_files                              # authoritative format oracle (164 cases)
uv run pytest tests/test_core/test_trace_io.py tests/test_runtime/test_workflow_trace.py \
  tests/test_integration/test_metrics_integration.py tests/test_integration/test_failed_node_invariant.py \
  tests/test_runtime/test_trace_format_2_1.py tests/test_runtime/test_trace_format_2_2.py \
  tests/test_core/test_trace_tree.py tests/test_core/test_trace_report.py \
  tests/test_runtime/test_trace_integration.py tests/test_runtime/test_engine_behavior.py \
  tests/test_runtime/test_instrumented_wrapper.py tests/test_runtime/test_only_snapshot.py
```

**Headline NEW test — emit↔reconstruct equivalence (the contract):** one realistic workflow
(**sub-workflow + parallel batch + a loop + at least one CACHED node, one of them nested INSIDE a
sub-workflow**, mocked LLM via `tests/shared/llm_mock`), assert **(complete-run only)**: `collector.tree()` ==
`reconstruct_trace_from_lines(disk_lines)`, **plus** cost totals / `final_status` / `failed_node_ids` equal
**hardcoded literals** matching the known fixture (e.g. `summary.total_cost_usd == 0.0042`, the sum of the
mocked per-call costs) — **NOT** recomputed via the same reader over both structures. This is load-bearing:
`tree()` and `reconstruct(disk)` both feed the *same* `TraceTree`, so a missed `cached`→`status` reader leaves
them **equal but wrong** — only the independent cost literal catches it (the `tree()==reconstruct()` half gives
false confidence on its own). Also assert the cached node *inside* the sub-workflow has `parent_id == host.seq`
(it actually nested under its host, didn't escape to `parent_id=None`).

**Producer-internals unit tests:**
- No-lock `seq` under **parallel-batch-of-sub-workflows** (gap-free, `parent.seq < child.seq`, no dupes).
- **OLD-path preservation (highest-risk silent regression):** a parallel-batch-of-sub-workflows trace still
  nests children under `batch_items[*].events`, **never** flat `parent_id` lines. Assert it *discriminatingly*:
  batch-child events carry **no** `id`/`seq`/`parent_id` keys (buffer collectors don't stamp correlation), and
  `len(self._top_level_events())` equals the count of top-level + sequential-descent nodes **only** (excludes
  batch children) — a bare "is nested" check passes even if children are *also* duplicated flat. Take it **two
  levels deep** (sub-wf → batch → sub-wf) and add a **sequential**-batch variant (distinct instance-reuse path).
- **Looped sub-workflow:** each visit a distinct host `seq`, same `node_id`/`ancestor_path`, balanced stack.
- **Loop-recovery through the flat path:** visit-1 fail + visit-2 success → `final_status="success"`.
- **On-error Fallback (degraded):** a node that fails-then-recovers via on-error routing → run `final_status`
  is `degraded`, node-level event honestly `failed`.
- **Routing dead-end:** top-level AND sub-workflow-internal → corrected `status="failed"` reaches disk (re-flush
  + dedup), `failed_node_ids` correct, `tree()==reconstruct(disk)`.
- `ancestor_path` stamping + stripped on read; `port: null` emitted.
- Incremental flush — one `event` line per node; `blob` declaration precedes its first ref.
- **D3 crash-tail:** truncated *final* line → `incomplete`; malformed *earlier* line → raises. **Replaces** the
  A–C test `test_load_trace_file_skips_truncated_tail_line` (`test_trace_io.py:266-280`) — delete it.
- **Lenient transitive orphan:** dangling `parent_id` in an incomplete trace drops the child AND descendants;
  same in a complete trace raises.

**Intermediate checkpoint (the "done" bar, ADR-0008):** one sub-workflow **and** one parallel batch end-to-end
through the unified collector, asserting `parent_id`/`ancestor_path`/`seq` + cost/`failed_node_ids`. Reuse
`task_159/baseline/_shared/workflows/lyrics-generator/` (3-level nesting, batch) as an at-scale **fixture** —
**mocked LLM**. Glance at the collector-events-count asserts Piece 3 touches
(`test_workflow_executor/test_prep_error_action.py:467`, `tests/shared/engine_utils.py:16`).

**Manual e2e (one at a time, scoped HOME):**
```
env HOME=$(mktemp -d) uv run pflow examples/<sub-workflow + batch>.pflow.md
# inspect ~/.pflow/debug/*.json: meta+marker first, one event line per node (parent_id/ancestor_path/seq/port),
# blob lines precede refs, run.complete trailer; then `pflow report` / `analyze-cache` read it back.
```

**Finish:** `make test` + `make check` green; report the baseline delta.

---

## Build order & per-phase verification gates

Each phase has an explicit **exit gate** — do not start the next until it is green. (The "Verification"
section above is the full test menu; this maps each test to the phase that must make it pass.)

1. **Pieces 1 + 2 + the `status` half of Piece 6 (atomic).** Flat store, emit-time correlation, `status` enum,
   reader migration — file still whole-written at finalize (no per-event streaming yet).
   **Gate:** captured baseline still green **+** the headline equivalence test passes on this flat,
   not-yet-streamed producer, asserting cost/`final_status`/`failed_node_ids` against **hardcoded literals**
   (NOT raw `tree()`-dict equality — until Piece 5.1 strips `ancestor_path`/`port`, `tree()` still carries
   them). A **top-level** routing dead-end already works here (the whole-file write reflects the corrected
   in-memory event — no re-flush needed yet); assert its `failed_node_ids`/`final_status`.
2. **Piece 3** (host-descent stack, sequential unification).
   **Gate:** equivalence **+** OLD-path preservation (2-deep sub-wf→batch→sub-wf **and** a sequential-batch
   variant) **+** looped-sub-workflow **+** loop-recovery **+** cached-node-inside-a-sub-workflow tests green,
   **and** the ADR-0008 intermediate checkpoint (one sub-workflow **and** one parallel batch end-to-end) green.
   This is the real "producer works" bar — a green skeleton (step 1) does **not** prove the hard part.
3. **Pieces 4 + 5** (streaming flush, inline blobs, two-pass reconstruct, 5.4 re-flush).
   **Gate:** incremental-flush **+** D3 crash-tail (and the A–C `test_load_trace_file_skips_truncated_tail_line`
   **deleted**) **+** transitive-orphan **+** the **streaming** dead-end re-flush (`tree()==reconstruct(disk)`
   on a dead-end run — only here do events flush *before* the correction, exercising re-flush + dedup) green.

**Final verification:** full `make test` + `make check` green; the manual e2e (scoped `HOME`) writes a valid
streamed JSONL that `pflow report`/`analyze-cache` read back; report the captured baseline pass/fail delta by
name. **After coding:** run `review-silent-failures` + `review-impact-completeness` + `review-test-fidelity`
(the proven code-stage trio for this subsystem).
