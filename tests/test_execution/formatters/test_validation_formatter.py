"""Tests for validation formatter - guardrails for validation display.

These tests catch real bugs that could break validation feedback for agents.
Each test documents what bug it prevents.
"""

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.execution.formatters.validation_formatter import (
    format_validation_failure,
    format_validation_success,
)


def _errors(*messages: str) -> list[Diagnostic]:
    """Create minimal error Diagnostics from message strings for test brevity."""
    return [Diagnostic(severity=Severity.ERROR, message=msg, source="validation") for msg in messages]


class TestValidationSuccessFormatting:
    """Tests for validation success message formatting."""

    def test_success_is_minimal_and_token_efficient(self):
        """CORRECTNESS: Success message must be concise for token efficiency.

        Real bug this catches: Verbose success messages waste tokens. Simple
        "valid" confirmation is sufficient - detailed steps aren't needed.
        """
        result = format_validation_success()

        # Should be minimal: just confirmation
        assert result == "\u2713 Workflow is valid"

    def test_success_includes_checkmark_symbol(self):
        """UX: Success message must use checkmark for visual confirmation.

        Real bug this catches: Without visual indicator, success might be
        confused with regular output.
        """
        result = format_validation_success()
        assert "\u2713" in result

    def test_success_message_is_single_line(self):
        """FORMAT: Success message must be single line for token efficiency.

        Real bug this catches: Multiline output wastes tokens. For success
        cases, concise confirmation is preferred.
        """
        result = format_validation_success()
        assert "\n" not in result  # Single line only


class TestValidationFailureFormatting:
    """Tests for validation failure message formatting."""

    def test_failure_includes_header_with_error_count(self):
        """CORRECTNESS: Failure message must have header with error count.

        Real bug this catches: Without header, error list would be confusing
        and not clearly indicate validation failure. The header includes the
        exact error count so agents know the scope.
        """
        errors = _errors("Error 1", "Error 2")
        result = format_validation_failure(errors)
        assert "\u2717 Validation failed (2 errors):" in result

    def test_failure_header_uses_singular_for_one_error(self):
        """FORMAT: Header uses singular 'error' when there's exactly one.

        Real bug this catches: Grammar error ("1 errors") makes output look
        unprofessional to agents parsing text.
        """
        errors = _errors("Only error")
        result = format_validation_failure(errors)
        assert "\u2717 Validation failed (1 error):" in result

    def test_failure_includes_all_errors_when_few(self):
        """CORRECTNESS: All errors must be shown when list is small (under 5).

        Real bug this catches: Truncating small error lists would hide
        critical validation issues.
        """
        errors = _errors("Error 1", "Error 2", "Error 3")
        result = format_validation_failure(errors)

        assert "1. Error 1" in result
        assert "2. Error 2" in result
        assert "3. Error 3" in result
        assert "more errors" not in result  # No truncation warning

    def test_failure_truncates_at_5_errors(self):
        """UX: Long error lists must be truncated at 5 to avoid overwhelming output.

        Real bug this catches: Showing all errors when there are 50+ would
        make terminal output unusable and hide actionable information.
        """
        errors = _errors(*[f"Error {i}" for i in range(8)])
        result = format_validation_failure(errors)

        # First 5 should be shown (numbered format)
        assert "1. Error 0" in result
        assert "5. Error 4" in result

        # 6th and beyond should not be shown
        assert "6. Error 5" not in result
        assert "Error 7" not in result

        # Must indicate there are more errors
        assert "... and 3 more errors" in result

    def test_failure_shows_exact_count_when_truncated(self):
        """CORRECTNESS: Truncation message must show exact remaining count.

        Real bug this catches: Vague messages like "more errors" don't help
        users understand scope of validation issues.
        """
        errors = _errors(*[f"Error {i}" for i in range(23)])
        result = format_validation_failure(errors)

        # Must show exactly 18 more errors (23 - 5 = 18)
        assert "... and 18 more errors" in result

    def test_failure_handles_empty_error_list(self):
        """ROBUSTNESS: Must handle empty error list without crashing.

        Real bug this catches: Edge case where validation returns no errors
        but failure path is taken would crash without defensive handling.
        """
        result = format_validation_failure(_errors())

        # Should still have header (0 errors)
        assert "\u2717 Validation failed (0 errors):" in result
        # Should not have truncation message
        assert "more errors" not in result

    def test_failure_handles_exactly_5_errors(self):
        """EDGE CASE: Exactly 5 errors should not trigger truncation message.

        Real bug this catches: Off-by-one error in truncation logic would
        show "... and 0 more errors" which looks broken.
        """
        errors = _errors(*[f"Error {i}" for i in range(5)])
        result = format_validation_failure(errors)

        # All 5 should be shown
        assert "1. Error 0" in result
        assert "5. Error 4" in result

        # Should NOT have truncation message
        assert "more errors" not in result

    def test_failure_handles_exactly_6_errors(self):
        """EDGE CASE: Exactly 6 errors should trigger truncation message.

        Real bug this catches: Boundary condition where truncation logic
        starts should be tested to avoid off-by-one errors.
        """
        errors = _errors(*[f"Error {i}" for i in range(6)])
        result = format_validation_failure(errors)

        # First 5 should be shown
        assert "1. Error 0" in result
        assert "5. Error 4" in result

        # 6th should not be shown
        assert "6. Error 5" not in result

        # Should indicate 1 more error
        assert "... and 1 more error" in result

    def test_failure_preserves_error_formatting(self):
        """FORMAT: Error messages must be indented and numbered.

        Real bug this catches: Without proper formatting, error list would
        be hard to parse visually and wouldn't match CLI expectations.
        """
        errors = _errors("Node 'fetch' not found", "Template ${invalid} undefined")
        result = format_validation_failure(errors)

        # Each error should be indented with numbered format
        assert "  1. Node 'fetch' not found" in result
        assert "  2. Template ${invalid} undefined" in result

    def test_failure_with_diagnostic_objects_shows_suggestions(self):
        """CORRECTNESS: Diagnostic objects render with per-error suggestions.

        Real bug this catches: Diagnostic objects carry richer data than
        plain strings. Their suggestions must appear in output.
        """
        diagnostics = [
            Diagnostic(
                severity=Severity.ERROR,
                message="Node type 'nonexistent' not found in registry",
                suggestions=["Use 'pflow registry list' to see available nodes"],
                source="validator",
            ),
        ]
        result = format_validation_failure(diagnostics)

        assert "1. Node type 'nonexistent' not found in registry" in result
        assert "\u2192 Use 'pflow registry list' to see available nodes" in result

    def test_failure_with_diagnostic_shows_path_context(self):
        """CORRECTNESS: Diagnostic with path context shows location.

        Real bug this catches: Without location info, users can't find
        where the error occurred in complex workflows.
        """
        diagnostics = [
            Diagnostic(
                severity=Severity.ERROR,
                message="Invalid parameter",
                source="validator",
                context={"path": "nodes[0].params.command"},
            ),
        ]
        result = format_validation_failure(diagnostics)

        assert "At: nodes[0].params.command" in result

    def test_failure_skips_root_path_in_diagnostic(self):
        """FORMAT: Path 'root' is not shown (not useful to users).

        Real bug this catches: Showing "At: root" adds noise without
        providing any useful location information.
        """
        diagnostics = [
            Diagnostic(
                severity=Severity.ERROR,
                message="Missing required field",
                source="validator",
                context={"path": "root"},
            ),
        ]
        result = format_validation_failure(diagnostics)

        assert "At:" not in result


class TestValidationFormatterIntegration:
    """Integration tests for validation formatter usage patterns."""

    def test_success_and_failure_have_consistent_styling(self):
        """UX: Success and failure messages must use consistent visual style.

        Real bug this catches: Inconsistent use of symbols (\u2713 vs \u2717) or
        formatting would make output look unprofessional.
        """
        success = format_validation_success()
        failure = format_validation_failure(_errors("Error"))

        # Both should use checkmark/X symbols
        assert "\u2713" in success
        assert "\u2717" in failure

    def test_messages_are_suitable_for_cli_display(self):
        """FORMAT: Messages must be properly formatted for terminal display.

        Real bug this catches: Messages with incorrect line breaks or
        formatting would look broken in terminal output.
        """
        success = format_validation_success()
        failure = format_validation_failure(_errors("Error 1", "Error 2"))

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
        failure = format_validation_failure(_errors("Error with 'quotes'"))

        # Should be plain strings (no special encoding needed)
        assert isinstance(success, str)
        assert isinstance(failure, str)

        # Should handle quotes in error messages
        assert "Error with 'quotes'" in failure


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
