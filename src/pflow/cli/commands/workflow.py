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
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def list_workflows(output_json: bool) -> None:
    """List all saved workflows."""
    wm = WorkflowManager()
    workflows = wm.list_all()

    if not workflows:
        click.echo("No workflows saved yet.\n")
        click.echo("To save a workflow:")
        click.echo('  1. Create one: pflow "your task"')
        click.echo("  2. Choose to save when prompted")
        return

    if output_json:
        click.echo(json.dumps(workflows, indent=2))
    else:
        click.echo("Saved Workflows:")
        click.echo("─" * 40)
        for wf in workflows:
            name = wf["name"]
            desc = wf.get("description", "No description")
            click.echo(f"\n{name}")
            click.echo(f"  {desc}")
        click.echo(f"\nTotal: {len(workflows)} workflows")


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


def _display_inputs(ir: dict[str, Any]) -> None:
    """Display workflow inputs."""
    if not ir.get("inputs"):
        click.echo("\nInputs: None")
        return

    click.echo("\nInputs:")
    for input_name, config in ir["inputs"].items():
        required = config.get("required", True)
        req_text = "required" if required else "optional"
        desc = config.get("description", "")
        default = config.get("default")

        click.echo(f"  - {input_name} ({req_text}): {desc}")
        if default is not None:
            click.echo(f"    Default: {default}")


def _display_outputs(ir: dict[str, Any]) -> None:
    """Display workflow outputs."""
    if not ir.get("outputs"):
        click.echo("\nOutputs: None")
        return

    click.echo("\nOutputs:")
    for output_name, config in ir["outputs"].items():
        desc = config.get("description", "")
        click.echo(f"  - {output_name}: {desc}")


def _display_example_usage(name: str, ir: dict[str, Any]) -> None:
    """Display example usage for the workflow."""
    click.echo("\nExample Usage:")

    # Collect required parameters
    example_params = []
    if "inputs" in ir:
        for input_name, config in ir["inputs"].items():
            if config.get("required", True):
                example_params.append(f"{input_name}=<value>")

    # Show the example command
    command = f"  pflow {name}"
    if example_params:
        command += f" {' '.join(example_params)}"
    click.echo(command)


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
    ir = metadata["ir"]

    # Display basic info
    click.echo(f"Workflow: {name}")
    click.echo(f"Description: {metadata.get('description', 'No description')}")

    # Display interface components
    _display_inputs(ir)
    _display_outputs(ir)
    _display_example_usage(name, ir)
