"""Top-level node probing command."""

from __future__ import annotations

import click


@click.command(name="probe")
@click.argument("node_type")
@click.argument("params", nargs=-1)
@click.option("--output-format", type=click.Choice(["json"]), default=None, help="Output format")
@click.pass_context
def probe_cmd(ctx: click.Context, node_type: str, params: tuple[str, ...], output_format: str | None) -> None:
    """Test a single node without building a full workflow.

    Returns metadata and template paths, not raw data, so you can inspect
    structure first and then use `read-fields` for specific values.

    \b
    Examples:
        pflow probe shell command="echo hello"
        pflow probe http url="https://api.example.com/data"
        pflow probe shell command="ls" --output-format json
    """
    from pflow.cli.commands._probe_impl import execute_single_node

    verbose = ctx.obj.get("verbose", False) if ctx.obj else False
    execute_single_node(
        node_type=node_type,
        params=params,
        output_format=output_format or "text",
        show_structure=(output_format != "json"),
        verbose=verbose,
    )
