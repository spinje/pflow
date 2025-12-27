"""Tests for success formatter - guardrails for execution success display.

These tests catch real bugs that could break execution output for agents and CLI.
Each test documents what bug it prevents.
"""

from pflow.execution.formatters.success_formatter import (
    _format_batch_errors_section,
    _format_batch_node_line,
    _format_execution_step,
    _truncate_error_message,
    format_success_as_text,
)


class TestBatchNodeLineFormatting:
    """Tests for batch node status line formatting."""

    def test_batch_full_success_shows_checkmark(self):
        """CORRECTNESS: Batch with all items successful shows checkmark.

        Real bug this catches: Without visual distinction, users can't quickly
        identify batch node success status.
        """
        step = {
            "node_id": "process",
            "status": "completed",
            "duration_ms": 31,
            "is_batch": True,
            "batch_total": 10,
            "batch_success": 10,
            "batch_errors": 0,
        }
        result = _format_batch_node_line(step)

        assert "✓ process" in result
        assert "10/10 items succeeded" in result
        assert "failed" not in result

    def test_batch_partial_success_shows_warning(self):
        """CORRECTNESS: Batch with some failures shows warning indicator.

        Real bug this catches: Showing green checkmark for partial failures
        would give false confidence about execution success.
        """
        step = {
            "node_id": "process",
            "status": "completed",
            "duration_ms": 31,
            "is_batch": True,
            "batch_total": 10,
            "batch_success": 8,
            "batch_errors": 2,
        }
        result = _format_batch_node_line(step)

        assert "⚠ process" in result
        assert "8/10 items succeeded" in result
        assert "2 failed" in result

    def test_batch_line_includes_timing(self):
        """FORMAT: Batch node line must include execution time.

        Real bug this catches: Missing timing info makes performance debugging
        impossible.
        """
        step = {
            "node_id": "process",
            "duration_ms": 150,
            "is_batch": True,
            "batch_total": 5,
            "batch_success": 5,
            "batch_errors": 0,
        }
        result = _format_batch_node_line(step)

        assert "(150ms)" in result

    def test_batch_line_includes_cached_tag(self):
        """FORMAT: Cached batch nodes must show cached tag.

        Real bug this catches: Without cached indicator, users can't identify
        which batch nodes used cached results.
        """
        step = {
            "node_id": "process",
            "duration_ms": 0,
            "is_batch": True,
            "batch_total": 5,
            "batch_success": 5,
            "batch_errors": 0,
            "cached": True,
        }
        result = _format_batch_node_line(step)

        assert "[cached]" in result

    def test_batch_line_includes_repaired_tag(self):
        """FORMAT: Repaired batch nodes must show repaired tag.

        Real bug this catches: Without repaired indicator, users can't identify
        which batch nodes were auto-repaired.
        """
        step = {
            "node_id": "process",
            "duration_ms": 50,
            "is_batch": True,
            "batch_total": 5,
            "batch_success": 5,
            "batch_errors": 0,
            "repaired": True,
        }
        result = _format_batch_node_line(step)

        assert "[repaired]" in result


class TestBatchErrorsSectionFormatting:
    """Tests for batch errors section formatting."""

    def test_batch_errors_section_includes_node_id(self):
        """CORRECTNESS: Error section header must identify which batch node.

        Real bug this catches: Without node ID in header, users can't identify
        which batch node's errors are being shown.
        """
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 2,
                "batch_error_details": [
                    {"index": 1, "error": "Error 1"},
                    {"index": 4, "error": "Error 2"},
                ],
            }
        ]
        lines = _format_batch_errors_section(steps)

        assert any("Batch 'process' errors:" in line for line in lines)

    def test_batch_errors_show_item_indices(self):
        """CORRECTNESS: Each error must show which item failed (0-based index).

        Real bug this catches: Without item indices, users can't identify which
        input items caused failures.
        """
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 2,
                "batch_error_details": [
                    {"index": 1, "error": "Error at item 1"},
                    {"index": 4, "error": "Error at item 4"},
                ],
            }
        ]
        lines = _format_batch_errors_section(steps)

        assert any("[1]" in line for line in lines)
        assert any("[4]" in line for line in lines)

    def test_batch_errors_show_messages(self):
        """CORRECTNESS: Error messages must be displayed.

        Real bug this catches: Without error messages, users can't understand
        what went wrong.
        """
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 1,
                "batch_error_details": [
                    {"index": 0, "error": "Command failed with exit code 1"},
                ],
            }
        ]
        lines = _format_batch_errors_section(steps)

        assert any("Command failed with exit code 1" in line for line in lines)

    def test_batch_errors_capped_at_5(self):
        """UX: More than 5 errors shows truncation message.

        Real bug this catches: Showing 50 error lines would overwhelm the user
        and make terminal output unusable.
        """
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 8,
                "batch_error_details": [{"index": i, "error": f"Error {i}"} for i in range(5)],
                "batch_errors_truncated": 3,
            }
        ]
        lines = _format_batch_errors_section(steps)

        # Should show truncation message
        assert any("...and 3 more errors" in line for line in lines)

    def test_batch_errors_empty_for_no_failures(self):
        """CORRECTNESS: No error section when batch succeeds fully.

        Real bug this catches: Showing empty error section would be confusing
        and add visual noise.
        """
        steps = [
            {
                "node_id": "process",
                "is_batch": True,
                "batch_errors": 0,
                "batch_error_details": [],
            }
        ]
        lines = _format_batch_errors_section(steps)

        assert len(lines) == 0

    def test_batch_errors_empty_for_non_batch_nodes(self):
        """CORRECTNESS: Non-batch nodes don't show error section.

        Real bug this catches: Regular node errors would be incorrectly formatted
        as batch errors.
        """
        steps = [
            {
                "node_id": "regular_node",
                "status": "failed",
                # No is_batch flag
            }
        ]
        lines = _format_batch_errors_section(steps)

        assert len(lines) == 0


class TestErrorMessageTruncation:
    """Tests for error message truncation."""

    def test_short_message_not_truncated(self):
        """CORRECTNESS: Short messages pass through unchanged.

        Real bug this catches: Unnecessarily truncating short messages would
        remove valuable error context.
        """
        message = "Command failed with exit code 1"
        result = _truncate_error_message(message)

        assert result == message
        assert "..." not in result

    def test_long_message_truncated_at_200_chars(self):
        """UX: Long messages truncated to 200 characters.

        Real bug this catches: Full stack traces would overwhelm error display
        and make output hard to read.
        """
        long_message = "x" * 300
        result = _truncate_error_message(long_message)

        assert len(result) == 200
        assert result.endswith("...")

    def test_truncation_preserves_start_of_message(self):
        """CORRECTNESS: Truncation keeps message start (most important part).

        Real bug this catches: Truncating from the start would remove the most
        relevant error information.
        """
        message = "Important error: " + "x" * 300
        result = _truncate_error_message(message)

        assert result.startswith("Important error:")


class TestExecutionStepFormatting:
    """Tests for execution step formatting dispatch."""

    def test_batch_node_uses_batch_formatting(self):
        """CORRECTNESS: Batch nodes use enhanced formatting with summary.

        Real bug this catches: Batch nodes showing generic format would miss
        the item success/failure counts.
        """
        step = {
            "node_id": "process",
            "status": "completed",
            "duration_ms": 100,
            "is_batch": True,
            "batch_total": 5,
            "batch_success": 5,
            "batch_errors": 0,
        }
        result = _format_execution_step(step)

        assert "5/5 items succeeded" in result

    def test_regular_node_uses_standard_formatting(self):
        """CORRECTNESS: Regular nodes use standard status line format.

        Real bug this catches: Regular nodes showing batch format would be
        confusing and incorrect.
        """
        step = {
            "node_id": "fetch",
            "status": "completed",
            "duration_ms": 100,
        }
        result = _format_execution_step(step)

        assert "✓ fetch" in result
        assert "(100ms)" in result
        assert "items succeeded" not in result  # No batch summary


class TestFormatSuccessAsText:
    """Tests for full text output formatting."""

    def test_batch_node_in_full_output(self):
        """INTEGRATION: Batch node formatting appears in full text output.

        Real bug this catches: Batch formatting might work in isolation but not
        be integrated correctly into format_success_as_text().
        """
        result_dict = {
            "success": True,
            "status": "success",
            "duration_ms": 500,
            "execution": {
                "nodes_executed": 2,
                "steps": [
                    {"node_id": "source", "status": "completed", "duration_ms": 100},
                    {
                        "node_id": "process",
                        "status": "completed",
                        "duration_ms": 400,
                        "is_batch": True,
                        "batch_total": 10,
                        "batch_success": 8,
                        "batch_errors": 2,
                        "batch_error_details": [
                            {"index": 1, "error": "Error 1"},
                            {"index": 4, "error": "Error 2"},
                        ],
                    },
                ],
            },
        }
        text = format_success_as_text(result_dict)

        # Header present
        assert "Workflow completed" in text
        # Regular node present
        assert "✓ source" in text
        # Batch node with partial success
        assert "⚠ process" in text
        assert "8/10 items succeeded" in text
        # Error section present
        assert "Batch 'process' errors:" in text
        assert "[1] Error 1" in text
        assert "[4] Error 2" in text

    def test_batch_full_success_in_full_output(self):
        """INTEGRATION: Fully successful batch shows checkmark.

        Real bug this catches: Batch with 0 errors might incorrectly show
        warning indicator.
        """
        result_dict = {
            "success": True,
            "status": "success",
            "duration_ms": 200,
            "execution": {
                "nodes_executed": 1,
                "steps": [
                    {
                        "node_id": "process",
                        "status": "completed",
                        "duration_ms": 200,
                        "is_batch": True,
                        "batch_total": 5,
                        "batch_success": 5,
                        "batch_errors": 0,
                        "batch_error_details": [],
                    },
                ],
            },
        }
        text = format_success_as_text(result_dict)

        assert "✓ process" in text
        assert "5/5 items succeeded" in text
        assert "Batch 'process' errors:" not in text  # No error section

    def test_multiple_batch_nodes_with_errors(self):
        """INTEGRATION: Multiple batch nodes with errors show all error sections.

        Real bug this catches: Only the first batch node's errors might be shown.
        """
        result_dict = {
            "success": True,
            "status": "success",
            "duration_ms": 500,
            "execution": {
                "nodes_executed": 2,
                "steps": [
                    {
                        "node_id": "batch1",
                        "status": "completed",
                        "duration_ms": 200,
                        "is_batch": True,
                        "batch_total": 5,
                        "batch_success": 4,
                        "batch_errors": 1,
                        "batch_error_details": [{"index": 0, "error": "Batch1 error"}],
                    },
                    {
                        "node_id": "batch2",
                        "status": "completed",
                        "duration_ms": 300,
                        "is_batch": True,
                        "batch_total": 5,
                        "batch_success": 3,
                        "batch_errors": 2,
                        "batch_error_details": [
                            {"index": 1, "error": "Batch2 error 1"},
                            {"index": 2, "error": "Batch2 error 2"},
                        ],
                    },
                ],
            },
        }
        text = format_success_as_text(result_dict)

        # Both batch nodes shown
        assert "⚠ batch1" in text
        assert "⚠ batch2" in text
        # Both error sections present
        assert "Batch 'batch1' errors:" in text
        assert "Batch 'batch2' errors:" in text
        assert "Batch1 error" in text
        assert "Batch2 error 1" in text
        assert "Batch2 error 2" in text


class TestNonBatchNodesUnchanged:
    """Tests ensuring non-batch node formatting is unchanged."""

    def test_regular_completed_node_unchanged(self):
        """REGRESSION: Regular completed nodes use standard format.

        Real bug this catches: Adding batch support could accidentally break
        regular node formatting.
        """
        step = {
            "node_id": "fetch",
            "status": "completed",
            "duration_ms": 100,
        }
        result = _format_execution_step(step)

        assert result == "  ✓ fetch (100ms)"

    def test_regular_failed_node_unchanged(self):
        """REGRESSION: Regular failed nodes use standard format.

        Real bug this catches: Failed node formatting could be broken.
        """
        step = {
            "node_id": "send",
            "status": "failed",
            "duration_ms": 50,
        }
        result = _format_execution_step(step)

        assert result == "  ❌ send (50ms)"

    def test_cached_node_unchanged(self):
        """REGRESSION: Cached nodes show cached tag.

        Real bug this catches: Cached tag formatting could be broken.
        """
        step = {
            "node_id": "fetch",
            "status": "completed",
            "duration_ms": 0,
            "cached": True,
        }
        result = _format_execution_step(step)

        assert result == "  ✓ fetch (0ms) [cached]"

    def test_repaired_node_unchanged(self):
        """REGRESSION: Repaired nodes show repaired tag.

        Real bug this catches: Repaired tag formatting could be broken.
        """
        step = {
            "node_id": "send",
            "status": "completed",
            "duration_ms": 100,
            "repaired": True,
        }
        result = _format_execution_step(step)

        assert result == "  ✓ send (100ms) [repaired]"
