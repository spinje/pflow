# PocketFlow Patterns for Task 8: Shell Pipe Integration

## Task Context

- **Goal**: Implement comprehensive Unix pipe support for stdin/stdout handling
- **Dependencies**: Task 3 (shared store initialization with stdin)
- **Constraints**: Must work seamlessly with both piped input AND pflow's >> operator

## Core Patterns from Advanced Analysis

### Pattern: stdin Detection and Shared Store Population
**Found in**: Tutorial-Cold-Email (batch processing), implicit in others
**Why It Applies**: Natural integration with Unix philosophy

```python
import sys
import select

def detect_stdin() -> bool:
    """Detect if stdin has piped content"""
    # Check if stdin is not a terminal (piped/redirected)
    if not sys.stdin.isatty():
        # Additional check for actual content availability
        # Handles edge case of empty pipe
        return select.select([sys.stdin], [], [], 0.0)[0]
    return False

def read_stdin() -> str:
    """Read all stdin content"""
    # Read all at once for small inputs (MVP approach)
    return sys.stdin.read()

def initialize_shared_with_stdin(shared: dict) -> dict:
    """Pattern from Task 3 - populate shared with stdin"""
    if detect_stdin():
        stdin_content = read_stdin()
        if stdin_content:
            shared["stdin"] = stdin_content
            # Log for debugging
            logger.debug(f"Populated shared['stdin'] with {len(stdin_content)} bytes")

    return shared
```

### Pattern: Streaming for Large Inputs
**Found in**: YouTube tutorial handles large transcripts
**Why It Applies**: pflow must handle arbitrary input sizes

```python
def stream_stdin(chunk_size: int = 8192) -> Iterator[str]:
    """Stream stdin in chunks for large inputs"""
    while True:
        chunk = sys.stdin.read(chunk_size)
        if not chunk:
            break
        yield chunk

def read_stdin_with_limit(max_size: int = 10 * 1024 * 1024) -> str:
    """Read stdin with size limit (10MB default)"""
    content = []
    total_size = 0

    for chunk in stream_stdin():
        total_size += len(chunk)
        if total_size > max_size:
            raise ValueError(f"Input exceeds {max_size} bytes")
        content.append(chunk)

    return "".join(content)

# Integration with shared store
def populate_stdin_smart(shared: dict, config: dict) -> dict:
    """Smart stdin handling based on config"""
    if not detect_stdin():
        return shared

    if config.get("stream_mode", False):
        # For future: streaming mode
        shared["stdin_stream"] = stream_stdin()
    else:
        # Default: read all with limit
        try:
            shared["stdin"] = read_stdin_with_limit(
                config.get("max_stdin_size", 10 * 1024 * 1024)
            )
        except ValueError as e:
            logger.error(f"Stdin too large: {e}")
            sys.exit(2)  # Exit code 2 for usage error

    return shared
```

### Pattern: Exit Code Propagation
**Found in**: All CLI tools follow Unix conventions
**Why It Applies**: pflow must be scriptable

```python
# Exit codes following Unix conventions
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_DATAERR = 65  # Input data error
EXIT_SOFTWARE = 70  # Internal software error
EXIT_OSERR = 71  # System error
EXIT_IOERR = 74  # I/O error
EXIT_TEMPFAIL = 75  # Temporary failure
EXIT_NOPERM = 77  # Permission denied
EXIT_CONFIG = 78  # Configuration error

def exit_with_code(code: int, message: str = None):
    """Exit with proper code and optional message"""
    if message:
        # Write errors to stderr, not stdout
        sys.stderr.write(f"pflow: {message}\n")
    sys.exit(code)

# Usage in error handling
try:
    flow.run(shared)
except FileNotFoundError as e:
    exit_with_code(EXIT_IOERR, f"File not found: {e}")
except PermissionError as e:
    exit_with_code(EXIT_NOPERM, f"Permission denied: {e}")
except ValueError as e:
    exit_with_code(EXIT_DATAERR, f"Invalid input: {e}")
except Exception as e:
    exit_with_code(EXIT_SOFTWARE, f"Internal error: {e}")
```

### Pattern: Signal Handling for Graceful Interruption
**Found in**: Production CLI tools handle Ctrl+C gracefully
**Why It Applies**: Users expect clean interruption

```python
import signal
import atexit

class GracefulInterrupt:
    """Context manager for graceful shutdown"""
    def __init__(self):
        self.interrupted = False
        self.original_handlers = {}

    def __enter__(self):
        # Install signal handlers
        for sig in [signal.SIGINT, signal.SIGTERM]:
            self.original_handlers[sig] = signal.signal(sig, self._handler)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore original handlers
        for sig, handler in self.original_handlers.items():
            signal.signal(sig, handler)

    def _handler(self, signum, frame):
        """Handle interrupt signal"""
        self.interrupted = True
        # Clean up resources
        cleanup_resources()
        # Exit with standard interrupted code
        sys.stderr.write("\npflow: Interrupted\n")
        sys.exit(130)  # 128 + SIGINT(2)

def cleanup_resources():
    """Clean up temporary files, connections, etc."""
    # Called on interrupt or exit
    if hasattr(shared, "_temp_files"):
        for temp_file in shared.get("_temp_files", []):
            try:
                os.unlink(temp_file)
            except OSError:
                pass

# Register cleanup
atexit.register(cleanup_resources)

# Usage
with GracefulInterrupt() as interrupt:
    for node in flow_sequence:
        if interrupt.interrupted:
            break
        node.run(shared)
```

### Pattern: Shell Integration Helpers
**Found in**: Simon Willison's llm CLI patterns
**Why It Applies**: pflow should feel native to shell users

```python
def setup_shell_environment():
    """Configure for optimal shell usage"""
    # Ensure UTF-8 output
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

    # Disable Python buffering for real-time output
    sys.stdout = Unbuffered(sys.stdout)
    sys.stderr = Unbuffered(sys.stderr)

class Unbuffered:
    """Unbuffered stream wrapper"""
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)

# Progress output that respects piping
def show_progress(message: str):
    """Show progress only when stdout is terminal"""
    if sys.stderr.isatty():
        # Show progress to stderr when interactive
        sys.stderr.write(f"\r{message}")
        sys.stderr.flush()
    # When piped, no progress output
```

## Anti-Patterns to Avoid

### Anti-Pattern: Reading stdin Multiple Times
**Issue**: stdin is consumed on first read
**Alternative**: Read once, store in shared

### Anti-Pattern: Mixing stdout and stderr
**Issue**: Breaks pipe chains
**Alternative**: Results to stdout, messages to stderr

### Anti-Pattern: Interactive Prompts in Pipe Mode
**Issue**: Breaks automation
**Alternative**: Fail with clear error or use defaults

## Implementation Guidelines

1. **Follow Unix Philosophy**: Do one thing well
2. **Be a Good Citizen**: Respect pipes and signals
3. **Fail Fast**: Clear errors with proper exit codes
4. **Stay Silent**: No progress output when piped
5. **Handle Large Data**: Stream when needed

## Testing Strategy

```python
import subprocess
import tempfile

def test_stdin_detection():
    """Test stdin detection and reading"""

    # Test with piped input
    proc = subprocess.Popen(
        ["echo", "test input"],
        stdout=subprocess.PIPE
    )

    pflow_proc = subprocess.Popen(
        ["python", "-c", """
import sys
sys.path.insert(0, '.')
from shell_integration import detect_stdin, read_stdin
if detect_stdin():
    content = read_stdin()
    print(f"Got: {content.strip()}")
else:
    print("No stdin")
"""],
        stdin=proc.stdout,
        stdout=subprocess.PIPE,
        text=True
    )

    output, _ = pflow_proc.communicate()
    assert "Got: test input" in output

def test_exit_codes():
    """Test proper exit code propagation"""

    # Test success
    proc = subprocess.run(
        ["pflow", "test-success"],
        capture_output=True
    )
    assert proc.returncode == 0

    # Test file not found
    proc = subprocess.run(
        ["pflow", "read-file", "--path=nonexistent.txt"],
        capture_output=True
    )
    assert proc.returncode == 74  # EXIT_IOERR

def test_signal_handling():
    """Test graceful interruption"""

    # Start long-running process
    proc = subprocess.Popen(
        ["pflow", "long-task"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Send interrupt
    import time
    time.sleep(0.1)
    proc.send_signal(signal.SIGINT)

    # Check exit code
    proc.wait()
    assert proc.returncode == 130  # 128 + SIGINT
```

## Integration Points

### Connection to Task 3 (Hello World)
Task 8 provides stdin initialization used by Task 3:
```python
# Task 8 provides
shared = initialize_shared_with_stdin({})

# Task 3 uses
flow.run(shared)  # stdin already populated if available
```

### Connection to Task 11 (File Nodes)
stdin can replace file reading:
```python
# Traditional file reading
pflow read-file --path=input.txt >> process

# Unix pipe alternative
cat input.txt | pflow process
# process node reads from shared["stdin"] instead
```

### Connection to Task 23 (Execution Tracing)
Include stdin in traces:
```python
if "stdin" in shared:
    trace["stdin_preview"] = shared["stdin"][:100] + "..."
    trace["stdin_size"] = len(shared["stdin"])
```

## Minimal Test Case

```python
# Save as test_shell_integration.py
import os
import sys
import select
import signal
import tempfile
import subprocess

def detect_stdin():
    """Minimal stdin detection"""
    return not sys.stdin.isatty()

def test_pipe_integration():
    """Test complete pipe integration"""

    # Create test script
    test_script = '''
import sys
sys.path.insert(0, '.')

def detect_stdin():
    return not sys.stdin.isatty()

def main():
    shared = {}

    # Read stdin if available
    if detect_stdin():
        shared["stdin"] = sys.stdin.read()

    # Process
    if "stdin" in shared:
        result = shared["stdin"].upper()
        print(result, end='')
        sys.exit(0)
    else:
        sys.stderr.write("No input\\n")
        sys.exit(2)

if __name__ == "__main__":
    main()
'''

    # Test 1: Pipe input
    proc = subprocess.run(
        ["echo", "hello world"],
        stdout=subprocess.PIPE
    )

    result = subprocess.run(
        [sys.executable, "-c", test_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        input=proc.stdout,
        text=True
    )

    assert result.stdout == "HELLO WORLD\n"
    assert result.returncode == 0

    # Test 2: No input
    result = subprocess.run(
        [sys.executable, "-c", test_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    assert "No input" in result.stderr
    assert result.returncode == 2

    print("✓ Shell integration patterns validated")

if __name__ == "__main__":
    test_pipe_integration()
```

## Summary

Task 8's shell integration patterns ensure pflow is a first-class Unix citizen:

1. **Automatic stdin Detection** - Works naturally in pipe chains
2. **Proper Exit Codes** - Scriptable and automation-friendly
3. **Signal Handling** - Graceful interruption with cleanup
4. **Stream Support** - Handles both small and large inputs
5. **Unix Philosophy** - Silent operation, stderr for messages

These patterns make pflow feel native to shell users while maintaining compatibility with the >> operator for flow composition.
