# Template Resolution Fix for registry_run

## Problem
Agents couldn't securely test nodes that require API keys. Passing actual tokens would expose secrets to the LLM, but using `${VAR}` templates didn't work because `registry_run` doesn't have the workflow runtime's template resolver.

## Solution
Added environment variable resolution to `registry_run` so agents can use `${VAR}` syntax without exposing actual tokens.

## Implementation

**File**: `src/pflow/mcp_server/services/execution_service.py` (lines 592-604)

```python
# Resolve ${var} templates from environment variables
# This allows agents to use ${API_KEY} without exposing actual tokens
# Same pattern as MCP nodes use for auth config expansion
if parameters:
    from pflow.mcp.auth_utils import expand_env_vars_nested

    # Expand environment variables in parameters (recursively handles nested dicts/lists)
    parameters = expand_env_vars_nested(parameters)
```

## How It Works

1. **Agent sends**: `{"auth_token": "${REPLICATE_API_TOKEN}"}`
2. **Server resolves**: Looks up `REPLICATE_API_TOKEN` from environment
3. **Node executes**: With real token value
4. **Agent receives**: Output structure (not the token) ✅ Secure!

## Key Features

### Recursive Resolution
Works in nested structures:
```json
{
  "headers": {
    "Authorization": "Bearer ${API_KEY}"
  },
  "body": {
    "secrets": ["${KEY1}", "${KEY2}"]
  }
}
```

### Security
- Agent never sees actual token values
- Only resolved at server-side
- Same pattern MCP nodes use for auth

### Requirement
Environment variables must be set via:
- `pflow settings set-env KEY=value`, or
- Shell export: `export API_KEY=value`

## Testing

**Unit tests** (`tests/test_mcp_server/test_registry_run_mcp.py`):
- ✅ Simple template resolution
- ✅ Nested structure resolution
- ✅ No impact on non-template parameters

**Manual test** (requires API key in environment):
```python
# Set your API key first:
# pflow settings set-env REPLICATE_API_TOKEN=r8_your_token

# Then test via MCP:
await mcp__pflow__registry_run(
    node_type="http",
    parameters={
        "url": "https://api.replicate.com/v1/models",
        "method": "GET",
        "auth_token": "${REPLICATE_API_TOKEN}"
    }
)
```

## Benefits

1. **Security**: Agents can test auth-requiring nodes without seeing tokens
2. **Consistency**: Same `${VAR}` syntax as workflows use
3. **Simple**: Reuses existing `expand_env_vars_nested()` function (13 lines of code)
4. **Backward compatible**: Non-template parameters work as before

## Files Modified

1. **Implementation**:
   - `src/pflow/mcp_server/services/execution_service.py` (+13 lines)

2. **Tests**:
   - `tests/test_mcp_server/test_registry_run_mcp.py` (+76 lines, 2 new tests)

## Impact

- **Before**: Agents couldn't test auth-requiring nodes securely
- **After**: Agents can use `${VAR}` templates, resolved from environment
- **Breaking changes**: None
- **Performance**: Negligible (only resolves when `${...}` present)
