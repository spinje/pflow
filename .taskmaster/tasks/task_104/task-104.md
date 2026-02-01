# Task 104: Implement Python Code Node for Data Transformation

## Description
Create a native Python code node that executes Python code with direct access to input data as native objects. This solves the shell node limitation of single stdin input and avoids JSON serialization/escaping issues by running Python code in-process.

**Key Innovation**: Native Python objects + required type hints → enables IDE support for markdown workflows (Task 107).

## Status
not started

## Dependencies
None (Task 103 not required - code node uses different approach)

## Priority
medium

## Specification
See `.taskmaster/tasks/task_104/starting-context/task-104-spec.md` for complete implementation details.

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

### Solution

```json
{
  "id": "transform",
  "type": "code",
  "params": {
    "inputs": {
      "data": "${fetch.result}",
      "count": 10
    },
    "code": "data: list[dict]\ncount: int\n\nresult: list = data[:count]"
  }
}
```

**With external libraries:**
```json
{
  "id": "analyze",
  "type": "code",
  "params": {
    "inputs": {"records": "${api.data}"},
    "code": "import pandas as pd\n\nrecords: list[dict]\n\ndf = pd.DataFrame(records)\nresult: dict = df.describe().to_dict()",
    "requires": ["pandas"]
  }
}
```

## Key Decisions

**Type annotations REQUIRED** (for Task 107 markdown workflow IDE support):
- All inputs must have type annotations: `data: list`
- Result must have type annotation: `result: dict = {...}`
- Enables Python tooling (mypy, LSP) in markdown code blocks

**No sandboxing** (explicit decision - see braindump):
- Unrestricted `__builtins__` and imports
- Users need real libraries (pandas, youtube-transcript-api, etc.)
- Container sandboxing deferred to Task 87

**Timeout via ThreadPoolExecutor**:
- Cross-platform (unlike signal.alarm)
- Default 30s, configurable
- Follows pflow patterns

**Single output** (`result` variable):
- User can return dict for structured data
- Multiple outputs deferred to future enhancement

## Implementation Notes

**File locations**:
- Node: `src/pflow/nodes/python/python_code.py`
- Tests: `tests/test_nodes/test_python/test_python_code.py`

**Key implementation details**:
- Use `ast.parse()` to extract type annotations (15 lines, built-in)
- Use `concurrent.futures.ThreadPoolExecutor` for timeout
- Use `contextlib.redirect_stdout/stderr` for output capture
- Follow standard node pattern: prep/exec/exec_fallback/post
- Validate types in prep() before execution
- Let exceptions bubble in exec() for retry mechanism

**Context files**:
- `braindump-sandbox-decision-reversal.md` - Why no sandboxing
- `task-104-handover.md` - Origin story and technical context
- `task-104-spec.md` - Complete specification
