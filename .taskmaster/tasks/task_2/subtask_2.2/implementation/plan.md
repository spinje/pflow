# Implementation Plan for Subtask 2.2

## Objective
Enhance the 'run' command to accept input from multiple sources (stdin, file, or command-line arguments) while storing the raw input in click context for future planner use.

## Implementation Steps
1. [ ] Add necessary imports to main.py
   - File: src/pflow/cli/main.py
   - Change: Add `import sys` and `from pathlib import Path`
   - Test: Verify imports work with basic run

2. [ ] Enhance run command with context and file option
   - File: src/pflow/cli/main.py
   - Change: Add @click.pass_context decorator and --file option
   - Test: Run with --help to see new option

3. [ ] Implement input detection logic
   - File: src/pflow/cli/main.py
   - Change: Add exclusive source detection and reading logic
   - Test: Test each input mode manually

4. [ ] Add stdin input tests
   - File: tests/test_cli_core.py
   - Change: Add test group for stdin handling
   - Test: pytest tests/test_cli_core.py::test_run_from_stdin

5. [ ] Add file input tests
   - File: tests/test_cli_core.py
   - Change: Add test group for file handling
   - Test: pytest tests/test_cli_core.py::test_run_from_file

6. [ ] Add error case tests
   - File: tests/test_cli_core.py
   - Change: Add tests for multiple source errors
   - Test: pytest tests/test_cli_core.py::test_run_error_cases

7. [ ] Add context storage tests
   - File: tests/test_cli_core.py
   - Change: Add tests verifying ctx.obj storage
   - Test: pytest tests/test_cli_core.py::test_run_context_storage

8. [ ] Verify all existing tests still pass
   - File: None
   - Change: Run full test suite
   - Test: make test

## Pattern Applications

### Cookbook Patterns (only potentially applicable to tasks that can leverage pocketflow)
- Not applicable for this CLI-only task

### Previous Task Patterns
- Using **click.UNPROCESSED pattern** from Task 2.1 for raw argument collection
- Using **-- separator pattern** from Task 2.1 for flag handling
- Using **type annotation pattern** from Task 2.1 for all new code
- Using **CliRunner testing pattern** from Task 1 and 2.1 for test cases
- Avoiding **empty arguments edge case** discovered in Task 2.1

## Risk Mitigations
- **Risk**: Breaking existing functionality
  - **Mitigation**: Run existing tests first, ensure all pass before and after changes
- **Risk**: stdin detection interfering with interactive mode
  - **Mitigation**: Use sys.stdin.isatty() to properly detect piped input
- **Risk**: Complex error messages confusing users
  - **Mitigation**: Clear, actionable error messages with examples
- **Risk**: File path issues on different platforms
  - **Mitigation**: Use pathlib.Path for cross-platform compatibility
