"""End-to-end test for inputs forwarding to sub-workflows.

Guards the contract between the validator and runtime: when a parent workflow
node uses ``inputs`` to forward values to a child with required inputs, both
validation AND execution must succeed.  If either side regresses (validator
rejects, or runtime stops forwarding), this test catches it.

Crosses: parser → compiler → template resolution → WorkflowExecutor →
child compilation → child execution → output resolution.
"""

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


class TestInputsForwardingEndToEnd:
    """Full pipeline: parent with inputs forwarding → child executes correctly."""

    def test_inputs_dict_forwarding_to_child(self, tmp_path):
        """Parent forwards inputs via dict mapping to a child with required inputs."""
        child_file = tmp_path / "child.pflow.md"
        child_file.write_text(
            """\
# Child

Child workflow with required inputs.

## Inputs

### name

The name to echo.

- type: string
- required: true

### value

The value to echo.

- type: string
- required: true

## Steps

### echo-it

Echo the provided values.

- type: shell
- command: echo "${name}=${value}"

## Outputs

### result

The echoed output.

- source: ${echo-it.stdout}
""",
            encoding="utf-8",
        )

        parent_file = tmp_path / "parent.pflow.md"
        parent_file.write_text(
            f"""\
# Parent

Parent forwards inputs to child via dict mapping.

## Steps

### build

Build an object with name and value fields.

- type: code

```python code
result: dict = {{"name": "alice", "value": "100"}}
```

### invoke-child

Forward the built object's fields to the child workflow.

- type: workflow
- workflow: {child_file}
- inputs:
    name: ${{build.result.name}}
    value: ${{build.result.value}}

## Outputs

### result

The child's output.

- source: ${{invoke-child.result}}
""",
            encoding="utf-8",
        )

        runner = WorkflowRunner()
        result = runner.run(str(parent_file), {}, RunnerConfig())

        assert result.success, f"Workflow failed: {result.diagnostics}"
        assert result.shared_after.get("result").strip() == "alice=100"
