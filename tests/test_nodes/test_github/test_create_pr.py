"""Tests for GitHub PR creation node."""

import json
import subprocess
from unittest.mock import Mock, call, patch

import pytest

from src.pflow.nodes.github.create_pr import GitHubCreatePRNode


class TestGitHubCreatePRNode:
    """Test suite for GitHubCreatePRNode."""

    def test_prep_validates_authentication(self):
        """Test that prep checks GitHub CLI authentication."""
        node = GitHubCreatePRNode()
        node.params = {"title": "Test PR", "body": "Test body", "head": "feature-branch", "base": "main"}
        shared = {}

        with patch("subprocess.run") as mock_run:
            # Mock auth check failure
            mock_run.return_value = Mock(returncode=1)

            with pytest.raises(ValueError, match="GitHub CLI not authenticated"):
                node.prep(shared)

            # Verify auth status was checked
            mock_run.assert_called_once_with(["gh", "auth", "status"], capture_output=True, text=True, timeout=10)

    def test_prep_extracts_required_fields(self):
        """Test that prep extracts and validates required fields."""
        node = GitHubCreatePRNode()

        # Test missing title
        node.params = {"body": "Test body", "head": "feature-branch"}
        shared = {}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)  # Auth success

            with pytest.raises(ValueError, match="requires 'title'"):
                node.prep(shared)

        # Test missing head branch
        node.params = {"title": "Test PR", "body": "Test body"}
        shared = {}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)  # Auth success

            with pytest.raises(ValueError, match="requires 'head' branch"):
                node.prep(shared)

    def test_prep_uses_parameters(self):
        """Test that prep uses parameters."""
        node = GitHubCreatePRNode()
        node.params = {
            "title": "Param Title",
            "body": "Param Body",
            "head": "param-branch",
            "base": "develop",
            "repo": "owner/repo",
        }
        shared = {}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)  # Auth success

            result = node.prep(shared)

            assert result == {
                "title": "Param Title",
                "body": "Param Body",
                "head": "param-branch",
                "base": "develop",
                "repo": "owner/repo",
            }

    def test_exec_two_step_process(self):
        """Test the critical two-step PR creation process."""
        node = GitHubCreatePRNode()

        prep_res = {
            "title": "Test PR",
            "body": "Test description",
            "head": "feature-branch",
            "base": "main",
            "repo": "owner/repo",
        }

        with patch("subprocess.run") as mock_run:
            # Step 1: gh pr create returns URL only (not JSON)
            create_result = Mock(returncode=0, stdout="https://github.com/owner/repo/pull/456\n", stderr="")

            # Step 2: gh pr view returns JSON data
            view_result = Mock(
                returncode=0,
                stdout=json.dumps({
                    "number": 456,
                    "title": "Test PR",
                    "state": "OPEN",
                    "author": {"login": "testuser"},
                }),
                stderr="",
            )

            mock_run.side_effect = [create_result, view_result]

            result = node.exec(prep_res)

            # Verify both commands were called
            assert mock_run.call_count == 2

            # Verify first call (create PR)
            create_call = mock_run.call_args_list[0]
            assert create_call == call(
                [
                    "gh",
                    "pr",
                    "create",
                    "--title",
                    "Test PR",
                    "--body",
                    "Test description",
                    "--base",
                    "main",
                    "--head",
                    "feature-branch",
                    "--repo",
                    "owner/repo",
                ],
                capture_output=True,
                text=True,
                shell=False,
                timeout=30,
            )

            # Verify second call (view PR)
            view_call = mock_run.call_args_list[1]
            assert view_call == call(
                ["gh", "pr", "view", "456", "--json", "number,url,title,state,author", "--repo", "owner/repo"],
                capture_output=True,
                text=True,
                shell=False,
                timeout=30,
            )

            # Verify result includes URL from step 1 and data from step 2
            assert result["pr_data"]["url"] == "https://github.com/owner/repo/pull/456"
            assert result["pr_data"]["number"] == 456
            assert result["pr_data"]["title"] == "Test PR"
            assert result["pr_data"]["state"] == "OPEN"

    def test_exec_parses_pr_number_from_url(self):
        """Test that exec correctly parses PR number from URL."""
        node = GitHubCreatePRNode()

        prep_res = {"title": "Test", "body": "Body", "head": "branch", "base": "main", "repo": None}

        test_cases = [
            "https://github.com/owner/repo/pull/123",
            "https://github.com/org/project/pull/9999",
            "http://github.com/user/repo/pull/1",
        ]

        for url in test_cases:
            with patch("subprocess.run") as mock_run:
                create_result = Mock(returncode=0, stdout=url + "\n", stderr="")
                view_result = Mock(returncode=0, stdout=json.dumps({"number": 123}), stderr="")
                mock_run.side_effect = [create_result, view_result]

                node.exec(prep_res)

                # Extract expected PR number from URL
                import re

                match = re.search(r"/pull/(\d+)", url)
                expected_pr_num = match.group(1)

                # Verify gh pr view was called with correct PR number
                view_call = mock_run.call_args_list[1]
                assert expected_pr_num in view_call[0][0]

    def test_exec_handles_invalid_url(self):
        """Test that exec raises error for invalid URL format."""
        node = GitHubCreatePRNode()

        prep_res = {"title": "Test", "body": "Body", "head": "branch", "base": "main", "repo": None}

        with patch("subprocess.run") as mock_run:
            # Return invalid URL format
            mock_run.return_value = Mock(returncode=0, stdout="not-a-valid-url", stderr="")

            with pytest.raises(ValueError, match="Could not parse PR number from URL"):
                node.exec(prep_res)

    def test_exec_handles_empty_response(self):
        """Test that exec raises error for empty response."""
        node = GitHubCreatePRNode()

        prep_res = {"title": "Test", "body": "Body", "head": "branch", "base": "main", "repo": None}

        with patch("subprocess.run") as mock_run:
            # Return empty response
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            with pytest.raises(ValueError, match="GitHub CLI returned empty response"):
                node.exec(prep_res)

    def test_exec_bubbles_up_exceptions(self):
        """Test that exec does NOT catch exceptions (for retry mechanism)."""
        node = GitHubCreatePRNode()

        prep_res = {"title": "Test", "body": "Body", "head": "branch", "base": "main", "repo": None}

        with patch("subprocess.run") as mock_run:
            # Simulate command failure
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="Error creating PR")

            # Should raise CalledProcessError, not catch it
            with pytest.raises(subprocess.CalledProcessError):
                node.exec(prep_res)

    def test_post_stores_pr_data(self):
        """Test that post stores PR data in shared store."""
        node = GitHubCreatePRNode()
        shared = {}
        prep_res = {}
        exec_res = {
            "pr_data": {
                "number": 456,
                "url": "https://github.com/owner/repo/pull/456",
                "title": "Test PR",
                "state": "OPEN",
                "author": {"login": "testuser"},
            }
        }

        action = node.post(shared, prep_res, exec_res)

        assert shared["pr_data"] == exec_res["pr_data"]
        assert action == "default"

    def test_exec_fallback_transforms_errors(self):
        """Test that exec_fallback provides user-friendly error messages."""
        node = GitHubCreatePRNode()
        prep_res = {"title": "Test PR", "head": "feature", "base": "main", "repo": "owner/repo"}

        # Test various error scenarios
        error_cases = [
            ("gh: command not found", "GitHub CLI .* is not installed"),
            ("authentication required", "GitHub authentication failed"),
            ("repository not found", "Repository .* not found"),
            ("rate limit exceeded", "GitHub API rate limit"),
            ("A pull request already exists", "pull request already exists"),
            ("No commits between", "No changes to create PR"),
            ("branch 'feature' not found", "Branch not found"),
        ]

        for error_msg, expected_pattern in error_cases:
            exc = Exception(error_msg)

            with pytest.raises(ValueError, match=expected_pattern):
                node.exec_fallback(prep_res, exc)

    def test_exec_fallback_generic_error(self):
        """Test that exec_fallback handles unknown errors."""
        node = GitHubCreatePRNode()
        node.max_retries = 3
        prep_res = {"title": "Test PR", "head": "feature", "base": "main", "repo": "owner/repo"}

        exc = Exception("Some unexpected error")

        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)

        error = str(exc_info.value)
        assert "Failed to create PR after 3 attempts" in error
        assert "Title: Test PR" in error
        assert "Head: feature" in error
        assert "Base: main" in error
        assert "Repository: owner/repo" in error
        assert "Some unexpected error" in error

    def test_integration_full_workflow(self):
        """Test complete workflow from prep to post."""
        node = GitHubCreatePRNode()
        node.params = {
            "title": "Integration Test PR",
            "body": "This is a test",
            "head": "feature-xyz",
            "base": "develop",
        }
        shared = {}

        with patch("subprocess.run") as mock_run:
            # Mock successful auth check
            auth_result = Mock(returncode=0)

            # Mock successful PR creation (returns URL)
            create_result = Mock(returncode=0, stdout="https://github.com/test/repo/pull/789\n", stderr="")

            # Mock successful PR view (returns JSON)
            view_result = Mock(
                returncode=0,
                stdout=json.dumps({
                    "number": 789,
                    "title": "Integration Test PR",
                    "state": "OPEN",
                    "author": {"login": "testuser"},
                }),
                stderr="",
            )

            mock_run.side_effect = [auth_result, create_result, view_result]

            # Execute full workflow
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            # Verify final state
            assert shared["pr_data"]["number"] == 789
            assert shared["pr_data"]["url"] == "https://github.com/test/repo/pull/789"
            assert shared["pr_data"]["title"] == "Integration Test PR"
            assert action == "default"

    def test_exec_enforces_security_flags(self):
        """Test that subprocess.run is called with required security flags.

        SECURITY: These flags prevent command injection (shell=False),
        hanging processes (timeout), and ensure proper output handling.
        """
        node = GitHubCreatePRNode()
        node.params = {
            "title": "Security Test PR",
            "body": "Testing security flags",
            "head": "feature-branch",
            "base": "main",
            "repo": "owner/repo",
        }
        shared = {}

        with patch("subprocess.run") as mock_run:
            # Mock auth check, PR creation, and PR view
            auth_result = Mock(returncode=0, stdout="", stderr="")
            create_result = Mock(returncode=0, stdout="https://github.com/owner/repo/pull/123\n", stderr="")
            view_result = Mock(
                returncode=0,
                stdout=json.dumps({"number": 123, "title": "Security Test PR", "state": "OPEN"}),
                stderr="",
            )

            mock_run.side_effect = [auth_result, create_result, view_result]

            # Execute the node
            prep_res = node.prep(shared)
            node.exec(prep_res)

            # CRITICAL: Verify security flags on ALL calls
            # Should have 3 calls: auth check in prep, PR create in exec, PR view in exec
            assert len(mock_run.call_args_list) == 3, f"Expected 3 subprocess calls, got {len(mock_run.call_args_list)}"

            for idx, call in enumerate(mock_run.call_args_list):
                call_kwargs = call[1]  # Get keyword arguments
                call_cmd = call[0][0] if call[0] else []

                # Security assertions
                # shell defaults to False if not specified, so we check it's not explicitly True
                assert call_kwargs.get("shell", False) is False, (
                    f"Security violation: shell=True in call {idx + 1}: {call_cmd}"
                )
                assert call_kwargs.get("timeout") is not None, f"Missing timeout in call {idx + 1}: {call_cmd}"

                # Auth check might have shorter timeout (10s), others should be 30s
                if idx == 0:  # Auth check
                    assert call_kwargs.get("timeout") <= 10, f"Auth timeout too long: {call_kwargs.get('timeout')}"
                else:  # PR operations
                    assert call_kwargs.get("timeout") <= 30, (
                        f"Timeout too long: {call_kwargs.get('timeout')} in call {idx + 1}: {call_cmd}"
                    )

                assert call_kwargs.get("capture_output") is True, (
                    f"Missing capture_output in call {idx + 1}: {call_cmd}"
                )
                assert call_kwargs.get("text") is True, f"Missing text=True in call {idx + 1}: {call_cmd}"

    def test_retry_on_transient_failure(self):
        """Test that transient failures trigger retries and eventually succeed."""
        node = GitHubCreatePRNode(max_retries=2, wait=0)  # wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # Auth checks always succeed
                if args[0] == ["gh", "auth", "status"]:
                    return Mock(returncode=0, stdout="", stderr="")

                # Check if this is a PR create or PR view command
                if "create" in args[0]:
                    # Track create attempts
                    attempt_count += 1

                    # First attempt fails, second succeeds
                    if attempt_count == 1:
                        return Mock(returncode=1, stdout="", stderr="temporary network error")
                    else:
                        return Mock(returncode=0, stdout="https://github.com/owner/repo/pull/456\n", stderr="")
                elif "view" in args[0]:
                    # PR view to get details (only called after successful create)
                    return Mock(
                        returncode=0,
                        stdout=json.dumps({
                            "number": 456,
                            "title": "Test PR",
                            "state": "OPEN",
                            "author": {"login": "testuser"},
                        }),
                        stderr="",
                    )

                # Default
                return Mock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect

            node.params = {
                "title": "Test PR",
                "body": "Test body",
                "head": "feature-branch",
                "base": "main",
                "repo": "owner/repo",
            }
            shared = {}
            action = node.run(shared)

            # Should succeed after retry
            assert action == "default"
            assert attempt_count == 2  # Failed once, succeeded on retry

            # Verify the result was stored correctly
            assert "pr_data" in shared
            assert shared["pr_data"]["number"] == 456
            assert shared["pr_data"]["title"] == "Test PR"
            assert shared["pr_data"]["url"] == "https://github.com/owner/repo/pull/456"

    def test_retry_exhaustion_raises_error(self):
        """Test that error is raised after all retries are exhausted."""
        node = GitHubCreatePRNode(max_retries=1, wait=0)  # Only 1 retry, wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            # All attempts fail with persistent error
            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # Auth checks succeed
                if args[0] == ["gh", "auth", "status"]:
                    return Mock(returncode=0, stdout="", stderr="")

                # Track create attempts
                if "create" in args[0]:
                    attempt_count += 1

                # PR creation always fails
                return Mock(returncode=1, stdout="", stderr="A pull request already exists")

            mock_run.side_effect = side_effect

            node.params = {
                "title": "Test PR",
                "body": "Test body",
                "head": "feature-branch",
                "base": "main",
                "repo": "owner/repo",
            }
            shared = {}

            with pytest.raises(ValueError) as exc_info:
                node.run(shared)

            # Should have tried max_retries times
            assert attempt_count == 1  # max_retries=1 means 1 attempt total

            # Error message should mention failure or the error
            error_msg = str(exc_info.value).lower()
            assert "already exists" in error_msg or "pull request" in error_msg or "failed" in error_msg
