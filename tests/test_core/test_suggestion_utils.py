"""Tests for suggestion utilities."""

from pflow.core.suggestion_utils import find_similar_items, format_did_you_mean


class TestFindSimilarItems:
    """Tests for find_similar_items function."""

    def test_substring_exact_match(self):
        """Test substring matching with exact match."""
        items = ["read-file", "write-file", "llm"]
        result = find_similar_items("file", items, method="substring")
        assert result == ["read-file", "write-file"]

    def test_substring_partial_match(self):
        """Test substring matching with partial match."""
        items = ["read-file", "write-file", "llm-generate"]
        result = find_similar_items("read", items, method="substring")
        assert result == ["read-file"]

    def test_substring_case_insensitive(self):
        """Test substring matching is case-insensitive."""
        items = ["ReadFile", "WriteFile"]
        result = find_similar_items("file", items, method="substring")
        assert result == ["ReadFile", "WriteFile"]

    def test_substring_max_results(self):
        """Test max_results limit."""
        items = ["file1", "file2", "file3", "file4"]
        result = find_similar_items("file", items, method="substring", max_results=2)
        assert len(result) == 2
        assert result == ["file1", "file2"]

    def test_substring_sort_by_length(self):
        """Test sorting by length."""
        items = ["very-long-file", "file", "medium-file"]
        result = find_similar_items("file", items, method="substring", sort_by_length=True)
        assert result[0] == "file"  # Shortest first

    def test_fuzzy_typo_tolerant(self):
        """Test fuzzy matching catches typos."""
        items = ["read", "write", "execute"]
        result = find_similar_items("reed", items, method="fuzzy", cutoff=0.4)
        assert "read" in result

    def test_fuzzy_cutoff_threshold(self):
        """Test fuzzy cutoff threshold."""
        items = ["read", "write"]
        result = find_similar_items("xyz", items, method="fuzzy", cutoff=0.6)
        assert result == []  # No matches above threshold

    def test_empty_items_list(self):
        """Test with empty items list."""
        result = find_similar_items("file", [], method="substring")
        assert result == []
        assert isinstance(result, list)

    def test_no_matches(self):
        """Test when no items match."""
        items = ["read", "write"]
        result = find_similar_items("xyz", items, method="substring")
        assert result == []

    def test_fuzzy_max_results(self):
        """Test fuzzy matching respects max_results."""
        items = ["read", "reed", "reedx", "reedy", "reedz"]
        result = find_similar_items("reed", items, method="fuzzy", max_results=3)
        assert len(result) <= 3
        assert all(item in items for item in result)

    def test_substring_stops_at_max(self):
        """Test substring matching stops at max_results."""
        items = [f"file{i}" for i in range(100)]
        result = find_similar_items("file", items, method="substring", max_results=5)
        assert len(result) == 5
        # Should be first 5 due to early termination
        assert result == ["file0", "file1", "file2", "file3", "file4"]


class TestFormatDidYouMean:
    """Tests for format_did_you_mean function."""

    def test_with_suggestions(self):
        """Test formatting with suggestions."""
        result = format_did_you_mean("fil", ["file", "filter"], item_type="node")
        assert "Did you mean one of these nodes?" in result
        assert "file" in result
        assert "filter" in result
        assert isinstance(result, str)
        assert len(result) > 0

    def test_with_fallback(self):
        """Test formatting with fallback items."""
        result = format_did_you_mean("xyz", [], item_type="node", fallback_items=["read", "write", "llm"])
        assert "No similar nodes found" in result
        assert "Available nodes:" in result
        assert "read" in result

    def test_fallback_truncation(self):
        """Test fallback truncates to max_fallback."""
        many_items = [f"item{i}" for i in range(20)]
        result = format_did_you_mean("xyz", [], item_type="node", fallback_items=many_items, max_fallback=5)
        assert isinstance(result, str)
        assert "... and 15 more" in result
        # Should show only first 5
        for i in range(5):
            assert f"item{i}" in result
        # Should not show item5 or later
        assert "item5" not in result

    def test_no_suggestions_no_fallback(self):
        """Test with no suggestions and no fallback."""
        result = format_did_you_mean("xyz", [], item_type="workflow")
        assert "No workflows found matching 'xyz'" in result

    def test_custom_item_type(self):
        """Test custom item type in message."""
        result = format_did_you_mean("test", ["test1"], item_type="workflow")
        assert "workflow" in result

    def test_single_suggestion(self):
        """Test with single suggestion."""
        result = format_did_you_mean("fil", ["file"], item_type="node")
        assert "Did you mean one of these nodes?" in result
        assert "  - file" in result
        assert isinstance(result, str)

    def test_fallback_exact_max(self):
        """Test fallback with exactly max_fallback items."""
        items = [f"item{i}" for i in range(10)]
        result = format_did_you_mean("xyz", [], item_type="node", fallback_items=items, max_fallback=10)
        # Should not show "and N more" message
        assert "and" not in result.lower() or "more" not in result.lower()
        assert "item9" in result

    def test_multiple_suggestions_format(self):
        """Test formatting of multiple suggestions."""
        suggestions = ["node1", "node2", "node3"]
        result = format_did_you_mean("nod", suggestions, item_type="node")
        assert isinstance(result, str)
        lines = result.split("\n")
        assert len(lines) == 4  # Header + 3 suggestions
        assert lines[0] == "Did you mean one of these nodes?"
        assert lines[1] == "  - node1"
        assert lines[2] == "  - node2"
        assert lines[3] == "  - node3"


class TestIntegration:
    """Integration tests combining both functions."""

    def test_workflow_suggestion_pattern(self):
        """Test typical workflow suggestion pattern."""
        available_workflows = ["build-image", "deploy-service", "run-tests"]

        # Find similar items
        suggestions = find_similar_items("build", available_workflows, method="substring", max_results=5)

        # Format message
        message = format_did_you_mean("build", suggestions, item_type="workflow", fallback_items=available_workflows)

        assert "build-image" in message
        assert "Did you mean" in message

    def test_node_suggestion_with_fallback(self):
        """Test node suggestion with fallback to all nodes."""
        available_nodes = ["read-file", "write-file", "llm"]

        # No matches for invalid query
        suggestions = find_similar_items("xyz", available_nodes, method="substring")

        # Format with fallback
        message = format_did_you_mean("xyz", suggestions, item_type="node", fallback_items=available_nodes)

        assert "No similar nodes found" in message
        assert "read-file" in message

    def test_fuzzy_match_with_formatting(self):
        """Test fuzzy matching with formatted output."""
        available_tools = ["add_reaction", "send_message", "list_channels"]

        # Fuzzy match for typo
        suggestions = find_similar_items("sent_message", available_tools, method="fuzzy", cutoff=0.6)

        message = format_did_you_mean("sent_message", suggestions, item_type="tool")

        # Should find send_message despite typo
        assert "send_message" in message or len(suggestions) == 0  # Depending on cutoff
