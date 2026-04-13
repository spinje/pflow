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
            "description": "Analyzes GitHub PRs",
            "version": "1.0.0",
            "ir": {
                "edges": [
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
        assert "*Why*: Matches PR analysis requirements" in formatted
        assert "Partial match" in formatted


class TestFormatNoMatchesWithSuggestions:
    """Test no matches message formatting with workflow suggestions."""

    def test_limits_workflows_and_shows_remaining_count(self):
        """NO MATCHES: Limits displayed workflows and shows count of remaining."""
        names = [f"workflow-{i}" for i in range(15)]
        query = "test"

        formatted = format_no_matches_with_suggestions(names, query, max_suggestions=3)

        assert 'No workflows found matching "test" (minimum 70% confidence).' in formatted
        assert "• workflow-0" in formatted
        assert "• workflow-1" in formatted
        assert "• workflow-2" in formatted
        assert "workflow-3" not in formatted
        assert "... and 12 more" in formatted
        assert "No match" in formatted
        assert "pflow guide core" in formatted

    def test_formats_with_few_workflows(self):
        """NO MATCHES: Shows all workflows when less than max_suggestions."""
        names = ["workflow-a", "workflow-b", "workflow-c"]
        query = "find something"

        formatted = format_no_matches_with_suggestions(names, query)

        assert "• workflow-a" in formatted
        assert "• workflow-b" in formatted
        assert "• workflow-c" in formatted
        assert "... and" not in formatted

    def test_formats_with_empty_workflow_list(self):
        """NO MATCHES: Empty list shows guidance to build new."""
        formatted = format_no_matches_with_suggestions([], "test query")

        assert 'No workflows found matching "test query"' in formatted
        assert "Available workflows:" not in formatted
        assert "No match" in formatted
        assert "pflow guide core" in formatted

    def test_respects_max_suggestions_parameter(self):
        """NO MATCHES: Respects custom max_suggestions limit."""
        names = [f"workflow-{i}" for i in range(10)]

        formatted = format_no_matches_with_suggestions(names, "test", max_suggestions=3)

        assert "• workflow-0" in formatted
        assert "• workflow-1" in formatted
        assert "• workflow-2" in formatted
        assert "workflow-3" not in formatted
        assert "... and 7 more workflows" in formatted

    def test_formats_singular_remaining_count(self):
        """NO MATCHES: Uses singular 'workflow' when 1 remaining."""
        names = [f"workflow-{i}" for i in range(4)]

        formatted = format_no_matches_with_suggestions(names, "test", max_suggestions=3)

        assert "... and 1 more workflow" in formatted
        assert "... and 1 more workflows" not in formatted

    def test_formats_plural_remaining_count(self):
        """NO MATCHES: Uses plural 'workflows' when multiple remaining."""
        names = [f"w-{i}" for i in range(6)]

        formatted = format_no_matches_with_suggestions(names, "test", max_suggestions=3)

        assert "... and 3 more workflows" in formatted

    def test_handles_special_characters_in_query(self):
        """NO MATCHES: Query with special chars displayed correctly."""
        query = 'test with "quotes" and $special chars'

        formatted = format_no_matches_with_suggestions(["test"], query)

        assert 'No workflows found matching "test with "quotes" and $special chars"' in formatted

    def test_handles_special_characters_in_names(self):
        """NO MATCHES: Names with special chars displayed correctly."""
        formatted = format_no_matches_with_suggestions(["special-workflow-${var}"], "test")

        assert "• special-workflow-${var}" in formatted

    def test_includes_reasoning_when_provided(self):
        """NO MATCHES: Shows LLM reasoning when available."""
        reasoning = "The query is too vague and doesn't match any specific workflow purpose."

        formatted = format_no_matches_with_suggestions(["test"], "something random", reasoning=reasoning)

        assert "Why: The query is too vague" in formatted
        assert "doesn't match any specific workflow purpose" in formatted

    def test_omits_reasoning_section_when_none(self):
        """NO MATCHES: No 'Why:' section when reasoning is None."""
        formatted = format_no_matches_with_suggestions(["test"], "test", reasoning=None)

        assert "Why:" not in formatted

    def test_reasoning_appears_before_suggestions(self):
        """NO MATCHES: Reasoning appears after header but before suggestions."""
        formatted = format_no_matches_with_suggestions(["test"], "test", reasoning="Query is too vague.")

        lines = formatted.split("\n")
        header_idx = 0
        why_idx = next(i for i, line in enumerate(lines) if line.startswith("Why:"))
        suggestions_idx = next(i for i, line in enumerate(lines) if "Available workflows:" in line)

        assert header_idx < why_idx < suggestions_idx


class TestHelperFunctions:
    """Test helper formatting functions."""

    def test_format_workflow_metadata(self):
        """METADATA: Formats description and version."""
        workflow = {"description": "Test workflow", "version": "2.0.0"}

        lines = format_workflow_metadata(workflow)

        assert "**Description**: Test workflow" in lines
        assert "**Version**: 2.0.0" in lines

    def test_format_workflow_flow_truncates_long_flows(self):
        """FLOW: Truncates flows longer than 3 nodes."""
        ir = {
            "edges": [
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
        formatted = format_no_matches_with_suggestions(["test"], "")

        assert 'No workflows found matching ""' in formatted


class TestCLIParity:
    """Tests ensuring output matches CLI format exactly."""

    def test_bullet_character_matches_cli(self):
        """PARITY: Uses bullet character (•) like CLI."""
        formatted = format_no_matches_with_suggestions(["test"], "test")

        assert "  • test" in formatted

    def test_guidance_format_matches_cli(self):
        """PARITY: Guidance section format matches CLI."""
        formatted = format_no_matches_with_suggestions(["test"], "test")

        assert "No match" in formatted
        assert "pflow guide core" in formatted
        assert "pflow find" in formatted

    def test_section_spacing_matches_cli(self):
        """PARITY: Blank lines between sections match CLI."""
        formatted = format_no_matches_with_suggestions(["test"], "test")

        lines = formatted.split("\n")
        suggestions_idx = lines.index("Available workflows:")

        assert lines[suggestions_idx - 1] == ""  # Blank before suggestions
