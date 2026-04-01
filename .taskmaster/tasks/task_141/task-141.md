# Task 141: Consolidate Exception Hierarchy Under PflowError

## Description

Move orphaned exception classes into `core/exceptions.py`, rebase them onto `PflowError`, rename `ValidationError` to `SchemaValidationError` to eliminate name collisions, and clean up the resulting lazy imports across the codebase. Also fixes a pre-existing ValueError miscategorization bug in the runner's error handler.

## Status

not started

## Priority

medium

## Problem

The codebase has four independent exception inheritance trees:

```
PflowError(Exception)           <- 7 subclasses, in core/exceptions.py
UserFriendlyError(Exception)    <- 2 subclasses, in core/user_errors.py
ValidationError(Exception)      <- in core/ir_schema.py (700-line schema module)
MarkdownParseError(ValueError)  <- in core/markdown_parser.py (700-line parser)
```

This causes:
1. **18+ lazy imports** because two exceptions live in heavy modules that trigger circular imports
2. **A duck-type hack** in `runner.py:545`: `type(exception).__name__ == "ValidationError" and hasattr(exception, "path")` — avoids importing from the heavy module, but incorrectly matches pydantic's `ValidationError` (which also has `.path`)
3. **Three different aliases** for the same class: `SchemaValidationError`, `IrSchemaValidationError`, `IRValidationError` at different import sites
4. **No catch-all** — can't write `except PflowError` to handle all pflow-specific errors
5. **`MarkdownParseError(ValueError)`** was a migration hack (docstring: "so existing `except ValueError` catches still work") — almost every catch site already catches `MarkdownParseError` by name, with one exception: `save_service.py:311` has `except (FileNotFoundError, ValueError)` that catches `MarkdownParseError` through its `ValueError` inheritance

Additionally, `runner.py:541` miscategorizes ALL ValueErrors as `category: "validation"`, including node execution errors (HTTP timeouts, GitHub API failures, git errors) that should be `category: "execution_failure"`.

## Solution

### Phase 1: Move + rebase + rename

Move `ValidationError` and `MarkdownParseError` to `core/exceptions.py`. Rebase both onto `PflowError`. Rename `ValidationError` to `SchemaValidationError`. Leave one-line re-exports in original files.

### Phase 2: Rebase UserFriendlyError

Change `class UserFriendlyError(Exception)` to `class UserFriendlyError(PflowError)` in `user_errors.py`. Add `from pflow.core.exceptions import PflowError`. File stays in `user_errors.py` (different concern — structured WHAT/WHY/HOW formatting with `format_for_cli()`).

### Phase 3: Fix all import sites

Convert lazy imports to module-level. Fix the duck-type hack. Eliminate aliases. Fix the one breaking test. Clean up CompilationError lazy imports in compilation/ siblings.

### Phase 4: Fix ValueError miscategorization

Use `_pflow_node_id` annotation as discriminator in `_exception_to_result`: ValueErrors WITH `_pflow_node_id` came from node execution (category: `execution_failure`), without it came from pre-execution (category: `validation`).

## Design Decisions

- **Rename `ValidationError` to `SchemaValidationError`**: Eliminates name collision with pydantic's and jsonschema's `ValidationError`. Makes distinction with `WorkflowValidationError` self-documenting (schema-level vs. aggregated workflow-level). The name is already used as a local alias in `validator.py`. Verified no collision in any dependency.

- **Rebase `MarkdownParseError` off `PflowError`, not keep `ValueError`**: The `ValueError` inheritance was an explicit migration hack. Almost every production catch site already catches `MarkdownParseError` by name. One `except ValueError` in `save_service.py:_discover_and_bundle_deps` (line 311) incidentally catches `MarkdownParseError` through inheritance — must add `MarkdownParseError` to that except tuple. One test (`test_workflow_executor_comprehensive.py:226`) uses `pytest.raises(ValueError)` to catch it — trivial fix.

- **Rebase `UserFriendlyError` onto `PflowError` but keep it in `user_errors.py`**: The class has a `format_for_cli()` method with structured WHAT/WHY/HOW formatting — a different concern from the simple data-carrying exceptions in `exceptions.py`. Zero `isinstance(_, PflowError)` checks exist in the codebase, so the rebase changes zero behavior. No circular import risk (`user_errors.py` currently imports only from `typing`; adding `PflowError` is a one-way dependency).

- **Leave `CycleError` and `NonRetriableError` where they are**: `CycleError` has zero external production imports (module-internal to `data_flow.py`). `NonRetriableError` is package-local to `nodes/file/` with 0% lazy imports. Neither benefits from consolidation.

- **Leave `MaxNodeVisitsError(RuntimeError)` separate**: Intentionally not a `PflowError` — it's a runtime guard (infinite loop detection) that should propagate differently from domain errors.

- **Fix ValueError miscategorization as companion fix**: The `_pflow_node_id` annotation is set by the engine (line 307) and the runner's `_compile_and_execute` (line 200). Pre-execution ValueErrors never have it. This is a reliable discriminator that requires ~3 lines to implement. Scoped in because it's directly exposed by reading this code path during the hierarchy work.

## Dependencies

None. `core/exceptions.py` is a leaf module with only `typing` imports.

## Requirements

### Hierarchy

- All pflow-specific exceptions (except `MaxNodeVisitsError`) inherit from `PflowError`
- `SchemaValidationError(PflowError)` in `core/exceptions.py` with attrs: `message`, `path`, `suggestion`
- `MarkdownParseError(PflowError)` in `core/exceptions.py` with attrs: `line`, `suggestion`
- `UserFriendlyError(PflowError)` in `core/user_errors.py` (file unchanged except base class + import)
- Re-exports in original files: `ir_schema.py` re-exports `SchemaValidationError` (aliased as `ValidationError` for the re-export), `markdown_parser.py` re-exports `MarkdownParseError`

### Imports

- Zero lazy imports of `SchemaValidationError`, `MarkdownParseError`, or `CompilationError` from heavy modules (ir_schema, markdown_parser, compiler)
- All import sites use `from pflow.core.exceptions import ClassName` (canonical path)
- No aliases — `SchemaValidationError` everywhere, not `IrSchemaValidationError` or `IRValidationError`
- The duck-type hack at `runner.py:545` replaced with proper `isinstance(exception, SchemaValidationError)`
- CompilationError lazy imports in `compilation/` siblings (`compile_validation.py`, `mcp_resolution.py`, `node_loader.py`, `ir_preparation.py`) converted to module-level from `pflow.core.exceptions`
- Redundant lazy import in `batch_executor.py:419` removed (module-level import already at line 19)
- Redundant lazy import of `WorkflowValidationError` in `runner.py:359` removed (now at module-level)

### Error categorization fix

- In `runner.py:_exception_to_result`, ValueErrors with `_pflow_node_id` annotation categorized as `execution_failure` (not `validation`)
- ValueErrors without `_pflow_node_id` annotation remain categorized as `validation`
- `MarkdownParseError` handled by its own explicit branch (not lumped with `ValueError`), conditionally preserving `.line` and `.suggestion` attrs in the error dict (only when non-None, to avoid writing null values into JSON output)
- `MarkdownParseError` branch preserves `annotated_node_id` when present (nested workflow scenarios where engine annotates parse errors with the failing workflow node's ID)
- `save_service.py:_discover_and_bundle_deps` (line 311): `MarkdownParseError` added to `except (FileNotFoundError, ValueError)` tuple to prevent fallthrough to misleading "If this is a bug" error message

### Test updates

- `test_workflow_executor_comprehensive.py:226`: `pytest.raises(ValueError)` changed to `pytest.raises(MarkdownParseError)`
- No other test changes required for the rebase (verified by exhaustive search)
- New test: verify `except PflowError` catches `SchemaValidationError`, `MarkdownParseError`, `CompilationError`, `UserFriendlyError` (and subclasses)
- Regression tests for `_exception_to_result` behavioral changes:
  - `ValueError` with `_pflow_node_id` annotation produces `category: "execution_failure"` + `node_id`
  - `ValueError` without `_pflow_node_id` produces `category: "validation"` (no `node_id`)
  - `SchemaValidationError` preserves `path` and `suggestion` in error dict (replaces duck-type hack)
  - `MarkdownParseError` extracts `.line` and `.suggestion` into error dict (only when non-None)
  - `MarkdownParseError` with no `.line`/`.suggestion` omits those fields (not `None` values)

## Implementation Notes

### Target hierarchy after completion

```
PflowError(Exception)                    <- core/exceptions.py
├── SchemaValidationError                <- core/exceptions.py (moved + renamed from ir_schema.py)
├── WorkflowValidationError              <- core/exceptions.py (unchanged)
├── CompilationError                     <- core/exceptions.py (already here from Task 135)
├── MarkdownParseError                   <- core/exceptions.py (moved from markdown_parser.py)
├── WorkflowNotFoundError                <- core/exceptions.py (unchanged)
├── WorkflowExistsError                  <- core/exceptions.py (unchanged)
├── CriticalDiscoveryError               <- core/exceptions.py (unchanged)
├── UserFriendlyError                    <- core/user_errors.py (rebased from Exception)
│   ├── MCPError                         <- core/user_errors.py (unchanged)
│   └── OutputResolutionError            <- core/user_errors.py (unchanged)
MaxNodeVisitsError(RuntimeError)         <- core/exceptions.py (intentionally separate)
CycleError(Exception)                    <- core/workflow/data_flow.py (module-internal, leave as-is)
NonRetriableError(Exception)             <- nodes/file/exceptions.py (package-local, leave as-is)
```

### Import site inventory (production code)

**SchemaValidationError** (currently `ValidationError`):
- `core/__init__.py:9` — re-export (update name)
- `runtime/compilation/compile_validation.py:11` — module-level (update import path + name)
- `core/workflow/validator.py:126` — lazy, aliased as `SchemaValidationError` (convert to module-level, drop alias)
- `cli/error_output.py:156` — lazy, aliased as `IrSchemaValidationError` (convert to module-level, rename)
- `execution/runner.py:297` — lazy, aliased as `IRValidationError` (convert to module-level, rename)
- `execution/runner.py:545` — duck-type hack (replace with isinstance)

**MarkdownParseError**:
- `core/workflow/manager.py:26` — module-level (update import path)
- `core/workflow/save_service.py:14` — module-level (update import path)
- `core/workflow/save_service.py:311` — `except (FileNotFoundError, ValueError)` catches `MarkdownParseError` through inheritance (add `MarkdownParseError` to tuple)
- `core/workflow/dependency_discovery.py:16` — module-level (update import path)
- `cli/error_output.py:157` — lazy (convert to module-level, update path)
- `cli/error_output.py:274` — lazy (convert to module-level, update path)
- `cli/commands/workflow.py:239` — lazy (convert to module-level, update path)
- `core/workflow/validator.py:684` — lazy (convert to module-level, update path)
- `mcp_server/services/execution_service.py:302` — lazy (convert to module-level, update path)
- `execution/runner.py:298` — lazy (convert to module-level, update path)
- `execution/runner.py:491` — lazy (convert to module-level, update path)

**CompilationError** (already in `core/exceptions.py`, cleaning up stale import paths):
- `runtime/compilation/compile_validation.py:81,150` — 2 lazy imports from `.compiler` (convert to module-level from `core.exceptions`)
- `runtime/compilation/mcp_resolution.py:114` — lazy from `.compiler` (convert)
- `runtime/compilation/node_loader.py:40` — lazy from `.compiler` (convert)
- `runtime/compilation/ir_preparation.py:189` — lazy from `.compiler` (convert)
- `runtime/engine/batch_executor.py:419` — redundant lazy (remove, line 19 already has module-level)
- `runtime/engine/engine.py:59,79` — 2 lazy from `core.exceptions` (convert to module-level)
- `execution/runner.py:299,328,492` — 3 lazy from `pflow.runtime` (convert to `core.exceptions`, module-level)
- `execution/runner.py:359` — lazy `WorkflowValidationError` (redundant after module-level import, remove)

### Edge case: `compile_validation.py` passes CompilationError as parameter

`compile_validation.py:102` — `_validate_data_flow_at_compile_time` receives `CompilationError` as a function parameter (passed at line 160). This exists to avoid a second lazy import inside that function. After converting to module-level, the parameter can be removed and the function can import directly.

### runner.py `_exception_to_result` changes

Current (line 541):
```python
elif isinstance(exception, (MarkdownParseError, ValueError)):
    error_dict.update({"category": "validation"})
    if annotated_node_id:
        error_dict["node_id"] = annotated_node_id
```

After:
```python
elif isinstance(exception, SchemaValidationError):
    error_dict.update({
        "source": "validation",
        "category": "validation",
    })
    if exception.path:
        error_dict["path"] = exception.path
    if exception.suggestion:
        error_dict["suggestion"] = exception.suggestion
elif isinstance(exception, MarkdownParseError):
    error_dict.update({"category": "validation"})
    if exception.line is not None:
        error_dict["line"] = exception.line
    if exception.suggestion:
        error_dict["suggestion"] = exception.suggestion
    if annotated_node_id:
        error_dict["node_id"] = annotated_node_id
elif isinstance(exception, ValueError):
    if annotated_node_id:
        error_dict.update({
            "category": "execution_failure",
            "node_id": annotated_node_id,
        })
    else:
        error_dict.update({"category": "validation"})
```

### runner.py `validate()` method (line 282)

Currently catches `ValueError` which includes `MarkdownParseError`. After rebase, `MarkdownParseError` falls through to the `except Exception` block at line 294 which explicitly checks `isinstance(e, MarkdownParseError)` and returns the same `ValidationResult`. Same behavior, different code path. Add `MarkdownParseError` and `SchemaValidationError` to the first except tuple for explicitness, then simplify the second except block (remove lazy imports, keep only `WorkflowValidationError` and `CompilationError`).

## Verification

- `make test` passes (4,630+ tests)
- `make check` passes (ruff, mypy)
- Zero lazy imports of `SchemaValidationError`, `MarkdownParseError` remain in `src/pflow/`
- Zero lazy imports of `CompilationError` from `compiler.py` or `pflow.runtime` remain in `src/pflow/`
- `grep -r 'type(exception).__name__ == "ValidationError"' src/pflow/` returns zero matches (duck-type hack eliminated)
- `except PflowError` catches all pflow-specific exceptions (verified by new test)
- Node execution ValueErrors (with `_pflow_node_id`) produce `category: "execution_failure"` in error output
- Pre-execution ValueErrors (without `_pflow_node_id`) produce `category: "validation"` in error output

## References

- GitHub issue: #185 (Consolidate exception classes into core/exceptions.py)
- Current exceptions: `src/pflow/core/exceptions.py` (153 lines, 7 classes)
- Current user errors: `src/pflow/core/user_errors.py` (144 lines, 3 classes)
- ValidationError definition: `src/pflow/core/ir_schema.py:75-114`
- MarkdownParseError definition: `src/pflow/core/markdown_parser.py:31-53`
- Duck-type hack: `src/pflow/execution/runner.py:545`
- ValueError miscategorization: `src/pflow/execution/runner.py:541-544`
- Error dispatch chain: `src/pflow/cli/error_output.py:142-189`
- Architectural debt catalog: `scratchpads/architectural-debt/compounding-issues.md` (Issue 7)
- Task 135 review (CompilationError move precedent): `.taskmaster/tasks/task_135/task-review.md`
