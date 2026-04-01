"""Test that the consolidated exception hierarchy works as expected."""

import pytest

from pflow.core.exceptions import (
    CompilationError,
    CriticalDiscoveryError,
    MarkdownParseError,
    MaxNodeVisitsError,
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

    def test_max_node_visits_error_intentionally_not_pflow_error(self):
        """MaxNodeVisitsError extends RuntimeError, NOT PflowError (intentional)."""
        exc = MaxNodeVisitsError("node-1", visit_count=100, max_visits=100)
        assert isinstance(exc, RuntimeError)
        assert not isinstance(exc, PflowError)
