# Task 173: Live execution overlay — UI runtime consumer

## Description

A live execution overlay in the pflow web UI: watch a workflow execute in **real time** — nodes light up
as they run/complete, with cost/output detail on demand. This is the **consumer** half of the
live-execution-overlay architecture (ADR-0008): a server-side tailer reads the incremental trace
(Task 172), pushes run events to the browser over SSE (Task 169), and the frontend renders them on the
static graph (Task 168) by joining via `NodeId = (node_id, ancestor_path)`.

## Status

done

## Completed

2026-06-29

## Priority

medium

## Problem

Task 168 shipped a **static** React Flow viewer with zero runtime data — it draws a saved workflow's
shape and nothing more. The overlay seams were deliberately reserved (a `status` prop on `memo()`'d
nodes, a ChipRail status-chip slot, a Rail run-control slot, the `web/src/api/client.ts` subscription
point), but nothing feeds them. There is no way to watch a run — *especially an agent/CLI-launched run* —
execute live. The `pflow ui` server is currently stateless, read-only GETs, in a different process from
any run.

## Solution

Observe-and-tail, decoupled by the filesystem:

- **Server-side trace-tailer:** discover the live run's incremental JSONL trace (Task 172 writes it) and
  tail it as the run progresses. Works for **any** run — agent, CLI, or UI-launched — because the run
  writes the file regardless of whether the UI is up.
- **Push over SSE:** emit run events as a message type on Task 169's vocabulary-agnostic SSE bus.
- **Frontend rendering:** thread a `status` onto the `memo()`'d node components, joining each event to its
  graph node via the existing `RFRef`/`sameRef` on `(node_id, ancestor_path)` (`port=null`); surface
  status via the reserved ChipRail chip; subscribe in `web/src/api/client.ts`.
- **Optional launch-by-spawn:** a `POST` that spawns a normal `pflow run` **subprocess** (the UI launches
  but never *hosts* the run — it stays a launcher + observer).

**Build skeleton-first:** the opening milestone is a thin vertical slice — a minimal producer emit
(top-level completions, `ancestor_path=[]`) → minimal SSE → light one node — to validate the D1 schema
and the whole pipe *before* the full producer (Task 172) is done.

## Design Decisions

- **Observe, don't host.** The run executes in its own process; the server tails its trace + may *launch*
  it via subprocess. Keeps pflow CLI-first, survives server death, sidesteps HITL coupling. (ADR-0008.)
- **File-tail transport (not POST-from-run, not pipe-only).** File-tail watches *any* run and is
  crash-safe/replayable; a pipe would only catch UI-launched runs, and we need agent/CLI runs.
- **Join externally on NodeId — never add runtime fields to GraphModel.** The graph model is
  purity-tested (`test_graph_model_purity.py`); the overlay joins runtime state onto it via `RFRef`,
  it does not mutate the model.
- **Status:** per-node `failed`/`cached`/`success` (derived from the event); `degraded` is a **run
  banner** read from `run.complete.final_status`; `running`/`pending` are **inferred** from the static
  graph (no `node.start` in v1).

## Dependencies

- **Task 172** (emit-time producer) — the incremental trace this tails. The schema (D1) is the contract.
- **Task 169** (SSE transport) — the server→browser bus; build as a vocabulary-agnostic typed-message
  bus, this task adds run-event message types. Can proceed in parallel with 172.
- **Tasks 168 + 155** (shipped) — the static viewer, the `RFRef`/`sameRef` join key, the reserved seams.

## Requirements

### Server-side tailer
- Discover the live run's trace file (newest-by-workflow-hash in `~/.pflow/debug`, or the run registers
  its path; trivial when the UI *launched* it). Tail incrementally as lines append.
- **Producer eager-`meta` write — DO THIS as a small Task 172 follow-up (discoverability gate).** Today the
  producer opens the trace file **lazily, on the first node *completion*** (`runtime/workflow_trace.py::
  _open_stream`, called from `_flush_event`). So a still-running first node (e.g. a 30 s LLM call) is
  **undiscoverable until it finishes**, and a crash mid-first-node leaves no file at all — directly
  undercutting "watch a run live." Fix: write the `meta` line **eagerly at run start** (after `only_node` is
  set) so the file exists from t=0 and the tailer can find an in-flight run immediately. **Ripple to handle
  when adding it:** `meta`-only files from crashed/empty runs would then surface to `pflow report`'s
  newest-by-mtime auto-detect (`cli/commands/report.py`) and analyze-cache's "found other traces" disclosure
  (`prompt_cache_analysis/trace_loading.py`) — review/guard those (they currently never see a contentless
  trace). Compatible with the pytest gate (it patches `_open_stream`). Surfaced by the PR #530 review;
  context also in GH #531 (related section) and `task_172/implementation/progress-log.md` (2026-06-23).
- Tolerate a crash-tail / partial file (no `run.complete`). Cross-platform file watching.
- Push each new event as a run-event SSE message on Task 169's bus.

### SSE / server
- Add run-event message type(s) over the bus; the producer (Task 172) never touches the bus.
- Any mutating/live endpoint (the launch POST, or a stateful tail) must **revisit the CORS / file-content
  exposure tripwire** at `src/pflow/ui/server.py` (currently bind-127.0.0.1, no-CORS, read-only GETs).

### Frontend
- Subscribe in `web/src/api/client.ts` (the single documented data-loading seam); components stay
  callback-free / overlay-ready.
- Join each event to its node via `sameRef` on `(node_id, ancestor_path)` with `port=null`
  (`web/src/graph/remap.ts`).
- Render node status via the reserved ChipRail status-chip slot; the Rail top slot is the run control.
  Components remain `memo()`'d.
- Derive display status (`failed`/`cached`/`success`); read the run banner (`degraded`/`failed`/`success`)
  from `run.complete.final_status`; infer `running`/`pending` from the graph.
- Do **not** surface raw `node_type` (Python class name) to agents.

### Optional launch
- `POST /api/run` spawns `pflow run <workflow>` as a subprocess; track the PID for status/cancel; the run
  is independent and survives server death; the browser re-discovers via the trace file.

## Implementation Notes

- The reserved seams are documented: `web/CLAUDE.md` ("Overlay-ready seam"), `ChipRail.tsx` (status-chip
  slot), `WorkflowNode.tsx` (leaf status badge), `src/pflow/ui/CLAUDE.md` (the `api/` contract), the
  deleted `/events` stub ("build it when a consumer exists").
- **Known v1 limitation:** for parallel/batch the overlay can't show *which* of N is running until items
  complete (no `node.start`) — a per-completion flipbook there. Acceptable for v1; the `node.start`/L2 fix
  is deferred.
- Rich detail (resolved IO, cost, tokens) comes from the event payload (`node_output`, `llm_call`);
  the detail panel can also read the post-run trace file.

## Verification

- **Skeleton milestone:** light one node end-to-end (minimal producer emit → SSE → frontend) — proves D1.
- e2e: launch a real workflow (sub-workflow + parallel batch + loop) and watch the graph light up live;
  node statuses + costs match the final `report`. Use the `screenshot-pflow-web-ui` skill to verify.
- The optional launch POST spawns an independent run that keeps going if the server is killed.

## References

- **ADR-0008** (`context/adr/0008-live-execution-overlay.md`); **D1 schema**
  (`.taskmaster/tasks/task_133/design/d1-event-schema.md`).
- Task 168 (static viewer) `task-review.md`; Task 169 (SSE transport) `task-169.md`; ADR-0005 (web-ui
  server delivery); ADR-0003 + `src/pflow/core/workflow/graph/CLAUDE.md` (Runtime Overlay Join Contract).
- Frontend: `web/src/api/client.ts`, `web/src/graph/remap.ts` (`sameRef`),
  `web/src/components/nodes/{WorkflowNode,ChipRail}.tsx`, `web/CLAUDE.md`.
- Server: `src/pflow/ui/server.py` (CORS tripwire), `src/pflow/cli/commands/ui.py`.
