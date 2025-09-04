# Task 55: Fix Output Control for Interactive vs Non-Interactive Execution

## ID
55

## Title
Fix Output Control for Interactive vs Non-Interactive Execution

## Description
Fix output behavior to properly handle interactive (terminal) vs non-interactive (piped/automated) execution modes. In interactive mode, add progress indicators for both planning and node execution. In non-interactive mode, suppress ALL progress output and only return the workflow result, making pflow usable in shell scripts, pipes, and CI/CD automation.

## Status
not started

## Dependencies
None

## Priority
high

## Details
pflow currently has two critical output control issues that make it appear broken in different contexts:

### Issue 1: Non-Interactive Mode is Broken (CRITICAL)
When used in pipes, scripts, or automation, pflow outputs progress messages that break downstream processing:
- Progress output pollutes stdout when piping: `pflow "count files" | wc -l` includes progress text
- Cannot be used in shell scripts reliably
- Breaks CI/CD automation
- Violates Unix philosophy of composable tools

### Issue 2: No Progress During Workflow Execution
In interactive mode, execution goes silent for 15-30 seconds during LLM calls:
- Planning phase shows progress (workflow-discovery... ✓ 7.6s)
- Execution phase shows nothing until complete
- Users abort thinking pflow has crashed
- Particularly bad with LLM nodes taking 10-30 seconds

### Current Behavior
- Always outputs progress messages regardless of context
- No detection of TTY/pipe status
- Silent during workflow execution even in interactive mode
- JSON mode partially suppresses output but not consistently

### Desired Behavior

**Non-Interactive Mode (piped/scripted/forced with -p):**
- Auto-detect via `sys.stdin.isatty()` and `sys.stdout.isatty()`
- OR force with `-p/--print` flag (for CI/Windows/weird TTY)
- Suppress ALL progress output (planner and execution)
- Output ONLY the workflow result
- In JSON mode, output only valid JSON
- No save prompts, no progress, just result

**Interactive Mode (terminal without -p):**
- Show planning progress (existing behavior)
- ADD workflow execution progress:
  - "Executing workflow (N nodes):" header
  - Each node name as it starts
  - Checkmark and duration when complete
- Keep all user prompts for saving workflows

### Usage Examples
```bash
# Auto-detect non-interactive (clean output)
$ pflow "count files" | wc -l
$ cat data.txt | pflow "analyze this"

# Force non-interactive with -p (for CI/Windows)
$ pflow -p "generate report"
$ pflow --print --output-format json "analyze"

# Interactive (shows progress)
$ pflow "complex analysis"  # In terminal, shows all progress
```

### Implementation Approach
- Add `-p/--print` flag to force non-interactive mode (like Claude Code)
- Create `is_interactive()` helper checking TTY status, JSON mode, and print flag
- Auto-detect non-TTY but allow explicit override with `-p`
- Wrap ALL progress outputs in interactive checks
- Add node execution callbacks to InstrumentedNodeWrapper
- Use consistent progress format across planner and executor
- Ensure clean result output for non-interactive use

### CLI Flag Addition
Add `-p/--print` flag that:
- Forces non-interactive mode regardless of TTY status
- Ensures pipeline-safe output even in weird TTY environments
- Matches Claude Code's behavior for user familiarity
- Provides escape hatch for CI/CD and Windows TTY issues

### Display Format
The progress output should match the existing planner style for consistency:
- Use same checkmark symbol (✓)
- Show timing in seconds with one decimal place
- Indent node names under workflow header
- Use emoji sparingly but effectively (📊 for workflow start)

### Integration Points
- InstrumentedNodeWrapper needs progress callback hooks
- CLI main.py passes callbacks via shared storage
- Must respect --output-format json flag
- Should work with both traced and non-traced execution
- Consider integration with existing metrics system

## Test Strategy
Test output control across all execution contexts:

### Non-Interactive Mode Tests (PRIORITY)
- Test piped output contains ONLY result: `pflow "test" | cat`
- Test explicit `-p/--print` flag forces non-interactive in terminal
- Test `-p` works in CI/CD environments with weird TTY
- Test scripted execution has clean output for parsing
- Test JSON mode outputs valid JSON only
- Test stderr still works for errors in non-interactive mode
- Test with various shell constructs: pipes, redirects, subshells
- Verify no ANSI codes or progress chars in piped output
- Test Windows environments where TTY detection fails

### Interactive Mode Tests
- Test planning progress indicators display correctly
- Test node execution progress with fast nodes (< 1 second)
- Test with slow nodes (mock 15-second LLM calls)
- Test progress updates don't create visual artifacts
- Test Ctrl+C interruption during long operations
- Test workflow save prompts appear only in interactive mode

### Cross-Mode Tests
- Verify is_interactive() detection works correctly
- Test JSON mode suppresses output in both modes
- Test progress timing data still captured in traces
- Test nested/namespaced nodes display correctly
- Ensure result output format is consistent
- Test with workflows of varying lengths (1, 5, 20 nodes)