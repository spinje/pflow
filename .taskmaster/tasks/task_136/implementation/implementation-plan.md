# Plan: Fix Sub-Workflow Validation Errors Not Caught at Parse Time

## Context

When a workflow references a sub-workflow that has a validation error (e.g., missing step description), pflow only discovers the error at execution time — after running all upstream nodes. In real pipelines, this wastes minutes and dollars on LLM calls. The root cause: the 7-step validation pipeline in `WorkflowValidator.validate()` explicitly skips `type: workflow` nodes (`validator.py:205`), and sub-workflow files are only loaded inside `WorkflowExecutor.prep()/exec()` at runtime.

The template validation path (`_resolve_child_workflow_outputs()` in `template_validation/validator.py:471-532`) already loads and parses sub-workflow files during validation — but wraps everything in `except Exception: return None`, silently discarding parse errors like missing descriptions.

### What this fix does

1. Adds recursive sub-workflow validation as step 8 in `WorkflowValidator.validate()`
2. Fixes `inputs` framework key leaking into child workflows at runtime
3. Harmonizes the "required input" heuristic across the codebase
4. Threads `_pflow_workflow_file` into validate-only paths for correct relative path resolution

### Reproduction files

- `scratchpads/sub-workflow-validation-bug/parent-workflow.pflow.md` — upstream LLM then broken sub-workflow batch
- `scratchpads/sub-workflow-validation-bug/broken-sub-workflow.pflow.md` — missing description on `process` step

---

## Change 1: Add `inputs` to `RESERVED_PARAMS`

**File:** `src/pflow/runtime/workflow_executor.py`

**Line 55-62:** Add `"inputs"` to the `RESERVED_PARAMS` frozenset:

```python
RESERVED_PARAMS = frozenset({
    "workflow",
    "workflow_ir",
    "storage_mode",
    "max_depth",
    "error_action",
    "__registry__",
    "inputs",  # Framework key consumed by template wrapper, not a child input
})
```

**Why:** The `inputs` key (Task 161) is a framework-level param consumed by `TemplateAwareNodeWrapper` for template context enrichment. It's NOT in `RESERVED_PARAMS`, so `_extract_child_inputs()` (line 265-271) passes it through as a child input named `"inputs"`. This pollutes the child's execution context and would also break our static key comparison in Change 3.

**Safety:** `RESERVED_PARAMS` has exactly one consumer: `_extract_child_inputs()` at line 265-271. No existing workflow passes `"inputs"` as a sub-workflow child input. Code nodes (which use `inputs` extensively) go through a completely different execution path.

---

## Change 2: Harmonize "required input" heuristic

### 2a. Fix `_validate_child_params()`

**File:** `src/pflow/runtime/workflow_executor.py`
**Lines 378-380:** Change from:

```python
has_default = "default" in input_spec
if not has_default and input_name not in child_params:
```

To:

```python
is_required = input_spec.get("required", True)
has_default = "default" in input_spec
if is_required and not has_default and input_name not in child_params:
```

**Why:** This is the only consumer that ignores the `required` field entirely. All other 10+ consumers use `input_spec.get("required", True)`. The IR schema (`ir_schema.py:269`) declares `required` as boolean with default `True`. A user who writes `required: false` with no default means "this is optional, give me None" — the current code falsely rejects this in sub-workflow calls.

### 2b. Fix `context.py` display bug

**File:** `src/pflow/core/workflow/context.py`
**Line 144:** Change `.get("required", False)` to `.get("required", True)` — matches schema default. Same on line 145.

### 2c. Fix `discovery_formatter.py` display bug

**File:** `src/pflow/execution/formatters/discovery_formatter.py`
**Line 162:** Change `spec.get("required")` to `spec.get("required", True)` — bare `.get()` returns `None` (falsy), making inputs without explicit `required` field show as "optional".

### 2d. Fix `cli/commands/mcp.py` display bug

**File:** `src/pflow/cli/commands/mcp.py`
**Line 612:** Change `param.get("required")` to `param.get("required", True)`.

---

## Change 3: Recursive sub-workflow validation (main fix)

### 3a. Add `_seen` parameter to `WorkflowValidator.validate()`

**File:** `src/pflow/core/workflow/validator.py`
**Line 24-30:** Add private `_seen` parameter for cycle detection during recursive validation:

```python
@staticmethod
def validate(
    workflow_ir: dict[str, Any],
    extracted_params: Optional[dict[str, Any]] = None,
    registry: Optional[Registry] = None,
    skip_node_types: bool = False,
    _seen: Optional[set[str]] = None,
) -> tuple[list[str], list[ValidationWarning]]:
```

This is backward-compatible — no external caller needs to change.

### 3b. Add step 8 call in `validate()`

**File:** `src/pflow/core/workflow/validator.py`
**After line 94** (after step 7, before the logging), add:

```python
# 8. Sub-workflow validation (recursive)
sub_errors = WorkflowValidator._validate_sub_workflows(
    workflow_ir, extracted_params, registry, _seen
)
errors.extend(sub_errors)
```

### 3c. Implement `_validate_sub_workflows()`

**File:** `src/pflow/core/workflow/validator.py`
**New static method** on `WorkflowValidator`. This is the core of the fix.

**Logic:**

1. Iterate over `workflow_ir["nodes"]`, find nodes where `type` is `"workflow"` or `"pflow.runtime.workflow_executor"`.

2. For each workflow node, determine the child workflow reference:
   - If `params.get("workflow_ir")` is a dict → inline IR, use directly
   - If `params.get("workflow")` is a string:
     - Skip if contains `${` (template ref, can't resolve statically)
     - If `is_workflow_file_reference(ref)` → resolve path relative to parent using `extracted_params.get("_pflow_workflow_file")`, fall back to `Path.cwd()`. Read file, call `parse_markdown()`.
     - Else → saved name, load via `WorkflowManager().load_ir()`
   - If neither → skip (no workflow reference)

3. **Cycle detection:** Use `_seen` set of resolved absolute path strings (for file refs) or `"name:<workflow_name>"` strings (for saved names). If already in `seen`, skip with no error (cycles are caught by data flow validation or runtime stack check). For inline `workflow_ir`, no cycle detection needed (can't be self-referencing).

4. **Parse error handling:** If `parse_markdown()` raises `MarkdownParseError`, convert to a validation error: `f"In sub-workflow '{ref}' (step '{node_id}'): {error_message}"`. This is the exact error from the reproduction case.

5. **Full validation:** Generate dummy params from child's declared inputs using `generate_dummy_parameters(child_ir.get("inputs", {}))`. Also inject `_pflow_workflow_file` pointing to the child's file path (so the child's own sub-workflow references can resolve). Call `WorkflowValidator.validate(child_ir, dummy_params, registry, _seen=seen)` recursively. Prefix each returned error with context: `f"In sub-workflow '{ref}' (step '{node_id}'): {error}"`.

6. **Static required-input check:** Compute parent-provided keys:
   ```python
   from pflow.runtime.workflow_executor import WorkflowExecutor
   parent_keys = {
       k for k in node.get("params", {})
       if k not in WorkflowExecutor.RESERVED_PARAMS and not k.startswith("__")
   }
   ```
   Compare against child's required inputs (using harmonized heuristic):
   ```python
   child_inputs = child_ir.get("inputs", {})
   for name, spec in child_inputs.items():
       is_required = spec.get("required", True)
       has_default = "default" in spec
       if is_required and not has_default and name not in parent_keys:
           errors.append(f"Step '{node_id}': sub-workflow '{ref}' requires input '{name}' but it is not provided")
   ```

**Imports needed** (lazy, inside the method):
- `from pathlib import Path`
- `from pflow.core.markdown_parser import MarkdownParseError, parse_markdown`
- `from pflow.core.file_resolver import is_workflow_file_reference`
- `from pflow.core.validation_utils import generate_dummy_parameters`
- `from pflow.runtime.workflow_executor import WorkflowExecutor`
- `from pflow.core.workflow.manager import WorkflowManager`

**Error handling:** Wrap file I/O and `WorkflowManager.load_ir()` in try/except. If a child can't be loaded (file not found, permission error, etc.), produce a validation error — do NOT silently skip. Template refs (`${var}` in workflow path) are the only case that's silently skipped.

**Key files to reference for implementation patterns:**
- `src/pflow/core/workflow/dependency_discovery.py:80-117` — recursion with cycle detection via `seen` set
- `src/pflow/runtime/template_validation/validator.py:471-532` — `_resolve_child_workflow_outputs()` for file/name/inline resolution logic
- `src/pflow/runtime/workflow_executor.py:55-62` — `RESERVED_PARAMS` for key filtering
- `src/pflow/core/validation_utils.py:6-29` — `generate_dummy_parameters()`

---

## Change 4: Thread `_pflow_workflow_file` into validate-only paths

### 4a. CLI `_perform_validation()`

**File:** `src/pflow/cli/main.py`
**Lines 508-553:** The function signature currently takes `(ir_data, output_format)`. It needs access to the source file path for sub-workflow resolution.

**Option:** Add `source_file_path: Optional[str] = None` parameter. When provided, inject `_pflow_workflow_file` into the dummy params dict before calling `WorkflowValidator.validate()`.

The caller `_handle_validate_only_mode()` (line 601-630) has access to `ctx.obj["source_file_path"]` and should pass it:

```python
# In _handle_validate_only_mode():
source_file_path = ctx.obj.get("source_file_path")
errors, warnings = _perform_validation(ir_data, output_format, source_file_path=source_file_path)
```

```python
# In _perform_validation():
if source_file_path:
    dummy_params["_pflow_workflow_file"] = str(Path(source_file_path).resolve())
```

### 4b. MCP `validate_workflow()`

**File:** `src/pflow/mcp_server/services/execution_service.py`
**Lines 382-397:** After generating dummy params (line 384), inject `_pflow_workflow_file` when the source is file or library:

```python
dummy_params = generate_dummy_parameters(inputs)

# Inject file path for sub-workflow resolution
if source == "file":
    dummy_params["_pflow_workflow_file"] = str(Path(str(workflow)).resolve())
elif source == "library":
    wm = WorkflowManager()
    dummy_params["_pflow_workflow_file"] = wm.get_path(str(workflow))
```

This also fixes a pre-existing bug where `_resolve_child_workflow_outputs()` falls back to `Path.cwd()` for relative sub-workflow paths during MCP validation.

---

## Tests

### Test file: `tests/test_core/test_sub_workflow_validation.py` (NEW)

This is the main test file for the new step 8 validation.

**Tests to write:**

1. **`test_broken_sub_workflow_caught_at_validation_time`** — The reproduction case. Create parent workflow referencing a child with missing description. Validate parent. Expect error containing "missing a description" and "In sub-workflow".

2. **`test_valid_sub_workflow_passes_validation`** — Parent references valid child. Validate. No errors.

3. **`test_nested_sub_workflow_validation`** — Parent → middle → broken child (3 levels). Expect error with chained prefix showing the full nesting path.

4. **`test_circular_sub_workflow_reference_no_infinite_loop`** — Workflow A references B, B references A. Validation terminates without error (cycles handled gracefully via `_seen`).

5. **`test_missing_required_input_detected`** — Parent passes `text` but child requires `text` and `count`. Expect error about missing `count`.

6. **`test_template_workflow_ref_skipped`** — Workflow node with `workflow: ${dynamic_path}`. No error (gracefully skipped).

7. **`test_inline_workflow_ir_validated`** — Workflow node with `workflow_ir` dict containing a broken child. Expect validation error.

8. **`test_saved_workflow_name_validated`** — Use `WorkflowManager` to save a broken workflow, then validate parent referencing it by name. Expect validation error.

9. **`test_sub_workflow_unknown_node_type_caught`** — Child has `type: nonexistent`. Expect error about unknown node type.

10. **`test_sub_workflow_data_flow_error_caught`** — Child has circular dependency. Expect error.

11. **`test_required_false_input_not_flagged`** — Child declares `required: false` without default. Parent doesn't provide it. No error (harmonized heuristic).

**Fixture pattern:** Use `tmp_path` for file-based tests. Write child `.pflow.md` files as raw markdown strings to `tmp_path`. Build parent IR dicts inline referencing child files via absolute paths. Call `WorkflowValidator.validate()` with dummy params containing `_pflow_workflow_file`.

### Test file: `tests/test_runtime/test_workflow_executor/test_reserved_params.py` (NEW or extend existing)

12. **`test_inputs_not_passed_as_child_input`** — Verify `_extract_child_inputs()` excludes `"inputs"` after adding it to `RESERVED_PARAMS`.

### Test file: `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` (EXTEND)

13. **`test_required_false_no_default_not_rejected`** — Child input with `required: false`, no default, parent doesn't provide it. `_validate_child_params` should NOT raise.

### Changes to existing tests

- **`tests/test_core/test_workflow_validator.py`** — Verify existing tests still pass. The new `_seen` parameter is optional with default `None`, so existing calls are backward-compatible.

---

## Verification

### Manual testing with reproduction files

```bash
cd /path/to/pflow
# Should fail INSTANTLY with validation error (0 LLM calls, $0 cost):
uv run pflow scratchpads/sub-workflow-validation-bug/parent-workflow.pflow.md items='["hello", "world"]' --no-cache

# Should also fail instantly (deeply nested):
uv run pflow scratchpads/sub-workflow-validation-bug/deep-parent-workflow.pflow.md items='["hello", "world"]' --no-cache

# Validate-only should also catch it:
uv run pflow --validate-only scratchpads/sub-workflow-validation-bug/parent-workflow.pflow.md
```

Expected: Validation error mentioning "missing a description" with sub-workflow context. Zero LLM calls. Instant failure.

### Automated testing

```bash
make test    # Full test suite
make check   # Lint + type checks
```

---

## Files Modified Summary

| File | Change |
|------|--------|
| `src/pflow/core/workflow/validator.py` | Add `_seen` param, step 8 `_validate_sub_workflows()` |
| `src/pflow/runtime/workflow_executor.py` | Add `"inputs"` to `RESERVED_PARAMS`, fix `_validate_child_params` heuristic |
| `src/pflow/cli/main.py` | Inject `_pflow_workflow_file` in `_perform_validation()`, update `_handle_validate_only_mode()` |
| `src/pflow/mcp_server/services/execution_service.py` | Inject `_pflow_workflow_file` in `validate_workflow()` |
| `src/pflow/core/workflow/context.py` | Fix `.get("required", False)` → `.get("required", True)` |
| `src/pflow/execution/formatters/discovery_formatter.py` | Fix `.get("required")` → `.get("required", True)` |
| `src/pflow/cli/commands/mcp.py` | Fix `.get("required")` → `.get("required", True)` |
| `tests/test_core/test_sub_workflow_validation.py` | **NEW** — 11 tests for recursive sub-workflow validation |
| `tests/test_runtime/test_workflow_executor/...` | 2 new tests for RESERVED_PARAMS and required heuristic |

## Implementation Order

1. **Change 1** (RESERVED_PARAMS) — standalone, no dependencies
2. **Change 2** (required heuristic) — standalone, no dependencies
3. **Change 3** (recursive validation) — the main fix, depends on Changes 1-2 for correct key filtering and required-input checking
4. **Change 4** (validate-only paths) — depends on Change 3 existing
5. **Tests** — after all changes, can be written alongside

Changes 1 and 2 can be implemented in parallel. Change 3 is the largest piece. Change 4 is small.
