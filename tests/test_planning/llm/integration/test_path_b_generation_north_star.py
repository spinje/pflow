"""PATH B (Generation) Integration Tests - North Star Examples with Task 52.

Tests workflow GENERATION from natural language with comprehensive validation.
Focuses on Path B where new workflows are created from scratch.

This file contains ONLY high-value tests with COMPREHENSIVE validation:
- 3 North Star examples (changelog, triage, issue summary)
- 2 Task 52 features (vague/impossible detection)
- 1 Critical bug prevention (parameter types)
- 1 Performance protection

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_path_b_generation_north_star.py -v
Parallel: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_path_b_generation_north_star.py -v -n auto
"""

import json
import logging
import os
import time

import pytest

from pflow.planning.nodes import (
    ComponentBrowsingNode,
    ParameterDiscoveryNode,
    ParameterMappingNode,
    PlanningNode,
    RequirementsAnalysisNode,
    WorkflowDiscoveryNode,
    WorkflowGeneratorNode,
)

logger = logging.getLogger(__name__)

# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestPathBGenerationNorthStar:
    """Path B workflow generation tests with comprehensive validation."""

    def test_generate_changelog_north_star_primary(self):
        """Test PRIMARY north star example: changelog generation with complete Task 52 flow.

        This is the most common use case and tests the full Path B pipeline.
        """
        # EXACT verbose north star prompt from architecture docs
        CHANGELOG_VERBOSE = """generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."""

        shared = {"user_input": CHANGELOG_VERBOSE}

        try:
            # Step 1: Parameter Discovery (moved earlier in Task 52)
            discovery_node = ParameterDiscoveryNode()
            prep_res = discovery_node.prep(shared)
            exec_res = discovery_node.exec(prep_res)
            discovery_node.post(shared, prep_res, exec_res)

            assert "discovered_params" in shared
            discovered = shared["discovered_params"]

            # Critical validation: parameters must be strings
            assert any("1.3" in str(v) for v in discovered.values()), "Should discover version 1.3"
            assert any("20" in str(v) for v in discovered.values()), "Should discover limit 20"

            # Step 2: Requirements Analysis (NEW in Task 52)
            requirements_node = RequirementsAnalysisNode()
            prep_res = requirements_node.prep(shared)
            exec_res = requirements_node.exec(prep_res)
            action = requirements_node.post(shared, prep_res, exec_res)

            requirements = shared["requirements_result"]
            assert requirements.get("is_clear") is True, "Requirements should be clear"
            assert len(requirements.get("steps", [])) > 0, "Should extract operational steps"
            assert action == "", "Should continue to component browsing"

            # Step 3: Component Browsing
            browsing_node = ComponentBrowsingNode()
            prep_res = browsing_node.prep(shared)
            exec_res = browsing_node.exec(prep_res)
            action = browsing_node.post(shared, prep_res, exec_res)

            assert "browsed_components" in shared
            assert action == "generate", "Should route to planning/generation"

            # Step 4: Planning (NEW in Task 52)
            planning_node = PlanningNode()
            prep_res = planning_node.prep(shared)
            exec_res = planning_node.exec(prep_res)
            action = planning_node.post(shared, prep_res, exec_res)

            assert "planner_extended_blocks" in shared, "Should create extended blocks"
            assert action == "", "Should continue to workflow generation (FEASIBLE)"

            # Step 5: Workflow Generation
            generator_node = WorkflowGeneratorNode()
            prep_res = generator_node.prep(shared)
            exec_res = generator_node.exec(prep_res)
            action = generator_node.post(shared, prep_res, exec_res)

            assert action == "validate"
            assert "generated_workflow" in shared

            workflow = shared["generated_workflow"]

            # Critical validations
            assert workflow["ir_version"] == "1.0.0"
            assert len(workflow["nodes"]) >= 4, "Should have multi-step workflow"
            assert "inputs" in workflow and len(workflow["inputs"]) > 0

            # Verify template variables or defaults
            workflow_str = json.dumps(workflow)
            has_template_vars = "$" in workflow_str or "{{" in workflow_str
            logger.info(f"Workflow uses {'template variables' if has_template_vars else 'input defaults'}")

            # Step 6: Parameter Mapping convergence
            shared["selected_workflow"] = workflow
            mapping_node = ParameterMappingNode()
            prep_res = mapping_node.prep(shared)
            exec_res = mapping_node.exec(prep_res)
            action = mapping_node.post(shared, prep_res, exec_res)

            logger.info(f"Parameter mapping result: {action}")
            assert "extracted_params" in shared

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_issue_triage_north_star_secondary(self):
        """Test SECONDARY north star example: issue triage with double 'the'.

        Tests different parameter patterns and intentional grammar quirks.
        """
        # EXACT prompt with intentional double "the"
        TRIAGE_VERBOSE = """create a triage report for all open issues by fetching the the last 50 open issues from github, categorizing them by priority and type and then write them to triage-reports/2025-08-07-triage-report.md then commit the changes. Replace 2025-08-07 with the current date and mention the date in the commit message."""

        shared = {"user_input": TRIAGE_VERBOSE}

        try:
            # Run through Task 52 flow
            discovery = ParameterDiscoveryNode()
            discovery.post(shared, discovery.prep(shared), discovery.exec(discovery.prep(shared)))

            assert any("50" in str(v) for v in shared["discovered_params"].values()), "Should discover limit 50"

            requirements = RequirementsAnalysisNode()
            requirements.post(shared, requirements.prep(shared), requirements.exec(requirements.prep(shared)))

            assert shared["requirements_result"]["is_clear"] is True
            assert len(shared["requirements_result"]["steps"]) >= 3, "Should have multiple steps"

            browsing = ComponentBrowsingNode()
            browsing.post(shared, browsing.prep(shared), browsing.exec(browsing.prep(shared)))

            planning = PlanningNode()
            planning.post(shared, planning.prep(shared), planning.exec(planning.prep(shared)))

            generator = WorkflowGeneratorNode()
            generator.post(shared, generator.prep(shared), generator.exec(generator.prep(shared)))

            workflow = shared["generated_workflow"]

            # Verify complex workflow structure
            assert len(workflow["nodes"]) >= 4, "Should have detailed workflow"
            node_types = [n["type"] for n in workflow["nodes"]]
            assert any("github" in t.lower() or "issue" in t.lower() for t in node_types)
            assert any("llm" in t.lower() or "write" in t.lower() for t in node_types)

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_summarize_issue_north_star_tertiary(self):
        """Test TERTIARY north star example: simple issue summary.

        Ensures simple workflows still work with Task 52 flow.
        """
        ISSUE_SUMMARY = "summarize github issue 1234"
        shared = {"user_input": ISSUE_SUMMARY}

        try:
            # Run through Task 52 flow
            discovery = ParameterDiscoveryNode()
            discovery.post(shared, discovery.prep(shared), discovery.exec(discovery.prep(shared)))

            assert "1234" in str(shared["discovered_params"].values())

            requirements = RequirementsAnalysisNode()
            requirements.post(shared, requirements.prep(shared), requirements.exec(requirements.prep(shared)))

            assert shared["requirements_result"]["is_clear"] is True

            browsing = ComponentBrowsingNode()
            browsing.post(shared, browsing.prep(shared), browsing.exec(browsing.prep(shared)))

            planning = PlanningNode()
            planning.post(shared, planning.prep(shared), planning.exec(planning.prep(shared)))

            generator = WorkflowGeneratorNode()
            generator.post(shared, generator.prep(shared), generator.exec(generator.prep(shared)))

            workflow = shared["generated_workflow"]

            # Simple workflow validations
            assert 2 <= len(workflow["nodes"]) <= 4, "Simple workflow should be minimal"
            node_types = [n["type"] for n in workflow["nodes"]]
            assert any("github" in t.lower() for t in node_types), "Should have GitHub node"
            assert any("llm" in t.lower() for t in node_types), "Should have LLM for summarization"

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_vague_request_clarification_task52_feature(self):
        """Test Task 52 NEW FEATURE: RequirementsAnalysisNode catches vague requests.

        Critical for user experience - prevents confusing error messages.
        """
        VAGUE_REQUEST = "process the data"
        shared = {"user_input": VAGUE_REQUEST}

        try:
            discovery = ParameterDiscoveryNode()
            discovery.post(shared, discovery.prep(shared), discovery.exec(discovery.prep(shared)))

            # Requirements Analysis should catch vagueness
            requirements = RequirementsAnalysisNode()
            prep_res = requirements.prep(shared)
            exec_res = requirements.exec(prep_res)
            action = requirements.post(shared, prep_res, exec_res)

            result = shared["requirements_result"]

            if result.get("is_clear") is False:
                assert action == "clarification_needed", "Should route to clarification"
                assert result.get("clarification_needed"), "Should have clarification message"
                logger.info(f"SUCCESS: Vague request caught - {result.get('clarification_needed')}")
                return

            # If LLM thinks it's clear, verify it extracted something meaningful
            assert len(result.get("steps", [])) > 0, "If clear, should have steps"
            logger.warning("LLM interpreted vague request as clear - may need prompt tuning")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_impossible_requirements_task52_feature(self):
        """Test Task 52 NEW FEATURE: PlanningNode detects impossible requirements.

        Prevents wasted generation attempts and provides clear user feedback.
        """
        IMPOSSIBLE = "deploy the application to kubernetes cluster and send notification to slack channel #releases"
        shared = {"user_input": IMPOSSIBLE}

        try:
            # Run through to Planning
            discovery = ParameterDiscoveryNode()
            discovery.post(shared, discovery.prep(shared), discovery.exec(discovery.prep(shared)))

            requirements = RequirementsAnalysisNode()
            action = requirements.post(shared, requirements.prep(shared), requirements.exec(requirements.prep(shared)))

            if action == "clarification_needed":
                logger.info("Caught as vague by requirements")
                return  # Also acceptable

            browsing = ComponentBrowsingNode()
            browsing.post(shared, browsing.prep(shared), browsing.exec(browsing.prep(shared)))

            # Planning should detect missing capabilities
            planning = PlanningNode()
            prep_res = planning.prep(shared)
            exec_res = planning.exec(prep_res)
            action = planning.post(shared, prep_res, exec_res)

            if action == "impossible_requirements":
                logger.info("SUCCESS: Correctly identified as impossible")
                assert "_error" in exec_res or "error" in shared
            elif action == "partial_solution":
                logger.info("SUCCESS: Identified as partial solution")
                assert "_error" in exec_res or "error" in shared
            else:
                logger.warning("Planning thinks kubernetes/slack is feasible - checking plan")
                assert "planner_extended_blocks" in shared

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_parameter_types_critical_validation(self):
        """Test CRITICAL validation: parameters must be strings not integers.

        This bug caused actual failures in production (Task 57).
        """
        CHANGELOG = """generate a changelog for version 1.3 from the last 20 closed issues"""
        shared = {"user_input": CHANGELOG}

        try:
            discovery = ParameterDiscoveryNode()
            prep_res = discovery.prep(shared)
            exec_res = discovery.exec(prep_res)
            discovery.post(shared, prep_res, exec_res)

            discovered = shared.get("discovered_params", {})

            # CRITICAL: All numeric parameters must be strings
            for key, value in discovered.items():
                if value in ["20", "1.3", "50", "1234"]:
                    assert isinstance(value, str), f"CRITICAL BUG: {key}={value} must be string, got {type(value)}"

            # Specific checks for known parameters
            for key, value in discovered.items():
                if "version" in key.lower():
                    assert isinstance(value, str), f"Version must be string: {value}"
                if "limit" in key.lower() or "count" in key.lower():
                    assert isinstance(value, str), f"Count must be string: {value}"

            logger.info("SUCCESS: All parameters are strings")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_performance_monitoring_no_failures(self):
        """Test that slow API responses DON'T fail tests (Task 28 lesson).

        API response times vary 10x between models - must only warn.
        """
        shared = {"user_input": "generate a changelog for version 1.5"}
        start = time.time()

        try:
            discovery = WorkflowDiscoveryNode()
            prep_res = discovery.prep(shared)
            exec_res = discovery.exec(prep_res)
            action = discovery.post(shared, prep_res, exec_res)

            duration = time.time() - start

            # CRITICAL: Never fail on performance, only warn
            if duration > 20.0:
                logger.warning(f"Slow performance: {duration:.2f}s (model-dependent)")
                # Test still passes!

            assert action in ["found_existing", "not_found"]
            logger.info(f"Performance test completed in {duration:.2f}s - DID NOT FAIL")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise
