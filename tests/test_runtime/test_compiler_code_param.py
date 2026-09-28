"""Compiler handling of a non-string `code` param (issue #622).

`WorkflowValidator` rejects it, but some callers compile without validating
first (the web UI run pre-flight, cache-key prediction in `analyze-cache`).
They must get a structured `CompilationError`, not a raw `TypeError`.
"""

from typing import Any

import pytest

from pflow.core.exceptions import CompilationError
from pflow.registry import Registry
from pflow.runtime import compile_workflow


@pytest.mark.parametrize(
    ("code", "type_name"),
    [(["./helpers.py", "./main.py"], "list"), (42, "int"), (None, "null")],
)
@pytest.mark.parametrize("inputs", [{"name": "world"}, None])
def test_non_string_code_raises_compilation_error(code: Any, type_name: str, inputs: dict[str, str] | None) -> None:
    params: dict[str, Any] = {"code": code}
    if inputs is not None:
        params["inputs"] = inputs
    workflow_ir = {"ir_version": "0.1.0", "nodes": [{"id": "run", "type": "code", "params": params}], "edges": []}

    with pytest.raises(CompilationError) as exc_info:
        compile_workflow(workflow_ir, Registry(), initial_params={})

    [diagnostic] = exc_info.value.to_diagnostics()
    assert diagnostic.node_id == "run"
    assert diagnostic.message == f"Parameter 'code' must be a string of Python source, got {type_name}."
