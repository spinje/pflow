"""Shared helpers for splitting validator diagnostics by severity.

These replace the duplicated local test helpers introduced during the task 147
test migration. Errors are returned as typed ``Diagnostic`` objects, not
pre-rendered strings, so callers can assert on ``.message`` or structural
context fields directly.
"""

from __future__ import annotations

from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity


def split_validator_diagnostics(*args: Any, **kwargs: Any) -> tuple[list[Diagnostic], list[Diagnostic]]:
    """Run ``WorkflowValidator.validate`` and split by severity."""
    from pflow.core.workflow.validator import WorkflowValidator

    diagnostics = WorkflowValidator.validate(*args, **kwargs)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]
    return errors, warnings


def split_template_diagnostics(*args: Any, **kwargs: Any) -> tuple[list[Diagnostic], list[Diagnostic]]:
    """Run ``validate_workflow_templates`` and split by severity."""
    from pflow.runtime.template_validation import validate_workflow_templates

    diagnostics = validate_workflow_templates(*args, **kwargs)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]
    return errors, warnings
