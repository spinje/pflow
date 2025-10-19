# Type Handling Bug Investigation - Critical Findings

## Bug Summary

**Problem**: When an LLM node returns JSON (auto-parsed to dict) and a template like `${llm.response}` passes the entire dict to a parameter expecting a string, the literal template variable appears in the output instead of a proper error.

**Root Cause**: Template resolution error handling has a critical gap that allows unresolved templates to pass through silently.

---

## 1. JSON Auto-Parsing Location

### LLM Node: `src/pflow/nodes/llm/llm.py`

**Lines 60-91**: `parse_json_response()` method
```python
@staticmethod
def parse_json_response(response: str) -> Union[Any, str]:
    """Parse JSON from LLM response if possible."""
    if not isinstance(response, str):
        return response

    trimmed = response.strip()

    # Extract from markdown code blocks if present
    if "```" in trimmed:
        start = trimmed.find("```json") + 7 if "```json" in trimmed else trimmed.find("```") + 3
        end = trimmed.find("```", start)
        if end > start:
            trimmed = trimmed[start:end].strip()

    # Try to parse as JSON
    try:
        return json.loads(trimmed)
    except (json.JSONDecodeError, ValueError):
        # Not valid JSON, return original string
        return response
```

**Lines 189-195**: Parsing happens in `post()` method
```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    raw_response = exec_res["response"]

    # Parse JSON if possible
    parsed_response = self.parse_json_response(raw_response)

    # Store the parsed response
    shared["response"] = parsed_response  # ← DICT STORED HERE
```

**Result**: `shared["response"]` contains a Python dict, not a JSON string.

---

## 2. Template Resolution Flow

### Step 1: Template Detected in Parameter

**File**: `src/pflow/runtime/node_wrapper.py`
**Lines 42-66**: `set_params()` categorizes templates

```python
def set_params(self, params: dict[str, Any]) -> None:
    for key, value in params.items():
        if TemplateResolver.has_templates(value):
            self.template_params[key] = value  # ← Stored for later resolution
        else:
            self.static_params[key] = value
```

### Step 2: Template Resolution at Runtime

**File**: `src/pflow/runtime/node_wrapper.py`
**Lines 101-135**: `_resolve_simple_template()` method

```python
def _resolve_simple_template(self, template: str, context: dict[str, Any]) -> tuple[Any, bool]:
    simple_var_match = re.match(r"^\$\{([^}]+)\}$", template)
    if not simple_var_match:
        return None, False

    var_name = simple_var_match.group(1)

    # Check if variable exists (even if its value is None)
    if TemplateResolver.variable_exists(var_name, context):
        # Variable exists - resolve and preserve its type (including None)
        resolved_value = TemplateResolver.resolve_value(var_name, context)
        # ↓ THIS IS WHERE DICT IS RETURNED ↓
        return resolved_value, True  # ← Returns dict if value is dict
    else:
        # Variable doesn't exist - keep template as-is for debugging
        return template, True  # ← Returns literal "${llm.response}"
```

**Lines 171-230**: `_run()` executes with resolved templates

```python
def _run(self, shared: dict[str, Any]) -> Any:
    # Build resolution context
    context = self._build_resolution_context(shared)

    # Resolve all template parameters
    resolved_params = {}
    for key, template in self.template_params.items():
        resolved_value, is_simple_template = self._resolve_template_parameter(key, template, context)
        resolved_params[key] = resolved_value

        # ↓ ERROR DETECTION IS HERE ↓
        if not is_simple_template:
            if resolved_value != template:
                # Success - template changed
                pass
            elif "${" in str(template):
                error_msg = f"Template in param '{key}' could not be fully resolved: '{template}'"
                logger.error(error_msg)
                raise ValueError(error_msg)  # ← SHOULD TRIGGER HERE

    # Temporarily update inner node params with resolved values
    merged_params = {**self.static_params, **resolved_params}
    self.inner_node.params = merged_params

    # Execute with resolved params
    result = self.inner_node._run(shared)  # ← DICT PASSED TO MCP NODE
    return result
```

**CRITICAL GAP**: The error check on lines 209-216 only triggers for **complex templates** (`is_simple_template == False`). For simple templates like `${llm.response}`, `is_simple_template == True`, so the error check is **skipped entirely**.

---

## 3. MCP Parameter Validation

### MCP Node: `src/pflow/nodes/mcp/node.py`

**Lines 75-163**: `prep()` method extracts parameters

```python
def prep(self, shared: dict) -> dict:
    # Extract user parameters (exclude special __ parameters)
    tool_args = {k: v for k, v in self.params.items() if not k.startswith("__")}

    return {
        "server": server,
        "tool": tool,
        "config": config,
        "arguments": tool_args,  # ← DICT PASSED HERE
        "verbose": verbose
    }
```

**Lines 165-183**: `exec()` calls MCP tool

```python
def exec(self, prep_res: dict) -> dict:
    # Run async code in sync context using asyncio.run()
    result = asyncio.run(self._exec_async(prep_res), debug=False)
    return result
```

**Lines 205-264**: `_exec_async_stdio()` executes MCP tool

```python
async def _exec_async_stdio(self, prep_res: dict) -> dict:
    async with stdio_client(params, errlog=errlog) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        # Call the tool with arguments
        result = await session.call_tool(prep_res["tool"], prep_res["arguments"])
        # ↓ MCP SDK VALIDATES PARAMETERS HERE ↓
        # If markdown_text parameter expects string but gets dict:
        # Pydantic ValidationError: Input should be a valid string [type=string_type, input_value={'message': 'hello'}, input_type=dict]
```

**Where validation happens**: Inside the MCP SDK's `session.call_tool()` method, which uses Pydantic to validate parameters against the tool's schema.

**What happens on validation error**:
- MCP SDK raises an exception
- Exception bubbles up through `exec()` → PocketFlow retry → `exec_fallback()` → `post()`
- Node returns `"error"` action
- **BUT**: The error message contains the dict representation, not the original template

---

## 4. Error Cascade Analysis

### Error Path Flow

```
1. Template resolution:
   TemplateAwareNodeWrapper._run()
   ├─ Resolves ${llm.response} → dict {'message': 'hello'}
   ├─ is_simple_template == True
   └─ NO ERROR CHECK (gap)

2. Parameter passing:
   MCPNode.prep()
   └─ Receives params with dict value for markdown_text

3. MCP execution:
   MCPNode.exec() → _exec_async_stdio()
   └─ session.call_tool(tool, arguments) raises ValidationError
      "Input should be a valid string [type=string_type, input_value={'message': 'hello'}, input_type=dict]"

4. Exception handling:
   PocketFlow retry mechanism
   └─ Calls exec_fallback() after retries

5. Error propagation:
   MCPNode.exec_fallback()
   └─ Returns {"error": "MCP tool failed: ...", "exception_type": "..."}

6. Final result:
   MCPNode.post()
   └─ Returns "error" action
```

### Why Literal Template Appears

The validation error message shows:
```
Input should be a valid string [type=string_type, input_value={'message': 'hello'}, input_type=dict]
```

This suggests the **dict was passed to Slack**, not the literal template string `${llm.response}`.

**Hypothesis**: The user is seeing the literal template in Slack output because:

1. **Error occurred during repair**: The repair system tried to fix the workflow but failed
2. **Template remained unresolved**: During repair, the template couldn't be resolved (maybe `llm.response` wasn't available)
3. **Literal template got passed**: The unresolved `${llm.response}` string was passed to Slack
4. **Slack displayed it**: Slack received the literal string and displayed it

This would happen if:
- First execution: Template resolves to dict → validation error
- Repair attempt: Template can't resolve (missing context) → literal string passed
- Slack receives: The literal string `${llm.response}`

---

## 5. Root Cause: Error Handling Gap

### The Critical Code Section

**File**: `src/pflow/runtime/node_wrapper.py`
**Lines 196-230**

```python
# Resolve all template parameters
resolved_params = {}
for key, template in self.template_params.items():
    resolved_value, is_simple_template = self._resolve_template_parameter(key, template, context)
    resolved_params[key] = resolved_value

    # ↓↓↓ ERROR CHECK ONLY FOR COMPLEX TEMPLATES ↓↓↓
    if not is_simple_template:  # ← BUG: Skips simple templates
        if resolved_value != template:
            logger.debug(...)
        elif "${" in str(template):
            error_msg = f"Template in param '{key}' could not be fully resolved: '{template}'"
            logger.error(error_msg)
            raise ValueError(error_msg)  # ← NEVER REACHES HERE FOR SIMPLE TEMPLATES
```

**Problem**: The error detection only runs for complex templates (`is_simple_template == False`). For simple templates like `${llm.response}`, the code:

1. Returns the dict value (preserving type)
2. Sets `is_simple_template = True`
3. **Skips the error check entirely**
4. Passes the dict to the MCP node without validation

---

## 6. Type Mismatch Detection

### Current Behavior

**No type checking happens** between template resolution and parameter usage. The flow is:

```python
# Template resolution (node_wrapper.py)
resolved_value = TemplateResolver.resolve_value(var_name, context)
# ↓ Could be: dict, list, str, int, bool, None, etc.

# Parameter assignment (node_wrapper.py)
self.inner_node.params = merged_params
# ↓ Dict value assigned to parameter

# Parameter usage (mcp/node.py)
tool_args = {k: v for k, v in self.params.items() if not k.startswith("__")}
# ↓ Dict value passed to MCP tool

# MCP validation (MCP SDK)
# ↓ Pydantic raises ValidationError
```

**Missing**: Type validation during template resolution against expected parameter types.

---

## 7. Key Questions Answered

### Q1: Where does JSON auto-parsing happen?

**A**: In `LLMNode.post()` method (`src/pflow/nodes/llm/llm.py:189-195`) via the `parse_json_response()` static method.

### Q2: Where does MCP parameter validation happen?

**A**: Inside the MCP SDK's `session.call_tool()` method (`src/pflow/nodes/mcp/node.py:249`), which uses Pydantic to validate parameters against the tool's input schema.

### Q3: Why does validation error cause literal template to appear?

**A**: The literal template appears during **repair attempts** when:
1. First execution: Template resolves to dict → validation error
2. Repair system: Tries to fix workflow
3. Second execution: Template can't resolve (context missing) → literal string `${llm.response}` passed
4. Literal string sent to Slack and displayed

### Q4: Is there error handling that swallows validation errors?

**A**: Yes, two levels:
1. **PocketFlow retry mechanism**: Catches exceptions, retries, calls `exec_fallback()`
2. **Template wrapper error check gap**: Only checks complex templates, not simple ones

### Q5: Should pflow detect type mismatch earlier?

**A**: **YES**. The bug is that template resolution:
- Preserves types for simple templates (`${var}` → dict/int/bool/etc.)
- Has NO type checking against parameter schemas
- Only detects unresolved templates for **complex** templates
- Allows type mismatches to reach runtime validation

---

## 8. Proposed Fixes

### Fix 1: Add Type Validation During Template Resolution

**Location**: `src/pflow/runtime/node_wrapper.py`

```python
def _run(self, shared: dict[str, Any]) -> Any:
    # ... existing code ...

    for key, template in self.template_params.items():
        resolved_value, is_simple_template = self._resolve_template_parameter(key, template, context)
        resolved_params[key] = resolved_value

        # ↓ ADD TYPE VALIDATION HERE ↓
        if is_simple_template and resolved_value != template:
            # Simple template was resolved - check if type mismatch might occur
            if isinstance(resolved_value, (dict, list)):
                logger.warning(
                    f"Template '{template}' resolved to {type(resolved_value).__name__} for param '{key}'. "
                    f"If this parameter expects a string, you may need to access a nested field like '{template}.field' "
                    f"or serialize it with JSON like '{{\"data\": {template}}}'."
                )
```

### Fix 2: Detect Unresolved Templates for Simple Templates Too

**Location**: `src/pflow/runtime/node_wrapper.py`

```python
for key, template in self.template_params.items():
    resolved_value, is_simple_template = self._resolve_template_parameter(key, template, context)
    resolved_params[key] = resolved_value

    # ↓ EXPAND ERROR CHECK TO INCLUDE SIMPLE TEMPLATES ↓
    # Check if template wasn't resolved (value unchanged)
    if resolved_value == template and "${" in str(template):
        error_msg = f"Template in param '{key}' could not be fully resolved: '{template}'"
        logger.error(error_msg)
        raise ValueError(error_msg)
```

### Fix 3: Use Template Validator for Pre-Execution Type Checking

**Location**: Enhance `src/pflow/runtime/template_validator.py` to:
1. Check if template resolves to expected type
2. Warn about dict → string conversions
3. Suggest correct template paths (e.g., `${llm.response.message}` instead of `${llm.response}`)

---

## 9. Test Case for Bug

```python
def test_dict_to_string_parameter_error():
    """Test that passing dict to string parameter raises clear error."""
    from pflow.nodes.llm.llm import LLMNode
    from pflow.nodes.mcp.node import MCPNode

    # LLM returns JSON
    llm = LLMNode()
    shared = {"prompt": "Return JSON: {\"message\": \"hello\"}"}
    llm.run(shared)

    # shared["response"] is now a dict
    assert isinstance(shared["response"], dict)

    # Try to use it in a string parameter
    mcp = MCPNode()
    mcp.params = {
        "__mcp_server__": "slack",
        "__mcp_tool__": "post-message",
        "markdown_text": "${response}"  # Template resolves to dict
    }

    # Should raise clear error BEFORE reaching MCP validation
    with pytest.raises(ValueError) as exc_info:
        mcp.run(shared)

    assert "type mismatch" in str(exc_info.value).lower()
    assert "expects string" in str(exc_info.value).lower()
    assert "resolved to dict" in str(exc_info.value).lower()
```

---

## 10. Recommendations

### Immediate Fix (High Priority)

**Expand error detection to simple templates** in `node_wrapper.py`:
- Lines 209-216: Remove `if not is_simple_template` condition
- Check unresolved templates for ALL template types
- This prevents literal templates from being passed through

### Medium-Term Fix

**Add type validation during template resolution**:
- Detect when dict/list resolves for parameters likely expecting strings
- Provide helpful suggestions (e.g., "Use ${llm.response.message} instead")
- This catches type mismatches early with actionable guidance

### Long-Term Fix

**Enhance template validator with schema-aware type checking**:
- Use node interface metadata to validate resolved types
- Detect dict → string conversions automatically
- Suggest correct template paths based on available fields

---

## Summary

The bug occurs because:
1. LLM auto-parses JSON → dict stored in shared store
2. Template `${llm.response}` resolves to dict (type preservation)
3. Error detection only checks **complex** templates, not simple ones
4. Dict passes through to MCP validation where Pydantic rejects it
5. During repair, template can't resolve → literal string appears in Slack

**Fix**: Expand error detection to ALL templates and add type validation warnings.
