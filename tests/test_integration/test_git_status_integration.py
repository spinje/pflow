"""Integration tests for GitStatusNode with real git repository."""

import subprocess
import tempfile
from pathlib import Path

import pytest

from src.pflow.nodes.git.status import GitStatusNode


class TestGitStatusIntegration:
    """Integration tests for GitStatusNode with actual git commands."""

    @pytest.fixture
    def temp_git_repo(self):
        """Create a temporary git repository for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Initialize git repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)

            # Configure git user for commits
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True
            )
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)

            yield repo_path

    def test_clean_repository(self, temp_git_repo):
        """Test GitStatusNode with a clean repository."""
        node = GitStatusNode()
        shared = {"working_directory": str(temp_git_repo)}

        # Execute the node workflow
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        # Verify results
        assert action == "default"
        assert "git_status" in shared

        status = shared["git_status"]
        assert status["modified"] == []
        assert status["untracked"] == []
        assert status["staged"] == []
        assert status["branch"] in ["main", "master"]  # Could be either
        assert status["ahead"] == 0
        assert status["behind"] == 0
        assert "error" not in status

    def test_repository_with_untracked_files(self, temp_git_repo):
        """Test GitStatusNode with untracked files."""
        # Create untracked files
        (temp_git_repo / "file1.txt").write_text("content1")
        (temp_git_repo / "file2.py").write_text("print('hello')")

        node = GitStatusNode()
        shared = {"working_directory": str(temp_git_repo)}

        # Execute the node workflow
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        # Verify results
        assert action == "default"
        status = shared["git_status"]
        assert sorted(status["untracked"]) == ["file1.txt", "file2.py"]
        assert status["modified"] == []
        assert status["staged"] == []

    def test_repository_with_staged_files(self, temp_git_repo):
        """Test GitStatusNode with staged files."""
        # Create and stage files
        (temp_git_repo / "staged.txt").write_text("staged content")
        subprocess.run(["git", "add", "staged.txt"], cwd=temp_git_repo, check=True)

        node = GitStatusNode()
        shared = {"working_directory": str(temp_git_repo)}

        # Execute the node workflow
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        # Verify results
        assert action == "default"
        status = shared["git_status"]
        assert status["staged"] == ["staged.txt"]
        assert status["modified"] == []
        assert status["untracked"] == []

    def test_repository_with_modified_files(self, temp_git_repo):
        """Test GitStatusNode with modified files."""
        # Create, commit, then modify a file
        (temp_git_repo / "committed.txt").write_text("original")
        subprocess.run(["git", "add", "committed.txt"], cwd=temp_git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=temp_git_repo, check=True, capture_output=True)

        # Modify the file
        (temp_git_repo / "committed.txt").write_text("modified")

        node = GitStatusNode()
        shared = {"working_directory": str(temp_git_repo)}

        # Execute the node workflow
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        # Verify results
        assert action == "default"
        status = shared["git_status"]
        assert status["modified"] == ["committed.txt"]
        assert status["staged"] == []
        assert status["untracked"] == []

    def test_repository_with_mixed_changes(self, temp_git_repo):
        """Test GitStatusNode with mixed file states."""
        # Create initial commit
        (temp_git_repo / "base.txt").write_text("base")
        (temp_git_repo / "staged_mod.txt").write_text("original")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=temp_git_repo, check=True, capture_output=True)

        # Create various file states
        # 1. Modified file (not staged)
        (temp_git_repo / "base.txt").write_text("modified base")

        # 2. Staged new file
        (temp_git_repo / "new_staged.py").write_text("# new staged")
        subprocess.run(["git", "add", "new_staged.py"], cwd=temp_git_repo, check=True)

        # 3. Untracked file
        (temp_git_repo / "untracked.md").write_text("# Untracked")

        # 4. Staged modification
        (temp_git_repo / "staged_mod.txt").write_text("staged change")
        subprocess.run(["git", "add", "staged_mod.txt"], cwd=temp_git_repo, check=True)

        node = GitStatusNode()
        shared = {"working_directory": str(temp_git_repo)}

        # Execute the node workflow
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        # Verify results
        assert action == "default"
        status = shared["git_status"]

        assert sorted(status["modified"]) == ["base.txt"]
        assert sorted(status["staged"]) == ["new_staged.py", "staged_mod.txt"]
        assert status["untracked"] == ["untracked.md"]

    def test_not_git_repository(self):
        """Test GitStatusNode when not in a git repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node = GitStatusNode()
            shared = {"working_directory": tmpdir}

            # Execute the node workflow
            prep_res = node.prep(shared)
            exec_res = node.exec_fallback(prep_res, ValueError(f"Directory '{tmpdir}' is not a git repository"))
            action = node.post(shared, prep_res, exec_res)

            # Verify error handling
            assert action == "default"
            status = shared["git_status"]
            assert "error" in status
            assert "not a git repository" in status["error"]
            assert status["branch"] == "unknown"

    def test_current_directory_default(self):
        """Test GitStatusNode using pflow repository directory."""
        # Use the actual pflow repository directory
        pflow_repo = Path(__file__).parent.parent.parent  # Go up to pflow root

        node = GitStatusNode()
        shared = {"working_directory": str(pflow_repo)}

        # Execute the node workflow
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        # Verify it works with the pflow repository
        assert action == "default"
        assert "git_status" in shared
        status = shared["git_status"]

        # Should have a branch name at minimum
        assert "branch" in status
        assert isinstance(status["branch"], str)
        assert len(status["branch"]) > 0

        # All expected keys should be present
        assert "modified" in status
        assert "untracked" in status
        assert "staged" in status
        assert "ahead" in status
        assert "behind" in status

        # All lists should be lists
        assert isinstance(status["modified"], list)
        assert isinstance(status["untracked"], list)
        assert isinstance(status["staged"], list)

        # Numbers should be integers
        assert isinstance(status["ahead"], int)
        assert isinstance(status["behind"], int)
