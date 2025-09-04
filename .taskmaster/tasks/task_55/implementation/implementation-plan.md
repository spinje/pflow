# Task 55 Implementation Plan

## Overview

Implementing proper output control for interactive vs non-interactive execution modes. The solution follows Unix philosophy: clean stdout for piping, progress to stderr when interactive.

## Phase 1: Context Gathering with Parallel Subagents (30 mins)

Deploy ALL these tasks simultaneously to gather context:

### Output Analysis Tasks
1. **Task: Analyze all click.echo() calls in main.py**
   - "Search for all click.echo() calls in src/pflow/cli/main.py and categorize which ones go to stdout (no err parameter) vs stderr (err=True). Create a list showing line numbers and what type of output each one is (result/progress/error)."

2. **Task: Understand PlannerProgress implementation**
   - "Examine the PlannerProgress class in src/pflow/planning/debug.py lines 589-612. Document exactly how it displays progress, what format it uses, and how it could be made to respect an is_interactive flag."

### Integration Point Discovery Tasks
3. **Task: Examine InstrumentedNodeWrapper for callback hooks**
   - "Analyze the InstrumentedNodeWrapper._run() method in src/pflow/runtime/instrumented_wrapper.py lines 223-276. Identify the exact lines where we should add callback invocations for node_start and node_complete events."

4. **Task: Analyze _prepare_shared_storage function**
   - "Study the _prepare_shared_storage() function around line 569 in src/pflow/cli/main.py. Document its current parameters, what it adds to shared storage, and how we can modify it to accept an OutputController parameter."

### Testing Pattern Analysis Tasks
5. **Task: Find TTY testing patterns**
   - "Search the test suite for any existing tests that mock sys.stdin.isatty() or sys.stdout.isatty(). Document the mocking patterns used and any edge cases tested."

6. **Task: Analyze CLI output testing**
   - "Examine tests/test_cli/test_workflow_output_handling.py to understand how CLI output is currently tested. Document the testing patterns and how we can test output in different modes."

### Edge Case Research Tasks
7. **Task: Find existing TTY detection**
   - "Search for any existing code that checks sys.stdin.isatty() or sys.stdout.isatty() in the codebase. Document where it's used and what patterns are followed."

8. **Task: Analyze save workflow prompts**
   - "Find the save workflow prompt code around line 1361 in src/pflow/cli/main.py. Document how it currently detects interactive mode and what happens when non-interactive."

## Phase 2: Core Implementation (2-3 hours)

### Step 1: Create OutputController class (45 mins)
**File**: Create `src/pflow/core/output_controller.py`

```python
class OutputController:
    """Central output control based on execution mode."""

    def __init__(self, print_flag: bool = False,
                 output_format: str = "text",
                 stdin_tty: bool = None,
                 stdout_tty: bool = None):
        # Implementation per spec

    def is_interactive(self) -> bool:
        """Determine if running in interactive mode."""
        # Follow rules 1-4 from spec

    def create_progress_callback(self) -> Optional[Callable]:
        """Create progress callback for workflow execution."""
        # Return callback matching planner format

    def echo_progress(self, message: str):
        """Output progress message if interactive."""
        if self.is_interactive():
            click.echo(message, err=True)

    def echo_result(self, data: str):
        """Output result data to stdout."""
        click.echo(data)
```

### Step 2: Add CLI flag (30 mins)
**File**: Modify `src/pflow/cli/main.py`

At line 1756-1770, add:
```python
@click.option("-p", "--print", "print_flag", is_flag=True,
              help="Force non-interactive output (print mode)")
```

Pass through context:
```python
ctx.obj['print_flag'] = print_flag
```

### Step 3: Integrate with _prepare_shared_storage (30 mins)
**File**: Modify `src/pflow/cli/main.py` at line 569

```python
def _prepare_shared_storage(..., output_controller: Optional[OutputController] = None):
    # ... existing code ...
    if output_controller:
        callback = output_controller.create_progress_callback()
        if callback:
            shared_storage["__progress_callback__"] = callback
```

### Step 4: Add callbacks to InstrumentedNodeWrapper (45 mins)
**File**: Modify `src/pflow/runtime/instrumented_wrapper.py`

At line 246 (before execution):
```python
callback = shared.get("__progress_callback__")
if callable(callback):
    depth = shared.get("_pflow_depth", 0)
    try:
        callback(self.node_id, "node_start", None, depth)
    except Exception:
        pass  # Never let callback errors break execution
```

At line 264 (after execution):
```python
if callable(callback):
    try:
        callback(self.node_id, "node_complete", duration_ms, depth)
    except Exception:
        pass
```

## Phase 3: Update Existing Output (1-2 hours)

### Step 1: Update PlannerProgress (30 mins)
**File**: Modify `src/pflow/planning/debug.py`

Make PlannerProgress accept and respect OutputController:
- Pass OutputController to PlannerProgress.__init__
- Check is_interactive before outputting progress

### Step 2: Wrap click.echo calls (1 hour)
**File**: Modify `src/pflow/cli/main.py`

Based on context gathering results, wrap appropriate click.echo calls:
- Progress/status messages: Use output_controller.echo_progress()
- Results: Keep as-is (stdout)
- Errors: Keep as-is (stderr)
- Save prompts: Check output_controller.is_interactive()

### Step 3: Handle workflow execution header (30 mins)
Add "Executing workflow (N nodes):" header before execution.
Use the callback with a "workflow_start" event.

## Phase 4: Testing (2-3 hours)

Deploy test-writer-fixer agent for ALL test tasks:

### Test Suite 1: TTY Detection Tests
**Task for test-writer-fixer agent**:
"Create tests for OutputController.is_interactive() method testing all combinations: both TTY, neither TTY, mixed TTY, with -p flag, with JSON mode. Use mocking for sys.stdin.isatty() and sys.stdout.isatty(). Test Windows edge case where sys.stdin is None."

### Test Suite 2: Progress Callback Tests
**Task for test-writer-fixer agent**:
"Create tests for progress callbacks in InstrumentedNodeWrapper. Test that callbacks are invoked with correct parameters, that exceptions in callbacks don't break execution, and that missing callbacks are handled gracefully."

### Test Suite 3: Output Contamination Tests
**Task for test-writer-fixer agent**:
"Create tests that verify zero output contamination when piped. Test commands like 'echo test | pflow echo hello | cat' to ensure only results appear in stdout. Test with -p flag and JSON mode."

### Test Suite 4: Interactive Progress Tests
**Task for test-writer-fixer agent**:
"Create tests for interactive mode progress display. Test that planner progress appears, execution header shows node count, and each node shows progress with proper indentation for nested workflows."

### Test Suite 5: Edge Case Tests
**Task for test-writer-fixer agent**:
"Create tests for edge cases: empty workflows (0 nodes), nested workflows with different depths, very fast nodes (<100ms), and save workflow prompts in different modes."

## Phase 5: Verification & Polish (1 hour)

### Manual Testing Checklist
1. [ ] `echo "test" | pflow "echo hello" | cat` - outputs ONLY "hello"
2. [ ] `pflow "count files" | wc -l` - outputs clean number
3. [ ] `pflow -p "generate report"` - no progress in terminal
4. [ ] `pflow "analyze data"` - shows both planning and execution progress
5. [ ] `pflow --output-format json "test" | jq .` - valid JSON only
6. [ ] Nested workflows show proper indentation

### Automated Testing
1. [ ] `make test` - all tests pass
2. [ ] `make check` - linting and type checking pass
3. [ ] Run full test suite with coverage

## Critical Implementation Notes

### From Handover Document
1. **USE InstrumentedNodeWrapper, NOT WorkflowExecutor** - All nodes go through this wrapper
2. **USE existing _pflow_depth** - Don't implement custom depth tracking
3. **BOTH stdin AND stdout must be TTY** - Partial pipes mean non-interactive
4. **Windows: sys.stdin can be None** - Always check before isatty()
5. **Progress to stderr, results to stdout** - Never mix streams

### From Specification (Authoritative)
- 15 rules that MUST be implemented (see spec lines 108-125)
- 22 test criteria that MUST pass (see spec lines 177-199)
- Callbacks use `__progress_callback__` key in shared storage
- Progress format: `{name}... ✓ {duration:.1f}s`
- Node indentation based on _pflow_depth value

### From Epistemic Manifesto
- Question assumptions - verify integration points exist
- Test what matters - focus on piping and Unix composability
- Robustness over elegance - use try/except around callbacks
- Document ripple effects - list all files modified

## Success Metrics

✅ Task is complete when:
1. All 22 test criteria from spec pass
2. Zero contamination in piped output: `echo "test" | pflow "echo hello" | cat` shows only "hello"
3. Interactive mode shows progress for both planning and execution
4. -p flag forces non-interactive in any environment
5. make test and make check pass with no regressions

## File Modification Summary

Files to modify (4):
1. `src/pflow/cli/main.py` - Add flag, integrate OutputController
2. `src/pflow/runtime/instrumented_wrapper.py` - Add callback hooks
3. `src/pflow/planning/debug.py` - Make PlannerProgress respect mode

Files to create (1):
1. `src/pflow/core/output_controller.py` - New OutputController class

Test files to create/modify (5-10):
- Based on test-writer-fixer agent recommendations after implementation

## Risk Mitigation

1. **Risk**: Breaking existing behavior
   - **Mitigation**: Default remains interactive in terminal
   - **Verification**: Run existing test suite first

2. **Risk**: Windows TTY detection issues
   - **Mitigation**: -p flag provides override
   - **Verification**: Test with sys.stdin = None case

3. **Risk**: Callback errors breaking execution
   - **Mitigation**: Wrap all callbacks in try/except
   - **Verification**: Test with exception-raising callbacks

## Next Steps

1. ✅ Complete reading all context files
2. ✅ Create this implementation plan
3. ⏳ Deploy parallel subagents for context gathering
4. ⏳ Review gathered context and update plan if needed
5. ⏳ Implement Phase 2 (Core Implementation)
6. ⏳ Implement Phase 3 (Update Existing Output)
7. ⏳ Deploy test-writer-fixer for Phase 4 (Testing)
8. ⏳ Complete Phase 5 (Verification)

---
Plan created: 2025-01-03
Estimated time: 8-10 hours total
Priority: Fix non-interactive mode FIRST (it's critical for Unix composability)