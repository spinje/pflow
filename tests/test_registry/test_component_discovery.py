"""Tests for component discovery via LLM-powered selection."""

from pflow.registry.discovery import ComponentSelection, ComponentSelectionSchema, find_components


class TestDiscoverComponentsBasic:
    """find_components returns a ComponentSelection with node_ids, reasoning, and component_context."""

    def test_returns_component_selection_with_selected_nodes(self, mock_llm_client, monkeypatch):
        """LLM selects nodes and planning context is built for them."""
        monkeypatch.setattr(
            "pflow.registry.discovery.build_nodes_context",
            lambda **kwargs: "1. `read-file` - Reads a file\n2. `write-file` - Writes a file",
        )
        monkeypatch.setattr(
            "pflow.registry.discovery.build_workflows_context",
            lambda **kwargs: "",
        )
        monkeypatch.setattr(
            "pflow.registry.discovery.build_component_context",
            lambda **kwargs: "## read-file\nReads files from disk.",
        )

        mock_llm_client.set_response(
            "*",
            ComponentSelectionSchema,
            {
                "node_ids": ["read-file", "write-file"],
                "workflow_names": [],
                "reasoning": "File read and write needed for the task",
            },
        )

        result = find_components("read a file and write output")

        assert isinstance(result, ComponentSelection)
        assert result.node_ids == ["read-file", "write-file"]
        assert "file" in result.reasoning.lower()
        assert "read-file" in result.component_context


class TestDiscoverComponentsClearsWorkflowNames:
    """find_components clears workflow_names from LLM output (not yet integrated)."""

    def test_workflow_names_from_llm_are_cleared(self, mock_llm_client, monkeypatch):
        """Even if the LLM suggests workflow_names, they are dropped."""
        monkeypatch.setattr(
            "pflow.registry.discovery.build_nodes_context",
            lambda **kwargs: "1. `shell` - Run shell commands",
        )
        monkeypatch.setattr(
            "pflow.registry.discovery.build_workflows_context",
            lambda **kwargs: "1. `deploy` - Deploy to prod",
        )

        # build_component_context receives the cleared workflow names
        captured_kwargs = {}

        def fake_build_component_context(**kwargs):
            captured_kwargs.update(kwargs)
            return "## shell\nRuns shell commands."

        monkeypatch.setattr(
            "pflow.registry.discovery.build_component_context",
            fake_build_component_context,
        )

        mock_llm_client.set_response(
            "*",
            ComponentSelectionSchema,
            {
                "node_ids": ["shell"],
                "workflow_names": ["deploy", "cleanup"],
                "reasoning": "Need shell for deployment",
            },
        )

        result = find_components("deploy the app")

        # The function always passes empty workflow names to build_component_context
        assert captured_kwargs["selected_workflow_names"] == []
        # Result should have nodes but no trace of workflow_names
        assert result.node_ids == ["shell"]


class TestDiscoverComponentsComponentContextError:
    """When build_component_context returns an error dict, find_components handles it gracefully."""

    def test_returns_empty_component_context_on_error(self, mock_llm_client, monkeypatch):
        """An error dict from build_component_context results in empty component_context string."""
        monkeypatch.setattr(
            "pflow.registry.discovery.build_nodes_context",
            lambda **kwargs: "1. `fake-node` - Does something",
        )
        monkeypatch.setattr(
            "pflow.registry.discovery.build_workflows_context",
            lambda **kwargs: "",
        )
        monkeypatch.setattr(
            "pflow.registry.discovery.build_component_context",
            lambda **kwargs: {"error": "No matching nodes found", "missing_nodes": ["fake-node"]},
        )

        mock_llm_client.set_response(
            "*",
            ComponentSelectionSchema,
            {
                "node_ids": ["fake-node"],
                "workflow_names": [],
                "reasoning": "Selected fake-node for the task",
            },
        )

        result = find_components("do something with fake-node")

        assert result.component_context == ""
        assert result.node_ids == ["fake-node"]


class TestDiscoverComponentsModelSelection:
    """find_components uses the correct LLM model."""

    def test_uses_get_model_for_feature_as_default(self, mock_llm_client, monkeypatch):
        """When no model_name is passed, the discovery feature model is used."""
        monkeypatch.setattr(
            "pflow.registry.discovery.build_nodes_context",
            lambda **kwargs: "1. `shell` - Run commands",
        )
        monkeypatch.setattr(
            "pflow.registry.discovery.build_workflows_context",
            lambda **kwargs: "",
        )
        monkeypatch.setattr(
            "pflow.registry.discovery.build_component_context",
            lambda **kwargs: "context",
        )

        captured_model = {}

        def fake_get_model_for_feature(feature: str) -> str:
            captured_model["feature"] = feature
            return "gemini-2.5-flash"

        monkeypatch.setattr(
            "pflow.core.llm_config.get_model_for_feature",
            fake_get_model_for_feature,
        )

        mock_llm_client.set_response(
            "*",
            ComponentSelectionSchema,
            {
                "node_ids": ["shell"],
                "workflow_names": [],
                "reasoning": "Need shell",
            },
        )

        find_components("run a script")

        assert captured_model["feature"] == "discovery"
        assert len(mock_llm_client.call_history) == 1
        assert mock_llm_client.call_history[0]["model"] == "gemini-2.5-flash"

    def test_uses_explicit_model_name_when_provided(self, mock_llm_client, monkeypatch):
        """When model_name is explicitly passed, it overrides the default."""
        monkeypatch.setattr(
            "pflow.registry.discovery.build_nodes_context",
            lambda **kwargs: "1. `shell` - Run commands",
        )
        monkeypatch.setattr(
            "pflow.registry.discovery.build_workflows_context",
            lambda **kwargs: "",
        )
        monkeypatch.setattr(
            "pflow.registry.discovery.build_component_context",
            lambda **kwargs: "context",
        )

        mock_llm_client.set_response(
            "*",
            ComponentSelectionSchema,
            {
                "node_ids": ["shell"],
                "workflow_names": [],
                "reasoning": "Need shell",
            },
        )

        find_components("run a script", model_name="openai/gpt-4o")

        assert len(mock_llm_client.call_history) == 1
        assert mock_llm_client.call_history[0]["model"] == "openai/gpt-4o"
