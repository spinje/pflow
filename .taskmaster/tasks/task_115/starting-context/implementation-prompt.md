# Implementation Prompt: Task 115 - Automatic Stdin Routing

## Current Status: IMPLEMENTATION 95% COMPLETE

**The core implementation is done.** A previous agent has implemented all the main functionality. Only **3 test failures remain** to be fixed.

### Before You Do Anything Else

1. **Read ALL Context Files
   ```
   .taskmaster/tasks/task_115/starting-context/task-115-spec.md
   .taskmaster/tasks/task_115/starting-context/braindump-research-complete.md
   .taskmaster/tasks/task_115/starting-context/task-115.md
   .taskmaster/tasks/task_115/starting-context/research-findings.md
   ```

2. **Read the progress log** to understand what's been done and what's left:
   ```
   .taskmaster/tasks/task_115/implementation/progress-log.md
   ```

3. **Review the current changes** by running:
   ```bash
   git diff --staged
   ```
   This shows all the implementation changes already made.

4. **Run the tests** to see current state:
   ```bash
   make test
   ```
   Expected: 3 failures, ~4008 passed

---

## What's Already Done

✅ Schema updated with `stdin` field (`ir_schema.py`)
✅ Multi-stdin validation added (`workflow_validator.py`)
✅ Full stdin routing logic implemented (`main.py`)
✅ Old `${stdin}` pattern removed entirely
✅ Most tests updated
✅ `make check` passes (linting, type checks)

## What's Left: Fix 3 Failing Tests

### 1. `tests/test_cli/test_dual_mode_stdin.py::test_very_large_stdin_handled_appropriately`
- Need to investigate why it's failing
- The workflow was updated to have `stdin: true` input

### 2. `tests/test_planning/integration/test_parameter_management_integration.py::test_stdin_no_longer_detected_in_planner`
- Error: `KeyError: 'stdin_type'` at line 251
- The assertion `exec_res["stdin_type"]` fails because the field doesn't exist
- **Quick fix**: Remove or change the `exec_res["stdin_type"]` assertion - we no longer care about this

### 3. `tests/test_planning/unit/test_parameter_management.py::test_stdin_info_is_none_in_planner`
- Error: Same `KeyError: 'stdin_type'` at line 212
- **Quick fix**: Same as above - remove the `exec_res["stdin_type"]` assertion

### Suggested Fix for Tests 2 & 3

The tests were updated to verify `stdin_info` is None (correct), but they also try to check `exec_res["stdin_type"]` which doesn't exist in the response. Simply remove those assertions:

```python
# Remove these lines from both tests:
# assert exec_res["stdin_type"] is None  # <-- DELETE THIS
```

The `prep_res["stdin_info"] is None` assertion is sufficient.

---

## Context Files

If you need deeper understanding, these files contain the original research:

1. **Task Specification (SOURCE OF TRUTH):**
   ```
   .taskmaster/tasks/task_115/starting-context/task-115-spec.md
   ```

2. **Braindump (TACIT KNOWLEDGE):**
   ```
   .taskmaster/tasks/task_115/starting-context/braindump-research-complete.md
   ```

3. **Task Description:**
   ```
   .taskmaster/tasks/task_115/task-115.md
   ```

4. **Research Findings (CODEBASE ANALYSIS):**
   ```
   .taskmaster/tasks/task_115/starting-context/research-findings.md
   ```

---

## Your Mission

1. **Read the progress log** first
2. **Review git staged changes** to understand the implementation
3. **Fix the 3 remaining test failures**
4. **Run `make test`** to verify all tests pass
5. **Run `make check`** to verify linting/types still pass
6. **Update the progress log** with your fixes

---

## Implementation Summary (For Reference)

### Key Files Modified

| File | Change |
|------|--------|
| `src/pflow/core/ir_schema.py` | Added `stdin` boolean field to input schema |
| `src/pflow/runtime/workflow_validator.py` | Added multi-stdin validation |
| `src/pflow/cli/main.py` | Full stdin routing: helpers + routing logic |
| `src/pflow/execution/executor_service.py` | Removed `populate_shared_store()` call |
| `src/pflow/core/shell_integration.py` | Removed `populate_shared_store()` function |
| `src/pflow/core/__init__.py` | Removed export |
| `src/pflow/planning/nodes.py` | Removed stdin checking, `stdin_info = None` |

### Key Implementation in main.py

```python
def _route_stdin_to_params(ctx, stdin_data, workflow_ir, params):
    """Route stdin to workflow input marked with stdin: true."""
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

## Verification After Fixes

```bash
# All tests should pass
make test

# All checks should pass
make check

# Manual verification (optional)
echo '{"items": [1,2,3]}' | pflow workflow-with-stdin-true.json
```

---

## User Priorities (Keep In Mind)

1. **Simplicity** - One rule, explicit `stdin: true`, no magic
2. **Agent-friendly errors** - Show JSON examples, no internals
3. **Clean removal** - No half measures with `${stdin}` pattern
