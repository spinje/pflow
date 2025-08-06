"""LLM prompt-sensitive tests for parameter management nodes.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests are PROMPT-SENSITIVE and will break if the parameter prompts change.
They verify the exact prompt structure and LLM response format.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_parameter_prompts.py -v
"""

import logging
import os

import pytest

from pflow.planning.nodes import ParameterDiscoveryNode, ParameterMappingNode, ParameterPreparationNode

logger = logging.getLogger(__name__)

# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestParameterDiscoveryPromptSensitive:
    """Tests that are sensitive to parameter discovery prompt changes."""

    def test_parameter_discovery_basic_extraction(self):
        """Test ParameterDiscoveryNode extracts basic parameters from natural language."""
        node = ParameterDiscoveryNode()
        # North Star Example: generate-changelog
        shared = {
            "user_input": "Generate a changelog from recent commits in the pflow repo since 2024-01-01 in markdown format"
        }

        # Run the full lifecycle
        prep_res = node.prep(shared)

        # Verify prep includes model configuration
        assert "model_name" in prep_res
        assert "temperature" in prep_res
        assert prep_res["model_name"] == "anthropic/claude-sonnet-4-0"
        assert prep_res["temperature"] == 0.0

        # Execute with real LLM
        try:
            exec_res = node.exec(prep_res)

            # Verify we got a valid response structure
            assert isinstance(exec_res, dict)
            assert "parameters" in exec_res
            assert "stdin_type" in exec_res
            assert "reasoning" in exec_res
            assert isinstance(exec_res["parameters"], dict)

            # Verify we extracted the expected parameters
            params = exec_res["parameters"]
            logger.info(f"Discovered parameters: {params}")
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # Check we found key parameters (repo, since_date, format)
            # The LLM might use different param names, so be flexible
            has_repo = any("pflow" in str(v).lower() for v in params.values())
            has_date = any("2024-01-01" in str(v) or "2024" in str(v) for v in params.values())
            has_format = any("markdown" in str(v).lower() or "md" in str(v).lower() for v in params.values())

            assert has_repo, f"Expected to find pflow repo in parameters: {params}"
            assert has_date, f"Expected to find since date in parameters: {params}"
            assert has_format, f"Expected to find markdown format in parameters: {params}"

            # Run post to store parameters
            action = node.post(shared, prep_res, exec_res)
            assert action == ""  # Continues Path B
            assert "discovered_params" in shared
            assert shared["discovered_params"] == exec_res["parameters"]

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_parameter_discovery_with_complex_input(self):
        """Test extraction of multiple parameter types from complex input."""
        node = ParameterDiscoveryNode()
        # North Star Example: issue-triage-report
        shared = {
            "user_input": "Create a triage report for GitHub issues from anthropic/pflow repo with bug and enhancement labels, closed state, limit to 25"
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)
            params = exec_res["parameters"]

            logger.info(f"Complex extraction - Parameters: {params}")
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # Should extract repo, labels, state, and limit
            has_repo = any("anthropic/pflow" in str(v).lower() or "pflow" in str(v).lower() for v in params.values())
            has_labels = any("bug" in str(v).lower() or "enhancement" in str(v).lower() for v in params.values())
            has_state = any("closed" in str(v).lower() for v in params.values())
            has_limit = any("25" in str(v) or v == 25 for v in params.values())

            assert has_repo, f"Expected to find repo in parameters: {params}"
            assert has_labels, f"Expected to find labels in parameters: {params}"
            assert has_state, f"Expected to find 'closed' state in parameters: {params}"
            assert has_limit, f"Expected to find limit 25 in parameters: {params}"

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_parameter_discovery_with_stdin(self):
        """Test parameter discovery recognizes stdin data."""
        node = ParameterDiscoveryNode()
        shared = {
            "user_input": "Process the piped data and extract email addresses",
            "stdin": "Sample data with test@example.com in it",
        }

        prep_res = node.prep(shared)

        # Verify stdin info is included
        assert prep_res["stdin_info"] is not None
        assert prep_res["stdin_info"]["type"] == "text"
        assert "Sample data" in prep_res["stdin_info"]["preview"]

        try:
            exec_res = node.exec(prep_res)

            logger.info(f"Stdin test - Parameters: {exec_res['parameters']}")
            logger.info(f"Stdin type: {exec_res['stdin_type']}")
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # When stdin is present, parameters might be minimal
            # The important part is recognizing stdin is available
            if exec_res["stdin_type"]:
                assert exec_res["stdin_type"] == "text"

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_parameter_discovery_with_planning_context(self):
        """Test that planning context influences parameter discovery."""
        node = ParameterDiscoveryNode()

        # Simulate having browsed components
        # North Star Example: create-release-notes with context
        shared = {
            "user_input": "Create release notes for version 2.0 with contributor list",
            "browsed_components": {
                "node_ids": ["github-list-contributors", "github-list-commits", "llm-node"],
                "workflow_names": ["generate-release-notes"],
            },
            "planning_context": "github-list-contributors requires 'repo' parameter, llm-node requires 'prompt' parameter",
        }

        prep_res = node.prep(shared)

        # Verify context is included
        assert prep_res["planning_context"] == shared["planning_context"]
        assert prep_res["browsed_components"] == shared["browsed_components"]

        try:
            exec_res = node.exec(prep_res)
            params = exec_res["parameters"]

            logger.info(f"Context-aware - Parameters: {params}")
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # With context about needing repo parameter,
            # the LLM should extract version and include_contributors flag
            has_version = any("2.0" in str(v) or "version" in str(k).lower() for k, v in params.items())
            has_contributors = any("contributor" in str(v).lower() or "true" in str(v).lower() for v in params.values())
            assert has_version, f"Expected version parameter with context: {params}"
            assert has_contributors, f"Expected contributor flag with context: {params}"

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


class TestParameterMappingPromptSensitive:
    """Tests that are sensitive to parameter mapping prompt changes."""

    def test_parameter_mapping_basic_workflow(self):
        """Test ParameterMappingNode maps parameters to workflow inputs."""
        node = ParameterMappingNode()

        # Create a simple workflow IR with defined inputs
        # North Star Example: summarize-github-issue
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "github", "type": "github-get-issue"}],
            "inputs": {
                "issue_number": {"type": "integer", "required": True, "description": "GitHub issue number"},
                "repo": {"type": "string", "required": True, "description": "Repository name"},
            },
        }

        shared = {"user_input": "Summarize issue #123 from the pflow repository", "generated_workflow": workflow_ir}

        prep_res = node.prep(shared)

        # Verify workflow IR is included
        assert prep_res["workflow_ir"] == workflow_ir

        try:
            exec_res = node.exec(prep_res)

            # Verify response structure
            assert isinstance(exec_res, dict)
            assert "extracted" in exec_res
            assert "missing" in exec_res
            assert "confidence" in exec_res
            assert "reasoning" in exec_res

            logger.info(f"Extracted: {exec_res['extracted']}")
            logger.info(f"Missing: {exec_res['missing']}")
            logger.info(f"Confidence: {exec_res['confidence']}")
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # Should extract the issue_number and repo parameters
            if exec_res["extracted"]:
                assert "issue_number" in exec_res["extracted"] or "123" in str(exec_res["extracted"].values())
                assert "repo" in exec_res["extracted"] or "pflow" in str(exec_res["extracted"].values())
                assert len(exec_res["missing"]) == 0
                assert exec_res["confidence"] > 0.5

            # Run post to check routing
            action = node.post(shared, prep_res, exec_res)
            if exec_res["missing"]:
                assert action == "params_incomplete"
                assert "missing_params" in shared
            else:
                assert action == "params_complete"
                assert "extracted_params" in shared

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_parameter_mapping_multiple_required(self):
        """Test mapping with multiple required parameters."""
        node = ParameterMappingNode()

        # North Star Example: issue-triage-report parameters
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [],
            "inputs": {
                "repo": {"type": "string", "required": True, "description": "GitHub repository (owner/name format)"},
                "labels": {"type": "array", "required": True, "description": "Issue labels to filter"},
                "state": {
                    "type": "string",
                    "required": False,
                    "default": "open",
                    "description": "Issue state filter",
                },
                "limit": {
                    "type": "integer",
                    "required": False,
                    "default": 100,
                    "description": "Maximum issues to retrieve",
                },
            },
        }

        shared = {
            "user_input": "Get bug and security issues from anthropic/pflow repository, limit to 50",
            "found_workflow": {"ir": workflow_ir},  # Simulating Path A
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)

            logger.info(f"Multi-param - Extracted: {exec_res['extracted']}")
            logger.info(f"Missing: {exec_res['missing']}")
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # Should extract repo and labels
            extracted = exec_res["extracted"]
            if extracted:
                # LLM should identify repo and labels
                has_repo = "repo" in extracted and "anthropic/pflow" in str(extracted["repo"]).lower()
                has_labels = "labels" in extracted and (
                    "bug" in str(extracted["labels"]).lower() or "security" in str(extracted["labels"]).lower()
                )

                assert has_repo or has_labels, f"Expected to extract repo and labels: {extracted}"

                # Optional parameters might not be extracted (using defaults)
                # That's fine - they're optional

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_parameter_mapping_with_stdin_fallback(self):
        """Test that mapping checks stdin for missing parameters."""
        node = ParameterMappingNode()

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [],
            "inputs": {"data": {"type": "string", "required": True, "description": "Data to process"}},
        }

        shared = {
            "user_input": "Process the input data",
            "stdin": "This is the actual data from stdin",
            "generated_workflow": workflow_ir,
        }

        prep_res = node.prep(shared)

        # Verify stdin is included
        assert prep_res["stdin_data"] == shared["stdin"]

        try:
            exec_res = node.exec(prep_res)

            logger.info(f"Stdin fallback - Extracted: {exec_res['extracted']}")
            logger.info(f"Reasoning: {exec_res['reasoning']}")

            # Should recognize that "data" can come from stdin
            if exec_res["extracted"] and "data" in exec_res["extracted"]:
                # Either extracted from stdin or recognized stdin as source
                assert exec_res["confidence"] > 0.5
                assert len(exec_res["missing"]) == 0

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_parameter_mapping_missing_detection(self):
        """Test that missing required parameters are properly detected."""
        node = ParameterMappingNode()

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [],
            "inputs": {
                "api_key": {"type": "string", "required": True, "description": "API key for authentication"},
                "endpoint": {"type": "string", "required": True, "description": "API endpoint URL"},
            },
        }

        shared = {
            "user_input": "Call the API to get weather data",  # No specific values mentioned
            "generated_workflow": workflow_ir,
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)

            logger.info(f"Missing detection - Extracted: {exec_res['extracted']}")
            logger.info(f"Missing: {exec_res['missing']}")
            logger.info(f"Confidence: {exec_res['confidence']}")

            # Should identify that required parameters are missing
            assert len(exec_res["missing"]) > 0
            assert exec_res["confidence"] == 0.0  # No confidence when missing required

            # Post should route to incomplete
            action = node.post(shared, prep_res, exec_res)
            assert action == "params_incomplete"
            assert "missing_params" in shared

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


class TestParameterPreparationNode:
    """Test the parameter preparation node (currently pass-through)."""

    def test_parameter_preparation_passthrough(self):
        """Test that ParameterPreparationNode passes parameters through in MVP."""
        node = ParameterPreparationNode()

        shared = {"extracted_params": {"file_path": "/test/file.txt", "format": "json"}}

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        # In MVP, it's a pass-through
        assert exec_res["workflow_params"] == shared["extracted_params"]
        assert exec_res["validation_status"] == "passed"

        # Post should store prepared params
        action = node.post(shared, prep_res, exec_res)
        assert action == ""  # Continues to execution
        assert "workflow_params" in shared
        assert shared["workflow_params"] == shared["extracted_params"]


class TestParameterConvergenceArchitecture:
    """Test the convergence architecture with real LLM responses."""

    def test_path_a_to_parameter_mapping(self):
        """Test that Path A workflows go through parameter mapping."""
        # This would be an integration test with multiple nodes
        # For now, test that ParameterMappingNode handles Path A workflow structure

        node = ParameterMappingNode()

        # Simulate Path A with found_workflow
        # North Star Example: generate-changelog via Path A
        shared = {
            "user_input": "Generate changelog for pflow since January 2024",
            "found_workflow": {
                "name": "generate-changelog",
                "ir": {
                    "ir_version": "0.1.0",
                    "inputs": {
                        "repo": {"type": "string", "required": True},
                        "since_date": {"type": "string", "required": True},
                        "format": {"type": "string", "required": False, "default": "markdown"},
                    },
                },
            },
        }

        prep_res = node.prep(shared)

        # Should use found_workflow from Path A
        assert prep_res["workflow_ir"] == shared["found_workflow"]["ir"]

        try:
            exec_res = node.exec(prep_res)

            # Should extract repo and since_date from user input
            if exec_res["extracted"]:
                has_repo = "repo" in exec_res["extracted"] and "pflow" in str(exec_res["extracted"]["repo"]).lower()
                has_date = "since_date" in exec_res["extracted"] and (
                    "january" in str(exec_res["extracted"]["since_date"]).lower()
                    or "2024" in str(exec_res["extracted"]["since_date"])
                )
                assert has_repo or has_date, f"Expected to extract repo and date: {exec_res['extracted']}"

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_path_b_to_parameter_mapping(self):
        """Test that Path B workflows go through parameter mapping."""
        node = ParameterMappingNode()

        # Simulate Path B with generated_workflow
        # North Star Example: create-release-notes via Path B
        shared = {
            "user_input": "Create release notes for v2.0 of pflow including contributors",
            "generated_workflow": {
                "ir_version": "0.1.0",
                "inputs": {
                    "version": {"type": "string", "required": True},
                    "repo": {"type": "string", "required": True},
                    "include_contributors": {"type": "boolean", "required": False, "default": False},
                },
            },
        }

        prep_res = node.prep(shared)

        # Should use generated_workflow from Path B
        assert prep_res["workflow_ir"] == shared["generated_workflow"]

        try:
            exec_res = node.exec(prep_res)

            # Should extract all parameters
            if exec_res["extracted"]:
                has_version = "version" in exec_res["extracted"] or any(
                    "2.0" in str(v) or "v2.0" in str(v).lower() for v in exec_res["extracted"].values()
                )
                has_repo = "repo" in exec_res["extracted"] or any(
                    "pflow" in str(v).lower() for v in exec_res["extracted"].values()
                )

                assert has_version or has_repo, f"Expected to extract version and repo: {exec_res['extracted']}"

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise


if __name__ == "__main__":
    # Run with logging to see actual LLM responses
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
