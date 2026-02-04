"""Handlers for saving repaired workflows based on their source."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import click

logger = logging.getLogger(__name__)


def save_repaired_workflow(ctx: click.Context, repaired_workflow_ir: dict[str, Any]) -> None:
    """Save repaired workflow based on source type.

    Routes to appropriate handler based on workflow source:
    - saved: Workflows from workflow manager
    - file: Workflows from JSON files
    - other: Planner-generated workflows
    """
    # GATED: Repair disabled pending markdown format migration (Task 107).
    # Repair prompts assume JSON workflow format. Re-enable after prompt rewrite.
    logger.warning("save_repaired_workflow called but repair is gated (Task 107)")
    return

    source = ctx.obj.get("workflow_source")
    no_update = ctx.obj.get("no_update", False)

    if source == "saved":
        _save_repaired_saved_workflow(ctx, repaired_workflow_ir, no_update)
    elif source == "file":
        _save_repaired_file_workflow(ctx, repaired_workflow_ir, no_update)
    else:
        # Planner-generated workflow
        _save_repaired_planner_workflow(ctx, repaired_workflow_ir)


def _save_repaired_saved_workflow(ctx: click.Context, repaired_workflow_ir: dict[str, Any], no_update: bool) -> None:
    """Save repaired workflow that came from workflow manager.

    Args:
        ctx: Click context with workflow_manager and workflow_name
        repaired_workflow_ir: The repaired workflow IR
        no_update: If True, save to repaired/ subfolder; if False, overwrite original
    """
    from pflow.core.workflow_manager import WorkflowManager

    workflow_name = ctx.obj.get("workflow_name")
    if not workflow_name:
        logger.warning("No workflow name found for saved workflow repair")
        return

    # Get or create workflow manager
    workflow_manager = ctx.obj.get("workflow_manager")
    if not workflow_manager:
        workflow_manager = WorkflowManager()
        ctx.obj["workflow_manager"] = workflow_manager

    try:
        if no_update:
            # Save to repaired/ subfolder using direct filesystem access
            # (WorkflowManager doesn't allow slashes in names)
            repaired_dir = Path.home() / ".pflow" / "workflows" / "repaired"
            repaired_dir.mkdir(parents=True, exist_ok=True)

            # Save directly to filesystem
            repaired_path = repaired_dir / f"{workflow_name}.json"
            with open(repaired_path, "w") as f:
                json.dump(repaired_workflow_ir, f, indent=2)

            click.echo(click.style(f"\n✅ Repaired workflow saved to: repaired/{workflow_name}.json", fg="green"))

            # Display rerun command with actual parameters
            from pflow.cli.rerun_display import display_file_rerun_commands

            execution_params = ctx.obj.get("execution_params")
            display_file_rerun_commands(
                file_path=str(repaired_path),
                params=execution_params,
                show_save_tip=False,  # Can't save without execution
            )
        else:
            # Default: Overwrite original using new API method
            workflow_manager.update_ir(workflow_name, repaired_workflow_ir)
            # Only show message in text mode (not JSON mode)
            output_format = ctx.obj.get("output_format", "text")
            if output_format != "json":
                click.echo(click.style(f"\n✅ Updated saved workflow '{workflow_name}'", fg="green"))

    except Exception as e:
        # Show error to user (visible, not just logged)
        click.echo(click.style(f"⚠️  Could not save repaired workflow: {e}", fg="yellow"), err=True)
        # Still log for debugging
        logger.exception("Failed to save repaired workflow")


def _save_repaired_file_workflow(ctx: click.Context, repaired_workflow_ir: dict[str, Any], no_update: bool) -> None:
    """Save repaired workflow that came from a file.

    Args:
        ctx: Click context with source_file_path
        repaired_workflow_ir: The repaired workflow IR
        no_update: If True, create .repaired.json file; if False, overwrite original
    """
    source_file_path = ctx.obj.get("source_file_path")
    if not source_file_path:
        logger.warning("No source file path found for file workflow repair")
        return

    try:
        if no_update:
            # Create .repaired.json file
            base_name = source_file_path.rsplit(".json", 1)[0]
            repaired_path = f"{base_name}.repaired.json"

            with open(repaired_path, "w") as f:
                json.dump(repaired_workflow_ir, f, indent=2)

            click.echo(click.style(f"\n✅ Repaired workflow saved to: {repaired_path}", fg="green"))

            # Display rerun command with actual parameters
            from pflow.cli.rerun_display import display_file_rerun_commands

            execution_params = ctx.obj.get("execution_params")
            display_file_rerun_commands(
                file_path=repaired_path,
                params=execution_params,
                show_save_tip=False,  # No save tip for .repaired.json files
            )
        else:
            # Default: Overwrite original (no backup)
            with open(source_file_path, "w") as f:
                json.dump(repaired_workflow_ir, f, indent=2)

            # Only show message in text mode (not JSON mode)
            output_format = ctx.obj.get("output_format", "text")
            if output_format != "json":
                click.echo(click.style(f"\n✅ Updated {source_file_path}", fg="green"))

    except Exception as e:
        # Non-fatal - just warn
        logger.warning(f"Could not save repaired workflow: {e}")


def _save_repaired_planner_workflow(ctx: click.Context, repaired_workflow_ir: dict[str, Any]) -> None:
    """Save repaired workflow that was planner-generated.

    Args:
        ctx: Click context with execution_params
        repaired_workflow_ir: The repaired workflow IR
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    repaired_path = f"workflow-repaired-{timestamp}.json"

    try:
        with open(repaired_path, "w") as f:
            json.dump(repaired_workflow_ir, f, indent=2)

        click.echo(click.style(f"\n✅ Repaired workflow saved to: {repaired_path}", fg="green"))

        # Display rerun command with actual parameters
        from pflow.cli.rerun_display import display_file_rerun_commands

        execution_params = ctx.obj.get("execution_params")
        display_file_rerun_commands(
            file_path=repaired_path,
            params=execution_params,
            show_save_tip=False,  # Can't save without execution
        )

    except Exception as e:
        # Non-fatal - just warn
        logger.warning(f"Could not save repaired workflow: {e}")
