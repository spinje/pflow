# Feature: mcp_server_support

## Objective

Enable pflow to execute MCP server tools as workflow nodes.

## Requirements

* Must have Registry class that supports manual save()
* Must have compiler that can inject special parameters
* Must have JSON-RPC 2.0 client implementation
* Must have subprocess management for stdio transport
* Must implement environment variable expansion for ${VAR} syntax

## Scope

* Does not support HTTP transport
* Does not support SSE transport
* Does not support OAuth authentication
* Does not support connection pooling
* Does not support auto-discovery on startup
* Does not support project or local scopes
* Does not support binary content types

## Inputs

* `server_config`: dict - MCP server configuration
  * `name`: str - Server identifier (e.g., "github")
  * `transport`: str - Transport type (only "stdio" supported)
  * `command`: str - Command to execute
  * `args`: list[str] - Command arguments
  * `env`: dict[str, str] - Environment variables with ${VAR} expansion
* `sync_server`: str - Server name to sync tools from
* `node_type`: str - Registry node type (e.g., "mcp-github-create-issue")

## Outputs

Returns: dict - Operation results
* For sync: {"tools_discovered": int, "tools_registered": int}
* For execution: {"result": Any, "error": Optional[str]}

Side effects:
* Updates ~/.pflow/registry.json with virtual node entries
* Creates ~/.pflow/mcp-servers.json configuration file
* Starts/stops MCP server subprocesses

## Structured Formats

```json
{
  "mcp_server_config": {
    "servers": {
      "<server_name>": {
        "transport": "stdio",
        "command": "string",
        "args": ["string"],
        "env": {"KEY": "${VALUE}"}
      }
    }
  },
  "registry_entry": {
    "<node_name>": {
      "class_name": "MCPNode",
      "module": "pflow.nodes.mcp.node",
      "file_path": "virtual://mcp",
      "interface": {
        "description": "string",
        "params": [],
        "outputs": [],
        "actions": ["default", "error"]
      }
    }
  }
}
```

## State/Flow Changes

* `unconfigured` → `configured` when server added via CLI
* `configured` → `discovered` when tools enumerated via sync
* `discovered` → `registered` when tools added to registry
* `registered` → `executing` when node instantiated
* `executing` → `completed` when tool execution finishes

## Constraints

* Server names must match [a-z0-9-]+ pattern
* Node names must follow mcp-{server}-{tool} pattern
* Maximum subprocess timeout: 30 seconds
* JSON-RPC messages must be newline-delimited
* Environment variables must use ${VAR} syntax

## Rules

1. If server transport is not "stdio" then reject configuration
2. If server command does not exist then fail with clear error
3. If MCP handshake fails then report protocol error
4. If tools/list returns empty then register zero nodes
5. If tool name contains invalid characters then sanitize to [a-z0-9-]
6. If registry entry already exists then overwrite with warning
7. If node_type starts with "mcp-" then inject __mcp_server__ parameter
8. If node_type starts with "mcp-" then inject __mcp_tool__ parameter
9. If subprocess exceeds timeout then terminate with SIGTERM
10. If JSON-RPC response has error then translate to user message
11. If environment variable ${VAR} is undefined then pass VAR="" to subprocess
12. Store discovered tools in registry with virtual file_path
13. Use single MCPNode class for all MCP tool executions
14. Parse server and tool from node_type in MCPNode.prep()

## Edge Cases

* Server command not found → Return error "Command not found: {command}"
* Malformed JSON-RPC response → Return error "Invalid JSON response from server"
* Tool no longer exists after discovery → Return error "Tool {tool} not found on server {server}"
* Environment variable undefined → Pass empty string as VAR="" to subprocess
* Subprocess hangs → Kill after 30 seconds
* Duplicate tool names from different servers → Namespace with server prefix
* Registry corruption → Backup before modification
* Node_type missing "mcp-" prefix → Skip metadata injection

## Error Handling

* Missing server configuration → Return error "Server {name} not configured"
* Protocol version mismatch → Return error "MCP protocol version not supported"
* JSON-RPC error codes → Map to readable messages (-32601: "Method not found", -32602: "Invalid params")
* Subprocess crash → Return error "MCP server process terminated unexpectedly"

## Non-Functional Criteria

* Tool discovery completes within 5 seconds per server
* Registry updates are atomic (all or nothing)
* Subprocess cleanup on workflow completion
* Maximum 100MB memory per MCP server process

## Examples

Valid configuration:
```json
{
  "servers": {
    "github": {
      "transport": "stdio",
      "command": "npx",
      "args": ["@modelcontextprotocol/github"],
      "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    }
  }
}
```

Registry entry created:
```json
{
  "mcp-github-create-issue": {
    "class_name": "MCPNode",
    "module": "pflow.nodes.mcp.node",
    "file_path": "virtual://mcp",
    "interface": {
      "description": "Create a GitHub issue",
      "params": [
        {"name": "title", "type": "str"},
        {"name": "body", "type": "str"}
      ],
      "outputs": [
        {"name": "issue_url", "type": "str"}
      ],
      "actions": ["default", "error"]
    }
  }
}
```

## Test Criteria

1. Configure stdio server with valid command → Server saved to config
2. Configure server with HTTP transport → Configuration rejected
3. Sync server with 3 tools → 3 registry entries created
4. Sync server with empty tools/list → 0 registry entries created
5. Execute MCP node → __mcp_server__ parameter injected
6. Execute MCP node → __mcp_tool__ parameter injected
7. Invalid server command → Clear error message returned
8. Subprocess timeout at 31 seconds → Process killed with SIGTERM
9. Malformed JSON from server → Error "Invalid JSON response"
10. Tool with spaces in name → Sanitized to valid characters
11. Duplicate registry entry → Previous entry overwritten
12. Undefined ${TOKEN} → TOKEN="" in subprocess env
13. Node without "mcp-" prefix → No metadata injection
14. JSON-RPC error -32601 → Error "Method not found"
15. Parse "mcp-github-create-issue" → server="github", tool="create-issue"

## Notes (Why)

* Virtual nodes avoid Python file generation complexity
* Single MCPNode class simplifies maintenance
* Compiler metadata injection follows existing __registry__ pattern
* stdio-only MVP reduces implementation scope
* Namespacing prevents tool name collisions

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 2                          |
| 2      | 7                          |
| 3      | 9                          |
| 4      | 4                          |
| 5      | 10                         |
| 6      | 11                         |
| 7      | 5                          |
| 8      | 6                          |
| 9      | 8                          |
| 10     | 14                         |
| 11     | 12                         |
| 12     | 3                          |
| 13     | 5, 6                       |
| 14     | 15                         |

## Versioning & Evolution

* **Version:** 1.0.0
* **Changelog:**
  * **1.0.0** — Initial MCP support with stdio transport only

## Epistemic Appendix

### Assumptions & Unknowns

* Assumes MCP servers follow JSON-RPC 2.0 specification exactly
* Assumes stdio servers output only valid JSON-RPC messages
* Assumes environment variable expansion will follow shell-like behavior
* Unknown: Actual memory usage of MCP server processes
* Unknown: How MCP servers handle concurrent requests

### Conflicts & Resolutions

* Registry design expects one class per entry vs multiple entries per class — **Resolution:** Registry supports multiple entries pointing to same class (verified in codebase)
* Compiler expects node classes with parameterless constructors — **Resolution:** Use set_params() for metadata injection
* Template resolver uses ${var} but only for context variables not environment — **Resolution:** Implement separate environment variable expansion for MCP config

### Decision Log / Tradeoffs

* Direct registry manipulation vs code generation — Chose direct manipulation for simplicity
* Generic metadata injection vs MCP-specific — Chose MCP-specific following __registry__ pattern
* Connection pooling vs subprocess per execution — Chose subprocess per execution for MVP simplicity

### Ripple Effects / Impact Map

* Compiler modification affects all future node types
* Registry becomes hybrid (scanned Python files + virtual MCP entries)
* CLI gains new "mcp" subcommand group

### Residual Risks & Confidence

* Risk: MCP protocol changes break compatibility; Mitigation: Version checking
* Risk: Subprocess resource leaks; Mitigation: Timeout and cleanup
* Confidence: High for stdio; Low for future HTTP/SSE support

### Epistemic Audit (Checklist Answers)

1. Assumed MCP servers are well-behaved with JSON output and need environment variable expansion
2. Wrong assumption causes parsing failures and poor error messages
3. Chose robustness (subprocess isolation) over performance (pooling)
4. All rules have corresponding tests
5. Touches compiler, registry, CLI, and requires new env var expansion
6. Uncertainty around MCP server resource usage; High confidence in architecture