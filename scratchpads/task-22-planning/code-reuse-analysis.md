# Code Reuse Analysis - Named vs File Workflows

## Current Duplication Analysis

### 1. **Parameter Handling Duplication**

**Named workflow** (`_try_direct_workflow_execution`, line 563):
```python
execution_params = parse_workflow_params(remaining_args)
```

**File workflow** (`_get_file_execution_params`, line 880):
```python
execution_params = parse_workflow_params(workflow_args)
```

Both do the same thing! They could share more code.

### 2. **Workflow Execution Path Duplication**

Both paths eventually call `execute_json_workflow()` with similar parameters:

**Named workflow** (line 572-581):
```python
execute_json_workflow(
    ctx, workflow_ir, stdin_data, output_key,
    execution_params, None, output_format, None
)
```

**File workflow** (line 989-998):
```python
execute_json_workflow(
    ctx, ir_data, stdin_data, output_key,
    execution_params, None, output_format, None
)
```

Identical! Just different variable names for the IR.

### 3. **JSON Loading Logic Scattered**

Currently we have:
- `WorkflowManager.load_ir()` for saved workflows
- `_parse_and_validate_json_workflow()` for file content
- Manual JSON parsing in `process_file_workflow()`

All doing similar JSON → IR conversion!

## Low-Hanging Fruit Opportunities

### Opportunity 1: Unified Workflow Resolution
Create ONE function that handles ALL workflow loading:

```python
def resolve_workflow(identifier: str, workflow_manager: WorkflowManager) -> tuple[dict, str]:
    """
    Resolve workflow from:
    1. Saved workflow name (exact match)
    2. Saved workflow name.json (strip extension)
    3. Local file path (./workflow.json or /path/to/workflow.json)

    Returns: (workflow_ir, source_type)
    """
    # Try saved workflow (exact)
    if workflow_manager.exists(identifier):
        return workflow_manager.load_ir(identifier), "saved"

    # Try saved workflow (strip .json)
    if identifier.endswith('.json'):
        name = identifier[:-5]
        if workflow_manager.exists(name):
            return workflow_manager.load_ir(name), "saved"

    # Try as file path
    if '/' in identifier or identifier.endswith('.json'):
        path = Path(identifier)
        if path.exists():
            content = path.read_text()
            ir_data = json.loads(content)
            # Handle wrapped vs raw IR
            if 'ir' in ir_data:
                return ir_data['ir'], "file"
            return ir_data, "file"

    return None, None
```

### Opportunity 2: Unified Parameter Extraction
Instead of having `_get_file_execution_params()` just for files:

```python
def extract_workflow_params(
    ctx: click.Context,
    args: tuple[str, ...],
    verbose: bool = False
) -> dict[str, Any]:
    """Extract parameters from command args, regardless of source."""
    params = parse_workflow_params(args)
    if params and verbose:
        click.echo(f"cli: With parameters: {params}")
    return params
```

### Opportunity 3: Simplify Main Execution Path
Instead of separate paths for file/named/args, we could have:

```python
def main():
    # ... setup ...

    # Try direct execution first (files or named workflows)
    if looks_like_direct_execution(workflow):
        workflow_ir, source = resolve_workflow(workflow[0], wm)
        if workflow_ir:
            params = extract_workflow_params(ctx, workflow[1:])
            execute_json_workflow(ctx, workflow_ir, stdin_data, params, ...)
            return

    # Fall back to planner for natural language
    _execute_with_planner(...)
```

### Opportunity 4: Remove --file Flag (Breaking but Simplifying)
Since we're building an MVP with no users, we could:
- Remove the `--file` flag entirely
- Make `pflow workflow.json` just work
- Simplify the entire input detection logic

This would eliminate:
- `get_input_source()` complexity
- `_determine_workflow_source()`
- Special file handling in `process_file_workflow()`

## Recommended Refactoring Strategy

### Phase 1: Core Resolution (Must Have)
1. **Create `resolve_workflow()`** - Handles all workflow loading
2. **Update `is_likely_workflow_name()`** - Detect .json and paths
3. **Simplify execution path** - One path for all direct execution

### Phase 2: Parameter Unification (Should Have)
1. **Unify parameter extraction** - One function for all sources
2. **Remove `_get_file_execution_params()`** - Use unified function

### Phase 3: Radical Simplification (Nice to Have)
1. **Consider removing --file flag** - Everything works naturally
2. **Merge `process_file_workflow()` into main flow** - Less branching
3. **Unify error handling** - One place for all workflow errors

## Benefits of Refactoring

1. **Less Code** - Remove ~100 lines of duplication
2. **Clearer Flow** - One path for workflow execution
3. **Better UX** - Users don't need to know about --file
4. **Easier Testing** - Test one resolution function, not multiple paths
5. **Natural Usage** - `pflow my-workflow.json` just works

## Risks and Mitigations

1. **Breaking Changes** - We're MVP, no users, so OK!
2. **Complexity** - Actually reducing complexity
3. **Edge Cases** - Unified resolution handles more cases

## Decision Point

Should we:
1. **Option A: Minimal Refactor** - Just add resolution function, keep --file
2. **Option B: Medium Refactor** - Unify resolution and parameters, keep --file
3. **Option C: Full Refactor** - Remove --file, unify everything

Given we're building an MVP with no users, I recommend **Option B or C** - we can make breaking changes now to get a cleaner architecture.