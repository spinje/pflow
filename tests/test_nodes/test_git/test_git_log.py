"""Tests for git-log node."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pflow.nodes.git.log import GitLogNode


class TestGitLogNode:
    """Test GitLogNode functionality."""

    def test_node_initialization(self):
        """Test node initializes with correct retry settings."""
        node = GitLogNode()
        assert node.max_retries == 2
        assert node.wait == 0.5

    def test_prep_with_defaults(self):
        """Test prep with default parameters."""
        node = GitLogNode()
        shared = {}

        result = node.prep(shared)

        assert result["limit"] == 20
        assert result["since"] is None
        assert result["until"] is None
        assert result["author"] is None
        assert result["grep"] is None
        assert result["path"] is None
        assert Path(result["working_directory"]).is_absolute()

    def test_prep_with_params_values(self):
        """Test prep extracts values from params."""
        import tempfile

        node = GitLogNode()
        with tempfile.TemporaryDirectory() as tmpdir:
            node.params = {
                "since": "v1.0.0",
                "until": "HEAD",
                "limit": 50,
                "author": "test@example.com",
                "grep": "feat:",
                "path": "src/",
                "working_directory": tmpdir,
            }
            shared = {}

            result = node.prep(shared)

            assert result["since"] == "v1.0.0"
            assert result["until"] == "HEAD"
            assert result["limit"] == 50
            assert result["author"] == "test@example.com"
            assert result["grep"] == "feat:"
            assert result["path"] == "src/"
            assert result["working_directory"] == str(Path(tmpdir).resolve())

    def test_prep_with_params(self):
        """Test prep falls back to node parameters."""
        node = GitLogNode()
        node.params = {"since": "2024-01-01", "limit": 10, "author": "Jane Doe"}
        shared = {}

        result = node.prep(shared)

        assert result["since"] == "2024-01-01"
        assert result["limit"] == 10
        assert result["author"] == "Jane Doe"

    def test_prep_invalid_limit(self):
        """Test prep raises error for invalid limit."""
        node = GitLogNode()

        # Test non-integer
        node.params = {"limit": "invalid"}
        shared = {}
        with pytest.raises(ValueError, match="Invalid limit"):
            node.prep(shared)

        # Test negative
        node.params = {"limit": -1}
        shared = {}
        with pytest.raises(ValueError, match="Invalid limit"):
            node.prep(shared)

        # Test zero
        node.params = {"limit": 0}
        shared = {}
        with pytest.raises(ValueError, match="Invalid limit"):
            node.prep(shared)

    def test_parse_commits_empty(self):
        """Test parsing empty output."""
        node = GitLogNode()
        result = node._parse_commits("")
        assert result == []

    def test_parse_commits_single(self):
        """Test parsing single commit."""
        node = GitLogNode()
        output = "abc123|abc|John Doe|john@example.com|2024-01-15T10:30:00+00:00|1705316400|Initial commit||ENDCOMMIT\n"

        commits = node._parse_commits(output)

        assert len(commits) == 1
        commit = commits[0]
        assert commit["sha"] == "abc123"
        assert commit["short_sha"] == "abc"
        assert commit["author_name"] == "John Doe"
        assert commit["author_email"] == "john@example.com"
        assert commit["date"] == "2024-01-15T10:30:00+00:00"
        assert commit["timestamp"] == 1705316400
        assert commit["subject"] == "Initial commit"
        assert commit["message"] == "Initial commit"
        assert commit["body"] == ""

    def test_parse_commits_with_body(self):
        """Test parsing commit with multi-line body."""
        node = GitLogNode()
        output = "def456|def|Jane Smith|jane@example.com|2024-01-16T14:20:00+00:00|1705416000|feat: Add new feature|This adds a new feature.\n\nMore details here.|ENDCOMMIT\n"

        commits = node._parse_commits(output)

        assert len(commits) == 1
        commit = commits[0]
        assert commit["subject"] == "feat: Add new feature"
        assert commit["body"] == "This adds a new feature.\n\nMore details here."
        assert commit["message"] == "feat: Add new feature\n\nThis adds a new feature.\n\nMore details here."

    def test_parse_commits_multiple(self):
        """Test parsing multiple commits."""
        node = GitLogNode()
        output = (
            "abc123|abc|John Doe|john@example.com|2024-01-15T10:30:00+00:00|1705316400|Commit 1||ENDCOMMIT\n"
            "def456|def|Jane Smith|jane@example.com|2024-01-16T14:20:00+00:00|1705416000|Commit 2|With body|ENDCOMMIT\n"
            "ghi789|ghi|Bob Jones|bob@example.com|2024-01-17T09:15:00+00:00|1705484100|Commit 3||ENDCOMMIT\n"
        )

        commits = node._parse_commits(output)

        assert len(commits) == 3
        assert commits[0]["subject"] == "Commit 1"
        assert commits[1]["subject"] == "Commit 2"
        assert commits[2]["subject"] == "Commit 3"

    @patch("subprocess.run")
    def test_exec_successful(self, mock_run):
        """Test successful git log execution."""
        node = GitLogNode()
        prep_res = {
            "since": None,
            "until": None,
            "limit": 2,
            "author": None,
            "grep": None,
            "path": None,
            "working_directory": "/test/repo",
        }

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "abc123|abc|John Doe|john@example.com|2024-01-15T10:30:00+00:00|1705316400|Test commit||ENDCOMMIT\n"
        )
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = node.exec(prep_res)

        # Check subprocess called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0][:3] == ["git", "log", "--format=%H|%h|%an|%ae|%aI|%at|%s|%b|ENDCOMMIT"]
        assert "-n2" in call_args[0][0]
        assert call_args[1]["cwd"] == "/test/repo"
        assert call_args[1]["shell"] is False
        assert call_args[1]["timeout"] == 30

        # Check result
        assert result["status"] == "success"
        assert len(result["commits"]) == 1
        assert result["commits"][0]["sha"] == "abc123"

    @patch("subprocess.run")
    def test_exec_with_filters(self, mock_run):
        """Test git log execution with all filters including git ref range."""
        node = GitLogNode()
        prep_res = {
            "since": "v1.0.0",
            "until": "v2.0.0",
            "limit": 100,
            "author": "john@example.com",
            "grep": "feat:",
            "path": "src/",
            "working_directory": "/test/repo",
        }

        # Mock responses: 3 _is_git_ref checks + 1 git log command
        # _is_git_ref is called: once for since, twice for until (in condition and assignment)
        mock_ref_check = MagicMock(returncode=0)  # Valid git ref
        mock_log_result = MagicMock(returncode=0, stdout="")
        mock_run.side_effect = [mock_ref_check, mock_ref_check, mock_ref_check, mock_log_result]

        node.exec(prep_res)

        # Check command includes all filters
        # The git log command should be the last call
        call_args = mock_run.call_args_list[-1][0][0]
        assert "-n100" in call_args
        # Since both since and until are git refs, should use commit range syntax
        assert "v1.0.0..v2.0.0" in call_args
        assert "--author" in call_args
        assert "john@example.com" in call_args
        assert "--grep" in call_args
        assert "feat:" in call_args
        assert "--" in call_args
        assert "src/" in call_args

    @patch("subprocess.run")
    def test_exec_with_date_filters(self, mock_run):
        """Test git log execution with date-based since/until (not git refs)."""
        node = GitLogNode()
        prep_res = {
            "since": "2024-01-01",
            "until": "2024-06-01",
            "limit": 50,
            "author": None,
            "grep": None,
            "path": None,
            "working_directory": "/test/repo",
        }

        # Mock responses: _is_git_ref called once for since (returns False, so we use --since)
        # Then once for until (returns False, so we use --until)
        mock_ref_check = MagicMock(returncode=1)  # Not a valid git ref (it's a date)
        mock_log_result = MagicMock(returncode=0, stdout="")
        mock_run.side_effect = [mock_ref_check, mock_ref_check, mock_log_result]

        node.exec(prep_res)

        # Check command uses --since and --until for dates
        call_args = mock_run.call_args_list[-1][0][0]
        assert "-n50" in call_args
        assert "--since=2024-01-01" in call_args
        assert "--until=2024-06-01" in call_args

    @patch("subprocess.run")
    def test_exec_not_git_repository(self, mock_run):
        """Test error when not in a git repository."""
        node = GitLogNode()
        prep_res = {
            "since": None,
            "until": None,
            "limit": 20,
            "author": None,
            "grep": None,
            "path": None,
            "working_directory": "/not/a/repo",
        }

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: not a git repository"
        mock_run.return_value = mock_result

        with pytest.raises(ValueError, match="not a git repository"):
            node.exec(prep_res)

    @patch("subprocess.run")
    def test_exec_invalid_revision(self, mock_run):
        """Test error with invalid revision reference."""
        node = GitLogNode()
        prep_res = {
            "since": "invalid-tag",
            "until": None,
            "limit": 20,
            "author": None,
            "grep": None,
            "path": None,
            "working_directory": "/test/repo",
        }

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: unknown revision or path not in the working tree"
        mock_run.return_value = mock_result

        with pytest.raises(ValueError, match="Invalid revision reference"):
            node.exec(prep_res)

    @patch("subprocess.run")
    def test_exec_empty_repository(self, mock_run):
        """Test handling of empty repository."""
        node = GitLogNode()
        prep_res = {
            "since": None,
            "until": None,
            "limit": 20,
            "author": None,
            "grep": None,
            "path": None,
            "working_directory": "/test/repo",
        }

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: your current branch 'main' does not have any commits yet"
        mock_run.return_value = mock_result

        result = node.exec(prep_res)

        assert result["status"] == "empty_repository"
        assert result["commits"] == []

    @patch("subprocess.run")
    def test_exec_timeout(self, mock_run):
        """Test timeout handling."""
        node = GitLogNode()
        prep_res = {
            "since": None,
            "until": None,
            "limit": 20,
            "author": None,
            "grep": None,
            "path": None,
            "working_directory": "/test/repo",
        }

        mock_run.side_effect = subprocess.TimeoutExpired("git log", 30)

        with pytest.raises(subprocess.TimeoutExpired):
            node.exec(prep_res)

    def test_exec_fallback_not_repository(self):
        """Test fallback for not a git repository error."""
        node = GitLogNode()
        prep_res = {"working_directory": "/not/a/repo"}
        exc = ValueError("Directory '/not/a/repo' is not a git repository")

        result = node.exec_fallback(prep_res, exc)

        assert result["status"] == "error"
        assert result["commits"] == []
        assert "not a git repository" in result["error"]

    def test_exec_fallback_invalid_revision(self):
        """Test fallback for invalid revision error."""
        node = GitLogNode()
        prep_res = {"working_directory": "/test/repo"}
        exc = ValueError("Invalid revision reference: some error")

        result = node.exec_fallback(prep_res, exc)

        assert result["status"] == "error"
        assert result["commits"] == []
        assert "Invalid revision reference" in result["error"]

    def test_exec_fallback_timeout(self):
        """Test fallback for timeout error."""
        node = GitLogNode()
        prep_res = {"working_directory": "/test/repo"}
        exc = subprocess.TimeoutExpired("git log", 30)

        result = node.exec_fallback(prep_res, exc)

        assert result["status"] == "error"
        assert result["commits"] == []
        assert "timed out" in result["error"]

    def test_exec_fallback_general_error(self):
        """Test fallback for general subprocess error."""
        node = GitLogNode()
        prep_res = {"working_directory": "/test/repo"}
        exc = subprocess.CalledProcessError(1, "git log", stderr="Some error")

        result = node.exec_fallback(prep_res, exc)

        assert result["status"] == "error"
        assert result["commits"] == []
        assert "exit code 1" in result["error"]
        assert "Some error" in result["error"]

    def test_post_success(self):
        """Test post method with successful execution."""
        node = GitLogNode()
        shared = {}
        prep_res = {}
        exec_res = {"commits": [{"sha": "abc123", "subject": "Test"}], "status": "success"}

        action = node.post(shared, prep_res, exec_res)

        assert action == "default"
        assert shared["commits"] == [{"sha": "abc123", "subject": "Test"}]

    def test_post_error(self):
        """Test post method with error status."""
        node = GitLogNode()
        shared = {}
        prep_res = {}
        exec_res = {"commits": [], "status": "error", "error": "Test error"}

        action = node.post(shared, prep_res, exec_res)

        # Node correctly returns "error" action on failures to enable repair system
        assert action == "error"
        assert shared["commits"] == []
        assert shared["error"] == "Test error"

    def test_post_empty_repository(self):
        """Test post method with empty repository status."""
        node = GitLogNode()
        shared = {}
        prep_res = {}
        exec_res = {"commits": [], "status": "empty_repository"}

        action = node.post(shared, prep_res, exec_res)

        assert action == "default"
        assert shared["commits"] == []

    @patch("subprocess.run")
    def test_retry_on_transient_failure(self, mock_run):
        """Test that node retries on transient failures."""
        node = GitLogNode()
        shared = {}

        # First call fails, second succeeds
        mock_results = [
            MagicMock(returncode=1, stderr="fatal: Unable to read"),  # Transient failure
            MagicMock(
                returncode=0,
                stdout="abc123|abc|John|john@ex.com|2024-01-15T10:30:00+00:00|1705316400|Test||ENDCOMMIT\n",
            ),
        ]
        mock_run.side_effect = [subprocess.CalledProcessError(1, "git", stderr=mock_results[0].stderr), mock_results[1]]

        # Run the full node lifecycle
        prep_res = node.prep(shared)
        try:
            # First exec will fail and trigger retry
            exec_res = node.exec(prep_res)
        except subprocess.CalledProcessError:
            # Simulate PocketFlow retry mechanism
            exec_res = node.exec(prep_res)

        # Should succeed on retry
        assert exec_res["status"] == "success"
        assert len(exec_res["commits"]) == 1
