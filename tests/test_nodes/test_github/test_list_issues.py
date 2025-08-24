"""Tests for GitHubListIssuesNode."""

import subprocess
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.pflow.nodes.github.list_issues import ListIssuesNode


class TestListIssuesNode:
    """Test suite for GitHubListIssuesNode."""

    def test_prep_validates_authentication(self):
        """Test that prep checks for GitHub CLI authentication."""
        node = ListIssuesNode()
        shared = {}

        with patch("subprocess.run") as mock_run:
            # Simulate authentication failure
            mock_run.return_value = MagicMock(returncode=1)

            with pytest.raises(ValueError) as exc_info:
                node.prep(shared)

            assert "GitHub CLI not authenticated" in str(exc_info.value)
            assert "gh auth login" in str(exc_info.value)

    def test_prep_validates_state(self):
        """Test that prep validates the state parameter."""
        node = ListIssuesNode()
        node.params = {"state": "invalid"}
        shared = {}

        with patch("subprocess.run") as mock_run:
            # Simulate successful authentication
            mock_run.return_value = MagicMock(returncode=0)

            with pytest.raises(ValueError) as exc_info:
                node.prep(shared)

            assert "Invalid issue state 'invalid'" in str(exc_info.value)
            assert "Must be one of: open, closed, all" in str(exc_info.value)

    def test_prep_validates_and_clamps_limit(self):
        """Test that prep validates and clamps the limit parameter."""
        node = ListIssuesNode()

        with patch("subprocess.run") as mock_run:
            # Simulate successful authentication
            mock_run.return_value = MagicMock(returncode=0)

            # Test clamping to minimum
            shared = {"limit": -5}
            result = node.prep(shared)
            assert result["limit"] == 1

            # Test clamping to maximum
            shared = {"limit": 200}
            result = node.prep(shared)
            assert result["limit"] == 100

            # Test valid range
            shared = {"limit": 50}
            result = node.prep(shared)
            assert result["limit"] == 50

            # Test invalid type
            shared = {"limit": "not_a_number"}
            with pytest.raises(ValueError) as exc_info:
                node.prep(shared)
            assert "Invalid limit value" in str(exc_info.value)
            assert "Must be an integer between 1 and 100" in str(exc_info.value)

    def test_prep_parameter_fallback(self):
        """Test the fallback order: shared → params → defaults."""
        node = ListIssuesNode()

        with patch("subprocess.run") as mock_run:
            # Simulate successful authentication
            mock_run.return_value = MagicMock(returncode=0)

            # Test shared takes precedence
            node.params = {"repo": "param/repo", "state": "closed", "limit": 10}
            shared = {"repo": "shared/repo", "state": "all", "limit": 20}
            result = node.prep(shared)
            assert result["repo"] == "shared/repo"
            assert result["state"] == "all"
            assert result["limit"] == 20

            # Test params fallback when shared is empty
            shared = {}
            result = node.prep(shared)
            assert result["repo"] == "param/repo"
            assert result["state"] == "closed"
            assert result["limit"] == 10

            # Test defaults when neither shared nor params have values
            node.params = {}
            result = node.prep(shared)
            assert result["repo"] is None
            assert result["state"] == "open"
            assert result["limit"] == 30
            assert result["since"] is None  # Ensure since is in the result

    def test_exec_builds_correct_command(self):
        """Test that exec builds the correct GitHub CLI command."""
        node = ListIssuesNode()

        # Test with all parameters (but no since, for backward compatibility)
        prep_res = {"repo": "owner/repo", "state": "closed", "limit": 50, "since": None}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='[{"number": 1, "title": "Test Issue"}]')

            result = node.exec(prep_res)

            # Verify command structure
            call_args = mock_run.call_args[0][0]
            assert call_args[:3] == ["gh", "issue", "list"]
            assert "--json" in call_args
            assert "number,title,state,author,labels,createdAt,updatedAt" in call_args
            assert "--repo" in call_args
            assert "owner/repo" in call_args
            assert "--state" in call_args
            assert "closed" in call_args
            assert "--limit" in call_args
            assert "50" in call_args

            # Verify result
            assert result["issues"] == [{"number": 1, "title": "Test Issue"}]

    def test_exec_handles_empty_response(self):
        """Test that exec handles empty issue lists correctly."""
        node = ListIssuesNode()
        prep_res = {"repo": None, "state": "open", "limit": 30, "since": None}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")

            result = node.exec(prep_res)
            assert result["issues"] == []

    def test_exec_raises_on_error(self):
        """Test that exec lets exceptions bubble up for retry."""
        node = ListIssuesNode()
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 30, "since": None}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="repository not found")

            with pytest.raises(subprocess.CalledProcessError):
                node.exec(prep_res)

    def test_post_stores_issues_in_shared(self):
        """Test that post stores the issues list in shared store."""
        node = ListIssuesNode()
        shared = {}
        prep_res = {}
        exec_res = {"issues": [{"number": 1, "title": "Issue 1"}, {"number": 2, "title": "Issue 2"}]}

        action = node.post(shared, prep_res, exec_res)

        assert shared["issues"] == exec_res["issues"]
        assert action == "default"

    def test_exec_fallback_transforms_errors(self):
        """Test that exec_fallback provides user-friendly error messages."""
        node = ListIssuesNode()
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 30, "since": None}

        # Test gh not installed
        exc = Exception("gh: command not found")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)
        assert "GitHub CLI (gh) is not installed" in str(exc_info.value)

        # Test repository not found
        exc = Exception("repository not found")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)
        assert "Repository 'owner/repo' not found" in str(exc_info.value)

        # Test authentication error
        exc = Exception("authentication required")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)
        assert "GitHub authentication failed" in str(exc_info.value)

        # Test rate limit
        exc = Exception("rate limit exceeded")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)
        assert "GitHub API rate limit exceeded" in str(exc_info.value)

        # Test generic error
        exc = Exception("some other error")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)
        assert "Failed to list issues after 3 attempts" in str(exc_info.value)
        assert "Repository: owner/repo" in str(exc_info.value)

    def test_exec_enforces_security_flags(self):
        """Test that subprocess.run is called with required security flags.

        SECURITY: These flags prevent command injection (shell=False),
        hanging processes (timeout), and ensure proper output handling.
        """
        node = ListIssuesNode()
        shared = {"repo": "owner/repo", "state": "open", "limit": 10}

        with patch("subprocess.run") as mock_run:
            # Mock auth check and main command
            mock_run.return_value = MagicMock(returncode=0, stdout='[{"number": 1, "title": "Test Issue"}]', stderr="")

            # Execute the node
            prep_res = node.prep(shared)
            node.exec(prep_res)

            # CRITICAL: Verify security flags on ALL calls
            # Should have 2 calls: auth check in prep, and issue list in exec
            assert len(mock_run.call_args_list) == 2, f"Expected 2 subprocess calls, got {len(mock_run.call_args_list)}"

            for idx, call in enumerate(mock_run.call_args_list):
                call_kwargs = call[1]  # Get keyword arguments
                call_cmd = call[0][0] if call[0] else []

                # Security assertions
                # shell defaults to False if not specified, so we check it's not explicitly True
                assert call_kwargs.get("shell", False) is False, (
                    f"Security violation: shell=True in call {idx + 1}: {call_cmd}"
                )
                assert call_kwargs.get("timeout") is not None, f"Missing timeout in call {idx + 1}: {call_cmd}"
                assert call_kwargs.get("timeout") <= 30, (
                    f"Timeout too long: {call_kwargs.get('timeout')} in call {idx + 1}: {call_cmd}"
                )
                assert call_kwargs.get("capture_output") is True, (
                    f"Missing capture_output in call {idx + 1}: {call_cmd}"
                )
                assert call_kwargs.get("text") is True, f"Missing text=True in call {idx + 1}: {call_cmd}"

    def test_retry_on_transient_failure(self):
        """Test that transient failures trigger retries and eventually succeed."""
        node = ListIssuesNode(max_retries=2, wait=0)  # wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # Auth checks always succeed
                if args[0] == ["gh", "auth", "status"]:
                    return Mock(returncode=0, stdout="", stderr="")

                # Track list attempts
                attempt_count += 1

                # First attempt fails, second succeeds
                if attempt_count == 1:
                    return Mock(returncode=1, stdout="", stderr="temporary network error")
                else:
                    return Mock(
                        returncode=0,
                        stdout='[{"number": 1, "title": "Issue 1"}, {"number": 2, "title": "Issue 2"}]',
                        stderr="",
                    )

            mock_run.side_effect = side_effect

            shared = {"repo": "owner/repo", "state": "open", "limit": 10}
            action = node.run(shared)

            # Should succeed after retry
            assert action == "default"
            assert attempt_count == 2  # Failed once, succeeded on retry

            # Verify the result was stored correctly
            assert "issues" in shared
            assert len(shared["issues"]) == 2
            assert shared["issues"][0]["number"] == 1
            assert shared["issues"][0]["title"] == "Issue 1"

    def test_retry_exhaustion_raises_error(self):
        """Test that error is raised after all retries are exhausted."""
        node = ListIssuesNode(max_retries=1, wait=0)  # Only 1 retry, wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            # All attempts fail with persistent error
            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # Auth checks succeed
                if args[0] == ["gh", "auth", "status"]:
                    return Mock(returncode=0, stdout="", stderr="")

                # Track list attempts
                attempt_count += 1

                # All issue list fetches fail
                return Mock(returncode=1, stdout="", stderr="repository not found")

            mock_run.side_effect = side_effect

            shared = {"repo": "owner/repo", "state": "open", "limit": 30}

            with pytest.raises(ValueError) as exc_info:
                node.run(shared)

            # Should have tried max_retries times
            assert attempt_count == 1  # max_retries=1 means 1 attempt total

            # Error message should mention repository or failure
            error_msg = str(exc_info.value).lower()
            assert "repository" in error_msg or "not found" in error_msg or "failed" in error_msg

    # =====================================================================
    # Date Filtering Feature Tests
    # =====================================================================

    def test_normalize_date_iso_format(self):
        """Test that ISO date formats are correctly normalized to YYYY-MM-DD."""
        node = ListIssuesNode()

        # Test standard ISO date (already in correct format)
        assert node._normalize_date("2025-08-20") == "2025-08-20"

        # Test ISO datetime with time component
        assert node._normalize_date("2025-08-20T10:30:00") == "2025-08-20"
        assert node._normalize_date("2025-08-20T23:59:59.999Z") == "2025-08-20"

        # Test date with leading/trailing whitespace
        assert node._normalize_date("  2025-08-20  ") == "2025-08-20"
        assert node._normalize_date("\t2025-08-20\n") == "2025-08-20"

    def test_normalize_date_relative(self):
        """Test that relative date strings are converted to YYYY-MM-DD format."""
        node = ListIssuesNode()

        # Mock datetime.now() for deterministic testing
        with patch("src.pflow.nodes.github.list_issues.datetime") as mock_datetime:
            mock_now = datetime(2025, 8, 24, 12, 0, 0)
            mock_datetime.now.return_value = mock_now
            mock_datetime.strptime = datetime.strptime  # Keep strptime working

            # Test "yesterday"
            assert node._normalize_date("yesterday") == "2025-08-23"
            assert node._normalize_date("Yesterday") == "2025-08-23"
            assert node._normalize_date("YESTERDAY") == "2025-08-23"

            # Test "today"
            assert node._normalize_date("today") == "2025-08-24"
            assert node._normalize_date("Today") == "2025-08-24"

            # Test "N days ago"
            assert node._normalize_date("7 days ago") == "2025-08-17"
            assert node._normalize_date("1 day ago") == "2025-08-23"
            assert node._normalize_date("30 days ago") == "2025-07-25"

            # Test "N weeks ago"
            assert node._normalize_date("1 week ago") == "2025-08-17"
            assert node._normalize_date("2 weeks ago") == "2025-08-10"
            assert node._normalize_date("4 weeks ago") == "2025-07-27"

            # Test "N months ago" (uses 30-day approximation)
            assert node._normalize_date("1 month ago") == "2025-07-25"
            assert node._normalize_date("2 months ago") == "2025-06-25"
            assert node._normalize_date("3 months ago") == "2025-05-26"

    def test_normalize_date_various_formats(self):
        """Test that various date formats are normalized to YYYY-MM-DD."""
        node = ListIssuesNode()

        # Test slash format (YYYY/MM/DD)
        assert node._normalize_date("2025/08/20") == "2025-08-20"

        # Test US format (MM/DD/YYYY)
        assert node._normalize_date("08/20/2025") == "2025-08-20"

        # Test European format (DD-MM-YYYY)
        assert node._normalize_date("20-08-2025") == "2025-08-20"

    def test_normalize_date_invalid(self):
        """Test that invalid date formats are passed through unchanged."""
        node = ListIssuesNode()

        # Invalid formats should pass through unchanged (GitHub will handle the error)
        assert node._normalize_date("not-a-date") == "not-a-date"
        assert node._normalize_date("abc123") == "abc123"
        assert node._normalize_date("2025-13-45") == "2025-13-45"  # Invalid month/day
        assert node._normalize_date("99 centuries ago") == "99 centuries ago"  # Unsupported unit

    def test_normalize_date_edge_cases(self):
        """Test edge cases for date normalization."""
        node = ListIssuesNode()

        # Test None
        assert node._normalize_date(None) is None

        # Test empty string
        assert node._normalize_date("") is None

        # Test whitespace only
        assert node._normalize_date("   ") is None

    def test_prep_extracts_since_parameter(self):
        """Test that prep correctly extracts the since parameter with proper fallback."""
        node = ListIssuesNode()

        with patch("subprocess.run") as mock_run:
            # Mock successful authentication
            mock_run.return_value = MagicMock(returncode=0)

            # Test shared takes precedence
            node.params = {"since": "2025-08-01"}
            shared = {"since": "2025-08-15"}
            result = node.prep(shared)
            assert result["since"] == "2025-08-15"

            # Test params fallback when shared is empty
            shared = {}
            result = node.prep(shared)
            assert result["since"] == "2025-08-01"

            # Test no since parameter
            node.params = {}
            result = node.prep(shared)
            assert result["since"] is None

    def test_prep_normalizes_since_date(self):
        """Test that prep normalizes the since date during extraction."""
        node = ListIssuesNode()

        with patch("subprocess.run") as mock_run:
            # Mock successful authentication
            mock_run.return_value = MagicMock(returncode=0)

            # Mock datetime for relative dates
            with patch("src.pflow.nodes.github.list_issues.datetime") as mock_datetime:
                mock_now = datetime(2025, 8, 24, 12, 0, 0)
                mock_datetime.now.return_value = mock_now
                mock_datetime.strptime = datetime.strptime

                # Test relative date normalization
                shared = {"since": "7 days ago"}
                result = node.prep(shared)
                assert result["since"] == "2025-08-17"

                # Test ISO datetime normalization
                shared = {"since": "2025-08-20T15:30:00"}
                result = node.prep(shared)
                assert result["since"] == "2025-08-20"

                # Test already normalized date
                shared = {"since": "2025-08-20"}
                result = node.prep(shared)
                assert result["since"] == "2025-08-20"

    def test_exec_with_since_only(self):
        """Test that exec builds correct command with only the since parameter."""
        node = ListIssuesNode()

        # Test with since and default state (open)
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 30, "since": "2025-08-15"}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='[{"number": 1, "title": "Recent Issue"}]')

            result = node.exec(prep_res)

            # Verify the command structure
            call_args = mock_run.call_args[0][0]
            assert call_args[:3] == ["gh", "issue", "list"]
            assert "--search" in call_args

            # Find the search query
            search_idx = call_args.index("--search")
            search_query = call_args[search_idx + 1]

            # Verify search query contains date filter and state
            assert "created:>2025-08-15" in search_query
            assert "is:open" in search_query

            # Verify --state is NOT used when --search is present
            assert "--state" not in call_args

            # Verify result
            assert result["issues"] == [{"number": 1, "title": "Recent Issue"}]

    def test_exec_with_since_and_state(self):
        """Test combining since parameter with different state values."""
        node = ListIssuesNode()

        test_cases = [
            ("open", "is:open"),
            ("closed", "is:closed"),
            ("all", None),  # "all" should not add is: clause
        ]

        for state, expected_state_clause in test_cases:
            prep_res = {"repo": "owner/repo", "state": state, "limit": 30, "since": "2025-08-15"}

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="[]")

                node.exec(prep_res)

                # Verify the command structure
                call_args = mock_run.call_args[0][0]
                assert "--search" in call_args

                # Find the search query
                search_idx = call_args.index("--search")
                search_query = call_args[search_idx + 1]

                # Verify date filter is always present
                assert "created:>2025-08-15" in search_query

                # Verify state clause
                if expected_state_clause:
                    assert expected_state_clause in search_query, (
                        f"Expected '{expected_state_clause}' in query for state='{state}'"
                    )
                else:
                    # For "all" state, there should be no is: clause
                    assert "is:" not in search_query, "Unexpected 'is:' clause in query for state='all'"

    def test_exec_without_since_backward_compat(self):
        """Test that exec maintains backward compatibility when since is not provided."""
        node = ListIssuesNode()

        # Test without since parameter (should use --state flag)
        prep_res = {"repo": "owner/repo", "state": "closed", "limit": 50, "since": None}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='[{"number": 2, "title": "Old Issue"}]')

            result = node.exec(prep_res)

            # Verify the command uses --state, not --search
            call_args = mock_run.call_args[0][0]
            assert "--state" in call_args
            assert "closed" in call_args
            assert "--search" not in call_args

            # Verify other parameters
            assert "--repo" in call_args
            assert "owner/repo" in call_args
            assert "--limit" in call_args
            assert "50" in call_args

            # Verify result
            assert result["issues"] == [{"number": 2, "title": "Old Issue"}]

    def test_exec_fallback_invalid_date_format(self):
        """Test that exec_fallback provides helpful error for invalid date format."""
        node = ListIssuesNode()
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 30, "since": "invalid-date"}

        # Test "Invalid query" error from GitHub
        exc = Exception("Invalid query: created:>invalid-date")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)

        error_msg = str(exc_info.value)
        assert "Invalid date format 'invalid-date'" in error_msg
        assert "Use ISO date" in error_msg
        assert "relative date" in error_msg
        assert "YYYY-MM-DD" in error_msg

    def test_exec_fallback_github_parse_error(self):
        """Test that exec_fallback provides helpful error when GitHub can't parse date."""
        node = ListIssuesNode()
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 30, "since": "bad-format"}

        # Test "could not parse" error from GitHub
        exc = Exception("could not parse 'created:>bad-format'")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)

        error_msg = str(exc_info.value)
        assert "GitHub couldn't parse the date 'bad-format'" in error_msg
        assert "Try using YYYY-MM-DD format" in error_msg
        assert "2025-08-20" in error_msg  # Example format

    def test_full_workflow_with_date_filter(self):
        """Test complete workflow with date filtering from shared store to results."""
        node = ListIssuesNode(max_retries=1, wait=0)

        with patch("subprocess.run") as mock_run:
            # Mock successful auth and issue list
            def side_effect(*args, **kwargs):
                if args[0] == ["gh", "auth", "status"]:
                    return Mock(returncode=0, stdout="", stderr="")
                else:
                    # Return issues created after the date
                    return Mock(
                        returncode=0,
                        stdout='[{"number": 10, "title": "Recent Bug", "createdAt": "2025-08-20T10:00:00Z"}]',
                        stderr="",
                    )

            mock_run.side_effect = side_effect

            # Mock datetime for relative date testing
            with patch("src.pflow.nodes.github.list_issues.datetime") as mock_datetime:
                mock_now = datetime(2025, 8, 24, 12, 0, 0)
                mock_datetime.now.return_value = mock_now
                mock_datetime.strptime = datetime.strptime

                # Run the node with relative date
                shared = {"repo": "owner/repo", "state": "open", "limit": 10, "since": "7 days ago"}
                action = node.run(shared)

                # Verify success
                assert action == "default"
                assert "issues" in shared
                assert len(shared["issues"]) == 1
                assert shared["issues"][0]["number"] == 10
                assert shared["issues"][0]["title"] == "Recent Bug"

                # Verify the command used search with normalized date
                list_call = mock_run.call_args_list[1]  # Second call is the list command
                call_args = list_call[0][0]
                assert "--search" in call_args
                search_idx = call_args.index("--search")
                search_query = call_args[search_idx + 1]
                assert "created:>2025-08-17" in search_query  # 7 days before 2025-08-24

    def test_parse_relative_date_comprehensive(self):
        """Test comprehensive relative date parsing scenarios."""
        node = ListIssuesNode()

        with patch("src.pflow.nodes.github.list_issues.datetime") as mock_datetime:
            mock_now = datetime(2025, 8, 24, 12, 0, 0)
            mock_datetime.now.return_value = mock_now

            # Test singular units
            assert node._parse_relative_date("1 day ago") == "2025-08-23"
            assert node._parse_relative_date("1 week ago") == "2025-08-17"
            assert node._parse_relative_date("1 month ago") == "2025-07-25"

            # Test plural units
            assert node._parse_relative_date("10 days ago") == "2025-08-14"
            assert node._parse_relative_date("3 weeks ago") == "2025-08-03"
            assert node._parse_relative_date("6 months ago") == "2025-02-25"  # 6 * 30 = 180 days

            # Test case insensitivity
            assert node._parse_relative_date("7 DAYS AGO") == "2025-08-17"
            assert node._parse_relative_date("2 Weeks Ago") == "2025-08-10"

            # Test whitespace variations
            assert node._parse_relative_date("  5 days ago  ") == "2025-08-19"
            assert node._parse_relative_date("2   weeks   ago") == "2025-08-10"

            # Test invalid relative dates should raise ValueError
            with pytest.raises(ValueError) as exc_info:
                node._parse_relative_date("5 years ago")  # Unsupported unit
            assert "Cannot parse relative date" in str(exc_info.value)  # Years are not supported

            with pytest.raises(ValueError) as exc_info:
                node._parse_relative_date("next week")  # Future dates not supported
            assert "Cannot parse relative date" in str(exc_info.value)

            with pytest.raises(ValueError) as exc_info:
                node._parse_relative_date("sometime ago")  # Invalid format
            assert "Cannot parse relative date" in str(exc_info.value)

    def test_date_filter_with_retry_mechanism(self):
        """Test that date filtering works correctly with retry mechanism."""
        node = ListIssuesNode(max_retries=2, wait=0)

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # Auth checks always succeed
                if args[0] == ["gh", "auth", "status"]:
                    return Mock(returncode=0, stdout="", stderr="")

                # Track list attempts
                attempt_count += 1

                # First attempt fails with transient error, second succeeds
                if attempt_count == 1:
                    return Mock(returncode=1, stdout="", stderr="temporary network error")
                else:
                    return Mock(
                        returncode=0,
                        stdout='[{"number": 100, "title": "Recent Issue", "createdAt": "2025-08-20T10:00:00Z"}]',
                        stderr="",
                    )

            mock_run.side_effect = side_effect

            shared = {"repo": "owner/repo", "state": "open", "limit": 10, "since": "2025-08-15"}
            action = node.run(shared)

            # Should succeed after retry
            assert action == "default"
            assert attempt_count == 2  # Failed once, succeeded on retry

            # Verify the search query was consistent across retries
            for call in mock_run.call_args_list[1:]:  # Skip auth check
                call_args = call[0][0]
                if "--search" in call_args:
                    search_idx = call_args.index("--search")
                    search_query = call_args[search_idx + 1]
                    assert "created:>2025-08-15" in search_query

    def test_date_filter_security_flags(self):
        """Test that date filtering maintains security flags in subprocess calls."""
        node = ListIssuesNode()
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 10, "since": "2025-08-15"}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="[]")

            node.exec(prep_res)

            # Verify security flags
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs.get("shell", False) is False, "Security violation: shell=True"
            assert call_kwargs.get("timeout") is not None, "Missing timeout"
            assert call_kwargs.get("timeout") <= 30, f"Timeout too long: {call_kwargs.get('timeout')}"
            assert call_kwargs.get("capture_output") is True, "Missing capture_output"
            assert call_kwargs.get("text") is True, "Missing text=True"
