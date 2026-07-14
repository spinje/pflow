# Task 169: Agent↔Browser Interaction Channel — Point and Watch for the Workflow Viewer

## Description

A bidirectional interaction layer between an AI agent (via CLI) and the user's open `pflow ui`
browser windows: the agent can **point** (focus a node — with its edge highlighting — in every
window showing that workflow) and **watch** (read what the user recently clicked/selected).
Together with the existing screenshot/inspect tooling (which lets the agent *see*), this makes
the canvas a shared surface for human↔agent conversation about a workflow.

## Status

done

## Completed

2026-06-22

## Priority

medium — the natural next increment of the "see / understand the agentic harness" track after
Task 168; also builds the push transport the deferred live-run overlay will ride.

## Problem

The observed trigger (not theorized): while discussing the Task 168 UI, the user said *"I can't
find it"* about a node the agent was describing. The agent's only tools were prose and screenshot
crops of its **own** headless browser — it has no way to act in the **user's** window. Two gaps:

- **The agent can't point.** When a user asks "where is X?" or "explain this node", the agent
  cannot focus/frame/highlight anything in the browser the user is actually looking at. The
  `?focus=` URL param exists but only applies at page load — the agent would have to tell the
  user to paste a URL.
- **The agent can't see what the user is doing.** When a user clicks a node and asks "what's
  this?", the agent has no idea what "this" is — no visibility into recent selections, clicks,
  or the current view state (density/direction/focus).

Structurally: the Task 168 server is stateless request/response with no push channel. The
`/events` SSE stub was deliberately deleted during Task 168 design ("no dead routes — build it
when a consumer exists"). The consumer now exists.

## Solution

Three pieces, all small because the hard parts already exist:

1. **A server→browser push channel (SSE).** Open pages subscribe, identifying which workflow
   they're showing. The server keeps an in-memory registry of live connections per workflow —
   the first stateful piece of the UI server (ephemeral, per-process, nothing persisted).
2. **Agent commands** via new CLI verbs (thin HTTP clients against the running server): focus a
   node, clear focus, frame the camera on a node. The server broadcasts the command to every
   subscribed window showing that workflow. The command's output reports **how many windows
   received it** — "0 windows have this workflow open" is the agent-actionable case.
3. **A user-event buffer.** The page reports deliberate interactions (node/row clicks, focus
   changes, workflow switches — NOT hover/pan/zoom) to the server; a small in-memory ring
   buffer holds the recent history per workflow; a CLI verb reads it. Events carry enough for
   the agent to reason: timestamp, event type, node identity, and the window's current view
   state (density/direction/focus).

The frontend's "pointing" behavior is **not new mechanics**: an incoming focus command
dispatches through the exact code path the `?focus=` param and a user click already use
(focus + dim non-incident + reveal incident data lines + (beautiful) expand the card). The
incoming/outgoing edge highlighting the feature wants IS what focus already does.

## Design Decisions

- **SSE + plain POST, not WebSocket.** Commands flow CLI → server (POST) → browsers (SSE);
  user events flow browser → server (fire-and-forget POST) → CLI (GET). Nothing needs a
  bidirectional socket; SSE is also the transport shape the original Task 168 design named for
  the future overlay.
- **This is the overlay's transport, but NOT the overlay's schema.** Building the channel now
  must not pin Task 133's run-event schema — that was deliberately deferred until its consumers
  exist. This channel carries *UI interaction* messages only; the overlay adds its own message
  types later. Frame it as: same pipe, different (future) vocabulary.
- **Agent-pointing = focus, reused verbatim.** No separate "agent highlight" visual state in v1.
  If "the agent is pointing here" should later look different from "I clicked here" (e.g. a
  pulsing ring), that's an additive style on top — not a parallel mechanism.
- **Single-target commands, extensible shape.** One target per command. **v1 target types expanded
  during planning** to: a node, a container (sub-workflow/batch box), a workflow/sub-workflow IO
  port, AND a data edge (named by a `from -> to` pair, e.g. `gen.response -> summarize.prompt`).
  Deferred to a fast-follow: standalone body-rows (an output/input field alone), control/branch
  edges, and any multi-target form — the structural target-descriptor payload does not preclude
  them. See `implementation/implementation-plan.md` for the addressing grammar (scope prefixes,
  `in:`/`out:`, `[batch_index]`).
- **Watch = deliberate interactions only.** Hover/pan/zoom are noise that would drown the
  buffer and the agent. Clicks, row clicks, focus changes, workflow switches.
- **Delivered-count in every command response, with per-window visibility.** A broadcast into
  zero windows must be loudly visible to the agent, never a silent success. Subscriptions also
  carry the page's `document.visibilityState` (updated on `visibilitychange`), so the report
  distinguishes "delivered to a visible window" from "delivered to a backgrounded tab" — the
  agent's decision tree is fully informed: visible → done; hidden → tell the user where to
  look; zero → open one.
- **Open-if-absent is an explicit flag, not automatic.** When zero windows have the workflow
  open, the focus command can open a browser itself (reusing the load-time `?focus=` URL — no
  new frontend mechanism) behind an explicit `--open`-style flag. The agent will usually pass
  it in a "where is X?" conversation, but taking over the user's screen is a per-invocation
  decision the agent makes visibly, not a silent default.
- **Force-focusing an existing background tab is OUT — impossible by web platform design.**
  Browsers block background pages from stealing focus (`window.focus()` outside a user gesture
  is a no-op; anti-abuse focus-stealing protection) — this cannot be engineered around via the
  SSE channel. Re-opening the URL from the CLI doesn't dedupe either (it creates a duplicate
  tab, worse than none). The visibility report above is the deliberate alternative. A
  title/favicon attention cue for hidden tabs is possible later polish, not v1.
- **Server state is ephemeral in-memory.** Connection registry + ring buffer live in the
  process; restart loses them; no persistence layer. This deliberately changes the server's
  "every request is a stateless re-parse" nature — for live connections only, not for graph data.
- **Own task, not Task 168 polish.** It changes the server's nature and adds a CLI surface;
  Task 168 is done and PR'd.

## Dependencies

- **Task 168 (Workflow Visualization Web UI) — DONE.** The server, the contract, and the entire
  frontend focus/expand mechanism this reuses.
- **Source-reload REACTION already ships (Task 168, 2026-06-16).** The in-place rebuild trigger
  (`useWorkflowGraph`'s `reload`, fed by `useSourceWatch` polling `/api/version`) preserves
  viewport/focus/collapse. Task 169 MAY replace the DETECTION (the poll) with a push on its SSE
  channel via the `web/src/api/` seam — the reaction trigger is unchanged, so nothing downstream
  of the seam moves.
- **Task 133 — NOT a dependency.** The overlay remains deferred; see the schema-decoupling
  decision above.

## Requirements

### Point (agent → browsers)
- A CLI command focuses a node in **all** open browser windows currently showing that workflow;
  the focus applies the same visual state as a user click (dim non-incident, reveal incident
  data lines, expand in beautiful) — incoming/outgoing edge highlighting comes with it.
- Clear-focus and frame-only (camera moves, no focus state) variants exist.
- The command's stdout states how many windows received the command AND each window's
  visibility (visible vs backgrounded); zero is a distinct, agent-actionable message (what to
  do next), not an error-free no-op.
- An opt-in flag on the focus command opens a browser window (via the `?workflow=…&focus=…`
  URL) when zero windows have the workflow open; without the flag, zero windows only reports.
  The flag never opens a duplicate when a window (even a hidden one) already has the workflow.
- A command for a workflow no window has open never errors the server or affects other windows.
- Commands work against a server the agent didn't start (any `pflow ui` instance on the port).

### Watch (browsers → agent)
- Deliberate user interactions (node click, port-row click, focus change, workflow open/switch)
  are readable via a CLI command, most-recent-first, with timestamps.
- Each event identifies the node both ways the system names nodes (the author-known `node_id`
  and the flat contract id) and carries the window's view state at the time (density, direction,
  current focus).
- The buffer is bounded (ring); event reporting from the page is fire-and-forget (a failed
  report never breaks the UI).
- Hover/pan/zoom produce no events.

### Server & channel
- Pages subscribe per workflow; the registry tracks live connections and cleans up dropped ones.
- All existing Task 168 behavior is unchanged: `/api/catalog`, `/api/graph`, static serving,
  and all four `/api/graph` status arms behave exactly as before.
- The new mutating endpoints honor the existing no-CORS security tripwire in `server.py`
  (binds 127.0.0.1, no CORS headers): the analysis comment must be revisited and extended, and
  the worst-case cross-origin write must remain benign (focusing a node in the user's own
  viewer; no file/system effect).
- The channel carries no run/trace data and defines no run-event schema (Task 133 boundary).

### CLI
- `pflow ui` keeps serving with optional workflow + `--port`/`--no-open`; the new verbs are
  additive. Mechanism: a custom `click.Group` modeled on `PflowCLI` (a plain group with a
  positional arg cannot coexist with subcommands — see the implementation plan). The pre-existing
  `--no-watch` serve flag is renamed `--no-auto-update` (Watch now means the agent watching the
  user; that flag controls the source-file auto-update).
- New verbs (thin HTTP clients, all taking `--json`): `pflow ui focus <wf> <target> [--open]`,
  `pflow ui frame <wf> <target>`, `pflow ui clear-focus <wf>`, `pflow ui user-activity [wf]` (the
  Watch read — named to avoid colliding with the renamed auto-update flag). When no server is
  running they fail fast with an agent-actionable hint, not a hang or traceback.

### Packaging
- No new runtime dependency beyond what `[ui]` already declares (SSE is within Starlette's
  capabilities; the CLI client should use stdlib or an existing dependency).

## Implementation Notes

- **Frontend seam:** `web/src/api/` is the designated role-slot folder for a subscription
  client (per `web/CLAUDE.md` — "events.ts plugs in here"); the file does not exist yet.
  Incoming commands should dispatch through `GraphView`'s existing focus state (the same path
  as `viewParams.ts` `focus=` and `onNodeClick`) — do not build a second focus mechanism.
- **CLI shape:** `cli/commands/ui.py` is currently a plain `@click.command`; new verbs imply a
  group restructure with the bare invocation preserved (Click `invoke_without_command`) or
  sibling commands — implementer's call, but `pflow ui <workflow>` must keep working as-is.
- **Workflow identity for broadcast filtering:** pages identify workflows by the `?workflow=`
  value (saved name OR a path). The same workflow opened by name vs path must not silently
  split into two broadcast groups the agent can't see — either normalize, or make the events/
  delivery output expose the identity actually used so the agent can match it.
- **Node addressing in commands:** accept what the `node=`/`focus=` URL params already accept
  (author-known `node_id`, falling back to flat id) — `node_id` is not unique across
  sub-workflows; same disambiguation rules as the URL params.
- **Multiple servers/ports:** default port 8765, `--port` to target another instance — same
  convention as `pflow ui` itself. No discovery mechanism in v1.
- **Open-if-absent:** reuse `pflow ui`'s existing browser-open machinery (`webbrowser`); on
  macOS this activates the browser at the OS level, so a fresh open does land in front of the
  user — which is exactly why force-focusing an *existing* tab is the only part the platform
  withholds.
- The screenshot/inspect skill (`.claude/skills/screenshot-pflow-web-ui`) is the *see* leg of
  the same arc and is unaffected; it drives the agent's own headless Chrome, not user windows.

## Verification

- **The originating scenario:** with a workflow open in a real browser, the agent runs the
  focus command for a node — the open window focuses/frames it with its connections highlighted,
  without a reload. With two windows open on the same workflow, both respond; output reports 2.
- With no window open, the command reports 0 windows with an actionable hint; the server is
  unaffected. With the open flag, a browser opens on the workflow with the node focused; with
  a backgrounded tab already subscribed, the report says so and the open flag does NOT
  duplicate the tab.
- User clicks a node in the browser; the events command shows the click with the correct
  `node_id`, flat id, and view state. Hovering and panning produce nothing.
- All Task 168 server tests still pass unchanged (the four `/api/graph` arms, catalog, static
  serving, 503 fallback, lazy-import boundary).
- A dropped browser connection (tab closed) is cleaned from the registry; subsequent commands
  report the corrected window count.
- Frontend gates: the handle-type invariant and existing focus tests unchanged; new behavior
  pinned at the transform/state level (jsdom cannot verify the visual layer — final visual
  check via the real-browser skill, per the Task 168 discipline).

## References

- **Task 168** (`.taskmaster/tasks/task_168/`): `task-168.md` (the deleted-SSE-stub decision,
  overlay-readiness framing), `visualization-requirements.md` (focus/reveal semantics that
  pointing reuses), `task-review.md` (server/contract reading order).
- **ADR-0005** (`context/adr/0005-web-ui-local-server-delivery.md`) — the server exists partly
  *because* live streaming would someday need one; this is that "someday" arriving for
  interaction (not yet for run data).
- `src/pflow/ui/server.py` — the no-CORS security tripwire comment (~line 126) that the new
  mutating endpoints must extend; `src/pflow/ui/CLAUDE.md` — API consumption rules.
- `web/src/views/GraphView.tsx` (focus state + `onNodeClick`), `web/src/utils/viewParams.ts`
  (`focus=`/`node=` resolution rules), `web/CLAUDE.md` (the `api/` seam).
- **Task 133** (`.taskmaster/tasks/task_133/`) — the overlay whose schema this task must NOT
  pin; shares only the transport shape.
- **`implementation/implementation-plan.md`** — the authoritative, deep-reviewed execution plan
  (server hub + SSE, target resolver, frontend wiring, CLI group, phases, tests, edge cases).
  Where any detail above conflicts with it (e.g. the ring buffer is one global tagged buffer, not
  literally per-workflow), the plan wins.
- **`context/CONTEXT.md`** — glossary terms added this task: Viewer, Point, Watch, Auto-update
  (plus the Watch-vs-Auto-update ambiguity).
