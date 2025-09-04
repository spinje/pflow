# Task 55: Fix Output Control for Interactive vs Non-Interactive Execution - Agent Instructions

## The Problem You're Solving

pflow currently outputs progress messages to stdout even when piped, breaking Unix composability and making commands like `pflow "count files" | wc -l` unusable. Additionally, during interactive execution, users see no progress for 15-30 seconds during LLM calls, leading them to think pflow has crashed.

## Your Mission

Implement proper output control that detects interactive vs non-interactive execution modes, suppresses all progress when piped, and adds execution progress indicators for interactive mode.

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
**File**: `.taskmaster/tasks/task_55/task-55.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_55/starting-context/`

**Files to read (in this order):**
1. `research-findings.md` - Comprehensive research about current output system, execution flow, and integration points
2. `task-55-spec.md` - The specification (FOLLOW THIS PRECISELY) - contains all requirements and test criteria
3. `task-55-handover.md` - Critical insights about existing infrastructure that took hours to discover

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-55-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

An output control system that properly handles interactive (terminal) vs non-interactive (piped/automated) execution modes. In non-interactive mode, only the result is output (enabling Unix pipes). In interactive mode, progress indicators appear for both planning and execution phases.

Example:
```bash
# Interactive (terminal) - shows progress
$ pflow "analyze data"
workflow-discovery... ✓ 2.1s
generator... ✓ 3.4s
Executing workflow (3 nodes):
  read_file... ✓ 0.1s
  llm... ✓ 8.7s
  write_file... ✓ 0.2s

# Non-interactive (piped) - only result
$ pflow "count files" | wc -l
42

# Force non-interactive with -p flag
$ pflow -p "generate report"
Report content here
```

## Key Outcomes You Must Achieve

### Output Control
- Implement `OutputController` class for centralized output management
- Add `-p/--print` CLI flag to force non-interactive mode
- Detect TTY status using dual-check: `sys.stdin.isatty() AND sys.stdout.isatty()`
- Route progress to stderr when interactive, suppress when non-interactive
- Ensure results always go to stdout

### Progress Display
- Add execution progress callbacks to `InstrumentedNodeWrapper`
- Pass callbacks through shared storage using `__progress_callback__` key
- Match existing planner format: `{name}... ✓ {duration:.1f}s`
- Use existing `_pflow_depth` key for nested workflow indentation
- Show "Executing workflow (N nodes):" header before execution

### Integration Requirements
- Preserve existing planner progress behavior
- Make JSON mode imply non-interactive
- Suppress save workflow prompts in non-interactive mode
- Handle Windows edge cases where sys.stdin can be None
- Ensure zero output contamination when piped

## Implementation Strategy

### Phase 1: Core Output Control (1-2 hours)
1. Add `-p/--print` flag to CLI at line 1756-1770 in `src/pflow/cli/main.py`
2. Create `OutputController` class in new file `src/pflow/core/output_controller.py`
3. Implement `is_interactive()` method with proper TTY detection logic
4. Update `_prepare_shared_storage()` to accept OutputController and add callback

### Phase 2: Progress Callback Integration (1-2 hours)
1. Modify `InstrumentedNodeWrapper._run()` to check for and invoke callbacks
2. Add callback invocation at node start (line 246) and complete (line 264)
3. Extract depth from `shared.get("_pflow_depth", 0)` for indentation
4. Wrap callback invocations in try/except to prevent breaking execution

### Phase 3: Update Existing Output (2-3 hours)
1. Wrap all `click.echo()` calls in main.py with output controller checks
2. Update `PlannerProgress` class to respect is_interactive mode
3. Modify save workflow prompts to check is_interactive
4. Ensure error messages always go to stderr regardless of mode

### Phase 4: Testing (2-3 hours)
1. Create tests for TTY detection with mocking
2. Test all flag combinations and edge cases
3. Verify piped output contains no progress contamination
4. Test nested workflow indentation

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

Implementation should be done by yourself! Write tests using the `test-writer-fixer` subagent AFTER implementation is complete.

## Critical Technical Details

### TTY Detection Must Use Both Streams
```python
# CORRECT - both must be TTY for interactive
interactive = sys.stdin.isatty() and sys.stdout.isatty()

# WRONG - partial pipes will break
interactive = sys.stdin.isatty() or sys.stdout.isatty()
```

### Callback Integration Pattern
```python
# In InstrumentedNodeWrapper._run() around line 246
callback = shared.get("__progress_callback__")
if callable(callback):
    depth = shared.get("_pflow_depth", 0)
    try:
        callback(self.node_id, "node_start", None, depth)
    except Exception:
        pass  # Never let callback errors break execution

# After execution around line 264
if callable(callback):
    callback(self.node_id, "node_complete", duration_ms, depth)
```

### Progress Output Rules
```python
# Progress ALWAYS to stderr when shown
click.echo("progress message", err=True)

# Results ALWAYS to stdout
click.echo("result data")

# Never mix progress with results!
```

### Using Existing Infrastructure
The system already has `_pflow_depth` tracking in shared storage - use it:
```python
depth = shared.get("_pflow_depth", 0)
indent = "  " * depth
```

## Critical Warnings from Experience

### InstrumentedNodeWrapper, NOT WorkflowExecutor
The original task description incorrectly mentioned WorkflowExecutor. The correct integration point is `InstrumentedNodeWrapper` at lines 223-276 in `src/pflow/runtime/instrumented_wrapper.py`. Every node goes through this wrapper.

### Depth Tracking Already Exists
Don't implement custom depth tracking. The `_pflow_depth` key in shared storage is automatically maintained by WorkflowExecutor for nested workflows. Just read it and use it for indentation.

### Windows Edge Cases
On Windows GUI apps, `sys.stdin` can be None. Always check before calling `isatty()`:
```python
if sys.stdin is None or sys.stdout is None:
    return False  # Treat as non-interactive
```

## Key Decisions Already Made

1. **Use shared storage for callbacks** - Pass callbacks via `__progress_callback__` key rather than modifying PocketFlow
2. **Hook into InstrumentedNodeWrapper** - Don't create new wrappers, use the existing one
3. **-p flag matches Claude Code** - Use `-p/--print` for familiarity, not `--quiet` or `--no-progress`
4. **Dual TTY check required** - Both stdin AND stdout must be TTY for interactive mode
5. **JSON mode implies non-interactive** - When `--output-format json`, always suppress progress
6. **Use existing _pflow_depth** - Don't create custom depth tracking

**📋 Note on Specifications**: The specification file (`task-55-spec.md`) is the authoritative source. It contains 15 rules and 22 test criteria that must ALL be met.

## Success Criteria

Your implementation is complete when:

- ✅ All 22 test criteria from the spec pass
- ✅ Piped commands output ONLY results (no progress contamination)
- ✅ Interactive mode shows both planning and execution progress
- ✅ `-p` flag forces non-interactive mode in any environment
- ✅ Nested workflows show proper indentation
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Zero output contamination verified with: `echo "test" | pflow "echo hello" | cat`

## Common Pitfalls to Avoid

- **DON'T modify PocketFlow core** - Use shared storage for passing callbacks
- **DON'T create new node wrappers** - InstrumentedNodeWrapper already exists
- **DON'T implement custom depth tracking** - Use existing `_pflow_depth` key
- **DON'T let callback errors break execution** - Always wrap in try/except
- **DON'T forget Windows edge cases** - Check for None before isatty()
- **DON'T mix stdout and stderr** - Progress to stderr, results to stdout
- **DON'T skip the handover document** - It contains hours of research insights

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

1. **Current Output Analysis**
   - Task: "Analyze all click.echo() calls in src/pflow/cli/main.py and categorize which go to stdout vs stderr"
   - Task: "Find how PlannerProgress in src/pflow/planning/debug.py displays progress"

2. **Integration Points Discovery**
   - Task: "Examine InstrumentedNodeWrapper._run() method and identify exact lines for callback insertion"
   - Task: "Analyze _prepare_shared_storage() function to understand how to add callbacks"

3. **Testing Pattern Analysis**
   - Task: "Find existing tests that mock TTY status for testing patterns"
   - Task: "Identify how CLI output is tested in tests/test_cli/"

4. **Edge Cases Research**
   - Task: "Search for any existing TTY detection patterns in the codebase"
   - Task: "Find how save workflow prompts currently detect interactive mode"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_55/implementation/implementation-plan.md`

Follow the template provided in the main instructions above, ensuring you cover all phases and identify file-specific subagent tasks.

### When to Revise Your Plan

Your plan is a living document. Update it when:
- Context gathering reveals new requirements
- Implementation hits unexpected obstacles
- Dependencies change
- Better approaches become apparent

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_55/implementation/progress-log.md`

```markdown
# Task 55 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. Read all context files to understand the complete picture
2. Create implementation plan with subagent task assignments
3. Add `-p/--print` flag to CLI
4. Create OutputController class with TTY detection
5. Modify _prepare_shared_storage to add callbacks
6. Add callback hooks to InstrumentedNodeWrapper
7. Update all output calls to respect interactive mode
8. Write comprehensive tests with TTY mocking
9. Verify zero contamination in piped mode
10. Run full test suite and fix any issues

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to add -p flag to CLI...

Result: Flag added successfully
- ✅ What worked: Added at line 1765 after --output-format
- ❌ What failed: Initially put it in wrong location
- 💡 Insight: Click options must be in specific order

Code that worked:
```python
@click.option("-p", "--print", "print_flag", is_flag=True,
              help="Force non-interactive output (print mode)")
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
- Original plan: Modify WorkflowExecutor for callbacks
- Why it failed: WorkflowExecutor is for nested workflows only
- New approach: Use InstrumentedNodeWrapper instead
- Lesson: Always verify integration points before implementing
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**Critical tests for this task**:
- TTY detection with all combinations (both TTY, neither, mixed)
- Piped output contamination (must be zero progress in output)
- Flag behavior (-p overrides TTY detection)
- JSON mode suppresses progress
- Nested workflow indentation
- Callback error handling doesn't break execution

**Progress Log - Only document testing insights**:
```markdown
## 15:30 - Testing revealed Windows edge case
sys.stdin can be None in Windows GUI apps. Added None check
before isatty() calls. This prevents AttributeError crashes.
```

## What NOT to Do

- **DON'T** read the context files before confirming you understand the approach
- **DON'T** modify PocketFlow core files in pocketflow/__init__.py
- **DON'T** create performance benchmarks or metrics (removed from spec)
- **DON'T** implement Ctrl+C handling (separate concern)
- **DON'T** change existing test behavior
- **DON'T** forget to test the critical pipe use case: `echo "test" | pflow "echo hello" | cat`

## Getting Started

1. First read the epistemic manifesto to understand the approach
2. Read all context files in order (research → spec → handover)
3. Create your implementation plan before any coding
4. Start with the simplest part: adding the -p flag
5. Test frequently with: `echo "test" | pflow "echo hello" | cat`

## Final Notes

- The infrastructure you need mostly already exists (depth tracking, node wrapping)
- The handover document contains critical discoveries that took hours to find
- Focus on the Unix philosophy: clean stdout for piping
- The spec has 22 specific test criteria - meet them all
- Test with real pipes, not just unit tests

## Remember

You're fixing a critical usability issue that makes pflow appear broken in different contexts. The solution enables pflow to be a proper Unix tool that composes in pipelines while providing helpful progress in interactive use. The research has already identified all the integration points - trust it.

When facing uncertainty, the specification is your source of truth. The handover document will save you hours by revealing what already exists in the codebase.

Good luck! This fix will make pflow a first-class citizen in Unix pipelines and shell scripts.