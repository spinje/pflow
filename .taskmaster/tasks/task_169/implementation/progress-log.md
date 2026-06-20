# Task 169 — Progress Log (design & planning)

> **What this file is:** the tacit knowledge from the design + planning process — *why* decisions
> landed where they did, what was tried and rejected, and what nearly bit us. It is the complement
> to the other three artifacts; it deliberately does **not** restate them:
> - `task-169.md` — the spec (what/why, requirements).
> - `implementation/implementation-plan.md` — the how (endpoints, resolver, phases, tests, anchors).
> - `context/CONTEXT.md` — the glossary (Viewer, Point, Watch, Auto-update).
>
> Read those for *what to build*. Read this for *why it's shaped this way and where the bodies are
> buried*. Status as of this entry: **planned + deep-reviewed, not yet implemented.**

---

## 2026-06-19 — Planning & design session (no code yet)

### The one decision a future agent will most want explained: resolution lives in the SERVER

The plan says "the server parses the target → resolves to a structural `RFRef` → the browser maps it
via `sameRef`." That is **not** the obvious choice, and we arrived at it by reversing an earlier one.
The journey, so nobody re-treads it:

1. **First instinct:** validate the node server-side (build the graph, check it exists).
2. **Rejected → "resolve in the frontend only":** the frontend already has `resolveNodeFlatId`/
   `sameRef`; re-implementing node addressing in Python would be a *second source of truth* that
   drifts — exactly the validation-vs-runtime drift this codebase hunts for. So: server stays a dumb
   pipe, broadcasts the opaque target string, the browser resolves. Agent learns the result by
   *screenshot* (the "see" leg already exists).
3. **Reversed → "resolve in the server, to a structural `RFRef`":** the frontend-only design forces
   the agent to screenshot-and-eyeball to learn "did it hit? how many matched?". For an agent-first
   tool that's worse than a structured answer. The key unlock: the server resolves the *agent's text*
   to a **structural identity** (`node_id`+`ancestor_path`+`port`), and the browser maps *that* to its
   on-screen flat id via its **existing** `sameRef` — so there is still only **one notation parser**
   (Python), no drift, the report is **synchronous + structured**, and the parser is unit-testable
   without a browser. The browser became a dumb display after all, just keyed on structure not text.

**Load-bearing principle that fell out of this:** flat ids (`n3`/`g2`/`e7`) are positional and
unstable, and the server's fresh render ≠ the browser's live render. **Only structural identity is
valid currency between two independently-rendered views.** If you ever find a flat id crossing the
SSE wire, that's a bug.

### The insight the deep-review forced (and the lesson for the deferred work)

The agent-facing **address string was lossier than the `RFRef` it described** — it dropped `port`
(IO in/out) and `batch_index`. Consequence: an input `data` and an output `data` both stringified to
`data`; batch items 0 and 1 both stringified to `fanout.gen`. The "ambiguous → here are the qualified
scopes → re-point" loop then dead-ends, because the qualify list is *identical strings*. Fixed in the
plan (`in:`/`out:`, `[batch_index]`).

**Reusable lesson (applies to every deferred fast-follow too):** an agent-facing identity string must
carry **everything** the structural identity carries, or self-correction can't converge. When you add
standalone-row or control-edge addressing later, re-check this invariant first.

### The design philosophy that drove half the small decisions: the self-correcting loop

The user articulated it as *"agents see this happening and can prefix with the subworkflow name if
they need to."* The agent doesn't have to be precise on the first point — it points, observes (the
structured report's qualified scopes, or a screenshot), and re-points. This single idea decided:
- **ambiguous → report, never guess** (a wrong point is worse than no point);
- the **qualify list must round-trip** (each entry resolves to exactly 1 — now a required test);
- **structured/parseable output** matters more than a pretty point, because the *report* is the
  feedback channel that closes the loop.

### Scope calls and the reasoning the spec doesn't carry

- **Edges are in v1 by the user's explicit choice, against my recommendation to defer.** Verification
  showed edges are the costliest target (no field-level structural identity; a frontend edge-by-
  endpoints lookup the existing code deliberately marked *"deferred"*; and a collapse/re-anchor case
  where the discrete edge doesn't exist). I recommended shipping nodes+containers+IO and fast-
  following edges; the user chose to include edges. So the cost is **known and accepted**, not
  overlooked — budget for the real-browser verification of the `data.from`/`data.to` keying.
- **Why standalone body-rows are deferred (not just "later"):** `RFRef` has no field-level identity —
  it reaches node + in/out side, not "the `prompt` row of `summarize`." Addressing a row *alone* needs
  a richer descriptor. (Rows are still reachable *as edge endpoints* — that's why edges work but
  standalone rows don't.)
- **Why control/branch edges are deferred:** they have no `${ref}` to name them by, and they hit the
  same collapse/re-anchor fragility. The `data_flow`-only restriction is coherent, not arbitrary.
- **Per-window visibility is full (not count-only)** because it serves the *originating* "I can't find
  it" moment directly — "it's in a backgrounded tab, switch over" is the actual help. The cost is one
  conn-id + a tiny visibility POST, which we needed for registry cleanup anyway.
- **Watch buffer is one global tagged ring, not a per-workflow dict** (the spec says "per workflow").
  Observably equivalent, less structure; supports the "what did the user just touch, anywhere" case.

### The concurrency landmine (most important thing for whoever writes the SSE endpoint)

The "all handlers async → single loop → no locks" claim is **correct for the design and the shipped
stack**, verified at ASGI level. But the disconnect cleanup has a **latent, version-dependent trap**:

- A bare `try/finally` around `await queue.get()` only fires on a silently-dropped tab when
  `StreamingResponse` runs under ASGI **`spec_version < 2.4`**. Today's stack (plain `uvicorn` 0.35,
  h11 → spec 2.3) takes that branch, so it *works today*.
- The moment anyone installs `httptools` / `uvicorn[standard]` / bumps uvicorn to a 2.4+ path, the
  generator blocks on `queue.get()` forever and **connections leak** — silently inflating the very
  delivery counts this feature exists to report. The `>=0.30` floor does **not** pin this.
- Fix (in the plan): a periodic **keepalive `yield`**, which forces a `send()` so a dead socket
  surfaces on *either* ASGI version. **Do not "simplify" it to `request.is_disconnected()`** — on the
  spec<2.4 path `StreamingResponse` already consumes `receive()`, and a second consumer is undefined.
- **Testing trap:** Starlette's `TestClient` **cannot** deliver `http.disconnect` to an infinite SSE
  generator, so a `client.stream(...)` "cleanup" test passes **green without testing cleanup**. Test
  cleanup via `_Hub` units + a raw-ASGI disconnect injection. (This is exactly the kind of
  synthetic-fixture-matches-happy-path false confidence to avoid.)

And the future-facing one: the no-locks invariant is **unenforced**. A later "stats" endpoint written
as a sync `def` that reads `app.state.hub` would run in a threadpool and race the loop. The plan puts
a hard comment naming this failure at `_Hub` and the route list — keep it.

### Spec-vs-code discrepancies found (trust boundary — don't trust the spec's specifics blindly)

The spec is directionally right but had stale specifics. Verified against code:
- "no-CORS security comment ~line 126" → actually **`server.py:279-287`** (line 126 is an unrelated
  400 branch). And that comment *already* anticipated "any mutating/live-run endpoint must revisit
  this" — it foresaw us.
- "the `?focus=` URL param exists" → yes in the **frontend**, but the **CLI never emits it** today;
  `--open` adds it.
- "focus produces incoming/outgoing edge highlighting" → imprecise. Focus does **symmetric** incident
  reveal/dim + a per-edge source/target *fade hint*, not separate in/out edge sets. Substance (the
  connected edges light up) holds.
- A `--no-watch` serve flag existed that the spec never mentioned — found during exploration, now
  renamed `--no-auto-update`.
- `WorkflowManager.get_path(name)` does **not** raise on a bad name — it returns a *phantom* resolved
  path for any string. Gate name→key normalization with `exists()`, or a typo silently maps to a key
  no window will ever match (reported as a misleading "0 windows").

### Smaller rejected alternatives (so they're not re-proposed)

- **Plain `@click.group` + positional `WORKFLOW`** — the obvious restructure. It's *broken in Click*
  (reproduced in review: both the new verbs and the existing `pflow ui <wf> --no-open` fail). Must use
  a custom `UiGroup` mirroring `PflowCLI`. Don't retry the plain group.
- **WebSocket** — nothing needs a bidirectional socket; SSE (down) + plain POST (up) is enough and is
  the transport shape the overlay was always named for.
- **`navigator.sendBeacon`** for the interaction report — rejected: it sends a CORS-safelisted content
  type, which would *bypass* the `application/json`-forces-preflight cross-origin defense. Use
  `fetch(keepalive:true)` with a JSON content-type.
- **`--output-format json`** on the verbs — there's no such convention for subcommands; the repo idiom
  is a boolean `--json` + inline `json.dumps` (like `list.py`).

### Why this is also the overlay's transport (don't let it rot)

This channel is the live-run overlay's (Task 133) future transport. The single rule that keeps the two
tracks decoupled: **the SSE envelope stays vocabulary-agnostic** (`{type, ...}`) and this task defines
**no run-event schema**. If you find yourself baking interaction-message assumptions into the bus
plumbing, stop — the overlay adds its own `type`s over the same pipe later.

### For implementation: do Phase 0 (the ADR) before code

The server going stateful + push reopens a *recorded* "read-only, stateless, no side effects" decision
(`server.py:279`, `ui/CLAUDE.md`, ADR-0005). Write the amendment first, or a future validation-
consistency review will (correctly) flag the stateful server as an unjustified regression.

---

## 2026-06-19 — Apply model: the "sent vs shown" correction (and why there is NO ack channel)

A contradiction surfaced after the deep-review (the user caught it; it was *my* planning over-reach):
the plan reported a command's outcome at the moment the message was **queued** to the SSE connections,
yet *also* promised browser-determined outcomes back in the command response — e.g. it literally said
"the command's window entry notes 'target hidden'". There was **no channel** for the browser to report
that, and the word "delivered" quietly conflated **queued** with **shown**. So the CLI could report
success while the user's screen showed nothing.

We considered building command **acknowledgments** (command id → each Viewer POSTs applied/failed →
the CLI waits a bounded time and returns per-window outcomes). **We deliberately did NOT.** The cleaner
resolution — which the user steered — is two rules that make the report honest without a protocol:

1. **The server validates before sending** → a bad target never broadcasts; it returns a *great error*
   (not-found + fuzzy suggestions / ambiguous + qualified scopes / 0 windows). All server-knowable.
2. **The browser always reveals a resolvable target** (total apply: focus/edge/frame expand collapsed
   ancestors; edge focus un-hides in beautiful). So "exists in the view → shown" holds without a
   confirmation round-trip.

The report now says **`sent_to` N windows (+ per-window visible/backgrounded)** — never "shown".

**The insight that makes acks unnecessary in v1: the human is the acknowledgment.** This is a
*conversation* — the agent points, says "see it?", and the human says yes/no. Two corollaries a future
agent must not forget:
- The screenshot skill drives the **agent's own** headless browser, **not the user's window** — so it
  can never confirm the point landed in the user's Viewer. Don't reach for it as proof.
- The only residual gap is a **stale browser view** (~1.5s after an edit, before Auto-update
  refreshes): a just-validated target may not be in that window yet → nothing shows. It **self-heals**
  on the next poll and the human re-points. A transient, not a failure mode worth a protocol.

**When acks WOULD be worth building (deferred fast-follow):** an autonomous/no-human flow that must
programmatically confirm "shown", or the run-overlay (which would define its own confirmation). Until
such a consumer exists, building it would violate the same "build it when a consumer exists" discipline
that deleted the original SSE stub. The envelope is generic, so an `applied`/ack message type is purely
additive later — no rework.

**Meta-lesson for the next agent:** don't add a confirmation protocol when a human closes the loop.
"Validate hard up front + always reveal + report honestly" beats "do it blind, then build machinery to
check whether it worked."
