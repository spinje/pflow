# Task 99: Expose pflow Tools to Claude Code Node

## Description
Add a `pflow_tools` parameter to the Claude Code node that allows users to expose pflow capabilities as MCP tools within a Claude Code session. This covers three tool sources:

1. **Registry nodes** (including synced MCP tools): e.g., `github-add-comment`, `http`, `slack-mcp/post-message`
2. **Saved workflows**: e.g., `my-review-pipeline`, enabling Claude Code to invoke entire workflows as single tool calls

This enables Claude Code to call pflow nodes and workflows on-demand without pre-wiring them into the workflow DAG, giving the agent dynamic access to pflow's full capabilities.

## Status
not started

## Dependencies
- Claude Code node enhancements (completed in this session) - The node now supports `allowed_tools=None` for all tools, `resume` for session continuation, and configurable `timeout`. These provide the foundation for adding MCP server integration.
- Task 72: Implement MCP Server for pflow - The `ExecutionService.run_registry_node()` function exists and can be reused to execute nodes.

## Priority
medium

## Details
When invoking a Claude Code node, users should be able to specify a list of pflow nodes and/or saved workflows to expose as MCP tools:

```json
{
  "type": "claude-code",
  "params": {
    "prompt": "Review PR and post comments to GitHub",
    "pflow_tools": ["github-add-comment", "http", "llm", "workflow:my-review-pipeline"],
    "timeout": 600
  }
}
```

The `pflow_tools` list accepts:
- **Registry node names**: `"github-add-comment"`, `"http"`, `"slack-mcp/post-message"` — resolves to individual nodes (including MCP tools synced to the registry)
- **Saved workflow references**: `"workflow:my-review-pipeline"` — resolves to a saved workflow, exposed as a single callable tool with the workflow's declared inputs as parameters

### What This Enables

1. **Dynamic Tool Access**: Claude Code can call pflow nodes and workflows on-demand without pre-wiring everything in the workflow
2. **Scoped Access**: Only specified nodes/workflows are available, maintaining security
3. **Simplified Workflows**: Complex agent behaviors don't require complex workflow DAGs - the agent decides what to call
4. **Workflow Composition**: Saved workflows become reusable tools that Claude Code can invoke, enabling layered agentic behavior

### Implementation Approach

**Option A (Recommended): Minimal SDK MCP Server**

Create a lightweight in-process MCP server that exposes pflow capabilities as tools:

```python
def create_pflow_tools_server(allowed_tools: list[str], registry, workflow_manager):
    """Create MCP server exposing pflow nodes and workflows as tools."""
    from mcp import FastMCP
    from pflow.mcp_server.services.execution_service import ExecutionService

    server = FastMCP("pflow-tools")

    # Separate node refs from workflow refs
    node_refs = [t for t in allowed_tools if not t.startswith("workflow:")]
    workflow_refs = [t.removeprefix("workflow:") for t in allowed_tools if t.startswith("workflow:")]

    @server.tool()
    def pflow_run_node(node_type: str, parameters: dict) -> str:
        """Execute a pflow registry node."""
        if node_type not in node_refs:
            return f"Error: {node_type} not in allowed tools: {node_refs}"
        return ExecutionService.run_registry_node(node_type, parameters)

    @server.tool()
    def pflow_run_workflow(workflow_name: str, inputs: dict) -> str:
        """Execute a saved pflow workflow."""
        if workflow_name not in workflow_refs:
            return f"Error: {workflow_name} not in allowed workflows: {workflow_refs}"
        return ExecutionService.run_workflow(workflow_name, inputs)

    return server
```

Then pass to Claude Code via `mcp_servers` parameter:

```python
if pflow_tools:
    server = create_pflow_tools_server(pflow_tools, registry, workflow_manager)
    options_kwargs["mcp_servers"] = {"pflow": server}
```

### Key Design Decisions

1. **Two MCP Tools**: Expose `pflow_run_node` and `pflow_run_workflow` — separate tools for clarity, since they have different parameter shapes (node_type+parameters vs workflow_name+inputs)
2. **Reuse ExecutionService**: Leverage existing `run_registry_node()` and `run_workflow()` logic
3. **Allowlist Validation**: Validate against the provided `pflow_tools` list
4. **System Prompt Injection**: Include node/workflow metadata/descriptions in system prompt so Claude knows what's available
5. **Prefixed Syntax**: `workflow:name` prefix distinguishes workflow refs from node refs in a flat list

### Files to Modify/Create

1. **`src/pflow/nodes/claude/claude_code.py`**:
   - Add `pflow_tools` parameter validation
   - Add to `prep()` return dict
   - Update `_build_claude_options()` to create and pass MCP server

2. **`src/pflow/nodes/claude/pflow_mcp_bridge.py`** (new file):
   - `create_pflow_tools_server()` function
   - Resolve `workflow:` prefixed refs via WorkflowManager
   - Helper to build system prompt additions with node/workflow metadata

3. **Tests**: `tests/test_nodes/test_claude/test_pflow_tools.py`

### Integration Points

- **Claude Agent SDK**: Uses `mcp_servers` parameter in `ClaudeAgentOptions`
- **ExecutionService**: Reuses `run_registry_node()` and `run_workflow()` for actual execution
- **Registry**: Loads node metadata for system prompt injection
- **WorkflowManager**: Loads saved workflow metadata (inputs, description) for workflow tools
- **Context Builder**: May reuse `build_planning_context()` for node/workflow descriptions

### Example Usage

**Registry nodes (including synced MCP tools):**
```json
{
  "id": "smart_agent",
  "type": "claude-code",
  "params": {
    "prompt": "Analyze the PR, identify issues, then use github-add-comment to post your findings",
    "pflow_tools": ["github-add-comment", "github-list-prs", "slack-mcp/post-message"],
    "timeout": 600
  }
}
```

**Saved workflows as tools:**
```json
{
  "id": "orchestrator",
  "type": "claude-code",
  "params": {
    "prompt": "For each open PR, run the review pipeline and post a summary",
    "pflow_tools": ["github-list-prs", "workflow:pr-review-pipeline", "workflow:summarize-findings"],
    "timeout": 900
  }
}
```

Claude Code would then have access to:
- Built-in tools: Read, Write, Edit, Bash, Task, Glob, Grep, etc.
- MCP tool: `pflow_run_node(node_type="github-add-comment", parameters={...})`
- MCP tool: `pflow_run_workflow(workflow_name="pr-review-pipeline", inputs={...})`

## Test Strategy

### Unit Tests
1. **Parameter Validation**:
   - `pflow_tools=None` → no MCP server created
   - `pflow_tools=[]` → no MCP server created
   - `pflow_tools=["node1", "node2"]` → MCP server created with allowlist
   - `pflow_tools=["workflow:my-wf"]` → workflow ref parsed correctly

2. **MCP Server Creation**:
   - Server has two tools: `pflow_run_node` and `pflow_run_workflow`
   - Node tool validates node_type against node allowlist
   - Workflow tool validates workflow_name against workflow allowlist
   - Rejects items not in their respective allowlists

3. **Tool Reference Parsing**:
   - Plain names resolve to registry nodes
   - `workflow:` prefixed names resolve to saved workflows
   - Mixed lists are split correctly

4. **System Prompt Injection**:
   - Node metadata included when registry nodes specified
   - Workflow metadata (description, declared inputs) included when workflows specified

### Integration Tests
1. **End-to-end**: Claude Code can call both MCP tools (mocked SDK)
2. **Node execution**: `pflow_run_node` correctly delegates to `ExecutionService.run_registry_node()`
3. **Workflow execution**: `pflow_run_workflow` correctly delegates to workflow execution

### Security Tests
1. Verify nodes not in allowlist are rejected
2. Verify workflows not in allowlist are rejected
3. Verify invalid node types and workflow names return appropriate errors
