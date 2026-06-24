# Task 173 — Live Execution Overlay — Implementation Plan

> Status: DRAFT for review. Decision log + workstreams + build order. Verified against `main`
> via five parallel codebase surveys (2026-06-23). File:line anchors are as-surveyed — re-confirm
> before editing (the 133→172→169 arc moved fast).

## Decision log

| # | Decision | Verdict | Rationale |
|---|---|---|---|
| D1 | Running-state representation | **`node.start` via re-flush** (user-confirmed) | Reuse the shipped `mark_last_event_failed` re-flush + reader's last-wins-by-`id` dedup. Add `"running"` to the per-node `status` enum. Flush a `running` line at node start; re-flush the SAME `id` at completion with the terminal status. Consumer = pure last-wins state machine, NO topology inference. |
| D2 | Transport | **Server tails the trace file** (ADR-0008, mandated) | NOT "run POSTs to server" (ADR-rejected: server-down-at-start, no mid-run replay, lifecycle coupling). The run only writes its file; `pflow ui` discovers + tails it. |
| D3 | Parallel-batch item granularity | **Stays flipbook** (deferred, unavoidable) | The no-lock owner-thread rule forbids worker threads emitting to the run-scoped collector. Batch *host* lights `running`; items flip on completion. Batch-item promotion stays deferred. |
| D4 | Launch POST (`POST /api/run`) | **DEFER** (recommend; user to veto) | Optional in the spec. It's the only mutating endpoint → forces the CORS/exposure re-evaluation; core value (observe agent/CLI/UI runs) needs only discovery+tail. Browser re-discovers any run via the trace file regardless. Natural future home = a "Run" button on the global dashboard (D6). |
| D5 | Catch-up on subscribe | **Snapshot-then-stream** | On SSE subscribe, tailer reads the whole current file → sends ONE consolidated snapshot (all current node states), then streams incrementally. Handles "open UI mid-run" replay AND avoids the 64/conn queue overflow from replaying N individual events of a long run. |
| D6 | Run-discovery / navigation scope | **Core + in-context surfaces + global dashboard** (user-confirmed) | One shared `/api/runs` data layer (from the trace dir) + the live overlay + replay-a-finished-run, since **live and historical are the same render path**. Surfaces: (1) live overlay on the open Viewer; (2) catalog "● running" indicator; (3) per-workflow run history + replay in the Viewer; (4) a dedicated global runs-dashboard page (all runs, live+historical, click-to-open). All pure observation (read-only over the trace dir) — ADR-clean. |
| D7 | Run liveness signal | **File-based heuristic, no process tracking** | A run is `live` = has `meta` (eager-meta, t=0) + NO `run.complete` + fresh mtime. Crashed = incomplete + stale mtime → "interrupted". `node.start` (A2) appends at every node boundary, sharpening freshness. Runs are keyed by the trace dir, NOT the catalog → ad-hoc `pflow run unsaved.pflow.md` still appears. |

## Architecture (the pipe)

```
pflow run (agent / CLI / UI-spawned — its own process)
  └─ streams JSONL trace → ~/.pflow/debug/workflow-trace-<hash>-<name>-<ts>.json   [shipped, Task 172]
     + NEW: a `running` event line per main-thread node at start (D1)
     + NEW: `meta` written EAGERLY at run start (discoverability gate)

pflow ui server (src/pflow/ui/server.py — separate, long-lived, NOW stateful)
  └─ on GET /api/events?workflow=X subscribe:
       start (or reuse) an async Tailer for X's newest live trace file
       Tailer: read raw lines (NOT load_trace_file) → maintain md5→blob map →
               substitute_refs forward-only → key joined index by `id` last-wins →
               emit run-events: hub.broadcast(workflow_key, {type:"run-event", ...})
       on run.complete line → broadcast {type:"run-complete", final_status}

browser (web/ — existing Task-168 canvas, ADDITIVE)
  └─ events.ts: +1 dispatch arm for "run-event"/"run-complete"
     status map keyed on stable RFRef → restyle pass (like applyFocus) → memo'd node lights
     ChipRail status chip (leftmost) + node status class; Rail top slot = run banner/control
```

## Workstream A — Producer (`src/pflow/runtime/`)

### A1. Eager `meta` (discoverability gate)
- Today `_open_stream` (`workflow_trace.py:773-800`) opens lazily on first node completion (`_flush_event`→`_open_stream`, `:837`); `meta` written at `:800`. A still-running first node (30s LLM) is undiscoverable; a crash mid-first-node leaves no file.
- **Change:** call `_open_stream()` at run start so `meta` (and thus the file) exists from t=0. `_open_stream` is already idempotent (guard `:786`) and writes `meta` as its last act.
- **Ordering caveat (verified):** `self.trace.only_node` is stamped at `engine.py:650` (`self.trace.only_node = self.only_node`). Eager `_open_stream` MUST run AFTER that stamp, or `--only` runs write `meta` with `only_node=None` (poisons the snapshot-rejection). Hook the eager open right after the `only_node` stamp on the owner thread.

### A2. `node.start` via re-flush (D1)
Two emit points; both flush a `{kind:event, status:"running", node_id, node_type, ancestor_path, port:null, id, seq, parent_id, timestamp}` line. The terminal line at step 16 re-flushes the SAME `id` → reader last-wins collapses it (zero reader changes — `mark_last_event_failed` proves the path).

- **Leaf nodes:** reserve `seq`/`id` at step 8 (`engine.py:1086`, `call_start_callback` — already the pre-exec point where `node_id`+`node_type` are known and progress fires `node_start`). Stash the reserved id on the engine local (next to `host_frame`, `engine.py:1022`); thread it into the step-16 `record_node_execution` so the completion line reuses it instead of taking a fresh `seq`.
- **Sub-workflow hosts:** `descend()` (`workflow_trace.py:751-764`, called pre-order at `workflow_executor.py:432-433`) already reserves the host's `seq` in a `_HostFrame`. Flush the `running` line there using the frame's seq. Step 16 already reuses the frame (`engine.py:1202`).
  > NOTE: A2 ships as a distinct `node.start` line KIND (not `event`+`status:running`) — see "Slice status".
- **SEQ-RESERVATION WRINKLE → RESOLVED to option (a)** (deep-review C1, 2026-06-23). The shipped guard
  (`begin_node` skipped for `WorkflowExecutor` at step 8.5) is correct and already half the answer. Add
  host `node.start` by having **`descend()` ALSO flush a `node.start` disk line using the `_HostFrame` it
  already reserves** — NO contract change, NO double-reservation, and the loop re-descent / after-ascend /
  same-id-child cases are already pinned. The earlier lean toward option (b) (step-8 reserves for all +
  `descend` reuses) was WRONG: `descend()` runs *inside* `node._run` at step 9 (`workflow_executor.py:433`),
  which the engine can't reach to thread a pre-reserved seq into → (b) needs a new engine→node channel AND
  changes `descend`'s contract for no benefit. Gate with the three host-frame pins:
  `test_looped_subworkflow_re_descends_distinct_seq_balanced_stack`,
  `test_host_recorded_after_ascend_with_frame_keeps_children_linked`,
  `test_subworkflow_child_id_collision_does_not_corrupt_top_level_status`. **Sequence host `node.start`
  BEFORE the build-order sub-workflow checkpoint** (deep-review W3), or the host shows dead/pending until
  the whole sub-workflow completes — the exact UX bug the overlay exists to fix.
- **Parallel-batch items: NO start line** (D3). Worker threads must not touch the run-scoped collector (`_assert_owner_thread`, `workflow_trace.py:722-734`). Only main-thread nodes + hosts get `running`.
- **Cost:** one small extra line per main-thread node on disk (no payload/blobs on the running line). Reader dedups; complete traces never surface `running` (always superseded). `running` only meaningfully appears in live/incomplete reads — which post-hoc consumers already reject as truth.

### A3. Schema / D1 update (co-finalize per kickoff brief's schema authority)
- `status` enum: `running | success | cached | failed` (was `success|cached|failed`).
- Document: `running` is emit-at-start, superseded by terminal at completion (same `id`, last-wins); only surfaces in live/incomplete reads; not emitted for parallel-batch items.
- Update `.taskmaster/tasks/task_133/design/d1-event-schema.md` §c + the consumer-derivation section. Pin against the shipped overlay (build-order step 4).

## Workstream B — Ripple guards (eager-meta fallout)

A `meta`-only file now appears from a run that crashes before any node completes (and from any in-flight run). Guard the two post-hoc consumers:
- **`cli/commands/report.py:41-45`** — UNGUARDED raw mtime glob of `workflow-trace-*.json`, takes newest. WILL pick a `meta`-only / in-flight file. **Guard:** route through `_iter_workflow_traces` or skip files with no `run.complete` / `final_status=="incomplete"`.
- **`prompt_cache_analysis/trace_loading.py`** — already routes through `_iter_workflow_traces` (incomplete→failed bucket, won't shadow a good trace). One nit: `_autoload_selection_with_disclosure` (`:234-256`) could mislabel a `meta`-only file as "failed run" when it's the sole trace. **Guard:** distinguish `incomplete` from `failed` in the disclosure label.
- Invariant to preserve: `_iter_workflow_traces` MUST NOT filter on `final_status` (`workflow_trace.py:109-112`) — guard at the consumer, not the iterator.

## Workstream C — Server tailer + SSE + `/api/runs` (`src/pflow/ui/`)

- **`/api/runs` data layer (the shared core for all D6 surfaces):** `GET /api/runs` → all runs from `~/.pflow/debug`: `[{run_id, workflow_name, workflow_path, start_time, final_status|null, live: bool, trace_file}]`. Reads the cheap `meta` head + checks for a `run.complete` tail + mtime (D7 liveness). `GET /api/runs?workflow=X` filters by path/hash (per-workflow history). This is the single source of run truth; the catalog indicator + per-workflow history + global dashboard are all views over it.
- **Discovery & run selection:** `GET /api/events?workflow=X` defaults to X's newest **live** trace; `&run=<run_id>` pins a specific (historical) run to replay. Pick the file by filename timestamp / run_id, don't force a full `load_trace_file` parse on a growing file (`_iter_workflow_traces` parses each — glob+pick is lighter for the live path). Eager-meta makes the file exist from t=0. **v1 limit:** concurrent runs of the same workflow → `/api/runs` lists all; the overlay defaults to newest, user can pick another via history.
- **Tailer (the one honest deep module):** async task per watched workflow.
  - Read RAW lines (`json.loads`), NEVER `load_trace_file`/`reconstruct` (they strip `ancestor_path`/`port` — the join keys; pinned by `test_streamed_wire_is_joinable...`).
  - Only parse complete lines (end in `\n`); re-read the tail next tick (truncated final line is NORMAL, not corruption).
  - Maintain `md5→value` blob map; `core.trace_io.substitute_refs(event, blob_map)` forward-only (no `blobs` trailer).
  - Index joined events by `id`, last-wins (re-flush correction / running→terminal).
  - Cross-platform file watch (poll-based is simplest + robust; avoid OS-specific watchers for v1).
- **Snapshot-then-stream (D5):** on subscribe, send one consolidated snapshot of current node states, then stream increments. Avoids 64/conn queue overflow (`_CONNECTION_QUEUE_MAX`, `server.py:74`) on mid-run replay of a long trace.
- **SSE emit:** `hub.broadcast(workflow_key, {type:"run-event", ref:{node_id, ancestor_path, port:null}, status, ...})` and `{type:"run-complete", final_status}`. The bus is vocabulary-agnostic; `broadcast` (`server.py:124`) needs no change. Handler touching the hub MUST be `async def` (invariant `server.py:89-94`).
- **Lifecycle:** start tailer on first subscribe for workflow X, share across its viewers, stop when last disconnects.
- **Security tripwire (`server.py:606-617`):** the stateful tail rides the existing read-only GET `/api/events` (EventSource unreadable cross-origin — posture preserved). NO new ingest endpoint for the core overlay. The launch POST (D4, deferred) is what would force a real re-evaluation.
- **Run-event payload (v1):** lightweight — ref + status + small summary (duration, cost_usd). Rich detail (resolved IO, tokens, llm_call) is build-out (step 3); keep blobs OFF the live wire (detail panel fetches on demand or reads the post-run trace).

## Workstream D — Frontend (`web/`, ADDITIVE to Task-168 canvas)

- **Status type:** add `status?: NodeStatus` (`"pending"|"running"|"success"|"cached"|"failed"`) to `LeafData` (`flow.ts:77-106`); seed default in `buildFlow` (alongside `dimmed:false`, `flow.ts:530`). Add to group/io data too (all node kinds are `memo()`'d).
- **Subscription:** add `"run-event"`/`"run-complete"` arms to the `if/elif` dispatch in `events.ts:81-92`; add a handler bag (parallel to `PointHandlers`) + a `RunEvent` type in `types.ts` + a type-guard. The data-loading seam comment (`client.ts:1-3`) anticipates exactly this.
- **Status map → nodes:** keep a `Map<RFRef-key, status>` (key on the stable structural ref, NOT the positional flat id — `remap.ts`). Resolve to flat id via `flatIdForRef(graph, ref)` (`remap.ts:26-28`).
- **Restyle pass (clone `applyFocus`):** a new pass that rebuilds `data` ONLY for nodes whose status changed (preserve object identity otherwise → `memo()` skips). Layer it in the decoration effect (`useWorkflowGraph.ts:313-393`) AFTER `applyFocus` (`:319`), BEFORE `setNodes` (`:348`). No ELK re-layout. Do NOT add `status` to the `updateNodeInternals` dep array (`WorkflowNode.tsx:226-228`) — status doesn't move handles.
- **Render:** ChipRail status chip leftmost (insert after `<span className="chip-rail">`, `ChipRail.tsx:39`, before the loop chip; update the null-guard `:37`); + a `status-running`/`-failed`/etc. class in the `classes` array (`WorkflowNode.tsx:249-256`) for border/glow.
- **Run banner / control:** Rail top slot (`Rail.tsx:76`, before `RailSearch`; reuse `RailButton`; update early-return `:73`). Banner reads `run-complete.final_status` → `success|degraded|failed`.
- **`pending`/`running`/`done`:** pending = default (no event yet); running = `status:"running"`; done = terminal. NO topology inference (the payoff of D1).
- **Do NOT surface `node_type` raw** (Python class name) to agents in the detail panel.

## Workstream E — Run-discovery surfaces (frontend, D6)

All consume the shared `/api/runs` data layer (Workstream C) and the same overlay render path. Each is its OWN real-browser-verification surface (the real cost of D6 — the data/render are shared, the views multiply verification).
- **Catalog "● running" indicator:** `CatalogView` cross-references `/api/runs` (filter `live`) → a badge per workflow. Source of run truth = `/api/runs`, NOT the catalog list (so ad-hoc runs of unsaved files are reflected where matchable).
- **Per-workflow run history (in the Viewer):** a history list/dropdown in `GraphView` from `/api/runs?workflow=X`; selecting a past `run_id` re-subscribes `/api/events?workflow=X&run=<id>` → replays that finished run's final state onto the graph (same join, frozen — no live tail). Default = newest live run.
- **Global runs dashboard (new view):** a dedicated page listing ALL runs (live + historical) across workflows, click-to-open (→ GraphView with that `workflow`+`run`). Add as a third screen alongside CatalogView/GraphView (`App.tsx` routes on URL param). **Live updates:** poll `/api/runs` on an interval for v1 (simple, robust); a workflow-agnostic SSE "runs-changed" feed is a later refinement (the current SSE bus is per-workflow-keyed).
- Reuse `RailButton`/existing chrome patterns; keep it read-only (no launch in v1, D4).

## Build order (skeleton-first; prove the pipe before the surfaces)

1. **Thin vertical slice (proves D1 + the whole pipe):** A1 eager-meta + A2 leaf `running`/terminal for top-level nodes → C tailer+SSE (snapshot+stream) → D light ONE node end-to-end on the open Viewer. Validates schema + join + pipe.
2. **Real "done" bar:** ONE sub-workflow (host + flat children join via non-empty `ancestor_path`) AND ONE parallel batch (host lights running, items flipbook) end-to-end through the overlay.
3. **`/api/runs` + replay:** the shared data layer + run selection (`&run=`) + replay-a-finished-run (reuses the overlay join; "view a past run" = tail a file that already has `run.complete`).
4. **Run-discovery surfaces (E):** catalog running-indicator → per-workflow history → global dashboard. Browser-verify each.
5. **Build out:** detail panel (resolved IO, cost, tokens from event payload / post-run trace), run banner, loop + slow-node observation.
6. **Pin D1** once the shipped overlay has validated the consumer-derivation contract.

## Verification (brief Q4 — build own loops, escalate sparingly)

- Capture `make test` / `make check` baseline FIRST (named pass/fail), re-run after, report delta.
- Write throwaway `*.pflow.md` (sub-workflow, parallel batch, loop, a slow node to observe `running`); run them to generate live traces; tail + render.
- **Real-browser verification is MANDATORY** (CLI-invisible; a green unit test over a wrong assumption reverted a #529 attempt). Use the `screenshot-pflow-web-ui` skill to capture overlay state.
- Producer join guarantee: re-run `test_runtime_event_refs_join_onto_the_static_graph` after ANY producer/renderer change.
- Closing: tool-elevation verdict (discard vs. elevate each throwaway) recorded in `task_173/task-review.md`.

## Terminology (CONTEXT.md)

`task-173.md` says "watch a workflow execute in real time" — but **"Watch" is already a glossary term** (agent reading user interactions) and "Auto-update" is the viewer watching the source file. The live overlay is a THIRD watching concept (user watching a *run* execute). Propose: add **"Overlay"** (live run-state drawn onto the static canvas, joined by NodeId) as the canonical noun + a "Watch vs Overlay vs Auto-update" ambiguity note. Avoid calling the overlay "watch." (User to confirm the term.)

## Slice status — DONE & browser-verified (2026-06-23)

Build-order **step 1 (thin vertical slice) complete and validated in a real browser.** Refinement vs.
the approved D1: `node.start` ships as a **distinct line kind** (reader-ignored, tailer-only), NOT
`event`+`status:running` — overloading `event` broke raw-line-count tests and muddied "`event` =
completion"; the distinct kind is back-compat (all readers/tests green) and matches D1's own naming.
The seq-reuse + last-wins thesis is unchanged.

Shipped in the slice:
- **Producer:** eager `meta` at run start (`engine.run` depth-0, after `only_node`), `node.start` via
  `begin_node` (top-level + nested leaves; hosts/batch-items deferred). Files: `workflow_trace.py`
  (`begin_node`/`start_streaming`), `engine.py` (step 8.5 + frame threading), `trace_io.py` (skip-arm).
- **Server:** `src/pflow/ui/run_tailer.py` (discover-by-meta + raw read + batched run-events +
  snapshot), wired into `server.py` `_Hub` (ref-counted tailer per workflow_key) + `events()`.
- **Frontend:** `status` on `LeafData`, `refKey`/`applyStatus` restyle pass (focus.ts), `run-*` SSE
  arms (events.ts), `runStatus`/`runBanner` in GraphView, status rings + banner CSS.

Verified (real browser, `screenshot-pflow-web-ui`): **running** (blue pulse mid-flight), **failed**
(red + "Run failed" banner), **success** (all green + "Run success · 3 nodes"). Success screenshot
opened AFTER completion → also proves **replay-a-finished-run** (one render path). Producer trace
confirmed through the real engine (3 node.start + 3 event, ids reused, seqs contiguous, run.complete).

Quality gates: `make test` 8119 passed (= baseline, no regressions); `make check` clean (mypy 238
files); frontend `vitest` 535 passed + strict `tsc` clean. Test artifacts: `scratchpads/.../verify/`.

NOT yet built (next phases, in order): **host `node.start` via option (a)** (`descend()` flushes its own
start line — see the A2 wrinkle resolution) + the **checkpoint** (one sub-workflow + one parallel batch
end-to-end); analyze-cache **R6** label (deferred, cosmetic); **`/api/runs`** + replay + the 3 discovery
surfaces (E) + `&run=` pinning; the **detail panel**; **pin D1**; the **tool-elevation verdict** +
**docs/guide** update (S-d). The slice's hardening fixes (R1–R5, R7) and its committed tests (R8) are
DONE — see the Deep-review findings status below.

## Deep-review findings (2026-06-23, 4-agent: plan / concurrency / silent-failures / impact)

> **STATUS (2026-06-24): R1, R2, R3, R4, R5, R7 and the owed tests (R8) are DONE** (the hardening pass —
> see progress-log). **R6** (analyze-cache mislabel) is deferred (cosmetic; selection is already correct).
> Suggestions S-a (`&run=` pin path) and S-d (docs) fold into the named next phases; S-b/S-c/S-e are
> nice-to-haves. The findings are kept below as the rationale record.

Verdict: **no criticals in the shipped slice's happy-path correctness; `begin_node` is provably
thread-safe** (concurrency review constructed no worker-thread path to the run-scoped collector — workers
route to `_execute_single_node` (no `begin_node`) or a buffer collector). The slice foundation is sound.
Findings below, deduped, severity-ordered, tagged **[SHIPPED bug]** (fix the slice) vs **[PLAN gap]**
(fold into a phase). Reviewer cross-checks noted.

**Critical**
- **R1 — Join has NO miss-detection, and the join pin is BLIND to `node.start`** [SHIPPED bug; fix now].
  `test_runtime_event_refs_join_onto_the_static_graph` only iterates `kind=="event"`, but `node.start`
  carries its OWN independently-derived `ancestor_path`/`port` and lights the *running* state — a
  `node.start`-only drift passes the pin and silently never lights. Also nothing consumer-side surfaces a
  status entry that joins to no node. Fixes: (a) extend the pin to `kind in ("node.start","event")`;
  (b) add a dev-only `console.warn` for `refKey`s in the status map that resolve to no rendered node
  (`flatIdForRef` already exists). Do BEFORE the sub-workflow/batch checkpoint, where non-empty
  `ancestor_path` drift first becomes possible. (silent-failures C1; the highest-value finding.)
- **R2 — `discover_live_trace` picks newest-by-mtime regardless of `run.complete`** [SHIPPED bug].
  A finished run (newer mtime) can shadow a still-live one → the overlay tails the wrong file. Fix: prefer
  a *live* file (has `meta`, NO `run.complete`) before ranking by mtime; fall back to newest-overall only
  when none is live (D7 liveness). Eager-meta makes multiple matching files the COMMON case, not an edge.
  Ties to the `&run=` pin path (S-below). (plan C2.)

**Warnings**
- **R3 — Tailer does blocking file I/O on the event loop** [SHIPPED bug]. `_poll_once` (glob/stat/open
  every 0.25s) runs ON the asyncio loop, violating the codebase's `asyncio.to_thread` rule (`command()`
  follows it). A large `~/.pflow/debug` stalls ALL viewers' SSE/keepalive/cleanup. Fix:
  `await asyncio.to_thread(self._poll_once)` but KEEP `broadcast` (loop-affine `put_nowait`) on the loop —
  pull the broadcasts out of `_poll_once` so they don't run in the thread. (concurrency W1.)
- **R4 — `_read_new` decodes with `errors="ignore"` on byte-offset reads** [SHIPPED bug]. A multibyte char
  split across a poll boundary is PERMANENTLY lost (offset advances past it) → a non-ASCII `node_id`
  sporadically fails to light (feeds R1). Fix: buffer raw BYTES, split on `b"\n"`, decode only complete
  lines (or an incremental decoder). (silent-failures W3.)
- **R5 — `report.py:41` no-arg auto-select** [PLAN gap, Workstream B]. Confirmed by THREE reviewers as the
  ONLY unguarded newest-by-mtime selector. Eager-meta → it now picks an in-flight/crashed `meta`-only file
  over the last good run → empty report ("incomplete, 0 nodes"), exit 0, no error. Fix: skip
  `final_status=="incomplete"`, prefer newest complete; if none, a real "no completed trace" message.
- **R6 — analyze-cache mislabels a meta-only trace "(failed run)"** [PLAN gap, Workstream B]. **W2 RESOLVED
  to the milder case** (silent-failures + impact verified against code): a meta-only file loads as
  `final_status="incomplete"` → the *failed* bucket (NOT "successful" as the plan reviewer first feared) →
  selection stays correct, only the disclosure LABEL is wrong. Fix: distinguish `incomplete` from `failed`
  in `_autoload_selection_with_disclosure`. Low impact (cosmetic).
- **R7 — snapshot `put_nowait` lacks the `QueueFull` guard `broadcast` has** [SHIPPED bug, narrow].
  `server.py` snapshot enqueue can raise `QueueFull` into the SSE generator → hard stream abort (vs.
  `broadcast`'s graceful eviction). Reachable only if a fresh conn's queue is already near-full (reconnect
  storm). Fix: 2-line try/except around the snapshot put, mirroring `broadcast`. (silent-failures W4.)
- **R8 — Zero committed tests for the slice** [owed before merge]. The no-lock safety is ROUTING-based and
  untested — a future refactor making a worker call `_execute_node` would silently re-introduce the race.
  Owe: (i) parallel-batch-of-sub-workflows under a streaming run-scoped collector asserting no
  `RuntimeError` + seq contiguity; (ii) `report.py` skips an `incomplete` trace for an older complete one;
  (iii) collector `begin_node` (disk-only line, seq reuse), reader skip-arm, tailer, frontend overlay pass.

**Suggestions (fold into phases)**
- **S-a — `&run=` pinning needs its own tailer code path** (plan S1): the shipped `_poll_once` always
  switches to `discover_live_trace`'s newest; a pinned historical run must NOT be yanked by a new live run
  starting. Build in Workstream E with R2.
- **S-b — Banner "K of N lit" cross-check** (silent-failures S1): derive a joined-node count and compare to
  `run.complete.nodes_executed` — a free in-band join-miss signal (complements R1).
- **S-c — Crash-before-first-node manual scenario** (plan S2 / silent-failures): one throwaway workflow
  whose first node crashes/Ctrl+C — exercises A1's payoff AND the R5/R6 guards together.
- **S-d — Docs/guide phase** (plan S3): once the overlay ships, update `web/CLAUDE.md` "Overlay-ready seam"
  (currently "reserved/future") + any `pflow guide` content. Not currently a phase.
- **S-e — `release_tailer` fire-and-forget cancel** (concurrency S1): add a one-line comment that NOT
  awaiting the cancelled read-only task is deliberate.

## Risk register

- **Silent join failure (#6 trap):** producer `ancestor_path` vs renderer `RFRef.ancestor_path` are independent derivations; drift = node never lights, nothing raises. Pinned by `test_runtime_event_refs_join_onto_the_static_graph` — re-run on any change to either side.
- **Reuse `load_trace_file` for the tailer** = strips the join key. Read RAW. (Pinned-by-contrast.)
- **Append-without-dedup in the SSE consumer** = duplicate nodes + dead-end shown as success. Key on `id` last-wins.
- **64/conn queue overflow** on mid-run replay → viewer evicted. Mitigated by snapshot-on-subscribe (D5).
- **Host seq double-reservation** (A2 wrinkle) → break host-frame pins. Resolve with the three host-frame tests as the gate.
- **Concurrent runs of same workflow** → newest-wins discovery picks one (v1 limit, documented).
