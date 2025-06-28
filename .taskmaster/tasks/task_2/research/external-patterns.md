# LLM Patterns Guidance for Task 2: Set up basic CLI for argument collection

## Summary
This task can significantly benefit from the following LLM patterns:
- **Click Default Group**: Intuitive default command pattern for better UX
- **Shell Integration**: Proper Unix signal handling and stdin detection
- **Context Management**: Clean state management between commands
- **Error Handling**: Clear, actionable error messages

## Specific Implementation

### Pattern: Click Default Group
Transform the basic CLI into a professional interface with default commands:

```python
# src/pflow/cli.py
from click_default_group import DefaultGroup
import click
import sys
import signal

@click.group(cls=DefaultGroup, default="run", default_if_no_args=True)
@click.version_option(version="0.1.0", prog_name="pflow")
@click.option('-v', '--verbose', is_flag=True, help='Verbose output')
@click.pass_context
def cli(ctx, verbose):
    """pflow - Plan Once, Run Forever.

    Natural language to deterministic workflows.
    """
    # Initialize context for sharing state
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['shared'] = {}  # Will hold shared store

# This enables both:
# pflow "fix issue 123"        # Uses default 'run' command
# pflow run "fix issue 123"    # Explicit command
# pflow registry list          # Other commands still work
```

### Pattern: Shell Signal Handling
Add proper Unix citizenship from the start:

```python
def setup_shell_integration():
    """Set up proper shell citizenship."""
    # Handle Ctrl+C gracefully (exit code 130)
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(130))

    # Handle broken pipe (when output is piped and closed)
    if hasattr(signal, 'SIGPIPE'):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    return {
        'stdin_is_tty': sys.stdin.isatty(),
        'stdout_is_tty': sys.stdout.isatty()
    }

# Call this in the main CLI group
@click.group(cls=DefaultGroup, default="run", default_if_no_args=True)
@click.pass_context
def cli(ctx):
    """pflow - Plan Once, Run Forever."""
    shell_info = setup_shell_integration()
    ctx.ensure_object(dict)
    ctx.obj['shell'] = shell_info
```

### Pattern: Collecting Raw Arguments
Properly collect all arguments including the '>>' operator:

```python
@cli.command()
@click.argument('workflow', nargs=-1)  # Captures all args as tuple
@click.option('--file', '-f', type=click.Path(exists=True))
@click.pass_context
def run(ctx, workflow, file):
    """Run a workflow (default command)."""
    # Join all arguments to handle >> operator
    if workflow:
        raw_input = ' '.join(workflow)
        # This preserves: "node1 --param=val >> node2"

    # Check for piped input
    if not ctx.obj['shell']['stdin_is_tty']:
        stdin_content = sys.stdin.read()
        # Store in context for later use
        ctx.obj['stdin'] = stdin_content
```

## Integration Points

### Where to Integrate
- **Main file**: `src/pflow/cli.py` (not cli/main.py as currently structured)
- **Dependencies**: Add to `pyproject.toml`:
  ```toml
  dependencies = [
      "click>=8.1.0",
      "click-default-group>=1.2.4",
  ]
  ```

### Migration from Current Structure
Current structure has `src/pflow/cli/main.py`. Consider either:
1. Moving to `src/pflow/cli.py` for simpler imports
2. Keeping current structure but updating imports

## Testing Approach

Use Click's CliRunner for all CLI tests:

```python
# tests/test_cli_core.py
from click.testing import CliRunner
from pflow.cli import cli

def test_default_command():
    """Test that default command works."""
    runner = CliRunner()

    # Test with argument (should use default 'run')
    result = runner.invoke(cli, ['test workflow'])
    assert result.exit_code == 0

    # Test explicit command
    result = runner.invoke(cli, ['run', 'test workflow'])
    assert result.exit_code == 0

def test_pipe_operator_collection():
    """Test that >> operator is preserved."""
    runner = CliRunner()

    result = runner.invoke(cli, ['node1', '--param=val', '>>', 'node2'])
    # Should capture: "node1 --param=val >> node2"
    assert result.exit_code == 0

def test_stdin_detection():
    """Test stdin piping."""
    runner = CliRunner()

    result = runner.invoke(cli, ['run'], input='piped content')
    assert result.exit_code == 0
    # Should detect and handle piped input
```

## Common Pitfalls to Avoid

1. **Don't parse '>>' too early**: This task only collects raw input
2. **Don't forget signal handlers**: Add them early for proper shell behavior
3. **Don't use sys.argv directly**: Let Click handle argument parsing
4. **Remember nargs=-1**: Captures all remaining arguments as tuple

## Benefits Over Basic Implementation

- **Better UX**: Users can just type `pflow "do something"`
- **Shell Integration**: Proper Ctrl+C handling, pipe support
- **Testing**: CliRunner makes testing much easier
- **Future-proof**: Sets foundation for complex commands later

## References
- `docs/implementation-details/simonw-llm-patterns/IMPLEMENTATION-GUIDE.md`: Task 2 section
- LLM source: `llm-main/llm/cli.py` lines 1-200 for CLI structure
- Click documentation: Default groups and context passing
