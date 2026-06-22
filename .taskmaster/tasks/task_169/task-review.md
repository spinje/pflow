# Task 169 Review: Agent↔Browser Interaction Channel — Point & Watch

## Metadata
- **Implemented:** 2026-06-20/21. **PR #527** (open, not merged). Commits: `04faa88e` (implementation) + `378cd952` (post-review fixes).
- **Trust boundary:** the bulk of the implementation was authored by another agent (its phase-by-phase journey is in `implementation/progress-log.md` — **read it for the "why it happened that way"**). This review's author owns, first-hand and **[verified]**: the design + plan, two 4-agent deep-reviews (plan + code), the three post-review fixes in `378cd952`, and the full test/lint/type run. Implementation internals not personally written are **[reviewed]** (read end-to-end + test-exercised), not **[authored]**.
- **Project stakes:** pre-1.0, no external users (per root `CLAUDE.md`) — breaking changes are cheap. So this review weights **silent-correctness invariants** (concurrency, identity-over-the-wire) over migration/back-compat, because those are the failure modes that *don't* announce themselves.

## Read First — the load-bearing block

**What exists now:** the previously read-only `pflow ui` Starlette server gained a stateful, push-capable layer (an in-memory `_Hub` + SSE) plus a server-side target resolver; the CLI gained `focus`/`frame`/`clear-focus`/`user-activity`; the frontend gained an SSE client and reveal-before-focus. The agent Points at canvas elements in the user's *own* open browser windows and Watches their recent clicks.

**Read these first (path · symbol):**
- `src/pflow/ui/server.py` · `_Hub`, `events()`, `command()`, `_workflow_key()` — the hub + the five endpoints.
- `src/pflow/ui/targets.py` · `resolve_target()`, `_format_ref()`/`_format_target()`, `address_for_target()` — the **single** address grammar + parser.
- `web/src/api/events.ts` · `subscribe()`, `reportInteraction()` — the browser SSE seam.
- `web/src/views/GraphView.tsx` · `applyPoint()` — maps a server descriptor to focus/frame.
- `web/src/graph/flow.ts` (the edge dedup loop) + `web/src/graph/focus.ts` · `applyFocus()` — the `mergedIds` coupling.

**Invariants that must NOT break:**
1. **Every hub-touching handler is `async def`.** A sync handler runs in Starlette's threadpool and races the loop-affine `asyncio.Queue`/`deque` with **no lock** → state corruption. (Comment pins this at `_Hub` and the route list. Don't add a sync "stats" endpoint that reads `app.state.hub`.)
2. **Flat ids (`n*`/`g*`/`e*`) never cross the SSE wire.** Only structural `RFRef` identity does. The server's fresh render ≠ the browser's live render; a flat id silently targets the wrong element or nothing.
3. **The address grammar lives ONCE in `targets.py`.** The CLI Watch display delegates (`address_for_target`). Re-implementing it elsewhere drifts → the "ambiguous → qualify → re-point" self-correcting loop dead-ends. Guarded by the drift-guard test.
4. **The SSE keepalive `yield` is required.** Removing it leaks connections on ASGI spec ≥2.4 (no disconnect listener there; a dead socket only surfaces on the next `send`). Do **not** swap it for `request.is_disconnected()` — that double-consumes `receive()` on spec <2.4.
5. **No run-event schema here.** The envelope stays vocabulary-agnostic `{type, ...}`; Task 133's overlay adds its own message types over the same pipe. Baking interaction assumptions into the bus breaks that decoupling.
6. **Edge identity = (source `RFRef`, target `RFRef`, `output_field`, `output_path`, `input_name`)** — never the re-anchored `edge.source/target`. And the `flow.ts` dedup must record dropped ids on `mergedIds` (invariant #6b below) or edge-focus silently shows nothing.

## What Was Built (actual vs. planned)

The transport/resolver/CLI shape matches the plan. The **deviations that matter** (each a real plan gap the implementer or the code-review caught — do not "revert to the plan"):

- **Edge descriptor carries `source_path`** (plan omitted it). `RFEdge.output_path` is part of edge identity, so `gen.result.ok → x` and `gen.result.err → x` had identical descriptors → indistinguishable after broadcast. Fixed in both the address and the descriptor.
- **`--open` re-posts *every* target** after the Viewer subscribes, not just edges. The load-time `?focus=` deep-link can't parse qualified / `in:`/`out:` / nested addresses, so re-posting the validated structural command is what makes all target types reliable.
- **Subscription starts only after the graph loads.** Otherwise `--open`'s zero-window count could include a Viewer that can't yet apply a command.
- **Edge resolution keys on the contract `RFEdge`** (matched by endpoint refs + fields + `source_path`), not a search of the painted `FlowEdge` by `data.from`/`data.to`. The plan's `data.from/to` guidance was premised on a rejected approach; the contract endpoints *are* the pre-re-anchor identity, so this is simpler and equivalent. (`web/src/graph/remap.ts` · `edgeIdForTarget`.)
- **`render_react_flow` is left on the event loop** (only `resolve_validate_build` is `to_thread`'d). The plan said move both off-loop; the render is pure in-memory and cheap, so the split is deliberate, not an oversight.
- **Watch buffer is one global `deque` tagged by workflow** (spec said "per workflow") — observably equivalent, simpler.

**Post-review fixes (`378cd952`, [verified] mine):** (a) edge-dedup `mergedIds` (invariant #6b); (b) the single address grammar (#3); (c) the idle-keepalive test.

## Patterns & Anti-Patterns

**Reuse these:**
- **Server resolves text → structural identity; browser maps via the existing `sameRef`.** One parser (Python, unit-testable), browser stays a dumb display. This is the template for *any* future "address a canvas element from outside the browser" feature.
- **Tolerant public + strict private formatter** (`targets.py`): `address_for_ref` validates an untrusted wire dict and returns `None`; `_format_ref` assumes a well-formed payload. Internal callers use the strict one; the CLI uses the tolerant one. Same grammar, no drift.
- **All-async, loop-owned, lock-free shared state** behind a one-line invariant comment naming the *specific* failure. Cheaper and clearer than locks for a single-process server.
- **Bounded queue + evict a non-consuming client** (`_CONNECTION_QUEUE_MAX`): a socket that can't drain 64 human-paced commands is evicted, so memory and the `sent_to` count stay truthful.

**Rejected / anti-patterns (don't reintroduce):**
- A plain `@click.group` with a positional `WORKFLOW` + subcommands — **broken in Click** (reproduced). Must mirror `PflowCLI` (custom `resolve_command` routing to a hidden `serve`).
- A bare `try/finally` for SSE disconnect cleanup (silently breaks on ASGI ≥2.4 — use the keepalive).
- `TestClient` for SSE disconnect cleanup — it can't deliver `http.disconnect` to an infinite generator, so the test passes green **without testing cleanup** (false confidence). Use a raw-ASGI scope.
- A browser→server apply-ack — deliberately *not* built; the human in the loop is the acknowledgment, and the report says `sent_to`, never "shown".

## Gotchas & Non-Obvious Coupling

- **6b — the `flow.ts` FlowEdge dedup key excludes `output_field`/`output_path`.** Two distinct contract data edges between the same nodes (different fields) that fall back to node-level handles in beautiful density **collapse to one rendered edge**. The dropped contract ids are recorded on the kept edge's `data.mergedIds`, and `applyFocus` matches a focused id against `e.id` **or** `e.data.mergedIds`. If you change the dedup to drop without recording, or change `applyFocus` to match only `e.id`, the "resolvable but shown nothing" edge-focus bug returns. This coupling spans `flow.ts` (producer) ↔ `focus.ts` (consumer) and is invisible from either file alone.
- **`_workflow_key` does sync filesystem I/O on the event loop** (a `stat`/resolve per command/interaction/events/activity). Negligible for a localhost single-user server; would matter if this ever went multi-client.
- **`get_path()` never raises** — it returns a phantom path for any string. The `exists()` gate in `_workflow_key` is load-bearing; without it a typo'd workflow name silently maps to a key no window matches (a misleading "0 windows").
- **Density vocabulary splits:** code says `detailed`/`compact`; the agent-facing words are `advanced`/`beautiful` (via `DENSITY_TO_PARAM`). Watch events report the agent-facing words.
- **The spec≥2.4 silent-drop path has no red test** (only the keepalive *emission* is tested + spec-2.3 disconnect). It rests on the keepalive comment + Starlette's send-failure behavior. Acceptable; know it if you touch the SSE generator.

## Integration Points

- **Depends on:** `execution/graph_service.resolve_validate_build` + `render_react_flow` (per-command graph build, same as `/api/graph`); `WorkflowManager.{exists,get_path,list_names}`; `suggestion_utils.find_similar_items(method="fuzzy")`; the `RFRef`/`RFEdge` contract (`react_flow.py`) and `sameRef` (`remap.ts`).
- **Now depended on by (blast radius):** the **SSE envelope** is the seam Task 133's run overlay will ride (coordinate only there). The **`_Hub`** is the first stateful piece of the UI server — ADR-0007 records why; a future "simplify the server back to stateless" would re-break this.
- **Contracts:** new endpoints `/api/events|command|interaction|visibility|activity`; the security comment in `server.py` was extended (JSON-content-type preflight defense — any future mutating endpoint must revisit it). No DB/cache/queue/schema changes. CLI: `--no-watch` → `--no-auto-update` (the `?watch=0` URL param is unchanged, internal).

## Tests That Matter

Run these when you touch the named area:
- `tests/test_cli/test_ui_targets.py` — the resolver. Guards: every `qualify` address round-trips to exactly 1 element; `in:`/`out:`/`[batch_index]` disambiguation; **the display-grammar drift guard** (a `user-activity`-rendered address re-points). Touch `targets.py` → run this.
- `tests/test_cli/test_ui_interaction_server.py` — the hub. Guards: register/broadcast/visibility/**eviction**; the **raw-ASGI `http.disconnect`** cleanup (not TestClient theater); off-loop build; **idle-keepalive emission**. Touch `server.py` → run this.
- `web/src/graph/flow.test.ts` — the **`mergedIds`** regression: a deduped-away data edge focuses the kept line. Touch the `flow.ts` dedup or `focus.ts` edge matching → run this (it's the only guard for invariant #6b).
- `tests/test_cli/test_ui_commands.py` — `UiGroup` routing + preserved bare-serve + exit codes + `httpx` error rendering. Touch `ui.py` → run this; also keep `test_ui.py`'s lazy-import boundary test green (don't move server imports to module top).
- **The visual layer is NOT unit-testable** (jsdom renders no edges/camera). A data line actually lighting was verified in real headless Chrome (progress log Phase 2 + rerun); re-verify there after any focus/reveal change, via `.claude/skills/screenshot-pflow-web-ui`.

---
*Distilled from the implementation + review context of Task 169. The chronological journey (phase-by-phase deviations, dead ends, the live-browser runs) lives in `implementation/progress-log.md` — this review is the durable forward-reference, not a re-narration of it.*
