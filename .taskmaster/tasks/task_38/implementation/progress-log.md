# Task 38: Conditional Branching — Implementation Progress Log

## Implementation Steps

1. Add `MaxNodeVisitsError` to `src/pflow/core/exceptions.py`
2. Add loop guard to `src/pflow/runtime/instrumented_wrapper.py`
3. Modify Python code node for `next` variable (`src/pflow/nodes/python/python_code.py`)
4. Modify markdown parser for routing syntax (`src/pflow/core/markdown_parser.py`)
5. Fix topological sort for cycles (`src/pflow/core/workflow_data_flow.py`)
6. Write tests for Python code node `next` variable
7. Write tests for markdown parser routing
8. Write integration tests
9. Fix existing stub tests in compiler integration
10. Add example workflows
11. Update documentation (CLAUDE.md files)
12. Run `make test && make check`

---

## Phase 1: Core Implementation (Steps 1-5)

### Steps 1-4 executed in parallel (no dependencies between them)

**Step 1: MaxNodeVisitsError** — Straightforward addition to `exceptions.py`. Subclasses `RuntimeError` (not `PflowError`) so it propagates through the executor's error handling chain correctly — `executor_service.py` re-raises `RuntimeError` directly. Includes `node_id`, `visit_count`, `max_visits` attributes and a message mentioning `PFLOW_MAX_NODE_VISITS` env var for users who need to increase the limit.

**Step 2: Loop guard in InstrumentedNodeWrapper** — Three changes:
1. Import `MaxNodeVisitsError` and add `MAX_NODE_VISITS` constant from env var (default 100)
2. Add `node_visit_counts` to the `__execution__` dict (both creation and backward compat)
3. Add visit count check in `_run()` after `_initialize_execution_state` and before `_check_cache_validity`

Placement before cache check is critical: the guard must fire before cached loops can spin.

**Step 3: Python code node `next` variable** — Four changes in `PythonCodeNode`:
- `prep()`: Allow `next: str` annotation as alternative to `result`. Added `has_result` flag to prep dict. Validate `next` annotation type is `str`.
- `exec()`: Only require `result` in namespace if `has_result` is True. Capture `next` from namespace if present.
- `post()`: Validate `next` is non-empty string. Return `next` value as action (instead of `"default"`). Result type validation only fires if `has_result`.
- Docstring updated to document `next` variable and `<custom>` action.

Key insight: `"next" in namespace` only matches user-code assignments. The builtin `next()` function lives in `namespace["__builtins__"]`, not as a top-level namespace key.

**Step 4: Markdown parser routing** — The largest change. Added 4 new helper functions:
- `_parse_next_targets()`: Handles single, "end", and comma-separated target lists
- `_extract_next_targets_from_code()`: AST walks Python code for `next: str = "literal"` and `next = "literal"` assignments (only string constants)
- `_build_edges()`: Replaces the simple document-order edge generation with routing-aware logic
- `_validate_routing_targets()`: Validates edge targets exist with fuzzy "did you mean" suggestions

Modified `_build_node_dict()` to return `(node_dict, routing_dict)` tuple, extracting `next` and `on-error` from YAML params into routing metadata. Modified `parse_markdown()` caller to use new edge generation pipeline.

**Step 5: Topological sort fix** — Single change in `build_execution_order()`: only consider edges where `action is None or action == "default"` for topological ordering. Conditional edges (error, named routing) are alternative paths that may create backward edges (loops, error handlers pointing to earlier nodes).

- Verified: all 134 existing tests passed after Steps 1-5.

---

## Phase 2: Unit Tests (Steps 6-7, parallel)

**Step 6: Python code node tests** — Added `TestNextVariableRouting` class with 11 tests. Also updated `test_missing_result_annotation_rejected` whose error message changed (now mentions both `result` and `next`). All 44 node tests pass.

**Step 7: Markdown parser tests** — Added `TestConditionalBranching` class with 15 tests covering: next overrides, next end, single/multi targets, on-error edges, AST detection (literal and non-literal), invalid targets with fuzzy suggestions, params cleanup, backward compatibility, AST + document-order coexistence. All 92 parser tests pass.

---

## Phase 3: Integration Tests, Examples, Docs (Steps 8-11, parallel)

**Step 8: Integration tests** — Created `tests/test_integration/test_conditional_branching.py` with 10 tests across 5 classes: TestCodeDynamicRouting (3), TestErrorRouting (2), TestLoopExecution (1 initially), TestNextEnd (1), TestFullPipeline (3 markdown-to-execution tests).

Failure found during development: `test_pipeline_code_classification` initially failed because branch nodes (`positive`, `negative`) lacked `- next: end` directives. Without explicit termination, document-order edges caused fall-through. Added `- next: end` to both branches.

**Step 9: Stub compiler tests** — In `tests/test_runtime/test_compiler_integration.py`:
1. Added `"code"` node type to `create_real_test_registry()`
2. Replaced `branching_ir` fixture to use code router node with `next` variable
3. Replaced stub test methods with real assertions checking `__execution__["completed_nodes"]`

Root cause of stubs: test nodes (`ExampleNode`, etc.) always return `"default"`, making branching untestable. `PythonCodeNode` with `next` enables real routing.

**Step 10: Example workflows** — Created `examples/core/conditional-branching.pflow.md` and updated `examples/core/error-handling.pflow.md` to use `on-error` syntax. Updated `tests/test_core/test_ir_examples.py` for changed node IDs (underscores → hyphens).

**Step 11: Documentation** — Updated 4 CLAUDE.md files: root (moved Task 38 to completed), core (added routing syntax docs, MaxNodeVisitsError), nodes (dynamic routing via next), runtime (node_visit_counts in reserved keys).

---

## Phase 4: Test Fix — `test_instrumented_wrapper.py`

The `test_trace_collector_integration` test expected a specific `__execution__` dict shape that didn't include the new `node_visit_counts` key. Fixed by adding `"node_visit_counts": {"test_node": 1}` to the expected dict.

---

## Phase 5: Cache vs Loop Bug Discovery and Fix

### The Question

After all 12 steps passed, asked: "Are there HIGH VALUE tests that could catch actual bugs?"

### Analysis

Traced through the execution path for a looping node:

1. Code node runs, sets `next = "self"`, succeeds
2. `_cache_result_if_successful()` adds node to `completed_nodes` with config hash
3. Flow routes back to same node via action edge
4. `_check_cache_validity()` fires: node IS in `completed_nodes`, params unchanged, hash matches → **returns cached action without re-running**
5. Exit condition is never re-evaluated
6. Loop runs forever via cached actions until `MaxNodeVisitsError`

### Verification

Confirmed by reading `_check_cache_validity()` (line 565-590 of `instrumented_wrapper.py`):
- Hash computed from `_compute_node_config()` which hashes node params
- Params don't change between loop iterations (templates are raw strings at this layer)
- Cache returns stale first-iteration action indefinitely

### The Bug

**Any loop with an exit condition would never terminate.** The cache returns the first iteration's action forever. The `test_loop_guard_raises_at_limit` test didn't catch this because it always loops — cached "looper" action still loops, so it looks correct.

### First Test Attempt: Self-Referencing Loop

Tried a single code node that reads `${counter.result}` (its own output) to track iterations.

**Failed**: `NamespacedSharedStore.keys()` at line 142 explicitly excludes the own namespace to prevent recursion. So `${counter.result}` from within the counter node will never resolve.

```
ValueError: Unresolved variables in parameter 'inputs': ${counter.result}
Available context keys:
  • result (str): 0
```

- Insight: Self-referencing single-node loops are a design limitation of namespacing, not a bug we introduced.

### The Fix (3 parts)

**Part 1 — Cache invalidation** (`instrumented_wrapper.py`): After incrementing visit_count, if `visit_counts[self.node_id] > 1`, clear the node's cache entry (remove from `completed_nodes`, `node_actions`, `node_hashes`). Within a single `flow.run()`, a revisited node must re-execute.

**Part 2 — Visit count reset** (`compiler.py`): `flow.run()` now always resets `node_visit_counts` to `{}` before executing. This changed the existing conditional monkey-patch (`run_with_outputs` only when outputs declared) to an unconditional `run_with_hooks` that always wraps `flow.run()`.

This is critical for distinguishing loop revisits from resume revisits:
- **Loop**: visit counts accumulate within a single `flow.run()` → count > 1 → invalidate cache
- **Resume**: `flow.run()` called again → counts reset to {} → count = 1 → cache preserved

**Part 3 — Test updates**:
- `test_checkpoint_tracking.py`: Added `shared["__execution__"]["node_visit_counts"] = {}` between `wrapper._run()` calls to simulate what `flow.run()` does at the execution boundary
- `test_compiler_output_wrapping.py`: Updated function name assertions from `run_with_outputs` to `run_with_hooks`, and changed "no wrapper when no outputs" test to verify wrapper is always applied

### The Test: Two-Node Loop with Exit Condition

Used worker→checker pattern (avoids self-referencing namespace limitation):
- **worker** reads `${checker.result}`, increments, writes result
- **checker** reads `${worker.result}`, decides: if count >= 3 → "done", else → "worker"
- Pre-seeded `shared["checker"]["result"] = "0"` for first iteration

Assertions: done node ran, worker result is "3", visit counts are 3 for both nodes.

Without the cache fix, this test fails: worker runs once, gets cached, returns stale "default" action forever.

---

## Phase 6: Post-Implementation Review

Independent review of the staged code (`scratchpads/task-38/code-review-staged-20260314.md`) found one critical bug and several issues.

### Critical: Topological sort regression in `workflow_data_flow.py`

The Phase 1 fix (Step 5) filtered ALL non-default edges from the topological sort. This caused branch-only targets (e.g., `path-b` in `- next: path-a, path-b`) to have zero incoming edges. Kahn's algorithm ordered them before the router, making `${router.result}` references appear as forward-reference errors in validation.

**Reproduced**: A workflow with `router → path-a (action path-a), router → path-b (action path-b)` where `path-b` references `${router.result}`. Validation returned: `"Node 'path-b' references 'router' which comes after it in execution order"`.

**Root cause**: The fix was too aggressive — it excluded all named/error edges, but forward-direction named edges are valid data flow dependencies (branch targets depend on the router's output). Only backward edges (loops) create cycles.

**Fix**: Use node document-order positions to determine edge direction. Include forward edges (source before target) regardless of action type. Exclude only backward edges (source after target) with actions — these are loops.

```python
# Before (broken): only default edges included
if action is None or action == "default":

# After (fixed): forward edges of any type included, backward excluded
if action is None or source_pos < target_pos:
```

Verified with three cases:
1. Branch targets referencing upstream data → no false validation errors ✓
2. Retry loops (backward edges) → no CycleError ✓
3. Error handlers referencing failing node → correct ordering ✓

### Other fixes from review

1. **Example missing `- inputs:` mapping** — `examples/core/conditional-branching.pflow.md` classify node had `data: str` but no input wiring. Would always fail and route to handle-error. Added `- inputs: { data: "${fetch-data.output}" }`.

2. **PocketFlow warning in test** — `test_on_error_not_triggered_on_success` produced a noisy UserWarning because the test IR only had an error edge. Suppressed with `warnings.catch_warnings()` and explanatory comment.

3. **`next = "end"` in code would fail validation** — AST extraction included `"end"` as a routing target, creating an edge to nonexistent node `"end"`. Added filter in `_extract_next_targets_from_code()` to skip the `"end"` keyword.

4. **Integration tests used `validate=False` exclusively** — None of the tests exercised the validation pipeline, so the topological sort regression passed all tests. Added `validate` parameter to test helpers. Added `test_pipeline_validated_branching_with_upstream_refs` that compiles with `validate=True` and has branch targets using `${router.result}` via `inputs:` mapping.

5. **Template resolution in branch targets untested** — The most common real-world pattern (shell commands in branch targets using `${router.result}`) wasn't tested. Added `test_pipeline_template_resolution_in_branch_targets` — full markdown-to-execution test that verifies `${router.result}` resolves correctly inside a branched-to shell node.

---

## Final State

- **3831 tests pass**, 0 failures, 604 skipped, 0 warnings
- `make check` clean: ruff, ruff-format, mypy, deptry all pass
- All 12 implementation steps + cache bug fix + review fixes complete

## Files Modified (Final)

| File | Change |
|------|--------|
| `src/pflow/core/exceptions.py` | Add `MaxNodeVisitsError` |
| `src/pflow/runtime/instrumented_wrapper.py` | Loop guard + cache invalidation for revisited nodes |
| `src/pflow/runtime/compiler.py` | `flow.run()` always wrapped; resets visit counts per execution |
| `src/pflow/nodes/python/python_code.py` | `next` variable support in prep/exec/post |
| `src/pflow/core/markdown_parser.py` | Parse `next`/`on-error`, AST detection, edge generation, `"end"` filter |
| `src/pflow/core/workflow_data_flow.py` | Position-based edge filtering for topological sort |
| `tests/test_nodes/test_python/test_python_code.py` | 11 new tests (TestNextVariableRouting) |
| `tests/test_core/test_markdown_parser.py` | 15 new tests (TestConditionalBranching) |
| `tests/test_integration/test_conditional_branching.py` | NEW: 13 tests (loops, validation, templates) |
| `tests/test_runtime/test_compiler_integration.py` | Fixed 2 stub tests + registry |
| `tests/test_runtime/test_instrumented_wrapper.py` | Fixed assertion for node_visit_counts |
| `tests/test_runtime/test_checkpoint_tracking.py` | Visit count reset between resume calls |
| `tests/test_runtime/test_compiler_output_wrapping.py` | Updated for run_with_hooks |
| `tests/test_core/test_ir_examples.py` | Updated for changed example node IDs |
| `examples/core/conditional-branching.pflow.md` | NEW example (with correct input wiring) |
| `examples/core/error-handling.pflow.md` | Updated with on-error syntax |
| `CLAUDE.md` | Task 38 moved to completed |
| `src/pflow/core/CLAUDE.md` | Routing syntax + MaxNodeVisitsError docs |
| `src/pflow/nodes/CLAUDE.md` | Dynamic routing via next docs |
| `src/pflow/runtime/CLAUDE.md` | node_visit_counts in reserved keys |

## Key Decisions

1. **`MaxNodeVisitsError` subclasses `RuntimeError`, not `PflowError`** — ensures it propagates through executor's error handling chain
2. **Loop guard fires before cache check** — prevents cached loops from spinning
3. **Visit counts reset at `flow.run()` boundary** — distinguishes loop revisits from resume revisits
4. **`flow.run()` always wrapped** (not just when outputs declared) — needed for visit count reset
5. **Self-referencing single-node loops unsupported** — NamespacedSharedStore design limitation; use two-node loops instead
6. **AST detection extracts only string literals** — dynamic `next = variable` assignments don't generate edges (correct: edge topology must be static)
7. **Position-based edge filtering** — topological sort includes forward edges (any action), excludes backward edges (loops). Document-order edges (no action) always included.

## Key Insights

- The checkpoint cache was designed for resume, not loops. Adding backward edges exposed an implicit assumption: "nodes only execute once per flow.run()"
- NamespacedSharedStore's `keys()` excluding own namespace (anti-recursion) makes self-referencing templates impossible — this is a design constraint, not a bug
- The distinction between "within a flow.run() revisit" (loop) and "across flow.run() revisit" (resume) is the critical boundary for cache correctness
- Topological sort must include forward named/error edges to correctly order branch targets. The naive "exclude all non-default" approach breaks validation for any branch target that references upstream data.
- Integration tests must exercise the validation pipeline (not just `validate=False`) to catch ordering regressions
