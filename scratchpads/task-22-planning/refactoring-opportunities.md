# Refactoring Opportunities - Code Reuse Analysis

## Current Duplication

### Path 1: Named Workflow Execution
```python
# _try_direct_workflow_execution() - lines 1548-1605
1. Load workflow: wm.load_ir(name)
2. Parse params: parse_workflow_params(remaining_args)
3. Execute: execute_json_workflow(ctx, ir, stdin_data, output_key, params, ...)
```

### Path 2: File Workflow Execution
```python
# process_file_workflow() → _execute_json_workflow_from_file() - lines 975-1000
1. Load workflow: json.loads(file_content)
2. Parse params: _get_file_execution_params(ctx) → parse_workflow_params()
3. Execute: execute_json_workflow(ctx, ir, stdin_data, output_key, params, ...)
```

**They're doing THE SAME THING!** Just getting the IR from different sources.

## Unified Approach

### Single Resolution + Execution Path

```python
def resolve_workflow_ir(identifier: str) -> tuple[dict, str]:
    """
    Resolve workflow from any source.
    Returns: (workflow_ir, source_type)
    """
    # Try saved workflow (exact name)
    if wm.exists(identifier):
        return wm.load_ir(identifier), "saved"

    # Try without .json extension
    if identifier.endswith('.json'):
        base_name = identifier[:-5]
        if wm.exists(base_name):
            return wm.load_ir(base_name), "saved"

    # Try as file path
    if '/' in identifier or identifier.endswith('.json'):
        path = Path(identifier)
        if path.exists():
            content = path.read_text()
            data = json.loads(content)
            # Handle metadata wrapper
            if 'ir' in data:
                return data['ir'], "file"
            return data, "file"

    return None, None

def execute_workflow(
    ctx: click.Context,
    identifier: str,
    params: dict[str, Any],
    stdin_data: Any = None,
) -> None:
    """
    Single execution path for ALL workflows.
    """
    # Resolve the workflow
    workflow_ir, source = resolve_workflow_ir(identifier)

    if not workflow_ir:
        # Handle not found error
        raise click.ClickException(f"Workflow '{identifier}' not found")

    if ctx.obj.get("verbose"):
        click.echo(f"cli: Loading workflow from {source}")

    # Execute with unified path
    execute_json_workflow(
        ctx,
        workflow_ir,
        stdin_data,
        ctx.obj.get("output_key"),
        params,
        None,  # planner_llm_calls
        ctx.obj.get("output_format", "text"),
        None,  # metrics_collector
    )
```

## Refactoring Benefits

### Before: Two Separate Paths
```
User Input → Detect Type → Named Path → Load → Parse Params → Execute
         ↓              ↘ File Path  → Load → Parse Params → Execute
    --file flag
```

### After: Single Unified Path
```
User Input → Resolve Workflow → Parse Params → Execute
  (any format)     ↑
              (handles all sources)
```

## What We Can Remove/Simplify

1. **Merge `_try_direct_workflow_execution()` and `_execute_json_workflow_from_file()`**
   - They're doing the same thing!

2. **Simplify `process_file_workflow()`**
   - Just becomes a thin wrapper that calls our unified execution

3. **Remove `_get_file_execution_params()`**
   - Just use `parse_workflow_params()` directly

4. **Unify parameter handling**
   - Both paths parse params the same way
   - Move to single location

## Implementation Strategy

### Step 1: Create Unified Resolution
```python
def resolve_and_execute_workflow(
    ctx: click.Context,
    workflow_args: tuple[str, ...],
    use_file_flag: bool = False,
) -> bool:
    """
    Unified workflow execution.
    Returns True if executed, False to fall back to planner.
    """
    if not workflow_args:
        return False

    identifier = workflow_args[0]
    params = parse_workflow_params(workflow_args[1:])

    # If --file flag used, only try file
    if use_file_flag:
        workflow_ir = load_file_workflow(identifier)
    else:
        # Try all resolution strategies
        workflow_ir, source = resolve_workflow_ir(identifier)

    if workflow_ir:
        execute_workflow(ctx, workflow_ir, params, ctx.obj.get("stdin_data"))
        return True

    return False  # Fall back to planner
```

### Step 2: Update Main Command
```python
def main(file, workflow, ...):
    if file:
        # Use file path directly
        resolve_and_execute_workflow(ctx, (file,) + workflow, use_file_flag=True)
    elif workflow:
        # Try smart resolution
        if not resolve_and_execute_workflow(ctx, workflow):
            # Fall back to planner
            process_natural_language(workflow)
```

## Low-Hanging Fruit

1. **Parameter parsing** - Already shared via `parse_workflow_params()`
2. **Execution** - Already shared via `execute_json_workflow()`
3. **Workflow loading** - Can be unified (main opportunity!)
4. **Error handling** - Can be unified
5. **Verbose logging** - Can be unified

## Breaking Changes (OK for MVP)

This refactoring would change:
- How `--file` flag works internally (but not user-facing)
- Some error messages might change slightly
- Internal code structure

Since we have **no users**, this is the perfect time to clean this up!

## Benefits

1. **Less code** - Remove ~100 lines of duplication
2. **Single source of truth** - One place to update workflow execution
3. **Easier to extend** - Add new resolution strategies in one place
4. **Better testing** - Test one path instead of two
5. **Cleaner architecture** - Clear separation of concerns