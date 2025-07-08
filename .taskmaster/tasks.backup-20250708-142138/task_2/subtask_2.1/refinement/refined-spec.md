# Refined Specification for Subtask 2.1

## Clear Objective
Add a 'run' subcommand to pflow's CLI that collects all command-line arguments as raw, unprocessed input, preserving special operators like '>>' for future parsing.

## Context from Knowledge Base
- Building on: Click group pattern from Task 1 with @main.command() decorator
- Avoiding: Processing or interpreting arguments (that's for future tasks)
- Following: Modular command structure, clear docstrings, CliRunner testing pattern
- **Cookbook patterns to apply**: Not applicable (CLI-only task, no PocketFlow usage)

## Technical Specification

### Inputs
- Command-line arguments after `pflow run`
- Examples:
  - `pflow run read-file --path=input.txt >> llm --prompt="Summarize"`
  - `pflow run "plan a backup strategy"`
  - `pflow run node1 >> node2 --flag=value >> node3`

### Outputs
- Tuple of all arguments collected via nargs=-1
- Temporary: Print joined arguments to stdout for verification
- Exit code 0 on success

### Implementation Constraints
- Must use: click framework with @main.command() decorator
- Must use: nargs=-1 with type=click.UNPROCESSED for raw collection
- Must avoid: Any parsing or interpretation of '>>' or other operators
- Must maintain: Existing click.group() structure in main.py

## Success Criteria
- [ ] 'run' command appears in `pflow --help` output
- [ ] All arguments after 'run' are collected as-is
- [ ] Special operators like '>>' are preserved in collected arguments
- [ ] Temporary output shows the collected workflow string
- [ ] Tests pass in new tests/test_cli_core.py file
- [ ] No modifications to existing commands or structure

## Test Strategy
- Unit tests: Create tests/test_cli_core.py with following coverage:
  - Test 'run' command exists and is callable
  - Test simple argument collection (e.g., `run node1 node2`)
  - Test preservation of '>>' operator
  - Test handling of quoted strings
  - Test handling of flags with values
  - Test empty arguments case
- Integration tests: Not needed for this subtask
- Manual verification: Run command with various inputs to see output

## Implementation Details

### File Changes
1. **src/pflow/cli/main.py**:
   - Add new `run` function after the `version` command
   - Use @main.command() decorator
   - Use @click.argument('workflow', nargs=-1, type=click.UNPROCESSED)
   - Add clear docstring
   - Temporarily echo the collected workflow

2. **tests/test_cli_core.py** (new file):
   - Import necessary modules (click.testing, pflow.cli.main)
   - Create comprehensive test functions
   - Follow patterns from test_cli.py

### Code Structure
```python
@main.command()
@click.argument('workflow', nargs=-1, type=click.UNPROCESSED)
def run(workflow):
    """Run a pflow workflow from command-line arguments."""
    # Join arguments to show collected workflow
    workflow_str = ' '.join(workflow)
    click.echo(f"Collected workflow: {workflow_str}")
```

## Dependencies
- Requires: Existing CLI structure from Task 1
- Impacts: Future tasks will build on this command (2.2, 2.3)

## Decisions Made
- Use click.UNPROCESSED type for truly raw input (evaluated in evaluation.md)
- Print joined string format for user-friendly output (evaluated in evaluation.md)
- Create separate test file as specified in task requirements
