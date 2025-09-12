"""Test context accumulates through retry cycle enabling learning.

WHEN TO RUN:
- After changing PlannerContextBuilder
- After modifying retry logic in WorkflowGeneratorNode
- After changing context block structure
- Before releases

WHAT IT VALIDATES:
- Context grows: base → planning → workflow → errors
- Previous context is preserved at each stage
- This enables learning from validation errors
- Block boundaries are maintained

CRITICAL: This is Task 52's core value - learning from errors.
"""

from unittest.mock import patch

from pflow.planning.context_blocks import PlannerContextBuilder


class TestContextAccumulation:
    """Test context accumulation pattern through retry cycle."""

    def test_retry_preserves_and_extends_context(self):
        """Context MUST grow: base → planning → workflow → errors → retry.

        This is THE critical integration test for Task 52.
        If context doesn't accumulate, retries just repeat the same mistakes.
        """

        # Stage 1: Build base context
        base_context = PlannerContextBuilder.build_base_context(
            user_request="fetch ${issue_count} issues from ${repo} and create changelog",
            requirements_result={
                "is_clear": True,
                "steps": [
                    "Fetch filtered issues from GitHub repository",
                    "Analyze and group issues by type",
                    "Generate formatted changelog",
                    "Write changelog to file",
                ],
                "required_capabilities": ["github_api", "text_generation", "file_io"],
                "estimated_nodes": 4,
            },
            browsed_components={
                "node_ids": ["github-list-issues", "llm", "write-file"],
                "workflow_names": [],
                "reasoning": "Selected GitHub, LLM, and file nodes for the workflow",
            },
            planning_context="github-list-issues: Fetches issues from GitHub\nllm: Processes text\nwrite-file: Writes to filesystem",
            discovered_params={"issue_count": "30", "repo": "octocat/hello-world"},
        )

        # CRITICAL ASSERTIONS - Base context has all foundation blocks
        assert "## User Request" in base_context, "Must include user request"
        assert "fetch ${issue_count} issues" in base_context, "Must show templatized input"
        assert "# Workflow System Overview" in base_context, "Must include shared knowledge"
        assert "## Requirements Analysis" in base_context, "Must include requirements"
        assert "## Available Nodes" in base_context, "Must include components"
        assert "github-list-issues" in base_context, "Must list available nodes"

        # Count initial blocks
        initial_block_count = base_context.count("##")

        # Stage 2: Add planning output
        plan_markdown = """
        ## Execution Plan
        I'll create a workflow that fetches GitHub issues and generates a changelog.

        The workflow will:
        1. Use github-list-issues to fetch the issues
        2. Use llm to analyze and format them
        3. Use write-file to save the changelog

        ### Feasibility Assessment
        **Status**: FEASIBLE
        **Node Chain**: github-list-issues >> llm >> write-file
        """

        extended_context = PlannerContextBuilder.append_planning_output(
            base_context, plan_markdown, {"status": "FEASIBLE", "node_chain": "github-list-issues >> llm >> write-file"}
        )

        # CRITICAL ASSERTIONS - Planning added to context
        assert base_context in extended_context, "Must preserve ALL base context"
        assert "## Execution Plan" in extended_context, "Must add planning block"
        assert "github-list-issues >> llm >> write-file" in extended_context
        assert extended_context.count("##") > initial_block_count, "Must add new blocks"

        # Stage 3: Add generated workflow (first attempt)
        workflow_attempt1 = {
            "nodes": [
                {"id": "fetch", "type": "github-list-issues", "params": {"repo": "${repo}", "limit": "${issue_count}"}},
                {"id": "process", "type": "llm", "params": {"prompt": "Generate changelog from ${fetch.issues}"}},
                {
                    "id": "save",
                    "type": "write-file",
                    "params": {"path": "CHANGELOG.md", "content": "${process.response}"},
                },
            ],
            "edges": [{"from": "fetch", "to": "process"}, {"from": "process", "to": "save"}],
            "inputs": {
                "repo": {"type": "string", "required": True},
                "issue_count": {"type": "integer", "required": True},  # WRONG TYPE - will fail validation
            },
        }

        accumulated_context = PlannerContextBuilder.append_workflow_output(
            extended_context, workflow_attempt1, attempt=1
        )

        # CRITICAL ASSERTIONS - Workflow added to context
        assert extended_context in accumulated_context, "Must preserve ALL previous context"
        assert "## Generated Workflow (Attempt 1)" in accumulated_context
        assert '"type": "github-list-issues"' in accumulated_context, "Must include workflow JSON"
        assert accumulated_context.count("github-list-issues") > extended_context.count("github-list-issues")

        # Stage 4: Add validation errors
        validation_errors = [
            "Input 'issue_count' has wrong type: expected string, got integer",
            "Template variable ${fetch.issues} not defined - did you mean ${fetch.output}?",
            "Node 'fetch' missing required 'state' parameter",
        ]

        with_errors = PlannerContextBuilder.append_validation_errors(accumulated_context, validation_errors)

        # CRITICAL ASSERTIONS - ALL context preserved for learning
        assert "## User Request" in with_errors, "Original request preserved"
        assert "Workflow System Overview" in with_errors, "System knowledge preserved"
        assert "## Requirements Analysis" in with_errors, "Requirements preserved"
        assert "## Execution Plan" in with_errors, "Plan preserved"
        assert "## Generated Workflow (Attempt 1)" in with_errors, "Previous attempt preserved"
        assert "## Validation Errors" in with_errors, "Errors added"

        # Verify specific errors are included
        assert "wrong type: expected string" in with_errors
        assert "${fetch.issues} not defined" in with_errors
        assert "missing required 'state' parameter" in with_errors

        # This accumulated context enables learning!
        assert with_errors.count("##") >= 6, "Should have at least 6 context blocks"

        # Verify order is maintained (critical for caching)
        # Note: Some sections use # and some use ##, so check for both

        # Check that key sections exist in order
        assert with_errors.index("## User Request") < with_errors.index("# Workflow System Overview")
        assert with_errors.index("# Workflow System Overview") < with_errors.index("## Requirements Analysis")
        assert with_errors.index("## Requirements Analysis") < with_errors.index("## Available Nodes")
        assert with_errors.index("## Available Nodes") < with_errors.index("## Execution Plan")
        assert with_errors.index("## Execution Plan") < with_errors.index("## Generated Workflow (Attempt 1)")
        assert with_errors.index("## Generated Workflow (Attempt 1)") < with_errors.index("## Validation Errors")

    def test_multiple_retries_accumulate_history(self):
        """Multiple retries MUST preserve complete history.

        This ensures the LLM can see all previous attempts and errors.
        """
        base_context = PlannerContextBuilder.build_base_context(
            user_request="simple test",
            requirements_result={"steps": ["Test step"]},
            browsed_components={"node_ids": ["test-node"]},
            planning_context="test context",
            discovered_params={},
        )

        # Add planning
        with_plan = PlannerContextBuilder.append_planning_output(
            base_context, "Plan text", {"status": "FEASIBLE", "node_chain": "test"}
        )

        # Attempt 1
        with_attempt1 = PlannerContextBuilder.append_workflow_output(
            with_plan, {"nodes": [{"id": "1", "type": "test"}]}, attempt=1
        )

        with_errors1 = PlannerContextBuilder.append_validation_errors(with_attempt1, ["Error 1"])

        # Attempt 2
        with_attempt2 = PlannerContextBuilder.append_workflow_output(
            with_errors1, {"nodes": [{"id": "2", "type": "test-fixed"}]}, attempt=2
        )

        with_errors2 = PlannerContextBuilder.append_validation_errors(with_attempt2, ["Error 2"])

        # Attempt 3
        with_attempt3 = PlannerContextBuilder.append_workflow_output(
            with_errors2, {"nodes": [{"id": "3", "type": "test-final"}]}, attempt=3
        )

        # CRITICAL ASSERTIONS - Complete history preserved
        assert "## Generated Workflow (Attempt 1)" in with_attempt3
        assert "## Validation Errors" in with_attempt3  # Errors don't have attempt numbers
        assert "## Generated Workflow (Attempt 2)" in with_attempt3
        # Second validation errors would appear as another "## Validation Errors" section
        assert "## Generated Workflow (Attempt 3)" in with_attempt3

        # Verify we can trace the learning
        assert '"type": "test"' in with_attempt3, "First attempt preserved"
        assert '"type": "test-fixed"' in with_attempt3, "Second attempt preserved"
        assert '"type": "test-final"' in with_attempt3, "Third attempt preserved"
        assert "Error 1" in with_attempt3, "First error preserved"
        assert "Error 2" in with_attempt3, "Second error preserved"

    def test_context_metrics_track_growth(self):
        """Context metrics MUST track size growth accurately.

        This helps monitor token usage and cache efficiency.
        """
        base_context = PlannerContextBuilder.build_base_context(
            user_request="test",
            requirements_result={"steps": ["Step 1"]},
            browsed_components={"node_ids": ["node1"]},
            planning_context="context",
            discovered_params={},
        )

        base_metrics = PlannerContextBuilder.get_context_metrics(base_context)

        # Add planning
        with_plan = PlannerContextBuilder.append_planning_output(
            base_context,
            "A" * 1000,  # 1000 chars of planning
            {"status": "FEASIBLE", "node_chain": "test"},
        )

        plan_metrics = PlannerContextBuilder.get_context_metrics(with_plan)

        # CRITICAL ASSERTIONS
        assert plan_metrics["blocks"] > base_metrics["blocks"], "Block count should increase"
        assert plan_metrics["characters"] > base_metrics["characters"], "Character count should increase"
        assert plan_metrics["estimated_tokens"] > base_metrics["estimated_tokens"], "Tokens should increase"

        # Verify reasonable estimates
        assert plan_metrics["characters"] >= base_metrics["characters"] + 1000, "Should add at least planning text"
        assert plan_metrics["estimated_tokens"] > 0, "Should estimate tokens"

    def test_workflow_overview_loaded_and_cached(self):
        """Workflow overview MUST be loaded once and cached.

        This is critical shared knowledge between Planning and Generation.
        """
        # Clear cache to test loading
        PlannerContextBuilder._workflow_overview_cache = None

        with patch("pflow.planning.context_blocks.Path.read_text") as mock_read:
            mock_read.return_value = "# Workflow System Overview\nCritical shared knowledge..."

            # First call - should load from file
            context1 = PlannerContextBuilder.build_base_context(
                user_request="test 1",
                requirements_result={"steps": []},
                browsed_components={"node_ids": []},
                planning_context="",
                discovered_params={},
            )

            assert mock_read.call_count == 1, "Should read file once"
            assert "Workflow System Overview" in context1
            assert "Critical shared knowledge" in context1

            # Second call - should use cache
            context2 = PlannerContextBuilder.build_base_context(
                user_request="test 2",
                requirements_result={"steps": []},
                browsed_components={"node_ids": []},
                planning_context="",
                discovered_params={},
            )

            assert mock_read.call_count == 1, "Should NOT read file again - use cache"
            assert "Workflow System Overview" in context2
            assert "Critical shared knowledge" in context2

    def test_context_blocks_have_clear_boundaries(self):
        """Context blocks MUST have clear boundaries for caching.

        This enables efficient cache prefix matching.
        """
        base_context = PlannerContextBuilder.build_base_context(
            user_request="test",
            requirements_result={"steps": ["Step"]},
            browsed_components={"node_ids": ["node"]},
            planning_context="context",
            discovered_params={"param": "value"},
        )

        # Each major section should start with ##
        assert "## User Request" in base_context
        assert "Workflow System Overview" in base_context  # This uses # not ##
        assert "## Discovered Parameters" in base_context
        assert "## Requirements Analysis" in base_context
        assert "Available Nodes" in base_context  # Available Nodes section

        # Sections should be clearly separated
        sections = base_context.split("##")
        assert len(sections) > 5, "Should have multiple clear sections"

        # Each section should be self-contained
        for section in sections[1:]:  # Skip first empty
            if section.strip():
                lines = section.strip().split("\n")
                assert len(lines) > 0, "Section should have content"
                # First line should be section title
                assert not lines[0].startswith("#"), "Section title should not have extra #"
