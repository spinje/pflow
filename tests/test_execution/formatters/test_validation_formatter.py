"""Tests for validation formatter - guardrails for validation display.

These tests catch real bugs that could break validation feedback for agents.
Each test documents what bug it prevents.
"""

import pytest

from pflow.execution.formatters.validation_formatter import (
    format_validation_failure,
    format_validation_success,
)


class TestValidationSuccessFormatting:
    """Tests for validation success message formatting."""

    def test_success_is_minimal_and_token_efficient(self):
        """CORRECTNESS: Success message must be concise for token efficiency.

        Real bug this catches: Verbose success messages waste tokens. Simple
        "valid" confirmation is sufficient - detailed steps aren't needed.
        """
        result = format_validation_success()

        # Should be minimal: just confirmation
        assert result == "✓ Workflow is valid"

    def test_success_includes_checkmark_symbol(self):
        """UX: Success message must use checkmark for visual confirmation.

        Real bug this catches: Without visual indicator, success might be
        confused with regular output.
        """
        result = format_validation_success()
        assert "✓" in result

    def test_success_message_is_single_line(self):
        """FORMAT: Success message must be single line for token efficiency.

        Real bug this catches: Multiline output wastes tokens. For success
        cases, concise confirmation is preferred.
        """
        result = format_validation_success()
        assert "\n" not in result  # Single line only


class TestValidationFailureFormatting:
    """Tests for validation failure message formatting."""

    def test_failure_includes_header(self):
        """CORRECTNESS: Failure message must have clear error header.

        Real bug this catches: Without header, error list would be confusing
        and not clearly indicate validation failure.
        """
        errors = ["Error 1", "Error 2"]
        result = format_validation_failure(errors)
        assert "✗ Static validation failed:" in result

    def test_failure_includes_all_errors_when_few(self):
        """CORRECTNESS: All errors must be shown when list is small.

        Real bug this catches: Truncating small error lists would hide
        critical validation issues.
        """
        errors = ["Error 1", "Error 2", "Error 3"]
        result = format_validation_failure(errors)

        assert "• Error 1" in result
        assert "• Error 2" in result
        assert "• Error 3" in result
        assert "more errors" not in result  # No truncation warning

    def test_failure_truncates_at_10_errors(self):
        """UX: Long error lists must be truncated to avoid overwhelming output.

        Real bug this catches: Showing all errors when there are 50+ would
        make terminal output unusable and hide actionable information.
        """
        errors = [f"Error {i}" for i in range(15)]
        result = format_validation_failure(errors)

        # First 10 should be shown
        assert "• Error 0" in result
        assert "• Error 9" in result

        # 11th and beyond should not be shown
        assert "• Error 10" not in result
        assert "• Error 14" not in result

        # Must indicate there are more errors
        assert "... and 5 more errors" in result

    def test_failure_shows_exact_count_when_truncated(self):
        """CORRECTNESS: Truncation message must show exact remaining count.

        Real bug this catches: Vague messages like "more errors" don't help
        users understand scope of validation issues.
        """
        errors = [f"Error {i}" for i in range(23)]
        result = format_validation_failure(errors)

        # Must show exactly 13 more errors (23 - 10 = 13)
        assert "... and 13 more errors" in result

    def test_failure_handles_empty_error_list(self):
        """ROBUSTNESS: Must handle empty error list without crashing.

        Real bug this catches: Edge case where validation returns no errors
        but failure path is taken would crash without defensive handling.
        """
        result = format_validation_failure([])

        # Should still have header
        assert "✗ Static validation failed:" in result
        # Should not have truncation message
        assert "more errors" not in result

    def test_failure_handles_exactly_10_errors(self):
        """EDGE CASE: Exactly 10 errors should not trigger truncation message.

        Real bug this catches: Off-by-one error in truncation logic would
        show "... and 0 more errors" which looks broken.
        """
        errors = [f"Error {i}" for i in range(10)]
        result = format_validation_failure(errors)

        # All 10 should be shown
        assert "• Error 0" in result
        assert "• Error 9" in result

        # Should NOT have truncation message
        assert "more errors" not in result

    def test_failure_handles_exactly_11_errors(self):
        """EDGE CASE: Exactly 11 errors should trigger truncation message.

        Real bug this catches: Boundary condition where truncation logic
        starts should be tested to avoid off-by-one errors.
        """
        errors = [f"Error {i}" for i in range(11)]
        result = format_validation_failure(errors)

        # First 10 should be shown
        assert "• Error 0" in result
        assert "• Error 9" in result

        # 11th should not be shown
        assert "• Error 10" not in result

        # Should indicate 1 more error
        assert "... and 1 more errors" in result

    def test_failure_preserves_error_formatting(self):
        """FORMAT: Error messages must be indented and bulleted.

        Real bug this catches: Without proper formatting, error list would
        be hard to parse visually and wouldn't match CLI expectations.
        """
        errors = ["Node 'fetch' not found", "Template ${invalid} undefined"]
        result = format_validation_failure(errors)

        # Each error should be indented with bullet points
        assert "  • Node 'fetch' not found" in result
        assert "  • Template ${invalid} undefined" in result


class TestValidationFormatterIntegration:
    """Integration tests for validation formatter usage patterns."""

    def test_success_and_failure_have_consistent_styling(self):
        """UX: Success and failure messages must use consistent visual style.

        Real bug this catches: Inconsistent use of symbols (✓ vs ✗) or
        formatting would make output look unprofessional.
        """
        success = format_validation_success()
        failure = format_validation_failure(["Error"])

        # Both should use checkmark/X symbols
        assert "✓" in success
        assert "✗" in failure

    def test_messages_are_suitable_for_cli_display(self):
        """FORMAT: Messages must be properly formatted for terminal display.

        Real bug this catches: Messages with incorrect line breaks or
        formatting would look broken in terminal output.
        """
        success = format_validation_success()
        failure = format_validation_failure(["Error 1", "Error 2"])

        # Success is single line (minimal), failure is multi-line
        assert "\n" not in success  # Single line for token efficiency
        assert "\n" in failure  # Multi-line with error list

        # Neither should have trailing newlines (caller adds them)
        assert not success.endswith("\n\n")
        assert not failure.endswith("\n\n")

    def test_messages_are_suitable_for_mcp_display(self):
        """FORMAT: Messages must work in MCP message field.

        Real bug this catches: Special characters or formatting that don't
        serialize well in JSON would break MCP responses.
        """
        success = format_validation_success()
        failure = format_validation_failure(["Error with 'quotes'"])

        # Should be plain strings (no special encoding needed)
        assert isinstance(success, str)
        assert isinstance(failure, str)

        # Should handle quotes in error messages
        assert "Error with 'quotes'" in failure


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
