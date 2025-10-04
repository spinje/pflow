"""Integration tests for cross-session caching functionality.

This test suite validates the end-to-end caching behavior:
1. Cache flag propagation through the system
2. Cache blocks are built when flag is enabled
3. LLM is called with appropriate cache parameters
"""

from unittest.mock import Mock, patch

from pflow.planning.nodes import (
    ComponentBrowsingNode,
    RequirementsAnalysisNode,
    WorkflowDiscoveryNode,
)


class TestCachingIntegration:
    """Test end-to-end caching functionality."""

    def test_discovery_node_uses_cache_when_enabled(self):
        """Test that WorkflowDiscoveryNode properly uses caching when enabled.

        FIX HISTORY:
        - 2025-01-19: Fixed to provide non-empty discovery_context. The optimization in
          WorkflowDiscoveryNode.exec() skips the LLM call when discovery_context is empty
          (no workflows exist). Tests must provide workflows to test caching behavior.
        """
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "Build me a workflow to process files",
            "cache_planner": True,  # Enable caching
        }

        # Mock dependencies - MUST return non-empty context to trigger LLM call
        with patch("pflow.planning.nodes.build_workflows_context") as mock_build_context:
            # Return workflow context that would trigger LLM call (> 1000 chars for caching)
            workflow_context = (
                """**1. `test-workflow`** - A test workflow for processing files
   **Flow:** `read-file → transform → write-file`
   **Can:** read files, transform data, write output
   **For:** file processing, data transformation

**2. `another-workflow`** - Another workflow for testing
   **Flow:** `fetch-data → process → store`
   **Can:** fetch remote data, process it, store results
   **For:** data fetching, processing pipelines"""
                + "A" * 700
            )  # Pad to ensure > 1000 chars
            mock_build_context.return_value = workflow_context

            # Patch at both locations to ensure proper cleanup
            with (
                patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt,
                patch("pflow.planning.utils.prompt_cache_helper.load_prompt", mock_load_prompt),
            ):
                # Use side_effect to return different templates based on prompt_name
                def load_prompt_side_effect(prompt_name):
                    if prompt_name == "discovery":
                        # Return a template that matches the real discovery prompt structure
                        # Must have "## Context" for caching logic to work
                        # Create actual content > 1000 chars (not just visual line breaks)
                        instructions_content = "Instructions for discovery. " * 50  # ~1400 chars
                        return f"""{instructions_content}

## Context

<existing_workflows>
{{{{discovery_context}}}}
</existing_workflows>

## Inputs

<user_request>
{{{{user_input}}}}
</user_request>"""
                    else:
                        # Return a generic template for other prompts
                        return f"Generic template for {prompt_name}"

                mock_load_prompt.side_effect = load_prompt_side_effect

                with patch("llm.get_model") as mock_get_model:
                    mock_model = Mock()
                    mock_response = Mock()

                    # Mock the response to return JSON string matching WorkflowDecision schema
                    mock_response.text.return_value = '{"found": false, "workflow_name": null, "confidence": 0.0, "reasoning": "No matching workflow found"}'

                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model

                    # Execute
                    prep_res = node.prep(shared)
                    node.exec(prep_res)

                    # Verify cache blocks were passed to LLM
                    mock_model.prompt.assert_called_once()
                    call_args = mock_model.prompt.call_args

                    # Check that cache_blocks parameter was provided and is not None when caching is enabled
                    assert "cache_blocks" in call_args.kwargs
                    cache_blocks = call_args.kwargs["cache_blocks"]

                    # When caching is enabled, cache_blocks should be a list (even if empty)
                    # The new architecture always builds cache blocks but passes them as None when disabled
                    assert cache_blocks is not None, "cache_blocks should not be None when caching is enabled"
                    assert isinstance(cache_blocks, list)

                    # Note: Cache blocks may be empty if content doesn't meet the 1000 char threshold
                    # The test setup has instructions > 1000 chars, so we should have at least one block
                    assert len(cache_blocks) >= 1, "Should have at least the instructions cached"

                    # Verify cache block structure
                    for block in cache_blocks:
                        assert "text" in block
                        assert "cache_control" in block
                        # All blocks should have ephemeral cache control when content is substantial
                        assert block["cache_control"]["type"] == "ephemeral"

    def test_discovery_node_no_cache_when_disabled(self):
        """Test that WorkflowDiscoveryNode doesn't use caching when disabled.

        FIX HISTORY:
        - 2025-01-19: Fixed to provide non-empty discovery_context. The optimization in
          WorkflowDiscoveryNode.exec() skips the LLM call when discovery_context is empty
          (no workflows exist). Tests must provide workflows to test caching behavior.
        """
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "Build me a workflow to process files",
            "cache_planner": False,  # Caching disabled
        }

        with patch("pflow.planning.nodes.build_workflows_context") as mock_build_context:
            # Return workflow context that would trigger LLM call (> 1000 chars for potential caching)
            workflow_context = (
                """**1. `test-workflow`** - A test workflow for processing files
   **Flow:** `read-file → transform → write-file`
   **Can:** read files, transform data, write output
   **For:** file processing, data transformation

**2. `another-workflow`** - Another workflow for testing
   **Flow:** `fetch-data → process → store`
   **Can:** fetch remote data, process it, store results
   **For:** data fetching, processing pipelines"""
                + "A" * 700
            )  # Pad to ensure > 1000 chars
            mock_build_context.return_value = workflow_context

            # Patch at both locations to ensure proper cleanup
            with (
                patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt,
                patch("pflow.planning.utils.prompt_cache_helper.load_prompt", mock_load_prompt),
            ):
                # Use side_effect to return different templates based on prompt_name
                def load_prompt_side_effect(prompt_name):
                    if prompt_name == "discovery":
                        # Same structure as above but caching should be disabled
                        # Create actual content > 1000 chars (not just visual line breaks)
                        instructions_content = "Instructions for discovery. " * 50  # ~1400 chars
                        return f"""{instructions_content}

## Context

<existing_workflows>
{{{{discovery_context}}}}
</existing_workflows>

## Inputs

<user_request>
{{{{user_input}}}}
</user_request>"""
                    else:
                        # Return a generic template for other prompts
                        return f"Generic template for {prompt_name}"

                mock_load_prompt.side_effect = load_prompt_side_effect

                with patch("llm.get_model") as mock_get_model:
                    mock_model = Mock()
                    mock_response = Mock()
                    # Mock the response to return JSON string matching WorkflowDecision schema
                    mock_response.text.return_value = '{"found": false, "workflow_name": null, "confidence": 0.0, "reasoning": "No matching workflow found"}'
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model

                    # Execute
                    prep_res = node.prep(shared)
                    node.exec(prep_res)

                    # Verify cache blocks parameter is None when disabled
                    mock_model.prompt.assert_called_once()
                    call_args = mock_model.prompt.call_args

                    # cache_blocks should be None when caching is disabled
                    assert "cache_blocks" in call_args.kwargs
                    assert call_args.kwargs["cache_blocks"] is None

    @patch("pflow.planning.utils.prompt_cache_helper.load_prompt")  # Patch where it's used
    @patch("llm.get_model")
    def test_requirements_node_uses_cache_when_enabled(self, mock_get_model, mock_load_prompt):
        """Test that RequirementsAnalysisNode properly uses caching when enabled."""
        # Import here to avoid cross-test contamination
        from pflow.planning.nodes import RequirementsAnalysisNode

        node = RequirementsAnalysisNode()
        shared = {
            "user_input": "Build me a workflow",
            "cache_planner": True,  # Enable caching
        }

        # Set up the mock to return the requirements template
        mock_load_prompt.return_value = "A" * 1500 + "\n## Context\n{{input_text}}"

        # Set up LLM mock
        mock_model = Mock()
        mock_response = Mock()
        # Mock the response to return JSON string matching RequirementsSchema
        mock_response.text.return_value = '{"is_clear": true, "clarification_needed": null, "steps": ["req1", "req2"], "estimated_nodes": 3, "required_capabilities": ["file_ops"], "complexity_indicators": {"complexity": "medium"}}'
        mock_model.prompt.return_value = mock_response
        mock_get_model.return_value = mock_model

        # Execute
        prep_res = node.prep(shared)
        node.exec(prep_res)

        # Verify cache blocks were used
        call_args = mock_model.prompt.call_args
        assert "cache_blocks" in call_args.kwargs
        cache_blocks = call_args.kwargs["cache_blocks"]
        assert len(cache_blocks) > 0

    def test_component_browsing_uses_multiple_cache_blocks(self):
        """Test that ComponentBrowsingNode creates multiple cache blocks."""
        node = ComponentBrowsingNode()
        shared = {
            "user_input": "test input",
            "selected_path": "PATH_A",
            "cache_planner": True,
        }

        # Mock all the context builders
        with patch("pflow.planning.context_builder.build_nodes_context") as mock_build_nodes:
            mock_build_nodes.return_value = "Node documentation " * 100

            with patch("pflow.planning.context_builder.build_workflows_context") as mock_build_workflows:
                mock_build_workflows.return_value = "Workflow documentation " * 100

                # Patch at both locations to ensure proper cleanup
                with (
                    patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt,
                    patch("pflow.planning.utils.prompt_cache_helper.load_prompt", mock_load_prompt),
                ):
                    # Use side_effect to return different templates based on prompt_name
                    def load_prompt_side_effect(prompt_name):
                        if prompt_name == "component_browsing":
                            # Must have "## Context" marker for special caching logic
                            # Create actual content > 1000 chars (not just visual line breaks)
                            instructions_content = "Component browsing instructions. " * 40  # ~1360 chars
                            return f"""{instructions_content}

## Context

This section will be dynamically built."""
                        else:
                            # Return a generic template for other prompts
                            return f"Generic template for {prompt_name}"

                    mock_load_prompt.side_effect = load_prompt_side_effect

                    with patch("pflow.registry.registry.Registry.load") as mock_registry:
                        mock_registry.return_value = {}

                        with patch("llm.get_model") as mock_get_model:
                            mock_model = Mock()
                            mock_response = Mock()
                            # Mock the response to return JSON string matching ComponentSelection schema
                            mock_response.text.return_value = '{"node_ids": ["read-file"], "workflow_names": [], "reasoning": "Selected read-file node for file operations"}'
                            mock_model.prompt.return_value = mock_response
                            mock_get_model.return_value = mock_model

                            # Execute
                            prep_res = node.prep(shared)
                            node.exec(prep_res)

                            # Verify cache blocks were passed to LLM
                            call_args = mock_model.prompt.call_args
                            assert "cache_blocks" in call_args.kwargs
                            cache_blocks = call_args.kwargs["cache_blocks"]

                            # When caching is enabled, cache_blocks should not be None
                            assert cache_blocks is not None, "cache_blocks should not be None when caching is enabled"
                            assert isinstance(cache_blocks, list)

                            # Component browsing should have at least the instructions cached
                            # The test setup has instructions > 1000 chars
                            assert len(cache_blocks) >= 1, "Should have at least the instructions cached"

                            # Could have up to 3 blocks: instructions, nodes context, workflows context
                            assert len(cache_blocks) <= 3, "Should have at most 3 cache blocks"

                            # Each block should be properly structured
                            for block in cache_blocks:
                                assert "text" in block
                                assert "cache_control" in block
                                assert block["cache_control"]["type"] == "ephemeral"
                                # Instructions or context should be substantial
                                assert len(block["text"]) > 100  # Should be substantial


class TestCacheFlagPropagation:
    """Test that cache flag propagates correctly through the system."""

    def test_cache_flag_in_shared_store(self):
        """Test that cache_planner flag is available in shared store."""
        shared_with_cache = {"cache_planner": True, "user_input": "test"}
        shared_without_cache = {"cache_planner": False, "user_input": "test"}
        shared_no_flag = {"user_input": "test"}  # No flag

        node = WorkflowDiscoveryNode()

        with patch("pflow.planning.context_builder.build_workflows_context"):
            # Test with cache enabled
            prep_res = node.prep(shared_with_cache)
            assert prep_res["cache_planner"] is True

            # Test with cache disabled
            prep_res = node.prep(shared_without_cache)
            assert prep_res["cache_planner"] is False

            # Test default (no flag)
            prep_res = node.prep(shared_no_flag)
            assert prep_res["cache_planner"] is False  # Defaults to False

    def test_all_nodes_respect_cache_flag(self):
        """Test that all LLM nodes check and respect the cache flag."""
        nodes_to_test = [
            WorkflowDiscoveryNode(),
            RequirementsAnalysisNode(),
        ]

        for node in nodes_to_test:
            shared = {"user_input": "test", "cache_planner": True}

            # Mock minimal dependencies
            with (
                patch("pflow.planning.context_builder.build_workflows_context", return_value="context"),
                patch("pflow.planning.context_builder.build_nodes_context", return_value="nodes"),
                patch("pflow.registry.registry.Registry.load", return_value={}),
            ):
                prep_res = node.prep(shared)

                # Verify cache flag is preserved
                assert "cache_planner" in prep_res
                assert prep_res["cache_planner"] is True


class TestCacheEffectiveness:
    """Test that caching actually provides the expected benefits."""

    def test_cache_blocks_contain_static_content(self):
        """Test that cache blocks contain the static documentation."""
        # Test the actual caching behavior with WorkflowDiscoveryNode
        from pflow.planning.nodes import WorkflowDiscoveryNode

        node = WorkflowDiscoveryNode()

        # Test with caching enabled
        with patch("pflow.planning.prompts.loader.load_prompt") as mock_load:
            # Create a prompt with substantial instructions (must be > 1000 chars)
            mock_load.return_value = (
                "A" * 1001 + "\n## Context\n<existing_workflows>\n{{discovery_context}}\n</existing_workflows>"
            )

            # Call _build_cache_blocks directly
            cache_blocks, _ = node._build_cache_blocks(
                discovery_context="B" * 1001,  # Also > 1000 to trigger caching
                user_input="test input",
                cache_planner=True,
            )

            # Should have created cache blocks
            assert len(cache_blocks) == 2  # One for instructions, one for context
            assert "A" * 1001 in cache_blocks[0]["text"]  # Instructions
            assert "B" * 1001 in cache_blocks[1]["text"]  # Discovery context
            assert all(b["cache_control"]["type"] == "ephemeral" for b in cache_blocks)

    def test_cache_blocks_marked_as_ephemeral(self):
        """Test that all cache blocks use ephemeral cache control."""
        from pflow.planning.utils.prompt_cache_helper import build_cached_prompt

        # Patch at the location where it's imported in prompt_cache_helper
        with patch("pflow.planning.utils.prompt_cache_helper.load_prompt") as mock_load:
            # Create a prompt that will trigger caching
            mock_load.return_value = "B" * 2000 + "\n## Context\n{{discovery_context}}\n{{user_input}}"

            blocks, _ = build_cached_prompt(
                "test_prompt", {"discovery_context": "test context", "user_input": "test input"}
            )

            # All blocks should be marked as ephemeral
            for block in blocks:
                assert block["cache_control"]["type"] == "ephemeral"
