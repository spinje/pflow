"""Tests for the `pflow probe` command.

Probe runs a real node through ``execution/probe.py::probe_node`` — the same path MCP ``registry_run``
takes — so these tests run real nodes; a fake node is registered only where a real one needs a server.
"""

import json
import re
from pathlib import Path
from typing import Any

import click.testing
import pytest

from pflow.cli.commands.probe import probe_cmd
from pflow.cli.commands.read_fields import read_fields
from pflow.core.node import Node
from pflow.mcp.manager import MCPServerManager
from pflow.mcp.registrar import MCPRegistrar
from pflow.registry.registry import Registry

FAKE_MCP_NODE = "mcp-images-generate"


class FakeImagesNode(Node):
    """Stands in for an MCP tool with an outputSchema: writes ``result`` like MCPNode does."""

    def exec(self, prep_res: Any) -> Any:
        return {"success": True, "images": [{"path": "generated/image.jpg"}]}

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["result"] = exec_res
        return "default"


@pytest.fixture
def runner() -> click.testing.CliRunner:
    return click.testing.CliRunner(mix_stderr=False)


@pytest.fixture
def fake_mcp_node() -> str:
    """Register an MCP tool entry (outputSchema included) whose class is FakeImagesNode, and its server."""
    tool = {
        "name": "generate",
        "inputSchema": {"type": "object", "properties": {}},
        "outputSchema": {
            "type": "object",
            "properties": {"success": {"type": "boolean"}, "images": {"type": "array"}},
        },
    }
    entry = MCPRegistrar()._create_registry_entry("images", tool)
    entry.update({"module": FakeImagesNode.__module__, "class_name": FakeImagesNode.__name__})
    registry = Registry()
    nodes = registry.load()
    nodes[FAKE_MCP_NODE] = entry
    registry.save(nodes)
    MCPServerManager().add_server("images", command="true")
    return FAKE_MCP_NODE


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.txt"
    path.write_text("test content", encoding="utf-8")
    return path


def test_probe_help_mentions_metadata_contract(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(probe_cmd, ["--help"])

    assert result.exit_code == 0
    assert "shows structure and template paths" in result.output


def test_probe_success_prints_paths_on_stdout(runner: click.testing.CliRunner, text_file: Path) -> None:
    result = runner.invoke(probe_cmd, ["read-file", f"file_path={text_file}"])

    assert result.exit_code == 0
    assert "✓ Node executed successfully" in result.stdout
    assert "Execution ID:" in result.stdout
    assert result.stderr == ""


def test_probe_json_output_produces_valid_json(runner: click.testing.CliRunner, text_file: Path) -> None:
    result = runner.invoke(probe_cmd, ["read-file", f"file_path={text_file}", "--output-format", "json"])

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["success"] is True
    assert output["node_type"] == "read-file"
    assert output["outputs"]["content"] == "test content"
    assert "errors" not in output


def test_probe_verbose_json_keeps_progress_off_stdout(runner: click.testing.CliRunner, text_file: Path) -> None:
    """`-v` progress lines go to stderr so the JSON document on stdout still parses (#658), and the
    `-v` shared_store is the flat view — the params given, then what the node wrote."""
    result = runner.invoke(
        probe_cmd, ["read-file", f"file_path={text_file}", "--output-format", "json"], obj={"verbose": True}
    )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["success"] is True
    assert output["shared_store"]["file_path"] == str(text_file)
    assert output["shared_store"]["content"] == "test content"
    assert "Running node 'read-file'" in result.stderr
    assert "file_path: " in result.stderr
    assert f"Stored execution in cache: {output['execution_id']}" in result.stderr


def test_probe_verbose_text_mode_also_routes_progress_to_stderr(
    runner: click.testing.CliRunner, text_file: Path
) -> None:
    """Progress is diagnostics in every format, matching `pflow run -v`; stdout carries only the result."""
    result = runner.invoke(probe_cmd, ["read-file", f"file_path={text_file}"], obj={"verbose": True})

    assert result.exit_code == 0
    assert "Execution ID:" in result.stdout
    assert "Running node" not in result.stdout
    assert "Stored execution in cache" not in result.stdout
    assert "Running node 'read-file'" in result.stderr
    assert "Stored execution in cache" in result.stderr


def test_probe_rejects_text_output_format(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(probe_cmd, ["read-file", "file_path=/tmp/test.txt", "--output-format", "text"])

    assert result.exit_code != 0
    assert "Invalid value" in result.stderr or "invalid choice" in result.stderr.lower()


# --- A node that ran and failed: exit 1, the run's diagnostic on stderr (#846, #709) ---


def test_failed_node_exits_1_with_its_diagnostic_on_stderr(runner: click.testing.CliRunner) -> None:
    """#846: a node returning the error action is a failure — exit 1, stdout empty, and stderr carries
    the same titled diagnostic `pflow run` prints (shell details included)."""
    result = runner.invoke(probe_cmd, ["shell", "command=echo oops >&2; exit 3"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith("Error: Execution Failed\n\nCommand failed with exit code 3: oops")
    assert "At: node 'shell'" in result.stderr
    assert "Command: echo oops >&2; exit 3" in result.stderr


def test_failed_node_json_is_a_document_with_errors(runner: click.testing.CliRunner) -> None:
    """#846 in JSON mode: still one document on stdout, `success: false` with the run's errors, exit 1."""
    result = runner.invoke(probe_cmd, ["shell", "command=exit 3", "--output-format", "json"])

    assert result.exit_code == 1
    output = json.loads(result.stdout)
    assert output["success"] is False
    assert output["outputs"]["exit_code"] == 3
    assert output["execution_id"] is None
    (error,) = output["errors"]
    assert error["title"] == "Execution Failed"
    assert error["node_id"] == "shell"
    assert error["context"]["shell_exit_code"] == 3


def test_raised_node_error_renders_structured_diagnostic(runner: click.testing.CliRunner) -> None:
    """#709: a node that raises (write-file with an empty path) renders the titled diagnostic without
    `-v`, never the bare `str(exc)`; JSON carries the same diagnostic with its `param` context."""
    text = runner.invoke(probe_cmd, ["write-file", "file_path=", "content=x"])
    as_json = runner.invoke(probe_cmd, ["write-file", "file_path=", "content=x", "--output-format", "json"])

    assert text.exit_code == 1
    assert text.stderr.startswith("Error: Validation Error\n\nMissing required 'file_path' parameter")
    assert "At: node 'write-file'" in text.stderr
    assert "execution failed:" not in text.stderr
    assert as_json.exit_code == 1
    (error,) = json.loads(as_json.stdout)["errors"]
    assert error["title"] == "Validation Error"
    assert error["context"]["param"] == "file_path"


# --- Refused before the node ran: exit 2 (the call is wrong) ---


def test_unknown_node_is_refused_with_exit_2(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(probe_cmd, ["nonexistent-node"])

    assert result.exit_code == 2
    assert result.stderr.startswith("Error: Node Not Found")
    assert "Did you mean one of these?" in result.stderr


def test_unknown_node_json_is_a_document(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(probe_cmd, ["nonexistent-node", "--output-format", "json"])

    assert result.exit_code == 2
    output = json.loads(result.stdout)
    assert output["success"] is False
    assert output["errors"][0]["title"] == "Node Not Found"


def test_probe_rejects_shell_special_chars_in_param_names(runner: click.testing.CliRunner, tmp_path: Path) -> None:
    """Security boundary: shell special characters and pflow's reserved `_pflow_*` prefix in
    parameter names must be rejected before any node execution occurs."""
    marker = tmp_path / "ran"
    for invalid_param in ["$PWD", "key|value", "test>out", "test&bg", "test;next", "_pflow_depth"]:
        result = runner.invoke(probe_cmd, ["shell", f"{invalid_param}=value", f"command=touch {marker}"])

        assert result.exit_code == 2, f"Expected rejection for '{invalid_param}'"
        assert "Invalid parameter name" in result.stderr, f"Missing error message for '{invalid_param}'"
    assert not marker.exists()


def test_unknown_param_is_refused_by_validation(runner: click.testing.CliRunner) -> None:
    """Probe validates the node's params as `pflow run` does: an unknown one is a wrong call."""
    result = runner.invoke(probe_cmd, ["shell", "command=echo hi", "bogus=1"])

    assert result.exit_code == 2
    assert "Unknown parameter 'bogus' on node 'shell'" in result.stderr


def test_ambiguous_short_form_lists_candidates(runner: click.testing.CliRunner, fake_mcp_node: str) -> None:
    """A short form matching several nodes is refused (exit 2) with the candidates listed."""
    registry = Registry()
    nodes = registry.load()
    nodes["mcp-other-generate"] = dict(nodes[fake_mcp_node])
    registry.save(nodes)

    result = runner.invoke(probe_cmd, ["generate"])

    assert result.exit_code == 2
    assert "Ambiguous Node" in result.stderr
    assert "mcp-images-generate" in result.stderr
    assert "mcp-other-generate" in result.stderr


# --- ${VAR} expansion ---


def test_env_var_in_a_param_is_expanded(
    runner: click.testing.CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # an unexpanded `${…}` path would land here, not in the repo
    monkeypatch.setenv("PFLOW_PROBE_TEST_DIR", str(tmp_path))

    result = runner.invoke(probe_cmd, ["write-file", "file_path=${PFLOW_PROBE_TEST_DIR}/out.txt", "content=x"])

    assert result.exit_code == 0, result.stderr
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "x"


def test_unset_env_var_refuses_with_the_missing_variable_error(runner: click.testing.CliRunner) -> None:
    result = runner.invoke(probe_cmd, ["http", "url=https://example.invalid/${PFLOW_PROBE_UNSET_VAR}"])

    assert result.exit_code == 2
    assert "Missing environment variable(s): PFLOW_PROBE_UNSET_VAR" in result.stderr
    assert "pflow settings set-env PFLOW_PROBE_UNSET_VAR=" in result.stderr


def test_env_var_in_a_body_is_left_to_the_shell(runner: click.testing.CliRunner) -> None:
    """A shell command is a body: its ${VAR} is the shell's own, so an unset one is no refusal."""
    result = runner.invoke(probe_cmd, ["shell", "command=echo x${PFLOW_PROBE_UNSET_VAR}y", "--output-format", "json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["outputs"]["stdout"] == "xy"


# --- Resolution, MCP output paths, cache ---


def test_short_form_resolves_to_the_registered_node(runner: click.testing.CliRunner, fake_mcp_node: str) -> None:
    result = runner.invoke(probe_cmd, ["generate", "--output-format", "json"], obj={"verbose": True})

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["node_type"] == fake_mcp_node
    assert f"Resolved 'generate' to '{fake_mcp_node}'" in result.stderr


def test_probe_mcp_output_schema_paths_resolve_via_read_fields(
    runner: click.testing.CliRunner, fake_mcp_node: str
) -> None:
    """MCP outputSchema fields stay beneath the runtime ``result`` namespace."""
    probe_result = runner.invoke(probe_cmd, [fake_mcp_node])

    assert probe_result.exit_code == 0, probe_result.stderr
    assert "${result.success} (bool) = true" in probe_result.stdout
    assert "${result.images} (list, 1 item)" in probe_result.stdout
    assert "${result.images[0].path} (str)" in probe_result.stdout
    assert "${success}" not in probe_result.stdout
    assert "<not found>" not in probe_result.stdout

    execution_id_match = re.search(r"Execution ID: (exec-[^\s]+)", probe_result.stdout)
    assert execution_id_match is not None
    read_result = runner.invoke(read_fields, [execution_id_match.group(1), "result.success"])

    assert read_result.exit_code == 0
    assert "result.success: True" in read_result.stdout


def test_probe_still_types_node_parameter_tokens(runner: click.testing.CliRunner, mock_llm_client) -> None:
    """A node parameter has no workflow-input declaration, so the probe keeps guessing a token's type
    (workflow inputs never are — their declaration decides): `temperature=0.5` reaches the node a float."""
    mock_llm_client.set_response("*", None, "ok")
    result = runner.invoke(
        probe_cmd,
        ["llm", "model=anthropic/claude-sonnet-4-5", "prompt=hi", "temperature=0.5", "--output-format", "json"],
    )

    assert result.exit_code == 0, result.stdout
    (call,) = mock_llm_client.call_history
    assert call["temperature"] == 0.5
    assert isinstance(call["temperature"], float)
