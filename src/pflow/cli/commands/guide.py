"""pflow guide command."""

from __future__ import annotations

import click

from pflow.guide import GuideError, compose_guide, render_entry_content


@click.command(name="guide")
@click.argument("topics", nargs=-1)
def guide_cmd(topics: tuple[str, ...]) -> None:
    """Learn how to build workflows with pflow.

    Without arguments, shows the same overview as `pflow --help`.
    With topics, shows tailored content for those topics.

    \b
    Examples:
      pflow guide core                  Framework fundamentals
      pflow guide http llm              HTTP + LLM node guides
      pflow guide core http batch       Core + HTTP + batch processing
      pflow guide ./workflow.pflow.md   Auto-detect topics from a workflow
    """
    if not topics:
        click.echo(render_entry_content())
        return

    try:
        click.echo(compose_guide(list(topics)))
    except GuideError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from None
