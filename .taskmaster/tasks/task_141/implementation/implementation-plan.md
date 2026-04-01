# Task 141: Consolidate Exception Hierarchy Under PflowError

## Context

pflow has four independent exception inheritance trees scattered across heavy modules (`ir_schema.py`, `markdown_parser.py`, `user_errors.py`, `exceptions.py`). This causes 21+ lazy imports (circular dependency workarounds), 3 different aliases for the same class, a duck-type hack (`type(exception).__name__ == "ValidationError"`), and no ability to write `except PflowError` as a catch-all. A companion bug miscategorizes node execution ValueErrors (HTTP timeouts, GitHub API failures) as `category: "validation"` instead of `category: "execution_failure"`.

**Goal**: One rooted hierarchy, zero lazy exception imports, zero aliases, zero duck-typing, fixed ValueError categorization.

**Target hierarchy after completion**:
```
PflowError(Exception)                    <- core/exceptions.py
  |- SchemaValidationError               <- core/exceptions.py (moved+renamed from ir_schema.py)
  |- WorkflowValidationError             <- core/exceptions.py (unchanged)
  |- CompilationError                    <- core/exceptions.py (unchanged)
  |- MarkdownParseError                  <- core/exceptions.py (moved from markdown_parser.py)
  |- WorkflowNotFoundError               <- core/exceptions.py (unchanged)
  |- WorkflowExistsError                 <- core/exceptions.py (unchanged)
  |- CriticalDiscoveryError              <- core/exceptions.py (unchanged)
  |- UserFriendlyError                   <- core/user_errors.py (rebased from Exception)
  |   |- MCPError                        <- core/user_errors.py (unchanged)
  |   |- OutputResolutionError           <- core/user_errors.py (unchanged)
MaxNodeVisitsError(RuntimeError)         <- core/exceptions.py (intentionally separate)
CycleError(Exception)                    <- core/workflow/data_flow.py (module-internal, leave as-is)
NonRetriableError(Exception)             <- nodes/file/exceptions.py (package-local, leave as-is)
```

**Verification after each phase**: `make test && make check`

---

## Phase 1: Move + Rebase + Rename

### 1.1 Add `SchemaValidationError` and `MarkdownParseError` to `core/exceptions.py`

**File**: `src/pflow/core/exceptions.py`

Add these two classes BEFORE the existing `CompilationError` class (after `CriticalDiscoveryError`, before `CompilationError`). Both inherit from `PflowError`.

**Add `SchemaValidationError`** (adapted from `ir_schema.py:75-114`, renamed, rebased):

```python
class SchemaValidationError(PflowError):
    """Validation error for IR schema with helpful messages and field paths.

    Attributes:
        message: The validation error message
        path: Dotted path to the invalid field (e.g., "nodes[0].type")
        suggestion: Optional suggestion for fixing the error
    """

    def __init__(self, message: str, path: str = "", suggestion: str = ""):
        self.message = message
        self.path = path
        self.suggestion = suggestion

        full_message = "Validation error"
        if path:
            full_message += f" at {path}"
        full_message += f": {message}"
        if suggestion:
            full_message += f"\n{suggestion}"

        super().__init__(full_message)
```

**Add `MarkdownParseError`** (adapted from `markdown_parser.py:31-53`, rebased from `ValueError` to `PflowError`):

```python
class MarkdownParseError(PflowError):
    """Error raised when markdown workflow content cannot be parsed.

    Attributes:
        line: Source line number where the error occurred (1-based).
        suggestion: Optional human-readable fix suggestion.
    """

    def __init__(
        self,
        message: str,
        line: int | None = None,
        suggestion: str | None = None,
    ):
        self.line = line
        self.suggestion = suggestion
        prefix = f"Line {line}: " if line else ""
        full = f"{prefix}{message}"
        if suggestion:
            full += f"\n\n{suggestion}"
        super().__init__(full)
```

### 1.2 Add re-export in `ir_schema.py`

**File**: `src/pflow/core/ir_schema.py`

**Remove** the entire `ValidationError` class definition (lines 75-114).

**Add** in its place (single line):
```python
from pflow.core.exceptions import SchemaValidationError as ValidationError
```

This preserves backward compatibility for anything importing `ValidationError` from `ir_schema`.

### 1.3 Add re-export in `markdown_parser.py`

**File**: `src/pflow/core/markdown_parser.py`

**Remove** the entire `MarkdownParseError` class definition (lines 31-53, including the `# --- Exceptions ---` comment above it).

**Add** in its place:
```python
from pflow.core.exceptions import MarkdownParseError  # noqa: F401
```

The `# noqa: F401` is needed because ruff may flag it as an unused import (it's used by consumers that import from this module).

### 1.4 Verify Phase 1

Run `make test`. **Expect one test failure** — all other tests pass because re-exports preserve existing import paths:

- **Fails**: `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py::TestWorkflowExecutor::test_malformed_workflow` (line 226: `pytest.raises(ValueError)` no longer catches `MarkdownParseError` since it's rebased off `PflowError`). Fixed in Phase 5.
- **All other tests pass**: every other catch site already catches `MarkdownParseError` by name.

---

## Phase 2: Rebase UserFriendlyError

### 2.1 Change base class in `user_errors.py`

**File**: `src/pflow/core/user_errors.py`

**Add import** after existing imports (after line 7 `from typing import Any, Optional`):
```python
from pflow.core.exceptions import PflowError
```

**Change** line 10:
```python
# FROM:
class UserFriendlyError(Exception):
# TO:
class UserFriendlyError(PflowError):
```

### 2.2 Verify Phase 2

Run `make test && make check`. Zero behavior changes because no `isinstance(_, PflowError)` checks exist in the codebase (verified by research).

---

## Phase 3: Fix All Production Import Sites

This phase converts all lazy exception imports to module-level and eliminates aliases, duck-typing, and the `_is_markdown_parse_error` helper.

### 3.1 `src/pflow/core/__init__.py`

**Current** (line 9):
```python
from .ir_schema import FLOW_IR_SCHEMA, ValidationError, normalize_ir, validate_ir
```

**Replace with**:
```python
from .exceptions import SchemaValidationError
from .ir_schema import FLOW_IR_SCHEMA, normalize_ir, validate_ir
```

**Current `__all__`** (lines 12-18):
```python
__all__ = [
    "FLOW_IR_SCHEMA",
    "StdinData",
    "ValidationError",
    "normalize_ir",
    "validate_ir",
]
```

**Replace `"ValidationError"` with `"SchemaValidationError"`**:
```python
__all__ = [
    "FLOW_IR_SCHEMA",
    "SchemaValidationError",
    "StdinData",
    "normalize_ir",
    "validate_ir",
]
```

### 3.2 `src/pflow/runtime/compilation/compile_validation.py`

**Current module-level imports** (lines 8-17):
```python
import logging
from typing import Any

from pflow.core.ir_schema import ValidationError
from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name
from pflow.registry import Registry

from ..template_validation import extract_node_outputs
from .ir_preparation import prepare_inputs, validate_ir_structure
```

**Change** line 11 to import from canonical path with new name, AND add CompilationError:
```python
import logging
from typing import Any

from pflow.core.exceptions import CompilationError, SchemaValidationError
from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name
from pflow.registry import Registry

from ..template_validation import extract_node_outputs
from .ir_preparation import prepare_inputs, validate_ir_structure
```

Then update all references to `ValidationError` in this file to `SchemaValidationError`. Search for usage — it's used in isinstance checks and catch clauses within this file.

**Remove lazy import at line 81** (`from .compiler import CompilationError` inside `_get_template_resolution_mode`). The function body uses `CompilationError` directly — now resolved from module-level.

**Remove lazy import at line 150** (`from .compiler import CompilationError` inside `_prepare_compilation`). Same reason.

**Fix `_validate_data_flow_at_compile_time` signature** (line 102):

Current:
```python
def _validate_data_flow_at_compile_time(ir_dict: dict[str, Any], CompilationError: type) -> None:
```

Change to:
```python
def _validate_data_flow_at_compile_time(ir_dict: dict[str, Any]) -> None:
```

Remove the `CompilationError` parameter — the function now uses the module-level import directly.

**Update docstring** inside `_validate_data_flow_at_compile_time`: Remove the line:
```
        CompilationError: The CompilationError class (passed to avoid circular import)
```

**Fix call site at line 160**:

Current:
```python
    _validate_data_flow_at_compile_time(ir_dict, CompilationError)
```

Change to:
```python
    _validate_data_flow_at_compile_time(ir_dict)
```

### 3.3 `src/pflow/core/workflow/validator.py`

**Add module-level import** (near top, with other pflow imports):
```python
from pflow.core.exceptions import SchemaValidationError
```

**Line ~131** (inside `_validate_schema` staticmethod): Remove the lazy import:
```python
# REMOVE these two lines:
from pflow.core.ir_schema import ValidationError as SchemaValidationError
from pflow.core.ir_schema import validate_ir
```

Replace with just the non-exception import (keep lazy since validate_ir is a function, not an exception):
```python
from pflow.core.ir_schema import validate_ir
```

The `except SchemaValidationError` catch now uses the module-level import.

**Line ~691** (inside `_load_child_workflow` staticmethod): The lazy import is:
```python
from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
```

**Add `MarkdownParseError` to module-level imports**:
```python
from pflow.core.exceptions import MarkdownParseError, SchemaValidationError
```

**Change the lazy import** to only import parse_markdown:
```python
from pflow.core.markdown_parser import parse_markdown
```

### 3.4 `src/pflow/cli/error_output.py`

**Add module-level imports** (after existing `import click` around line 12):
```python
from pflow.core.exceptions import (
    MaxNodeVisitsError,
    MarkdownParseError,
    SchemaValidationError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from pflow.core.user_errors import MCPError, OutputResolutionError, UserFriendlyError
```

**In `_exception_to_errors` function (lines 142-189)**:

Remove the entire lazy import block (lines 151-158):
```python
    # REMOVE:
    from pflow.core.exceptions import (
        MaxNodeVisitsError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    )
    from pflow.core.ir_schema import ValidationError as IrSchemaValidationError
    from pflow.core.markdown_parser import MarkdownParseError
    from pflow.core.user_errors import MCPError, OutputResolutionError, UserFriendlyError
```

Change the isinstance check that uses `IrSchemaValidationError` (line ~182):
```python
# FROM:
    if isinstance(exception, IrSchemaValidationError):
        return _schema_validation_to_errors(exception)
# TO:
    if isinstance(exception, SchemaValidationError):
        return _schema_validation_to_errors(exception)
```

**Delete the `_is_markdown_parse_error` helper** (lines 272-276):
```python
# DELETE entirely:
def _is_markdown_parse_error(exception: Exception) -> bool:
    """Check if exception is a MarkdownParseError (avoids top-level import)."""
    from pflow.core.markdown_parser import MarkdownParseError

    return isinstance(exception, MarkdownParseError)
```

**In `display_exception_text` function (lines 279-305)**:

Remove the lazy import block:
```python
    # REMOVE:
    from pflow.core.exceptions import WorkflowNotFoundError, WorkflowValidationError
    from pflow.core.user_errors import UserFriendlyError
```

Replace the `_is_markdown_parse_error(exception)` call (line ~296) with `isinstance(exception, MarkdownParseError)`:
```python
# FROM:
    elif isinstance(exception, FileNotFoundError) or _is_markdown_parse_error(exception):
# TO:
    elif isinstance(exception, (FileNotFoundError, MarkdownParseError)):
```

### 3.5 `src/pflow/cli/commands/workflow.py`

**Line ~239** (inside `_load_and_display` or similar function): The lazy import is:
```python
    from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
```

**Add module-level import** near top of file:
```python
from pflow.core.exceptions import MarkdownParseError
```

**Change the lazy import** to only import `parse_markdown`:
```python
    from pflow.core.markdown_parser import parse_markdown
```

### 3.6 `src/pflow/execution/runner.py`

This is the most complex file. Multiple changes.

**Module-level imports** — current (lines 9-11):
```python
from pflow.core.exceptions import WorkflowNotFoundError
from pflow.core.workflow.manager import WorkflowManager
from pflow.core.workflow.status import WorkflowStatus
```

**Replace line 9** with expanded imports:
```python
from pflow.core.exceptions import (
    CompilationError,
    MarkdownParseError,
    MaxNodeVisitsError,
    SchemaValidationError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
```

**In `validate()` method — first except block (lines 284-295)**:

Current:
```python
        except (
            WorkflowNotFoundError,
            ValueError,
            PermissionError,
            FileNotFoundError,
        ) as e:
            # Expected validation-phase errors -> structured result
            return ValidationResult(
                valid=False,
                errors=[str(e)],
                warnings=[],
            )
```

Add `MarkdownParseError` and `SchemaValidationError`:
```python
        except (
            WorkflowNotFoundError,
            SchemaValidationError,
            MarkdownParseError,
            ValueError,
            PermissionError,
            FileNotFoundError,
        ) as e:
            # Expected validation-phase errors -> structured result
            return ValidationResult(
                valid=False,
                errors=[str(e)],
                warnings=[],
            )
```

**In `validate()` method — second except block (lines 296-311)**:

Current:
```python
        except Exception as e:
            # Check for pflow-specific exceptions via lazy imports to avoid circular deps
            from pflow.core.exceptions import WorkflowValidationError
            from pflow.core.ir_schema import ValidationError as IRValidationError
            from pflow.core.markdown_parser import MarkdownParseError
            from pflow.runtime import CompilationError

            if isinstance(e, (WorkflowValidationError, MarkdownParseError, CompilationError, IRValidationError)):
                return ValidationResult(
                    valid=False,
                    errors=[str(e)],
                    warnings=[],
                )
            # Unexpected errors (programming bugs) — let them propagate.
            # Callers (CLI, MCP) have their own exception handlers.
            raise
```

Replace with (no lazy imports needed, MarkdownParseError/SchemaValidationError caught above):
```python
        except Exception as e:
            if isinstance(e, (WorkflowValidationError, CompilationError)):
                return ValidationResult(
                    valid=False,
                    errors=[str(e)],
                    warnings=[],
                )
            # Unexpected errors (programming bugs) — let them propagate.
            raise
```

**In `_validate()` helper method (line 359)** — remove redundant lazy import:
```python
        # REMOVE (now at module level):
        from pflow.core.exceptions import WorkflowValidationError
```
The `raise WorkflowValidationError(...)` on line 362 now uses the module-level import.

**In `_resolve_file_references` method (lines 326-341)**:

Remove the lazy imports:
```python
        # REMOVE:
        from pflow.runtime import CompilationError
```

Keep the `import yaml` lazy import (that's a different concern — performance).

**In `_exception_to_result` method (lines 486-580)**:

Remove the lazy import block (lines 494-496):
```python
        # REMOVE:
        from pflow.core.exceptions import MaxNodeVisitsError, WorkflowValidationError
        from pflow.core.markdown_parser import MarkdownParseError
        from pflow.runtime import CompilationError
```

**Replace the `MarkdownParseError | ValueError` branch and the duck-type hack** (lines 545-560).

Current code (lines 545-560):
```python
        elif isinstance(exception, (MarkdownParseError, ValueError)):
            error_dict.update({"category": "validation"})
            if annotated_node_id:
                error_dict["node_id"] = annotated_node_id
        elif type(exception).__name__ == "ValidationError" and hasattr(exception, "path"):
            # ir_schema.ValidationError — has path and suggestion from prepare_inputs
            error_dict.update({
                "source": "validation",
                "category": "validation",
            })
            path = getattr(exception, "path", None)
            suggestion = getattr(exception, "suggestion", None)
            if path:
                error_dict["path"] = path
            if suggestion:
                error_dict["suggestion"] = suggestion
```

Replace with three separate branches:
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

**Key**: The `SchemaValidationError` branch MUST come before `ValueError`. The `MarkdownParseError` branch uses conditional field assignment (matching the `SchemaValidationError` pattern — don't write `None` values into error dicts). It preserves `annotated_node_id` for nested workflow scenarios where the engine annotates parse errors with the failing workflow node's ID.

### 3.7 `src/pflow/runtime/compilation/mcp_resolution.py`

**Add module-level import** (near top, with other imports):
```python
from pflow.core.exceptions import CompilationError
```

**Remove lazy import at line 114** (inside `_parse_mcp_node_type`):
```python
    # REMOVE:
    from .compiler import CompilationError
```

### 3.8 `src/pflow/runtime/compilation/node_loader.py`

**Add module-level import** (near top):
```python
from pflow.core.exceptions import CompilationError
```

**Remove lazy import at line 39** (inside `import_node_class`):
```python
    # REMOVE:
    from .compiler import CompilationError
```

### 3.9 `src/pflow/runtime/compilation/ir_preparation.py`

**Add module-level import** (near top):
```python
from pflow.core.exceptions import CompilationError
```

**Remove lazy import at line 189** (inside `validate_ir_structure`):
```python
    # REMOVE:
    from .compiler import CompilationError
```

### 3.10 `src/pflow/runtime/engine/engine.py`

**Add module-level import** (near top, with other imports):
```python
from pflow.core.exceptions import CompilationError
```

**Remove BOTH lazy imports** in the `run` method:
- Line 59: `from pflow.core.exceptions import CompilationError` (inside `--only` validation)
- Line 79: `from pflow.core.exceptions import CompilationError` (inside graph walk validation)

### 3.11 `src/pflow/runtime/engine/batch_executor.py`

**Remove the redundant lazy import at line 419** (inside `_collect_parallel_results`):
```python
    # REMOVE:
    from pflow.core.exceptions import CompilationError
```

The module-level import at line 19 (`from pflow.core.exceptions import CompilationError`) already covers this.

### 3.12 `src/pflow/mcp_server/services/execution_service.py`

**Add module-level import** (near top):
```python
from pflow.core.exceptions import MarkdownParseError
```

**Line ~302** (inside `save_workflow` method): The lazy import is:
```python
        from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
```

Change to only import `parse_markdown`:
```python
        from pflow.core.markdown_parser import parse_markdown
```

### 3.13 `src/pflow/core/workflow/manager.py`

**Current import at line 26**:
```python
from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
```

**Split**: Add module-level from exceptions, keep parse_markdown from markdown_parser:
```python
from pflow.core.exceptions import MarkdownParseError
```

Change line 26 to:
```python
from pflow.core.markdown_parser import parse_markdown
```

Note: `WorkflowExistsError`, `WorkflowNotFoundError`, `WorkflowValidationError` are already imported from `pflow.core.exceptions` at line 25. Add `MarkdownParseError` to that existing import:
```python
from pflow.core.exceptions import MarkdownParseError, WorkflowExistsError, WorkflowNotFoundError, WorkflowValidationError
```

### 3.14 `src/pflow/core/workflow/save_service.py`

**Current import at line 14**:
```python
from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
```

**Split**:
- Add `MarkdownParseError` to the existing exceptions import at line 12:
  ```python
  from pflow.core.exceptions import MarkdownParseError, WorkflowValidationError
  ```
- Change line 14 to:
  ```python
  from pflow.core.markdown_parser import parse_markdown
  ```

**Fix catch clause in `_discover_and_bundle_deps` (line 311)**:

Current:
```python
    except (FileNotFoundError, ValueError) as e:
```

The `parse_markdown()` call at line 282 can raise `MarkdownParseError`. After the rebase, `MarkdownParseError(PflowError)` is no longer a `ValueError`, so it falls through to `except Exception` producing misleading "If this is a bug, please report it" message. Fix:
```python
    except (FileNotFoundError, MarkdownParseError, ValueError) as e:
```

### 3.15 `src/pflow/core/workflow/dependency_discovery.py`

**Current import at line 16**:
```python
from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
```

**Split**:
- Add module-level: `from pflow.core.exceptions import MarkdownParseError`
- Change line 16 to: `from pflow.core.markdown_parser import parse_markdown`

### 3.16 Verify Phase 3

Run `make test`. Same single expected test failure as Phase 1 (`test_malformed_workflow`). All other tests pass.

---

## Phase 4: Fix ValueError Miscategorization

Already implemented in Phase 3 step 3.6 (the three-branch replacement in `_exception_to_result`). The ValueError branch now uses `annotated_node_id` as discriminator:
- WITH `_pflow_node_id` -> `category: "execution_failure"` (node threw during execution)
- WITHOUT `_pflow_node_id` -> `category: "validation"` (pre-execution error)

**Where `_pflow_node_id` is SET** (verified):
- `src/pflow/runtime/engine/engine.py:307` — engine sets it on any exception from `_execute_node`
- `src/pflow/execution/runner.py:202` — runner sets it from `shared["__execution__"]["failed_node"]`

**Where `_pflow_node_id` is READ**:
- `src/pflow/execution/runner.py:501` — `annotated_node_id = getattr(exception, "_pflow_node_id", None)`

Pre-execution ValueErrors (from IR parsing, template resolution before engine.run) never have `_pflow_node_id` set. This is a reliable discriminator.

---

## Phase 5: Fix Test Imports

### 5.1 `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py`

**Line 226** — the ONE breaking test:
```python
# FROM:
        with pytest.raises(ValueError):
# TO:
        with pytest.raises(MarkdownParseError):
```

**Add import** at top of file (after line 14 `import pytest`):
```python
from pflow.core.exceptions import MarkdownParseError
```

**Line 689** — this test catches a `ValueError("Circular workflow reference")` which is a plain `ValueError` from `workflow_executor.py:388`, NOT a `MarkdownParseError`. **Do NOT change this line.** It should remain `pytest.raises(ValueError)`.

### 5.2 `tests/test_docs/test_example_validation.py`

**Line 19** — current:
```python
from pflow.core import ValidationError, validate_ir
```

Replace with:
```python
from pflow.core import validate_ir
from pflow.core.exceptions import SchemaValidationError
```

**Line 21** — current:
```python
from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
```

Replace with:
```python
from pflow.core.exceptions import MarkdownParseError
from pflow.core.markdown_parser import parse_markdown
```

Note: if `SchemaValidationError` is already imported above, merge into one import:
```python
from pflow.core.exceptions import MarkdownParseError, SchemaValidationError
```

**Update all references**: `ValidationError` -> `SchemaValidationError` throughout the file:
- Line 72: `except ValidationError as e:` -> `except SchemaValidationError as e:`
- Line 94: `except (MarkdownParseError, ValidationError, ValueError):` -> `except (MarkdownParseError, SchemaValidationError, ValueError):`

### 5.3 `tests/test_runtime/test_compiler_interfaces.py`

**Line 12** — current:
```python
from pflow.core.ir_schema import ValidationError
```

Replace with:
```python
from pflow.core.exceptions import SchemaValidationError
```

**Update all references** (lines 129, 191, 239, 255, 341, 522, 537, 554):
All `pytest.raises(ValidationError)` -> `pytest.raises(SchemaValidationError)`
All `except ValidationError` -> `except SchemaValidationError`

### 5.4 `tests/test_runtime/test_output_validation.py`

**Line 8** — current:
```python
from pflow.core.ir_schema import ValidationError
```

Replace with:
```python
from pflow.core.exceptions import SchemaValidationError
```

**Update all references** (line 43):
`pytest.raises(ValidationError)` -> `pytest.raises(SchemaValidationError)`

### 5.5 `tests/test_cli/test_unified_error_output.py`

**Line 225** (lazy import inside test function) — current:
```python
        from pflow.core.ir_schema import ValidationError
```

Replace with:
```python
        from pflow.core.exceptions import SchemaValidationError
```

**Line 227** — current:
```python
        exc = ValidationError(
```

Replace with:
```python
        exc = SchemaValidationError(
```

### 5.6 `tests/test_core/test_ir_examples.py`

**Line 15** — current:
```python
from pflow.core import ValidationError, validate_ir
```

**Line 17** — current:
```python
from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
```

Replace both with:
```python
from pflow.core import validate_ir
from pflow.core.exceptions import MarkdownParseError, SchemaValidationError
from pflow.core.markdown_parser import parse_markdown
```

**Update references**:
- Line 250: `except (MarkdownParseError, ValidationError) as exc:` -> `except (MarkdownParseError, SchemaValidationError) as exc:`

### 5.7 `tests/test_core/test_ir_schema_output_suggestions.py`

**Line 11** — current:
```python
from pflow.core.ir_schema import ValidationError, validate_ir
```

Replace with:
```python
from pflow.core.exceptions import SchemaValidationError
from pflow.core.ir_schema import validate_ir
```

**Update all references** (lines 32, 54):
`pytest.raises(ValidationError)` -> `pytest.raises(SchemaValidationError)`

### 5.8 `tests/test_core/test_ir_schema.py`

**Line 5** — current:
```python
from pflow.core import FLOW_IR_SCHEMA, ValidationError, validate_ir
```

Replace with:
```python
from pflow.core import FLOW_IR_SCHEMA, validate_ir
from pflow.core.exceptions import SchemaValidationError
```

**Update ALL references** (29 occurrences at lines 149, 161, 172, 186, 202, 218, 239, 259, 276, 294, 309, 338, 353, 361, 398, 533, 553, 574, 594, 614, 634, 714, 825, 844, 881, 900, 937, 980, 999):
All `pytest.raises(ValidationError)` -> `pytest.raises(SchemaValidationError)`

### 5.9 `tests/test_core/test_workflow_interfaces.py`

**Line 5** — current:
```python
from pflow.core import ValidationError, validate_ir
```

Replace with:
```python
from pflow.core import validate_ir
from pflow.core.exceptions import SchemaValidationError
```

**Update all references** (lines 197, 218, 232, 247, 281, 301, 321):
`pytest.raises(ValidationError)` -> `pytest.raises(SchemaValidationError)`

### 5.10 `tests/test_integration/test_workflow_manager_integration.py`

**Line 20** — current:
```python
from pflow.core.markdown_parser import MarkdownParseError
```

Replace with:
```python
from pflow.core.exceptions import MarkdownParseError
```

### 5.11 `tests/test_core/test_file_resolver_integration.py`

**Line 10** — current:
```python
from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
```

Replace with:
```python
from pflow.core.exceptions import MarkdownParseError
from pflow.core.markdown_parser import parse_markdown
```

### 5.12 Verify Phase 5

Run `make test && make check`. ALL tests should now pass.

---

## Phase 6: New Tests

### 6.1 Hierarchy Coverage — `tests/test_core/test_exception_hierarchy.py` (NEW file)

```python
"""Test that the consolidated exception hierarchy works as expected."""

import pytest

from pflow.core.exceptions import (
    CompilationError,
    CriticalDiscoveryError,
    MarkdownParseError,
    PflowError,
    SchemaValidationError,
    WorkflowExistsError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from pflow.core.user_errors import MCPError, OutputResolutionError, UserFriendlyError


class TestExceptionHierarchy:
    """Verify all pflow exceptions inherit from PflowError."""

    def test_except_pflow_error_catches_all(self):
        """except PflowError catches all pflow-specific exceptions."""
        exceptions = [
            SchemaValidationError("test", path="root"),
            MarkdownParseError("test", line=1),
            CompilationError("test", phase="test"),
            WorkflowValidationError("test"),
            WorkflowNotFoundError("test"),
            WorkflowExistsError(),
            CriticalDiscoveryError("node", "reason"),
            UserFriendlyError("title", "explanation"),
            MCPError(),
            OutputResolutionError(failures=[]),
        ]
        for exc in exceptions:
            assert isinstance(exc, PflowError), f"{type(exc).__name__} is not a PflowError subclass"
            with pytest.raises(PflowError):
                raise exc

    def test_schema_validation_error_attributes(self):
        """SchemaValidationError carries message, path, suggestion."""
        exc = SchemaValidationError("bad field", path="nodes[0].type", suggestion="Use 'shell'")
        assert exc.message == "bad field"
        assert exc.path == "nodes[0].type"
        assert exc.suggestion == "Use 'shell'"
        assert "nodes[0].type" in str(exc)

    def test_markdown_parse_error_attributes(self):
        """MarkdownParseError carries line and suggestion."""
        exc = MarkdownParseError("bad syntax", line=42, suggestion="Add ## Steps")
        assert exc.line == 42
        assert exc.suggestion == "Add ## Steps"
        assert "Line 42" in str(exc)

    def test_markdown_parse_error_not_value_error(self):
        """MarkdownParseError no longer extends ValueError."""
        exc = MarkdownParseError("test")
        assert not isinstance(exc, ValueError)
        assert isinstance(exc, PflowError)
```

### 6.2 Regression Tests for `_exception_to_result` — `tests/test_execution/test_runner.py`

Add these tests to the existing test file (or as a new class in that file). These test the behavioral changes in `_exception_to_result`:

```python
from pflow.core.exceptions import MarkdownParseError, SchemaValidationError
from pflow.execution.runner import WorkflowRunner


class TestExceptionToResultCategorization:
    """Regression tests for _exception_to_result error categorization."""

    def _run(self, exception):
        """Helper to call _exception_to_result with minimal args."""
        runner = WorkflowRunner()
        return runner._exception_to_result(exception, 0.0, None)

    def test_valueerror_with_node_annotation_is_execution_failure(self):
        """ValueError from node execution (annotated) -> execution_failure."""
        exc = ValueError("HTTP timeout connecting to api.example.com")
        exc._pflow_node_id = "fetch-data"  # type: ignore[attr-defined]
        result = self._run(exc)
        assert result.errors[0]["category"] == "execution_failure"
        assert result.errors[0]["node_id"] == "fetch-data"

    def test_valueerror_without_annotation_is_validation(self):
        """ValueError from pre-execution (no annotation) -> validation."""
        exc = ValueError("Invalid parameter format")
        result = self._run(exc)
        assert result.errors[0]["category"] == "validation"
        assert "node_id" not in result.errors[0]

    def test_schema_validation_error_preserves_fields(self):
        """SchemaValidationError (replacing duck-type hack) preserves path and suggestion."""
        exc = SchemaValidationError("bad field", path="nodes[0].type", suggestion="Use 'shell'")
        result = self._run(exc)
        assert result.errors[0]["category"] == "validation"
        assert result.errors[0]["source"] == "validation"
        assert result.errors[0]["path"] == "nodes[0].type"
        assert result.errors[0]["suggestion"] == "Use 'shell'"

    def test_markdown_parse_error_preserves_line_and_suggestion(self):
        """MarkdownParseError extracts .line and .suggestion into error dict."""
        exc = MarkdownParseError("bad syntax", line=42, suggestion="Add ## Steps")
        result = self._run(exc)
        assert result.errors[0]["category"] == "validation"
        assert result.errors[0]["line"] == 42
        assert result.errors[0]["suggestion"] == "Add ## Steps"

    def test_markdown_parse_error_omits_none_fields(self):
        """MarkdownParseError with None line/suggestion doesn't write None values."""
        exc = MarkdownParseError("bad syntax")
        result = self._run(exc)
        assert result.errors[0]["category"] == "validation"
        assert "line" not in result.errors[0]
        assert "suggestion" not in result.errors[0]
```

---

## Phase 7: Final Verification

1. `make test` — all 4,630+ tests pass
2. `make check` — ruff + mypy clean
3. Verify zero lazy exception imports remain:
   ```bash
   # Should return zero matches in src/pflow/ for lazy imports of our exceptions:
   grep -rn "from pflow.core.ir_schema import.*ValidationError" src/pflow/ | grep -v "SchemaValidationError as ValidationError"
   # The only match should be the re-export in ir_schema.py itself

   grep -rn "from pflow.core.markdown_parser import.*MarkdownParseError" src/pflow/
   # The only match should be the re-export in markdown_parser.py itself

   grep -rn "from .compiler import CompilationError" src/pflow/
   # Should return zero matches

   grep -rn "from pflow.runtime import CompilationError" src/pflow/
   # Should return zero matches in execution/ and cli/ (runtime/__init__.py re-export still exists but is unused by production code)

   # Verify duck-type hack is eliminated (check for the SPECIFIC pattern, not all type().__name__ usage):
   grep -rn 'type(exception).__name__ == "ValidationError"' src/pflow/
   # Should return zero matches
   ```
4. Verify `except PflowError` catches all (covered by Phase 6.1 test)
5. Verify ValueError categorization fix (covered by Phase 6.2 tests)

---

## Phase 8: Code Review

Run `/code-review` (the skill) to deploy specialized review agents against the actual implementation (not the plan). This catches issues that only surface in real code — missed imports, typos in isinstance checks, ordering bugs in dispatch chains, etc.

**Trigger**: Use the `code-review` skill at the start of this phase. It will deploy 7 agents in parallel.

**Process**:
1. Run `/code-review` against the staged/committed changes on this branch
2. Evaluate findings — the review summary will classify each as confirmed/disputed/needs-investigation
3. Fix all confirmed findings
4. Re-run `make test && make check` after fixes
5. If any fix was non-trivial, run `/code-review` again on the delta

---

## Phase 9: Manual Testing + Baseline Comparison

Verify error output hasn't regressed by comparing against pre-implementation baselines.

**At the start of this phase, read these files**:
- `.taskmaster/tasks/task_141/implementation/baseline.md` — baseline behavior reference
- `.taskmaster/tasks/task_141/implementation/baseline-error-output.md` — baseline error output shapes (pre-implementation snapshots)

**Test fixtures** (pre-created in `.taskmaster/tasks/task_141/implementation/baseline-fixtures/`):
- `valid.pflow.md` — valid workflow (happy path)
- `malformed.pflow.md` — triggers MarkdownParseError (no ## Steps)
- `missing-type.pflow.md` — triggers SchemaValidationError (missing node type)
- `duplicate-ids.pflow.md` — triggers SchemaValidationError (duplicate node IDs)
- `bad-schema.pflow.md` — triggers SchemaValidationError (schema-level error)
- `unclosed-code-block.pflow.md` — triggers MarkdownParseError (unclosed fence)
- `bad-sub-workflow.pflow.md` — triggers nested workflow error path

**Manual test cases** (run each fixture in both text and JSON mode, compare against baselines):

```bash
FIXTURES=.taskmaster/tasks/task_141/implementation/baseline-fixtures

# 1. Valid workflow — verify happy path unaffected
uv run pflow $FIXTURES/valid.pflow.md

# 2. Markdown parse errors — verify MarkdownParseError output
uv run pflow $FIXTURES/malformed.pflow.md
uv run pflow --output-format json $FIXTURES/malformed.pflow.md
uv run pflow $FIXTURES/unclosed-code-block.pflow.md
uv run pflow --output-format json $FIXTURES/unclosed-code-block.pflow.md

# 3. Schema validation errors — verify SchemaValidationError output
uv run pflow --validate-only $FIXTURES/missing-type.pflow.md
uv run pflow --output-format json --validate-only $FIXTURES/missing-type.pflow.md
uv run pflow --validate-only $FIXTURES/duplicate-ids.pflow.md
uv run pflow --validate-only $FIXTURES/bad-schema.pflow.md

# 4. Nested workflow error — verify sub-workflow error path
uv run pflow $FIXTURES/bad-sub-workflow.pflow.md
uv run pflow --output-format json $FIXTURES/bad-sub-workflow.pflow.md
```

**Compare each output against the baseline-error-output.md document.** Check:
- Error messages match expected format
- JSON error dicts have correct `category` fields
- No `null` values in JSON error dicts (line/suggestion only present when non-None)
- Text mode uses correct formatting (no "If this is a bug" for parse errors)

**Pass criteria**: Error output shape and content matches baselines. Any differences must be intentional improvements documented in the plan (e.g., MarkdownParseError now includes `line` and `suggestion` fields when non-None, ValueError from node execution now gets `execution_failure` category).

---

## Files Modified (Complete List)

### Production code (19 files):
1. `src/pflow/core/exceptions.py` — add SchemaValidationError, MarkdownParseError classes
2. `src/pflow/core/ir_schema.py` — remove class, add re-export
3. `src/pflow/core/markdown_parser.py` — remove class, add re-export
4. `src/pflow/core/user_errors.py` — rebase UserFriendlyError, add PflowError import
5. `src/pflow/core/__init__.py` — update re-export name
6. `src/pflow/runtime/compilation/compile_validation.py` — module-level imports, remove parameter pattern
7. `src/pflow/core/workflow/validator.py` — module-level exception imports
8. `src/pflow/cli/error_output.py` — module-level imports, delete helper, fix isinstance
9. `src/pflow/cli/commands/workflow.py` — module-level MarkdownParseError import
10. `src/pflow/execution/runner.py` — module-level imports, fix duck-type, fix ValueError categorization
11. `src/pflow/runtime/compilation/mcp_resolution.py` — module-level CompilationError
12. `src/pflow/runtime/compilation/node_loader.py` — module-level CompilationError
13. `src/pflow/runtime/compilation/ir_preparation.py` — module-level CompilationError
14. `src/pflow/runtime/engine/engine.py` — module-level CompilationError
15. `src/pflow/runtime/engine/batch_executor.py` — remove redundant lazy import
16. `src/pflow/mcp_server/services/execution_service.py` — module-level MarkdownParseError
17. `src/pflow/core/workflow/manager.py` — update MarkdownParseError import path
18. `src/pflow/core/workflow/save_service.py` — update MarkdownParseError import path + fix catch clause in `_discover_and_bundle_deps`
19. `src/pflow/core/workflow/dependency_discovery.py` — update MarkdownParseError import path

### Test code (13 files):
1. `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` — pytest.raises fix
2. `tests/test_docs/test_example_validation.py` — import + rename
3. `tests/test_runtime/test_compiler_interfaces.py` — import + rename
4. `tests/test_runtime/test_output_validation.py` — import + rename
5. `tests/test_cli/test_unified_error_output.py` — import + rename
6. `tests/test_core/test_ir_examples.py` — import + rename
7. `tests/test_core/test_ir_schema_output_suggestions.py` — import + rename
8. `tests/test_core/test_ir_schema.py` — import + rename (29 occurrences)
9. `tests/test_core/test_workflow_interfaces.py` — import + rename
10. `tests/test_integration/test_workflow_manager_integration.py` — import path
11. `tests/test_core/test_file_resolver_integration.py` — import path
12. `tests/test_core/test_exception_hierarchy.py` — NEW file (hierarchy coverage test)
13. `tests/test_execution/test_runner.py` — NEW tests (regression tests for categorization fix)
