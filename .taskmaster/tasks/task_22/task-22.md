# Task 22: Implement Named Workflow Execution

## ID
22

## Title
Implement Named Workflow Execution

## Description
Enable execution of saved workflows by name with parameters, supporting natural workflow invocation patterns like `pflow my-workflow param=value` and `pflow workflow.json`. This delivers the core "Plan Once, Run Forever" value proposition by making saved workflows easily executable.

## Status
in progress

## Dependencies
- Task 17: Natural Language Planner System - Provides workflow saving functionality that creates the workflows we'll execute by name
- Task 21: Workflow Input Declaration - Provides the input/output declarations and validation that we'll use for parameter validation
- Task 24: Workflow Manager - Provides the centralized service for loading/saving workflows that we'll use for resolution

## Priority
high

## Details
After extensive investigation, we discovered that named workflow execution is already 70% implemented but lacks critical usability features. The current system can execute workflows by name (`pflow my-workflow`) but has major gaps:

1. **Cannot use .json extension**: `pflow my-workflow.json` doesn't work
2. **Cannot use file paths directly**: `pflow ./workflow.json` requires `--file` flag
3. **Poor workflow name detection**: Single-word names without parameters go to planner
4. **No discovery commands**: Users can't list or describe available workflows
5. **Technical error messages**: Not user-friendly when workflows aren't found

### Radical Simplification Opportunity
We've identified that we can **remove the --file flag entirely** and create a unified workflow resolution system. Since we have zero users (MVP), this is the perfect time for this breaking change that will:
- Delete ~200 lines of complex routing code
- Create one simple resolution path for all workflows
- Make the interface completely intuitive

### Implementation Approach

#### Phase 1: Unified Workflow Resolution
Create a single `resolve_workflow()` function that handles:
- Saved workflows by name (`my-workflow`)
- Saved workflows with .json extension (`my-workflow.json`)
- Local file paths (`./workflow.json`, `/tmp/workflow.json`)
- Path expansion (`~/workflows/test.json`)

Resolution order:
1. If contains `/` or `.json` → Try as file path
2. Try exact name in saved workflows
3. Try name without .json in saved workflows
4. Return None if not found

#### Phase 2: Simplified Main Flow
Replace the current 3-way branching (file/named/args) with:
```python
if looks_like_direct_execution(input):
    workflow_ir, source = resolve_workflow(first_arg)
    if workflow_ir:
        params = parse_params(remaining_args)
        execute_workflow(workflow_ir, params)
        return
# Fall back to planner for natural language
```

#### Phase 3: Discovery Commands
Add new commands in `src/pflow/cli/workflow.py`:
- `pflow workflow list` - Show all saved workflows with descriptions
- `pflow workflow describe <name>` - Show workflow interface (inputs/outputs)

#### Phase 4: User-Friendly Error Messages
Implement helpful error messages with:
- Suggestions for similar workflow names
- Clear guidance when workflows aren't found
- Examples showing correct usage
- Smart detection of user intent

### Key Design Decisions
1. **Remove --file flag**: Everything works naturally without it
2. **Unified resolution**: One function handles all workflow loading
3. **Natural precedence**: Files → Saved workflows → Natural language
4. **Simple parameter syntax**: Keep key=value pattern everywhere

### Files to Modify
- `src/pflow/cli/main.py` - Remove complex routing, add unified resolution
- `src/pflow/cli/workflow.py` (new) - Discovery commands
- `src/pflow/cli/main_wrapper.py` - Add workflow command routing

### Files to Delete/Simplify
- Remove `get_input_source()` function
- Remove `process_file_workflow()` function
- Remove `_determine_workflow_source()` function
- Remove `_get_file_execution_params()` function
- Simplify main routing logic

## Test Strategy
Focus on testing user-visible behavior, not implementation details:

### Critical Behaviors to Test
1. **Resolution works all ways**:
   - `pflow my-workflow` (saved workflow)
   - `pflow my-workflow.json` (strips extension)
   - `pflow ./workflow.json` (local file)
   - `pflow /tmp/workflow.json` (absolute path)

2. **Parameters work correctly**:
   - Required parameters are validated
   - Default values are applied
   - Type conversion works (string → int/bool/json)
   - Error messages show what's needed

3. **Errors guide users**:
   - Not found → suggests similar workflows
   - Missing params → shows requirements with examples
   - Invalid types → shows expected format

4. **Discovery helps users**:
   - List shows all workflows with descriptions
   - Describe shows inputs, outputs, and examples
   - Empty state provides guidance

### Test Implementation Pattern
Use Click's CliRunner to test what users see:
```python
def test_workflow_with_json_extension():
    """User naturally types .json and it works."""
    result = runner.invoke(main, ["my-workflow.json"])
    assert result.exit_code == 0
    assert "Workflow executed successfully" in result.output
```

No need to test internal state - only test the user experience!