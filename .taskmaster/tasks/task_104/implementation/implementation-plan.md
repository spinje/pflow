# Task 104: Python Code Node — Implementation Plan

## Summary

Implement a `code` node type that executes Python code in-process with native object inputs, AST-extracted type annotations, stdout/stderr capture, and ThreadPoolExecutor timeout.

## Verified Assumptions

All critical assumptions have been verified against the codebase:

| Assumption | Status | Evidence |
|---|---|---|
| Template resolution before prep() | **Verified** | `node_wrapper.py:941-947` — merges resolved params then calls `inner_node._run(shared)` |
| `self.params` for input access | **Verified** | All nodes use `self.params.get()`, never shared store fallback |
| Namespaced shared store writes | **Verified** | `namespaced_store.py:43-55` — `shared["node_id"]["key"]` for regular keys |
| Node discovery via scanner | **Verified** | `scanner.py:53-65` — checks `name` attribute first, then kebab-case |
| IR schema accepts any string type | **Verified** | `ir_schema.py:199` — `"type": {"type": "string"}`, no enum |
| Compiler resolves via registry | **Verified** | `compiler.py:163-202` — `import_node_class()` looks up registry |
| `Node` (not `BaseNode`) for retry | **Verified** | All production nodes inherit from `pocketflow.Node` |
| "default"/"error" action strings | **Verified** | Standard across all nodes |
| exec_fallback returns same shape as exec | **Verified** | LLM node returns error dict, file node returns error string |
| `ast.unparse()` available Python 3.10+ | **Verified** | pflow requires Python 3.10+ |

## Architecture Decision: Node Type Name

The spec uses `"type": "code"` in workflow JSON. The class will be `PythonCodeNode` (descriptive) with an explicit `name = "code"` class attribute to override the kebab-case derivation (`python-code`). This matches the spec while keeping the class name meaningful.

**File locations** (per spec):
- `src/pflow/nodes/python/__init__.py`
- `src/pflow/nodes/python/python_code.py`
- `tests/test_nodes/test_python/__init__.py`
- `tests/test_nodes/test_python/test_python_code.py`

## Expected Workflow Usage

```json
{
  "id": "transform",
  "type": "code",
  "params": {
    "inputs": {
      "data": "${fetch.result}",
      "count": 10
    },
    "code": "data: list\ncount: int\n\nresult: list = data[:count]"
  }
}
```

## Phase 1: Core Node Skeleton + AST Parsing

**Goal**: Get the node registered and parsing type annotations. No execution yet.

### Files to create:
1. `src/pflow/nodes/python/__init__.py`
2. `src/pflow/nodes/python/python_code.py`
3. `tests/test_nodes/test_python/__init__.py`
4. `tests/test_nodes/test_python/test_python_code.py`

### Implementation:

**`python_code.py`** — Create `PythonCodeNode` with:
- `name = "code"` class attribute
- `__init__`: `super().__init__(max_retries=1, wait=0)` — code execution is deterministic, retries won't help
- `prep()`: Extract and validate params, parse AST, validate types
- Stub `exec()`, `exec_fallback()`, `post()` that raise `NotImplementedError`

**AST parsing helper** (`_extract_annotations`):
```python
def _extract_annotations(self, code: str) -> dict[str, str]:
    """Extract type annotations from code using ast.parse().

    Returns dict mapping variable names to type strings.
    Example: {"data": "list", "count": "int", "result": "dict"}
    """
    tree = ast.parse(code)
    annotations = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            annotations[node.target.id] = ast.unparse(node.annotation)
    return annotations
```

**Type validation helper** (`_validate_type`):
```python
TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "int": int,
    "float": (int, float),
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "bytes": bytes,
}

def _get_outer_type(self, type_str: str) -> type | tuple[type, ...] | None:
    """Get the outer Python type for isinstance() checking.

    Handles generics: 'list[dict]' -> list, 'dict[str, Any]' -> dict
    """
    # Strip generic parameters: "list[dict[str, Any]]" -> "list"
    base = type_str.split("[")[0].strip()
    return self.TYPE_MAP.get(base)
```

**prep() validation logic**:
1. Get `code` param — validate non-empty string
2. Get `timeout` param — validate positive number, default 30
3. Get `inputs` param — validate is dict (can be empty)
4. Get `requires` param — store as-is (documentation only)
5. Parse code with `ast.parse()` — SyntaxError propagates with line info
6. Extract annotations via `_extract_annotations()`
7. Validate every key in `inputs` has a type annotation in code
8. Validate `result` has a type annotation in code
9. For each input, validate `isinstance(value, outer_type)` — TypeError if mismatch
10. Return prep dict with parsed code, annotations, validated inputs, timeout

### Tests (Phase 1):
- Test 1: Type annotation extraction — basic types
- Test 23: Complex type extraction — `list[dict[str, Any]]` as string
- Test 2: Missing input annotation → ValueError
- Test 3: Missing result annotation → ValueError
- Test 4: Simple type validation — pass and fail cases
- Test 5: Complex type outer validation — `list[dict]` checks list only
- Test 12: Syntax error handling — line number in error
- Test 17: Empty code rejection → ValueError
- Test 18: Negative timeout rejection → ValueError

### Verification:
```bash
make test -- tests/test_nodes/test_python/
make check
```

---

## Phase 2: Code Execution with Timeout

**Goal**: Execute Python code with ThreadPoolExecutor timeout, stdout/stderr capture.

### Implementation:

**exec() method**:
1. Build execution namespace: `namespace = {"__builtins__": __builtins__}`
2. Inject all input variables into namespace
3. Set up stdout/stderr capture with `io.StringIO` + `contextlib.redirect_stdout/stderr`
4. Execute via ThreadPoolExecutor:
   ```python
   with ThreadPoolExecutor(max_workers=1) as pool:
       future = pool.submit(self._execute_code, code, namespace)
       future.result(timeout=timeout)
   ```
5. Extract `result` from namespace — ValueError if missing
6. Return exec result dict: `{"result": namespace["result"], "stdout": ..., "stderr": ...}`

**`_execute_code` helper** (runs in thread):
```python
def _execute_code(self, code: str, namespace: dict) -> None:
    """Execute code with stdout/stderr capture. Modifies namespace in-place."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        exec(code, namespace)  # noqa: S102
    namespace["__stdout__"] = stdout_buf.getvalue()
    namespace["__stderr__"] = stderr_buf.getvalue()
```

Note: `exec()` will trigger a `ruff` security warning (S102). We'll add `# noqa: S102` since this is intentional and the design decision to allow unrestricted execution is documented.

**No try/except in exec()** — exceptions bubble up for retry mechanism (though retries are 1, so exec_fallback fires on first failure).

### Tests (Phase 2):
- Test 6: Namespace injection — input variables available in code
- Test 22: Multiple inputs — both available
- Test 7: Stdout capture — `print("hello")` → `shared["stdout"]`
- Test 8: Stderr capture — `sys.stderr.write("warn")` → `shared["stderr"]`
- Test 9: Result capture — `result = 42` → `shared["result"]`
- Test 11: Missing result — code doesn't set result → ValueError
- Test 14: Timeout enforcement — infinite loop terminates
- Test 15: Import allowed — `import json` works
- Test 20: No builtins restriction — full access

### Verification:
```bash
make test -- tests/test_nodes/test_python/
```

---

## Phase 3: Error Handling + Post

**Goal**: Complete exec_fallback with context-specific messages, post() with result type validation and shared store writes.

### Implementation:

**exec_fallback()**:
```python
def exec_fallback(self, prep_res: dict, exc: Exception) -> dict:
    if isinstance(exc, SyntaxError):
        error = f"Syntax error at line {exc.lineno}: {exc.msg}"
    elif isinstance(exc, NameError):
        error = f"Undefined variable: {exc.name}"  # Python 3.10+ has .name
    elif isinstance(exc, TimeoutError):
        error = f"Code execution timed out after {prep_res['timeout']} seconds"
    elif isinstance(exc, ImportError):
        error = f"Module '{exc.name}' not found. Install with: uv pip install {exc.name}"
    else:
        error = f"Code execution failed: {exc}"

    return {
        "result": None,
        "stdout": prep_res.get("_stdout", ""),
        "stderr": prep_res.get("_stderr", ""),
        "error": error,
    }
```

Note: `concurrent.futures.TimeoutError` is an alias for the builtin `TimeoutError` in Python 3.

**post()**:
1. Check for error marker in exec_res
2. If error: write `shared["error"]`, return `"error"`
3. If success:
   - Validate result type matches annotation (outer type check)
   - Write `shared["result"]`, `shared["stdout"]`, `shared["stderr"]`
   - Return `"default"`

**Type mismatch error format** (in post for result validation):
```
Result declared as list but code returned dict

Suggestions:
  - Change result type annotation to: result: dict
  - Or convert the value: result: list = list(your_value)
```

### Tests (Phase 3):
- Test 10: Result type validation — `result: int = "text"` → TypeError in post
- Test 13: NameError handling → error in shared["error"]
- Test 16: ImportError handling → error message with module name
- Test 19: Type mismatch suggestions — includes fix hints
- Test 24: Action on success → "default"
- Test 25: Action on error → "error"
- Test 21: Requires field storage — stored but not validated

### Verification:
```bash
make test -- tests/test_nodes/test_python/
make check
```

---

## Phase 4: Interface Docstring + Integration Test

**Goal**: Add the enhanced Interface docstring for registry discovery, run full integration test with workflow execution.

### Implementation:

**Module-level docstring** (top of file, for the MCP/planner context):
```python
"""Execute Python code with typed native object inputs.

...
"""
```

**Class docstring** with Interface format:
```python
class PythonCodeNode(Node):
    """Execute Python code with typed inputs and result capture.

    Runs Python code in-process with native object access. All input variables
    must have type annotations in code. Result must be assigned to annotated
    `result` variable.

    Interface:
    - Params: code: str  # Python code to execute (required, must contain type annotations)
    - Params: inputs: dict  # Variable name to value mapping (optional, default: {})
    - Params: timeout: int  # Execution timeout in seconds (optional, default: 30)
    - Params: requires: list  # Package dependencies for documentation (optional)
    - Writes: shared["result"]: any  # Value of result variable after execution
    - Writes: shared["stdout"]: str  # Captured print() output
    - Writes: shared["stderr"]: str  # Captured stderr output
    - Writes: shared["error"]: str  # Error message if execution failed
    - Actions: default (success), error (failure)
    """
```

**Integration test**: Create a minimal workflow JSON that uses the code node and run it through the executor to verify end-to-end behavior (template resolution → code execution → result in shared store).

### Tests (Phase 4):
- Integration test: workflow with fetch → code transform → verify shared store
- Registry discovery test: scan finds node, type is "code", interface parsed correctly

### Final Verification:
```bash
make test                    # Full test suite
make check                   # Lint + type check
uv run pflow registry scan   # Verify node appears
uv run pflow registry describe code  # Verify interface
```

---

## Implementation Notes

### Error message design

Error messages follow the spec's multi-line format with suggestions. Example for type mismatch:

```
Error: Input 'data' expects list but received dict

Template: ${fetch.result}
Expected: list
Received: dict

Suggestions:
  - Wrap the value in a list: [${fetch.result}]
  - Change the type annotation to: data: dict
```

### What NOT to implement

Per spec, these are explicitly out of scope:
- Language-level sandboxing or `__builtins__` restriction
- Deep generic type validation (only outer type)
- Multiple output variables (only `result`)
- Union/Optional types in annotations
- Async/await code execution
- State persistence between invocations
- `requires` field enforcement

### Risk: ThreadPoolExecutor thread not killable

`ThreadPoolExecutor` cannot kill a running thread. After timeout, the thread continues running in the background until the Python process exits. This is a known limitation documented in the spec. For truly stuck code (e.g., C extension infinite loop), container sandboxing (Task 87) is the solution.

**Mitigation**: The timeout still prevents the workflow from hanging — it continues to the next node. The zombie thread is a resource leak but acceptable for MVP.

### Ruff/mypy considerations

- `exec()` usage will need `# noqa: S102` (security warning for exec)
- `ast.unparse()` is typed in Python 3.10+ stubs — no mypy issues expected
- `concurrent.futures.TimeoutError` is `builtins.TimeoutError` in 3.10+ — use `TimeoutError` directly

## File Inventory

| File | Action | Purpose |
|---|---|---|
| `src/pflow/nodes/python/__init__.py` | Create | Export `PythonCodeNode` |
| `src/pflow/nodes/python/python_code.py` | Create | Node implementation (~250 lines) |
| `tests/test_nodes/test_python/__init__.py` | Create | Test package init |
| `tests/test_nodes/test_python/test_python_code.py` | Create | Tests (~400 lines, 25 test criteria) |

No existing files need modification — the registry scanner auto-discovers new nodes.
