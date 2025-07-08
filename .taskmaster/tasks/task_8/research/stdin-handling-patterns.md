# stdin Handling Patterns

## Overview

Proper stdin handling enables pflow to integrate seamlessly with Unix pipelines. This document covers detection, reading, streaming, and shared store population patterns.

## Detection Patterns

### Basic Detection
```python
import sys

def detect_stdin():
    """Check if stdin has piped data."""
    return not sys.stdin.isatty()
```

### Comprehensive Detection
```python
def get_input_source():
    """Determine where input is coming from."""
    if not sys.stdin.isatty():
        # Data is piped in
        return "pipe"
    elif sys.stdin.isatty() and len(sys.argv) > 1:
        # Arguments provided
        return "args"
    else:
        # Interactive mode
        return "interactive"
```

## Reading Patterns

### Simple Read (Small Data)
```python
def read_stdin_simple():
    """Read all stdin at once - suitable for small inputs."""
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return None
```

### Buffered Read (Large Data)
```python
def read_stdin_buffered(chunk_size=8192):
    """Read stdin in chunks - memory efficient for large inputs."""
    if not sys.stdin.isatty():
        chunks = []
        while True:
            chunk = sys.stdin.read(chunk_size)
            if not chunk:
                break
            chunks.append(chunk)
        return ''.join(chunks)
    return None
```

### Line-by-Line Read (Streaming)
```python
def read_stdin_lines():
    """Read stdin line by line - for streaming processing."""
    if not sys.stdin.isatty():
        for line in sys.stdin:
            yield line.rstrip('\n')
```

## Encoding Handling

### UTF-8 with Fallback
```python
def read_stdin_safe():
    """Read stdin with encoding safety."""
    import locale

    if not sys.stdin.isatty():
        # Try UTF-8 first
        try:
            return sys.stdin.read()
        except UnicodeDecodeError:
            # Fallback to system locale
            encoding = locale.getpreferredencoding()
            return sys.stdin.buffer.read().decode(encoding, errors='replace')
```

### Binary Data Handling
```python
def read_stdin_binary():
    """Read binary data from stdin."""
    if not sys.stdin.isatty():
        # Use buffer for binary data
        return sys.stdin.buffer.read()
```

## Shared Store Population

### Basic Population
```python
def populate_shared_from_stdin(shared):
    """Add stdin content to shared store."""
    stdin_content = read_stdin_simple()
    if stdin_content:
        shared["stdin"] = stdin_content
        # Also populate common aliases
        shared["input"] = stdin_content
        shared["content"] = stdin_content
```

### Smart Population
```python
def smart_populate_shared(shared, stdin_content):
    """Intelligently populate shared store based on content type."""
    if not stdin_content:
        return

    # Always set stdin
    shared["stdin"] = stdin_content

    # Try to parse as JSON
    try:
        data = json.loads(stdin_content)
        shared["json_data"] = data
        if isinstance(data, dict):
            # Flatten top-level keys
            for key, value in data.items():
                if key not in shared:
                    shared[key] = value
    except json.JSONDecodeError:
        pass

    # Check if it's a file path
    if len(stdin_content.splitlines()) == 1 and os.path.exists(stdin_content):
        shared["file_path"] = stdin_content

    # Multi-line content
    lines = stdin_content.splitlines()
    if len(lines) > 1:
        shared["lines"] = lines
        shared["line_count"] = len(lines)
```

## Integration with CLI Flow

### Early stdin Handling
```python
def main():
    """Main CLI entry point."""
    # Handle stdin early
    stdin_content = None
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read()

    # Now parse arguments
    # stdin_content is available for use
```

### Combined Input Handling
```python
def get_workflow_input(args, stdin_content):
    """Combine various input sources."""
    # Priority: explicit file > stdin > arguments

    if args.file:
        return read_file(args.file), "file"
    elif stdin_content:
        return stdin_content, "stdin"
    elif args.workflow:
        return " ".join(args.workflow), "args"
    else:
        return None, None
```

## Edge Cases

### Empty stdin
```python
def handle_empty_stdin():
    """Handle case where stdin is connected but empty."""
    content = read_stdin_simple()
    if content == "":
        # Distinguish between no stdin and empty stdin
        return None  # Treat as no input
    return content
```

### Very Large stdin
```python
def handle_large_stdin(max_size=100_000_000):  # 100MB limit
    """Handle very large stdin with size limits."""
    if not sys.stdin.isatty():
        size = 0
        chunks = []

        while size < max_size:
            chunk = sys.stdin.read(8192)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)

        if size >= max_size:
            raise ValueError("stdin too large (>100MB)")

        return ''.join(chunks)
```

### Binary Detection
```python
def is_binary_stdin():
    """Detect if stdin contains binary data."""
    if not sys.stdin.isatty():
        # Read small sample
        sample = sys.stdin.buffer.read(512)
        sys.stdin.buffer.seek(0)  # Reset

        # Check for null bytes (common in binary)
        if b'\x00' in sample:
            return True

        # Check if valid UTF-8
        try:
            sample.decode('utf-8')
            return False
        except UnicodeDecodeError:
            return True
```

## Error Handling

### Graceful Failures
```python
def safe_stdin_read():
    """Read stdin with comprehensive error handling."""
    try:
        if not sys.stdin.isatty():
            return sys.stdin.read()
    except KeyboardInterrupt:
        # Ctrl+C during read
        sys.exit(130)
    except IOError as e:
        # Broken pipe or other IO errors
        if e.errno == errno.EPIPE:
            sys.exit(0)  # Normal for pipes
        else:
            click.echo(f"Error reading stdin: {e}", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error reading stdin: {e}", err=True)
        sys.exit(1)

    return None
```

## Testing Patterns

### Mock stdin for Testing
```python
import io
import contextlib

@contextlib.contextmanager
def mock_stdin(content):
    """Mock stdin for testing."""
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(content)
    # Make it look like piped input
    sys.stdin.isatty = lambda: False
    try:
        yield
    finally:
        sys.stdin = old_stdin
```

### Test Cases
```python
def test_stdin_detection():
    """Test stdin detection logic."""
    # No stdin
    assert detect_stdin() == False

    # With stdin
    with mock_stdin("test data"):
        assert detect_stdin() == True

def test_stdin_reading():
    """Test reading from stdin."""
    with mock_stdin("hello\nworld"):
        content = read_stdin_simple()
        assert content == "hello\nworld"

def test_empty_stdin():
    """Test empty stdin handling."""
    with mock_stdin(""):
        content = read_stdin_simple()
        assert content == ""
```

## Performance Considerations

### Memory Usage
```python
# Bad: Loads entire stdin into memory
content = sys.stdin.read()  # Could be gigabytes!

# Good: Process in chunks
for chunk in read_stdin_chunks():
    process(chunk)
```

### Response Time
```python
# Bad: Wait for all stdin before processing
all_data = sys.stdin.read()
process(all_data)

# Good: Start processing as data arrives
for line in sys.stdin:
    process(line)
    # User sees output sooner
```

## Integration Examples

### With pflow Workflows
```bash
# Simple text processing
echo "Hello, World!" | pflow uppercase

# File list processing
find . -name "*.py" | pflow analyze-code

# JSON data processing
curl api.example.com/data | pflow process-json

# Log analysis
tail -f app.log | pflow monitor-errors
```

### Shared Store Population Examples
```python
# Text input
echo "Analyze this text" | pflow
# shared["stdin"] = "Analyze this text"
# shared["content"] = "Analyze this text"

# JSON input
echo '{"user": "john", "age": 30}' | pflow
# shared["stdin"] = '{"user": "john", "age": 30}'
# shared["json_data"] = {"user": "john", "age": 30}
# shared["user"] = "john"
# shared["age"] = 30

# File path input
echo "/path/to/file.txt" | pflow
# shared["stdin"] = "/path/to/file.txt"
# shared["file_path"] = "/path/to/file.txt"
```

## Best Practices

1. **Always check isatty()** before reading stdin
2. **Handle empty stdin** gracefully
3. **Set reasonable size limits** for safety
4. **Populate multiple shared keys** for flexibility
5. **Stream when possible** for large data
6. **Test with various input types** (text, JSON, binary)
7. **Document which shared keys** are populated

## Remember

stdin handling is often the first interaction users have with pflow in a pipeline. Make it smooth, predictable, and error-free to build trust in the tool.
