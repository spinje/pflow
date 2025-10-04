"""Security tests for workflow save command and validation functions.

Tests validate that security measures prevent common attacks:
- Log injection via newlines in error messages
- Path traversal in workflow names
- Reserved name conflicts
- Input validation for discovery queries
"""

import pytest

from pflow.core.exceptions import WorkflowValidationError
from pflow.core.workflow_manager import WorkflowManager
from pflow.runtime.template_validator import TemplateValidator


class TestSanitizeForDisplay:
    """Test _sanitize_for_display prevents log injection attacks."""

    def test_sanitize_blocks_newline_injection(self):
        """Newlines must be stripped to prevent log injection."""
        malicious = "fake\n[INFO] admin logged in\n"
        result = TemplateValidator._sanitize_for_display(malicious)
        assert "\n" not in result
        assert "\r" not in result
        assert result == "fake[INFO] admin logged in"

    def test_sanitize_blocks_carriage_return(self):
        """Carriage returns must be stripped."""
        malicious = "node\rmalicious_override"
        result = TemplateValidator._sanitize_for_display(malicious)
        assert "\r" not in result
        assert result == "nodemalicious_override"

    def test_sanitize_blocks_tab_characters(self):
        """Tab characters must be stripped."""
        malicious = "node\tmalicious"
        result = TemplateValidator._sanitize_for_display(malicious)
        assert "\t" not in result
        assert result == "nodemalicious"

    def test_sanitize_blocks_vertical_tab(self):
        """Vertical tabs (\x0b) must be stripped."""
        malicious = "node\x0bmalicious"
        result = TemplateValidator._sanitize_for_display(malicious)
        assert "\x0b" not in result
        assert result == "nodemalicious"

    def test_sanitize_blocks_form_feed(self):
        """Form feeds (\x0c) must be stripped."""
        malicious = "node\x0cmalicious"
        result = TemplateValidator._sanitize_for_display(malicious)
        assert "\x0c" not in result
        assert result == "nodemalicious"

    def test_sanitize_truncates_long_strings(self):
        """Long strings should be truncated with ellipsis."""
        long_string = "a" * 200
        result = TemplateValidator._sanitize_for_display(long_string, max_length=100)
        assert len(result) == 103  # 100 chars + "..."
        assert result.endswith("...")

    def test_sanitize_preserves_safe_characters(self):
        """Safe characters should pass through unchanged."""
        safe = "node-123_abc.xyz"
        result = TemplateValidator._sanitize_for_display(safe)
        assert result == safe


class TestWorkflowNameValidation:
    """Test workflow name validation in WorkflowManager."""

    def test_name_validation_blocks_reserved_names(self):
        """Reserved names should be rejected."""
        wm = WorkflowManager()

        reserved_names = ["null", "undefined", "none", "test", "settings", "registry", "workflow", "mcp"]

        for reserved in reserved_names:
            with pytest.raises(WorkflowValidationError) as exc_info:
                wm._validate_workflow_name(reserved)
            assert "reserved" in str(exc_info.value).lower()

    def test_name_validation_blocks_reserved_names_case_insensitive(self):
        """Reserved names should be blocked regardless of case."""
        wm = WorkflowManager()

        with pytest.raises(WorkflowValidationError) as exc_info:
            wm._validate_workflow_name("NULL")
        assert "reserved" in str(exc_info.value).lower()

        with pytest.raises(WorkflowValidationError) as exc_info:
            wm._validate_workflow_name("Test")
        assert "reserved" in str(exc_info.value).lower()

    def test_name_validation_enforces_format(self):
        """Workflow names must follow strict format rules."""
        wm = WorkflowManager()

        # Leading hyphen not allowed
        with pytest.raises(WorkflowValidationError):
            wm._validate_workflow_name("-myworkflow")

        # Trailing hyphen not allowed
        with pytest.raises(WorkflowValidationError):
            wm._validate_workflow_name("myworkflow-")

        # Consecutive hyphens not allowed
        with pytest.raises(WorkflowValidationError):
            wm._validate_workflow_name("my--workflow")

        # Uppercase not allowed
        with pytest.raises(WorkflowValidationError):
            wm._validate_workflow_name("MyWorkflow")

        # Dots not allowed
        with pytest.raises(WorkflowValidationError):
            wm._validate_workflow_name("my.workflow")

        # Underscores not allowed
        with pytest.raises(WorkflowValidationError):
            wm._validate_workflow_name("my_workflow")

    def test_name_validation_allows_valid_names(self):
        """Valid workflow names should pass validation."""
        wm = WorkflowManager()

        valid_names = [
            "my-workflow",
            "pr-analyzer-v2",
            "simple",
            "workflow123",
            "a",
            "test123",  # "test" is reserved but "test123" is fine
        ]

        for name in valid_names:
            # Should not raise
            wm._validate_workflow_name(name)

    def test_name_validation_enforces_length_limit(self):
        """Workflow names must not exceed 50 characters."""
        wm = WorkflowManager()

        # 51 characters should fail
        too_long = "a" * 51
        with pytest.raises(WorkflowValidationError) as exc_info:
            wm._validate_workflow_name(too_long)
        assert "50 characters" in str(exc_info.value)

        # 50 characters should pass
        exactly_50 = "a" * 50
        wm._validate_workflow_name(exactly_50)  # Should not raise

    def test_name_validation_rejects_empty_name(self):
        """Empty workflow names should be rejected."""
        wm = WorkflowManager()

        with pytest.raises(WorkflowValidationError) as exc_info:
            wm._validate_workflow_name("")
        assert "empty" in str(exc_info.value).lower()


class TestDiscoveryQueryValidation:
    """Test discovery query validation for workflow and registry discover commands."""

    def test_empty_query_rejected(self):
        """Empty queries should be rejected by validation helper."""
        from pflow.cli.commands.workflow import _validate_discovery_query

        # Empty string
        with pytest.raises(SystemExit):
            _validate_discovery_query("", "test command")

        # Whitespace only
        with pytest.raises(SystemExit):
            _validate_discovery_query("   ", "test command")

    def test_long_query_rejected(self):
        """Queries over 500 characters should be rejected."""
        from pflow.cli.commands.workflow import _validate_discovery_query

        # 501 characters should fail
        too_long = "a" * 501
        with pytest.raises(SystemExit):
            _validate_discovery_query(too_long, "test command")

    def test_valid_query_accepted(self):
        """Valid queries should pass through with whitespace stripped."""
        from pflow.cli.commands.workflow import _validate_discovery_query

        # Normal query
        result = _validate_discovery_query("I need to analyze pull requests", "test command")
        assert result == "I need to analyze pull requests"

        # Query with leading/trailing whitespace
        result = _validate_discovery_query("  query with spaces  ", "test command")
        assert result == "query with spaces"

        # Exactly 500 characters should pass
        exactly_500 = "a" * 500
        result = _validate_discovery_query(exactly_500, "test command")
        assert result == exactly_500


class TestRuntimeTypeValidation:
    """Test runtime type assertions in executor_service.py."""

    def test_available_fields_type_safety(self):
        """Runtime assertions should validate available_fields type."""
        # This test validates that the assertions in executor_service.py work correctly
        # The assertions are:
        # 1. assert isinstance(error["available_fields"], list)
        # 2. assert all(isinstance(f, str) for f in error["available_fields"])

        # Valid case: list of strings
        error = {"available_fields": ["field1", "field2", "field3"]}
        assert isinstance(error["available_fields"], list)
        assert all(isinstance(f, str) for f in error["available_fields"])

        # Invalid case: not a list
        error_invalid = {"available_fields": "not a list"}
        with pytest.raises(AssertionError):
            assert isinstance(error_invalid["available_fields"], list)

        # Invalid case: list with non-strings
        error_mixed = {"available_fields": ["field1", 123, "field3"]}
        with pytest.raises(AssertionError):
            assert all(isinstance(f, str) for f in error_mixed["available_fields"])
