# Handoff to Task 169 — you are the transport for the live execution overlay

> **Provenance / trust boundary.** This came out of a live-overlay scoping session with the task
> owner on **2026-06-18**, in the `feat/unified-node-storage` worktree (Task 133). It **complements**
> `task-169.md` — it does **not** override it. Codebase facts below were established by file-grounded
> search on 2026-06-18; **re-confirm `file:line` before relying.** Where I mark something
> "user-confirmed," the owner decided it this session; "recommendation" is mine and still open.

## Why you're being pulled forward

Task 169 (the SSE channel) was gated on "build it when a consumer exists." **That consumer now
exists in concept:** the **live execution overlay** for the web UI (informally "the runtime for the
UI"), being scoped under Task 133. Your SSE pipe is the transport that overlay rides. So 169 is no
longer speculative plumbing — it has a real, named consumer.

## The architecture you plug into (user-confirmed this session)

- **Observe-only, with launch-without-owning.** Workflows run as ordinary `pflow run` processes
  (CLI / agent / MCP, or a thin *server-spawned subprocess*). The UI server **never hosts
  execution** — it *observes*, and may *launch* by spawning a subprocess, but the run lives in its
  own OS process. This preserves pflow's CLI-first model and keeps the server simple.
- **Carrier = A1: tail the incremental trace.** As a run executes it appends its trace to disk
  (Task 133 **Phase D** — emit-time/incremental append). The UI server **tails that file and fans
  it out over your SSE channel.** One stream serves the live overlay *and* the post-hoc `report`
  *and* (later) resume. We rejected a second parallel "lifecycle log" (A2) to avoid two event
  streams.

The full pipeline:

```
[run appends incremental trace]  →  [UI server tails the file]  →  [169 SSE bus pushes to browser]
   (Task 133 Phase D)                  (overlay's tailer)            (YOUR layer)
        →  [frontend renders, joining on (node_id, ancestor_path)]
```

## Your boundary — the clean split

- **169 owns:** SSE connection management + a **vocabulary-agnostic typed-message envelope**
  (register a message type, push a message, fan out to connected browsers) + your interaction
  message types (agent point/focus, the user-event watch buffer) + the security/CORS revisit.
- **The overlay owns (NOT you):** the run-event *schema* (Task 133 D1), the server-side trace-tailer
  that produces run-event messages, and the frontend rendering.
- **The single seam between us:** the **SSE message envelope**. Pin that and the two tracks run in
  parallel — exactly your spec's own framing ("same pipe, different vocabulary; Task 133 is not a
  dependency").

## Three conditions so 169-first pays off (recommendation)

1. **Build the bus vocabulary-agnostic** — do not hardwire it to interaction messages. The overlay
   adds run-event message types over the same pipe later. (Your spec already commits to this; hold
   the line.)
2. **Don't over-build the interaction features as an overlay blocker.** The bus + a minimal
   interaction proof is enough to unblock the overlay; flesh out point/focus/watch on your own track.
3. **The hard, uncertain part lives on the overlay side** (the incremental trace + the run-event
   schema), not your pipe. So the **SSE envelope is the one thing to pin with the overlay early**;
   everything else you can build independently.

## Verified landscape (codebase search 2026-06-18 — re-confirm)

- **Server:** `src/pflow/ui/server.py` — Starlette, **stateless per request, read-only GETs only**
  (`/api/catalog|graph|source|version`). You add the **first stateful, push** piece.
- **Security tripwire — load-bearing:** `server.py:279-287` binds `127.0.0.1`, sets **no CORS**,
  every request is a read-only GET. Any push/mutating endpoint (your SSE stream; a future
  spawn-a-run POST) **must revisit this file-content exposure.**
- The `/events` SSE stub was **deliberately deleted** during Task 168 ("no dead routes — build it
  when a consumer exists"). That's you, now.
- **Delivery decision: ADR-0005** — a local ASGI server was chosen *specifically because* "a browser
  on `file://` can't tail a growing Run log, so live streaming needs a server." It names SSE for
  runtime events and WebSocket later for Task 125 approval gates.
- **Frontend seam:** `web/src/api/client.ts` is the single data-loading point; the `events.ts`
  subscription client **does not exist yet** — that's where browser-side SSE plugs in. (Frontend
  source is `web/` at the **repo root**, not under `src/pflow/`; build output → `src/pflow/ui/static/`.)
- **Join contract (read-only, shared — do NOT change unilaterally):** `RFRef` /
  `(node_id, ancestor_path)`, the "Runtime Overlay Join Contract" in
  `src/pflow/core/workflow/graph/CLAUDE.md`; frontend `sameRef()` in `web/src/graph/remap.ts`. The
  GraphModel is purity-tested — runtime state joins **externally**, never as fields on the model.
- **Why a file-tail, not the in-process progress callback:** the run and the `pflow ui` server are
  **different processes**. The progress callback (`__progress_callback__`) is an in-process Python
  closure — invisible to the server. The cross-process carrier is the trace file (A1).

## Status of the surrounding pieces

- **Task 168** (server + static viewer + reserved overlay seams): shipped.
- **Task 133 A–C** (on-disk JSONL trace transport): done. **Phase D** (incremental/emit-time append —
  the overlay's producer): pending, being scoped now.
- **Task 169** (you): not started.
- **The live-overlay task itself:** not yet created — scoping in progress. An **ADR** is planned for
  "overlay tails the incremental trace over SSE; the UI server observes/launches but never hosts
  execution."

## Open / not yet decided (don't assume)

- The run-event **schema (Task 133 D1) is NOT pinned** yet — it's the next deep-dive. Your envelope
  must not bake in run-event field assumptions.
- Whether the overlay ships before/after your full interaction feature set — independent tracks;
  coordinate **only** at the SSE envelope seam.

## References

- `.taskmaster/tasks/task_169/task-169.md` — your spec.
- `context/adr/0005-web-ui-local-server-delivery.md` — why a server, SSE for runtime events.
- `src/pflow/ui/server.py`, `src/pflow/ui/CLAUDE.md` — the server + HTTP contract.
- `web/src/api/client.ts`, `web/CLAUDE.md` — the frontend data seam (where `events.ts` goes).
- `src/pflow/core/workflow/graph/CLAUDE.md` — the `(node_id, ancestor_path)` join contract.
- Task 133 (the run-event schema half): `.taskmaster/tasks/task_133/` — scoping in the
  `feat/unified-node-storage` worktree.
