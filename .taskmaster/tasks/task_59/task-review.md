# Task 59 Review: Nested Workflows — Polish and Ship

## Metadata
- Implementation Date: 2026-03-14
- Branch: `feat/nested-workflows`
- Baseline: 3857 passed → Final: 3872 passed

## Executive Summary

Refactored the existing WorkflowExecutor from a verbose API (`workflow_ref`/`workflow_name`, `param_mapping`, `output_mapping`) to a clean design where workflow nodes look identical to any other pflow node. Child inputs are regular params, child outputs auto-expose via the namespace system. Fixed 3 bugs (traceback suppression, relative path resolution, output_mapping error escalation), added input validation against child declared inputs, rewrote all tests, and created working end-to-end examples.

## Implementation Overview

### What Was Built

**Tier 1 — Bug fixes:**
- Traceback suppression: `logger.exception()` → `logger.debug(..., exc_info=True)` in compiler.py (7 sites)
- Relative path resolution: injected `_pflow_workflow_file` into `enhanced_params` in CLI's `_prepare_execution_environment()`
- output_mapping error escalation: missing keys → error action (not just warning)

**Tier 2 — Better errors:**
- `_validate_child_params()`: loads child IR, compares provided params against declared `## Inputs`, gives actionable error with "You provided X, Available inputs: Y"

**Tier 3 — New syntax (the big one):**
- Unified `workflow` param (file path OR saved name, auto-detected)
- Params-as-inputs: non-reserved params auto-extracted as child inputs
- Auto-outputs: child's `## Outputs` (or all non-internal keys) exposed via namespace
- Removed: `workflow_ref`, `workflow_name`, `param_mapping`, `output_mapping`, `isolated`/`scoped` storage modes
- Template validator: resolves child workflow outputs at validation time
- Compiler: removed redundant output_mapping handling

### Implementation Approach

The key insight was: **workflow nodes should work exactly like every other node in pflow.** Every other node takes params and exposes outputs via `${node_id.key}`. The old API with `param_mapping`/`output_mapping` was a separate concept that agents had to learn. The new design requires zero new concepts.

The auto-output mechanism relies on an existing architectural fact: `NamespacedNodeWrapper` wraps `WorkflowExecutor`, so writes in `post()` automatically go to `shared[node_id][key]`. We just needed `post()` to write the right keys.

## Files Modified/Created

### Core Changes
- `src/pflow/runtime/workflow_executor.py` — Full rewrite: unified `workflow`, params-as-inputs, auto-outputs, removed 4 storage modes → 2
- `src/pflow/runtime/template_validator.py` — Added `_resolve_child_workflow_outputs()`, updated `_extract_node_outputs()` with `initial_params` param, added dynamic workflow fallback in `_validate_namespaced_output()`
- `src/pflow/runtime/compiler.py` — Traceback suppression (7 logger changes), removed redundant output_mapping loop in `_validate_outputs()`
- `src/pflow/execution/executor_service.py` — No changes (Tier 1b fix went into `cli/main.py`)
- `src/pflow/cli/main.py` — Injected `_pflow_workflow_file` into `enhanced_params` at line ~1373

### Test Files
- `tests/test_runtime/test_workflow_executor/test_workflow_executor.py` — 7 tests (rewritten)
- `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` — 33 tests (rewritten, added new-syntax tests)
- `tests/test_runtime/test_workflow_executor/test_integration.py` — 8 tests (rewritten, added auto_output_exposure)
- `tests/test_runtime/test_workflow_executor/test_workflow_name.py` — 8 tests (rewritten for unified `workflow` param)
- `tests/test_integration/test_workflow_manager_integration.py` — 6 tests updated (old API → new)
- `tests/test_runtime/test_output_validation.py` — 1 test updated (output_mapping → dynamic)
- `tests/test_core/test_workflow_validator.py` — 2 tests replaced (output_mapping → auto-outputs + dynamic)
- `tests/test_cli/test_nested_workflow_cli.py` — **New file**: 5 CLI e2e tests
- `examples/nested/` — Replaced 3 old examples + README with 2 working examples + README

### Critical Tests
- `test_auto_output_exposure` (integration) — Validates the double-namespace chain: child node writes → child namespace → WorkflowExecutor.post() copies → parent namespace. This caught real bugs during development.
- `test_three_level_nesting_with_relative_paths` (CLI) — Validates `_pflow_workflow_file` propagation at depth 3 with relative file paths across directories.
- `test_nested_workflow_e2e` (CLI) — Full stack: markdown → compile → execute child → auto-output → downstream shell node uses output.
- `test_missing_required_child_input_gives_actionable_error` (comprehensive) — Validates the Tier 2 error message format.
- `test_compilation_error_no_error_log` (compiler) — Ensures tracebacks don't leak to agents.

## Integration Points & Dependencies

### Load-Bearing Integration Points

**1. NamespacedNodeWrapper wrapping WorkflowExecutor**
The entire auto-output mechanism depends on `NamespacedNodeWrapper` intercepting `post()` writes. When `post()` does `shared["result"] = value`, the namespace proxy redirects to `raw_shared[node_id]["result"]`. If the compiler ever skips namespace wrapping for workflow nodes, auto-outputs break silently.

**2. `populate_declared_outputs()` monkey-patch on `flow.run`**
The compiler wraps `flow.run` (compiler.py:1256-1281) to call `populate_declared_outputs()` after successful execution. For nested workflows, this runs INSIDE `sub_flow.run(child_storage)`. This means child's `## Outputs` are at root level of `child_storage` when `sub_flow.run()` returns. `post()` reads them from there.

**3. `_pflow_workflow_file` propagation chain**
CLI sets it in `enhanced_params` → `executor_service._initialize_shared_store()` copies to shared → WorkflowExecutor reads it in `_resolve_safe_path()` → WorkflowExecutor sets it in `_create_child_storage()` for the next level. Break any link → relative paths fail at that depth.

**4. Template validator file I/O**
`_resolve_child_workflow_outputs()` loads child workflow files during validation. This is new — the template validator was previously pure computation on the IR dict. Failures are caught and fall through to dynamic (accept any output), so it's safe but adds a new failure mode.

### Shared Store Keys
- `_pflow_depth` (int) — Current nesting depth, incremented per level
- `_pflow_stack` (list[str]) — Execution stack for circular detection (resolved paths)
- `_pflow_workflow_file` (str) — Current workflow's resolved file path, used for relative path resolution

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative Considered |
|----------|-----------|----------------------|
| Unified `workflow` param | One param handles files and saved names. Agents don't need to know the difference. | Keep separate `workflow_ref`/`workflow_name` — rejected: unnecessary complexity |
| `_is_file_reference()` heuristic | Checks for `/`, `\`, `.` prefix, `.pflow.md` suffix. Simple, covers all real cases. | Parse as path and check existence — rejected: too expensive during validation |
| Auto-output via namespace | Consistent with every other node type. Zero new concepts for agents. | Keep `output_mapping` — rejected: redundant with namespace system |
| Remove `isolated`/`scoped` storage modes | No real use case. `mapped` + `shared` cover all needs. | Keep all 4 — rejected: theoretical complexity for zero value |
| Clean break, no backward compat | No users. Simpler code (one path, not two). Cost: rewrite ~60 tests. | Backward compat — rejected by user decision |
| Template validator loads child files | Gives static validation for `${workflow_node.output}` references. | Skip validation for workflow outputs — rejected: loses real value (typo catching) |
| Dynamic workflow fallback | When child can't be loaded (template ref, missing file), accept any output reference. | Fail validation — rejected: false positives for dynamic references |

### Technical Debt

- **Template validator file I/O**: `_resolve_child_workflow_outputs()` does file I/O during validation. Clean but mixes concerns. If validation perf becomes an issue, this is where to look.
- **`_is_file_reference()` edge cases**: A saved workflow named `my.workflow` would be misclassified as a file reference. Currently impossible (save validates: lowercase, numbers, hyphens only) but worth noting.

## Unexpected Discoveries

### output_mapping was fundamentally broken with namespacing

The old `output_mapping` design had a subtle bug: `post()` wrote `shared[parent_key] = child_storage[child_key]`, but the NamespacedNodeWrapper intercepted this and stored it at `shared[node_id][parent_key]`. So the mapped key ended up at `shared["process_title"]["mapped_name"]`. Downstream templates accessed it as `${process_title.mapped_name}` which worked — but only because the namespace system coincidentally provided the right path. Two integration tests had output_mapping that was ALWAYS silently failing (the mapped keys were never actually at the expected location). The auto-output design is architecturally cleaner because it works WITH the namespace system instead of accidentally around it.

### The double-namespace chain for undeclared outputs

When a child workflow has no `## Outputs`, `post()` copies all non-internal keys from `child_storage`. One of those keys is `"transform"` — a dict containing the child node's namespaced outputs. The parent's namespace wrapper puts this at `parent_shared["workflow_node"]["transform"]`. Downstream accesses it as `${workflow_node.transform.stdout}` — a 3-level path traversal. This works correctly but is non-obvious.

## Patterns Established

### RESERVED_PARAMS pattern
```python
RESERVED_PARAMS = frozenset({
    "workflow", "workflow_ir", "storage_mode",
    "max_depth", "error_action", "__registry__",
})

def _extract_child_inputs(self) -> dict[str, Any]:
    return {
        key: value
        for key, value in self.params.items()
        if key not in self.RESERVED_PARAMS and not key.startswith("__")
    }
```
Any future node that needs to separate its own config from user-provided data should follow this pattern.

### Child output resolution at validation time
`_resolve_child_workflow_outputs()` tries file → saved name → inline IR, with silent fallback to None. This pattern (try to load, fall through gracefully) could be reused for any validation that needs external context.

## Breaking Changes

### API Changes (no users, intentional clean break)
- `workflow_ref` → `workflow` (file paths)
- `workflow_name` → `workflow` (saved names)
- `param_mapping: {child_key: value}` → direct params: `child_key: value`
- `output_mapping: {child_key: parent_key}` → removed (auto via namespace)
- `storage_mode: "isolated"` → removed
- `storage_mode: "scoped"` → removed
- `scope_prefix` parameter → removed

## Future Considerations

### Tier 4 (not yet implemented)
- Agent instructions in `cli-agent-instructions.md`
- Registry visibility (`pflow registry list` showing `workflow`)
- Unknown param warning suppression for workflow executor config

### Tier 5 (deferred)
- Planner integration: re-enable `ComponentBrowsingNode` workflow context (planner is gated)

### Extension Points
- **Batch + workflow nodes**: Untested combination. Could work (batch wrapper creates isolated contexts per item) but needs design thought.
- **Template-based workflow references**: `workflow: ${dynamic_ref}` — supported at runtime, falls through to dynamic at validation time.
- **Child output type propagation**: Currently all auto-outputs are typed as `"any"`. Could propagate actual types from child's `## Outputs` declarations for richer validation.

## AI Agent Guidance

### Quick Start for Related Tasks
1. Read `src/pflow/runtime/workflow_executor.py` — the full WorkflowExecutor (~250 lines)
2. Read `src/pflow/runtime/namespaced_wrapper.py` + `namespaced_store.py` — understand how namespace interception works
3. Read `src/pflow/runtime/output_resolver.py` — understand `populate_declared_outputs()`
4. Read `examples/nested/` — see the actual syntax in action

### Common Pitfalls
- **Forgetting RESERVED_PARAMS**: If you add a new config param to WorkflowExecutor, ADD IT to `RESERVED_PARAMS` or it gets passed as child input.
- **Testing post() without namespace wrapper**: Unit tests call `post()` directly. In production, `shared` is a `NamespacedSharedStore` proxy. Writes to `shared["key"]` go to `raw_shared[node_id]["key"]`. Direct `post()` tests won't catch namespace-related bugs.
- **Assuming child_storage structure**: After `sub_flow.run(child_storage)`, the storage contains namespaced dicts (e.g., `child_storage["node_id"] = {"stdout": "..."}`) plus root-level declared outputs (if `## Outputs` exists). Don't assume flat key-value.

### Test-First Recommendations
When modifying WorkflowExecutor:
1. Run `tests/test_runtime/test_workflow_executor/` first (fast, catches API breaks)
2. Run `tests/test_cli/test_nested_workflow_cli.py` second (catches integration breaks)
3. Run `make test` last (catches collateral damage)

---

*Generated from implementation context of Task 59*
