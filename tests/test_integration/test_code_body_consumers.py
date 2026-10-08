"""Every consumer that walks a step's params skips a code body (ADR-0016, Task 118).

One row per consumer of a param's text, each through that consumer's own entry
point. Each row puts a ``${…}`` the consumer WOULD act on into a shell command
(it must not) and the same text into ``env:`` (it must — the presence half, proving
the row's input is one the consumer reports at all). Mutation ledger: removing the
body rule at a row's site turns exactly that row red (recorded in the task log).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.file_resolver import has_file_references, resolve_file_references
from pflow.core.workflow.data_flow import validate_data_flow
from pflow.core.workflow.dependency_discovery import discover_dependencies
from pflow.core.workflow.graph.build import build_graph
from pflow.core.workflow.graph.model import EdgeKind
from pflow.core.workflow.graph.renderers.react_flow import render_react_flow
from pflow.mcp_server.services.execution_service import ExecutionService
from pflow.registry import Registry
from pflow.runtime.engine.template_resolution import split_params
from pflow.runtime.template_validation import validate_workflow_templates


@pytest.fixture(scope="module")
def registry() -> Registry:
    reg = Registry()
    reg.load()
    return reg


def _up_and_shell(**shell_params: Any) -> dict[str, Any]:
    """``up`` (a shell step) → ``s`` (a shell step carrying the row's params)."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "up", "type": "shell", "params": {"command": "echo hi"}},
            {"id": "s", "type": "shell", "params": shell_params},
        ],
        "edges": [{"from": "up", "to": "s"}],
    }


def _messages(diagnostics: list[Diagnostic], needle: str) -> list[str]:
    return [d.message for d in diagnostics if needle in d.message]


# ── one function per consumer: (body run, env run) → assertions ────────────


def _data_flow(_registry: Registry, _tmp: Path) -> None:
    needle = "non-existent node 'ghost'"
    body = validate_data_flow(_up_and_shell(command="echo ${ghost.x}"))
    assert _messages(body, needle) == []
    assert [d.severity for d in body] == [Severity.WARNING]  # ruling 2 only
    env = validate_data_flow(_up_and_shell(command='echo "$V"', env={"V": "${ghost.x}"}))
    assert len(_messages(env, needle)) == 1


def _pass_5(registry: Registry, _tmp: Path) -> None:
    needle = "does not output 'nope'"
    body = validate_workflow_templates(_up_and_shell(command="echo ${up.nope}"), {}, registry)
    assert _messages(body, needle) == []
    env = validate_workflow_templates(_up_and_shell(command='echo "$V"', env={"V": "${up.nope}"}), {}, registry)
    assert len(_messages(env, needle)) == 1


def _pass_8(_registry: Registry, _tmp: Path) -> None:
    llm_metadata = {
        "interface": {
            "inputs": [{"key": "prompt", "type": "str", "description": "prompt"}],
            "outputs": [{"key": "response", "type": "str", "description": "response"}],
            "params": [],
            "actions": ["default"],
        }
    }
    shell_metadata = {
        "interface": {
            "inputs": [],
            "outputs": [{"key": "stdout", "type": "str", "description": "out"}],
            "params": [{"key": "command", "type": "str"}, {"key": "env", "type": "dict"}],
            "actions": ["default"],
        }
    }
    mock = Mock()
    mock.get_nodes_metadata = Mock(
        side_effect=lambda types: {t: {"llm": llm_metadata, "shell": shell_metadata}[t] for t in types}
    )

    def ir(**params: Any) -> dict[str, Any]:
        return {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {"id": "process", "type": "llm", "batch": {"items": "${data}"}, "params": {"prompt": "P ${item}"}},
                {"id": "s", "type": "shell", "batch": {"items": "${process.results}"}, "params": params},
            ],
            "edges": [{"from": "process", "to": "s"}],
        }

    needle = "not available on batch items"
    body = validate_workflow_templates(ir(command="echo ${item.nope}"), {"data": ["a"]}, mock)
    assert _messages(body, needle) == []
    env = validate_workflow_templates(ir(command='echo "$V"', env={"V": "${item.nope}"}), {"data": ["a"]}, mock)
    assert len(_messages(env, needle)) == 1


def _issue_pass(registry: Registry, _tmp: Path) -> None:
    needle = "Malformed template"
    body = validate_workflow_templates(_up_and_shell(command="echo ${1:-x}"), {}, registry)
    assert _messages(body, needle) == []
    env = validate_workflow_templates(_up_and_shell(command='echo "$V"', env={"V": "${1:-x}"}), {}, registry)
    assert len(_messages(env, needle)) == 1


def _unused_input(registry: Registry, _tmp: Path) -> None:
    needle = "never used"

    def ir(**params: Any) -> dict[str, Any]:
        return {**_up_and_shell(**params), "inputs": {"name": {"type": "string", "required": True}}}

    # Read only through a leftover: the leftover ERROR (data flow) is the one diagnostic.
    assert _messages(validate_workflow_templates(ir(command="echo ${name}"), {"name": "x"}, registry), needle) == []
    bound = ir(command='echo "$NAME"', env={"NAME": "${name}"})
    assert _messages(validate_workflow_templates(bound, {"name": "x"}, registry), needle) == []
    unread = validate_workflow_templates(ir(command='echo "$NAME"'), {"name": "x"}, registry)
    assert len(_messages(unread, needle)) == 1


def _source_file_hint(registry: Registry, _tmp: Path) -> None:
    """Pass 5's "which file did this reference come from" hint never cites a body's script."""

    def ir(source_files: dict[str, str], **params: Any) -> dict[str, Any]:
        workflow = _up_and_shell(**params)
        workflow["nodes"][1]["_source_files"] = source_files
        return workflow

    body = ir({"command": "./cmd.sh"}, command="cat <<'E'\n${up.nope}\nE", stdin="${up.nope}")
    [diagnostic] = [d for d in validate_workflow_templates(body, {}, registry) if "does not output 'nope'" in d.message]
    assert "source_file" not in (diagnostic.context or {})
    env = ir({"stdin": "./in.txt"}, command="cat", stdin="${up.nope}")
    [diagnostic] = [d for d in validate_workflow_templates(env, {}, registry) if "does not output 'nope'" in d.message]
    assert (diagnostic.context or {})["source_file"] == "./in.txt"


def _pass_6(_registry: Registry, _tmp: Path) -> None:
    """No real output type trips a ``str`` param, so a mock declares ``command: int``."""
    metadata = {
        "shell": {
            "interface": {
                "inputs": [],
                "outputs": [
                    {"key": "stdout", "type": "str", "description": "out"},
                    {"key": "exit_code", "type": "int", "description": "code"},
                ],
                "params": [
                    {"key": "command", "type": "int"},
                    {"key": "count", "type": "int"},
                    {"key": "code_n", "type": "int"},
                ],
                "actions": ["default"],
            }
        }
    }
    mock = Mock()
    mock.get_nodes_metadata = Mock(side_effect=lambda types: {t: metadata[t] for t in types if t in metadata})
    needle = "Type mismatch"
    # A compatible template beside the body, so the passes run at all (no template → early return).
    body = validate_workflow_templates(_up_and_shell(command="${up.stdout}", code_n="${up.exit_code}"), {}, mock)
    assert _messages(body, needle) == []
    other = validate_workflow_templates(_up_and_shell(command="true", count="${up.stdout}"), {}, mock)
    assert len(_messages(other, needle)) == 1


def _split_params(_registry: Registry, _tmp: Path) -> None:
    params = {"command": "echo ${up.stdout} $$ $${X}", "env": {"V": "${up.stdout}"}}
    template_params, static_params = split_params(params, {}, "shell")
    assert static_params == {"command": "echo ${up.stdout} $$ $${X}"}  # the escape is not collapsed
    assert template_params == {"env": {"V": "${up.stdout}"}}


def _graph_build(_registry: Registry, _tmp: Path) -> None:
    graph = build_graph(_up_and_shell(command="echo ${up.stdout}", env={"T": "${up.stdout}"}))
    data_flow = [
        (edge.source.node_id, edge.target.node_id, edge.input_name)
        for edge in graph.edges
        if edge.kind is EdgeKind.DATA_FLOW
    ]
    assert data_flow == [("up", "s", "T")]


def _canvas_is_dynamic(_registry: Registry, _tmp: Path) -> None:
    rendered = render_react_flow(build_graph(_up_and_shell(command="echo ${HOME}", env={"T": "${up.stdout}"})))
    [node] = [node for node in rendered.nodes if node.ref.node_id == "s"]
    assert {param.name: param.is_dynamic for param in node.params} == {"command": False, "env": True}


def _file_references(_registry: Registry, tmp: Path) -> None:
    """``./scripts/$NAME.sh`` is a command at every param-walk site; a ``$``-free body
    is still a file reference (the presence half), and so is a batch item's."""
    (tmp / "scripts").mkdir()
    (tmp / "scripts" / "run.sh").write_text("echo from-file\n", encoding="utf-8")

    def ir(command: str, item_command: str | None = None) -> dict[str, Any]:
        node: dict[str, Any] = {"id": "s", "type": "shell", "params": {"command": command}}
        if item_command is not None:
            node["batch"] = {"items": [{"command": item_command}]}
        return {"ir_version": "0.1.0", "nodes": [node], "edges": []}

    variable = ir("./scripts/$NAME.sh", item_command="./scripts/$NAME.sh")
    assert has_file_references(variable) == []
    assert discover_dependencies(variable, tmp) == []  # never FileNotFoundError on the command
    resolved = resolve_file_references(variable, tmp)
    assert resolved["nodes"][0]["params"]["command"] == "./scripts/$NAME.sh"
    assert resolved["nodes"][0]["batch"]["items"][0]["command"] == "./scripts/$NAME.sh"

    plain = ir("./scripts/run.sh", item_command="./scripts/run.sh")
    assert has_file_references(plain) == ["./scripts/run.sh", "./scripts/run.sh"]
    assert [dep.source_param for dep in discover_dependencies(plain, tmp)] == ["command", "batch.items[0].command"]
    resolved = resolve_file_references(plain, tmp)
    assert resolved["nodes"][0]["params"]["command"] == "echo from-file\n"
    assert resolved["nodes"][0]["batch"]["items"][0]["command"] == "echo from-file\n"

    templated_prompt = {"nodes": [{"id": "l", "type": "llm", "params": {"prompt": "./prompts/${var}.md"}}]}
    assert has_file_references(templated_prompt) == []


def _mcp_expansion(_registry: Registry, _tmp: Path) -> None:
    os.environ["PFLOW_TEST_X"] = "expanded"
    try:
        output = ExecutionService.run_registry_node(
            "shell",
            {"command": "printf '%s|%s' '${PFLOW_TEST_X}' \"$V\"", "env": {"V": "${PFLOW_TEST_X}"}},
        )
    finally:
        del os.environ["PFLOW_TEST_X"]
    assert "${PFLOW_TEST_X}|expanded" in output, output


CONSUMERS: list[tuple[str, Callable[[Registry, Path], None]]] = [
    ("data_flow", _data_flow),
    ("pass_5", _pass_5),
    ("pass_8", _pass_8),
    ("issue_pass", _issue_pass),
    ("unused_input", _unused_input),
    ("source_file_hint", _source_file_hint),
    ("pass_6", _pass_6),
    ("split_params", _split_params),
    ("graph_build", _graph_build),
    ("canvas_is_dynamic", _canvas_is_dynamic),
    ("file_references", _file_references),
    ("mcp_expansion", _mcp_expansion),
]


@pytest.mark.parametrize("check", [pytest.param(fn, id=name) for name, fn in CONSUMERS])
def test_consumer_skips_a_body_and_still_reads_env(
    check: Callable[[Registry, Path], None], registry: Registry, tmp_path: Path
) -> None:
    check(registry, tmp_path)
