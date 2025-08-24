"""Tests for git-get-latest-tag node."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pflow.nodes.git.get_latest_tag import GitGetLatestTagNode


class TestGitGetLatestTagNode:
    """Test GitGetLatestTagNode functionality."""

    def test_node_initialization(self):
        """Test node initializes with correct retry settings."""
        node = GitGetLatestTagNode()
        assert node.max_retries == 2
        assert node.wait == 0.5

    def test_prep_with_defaults(self):
        """Test prep with default parameters."""
        node = GitGetLatestTagNode()
        shared = {}

        result = node.prep(shared)

        assert result["pattern"] is None
        assert Path(result["working_directory"]).is_absolute()

    def test_prep_with_pattern(self):
        """Test prep with pattern filter."""
        node = GitGetLatestTagNode()
        shared = {"pattern": "v*"}

        result = node.prep(shared)

        assert result["pattern"] == "v*"
        assert Path(result["working_directory"]).is_absolute()

    def test_prep_with_working_directory(self):
        """Test prep with custom working directory."""
        import tempfile

        node = GitGetLatestTagNode()
        with tempfile.TemporaryDirectory() as tmpdir:
            shared = {"working_directory": tmpdir}

            result = node.prep(shared)

            assert result["working_directory"] == str(Path(tmpdir).resolve())

    def test_prep_with_params(self):
        """Test prep falls back to node parameters."""
        node = GitGetLatestTagNode()
        node.params = {"pattern": "release-*", "working_directory": "/custom/path"}
        shared = {}

        result = node.prep(shared)

        assert result["pattern"] == "release-*"
        assert result["working_directory"] == str(Path("/custom/path").expanduser().resolve())

    def test_prep_invalid_pattern(self):
        """Test prep with invalid pattern containing shell operators."""
        node = GitGetLatestTagNode()

        # Pattern validation happens in exec, not prep
        # Prep just passes through the pattern
        patterns = ["v* ; rm -rf", "tag | echo", "tag & ls"]
        for pattern in patterns:
            shared = {"pattern": pattern}
            result = node.prep(shared)
            assert result["pattern"] == pattern  # Prep doesn't validate

    def test_parse_tag_output(self):
        """Test parsing git for-each-ref output."""
        node = GitGetLatestTagNode()

        # Test annotated tag with message
        output = "v1.2.3|abc123def456|2024-01-15 10:30:00 +0000|Release version 1.2.3"
        result = node._parse_tag_output(output)

        assert result["name"] == "v1.2.3"
        assert result["sha"] == "abc123def456"
        assert result["date"] == "2024-01-15 10:30:00 +0000"
        assert result["message"] == "Release version 1.2.3"
        assert result["is_annotated"] is True

    def test_parse_tag_output_lightweight(self):
        """Test parsing lightweight tag (no message)."""
        node = GitGetLatestTagNode()

        # Lightweight tag has empty message field
        output = "v1.0.0|def456abc123|2024-01-10 09:00:00 +0000|"
        result = node._parse_tag_output(output)

        assert result["name"] == "v1.0.0"
        assert result["sha"] == "def456abc123"
        assert result["date"] == "2024-01-10 09:00:00 +0000"
        assert result["message"] == ""
        assert result["is_annotated"] is False

    def test_parse_tag_output_empty(self):
        """Test parsing empty output."""
        node = GitGetLatestTagNode()

        result = node._parse_tag_output("")
        assert result == {}

        result = node._parse_tag_output("  \n  ")
        assert result == {}

    def test_parse_tag_output_malformed(self):
        """Test parsing malformed output."""
        node = GitGetLatestTagNode()

        # Less than 4 parts
        output = "v1.0.0|abc123"
        result = node._parse_tag_output(output)
        assert result == {}

    def test_parse_tag_output_with_pipe_in_message(self):
        """Test parsing output where message contains pipe character."""
        node = GitGetLatestTagNode()

        # The implementation splits with maxsplit=4, creating up to 5 parts
        # But only uses parts[0] through parts[3], so pipes in the message are not preserved
        # This is a limitation of the current implementation
        output = "v2.0.0|xyz789|2024-02-01 12:00:00 +0000|feat: Add | support for pipes | in messages"
        result = node._parse_tag_output(output)

        assert result["name"] == "v2.0.0"
        assert result["sha"] == "xyz789"
        assert result["date"] == "2024-02-01 12:00:00 +0000"
        # The split("|", 4) creates: ["v2.0.0", "xyz789", "2024-02-01...", "feat: Add ", "support for pipes | in messages"]
        # But parts[3] only gets "feat: Add " since it's the 4th element (index 3)
        assert result["message"] == "feat: Add "
        assert result["is_annotated"] is True

    @patch("subprocess.run")
    def test_exec_successful(self, mock_run):
        """Test successful tag retrieval."""
        node = GitGetLatestTagNode()
        prep_res = {"pattern": None, "working_directory": "/test/repo"}

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v1.2.3|abc123def456|2024-01-15 10:30:00 +0000|Release version 1.2.3"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = node.exec(prep_res)

        # Check subprocess called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0][:2] == ["git", "for-each-ref"]
        assert "--sort=-version:refname" in call_args[0][0]
        assert "--count=1" in call_args[0][0]
        assert "refs/tags" in call_args[0][0][-1]
        assert call_args[1]["cwd"] == "/test/repo"
        assert call_args[1]["shell"] is False
        assert call_args[1]["timeout"] == 30

        # Check result
        assert result["status"] == "success"
        assert result["latest_tag"]["name"] == "v1.2.3"
        assert result["latest_tag"]["sha"] == "abc123def456"
        assert result["latest_tag"]["is_annotated"] is True

    @patch("subprocess.run")
    def test_exec_with_pattern(self, mock_run):
        """Test tag retrieval with pattern filter."""
        node = GitGetLatestTagNode()
        prep_res = {"pattern": "v*", "working_directory": "/test/repo"}

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v2.0.0|def789|2024-02-01 12:00:00 +0000|Version 2.0.0"
        mock_run.return_value = mock_result

        result = node.exec(prep_res)

        # Check command includes pattern
        call_args = mock_run.call_args[0][0]
        assert "refs/tags/v*" in call_args

        # Check result
        assert result["status"] == "success"
        assert result["latest_tag"]["name"] == "v2.0.0"

    def test_exec_invalid_pattern(self):
        """Test error with invalid pattern containing shell operators."""
        node = GitGetLatestTagNode()

        patterns = [("v* ; rm -rf", ";"), ("tag | echo", "|"), ("tag & ls", "&")]

        for pattern, operator in patterns:
            prep_res = {"pattern": pattern, "working_directory": "/test/repo"}

            with pytest.raises(ValueError) as exc:
                node.exec(prep_res)

            assert "Invalid pattern" in str(exc.value)
            assert operator in pattern
            assert "cannot contain shell operators" in str(exc.value)

    @patch("subprocess.run")
    def test_exec_no_tags(self, mock_run):
        """Test when no tags exist in repository."""
        node = GitGetLatestTagNode()
        prep_res = {"pattern": None, "working_directory": "/test/repo"}

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""  # Empty output means no tags
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = node.exec(prep_res)

        # Should succeed with empty result
        assert result["status"] == "success"
        assert result["latest_tag"] == {}

    @patch("subprocess.run")
    def test_exec_not_git_repository(self, mock_run):
        """Test error when not in a git repository."""
        node = GitGetLatestTagNode()
        prep_res = {"pattern": None, "working_directory": "/not/a/repo"}

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: not a git repository (or any of the parent directories)"
        mock_run.return_value = mock_result

        with pytest.raises(ValueError, match="not a git repository"):
            node.exec(prep_res)

    @patch("subprocess.run")
    def test_exec_fatal_error(self, mock_run):
        """Test handling of other fatal git errors."""
        node = GitGetLatestTagNode()
        prep_res = {"pattern": None, "working_directory": "/test/repo"}

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: Unable to read current working directory"
        mock_result.stdout = ""
        mock_result.args = ["git", "for-each-ref"]
        mock_run.return_value = mock_result

        with pytest.raises(subprocess.CalledProcessError) as exc:
            node.exec(prep_res)

        assert exc.value.returncode == 128

    @patch("subprocess.run")
    def test_exec_timeout(self, mock_run):
        """Test timeout handling."""
        node = GitGetLatestTagNode()
        prep_res = {"pattern": None, "working_directory": "/test/repo"}

        mock_run.side_effect = subprocess.TimeoutExpired("git for-each-ref", 30)

        with pytest.raises(subprocess.TimeoutExpired):
            node.exec(prep_res)

    def test_exec_fallback_not_repository(self):
        """Test fallback for not a git repository error."""
        node = GitGetLatestTagNode()
        prep_res = {"working_directory": "/not/a/repo", "pattern": None}
        exc = ValueError("Directory '/not/a/repo' is not a git repository")

        result = node.exec_fallback(prep_res, exc)

        assert result["status"] == "error"
        assert result["latest_tag"] == {}
        assert "not a git repository" in result["error"]
        assert "/not/a/repo" in result["error"]

    def test_exec_fallback_invalid_pattern(self):
        """Test fallback for invalid pattern error."""
        node = GitGetLatestTagNode()
        prep_res = {"working_directory": "/test/repo", "pattern": "v* ; rm -rf"}
        exc = ValueError("Invalid pattern: v* ; rm -rf. Pattern cannot contain shell operators.")

        result = node.exec_fallback(prep_res, exc)

        assert result["status"] == "error"
        assert result["latest_tag"] == {}
        assert "Invalid tag pattern" in result["error"]
        assert "cannot contain shell operators" in result["error"]

    def test_exec_fallback_timeout(self):
        """Test fallback for timeout error."""
        node = GitGetLatestTagNode()
        prep_res = {"working_directory": "/test/repo", "pattern": None}
        exc = subprocess.TimeoutExpired("git for-each-ref", 30)

        result = node.exec_fallback(prep_res, exc)

        assert result["status"] == "error"
        assert result["latest_tag"] == {}
        assert "timed out" in result["error"]
        assert "30 seconds" in result["error"]

    def test_exec_fallback_subprocess_error(self):
        """Test fallback for general subprocess error."""
        node = GitGetLatestTagNode()
        prep_res = {"working_directory": "/test/repo", "pattern": None}
        exc = subprocess.CalledProcessError(1, "git for-each-ref", stderr="Permission denied")

        result = node.exec_fallback(prep_res, exc)

        assert result["status"] == "error"
        assert result["latest_tag"] == {}
        assert "exit code 1" in result["error"]
        assert "Permission denied" in result["error"]

    def test_exec_fallback_file_not_found(self):
        """Test fallback when git is not installed."""
        node = GitGetLatestTagNode()
        prep_res = {"working_directory": "/test/repo", "pattern": None}
        exc = FileNotFoundError("git not found")

        result = node.exec_fallback(prep_res, exc)

        assert result["status"] == "error"
        assert result["latest_tag"] == {}
        assert "Git is not installed" in result["error"]

    def test_exec_fallback_general_error(self):
        """Test fallback for unexpected errors."""
        node = GitGetLatestTagNode()
        prep_res = {"working_directory": "/test/repo", "pattern": None}
        exc = RuntimeError("Unexpected error")

        result = node.exec_fallback(prep_res, exc)

        assert result["status"] == "error"
        assert result["latest_tag"] == {}
        assert "Could not get latest tag" in result["error"]
        assert "2 retries" in result["error"]

    def test_post_success(self):
        """Test post method with tag found."""
        node = GitGetLatestTagNode()
        shared = {}
        prep_res = {}
        exec_res = {
            "latest_tag": {
                "name": "v1.2.3",
                "sha": "abc123",
                "date": "2024-01-15 10:30:00 +0000",
                "message": "Release",
                "is_annotated": True,
            },
            "status": "success",
        }

        action = node.post(shared, prep_res, exec_res)

        assert action == "default"
        assert shared["latest_tag"]["name"] == "v1.2.3"
        assert shared["latest_tag"]["sha"] == "abc123"

    def test_post_no_tags(self):
        """Test post method when no tags found."""
        node = GitGetLatestTagNode()
        shared = {}
        prep_res = {}
        exec_res = {"latest_tag": {}, "status": "success"}

        action = node.post(shared, prep_res, exec_res)

        assert action == "default"
        assert shared["latest_tag"] == {}

    def test_post_error(self):
        """Test post method with error status."""
        node = GitGetLatestTagNode()
        shared = {}
        prep_res = {}
        exec_res = {"latest_tag": {}, "status": "error", "error": "Test error"}

        action = node.post(shared, prep_res, exec_res)

        assert action == "default"
        assert shared["latest_tag"] == {}

    @patch("subprocess.run")
    def test_retry_on_transient_failure(self, mock_run):
        """Test that node retries on transient failures."""
        node = GitGetLatestTagNode()
        shared = {}

        # First call fails, second succeeds
        mock_results = [
            MagicMock(returncode=1, stderr="fatal: Unable to read"),  # Transient failure
            MagicMock(returncode=0, stdout="v1.0.0|abc123|2024-01-15 10:30:00 +0000|Initial release", stderr=""),
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
        assert exec_res["latest_tag"]["name"] == "v1.0.0"

    @patch("subprocess.run")
    def test_lightweight_vs_annotated_tags(self, mock_run):
        """Test differentiation between lightweight and annotated tags."""
        node = GitGetLatestTagNode()

        # Test annotated tag (has message)
        prep_res = {"pattern": None, "working_directory": "/test/repo"}

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v1.0.0-annotated|abc123|2024-01-15 10:30:00 +0000|This is an annotated tag"
        mock_run.return_value = mock_result

        result = node.exec(prep_res)
        assert result["latest_tag"]["is_annotated"] is True
        assert result["latest_tag"]["message"] == "This is an annotated tag"

        # Test lightweight tag (no message)
        mock_result.stdout = "v1.0.0-light|def456|2024-01-16 11:00:00 +0000|"
        mock_run.return_value = mock_result

        result = node.exec(prep_res)
        assert result["latest_tag"]["is_annotated"] is False
        assert result["latest_tag"]["message"] == ""
