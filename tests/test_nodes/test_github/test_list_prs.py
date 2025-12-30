"""Tests for GitHubListPrsNode."""

import json
import subprocess
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.pflow.nodes.github.list_prs import ListPrsNode


class TestListPrsNode:
    """Test suite for GitHubListPrsNode."""

    def test_prep_validates_authentication(self):
        """Test that prep checks for GitHub CLI authentication."""
        node = ListPrsNode()
        shared = {}

        with patch("subprocess.run") as mock_run:
            # Simulate authentication failure
            mock_run.return_value = MagicMock(returncode=1)

            with pytest.raises(ValueError) as exc_info:
                node.prep(shared)

            assert "GitHub CLI not authenticated" in str(exc_info.value)
            assert "gh auth login" in str(exc_info.value)

    def test_prep_validates_state(self):
        """Test that prep validates the state parameter for PRs."""
        node = ListPrsNode()

        with patch("subprocess.run") as mock_run:
            # Simulate successful authentication
            mock_run.return_value = MagicMock(returncode=0)

            # Test valid PR states
            valid_states = ["open", "closed", "merged", "all"]
            for state in valid_states:
                node.params = {"state": state}
                shared = {}
                result = node.prep(shared)
                assert result["state"] == state

            # Test invalid state
            node.params = {"state": "invalid"}
            shared = {}
            with pytest.raises(ValueError) as exc_info:
                node.prep(shared)

            assert "Invalid PR state 'invalid'" in str(exc_info.value)
            assert "Must be one of: open, closed, merged, all" in str(exc_info.value)

    def test_prep_validates_merged_state(self):
        """Test that 'merged' state is valid for PRs (unlike issues)."""
        node = ListPrsNode()
        node.params = {"state": "merged"}
        shared = {}

        with patch("subprocess.run") as mock_run:
            # Simulate successful authentication
            mock_run.return_value = MagicMock(returncode=0)

            # Should not raise an error for 'merged' state
            result = node.prep(shared)
            assert result["state"] == "merged"

    def test_prep_validates_and_clamps_limit(self):
        """Test that prep validates and clamps the limit parameter."""
        node = ListPrsNode()

        with patch("subprocess.run") as mock_run:
            # Simulate successful authentication
            mock_run.return_value = MagicMock(returncode=0)

            # Test clamping to minimum
            node.params = {"limit": -5}
            shared = {}
            result = node.prep(shared)
            assert result["limit"] == 1

            # Test clamping to maximum
            node.params = {"limit": 200}
            shared = {}
            result = node.prep(shared)
            assert result["limit"] == 100

            # Test valid range
            node.params = {"limit": 50}
            shared = {}
            result = node.prep(shared)
            assert result["limit"] == 50

            # Test invalid type
            node.params = {"limit": "not_a_number"}
            shared = {}
            with pytest.raises(ValueError) as exc_info:
                node.prep(shared)
            assert "Invalid limit value" in str(exc_info.value)
            assert "Must be an integer between 1 and 100" in str(exc_info.value)

    def test_prep_uses_params_and_defaults(self):
        """Test that prep uses params and defaults."""
        node = ListPrsNode()

        with patch("subprocess.run") as mock_run:
            # Simulate successful authentication
            mock_run.return_value = MagicMock(returncode=0)

            # Test params are used
            node.params = {"repo": "param/repo", "state": "closed", "limit": 10}
            shared = {}
            result = node.prep(shared)
            assert result["repo"] == "param/repo"
            assert result["state"] == "closed"
            assert result["limit"] == 10

            # Test defaults when params are empty
            node.params = {}
            shared = {}
            result = node.prep(shared)
            assert result["repo"] is None
            assert result["state"] == "open"
            assert result["limit"] == 30

    def test_exec_builds_correct_command(self):
        """Test that exec builds the correct GitHub CLI command for PRs."""
        node = ListPrsNode()

        # Test with all parameters
        prep_res = {"repo": "owner/repo", "state": "merged", "limit": 50}

        sample_pr = {
            "number": 123,
            "title": "Fix authentication bug",
            "state": "MERGED",
            "author": {"login": "testuser", "is_bot": False},
            "labels": [{"name": "bug"}, {"name": "urgent"}],
            "headRefName": "fix-auth",
            "baseRefName": "main",
            "isDraft": False,
            "url": "https://github.com/owner/repo/pull/123",
            "createdAt": "2024-01-01T12:00:00Z",
            "updatedAt": "2024-01-02T12:00:00Z",
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps([sample_pr]))

            result = node.exec(prep_res)

            # Verify command structure
            call_args = mock_run.call_args[0][0]
            assert call_args[:3] == ["gh", "pr", "list"]
            assert "--json" in call_args
            assert (
                "number,title,state,author,labels,headRefName,baseRefName,isDraft,url,createdAt,updatedAt" in call_args
            )
            assert "--repo" in call_args
            assert "owner/repo" in call_args
            assert "--state" in call_args
            assert "merged" in call_args
            assert "--limit" in call_args
            assert "50" in call_args

            # Verify result
            assert result["prs"] == [sample_pr]

    def test_exec_preserves_native_fields(self):
        """Test that exec preserves native field names like isDraft and headRefName."""
        node = ListPrsNode()
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 30}

        sample_pr = {
            "number": 456,
            "title": "Add new feature",
            "state": "OPEN",
            "author": {"login": "botuser", "is_bot": True},
            "labels": [],
            "headRefName": "feature-branch",
            "baseRefName": "develop",
            "isDraft": True,
            "url": "https://github.com/owner/repo/pull/456",
            "createdAt": "2024-01-03T10:00:00Z",
            "updatedAt": "2024-01-03T11:00:00Z",
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps([sample_pr]))

            result = node.exec(prep_res)

            # Verify native fields are preserved
            pr = result["prs"][0]
            assert pr["isDraft"] is True  # Not is_draft
            assert pr["headRefName"] == "feature-branch"  # Not head_ref_name
            assert pr["baseRefName"] == "develop"  # Not base_ref_name
            assert pr["author"]["is_bot"] is True  # Native GitHub field

    def test_exec_handles_uppercase_state_values(self):
        """Test that exec correctly handles UPPERCASE state values from GitHub API."""
        node = ListPrsNode()
        prep_res = {"repo": None, "state": "all", "limit": 5}

        sample_prs = [
            {"number": 1, "title": "PR 1", "state": "OPEN"},
            {"number": 2, "title": "PR 2", "state": "CLOSED"},
            {"number": 3, "title": "PR 3", "state": "MERGED"},
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(sample_prs))

            result = node.exec(prep_res)

            # Verify states are preserved as UPPERCASE
            assert result["prs"][0]["state"] == "OPEN"
            assert result["prs"][1]["state"] == "CLOSED"
            assert result["prs"][2]["state"] == "MERGED"

    def test_exec_handles_empty_response(self):
        """Test that exec handles empty PR lists correctly."""
        node = ListPrsNode()
        prep_res = {"repo": None, "state": "open", "limit": 30}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")

            result = node.exec(prep_res)
            assert result["prs"] == []

    def test_exec_raises_on_error(self):
        """Test that exec lets exceptions bubble up for retry."""
        node = ListPrsNode()
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 30}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="repository not found")

            with pytest.raises(subprocess.CalledProcessError):
                node.exec(prep_res)

    def test_post_stores_prs_in_shared(self):
        """Test that post stores the PRs list in shared store."""
        node = ListPrsNode()
        shared = {}
        prep_res = {}
        exec_res = {
            "prs": [
                {"number": 1, "title": "PR 1", "state": "OPEN"},
                {"number": 2, "title": "PR 2", "state": "MERGED"},
            ]
        }

        action = node.post(shared, prep_res, exec_res)

        assert shared["prs"] == exec_res["prs"]
        assert action == "default"

    def test_exec_fallback_transforms_errors(self):
        """Test that exec_fallback provides user-friendly error messages."""
        node = ListPrsNode()
        prep_res = {"repo": "owner/repo", "state": "open", "limit": 30}

        # Test gh not installed
        exc = Exception("gh: command not found")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)
        assert "GitHub CLI (gh) is not installed" in str(exc_info.value)
        assert "brew install gh" in str(exc_info.value)

        # Test repository not found
        exc = Exception("repository not found")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)
        assert "Repository 'owner/repo' not found" in str(exc_info.value)
        assert "verify the repository name" in str(exc_info.value)

        # Test authentication error
        exc = Exception("authentication required")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)
        assert "GitHub authentication failed" in str(exc_info.value)
        assert "gh auth login" in str(exc_info.value)

        # Test rate limit
        exc = Exception("rate limit exceeded")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)
        assert "GitHub API rate limit exceeded" in str(exc_info.value)
        assert "wait a few minutes" in str(exc_info.value)

        # Test generic error
        exc = Exception("some other error")
        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)
        assert "Failed to list pull requests after 3 attempts" in str(exc_info.value)
        assert "Repository: owner/repo" in str(exc_info.value)
        assert "State: open" in str(exc_info.value)
        assert "Limit: 30" in str(exc_info.value)

    def test_exec_enforces_security_flags(self):
        """Test that subprocess.run is called with required security flags.

        SECURITY: These flags prevent command injection (shell=False),
        hanging processes (timeout), and ensure proper output handling.
        """
        node = ListPrsNode()
        node.params = {"repo": "owner/repo", "state": "open", "limit": 10}
        shared = {}

        with patch("subprocess.run") as mock_run:
            # Mock auth check and main command
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps([{"number": 1, "title": "Test PR", "state": "OPEN"}]),
                stderr="",
            )

            # Execute the node
            prep_res = node.prep(shared)
            node.exec(prep_res)

            # CRITICAL: Verify security flags on ALL calls
            # Should have 2 calls: auth check in prep, and PR list in exec
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
        node = ListPrsNode(max_retries=2, wait=0)  # wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # Auth checks always succeed
                if args[0] == ["gh", "auth", "status"]:
                    return Mock(returncode=0, stdout="", stderr="")

                # Track list attempts
                attempt_count += 1

                # First attempt fails, second succeeds
                if attempt_count == 1:
                    return Mock(returncode=1, stdout="", stderr="temporary network error")
                else:
                    sample_prs = [
                        {
                            "number": 123,
                            "title": "Fix bug",
                            "state": "OPEN",
                            "author": {"login": "user1", "is_bot": False},
                            "labels": [{"name": "bug"}],
                            "headRefName": "bugfix",
                            "baseRefName": "main",
                            "isDraft": False,
                            "url": "https://github.com/owner/repo/pull/123",
                            "createdAt": "2024-01-01T12:00:00Z",
                            "updatedAt": "2024-01-02T12:00:00Z",
                        },
                        {
                            "number": 124,
                            "title": "Add feature",
                            "state": "MERGED",
                            "author": {"login": "user2", "is_bot": False},
                            "labels": [{"name": "enhancement"}],
                            "headRefName": "feature",
                            "baseRefName": "main",
                            "isDraft": False,
                            "url": "https://github.com/owner/repo/pull/124",
                            "createdAt": "2024-01-03T12:00:00Z",
                            "updatedAt": "2024-01-04T12:00:00Z",
                        },
                    ]
                    return Mock(returncode=0, stdout=json.dumps(sample_prs), stderr="")

            mock_run.side_effect = side_effect

            node.params = {"repo": "owner/repo", "state": "open", "limit": 10}
            shared = {}
            action = node.run(shared)

            # Should succeed after retry
            assert action == "default"
            assert attempt_count == 2  # Failed once, succeeded on retry

            # Verify the result was stored correctly
            assert "prs" in shared
            assert len(shared["prs"]) == 2
            assert shared["prs"][0]["number"] == 123
            assert shared["prs"][0]["title"] == "Fix bug"
            assert shared["prs"][0]["state"] == "OPEN"
            assert shared["prs"][0]["headRefName"] == "bugfix"
            assert shared["prs"][0]["isDraft"] is False

    def test_retry_exhaustion_raises_error(self):
        """Test that error is raised after all retries are exhausted."""
        node = ListPrsNode(max_retries=1, wait=0)  # Only 1 retry, wait=0 for fast testing

        with patch("subprocess.run") as mock_run:
            attempt_count = 0

            # All attempts fail with persistent error
            def side_effect(*args, **kwargs):
                nonlocal attempt_count

                # Auth checks succeed
                if args[0] == ["gh", "auth", "status"]:
                    return Mock(returncode=0, stdout="", stderr="")

                # Track list attempts
                attempt_count += 1

                # All PR list fetches fail
                return Mock(returncode=1, stdout="", stderr="repository not found")

            mock_run.side_effect = side_effect

            node.params = {"repo": "owner/repo", "state": "open", "limit": 30}
            shared = {}

            with pytest.raises(ValueError) as exc_info:
                node.run(shared)

            # Should have tried max_retries times
            assert attempt_count == 1  # max_retries=1 means 1 attempt total

            # Error message should mention repository or failure
            error_msg = str(exc_info.value).lower()
            assert "repository" in error_msg or "not found" in error_msg or "failed" in error_msg

    def test_exec_with_no_repo_parameter(self):
        """Test that exec works without repo parameter (uses current repo)."""
        node = ListPrsNode()
        prep_res = {"repo": None, "state": "open", "limit": 30}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps([{"number": 789, "title": "Local PR", "state": "OPEN"}]),
            )

            result = node.exec(prep_res)

            # Verify command structure - should not have --repo flag
            call_args = mock_run.call_args[0][0]
            assert "--repo" not in call_args
            assert result["prs"][0]["number"] == 789

    def test_comprehensive_pr_response(self):
        """Test handling of comprehensive PR response with all fields."""
        node = ListPrsNode()
        prep_res = {"repo": "owner/repo", "state": "all", "limit": 10}

        # Comprehensive PR data with all fields
        sample_prs = [
            {
                "number": 100,
                "title": "Feature: Add authentication",
                "state": "OPEN",
                "author": {"login": "alice", "is_bot": False},
                "labels": [{"name": "feature"}, {"name": "security"}],
                "headRefName": "feature/auth",
                "baseRefName": "main",
                "isDraft": False,
                "url": "https://github.com/owner/repo/pull/100",
                "createdAt": "2024-01-01T08:00:00Z",
                "updatedAt": "2024-01-01T09:00:00Z",
            },
            {
                "number": 101,
                "title": "Fix: Memory leak in cache",
                "state": "MERGED",
                "author": {"login": "bob", "is_bot": False},
                "labels": [{"name": "bug"}, {"name": "critical"}],
                "headRefName": "fix/memory-leak",
                "baseRefName": "develop",
                "isDraft": False,
                "url": "https://github.com/owner/repo/pull/101",
                "createdAt": "2024-01-02T10:00:00Z",
                "updatedAt": "2024-01-03T14:00:00Z",
            },
            {
                "number": 102,
                "title": "WIP: Documentation update",
                "state": "OPEN",
                "author": {"login": "dependabot[bot]", "is_bot": True},
                "labels": [{"name": "documentation"}],
                "headRefName": "docs/update",
                "baseRefName": "main",
                "isDraft": True,
                "url": "https://github.com/owner/repo/pull/102",
                "createdAt": "2024-01-04T16:00:00Z",
                "updatedAt": "2024-01-04T16:30:00Z",
            },
            {
                "number": 103,
                "title": "Refactor: Clean up legacy code",
                "state": "CLOSED",
                "author": {"login": "charlie", "is_bot": False},
                "labels": [],
                "headRefName": "refactor/cleanup",
                "baseRefName": "main",
                "isDraft": False,
                "url": "https://github.com/owner/repo/pull/103",
                "createdAt": "2024-01-05T09:00:00Z",
                "updatedAt": "2024-01-06T11:00:00Z",
            },
        ]

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(sample_prs))

            result = node.exec(prep_res)

            # Verify all PRs are preserved with correct fields
            assert len(result["prs"]) == 4

            # Check first PR (OPEN, non-draft)
            pr1 = result["prs"][0]
            assert pr1["number"] == 100
            assert pr1["state"] == "OPEN"
            assert pr1["isDraft"] is False
            assert pr1["author"]["is_bot"] is False
            assert len(pr1["labels"]) == 2

            # Check second PR (MERGED)
            pr2 = result["prs"][1]
            assert pr2["number"] == 101
            assert pr2["state"] == "MERGED"
            assert pr2["baseRefName"] == "develop"

            # Check third PR (draft by bot)
            pr3 = result["prs"][2]
            assert pr3["number"] == 102
            assert pr3["isDraft"] is True
            assert pr3["author"]["is_bot"] is True
            assert pr3["author"]["login"] == "dependabot[bot]"

            # Check fourth PR (CLOSED, no labels)
            pr4 = result["prs"][3]
            assert pr4["number"] == 103
            assert pr4["state"] == "CLOSED"
            assert pr4["labels"] == []
