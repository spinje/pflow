"""Tests for GitCheckoutNode."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.pflow.nodes.git.checkout import GitCheckoutNode


@pytest.fixture
def git_checkout_node():
    """Create a GitCheckoutNode instance for testing."""
    return GitCheckoutNode()


@pytest.fixture
def shared_store():
    """Create a shared store for testing."""
    return {}


class TestGitCheckoutNode:
    """Test suite for GitCheckoutNode."""

    def test_init(self, git_checkout_node):
        """Test node initialization."""
        assert git_checkout_node.max_retries == 2
        assert git_checkout_node.wait == 0.5
        assert git_checkout_node.name == "git-checkout"

    def test_node_name_for_registry(self, git_checkout_node):
        """Test that node has correct name for registry discovery.

        CRITICAL: The name attribute is required for the registry to
        discover and load this node. Without it, the node won't be
        available in the pflow CLI.
        """
        assert hasattr(git_checkout_node, "name")
        assert git_checkout_node.name == "git-checkout"
        # Verify it's a class attribute, not just instance
        assert GitCheckoutNode.name == "git-checkout"

    def test_prep_requires_branch_name(self, git_checkout_node, shared_store):
        """Test that prep raises error when branch name is missing."""
        with pytest.raises(ValueError) as exc_info:
            git_checkout_node.prep(shared_store)
        assert "Branch name is required" in str(exc_info.value)

    def test_prep_validates_branch_name(self, git_checkout_node, shared_store):
        """Test that prep validates branch names."""
        git_checkout_node.params = {"branch": "invalid@branch!"}
        with pytest.raises(ValueError) as exc_info:
            git_checkout_node.prep(shared_store)
        assert "Invalid branch name" in str(exc_info.value)

    def test_prep_with_valid_branch(self, git_checkout_node, shared_store):
        """Test prep with valid branch name."""
        git_checkout_node.params = {"branch": "feature/test-branch"}
        result = git_checkout_node.prep(shared_store)

        assert result["branch"] == "feature/test-branch"
        assert result["create"] is False
        assert result["base"] is None
        assert result["force"] is False
        assert result["stash"] is False
        assert "main" in result["protected_branches"]
        assert "master" in result["protected_branches"]

    def test_prep_with_all_parameters(self, git_checkout_node, shared_store):
        """Test prep with all parameters specified."""
        git_checkout_node.params = {
            "branch": "feature/new",
            "create": True,
            "base": "develop",
            "force": True,
            "stash": True,
            "working_directory": "/test/repo",
        }

        result = git_checkout_node.prep(shared_store)

        assert result["branch"] == "feature/new"
        assert result["create"] is True
        assert result["base"] == "develop"
        assert result["force"] is True
        assert result["stash"] is True
        assert result["working_directory"] == str(Path("/test/repo").resolve())

    def test_prep_with_custom_protected_branches(self, git_checkout_node, shared_store):
        """Test prep with custom protected branches."""
        git_checkout_node.params = {"branch": "test", "protected_branches": ["release", "hotfix"]}

        result = git_checkout_node.prep(shared_store)

        assert "release" in result["protected_branches"]
        assert "hotfix" in result["protected_branches"]
        assert "main" in result["protected_branches"]  # Default still included

    @patch("subprocess.run")
    def test_exec_switch_to_existing_branch(self, mock_run, git_checkout_node):
        """Test switching to an existing branch."""
        # Mock current branch check
        current_branch_result = MagicMock()
        current_branch_result.returncode = 0
        current_branch_result.stdout = "main"
        current_branch_result.stderr = ""

        # Mock status check (clean)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = ""
        status_result.stderr = ""

        # Mock checkout command
        checkout_result = MagicMock()
        checkout_result.returncode = 0
        checkout_result.stdout = "Switched to branch 'feature'"
        checkout_result.stderr = ""

        mock_run.side_effect = [current_branch_result, status_result, checkout_result]

        prep_res = {
            "branch": "feature",
            "create": False,
            "base": None,
            "force": False,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master"],
        }

        result = git_checkout_node.exec(prep_res)

        assert result["current_branch"] == "feature"
        assert result["previous_branch"] == "main"
        assert result["branch_created"] is False
        assert result["stash_created"] == ""
        assert result["status"] == "success"

        # Verify git commands were called correctly
        assert mock_run.call_count == 3
        mock_run.assert_any_call(
            ["git", "branch", "--show-current"],
            cwd="/test/repo",
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )
        mock_run.assert_any_call(
            ["git", "checkout", "feature"],
            cwd="/test/repo",
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
            check=False,
        )

    @patch("subprocess.run")
    def test_exec_create_new_branch(self, mock_run, git_checkout_node):
        """Test creating a new branch."""
        # Mock current branch check
        current_branch_result = MagicMock()
        current_branch_result.returncode = 0
        current_branch_result.stdout = "main"
        current_branch_result.stderr = ""

        # Mock status check (clean)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = ""
        status_result.stderr = ""

        # Mock branch exists check (doesn't exist)
        branch_check_result = MagicMock()
        branch_check_result.returncode = 128  # Branch doesn't exist
        branch_check_result.stdout = ""
        branch_check_result.stderr = "not a valid object name"

        # Mock checkout command
        checkout_result = MagicMock()
        checkout_result.returncode = 0
        checkout_result.stdout = "Switched to a new branch 'feature/new'"
        checkout_result.stderr = ""

        mock_run.side_effect = [current_branch_result, status_result, branch_check_result, checkout_result]

        prep_res = {
            "branch": "feature/new",
            "create": True,
            "base": None,
            "force": False,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master"],
        }

        result = git_checkout_node.exec(prep_res)

        assert result["current_branch"] == "feature/new"
        assert result["previous_branch"] == "main"
        assert result["branch_created"] is True
        assert result["status"] == "success"

    @patch("subprocess.run")
    def test_exec_create_from_base_branch(self, mock_run, git_checkout_node):
        """Test creating a new branch from a specific base."""
        # Mock current branch check
        current_branch_result = MagicMock()
        current_branch_result.returncode = 0
        current_branch_result.stdout = "main"
        current_branch_result.stderr = ""

        # Mock status check (clean)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = ""
        status_result.stderr = ""

        # Mock branch exists check (doesn't exist)
        branch_check_result = MagicMock()
        branch_check_result.returncode = 128
        branch_check_result.stdout = ""
        branch_check_result.stderr = ""

        # Mock base checkout
        base_checkout_result = MagicMock()
        base_checkout_result.returncode = 0
        base_checkout_result.stdout = "Switched to branch 'develop'"
        base_checkout_result.stderr = ""

        # Mock new branch creation
        create_result = MagicMock()
        create_result.returncode = 0
        create_result.stdout = "Switched to a new branch 'feature/from-develop'"
        create_result.stderr = ""

        mock_run.side_effect = [
            current_branch_result,
            status_result,
            branch_check_result,
            base_checkout_result,
            create_result,
        ]

        prep_res = {
            "branch": "feature/from-develop",
            "create": True,
            "base": "develop",
            "force": False,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master"],
        }

        result = git_checkout_node.exec(prep_res)

        assert result["current_branch"] == "feature/from-develop"
        assert result["previous_branch"] == "main"
        assert result["branch_created"] is True

        # Verify base branch was checked out first
        mock_run.assert_any_call(
            ["git", "checkout", "develop"],
            cwd="/test/repo",
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
            check=False,
        )

    @patch("subprocess.run")
    def test_exec_with_uncommitted_changes_no_stash(self, mock_run, git_checkout_node):
        """Test that uncommitted changes without stash flag raises error."""
        # Mock current branch check
        current_branch_result = MagicMock()
        current_branch_result.returncode = 0
        current_branch_result.stdout = "main"
        current_branch_result.stderr = ""

        # Mock status check (has changes)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = "M file.txt"
        status_result.stderr = ""

        mock_run.side_effect = [current_branch_result, status_result]

        prep_res = {
            "branch": "feature",
            "create": False,
            "base": None,
            "force": False,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master"],
        }

        with pytest.raises(ValueError) as exc_info:
            git_checkout_node.exec(prep_res)

        assert "Uncommitted changes detected" in str(exc_info.value)
        assert "stash=true" in str(exc_info.value)

    @patch("subprocess.run")
    def test_exec_with_uncommitted_changes_auto_stash(self, mock_run, git_checkout_node):
        """Test auto-stashing uncommitted changes."""
        # Mock current branch check
        current_branch_result = MagicMock()
        current_branch_result.returncode = 0
        current_branch_result.stdout = "main"
        current_branch_result.stderr = ""

        # Mock status check (has changes)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = "M file.txt"
        status_result.stderr = ""

        # Mock stash command
        stash_result = MagicMock()
        stash_result.returncode = 0
        stash_result.stdout = (
            "Saved working directory and index state On main: Auto-stash before checkout to feature\nstash@{0}"
        )
        stash_result.stderr = ""

        # Mock checkout command
        checkout_result = MagicMock()
        checkout_result.returncode = 0
        checkout_result.stdout = "Switched to branch 'feature'"
        checkout_result.stderr = ""

        mock_run.side_effect = [current_branch_result, status_result, stash_result, checkout_result]

        prep_res = {
            "branch": "feature",
            "create": False,
            "base": None,
            "force": False,
            "stash": True,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master"],
        }

        result = git_checkout_node.exec(prep_res)

        assert result["current_branch"] == "feature"
        assert result["previous_branch"] == "main"
        assert result["stash_created"] == "stash@{0}"
        assert result["status"] == "success"

    @patch("subprocess.run")
    def test_exec_protected_branch_creation_prevented(self, mock_run, git_checkout_node):
        """Test that protected branches cannot be created without force."""
        # Mock current branch check
        current_branch_result = MagicMock()
        current_branch_result.returncode = 0
        current_branch_result.stdout = "feature"
        current_branch_result.stderr = ""

        # Mock status check (clean)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = ""
        status_result.stderr = ""

        mock_run.side_effect = [current_branch_result, status_result]

        prep_res = {
            "branch": "main",
            "create": True,
            "base": None,
            "force": False,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master", "develop"],
        }

        with pytest.raises(ValueError) as exc_info:
            git_checkout_node.exec(prep_res)

        assert "Cannot create protected branch 'main'" in str(exc_info.value)
        assert "force=true" in str(exc_info.value)

    @patch("subprocess.run")
    def test_exec_force_create_existing_branch(self, mock_run, git_checkout_node):
        """Test force creating a branch that already exists."""
        # Mock current branch check
        current_branch_result = MagicMock()
        current_branch_result.returncode = 0
        current_branch_result.stdout = "main"
        current_branch_result.stderr = ""

        # Mock status check (clean)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = ""
        status_result.stderr = ""

        # Mock branch exists check (exists)
        branch_check_result = MagicMock()
        branch_check_result.returncode = 0  # Branch exists
        branch_check_result.stdout = "refs/heads/feature"
        branch_check_result.stderr = ""

        # Mock force checkout command
        checkout_result = MagicMock()
        checkout_result.returncode = 0
        checkout_result.stdout = "Reset branch 'feature'"
        checkout_result.stderr = ""

        mock_run.side_effect = [current_branch_result, status_result, branch_check_result, checkout_result]

        prep_res = {
            "branch": "feature",
            "create": True,
            "base": None,
            "force": True,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master"],
        }

        result = git_checkout_node.exec(prep_res)

        assert result["current_branch"] == "feature"
        assert result["branch_created"] is True

        # Verify -B flag was used for force
        mock_run.assert_any_call(
            ["git", "checkout", "-B", "feature"],
            cwd="/test/repo",
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
            check=False,
        )

    @patch("subprocess.run")
    def test_exec_branch_does_not_exist_error(self, mock_run, git_checkout_node):
        """Test error when trying to switch to non-existent branch."""
        # Mock current branch check
        current_branch_result = MagicMock()
        current_branch_result.returncode = 0
        current_branch_result.stdout = "main"
        current_branch_result.stderr = ""

        # Mock status check (clean)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = ""
        status_result.stderr = ""

        # Mock checkout failure
        checkout_result = MagicMock()
        checkout_result.returncode = 1
        checkout_result.stdout = ""
        checkout_result.stderr = "pathspec 'nonexistent' did not match any file"

        mock_run.side_effect = [current_branch_result, status_result, checkout_result]

        prep_res = {
            "branch": "nonexistent",
            "create": False,
            "base": None,
            "force": False,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master"],
        }

        with pytest.raises(ValueError) as exc_info:
            git_checkout_node.exec(prep_res)

        assert "Branch 'nonexistent' does not exist" in str(exc_info.value)
        assert "create=true" in str(exc_info.value)

    @patch("subprocess.run")
    def test_exec_not_git_repository(self, mock_run, git_checkout_node):
        """Test error when not in a git repository."""
        # Mock current branch check failure
        current_branch_result = MagicMock()
        current_branch_result.returncode = 128
        current_branch_result.stdout = ""
        current_branch_result.stderr = "fatal: not a git repository"

        mock_run.return_value = current_branch_result

        prep_res = {
            "branch": "feature",
            "create": False,
            "base": None,
            "force": False,
            "stash": False,
            "working_directory": "/test/not-repo",
            "protected_branches": ["main", "master"],
        }

        with pytest.raises(ValueError) as exc_info:
            git_checkout_node.exec(prep_res)

        assert "not a git repository" in str(exc_info.value)

    def test_exec_fallback(self, git_checkout_node):
        """Test exec_fallback error handling."""
        prep_res = {"branch": "feature", "working_directory": "/test/repo"}

        # Test with ValueError
        exc = ValueError("Custom error message")
        result = git_checkout_node.exec_fallback(prep_res, exc)
        assert result["status"] == "error"
        assert result["error"] == "Custom error message"
        assert result["current_branch"] == ""

        # Test with TimeoutExpired
        exc = subprocess.TimeoutExpired("git", 30)
        result = git_checkout_node.exec_fallback(prep_res, exc)
        assert "timed out" in result["error"]

        # Test with CalledProcessError
        exc = subprocess.CalledProcessError(1, "git", stderr="git error")
        result = git_checkout_node.exec_fallback(prep_res, exc)
        assert "git error" in result["error"]

        # Test with FileNotFoundError (git not installed)
        exc = FileNotFoundError("git not found")
        result = git_checkout_node.exec_fallback(prep_res, exc)
        assert "Git is not installed" in result["error"]
        assert result["status"] == "error"

        # Test with generic Exception
        exc = Exception("Unknown error")
        result = git_checkout_node.exec_fallback(prep_res, exc)
        assert "Unknown error" in str(result["error"])

    def test_post_success(self, git_checkout_node, shared_store):
        """Test post method with successful checkout."""
        prep_res = {}
        exec_res = {
            "current_branch": "feature",
            "previous_branch": "main",
            "branch_created": True,
            "stash_created": "stash@{0}",
            "status": "success",
        }

        action = git_checkout_node.post(shared_store, prep_res, exec_res)

        assert shared_store["current_branch"] == "feature"
        assert shared_store["previous_branch"] == "main"
        assert shared_store["branch_created"] is True
        assert shared_store["stash_created"] == "stash@{0}"
        assert action == "default"

    def test_post_error(self, git_checkout_node, shared_store):
        """Test post method with error.

        FIXED: The node now correctly returns "error" action when
        exec_res.get("status") == "error", enabling the repair system
        to handle failures properly.
        """
        prep_res = {}
        exec_res = {
            "current_branch": "",
            "previous_branch": "",
            "branch_created": False,
            "stash_created": "",
            "status": "error",
            "error": "Test error",
        }

        action = git_checkout_node.post(shared_store, prep_res, exec_res)

        assert shared_store["current_branch"] == ""
        assert shared_store["previous_branch"] == ""
        assert shared_store["branch_created"] is False
        assert "stash_created" not in shared_store
        # Node correctly returns "error" action for error status
        assert action == "error"
        # Verify error message was stored in shared store
        assert shared_store["error"] == "Test error"


class TestGitCheckoutNodeHelperMethods:
    """Test helper methods of GitCheckoutNode."""

    @patch("subprocess.run")
    def test_get_current_branch_normal(self, mock_run, git_checkout_node):
        """Test _get_current_branch with normal branch."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "main"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = git_checkout_node._get_current_branch("/test/repo")
        assert result == "main"

        mock_run.assert_called_once_with(
            ["git", "branch", "--show-current"],
            cwd="/test/repo",
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
            check=False,
        )

    @patch("subprocess.run")
    def test_get_current_branch_detached_head(self, mock_run, git_checkout_node):
        """Test _get_current_branch in detached HEAD state."""
        # First call fails (detached HEAD)
        detached_result = MagicMock()
        detached_result.returncode = 128
        detached_result.stdout = ""
        detached_result.stderr = "fatal: not on a branch"

        # Fallback call returns HEAD
        fallback_result = MagicMock()
        fallback_result.returncode = 0
        fallback_result.stdout = "HEAD"
        fallback_result.stderr = ""

        mock_run.side_effect = [detached_result, fallback_result]

        result = git_checkout_node._get_current_branch("/test/repo")
        assert result == ""  # Empty string for detached HEAD
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_get_current_branch_not_git_repo(self, mock_run, git_checkout_node):
        """Test _get_current_branch when not in a git repository."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: not a git repository"
        mock_run.return_value = mock_result

        with pytest.raises(ValueError) as exc_info:
            git_checkout_node._get_current_branch("/not/repo")
        assert "not a git repository" in str(exc_info.value)

    @patch("subprocess.run")
    def test_has_uncommitted_changes(self, mock_run, git_checkout_node):
        """Test _has_uncommitted_changes detection."""
        # Test with changes
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "M file.txt\nA new.txt"
        mock_run.return_value = mock_result

        assert git_checkout_node._has_uncommitted_changes("/test/repo") is True

        # Test without changes
        mock_result.stdout = ""
        assert git_checkout_node._has_uncommitted_changes("/test/repo") is False

        # Test with only whitespace
        mock_result.stdout = "  \n  "
        assert git_checkout_node._has_uncommitted_changes("/test/repo") is False

    @patch("subprocess.run")
    def test_branch_exists(self, mock_run, git_checkout_node):
        """Test _branch_exists check."""
        # Branch exists
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "refs/heads/feature"
        mock_run.return_value = mock_result

        assert git_checkout_node._branch_exists("feature", "/test/repo") is True

        # Branch doesn't exist
        mock_result.returncode = 128
        assert git_checkout_node._branch_exists("nonexistent", "/test/repo") is False

    def test_is_protected_branch(self, git_checkout_node):
        """Test _is_protected_branch check."""
        protected = ["main", "master", "develop"]

        # Test protected branches
        assert git_checkout_node._is_protected_branch("main", protected) is True
        assert git_checkout_node._is_protected_branch("MAIN", protected) is True  # Case insensitive
        assert git_checkout_node._is_protected_branch("Master", protected) is True

        # Test non-protected branches
        assert git_checkout_node._is_protected_branch("feature", protected) is False
        assert git_checkout_node._is_protected_branch("main-feature", protected) is False

    @patch("subprocess.run")
    def test_stash_changes_with_changes(self, mock_run, git_checkout_node):
        """Test _stash_changes when there are changes to stash."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Saved working directory and index state On main: Test stash\nstash@{0}"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = git_checkout_node._stash_changes("/test/repo", "Test stash")
        assert result == "stash@{0}"

        # Test with different stash number
        mock_result.stdout = "Saved working directory and index state On main: Test stash\nstash@{3}"
        result = git_checkout_node._stash_changes("/test/repo", "Test stash")
        assert result == "stash@{3}"

    @patch("subprocess.run")
    def test_stash_changes_no_changes(self, mock_run, git_checkout_node):
        """Test _stash_changes when there are no changes to stash."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "No local changes to save"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = git_checkout_node._stash_changes("/test/repo", "Test stash")
        assert result == ""

    @patch("subprocess.run")
    def test_stash_changes_fallback_detection(self, mock_run, git_checkout_node):
        """Test _stash_changes fallback detection when regex doesn't match."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Saved working directory and index state"  # No stash@{} pattern
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = git_checkout_node._stash_changes("/test/repo", "Test stash")
        assert result == "stash@{0}"  # Falls back to stash@{0}


class TestGitCheckoutNodeIntegration:
    """Integration tests for GitCheckoutNode."""

    def test_real_git_checkout(self, tmp_path):
        """Test with a real git repository."""
        import os

        # Create a temporary git repository
        os.chdir(tmp_path)
        subprocess.run(["git", "init"], check=True)  # noqa: S603, S607
        subprocess.run(["git", "config", "user.email", "test@test.com"], check=True)  # noqa: S603, S607
        subprocess.run(["git", "config", "user.name", "Test User"], check=True)  # noqa: S603, S607

        # Create initial commit
        (tmp_path / "README.md").write_text("# Test Repo")
        subprocess.run(["git", "add", "README.md"], check=True)  # noqa: S603, S607
        subprocess.run(["git", "commit", "-m", "Initial commit"], check=True)  # noqa: S603, S607

        # Test checkout node
        node = GitCheckoutNode()
        node.params = {"branch": "feature/test", "create": True, "working_directory": str(tmp_path)}
        shared = {}

        node.run(shared)

        assert shared["current_branch"] == "feature/test"
        assert shared["branch_created"] is True

        # Verify branch was actually created
        result = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, check=True)  # noqa: S603, S607
        assert result.stdout.strip() == "feature/test"


class TestGitCheckoutNodeSecurity:
    """Security and reliability tests for GitCheckoutNode."""

    @patch("subprocess.run")
    def test_exec_enforces_security_flags(self, mock_run, git_checkout_node):
        """Test that subprocess.run is called with required security flags.

        SECURITY: These flags prevent command injection (shell=False),
        hanging processes (timeout), and ensure proper output handling.
        """
        # Mock all subprocess calls for a simple checkout
        current_branch = MagicMock(returncode=0, stdout="main", stderr="")
        status_check = MagicMock(returncode=0, stdout="", stderr="")  # Clean
        checkout = MagicMock(returncode=0, stdout="Switched to branch 'feature'", stderr="")

        mock_run.side_effect = [current_branch, status_check, checkout]

        prep_res = {
            "branch": "feature",
            "create": False,
            "base": None,
            "force": False,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main"],
        }

        git_checkout_node.exec(prep_res)

        # Verify security flags on ALL subprocess calls
        assert len(mock_run.call_args_list) >= 3, "Expected at least 3 subprocess calls"

        for idx, call in enumerate(mock_run.call_args_list):
            call_kwargs = call[1]  # Get keyword arguments
            call_cmd = call[0][0] if call[0] else []

            # Security assertions
            assert call_kwargs.get("shell", False) is False, (
                f"Security violation: shell=True in call {idx + 1}: {call_cmd}"
            )
            assert call_kwargs.get("timeout") is not None, f"Missing timeout in call {idx + 1}: {call_cmd}"
            assert call_kwargs.get("timeout") <= 30, (
                f"Timeout too long: {call_kwargs.get('timeout')} in call {idx + 1}: {call_cmd}"
            )
            assert call_kwargs.get("capture_output") is True, f"Missing capture_output in call {idx + 1}: {call_cmd}"
            assert call_kwargs.get("text") is True, f"Missing text=True in call {idx + 1}: {call_cmd}"

    def test_retry_on_transient_failure(self, git_checkout_node, shared_store):
        """Test that transient failures trigger retries and eventually succeed."""
        git_checkout_node.max_retries = 2
        git_checkout_node.wait = 0  # Fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count
                cmd = args[0]

                # Always succeed for get current branch and status check
                if "branch" in cmd and "--show-current" in cmd:
                    return Mock(returncode=0, stdout="main", stderr="")
                if "status" in cmd and "--porcelain" in cmd:
                    return Mock(returncode=0, stdout="", stderr="")  # Clean

                # Checkout command: fail first, succeed second
                if "checkout" in cmd:
                    attempt_count += 1
                    if attempt_count == 1:
                        # Transient failure
                        return Mock(returncode=1, stdout="", stderr="fatal: unable to access")
                    else:
                        # Success on retry
                        return Mock(returncode=0, stdout="Switched to branch 'feature'", stderr="")

                # Default
                return Mock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect

            git_checkout_node.params = {"branch": "feature", "working_directory": "/test/repo"}

            action = git_checkout_node.run(shared_store)

            # Should succeed after retry
            assert action == "default"
            assert attempt_count == 2  # Failed once, succeeded on retry
            assert shared_store["current_branch"] == "feature"

    def test_retry_exhaustion_returns_error(self, git_checkout_node, shared_store):
        """Test that error action is returned after all retries are exhausted.

        FIXED: When exec_fallback is triggered after retries are exhausted,
        it returns a dict with status="error". The post() method then correctly
        returns "error" action, enabling the repair system to handle the failure.
        """
        git_checkout_node.max_retries = 1
        git_checkout_node.wait = 0  # Fast testing

        with patch("subprocess.run") as mock_run:

            def side_effect(*args, **kwargs):
                cmd = args[0]

                # Get current branch always fails (not a git repo)
                if "branch" in cmd and "--show-current" in cmd:
                    return Mock(returncode=128, stdout="", stderr="fatal: not a git repository")

                return Mock(returncode=0, stdout="", stderr="")

            mock_run.side_effect = side_effect

            git_checkout_node.params = {"branch": "feature", "working_directory": "/not/a/repo"}

            # exec_fallback returns a dict with error info, post() returns "error" action
            action = git_checkout_node.run(shared_store)

            # Node correctly returns "error" action after retries exhausted
            assert action == "error"
            assert shared_store["current_branch"] == ""
            assert shared_store["branch_created"] is False
            # Verify error message was set in shared store
            assert "error" in shared_store
            assert "not a git repository" in shared_store["error"]


class TestGitCheckoutNodeEdgeCases:
    """Test edge cases and error scenarios."""

    @patch("subprocess.run")
    def test_exec_with_invalid_base_branch(self, mock_run, git_checkout_node):
        """Test error when base branch doesn't exist."""
        # Mock current branch check
        current_branch_result = MagicMock()
        current_branch_result.returncode = 0
        current_branch_result.stdout = "main"
        current_branch_result.stderr = ""

        # Mock status check (clean)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = ""
        status_result.stderr = ""

        # Mock branch exists check (new branch doesn't exist)
        branch_check_result = MagicMock()
        branch_check_result.returncode = 128
        branch_check_result.stdout = ""
        branch_check_result.stderr = ""

        # Mock base checkout failure
        base_checkout_result = MagicMock()
        base_checkout_result.returncode = 1
        base_checkout_result.stdout = ""
        base_checkout_result.stderr = "pathspec 'invalid-base' did not match any file"

        mock_run.side_effect = [current_branch_result, status_result, branch_check_result, base_checkout_result]

        prep_res = {
            "branch": "feature/new",
            "create": True,
            "base": "invalid-base",
            "force": False,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master"],
        }

        with pytest.raises(ValueError) as exc_info:
            git_checkout_node.exec(prep_res)

        assert "Base branch 'invalid-base' does not exist" in str(exc_info.value)

    @patch("subprocess.run")
    def test_exec_detached_head_handling(self, mock_run, git_checkout_node):
        """Test handling checkout from detached HEAD state."""
        # First call for --show-current returns empty (detached)
        show_current_result = MagicMock()
        show_current_result.returncode = 128
        show_current_result.stdout = ""
        show_current_result.stderr = ""

        # Fallback call returns HEAD
        fallback_result = MagicMock()
        fallback_result.returncode = 0
        fallback_result.stdout = "HEAD"
        fallback_result.stderr = ""

        # Status check (clean)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = ""
        status_result.stderr = ""

        # Checkout succeeds
        checkout_result = MagicMock()
        checkout_result.returncode = 0
        checkout_result.stdout = "Switched to branch 'main'"
        checkout_result.stderr = ""

        mock_run.side_effect = [show_current_result, fallback_result, status_result, checkout_result]

        prep_res = {
            "branch": "main",
            "create": False,
            "base": None,
            "force": False,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master"],
        }

        result = git_checkout_node.exec(prep_res)

        assert result["current_branch"] == "main"
        assert result["previous_branch"] == ""  # Empty for detached HEAD
        assert result["status"] == "success"

    @patch("subprocess.run")
    def test_exec_create_branch_already_exists_without_force(self, mock_run, git_checkout_node):
        """Test error when trying to create existing branch without force."""
        # Mock current branch check
        current_branch_result = MagicMock()
        current_branch_result.returncode = 0
        current_branch_result.stdout = "main"
        current_branch_result.stderr = ""

        # Mock status check (clean)
        status_result = MagicMock()
        status_result.returncode = 0
        status_result.stdout = ""
        status_result.stderr = ""

        # Mock branch exists check (branch exists!)
        branch_check_result = MagicMock()
        branch_check_result.returncode = 0  # Branch exists
        branch_check_result.stdout = "refs/heads/existing"
        branch_check_result.stderr = ""

        mock_run.side_effect = [current_branch_result, status_result, branch_check_result]

        prep_res = {
            "branch": "existing",
            "create": True,
            "base": None,
            "force": False,
            "stash": False,
            "working_directory": "/test/repo",
            "protected_branches": ["main", "master"],
        }

        with pytest.raises(ValueError) as exc_info:
            git_checkout_node.exec(prep_res)

        assert "Branch 'existing' already exists" in str(exc_info.value)
        assert "force=true" in str(exc_info.value)
