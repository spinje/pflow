# Task 89: Implement Structure-Only Mode and Selective Data Retrieval

## ID
89

## Title
Implement Structure-Only Mode and Selective Data Retrieval

## Description
Transform pflow's registry run command to return only structure (no actual data) by default, dramatically reducing token consumption for AI agents. Add a new read-fields tool that enables selective retrieval of specific data fields from cached node execution results, providing 600x token efficiency improvement over traditional tool calling approaches.

## Status
not started

## Dependencies
- Task 76: Implement Registry Execute Command for Independent Node Testing by agents - The registry run command infrastructure that we're modifying is already implemented here
- Task 72: Implement MCP Server for pflow - The MCP server integration needs to expose both the modified registry_run and new read_fields tools

## Priority
high

## Details
This task addresses the "intermediate tool results consume additional tokens" problem outlined in Anthropic's MCP blog post. The current registry run command returns full data output plus structure, which can consume hundreds of thousands of tokens for large responses (e.g., 100+ GitHub issues).

The solution involves two key changes:

### 1. Modify Registry Run to Return Structure-Only
The existing `registry run` command (both CLI and MCP) will be modified to:
- Execute the node normally but only return structure/schema information
- Show available template paths (like `${result[0].title}`) without actual data values
- Return an execution ID for later data retrieval
- No new flags needed - this becomes the default behavior

**Example Output:**
```
✓ Node executed successfully
Execution ID: exec-12345-abc

Available template paths:
  ✓ ${result} (list, 847 items)
  ✓ ${result[0].id} (int)
  ✓ ${result[0].title} (str, ~50 chars)
  ✓ ${result[0].body} (str, ~2000 chars)
  ... (48 more fields filtered by smart filtering)
```

### 2. Implement read-fields Tool for Selective Data Access
A new tool that allows retrieving specific fields from cached execution results:
- Accepts execution ID and one or more field paths
- Returns only the requested data values
- Supports multiple fields in single call for efficiency
- Works identically in CLI and MCP interfaces

**CLI Examples:**
```bash
# Single field
pflow read-fields exec-12345-abc result[0].title

# Multiple fields
pflow read-fields exec-12345-abc result[0].title result[0].id result[0].state
```

### 3. Lightweight Execution Cache
Store node execution results temporarily:
- Location: `~/.pflow/cache/node-executions/{execution_id}.json`
- Simple structure: just node_type, params, timestamp, and outputs
- 24-hour TTL with automatic cleanup
- Shared between CLI and MCP interfaces

### 4. Smart Structure Filtering (when >50 fields)
For complex API responses with many fields:
- Use Haiku 3.5 to intelligently filter structure to relevant fields only
- Remove obvious metadata fields (URLs, IDs, timestamps)
- Keep business-relevant fields (titles, content, status)
- Reduces structure from 200+ fields to ~8 relevant ones

### Key Technical Considerations
- **Code Sharing**: Both CLI and MCP must use shared formatters and services
- **Security**: Agent permissions for read-fields tool configurable in agent settings
- **Performance**: Cache lookup must be fast (<100ms)
- **Storage**: Implement TTL-based cleanup to prevent unbounded growth
- **Backwards Compatibility**: Not a concern (MVP with no users)

### Implementation Approach
1. Create `ExecutionCache` class for storing/retrieving results
2. Modify `registry_run.py` to save outputs and return execution ID
3. Update shared formatter to show structure without data
4. Implement `read-fields` command in CLI
5. Add corresponding MCP tools (registry_run already exists, add read_fields)
6. Implement smart filtering for complex structures
7. Add cleanup mechanism for old cache entries

### Token Efficiency Improvements
- Traditional tool calling: ~200,000 tokens for 1000 records
- Anthropic's code execution: ~3,500 tokens
- **pflow structure-only**: ~300 tokens (600x improvement)

### Security Benefits
- AI never sees sensitive data by default
- Data access requires explicit read-fields call
- Enables audit trail of what data was accessed
- Supports enterprise compliance requirements (GDPR, HIPAA)

## Test Strategy
Comprehensive testing will ensure both efficiency and security:

### Unit Tests
- `ExecutionCache` class: store, retrieve, TTL expiry
- Structure extraction without data values
- Field path parsing for read-fields
- Smart filtering logic with mock LLM responses

### Integration Tests
- End-to-end flow: registry run → execution ID → read-fields
- CLI and MCP parity verification
- Large data handling (100MB+ responses)
- Cache cleanup after TTL expiry
- Multiple field retrieval in single call

### Security Tests
- Verify no sensitive data in structure output
- Test permission controls for read-fields
- Validate execution ID cannot be guessed
- Ensure cache files have proper permissions (600)

### Performance Tests
- Cache lookup speed with 1000+ entries
- Smart filtering response time
- Memory usage with large cached results
- Concurrent access to cache

### Edge Cases
- Non-existent execution IDs
- Expired cache entries
- Invalid field paths
- Complex nested structures
- Binary data handling