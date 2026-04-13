"""Tests for the `pflow probe` command."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import click.testing
import pytest

from pflow.cli.commands.probe import probe_cmd
from pflow.registry.registry import Registry


@pytest.fixture
def runner() -> click.testing.CliRunner:
    return click.testing.CliRunner()


@pytest.fixture
def mock_registry():
    with patch("pflow.cli.commands._probe_impl.Registry") as MockRegistry:
        instance = MagicMock(spec=Registry)
        MockRegistry.return_value = instance
        instance.load.return_value = {
            "read-file": {
                "interface": {
                    "description": "Read content from a file",
                    "params": [{"key": "file_path", "type": "str", "required": True}],
                }
            },
            "mcp-slack-composio-SLACK_SEND_MESSAGE": {
                "interface": {
                    "description": "Send a Slack message",
                    "params": [
                        {"key": "channel", "type": "str", "required": True},
                        {"key": "text", "type": "str", "required": True},
                    ],
                }
            },
            "mcp-other-SLACK_SEND_MESSAGE": {
                "interface": {
                    "description": "Ambiguous Slack message sender",
                    "params": [
                        {"key": "channel", "type": "str", "required": True},
                        {"key": "text", "type": "str", "required": True},
                    ],
                }
            },
        }
        yield MockRegistry, instance


def test_probe_help_mentions_metadata_contract(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(probe_cmd, ["--help"])

    assert result.exit_code == 0
    assert "shows structure and template paths" in result.output


def test_probe_basic_node_execution_with_temp_file(runner: click.testing.CliRunner, tmp_path: Path) -> None:
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, world!")

    from pflow.nodes.file.read_file import ReadFileNode

    with (
        patch("pflow.cli.commands._probe_impl.import_node_class", return_value=ReadFileNode),
        patch("pflow.cli.commands._probe_impl.Registry") as MockRegistry,
    ):
        MockRegistry.return_value.load.return_value = {"read-file": {"interface": {"params": []}}}
        result = runner.invoke(probe_cmd, ["read-file", f"file_path={test_file}"])

    assert result.exit_code == 0
    assert "Execution ID:" in result.output
    assert "Hello, world!" not in result.output


def test_probe_json_output_produces_valid_json(runner: click.testing.CliRunner, tmp_path: Path) -> None:
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    from pflow.nodes.file.read_file import ReadFileNode

    with (
        patch("pflow.cli.commands._probe_impl.import_node_class", return_value=ReadFileNode),
        patch("pflow.cli.commands._probe_impl.Registry") as MockRegistry,
    ):
        MockRegistry.return_value.load.return_value = {"read-file": {"interface": {"params": []}}}
        result = runner.invoke(probe_cmd, ["read-file", f"file_path={test_file}", "--output-format", "json"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["success"] is True
    assert output["node_type"] == "read-file"
    assert "test content" in output["outputs"]["content"]


def test_probe_rejects_text_output_format(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(probe_cmd, ["read-file", "file_path=/tmp/test.txt", "--output-format", "text"])

    assert result.exit_code != 0
    assert "Invalid value" in result.output or "invalid choice" in result.output.lower()


def test_probe_short_form_mcp_normalization(runner: click.testing.CliRunner, mock_registry) -> None:
    _MockRegistry, instance = mock_registry
    node_instance = MagicMock()
    node_instance.run.return_value = "success"

    with (
        patch("pflow.cli.commands._probe_impl.import_node_class", return_value=lambda: node_instance),
        patch(
            "pflow.cli.commands._probe_impl.inject_special_parameters", return_value={"channel": "test", "text": "hi"}
        ),
    ):
        result = runner.invoke(probe_cmd, ["mcp-slack-composio-SLACK_SEND_MESSAGE", "channel=test", "text=hi"])

    assert result.exit_code == 0
    assert "Execution ID:" in result.output
    instance.load.assert_called()


def test_probe_unknown_node_errors(runner: click.testing.CliRunner, mock_registry) -> None:
    result = runner.invoke(probe_cmd, ["nonexistent-node"])

    assert result.exit_code == 1
    assert "Unknown node" in result.output


def test_probe_rejects_shell_special_chars_in_param_names(runner: click.testing.CliRunner) -> None:
    """Security boundary: shell special characters in parameter names must be
    rejected before any node execution occurs."""
    for invalid_param in ["$PWD", "key|value", "test>out", "test&bg", "test;next"]:
        result = runner.invoke(probe_cmd, ["shell", f"{invalid_param}=value"])

        assert result.exit_code == 1, f"Expected rejection for '{invalid_param}'"
        assert "Invalid parameter name" in result.output, f"Missing error message for '{invalid_param}'"


def test_probe_ambiguous_node_shows_candidates(runner: click.testing.CliRunner, mock_registry) -> None:
    """When a short-form node ID matches multiple nodes, probe should list
    the matching candidates so agents can self-correct."""
    result = runner.invoke(probe_cmd, ["SLACK_SEND_MESSAGE"])

    assert result.exit_code == 1
    assert "Ambiguous" in result.output
    assert "mcp-slack-composio-SLACK_SEND_MESSAGE" in result.output
    assert "mcp-other-SLACK_SEND_MESSAGE" in result.output
