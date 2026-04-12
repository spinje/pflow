"""Top-level workflow history command."""

from __future__ import annotations

import sys

import click

from pflow.core.workflow.manager import WorkflowManager


@click.command(name="history")
@click.argument("workflow_name")
def history_cmd(workflow_name: str) -> None:
    """Show execution history for a saved workflow.

    Examples:
      pflow history my-workflow
    """
    from pflow.execution.formatters.history_formatter import format_workflow_history

    workflow_manager = WorkflowManager()
    if not workflow_manager.exists(workflow_name):
        _handle_workflow_not_found(workflow_name, workflow_manager)

    metadata = workflow_manager.load(workflow_name)
    click.echo(format_workflow_history(workflow_name, metadata))


def _handle_workflow_not_found(workflow_name: str, workflow_manager: WorkflowManager) -> None:
    all_workflows = workflow_manager.list_all()
    similar = [workflow["name"] for workflow in all_workflows if workflow_name.lower() in workflow["name"].lower()][:3]
    click.echo(f"Error: Workflow '{workflow_name}' not found.", err=True)
    if similar:
        click.echo(f"  Did you mean: {', '.join(similar)}", err=True)
    sys.exit(1)
