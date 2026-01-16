# Task 104: Implement Python Code Node for Data Transformation

## ID
104

## Title
Implement Python Code Node for Data Transformation

## Description
Create a native Python code node that executes Python code with direct access to input data as native objects. This solves the shell node limitation of single stdin input and avoids JSON serialization/escaping issues by running Python code in-process.

## Status
not started

## Dependencies
- Task 103: Preserve Inline Object Type in Template Resolution - While not strictly required, Task 103's inline object pattern (`{"a": "${a}", "b": "${b}"}`) could inform how code node handles multiple inputs. However, the code node can proceed independently since it receives inputs as native Python objects, not serialized strings.

## Priority
medium

## Details

### Problem Being Solved

The shell node has fundamental limitations for data transformation:

1. **Single stdin** - Can only pass ONE data source to a shell command
2. **Serialization overhead** - Data must be JSON serialized and deserialized
3. **Escaping complexity** - Python code in shell command strings requires painful escaping
4. **Shell parsing risks** - Quotes, backticks, `$()` in data can break shell commands

Current workaround for multiple inputs requires temp files:
```json
{"id": "save-a", "type": "write-file", "params": {"path": "/tmp/a.json", "content": "${data-a}"}}
{"id": "save-b", "type": "write-file", "params": {"path": "/tmp/b.json", "content": "${data-b}"}}
{"id": "process", "type": "shell", "params": {"command": "python script.py /tmp/a.json /tmp/b.json"}}
```

This is verbose and clunky.

### Proposed Solution

A native Python code node that:
- Receives multiple inputs as **native Python objects** (no serialization)
- Executes Python code **in-process** (no subprocess overhead)
- Returns results directly (no output parsing)

```json
{
  "id": "transform",
  "type": "code",
  "params": {
    "inputs": {"data": "${data}", "config": "${config}"},
    "code": "result = f\"{data['name']} - {config['setting']}\"",
    "requires": []
  }
}
```

Example with dependencies:
```json
{
  "id": "analyze",
  "type": "code",
  "params": {
    "inputs": {"records": "${fetch.result}"},
    "code": "import pandas as pd\ndf = pd.DataFrame(records)\nresult = df.describe().to_dict()",
    "requires": ["pandas"]
  }
}
```

### Design Decisions

**Python-only (MVP)**:
- pflow IS Python, so guaranteed available
- No dependency checks needed
- Can run in-process (fast, simple)
- Later could add jq, JavaScript, etc.

**In-process execution**:
- Use `exec()` with full Python access
- Inputs injected as local variables
- `result` variable captured as output
- All imports allowed (no sandbox restrictions for MVP - see braindump for rationale)

**Interface**:
```python
class CodeNode(Node):
    """Execute Python code with native object inputs."""

    # Params:
    # - inputs: dict mapping variable names to template values
    # - code: Python code string to execute
    # - requires: optional list of package dependencies (documentation/validation)
    # - timeout: optional execution timeout (default: 30s)

    # Outputs:
    # - result: the value of 'result' variable after execution
    # - stdout: captured print() output (optional)
```

**Dependency declaration**:
- Optional `requires` field lists package dependencies: `["pandas", "numpy"]`
- For documentation and future validation (not enforcement for MVP)
- Could enable auto-install or containerization later

### Key Technical Considerations

1. **No Sandbox (MVP Decision)**:
   - Python language-level sandboxing is fundamentally bypassable (object traversal escapes)
   - Users need full Python access (pandas, youtube-transcript-api, etc.)
   - Container-level sandboxing would require serialization, negating native objects value
   - All imports allowed - user's responsibility
   - Consider timeout for runaway code

2. **Error Handling**:
   - Capture Python exceptions with full tracebacks
   - Report line numbers in user's code
   - Clear error messages for missing `result` variable

3. **Variable Injection**:
   - Each key in `inputs` becomes a local variable
   - Types preserved (dict stays dict, list stays list)
   - No JSON serialization needed

4. **Output Capture**:
   - Primary: `result` variable value
   - Optional: capture `print()` statements to `stdout` output

### Comparison with Alternatives

| Approach | Multiple Inputs | Serialization | Code Readability | Error Messages |
|----------|----------------|---------------|------------------|----------------|
| Shell + stdin | ❌ One | ❌ JSON roundtrip | ❌ Escaped strings | ❌ Shell errors |
| Shell + Python -c | ❌ One | ❌ JSON roundtrip | ❌ String in string | ❌ Shell errors |
| Code node | ✅ Unlimited | ✅ Native objects | ✅ Clean code | ✅ Python traceback |

## Test Strategy

### Unit Tests

1. **Basic execution**:
   - Simple code with single input returns correct result
   - Multiple inputs accessible as variables
   - Different types preserved (dict, list, str, int, bool)

2. **Output handling**:
   - `result` variable captured correctly
   - Missing `result` produces clear error
   - `print()` captured to stdout output

3. **Error handling**:
   - Syntax errors report line numbers
   - Runtime errors include traceback
   - Timeout triggers for infinite loops

4. **Import handling**:
   - Standard library imports work (json, re, math, etc.)
   - Third-party imports work if installed (pandas, etc.)
   - Clear error message when import fails (module not found)

### Integration Tests

1. **Workflow integration**:
   - Code node receives template-resolved inputs
   - Output flows to downstream nodes
   - Works with namespacing

2. **Real-world transformations**:
   - Combine two dicts
   - Filter/map list items
   - String formatting with multiple data sources

## Open Questions

1. **`requires` field behavior**: Is it optional or required? What happens when deps aren't installed - error, warning, or just documentation?

2. **Sandbox for MVP**: Dropped per braindump discussion. No restricted builtins, all imports allowed.

3. **Task 107 integration**: How does `requires` appear in markdown frontmatter?
