# Feature: python_code_node

## Objective

Execute Python code with typed native object inputs.

## Requirements

- Must execute Python code in-process using `exec()`
- Must inject input variables into execution namespace
- Must extract type annotations from code using AST parsing
- Must validate input types match declared annotations before execution
- Must validate result type matches declared annotation after execution
- Must capture stdout and stderr during execution
- Must support execution timeout with default 30 seconds
- Must allow all Python imports without restriction
- Must provide clear error messages with line numbers for syntax errors
- Must provide clear error messages with tracebacks for runtime errors

## Scope

- Does not implement language-level sandboxing or restrict `__builtins__`
- Does not restrict imports or module access
- Does not support multiple output variables (only `result` variable)
- Does not validate deep generic types (e.g., `list[dict]` vs `list[str]`)
- Does not support union types or Optional types in MVP
- Does not implement container-level sandboxing (deferred to Task 87)
- Does not support async/await code execution
- Does not persist execution state between node invocations

## Inputs

- `inputs: dict[str, Any]` - Dictionary mapping variable names to template-resolved values
- `code: str` - Python code string to execute (must contain type annotations)
- `timeout: int` - Execution timeout in seconds (optional, default: 30)
- `requires: list[str]` - Package dependencies for documentation (optional)

## Outputs

Returns: Execution success or failure via node action

Side effects:
- Writes `shared["result"]: Any` - Value of `result` variable after code execution
- Writes `shared["stdout"]: str` - Captured print() output
- Writes `shared["stderr"]: str` - Captured stderr output
- Writes `shared["error"]: str` - Error message if execution failed (only on error action)
- Returns action `"default"` on successful execution
- Returns action `"error"` on execution failure, timeout, or validation error

## Structured Formats

### Type Annotation Format
```python
# Variable annotations (AnnAssign nodes)
variable_name: type_string

# Example:
data: list[dict]
count: int
result: dict = {"items": data[:count]}
```

### Error Message Format
```
Error: {brief_description}

{detailed_context}

💡 Suggestions:
  - {suggestion_1}
  - {suggestion_2}
```

## State/Flow Changes

- Node params → AST parsing → Type annotations extracted
- Type annotations + resolved inputs → Validation → Pass/Fail
- Validated inputs → Code execution → Result + stdout/stderr
- Execution success → shared store update → "default" action
- Execution failure → error formatting → shared["error"] → "error" action

## Constraints

- Code parameter must be non-empty string
- All variables in `inputs` dict must have type annotations in code
- `result` variable must have type annotation in code
- Timeout must be positive integer or float
- Type validation checks outer type only (e.g., `list[dict]` validates `isinstance(value, list)`)
- Maximum execution time enforced by timeout parameter
- AST parsing requires valid Python syntax (SyntaxError fails in prep)

## Rules

1. Extract type annotations from code using `ast.parse()` in prep phase
2. Validate all input variable names have corresponding type annotations
3. Validate `result` variable has type annotation
4. Resolve template values for all inputs before type validation
5. Validate each resolved input value matches its declared type
6. Create execution namespace with `__builtins__` unrestricted
7. Inject all input variables into execution namespace
8. Capture stdout using `contextlib.redirect_stdout` and `io.StringIO`
9. Capture stderr using `contextlib.redirect_stderr` and `io.StringIO`
10. Execute code using `exec(code, namespace)` without try/except
11. Validate `result` variable exists in namespace after execution
12. Validate `result` value matches its declared type annotation
13. Apply timeout using `concurrent.futures.ThreadPoolExecutor` with `Future.result(timeout=)`
14. Let exceptions bubble up in exec() for retry mechanism
15. Handle all exceptions in exec_fallback() with context-specific messages
16. Format SyntaxError with line number and error message
17. Format NameError with undefined variable name
18. Format concurrent.futures.TimeoutError with timeout duration
19. Format TypeError for type mismatches with fix suggestions
20. Store stdout, stderr, result in shared store on success
21. Store error message in shared store and return "error" action on failure

## Edge Cases

- Code with no type annotations → ValidationError in prep listing missing annotations
- Code with syntax errors → SyntaxError in prep with line number and message
- Input variable missing type annotation → ValidationError in prep
- `result` variable missing type annotation → ValidationError in prep
- Input value type mismatch → TypeError in prep with type comparison and suggestions
- Result value type mismatch → TypeError in post with type comparison
- Code does not set `result` variable → ValueError in exec with clear message
- Code execution timeout → concurrent.futures.TimeoutError with timeout duration
- Undefined variable in code → NameError in exec_fallback with variable name
- Empty code string → ValidationError in prep
- Negative timeout value → ValidationError in prep
- Import fails (module not installed) → ImportError in exec_fallback with module name
- Code with infinite loop → TimeoutError after timeout seconds
- Code that modifies `inputs` dict → Allowed (no protection)
- Complex type annotations (e.g., `dict[str, list[int]]`) → Validates outer type only

## Error Handling

### Prep Phase Errors
- Empty code → `ValueError("Code parameter cannot be empty")`
- Invalid timeout → `ValueError(f"Timeout must be positive number, got {timeout}")`
- Missing input annotation → `ValueError(f"Input '{name}' missing type annotation in code. Add: {name}: <type>")`
- Missing result annotation → `ValueError("Code must declare result type annotation: result: <type> = ...")`
- Syntax error in code → `SyntaxError` with line number, offset, message
- Input type mismatch → `TypeError` with template, expected type, actual type, fix suggestions

### Exec Phase Errors (handled in exec_fallback)
- Timeout → `concurrent.futures.TimeoutError` → `f"Python code execution timed out after {timeout} seconds"`
- NameError → `f"Error: Undefined variable '{var_name}'. Ensure all variables are defined in code or provided as inputs"`
- ImportError → `f"Error: Module '{module_name}' not found. Install with: pip install {module_name}"`
- Result missing → `ValueError("Code must set 'result' variable. Add: result = <your_value>")`
- Generic exception → `f"Error: Code execution failed: {exc}"`

### Post Phase Errors
- Result type mismatch → `f"Result declared as {expected_type} but code returned {actual_type}"`

## Non-Functional Criteria

- Type annotation extraction completes in < 10ms for typical code (< 100 lines)
- Type validation completes in < 5ms per input variable
- Stdout/stderr capture overhead < 1ms
- Code execution timeout enforced within ±100ms of specified value
- Error messages include specific line numbers for syntax errors
- Error messages include variable names for NameError
- Error messages include module names for ImportError
- AST parsing uses Python stdlib only (no external dependencies)

## Examples

### Valid: Simple transformation
```json
{
  "type": "code",
  "params": {
    "inputs": {
      "data": "${fetch.result}",
      "limit": 10
    },
    "code": "data: list\nlimit: int\n\nresult: list = data[:limit]"
  }
}
```

### Valid: Data processing with imports
```json
{
  "type": "code",
  "params": {
    "inputs": {
      "records": "${api.data}"
    },
    "code": "import pandas as pd\n\nrecords: list[dict]\n\ndf = pd.DataFrame(records)\nresult: dict = df.describe().to_dict()",
    "requires": ["pandas"],
    "timeout": 60
  }
}
```

### Invalid: Missing type annotation
```json
{
  "type": "code",
  "params": {
    "inputs": {"data": "${fetch.result}"},
    "code": "result = data[:10]"
  }
}
```
Error: `ValueError("Input 'data' missing type annotation in code. Add: data: <type>")`

### Invalid: Type mismatch
```json
{
  "type": "code",
  "params": {
    "inputs": {"data": "${fetch.result}"},
    "code": "data: list\n\nresult: list = data[:10]"
  }
}
```
Where `fetch.result` is `dict`:
Error: `TypeError("Input 'data' expects list but received dict\nTemplate: ${fetch.result}\n...")`

## Test Criteria

1. **Type annotation extraction** — Code `"data: list\nresult: dict = {}"` extracts `{"data": "list", "result": "dict"}`
2. **All inputs validated** — Input `{"data": "${x}"}` without annotation `data:` raises `ValueError`
3. **Result annotation required** — Code without `result:` annotation raises `ValueError`
4. **Simple type validation** — Input declared `data: list`, value `[1,2,3]` passes; value `{"a":1}` fails with `TypeError`
5. **Complex type outer validation** — Input `data: list[dict]`, value `[{"a":1}]` passes (only checks `isinstance(value, list)`)
6. **Namespace injection** — Input `{"count": 5}` makes `count` variable available in code
7. **Stdout capture** — Code `print("hello")` stores `"hello\n"` in `shared["stdout"]`
8. **Stderr capture** — Code `import sys; sys.stderr.write("warn")` stores `"warn"` in `shared["stderr"]`
9. **Result capture** — Code `result = 42` stores `42` in `shared["result"]`
10. **Result type validation** — Code `result: int = "text"` raises `TypeError` in post
11. **Missing result** — Code without `result = ...` raises `ValueError` in exec
12. **Syntax error handling** — Code `"result = ["` raises `SyntaxError` in prep with line number
13. **NameError handling** — Code referencing undefined variable stores error in `shared["error"]`
14. **Timeout enforcement** — Infinite loop code terminates after `timeout` seconds
15. **Import allowed** — Code `import json; result = json.dumps({})` executes successfully
16. **ImportError handling** — Code `import nonexistent_module` stores ImportError in `shared["error"]`
17. **Empty code rejection** — Empty string code raises `ValueError` in prep
18. **Negative timeout rejection** — `timeout: -5` raises `ValueError` in prep
19. **Type mismatch suggestions** — TypeError includes "💡 Suggestions:" with fix options
20. **No builtins restriction** — Code can access `__builtins__` without restriction
21. **Requires field storage** — `requires: ["pandas"]` stored but not validated in MVP
22. **Multiple inputs** — `inputs: {"a": 1, "b": 2}` both available as variables
23. **AST handles complex types** — Annotation `list[dict[str, Any]]` extracted as string `"list[dict[str, Any]]"`
24. **Action on success** — Successful execution returns action `"default"`
25. **Action on error** — Failed execution returns action `"error"`

## Notes (Why)

- **In-process exec() chosen** over subprocess for native object access without serialization
- **Type annotations required** to support markdown workflow Python tooling integration (Task 107)
- **No sandboxing** because Python language-level sandboxing is fundamentally bypassable via object traversal
- **Outer type validation only** for MVP to avoid complex type system implementation
- **AST parsing** uses Python's own parser ensuring robustness for all valid Python syntax
- **`requires` field** provides documentation and enables future auto-install/containerization
- **Timeout via ThreadPoolExecutor** for cross-platform compatibility (follows pflow patterns)
- **`shared["result"]` key** deviates from typical semantic naming (most nodes use `response`, `content`, etc.) but matches Claude Code node pattern for generic output
- **All imports allowed** because users need real-world libraries (pandas, youtube-transcript-api, etc.)
- **Error messages with suggestions** help AI agents learn correct usage patterns
- **No try/except in exec()** preserves Node retry mechanism for transient failures
- **Type hints enable IDE support** in markdown workflows with generated type stubs

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
|--------|----------------------------|
| 1      | 1, 23                      |
| 2      | 2                          |
| 3      | 3                          |
| 4      | 4                          |
| 5      | 4, 5                       |
| 6      | 20                         |
| 7      | 6, 22                      |
| 8      | 7                          |
| 9      | 8                          |
| 10     | 9, 15                      |
| 11     | 11                         |
| 12     | 10                         |
| 13     | 14                         |
| 14     | 13, 16                     |
| 15     | 12, 13, 16                 |
| 16     | 12                         |
| 17     | 13                         |
| 18     | 14                         |
| 19     | 4, 19                      |
| 20     | 7, 8, 9, 24                |
| 21     | 13, 16, 25                 |

## Versioning & Evolution

- **Version:** 1.0.0
- **Changelog:**
  - **1.0.0** — Initial spec for Python code node with required type annotations, no sandboxing, AST-based validation, in-process execution with native objects

## Epistemic Appendix

### Assumptions & Unknowns

- **Assumes** `concurrent.futures.ThreadPoolExecutor` provides sufficient timeout mechanism for in-process Python execution
- **Assumes** Python 3.10+ for `ast.unparse()` availability (verified: pflow requires Python 3.10+)
- **Assumes** Template resolution completes before node prep() per existing wrapper behavior
- **Assumes** `requires` field validation/enforcement deferred to future tasks
- **Assumes** Container sandboxing (Task 87) will provide optional secure execution mode
- **Unknown** whether deep generic type validation (e.g., `list[dict]` vs `list[str]`) will be needed before Task 107
- **Unknown** exact markdown frontmatter format for `requires` field in Task 107

### Conflicts & Resolutions

- **Conflict:** Handover doc (`task-104-handover.md` line 103) specifies sandboxed globals; Braindump (`braindump-sandbox-decision-reversal.md` line 5) explicitly reverses this decision
  - **Resolution:** Followed braindump (latest decision) — no sandboxing, unrestricted `__builtins__`
  - **Hierarchy:** Latest explicit user decision > earlier handover documentation

### Decision Log / Tradeoffs

- **Type annotations: Required vs Optional**
  - **Options:** (A) Optional annotations with gradual typing, (B) Required annotations
  - **Chosen:** B — Required type annotations for all inputs and result
  - **Rationale:** Task 107 (markdown workflows) follows immediately; Python tooling (mypy, IDE autocomplete) requires type hints; enables workflow-level type validation
  - **Tradeoff:** More verbose (2-3 extra lines per node) but enables professional tooling support

- **Sandboxing: Language-level vs Container vs None**
  - **Options:** (A) Restricted `__builtins__`, (B) Container isolation, (C) No sandboxing
  - **Chosen:** C — No sandboxing for MVP
  - **Rationale:** Python object traversal makes language-level sandboxing bypassable; containers require serialization (negates native objects value); users need real libraries (pandas, etc.)
  - **Tradeoff:** Security vs utility — chose utility for local automation use case

- **Type validation: Deep vs Outer**
  - **Options:** (A) Full generic validation, (B) Outer type only, (C) Runtime only
  - **Chosen:** B — Validate outer type only (e.g., `list[dict]` checks `isinstance(value, list)`)
  - **Rationale:** Simple implementation for MVP; covers 90% of type errors; deep validation complex to implement
  - **Tradeoff:** Some type mismatches undetected (e.g., `list[str]` vs `list[int]`) but catches most common errors

- **Timeout: signal.alarm vs asyncio vs ThreadPoolExecutor**
  - **Options:** (A) signal.alarm() Unix-only, (B) asyncio.wait_for() for async, (C) ThreadPoolExecutor.result(timeout=), (D) subprocess.run(timeout=)
  - **Chosen:** C — ThreadPoolExecutor with Future.result(timeout=)
  - **Rationale:** Cross-platform (unlike signal.alarm); follows pflow patterns (MCP uses asyncio for async, shell uses subprocess for process); works with synchronous exec(); no global state
  - **Tradeoff:** Python GIL limitations but acceptable for code node use case; harder to kill truly stuck code but timeout still enforces limit

- **Multiple outputs: Single result vs Multiple variables**
  - **Options:** (A) Single `result` variable, (B) Multiple declared outputs, (C) Return dict
  - **Chosen:** A — Single `result` variable
  - **Rationale:** Simplest for MVP; user can return dict for structured data; future enhancement possible
  - **Tradeoff:** Single output only but can contain any structure (dict with multiple fields)

### Ripple Effects / Impact Map

- **Template validation system** (`src/pflow/runtime/template_validator.py`) — Will use code node's type annotations for cross-node validation
- **Registry metadata** (`src/pflow/registry/metadata_extractor.py`) — Already extracts type metadata from docstrings; code node provides runtime type info
- **Node wrapper** (`src/pflow/runtime/node_wrapper.py`) — Template resolution happens before prep(); code node receives resolved native objects
- **Task 107** (Markdown workflows) — Code node type annotations enable Python LSP/mypy integration in markdown code blocks
- **Task 87** (Container sandboxing) — Code node will gain optional `sandbox: true` parameter for secure execution
- **Error message patterns** — Establishes multi-line format with "💡 Suggestions:" for other nodes
- **AST parsing precedent** — First use of AST in pflow; establishes pattern for future code analysis features

### Residual Risks & Confidence

- **Risk:** ThreadPoolExecutor timeout may not interrupt truly stuck code (e.g., infinite C extension call)
  - **Mitigation:** Document limitation; recommend container sandboxing (Task 87) for untrusted code
  - **Confidence:** High (rare edge case; most Python code respects timeout)

- **Risk:** Deep type validation needed before Task 107
  - **Mitigation:** Outer type validation catches most errors; can enhance incrementally
  - **Confidence:** High (simple types cover 90% of use cases)

- **Risk:** Unrestricted exec() enables malicious code
  - **Mitigation:** Document trust model; defer sandboxing to Task 87
  - **Confidence:** High (local automation use case, same trust as shell node)

- **Risk:** AST parsing performance on very large code strings
  - **Mitigation:** Non-functional criteria specify < 10ms for typical code; Python's parser is fast
  - **Confidence:** High (AST parsing is O(n) and Python's parser is production-grade)

- **Risk:** Type annotation extraction fails for complex annotations
  - **Mitigation:** `ast.unparse()` handles all valid Python syntax; capture as strings without semantic validation
  - **Confidence:** Very High (uses Python's own parser)

### Epistemic Audit (Checklist Answers)

1. **Which assumptions weren't explicit?**
   - ThreadPoolExecutor timeout sufficient (vs signal.alarm or other mechanisms)
   - Python 3.10+ for ast.unparse() (verified: matches pflow requirement)
   - Template resolution timing before prep() (verified: correct per wrapper behavior)
   - Outer type validation sufficient for MVP (design decision, not assumption)
   - `shared["result"]` key naming (intentional choice, matches Claude Code pattern)

2. **What breaks if assumptions wrong?**
   - ThreadPoolExecutor insufficient → would need subprocess isolation (Task 87 provides this)
   - Python < 3.10 → ast.unparse() unavailable (safe: pflow requires 3.10+)
   - Template timing different → would need wrapper changes (verified: timing is correct)
   - Deep type validation needed → incremental enhancement required (unlikely for MVP)

3. **Optimized elegance over robustness?**
   - No — chose required type annotations (verbose) over optional (elegant)
   - No — chose outer type validation (simple) over no validation (simpler)
   - No — chose explicit error messages (verbose) over generic errors (simpler)

4. **Every Rule maps to Test?**
   - Yes — Compliance Matrix shows all 21 rules covered by 25 tests
   - All edge cases covered: empty code, missing annotations, type mismatches, timeouts

5. **Ripple effects/invariants touched?**
   - Template validator will use type annotations for cross-node checks
   - Task 107 depends on type annotation requirement
   - Error message format influences other nodes
   - AST parsing establishes pattern for future features

6. **Remaining uncertainty + confidence?**
   - **Low uncertainty** on core implementation (AST, exec, type validation)
   - **Medium uncertainty** on Windows timeout behavior (deferred)
   - **Low uncertainty** on deep type validation need (outer type sufficient)
   - **Overall confidence: High** (90%+)
