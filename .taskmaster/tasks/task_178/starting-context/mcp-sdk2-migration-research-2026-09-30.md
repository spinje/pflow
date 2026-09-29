# MCP SDK 2.x / spec 2026-07-28 migration: research for the task spec

Researched 2026-09-30 against pflow `main` @ `08e1eb68` (locked `mcp` 1.26.0).

**Labels.**
- **VERIFIED** means I checked it myself, either by reading a primary source (quoted) or by running code. Scratch harnesses live in this session's scratchpad (`v2/` venv with `mcp==2.2.0`; pflow's `.venv` stands in for 1.26). None of them touched the repo.
- **INFERRED** means reasoned from sources but not executed.
- **UNVERIFIED** means I could not check it.

This is gathering only. Implementation shapes are listed as open questions (section 5), not chosen.

---

## 0. Headline

**A one-step migration is feasible.** Upgrading the SDK does not force pflow to go "modern-only" or break either side of the ecosystem:

- **Client side, VERIFIED by a wire matrix (section 2).** A v2 client using the lowlevel `ClientSession` + `initialize()` talks to 1.26 servers over stdio and streamable HTTP. So does v2 `Client(mode="auto")`, which probes `server/discover` and falls back to `initialize`. The same holds against real `chrome-devtools-mcp@1.10.1` and `@playwright/mcp@0.0.83` over stdio.
- **Server side, VERIFIED.** A v2 `MCPServer` serves a 1.26 client over stdio and HTTP; the v2 SDK is dual-era by default.
- **The deadline pressure is real but narrow.** Only a *modern-only* server rejects pflow's current 1.26 client:
  - The spec makes legacy support optional for servers (MAY).
  - The TS SDK makes modern-only an explicit opt-in (`legacy: 'reject'`).
  - I found no modern-only server among the ones pflow users connect to.

**Two pieces of risk decide the migration's scope:**
1. **Silent-failure renames in pflow's result and schema handling** (camelCase attributes read through `hasattr`).
2. **The pflow MCP server's exception boundary**, which depends on SDK internals that changed.

Both are VERIFIED below. The mechanical renames (`FastMCP`→`MCPServer`, `streamablehttp_client`→`streamable_http_client`) are the easy part.

---

## 1. Upstream changes (SDK 1.x → 2.x, spec 2025-11-25 → 2026-07-28)

Primary sources:
- **Migration guide:** `docs/migration.md` @ tag `v2.2.0` (2884 lines), fetched via `gh api repos/modelcontextprotocol/python-sdk/contents/docs/migration.md?ref=v2.2.0`. Line refs below are to that file.
- **Release notes:** `gh api repos/modelcontextprotocol/python-sdk/releases/tags/<tag>`.
- **Spec:** https://modelcontextprotocol.io/specification/2026-07-28/…

### 1.1 Release timeline and 1.x status (VERIFIED)

| Tag | Published |
|---|---|
| v1.26.0 (pflow's lock) | 2026-01-24 |
| v2.0.0a1 | 2026-06-11 |
| v2.0.0rc1 | 2026-07-27 |
| **v2.0.0** | **2026-07-28** |
| v1.29.0 | 2026-07-28 ("Move the v1.x docs to /v1/ and mark v1.x as the maintenance line") |
| v2.1.0 / v1.29.1 | 2026-08-24 |
| v2.0.1 / v2.1.1 | 2026-08-25/26 |
| **v2.2.0** (latest; `pypi.org/pypi/mcp/json` → 2.2.0) | 2026-09-07 |
| **v1.30.0** (latest 1.x) | 2026-09-07 |

- **v2.0.0 release notes:** "**v1.x is in maintenance mode and will only receive security fixes from now on** … continues to receive critical bug fixes and security patches … If your project is not ready to migrate, keep a `<2` upper bound on your requirement (for example `mcp>=1.28,<2`)."
- **`VERSIONING.md` @ v2.2.0 L37-38:** "**2.x** (`main`) — bug fixes, security fixes, and features. **1.x** (`v1.x`) — critical bug fixes and security fixes."
- **No end-of-life date for 1.x is published.** VERIFIED absence in `VERSIONING.md`, the release notes and the migration guide.
- **1.x keeps changing defaults in maintenance.** v1.30.0 "Behaviour changes" covers same-origin-only redirects, idle Streamable HTTP sessions expiring after 30 min, and OAuth issuer checks. Staying on 1.x is not frozen either.
- **mcp 2.2.0 metadata (VERIFIED, PyPI JSON):** `requires_python >=3.10`, which matches pflow's `>=3.10`. It is the same for 1.26.

### 1.2 Renamed and removed APIs that pflow touches (VERIFIED by import in the 2.2.0 venv unless noted)

| v1 | v2 | Evidence |
|---|---|---|
| `from mcp.server.fastmcp import FastMCP` | `from mcp.server.mcpserver import MCPServer` | Import raises `ModuleNotFoundError: … FastMCP was renamed to MCPServer …` (the stub module `mcp/server/fastmcp.py` exists only to raise). Guide L645. |
| `mcp.server.fastmcp.exceptions.{ToolError, ResourceError}` | `mcp.server.mcpserver.exceptions.{ToolError, ResourceError}`, plus new `UnexpectedToolError`, `UnexpectedResourceError`, `ResourceNotFoundError` (all subclasses of `ToolError`/`ResourceError`, see 1.6) | Guide L668; `dir()` of module |
| `mcp.client.streamable_http.streamablehttp_client(url, headers, timeout, sse_read_timeout, auth, terminate_on_close)` → 3-tuple `(read, write, get_session_id)` | `streamable_http_client(url, *, http_client=None, terminate_on_close=True)` → **2-tuple** `(read, write)` | `inspect.signature` in 2.2.0. Guide L2065-2113: "`headers`, `timeout`, `sse_read_timeout`, `auth`: set them on the `httpx2.AsyncClient` … a bare `httpx2.AsyncClient()` falls back to httpx2's flat 5-second timeout … set `timeout=httpx2.Timeout(30, read=300)` … Omitting `http_client` still gives you a default client with those timeouts." |
| `get_session_id` callback | removed | Guide L2115-2119 |
| `mcp.shared.exceptions.McpError` | `MCPError` (also `from mcp import MCPError`); constructor `MCPError(code, message, data)` | Guide L558. `ImportError: … Did you mean: 'MCPError'?`. `str(MCPError(-32603,'x'))` == `'x'` (no `McpError:` prefix). |
| pydantic fields camelCase (`structuredContent`, `isError`, `inputSchema`, `outputSchema`, `mimeType`, …) | **snake_case attributes** (`structured_content`, `is_error`, `input_schema`, …). The wire format is unchanged; constructors accept both spellings. | Guide L287-340. **Attribute access by the camel name is gone:** `hasattr(result, "structuredContent")` → **False**, `hasattr(result, "isError")` → **False**, `hasattr(tool, "inputSchema")` → **False**. `model_dump()` emits snake_case unless `by_alias=True`. |
| `httpx` / `httpx-sse` | `httpx2` (a fork; the SDK no longer installs `httpx`) | Guide L102-188: "an old `except httpx.ConnectError:` block keeps importing fine and simply never matches again." |
| `MCPServer` positional order `name, instructions, …` | `name, title, description, instructions, …` | Guide L711-734 (pflow passes `instructions=` by keyword, so it is unaffected) |
| Unversioned server reports the SDK version | reports `""` | Guide L736 |
| Default server name `FastMCP` | `mcp-server` | Guide L689 (pflow passes `"pflow"`, so it is unaffected) |
| `MCPServer.call_tool(name, arguments)` returned a `(content, structured)` tuple | `call_tool(name, arguments, context=None) -> CallToolResult \| InputRequiredResult`; `read_resource(uri, context=None)` likewise | `inspect.signature`; Guide L929-961. Measured in 1.26: `FastMCP.call_tool` → tuple; in 2.2: `CallToolResult`. |
| `mcp.shared.memory.create_connected_server_and_client_session` | removed; use `Client(server)` | Guide L2688 |
| `ClientSession` timeouts as `timedelta` | `float` seconds | Guide L1883 (pflow passes no SDK timeout, so it is unaffected) |
| WebSocket transport | removed | Guide L2305 (pflow doesn't use it) |

**Unchanged (VERIFIED by import):**
- `from mcp import ClientSession, StdioServerParameters`
- `from mcp.client.stdio import stdio_client`, same `(server, errlog=)` signature
- `from mcp import types`, `from mcp.types import CallToolResult, TextContent, ImageContent, ToolAnnotations`. `mcp.types` is "a permanent alias" of the new `mcp-types` package (Guide L202-215).
- `ClientSession.initialize()` still exists and still does the pre-2026 handshake. Guide L1798: "a lowlevel `ClientSession` you `initialize()` yourself always performs the pre-2026 handshake, and `ClientSession.discover()` is the explicit 2026-07-28 entry point."
- `@mcp.tool()` / `@mcp.resource()` decorators. Guide L677-687 lists "What is unchanged on `MCPServer`".
- `mcp.run("stdio")`.

### 1.3 Session and `initialize` removal, and what replaces it (VERIFIED, spec)

- **Changelog** (https://modelcontextprotocol.io/specification/2026-07-28/changelog; quoted in session-08 report and re-verified via the transport page):
  - Sessions and `Mcp-Session-Id` are removed (SEP-2567).
  - `initialize`/`notifications/initialized` is removed (SEP-2575): "Every request now carries its protocol version and client capabilities in `_meta`."
  - The GET stream and `Last-Event-ID` resumability are removed.
- **Streamable HTTP page, top Info box:** "Revision 2026-07-28 changed the behavior of Streamable HTTP … Removal of the GET stream endpoint. Removal of protocol-level sessions."
- **Versioning page:** "There is no negotiation handshake. Every request carries its protocol version, and the server accepts or rejects each request independently." Also: "Servers **MUST** implement `server/discover`. Clients **MAY** call it before sending any other requests."
- **Replacement for state:** state is carried in explicit server-minted handles passed as ordinary tool arguments. This is a tool-design pattern, not a protocol feature (SEP-2567, quoted in `scratchpads/session-08/mcp-stateless-research.md` §(b)1). **Nothing in the client API replaces session state.** The v2 `Client` exposes `prior_discover=` only to skip the negotiation round trip (`docs/protocol-versions.md` @ v2.2.0 L95-116).
- **Server-to-client requests** (sampling, elicitation, roots) become MRTR on modern connections: `InputRequiredResult` plus a client retry. **INFERRED:** this doesn't touch pflow, whose client registers no sampling/elicitation callbacks and whose server tools don't elicit. v2 `ClientSession.call_tool(..., allow_input_required=False)` raises `RuntimeError` if a server returns `InputRequiredResult` (`mcp/client/session.py` L383, L952-966 in 2.2.0; VERIFIED by reading).

### 1.4 Transport changes

**stdio (VERIFIED, Guide L2241-2303):**
- Same API.
- Shutdown rework: "a gracefully-exited server's children are left alive on POSIX." Before, `stdio_client`'s tree-kill attempt usually failed anyway.
- "a failed write to a server that is still running now surfaces as a closed connection (`CONNECTION_CLOSED`) … instead of a raw `BrokenResourceError`."
- The server side (`stdio_server`) moves the wire to private fds and points fd 1 at stderr while serving, so child-process stdout can no longer corrupt the protocol.

**Streamable HTTP (client):**
- Rename and param move (table above).
- `terminate_on_close=True` is still the default. VERIFIED: the v2 client sends `DELETE /mcp` on exit to a v2 server, per the server log `"DELETE /mcp HTTP/1.1" 200 OK`.
- **Error surfacing changed (VERIFIED by running v1 and v2 clients against a stub HTTP server returning fixed statuses):**

| Server response | 1.26 leaf exception | 2.2 leaf exception |
|---|---|---|
| 401 | `httpx.HTTPStatusError` (has `.response.status_code`) | `MCPError(-32603, 'Server returned an error response')`, `data=None` |
| 500 | `httpx.HTTPStatusError` | same `MCPError(-32603, …)`, `data=None` |
| 404 before a session exists | `McpError('Session terminated')` | `MCPError('Not Found')` (guide: code -32601) |
| connection refused | `httpx.ConnectError` | `httpx2.ConnectError` (same class name) |

Guide L2178-2231 agrees: "In v2 the transport no longer raises for HTTP status errors: the failing request gets a JSON-RPC error … Any other 4xx/5xx → `MCPError(-32603, 'Server returned an error response')`." **The HTTP status code is not recoverable from the exception.** The guide shows `httpx2` `event_hooks` as the way to see raw responses (L2145-2160).

**Streamable HTTP (server):**
- A 4 MiB request-body limit applies.
- Idle legacy sessions expire after 30 min (v2.2.0 notes).
- Transport kwargs move to `run()`.
- pflow's server is stdio-only (`mcp_server/main.py:65`), so none of these apply today.

**Client era negotiation (VERIFIED, Guide L1792-1800; `docs/protocol-versions.md`):**
- `Client(target)` defaults to `mode='auto'`: probe `server/discover`, fall back to `initialize`.
- `mode='legacy'` forces the handshake.
- `mode='2026-07-28'` pins the version.
- Server-initiated requests need `legacy` (they raise `NoBackChannelError` on modern connections).

**Outbound `_meta` and OpenTelemetry (VERIFIED, Guide L2664-2684):** every request now carries `"_meta": {}`, and OpenTelemetry spans are on by default (no-op without a configured tracer provider). `opentelemetry-api` becomes a hard dependency.

### 1.5 Structured content and tool result shape (VERIFIED)

- **Wire shape unchanged.** `structuredContent`/`isError` stay camelCase on the wire. Only the Python attribute names change (Guide L289).
- `model_dump(mode="json", by_alias=True, exclude_none=True)` on content blocks gives the same wire-shaped dict. Run in 2.2: `ImageContent(... mimeType=..., _meta=...)` → `{'type':'image','data':'aGk=','mimeType':'image/png','_meta':{'page':2}}`. `EmbeddedResource` behaves the same.
- **Server-side structured output** of an `async def f() -> dict[str, Any]` tool is identical in both versions: `content=[TextContent(json)]`, `structured_content={'a':1}`. A `-> str` tool gives `{'result': 'hello'}` in both (measured).
- **v2.1.0 change** (release notes): "a tool annotated to return `TextContent`, `EmbeddedResource`, `Image`, `Audio` … no longer advertises `outputSchema` or returns `structuredContent`." pflow's tools return `str`/`dict`, so this doesn't apply.
- **v2 client validates inbound results against the negotiated schema** (Guide L2656): "Spec-invalid server output that the previous monolith parse tolerated may now raise `pydantic.ValidationError` from `list_tools()`, `call_tool()`." This is a new failure mode against sloppy third-party servers. UNVERIFIED which real servers trip it; chrome-devtools and Playwright `list_tools` passed.
- **"Extra fields on MCP types are no longer preserved"** (Guide L342). Unknown result keys are dropped.
- **`MCPError` raised inside a server tool now surfaces as a JSON-RPC error**, which the v2 client *raises*, instead of `isError=True` (Guide L984-1017). This changes what pflow's MCP node sees from v2 servers that raise `MCPError` in tools.

### 1.6 Server exception behaviour (VERIFIED by running v2 `MCPServer` directly)

| Situation | 1.26 (pflow's `_unwrap_cause` docstring, `server.py:73-80`) | 2.2 measured |
|---|---|---|
| Unknown tool | `ToolError("Unknown tool: X")`, no cause/context | **same**: `ToolError('Unknown tool: nope')`, cause/context None |
| Tool raises `KeyError` | `ToolError(...) from e` | `UnexpectedToolError('Error executing tool boom')`, `__cause__=KeyError`; `UnexpectedToolError` ⊂ `ToolError` |
| Unknown resource | `ValueError("Unknown resource: …")` or `ResourceError(…)` | `ResourceNotFoundError('Unknown resource: pflow://missing')` ⊂ `ResourceError`, not a `ValueError`; the prefix is unchanged |
| Resource fn raises | `FunctionResource` wraps as `ValueError("Error reading resource …")`, then `ResourceError(str(e))` | `UnexpectedResourceError('Error reading resource pflow://r')`, `__cause__=KeyError`. **The `ValueError` layer is gone.** |
| Tool raises `ValueError(msg)` and the SDK default handles it (pflow's "pass-through" path) | client sees `"Error executing tool val: <msg>"` (measured with 1.26 in-memory) | client sees **`"Error executing tool val"`, with the message dropped**. v2.1.0 notes: "the client now sees only `Error executing tool <name>` … Raise `ToolError` / `ResourceError` when the message is meant for the model." A `ToolError("text")` still reaches the client as `"Error executing tool terr: text"`. |
| Subclass override with the v1 signature `call_tool(self, name, arguments)` | fine | **every call fails**: `TypeError: P.call_tool() takes 3 positional arguments but 4 were given`, returned as `is_error=True`. `read_resource` fails the same way (a loud failure). |

---

## 2. Backward compatibility

### 2.1 Wire matrix I ran (VERIFIED)

The test server is `srv.py`: one `echo` tool returning `dict[str, Any]` and one `fail` tool that raises. It runs on 1.26 (`FastMCP`) or 2.2 (`MCPServer`). The clients are pflow-style `ClientSession`+`initialize()` in each SDK, plus v2 `Client`. "OK" means `initialize`/discover, `list_tools`, `call_tool` with the correct `structured` content, and `fail` returning `is_error=True`.

| Client → Server | stdio | streamable HTTP |
|---|---|---|
| 1.26 session → 1.26 | OK (2025-11-25) | OK, session id issued |
| 1.26 session → **2.2** | **OK** (2025-11-25) | **OK**, session id issued |
| 2.2 `ClientSession.initialize()` → **1.26** | **OK** (2025-11-25) | **OK** |
| 2.2 `ClientSession.initialize()` → 2.2 | OK (2025-11-25, legacy era) | OK (2025-11-25) |
| 2.2 `Client(mode="auto")` → 1.26 | OK, falls back to 2025-11-25; the 1.26 server logs a pydantic validation error for the unknown `server/discover` on its stderr | OK, fallback |
| 2.2 `Client(mode="auto")` → 2.2 | OK, **2026-07-28** | OK, **2026-07-28** |
| 2.2 `Client(mode="2026-07-28")` → 1.26 | **FAIL** `MCPError: Invalid request parameters` | **FAIL** `MCPError: Bad Request: Missing session ID` |

**Real ecosystem servers over stdio (VERIFIED, `npx`):**

| Server | 1.26 client | 2.2 `ClientSession.initialize()` | 2.2 `Client(auto)` |
|---|---|---|---|
| `chrome-devtools-mcp@1.10.1` (its `package.json` on GitHub main pins `@modelcontextprotocol/{client,core,server}` `2.0.0`) | OK, 30 tools | OK | OK, **negotiated 2025-11-25** |
| `@playwright/mcp@0.0.83` (Playwright repo `package.json` pins `@modelcontextprotocol/sdk` `1.29.0`) | OK, 25 tools | (not run) | OK, 2025-11-25 |

UNVERIFIED: why chrome-devtools' auto probe landed on 2025-11-25 despite the TS SDK 2.0 dep. The published npm artifact may bundle an older SDK, or its stdio entry may not answer `server/discover`. It doesn't matter for compatibility: every client style works.

### 2.2 What the spec says (VERIFIED, versioning page, "Compatibility Matrix")

- "Modern | Legacy | **Fails**."
- "Dual-era | Legacy | **Works**. stdio: the probe returns a non-modern error or times out, and the client falls back to `initialize`."
- "Legacy | Modern | **Fails**. … Legacy clients have no fall-forward mechanism."
- "Legacy | Dual-era | **Works**."
- "A server that wishes to support both legacy clients … and modern clients … **MAY** implement both behaviors."

So a modern-only server is spec-legal. Against one, **pflow's current 1.26 client fails, and so would a v2 port that keeps `ClientSession.initialize()`**. Only a dual-era client works against both eras.

**The ecosystem posture (VERIFIED, TS SDK `docs/serving/legacy-clients.md` on `main`):**
- "The default, `legacy: 'stateless'`, serves each legacy request from a fresh instance … `legacy: 'reject'` makes the endpoint modern-only."
- On stdio, "`serveStdio` takes the same option with a different default — `'serve'`."
- Under the HTTP default, "a legacy `GET` … and `DELETE` … answer `405`."

**INFERRED:** modern-only servers exist only by explicit author choice, so the "deadline" is gradual. A legacy client talking to a TS-v2 default HTTP server gets per-request fresh server instances, with no cross-call state even within one pflow run. Modern clients get the same by design.

### 2.3 pflow's server serving 1.x clients (Claude Code, Claude Desktop, Codex)

- **VERIFIED for a Python 1.26 client over stdio and HTTP** against a v2 `MCPServer` (matrix above).
- v2.0.0 release notes: "still serves every 2025-era client from the same `MCPServer`, over Streamable HTTP and stdio, with nothing to configure."
- **UNVERIFIED with the actual Claude Code / Claude Desktop / Codex binaries.** They send `initialize` like any legacy client, so INFERRED to work.

**Conclusion:** both directions stay compatible through one SDK bump. What stays open is *which client era pflow speaks* (section 5, Q1), not whether the bump can be one step.

---

## 3. pflow's exposure (every SDK touchpoint in `src/pflow`)

Found with `grep -rnE "from mcp|import mcp|streamablehttp|FastMCP|ClientSession|stdio_client|structuredContent|isError|inputSchema|…" src/pflow`. There are no `mcp` imports outside these files. `nodes/shell/shell.py:416` is a false positive: a docstring template string.

**Classes:**
- **U** = unchanged
- **R** = renamed or reshaped (fails loudly at import or call)
- **S** = semantics changed (still runs, behaves differently; **S!** = silently wrong)
- **X** = removed

### 3.1 Client: connection pool (`src/pflow/mcp/pool.py`, used by `pflow run` via `execution/runner.py:198,663,905`)

| # | Site | What | Class |
|---|---|---|---|
| 1 | `pool.py:24` | `from mcp import ClientSession, StdioServerParameters` | U |
| 2 | `pool.py:25` | `from mcp.client.stdio import stdio_client` | U |
| 3 | `pool.py:26,86,253,272,287` | `CallToolResult` type; v2 `ClientSession.call_tool` is annotated `CallToolResult \| InputRequiredResult \| Result` (mypy impact) | U (import) / S (typing) |
| 4 | `pool.py:196-208` | `StdioServerParameters(...)`, `stdio_client(params, errlog=)` | U. Shutdown: children of a gracefully-exited server are left alive on POSIX (Guide L2241); pflow's pool comment says `shutdown()` "kills all servers" (`pool.py:11,306`) |
| 5 | `pool.py:209-210` | `ClientSession(read, write)` + `await session.initialize()` (stdio) | U API; S: legacy handshake only, fails against a modern-only server (section 2.2) |
| 6 | `pool.py:220` | `from mcp.client.streamable_http import streamablehttp_client` | **X/R** (ImportError; v1.26 already exports `streamable_http_client` too) |
| 7 | `pool.py:232-240` | `streamablehttp_client(url, headers=, timeout=, sse_read_timeout=, terminate_on_close=True)` → `(read, write, _get_session_id)` | **R**: params move to an `httpx2.AsyncClient`; 2-tuple |
| 8 | `pool.py:238` | `terminate_on_close=True` | U (default True; DELETE still sent, VERIFIED) |
| 9 | `pool.py:241-242` | `ClientSession` + `initialize()` (HTTP) | U API / S (as #5) |
| 10 | `pool.py:284,289` | `await session.call_tool(tool, arguments)` | U signature; S: raises `MCPError` for non-2xx and for server tools that raise `MCPError` (previously `isError` results or `HTTPStatusError`) |
| 11 | `pool.py:31-56` | `_is_transport_error`: matches `BrokenPipeError/ConnectionError/OSError` or type name `ClosedResourceError` → evict and reconnect once | **S!**, VERIFIED: after a stdio server dies, the next call raises `anyio.ClosedResourceError` in 1.26 (retry fires) but `MCPError(-32000 CONNECTION_CLOSED, 'Connection closed')` in 2.2 (not an `OSError`, so **no reconnect**) |

**Session semantics pflow relies on:**
- **The pool is per run.** `runner.py:198` creates it, `runner.py:905` shuts it down. It keeps one `ClientSession` per server for the run (`pool.py:72`).
  - stdio: state survives within a run through process lifetime. That still works mechanically in 2026, but SEP-2567 says stdio servers "SHOULD NOT rely on process-lifetime state".
  - HTTP to a legacy server: the pool holds an `Mcp-Session-Id` for the run and sends DELETE at shutdown (`terminate_on_close=True`).
  - HTTP to a modern server: there is no session. The pool's "keep alive" then only saves reconnect cost, and server state must come from handles.
  - **INFERRED:** nothing in the pool breaks. Its reason to exist for HTTP weakens.
- **HTTP 404 "session expired"** (`errors.py:125-128`, `_STATUS_MAP[404]`) and `_is_transport_error` are the pool's only recovery signals, and both change (see #11 and #29).

### 3.2 Client: MCP node standalone path (`src/pflow/nodes/mcp/node.py`, used by `pflow probe` and MCP-server `registry_run`)

`node.py:257-271`: if `shared` has no `__mcp_pool__`, the node falls back to `asyncio.run(self._exec_async(...))`. `pflow probe` builds `shared_store = {}` with no pool (`cli/commands/_probe_impl.py:146-157`), so **probe uses this duplicate client**, a throwaway connection per call.

| # | Site | What | Class |
|---|---|---|---|
| 12 | `node.py:307-308` | lazy imports `ClientSession, StdioServerParameters`, `stdio_client` | U |
| 13 | `node.py:319,334-340` | stdio connect + `initialize()` + `call_tool` | U / S (as #5, #10) |
| 14 | `node.py:366-367` | lazy `streamablehttp_client` import | **X/R** |
| 15 | `node.py:386-396` | 5-kwarg call, 3-tuple, `get_session_id()` for debug logging | **R/X** |
| 16 | `node.py:402` | `call_tool` (HTTP) | U / S |

### 3.3 Client: result extraction (`node.py`, shared by the pool and standalone paths)

| # | Site | What | Class |
|---|---|---|---|
| 17 | `node.py:742-744` | `if hasattr(mcp_result, "structuredContent") and mcp_result.structuredContent is not None: return …` | **S!**, VERIFIED: `hasattr` is False in v2, so structured results are silently ignored and fall through to text-block parsing |
| 18 | `node.py:747-750` | `if hasattr(mcp_result, "isError") and mcp_result.isError:` → `{"error":…, "is_tool_error": True}` | **S!**, VERIFIED `hasattr` False: **tool errors stop being detected**, the error text becomes `result` and the node returns `"default"` (success) |
| 19 | `node.py:693-697,713,771` | `.content`, `content.text`, `content.type` | U |
| 20 | `node.py:707-708` | `content.model_dump(mode="json", by_alias=True, exclude_none=True)` | U, VERIFIED identical wire dict |
| 21 | `engine/api_warning_detector.py:250` | `output.get("isError") is True` on the *dict* result | U (wire/JSON dicts keep camelCase); INFERRED |

### 3.4 Client: discovery (`src/pflow/mcp/discovery.py`, used by `pflow mcp add/sync`)

| # | Site | What | Class |
|---|---|---|---|
| 22 | `discovery.py:10-11` | `ClientSession, StdioServerParameters`, `stdio_client` | U |
| 23 | `discovery.py:149-166` | stdio connect, `initialize()`, `list_tools()` | U / S (as #5). `list_tools()` without cursor: only the first page, before and after (pflow never paginates). UNVERIFIED whether the v2 Python `ClientSession.list_tools()` auto-follows `nextCursor`; the TS SDK 2.2 does ("List calls return the whole list") |
| 24 | `discovery.py:176-189` | `hasattr(tool, "inputSchema")` / `tool.inputSchema`, `hasattr(tool, "outputSchema")` | **S!**, VERIFIED `hasattr` False: **every discovered tool gets the fallback empty schema** `{"type":"object","properties":{},"required":[]}` and no output schema. This flows into `registrar.py:347-374` (params, `original_schema`, `output_schema`) and so into the registry, validation and `pflow describe` |
| 25 | `discovery.py:207-208` | lazy `streamablehttp_client` import | **X/R** |
| 26 | `discovery.py:225-236` | 4-kwarg call, 3-tuple, `get_session_id()` for logging (no `terminate_on_close`, default True) | **R/X** |
| 27 | `discovery.py:250-263` | same camelCase `hasattr` reads (HTTP path) | **S!** |
| 28 | `mcp/types.py:52-53` | pflow's own `TypedDict` with `inputSchema`/`outputSchema` keys (a pflow dict, not SDK) | U (it is fine if producers write camelCase keys) |

### 3.5 Client: error classification (`src/pflow/mcp/errors.py`, used by `MCPNode.exec_fallback` `node.py:503-509` and discovery `discovery.py:93-98`)

| # | Site | What | Class |
|---|---|---|---|
| 29 | `errors.py:44-46,114-181` | `type(root).__name__ == "HTTPStatusError"` → `_STATUS_MAP` 401/403/404/429/5xx diagnostics | **S!**, VERIFIED: v2 never raises it for status errors; 401 and 500 both become a generic `MCPError(-32603,'Server returned an error response')`, `data=None`, **with the status code lost**. The auth/rate-limit/5xx diagnostics go dead and fall to the generic branch |
| 30 | `errors.py:48-66` | name `"ConnectError"` (SSL vs connect) | U by name (`httpx2.ConnectError`, VERIFIED) |
| 31 | `errors.py:68-77` | name `"TimeoutException"` | U by name (class exists in httpx2). INFERRED: pflow's outer `asyncio.timeout` usually fires first; SDK read timeouts now raise `MCPError(-32001)` (Guide L1933) |
| 32 | `errors.py:103-106` | regex `McpError: (.+?)` on the message | R (harmless): v2 `str(MCPError)` has no prefix; pflow tests hard-code the v1 text |
| 33 | `errors.py:125-128` | 404 = "Endpoint not found or session expired." | S: 404 is now `MCPError('Not Found')` or `('Session terminated')`, not `HTTPStatusError` |

### 3.6 Client: config and auth plumbing (no SDK import, but it feeds the reshaped call)

| # | Site | What | Class |
|---|---|---|---|
| 34 | `mcp/manager.py:322` | per-server `timeout` / `sse_timeout` config ("used by streamablehttp_client") | S: must map onto `httpx2.Timeout(timeout, read=sse_timeout)` on an `httpx2.AsyncClient` |
| 35 | `mcp/auth_utils.py` `build_auth_headers` (called `pool.py:222`, `node.py:377`, `discovery.py`) | header dict | S: goes on the `httpx2.AsyncClient(headers=…)` |
| — | `httpx` elsewhere (`core/tts.py`, `core/litellm_runtime.py`, `cli/commands/ui.py`) | pflow's own direct `httpx>=0.18` dependency (`pyproject.toml:38`) | U: the guide says httpx and httpx2 "install side by side". `cli/logging_config.py:44` silences `httpx._client`; the SDK's HTTP logs would now come from `httpx2`/`httpcore2` loggers |

### 3.7 Server (`src/pflow/mcp_server/`)

| # | Site | What | Class |
|---|---|---|---|
| 36 | `server.py:15` | `from mcp import types` | U |
| 37 | `server.py:16` | `from mcp.server.fastmcp import FastMCP` | **R** |
| 38 | `server.py:17` | `from mcp.server.fastmcp.exceptions import ResourceError, ToolError` | **R** (path) |
| 39 | `server.py:156` | `class PflowMCP(FastMCP)` | **R** |
| 40 | `server.py:166-172` | `call_tool(self, name, arguments)` override | **R**, VERIFIED: the v2 dispatcher passes `context`, so every tool call fails with TypeError until the override accepts `context` and forwards it |
| 41 | `server.py:176-186` | unknown-tool detection: `ToolError`, no cause/context, prefix `"Unknown tool:"` | U, VERIFIED |
| 42 | `server.py:182-185,202-205` | `types.CallToolResult(content=[types.TextContent(...)], isError=True)` | U (camelCase kwargs still construct; VERIFIED) |
| 43 | `server.py:29-52,188-199` | `_PASS_THROUGH_TYPES` (`ValueError, TypeError, RuntimeError, FileExistsError`) re-raised "so FastMCP's default handling surfaces their rendered text unchanged" | **S!**, VERIFIED: in v2.1+ the SDK default hides the message (`"Error executing tool <name>"`), so **every pass-through error reaching agents over MCP loses its text**. The module comment says services raise pre-formatted `ValueError`s by design (issue #325 follow-up) |
| 44 | `server.py:57-95` | `_is_function_resource_wrapper` + `_unwrap_cause` walking wrapper layers | S: the `ValueError("Error reading resource …")` layer is gone (dead code); `UnexpectedToolError`/`UnexpectedResourceError` still subclass `ToolError`/`ResourceError` with `__cause__`, so the walk still reaches the original (VERIFIED MRO + cause) |
| 45 | `server.py:208` | `read_resource(self, uri)` override | **R**, VERIFIED (`context` arg; fails like #40) |
| 46 | `server.py:210-219` | unknown resource caught as `(ResourceError, ValueError)` + prefix `"Unknown resource:"`; re-raised as `ResourceError(rendered)` | S: now `ResourceNotFoundError` (still caught, prefix matches, VERIFIED). But v2 maps `ResourceNotFoundError` to JSON-RPC `-32602` with `{"uri":…}` (Guide L1019), and pflow's re-raise as plain `ResourceError` may change the code clients see. UNVERIFIED which code results |
| 47 | `server.py:220` | `str(r.uri)` over `list_resources()` | U (uri is now `str`) |
| 48 | `server.py:250-272` | `PflowMCP("pflow", instructions=…)` | U (keyword). S (display): `serverInfo.version` becomes `""` unless `version=` is passed |
| 49 | `main.py:65` | `mcp.run("stdio")` | U. S (benign): the stdio fd diversion means child stdout (shell nodes run by `workflow_execute`) goes to stderr instead of possibly corrupting the wire |
| 50 | `tools/*.py` | 13 `@mcp.tool()` `async def` tools (discovery 2, execution 7, registry 2, workflow 2), each offloading via `asyncio.to_thread` | U (decorator unchanged; async handlers stay on the loop) |
| 51 | `resources/instruction_resources.py:61,103,127,153` | 2 `@mcp.resource()` **sync** `def` | S (benign): sync handlers now run on a worker thread (Guide L909) |
| 52 | `mcp_server/CLAUDE.md:36,53` | prose naming FastMCP / the CallToolResult boundary | doc update |

### 3.8 Counts by class (the 52 enumerated sites above, per-site call/field use; #28 and #21 are pflow-dict sites counted as U)

| Class | Count | Sites |
|---|---|---|
| **U** (unchanged) | 22 | 1, 2, 4, 8, 12, 19, 20, 21, 22, 28, 30, 31, 36, 41, 42, 47, 49, 50, plus the U halves of 3, 5/9/13/23 (the imports and constructor calls) |
| **R/X** (renamed / reshaped / removed; loud) | 13 | 6, 7, 14, 15, 25, 26, 32, 37, 38, 39, 40, 45 + `get_session_id` uses (7/15/26 counted once each) |
| **S** (semantics changed, still runs) | 11 | 3 (typing), 5/9/13/23 (legacy-only handshake), 10/16 (MCPError raising), 33, 34, 35, 44, 46, 48, 51 |
| **S!** (silently wrong) | 8 | **11** (no reconnect), **17** (structured ignored), **18** (tool errors read as success), **24**, **27** (empty schemas), **29** (HTTP status diagnostics dead), **43** (server error text dropped) |

The "U" and "S" counts overlap on the connect lines (5/9/13/23 are U-API/S-era). The load-bearing number is the **8 silent-failure sites**. There are **3 client connect implementations** (`pool.py`, the `node.py` fallback, `discovery.py`), each with stdio and HTTP, making **6 connect paths** to port.

---

## 4. Related pins and tests

### 4.1 Upstream pins

- **sparfenyuk/mcp-proxy #235 is still OPEN** (VERIFIED `gh issue view 235 -R sparfenyuk/mcp-proxy`, created 2026-07-28, "Unbounded `mcp>=1.17.0` dependency lets `uvx mcp-proxy` resolve `mcp==2.0.0`, which removed `request_ctx` — every ephemeral run crashes on import"). The latest comment, from 2026-09-24, independently reproduces with mcp 2.2.0: "pinning mcp>=1.27.1,<2 resolved mcp 1.30.0 and restored startup".
  - Latest release **v0.12.0 (2026-05-14)**. `main` `pyproject.toml:31` still declares `"mcp>=1.27.1"` with no upper bound. There is no 2.x-compatible release.
  - pflow already documents the workaround: `docs/reference/nodes/mcp.mdx:115` and `src/pflow/guide/nodes/mcp.md:153`, `uvx --with 'mcp<2' mcp-proxy …`. **INFERRED:** this is independent of pflow's own pin, because it runs in the uvx tool env, so pflow's migration does not change it.
- **claude-agent-sdk** (pflow dependency `>=0.2.82`, locked **0.2.82**) also depends on `mcp`. VERIFIED from PyPI `requires_dist` history:
  - 0.2.82: `mcp>=1.23.0`
  - **0.2.96–0.2.139: `mcp<2.0.0,>=1.23.0`**
  - ≥**0.2.140**: `mcp<3.0.0,>=1.23.0` (latest 0.2.162, 2026-09-29, ships `_internal/_mcp_compat.py`)
  - VERIFIED: 0.2.82 and 0.2.162 both import cleanly (`claude_agent_sdk`, `_internal.query`, `client`) against mcp 2.2.0.
  - pflow's agent node passes no MCP servers to the SDK (`grep mcp src/pflow/nodes/agent/*.py` → none).
  - VERIFIED: `uv pip compile` of pflow's direct deps with `mcp[cli]>=2.2,<3` on Python 3.10 resolves (mcp 2.2.0, claude-agent-sdk 0.2.162, httpx 0.28.1 + httpx2 2.13.1). The actual `uv lock` on a scratch copy of the project was denied by the permission prompt, so **the real lockfile diff is UNVERIFIED**.
- **Transitive jumps a relock would bring (current lock → resolved):**

| Package | Current | Resolved |
|---|---|---|
| starlette | 0.47.3 | 1.7.0 |
| sse-starlette | 3.0.2 | 3.5.0 |
| anyio | 4.9.0 | 4.15.1 |
| pydantic | 2.12.5 | 2.13.5 |

  New packages: `httpx2`, `mcp-types`, `opentelemetry-api`. Removed: `pydantic-settings` (2.12.0 in the lock) is no longer pulled by mcp.
  - `starlette` 1.x matters for pflow's own web UI (`ui` extra `starlette>=0.40`; `src/pflow/ui/server.py`). **UNVERIFIED** whether the UI works on starlette 1.7. Starlette is only pulled in by the `mcp[cli]` resolution.
- `mcp[cli]` extra: nothing in `src/pflow` uses `typer`, `dotenv` or `mcp dev/install` (grep empty). The extra still exists in 2.2.0 (VERIFIED, installed `mcp[cli]==2.2.0`).

### 4.2 Test exposure (`tests/`)

**No test spins up an HTTP MCP server.** Exactly **one real stdio server fixture** exists: `tests/test_nodes/test_mcp/test_result_format_json_block.py:151-195` writes `from mcp.server.fastmcp import FastMCP` with `@mcp.tool(structured_output=False)` into a temp file and runs it as a subprocess (`@pytest.mark.e2e`). **It breaks on import under v2.** mcp-proxy appears in no test.

| File | Exposure | Under v2 |
|---|---|---|
| `test_mcp_server/test_exception_boundary.py:14-15,52-141` | imports `mcp.server.fastmcp.exceptions`; calls `mcp.call_tool(...)` directly; asserts `result.isError` / `result.structuredContent` | ImportError; then `AttributeError` on camelCase |
| `test_mcp_server/test_tool_registration.py:143-144` | `tool.inputSchema` | AttributeError |
| `test_mcp_server/test_analyze_cache_tool.py:130-165` | reaches into FastMCP's `FunctionTool` wrapper (`.fn`, `__wrapped__`) | UNVERIFIED (the guide says `Tool` internals keep their v1 shapes) |
| `test_mcp/test_connection_pool.py:3,59-60,85-86,143-144` | patches `pflow.mcp.pool.stdio_client/ClientSession/streamablehttp_client`; **MagicMock results with `.isError=False`, `.structuredContent=None`** | patch targets must be renamed; **the mocks mask the rename**: they would keep "passing" with unchanged code |
| `test_mcp/test_mcp_node_behavior.py:12,147-185,240,420-444` | `mcp.types` import; **MagicMocks with `structuredContent`/`isError`**; `"McpError: …"` strings | **masks S! sites #17/#18**; McpError text is v1-shaped |
| `test_nodes/test_mcp/test_result_format_json_block.py:16,30-39` | real `CallToolResult(structuredContent=…, isError=…)` objects | constructors accept camel kwargs, so these tests **would catch #17/#18** (they use real SDK objects, not mocks) |
| `test_nodes/test_mcp/test_content_blocks.py:15-108` | real content types with `mimeType=`; asserts by_alias dicts | U, VERIFIED dump identical |
| `test_nodes/test_mcp/test_json_text_parsing.py:5` | `mcp.types` import | U |
| `test_mcp/test_mcp_errors.py:45-141`, `test_mcp/test_http_transport.py:14-15,417-520` | build `httpx.HTTPStatusError` / `ConnectError` / `"McpError: …"` exceptions and feed `describe_mcp_error` | keep passing but **test exception shapes v2 never produces** (fidelity gap for S! #29) |
| `test_nodes/test_mcp/test_mcp_output_control.py:101` | comment only | U |
| `test_cli/test_mcp_commands.py:8` | pflow's own `mcp` click group, not the SDK | U |

`pyproject.toml:149-152` `filterwarnings` only errors on `EncodingWarning`. v2's `MCPDeprecationWarning` (a `UserWarning`) would show but not fail tests. pflow calls no deprecated method that I found (no ping, logging, roots or sampling).

---

## 5. Open questions the spec must settle

**Q1. Which client era does pflow speak?** This is the central design fork.

- **(a) Keep the lowlevel `ClientSession` + `initialize()`** (the smallest diff).
  - Assumes the servers pflow users use keep serving legacy clients.
  - Failure mode: fails against modern-only servers (spec: Legacy→Modern "Fails"), which is the same exposure as today.
  - Reversible.
- **(b) Move to v2 `Client(target, mode="auto")`** (dual-era, spec-recommended detection built in).
  - Works against both eras (VERIFIED matrix).
  - Costs one `server/discover` probe per connection. A legacy server logs an error on its stderr for the probe, which pflow routes to devnull unless verbose.
  - `Client` has a different surface: it takes `StdioServerParameters` or a URL string directly (v2.1.0), and `list_*` pagination differs. Whether it takes a pre-built `httpx2.AsyncClient` for headers/auth/timeouts is **UNVERIFIED**; I did not check `Client`'s HTTP transport injection.
- **(c) `ClientSession` with a hand-rolled `discover()`-then-`initialize()` fallback.** Reimplements (b).
- **Sub-question:** cache the era per server config (the spec says clients "MAY persist it across restarts") or re-probe each run?

**Q2. Probe's duplicate client (`node.py:257-402`).** The standalone path duplicates `pool.py`'s connect logic, and `pflow probe` depends on it. Port both, or have probe use a pool? The #624 ruling may bear on this. Either way the spec must name all 6 connect paths (3.8), or one gets missed.

**Q3. HTTP error diagnostics (S! #29).** With v2 the status code isn't in the exception. Options:
- (a) accept a generic "Server returned an error response" (a loss of agent-facing 401/403/429 guidance);
- (b) capture the status via an `httpx2` response `event_hook` on the `AsyncClient` pflow builds (Guide L2145);
- (c) classify by `MCPError.code`/message only.

Needs a decision plus a test that uses real v2 exception shapes, replacing the `httpx.HTTPStatusError` fixtures.

**Q4. Pool reconnect (S! #11).** Should `MCPError(code=CONNECTION_CLOSED -32000)` count as a transport error worth one reconnect? The v1 semantics ("dead peer → reconnect once, never on timeout") need re-expressing on v2's exception types. Also, a stdio server that crashes mid-call now gives `MCPError` on the *first* call too (VERIFIED: in 1.26 the first call gives `McpError('Connection closed')`, the second `ClosedResourceError`; in 2.2 both give `MCPError(-32000)`).

**Q5. Pflow MCP server pass-through (S! #43).** v2.1+ hides the text of non-`ToolError` exceptions from clients. To keep agents seeing pflow's pre-formatted `ValueError`/`TypeError`/`RuntimeError`/`FileExistsError` messages, the boundary must convert them. Options:
- (a) `ToolError(str(e))`, or
- (b) render them itself as `CallToolResult(is_error=True)`, which changes byte-level output ("Error executing tool X: …" prefix vs pflow's own).

Requires a "show before you code" before/after example per project rules (user-visible output).

**Q6. `terminate_on_close` / DELETE.**
- Against legacy servers, pflow's DELETE still frees sessions (VERIFIED on v2 servers).
- Against TS-v2 default HTTP servers, legacy DELETE answers 405 (TS docs). **UNVERIFIED** whether the v2 Python client logs a warning on 405.
- For a modern connection there's no session, so DELETE shouldn't be sent. INFERRED that the SDK handles this per era; unconfirmed.

Keep the explicit `terminate_on_close=True`?

**Q7. Timeouts mapping.** Today: `timeout` (default 30) and `sse_timeout` (default 300) from server config go straight to the SDK (`manager.py:322`). In v2 they go to `httpx2.Timeout(timeout, read=sse_timeout)`. Confirm the modern era, with no GET stream, still needs a long read timeout for per-request SSE responses (INFERRED yes, since tool calls can stream).

**Q8. Version bounds.**
- `mcp[cli]>=2.2,<3` or `>=2.0,<3`? The v2.1 exception-text change and the v2.2 redirect/session changes mean the floor chooses behaviour.
- Is `[cli]` still needed (nothing uses it)?
- Raise the `claude-agent-sdk` floor to `>=0.2.140`? Otherwise the resolver can only pick 0.2.82–0.2.95 (unbounded) or ≥0.2.140 (`<3`); it resolved to 0.2.162 in my compile.
- Starlette 0.47→1.7 for the web UI needs a check (UNVERIFIED).

**Q9. Test fidelity.** The pool and node-behaviour tests mock `isError`/`structuredContent` as attributes, so they can't catch the rename. Options:
- switch the fixtures to real `CallToolResult` objects, or
- add a real-server test (v2 `MCPServer` over stdio *and* streamable HTTP, plus a 1.x-era peer).

There is currently no HTTP transport test against a real server, and the one stdio e2e fixture uses the removed `FastMCP` import. A cross-era test needs a 1.x server in the test env, which can't co-install with mcp 2.x. Options: a subprocess `uvx --with 'mcp<2'` fixture (network), a stub, or skip.

**Q10. Structured output from the pflow server.** v2 clients validate results against the negotiated schema. The tools returning `dict[str, Any]` (`plan_workflow`, `analyze_cache`) produce the same `structured_content` (VERIFIED on a toy tool). **UNVERIFIED** against the actual pflow tools' output.

**Q11. Resource not-found wire code (#46).** Should pflow's rendered unknown-resource error keep v2's `-32602`+`{"uri":…}` (raise `ResourceNotFoundError(rendered)`) or accept whatever a plain `ResourceError` maps to? Not measured.

**Q12. #624 follow-ups** (handles, holder process). SDK 2 adds nothing that revives cross-process session replay: `get_session_id` is removed, and `prior_discover` only skips negotiation. **INFERRED:** the migration is orthogonal to the #624 ruling, and the docs lane's mcp-proxy guidance stays `mcp<2`-pinned until mcp-proxy #235 closes.

**Things I could not verify** (collected):
- a real `uv lock` diff;
- Claude Code / Desktop / Codex as clients of a v2 pflow server;
- v2 Python `list_tools` auto-pagination;
- `Client`'s injectable `httpx2` client;
- 405-on-DELETE logging;
- a starlette 1.x UI check;
- the resource-not-found wire code;
- why chrome-devtools-mcp negotiated 2025-11-25.

---

## Appendix: harnesses (session scratchpad, not in the repo)

`/private/tmp/claude-501/-Users-andfal-projects-pflow/154ca0bc-c047-4253-9469-a0388eb3305a/scratchpad/`:

| File | Purpose |
|---|---|
| `v2/` | venv with mcp 2.2.0 |
| `srv.py`, `cli.py` | era matrix |
| `cdt.py`, `pw.py` | chrome-devtools / Playwright |
| `status_cli.py`, `st_srv2.py` | HTTP status surfacing |
| `die_srv.py`, `die_cli.py` | dead-peer exception |
| `probe_server.py`, `probe_dict.py`, `passthru.py`, `override.py` | server behaviour |
| `migration.md`, `rel-*.md`, `VERSIONING.md`, `pv.md` | fetched upstream docs |
| `req.in`, `req310.txt` | dependency resolution |
