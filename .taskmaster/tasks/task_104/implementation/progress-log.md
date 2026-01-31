# Task 104 Implementation Progress Log

## Phase 1: Core Node + AST Parsing + Type Validation + Execution

---

## [01] - Research & Assumption Verification

Deployed 4 parallel codebase searcher agents to verify all assumptions before writing any code.

Result: All critical assumptions confirmed.
- ✅ Template resolution happens before prep() — `node_wrapper.py:941-947`
- ✅ All nodes use `self.params.get()`, never shared store fallback
- ✅ Scanner checks `name` class attribute first, then kebab-case — `scanner.py:53-65`
- ✅ IR schema accepts any string for node type — no enum constraint
- ✅ Compiler resolves types via registry lookup — auto-discovery handles registration
- ✅ `Node` (not `BaseNode`) required for retry support
- 💡 Insight: The class should be `PythonCodeNode` with explicit `name = "code"` to get workflow type `"code"` instead of auto-derived `"python-code"`

---

## [02] - Implementation: Node Skeleton

Created 4 files:
- `src/pflow/nodes/python/__init__.py`
- `src/pflow/nodes/python/python_code.py`
- `tests/test_nodes/test_python/__init__.py`
- `tests/test_nodes/test_python/test_python_code.py`

Implemented the full node in one pass since it's self-contained (~300 lines):
- prep(): validate params, AST parse, type check
- exec(): ThreadPoolExecutor + stdout/stderr capture
- exec_fallback(): context-specific error formatting
- post(): result type validation + shared store writes

Result: 34 tests written by test-writer-fixer agent, all passing.
- ✅ `make test` passes (34/34)
- ❌ `make check` found 1 mypy error

---

## [03] - Fix: mypy error on `_validate_code` return type

mypy complained: "Returning Any from function declared to return str" at line 268.

Original code:
```python
def _validate_code(self) -> str:
    code = self.params.get("code")
    if not code or not isinstance(code, str) or not code.strip():
        raise ValueError("Code parameter cannot be empty")
    return code
```

Problem: `self.params.get("code")` returns `Any`. The `not code` check is evaluated before `isinstance`, so mypy can't narrow the type by the time it reaches `return`.

Fix: Removed the redundant `not code` guard — `isinstance` already handles `None` (returns False), and empty string is caught by `not code.strip()`.

```python
def _validate_code(self) -> str:
    code = self.params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Code parameter cannot be empty")
    return code
```

- ✅ mypy passes
- 💡 Insight: When narrowing `Any` for mypy, `isinstance` must be the dominant guard — don't short-circuit with truthiness checks before it.

---

## [04] - Test Review: Behavioral vs Implementation Detail Tests

Critically reviewed all 34 tests. Found significant issues with test quality.

**Removed 11 tests** (implementation details, not behavior):
- 6 tests for private helpers `_extract_annotations`, `_get_outer_type` — behavior already covered through public API
- `test_node_name_is_code` — attribute check, caught by registry tests
- `test_max_retries_configuration` — internal config constants
- `test_no_builtins_restriction` — tested `len()` works (testing Python, not our node)
- `test_result_capture`, `test_result_type_validation_success` — redundant with other success tests
- `test_stdout_stderr_empty_on_exec_error` — documents PocketFlow internals

**Added 7 tests** (important behavioral gaps):
- `test_dict_result_with_structured_data` — THE primary use case for downstream `${node.result.field}` access
- `test_no_inputs_pure_computation` — valid common pattern
- `test_none_input_fails_type_check` — catches upstream failures early
- `test_input_mutation_affects_original` — documents pass-by-reference semantics
- `test_bool_passes_as_int` — Python subclass quirk (`bool` is subclass of `int`)
- `test_int_passes_as_float` — documents TYPE_MAP design decision
- `test_unknown_type_annotation_skips_check` — custom types don't crash
- `test_whitespace_only_code_rejected` — boundary case
- `test_syntax_error_includes_line_info` — spec requirement, was untested

Result: 34 → 30 tests. Fewer tests, better coverage of what matters.

---

## [05] - DEVIATION FROM PLAN: `test_unknown_type_annotation_skips_check` failure

- **Original plan**: Test with `data: DataFrame` annotation to show unknown types skip isinstance check
- **Why it failed**: Python's `exec()` eagerly evaluates annotations. `data: DataFrame` triggers `NameError` at runtime because `DataFrame` isn't imported. The type validation skip in prep works correctly, but execution fails.
- **New approach**: Used `data: object` instead — `object` is a real builtin not in our TYPE_MAP, so it tests the skip behavior without causing a NameError during exec.
- **Lesson**: There's a gap between AST-time (annotations are strings) and exec-time (annotations are evaluated). Users writing `data: DataFrame` MUST import pandas first, even though our validator doesn't check the type.

---

## [06] - Fix: ruff TRY004 lint error

ruff flagged `_validate_inputs()`: "Prefer TypeError for invalid type" (TRY004).

```python
# Before
raise ValueError(f"'inputs' parameter must be a dict, got {type(inputs).__name__}")

# After
raise TypeError(f"'inputs' parameter must be a dict, got {type(inputs).__name__}")
```

- ✅ Correct — this IS a type error, not a value error
- 💡 Insight: ruff's TRY004 catches a real semantic issue, not just style.

---

## [07] - CRITICAL BUG FOUND: ThreadPoolExecutor `with` block hangs on timeout

Traced every execution path in the implementation. Found a serious bug.

**The bug**: `with ThreadPoolExecutor(...) as pool:` — when `future.result(timeout=X)` raises TimeoutError, the exception propagates out of the `with` block. `__exit__` calls `shutdown(wait=True)`, which **joins the worker thread**. For stuck code, this blocks indefinitely.

**Proof**:
```python
# With context manager — blocks for full 5 seconds
with ThreadPoolExecutor(max_workers=1) as pool:
    future = pool.submit(lambda: time.sleep(5))
    future.result(timeout=0.1)
# TimeoutError raised after 5.00s (not 0.1s!)
```

```python
# Without context manager — returns immediately
pool = ThreadPoolExecutor(max_workers=1)
future = pool.submit(lambda: time.sleep(5))
future.result(timeout=0.1)  # TimeoutError after 0.10s
pool.shutdown(wait=False, cancel_futures=True)
# Completed after 0.10s
```

**Fix**:
```python
pool = ThreadPoolExecutor(max_workers=1)
future = pool.submit(self._execute_code, code, namespace)
try:
    future.result(timeout=timeout)
finally:
    pool.shutdown(wait=False, cancel_futures=True)
```

**Impact**: Test suite went from **10.33s → 0.45s**. The old timeout test's `time.sleep(10)` zombie thread was blocking the `with` block for the full 10 seconds.

- ✅ Timeout now actually works for infinite loops
- ✅ Success path unaffected (future.result() blocks until done before we read namespace)
- 💡 Insight: Never use `with ThreadPoolExecutor` when you need timeout semantics. The context manager's cleanup guarantee is exactly what defeats the timeout.

---

## [08] - Slow test optimization

Full test suite went from ~7s to ~14s. Investigated.

**Root cause**: The timeout test used `time.sleep(10)` — the zombie thread lingered for 10 seconds in the background during parallel test execution, consuming worker resources.

**Fix**: Reduced to `time.sleep(0.1)` with `timeout=0.01`. Still tests the exact same behavior (code exceeds timeout → error action), just without the 10-second zombie.

Result: Full suite back to ~8.5s. Timeout test call time: 0.01s.

---

## Summary of Deviations from Plan

| # | Original Plan | What Happened | Lesson |
|---|---|---|---|
| 1 | 4 phases, implement incrementally | Implemented all at once — node is small enough | Don't phase tiny components; the overhead of stubs > just writing it |
| 2 | `with ThreadPoolExecutor` for timeout | Hangs on timeout due to `shutdown(wait=True)` | Always verify timeout behavior with real stuck code, not just "slow" code |
| 3 | `test_unknown_type_annotation_skips_check` with `DataFrame` | `exec()` evaluates annotations eagerly → NameError | AST parsing and exec have different evaluation models for annotations |
| 4 | `ValueError` for wrong inputs type | ruff correctly flags this as `TypeError` | Use the right exception type — linters catch semantic errors too |

---

## Phase 4: Integration Test + Registry Discovery

## [09] - Integration test: compiled workflow with template resolution

Added one integration test (`TestWorkflowIntegration::test_code_node_in_compiled_workflow`) that exercises the three integration seams unit tests can't reach:

1. **Registry → Compiler**: `ensure_test_registry()` scans `src/pflow/nodes/`, finds `PythonCodeNode` with `name = "code"`. Compiler resolves `"type": "code"` to the class.
2. **Template resolution inside `inputs` dict**: Workflow has `"inputs": {"data": "${source.data}"}`. The `TemplateAwareNodeWrapper` resolves `${source.data}` inside the nested dict BEFORE the code node's `prep()` runs. The code node receives a native Python list, not a template string.
3. **Namespaced shared store output**: Code node writes `shared["result"]` which becomes `shared["transform"]["result"]` via `NamespacedSharedStore`. Test verifies output at the namespaced path.

Test uses echo node as upstream data source (produces `data: [1..10]`), code node slices it (`data[:limit]`), verifies `shared["transform"]["result"] == [1, 2, 3, 4, 5]`.

Used `validate=False` in `compile_ir_to_flow` because template validation against interface metadata is a separate concern — the test focuses on runtime behavior.

Result: 31 tests, all passing in 0.35s. `make check` clean.

---

## Final State

- **4 files created**, 0 existing files modified
- **31 tests**, all passing in **0.35s**
- **`make check`** clean (ruff, mypy, deptry)
- **1 critical bug found and fixed** (ThreadPoolExecutor timeout)
- **Integration seams verified**: registry discovery, template resolution in nested dicts, namespaced output
