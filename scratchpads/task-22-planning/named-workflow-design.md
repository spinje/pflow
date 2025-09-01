# Named Workflow Execution - Design Specification

## Executive Summary

Task 22 enhances the **already partially implemented** named workflow execution to provide a complete, user-friendly experience with proper input validation, default values, and discovery capabilities.

## Current Implementation Status

### What Already Works
- `pflow my-workflow` - Executes saved workflow by name
- `pflow my-workflow key=value` - Pass parameters via key=value syntax
- Workflows saved to `~/.pflow/workflows/` via WorkflowManager
- Workflows can declare inputs/outputs in IR schema (Task 21)

### Critical Gaps
1. **No Input Validation** - Parameters aren't validated against declared inputs
2. **No Default Values** - Optional inputs don't use their defaults
3. **No Type Conversion** - All parameters remain as strings
4. **No Discovery** - Can't see what parameters a workflow expects
5. **Poor Error Messages** - Generic errors when workflow not found or params invalid

## Proposed Design

### 1. Enhanced Parameter Validation

When executing a named workflow, the system should:

```python
# Current flow (simplified)
def _try_direct_workflow_execution(workflow_args):
    name = workflow_args[0]
    params = parse_params(workflow_args[1:])  # Just key=value parsing
    workflow = load_workflow(name)
    execute(workflow, params)  # No validation!

# Enhanced flow
def _try_direct_workflow_execution(workflow_args):
    name = workflow_args[0]
    raw_params = parse_params(workflow_args[1:])
    workflow = load_workflow(name)

    # NEW: Validate and prepare inputs
    validated_params = prepare_inputs(
        workflow.inputs,  # Declared inputs
        raw_params,       # Provided params
        apply_defaults=True,
        convert_types=True
    )

    execute(workflow, validated_params)
```

### 2. CLI Interface Options

#### Option A: Keep Implicit Detection (Current)
```bash
# Single interface for everything
pflow my-workflow param1=value1 param2=value2
pflow "analyze this file"  # Falls back to planner
```

**Pros:**
- Simpler, more "magical" UX
- Backwards compatible
- Aligns with "CLI-first" philosophy

**Cons:**
- Ambiguous (is "analyze" a workflow or natural language?)
- Hard to improve heuristics without false positives

#### Option B: Add Explicit `run` Command
```bash
# Explicit command for named workflows
pflow run my-workflow param1=value1 param2=value2
pflow "analyze this file"  # Always goes to planner
```

**Pros:**
- Clear intent, no ambiguity
- Can add subcommands: `pflow run --list`, `pflow run --help my-workflow`
- Industry standard pattern (npm run, make run, etc.)

**Cons:**
- More verbose
- Breaking change for existing usage

#### Option C: Hybrid Approach (Recommended)
```bash
# Both work
pflow run my-workflow param1=value1    # Explicit
pflow my-workflow param1=value1        # Implicit (improved heuristics)

# Discovery commands
pflow list                              # List all workflows
pflow describe my-workflow              # Show inputs/outputs
```

### 3. Parameter Syntax Design

#### Current: Positional key=value
```bash
pflow my-workflow input_file=data.csv output_format=json verbose=true
```

#### Enhanced: Type-aware parsing
```bash
# Strings (default)
pflow my-workflow name="John Doe"

# Numbers
pflow my-workflow count=5 threshold=0.95

# Booleans
pflow my-workflow verbose=true debug=false

# JSON for complex types
pflow my-workflow items='["a","b","c"]' config='{"key":"value"}'

# Files (auto-detect and read)
pflow my-workflow data=@file.json
```

### 4. Help and Discovery System

#### Workflow Description Command
```bash
$ pflow describe fix-issue
Workflow: fix-issue
Description: Fixes a GitHub issue by creating a PR

Inputs:
  issue (required, string): GitHub issue number
  repo (optional, string): Repository name (default: current)
  branch (optional, string): Branch name (default: fix-issue-${issue})

Outputs:
  pr_url: URL of the created pull request

Example:
  pflow fix-issue issue=123 repo=myorg/myrepo
```

#### List Command
```bash
$ pflow list
Available workflows:
  fix-issue         - Fixes a GitHub issue by creating a PR
  analyze-code      - Analyzes code quality and suggests improvements
  deploy-staging    - Deploys application to staging environment

Run 'pflow describe <workflow>' for details
```

### 5. Error Handling

#### Missing Required Input
```bash
$ pflow fix-issue
Error: Missing required input 'issue'

This workflow requires:
  issue (string): GitHub issue number

Example:
  pflow fix-issue issue=123
```

#### Invalid Type
```bash
$ pflow analyze-code max_lines=abc
Error: Invalid value for 'max_lines': expected number, got 'abc'
```

#### Workflow Not Found
```bash
$ pflow unknown-workflow
Error: Workflow 'unknown-workflow' not found

Available workflows:
  fix-issue
  analyze-code

Did you mean to use natural language? Try:
  pflow "your request here"
```

## Implementation Plan

### Phase 1: Core Validation (Priority 1)
1. Enhance `_try_direct_workflow_execution()` to use `prepare_inputs()`
2. Connect to existing validation from `workflow_validator.py`
3. Apply default values for optional inputs
4. Add proper error messages with input descriptions

### Phase 2: Discovery Commands (Priority 2)
1. Add `pflow list` command to show saved workflows
2. Add `pflow describe <name>` to show workflow interface
3. Enhance error messages to suggest available workflows

### Phase 3: Type System (Priority 3)
1. Implement type conversion in parameter parsing
2. Support JSON values for complex types
3. Add file reading with `@file` syntax

### Phase 4: Explicit Commands (Future)
1. Add `pflow run` as alternative interface
2. Consider `pflow delete` for workflow management
3. Add `pflow rename` for workflow updates

## Technical Details

### Files to Modify

1. **`src/pflow/cli/main.py`**
   - Enhance `_try_direct_workflow_execution()`
   - Add input validation using `prepare_inputs()`
   - Improve error messages

2. **`src/pflow/cli/commands.py`** (new)
   - Add `list` command
   - Add `describe` command

3. **`src/pflow/cli/param_parser.py`** (enhance)
   - Add type conversion logic
   - Support JSON parsing
   - Handle file references

### Testing Strategy

1. **Unit Tests**
   - Parameter parsing with types
   - Input validation logic
   - Default value application

2. **Integration Tests**
   - Full workflow execution with parameters
   - Error cases (missing inputs, wrong types)
   - Discovery commands

3. **E2E Tests**
   - Save workflow → Execute by name → Verify output
   - Complex parameter types
   - Error recovery

## Open Questions

1. **Parameter Syntax**: Should we support `--param=value` (GNU-style) in addition to `param=value`?

2. **Single Word Names**: Should `pflow analyze` try to find an "analyze" workflow, or always go to planner?

3. **Update Semantics**: When saving a workflow with an existing name, overwrite or version?

4. **Aliases**: Should we support workflow aliases? (e.g., `fi` → `fix-issue`)

## Recommendation

Start with **Phase 1** (Core Validation) as it provides immediate value with minimal changes. This connects the existing input declaration system (Task 21) with the existing execution path, providing the core value proposition of validated, typed workflow execution.

Then move to **Phase 2** (Discovery) to improve usability. Phases 3 and 4 can be deferred as they're nice-to-have enhancements.