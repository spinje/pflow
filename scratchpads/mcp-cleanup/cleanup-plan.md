# MCP Format Cleanup Plan

## Current Issues Found

### 1. MCPServerManager (`src/pflow/mcp/manager.py`)
- **Migration code** (lines ~88-140): `_migrate_to_standard()` method - REMOVE
- **Internal conversion** (lines ~290-295): `_standard_to_internal_for_validation()` - REMOVE
- **Old "servers" key references**:
  - Line ~88: Migration check for "servers" key
  - Line ~90: Iterating over config["servers"]
  - Line ~404: Returning config["servers"]
- **"transport" field references**:
  - Multiple validation methods checking for "transport" field
  - Should use "type" field from standard format

### 2. MCPDiscovery (`src/pflow/mcp/discovery.py`)
- Line ~71: `transport = server_config.get("transport", "stdio")`
- Should use: `transport_type = "stdio" if server_config.get("type") != "http" else "http"`

### 3. Methods that need updating:
- `validate_server_config()` - currently validates internal format with "transport"
- `get_server()` - converts to internal format
- `get_all_servers()` - converts all to internal format
- `add_server()` - builds internal format configs
- `_build_stdio_config_standard()` - name is misleading, should just be `_build_stdio_config()`
- `_build_http_config_standard()` - name is misleading, should just be `_build_http_config()`

### 4. Documentation/Comments
- Remove all references to old format examples
- Remove migration-related comments
- Update docstrings to show standard format only

## Cleanup Steps

### Step 1: Remove ALL migration/conversion code
1. Delete `_migrate_to_standard()` method
2. Delete `_standard_to_internal_for_validation()` method
3. Remove migration logic from `load()` method

### Step 2: Update data access to use standard format
1. Change all `config["servers"]` to `config["mcpServers"]`
2. Change all `server_config.get("transport")` to check `type` field
3. Update validation to expect standard format fields

### Step 3: Simplify methods
1. Rename `_build_stdio_config_standard()` → `_build_stdio_config()`
2. Rename `_build_http_config_standard()` → `_build_http_config()`
3. Remove all internal format building - just return standard format

### Step 4: Fix validation
1. Update `validate_server_config()` to validate standard format:
   - No "transport" field
   - Use "type" field (optional for stdio, required for http)
   - Validate standard field names

### Step 5: Update all consuming code
1. MCPDiscovery - use "type" field
2. MCPNode - ensure it works with standard format
3. Any other code that reads configs

## Expected Result

After cleanup:
- NO references to "servers" key (only "mcpServers")
- NO references to "transport" field (only "type")
- NO conversion methods
- NO migration code
- ALL code works directly with standard MCP format
- Validation checks standard format fields

## Standard Format Reference

```json
{
  "mcpServers": {
    "server-name": {
      // For stdio (type is optional):
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}
    },
    "http-server": {
      "type": "http",  // Required for http
      "url": "https://api.example.com/mcp",
      "headers": {"Authorization": "Bearer ${TOKEN}"}
    }
  }
}
```

## Files to modify:
1. `/src/pflow/mcp/manager.py` - MAJOR cleanup
2. `/src/pflow/mcp/discovery.py` - Minor update
3. `/src/pflow/mcp/node.py` - Verify it works with standard format