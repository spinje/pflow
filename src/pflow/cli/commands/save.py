"""Top-level workflow save command."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from pflow.core.exceptions import MarkdownParseError, WorkflowValidationError


@click.command(name="save")
@click.argument("file_path", type=click.Path(exists=True, readable=True))
@click.option("--name", required=True, help="Workflow name (lowercase-with-hyphens, max 50 chars)")
@click.option("--delete-draft", is_flag=True, help="Delete source file after save")
@click.option("--force", is_flag=True, help="Overwrite existing workflow")
def save_cmd(file_path: str, name: str, delete_draft: bool, force: bool) -> None:
    """Save a workflow file to the library.

    \b
    Examples:
      pflow save workflow.pflow.md --name my-workflow
      pflow save draft.pflow.md --name api-fetcher --delete-draft
      pflow save workflow.pflow.md --name my-workflow --force
    """
    from pflow.core.workflow.save_service import save_workflow_with_options, validate_workflow_name
    from pflow.execution.formatters.workflow_save_formatter import format_save_success

    is_valid, error = validate_workflow_name(name)
    if not is_valid:
        click.echo(f"Error: {error}", err=True)
        sys.exit(1)

    path = Path(file_path)
    if path.suffix == ".json":
        click.echo(
            "Error: JSON workflow format is no longer supported. Use .pflow.md format instead.",
            err=True,
        )
        sys.exit(1)

    metadata = None

    try:
        markdown_content = path.read_text(encoding="utf-8")
        saved_path, bundled_files, workflow_ir = save_workflow_with_options(
            name=name,
            markdown_content=markdown_content,
            force=force,
            metadata=metadata,
            source_path=path,
        )
    except FileExistsError as exception:
        click.echo(f"Error: {exception}", err=True)
        click.echo("  Use --force to overwrite.", err=True)
        sys.exit(1)
    except WorkflowValidationError as exception:
        if exception.validation_errors:
            from pflow.execution.formatters.validation_formatter import format_validation_failure

            click.echo(format_validation_failure(exception.validation_errors), err=True)
        else:
            click.echo(f"Error: {exception}", err=True)
        sys.exit(1)
    except MarkdownParseError as exception:
        click.echo(f"Error: {exception}", err=True)
        sys.exit(1)
    except FileNotFoundError:
        click.echo(f"Error: File not found: {file_path}", err=True)
        sys.exit(1)
    except Exception as exception:
        click.echo(f"Error saving workflow: {exception}", err=True)
        sys.exit(1)

    if force:
        click.echo(f"✓ Overwritten existing workflow '{name}'")

    _delete_draft_if_requested(file_path, delete_draft)

    click.echo(
        format_save_success(
            name=name,
            saved_path=str(saved_path),
            workflow_ir=workflow_ir,
            metadata=metadata,
            bundled_files=bundled_files,
        )
    )


def _delete_draft_if_requested(file_path: str, delete_draft: bool) -> None:
    """Delete the source draft file when requested and safe."""
    if not delete_draft:
        return

    from pflow.core.workflow.save_service import delete_draft_safely

    if delete_draft_safely(file_path):
        click.echo(f"✓ Deleted draft: {file_path}")
    else:
        click.echo(
            f"Warning: Not deleting {file_path} - only files in .pflow/workflows/ can be auto-deleted",
            err=True,
        )
