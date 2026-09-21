# MCP Client Integration

Connects workflow nodes to external MCP servers. `mcp_server/` is the opposite
surface: it exposes pflow itself as an MCP server.

## Navigation

| Concern | Owner |
|---|---|
| Persisted server configuration | `manager.py:MCPServerManager` (`~/.pflow/mcp-servers.json`) |
| Environment expansion and HTTP auth | `auth_utils.py:expand_env_vars_nested`, `build_auth_headers` |
| Tool discovery/schema conversion | `discovery.py:MCPDiscovery` |
| Registry reconciliation | `registrar.py:MCPRegistrar.sync_servers`; fingerprints in `sync_state.py` |
| Stateful sessions and transport recovery | `pool.py:MCPConnectionPool` |
| SDK exception/Diagnostic translation | `errors.py` |
| Workflow tool execution/results | `nodes/mcp/node.py:MCPNode`, `_extract_result` |
| Execution-start auto-sync | `cli/mcp_sync.py:_auto_discover_mcp_servers` |

## Registration and naming

Virtual tool entries all reference the same `MCPNode` class and use
`virtual://mcp` as their file path. Compiler parameter injection distinguishes the
server/tool through `runtime/compilation/mcp_resolution.py:_parse_mcp_node_type`,
which matches configured server names longest-first. Do not use
`utils.py:parse_mcp_node_name`; it is not the live parser.

Registry mutation must **not** split `mcp-{server}-{tool}` names: server names can
contain hyphens. Replacement/removal/listing use exact
`interface.mcp_metadata.server` ownership. `registrar.py:get_tool_info` still has a
naive split; its display limitation is separate from mutation and compiler parsing.

Auto-sync fingerprints raw persisted configurations per server. Successful servers
advance independently; failures retain prior tools/fingerprints for retry. Missing
configuration is a no-op; an explicit empty configuration can reconcile MCP state
to empty. `sync_servers` discovers first, rechecks configuration, then late-loads
unfiltered registry state and publishes tools plus fingerprints together.

Use `registry.load(include_filtered=True)` before replacement writes: saving a
filtered view deletes hidden entries. Atomic publication prevents partial snapshots,
not cross-process read-modify-write races; see `registry/CLAUDE.md`.

## Pool lifecycle and retry

Runner creates `shared["__mcp_pool__"]`; its background event-loop thread starts
lazily. Synchronous `call_tool` submits work to that loop, which owns mutable async
session state. Keeping sessions alive preserves state between workflow steps.
`runtime/workflow_executor.py:_PROPAGATED_KEYS` passes the same pool to nested
workflows; Runner owns shutdown. Do not shut it down from a child workflow.

`MCPNode` uses one total attempt (`max_retries=1`). Without a pool it opens an
ephemeral connection. The pool separately retries transport failures by evicting
the session and reconnecting; the new session does not preserve server state.
`pool.py:_is_transport_error` explicitly excludes TimeoutError even where it is an
OSError subclass: slow responses must not trigger destructive reconnects.

## Configuration/auth traps

- Runtime transport selection reads `type` (absent means stdio); the TypedDicts in
  `types.py` still name this field `transport`. Follow runtime/config behavior.
- `expand_env_vars_nested` always checks process environment first. Settings lookup
  is opt-in via `include_settings=True` and case-insensitive; discovery and MCPNode
  enable it, together with `raise_on_missing=True`. Other callers may choose differently.
- Expand configuration before `build_auth_headers`, which expects resolved values.
  Fingerprints must still use the raw persisted configuration, not expanded secrets.
