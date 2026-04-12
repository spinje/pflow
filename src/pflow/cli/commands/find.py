"""Top-level workflow discovery command."""

from __future__ import annotations

import sys

import click

from pflow.core.workflow.manager import WorkflowManager


@click.command(name="find")
@click.argument("query")
def find_cmd(query: str) -> None:
    """Search saved workflows by intent using LLM.

    Unlike `list` (keyword matching), `find` uses an LLM to understand
    what you're looking for and match it to saved workflows.

    \b
    Examples:
      pflow find "something that fetches github PRs"
      pflow find "workflow for sending slack notifications"
    """
    from pflow.cli.find_errors import handle_discovery_error
    from pflow.core.workflow.discovery import find_workflow
    from pflow.execution.formatters.discovery_formatter import (
        format_discovery_result,
        format_no_matches_with_suggestions,
    )

    validated_query = _validate_discovery_query(query, "find")
    workflow_manager = WorkflowManager()

    try:
        result = find_workflow(validated_query, workflow_manager=workflow_manager)
    except Exception as exception:
        handle_discovery_error(
            exception,
            discovery_type="workflow",
            alternative_commands=[
                ("pflow list", "Show saved workflows"),
                ("pflow describe <name>", "Show workflow details"),
            ],
        )
        sys.exit(1)

    if result.found and result.workflow:
        result_dict = {
            "workflow_name": result.workflow_name,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }
        click.echo(format_discovery_result(result_dict, result.workflow))
        return

    all_workflows = workflow_manager.list_all()
    click.echo(format_no_matches_with_suggestions(all_workflows, validated_query, reasoning=result.reasoning))


def _validate_discovery_query(query: str, command_name: str) -> str:
    """Validate and sanitize a discovery query."""
    query = query.strip()

    if not query:
        click.echo(f"Error: {command_name} query cannot be empty", err=True)
        sys.exit(1)

    if len(query) > 500:
        click.echo(f"Error: Query too long (max 500 characters, got {len(query)})", err=True)
        click.echo("  Please use a more concise description", err=True)
        sys.exit(1)

    return query
