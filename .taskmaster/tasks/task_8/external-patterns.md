# LLM Patterns Guidance for Task 8: Build comprehensive shell pipe integration

## Summary
This task implements shell integration patterns inspired by LLM's approach, with pflow-specific enhancements:
- **Stdin/Stdout Handling**: Detect and read piped input correctly (like LLM's `sys.stdin.isatty()` check)
- **Signal Management**: Graceful handling of Ctrl+C and broken pipes (not directly in LLM, but Unix best practice)
- **Exit Codes**: Proper error propagation for shell scripts
- **Encoding Safety**: Handle Unicode gracefully
- **Streaming Support**: Efficient handling of large inputs

**Note**: While LLM provides the stdin detection pattern, the comprehensive signal handling and broken pipe management shown below are additional Unix shell citizenship best practices not explicitly found in LLM's codebase.

## Specific Implementation

### Pattern: Complete Shell Integration Module
Create a comprehensive shell integration module inspired by LLM's stdin detection approach, enhanced with full Unix shell citizenship:

```python
# src/pflow/core/shell_integration.py
import sys
import os
import signal
import select

class ShellIntegration:
    """Handle Unix pipes and shell integration for pflow."""

    @staticmethod
    def setup():
        """Initialize proper shell citizenship."""
        # Handle Ctrl+C gracefully - exit with code 130
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(130))

        # Handle broken pipe when output is piped and closed
        if hasattr(signal, 'SIGPIPE'):
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)

        return {
            'stdin_is_tty': sys.stdin.isatty(),
            'stdout_is_tty': sys.stdout.isatty(),
            'stderr_is_tty': sys.stderr.isatty()
        }

    @staticmethod
    def is_stdin_piped():
        """Check if stdin has piped data."""
        return not sys.stdin.isatty()

    @staticmethod
    def read_stdin():
        """Read all stdin content if piped."""
        if not sys.stdin.isatty():
            try:
                return sys.stdin.read()
            except KeyboardInterrupt:
                sys.exit(130)
            except Exception:
                return None
        return None

    @staticmethod
    def populate_shared_store(shared):
        """Populate shared store with stdin if available."""
        stdin_content = ShellIntegration.read_stdin()
        if stdin_content:
            shared["stdin"] = stdin_content
            return True
        return False

    @staticmethod
    def safe_output(text, file=sys.stdout):
        """Output text safely, handling encoding and broken pipes."""
        if text is None:
            return

        try:
            print(text, file=file, flush=True)
        except BrokenPipeError:
            # Handle broken pipe gracefully
            # Close stdout and exit cleanly
            try:
                file.close()
            except:
                pass
            # Use os._exit to avoid further writes
            os._exit(0)
        except IOError as e:
            if e.errno == 32:  # Broken pipe
                os._exit(0)
        except UnicodeEncodeError:
            # Handle encoding issues gracefully
            safe_text = text.encode('utf-8', errors='replace').decode('utf-8')
            try:
                print(safe_text, file=file, flush=True)
            except:
                os._exit(1)
```

### Pattern: Streaming Support for Large Inputs
Handle large piped inputs efficiently:

```python
    @staticmethod
    def stream_stdin(chunk_size=8192):
        """Stream stdin in chunks for large inputs."""
        if sys.stdin.isatty():
            return

        try:
            while True:
                chunk = sys.stdin.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        except KeyboardInterrupt:
            sys.exit(130)

    @staticmethod
    def read_stdin_with_limit(max_size=10_000_000):  # 10MB default
        """Read stdin with size limit for safety."""
        if sys.stdin.isatty():
            return None

        content = []
        total_size = 0

        for chunk in ShellIntegration.stream_stdin():
            total_size += len(chunk)
            if total_size > max_size:
                raise ValueError(f"Input exceeds maximum size of {max_size} bytes")
            content.append(chunk)

        return ''.join(content)
```

### Pattern: Exit Code Management
Proper exit codes for shell script compatibility:

```python
class ExitCodes:
    """Standard exit codes for shell compatibility."""
    SUCCESS = 0
    GENERAL_ERROR = 1
    USAGE_ERROR = 2
    DATAERR = 65      # Input data incorrect
    NOINPUT = 66      # Input file missing
    SOFTWARE = 70     # Internal software error
    OSERR = 71        # System error
    IOERR = 74        # I/O error
    TEMPFAIL = 75     # Temporary failure
    NOPERM = 77       # Permission denied
    CONFIG = 78       # Configuration error
    SIGINT = 130      # Ctrl+C (128 + 2)

    @staticmethod
    def exit(code, message=None):
        """Exit with proper code and optional message."""
        if message:
            print(message, file=sys.stderr)
        sys.exit(code)
```

### Pattern: Integration with CLI
How to use in the main CLI:

```python
# In src/pflow/cli.py
@click.command()
@click.pass_context
def run(ctx, workflow):
    """Run a workflow."""
    shell = ShellIntegration.setup()
    shared = ctx.obj['shared']

    # Populate shared store with stdin if piped
    if ShellIntegration.populate_shared_store(shared):
        if ctx.obj['verbose']:
            click.echo(f"Read {len(shared['stdin'])} bytes from stdin", err=True)

    try:
        # Workflow execution...
        result = execute_workflow(workflow, shared)

        # Output result for pipe chaining
        if result and 'response' in shared:
            ShellIntegration.safe_output(shared['response'])

    except KeyboardInterrupt:
        ExitCodes.exit(ExitCodes.SIGINT)
    except IOError as e:
        if e.errno == 32:  # Broken pipe
            os._exit(0)
        ExitCodes.exit(ExitCodes.IOERR, str(e))
    except Exception as e:
        ExitCodes.exit(ExitCodes.SOFTWARE, f"Error: {e}")
```

## Testing Approach

Test all shell integration scenarios:

```python
# tests/test_shell_integration.py
import pytest
from pflow.core.shell_integration import ShellIntegration
from click.testing import CliRunner

def test_stdin_detection(monkeypatch):
    """Test stdin piped vs terminal detection."""
    # Mock piped stdin
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    assert ShellIntegration.is_stdin_piped() == True

    # Mock terminal stdin
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    assert ShellIntegration.is_stdin_piped() == False

def test_stdin_reading():
    """Test reading from stdin using CliRunner."""
    runner = CliRunner()

    # Test with piped input
    result = runner.invoke(cli, ['run'], input='Hello, World!')
    assert result.exit_code == 0
    # Verify stdin was captured

def test_broken_pipe_handling():
    """Test graceful handling of broken pipes."""
    runner = CliRunner()

    # Simulate broken pipe scenario
    with runner.isolated_filesystem():
        # Create large output that would trigger broken pipe
        result = runner.invoke(cli, ['generate-large-output'])
        # Should exit cleanly, not crash

def test_exit_codes():
    """Test proper exit code propagation."""
    runner = CliRunner()

    # Test success
    result = runner.invoke(cli, ['valid-command'])
    assert result.exit_code == 0

    # Test general error
    result = runner.invoke(cli, ['invalid-command'])
    assert result.exit_code == 1

    # Test Ctrl+C simulation
    # Would need special handling to test signal
```

## Common Pitfalls to Avoid

1. **Don't forget flush=True**: Important for real-time output in pipes
2. **Handle broken pipe properly**: Use os._exit(0), not sys.exit()
3. **Check isatty() before reading**: Prevents hanging on terminal input
4. **Use proper exit codes**: Shell scripts depend on these
5. **Handle Unicode errors**: Not all terminals support UTF-8

## Integration with pocketflow

Remember that stdin content goes into the shared store:

```python
# In workflow execution
shared = {}
ShellIntegration.populate_shared_store(shared)

# Now shared["stdin"] contains piped input if any
# Nodes can check for this:
class SomeNode(Node):
    def prep(self, shared):
        # Use stdin as fallback
        content = shared.get("text") or shared.get("stdin", "")
```

## Real-World Usage Examples

```bash
# Pipe text to pflow
echo "Hello, World" | pflow llm --prompt="Translate to French"

# Chain with other Unix tools
cat document.md | pflow summarize | head -10

# Use in shell scripts with proper error handling
if pflow process --file=data.txt > output.txt; then
    echo "Success"
else
    echo "Failed with code $?"
fi

# Handle Ctrl+C gracefully
pflow long-running-task  # Ctrl+C exits with code 130
```

## References
- IMPLEMENTATION-GUIDE.md: Task 8 section
- LLM source: `llm-main/llm/cli.py` lines ~1106-1110 (stdin handling in read_prompt)
- LLM attachment handling: `llm-main/llm/cli.py` lines ~170-190 (stdin for attachments)
- Unix philosophy: Proper pipe citizenship
- Python docs: signal handling, sys.stdin/stdout
