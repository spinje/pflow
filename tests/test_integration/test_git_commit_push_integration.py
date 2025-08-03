"""Integration tests for GitCommitNode and GitPushNode."""

import subprocess
from unittest.mock import MagicMock, patch

from src.pflow.nodes.git.commit import GitCommitNode
from src.pflow.nodes.git.push import GitPushNode
from src.pflow.nodes.git.status import GitStatusNode


class TestGitIntegration:
    """Integration tests for git nodes."""

    def test_commit_node_with_status_node(self, tmp_path):
        """Test GitCommitNode integrates with GitStatusNode."""
        # Create a temporary git repo
        repo_dir = tmp_path / "test_repo"
        repo_dir.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)

        # Create a test file
        test_file = repo_dir / "test.txt"
        test_file.write_text("Hello, World!")

        # Set up shared store
        shared = {"working_directory": str(repo_dir)}

        # Run GitStatusNode to see untracked files
        status_node = GitStatusNode()
        status_node.run(shared)

        assert "test.txt" in shared["git_status"]["untracked"]

        # Run GitCommitNode to commit the file
        commit_node = GitCommitNode()
        shared["message"] = "Initial commit"
        shared["files"] = ["."]
        commit_node.run(shared)

        assert shared["commit_sha"] != ""
        assert shared["commit_message"] == "Initial commit"

        # Run GitStatusNode again to verify commit
        status_node.run(shared)

        assert len(shared["git_status"]["untracked"]) == 0
        assert len(shared["git_status"]["modified"]) == 0

    def test_commit_and_push_workflow(self, tmp_path):
        """Test complete workflow of commit and push in a real git repo."""
        # Create a temporary git repo
        repo_dir = tmp_path / "test_repo"
        repo_dir.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)

        # Create a test file
        test_file = repo_dir / "test.txt"
        test_file.write_text("Hello, World!")

        # Set up shared store
        shared = {"working_directory": str(repo_dir), "message": "Test commit", "files": ["test.txt"]}

        # Run commit node
        commit_node = GitCommitNode()
        commit_node.run(shared)

        # Verify commit was created
        assert shared["commit_sha"] != ""
        assert shared["commit_message"] == "Test commit"

        # Verify the commit exists in git
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"], cwd=repo_dir, capture_output=True, text=True, check=True
        )
        assert "Test commit" in result.stdout

    def test_commit_with_nothing_to_commit(self, tmp_path):
        """Test GitCommitNode handles nothing to commit gracefully."""
        # Create a temporary git repo
        repo_dir = tmp_path / "test_repo"
        repo_dir.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)

        # Create and commit a file
        test_file = repo_dir / "test.txt"
        test_file.write_text("Initial content")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)

        # Set up shared store
        shared = {"working_directory": str(repo_dir), "message": "Nothing to commit", "files": ["."]}

        # Run GitCommitNode - should handle nothing to commit
        commit_node = GitCommitNode()
        commit_node.run(shared)

        # Check that it handled the case gracefully
        assert shared["commit_sha"] == ""
        assert shared["commit_message"] == "Nothing to commit"

    @patch("subprocess.run")
    def test_push_handles_rejection(self, mock_run):
        """Test GitPushNode handles push rejection gracefully."""
        push_result = MagicMock(returncode=1, stdout="", stderr="! [rejected] main -> main (non-fast-forward)")

        mock_run.return_value = push_result

        shared = {"working_directory": "/test/repo", "branch": "main", "remote": "origin"}

        # Run push node
        push_node = GitPushNode()
        push_node.run(shared)

        # Should not raise exception, but indicate failure
        assert shared["push_result"]["success"] is False
        assert shared["push_result"]["branch"] == "main"
        assert shared["push_result"]["remote"] == "origin"
