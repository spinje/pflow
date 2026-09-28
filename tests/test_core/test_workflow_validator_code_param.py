"""Static validation of the `code` node's `code` param type (issue #622).

A non-string `code` value used to pass validation and then crash at compile
time with a raw ``TypeError`` from ``ast.parse``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.workflow.validator import WorkflowValidator
from pflow.execution.runner import WorkflowRunner


def _code_node_workflow(code: Any) -> dict[str, Any]:
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "upstream", "type": "shell", "params": {"command": "echo hi"}},
            {"id": "run", "type": "code", "params": {"code": code, "inputs": {"name": "world"}}},
        ],
        "edges": [{"from": "upstream", "to": "run"}],
    }


def _code_param_errors(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return [
        d
        for d in diagnostics
        if d.severity == Severity.ERROR and (d.context or {}).get("path") == "nodes[id=run].params.code"
    ]


@pytest.mark.parametrize(
    ("code", "type_name"),
    [
        (["./helpers.py", "./main.py"], "list"),
        ({"file": "./main.py"}, "dict"),
        (42, "int"),
        (None, "null"),
    ],
)
def test_non_string_code_is_rejected(code: Any, type_name: str) -> None:
    diagnostics = WorkflowValidator.validate(_code_node_workflow(code), skip_node_types=True)

    [error] = _code_param_errors(diagnostics)
    assert error.node_id == "run"
    assert error.message == f"Parameter 'code' must be a string of Python source, got {type_name}."
    assert error.suggestions


@pytest.mark.parametrize("code", ["name: str\nresult: str = name", "${upstream.stdout}"])
def test_string_code_is_accepted(code: str) -> None:
    diagnostics = WorkflowValidator.validate(_code_node_workflow(code), skip_node_types=True)

    assert _code_param_errors(diagnostics) == []


def test_validate_only_rejects_list_of_code_files(tmp_path: Path) -> None:
    """The exact workflow from the issue, through the `--validate-only` path (parse → resolve → validate)."""
    (tmp_path / "helpers.py").write_text('def greet(n): return "hi " + n\n', encoding="utf-8")
    (tmp_path / "main.py").write_text("name: str\nresult: str = greet(name)\n", encoding="utf-8")
    workflow_file = tmp_path / "multi.pflow.md"
    workflow_file.write_text(
        "# Multi\n\nList-valued code.\n\n## Steps\n\n### run\n\nRun code.\n\n"
        "- type: code\n- code: [./helpers.py, ./main.py]\n- inputs:\n    name: world\n",
        encoding="utf-8",
    )

    result = WorkflowRunner().validate(str(workflow_file), {})

    assert result.valid is False
    [error] = _code_param_errors(list(result.diagnostics))
    assert error.message == "Parameter 'code' must be a string of Python source, got list."
    assert any("list of files" in s for s in error.suggestions or [])
