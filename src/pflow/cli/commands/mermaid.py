"""``pflow mermaid`` — emit a workflow as a Mermaid flowchart diagram."""

import click


@click.command("mermaid")
@click.argument("workflow")
@click.option("--depth", type=click.IntRange(min=0), default=5, help="Sub-workflow expansion depth (0 = no expansion)")
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
    help="Write to file (.md wraps in markdown with title; other extensions write raw Mermaid)",
)
@click.option(
    "--descriptions",
    is_flag=True,
    default=False,
    help="Add first sentence of node descriptions to labels",
)
@click.pass_context
def mermaid_cmd(
    ctx: click.Context, workflow: str, depth: int, direction: str, output: str | None, descriptions: bool
) -> None:
    """Generate a Mermaid flowchart from a workflow.

    A niche output for humans who want a rendered diagram (or to paste one into a
    markdown doc) — NOT needed to understand a workflow: the .pflow.md source is
    self-describing. Use this only when explicitly asked for a Mermaid/markdown diagram.

    Validates the workflow first (same checks as --validate-only).
    On validation failure, shows diagnostics and exits with code 1.
    On success, outputs Mermaid syntax to stdout (or to file with -o).

    Examples:

        pflow mermaid workflow.pflow.md

        pflow mermaid my-saved-workflow --depth 2

        pflow mermaid workflow.pflow.md -o diagram.md

        pflow mermaid workflow.pflow.md --direction TD --descriptions
    """
    from pathlib import Path

    from pflow.core.diagnostic import Severity, exception_to_diagnostics
    from pflow.core.diagnostic_render import format_diagnostic
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
    try:
        vresult = runner.validate(
            resolved,
            params={},
            source_file_path=resolved.file_path,
        )
    except Exception as e:
        for diagnostic in exception_to_diagnostics(e):
            click.echo(format_diagnostic(diagnostic), err=True)
        ctx.exit(1)
        return

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

    # Generate mermaid
    base_path = Path(resolved.file_path).parent if resolved.file_path else None
    source_file = Path(resolved.file_path) if resolved.file_path else None
    mermaid = generate_mermaid(
        resolved.ir,
        resolve_child=resolve_sub_workflow,
        base_path=base_path,
        source_file=source_file,
        max_depth=depth,
        direction=direction,
        descriptions=descriptions,
    )

    if output:
        content = mermaid
        if output.endswith(".md"):
            title = resolved.title or Path(resolved.file_path or workflow).stem
            desc = f"\n{resolved.description}\n" if resolved.description else ""
            content = f"# {title}\n{desc}\n```mermaid\n{mermaid}```\n"
        Path(output).write_text(content, encoding="utf-8")
        click.echo(f"Mermaid diagram written to {output}", err=True)
    else:
        click.echo(mermaid)
