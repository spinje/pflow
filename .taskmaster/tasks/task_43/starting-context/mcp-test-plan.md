# MCP Test Client Implementation Plan

## Purpose

Establish a test harness using the official MCP Python SDK to validate our understanding of the protocol before implementing pflow's MCPNode. This approach minimizes risk and provides a reference implementation.

## Verified Technical Stack

### Official MCP Python SDK
- **Repository**: github.com/modelcontextprotocol/python-sdk
- **Installation**: `uv add "mcp[cli]"`
- **Architecture**: Async-only with asyncio
- **Supported Transports**: stdio, SSE, Streamable HTTP
- **Key Classes**: `ClientSession`, `StdioServerParameters`, `stdio_client`

### MCP Inspector Tool
- **Documentation**: modelcontextprotocol.io/docs/tools/inspector
- **Usage**: `npx @modelcontextprotocol/inspector <server-command>`
- **Purpose**: Visual debugging and server testing
- **No installation required**: Runs directly via npx

### Available Test Servers
- **Filesystem**: `@modelcontextprotocol/server-filesystem`
- **GitHub**: `@modelcontextprotocol/server-github` (requires GITHUB_TOKEN)
- **Installation**: Via npx, no local install needed

## Test Strategy

### Phase 1: Protocol Validation (Day 1 Morning)

**Objective**: Confirm MCP protocol understanding

**Test 1.1: Inspector Smoke Test**
- Run filesystem server in Inspector
- Verify tools are listed
- Execute a read_file operation
- Observe JSON-RPC messages in logs

**Test 1.2: SDK Connection Test**
- Create minimal Python client using official SDK
- Connect to filesystem server via stdio
- Perform initialize handshake
- List available tools
- Execute simple tool call

**Expected Outcomes**:
- Understand message format
- Confirm handshake sequence
- Validate tool discovery process
- Document error handling patterns

### Phase 2: Protocol Deep Dive (Day 1 Afternoon)

**Objective**: Understand implementation requirements

**Test 2.1: Message Logging**
- Create client that logs all JSON-RPC messages
- Capture complete session:
  - Initialize request/response
  - Tools/list request/response
  - Tool call request/response
  - Error scenarios

**Test 2.2: Error Handling**
- Test invalid tool names
- Test malformed parameters
- Test timeout scenarios
- Test server disconnection

**Test 2.3: Performance Characteristics**
- Measure handshake latency
- Measure tool discovery time
- Test concurrent tool calls (if supported)
- Memory usage of server processes

**Expected Outcomes**:
- Complete protocol documentation
- Error code mapping
- Performance baseline
- Resource requirements

### Phase 3: pflow Integration Analysis (Day 2 Morning)

**Objective**: Design MCPNode implementation

**Test 3.1: Async-to-Sync Wrapper**
- Test wrapping async SDK calls in sync functions
- Evaluate asyncio.run() overhead
- Test thread safety considerations

**Test 3.2: Subprocess Management**
- Test server lifecycle (start/stop)
- Test cleanup on errors
- Test multiple server instances

**Test 3.3: Registry Integration Mock**
- Simulate tool discovery to registry format
- Test parameter schema conversion
- Test virtual node creation

**Expected Outcomes**:
- Async wrapper design
- Subprocess management strategy
- Registry update mechanism

## Implementation Checklist

### Prerequisites
- [ ] Node.js/npm installed (for npx)
- [ ] Python 3.9+ with uv
- [ ] GitHub token (optional, for GitHub server testing)

### Test Artifacts to Create
- [ ] `test-client.py` - SDK-based test client
- [ ] `protocol-logger.py` - Message capture tool
- [ ] `async-wrapper.py` - Sync wrapper prototype
- [ ] `test-results.json` - Captured protocol messages
- [ ] `performance-metrics.md` - Timing and resource data

### Documentation to Generate
- [ ] Protocol specification summary
- [ ] Error code reference
- [ ] Tool schema examples
- [ ] Implementation recommendations

## Risk Mitigation

### Identified Risks

1. **Async-only SDK**
   - Risk: pflow nodes are synchronous
   - Mitigation: Build asyncio.run() wrapper
   - Test: Verify no event loop conflicts

2. **Subprocess Management**
   - Risk: Zombie processes, resource leaks
   - Mitigation: Proper cleanup handlers
   - Test: Kill/restart scenarios

3. **Protocol Changes**
   - Risk: MCP spec evolves
   - Mitigation: Version checking in handshake
   - Test: Multiple protocol versions

4. **Heavy Dependencies**
   - Risk: SDK pulls in many packages
   - Mitigation: Build minimal client for pflow
   - Test: Measure dependency impact

## Success Criteria

### Must Have
- [ ] Successfully connect to filesystem MCP server
- [ ] List and execute tools programmatically
- [ ] Handle errors gracefully
- [ ] Document complete message flow

### Should Have
- [ ] Test multiple server types
- [ ] Measure performance characteristics
- [ ] Create reusable test utilities
- [ ] Build sync wrapper prototype

### Nice to Have
- [ ] Test HTTP/SSE transports
- [ ] Automated test suite
- [ ] Benchmark against direct implementations

## Timeline

**Day 1 (4 hours)**
- Morning: Phase 1 - Protocol Validation
- Afternoon: Phase 2 - Protocol Deep Dive

**Day 2 (4 hours)**
- Morning: Phase 3 - Integration Analysis
- Afternoon: Document findings and recommendations

**Day 3 (4 hours)**
- Morning: Build MCPNode prototype
- Afternoon: Integration with registry

## Decision Points

After test completion, decide:

1. **Client Implementation**
   - Use SDK with wrapper? (easier but heavier)
   - Build minimal client? (harder but lighter)
   - Hybrid approach? (SDK for testing, minimal for production)

2. **Transport Focus**
   - stdio only for MVP? (recommended)
   - Plan for HTTP/SSE? (future)

3. **Registry Strategy**
   - Direct manipulation? (fastest)
   - Enhanced scanner? (cleaner)

## Conclusion

This test plan provides a systematic approach to understanding MCP before implementation. By using the official SDK for testing, we can:
- Validate our assumptions
- Understand edge cases
- Build with confidence
- Have reference implementation for debugging

The investment of 1-2 days in testing will save weeks of debugging later.