# Node Implementation Guide

This directory contains all pflow nodes. **CRITICAL**: All nodes MUST follow the Node retry pattern.

> **Note:** Template resolution, namespacing, and instrumentation are applied automatically by the engine at runtime. Node implementations should focus only on business logic — never implement these concerns yourself. See `src/pflow/runtime/engine/CLAUDE.md` for details.

## Shared Store vs Params

- **Params** (`self.params`): Static configuration — model name, temperature, timeout, file format. Set by the engine from the workflow IR before each `_run()`.
- **Shared store** (`shared`): Dynamic data flowing between nodes — user inputs, API responses, generated content. Read in `prep()`, written in `post()`.

Rule of thumb: if the value changes between workflow runs, it's shared store data. If it's the same regardless of input, it's a param.

`LLMNode.post()` and `ClaudeCodeNode.post()` are approved direct producers of `shared["__warnings__"]`. The convention for choosing between `setdefault` and `=` is intent-based:

- **`setdefault` — preserve prior signal.** Used by `LLMNode._emit_observed_below_min_cache_warning` (catalog-backed `cache.below-min-tokens` diagnostic emitted when provider telemetry reports zero cache creation/read for a node declaring `prompt_cache:`). Pre-existing warnings survive; this is supplementary observability that never overwrites earlier evidence.
- **`=` — this signal takes precedence.** Used by `LLMNode._emit_prewarm_disabled_warning` (when `prewarm: true` is declared but cache rendering can't fire — e.g., images present, or canonical/standard byte alignment failed), adapter-empty-response warnings emitted later in `LLMNode.post()`, and `ClaudeCodeNode._emit_soft_fail_signal` / `_emit_schema_resolved_null_warning` (schema soft-failures and templated-schema-resolved-to-None — both authoritative for the run). These signals clobber prior writes intentionally.

Future contributors adding new direct `__warnings__` writes: pick the verb by asking "is this signal authoritative for the node's current run, or supplementary?" Authoritative → `=`. Supplementary → `setdefault`.

## Critical Pattern: Node Error Handling

**This is non-negotiable** - violating this pattern disables automatic retries, severely impacting reliability.

### The Pattern

```python
from pflow.core.node import Node  # NOT BaseNode!
from .exceptions import NonRetriableError

class ExampleNode(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=0.1)

    def prep(self, shared: dict) -> Any:
        """Validate inputs and prepare for execution."""
        # Validation logic here
        return prep_data

    def exec(self, prep_res: Any) -> Any:
        """Execute main logic - NO try/except blocks!"""
        # Let ALL exceptions bubble up for retry mechanism
        result = some_operation()  # If this fails, it will retry
        return result  # Only return success value

    def exec_fallback(self, prep_res: Any, exc: Exception) -> Any:
        """Handle errors AFTER all retries exhausted."""
        if isinstance(exc, SpecificError):
            return "Error: Specific error message"
        else:
            return f"Error: Operation failed: {exc!s}"

    def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
        """Process results and determine next action."""
        if isinstance(exec_res, str) and exec_res.startswith("Error:"):
            shared["error"] = exec_res
            return "error"
        else:
            shared["result"] = exec_res
            return "default"
```

### Key Rules

1. **NO try/except in exec()** - Let exceptions bubble up!
2. **Use NonRetriableError** for validation errors that shouldn't retry
3. **Prefer `PflowError` subclasses** over vanilla `ValueError`/`Exception` — see `src/pflow/core/exceptions.py`
4. **Return only success values** from exec()
4. **Handle errors in exec_fallback()** after retries exhausted
5. **Check for errors in post()** by looking for "Error:" prefix

### Examples

#### ✅ CORRECT - Enables Retry
```python
def exec(self, prep_res):
    file_path = prep_res
    # No try/except - exceptions bubble up!
    with open(file_path) as f:
        return f.read()
```

#### ❌ WRONG - Breaks Retry
```python
def exec(self, prep_res):
    file_path = prep_res
    try:
        with open(file_path) as f:
            return f.read()
    except Exception as e:
        # This prevents retry!
        return f"Error: {e}"
```

### Testing Retry Behavior

Always test that your nodes retry correctly:

```python
def test_node_retries_on_failure():
    node = YourNode()
    shared = {"input": "test"}

    with patch("some.operation") as mock_op:
        # Fail twice, then succeed
        mock_op.side_effect = [
            Exception("Temporary failure"),
            Exception("Still failing"),
            "Success!"
        ]

        action = node.run(shared)

        assert action == "default"
        assert mock_op.call_count == 3
```

## Node Categories

- **file/** - File operations (read, write, copy, move, delete)
- **llm/** - Language model interactions
- **shell/** - Shell command execution
- **http/** - HTTP requests
- **claude/** - Claude Code CLI integration
- **mcp/** - MCP tool bridge

## Interface Documentation Format

All nodes MUST use the enhanced Interface format with type annotations:

```python
"""
Node description here.

Interface:
- Reads: shared["file_path"]: str  # Path to the file to read
- Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
- Writes: shared["content"]: str  # File contents
- Writes: shared["error"]: str  # Error message if operation failed
- Params: append: bool  # Append mode (default: false)
- Actions: default (success), error (failure)
"""
```

See `architecture/reference/enhanced-interface-format.md` for more details of the docstring format for pflow nodes.

### Dynamic Routing via `next` Variable (Python Code Node)

Python code nodes (`type: code`) support dynamic routing by setting `next: str = "target-node-id"` in the code. When `next` is set, it becomes the action returned by `post()`, routing execution to the matching edge. The `result` annotation is optional when `next` is declared.

### Key Rules:

1. **Multi-line format**: Each input/output on its own line for readability
2. **Type annotations**: Always include `: type` after the key
3. **Descriptions**: Use `# Description` after the type
4. **Optional/defaults**: Document in description like `(optional, default: value)`
5. **All inputs in Params**: Node inputs come from `self.params`, not shared store
6. **Writes for outputs**: Node outputs go to shared store via `shared["key"]`

### Example Interface:

```python
Interface:
- Params: file_path: str  # Path to the file to read (required)
- Params: encoding: str  # File encoding (optional, default: utf-8)
- Writes: shared["content"]: str  # File contents read from file
- Writes: shared["error"]: str  # Error message if operation failed
- Actions: default (success), error (failure)
```

### Parameter-Only Pattern

All node inputs should come from `self.params`, NOT from the shared store. The runtime uses template resolution to inject values from the shared store into node params before execution.

Do:
```python
file_path = self.params.get("file_path")  # Correct - params only
```

Do NOT do:
```python
file_path = shared.get("file_path") or self.params.get("file_path")  # Wrong - shared store fallback
```

## Creating New Nodes

> **Node Output Types**: Nodes should store their natural output type (strings from shell/LLM, dicts from parsed APIs). Do NOT implement JSON auto-parsing in nodes — the template system handles type coercion automatically. See `architecture/core-concepts/data-type-coercion.md`.

1. Copy the retry pattern above
2. Inherit from `Node` (not `BaseNode`)
3. NO try/except in exec()
4. Use `NonRetriableError` for validation failures
5. Test retry behavior
6. Document using the Interface format above

## Nested Structure support

Nested JSON/Object Outputs Are Fully Supported:

You can write this in a node's docstring:
  Interface:
  - Writes: shared["issue_data"]: dict  # GitHub issue information
      - number: int  # Issue number
      - title: str  # Issue title
      - user: dict  # Author information
        - login: str  # GitHub username
        - id: int  # User ID
        - avatar_url: str  # Profile picture URL
      - labels: list  # Array of label objects
      - milestone: dict  # Milestone info (optional)
        - id: int  # Milestone ID
        - title: str  # Milestone title

  And the context builder will display it as:
  **Outputs**: `issue_data: dict` - GitHub issue information
    Structure of issue_data:
      - number: int - Issue number
      - title: str - Issue title
      - user: dict - Author information
        - login: str - GitHub username
        - id: int - User ID
        - avatar_url: str - Profile picture URL
      - labels: list - Array of label objects
      - milestone: dict - Milestone info (optional)
        - id: int - Milestone ID
        - title: str - Milestone title

## Common Mistakes

1. **Catching exceptions in exec()** - This is the #1 anti-pattern!
2. **Returning error tuples** - Return only success values
3. **Forgetting exec_fallback()** - Needed for error messages
4. **Not testing retries** - Always verify retry behavior
5. **Using `redirect_stdout`/`redirect_stderr` in threads** — Not thread-safe; zombie threads corrupt streams. See `python_code.py:_execute_code` docstring and issue #138 for details.
6. **Storing execution state on `self`** — Nodes may be reused across sequential batch items (compile-once cache). Never set `self.X = result` in `exec()`/`post()` — communicate between lifecycle methods via the return value (`prep_res`, `exec_res`) or the shared store. Exception: `self.params` is set by the engine before each `_run()` call.
7. **Writing directly to stderr from `prep`/`exec`/`post`** — Direct `click.echo(..., err=True)`, `print(..., file=sys.stderr)`, or `sys.stderr.write(...)` during live progress rendering corrupts the partial `node_id...` line emitted by `OutputController._handle_node_start`. Use `logger.warning`/`logger.error` instead — a logging filter installed by `OutputController` closes the partial line as a side effect before each log record emits, so `logger.*` calls render cleanly on their own lines. Raw stderr writes bypass the filter.

## References

- Full pattern documentation: `/.taskmaster/knowledge/patterns.md` - "Node Error Handling"
- Anti-pattern to avoid: `/.taskmaster/knowledge/pitfalls.md` - "Catching Exceptions in exec()"
- Architectural decision: `/.taskmaster/knowledge/decisions.md` - "All pflow Nodes Must Follow Node Retry Pattern"
- Node lifecycle primitives: `src/pflow/core/node.py`

## Quick Checklist

Before committing any node:

- [ ] Inherits from `Node` (not `BaseNode`)?
- [ ] No try/except blocks in `exec()`?
- [ ] Returns only success values from `exec()`?
- [ ] Has `exec_fallback()` for error handling?
- [ ] Uses `NonRetriableError` for validation errors?
- [ ] Tests verify retry behavior?
- [ ] `post()` checks for "Error:" prefix?
- [ ] Interface uses enhanced format with types?
- [ ] Only exclusive params listed (not in Reads)?
- [ ] No `self.X = ...` in exec()/post()? (nodes reused across batch items — use return values, not instance state)

Remember: **Let exceptions bubble up!** The framework handles retries for you.
