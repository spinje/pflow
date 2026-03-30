"""Test template resolution for registry-style single-node execution through the Runner.

When the MCP server runs a single registry node (e.g. shell), it builds a
synthetic IR with one node and passes user-provided parameters to the Runner.
Templates like ${greeting} in node params must resolve from the Runner params
(which become the shared store). This test guards that pipeline end-to-end
without mocking -- a real shell node executes with a resolved template.
"""

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def test_runner_resolves_template_in_single_node_ir() -> None:
    """When Runner receives params, templates in node params resolve from those params.

    This simulates the registry_run path: a synthetic single-node IR with a
    template variable (${greeting}) in the shell command, and the variable
    value ("hello") provided as a Runner param. The param flows into the
    shared store and the template engine resolves it before execution.
    """
    synthetic_ir: dict = {
        "inputs": {
            "greeting": {"type": "str", "description": "A greeting word"},
        },
        "nodes": [
            {
                "id": "shell",
                "type": "shell",
                "params": {"command": "echo ${greeting}"},
            }
        ],
        "edges": [],
    }

    config = RunnerConfig(cache_enabled=False)
    result = WorkflowRunner().run(synthetic_ir, {"greeting": "hello"}, config)

    assert result.success is True, f"Execution failed: {result.errors}"

    # The shell node output must contain the resolved value, not the raw template
    stdout = result.shared_after["shell"]["stdout"]
    assert "hello" in stdout, f"Expected 'hello' in stdout, got: {stdout!r}"
    assert "${greeting}" not in stdout, f"Template was not resolved: {stdout!r}"
