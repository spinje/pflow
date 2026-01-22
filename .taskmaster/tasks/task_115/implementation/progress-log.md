# Task 115 Implementation Progress Log

## Overview

**Task**: Automatic Stdin Routing for Unix-First Piping
**Goal**: Route piped stdin to workflow inputs marked with `"stdin": true`
**Started**: 2026-01-22

---

## [Session Start] - Reading Context Files

Read all four context files as instructed:
1. `task-115-spec.md` - Source of truth (v1.3.0)
2. `braindump-research-complete.md` - Tacit knowledge from previous research
3. `task-115.md` - Task description and examples
4. `research-findings.md` - Codebase analysis with line numbers

### Key Understanding Confirmed

**Critical Injection Point**: Stdin routing must happen INSIDE `_validate_and_prepare_workflow_params()` in `src/pflow/cli/main.py`:
- After `parse_workflow_params()` (line ~3093)
- Before `prepare_inputs()` (line ~3121)

**Why**: If routing happens AFTER this function, required inputs expecting stdin will fail validation because `prepare_inputs()` checks for required inputs.

**Error Handling Pattern**: Use direct `click.echo(..., err=True)` + `ctx.exit(1)`, NOT tuple pattern.

**What to Remove** (old `${stdin}` pattern):
- `executor_service.py:176` - `populate_shared_store()` call
- `shell_integration.py:200-210` - `populate_shared_store()` function
- `core/__init__.py` - Export of `populate_shared_store`
- `planning/nodes.py:840-847` - Stdin checking in `ParameterDiscoveryNode`
- Tests for removed function

---

## [Step 1] - Add stdin field to IR schema

**File**: `src/pflow/core/ir_schema.py`

**Action**: Added `stdin` boolean field to input schema properties.

```python
"stdin": {
    "type": "boolean",
    "default": False,
    "description": "Whether this input receives piped stdin data",
},
```

- ✅ What worked: Clean addition to existing properties block
- 💡 Insight: Schema already had `additionalProperties: False`, so this was required

---

## [Step 2] - Add multi-stdin validation in prepare_inputs

**File**: `src/pflow/runtime/workflow_validator.py`

**Action**: Added validation in `prepare_inputs()` to reject workflows with multiple `stdin: true` inputs.

```python
# Check for multiple stdin: true inputs (only one allowed)
stdin_inputs = [name for name, spec in inputs.items() if spec.get("stdin") is True]
if len(stdin_inputs) > 1:
    errors.append((
        f"Multiple inputs marked with \"stdin\": true: {', '.join(stdin_inputs)}",
        "inputs",
        "Only one input can receive piped stdin",
    ))
```

- ✅ What worked: Added after inputs extraction, before individual input validation
- 💡 Insight: Using tuple format `(msg, path, suggestion)` matches existing error pattern

---

## [Step 3] - Implement stdin routing logic in main.py

**File**: `src/pflow/cli/main.py`

### 3a. Added helper functions

```python
def _find_stdin_input(workflow_ir: dict[str, Any]) -> str | None:
    """Find the input marked with stdin: true."""
    inputs = workflow_ir.get("inputs", {})
    for name, spec in inputs.items():
        if spec.get("stdin") is True:
            return name
    return None


def _extract_stdin_text(stdin_data: str | StdinData | None) -> str | None:
    """Extract text content from stdin data."""
    if stdin_data is None:
        return None
    if isinstance(stdin_data, str):
        return stdin_data
    # StdinData object - only extract text_data, not binary or temp file
    if stdin_data.text_data is not None:
        return stdin_data.text_data
    # Binary data or temp file path - do not route
    return None
```

- ✅ What worked: Simple, focused helper functions
- 💡 Insight: Handling both `str` and `StdinData` types covers all CLI input modes

### 3b. Modified _validate_and_prepare_workflow_params signature

Added `stdin_data: str | StdinData | None = None` parameter.

### 3c. Added stdin routing logic

Added routing between parameter parsing and validation:

```python
# Route stdin to workflow input marked with stdin: true
stdin_text = _extract_stdin_text(stdin_data)
if stdin_text is not None:
    target_input = _find_stdin_input(workflow_ir)

    if target_input is None:
        # Error with JSON example
        click.echo("❌ Piped input cannot be routed to workflow", err=True)
        # ... detailed error message ...
        ctx.exit(1)

    # Route stdin to target input (unless CLI override exists)
    if target_input not in params:
        params[target_input] = stdin_text
```

- ✅ What worked: Error message with JSON example as per spec
- ✅ What worked: CLI override check (`if target_input not in params`)

### 3d. Updated call site

Updated `_handle_named_workflow()` to pass `stdin_data`:

```python
params = _validate_and_prepare_workflow_params(ctx, workflow_ir, remaining_args, stdin_data)
```

- ✅ What worked: `stdin_data` was already available in the function
- 💡 Insight: Only one call site needed updating (spec mentioned two paths, but planner path uses different code)

---

## [Step 4] - Remove populate_shared_store call

**File**: `src/pflow/execution/executor_service.py`

**Action**: Removed import and call to `populate_shared_store()`:

Before:
```python
from pflow.core.shell_integration import populate_shared_store
...
if stdin_data:
    populate_shared_store(shared_store, stdin_data)
```

After:
```python
# Note: stdin data is now routed to workflow inputs via stdin: true
# in the workflow IR, handled by _validate_and_prepare_workflow_params
```

- ✅ What worked: Clean removal with explanatory comment

---

## [Step 5] - Remove populate_shared_store function

**File**: `src/pflow/core/shell_integration.py`

**Action**: Removed the entire function (lines 200-210):

```python
# REMOVED:
def populate_shared_store(shared: dict, content: str) -> None:
    """Add stdin content to shared store."""
    shared["stdin"] = content
```

- ✅ What worked: Simple deletion

---

## [Step 6] - Remove populate_shared_store from exports

**File**: `src/pflow/core/__init__.py`

**Action**: Removed from both import statement and `__all__` list.

- ✅ What worked: Two edits required (import and __all__)

---

## [Step 7] - Remove stdin checking in ParameterDiscoveryNode

**File**: `src/pflow/planning/nodes.py`

**Action**: Replaced stdin checking logic with comment explaining the change:

Before:
```python
# Check for stdin data (fallback parameter source)
stdin_info = None
if shared.get("stdin"):
    stdin_info = {"type": "text", "preview": str(shared["stdin"])[:500]}
elif shared.get("stdin_binary"):
    stdin_info = {"type": "binary", "size": str(len(shared["stdin_binary"]))}
elif shared.get("stdin_path"):
    stdin_info = {"type": "file", "path": shared["stdin_path"]}
```

After:
```python
# Note: stdin data is now routed to workflow inputs via stdin: true
# in the workflow IR, handled by the CLI. The planner no longer needs
# to know about stdin content.
stdin_info = None
```

- ✅ What worked: Kept `stdin_info = None` to maintain prompt compatibility
- 💡 Insight: The variable is still used in the prompt, so setting to None is cleaner than removing

---

## [Step 8] - Update tests

### 8a. test_shell_integration.py

**Actions**:
1. Removed `populate_shared_store` from imports
2. Removed entire `TestPopulateSharedStore` class (4 tests)
3. Updated `test_full_data_flow` to not use `populate_shared_store`

- ✅ What worked: Clean removal of obsolete tests

### 8b. test_parameter_mapping_prompt.py

**Action**: Removed `shared["stdin"]` setting (line 286), replaced with comment:

```python
# Note: stdin is now routed to workflow inputs via stdin: true
# in the workflow IR, not via shared["stdin"]. The test cases don't
# use stdin_data, so no additional setup is needed.
```

- 💡 Insight: No test cases actually used `stdin_data=`, so this was dead code

### 8c. test_user_nodes.py

**Action**: Changed test to pass params directly instead of via `shared["stdin"]`:

Before:
```python
stdin_data = {"x": 7, "y": 3, "operation": "multiply"}
shared = {"stdin": json.dumps(stdin_data)}
```

After:
```python
# Pass calculation parameters directly (previously tested via shared["stdin"])
# Note: stdin is now routed to workflow inputs via stdin: true
shared = {"x": 7, "y": 3, "operation": "multiply"}
```

- ✅ What worked: CalculatorNode has fallback to direct params
- 💡 Insight: Node still has stdin handling code but it's never exercised now

---

## [Step 9] - Run make check

**First run result**: FAILED

```
src/pflow/cli/main.py:3112:5: C901 `_validate_and_prepare_workflow_params` is too complex (13 > 10)
```

### 9a. First fix attempt - Extract error display

**Action**: Created `_show_stdin_routing_error()` function:

```python
def _show_stdin_routing_error(ctx: click.Context) -> None:
    """Display error when stdin cannot be routed to workflow."""
    click.echo("❌ Piped input cannot be routed to workflow", err=True)
    # ... rest of error message ...
    ctx.exit(1)
```

Updated main function to call it:
```python
if target_input is None:
    _show_stdin_routing_error(ctx)
```

**Second run result**: STILL FAILED - complexity still 13

- ❌ What failed: Extracting error display didn't reduce complexity enough
- 💡 Insight: The function has many branches - need to extract more logic

---

## [Current State] - Need further refactoring

The function `_validate_and_prepare_workflow_params` is still too complex (13 > 10).

**Plan**: Extract additional helper functions:
- Settings loading logic
- Validation error display logic

**Files Modified So Far**:
1. ✅ `src/pflow/core/ir_schema.py` - Added stdin field
2. ✅ `src/pflow/runtime/workflow_validator.py` - Added multi-stdin validation
3. ⚠️ `src/pflow/cli/main.py` - Implemented routing (needs complexity fix)
4. ✅ `src/pflow/execution/executor_service.py` - Removed populate_shared_store call
5. ✅ `src/pflow/core/shell_integration.py` - Removed populate_shared_store function
6. ✅ `src/pflow/core/__init__.py` - Removed export
7. ✅ `src/pflow/planning/nodes.py` - Removed stdin checking
8. ✅ `tests/test_shell_integration.py` - Removed obsolete tests
9. ✅ `tests/test_planning/llm/prompts/test_parameter_mapping_prompt.py` - Updated
10. ✅ `tests/test_integration/test_user_nodes.py` - Updated

**Next Steps**:
1. Extract more helper functions to reduce complexity
2. Re-run `make check`
3. Run `make test` to verify all tests pass
4. Manual verification with test workflows

---

---

## [After make check passes] - Running Tests

**Command**: `make test`

**Result**: 6 failing tests

### Failing Tests Analysis

1. **test_file_workflow_with_stdin_data_shows_injection_message** - Expects "Injected" message for stdin
   - Old behavior: stdin went to `shared["stdin"]` regardless of workflow config
   - New behavior: stdin errors if no `stdin: true` input exists
   - **Fix**: Update test to expect error, or add `stdin: true` input to workflow

2. **test_very_large_stdin_handled_appropriately** - Tests large stdin handling
   - Same issue - workflow has no `stdin: true` input
   - **Fix**: Add `stdin: true` input to test workflow

3. **test_stdin_with_file_workflow** - Tests stdin with file workflow
   - Same issue
   - **Fix**: Add `stdin: true` input to test workflow

4. **test_stdin_fallback_across_all_nodes** - Tests `prep_res["stdin_info"]`
   - Old behavior: ParameterDiscoveryNode populated `stdin_info` from `shared["stdin"]`
   - New behavior: `stdin_info` is always None (stdin routed via CLI, not planner)
   - **Fix**: Remove or update test - this behavior is intentionally removed

5. **test_detects_stdin_as_parameter_source** - Same as above
   - **Fix**: Remove or update test

6. **test_stdin_metadata_preserved** - Same as above
   - **Fix**: Remove or update test

### Decision: How to Handle Each Test

| Test | Decision | Reason |
|------|----------|--------|
| CLI tests (1-3) | Update workflow to have `stdin: true` input | Tests valid use case |
| Planning tests (4-6) | Remove stdin-specific assertions | Behavior intentionally removed |

---

## [Test Fixes Applied] - Updating Failing Tests

### CLI Tests Fixed

1. **test_file_workflow_with_stdin_data_shows_injection_message** → Renamed to `test_file_workflow_with_stdin_data_routes_to_input`
   - Added `stdin: true` input to workflow
   - Updated assertions

2. **test_very_large_stdin_handled_appropriately**
   - Added `stdin: true` input to workflow
   - Still failing (needs investigation)

3. **test_stdin_with_file_workflow**
   - Added `stdin: true` input to workflow
   - Updated assertions

### Planning Tests Fixed

4. **test_stdin_fallback_across_all_nodes** → Renamed to `test_stdin_no_longer_detected_in_planner`
   - Changed assertions to expect `stdin_info` is None
   - Still failing due to KeyError: 'stdin_type' in exec_res

5. **test_detects_stdin_as_parameter_source** → Renamed to `test_stdin_info_is_none_in_planner`
   - Changed assertions to expect `stdin_info` is None
   - Still failing due to KeyError: 'stdin_type' in exec_res

6. **test_stdin_metadata_preserved**
   - Changed assertions to expect `stdin_info` is None
   - Now passing

---

## [CURRENT STATE] - 3 Tests Still Failing

**`make check`**: ✅ PASSING

**`make test`**: 3 failures, 4008 passed

### Remaining Failures

1. **test_very_large_stdin_handled_appropriately** (`tests/test_cli/test_dual_mode_stdin.py`)
   - Status: Unknown failure reason - need to investigate

2. **test_stdin_no_longer_detected_in_planner** (`tests/test_planning/integration/test_parameter_management_integration.py:251`)
   - Error: `KeyError: 'stdin_type'` in `exec_res`
   - The test asserts `exec_res["stdin_type"] is None` but the field doesn't exist
   - **Fix needed**: Check actual exec_res structure and update assertion

3. **test_stdin_info_is_none_in_planner** (`tests/test_planning/unit/test_parameter_management.py:212`)
   - Error: Same `KeyError: 'stdin_type'`
   - **Fix needed**: Same fix as above

### Root Cause of KeyError

The `exec_res` from `ParameterDiscoveryNode.exec()` returns the LLM response which is a `ParameterDiscovery` Pydantic model. Need to check:
- What fields does `ParameterDiscovery` actually have?
- The mock response includes `stdin_type` but the actual exec_res structure may be different

**Location to check**: `src/pflow/planning/nodes.py:777` - `class ParameterDiscovery(BaseModel)`

---

## Files Modified (Complete List)

### Implementation Files
1. ✅ `src/pflow/core/ir_schema.py` - Added `stdin` field to input schema
2. ✅ `src/pflow/runtime/workflow_validator.py` - Added multi-stdin validation
3. ✅ `src/pflow/cli/main.py` - Full stdin routing implementation:
   - Added `_find_stdin_input()` helper
   - Added `_extract_stdin_text()` helper
   - Added `_show_stdin_routing_error()` helper (NoReturn)
   - Added `_route_stdin_to_params()` helper
   - Added `_load_settings_env()` helper
   - Modified `_validate_and_prepare_workflow_params()` signature and logic
   - Updated call site in `_handle_named_workflow()`
4. ✅ `src/pflow/execution/executor_service.py` - Removed `populate_shared_store()` call
5. ✅ `src/pflow/core/shell_integration.py` - Removed `populate_shared_store()` function
6. ✅ `src/pflow/core/__init__.py` - Removed `populate_shared_store` export
7. ✅ `src/pflow/planning/nodes.py` - Removed stdin checking, set `stdin_info = None`

### Test Files
8. ✅ `tests/test_shell_integration.py` - Removed `TestPopulateSharedStore` class, updated imports
9. ✅ `tests/test_planning/llm/prompts/test_parameter_mapping_prompt.py` - Removed stdin handling
10. ✅ `tests/test_integration/test_user_nodes.py` - Changed from `shared["stdin"]` to direct params
11. ⚠️ `tests/test_cli/test_dual_mode_stdin.py` - Updated 2 tests, 1 still failing
12. ⚠️ `tests/test_cli/test_main.py` - Updated test, now passing
13. ⚠️ `tests/test_planning/unit/test_parameter_management.py` - Updated test, still failing
14. ⚠️ `tests/test_planning/integration/test_parameter_management_integration.py` - Updated test, still failing
15. ✅ `tests/test_planning/integration/test_discovery_to_parameter_flow.py` - Updated test, now passing

---

## What the Next Agent Needs to Do

### 1. Fix the 3 Remaining Test Failures

**For test_very_large_stdin_handled_appropriately:**
- Run the test in isolation to see actual error
- May need workflow adjustment or assertion fix

**For the two KeyError: 'stdin_type' tests:**
- Check `ParameterDiscovery` model at `src/pflow/planning/nodes.py:777`
- The exec_res might not have `stdin_type` field in the way tests expect
- Either:
  a. Remove the `exec_res["stdin_type"]` assertion entirely (simpler)
  b. Or check actual structure and update assertion

### 2. Verify All Tests Pass
```bash
make test
```

### 3. Update Progress Log with Final Status

### 4. Consider Adding New Tests for stdin: true Feature
- Test stdin routing to input with `stdin: true`
- Test error when no `stdin: true` input exists
- Test CLI override wins over stdin
- Test multiple `stdin: true` validation error

---

## Key Implementation Details for Reference

### Stdin Routing Logic (main.py)
```python
def _route_stdin_to_params(ctx, stdin_data, workflow_ir, params):
    stdin_text = _extract_stdin_text(stdin_data)
    if stdin_text is None:
        return
    target_input = _find_stdin_input(workflow_ir)
    if target_input is None:
        _show_stdin_routing_error(ctx)  # NoReturn - exits
    if target_input not in params:
        params[target_input] = stdin_text
```

### Error Message Format
```
❌ Piped input cannot be routed to workflow

   This workflow has no input marked with "stdin": true.
   To accept piped data, add "stdin": true to one input declaration.

   Example:
     "inputs": {
       "data": {"type": "string", "required": true, "stdin": true}
     }

   👉 Add "stdin": true to the input that should receive piped data
```

---

## Lessons Learned So Far

1. **Read all context files first** - The spec was comprehensive and accurate
2. **Injection point matters** - INSIDE the validation function, not after it
3. **Function complexity limits** - ruff enforces max complexity of 10
4. **Test cleanup is straightforward** - Most tests weren't actually exercising the old pattern
5. **Planner vs CLI paths differ** - Only CLI path needed modification for stdin routing

---

## Deviations from Plan

### DEVIATION 1: Function Complexity
- **Original plan**: Implement all logic in `_validate_and_prepare_workflow_params`
- **Why it failed**: Function exceeded ruff complexity limit (13 > 10)
- **New approach**: Extract helper functions for error display, potentially more
- **Lesson**: Consider complexity limits when adding to existing functions

### DEVIATION 2: Planner Path
- **Original understanding**: Spec mentioned two execution paths using the validation function
- **Actual code**: Planner path uses different parameter handling (`_execute_successful_workflow`)
- **Impact**: None - CLI path is the right place for stdin routing
- **Lesson**: Verify spec against actual code, especially for multi-path systems

---

## [Session 2] - Final Test Fixes (2026-01-22)

### 3 Remaining Test Failures Fixed

**1. test_very_large_stdin_handled_appropriately**

**Root Cause**: Two issues:
- Used invalid node type "echo" (doesn't exist in registry)
- Shell command with embedded 1MB data exceeded OS argument list limits

**Fix**: Changed to use `write-file` node which:
- Is a valid registered node type
- Handles large data via Python file I/O, not shell argv
- Added assertion to verify data was written correctly

```python
# Before (broken):
"type": "echo"
"params": {"message": "Received data"}

# After (working):
"type": "write-file"
"params": {"file_path": str(output_file), "content": "${data}"}
```

**2. test_stdin_no_longer_detected_in_planner** (integration test)

**Root Cause**: Test tried to access `exec_res["stdin_type"]` but:
- The `exec()` method calls `parse_structured_response()` which may not include all fields
- The mock LLM response structure didn't match what the parser extracts

**Fix**: Removed the `exec_res["stdin_type"]` assertion since:
- The test's real purpose is verifying `prep_res["stdin_info"]` is None
- The exec_res check was just verifying mock behavior, not real functionality

**3. test_stdin_info_is_none_in_planner** (unit test)

**Root Cause**: Same issue as above

**Fix**: Same approach - removed the redundant `exec_res["stdin_type"]` assertion

### Final Verification

```bash
make test   # 4011 passed
make check  # All checks passed (ruff, mypy, deptry)
```

### Task 115 Implementation: COMPLETE ✅

**All tests passing. All checks passing.**

Files modified in this session:
- `tests/test_cli/test_dual_mode_stdin.py` - Fixed large stdin test
- `tests/test_planning/unit/test_parameter_management.py` - Removed exec_res assertion
- `tests/test_planning/integration/test_parameter_management_integration.py` - Removed exec_res assertion

---

## [Session 3] - Test Quality Improvement (2026-01-22)

### Re-evaluated Test Value

After reading all context files and discussing with user, identified that the original test fixes were addressing symptoms, not testing valuable behavior.

**Problem identified**: Tests were testing implementation details (e.g., `stdin_info is None` in planner) rather than user-facing behavior.

### Changes Made

**ADDED 3 valuable behavior tests:**

1. **`test_stdin_error_when_no_stdin_input_declared`**
   - Pipes data to workflow without `stdin: true`
   - Verifies error message contains helpful guidance
   - Tests the main error path users will hit

2. **`test_stdin_error_when_multiple_stdin_inputs`**
   - Workflow with two `stdin: true` inputs
   - Verifies validation error lists both input names
   - Tests schema validation

3. **`test_cli_param_overrides_stdin`**
   - Pipes data but also provides CLI param for same input
   - Verifies CLI value is used (writes to file, checks contents)
   - Tests override behavior for debugging/testing

**REMOVED 2 implementation-detail tests:**

4. **Deleted `test_stdin_no_longer_detected_in_planner`**
   - Was testing that `prep_res["stdin_info"]` is None
   - This is internal planner state, not user-visible behavior

5. **Deleted `test_stdin_info_is_none_in_planner`**
   - Same issue - testing implementation, not behavior

### Test Philosophy Applied

> "We should not follow the spec blindly but do what actually makes most sense. We are not optimizing for test coverage but for actually VALUABLE tests, testing important behavior."

**What matters:**
- Does stdin route correctly? (happy path)
- Do users get helpful errors? (error paths)
- Can users override stdin with CLI? (flexibility)

**What doesn't matter:**
- Internal variable values in planner
- Whether a specific function sets a specific field

### Final Verification

```bash
make test   # 4012 passed ✅
make check  # All checks passed ✅
```

### Test Coverage for Task 115 Stdin Routing

| Behavior | Test | File |
|----------|------|------|
| Stdin routes to `stdin: true` input | `test_file_workflow_with_stdin_data_routes_to_input` | test_dual_mode_stdin.py |
| Large stdin handled | `test_very_large_stdin_handled_appropriately` | test_dual_mode_stdin.py |
| Binary stdin doesn't crash | `test_binary_stdin_shows_appropriate_warning` | test_dual_mode_stdin.py |
| Error when no `stdin: true` | `test_stdin_error_when_no_stdin_input_declared` | test_dual_mode_stdin.py |
| Error when multiple `stdin: true` | `test_stdin_error_when_multiple_stdin_inputs` | test_dual_mode_stdin.py |
| CLI param overrides stdin | `test_cli_param_overrides_stdin` | test_dual_mode_stdin.py |

### Lessons Learned

1. **Read context files first** - Would have avoided wasted effort on wrong tests
2. **Test behavior, not implementation** - Users don't care about internal state
3. **Question test value** - Just because a test passes doesn't mean it's valuable
4. **Use verifiable side effects** - Writing to file is more reliable than checking CLI output

---

## [Session 4] - Manual Testing & Documentation (2026-01-22)

### Manual CLI Testing

Created test workflows in `/tmp/task115-tests/` and verified all functionality:

| Test | Command | Result |
|------|---------|--------|
| Basic stdin routing | `echo "Hello" \| pflow workflow.json` | ✅ Data routed correctly |
| No stdin: true error | `echo "data" \| pflow no-stdin-workflow.json` | ✅ Helpful error with JSON example |
| Multiple stdin: true | `pflow multi-stdin-workflow.json` | ✅ Lists both input names |
| CLI override | `echo "ignored" \| pflow w.json data="used"` | ✅ CLI value wins |
| No stdin provided | `pflow workflow.json` (no pipe) | ✅ Normal required input error |

### Documentation Updates

Added minimal `stdin: true` documentation to `src/pflow/cli/resources/cli-agent-instructions.md`:

1. **Workflow Structure Complete Reference** (line ~858):
   ```json
   "stdin": true|false  // If true, piped stdin routes here (only one input can have this)
   ```

2. **Parameter Types - Complete Guide** (line ~1183):
   ```json
   // Stdin - receives piped input (e.g., cat data.json | pflow workflow.json)
   "data": {
     "type": "string",
     "required": true,
     "stdin": true,
     "description": "Data from stdin or CLI"
   }
   ```

### Critical Bug Found: Workflow Chaining Broken

**Discovery**: While testing `pflow -p workflow1.json | pflow workflow2.json`, the chaining fails.

**Root Cause**: Pre-existing bug in `stdin_has_data()` (shell_integration.py:99):
```python
rlist, _, _ = select.select([sys.stdin], [], [], 0)  # timeout=0 = non-blocking
```

When shell starts `pflow A | pflow B` simultaneously, Process B checks for stdin before Process A has written anything. The `select()` with timeout=0 returns empty immediately.

**Workaround** (currently required):
```bash
# Via intermediate file
pflow -p workflow1.json > /tmp/out.json && cat /tmp/out.json | pflow workflow2.json
```

**Recommended Fix** (Option 2 - Detect FIFO):
```python
import stat
mode = os.fstat(sys.stdin.fileno()).st_mode
if stat.S_ISFIFO(mode):
    # Real pipe - block until data/EOF (like cat, grep do)
    content = sys.stdin.read()
else:
    # Other non-TTY (socket, /dev/null, etc) - use non-blocking check
    if not stdin_has_data():
        return None
```

This matches Unix tool behavior - block on actual pipes, use non-blocking for other non-TTY cases.

### Remaining Work

**For another agent to implement:**
1. Fix `stdin_has_data()` in `src/pflow/core/shell_integration.py` using FIFO detection
2. Add test for workflow chaining: `pflow -p w1.json | pflow w2.json`
3. Verify the fix doesn't break existing stdin handling (IDE environments, etc.)

### Test Coverage Summary (Pre-FIFO Fix)

| Scenario | Status |
|----------|--------|
| Basic stdin routing | ✅ Tested |
| No stdin: true error | ✅ Tested |
| Multiple stdin: true error | ✅ Tested |
| CLI override | ✅ Tested |
| Binary stdin | ✅ Tested |
| Large stdin | ✅ Tested |
| Empty stdin | ✅ Tested |
| Workflow chaining | ❌ Blocked by FIFO bug |

---

## [Session 5] - FIFO Detection Fix (2026-01-22)

### Problem

Workflow chaining (`pflow -p workflow1.json | pflow workflow2.json`) didn't work because `stdin_has_data()` uses `select()` with timeout=0 which returns immediately before the upstream process has produced output.

**Root cause**: When shell pipes two processes, they start simultaneously. Process B checks for stdin before Process A writes anything. The `select()` with timeout=0 returns empty immediately.

### Solution Implemented

Modified `stdin_has_data()` in `src/pflow/core/shell_integration.py` to detect FIFO (pipe) vs other non-TTY:

```python
import stat

# Check if stdin is a FIFO (pipe from another process)
# For real pipes, return True and let the caller block on read
# This is correct Unix behavior - cat, grep, jq all do this
try:
    mode = os.fstat(sys.stdin.fileno()).st_mode
    if stat.S_ISFIFO(mode):
        return True
except (OSError, AttributeError):
    # fstat might fail in some environments
    pass

# For other non-TTY cases (sockets, etc.), use non-blocking check
# This prevents hanging in environments like Claude Code
```

**Why this works**:
- For FIFO pipes: Return True immediately, letting the caller block on `sys.stdin.read()` (correct Unix behavior)
- For other non-TTY (sockets, /dev/null): Keep using `select()` with timeout=0 to avoid hanging in IDE environments

### Changes Made

**File**: `src/pflow/core/shell_integration.py`
1. Added `import stat` to imports
2. Modified `stdin_has_data()` to detect FIFO using `os.fstat()` and `stat.S_ISFIFO()`

### Verification

```bash
make check   # ✅ All checks pass
make test    # ✅ 4012 tests pass
```

### Manual Test Results

| Test | Command | Result |
|------|---------|--------|
| Direct pipe | `pflow -p producer.json \| pflow -p consumer.json` | ✅ Works |
| Producer alone | `pflow -p producer.json count=3` | ✅ Works |
| Consumer with echo | `echo '[1,2,3]' \| pflow -p consumer.json` | ✅ Works |
| No stdin (terminal) | `pflow consumer.json` (no pipe) | ✅ Error (not hang) |
| Three-stage pipeline | `pflow -p a.json \| pflow -p b.json \| pflow -p c.json` | ✅ Works |

### Final Test Coverage

| Scenario | Status |
|----------|--------|
| Basic stdin routing | ✅ Tested |
| No stdin: true error | ✅ Tested |
| Multiple stdin: true error | ✅ Tested |
| CLI override | ✅ Tested |
| Binary stdin | ✅ Tested |
| Large stdin | ✅ Tested |
| Empty stdin | ✅ Tested |
| Workflow chaining | ✅ **FIXED** |
| Three-stage pipeline | ✅ Tested |

### Automated Tests Added

Added 2 valuable behavior tests in `tests/test_cli/test_dual_mode_stdin.py`:

**1. `test_workflow_chaining_producer_to_consumer`**
- Uses actual subprocess with `shell=True` for real Unix pipe behavior
- Producer generates `[1,2,3]`, consumer counts length via jq
- Verifies output is `3`
- This is THE key test - it would fail without the FIFO fix

**2. `test_three_stage_pipeline`**
- Tests `producer | transform | consumer` pipeline
- Producer generates `[1,2,3,4,5]`
- Transform doubles each element
- Consumer sums all elements
- Verifies output is `30`

These tests are valuable because they:
- Test real Unix pipe behavior (not CliRunner which doesn't support real pipes)
- Verify the core user-facing feature that the FIFO fix enables
- Would fail without the fix (consumer would check stdin before producer writes)

### Task 115 Implementation: COMPLETE ✅

All functionality working:
1. ✅ Stdin routes to `stdin: true` input
2. ✅ Helpful error when no `stdin: true` input exists
3. ✅ Validation error when multiple `stdin: true` inputs
4. ✅ CLI parameters override stdin
5. ✅ Workflow chaining with pipes works
6. ✅ All tests pass (4014 including 2 new tests)
7. ✅ All linting and type checks pass

---

## [Session 5 continued] - Risk Analysis & Additional Tests (2026-01-22)

### Bugfix Log Analysis

Reviewed `.taskmaster/bugfix/bugfix-log.md` to verify the FIFO fix is safe. Key relevant bug:

**BF-20250112-stdin-hang-nontty-grep**:
> Problem: `pflow --trace workflow.json 2>&1 | grep "pattern"` hung in Claude Code
> Root cause: stdin.read() blocked waiting for EOF when stdin was non-TTY but had no data
> Fix: Use select.select() with 0 timeout to check if stdin has data

**Why the FIFO fix is safe:**

The original fix was for Claude Code where stdin is a **socket** (non-TTY, but NOT a FIFO). Our FIFO detection correctly distinguishes:

| Environment | stdin type | S_ISFIFO | Behavior |
|-------------|------------|----------|----------|
| Real pipe (`a \| b`) | FIFO | True | Return True → block on read ✅ |
| Claude Code | Socket | False | Fall through to select() ✅ |
| Terminal | TTY | N/A | Return False early ✅ |
| /dev/null | Special | False | Explicit check returns False ✅ |

**SIGPIPE handling verified**: Already set to `SIG_IGN` in `main.py:2807-2808`

### Additional Unit Tests Added

Added 2 tests to `tests/test_core/test_stdin_no_hang.py`:

**1. `test_stdin_has_data_returns_true_for_fifo`**
- Mocks stdin with `stat.S_IFIFO` mode
- Verifies FIFO pipes return True immediately
- Critical for workflow chaining

**2. `test_stdin_has_data_uses_select_for_non_fifo_non_tty`**
- Mocks stdin as socket (`stat.S_IFSOCK`)
- Verifies non-FIFO falls through to select()
- Verifies select() is called with timeout=0
- Preserves Claude Code fix (BF-20250112)

### Windows Compatibility Research

**Findings:**
- `stat.S_ISFIFO()` always returns False on Windows (no FIFO concept)
- `select.select()` on Windows only works with sockets, not stdin
- Current fallback handles Windows: `return not sys.stdin.isatty()`

**Windows behavior:**
| Scenario | Behavior |
|----------|----------|
| TTY (interactive) | Returns False ✅ |
| Piped stdin | select() fails → fallback returns True → blocks ✅ |
| Non-TTY, no data | Returns True → could hang (rare edge case) ⚠️ |

**Decision:** Accept limitation. pflow is Unix-first, fallback is acceptable.

**Created Task 116** for Windows compatibility tracking with detailed research in:
- `.taskmaster/tasks/task_116/task-116.md`
- `.taskmaster/tasks/task_116/research/stdin-fifo-detection.md`

### Final Verification

```bash
make check   # ✅ All checks pass
make test    # ✅ 4016 tests pass (4 new tests total)
```

### Complete Test Coverage for Task 115

| Test | File | Purpose |
|------|------|---------|
| `test_workflow_chaining_producer_to_consumer` | test_dual_mode_stdin.py | Real subprocess pipe chaining |
| `test_three_stage_pipeline` | test_dual_mode_stdin.py | Multi-stage pipeline |
| `test_stdin_has_data_returns_true_for_fifo` | test_stdin_no_hang.py | FIFO detection unit test |
| `test_stdin_has_data_uses_select_for_non_fifo_non_tty` | test_stdin_no_hang.py | Socket fallback unit test |

### Key Insights

1. **Unix tool behavior**: cat, grep, jq all block on FIFO pipes - this is correct behavior
2. **Claude Code environment**: stdin is a socket, not FIFO - select() fallback handles this
3. **SIGPIPE**: Already handled with `SIG_IGN` - large data pipes won't fail
4. **Windows**: Falls back gracefully, documented in Task 116

### Files Modified (Complete)

**Implementation:**
- `src/pflow/core/shell_integration.py` - Added `import stat`, FIFO detection in `stdin_has_data()`

**Tests:**
- `tests/test_cli/test_dual_mode_stdin.py` - Added `TestWorkflowChaining` class (2 tests)
- `tests/test_core/test_stdin_no_hang.py` - Added FIFO and socket tests (2 tests)

**Documentation:**
- `.taskmaster/tasks/task_115/implementation/progress-log.md` - This file
- `.taskmaster/tasks/task_116/task-116.md` - Windows compatibility task
- `.taskmaster/tasks/task_116/research/stdin-fifo-detection.md` - Detailed research
- `CLAUDE.md` - Added Task 116 to Later section

---

## Task 115: FINAL STATUS ✅

**All objectives achieved:**
1. ✅ `stdin: true` field added to IR schema
2. ✅ Stdin routes to marked input automatically
3. ✅ Helpful errors when no/multiple `stdin: true` inputs
4. ✅ CLI parameters override piped stdin
5. ✅ Workflow chaining via Unix pipes works
6. ✅ Backward compatible (Claude Code, IDE environments)
7. ✅ Comprehensive test coverage (4016 tests)
8. ✅ Windows limitations documented (Task 116)
