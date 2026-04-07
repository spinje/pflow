#!/usr/bin/env python3
"""Baseline capture for Task 144: Diagnostic Rendering Redesign.

Captures rendered text output for every error type through every rendering path.
Run before AND after implementation to produce comparable output for diffing.

Usage:
    uv run python scratchpads/task-144-diagnostic-rendering/capture_baselines.py before
    uv run python scratchpads/task-144-diagnostic-rendering/capture_baselines.py after
    uv run python scratchpads/task-144-diagnostic-rendering/capture_baselines.py compare

Output:
    baselines-{before,after}/
        rendering-output.txt    — rendered text for every fixture x path combination
        context-coverage.txt    — per-fixture context key inventory (available vs rendered)
"""

from __future__ import annotations

import difflib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# pflow imports — keep these at the top so import errors surface immediately
# ---------------------------------------------------------------------------
from pflow.core.diagnostic import (
    Diagnostic,
    Severity,
    exception_to_diagnostics,
    format_diagnostic,
)
from pflow.core.exceptions import (
    CompilationError,
    MarkdownParseError,
    MaxNodeVisitsError,
    SchemaValidationError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from pflow.core.user_errors import MCPError, OutputResolutionError, UserFriendlyError

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

SEPARATOR = "=" * 78
SUBSEP = "-" * 60


@dataclass
class Fixture:
    """One error scenario with its expected context."""

    name: str
    description: str
    # Exactly one of these is set:
    exception: Exception | None = None
    diagnostic: Diagnostic | None = None
    # Context keys the Diagnostic SHOULD have (key -> human description)
    expected_context: dict[str, str] = field(default_factory=dict)
    # Tags for filtering (e.g., "bypass", "wrapper")
    tags: list[str] = field(default_factory=list)


@dataclass
class RenderResult:
    """Output from rendering one fixture through one path."""

    fixture_name: str
    path_name: str
    rendered: str
    # Context coverage analysis
    context_keys_available: list[str] = field(default_factory=list)
    context_keys_rendered: list[str] = field(default_factory=list)
    context_keys_dropped: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fixture construction — every error type with realistic data
# ---------------------------------------------------------------------------


def build_fixtures() -> list[Fixture]:
    """Construct representative error fixtures for every type."""
    fixtures: list[Fixture] = []

    # --- Exception-based fixtures (go through exception_to_diagnostics) ---

    fixtures.append(
        Fixture(
            name="compilation-error",
            description="CompilationError with all fields populated",
            exception=CompilationError(
                message="Node type 'httpp' is not registered",
                phase="node_import",
                node_id="fetch",
                node_type="httpp",
                suggestion="Check available node types with: pflow registry list",
                details={"sub_workflow_path": "./child.pflow.md"},
            ),
            expected_context={
                "category": "The error category (compilation)",
                "phase": "Compilation phase where error occurred (node_import)",
                "node_type": "The invalid node type (httpp)",
                "sub_workflow_path": "Path to sub-workflow (./child.pflow.md)",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="max-visits-error",
            description="MaxNodeVisitsError — infinite loop detection",
            exception=MaxNodeVisitsError(
                node_id="process",
                visit_count=100,
                max_visits=100,
            ),
            expected_context={
                "category": "The error category (max_visits)",
                "visit_count": "How many times the node was visited (100)",
                "max_visits": "The configured limit (100)",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="workflow-validation-error",
            description="WorkflowValidationError with 3 errors (paths + suggestions)",
            exception=WorkflowValidationError(
                summary="Workflow validation failed",
                validation_errors=[
                    Diagnostic(
                        severity=Severity.ERROR,
                        message="Unknown node type 'httpp'",
                        title="Validation Error",
                        suggestions=["Use 'shell', 'http', 'llm', 'file', or 'mcp'"],
                        source="validation",
                        context={"category": "validation", "path": "nodes[0].type"},
                    ),
                    Diagnostic(
                        severity=Severity.ERROR,
                        message="Missing required field 'type'",
                        title="Validation Error",
                        suggestions=["Every node must have a 'type' field"],
                        source="validation",
                        context={"category": "validation", "path": "nodes[1]"},
                    ),
                    Diagnostic(
                        severity=Severity.ERROR,
                        message="Undefined template variable '${api_key}'",
                        title="Validation Error",
                        source="validation",
                        context={"category": "validation", "path": "nodes[2].params.url"},
                    ),
                ],
            ),
            expected_context={
                "category": "The error category (validation)",
                "path": "Location in workflow IR (e.g., nodes[0].type)",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="schema-validation-error",
            description="SchemaValidationError with path and suggestion",
            exception=SchemaValidationError(
                message="'steps' is not a valid section name",
                path="root.sections",
                suggestion="Did you mean '## Steps'? Section names are case-sensitive.",
            ),
            expected_context={
                "category": "The error category (validation)",
                "path": "Schema path (root.sections)",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="markdown-parse-error",
            description="MarkdownParseError with line number and suggestion",
            exception=MarkdownParseError(
                message="Unclosed code fence",
                line=42,
                suggestion="Add a closing ``` to terminate the code block.",
            ),
            expected_context={
                "category": "The error category (parse_error)",
                "line": "Source line number (42)",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="workflow-not-found-with-suggestions",
            description="WorkflowNotFoundError with similar names",
            exception=WorkflowNotFoundError(
                workflow_name="my-workfow",
                similar_names=["my-workflow", "my-workflow-v2"],
            ),
            expected_context={
                "category": "The error category (not_found)",
                "workflow_name": "The name that was looked up (my-workfow)",
                "similar_names": "List of similar workflow names",
                "hint": "Pre-formatted hint message (None here)",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="workflow-not-found-with-hint",
            description="WorkflowNotFoundError with a hint (no similar names)",
            exception=WorkflowNotFoundError(
                workflow_name="missing",
                hint="No saved workflows found. Use 'pflow save' to save a workflow first.",
            ),
            expected_context={
                "category": "The error category (not_found)",
                "workflow_name": "The name that was looked up (missing)",
                "hint": "Pre-formatted hint message",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="output-resolution-error",
            description="OutputResolutionError with per-output failure diagnostics",
            exception=OutputResolutionError(
                failures=[
                    {
                        "output_name": "summary",
                        "source_expr": "${branch-a.result}",
                        "diagnostics": [
                            "Node 'branch-a' did not execute on this path",
                        ],
                        "raw_diagnostics": [{"root_absent": True}],
                    },
                    {
                        "output_name": "details",
                        "source_expr": "${branch-b.response}",
                        "diagnostics": [
                            "Key 'response' not found in node 'branch-b' output",
                        ],
                        "raw_diagnostics": [],
                    },
                ],
                technical_details="branch-a was skipped because condition evaluated to False",
            ),
            expected_context={
                "category": "The error category (runtime)",
                "title": "The error title (2 workflow outputs could not be resolved)",
                "explanation": "Per-output failure details",
                "suggestions": "List of fix suggestions",
                "technical_details": "Technical context (branch condition)",
                "failures": "Full per-output failure list with diagnostics",
                "output_name": "First failure's output name (summary)",
                "source_expr": "First failure's source expression (${branch-a.result})",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="mcp-error",
            description="MCPError with suggestions and technical details",
            exception=MCPError(
                title="MCP tools not available",
                explanation=(
                    "The workflow tried to use MCP tools that aren't registered.\n"
                    "This usually happens when MCP servers haven't been synced."
                ),
                suggestions=[
                    "Check your MCP servers: pflow mcp list",
                    "Sync MCP tools: pflow mcp sync --all",
                    "Verify tools are registered: pflow registry list | grep mcp",
                    "Run your workflow again",
                ],
                technical_details="ModuleNotFoundError: No module named 'mcp_github'",
            ),
            expected_context={
                "category": "The error category (mcp)",
                "title": "Error title (MCP tools not available)",
                "explanation": "Why it failed",
                "suggestions": "List of fix steps",
                "technical_details": "Verbose-only technical info",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="user-friendly-error",
            description="UserFriendlyError with title/explanation/suggestions",
            exception=UserFriendlyError(
                title="API Key Missing",
                explanation="No API key found for the configured LLM provider.",
                suggestions=[
                    "Set your API key: pflow settings set-env OPENAI_API_KEY sk-...",
                    "Or set it as an environment variable: export OPENAI_API_KEY=sk-...",
                ],
                technical_details="KeyError: 'OPENAI_API_KEY' not in os.environ",
            ),
            expected_context={
                "category": "The error category (cli)",
                "title": "Error title",
                "explanation": "Why it failed",
                "suggestions": "Fix steps",
                "technical_details": "Verbose-only details",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="file-not-found-error",
            description="FileNotFoundError — simple OS error",
            exception=FileNotFoundError("workflow.pflow.md"),
            expected_context={
                "category": "The error category (file_not_found)",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="permission-error",
            description="PermissionError — simple OS error",
            exception=PermissionError("Permission denied: /etc/pflow/config"),
            expected_context={
                "category": "The error category (permission_denied)",
            },
        )
    )

    # ValueError with node annotation (runtime execution failure)
    val_err_annotated = ValueError("Invalid JSON response from API")
    val_err_annotated._pflow_node_id = "parse"  # type: ignore[attr-defined]
    fixtures.append(
        Fixture(
            name="valueerror-with-node-annotation",
            description="ValueError during node execution (annotated with _pflow_node_id)",
            exception=val_err_annotated,
            expected_context={
                "category": "The error category (execution_failure)",
            },
        )
    )

    # ValueError without annotation (validation context)
    fixtures.append(
        Fixture(
            name="valueerror-without-annotation",
            description="ValueError without node annotation (validation context)",
            exception=ValueError("Missing required field 'type' in node configuration"),
            expected_context={
                "category": "The error category (validation)",
            },
        )
    )

    # Generic exception (TypeError)
    type_err = TypeError("Expected str, got int for parameter 'count'")
    type_err._pflow_node_id = "transform"  # type: ignore[attr-defined]
    fixtures.append(
        Fixture(
            name="generic-exception-typeerror",
            description="Unexpected TypeError during node execution",
            exception=type_err,
            expected_context={
                "category": "The error category (execution_failure)",
                "exception_type": "The Python exception class name (TypeError)",
            },
        )
    )

    # --- Diagnostic-based fixtures (constructed directly, e.g., from build_error_list) ---

    fixtures.append(
        Fixture(
            name="runtime-shell-error",
            description="Runtime shell command failure (from build_error_list enrichment)",
            diagnostic=Diagnostic(
                severity=Severity.ERROR,
                message="Command failed with exit code 1",
                node_id="deploy",
                source="runtime",
                context={
                    "category": "execution_failure",
                    "action": "error",
                    "shell_command": "npm run build && npm run deploy",
                    "shell_exit_code": 1,
                    "shell_stdout": "Building project...\nBuild complete.",
                    "shell_stderr": "Error: Cannot find module 'react'\n  at Function.Module._resolveFilename",
                },
            ),
            expected_context={
                "category": "execution_failure",
                "action": "Action result string",
                "shell_command": "The shell command that ran",
                "shell_exit_code": "Exit code (1)",
                "shell_stdout": "Standard output from the command",
                "shell_stderr": "Standard error from the command",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="runtime-api-error",
            description="Runtime HTTP API failure (from build_error_list enrichment)",
            diagnostic=Diagnostic(
                severity=Severity.ERROR,
                message="HTTP request failed with status 422",
                node_id="create-issue",
                source="runtime",
                context={
                    "category": "api_validation",
                    "action": "error",
                    "status_code": 422,
                    "raw_response": {
                        "errors": [
                            {"field": "title", "message": "Title is required"},
                            {"field": "labels", "message": "Invalid label: 'urgent'"},
                        ],
                        "documentation_url": "https://docs.github.com/rest/issues",
                    },
                },
            ),
            expected_context={
                "category": "api_validation",
                "action": "Action result",
                "status_code": "HTTP status code (422)",
                "raw_response": "Full API response with error details",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="runtime-mcp-error",
            description="Runtime MCP tool failure (from build_error_list enrichment)",
            diagnostic=Diagnostic(
                severity=Severity.ERROR,
                message="MCP tool 'search_issues' returned an error",
                node_id="mcp-jira-search_issues",
                source="runtime",
                context={
                    "category": "execution_failure",
                    "action": "error",
                    "mcp_error": {
                        "details": {
                            "field": "jql",
                            "expected": "valid JQL query",
                            "received": "project = INVALID",
                        },
                    },
                },
            ),
            expected_context={
                "category": "execution_failure",
                "action": "Action result",
                "mcp_error": "MCP error details (field, expected, received)",
            },
        )
    )

    fixtures.append(
        Fixture(
            name="runtime-template-error",
            description="Runtime template resolution failure (from build_error_list enrichment)",
            diagnostic=Diagnostic(
                severity=Severity.ERROR,
                message="Undefined variable '${api_key}' in node 'fetch'",
                node_id="fetch",
                source="runtime",
                context={
                    "category": "template_error",
                    "action": "error",
                    "available_fields": ["stdout", "stderr", "exit_code", "result", "response"],
                    "available_fields_total": 12,
                    "available_fields_truncated": True,
                },
            ),
            expected_context={
                "category": "template_error",
                "action": "Action result",
                "available_fields": "Top-5 fields available in the node namespace",
                "available_fields_total": "Total number of fields (12)",
                "available_fields_truncated": "Whether the list was truncated",
            },
        )
    )

    # --- Warning fixture (for completeness — warnings have one path) ---

    fixtures.append(
        Fixture(
            name="warning-with-suggestion",
            description="Parser warning with suggestion (single rendering path)",
            diagnostic=Diagnostic(
                severity=Severity.WARNING,
                message="Section heading '## Input' looks like a typo",
                suggestions=["Rename to '## Inputs' (plural) for it to be recognized."],
                source="parser",
                node_id=None,
                context={"template": "## Input"},
            ),
            expected_context={
                "template": "The template string that triggered the warning",
            },
            tags=["warning"],
        )
    )

    fixtures.append(
        Fixture(
            name="warning-with-node-id",
            description="Validator warning attached to a specific node",
            diagnostic=Diagnostic(
                severity=Severity.WARNING,
                message="Cache enabled but node has side effects",
                suggestions=["Consider adding 'cache: false' to this node."],
                source="validator",
                node_id="send-alert",
            ),
            expected_context={},
            tags=["warning"],
        )
    )

    return fixtures


# ---------------------------------------------------------------------------
# Rendering paths
# ---------------------------------------------------------------------------


def fixture_to_diagnostics(fixture: Fixture) -> list[Diagnostic]:
    """Convert a fixture to Diagnostics using the appropriate path."""
    if fixture.diagnostic is not None:
        return [fixture.diagnostic]
    if fixture.exception is not None:
        return exception_to_diagnostics(fixture.exception)
    raise ValueError(f"Fixture {fixture.name} has neither exception nor diagnostic")


def render_core(fixtures: list[Fixture]) -> list[RenderResult]:
    """Render every fixture through format_diagnostic() with param variations."""
    results: list[RenderResult] = []

    for fixture in fixtures:
        diagnostics = fixture_to_diagnostics(fixture)

        for i, diag in enumerate(diagnostics):
            suffix = f" [{i + 1}/{len(diagnostics)}]" if len(diagnostics) > 1 else ""

            # Default params
            results.append(
                _render_and_analyze(
                    fixture_name=f"{fixture.name}{suffix}",
                    path_name="format_diagnostic()",
                    diagnostic=diag,
                    rendered=format_diagnostic(diag),
                )
            )

            # With verbose=True (only meaningful for errors with technical_details)
            if diag.severity == Severity.ERROR:
                verbose_out = format_diagnostic(diag, verbose=True)
                default_out = format_diagnostic(diag)
                if verbose_out != default_out:
                    results.append(
                        _render_and_analyze(
                            fixture_name=f"{fixture.name}{suffix}",
                            path_name="format_diagnostic(verbose=True)",
                            diagnostic=diag,
                            rendered=verbose_out,
                        )
                    )

            # With error_number=1 (only for errors)
            if diag.severity == Severity.ERROR:
                numbered_out = format_diagnostic(diag, error_number=1)
                default_out = format_diagnostic(diag)
                if numbered_out != default_out:
                    results.append(
                        _render_and_analyze(
                            fixture_name=f"{fixture.name}{suffix}",
                            path_name="format_diagnostic(error_number=1)",
                            diagnostic=diag,
                            rendered=numbered_out,
                        )
                    )

    return results


def render_wrappers(fixtures: list[Fixture]) -> list[RenderResult]:
    """Render through wrapper functions that add context around format_diagnostic()."""
    results: list[RenderResult] = []

    # --- format_validation_failure (current: takes list[str]) ---
    from pflow.execution.formatters.validation_formatter import format_validation_failure

    results.append(
        RenderResult(
            fixture_name="validation-failure-3-errors",
            path_name="format_validation_failure(3 errors)",
            rendered=format_validation_failure([
                Diagnostic(
                    severity=Severity.ERROR,
                    message="Unknown node type 'httpp'",
                    title="Validation Error",
                    source="validation",
                    context={"category": "validation"},
                ),
                Diagnostic(
                    severity=Severity.ERROR,
                    message="Missing required field 'type'",
                    title="Validation Error",
                    source="validation",
                    context={"category": "validation"},
                ),
                Diagnostic(
                    severity=Severity.ERROR,
                    message="Undefined template variable '${api_key}'",
                    title="Validation Error",
                    source="validation",
                    context={"category": "validation"},
                ),
            ]),
        )
    )
    results.append(
        RenderResult(
            fixture_name="validation-failure-15-errors",
            path_name="format_validation_failure(15 errors, truncation)",
            rendered=format_validation_failure([
                Diagnostic(
                    severity=Severity.ERROR,
                    message=f"Validation error {i}",
                    title="Validation Error",
                    source="validation",
                    context={"category": "validation"},
                )
                for i in range(15)
            ]),
        )
    )

    # --- _build_error_text (MCP error text generation) ---
    from pflow.mcp_server.services.execution_service import _build_error_text

    # Single error with warnings
    single_errors = [
        Diagnostic(
            severity=Severity.ERROR,
            message="Command failed with exit code 1",
            title="Execution Failed",
            node_id="deploy",
            source="runtime",
            context={
                "category": "execution_failure",
                "shell_command": "npm run deploy",
                "shell_stderr": "Error: EACCES permission denied",
            },
        )
    ]
    single_warnings = [
        Diagnostic(
            severity=Severity.WARNING,
            message="Cache enabled but node has side effects",
            suggestions=["Consider adding 'cache: false' to this node."],
            source="validator",
            node_id="send-alert",
        )
    ]
    results.append(
        RenderResult(
            fixture_name="mcp-error-text-single-error",
            path_name="_build_error_text(1 error + 1 warning)",
            rendered=_build_error_text(single_errors, single_warnings),
        )
    )

    # Multiple errors
    multi_errors = [
        Diagnostic(
            severity=Severity.ERROR,
            message="Node 'fetch' failed: timeout",
            title="Execution Failed",
            node_id="fetch",
            source="runtime",
            context={"category": "execution_failure"},
        ),
        Diagnostic(
            severity=Severity.ERROR,
            message="Node 'parse' failed: invalid JSON",
            title="Execution Failed",
            node_id="parse",
            source="runtime",
            context={"category": "execution_failure"},
        ),
        Diagnostic(
            severity=Severity.ERROR,
            message="Node 'deploy' skipped: upstream failure",
            title="Execution Failed",
            node_id="deploy",
            source="runtime",
            context={"category": "execution_failure"},
        ),
    ]
    results.append(
        RenderResult(
            fixture_name="mcp-error-text-multi-error",
            path_name="_build_error_text(3 errors + 0 warnings)",
            rendered=_build_error_text(multi_errors, []),
        )
    )

    # --- format_success_as_text with warnings ---
    from pflow.execution.formatters.success_formatter import format_success_as_text

    success_dict_with_warnings = {
        "success": True,
        "status": "degraded",
        "result": {"summary": "Analysis complete"},
        "workflow": {"name": "analyze", "action": "reused"},
        "duration_ms": 1234,
        "total_cost_usd": 0.0042,
        "nodes_executed": 3,
        "warnings": [
            {
                "severity": "warning",
                "message": "Section heading '## Input' looks like a typo",
                "suggestion": "Rename to '## Inputs'.",
                "source": "parser",
            },
            {
                "severity": "warning",
                "message": "Cache enabled but node has side effects",
                "source": "validator",
                "node_id": "send-alert",
            },
        ],
        "diagnostics": [],
        "execution": {
            "duration_ms": 1234,
            "nodes_executed": 3,
            "nodes_total": 3,
            "steps": [
                {"node_id": "fetch", "status": "completed", "duration_ms": 400},
                {"node_id": "process", "status": "completed", "duration_ms": 600},
                {"node_id": "send-alert", "status": "completed", "duration_ms": 234},
            ],
        },
        "metrics": {"workflow": {"total_tokens": 1500}},
    }
    success_warning_diagnostics = [
        Diagnostic(
            severity=Severity.WARNING,
            message="Section heading '## Input' looks like a typo",
            suggestions=["Rename to '## Inputs'."],
            source="parser",
        ),
        Diagnostic(
            severity=Severity.WARNING,
            message="Cache enabled but node has side effects",
            source="validator",
            node_id="send-alert",
        ),
    ]
    results.append(
        RenderResult(
            fixture_name="success-text-with-warnings",
            path_name="format_success_as_text(2 warnings)",
            rendered=format_success_as_text(
                success_dict_with_warnings,
                warning_diagnostics=success_warning_diagnostics,
            ),
        )
    )

    return results


def render_bypasses(fixtures: list[Fixture]) -> list[RenderResult]:
    """Render registry error scenarios through the diagnostic pipeline.

    Previously these used bypass formatters (registry_run_formatter.py).
    Now they all go through format_diagnostic() — this section verifies
    the new output matches or improves on the old.
    """
    from pflow.core.suggestion_utils import find_similar_items

    results: list[RenderResult] = []

    # --- Node not found (was format_node_not_found_error) ---
    available_nodes = ["read-file", "read-url", "write-file", "shell", "http", "llm"]
    similar = find_similar_items("read-fle", available_nodes, max_results=5, method="substring")
    # When no fuzzy matches, show available nodes (same logic as _handle_unknown_node)
    if not similar:
        similar = sorted(available_nodes)[:10]
    not_found_diag = Diagnostic(
        severity=Severity.ERROR,
        message="Node 'read-fle' not found in registry.",
        title="Node Not Found",
        suggestions=[
            "Use 'pflow registry discover' to search for nodes",
            "Use 'pflow registry list' to see all available nodes",
        ],
        source="registry",
        context={"category": "not_found", "similar_names": similar},
    )
    results.append(
        RenderResult(
            fixture_name="registry-node-not-found",
            path_name="format_diagnostic(node-not-found)",
            rendered=format_diagnostic(not_found_diag),
        )
    )

    # --- Execution errors (was format_execution_error) ---
    # Simulate the enrichment that _handle_execution_error does in registry_run.py
    from dataclasses import replace as dc_replace

    node_type = "fetch"
    for exc, label in [
        (FileNotFoundError("input.txt"), "FileNotFoundError"),
        (PermissionError("Permission denied: /etc/pflow"), "PermissionError"),
        (ValueError("Required parameter 'url' is missing"), "ValueError-required"),
        (RuntimeError("Connection timeout after 30s"), "timeout"),
        (RuntimeError("Unexpected error in node execution"), "generic"),
    ]:
        diagnostics = exception_to_diagnostics(exc)
        for diag in diagnostics:
            # Enrich with registry-run suggestions (same logic as _registry_run_suggestions)
            extra = list(diag.suggestions or [])
            if not isinstance(exc, (FileNotFoundError, PermissionError)):
                if isinstance(exc, ValueError) and "required" in str(exc).lower():
                    extra.append(f"Use 'pflow registry describe {node_type}' to see required parameters")
                elif "timeout" in str(exc).lower():
                    extra.append("Try increasing timeout if supported")
                    extra.append(f"Use 'pflow registry describe {node_type}' to check parameters")
                else:
                    extra.append(f"Use 'pflow registry describe {node_type}' to see required parameters")
            enriched = dc_replace(diag, node_id=diag.node_id or node_type, suggestions=extra or None)
            results.append(
                RenderResult(
                    fixture_name=f"registry-exec-error-{label}",
                    path_name=f"exception_to_diagnostics({label})",
                    rendered=format_diagnostic(enriched),
                )
            )

    # --- Ambiguous node (was format_ambiguous_node_error) ---
    matches = ["mcp-github-search", "mcp-jira-search", "mcp-confluence-search"]
    ambiguous_diag = Diagnostic(
        severity=Severity.ERROR,
        message="Ambiguous node name 'search'. Found in multiple servers.",
        title="Ambiguous Node Name",
        suggestions=[
            f"Specify the full node ID (e.g., '{matches[0]}')",
            "Use format: {server}-{tool}",
        ],
        source="registry",
        context={"category": "not_found", "similar_names": sorted(matches)},
    )
    results.append(
        RenderResult(
            fixture_name="registry-ambiguous-node",
            path_name="format_diagnostic(ambiguous-node)",
            rendered=format_diagnostic(ambiguous_diag),
        )
    )

    return results


# ---------------------------------------------------------------------------
# Context coverage analysis
# ---------------------------------------------------------------------------


def _render_and_analyze(
    fixture_name: str,
    path_name: str,
    diagnostic: Diagnostic,
    rendered: str,
) -> RenderResult:
    """Render a diagnostic and analyze which context keys appear in the output."""
    context = diagnostic.context or {}
    available = sorted(context.keys())
    rendered_keys = []
    dropped_keys = []

    for key in available:
        value = context[key]
        # Check if the VALUE appears in the rendered text
        # For dicts/lists, check if any leaf value appears
        if _value_appears_in_text(value, rendered):
            rendered_keys.append(key)
        else:
            dropped_keys.append(key)

    return RenderResult(
        fixture_name=fixture_name,
        path_name=path_name,
        rendered=rendered,
        context_keys_available=available,
        context_keys_rendered=rendered_keys,
        context_keys_dropped=dropped_keys,
    )


def _value_appears_in_text(value: Any, text: str) -> bool:
    """Check if a context value appears anywhere in the rendered text."""
    if value is None:
        return False
    if isinstance(value, bool):
        return str(value) in text
    if isinstance(value, (int, float)):
        return str(value) in text
    if isinstance(value, str):
        # For multi-line strings, check if any line appears
        for line in value.split("\n"):
            stripped = line.strip()
            if stripped and stripped in text:
                return True
        # Also check the full string
        return value in text
    if isinstance(value, list):
        # Check if any list item appears
        return any(_value_appears_in_text(item, text) for item in value)
    if isinstance(value, dict):
        # Check if any dict value appears
        return any(_value_appears_in_text(v, text) for v in value.values())
    return str(value) in text


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def write_rendering_output(results: list[RenderResult], output_path: Path) -> None:
    """Write all rendered outputs to a structured text file."""
    lines: list[str] = []
    lines.append("DIAGNOSTIC RENDERING BASELINE CAPTURE")
    lines.append(f"Total outputs: {len(results)}")
    lines.append("")

    current_fixture = ""
    for result in results:
        if result.fixture_name != current_fixture:
            current_fixture = result.fixture_name
            lines.append("")
            lines.append(SEPARATOR)
            lines.append(f"  {current_fixture}")
            lines.append(SEPARATOR)

        lines.append("")
        lines.append(f"--- {result.path_name} ---")
        lines.append("")
        # Indent the rendered output for clarity
        for line in result.rendered.split("\n"):
            lines.append(f"  {line}" if line else "")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Wrote {output_path} ({len(results)} outputs)")


def write_context_coverage(results: list[RenderResult], output_path: Path) -> None:
    """Write context key coverage analysis."""
    lines: list[str] = []
    lines.append("CONTEXT KEY COVERAGE ANALYSIS")
    lines.append("")
    lines.append("For each fixture, shows which context keys from the Diagnostic")
    lines.append("are rendered in text vs silently dropped.")
    lines.append("")

    # Only include results that have context analysis (core rendering, default params)
    analyzed = [r for r in results if r.context_keys_available]

    # Summary stats
    total_available = sum(len(r.context_keys_available) for r in analyzed)
    total_rendered = sum(len(r.context_keys_rendered) for r in analyzed)
    total_dropped = sum(len(r.context_keys_dropped) for r in analyzed)
    if total_available > 0:
        pct = total_rendered / total_available * 100
        lines.append(f"SUMMARY: {total_rendered}/{total_available} context keys rendered ({pct:.0f}%)")
        lines.append(f"         {total_dropped} keys silently dropped")
    lines.append("")

    current_fixture = ""
    for result in analyzed:
        if result.fixture_name != current_fixture:
            current_fixture = result.fixture_name
            lines.append(SEPARATOR)
            lines.append(f"  {current_fixture}")
            lines.append(SEPARATOR)

        lines.append(f"  Path: {result.path_name}")

        if result.context_keys_rendered:
            lines.append(f"  Rendered ({len(result.context_keys_rendered)}):")
            for key in result.context_keys_rendered:
                lines.append(f"    + {key}")

        if result.context_keys_dropped:
            lines.append(f"  DROPPED ({len(result.context_keys_dropped)}):")
            for key in result.context_keys_dropped:
                lines.append(f"    - {key}")

        if not result.context_keys_available:
            lines.append("  (no context keys)")

        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Wrote {output_path} ({len(analyzed)} fixtures analyzed)")


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def compare_baselines(base_dir: Path) -> None:
    """Diff before vs after baselines."""
    before_dir = base_dir / "baselines-before"
    after_dir = base_dir / "baselines-after"

    if not before_dir.exists():
        print("ERROR: baselines-before/ not found. Run with 'before' first.")
        sys.exit(1)
    if not after_dir.exists():
        print("ERROR: baselines-after/ not found. Run with 'after' first.")
        sys.exit(1)

    for filename in ["rendering-output.txt", "context-coverage.txt"]:
        before_file = before_dir / filename
        after_file = after_dir / filename

        if not before_file.exists() or not after_file.exists():
            print(f"  SKIP: {filename} missing in one of the directories")
            continue

        before_lines = before_file.read_text(encoding="utf-8").splitlines()
        after_lines = after_file.read_text(encoding="utf-8").splitlines()

        diff = list(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"before/{filename}",
                tofile=f"after/{filename}",
                lineterm="",
            )
        )

        if diff:
            print(f"\n{'=' * 78}")
            print(f"  DIFF: {filename}")
            print(f"{'=' * 78}")
            for line in diff:
                print(line)
        else:
            print(f"  {filename}: NO CHANGES")

    # Context coverage comparison
    _compare_coverage(before_dir, after_dir)


def _compare_coverage(before_dir: Path, after_dir: Path) -> None:
    """Compare context coverage between before and after."""
    before_file = before_dir / "context-coverage.txt"
    after_file = after_dir / "context-coverage.txt"

    if not before_file.exists() or not after_file.exists():
        return

    before_text = before_file.read_text(encoding="utf-8")
    after_text = after_file.read_text(encoding="utf-8")

    # Extract summary lines
    for label, text in [("BEFORE", before_text), ("AFTER", after_text)]:
        for line in text.splitlines():
            if line.startswith("SUMMARY:"):
                print(f"  {label} {line}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("before", "after", "compare"):
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]
    base_dir = Path(__file__).parent

    if mode == "compare":
        compare_baselines(base_dir)
        return

    output_dir = base_dir / f"baselines-{mode}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Capturing baselines ({mode})...")

    # Build fixtures
    fixtures = build_fixtures()
    print(f"  {len(fixtures)} fixtures constructed")

    # Render through all paths
    all_results: list[RenderResult] = []

    core_results = render_core(fixtures)
    print(f"  Core rendering: {len(core_results)} outputs")
    all_results.extend(core_results)

    wrapper_results = render_wrappers(fixtures)
    print(f"  Wrapper rendering: {len(wrapper_results)} outputs")
    all_results.extend(wrapper_results)

    bypass_results = render_bypasses(fixtures)
    print(f"  Bypass rendering: {len(bypass_results)} outputs")
    all_results.extend(bypass_results)

    print(f"  Total: {len(all_results)} outputs")

    # Write output files
    write_rendering_output(all_results, output_dir / "rendering-output.txt")
    write_context_coverage(all_results, output_dir / "context-coverage.txt")

    print(f"\nDone. Results in {output_dir}/")


if __name__ == "__main__":
    main()
