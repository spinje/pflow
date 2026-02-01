# Task 104 Review: Python Code Node for Data Transformation

## Executive Summary

Added a `code` node type (`"type": "code"`) that executes Python code in-process with native object inputs, AST-extracted type annotations, stdout/stderr capture, and ThreadPoolExecutor timeout. Zero existing files modified — the node is fully self-contained and auto-discovered by the registry scanner. Required type annotations are a strategic decision for Task 107 (markdown workflow IDE support).

## Implementation Overview

### What Was Built

A single node class (`PythonCodeNode`) in 336 lines that:
- Accepts a `code` string param and an `inputs` dict param
- Extracts type annotations from code via `ast.parse()` (~6 lines of AST walking)
- Validates input types match annotations (outer type only: `list[dict]` checks `isinstance(value, list)`)
- Executes code via `exec()` in a ThreadPoolExecutor thread with configurable timeout
- Captures stdout/stderr via `contextlib.redirect_stdout/stderr`
- Writes `result`, `stdout`, `stderr` to shared store

### Deviations from Spec

1. **Phased implementation collapsed to one pass** — the node is small enough that stubs add overhead without value.
2. **ThreadPoolExecutor used WITHOUT context manager** — the spec's suggested `with ThreadPoolExecutor` pattern causes the `__exit__` to block on `shutdown(wait=True)`, defeating the timeout. See "Critical Bug" below.
3. **`TypeError` (not `ValueError`) for wrong `inputs` param type** — ruff TRY004 correctly identified this as a type error.

## Files Created

### Core Changes
- `src/pflow/nodes/python/__init__.py` — Exports `PythonCodeNode`
- `src/pflow/nodes/python/python_code.py` — Full node implementation (336 lines)

### Test Files
- `tests/test_nodes/test_python/__init__.py` — Package init
- `tests/test_nodes/test_python/test_python_code.py` — 31 tests (0.35s)

## Integration Points & Dependencies

### How the Code Node Plugs Into pflow

The node requires **zero changes to existing code**. It integrates through three automatic mechanisms:

1. **Registry Scanner** (`scanner.py:53-65`): Discovers `PythonCodeNode` via file scan of `src/pflow/nodes/python/`. The explicit `name = "code"` class attribute overrides the auto-derived `"python-code"`.

2. **Compiler** (`compiler.py:163-202`): Resolves `"type": "code"` by looking up the registry, importing `pflow.nodes.python.python_code.PythonCodeNode`, then wrapping it with `TemplateAwareNodeWrapper` → `NamespacedNodeWrapper` → `InstrumentedNodeWrapper`.

3. **Template Resolution** (`node_wrapper.py:797-952`): The wrapper resolves `${...}` inside the `inputs` dict **before** `prep()` runs. This is the critical seam — the code node receives native Python objects, not template strings.

### Shared Store Keys

| Key | Type | When |
|---|---|---|
| `result` | any | Success — value of the `result` variable after execution |
| `stdout` | str | Always — captured `print()` output |
| `stderr` | str | Always — captured stderr output |
| `error` | str | Error only — formatted error message |

With namespacing (always active in compiled workflows): `shared["node_id"]["result"]` etc.

## Architectural Decisions & Tradeoffs

### Key Decisions

**Required type annotations** — All inputs and `result` must have type annotations in the code string. This adds 2-3 lines of boilerplate per node but enables Python IDE tooling (mypy, LSP) in Task 107's markdown code blocks. The user explicitly decided this is strategic, not cosmetic.

**No sandboxing** — Unrestricted `__builtins__` and imports. Python language-level sandboxing is fundamentally bypassable via object traversal. Users need real libraries (pandas, etc.). Container sandboxing deferred to Task 87.

**Outer type validation only** — `list[dict]` validates `isinstance(value, list)`, does not inspect element types. Catches 90% of type errors with zero complexity. Deep validation deferred.

**`max_retries=1, wait=0`** — Code execution is deterministic. A NameError won't fix itself on retry. This differs from most other nodes (shell: `max_retries=1`, LLM: `max_retries=3`).

### Technical Debt

- **Zombie threads on timeout**: When code times out, the worker thread keeps running until process exit. `pool.shutdown(wait=False, cancel_futures=True)` prevents blocking but doesn't kill the thread. Acceptable for MVP; Task 87 (container sandboxing) is the real fix.
- **`requires` field is documentation-only**: No validation, no auto-install. ImportError bubbles naturally. Option to catch ImportError and cross-reference against `requires` is easy to add later.

## Unexpected Discoveries

### Critical Bug: ThreadPoolExecutor Context Manager Defeats Timeout

**This is the most important finding of this implementation.**

```python
# BROKEN — blocks for the full sleep duration, not 0.1s
with ThreadPoolExecutor(max_workers=1) as pool:
    future = pool.submit(lambda: time.sleep(5))
    future.result(timeout=0.1)  # TimeoutError raised, but...
# __exit__ calls shutdown(wait=True) → blocks until thread finishes → 5 seconds

# CORRECT — returns immediately on timeout
pool = ThreadPoolExecutor(max_workers=1)
future = pool.submit(lambda: time.sleep(5))
try:
    future.result(timeout=0.1)  # TimeoutError after 0.1s
finally:
    pool.shutdown(wait=False, cancel_futures=True)  # Non-blocking cleanup
```

**Impact**: Any future node that uses ThreadPoolExecutor for timeout MUST NOT use the context manager pattern.

### AST Annotations vs. exec() Annotations

Type annotations exist in two different worlds:
- **AST-time**: Annotations are strings — `ast.unparse(node.annotation)` returns `"DataFrame"` without evaluating it
- **exec()-time**: Annotations are evaluated — `data: DataFrame` triggers `NameError` if `pandas` isn't imported

This means a user writing `data: DataFrame` MUST `import pandas as pd` in their code, even though our type validator doesn't check the type (it's not in `_TYPE_MAP`). The validator skips unknown types gracefully, but `exec()` will crash.

### mypy Type Narrowing with `self.params.get()`

`self.params.get("key")` returns `Any`. When validating, `isinstance()` must be the **dominant** guard for mypy to narrow the type:

```python
# FAILS mypy — truthiness check before isinstance prevents narrowing
if not code or not isinstance(code, str) or not code.strip():
    raise ValueError(...)
return code  # mypy: "Returning Any from function declared to return str"

# PASSES mypy — isinstance is the first meaningful check
if not isinstance(code, str) or not code.strip():
    raise ValueError(...)
return code  # mypy: str ✓
```

## Patterns Established

### The `inputs` Dict Pattern

The code node introduced a new param pattern: a dict of template-resolved values that become execution-namespace variables. This is different from other nodes where params are flat key-value pairs.

```json
"params": {
    "inputs": {"data": "${upstream.result}", "limit": 10},
    "code": "data: list\nlimit: int\nresult: list = data[:limit]"
}
```

The `TemplateAwareNodeWrapper` resolves templates **inside nested dicts** automatically — no special handling needed. This was verified in the integration test.

### Explicit `name` Class Attribute for Type Override

```python
class PythonCodeNode(Node):
    name = "code"  # Workflow uses "type": "code", not "python-code"
```

The scanner checks `name` attribute first (`scanner.py:56`), then falls back to kebab-case from class name. Use this when the desired workflow type name doesn't match the class name's kebab-case form.

## Testing Implementation

### Test Philosophy Applied

Started with 34 tests (auto-generated), reviewed critically, ended with 31. Removed tests that tested implementation details (private helpers, config constants, Python builtins). Added tests that catch real user-facing issues (dict results for downstream access, None inputs, pass-by-reference semantics).

### Tests That Catch Real Issues

| Test | What It Prevents |
|---|---|
| `test_dict_result_with_structured_data` | Regression in the primary use case — `${node.result.field}` access |
| `test_code_node_in_compiled_workflow` | Breaks in registry discovery, template resolution, or namespacing |
| `test_none_input_fails_type_check` | Upstream node returning None silently passes through |
| `test_timeout_stops_long_running_code` | Timeout regression (the ThreadPoolExecutor bug) |
| `test_input_mutation_affects_original` | Documents pass-by-reference — if someone adds defensive copying, this test validates or catches the change |
| `test_result_type_mismatch_caught_in_post` | Type annotation contract enforcement |

### Tests That Are Nice-to-Have

`test_bool_passes_as_int`, `test_int_passes_as_float`, `test_unknown_type_annotation_skips_check` — these document Python semantics and `_TYPE_MAP` design decisions. They're more documentation than regression prevention.

## AI Agent Guidance

### Quick Start for Related Tasks

**Task 107 (Markdown Workflows)**: The code node's type annotations are your hook. `_extract_annotations()` returns a dict of `{var_name: type_string}` that you can use to generate `.pyi` stubs for IDE support. The annotations are AST strings, not evaluated types.

**Task 87 (Container Sandboxing)**: The timeout mechanism already works correctly. To add container isolation, you'd replace `ThreadPoolExecutor.submit(exec, ...)` with subprocess execution. The `exec_fallback` error formatting would need container-specific error types.

**Task 113 (TypeScript Code Node)**: Follow this exact file structure (`src/pflow/nodes/typescript/`) with an explicit `name = "typescript-code"` or similar. The pattern of `inputs` dict → namespace injection → single `result` output is reusable.

### Key Files to Read First

1. `src/pflow/nodes/python/python_code.py` — the implementation
2. `src/pflow/nodes/CLAUDE.md` — the node pattern rules
3. `src/pflow/runtime/node_wrapper.py:797-952` — template resolution flow (critical for understanding what the node receives)

### Common Pitfalls

1. **Never use `with ThreadPoolExecutor` for timeout** — `__exit__` blocks. Use manual `pool.shutdown(wait=False, cancel_futures=True)`.
2. **Never add try/except to `exec()`** — breaks PocketFlow retry mechanism. Handle errors in `exec_fallback()`.
3. **`isinstance` must be the dominant guard** when narrowing `Any` from `self.params.get()` for mypy.
4. **Type annotations in exec() are evaluated eagerly** — users must import custom types before annotating with them.
5. **Test timeout tests with very short durations** (0.01s sleep, 0.001s timeout) to avoid zombie thread slowdowns in the test suite.

---

*Generated from implementation context of Task 104*
