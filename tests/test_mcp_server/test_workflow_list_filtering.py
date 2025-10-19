"""Test workflow_list filtering functionality.

This test suite verifies that the filter_pattern parameter works correctly
according to the documented behavior:
- Single keyword: Matches name OR description
- Multiple keywords: Space-separated AND logic (all must match)
"""

import pytest

from pflow.mcp_server.services.workflow_service import WorkflowService


class TestWorkflowListFiltering:
    """Test workflow list filtering with various patterns."""

    @pytest.fixture
    def sample_workflows(self):
        """Sample workflows for testing filters."""
        return [
            {
                "name": "slack-qa-analyzer",
                "description": "Analyzes QA results and posts to Slack",
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "name": "github-pr-analyzer",
                "description": "Analyzes GitHub pull requests",
                "created_at": "2024-01-02T00:00:00Z",
            },
            {
                "name": "slack-notification",
                "description": "Sends notifications to Slack channels",
                "created_at": "2024-01-03T00:00:00Z",
            },
            {
                "name": "data-processor",
                "description": "Process data files",
                "created_at": "2024-01-04T00:00:00Z",
            },
        ]

    def test_no_filter_returns_all_workflows(self, sample_workflows, monkeypatch):
        """Test that no filter returns all workflows."""

        def mock_list_all(self):
            return sample_workflows

        monkeypatch.setattr("pflow.core.workflow_manager.WorkflowManager.list_all", mock_list_all)

        result = WorkflowService.list_workflows(filter_pattern=None)

        # All 4 workflows should be in the result
        assert "slack-qa-analyzer" in result
        assert "github-pr-analyzer" in result
        assert "slack-notification" in result
        assert "data-processor" in result
        assert "Total: 4 workflows" in result

    def test_single_keyword_filter_in_name(self, sample_workflows, monkeypatch):
        """Test filtering with single keyword that matches name."""

        def mock_list_all(self):
            return sample_workflows

        monkeypatch.setattr("pflow.core.workflow_manager.WorkflowManager.list_all", mock_list_all)

        result = WorkflowService.list_workflows(filter_pattern="slack")

        # Should match both slack workflows
        assert "slack-qa-analyzer" in result
        assert "slack-notification" in result
        # Should NOT match github or data-processor
        assert "github-pr-analyzer" not in result
        assert "data-processor" not in result
        assert "Total: 2 workflows" in result

    def test_single_keyword_filter_in_description(self, sample_workflows, monkeypatch):
        """Test filtering with single keyword that matches description."""

        def mock_list_all(self):
            return sample_workflows

        monkeypatch.setattr("pflow.core.workflow_manager.WorkflowManager.list_all", mock_list_all)

        result = WorkflowService.list_workflows(filter_pattern="github")

        # Should match github workflow
        assert "github-pr-analyzer" in result
        # Should NOT match slack workflows
        assert "slack-qa-analyzer" not in result
        assert "slack-notification" not in result
        assert "Total: 1 workflow" in result

    def test_multiple_keywords_and_logic(self, sample_workflows, monkeypatch):
        """Test filtering with multiple keywords (AND logic).

        THIS IS THE BUG: Currently fails because it looks for "slack qa" as a substring
        instead of checking that BOTH "slack" AND "qa" are present.
        """

        def mock_list_all(self):
            return sample_workflows

        monkeypatch.setattr("pflow.core.workflow_manager.WorkflowManager.list_all", mock_list_all)

        # Filter: "slack qa" should match workflows with BOTH "slack" AND "qa"
        result = WorkflowService.list_workflows(filter_pattern="slack qa")

        # Should match slack-qa-analyzer (has both "slack" and "qa")
        assert "slack-qa-analyzer" in result

        # Should NOT match slack-notification (has "slack" but not "qa")
        assert "slack-notification" not in result

        # Should NOT match github-pr-analyzer (has neither)
        assert "github-pr-analyzer" not in result

        assert "Total: 1 workflow" in result

    def test_multiple_keywords_no_match(self, sample_workflows, monkeypatch):
        """Test filtering where no workflows match all keywords."""

        def mock_list_all(self):
            return sample_workflows

        monkeypatch.setattr("pflow.core.workflow_manager.WorkflowManager.list_all", mock_list_all)

        # No workflow has both "slack" and "github"
        result = WorkflowService.list_workflows(filter_pattern="slack github")

        # Should show custom message with context (workflows exist but don't match)
        assert "No workflows match filter: 'slack github'" in result
        assert "Found 4 total workflows" in result

    def test_case_insensitive_filtering(self, sample_workflows, monkeypatch):
        """Test that filtering is case-insensitive."""

        def mock_list_all(self):
            return sample_workflows

        monkeypatch.setattr("pflow.core.workflow_manager.WorkflowManager.list_all", mock_list_all)

        # Test with different cases
        result1 = WorkflowService.list_workflows(filter_pattern="SLACK")
        result2 = WorkflowService.list_workflows(filter_pattern="Slack")
        result3 = WorkflowService.list_workflows(filter_pattern="slack")

        # All should return same results
        assert "slack-qa-analyzer" in result1
        assert "slack-qa-analyzer" in result2
        assert "slack-qa-analyzer" in result3

    def test_filter_with_extra_whitespace(self, sample_workflows, monkeypatch):
        """Test filtering handles extra whitespace correctly."""

        def mock_list_all(self):
            return sample_workflows

        monkeypatch.setattr("pflow.core.workflow_manager.WorkflowManager.list_all", mock_list_all)

        # Filter with extra spaces should still work
        result = WorkflowService.list_workflows(filter_pattern="  slack   qa  ")

        # Should match slack-qa-analyzer
        assert "slack-qa-analyzer" in result
        assert "Total: 1 workflow" in result

    def test_filter_matches_description_and_keywords(self, sample_workflows, monkeypatch):
        """Test that keywords can match in description."""

        def mock_list_all(self):
            return sample_workflows

        monkeypatch.setattr("pflow.core.workflow_manager.WorkflowManager.list_all", mock_list_all)

        # "analyzes" appears in descriptions of multiple workflows
        result = WorkflowService.list_workflows(filter_pattern="analyzes slack")

        # Should match slack-qa-analyzer (has both in name/description)
        assert "slack-qa-analyzer" in result

        # Should NOT match slack-notification (has "slack" but not "analyzes")
        assert "slack-notification" not in result

        # Should NOT match github-pr-analyzer (has "analyzes" but not "slack")
        assert "github-pr-analyzer" not in result

        assert "Total: 1 workflow" in result

    def test_filter_no_match_with_existing_workflows_shows_context(self, sample_workflows, monkeypatch):
        """Test that filter with no matches shows context about total workflows."""

        def mock_list_all(self):
            return sample_workflows

        monkeypatch.setattr("pflow.core.workflow_manager.WorkflowManager.list_all", mock_list_all)

        # No workflow has both "slack" and "github"
        result = WorkflowService.list_workflows(filter_pattern="slack github")

        # Should show custom message with context
        assert "No workflows match filter: 'slack github'" in result
        assert "Found 4 total workflows" in result
        assert "Try:" in result
        assert "Broader keywords" in result
        # Should NOT show the default "No workflows saved yet" message
        assert "No workflows saved yet" not in result
