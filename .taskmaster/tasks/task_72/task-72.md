# Task 72: Implement MCP Server for pflow (Future Work)

## ID
72

## Title
Implement MCP Server for pflow (Future Work)

## Description
Build an MCP (Model Context Protocol) server that exposes pflow's capabilities as tools for AI agents, but ONLY if the CLI-first approach from Task 71 proves insufficient. This task preserves all the research and planning from the original Task 71 design, ready for implementation if needed.

## Status
deferred

## Dependencies
- Task 71: Complete CLI Commands - Must be tested with agents first to determine if MCP is needed
- Task 68: Refactor RuntimeValidation and Workflow Execution - Provides clean APIs if MCP is built

## Priority
low (deferred until CLI approach validated)

## Details

### Why This Task Exists

During Task 70's validation, we initially designed a comprehensive MCP server implementation. However, we discovered that:
1. pflow already has ~24 CLI commands with 95% of needed functionality
2. AI agents already excel at file editing and CLI execution
3. The simpler approach is to complete the CLI with intelligent discovery

This task preserves all the MCP research and design for future implementation if the CLI approach proves insufficient.

### What Task 71 Now Provides

Task 71 implements intelligent, LLM-powered discovery via CLI:
- `pflow discover-nodes "query"` - Rich discovery with complete interface details
- `pflow discover-workflows "query"` - Find workflows with full metadata
- `pflow workflow save` - Promote drafts to library
- `pflow workflow describe --json` - Structured workflow details

This discovery-first approach means agents describe what they want and receive complete, curated information.

### When to Activate This Task

Consider implementing the MCP server when:
- **Performance issues** with spawning multiple CLI commands
- **Stateful sessions** are needed (CLI is stateless)
- **Concurrent operations** from multiple agents on same workflow
- **Authentication/authorization** is required
- **Programmatic workflow generation** (not just discovery)
- **Direct integration** without shell access

Note: The CLI's LLM-powered discovery may eliminate many use cases we originally thought needed MCP.

### Preserved Research and Design

All research documents from the original MCP design:
- `task-72-spec.md` - Original MCP specification
- `task-72-comprehensive-research.md` - Technical analysis and code snippets
- `task-72-handover.md` - Critical tacit knowledge about stateless design
- `mcp-server-architecture.md` - Architectural decisions
- `mcp-protocol-best-practices.md` - MCP implementation patterns
- `task-72-implementation-prompt.md` - Implementation instructions

### Potential MCP Tools (If Implemented)

If MCP is needed, consider these tools based on what CLI cannot provide efficiently:

1. **discover_components** - Mirror CLI's discover-nodes but with structured response
2. **discover_workflows** - Mirror CLI's discover-workflows with programmatic access
3. **execute_workflow** - Run with structured error handling and checkpoints
4. **generate_workflow** - Programmatically create workflows (beyond discovery)
5. **manage_session** - Handle stateful workflow editing sessions

Note: These would likely wrap the CLI's discovery logic but provide:
- Structured JSON responses without parsing
- Session management
- Concurrent access control
- Performance optimization (no shell spawning)

### Key Design Principles (Preserved)

- **Stateless Design**: Fresh instances per request
- **Agent-Orchestrated Repair**: Return errors with checkpoints, not auto-repair
- **Minimal Tool Set**: Cognitive load reduction
- **Leverage CLI Logic**: Reuse discovery and execution from Task 71
- **asyncio.to_thread()**: Bridge async MCP to sync pflow

### Implementation Estimate

If activated:
- 5-10 hours if wrapping CLI commands
- 15-20 hours if implementing direct service integration

The estimate is reduced because Task 71's discovery logic can be reused.

### What We Learned

The evolution of our understanding:
1. **First**: 14 MCP tools mimicking every CLI command
2. **Then**: 5 focused tools for core operations
3. **Finally**: CLI-first with intelligent discovery
4. **Future**: MCP only if specific limitations emerge

Key insights:
- Rich discovery eliminates many tool needs
- LLM-powered selection is more powerful than listing
- Agents prefer natural language queries over structured browsing
- Complete information in one shot beats multiple queries

## Success Criteria (If Activated)

✅ MCP tools provide same discovery intelligence as CLI
✅ Structured responses without text parsing
✅ Session management for complex workflows
✅ Performance improvement over CLI spawning
✅ Concurrent access handled correctly
✅ Authentication/authorization if needed

## Notes

This task represents the evolution of our thinking:
- We started with complex MCP infrastructure
- Discovered the power of LLM-powered discovery
- Implemented it in CLI first (simpler, faster)
- Preserved MCP option for specific future needs

The CLI's discovery-first approach may be sufficient for most use cases. MCP becomes valuable primarily for performance, session management, and programmatic integration scenarios.

The key insight: "Even more simple" led us to CLI, but MCP remains an option for specific advanced requirements.