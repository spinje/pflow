"""Tests for workflow list formatter.

This formatter is shared by CLI and MCP interfaces.
"""

from pflow.execution.formatters.workflow_list_formatter import format_workflow_list


class TestWorkflowListFormatter:
    """Tests for the shared workflow list formatter."""

    def test_format_empty_list(self) -> None:
        """Test formatting empty workflow list shows help message."""
        result = format_workflow_list([])

        assert "No workflows saved yet." in result
        assert "To save a workflow:" in result
        assert "Create a .pflow.md workflow file" in result

    def test_format_single_workflow(self) -> None:
        """Test formatting single workflow."""
        workflows = [
            {
                "name": "test-workflow",
                "description": "Test description",
            }
        ]

        result = format_workflow_list(workflows)

        assert "Saved Workflows:" in result
        assert "─" * 40 in result
        assert "test-workflow" in result
        assert "Test description" in result
        assert "Total: 1 workflow" in result  # Singular

    def test_format_multiple_workflows(self) -> None:
        """Test formatting multiple workflows."""
        workflows = [
            {"name": "workflow-1", "description": "First workflow"},
            {"name": "workflow-2", "description": "Second workflow"},
            {"name": "workflow-3", "description": "Third workflow"},
        ]

        result = format_workflow_list(workflows)

        # Check all workflows present
        assert "workflow-1" in result
        assert "First workflow" in result
        assert "workflow-2" in result
        assert "Second workflow" in result
        assert "workflow-3" in result
        assert "Third workflow" in result

        # Check structure
        assert "Saved Workflows:" in result
        assert "─" * 40 in result
        assert "Total: 3 workflows" in result  # Plural

    def test_format_missing_description(self) -> None:
        """Test handling workflow with missing description field."""
        workflows = [
            {"name": "no-desc-workflow"},  # No description field
            {"name": "has-desc-workflow", "description": "Has description"},
        ]

        result = format_workflow_list(workflows)

        # Missing description shows default
        assert "no-desc-workflow" in result
        assert "No description" in result

        # Normal workflow shows description
        assert "has-desc-workflow" in result
        assert "Has description" in result

    def test_pluralization(self) -> None:
        """Test correct pluralization of workflow count."""
        # Singular
        result_one = format_workflow_list([{"name": "single", "description": "One"}])
        assert "Total: 1 workflow" in result_one
        assert "workflows" not in result_one  # Should not have plural

        # Plural
        result_two = format_workflow_list([
            {"name": "first", "description": "First"},
            {"name": "second", "description": "Second"},
        ])
        assert "Total: 2 workflows" in result_two

    def test_format_structure(self) -> None:
        """Test the overall structure of formatted output."""
        workflows = [{"name": "test", "description": "Test"}]

        result = format_workflow_list(workflows)
        lines = result.split("\n")

        # Check structure
        assert lines[0] == "Saved Workflows:"
        assert lines[1] == "─" * 40
        assert any("test" in line for line in lines)
        assert any("Test" in line for line in lines)
        assert lines[-1].startswith("Total:")

    def test_missing_name_field(self) -> None:
        """Test handling workflow with missing name field."""
        workflows = [{"description": "Has description"}]  # No name field

        result = format_workflow_list(workflows)

        # Missing name shows default
        assert "Unknown" in result
        assert "Has description" in result
