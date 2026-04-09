"""User-friendly error formatting for pflow.

This module provides base classes and utilities for creating clear, actionable
error messages that help users resolve issues independently.
"""

from __future__ import annotations

from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import PflowError


class UserFriendlyError(PflowError):
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
        suggestions: list[str] | None = None,
        technical_details: str | None = None,
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

    _diagnostic_category: str = "cli"

    def to_diagnostics(self) -> list[Diagnostic]:
        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.explanation,
                title=self.title,
                suggestions=self.suggestions or None,
                source="runtime",
                context={
                    "category": self._diagnostic_category,
                    "explanation": self.explanation,
                    "technical_details": self.technical_details,
                },
            )
        ]


class MCPError(UserFriendlyError):
    """Error related to MCP (Model Context Protocol) functionality."""

    _diagnostic_category: str = "mcp"

    def __init__(
        self,
        title: str = "MCP tools not available",
        explanation: str | None = None,
        suggestions: list[str] | None = None,
        technical_details: str | None = None,
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
    """Error when workflow output source expressions cannot be resolved.

    Produces the same structured Diagnostic format as the node-param
    template error path in ``runtime/engine/template_errors.py``. Fix
    guidance, peer-node suggestions, typo hints, and category-aware
    failure detail all live on the structured ``unresolved_references``
    list — not in the text ``message`` or ``suggestions`` fields.
    """

    def __init__(
        self,
        failures: list[dict[str, Any]],
        technical_details: str | None = None,
    ):
        self.failures = failures

        title = "Template Resolution Failed"
        explanation = _build_output_error_summary(failures)

        # No canned suggestions — the structured renderer emits per-ref
        # fix blocks and a coalesce summary block when appropriate.
        super().__init__(title, explanation, suggestions=None, technical_details=technical_details)

    def to_diagnostics(self) -> list[Diagnostic]:
        # Build per-output structured blocks. Each block carries its own
        # source_line / source_file / template — the renderer iterates
        # them uniformly regardless of single- vs. multi-output case and
        # emits inline ``(at file:line)`` per block. No top-level hoist.
        output_blocks: list[dict[str, Any]] = []
        merged_refs: list[dict[str, Any]] = []
        merged_available_keys: list[str] = []
        seen_keys: set[str] = set()

        for failure in self.failures:
            block_refs: list[dict[str, Any]] = []
            for ref in failure.get("unresolved_references") or []:
                enriched = dict(ref)
                enriched.setdefault("is_output_source", True)
                block_refs.append(enriched)
                merged_refs.append(enriched)
            for key in failure.get("available_context_keys") or []:
                if key not in seen_keys:
                    seen_keys.add(key)
                    merged_available_keys.append(key)
            block: dict[str, Any] = {
                "kind": "output",
                "output_name": failure.get("output_name"),
                "source_expr": failure.get("source_expr"),
                "template": failure.get("template") or failure.get("source_expr"),
                "unresolved_references": block_refs,
            }
            if failure.get("source_line") is not None:
                block["source_line"] = failure["source_line"]
            if failure.get("source_file"):
                block["source_file"] = failure["source_file"]
            output_blocks.append(block)

        if len(output_blocks) == 1:
            param_key = f"output '{output_blocks[0]['output_name']}'"
        else:
            names = ", ".join(f"'{b['output_name']}'" for b in output_blocks)
            param_key = f"outputs {names}"

        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.explanation,
                title="Template Resolution Failed",
                suggestions=None,
                node_id=None,
                source="runtime",
                context={
                    "category": "template_error",
                    "param_key": param_key,
                    "unresolved_references": merged_refs,
                    "available_context_keys": merged_available_keys,
                    "output_failures": output_blocks,
                    "is_output_resolution": True,
                },
            )
        ]


def _build_output_error_summary(failures: list[dict[str, Any]]) -> str:
    """Build a one-line summary for OutputResolutionError.

    Matches the format of ``build_template_error_diagnostic`` in
    ``runtime/engine/template_errors.py`` so both error paths render
    identical-shape messages.
    """
    if not failures:
        return "Unresolved output sources"

    if len(failures) == 1:
        f = failures[0]
        refs = f.get("unresolved_references") or []
        if refs:
            ref_summary = ", ".join(f"${{{r.get('var', '')}}}" for r in refs[:3])
            if len(refs) > 3:
                ref_summary += f" (+{len(refs) - 3} more)"
            return f"Unresolved variables in output '{f['output_name']}': {ref_summary}"
        return f"Unresolved template in output '{f['output_name']}'"

    names = ", ".join(f"'{f['output_name']}'" for f in failures)
    return f"Unresolved variables in outputs {names}"
