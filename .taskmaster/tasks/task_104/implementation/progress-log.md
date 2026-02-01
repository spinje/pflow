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

## [10] - Error message audit and fix for AI agent consumption

Audited all 13 error paths. Found 3 weak spots where an AI agent iterating on a workflow wouldn't get enough information to self-correct:

### Fix 1: Empty code message (Low impact)
**Before**: `"Code parameter cannot be empty"` — doesn't name the param or show what a valid value looks like.
**After**:
```
Missing required 'code' parameter

Provide a Python code string with type-annotated inputs and result.
Example:
  "code": "data: list\nresult: list = data[:10]"
```

### Fix 2: Timeout — no suggestion (Medium impact)
**Before**: `"Python code execution timed out after 30 seconds"` — tells what happened but not what to do.
**After**:
```
Python code execution timed out after 30 seconds

Suggestions:
  - Increase timeout: "timeout": 60
  - Check for infinite loops or blocking I/O in code
  - Break long computation into multiple code nodes
```

### Fix 3: Generic runtime errors — no line number, no context (High impact)
**Before**: `"Code execution failed: division by zero"` — no line number, no source context, no suggestion.
**After**:
```
ZeroDivisionError: division by zero
  at line 3: result: int = x / y

Suggestions:
  - Fix the error in the code string above
  - Check input data types and values match expectations
```

**Key implementation change**: `_execute_code` now uses `compile(code, '<code>', 'exec')` instead of raw `exec(code)`. This tags user code frames with filename `'<code>'` so `_extract_error_location()` can filter the traceback to only user frames and extract the line number + source text.

Also improved NameError and ImportError messages to include line location and more specific fix suggestions (e.g., "Add to inputs dict" for NameError, "Add to requires field" for ImportError).

- mypy fix: `FrameSummary.lineno` is `int | None` in type stubs — added None guard.
- ruff auto-fixed f-string formatting in error messages.

Result: 31 tests passing (updated 3 assertion patterns for new messages, added line number assertion to runtime error test). `make check` clean.

---

## [11] - Fix: Flaky timeout test on CI (Linux/Python 3.10)

CI failure: `test_timeout_stops_long_running_code` — on slow Linux CI with Python 3.10, the 0.01s timeout vs 0.1s sleep had too small a margin. Two problems:

1. **Timing race**: ThreadPoolExecutor thread startup overhead on slow CI could mean `time.sleep(0.1)` completed before the 0.01s timeout was checked.
2. **Result set before sleep**: `result: int = 0` was set BEFORE `time.sleep(0.1)`, so if the sleep completed, the node succeeded instead of timing out.

Fix: `time.sleep(10)` with `timeout=0.5` (20x margin). Sleep placed BEFORE result assignment so timeout is the only path to success. The zombie sleep thread self-terminates after 10s (not an infinite loop).

---

---

## Phase 5: Agent Instructions Update

## [12] - The three-node mental model and why "no caveats" matters

The code node doesn't just add a capability — it **redefines what shell is for**. The user's insight crystallized into a clean three-way split:
- **Shell** = run a program (side effects, exit codes, external tools)
- **Code** = transform data (filter, reshape, merge, compute on native objects)
- **LLM** = interpret/judge (creative decisions, understanding)

The critical decision: jq/awk/sed for inter-node data transformation is now an anti-pattern. Not "secondary" or "use code node first" — gone entirely from recommended patterns. The user was explicit: "no caveats that can confuse." A document that shows both approaches will have agents follow whichever they read last.

This forced a complete re-evaluation of the 1800-line agent instructions. ~90% of the document is node-agnostic (edges, templates, testing, MCP discovery) and needed no changes. The remaining ~10% was the jq-as-transformation guidance scattered across 31 locations — every decision tree, every example, every quick reference that said "shell+jq" for data work.

---

## [13] - What the instructions update revealed about the old mental model

The previous framing was binary: "structured data → shell, unstructured → LLM." This created a blind spot — shell was both "run programs" AND "transform data," and agents couldn't distinguish when to use which. The code node doesn't just replace jq; it **separates concerns** that were conflated.

Key insights from the edit:

**Cascading template references**: Changing a node from shell to code changes its output key from `stdout` to `result`. Every downstream `${node.stdout}` must become `${node.result}`. This cascaded through 5 template references across the document. Missing any one would create a broken example that agents would copy.

**The Complexity Checklist shrank by 60%**: The old checklist (30 lines) existed because shell pipelines are fragile — "Valid JSON → grep → sed → BROKEN JSON." Code node eliminates this entire failure class. The principles survive (fix at source, solve real problems) but the shell-specific advice is dead weight.

**jq has exactly two legitimate remaining uses**: (1) developer debugging on trace files (`cat trace.json | jq '...'`) and (2) text→JSON array conversion in shell pipelines for batch processing. Everything else is code node territory.

**Example ordering teaches the mental model**: In the Node Creation Patterns section, the order HTTP → Shell → Code → LLM → MCP implicitly teaches "shell runs programs, code transforms data, LLM interprets." Agents learn from example order, not just text.

**Token impact was net negative**: The document got ~17 lines shorter while gaining full code node documentation. The Complexity Checklist simplification (-18 lines) more than offset the gotchas block (+8 lines).

---

## [14] - Manual workflow testing: documentation examples must actually work

Created 8 test workflows from every code node example in the agent instructions and ran them as real pflow workflows. All passed.

The most important test was the **pipeline** (validate-structure → transform-data) because it exercises template chaining: `${validate-structure.result.items}` accessing a nested field from a code node's dict output. This is the exact pattern agents will use most — chaining code nodes where each one's output feeds the next through template references.

This also caught a missing comma in the JSON examples (between nodes in the array) that would have caused agents to get syntax errors when copy-pasting.

**Insight**: Documentation examples are code. They should be tested like code. An agent that copies a broken example will waste its entire context window debugging a documentation bug.

---

## Final State

- **31 tests**, all passing. `make check` clean. `make test` — 4059 tests, no regression.
- **Agent instructions updated** (`cli-agent-instructions.md`): 31 changes, document speaks with one voice
- **All 8 manual workflow tests pass**: every code node example verified as working pflow workflow
- **Change spec**: `scratchpads/code-node-instructions/pass3-findings.md` — authoritative reference for what changed and why
- **Remaining work**: Same changes likely needed in `mcp-agent-instructions.md`, `mcp-sandbox-agent-instructions.md`, and planner prompts — not scoped for this session
