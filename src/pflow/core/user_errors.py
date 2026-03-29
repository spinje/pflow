"""User-friendly error formatting for pflow.

This module provides base classes and utilities for creating clear, actionable
error messages that help users resolve issues independently.
"""

from typing import Any, Optional


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


class OutputResolutionError(UserFriendlyError):
    """Error when workflow output source expressions cannot be resolved."""

    def __init__(
        self,
        failures: list[dict[str, Any]],
        technical_details: Optional[str] = None,
    ):
        self.failures = failures

        count = len(failures)
        title = f"{count} workflow output{'s' if count != 1 else ''} could not be resolved"

        # Build explanation from per-output diagnostics
        lines: list[str] = []
        for f in failures:
            lines.append(f"  Output '{f['output_name']}' (source: {f['source_expr']}):")
            for diag in f.get("diagnostics", []):
                lines.append(f"    - {diag}")
        explanation = "\n".join(lines)

        # Suggest ?? only when at least one variable's root node is absent
        suggestions: list[str] = []
        has_absent_root = any(d.get("root_absent") for f in failures for d in f.get("raw_diagnostics", []))
        if has_absent_root:
            suggestions.append(
                "Use the ?? coalesce operator for branch-dependent outputs: "
                "source: ${branch-a.result ?? branch-b.result}"
            )
        suggestions.append("Check that source expressions reference nodes that always execute on this path")

        super().__init__(title, explanation, suggestions, technical_details)
