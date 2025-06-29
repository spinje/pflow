# Task 8: Shell Integration - PocketFlow Implementation Guide

## Overview
This task implements shell integration for pflow, handling stdin/stdout pipes, shell operators, and command execution. PocketFlow orchestrates the complex flow of detecting input sources, streaming data, and managing shell interactions.

## PocketFlow Architecture

### Flow Structure
```
DetectInput >> ClassifySource >> ReadInput >> ProcessInput >> ExecuteFlow >> WriteOutput
      |              |               |             |               |              |
      v              v               v             v               v              v
  NoInput      InvalidSource    Timeout      ParseError     ExecError      WriteError
                                   |
                                   v
                              StreamLarge
```

### Key Nodes

#### 1. DetectInputNode
```python
class DetectInputNode(Node):
    """Detect input source (stdin, args, or interactive)"""
    def exec(self, shared):
        # Check for piped stdin
        if not sys.stdin.isatty():
            shared["has_stdin"] = True
            shared["input_source"] = "pipe"
            return "read_stdin"

        # Check for command args
        if shared.get("cli_args"):
            shared["input_source"] = "args"
            return "process_args"

        # Interactive mode
        shared["input_source"] = "interactive"
        return "prompt_user"
```

#### 2. StreamStdinNode
```python
class StreamStdinNode(Node):
    """Handle large stdin with streaming and timeout"""
    def __init__(self):
        super().__init__(max_retries=2, wait=1)

    def exec(self, shared):
        timeout = shared.get("stdin_timeout", 5.0)
        max_size = shared.get("max_stdin_size", 10 * 1024 * 1024)  # 10MB

        chunks = []
        total_size = 0

        with self._timeout_handler(timeout):
            while True:
                chunk = sys.stdin.read(8192)  # 8KB chunks
                if not chunk:
                    break

                chunks.append(chunk)
                total_size += len(chunk)

                if total_size > max_size:
                    shared["stdin_truncated"] = True
                    shared["truncated_size"] = total_size
                    break

        shared["stdin_content"] = "".join(chunks)
        return "parse_input"

    def exec_fallback(self, shared, exc):
        if isinstance(exc, TimeoutError):
            shared["error"] = "Stdin read timeout"
            return "timeout_error"
        return "read_error"
```

#### 3. ShellExecutorNode
```python
class ShellExecutorNode(Node):
    """Execute pflow with shell operator support"""
    def __init__(self, executor):
        super().__init__()
        self.executor = executor

    def exec(self, shared):
        command = shared["parsed_command"]
        input_data = shared.get("stdin_content", "")

        # Handle different operators
        if ">>" in command:
            # Append output
            shared["output_mode"] = "append"
            return "execute_flow"
        elif ">" in command:
            # Redirect output
            shared["output_mode"] = "redirect"
            return "execute_flow"
        elif "|" in command:
            # Pipe to next command
            shared["output_mode"] = "pipe"
            return "execute_pipeline"
        else:
            # Standard output
            shared["output_mode"] = "stdout"
            return "execute_flow"
```

#### 4. OutputWriterNode
```python
class OutputWriterNode(Node):
    """Write output based on shell operators"""
    def __init__(self):
        super().__init__(max_retries=3)

    def exec(self, shared):
        output = shared["flow_output"]
        mode = shared["output_mode"]

        if mode == "stdout":
            sys.stdout.write(output)
            sys.stdout.flush()
        elif mode == "redirect":
            filename = shared["redirect_target"]
            with open(filename, 'w') as f:
                f.write(output)
        elif mode == "append":
            filename = shared["append_target"]
            with open(filename, 'a') as f:
                f.write(output)
        elif mode == "pipe":
            # Output already in shared for next command
            shared["pipe_output"] = output

        return "success"
```

## Implementation Plan

### Phase 1: Input Detection
1. Create `src/pflow/flows/shell/` directory
2. Implement input detection nodes
3. Handle stdin timeout and size limits
4. Create input classification logic

### Phase 2: Shell Parsing
1. Parse shell operators (>, >>, |)
2. Extract pflow commands
3. Handle quoted strings
4. Support environment variables

### Phase 3: Execution Integration
1. Connect to pflow executor
2. Pass stdin data to flows
3. Capture flow output
4. Handle execution errors

### Phase 4: Output Handling
1. Implement output modes
2. File redirection with retry
3. Pipeline support
4. Error stream handling

## Testing Strategy

### Unit Tests
```python
def test_stdin_timeout():
    """Test stdin read timeout handling"""
    node = StreamStdinNode()

    # Mock stdin that never completes
    with patch('sys.stdin') as mock_stdin:
        mock_stdin.read.side_effect = lambda x: time.sleep(10)

        shared = {"stdin_timeout": 0.1}
        result = node.exec(shared)

        assert result == "timeout_error"
        assert "error" in shared
```

### Integration Tests
```python
def test_pipe_integration():
    """Test full pipe: echo "data" | pflow process >> output.txt"""
    flow = create_shell_flow()

    # Simulate piped input
    with patch('sys.stdin') as mock_stdin:
        mock_stdin.isatty.return_value = False
        mock_stdin.read.return_value = "test data"

        result = flow.run({
            "cli_args": ["process", ">>", "output.txt"]
        })

        assert result["output_mode"] == "append"
        assert Path("output.txt").exists()
```

## Shell Integration Patterns

### Operator Handling
```python
SHELL_OPERATORS = {
    ">>": "append",
    ">": "redirect",
    "|": "pipe",
    "2>": "error_redirect",
    "&>": "all_redirect"
}

class OperatorParserNode(Node):
    def exec(self, shared):
        command = shared["raw_command"]

        for op, mode in SHELL_OPERATORS.items():
            if op in command:
                parts = command.split(op, 1)
                shared["pflow_command"] = parts[0].strip()
                shared["operator"] = op
                shared["operator_arg"] = parts[1].strip()
                return f"handle_{mode}"

        # No operators
        shared["pflow_command"] = command
        return "execute_simple"
```

### Error Stream Handling
```python
class ErrorStreamNode(Node):
    """Separate stdout and stderr handling"""
    def exec(self, shared):
        if shared.get("capture_stderr"):
            # Capture both streams
            shared["stdout"] = []
            shared["stderr"] = []
            return "execute_with_capture"
        else:
            # Normal execution
            return "execute_normal"
```

## Benefits of PocketFlow Approach

1. **Timeout Handling**: Built-in timeout for stdin reads
2. **Stream Processing**: Handle large inputs gracefully
3. **Retry Logic**: File operations with automatic retry
4. **Clear Flow**: Shell operation flow is visual
5. **Error Recovery**: Each operation has error paths

## Shell-Specific Features

### Signal Handling
```python
class SignalHandlerNode(Node):
    """Handle SIGPIPE and other shell signals"""
    def prep(self, shared):
        # Set up signal handlers
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    def exec(self, shared):
        # Process with signal handling
        return "continue"

    def post(self, shared):
        # Restore default handlers
        pass
```

### Exit Code Management
```python
class ExitCodeNode(Node):
    """Set appropriate exit codes"""
    def exec(self, shared):
        if "error" in shared:
            shared["exit_code"] = 1
        elif shared.get("validation_failed"):
            shared["exit_code"] = 2
        else:
            shared["exit_code"] = 0
        return "cleanup"
```

## Performance Optimizations

1. **Streaming**: Process large inputs in chunks
2. **Lazy Loading**: Only load what's needed
3. **Buffer Management**: Efficient memory usage
4. **Parallel Processing**: When possible

## Integration Points

- **CLI Parser**: Extract commands and arguments
- **Flow Executor**: Run pflow workflows
- **File System**: Handle redirections
- **Process Manager**: Pipeline execution

## Future Extensions

1. **Background Jobs**: Support & operator
2. **Process Substitution**: Support <() and >()
3. **Shell Variables**: Environment integration
4. **Tab Completion**: Shell completion hooks
