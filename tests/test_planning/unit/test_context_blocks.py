"""Unit tests for PlannerContextBuilder - Critical Task 52 functionality.

This test suite validates:
1. Immutable pattern - append methods return NEW lists
2. 4-block limit handling - Anthropic's cache_control marker limit
3. Edge cases - empty inputs, large context, missing params
4. Content structure - XML tags, cache markers, text format
"""

import json
from unittest.mock import patch

import pytest

from pflow.planning.context_blocks import PlannerContextBuilder


class TestImmutablePattern:
    """CRITICAL: Verify that append methods follow immutable pattern."""

    def test_append_planning_block_returns_new_list(self):
        """append_planning_block MUST return a new list, not modify original."""
        # Create original blocks
        original_blocks = [
            {"text": "Block A", "cache_control": {"type": "ephemeral"}},
            {"text": "Block B", "cache_control": {"type": "ephemeral"}},
        ]

        # Store references to verify immutability
        original_blocks_copy = original_blocks.copy()
        original_first_block = original_blocks[0]

        # Append planning block
        new_blocks = PlannerContextBuilder.append_planning_block(
            original_blocks, "Planning output text", {"status": "FEASIBLE", "node_chain": "node1 >> node2"}
        )

        # CRITICAL ASSERTIONS
        assert new_blocks is not original_blocks, "Must return NEW list, not same object"
        assert len(new_blocks) == 3, "Should have 3 blocks after appending"
        assert len(original_blocks) == 2, "Original list must remain unchanged"
        assert original_blocks == original_blocks_copy, "Original list content must not change"
        assert original_blocks[0] is original_first_block, "Original block objects must not be replaced"

        # Verify new block was added correctly
        assert "## Execution Plan" in new_blocks[2]["text"]
        assert "Planning output text" in new_blocks[2]["text"]

    def test_append_workflow_block_returns_new_list(self):
        """append_workflow_block MUST return a new list, not modify original."""
        original_blocks = [
            {"text": "Block A", "cache_control": {"type": "ephemeral"}},
            {"text": "Block B", "cache_control": {"type": "ephemeral"}},
        ]

        original_blocks_copy = original_blocks.copy()

        # Append workflow block
        workflow = {"nodes": [{"id": "test"}], "edges": []}
        new_blocks = PlannerContextBuilder.append_workflow_block(original_blocks, workflow, attempt_number=1)

        # CRITICAL ASSERTIONS
        assert new_blocks is not original_blocks, "Must return NEW list"
        assert len(new_blocks) == 3, "Should have 3 blocks"
        assert len(original_blocks) == 2, "Original unchanged"
        assert original_blocks == original_blocks_copy, "Original content unchanged"

        # Verify workflow content
        assert "## Generated Workflow (Attempt 1)" in new_blocks[2]["text"]
        assert json.dumps(workflow, indent=2) in new_blocks[2]["text"]

    def test_append_errors_block_returns_new_list(self):
        """append_errors_block MUST return a new list, not modify original."""
        original_blocks = [
            {"text": "Block A", "cache_control": {"type": "ephemeral"}},
        ]

        original_blocks_copy = original_blocks.copy()

        # Append errors block
        errors = ["Error 1: Invalid node", "Error 2: Missing input"]
        new_blocks = PlannerContextBuilder.append_errors_block(original_blocks, errors)

        # CRITICAL ASSERTIONS
        assert new_blocks is not original_blocks, "Must return NEW list"
        assert len(new_blocks) == 2, "Should have 2 blocks"
        assert len(original_blocks) == 1, "Original unchanged"
        assert original_blocks == original_blocks_copy, "Original content unchanged"

        # Verify error content
        assert "## Validation Errors" in new_blocks[1]["text"]
        assert "1. Error 1: Invalid node" in new_blocks[1]["text"]
        assert "2. Error 2: Missing input" in new_blocks[1]["text"]

    def test_append_errors_with_empty_list_returns_same_list(self):
        """append_errors_block with empty errors should return same list (but still immutable)."""
        original_blocks = [
            {"text": "Block A", "cache_control": {"type": "ephemeral"}},
        ]

        # Append empty errors
        new_blocks = PlannerContextBuilder.append_errors_block(
            original_blocks,
            [],  # Empty errors
        )

        # Should return same list when no errors
        assert new_blocks is original_blocks, "Should return same list object when no errors"
        assert len(new_blocks) == 1, "Should still have 1 block"

    def test_deep_copy_behavior_for_combined_blocks(self):
        """When combining blocks at limit, ensure deep copy of the modified block."""
        # Create blocks at the 4-block limit
        original_blocks = [
            {"text": "Block A", "cache_control": {"type": "ephemeral"}},
            {"text": "Block B", "cache_control": {"type": "ephemeral"}},
            {"text": "Block C", "cache_control": {"type": "ephemeral"}},
            {"text": "Block D", "cache_control": {"type": "ephemeral"}},
        ]

        # Store reference to last block
        original_last_block = original_blocks[3]

        # Append workflow (should combine with last block due to limit)
        workflow = {"test": "workflow"}
        new_blocks = PlannerContextBuilder.append_workflow_block(original_blocks, workflow, attempt_number=2)

        # CRITICAL: Original blocks must not be modified
        assert len(new_blocks) == 4, "Should still have 4 blocks"
        assert len(original_blocks) == 4, "Original should still have 4"
        assert original_blocks[3] is original_last_block, "Original last block object unchanged"
        assert original_blocks[3]["text"] == "Block D", "Original last block text unchanged"

        # New blocks should have combined content in last position
        assert new_blocks[3] is not original_last_block, "New last block is different object"
        assert "Block D" in new_blocks[3]["text"], "Original content preserved"
        assert "## Generated Workflow (Attempt 2)" in new_blocks[3]["text"], "New content added"


class TestFourBlockLimit:
    """Test Anthropic's 4 cache_control marker limit handling."""

    def test_exactly_at_four_block_limit(self):
        """Test behavior when exactly at 4-block limit."""
        # Create blocks at limit
        blocks_at_limit = [
            {"text": "Block 1", "cache_control": {"type": "ephemeral"}},
            {"text": "Block 2", "cache_control": {"type": "ephemeral"}},
            {"text": "Block 3", "cache_control": {"type": "ephemeral"}},
            {"text": "Block 4", "cache_control": {"type": "ephemeral"}},
        ]

        # Try to append planning block
        new_blocks = PlannerContextBuilder.append_planning_block(
            blocks_at_limit, "Planning text", {"status": "FEASIBLE", "node_chain": "test"}
        )

        # Should combine with last block
        assert len(new_blocks) == 4, "Should remain at 4 blocks"
        assert "Block 4" in new_blocks[3]["text"], "Original Block 4 content preserved"
        assert "## Execution Plan" in new_blocks[3]["text"], "Planning content added"
        assert new_blocks[3]["text"].count("\n\n") >= 1, "Proper spacing between combined content"

    def test_multiple_retries_exceeding_limit(self):
        """Test multiple retry scenario that would exceed 4 blocks."""
        # Start with base blocks (2)
        base_blocks = PlannerContextBuilder.build_base_blocks(
            user_request="test request",
            requirements_result={"steps": ["step1"]},
            browsed_components={"node_ids": ["node1"]},
            planning_context="context",
        )

        # Add planning block (3)
        with_plan = PlannerContextBuilder.append_planning_block(
            base_blocks, "Plan output", {"status": "FEASIBLE", "node_chain": "node1"}
        )

        # Add first workflow attempt (4)
        with_workflow_1 = PlannerContextBuilder.append_workflow_block(with_plan, {"attempt": 1}, attempt_number=1)

        # Add validation errors (should combine due to limit)
        with_errors_1 = PlannerContextBuilder.append_errors_block(with_workflow_1, ["Error 1", "Error 2"])

        assert len(with_errors_1) == 4, "Should be at 4-block limit"
        assert "## Validation Errors" in with_errors_1[3]["text"], "Errors combined with last block"

        # Add second workflow attempt (should still combine)
        with_workflow_2 = PlannerContextBuilder.append_workflow_block(with_errors_1, {"attempt": 2}, attempt_number=2)

        assert len(with_workflow_2) == 4, "Should remain at 4 blocks"
        assert "Attempt 1" in with_workflow_2[3]["text"], "First attempt preserved"
        assert "Attempt 2" in with_workflow_2[3]["text"], "Second attempt added"

    def test_content_preservation_when_combining(self):
        """Verify all content is preserved when blocks are combined."""
        blocks = [
            {"text": "A" * 1000, "cache_control": {"type": "ephemeral"}},
            {"text": "B" * 1000, "cache_control": {"type": "ephemeral"}},
            {"text": "C" * 1000, "cache_control": {"type": "ephemeral"}},
            {"text": "D" * 1000, "cache_control": {"type": "ephemeral"}},
        ]

        # Add multiple items that should combine
        errors = ["X" * 100, "Y" * 100, "Z" * 100]
        new_blocks = PlannerContextBuilder.append_errors_block(blocks, errors)

        # Verify all content is present
        combined_text = new_blocks[3]["text"]
        assert "D" * 1000 in combined_text, "Original block D preserved"
        assert "X" * 100 in combined_text, "Error X added"
        assert "Y" * 100 in combined_text, "Error Y added"
        assert "Z" * 100 in combined_text, "Error Z added"

        # Verify structure
        assert combined_text.index("D" * 1000) < combined_text.index("X" * 100), "Original content comes first"

    def test_empty_blocks_at_limit(self):
        """Test edge case: empty blocks when at limit."""
        blocks = [
            {"text": "", "cache_control": {"type": "ephemeral"}},
            {"text": "", "cache_control": {"type": "ephemeral"}},
            {"text": "", "cache_control": {"type": "ephemeral"}},
            {"text": "", "cache_control": {"type": "ephemeral"}},
        ]

        # Append content to empty blocks at limit
        new_blocks = PlannerContextBuilder.append_planning_block(
            blocks, "Planning content", {"status": "FEASIBLE", "node_chain": "test"}
        )

        assert len(new_blocks) == 4, "Should remain at 4 blocks"
        assert "## Execution Plan" in new_blocks[3]["text"], "Content added to last block"


class TestEdgeCases:
    """Test edge cases and robustness."""

    def test_build_base_blocks_with_empty_inputs(self):
        """Test build_base_blocks with empty/minimal inputs."""
        # Test with all empty strings
        blocks = PlannerContextBuilder.build_base_blocks(
            user_request="", requirements_result={}, browsed_components={}, planning_context="", discovered_params=None
        )

        # Should still create blocks with structure
        assert len(blocks) >= 1, "Should create at least one block"
        assert all("text" in b and "cache_control" in b for b in blocks), "Blocks have required structure"

    def test_build_base_blocks_with_none_values(self):
        """Test build_base_blocks with None values for optional params."""
        blocks = PlannerContextBuilder.build_base_blocks(
            user_request="test",
            requirements_result=None,
            browsed_components={"node_ids": ["test"]},
            planning_context="",
            discovered_params=None,  # Optional
        )

        # Should handle None gracefully
        assert len(blocks) >= 1, "Should create blocks"
        assert "<user_request>" in blocks[-1]["text"], "User request included"
        # Should not have user_values section when discovered_params is None
        assert "<user_values>" not in blocks[-1]["text"], "No user_values when params are None"

    def test_very_large_context_handling(self):
        """Test handling of very large context (100K+ chars)."""
        # Create very large context
        large_text = "X" * 100000  # 100K chars

        blocks = PlannerContextBuilder.build_base_blocks(
            user_request=large_text,
            requirements_result={"steps": ["Y" * 10000]},  # 10K chars
            browsed_components={"node_ids": ["node"] * 1000},  # Many nodes
            planning_context="Z" * 50000,  # 50K chars
            discovered_params={"param": "A" * 10000},
        )

        # Should handle large content without errors
        assert len(blocks) >= 1, "Should create blocks"
        total_size = sum(len(b["text"]) for b in blocks)
        assert total_size > 150000, "Should preserve large content"

        # Verify structure is maintained
        assert all("cache_control" in b for b in blocks), "All blocks have cache_control"

    def test_max_retry_history_limit(self):
        """Test that MAX_RETRY_HISTORY is enforced (if implemented)."""
        # Note: MAX_RETRY_HISTORY is defined but not currently enforced in the code
        # This test documents expected behavior if it were implemented

        # Create blocks and add many retries
        blocks = [{"text": "Base", "cache_control": {"type": "ephemeral"}}]

        # Add more retries than MAX_RETRY_HISTORY (which is 3)
        for i in range(5):
            blocks = PlannerContextBuilder.append_workflow_block(blocks, {"attempt": i + 1}, attempt_number=i + 1)
            blocks = PlannerContextBuilder.append_errors_block(blocks, [f"Error {i + 1}"])

        # Currently this will just keep appending/combining
        # Document that MAX_RETRY_HISTORY could be enforced here
        assert len(blocks) <= 4, "Blocks stay within Anthropic limit"

    def test_special_characters_in_content(self):
        """Test handling of special characters that might break JSON/XML."""
        special_content = """
        Special chars: < > & " ' \\ /
        Unicode: 🎉 你好 مرحبا
        Control chars: \n \t \r
        JSON breakers: {"key": "value"}
        XML breakers: <tag>content</tag>
        """

        blocks = PlannerContextBuilder.build_base_blocks(
            user_request=special_content,
            requirements_result={"steps": [special_content]},
            browsed_components={"node_ids": ["<node>", "&node", '"node"']},
            planning_context=special_content,
            discovered_params={"<param>": special_content},
        )

        # Should handle special characters without breaking
        assert len(blocks) >= 1, "Should create blocks"

        # When appending workflow with special chars
        workflow = {"special": special_content}
        new_blocks = PlannerContextBuilder.append_workflow_block(blocks, workflow, attempt_number=1)

        # JSON should be properly escaped
        assert json.dumps(workflow, indent=2) in new_blocks[-1]["text"], "JSON properly formatted"


class TestContentStructure:
    """Test content structure and formatting."""

    def test_xml_tags_properly_formatted(self):
        """Verify XML tags are properly opened and closed."""
        blocks = PlannerContextBuilder.build_base_blocks(
            user_request="test request",
            requirements_result={"steps": ["step1", "step2"]},
            browsed_components={"node_ids": ["node1", "node2"]},
            planning_context="context",
            discovered_params={"param1": "value1"},
        )

        # Get just the dynamic block (last one) which has our XML tags
        # The first block is the static workflow overview
        dynamic_block = blocks[-1]["text"] if len(blocks) > 1 else blocks[0]["text"]

        # Check XML tags are properly paired in the dynamic content
        assert dynamic_block.count("<user_request>") == dynamic_block.count("</user_request>"), (
            "user_request tags paired"
        )
        assert dynamic_block.count("<user_values>") == dynamic_block.count("</user_values>"), "user_values tags paired"
        assert dynamic_block.count("<requirements_analysis>") == dynamic_block.count("</requirements_analysis>"), (
            "requirements tags paired"
        )
        assert dynamic_block.count("<available_nodes>") == dynamic_block.count("</available_nodes>"), (
            "nodes tags paired"
        )
        assert dynamic_block.count("<node_details>") == dynamic_block.count("</node_details>"), "details tags paired"

    @patch("pflow.planning.context_blocks.Path.exists")
    @patch("pflow.planning.context_blocks.Path.read_text")
    def test_workflow_overview_caching(self, mock_read_text, mock_exists):
        """Test that workflow overview is loaded once and cached."""
        mock_exists.return_value = True
        mock_read_text.return_value = "# Workflow System Overview\nTest content"

        # Clear any existing cache
        PlannerContextBuilder._workflow_overview_cache = None

        # First call should load from file
        blocks1 = PlannerContextBuilder.build_base_blocks(
            user_request="test1",
            requirements_result={},
            browsed_components={},
            planning_context="",
        )

        assert mock_read_text.call_count == 1, "Should load file once"

        # Second call should use cache
        blocks2 = PlannerContextBuilder.build_base_blocks(
            user_request="test2",
            requirements_result={},
            browsed_components={},
            planning_context="",
        )

        assert mock_read_text.call_count == 1, "Should not reload file (cached)"

        # Both should have the same overview content
        assert blocks1[0]["text"] == blocks2[0]["text"], "Same cached content"

    def test_cache_control_markers_present(self):
        """Verify all blocks have proper cache_control markers."""
        # Test all methods that create blocks
        base_blocks = PlannerContextBuilder.build_base_blocks(
            user_request="test",
            requirements_result={"steps": ["step"]},
            browsed_components={"node_ids": ["node"]},
            planning_context="context",
        )

        with_plan = PlannerContextBuilder.append_planning_block(
            base_blocks, "plan", {"status": "FEASIBLE", "node_chain": "test"}
        )

        with_workflow = PlannerContextBuilder.append_workflow_block(with_plan, {"test": "workflow"}, attempt_number=1)

        with_errors = PlannerContextBuilder.append_errors_block(with_workflow, ["error1", "error2"])

        # All blocks should have cache_control
        all_blocks = with_errors
        for i, block in enumerate(all_blocks):
            assert "cache_control" in block, f"Block {i} missing cache_control"
            assert block["cache_control"]["type"] == "ephemeral", f"Block {i} should be ephemeral"
            assert "text" in block, f"Block {i} missing text"

    def test_get_context_metrics(self):
        """Test the get_context_metrics utility method."""
        test_text = "Hello " * 100  # 600 chars

        metrics = PlannerContextBuilder.get_context_metrics(test_text)

        assert "characters" in metrics, "Should have characters count"
        assert metrics["characters"] == 600, "Should count characters correctly"
        assert "estimated_tokens" in metrics, "Should estimate tokens"
        assert metrics["estimated_tokens"] > 0, "Should have positive token estimate"
        # Note: "blocks" in metrics refers to text sections, not cache blocks

    def test_discovered_params_format_handling(self):
        """Test handling of different discovered_params formats."""
        # Test dict format
        blocks1 = PlannerContextBuilder.build_base_blocks(
            user_request="test",
            requirements_result={},
            browsed_components={},
            planning_context="",
            discovered_params={"param1": "value1", "param2": "value2"},
        )

        text1 = "\n".join(b["text"] for b in blocks1)
        assert 'param1: "value1"' in text1, "Dict format handled"
        assert 'param2: "value2"' in text1, "Dict format handled"

        # Test nested format with 'parameters' key
        blocks2 = PlannerContextBuilder.build_base_blocks(
            user_request="test",
            requirements_result={},
            browsed_components={},
            planning_context="",
            discovered_params={"parameters": {"param3": "value3"}},
        )

        text2 = "\n".join(b["text"] for b in blocks2)
        assert 'param3: "value3"' in text2, "Nested format handled"


class TestRealWorldScenarios:
    """Test real-world usage patterns."""

    def test_complete_retry_flow(self):
        """Test a complete flow with initial attempt and retry."""
        # Initial context
        base = PlannerContextBuilder.build_base_blocks(
            user_request="Create changelog from ${repo} issues",
            requirements_result={
                "is_clear": True,
                "steps": ["Fetch issues", "Generate changelog"],
                "required_capabilities": ["github", "text"],
            },
            browsed_components={
                "node_ids": ["github-list-issues", "llm"],
                "workflow_names": [],
                "reasoning": "Selected GitHub and LLM nodes",
            },
            planning_context="github-list-issues: Fetches issues\nllm: Processes text",
            discovered_params={"repo": "myrepo"},
        )

        # Add planning (the plan_output text is what gets included, not the parsed dict)
        plan_output = """Plan: Use github-list-issues to fetch, then llm to format

**Status**: FEASIBLE
**Node Chain**: github-list-issues >> llm"""
        with_plan = PlannerContextBuilder.append_planning_block(
            base, plan_output, {"status": "FEASIBLE", "node_chain": "github-list-issues >> llm"}
        )

        # First generation attempt
        workflow_v1 = {
            "nodes": [{"id": "fetch", "type": "github-list-issues"}, {"id": "format", "type": "llm"}],
            "inputs": {"repo": {"type": "string"}},
        }
        with_workflow = PlannerContextBuilder.append_workflow_block(with_plan, workflow_v1, attempt_number=1)

        # Validation fails
        with_errors = PlannerContextBuilder.append_errors_block(
            with_workflow, ["Missing required parameter 'prompt' for llm node"]
        )

        # Second attempt
        workflow_v2 = {
            "nodes": [
                {"id": "fetch", "type": "github-list-issues"},
                {"id": "format", "type": "llm", "params": {"prompt": "Format as changelog"}},
            ],
            "inputs": {"repo": {"type": "string"}},
        }
        final_blocks = PlannerContextBuilder.append_workflow_block(with_errors, workflow_v2, attempt_number=2)

        # Verify the complete context is preserved
        assert len(final_blocks) == 4, "Should be at 4-block limit"

        # Check all content is present
        combined = "\n".join(b["text"] for b in final_blocks)
        assert "Create changelog from ${repo} issues" in combined, "Original request preserved"
        assert "github-list-issues >> llm" in combined, "Plan preserved"
        assert "Attempt 1" in combined, "First attempt preserved"
        assert "Missing required parameter" in combined, "Error preserved"
        assert "Attempt 2" in combined, "Second attempt added"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
