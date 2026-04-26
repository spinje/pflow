"""Test that the consolidated exception hierarchy works as expected."""

import pytest

from pflow.core.exceptions import (
    _PFLOW_EXCEPTION_ANNOTATIONS,
    CompilationError,
    MarkdownParseError,
    MaxNodeVisitsError,
    PflowError,
    SchemaValidationError,
    WorkflowExistsError,
    WorkflowNotFoundError,
    WorkflowValidationError,
    copy_pflow_annotations,
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

    def test_max_node_visits_error_intentionally_not_pflow_error(self):
        """MaxNodeVisitsError extends RuntimeError, NOT PflowError (intentional)."""
        exc = MaxNodeVisitsError("node-1", visit_count=100, max_visits=100)
        assert isinstance(exc, RuntimeError)
        assert not isinstance(exc, PflowError)

    def test_workflow_validation_error_carries_warnings_as_first_class_attr(self):
        """WorkflowValidationError.validation_warnings is a real constructor kwarg.

        Regression guard for PR #244 review feedback — before the promotion,
        warnings were smuggled via a dynamic attribute (``error._pflow_validation_warnings``)
        with a ``# type: ignore[attr-defined]``. Promoting to a real kwarg
        removes the type ignore and makes the contract explicit. This test
        locks in that the kwarg round-trips correctly and defaults to an empty
        list when omitted.
        """
        from pflow.core.diagnostic import Diagnostic, Severity

        warn = Diagnostic(
            severity=Severity.WARNING,
            message="cache lint warning",
            source="validator",
            node_id="fetch",
        )
        err = Diagnostic(
            severity=Severity.ERROR,
            message="structural error",
            source="validator",
            title="Validation Error",
        )

        # Construct with both errors and warnings
        exc = WorkflowValidationError(
            validation_errors=[err],
            validation_warnings=[warn],
        )
        assert exc.validation_errors == [err]
        assert exc.validation_warnings == [warn]

        # Default to empty list when warnings omitted
        exc_no_warnings = WorkflowValidationError(validation_errors=[err])
        assert exc_no_warnings.validation_warnings == []

        # Pre-existing summary-only constructor still works (backward compat)
        exc_summary = WorkflowValidationError("failed")
        assert exc_summary.validation_errors == []
        assert exc_summary.validation_warnings == []


class TestCopyPflowAnnotations:
    """Tests for the copy_pflow_annotations helper and _PFLOW_EXCEPTION_ANNOTATIONS constant."""

    def test_copies_all_present_annotations(self):
        """All _pflow_* attributes on source are copied to target."""
        source = ValueError("original")
        source._pflow_node_id = "fetch-data"  # type: ignore[attr-defined]
        source._pflow_shared_store = {"key": "value"}  # type: ignore[attr-defined]
        source._pflow_template_diagnostic = "diag"  # type: ignore[attr-defined]

        target = RuntimeError("wrapper")
        copy_pflow_annotations(source, target)

        assert target._pflow_node_id == "fetch-data"  # type: ignore[attr-defined]
        assert target._pflow_shared_store == {"key": "value"}  # type: ignore[attr-defined]
        assert target._pflow_template_diagnostic == "diag"  # type: ignore[attr-defined]

    def test_skips_absent_annotations(self):
        """Attributes not present on source are not set on target."""
        source = ValueError("original")
        source._pflow_node_id = "fetch-data"  # type: ignore[attr-defined]

        target = RuntimeError("wrapper")
        copy_pflow_annotations(source, target)

        assert target._pflow_node_id == "fetch-data"  # type: ignore[attr-defined]
        assert not hasattr(target, "_pflow_shared_store")
        assert not hasattr(target, "_pflow_template_diagnostic")
        assert not hasattr(target, "_pflow_partial_resolutions")

    def test_source_overwrites_existing_target_attrs(self):
        """Existing non-None attrs on source overwrite target — this is the
        expected behavior when wrapping (source has the authoritative context).
        """
        source = ValueError("original")
        source._pflow_node_id = "source-node"  # type: ignore[attr-defined]

        target = RuntimeError("wrapper")
        target._pflow_node_id = "target-node"  # type: ignore[attr-defined]
        copy_pflow_annotations(source, target)

        assert target._pflow_node_id == "source-node"  # type: ignore[attr-defined]

    def test_constant_covers_all_known_annotations(self):
        """_PFLOW_EXCEPTION_ANNOTATIONS lists every annotation used in production.

        If a new _pflow_* annotation is added to the engine/runner/template
        resolution without updating the constant, this test should be updated
        to catch the gap.
        """
        expected = {
            "_pflow_node_id",
            "_pflow_shared_store",
            "_pflow_parser_diagnostics",
            "_pflow_template_diagnostic",
            "_pflow_partial_resolutions",
        }
        assert set(_PFLOW_EXCEPTION_ANNOTATIONS) == expected
