# Implementation Plan for 8.5

## Objective
Add configurable stdout output from shared store and implement proper signal handling with exit codes for Unix pipe compatibility.

## Implementation Steps

### Part 1: Signal Handling Enhancement

1. [ ] Add SIGPIPE handler to main.py
   - File: `src/pflow/cli/main.py`
   - Change: Add SIGPIPE handler after SIGINT handler (around line 369)
   - Test: Manual test with `pflow run -f test.json | head -n 1`

### Part 2: CLI Option Addition

2. [ ] Add --output-key option to run command
   - File: `src/pflow/cli/main.py`
   - Change: Add @click.option decorator after line 328
   - Test: `pflow run --help` should show new option

3. [ ] Add output_key parameter to run function
   - File: `src/pflow/cli/main.py`
   - Change: Add parameter to run() function signature
   - Test: Function accepts the parameter

### Part 3: Output Logic Implementation

4. [ ] Implement output detection logic
   - File: `src/pflow/cli/main.py`
   - Change: After workflow execution (line 245), add logic to detect output
   - Test: Unit test for key detection order

5. [ ] Add safe output function with BrokenPipeError handling
   - File: `src/pflow/cli/main.py`
   - Change: Create helper function for safe output
   - Test: Manual broken pipe test

6. [ ] Integrate output logic with success message suppression
   - File: `src/pflow/cli/main.py`
   - Change: Modify success message logic based on output
   - Test: Verify message appears/disappears correctly

### Part 4: Testing

7. [ ] Create unit tests for output logic
   - File: `tests/test_cli/test_stdout_output.py`
   - Change: New test file with output scenarios
   - Test: Run pytest on new tests

8. [ ] Add integration tests for piping
   - File: `tests/test_cli/test_stdout_output.py`
   - Change: Add subprocess tests for real piping
   - Test: Verify Unix pipe compatibility

## Pattern Applications

### Previous Task Patterns
- Using Click option pattern from Task 2 for consistent CLI structure
- Following test-as-you-go from all previous subtasks
- Applying explicit None checks from 8.1 pitfall
- Maintaining backward compatibility pattern from 8.4

## Risk Mitigations
- **Risk**: Breaking existing CLI behavior
  - **Mitigation**: Only output when key exists, preserve all existing messages
- **Risk**: Platform-specific SIGPIPE failure
  - **Mitigation**: Use hasattr check before signal registration
- **Risk**: Binary data corruption
  - **Mitigation**: Skip binary output with warning as decided
