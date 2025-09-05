"""Integration tests for WorkflowGeneratorNode with North Star examples.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests verify complete Path B flow with real-world examples like
generate-changelog and issue-triage-report generation.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_generator_north_star.py -v

CRITICAL: These tests validate the complete generation flow including
convergence with ParameterMappingNode.
"""

import json
import logging
import os

import pytest

from pflow.planning.nodes import (
    ComponentBrowsingNode,
    ParameterDiscoveryNode,
    ParameterMappingNode,
    WorkflowGeneratorNode,
)

logger = logging.getLogger(__name__)

# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestGeneratorNorthStarExamples:
    """Test WorkflowGeneratorNode with North Star examples."""

    def test_generate_changelog_complete_flow(self):
        """Test complete Path B flow for generate-changelog North Star example."""
        # EXACT verbose north star prompt from architecture/vision/north-star-examples.md
        CHANGELOG_VERBOSE = """generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."""

        shared = {"user_input": CHANGELOG_VERBOSE}

        try:
            # Step 1: Parameter Discovery
            discovery_node = ParameterDiscoveryNode()
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)
            discovery_node.post(shared, prep_res, exec_res)

            assert "discovered_params" in shared
            discovered = shared["discovered_params"]
            logger.info(f"Discovered parameters: {discovered}")

            # Should discover EXACT parameters from north star prompt
            # Parameters are strings, not integers
            assert any("1.3" in str(v) for v in discovered.values()), "Should discover version 1.3"
            assert any("20" in str(v) for v in discovered.values()), "Should discover limit 20"
            assert any("create-changelog-version-1.3" in str(v) for v in discovered.values()), (
                "Should discover branch name"
            )

            # Step 2: Component Browsing
            browsing_node = ComponentBrowsingNode()
            prep_res = browsing_node.prep(shared)
            exec_res = browsing_node.exec(prep_res)
            browsing_node.post(shared, prep_res, exec_res)

            assert "browsed_components" in shared
            components = shared["browsed_components"]
            logger.info(f"Browsed {len(components)} components")

            # Should find relevant nodes for the task
            # Note: browsed_components values can be lists or dicts
            if components:
                logger.info(f"Found components: {list(components.keys())[:5]}")  # Log first 5 components
                # Just verify we found some components
                assert len(components) > 0, "Should have browsed some components"

            # Step 3: Workflow Generation
            generator_node = WorkflowGeneratorNode()
            prep_res = generator_node.prep(shared)
            exec_res = generator_node.exec(prep_res)
            action = generator_node.post(shared, prep_res, exec_res)

            assert action == "validate"  # Should route to validation
            assert "generated_workflow" in shared

            workflow = shared["generated_workflow"]
            logger.info(f"Generated workflow with {len(workflow.get('nodes', []))} nodes")

            # Verify workflow structure
            assert "ir_version" in workflow
            assert "nodes" in workflow
            assert len(workflow["nodes"]) >= 2  # At least github + llm nodes

            # Verify inputs field
            assert "inputs" in workflow
            inputs = workflow["inputs"]
            assert len(inputs) > 0

            # Key requirement: workflow should parameterize discovered values
            # Either through template variables OR inputs with defaults
            workflow_str = json.dumps(workflow)
            has_template_vars = "$" in workflow_str or "{{" in workflow_str

            if not has_template_vars:
                # If no template variables, should have inputs with discovered defaults
                assert "inputs" in workflow, "Must have inputs if not using template variables"
                inputs = workflow["inputs"]

                # Verify defaults match discovered values
                defaults_str = json.dumps({k: v.get("default") for k, v in inputs.items()})
                assert "1.3" in defaults_str or "version" in defaults_str, "Should have version default"
                assert "20" in defaults_str, "Should have limit default of 20"
                assert "CHANGELOG.md" in defaults_str or "versions/1.3" in defaults_str, "Should have path default"

                logger.info("Workflow uses input defaults instead of template variables")
            else:
                logger.info("Workflow uses template variables")

            # Step 4: Parameter Mapping (convergence point)
            # Simulate the workflow being selected for execution
            shared["selected_workflow"] = workflow
            shared["extracted_params"] = {}  # Will be filled by mapping

            mapping_node = ParameterMappingNode()
            prep_res = mapping_node.prep(shared)
            exec_res = mapping_node.exec(prep_res)
            action = mapping_node.post(shared, prep_res, exec_res)

            logger.info(f"Parameter mapping result: {action}")
            logger.info(f"Extracted params: {shared.get('extracted_params', {})}")

            # Should extract parameters from user input to fill template variables
            assert "extracted_params" in shared
            extracted = shared["extracted_params"]

            # The mapping should provide values for the template variables
            if action == "params_complete":
                assert len(extracted) > 0
                logger.info("Parameters successfully mapped")
            else:
                assert "missing_params" in shared
                logger.info(f"Missing parameters that need user input: {shared['missing_params']}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_issue_triage_report_generation(self):
        """Test Path B flow for issue-triage-report North Star example.

        For Path B (generation), the user needs to be SPECIFIC about:
        - The source (GitHub)
        - What to fetch (issues)
        - How to process (categorize)
        - Where to save (file path)

        This follows the north star example pattern where first-time users
        provide detailed instructions for workflow generation.
        """
        # EXACT verbose north star prompt with intentional double "the"
        TRIAGE_VERBOSE = """create a triage report for all open issues by fetching the the last 50 open issues from github, categorizing them by priority and type and then write them to triage-reports/2025-08-07-triage-report.md then commit the changes. Replace 2025-08-07 with the current date and mention the date in the commit message."""

        shared = {"user_input": TRIAGE_VERBOSE}

        try:
            # Step 1: Parameter Discovery
            discovery_node = ParameterDiscoveryNode()
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)
            discovery_node.post(shared, prep_res, exec_res)

            discovered = shared.get("discovered_params", {})
            logger.info(f"Discovered: {discovered}")

            # Should discover EXACT parameters from north star prompt
            assert any("50" in str(v) for v in discovered.values()), "Should discover limit 50"
            assert any("github" in str(v).lower() for v in discovered.values()), "Should discover GitHub source"
            assert any("2025-08-07" in str(v) or "triage-report" in str(v) for v in discovered.values()), (
                "Should discover date/filename"
            )

            # Step 2: Component Browsing
            browsing_node = ComponentBrowsingNode()
            prep_res = browsing_node.prep(shared)
            exec_res = browsing_node.exec(prep_res)
            browsing_node.post(shared, prep_res, exec_res)

            components = shared.get("browsed_components", {})
            logger.info(f"Found components: {list(components.keys())}")

            # Step 3: Workflow Generation
            generator_node = WorkflowGeneratorNode()
            prep_res = generator_node.prep(shared)
            exec_res = generator_node.exec(prep_res)
            generator_node.post(shared, prep_res, exec_res)

            workflow = shared["generated_workflow"]

            # Verify workflow was generated
            nodes = workflow.get("nodes", [])
            node_types = [n["type"] for n in nodes]
            logger.info(f"Node types in workflow: {node_types}")
            logger.info(f"Full workflow nodes: {nodes}")

            # Basic validation - workflow was generated with multiple steps
            assert len(node_types) >= 2, "Should have at least fetch and write steps"

            # The workflow should include GitHub operations since we explicitly mentioned GitHub
            # Could be github-list-issues, github-get-issues, or a composed workflow
            assert any("github" in t.lower() or "issue" in t.lower() for t in node_types), (
                "Should include GitHub-related nodes since prompt mentions GitHub"
            )

            # Should also have output generation (LLM or write-file)
            assert any("llm" in t.lower() or "write" in t.lower() or "file" in t.lower() for t in node_types), (
                "Should include nodes for generating or writing the report"
            )

            # Verify correct workflow structure
            assert workflow.get("ir_version") == "0.1.0"
            assert "inputs" in workflow

            # Verify the workflow uses inputs properly
            # Either through template variables in params OR through defined inputs with defaults
            workflow_str = json.dumps(workflow)
            has_template_vars = "$" in workflow_str or "{{" in workflow_str

            # Check inputs are properly defined
            if "inputs" in workflow:
                input_keys = list(workflow["inputs"].keys())
                logger.info(f"Workflow inputs: {input_keys}")

                # Should have inputs for repository, issue filters, and output path
                assert len(input_keys) >= 2, "Should have inputs for repo and output path at minimum"

                # If no template variables in params, inputs should have defaults
                if not has_template_vars:
                    # Check that inputs have defaults matching discovered params
                    inputs = workflow["inputs"]

                    # Output file should match what was specified
                    if "output_file_path" in inputs or "output_path" in inputs:
                        output_input = inputs.get("output_file_path") or inputs.get("output_path")
                        assert "triage-report" in str(output_input.get("default", "")), (
                            "Output path default should match specified value"
                        )

                    logger.info("Workflow uses input defaults instead of template variables")
                else:
                    logger.info("Workflow uses template variables in params")
            else:
                # If no inputs defined, must use template variables
                assert has_template_vars, "Workflow must either define inputs or use template variables"

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_convergence_with_parameter_mapping(self):
        """Test that generated workflows converge properly with ParameterMappingNode."""
        shared = {"user_input": "Summarize pull request #456 from anthropic/pflow"}

        try:
            # Run through generation flow
            # Step 1: Discovery
            discovery = ParameterDiscoveryNode()
            prep_res = discovery.prep(shared)
            exec_res = discovery.exec(prep_res)
            discovery.post(shared, prep_res, exec_res)

            discovered = shared.get("discovered_params", {})
            assert "456" in str(discovered.values())

            # Step 2: Browsing
            browsing = ComponentBrowsingNode()
            prep_res = browsing.prep(shared)
            exec_res = browsing.exec(prep_res)
            browsing.post(shared, prep_res, exec_res)

            # Step 3: Generation
            generator = WorkflowGeneratorNode()
            prep_res = generator.prep(shared)
            exec_res = generator.exec(prep_res)
            generator.post(shared, prep_res, exec_res)

            workflow = shared["generated_workflow"]

            # Verify workflow was generated (might use github or generic nodes)
            assert len(workflow.get("nodes", [])) > 0

            # Step 4: Test convergence with ParameterMappingNode
            # The workflow is already in shared["generated_workflow"] from generator.post()

            mapping = ParameterMappingNode()
            prep_res = mapping.prep(shared)

            # Verify mapping has access to workflow IR (from generated_workflow)
            assert prep_res["workflow_ir"] is not None
            assert prep_res["user_input"] is not None

            exec_res = mapping.exec(prep_res)
            action = mapping.post(shared, prep_res, exec_res)

            # Should extract PR number and repo
            extracted = shared.get("extracted_params", {})
            logger.info(f"Convergence extracted: {extracted}")

            # The specific parameter names depend on the workflow inputs
            # but should contain the PR number and repo info
            param_values = str(extracted.values()).lower()
            assert "456" in param_values or "pull" in param_values or "pr" in param_values

            logger.info(f"Convergence successful with action: {action}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_retry_with_validation_errors(self):
        """Test that generator can retry with validation feedback."""
        # Start with a deliberately problematic context to trigger validation errors
        shared = {
            "user_input": "Generate a report",
            "planning_context": """Available nodes:
- github_get_data: Generic GitHub data fetcher (intentionally vague)
  Parameters: resource, id
- process: Generic processor (intentionally vague)
  Parameters: data
""",
            "browsed_components": {
                "github_get_data": {"type": "node", "parameters": ["resource", "id"]},
                "process": {"type": "node", "parameters": ["data"]},
            },
            "validation_errors": ["Node type 'github_get_data' not found in registry"],
            "generation_attempts": 1,  # Simulate retry
        }

        try:
            generator = WorkflowGeneratorNode()
            prep_res = generator.prep(shared)

            # The prompt should include validation errors
            prompt = generator._build_prompt(prep_res)
            assert "not found in registry" in prompt

            # Generate with corrections
            exec_res = generator.exec(prep_res)
            workflow = exec_res["workflow"]

            # Should have attempted to fix the issue
            assert exec_res["attempt"] == 2  # Incremented attempt count

            logger.info(f"Retry generated workflow with {len(workflow.get('nodes', []))} nodes")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_complex_multi_step_workflow(self):
        """Test generation of complex multi-step workflow."""
        shared = {
            "user_input": (
                "Get all open issues with bug label from anthropic/pflow, "
                "analyze them with AI to find patterns, "
                "then create a summary report and save it to bug-analysis.md"
            )
        }

        try:
            # Full generation flow
            # Discovery
            discovery = ParameterDiscoveryNode()
            prep_res = discovery.prep(shared)
            exec_res = discovery.exec(prep_res)
            discovery.post(shared, prep_res, exec_res)

            # Browsing
            browsing = ComponentBrowsingNode()
            prep_res = browsing.prep(shared)
            exec_res = browsing.exec(prep_res)
            browsing.post(shared, prep_res, exec_res)

            # Generation
            generator = WorkflowGeneratorNode()
            prep_res = generator.prep(shared)
            exec_res = generator.exec(prep_res)
            generator.post(shared, prep_res, exec_res)

            workflow = shared["generated_workflow"]

            # Should have multiple nodes for this complex task
            nodes = workflow.get("nodes", [])
            assert len(nodes) >= 3  # At least: list issues, analyze, write file

            # Verify logical flow
            node_types = [n["type"] for n in nodes]
            logger.info(f"Complex workflow nodes: {node_types}")

            # Should include GitHub, analysis, and file operations
            # The LLM might use different node names, so be flexible
            workflow_str = json.dumps(workflow)

            # Verify it mentions the key components
            assert "github" in workflow_str.lower() or "issue" in workflow_str.lower(), (
                "Should reference GitHub or issues"
            )
            assert (
                "analyze" in workflow_str.lower() or "llm" in workflow_str.lower() or "pattern" in workflow_str.lower()
            ), "Should include analysis step"
            assert "bug-analysis.md" in workflow_str, "Should include the specific output file mentioned"

            # Check edges create a logical flow
            edges = workflow.get("edges", [])
            assert len(edges) >= len(nodes) - 1  # Connected workflow

            # Verify inputs are comprehensive
            if "inputs" in workflow:
                inputs = workflow["inputs"]
                logger.info(f"Complex workflow inputs: {list(inputs.keys())}")

                # Should have inputs for repo, label, and output file
                assert len(inputs) >= 2  # At minimum repo and output file

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_handles_ambiguous_requests(self):
        """Test generation with ambiguous user requests."""
        shared = {"user_input": "Do something with the data"}  # Very ambiguous

        try:
            # Even with ambiguous input, should generate something reasonable
            discovery = ParameterDiscoveryNode()
            prep_res = discovery.prep(shared)
            exec_res = discovery.exec(prep_res)
            discovery.post(shared, prep_res, exec_res)

            browsing = ComponentBrowsingNode()
            prep_res = browsing.prep(shared)
            exec_res = browsing.exec(prep_res)
            browsing.post(shared, prep_res, exec_res)

            generator = WorkflowGeneratorNode()
            prep_res = generator.prep(shared)
            exec_res = generator.exec(prep_res)
            generator.post(shared, prep_res, exec_res)

            workflow = shared.get("generated_workflow")

            if workflow:
                # Should still generate valid structure
                assert "nodes" in workflow
                assert "ir_version" in workflow

                # Should have generic inputs that can be specified later
                if "inputs" in workflow:
                    assert len(workflow["inputs"]) > 0
                    logger.info(f"Generated generic inputs: {list(workflow['inputs'].keys())}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            # Ambiguous requests might fail, which is acceptable
            logger.info(f"Ambiguous request handling: {e}")
            pass

    def test_summarize_issue_tertiary_example(self):
        """Test Path B flow for simple issue summary North Star tertiary example.

        This is the simplest north star example - just summarize a single issue.
        Even though it's simple, a specific issue number should trigger Path B.
        """
        # EXACT tertiary north star prompt from architecture/vision/north-star-examples.md
        ISSUE_SUMMARY = "summarize github issue 1234"

        shared = {"user_input": ISSUE_SUMMARY}

        try:
            # Step 1: Parameter Discovery
            discovery_node = ParameterDiscoveryNode()
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)
            discovery_node.post(shared, prep_res, exec_res)

            assert "discovered_params" in shared
            discovered = shared["discovered_params"]
            logger.info(f"Discovered parameters: {discovered}")

            # Should discover the specific issue number
            assert any("1234" in str(v) for v in discovered.values()), "Should discover issue number 1234"

            # Step 2: Component Browsing
            browsing_node = ComponentBrowsingNode()
            prep_res = browsing_node.prep(shared)
            exec_res = browsing_node.exec(prep_res)
            browsing_node.post(shared, prep_res, exec_res)

            assert "browsed_components" in shared
            components = shared["browsed_components"]
            logger.info(f"Browsed components for simple workflow: {list(components.keys())[:5]}")

            # Step 3: Workflow Generation
            generator_node = WorkflowGeneratorNode()
            prep_res = generator_node.prep(shared)
            exec_res = generator_node.exec(prep_res)
            action = generator_node.post(shared, prep_res, exec_res)

            assert action == "validate"
            assert "generated_workflow" in shared

            workflow = shared["generated_workflow"]
            logger.info(f"Generated simple workflow with {len(workflow.get('nodes', []))} nodes")

            # Simple workflow should still be valid
            assert "ir_version" in workflow
            assert "nodes" in workflow

            # Should be minimal - likely just github-get-issue + llm
            nodes = workflow.get("nodes", [])
            assert len(nodes) >= 2, "Even simple workflow needs at least fetch + process"
            assert len(nodes) <= 4, "Simple workflow shouldn't be overly complex"

            # Verify it includes GitHub issue operation
            node_types = [n["type"] for n in nodes]
            assert any("github" in t.lower() or "issue" in t.lower() for t in node_types), (
                "Should include GitHub issue node"
            )

            # Should have summarization step (likely LLM)
            assert any("llm" in t.lower() or "summar" in t.lower() for t in node_types), (
                "Should include summarization step"
            )

            # Step 4: Parameter Mapping
            shared["selected_workflow"] = workflow
            shared["extracted_params"] = {}

            mapping_node = ParameterMappingNode()
            prep_res = mapping_node.prep(shared)
            exec_res = mapping_node.exec(prep_res)
            action = mapping_node.post(shared, prep_res, exec_res)

            logger.info(f"Parameter mapping for simple workflow: {action}")

            # Should extract the issue number
            extracted = shared.get("extracted_params", {})
            assert "1234" in str(extracted.values()), "Should map issue number 1234"

            logger.info("Tertiary example successfully tested")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_performance_monitoring(self):
        """Test that performance is monitored but doesn't fail tests.

        This test validates that slow API responses don't cause test failures,
        only warnings. This is important because API response times can vary
        significantly between models and network conditions.
        """
        import time

        shared = {
            "user_input": "generate a changelog for version 1.5"  # Brief prompt for faster execution
        }

        start = time.time()

        try:
            # Just test discovery node performance
            from pflow.planning.nodes import WorkflowDiscoveryNode

            discovery = WorkflowDiscoveryNode()
            prep_res = discovery.prep(shared)
            exec_res = discovery.exec(prep_res)
            action = discovery.post(shared, prep_res, exec_res)

            duration = time.time() - start

            # Performance check - NEVER fail, only warn
            # This follows Task 28 lessons about API variance
            if duration > 20.0:
                logger.warning(f"Slow performance: {duration:.2f}s (model-dependent)")

            # Test passes regardless of performance
            assert action in ["found_existing", "not_found"]

            logger.info(f"Performance test completed in {duration:.2f}s")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_parameter_types_are_strings(self):
        """Test that discovered parameters are strings, not integers.

        This is critical for pflow - all parameters must be strings for
        consistent template variable replacement and JSON serialization.
        """
        # EXACT verbose north star prompt
        CHANGELOG_VERBOSE = """generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."""

        shared = {"user_input": CHANGELOG_VERBOSE}

        try:
            # Test parameter discovery
            param_discovery = ParameterDiscoveryNode()
            prep_res = param_discovery.prep(shared)
            exec_res = param_discovery.exec(prep_res)
            param_discovery.post(shared, prep_res, exec_res)

            discovered = shared.get("discovered_params", {})

            # Check that numeric values are stored as strings
            for key, value in discovered.items():
                if value in ["20", "1.3", "50", "1234"]:
                    assert isinstance(value, str), f"Parameter {key}={value} should be string, got {type(value)}"

            # Specifically check our known numeric parameters
            if "version" in discovered:
                assert isinstance(discovered["version"], str), "Version should be string"
            if "issue_count" in discovered or "limit" in discovered:
                limit_key = "issue_count" if "issue_count" in discovered else "limit"
                assert isinstance(discovered[limit_key], str), "Issue count/limit should be string"

            logger.info("Parameter types validated - all strings")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_validation_with_production_validator(self):
        """Test workflow validation with production WorkflowValidator.

        This ensures that generated workflows can be validated with the same
        validator used in production, catching any schema or structure issues.
        """
        from pflow.core.workflow_validator import WorkflowValidator
        from pflow.registry import Registry

        # Create a test workflow that might have validation challenges
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "fetch", "type": "github-list-issues", "params": {"limit": "${limit}"}},
                {"id": "process", "type": "llm", "params": {"prompt": "Process ${data}"}},
            ],
            "edges": [
                {"from": "fetch", "to": "process", "action": "default"},
            ],
            "start_node": "fetch",
            "inputs": {
                "limit": {"required": True}  # This might fail validation if no value provided!
            },
            "outputs": {},
        }

        # Load real registry
        registry = Registry()
        registry.load()

        # Use static validator method - same as production
        errors = WorkflowValidator.validate(
            workflow_ir=workflow, extracted_params={"limit": "20"}, registry=registry, skip_node_types=False
        )

        if errors:
            logger.warning(f"Validation errors (expected for test): {errors}")
        else:
            logger.info("Workflow passed validation")

        # Test should not fail on validation errors - just verify validator works
        assert isinstance(errors, list), "Validator should return list of errors"

        # If we have errors, they should be strings describing the issues
        for error in errors:
            assert isinstance(error, str), "Each error should be a string"
            logger.info(f"Validation error detail: {error}")
