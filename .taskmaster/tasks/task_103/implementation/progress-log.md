# Task 103 Implementation Progress Log

## [Session Start] - Understanding the Problem

Reading task files and handover memo...

**The Core Problem:**
```python
# Input
"stdin": {"config": "${config}", "data": "${data}"}
# Where config = {"name": "MyApp"} and data = {"value": "Hello"}

# ACTUAL output (broken):
{"config": "{\"name\": \"MyApp\"}", "data": "{\"value\": \"Hello\"}"}

# DESIRED output:
{"config": {"name": "MyApp"}, "data": {"value": "Hello"}}
```

Double-serialization bug: inner dicts are JSON-serialized to strings, then the outer dict serializes again.

---

## [Research Phase] - Parallel Subagent Investigation

Deployed 8 parallel `pflow-codebase-searcher` agents to resolve all ambiguities:

1. Template resolution flow (end-to-end)
2. `_resolve_simple_template()` pattern analysis
3. `_to_string()` and `resolve_string()` behavior
4. Shell node stdin handling
5. Nodes with structured params
6. Existing test coverage
7. Nested structure handling
8. Param type validation flow

### Key Findings:

**Root Cause Identified:**
```
resolve_nested() at template_resolver.py:381-385
    ↓
Calls resolve_string() for ALL string templates
    ↓
resolve_string() ALWAYS calls _convert_to_string()
    ↓
_convert_to_string() calls json.dumps() on dicts/lists (line 279)
    ↓
DOUBLE SERIALIZATION
```

**The Pattern Already Exists:**
- `_resolve_simple_template()` in `node_wrapper.py:525-559` correctly preserves types for TOP-LEVEL params
- Uses regex: `r"^\$\{([^}]+)\}$"` to detect simple templates
- But this logic is NOT applied inside `resolve_nested()`

**Impact Assessment:**
- 7 nodes benefit: HTTP, Shell, MCP, LLM, Claude Code, Git, GitHub
- Zero nodes will break (all have `isinstance()` checks)
- 36 test occurrences call `resolve_string` directly

---

## [Design Decision] - Choosing the Approach

### Options Considered:

1. **Minimal fix in resolve_nested()** - Just add simple template detection
2. **Create unified resolve() method** - New entry point
3. **Smart resolve_string()** - Make it detect simple templates
4. **Rename and reorganize** - `resolve_string` → `resolve_template`

### Decision: Option 4 - Rename `resolve_string` to `resolve_template`

**Rationale:**
- Method will return `Any` (not just `str`), name should reflect this
- "resolve_template" accurately describes behavior
- Fixes all callers automatically (workflow_executor, node_wrapper)
- Single source of truth for simple template detection

### Plan Change: Added shared helper methods

**Original plan:** Just modify `resolve_nested()` with inline regex

**Updated plan:** Extract to shared helpers `is_simple_template()` and `extract_simple_template_var()`

**Rationale:**
- Eliminates code duplication with `node_wrapper._resolve_simple_template()`
- Single source of truth for the regex pattern
- If pattern needs to change, only one place to update

---

## [Phase 1] - Core template_resolver.py Changes

### Step 1.1: Add SIMPLE_TEMPLATE_PATTERN

```python
# Pattern for detecting simple templates (entire string is one ${var} reference)
# Used to determine when to preserve type vs stringify
SIMPLE_TEMPLATE_PATTERN = re.compile(r"^\$\{([^}]+)\}$")
```

Result: ✅ Added after TEMPLATE_PATTERN constant

### Step 1.2: Add Helper Methods

```python
@staticmethod
def is_simple_template(value: str) -> bool:
    """Check if string is exactly one template variable reference."""
    return bool(TemplateResolver.SIMPLE_TEMPLATE_PATTERN.match(value))

@staticmethod
def extract_simple_template_var(value: str) -> Optional[str]:
    """Extract variable name from a simple template."""
    match = TemplateResolver.SIMPLE_TEMPLATE_PATTERN.match(value)
    return match.group(1) if match else None
```

Result: ✅ Added after `extract_variables()` method

### Step 1.3: Rename resolve_string → resolve_template

Key changes:
- Return type: `str` → `Any`
- Added simple template detection at start:
```python
# Check for simple template first - preserve type
var_name = TemplateResolver.extract_simple_template_var(template)
if var_name is not None:
    if TemplateResolver.variable_exists(var_name, context):
        resolved = TemplateResolver.resolve_value(var_name, context)
        return resolved  # Type preserved!
    else:
        return template  # Unresolved, keep as-is
```

- Kept existing complex template logic (string interpolation)

Result: ✅ Method renamed and enhanced

### Step 1.4: Update resolve_nested

Changed line 384:
```python
# Before:
return TemplateResolver.resolve_string(value, context)

# After:
return TemplateResolver.resolve_template(value, context)
```

Also updated docstring with type preservation example.

Result: ✅ Now calls resolve_template

### Step 1.5: Verification

Created `/tmp/test_phase1.py` with 12 test cases:

```
Test 1 - Simple template dict: {'name': 'Alice', 'age': 30}
  Type preserved: True
Test 2 - Simple template list: [1, 2, 3]
  Type preserved: True
Test 3 - Simple template int: 42
  Type preserved: True
Test 4 - Complex template: Hello Alice!
  Is string: True
Test 5 - Nested resolution: {'outer': {'nested': 'value'}}
  Inner type preserved: True
Test 6 - Unresolved: ${missing}
Test 7 - is_simple_template:
  '${var}': True
  'Hello ${var}': False
Test 8 - Path template: [{'id': 1}, {'id': 2}]
Test 9 - Original bug fix: {'config': {'name': 'MyApp'}, 'data': {'value': 'Hello'}}
Test 10 - List with templates: [{'x': 1}, [1, 2, 3]]
Test 11 - Boolean: True (type: bool)
Test 12 - None: None

All Phase 1 core tests passed!
```

💡 **Insight:** The original bug (Test 9) is now fixed - nested templates preserve type.

---

## [Phase 2] - Update Callers

### Callers identified via grep:
1. `workflow_executor.py:274`
2. `node_wrapper.py:589`

### Step 2.1: Update workflow_executor.py

```python
# Before:
resolved[child_param] = TemplateResolver.resolve_string(parent_value, context)

# After:
resolved[child_param] = TemplateResolver.resolve_template(parent_value, context)
```

Result: ✅ Updated

### Step 2.2: Update node_wrapper.py

```python
# Before:
resolved_value = TemplateResolver.resolve_string(template, context)

# After:
resolved_value = TemplateResolver.resolve_template(template, context)
```

Result: ✅ Updated

### Step 2.3: Verification

Ran full integration test with shell node:

```python
workflow_ir = {
    'inputs': {...},
    'nodes': [{
        'id': 'process',
        'type': 'shell',
        'params': {
            'stdin': {'config': '${config}', 'data': '${data}'},
            'command': 'cat'
        }
    }],
    ...
}
```

Output:
```
Shell output: {"config": {"name": "MyApp"}, "data": {"value": "Hello"}}
PASS - Original bug is FIXED!
```

💡 **Insight:** The exact scenario from the task description now works correctly.

---

## [Phase 3] - Refactor node_wrapper._resolve_simple_template

### Step 3.1: Use shared helper

```python
# Before:
import re
simple_var_match = re.match(r"^\$\{([^}]+)\}$", template)
if not simple_var_match:
    return None, False
var_name = simple_var_match.group(1)

# After:
var_name = TemplateResolver.extract_simple_template_var(template)
if var_name is None:
    return None, False
```

Result: ✅ Removed inline regex, using shared helper

### Benefits achieved:
- Removed `import re` from method
- Single source of truth for simple template pattern
- Kept node-specific logging (uses `self.node_id`)

### Step 3.2: Verification

All previous tests still pass. Added specific tests for:
- `is_simple_template()` edge cases
- `extract_simple_template_var()` with paths
- Full workflow with node_wrapper in the loop

---

## [Pre-Phase 4] - Additional Verification

### User Questions Addressed:

**Q1: Is string interpolation still preserved?**

Verified with test:
```python
context = {"name": "Alice", "data": {"key": "value"}}

# Complex templates → strings
"Hello ${name}!" → "Hello Alice!"
"Data: ${data}" → 'Data: {"key": "value"}'

# Simple templates → type preserved
"${data}" → {"key": "value"}
```

✅ Confirmed: Complex templates still do string interpolation

**Q2: Does this work for ALL nodes, not just shell?**

Verified that fix is in `TemplateResolver` which is used by `TemplateAwareNodeWrapper`, which wraps all nodes. Tested with:
- HTTP node ✅
- LLM node ✅
- Shell node ✅

### Manual CLI Workflow Tests:

Created 5 test workflows in `/tmp/pflow-test-workflows/`:

**Test 1: Inline object** - `{"config": "${config}", "data": "${items}"}`
```
Output: {"configuration": {"name": "MyApp", "debug": true}, "data": [1, 2, 3]}
✅ Types preserved
```

**Test 2: Mixed templates**
```
Output: {"greeting": "Hello Alice!", "profile": {"email": "...", "age": 30}, "message": "You have 5 notifications", "raw_count": 5}
✅ Complex→string, Simple→preserved
```

**Test 3: Deeply nested**
```
Output: {"request": {"config": {...}, "headers": [...], "metadata": {"nested_config": {...}, "description": "Config is: {...}"}}}
✅ Works at all nesting levels
```

**Test 4: Multi-node data passing**
```
Output: {"original": {"name": "test", "items": [1, 2, 3]}, "modified": "..."}
✅ Types preserved across nodes
```

**Test 5: jq combining multiple sources** (the exact task use case!)
```
stdin: {"a": "${data_a}", "b": "${data_b}"}
jq '{combined_name: (.a.name + " & " + .b.name), total: (.a.value + .b.value)}'

Output: {"combined_name": "Alice & Bob", "total": 35}
✅ Original task use case works perfectly
```

---

## [Test Analysis] - Expected Failures

Ran existing tests to identify what needs updating:

### Tests expecting OLD behavior (to be updated in Phase 4):

1. **test_template_resolver.py** - 22 calls to `resolve_string`
2. **test_template_resolver_arrays.py** - 6 calls
3. **test_template_resolver_nested.py** - 2 calls
4. **test_template_array_notation.py** - 1 call
5. **test_json_text_parsing.py** - 5 calls

### Tests documenting OLD (broken) behavior:

`test_node_wrapper_nested_resolution.py`:
```python
# OLD expectation (WRONG):
# "Template resolution converts numbers to strings when in nested structures"
assert node.exec_params["params"]["limit"] == "10"

# NEW behavior (CORRECT):
# Numbers are preserved
assert node.exec_params["params"]["limit"] == 10
```

These 2 tests fail because they were testing the bug, not correct behavior.

---

## Summary of Changes (Phases 1-3)

### Files Modified:

1. **src/pflow/runtime/template_resolver.py**
   - Added `SIMPLE_TEMPLATE_PATTERN` regex constant
   - Added `is_simple_template()` method
   - Added `extract_simple_template_var()` method
   - Renamed `resolve_string()` → `resolve_template()` with type preservation
   - Updated `resolve_nested()` to call `resolve_template()`

2. **src/pflow/runtime/workflow_executor.py**
   - Line 274: `resolve_string` → `resolve_template`

3. **src/pflow/runtime/node_wrapper.py**
   - Line 589: `resolve_string` → `resolve_template`
   - `_resolve_simple_template()`: Now uses shared helper instead of inline regex

### Behavior Change:

| Template Type | Before | After |
|--------------|--------|-------|
| Simple `${var}` at top level | Type preserved | Type preserved (unchanged) |
| Simple `${var}` in nested structure | JSON string | **Type preserved (FIXED)** |
| Complex `"Hello ${var}"` anywhere | String | String (unchanged) |

---

## [Phase 4] - Update Tests

### Tests Updated:

| File | Changes |
|------|---------|
| `test_template_resolver.py` | 22 `resolve_string` → `resolve_template` |
| `test_template_resolver_arrays.py` | 6 calls updated |
| `test_template_resolver_nested.py` | 2 calls updated |
| `test_template_array_notation.py` | 1 call updated |
| `test_json_text_parsing.py` | 5 calls updated, tests rewritten for new behavior |
| `test_node_wrapper_nested_resolution.py` | 2 assertions fixed (int/bool now preserved) |

### New Tests Added:

**`test_template_type_preservation.py`** - Core behavior tests:
- `TestInlineObjectTypePreservation` - The exact bug fix scenarios
- `TestPathTemplateTypePreservation` - Path templates preserve type
- `TestSimpleTemplateDetection` - Documents simple vs complex boundary

**`test_shell_stdin_type_preservation.py`** - Integration tests:
- Real shell node with inline objects
- jq processing with combined data sources
- Mixed types (dict, list, int, bool)

### Key Insight: Tests Confirmed the Fix

The 2 failing tests in `test_node_wrapper_nested_resolution.py` were **documenting the bug**:
```python
# Test comment: "Template resolution converts numbers to strings when in nested structures"
assert node.exec_params["params"]["limit"] == "10"  # WRONG expectation
```

These failures were CONFIRMATION that our fix works - the test was checking for broken behavior.

---

## Final Results

```
3236 passed, 9 skipped in 15.82s
```

All tests pass including:
- 99 template-related tests (updated + new)
- Full runtime test suite
- Integration tests

---

## Key Insights

### 1. The Pattern Was Already Correct (Just Misplaced)

The `_resolve_simple_template()` logic in `node_wrapper.py` was correct - it just wasn't applied to nested structures. The fix was moving this logic to `TemplateResolver` where `resolve_nested()` could use it.

### 2. Backward Compatibility Was Free

No nodes broke because they all have `isinstance()` checks that handle both types. The fix enabled the "happy path" code that already existed.

### 3. Test Failures = Confirmation

Tests that fail after a bug fix aren't regressions - they're confirmation that the bug existed. The key is understanding which tests document behavior vs. which document bugs.

### 4. Shared Helpers Reduce Risk

Extracting `is_simple_template()` and `extract_simple_template_var()` to `TemplateResolver` means:
- One regex pattern to maintain
- Consistent detection across all resolution paths
- Easier to test and verify

---

## Files Changed Summary

**Source (3 files):**
- `src/pflow/runtime/template_resolver.py` - Core fix
- `src/pflow/runtime/node_wrapper.py` - Use shared helper
- `src/pflow/runtime/workflow_executor.py` - Use resolve_template

**Tests (8 files):**
- 6 files updated (resolve_string → resolve_template)
- 2 new test files added

**Documentation:**
- `implementation-plan.md` - Created
- `progress-log.md` - This file

---

## [Code Review] - PR #32 Review Feedback

### Review Summary

Received comprehensive code review via GitHub comment. Overall assessment: **8.5-10/10** across categories.

### Warnings Identified

| Finding | Priority | Action |
|---------|----------|--------|
| ⚠️ SIMPLE_TEMPLATE_PATTERN too permissive | Medium | **FIXED** |
| ⚠️ Missing whitespace edge case test | Low | **FIXED** |

### Suggestions Identified

| Finding | Priority | Action |
|---------|----------|--------|
| 💡 Extract shared `_VAR_NAME_PATTERN` | Code organization | **FIXED** |
| 💡 Escaped template test | Test quality | Skipped (behavior verified correct) |
| 💡 Logging enhancement | Observability | Skipped (too minor) |

---

## [Review Fix 1] - Stricter SIMPLE_TEMPLATE_PATTERN

### Problem

The original pattern `r"^\$\{([^}]+)\}$"` was too permissive:
- Matched invalid variable names: `${123}`, `${-invalid}`
- Matched whitespace: `${ var }`
- Inconsistent with `TEMPLATE_PATTERN` which is strict

### Solution

Extracted shared pattern and use in both constants:

```python
# Before:
TEMPLATE_PATTERN = re.compile(
    r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[\d+\])?(?:\.[a-zA-Z_][\w-]*(?:\[\d+\])?)*)?)\}"
)
SIMPLE_TEMPLATE_PATTERN = re.compile(r"^\$\{([^}]+)\}$")  # TOO PERMISSIVE

# After:
_VAR_NAME_PATTERN = r"[a-zA-Z_][\w-]*(?:(?:\[\d+\])?(?:\.[a-zA-Z_][\w-]*(?:\[\d+\])?)*)?"
TEMPLATE_PATTERN = re.compile(rf"(?<!\$)\$\{{({_VAR_NAME_PATTERN})\}}")
SIMPLE_TEMPLATE_PATTERN = re.compile(rf"^\$\{{({_VAR_NAME_PATTERN})\}}$")  # STRICT
```

### Verification

```
Testing patterns...
  is_simple_template('${var}'): True PASS
  is_simple_template('${data.field}'): True PASS
  is_simple_template('${items[0]}'): True PASS

  is_simple_template('${123}'): False PASS      # Now correctly rejected
  is_simple_template('${ var }'): False PASS    # Now correctly rejected
  is_simple_template('${-invalid}'): False PASS # Now correctly rejected
```

---

## [Review Fix 2] - Invalid Variable Name Tests

### Added Test

```python
def test_invalid_variable_names_not_simple(self):
    """Invalid variable names should NOT be detected as simple templates."""
    # Starting with number
    assert TemplateResolver.is_simple_template("${123}") is False
    # Starting with hyphen
    assert TemplateResolver.is_simple_template("${-invalid}") is False
    # Whitespace inside
    assert TemplateResolver.is_simple_template("${ var }") is False
    assert TemplateResolver.is_simple_template("${ var}") is False
    assert TemplateResolver.is_simple_template("${var }") is False
    # Special characters
    assert TemplateResolver.is_simple_template("${@invalid}") is False
    assert TemplateResolver.is_simple_template("${var!}") is False
```

### Rationale

Documents the exact boundary between valid and invalid templates. Protects against pattern regression.

---

## [Review Fix 3] - Verified Escaped Templates

### Verified Current Behavior

```python
# Escaped template test:
is_simple_template('$${var}'): False  # Correct - not a simple template
resolve_template('$${var}'): '$${var}'  # Correct - stays literal
```

The negative lookbehind in `TEMPLATE_PATTERN` (`(?<!\$)`) correctly prevents matching templates preceded by `$`. No code change needed.

---

## Final Test Results After Review Fixes

```
3237 passed, 9 skipped in 16.02s
```

One additional test added (total now 3237).

---

## Summary of All Changes

### Source Files (3 files)

| File | Change |
|------|--------|
| `template_resolver.py` | Added `_VAR_NAME_PATTERN`, renamed `resolve_string`→`resolve_template`, added helper methods |
| `node_wrapper.py` | Use shared helper, call `resolve_template` |
| `workflow_executor.py` | Call `resolve_template` |

### Test Files (8 files)

| File | Change |
|------|--------|
| `test_template_resolver.py` | Updated 22 calls |
| `test_template_resolver_arrays.py` | Updated 6 calls |
| `test_template_resolver_nested.py` | Updated 2 calls |
| `test_template_array_notation.py` | Updated 1 call |
| `test_json_text_parsing.py` | Updated 5 calls, rewrote for new behavior |
| `test_node_wrapper_nested_resolution.py` | Fixed 2 assertions |
| `test_template_type_preservation.py` | **NEW** - 13 tests for type preservation |
| `test_shell_stdin_type_preservation.py` | **NEW** - 4 integration tests |

### Documentation

| File | Change |
|------|--------|
| `implementation-plan.md` | Created |
| `progress-log.md` | This file |

---
