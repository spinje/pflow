# MCP Client Integration

This module connects pflow workflows to **external MCP servers** (Playwright, GitHub, Slack, etc.).

> **Not to be confused with `mcp_server/`** which exposes pflow *as* an MCP server for AI agents. This module is the MCP *client*.

## File Tree

```
mcp/
├── __init__.py        # Re-exports: MCPConnectionPool, MCPDiscovery, MCPRegistrar, MCPServerManager
├── types.py           # TypedDicts for server configs, tool schemas, registry entries
├── utils.py           # Parse mcp-<server>-<tool> names (handles hyphenated server names)
├── auth_utils.py      # Env var expansion (${VAR}, ${VAR:-default}) + auth header building
├── discovery.py       # Connect to MCP servers, list tools, convert schemas to pflow format
├── manager.py         # CRUD for ~/.pflow/mcp-servers.json (standard MCP config format)
├── registrar.py       # Bridge: discovered tools → virtual pflow registry entries
└── pool.py            # Connection pool: keeps server sessions alive across workflow steps
```

## Lifecycle (4-step pipeline)

```
1. Configure    →  2. Discover       →  3. Register         →  4. Execute
manager.py         discovery.py          registrar.py            pool.py + MCPNode
pflow mcp add      pflow mcp sync        (called by sync)        pflow run workflow
~/.pflow/          connects to server,   creates virtual          MCPNode uses pool
mcp-servers.json   lists tools+schemas   registry entries         for stateful sessions
```

**Auto-sync at startup**: `pflow run` auto-discovers MCP tools before execution (`cli/main.py:_auto_discover_mcp_servers`). Uses smart sync — compares config file mtime + SHA256 hash of server names against stored values in Registry metadata. Skips sync when config hasn't changed. Errors are silently swallowed (auto-discovery is optional).

## Integration Points

| Integration | From → To | Mechanism |
|-------------|-----------|-----------|
| Auto-sync at startup | `cli/main.py` → `MCPDiscovery` + `MCPRegistrar` | Smart sync on mtime+hash change; cleans ALL old `mcp-` entries before re-syncing |
| Compiler param injection | `runtime/compilation/compiler.py:inject_special_parameters` → MCPNode params | Parses node type string with greedy longest-match against known servers. Does **NOT** use `mcp_metadata` from registry |
| Pool creation | `execution/runner.py:_initialize_shared_store` → `shared["__mcp_pool__"]` | Created unconditionally for every workflow, but background thread starts lazily on first `call_tool()` |
| Pool consumption | `nodes/mcp/node.py:prep()` → `pool.call_tool()` | Falls back to `asyncio.run()` if no pool (e.g., `pflow registry run`) |
| Pool shutdown | `execution/runner.py:_cleanup()` | Always runs; safe to call multiple times |
| Nested workflows | `__mcp_pool__` propagated from parent | Child workflows reuse parent's pool via `WorkflowExecutor._PROPAGATED_KEYS` (thread-safe, no shutdown risk) |

## Critical Details

### Virtual Registry Entries
All MCP tools create registry entries pointing to the **same** `MCPNode` class (`pflow.nodes.mcp.node`). What differentiates them:
- `file_path`: always `"virtual://mcp"` (not a real file)
- `interface.mcp_metadata`: contains `server`, `tool`, and `original_schema` (stored for reference but NOT used by the compiler at runtime)
- Node name format: `mcp-{server_name}-{tool_name}`

### Node Naming Ambiguity
`mcp-slack-http-remote-SEND_MESSAGE` — where does server end and tool begin? Two parsing paths exist:
1. **`runtime/compilation/mcp_resolution.py:_parse_mcp_node_type`** (authoritative): Greedy longest-match against known servers from `MCPServerManager().list_servers()`
2. **`utils.py:parse_mcp_node_name`**: Progressive matching + heuristic fallback (tool names tend to be `UPPERCASE_WITH_UNDERSCORES`)

**Known inconsistency**: `registrar.py:get_tool_info()` uses a naive `split("-", 2)` that breaks for multi-hyphen server names.

### Connection Pool Threading Model
PocketFlow nodes are **synchronous**. MCP protocol is **async**. The pool bridges this:
- Background daemon thread runs `asyncio.new_event_loop()` + `run_forever()`
- `call_tool()` submits via `run_coroutine_threadsafe()`, blocks on future
- All async state (`_sessions`, `_stacks`) accessed only from the background loop
- `AsyncExitStack` per session manages lifecycle; shutdown closes all stacks (kills server subprocesses)

**Why it exists**: Without pooling, each MCPNode.exec() spawns a new server subprocess. Stateful servers (Playwright, databases) lose ALL state between workflow steps.

### Retry Behavior
- **MCPNode**: `max_retries=1` (= 1 total attempt, 0 retries — PocketFlow's naming is misleading). Each retry spawns a NEW server subprocess, causing resource conflicts.
- **Pool**: One automatic retry on transport errors (`BrokenPipeError`, `ConnectionError`, `OSError`). Evicts dead session, creates fresh one.
- **TimeoutError is NOT a transport error** even on Python 3.11+ (where it's an `OSError` subclass). Timeout = server is alive but slow; retrying would destroy stateful sessions for no benefit.

### Env Var Expansion
`expand_env_vars_nested()` in `auth_utils.py` checks **two sources** in order:
1. `os.environ` (case-sensitive) — wins if present
2. `settings.json` via `SettingsManager` (case-insensitive fallback)

Supports `${VAR}` and `${VAR:-default}` syntax. **Must be called BEFORE `build_auth_headers()`** — the auth function expects already-resolved values.

### Config Format
Storage: `~/.pflow/mcp-servers.json` with `mcpServers` wrapper (standard MCP format, same as Claude Desktop).

**Gotcha**: `types.py` defines `transport` field in its TypedDicts but actual configs and all runtime code use `type`. Absent `type` = stdio (default), `"http"` = HTTP transport.

### Registry Load Correctness
Registrar always calls `registry.load(include_filtered=True)`. If you load with default `include_filtered=False` and save, you **permanently lose** all filtered-out entries. `save()` does a complete replacement of the registry file.

### Result Extraction Priority (in MCPNode)
1. `structuredContent` — typed JSON matching outputSchema (preferred)
2. `isError` flag — tool-level error (distinct from protocol errors)
3. `content` blocks — text, image, resource (legacy/fallback); text blocks are auto-parsed as JSON
