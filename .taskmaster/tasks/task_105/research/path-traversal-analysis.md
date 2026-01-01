# Template Resolver Path Traversal Analysis

## Current Behavior

### Location
File: `src/pflow/runtime/template_resolver.py`

### Key Functions

#### 1. `resolve_value()` - Main Path Traversal (Lines 224-292)

**Purpose**: Resolve variable names with dot-notation paths from context dictionary.

**Current Logic Flow**:
```python
def resolve_value(var_name: str, context: dict[str, Any]) -> Optional[Any]:
    if "." in var_name or "[" in var_name:
        # Path traversal mode
        parts = re.split(r"\.(?![^\[]*\])", var_name)  # Split on dots (not inside brackets)
        value = context

        for part in parts:
            # Handle array indices: name[0] or name[0][1]
            array_match = re.match(r"^([^[]+)((?:\[\d+\])+)$", part)

            if array_match:
                # Array access (lines 252-278)
                base_name = array_match.group(1)
                if isinstance(value, dict) and base_name in value:
                    value = value[base_name]
                    # Then apply indices...
                else:
                    return None  # ❌ FAILS HERE
            else:
                # Regular property access (lines 280-288)
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    logger.debug(f"Cannot resolve path: '{part}' not found or parent not a dict")
                    return None  # ❌ FAILS HERE

        return value
    else:
        # Simple variable lookup
        return context.get(var_name)
```

**Critical Check (Line 281)**:
```python
if isinstance(value, dict) and part in value:
    value = value[part]
else:
    return None  # ❌ Path traversal STOPS if parent is not a dict
```

#### 2. `_traverse_path_part()` - Helper for Validation (Lines 147-193)

Similar logic used by `variable_exists()` for validation:

```python
def _traverse_path_part(current: Any, part: str, part_index: int, total_parts: int):
    # ... array handling ...
    else:
        # Regular property access (lines 179-193)
        if not isinstance(current, dict):
            return False, current  # ❌ STOPS if not a dict

        if part not in current:
            return False, current

        # Continue traversal or just check existence
        return True, current
```

## The Problem

### Example Scenario
```python
context = {
    "node": {
        "stdout": '{"status": "success", "data": {"count": 42}}'  # ← String, not dict!
    }
}

# Template: ${node.stdout.status}
var_name = "node.stdout.status"
```

**What Happens**:
1. Split path: `["node", "stdout", "status"]`
2. First iteration: `value = context["node"]` → `{"stdout": "..."}`  ✅
3. Second iteration: `value = value["stdout"]` → `'{"status": ...}'`  ✅
4. Third iteration: **FAILS** at line 281
   - `isinstance(value, dict)` → `False` (it's a string)
   - Returns `None` immediately
   - Never attempts to parse the JSON string

### Error Raised
- **Function**: `resolve_value()` returns `None`
- **Caller**: `resolve_template()` sees `None` and leaves template unresolved
- **Result**: Template remains as `${node.stdout.status}` in output
- **No exception**: Just silent failure (logged at debug level)

## Where the Change Would Go

### Option 1: Modify `resolve_value()` - Lines 280-288

**Current Code**:
```python
else:
    # Regular property access
    if isinstance(value, dict) and part in value:
        value = value[part]
    else:
        logger.debug(
            f"Cannot resolve path '{var_name}': '{part}' not found or parent not a dict",
            extra={"var_name": var_name, "failed_at": part},
        )
        return None
```

**Proposed Change**:
```python
else:
    # Regular property access
    if isinstance(value, dict) and part in value:
        value = value[part]
    elif isinstance(value, str):
        # 🆕 Attempt to parse as JSON if parent is a string
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict) and part in parsed:
                value = parsed[part]
            else:
                logger.debug(f"Cannot resolve path: '{part}' not in parsed JSON")
                return None
        except (json.JSONDecodeError, TypeError):
            logger.debug(f"Cannot resolve path: '{part}' - parent is string but not valid JSON")
            return None
    else:
        logger.debug(
            f"Cannot resolve path '{var_name}': '{part}' not found or parent not a dict",
            extra={"var_name": var_name, "failed_at": part},
        )
        return None
```

### Option 2: Modify `_traverse_path_part()` - Lines 179-193

Similar change needed for validation consistency:

```python
else:
    # Regular property access
    if not isinstance(current, dict):
        # 🆕 Try parsing string as JSON
        if isinstance(current, str):
            try:
                parsed = json.loads(current)
                if isinstance(parsed, dict) and part in parsed:
                    if part_index < total_parts - 1:
                        current = parsed[part]
                        if current is None:
                            return False, current
                    return True, current
            except (json.JSONDecodeError, TypeError):
                pass
        return False, current  # ❌ Original failure

    # Rest of logic...
```

## Key Observations

### 1. JSON Module Already Imported
Line 8: `import json`

Currently only used in `_convert_to_string()` (line 331) for serialization:
```python
return json.dumps(value, ensure_ascii=False)
```

### 2. No Existing Parse Logic
- `json.loads()` is NOT currently used anywhere
- All JSON parsing would be NEW functionality
- No risk of conflicting with existing parse behavior

### 3. Error Handling Strategy
Current pattern (lines 261-265, 274-278, 284-288):
```python
logger.debug(
    f"Cannot resolve path '{var_name}': {reason}",
    extra={"var_name": var_name, "failed_at": part}
)
return None
```

**Implication**:
- Failures are logged at DEBUG level (not visible by default)
- Return `None` to signal "couldn't resolve"
- Caller (`resolve_template()`) handles this gracefully by leaving template unresolved

### 4. Type Preservation Context
From `resolve_template()` (lines 366-382):
- Simple templates (`${var}`) preserve original type
- Complex templates (`"text ${var}"`) stringify everything

**After JSON parse**:
```python
# If we parse '{"status": "success"}' and access .status
# We get: "success" (string)
# This is CORRECT - the parsed value's type is preserved
```

### 5. Two Places Need Changes
Both validation and resolution use path traversal:
1. **Validation**: `_traverse_path_part()` (called by `variable_exists()`)
2. **Resolution**: `resolve_value()` (called by `resolve_template()`)

**Must keep them in sync** or validation will fail while resolution succeeds (or vice versa).

## Logic Flow After Change

### Example: `${node.stdout.status}`

**Input**:
```python
context = {
    "node": {
        "stdout": '{"status": "success", "data": {"count": 42}}'
    }
}
```

**Execution**:
1. Split: `["node", "stdout", "status"]`
2. Iteration 1: `value = {"stdout": "..."}`  ✅
3. Iteration 2: `value = '{"status": ...}'`  ✅
4. Iteration 3: **NEW BEHAVIOR**
   - Check: `isinstance(value, dict)` → `False`
   - Check: `isinstance(value, str)` → `True` 🆕
   - Parse: `parsed = json.loads(value)` → `{"status": "success", "data": {...}}`
   - Check: `"status" in parsed` → `True`
   - Extract: `value = parsed["status"]` → `"success"`
5. Return: `"success"` ✅

### Example: `${node.stdout.data.count}`

**Same context, deeper path**:
1. Split: `["node", "stdout", "data", "count"]`
2. Iteration 1: `value = {"stdout": "..."}`  ✅
3. Iteration 2: `value = '{"status": ...}'`  ✅
4. Iteration 3: **Parse JSON** 🆕
   - `value = parsed["data"]` → `{"count": 42}`
5. Iteration 4: **Regular dict access**
   - `value = value["count"]` → `42`
6. Return: `42` (int) ✅

## Edge Cases to Handle

### 1. Invalid JSON String
```python
context = {"node": {"stdout": "not valid json"}}
# Template: ${node.stdout.status}
```
**Behavior**:
- `json.loads()` raises `JSONDecodeError`
- Catch and return `None` (same as current behavior)
- Template remains unresolved: `${node.stdout.status}`

### 2. JSON Array Instead of Object
```python
context = {"node": {"stdout": '[1, 2, 3]'}}
# Template: ${node.stdout.status}
```
**Behavior**:
- Parse succeeds → `[1, 2, 3]`
- Check: `isinstance(parsed, dict)` → `False`
- Return `None` (can't access `.status` on array)

### 3. Nested JSON Strings (Edge Edge Case)
```python
context = {
    "node": {
        "stdout": '{"inner": "{\\"deep\\": \\"value\\"}"}'
    }
}
# Template: ${node.stdout.inner.deep}
```
**Behavior**:
- Parse outer: `{"inner": "{\"deep\": \"value\"}"}`
- Access `.inner`: `"{\"deep\": \"value\"}"` (still a string)
- Next iteration would parse again 🆕
- This creates **recursive parsing**

**Question**: Should we parse recursively or just once per path segment?

### 4. JSON String at End of Path
```python
context = {"data": '{"status": "ok"}'}
# Template: ${data}  (simple template)
```
**Behavior**:
- No path traversal (no dots)
- Returns the string as-is: `'{"status": "ok"}'`
- **NOT parsed** (only triggered during traversal)

**Question**: Should simple templates also auto-parse JSON strings?

## Performance Considerations

### Parse Frequency
- Only triggered when traversing through a string value
- Only if that string looks like it should have properties (has remaining path parts)
- Parse happens **per path segment** that's a string

### Caching Opportunity
Current code doesn't cache parsed values. Each template resolution re-parses:
```python
# If 3 templates use node.stdout.X, node.stdout.Y, node.stdout.Z
# The same JSON string gets parsed 3 times
```

**Possible optimization** (not required for MVP):
- Cache parsed JSON in shared store
- Key: hash of JSON string
- Reduces redundant parsing

## Integration with Existing Features

### 1. Type Preservation (Task 103)
- Simple templates preserve type: `${var}` → keeps int/bool/dict/list
- After JSON parse, extracted values keep their types
- Example: `${node.stdout.count}` where `stdout = '{"count": 42}'` → `42` (int)

### 2. Template Validation (Task 71)
- Validator uses `_traverse_path_part()` to check variable existence
- **Must also support JSON parsing** or validation will fail
- If validation and resolution diverge, we get false negatives

### 3. Batch Processing (Task 96)
- Batch items might have JSON strings
- Template resolution happens per item
- Parse overhead multiplied by batch size

### 4. Error Reporting
- Current: "parent not a dict" debug message
- New: Could add "parent is string but not valid JSON"
- Should be DEBUG level (not user-facing errors)

## Conclusion

### Insertion Points
1. **Primary**: `resolve_value()` lines 280-288 (regular property access)
2. **Secondary**: `resolve_value()` lines 257-265 (array base access)
3. **Validation**: `_traverse_path_part()` lines 179-193

### Current Error Behavior
- Returns `None` (no exception)
- Logs at DEBUG level
- Template remains unresolved in output

### New Behavior After Change
- Attempt `json.loads()` when parent is string
- If parse succeeds and key exists, continue traversal
- If parse fails or key missing, return `None` (same as before)
- Backwards compatible (only adds new success cases)

### Open Questions
1. Should we parse recursively (JSON string inside JSON string)?
2. Should simple templates (no path) also auto-parse?
3. Should we cache parsed JSON to avoid redundant parsing?
4. Should we add specific error messages for "valid JSON but key not found"?
