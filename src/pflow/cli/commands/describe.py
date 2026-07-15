"""Top-level workflow describe command."""

from __future__ import annotations

import shlex
import sys
from typing import NoReturn

import click

from pflow.core.workflow.manager import WorkflowManager


@click.command(name="describe")
@click.argument("name", metavar="NAME_OR_PATH")
def describe_cmd(name: str) -> None:
    """Show a saved or local workflow's inputs, outputs, and example usage.

    \b
    Examples:
      pflow describe my-workflow
      pflow describe ./drafts/fetch-github-prs.pflow.md
    """
    from pflow.cli.workflow_interface import format_workflow_interface_for_cli
    from pflow.core.exceptions import WorkflowNotFoundError
    from pflow.core.user_errors import UserFriendlyError
    from pflow.execution.workflow_resolver import resolve_workflow

    workflow_manager = WorkflowManager()
    example_name = name
    if workflow_manager.exists(name):
        metadata = workflow_manager.load(name)
    else:
        try:
            resolved = resolve_workflow(name, workflow_manager)
        except WorkflowNotFoundError as e:
            if e.hint:
                raise
            _handle_workflow_not_found(name, workflow_manager)
        except (OSError, UnicodeError) as e:
            raise UserFriendlyError(
                title="Could not read workflow file",
                explanation=f"pflow could not read '{name}': {e}",
                suggestions=["Check that the path points to a readable UTF-8 .pflow.md file."],
                technical_details=repr(e),
            ) from e
        if resolved.source != "file":
            _handle_workflow_not_found(name, workflow_manager)
        metadata = {"ir": resolved.ir, "description": resolved.description or "No description"}
        example_name = shlex.quote(name)

    formatted = format_workflow_interface_for_cli(name, metadata, example_name=example_name)
    click.echo(formatted)


def _handle_workflow_not_found(name: str, workflow_manager: WorkflowManager) -> NoReturn:
    all_names = workflow_manager.list_names()
    similar = [n for n in all_names if name.lower() in n.lower()][:3]
    click.echo(f"Error: Workflow '{name}' not found.", err=True)
    if similar:
        click.echo(f"  Did you mean: {', '.join(similar)}", err=True)
    sys.exit(1)
