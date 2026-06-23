# Braindump: Task 172 producer → Task 173 consumer handoff (2026-06-23)

**Who this is for:** the agent building Task 173 (the live overlay — server-side tailer + frontend). The
producer (Task 172) is **shipped** (PR #530). This file is the **tailer trap list** — the things you will get
wrong if you only read `task_172/task-review.md` (which is *producer*-centric: how to safely MODIFY the
producer) or the D1 schema alone. Each trap below is **verified against the shipped code** and most are
**pinned by a test you can read as the executable spec.**

> Read order: `task-173.md` → `d1-event-schema.md` (now corrected to as-built) → **this** → the three pin
> tests in `tests/test_runtime/test_emit_time_trace.py` (`test_runtime_event_refs_join_onto_the_static_graph`,
> `test_streamed_wire_is_joinable_and_blob_resolvable_by_a_tailer`,
> `test_streamed_wire_dead_end_correction_is_last_wins_by_id_for_a_tailer`).

## The one-line model

The trace is a JSONL file the engine **streams one line per node as the run executes**: a `meta` line, then
— interleaved in emit order — `event` lines and inline `blob` lines, then a `run.complete` trailer at the end.
You **tail it**. The producer never touches your SSE bus (Task 169); you meet it only at the D1 line shape and
the `NodeId = (node_id, ancestor_path)` join.

## The traps (read every one before writing the tailer)

1. **Read the RAW lines yourself. Do NOT reuse `load_trace_file` / `reconstruct_trace_from_lines`.**
   They **STRIP `ancestor_path` and `port`** (they're in `_RESERVED_LINE_KEYS`) — i.e. the post-hoc reader
   removes *the exact field the overlay joins on*. The reconstruct path is for `report`/`analyze-cache`, not
   for you. Parse each line with `json.loads`, read `ancestor_path`/`port` off the raw `event` dict.
   *Pinned by the strip-contrast in `test_streamed_wire_is_joinable_and_blob_resolvable_by_a_tailer`.*

2. **A truncated final line is NORMAL, not corruption.** You are reading a file that is being appended to —
   you will routinely catch a half-written final line mid-flush. `load_trace_file`'s crash-tail tolerance is
   for *whole-file post-hoc* loads; a live tailer needs its OWN "only parse complete lines (ends in `\n`),
   re-read the tail next tick" discipline. Don't treat a partial last line as a crash.

3. **`incomplete` (no `run.complete`) is the normal LIVE state.** Every in-flight run is "incomplete" until it
   finishes. Render it live. (Separately: the post-hoc *consumers* correctly reject an `incomplete` trace as a
   finished snapshot/cache source — that's their policy, not yours. You WANT to show the in-flight run.)

4. **Blobs are inline + backward-only — resolve forward, no trailer.** A large string leaf (≥1 KB) is replaced
   by `{"$pflow_blob": "<md5>"}` and the value rides an earlier `{"kind":"blob","md5","value"}` line, ALWAYS
   written before the first event that references it. Maintain a running `md5 → value` map as you read; resolve
   each event with `core.trace_io.substitute_refs(event, blob_map)` (it accepts a partial/accumulated map — it
   only substitutes digests already seen, which is exactly the backward-only guarantee). There is **no `blobs`
   trailer** (that was the pre-172 shape). *Pinned by the same wire test.*

5. **The SAME `id` can appear twice on the wire → key on `id`, last-wins UPDATE, never append.** A routing
   dead-end re-flushes the corrected event (same `id`/`seq`, `status` flips `success`→`failed`). If your SSE
   consumer appends per line, you render a duplicate node AND show a dead-ended node as success. Index events by
   `id`; a repeat is an update. *Pinned by `test_streamed_wire_dead_end_correction_is_last_wins_by_id_for_a_tailer`.*

6. **The join is two INDEPENDENT derivations — and that's the silent-failure risk.** The producer stamps
   `ancestor_path` from its host-descent stack; the renderer (`react_flow.py`) derives `RFRef.ancestor_path`
   from the IR. The overlay joins via `sameRef` on `(node_id, ancestor_path, port=null)`. If they ever drift
   (wrong `batch_index`, extra/missing step, qualified vs. bare `node_id`), the node **silently never lights
   up — nothing raises.** Both component suites stay green. This is now pinned producer-side by
   `test_runtime_event_refs_join_onto_the_static_graph` (runtime ⊆ graph; a node that RAN must join — the
   converse need not hold: batch internals are inline in v1, untaken branches don't run). **If you touch either
   the producer's descent stack or the renderer, re-run that test.** It is your end-to-end join guarantee.

7. **`port` is always `null` on events** — the producer writes it explicitly on every body event; the graph's
   never-traced IO nodes carry `"in"/"out"` but no `event` ever does. Join with `port = null`.

8. **`batch_index` is always `null` from the runtime side in v1.** Batch items are inline (`batch_items`), not
   flat events — so the producer never emits a flat event with `batch_index != null`. The graph DOES have
   batch-internal RFRefs (with indices), but no runtime event joins to them. That's the v1 "can't show which of
   N is running" limitation, by design (`node.start`/L2 deferred). Don't expect batch-internal nodes to light.

9. **Only CLI / spawned `pflow run` / library-callers-with-`finalize_trace` stream.** **MCP runs do NOT**
   (`trace_enabled=False`). So an agent run via the *MCP server tool* is not watchable; an agent run via the
   *CLI* is. Your launch-by-spawn POST uses the CLI → fine. But the ADR's "watch any agent run" has this
   asterisk — set expectations accordingly.

## The eager-`meta` follow-up — YOUR first producer change (small, scoped to you)

The producer opens the file **lazily on the first node completion** (`_open_stream` ← `_flush_event`), so a
still-running first node (30 s LLM call) is **undiscoverable until it finishes**, and a crash mid-first-node
leaves no file. Fix: write the `meta` line **eagerly at run start** so the file exists from t=0 and your tailer
can find an in-flight run immediately. **It was deliberately deferred to you** (not done in 172) because the
ripple is best guarded against *your* behavior:
- `report.py` newest-by-mtime auto-detect and analyze-cache's "found other traces" disclosure would then see
  contentless `meta`-only files (from a crash before the first completion) — review/guard those.
- The pytest gate already patches `_open_stream`, so it's compatible.
This is in `task-173.md` Requirements and GH #531 (related). It's a ~few-line producer change + the two ripple
guards.

## What's pinned vs. what 173 still owns

- **Pinned (producer-side, green):** the wire shape, the `status` enum, inline backward-only blobs, the
  same-`id` re-flush, crash-tail tolerance, and **the join actually succeeding** (`ancestor_path` ≡ RFRef).
- **173 owns (unpinned — you are the validator):** the file-watcher + truncated-line discipline, SSE framing
  (Task 169 message types), the frontend `sameRef` render, discovery of a live run's file, and eager-`meta`.
  ADR-0008 always intended 173 to be the producer's final validator — the streamed *shape* is proven, the
  *live tail + render* is yours.

## Don't re-derive

- `node_type` is the Python class name (`LLMNode`, `WorkflowExecutor`) — **never surface it raw to agents**
  (authoring-surface rule).
- Filename uses `start_time` (stable from collector construction; `%f` microseconds preserve `--only` entropy).
- Discovery: newest-by-workflow-hash in `~/.pflow/debug`, or have the launched run register its path (trivial
  when you spawned it). Eager-`meta` makes "file exists from t=0" true.

---

> **Note to next agent**: this is the consumer's-eye companion to `task_172/task-review.md`. The review tells
> you how the producer is built; THIS tells you how to *read* it without stepping on the traps the review
> doesn't cover. When ready, confirm you've internalized the join trap (#6) and the read-raw trap (#1) — those
> are the two that silently break the overlay.
