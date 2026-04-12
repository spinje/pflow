"""Tests for the `pflow guide` command."""

import click.testing

from pflow.cli.commands.guide import guide_cmd
from pflow.guide import render_entry_content


def test_guide_without_topics_renders_entry_content() -> None:
    runner = click.testing.CliRunner()

    result = runner.invoke(guide_cmd, [])

    assert result.exit_code == 0
    assert result.output == f"{render_entry_content()}\n"


def test_guide_with_single_topic_acknowledges_topic() -> None:
    runner = click.testing.CliRunner()

    result = runner.invoke(guide_cmd, ["http"])

    assert result.exit_code == 0
    assert "Guide content for topics [http] is not yet implemented." in result.output
    assert "cli-agent-instructions.md" in result.output


def test_guide_with_multiple_topics_accepts_all_topics() -> None:
    runner = click.testing.CliRunner()

    result = runner.invoke(guide_cmd, ["http", "llm"])

    assert result.exit_code == 0
    assert "Guide content for topics [http, llm] is not yet implemented." in result.output
