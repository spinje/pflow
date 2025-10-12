# Task 72: MCP Server Implementation Plan

## Overview

This plan breaks down the MCP server implementation into 5 phases, each with clear deliverables, verification steps, and tests. Each phase builds on the previous one and can be independently verified.

## Phase Structure

Each phase follows this pattern:
1. **Implementation**: Create the specified components
2. **Review**: Stop for user review
3. **Verification**: Manual testing with MCP Inspector or similar
4. **Automated Tests**: Write unit and integration tests
5. **Proceed**: Move to next phase after approval

---

## Phase 1: Foundation & Basic Infrastructure

**Goal**: Establish the MCP server foundation with one simple tool to verify everything works.

### Deliverables

1. **Directory Structure**:
   ```
   src/pflow/mcp_server/
   ├── __init__.py
   ├── server.py         # FastMCP instance
   ├── main.py           # Entry point with stdio
   └── tools/
       ├── __init__.py
       └── test_tools.py # One simple tool for verification
   ```

2. **CLI Integration**:
   - Add `pflow serve mcp` command to `src/pflow/cli/commands/serve.py`
   - Proper stdio handling (stdout for protocol, stderr for logs)
   - Signal handlers for graceful shutdown

3. **Basic Tool**:
   - Implement `ping` tool that returns `{"status": "pong", "timestamp": ...}`
   - Verifies async/sync bridge pattern works
   - Tests error handling with optional `error` parameter

### Verification Steps

1. Start server: `pflow serve mcp`
2. Test with MCP Inspector: `npx @modelcontextprotocol/inspector python -m pflow.cli.main serve mcp`
3. Call ping tool and verify response
4. Test error handling by passing error=true parameter
5. Test graceful shutdown with Ctrl+C

### Tests to Write

- `test_mcp_server/test_server_startup.py` - Server lifecycle
- `test_mcp_server/test_ping_tool.py` - Basic tool functionality
- `test_mcp_server/test_stdio_transport.py` - Protocol communication

---

## Phase 2: Core Discovery Tools (Priority 1 - Part 1)

**Goal**: Implement intelligent discovery tools using planning nodes.

### Deliverables

1. **Service Layer**:
   ```
   src/pflow/mcp_server/
   └── services/
       ├── __init__.py
       ├── discovery_service.py  # Wraps planning nodes
       └── base_service.py       # Stateless pattern enforcement
   ```

2. **Discovery Tools** (`tools/discovery_tools.py`):
   - `workflow_discover` - Find existing workflows (uses WorkflowDiscoveryNode)
   - `registry_discover` - Find nodes for tasks (uses ComponentBrowsingNode)

3. **Error Handling** (`utils/errors.py`):
   - Error formatting helpers
   - Sanitization functions
   - LLM-friendly error messages

### Verification Steps

1. Test workflow discovery: "Find workflows for GitHub automation"
2. Verify confidence scores and reasoning
3. Test registry discovery: "Find nodes to fetch and analyze data"
4. Verify LLM intelligence is working (not just keyword matching)
5. Test error cases (empty queries, invalid requests)

### Tests to Write

- `test_mcp_server/test_discovery_tools.py` - Discovery functionality
- `test_mcp_server/test_services/test_discovery_service.py` - Service layer
- `test_mcp_server/test_stateless_pattern.py` - Verify fresh instances

---

## Phase 3: Core Execution Tools (Priority 1 - Part 2)

**Goal**: Implement the core workflow execution loop.

### Deliverables

1. **Execution Service** (`services/execution_service.py`):
   - Workflow resolution (name vs path vs IR)
   - Execution with NullOutput
   - Checkpoint extraction

2. **Execution Tools** (`tools/execution_tools.py`):
   - `workflow_execute` - Execute with checkpoints
   - `workflow_validate` - Structural validation
   - `registry_run` - Test nodes to reveal output structure
   - `workflow_save` - Save to global library

3. **Security** (`utils/validation.py`):
   - Path traversal prevention
   - Workflow name validation
   - Parameter sanitization

### Verification Steps

1. Execute a simple workflow with parameters
2. Verify checkpoint on failure
3. Test validation with invalid workflows
4. Test registry_run with MCP nodes (reveals nested structure)
5. Save a workflow and verify it's accessible

### Tests to Write

- `test_mcp_server/test_execution_tools.py` - All execution tools
- `test_mcp_server/test_checkpoint_recovery.py` - Checkpoint functionality
- `test_mcp_server/test_security.py` - Path traversal, sanitization

---

## Phase 4: Supporting Tools (Priority 2)

**Goal**: Implement supporting tools for complete workflows.

### Deliverables

1. **Registry Tools** (`tools/registry_tools.py`):
   - `registry_describe` - Detailed node specs
   - `registry_search` - Pattern-based search
   - `registry_list` - List all nodes

2. **Workflow Management** (`tools/workflow_tools.py` - extend):
   - `workflow_list` - List saved workflows

3. **Settings Tools** (`tools/settings_tools.py`):
   - `settings_get` - Retrieve settings
   - `settings_set` - Configure API keys

### Verification Steps

1. Test complete workflow: discover → build → test → save → list
2. Configure API keys via settings
3. Search for specific node types
4. List and filter workflows

### Tests to Write

- `test_mcp_server/test_registry_tools.py` - Registry operations
- `test_mcp_server/test_settings_tools.py` - Settings management
- `test_mcp_server/test_workflow_management.py` - Workflow operations

---

## Phase 5: Advanced Tools & Polish (Priority 3)

**Goal**: Complete implementation with advanced features and polish.

### Deliverables

1. **Trace Tool** (`tools/trace_tools.py`):
   - `trace_read` - Parse and return trace data

2. **Performance Optimizations**:
   - Connection pooling for LLM calls
   - Caching for registry (if needed)
   - Response size optimization

3. **Documentation**:
   - User guide for MCP server
   - Tool documentation
   - Integration examples

4. **Integration Tests**:
   - Full AGENT_INSTRUCTIONS workflows
   - CLI/MCP parity tests
   - Performance benchmarks

### Verification Steps

1. Read trace from failed execution
2. Test with full agent workflows
3. Performance comparison with CLI
4. Security audit
5. Documentation review

### Tests to Write

- `test_mcp_server/test_trace_tools.py` - Trace functionality
- `test_integration/test_mcp_agent_workflows.py` - Full workflows
- `test_integration/test_cli_mcp_parity.py` - Ensure same behavior
- `test_performance/test_mcp_performance.py` - Benchmarks

---

## Success Criteria

Each phase is successful when:

### Phase 1
- ✅ Server starts and responds to ping
- ✅ Stdio transport works correctly
- ✅ Logging goes to stderr only
- ✅ Graceful shutdown works

### Phase 2
- ✅ Discovery tools use LLM intelligence
- ✅ Confidence scores guide decisions
- ✅ Stateless pattern verified

### Phase 3
- ✅ Complete execution loop works
- ✅ Checkpoints enable recovery
- ✅ MCP node structures revealed
- ✅ Security validations in place

### Phase 4
- ✅ All 13 tools implemented
- ✅ Settings management works
- ✅ Complete workflows possible

### Phase 5
- ✅ Performance meets or beats CLI
- ✅ All AGENT_INSTRUCTIONS workflows work
- ✅ Documentation complete
- ✅ Production ready

---

## Risk Mitigation

### Technical Risks

1. **FastMCP compatibility**: Start with simple tool in Phase 1 to verify
2. **Planning node integration**: Test in Phase 2 before building on it
3. **Thread safety**: Verify stateless pattern in Phase 2
4. **Performance**: Benchmark in each phase, optimize in Phase 5

### Process Risks

1. **Scope creep**: Stick to 13 tools defined in spec
2. **Over-engineering**: Follow validated patterns from research
3. **Testing gaps**: Write tests immediately after implementation
4. **Integration issues**: Test with real workflows early (Phase 3)

---

## Timeline

- **Phase 1**: 0.5 days (Foundation)
- **Phase 2**: 0.5 days (Discovery)
- **Phase 3**: 1.5 days (Execution)
- **Phase 4**: 1 day (Supporting)
- **Phase 5**: 1 day (Polish)

**Total**: 4.5 days (matches task estimate)

---

## Implementation Notes

### Critical Patterns (Must Follow)

1. **Stateless**: Fresh instances for every request
2. **Async Bridge**: Use `asyncio.to_thread()` for sync code
3. **Error Handling**: `CallToolResult` with `isError=True`
4. **Logging**: stderr only, stdout for protocol
5. **Security**: Sanitize all errors and validate all inputs

### File Organization

- 4-6 tool files grouped by domain (not 13 separate files)
- Service layer for business logic
- Utils for cross-cutting concerns
- Tests mirror source structure

### Dependencies

Add to `pyproject.toml`:
```toml
dependencies = [
    # existing deps...
    "mcp[cli]>=1.17.0",
]
```

---

## Ready to Start

This plan provides a clear path from foundation to production-ready MCP server. Each phase builds on the previous one with verification points to ensure quality.

**Next Step**: Begin Phase 1 implementation.