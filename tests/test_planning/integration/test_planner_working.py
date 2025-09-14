"""Working integration tests for the planner flow.

These tests demonstrate the correct mock setup that makes the flow work.
Based on the debug script that proved the flow executes correctly.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning import create_planner_flow


class TestPlannerWorking:
    """Working integration tests with correct mock setup."""

    @pytest.fixture
    def changelog_workflow(self):
        """The changelog workflow that should be discovered."""
        return {
            "name": "generate-changelog",
            "description": "Generate a changelog from closed GitHub issues and PRs",
            "version": "1.0.0",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "ir": {
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "fetch",
                        "type": "github-list-issues",
                        "params": {"repo": "${repo}", "state": "closed", "since": "${since_date}", "limit": "${limit}"},
                    },
                    {
                        "id": "generate",
                        "type": "llm",
                        "params": {"prompt": "Generate a changelog from these issues:\n${issues}", "model": "gpt-4"},
                    },
                    {
                        "id": "save",
                        "type": "write-file",
                        "params": {"path": "${output_path}", "content": "${changelog}"},
                    },
                ],
                "edges": [
                    {"from": "fetch", "to": "generate", "action": "default"},
                    {"from": "generate", "to": "save", "action": "default"},
                ],
                "start_node": "fetch",
                "inputs": {
                    "repo": {"description": "GitHub repository (owner/name)", "type": "string", "required": True},
                    "since_date": {
                        "description": "ISO date to fetch issues since",
                        "type": "string",
                        "required": False,
                        "default": "30 days ago",
                    },
                    "limit": {
                        "description": "Maximum number of issues to fetch",
                        "type": "integer",
                        "required": False,
                        "default": 100,
                    },
                    "output_path": {"description": "Path to save the changelog", "type": "string", "required": True},
                },
                "outputs": {},
            },
        }

    def test_path_a_success_with_all_params(self, tmp_path, changelog_workflow):
        """Test successful Path A execution with all parameters extracted."""
        # Create test workflow manager and save workflow
        test_manager = WorkflowManager(workflows_dir=str(tmp_path / "workflows"))
        test_manager.save(
            name="generate-changelog",
            workflow_ir=changelog_workflow["ir"],
            description="Generate a changelog from closed GitHub issues",
        )

        # Create shared store with user input
        shared = {
            "user_input": "create a changelog for anthropics/pflow repo since 2024-01-01 with max 50 issues and save to CHANGELOG.md",
            "workflow_manager": test_manager,
        }

        # Mock the LLM with correct sequence of responses
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            # Define responses in the order they'll be called
            responses = []

            # 1. WorkflowDiscoveryNode will call LLM
            discovery_response = Mock()
            discovery_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "found": True,
                            "workflow_name": "generate-changelog",
                            "confidence": 0.95,
                            "reasoning": "User wants to create a changelog, exact match found",
                        }
                    }
                ]
            }
            responses.append(discovery_response)

            # 2. ParameterMappingNode will call LLM to extract parameters
            param_response = Mock()
            param_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "extracted": {  # Changed from "parameters" to "extracted"
                                "repo": "anthropics/pflow",  # Direct values, not nested dicts
                                "since_date": "2024-01-01",
                                "limit": "50",
                                "output_path": "CHANGELOG.md",
                            },
                            "missing": [],
                            "confidence": 0.95,
                            "reasoning": "All required parameters extracted from user input",
                        }
                    }
                ]
            }
            responses.append(param_response)

            # Set up the mock to return responses in sequence
            mock_model.prompt.side_effect = responses
            mock_get_model.return_value = mock_model

            # Create and run the flow
            flow = create_planner_flow(wait=0)
            flow.run(shared)

        # Verify the results
        assert "planner_output" in shared
        output = shared["planner_output"]

        # Check success
        assert output["success"] is True
        assert output["error"] is None

        # Check workflow IR (it's the actual IR, not the workflow wrapper)
        assert output["workflow_ir"] is not None
        assert output["workflow_ir"]["start_node"] == "fetch"
        assert len(output["workflow_ir"]["nodes"]) == 3

        # Check execution params
        assert output["execution_params"] is not None
        assert output["execution_params"]["repo"] == "anthropics/pflow"
        assert output["execution_params"]["since_date"] == "2024-01-01"
        assert output["execution_params"]["limit"] == "50"
        assert output["execution_params"]["output_path"] == "CHANGELOG.md"

        # Verify Path A was taken
        assert "found_workflow" in shared
        assert "generated_workflow" not in shared

        # Verify intermediate steps
        assert "discovery_result" in shared
        assert shared["discovery_result"]["found"] is True
        assert shared["discovery_result"]["workflow_name"] == "generate-changelog"

        assert "extracted_params" in shared
        assert shared["extracted_params"]["repo"] == "anthropics/pflow"

    def test_path_a_with_missing_required_params(self, tmp_path, changelog_workflow):
        """Test Path A with missing required parameters."""
        # Create test workflow manager and save workflow
        test_manager = WorkflowManager(workflows_dir=str(tmp_path / "workflows"))
        test_manager.save(
            name="generate-changelog",
            workflow_ir=changelog_workflow["ir"],
            description="Generate a changelog from closed GitHub issues",
        )

        # Create shared store with incomplete user input (missing repo and output_path)
        shared = {"user_input": "create a changelog since last month", "workflow_manager": test_manager}

        # Mock the LLM with correct sequence of responses
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            # Define responses
            responses = []

            # 1. WorkflowDiscoveryNode
            discovery_response = Mock()
            discovery_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "found": True,
                            "workflow_name": "generate-changelog",
                            "confidence": 0.85,
                            "reasoning": "User wants a changelog",
                        }
                    }
                ]
            }
            responses.append(discovery_response)

            # 2. ParameterMappingNode - can't extract required params
            param_response = Mock()
            param_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "extracted": {
                                "since_date": "last month"
                                # Missing: repo, output_path (required params)
                            },
                            "missing": ["repo", "output_path"],
                            "confidence": 0.0,
                            "reasoning": "Missing required parameters: repo and output_path",
                        }
                    }
                ]
            }
            responses.append(param_response)

            mock_model.prompt.side_effect = responses
            mock_get_model.return_value = mock_model

            # Create and run the flow
            flow = create_planner_flow(wait=0)
            flow.run(shared)

        # Verify the results
        assert "planner_output" in shared
        output = shared["planner_output"]

        # Check failure due to missing params
        assert output["success"] is False
        assert output["error"] is not None
        assert "Missing required parameters" in output["error"]
        assert "repo" in output["error"]
        assert "output_path" in output["error"]

        # Check missing params list
        assert output["missing_params"] is not None
        assert "repo" in output["missing_params"]
        assert "output_path" in output["missing_params"]

        # Verify Path A was taken but incomplete
        assert "found_workflow" in shared
        assert "generated_workflow" not in shared
        assert "missing_params" in shared
