# Task 53 Implementation Plan

## Context Gathered

### Display Patterns
- Success messages use `✅` prefix with `\n` for spacing
- Commands shown with `$` prefix and 2-space indent
- Only display in interactive mode (stdin and stdout are TTY)

### Integration Points
- Reused workflows: Line 1363 in `_execute_successful_workflow()`
- New workflows: Line 531 in `_prompt_workflow_save()` after save
- Single caller of `_prompt_workflow_save()` at line 1366

### Dependencies
- `shlex.quote()` for shell escaping (needs import)
- `json.dumps()` for list/dict formatting
- `click.echo()` for output display

## Implementation Steps

### Phase 1: Core Utilities (New Module)
**File**: `src/pflow/cli/rerun_display.py` (new)

Functions to create:
1. `format_param_value(value: Any) -> str` - Convert Python types to CLI strings
2. `format_rerun_command(workflow_name: str, params: dict[str, Any] | None) -> str` - Build complete command
3. `display_rerun_commands(workflow_name: str, params: dict[str, Any] | None) -> None` - Display both commands

Key logic:
- Reverse `infer_type()` conversions exactly
- Use `shlex.quote()` for ALL values
- Handle edge cases: empty strings, JSON, booleans

### Phase 2: Modify Save Function Return Type
**File**: `src/pflow/cli/main.py`

1. Change `_prompt_workflow_save()` signature:
   - From: `-> None`
   - To: `-> tuple[bool, str | None]`

2. Update return statements:
   - Line 495: `return (False, None)` when user declines
   - Line 531: `return (True, workflow_name)` after successful save
   - Line 536: `return (False, None)` when user doesn't retry
   - Line 542: `return (False, None)` on validation error
   - Line 545: `return (False, None)` on general error

3. Update caller at line 1366:
   - Capture return value but don't use it yet (will use in Phase 3)

### Phase 3: Add Display Logic - Reused Workflows
**File**: `src/pflow/cli/main.py`

Location: After line 1363 in `_execute_successful_workflow()`

Add after existing echo:
```python
# Display rerun command for reused workflows
from src.pflow.cli.rerun_display import display_rerun_commands
execution_params = planner_output.get("execution_params")
if execution_params is not None:
    display_rerun_commands(workflow_name, execution_params)
```

### Phase 4: Add Display Logic - New Workflows
**File**: `src/pflow/cli/main.py`

Location: Modify line 1366 caller and add display in `_prompt_workflow_save()`

1. In `_prompt_workflow_save()` after line 531:
```python
# Display rerun command after saving
# Note: execution_params passed as new parameter
```

2. Update function signature to accept execution_params
3. Update caller to pass execution_params

### Phase 5: Integration Testing
Create comprehensive tests in `tests/test_cli/test_rerun_display.py`

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|-------------------|
| Breaking save function callers | Only one caller found at line 1366 |
| Shell escaping edge cases | Use shlex.quote() for ALL values |
| Type conversion errors | Test all types from infer_type() |
| Display breaking piped output | Already protected by TTY check |

## Validation Strategy

- Unit tests for parameter formatting with all types
- Unit tests for command building
- Integration test for round-trip execution
- Verify displayed command parses identically

## Task Dependencies

1. Phase 1 can be done independently (new file)
2. Phase 2 must be done before Phase 4
3. Phase 3 can be done independently after Phase 1
4. Phase 4 depends on Phase 1 and Phase 2
5. Phase 5 depends on all previous phases

## Critical Decisions Made

1. **Use shlex.quote() for ALL values** - Safety over optimization
2. **Display WITHOUT "run" prefix** - Matches actual CLI usage
3. **Skip display for unsaved workflows** - Prevents user confusion
4. **Modify _prompt_workflow_save() signature** - Clean architecture
5. **Create new module for utilities** - Better organization and testability