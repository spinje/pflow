"""LLM prompt effectiveness tests for WorkflowGeneratorNode.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests verify that the prompts effectively guide the LLM to generate
workflows with correct template variables and constraints.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_generator_prompts.py -v
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


class TestGeneratorPromptEffectiveness:
    """Test the effectiveness of WorkflowGeneratorNode prompts."""

    def test_prompt_enforces_template_variables(self):
        """Test that prompt effectively guides LLM to use template variables."""
        node = WorkflowGeneratorNode()

        # Test with explicit discovered parameters
        shared = {
            "user_input": "Create changelog for repo since date with limit",
            "discovered_params": {
                "repository": "anthropic/pflow",
                "since_date": "2024-01-01",
                "max_commits": "100",
            },
            "planning_context": """Available nodes:
- github_list_commits: List commits from a GitHub repository
  Parameters: repo (string), since (string), limit (integer)
- llm: Generate text using an LLM
  Parameters: prompt (string)
- write_file: Write content to a file
  Parameters: path (string), content (string)
""",
            "browsed_components": {
                "github_list_commits": {
                    "type": "node",
                    "description": "List commits",
                    "parameters": ["repo", "since", "limit"],
                }
            },
        }

        prep_res = node.prep(shared)

        try:
            # Build the prompt to inspect it
            prompt = node._build_prompt(prep_res)

            # Verify prompt contains template variable instructions
            assert "template variable" in prompt.lower()
            assert "$" in prompt or "{{" in prompt  # Mentions template syntax
            assert "NEVER hardcode" in prompt or "hardcode" in prompt.lower()

            # Execute and verify result
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            # Check that nodes use template variables
            workflow_str = json.dumps(workflow)

            # Should not contain hardcoded discovered values
            assert '"anthropic/pflow"' not in workflow_str or "$" in workflow_str
            assert '"2024-01-01"' not in workflow_str or "$" in workflow_str
            assert '"100"' not in workflow_str or "$" in workflow_str

            logger.info("Prompt successfully enforced template variable usage")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_prompt_enforces_linear_workflow(self):
        """Test that prompt effectively prevents branching workflows."""
        node = WorkflowGeneratorNode()

        shared = {
            "user_input": "If file exists, read it; otherwise create it",  # Conditional request
            "planning_context": """Available nodes:
- check_file_exists: Check if file exists
- read_file: Read file content
- create_file: Create new file
- write_file: Write to file
""",
            "browsed_components": {
                "check_file_exists": {"type": "node", "parameters": ["path"]},
                "read_file": {"type": "node", "parameters": ["path"]},
                "create_file": {"type": "node", "parameters": ["path"]},
                "write_file": {"type": "node", "parameters": ["path", "content"]},
            },
        }

        prep_res = node.prep(shared)

        try:
            # Check prompt mentions linear constraint
            prompt = node._build_prompt(prep_res)
            assert "LINEAR" in prompt or "linear" in prompt
            assert "no branching" in prompt.lower() or "branching" in prompt.lower()

            # Execute and verify linear result
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            # Count edge connections per node
            edges = workflow.get("edges", [])
            outgoing_edges = {}

            for edge in edges:
                from_node = edge["from"]
                if from_node in outgoing_edges:
                    outgoing_edges[from_node] += 1
                else:
                    outgoing_edges[from_node] = 1

            # No node should have more than one outgoing edge (no branching)
            for node_id, count in outgoing_edges.items():
                assert count <= 1, f"Node {node_id} has {count} outgoing edges (branching)"

            logger.info("Prompt successfully enforced linear workflow")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_prompt_guides_parameter_renaming(self):
        """Test that prompt guides LLM to rename parameters for clarity."""
        node = WorkflowGeneratorNode()

        shared = {
            "user_input": "Read from file.txt and process it",
            "discovered_params": {
                "filename": "file.txt",  # Should be renamed to something clearer
                "f": "output.txt",  # Unclear parameter name
            },
            "planning_context": """Available nodes:
- read_file: Read content from a file
  Parameters: path (file path to read)
- write_file: Write content to a file
  Parameters: path (file path to write), content (content to write)
""",
            "browsed_components": {
                "read_file": {"type": "node", "parameters": ["path"]},
                "write_file": {"type": "node", "parameters": ["path", "content"]},
            },
        }

        prep_res = node.prep(shared)

        try:
            # Check prompt mentions parameter renaming
            prompt = node._build_prompt(prep_res)
            assert "rename" in prompt.lower() or "clarity" in prompt.lower()

            # Execute
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            # Check inputs field for renamed parameters
            if "inputs" in workflow:
                inputs = workflow["inputs"]

                # Should have clear parameter names
                for param_name in inputs:
                    # Single letter parameters should be renamed
                    assert len(param_name) > 1, f"Parameter '{param_name}' should be renamed for clarity"

                    # Generic names should be more specific
                    if param_name in ["filename", "f", "p", "val"]:
                        logger.warning(f"Parameter '{param_name}' could be more descriptive")

                logger.info(f"Parameters renamed for clarity: {list(inputs.keys())}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_prompt_includes_validation_feedback(self):
        """Test that prompt includes validation errors for retry attempts."""
        node = WorkflowGeneratorNode()

        # Simulate a retry with validation errors
        shared = {
            "user_input": "Generate changelog",
            "planning_context": """Available nodes:
- github_list_commits: List commits
  Parameters: repo, since
""",
            "browsed_components": {"github_list_commits": {"type": "node", "parameters": ["repo", "since"]}},
            "validation_errors": [
                "Missing required parameter 'repo' in node 'list_commits'",
                "Template variable ${repository} not defined in inputs",
                "Invalid node type 'github_commits' - did you mean 'github_list_commits'?",
            ],
            "generation_attempts": 1,  # This is a retry
        }

        prep_res = node.prep(shared)

        try:
            # Build prompt and check for error inclusion
            prompt = node._build_prompt(prep_res)

            # Should include validation errors
            assert "Missing required parameter" in prompt
            assert "Template variable" in prompt
            assert "Invalid node type" in prompt

            # Should mention it's a fix/retry
            assert "Fix" in prompt or "fix" in prompt or "previous attempt" in prompt

            logger.info("Prompt includes validation feedback for retry")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_prompt_emphasizes_inputs_field(self):
        """Test that prompt emphasizes the importance of the inputs field."""
        node = WorkflowGeneratorNode()

        shared = {
            "user_input": "Process data with custom parameters",
            "discovered_params": {"input_file": "data.csv", "output_format": "json"},
            "planning_context": """Available nodes:
- read_file: Read file
  Parameters: path
- transform_data: Transform data
  Parameters: format
- write_file: Write file
  Parameters: path, content
""",
            "browsed_components": {
                "read_file": {"type": "node", "parameters": ["path"]},
                "transform_data": {"type": "node", "parameters": ["format"]},
                "write_file": {"type": "node", "parameters": ["path", "content"]},
            },
        }

        prep_res = node.prep(shared)

        try:
            # Check prompt mentions inputs field requirements
            prompt = node._build_prompt(prep_res)

            assert "inputs" in prompt.lower()
            assert "field" in prompt.lower()
            # Should mention that each template variable needs a corresponding input
            assert "corresponding" in prompt.lower() or "must have" in prompt.lower()

            # Execute and verify inputs field
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            assert "inputs" in workflow, "Workflow missing inputs field"
            inputs = workflow["inputs"]

            # Collect all template variables used in nodes
            template_vars = set()
            for node_def in workflow["nodes"]:
                params = node_def.get("params", {})
                for param_value in params.values():
                    if isinstance(param_value, str):
                        # Extract template variable names
                        if "$" in param_value:
                            # Simple ${var} syntax
                            import re

                            matches = re.findall(r"\$(\w+)", param_value)
                            template_vars.update(matches)
                        elif "{{" in param_value:
                            # Jinja2 {{var}} syntax
                            import re

                            matches = re.findall(r"\{\{(\w+)\}\}", param_value)
                            template_vars.update(matches)

            # Verify that template variables have corresponding inputs
            # (May not be exact match due to renaming, but should be similar count)
            if template_vars:
                assert len(inputs) > 0, f"Template variables {template_vars} used but no inputs defined"
                logger.info(f"Template vars: {template_vars}, Inputs: {list(inputs.keys())}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_prompt_handles_missing_context_gracefully(self):
        """Test that missing planning context is handled with clear error."""
        node = WorkflowGeneratorNode()

        shared = {
            "user_input": "Generate a report",
            "planning_context": "",  # Empty context
        }

        prep_res = node.prep(shared)

        try:
            # Should raise ValueError for empty context
            with pytest.raises(ValueError) as exc_info:
                node.exec(prep_res)

            assert "context" in str(exc_info.value).lower()
            logger.info(f"Empty context handled correctly: {exc_info.value}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            # This test expects a ValueError, so re-raise others
            if not isinstance(e, ValueError):
                raise

    def test_prompt_universal_defaults_not_specific(self):
        """Test that prompt guides toward universal defaults, not request-specific ones."""
        node = WorkflowGeneratorNode()

        shared = {
            "user_input": "List the last 20 commits",  # Specific number
            "discovered_params": {"limit": "20"},  # Specific value
            "planning_context": """Available nodes:
- github_list_commits: List commits
  Parameters: repo, limit (number of commits to fetch)
""",
            "browsed_components": {"github_list_commits": {"type": "node", "parameters": ["repo", "limit"]}},
        }

        prep_res = node.prep(shared)

        try:
            # Check prompt mentions universal defaults
            prompt = node._build_prompt(prep_res)
            assert "universal defaults" in prompt.lower() or "100" in prompt  # Example universal default

            # Execute
            exec_res = node.exec(prep_res)
            workflow = exec_res["workflow"]

            # Check inputs for defaults
            if "inputs" in workflow and "limit" in workflow["inputs"]:
                limit_spec = workflow["inputs"]["limit"]
                if "default" in limit_spec:
                    default_value = limit_spec["default"]
                    # Default should be universal (like 100), not request-specific (20)
                    assert default_value != 20, f"Default should be universal, not request-specific: {default_value}"
                    assert default_value != "20", f"Default should be universal, not request-specific: {default_value}"
                    logger.info(f"Universal default used: {default_value}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise
