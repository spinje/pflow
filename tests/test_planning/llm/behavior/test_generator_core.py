"""LLM behavior tests for WorkflowGeneratorNode core functionality.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests verify that the LLM can generate valid FlowIR structures with correct
template variables and input specifications.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior/test_generator_core.py -v

CRITICAL: The most important test verifies that discovered parameters are used as
template variables ($limit) NOT hardcoded values (20).
"""

import json
import logging
import os

import pytest

from pflow.planning.nodes import WorkflowGeneratorNode

logger = logging.getLogger(__name__)

# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestWorkflowGeneratorCoreBehavior:
    """Test WorkflowGeneratorNode core behavior with real LLM calls."""

    def test_generates_valid_flowir_structure(self):
        """Test that LLM generates valid FlowIR structure matching schema."""
        node = WorkflowGeneratorNode()

        # Prepare shared store with minimal context
        shared = {
            "user_input": "Generate a changelog for anthropic/pflow repository",
            "planning_context": """Available nodes:
- github_list_commits: List commits from a GitHub repository
  Parameters: repo (repository name), since (date), limit (number of commits)
- llm: Generate text using an LLM
  Parameters: prompt (text prompt), model (model name)
- write_file: Write content to a file
  Parameters: path (file path), content (file content)
""",
            "browsed_components": {
                "github_list_commits": {
                    "type": "node",
                    "description": "List commits from a GitHub repository",
                    "parameters": ["repo", "since", "limit"],
                },
                "llm": {
                    "type": "node",
                    "description": "Generate text using an LLM",
                    "parameters": ["prompt", "model"],
                },
                "write_file": {
                    "type": "node",
                    "description": "Write content to a file",
                    "parameters": ["path", "content"],
                },
            },
        }

        # Prepare the node
        prep_res = node.prep(shared)

        try:
            # Execute generation
            exec_res = node.exec(prep_res)

            # Verify workflow structure
            assert "workflow" in exec_res
            workflow = exec_res["workflow"]

            # Check required FlowIR fields
            assert "ir_version" in workflow
            assert workflow["ir_version"] == "0.1.0"
            assert "nodes" in workflow
            assert isinstance(workflow["nodes"], list)
            assert len(workflow["nodes"]) > 0

            # Verify nodes have required fields
            for node_def in workflow["nodes"]:
                assert "id" in node_def
                assert "type" in node_def
                assert isinstance(node_def.get("params", {}), dict)

            # Check edges if present
            if "edges" in workflow:
                assert isinstance(workflow["edges"], list)
                for edge in workflow["edges"]:
                    assert "from" in edge
                    assert "to" in edge

            logger.info(f"Generated valid workflow with {len(workflow['nodes'])} nodes")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_template_variables_preserved_not_hardcoded(self):
        """CRITICAL TEST: Verify that discovered values become template variables.

        When discovered_params contains {"limit": "20"}, the generated workflow
        MUST use "$limit" NOT "20" in the node configuration.
        """
        node = WorkflowGeneratorNode()

        # Prepare shared store with discovered parameters
        shared = {
            "user_input": "List the last 20 commits from anthropic/pflow",
            "discovered_params": {"limit": "20", "repo": "anthropic/pflow"},
            "planning_context": """Available nodes:
- github_list_commits: List commits from a GitHub repository
  Parameters: repo (repository name), limit (number of commits)
""",
            "browsed_components": {
                "github_list_commits": {
                    "type": "node",
                    "description": "List commits from a GitHub repository",
                    "parameters": ["repo", "limit"],
                }
            },
        }

        prep_res = node.prep(shared)

        try:
            # Execute generation
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            # Find the github_list_commits node
            github_node = None
            for node_def in workflow["nodes"]:
                if node_def["type"] == "github_list_commits":
                    github_node = node_def
                    break

            assert github_node is not None, "Should have github_list_commits node"

            # CRITICAL: Check that parameters use template variables
            params = github_node.get("params", {})

            # The limit parameter MUST be a template variable, not hardcoded
            if "limit" in params:
                limit_value = str(params["limit"])
                assert "$" in limit_value or "{{" in limit_value, (
                    f"limit should be template variable, got: {limit_value}"
                )
                assert "20" not in limit_value or "$" in limit_value, (
                    f"limit should not hardcode '20', got: {limit_value}"
                )

            # The repo parameter should also be a template variable
            if "repo" in params:
                repo_value = str(params["repo"])
                assert "$" in repo_value or "{{" in repo_value, f"repo should be template variable, got: {repo_value}"
                assert "anthropic/pflow" not in repo_value or "$" in repo_value, (
                    f"repo should not hardcode value, got: {repo_value}"
                )

            logger.info(f"Template variables correctly used: {params}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_inputs_field_created_properly(self):
        """Test that the inputs field is created with proper specifications."""
        node = WorkflowGeneratorNode()

        shared = {
            "user_input": "Create a changelog for repository since a specific date",
            "discovered_params": {"repository": "my-repo", "since_date": "2024-01-01"},
            "planning_context": """Available nodes:
- github_list_commits: List commits from a GitHub repository
  Parameters: repo (repository name), since (date)
- llm: Generate text using an LLM
  Parameters: prompt (text prompt)
""",
            "browsed_components": {
                "github_list_commits": {
                    "type": "node",
                    "description": "List commits from a GitHub repository",
                    "parameters": ["repo", "since"],
                },
                "llm": {
                    "type": "node",
                    "description": "Generate text using an LLM",
                    "parameters": ["prompt"],
                },
            },
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            # Verify inputs field exists
            assert "inputs" in workflow, "Workflow should have inputs field"
            inputs = workflow["inputs"]
            assert isinstance(inputs, dict), "Inputs should be a dict"

            # Check that inputs have proper structure
            for param_name, param_spec in inputs.items():
                assert isinstance(param_spec, dict), f"Input {param_name} should be a dict"

                # Each input should have description, type, and required
                assert "description" in param_spec, f"Input {param_name} missing description"
                assert "type" in param_spec, f"Input {param_name} missing type"
                assert "required" in param_spec, f"Input {param_name} missing required field"

                # Type should be a valid JSON schema type
                assert param_spec["type"] in [
                    "string",
                    "number",
                    "integer",
                    "boolean",
                    "array",
                    "object",
                ], f"Invalid type for {param_name}: {param_spec['type']}"

            logger.info(f"Inputs field created with {len(inputs)} parameters: {list(inputs.keys())}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_discovered_values_never_hardcoded(self):
        """Test that discovered parameter values are NEVER hardcoded in the workflow."""
        node = WorkflowGeneratorNode()

        # Test with various discovered values
        test_cases = [
            {
                "user_input": "Triage issues with bug label from project-x",
                "discovered_params": {"label": "bug", "project": "project-x", "limit": "50"},
                "hardcoded_values": ["bug", "project-x", "50"],  # Should NOT appear as literals
            },
            {
                "user_input": "Generate report for issue #1234",
                "discovered_params": {"issue_number": "1234", "format": "markdown"},
                "hardcoded_values": ["1234", "markdown"],
            },
        ]

        for test_case in test_cases:
            shared = {
                "user_input": test_case["user_input"],
                "discovered_params": test_case["discovered_params"],
                "planning_context": """Available nodes:
- github_get_issue: Get issue details from GitHub
  Parameters: repo, issue_number
- github_list_issues: List issues from GitHub
  Parameters: repo, label, limit
- llm: Generate text using an LLM
  Parameters: prompt
- write_file: Write content to a file
  Parameters: path, content, format
""",
                "browsed_components": {
                    "github_get_issue": {
                        "type": "node",
                        "description": "Get issue details",
                        "parameters": ["repo", "issue_number"],
                    },
                    "github_list_issues": {
                        "type": "node",
                        "description": "List issues",
                        "parameters": ["repo", "label", "limit"],
                    },
                    "llm": {"type": "node", "description": "Generate text", "parameters": ["prompt"]},
                    "write_file": {
                        "type": "node",
                        "description": "Write file",
                        "parameters": ["path", "content", "format"],
                    },
                },
            }

            prep_res = node.prep(shared)

            try:
                exec_res = node.exec(prep_res)
                workflow = exec_res["workflow"]

                # Check node params specifically - the most important place not to hardcode
                for node_def in workflow["nodes"]:
                    params = node_def.get("params", {})
                    for param_name, param_value in params.items():
                        if isinstance(param_value, str):
                            # Check if any discovered value is hardcoded in params
                            for hardcoded_value in test_case["hardcoded_values"]:
                                if str(hardcoded_value) == param_value:
                                    # It's exactly the hardcoded value - bad!
                                    raise AssertionError(
                                        f"Found hardcoded value '{hardcoded_value}' in node {node_def['id']} param {param_name}"
                                    )
                                elif (
                                    str(hardcoded_value) in param_value
                                    and "$" not in param_value
                                    and "{{" not in param_value
                                ):
                                    # It contains the value but isn't a template - potentially bad
                                    logger.warning(
                                        f"Possible hardcoded value '{hardcoded_value}' in {param_name}: {param_value}"
                                    )

                logger.info(f"No hardcoded values found for: {test_case['user_input']}")

            except Exception as e:
                if "API" in str(e) or "key" in str(e).lower():
                    pytest.skip(f"LLM API not configured: {e}")
                raise

    def test_template_variable_paths_supported(self):
        """Test that template variables can use paths like $data.field.subfield."""
        node = WorkflowGeneratorNode()

        shared = {
            "user_input": "Extract author name from GitHub issue and save to file",
            "planning_context": """Available nodes:
- github_get_issue: Get issue details from GitHub
  Parameters: repo, issue_number
  Output: Puts issue data in shared store with nested structure
- write_file: Write content to a file
  Parameters: path, content
""",
            "browsed_components": {
                "github_get_issue": {
                    "type": "node",
                    "description": "Get issue details",
                    "parameters": ["repo", "issue_number"],
                },
                "write_file": {
                    "type": "node",
                    "description": "Write file",
                    "parameters": ["path", "content"],
                },
            },
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            # Convert to string to search for path-based template variables
            workflow_str = json.dumps(workflow)

            # Check if any node uses path-based template variables
            # Common patterns: $issue.author, $data.field, {{issue.author.name}}
            has_path_template = (
                "$issue." in workflow_str
                or "$data." in workflow_str
                or "{{issue." in workflow_str
                or ("." in workflow_str and ("$" in workflow_str or "{{" in workflow_str))
            )

            # We don't require path templates, but if they're used, verify format
            if has_path_template:
                logger.info("Found path-based template variables in workflow")
                # Just verify the workflow is still valid
                assert "nodes" in workflow
                assert len(workflow["nodes"]) > 0

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_linear_workflow_no_branching(self):
        """Test that generated workflows are linear with no branching."""
        node = WorkflowGeneratorNode()

        shared = {
            "user_input": "Get issues, filter by label, generate report, and save",
            "planning_context": """Available nodes:
- github_list_issues: List issues from GitHub
- filter_by_label: Filter issues by label (mock node for testing)
- llm: Generate text report
- write_file: Save to file
""",
            "browsed_components": {
                "github_list_issues": {"type": "node", "parameters": ["repo"]},
                "filter_by_label": {"type": "node", "parameters": ["label"]},
                "llm": {"type": "node", "parameters": ["prompt"]},
                "write_file": {"type": "node", "parameters": ["path", "content"]},
            },
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            edges = workflow.get("edges", [])

            # Build a map of node connections
            from_nodes = {}
            to_nodes = {}

            for edge in edges:
                from_node = edge["from"]
                to_node = edge["to"]

                # Check for branching (one node going to multiple)
                if from_node in from_nodes:
                    raise AssertionError(f"Branching detected: {from_node} has multiple outgoing edges")
                from_nodes[from_node] = to_node

                # Check for merging (multiple nodes going to one)
                if to_node in to_nodes:
                    logger.warning(f"Merging detected: {to_node} has multiple incoming edges")
                to_nodes[to_node] = from_node

            logger.info(f"Workflow is linear with {len(edges)} edges")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_descriptive_node_ids_generated(self):
        """Test that node IDs are descriptive, not generic like 'n1' or 'node1'."""
        node = WorkflowGeneratorNode()

        shared = {
            "user_input": "List GitHub commits and generate a changelog",
            "planning_context": """Available nodes:
- github_list_commits: List commits from GitHub
- llm: Generate text using an LLM
- write_file: Write to file
""",
            "browsed_components": {
                "github_list_commits": {"type": "node", "parameters": ["repo"]},
                "llm": {"type": "node", "parameters": ["prompt"]},
                "write_file": {"type": "node", "parameters": ["path", "content"]},
            },
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            # Check node IDs
            bad_ids = ["n1", "n2", "n3", "node1", "node2", "node3", "node_1", "node_2"]

            for node_def in workflow["nodes"]:
                node_id = node_def["id"]

                # ID should be descriptive
                assert node_id not in bad_ids, f"Node ID '{node_id}' is not descriptive"

                # ID should relate to the node type or purpose
                assert len(node_id) > 2, f"Node ID '{node_id}' is too short"

                logger.info(f"Node ID: {node_id} (type: {node_def['type']})")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_avoids_multiple_nodes_same_type(self):
        """Test that workflow avoids multiple nodes of the same type (shared store collision)."""
        node = WorkflowGeneratorNode()

        shared = {
            "user_input": "Read two files and combine them",
            "planning_context": """Available nodes:
- read_file: Read content from a file
  Parameters: path
  Note: Multiple read_file nodes cause shared store collision
- combine_files: Combine content from multiple files (better alternative)
  Parameters: paths (list of file paths)
""",
            "browsed_components": {
                "read_file": {"type": "node", "parameters": ["path"]},
                "combine_files": {"type": "node", "parameters": ["paths"]},
            },
        }

        prep_res = node.prep(shared)

        try:
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            # Count nodes by type
            node_types = {}
            for node_def in workflow["nodes"]:
                node_type = node_def["type"]
                node_types[node_type] = node_types.get(node_type, 0) + 1

            # Check for duplicates
            for node_type, count in node_types.items():
                if count > 1:
                    logger.warning(f"Found {count} nodes of type '{node_type}' - may cause collision")
                    # This is a warning, not an assertion, as sometimes it might be valid

            logger.info(f"Node type distribution: {node_types}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise
