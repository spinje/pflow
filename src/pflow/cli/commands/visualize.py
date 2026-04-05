"""Visualize workflow as a Mermaid flowchart diagram."""

import click


@click.command("visualize")
@click.argument("workflow")
@click.option("--depth", type=click.IntRange(min=0), default=1, help="Sub-workflow expansion depth (0 = no expansion)")
@click.option(
    "--direction",
    type=click.Choice(["LR", "TD"], case_sensitive=True),
    default="LR",
    help="Graph direction: LR (left-to-right) or TD (top-down)",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    default=None,
    help="Write Mermaid output to file instead of stdout",
)
@click.pass_context
def visualize(ctx: click.Context, workflow: str, depth: int, direction: str, output: str | None) -> None:
    """Generate a Mermaid flowchart from a workflow.

    Validates the workflow first (same checks as --validate-only).
    On validation failure, shows diagnostics and exits with code 1.
    On success, outputs Mermaid syntax to stdout (or to file with -o).

    Examples:

        pflow visualize workflow.pflow.md

        pflow visualize my-saved-workflow --depth 2

        pflow visualize workflow.pflow.md -o diagram.mmd

        pflow visualize workflow.pflow.md --direction TD
    """
    from pathlib import Path

    from pflow.core.diagnostic import Severity, exception_to_diagnostics, format_diagnostic
    from pflow.core.workflow.mermaid import generate_mermaid
    from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow
    from pflow.execution.runner import WorkflowRunner
    from pflow.execution.workflow_resolver import resolve_workflow

    # Resolve the workflow (file path or saved name)
    try:
        resolved = resolve_workflow(workflow)
    except Exception as e:
        for diagnostic in exception_to_diagnostics(e):
            click.echo(format_diagnostic(diagnostic), err=True)
        ctx.exit(1)
        return

    # Validate (same pipeline as --validate-only)
    runner = WorkflowRunner()
    vresult = runner.validate(
        resolved,
        params={},
        source_file_path=resolved.file_path,
    )

    if not vresult.valid:
        from pflow.execution.formatters.validation_formatter import format_validation_failure

        click.echo(format_validation_failure(vresult.errors), err=True)
        extra = [d for d in vresult.diagnostics if d.severity in {Severity.WARNING, Severity.INFO}]
        if extra:
            click.echo("", err=True)
            for diagnostic in extra:
                click.echo(format_diagnostic(diagnostic), err=True)
        ctx.exit(1)
        return

    # Show warnings on stderr (non-fatal)
    for diagnostic in vresult.diagnostics:
        if diagnostic.severity == Severity.WARNING:
            click.echo(format_diagnostic(diagnostic), err=True)

    # Generate mermaid
    base_path = Path(resolved.file_path).parent if resolved.file_path else None
    mermaid = generate_mermaid(
        resolved.ir,
        resolve_child=resolve_sub_workflow,
        base_path=base_path,
        max_depth=depth,
        direction=direction,
    )

    if output:
        Path(output).write_text(mermaid, encoding="utf-8")
        click.echo(f"Mermaid diagram written to {output}", err=True)
    else:
        click.echo(mermaid)
