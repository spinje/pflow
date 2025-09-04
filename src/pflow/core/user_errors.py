"""User-friendly error formatting for pflow.

This module provides base classes and utilities for creating clear, actionable
error messages that help users resolve issues independently.
"""

from typing import Optional


class UserFriendlyError(Exception):
    """Base class for user-friendly errors with structured formatting.

    Every error follows a three-part structure:
    1. WHAT went wrong (title)
    2. WHY it failed (explanation)
    3. HOW to fix it (suggestions)
    """

    def __init__(
        self,
        title: str,
        explanation: str,
        suggestions: Optional[list[str]] = None,
        technical_details: Optional[str] = None,
    ):
        """Initialize a user-friendly error.

        Args:
            title: Brief one-line description of the error
            explanation: Plain language explanation of why it failed
            suggestions: List of actionable steps to fix the issue
            technical_details: Technical information shown with --verbose
        """
        self.title = title
        self.explanation = explanation
        self.suggestions = suggestions or []
        self.technical_details = technical_details

        # Build the base exception message
        message = f"{title}\n\n{explanation}"
        super().__init__(message)

    def format_for_cli(self, verbose: bool = False) -> str:
        """Format the error for CLI display.

        Args:
            verbose: Whether to include technical details

        Returns:
            Formatted error message for terminal display
        """
        lines = []

        # Error title (in red when displayed by CLI)
        lines.append(f"Error: {self.title}")
        lines.append("")

        # Explanation
        if self.explanation:
            lines.append(self.explanation)
            lines.append("")

        # Suggestions
        if self.suggestions:
            if len(self.suggestions) == 1:
                lines.append("To fix this:")
                lines.append(f"  {self.suggestions[0]}")
            else:
                lines.append("To fix this:")
                for i, suggestion in enumerate(self.suggestions, 1):
                    lines.append(f"  {i}. {suggestion}")
            lines.append("")

        # Technical details (only with --verbose)
        if verbose and self.technical_details:
            lines.append("Technical details:")
            lines.append(self.technical_details)
            lines.append("")
        elif not verbose and self.technical_details:
            lines.append("Run with --verbose for technical details.")

        return "\n".join(lines).strip()


class MCPError(UserFriendlyError):
    """Error related to MCP (Model Context Protocol) functionality."""

    def __init__(
        self,
        title: str = "MCP tools not available",
        explanation: Optional[str] = None,
        suggestions: Optional[list[str]] = None,
        technical_details: Optional[str] = None,
    ):
        if explanation is None:
            explanation = (
                "The workflow tried to use MCP tools that aren't registered.\n"
                "This usually happens when MCP servers haven't been synced."
            )

        if suggestions is None:
            suggestions = [
                "Check your MCP servers: pflow mcp list",
                "Sync MCP tools: pflow mcp sync --all",
                "Verify tools are registered: pflow registry list | grep mcp",
                "Run your workflow again",
            ]

        super().__init__(title, explanation, suggestions, technical_details)


class NodeNotFoundError(UserFriendlyError):
    """Error when a node type cannot be found in the registry."""

    def __init__(
        self,
        node_type: str,
        similar_nodes: Optional[list[str]] = None,
        available_count: int = 0,
    ):
        title = f"Unknown node type '{node_type}'"

        # Build explanation with suggestions
        explanation_parts = []

        if similar_nodes:
            explanation_parts.append("Did you mean one of these?")
            for node in similar_nodes[:3]:
                explanation_parts.append(f"  • {node}")
        else:
            explanation_parts.append("No similar nodes found.")

        if available_count > 0:
            explanation_parts.append(f"\n{available_count} nodes are available.")

        explanation = "\n".join(explanation_parts)

        suggestions = ["Check spelling and case (node names are case-sensitive)"]

        # Special handling for MCP nodes
        if node_type.lower().startswith("mcp"):
            suggestions.append("For MCP tools, run: pflow mcp sync --all")

        suggestions.append("See all available nodes: pflow registry list")

        super().__init__(
            title=title,
            explanation=explanation,
            suggestions=suggestions,
        )


class MissingParametersError(UserFriendlyError):
    """Error when required parameters are missing from a request."""

    def __init__(
        self,
        missing_params: list[str],
        context: Optional[str] = None,
    ):
        title = "Need more information to create workflow"

        explanation_parts = ["Your request is missing some details:"]
        for param in missing_params:
            explanation_parts.append(f"  • {param} - {self._get_param_description(param)}")

        if context:
            explanation_parts.append(f"\nContext: {context}")

        explanation = "\n".join(explanation_parts)

        suggestions = [
            "Include specific file names, paths, and values in your request",
            'Example: "analyze the data in sales.csv and save to reports/"',
        ]

        super().__init__(
            title=title,
            explanation=explanation,
            suggestions=suggestions,
        )

    def _get_param_description(self, param: str) -> str:
        """Get user-friendly description for a parameter."""
        descriptions = {
            "file_path": "Which file should be processed?",
            "input_data": "What data should be analyzed?",
            "output_directory": "Where should results be saved?",
            "output_path": "Where should the output file be saved?",
            "api_key": "Your API key for the service",
            "model_name": "Which AI model to use?",
            "channel_id": "Which Slack channel? (e.g., C09C16NAU5B)",
            "message": "What message to send?",
            "content": "What content to process?",
        }
        return descriptions.get(param, f"Please specify the {param.replace('_', ' ')}")


class TemplateVariableError(UserFriendlyError):
    """Error when template variables are undefined."""

    def __init__(
        self,
        missing_variables: list[str],
        workflow_name: Optional[str] = None,
    ):
        title = "Missing workflow variables"

        count = len(missing_variables)
        explanation_parts = [
            f"This workflow needs {count} variable{'s' if count > 1 else ''} that {'were' if count > 1 else 'was'}n't provided:"
        ]

        for var in missing_variables:
            # Remove ${} wrapper if present
            var_name = var.strip("${}")
            explanation_parts.append(f"  • {var_name} - {self._get_var_description(var_name)}")

        explanation = "\n".join(explanation_parts)

        # Build parameter command
        param_examples = []
        for var in missing_variables[:2]:  # Show first 2 as examples
            var_name = var.strip("${}")
            param_examples.append(f"--param {var_name}=<value>")

        suggestions = [
            f"Provide them when running: pflow {workflow_name or 'workflow.json'} {' '.join(param_examples)}",
        ]

        # Add environment variable option
        if len(missing_variables) > 2:
            suggestions.append("Or set them as environment variables (PFLOW_ prefix)")

        super().__init__(
            title=title,
            explanation=explanation,
            suggestions=suggestions,
        )

    def _get_var_description(self, var_name: str) -> str:
        """Get user-friendly description for a variable."""
        descriptions = {
            "api_key": "Your API key for the service",
            "model": "AI model name (e.g., 'gpt-4')",
            "model_name": "AI model name (e.g., 'gpt-4')",
            "file_path": "Path to the input file",
            "output_dir": "Where to save results",
            "base_url": "API endpoint URL",
        }
        return descriptions.get(var_name, f"Value for {var_name.replace('_', ' ')}")


class PlannerError(UserFriendlyError):
    """Error during workflow planning/generation."""

    pass


class CompilationError(UserFriendlyError):
    """Error during workflow compilation."""

    pass
