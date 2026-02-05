"""Tests for execution history formatter."""

from datetime import datetime, timedelta

import pytest

from pflow.execution.formatters.history_formatter import (
    _format_parameters,
    _format_relative_time,
    format_execution_history,
    format_timestamp,
    format_workflow_history,
)


class TestFormatExecutionHistory:
    """Tests for format_execution_history function."""

    def test_compact_mode_with_all_fields(self):
        """Test compact mode displays all fields in single line."""
        rich_metadata = {
            "execution_count": 5,
            "last_execution_timestamp": "2025-10-18T22:01:49.857930",
            "last_execution_success": True,
        }

        result = format_execution_history(rich_metadata, mode="compact")

        assert "5 times" in result
        assert "Last: 2025-10-18 22:01" in result
        assert "Status: ✓ Success" in result
        assert "|" in result  # Pipe separator

    def test_compact_mode_with_failure(self):
        """Test compact mode shows failure status."""
        rich_metadata = {
            "execution_count": 2,
            "last_execution_timestamp": "2025-10-18T22:01:49.857930",
            "last_execution_success": False,
        }

        result = format_execution_history(rich_metadata, mode="compact")

        assert "2 times" in result
        assert "Status: ✗ Failed" in result

    def test_compact_mode_singular_time(self):
        """Test compact mode uses singular 'time' for count of 1."""
        rich_metadata = {
            "execution_count": 1,
            "last_execution_timestamp": "2025-10-18T22:01:49.857930",
            "last_execution_success": True,
        }

        result = format_execution_history(rich_metadata, mode="compact")

        assert "1 time |" in result

    def test_detailed_mode_with_parameters(self):
        """Test detailed mode shows parameters."""
        rich_metadata = {
            "execution_count": 3,
            "last_execution_timestamp": "2025-10-18T22:01:49.857930",
            "last_execution_success": True,
            "last_execution_params": {
                "channel": "C09C16NAU5B",
                "limit": 20,
                "api_key": "<REDACTED>",
            },
        }

        result = format_execution_history(rich_metadata, mode="detailed")

        assert "Runs: 3 times" in result
        assert "Last: 2025-10-18 22:01:49" in result
        assert "Status: ✓ Success" in result
        assert "Last Parameters:" in result
        assert "channel=C09C16NAU5B" in result
        assert "limit=20" in result
        assert "api_key=<REDACTED>" in result

    def test_no_execution_count_returns_none(self):
        """Test returns None when no execution count."""
        rich_metadata = {}
        result = format_execution_history(rich_metadata, mode="compact")
        assert result is None

    def test_zero_execution_count_returns_none(self):
        """Test returns None when execution count is 0."""
        rich_metadata = {"execution_count": 0}
        result = format_execution_history(rich_metadata, mode="compact")
        assert result is None

    def test_none_metadata_returns_none(self):
        """Test returns None when metadata is None."""
        result = format_execution_history(None, mode="compact")
        assert result is None

    def test_invalid_mode_raises_error(self):
        """Test invalid mode raises ValueError."""
        rich_metadata = {"execution_count": 1}
        with pytest.raises(ValueError, match="Invalid mode"):
            format_execution_history(rich_metadata, mode="invalid")


class TestFormatTimestamp:
    """Tests for format_timestamp function."""

    def test_short_mode_formats_without_seconds(self):
        """Test short mode shows date and time without seconds."""
        ts = "2025-10-18T22:01:49.857930"
        result = format_timestamp(ts, mode="short")
        assert result == "2025-10-18 22:01"

    def test_full_mode_includes_seconds(self):
        """Test full mode shows complete timestamp."""
        ts = "2025-10-18T22:01:49.857930"
        result = format_timestamp(ts, mode="full")
        assert result == "2025-10-18 22:01:49"

    def test_relative_mode_just_now(self):
        """Test relative mode shows 'just now' for recent times."""
        now = datetime.now()
        ts = now.isoformat()
        result = format_timestamp(ts, mode="relative")
        assert result == "just now"

    def test_relative_mode_minutes(self):
        """Test relative mode shows minutes."""
        past = datetime.now() - timedelta(minutes=5)
        ts = past.isoformat()
        result = format_timestamp(ts, mode="relative")
        assert "5 minutes ago" in result

    def test_relative_mode_hours(self):
        """Test relative mode shows hours."""
        past = datetime.now() - timedelta(hours=3)
        ts = past.isoformat()
        result = format_timestamp(ts, mode="relative")
        assert "3 hours ago" in result

    def test_relative_mode_days(self):
        """Test relative mode shows days."""
        past = datetime.now() - timedelta(days=2)
        ts = past.isoformat()
        result = format_timestamp(ts, mode="relative")
        assert "2 days ago" in result

    def test_handles_timezone_aware_timestamps(self):
        """Test handles timestamps with timezone info."""
        ts = "2025-10-18T22:01:49.857930+00:00"
        result = format_timestamp(ts, mode="short")
        assert "2025-10-18" in result

    def test_handles_zulu_time(self):
        """Test handles Z suffix for UTC."""
        ts = "2025-10-18T22:01:49.857930Z"
        result = format_timestamp(ts, mode="short")
        assert "2025-10-18" in result

    def test_invalid_timestamp_returns_original(self):
        """Test returns original string if parsing fails."""
        invalid_ts = "not-a-timestamp"
        result = format_timestamp(invalid_ts, mode="short")
        assert result == invalid_ts

    def test_invalid_mode_raises_error(self):
        """Test invalid mode raises ValueError."""
        ts = "2025-10-18T22:01:49.857930"
        with pytest.raises(ValueError, match="Invalid mode"):
            format_timestamp(ts, mode="invalid")


class TestFormatParameters:
    """Tests for _format_parameters function."""

    def test_formats_simple_parameters(self):
        """Test formats simple key-value pairs."""
        params = {"channel": "C09", "limit": 20}
        result = _format_parameters(params)
        assert result == "channel=C09, limit=20"

    def test_shows_redacted_values(self):
        """Test includes <REDACTED> for sensitive params."""
        params = {"api_key": "<REDACTED>", "channel": "C09"}
        result = _format_parameters(params)
        assert "api_key=<REDACTED>" in result
        assert "channel=C09" in result

    def test_empty_params_shows_none(self):
        """Test empty params shows (none)."""
        params = {}
        result = _format_parameters(params)
        assert result == "(none)"

    def test_truncates_long_output(self):
        """Test truncates output exceeding max_length."""
        params = {"very_long_param_name_" + str(i): f"value{i}" for i in range(20)}
        result = _format_parameters(params, max_length=50)
        assert len(result) <= 53  # 50 + "..."
        assert result.endswith("...")


class TestFormatRelativeTime:
    """Tests for _format_relative_time function."""

    def test_singular_forms(self):
        """Test uses singular form for 1 unit."""
        # 1 minute
        past = datetime.now() - timedelta(minutes=1)
        result = _format_relative_time(past)
        assert "1 minute ago" in result

        # 1 hour
        past = datetime.now() - timedelta(hours=1)
        result = _format_relative_time(past)
        assert "1 hour ago" in result

        # 1 day
        past = datetime.now() - timedelta(days=1)
        result = _format_relative_time(past)
        assert "1 day ago" in result

    def test_plural_forms(self):
        """Test uses plural form for multiple units."""
        # Multiple minutes
        past = datetime.now() - timedelta(minutes=5)
        result = _format_relative_time(past)
        assert "5 minutes ago" in result

        # Multiple hours
        past = datetime.now() - timedelta(hours=3)
        result = _format_relative_time(past)
        assert "3 hours ago" in result

    def test_weeks_and_months(self):
        """Test formats weeks and months."""
        # Weeks
        past = datetime.now() - timedelta(weeks=2)
        result = _format_relative_time(past)
        assert "2 weeks ago" in result

        # Months (approximate)
        past = datetime.now() - timedelta(days=60)
        result = _format_relative_time(past)
        assert "2 months ago" in result

    def test_years(self):
        """Test formats years."""
        past = datetime.now() - timedelta(days=400)
        result = _format_relative_time(past)
        assert "1 year ago" in result


class TestIntegrationWithFormatters:
    """Integration tests with discovery and describe formatters."""

    def test_discovery_formatter_shows_history(self):
        """Test discovery formatter includes execution history."""
        from pflow.execution.formatters.discovery_formatter import (
            format_workflow_metadata,
        )

        workflow = {
            "metadata": {
                "description": "Test workflow",
                "version": "1.0.0",
            },
            "execution_count": 5,
            "last_execution_timestamp": "2025-10-18T22:01:49",
            "last_execution_success": True,
        }

        result = format_workflow_metadata(workflow)

        # Should include execution history
        assert any("Executed" in line for line in result)
        assert any("5 times" in line for line in result)

    def test_describe_formatter_shows_history(self):
        """Test describe formatter includes execution history."""
        from pflow.execution.formatters.workflow_describe_formatter import (
            format_workflow_interface,
        )

        metadata = {
            "description": "Test workflow",
            "ir": {"inputs": {}, "outputs": {}},
            "execution_count": 3,
            "last_execution_timestamp": "2025-10-18T22:01:49",
            "last_execution_success": True,
            "last_execution_params": {"param": "value"},
        }

        result = format_workflow_interface("test-workflow", metadata)

        # Should include execution history section
        assert "Execution History:" in result
        assert "Runs: 3 times" in result
        assert "param=value" in result

    def test_formatters_handle_no_history(self):
        """Test formatters gracefully handle workflows without history."""
        from pflow.execution.formatters.discovery_formatter import (
            format_workflow_metadata,
        )
        from pflow.execution.formatters.workflow_describe_formatter import (
            format_workflow_interface,
        )

        workflow = {
            "metadata": {
                "description": "Test workflow",
                "version": "1.0.0",
            },
        }

        # Discovery formatter should not show history
        result = format_workflow_metadata(workflow)
        assert not any("Executed" in line for line in result)

        # Describe formatter should not show history
        metadata = {"description": "Test workflow", "ir": {"inputs": {}, "outputs": {}}}
        result = format_workflow_interface("test-workflow", metadata)
        assert "Execution History:" not in result


class TestFormatWorkflowHistory:
    """Tests for format_workflow_history function (workflow history command)."""

    def test_formats_history_with_inputs(self):
        """Test formats complete history including last used inputs."""
        metadata = {
            "execution_count": 5,
            "last_execution_timestamp": "2026-02-05T02:22:06.123456",
            "last_execution_success": True,
            "last_execution_params": {
                "slack_channel": "C09ABC123",
                "version": "1.2.0",
            },
        }

        result = format_workflow_history("release-announcements", metadata)

        # Core data agent needs: workflow name, run count, timestamp, status, inputs
        assert "Execution History: release-announcements" in result
        assert "Runs: 5" in result
        assert "Last run: 2026-02-05 02:22:06" in result
        assert "Status: Success" in result
        assert "Last used inputs:" in result
        assert "slack_channel: C09ABC123" in result
        assert "version: 1.2.0" in result

    def test_no_history_message_when_never_executed(self):
        """Test returns clear message when workflow has never been executed."""
        # This is the key edge case - agent needs to know there's no history
        result = format_workflow_history("new-workflow", {"execution_count": 0})
        assert result == "No execution history for 'new-workflow'."

        # Also handles None/empty metadata gracefully
        assert format_workflow_history("empty", {}) == "No execution history for 'empty'."
        assert format_workflow_history("none", None) == "No execution history for 'none'."
