"""Tests for GitStatusNode."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.pflow.nodes.git.status import GitStatusNode


@pytest.fixture
def git_status_node():
    """Create a GitStatusNode instance for testing."""
    return GitStatusNode()


@pytest.fixture
def shared_store():
    """Create a shared store for testing."""
    return {}


class TestGitStatusNode:
    """Test suite for GitStatusNode."""

    def test_init(self, git_status_node):
        """Test node initialization."""
        assert git_status_node.max_retries == 2
        assert git_status_node.wait == 0.5

    def test_prep_default_directory(self, git_status_node, shared_store):
        """Test prep with default current directory."""
        result = git_status_node.prep(shared_store)
        # Should resolve to current directory
        assert result == str(Path(".").resolve())

    def test_prep_with_shared_directory(self, git_status_node, shared_store):
        """Test prep with directory from shared store."""
        test_dir = Path.cwd() / "test_dir"
        shared_store["working_directory"] = str(test_dir)
        result = git_status_node.prep(shared_store)
        assert result == str(test_dir.resolve())

    def test_prep_with_params_directory(self, git_status_node, shared_store):
        """Test prep with directory from params."""
        params_dir = Path.cwd() / "params_dir"
        git_status_node.params = {"working_directory": str(params_dir)}
        result = git_status_node.prep(shared_store)
        assert result == str(params_dir.resolve())

    def test_prep_shared_overrides_params(self, git_status_node, shared_store):
        """Test that shared store overrides params."""
        shared_dir = Path.cwd() / "shared_dir"
        params_dir = Path.cwd() / "params_dir"
        shared_store["working_directory"] = str(shared_dir)
        git_status_node.params = {"working_directory": str(params_dir)}
        result = git_status_node.prep(shared_store)
        assert result == str(shared_dir.resolve())

    @patch("subprocess.run")
    def test_exec_clean_repo(self, mock_run, git_status_node):
        """Test exec with a clean repository."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """# branch.head main
# branch.ab +0 -0"""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = git_status_node.exec("/test/repo")

        assert result == {"modified": [], "untracked": [], "staged": [], "branch": "main", "ahead": 0, "behind": 0}

        mock_run.assert_called_once_with(
            ["git", "status", "--porcelain=v2", "--branch"],
            cwd="/test/repo",
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
            check=False,
        )

    @patch("subprocess.run")
    def test_exec_with_modified_files(self, mock_run, git_status_node):
        """Test exec with modified files."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """# branch.head feature-branch
# branch.ab +2 -1
1 .M N... 100644 100644 100644 abc123 def456 file1.py
1 .M N... 100644 100644 100644 abc123 def456 file2.py"""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = git_status_node.exec("/test/repo")

        assert result == {
            "modified": ["file1.py", "file2.py"],
            "untracked": [],
            "staged": [],
            "branch": "feature-branch",
            "ahead": 2,
            "behind": 1,
        }

    @patch("subprocess.run")
    def test_exec_with_staged_files(self, mock_run, git_status_node):
        """Test exec with staged files."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """# branch.head main
# branch.ab +0 -0
1 M. N... 100644 100644 100644 abc123 def456 staged.py
1 A. N... 000000 100644 100644 000000 def456 new_file.py"""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = git_status_node.exec("/test/repo")

        assert result == {
            "modified": [],
            "untracked": [],
            "staged": ["new_file.py", "staged.py"],  # Sorted
            "branch": "main",
            "ahead": 0,
            "behind": 0,
        }

    @patch("subprocess.run")
    def test_exec_with_untracked_files(self, mock_run, git_status_node):
        """Test exec with untracked files."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """# branch.head main
# branch.ab +0 -0
? untracked1.txt
? untracked2.py"""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = git_status_node.exec("/test/repo")

        assert result == {
            "modified": [],
            "untracked": ["untracked1.txt", "untracked2.py"],
            "staged": [],
            "branch": "main",
            "ahead": 0,
            "behind": 0,
        }

    @patch("subprocess.run")
    def test_exec_with_mixed_changes(self, mock_run, git_status_node):
        """Test exec with mixed file changes."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """# branch.head develop
# branch.ab +3 -2
1 MM N... 100644 100644 100644 abc123 def456 both.py
1 M. N... 100644 100644 100644 abc123 def456 staged_only.py
1 .M N... 100644 100644 100644 abc123 def456 modified_only.py
? new_file.txt"""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = git_status_node.exec("/test/repo")

        assert result == {
            "modified": ["both.py", "modified_only.py"],  # Sorted
            "untracked": ["new_file.txt"],
            "staged": ["both.py", "staged_only.py"],  # Sorted
            "branch": "develop",
            "ahead": 3,
            "behind": 2,
        }

    @patch("subprocess.run")
    def test_exec_not_git_repository(self, mock_run, git_status_node):
        """Test exec when not in a git repository."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: not a git repository (or any of the parent directories): .git"
        mock_run.return_value = mock_result

        with pytest.raises(ValueError) as exc_info:
            git_status_node.exec("/not/a/repo")

        assert "is not a git repository" in str(exc_info.value)

    @patch("subprocess.run")
    def test_exec_git_error(self, mock_run, git_status_node):
        """Test exec with other git errors."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "fatal: some other git error"
        mock_run.return_value = mock_result

        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            git_status_node.exec("/test/repo")

        assert exc_info.value.returncode == 1

    @patch("subprocess.run")
    def test_exec_timeout(self, mock_run, git_status_node):
        """Test exec with command timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(["git", "status"], timeout=30)

        with pytest.raises(subprocess.TimeoutExpired):
            git_status_node.exec("/test/repo")

    def test_exec_fallback_not_git_repo(self, git_status_node):
        """Test exec_fallback with not a git repository error."""
        exc = ValueError("Directory '/test' is not a git repository")
        result = git_status_node.exec_fallback("/test", exc)

        assert "error" in result
        assert "not a git repository" in result["error"]
        assert result["branch"] == "unknown"
        assert result["modified"] == []
        assert result["untracked"] == []
        assert result["staged"] == []

    def test_exec_fallback_timeout(self, git_status_node):
        """Test exec_fallback with timeout error."""
        exc = subprocess.TimeoutExpired(["git", "status"], timeout=30)
        result = git_status_node.exec_fallback("/test", exc)

        assert "error" in result
        assert "timed out" in result["error"]

    def test_exec_fallback_git_command_failed(self, git_status_node):
        """Test exec_fallback with git command failure."""
        exc = subprocess.CalledProcessError(1, ["git", "status"], stderr="Permission denied")
        result = git_status_node.exec_fallback("/test", exc)

        assert "error" in result
        assert "exit code 1" in result["error"]
        assert "Permission denied" in result["error"]

    def test_exec_fallback_git_not_installed(self, git_status_node):
        """Test exec_fallback when git is not installed."""
        exc = FileNotFoundError("git not found")
        result = git_status_node.exec_fallback("/test", exc)

        assert "error" in result
        assert "Git is not installed" in result["error"]

    def test_exec_fallback_generic_error(self, git_status_node):
        """Test exec_fallback with generic error."""
        exc = Exception("Unknown error")
        result = git_status_node.exec_fallback("/test", exc)

        assert "error" in result
        assert "Unknown error" in result["error"]

    def test_post_success(self, git_status_node, shared_store):
        """Test post with successful execution."""
        exec_res = {
            "modified": ["file1.py"],
            "untracked": ["file2.py"],
            "staged": ["file3.py"],
            "branch": "main",
            "ahead": 1,
            "behind": 0,
        }

        action = git_status_node.post(shared_store, "/test", exec_res)

        assert shared_store["git_status"] == exec_res
        assert action == "default"

    def test_post_with_error(self, git_status_node, shared_store):
        """Test post with error in exec_res."""
        exec_res = {
            "modified": [],
            "untracked": [],
            "staged": [],
            "branch": "unknown",
            "ahead": 0,
            "behind": 0,
            "error": "Error: Not a git repository",
        }

        action = git_status_node.post(shared_store, "/test", exec_res)

        assert shared_store["git_status"] == exec_res
        assert action == "default"  # Still returns default

    @patch("subprocess.run")
    def test_integration_full_flow(self, mock_run, git_status_node, shared_store):
        """Test the full flow from prep to post."""
        # Setup
        shared_store["working_directory"] = "/test/repo"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """# branch.head main
# branch.ab +1 -0
1 M. N... 100644 100644 100644 abc123 def456 file.py
? new.txt"""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        # Execute full flow
        prep_res = git_status_node.prep(shared_store)
        exec_res = git_status_node.exec(prep_res)
        action = git_status_node.post(shared_store, prep_res, exec_res)

        # Verify results
        assert shared_store["git_status"] == {
            "modified": [],
            "untracked": ["new.txt"],
            "staged": ["file.py"],
            "branch": "main",
            "ahead": 1,
            "behind": 0,
        }
        assert action == "default"

    @patch("subprocess.run")
    def test_exec_enforces_security_flags(self, mock_run, git_status_node):
        """Test that subprocess.run is called with required security flags.

        SECURITY: These flags prevent command injection (shell=False),
        hanging processes (timeout), and ensure proper output handling.
        """
        shared_store = {"working_directory": "/test/repo"}

        # Mock successful git status
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """# branch.head main
# branch.ab +0 -0"""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        # Execute the node
        prep_res = git_status_node.prep(shared_store)
        git_status_node.exec(prep_res)

        # CRITICAL: Verify security flags on ALL calls
        # Should have 1 call for git status
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

    def test_retry_on_transient_failure(self, git_status_node, shared_store):
        """Test that transient failures trigger retries and eventually succeed."""
        git_status_node.max_retries = 2
        git_status_node.wait = 0  # wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count
                attempt_count += 1

                # First attempt fails, second succeeds
                if attempt_count == 1:
                    return Mock(returncode=1, stdout="", stderr="fatal: Unable to read current working directory")
                else:
                    return Mock(
                        returncode=0,
                        stdout="""# branch.head main
# branch.ab +0 -0
1 M. N... 100644 100644 100644 abc123 def456 file.py""",
                        stderr="",
                    )

            mock_run.side_effect = side_effect

            shared_store["working_directory"] = "/test/repo"
            action = git_status_node.run(shared_store)

            # Should succeed after retry
            assert action == "default"
            assert attempt_count == 2  # Failed once, succeeded on retry

            # Verify the result was stored correctly
            assert "git_status" in shared_store
            assert shared_store["git_status"]["branch"] == "main"
            assert shared_store["git_status"]["staged"] == ["file.py"]

    def test_retry_exhaustion_raises_error(self, git_status_node, shared_store):
        """Test that error is raised after all retries are exhausted."""
        git_status_node.max_retries = 1
        git_status_node.wait = 0  # wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count
                attempt_count += 1
                # All attempts fail with persistent error
                return Mock(returncode=128, stdout="", stderr="fatal: not a git repository")

            mock_run.side_effect = side_effect

            shared_store["working_directory"] = "/not/a/repo"

            # The exec_fallback returns a dict with error info, not raising an exception
            action = git_status_node.run(shared_store)

            # Should have tried max_retries times
            assert attempt_count == 1  # max_retries=1 means 1 attempt total

            # Check that error was handled and stored
            assert action == "default"
            assert "git_status" in shared_store
            assert "error" in shared_store["git_status"]
            assert "not a git repository" in shared_store["git_status"]["error"].lower()
