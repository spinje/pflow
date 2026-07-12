# Approval surfaces are out-of-process bridges: one payload, one resume verb, a surface-ignorant engine

## Status

accepted (2026-07-02)

Human-approval gates (Task 125) must reach humans on many surfaces — TTY today; web UI, Slack,
email, MCP callers later. **Decision: the engine knows nothing about surfaces.** It emits one
structured, self-contained `GateRequest` payload (rendered by the TTY prompt, written to the trace
as a `gate` event, persisted by the durable pause) and accepts exactly one delivery API for the
human's answer — `pflow resume <execution-id> --approve yes|no`. Every approval surface is an
**out-of-process bridge**: read the gate (the `gate` trace event / `paused` trailer) → render
`GateRequest` → run `pflow resume`. The first bridge is the web UI (Task 176: `POST /api/approve`
spawns the CLI, mirroring `/api/run` under ADR-0008's observe-never-host rule).

> **Amendment (2026-07-11, Task 176 plan session):** the web bridge shipped the answer surface as
> ONE `POST /api/resume` mirroring the CLI verb — `{run, approve?, choose?, force?}` — rather than
> a separate `/api/approve`; approval delivery is the `approve` body field. The decision (one
> pre-flight, one spawn path, flag exclusivity mapped 1:1 from the CLI) is ledger #4 in
> `task-176.md`. The pattern this ADR fixes — payload is the seam, answers only via
> `pflow resume` — is unchanged.

## Considered options

- **In-engine surface abstraction (`ApprovalSurface` ABC / plugin registry)** — rejected. One
  adapter is a hypothetical seam; resolution today is a plain function (TTY prompt /
  `--auto-approve=<node-id>` / non-TTY → structured, agent-actionable error; Task 171 later
  replaces only the non-TTY branch). Surfaces multiply outside the engine at zero engine cost —
  **the payload is the seam**, not a surface interface.
- **Web approval inside Task 125 (blocking mode)** — rejected. Approving a *blocked in-process*
  run from the server needs either server→process IPC (couples the run's lifecycle to the server —
  the exact coupling ADR-0008 forbids) or a decision-file poll (a throwaway second resume mechanism
  that Task 171 obsoletes). Durable-token-then-bridge is strictly less final machinery.
- **Per-surface payload shapes** — rejected. `GateRequest` must be **self-contained** (a remote
  human decides from the payload alone, no terminal access); the trace `gate` event doubles as the
  serialization test for exactly what Task 171 persists.

## Consequences

- Adding a surface (Slack, email, phone app) never touches the engine: each is a renderer plus a
  `pflow resume` caller. Bridges own their own authentication; pflow's trust boundary stays
  "whoever can run the CLI locally."
- A pause-time notification hook (`on_pause` command/webhook) is additive at the single pause
  site — build it with the first external bridge, not before (polling `pflow resume list`
  suffices until then).
- A blanket `--auto-approve` deliberately does not exist (agent-first footgun: an agent that
  learns to always pass it defeats the gate). Approval bypass is per-node:
  `--auto-approve=<node-id>`, repeatable.

## References

- Tasks: 125 (gate primitive + `GateRequest`), 164 (resume machinery), 171 (durable pause/token),
  176 (the web bridge — first instance of the pattern).
- ADR-0008 (the UI observes, never hosts; the `/api/run` spawn precedent). ADR-0007 (169 SSE;
  WebSocket pre-authorized if true bidirectionality is ever needed).
- `task-171.md` "Consumers & synergies" — the generalized bridge pattern + external-surface notes.
