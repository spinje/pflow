# Task 72: Implement MCP Server for pflow

## Description
Build an MCP (Model Context Protocol) server that exposes pflow's core workflow building and execution capabilities as programmatically accessible tools for AI agents. This enables agents to use pflow without shell access, with structured responses and better performance than CLI spawning.

## Status
done

## Completed
2025-10-12

## Dependencies
- Task 71: CLI extensions for agents (COMPLETED - provides the patterns we're exposing)
- Task 68: Service layer separation (COMPLETED - provides clean APIs to wrap)
- Task 43: MCP client support (COMPLETED - shows MCP patterns in pflow)
- MCP SDK updated to 1.17.0 (from 1.13.1) for latest features and stability

## Priority
high

## Details

### Context and Rationale

Task 71 successfully implemented CLI discovery commands that agents use to build workflows. However, some environments require programmatic access without shell execution:

1. **Performance**: CLI spawning adds overhead for multiple commands
2. **Structure**: MCP provides JSON responses without text parsing
3. **Integration**: Some AI systems (Cursor, Continue) prefer MCP over shell
4. **Session Management**: MCP can maintain context across calls
5. **Error Handling**: MCP has structured error protocols

This task creates an MCP server that mirrors the CLI capabilities agents already use, but with programmatic access.

### What We're Building

An MCP server exposing **13 tools** organized in three priority tiers:

#### Priority 1: Core Workflow Loop (6 tools)
These are MANDATORY for agents to build workflows:

1. **`workflow_discover`** - Find existing workflows matching a request
   - Uses LLM for intelligent matching
   - Returns confidence scores and reasoning
   - Enforces discovery-first pattern

2. **`registry_discover`** - Find nodes for building workflows
   - Uses LLM for intelligent selection
   - Returns complete interface specifications
   - Provides everything needed to build

3. **`registry_run`** - Test node execution
   - Critical for MCP nodes with nested outputs
   - Returns complete structure, not just values
   - Reveals actual output paths for templates

4. **`workflow_execute`** - Execute workflows
   - Built-in: JSON output, no auto-repair, trace enabled
   - Returns structured results with errors
   - Includes checkpoint for failed executions

5. **`workflow_validate`** - Validate without execution
   - Catches template and structural errors
   - Returns detailed errors with suggestions
   - No side effects

6. **`workflow_save`** - Save to global library
   - Makes workflows reusable
   - Validates name format
   - Auto-normalizes workflow structure

#### Priority 2: Supporting Functions (5 tools)
Enhanced functionality for complete workflows:

7. **`registry_describe`** - Get detailed node specs
8. **`registry_search`** - Find nodes by pattern
9. **`workflow_list`** - List saved workflows
10. **`settings_set`** - Configure API keys
11. **`settings_get`** - Retrieve settings

#### Priority 3: Advanced (2 tools)
Nice to have for power users:

12. **`registry_list`** - Browse all nodes (verbose)
13. **`trace_read`** - Parse execution traces

### Key Design Decisions

1. **Direct Service Integration**: Use WorkflowManager, Registry, execute_workflow directly (not CLI wrapping)
2. **Clean Interface**: No unnecessary parameters, sensible defaults
3. **Agent-Optimized Defaults**:
   - Always return JSON structures
   - Never auto-repair (explicit errors)
   - Always save execution traces
   - Auto-normalize workflow structures
4. **Stateless Operation**: Fresh instances per request (matches pflow patterns)
5. **Discovery-First**: Enforce checking for existing workflows before building

### Implementation Architecture

```
src/pflow/mcp_server/
├── __init__.py
├── server.py          # FastMCP server setup
├── tools/
│   ├── discovery.py   # workflow_discover, registry_discover
│   ├── execution.py   # workflow_execute, workflow_validate
│   ├── registry.py    # registry_run, describe, search, list
│   ├── workflow.py    # workflow_save, workflow_list
│   ├── settings.py    # settings_set, settings_get
│   └── trace.py      # trace_read
└── utils/
    ├── resolver.py    # Workflow resolution logic
    └── security.py    # Path validation
```

### Technical Approach

Using FastMCP pattern with asyncio.to_thread bridge:

```python
from mcp.server.fastmcp import FastMCP
import asyncio

mcp = FastMCP("pflow", version="0.1.0")

@mcp.tool()
async def workflow_execute(workflow: str | dict, parameters: dict = None) -> dict:
    """Execute workflow with agent-optimized defaults."""
    # Direct service integration
    from pflow.execution.workflow_execution import execute_workflow
    from pflow.execution.null_output import NullOutput

    result = await asyncio.to_thread(
        execute_workflow,
        workflow_ir=workflow,
        execution_params=parameters or {},
        output=NullOutput(),     # Silent execution
        enable_repair=False      # No auto-repair
    )

    # Return structured response
    return format_result(result)
```

### CLI Integration

Add `pflow serve mcp` command:

```python
# src/pflow/cli/commands/serve.py
@serve.command()
def mcp():
    """Run as MCP server (stdio transport)."""
    from pflow.mcp_server import run_server
    asyncio.run(run_server())
```

### Critical Implementation Notes

1. **Discovery Tools Use LLM**: Unlike simple keyword search, use ComponentBrowsingNode and WorkflowDiscoveryNode directly
2. **Agent Mode Built-in**: No flags for JSON output or disabling repair - these are defaults
3. **MCP Node Testing Essential**: registry_run must reveal nested structures (documentation shows "Any" but reality is deeply nested)
4. **Stateless by Design**: Create fresh Registry/WorkflowManager instances per request
5. **Security**: Validate all paths, sanitize sensitive parameters in responses

## Implementation Plan

### Phase 1: Core Tools (2 days)
- Set up FastMCP server structure
- Implement 6 Priority 1 tools
- Test discovery → execute loop

### Phase 2: Supporting Tools (1 day)
- Implement 5 Priority 2 tools
- Add settings management
- Test complete workflows

### Phase 3: Testing & Validation (1 day)
- Test with AGENT_INSTRUCTIONS workflows
- Validate Claude Code discovery
- Performance testing

### Phase 4: Advanced Tools (0.5 day)
- Implement Priority 3 tools if time permits
- Documentation and examples

## Success Criteria

✅ MCP server exposes 13 tools via stdio transport
✅ Discovery tools use LLM for intelligent selection
✅ Execution returns structured JSON with errors and traces
✅ All tools use agent-optimized defaults (no flags needed)
✅ Agents can complete full workflow: discover → build → test → save
✅ Performance better than CLI spawning
✅ Clean interface without unnecessary parameters

## Testing Strategy

1. **Unit Tests**: Each tool in isolation
2. **Integration Tests**: Complete workflow cycles
3. **Agent Testing**: Use actual AGENT_INSTRUCTIONS examples
4. **Performance Tests**: Compare with CLI execution times
5. **Security Tests**: Path traversal, sensitive data

## Estimated Timeline

- Phase 1 (Core): 2 days
- Phase 2 (Supporting): 1 day
- Phase 3 (Testing): 1 day
- Phase 4 (Advanced): 0.5 day
- **Total: 4.5 days**

## Notes

This implementation is based on extensive research documented in:
- `starting-context/final-implementation-spec.md` - Complete technical specification
- `starting-context/pflow-commands-extraction.md` - Analysis of CLI commands agents use
- `starting-context/critical-analysis.md` - Resolution of documentation conflicts

The MCP server provides the same capabilities as CLI but with:
- Structured responses (no text parsing)
- Better performance (no shell spawning)
- Programmatic access (for systems without shell)
- Clean interface (sensible defaults, no unnecessary flags)

Key insight from research: Agents follow a strict workflow pattern (discover → build → test → save) that the MCP server must support with appropriate defaults and built-in behaviors.
