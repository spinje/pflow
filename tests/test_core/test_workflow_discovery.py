"""Tests for workflow discovery via LLM-powered matching."""

from unittest.mock import MagicMock

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.core.workflow.discovery import WorkflowDecision, WorkflowMatch, find_workflow


class TestDiscoverWorkflowNoWorkflows:
    """When no saved workflows exist, find_workflow returns immediately without calling the LLM."""

    def test_returns_not_found_when_no_workflows_exist(self, mock_llm_client, monkeypatch):
        """No LLM call should be made when there are no workflows to match against."""
        monkeypatch.setattr(
            "pflow.core.workflow.discovery.build_workflows_context",
            lambda **kwargs: "",
        )

        result = find_workflow("find a changelog generator")

        assert isinstance(result, WorkflowMatch)
        assert result.found is False
        assert result.workflow_name is None
        assert result.workflow is None
        assert result.confidence == 1.0
        # No LLM call should have been recorded
        assert len(mock_llm_client.call_history) == 0


class TestDiscoverWorkflowLLMFound:
    """When workflows exist and LLM finds a match, find_workflow loads the workflow."""

    def test_returns_loaded_workflow_when_llm_finds_match(self, mock_llm_client, monkeypatch):
        """LLM says found=True and the workflow loads successfully from disk."""
        monkeypatch.setattr(
            "pflow.core.workflow.discovery.build_workflows_context",
            lambda **kwargs: "1. `changelog` - Generate changelogs",
        )

        mock_llm_client.set_response(
            "*",
            WorkflowDecision,
            {
                "found": True,
                "workflow_name": "changelog",
                "confidence": 0.95,
                "reasoning": "Exact match for changelog generation",
            },
        )

        fake_loaded = {"name": "changelog", "description": "Generate changelogs", "ir": {"nodes": []}}
        mock_manager = MagicMock()
        mock_manager.load.return_value = fake_loaded

        result = find_workflow("generate a changelog", workflow_manager=mock_manager)

        assert result.found is True
        assert result.workflow_name == "changelog"
        assert result.confidence == 0.95
        assert result.workflow is fake_loaded
        mock_manager.load.assert_called_once_with("changelog")

    def test_returns_not_found_when_workflow_missing_on_disk(self, mock_llm_client, monkeypatch):
        """LLM says found=True but the workflow file no longer exists on disk."""
        monkeypatch.setattr(
            "pflow.core.workflow.discovery.build_workflows_context",
            lambda **kwargs: "1. `stale-workflow` - Old workflow",
        )

        mock_llm_client.set_response(
            "*",
            WorkflowDecision,
            {
                "found": True,
                "workflow_name": "stale-workflow",
                "confidence": 0.8,
                "reasoning": "Found stale workflow",
            },
        )

        mock_manager = MagicMock()
        mock_manager.load.side_effect = WorkflowNotFoundError("stale-workflow")

        result = find_workflow("run stale workflow", workflow_manager=mock_manager)

        assert result.found is False
        assert result.workflow is None
        assert result.workflow_name == "stale-workflow"


class TestDiscoverWorkflowLLMNotFound:
    """When workflows exist but LLM says none match, find_workflow returns not found."""

    def test_returns_not_found_when_llm_says_no_match(self, mock_llm_client, monkeypatch):
        """LLM evaluates workflows and determines none match the query."""
        monkeypatch.setattr(
            "pflow.core.workflow.discovery.build_workflows_context",
            lambda **kwargs: "1. `deploy-app` - Deploy to production",
        )

        mock_llm_client.set_response(
            "*",
            WorkflowDecision,
            {
                "found": False,
                "workflow_name": None,
                "confidence": 0.9,
                "reasoning": "No workflow matches the request for data migration",
            },
        )

        mock_manager = MagicMock()

        result = find_workflow("migrate database tables", workflow_manager=mock_manager)

        assert result.found is False
        assert result.workflow is None
        # load() should NOT have been called since found=False
        mock_manager.load.assert_not_called()


class TestDiscoverWorkflowModelSelection:
    """find_workflow uses the correct LLM model."""

    def test_uses_get_model_for_feature_as_default(self, mock_llm_client, monkeypatch):
        """When no model_name is passed, the discovery feature model is used."""
        monkeypatch.setattr(
            "pflow.core.workflow.discovery.build_workflows_context",
            lambda **kwargs: "1. `test-wf` - A test workflow",
        )

        captured_model = {}

        def fake_get_model_for_feature(feature: str) -> str:
            captured_model["feature"] = feature
            return "gemini-2.5-flash"

        monkeypatch.setattr(
            "pflow.core.llm_config.get_model_for_feature",
            fake_get_model_for_feature,
        )

        mock_manager = MagicMock()

        find_workflow("anything", workflow_manager=mock_manager)

        assert captured_model["feature"] == "discovery"
        # The LLM mock call should have been made with the resolved model
        assert len(mock_llm_client.call_history) == 1
        assert mock_llm_client.call_history[0]["model"] == "gemini-2.5-flash"

    def test_uses_explicit_model_name_when_provided(self, mock_llm_client, monkeypatch):
        """When model_name is explicitly passed, it overrides the default."""
        monkeypatch.setattr(
            "pflow.core.workflow.discovery.build_workflows_context",
            lambda **kwargs: "1. `test-wf` - A test workflow",
        )

        mock_manager = MagicMock()

        find_workflow("anything", model_name="openai/gpt-4o", workflow_manager=mock_manager)

        assert len(mock_llm_client.call_history) == 1
        assert mock_llm_client.call_history[0]["model"] == "openai/gpt-4o"
