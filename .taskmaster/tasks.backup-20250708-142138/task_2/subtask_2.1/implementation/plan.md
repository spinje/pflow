# Implementation Plan for Subtask 2.1

## Objective
Add a 'run' subcommand to pflow's CLI that collects all command-line arguments as raw, unprocessed input, preserving special operators like '>>' for future parsing.

## Implementation Steps
1. [ ] Add `run` command to main.py
   - File: src/pflow/cli/main.py
   - Change: Add new function with @main.command() decorator after version command
   - Test: Verify command appears in `pflow --help`

2. [ ] Implement raw argument collection
   - File: src/pflow/cli/main.py
   - Change: Add @click.argument with nargs=-1 and type=click.UNPROCESSED
   - Test: Manual test with various inputs including '>>' operator

3. [ ] Create test file for CLI core functionality
   - File: tests/test_cli_core.py (new file)
   - Change: Create new test file with appropriate imports
   - Test: Ensure file is discovered by pytest

4. [ ] Add test for run command existence
   - File: tests/test_cli_core.py
   - Change: Test that 'run' appears in help and is callable
   - Test: Run pytest on this specific test

5. [ ] Add tests for argument collection scenarios
   - File: tests/test_cli_core.py
   - Change: Add tests for simple args, '>>' preservation, quoted strings, flags, empty args
   - Test: All tests pass with `make test`

## Pattern Applications

### Cookbook Patterns (only potentially applicable to tasks that can leverage pocketflow)
- Not applicable for this CLI-only task

### Previous Task Patterns
- Using Click group pattern from Task 1 for command structure
- Using CliRunner test pattern from Task 1 for testing
- Following modular command addition approach (no modification to existing commands)

## Risk Mitigations
- **Risk**: Breaking existing CLI structure
  - **Mitigation**: Only add new command, don't modify existing code
- **Risk**: Arguments not collected raw
  - **Mitigation**: Use click.UNPROCESSED type explicitly
- **Risk**: Tests not discovered
  - **Mitigation**: Follow exact naming pattern from existing test_cli.py
