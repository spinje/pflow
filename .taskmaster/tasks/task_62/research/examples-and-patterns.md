# Examples and Patterns for stdin Routing

## Real-World Use Cases

### Use Case 1: Data Processing Pipeline

**User Need**: Process CSV data from various sources

```bash
# From stdin (common in data pipelines)
curl -s https://api.example.com/data.csv | pflow "analyze sales data"

# From file (batch processing)
pflow "analyze sales data" data_file=monthly_sales.csv

# Same workflow handles both!
```

**Parameter Discovery Output**:
```json
// With stdin
{"sales_data": "${stdin}"}

// With explicit file
{"sales_data": "monthly_sales.csv"}
```

### Use Case 2: Log Analysis

**User Need**: Analyze logs from different sources

```bash
# Real-time log streaming
tail -f app.log | pflow "detect errors and alert"

# Historical log analysis
pflow "detect errors" log_file=/var/log/app.log

# Docker logs piped
docker logs container_id | pflow "analyze performance"
```

### Use Case 3: Text Transformation

**User Need**: Transform text data

```bash
# From clipboard (macOS)
pbpaste | pflow "format as markdown"

# From file
pflow "format as markdown" input_file=notes.txt

# From command output
ls -la | pflow "create a summary table"
```

## Pattern Library

### Pattern 1: Generic Data References

**User says**: "the data", "the file", "the input"
**stdin present**: Yes
**Result**: Route to stdin

```python
# Input
user_input = "analyze the data"
stdin_info = {"type": "text", "preview": "..."}

# Output
parameters = {"data": "${stdin}"}
```

### Pattern 2: Explicit Path Override

**User says**: Specific file name/path
**stdin present**: Yes (but ignored)
**Result**: Use explicit path

```python
# Input
user_input = "analyze sales.csv"
stdin_info = {"type": "text", "preview": "..."}

# Output
parameters = {"data_file": "sales.csv"}
```

### Pattern 3: Multiple Inputs

**User says**: Multiple data references
**stdin present**: Yes
**Result**: stdin fills first generic reference

```python
# Input
user_input = "compare the data with baseline.csv"
stdin_info = {"type": "text", "preview": "..."}

# Output
parameters = {
    "data": "${stdin}",
    "baseline": "baseline.csv"
}
```

### Pattern 4: Action Without Data

**User says**: Action only
**stdin present**: Yes
**Result**: Infer data parameter from stdin

```python
# Input
user_input = "summarize"
stdin_info = {"type": "text", "preview": "..."}

# Output
parameters = {"input": "${stdin}"}
```

### Pattern 5: Explicit stdin Reference

**User says**: "piped data", "stdin"
**stdin present**: Yes
**Result**: Direct stdin mapping

```python
# Input
user_input = "process the piped data"
stdin_info = {"type": "text", "preview": "..."}

# Output
parameters = {"piped_data": "${stdin}"}
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Forcing stdin When Inappropriate

```python
# ❌ WRONG
user_input = "generate random data"
stdin_info = {"type": "text", "preview": "..."}
# Don't route stdin - generation doesn't need input

# ✅ CORRECT
parameters = {}  # No input needed for generation
```

### Anti-Pattern 2: Type Mismatches

```python
# ❌ WRONG
user_input = "analyze the image"
stdin_info = {"type": "text", "preview": "csv,data"}
# Don't route text stdin for image processing

# ✅ CORRECT
parameters = {}  # Request image file path from user
```

### Anti-Pattern 3: Overriding Explicit Paths

```python
# ❌ WRONG
user_input = "read config.json"
stdin_info = {"type": "text", "preview": "other data"}
parameters = {"config": "${stdin}"}  # NO! User wants config.json

# ✅ CORRECT
parameters = {"config": "config.json"}  # Respect explicit path
```

## Workflow Examples

### Example 1: CSV Processing Workflow

```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "csv_data": {
      "type": "string",
      "required": true,
      "description": "CSV data to process"
    }
  },
  "nodes": [
    {
      "id": "parse",
      "type": "shell",
      "params": {
        "command": "echo '${csv_data}' | python -c 'import csv; ...'"
      }
    }
  ]
}
```

**Works with both**:
```bash
cat data.csv | pflow csv-processor
pflow csv-processor csv_data=file.csv
```

### Example 2: Text Analysis Workflow

```json
{
  "inputs": {
    "text": {
      "type": "string",
      "required": true
    }
  },
  "nodes": [
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Analyze this text: ${text}"
      }
    }
  ]
}
```

**Parameter discovery handles**:
```bash
# stdin: "Process the document" → {"text": "${stdin}"}
# file: "Process document.txt" → {"text": "document.txt"}
```

### Example 3: Multi-Input Workflow

```json
{
  "inputs": {
    "source_data": {"type": "string", "required": true},
    "template": {"type": "string", "required": true}
  },
  "nodes": [
    {
      "id": "transform",
      "type": "shell",
      "params": {
        "command": "transform --data '${source_data}' --template '${template}'"
      }
    }
  ]
}
```

**Parameter discovery with stdin**:
```bash
# "Apply template.json to the data" + stdin
# → {"source_data": "${stdin}", "template": "template.json"}
```

## Edge Cases and Solutions

### Edge Case 1: Empty stdin

```python
stdin_info = {"type": "text", "preview": ""}
user_input = "process the data"

# Solution: Don't route empty stdin
parameters = {}  # Request file path
```

### Edge Case 2: Binary stdin for Text Processing

```python
stdin_info = {"type": "binary", "size": "1048576"}
user_input = "analyze the text"

# Solution: Type mismatch - don't route
parameters = {}  # Request text file
```

### Edge Case 3: Ambiguous References

```python
user_input = "process the file using the data"
stdin_info = {"type": "text", "preview": "..."}

# Solution: Map stdin to most generic reference
parameters = {
    "data": "${stdin}",
    "file": ""  # Request this from user
}
```

## Testing Patterns

### Test Pattern 1: Basic Routing

```python
@pytest.mark.parametrize("input,expected", [
    ("analyze the data", {"data": "${stdin}"}),
    ("process the file", {"file": "${stdin}"}),
    ("transform the input", {"input": "${stdin}"}),
])
def test_stdin_routing(input, expected):
    result = discover_parameters(
        input,
        stdin_info={"type": "text", "preview": "..."}
    )
    assert result == expected
```

### Test Pattern 2: Override Behavior

```python
@pytest.mark.parametrize("input,expected", [
    ("analyze data.csv", {"data_file": "data.csv"}),
    ("process /tmp/file.txt", {"file": "/tmp/file.txt"}),
    ("read config.json", {"config": "config.json"}),
])
def test_explicit_path_overrides(input, expected):
    result = discover_parameters(
        input,
        stdin_info={"type": "text", "preview": "..."}
    )
    assert result == expected
    # stdin is present but ignored
```

### Test Pattern 3: No stdin Scenarios

```python
@pytest.mark.parametrize("input,expected", [
    ("analyze the data", {}),
    ("process the file", {}),
    ("transform the input", {}),
])
def test_no_stdin_handling(input, expected):
    result = discover_parameters(input, stdin_info=None)
    assert result == expected
    # Should request file paths
```

## Migration Guide

### For Existing Workflows

No changes needed! Existing workflows continue to work:

```json
// This workflow already works with stdin routing
{
  "inputs": {
    "data": {"type": "string"}
  },
  "nodes": [...]
}
```

### For New Workflows

Design with stdin in mind:

```json
{
  "inputs": {
    "input_data": {
      "type": "string",
      "description": "Data to process (file path or content)"
    }
  }
}
```

### For Node Developers

No changes! Keep nodes atomic:

```python
class ProcessNode(Node):
    def exec(self, prep_res):
        # Just process the data
        # Don't care where it came from
        return process(prep_res)
```

## Common Mistakes

### Mistake 1: Hardcoding stdin Checks

```python
# ❌ WRONG: Node checks for stdin
if shared.get("stdin"):
    data = shared["stdin"]
else:
    data = read_file(shared["file_path"])

# ✅ RIGHT: Let parameters handle it
data = shared["input_data"]  # Could be stdin or file content
```

### Mistake 2: Complex Routing Logic

```json
// ❌ WRONG: Workflow handles routing
{
  "nodes": [
    {"id": "check_stdin", "type": "shell", "params": {"command": "[ -n '${stdin}' ]"}},
    // Complex routing logic...
  ]
}

// ✅ RIGHT: Simple parameter reference
{
  "nodes": [
    {"id": "process", "params": {"data": "${input_data}"}}
  ]
}
```

### Mistake 3: Assuming stdin Format

```python
# ❌ WRONG: Assume stdin is always text
parameters = {"csv_data": "${stdin}"}  # What if it's JSON?

# ✅ RIGHT: Check stdin type
if stdin_info["type"] == "text" and "csv" in stdin_info["preview"]:
    parameters = {"csv_data": "${stdin}"}
```

## Conclusion

These examples and patterns demonstrate that stdin routing through parameter discovery is:

1. **Natural**: Matches user expectations
2. **Flexible**: Handles diverse use cases
3. **Simple**: No complex logic needed
4. **Powerful**: Enables Unix-style composability

The key is letting the planner's intelligence handle the routing, keeping workflows and nodes simple and focused.