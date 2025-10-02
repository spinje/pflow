# Existing CLI Commands & Helper Functions - MCP Tool Exposure Analysis

This document analyzes all existing pflow CLI commands and helper functions that could be exposed as MCP tools.

## Executive Summary

**Total Reusable Commands**: 24 commands across 5 groups
**Recommended for MCP**: 18 tools (marked with ✅)
**Implementation Strategy**: Thin wrapper pattern - MCP tools call existing CLI functions

---

## 1. Workflow Commands

### 1.1 `workflow list` ✅ HIGH VALUE
**Location**: `src/pflow/cli/commands/workflow.py:20`

**Core Function**:
```python
WorkflowManager().list_all()
```

**Returns**: List of workflow objects with name, description, created_at, execution_count

**MCP Tool**: `pflow_list_workflows`

---

### 1.2 `workflow describe` ✅ HIGH VALUE
**Location**: `src/pflow/cli/commands/workflow.py:108`

**Core Function**:
```python
WorkflowManager().load(name)  # Full metadata
```

**Returns**: Workflow description, inputs, outputs, example usage

**MCP Tool**: `pflow_describe_workflow`

---

## 2. MCP Management Commands

### 2.1 `mcp list` ✅ HIGH VALUE
**Location**: `src/pflow/cli/mcp.py:166`

**Core Function**:
```python
MCPServerManager().get_all_servers()
```

**Returns**: Dict of server configs (transport, command, url, etc.)

**MCP Tool**: `pflow_list_mcp_servers`

---

### 2.2 `mcp tools` ✅ HIGH VALUE
**Location**: `src/pflow/cli/mcp.py:445`

**Core Functions**:
```python
MCPRegistrar().list_registered_tools(server)
MCPRegistrar().get_tool_info(tool_name)
```

**Returns**: List of tool metadata (params, outputs, description)

**MCP Tool**: `pflow_list_mcp_tools`

**Helper**: `_get_tools_info_as_json()` (line 377) - perfect for MCP

---

### 2.3 `mcp info` ✅ MEDIUM VALUE
**Location**: `src/pflow/cli/mcp.py:521`

**Core Function**:
```python
MCPRegistrar().get_tool_info(tool)
```

**Returns**: Detailed tool schema

**MCP Tool**: `pflow_get_mcp_tool_info`

---

### 2.4 `mcp sync` ⚠️ SIDE-EFFECTS
**Location**: `src/pflow/cli/mcp.py:350`

**Core Functions**:
```python
MCPRegistrar().sync_server(name)
MCPRegistrar().sync_all_servers()
```

**Recommendation**: INCLUDE but mark as modifying operation

**MCP Tool**: `pflow_sync_mcp_server`

---

## 3. Registry Commands

### 3.1 `registry list` ✅ HIGH VALUE
**Location**: `src/pflow/cli/registry.py:202`

**Core Function**:
```python
Registry().load()
```

**Helper**: `_output_json_nodes()` (line 185) - already has JSON output

**Returns**: Array of node objects by package/type

**MCP Tool**: `pflow_list_nodes`

---

### 3.2 `registry describe` ✅ HIGH VALUE
**Location**: `src/pflow/cli/registry.py:356`

**Core Function**:
```python
Registry().load()
_resolve_node_name(node, nodes)  # Smart fuzzy matching
```

**Critical Feature**: Handles exact matches, underscores, MCP prefixes

**Returns**: Node interface (inputs, outputs, params)

**MCP Tool**: `pflow_describe_node`

---

### 3.3 `registry search` ✅ HIGH VALUE
**Location**: `src/pflow/cli/registry.py:526`

**Core Function**:
```python
Registry().search(query)
```

**Search Scoring**:
- Exact: 100 points
- Prefix: 90 points
- In name: 70 points
- In description: 50 points

**Returns**: Ranked results with scores

**MCP Tool**: `pflow_search_nodes`

---

## 4. Settings Commands

### 4.1 `settings show` ✅ MEDIUM VALUE
**Location**: `src/pflow/cli/commands/settings.py:38`

**Core Function**:
```python
SettingsManager().load()
```

**Returns**: Current settings + environment overrides

**MCP Tool**: `pflow_get_settings`

---

### 4.2 `settings check` ✅ MEDIUM VALUE
**Location**: `src/pflow/cli/commands/settings.py:171`

**Core Function**:
```python
SettingsManager().should_include_node(node_name)
```

**Returns**: Inclusion status + matching patterns

**MCP Tool**: `pflow_check_node_visibility`

---

## 5. Core Workflow Execution

### 5.1 Execute Workflow ✅ HIGHEST VALUE
**Location**: `src/pflow/cli/main.py:2794` (workflow_command)

**Core Functions**:
```python
resolve_workflow(workflow_str, ctx)  # Line 209
execute_json_workflow(ir_data, ctx, ...)  # Line 1376
```

**Integration**:
```python
from pflow.execution.workflow_execution import execute_workflow
```

**Returns**:
- success (boolean)
- output (any)
- metrics (duration, tokens, cost)
- repairs (array)

**MCP Tool**: `pflow_execute`

**Most Important Tool** - enables AI to run workflows

---

## 6. Key Helper Classes

### 6.1 WorkflowManager
**Location**: `src/pflow/core/workflow_manager.py`

**Key Methods**:
- `save(name, workflow_ir, description, metadata)` → Path
- `load(name)` → dict (full metadata)
- `load_ir(name)` → dict (just IR)
- `list_all()` → list[dict]
- `exists(name)` → bool
- `delete(name)` → None
- `update_ir(name, new_ir)` → None

---

### 6.2 MCPServerManager
**Location**: `src/pflow/mcp/manager.py`

**Key Methods**:
- `get_all_servers()` → dict
- `get_server(name)` → Optional[dict]
- `list_servers()` → list[str]
- `add_servers_from_file(path)` → list[str]
- `remove_server(name)` → bool

---

### 6.3 Registry
**Location**: `src/pflow/registry/registry.py`

**Key Methods**:
- `load(include_filtered=False)` → dict
- `search(query)` → list[tuple[str, dict, int]]
- `get_metadata(key, default)` → Any
- `set_metadata(key, value)` → None

---

### 6.4 MCPRegistrar
**Location**: Implied from `src/pflow/cli/mcp.py` usage

**Key Methods**:
- `list_registered_tools(server=None)` → list[str]
- `get_tool_info(tool_name)` → Optional[dict]
- `sync_server(name)` → dict
- `sync_all_servers()` → list[dict]

**Tool Info Structure**:
```python
{
    "node_name": "mcp-github-create-issue",
    "server": "github",
    "tool": "create_issue",
    "description": "Create GitHub issue",
    "params": [{"key": "title", "type": "string", ...}],
    "outputs": [{"key": "issue_url", "type": "string", ...}]
}
```

---

## 7. Implementation Recommendations

### 7.1 High Priority (Implement First)
1. ✅ `pflow_execute` - Execute workflows
2. ✅ `pflow_list_workflows` - Discover saved workflows
3. ✅ `pflow_describe_workflow` - Workflow metadata
4. ✅ `pflow_list_nodes` - Available nodes
5. ✅ `pflow_describe_node` - Node interfaces
6. ✅ `pflow_search_nodes` - Find nodes

### 7.2 Medium Priority
7. ✅ `pflow_list_mcp_servers` - Server status
8. ✅ `pflow_list_mcp_tools` - MCP tools
9. ✅ `pflow_get_mcp_tool_info` - Tool details
10. ✅ `pflow_sync_mcp_server` - Refresh catalog
11. ✅ `pflow_get_settings` - Config status
12. ✅ `pflow_check_node_visibility` - Filtering

### 7.3 Exclude
- ❌ Destructive: delete, remove, reset
- ❌ File system: add, scan, init
- ❌ Config modification: allow, deny

---

## 8. Implementation Pattern

### Thin Wrapper Approach
```python
async def pflow_list_workflows(arguments: dict) -> list[dict]:
    """MCP tool: List all saved workflows"""
    wm = WorkflowManager()
    workflows = wm.list_all()
    return workflows
```

**Benefits**:
- No duplication
- Consistent with CLI
- Easy maintenance
- Reuse existing tests

---

## 9. Critical Implementation Notes

### 9.1 Output Format
**CLI**: Uses `click.echo()`, colored text
**MCP**: Needs pure data structures

**Solution**: Extract data before formatting (many commands already have `--json` mode)

### 9.2 Interactive Mode
**MCP Should**:
- Always non-interactive
- Never prompt
- Return structured errors

### 9.3 Error Handling
```python
try:
    result = execute_workflow(...)
    return {"success": True, "data": result}
except WorkflowNotFoundError as e:
    raise McpError(f"Workflow not found: {e}")
```

---

## Summary

**Commands Analyzed**: 24
**Recommended for MCP**: 18 tools
**Code Reuse**: ~95%
**Implementation**: Thin wrappers

**Key Findings**:
1. All functionality already exists
2. Many have JSON output mode
3. Functions well-factored
4. Consistent error handling
5. No architectural changes needed

**Next Steps**:
1. Create MCP tool wrappers
2. Implement high-priority tools
3. Add integration tests
4. Document usage
