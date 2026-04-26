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

    Output is pre-filtered for AI agents: shows structure and template
    paths, not raw data values. Don't grep or filter — what's displayed
    is what matters.

    \b
    Example:
        pflow probe mcp-slack-GET_CHANNEL channel="general"
    \b
        ✓ Node executed successfully
        Execution ID: exec-1763463202-0cd0c8fe
        Available template paths (from actual output):
        ✓ ${result.data.items} (list, 11 items)
        ✓ ${result.data.items[0].id} (str)
        ✓ ${result.data.items[0].title} (str)

    Use the template paths in your workflow: ${node.result.data.items}

    To get actual data values, use the Execution ID:

    \b
        pflow read-fields exec-1763463202-0cd0c8fe result.data.items

    \b
    More examples:
        pflow probe http url="https://api.example.com/data"
        pflow probe shell command="git log --oneline -5"
    """
    from pflow.cli.commands._probe_impl import execute_single_node
    from pflow.core.llm_config import inject_settings_env_vars

    inject_settings_env_vars()
    verbose = ctx.obj.get("verbose", False) if ctx.obj else False
    execute_single_node(
        node_type=node_type,
        params=params,
        output_format=output_format or "text",
        show_structure=(output_format != "json"),
        verbose=verbose,
    )
