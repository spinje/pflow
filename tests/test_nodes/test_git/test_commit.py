"""Tests for GitCommitNode."""

import subprocess
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.pflow.nodes.git.commit import GitCommitNode


class TestGitCommitNode:
    """Test suite for GitCommitNode."""

    def test_prep_extracts_message_from_shared(self):
        """Test that prep extracts commit message from shared store."""
        node = GitCommitNode()
        shared = {"message": "Test commit message", "files": ["file1.txt", "file2.txt"]}

        result = node.prep(shared)

        assert result["message"] == "Test commit message"
        assert result["files"] == ["file1.txt", "file2.txt"]
        assert "working_directory" in result

    def test_prep_uses_params_as_fallback(self):
        """Test that prep uses params when shared doesn't have values."""
        node = GitCommitNode()
        node.params = {"message": "Param commit message", "files": ["param_file.txt"]}
        shared = {}

        result = node.prep(shared)

        assert result["message"] == "Param commit message"
        assert result["files"] == ["param_file.txt"]

    def test_prep_defaults_files_to_dot(self):
        """Test that prep defaults files to ['.'] when not provided."""
        node = GitCommitNode()
        shared = {"message": "Test commit"}

        result = node.prep(shared)

        assert result["files"] == ["."]

    def test_prep_converts_string_files_to_list(self):
        """Test that prep converts string files to list."""
        node = GitCommitNode()
        shared = {"message": "Test commit", "files": "single_file.txt"}

        result = node.prep(shared)

        assert result["files"] == ["single_file.txt"]

    def test_prep_raises_without_message(self):
        """Test that prep raises ValueError when no message provided."""
        node = GitCommitNode()
        shared = {}

        with pytest.raises(ValueError, match="Commit message is required"):
            node.prep(shared)

    @patch("subprocess.run")
    def test_exec_stages_and_commits(self, mock_run):
        """Test that exec stages files and creates commit."""
        # Setup mock responses
        add_result = MagicMock()
        add_result.returncode = 0
        add_result.stdout = ""
        add_result.stderr = ""

        commit_result = MagicMock()
        commit_result.returncode = 0
        commit_result.stdout = "[main abc1234] Test commit message"
        commit_result.stderr = ""

        mock_run.side_effect = [add_result, commit_result]

        node = GitCommitNode()
        prep_res = {"message": "Test commit message", "files": ["file1.txt"], "working_directory": "/test/dir"}

        result = node.exec(prep_res)

        assert result["commit_sha"] == "abc1234"
        assert result["commit_message"] == "Test commit message"
        assert result["status"] == "committed"

        # Verify subprocess calls
        assert mock_run.call_count == 2
        add_call = mock_run.call_args_list[0]
        assert add_call[0][0] == ["git", "add", "file1.txt"]

        commit_call = mock_run.call_args_list[1]
        assert commit_call[0][0] == ["git", "commit", "-m", "Test commit message"]

    @patch("subprocess.run")
    def test_exec_handles_nothing_to_commit(self, mock_run):
        """Test that exec handles 'nothing to commit' case."""
        add_result = MagicMock()
        add_result.returncode = 0

        commit_result = MagicMock()
        commit_result.returncode = 1
        commit_result.stdout = "nothing to commit, working tree clean"
        commit_result.stderr = ""

        mock_run.side_effect = [add_result, commit_result]

        node = GitCommitNode()
        prep_res = {"message": "Test commit", "files": ["."], "working_directory": "/test/dir"}

        result = node.exec(prep_res)

        assert result["commit_sha"] == ""
        assert result["status"] == "nothing_to_commit"

    @patch("subprocess.run")
    def test_exec_raises_on_not_git_repo(self, mock_run):
        """Test that exec raises ValueError for non-git directories."""
        add_result = MagicMock()
        add_result.returncode = 1
        add_result.stderr = "fatal: not a git repository"

        mock_run.return_value = add_result

        node = GitCommitNode()
        prep_res = {"message": "Test commit", "files": ["."], "working_directory": "/test/dir"}

        with pytest.raises(ValueError, match="not a git repository"):
            node.exec(prep_res)

    @patch("subprocess.run")
    def test_exec_uses_rev_parse_fallback(self, mock_run):
        """Test that exec uses git rev-parse as fallback for SHA."""
        add_result = MagicMock()
        add_result.returncode = 0

        commit_result = MagicMock()
        commit_result.returncode = 0
        commit_result.stdout = "Commit created"  # No SHA in output

        rev_parse_result = MagicMock()
        rev_parse_result.returncode = 0
        rev_parse_result.stdout = "def567890abcdef"

        mock_run.side_effect = [add_result, commit_result, rev_parse_result]

        node = GitCommitNode()
        prep_res = {"message": "Test commit", "files": ["."], "working_directory": "/test/dir"}

        result = node.exec(prep_res)

        assert result["commit_sha"] == "def5678"  # First 7 chars

    def test_exec_fallback_handles_errors(self):
        """Test that exec_fallback provides user-friendly error messages."""
        node = GitCommitNode()
        prep_res = {"message": "Test commit", "working_directory": "/test/dir"}

        # Test ValueError
        exc = ValueError("Directory '/test/dir' is not a git repository")
        result = node.exec_fallback(prep_res, exc)
        assert "not a git repository" in result["error"]
        assert result["status"] == "error"

        # Test TimeoutExpired
        exc = subprocess.TimeoutExpired(["git"], 30)
        result = node.exec_fallback(prep_res, exc)
        assert "timed out" in result["error"]

        # Test CalledProcessError
        exc = subprocess.CalledProcessError(1, ["git"], stderr="permission denied")
        result = node.exec_fallback(prep_res, exc)
        assert "permission denied" in result["error"]

    def test_post_updates_shared_store(self):
        """Test that post updates shared store with commit results."""
        node = GitCommitNode()
        shared = {}
        prep_res = {}
        exec_res = {"commit_sha": "abc1234", "commit_message": "Test commit", "status": "committed"}

        action = node.post(shared, prep_res, exec_res)

        assert shared["commit_sha"] == "abc1234"
        assert shared["commit_message"] == "Test commit"
        assert action == "default"

    def test_post_handles_error_status(self):
        """Test that post handles error status correctly."""
        node = GitCommitNode()
        shared = {}
        prep_res = {}
        exec_res = {
            "commit_sha": "",
            "commit_message": "Test commit",
            "status": "error",
            "error": "Some error occurred",
        }

        action = node.post(shared, prep_res, exec_res)

        # The node should return "error" action to trigger repair
        assert shared["commit_sha"] == ""
        assert shared["commit_message"] == "Test commit"
        assert shared["error"] == "Some error occurred"
        assert shared["commit_status"] == "error"
        assert action == "error"  # CORRECT: Returns error to trigger repair

    @patch("subprocess.run")
    def test_exec_enforces_security_flags(self, mock_run):
        """Test that subprocess.run is called with required security flags.

        SECURITY: These flags prevent command injection (shell=False),
        hanging processes (timeout), and ensure proper output handling.
        """
        node = GitCommitNode()
        shared = {"message": "Security test commit", "files": ["test.txt"]}

        # Mock successful git add and commit
        add_result = MagicMock(returncode=0, stdout="", stderr="")
        commit_result = MagicMock(returncode=0, stdout="[main abc1234] Security test commit", stderr="")
        mock_run.side_effect = [add_result, commit_result]

        # Execute the node
        prep_res = node.prep(shared)
        node.exec(prep_res)

        # CRITICAL: Verify security flags on ALL calls
        # Should have 2 calls: git add and git commit
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
            assert call_kwargs.get("capture_output") is True, f"Missing capture_output in call {idx + 1}: {call_cmd}"
            assert call_kwargs.get("text") is True, f"Missing text=True in call {idx + 1}: {call_cmd}"

    def test_retry_on_transient_failure(self):
        """Test that transient failures trigger retries and eventually succeed."""
        node = GitCommitNode()
        node.max_retries = 2
        node.wait = 0  # wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # Check if this is git add or git commit
                if "add" in args[0]:
                    # git add always succeeds
                    return Mock(returncode=0, stdout="", stderr="")
                elif "commit" in args[0]:
                    # Track commit attempts
                    attempt_count += 1

                    # First attempt fails, second succeeds
                    if attempt_count == 1:
                        return Mock(
                            returncode=1, stdout="", stderr="fatal: Unable to create '.git/index.lock': File exists"
                        )
                    else:
                        return Mock(returncode=0, stdout="[main def5678] Test commit", stderr="")
                else:
                    # Default for other commands
                    return Mock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect

            shared = {"message": "Test commit", "files": ["file.txt"]}
            action = node.run(shared)

            # Should succeed after retry
            assert action == "default"
            assert attempt_count == 2  # Failed once, succeeded on retry

            # Verify the result was stored correctly
            assert "commit_sha" in shared
            assert shared["commit_sha"] == "def5678"
            assert shared["commit_message"] == "Test commit"

    def test_retry_exhaustion_returns_error(self):
        """Test that error action is returned after all retries are exhausted."""
        node = GitCommitNode()
        node.max_retries = 1
        node.wait = 0  # Only 1 retry, wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            # All attempts fail with persistent error
            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # git add succeeds
                if "add" in args[0]:
                    return Mock(returncode=0, stdout="", stderr="")
                elif "commit" in args[0]:
                    # Track commit attempts
                    attempt_count += 1
                    # git commit always fails
                    return Mock(returncode=128, stdout="", stderr="fatal: not a git repository")
                else:
                    return Mock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect

            shared = {"message": "Test commit", "files": ["."]}

            # The exec_fallback returns a dict with error info, not raising an exception
            action = node.run(shared)

            # Should have tried max_retries times
            assert attempt_count == 1  # max_retries=1 means 1 attempt total

            # Check that error was handled correctly
            assert action == "error"  # CORRECT: Returns error to trigger repair
            assert "commit_sha" in shared
            assert shared["commit_sha"] == ""
            assert shared["commit_message"] == "Test commit"
            assert shared["commit_status"] == "error"
            assert "error" in shared
            assert "not a git repository" in shared["error"]
