# Task 38 Review: Conditional Branching in Workflows

## Metadata

- **Implementation Date**: 2026-03-14
- **Branch**: `feat/conditional-branching`

## Executive Summary

Added conditional branching to `.pflow.md` workflows via three mechanisms: `- on-error: node-id` for error routing, `- next: node-id` / `- next: end` for static routing, and `next: str = "node-id"` in python code nodes for dynamic data-driven routing. The infrastructure (PocketFlow, compiler, IR schema) already supported action-based transitions — the work was in the markdown parser, python code node, and supporting systems (loop guard, cache invalidation, topological sort).

## Implementation Overview

### What Was Built

1. **Markdown routing syntax** — `- next:`, `- on-error:`, `- next: end` parsed from step params into routing metadata, used by a new edge generation pipeline
2. **Python code node `next` variable** — code sets `next: str = "node-id"` to dynamically choose the next node; `result` becomes optional when `next` is declared
3. **AST-based edge detection** — parser walks python code blocks to find literal `next = "..."` assignments and creates routing edges automatically
4. **Loop guard** — per-node visit counter in `InstrumentedNodeWrapper`, raises `MaxNodeVisitsError` at 100 visits (configurable via `PFLOW_MAX_NODE_VISITS`)
5. **Cache invalidation for loops** — revisited nodes within a single `flow.run()` have their cache cleared so exit conditions are re-evaluated
6. **Visit count reset** — `flow.run()` always wrapped by `run_with_hooks` (not just when outputs declared) to reset visit counts between executions

### What Was Built That Wasn't in the Original Spec

The original task spec (written in 2024) assumed JSON format, planner prompt updates, and "low effort — runtime already supports it." In reality:

- **The markdown format had no routing syntax at all** — designing and implementing the `.pflow.md` branching syntax was the core work
- **Cache invalidation bug** — looping nodes returned cached first-iteration actions forever, never re-evaluating exit conditions. Required cache invalidation logic and `flow.run()` wrapping changes
- **Topological sort regression** — filtering non-default edges from `build_execution_order()` broke validation for branch targets that reference upstream data
- **Planner is gated** — planner prompt updates (the original scope) were irrelevant

### Implementation Approach

Design-first: spent significant time with the user exploring what syntax would be most natural for AI agents to write. Key insight: AI agents think top-to-bottom and want routing decisions inline with the decision point, not in a separate section. This led to the `- next:`/`- on-error:` on nodes + `next` variable in code design.

## Files Modified/Created

### Core Changes

| File | What Changed |
|------|-------------|
| `src/pflow/core/markdown_parser.py` | New functions: `_parse_next_targets()`, `_extract_next_targets_from_code()`, `_build_edges()`, `_validate_routing_targets()`. Modified `_build_node_dict()` to return `(node, routing)` tuple. Modified `parse_markdown()` to use new edge generation pipeline. |
| `src/pflow/nodes/python/python_code.py` | `prep()`: `result` optional when `next` declared, validates `next` annotation is `str`. `exec()`: captures `next` from namespace. `post()`: returns `next` value as action string, validates non-empty string. |
| `src/pflow/runtime/instrumented_wrapper.py` | Loop guard (visit counter before cache check), cache invalidation for revisited nodes (removes from `completed_nodes`, `node_actions`, `node_hashes`). |
| `src/pflow/runtime/compiler.py` | `run_with_outputs` → `run_with_hooks` (always applied, resets `node_visit_counts` per execution). |
| `src/pflow/core/workflow_data_flow.py` | Position-based edge filtering: forward edges included regardless of action type, backward edges excluded. |
| `src/pflow/core/exceptions.py` | `MaxNodeVisitsError(RuntimeError)` — not `PflowError`, so it propagates through executor's error chain. |
| `src/pflow/cli/resources/cli-agent-instructions.md` | Removed "No Conditional Logic" limitation, added Conditional Branching pattern, updated related sections. |

### Test Files

| File | Tests | Critical? |
|------|-------|-----------|
| `tests/test_integration/test_conditional_branching.py` | 13 tests (NEW) | **Yes** — catches real integration bugs |
| `tests/test_core/test_markdown_parser.py` | 15 tests added | Yes — parser edge generation |
| `tests/test_nodes/test_python/test_python_code.py` | 11 tests added | Yes — `next` variable contract |
| `tests/test_runtime/test_compiler_integration.py` | 2 stubs fixed + registry | Medium — validates compiler wiring |
| `tests/test_runtime/test_instrumented_wrapper.py` | 1 assertion updated | Low — snapshot test |
| `tests/test_runtime/test_checkpoint_tracking.py` | Visit count resets added | Medium — resume vs loop distinction |
| `tests/test_runtime/test_compiler_output_wrapping.py` | Renamed assertions | Low — function name change |
| `tests/test_core/test_ir_examples.py` | Example content tests | Low — structural checks |
| `tests/test_cli/test_instructions.py` | Line count assertion widened | Low — content size guard |

## Integration Points & Dependencies

### Incoming Dependencies

- **Markdown parser** (`parse_markdown()`) — all consumers (CLI, MCP server, workflow manager, tests) now get IR with action-based edges
- **Python code node** — any workflow using `type: code` can now use `next` variable
- **InstrumentedNodeWrapper** — ALL node executions now have visit counting and cache invalidation

### Outgoing Dependencies

- **PocketFlow** `Flow._orch()` / `get_next_node()` — unchanged, action-based routing worked already
- **Compiler** `_wire_nodes()` — unchanged, already handled `action` field in edges
- **IR schema** — unchanged, `action` field already existed on edges
- **`find_similar_items()`** from `suggestion_utils.py` — used for "did you mean" in validation errors
- **`TemplateAwareNodeWrapper`** — resolves `${router.result}` in branch target params; verified working

### Shared Store Keys

- `shared["__execution__"]["node_visit_counts"]` — `dict[str, int]`, maps node ID to visit count within current `flow.run()`. Reset between executions by `run_with_hooks`.
- `shared["__execution__"]["completed_nodes"]` — existing `list[str]`, now has entries removed during cache invalidation for revisited nodes.

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative Considered |
|----------|-----------|----------------------|
| `next` variable (not `return`) | `return` doesn't work inside Python's `exec()` — raises SyntaxError. `next` is consistent with `result` pattern. | Wrapping user code in a function (complex AST transformation) |
| `next` variable (not `action`) | "Next" matches the markdown field `- next:`, creates consistency. Users think "where does this go next?" not "what action string?" | `action` (PocketFlow jargon), `goto` (negative connotations) |
| `MaxNodeVisitsError(RuntimeError)` | `RuntimeError` propagates through `executor_service.py` which re-raises it directly. `PflowError` would be caught and formatted differently. | Subclassing `PflowError` |
| Position-based edge filtering in topological sort | Forward edges establish valid data dependencies. Backward edges (loops) create cycles. Node document order is the natural proxy for "intended direction." | Filter all non-default edges (caused regression), include all edges (caused CycleError on loops) |
| `flow.run()` always wrapped | Visit count reset must happen at every `flow.run()` boundary to distinguish loop revisits from resume revisits. Previously only wrapped when outputs declared. | Resetting in `InstrumentedNodeWrapper` (can't distinguish loop from resume) |
| `"end"` filtered from AST extraction | `next = "end"` in code would create an edge to nonexistent node `"end"`. It's a keyword, not a node reference. | Validating and erroring (confusing message) |

### Technical Debt Incurred

- **`completed_nodes` is a list, not a set** — grows with duplicate entries during loops (bounded by MAX_NODE_VISITS=100). Can't change to set because resume system uses order. Acceptable.
- **Self-referencing single-node loops don't work** — `NamespacedSharedStore.keys()` excludes own namespace to prevent recursion, so `${counter.result}` from within counter never resolves. Use two-node loops instead. This is a NamespacedSharedStore design constraint, not a branching issue.

## Testing Implementation

### Critical Test Cases

| Test | What It Catches |
|------|----------------|
| `test_loop_with_exit_condition` | Cache invalidation bug — without the fix, exit conditions are never re-evaluated because cached action is returned forever |
| `test_pipeline_validated_branching_with_upstream_refs` | Topological sort regression — branch targets ordered before router cause false validation errors |
| `test_pipeline_template_resolution_in_branch_targets` | Template resolution in branches — `${router.result}` must resolve inside branched-to shell nodes |
| `test_loop_guard_raises_at_limit` | Infinite loop protection — uses `monkeypatch` to lower MAX_NODE_VISITS to 5 for speed |
| `test_on_error_routes_to_handler` | Error routing actually works end-to-end (code node with `1 // 0` → error edge → handler) |
| `test_code_skip_ahead` | Skip-ahead pattern — intermediate nodes NOT executed when `next` jumps forward |

### Tests That DON'T Catch Real Bugs (Coverage Only)

- `test_next_not_stored_in_shared` — verifies `next` isn't in shared store (it never would be)
- `test_document_order_unchanged_without_routing` — backward compatibility (obvious)
- `test_next_end_on_last_node` — trivial case

## Unexpected Discoveries

### Cache Invalidation Bug

The checkpoint cache was designed for resume, not loops. When a node is revisited in a loop:
1. Node runs, succeeds, gets cached (hash + action stored)
2. Flow routes back to same node
3. `_check_cache_validity()` finds the node in `completed_nodes`, hash matches → returns cached action
4. Exit condition never re-evaluated
5. Loop runs forever via cached actions until `MaxNodeVisitsError`

This was invisible in the initial loop guard test because that test always loops (cached "looper" action still loops). Only a test with an EXIT CONDITION exposed it.

### Topological Sort Regression

Initial fix filtered ALL non-default edges from `build_execution_order()`. This seemed correct (loops create backward edges → cycles → CycleError). But it made branch-only targets invisible to the topological sort — they appeared as root nodes, got ordered first, and their `${router.result}` references became false forward-reference errors.

The fix (position-based filtering) only emerged after an external code review reproduced the bug with a concrete workflow.

### JSON Auto-Parse Interaction

The checked-in example failed on first manual test because template system auto-parses JSON strings (Task 105). Shell node echoing `{"key": "value"}` → template `${shell.stdout}` resolves to a Python `dict`, not a `str`. Code nodes expecting `data: str` fail with type mismatch. Must use `data: dict` and skip `json.loads()`.

## Patterns Established

### Routing Code Node Pattern

```python code
data: dict
result: str = data["category"]

if data["category"] == "premium":
    next: str = "premium-handler"
else:
    next: str = "standard-handler"
```

- `result` stores output data for downstream nodes
- `next` controls routing (returned as action string)
- Both are optional (at least one required)
- `next` not stored in shared store

### Branch Target Layout

```markdown
### router (code node with next)
### main-flow-continuation
### branch-target-a (- next: convergence-point)
### branch-target-b (- next: convergence-point)
### convergence-point
```

Branch targets at the bottom, `- next: end` or `- next: convergence-point` to prevent fall-through.

### Anti-Patterns to Avoid

- **Don't name routing actions starting with "error"** — `startswith("error")` checks at multiple layers would misinterpret them
- **Don't use `return` in code nodes** — raises SyntaxError inside `exec()`
- **Don't create self-referencing template loops** — `${self.result}` from within self never resolves due to namespace exclusion
- **Don't assume `validate=False` tests cover validation** — the topological sort regression proved otherwise

## Breaking Changes

### API/Interface Changes

- `_build_node_dict()` now returns `tuple[dict, dict]` instead of `dict` — any direct callers must destructure
- `flow.run` is ALWAYS monkey-patched to `run_with_hooks` (not just when outputs declared) — `run.__name__` changed from `run_with_outputs` to `run_with_hooks`
- `shared["__execution__"]` has new key `node_visit_counts`

### Behavioral Changes

- Nodes can now be visited >1 time (loops). Cache is invalidated on revisit.
- Python code nodes can return custom action strings (any string, not just "default"/"error")
- `result` annotation no longer required in code nodes when `next` is declared

## Future Considerations

### Extension Points

- **New routing actions on existing nodes** — shell/http/llm nodes currently only return "default" or "error". Future work could add custom actions (e.g., HTTP node returning status-code-based actions).
- **`- on-retry: node-id`** — retry routing (currently handled by loops with `- next:`). A dedicated syntax could be cleaner.
- **Task 125 (Human-in-the-Loop)** — approval gates could use the same `next` variable pattern: code node pauses for input, then routes based on response.

### Scalability Concerns

- `completed_nodes` list grows with loop iterations (bounded by MAX_NODE_VISITS)
- `node_visit_counts` is reset per `flow.run()` — nested workflows (Task 59) that share `__execution__` state need to consider isolation

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/core/markdown_parser.py` `_build_edges()` — this is the edge generation logic
2. Read `src/pflow/nodes/python/python_code.py` `post()` — this is where `next` becomes an action string
3. Read `src/pflow/runtime/instrumented_wrapper.py` `_run()` lines 653-670 — loop guard + cache invalidation
4. Run `uv run pflow --no-trace examples/core/conditional-branching.pflow.md` to see it work

### Common Pitfalls

- **Template auto-parse**: Shell nodes echoing JSON → templates resolve to `dict`, not `str`. Code nodes must declare `data: dict` (not `str`) when consuming JSON shell output.
- **`validate=False` hides bugs**: Always write at least one integration test with `validate=True` for any feature that changes edge generation or node ordering.
- **Edge direction matters for topological sort**: Forward edges (source before target in document order) are included. Backward edges are excluded. If you add a new edge type, verify it works with `build_execution_order()`.
- **Cache invalidation is per-`flow.run()`**: Visit counts reset between runs. If you add a new execution boundary, ensure visit counts are reset there too.

### Test-First Recommendations

When modifying branching:
1. Run `tests/test_integration/test_conditional_branching.py` — catches integration issues
2. Run `tests/test_core/test_markdown_parser.py::TestConditionalBranching` — catches parser issues
3. Run `tests/test_nodes/test_python/test_python_code.py::TestNextVariableRouting` — catches node issues
4. Run `uv run pflow --no-trace examples/core/conditional-branching.pflow.md` — catches real execution issues

---

*Generated from implementation context of Task 38*
