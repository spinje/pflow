# Supporting .json Extension - Design Thinking

## The Problem

Users naturally want to run workflows using .json extension:
```bash
# These should all work:
pflow my-workflow              # Saved workflow by name
pflow my-workflow.json         # Saved workflow with extension
pflow ./my-workflow.json       # Local file in current dir
pflow /tmp/workflow.json       # Absolute path to file
```

## Current Behavior Analysis

### How `is_likely_workflow_name()` Works:
```python
def is_likely_workflow_name(first_arg: str) -> bool:
    # Returns False for:
    - Contains spaces
    - Contains shell operators (|, >, <, &&)
    - Is a question
    - Is natural language

    # Returns True for:
    - Kebab-case (my-workflow)
    - Has parameters after it
```

The function doesn't consider `.json` extension at all!

## Design Options

### Option 1: Enhanced Detection Logic
Modify `is_likely_workflow_name()` to:
1. Strip `.json` extension before checking
2. Check if it's a file path (starts with ./ or / or contains /)
3. Try both saved workflow and file system

```python
def is_likely_workflow_name(first_arg: str) -> bool:
    # Check if it's a file path
    if first_arg.startswith('./') or first_arg.startswith('/') or '.json' in first_arg:
        return True  # Could be file or saved workflow with .json

    # Continue existing logic...
```

### Option 2: Unified Resolution Strategy
In `_try_direct_workflow_execution()`:
1. Try exact name in saved workflows
2. Try name without .json in saved workflows
3. Try as file path if contains / or .json
4. Fall back to planner

```python
def _try_direct_workflow_execution(workflow_args):
    name = workflow_args[0]

    # Try saved workflow (exact name)
    if wm.exists(name):
        return execute_saved_workflow(name)

    # Try saved workflow (strip .json)
    if name.endswith('.json'):
        base_name = name[:-5]
        if wm.exists(base_name):
            return execute_saved_workflow(base_name)

    # Try as file path
    if '/' in name or name.endswith('.json'):
        path = Path(name)
        if path.exists():
            return execute_file_workflow(path)

    return False  # Let planner handle it
```

### Option 3: Smart Resolution (Recommended)
Implement a `resolve_workflow()` function that handles all cases:

```python
def resolve_workflow(name: str) -> tuple[dict, str]:
    """
    Resolve a workflow name to its IR and source.

    Returns: (workflow_ir, source_type)
    source_type: 'saved' | 'file' | None
    """
    wm = WorkflowManager()

    # 1. Check saved workflows (exact match)
    if wm.exists(name):
        return wm.load_ir(name), 'saved'

    # 2. Check saved workflows (without .json)
    if name.endswith('.json'):
        base = name[:-5]
        if wm.exists(base):
            return wm.load_ir(base), 'saved'

    # 3. Check as file path
    if any(indicator in name for indicator in ['/', '.json']):
        path = Path(name).resolve()
        if path.exists() and path.suffix == '.json':
            with open(path) as f:
                data = json.load(f)
                # Handle both raw IR and metadata wrapper
                if 'ir' in data:
                    return data['ir'], 'file'
                return data, 'file'

    return None, None
```

## Implementation Strategy

### Step 1: Update Detection
Enhance `is_likely_workflow_name()` to recognize:
- Names with .json extension
- Paths (contain /)
- Keep existing kebab-case and parameter detection

### Step 2: Implement Resolution
Add workflow resolution that tries multiple strategies:
1. Exact name in saved workflows
2. Name without .json in saved workflows
3. Local file path
4. Return None if not found

### Step 3: Update Execution
Modify `_try_direct_workflow_execution()` to:
1. Use the new resolution logic
2. Handle both saved and file workflows
3. Provide clear error messages

## Benefits

This approach:
- Makes the CLI more intuitive
- Supports natural usage patterns
- Maintains backward compatibility
- Provides a clear resolution order

## Examples After Implementation

```bash
# All of these would work:
pflow my-workflow                    # Saved workflow
pflow my-workflow.json               # Same saved workflow
pflow ./workflows/test.json          # Local file
pflow /tmp/generated-workflow.json   # Absolute path

# With parameters:
pflow my-workflow.json input=data    # Works
pflow ./test.json param=value         # Works
```