# Task 137: Unified CLI Output Pipeline — Implementation Plan

## Context

The CLI output layer produces 7 different JSON shapes from 4 separate pipelines. Pre-execution errors (9 handlers) output plain text even when `--output-format json` is set. Structured exception fields (ValidationError.path, MaxNodeVisitsError.node_id, MarkdownParseError.line) are destroyed in catch chains. ExecutionResult carries 5 orphaned fields never read by any consumer.

This plan restructures the output layer so ALL outcomes flow through one pipeline with one JSON shape. It preserves all existing text-mode display fidelity while adding JSON support to every error path and preserving structured exception data.

**Supersedes**: Task 117 (JSON error output — bandaid approach)
**Enables**: Task 134 (output detection), Issue 6 (entry point unification)

---

## The Unified JSON Error Shape

All error JSON output will conform to this single structure, mirroring the success shape:

```json
{
  "success": false,
  "status": "failed",
  "error": "Human-readable summary string",
  "errors": [
    {
      "message": "Detailed error message",
      "category": "validation|compilation|runtime|parse_error|not_found|cli|mcp|max_visits|file_not_found|permission_denied|unknown",
      "suggestion": "How to fix",
      "node_id": "node-id",
      "path": "inputs.data",
      "line": 42,
      "source": "runtime|compilation",
      "node_type": "shell",
      "phase": "template_validation",
      "sub_workflow_path": "path/to/sub.pflow.md",
      "shell_command": "exit 1",
      "shell_stderr": "error output",
      "status_code": 400,
      "raw_response": {},
      "mcp_error": {}
    }
  ],
  "workflow": {"action": "unsaved|reused|created", "name": "workflow-name"},
  "duration_ms": 1234.5,
  "total_cost_usd": 0.001,
  "nodes_executed": 3,
  "metrics": {"workflow": {}, "total": {}},
  "execution": {"duration_ms": 1234.5, "nodes_executed": 3, "nodes_total": 5, "steps": []}
}
```

**Rules:**
- `success`: always `false` for errors
- `status`: always present, always `"failed"` for errors
- `error`: always a **string** (human-readable summary), never a dict. For single-error results, derived from `errors[0].message`. For multi-error, use descriptive summary with count (e.g., "Workflow execution failed (3 errors)")
- `errors`: always an **array of objects**, each with at minimum `message` and `category`
- `category` authoritative enum: `validation`, `compilation`, `runtime`, `parse_error`, `not_found`, `cli`, `mcp`, `max_visits`, `file_not_found`, `permission_denied`, `unknown`. Code and spec MUST use only these values.
- `workflow`: always present, uses key name `workflow` (not `metadata`)
- Optional fields (`suggestion`, `node_id`, `path`, `line`, `source`, etc.): **omitted** when not applicable (not null)
- Post-execution fields (`duration_ms`, `total_cost_usd`, `nodes_executed`, `metrics`, `execution`): **omitted** for pre-execution errors
- **Removed fields**: `is_error` (redundant), `validation_errors` (use `errors`), `metadata` (use `workflow`), `failed_node` (use `errors[0].node_id`), `checkpoint` (internal)

---

## Implementation Phases

All phases are ordered so `make test && make check` passes after each phase.

---

### Phase 0: Dead Code Removal

**Goal**: Remove confirmed dead code to reduce noise for subsequent phases.

#### 0.1 Remove `_append_footer` from success_formatter.py

**File**: `src/pflow/execution/formatters/success_formatter.py`
**Action**: Delete function `_append_footer` at line ~478. It is defined but never called by any code.

#### 0.2 Remove vestigial CompilationError from user_errors.py

**File**: `src/pflow/core/user_errors.py`
**Action**: Delete class `CompilationError(UserFriendlyError)` at lines 112-115. It has zero raise sites — the real CompilationError is at `runtime/compilation/compiler.py:33`.

**File**: `src/pflow/cli/main.py`
**Action**: Find and remove the import alias `CompilerCompilationError` (or similar disambiguation) if it exists. The compiler's CompilationError can now be imported without ambiguity. Search for `CompilerCompilationError` or `from pflow.core.user_errors import CompilationError`.

**Note**: After removing the vestigial class, verify no imports reference `pflow.core.user_errors.CompilationError`. Search: `grep -r "user_errors.*CompilationError" src/`.

#### 0.3 Remove unused logger from workflow_execution.py

**File**: `src/pflow/execution/workflow_execution.py`
**Action**: Delete `import logging` and `logger = logging.getLogger(__name__)` at line ~10. The logger is never used.

#### Verification

```bash
make test && make check
```

---

### Phase 1: Clean ExecutionResult

**Goal**: Remove 5 orphaned fields from `ExecutionResult` that are populated but never read.

#### 1.1 Remove fields from dataclass

**File**: `src/pflow/execution/executor_service.py:18-31`

Change from:
```python
@dataclass
class ExecutionResult:
    """Result of workflow execution."""
    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    action_result: Optional[str] = None
    node_count: int = 0
    duration: float = 0.0
    output_data: Optional[str] = None
    metrics_summary: Optional[dict[str, Any]] = None
```

To:
```python
@dataclass
class ExecutionResult:
    """Result of workflow execution."""
    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
```

#### 1.2 Update `_build_execution_result` in executor_service.py

**File**: `src/pflow/execution/executor_service.py` — find `_build_execution_result` (around line 655)

Remove the 5 orphaned fields from BOTH the `ExecutionResult(...)` constructor call AND the `_build_execution_result` function signature. The function currently accepts `action_result`, `output_data`, `metrics_summary`, `node_count`, `duration` as parameters from its caller (`execute_workflow` method around line 154-169). Remove these parameters from the function signature and stop computing/passing them in the caller. Keep only: `success`, `status`, `shared_after`, `errors`, `warnings`.

#### 1.3 Update CompilationError wrapping in workflow_execution.py

**File**: `src/pflow/execution/workflow_execution.py:64-90`

Remove `action_result="compilation_failed"` from the `ExecutionResult(...)` constructor. Remove `shared_after={}` only if `shared_after` still has a default — check: yes, it defaults to `field(default_factory=dict)`, so it can be omitted.

The wrapping becomes:
```python
return ExecutionResult(
    success=False,
    status=WorkflowStatus.FAILED,
    errors=[{
        "source": "compilation",
        "category": "compilation",
        "message": getattr(e, "raw_message", str(e)),
        "phase": getattr(e, "phase", None),
        "node_id": getattr(e, "node_id", None),
        "node_type": getattr(e, "node_type", None),
        "suggestion": getattr(e, "suggestion", None),
        "sub_workflow_path": (getattr(e, "details", None) or {}).get("sub_workflow_path"),
    }],
)
```

#### 1.4 Update test files

4 test files construct `ExecutionResult` directly:

1. **`tests/test_execution/formatters/test_error_formatter.py`** — 14 constructions. None use orphaned fields. No changes needed.

2. **`tests/test_cli/test_agent_ux_fixes.py`** — 2 constructions. Neither uses orphaned fields. No changes needed.

3. **`tests/test_runtime/test_checkpoint_tracking.py:267-275`** — Remove `output_data=None` from the constructor call.

4. **`tests/test_cli/test_workflow_output_handling.py:108`** — Remove `output_data=None` from the constructor call.

5. **`tests/test_execution/test_workflow_execution.py:70,166`** — These assert `result.action_result == "compilation_failed"`. Change to assert `result.errors[0]["source"] == "compilation"` (same information, already asserted on the next line in both tests).

#### Verification

```bash
make test && make check
```

---

### Phase 2: Enrich Exception Classes

**Goal**: Add structured fields to exceptions that will carry pre-execution error data through the pipeline.

#### 2.1 Enrich WorkflowNotFoundError

**File**: `src/pflow/core/exceptions.py`

Change from:
```python
class WorkflowNotFoundError(PflowError):
    pass
```

To:
```python
class WorkflowNotFoundError(PflowError):
    """Raised when a workflow cannot be found or has an unsupported format."""

    def __init__(
        self,
        workflow_name: str,
        similar_names: Optional[list[str]] = None,
        hint: str | None = None,
    ):
        self.workflow_name = workflow_name
        self.similar_names = similar_names or []
        self.hint = hint
        super().__init__(hint or f"Workflow '{workflow_name}' not found")

    def format_for_cli(self) -> str:
        """Format for text-mode CLI display."""
        if self.hint:
            return f"\u274c {self.hint}"
        lines = [f"\u274c Workflow '{self.workflow_name}' not found."]
        if self.similar_names:
            lines.append("\nDid you mean one of these?")
            for name in self.similar_names:
                lines.append(f"  - {name}")
        else:
            lines.append("\nUse 'pflow workflow list' to see available workflows.")
        return "\n".join(lines)
```

Add `from typing import Optional` if not already imported.

**Important**: `WorkflowNotFoundError` is also raised in `src/pflow/core/workflow/manager.py` (lines ~287, 385, 413) with a single string argument. Those raise sites use `WorkflowNotFoundError("message")`. The new constructor's first param is `workflow_name`, not `message`. This is a breaking change for those call sites.

**Fix**: Update raise sites in `manager.py` to pass the workflow name:
- Search for `raise WorkflowNotFoundError` in `src/pflow/core/workflow/manager.py`
- Change `raise WorkflowNotFoundError(f"Workflow '{name}' not found")` to `raise WorkflowNotFoundError(name)`
- Change `raise WorkflowNotFoundError(f"No workflow found matching '{query}'")` to `raise WorkflowNotFoundError(query)`

#### 2.2 Enrich WorkflowValidationError

**File**: `src/pflow/core/exceptions.py`

Change from:
```python
class WorkflowValidationError(PflowError):
    pass
```

To:
```python
class WorkflowValidationError(PflowError):
    """Raised when workflow validation fails."""

    def __init__(
        self,
        summary: str = "Workflow validation failed",
        validation_errors: Optional[list[str | tuple[str, str, str]]] = None,
    ):
        self.summary = summary
        self.validation_errors = validation_errors or []
        super().__init__(summary)

    def format_for_cli(self) -> str:
        """Format for text-mode CLI display."""
        from pflow.execution.formatters.validation_formatter import format_validation_failure

        # Extract message strings from either plain strings or (msg, path, suggestion) tuples
        error_strings = []
        for err in self.validation_errors:
            if isinstance(err, tuple):
                msg, path, suggestion = err
                parts = [f"\u274c {msg}"]
                if path and path != "root":
                    parts.append(f"   At: {path}")
                if suggestion:
                    parts.append(f"   \U0001f449 {suggestion}")
                error_strings.append("\n".join(parts))
            else:
                error_strings.append(str(err))

        if error_strings:
            return "\n".join(error_strings)
        # No structured validation_errors — display the summary directly
        return f"\u274c {self.summary}"
```

**Important**: `WorkflowValidationError` is also raised in `src/pflow/core/workflow/manager.py` AND `src/pflow/core/workflow/save_service.py` (20+ sites total) with a single string. These all pass a positional string as `summary` — backward-compatible, no changes needed to those call sites. But verify with: `grep -r "raise WorkflowValidationError" src/` to confirm all sites work with the new constructor.

#### 2.3 Add format_for_cli to MaxNodeVisitsError

**File**: `src/pflow/core/exceptions.py`

The class already has structured fields. Add a `format_for_cli` method:

```python
class MaxNodeVisitsError(RuntimeError):
    """Raised when a node exceeds its maximum visit count."""

    def __init__(self, node_id: str, visit_count: int, max_visits: int):
        self.node_id = node_id
        self.visit_count = visit_count
        self.max_visits = max_visits
        super().__init__(
            f"Node '{node_id}' exceeded maximum visits: {visit_count} visits "
            f"(max: {max_visits}). This usually indicates an infinite loop."
        )

    def format_for_cli(self) -> str:
        return f"\u274c {self}"
```

#### Verification

```bash
make test && make check
```

No behavioral change — only additive (new fields with defaults, new methods).

---

### Phase 3: Create Unified Error Formatter

**Goal**: Create a single function that produces the unified JSON error shape from ANY error source.

#### 3.1 Create the formatter

**File**: `src/pflow/cli/error_output.py` (NEW FILE)

```python
"""Unified error output for CLI.

Produces a single JSON shape for ALL error types: pre-execution exceptions,
post-execution failures (ExecutionResult), and unexpected exceptions.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import click


def format_error_json(
    *,
    exception: Exception | None = None,
    result: Any = None,
    workflow_metadata: dict[str, Any] | None = None,
    metrics_collector: Any = None,
    shared_storage: dict[str, Any] | None = None,
    ir_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build unified error JSON from either an exception or an ExecutionResult.

    Exactly one of `exception` or `result` must be provided.

    Returns a dict conforming to the unified error shape:
    {success, status, error, errors, workflow, [duration_ms, metrics, execution]}
    """
    if result is not None:
        return _format_from_result(result, workflow_metadata, metrics_collector, shared_storage, ir_data)
    if exception is not None:
        return _format_from_exception(exception, workflow_metadata, metrics_collector, shared_storage)
    raise ValueError("Either exception or result must be provided")


def _format_from_result(
    result: Any,
    workflow_metadata: dict[str, Any] | None,
    metrics_collector: Any,
    shared_storage: dict[str, Any] | None,
    ir_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Format error from ExecutionResult (post-execution failure)."""
    from pflow.execution.formatters.error_formatter import format_execution_errors

    status = getattr(result, "status", None)
    status_str = status.value if status else "failed"

    # Use existing error formatter for sanitization and execution steps
    formatted = format_execution_errors(
        result,
        shared_storage=shared_storage,
        ir_data=ir_data,
        metrics_collector=metrics_collector,
        sanitize=True,
    )

    # Errors array
    if "errors" in formatted:
        errors_list = formatted["errors"]
    elif hasattr(result, "errors") and result.errors:
        errors_list = result.errors
    else:
        errors_list = [{"message": "Unknown error", "category": "unknown"}]

    # Derive summary from actual errors (not hardcoded)
    if len(errors_list) == 1:
        first_msg = errors_list[0].get("message", "Unknown error")
        first_cat = errors_list[0].get("category", "")
        summary = "Compilation failed" if first_cat == "compilation" else first_msg
    else:
        summary = f"Workflow execution failed ({len(errors_list)} errors)"

    output: dict[str, Any] = {
        "success": False,
        "status": status_str,
        "error": summary,
        "errors": errors_list,
    }

    # Workflow metadata
    output["workflow"] = workflow_metadata or {"action": "unsaved"}

    # Execution state (from formatter)
    if "execution" in formatted:
        output["execution"] = formatted["execution"]

    # Metrics (flatten to top-level, matching success shape)
    if "metrics" in formatted:
        metrics_data = formatted["metrics"]
        if "duration_ms" in metrics_data:
            output["duration_ms"] = metrics_data["duration_ms"]
        if "total_cost_usd" in metrics_data:
            output["total_cost_usd"] = metrics_data["total_cost_usd"]
        if "nodes_executed" in metrics_data:
            output["nodes_executed"] = metrics_data["nodes_executed"]
        if "metrics" in metrics_data:
            output["metrics"] = metrics_data["metrics"]

    return output


def _format_from_exception(
    exception: Exception,
    workflow_metadata: dict[str, Any] | None,
    metrics_collector: Any,
    shared_storage: dict[str, Any] | None,
) -> dict[str, Any]:
    """Format error from a pre-execution or unexpected exception."""
    summary, errors = _exception_to_errors(exception)

    output: dict[str, Any] = {
        "success": False,
        "status": "failed",
        "error": summary,
        "errors": errors,
        "workflow": workflow_metadata or {"action": "unsaved"},
    }

    # Add metrics if available (exception during execution may still have metrics)
    # record_workflow_end() is idempotent (just sets a timestamp).
    # executor_service's finally block may have already called it if the exception
    # occurred inside execute_workflow. For pre-execution exceptions, this is the first call.
    if metrics_collector is not None:
        try:
            metrics_collector.record_workflow_end()
            # get_summary() requires llm_calls — extract from trace collector
            # (matches pattern in workflow_errors.py:74-84 and error_formatter.py:83-85)
            trace = shared_storage.get("_trace_collector") if shared_storage else None
            llm_calls = trace.collect_llm_calls() if trace else []
            summary_data = metrics_collector.get_summary(llm_calls)
            if summary_data:
                if "duration_ms" in summary_data:
                    output["duration_ms"] = summary_data["duration_ms"]
                if "total_cost_usd" in summary_data:
                    output["total_cost_usd"] = summary_data["total_cost_usd"]
                if "metrics" in summary_data:
                    output["metrics"] = summary_data["metrics"]
        except Exception:
            pass  # Metrics are best-effort

    return output


def _exception_to_errors(exception: Exception) -> tuple[str, list[dict[str, Any]]]:
    """Convert any exception to (summary, errors_list) for unified JSON.

    Extracts structured fields from known exception types.
    Unknown exceptions get a generic single-error entry.
    """
    # Lazy imports to avoid circular dependencies
    from pflow.core.exceptions import (
        MaxNodeVisitsError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    )
    from pflow.core.ir_schema import ValidationError as IrSchemaValidationError
    from pflow.core.markdown_parser import MarkdownParseError
    from pflow.core.user_errors import MCPError, OutputResolutionError, UserFriendlyError

    # Order matters: check subclasses BEFORE parent classes

    if isinstance(exception, WorkflowValidationError):
        errors = []
        for err in exception.validation_errors:
            if isinstance(err, tuple):
                msg, path, suggestion = err
                entry: dict[str, Any] = {"message": msg, "category": "validation"}
                if path and path != "root":
                    entry["path"] = path
                if suggestion:
                    entry["suggestion"] = suggestion
                errors.append(entry)
            else:
                errors.append({"message": str(err), "category": "validation"})
        return exception.summary, errors if errors else [{"message": str(exception), "category": "validation"}]

    if isinstance(exception, WorkflowNotFoundError):
        entry: dict[str, Any] = {"message": str(exception), "category": "not_found"}
        if exception.similar_names:
            entry["suggestion"] = f"Did you mean: {', '.join(exception.similar_names)}"
        return str(exception), [entry]

    # Check UserFriendlyError subclasses BEFORE the parent
    if isinstance(exception, MCPError):
        entry: dict[str, Any] = {"message": exception.explanation, "category": "mcp"}
        if exception.suggestions:
            entry["suggestion"] = "; ".join(exception.suggestions)
        return exception.title, [entry]

    if isinstance(exception, OutputResolutionError):
        # Preserve structured .failures data
        errors = []
        for failure in exception.failures:
            entry: dict[str, Any] = {
                "message": failure.get("diagnostics", str(exception)),
                "category": "runtime",
                "output_name": failure.get("output_name"),
                "source_expr": failure.get("source_expr"),
            }
            errors.append(entry)
        if not errors:
            errors = [{"message": exception.explanation, "category": "runtime"}]
        return exception.title, errors

    if isinstance(exception, UserFriendlyError):
        # Generic UserFriendlyError (not MCPError/OutputResolutionError)
        entry: dict[str, Any] = {"message": exception.explanation, "category": "cli"}
        if exception.suggestions:
            entry["suggestion"] = "; ".join(exception.suggestions)
        return exception.title, [entry]

    if isinstance(exception, MaxNodeVisitsError):
        return str(exception), [{
            "message": str(exception),
            "category": "max_visits",
            "node_id": exception.node_id,
            "visit_count": exception.visit_count,
            "max_visits": exception.max_visits,
        }]

    # MarkdownParseError (explicit isinstance, not duck-typed)
    if isinstance(exception, MarkdownParseError):
        entry: dict[str, Any] = {"message": str(exception), "category": "parse_error"}
        if exception.line is not None:
            entry["line"] = exception.line
        if exception.suggestion:
            entry["suggestion"] = exception.suggestion
        return str(exception), [entry]

    # ValidationError from ir_schema (explicit isinstance, not string-based type check)
    if isinstance(exception, IrSchemaValidationError):
        entry: dict[str, Any] = {"message": exception.message, "category": "validation"}
        if exception.path:
            entry["path"] = exception.path
        if exception.suggestion:
            entry["suggestion"] = exception.suggestion
        return str(exception), [entry]

    if isinstance(exception, FileNotFoundError):
        return str(exception), [{"message": str(exception), "category": "file_not_found"}]

    if isinstance(exception, PermissionError):
        return str(exception), [{"message": str(exception), "category": "permission_denied"}]

    # Generic fallback
    return str(exception), [{"message": str(exception), "category": "unknown"}]


def display_exception_text(exception: Exception, verbose: bool = False) -> None:
    """Display exception in text mode, preserving rich formatting.

    Uses format_for_cli() when available, falls back to generic display.
    """
    from pflow.core.exceptions import WorkflowNotFoundError, WorkflowValidationError
    from pflow.core.user_errors import UserFriendlyError

    if isinstance(exception, UserFriendlyError):
        click.echo(exception.format_for_cli(verbose), err=True)
    elif isinstance(exception, WorkflowNotFoundError):
        click.echo(exception.format_for_cli(), err=True)
    elif isinstance(exception, WorkflowValidationError):
        click.echo(exception.format_for_cli(), err=True)
    elif hasattr(exception, "format_for_cli"):
        click.echo(exception.format_for_cli(), err=True)
    elif isinstance(exception, (FileNotFoundError, PermissionError)):
        click.echo(f"\u2717 {exception}", err=True)
    elif isinstance(exception, ValueError) and hasattr(exception, "line"):
        # MarkdownParseError
        click.echo(f"\u2717 {exception}", err=True)
    elif isinstance(exception, RuntimeError) and "registry" in str(exception).lower():
        # Preserve registry-specific guidance from old _handle_workflow_exception
        click.echo(f"cli: Error - Failed to load registry: {exception}", err=True)
        click.echo("cli: Try 'pflow registry list' to see available nodes.", err=True)
        click.echo("cli: Or 'pflow registry scan <path>' to add custom nodes.", err=True)
    else:
        click.echo(f"cli: Workflow execution failed - {exception}", err=True)


def output_error(
    ctx: click.Context | None,
    exception: Exception | None = None,
    result: Any = None,
    output_format: str = "text",
    verbose: bool = False,
    workflow_metadata: dict[str, Any] | None = None,
    metrics_collector: Any = None,
    shared_storage: dict[str, Any] | None = None,
    ir_data: dict[str, Any] | None = None,
) -> None:
    """Output an error in the appropriate format (JSON or text).

    This is the SINGLE error output function for the entire CLI.
    """
    if output_format == "json":
        from pflow.cli.workflow_output import _serialize_json_result

        error_dict = format_error_json(
            exception=exception,
            result=result,
            workflow_metadata=workflow_metadata,
            metrics_collector=metrics_collector,
            shared_storage=shared_storage,
            ir_data=ir_data,
        )
        _serialize_json_result(error_dict, verbose)
    else:
        if exception is not None:
            display_exception_text(exception, verbose)
        elif result is not None:
            from pflow.cli.workflow_errors import _display_text_error_details

            _display_text_error_details(result, verbose)
        else:
            click.echo("cli: Unknown error", err=True)
```

#### Verification

```bash
make test && make check
```

New file, not yet wired — no behavioral change.

---

### Phase 4: Fix Exception Data Loss at Catch Sites

**Goal**: Preserve structured fields that are currently destroyed.

#### 4.1 Catch ValidationError specifically in validator.py

**File**: `src/pflow/core/workflow/validator.py` — find the `except Exception as e` around line ~131 that catches validation errors from `validate_ir()`.

Change from (approximately):
```python
try:
    validate_ir(workflow_ir)
except Exception as e:
    errors.append(f"Structure: {e}")
```

To:
```python
from pflow.core.ir_schema import ValidationError as SchemaValidationError

try:
    validate_ir(workflow_ir)
except SchemaValidationError as e:
    error_msg = f"Structure: {e}"
    errors.append(error_msg)
except Exception as e:
    errors.append(f"Structure: Unexpected error during validation: {e}")
```

This preserves the same behavior (errors list gets a string) but now unexpected non-validation exceptions are labeled differently instead of silently becoming "validation errors."

#### 4.2 Catch MaxNodeVisitsError in workflow_execution.py

**File**: `src/pflow/execution/workflow_execution.py:64-90`

The current code catches `Exception`, checks for `CompilationError`, and re-raises everything else. Add `MaxNodeVisitsError` handling:

```python
except Exception as e:
    from pflow.runtime import CompilationError
    from pflow.core.exceptions import MaxNodeVisitsError

    if isinstance(e, CompilationError):
        from pflow.core.workflow.status import WorkflowStatus
        return ExecutionResult(
            success=False,
            status=WorkflowStatus.FAILED,
            errors=[{
                "source": "compilation",
                "category": "compilation",
                "message": getattr(e, "raw_message", str(e)),
                "phase": getattr(e, "phase", None),
                "node_id": getattr(e, "node_id", None),
                "node_type": getattr(e, "node_type", None),
                "suggestion": getattr(e, "suggestion", None),
                "sub_workflow_path": (getattr(e, "details", None) or {}).get("sub_workflow_path"),
            }],
        )

    if isinstance(e, MaxNodeVisitsError):
        from pflow.core.workflow.status import WorkflowStatus
        return ExecutionResult(
            success=False,
            status=WorkflowStatus.FAILED,
            errors=[{
                "source": "runtime",
                "category": "max_visits",
                "message": str(e),
                "node_id": e.node_id,
                "visit_count": e.visit_count,
                "max_visits": e.max_visits,
            }],
        )

    raise
```

#### 4.3 Stop wrapping MarkdownParseError in ValueError

**File**: `src/pflow/runtime/workflow_executor.py` — find the catch around line ~375 where `MarkdownParseError` is wrapped in `ValueError`.

Change from:
```python
except MarkdownParseError as e:
    raise ValueError(f"Invalid workflow file {path}: {e}")
```

To:
```python
except MarkdownParseError:
    raise  # Preserve structured fields (line, suggestion)
```

The `MarkdownParseError` will now propagate with its `line` and `suggestion` fields intact. Callers that catch `ValueError` will still catch it (since `MarkdownParseError extends ValueError`).

#### Verification

```bash
make test && make check
```

---

### Phase 5: Restructure workflow_resolution.py

**Goal**: Change `resolve_workflow()` to raise exceptions instead of returning error tuples.

#### 5.1 Modify `_try_load_workflow_from_file`

**File**: `src/pflow/cli/workflow_resolution.py`

Current behavior: catches `MarkdownParseError`, `PermissionError`, `UnicodeDecodeError`, displays errors, returns `(None, "parse_error")`.

New behavior: raises exceptions (MarkdownParseError, PermissionError, UnicodeDecodeError propagate). Extension checks raise `WorkflowNotFoundError`.

**Changes**:
1. Remove the `_show_markdown_parse_error` function entirely
2. In `_try_load_workflow_from_file`:
   - `.json` extension check: raise `WorkflowNotFoundError(str(path), hint="JSON workflow format is no longer supported: ...")` instead of `click.echo` + return
   - `.md` not `.pflow.md` check: raise `WorkflowNotFoundError(str(path), hint="Wrong file extension: ...")` instead of `click.echo` + return
   - Remove `except MarkdownParseError` — let it propagate
   - Remove `except PermissionError` — let it propagate
   - Remove `except UnicodeDecodeError` — let it propagate
   - File not found: still return `None` (to allow fallthrough to registry)

3. Change return type from `tuple[dict | None, str | None]` to `dict | None`

#### 5.2 Simplify `resolve_workflow`

**File**: `src/pflow/cli/workflow_resolution.py`

Current signature: `resolve_workflow(identifier, wm=None) -> tuple[dict | None, str | None]`
New signature: `resolve_workflow(identifier, wm=None) -> tuple[dict | None, str | None]`

Keep the return type for now (source is still useful for metadata). But remove the `"parse_error"` sentinel — errors are now exceptions.

```python
def resolve_workflow(identifier: str, wm: WorkflowManager | None = None) -> tuple[dict | None, str | None]:
    """Resolve a workflow identifier to an IR dict.

    Returns (ir_dict, source) or (None, None) if not found.
    Raises WorkflowNotFoundError for wrong extensions, MarkdownParseError for parse failures.

    Note: File-not-found for path-like identifiers intentionally falls through to registry
    lookup. A user might pass './my-workflow.pflow.md' that doesn't exist as a file but
    exists as a saved workflow.
    """
    # IMPORTANT: Preserve the WorkflowManager initialization guard
    wm = wm or WorkflowManager()

    if _is_path_like(identifier):
        ir = _try_load_workflow_from_file(Path(identifier).expanduser().resolve())
        if ir is not None:
            return ir, "file"
        # File not found, fall through to registry

    ir = _try_load_workflow_from_registry(identifier, wm)
    if ir is not None:
        return ir, "saved"

    return None, None
```

#### 5.3 Update callers of resolve_workflow

**File**: `src/pflow/cli/main.py` — find `_try_execute_named_workflow`

The current flow:
```python
workflow_ir, source = resolve_workflow(workflow_name)
# ... passes to _handle_named_workflow which checks source == "parse_error"
```

After Phase 5, `resolve_workflow` never returns `"parse_error"` — it raises instead. Remove the `source == "parse_error"` check from `_handle_workflow_not_found`.

In `_handle_workflow_not_found`, remove:
```python
if source == "parse_error":
    ctx.exit(1)
```

This line is now dead code because parse errors are exceptions.

#### Verification

```bash
make test && make check
```

Note: This phase changes error propagation. Some tests that expect `(None, "parse_error")` return values from `resolve_workflow` will need updating. Search: `grep -r "parse_error" tests/` and update assertions.

---

### Phase 6: Pipeline Restructure (main.py)

**Goal**: Replace 9+ early-exit handlers with exceptions + one catch block + one output function.

This is the largest phase. It restructures `workflow_command()` and its helpers.

#### 6.1 Convert early-exit handlers to exception raises

For each handler, replace the `click.echo() + ctx.exit(1)` pattern with an exception raise:

**`_validate_workflow_flags` (lines 924-944)**:
Replace the body with:
```python
if misplaced_flags:
    from pflow.core.user_errors import UserFriendlyError
    raise UserFriendlyError(
        title="CLI flags must come BEFORE the workflow text",
        explanation=f"Found misplaced flags: {', '.join(misplaced_flags)}",
        suggestions=[
            'pflow --verbose "analyze this data"',
            'pflow --no-trace "run without tracing"',
        ],
    )
```

**`_preprocess_run_prefix` (lines 909-921)**:
Replace the exit path with:
```python
if len(workflow) == 1:
    from pflow.core.user_errors import UserFriendlyError
    raise UserFriendlyError(
        title="Need to specify what to run",
        explanation="The 'run' command requires a workflow name.",
        suggestions=[
            "pflow <workflow-name>",
            "pflow workflow list",
        ],
    )
```

**`_handle_invalid_workflow_input` (lines 1438-1464)**:
Replace with raising `UserFriendlyError`. Three branches based on `len(workflow)`:
- Empty: title="No workflow specified", suggestions with usage examples
- Single word: title="'{word}' is not a known workflow or command", suggestions
- Multi-word: title="Invalid input: {workflow[0]} {workflow[1]} ...", suggestions

**`_show_stdin_routing_error` (lines 983-1024)**:
Use `UserFriendlyError` (NOT `WorkflowValidationError`) to preserve the rich `.pflow.md` format example in text mode:
```python
from pflow.core.user_errors import UserFriendlyError
raise UserFriendlyError(
    title="Piped input cannot be routed to workflow",
    explanation=(
        'This workflow has no input marked with "stdin": true.\n'
        'To accept piped data, add "stdin": true to one input declaration.\n\n'
        'Example (.pflow.md format):\n'
        '  ### data\n\n'
        '  Input data piped via stdin.\n\n'
        '  - type: string\n'
        '  - required: true\n'
        '  - stdin: true'
    ),
    suggestions=['Add "stdin": true to the input that should receive piped data'],
)
```

**IMPORTANT**: The binary/large stdin warning path in `_route_stdin_to_params` (the `if isinstance(stdin_data, StdinData) and (stdin_data.binary_data or stdin_data.temp_path):` branch) is a `return`, NOT an error. It must be preserved as-is — do NOT convert it to an exception raise.

**`_output_validation_errors` (lines 1027-1072)**:
Replace with:
```python
raise WorkflowValidationError(
    summary=error_summary,
    validation_errors=errors,  # list of (msg, path, suggestion) tuples
)
```

**`_validate_before_execution` (lines 643-694)**:
Replace the error branch with:
```python
if errors:
    raise WorkflowValidationError(
        summary="Workflow validation failed",
        validation_errors=[(e, "", "") for e in errors],  # errors are strings from validator
    )
```

**`_resolve_file_refs_or_exit` (lines 620-641)**:
Remove the try/except entirely. Let `FileNotFoundError` and `yaml.YAMLError` propagate. The function becomes:
```python
def _resolve_file_refs(ir_data: dict, source_file_path: str | None) -> None:
    """Resolve external file references in workflow IR."""
    if source_file_path:
        from pflow.core.file_resolver import resolve_file_references
        base_dir = Path(source_file_path).resolve().parent
        resolve_file_references(ir_data, base_dir)
```

**`_perform_validation` (lines 486-539)**:
Remove the `sys.exit(1)` in the except block. Let the exception propagate. The function returns `(errors, warnings)` on success, raises on crash.

**`_display_validation_results` (lines 542-585)**:
This is the validate-only termination. Keep it as a special case OUTSIDE the main pipeline (see 6.2).

**`_validate_and_prepare_workflow_params` (lines 1133-1184)**:
The inline param key validation (lines 1159-1161) changes to:
```python
if invalid_keys:
    raise WorkflowValidationError(
        summary="Invalid parameter names",
        validation_errors=[
            (f"Invalid parameter name(s): {', '.join(invalid_keys)}", "",
             "Parameter names cannot contain shell special characters ($, |, >, <, &, ;, etc.)")
        ],
    )
```

The `_route_stdin_to_params` call will now raise instead of calling `_show_stdin_routing_error`, so remove the separate function call and let the exception propagate.

The `_output_validation_errors` call becomes a raise (already converted above), so `prepare_inputs` errors propagate.

#### 6.2 Restructure workflow_command flow

**File**: `src/pflow/cli/main.py`

The new high-level flow for `execute_json_workflow` (or its replacement):

```python
def _execute_workflow_pipeline(ctx, workflow_ir, workflow_name, source, remaining_args, stdin_data, ...):
    """Main execution pipeline with unified error handling."""
    output_format = ctx.obj.get("output_format", "text")
    verbose = ctx.obj.get("verbose", False)
    workflow_metadata = ctx.obj.get("workflow_metadata")
    metrics_collector = None
    shared_storage = None
    workflow_trace = None
    ir_data = workflow_ir

    try:
        # Validate-only mode (exits independently)
        validate_only = ctx.obj.get("validate_only", False)
        if validate_only:
            _handle_validate_only_mode(ctx, workflow_ir, output_format, ...)
            return  # _handle_validate_only_mode calls ctx.exit()

        # Prepare params (raises WorkflowValidationError on failure)
        params = _validate_and_prepare_workflow_params(ctx, workflow_ir, remaining_args, stdin_data)

        # Setup execution context
        metrics_collector, workflow_trace = _setup_execution_context(...)

        # File reference resolution (raises FileNotFoundError on failure)
        source_file = ctx.obj.get("source_file_path")
        _resolve_file_refs(workflow_ir, source_file)

        # Pre-execution validation (raises WorkflowValidationError on failure)
        _validate_before_execution_pipeline(workflow_ir, params)

        # Execute
        result = execute_workflow(workflow_ir, params, ...)
        shared_storage = result.shared_after

        # Handle result
        if result.success:
            _handle_workflow_success(ctx, result, ...)
            if getattr(result, "status", None) == WorkflowStatus.DEGRADED:
                ctx.exit(2)
        else:
            output_error(
                ctx, result=result, output_format=output_format, verbose=verbose,
                workflow_metadata=workflow_metadata, metrics_collector=metrics_collector,
                shared_storage=shared_storage, ir_data=ir_data,
            )
            ctx.exit(1)

    except click.exceptions.Exit:
        raise  # Let Click handle its own exits

    except Exception as e:
        # Verbose traceback logging (preserves existing _handle_workflow_exception behavior)
        if verbose:
            import logging
            logging.getLogger(__name__).error(f"Workflow execution failed: {e}", exc_info=True)
        output_error(
            ctx, exception=e, output_format=output_format, verbose=verbose,
            workflow_metadata=workflow_metadata, metrics_collector=metrics_collector,
            shared_storage=shared_storage,
        )
        ctx.exit(1)

    finally:
        if workflow_trace:
            _save_trace_and_report(ctx, workflow_trace)
        _cleanup_workflow_resources(workflow_trace, stdin_data, verbose)
```

**Key changes:**
- One try/except/finally instead of scattered handlers
- `output_error()` from `error_output.py` handles both JSON and text for all exceptions
- `_handle_workflow_success` stays the same (it works)
- `_handle_workflow_error` is replaced by `output_error(result=result, ...)`
- `_handle_workflow_exception` is replaced by `output_error(exception=e, ...)`

#### 6.3 Update _try_execute_named_workflow

The caller flow changes:

```python
def _try_execute_named_workflow(ctx, workflow, stdin_data, ...):
    # NOTE: is_likely_workflow_name takes TWO args: (text, remaining_args)
    if not is_likely_workflow_name(workflow[0], workflow[1:]):
        return False

    workflow_name = workflow[0]
    remaining_args = workflow[1:]

    workflow_ir, source = resolve_workflow(workflow_name)
    # resolve_workflow now raises on parse errors, wrong extensions

    if workflow_ir is None:
        # Not found — raise with similar names
        wm = WorkflowManager()
        similar = find_similar_workflows(workflow_name, wm)
        raise WorkflowNotFoundError(workflow_name, similar_names=similar)

    # Check --help
    if "--help" in remaining_args or "-h" in remaining_args:
        _show_workflow_help(ctx, workflow_ir, workflow_name)
        return True

    # Setup metadata
    _setup_workflow_execution(ctx, workflow_name, source, ...)

    # Execute pipeline
    _execute_workflow_pipeline(ctx, workflow_ir, workflow_name, source, remaining_args, stdin_data, ...)
    return True
```

#### 6.4 Update workflow_command top level

```python
def workflow_command(ctx, ...):
    # ... setup (signals, env, context, MCP, stdin) ...

    try:
        workflow = _preprocess_run_prefix(ctx, workflow)  # raises UserFriendlyError
        _validate_workflow_flags(workflow, ctx)  # raises UserFriendlyError

        if _try_execute_named_workflow(ctx, workflow, stdin_data, ...):
            return

        # Not a workflow name — raise guidance error
        _raise_invalid_workflow_input(ctx, workflow)  # raises UserFriendlyError

    except click.exceptions.Exit:
        raise
    except Exception as e:
        output_format = "text"
        verbose = False
        if ctx.obj:
            output_format = ctx.obj.get("output_format", "text")
            verbose = ctx.obj.get("verbose", False)
        output_error(ctx, exception=e, output_format=output_format, verbose=verbose)
        ctx.exit(1)
    finally:
        # Restore logging levels (existing)
        ...
```

**Pre-initialization safety**: The outer catch safely handles errors that occur before `ctx.obj` is populated by defaulting `output_format` to `"text"`.

#### 6.5 Remove replaced functions

After wiring the pipeline, delete these functions from main.py:
- `_handle_workflow_error` (replaced by `output_error(result=...)`)
- `_handle_workflow_exception` (replaced by pipeline catch + `output_error(exception=...)`)
- `_handle_workflow_not_found` (replaced by `WorkflowNotFoundError` raise)
- `_handle_invalid_workflow_input` (replaced by `_raise_invalid_workflow_input` that raises `UserFriendlyError`)
- `_show_stdin_routing_error` (replaced by `UserFriendlyError` raise)
- `_resolve_file_refs_or_exit` (replaced by `_resolve_file_refs`)
- `_execute_workflow_and_handle_result` (absorbed into `_execute_workflow_pipeline`)

Keep (still needed):
- `_handle_workflow_success` — success output logic (unchanged)
- `_display_validation_results` — validate-only mode (special case)
- `_perform_validation` — validate-only mode (special case, but remove `sys.exit(1)` in except — let exceptions propagate to outer handler)

**IMPORTANT**: `_handle_validate_only_mode` currently calls `_resolve_file_refs_or_exit` (which is deleted). Update it to call `_resolve_file_refs` instead. Also wrap its body in try/except so file resolution errors in validate-only mode produce proper error output.

**KNOWN DIVERGENCE**: `_display_validation_results` emits `{"errors": ["string1", ...]}` (flat string list) while the unified shape requires `{"errors": [{"message": "...", "category": "..."}]}` (dict list). To unify: update `_display_validation_results` to convert its `errors: list[str]` to `[{"message": e, "category": "validation"} for e in errors]` before JSON output. Also add `"status": "failed"` and `"workflow": {"action": "unsaved"}` to match the unified shape. This is a small change (~5 lines) and eliminates the shape divergence for `--validate-only --output-format json`.

#### 6.6 Remove old error formatters from workflow_errors.py

**File**: `src/pflow/cli/workflow_errors.py`

Delete:
- `_create_json_error_output()` (lines 15-126) — replaced by `format_error_json(exception=...)`
- `_build_json_error_response()` (lines 129-178) — replaced by `format_error_json(result=...)`

Keep:
- `_display_text_error_details()` — used by `output_error()` for text-mode ExecutionResult errors
- `_display_single_error()` — called by `_display_text_error_details`
- `_display_api_error_response()` — called by `_display_single_error`
- `_display_mcp_error_details()` — called by `_display_single_error`
- `_display_shell_error_details()` — called by `_display_single_error`
- `_display_suggestion_and_compilation_context()` — called by `_display_single_error`

Update imports in workflow_errors.py — remove now-unused imports that were only used by the deleted functions.

#### Verification

```bash
make test && make check
```

This is the riskiest phase. Many tests may need updating because:
- Functions they import are deleted
- JSON error shapes change
- Error handling flow changes

Run tests frequently during implementation. Fix test failures as they arise.

---

### Phase 7: Stdout→Stderr Bug Fixes

**Goal**: Fix 4 confirmed stdout→stderr bugs.

#### 7.1 registry.py: _handle_nonexistent_path

**File**: `src/pflow/cli/commands/registry.py`

Find `_handle_nonexistent_path`. Add `err=True` to ALL `click.echo` calls (both JSON and text branches).

#### 7.2 registry.py: _handle_scan_error

**File**: `src/pflow/cli/commands/registry.py`

Find `_handle_scan_error`. Add `err=True` to the JSON branch's `click.echo`.

#### 7.3 workflow.py: filter-no-match message

**File**: `src/pflow/cli/commands/workflow.py` — around lines 48-55

Add `err=True` to the 4 `click.echo` calls that display the filter guidance message.

#### Verification

```bash
make test && make check
```

---

### Phase 8: Tests

**Goal**: Add tests for unified JSON error output and verify no regressions.

#### 8.1 Test file: `tests/test_cli/test_unified_error_output.py` (NEW)

**Pattern**: Follow `tests/test_cli/test_enhanced_error_output.py` patterns.

**Test class: `TestUnifiedErrorJsonShape`**

Each test invokes the CLI with `--output-format json`, triggers a specific error, and validates the unified JSON shape:

```python
import json
import pytest
from click.testing import CliRunner
from pflow.cli.main import main
from tests.shared.markdown_utils import write_workflow_file


class TestUnifiedErrorJsonShape:
    """All error paths produce the unified JSON shape."""

    def _assert_unified_shape(self, output: dict) -> None:
        """Assert the output conforms to the unified error JSON shape."""
        assert output["success"] is False
        assert isinstance(output["status"], str)
        assert output["status"] == "failed"
        assert isinstance(output["error"], str)  # Always a string, never a dict
        assert isinstance(output["errors"], list)
        assert len(output["errors"]) > 0
        for error in output["errors"]:
            assert isinstance(error, dict)
            assert "message" in error
            assert "category" in error
            # Verify category is from the authoritative enum
            valid_categories = {
                "validation", "compilation", "runtime", "parse_error", "not_found",
                "cli", "mcp", "max_visits", "file_not_found", "permission_denied", "unknown",
            }
            assert error["category"] in valid_categories, f"Unknown category: {error['category']}"
        assert isinstance(output["workflow"], dict)
        assert "action" in output["workflow"]
        # Removed fields must NOT appear
        assert "is_error" not in output
        assert "validation_errors" not in output
        assert "metadata" not in output
        assert "failed_node" not in output
        assert "checkpoint" not in output

    def test_file_not_found(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(tmp_path / "nonexistent.pflow.md")])
        assert result.exit_code == 1
        output = json.loads(result.output)
        self._assert_unified_shape(output)
        assert output["errors"][0]["category"] == "not_found"

    def test_parse_error(self, tmp_path):
        bad_file = tmp_path / "bad.pflow.md"
        bad_file.write_text("# Not a valid workflow\n\nJust some text")
        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(bad_file)])
        assert result.exit_code == 1
        output = json.loads(result.output)
        self._assert_unified_shape(output)
        assert output["errors"][0]["category"] == "parse_error"

    def test_validation_error(self, tmp_path):
        workflow = {
            "nodes": [{"id": "n1", "type": "unknown_type", "params": {}}],
            "edges": [],
        }
        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)
        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])
        assert result.exit_code == 1
        output = json.loads(result.output)
        self._assert_unified_shape(output)

    def test_execution_error(self, tmp_path):
        workflow = {
            "nodes": [{"id": "fail", "type": "shell", "params": {"command": "exit 1"}}],
            "edges": [],
        }
        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)
        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])
        assert result.exit_code == 1
        output = json.loads(result.output)
        self._assert_unified_shape(output)
        # NOTE: The category for shell node failures comes from executor_service._determine_error_category().
        # Run `uv run pflow --output-format json failing-shell.pflow.md` to discover the actual category
        # and update this assertion. Do NOT guess — verify against actual output.
        assert "category" in output["errors"][0]
        assert "execution" in output  # Post-execution errors have execution state

    def test_json_extension_error(self, tmp_path):
        json_file = tmp_path / "workflow.json"
        json_file.write_text("{}")
        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(json_file)])
        assert result.exit_code == 1
        output = json.loads(result.output)
        self._assert_unified_shape(output)
        assert output["errors"][0]["category"] == "not_found"
```

**Test class: `TestStructuredFieldPreservation`**

```python
class TestStructuredFieldPreservation:
    """Structured exception fields survive to JSON output."""

    def test_markdown_parse_error_preserves_fields(self, tmp_path):
        """MarkdownParseError line/suggestion fields survive to JSON.

        Use a file that reliably triggers MarkdownParseError with a line number.
        Look at markdown_parser.py to find what triggers line-numbered errors.
        """
        # A file with valid heading structure but invalid YAML in a node block
        # triggers MarkdownParseError with line number
        bad_file = tmp_path / "bad.pflow.md"
        bad_file.write_text(
            "# Workflow\n\n## Steps\n\n### node1\n\n"
            "```yaml\ntype: shell\ncommand: echo hi\n"
            "invalid yaml: [unclosed\n```\n"
        )
        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(bad_file)])
        assert result.exit_code == 1
        output = json.loads(result.output)
        assert output["success"] is False
        assert output["errors"][0]["category"] == "parse_error"

    def test_exception_to_errors_max_node_visits(self):
        """MaxNodeVisitsError structured fields survive to unified JSON."""
        from pflow.cli.error_output import _exception_to_errors
        from pflow.core.exceptions import MaxNodeVisitsError

        exc = MaxNodeVisitsError(node_id="fetch-data", visit_count=10, max_visits=5)
        summary, errors = _exception_to_errors(exc)
        assert len(errors) == 1
        assert errors[0]["category"] == "max_visits"
        assert errors[0]["node_id"] == "fetch-data"
        assert errors[0]["visit_count"] == 10
        assert errors[0]["max_visits"] == 5

    def test_exception_to_errors_validation_error(self):
        """ValidationError path/suggestion fields survive to unified JSON."""
        from pflow.cli.error_output import _exception_to_errors
        from pflow.core.ir_schema import ValidationError

        exc = ValidationError("Node references itself", path="nodes.fetch", suggestion="Remove self-reference")
        summary, errors = _exception_to_errors(exc)
        assert len(errors) == 1
        assert errors[0]["category"] == "validation"
        assert errors[0]["path"] == "nodes.fetch"
        assert errors[0]["suggestion"] == "Remove self-reference"
```

**Test class: `TestCoreRegression`**

```python
class TestCoreRegression:
    """Regression tests for the core bug: pre-execution errors producing plain text with --output-format json."""

    def test_workflow_not_found_produces_json(self, tmp_path):
        """Before Task 137, this would output plain text instead of JSON."""
        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(tmp_path / "nonexistent.pflow.md")])
        assert result.exit_code == 1
        # This is THE regression test: json.loads would raise JSONDecodeError pre-fix
        output = json.loads(result.output)
        assert output["success"] is False
        assert isinstance(output["error"], str)  # Was a dict in _create_json_error_output

    def test_error_field_is_string_not_dict(self, tmp_path):
        """Before Task 137, exception-path errors had error as a dict {type, message}."""
        runner = CliRunner()
        result = runner.invoke(main, ["--output-format", "json", str(tmp_path / "nonexistent.pflow.md")])
        output = json.loads(result.output)
        assert isinstance(output["error"], str), "error field must be a string, not a dict"
```

#### 8.2 Update existing tests

**Comprehensive list** — ALL test files needing updates:

1. **`tests/test_cli/test_dual_mode_stdin.py`**:
   - Change `output["validation_errors"]` → `output["errors"]` (key rename)
   - Change `output["validation_errors"][0].lower()` → `output["errors"][0]["message"].lower()` (items are now dicts, not strings)
   - Change `e.get("message", "")` → stays the same (already dict accessor)
   - Remove `"validation_errors" in output` assertions → `"errors" in output`

2. **`tests/test_cli/test_validation_before_execution.py`**:
   - Change `"validation_errors" in output_data or "error" in output_data` → `assert output_data["success"] is False` and `assert isinstance(output_data["errors"], list)` (remove weak `or` condition)
   - Change `"metadata"` assertions → `"workflow"`

3. **`tests/test_cli/test_enhanced_error_output.py`**:
   - Verify no `is_error` assertions (likely clean). If any exist, change to `assert output["success"] is False`

4. **`tests/test_integration/test_metrics_integration.py`**:
   - Change `output.get("is_error") is True or "error" in output` → `assert output["success"] is False` (remove weak `or` condition)

5. **`tests/test_execution/test_workflow_execution.py`**:
   - Change `assert result.action_result == "compilation_failed"` → `assert result.errors[0]["source"] == "compilation"` (already done in Phase 1.4)

6. **`tests/test_cli/test_workflow_resolution.py`** (**CRITICAL — missing from original plan**):
   - 9 sites mock `pflow.cli.main.execute_json_workflow`. After Phase 6, this function is deleted/renamed.
   - Change mock target to the new function name (e.g., `pflow.cli.main._execute_workflow_pipeline`) or to `pflow.execution.workflow_execution.execute_workflow`
   - Lines ~574-601: PermissionError and UnicodeDecodeError test assertions check for specific text messages (`"Permission denied"`, `"Unable to read file"`). After Phase 5, these exceptions propagate to `display_exception_text` which outputs `"✗ {exception}"`. Update assertions to match the new message format.

7. **`tests/test_cli/test_parse_error_handling.py`** (**CRITICAL — missing from original plan**):
   - Lines ~38, 70: Assert `"Invalid workflow syntax" in result.output`. After Phase 5, `_show_markdown_parse_error` is deleted. The error now comes from `MarkdownParseError.__str__()` via `display_exception_text`. Update assertions to match actual MarkdownParseError message text.

8. **`tests/test_cli/test_agent_ux_fixes.py`** (**CRITICAL — missing from original plan**):
   - Lines ~195, 224: Import `_execute_workflow_and_handle_result` from `pflow.cli.main`. After Phase 6.5, this function is deleted. Either update the import to the replacement function, or restructure these tests to test through the CLI runner instead of calling internal functions.

9. **`tests/test_cli/test_workflow_commands.py`** (Phase 7 verification):
   - Lines ~201-204, 318-319: After Phase 7.3 moves filter messages to stderr, use `runner = CliRunner(mix_stderr=False)` and assert on `result.stderr` instead of `result.output` to properly verify the stdout→stderr fix.

**Search commands to find additional affected tests:**
```bash
grep -r "validation_errors" tests/
grep -r "is_error" tests/
grep -r '"metadata"' tests/test_cli/
grep -r "action_result" tests/
grep -r "execute_json_workflow" tests/
grep -r "_handle_workflow_exception" tests/
grep -r "_execute_workflow_and_handle_result" tests/
grep -r "Invalid workflow syntax" tests/
grep -r "failed_node" tests/
```

#### Verification

```bash
make test && make check
```

---

## Implementation Order Summary

| Phase | Risk | What changes | Tests pass? |
|-------|------|-------------|-------------|
| 0. Dead code removal | None | Delete unused code | Yes |
| 1. Clean ExecutionResult | Low | Remove 5 fields, update ~5 tests | Yes |
| 2. Enrich exceptions | Low | Add fields/methods (additive) | Yes |
| 3. Create unified formatter | None | New file, not wired | Yes |
| 4. Fix catch sites | Low | Better exception handling | Yes |
| 5. Restructure resolution | Medium | Exceptions instead of tuples | Yes (with test updates) |
| 6. Pipeline restructure | High | Biggest change | Yes (with test updates) |
| 7. Bug fixes | Low | stdout→stderr | Yes |
| 8. Tests | None | New + updated tests | Yes |

**Critical**: Run `make test && make check` after EVERY phase. Fix failures before proceeding.

---

## Files Modified (Complete List)

| File | Phase | Changes |
|------|-------|---------|
| `src/pflow/execution/formatters/success_formatter.py` | 0 | Delete `_append_footer` |
| `src/pflow/core/user_errors.py` | 0 | Delete vestigial `CompilationError` |
| `src/pflow/execution/workflow_execution.py` | 0, 1, 4 | Remove logger, remove orphaned fields, add MaxNodeVisitsError catch |
| `src/pflow/execution/executor_service.py` | 1 | Remove 5 fields from dataclass + builder |
| `src/pflow/core/exceptions.py` | 2 | Enrich WorkflowNotFoundError, WorkflowValidationError, MaxNodeVisitsError |
| `src/pflow/core/workflow/manager.py` | 2 | Update raise sites for new constructors |
| `src/pflow/cli/error_output.py` | 3 | **NEW** — unified error output |
| `src/pflow/core/workflow/validator.py` | 4 | Catch ValidationError specifically |
| `src/pflow/runtime/workflow_executor.py` | 4 | Stop wrapping MarkdownParseError |
| `src/pflow/cli/workflow_resolution.py` | 5 | Raise instead of return error tuples |
| `src/pflow/cli/main.py` | 6 | Pipeline restructure, remove old handlers |
| `src/pflow/cli/workflow_errors.py` | 6 | Delete 2 JSON builders |
| `src/pflow/cli/commands/registry.py` | 7 | stdout→stderr fixes |
| `src/pflow/cli/commands/workflow.py` | 7 | stdout→stderr fix |
| `src/pflow/execution/CLAUDE.md` | 1 | Update ExecutionResult field documentation |
| `src/pflow/cli/CLAUDE.md` | 6 | Update error pipeline documentation |
| `tests/test_cli/test_unified_error_output.py` | 8 | **NEW** — unified shape + regression + structured field tests |
| `tests/test_runtime/test_checkpoint_tracking.py` | 1 | Remove `output_data=None` |
| `tests/test_cli/test_workflow_output_handling.py` | 1 | Remove `output_data=None` |
| `tests/test_execution/test_workflow_execution.py` | 1 | Update action_result assertions |
| `tests/test_cli/test_dual_mode_stdin.py` | 8 | Update JSON field assertions + accessor types |
| `tests/test_cli/test_validation_before_execution.py` | 8 | Remove weak `or` conditions, update field names |
| `tests/test_cli/test_enhanced_error_output.py` | 8 | Update if needed |
| `tests/test_integration/test_metrics_integration.py` | 8 | Change `is_error` → `success is False` |
| `tests/test_cli/test_workflow_resolution.py` | 5, 6, 8 | Update 9 mock targets, update error message assertions |
| `tests/test_cli/test_parse_error_handling.py` | 5, 8 | Update "Invalid workflow syntax" assertions |
| `tests/test_cli/test_agent_ux_fixes.py` | 6, 8 | Update deleted function imports |
| `tests/test_cli/test_workflow_commands.py` | 7, 8 | Add `mix_stderr=False` for stderr verification |

---

## Verification Checklist

```bash
# 1. All tests pass
make test && make check

# 2. All error paths produce valid JSON with unified structure
uv run pflow --output-format json nonexistent.pflow.md
uv run pflow --output-format json malformed.pflow.md
echo "data" | uv run pflow --output-format json workflow-no-stdin.pflow.md
uv run pflow --output-format json bad-node-workflow.pflow.md
uv run pflow --output-format json failing-workflow.pflow.md

# 3. All outputs parseable with same jq query
# jq '.success, .status, .error, .errors[0].message, .workflow'

# 4. Text mode unchanged (visually compare with pre-refactor output)
uv run pflow failing-workflow.pflow.md
uv run pflow nonexistent.pflow.md

# 5. No old field names in JSON output
# Verify: no "is_error", no "validation_errors", no "metadata" key, no dict-type "error"

# 6. MCP server unaffected
# Run MCP server tests: pytest tests/test_mcp_server/

# 7. Registry run unaffected
# Run registry tests: pytest tests/test_cli/ -k "registry"
```
