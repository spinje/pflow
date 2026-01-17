# Task 99: Expose pflow Nodes as MCP Tools to Claude Code Node

## Description
Add a `pflow_tools` parameter to the Claude Code node that allows users to expose specific pflow registry nodes as MCP tools within a Claude Code session. This enables Claude Code to call pflow nodes directly (e.g., github-create-pr, http, llm) without pre-wiring them into the workflow, giving the agent dynamic access to pflow's capabilities.

## Status
not started

## Dependencies
- Claude Code node enhancements (completed in this session) - The node now supports `allowed_tools=None` for all tools, `resume` for session continuation, and configurable `timeout`. These provide the foundation for adding MCP server integration.
- Task 72: Implement MCP Server for pflow - The `ExecutionService.run_registry_node()` function exists and can be reused to execute nodes.

## Priority
medium

## Details
When invoking a Claude Code node, users should be able to specify a list of pflow nodes to expose as MCP tools:

```json
{
  "type": "claude-code",
  "params": {
    "prompt": "Review PR and post comments to GitHub",
    "pflow_tools": ["github-add-comment", "http", "llm"],
    "timeout": 600
  }
}
```

### What This Enables

1. **Dynamic Tool Access**: Claude Code can call pflow nodes on-demand without pre-wiring everything in the workflow
2. **Scoped Access**: Only specified nodes are available, maintaining security
3. **Simplified Workflows**: Complex agent behaviors don't require complex workflow DAGs - the agent decides what to call

### Implementation Approach

**Option A (Recommended): Minimal SDK MCP Server**

Create a lightweight in-process MCP server that exposes a single `pflow_run` tool:

```python
def create_pflow_tools_server(allowed_nodes: list[str], registry):
    """Create minimal MCP server with only pflow_run tool."""
    from mcp import FastMCP
    from pflow.mcp_server.services.execution_service import ExecutionService

    server = FastMCP("pflow-tools")

    @server.tool()
    def pflow_run(node_type: str, parameters: dict) -> str:
        """Execute a pflow node from the registry."""
        if node_type not in allowed_nodes:
            return f"Error: {node_type} not in allowed tools: {allowed_nodes}"
        return ExecutionService.run_registry_node(node_type, parameters)

    return server
```

Then pass to Claude Code via `mcp_servers` parameter:

```python
if pflow_tools:
    server = create_pflow_tools_server(pflow_tools, registry)
    options_kwargs["mcp_servers"] = {"pflow": server}
```

### Key Design Decisions

1. **Single MCP Tool**: Expose ONE tool (`pflow_run`) rather than the entire pflow MCP server (11+ tools)
2. **Reuse ExecutionService**: Leverage existing `run_registry_node()` logic rather than duplicating
3. **Allowlist Validation**: Validate `node_type` against provided `pflow_tools` list
4. **System Prompt Injection**: Include node metadata/descriptions in system prompt so Claude knows what's available

### Files to Modify/Create

1. **`src/pflow/nodes/claude/claude_code.py`**:
   - Add `pflow_tools` parameter validation
   - Add to `prep()` return dict
   - Update `_build_claude_options()` to create and pass MCP server

2. **`src/pflow/nodes/claude/pflow_mcp_bridge.py`** (new file):
   - `create_pflow_tools_server()` function
   - Helper to build system prompt additions with node metadata

3. **Tests**: `tests/test_nodes/test_claude/test_pflow_tools.py`

### Integration Points

- **Claude Agent SDK**: Uses `mcp_servers` parameter in `ClaudeAgentOptions`
- **ExecutionService**: Reuses `run_registry_node()` for actual execution
- **Registry**: Loads node metadata for system prompt injection
- **Context Builder**: May reuse `build_planning_context()` for node descriptions

### Example Usage

```json
{
  "id": "smart_agent",
  "type": "claude-code",
  "params": {
    "prompt": "Analyze the PR, identify issues, then use github-add-comment to post your findings",
    "pflow_tools": ["github-add-comment", "github-list-prs"],
    "timeout": 600
  }
}
```

Claude Code would then have access to:
- Built-in tools: Read, Write, Edit, Bash, Task, Glob, Grep, etc.
- MCP tool: `pflow_run(node_type="github-add-comment", parameters={...})`

## Test Strategy

### Unit Tests
1. **Parameter Validation**:
   - `pflow_tools=None` → no MCP server created
   - `pflow_tools=[]` → no MCP server created
   - `pflow_tools=["node1", "node2"]` → MCP server created with allowlist

2. **MCP Server Creation**:
   - Server has exactly one tool: `pflow_run`
   - Tool validates node_type against allowlist
   - Tool rejects nodes not in allowlist

3. **System Prompt Injection**:
   - Node metadata included when `pflow_tools` provided
   - Describes available nodes and their parameters

### Integration Tests
1. **End-to-end**: Claude Code can call `pflow_run` MCP tool (mocked SDK)
2. **Node execution**: `pflow_run` correctly delegates to `ExecutionService.run_registry_node()`

### Security Tests
1. Verify nodes not in allowlist are rejected
2. Verify invalid node types return appropriate errors
