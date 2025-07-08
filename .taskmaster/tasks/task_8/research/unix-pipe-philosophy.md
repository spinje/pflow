# Unix Pipe Philosophy & pflow Integration

## Core Unix Philosophy

"Write programs that do one thing and do it well. Write programs to work together. Write programs to handle text streams, because that is a universal interface." - Doug McIlroy

## How pflow Embodies Unix Philosophy

### 1. Do One Thing Well
Each pflow node is focused:
- `read-file`: Reads files
- `github-get-issue`: Gets GitHub issues
- `llm`: Processes text with LLM

Not:
- `read-file-and-analyze-and-save`: Too many responsibilities

### 2. Work Together
Nodes compose via the `>>` operator:
```bash
pflow read-file >> llm >> write-file
```

This mirrors Unix pipes:
```bash
cat file.txt | process | tee output.txt
```

### 3. Text Streams as Universal Interface
The shared store with natural keys is pflow's "text stream":
- `shared["content"]` = Universal text data
- `shared["output"]` = Command output
- Nodes communicate through these common interfaces

## Integration Patterns

### 1. stdin as Input Source
```bash
# Unix way
echo "analyze this" | pflow

# Becomes
shared["stdin"] = "analyze this"
```

### 2. stdout as Output Destination
```bash
# Workflow output goes to stdout
pflow analyze-text | grep "important"
```

### 3. Exit Codes for Scripting
```bash
# Success
pflow workflow && echo "Success!"

# Failure
pflow workflow || echo "Failed!"
```

### 4. Composable with Unix Tools
```bash
# Find files and process with pflow
find . -name "*.log" | pflow analyze-logs

# Generate data and visualize
pflow generate-report | gnuplot
```

## Design Principles

### 1. Silence is Golden
```bash
# Good: Only output results
$ pflow analyze-data
Results: 42

# Bad: Chatty output
$ pflow analyze-data
Loading nodes...
Initializing...
Processing...
Results: 42
```

### 2. Expect the Unexpected
```bash
# Handle empty stdin
echo "" | pflow  # Should not crash

# Handle large inputs
cat huge-file.txt | pflow  # Should stream, not load all
```

### 3. Be Liberal in What You Accept
```bash
# Multiple input formats
echo "data" | pflow
pflow < file.txt
pflow --file workflow.json
pflow "natural language"
```

### 4. Be Conservative in What You Send
```bash
# Clean, parseable output
$ pflow list-items
item1
item2
item3

# Not JSON by default (unless requested)
$ pflow list-items --format=json
["item1", "item2", "item3"]
```

## Implementation Details

### Detecting Piped Input
```python
import sys

if not sys.stdin.isatty():
    # stdin is piped
    stdin_content = sys.stdin.read()
    shared["stdin"] = stdin_content
```

### Streaming Large Inputs
```python
def read_stdin_streaming():
    """Read stdin in chunks for large inputs."""
    CHUNK_SIZE = 8192
    chunks = []

    while True:
        chunk = sys.stdin.read(CHUNK_SIZE)
        if not chunk:
            break
        chunks.append(chunk)

    return ''.join(chunks)
```

### Proper Exit Codes
```python
# Success
sys.exit(0)

# General error
sys.exit(1)

# Usage error
sys.exit(2)

# Cannot execute
sys.exit(126)

# Command not found
sys.exit(127)

# Interrupted (Ctrl+C)
sys.exit(130)
```

### Signal Handling
```python
import signal

def handle_sigint(signum, frame):
    """Handle Ctrl+C gracefully."""
    # Cleanup
    cleanup_resources()
    # Exit with standard code
    sys.exit(130)

signal.signal(signal.SIGINT, handle_sigint)
```

## Unix Tool Interoperability

### Input Patterns
```bash
# From file listing
ls *.csv | pflow process-files

# From grep results
grep ERROR app.log | pflow analyze-errors

# From curl
curl api.example.com/data | pflow process-json
```

### Output Patterns
```bash
# To file
pflow generate-report > report.txt

# To another command
pflow list-tasks | wc -l

# To multiple destinations
pflow analyze | tee results.txt | mail -s "Results" user@example.com
```

### Error Handling
```bash
# Errors go to stderr
pflow bad-workflow 2> error.log

# Separate streams
pflow workflow > output.txt 2> error.log

# Combine streams
pflow workflow &> full.log
```

## Best Practices

### 1. Line-Oriented Output
```python
# Good: One item per line
for item in results:
    print(item)

# Bad: Custom format
print(f"Items: {', '.join(results)}")
```

### 2. No Interactive Prompts in Pipe Mode
```python
if sys.stdin.isatty():
    # Interactive mode - can prompt
    response = input("Continue? ")
else:
    # Pipe mode - use defaults
    response = "yes"
```

### 3. Respect SIGPIPE
```python
# Handle broken pipe gracefully
try:
    print(output)
except BrokenPipeError:
    # Reader closed their end
    sys.exit(0)
```

### 4. Support Standard Flags
```bash
pflow --help      # Show help
pflow --version   # Show version
pflow -q          # Quiet mode
pflow -v          # Verbose mode
```

## Testing Unix Integration

### Test Piping
```bash
# Test empty input
echo "" | pflow

# Test large input
dd if=/dev/urandom bs=1M count=10 | pflow

# Test binary input (should handle gracefully)
cat /bin/ls | pflow
```

### Test Exit Codes
```bash
# Success case
pflow workflow
echo $?  # Should be 0

# Error case
pflow nonexistent
echo $?  # Should be non-zero
```

### Test Signal Handling
```bash
# Start long-running workflow
pflow long-workflow &
PID=$!

# Send interrupt
kill -INT $PID

# Check exit code
wait $PID
echo $?  # Should be 130
```

## Integration with pflow Design

The Unix philosophy reinforces pflow's design:

1. **Nodes = Unix Commands**: Single-purpose, composable
2. **Shared Store = Pipes**: Data flows between components
3. **Workflows = Shell Scripts**: Saved combinations of commands
4. **Natural Language = Shell Aliases**: Easy invocation of complex operations

## Remember

pflow should feel like a natural extension of Unix, not a foreign system. When in doubt, ask "What would `cat` do?" and follow that pattern.
