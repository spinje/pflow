"""Tests for GitPushNode."""

import subprocess
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.pflow.nodes.git.push import GitPushNode


class TestGitPushNode:
    """Test suite for GitPushNode."""

    def test_prep_extracts_branch_and_remote_from_params(self):
        """Test that prep extracts branch and remote from params."""
        node = GitPushNode()
        node.params = {"branch": "feature/test", "remote": "upstream"}
        shared = {}

        result = node.prep(shared)

        assert result["branch"] == "feature/test"
        assert result["remote"] == "upstream"
        assert "working_directory" in result

    def test_prep_uses_params_as_fallback(self):
        """Test that prep uses params when shared doesn't have values."""
        node = GitPushNode()
        node.params = {"branch": "main", "remote": "origin"}
        shared = {}

        result = node.prep(shared)

        assert result["branch"] == "main"
        assert result["remote"] == "origin"

    def test_prep_defaults_branch_and_remote(self):
        """Test that prep defaults branch to HEAD and remote to origin."""
        node = GitPushNode()
        shared = {}

        result = node.prep(shared)

        assert result["branch"] == "HEAD"
        assert result["remote"] == "origin"

    @patch("subprocess.run")
    def test_exec_pushes_successfully(self, mock_run):
        """Test that exec pushes to remote successfully."""
        push_result = MagicMock()
        push_result.returncode = 0
        push_result.stdout = "Everything up-to-date"
        push_result.stderr = ""

        mock_run.return_value = push_result

        node = GitPushNode()
        prep_res = {"branch": "main", "remote": "origin", "working_directory": "/test/dir"}

        result = node.exec(prep_res)

        assert result["success"] is True
        assert result["branch"] == "main"
        assert result["remote"] == "origin"
        assert result["reason"] == "pushed"
        assert "Everything up-to-date" in result["details"]

        # Verify subprocess call
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args == ["git", "push", "origin", "main"]

    @patch("subprocess.run")
    def test_exec_handles_rejection(self, mock_run):
        """Test that exec handles push rejection gracefully."""
        push_result = MagicMock()
        push_result.returncode = 1
        push_result.stdout = ""
        push_result.stderr = "! [rejected] main -> main (non-fast-forward)"

        mock_run.return_value = push_result

        node = GitPushNode()
        prep_res = {"branch": "main", "remote": "origin", "working_directory": "/test/dir"}

        result = node.exec(prep_res)

        assert result["success"] is False
        assert result["reason"] == "rejected"
        assert "rejected" in result["details"]

    @patch("subprocess.run")
    def test_exec_raises_on_not_git_repo(self, mock_run):
        """Test that exec raises ValueError for non-git directories."""
        push_result = MagicMock()
        push_result.returncode = 1
        push_result.stdout = ""
        push_result.stderr = "fatal: not a git repository"

        mock_run.return_value = push_result

        node = GitPushNode()
        prep_res = {"branch": "main", "remote": "origin", "working_directory": "/test/dir"}

        with pytest.raises(ValueError, match="not a git repository"):
            node.exec(prep_res)

    @patch("subprocess.run")
    def test_exec_raises_on_other_errors(self, mock_run):
        """Test that exec raises CalledProcessError for other git errors."""
        push_result = MagicMock()
        push_result.returncode = 128
        push_result.stdout = ""
        push_result.stderr = "fatal: Could not read from remote repository"
        push_result.args = ["git", "push", "origin", "main"]

        mock_run.return_value = push_result

        node = GitPushNode()
        prep_res = {"branch": "main", "remote": "origin", "working_directory": "/test/dir"}

        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            node.exec(prep_res)

        assert exc_info.value.returncode == 128

    def test_exec_fallback_handles_errors(self):
        """Test that exec_fallback provides user-friendly error messages."""
        node = GitPushNode()
        prep_res = {"branch": "main", "remote": "origin", "working_directory": "/test/dir"}

        # Test ValueError
        exc = ValueError("Directory '/test/dir' is not a git repository")
        result = node.exec_fallback(prep_res, exc)
        assert "not a git repository" in result["details"]
        assert result["success"] is False
        assert result["reason"] == "error"

        # Test TimeoutExpired
        exc = subprocess.TimeoutExpired(["git"], 30)
        result = node.exec_fallback(prep_res, exc)
        assert "timed out" in result["details"]

        # Test CalledProcessError with authentication error
        exc = subprocess.CalledProcessError(1, ["git"], stderr="Authentication failed")
        result = node.exec_fallback(prep_res, exc)
        assert "authentication" in result["details"].lower()

        # Test CalledProcessError with connection error
        exc = subprocess.CalledProcessError(1, ["git"], stderr="Could not read from remote repository")
        result = node.exec_fallback(prep_res, exc)
        assert "could not connect" in result["details"].lower()

    def test_post_updates_shared_store_on_success(self):
        """Test that post updates shared store with successful push results."""
        node = GitPushNode()
        shared = {}
        prep_res = {}
        exec_res = {"success": True, "branch": "main", "remote": "origin", "reason": "pushed"}

        action = node.post(shared, prep_res, exec_res)

        assert shared["push_result"]["success"] is True
        assert shared["push_result"]["branch"] == "main"
        assert shared["push_result"]["remote"] == "origin"
        assert action == "default"

    def test_post_updates_shared_store_on_failure(self):
        """Test that post updates shared store with failed push results."""
        node = GitPushNode()
        shared = {}
        prep_res = {}
        exec_res = {
            "success": False,
            "branch": "main",
            "remote": "origin",
            "reason": "rejected",
            "details": "Non-fast-forward",
        }

        action = node.post(shared, prep_res, exec_res)

        assert shared["push_result"]["success"] is False
        assert shared["push_result"]["branch"] == "main"
        assert shared["push_result"]["remote"] == "origin"
        assert action == "default"

    @patch("subprocess.run")
    def test_exec_enforces_security_flags(self, mock_run):
        """Test that subprocess.run is called with required security flags.

        SECURITY: These flags prevent command injection (shell=False),
        hanging processes (timeout), and ensure proper output handling.
        """
        node = GitPushNode()
        shared = {"branch": "main", "remote": "origin"}

        # Mock successful git push
        push_result = MagicMock(returncode=0, stdout="Everything up-to-date", stderr="")
        mock_run.return_value = push_result

        # Execute the node
        prep_res = node.prep(shared)
        node.exec(prep_res)

        # CRITICAL: Verify security flags on ALL calls
        # Should have 1 call for git push
        assert len(mock_run.call_args_list) == 1, f"Expected 1 subprocess call, got {len(mock_run.call_args_list)}"

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
            assert call_kwargs.get("capture_output") is True, f"Missing capture_output in call {idx + 1}: {call_cmd}"
            assert call_kwargs.get("text") is True, f"Missing text=True in call {idx + 1}: {call_cmd}"

    def test_retry_on_transient_failure(self):
        """Test that transient failures trigger retries and eventually succeed."""
        node = GitPushNode()
        node.max_retries = 2
        node.wait = 0  # wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count
                attempt_count += 1

                # First attempt fails, second succeeds
                if attempt_count == 1:
                    return Mock(
                        returncode=1,
                        stdout="",
                        stderr="fatal: unable to access 'https://github.com/': Failed to connect",
                    )
                else:
                    return Mock(returncode=0, stdout="Everything up-to-date", stderr="")

            mock_run.side_effect = side_effect

            node.params = {"branch": "main", "remote": "origin"}
            shared = {}
            action = node.run(shared)

            # Should succeed after retry
            assert action == "default"
            assert attempt_count == 2  # Failed once, succeeded on retry

            # Verify the result was stored correctly
            assert "push_result" in shared
            assert shared["push_result"]["success"] is True
            assert shared["push_result"]["branch"] == "main"
            assert shared["push_result"]["remote"] == "origin"

    def test_retry_exhaustion_returns_error(self):
        """Test that error action is returned after all retries are exhausted."""
        node = GitPushNode()
        node.max_retries = 1
        node.wait = 0  # Only 1 retry, wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count
                attempt_count += 1
                # All attempts fail with persistent error
                return Mock(
                    returncode=128,
                    stdout="",
                    stderr="fatal: not a git repository",
                    args=["git", "push", "origin", "main"],
                )

            mock_run.side_effect = side_effect

            node.params = {"branch": "main", "remote": "origin"}
            shared = {}

            # The node will return normally since exec_fallback handles the error
            action = node.run(shared)

            # Should have tried max_retries times
            assert attempt_count == 1  # max_retries=1 means 1 attempt total

            # Check that error action is returned to trigger repair
            assert action == "error"
            # Error should be stored in shared store
            assert "error" in shared
            assert "not a git repository" in shared["error"]
            # Push result should also be stored with failure status
            assert "push_result" in shared
            assert shared["push_result"]["success"] is False
            assert shared["push_result"]["branch"] == "main"
            assert shared["push_result"]["remote"] == "origin"
