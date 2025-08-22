"""Integration test for parameter transformation in metadata generation."""

from unittest.mock import Mock, patch

from pflow.planning.nodes import MetadataGenerationNode


class TestParameterTransformationIntegration:
    """Test that parameter transformation works in the full planner flow."""

    @patch("llm.get_model")
    def test_metadata_generation_transforms_parameters(self, mock_get_model):
        """Test that MetadataGenerationNode transforms user input with extracted parameters."""

        # Mock LLM responses
        mock_model = Mock()
        mock_get_model.return_value = mock_model

        # Setup shared store with pre-populated data
        shared = {
            "user_input": "generate changelog from last 30 closed issues in pflow repo",
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

        # Verify the prompt contains transformed input
        assert captured_prompt is not None

        # Check that the user input section has been transformed
        assert "<original_request>" in captured_prompt
        assert "generate changelog from last [issue_count] closed issues in [repo_name] repo" in captured_prompt

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
    def test_metadata_generation_without_extracted_params(self, mock_get_model):
        """Test backward compatibility when extracted_params is not available."""

        # Mock LLM responses
        mock_model = Mock()
        mock_get_model.return_value = mock_model

        # Setup shared store WITHOUT extracted_params (simulating old flow)
        shared = {
            "user_input": "do something generic",
            "planning_context": "Test context",
            "generated_workflow": {"version": "1.0", "name": "test_workflow", "nodes": []},
            "discovered_params": {},
            # No extracted_params key!
        }

        # Mock metadata generation response
        from pflow.planning.ir_models import WorkflowMetadata

        mock_metadata = WorkflowMetadata(
            suggested_name="generic-workflow",  # Use hyphens instead of underscores
            description="This is a generic workflow that performs basic processing tasks without specific domain requirements, suitable for general-purpose automation and simple data manipulation operations",
            search_keywords=["generic", "workflow", "automation", "processing", "general"],
            capabilities=["general processing", "basic automation tasks"],
            typical_use_cases=["general automation", "simple data processing"],
        )

        # Mock response needs the structure expected by parse_structured_response
        mock_response = Mock()
        mock_response.json = Mock(
            return_value={
                "content": [{"input": mock_metadata.model_dump()}]  # Claude format
            }
        )

        # Capture the prompt
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

        # Verify the prompt contains original input (no transformation)
        assert captured_prompt is not None
        assert "do something generic" in captured_prompt

        # Verify metadata was stored
        assert "workflow_metadata" in shared
        assert shared["workflow_metadata"]["suggested_name"] == "generic-workflow"

    @patch("llm.get_model")
    def test_full_flow_with_parameter_transformation(self, mock_get_model):
        """Test complete flow from discovery through metadata with parameter transformation."""

        # This is a simplified test that shows the flow works end-to-end
        # In reality, each node would make LLM calls

        mock_model = Mock()
        mock_get_model.return_value = mock_model

        # Initial shared store
        shared = {
            "user_input": "analyze sales data from Q4 2024 for product ABC123",
        }

        # Simulate the flow execution with mocked responses
        # This would normally happen through the Flow >> operator

        # 1. Discovery finds relevant components
        shared["discovered_params"] = {"quarter": "Q4", "year": "2024", "product": "ABC123"}

        # 2. Generator creates workflow with inputs
        shared["generated_workflow"] = {
            "version": "1.0",
            "name": "sales_analysis",
            "inputs": {
                "quarter": {"type": "string", "default": "Q4"},
                "year": {"type": "integer", "default": 2024},
                "product_id": {"type": "string", "default": "ABC123"},
            },
            "nodes": [],
        }

        # 3. Parameter mapping maps discovered to workflow inputs
        shared["extracted_params"] = {"quarter": "Q4", "year": 2024, "product_id": "ABC123"}

        # 4. Metadata generation with transformation
        from pflow.planning.ir_models import WorkflowMetadata

        mock_metadata = WorkflowMetadata(
            suggested_name="sales-analyzer",  # Use hyphens instead of underscores
            description="This workflow analyzes sales data for a specified quarter and product, generating comprehensive reports with metrics, trends, and insights to support business decision-making and performance tracking",
            search_keywords=["sales", "analysis", "quarterly", "data", "reporting"],
            capabilities=["analyze sales data", "generate quarterly reports", "track product performance"],
            typical_use_cases=["quarterly sales reporting", "product performance analysis"],
        )

        # Mock response needs the structure expected by parse_structured_response
        mock_response = Mock()
        mock_response.json = Mock(
            return_value={
                "content": [{"input": mock_metadata.model_dump()}]  # Claude format
            }
        )

        captured_prompt = None

        def capture_prompt(prompt, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return mock_response

        mock_model.prompt = capture_prompt

        # Run metadata generation
        node = MetadataGenerationNode()
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        node.post(shared, prep_res, exec_res)

        # Verify transformation happened
        assert captured_prompt is not None

        # Check that the user input has been transformed
        assert "<original_request>" in captured_prompt

        # Parse the original request section to verify transformation
        lines = captured_prompt.split("\n")
        in_original_request = False
        original_request_text = ""
        for line in lines:
            if "<original_request>" in line:
                in_original_request = True
            elif "</original_request>" in line:
                in_original_request = False
            elif in_original_request:
                original_request_text += line

        # Verify the transformation worked
        assert "[quarter]" in original_request_text
        assert "[year]" in original_request_text
        assert "[product_id]" in original_request_text

        # Original values should not be in the transformed user input
        assert "Q4" not in original_request_text
        assert "2024" not in original_request_text
        assert "ABC123" not in original_request_text
