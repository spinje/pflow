# MCP Smart Sync - Implementation Checklist

## Pre-Implementation Checks
- [ ] Verify if Registry already has metadata support
  - Check for `get_metadata()` and `set_metadata()` methods
  - If not, need to add them

## Core Implementation

### 1. Registry Metadata Support
- [ ] Add `get_metadata()` method to Registry class
- [ ] Add `set_metadata()` method to Registry class
- [ ] Ensure metadata persists in `__metadata__` key
- [ ] Test metadata persistence across runs

### 2. Update Auto-Discovery
**File**: `src/pflow/cli/main.py`

- [ ] Add imports: `hashlib`, `json`, `time`
- [ ] Replace current `_auto_discover_mcp_servers()` implementation
- [ ] Add config mtime check
- [ ] Add servers hash calculation
- [ ] Implement skip logic when unchanged
- [ ] Implement full sync when changed
- [ ] Add metadata updates after sync
- [ ] Add progress messages

### 3. Update Manual Sync
**File**: `src/pflow/cli/mcp.py`

- [ ] Update `sync` command to set `mcp_last_sync_time`
- [ ] Update `sync` command to set `mcp_servers_hash`
- [ ] Test manual sync updates metadata

### 4. Error Handling
- [ ] Handle missing config file gracefully
- [ ] Handle corrupted config file
- [ ] Handle registry permission errors
- [ ] Handle concurrent access

## Testing

### Functional Tests
- [ ] Test: No sync when config unchanged
- [ ] Test: Sync triggers when config modified
- [ ] Test: Sync triggers when server added via `pflow mcp add`
- [ ] Test: Server rename removes old entries
- [ ] Test: Registry deletion triggers sync
- [ ] Test: First run triggers sync

### Performance Tests
- [ ] Measure: Time with no changes (<10ms expected)
- [ ] Measure: Time with changes (3-10s expected)
- [ ] Verify: No MCP server connections when cache valid

### Edge Case Tests
- [ ] Test: Multiple concurrent pflow runs
- [ ] Test: Config file permissions issues
- [ ] Test: Registry corruption recovery

## Documentation
- [ ] Update CLAUDE.md if needed
- [ ] Add comment explaining smart sync in code
- [ ] Log messages at debug level for troubleshooting

## Rollback Preparation
- [ ] Keep diff of changes for easy revert
- [ ] Test rollback procedure
- [ ] Document how to disable if needed

## Final Validation
- [ ] Run full test suite
- [ ] Test with real MCP servers
- [ ] Verify no regression in functionality
- [ ] Check startup time improvement

## Notes
- Start with simplest implementation
- Can optimize further if needed
- Priority is reliability over micro-optimizations