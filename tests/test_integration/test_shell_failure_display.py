"""What ran stays answerable: a failing shell step shows its command AND its bound ``env:`` values.

Once values travel through ``env:`` instead of being pasted into the command text, the
failure block, the JSON error and ``pflow report`` would otherwise show ``"$ENDPOINT"``
and nothing else. A failing step records one display-safe copy of its bound values
(``nodes/shell/env_binding.py::displayable_env`` — masked by name, each value capped at
200 characters); every failure surface carries that copy; ``pflow report`` re-derives
full values from the trace. Every test drives the real CLI (or the runner/MCP service)
and reads the surface an agent reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from pflow.cli.main import main
from pflow.core.diagnostic_render import format_diagnostic
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.mcp_server.services.execution_service import ExecutionService
from tests.shared.markdown_utils import write_workflow_file

SECRET = "sk-secret-123456"  # noqa: S105 - redaction sentinel
REDACTION_NOTE = "(<REDACTED>: hidden because the name looks like a secret)"

FAILING_CALL = """\
# Failing call

Call an endpoint and fail.

## Inputs

### endpoint

The endpoint.

- type: string

### api_token

The token.

- type: string

## Steps

### call

Call the API and fail.

- type: shell
- env:
    ENDPOINT: ${endpoint}
    API_TOKEN: ${api_token}

```shell command
echo "calling $ENDPOINT" >&2; exit 3
```
"""


def _write(tmp_path: Path, text: str, name: str = "wf.pflow.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _cli(*args: str) -> Result:
    return CliRunner(mix_stderr=False).invoke(main, list(args))


def _everything(result: Result) -> str:
    return result.stdout + result.stderr


def _json_error(result: Result) -> dict[str, Any]:
    error: dict[str, Any] = json.loads(result.stdout)["errors"][0]
    return error


def _latest_trace() -> Path:
    traces = sorted((Path.home() / ".pflow" / "debug").glob("workflow-trace-*.json"))
    assert traces, "the run saved no trace"
    return traces[-1]


def _report(tmp_path: Path) -> Path:
    out = tmp_path / "report"
    result = _cli("report", str(_latest_trace()), "-o", str(out))
    assert result.exit_code == 0, _everything(result)
    return out


class TestTheFailureBlockShowsTheBoundValues:
    """Scenario 1 — the values are missing (and a secret must not leak in their place)."""

    def test_text_block_names_each_value_and_masks_the_secret(self, tmp_path: Path) -> None:
        result = _cli(str(_write(tmp_path, FAILING_CALL)), "endpoint=users", f"api_token={SECRET}")

        assert result.exit_code == 1
        assert (
            '    Command: echo "calling $ENDPOINT" >&2; exit 3\n'
            "    Env:\n"
            "      ENDPOINT=users\n"
            "      API_TOKEN=<REDACTED>\n"
            f"      {REDACTION_NOTE}\n"
            "    Stderr: calling users\n"
        ) in _everything(result)
        assert SECRET not in _everything(result)

    def test_json_error_carries_the_same_copy(self, tmp_path: Path) -> None:
        result = _cli(
            "--output-format", "json", str(_write(tmp_path, FAILING_CALL)), "endpoint=users", f"api_token={SECRET}"
        )

        error = _json_error(result)
        assert error["shell_env"] == {"ENDPOINT": "users", "API_TOKEN": "<REDACTED>"}
        assert error["context"]["shell_env"] == error["shell_env"]
        assert SECRET not in _everything(result)


LONG_VALUES = """\
# Long values

Bind values of several lengths and fail.

## Inputs

### mid

A 150-character value.

- type: string

### long

A 5,000-character value.

- type: string

### api_token

An empty secret.

- type: string
- required: false
- default: ""

## Steps

### call

Fail with the values bound.

- type: shell
- env:
    MID: ${mid}
    LONG: ${long}
    API_TOKEN: ${api_token}

```shell command
exit 4
```
"""

MID = "m" * 149 + "Z"
LONG = "L" * 4999 + "E"
LONG_SHOWN = "L" * 200 + "… (5,000 chars — full value: pflow report)"


class TestValueLengths:
    """Scenario 2 — the generic sanitizer cuts >100 chars to 20; the copy caps at 200, naming the length."""

    def test_text_and_json_cap_at_200_naming_the_length(self, tmp_path: Path) -> None:
        path = _write(tmp_path, LONG_VALUES)

        text = _cli(str(path), f"mid={MID}", f"long={LONG}")
        as_json = _cli("--output-format", "json", str(path), f"mid={MID}", f"long={LONG}")

        assert f"      MID={MID}\n      LONG={LONG_SHOWN}\n      API_TOKEN=<REDACTED>\n" in _everything(text)
        assert _json_error(as_json)["shell_env"] == {"MID": MID, "LONG": LONG_SHOWN, "API_TOKEN": "<REDACTED>"}

    @pytest.mark.trace_files
    def test_the_report_holds_the_whole_value(self, tmp_path: Path) -> None:
        _cli(str(_write(tmp_path, LONG_VALUES)), f"mid={MID}", f"long={LONG}")

        page = (_report(tmp_path) / "01-call.md").read_text(encoding="utf-8")
        env = json.loads(page.split("## Env\n\n```json\n", 1)[1].split("\n```", 1)[0])
        assert env == {"MID": MID, "LONG": LONG, "API_TOKEN": "<REDACTED>"}

    def test_a_newline_shows_escaped_on_one_line(self, tmp_path: Path) -> None:
        result = _cli("--output-format", "json", str(_write(tmp_path, LONG_VALUES)), "mid=a\nb", "long=x")

        assert _json_error(result)["shell_env"]["MID"] == "a\\nb"


BOOLEAN_FLAG = """\
# Boolean flag

Bind a boolean and fail.

## Inputs

### b

A flag.

- type: boolean

## Steps

### call

Fail with the flag bound.

- type: shell
- env:
    FLAG: ${b}

```shell command
echo "flag=$FLAG" >&2; exit 5
```
"""


class TestShownTextIsWhatRan:
    """Scenario 3 — a typed value is shown as the text the command received (`True`), never `true`."""

    @pytest.mark.trace_files
    def test_block_and_report_show_python_text(self, tmp_path: Path) -> None:
        result = _cli(str(_write(tmp_path, BOOLEAN_FLAG)), "b=true")

        assert "    Env:\n      FLAG=True\n    Stderr: flag=True\n" in _everything(result)
        page = (_report(tmp_path) / "01-call.md").read_text(encoding="utf-8")
        assert '## Env\n\n```json\n{\n  "FLAG": "True"\n}\n```' in page


STATIC_AND_BOUND = """\
# Two steps

One step without env, one with it.

## Inputs

### endpoint

The endpoint.

- type: string

## Steps

### plain

No env.

- type: shell

```shell command
echo plain
```

### bound

Reads a bound value.

- type: shell
- env:
    ENDPOINT: ${endpoint}

```shell command
echo "to $ENDPOINT"
```
"""

BATCH = """\
# Batch

Each item binds its own value.

## Steps

### per-item

Print each item.

- type: shell
- env:
    ITEM: ${item}
- batch:
    items: ["alpha", "beta"]

```shell command
printf '%s' "$ITEM"
```
"""


@pytest.mark.trace_files
class TestReportShowsCommandAndEnv:
    """Scenario 4 — `## Command` rendered only for a templated command would vanish for every converted step."""

    def test_every_shell_step_has_its_command_and_bound_values_have_their_own_section(self, tmp_path: Path) -> None:
        assert _cli(str(_write(tmp_path, STATIC_AND_BOUND)), "endpoint=users").exit_code == 0

        report = _report(tmp_path)
        plain = (report / "01-plain.md").read_text(encoding="utf-8")
        bound = (report / "02-bound.md").read_text(encoding="utf-8")
        assert "## Command\n\n```bash\necho plain\n```" in plain
        assert "## Env" not in plain
        assert (
            '## Command\n\n```bash\necho "to $ENDPOINT"\n```\n\n## Env\n\n```json\n{\n  "ENDPOINT": "users"\n}' in bound
        )
        assert "## Resolved Parameters" not in bound  # env is not repeated there

    def test_a_batch_item_page_shows_the_command_and_its_own_values(self, tmp_path: Path) -> None:
        assert _cli(str(_write(tmp_path, BATCH))).exit_code == 0

        batch_dir = _report(tmp_path) / "01-per-item"
        for index, value in enumerate(("alpha", "beta")):
            page = (batch_dir / f"item-{index}-{value}.md").read_text(encoding="utf-8")
            assert "## Command\n\n```bash\nprintf '%s' \"$ITEM\"\n```" in page
            assert f'## Env\n\n```json\n{{\n  "ITEM": "{value}"\n}}\n```' in page


def _shell(node_id: str, command: str, env: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"command": command}
    if env is not None:
        params["env"] = env
    return {"id": node_id, "type": "shell", "purpose": "A shell step.", "params": params, **extra}


def _run(*nodes: dict[str, Any]) -> Any:
    ir = {"ir_version": "0.1.0", "nodes": list(nodes), "edges": [], "start_node": nodes[0]["id"]}
    return WorkflowRunner().run(ir, {}, RunnerConfig(cache_enabled=False))


class TestOnlyAFailureRecordsTheCopy:
    """Scenario 5 — the copy must not grow every successful step's outputs (regression guard), but a failure has it."""

    def test_a_successful_step_and_batch_item_have_no_env_output(self) -> None:
        single = _run(_shell("s", 'printf %s "$V"', {"V": "x"}))
        batch = _run(_shell("b", 'printf %s "$V"', {"V": "${item}"}, batch={"items": ["a"]}))

        assert single.shared_after["s"]["stdout"] == "x"
        assert "env" not in single.shared_after["s"]
        assert batch.shared_after["b"]["results"][0]["stdout"] == "a"
        assert "env" not in batch.shared_after["b"]["results"][0]

    def test_a_failed_step_records_it(self) -> None:
        result = _run(_shell("s", "exit 2", {"V": "x"}))

        assert result.shared_after["__failures__"]["s"]["data"]["env"] == {"V": "x"}


REFERENCED_FAILURE = """\
# Referenced failure

A later output reads the failed step directly.

## Steps

### primary

Fails with a bound value.

- type: shell
- env:
    REGION: eu-west-1
    API_TOKEN: abc
- on-error: fallback
- next: end

```shell command
echo "stuff to stderr" >&2; exit 42
```

### fallback

Runs when primary fails.

- type: shell
- next: end

```shell command
echo "fallback ran"
```

## Outputs

### content

Reads the failed step.

- source: ${primary.stdout}
"""


class TestTheReferencedFailureBlock:
    """Scenario 6 — the block shown when a later reference hits the failed step renders the same Env lines."""

    def test_same_env_lines_at_the_block_indent(self, tmp_path: Path) -> None:
        result = WorkflowRunner().run(
            str(_write(tmp_path, REFERENCED_FAILURE)), {}, config=RunnerConfig(cache_enabled=False)
        )

        rendered = "\n".join(format_diagnostic(d) for d in result.errors)
        assert (
            '        Command: echo "stuff to stderr" >&2; exit 42\n'
            "        Env:\n"
            "          REGION=eu-west-1\n"
            "          API_TOKEN=<REDACTED>\n"
            f"          {REDACTION_NOTE}\n"
            "        Exit code: 42\n"
        ) in rendered


class TestCodeStepReportUnchanged:
    """Scenario 7 — the shell sections must not leak onto a code step's page (regression guard)."""

    @pytest.mark.trace_files
    def test_code_page_has_code_and_inputs_only(self, tmp_path: Path) -> None:
        workflow = """\
# Code

One code step.

## Steps

### compute

Double a number.

- type: code
- inputs:
    n: 21

```python code
n: int
result: int = n * 2
```
"""
        assert _cli(str(_write(tmp_path, workflow))).exit_code == 0

        page = (_report(tmp_path) / "01-compute.md").read_text(encoding="utf-8")
        assert "## Code\n\n```python\nn: int\nresult: int = n * 2\n```" in page
        assert "## Command" not in page
        assert "## Env" not in page


def _payload(label: str) -> dict[str, str]:
    return {"label": label, "payload": "PAYLOAD-START " + "token " * 200 + "PAYLOAD-END"}


CHILD = """\
# Child

Fail with the item bound beside a secret.

## Inputs

### item

The item.

- type: object

### token

A secret.

- type: string

## Steps

### inner

Fail.

- type: shell
- env:
    API_TOKEN: ${token}
    ITEM: ${item}

```shell command
echo "failing" >&2; exit 7
```
"""


class TestBatchErrorRecordsCarryOnlyTheSafeCopy:
    """Scenario 8 — batch error records reach CLI text, JSON and MCP unredacted and uncapped."""

    def test_a_top_level_batch_item_shows_its_summary_not_its_payload(self, tmp_path: Path) -> None:
        # Regression guard: a top-level batch's error records carry no node output at all.
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                _shell(
                    "fail-batch",
                    'echo "failed $LABEL" >&2; exit 1',
                    {"LABEL": "${item.label}", "ITEM": "${item}"},
                    batch={"items": [_payload("oversized-item")], "error_handling": "fail_fast"},
                )
            ],
        }
        path = tmp_path / "wf.pflow.md"
        write_workflow_file(workflow, path)

        text = _cli(str(path))
        as_json = _cli("--output-format", "json", str(path))

        for output in (_everything(text), _everything(as_json)):
            assert "oversized-item" in output
            assert "PAYLOAD-END" not in output

    def _parent(self, tmp_path: Path) -> Path:
        child = _write(tmp_path, CHILD, "child.pflow.md")
        parent = f"""\
# Parent

Fan the failing child over one large item.

## Steps

### fan

Run the child per item.

- type: workflow
- workflow: {child}
- inputs:
    item: ${{item}}
    token: {SECRET}
- batch:
    items: {json.dumps([_payload("big-one")])}
    error_handling: continue
"""
        return _write(tmp_path, parent, "parent.pflow.md")

    def _assert_safe(self, output: str) -> None:
        assert "<REDACTED>" in output
        assert SECRET not in output
        assert "PAYLOAD-START" in output  # the first 200 characters of the item are the copy's
        assert "PAYLOAD-END" not in output

    def test_a_batched_sub_workflow_text_and_json(self, tmp_path: Path) -> None:
        path = self._parent(tmp_path)

        text = _cli(str(path))
        as_json = _cli("--output-format", "json", str(path))

        self._assert_safe(_everything(text))
        self._assert_safe(_everything(as_json))
        steps = json.loads(as_json.stdout)["execution"]["steps"]
        detail = next(s for s in steps if s["node_id"] == "fan")["batch_error_details"][0]
        inner_env = detail["child_failure"]["failures"]["inner"]["data"]["env"]
        assert inner_env["API_TOKEN"] == "<REDACTED>"  # noqa: S105 - the mask, not a secret
        assert inner_env["ITEM"].endswith(" chars — full value: pflow report)")

    def test_a_batched_sub_workflow_through_mcp(self, tmp_path: Path) -> None:
        path = self._parent(tmp_path)

        with pytest.raises(RuntimeError) as caught:
            ExecutionService.execute_workflow(str(path))

        self._assert_safe(str(caught.value))


class TestStaleCopy:
    """Scenario 9 — a step that fails on graph-loop visit 1 and succeeds on visit 2 keeps no copy.

    Regression guard: the node never removes its copy, because a failure moves the step's whole
    output into the failure record (``node_state.mark_node_failed``) and the revisit starts from
    an empty namespace. If that archival ever changes, this is the test that sees a stale copy.
    """

    def test_recovery_removes_the_copy(self, tmp_path: Path) -> None:
        workflow = f"""\
# Recovery

Fail on the first visit, succeed on the second.

## Steps

### maybe-fail

Fails until the marker exists.

- type: shell
- env:
    MARKER: {tmp_path / "marker"}
- on-error: retry
- next: end

```shell command
if [ -f "$MARKER" ]; then echo ok; else touch "$MARKER"; exit 9; fi
```

### retry

Loop back.

- type: shell
- next: maybe-fail

```shell command
echo retrying
```
"""
        result = WorkflowRunner().run(str(_write(tmp_path, workflow)), {}, RunnerConfig(cache_enabled=False))

        assert result.shared_after["retry"]["stdout"] == "retrying"  # visit 1 failed and routed
        assert result.shared_after["maybe-fail"]["stdout"] == "ok"
        assert "env" not in result.shared_after["maybe-fail"]
