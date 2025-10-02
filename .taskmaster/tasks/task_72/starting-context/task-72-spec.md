# Feature: mcp_server_infrastructure

## Objective

Expose pflow capabilities as MCP tools for AI agent orchestration.

## Requirements

- Task 68 execution service APIs must be complete
- Task 43 MCP client implementation patterns must exist
- Task 21 workflow input/output declarations must be implemented
- WorkflowManager must support workflow lifecycle operations
- Registry must provide node metadata extraction
- FastMCP SDK must be available (mcp[cli]>=1.13.1)

## Scope

- Does not implement natural language planner as MCP tool
- Does not implement internal repair loop
- Does not support HTTP transport
- Does not implement authentication
- Does not support concurrent MCP sessions
- Does not expose all pflow CLI commands
- Does not modify existing core libraries

## Inputs

- `tool_name`: str - Name of MCP tool being invoked
- `tool_arguments`: dict - Tool-specific parameters
  - For `browse_components`: `query: str, include_workflows: bool`
  - For `list_library`: `pattern: str | None`
  - For `describe_workflow`: `name: str`
  - For `execute`: `name: str, inputs: dict | None`
  - For `save_to_library`: `draft_name: str, final_name: str, description: str`

## Outputs

Returns: MCP CallToolResult with structured response
- For `browse_components`: `{"nodes": [...], "workflows": [...]}`
- For `list_library`: `[{"name": str, "description": str, ...}]`
- For `describe_workflow`: `{"inputs": dict, "outputs": dict, ...}`
- For `execute`: `{"success": bool, "outputs": dict, "checkpoint": dict | None}`
- For `save_to_library`: `{"success": bool, "path": str}`

Side effects:
- `execute` may create/modify files via workflow execution
- `save_to_library` moves draft file to library directory

## Structured Formats

```json
{
  "mcp_tools": {
    "browse_components": {
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"},
          "include_workflows": {"type": "boolean", "default": true}
        }
      }
    },
    "execute": {
      "inputSchema": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "inputs": {"type": "object"}
        },
        "required": ["name"]
      }
    }
  },
  "response_format": {
    "success": "boolean",
    "data": "object | array",
    "error": "object | null"
  }
}
```

## State/Flow Changes

- `draft_workflow` → `executed_workflow` when execute succeeds
- `executed_workflow` → `library_workflow` when save_to_library called
- `failed_workflow` → `checkpoint_state` when execution fails with errors
- `checkpoint_state` → `resumed_workflow` when re-executed with fixes

## Constraints

- Workflow names must not contain path separators
- Draft workflows must be in ~/.pflow/workflows/
- MCP server must use stdio transport only
- Each request creates fresh Registry/WorkflowManager instances
- asyncio.to_thread must bridge async MCP to sync pflow
- Sensitive parameters must be redacted in logs

## Rules

1. MCP server must expose exactly 5 tools
2. browse_components must return nodes with interface metadata
3. browse_components must return workflows if include_workflows is true
4. list_library must return all saved workflows when pattern is null
5. list_library must filter by pattern when provided
6. describe_workflow must return declared inputs from IR
7. describe_workflow must return discovered template variables
8. execute must try library workflows first
9. execute must try draft workflows if library not found
10. execute must return checkpoint on failure
11. execute must use NullOutput for silent execution
12. execute must use enable_repair=False for deterministic behavior
13. save_to_library must validate workflow exists as draft
14. save_to_library must use atomic file operations
15. save_to_library must remove draft file after successful save
16. All tools must validate workflow names for path traversal
17. All tools must use fresh instances per request
18. All tools must run sync code via asyncio.to_thread
19. Server must use FastMCP for tool registration
20. Server must handle SIGINT for graceful shutdown

## Edge Cases

- Workflow name contains "../" → reject with SecurityError
- Workflow name contains absolute path → reject with SecurityError
- Draft workflow not found → return FileNotFoundError
- Library workflow not found during execute → try draft directory
- Execute with no inputs when workflow needs them → return template errors
- Save_to_library with existing final_name → reject with error (no overwrite in MVP)
- Concurrent executions of same workflow → each gets fresh instances
- MCP client disconnects mid-execution → workflow continues to checkpoint
- Invalid JSON in workflow file → return validation error
- Registry returns no nodes → return empty list not error

## Error Handling

- Path traversal attempt → raise SecurityError with sanitized message
- Missing workflow → return structured error with available workflows
- Template resolution failure → return error with missing variables listed
- Execution failure → return error with checkpoint and failed node
- Invalid parameters → return MCP validation error
- Duplicate library name → return error indicating name exists

## Non-Functional Criteria

- browse_components must complete in < 1 second
- Registry loading must complete within 50ms
- Checkpoint data must be JSON-serializable
- Logs must not contain sensitive parameter values
- Server must use ThreadPoolExecutor default sizing
- Fresh instances must be created per request

## Examples

### Example 1: Browse components for GitHub workflow
Request:
```json
{
  "tool": "browse_components",
  "arguments": {"query": "github", "include_workflows": true}
}
```
Response:
```json
{
  "nodes": [
    {
      "type": "github",
      "description": "GitHub operations",
      "inputs": [{"key": "repo", "type": "str"}]
    }
  ],
  "workflows": [
    {"name": "pr-analyzer", "description": "Analyzes PRs"}
  ]
}
```

### Example 2: Execute with checkpoint on failure
Request:
```json
{
  "tool": "execute",
  "arguments": {"name": "test-workflow", "inputs": {}}
}
```
Response on error:
```json
{
  "success": false,
  "error": {
    "type": "template_error",
    "message": "Template ${api_key} not resolved",
    "node": "fetch"
  },
  "checkpoint": {
    "completed_nodes": ["init"],
    "failed_node": "fetch"
  }
}
```

## Test Criteria

1. Server exposes exactly 5 MCP tools via list_tools
2. browse_components with "github" returns github node
3. browse_components with include_workflows=false omits workflows
4. list_library with no pattern returns all workflows
5. list_library with pattern "test" filters correctly
6. describe_workflow returns both declared and template inputs
7. describe_workflow includes execution statistics
8. execute finds library workflow when exists
9. execute falls back to draft when library missing
10. execute returns checkpoint data on failure
11. execute uses NullOutput verified by no console output
12. execute with enable_repair=False verified by no repair attempts
13. save_to_library moves file from draft to library atomically
14. save_to_library validates draft exists before moving
15. save_to_library deletes draft after successful save
16. Path traversal "../etc" rejected with SecurityError
17. Absolute path "/etc/passwd" rejected with SecurityError
18. Fresh Registry instance per request verified by state isolation
19. asyncio.to_thread used verified by thread pool metrics
20. FastMCP tool registration verified by MCP protocol compliance
21. SIGINT handler exits with code 130
22. Concurrent executions maintain isolation
23. Template error includes missing variable names
24. Checkpoint contains completed_nodes list
25. Sensitive params redacted in logs

## Notes (Why)

- 5 tools chosen over 14 to reduce cognitive load on agents
- Agent orchestrates repair to leverage conversation context
- Stateless design ensures correctness over performance
- NullOutput prevents CLI display mixing with MCP responses
- asyncio.to_thread avoids rewriting sync pflow code
- Fresh instances prevent state pollution between requests
- Path validation critical for security in multi-user future

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 2                          |
| 3      | 3                          |
| 4      | 4                          |
| 5      | 5                          |
| 6      | 6                          |
| 7      | 6                          |
| 8      | 8                          |
| 9      | 9                          |
| 10     | 10, 24                     |
| 11     | 11                         |
| 12     | 12                         |
| 13     | 14                         |
| 14     | 13                         |
| 15     | 15                         |
| 16     | 16, 17                     |
| 17     | 18                         |
| 18     | 19                         |
| 19     | 20                         |
| 20     | 21                         |

## Versioning & Evolution

- v1.0.0 - Initial MCP server with 5 core tools
- v1.1.0 - (Future) Add workflow template generation tool
- v2.0.0 - (Future) Add HTTP transport support
- v3.0.0 - (Future) Add authentication and multi-tenant support

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes Claude Code MCP client follows standard protocol
- Assumes FastMCP stdio transport is stable
- Unknown whether agents need progress updates during execution
- Unknown optimal timeout for long-running workflows
- Assumes ~/.pflow/workflows/ is writable and persistent
- Unknown whether to keep or delete draft files after save_to_library
- Unknown specific concurrent request handling requirements
- Unknown specific memory usage limits for server

### Conflicts & Resolutions

- CLI uses enable_repair=True by default vs MCP needs deterministic behavior - Resolution: MCP always uses enable_repair=False
- ComponentBrowsingNode returns IDs vs MCP needs metadata - Resolution: Create new formatting layer instead of reusing
- Planner creates workflows vs agent creates workflows - Resolution: Agent uses file operations, no planner exposure

### Decision Log / Tradeoffs

- Chose 5 specific tools (browse_components, list_library, describe_workflow, execute, save_to_library): Based on agent workflow building needs
- Chose 5 tools over 14: Simplicity over completeness for MVP
- Chose stateless over cached: Correctness over 50ms latency
- Chose NullOutput over MCPOutput: Simplicity over structured progress
- Chose stdio over HTTP: Faster integration over scalability
- Chose asyncio.to_thread over rewrite: Time to market over elegance
- Chose agent file editing over workflow generation tool: Leverages agent's existing capabilities

### Ripple Effects / Impact Map

- WorkflowManager needs search() method addition
- WorkflowManager needs for_drafts() classmethod
- Execution needs duration tracking in metadata
- CLI needs new serve subcommand in main_wrapper.py
- Testing needs new test_mcp_server directory
- Documentation needs MCP setup instructions

### Residual Risks & Confidence

- Risk: Thread pool exhaustion under high load - Mitigation: Set max workers
- Risk: Large workflows exceed MCP message size - Mitigation: Pagination in v2
- Risk: Agent confusion with 5 tools - Mitigation: Clear descriptions
- Risk: Security vulnerabilities in path handling - Mitigation: Multiple validation layers
- Confidence: High for core functionality, Medium for agent natural discovery

### Epistemic Audit (Checklist Answers)

1. Assumed stable MCP protocol and single-session stdio model
2. Protocol changes would require transport abstraction layer
3. Chose robustness (stateless) over elegance (cached)
4. All rules have test coverage in matrix
5. Touches WorkflowManager, CLI routing, adds new module
6. Uncertainty on agent behavior patterns; Confidence: High on technical implementation