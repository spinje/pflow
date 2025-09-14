"""Integration test for parameter transformation in metadata generation."""

from unittest.mock import Mock, patch

from pflow.planning.nodes import MetadataGenerationNode, ParameterDiscoveryNode


class TestParameterTransformationIntegration:
    """Test that parameter transformation works in the full planner flow."""

    @patch("llm.get_model")
    def test_metadata_generation_uses_templatized_input(self, mock_get_model):
        """Test that MetadataGenerationNode uses templatized input from shared store."""

        # Mock LLM responses
        mock_model = Mock()
        mock_get_model.return_value = mock_model

        # Setup shared store with pre-populated data including templatized_input
        shared = {
            "user_input": "generate changelog from last 30 closed issues in pflow repo",
            "templatized_input": "generate changelog from last ${issue_count} closed issues in ${repo_name} repo",  # Pre-computed by ParameterDiscoveryNode
            "planning_context": "Test context",
            "generated_workflow": {
                "version": "1.0",
                "name": "test_workflow",
                "inputs": {
                    "issue_count": {"type": "integer", "description": "Number of issues", "default": 30},
                    "repo_name": {"type": "string", "description": "Repository name", "default": "pflow"},
                },
                "nodes": [
                    {
                        "id": "fetch_issues",
                        "type": "github_list_issues",
                        "params": {"repo": "${repo_name}", "limit": "${issue_count}"},
                    }
                ],
            },
            "discovered_params": {"count": "30", "repo": "pflow"},
            "extracted_params": {"issue_count": 30, "repo_name": "pflow"},
        }

        # Mock metadata generation response
        from pflow.planning.ir_models import WorkflowMetadata

        mock_metadata = WorkflowMetadata(
            suggested_name="changelog-generator",  # Use hyphens instead of underscores
            description="This workflow generates a comprehensive changelog by fetching and analyzing closed issues from a GitHub repository, formatting them into a release-ready document suitable for documentation purposes",
            search_keywords=["changelog", "issues", "github", "release", "documentation"],
            capabilities=["fetch issues from GitHub", "format changelog entries", "generate release notes"],
            typical_use_cases=["release notes generation", "changelog creation for new versions"],
        )

        # Mock response needs the structure expected by parse_structured_response
        mock_response = Mock()
        mock_response.json = Mock(
            return_value={
                "content": [{"input": mock_metadata.model_dump()}]  # Claude format
            }
        )

        # We need to check what prompt is sent to the LLM
        captured_prompt = None

        def capture_prompt(prompt, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return mock_response

        mock_model.prompt = capture_prompt

        # Create and run the metadata generation node
        node = MetadataGenerationNode()

        # Run prep, exec, post cycle
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        # Verify the prompt contains templatized input
        assert captured_prompt is not None

        # Check that the user input section has been templatized with ${} syntax
        assert "<user_input>" in captured_prompt
        assert "generate changelog from last ${issue_count} closed issues in ${repo_name} repo" in captured_prompt

        # The workflow inputs section will still contain defaults (this is expected)
        # But the original request should NOT contain the specific values
        lines = captured_prompt.split("\n")
        in_original_request = False
        for line in lines:
            if "<original_request>" in line:
                in_original_request = True
            elif "</original_request>" in line:
                in_original_request = False
            elif in_original_request:
                # Within the original request section, values should be replaced
                assert "30" not in line, f"Found '30' in original request line: {line}"
                assert "pflow" not in line, f"Found 'pflow' in original request line: {line}"

        # Verify metadata was stored
        assert "workflow_metadata" in shared
        assert shared["workflow_metadata"]["suggested_name"] == "changelog-generator"

    @patch("llm.get_model")
    def test_parameter_discovery_creates_templatized_input(self, mock_get_model):
        """Test that ParameterDiscoveryNode creates templatized input."""

        # Mock LLM response for parameter discovery
        mock_model = Mock()
        mock_get_model.return_value = mock_model

        from pflow.planning.nodes import ParameterDiscovery

        mock_params = ParameterDiscovery(
            parameters={"issue_count": 30, "repo_name": "pflow"},
            stdin_type=None,
            reasoning="Found parameters in user input",
        )

        mock_response = Mock()
        mock_response.json = Mock(
            return_value={
                "content": [{"input": mock_params.model_dump()}]  # Claude format
            }
        )
        mock_model.prompt = Mock(return_value=mock_response)

        # Setup shared store
        shared = {
            "user_input": "generate changelog from last 30 closed issues in pflow repo",
            "planning_context": "",
            "browsed_components": {},
        }

        # Create and run parameter discovery node
        node = ParameterDiscoveryNode()

        # Run prep, exec, post cycle
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        # Verify templatized input was created and stored
        assert "templatized_input" in shared
        assert (
            shared["templatized_input"]
            == "generate changelog from last ${issue_count} closed issues in ${repo_name} repo"
        )
        assert "discovered_params" in shared
        assert shared["discovered_params"] == {"issue_count": 30, "repo_name": "pflow"}

    @patch("llm.get_model")
    def test_full_flow_with_parameter_transformation(self, mock_get_model):
        """Test parameter transformation through the full flow."""

        # Mock LLM
        mock_model = Mock()
        mock_get_model.return_value = mock_model

        # Set up responses for different nodes
        from pflow.planning.ir_models import WorkflowMetadata
        from pflow.planning.nodes import ParameterDiscovery

        # 1. Parameter Discovery response
        param_discovery = ParameterDiscovery(
            parameters={"count": 50, "repo": "test-repo"},
            stdin_type=None,
            reasoning="Found parameters",
        )

        param_response = Mock()
        param_response.json = Mock(return_value={"content": [{"input": param_discovery.model_dump()}]})

        # 2. Metadata Generation response
        metadata = WorkflowMetadata(
            suggested_name="test-workflow",
            description="This is a test workflow that processes items from a repository. It demonstrates parameter transformation and metadata generation in the planner flow system.",
            search_keywords=["test", "workflow", "parameter"],
            capabilities=["test capability", "parameter processing"],
            typical_use_cases=["test use case"],
        )

        metadata_response = Mock()
        metadata_response.json = Mock(return_value={"content": [{"input": metadata.model_dump()}]})

        # Track which prompt is being used
        prompt_counter = 0
        captured_metadata_prompt = None

        def mock_prompt(prompt, **kwargs):
            nonlocal prompt_counter, captured_metadata_prompt
            prompt_counter += 1
            if prompt_counter == 1:
                # First call is parameter discovery
                return param_response
            else:
                # Second call is metadata generation
                captured_metadata_prompt = prompt
                return metadata_response

        mock_model.prompt = mock_prompt

        # Simulate the flow
        shared = {
            "user_input": "process 50 items from test-repo",
            "planning_context": "",
            "browsed_components": {},
            "generated_workflow": {
                "ir_version": "0.1.0",
                "inputs": {},
                "nodes": [],
                "edges": [],
            },
        }

        # 1. Run ParameterDiscoveryNode
        param_node = ParameterDiscoveryNode()
        prep_res = param_node.prep(shared)
        exec_res = param_node.exec(prep_res)
        param_node.post(shared, prep_res, exec_res)

        # Verify templatized input was created
        assert "templatized_input" in shared
        assert shared["templatized_input"] == "process ${count} items from ${repo}"

        # 2. Run MetadataGenerationNode
        metadata_node = MetadataGenerationNode()
        prep_res = metadata_node.prep(shared)
        exec_res = metadata_node.exec(prep_res)
        metadata_node.post(shared, prep_res, exec_res)

        # Verify the metadata prompt used templatized input
        assert captured_metadata_prompt is not None
        assert "process ${count} items from ${repo}" in captured_metadata_prompt
        # Original values should not appear in the prompt
        assert "50" not in captured_metadata_prompt or "${count}" in captured_metadata_prompt
        assert "test-repo" not in captured_metadata_prompt or "${repo}" in captured_metadata_prompt
