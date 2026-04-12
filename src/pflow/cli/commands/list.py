"""Top-level workflow listing command."""

from __future__ import annotations

import json
from typing import Any

import click

from pflow.core.workflow.manager import WorkflowManager


@click.command(name="list")
@click.argument("keywords", nargs=-1)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_cmd(keywords: tuple[str, ...], output_json: bool) -> None:
    """List saved workflows, optionally filtered by keywords.

    Examples:
      pflow list
      pflow list github
      pflow list github pr
      pflow list --json
    """
    workflow_manager = WorkflowManager()
    all_workflows = workflow_manager.list_all()
    workflows = all_workflows

    if keywords:
        workflows = [workflow for workflow in all_workflows if _matches_all_keywords(workflow, keywords)]

        if not workflows and all_workflows and not output_json:
            joined_keywords = " ".join(keywords)
            plural = "workflow" if len(all_workflows) == 1 else "workflows"
            click.echo(f"No workflows match filter: '{joined_keywords}'", err=True)
            click.echo(f"\nFound {len(all_workflows)} total {plural}. Try:", err=True)
            click.echo("  - Broader keywords: Use fewer or different terms", err=True)
            click.echo("  - List all: pflow list", err=True)
            click.echo('  - Semantic search: pflow find "your task description"', err=True)
            return

    if output_json:
        workflows_summary = [{key: value for key, value in workflow.items() if key != "ir"} for workflow in workflows]
        click.echo(json.dumps(workflows_summary, indent=2))
        return

    from pflow.execution.formatters.workflow_list_formatter import format_workflow_list

    if keywords:
        highlighted = [_highlight_workflow(workflow, keywords) for workflow in workflows]
        click.echo(format_workflow_list(highlighted))
        return

    click.echo(format_workflow_list(workflows))


def _matches_all_keywords(workflow: dict[str, Any], keywords: tuple[str, ...]) -> bool:
    name = str(workflow.get("name", ""))
    description = str(workflow.get("description", ""))
    return all(_matches_keyword(keyword, name) or _matches_keyword(keyword, description) for keyword in keywords)


def _matches_keyword(keyword: str, text: str) -> bool:
    if keyword == keyword.lower():
        return keyword in text.lower()
    return keyword in text


def _highlight_workflow(workflow: dict[str, Any], keywords: tuple[str, ...]) -> dict[str, Any]:
    highlighted = dict(workflow)
    highlighted["name"] = _highlight_matches(str(workflow.get("name", "")), keywords)
    highlighted["description"] = _highlight_matches(str(workflow.get("description", "No description")), keywords)
    return highlighted


def _highlight_matches(text: str, keywords: tuple[str, ...]) -> str:
    highlighted_text = text
    for keyword in keywords:
        highlighted_text = _highlight_keyword(highlighted_text, keyword)
    return highlighted_text


def _highlight_keyword(text: str, keyword: str) -> str:
    if not keyword:
        return text

    search_text = text if keyword != keyword.lower() else text.lower()
    search_keyword = keyword if keyword != keyword.lower() else keyword.lower()

    index = 0
    segments: list[str] = []
    while True:
        match_index = search_text.find(search_keyword, index)
        if match_index == -1:
            segments.append(text[index:])
            break
        segments.append(text[index:match_index])
        matched_text = text[match_index : match_index + len(keyword)]
        segments.append(click.style(matched_text, bold=True))
        index = match_index + len(keyword)
    return "".join(segments)
