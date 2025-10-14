# Summary: Planner Execution Control Fix

## The Problem

Currently, the planner executes for ANY input that isn't a recognized workflow or file. This means:

```bash
pflow "do something"         # ✅ SHOULD work → currently works
pflow lets do this thing     # ❌ SHOULD error → currently goes to planner
pflow jkahsd "do something"  # ❌ SHOULD error → currently goes to planner
pflow random                 # ❌ SHOULD error → currently goes to planner
```

## Root Cause

The CLI uses a "fallback" approach at the end of `workflow_command()`:

1. Try to execute as named/file workflow
2. Try to handle as single word
3. **Fallback: Everything else goes to planner** ← THIS IS THE PROBLEM

## How Shell Quotes Work

The shell processes quotes BEFORE Click sees arguments:

```bash
# Shell turns these into:
pflow "do something"              → workflow=("do something",)           # 1 arg with spaces
pflow lets do this                → workflow=("lets", "do", "this")      # 3 args
pflow jkahsd "do something"       → workflow=("jkahsd", "do something")  # 2 args
```

**Key insight:** A quoted string becomes ONE argument WITH spaces. Multiple words become MULTIPLE arguments.

## The Fix

Replace "fallback to planner" with **explicit validation**:

```python
# BEFORE (current)
# ... try named workflow ...
# ... try single word ...
_execute_with_planner(ctx, raw_input, ...)  # Everything else

# AFTER (fixed)
# ... try named workflow ...
if not _is_valid_natural_language_input(workflow):
    _handle_invalid_planner_input(ctx, workflow)  # Show clear error
    return

_execute_with_planner(ctx, raw_input, ...)  # Only valid input
```

Where `_is_valid_natural_language_input()` checks:
- Must be exactly 1 argument: `len(workflow) == 1`
- Must contain spaces: `" " in workflow[0]` (was quoted)
- Not a file path: defensive check

## Expected Behavior After Fix

### Valid Cases (Unchanged)
```bash
pflow "natural language prompt"   # ✅ Goes to planner
pflow workflow.json               # ✅ Executes file
pflow my-workflow input=value     # ✅ Executes saved workflow
pflow registry list               # ✅ Routes to subcommand
```

### Invalid Cases (Now Show Errors)
```bash
pflow lets do this thing
# ❌ Invalid input: lets do ...
# Natural language prompts must be quoted:
#   pflow "lets do this thing"

pflow jkahsd "do something"
# ❌ Invalid input: jkahsd do something ...
# Natural language prompts must be quoted:
#   pflow "jkahsd do something"

pflow random
# ❌ 'random' is not a known workflow or command.
# Did you mean:
#   pflow "random <rest of prompt>"    # Use quotes
#   pflow workflow list                # List workflows
```

## Implementation Changes

**Files to modify:**
- `src/pflow/cli/main.py` - Add validation, modify flow, improve error messages

**New functions:**
- `_is_valid_natural_language_input()` - Validates input structure
- `_handle_invalid_planner_input()` - Shows helpful errors

**Modified functions:**
- `workflow_command()` - Add validation before planner execution
- `_validate_and_prepare_natural_language_input()` - Simplify (validation moved upstream)

**Removed functions:**
- `_handle_single_token_workflow()` - No longer needed (validation catches this)

## Testing Strategy

1. **Unit tests:** Test validation logic directly
2. **Integration tests:** Test CLI behavior with various inputs
3. **Manual testing:** Verify error messages are helpful

## Why This Is Safe

- We have no production users (MVP phase)
- Current behavior wastes API calls on invalid input
- Error messages guide users to correct syntax
- Valid use cases remain unchanged

## Next Steps

1. Review this understanding and plan
2. Implement the changes
3. Add comprehensive tests
4. Verify all edge cases work correctly

