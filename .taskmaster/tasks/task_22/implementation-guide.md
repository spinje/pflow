# Task 22: Named Workflow Execution - Comprehensive Implementation Guide

## Executive Summary: The Hidden Opportunity

**Critical Discovery**: Named workflow execution is already 70% implemented but buried under 200+ lines of unnecessary complexity. The current system has three separate code paths (file/named/args) that all eventually call the same `execute_json_workflow()` function. By removing the `--file` flag and creating a unified resolution system, we can delete massive amounts of code while making the interface MORE intuitive.

**The Vision**: Users should never think about HOW to specify their workflow. Whether they type `pflow my-workflow`, `pflow workflow.json`, or `pflow ./path/to/workflow.json`, it should just work.

## Current State: What Actually Works (Surprising Discoveries)

### Already Working Features (Hidden Gems)
1. **Parameter validation** - `prepare_inputs()` already validates against workflow input declarations
2. **Type conversion** - `infer_type()` already converts strings to bool/int/float/JSON
3. **Default values** - Already applied for optional parameters
4. **Basic execution** - `pflow my-workflow param=value` works for kebab-case names
5. **WorkflowManager** - Complete implementation with save/load/list/exists/delete

### What Doesn't Work (The Gaps)
1. **Cannot use .json extension** - `pflow my-workflow.json` goes to planner
2. **Cannot use file paths directly** - `pflow ./workflow.json` requires --file flag
3. **Poor detection** - Single words like `pflow analyze` go to planner
4. **No discovery** - Can't list or describe workflows
5. **Technical errors** - Not user-friendly

### The Duplication Problem
```python
# THREE separate paths doing the same thing:

# Path 1: Named workflows
_try_direct_workflow_execution() → parse_workflow_params() → execute_json_workflow()

# Path 2: File workflows
process_file_workflow() → _get_file_execution_params() → execute_json_workflow()

# Path 3: Planner
_execute_with_planner() → (generates IR) → execute_json_workflow()
```

## The Radical Simplification: Remove --file Completely

### Why This is Perfect for MVP
- **Zero users** = No backward compatibility concerns
- **Simpler is better** = Less code, fewer bugs
- **Natural UX** = Users don't learn flags, they just use it
- **Clear mental model** = "It just works"

### Code Deletion Festival 🎉
**Delete these functions entirely:**
- `get_input_source()` - 45 lines
- `_determine_workflow_source()` - 15 lines
- `_determine_stdin_data()` - 35 lines
- `process_file_workflow()` - 35 lines
- `_execute_json_workflow_from_file()` - 35 lines
- `_get_file_execution_params()` - 20 lines
- Various validation logic - 20 lines

**Total: ~200 lines deleted!**

### What Replaces It (60 lines total)
```python
def resolve_workflow(identifier: str, wm: WorkflowManager) -> tuple[dict, str]:
    """One function to rule them all."""
    # 1. File path detection (/ or .json)
    if '/' in identifier or identifier.endswith('.json'):
        path = Path(identifier).expanduser().resolve()
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                # Handle both raw IR and wrapped format
                if 'ir' in data:
                    return data['ir'], 'file'
                return data, 'file'

    # 2. Saved workflow (exact match)
    if wm.exists(identifier):
        return wm.load_ir(identifier), 'saved'

    # 3. Saved workflow (strip .json)
    if identifier.endswith('.json'):
        name = identifier[:-5]
        if wm.exists(name):
            return wm.load_ir(name), 'saved'

    return None, None
```

## Implementation Roadmap

### Phase 1: Core Resolution (2-3 hours)

#### Step 1: Create resolve_workflow()
Location: `src/pflow/cli/main.py` (add near top with other helpers)

```python
def resolve_workflow(identifier: str, wm: WorkflowManager | None = None) -> tuple[dict | None, str]:
    """Resolve workflow from file path or saved name.

    Resolution order:
    1. File paths (contains / or ends with .json)
    2. Exact saved workflow name
    3. Saved workflow without .json extension

    Returns:
        (workflow_ir, source) where source is 'file', 'saved', or None
    """
    if not wm:
        wm = WorkflowManager()

    # [Implementation from above]
```

#### Step 2: Update is_likely_workflow_name()
Make it detect .json and paths:

```python
def is_likely_workflow_name(text: str, remaining_args: tuple[str, ...]) -> bool:
    if not text or " " in text:
        return False

    # NEW: Detect file paths and .json
    if '/' in text or text.endswith('.json'):
        return True

    # Existing logic for params and kebab-case
    if remaining_args and any("=" in arg for arg in remaining_args):
        return True
    if "-" in text and not text.startswith("--"):
        return True

    return False
```

#### Step 3: Simplify workflow_command()
Replace the complex branching at the end with:

```python
# Remove ALL of this:
# - get_input_source() call
# - if source in ("file", "stdin") branch
# - process_file_workflow() call

# Replace with:
if workflow and not " ".join(workflow).strip().count(" "):
    # Try direct execution
    first_arg = workflow[0]
    if is_likely_workflow_name(first_arg, workflow[1:]):
        workflow_ir, source = resolve_workflow(first_arg)
        if workflow_ir:
            params = parse_workflow_params(workflow[1:])
            # Validate with prepare_inputs
            errors, defaults = prepare_inputs(workflow_ir, params)
            if errors:
                # Show user-friendly error
                for msg, path, suggestion in errors:
                    click.echo(f"❌ {msg}", err=True)
                    if suggestion:
                        click.echo(f"👉 {suggestion}", err=True)
                ctx.exit(1)

            # Apply defaults
            if defaults:
                params.update(defaults)

            # Execute
            execute_json_workflow(ctx, workflow_ir, stdin_data, output_key, params, ...)
            return

# Natural language fallback
raw_input = " ".join(workflow)
_execute_with_planner(ctx, raw_input, stdin_data, output_key, verbose, "args", trace, planner_timeout)
```

### Phase 2: Discovery Commands (1-2 hours)

#### Step 1: Create workflow.py
New file: `src/pflow/cli/workflow.py`

```python
import click
from pflow.core.workflow_manager import WorkflowManager

@click.group(name="workflow")
def workflow():
    """Manage saved workflows."""
    pass

@workflow.command(name="list")
@click.option("--json", is_flag=True, help="Output as JSON")
def list_workflows(json: bool):
    """List all saved workflows."""
    wm = WorkflowManager()
    workflows = wm.list_all()

    if not workflows:
        click.echo("No workflows saved yet.\n")
        click.echo("To save a workflow:")
        click.echo('  1. Create one: pflow "your task"')
        click.echo('  2. Choose to save when prompted')
        return

    if json:
        import json as json_lib
        click.echo(json_lib.dumps(workflows, indent=2))
    else:
        click.echo("Saved Workflows:")
        click.echo("─" * 40)
        for wf in workflows:
            name = wf['name']
            desc = wf.get('description', 'No description')
            click.echo(f"\n{name}")
            click.echo(f"  {desc}")
        click.echo(f"\nTotal: {len(workflows)} workflows")

@workflow.command(name="describe")
@click.argument("name")
def describe_workflow(name: str):
    """Show workflow interface."""
    wm = WorkflowManager()
    if not wm.exists(name):
        # Show suggestions
        all_names = [w['name'] for w in wm.list_all()]
        similar = [n for n in all_names if name.lower() in n.lower()][:3]

        click.echo(f"❌ Workflow '{name}' not found.", err=True)
        if similar:
            click.echo("\nDid you mean:", err=True)
            for s in similar:
                click.echo(f"  - {s}", err=True)
        ctx.exit(1)

    # Load and display
    metadata = wm.load(name)
    ir = metadata['ir']

    click.echo(f"Workflow: {name}")
    click.echo(f"Description: {metadata.get('description', 'No description')}")

    # Show inputs
    if 'inputs' in ir and ir['inputs']:
        click.echo("\nInputs:")
        for input_name, config in ir['inputs'].items():
            required = config.get('required', True)
            req_text = "required" if required else "optional"
            desc = config.get('description', '')
            default = config.get('default')

            click.echo(f"  - {input_name} ({req_text}): {desc}")
            if default is not None:
                click.echo(f"    Default: {default}")
    else:
        click.echo("\nInputs: None")

    # Show outputs
    if 'outputs' in ir and ir['outputs']:
        click.echo("\nOutputs:")
        for output_name, config in ir['outputs'].items():
            desc = config.get('description', '')
            click.echo(f"  - {output_name}: {desc}")
    else:
        click.echo("\nOutputs: None")

    # Show example
    click.echo(f"\nExample Usage:")
    example_params = []
    if 'inputs' in ir:
        for input_name, config in ir['inputs'].items():
            if config.get('required', True):
                example_params.append(f"{input_name}=<value>")

    if example_params:
        click.echo(f"  pflow {name} {' '.join(example_params)}")
    else:
        click.echo(f"  pflow {name}")
```

#### Step 2: Update main_wrapper.py
Add routing for workflow command:

```python
# In main() function, add after registry check:
elif first_arg == "workflow":
    from pflow.cli.workflow import workflow
    original_argv = sys.argv[:]
    try:
        workflow_index = sys.argv.index("workflow")
        sys.argv = [sys.argv[0]] + sys.argv[workflow_index + 1:]
        workflow()
    finally:
        sys.argv = original_argv
```

### Phase 3: Enhanced Error Messages

Add helper for similarity:

```python
def find_similar_workflows(name: str, wm: WorkflowManager, max_results: int = 3) -> list[str]:
    """Find similar workflow names using substring matching."""
    all_names = [w['name'] for w in wm.list_all()]
    # Simple substring matching (existing pattern)
    matches = [n for n in all_names if name.lower() in n.lower()]
    if not matches:
        # Try reverse
        matches = [n for n in all_names if n.lower() in name.lower()]
    return matches[:max_results]
```

Update error handling in resolve_workflow:

```python
# When workflow not found
if not workflow_ir:
    similar = find_similar_workflows(first_arg, wm)
    click.echo(f"❌ Workflow '{first_arg}' not found.", err=True)

    if similar:
        click.echo("\nDid you mean one of these?", err=True)
        for name in similar:
            click.echo(f"  - {name}", err=True)
    else:
        click.echo("\nUse 'pflow workflow list' to see available workflows.", err=True)
        click.echo("Or use quotes for natural language: pflow \"your request\"", err=True)

    ctx.exit(1)
```

## Critical Warnings ⚠️

### 1. The Shell Pipe Bug (DO NOT FIX)
**Issue**: Any shell operations after workflows cause hangs
```bash
pflow workflow | grep something  # HANGS
pflow workflow && echo done      # HANGS
```
**Action**: Leave this for a separate task. Just be aware during testing.

### 2. Don't Add Fuzzy Matching
The codebase uses simple substring matching everywhere. Don't add difflib or Levenshtein distance - it's unnecessary complexity.

### 3. Don't Keep --file "For Compatibility"
We have ZERO users. This is the perfect time to break things for a better design.

### 4. Don't Create Abstraction Layers
Use the existing functions directly:
- `WorkflowManager.load_ir()` - Don't wrap it
- `parse_workflow_params()` - Don't create a new parser
- `prepare_inputs()` - Don't create custom validation

## Code Patterns to Follow

### Error Message Pattern (from existing CLI)
```python
# User-friendly with emoji
click.echo("❌ Error: Description", err=True)
click.echo("👉 Suggestion: Action", err=True)

# Technical with details
click.echo(f"cli: Error - {details}", err=True)
if verbose:
    click.echo(f"cli: Debug info: {more}", err=True)
```

### Command Group Pattern (from registry.py)
```python
@click.group(name="command")
def command():
    """Command description."""
    pass

@command.command(name="subcommand")
@click.option("--json", is_flag=True)
def subcommand(json: bool):
    """Subcommand description."""
    # Implementation
```

### Validation Pattern (from compiler.py)
```python
errors, defaults = prepare_inputs(ir_dict, params)
if errors:
    # Handle all errors
    for message, path, suggestion in errors:
        # Show error
    ctx.exit(1)

# Apply defaults
if defaults:
    params.update(defaults)
```

## Testing Strategy: Behavior Over Implementation

### Critical Behaviors to Test

```python
def test_json_extension_works():
    """User naturally types .json and it works."""
    result = runner.invoke(main, ["my-workflow.json"])
    assert result.exit_code == 0
    assert "Workflow executed successfully" in result.output

def test_file_path_works():
    """Local file paths work without --file."""
    result = runner.invoke(main, ["./workflow.json"])
    assert result.exit_code == 0

def test_missing_required_param_shows_help():
    """Missing params show what's needed."""
    result = runner.invoke(main, ["my-workflow"])
    assert "❌" in result.output
    assert "required" in result.output.lower()
    assert "input_file" in result.output  # The actual param name

def test_workflow_not_found_suggests():
    """Not found shows similar names."""
    result = runner.invoke(main, ["analize-code"])  # Typo
    assert "Did you mean" in result.output
    assert "analyze-code" in result.output

def test_list_empty_shows_guidance():
    """Empty list helps users."""
    result = runner.invoke(main, ["workflow", "list"])
    assert "No workflows saved yet" in result.output
    assert "To save a workflow:" in result.output
```

### What NOT to Test
- Internal state changes
- Private functions
- Implementation details
- Mock heavy unit tests
- Coverage for coverage's sake

## Migration Impact (Breaking Changes)

### What Breaks
```bash
# Old (broken)
pflow --file workflow.json

# New (works)
pflow workflow.json

# Everything else unchanged
pflow my-workflow param=value  # Still works
```

### User Communication
Since we have no users, just update the docs. But if we did:
```
BREAKING: Removed --file flag. Just use: pflow workflow.json
The interface is now simpler - workflows work however you specify them.
```

## Key Functions Quick Reference

All verified to exist with exact signatures:

```python
# Workflow Management
WorkflowManager().exists(name: str) -> bool
WorkflowManager().load_ir(name: str) -> dict[str, Any]
WorkflowManager().list_all() -> list[dict[str, Any]]
WorkflowManager().load(name: str) -> dict[str, Any]  # Full metadata

# Parameter Handling
parse_workflow_params(args: tuple[str, ...]) -> dict[str, Any]
infer_type(value: str) -> Any  # Converts to bool/int/float/json/str

# Validation
prepare_inputs(ir_dict: dict, params: dict) -> tuple[list, dict]
# Returns: (errors, defaults) where errors = [(message, path, suggestion), ...]

# Execution
execute_json_workflow(ctx, ir_data, stdin_data, output_key, execution_params,
                     planner_llm_calls, output_format, metrics_collector)

# Stdin Handling
_inject_stdin_data(shared_storage: dict, stdin_data: str | StdinData | None, verbose: bool)
```

## Success Checklist

After implementation, these should all work:

✅ **Resolution Works**
```bash
pflow my-workflow                  # Saved workflow
pflow my-workflow.json             # With extension
pflow ./workflow.json              # Local file
pflow /tmp/workflow.json           # Absolute path
pflow ~/workflows/test.json        # Home expansion
```

✅ **Parameters Work**
```bash
pflow my-workflow input=data.csv verbose=true count=5
# Types converted, defaults applied, validation runs
```

✅ **Discovery Works**
```bash
pflow workflow list                # Shows all
pflow workflow describe my-flow    # Shows interface
```

✅ **Errors Guide Users**
```bash
pflow unknown                      # Suggests similar
pflow workflow                     # Shows missing params
pflow workflow bad=value           # Shows validation error
```

✅ **Code is Simpler**
- 200 lines deleted
- One resolution path
- Clear, obvious flow

## Final Wisdom

This task is about REMOVING complexity, not adding it. The system already does 70% of what we need - we're just exposing it better and removing the cruft that hides it.

When in doubt:
1. Delete rather than refactor
2. Use existing functions rather than create new ones
3. Test what users see, not what code does
4. Break things boldly (we have no users!)

The end result should feel magical - users just type what feels natural and it works. No flags, no special syntax, no manual reading. Just: `pflow my-workflow` and it runs.