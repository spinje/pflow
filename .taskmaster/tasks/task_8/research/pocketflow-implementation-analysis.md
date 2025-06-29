# Task 8: Shell Integration - PocketFlow Implementation Analysis

## Why Shell Integration Needs PocketFlow

Shell integration involves multiple I/O operations, timeout handling, signal management, and different execution paths based on input type. It's a classic orchestration problem.

### The Shell Integration Flow

```
Start
  │
  ├─> Detect Stdin ─> Has Data ─> Read Stdin ─> Check Size ─┐
  │                      │                           │        │
  │                      └─> No Data ────────────────────────┤
  │                                                           │
  ├─> Setup Signal Handlers ──────────────────────────────> │
  │                                                           │
  └─> Check TTY Mode ─────────────────────────────────────> │
                                                              │
                                                              v
                                                     Process Input
                                                              │
                                    ┌─────────────────────────┼─────────────────┐
                                    │                         │                 │
                                    v                         v                 v
                              Small Input              Large Input        Timeout/Error
                                    │                         │                 │
                                    v                         v                 v
                              Direct Read              Stream Chunks        Handle Error
                                    │                         │                 │
                                    └─────────────────────────┴─────────────────┘
                                                              │
                                                              v
                                                        Write Output
                                                              │
                                                              v
                                                      Exit with Code
```

### Critical Requirements

1. **Stdin Detection** - Must detect piped vs interactive
2. **Timeout Handling** - Stdin reads can hang
3. **Large Data Streaming** - Can't load 1GB into memory
4. **Signal Handling** - Ctrl+C must work properly
5. **Exit Codes** - Must propagate for shell scripts

### Why PocketFlow Excels Here

#### 1. Multiple I/O Operations with Failure Modes

```python
class ReadStdinNode(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=0.5)

    def exec(self, shared):
        if not shared.get("has_stdin"):
            return "no_stdin"

        try:
            # Read with timeout
            content = self._read_with_timeout(sys.stdin, timeout=5)
            shared["stdin"] = content
            shared["stdin_size"] = len(content)

            # Route based on size
            if len(content) > 1_000_000:
                return "large_input"
            else:
                return "normal_input"

        except TimeoutError:
            shared["stdin_error"] = "Timeout reading stdin"
            return "timeout"
        except UnicodeDecodeError as e:
            shared["stdin_error"] = f"Encoding error: {e}"
            return "encoding_error"

    def exec_fallback(self, shared, exc):
        # Graceful degradation
        shared["stdin"] = ""
        shared["stdin_error"] = str(exc)
        return "error"
```

#### 2. Complex Branching Logic

```python
class ShellIntegrationFlow(Flow):
    def __init__(self):
        super().__init__()

        # Setup nodes
        detect = DetectStdinNode()
        setup_signals = SetupSignalHandlersNode()
        read_stdin = ReadStdinNode()
        stream_stdin = StreamStdinNode()
        process = ProcessInputNode()
        output = WriteOutputNode()

        # Main flow
        self.start(detect)

        # Stdin routing
        detect - "has_stdin" >> read_stdin
        detect - "no_stdin" >> process

        # Size-based routing
        read_stdin - "normal_input" >> process
        read_stdin - "large_input" >> stream_stdin
        read_stdin - "timeout" >> TimeoutHandler()
        read_stdin - "encoding_error" >> EncodingHandler()

        # Streaming path
        stream_stdin >> process

        # All paths lead to output
        process >> output
```

#### 3. Timeout and Signal Handling

```python
class SetupSignalHandlersNode(Node):
    def exec(self, shared):
        def sigint_handler(signum, frame):
            # Clean shutdown
            shared["interrupted"] = True
            if "partial_data" in shared:
                # Save partial data
                self._save_partial(shared["partial_data"])
            sys.exit(130)  # Standard SIGINT exit code

        signal.signal(signal.SIGINT, sigint_handler)
        shared["signals_ready"] = True
        return "continue"

class StreamStdinNode(Node):
    def exec(self, shared):
        chunks = []
        total_size = 0

        while True:
            if shared.get("interrupted"):
                break

            chunk = sys.stdin.read(8192)
            if not chunk:
                break

            chunks.append(chunk)
            total_size += len(chunk)

            # Update progress
            shared["bytes_read"] = total_size

            # Memory limit check
            if total_size > 100_000_000:  # 100MB limit
                shared["stdin_chunks"] = chunks
                return "memory_limit"

        shared["stdin"] = "".join(chunks)
        return "complete"
```

### Traditional Approach Problems

```python
# Traditional code becomes a mess
def handle_shell_integration():
    # Signal handling
    signal.signal(signal.SIGINT, lambda: sys.exit(130))

    # Stdin detection
    if not sys.stdin.isatty():
        try:
            # Set timeout (complex!)
            old_settings = termios.tcgetattr(sys.stdin)
            try:
                # Read stdin
                content = sys.stdin.read()

                # Handle large input
                if len(content) > 1000000:
                    # Now what? Need streaming...
                    # Getting complex already

            except Exception as e:
                # Error handling
                # But which error?
                # How to recover?
            finally:
                # Restore terminal
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    # Exit codes
    # Where do we handle different exit scenarios?
```

Issues:
- Signal handling mixed with business logic
- No clear timeout strategy
- Error handling scattered
- Hard to test (how to mock stdin?)
- No clear flow visibility

### PocketFlow Benefits for Shell Integration

#### 1. Testable I/O Operations

```python
def test_stdin_timeout():
    flow = ShellIntegrationFlow()

    # Mock stdin that hangs
    mock_stdin = MockStdin(hang=True)

    result = flow.run({
        "stdin_object": mock_stdin,
        "timeout": 1
    })

    assert result["stdin_error"] == "Timeout reading stdin"
    assert result["exit_code"] == 1
```

#### 2. Clear Error Recovery

```python
class EncodingHandler(Node):
    def exec(self, shared):
        # Try different encodings
        raw_bytes = shared.get("stdin_raw_bytes")

        for encoding in ["utf-8", "latin-1", "cp1252"]:
            try:
                content = raw_bytes.decode(encoding)
                shared["stdin"] = content
                shared["encoding_used"] = encoding
                return "recovered"
            except:
                continue

        # Fallback to ignore errors
        shared["stdin"] = raw_bytes.decode("utf-8", errors="ignore")
        shared["encoding_warning"] = "Used lossy decoding"
        return "degraded"
```

#### 3. Performance Monitoring

```python
class PerformanceMonitorNode(Node):
    def exec(self, shared):
        shared["timing"] = {
            "stdin_read": shared.get("stdin_read_time", 0),
            "processing": shared.get("process_time", 0),
            "output_write": shared.get("output_time", 0)
        }

        if shared["timing"]["stdin_read"] > 2.0:
            logger.warning("Slow stdin read detected")

        return "continue"
```

### Real-World Scenarios

#### Piped Input from Large Command
```bash
find / -name "*.log" 2>/dev/null | pflow process
```
- Needs streaming to handle potentially huge input
- Must handle Ctrl+C gracefully
- Should show progress for long operations

#### Script Integration
```bash
if pflow validate < data.json; then
    echo "Valid"
else
    echo "Invalid"
fi
```
- Must return proper exit codes
- Should handle malformed input gracefully
- Timeout protection needed

#### Interactive Mode Detection
```python
class DetectModeNode(Node):
    def exec(self, shared):
        # Complex detection logic
        if not sys.stdin.isatty():
            shared["mode"] = "piped"
        elif sys.stdout.isatty():
            shared["mode"] = "interactive"
        else:
            shared["mode"] = "scripted"

        return shared["mode"]
```

### Conclusion

Shell integration is not just reading stdin - it's a complex orchestration of:
- I/O operations with timeouts
- Signal handling
- Error recovery
- Performance considerations
- Multiple execution modes

PocketFlow provides:
- Clear separation of concerns
- Testable I/O operations
- Explicit error handling
- Timeout management
- Signal handling isolation
- Performance monitoring

The traditional approach would mix all these concerns into an unmaintainable mess. PocketFlow makes the complexity manageable and testable.
