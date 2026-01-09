"""Tests for workflow discovery result formatting.

Ensures consistent output formatting between CLI and MCP server for both
successful matches and "no matches" cases with suggestions.
"""

from pflow.execution.formatters.discovery_formatter import (
    format_discovery_result,
    format_no_matches_with_suggestions,
    format_workflow_flow,
    format_workflow_inputs_outputs,
    format_workflow_metadata,
)


class TestFormatDiscoveryResult:
    """Test successful discovery result formatting."""

    def test_formats_complete_discovery_result(self):
        """FORMAT: Complete discovery result with all sections."""
        result = {
            "workflow_name": "github-analyzer",
            "confidence": 0.85,
            "reasoning": "Matches PR analysis requirements",
        }
        workflow = {
            "metadata": {"description": "Analyzes GitHub PRs", "version": "1.0.0"},
            "ir": {
                "flow": [
                    {"from": "fetch-pr", "to": "analyze"},
                    {"from": "analyze", "to": "report"},
                ],
                "inputs": {"repo": {"required": True, "type": "string", "description": "Repository name"}},
                "outputs": {"analysis": {"type": "object", "description": "PR analysis"}},
            },
        }

        formatted = format_discovery_result(result, workflow)

        # Verify all sections
        assert "## github-analyzer" in formatted
        assert "**Description**: Analyzes GitHub PRs" in formatted
        assert "**Version**: 1.0.0" in formatted
        # Flow only shows edges, so 2 edges = "fetch-pr >> analyze"
        assert "**Node Flow**: fetch-pr >> analyze" in formatted
        assert "**Inputs**:" in formatted
        assert "repo: string (required) - Repository name" in formatted
        assert "**Outputs**:" in formatted
        assert "analysis: object - PR analysis" in formatted
        assert "**Confidence**: 85%" in formatted
        assert "*Match reasoning*: Matches PR analysis requirements" in formatted


class TestFormatNoMatchesWithSuggestions:
    """Test no matches message formatting with workflow suggestions."""

    def test_limits_workflows_and_shows_remaining_count(self):
        """NO MATCHES: Limits displayed workflows and shows count of remaining."""
        workflows = [{"name": f"workflow-{i}"} for i in range(15)]
        query = "test"

        # Use explicit limit to test the behavior
        formatted = format_no_matches_with_suggestions(workflows, query, max_suggestions=3)

        # Verify header
        assert 'No workflows found matching "test" (minimum 70% confidence).' in formatted

        # First 3 shown
        assert "• workflow-0" in formatted
        assert "• workflow-1" in formatted
        assert "• workflow-2" in formatted

        # 4th not shown
        assert "workflow-3" not in formatted

        # Remaining count displayed
        assert "... and 12 more" in formatted

        # Verify guidance section
        assert "Try:" in formatted
        assert '• More specific query: "workflow for [specific task]"' in formatted
        assert "• Recommendation: Try building a new workflow" in formatted

    def test_formats_with_few_workflows(self):
        """NO MATCHES: Shows all workflows when less than max_suggestions."""
        workflows = [
            {"name": "workflow-a", "description": "First workflow"},
            {"name": "workflow-b", "description": "Second workflow"},
            {"name": "workflow-c", "description": "Third workflow"},
        ]
        query = "find something"

        formatted = format_no_matches_with_suggestions(workflows, query)

        # All 3 workflows should be shown
        assert "• workflow-a" in formatted
        assert "• workflow-b" in formatted
        assert "• workflow-c" in formatted

        # No "... and X more" message
        assert "... and" not in formatted

    def test_formats_with_empty_workflow_list(self):
        """NO MATCHES: Empty list shows different message."""
        workflows = []
        query = "test query"

        formatted = format_no_matches_with_suggestions(workflows, query)

        # Verify header
        assert 'No workflows found matching "test query"' in formatted

        # No "Available workflows" section
        assert "Available workflows:" not in formatted

        # Different guidance for empty library
        assert "• Recommendation: Create your first workflow" in formatted

    def test_shows_names_only(self):
        """NO MATCHES: Shows only workflow names without descriptions."""
        workflows = [
            {
                "name": "my-workflow",
                "description": "This description should not appear in output",
            }
        ]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query)

        # Name should appear
        assert "• my-workflow" in formatted
        # Description should not appear
        assert "This description should not appear" not in formatted

    def test_handles_missing_names(self):
        """NO MATCHES: Missing names show default text."""
        workflows = [
            {"description": "Has description but no name"},  # Missing name
        ]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query)

        assert "• unknown" in formatted

    def test_respects_max_suggestions_parameter(self):
        """NO MATCHES: Respects custom max_suggestions limit."""
        workflows = [{"name": f"workflow-{i}", "description": f"Workflow {i}"} for i in range(10)]
        query = "test"

        # Custom limit of 3
        formatted = format_no_matches_with_suggestions(workflows, query, max_suggestions=3)

        # First 3 workflows shown
        assert "• workflow-0" in formatted
        assert "• workflow-1" in formatted
        assert "• workflow-2" in formatted

        # 4th workflow not shown
        assert "workflow-3" not in formatted

        # Count of remaining
        assert "... and 7 more workflows" in formatted

    def test_formats_singular_remaining_count(self):
        """NO MATCHES: Uses singular 'workflow' when 1 remaining."""
        workflows = [{"name": f"workflow-{i}"} for i in range(4)]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query, max_suggestions=3)

        # 4 workflows, showing 3, 1 remaining
        assert "... and 1 more workflow" in formatted  # Singular
        assert "... and 1 more workflows" not in formatted  # Not plural

    def test_formats_plural_remaining_count(self):
        """NO MATCHES: Uses plural 'workflows' when multiple remaining."""
        workflows = [{"name": f"w-{i}"} for i in range(6)]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query, max_suggestions=3)

        # 6 workflows, showing 3, 3 remaining
        assert "... and 3 more workflows" in formatted  # Plural

    def test_handles_special_characters_in_query(self):
        """NO MATCHES: Query with special chars displayed correctly."""
        workflows = [{"name": "test", "description": "Test workflow"}]
        query = 'test with "quotes" and $special chars'

        formatted = format_no_matches_with_suggestions(workflows, query)

        # Query should be preserved exactly in header
        assert 'No workflows found matching "test with "quotes" and $special chars"' in formatted

    def test_handles_special_characters_in_names(self):
        """NO MATCHES: Names with special chars displayed correctly."""
        workflows = [
            {
                "name": "special-workflow-${var}",
                "description": "Some description",
            }
        ]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query)

        # Special characters in name preserved
        assert "• special-workflow-${var}" in formatted

    def test_includes_reasoning_when_provided(self):
        """NO MATCHES: Shows LLM reasoning when available."""
        workflows = [{"name": "test", "description": "Test workflow"}]
        query = "something random"
        reasoning = "The query is too vague and doesn't match any specific workflow purpose."

        formatted = format_no_matches_with_suggestions(workflows, query, reasoning=reasoning)

        # Reasoning should be displayed
        assert "Why: The query is too vague" in formatted
        assert "doesn't match any specific workflow purpose" in formatted

    def test_omits_reasoning_section_when_none(self):
        """NO MATCHES: No 'Why:' section when reasoning is None."""
        workflows = [{"name": "test", "description": "Test"}]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query, reasoning=None)

        # No 'Why:' section
        assert "Why:" not in formatted

    def test_reasoning_appears_before_suggestions(self):
        """NO MATCHES: Reasoning appears after header but before suggestions."""
        workflows = [{"name": "test", "description": "Test"}]
        query = "test"
        reasoning = "Query is too vague."

        formatted = format_no_matches_with_suggestions(workflows, query, reasoning=reasoning)

        lines = formatted.split("\n")

        # Find line indices
        header_idx = 0  # First line
        why_idx = next(i for i, line in enumerate(lines) if line.startswith("Why:"))
        suggestions_idx = next(i for i, line in enumerate(lines) if "Available workflows:" in line)

        # Verify order: header < why < suggestions
        assert header_idx < why_idx < suggestions_idx


class TestHelperFunctions:
    """Test helper formatting functions."""

    def test_format_workflow_metadata(self):
        """METADATA: Formats description and version."""
        workflow = {"metadata": {"description": "Test workflow", "version": "2.0.0"}}

        lines = format_workflow_metadata(workflow)

        assert "**Description**: Test workflow" in lines
        assert "**Version**: 2.0.0" in lines

    def test_format_workflow_flow_truncates_long_flows(self):
        """FLOW: Truncates flows longer than 3 nodes."""
        ir = {
            "flow": [
                {"from": "node1", "to": "node2"},
                {"from": "node2", "to": "node3"},
                {"from": "node3", "to": "node4"},
                {"from": "node4", "to": "node5"},
            ]
        }

        lines = format_workflow_flow(ir)

        result = "\n".join(lines)
        assert "**Node Flow**: node1 >> node2 >> node3 >> ..." in result
        assert "node4" not in result
        assert "node5" not in result

    def test_format_workflow_inputs_outputs(self):
        """I/O: Formats inputs and outputs sections."""
        ir = {
            "inputs": {"required_param": {"required": True, "type": "string", "description": "Required"}},
            "outputs": {"result": {"type": "object", "description": "Result data"}},
        }

        lines = format_workflow_inputs_outputs(ir)

        result = "\n".join(lines)
        assert "**Inputs**:" in result
        assert "required_param: string (required) - Required" in result
        assert "**Outputs**:" in result
        assert "result: object - Result data" in result


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_query_displays_correctly(self):
        """EDGE: Empty query string handled gracefully."""
        workflows = [{"name": "test", "description": "Test"}]
        query = ""

        formatted = format_no_matches_with_suggestions(workflows, query)

        # Empty query should be shown in quotes
        assert 'No workflows found matching ""' in formatted

    def test_workflows_without_name_key(self):
        """EDGE: Workflows missing 'name' key show 'unknown'."""
        workflows = [{"description": "No name provided"}]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query)

        assert "• unknown" in formatted

    def test_workflows_with_none_values(self):
        """EDGE: None values handled as missing."""
        workflows = [{"name": "test", "description": None}]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query)

        # Name should appear without description
        assert "• test" in formatted


class TestCLIParity:
    """Tests ensuring output matches CLI format exactly."""

    def test_bullet_character_matches_cli(self):
        """PARITY: Uses bullet character (•) like CLI."""
        workflows = [{"name": "test", "description": "Test"}]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query)

        # Verify bullet character
        assert "  • test" in formatted

    def test_guidance_format_matches_cli(self):
        """PARITY: Guidance section format matches CLI."""
        workflows = [{"name": "test", "description": "Test"}]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query)

        # Verify guidance format with bullets
        assert "\nTry:\n" in formatted
        assert "  • More specific query:" in formatted
        assert "  • Recommendation:" in formatted

    def test_section_spacing_matches_cli(self):
        """PARITY: Blank lines between sections match CLI."""
        workflows = [{"name": "test", "description": "Test"}]
        query = "test"

        formatted = format_no_matches_with_suggestions(workflows, query)

        lines = formatted.split("\n")

        # Find key sections
        suggestions_idx = lines.index("Available workflows:")
        try_idx = lines.index("Try:")

        # Verify blank lines before sections
        assert lines[suggestions_idx - 1] == ""  # Blank before suggestions
        assert lines[try_idx - 1] == ""  # Blank before Try section
