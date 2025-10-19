"""Workflow management commands for pflow CLI."""

import json
import sys
from typing import Any

import click

from pflow.core.workflow_manager import WorkflowManager


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
        pflow workflow list github         # Match "github"
        pflow workflow list github pr      # Match BOTH "github" AND "pr"
        pflow workflow list                # Show all workflows
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
            click.echo(f"No workflows match filter: '{filter_pattern}'")
            click.echo(f"\nFound {total_count} total {plural}. Try:")
            click.echo("  - Broader keywords: Use fewer or different terms")
            click.echo("  - List all: pflow workflow list")
            click.echo('  - Discovery: pflow workflow discover "your task description"')
            return
    else:
        workflows = all_workflows

    if output_json:
        click.echo(json.dumps(workflows, indent=2))
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
    import os

    from pflow.planning.nodes import WorkflowDiscoveryNode

    # Validate query before processing
    query = _validate_discovery_query(query, "workflow discover")

    # Install Anthropic monkey patch for LLM calls (required for planning nodes)
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        from pflow.planning.utils.anthropic_llm_model import install_anthropic_model

        install_anthropic_model()

    # Create and run discovery node
    node = WorkflowDiscoveryNode()
    shared = {
        "user_input": query,
        "workflow_manager": WorkflowManager(),
    }

    try:
        action = node.run(shared)
    except Exception as e:
        _handle_discovery_error(e)
        sys.exit(1)

    # Display results
    if action == "found_existing":
        result = shared.get("discovery_result")
        workflow = shared.get("found_workflow")

        if workflow and result and isinstance(result, dict) and isinstance(workflow, dict):
            # Use shared formatter (same as MCP)
            from pflow.execution.formatters.discovery_formatter import format_discovery_result

            formatted = format_discovery_result(result, workflow)
            click.echo(formatted)
    else:
        # No match found - show available workflows as suggestions
        from pflow.execution.formatters.discovery_formatter import format_no_matches_with_suggestions

        workflow_manager_obj = shared.get("workflow_manager", WorkflowManager())
        # Type narrowing for mypy
        if not isinstance(workflow_manager_obj, WorkflowManager):
            workflow_manager_obj = WorkflowManager()
        all_workflows = workflow_manager_obj.list_all()

        # Get reasoning from discovery result if available
        result_obj = shared.get("discovery_result", {})
        # Type narrowing for mypy
        if not isinstance(result_obj, dict):
            result_obj = {}
        reasoning = result_obj.get("reasoning")

        formatted = format_no_matches_with_suggestions(all_workflows, query, reasoning=reasoning)
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


def _load_and_normalize_workflow(file_path: str) -> dict[str, Any]:
    """Load workflow from file and normalize IR structure.

    Args:
        file_path: Path to workflow JSON file

    Returns:
        Validated and normalized workflow IR

    Raises:
        SystemExit: If file can't be loaded or validation fails
    """
    from pflow.core.workflow_save_service import load_and_validate_workflow

    try:
        return load_and_validate_workflow(file_path, auto_normalize=True)
    except (ValueError, FileNotFoundError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading workflow: {e}", err=True)
        sys.exit(1)


def _generate_metadata_if_requested(validated_ir: dict[str, Any], generate_metadata: bool) -> dict[str, Any] | None:
    """Generate rich metadata for workflow if requested.

    Args:
        validated_ir: Validated workflow IR
        generate_metadata: Whether to generate metadata

    Returns:
        Generated metadata dict or None
    """
    if not generate_metadata:
        return None

    import os

    # Install Anthropic monkey patch for LLM calls (required for Anthropic-specific features)
    # Note: Other models (Gemini, OpenAI) work through standard LLM library
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        from pflow.planning.utils.anthropic_llm_model import install_anthropic_model

        install_anthropic_model()

    from pflow.core.workflow_save_service import generate_workflow_metadata

    click.echo("Generating rich metadata...")
    metadata = generate_workflow_metadata(validated_ir)

    if metadata:
        click.echo(f"  Generated {len(metadata.get('keywords', []))} keywords")
        click.echo(f"  Generated {len(metadata.get('capabilities', []))} capabilities")
    else:
        click.echo("  Warning: Could not generate metadata", err=True)

    return metadata


def _save_with_overwrite_check(
    name: str, validated_ir: dict[str, Any], description: str, metadata: dict[str, Any] | None, force: bool
) -> str:
    """Save workflow to library with overwrite handling.

    Args:
        name: Workflow name
        validated_ir: Validated workflow IR
        description: Workflow description
        metadata: Optional metadata
        force: Whether to overwrite existing workflow

    Returns:
        Path to saved workflow file

    Raises:
        SystemExit: If workflow exists and force=False, or save fails
    """
    from pflow.core.exceptions import WorkflowValidationError
    from pflow.core.workflow_save_service import save_workflow_with_options

    try:
        saved_path = save_workflow_with_options(
            name=name,
            workflow_ir=validated_ir,
            description=description,
            force=force,
            metadata=metadata,
        )

        if force:
            click.echo(f"✓ Overwritten existing workflow '{name}'")

        return str(saved_path)

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

    from pflow.core.workflow_save_service import delete_draft_safely

    if delete_draft_safely(file_path):
        click.echo(f"✓ Deleted draft: {file_path}")
    else:
        click.echo(
            f"Warning: Not deleting {file_path} - only files in .pflow/workflows/ can be auto-deleted",
            err=True,
        )


@workflow.command(name="save")
@click.argument("file_path", type=click.Path(exists=True, readable=True))
@click.argument("name")
@click.argument("description")
@click.option("--delete-draft", is_flag=True, help="Delete source file after save")
@click.option("--force", is_flag=True, help="Overwrite existing workflow")
@click.option("--generate-metadata", is_flag=True, help="Generate rich discovery metadata")
def save_workflow(
    file_path: str, name: str, description: str, delete_draft: bool, force: bool, generate_metadata: bool
) -> None:
    """Save a workflow file to the global library.

    Takes a workflow JSON file (typically a draft from .pflow/workflows/)
    and saves it to the global library at ~/.pflow/workflows/ for reuse
    across all projects.

    Example:
        pflow workflow save .pflow/workflows/draft.json my-analyzer "Analyzes PRs"
    """
    from pflow.core.workflow_save_service import validate_workflow_name

    # Validate workflow name
    is_valid, error = validate_workflow_name(name)
    if not is_valid:
        click.echo(f"Error: {error}", err=True)
        sys.exit(1)

    # Load and validate workflow
    validated_ir = _load_and_normalize_workflow(file_path)

    # Generate metadata if requested
    metadata = _generate_metadata_if_requested(validated_ir, generate_metadata)

    # Save workflow
    saved_path = _save_with_overwrite_check(name, validated_ir, description, metadata, force)

    # Delete draft if requested
    _delete_draft_if_requested(file_path, delete_draft)

    # Format success message using shared formatter
    from pflow.execution.formatters.workflow_save_formatter import format_save_success

    success_message = format_save_success(
        name=name,
        saved_path=saved_path,
        workflow_ir=validated_ir,
        metadata=metadata,
    )
    click.echo(success_message)
