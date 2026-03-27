# Task 136 Review: Recursive Sub-Workflow Validation at Parse Time

## Metadata

- Implementation Date: 2026-03-27
- Pull Request: https://github.com/spinje/pflow/pull/164
- Issue: https://github.com/spinje/pflow/issues/163
- Branch: `fix/sub-workflow-validation-errors`

## Executive Summary

Added step 8 to `WorkflowValidator.validate()`: recursive sub-workflow validation that catches parse errors, structural errors, unknown node types, data flow issues, and missing required inputs at validation time — before any nodes execute. Also fixed 6 pre-existing bugs discovered during research: `inputs` framework key leaking into child workflows, `_validate_child_params()` ignoring the `required` field, 3 display bugs with wrong `.get("required")` defaults, and `_pflow_workflow_file` missing from validate-only paths. The fix required touching 10 source files and adding 18 new tests (14 unit + 3 executor + 1 E2E).

## Implementation Overview

### What Was Built

1. **Step 8 in `WorkflowValidator.validate()`** — Three new static methods (`_validate_sub_workflows`, `_load_child_workflow`, `_load_child_from_file`) that recursively load and validate all `type: workflow` nodes. Handles file references, saved workflow names, inline `workflow_ir` dicts, and template refs (skipped). Cycle detection via shared `_seen` set. Child IR caching via shared `_ir_cache` across recursion levels.

2. **Static required-input checking** — Compares parent-provided param keys (minus `RESERVED_PARAMS` and `__` prefixed) against child's declared required inputs. This is a key insight: param keys are always static in the IR (YAML produces string keys, no template resolution on keys), so we can detect missing required inputs without any runtime values.

3. **`inputs` leak fix** — Added `"inputs"` to `WorkflowExecutor.RESERVED_PARAMS`. The `inputs` framework key (Task 161) was being passed through `_extract_child_inputs()` as a child workflow input.

4. **Required heuristic harmonization** — `_validate_child_params()` was the only consumer that ignored the `required` field (checked only `"default" in input_spec`). Fixed to use `input_spec.get("required", True)` matching `prepare_inputs()`, the IR schema, and 10+ other consumers. Also fixed 3 display bugs with wrong defaults.

5. **`_pflow_workflow_file` threading** — Injected into dummy params for CLI `--validate-only` and MCP `validate_workflow()` paths so relative sub-workflow paths resolve from the parent directory, not CWD.

### Deviations from Original Plan

| Planned | Actual | Why |
|---------|--------|-----|
| Single `_validate_sub_workflows()` method | 3 methods | `ruff` C901 rejected complexity 19 (max 10) |
| `ir_cache` local to each invocation | Shared across recursion via `_ir_cache` param on `validate()` | Code review found cross-nesting gap: grandchild validated at level 2, parent at level 1 couldn't find cached IR for input check |
| No `normalize_ir()` call | Added after `parse_markdown()` | Parser does not emit `ir_version` — all consumers must call `normalize_ir()`. Without it, every file-based child fails with `'ir_version' is a required property` |
| 11 tests | 18 tests | Added file-not-found, cross-nesting, E2E CLI, and required-true counterpart |

## Files Modified/Created

### Core Changes

- `src/pflow/core/workflow/validator.py` — **The main change.** Added `_seen` and `_ir_cache` params to `validate()`, step 8 call, and 3 new methods (~190 lines). All imports are lazy (inside method bodies) to avoid circular dependencies.
- `src/pflow/runtime/workflow_executor.py` — `"inputs"` added to `RESERVED_PARAMS`; `_validate_child_params()` heuristic fixed to check `required` field.
- `src/pflow/cli/main.py` — `_perform_validation()` accepts `source_file_path` param, injects `_pflow_workflow_file` into dummy params. Caller `_handle_validate_only_mode()` passes it from `ctx.obj["source_file_path"]`.
- `src/pflow/mcp_server/services/execution_service.py` — `validate_workflow()` injects `_pflow_workflow_file` for file/library sources. Also fixed redundant `WorkflowManager()` instantiation and stale comment.
- `src/pflow/core/workflow/context.py` — `.get("required", False)` → `.get("required", True)` (display bug).
- `src/pflow/execution/formatters/discovery_formatter.py` — `.get("required")` → `.get("required", True)` (display bug).
- `src/pflow/cli/commands/mcp.py` — `.get("required")` → `.get("required", True)` (display bug).

### Test Files

- `tests/test_core/test_sub_workflow_validation.py` — **NEW**, 14 tests. All resolution paths, all error categories, cycles, duplicate references, cross-nesting references.
- `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` — 3 new tests: `inputs` RESERVED_PARAMS filtering, `required: false` not rejected, `required: true` rejected.
- `tests/test_cli/test_nested_workflow_cli.py` — 1 new E2E test + updated assertion. The E2E test (`test_broken_sub_workflow_caught_before_execution`) is the most valuable: parent with upstream LLM → broken sub-workflow, asserts **zero LLM calls**, proving errors are caught at validation time.

## Integration Points & Dependencies

### Load-Bearing Integration Points

- **`WorkflowValidator.validate()` signature** — `_seen` and `_ir_cache` are private optional params. All 5 external callers use keyword args and never pass these. Backward-compatible. But if someone adds a new caller that passes positional args, they'd need to account for the new params.
- **`RESERVED_PARAMS`** — Single consumer: `_extract_child_inputs()`. Adding `"inputs"` here means `inputs` is no longer passed to child workflows at runtime. No existing code does this, but a future user writing `- inputs: {key: val}` on a workflow node would find it filtered.
- **`_pflow_workflow_file` in `extracted_params`** — Already present in execution paths (set by `_prepare_execution_environment()`). Now also present in validate-only paths. Used by `_resolve_child_workflow_outputs()` (step 4, template validation) and `_load_child_from_file()` (step 8, sub-workflow validation). If a new validation path is added without injecting this key, relative sub-workflow paths fall back to CWD resolution.

### The Two Validation Systems (Critical Context)

pflow has TWO independent validation pipelines:

1. **`WorkflowValidator.validate()`** (pre-execution, 8 steps) — Used by CLI, MCP, save service. This is where step 8 lives.
2. **`_validate_workflow()` in `compile_validation.py`** (compiler-time) — Called inside `compile_ir_to_flow()`. Does NOT call step 8.

Sub-workflow validation only runs in system 1. System 2 compiles sub-workflows at runtime via `WorkflowExecutor._compile_sub_workflow()`, which calls `compile_ir_to_flow()` with `validate=True` — so the child gets validated at compile time too. But that's at runtime, after upstream nodes have already executed. Step 8 catches errors before that.

Both systems call `validate_workflow_templates()`, which means child IRs are loaded twice during full execution: once by step 4's `_resolve_child_workflow_outputs()` (swallows errors, extracts outputs) and once by step 8 (surfaces errors, validates recursively). This duplication is intentional — coupling the two would be fragile.

## Architectural Decisions & Tradeoffs

### Key Decisions

**Static key comparison over mocking for required-input detection.** Considered mocking child inputs with `"__validation_placeholder__"` to run `prepare_inputs()` on the child. Investigation proved this doesn't help: `prepare_inputs()` uses lenient coercion that never raises on type mismatches. The one Category C error worth catching (missing required inputs) is detectable by comparing param key sets — no mocking needed. Mocking IS used for Category A+B validation (generating dummy params for the recursive `validate()` call), but not for input checking.

**Step 8 in `WorkflowValidator.validate()`, not inside `validate_workflow_templates()`.** Sub-workflow structural validation is a peer concern alongside data flow, node types, etc. — not a sub-concern of template validation. This keeps concerns cleanly separated at the cost of loading child IRs twice.

**Shared `_ir_cache` across recursion levels.** Initially `ir_cache` was local to each `_validate_sub_workflows()` call. Code review found a gap: when grandchild was validated during child recursion (level 2), its IR was cached in level 2's `ir_cache`. Parent (level 1) referencing the same grandchild got `None` from its own `ir_cache` → input check skipped. Threading `_ir_cache` through `validate()` alongside `_seen` fixed this.

**`normalize_ir()` after `parse_markdown()`.** The markdown parser deliberately does NOT emit `ir_version` — all consumers must call `normalize_ir()`. This wasn't in the original plan. Discovered during test writing when every file-based child failed structural validation.

### Technical Debt

- **`_resolve_child_workflow_outputs()` still swallows all exceptions** (`except Exception: return None` at `template_validation/validator.py:518`). Step 8 now handles error reporting, so this isn't a problem in practice. But if step 8 were removed, sub-workflow errors would go back to being invisible. The function's purpose is output extraction for template validation, not error reporting — the swallowing is intentional for that purpose.

## Unexpected Discoveries

### The `inputs` Framework Key Leak

Task 161 added `inputs` as a framework-level param consumed by `TemplateAwareNodeWrapper`. But `inputs` wasn't in `WorkflowExecutor.RESERVED_PARAMS`, so `_extract_child_inputs()` passed it through to child workflows as a param named `"inputs"`. This was a pre-existing runtime bug, not visible in any test because no existing workflow uses `inputs` on a workflow node.

### The "Required" Heuristic Conflict

`_validate_child_params()` used `"default" not in input_spec` to determine if an input was required. Every other consumer (10+ locations) used `input_spec.get("required", True)`. These disagreed on `{required: false}` without a default: `_validate_child_params` would reject it, `prepare_inputs` would accept it (providing `None`). Zero tests covered this case.

### `_pflow_workflow_file` Was Already Available

Initial research assumed we'd need to add a new parameter to `WorkflowValidator.validate()` for the workflow file path. Turns out `_pflow_workflow_file` was already in `extracted_params` for all execution paths — it just wasn't injected into the validate-only paths (dummy params). A 2-line fix in each of the 2 validate-only paths was all that was needed.

### Error Categorization

Deep research categorized all sub-workflow validation errors into:
- **Category A (~90%)**: Purely structural — parse errors, schema, data flow, node types. No runtime values needed.
- **Category B (~5%)**: Needs input key names — template path existence. Satisfied by dummy params.
- **Category C (~5%)**: Needs actual runtime values — type coercion, empty strings. Caught by lenient coercion (never raises). The one valuable Category C check (missing required inputs) works via static key comparison.

## Patterns Established

### Recursive Validation with Shared State

The `_seen` + `_ir_cache` pattern for recursive validation through `validate()`:
```python
@staticmethod
def validate(
    workflow_ir, extracted_params=None, registry=None,
    skip_node_types=False,
    _seen=None,        # Cycle detection — shared across all recursion levels
    _ir_cache=None,    # Child IR cache — shared so cross-nesting input checks work
):
```
Private `_` prefix signals internal use. `None` default means "create fresh on first call." External callers never pass these.

### Static Required-Input Checking

Param keys are always static in the IR (YAML parsing produces string keys, no template resolution on keys). This means you can check required inputs by comparing key sets:
```python
parent_keys = {k for k in params if k not in RESERVED_PARAMS and not k.startswith("__")}
for name, spec in child_inputs.items():
    if spec.get("required", True) and "default" not in spec and name not in parent_keys:
        # Missing required input
```

### `normalize_ir()` After `parse_markdown()`

Any new code path that loads a `.pflow.md` file and passes the result to `WorkflowValidator.validate()` MUST call `normalize_ir()` after `parse_markdown()`. The parser does not emit `ir_version` or `edges` — `normalize_ir()` adds them. Without it, structural validation fails with `'ir_version' is a required property`.

Existing pattern: `cli/workflow_resolution.py:79`, `core/workflow/save_service.py:102`.

## Anti-Patterns to Avoid

**Don't make `ir_cache` local again.** It was local initially and caused a correctness gap: cross-nesting references lost the cached IR. The `test_cross_nesting_reference_missing_input_caught` test guards this.

**Don't add framework keys without updating `RESERVED_PARAMS`.** If a new framework-level param is added (like `inputs` was in Task 161), it must be added to `WorkflowExecutor.RESERVED_PARAMS` AND to `framework_keys` in `_validate_unknown_params()`. Otherwise it leaks to child workflows and triggers unknown-param errors.

**Don't surface errors from `_resolve_child_workflow_outputs()`.** That function's purpose is output extraction for template validation. If it started surfacing errors, they'd duplicate with step 8's errors. Keep the two concerns separate.

## Testing Implementation

### Tests That Catch Real Bugs

- **`test_cross_nesting_reference_missing_input_caught`** — The `ir_cache` cross-nesting gap. Parent node A → child → grandchild (validated here), parent node B → grandchild with missing input. Would have caught the original local `ir_cache` design and the code review finding.
- **`test_broken_sub_workflow_caught_before_execution`** (E2E) — The value proposition. Parent with upstream LLM → broken child. Asserts zero LLM calls. This is the only test that proves the full CLI pipeline works end-to-end.
- **`test_second_reference_missing_input_still_caught`** — Two parent nodes referencing the same child. The second omits a required input. Caught the original `_seen` conflation issue during implementation.
- **`test_required_false_no_default_not_rejected`** — Verifies the harmonized heuristic. Would have caught the original `_validate_child_params()` bug.

### Tests That Are Coverage, Not Bug-Catchers

- `test_valid_sub_workflow_passes`, `test_template_workflow_ref_skipped` — Verify correct behavior but unlikely to catch regressions since they test the "do nothing" paths.

## Future Considerations

### Extension Points

- **Per-batch-item sub-workflow validation** — Currently, if `workflow: ${item.workflow}` is a template, it's skipped. If batch items contain literal workflow paths (e.g., `items: [{workflow: "./a.pflow.md"}, ...]`), those could be validated statically. Low value unless users hit this pattern.
- **Sub-workflow output type checking** — Step 8 validates the child's internal structure but doesn't check that the parent's template accesses on child outputs match the child's actual output types. `_resolve_child_workflow_outputs()` already loads child outputs for step 4. Deeper type checking could connect these.

### What Would Break If Modified Naively

1. **Making `ir_cache` local again** → cross-nesting input checks silently skipped (guarded by test)
2. **Removing `normalize_ir()` call** → every file-based child fails structural validation
3. **Adding a framework key without RESERVED_PARAMS** → leaks to children at runtime
4. **Removing step 8 without fixing `_resolve_child_workflow_outputs()`** → sub-workflow errors go back to being invisible (swallowed by `except Exception: return None`)

## AI Agent Guidance

### Quick Start for Related Tasks

Read these files in order:
1. `src/pflow/core/workflow/validator.py` lines 527-714 — the 3 new methods (the core of this task)
2. `src/pflow/runtime/workflow_executor.py` lines 54-62 — `RESERVED_PARAMS` (what keys are filtered)
3. `src/pflow/runtime/template_validation/validator.py` lines 471-532 — `_resolve_child_workflow_outputs()` (the OTHER place that loads child IRs, for template validation)
4. `tests/test_core/test_sub_workflow_validation.py` — all 14 tests show how validation is called

### Common Pitfalls

1. `parse_markdown()` does NOT produce a ready-to-validate IR. You MUST call `normalize_ir()` before passing to `WorkflowValidator.validate()`.
2. `_resolve_child_workflow_outputs()` swallows all errors. If you need error reporting from child workflow loading, use step 8's `_load_child_from_file()` pattern instead.
3. The `"required"` heuristic is `input_spec.get("required", True)` everywhere. Do not use `"default" not in input_spec` as a proxy — they disagree on `{required: false}` without a default.
4. `_pflow_workflow_file` must be in `extracted_params` for relative sub-workflow path resolution to work. If you add a new validation entry point, inject it.

---

*Generated from implementation context of Task 136, 2026-03-27*
