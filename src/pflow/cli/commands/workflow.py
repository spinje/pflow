"""Workflow management commands for pflow CLI."""

import json
import sys
from pathlib import Path
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


def _display_workflow_metadata(workflow: dict) -> None:
    """Display workflow metadata section.

    Args:
        workflow: Workflow dict with metadata
    """
    if "metadata" in workflow:
        meta = workflow["metadata"]
        if isinstance(meta, dict):
            click.echo(f"**Description**: {meta.get('description', 'No description')}")
            click.echo(f"**Version**: {meta.get('version', '1.0.0')}")


def _display_workflow_flow(ir: dict) -> None:
    """Display workflow node flow.

    Args:
        ir: Workflow IR with flow field
    """
    if "flow" in ir:
        flow = ir.get("flow", [])
        if flow:
            flow_str = " >> ".join([edge["from"] for edge in flow[:3]])
            if len(flow) > 3:
                flow_str += " >> ..."
            click.echo(f"**Node Flow**: {flow_str}")


def _display_workflow_inputs_outputs(ir: dict) -> None:
    """Display workflow inputs and outputs.

    Args:
        ir: Workflow IR with inputs and outputs
    """
    if inputs := ir.get("inputs"):
        click.echo("**Inputs**:")
        for key, spec in inputs.items():
            req = "(required)" if spec.get("required") else "(optional)"
            input_type = spec.get("type", "any")
            desc = spec.get("description", "")
            click.echo(f"  - {key}: {input_type} {req} - {desc}")

    if outputs := ir.get("outputs"):
        click.echo("**Outputs**:")
        for key, spec in outputs.items():
            output_type = spec.get("type", "any")
            desc = spec.get("description", "")
            click.echo(f"  - {key}: {output_type} - {desc}")


def _format_execution_hint(name: str, workflow_ir: dict) -> str:
    """Format execution hint with parameter examples.

    Args:
        name: Workflow name
        workflow_ir: Workflow IR with inputs declaration

    Returns:
        Formatted execution command with parameter hints

    Examples:
        >>> _format_execution_hint("my-workflow", {"inputs": {}})
        'pflow my-workflow'

        >>> _format_execution_hint("my-workflow", {
        ...     "inputs": {
        ...         "topic": {"required": True, "type": "string"},
        ...         "style": {"required": False, "type": "string"}
        ...     }
        ... })
        'pflow my-workflow topic=<value> [style=<value>]'
    """
    base_command = f"pflow {name}"

    # Get inputs from IR
    inputs = workflow_ir.get("inputs", {})
    if not inputs:
        return base_command

    # Separate required and optional parameters
    required_params = []
    optional_params = []

    for param_name, param_spec in inputs.items():
        is_required = param_spec.get("required", True)
        param_type = param_spec.get("type", "string")

        # Create hint based on type - use consistent <type> format
        if param_type == "boolean":
            type_hint = "<true/false>"
        elif param_type == "number":
            type_hint = "<number>"
        elif param_type == "array":
            type_hint = "<array>"
        elif param_type == "object":
            type_hint = "<object>"
        else:
            type_hint = "<value>"

        hint = f"{param_name}={type_hint}"

        if is_required:
            required_params.append(hint)
        else:
            # Add (optional) suffix instead of brackets
            optional_params.append(f"{hint}")

    # Construct full command
    all_params = required_params + optional_params
    if all_params:
        return f"{base_command} {' '.join(all_params)}"
    else:
        return base_command


def _format_discovery_result(result: dict, workflow: dict) -> None:
    """Format and display workflow discovery results.

    Args:
        result: Discovery result with workflow_name, confidence, reasoning
        workflow: Workflow IR with metadata, flow, inputs, outputs
    """
    workflow_name = result.get("workflow_name", "Unknown")
    click.echo(f"\n## {workflow_name}")

    _display_workflow_metadata(workflow)

    ir = workflow.get("ir", workflow)
    _display_workflow_flow(ir)
    _display_workflow_inputs_outputs(ir)

    # Show confidence
    confidence = result.get("confidence", 0)
    click.echo(f"**Confidence**: {confidence:.0%}")

    # Show reasoning
    if reasoning := result.get("reasoning"):
        click.echo(f"\n*Match reasoning*: {reasoning}")


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
            _format_discovery_result(result, workflow)
    else:
        click.echo("No matching workflows found.")
        click.echo("\nTip: Try a more specific query or use 'pflow workflow list' to see all workflows.")


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
    from pflow.core import normalize_ir, validate_ir

    # Load workflow
    try:
        with open(file_path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except json.JSONDecodeError as e:
        click.echo(f"Error: Invalid JSON in {file_path}: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error reading file: {e}", err=True)
        sys.exit(1)

    # Extract IR if wrapped
    workflow_ir: dict[str, Any] = data.get("ir", data)

    # Auto-normalize workflow (same as --validate-only)
    # Add boilerplate fields if missing to reduce friction for agents
    normalize_ir(workflow_ir)

    # Validate IR structure
    try:
        validate_ir(workflow_ir)  # Returns None, raises on error
        return workflow_ir
    except Exception as e:
        click.echo(f"Error: Invalid workflow: {e}", err=True)
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

    from pflow.planning.nodes import MetadataGenerationNode

    # Install Anthropic monkey patch for LLM calls (required for Anthropic-specific features)
    # Note: Other models (Gemini, OpenAI) work through standard LLM library
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        from pflow.planning.utils.anthropic_llm_model import install_anthropic_model

        install_anthropic_model()

    click.echo("Generating rich metadata...")
    try:
        node = MetadataGenerationNode()
        shared: dict[str, Any] = {
            "generated_workflow": validated_ir,
            "user_input": "",
            "cache_planner": False,
        }
        node.run(shared)
        metadata = shared.get("workflow_metadata", {})
        if metadata and isinstance(metadata, dict):
            click.echo(f"  Generated {len(metadata.get('keywords', []))} keywords")
            click.echo(f"  Generated {len(metadata.get('capabilities', []))} capabilities")
            return metadata  # type: ignore[no-any-return]
        return None
    except Exception as e:
        click.echo(f"Warning: Could not generate metadata: {e}", err=True)
        return None


def _save_with_overwrite_check(
    wm: WorkflowManager, name: str, validated_ir: dict, description: str, metadata: dict | None, force: bool
) -> str:
    """Save workflow to library with overwrite handling.

    Args:
        wm: WorkflowManager instance
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
    if wm.exists(name):
        if not force:
            click.echo(f"Error: Workflow '{name}' already exists.", err=True)
            click.echo("  Use --force to overwrite.", err=True)
            sys.exit(1)
        else:
            # Delete existing workflow before saving new one
            try:
                wm.delete(name)
                click.echo(f"✓ Deleted existing workflow '{name}'")
            except Exception as e:
                click.echo(f"Error deleting existing workflow: {e}", err=True)
                sys.exit(1)

    try:
        return wm.save(name, validated_ir, description, metadata)
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

    file_path_obj = Path(file_path).resolve()  # Resolves symlinks

    # Define safe base directories for auto-deletion (also resolve them)
    home_pflow = (Path.home() / ".pflow" / "workflows").resolve()
    cwd_pflow = (Path.cwd() / ".pflow" / "workflows").resolve()

    # Check if file is within safe directories using is_relative_to()
    # This prevents path traversal attacks (e.g., ../../etc/passwd)
    try:
        is_safe = file_path_obj.is_relative_to(home_pflow) or file_path_obj.is_relative_to(cwd_pflow)

        # Additional security: refuse to delete symlinks (defense in depth)
        if is_safe and Path(file_path).is_symlink():
            click.echo(f"Warning: Refusing to delete symlink: {file_path}", err=True)
            is_safe = False

    except (ValueError, TypeError):
        # is_relative_to() may raise on invalid paths
        is_safe = False

    if is_safe:
        try:
            file_path_obj.unlink()
            click.echo(f"✓ Deleted draft: {file_path}")
        except Exception as e:
            click.echo(f"Warning: Could not delete draft: {e}", err=True)
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
    from pflow.core.exceptions import WorkflowValidationError

    validated_ir = _load_and_normalize_workflow(file_path)
    metadata = _generate_metadata_if_requested(validated_ir, generate_metadata)

    wm = WorkflowManager()

    try:
        saved_path = _save_with_overwrite_check(wm, name, validated_ir, description, metadata, force)
    except WorkflowValidationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    _delete_draft_if_requested(file_path, delete_draft)

    # Success output
    click.echo(f"✓ Saved workflow '{name}' to library")
    click.echo(f"  Location: {saved_path}")

    # Enhanced execution hint with parameter information
    execution_hint = _format_execution_hint(name, validated_ir)
    click.echo(f"  Execute with: {execution_hint}")

    # Add note about optional parameters if there are any
    inputs = validated_ir.get("inputs", {})
    optional_params = [name for name, spec in inputs.items() if not spec.get("required", True)]
    if optional_params:
        click.echo(f"  Optional params: {', '.join(optional_params)}")

    if metadata:
        keywords = metadata.get("keywords", [])
        if keywords:
            click.echo(f"  Discoverable by: {', '.join(keywords[:3])}...")
