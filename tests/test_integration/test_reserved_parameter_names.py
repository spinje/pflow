"""Reserved parameter names through the real CLI (#817).

pflow's own root store keys (`_pflow_workflow_file`, `_pflow_depth`, `_pflow_stack`, ...) steer
child-workflow resolution and the nesting guards. A caller's parameter of that name is refused
as a wrong call (exit 2) on every way in, while pflow's own injections keep every nested shape
running: a sub-workflow, a batch of sub-workflows, a resume, and `--only`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from pflow.cli.main import cli
from pflow.core.validation_utils import get_parameter_validation_error

pytestmark = pytest.mark.trace_files

_CHILD = """# Child

Echoes the directory it was loaded from.

## Steps

### say

Print the marker.

- type: shell

```shell command
echo {marker}
```

## Outputs

### msg

The marker.

- source: ${{say.stdout}}
"""

_MAIN = """# Main

Runs the sibling child workflow.

## Steps

### run-child

Run the child next to this file.

- type: workflow
- workflow: ./child.pflow.md

## Outputs

### result

The child's marker.

- source: ${run-child.msg}
"""

_BATCH = """# Batch

Runs the sibling child once per item.

## Steps

### run-child

Run the child next to this file, per item.

- type: workflow
- workflow: ./child.pflow.md
- batch:
    items: ["one", "two"]

## Outputs

### result

Every child's marker.

- source: ${run-child.results}
"""

_FAIL_AFTER_CHILD = """# Fail after child

Runs the sibling child, then fails unless `go` is ok — so a resume exists.

## Inputs

### go

Whether the last step succeeds.

- type: string

## Steps

### run-child

Run the child next to this file.

- type: workflow
- workflow: ./child.pflow.md

### check

Fail unless go is ok.

- type: shell
- env: {"GO": "${go}"}

```shell command
test "$GO" = ok && echo checked || exit 3
```

## Outputs

### result

The child's marker.

- source: ${run-child.msg}
"""

_UNUSED_INPUT = """# Unused

Declares an input no step reads.

## Inputs

### topic

The topic.

- type: string
- required: true

## Steps

### say

Say hi.

- type: shell

```shell command
echo hi
```
"""

_RESUME_RE = re.compile(r"pflow resume (\S+)")


def _invoke(*args: str | Path) -> Result:
    return CliRunner(mix_stderr=False).invoke(cli, [str(arg) for arg in args])


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """`a/` holds the workflows and their child; `b/` holds a decoy child the caller must not reach."""
    (tmp_path / ".pflow" / "debug").mkdir(parents=True)
    for directory in ("a", "b"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "child.pflow.md").write_text(
            _CHILD.format(marker=f"from-{directory}"), encoding="utf-8"
        )
    for name, text in {"main": _MAIN, "batch": _BATCH, "fail": _FAIL_AFTER_CHILD}.items():
        (tmp_path / "a" / f"{name}.pflow.md").write_text(text, encoding="utf-8")
    return tmp_path


def _failed_run_id(workflow: Path) -> str:
    failed = _invoke(workflow, "go=no")
    assert failed.exit_code == 1, failed.stderr
    match = _RESUME_RE.search(failed.stdout + failed.stderr)
    assert match, failed.stderr
    return match.group(1)


class TestACallerCannotSupplyAReservedName:
    def test_run_refuses_a_redirected_workflow_file(self, project: Path) -> None:
        """The reported path: the caller's `_pflow_workflow_file` loaded the child from `b/`."""
        result = _invoke("-p", project / "a" / "main.pflow.md", f"_pflow_workflow_file={project / 'b' / 'x.pflow.md'}")

        assert result.exit_code == 2, result.stderr
        assert "_pflow_workflow_file" in result.stderr
        assert "from-b" not in result.stdout

    def test_run_refuses_a_seeded_depth_instead_of_crashing(self, project: Path) -> None:
        """A text `_pflow_depth` reached the depth guard's `>=` as a bare TypeError."""
        result = _invoke("-p", project / "a" / "main.pflow.md", "_pflow_depth=0")

        assert result.exit_code == 2, result.stderr
        assert "TypeError" not in result.stderr

    @pytest.mark.parametrize("mode", [(), ("--validate-only",), ("--dry-run",)], ids=["run", "validate", "dry-run"])
    @pytest.mark.parametrize("name", ["_pflow_x", "bad$name"])
    def test_every_mode_refuses_with_the_runners_name_error(
        self, project: Path, mode: tuple[str, ...], name: str
    ) -> None:
        """One owner for the rule: `--validate-only` refuses what the run refuses, with the same
        message — never "✓ Workflow is valid" for a reserved name, nor "Unknown input" for a bad one."""
        result = _invoke(*mode, project / "a" / "main.pflow.md", f"{name}=1")

        assert result.exit_code == 2, result.stdout + result.stderr
        assert get_parameter_validation_error(name) in result.stdout + result.stderr
        assert "Workflow is valid" not in result.stdout
        assert "Unknown input" not in result.stdout + result.stderr

    def test_validate_only_json_reports_the_name_error_alone(self, project: Path) -> None:
        """The name rule refuses first, as the run does: the workflow's own error (an input it never
        uses) is not reported beside it, and the result is the validation document."""
        workflow = project / "a" / "unused.pflow.md"
        workflow.write_text(_UNUSED_INPUT, encoding="utf-8")

        result = _invoke("--validate-only", "--output-format", "json", workflow, "_pflow_x=1")
        document = json.loads(result.stdout)

        assert result.exit_code == 2
        assert document["success"] is False
        assert document["validated_only"] is True
        assert [error["message"] for error in document["errors"]] == [get_parameter_validation_error("_pflow_x")]

    def test_resume_refuses_a_reserved_override(self, project: Path) -> None:
        """Resume overrides reach the runner's name check like every other way in."""
        run_id = _failed_run_id(project / "a" / "fail.pflow.md")

        result = _invoke("resume", run_id, "go=ok", "--force", "_pflow_stack=zzz", "__custom__=1")

        assert result.exit_code == 2, result.stderr
        assert get_parameter_validation_error("_pflow_stack") in result.stderr
        assert get_parameter_validation_error("__custom__") in result.stderr


class TestPflowsOwnKeysStillRunEveryNestedShape:
    def test_a_sub_workflow_runs(self, project: Path) -> None:
        result = _invoke("-p", project / "a" / "main.pflow.md")

        assert result.exit_code == 0, result.stderr
        assert result.stdout.strip() == "from-a"

    def test_a_batch_of_sub_workflows_runs(self, project: Path) -> None:
        result = _invoke("-p", project / "a" / "batch.pflow.md")

        assert result.exit_code == 0, result.stderr
        assert result.stdout.count("from-a") == 2

    def test_a_resume_runs(self, project: Path) -> None:
        run_id = _failed_run_id(project / "a" / "fail.pflow.md")

        result = _invoke("resume", run_id, "go=ok", "--force", "-p")

        assert result.exit_code == 0, result.stderr
        assert result.stdout.strip() == "from-a"

    def test_only_runs_a_sub_workflow_step(self, project: Path) -> None:
        workflow = project / "a" / "main.pflow.md"
        assert _invoke(workflow).exit_code == 0  # --only restores upstream from a prior full run

        result = _invoke("--only", "run-child", workflow)

        assert result.exit_code == 0, result.stderr
        assert "from-a" in result.stdout
