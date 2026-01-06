# Bug Report: JSON Auto-Parsing Breaks MCP Tools Expecting JSON String Parameters

## Summary

When an MCP tool declares a parameter type as `str` but expects a JSON-formatted string (e.g., `'{"key": "value"}'`), pflow incorrectly parses the JSON into a Python dict before passing it to the MCP tool. This causes the MCP tool to fail with a type error.

## Severity

**Medium-High** - Affects usability of MCP tools with JSON-string parameters. Currently requires a hacky workaround (leading space in CLI, escaped strings in workflows).

## Affected Components

1. **CLI `registry run` command** - Auto-parses JSON strings into dicts
2. **Workflow JSON execution** - JSON objects in workflow files become dicts

## Root Cause

pflow's type inference and JSON parsing doesn't consider the **target parameter type** declared in the MCP tool schema. It eagerly parses anything that looks like JSON into Python objects, even when the MCP tool expects a string containing JSON.

---

## Steps to Reproduce

### Prerequisites

1. Have the Discord MCP server configured (see `discord-mcp-setup.md` in this folder)
2. Discord MCP uses the generic `execute_action` pattern with JSON-string parameters

### Reproduction Case 1: CLI `registry run`

```bash
# This FAILS - pflow parses the JSON into a dict
uv run pflow registry run mcp-discord-execute_action \
  server_name=discord \
  category_name=DISCORD_CHANNELS_MESSAGES \
  action_name=create_message \
  path_params='{"channel_id":"1458059302022549698"}' \
  body_schema='{"content":"test message"}'
```

**Error:**
```
Error: the JSON object must be str, bytes or bytearray, not dict
```

**Workaround (hacky):**
```bash
# Adding a leading space prevents JSON parsing
uv run pflow registry run mcp-discord-execute_action \
  server_name=discord \
  category_name=DISCORD_CHANNELS_MESSAGES \
  action_name=create_message \
  'path_params= {"channel_id":"1458059302022549698"}' \
  'body_schema= {"content":"test message"}'
```

### Reproduction Case 2: Workflow JSON File

See `test-workflow-fails.json` in this folder.

```bash
# This FAILS
uv run pflow scratchpads/bug-json-string-params/test-workflow-fails.json \
  channel_id="1458059302022549698" \
  message="test from workflow"
```

**Error:**
```
Error: the JSON object must be str, bytes or bytearray, not dict
```

**Workaround:** Use escaped JSON string in workflow (see `test-workflow-works.json`):
```json
"path_params": "{\"channel_id\": \"${channel_id}\"}"
```

---

## Technical Analysis

### Where the Problem Occurs

#### 1. CLI Parameter Parsing

**File:** `src/pflow/cli/main.py`
**Function:** `infer_type()` (line ~2193)

```python
def infer_type(value: str) -> Any:
    # ...
    # JSON detection for arrays and objects
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)  # <-- PROBLEM: Always parses JSON
        except json.JSONDecodeError:
            pass
    return value
```

This function doesn't know the target parameter type. It eagerly parses anything that looks like JSON.

#### 2. Workflow JSON Parsing

When a workflow JSON file contains:
```json
"path_params": {"channel_id": "${channel_id}"}
```

Python's `json.load()` naturally creates a dict. This is correct JSON semantics, but the MCP tool expects a string.

### MCP Tool Schema Shows Type is `str`

The Discord MCP `execute_action` tool declares:
```
path_params: str  - JSON string containing path parameters
body_schema: str  - JSON string containing request body
```

This is confirmed in the registry:
```bash
uv run python -c "
from pflow.registry import Registry
r = Registry()
nodes = r.load()
node = nodes.get('mcp-discord-execute_action')
for p in node['interface']['params']:
    print(f\"{p['key']}: {p['type']}\")"
```

Output:
```
server_name: str
category_name: str
action_name: str
path_params: str      <-- Type is str, but expects JSON inside
query_params: str     <-- Same
body_schema: str      <-- Same
include_output_fields: list
maximum_output_characters: int
```

### Data Flow

```
User Input                     What MCP Tool Receives
-----------                    ----------------------
CLI: path_params='{"a":"b"}'   → dict {"a": "b"}      ❌ WRONG
Workflow: {"a":"b"}            → dict {"a": "b"}      ❌ WRONG
CLI: path_params=' {"a":"b"}'  → str ' {"a":"b"}'     ✓ (hacky)
Workflow: "{\"a\":\"b\"}"      → str '{"a":"b"}'      ✓ (awkward)
```

---

## Recommended Fix

### Approach: Type-Aware Coercion

When passing parameters to a node, check the **declared parameter type** from the registry. If the type is `str` but the value is a `dict` or `list`, serialize it to a JSON string.

### Fix Location 1: CLI `registry run`

**File:** `src/pflow/cli/registry_run.py`
**Function:** `_prepare_node_execution()` or new helper

```python
def _coerce_params_to_schema(params: dict, registry: Registry, node_id: str) -> dict:
    """Coerce parameter types based on node schema.

    If a parameter is declared as 'str' but the value is dict/list,
    serialize it to a JSON string.
    """
    node_info = registry.load().get(node_id, {})
    param_schemas = node_info.get('interface', {}).get('params', [])
    param_types = {p['key']: p['type'] for p in param_schemas}

    coerced = {}
    for key, value in params.items():
        expected_type = param_types.get(key)
        if expected_type == 'str' and isinstance(value, (dict, list)):
            coerced[key] = json.dumps(value)
        else:
            coerced[key] = value
    return coerced
```

### Fix Location 2: Workflow Execution

**Potential locations:**
- `src/pflow/runtime/template_resolver.py` - During template resolution
- `src/pflow/runtime/compiler.py` - During node compilation

The same logic applies: check if param type is `str` and value is dict/list, then serialize.

### Alternative Approach: Fix in MCPNode

Could also fix in `src/pflow/nodes/mcp/node.py` in the `prep()` method, but this is less ideal because:
1. MCPNode doesn't have easy access to the tool's input schema
2. The fix should be general (affect all nodes, not just MCP)

---

## Verification Checklist for Implementer

Before implementing, please verify:

1. [ ] Reproduce the bug using the test files in this folder
2. [ ] Confirm the registry has correct type information for the Discord MCP
3. [ ] Check if other MCP tools have similar JSON-string parameters
4. [ ] Verify the fix doesn't break normal string parameters
5. [ ] Verify the fix doesn't break actual JSON object parameters (where type IS dict/list)
6. [ ] Consider edge cases: nested templates, null values, empty objects

## Test Cases to Add

See `test-cases.md` in this folder for specific test scenarios.

## Files in This Folder

- `BUG-REPORT.md` - This file
- `test-workflow-fails.json` - Workflow that demonstrates the bug
- `test-workflow-works.json` - Workflow with workaround (for comparison)
- `test-cases.md` - Test cases for the fix
- `discord-mcp-setup.md` - How to set up Discord MCP for testing
- `code-locations.md` - Relevant code locations with line numbers

---

## Questions for Implementer

1. Should we emit a warning when auto-coercing? (Probably not - it should "just work")
2. Should the fix apply to ALL nodes or just MCP nodes? (Recommend: all nodes for consistency)
3. Are there any parameter types besides `str` that might need similar handling?
4. Should we add a way to opt-out of auto-coercion? (Probably not needed)

Please do your own investigation and assessment. The root cause analysis above is based on debugging, but verify it yourself before implementing.
