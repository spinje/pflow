"""Workflow management commands for pflow CLI."""

import json
import sys
from pathlib import Path
from typing import Any

import click

from pflow.core.exceptions import MarkdownParseError, WorkflowValidationError
from pflow.core.workflow.manager import WorkflowManager


@click.group(name="workflow")
def workflow() -> None:
    """Manage saved workflows."""
    pass


@workflow.command(name="list")
@click.argument("filter_pattern", required=False)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_workflows(filter_pattern: str | None, output_json: bool) -> None:
    """List all saved workflows.

    Filter by keywords (space-separated AND logic):
        pflow workflow list github           # Match "github"
        pflow workflow list "github pr"      # Match BOTH "github" AND "pr"
        pflow workflow list                  # Show all workflows
    """
    wm = WorkflowManager()
    all_workflows = wm.list_all()

    # Track original count for better messaging
    total_count = len(all_workflows)

    # Apply filter if provided (space-separated keywords with AND logic)
    if filter_pattern:
        keywords = [k.strip().lower() for k in filter_pattern.split() if k.strip()]
        workflows = [
            w
            for w in all_workflows
            if all(
                keyword in w.get("name", "").lower() or keyword in w.get("description", "").lower()
                for keyword in keywords
            )
        ]

        # Custom message when filter excludes everything but workflows exist
        if not workflows and total_count > 0 and not output_json:
            plural = "workflow" if total_count == 1 else "workflows"
            click.echo(f"No workflows match filter: '{filter_pattern}'", err=True)
            click.echo(f"\nFound {total_count} total {plural}. Try:", err=True)
            click.echo("  - Broader keywords: Use fewer or different terms", err=True)
            click.echo("  - List all: pflow workflow list", err=True)
            click.echo('  - Discovery: pflow workflow discover "your task description"', err=True)
            return
    else:
        workflows = all_workflows

    if output_json:
        # Exclude 'ir' field from JSON output (too verbose for listing)
        workflows_summary = [{k: v for k, v in w.items() if k != "ir"} for w in workflows]
        click.echo(json.dumps(workflows_summary, indent=2))
    else:
        # Use shared formatter (same as MCP)
        from pflow.execution.formatters.workflow_list_formatter import format_workflow_list

        formatted = format_workflow_list(workflows)
        click.echo(formatted)


def _handle_workflow_not_found(name: str, wm: WorkflowManager) -> None:
    """Handle workflow not found error with suggestions."""
    all_names = [w["name"] for w in wm.list_all()]
    similar = [n for n in all_names if name.lower() in n.lower()][:3]

    click.echo(f"❌ Workflow '{name}' not found.", err=True)
    if similar:
        click.echo("\nDid you mean:", err=True)
        for s in similar:
            click.echo(f"  - {s}", err=True)
    sys.exit(1)


@workflow.command(name="describe")
@click.argument("name")
def describe_workflow(name: str) -> None:
    """Show workflow interface."""
    wm = WorkflowManager()

    # Check if workflow exists
    if not wm.exists(name):
        _handle_workflow_not_found(name, wm)

    # Load workflow metadata
    metadata = wm.load(name)

    # Format using shared formatter (same as MCP)
    from pflow.execution.formatters.workflow_describe_formatter import format_workflow_interface

    formatted = format_workflow_interface(name, metadata)
    click.echo(formatted)


@workflow.command(name="history")
@click.argument("workflow_name")
def workflow_history(workflow_name: str) -> None:
    """Show execution history and last used inputs.

    Useful for finding previously used input values like channel IDs,
    API endpoints, or other parameters that are often reused.

    Example:
        pflow workflow history release-announcements
    """
    wm = WorkflowManager()

    # Check if workflow exists
    if not wm.exists(workflow_name):
        _handle_workflow_not_found(workflow_name, wm)

    # Load workflow metadata
    metadata = wm.load(workflow_name)

    # Format using shared formatter
    from pflow.execution.formatters.history_formatter import format_workflow_history

    formatted = format_workflow_history(workflow_name, metadata)
    click.echo(formatted)


def _handle_discovery_error(exception: Exception) -> None:
    """Handle errors during workflow discovery with user-friendly messages.

    Args:
        exception: The exception that occurred during discovery
    """
    from pflow.cli.discovery_errors import handle_discovery_error

    handle_discovery_error(
        exception,
        discovery_type="workflow",
        alternative_commands=[
            ("pflow workflow list", "Show all saved workflows"),
            ("pflow workflow describe <name>", "Get workflow details"),
        ],
    )


@workflow.command(name="discover")
@click.argument("query")
def discover_workflows(query: str) -> None:
    """Discover workflows that match your task description.

    Uses LLM to intelligently find relevant existing workflows
    based on a natural language description of what you want to do.

    Example:
        pflow workflow discover "I need to analyze pull requests"
    """
    from pflow.core.workflow.discovery import discover_workflow

    # Validate query before processing
    query = _validate_discovery_query(query, "workflow discover")

    manager = WorkflowManager()

    try:
        result = discover_workflow(query, workflow_manager=manager)
    except Exception as e:
        _handle_discovery_error(e)
        sys.exit(1)

    # Display results
    if result.found and result.workflow:
        from pflow.execution.formatters.discovery_formatter import format_discovery_result

        result_dict = {
            "workflow_name": result.workflow_name,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }
        formatted = format_discovery_result(result_dict, result.workflow)
        click.echo(formatted)
    else:
        from pflow.execution.formatters.discovery_formatter import format_no_matches_with_suggestions

        all_workflows = manager.list_all()
        formatted = format_no_matches_with_suggestions(all_workflows, query, reasoning=result.reasoning)
        click.echo(formatted)


# Workflow name validation is now handled by WorkflowManager._validate_workflow_name()
# This provides defense in depth - validation happens at the data layer, not just CLI


def _validate_discovery_query(query: str, command_name: str) -> str:
    """Validate and sanitize discovery query.

    Args:
        query: User's natural language query
        command_name: Name of the discovery command (for error messages)

    Returns:
        Sanitized query string

    Raises:
        SystemExit: If query is invalid
    """
    query = query.strip()

    if not query:
        click.echo(f"Error: {command_name} query cannot be empty", err=True)
        sys.exit(1)

    if len(query) > 500:
        click.echo(f"Error: Query too long (max 500 characters, got {len(query)})", err=True)
        click.echo("  Please use a more concise description", err=True)
        sys.exit(1)

    return query


def _load_and_parse_workflow(file_path: str) -> tuple[dict[str, Any], str, str | None]:
    """Load workflow from .pflow.md file, parse, and validate.

    Args:
        file_path: Path to workflow .pflow.md file

    Returns:
        Tuple of (validated_ir, markdown_content, description)

    Raises:
        SystemExit: If file can't be loaded or validation fails
    """
    from pathlib import Path

    from pflow.core import normalize_ir
    from pflow.core.markdown_parser import parse_markdown

    path = Path(file_path)

    # Reject .json files with a clear migration message
    if path.suffix == ".json":
        click.echo(
            "Error: JSON workflow format is no longer supported. Use .pflow.md format instead.",
            err=True,
        )
        sys.exit(1)

    try:
        content = path.read_text(encoding="utf-8")
        result = parse_markdown(content)

        # Normalize IR (adds ir_version, etc.)
        normalize_ir(result.ir)

        # Validate IR structure (raises WorkflowValidationError on failure)
        from pflow.core.ir_schema import validate_ir

        validate_ir(result.ir)

        return result.ir, content, result.description
    except MarkdownParseError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except FileNotFoundError:
        click.echo(f"Error: File not found: {file_path}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading workflow: {e}", err=True)
        sys.exit(1)


def _save_with_overwrite_check(
    name: str,
    markdown_content: str,
    metadata: dict[str, Any] | None,
    force: bool,
    source_path: Path | None = None,
) -> tuple[str, list[str]]:
    """Save workflow to library with overwrite handling.

    Args:
        name: Workflow name
        markdown_content: Original markdown content to save
        metadata: Optional metadata
        force: Whether to overwrite existing workflow
        source_path: Optional source file path for dependency discovery

    Returns:
        Tuple of (saved_path, bundled_files_list)

    Raises:
        SystemExit: If workflow exists and force=False, or save fails
    """
    from pflow.core.workflow.save_service import save_workflow_with_options

    try:
        saved_path, bundled_files = save_workflow_with_options(
            name=name,
            markdown_content=markdown_content,
            force=force,
            metadata=metadata,
            source_path=source_path,
        )

        if force:
            click.echo(f"✓ Overwritten existing workflow '{name}'")

        return str(saved_path), bundled_files

    except FileExistsError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("  Use --force to overwrite.", err=True)
        sys.exit(1)
    except WorkflowValidationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error saving workflow: {e}", err=True)
        sys.exit(1)


def _delete_draft_if_requested(file_path: str, delete_draft: bool) -> None:
    """Delete draft file if requested and safe to do so.

    Only deletes files in .pflow/workflows/ directory for safety.
    Uses is_relative_to() to prevent path traversal attacks.
    Resolves symlinks and refuses to delete symlinked files.

    Args:
        file_path: Path to draft file
        delete_draft: Whether to delete the draft
    """
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


@workflow.command(name="save")
@click.argument("file_path", type=click.Path(exists=True, readable=True))
@click.option("--name", required=True, help="Workflow name (lowercase-with-hyphens, max 30 chars)")
@click.option("--delete-draft", is_flag=True, help="Delete source file after save")
@click.option("--force", is_flag=True, help="Overwrite existing workflow")
def save_workflow(file_path: str, name: str, delete_draft: bool, force: bool) -> None:
    """Save a workflow file to the global library.

    Takes a .pflow.md workflow file and saves it to the global library
    at ~/.pflow/workflows/ for reuse across all projects. The workflow
    description is extracted from the markdown content (H1 prose).

    Example:
        pflow workflow save ./my-workflow.pflow.md --name my-analyzer
    """
    from pflow.core.workflow.save_service import validate_workflow_name

    # Validate workflow name
    is_valid, error = validate_workflow_name(name)
    if not is_valid:
        click.echo(f"Error: {error}", err=True)
        sys.exit(1)

    # Load, parse, and validate workflow
    validated_ir, markdown_content, _description = _load_and_parse_workflow(file_path)

    metadata = None

    # Save workflow (passes markdown content, not IR)
    saved_path, bundled_files = _save_with_overwrite_check(
        name, markdown_content, metadata, force, source_path=Path(file_path)
    )

    # Delete draft if requested
    _delete_draft_if_requested(file_path, delete_draft)

    # Format success message using shared formatter (needs IR for interface display)
    from pflow.execution.formatters.workflow_save_formatter import format_save_success

    success_message = format_save_success(
        name=name,
        saved_path=saved_path,
        workflow_ir=validated_ir,
        metadata=metadata,
        bundled_files=bundled_files,
    )
    click.echo(success_message)
