# Refined Specification for Subtask 2.2

## Clear Objective
Enhance the 'run' command to accept input from multiple sources (stdin, file, or command-line arguments) while storing the raw input in click context for future planner use.

## Context from Knowledge Base
- Building on: Existing 'run' command with raw argument collection from subtask 2.1
- Avoiding: Click's option parsing interference (use -- separator pattern)
- Following: Type annotation requirements, CliRunner testing pattern
- **Cookbook patterns to apply**: Not applicable (CLI-only task, no PocketFlow usage)

## Technical Specification

### Inputs
1. **Command-line arguments** (existing):
   - `pflow run read-file >> llm --prompt="Summarize"`
   - `pflow run "plan a backup strategy"`

2. **Stdin input** (new):
   - `echo "read-file >> llm" | pflow run`
   - `cat workflow.txt | pflow run`

3. **File input** (new):
   - `pflow run --file=workflow.txt`
   - `pflow run -f saved_workflow.pflow`

### Outputs
- Temporary: Echo message showing collected workflow and source
  - "Collected workflow from args: {workflow}"
  - "Collected workflow from stdin: {workflow}"
  - "Collected workflow from file: {workflow}"
- Store raw input in ctx.obj for future use
- Exit code 0 on success, non-zero on errors

### Implementation Constraints
- Must use: @click.pass_context decorator for context access
- Must use: sys.stdin.isatty() for stdin detection
- Must use: click.Path(exists=True) for file validation
- Must maintain: Backwards compatibility with existing tests
- Must enforce: Mutually exclusive input sources

## Success Criteria
- [ ] Existing argument collection tests still pass
- [ ] stdin input detected and read when piped
- [ ] --file option reads workflow from file
- [ ] Error on multiple input sources (e.g., both stdin and --file)
- [ ] Raw input stored in ctx.obj dictionary
- [ ] Clear error messages for missing files or invalid input
- [ ] Type annotations on all new code
- [ ] Tests for all three input modes

## Test Strategy
- Unit tests: Expand tests/test_cli_core.py with:
  - stdin tests using CliRunner(input="workflow content")
  - File tests with temporary files
  - Error cases (missing file, multiple sources)
  - Context storage verification
- Integration tests: Not needed for this subtask
- Manual verification: Test with actual pipes and files

## Implementation Details

### File Changes
1. **src/pflow/cli/main.py**:
   - Add imports: `import sys` and `from pathlib import Path`
   - Add @click.pass_context decorator to run function
   - Add @click.option("--file", "-f", type=click.Path(exists=True))
   - Implement input detection logic (priority: exclusive sources)
   - Initialize ctx.obj and store raw_input
   - Update output to show input source

2. **tests/test_cli_core.py**:
   - Add test group for stdin input handling
   - Add test group for file input handling
   - Add tests for error cases
   - Add tests for context storage

### Code Structure
```python
@main.command()
@click.pass_context
@click.option("--file", "-f", type=click.Path(exists=True), help="Read workflow from file")
@click.argument("workflow", nargs=-1, type=click.UNPROCESSED)
def run(ctx: click.Context, file: str | None, workflow: tuple[str, ...]) -> None:
    """Run a pflow workflow from command-line arguments, stdin, or file."""
    # Initialize context object
    if ctx.obj is None:
        ctx.obj = {}

    # Determine input source and read workflow
    if file and workflow:
        raise click.ClickException("Cannot specify both --file and command arguments")

    if file:
        # Read from file
        raw_input = Path(file).read_text().strip()
        source = "file"
    elif not sys.stdin.isatty():
        # Read from stdin
        raw_input = sys.stdin.read().strip()
        if workflow:
            raise click.ClickException("Cannot specify both stdin and command arguments")
        source = "stdin"
    else:
        # Use command arguments
        raw_input = " ".join(workflow)
        source = "args"

    # Store in context
    ctx.obj["raw_input"] = raw_input
    ctx.obj["input_source"] = source

    # Temporary output
    click.echo(f"Collected workflow from {source}: {raw_input}")
```

## Dependencies
- Requires: Subtask 2.1 completion (basic run command exists)
- Impacts: Future planner tasks will use ctx.obj["raw_input"]

## Decisions Made
- Use click.Context with ctx.obj for storage (standard click pattern)
- --file option reads workflow definitions, not data files
- Input sources are mutually exclusive with clear errors
- Simple detection: presence of '>>' indicates CLI syntax (for future use)
