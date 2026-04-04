# Task 143: Unified Diagnostic System — Implementation Plan

## Context

pflow generates diagnostics at multiple stages (parse, validate, execute) and surfaces them through multiple channels (CLI text, CLI JSON, MCP). Today this is fragmented across 3 incompatible warning types (`list[str]`, `ValidationWarning` dataclass, ad-hoc `dict`s) and inconsistent error dict shapes. This causes:

- Parser warnings silently dropped at all call sites (#209)
- Two merge sites combining `warnings` + `validation_warnings` on every result
- Duplicate display code (4 warning render sites, 2 error render paths)
- `format_for_cli()` methods on exceptions duplicating rendering logic

**Solution**: One `Diagnostic` dataclass. One list on `ExecutionResult`. One shared render function. Fixes #209, eliminates all duplicated formatting, and makes every diagnostic agent-actionable with a `suggestion` field.

**Pre-implementation state**: `make test` = 4513 passed, `make check` = clean. Branch: `feat/unified-diagnostic-system`. Base: `15eee95e`.

---

## Phase 1: Create the Diagnostic Type

**New file**: `src/pflow/core/diagnostic.py`

Zero imports from pflow modules — pure leaf module. No circular import risk.

### 1.1 Diagnostic dataclass

```python
"""Unified diagnostic type for all pflow warnings and errors."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(Enum):
    """Diagnostic severity levels."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Diagnostic:
    """Single type for all pflow diagnostics (warnings, errors, info).

    Identity is based on (severity, source, node_id, message) — context is
    excluded because it is mutable enrichment data that may differ between
    otherwise-identical diagnostics.
    """

    severity: Severity
    message: str
    suggestion: str | None = None
    node_id: str | None = None
    source: str = ""  # "parser" | "validator" | "runtime" | "compilation"
    context: dict[str, Any] | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Diagnostic):
            return NotImplemented
        return (
            self.severity == other.severity
            and self.source == other.source
            and self.node_id == other.node_id
            and self.message == other.message
        )

    def __hash__(self) -> int:
        return hash((self.severity, self.source, self.node_id, self.message))

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output and trace files."""
        d: dict[str, Any] = {
            "severity": self.severity.value,
            "message": self.message,
            "source": self.source,
        }
        if self.suggestion is not None:
            d["suggestion"] = self.suggestion
        if self.node_id is not None:
            d["node_id"] = self.node_id
        if self.context:
            d["context"] = self.context
        return d

    def to_display_dict(self) -> dict[str, Any]:
        """Serialize for display consumers that read flat dict keys.

        Merges context keys into the top level for backward-compatible
        display code (workflow_errors.py, workflow_output.py).
        """
        d = self.to_dict()
        if self.context:
            # Merge context into top level for display consumers
            for key, value in self.context.items():
                if key not in d:
                    d[key] = value
        return d
```

### 1.2 format_diagnostic() function

In the same file:

```python
def format_diagnostic(d: Diagnostic, verbose: bool = False) -> str:
    """Render a single diagnostic as text.

    Handles both simple warnings (one line) and rich errors (multi-line
    with enrichment from context).
    """
    if d.severity == Severity.ERROR:
        return _format_error_diagnostic(d, verbose)
    return _format_warning_diagnostic(d)


def _format_warning_diagnostic(d: Diagnostic) -> str:
    """Format a WARNING or INFO diagnostic as a single line."""
    if d.node_id:
        line = f"  ⚠ [{d.node_id}] {d.message}"
    else:
        line = f"  ⚠ {d.message}"
    if d.suggestion:
        line += f"\n    → {d.suggestion}"
    return line


def _format_error_diagnostic(d: Diagnostic, verbose: bool = False) -> str:
    """Format an ERROR diagnostic with full context rendering.

    This produces the text that replaces format_for_cli() on exception classes.
    The rendering is driven by the source and context fields.
    """
    ctx = d.context or {}
    source = d.source

    # WorkflowNotFoundError pattern
    if ctx.get("category") == "not_found":
        return _format_not_found(d, ctx)

    # WorkflowValidationError pattern — individual error from the list
    if source == "validation" and ctx.get("path"):
        parts = [f"❌ {d.message}"]
        if ctx["path"] != "root":
            parts.append(f"   At: {ctx['path']}")
        if d.suggestion:
            parts.append(f"   👉 {d.suggestion}")
        return "\n".join(parts)

    # UserFriendlyError pattern
    if ctx.get("title"):
        return _format_user_friendly(d, ctx, verbose)

    # MaxNodeVisitsError pattern
    if ctx.get("category") == "max_visits":
        return f"❌ {d.message}"

    # Simple errors (FileNotFoundError, PermissionError, generic)
    if d.suggestion:
        return f"✗ {d.message}\n    → {d.suggestion}"
    return f"✗ {d.message}"


def _format_not_found(d: Diagnostic, ctx: dict[str, Any]) -> str:
    """Format WorkflowNotFoundError diagnostic."""
    # If there's a hint in the message (from WorkflowNotFoundError.hint), use it directly
    if ctx.get("hint"):
        return f"❌ {ctx['hint']}"
    workflow_name = ctx.get("workflow_name", "unknown")
    lines = [f"❌ Workflow '{workflow_name}' not found."]
    similar = ctx.get("similar_names", [])
    if similar:
        lines.append("\nDid you mean one of these?")
        for name in similar:
            lines.append(f"  - {name}")
    else:
        lines.append("\nUse 'pflow workflow list' to see available workflows.")
    return "\n".join(lines)


def _format_user_friendly(d: Diagnostic, ctx: dict[str, Any], verbose: bool) -> str:
    """Format UserFriendlyError diagnostic (title/explanation/suggestions pattern)."""
    lines = [f"Error: {ctx['title']}", ""]
    if ctx.get("explanation"):
        lines.append(ctx["explanation"])
        lines.append("")

    suggestions = ctx.get("suggestions", [])
    if d.suggestion:
        # suggestion field holds the joined suggestions
        suggestions_list = suggestions if suggestions else [d.suggestion]
    else:
        suggestions_list = suggestions

    if suggestions_list:
        if len(suggestions_list) == 1:
            lines.append("To fix this:")
            lines.append(f"  {suggestions_list[0]}")
        else:
            lines.append("To fix this:")
            for i, s in enumerate(suggestions_list, 1):
                lines.append(f"  {i}. {s}")
        lines.append("")

    if verbose and ctx.get("technical_details"):
        lines.append("Technical details:")
        lines.append(ctx["technical_details"])
        lines.append("")
    elif not verbose and ctx.get("technical_details"):
        lines.append("Run with --verbose for technical details.")

    return "\n".join(lines).strip()
```

### 1.3 exception_to_diagnostics() function

In the same file. This is the shared conversion function that replaces BOTH `_exception_to_result()` error dict building in runner.py AND `_exception_to_errors()` in error_output.py.

```python
def exception_to_diagnostics(exc: Exception) -> list[Diagnostic]:
    """Convert any exception to a list of Diagnostics.

    Shared by the runner (execution boundary) and CLI (pre-runner boundary).
    Handles the _pflow_node_id annotation set by the engine.
    """
    from pflow.core.exceptions import (
        CompilationError,
        MarkdownParseError,
        MaxNodeVisitsError,
        SchemaValidationError,
        WorkflowNotFoundError,
        WorkflowValidationError,
    )
    from pflow.core.user_errors import MCPError, OutputResolutionError, UserFriendlyError

    annotated_node_id = getattr(exc, "_pflow_node_id", None)

    if isinstance(exc, CompilationError):
        return [Diagnostic(
            severity=Severity.ERROR,
            message=getattr(exc, "raw_message", str(exc)),
            suggestion=exc.suggestion,
            node_id=exc.node_id,
            source="compilation",
            context={
                "category": "compilation",
                "phase": exc.phase,
                "node_type": exc.node_type,
                "sub_workflow_path": (exc.details or {}).get("sub_workflow_path"),
            },
        )]

    if isinstance(exc, MaxNodeVisitsError):
        return [Diagnostic(
            severity=Severity.ERROR,
            message=str(exc),
            suggestion="Set PFLOW_MAX_NODE_VISITS to increase the limit if this is intentional.",
            node_id=exc.node_id,
            source="runtime",
            context={
                "category": "max_visits",
                "visit_count": exc.visit_count,
                "max_visits": exc.max_visits,
            },
        )]

    if isinstance(exc, WorkflowValidationError):
        # Produces MULTIPLE diagnostics, one per validation error
        diagnostics: list[Diagnostic] = []
        for err in exc.validation_errors:
            if isinstance(err, tuple) and len(err) >= 3:
                msg, path, suggestion = err[0], err[1], err[2]
                ctx: dict[str, Any] = {"category": "validation"}
                if path and path != "root":
                    ctx["path"] = path
                diagnostics.append(Diagnostic(
                    severity=Severity.ERROR,
                    message=msg,
                    suggestion=suggestion or None,
                    source="validation",
                    context=ctx,
                ))
            else:
                diagnostics.append(Diagnostic(
                    severity=Severity.ERROR,
                    message=str(err),
                    source="validation",
                    context={"category": "validation"},
                ))
        return diagnostics if diagnostics else [Diagnostic(
            severity=Severity.ERROR,
            message=str(exc),
            source="validation",
            context={"category": "validation"},
        )]

    if isinstance(exc, SchemaValidationError):
        ctx = {"category": "validation"}
        if exc.path:
            ctx["path"] = exc.path
        return [Diagnostic(
            severity=Severity.ERROR,
            message=exc.message,
            suggestion=exc.suggestion or None,
            source="validation",
            context=ctx,
        )]

    if isinstance(exc, MarkdownParseError):
        ctx = {"category": "parse_error"}
        if exc.line is not None:
            ctx["line"] = exc.line
        return [Diagnostic(
            severity=Severity.ERROR,
            message=str(exc),
            suggestion=exc.suggestion,
            node_id=annotated_node_id,
            source="parser",
            context=ctx,
        )]

    if isinstance(exc, WorkflowNotFoundError):
        suggestion = None
        if exc.similar_names:
            suggestion = f"Did you mean: {', '.join(exc.similar_names)}"
        return [Diagnostic(
            severity=Severity.ERROR,
            message=str(exc),
            suggestion=suggestion,
            source="runtime",
            context={
                "category": "not_found",
                "workflow_name": exc.workflow_name,
                "similar_names": exc.similar_names,
                "hint": exc.hint,
            },
        )]

    # MCPError before UserFriendlyError (subclass check order)
    if isinstance(exc, OutputResolutionError):
        diagnostics = []
        for failure in exc.failures:
            diag_msgs = failure.get("diagnostics", [])
            msg = "; ".join(diag_msgs) if diag_msgs else str(exc)
            ctx = {"category": "runtime"}
            if failure.get("output_name"):
                ctx["output_name"] = failure["output_name"]
            if failure.get("source_expr"):
                ctx["source_expr"] = failure["source_expr"]
            diagnostics.append(Diagnostic(
                severity=Severity.ERROR,
                message=msg,
                source="runtime",
                context=ctx,
            ))
        if not diagnostics:
            diagnostics = [Diagnostic(
                severity=Severity.ERROR,
                message=exc.explanation,
                source="runtime",
                context={"category": "runtime"},
            )]
        return diagnostics

    if isinstance(exc, MCPError):
        suggestion = "; ".join(exc.suggestions) if exc.suggestions else None
        return [Diagnostic(
            severity=Severity.ERROR,
            message=exc.explanation,
            suggestion=suggestion,
            source="runtime",
            context={
                "category": "mcp",
                "title": exc.title,
                "explanation": exc.explanation,
                "suggestions": exc.suggestions,
                "technical_details": exc.technical_details,
            },
        )]

    if isinstance(exc, UserFriendlyError):
        suggestion = "; ".join(exc.suggestions) if exc.suggestions else None
        return [Diagnostic(
            severity=Severity.ERROR,
            message=exc.explanation,
            suggestion=suggestion,
            source="runtime",
            context={
                "category": "cli",
                "title": exc.title,
                "explanation": exc.explanation,
                "suggestions": exc.suggestions,
                "technical_details": exc.technical_details,
            },
        )]

    if isinstance(exc, FileNotFoundError):
        return [Diagnostic(
            severity=Severity.ERROR,
            message=str(exc),
            source="runtime",
            context={"category": "file_not_found"},
        )]

    if isinstance(exc, PermissionError):
        msg = str(exc) if str(exc) else "Permission denied"
        return [Diagnostic(
            severity=Severity.ERROR,
            message=msg,
            source="runtime",
            context={"category": "permission_denied"},
        )]

    if isinstance(exc, ValueError):
        ctx = {}
        if annotated_node_id:
            ctx["category"] = "execution_failure"
            return [Diagnostic(
                severity=Severity.ERROR,
                message=str(exc),
                node_id=annotated_node_id,
                source="runtime",
                context=ctx,
            )]
        else:
            ctx["category"] = "validation"
            return [Diagnostic(
                severity=Severity.ERROR,
                message=str(exc),
                source="runtime",
                context=ctx,
            )]

    # Generic fallback
    ctx: dict[str, Any] = {
        "category": "execution_failure",
        "exception_type": type(exc).__name__,
    }
    return [Diagnostic(
        severity=Severity.ERROR,
        message=str(exc),
        node_id=annotated_node_id,
        source="runtime",
        context=ctx,
    )]


def deduplicate_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Remove duplicate diagnostics preserving order."""
    seen: set[Diagnostic] = set()
    result: list[Diagnostic] = []
    for d in diagnostics:
        if d not in seen:
            seen.add(d)
            result.append(d)
    return result
```

### 1.4 Verification

After Phase 1: `make check` and `make test` should pass — no existing code imports from this new file yet.

---

## Phase 2: Update Result Types

### 2.1 `src/pflow/execution/result.py`

Add `diagnostics` field to `ExecutionResult` and `ValidationResult`. Add `diagnostics` field to `ResolvedWorkflow`. Keep old fields during transition — they become properties in Phase 8.

```python
# Add import at top
from pflow.core.diagnostic import Diagnostic, Severity

# ResolvedWorkflow — add diagnostics field (frozen=True, so use tuple)
@dataclass(frozen=True)
class ResolvedWorkflow:
    ir: dict[str, Any]
    source: str
    file_path: Optional[str] = None
    diagnostics: tuple[Diagnostic, ...] = ()  # Parser diagnostics

# ValidationResult — add diagnostics field
@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)  # NEW

# ExecutionResult — add diagnostics field
@dataclass
class ExecutionResult:
    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    validation_warnings: list[dict[str, Any]] = field(default_factory=list)
    trace: Optional[Any] = None
    metrics: Optional[Any] = None
    diagnostics: list[Diagnostic] = field(default_factory=list)  # NEW
```

### 2.2 Verification

`make test` and `make check` pass — we only added fields with defaults.

---

## Phase 3: Convert Warning Producers

### 3.1 Parser warnings → Diagnostic

**File**: `src/pflow/core/markdown_parser.py`

Add import at top (alongside existing imports):
```python
from pflow.core.diagnostic import Diagnostic, Severity
```

Change `MarkdownParseResult.warnings` type:
```python
warnings: list[Diagnostic] = field(default_factory=list)
```

Change `_resolve_section()` return and warning creation at line ~308-320:
```python
# In _resolve_section() (line ~572):
# OLD:
#   warning = f"Line {line_num}: '## {section_name}' looks like a typo — did you mean '## {expected}'?"
# NEW:
warning = Diagnostic(
    severity=Severity.WARNING,
    source="parser",
    message=f"Line {line_num}: '## {section_name}' looks like a typo for '## {expected}'.",
    suggestion=f"Rename to '## {expected}'.",
)
```

Change orphaned content warning at line ~430:
```python
# OLD:
# warnings.append(f"Unparsed content in '{section_name}' section ({line_ref}). ...")
# NEW:
warnings.append(Diagnostic(
    severity=Severity.WARNING,
    source="parser",
    message=f"Unparsed content in '{section_name}' section ({line_ref}). Content before the first ### heading is not captured.",
    suggestion="Move content under a ### heading, or remove it.",
))
```

**Note**: `_resolve_section()` returns `tuple[_SectionType, bool, str | None]`. Change the third element to `Diagnostic | None`. Update the type annotation and the caller at line ~319 (`if warning: warnings.append(warning)`).

### 3.2 Validator template warnings → Diagnostic

**File**: `src/pflow/runtime/template_validation/path_validation.py`

Add import:
```python
from pflow.core.diagnostic import Diagnostic, Severity
```

Change both `ValidationWarning` creation sites:

**Site 1** (line ~181):
```python
# OLD: warning = ValidationWarning(node_id=..., message="Array access...", template=...)
# NEW:
warning = Diagnostic(
    severity=Severity.WARNING,
    source="validator",
    node_id=output_info.get("node_id", "unknown"),
    message=f"Array access on '{output_type}' requires valid JSON array at runtime. Non-JSON strings cause 'Unresolved variables' error.",
    suggestion="Ensure the value is a valid JSON array at runtime.",
    context={"template": template if template.startswith("${") else f"${{{template}}}"},
)
```

**Site 2** (line ~292):
```python
# OLD: warning = ValidationWarning(node_id=..., message="Nested access...", template=...)
# NEW:
warning = Diagnostic(
    severity=Severity.WARNING,
    source="validator",
    node_id=output_info.get("node_id", "unknown"),
    message=f"Nested access on '{output_type}' requires valid JSON at runtime. Non-JSON strings cause 'Unresolved variables' error.",
    suggestion="Ensure the value is valid JSON at runtime.",
    context={"template": full_template if full_template.startswith("${") else f"${{{full_template}}}"},
)
```

**Return type changes** in both `validate_template_path()` and `validate_nested_path()`:
- Change `tuple[bool, Optional[ValidationWarning]]` to `tuple[bool, Optional[Diagnostic]]`
- Update all callers in the same file

**File**: `src/pflow/runtime/template_validation/validator.py`

Change import:
```python
# OLD: from pflow.runtime.template_validation.utils import ValidationWarning, get_node_ids
# NEW:
from pflow.core.diagnostic import Diagnostic, Severity
from pflow.runtime.template_validation.utils import get_node_ids
```

Change type annotations:
```python
# validate_workflow_templates return type:
# OLD: tuple[list[str], list[ValidationWarning]]
# NEW: tuple[list[str], list[Diagnostic]]

# Internal warnings list:
# OLD: warnings: list[ValidationWarning] = []
# NEW: warnings: list[Diagnostic] = []
```

Change `__all__`:
```python
__all__ = ["extract_node_outputs", "validate_workflow_templates"]
```
(Remove `ValidationWarning` from exports — it's now imported from `core.diagnostic`)

### 3.3 Cache lint warnings → Diagnostic

**File**: `src/pflow/core/workflow/validator.py`

Change import:
```python
# OLD: from pflow.runtime.template_validation import ValidationWarning
# NEW: from pflow.core.diagnostic import Diagnostic, Severity
```

Change `_warn_inputless_shell_nodes()`:
```python
# Return type: list[Diagnostic]
# Internal list: warnings: list[Diagnostic] = []
# Warning creation:
warnings.append(Diagnostic(
    severity=Severity.WARNING,
    source="validator",
    node_id=node["id"],
    message="Shell node has no template inputs — cached results will persist across runs. Consider '- cache: false' if this node reads runtime state (git, env, filesystem).",
    suggestion="Add '- cache: false' if this node reads runtime state (git, env, filesystem).",
))
```

Change `validate()` return type:
```python
# OLD: tuple[list[str], list[ValidationWarning]]
# NEW: tuple[list[str], list[Diagnostic]]
```

Change internal type annotations for `warnings`:
```python
# OLD: warnings: list[ValidationWarning] = []
# NEW: warnings: list[Diagnostic] = []
```

### 3.4 `__init__.py` for template_validation

**File**: `src/pflow/runtime/template_validation/__init__.py`

Remove `ValidationWarning` from imports and `__all__`:
```python
from pflow.runtime.template_validation.utils import (
    MAX_DISPLAYED_FIELDS,
    flatten_output_structure,
    sanitize_for_display,
    split_template_path,
)
from pflow.runtime.template_validation.validator import (
    extract_node_outputs,
    validate_workflow_templates,
)

__all__ = [
    "MAX_DISPLAYED_FIELDS",
    "extract_node_outputs",
    "flatten_output_structure",
    "sanitize_for_display",
    "split_template_path",
    "validate_workflow_templates",
]
```

### 3.5 Runner bridge — `_warning_to_dict()`

**File**: `src/pflow/execution/runner.py`

Update `_warning_to_dict()` to handle Diagnostic objects:
```python
@staticmethod
def _warning_to_dict(warning: Any) -> dict[str, Any]:
    """Convert ValidationWarning or Diagnostic to agent-facing dict."""
    if isinstance(warning, dict):
        return warning
    # Handle Diagnostic objects
    if hasattr(warning, "to_dict"):
        d = warning.to_dict()
        # Preserve backward-compatible keys for display consumers
        if warning.context and "template" in warning.context:
            d["template"] = warning.context["template"]
        # Map source to type for legacy display format
        if "type" not in d and hasattr(warning, "source"):
            d["type"] = warning.source or "warning"
        return d
    return {
        "node_id": getattr(warning, "node_id", None),
        "template": getattr(warning, "template", None),
        "message": getattr(warning, "message", str(warning)),
    }
```

### 3.6 Verification

`make test` — some tests in `test_warnings.py` may need updating if they assert on `ValidationWarning` class. Fix those:

**File**: `tests/test_runtime/test_template_validation/test_warnings.py`
- Change assertions from `isinstance(w, ValidationWarning)` to `isinstance(w, Diagnostic)`
- Change field access from `w.template` to `w.context.get("template")`
- Import `Diagnostic` from `pflow.core.diagnostic`

---

## Phase 4: Convert Error Producers

### 4.1 Runtime warning extraction → Diagnostic

**File**: `src/pflow/execution/runner.py`

Add import:
```python
from pflow.core.diagnostic import Diagnostic, Severity, exception_to_diagnostics, deduplicate_diagnostics
```

Replace `_extract_runtime_warnings()`:
```python
def _extract_runtime_warnings(self, shared_store: dict[str, Any]) -> list[Diagnostic]:
    """Extract runtime warnings from shared store as Diagnostics."""
    warnings: list[Diagnostic] = []
    for node_id, message in shared_store.get("__warnings__", {}).items():
        warnings.append(Diagnostic(
            severity=Severity.WARNING,
            source="runtime",
            node_id=node_id,
            message=message,
            suggestion="Check the API response for details. The workflow continued but results may be incomplete.",
        ))
    for node_id, error_data in shared_store.get("__template_errors__", {}).items():
        warnings.append(Diagnostic(
            severity=Severity.WARNING,
            source="runtime",
            node_id=node_id,
            message=error_data.get("message", "Template resolution failed"),
            suggestion="Check template syntax: ${node.output}. Ensure referenced nodes have executed.",
            context={"unresolved_templates": error_data.get("unresolved", [])},
        ))
    return warnings
```

### 4.2 `_exception_to_result()` → use shared conversion

**File**: `src/pflow/execution/runner.py`

Replace the entire body of `_exception_to_result()`:
```python
def _exception_to_result(
    self,
    exception: Exception,
    start_time: float,
    trace_collector: Any,
    validation_warnings: list[Any] | None = None,
) -> ExecutionResult:
    """Convert any exception to ExecutionResult."""
    error_diagnostics = exception_to_diagnostics(exception)

    # Convert validation warnings to Diagnostic if they aren't already
    val_diags: list[Diagnostic] = []
    for w in (validation_warnings or []):
        if isinstance(w, Diagnostic):
            val_diags.append(w)
        else:
            val_diags.append(Diagnostic(
                severity=Severity.WARNING,
                source="validator",
                node_id=getattr(w, "node_id", None),
                message=getattr(w, "message", str(w)),
            ))

    all_diagnostics = error_diagnostics + val_diags

    # Derive legacy fields FROM diagnostics (single source of truth)
    return ExecutionResult(
        success=False,
        status=WorkflowStatus.FAILED,
        errors=[d.to_display_dict() for d in all_diagnostics if d.severity == Severity.ERROR],
        warnings=[],  # No runtime warnings on exception path
        validation_warnings=[d.to_dict() for d in all_diagnostics if d.severity == Severity.WARNING],
        trace=trace_collector,
        diagnostics=all_diagnostics,
    )
```

### 4.3 `_compile_and_execute()` — populate diagnostics

**File**: `src/pflow/execution/runner.py`

In the success path return (line ~223-232), build the diagnostics list:
```python
    # Convert validation warnings to Diagnostic
    val_diags: list[Diagnostic] = []
    for w in validation_warnings:
        if isinstance(w, Diagnostic):
            val_diags.append(w)
        else:
            val_diags.append(Diagnostic(
                severity=Severity.WARNING,
                source="validator",
                node_id=getattr(w, "node_id", None),
                message=getattr(w, "message", str(w)),
            ))

    runtime_warnings = self._extract_runtime_warnings(shared_store)

    # Build error diagnostics for failed executions
    error_diagnostics: list[Diagnostic] = []
    if not success:
        from .executor_service import build_error_list
        error_list = build_error_list(success, action_result, shared_store)
        for err in error_list:
            error_diagnostics.append(Diagnostic(
                severity=Severity.ERROR,
                source=err.get("source", "runtime"),
                node_id=err.get("node_id"),
                message=err.get("message", "Unknown error"),
                context={k: v for k, v in err.items() if k not in ("source", "node_id", "message", "suggestion")},
            ))

    all_diagnostics = deduplicate_diagnostics(error_diagnostics + runtime_warnings + val_diags)

    trace_collector = shared_store.get("_trace_collector", trace_collector)
    if trace_collector:
        trace_collector.set_warnings([d.to_dict() for d in runtime_warnings])

    # Derive legacy fields FROM diagnostics (single source of truth)
    return ExecutionResult(
        success=success,
        status=status,
        shared_after=shared_store,
        errors=[d.to_display_dict() for d in all_diagnostics if d.severity == Severity.ERROR],
        warnings=[d.to_dict() for d in all_diagnostics if d.source == "runtime" and d.severity == Severity.WARNING],
        validation_warnings=[d.to_dict() for d in all_diagnostics if d.source in ("validator", "parser") and d.severity == Severity.WARNING],
        trace=trace_collector,
        metrics=metrics_collector,
        diagnostics=all_diagnostics,
    )
```

### 4.4 `validate()` — populate diagnostics on ValidationResult

**File**: `src/pflow/execution/runner.py`

In the `validate()` method, after building `ValidationResult` (line ~285-289):
```python
    val_diags: list[Diagnostic] = []
    for w in warnings:
        if isinstance(w, Diagnostic):
            val_diags.append(w)
        else:
            val_diags.append(Diagnostic(
                severity=Severity.WARNING,
                source="validator",
                node_id=getattr(w, "node_id", None),
                message=getattr(w, "message", str(w)),
            ))

    error_diags = [Diagnostic(
        severity=Severity.ERROR,
        message=e,
        source="validation",
        context={"category": "validation"},
    ) for e in errors]

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=[self._warning_to_dict(w) for w in warnings],
        diagnostics=error_diags + val_diags,
    )
```

And update the exception catch blocks to also populate diagnostics:
```python
except (...) as e:
    return ValidationResult(
        valid=False,
        errors=[str(e)],
        warnings=[],
        diagnostics=exception_to_diagnostics(e),
    )
```

### 4.5 Verification

`make test` — the old fields are still populated, so all existing tests pass. The new `diagnostics` field is populated in parallel.

---

## Phase 5: Update Display Consumers

### 5.1 CLI error_output.py — use shared exception_to_diagnostics

**File**: `src/pflow/cli/error_output.py`

Add imports:
```python
from pflow.core.diagnostic import Diagnostic, Severity, exception_to_diagnostics, format_diagnostic
```

Replace `display_exception_text()`:
```python
def display_exception_text(exception: Exception, verbose: bool = False) -> None:
    """Display exception in text mode using Diagnostic rendering."""
    diagnostics = exception_to_diagnostics(exception)
    for d in diagnostics:
        click.echo(format_diagnostic(d, verbose=verbose), err=True)
```

Replace `_exception_to_errors()` and all helper functions with:
```python
def _exception_to_errors(exception: Exception) -> tuple[str, list[dict[str, Any]]]:
    """Convert any exception to (summary, errors_list) for unified JSON.

    Uses shared exception_to_diagnostics() for the conversion.
    """
    diagnostics = exception_to_diagnostics(exception)
    errors_list = [d.to_display_dict() for d in diagnostics]

    # Derive summary
    if len(diagnostics) == 1:
        summary = diagnostics[0].message
    else:
        summary = f"Workflow failed ({len(diagnostics)} errors)"

    return summary, errors_list
```

Delete all the per-exception helper functions:
- `_workflow_validation_to_errors`
- `_workflow_not_found_to_errors`
- `_mcp_error_to_errors`
- `_output_resolution_to_errors`
- `_user_friendly_to_errors`
- `_markdown_parse_to_errors`
- `_schema_validation_to_errors`

### 5.2 CLI commands/registry_run.py — replace format_for_cli call

**File**: `src/pflow/cli/commands/registry_run.py`

Line ~310 calls `e.format_for_cli(verbose=verbose)` on `MCPError`. Replace with:
```python
from pflow.core.diagnostic import exception_to_diagnostics, format_diagnostic
diagnostics = exception_to_diagnostics(e)
for d in diagnostics:
    click.echo(format_diagnostic(d, verbose=verbose), err=True)
```

### 5.3 CLI workflow_errors.py — read from Diagnostic

**File**: `src/pflow/cli/workflow_errors.py`

The `_display_single_error()` and `_display_text_error_details()` functions currently read from error dicts with top-level keys. During transition (Phase 5), `result.errors` still contains legacy dicts. These functions continue to work as-is since the legacy dicts contain all the same keys.

No changes needed yet — the legacy error dicts in `result.errors` maintain backward compatibility.

### 5.3 CLI main.py — use diagnostics for merge

**File**: `src/pflow/cli/main.py`

In `_handle_workflow_success()`, change the warning merge (line ~148).
Since legacy fields are derived FROM diagnostics (see Phase 4), there is no dual-source-of-truth — `result.warnings + result.validation_warnings` already matches `diagnostics`. So simply replace the merge with the legacy concat (it's already consistent):
```python
# OLD:
# result_warnings = getattr(result, "warnings", []) + getattr(result, "validation_warnings", [])

# NEW: Legacy fields are derived from diagnostics, so this stays simple
result_warnings = getattr(result, "warnings", []) + getattr(result, "validation_warnings", [])
# (In Phase 8 this becomes: [d.to_dict() for d in result.warnings])
```

In `_display_validation_result()`, use `format_diagnostic()` for warnings (line ~409-417):
```python
# In the valid branch, after showing success:
from pflow.core.diagnostic import Severity, format_diagnostic
if vresult.diagnostics:
    warning_diags = [d for d in vresult.diagnostics if d.severity == Severity.WARNING]
    for d in warning_diags:
        click.echo(format_diagnostic(d), err=True)
# No legacy fallback needed — diagnostics is always populated from Phase 4 onward
```

For JSON validation output, include diagnostics:
```python
if output_format == "json":
    output = {
        "success": vresult.valid,
        "validated_only": True,
        "errors": [{"message": e, "category": "validation"} for e in vresult.errors],
        "warnings": [d.to_dict() for d in vresult.diagnostics if d.severity == Severity.WARNING],
        "diagnostics": [d.to_dict() for d in vresult.diagnostics],
    }
    click.echo(json.dumps(output, indent=2, default=str))
```

### 5.4 MCP execution_service.py — use diagnostics for merge

**File**: `src/pflow/mcp_server/services/execution_service.py`

In `_format_success_result()` (line ~70), legacy fields are derived from diagnostics (Phase 4), so the existing concat still works during transition:
```python
# No change needed during transition — result.warnings + result.validation_warnings
# is already derived from diagnostics. In Phase 8, change to:
# warnings=[d.to_dict() for d in result.warnings]
```

In `validate_workflow()` (line ~269-280), use `format_diagnostic()`:
```python
from pflow.core.diagnostic import Severity, format_diagnostic
if vresult.diagnostics:
    warning_diags = [d for d in vresult.diagnostics if d.severity == Severity.WARNING]
    if warning_diags:
        warning_text = "\n".join(format_diagnostic(d) for d in warning_diags)
        msg += f"\n\nWarnings:\n{warning_text}"
# No legacy fallback — diagnostics is always populated from Phase 4 onward
```

### 5.5 Success formatter — handle Diagnostic dicts

**File**: `src/pflow/execution/formatters/success_formatter.py`

The `format_execution_success()` function receives `warnings` as a `list[dict]`. With diagnostics, callers pass `[d.to_dict() for d in warnings_diagnostics]`. The dict shape changes slightly — now has `severity`, `source`, `suggestion` keys instead of `type`, `template`.

Update `format_success_as_text()` warning rendering (lines 234-250) to handle both formats:
```python
warnings = success_dict.get("warnings", [])
if warnings:
    lines.append("")
    lines.append("⚠️ Warnings:")
    for warning in warnings:
        node_id = warning.get("node_id", "unknown")
        # Support both legacy "type" key and new "source" key
        warning_type = warning.get("type") or warning.get("source", "warning")
        message = warning.get("message", "No message")
        lines.append(f"  • {node_id} ({warning_type}):")
        for line in message.split("\n"):
            if line.strip():
                lines.append(f"    {line}")
        # Show suggestion if present (new Diagnostic feature)
        if suggestion := warning.get("suggestion"):
            lines.append(f"    → {suggestion}")
```

Apply the same change to `_display_execution_summary()` in `src/pflow/cli/workflow_output.py` (lines 583-597) — same format, same update.

### 5.6 Error formatter — serialize Diagnostics

**File**: `src/pflow/execution/formatters/error_formatter.py`

During transition, `result.errors` still contains legacy dicts. No changes needed yet.

### 5.7 Trace collector — accept Diagnostic dicts

**File**: `src/pflow/runtime/workflow_trace.py`

The `set_warnings()` call in the runner now passes `[d.to_dict() for d in runtime_warnings]` (see Phase 4.3), which produces plain dicts. No changes needed to the trace collector itself.

### 5.8 Verification

`make test` — all display consumers handle both old and new formats gracefully.

---

## Phase 6: Thread Parser Warnings

### 6.1 ResolvedWorkflow gains parser diagnostics

**File**: `src/pflow/execution/workflow_resolver.py`

Change `_try_load_from_file()` (line ~125-132):
```python
content = path.read_text(encoding="utf-8")
result = parse_markdown(content)
normalize_ir(result.ir)
return ResolvedWorkflow(
    ir=result.ir,
    source="file",
    file_path=str(path),
    diagnostics=tuple(result.warnings),  # Parser diagnostics
)
```

Change `_parse_markdown_content()` (line ~164-171) — needs to return diagnostics too. Change to return `ResolvedWorkflow`:
```python
def _parse_markdown_content(content: str) -> ResolvedWorkflow:
    """Parse raw markdown string into ResolvedWorkflow."""
    from pflow.core import normalize_ir
    from pflow.core.markdown_parser import parse_markdown

    result = parse_markdown(content)
    normalize_ir(result.ir)
    return ResolvedWorkflow(
        ir=result.ir,
        source="content",
        file_path=None,
        diagnostics=tuple(result.warnings),
    )
```

Update the caller in `resolve_workflow()` (line ~53-56):
```python
# OLD:
# ir = _parse_markdown_content(identifier)
# _check_inline_file_references(ir, "content")
# return ResolvedWorkflow(ir=ir, source="content", file_path=None)
# NEW:
resolved = _parse_markdown_content(identifier)
_check_inline_file_references(resolved.ir, "content")
return resolved
```

### 6.2 Runner propagates parser diagnostics

**File**: `src/pflow/execution/runner.py`

In `_prepare_workflow()`, after `resolved = self._resolve(workflow)`, capture parser diagnostics:
```python
def _prepare_workflow(self, workflow, params):
    resolved = self._resolve(workflow)
    # ... existing code ...
    validation_warnings = self._validate(resolved.ir, params)

    # Prepend parser diagnostics from resolution
    parser_diags = list(resolved.diagnostics)  # tuple → list
    all_warnings = parser_diags + list(validation_warnings)

    return resolved, all_warnings
```

### 6.3 Nested workflow executor — thread parser warnings

**File**: `src/pflow/runtime/workflow_executor.py`

Use the **instance variable pattern** (matching existing `_child_trace_events` pattern at line ~265-278). Do NOT use a shared store key — `_load_workflow_file()` doesn't receive `shared`, and a shared store key has propagation problems for depth > 2 and thread-safety problems in parallel batch.

**Step 1**: Change `_load_workflow_file()` to return parser warnings alongside IR:
```python
def _load_workflow_file(self, path: Path) -> tuple[dict[str, Any], list[Any]]:
    """Load and parse a .pflow.md workflow file. Returns (ir, parser_warnings)."""
    if not path.exists():
        raise FileNotFoundError(f"Workflow file not found: {path}")
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        raise OSError(f"Error reading workflow file: {e}") from e
    result = parse_markdown(content)
    workflow_ir = result.ir
    if "nodes" not in workflow_ir:
        raise ValueError(f"Workflow file {path} must contain a '## Steps' section with at least one node")
    return workflow_ir, list(result.warnings)
```

**Step 2**: In `prep()`, store parser warnings on instance:
```python
# Where _load_workflow_file is called in prep():
workflow_ir, parser_warnings = self._load_workflow_file(path)
self._child_parser_warnings = parser_warnings  # Instance variable
```

**Step 3**: In `post()`, propagate parser warnings to parent shared store:
```python
def post(self, shared, prep_res, exec_res):
    # ... existing post logic ...
    # Propagate parser warnings to parent
    if hasattr(self, "_child_parser_warnings") and self._child_parser_warnings:
        parent_diags = shared.setdefault("__parser_diagnostics__", [])
        parent_diags.extend(self._child_parser_warnings)
    return super().post(shared, prep_res, exec_res)
```

**Step 4**: Initialize `__parser_diagnostics__` in runner's `_initialize_shared_store()` so the list reference exists before any execution, and add it to `_PROPAGATED_KEYS` for deep nesting:
```python
# In runner.py _initialize_shared_store():
shared_store["__parser_diagnostics__"] = []

# In workflow_executor.py _PROPAGATED_KEYS:
_PROPAGATED_KEYS = (
    "__registry__",
    "__progress_callback__",
    "__mcp_pool__",
    "__warnings__",
    "__memoization_cache__",
    "_trace_collector",
    "__parser_diagnostics__",  # NEW — parser warnings from nested workflows
)
```

**Step 5**: In runner's `_extract_runtime_warnings()` (Phase 4.1), collect parser diagnostics:
```python
def _extract_runtime_warnings(self, shared_store: dict[str, Any]) -> list[Diagnostic]:
    warnings: list[Diagnostic] = []
    # ... existing api_warning and template_error extraction ...

    # Collect parser diagnostics from nested workflows
    for d in shared_store.get("__parser_diagnostics__", []):
        if isinstance(d, Diagnostic):
            warnings.append(d)

    return warnings
```

**Design note**: Parser warnings do NOT cause DEGRADED status. `_determine_status()` reads `__warnings__` and `__template_errors__`, not `__parser_diagnostics__`. This is correct: parser warnings are advisory (syntax near-misses, orphaned content), not execution-affecting.

### 6.4 Validator sub-workflow — thread parser warnings

**File**: `src/pflow/core/workflow/validator.py`

In `_resolve_child_workflow()` (line ~761), change to collect parser warnings:
```python
# OLD:
# result = parse_markdown(content)
# ir_cache[seen_key] = (result.ir, child_path)
# return result.ir, child_path, workflow_ref, [], False

# NEW:
result = parse_markdown(content)
ir_cache[seen_key] = (result.ir, child_path)
# Return parser warnings as part of the validation warnings
parser_warnings = list(result.warnings) if result.warnings else []
return result.ir, child_path, workflow_ref, [], False, parser_warnings
```

This requires changing the return type of `_resolve_child_workflow()` to include parser warnings. The callers in `_validate_sub_workflows()` need to collect these and add them to the warnings list.

**Simpler approach**: Since `_resolve_child_workflow()` has a complex return tuple already, and the parser warnings should flow into the validation warnings, have `_validate_sub_workflows()` collect them:

In `_validate_sub_workflows()`, after calling `_resolve_child_workflow()`:
```python
# After: child_ir, child_path, workflow_ref, resolve_errors, was_cached = ...
# Add: Collect parser warnings from the child parse result
# But _resolve_child_workflow already consumed the parse result...
```

The cleanest approach: Change `_resolve_child_workflow()` return tuple to include a `list[Diagnostic]` for parser warnings. The 6th element:

Current return: `tuple[ir, path, ref, errors, was_cached]`
New return: `tuple[ir, path, ref, errors, was_cached, parser_warnings]`

In `_resolve_child_workflow()`:
```python
result = parse_markdown(content)
ir_cache[seen_key] = (result.ir, child_path)
return result.ir, child_path, workflow_ref, [], False, list(result.warnings)
```

All other return paths return `[]` as the 6th element.

In `_validate_sub_workflows()`, collect **only parser warnings** (not all child warnings — template validation and cache lint warnings from children would cause noise and duplication):
```python
# After getting (child_ir, child_path, ref, errors, was_cached, parser_warnings):
# Filter to parser-only when propagating to parent
sub_parser_warnings.extend(parser_warnings)
```

Change `_validate_sub_workflows()` to return parser warnings alongside errors:

Current signature: `_validate_sub_workflows(...) -> list[str]` (errors only).
New signature: `_validate_sub_workflows(...) -> tuple[list[str], list[Diagnostic]]` (errors + parser warnings).

**Important**: When `_validate_sub_workflows()` calls `WorkflowValidator.validate()` recursively on child workflows, the child's `validate()` returns `(child_errors, child_warnings)`. Do NOT propagate all `child_warnings` to the parent — only propagate parser warnings from `_resolve_child_workflow()` (the 6th tuple element). Template validation and cache lint warnings from children are relevant to the child, not the parent.

In `validate()` (line ~109-111):
```python
# OLD:
# sub_errors = WorkflowValidator._validate_sub_workflows(...)
# errors.extend(sub_errors)

# NEW:
sub_errors, sub_parser_warnings = WorkflowValidator._validate_sub_workflows(...)
errors.extend(sub_errors)
warnings.extend(sub_parser_warnings)
```

### 6.5 Template validation child resolver — optional

**File**: `src/pflow/runtime/template_validation/validator.py:515`

The `_resolve_child_workflow_outputs()` function is for output structure resolution, not warning propagation. Per the task spec, this is one of the 5 sites, but it's the weakest case — template validation doesn't propagate warnings. **Skip this site** — the resolver and validator sites already cover parser warning threading.

### 6.6 Verification

Run a workflow with a near-miss section name (e.g., `## Input` instead of `## Inputs`). Verify the parser warning appears in:
- CLI text output
- CLI JSON output (in `diagnostics` array)
- MCP text output

---

## Phase 7: Update Tests

### 7.1 Tier 1 — Structural changes (~35 tests)

**`tests/test_runtime/test_template_validation/test_warnings.py`** (7 tests):
- Change `ValidationWarning` references to `Diagnostic`
- Change `warning.node_id` to `warning.node_id` (same)
- Change `warning.template` to `(warning.context or {}).get("template")`
- Change `warning.message` to `warning.message` (same)
- Import `Diagnostic` from `pflow.core.diagnostic`

**`tests/test_core/test_cache_lint_warning.py`** (9 tests):
- Change `ValidationWarning` references to `Diagnostic`
- Change `warnings[0].template` to `(warnings[0].context or {}).get("template")`
- `warnings[0].node_id` and `warnings[0].message` stay the same (exist on Diagnostic)
- Import `Diagnostic` from `pflow.core.diagnostic`

**`tests/test_core/test_markdown_parser.py`** (4 sites):
- Parser warnings are now `Diagnostic` objects, not strings
- Change `any("Input" in w and "Inputs" in w for w in warnings)` to `any("Input" in w.message and "Inputs" in w.message for w in warnings)`
- Change `"Unparsed content" in w` to `"Unparsed content" in w.message`
- Change `[w for w in result.warnings if "substring" in w]` to `[w for w in result.warnings if "substring" in w.message]`

**`tests/test_runtime/test_output_resolver.py`** (~1 test):
- Tests `format_for_cli()` on `OutputResolutionError` which is deleted in Phase 8.5
- Convert to test `exception_to_diagnostics()` + `format_diagnostic()`

**`tests/test_mcp_server/test_mcp_warnings.py`** (4 tests):
- These test warning dicts. If they access `warning["template"]`, update to check for `context.template` in the diagnostic dict. During transition, the legacy `warnings` field still has old-format dicts, but `diagnostics` has Diagnostic dicts.

**`tests/test_execution/formatters/test_error_formatter.py`** (16 tests):
- These test `formatted["errors"][N]["key"]`. During transition, `result.errors` contains `to_display_dict()` output (context merged to top-level). These tests should continue to pass since keys like `category`, `shell_command` etc. are in the top-level of `to_display_dict()`.
- But: `ExecutionResult(errors=[{...}])` constructor calls need updating to use `diagnostics=[Diagnostic(...)]` — **see Phase 8.10 for the full list**.

**Other test files** — tests that read `error["category"]`, `error["source"]`, `error["message"]` from `result.errors`:
- During transition (Phases 4-7): `result.errors` contains `to_display_dict()` output with context keys merged to top-level. These should pass.
- In Phase 8: these all break — see Phase 8.10 for the explicit list and conversion guide.

### 7.2 New tests for Diagnostic

Add `tests/test_core/test_diagnostic.py`:
- Test `Diagnostic.__eq__` and `__hash__` (context excluded)
- Test `to_dict()` serialization
- Test `to_display_dict()` with context merging
- Test `deduplicate_diagnostics()`
- Test `exception_to_diagnostics()` for all 13 exception types
- Test `format_diagnostic()` for warnings and errors
- Test that every warning has a suggestion field

### 7.3 Verification

`make test` — all 4500+ tests pass.

---

## Phase 8: Remove Legacy Code

### 8.1 Delete `ValidationWarning` class

**File**: `src/pflow/runtime/template_validation/utils.py`
- Delete the `ValidationWarning` dataclass (lines 22-34)
- Remove `from dataclasses import dataclass` if no longer needed (check — it's still needed for other code? No, there's no other dataclass in this file)

Wait — check if anything still imports `ValidationWarning`. After Phase 3, no production code should. Tests were updated in Phase 7. Delete it.

### 8.2 Convert ExecutionResult to use diagnostics as primary storage

**File**: `src/pflow/execution/result.py`

Replace the three old fields with convenience properties:
```python
@dataclass
class ExecutionResult:
    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    trace: Optional[Any] = None
    metrics: Optional[Any] = None

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.WARNING]
```

Remove `errors`, `warnings`, `validation_warnings` as stored fields. This is a breaking change to all code that constructs `ExecutionResult(errors=[...], warnings=[...], validation_warnings=[...])`.

**Update all construction sites**:

1. `runner.py:_compile_and_execute()` — change to pass `diagnostics=all_diagnostics`
2. `runner.py:_exception_to_result()` — change to pass `diagnostics=all_diagnostics`

**Update all consumer sites** that read `.errors` or `.warnings`:
- These now return `list[Diagnostic]` instead of `list[dict]`
- `workflow_errors.py:_display_text_error_details()` — iterates `result.errors`, now gets Diagnostics. Update `_display_single_error()` to accept Diagnostic.
- `error_output.py:_format_from_result()` — uses `result.errors`, now gets Diagnostics. Serialize via `to_display_dict()`.
- `error_formatter.py:format_execution_errors()` — iterates `result.errors`, now gets Diagnostics. Serialize via `to_display_dict()`, then sanitize.
- `main.py:_handle_workflow_success()` — uses `result.warnings`, now gets Diagnostics. Serialize for display.
- `main.py:_display_execution_result()` — checks `result.status`, not errors. No change.
- `execution_service.py` — uses `result.warnings + result.validation_warnings`. Now use `result.warnings`.

### 8.3 Convert ValidationResult similarly

```python
@dataclass
class ValidationResult:
    valid: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        """Legacy: return error messages as strings for backward compat."""
        return [d.message for d in self.diagnostics if d.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.WARNING]
```

### 8.4 Delete runner helper methods

**File**: `src/pflow/execution/runner.py`
- Delete `_warning_to_dict()` static method
- Delete `_deduplicate_warnings()` static method
- Delete `_build_errors()` method (the errors are now in diagnostics)

### 8.5 Delete `format_for_cli()` methods

**File**: `src/pflow/core/exceptions.py`
- Delete `WorkflowNotFoundError.format_for_cli()` (lines 32-43)
- Delete `WorkflowValidationError.format_for_cli()` (lines 58-75)
- Delete `MaxNodeVisitsError.format_for_cli()` (lines 197-199)

**File**: `src/pflow/core/user_errors.py`
- Delete `UserFriendlyError.format_for_cli()` (lines 45-84)

### 8.6 Delete per-exception converter functions

**File**: `src/pflow/cli/error_output.py`
- Already deleted in Phase 5.1

### 8.7 Update workflow_errors.py for Diagnostic

**File**: `src/pflow/cli/workflow_errors.py`

Change `_display_single_error()` to accept a Diagnostic and read from context:
```python
def _display_single_error(
    error: Diagnostic,
    error_number: int,
    verbose: bool = False,
) -> None:
    ctx = error.context or {}
    category = ctx.get("category", "unknown")

    if error_number == 1:
        header = "❌ Compilation failed" if error.source == "compilation" else "❌ Workflow execution failed"
        click.echo(header, err=True)

    if error.node_id:
        click.echo(f"\nError {error_number} at node '{error.node_id}':", err=True)
    else:
        click.echo(f"\nError {error_number}:", err=True)
    click.echo(f"  Category: {category}", err=True)
    click.echo(f"  Message: {error.message}", err=True)

    if error.suggestion:
        click.echo(f"\n  Suggestion: {error.suggestion}", err=True)

    if error.source == "compilation":
        if node_type := ctx.get("node_type"):
            click.echo(f"  Node type: {node_type}", err=True)
        if sub_path := ctx.get("sub_workflow_path"):
            click.echo(f"  Sub-workflow: {sub_path}", err=True)

    if (raw := ctx.get("raw_response")) and isinstance(raw, dict):
        from pflow.core.security_utils import sanitize_parameters
        sanitized_raw = sanitize_parameters(raw)
        _display_api_error_response(sanitized_raw)

    if (mcp := ctx.get("mcp_error")) and isinstance(mcp, dict):
        from pflow.core.security_utils import sanitize_parameters
        sanitized_mcp = sanitize_parameters(mcp)
        _display_mcp_error_details(sanitized_mcp)

    if category == "template_error" and (available := ctx.get("available_fields")):
        total = ctx.get("available_fields_total", len(available))
        click.echo(f"\n  Available fields in node (showing {min(len(available), 5)} of {total}):", err=True)
        for field_name in available[:5]:
            click.echo(f"    - {field_name}", err=True)
        if len(available) > 5:
            click.echo(f"    ... and {len(available) - 5} more (in error details)", err=True)
        if ctx.get("available_fields_truncated"):
            click.echo("\n  📁 Complete field list available in trace file", err=True)
            click.echo("     ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json", err=True)

    if "shell_command" in ctx:
        _display_shell_error_details(ctx)
```

Change `_display_text_error_details()`:
```python
def _display_text_error_details(result: Any, verbose: bool = False) -> None:
    errors = result.errors  # Now list[Diagnostic] via property
    if not errors:
        click.echo("cli: Workflow execution failed - Node returned error action", err=True)
        return
    for i, error in enumerate(errors, 1):
        _display_single_error(error, i, verbose=verbose)
```

Change `_display_shell_error_details()` to accept a dict (context):
```python
def _display_shell_error_details(ctx: dict[str, Any]) -> None:
    click.echo("\n  Shell details:", err=True)
    cmd = ctx.get("shell_command", "")
    cmd_display = cmd[:200] + "..." if len(cmd) > 200 else cmd
    click.echo(f"    Command: {cmd_display}", err=True)
    if stdout := ctx.get("shell_stdout"):
        stdout_preview = stdout[:300] + "..." if len(stdout) > 300 else stdout
        click.echo(f"    Stdout: {stdout_preview}", err=True)
    if stderr := ctx.get("shell_stderr"):
        stderr_preview = stderr[:300] + "..." if len(stderr) > 300 else stderr
        click.echo(f"    Stderr: {stderr_preview}", err=True)
```

### 8.8 Update error_formatter.py for Diagnostic

**File**: `src/pflow/execution/formatters/error_formatter.py`

```python
def format_execution_errors(result, ...) -> dict[str, Any]:
    formatted_errors = []
    for error in result.errors:  # Now list[Diagnostic]
        # Serialize to dict for JSON output
        error_dict = error.to_display_dict()

        if sanitize:
            from pflow.core.security_utils import sanitize_parameters
            if "raw_response" in error_dict:
                error_dict["raw_response"] = sanitize_parameters(error_dict["raw_response"])
            if "response_headers" in error_dict:
                error_dict["response_headers"] = sanitize_parameters(error_dict["response_headers"])

        formatted_errors.append(error_dict)

    # ... rest stays the same (checkpoint, execution, metrics)
```

### 8.9 Update MCP _build_error_text for Diagnostic

**File**: `src/pflow/mcp_server/services/execution_service.py`

`_build_error_text()` reads from the intermediate dict produced by `_format_error_result()`. Since `_format_error_result()` calls `format_execution_errors()` which now serializes Diagnostics to display dicts, `_build_error_text()` continues to work — it reads dict keys like `node_id`, `message`, `shell_command`, `shell_stderr`.

### 8.10 Update all ExecutionResult/ValidationResult construction sites and consumers

**CRITICAL: Phase 8 must be atomic.** When `errors`/`warnings`/`validation_warnings` become properties, ALL construction sites and ALL consumers must update in the same commit. Missing even one causes a hard crash.

**Production construction sites** (pass `diagnostics=` instead of old fields):
1. `runner.py:_compile_and_execute()` — already updated in Phase 4.3
2. `runner.py:_exception_to_result()` — already updated in Phase 4.2
3. `runner.py:validate()` — already updated in Phase 4.4

**Production consumer sites** (now receive `list[Diagnostic]` from properties):
1. `error_formatter.py:56-58` — `error.copy()` → `error.to_display_dict()` (Phase 8.8)
2. `error_output.py:74-75` — fallback `errors_list = result.errors` → `[d.to_display_dict() for d in result.errors]`
3. `main.py:148` — `result.warnings` → `[d.to_dict() for d in result.warnings]` for display
4. `main.py:401` — `"warnings": vresult.warnings` → `"warnings": [d.to_dict() for d in vresult.warnings]`
5. `execution_service.py:70` — `result.warnings + result.validation_warnings` → `[d.to_dict() for d in result.warnings]`
6. Delete all `elif vresult.warnings:` legacy fallback branches (dead code after Phase 8)

**Test construction sites** (pass `diagnostics=[Diagnostic(...)]` instead of `errors=[{...}]`):
- `tests/test_execution/formatters/test_error_formatter.py` — 14 `ExecutionResult(errors=[{...}])` calls
- `tests/test_execution/test_workflow_execution.py` — 1 construction site
- `tests/test_cli/test_workflow_output_handling.py` — 1 construction site
- `tests/test_runtime/test_checkpoint_tracking.py` — 1 construction site

**Test consumer sites** (change `error["key"]` dict access to Diagnostic attribute/context access):
- `tests/test_execution/test_runner.py` — ~20 assertions: `result.errors[0]["category"]` → `result.errors[0].context.get("category")`, `result.errors[0]["node_id"]` → `result.errors[0].node_id`, etc.
- `tests/test_execution/test_workflow_execution.py` — 5 assertions: `error["source"]` → `error.source`, `error["message"]` → `error.message`, `error["category"]` → `error.context.get("category")`
- `tests/test_cli/test_agent_ux_fixes.py` — 1 assertion: `result.errors[0]["category"]` → `result.errors[0].context.get("category")`
- `tests/test_integration/test_template_resolution_hardening.py` — 5 sites: `error["message"]` → `error.message`
- `tests/test_cli/test_dual_mode_stdin.py` — 1 site: `error["category"]` → `error.context.get("category")`
- `tests/test_cli/test_unified_error_output.py` — 3 tests import `_exception_to_errors`. This function survives Phase 8 (with new implementation using `exception_to_diagnostics` internally). Verify assertions match `to_display_dict()` output shape.

**Diagnostic field → dict key mapping for test conversions:**
| Old dict access | New Diagnostic access |
|----------------|----------------------|
| `error["message"]` | `error.message` |
| `error["node_id"]` | `error.node_id` |
| `error["source"]` | `error.source` |
| `error["suggestion"]` | `error.suggestion` |
| `error["category"]` | `error.context.get("category")` |
| `error["line"]` | `error.context.get("line")` |
| `error["path"]` | `error.context.get("path")` |
| `error["phase"]` | `error.context.get("phase")` |
| `error["node_type"]` | `error.context.get("node_type")` |
| `error["visit_count"]` | `error.context.get("visit_count")` |
| `error["similar_names"]` | `error.context.get("similar_names")` |
| `error["shell_command"]` | `error.context.get("shell_command")` |
| `"key" in error` | `"key" in (error.context or {})` |
| `"key" not in error` | `"key" not in (error.context or {})` |

### 8.11 Converge warning display to use format_diagnostic()

After Phase 8, three warning rendering sites should all use `format_diagnostic()` to eliminate the duplicate-rendering pattern:

1. `workflow_output.py:_display_execution_summary()` — replace inline warning formatting with `format_diagnostic()` calls on Diagnostic objects
2. `success_formatter.py:format_success_as_text()` — replace inline warning formatting with `format_diagnostic()` calls on Diagnostic objects
3. MCP `execution_service.py:validate_workflow()` — delete inline `_format_warning()`, use `format_diagnostic()`

### 8.12 Update CLAUDE.md documentation files

Update stale references to `ValidationWarning` and `format_for_cli()`:
- `src/pflow/runtime/template_validation/CLAUDE.md` — 4 references to `ValidationWarning` → `Diagnostic`
- `src/pflow/core/CLAUDE.md` — 3 references to `format_for_cli()` → note methods deleted, replaced by `format_diagnostic()`
- `src/pflow/cli/CLAUDE.md` — 1 reference to `format_for_cli()` protocol → update
- `src/pflow/execution/CLAUDE.md` — `ExecutionResult` field descriptions → update to show `diagnostics` field and convenience properties

### 8.13 Verification

`make test` and `make check` — full pass. All legacy fields removed, all consumers updated.

---

## Phase 9: Final Verification

### 9.1 Baseline comparison

Update `scratchpads/task-143-unified-diagnostics/baselines/capture_baselines.py` to use Diagnostic types and re-run. Diff against original baselines. Any differences should be:
- **Intentional improvements**: warnings now have suggestions, parser warnings now visible
- **Format-equivalent**: same information, different structure

### 9.2 End-to-end testing

1. Run a workflow that succeeds — verify output matches baseline
2. Run a workflow that fails — verify error display with enrichment is identical
3. Run a workflow with parser warnings (e.g., `## Input` typo) — verify warning appears in CLI text, CLI JSON, and MCP
4. Run `--validate-only` — verify diagnostics in both text and JSON
5. Run a workflow that produces runtime warnings (degraded status) — verify `⚠` status indicator

### 9.3 Automated checks

```bash
make test    # 4500+ tests pass
make check   # ruff, mypy, deptry clean
```

---

## Critical Files Summary

| File | Change Type |
|------|------------|
| `src/pflow/core/diagnostic.py` | **NEW** — Diagnostic, Severity, exception_to_diagnostics, format_diagnostic |
| `src/pflow/execution/result.py` | **MODIFY** — add diagnostics field, then convert to primary storage |
| `src/pflow/execution/runner.py` | **MODIFY** — exception_to_result, extract_runtime_warnings, compile_and_execute, validate |
| `src/pflow/core/markdown_parser.py` | **MODIFY** — parser warnings emit Diagnostic |
| `src/pflow/runtime/template_validation/path_validation.py` | **MODIFY** — template warnings emit Diagnostic |
| `src/pflow/runtime/template_validation/validator.py` | **MODIFY** — type annotations, imports |
| `src/pflow/runtime/template_validation/utils.py` | **MODIFY** — delete ValidationWarning |
| `src/pflow/runtime/template_validation/__init__.py` | **MODIFY** — remove ValidationWarning export |
| `src/pflow/core/workflow/validator.py` | **MODIFY** — cache lint warnings, sub-workflow parser threading |
| `src/pflow/cli/error_output.py` | **MODIFY** — use shared exception_to_diagnostics |
| `src/pflow/cli/workflow_errors.py` | **MODIFY** — read from Diagnostic.context |
| `src/pflow/cli/main.py` | **MODIFY** — delete merge site, use diagnostics |
| `src/pflow/cli/workflow_output.py` | **MODIFY** — warning display update |
| `src/pflow/mcp_server/services/execution_service.py` | **MODIFY** — delete merge site, use diagnostics |
| `src/pflow/execution/formatters/success_formatter.py` | **MODIFY** — handle Diagnostic dict shape |
| `src/pflow/execution/formatters/error_formatter.py` | **MODIFY** — serialize Diagnostics |
| `src/pflow/execution/formatters/validation_formatter.py` | **MODIFY** — use Diagnostics |
| `src/pflow/execution/workflow_resolver.py` | **MODIFY** — thread parser warnings |
| `src/pflow/runtime/workflow_executor.py` | **MODIFY** — thread nested workflow parser warnings |
| `src/pflow/core/exceptions.py` | **MODIFY** — delete format_for_cli methods |
| `src/pflow/core/user_errors.py` | **MODIFY** — delete format_for_cli method |
| `src/pflow/cli/commands/registry_run.py` | **MODIFY** — replace format_for_cli call (CORRECTION 4) |
| `tests/test_core/test_diagnostic.py` | **NEW** — comprehensive Diagnostic tests |
| `tests/test_runtime/test_template_validation/test_warnings.py` | **MODIFY** — Diagnostic assertions |
| `tests/test_mcp_server/test_mcp_warnings.py` | **MODIFY** — Diagnostic assertions |
| `tests/test_core/test_cache_lint_warning.py` | **MODIFY** — .template → context (CORRECTION 5) |
| `tests/test_core/test_markdown_parser.py` | **MODIFY** — string-in-warning → .message (CORRECTION 5) |
| `tests/test_runtime/test_output_resolver.py` | **MODIFY** — format_for_cli test (CORRECTION 5) |
| `tests/test_execution/formatters/test_error_formatter.py` | **MODIFY** — ExecutionResult construction + dict access (CORRECTION 5) |
| `tests/test_execution/test_runner.py` | **MODIFY** — ~20 dict access assertions (CORRECTION 5) |
| `tests/test_execution/test_workflow_execution.py` | **MODIFY** — construction + dict access (CORRECTION 5) |
| `tests/test_cli/test_workflow_output_handling.py` | **MODIFY** — ExecutionResult construction (CORRECTION 5) |
| `tests/test_cli/test_agent_ux_fixes.py` | **MODIFY** — error dict access (CORRECTION 5) |
| `tests/test_cli/test_unified_error_output.py` | **MODIFY** — verify assertions match new output (CORRECTION 5) |
| `tests/test_integration/test_template_resolution_hardening.py` | **MODIFY** — error dict access (CORRECTION 5) |
| `tests/test_cli/test_dual_mode_stdin.py` | **MODIFY** — error dict access (CORRECTION 5) |
| `tests/test_runtime/test_checkpoint_tracking.py` | **MODIFY** — ExecutionResult construction (CORRECTION 5) |

## Reusable Existing Functions

- `find_similar_items()` from `src/pflow/core/suggestion_utils.py` — used by WorkflowNotFoundError, reuse for suggestions
- `sanitize_parameters()` from `src/pflow/core/security_utils.py` — sanitize context at display time
- `generate_validation_suggestions()` from `src/pflow/core/validation_utils.py` — keep for validation formatter fallback
- `determine_error_category()` from `src/pflow/execution/executor_service.py` — reuse for runtime error categorization
- `build_error_list()` from `src/pflow/execution/executor_service.py` — reuse during transition, then convert output to Diagnostics
