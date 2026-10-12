"""A run's secret VALUES never print, wherever they travelled (#801).

Name-based masking hides ``SERVICE_TOKEN=<REDACTED>`` but not the same value inside free text —
shell stderr, an error message, a workflow result. The secret-value set (``security_utils.secret_values``:
every settings-stored value + every value bound under a sensitive-named declared input) is scrubbed
from every printed surface. Each test drives the real entry point and checks the WHOLE output for
absence and the scrubbed spot for ``<REDACTED>`` (presence and absence in the same medium).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from pflow.cli.main import main
from pflow.core.settings import SettingsManager
from pflow.mcp_server.services.execution_service import ExecutionService
from pflow.ui.run_node import run_node_detail

INPUT_SECRET = "sekret-input-0123"  # noqa: S105 - scrub sentinel
SETTINGS_SECRET = "sekret-settings-4567"  # noqa: S105 - scrub sentinel
SECRETS = (INPUT_SECRET, SETTINGS_SECRET)

pytestmark = pytest.mark.trace_files  # traces on, as in production: report and the UI read them

FAILING = """\
# Leak

Echo both secrets and fail.

## Inputs

### api_token

The token.

- type: string

## Steps

### use-token

Use the token.

- type: shell
- env:
    SERVICE_TOKEN: ${api_token}

```shell command
echo "auth failed for $SERVICE_TOKEN with $DEPLOY_KEY" >&2; exit 2
```
"""

SUCCEEDING = """\
# Echo

Print the token as the result.

## Inputs

### api_token

The token.

- type: string

## Steps

### show

Print the token.

- type: shell
- env:
    SERVICE_TOKEN: ${api_token}

```shell command
printf '{"tok": "%s", "deploy": "%s"}' "$SERVICE_TOKEN" "$DEPLOY_KEY"
```

## Outputs

### out

The printed token.

- source: ${show.stdout}
"""

CHILD = """\
# Child

Fails echoing what it was given.

## Inputs

### n

A value.

- type: string

## Steps

### fail

Fail with the value.

- type: shell
- env:
    VALUE: ${n}

```shell command
echo "denied $VALUE" >&2; exit 3
```
"""

BATCH_PARENT = """\
# Batch

Runs the child per item; a neutral child input carries the parent's secret.

## Inputs

### api_token

The token.

- type: string

## Steps

### each

Run the child.

- type: workflow
- workflow: ./child.pflow.md
- inputs:
    n: ${api_token}
- batch:
    items: [1, 2]
    error_handling: continue

## Outputs

### errs

The children's errors.

- source: ${each.errors}
"""


@pytest.fixture(autouse=True)
def settings_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """``DEPLOY_KEY`` stored in settings (the scrub's source) and exported (how the shell sees it)."""
    SettingsManager().set_env("DEPLOY_KEY", SETTINGS_SECRET)
    monkeypatch.setenv("DEPLOY_KEY", SETTINGS_SECRET)


def _write(tmp_path: Path, text: str, name: str = "leak.pflow.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _cli(*args: str) -> Result:
    return CliRunner(mix_stderr=False).invoke(main, list(args))


def _assert_scrubbed(output: str) -> None:
    for secret in SECRETS:
        assert secret not in output
    assert "<REDACTED>" in output


def _failed_json_run(tmp_path: Path) -> dict:
    result = _cli("--output-format", "json", str(_write(tmp_path, FAILING)), f"api_token={INPUT_SECRET}")
    assert result.exit_code == 1
    _assert_scrubbed(result.stdout + result.stderr)
    return json.loads(result.stdout)


def _failed_run_trace(tmp_path: Path) -> Path:
    return Path(_failed_json_run(tmp_path)["trace_path"])


class TestFailedRun:
    def test_text_output(self, tmp_path: Path) -> None:
        result = _cli(str(_write(tmp_path, FAILING)), f"api_token={INPUT_SECRET}")

        assert result.exit_code == 1
        _assert_scrubbed(result.stdout + result.stderr)
        assert "Stderr: auth failed for <REDACTED> with <REDACTED>" in result.stderr

    def test_json_document(self, tmp_path: Path) -> None:
        document = _failed_json_run(tmp_path)

        assert document["error"] == "Command failed with exit code 2: auth failed for <REDACTED> with <REDACTED>\n"
        assert document["errors"][0]["context"]["shell_stderr"] == "auth failed for <REDACTED> with <REDACTED>\n"
        assert document["errors"][0]["context"]["shell_env"]["SERVICE_TOKEN"] == "<REDACTED>"  # noqa: S105

    def test_verbose_parameters_line(self, tmp_path: Path) -> None:
        result = _cli("-v", str(_write(tmp_path, FAILING)), f"api_token={INPUT_SECRET}")

        _assert_scrubbed(result.stdout + result.stderr)
        assert "cli: With parameters: {'api_token': '<REDACTED>'}" in result.stderr

    def test_report_files_and_echo(self, tmp_path: Path) -> None:
        trace_path = _failed_run_trace(tmp_path)
        report_dir = tmp_path / "report"

        result = _cli("report", str(trace_path), "-o", str(report_dir))

        assert result.exit_code == 0
        files = "".join(path.read_text(encoding="utf-8") for path in report_dir.rglob("*") if path.is_file())
        _assert_scrubbed(result.stdout + result.stderr + files)
        # The trace itself stays raw: resume restores from it (redaction is display-time only).
        assert INPUT_SECRET in trace_path.read_text(encoding="utf-8")

    def test_web_ui_node_panel(self, tmp_path: Path) -> None:
        trace_path = _failed_run_trace(tmp_path)
        meta = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])

        detail = run_node_detail(
            meta["workflow_path"], meta["execution_id"], {"node_id": "use-token", "ancestor_path": [], "port": None}
        )

        assert detail is not None
        _assert_scrubbed(json.dumps(detail))
        assert detail["error"] == "Command failed with exit code 2: auth failed for <REDACTED> with <REDACTED>\n"

    def test_mcp_text(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError) as caught:
            ExecutionService.execute_workflow(str(_write(tmp_path, FAILING)), {"api_token": INPUT_SECRET})

        _assert_scrubbed(str(caught.value))


class TestSuccessfulRun:
    def test_text_result(self, tmp_path: Path) -> None:
        result = _cli(str(_write(tmp_path, SUCCEEDING)), f"api_token={INPUT_SECRET}")

        assert result.exit_code == 0
        _assert_scrubbed(result.stdout + result.stderr)
        assert '{"tok": "<REDACTED>", "deploy": "<REDACTED>"}' in result.stdout

    def test_json_result(self, tmp_path: Path) -> None:
        result = _cli("--output-format", "json", str(_write(tmp_path, SUCCEEDING)), f"api_token={INPUT_SECRET}")

        assert result.exit_code == 0
        _assert_scrubbed(result.stdout + result.stderr)
        assert json.loads(result.stdout)["result"]["out"] == {"tok": "<REDACTED>", "deploy": "<REDACTED>"}

    def test_output_key_miss_hint(self, tmp_path: Path) -> None:
        result = _cli(str(_write(tmp_path, SUCCEEDING)), f"api_token={INPUT_SECRET}", "-o", "show.stdout.missing")

        _assert_scrubbed(result.stdout + result.stderr)
        assert "cannot descend" in result.stderr


class TestBatchedChildren:
    """#799 residual 1 — a child's failure reaches the output through shapes no compactor recognises."""

    def test_declared_errors_output_text_and_json(self, tmp_path: Path) -> None:
        _write(tmp_path, CHILD, "child.pflow.md")
        parent = str(_write(tmp_path, BATCH_PARENT, "parent.pflow.md"))

        for args in ([parent], ["--output-format", "json", parent], [parent, "-o", "each.errors"]):
            result = _cli(*args, f"api_token={INPUT_SECRET}")
            _assert_scrubbed(result.stdout + result.stderr)
