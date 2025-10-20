"""Unit tests for WorkflowGeneratorNode (Task 17 Subtask 3).

This file tests the workflow generation system that creates workflows
using LLM with structured output for Path B of the Natural Language Planner.

Test Coverage:
1. Class structure and inheritance
2. Planning context validation
3. Prompt building with template emphasis
4. Parameter discovery integration
5. Validation error handling
6. LLM response parsing with Anthropic structure
7. Template variable generation
8. Linear workflow enforcement
9. Error handling and fallback
10. Lazy model loading
"""

import logging
from unittest.mock import Mock, patch

import pytest

from pflow.planning.context_blocks import PlannerContextBuilder
from pflow.planning.nodes import WorkflowGeneratorNode


def create_minimal_context():
    """Create minimal planner context for unit tests (returns blocks)."""
    # Create base blocks
    base_blocks = PlannerContextBuilder.build_base_blocks(
        user_request="test request",
        requirements_result={
            "is_clear": True,
            "steps": ["Step 1"],
            "estimated_nodes": 1,
            "required_capabilities": ["test"],
        },
        browsed_components={"node_ids": ["test-node"], "workflow_names": [], "reasoning": "Test reasoning"},
        planning_context="Test planning context",
        discovered_params={},
    )

    # Add planning output to make it extended blocks
    extended_blocks = PlannerContextBuilder.append_planning_block(
        base_blocks, "Test plan", {"status": "FEASIBLE", "node_chain": "test-node"}
    )

    return extended_blocks


@pytest.fixture
def mock_llm_generator():
    """Mock LLM response for WorkflowGeneratorNode with Anthropic's nested structure."""

    def create_response(workflow=None):
        """Create mock response with correct nested structure for workflow generation."""
        import json

        if workflow is None:
            # Default valid workflow with template variables
            workflow = {
                "ir_version": "0.1.0",
                "name": "generate-changelog",
                "description": "Generate changelog for repository",
                "inputs": {
                    "repo": {"type": "string", "required": True, "description": "Repository name"},
                    "since_date": {
                        "type": "string",
                        "required": False,
                        "default": "30 days ago",
                        "description": "Start date for changelog",
                    },
                },
                "nodes": [
                    {"id": "fetch_commits", "type": "git-log", "params": {"repo": "${repo}", "since": "${since_date}"}},
                    {
                        "id": "format_changelog",
                        "type": "llm",
                        "params": {"prompt": "Format commits from ${commits.data}"},
                    },
                ],
                "edges": [{"from": "fetch_commits", "to": "format_changelog"}],
            }

        response = Mock()
        # Mock text() to return JSON string (root cause fix)
        response.text.return_value = json.dumps(workflow)
        return response

    return create_response


class TestWorkflowGeneratorNodeStructure:
    """Test basic structure and class attributes."""

    def test_class_name_and_inheritance(self):
        """Test that the class name is WorkflowGeneratorNode and inherits from Node."""
        from pocketflow import Node

        assert WorkflowGeneratorNode.__name__ == "WorkflowGeneratorNode"
        assert issubclass(WorkflowGeneratorNode, Node)

    def test_name_class_attribute(self):
        """Test that name = 'generator' is set as class attribute."""
        assert hasattr(WorkflowGeneratorNode, "name")
        assert WorkflowGeneratorNode.name == "generator"


class TestPlanningContextValidation:
    """Test planning context validation and error handling."""

    def test_missing_context_raises_valueerror(self):
        """Test missing extended context raises ValueError with specific message."""
        node = WorkflowGeneratorNode()
        prep_res = {
            # No planner_extended_blocks or planner_accumulated_blocks provided
            "user_input": "test request",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        with pytest.raises(ValueError) as exc_info:
            node.exec(prep_res)

        assert "requires planner_extended_blocks" in str(exc_info.value)

    def test_retry_with_accumulated_context(self):
        """Test retry uses accumulated context properly."""
        node = WorkflowGeneratorNode()
        accumulated_blocks = create_minimal_context()
        accumulated_blocks = PlannerContextBuilder.append_workflow_block(
            accumulated_blocks, {"nodes": [], "edges": [], "start_node": "n1"}, 1
        )

        prep_res = {
            "planner_accumulated_blocks": accumulated_blocks,
            "user_input": "test request",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": ["Error 1"],
            "generation_attempts": 1,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        # Should not raise - accumulated blocks are valid
        try:
            # This will fail at the LLM call, but that's OK for this test
            node.exec(prep_res)
        except Exception as e:
            # Should fail on LLM call, not context validation
            assert "planner_extended_blocks" not in str(e)

    @patch("llm.get_model")
    def test_valid_planning_context_generates_workflow(self, mock_get_model, mock_llm_generator):
        """Test valid planning_context generates workflow with inputs field."""
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_generator()
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "user_input": "generate changelog",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        result = node.exec(prep_res)

        assert "workflow" in result
        assert "inputs" in result["workflow"]
        assert result["workflow"]["inputs"]["repo"]["type"] == "string"
        assert result["attempt"] == 1


class TestPromptBuilding:
    """Test prompt generation with proper requirements."""

    # DELETED: Tests that checked prompt content (anti-pattern)
    # The following tests were removed because they tested implementation details
    # (prompt content) instead of behavior. We have comprehensive behavioral tests
    # in tests/test_planning/llm/prompts/test_workflow_generator_prompt.py that
    # verify the system actually produces workflows with these characteristics:
    # - Template variable usage (not hardcoding)
    # - Linear/sequential execution
    # - Proper data flow
    #
    # Testing prompt content is like testing that a sorting algorithm uses specific
    # variable names - what matters is the OUTPUT behavior, not the implementation.
    # See test_workflow_generator_prompt.py lines 546-596 for behavioral validation.


class TestParameterIntegration:
    """Test parameter discovery integration and renaming."""

    @patch("llm.get_model")
    def test_discovered_params_included_in_context(self, mock_get_model, mock_llm_generator):
        """Test discovered_params are included in base context."""
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_generator()
        mock_get_model.return_value = mock_model

        # Create blocks with discovered params
        blocks = PlannerContextBuilder.build_base_blocks(
            user_request="test",
            requirements_result={"is_clear": True, "steps": ["Step 1"]},
            browsed_components={"node_ids": ["test-node"]},
            planning_context="test context",
            discovered_params={"filename": "test.txt", "repo": "owner/repo"},
        )

        # Check that discovered params are in the blocks
        combined_text = "\n".join(block["text"] for block in blocks)
        assert "user_values" in combined_text  # Now uses XML tag instead of header
        assert "filename" in combined_text
        assert "repo" in combined_text
        assert "NEVER be hardcoded" in combined_text  # Warning about not hardcoding

    @patch("llm.get_model")
    def test_discovered_params_none_generates_workflow(self, mock_get_model, mock_llm_generator):
        """Test discovered_params None generates workflow without parameter hints."""
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_generator()
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "user_input": "test",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        result = node.exec(prep_res)
        assert "workflow" in result


class TestValidationErrorHandling:
    """Test validation error feedback through context blocks."""

    def test_validation_errors_included_in_context(self):
        """Test validation_errors are included in context blocks."""
        base_blocks = create_minimal_context()
        errors = ["Missing required parameter: repo", "Invalid node type: unknown"]

        blocks_with_errors = PlannerContextBuilder.append_errors_block(base_blocks, errors)

        # Check that errors are in the blocks
        combined_text = "\n".join(block["text"] for block in blocks_with_errors)
        assert "Validation Errors" in combined_text
        assert "Missing required parameter: repo" in combined_text
        assert "Invalid node type: unknown" in combined_text

    def test_validation_errors_max_three_in_context(self):
        """Test validation_errors > 3 only includes first 3 in context."""
        base_blocks = create_minimal_context()
        errors = ["Error 1", "Error 2", "Error 3", "Error 4", "Error 5", "Error 6", "Error 7"]

        blocks_with_errors = PlannerContextBuilder.append_errors_block(base_blocks, errors)

        # Check that only first 3 errors are included (updated behavior)
        combined_text = "\n".join(block["text"] for block in blocks_with_errors)
        assert "Error 1" in combined_text
        assert "Error 2" in combined_text
        assert "Error 3" in combined_text
        # The new implementation only shows top 3 errors
        assert "Error 4" not in combined_text
        assert "Error 5" not in combined_text


class TestLLMResponseParsing:
    """Test LLM response parsing and error handling."""

    @patch("llm.get_model")
    def test_llm_returns_none_raises_valueerror(self, mock_get_model):
        """Test LLM returns None raises ValueError."""
        mock_model = Mock()
        mock_response = Mock()
        mock_response.text.return_value = ""  # Empty string triggers "LLM returned empty response"
        mock_model.prompt.return_value = mock_response
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "user_input": "test",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        with pytest.raises(ValueError) as exc_info:
            node.exec(prep_res)

        assert "LLM returned empty response" in str(exc_info.value)

    @patch("llm.get_model")
    def test_response_parsed_from_nested_structure(self, mock_get_model, mock_llm_generator):
        """Test response parsed from nested structure (response_data['content'][0]['input'])."""
        mock_model = Mock()
        workflow = {"ir_version": "0.1.0", "name": "test", "nodes": [{"id": "n1", "type": "test"}], "edges": []}
        mock_model.prompt.return_value = mock_llm_generator(workflow)
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "user_input": "test",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        result = node.exec(prep_res)

        assert result["workflow"]["name"] == "test"
        assert len(result["workflow"]["nodes"]) == 1

    @patch("llm.get_model")
    def test_llm_response_missing_content_logs_warning(self, mock_get_model, caplog):
        """Test LLM response missing content logs warning but returns raw result."""
        import json
        import logging

        mock_model = Mock()
        mock_response = Mock()
        # Return valid JSON but missing required workflow fields
        mock_response.text.return_value = json.dumps({"no_content": "here"})
        mock_model.prompt.return_value = mock_response
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "user_input": "test",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        # Should NOT raise, but logs warning and returns raw result
        with caplog.at_level(logging.WARNING):
            result = node.exec(prep_res)

        # Verify warning was logged about validation failure
        assert "Failed to validate result through FlowIR" in caplog.text

        # Result contains the raw (invalid) data with default ir_version added
        assert "workflow" in result
        assert result["workflow"]["no_content"] == "here"
        assert result["workflow"]["ir_version"] == "1.0.0"  # Default added by node


class TestWorkflowGeneration:
    """Test workflow generation constraints and requirements."""

    @patch("llm.get_model")
    def test_generated_workflow_has_linear_edges_only(self, mock_get_model):
        """Test generated workflow has linear edges only (no action field in edges)."""
        import json

        mock_model = Mock()

        # Create workflow with only linear edges (no action field)
        workflow = {
            "ir_version": "0.1.0",
            "name": "linear-workflow",
            "nodes": [{"id": "n1", "type": "node1"}, {"id": "n2", "type": "node2"}, {"id": "n3", "type": "node3"}],
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
        }

        response = Mock()
        response.text.return_value = json.dumps(workflow)
        mock_model.prompt.return_value = response
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "user_input": "test",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        result = node.exec(prep_res)

        # Verify no edges have action field (linear only)
        for edge in result["workflow"]["edges"]:
            assert "action" not in edge
            assert "from" in edge
            assert "to" in edge


class TestTemplateVariables:
    """Test template variable generation and validation."""

    @patch("llm.get_model")
    def test_template_variables_use_dollar_prefix(self, mock_get_model):
        """Test template variables use $ prefix (all params with variables start with $)."""
        import json

        mock_model = Mock()

        workflow = {
            "ir_version": "0.1.0",
            "name": "template-workflow",
            "inputs": {"repo": {"type": "string", "required": True}, "issue": {"type": "integer", "required": True}},
            "nodes": [
                {
                    "id": "fetch",
                    "type": "github-issue",
                    "params": {"repository": "${repo}", "issue_number": "${issue}", "static_value": "constant"},
                }
            ],
            "edges": [],
        }

        response = Mock()
        response.text.return_value = json.dumps(workflow)
        mock_model.prompt.return_value = response
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "user_input": "test",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        result = node.exec(prep_res)

        # Check that dynamic values use $ prefix
        params = result["workflow"]["nodes"][0]["params"]
        assert params["repository"] == "${repo}"
        assert params["issue_number"] == "${issue}"
        assert params["static_value"] == "constant"  # Static values don't use $

    @patch("llm.get_model")
    def test_template_paths_supported(self, mock_get_model):
        """Test template paths supported (${var.field.subfield} in params)."""
        import json

        mock_model = Mock()

        workflow = {
            "ir_version": "0.1.0",
            "name": "path-workflow",
            "inputs": {"data": {"type": "object", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "params": {"prompt": "Process user ${data.user.name} from ${data.user.email}"},
                }
            ],
            "edges": [],
        }

        response = Mock()
        response.text.return_value = json.dumps(workflow)
        mock_model.prompt.return_value = response
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "user_input": "test",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        result = node.exec(prep_res)

        # Check that path syntax is preserved
        prompt = result["workflow"]["nodes"][0]["params"]["prompt"]
        assert "${data.user.name}" in prompt
        assert "${data.user.email}" in prompt

    @patch("llm.get_model")
    def test_template_variables_match_inputs_keys(self, mock_get_model):
        """Test template variables match inputs keys (each ${var} has corresponding inputs key)."""
        import json

        mock_model = Mock()

        workflow = {
            "ir_version": "0.1.0",
            "name": "issue-triage-report",
            "inputs": {
                "repo": {"type": "string", "required": True},
                "labels": {"type": "array", "required": False, "default": []},
                "state": {"type": "string", "required": False, "default": "open"},
                "limit": {"type": "integer", "required": False, "default": 100},
            },
            "nodes": [
                {
                    "id": "fetch_issues",
                    "type": "github-issues",
                    "params": {
                        "repository": "${repo}",
                        "labels": "${labels}",
                        "state": "${state}",
                        "limit": "${limit}",
                    },
                }
            ],
            "edges": [],
        }

        response = Mock()
        response.text.return_value = json.dumps(workflow)
        mock_model.prompt.return_value = response
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "old_planning_context": "test context",
            "user_input": "create issue triage report",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        result = node.exec(prep_res)

        # All template variables should have corresponding input keys
        inputs = result["workflow"]["inputs"]
        params = result["workflow"]["nodes"][0]["params"]

        assert "${repo}" in params["repository"] and "repo" in inputs
        assert "${labels}" in params["labels"] and "labels" in inputs
        assert "${state}" in params["state"] and "state" in inputs
        assert "${limit}" in str(params["limit"]) and "limit" in inputs


class TestErrorHandling:
    """Test error handling and fallback mechanisms."""

    def test_exec_fallback_returns_compatible_structure(self):
        """Test exec_fallback raises CriticalPlanningError for WorkflowGeneratorNode."""
        from pflow.core.exceptions import CriticalPlanningError

        node = WorkflowGeneratorNode()
        prep_res = {"generation_attempts": 1}
        exc = ValueError("Test error")

        # WorkflowGeneratorNode is critical and should raise an exception
        with pytest.raises(CriticalPlanningError) as exc_info:
            node.exec_fallback(prep_res, exc)

        # Verify the exception details
        assert exc_info.value.node_name == "WorkflowGeneratorNode"
        assert "Cannot generate workflow" in exc_info.value.reason
        assert exc_info.value.original_error == exc

    def test_post_handles_exec_fallback_result(self):
        """Test that exec_fallback raises CriticalPlanningError and doesn't reach post().

        This test validates that WorkflowGeneratorNode properly aborts the flow
        on critical failures rather than trying to continue with invalid data.
        """
        from pflow.core.exceptions import CriticalPlanningError

        node = WorkflowGeneratorNode()
        shared = {}
        prep_res = {"generation_attempts": 1}

        # exec_fallback now raises an exception rather than returning a result
        exc = ValueError("LLM API failed")

        with pytest.raises(CriticalPlanningError) as exc_info:
            node.exec_fallback(prep_res, exc)

        # Verify the exception prevents reaching post()
        assert exc_info.value.node_name == "WorkflowGeneratorNode"
        assert "Cannot generate workflow" in exc_info.value.reason
        assert exc_info.value.original_error == exc

        # The shared store should not be modified since post() isn't reached
        assert "generated_workflow" not in shared
        assert "generation_attempts" not in shared


class TestLazyLoading:
    """Test lazy loading of models."""

    @patch("llm.get_model")
    def test_model_loaded_lazily_in_exec(self, mock_get_model, mock_llm_generator):
        """Test model loaded lazily in exec (llm.get_model called inside exec not __init__)."""
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_generator()
        mock_get_model.return_value = mock_model

        # Create node - should NOT call get_model
        node = WorkflowGeneratorNode()
        mock_get_model.assert_not_called()

        # Call exec - should call get_model
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "user_input": "test",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        node.exec(prep_res)
        mock_get_model.assert_called_once_with("test-model")


class TestLogging:
    """Test logging functionality.

    NOTE: This test class is skipped because it only tests logging output,
    not actual functionality. The logging configuration in main.py suppresses
    debug logs for UX reasons, and testing log messages is an anti-pattern
    that doesn't verify real behavior.
    """

    @patch("llm.get_model")
    def test_logging_present(self, mock_get_model, mock_llm_generator, caplog):
        """Test logging present (logger.debug calls for workflow generation)."""
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_generator()
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "old_planning_context": "test context",
            "user_input": "generate a changelog for my repository",
            "discovered_params": None,
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        with caplog.at_level(logging.DEBUG):
            node.exec(prep_res)  # We don't need to use the result here

        # Check for debug logs
        assert "Generating workflow for: generate a changelog for my repository" in caplog.text
        assert "Generated" in caplog.text
        assert "nodes" in caplog.text


class TestNorthStarExamples:
    """Test with North Star examples."""

    @patch("llm.get_model")
    def test_generate_changelog_workflow(self, mock_get_model):
        """Test generation of generate-changelog workflow with repo and since_date parameters."""
        import json

        mock_model = Mock()

        changelog_workflow = {
            "ir_version": "0.1.0",
            "name": "generate-changelog",
            "description": "Generate changelog for a repository",
            "inputs": {
                "repo": {"type": "string", "required": True, "description": "Repository name (owner/repo format)"},
                "since_date": {
                    "type": "string",
                    "required": False,
                    "default": "30 days ago",
                    "description": "Start date for changelog",
                },
            },
            "nodes": [
                {
                    "id": "fetch_commits",
                    "type": "git-log",
                    "params": {"repository": "${repo}", "since": "${since_date}"},
                },
                {
                    "id": "generate_changelog",
                    "type": "llm",
                    "params": {"prompt": "Generate changelog from commits: ${commits}"},
                },
            ],
            "edges": [{"from": "fetch_commits", "to": "generate_changelog"}],
        }

        response = Mock()
        response.text.return_value = json.dumps(changelog_workflow)
        mock_model.prompt.return_value = response
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "old_planning_context": "Available: git-log, llm nodes",
            "user_input": "generate changelog for my repo since last month",
            "discovered_params": {"repo": "owner/repo", "since": "last month"},
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        result = node.exec(prep_res)

        assert result["workflow"]["name"] == "generate-changelog"
        assert "repo" in result["workflow"]["inputs"]
        assert "since_date" in result["workflow"]["inputs"]
        assert result["workflow"]["inputs"]["repo"]["required"] is True
        assert result["workflow"]["inputs"]["since_date"]["required"] is False

    @patch("llm.get_model")
    def test_issue_triage_report_workflow(self, mock_get_model):
        """Test generation of issue-triage-report workflow with repo, labels, state, limit parameters."""
        import json

        mock_model = Mock()

        triage_workflow = {
            "ir_version": "0.1.0",
            "name": "issue-triage-report",
            "description": "Generate issue triage report",
            "inputs": {
                "repo": {"type": "string", "required": True, "description": "Repository name"},
                "labels": {"type": "array", "required": False, "default": [], "description": "Filter by labels"},
                "state": {
                    "type": "string",
                    "required": False,
                    "default": "open",
                    "description": "Issue state (open, closed, all)",
                },
                "limit": {
                    "type": "integer",
                    "required": False,
                    "default": 100,
                    "description": "Maximum issues to fetch",
                },
            },
            "nodes": [
                {
                    "id": "fetch_issues",
                    "type": "github-issues",
                    "params": {
                        "repository": "${repo}",
                        "labels": "${labels}",
                        "state": "${state}",
                        "per_page": "${limit}",
                    },
                },
                {
                    "id": "generate_report",
                    "type": "llm",
                    "params": {"prompt": "Create triage report from issues: ${issues}"},
                },
            ],
            "edges": [{"from": "fetch_issues", "to": "generate_report"}],
        }

        response = Mock()
        response.text.return_value = json.dumps(triage_workflow)
        mock_model.prompt.return_value = response
        mock_get_model.return_value = mock_model

        node = WorkflowGeneratorNode()
        prep_res = {
            "planner_extended_blocks": create_minimal_context(),
            "old_planning_context": "Available: github-issues, llm nodes",
            "user_input": "create issue triage report for high priority bugs",
            "discovered_params": {
                "repo": "owner/repo",
                "labels": ["bug", "high-priority"],
                "state": "open",
                "limit": 50,
            },
            "browsed_components": {},
            "validation_errors": [],
            "generation_attempts": 0,
            "model_name": "test-model",
            "temperature": 0.0,
        }

        result = node.exec(prep_res)

        assert result["workflow"]["name"] == "issue-triage-report"
        assert len(result["workflow"]["inputs"]) == 4
        assert all(param in result["workflow"]["inputs"] for param in ["repo", "labels", "state", "limit"])
        assert result["workflow"]["inputs"]["repo"]["required"] is True
        assert result["workflow"]["inputs"]["limit"]["default"] == 100


class TestPostProcessing:
    """Test post-processing and routing."""

    def test_post_stores_workflow_and_routes_to_validation(self):
        """Test post() stores generated workflow and routes to validation."""
        node = WorkflowGeneratorNode()
        shared = {}
        prep_res = {"generation_attempts": 0}
        exec_res = {
            "workflow": {"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "test"}], "edges": []},
            "attempt": 1,
        }

        action = node.post(shared, prep_res, exec_res)

        assert shared["generated_workflow"] == exec_res["workflow"]
        assert shared["generation_attempts"] == 1
        assert action == "validate"
