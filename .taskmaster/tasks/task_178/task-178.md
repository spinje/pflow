# Task 178: Migrate to MCP SDK 2.x (spec 2026-07-28)

## Description

Move pflow's MCP client (MCP nodes, discovery, the connection pool, `pflow probe`) and its MCP
server (`pflow mcp serve`) from the `mcp` 1.x SDK — pinned `<2` by #644 part 1, now in
maintenance-only mode upstream — to SDK 2.x, and close the eight places where 2.x makes pflow
silently wrong. One step: SDK 2.x interoperates with both protocol eras, so nothing in the
ecosystem is cut off by the bump.

## Status

not started

## Priority

medium

## Roadmap

then

## Problem

pflow pins `mcp<2` (`pyproject.toml`, #644 part 1; locked 1.26.0) because SDK 2.x renamed APIs
pflow imports. Upstream declared 1.x the maintenance line at the 2.0.0 release (2026-07-28: "v1.x
is in maintenance mode and will only receive security fixes") with no published end-of-life;
1.x still changes defaults in maintenance (v1.30.0: redirect, idle-session, OAuth behaviour).
The MCP specification revision 2026-07-28 removed protocol sessions and `initialize`
(SEP-2567/SEP-2575); a spec-legal *modern-only* server rejects pflow's current legacy client.

The rename surface is the easy part. The load-bearing risk is **silent**: SDK 2.x moved result
and schema attributes to snake_case and changed exception shapes, and pflow reads several of
them through `hasattr`/type-name checks that keep "working" while returning wrong answers.
Measured on SDK 2.2.0 (research below), eight sites go silently wrong:

- `nodes/mcp/node.py:742` — structured tool results ignored (`hasattr(r, "structuredContent")` is False);
- `nodes/mcp/node.py:747` — **tool errors read as success** (`isError`), node returns `default`;
- `mcp/discovery.py:176`, `:250` — every discovered tool gets an empty input/output schema
  (flows into the registry, validation, `describe`);
- `mcp/errors.py:44` — 401/403/429/5xx diagnostics dead: v2 raises
  `MCPError(-32603, 'Server returned an error response')` with the status code gone;
- `mcp/pool.py:31` — no reconnect after a stdio server dies (`MCPError(-32000)` is not an
  `OSError`/`ClosedResourceError`);
- `mcp_server/server.py` pass-through (`_PASS_THROUGH_TYPES`) — since SDK 2.1 agents calling
  pflow's server see "Error executing tool X" with pflow's pre-formatted message dropped.

The existing tests would not catch most of these: the pool and node-behaviour tests use
MagicMocks carrying `.isError`/`.structuredContent` attributes, and the error tests build
`httpx.HTTPStatusError` shapes v2 never raises.

## Solution

Bump to SDK 2.x in one step, port the three client connect implementations and the server
subclass, and re-express each silently-affected behaviour on v2's real shapes — proven by tests
that use real SDK objects and real servers, not attribute mocks.

## Design Decisions

- **One step, not a dual-SDK phase.** VERIFIED wire matrix: a v2 client (legacy handshake or
  `Client(mode="auto")`) works against 1.26 servers over stdio and streamable HTTP, and against
  real `chrome-devtools-mcp@1.10.1` / `@playwright/mcp@0.0.83`; a v2 server serves a 1.26 client
  over both transports.
- **Delete, don't port, what SDK 2.x now does natively.** v2's `stdio_server` moves the wire to
  private fds, points fd 1 at stderr and fd 0 at devnull while serving — so the MCP-server stdio
  shims (#652's stdout override, #657's stdin twin) are deleted here, not ported.
  Same test for every shim: if v2 covers it, the shim goes.
- **The user's governing lens applies to every fork below**, verbatim: *"We should prioritize
  simplicity of the FINAL code, not how easy it is to get there. When in doubt we should ask
  ourselves whats the right solution that the top 10% of codebases similar to this one would
  implement, have we considered it yet? What this doesnt mean is overfitting to "top 10% of
  codebases" and overengineering, this is about more simple code that is optimized for AI agents
  to understand and add features to."*

## Open questions (resolve at start — each ≥2 shapes; recommendation given, ruling is the user's where marked)

- **Q1 (user) — which client era pflow speaks.** (a) keep lowlevel `ClientSession` +
  `initialize()` (smallest diff; fails against modern-only servers, as today); (b) v2
  `Client(target, mode="auto")` — probes `server/discover`, falls back to `initialize`, works
  against both eras (VERIFIED), one probe per connection; (c) hand-rolled discover-then-initialize
  (reimplements b). Recommendation: (b), IF it accepts pflow's headers/auth/timeouts — UNVERIFIED
  whether `Client` takes an injected `httpx2.AsyncClient`; verify first. Sub-question: cache the
  negotiated era per server or re-probe per run.
- **Q2 — one client, not three.** The standalone path in `nodes/mcp/node.py:257-402` (used by
  `pflow probe` and the MCP-server `registry_run`) duplicates `pool.py`'s connect logic;
  `discovery.py` is a third. Six connect paths (3 × stdio/HTTP) must all port — or fold to one
  connect helper. Recommendation: fold (the migration touches all three anyway).
- **Q3 (user) — HTTP status diagnostics.** v2 drops the status from the exception. (a) accept a
  generic message (loses agent-facing 401/403/429 guidance); (b) capture status via an `httpx2`
  response `event_hook` on the client pflow builds; (c) classify by `MCPError.code`/message only.
  Recommendation: (b) if Q1 lets pflow own the `httpx2` client; else (c).
- **Q4 — reconnect semantics.** Re-express "dead peer → reconnect once, never on timeout" on v2
  types: does `MCPError(code=CONNECTION_CLOSED, -32000)` count?
- **Q5 (user, show-before-code) — pflow server error text.** Convert pass-through exceptions to
  `ToolError(str(e))` (client sees `Error executing tool X: <msg>`) or render
  `CallToolResult(is_error=True)` itself (pflow's own bytes). User-visible to agents → concrete
  before/after examples before building.
- **Q6 — version floors.** `mcp[cli]>=2.2,<3` vs `>=2.0` (2.1 changed exception text; 2.2 redirect/
  session behaviour); whether the `[cli]` extra is still needed (nothing in `src/pflow` uses it);
  raise `claude-agent-sdk` to `>=0.2.140` (0.2.96–0.2.139 pin `mcp<2`).
- Smaller, planner-owned: keep explicit `terminate_on_close=True`? (legacy DELETE vs TS-v2
  servers answering 405); timeouts map to `httpx2.Timeout(timeout, read=sse_timeout)`
  (`mcp/manager.py:322`); resource-not-found wire code (`-32602` via `ResourceNotFoundError` vs a
  plain `ResourceError`); `serverInfo.version` becomes `""` unless passed.

## Dependencies

None hard. Coordinate: **#652** (stdout reservation) merges first — this task deletes its
MCP-server override. Sequenced after **Task 170** by roadmap choice (limit concurrent churn), not
by a code dependency.

## Requirements

### Client
- Every connect path (pool, standalone/probe, discovery — stdio and streamable HTTP) runs on SDK
  2.x; per-server headers, auth (`mcp/auth_utils.py`), and `timeout`/`sse_timeout` config take
  effect on the v2 transport.
- Structured tool results are returned when present; a tool result with the error flag set is
  reported as a tool error (non-`default` action), never as success.
- Discovery records each tool's real input and output schema.
- A dead stdio server mid-run is reconnected at most once (Q4 ruling); timeouts never reconnect.
- HTTP failures carry the diagnostics Q3 rules (at minimum: auth vs rate-limit vs server error
  remain distinguishable if Q3 = b).

### Server
- `pflow mcp serve` runs on v2 (`MCPServer`); every tool and resource call succeeds (the v2
  `context` argument is accepted and forwarded by pflow's overrides).
- Agents see pflow's rendered error text for pass-through errors (shape per Q5).
- The MCP-side stdio shims are deleted — the #652 stdout override AND the #657 stdin twin (a
  private stdin stream handed to `stdio_server`); v2's `stdio_server` natively diverts fd 1 to
  stderr and points fd 0 at devnull while serving. Stray output from tool execution still never
  reaches the protocol channel, and a code-node subprocess under `mcp serve` still reads EOF.

### Dependencies and docs
- `pyproject.toml` bounds per Q6; `uv.lock` relocked; the web UI still works on the relocked
  starlette (0.47 → 1.7 in the resolution — UNVERIFIED today).
- `mcp_server/CLAUDE.md`, `guide/nodes/mcp.md`, `docs/reference/nodes/mcp.mdx` updated where they
  name 1.x APIs or behaviour. The `uvx --with 'mcp<2' mcp-proxy` workaround stays until upstream
  mcp-proxy #235 closes (it runs in its own tool env — independent of pflow's pin).

## Implementation Notes

- **Exposure map:** 52 SDK touchpoints across `mcp/pool.py`, `nodes/mcp/node.py`,
  `mcp/discovery.py`, `mcp/errors.py`, `mcp/manager.py`, `mcp/auth_utils.py`,
  `mcp_server/server.py`, `mcp_server/main.py`, `mcp_server/tools/*`,
  `mcp_server/resources/*` — table with `file:line` and class in
  `starting-context/mcp-sdk2-migration-research-2026-09-30.md` §3 (re-verify at start;
  line numbers drift).
- **Loud renames:** `FastMCP` → `mcp.server.mcpserver.MCPServer` (+ exceptions module path);
  `streamablehttp_client(url, headers, timeout, sse_read_timeout, auth, terminate_on_close)` →
  `streamable_http_client(url, *, http_client=None, terminate_on_close=True)` returning a
  2-tuple (no `get_session_id`); `McpError` → `MCPError` (`str()` has no prefix — `errors.py`'s
  `McpError: (.+?)` regex and tests hard-code v1 text); `call_tool`/`read_resource` overrides
  gain `context`.
- **httpx2:** SDK 2 uses the `httpx2` fork; pflow's own `httpx` stays (side by side). An
  `except httpx.X` around SDK calls silently never matches again; logger names change
  (`cli/logging_config.py:44`).
- **v2 client validates inbound results** — spec-invalid third-party output may now raise
  `pydantic.ValidationError` from `list_tools()`/`call_tool()`; surface it as an actionable MCP
  error, not a crash.
- **Tests (the fidelity gap is the risk):** replace attribute MagicMocks with real
  `CallToolResult`/`Tool` objects; port the one real stdio server fixture
  (`tests/test_nodes/test_mcp/test_result_format_json_block.py:151-195`, uses removed `FastMCP`);
  add a real streamable-HTTP server test (none exists); error-classification tests use exception
  shapes v2 actually raises.

## Verification

- Each of the eight silent sites has a test that FAILS on a v2 bump with today's code and passes
  after: structured result returned; `is_error` result → tool-error action; discovered schemas
  non-empty; HTTP 401 vs 429 vs 500 diagnostics per Q3; dead stdio server → one reconnect; server
  pass-through message visible to a client.
- Real servers: a v2 server over stdio AND streamable HTTP, driven through `pflow run`, `pflow
  probe` and `pflow mcp add/sync`; a real 1.x-era peer (e.g. `chrome-devtools-mcp` pinned, or a
  subprocess `uvx --with 'mcp<2'` fixture) proves the legacy direction.
- `pflow mcp serve` driven by a raw client session: tools and resources succeed, errors carry
  pflow's text, stray tool output lands on stderr.
- Real surface: `uv run pflow` workflows using an MCP node against a live server; `make
  test-all-local`; the `tests-windows` CI gate (subprocess/stdio).

## References

- Research (gathered, cited, labelled VERIFIED/INFERRED/UNVERIFIED):
  `starting-context/mcp-sdk2-migration-research-2026-09-30.md` — upstream timeline, rename
  table, wire matrix, full exposure map, test exposure, 12 open questions.
- Issues: #644 (part 1 pinned `<2`; part 2 = this task), #624 (stateless-spec research + the
  `mcp-proxy` pattern; orthogonal to this task), #652 (stdout reservation — MCP half deleted
  here), #636 (content-block type dispatch — keep).
- Upstream: `modelcontextprotocol/python-sdk` `docs/migration.md` @ v2.2.0; spec
  https://modelcontextprotocol.io/specification/2026-07-28/; `sparfenyuk/mcp-proxy#235`.
