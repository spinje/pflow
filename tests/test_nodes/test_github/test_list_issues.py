"""Tests for GitHubListIssuesNode."""

import subprocess
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

    def test_exec_builds_correct_command(self):
        """Test that exec builds the correct GitHub CLI command."""
        node = ListIssuesNode()

        # Test with all parameters
        prep_res = {"repo": "owner/repo", "state": "closed", "limit": 50}

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
        prep_res = {"repo": None, "state": "open", "limit": 30}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")

            result = node.exec(prep_res)
            assert result["issues"] == []

    def test_exec_raises_on_error(self):
        """Test that exec lets exceptions bubble up for retry."""
        node = ListIssuesNode()
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 30}

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
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 30}

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
