# The UI server adds a stateful SSE push channel for agent↔browser interaction (and the run-overlay's transport)

**Status:** accepted — builds on ADR-0005 (the "someday" it anticipated); coordinates with the deferred run-overlay (Task 133) only at the message-envelope seam.

The `pflow ui` server (Task 168) was stateless and read-only: every request a fresh re-parse, no side effects, no CORS, bound to `127.0.0.1` (the `server.py` security note + `ui/CLAUDE.md`). Task 169 adds its first **stateful, push-capable** layer — an **ephemeral, in-memory, per-process** connection registry plus a bounded interaction ring, served over **Server-Sent Events** (server→browser) alongside a few plain JSON POST/GET endpoints (browser/CLI→server). This lets an agent **Point** at a target in the user's open Viewers and **Watch** the user's recent interactions, and it is the same transport the deferred live-run overlay (Task 133) will ride — realizing the "SSE for runtime events" that ADR-0005 named as the reason a server (not a static export) was chosen.

The SSE **message envelope is deliberately vocabulary-agnostic** (`{type, …payload}`): Task 169 defines interaction message types; the overlay adds run-event types later over the same pipe. This ADR **does not define a run-event schema** — that stays pinned against the overlay's own consumers (Task 133, D1), so the two tracks share only the envelope seam. State is added **for live connections + the interaction ring only**; graph data stays stateless-per-request. The state is ephemeral (a restart drops connections and the ring) — the only sane behavior for a local, single-user server — so **no persistence layer** is introduced.

## Considered options

- **WebSocket instead of SSE** — rejected. Nothing needs a bidirectional socket: commands flow down over SSE, events/visibility up over plain POST. SSE is the shape ADR-0005 named; a later genuinely-bidirectional need (Task 125 approval gates) can add WS without disturbing this.
- **Stay stateless; poll for commands** — rejected. A poll cannot *push* a focus into an already-open page, and command-polling is laggy and wasteful; the overlay genuinely needs push.
- **Define the run-event schema now** — rejected. Task 133's consumers don't exist yet, and pinning it early over-constrains. The generic envelope keeps run events purely additive.
- **Persist the connection/interaction state** — rejected. Unnecessary for a local single-user server; restart-drops-all is correct, and persistence would be the kind of layer this codebase deletes.
- **Browser→server apply-acknowledgments** (the browser confirming a Point was *shown*) — rejected for v1. The human is in the loop (it's a conversation), and "the server validates the target up front + the browser always reveals a resolvable one" makes the command's report honest without an ack round-trip. Additive later, only for autonomous/no-human flows or the overlay. *(The "additive later" case arrived for narration playback — ADR-0012's beacons; Point commands themselves remain ack-less.)*

## Consequences

- The `server.py` security note must be **extended, not merely preserved**: it still binds `127.0.0.1` with no CORS, but now also records that mutating POSTs require `Content-Type: application/json` (so a cross-origin page is forced into a failing CORS preflight) and that the worst-case cross-origin write is benign (focusing a node in the user's own Viewer — no file/system effect). **Any future mutating or live-run endpoint must revisit this exposure.**
- Concurrency rests on a single uvicorn process/event loop plus an **async-only invariant** for every handler that touches the hub → no locks. A sync handler touching the hub would silently break it (the invariant is documented at the hub).
- The overlay can ride this transport without re-litigating the channel; the envelope is the only coordination point between the two tracks.
- Recorded so the server is not later "simplified" back into a stateless read-only emitter — which would re-break the interaction channel and the overlay seam this shape exists to provide. The mirror of ADR-0005's own "don't simplify this into a JSON/static-HTML emitter" caution.
