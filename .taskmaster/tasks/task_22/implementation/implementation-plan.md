# Task 22: Comprehensive Implementation Plan

## Executive Summary

This plan details the DELETION of ~200 lines of complex routing code and replacement with a simple 30-line unified resolution system. The key insight: 70% of named workflow execution already works - we're just removing the complexity that hides it.

## Phase 1: Core Resolution & Simplification (2-3 hours)

### 1.1 Delete Functions (FIRST - Most Satisfying!)

**File**: `src/pflow/cli/main.py`

Delete these entire functions:
1. **Lines 171-196**: `get_input_source()` - 25 lines
2. **Lines 96-113**: `_determine_workflow_source()` - 17 lines
3. **Lines 116-152**: `_determine_stdin_data()` - 36 lines
4. **Lines 1063-1111**: `process_file_workflow()` - 48 lines
5. **Lines 1012-1061**: `_execute_json_workflow_from_file()` - 49 lines
6. **Lines 901-921**: `_get_file_execution_params()` - 20 lines

**Total lines to delete**: ~195 lines

### 1.2 Remove --file Flag

**File**: `src/pflow/cli/main.py`

1. **Line 1695**: Remove the `@click.option("--file", "-f", type=str, help="Read workflow from file")` line
2. **Line 1721**: Remove `file: str | None,` parameter from workflow_command signature
3. Update function calls that reference `file` parameter throughout workflow_command

### 1.3 Create Unified Resolution Function

**File**: `src/pflow/cli/main.py`

Add near top of file (after imports, around line 90):

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

### 1.4 Update is_likely_workflow_name()

**File**: `src/pflow/cli/main.py`
**Location**: Lines 1648-1685

Update the function to detect .json and paths:

```python
def is_likely_workflow_name(text: str, remaining_args: tuple[str, ...]) -> bool:
    """Determine if text is likely a workflow name vs natural language."""
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

### 1.5 Simplify workflow_command()

**File**: `src/pflow/cli/main.py`
**Location**: Lines 1760-1828 (end of workflow_command function)

Replace the entire complex branching at the end with:

```python
# Around line 1760, DELETE everything from:
# stdin_data = get_stdin(...)
# source, raw_input, stdin_data = get_input_source(...)
#
# DELETE the entire if/elif/else branching
#
# REPLACE with:

# Handle stdin data
stdin_content, enhanced_stdin = get_stdin(quiet_stdin=output_format == "json")
stdin_data = enhanced_stdin if enhanced_stdin else stdin_content

# Simplified workflow resolution
if workflow and not " ".join(workflow).strip().count(" "):
    first_arg = workflow[0]
    if is_likely_workflow_name(first_arg, workflow[1:]):
        workflow_ir, source = resolve_workflow(first_arg)
        if workflow_ir:
            # Parse parameters
            params = parse_workflow_params(workflow[1:])

            # Validate with prepare_inputs
            errors, defaults = prepare_inputs(workflow_ir, params)
            if errors:
                # Show user-friendly errors
                for msg, path, suggestion in errors:
                    click.echo(f"❌ {msg}", err=True)
                    if path and path != "root":
                        click.echo(f"   At: {path}", err=True)
                    if suggestion:
                        click.echo(f"   👉 {suggestion}", err=True)
                ctx.exit(1)

            # Apply defaults
            if defaults:
                params.update(defaults)

            # Execute workflow
            execute_json_workflow(
                ctx, workflow_ir, stdin_data, output_key, params,
                None, output_format, metrics_collector
            )
            return

# Natural language fallback
raw_input = " ".join(workflow) if workflow else ""
_execute_with_planner(
    ctx, raw_input, stdin_data, output_key, verbose,
    "args", trace, planner_timeout
)
```

### 1.6 Add Error Helper Function

**File**: `src/pflow/cli/main.py`

Add near resolve_workflow():

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

Update error handling in workflow_command (add after `if workflow_ir:` check):

```python
# When workflow not found (add this after checking workflow_ir)
if not workflow_ir:
    wm = WorkflowManager()
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

## Phase 2: Discovery Commands (1-2 hours)

### 2.1 Create workflow.py Command File

**Create New File**: `src/pflow/cli/commands/workflow.py`

```python
"""Workflow management commands for pflow CLI."""

import json
import sys
import click
from pflow.core.workflow_manager import WorkflowManager


@click.group(name="workflow")
def workflow() -> None:
    """Manage saved workflows."""
    pass


@workflow.command(name="list")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_workflows(output_json: bool) -> None:
    """List all saved workflows."""
    wm = WorkflowManager()
    workflows = wm.list_all()

    if not workflows:
        click.echo("No workflows saved yet.\n")
        click.echo("To save a workflow:")
        click.echo('  1. Create one: pflow "your task"')
        click.echo('  2. Choose to save when prompted')
        return

    if output_json:
        click.echo(json.dumps(workflows, indent=2))
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
def describe_workflow(name: str) -> None:
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
        sys.exit(1)

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

### 2.2 Update Main Wrapper Routing

**File**: `src/pflow/cli/main_wrapper.py`

1. **Add import** (around line 22):
```python
from .commands.workflow import workflow
```

2. **Add routing** (after registry check, around line 53):
```python
elif first_arg == "workflow":
    # Route to Workflow group
    original_argv = sys.argv[:]
    try:
        workflow_index = sys.argv.index("workflow")
        sys.argv = [sys.argv[0]] + sys.argv[workflow_index + 1:]
        workflow()
    finally:
        sys.argv = original_argv
```

## Phase 3: Testing Strategy - Behavior Over Implementation (AFTER Implementation)

### Testing Philosophy
**Core Principle**: Test what users see and do, not how code works internally. Every test validates a real user journey.

### 3.1 Parameter Handling Tests
**Critical**: Parameters with type conversion and validation are core to the user experience.

- Users can pass parameters as key=value
- Types are automatically converted (string→int/bool/json)
- Required parameters are validated with helpful errors
- Optional parameters use defaults
- Error messages guide users to fix issues

### 3.2 Test Files to Create (Deploy Parallel Subagents AFTER Implementation)

1. **test_named_workflow_execution.py** - Core workflow resolution
   - Test all ways to specify workflows (.json, paths, saved names)
   - Verify parameters work with type conversion
   - Test missing workflows show suggestions
   - Test defaults are applied for optional params

2. **test_workflow_discovery.py** - Discovery commands
   - Test `pflow workflow list` output
   - Test `pflow workflow describe` shows interface
   - Test empty state guidance
   - Test suggestions for typos

3. **Update test_main.py** - Remove --file flag tests
   - Remove all tests using --file flag
   - Update any test expecting old behavior

### 3.3 Test Deployment Strategy
- Deploy test-writer-fixer agents in PARALLEL after implementation complete
- One agent per test file with clear, isolated instructions
- Focus on user behavior, NOT implementation details
- Each agent gets specific user scenarios to test

4. **test_file_flag_removal.py** - Verify --file is gone
   - Test that --file flag no longer exists
   - Test file paths work without flag

### 3.3 What NOT to Test
- Internal function signatures
- Private helper functions
- Mock-heavy unit tests
- Implementation details
- Code coverage for its own sake

## Phase 4: Verification

### 4.1 Run Tests
```bash
pytest tests/test_cli/ -xvs
```

### 4.2 Run Linting
```bash
make check
```

### 4.3 Manual Testing
Test all these scenarios:
```bash
pflow my-workflow                  # Saved workflow
pflow my-workflow.json             # With extension
pflow ./workflow.json              # Local file
pflow /tmp/workflow.json           # Absolute path
pflow ~/workflows/test.json        # Home expansion
pflow my-workflow input=value      # With parameters
pflow workflow list                # Discovery
pflow workflow describe my-flow    # Interface info
```

## Critical Implementation Order

1. **DELETE FIRST** - Remove all 6 functions and --file flag
2. **ADD resolve_workflow()** - The unified resolution
3. **UPDATE is_likely_workflow_name()** - Better detection
4. **SIMPLIFY workflow_command()** - Replace complex branching
5. **CREATE discovery commands** - New workflow.py file
6. **UPDATE routing** - main_wrapper.py changes
7. **TEST continuously** - Run tests after each step

## Risk Mitigation

- **Backup before deleting**: Create a git branch first
- **Test after each deletion**: Ensure nothing else breaks
- **Use real WorkflowManager**: Don't mock core functionality
- **Keep it simple**: Don't add features not in spec

## Success Metrics

✅ ~200 lines of code deleted
✅ All test scenarios pass
✅ `make test` passes
✅ `make check` passes
✅ Code is simpler and more intuitive

## Time Estimate

- Phase 1 (Core): 2-3 hours
- Phase 2 (Discovery): 1-2 hours
- Phase 3 (Testing): 1-2 hours (parallel)
- Phase 4 (Verification): 30 minutes

**Total**: 4-6 hours

## Notes

This implementation prioritizes DELETION over addition. The elegance comes from removing complexity, not adding features. When in doubt, delete more code!