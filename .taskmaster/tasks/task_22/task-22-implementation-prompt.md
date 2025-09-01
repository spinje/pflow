# Task 22: Implement Named Workflow Execution - Agent Instructions

## The Problem You're Solving

Named workflow execution is already 70% implemented but buried under 200+ lines of unnecessary complexity. The current system requires the `--file` flag for loading workflow files, doesn't support `.json` extensions naturally, and has three separate code paths that all eventually call the same `execute_json_workflow()` function. Users can't easily discover or run their saved workflows, leading to confusion and poor user experience.

## Your Mission

Remove the `--file` flag entirely and implement unified workflow resolution that makes everything "just work" - whether users type `pflow my-workflow`, `pflow workflow.json`, or `pflow ./path/to/workflow.json`. This is about REMOVING complexity, not adding it.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_22/task-22.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built. Critically, it explains what's already working and what gaps need to be filled.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_22/starting-context/`

**Files to read (in this order):**
1. `task-22-spec.md` - The specification (FOLLOW THIS PRECISELY) - contains all requirements, test criteria, and validated function signatures

**Instructions**: Read EACH file listed above. The specification is the source of truth for requirements and test criteria. Follow it PRECISELY.

### 4. CRITICAL: Implementation Guide
**File**: `.taskmaster/tasks/task_22/implementation-guide.md`

**Purpose**: This document contains ALL the accumulated insights from extensive planning:
- The discovery that 70% is already implemented
- Exactly which 200 lines of code to DELETE
- Step-by-step implementation with actual code snippets
- Critical warnings (shell pipe bug, no fuzzy matching)
- All verified function signatures

**Why this is essential**: This guide contains discoveries and insights that took hours of investigation to uncover. It will save you from reimplementing what already exists.

## What You're Building

You're creating a radically simplified workflow execution system where users never think about HOW to specify their workflow. The key insight: whether it's a saved workflow, a file, or natural language, they all become JSON IR that gets executed the same way. So why have 3 different paths?

Example of the final UX:
```bash
# ALL of these will work naturally after your implementation:
pflow my-workflow                    # Saved workflow
pflow my-workflow.json               # Strips .json, finds saved
pflow workflow.json                  # Local file (detects .json)
pflow ./workflow.json                # Local file (detects path)
pflow /tmp/workflow.json             # Absolute path
pflow ~/workflows/test.json          # Expands ~

# With parameters - consistent everywhere:
pflow my-workflow input=data.csv
pflow workflow.json count=5 verbose=true
pflow ./local.json api_key=secret
```

## Key Outcomes You Must Achieve

### 1. Radical Simplification
- Delete ~200 lines of complex routing code
- Remove `--file` flag completely
- Create one unified resolution path
- Make the interface completely intuitive

### 2. Unified Workflow Resolution
- Single `resolve_workflow()` function handling all cases
- Support for .json extension and file paths
- Smart precedence: files → saved workflows → natural language
- Clear error messages with suggestions

### 3. Discovery Commands
- `pflow workflow list` - Show all saved workflows
- `pflow workflow describe <name>` - Show workflow interface
- User-friendly output with examples

## Implementation Strategy

### Phase 1: Core Resolution & Simplification (2-3 hours)

1. **Create resolve_workflow() function** in `src/pflow/cli/main.py`
   - Handle file paths (/ or .json indicators)
   - Try saved workflows (exact and without .json)
   - Return (workflow_ir, source) or (None, None)

2. **Update is_likely_workflow_name()** in `src/pflow/cli/main.py`
   - Add detection for .json extension
   - Add detection for file paths (contains /)
   - Keep existing kebab-case and parameter detection

3. **DELETE unnecessary functions** from `src/pflow/cli/main.py`
   - Remove `get_input_source()` (~45 lines)
   - Remove `_determine_workflow_source()` (~15 lines)
   - Remove `_determine_stdin_data()` (~35 lines)
   - Remove `process_file_workflow()` (~35 lines)
   - Remove `_execute_json_workflow_from_file()` (~35 lines)
   - Remove `_get_file_execution_params()` (~20 lines)

4. **Simplify workflow_command()** in `src/pflow/cli/main.py`
   - Replace complex branching with unified resolution
   - Use `prepare_inputs()` for validation
   - Apply defaults from validation
   - Single execution path

### Phase 2: Discovery Commands (1-2 hours)

1. **Create new file** `src/pflow/cli/workflow.py`
   - Add Click group for workflow commands
   - Implement `list` command using `WorkflowManager.list_all()`
   - Implement `describe` command showing inputs/outputs

2. **Update routing** in `src/pflow/cli/main_wrapper.py`
   - Add elif block for "workflow" command
   - Import and call workflow group

### Phase 3: Enhanced Error Messages (1 hour)

1. **Add similarity function** using existing substring pattern
2. **Improve error messages** with suggestions and guidance
3. **Handle edge cases** gracefully

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### The resolve_workflow() Function
This is the heart of the simplification. Here's the exact implementation to use:

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

### Verified Function Signatures (Use These Exactly)

```python
# WorkflowManager (verified to exist)
WorkflowManager().exists(name: str) -> bool
WorkflowManager().load_ir(name: str) -> dict[str, Any]
WorkflowManager().list_all() -> list[dict[str, Any]]

# Parameter Handling (verified to exist)
parse_workflow_params(args: tuple[str, ...]) -> dict[str, Any]
infer_type(value: str) -> Any  # Converts to bool/int/float/json/str

# Validation (verified to exist)
prepare_inputs(ir_dict: dict, params: dict) -> tuple[list, dict]
# Returns: (errors, defaults) where errors = [(message, path, suggestion), ...]

# Execution (verified to exist)
execute_json_workflow(ctx, ir_data, stdin_data, output_key, execution_params,
                     planner_llm_calls, output_format, metrics_collector)
```

### Storage and IR Structure
- Workflows stored at `~/.pflow/workflows/{name}.json`
- Saved with metadata wrapper containing: name, description, ir, created_at, updated_at, version
- Workflow IR has: ir_version (required), nodes (required), edges, inputs, outputs, enable_namespacing

## Critical Warnings from Experience

### 1. The Shell Pipe Bug - DO NOT FIX
**Issue**: Any shell operations after workflows cause hangs
```bash
pflow workflow | grep something  # HANGS - known bug
pflow workflow && echo done      # HANGS - known bug
```
**Action**: Leave this for a separate task. Just be aware during testing. Test without shell pipes.

### 2. Don't Add Fuzzy Matching
The codebase uses simple substring matching everywhere:
```python
similar = [n for n in all_names if name.lower() in n.lower()][:3]
```
Don't add difflib or Levenshtein distance - it's unnecessary complexity.

### 3. Don't Keep --file "For Compatibility"
We have ZERO users. This is the perfect time to break things for a better design. Remove it completely.

### 4. Don't Create Abstraction Layers
Use the existing functions directly:
- Call `WorkflowManager.load_ir()` directly - don't wrap it
- Use `parse_workflow_params()` as-is - don't create a new parser
- Use `prepare_inputs()` for validation - don't create custom validation

### 5. Parameter Validation Already Works
`prepare_inputs()` already validates against workflow input declarations, applies defaults, and returns errors. Don't reimplement this!

## Key Decisions Already Made

1. **Complete removal of --file flag** - Not deprecated, completely removed
2. **File path precedence over saved workflows** - Avoids ambiguity
3. **Simple substring matching** - No fuzzy matching libraries
4. **Reuse existing validation** - prepare_inputs() handles everything
5. **Reuse existing type conversion** - infer_type() already works
6. **Breaking changes are fine** - We have zero users

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple subagents won't edit the same files
2. **Identifies dependencies**: Discover what needs to be built in what order
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Current Routing Analysis**
   - Task: "Analyze src/pflow/cli/main.py and identify all the functions related to input source detection and workflow routing that need to be deleted"
   - Task: "Find all references to --file flag in the codebase and how it's currently used"

2. **Validation System Understanding**
   - Task: "Examine how prepare_inputs() in workflow_validator.py works and what it returns"
   - Task: "Understand how ValidationError is structured and displayed to users"

3. **Discovery Command Patterns**
   - Task: "Analyze src/pflow/cli/registry.py to understand the pattern for list and describe commands"
   - Task: "Check how main_wrapper.py routes to different command groups"

4. **Testing Patterns**
   - Task: "Examine tests/test_cli/ to understand CLI testing patterns with CliRunner"
   - Task: "Find existing tests for workflow execution to understand what needs updating"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_22/implementation/implementation-plan.md`

Your plan should detail:
- Exactly which lines/functions to delete
- Order of implementation to avoid breaking things
- Which tests need updating
- How to verify each step works

## Success Criteria

Your implementation is complete when:

- ✅ All these commands work naturally:
  - `pflow my-workflow` (saved workflow)
  - `pflow my-workflow.json` (strips extension)
  - `pflow ./workflow.json` (local file)
  - `pflow /tmp/workflow.json` (absolute path)
- ✅ Parameters work with validation and defaults
- ✅ Discovery commands work (`pflow workflow list`, `pflow workflow describe`)
- ✅ Error messages show helpful suggestions
- ✅ ~200 lines of code have been deleted
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ All test criteria from the spec pass

## Common Pitfalls to Avoid

1. **Don't overthink the design** - The implementation guide has exact code to use
2. **Don't add features not in spec** - No aliases, no versioning, no caching
3. **Don't create new abstractions** - Use existing functions directly
4. **Don't fix the shell pipe bug** - It's a separate task
5. **Don't keep --file flag** - Remove it completely

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_22/implementation/progress-log.md`

```markdown
# Task 22 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Create Implementation Plan (SECOND!)

Follow the detailed planning instructions to create a comprehensive plan before any coding.

### 2. Phase 1: Core Resolution
- Create resolve_workflow() function
- Update is_likely_workflow_name()
- DELETE the 6 unnecessary functions
- Simplify workflow_command()

### 3. Phase 2: Discovery Commands
- Create src/pflow/cli/workflow.py
- Update main_wrapper.py routing

### 4. Phase 3: Error Messages
- Add similarity suggestions
- Improve all error messages

### 5. Testing
- Update tests for removed --file flag
- Add tests for new resolution behavior
- Add tests for discovery commands

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to delete get_input_source() function...

Result: Function deleted successfully
- ✅ What worked: Removed lines 150-195
- ✅ Also deleted: _determine_workflow_source() helper
- 💡 Insight: These functions were doing complex detection that resolve_workflow() now handles in 30 lines

Code that replaced it:
```python
# Simple resolution in workflow_command()
if workflow:
    workflow_ir, source = resolve_workflow(workflow[0])
    if workflow_ir:
        # execute it
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: Delete process_file_workflow()
- Why it failed: Still referenced in two places
- New approach: Update references first, then delete
- Lesson: Always check references before deleting
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage.

**Core Principle**: "Test what users see"

For Task 22, focus on:
- **User-visible behavior**: Can they run workflows all the ways shown?
- **Error messages**: Are they helpful when things go wrong?
- **Discovery commands**: Do they show useful information?
- **Parameter handling**: Are params validated and defaults applied?

Example test:
```python
def test_json_extension_works():
    """User naturally types .json and it works."""
    result = runner.invoke(main, ["my-workflow.json"])
    assert result.exit_code == 0
    assert "Workflow executed successfully" in result.output
```

## What NOT to Do

- **DON'T** keep --file flag for "backward compatibility" - We have no users
- **DON'T** add fuzzy matching or new dependencies
- **DON'T** create wrapper functions around existing ones
- **DON'T** fix the shell pipe bug - It's a known issue for later
- **DON'T** add features like aliases or versioning
- **DON'T** modify the workflow IR structure
- **DON'T** change how workflows are stored

## Getting Started

1. Read all the context files to understand the full picture
2. Create your progress log file
3. Create a detailed implementation plan
4. Start with deleting code (Phase 1) - it's satisfying!
5. Run tests frequently: `pytest tests/test_cli/ -v`

## Final Notes

- This task is about REMOVING complexity, not adding it
- The system already does 70% of what we need
- Trust the implementation guide - it has working code
- When in doubt, choose the simpler approach
- Breaking changes are fine - we have no users

## Remember

You're implementing a feature that makes pflow dramatically simpler and more intuitive. The current system works but is buried under unnecessary complexity. Your job is to expose the elegant simplicity that's already there by deleting code and unifying paths.

The vision: Users should never think about HOW to specify their workflow. Whether they type `pflow my-workflow`, `pflow workflow.json`, or `pflow ./workflow.json`, it should just work.

Good luck! This implementation will make pflow feel magical - users just type what feels natural and it works. No flags, no special syntax, no manual reading. Think hard!