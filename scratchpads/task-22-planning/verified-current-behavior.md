# Verified Current Behavior - Named Workflow Execution

## What Actually Works Right Now

After testing, here's the **actual** current behavior:

### ✅ Working:
1. **`pflow simple-test`** - Works for kebab-case workflow names
2. **`pflow existing param=value`** - Works for any name when parameters provided
3. **`pflow --file /path/to/workflow.json`** - Works for loading workflow files

### ❌ Not Working:
1. **`pflow existing`** - Single-word names without params go to planner
2. **`pflow simple-test.json`** - Adding .json extension goes to planner (not recognized)
3. **`pflow /path/to/workflow.json`** - Direct file paths not supported without --file
4. **Shell pipes after workflows** - Causes hang (confirmed bug)

### Execution Path When It Works:

```python
# When detected as workflow name:
1. is_likely_workflow_name() returns True
2. WorkflowManager.exists() checks ~/.pflow/workflows/
3. WorkflowManager.load_ir() loads the workflow
4. execute_json_workflow() runs it directly
5. NO planner involvement
```

## Key Issues to Address

### 1. **The .json Extension Problem**
Users naturally want to run workflows like:
- `pflow my-workflow.json` (from saved workflows)
- `pflow ./workflow.json` (from local files)

Currently neither works without `--file` flag.

### 2. **Input Validation Gap**
When a workflow executes:
- Parameters are passed raw as strings
- No validation against declared inputs
- No default values applied
- No type conversion

### 3. **Discovery Problem**
Users can't:
- See what workflows are available
- Know what parameters a workflow expects
- Get help for a specific workflow

### 4. **Shell Pipe Bug**
Any shell operations after workflow cause hang:
- `pflow workflow | grep something` - hangs
- `pflow workflow && echo done` - hangs
- `pflow workflow > output.txt` - hangs

## Revised Understanding

The feature is **more limited** than initially thought:
- Basic execution works for specific naming patterns
- But lacks critical usability features
- The .json extension issue is particularly problematic

## What Task 22 Should Actually Implement

### Phase 1: Core Functionality
1. **Support .json extension** for both saved and local workflows
2. **Connect input validation** from Task 21
3. **Apply default values** for optional inputs
4. **Add type conversion** for parameters

### Phase 2: Discovery & Help
1. **`pflow list`** - Show available workflows
2. **`pflow describe <workflow>`** - Show inputs/outputs
3. **Better error messages** with suggestions

### Phase 3: Enhanced Detection
1. **Improve heuristics** for single-word names
2. **Support file paths** without --file flag
3. **Consider explicit `pflow run`** command

### Shell Pipe Bug (Separate)
- This should be fixed in a separate task as you mentioned
- Likely related to how stdin/stdout is handled during execution