"""pflow guide command."""

from __future__ import annotations

import click

from pflow.guide import render_entry_content


@click.command(name="guide")
@click.argument("topics", nargs=-1)
def guide_cmd(topics: tuple[str, ...]) -> None:
    """Learn how to build workflows with pflow.

    Without arguments, shows the same overview as `pflow --help`.
    With topics, shows a placeholder until Task 77 provides composed guide content.
    """
    if not topics:
        click.echo(render_entry_content())
        return

    topic_list = ", ".join(topics)
    click.echo(f"Guide content for topics [{topic_list}] is not yet implemented.")
    click.echo("This will be available after Task 77 ships.")
    click.echo()
    click.echo("Meanwhile, run 'pflow --help' for an overview of available commands.")
