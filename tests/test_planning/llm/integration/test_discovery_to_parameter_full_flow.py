"""End-to-end integration tests for complete planner flows with real LLM.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests verify the full discovery → browsing → parameter flows with real LLM calls.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_discovery_to_parameter_full_flow.py -v

CRITICAL: These tests validate the convergence architecture where both paths
(Path A: reuse and Path B: generate) meet at ParameterMappingNode.
"""

import logging
import os
import uuid
from pathlib import Path

import pytest

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import (
    ComponentBrowsingNode,
    ParameterDiscoveryNode,
    ParameterMappingNode,
    WorkflowDiscoveryNode,
)

logger = logging.getLogger(__name__)

# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestCompletePathAFlow:
    """Test complete Path A flow: Discovery → Parameter Mapping with real LLM."""

    def setup_method(self):
        """Create a test workflow for Path A scenarios."""
        # Use a unique workflow name for each test run
        self.workflow_name = f"test-read-file-{uuid.uuid4().hex[:8]}"

        # Create a simple read-file workflow to match against
        test_workflow = {
            "name": self.workflow_name,
            "description": "Read data from a file and output its content",
            "inputs": {
                "filename": {
                    "type": "string",
                    "description": "Path to the data file",
                    "required": True,
                }
            },
            "nodes": [
                {
                    "id": "reader",
                    "type": "read_file",
                    "config": {"path": "{{filename}}"},
                }
            ],
            "edges": [],
        }

        # Save test workflow
        workflow_manager = WorkflowManager()
        workflow_manager.save(self.workflow_name, test_workflow)

    def teardown_method(self):
        """Clean up test workflows."""
        workflow_manager = WorkflowManager()
        try:
            workflow_path = Path(workflow_manager.workflow_dir) / f"{self.workflow_name}.json"
            if workflow_path.exists():
                workflow_path.unlink()
        except Exception:  # noqa: S110
            # Ignore cleanup errors - test teardown should not fail tests
            pass

    def test_path_a_complete_flow_with_parameters(self):
        """Test Path A: Discovery finds workflow → Parameter mapping extracts params."""
        # Initialize shared store with user request
        shared = {"user_input": "I want to read a file called data.txt"}

        try:
            # Step 1: WorkflowDiscoveryNode
            discovery_node = WorkflowDiscoveryNode()

            # Run discovery lifecycle
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)
            action = discovery_node.post(shared, prep_res, exec_res)

            logger.info(f"Discovery - Action: {action}, Found: {exec_res['found']}")

            # Verify discovery result
            assert "discovery_result" in shared
            assert "discovery_context" in shared

            # For this test, we expect it to find our test workflow
            if action == "found_existing":
                assert "found_workflow" in shared
                found_workflow = shared["found_workflow"]
                assert found_workflow["name"] == self.workflow_name

                # Step 2: ParameterMappingNode (convergence point)
                mapping_node = ParameterMappingNode()

                # Run parameter mapping lifecycle
                prep_res = mapping_node.prep(shared)
                exec_res = mapping_node.exec(prep_res)
                action = mapping_node.post(shared, prep_res, exec_res)

                logger.info(f"Parameter Mapping - Action: {action}, Extracted: {exec_res.get('extracted', {})}")

                # Verify parameter extraction
                assert "extracted_params" in shared
                assert action in ["params_complete", "params_incomplete"]

                # Should extract filename parameter from user input
                if action == "params_complete":
                    assert "filename" in shared["extracted_params"]
                    assert "data.txt" in str(shared["extracted_params"]["filename"])
                else:
                    assert "missing_params" in shared
                    logger.info(f"Missing parameters: {shared['missing_params']}")

            else:
                logger.info("Workflow not found - would continue to Path B")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_path_a_with_stdin_fallback(self):
        """Test Path A with parameters from stdin when not in user input."""
        # Initialize shared store with vague request and stdin data
        shared = {"user_input": "process the data file", "stdin": "data.txt"}

        try:
            # Step 1: WorkflowDiscoveryNode
            discovery_node = WorkflowDiscoveryNode()
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)
            action = discovery_node.post(shared, prep_res, exec_res)

            if action == "found_existing":
                # Step 2: ParameterMappingNode should use stdin for missing params
                mapping_node = ParameterMappingNode()
                prep_res = mapping_node.prep(shared)
                exec_res = mapping_node.exec(prep_res)
                action = mapping_node.post(shared, prep_res, exec_res)

                logger.info(f"Extracted from stdin: {exec_res.get('extracted', {})}")

                # LLM should recognize stdin can provide the filename
                assert "extracted_params" in shared

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


class TestCompletePathBFlow:
    """Test complete Path B flow: Discovery → Browsing → Parameter Discovery → Parameter Mapping."""

    def test_path_b_complete_flow_generate_changelog(self):
        """Test Path B with generate-changelog example from North Star."""
        # Initialize shared store with North Star example
        shared = {"user_input": "Generate a changelog for the last 20 closed issues from the pflow repository"}

        try:
            # Step 1: WorkflowDiscoveryNode (should route to Path B)
            discovery_node = WorkflowDiscoveryNode()
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)
            action = discovery_node.post(shared, prep_res, exec_res)

            logger.info(f"Discovery - Action: {action}, Reasoning: {exec_res.get('reasoning', '')[:200]}")

            # Should route to Path B since no exact workflow exists
            assert action == "not_found"
            assert "discovery_result" in shared

            # Step 2: ComponentBrowsingNode
            browsing_node = ComponentBrowsingNode()
            prep_res = browsing_node.prep(shared)
            exec_res = browsing_node.exec(prep_res)
            action = browsing_node.post(shared, prep_res, exec_res)

            logger.info(
                f"Browsing - Selected {len(exec_res['node_ids'])} nodes, {len(exec_res['workflow_names'])} workflows"
            )

            assert action == "generate"
            assert "browsed_components" in shared
            assert "planning_context" in shared

            # Should select GitHub nodes for this request
            selected_nodes = exec_res["node_ids"]
            logger.info(f"Selected nodes: {selected_nodes[:5]}...")

            # Step 3: ParameterDiscoveryNode
            param_discovery_node = ParameterDiscoveryNode()
            prep_res = param_discovery_node.prep(shared)
            exec_res = param_discovery_node.exec(prep_res)
            param_discovery_node.post(shared, prep_res, exec_res)

            logger.info(f"Parameter Discovery - Found: {exec_res.get('parameters', {})}")

            assert "discovered_params" in shared
            discovered = shared["discovered_params"]

            # Should discover key parameters from the request
            # Expected: limit=20, state=closed, repo=pflow
            logger.info(f"Discovered parameters: {discovered}")

            # Step 4: Simulate workflow generation (would happen in real flow)
            # For testing, create a mock generated workflow
            shared["generated_workflow"] = {
                "inputs": {
                    "repo": {"type": "string", "required": True, "description": "Repository name"},
                    "limit": {"type": "integer", "required": True, "description": "Number of issues"},
                    "state": {"type": "string", "required": True, "description": "Issue state filter"},
                },
                "nodes": [{"id": "github", "type": "github_list_issues"}],
                "edges": [],
            }

            # Step 5: ParameterMappingNode (convergence point)
            mapping_node = ParameterMappingNode()
            prep_res = mapping_node.prep(shared)
            exec_res = mapping_node.exec(prep_res)
            action = mapping_node.post(shared, prep_res, exec_res)

            logger.info(
                f"Parameter Mapping - Action: {action}, "
                f"Extracted: {exec_res.get('extracted', {})}, "
                f"Missing: {exec_res.get('missing', [])}"
            )

            assert "extracted_params" in shared
            extracted = shared["extracted_params"]

            # Verify critical parameters were extracted
            if action == "params_complete":
                # All required params should be found
                assert "repo" in extracted or "repository" in extracted
                assert "limit" in extracted or "count" in extracted
                assert "state" in extracted or "status" in extracted
            else:
                # Log what was missing for debugging
                logger.warning(f"Missing required parameters: {shared.get('missing_params', [])}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_path_b_with_complex_multi_step_workflow(self):
        """Test Path B with a complex multi-step workflow request."""
        shared = {
            "user_input": (
                "Read all CSV files from the data folder, combine them into one dataset, "
                "filter for records where status is 'active', and save the result as output.json"
            )
        }

        try:
            # Run through complete Path B flow
            discovery_node = WorkflowDiscoveryNode()
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)
            action = discovery_node.post(shared, prep_res, exec_res)

            assert action == "not_found"

            # Component browsing
            browsing_node = ComponentBrowsingNode()
            prep_res = browsing_node.prep(shared)
            exec_res = browsing_node.exec(prep_res)
            action = browsing_node.post(shared, prep_res, exec_res)

            # Should select file nodes and possibly data processing nodes
            logger.info(f"Selected components for multi-step: {exec_res['node_ids'][:10]}")

            # Parameter discovery
            param_discovery_node = ParameterDiscoveryNode()
            prep_res = param_discovery_node.prep(shared)
            exec_res = param_discovery_node.exec(prep_res)
            param_discovery_node.post(shared, prep_res, exec_res)

            discovered = shared["discovered_params"]
            logger.info(f"Discovered from complex request: {discovered}")

            # Should discover: folder=data, status=active, output=output.json
            # Verify at least some parameters were discovered
            assert len(discovered) > 0

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


class TestConvergenceArchitecture:
    """Test the convergence point where both paths meet."""

    def test_convergence_with_different_workflow_sources(self):
        """Test that ParameterMappingNode handles both found and generated workflows."""
        mapping_node = ParameterMappingNode()

        # Test Case 1: Path A with found_workflow
        shared_a = {
            "user_input": "process data.csv and convert to json",
            "found_workflow": {
                "ir": {
                    "inputs": {
                        "input_file": {"type": "string", "required": True},
                        "output_format": {"type": "string", "required": False, "default": "json"},
                    }
                }
            },
        }

        try:
            prep_res = mapping_node.prep(shared_a)
            exec_res = mapping_node.exec(prep_res)
            mapping_node.post(shared_a, prep_res, exec_res)

            logger.info(f"Path A convergence - Extracted: {exec_res.get('extracted', {})}")
            assert "extracted_params" in shared_a

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

        # Test Case 2: Path B with generated_workflow
        shared_b = {
            "user_input": "process data.csv and convert to json",
            "generated_workflow": {
                "inputs": {
                    "filename": {"type": "string", "required": True},
                    "format": {"type": "string", "required": True},
                }
            },
        }

        try:
            prep_res = mapping_node.prep(shared_b)
            exec_res = mapping_node.exec(prep_res)
            mapping_node.post(shared_b, prep_res, exec_res)

            logger.info(f"Path B convergence - Extracted: {exec_res.get('extracted', {})}")
            assert "extracted_params" in shared_b

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


class TestErrorHandlingWithRealLLM:
    """Test error cases and edge conditions with real LLM."""

    def test_llm_produces_unexpected_format(self):
        """Test handling when LLM returns unexpected response format."""
        # Use a request that might confuse the LLM
        shared = {"user_input": "Do something with the thing using the stuff"}

        try:
            discovery_node = WorkflowDiscoveryNode()
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)

            # Even with vague input, should return valid structure
            assert "found" in exec_res
            assert "reasoning" in exec_res
            assert isinstance(exec_res["found"], bool)

        except ValueError as e:
            # If parsing fails, that's what we're testing for
            logger.info(f"LLM parsing error (expected): {e}")
            assert "Failed to parse" in str(e)
        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_missing_required_parameters_flow(self):
        """Test the flow when required parameters can't be extracted."""
        shared = {
            "user_input": "do the workflow",  # Vague, no parameters
            "generated_workflow": {
                "inputs": {
                    "required_param": {"type": "string", "required": True},
                    "another_required": {"type": "string", "required": True},
                }
            },
        }

        try:
            mapping_node = ParameterMappingNode()
            prep_res = mapping_node.prep(shared)
            exec_res = mapping_node.exec(prep_res)
            action = mapping_node.post(shared, prep_res, exec_res)

            # Should route to params_incomplete
            assert action == "params_incomplete"
            assert "missing_params" in shared
            assert len(shared["missing_params"]) > 0

            logger.info(f"Correctly identified missing: {shared['missing_params']}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_parameter_discovery_with_ambiguous_input(self):
        """Test parameter discovery with ambiguous natural language."""
        shared = {
            "user_input": "Get the latest stuff from yesterday and make it nice",
            "planning_context": "File nodes: read_file, write_file",
        }

        try:
            param_node = ParameterDiscoveryNode()
            prep_res = param_node.prep(shared)
            exec_res = param_node.exec(prep_res)

            # Should still return valid structure even if parameters are unclear
            assert "parameters" in exec_res
            assert "reasoning" in exec_res

            logger.info(f"Ambiguous input produced: {exec_res['parameters']}")
            logger.info(f"LLM reasoning: {exec_res['reasoning'][:200]}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


class TestDataFlowIntegrity:
    """Test that data flows correctly through the shared store."""

    def test_shared_store_accumulation_through_path_b(self):
        """Verify data accumulates correctly through entire Path B flow."""
        shared = {"user_input": "analyze sales.csv and generate summary report"}

        expected_keys_after_each_step = [
            # After discovery
            {"discovery_result", "discovery_context"},
            # After browsing
            {"browsed_components", "registry_metadata", "planning_context"},
            # After parameter discovery
            {"discovered_params"},
            # After parameter mapping (with mock workflow)
            {"extracted_params"},
        ]

        try:
            # Step 1: Discovery
            discovery_node = WorkflowDiscoveryNode()
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)
            discovery_node.post(shared, prep_res, exec_res)

            for key in expected_keys_after_each_step[0]:
                assert key in shared, f"Missing {key} after discovery"

            # Step 2: Browsing
            browsing_node = ComponentBrowsingNode()
            prep_res = browsing_node.prep(shared)
            exec_res = browsing_node.exec(prep_res)
            browsing_node.post(shared, prep_res, exec_res)

            for key in expected_keys_after_each_step[1]:
                assert key in shared, f"Missing {key} after browsing"

            # Step 3: Parameter Discovery
            param_discovery_node = ParameterDiscoveryNode()
            prep_res = param_discovery_node.prep(shared)
            exec_res = param_discovery_node.exec(prep_res)
            param_discovery_node.post(shared, prep_res, exec_res)

            for key in expected_keys_after_each_step[2]:
                assert key in shared, f"Missing {key} after parameter discovery"

            # Add mock workflow for mapping
            shared["generated_workflow"] = {
                "inputs": {"file": {"type": "string", "required": True}},
                "nodes": [],
            }

            # Step 4: Parameter Mapping
            mapping_node = ParameterMappingNode()
            prep_res = mapping_node.prep(shared)
            exec_res = mapping_node.exec(prep_res)
            mapping_node.post(shared, prep_res, exec_res)

            for key in expected_keys_after_each_step[3]:
                assert key in shared, f"Missing {key} after parameter mapping"

            # Log final shared store state
            logger.info(f"Final shared store keys: {list(shared.keys())}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


if __name__ == "__main__":
    # Run with logging to see actual LLM responses
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
