# ~/.pflow/ Directory Structure Research Summary

## Overview
The `~/.pflow/` directory is the home for all pflow user data, including configurations, cached data, debug traces, saved workflows, and registry information.

## Complete Directory Structure

```
~/.pflow/
├── settings.json            # User settings (node filters, env vars/API keys)
├── registry.json            # Node registry cache
├── mcp-servers.json         # MCP server configurations
├── CLAUDE.md                # (Optional) User guidance file
├── .DS_Store                # (macOS system file)
│
├── debug/                   # Debug trace files (NOT auto-cleaned)
│   ├── workflow-trace-{name}-{timestamp}.json
│   ├── planner-trace-{timestamp}.json
│   └── archive/             # (Optional user organization)
│
├── cache/                   # Execution cache for structure-only mode
│   └── registry-run/        # Node execution results cache
│       └── exec-{timestamp}-{random}.json
│
├── workflows/               # Saved workflow definitions
│   └── {workflow-name}.json
│
├── temp-workflows/          # Temporary draft workflows
│   └── (temporary files)
│
├── trash/                   # (Purpose unclear - may be manual)
│
├── instructions/            # (Purpose unclear - may be user-created)
│
├── knowledge/               # (Purpose unclear - may be user-created)
│
└── nodes/                   # (Purpose unclear - may be user nodes)
```

## File Details

### 1. Configuration Files (Root Level)

#### `settings.json` (0600 permissions for security)
- **Location**: `~/.pflow/settings.json`
- **Purpose**: User settings with node filtering and API key storage
- **Cleanup**: Manual only (permanent user settings)
- **Security**: Automatically chmod 0600 (owner-only) when saved
- **Code**: `src/pflow/core/settings.py` (SettingsManager)

#### `registry.json` (281KB)
- **Location**: `~/.pflow/registry.json`
- **Purpose**: Cached node registry for fast lookup
- **Regeneration**: Via `pflow registry scan`
- **Cleanup**: Can be safely deleted (regenerated on next scan)
- **Code**: `src/pflow/registry/registry.py`

#### `mcp-servers.json` (0600 permissions)
- **Location**: `~/.pflow/mcp-servers.json`
- **Purpose**: MCP server configurations
- **Cleanup**: Manual only (permanent configuration)
- **Code**: `src/pflow/mcp/manager.py`

### 2. Debug Directory (`debug/`)

#### Workflow Traces
- **Pattern**: `workflow-trace-{name}-{timestamp}.json`
- **Example**: `workflow-trace-fix-issue-20251212-143025.json`
- **Purpose**: Detailed execution traces for debugging workflows
- **Format Version**: "1.2.0" (tri-state status support)
- **Typical Size**: 1KB - 100KB+ (depends on workflow complexity)
- **Creation**: Automatic on every workflow execution
- **Cleanup**: NOT AUTOMATIC - Accumulates indefinitely
- **Code**: `src/pflow/runtime/workflow_trace.py`

**Observation**: User has 18+ planner traces from September 2025, some over 600KB

#### Planner Traces
- **Pattern**: `planner-trace-{timestamp}.json`
- **Example**: `planner-trace-20251212-143025.json`
- **Purpose**: Natural language planner execution traces
- **Typical Size**: 1KB - 600KB+ (includes prompts and responses)
- **Creation**: Automatic with `--trace-planner` flag
- **Cleanup**: NOT AUTOMATIC - Accumulates indefinitely
- **Code**: `src/pflow/planning/debug.py`

### 3. Cache Directory (`cache/`)

#### Registry Run Cache (`cache/registry-run/`)
- **Pattern**: `exec-{timestamp}-{random}.json`
- **Purpose**: Structure-only mode execution cache (Task 89)
- **Typical Size**: 200-1000 bytes per file
- **TTL**: 24 hours (stored in metadata but NOT enforced)
- **Cleanup**: NOT AUTOMATIC - Accumulates indefinitely
- **Code**: `src/pflow/core/execution_cache.py`

**Observation**: User has 19 cache files from November 2025

### 4. Workflows Directory (`workflows/`)

#### Saved Workflows
- **Pattern**: `{workflow-name}.json`
- **Purpose**: Permanently saved workflow definitions
- **Cleanup**: Manual only (via `pflow workflow delete`)
- **Code**: `src/pflow/core/workflow_manager.py`

## Cleanup Status Summary

| Directory | Auto-Cleanup | Status | Risk Level |
|-----------|--------------|--------|------------|
| settings.json | No | Permanent | None (essential) |
| registry.json | No | Regenerable | None (can delete) |
| mcp-servers.json | No | Permanent | None (essential) |
| debug/ | **No** | **Accumulates** | **High** (can grow to GB+) |
| cache/registry-run/ | **No** | **Accumulates** | Low (small files) |
| workflows/ | No | Permanent | None (user data) |

## User Inspection Commands

### View Directory Contents
```bash
# List all pflow data
ls -lh ~/.pflow/

# Check debug traces (sorted by size)
du -h ~/.pflow/debug/* | sort -h

# Count cache entries
ls ~/.pflow/cache/registry-run/ | wc -l

# List saved workflows
ls -lh ~/.pflow/workflows/
```

### Size Analysis
```bash
# Show size of each directory
du -sh ~/.pflow/*

# Find largest debug traces (top 10)
find ~/.pflow/debug -name "*.json" -ls | sort -k7 -n | tail -10

# Show oldest cache entries
ls -lt ~/.pflow/cache/registry-run/ | tail -20
```

## Manual Cleanup Guidelines

### Safe to Delete (regenerable):
- `~/.pflow/registry.json` - Will be regenerated on next scan
- `~/.pflow/debug/*.json` - Debug traces (backup first if needed)
- `~/.pflow/cache/` - All cache files

### Important to Keep:
- `~/.pflow/settings.json` - User settings and API keys
- `~/.pflow/mcp-servers.json` - MCP server configurations
- `~/.pflow/workflows/` - Saved workflow definitions

## Configuration Environment Variables

### Trace Configuration
- `PFLOW_TRACE_PROMPT_MAX` (default: 50000)
- `PFLOW_TRACE_RESPONSE_MAX` (default: 20000)
- `PFLOW_TRACE_STORE_MAX` (default: 10000)
- `PFLOW_TRACE_DICT_MAX` (default: 50000)
- `PFLOW_TRACE_LLM_CALLS_MAX` (default: 100)

### Settings Overrides
- `PFLOW_INCLUDE_TEST_NODES` (true/false)
- `PFLOW_TEMPLATE_RESOLUTION_MODE` (strict/permissive)

## Recommendations

### For Users:
1. **Monitor debug/ directory** - Can grow large over time
2. **Cache is low-impact** - Small files, safe to ignore
3. **Never manually edit protected files** (settings.json, mcp-servers.json)

### For Developers:
1. **Add cleanup commands**:
   - `pflow debug clean` - Remove old traces
   - `pflow cache clean` - Remove expired cache
2. **Implement TTL enforcement** for execution cache
3. **Add size warnings** when directories exceed thresholds
4. **Consider trace rotation** - Keep only last N traces

## Security Notes

1. **Sensitive Data**:
   - `settings.json` - Contains API keys (0600 permissions)
   - `mcp-servers.json` - Contains credentials (0600 permissions)
   - Cache files - Mask sensitive parameters
   - Trace files - NO automatic masking (may contain sensitive data)

2. **Permission Management**:
   - Settings automatically chmod 0600 on save
   - Validation warns if insecure permissions detected

## Code References

- `src/pflow/core/settings.py` - SettingsManager
- `src/pflow/mcp/manager.py` - MCPServerManager
- `src/pflow/registry/registry.py` - Registry
- `src/pflow/runtime/workflow_trace.py` - WorkflowTraceCollector
- `src/pflow/planning/debug.py` - TraceCollector (planner)
- `src/pflow/core/execution_cache.py` - ExecutionCache
- `src/pflow/core/workflow_manager.py` - WorkflowManager
