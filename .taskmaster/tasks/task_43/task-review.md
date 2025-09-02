# Task 43 Review: MCP (Model Context Protocol) Server Support

## Executive Summary
Implemented comprehensive MCP support enabling pflow to connect to any MCP-compatible server (GitHub, Slack, filesystem) through a universal node architecture with virtual registry entries. This fundamentally changes how pflow integrates with external tools - instead of writing custom nodes, we now discover and register tools dynamically.

## Implementation Overview

### What Was Built
Built a **universal MCPNode** that handles ALL MCP tools through metadata injection, not the originally planned per-tool node generation. Key deviation: Instead of generating Python files for each tool, we use virtual registry entries (`"file_path": "virtual://mcp"`) all pointing to the same MCPNode class. The compiler injects `__mcp_server__` and `__mcp_tool__` parameters to identify which tool to execute.

### Implementation Approach
Chose **virtual node architecture** over code generation because:
- Single point of maintenance for all MCP tools
- No filesystem pollution with generated files
- Instant tool availability after discovery
- Easier debugging (one class to instrument)

## Files Modified/Created

### Core Changes
- `src/pflow/nodes/mcp/node.py` - Universal MCPNode with async-to-sync bridge
- `src/pflow/mcp/manager.py` - Server configuration with atomic writes
- `src/pflow/mcp/discovery.py` - Tool discovery and JSON Schema conversion
- `src/pflow/mcp/registrar.py` - Virtual registry entry creation
- `src/pflow/cli/mcp.py` - CLI commands (add/sync/list/remove/tools)
- `src/pflow/cli/main_wrapper.py` - Special handling for "mcp" subcommand
- `src/pflow/runtime/compiler.py` - Added `_inject_special_parameters()` for metadata

### Test Files
- `tests/test_mcp/test_metadata_injection.py` - Compiler injection (9 tests) - CRITICAL
- `tests/test_mcp/test_config_management.py` - Atomic writes, security (7 tests) - CRITICAL
- `tests/test_mcp/test_mcp_node_behavior.py` - Async bridge, results (11 tests)
- `tests/test_mcp/test_mcp_integration.py` - Full pipeline (3 tests)
- `tests/test_mcp/test_mcp_discovery_critical.py` - Discovery/registration (5 tests) - NEW
- `tests/test_mcp/test_mcp_node_critical.py` - Critical behaviors (4 tests) - NEW

## Integration Points & Dependencies

### Incoming Dependencies
- **Planner** -> MCP nodes (discovers via registry like any other node)
- **Compiler** -> `_inject_special_parameters()` (injects metadata for MCP nodes)
- **Registry** -> Virtual entries (all point to MCPNode class)
- **Template Resolver** -> MCPNode params (must preserve types)

### Outgoing Dependencies
- MCPNode -> **MCP SDK** (`mcp` package for protocol communication)
- MCPNode -> **asyncio** (bridges async SDK to sync PocketFlow)
- MCPNode -> **MCPServerManager** (loads server configs)
- Discovery -> **MCP servers** (connects to discover tools)

### Shared Store Keys
- `result` - Generic result from any MCP tool
- `{server}_{tool}_result` - Server-specific result (e.g., `github_create-issue_result`)
- `error` - Error message when tool fails
- `error_details` - Structured error info
- **Structured fields** - Extracted from result (e.g., `issue_url`, `issue_number`)

## Architectural Decisions & Tradeoffs

### Key Decisions

**Virtual Registry Entries** -> Avoids code generation complexity -> Considered: Generating Python files per tool

**Single MCPNode Class** -> One implementation to maintain -> Considered: Inheritance hierarchy per server

**Metadata Injection in Compiler** -> Clean separation of concerns -> Considered: Registry storing metadata

**max_retries=1** -> Prevents multiple server processes -> Learned: Each retry spawns new subprocess

**Return "default" not "error"** -> Works around planner limitation -> Planner doesn't generate error edges

### Technical Debt Incurred

- **No connection pooling** - Each execution creates new MCP server process
- **No async flow support** - Using asyncio.run() blocks event loop
- **Planner workaround** - Returns "default" on error instead of proper error handling
- **No CLI command tests** - CLI commands untested due to complexity

## Testing Implementation

### Test Strategy Applied
Focused on **tests that catch real bugs** over coverage metrics. After reviewer feedback, fixed critical issues:
- Atomic write test now actually tests temp file + rename
- Concurrent access test uses real threading
- Security tests for path traversal and injection
- Integration tests use real `flow.run()` not mocked calls

### Critical Test Cases
- `test_max_retries_prevents_multiple_processes` - Prevents resource exhaustion
- `test_atomic_write_mechanism_prevents_corruption` - Config integrity
- `test_path_traversal_in_server_names_blocked` - Security vulnerability
- `test_compiler_metadata_injection_through_real_stack` - Full integration
- `test_structured_data_extraction_to_shared_store` - Data accessibility

## Unexpected Discoveries

### Gotchas Encountered

**Registry Structure Requirements**: Must use `"key"` not `"name"` in params/outputs. Must have empty `"inputs": []` for MCP nodes. This wasn't documented anywhere.

**Type Preservation Bug**: Template resolver was converting all values to strings. Had to fix to preserve int/bool/float types or MCP validation fails.

**ExceptionGroup Wrapping**: MCP SDK wraps errors in ExceptionGroups. Had to extract meaningful messages in `exec_fallback()`.

**Retry Process Bug**: Each retry starts a NEW subprocess. Without max_retries=1, Slack server would spawn 3+ processes causing "unhandled errors in TaskGroup" crashes.

### Edge Cases Found

- Tool names with underscores (e.g., `list_repositories`) must be preserved exactly
- Server names can't contain special characters or path traversal sequences
- Environment variables must expand at runtime, not config save time
- Multiple MCP nodes in same workflow need result namespacing

## Patterns Established

### Reusable Patterns

**Virtual Node Pattern**:
```python
# Registry entry points to universal class with virtual path
{
    "mcp-server-tool": {
        "class_name": "UniversalNode",
        "module": "pflow.nodes.universal",
        "file_path": "virtual://universal",  # Not a real file
        "interface": {...}
    }
}
```

**Metadata Injection Pattern**:
```python
# Compiler injects special params based on node type
if node_type.startswith("mcp-"):
    parts = node_type.split("-", 2)
    params["__mcp_server__"] = parts[1]
    params["__mcp_tool__"] = "-".join(parts[2:])
```

**Async-to-Sync Bridge**:
```python
# Bridge async SDK to sync PocketFlow
def exec(self, prep_res):
    return asyncio.run(self._exec_async(prep_res))
```

### Anti-Patterns to Avoid

- Don't add server-specific logic to MCPNode - it must remain universal
- Don't mock internal methods in tests - mock only at boundaries
- Don't generate Python files for dynamic content - use virtual entries
- Don't retry MCP operations - each retry spawns processes

## Breaking Changes

### API/Interface Changes
None - MCP nodes appear as regular nodes to the rest of the system.

### Behavioral Changes
- Planner now discovers many more nodes after `pflow mcp sync`
- Error handling returns "default" action, not "error"

## Future Considerations

### Extension Points
- `MCPNode._extract_result()` - Add handlers for new content types
- `MCPDiscovery.convert_to_pflow_params()` - Enhance schema conversion
- Connection pooling could be added in `_exec_async()`

### Scalability Concerns
- Each execution spawns new process (no connection reuse)
- Large number of tools could slow planner's discovery phase
- No caching of MCP responses

## AI Agent Guidance

### Quick Start for Related Tasks

**If implementing similar tool integrations:**
1. Read `src/pflow/nodes/mcp/node.py` - Universal node pattern
2. Read `src/pflow/runtime/compiler.py::_inject_special_parameters()` - Metadata injection
3. Read `tests/test_mcp/test_metadata_injection.py` - How injection works
4. Use virtual registry entries, not code generation

**Key files to understand first:**
- How virtual nodes work: `src/pflow/mcp/registrar.py::_create_registry_entry()`
- How metadata flows: Follow `__mcp_server__` through the codebase
- How async bridging works: `MCPNode.exec()` and `_exec_async()`

### Common Pitfalls

1. **Don't test with mocks everywhere** - Integration bugs hide behind mocks
2. **Registry structure is strict** - Must have `"key"` not `"name"`, empty `"inputs": []`
3. **Type preservation critical** - Template resolver must not stringify numbers/bools
4. **max_retries must be 1** - Or you'll spawn multiple server processes
5. **Test atomic writes correctly** - Mock `Path.replace()` not `json.dump()`

### Test-First Recommendations

When modifying MCP integration:
1. Run `pytest tests/test_mcp/test_metadata_injection.py` - Verify injection works
2. Run `pytest tests/test_mcp/test_mcp_integration.py` - Check full pipeline
3. Add test for your specific server's response format in `test_mcp_node_behavior.py`
4. Test with real MCP server if possible - mocks hide protocol issues

---

*Generated from implementation context of Task 43*
*Session ID: 14dd2d1f-ce4d-44d3-9f7e-2266f13dbbc6*
*PR URL: https://github.com/spinje/pflow/pull/9*