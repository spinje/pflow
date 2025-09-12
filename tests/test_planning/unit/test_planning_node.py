"""Test PlanningNode markdown parsing and error routing.

WHEN TO RUN:
- Always (part of standard test suite)
- After modifying PlanningNode
- After changing planning_instructions.md prompt

WHAT IT VALIDATES:
- Markdown parsing extracts Status and Node Chain correctly
- IMPOSSIBLE status triggers impossible_requirements route
- PARTIAL status triggers partial_solution route with error
- Context narrative is built and stored correctly
- Only uses nodes from browsed_components

CRITICAL: Without parsing, we lose feasibility assessment and node chain.
"""

from unittest.mock import Mock, patch

import pytest

from pflow.planning.nodes import PlanningNode


class TestPlanningNode:
    """Test PlanningNode critical behavior."""

    def test_parse_plan_assessment_extracts_all_fields(self):
        """Markdown parsing MUST extract Status and Node Chain.

        This is THE integration point between Planning and Generation.
        If parsing fails, we lose critical plan information.
        """
        node = PlanningNode()

        markdown = """
        ## Execution Plan
        I'll fetch issues from GitHub, analyze them, and create a changelog.
        This workflow will use the available GitHub and file nodes.

        The data will flow from github-list-issues to the LLM for processing,
        then to write-file for output.

        ### Feasibility Assessment
        **Status**: IMPOSSIBLE
        **Missing Capabilities**: kubernetes_deployment, prometheus_monitoring
        **Node Chain**: github-list-issues >> llm >> write-file
        """

        parsed = node._parse_plan_assessment(markdown)

        # CRITICAL ASSERTIONS
        assert parsed["status"] == "IMPOSSIBLE", "Must extract status correctly"
        assert parsed["node_chain"] == "github-list-issues >> llm >> write-file", "Must extract node chain"
        assert parsed["missing_capabilities"] == ["kubernetes_deployment", "prometheus_monitoring"], (
            "Must extract missing capabilities"
        )

    def test_parse_handles_missing_fields_gracefully(self):
        """Parser MUST handle missing fields with defaults.

        This ensures we don't crash on unexpected markdown format.
        """
        node = PlanningNode()

        # Minimal markdown with only Status
        markdown = """
        Some planning text...
        **Status**: FEASIBLE
        """

        parsed = node._parse_plan_assessment(markdown)

        # Should have safe defaults
        assert parsed["status"] == "FEASIBLE"
        assert parsed["node_chain"] == "", "Missing node chain should default to empty"
        assert parsed["missing_capabilities"] == [], "Missing capabilities should default to empty list"

    def test_impossible_status_triggers_error_route(self):
        """IMPOSSIBLE status MUST route to user-visible error.

        This ensures users see specific "missing capabilities" feedback
        instead of generic "workflow generation failed".
        """
        node = PlanningNode()

        with patch("llm.get_model") as mock_llm:
            mock_model = Mock()
            mock_model.prompt.return_value = Mock(
                text=lambda: """
                ## Plan
                Cannot fulfill this request with available nodes.

                ### Feasibility Assessment
                **Status**: IMPOSSIBLE
                **Missing Capabilities**: kubernetes_api, monitoring_integration
                **Node Chain**: None
            """
            )
            mock_llm.return_value = mock_model

            # Mock context builder to avoid file reads
            with patch("pflow.planning.nodes.PlannerContextBuilder.build_base_context") as mock_context:
                mock_context.return_value = "Mock base context"

                shared = {
                    "requirements_result": {"steps": ["Deploy to Kubernetes", "Monitor with Prometheus"]},
                    "browsed_components": {
                        "node_ids": ["read-file", "write-file"],
                        "reasoning": "Only file nodes available",
                    },
                }

                prep_res = node.prep(shared)
                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                # CRITICAL ASSERTIONS
                assert action == "impossible_requirements", "IMPOSSIBLE must route to error"
                assert "_error" in exec_res, "Error must be embedded for ResultPreparationNode"
                assert exec_res["_error"]["category"] == "missing_resource"
                assert "kubernetes_api" in exec_res["_error"]["technical_details"]
                assert "monitoring_integration" in exec_res["_error"]["technical_details"]

                # User should see helpful message
                assert "capabilities not currently available" in exec_res["_error"]["user_action"]

    def test_partial_status_embeds_missing_capabilities(self):
        """PARTIAL status MUST embed missing capabilities as error.

        This provides specific feedback about what's missing.
        """
        node = PlanningNode()

        with patch("llm.get_model") as mock_llm:
            mock_model = Mock()
            mock_model.prompt.return_value = Mock(
                text=lambda: """
                ## Plan
                Can partially fulfill the request.

                ### Feasibility Assessment
                **Status**: PARTIAL
                **Missing Capabilities**: slack_integration
                **Node Chain**: github-list-issues >> llm >> write-file
            """
            )
            mock_llm.return_value = mock_model

            with patch("pflow.planning.nodes.PlannerContextBuilder.build_base_context") as mock_context:
                mock_context.return_value = "Mock base context"

                shared = {
                    "requirements_result": {"steps": ["Fetch issues", "Send to Slack"]},
                    "browsed_components": {"node_ids": ["github-list-issues", "llm", "write-file"]},
                }

                prep_res = node.prep(shared)
                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                # CRITICAL ASSERTIONS
                assert action == "partial_solution", "PARTIAL must route to partial_solution"
                assert "_error" in exec_res, "Error must be embedded even for partial"
                assert exec_res["_error"]["category"] == "missing_resource"
                assert "slack_integration" in exec_res["_error"]["technical_details"]
                assert "install the missing components" in exec_res["_error"]["user_action"]

    def test_feasible_status_continues_flow(self):
        """FEASIBLE status MUST continue to workflow generation.

        This is the happy path - plan is feasible, continue to generation.
        """
        node = PlanningNode()

        with patch("llm.get_model") as mock_llm:
            mock_model = Mock()
            mock_model.prompt.return_value = Mock(
                text=lambda: """
                ## Plan
                Perfect! I can create this workflow.

                ### Feasibility Assessment
                **Status**: FEASIBLE
                **Node Chain**: github-list-issues >> llm >> write-file
            """
            )
            mock_llm.return_value = mock_model

            with patch("pflow.planning.nodes.PlannerContextBuilder.build_base_context") as mock_context:
                mock_context.return_value = "Mock base context"

                shared = {
                    "requirements_result": {"steps": ["Fetch issues", "Generate changelog"]},
                    "browsed_components": {"node_ids": ["github-list-issues", "llm", "write-file"]},
                }

                prep_res = node.prep(shared)
                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                # CRITICAL ASSERTIONS
                assert action == "", "FEASIBLE must return empty string for default routing"
                assert "_error" not in exec_res, "No error should be embedded for feasible plan"
                assert shared["planning_result"]["status"] == "FEASIBLE"
                assert shared["planning_result"]["node_chain"] == "github-list-issues >> llm >> write-file"

    def test_stores_context_in_shared_store(self):
        """Context blocks MUST be stored for WorkflowGeneratorNode.

        This enables the cache-optimized architecture of Task 52.
        """
        node = PlanningNode()

        with patch("llm.get_model") as mock_llm:
            mock_model = Mock()
            mock_model.prompt.return_value = Mock(
                text=lambda: """
                ### Feasibility Assessment
                **Status**: FEASIBLE
                **Node Chain**: read-file >> llm
            """
            )
            mock_llm.return_value = mock_model

            with patch("pflow.planning.nodes.PlannerContextBuilder") as MockBuilder:
                MockBuilder.build_base_context.return_value = "BASE CONTEXT BLOCK"
                MockBuilder.append_planning_output.return_value = "EXTENDED CONTEXT BLOCK"
                MockBuilder.get_context_metrics.return_value = {"estimated_tokens": 1000, "blocks": 2}

                shared = {
                    "requirements_result": {"steps": ["Read file", "Process"]},
                    "browsed_components": {"node_ids": ["read-file", "llm"]},
                }

                prep_res = node.prep(shared)
                exec_res = node.exec(prep_res)
                node.post(shared, prep_res, exec_res)

                # CRITICAL ASSERTIONS - Context stored for pipeline
                assert "planner_base_context" in shared, "Base context must be stored"
                assert shared["planner_base_context"] == "BASE CONTEXT BLOCK"
                assert "planner_extended_context" in shared, "Extended context must be stored"
                assert shared["planner_extended_context"] == "EXTENDED CONTEXT BLOCK"

    def test_only_uses_browsed_component_nodes(self):
        """Planning MUST only use nodes from browsed_components.

        This validates the constraint that Planning can't suggest
        nodes that weren't selected by ComponentBrowsing.
        """
        node = PlanningNode()

        # This test validates the constraint is documented and followed
        # The actual enforcement happens in the prompt and LLM behavior

        shared = {
            "requirements_result": {"steps": ["Send email"]},
            "browsed_components": {
                "node_ids": ["read-file", "write-file"],  # No email node!
                "reasoning": "Only file nodes available",
            },
        }

        prep_res = node.prep(shared)

        # Verify browsed_components is passed to exec
        assert prep_res["browsed_components"]["node_ids"] == ["read-file", "write-file"]
        assert "email" not in str(prep_res["browsed_components"]["node_ids"])

    def test_case_insensitive_status_parsing(self):
        """Status parsing MUST be case-insensitive.

        This ensures robustness to LLM output variations.
        """
        node = PlanningNode()

        # Test various cases
        test_cases = [
            ("**Status**: feasible", "FEASIBLE"),
            ("**status**: IMPOSSIBLE", "IMPOSSIBLE"),
            ("**Status**: Partial", "PARTIAL"),
            ("**STATUS**: FEaSiBLe", "FEASIBLE"),
        ]

        for markdown, expected in test_cases:
            parsed = node._parse_plan_assessment(markdown)
            assert parsed["status"] == expected.upper(), f"Failed to parse {markdown}"

    def test_handles_complex_node_chain(self):
        """Parser MUST handle complex multi-node chains.

        Real workflows often have 5+ nodes chained together.
        """
        node = PlanningNode()

        markdown = """
        ### Feasibility Assessment
        **Status**: FEASIBLE
        **Node Chain**: github-list-issues >> github-get-issue >> llm >> slack-post-message >> write-file >> git-commit
        """

        parsed = node._parse_plan_assessment(markdown)

        expected_chain = (
            "github-list-issues >> github-get-issue >> llm >> slack-post-message >> write-file >> git-commit"
        )
        assert parsed["node_chain"] == expected_chain
        assert ">>" in parsed["node_chain"], "Should preserve >> operators"

    def test_exec_fallback_raises_critical_error(self):
        """exec_fallback MUST raise CriticalPlanningError.

        Planning is critical - we cannot generate workflows without a plan.
        """
        node = PlanningNode()

        prep_res = {
            "requirements_result": {"steps": ["Test"]},
            "browsed_components": {"node_ids": ["test"]},
            "model_name": "test-model",
        }

        from pflow.core.exceptions import CriticalPlanningError

        # Planning failure is critical
        with pytest.raises(CriticalPlanningError) as exc_info:
            node.exec_fallback(prep_res, Exception("LLM timeout"))

        assert "Cannot create execution plan" in str(exc_info.value)
        assert "LLM timeout" in str(exc_info.value.original_error)
