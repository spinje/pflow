"""Simple integration tests for the planner flow with correct mocking.

The validation flow has been redesigned to extract parameters BEFORE validation,
allowing workflows with required inputs to pass validation correctly.
"""

from unittest.mock import Mock, patch

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning import create_planner_flow


class TestPlannerSimpleIntegration:
    """Simple integration tests that actually work."""

    def test_path_a_working(self, tmp_path):
        """Test Path A with correct mock setup."""
        # Create test workflow with proper structure
        test_workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "read", "type": "read-file", "params": {"file_path": "${input_file}"}}],
            "edges": [],
            "start_node": "read",
            "inputs": {"input_file": {"description": "File to read", "type": "string", "required": True}},
        }

        # Create test workflow manager
        test_manager = WorkflowManager(workflows_dir=str(tmp_path / "workflows"))
        test_manager.save(name="read-file-workflow", workflow_ir=test_workflow_ir, description="Read a file")

        # Create flow
        flow = create_planner_flow()

        # Setup shared store
        shared = {
            "user_input": "read file test.txt",
            "workflow_manager": test_manager,
        }

        # Mock LLM responses
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            # Discovery finds the workflow
            discovery_response = Mock()
            discovery_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "found": True,
                            "workflow_name": "read-file-workflow",
                            "confidence": 0.95,
                            "reasoning": "Exact match for file reading",
                        }
                    }
                ]
            }

            # Parameter extraction
            param_response = Mock()
            param_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "extracted": {"input_file": "test.txt"},
                            "missing": [],
                            "confidence": 0.9,
                            "reasoning": "Extracted filename from user input",
                        }
                    }
                ]
            }

            # Set up responses in order
            mock_model.prompt.side_effect = [
                discovery_response,
                param_response,
            ]
            mock_get_model.return_value = mock_model

            # Run the flow
            flow.run(shared)

            # Verify success
            assert "planner_output" in shared
            output = shared["planner_output"]
            assert output["success"] is True
            assert output["workflow_ir"] is not None
            assert output["execution_params"] == {"input_file": "test.txt"}
            assert output["error"] is None

            # Verify Path A was taken
            assert "found_workflow" in shared
            assert "generated_workflow" not in shared

            # Verify extracted params exist
            assert shared["extracted_params"] == {"input_file": "test.txt"}

    def test_path_a_missing_params(self, tmp_path):
        """Test Path A with missing required parameters."""
        # Create workflow requiring parameters
        test_workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "process",
                    "type": "process-data",
                    "params": {"input": "${data_file}", "output": "${output_file}"},
                }
            ],
            "edges": [],
            "start_node": "process",
            "inputs": {
                "data_file": {"description": "Input data file", "type": "string", "required": True},
                "output_file": {"description": "Output file path", "type": "string", "required": True},
            },
        }

        # Create test workflow manager
        test_manager = WorkflowManager(workflows_dir=str(tmp_path / "workflows"))
        test_manager.save(name="process-workflow", workflow_ir=test_workflow_ir, description="Process data")

        # Create flow
        flow = create_planner_flow()

        # Setup shared store - vague input missing parameters
        shared = {
            "user_input": "process the data",  # Missing file names
            "workflow_manager": test_manager,
        }

        # Mock LLM responses
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()

            # Discovery finds the workflow
            discovery_response = Mock()
            discovery_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "found": True,
                            "workflow_name": "process-workflow",
                            "confidence": 0.85,
                            "reasoning": "Found data processing workflow",
                        }
                    }
                ]
            }

            # Parameter extraction fails to find all params
            param_response = Mock()
            param_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "extracted": {},  # No parameters extracted
                            "missing": ["data_file", "output_file"],
                            "confidence": 0.2,
                            "reasoning": "No file names specified in user input",
                        }
                    }
                ]
            }

            mock_model.prompt.side_effect = [
                discovery_response,
                param_response,
            ]
            mock_get_model.return_value = mock_model

            # Run the flow
            flow.run(shared)

            # Verify failure due to missing params
            assert "planner_output" in shared
            output = shared["planner_output"]
            assert output["success"] is False
            assert output["error"] is not None
            assert "Missing required parameters" in output["error"]
            # Check missing params without caring about order
            assert set(output["missing_params"]) == {"data_file", "output_file"}

    def test_path_b_generation(self, tmp_path):
        """Test Path B with workflow generation."""
        # Create test workflow manager (empty, no workflows)
        test_manager = WorkflowManager(workflows_dir=str(tmp_path / "workflows"))

        # Create flow
        flow = create_planner_flow()

        # Setup shared store
        shared = {
            "user_input": "create a new workflow to analyze CSV files and generate reports",
            "workflow_manager": test_manager,
        }

        # Mock Registry for component browsing
        with patch("pflow.planning.nodes.Registry") as MockRegistry:
            mock_registry = Mock()
            mock_registry.load.return_value = {
                "read-file": {"interface": {"inputs": [], "outputs": [], "params": []}, "description": "Read files"},
                "llm": {"interface": {"inputs": [], "outputs": [], "params": []}, "description": "Process with LLM"},
                "write-file": {"interface": {"inputs": [], "outputs": [], "params": []}, "description": "Write files"},
            }

            # get_nodes_metadata now takes node_types as argument
            def get_nodes_metadata_mock(node_types):
                metadata = {
                    "read-file": {},
                    "llm": {},
                    "write-file": {},
                }
                return {nt: metadata.get(nt, {}) for nt in node_types if nt in metadata}

            mock_registry.get_nodes_metadata.side_effect = get_nodes_metadata_mock
            MockRegistry.return_value = mock_registry

            # Mock LLM responses
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()

                # Response sequence for Path B with new flow order
                responses = [
                    # 1. Discovery - no workflow found
                    Mock(
                        json=lambda: {
                            "content": [
                                {
                                    "input": {
                                        "found": False,
                                        "workflow_name": None,
                                        "confidence": 0.1,
                                        "reasoning": "No existing CSV analysis workflow",
                                    }
                                }
                            ]
                        }
                    ),
                    # 2. Component browsing
                    Mock(
                        json=lambda: {
                            "content": [
                                {
                                    "input": {
                                        "node_ids": ["read-file", "llm", "write-file"],
                                        "workflow_names": [],
                                        "reasoning": "Selected file and LLM nodes",
                                    }
                                }
                            ]
                        }
                    ),
                    # 3. Parameter discovery
                    Mock(
                        json=lambda: {
                            "content": [
                                {
                                    "input": {
                                        "parameters": {"format": "CSV"},
                                        "stdin_type": None,
                                        "reasoning": "Found CSV format mentioned",
                                    }
                                }
                            ]
                        }
                    ),
                    # 4. Workflow generation (only 1 needed now!)
                    Mock(
                        json=lambda: {
                            "content": [
                                {
                                    "input": {
                                        "ir_version": "0.1.0",
                                        "nodes": [
                                            {
                                                "id": "read",
                                                "type": "read-file",
                                                "params": {"file_path": "${input_file}"},
                                            },
                                            {
                                                "id": "analyze",
                                                "type": "llm",
                                                "params": {"prompt": "Analyze CSV data from ${input_file}"},
                                            },
                                            {
                                                "id": "write",
                                                "type": "write-file",
                                                "params": {
                                                    "file_path": "${output_file}",
                                                    "content": "Analysis complete",
                                                },
                                            },
                                        ],
                                        "edges": [
                                            {"from": "read", "to": "analyze"},
                                            {"from": "analyze", "to": "write"},
                                        ],
                                        "start_node": "read",
                                        "inputs": {
                                            "input_file": {
                                                "description": "CSV file to analyze",
                                                "type": "string",
                                                "required": True,
                                            },
                                            "output_file": {
                                                "description": "Output report file",
                                                "type": "string",
                                                "required": True,
                                            },
                                        },
                                        "outputs": {},
                                    }
                                }
                            ]
                        }
                    ),
                    # 5. Parameter mapping (BEFORE validation now)
                    Mock(
                        json=lambda: {
                            "content": [
                                {
                                    "input": {
                                        "extracted": {},
                                        "missing": ["input_file", "output_file"],
                                        "confidence": 0.0,
                                        "reasoning": "No specific files mentioned",
                                    }
                                }
                            ]
                        }
                    ),
                    # Validation would happen here but param mapping detected missing params
                    # so flow goes to ResultPreparation with error
                ]

                mock_model.prompt.side_effect = responses
                mock_get_model.return_value = mock_model

                # Run the flow
                flow.run(shared)

                # Verify result
                assert "planner_output" in shared
                output = shared["planner_output"]

                # Path B generates workflow but fails due to missing required parameters
                assert output["success"] is False
                assert "Missing required parameters" in output["error"]
                assert set(output["missing_params"]) == {"input_file", "output_file"}

                # Verify Path B was taken
                assert "generated_workflow" in shared
                assert "found_workflow" not in shared
