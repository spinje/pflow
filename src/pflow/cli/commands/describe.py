"""Top-level workflow describe command."""

from __future__ import annotations

import sys

import click

from pflow.core.workflow.manager import WorkflowManager


@click.command(name="describe")
@click.argument("name")
def describe_cmd(name: str) -> None:
    """Show workflow interface — inputs, outputs, and example usage.

    \b
    Examples:
      pflow describe my-workflow
      pflow describe fetch-github-prs
    """
    from pflow.execution.formatters.workflow_describe_formatter import format_workflow_interface

    workflow_manager = WorkflowManager()
    if not workflow_manager.exists(name):
        _handle_workflow_not_found(name, workflow_manager)

    metadata = workflow_manager.load(name)
    click.echo(format_workflow_interface(name, metadata))


def _handle_workflow_not_found(name: str, workflow_manager: WorkflowManager) -> None:
    all_names = workflow_manager.list_names()
    similar = [n for n in all_names if name.lower() in n.lower()][:3]
    click.echo(f"Error: Workflow '{name}' not found.", err=True)
    if similar:
        click.echo(f"  Did you mean: {', '.join(similar)}", err=True)
    sys.exit(1)
