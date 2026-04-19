"""End-to-end validation of code-node input annotation checking."""

from pathlib import Path

import pytest

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner


def _write_t1_workflow(tmp_path: Path) -> Path:
    """Write the mismatch probe used for validate-time coverage."""
    path = tmp_path / "t1.pflow.md"
    path.write_text(
        """# T1
Upstream code node produces list. Downstream annotates dict.

## Steps

### upstream

Produces a list.

- type: code

```python code
result: list = [1, 2, 3]
```

### downstream

Annotates dict but upstream is list.

- type: code
- inputs:
    x: ${upstream.result}

```python code
x: dict
result: str = str(x)
```

## Outputs

### final
Final result.
- source: ${downstream.result}
""",
        encoding="utf-8",
    )
    return path


def _write_valid_workflow(tmp_path: Path) -> Path:
    """Write a matching variant for the positive path."""
    path = tmp_path / "valid.pflow.md"
    path.write_text(
        """# Valid
Upstream code node produces list. Downstream annotates list.

## Steps

### upstream

Produces a list.

- type: code

```python code
result: list = [1, 2, 3]
```

### downstream

Annotates list and matches upstream.

- type: code
- inputs:
    x: ${upstream.result}

```python code
x: list
result: str = str(x)
```

## Outputs

### final
Final result.
- source: ${downstream.result}
""",
        encoding="utf-8",
    )
    return path


def test_t1_validate_only_catches_type_mismatch(tmp_path: Path) -> None:
    """Validate-only should catch the mismatch before execution."""
    path = _write_t1_workflow(tmp_path)
    validation = WorkflowRunner().validate(str(path), params={})

    assert not validation.valid
    assert any("expects dict" in diagnostic.message for diagnostic in validation.errors), [
        diagnostic.message for diagnostic in validation.errors
    ]


def test_valid_workflow_passes_validation_and_runs(tmp_path: Path) -> None:
    """Matching annotations should pass both validation and execution."""
    path = _write_valid_workflow(tmp_path)
    runner = WorkflowRunner()

    validation = runner.validate(str(path), params={})
    assert validation.valid, [diagnostic.message for diagnostic in validation.errors]

    result = runner.run(str(path), {}, RunnerConfig())
    assert result.success, [diagnostic.message for diagnostic in result.diagnostics]


def test_runtime_still_defends_when_validation_bypassed() -> None:
    """Direct compile+run still fails at runtime when validation is skipped."""
    from pflow.runtime import WorkflowEngine, compile_workflow
    from tests.shared.registry_utils import ensure_test_registry

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "upstream", "type": "code", "params": {"code": "result: list = [1, 2, 3]"}},
            {
                "id": "downstream",
                "type": "code",
                "params": {
                    "code": "x: dict\nresult: str = str(x)",
                    "inputs": {"x": "${upstream.result}"},
                },
            },
        ],
        "edges": [{"from": "upstream", "to": "downstream"}],
    }

    registry = ensure_test_registry()
    workflow = compile_workflow(ir, registry=registry, initial_params={})

    with pytest.raises(TypeError, match=r"expects dict"):
        WorkflowEngine().run(workflow, {})
