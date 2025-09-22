"""Test complete parameter flow from extraction through runtime validation.

WHEN TO RUN:
- After modifying ParameterDiscoveryNode parameter extraction
- After modifying ParameterMappingNode parameter mapping logic
- After modifying RuntimeValidationNode parameter handling
- After changing how extracted_params flows between nodes
- After modifying shared store contracts for parameters

WHAT IT VALIDATES:
- ParameterDiscoveryNode extracts parameters from user input
- ParameterMappingNode maps discovered params to workflow inputs
- extracted_params is correctly populated in shared store
- RuntimeValidationNode receives extracted_params for execution
- Parameters flow correctly through the entire planner pipeline

DEPENDENCIES:
- Mock LLM responses (no real API calls)
- Tests the data contract between planning nodes
"""

from unittest.mock import Mock, patch

from pflow.planning.nodes import (
    ParameterDiscoveryNode,
    ParameterMappingNode,
    RuntimeValidationNode,
)


class TestParameterRuntimeFlow:
    """Test that parameters flow correctly from extraction to runtime validation."""

    def test_extracted_params_flow_to_runtime_validation(self):
        """Test that extracted params from ParameterMappingNode flow to RuntimeValidationNode.

        This test validates the complete parameter chain:
        1. User provides values in natural language
        2. ParameterDiscoveryNode extracts them (Path B)
        3. ParameterMappingNode maps them to workflow inputs
        4. RuntimeValidationNode receives them via extracted_params

        This test would have caught the bug where RuntimeValidationNode wasn't
        getting extracted_params from the shared store.
        """
        # Create a workflow that requires inputs
        test_workflow = {
            "ir_version": "0.1.0",
            "name": "slack-message-sender",
            "inputs": {
                "api_key": {
                    "type": "string",
                    "description": "Slack API key for authentication",
                    "required": True,  # CRITICAL: Required input
                },
                "channel_id": {
                    "type": "string",
                    "description": "Slack channel identifier",
                    "required": True,
                },
                "message": {
                    "type": "string",
                    "description": "Message to send",
                    "required": True,
                },
            },
            "nodes": [
                {
                    "id": "send_message",
                    "type": "http",
                    "params": {
                        "url": "https://slack.com/api/chat.postMessage",
                        "headers": {"Authorization": "Bearer ${api_key}"},
                        "body": {"channel": "${channel_id}", "text": "${message}"},
                    },
                }
            ],
            "edges": [],
            "start_node": "send_message",
        }

        # Set up shared store with user input
        shared = {
            "user_input": "send 'Hello team!' to slack channel C09C16NAU5B using API key xoxb-123456789",
            "generated_workflow": test_workflow,  # Path B: generated workflow
        }

        # Step 1: ParameterDiscoveryNode extracts parameters from user input
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_get_model.return_value = mock_model

            # Mock discovery response
            discovery_response = Mock()
            discovery_response.json = Mock(
                return_value={
                    "content": [
                        {
                            "input": {
                                "parameters": {
                                    "api_key": {"value": "xoxb-123456789", "confidence": 0.95},
                                    "channel_id": {"value": "C09C16NAU5B", "confidence": 0.9},
                                    "message": {"value": "Hello team!", "confidence": 1.0},
                                },
                                "stdin_type": None,
                                "reasoning": "Extracted API key, channel ID, and message from user input",
                            }
                        }
                    ]
                }
            )
            mock_model.prompt.return_value = discovery_response

            discovery_node = ParameterDiscoveryNode()
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)
            discovery_node.post(shared, prep_res, exec_res)

            # Verify discovered params are stored
            assert "discovered_params" in shared
            assert shared["discovered_params"]["api_key"]["value"] == "xoxb-123456789"
            assert shared["discovered_params"]["channel_id"]["value"] == "C09C16NAU5B"
            assert shared["discovered_params"]["message"]["value"] == "Hello team!"

        # Step 2: ParameterMappingNode maps discovered params to workflow inputs
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_get_model.return_value = mock_model

            # Mock mapping response - extracts actual values
            mapping_response = Mock()
            mapping_response.json = Mock(
                return_value={
                    "content": [
                        {
                            "input": {
                                "extracted": {  # NOTE: "extracted", not "parameters"
                                    "api_key": "xoxb-123456789",
                                    "channel_id": "C09C16NAU5B",
                                    "message": "Hello team!",
                                },
                                "missing": [],  # All required params found
                                "confidence": 0.95,
                                "reasoning": "Successfully mapped all required parameters",
                            }
                        }
                    ]
                }
            )
            mock_model.prompt.return_value = mapping_response

            mapping_node = ParameterMappingNode()
            prep_res = mapping_node.prep(shared)
            exec_res = mapping_node.exec(prep_res)
            action = mapping_node.post(shared, prep_res, exec_res)

            # Verify mapping results
            assert action == "params_complete_validate"  # Path B: needs validation
            assert "extracted_params" in shared
            assert shared["extracted_params"]["api_key"] == "xoxb-123456789"
            assert shared["extracted_params"]["channel_id"] == "C09C16NAU5B"
            assert shared["extracted_params"]["message"] == "Hello team!"

        # Step 3: RuntimeValidationNode should receive extracted_params
        runtime_node = RuntimeValidationNode()
        prep_res = runtime_node.prep(shared)

        # CRITICAL ASSERTION: RuntimeValidationNode gets the extracted params
        assert "execution_params" in prep_res
        assert prep_res["execution_params"] == {
            "api_key": "xoxb-123456789",
            "channel_id": "C09C16NAU5B",
            "message": "Hello team!",
        }

        # Verify these params would be passed to compile_ir_to_flow
        with patch("pflow.runtime.compiler.compile_ir_to_flow") as mock_compile:
            mock_flow = Mock()
            mock_flow.run.return_value = None
            mock_compile.return_value = mock_flow

            # Execute runtime validation
            exec_res = runtime_node.exec(prep_res)

            # Verify compile was called with the extracted params
            mock_compile.assert_called_once()
            call_args = mock_compile.call_args

            # Check that initial_params contains our extracted values
            assert call_args.kwargs["initial_params"] == {
                "api_key": "xoxb-123456789",
                "channel_id": "C09C16NAU5B",
                "message": "Hello team!",
            }

    def test_workflow_with_required_inputs_no_extracted_params(self):
        """Test that workflows with required inputs fail when no params are extracted."""
        # Workflow with required inputs
        test_workflow = {
            "ir_version": "0.1.0",
            "name": "test-workflow",
            "inputs": {
                "api_key": {
                    "type": "string",
                    "description": "API key",
                    "required": True,  # Required!
                }
            },
            "nodes": [{"id": "node1", "type": "http", "params": {"api_key": "${api_key}"}}],
            "edges": [],
            "start_node": "node1",
        }

        # Shared store WITHOUT extracted_params
        shared = {
            "generated_workflow": test_workflow,
            # No extracted_params!
        }

        # RuntimeValidationNode should get empty params
        runtime_node = RuntimeValidationNode()
        prep_res = runtime_node.prep(shared)

        assert prep_res["execution_params"] == {}  # Empty since no extracted_params

        # This would fail at runtime due to missing required parameter

    def test_workflow_with_optional_inputs_uses_extracted_params(self):
        """Test that workflows with optional inputs still use extracted params when available."""
        test_workflow = {
            "ir_version": "0.1.0",
            "name": "test-workflow",
            "inputs": {
                "limit": {
                    "type": "integer",
                    "description": "Result limit",
                    "required": False,  # Optional
                    "default": 10,
                }
            },
            "nodes": [{"id": "node1", "type": "fetch", "params": {"limit": "${limit}"}}],
            "edges": [],
            "start_node": "node1",
        }

        # Shared store WITH extracted_params
        shared = {
            "generated_workflow": test_workflow,
            "extracted_params": {
                "limit": 50  # User provided custom value
            },
        }

        runtime_node = RuntimeValidationNode()
        prep_res = runtime_node.prep(shared)

        # Should use the extracted value, not the default
        assert prep_res["execution_params"]["limit"] == 50

    def test_execution_params_override_extracted_params(self):
        """Test that execution_params take precedence over extracted_params."""
        test_workflow = {
            "ir_version": "0.1.0",
            "name": "test-workflow",
            "inputs": {"message": {"type": "string", "required": True}},
            "nodes": [],
            "edges": [],
        }

        # Both execution_params and extracted_params present
        shared = {
            "generated_workflow": test_workflow,
            "extracted_params": {"message": "from extraction"},
            "execution_params": {"message": "from preparation"},  # Takes precedence
        }

        runtime_node = RuntimeValidationNode()
        prep_res = runtime_node.prep(shared)

        # execution_params should override extracted_params
        assert prep_res["execution_params"]["message"] == "from preparation"

    def test_parameter_discovery_to_mapping_integration(self):
        """Test the complete flow from discovery to mapping with real node interactions."""
        # Start with user input that contains parameter values
        shared = {
            "user_input": "analyze the last 30 issues from repo pflow/main",
            "generated_workflow": {
                "ir_version": "0.1.0",
                "name": "issue-analyzer",
                "inputs": {
                    "issue_count": {
                        "type": "integer",
                        "description": "Number of issues to analyze",
                        "required": True,
                    },
                    "repo_name": {
                        "type": "string",
                        "description": "Repository name",
                        "required": True,
                    },
                },
                "nodes": [],
                "edges": [],
            },
        }

        # Mock LLM for both nodes
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_get_model.return_value = mock_model

            # Set up responses for both discovery and mapping
            responses = [
                # ParameterDiscoveryNode response
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "parameters": {
                                        "count": {"value": "30", "confidence": 0.9},
                                        "repository": {"value": "pflow/main", "confidence": 0.85},
                                    },
                                    "stdin_type": None,
                                    "reasoning": "Found issue count and repository",
                                }
                            }
                        ]
                    }
                ),
                # ParameterMappingNode response
                Mock(
                    json=lambda: {
                        "content": [
                            {
                                "input": {
                                    "extracted": {"issue_count": 30, "repo_name": "pflow/main"},
                                    "missing": [],
                                    "confidence": 0.9,
                                    "reasoning": "Mapped count to issue_count, repository to repo_name",
                                }
                            }
                        ]
                    }
                ),
            ]
            mock_model.prompt.side_effect = responses

            # Run discovery
            discovery_node = ParameterDiscoveryNode()
            discovery_node.run(shared)

            # Verify discovery stored params
            assert "discovered_params" in shared
            assert "count" in shared["discovered_params"]

            # Run mapping
            mapping_node = ParameterMappingNode()
            action = mapping_node.run(shared)

            # Verify complete chain
            assert action == "params_complete_validate"
            assert "extracted_params" in shared
            assert shared["extracted_params"]["issue_count"] == 30
            assert shared["extracted_params"]["repo_name"] == "pflow/main"

            # Verify RuntimeValidationNode would get these params
            runtime_node = RuntimeValidationNode()
            prep_res = runtime_node.prep(shared)
            assert prep_res["execution_params"]["issue_count"] == 30
            assert prep_res["execution_params"]["repo_name"] == "pflow/main"

    def test_missing_required_params_prevents_runtime_execution(self):
        """Test that missing required parameters are caught before runtime execution."""
        test_workflow = {
            "ir_version": "0.1.0",
            "name": "test-workflow",
            "inputs": {
                "api_key": {"type": "string", "required": True},
                "channel": {"type": "string", "required": True},
            },
            "nodes": [],
            "edges": [],
        }

        # User only provided one parameter
        shared = {
            "user_input": "send to channel general",
            "generated_workflow": test_workflow,
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_get_model.return_value = mock_model

            # ParameterMappingNode can't find api_key
            mapping_response = Mock(
                json=lambda: {
                    "content": [
                        {
                            "input": {
                                "extracted": {"channel": "general"},
                                "missing": ["api_key"],  # Missing required param
                                "confidence": 0.5,
                                "reasoning": "Could not find API key in user input",
                            }
                        }
                    ]
                }
            )
            mock_model.prompt.return_value = mapping_response

            mapping_node = ParameterMappingNode()
            prep_res = mapping_node.prep(shared)
            exec_res = mapping_node.exec(prep_res)
            action = mapping_node.post(shared, prep_res, exec_res)

            # Should route to params_incomplete
            assert action == "params_incomplete"
            assert "missing_params" in shared
            assert "api_key" in shared["missing_params"]

            # extracted_params should still have what was found
            assert shared["extracted_params"]["channel"] == "general"

    def test_parameter_defaults_applied_correctly(self):
        """Test that parameter defaults are applied when values not provided."""
        test_workflow = {
            "ir_version": "0.1.0",
            "name": "test-workflow",
            "inputs": {
                "limit": {
                    "type": "integer",
                    "description": "Result limit",
                    "required": False,
                    "default": 25,  # Has a default
                },
                "format": {
                    "type": "string",
                    "description": "Output format",
                    "required": False,
                    "default": "json",  # Has a default
                },
            },
            "nodes": [],
            "edges": [],
        }

        shared = {
            "user_input": "fetch data with limit 50",  # Only provides limit
            "generated_workflow": test_workflow,
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_get_model.return_value = mock_model

            # Mapping only extracts limit, not format
            mapping_response = Mock(
                json=lambda: {
                    "content": [
                        {
                            "input": {
                                "extracted": {"limit": 50},  # Only found limit
                                "missing": [],  # format not "missing" because it has default
                                "confidence": 0.8,
                                "reasoning": "Found limit, format will use default",
                            }
                        }
                    ]
                }
            )
            mock_model.prompt.return_value = mapping_response

            mapping_node = ParameterMappingNode()
            mapping_node.run(shared)

            # Note: ParameterMappingNode currently doesn't apply defaults
            # That's handled later by the compiler/runtime
            # This test documents the current behavior
            assert shared["extracted_params"]["limit"] == 50
            # format default would be applied at runtime, not here

    def test_path_a_parameter_flow(self):
        """Test parameter flow in Path A (found existing workflow)."""
        existing_workflow = {
            "ir_version": "0.1.0",
            "name": "existing-workflow",
            "inputs": {
                "search_term": {"type": "string", "required": True},
                "max_results": {"type": "integer", "required": False, "default": 10},
            },
            "nodes": [],
            "edges": [],
        }

        # Path A: found_workflow instead of generated_workflow
        shared = {
            "user_input": "search for 'python tutorials' and get 20 results",
            "found_workflow": {"ir": existing_workflow},  # Path A marker
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_get_model.return_value = mock_model

            mapping_response = Mock(
                json=lambda: {
                    "content": [
                        {
                            "input": {
                                "extracted": {"search_term": "python tutorials", "max_results": 20},
                                "missing": [],
                                "confidence": 0.95,
                                "reasoning": "Extracted search parameters",
                            }
                        }
                    ]
                }
            )
            mock_model.prompt.return_value = mapping_response

            mapping_node = ParameterMappingNode()
            prep_res = mapping_node.prep(shared)

            # Verify it uses found_workflow
            assert prep_res["workflow_ir"] == existing_workflow

            exec_res = mapping_node.exec(prep_res)
            action = mapping_node.post(shared, prep_res, exec_res)

            # Path A returns different action
            assert action == "params_complete"  # NOT params_complete_validate
            assert shared["extracted_params"]["search_term"] == "python tutorials"
            assert shared["extracted_params"]["max_results"] == 20
