# Braindump: Task 133 storage-architecture session — for whoever builds this

This file is the **reasoning trail + verified evidence** behind the rewritten `task-133.md`. The
task file is the distilled decision; this is *how we got there, what was verified vs assumed, and
what was rejected and why*. Read `task-133.md` first, then this for the "why" and the citations.

The session started from a user question — *"do I have a gh issue about the debug JSON being 100MB+
from data duplication?"* — and turned into a full re-derivation of the trace/cache storage
architecture. Two agents collaborated (a storage/internals lens and an observability/liveness lens);
this captures the convergence.

## The one thing that flips everything: the merge doesn't fix the problem

Task 133 was written **2026-03-26**, *before* prompt caching (159), the cache-analysis refactor
(160), and safer cache defaults (161). Its premise — node output duplicated across trace + cache,
~3MB overlap — is **true but irrelevant to the observed pain**:

- The user's pain is a **100MB+ trace file**.
- The trace↔cache overlap is **~3MB**. Merging the stores removes ~3MB of ~100MB.
- The 100MB is **within-trace** duplication: L-8 measured the lyrics trace at **53MB raw → ~12MB**
  after stripping duplicated text (Task 159 `BASELINE-AUDIT.md` L-8, recorded 2026-05-08). So ~77%
  of the file is the trace duplicating content *against itself*, not against the cache.

So the first move was *not* "how do we build the merge" — it was "the merge targets the wrong axis;
don't build it." That reframe is the spine of the whole decision.

## Verified findings (5 parallel codebase searches — trust: VERIFIED in code unless noted)

**Trace system** (`src/pflow/runtime/workflow_trace.py`):
- `WorkflowTraceCollector` accumulates events in memory, dumps once at end via `save_to_file()` →
  `json.dump(..., indent=2, default=str)` (~line 850). **Uncompressed, pretty-printed.** Only
  production caller: `cli/commands/run.py` (`_save_trace_and_report`), gated on trace enabled.
- `TRACE_FORMAT_VERSION = "2.4.0"` (NOT the 2.0.0-era the task assumed). Three additive bumps since,
  all from the tasks the spec named as future: 159 (2.0.0→2.2.0: `workflow_path`, memo-cache
  correlation fields, `llm_system`, prompt-cache token fields; then 2.3.0), #443 (2.3.0→2.4.0:
  `only_node`). Consumer gate is `format_version.startswith("2.")` everywhere — additive minors are
  forward-compatible.
- **No truncation anywhere** — `_sanitize_for_json` only filters `__`-keys (keeps `__metrics__`) and
  replaces bytes with a placeholder. Full untruncated `node_output`, `llm_prompt`, `llm_system`,
  `llm_response`, `template_resolutions`, `node_params`, nested `batch_items` / `sub_workflow_events`.
  This is *intentional* (Task 108: agents must SEE full content). Job is to dedup, NOT re-truncate.
- **Trace is now a load-bearing READ path** (the spec's "trace becomes a generated artifact" ignores
  this): `--only` snapshot seeding reads per-event `node_output` from disk to seed `shared[node_id]`
  (`workflow_trace.py:347-388`); `analyze-cache` autoload discovers traces by `{wf_hash}` filename
  glob. Filename schema is now `workflow-trace-{wf_hash}-{name}-{timestamp-µs}.json`.

**Cache system** (`src/pflow/runtime/cache.py`) — the spec's biggest stale assumption:
- It is **NOT "lean cache files"**. It is a single **SQLite DB** `~/.pflow/cache/cache.db`, one row
  per invocation, `output` stored as **zlib-compressed JSON BLOB**. The "cache index maps cache keys
  to store entries" / per-file model in the spec **does not exist**.
- Schema: `cache_entries(cache_key PK, node_id, workflow_path, action, output BLOB, output_hash,
  created_at)` + 3 indexes. `output_hash` comment literally says *"reserved for future trace
  unification (Task 133)"* — written, **never read** (the only existing 133 groundwork). It is the
  cache's own content hash; do not over-read it as a merge mandate.
- Cross-run, TTL-bounded (24h), workflow-path-scoped — NOT the "iteration cache" the spec frames.
- Type-based gating (Task 161): only `llm` nodes cache by default. So the cache is a **sparse subset**
  of what the trace records — the "~3MB written to both" symmetry is weaker than the spec implies;
  the trace is the superset.
- Reserved keys ride *inside* the blob: `__pflow_stats__` (duration/cost for `--dry-run`) and
  `__pflow_warnings__`, injected by `write_memo_cache`, stripped on restore. Task 156 says any
  unification must reuse/extend `__pflow_stats__`, readers absent-tolerant.

**Duplication verified** (the central premise): trace `node_output` and cache `output` are the
**same** `shared.get(node_id)` value, shallow-copied independently on the happy path —
`engine.py:884` (cache write) and `engine.py:915` (trace write). Trace is a strict superset; cache
is output-only + compressed. The within-event 4× prompt (#382): `llm_prompt`,
`node_params.prompt`, `template_resolutions.prompt.resolved`, `node_output.prompt` — all carry the
resolved prompt. **`node_params.prompt` and `node_output.prompt` have ZERO downstream consumers**
(grep-verified); only `template_resolutions.prompt.resolved` + `llm_prompt` are read, both by
`trace_report.py` for `## Prompt`. (3 copies for a static prompt; `template_resolutions` is
template-gated.)

**Break surface** (what a shape change touches): `TraceTree` (`core/trace_tree.py`) is the central
contract — *nearly every consumer funnels through it*, which is what makes both interning
(ref-resolution) and a future flat→tree reassembly tractable as a single change. `trace_report.py`
also walks directly. Plus the whole `prompt_cache_analysis/` package, 4 `startswith("2.")` gates, 4
committed JSON fixtures in `tests/fixtures/cache_analysis/`, `tests/shared/trace_fixture_builder.py`,
~62 test files touching trace fields.

**Sizes** — trust: ILLUSTRATIVE, not verified. No committed artifact measures file sizes. 17MB/3MB
(March, task-106) and 53MB→12MB (May, L-8) both come from prose about the lyrics-generator. Treat as
directional; **re-measure on a current real workflow** before leaning on any number.

## The reasoning evolution (so you don't re-walk the dead ends)

1. **Reject the merge** (above). The ~3MB cross-system axis is the smallest of three duplication
   axes (within-event, across-event, cross-system).
2. **The right primitive is content-addressing / interning** (git/Bazel/Perfetto/Parquet). Store
   each unique blob once, reference by hash. This is what `output_hash` reached for.
3. **Scope it per-run, not globally.** I (storage lens) initially leaned toward, and the
   observability lens initially proposed, a *global* shared blob store ("share the blobs, not the
   stores"). **We both walked that back.** Global sharing re-couples the TTL-cache and delete-freely-
   trace lifecycles (global GC) and loses trace portability, all to capture only the ~3MB
   cross-system win. **Per-run interning** captures the dominant within-run win, stays self-contained
   / portable / trivially-GC'd, and is reversible (promote to global later *if* cross-run dedup is
   observed). The cache keeps its own compressed copy; we accept the ~3MB.
4. **"Two artifacts" is not a smell to fix by merging.** The user asked "can one be enough?" The
   honest answer: the right unit isn't files, it's *copies of each blob*. Per-run interning gets
   each blob to one copy within a run without merging the stores.
5. **Observability lens added the orthogonal axis: write-timing / liveness.** The trace IS the event
   stream, dumped at end. Stream it instead and you get the live UI for free. The event sink replaces
   the **trace**, not the **cache** (log ≠ keyed index). This is real and good — but it's a
   **liveness** need (live UI, Task 164, Task 125), NOT a disk need.
6. **I leaned "do it all in one sweep / restructure once."** **Walked back** — both of us. The crux:
   *per-run interning is content-level and works on the current end-dumped tree, with zero span-schema
   commitment* (confirmed: interning is orthogonal to tree-vs-flat). So the disk fix does NOT touch
   the trace's shape. Therefore: ship the disk fix now on the current tree; **defer** the span model
   until the live overlay actually starts. Pinning a 5-consumer span schema before 4 of those
   consumers exist is exactly the speculative design the manifesto forbids.
7. **Final sequencing:** #382 (honest model + per-run interning, now) → streamable span-model event
   log (deferred, gated behind static Task 155 + live overlay) → global store + GC (far-future,
   gated on observed cross-run dedup). The one expensive-to-retrofit decision is "event model must be
   streamable from the start" — pay it only when liveness work begins, and record it as a bet.

## D1/D2/D3 refinements worth not re-deriving

- **D3 first-occurrence-inline ordering** (don't hoist blob table to a trailer) gives backward-only
  refs → live tailer safety AND crash-truncation self-consistency for free.
- **D2 trailer = Task 164's graceful-vs-hard-kill discriminator** (present+failed = resumable;
  absent = hard crash). Pin D2 and 164 gets failure classification for free.
- **D3 global `seq`**: liveness forces one tailable stream → single lock around (assign seq, append,
  flush) → global monotonic seq for free; per-writer buffers are out. Threads not subprocesses
  (`ThreadPoolExecutor`), so a lock suffices. Lock-first; queue+writer-thread only if contention
  observed. Flush frequently or a crash loses the tail.
- **D1 has TWO choke points**: read = `TraceTree.from_event_log`; write = the per-sub-workflow
  collector (save/restore around `engine.run`, `__trace_collector__`) must unify into span-context
  correlation. The "retry" in "retries as attempts" is ambiguous — graph-loop re-exec (≈free) vs
  internal `max_retries` (untraced today → new emit points). Be precise.
- **D1 is a shared contract**: write it once, cited by trace/cache/live-UI/164/125. Subsumes #370.

## What was done this session

- Updated **#382** in place: rescoped from "prompt duplicated 4×" to "honest event model + per-run
  interning, on the current tree, decoupled from streaming" (the now-work).
- Rewrote **`task-133.md`** into the decision record above.
- Wrote this braindump.
- NOT committed (user commits, never the agent).

## Open / to re-verify before building #382

- **Re-measure** current trace vs cache sizes + the actual cross-system overlap on a real workflow
  (all figures are illustrative/stale).
- **#357** status: code fix present (`_METADATA_KEY_SUFFIXES`) but GH issue OPEN, and the config-hash
  filter (`instrumentation.py`, exact `_source_line`) is asymmetric with the cache-key filter (3
  suffixes). Confirm before assuming saved-library caching is sound. *(Tangential to #382 but in the
  same storage area.)*
- Interning threshold (~>1KB) is a knob — tune against a real trace.
