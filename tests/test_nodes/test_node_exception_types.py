"""Node code raises ``NodeError`` (or another ``PflowError``), never a vanilla exception.

A vanilla ``ValueError``/``TypeError``/``RuntimeError``/``Exception`` reaching the
author renders through the diagnostic converter's builtin fallback: no category
the agent can act on, and a ``Type: TypeError`` line for anything but
``ValueError``. ``NodeError`` carries the category (``validation`` when a step
param is at fault, ``execution_failure`` otherwise) and the param name.

The ratchet scans every module under ``src/pflow/nodes/`` for a *construction*
of a vanilla exception — ``raise ValueError(...)``, a bare ``raise ValueError``,
and ``return ValueError(...)`` (the agent backends' ``translate_error`` builds
exceptions that ``exec_fallback`` raises). Semantic builtins that a node's own
``exec_fallback`` dispatches on (``FileNotFoundError``, ``OSError``) are not
vanilla and are out of scope.

See ``src/pflow/nodes/CLAUDE.md`` → "Errors".
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from click.testing import CliRunner

import pflow.nodes
from pflow.cli.main import main

NODES_DIR = Path(pflow.nodes.__file__).parent
VANILLA = frozenset({"Exception", "ValueError", "TypeError", "RuntimeError"})

# (path relative to src/pflow/nodes, enclosing function, exception name) -> reason
ALLOWLIST: dict[tuple[str, str, str], str] = {
    ("llm/llm.py", "_finite_json_float", "ValueError"): (
        "json.loads parse_float hook: the decoder protocol is ValueError, caught two lines "
        "later in _parse_and_validate_structured_response and re-raised as LLMResponseParseError."
    ),
    ("llm/llm.py", "_reject_json_constant", "ValueError"): (
        "json.loads parse_constant hook: same protocol and same local catch as _finite_json_float."
    ),
}


def _vanilla_constructions() -> set[tuple[str, str, str, int]]:
    """Every vanilla exception construction under src/pflow/nodes: (path, function, name, line)."""
    found: set[tuple[str, str, str, int]] = set()
    for path in sorted(NODES_DIR.rglob("*.py")):
        rel = path.relative_to(NODES_DIR).as_posix()
        _scan(ast.parse(path.read_text(encoding="utf-8")), rel, "<module>", found)
    return found


def _scan(node: ast.AST, rel: str, function: str, found: set[tuple[str, str, str, int]]) -> None:
    for child in ast.iter_child_nodes(node):
        scope = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in VANILLA:
            found.add((rel, function, child.func.id, child.lineno))
        if isinstance(child, ast.Raise) and isinstance(child.exc, ast.Name) and child.exc.id in VANILLA:
            found.add((rel, function, child.exc.id, child.lineno))
        _scan(child, rel, scope, found)


def test_node_code_constructs_no_vanilla_exceptions() -> None:
    violations = sorted(
        f"  {rel}:{line} in {function}(): {name}"
        for rel, function, name, line in _vanilla_constructions()
        if (rel, function, name) not in ALLOWLIST
    )
    assert not violations, (
        "Node code must raise NodeError (pflow.core.exceptions) — pass param= when a step param "
        "is at fault — or another PflowError subclass, never a vanilla exception:\n"
        + "\n".join(violations)
        + "\nOnly an exception that never escapes the node (a stdlib hook protocol caught locally) "
        "may be added to ALLOWLIST, with its reason."
    )


def test_scanner_detects_every_construction_form() -> None:
    """The ratchet is only as good as its scanner: each form it advertises is caught."""
    source = (
        "def prep():\n    raise ValueError('missing')\n"
        "def check(x):\n    try:\n        int(x)\n        raise TypeError\n    except TypeError:\n        pass\n"
        "def translate_error(exc):\n    return RuntimeError(str(exc))\n"
        "def fine():\n    raise NodeError('ok', param='x')\n"
    )
    found: set[tuple[str, str, str, int]] = set()
    _scan(ast.parse(source), "x.py", "<module>", found)
    assert {(function, name) for _, function, name, _ in found} == {
        ("prep", "ValueError"),
        ("check", "TypeError"),
        ("translate_error", "RuntimeError"),
    }


def test_allowlist_has_no_stale_entries() -> None:
    live = {(rel, function, name) for rel, function, name, _ in _vanilla_constructions()}
    assert set(ALLOWLIST) <= live, f"Stale ALLOWLIST entries: {sorted(set(ALLOWLIST) - live)}"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "wf.pflow.md"
    path.write_text(f"# Node error\n\nExercise a node error.\n\n## Steps\n\n{body}", encoding="utf-8")
    return path


_HTTP_BAD_METHOD = "### fetch\n\nFetch.\n\n- type: http\n- url: https://example.com\n- method: FROB\n"
_WRITE_EMPTY_PATH = '### write\n\nWrite.\n\n- type: write-file\n- file_path: ""\n- content: hello\n'
_SHELL_BAD_TIMEOUT = "### run\n\nRun.\n\n- type: shell\n- timeout: -5\n\n```shell command\necho hi\n```\n"


@pytest.mark.parametrize(
    ("body", "node_id", "param", "message"),
    [
        (_HTTP_BAD_METHOD, "fetch", "method", "Invalid HTTP method 'FROB'"),
        (_WRITE_EMPTY_PATH, "write", "file_path", "Missing required 'file_path' parameter"),
        (_SHELL_BAD_TIMEOUT, "run", "timeout", "Invalid timeout value: -5"),
    ],
)
def test_param_error_reaches_the_author_as_a_validation_error(
    tmp_path: Path, body: str, node_id: str, param: str, message: str
) -> None:
    """A bad step param fails the run as a validation error naming the param — JSON and text."""
    path = _write(tmp_path, body)
    runner = CliRunner(mix_stderr=False)

    result = runner.invoke(main, ["--output-format", "json", str(path)])
    assert result.exit_code != 0
    [error] = json.loads(result.stdout)["errors"]
    assert error["title"] == "Validation Error"
    assert error["category"] == "validation"
    assert error["context"] == {"category": "validation", "param": param}
    assert error["node_id"] == node_id
    assert message in error["message"]
    assert "exception_type" not in error

    text = runner.invoke(main, [str(path)])
    output = text.output + (text.stderr or "")
    assert "Error: Validation Error" in output
    assert message in output
    assert "Type:" not in output


def test_translated_runtime_failure_reaches_the_author_as_an_execution_failure(tmp_path: Path) -> None:
    """A failure the node translated (no param at fault) stays an execution failure."""
    body = "### fetch\n\nFetch.\n\n- type: http\n- url: http://service.invalid/data\n"
    with (
        patch("requests.request", side_effect=requests.ConnectionError("refused")),
        patch("pflow.core.node.time.sleep"),
    ):
        result = CliRunner(mix_stderr=False).invoke(main, ["--output-format", "json", str(_write(tmp_path, body))])

    assert result.exit_code != 0
    [error] = json.loads(result.stdout)["errors"]
    assert error["title"] == "Execution Failed"
    assert error["context"] == {"category": "execution_failure"}
    assert error["node_id"] == "fetch"
    assert error["message"].startswith("Could not connect to http://service.invalid/data.")
    assert "exception_type" not in error


def test_param_error_on_one_batch_item_does_not_abort_a_continue_batch(tmp_path: Path) -> None:
    """NodeError stays retriable: under ``error_handling: continue`` only the bad item fails.

    A non-retriable exception is re-raised by the batch executor and aborts the whole
    batch (see ``AgentValidationError``), so this pins ``NodeError.retriable``.
    """
    body = (
        "### run\n\nRun per item.\n\n- type: shell\n- timeout: ${item}\n"
        "- batch:\n    items: [5, -1, 7]\n    error_handling: continue\n\n"
        "```shell command\necho ok\n```\n"
    )
    result = CliRunner(mix_stderr=False).invoke(main, ["--output-format", "json", str(_write(tmp_path, body))])

    assert result.exit_code == 0
    batch = json.loads(result.stdout)["result"]["run"]
    assert batch["success_count"] == 2
    assert [(e["index"], e["error"]) for e in batch["errors"]] == [(1, "Invalid timeout value: -1")]
