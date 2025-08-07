"""Integration tests for WorkflowGeneratorNode and ParameterMappingNode.

Tests the critical convergence point where generated workflows (Path B)
meet parameter extraction, ensuring proper template variable handling and
workflow input specifications.
"""

from unittest.mock import Mock, patch

import pytest

from pflow.planning.nodes import (
    ComponentBrowsingNode,
    ParameterDiscoveryNode,
    ParameterMappingNode,
    WorkflowGeneratorNode,
)


@pytest.fixture
def mock_llm_response():
    """Factory for creating mock LLM responses with Anthropic's nested structure."""

    def create_response(**kwargs):
        """Create mock response with correct nested structure."""
        response = Mock()
        response.json.return_value = {"content": [{"input": kwargs}]}
        return response

    return create_response


@pytest.fixture
def mock_registry():
    """Mock registry with GitHub/Git nodes for North Star examples."""
    registry = Mock()
    registry.load.return_value = {
        "git-log": {
            "name": "git-log",
            "interface": {
                "description": "Get git commit history",
                "inputs": ["repo", "since"],
                "outputs": ["commits"],
                "params": [
                    {"key": "repo", "type": "string", "required": True},
                    {"key": "since", "type": "string", "required": False},
                ],
            },
        },
        "github-list-issues": {
            "name": "github-list-issues",
            "interface": {
                "description": "List GitHub issues",
                "inputs": ["repo", "labels", "state"],
                "outputs": ["issues"],
                "params": [
                    {"key": "repo", "type": "string", "required": True},
                    {"key": "labels", "type": "string", "required": False},
                    {"key": "state", "type": "string", "required": False},
                ],
            },
        },
        "llm": {
            "name": "llm",
            "interface": {
                "description": "Process text with LLM",
                "inputs": ["prompt"],
                "outputs": ["response"],
                "params": [{"key": "prompt", "type": "string", "required": True}],
            },
        },
    }
    return registry


class TestGeneratorParameterConvergence:
    """Test WorkflowGeneratorNode creating workflows that ParameterMappingNode validates."""

    def test_generator_creates_workflow_with_inputs_field(self, mock_llm_response):
        """Test generator creates workflow with inputs field that ParameterMappingNode expects."""
        with patch("llm.get_model") as mock_get_model:
            # Mock for WorkflowGeneratorNode - generate-changelog workflow
            generator_response = mock_llm_response(
                ir_version="0.1.0",
                name="generate-changelog",
                description="Generate changelog for repository",
                inputs={
                    "repo": {
                        "type": "string",
                        "required": True,
                        "description": "Repository name",
                    },
                    "since_date": {
                        "type": "string",
                        "required": False,
                        "default": "30 days ago",
                        "description": "Start date for changelog",
                    },
                },
                nodes=[
                    {
                        "id": "fetch_commits",
                        "type": "git-log",
                        "params": {"repo": "{{repo}}", "since": "{{since_date}}"},
                    },
                    {
                        "id": "format_changelog",
                        "type": "llm",
                        "params": {"prompt": "Format commits from {{commits.data}}"},
                    },
                ],
                edges=[{"from": "fetch_commits", "to": "format_changelog"}],
            )

            # Mock for ParameterMappingNode - extracts parameters
            mapping_response = mock_llm_response(
                extracted={"repo": "pflow", "since_date": "2024-01-01"},
                missing=[],
                confidence=0.95,
                reasoning="Extracted repository and date from user input",
            )

            # Configure mock to return different responses
            mock_model = Mock()
            mock_model.prompt.side_effect = [generator_response, mapping_response]
            mock_get_model.return_value = mock_model

            # Simulate Path B: browsing → generation → mapping
            shared = {
                "user_input": "Generate changelog for pflow since 2024-01-01",
                "planning_context": "Available nodes: git-log, llm",
                "browsed_components": {"node_ids": ["git-log", "llm"]},
            }

            # Step 1: Generate workflow
            generator = WorkflowGeneratorNode(wait=0)
            gen_prep = generator.prep(shared)
            gen_exec = generator.exec(gen_prep)
            gen_action = generator.post(shared, gen_prep, gen_exec)

            # Generator routes to "validate" not "generated"
            assert gen_action == "validate"
            assert "generated_workflow" in shared
            workflow = shared["generated_workflow"]
            assert "inputs" in workflow
            assert "repo" in workflow["inputs"]
            assert workflow["inputs"]["repo"]["required"] is True

            # Step 2: Map parameters to generated workflow
            mapper = ParameterMappingNode(wait=0)
            map_prep = mapper.prep(shared)
            map_exec = mapper.exec(map_prep)
            map_action = mapper.post(shared, map_prep, map_exec)

            assert map_action == "params_complete"
            assert "extracted_params" in shared
            assert shared["extracted_params"]["repo"] == "pflow"
            assert shared["extracted_params"]["since_date"] == "2024-01-01"

    def test_template_variables_match_inputs_keys(self, mock_llm_response):
        """Test template variables in nodes match the inputs keys exactly."""
        with patch("llm.get_model") as mock_get_model:
            # Generate issue-triage-report workflow
            generator_response = mock_llm_response(
                ir_version="0.1.0",
                name="issue-triage-report",
                description="Generate issue triage report",
                inputs={
                    "repo": {"type": "string", "required": True},
                    "labels": {"type": "string", "required": False},
                    "state": {"type": "string", "required": False, "default": "open"},
                    "limit": {"type": "integer", "required": False, "default": 100},
                },
                nodes=[
                    {
                        "id": "fetch_issues",
                        "type": "github-list-issues",
                        # Template variables MUST match inputs keys
                        "params": {
                            "repo": "{{repo}}",
                            "labels": "{{labels}}",
                            "state": "{{state}}",
                            "limit": "{{limit}}",
                        },
                    },
                    {
                        "id": "analyze",
                        "type": "llm",
                        "params": {"prompt": "Analyze {{issues.data}}"},
                    },
                ],
                edges=[{"from": "fetch_issues", "to": "analyze"}],
            )

            mock_model = Mock()
            mock_model.prompt.return_value = generator_response
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "Create issue triage report for repo with bug label",
                "planning_context": "Available nodes: github-list-issues, llm",
                "browsed_components": {"node_ids": ["github-list-issues", "llm"]},
            }

            generator = WorkflowGeneratorNode(wait=0)
            prep_res = generator.prep(shared)
            exec_res = generator.exec(prep_res)
            generator.post(shared, prep_res, exec_res)

            workflow = shared["generated_workflow"]

            # Verify template variables match inputs
            fetch_node = workflow["nodes"][0]
            assert "{{repo}}" in str(fetch_node["params"])
            assert "{{labels}}" in str(fetch_node["params"])
            assert "{{state}}" in str(fetch_node["params"])

            # Verify inputs define all template variables
            assert set(workflow["inputs"].keys()) >= {"repo", "labels", "state", "limit"}

    def test_parameter_renaming_workflow_convergence(self, mock_llm_response):
        """Test parameter renaming: discovered 'filename' → generated 'input_file' → mapped correctly."""
        with patch("llm.get_model") as mock_get_model:
            # Discovery finds 'filename' parameter
            discovery_response = mock_llm_response(
                parameters={
                    "filename": {
                        "value": "data.csv",
                        "confidence": 0.9,
                        "source": "explicit",
                    }
                },
                stdin_type=None,
                reasoning="Found filename in user input",
            )

            # Generator creates workflow with 'input_file' parameter
            generator_response = mock_llm_response(
                ir_version="0.1.0",
                name="process-file",
                description="Process input file",
                inputs={
                    "input_file": {
                        "type": "string",
                        "required": True,
                        "description": "Path to input file",
                    }
                },
                nodes=[
                    {
                        "id": "read",
                        "type": "read-file",
                        "params": {"path": "{{input_file}}"},
                    }
                ],
                edges=[],
            )

            # Mapper extracts 'input_file' from context
            mapping_response = mock_llm_response(
                extracted={"input_file": "data.csv"},
                missing=[],
                confidence=0.85,
                reasoning="Mapped filename to input_file parameter",
            )

            mock_model = Mock()
            mock_model.prompt.side_effect = [
                discovery_response,
                generator_response,
                mapping_response,
            ]
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "Process the file data.csv",
                "browsed_components": {"node_ids": ["read-file"]},
                "planning_context": "Available: read-file node",
            }

            # Step 1: Parameter discovery finds 'filename'
            discovery = ParameterDiscoveryNode(wait=0)
            disc_prep = discovery.prep(shared)
            disc_exec = discovery.exec(disc_prep)
            discovery.post(shared, disc_prep, disc_exec)

            assert "discovered_params" in shared
            assert "filename" in shared["discovered_params"]

            # Step 2: Generator creates workflow with 'input_file'
            generator = WorkflowGeneratorNode(wait=0)
            gen_prep = generator.prep(shared)
            gen_exec = generator.exec(gen_prep)
            generator.post(shared, gen_prep, gen_exec)

            assert "input_file" in shared["generated_workflow"]["inputs"]

            # Step 3: Mapper extracts 'input_file' (not 'filename')
            mapper = ParameterMappingNode(wait=0)
            map_prep = mapper.prep(shared)

            # Verify mapper does NOT get discovered_params
            assert "discovered_params" not in map_prep

            map_exec = mapper.exec(map_prep)
            mapper.post(shared, map_prep, map_exec)

            # Mapper should extract based on workflow needs, not discovery
            assert shared["extracted_params"]["input_file"] == "data.csv"

    def test_missing_required_params_triggers_incomplete(self, mock_llm_response):
        """Test missing required parameters trigger 'params_incomplete' routing."""
        with patch("llm.get_model") as mock_get_model:
            # Generator creates workflow with required params
            generator_response = mock_llm_response(
                ir_version="0.1.0",
                name="test-workflow",
                inputs={
                    "repo": {"type": "string", "required": True},
                    "token": {"type": "string", "required": True},
                    "format": {"type": "string", "required": False},
                },
                nodes=[{"id": "n1", "type": "test"}],
                edges=[],
            )

            # Mapper can't find required 'token'
            mapping_response = mock_llm_response(
                extracted={"repo": "my-repo"},
                missing=["token"],
                confidence=0.5,
                reasoning="Could not find authentication token",
            )

            mock_model = Mock()
            mock_model.prompt.side_effect = [generator_response, mapping_response]
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "Process my-repo",
                "planning_context": "test context",
                "browsed_components": {},
            }

            # Generate workflow
            generator = WorkflowGeneratorNode(wait=0)
            gen_prep = generator.prep(shared)
            gen_exec = generator.exec(gen_prep)
            generator.post(shared, gen_prep, gen_exec)

            # Map parameters - should detect missing required
            mapper = ParameterMappingNode(wait=0)
            map_prep = mapper.prep(shared)
            map_exec = mapper.exec(map_prep)
            action = mapper.post(shared, map_prep, map_exec)

            assert action == "params_incomplete"
            assert "missing_params" in shared
            assert "token" in shared["missing_params"]
            assert "repo" not in shared["missing_params"]

    def test_all_required_params_triggers_complete(self, mock_llm_response):
        """Test all required parameters found triggers 'params_complete' routing."""
        with patch("llm.get_model") as mock_get_model:
            # Create-release-notes workflow
            generator_response = mock_llm_response(
                ir_version="0.1.0",
                name="create-release-notes",
                description="Generate release notes",
                inputs={
                    "version": {"type": "string", "required": True},
                    "repo": {"type": "string", "required": True},
                    "include_contributors": {
                        "type": "boolean",
                        "required": False,
                        "default": True,
                    },
                },
                nodes=[
                    {
                        "id": "fetch",
                        "type": "git-log",
                        "params": {"repo": "{{repo}}", "tag": "{{version}}"},
                    }
                ],
                edges=[],
            )

            # Mapper finds all required params
            mapping_response = mock_llm_response(
                extracted={
                    "version": "v1.2.0",
                    "repo": "pflow",
                    # Optional param not provided, should still be complete
                },
                missing=[],
                confidence=0.95,
                reasoning="Found all required parameters",
            )

            mock_model = Mock()
            mock_model.prompt.side_effect = [generator_response, mapping_response]
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "Create release notes for pflow v1.2.0",
                "planning_context": "test context",
                "browsed_components": {},
            }

            # Generate and map
            generator = WorkflowGeneratorNode(wait=0)
            gen_prep = generator.prep(shared)
            gen_exec = generator.exec(gen_prep)
            generator.post(shared, gen_prep, gen_exec)

            mapper = ParameterMappingNode(wait=0)
            map_prep = mapper.prep(shared)
            map_exec = mapper.exec(map_prep)
            action = mapper.post(shared, map_prep, map_exec)

            assert action == "params_complete"
            assert "extracted_params" in shared
            assert shared["extracted_params"]["version"] == "v1.2.0"
            assert shared["extracted_params"]["repo"] == "pflow"
            # Optional param not in extracted_params is fine
            assert "missing_params" not in shared or not shared["missing_params"]


class TestCompletePathBFlow:
    """Test complete Path B flow from browsing to parameter mapping."""

    def test_complete_path_b_generate_changelog(self, mock_registry, mock_llm_response):
        """Test complete Path B flow for generate-changelog North Star example."""
        with (
            patch("pflow.planning.nodes.Registry") as mock_reg_class,
            patch("llm.get_model") as mock_get_model,
        ):
            mock_reg_class.return_value = mock_registry

            # Mock responses for each node
            browsing_response = mock_llm_response(
                node_ids=["git-log", "llm"],
                workflow_names=[],
                reasoning="Selected git and LLM nodes for changelog generation",
            )

            discovery_response = mock_llm_response(
                parameters={
                    "repository": {
                        "value": "pflow",
                        "confidence": 0.9,
                        "source": "explicit",
                    },
                    "start_date": {
                        "value": "2024-01-01",
                        "confidence": 0.8,
                        "source": "explicit",
                    },
                },
                stdin_type=None,
                reasoning="Found repository and date parameters",
            )

            generator_response = mock_llm_response(
                ir_version="0.1.0",
                name="generate-changelog",
                description="Generate changelog from git history",
                inputs={
                    "repo": {"type": "string", "required": True},
                    "since_date": {"type": "string", "required": False},
                },
                nodes=[
                    {
                        "id": "get_commits",
                        "type": "git-log",
                        "params": {"repo": "{{repo}}", "since": "{{since_date}}"},
                    },
                    {
                        "id": "format",
                        "type": "llm",
                        "params": {"prompt": "Format as changelog: {{commits}}"},
                    },
                ],
                edges=[{"from": "get_commits", "to": "format"}],
            )

            mapping_response = mock_llm_response(
                extracted={"repo": "pflow", "since_date": "2024-01-01"},
                missing=[],
                confidence=0.95,
                reasoning="Extracted all parameters successfully",
            )

            mock_model = Mock()
            mock_model.prompt.side_effect = [
                browsing_response,
                discovery_response,
                generator_response,
                mapping_response,
            ]
            mock_get_model.return_value = mock_model

            # Initialize shared store
            shared = {"user_input": "Generate changelog for pflow since 2024-01-01"}

            # Step 1: Component browsing
            browser = ComponentBrowsingNode(wait=0)
            browse_prep = browser.prep(shared)
            browse_exec = browser.exec(browse_prep)
            browse_action = browser.post(shared, browse_prep, browse_exec)

            assert browse_action == "generate"
            assert "git-log" in shared["browsed_components"]["node_ids"]

            # Step 2: Parameter discovery
            discovery = ParameterDiscoveryNode(wait=0)
            disc_prep = discovery.prep(shared)
            disc_exec = discovery.exec(disc_prep)
            discovery.post(shared, disc_prep, disc_exec)

            assert "discovered_params" in shared
            assert "repository" in shared["discovered_params"]

            # Step 3: Workflow generation
            generator = WorkflowGeneratorNode(wait=0)
            gen_prep = generator.prep(shared)
            gen_exec = generator.exec(gen_prep)
            gen_action = generator.post(shared, gen_prep, gen_exec)

            assert gen_action == "validate"
            assert shared["generated_workflow"]["name"] == "generate-changelog"

            # Step 4: Parameter mapping (convergence point)
            mapper = ParameterMappingNode(wait=0)
            map_prep = mapper.prep(shared)
            map_exec = mapper.exec(map_prep)
            map_action = mapper.post(shared, map_prep, map_exec)

            assert map_action == "params_complete"
            assert shared["extracted_params"]["repo"] == "pflow"
            assert shared["extracted_params"]["since_date"] == "2024-01-01"

    def test_path_b_with_stdin_data(self, mock_registry, mock_llm_response):
        """Test Path B flow when stdin data is available."""
        with (
            patch("pflow.planning.nodes.Registry") as mock_reg_class,
            patch("llm.get_model") as mock_get_model,
        ):
            mock_reg_class.return_value = mock_registry

            generator_response = mock_llm_response(
                ir_version="0.1.0",
                name="process-stdin",
                inputs={"format": {"type": "string", "required": False}},
                nodes=[{"id": "process", "type": "llm", "params": {"data": "{{stdin}}"}}],
                edges=[],
            )

            mapping_response = mock_llm_response(
                extracted={"format": "markdown"},
                missing=[],
                confidence=0.8,
                reasoning="Format specified, data from stdin",
            )

            mock_model = Mock()
            mock_model.prompt.side_effect = [generator_response, mapping_response]
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "Format this as markdown",
                "stdin": "Raw data from pipe",
                "planning_context": "test",
                "browsed_components": {"node_ids": ["llm"]},
            }

            # Generate workflow
            generator = WorkflowGeneratorNode(wait=0)
            gen_prep = generator.prep(shared)
            gen_exec = generator.exec(gen_prep)
            generator.post(shared, gen_prep, gen_exec)

            # Map parameters - should handle stdin
            mapper = ParameterMappingNode(wait=0)
            map_prep = mapper.prep(shared)

            # Verify stdin is passed to mapper
            assert map_prep["stdin_data"] == "Raw data from pipe"

            map_exec = mapper.exec(map_prep)
            mapper.post(shared, map_prep, map_exec)

            assert shared["extracted_params"]["format"] == "markdown"


class TestGeneratorRetryMechanism:
    """Test generator retry mechanism with validation errors."""

    def test_generator_retry_with_validation_errors(self, mock_llm_response):
        """Test generator uses validation_errors on retry attempts."""
        with patch("llm.get_model") as mock_get_model:
            # First attempt - missing inputs field
            first_response = mock_llm_response(
                ir_version="0.1.0",
                name="test",
                # Missing 'inputs' field!
                nodes=[{"id": "n1", "type": "test"}],
                edges=[],
            )

            # Second attempt - fixes the issue
            second_response = mock_llm_response(
                ir_version="0.1.0",
                name="test",
                inputs={"param": {"type": "string", "required": True}},
                nodes=[{"id": "n1", "type": "test"}],
                edges=[],
            )

            mock_model = Mock()
            mock_model.prompt.side_effect = [first_response, second_response]
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "test",
                "planning_context": "test context",
                "browsed_components": {},
            }

            generator = WorkflowGeneratorNode(wait=0)

            # First attempt - will generate workflow without inputs
            prep_res1 = generator.prep(shared)
            exec_res1 = generator.exec(prep_res1)
            generator.post(shared, prep_res1, exec_res1)

            # Verify first attempt generated workflow without inputs
            assert "generated_workflow" in shared
            assert "inputs" not in shared["generated_workflow"]

            # Simulate validation finding the issue
            shared["validation_errors"] = ["Missing 'inputs' field in workflow"]
            # generation_attempts was set by post()

            # Second attempt - should fix the issue
            prep_res2 = generator.prep(shared)

            # Verify validation errors are included
            assert prep_res2["validation_errors"] == ["Missing 'inputs' field in workflow"]
            assert prep_res2["generation_attempts"] == 1

            exec_res2 = generator.exec(prep_res2)

            # Should succeed on second attempt with inputs field
            assert "workflow" in exec_res2
            assert "inputs" in exec_res2["workflow"]
            assert exec_res2["attempt"] == 2

    def test_progressive_enhancement_on_retry(self, mock_llm_response):
        """Test generator progressively improves workflow on retries."""
        with patch("llm.get_model") as mock_get_model:
            # Multiple attempts with progressive improvements
            responses = [
                # Attempt 1: Basic but missing template vars
                mock_llm_response(
                    ir_version="0.1.0",
                    name="test",
                    inputs={"repo": {"type": "string", "required": True}},
                    nodes=[{"id": "n1", "type": "git-log", "params": {"repo": "hardcoded"}}],
                    edges=[],
                ),
                # Attempt 2: Fixed template variables
                mock_llm_response(
                    ir_version="0.1.0",
                    name="test",
                    inputs={"repo": {"type": "string", "required": True}},
                    nodes=[{"id": "n1", "type": "git-log", "params": {"repo": "{{repo}}"}}],
                    edges=[],
                ),
            ]

            mock_model = Mock()
            mock_model.prompt.side_effect = responses
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "test",
                "planning_context": "test",
                "browsed_components": {},
            }

            generator = WorkflowGeneratorNode(wait=0)

            # First attempt
            prep1 = generator.prep(shared)
            exec1 = generator.exec(prep1)
            generator.post(shared, prep1, exec1)

            first_workflow = shared["generated_workflow"]
            assert "hardcoded" in str(first_workflow["nodes"][0]["params"])

            # Simulate validation finding the hardcoded value
            shared["validation_errors"] = ["Hardcoded value found: 'hardcoded'"]
            shared["generation_attempts"] = 1

            # Second attempt - should fix
            prep2 = generator.prep(shared)
            exec2 = generator.exec(prep2)
            generator.post(shared, prep2, exec2)

            second_workflow = shared["generated_workflow"]
            assert "{{repo}}" in str(second_workflow["nodes"][0]["params"])
            assert "hardcoded" not in str(second_workflow["nodes"][0]["params"])


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_generator_handles_empty_browsed_components(self, mock_llm_response):
        """Test generator handles empty browsed_components gracefully."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response(
                ir_version="0.1.0",
                name="minimal",
                inputs={},
                nodes=[{"id": "n1", "type": "echo"}],
                edges=[],
            )
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "test",
                "planning_context": "minimal context",
                "browsed_components": {"node_ids": [], "workflow_names": []},
            }

            generator = WorkflowGeneratorNode(wait=0)
            prep_res = generator.prep(shared)
            exec_res = generator.exec(prep_res)
            action = generator.post(shared, prep_res, exec_res)

            assert action == "validate"
            assert "generated_workflow" in shared

    def test_mapper_handles_workflow_without_inputs(self, mock_llm_response):
        """Test mapper handles workflow without inputs field gracefully."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response(
                extracted={}, missing=[], confidence=1.0, reasoning="No params needed"
            )
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "test",
                "generated_workflow": {
                    "ir_version": "0.1.0",
                    # No 'inputs' field
                    "nodes": [{"id": "n1", "type": "static"}],
                    "edges": [],
                },
            }

            mapper = ParameterMappingNode(wait=0)
            prep_res = mapper.prep(shared)
            exec_res = mapper.exec(prep_res)
            action = mapper.post(shared, prep_res, exec_res)

            # Should handle gracefully
            assert action == "params_complete"
            assert "extracted_params" in shared
            assert shared["extracted_params"] == {}

    def test_discovered_params_not_passed_to_mapper(self, mock_llm_response):
        """Test discovered_params are NOT passed to ParameterMappingNode."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response(extracted={"param": "value"}, missing=[], confidence=0.9)
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "test",
                "discovered_params": {
                    "hint1": {"value": "val1", "confidence": 0.8},
                    "hint2": {"value": "val2", "confidence": 0.7},
                },
                "generated_workflow": {
                    "ir_version": "0.1.0",
                    "inputs": {"param": {"type": "string", "required": True}},
                    "nodes": [],
                    "edges": [],
                },
            }

            mapper = ParameterMappingNode(wait=0)
            prep_res = mapper.prep(shared)

            # Verify discovered_params NOT in prep_res
            assert "discovered_params" not in prep_res
            # But should have workflow and user input
            assert prep_res["workflow_ir"] is not None
            assert prep_res["user_input"] == "test"

    def test_generator_uses_discovered_params_as_hints(self, mock_llm_response):
        """Test generator receives discovered_params for context but doesn't enforce them."""
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response(
                ir_version="0.1.0",
                name="test",
                inputs={
                    # Generator can rename parameters
                    "input_file": {"type": "string", "required": True},
                    "output_format": {"type": "string", "required": False},
                },
                nodes=[],
                edges=[],
            )
            mock_get_model.return_value = mock_model

            shared = {
                "user_input": "test",
                "planning_context": "test",
                "browsed_components": {},
                "discovered_params": {
                    # Discovery found these names
                    "filename": {"value": "data.txt", "confidence": 0.9},
                    "format": {"value": "json", "confidence": 0.8},
                },
            }

            generator = WorkflowGeneratorNode(wait=0)
            prep_res = generator.prep(shared)

            # Generator gets discovered_params for context
            assert prep_res["discovered_params"] is not None
            assert "filename" in prep_res["discovered_params"]

            exec_res = generator.exec(prep_res)
            generator.post(shared, prep_res, exec_res)

            # But generator creates its own parameter names
            workflow = shared["generated_workflow"]
            assert "input_file" in workflow["inputs"]
            assert "output_format" in workflow["inputs"]
            assert "filename" not in workflow["inputs"]  # Renamed!
