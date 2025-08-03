"""Tests for GitHub get issue node."""

import json
import subprocess
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.pflow.nodes.github.get_issue import GetIssueNode


class TestGetIssueNode:
    """Test GitHub get issue node implementation."""

    def test_node_attributes(self):
        """Test node has required attributes."""
        node = GetIssueNode()
        assert node.name == "github-get-issue"
        assert node.__doc__ is not None
        assert "Interface:" in node.__doc__

    def test_prep_validates_authentication(self):
        """Test prep checks GitHub CLI authentication."""
        node = GetIssueNode()
        shared = {"issue_number": "123"}

        # Mock failed auth check
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)

            with pytest.raises(ValueError, match="GitHub CLI not authenticated"):
                node.prep(shared)

            # Verify auth status was checked
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == ["gh", "auth", "status"]

    def test_prep_validates_issue_number(self):
        """Test prep requires issue_number."""
        node = GetIssueNode()
        shared = {}  # Missing issue_number

        # Mock successful auth
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            with pytest.raises(ValueError, match="requires 'issue_number'"):
                node.prep(shared)

    def test_prep_extracts_inputs_with_fallback(self):
        """Test prep extracts inputs with parameter fallback."""
        node = GetIssueNode()
        node.params = {"issue_number": "456", "repo": "fallback/repo"}

        # Test shared takes precedence
        shared = {"issue_number": "123", "repo": "owner/repo"}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            prep_res = node.prep(shared)

            assert prep_res["issue_number"] == "123"
            assert prep_res["repo"] == "owner/repo"

        # Test fallback to params
        shared = {}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            prep_res = node.prep(shared)

            assert prep_res["issue_number"] == "456"
            assert prep_res["repo"] == "fallback/repo"

    def test_exec_builds_correct_command(self):
        """Test exec builds correct gh command."""
        node = GetIssueNode()
        prep_res = {"issue_number": "123", "repo": "owner/repo"}

        # Mock successful execution
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "number": 123,
                "title": "Test Issue",
                "body": "Issue body",
                "state": "OPEN",
                "author": {"login": "user"},
                "labels": [],
                "assignees": [],
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }),
        )

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = node.exec(prep_res)

            # Verify command construction
            expected_cmd = [
                "gh",
                "issue",
                "view",
                "123",
                "--json",
                "number,title,body,state,author,labels,createdAt,updatedAt,assignees",
                "--repo",
                "owner/repo",
            ]
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == expected_cmd
            assert mock_run.call_args[1]["shell"] is False
            assert mock_run.call_args[1]["timeout"] == 30

            # Verify result
            assert "issue_data" in result
            assert result["issue_data"]["number"] == 123
            assert result["issue_data"]["title"] == "Test Issue"

    def test_exec_no_repo_omits_flag(self):
        """Test exec omits --repo flag when repo is None."""
        node = GetIssueNode()
        prep_res = {"issue_number": "123", "repo": None}

        mock_result = MagicMock(returncode=0, stdout=json.dumps({"number": 123}))

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            node.exec(prep_res)

            # Verify --repo not in command
            cmd = mock_run.call_args[0][0]
            assert "--repo" not in cmd

    def test_exec_raises_on_error(self):
        """Test exec lets exceptions bubble up for retry."""
        node = GetIssueNode()
        prep_res = {"issue_number": "123", "repo": "owner/repo"}

        # Mock failed execution
        mock_result = MagicMock(returncode=1, stdout="", stderr="Issue not found")

        with patch("subprocess.run", return_value=mock_result), pytest.raises(subprocess.CalledProcessError):
            node.exec(prep_res)

    def test_post_stores_results(self):
        """Test post stores issue data in shared store."""
        node = GetIssueNode()
        shared = {}
        prep_res = {}
        exec_res = {"issue_data": {"number": 123, "title": "Test Issue", "state": "OPEN"}}

        action = node.post(shared, prep_res, exec_res)

        assert shared["issue_data"] == exec_res["issue_data"]
        assert action == "default"

    def test_exec_fallback_transforms_errors(self):
        """Test exec_fallback provides user-friendly error messages."""
        node = GetIssueNode()
        prep_res = {"issue_number": "123", "repo": "owner/repo"}

        # Test various error scenarios
        test_cases = [
            ("gh: command not found", r"GitHub CLI \(gh\) is not installed"),
            ("could not resolve to an Issue", "Issue #123 not found"),
            ("authentication required", "GitHub authentication failed"),
            ("repository not found", "Repository 'owner/repo' not found"),
            ("rate limit exceeded", "GitHub API rate limit exceeded"),
            ("generic error", "Failed to fetch issue after 3 attempts"),
        ]

        for error_msg, expected_msg in test_cases:
            exc = Exception(error_msg)
            with pytest.raises(ValueError, match=expected_msg):
                node.exec_fallback(prep_res, exc)

    def test_native_field_preservation(self):
        """Test that native gh field names are preserved."""
        node = GetIssueNode()
        prep_res = {"issue_number": "123", "repo": None}

        # Mock response with native field names
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "createdAt": "2024-01-01T00:00:00Z",  # Not created_at
                "updatedAt": "2024-01-02T00:00:00Z",  # Not updated_at
                "author": {"login": "user"},  # Not user
                "assignees": [{"login": "dev"}],  # Native structure
            }),
        )

        with patch("subprocess.run", return_value=mock_result):
            result = node.exec(prep_res)

            # Verify native field names preserved
            assert "createdAt" in result["issue_data"]
            assert "updatedAt" in result["issue_data"]
            assert "author" in result["issue_data"]
            assert "created_at" not in result["issue_data"]
            assert "updated_at" not in result["issue_data"]
            assert "user" not in result["issue_data"]

    def test_exec_enforces_security_flags(self):
        """Test that subprocess.run is called with required security flags.

        SECURITY: These flags prevent command injection (shell=False),
        hanging processes (timeout), and ensure proper output handling.
        """
        node = GetIssueNode()
        shared = {"issue_number": "123", "repo": "owner/repo"}

        with patch("subprocess.run") as mock_run:
            # Mock auth check and main command
            mock_run.return_value = MagicMock(
                returncode=0, stdout=json.dumps({"number": 123, "title": "Test Issue", "state": "OPEN"}), stderr=""
            )

            # Execute the node
            prep_res = node.prep(shared)
            node.exec(prep_res)

            # CRITICAL: Verify security flags on ALL calls
            # Should have 2 calls: auth check in prep, and issue fetch in exec
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
        node = GetIssueNode(max_retries=2, wait=0)  # wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            # Track attempts
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # Auth checks always succeed
                if args[0] == ["gh", "auth", "status"]:
                    return Mock(returncode=0, stdout="", stderr="")

                # Track fetch attempts
                attempt_count += 1

                # First attempt fails, second succeeds
                if attempt_count == 1:
                    # Return error that triggers retry
                    return Mock(returncode=1, stdout="", stderr="temporary network error")
                else:
                    # Second attempt succeeds
                    return Mock(
                        returncode=0,
                        stdout=json.dumps({"number": 123, "title": "Test Issue", "state": "OPEN"}),
                        stderr="",
                    )

            mock_run.side_effect = side_effect

            shared = {"issue_number": "123", "repo": "owner/repo"}
            action = node.run(shared)

            # Should succeed after retry
            assert action == "default"
            # Verify multiple attempts were made
            assert attempt_count == 2  # Failed once, succeeded on retry

            # Verify the result was stored correctly
            assert "issue_data" in shared
            assert shared["issue_data"]["number"] == 123
            assert shared["issue_data"]["title"] == "Test Issue"

    def test_retry_exhaustion_raises_error(self):
        """Test that error is raised after all retries are exhausted."""
        node = GetIssueNode(max_retries=1, wait=0)  # Only 1 retry, wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            # Track attempts
            attempt_count = 0

            # All attempts fail with persistent error
            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # Auth checks succeed
                if args[0] == ["gh", "auth", "status"]:
                    return Mock(returncode=0, stdout="", stderr="")

                # Track fetch attempts
                attempt_count += 1

                # All issue fetches fail
                return Mock(returncode=1, stdout="", stderr="Issue not found")

            mock_run.side_effect = side_effect

            shared = {"issue_number": "999", "repo": "owner/repo"}

            with pytest.raises(ValueError) as exc_info:
                node.run(shared)

            # Should have tried max_retries times
            assert attempt_count == 1  # max_retries=1 means 1 attempt total

            # Error message should mention the issue number or failure
            error_msg = str(exc_info.value).lower()
            assert "999" in error_msg or "not found" in error_msg or "failed" in error_msg
