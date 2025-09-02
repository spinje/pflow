# Task 53 Handoff: Rerun Command Display

## 🚨 Critical Discoveries - Read These First

### The "run" Prefix Trap
The original task documentation showed `pflow run analyzer` but **this is wrong**. The actual CLI uses `pflow analyzer` for saved workflows. The "run" prefix is optional and gets transparently stripped by `_preprocess_run_prefix()` in `/src/pflow/cli/main.py:1450-1462`.

**What you must do**: Display commands WITHOUT "run" prefix: `pflow workflow-name param=value`

### The `is_saved` Flag Doesn't Exist
The original spec assumed an `is_saved: bool` parameter. **This doesn't exist anywhere**. Instead:
- Use `workflow_source["found"]` to detect if an existing workflow was reused
- For new workflows, you must modify `_prompt_workflow_save()` to return `(was_saved: bool, workflow_name: str | None)`

### Parameter Values Are Real, Not Placeholders
The user explicitly wants to see the **actual parameter values** they used, not placeholders. These are available in `planner_output["execution_params"]` with the exact values extracted from their natural language input.

## 🎯 Core Implementation Points

### Where to Hook In

1. **For Reused Workflows**: `/src/pflow/cli/main.py:1358-1366`
   - After the line showing "✅ Reused existing workflow"
   - You have `workflow_name` from `workflow_source["workflow_name"]`
   - Display immediately after execution

2. **For New Workflows**: `/src/pflow/cli/main.py:486-546` in `_prompt_workflow_save()`
   - Modify function to return `(was_saved: bool, workflow_name: str | None)`
   - Display ONLY if user saves (was_saved=True)
   - Use the actual chosen name, not suggested_name

### The Data You Need

From `planner_output` dict:
```python
{
    "execution_params": dict[str, Any] | None,  # Actual parameter values (None on failure)
    "workflow_source": {
        "found": bool,                # True = reused, False = generated
        "workflow_name": str | None,  # Name if found, None if generated
        "confidence": float,
        "reasoning": str
    },
    "workflow_metadata": {
        "suggested_name": str,  # AI-generated name suggestion
        # ... other metadata
    }
}
```

### Parameter Type Conversion Rules

The CLI's `infer_type()` function (`/src/pflow/cli/main.py:1002-1039`) converts strings to Python types. You must **reverse** this:

```python
# Forward (CLI parsing)          # Reverse (for display)
"true"/"false" → bool           bool → "true"/"false" (lowercase!)
"42" → int                      int → "42"
"3.14" → float                  float → "3.14"
'["a","b"]' → list              list → json.dumps() with no spaces
'{"k":"v"}' → dict              dict → json.dumps() with no spaces
```

### Shell Escaping Strategy

Use `shlex.quote()` for **ALL** parameter values. It's already imported in `/src/pflow/mcp/manager.py:256` so there's precedent. This handles:
- Spaces: `hello world` → `'hello world'`
- Quotes: `She said "hi"` → `'She said "hi"'`
- Special chars: `$HOME` → `'$HOME'`

## ⚠️ Edge Cases and Gotchas

### When NOT to Display

1. **Unsaved workflows**: If user declines to save, don't display anything
2. **Missing data**: If `execution_params` is None or `workflow_source` is None, skip display
3. **Non-TTY**: The save prompt only appears in interactive terminals (`stdin.isatty() and stdout.isatty()`)

### The Parameter Parsing Round-Trip

The `parse_workflow_params()` function (`/src/pflow/cli/main.py:1042-1058`) expects:
- Simple split on first `=` only
- Type inference on the value part
- No shell processing (Click handles that before)

Your displayed command must survive: Shell → Click → parse_workflow_params → same params

### Empty Parameters Edge Case

- Empty dict `{}` → Display just `pflow workflow-name` (no parameters)
- Empty string value → Display as `key=''` (two single quotes)

## 🔗 Critical Files to Reference

1. **CLI Main Flow**: `/src/pflow/cli/main.py`
   - Lines 1329-1367: `_execute_successful_workflow()` - where reused workflows display
   - Lines 486-546: `_prompt_workflow_save()` - needs return value modification
   - Lines 1002-1039: `infer_type()` - type conversion logic to reverse
   - Lines 1042-1058: `parse_workflow_params()` - what your command must work with

2. **Planner Output Structure**: `/src/pflow/planning/nodes.py`
   - Lines 1724-1735: Complete `planner_output` structure
   - Lines 1233-1330: MetadataGenerationNode that creates suggested_name

3. **Test Examples**: `/tests/test_cli/test_direct_execution_helpers.py`
   - Shows all type inference test cases
   - Verify your parameter formatting works with these

## 💡 Patterns to Follow

### Display Format
```python
# After reused workflow execution:
click.echo("\n✨ Run again with:")
click.echo(f"  $ {formatted_command}")
click.echo("\n📖 Learn more:")
click.echo(f"  $ pflow workflow describe {workflow_name}")

# After saving new workflow:
click.echo(f"\n✅ Workflow saved as '{workflow_name}'")
# Then same display as above
```

### Existing CLI Patterns
- Success: `✅` prefix
- Commands: `✨` and `📖` prefixes
- Indentation: Two spaces for command examples
- Always include `$` in command examples

## 🐛 Subtle Issues Discovered

1. **The `run` prefix is silently accepted but not canonical** - Users might type either way, but we should show the clean version

2. **Parameter order matters** - Preserve the order from `execution_params` dict (Python 3.7+ guarantees dict order)

3. **Boolean case sensitivity** - The CLI accepts "TRUE"/"FALSE" but we should display lowercase "true"/"false" for consistency

4. **JSON formatting** - Use `json.dumps()` with `separators=(',', ':')` to avoid spaces in JSON output

## 📝 What Changed from Original Spec

I updated `/Users/andfal/projects/pflow-feat-rerun-command-display/.taskmaster/tasks/task_53/starting-context/task-53-spec.md` with:
- Removed "run" prefix from all examples
- Changed inputs to use `planner_output` dict structure
- Added requirement to modify `_prompt_workflow_save()` return value
- Clarified display timing for different scenarios
- Added complete `workflow_source` structure
- Fixed test criteria to match actual implementation

See `/Users/andfal/projects/pflow-feat-rerun-command-display/scratchpads/task-53-rerun-command/critical-findings.md` for a summary of all corrections.

## 🎬 Final Notes

**DO NOT** start implementing immediately. Read through the corrected spec, this handoff, and the referenced code sections first. The biggest risk is assuming the original task description is correct - it has several errors that I've corrected through codebase investigation.

When you're ready to implement:
1. Start by creating the parameter formatting utilities
2. Test them thoroughly with edge cases
3. Then integrate into the CLI flow
4. Verify round-trip execution works

Say "I'm ready to begin implementing Task 53" after you've absorbed this information.