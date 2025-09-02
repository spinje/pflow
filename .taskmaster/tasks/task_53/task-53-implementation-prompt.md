# Task 53: Add Rerun Command Display - Agent Instructions

## The Problem You're Solving

After users create or discover workflows through natural language, they have no way to re-execute them without going through the planner again. This creates a dependency on AI for every execution and prevents users from learning the underlying system. Users need to see the exact command that would reproduce their workflow execution.

## Your Mission

Implement a rerun command display feature that shows users the exact `pflow` command (with parameters) they can use to re-execute workflows without the planner. This creates a learning loop where users progress from natural language discovery to direct CLI mastery.

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
**File**: `.taskmaster/tasks/task_53/task-53.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_53/starting-context/`

**Files to read (in this order):**
1. `task-53-spec.md` - The corrected specification (FOLLOW THIS PRECISELY - it has critical corrections from the original task doc)
2. `task-53-handover.md` - Critical discoveries and corrections from investigation phase (READ CAREFULLY - contains warnings about incorrect assumptions)

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-53-spec.md`) is the source of truth for requirements and test criteria. The handover file contains CRITICAL corrections to the original task description - trust it over any conflicting information.

## What You're Building

A display system that shows executable rerun commands after workflow execution. When a workflow runs successfully (whether reused or newly created), users will see:

```
✨ Run again with:
  $ pflow commit-analyzer time_period="last week" author="john smith"

📖 Learn more:
  $ pflow workflow describe commit-analyzer
```

Example flow:
1. User: `pflow run "analyze commits from last week by john smith"`
2. System: Executes workflow successfully
3. System: Displays rerun command with actual parameter values
4. Next time, user can copy/paste: `pflow commit-analyzer time_period="last week" author="john smith"`

## Key Outcomes You Must Achieve

### Display Logic
- Show rerun command for reused workflows immediately after execution
- Show rerun command for new workflows only after user saves them
- Never show rerun command for unsaved workflows
- Display actual parameter values used, not placeholders

### Command Formatting
- Format commands WITHOUT "run" prefix (`pflow workflow-name` not `pflow run workflow-name`)
- Use `shlex.quote()` for ALL parameter values to ensure shell safety
- Convert types correctly: booleans to lowercase strings, JSON objects to compact format
- Handle edge cases: empty params, special characters, newlines

### Function Modifications
- Modify `_prompt_workflow_save()` to return `tuple[bool, str | None]` for tracking save status
- Add display logic in two integration points (reused and newly saved workflows)

## Implementation Strategy

### Phase 1: Create Core Utilities (1 hour)
1. Create shell escaping utility using `shlex.quote()`
2. Build parameter formatter to convert Python types to CLI format
3. Create command builder that assembles the complete rerun command
4. Write unit tests for all utilities

### Phase 2: Modify Save Function (30 minutes)
1. Update `_prompt_workflow_save()` signature to return `(was_saved: bool, workflow_name: str | None)`
2. Update the one caller to handle the new return value
3. Test the modification works correctly

### Phase 3: Implement Display Logic (1 hour)
1. Add rerun display for reused workflows in `_execute_successful_workflow()`
2. Add rerun display for newly saved workflows in `_prompt_workflow_save()`
3. Implement the describe command display
4. Test both display scenarios

### Phase 4: Comprehensive Testing (1-2 hours)
1. Test all parameter type conversions
2. Test shell escaping edge cases
3. Test round-trip execution (displayed command works)
4. Integration tests for both display scenarios

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### Parameter Type Conversion
You must reverse the CLI's type inference when displaying:
```python
# CLI parses (infer_type function)    # You must display
"true"/"false" → bool                 bool → "true"/"false" (lowercase!)
"42" → int                            int → "42"
"3.14" → float                        float → "3.14"
'[1,2,3]' → list                      list → json.dumps(v, separators=(',',':'))
'{"k":"v"}' → dict                    dict → json.dumps(v, separators=(',',':'))
```

### Data Access Pattern
The planner output structure contains everything you need:
```python
planner_output = {
    "execution_params": dict[str, Any] | None,  # Actual parameter values
    "workflow_source": {
        "found": bool,                # True = reused, False = generated
        "workflow_name": str | None,  # Name if found
    },
    "workflow_metadata": {
        "suggested_name": str,        # For new workflows before save
    }
}
```

### Integration Points
1. **Reused workflows**: `/src/pflow/cli/main.py:1358-1366` - After "✅ Reused existing workflow"
2. **New workflows**: `/src/pflow/cli/main.py:486-546` - In `_prompt_workflow_save()` after successful save

### Shell Escaping Requirements
Use `shlex.quote()` for ALL values - it's already used in the codebase at `/src/pflow/mcp/manager.py:256`

## Critical Warnings from Experience

### The "run" Prefix Misconception
**WARNING**: The original task doc shows `pflow run analyzer` but this is WRONG. The actual CLI uses `pflow analyzer` for saved workflows. The "run" prefix is optional and gets stripped. Display commands WITHOUT "run" prefix.

### The Non-Existent is_saved Flag
**WARNING**: There's no `is_saved` boolean anywhere in the codebase. You must track save status by:
- Using `workflow_source["found"]` to detect reused workflows
- Modifying `_prompt_workflow_save()` to return save status

### Display Only Known Workflow Names
**WARNING**: Never display rerun commands for unsaved workflows or when workflow name is unknown. This prevents user confusion.

## Key Decisions Already Made

1. **No "run" prefix in displayed commands** - Use `pflow workflow-name` format
2. **Display actual parameter values** - Not placeholders or examples
3. **Use shlex.quote() for all values** - Safety over optimization
4. **Show all execution_params** - Reproducibility over brevity
5. **Modify _prompt_workflow_save() return** - Cleaner than global state tracking
6. **Skip display for unsaved workflows** - Prevents confusion

**📋 Note on Specifications**: The specification file (`task-53-spec.md`) has been corrected from the original task description. Follow it precisely - it contains critical fixes discovered during investigation.

## Success Criteria

Your implementation is complete when:

- ✅ Reused workflows display rerun command immediately after execution
- ✅ New workflows display rerun command only after user saves
- ✅ Commands use correct format (`pflow name` not `pflow run name`)
- ✅ All parameter types convert correctly (bools, numbers, JSON)
- ✅ Shell escaping works for all edge cases (spaces, quotes, newlines)
- ✅ Round-trip test passes (displayed command executes identically)
- ✅ `_prompt_workflow_save()` returns new tuple format
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)

## Common Pitfalls to Avoid

- **DON'T** use `--param=value` format - pflow uses `param=value` without dashes
- **DON'T** display "run" prefix - it's optional and not canonical
- **DON'T** display commands for unsaved workflows - confusing for users
- **DON'T** show placeholder values - use actual execution_params
- **DON'T** skip shell escaping - even simple values should be escaped for safety
- **DON'T** assume is_saved flag exists - it doesn't
- **DON'T** trust the original task description - it has errors

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

1. **Current Display Logic Analysis**
   - Task: "Analyze how the CLI currently displays output after workflow execution in main.py"
   - Task: "Find all uses of click.echo() with emoji prefixes to understand display patterns"

2. **Parameter Handling Investigation**
   - Task: "Analyze the infer_type() and parse_workflow_params() functions to understand type conversion"
   - Task: "Find how execution_params flows from planner to CLI execution"

3. **Save Function Analysis**
   - Task: "Examine _prompt_workflow_save() to understand current implementation and callers"
   - Task: "Identify all places that call _prompt_workflow_save() to ensure compatibility"

4. **Testing Pattern Discovery**
   - Task: "Examine tests/test_cli/ for existing CLI output testing patterns"
   - Task: "Find tests for parameter parsing and type inference"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_53/implementation/implementation-plan.md`

Your plan should include:

1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - What must be done before what
3. **Subagent task assignments** - Who does what, ensuring no conflicts
4. **Risk identification** - What could go wrong and mitigation strategies
5. **Testing strategy** - How you'll verify each component works

### Implementation Plan Template

```markdown
# Task 53 Implementation Plan

## Context Gathered

### Display Patterns
- [Current CLI output patterns discovered]

### Integration Points
- [Where to hook in the display logic]

### Dependencies
- [What this implementation depends on]

## Implementation Steps

### Phase 1: Core Utilities (Parallel Execution Possible)
1. **Create Parameter Formatter** (Subagent A)
   - Files: src/pflow/cli/rerun_display.py (new)
   - Functions: format_param_value(), format_rerun_command()
   - Context: Must reverse infer_type() logic

2. **Create Shell Escaping Tests** (Subagent B - test-writer-fixer)
   - Files: tests/test_cli/test_rerun_display.py (new)
   - Test all parameter types and edge cases
   - Context: Test round-trip with parse_workflow_params()

### Phase 2: Modify Save Function (Sequential)
1. **Update _prompt_workflow_save Return**
   - Files: src/pflow/cli/main.py
   - Change return type to tuple[bool, str | None]
   - Update caller to handle new return

### Phase 3: Add Display Logic (Parallel Execution Possible)
1. **Display for Reused Workflows** (Subagent C)
   - Files: src/pflow/cli/main.py (specific lines)
   - Hook after "Reused existing workflow" message

2. **Display for Saved Workflows** (Subagent D)
   - Files: src/pflow/cli/main.py (specific lines)
   - Hook after successful save

### Phase 4: Integration Testing
[Testing tasks broken down by scenario]

### Phase 5: Final Test Review (use test-writer-fixer)
Deploy test-writer-fixer to review all tests and ensure quality

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|-------------------|
| Breaking save function callers | Search for all callers first |
| Shell escaping edge cases | Test with complex real examples |

## Validation Strategy

- Unit tests for each utility function
- Integration tests for both display scenarios
- Round-trip execution test
```

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_53/implementation/progress-log.md`

```markdown
# Task 53 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. Create implementation plan with context gathering
2. Build parameter formatting utilities in new module
3. Write comprehensive tests for utilities
4. Modify `_prompt_workflow_save()` to return status tuple
5. Add display logic for reused workflows
6. Add display logic for newly saved workflows
7. Test round-trip execution with displayed commands
8. Run full test suite and fix any issues

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to create parameter formatter...

Result: [What happened]
- ✅ What worked: Boolean conversion to lowercase strings
- ❌ What failed: JSON with nested quotes needed special handling
- 💡 Insight: shlex.quote() handles nested quotes correctly

Code that worked:
```python
def format_param_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    # ... rest of implementation
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
- Original plan: Modify only _prompt_workflow_save
- Why it failed: Found additional callers that needed updates
- New approach: Update all callers to handle tuple return
- Lesson: Always search for all function callers first
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test public interfaces and critical paths
- Test edge cases where bugs typically hide
- Create integration tests when components interact
- Document only interesting test discoveries in your progress log

**Critical test scenarios for this task**:
- Round-trip execution: displayed command must work identically
- Parameter type conversions: all types from spec
- Shell escaping edge cases: spaces, quotes, newlines, special chars
- Display scenarios: reused vs newly saved workflows

**Progress Log - Only document testing insights**:
```markdown
## 14:50 - Testing revealed edge case
JSON parameters with nested quotes weren't escaping correctly.
shlex.quote() handles this but only if we pass the string, not the dict.
Must json.dumps() first, then shlex.quote().
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** add "run" prefix to displayed commands
- **DON'T** display commands for unsaved workflows
- **DON'T** trust the original task description - use the corrected spec
- **DON'T** assume is_saved flag exists - it doesn't
- **DON'T** skip shell escaping for "simple" values
- **DON'T** use placeholder values - show actual parameters
- **DON'T** forget to update _prompt_workflow_save callers

## Getting Started

1. Read the epistemic manifesto to understand the approach
2. Read the corrected spec and handover - they contain critical fixes
3. Create your implementation plan with context gathering
4. Start with utility functions - they're testable in isolation
5. Run tests frequently: `pytest tests/test_cli/test_rerun_display.py -v`

## Final Notes

- The handover document contains CRITICAL corrections - the original task doc has errors
- The spec has been updated with the correct command format (no "run" prefix)
- Test the round-trip: your displayed command must execute identically
- This is a teaching feature - it helps users learn the system

## Remember

You're implementing a feature that transforms pflow from a black-box AI tool into a teaching system. Users will progress from natural language discovery to direct CLI mastery through the commands you display. The investigation phase discovered critical errors in the original requirements - trust the corrected spec and handover documents.

This feature is about user empowerment - enabling them to eventually bypass the AI planner entirely. Make the displayed commands correct, safe, and educational.

Good luck! Your implementation will accelerate user learning and reduce dependency on the AI planner.