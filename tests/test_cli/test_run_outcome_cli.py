"""The CLI renders the one Run outcome (Task 184): real workflows through ``pflow`` to every ending.

The builder's own rules are pinned in ``tests/test_execution/formatters/test_run_outcome.py``; this
file proves the CLI adapter: the JSON document on stdout, the stderr tiers with and without ``-p``,
identity settled before a failure renders, and lineage on every ending.
"""

from __future__ import annotations

import errno
import json
import re
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from pflow.cli.main import cli
from pflow.runtime.workflow_trace import WorkflowTraceCollector
from tests.test_cli.test_paused_cli import _LOOP_GATE_WF
from tests.test_execution.formatters.test_run_outcome import COMMON_KEYS, IDENTITY_KEYS, METRICS_KEYS

pytestmark = pytest.mark.trace_files

_TOKEN_RE = re.compile(r"Paused at '[^']+'\. Resume token: (\S+) \(exit 4\)")

_OK = """# Ok

Two steps and a declared output.

## Outputs

### verdict

The second step's text.

- source: ${two.stdout}

## Steps

### one

First.

- type: shell

```shell command
echo one-value
```

### two

Second.

- type: shell

```shell command
echo two-value
```
"""

# Strict template resolution raises out of the engine: the runner's exception return path (#699).
_FAIL_BY_EXCEPTION = """# Fail by exception

The second step reads a field the first step's JSON does not have.

## Steps

### first

Emit JSON.

- type: shell

```shell command
echo '{"a": 1}'
```

### second

Read a missing field.

- type: shell
- env: { X: "${first.stdout.b}" }

```shell command
echo "$X"
```
"""

# A non-zero exit is an error ACTION: the runner's normal return path.
_FAIL_BY_ACTION = """# Fail by action

The second step exits 1.

## Steps

### one

First.

- type: shell

```shell command
echo one-value
```

### two

Fail.

- type: shell

```shell command
echo boom >&2; exit 1
```
"""

_GATE = """# Gate

Three steps; the third needs a human approval.

## Steps

### one

First.

- type: shell

```shell command
echo one-value
```

### two

Second.

- type: shell

```shell command
echo two-value
```

### three

Third, gated.

- type: shell
- approval: required

```shell command
{third}
```
"""

# The second step reads a field of the first's text: the validator warns, the run still reaches the gate.
_WARNED_GATE = """# Warned gate

A validator warning, then a gate.

## Steps

### one

Emit JSON.

- type: shell

```shell command
echo '{"a": 1}'
```

### two

Read a field of it.

- type: shell
- env: { X: "${one.stdout.a}" }

```shell command
echo "$X"
```

### three

Gated.

- type: shell
- approval: required

```shell command
echo three-value
```
"""

_REQUIRED_INPUT = """# Needs a topic

One step that needs a required input.

## Inputs

### topic

The topic.

- type: string
- required: true

## Steps

### say

Say it.

- type: shell
- env: { T: "${topic}" }

```shell command
echo "$T"
```
"""

_BATCH = """# Batch

A shell step over two items.

## Steps

### each

Fail per item.

- type: shell
- env: {{ ITEM: "${{item}}" }}

```yaml batch
items: ["a", "b"]
error_handling: continue
```

```shell command
{command}
```
"""
_ALL_ITEMS_FAIL = 'echo "bad $ITEM" >&2; exit 1'
_ONE_ITEM_FAILS = 'if [ "$ITEM" = a ]; then echo "bad $ITEM" >&2; exit 1; fi; echo ok'
# A degraded batch (its warning) before a failing step: a failure that carries a warning.
_WARNED_FAILURE = (
    _BATCH.format(command=_ONE_ITEM_FAILS)
    + """
### fail

Then fail.

- type: shell

```shell command
exit 1
```
"""
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / f"{name}.pflow.md"
    path.write_text(text, encoding="utf-8")
    return path


def _gate(tmp_path: Path, *, third: str = "echo three-value") -> Path:
    return _write(tmp_path, "gate", _GATE.replace("{third}", third))


def _invoke(*args: str | Path) -> Result:
    return CliRunner(mix_stderr=False).invoke(cli, [str(arg) for arg in args])


def _json(*args: str | Path) -> tuple[Result, dict[str, Any]]:
    result = _invoke(*args, "--output-format", "json")
    return result, json.loads(result.stdout)


def _pause(workflow: Path, *extra: str) -> str:
    paused = _invoke(workflow, *extra)
    assert paused.exit_code == 4, paused.stderr
    match = _TOKEN_RE.search(paused.stdout)
    assert match, paused.stdout
    return match.group(1)


def _trailer(trace_path: str) -> dict[str, Any]:
    trailer: dict[str, Any] = json.loads(Path(trace_path).read_text(encoding="utf-8").splitlines()[-1])
    return trailer


def _resumed_line(source_id: str) -> str:
    return f"  ⤷ Resumed from {source_id} at 'three' — 2 upstream steps restored"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / ".pflow" / "debug").mkdir(parents=True)
    return tmp_path


class TestTheSpecsKeyTablesOnRealCliJson:
    """P2-T7: the builder's key tables hold on ``json.loads(stdout)`` of all five endings."""

    @pytest.mark.parametrize(
        ("workflow", "exit_code", "by_status"),
        [
            (_OK, 0, {"result"}),
            (_FAIL_BY_EXCEPTION, 1, {"error", "resume_command"}),
            (_FAIL_BY_ACTION, 1, {"error", "resume_command"}),
        ],
        ids=["success", "failed_by_exception", "failed_by_action"],
    )
    def test_run_endings(self, home: Path, tmp_path: Path, workflow: str, exit_code: int, by_status: set[str]) -> None:
        result, document = _json(_write(tmp_path, "wf", workflow))

        assert result.exit_code == exit_code, result.stderr
        assert document.keys() == COMMON_KEYS | IDENTITY_KEYS | METRICS_KEYS | by_status

    def test_paused_and_denied(self, home: Path, tmp_path: Path) -> None:
        workflow = _gate(tmp_path)
        paused, paused_doc = _json(workflow)
        token = paused_doc["execution_id"]
        denied, denied_doc = _json("resume", token, "--approve", "no")

        assert paused.exit_code == 4, paused.stderr
        assert paused_doc.keys() == COMMON_KEYS | IDENTITY_KEYS | METRICS_KEYS | {"gate", "resume_command"}
        assert denied.exit_code == 3, denied.stderr
        assert denied_doc.keys() == COMMON_KEYS | IDENTITY_KEYS | METRICS_KEYS | {"gate", "error"}
        assert denied_doc["execution"]["resumed_from"] == token


class TestFailureByExceptionKeepsItsMetrics:
    """P2-T1 (#699): the ❌ line and the metrics block on BOTH failure kinds."""

    @pytest.mark.parametrize("workflow", [_FAIL_BY_EXCEPTION, _FAIL_BY_ACTION], ids=["exception", "action"])
    def test_failed_line_and_metrics(self, home: Path, tmp_path: Path, workflow: str) -> None:
        path = _write(tmp_path, "wf", workflow)

        text = _invoke(path)
        _, document = _json(path)

        assert text.exit_code == 1
        assert re.search(r"^❌ Workflow failed (\(1 warnings\) )?after \d+\.\d{3}s$", text.stderr, re.MULTILINE), (
            text.stderr
        )
        assert document["duration_ms"] > 0
        assert document["total_cost_usd"] == 0.0
        assert "workflow" in document["metrics"]


class TestLineageOnFailedAndDenied:
    """P2-T2 (#737): a resumed attempt names its lineage whatever its ending."""

    def test_resumed_then_failed(self, home: Path, tmp_path: Path) -> None:
        token = _pause(_gate(tmp_path, third="exit 1"))

        text = _invoke("resume", token, "--approve", "yes")

        assert text.exit_code == 1
        assert _resumed_line(token) in text.stderr.splitlines()
        assert text.stderr.index("❌ Workflow failed") < text.stderr.index("⤷ Resumed from")

    def test_resumed_then_failed_json(self, home: Path, tmp_path: Path) -> None:
        token = _pause(_gate(tmp_path, third="exit 1"))

        result, document = _json("resume", token, "--approve", "yes")

        assert result.exit_code == 1
        assert document["execution"]["resumed_from"] == token
        assert document["execution"]["nodes_restored"] == 2

    def test_resumed_then_denied_counts_this_attempt_and_names_its_lineage(self, home: Path, tmp_path: Path) -> None:
        token = _pause(_gate(tmp_path))

        text = _invoke("resume", token, "--approve", "no")

        assert text.exit_code == 3
        lines = text.stderr.splitlines()
        assert (
            "✗ Denied at gate 'three'. Workflow stopped cleanly before the step ran. Steps completed: 0 of 3. (exit 3)"
        ) in lines
        assert _resumed_line(token) in lines
        # A human's no is not a failure: the denied line says it, no error block repeats it.
        assert "Error: Gate denied" not in text.stderr
        assert (
            lines.index(_resumed_line(token))
            == lines.index(next(line for line in lines if "Denied at gate" in line)) + 1
        )

    def test_a_fresh_denial_counts_its_steps_and_has_no_lineage(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("pflow.execution.gate_prompt.can_prompt", lambda oc: True)
        monkeypatch.setattr("pflow.execution.gate_prompt.click.confirm", lambda *a, **k: False)

        text = _invoke(_gate(tmp_path))

        assert text.exit_code == 3
        assert (
            "✗ Denied at gate 'three'. Workflow stopped cleanly before the step ran. Steps completed: 2 of 3. (exit 3)"
        ) in text.stderr.splitlines()
        assert "⤷" not in text.stderr
        assert "Workflow trace saved:" in text.stderr


class TestPrintFlagNeverChangesTheJson:
    """P2-T3: ``-p`` is a stderr flag; the document is the same with or without it."""

    _VOLATILE = frozenset({"duration_ms", "execution_id", "trace_path", "node_timings"})

    def _stable(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._stable(item) for key, item in value.items() if key not in self._VOLATILE}
        if isinstance(value, list):
            return [self._stable(item) for item in value]
        return value

    def test_success(self, home: Path, tmp_path: Path) -> None:
        path = _write(tmp_path, "ok", _OK)

        plain, plain_doc = _json(path)
        quiet, quiet_doc = _json(path, "-p")

        assert plain_doc.keys() == quiet_doc.keys()
        assert self._stable(plain_doc) == self._stable(quiet_doc)
        assert plain_doc["result"] == {"verdict": "two-value"}
        assert plain.stderr.count("Workflow trace saved:") == 1
        assert f"Workflow trace saved: {plain_doc['trace_path']}" in plain.stderr
        assert quiet.stderr == ""

    def test_a_resumed_run_keeps_only_its_mode_line_under_print(self, home: Path, tmp_path: Path) -> None:
        token = _pause(_gate(tmp_path))

        quiet, document = _json("resume", token, "--approve", "yes", "-p")

        assert quiet.exit_code == 0, quiet.stderr
        assert document["execution"]["resumed_from"] == token
        assert [line for line in quiet.stderr.splitlines() if line.strip()] == [_resumed_line(token)]


class TestIdentityOnSuccessJson:
    """P2-T4 (#695): the success document names its run and its trace file."""

    def test_identity_matches_the_trace_file(self, home: Path, tmp_path: Path) -> None:
        result, document = _json(_write(tmp_path, "ok", _OK))

        assert result.exit_code == 0
        trace = Path(document["trace_path"])
        assert trace.is_file()
        meta = json.loads(trace.read_text(encoding="utf-8").splitlines()[0])
        assert meta["execution_id"] == document["execution_id"]
        assert _trailer(document["trace_path"])["kind"] == "run.complete"

    def test_no_trace_no_identity(self, home: Path, tmp_path: Path) -> None:
        result, document = _json(_write(tmp_path, "ok", _OK), "--no-trace")

        assert result.exit_code == 0
        assert document["result"] == {"verdict": "two-value"}
        assert not (IDENTITY_KEYS & document.keys())
        assert "Workflow trace saved" not in result.stderr


class _FullDisk:
    """A trace stream whose every write fails the way a full disk does."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def write(self, _text: str) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    def flush(self) -> None:
        """Nothing buffered: every write already failed."""

    def close(self) -> None:
        self._stream.close()


class TestATrailerWriteFaultLeavesNoIdentity:
    """A success's outcome is built before the trailer is written (the trailer snapshots it). When that
    write faults, streaming is disabled and the file has no ``run.complete`` — the run has no trace to name."""

    @staticmethod
    def _fault_the_trailer(monkeypatch: pytest.MonkeyPatch) -> None:
        flush_line = WorkflowTraceCollector._flush_line

        def fault_the_trailer(self: WorkflowTraceCollector, line: dict[str, Any], *, intern: bool = True) -> None:
            if line.get("kind") == "run.complete" and self._stream is not None:
                self._stream = _FullDisk(self._stream)
            flush_line(self, line, intern=intern)

        monkeypatch.setattr(WorkflowTraceCollector, "_flush_line", fault_the_trailer)

    def test_json(self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = _write(tmp_path, "ok", _OK)
        healthy, healthy_document = _json(path)
        self._fault_the_trailer(monkeypatch)

        faulted, document = _json(path)

        assert healthy.exit_code == faulted.exit_code == 0
        assert healthy_document.keys() >= IDENTITY_KEYS
        assert document["result"] == healthy_document["result"] == {"verdict": "two-value"}
        assert not (IDENTITY_KEYS & document.keys())

    def test_text(self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = _write(tmp_path, "ok", _OK)
        healthy = _invoke(path)
        self._fault_the_trailer(monkeypatch)

        faulted = _invoke(path)

        assert healthy.exit_code == faulted.exit_code == 0
        assert faulted.stdout == healthy.stdout == "two-value\n"
        assert "Workflow trace saved:" in healthy.stderr
        assert "Workflow trace saved:" not in faulted.stderr
        assert "✓ Workflow completed in " in faulted.stderr


class TestTiersUnderPrint:
    """P2-T5: ``-p`` hides the summary tier and never the must-act tier — on every status."""

    def test_failure(self, home: Path, tmp_path: Path) -> None:
        path = _write(tmp_path, "warned", _WARNED_FAILURE)

        plain = _invoke(path)
        quiet = _invoke(path, "-p")

        assert plain.exit_code == quiet.exit_code == 1
        for stderr in (plain.stderr, quiet.stderr):
            assert "Error: Execution Failed" in stderr
            assert "To resume from the failed step: pflow resume " in stderr
        for summary in ("⚠️ Warnings:", "Workflow trace saved:", "❌ Workflow failed (1 warnings) after"):
            assert summary in plain.stderr
            assert summary not in quiet.stderr
        # The cause sits last: warnings render before the error block.
        assert plain.stderr.index("⚠️ Warnings:") < plain.stderr.index("Error: Execution Failed")

    def test_pause(self, home: Path, tmp_path: Path) -> None:
        workflow = _gate(tmp_path)

        plain = _invoke(workflow)
        quiet = _invoke(workflow, "-p")

        for result in (plain, quiet):
            assert result.exit_code == 4
            assert _TOKEN_RE.search(result.stdout)
            assert "   command:  echo three-value" in result.stderr.splitlines()
            assert "To answer: pflow resume " in result.stderr
        assert "Workflow trace saved:" in plain.stderr
        assert "Workflow trace saved:" not in quiet.stderr
        assert "⏸" not in plain.stderr  # the stdout token line is the pause's announcement
        assert "To resume from the failed step" not in plain.stderr  # a pause is answered, not resumed

    def test_a_pause_shows_its_warnings_only_without_print(self, home: Path, tmp_path: Path) -> None:
        path = _write(tmp_path, "warned-gate", _WARNED_GATE)
        _, document = _json(path)
        [warning] = document["warnings"]

        plain = _invoke(path)
        quiet = _invoke(path, "-p")

        assert document["status"] == "paused"
        for result in (plain, quiet):
            assert result.exit_code == 4
            assert "To answer: pflow resume " in result.stderr
        assert "⚠️ Warnings:" in plain.stderr
        assert warning["message"] in plain.stderr
        assert "⚠️ Warnings:" not in quiet.stderr
        assert warning["message"] not in quiet.stderr

    def test_the_paused_token_line_comes_before_the_gate_content(self, home: Path, tmp_path: Path) -> None:
        """show-before §3 "text unchanged": the stdout token line announces the pause, then the stderr
        gate lines follow. CliRunner's default mixes both streams into ``output`` in write order."""
        combined = CliRunner().invoke(cli, [str(_gate(tmp_path))])

        assert combined.exit_code == 4
        token_at = combined.output.index("Paused at 'three'. Resume token: ")
        assert token_at < combined.output.index("   command:  echo three-value")
        assert token_at < combined.output.index("To answer: pflow resume ")
        assert combined.output.index("two... ✓") < token_at

    def test_a_failed_batch_shows_its_item_errors_under_print(self, home: Path, tmp_path: Path) -> None:
        path = _write(tmp_path, "batch", _BATCH.format(command=_ALL_ITEMS_FAIL))

        for result in (_invoke(path), _invoke(path, "-p")):
            assert result.exit_code == 1
            assert "Batch 'each' errors:" in result.stderr
            assert "  [0] Command failed with exit code 1: bad a" in result.stderr.splitlines()
            assert "  [1] Command failed with exit code 1: bad b" in result.stderr.splitlines()

    def test_a_degraded_batch_shows_its_item_errors_only_without_print(self, home: Path, tmp_path: Path) -> None:
        path = _write(tmp_path, "batch", _BATCH.format(command=_ONE_ITEM_FAILS))

        plain = _invoke(path)
        quiet = _invoke(path, "-p")

        assert plain.exit_code == quiet.exit_code == 0
        assert "  [0] Command failed with exit code 1: bad a" in plain.stderr.splitlines()
        assert "Batch 'each' errors:" not in quiet.stderr
        assert json.loads(quiet.stdout)["error_count"] == json.loads(plain.stdout)["error_count"] == 1


class TestCompileTimeFailureCarriesIdentity:
    """P2-T8: a failure before the engine ran still names its run — the CLI settles the trace first."""

    def test_json(self, home: Path, tmp_path: Path) -> None:
        result, document = _json(_write(tmp_path, "needs", _REQUIRED_INPUT))

        assert result.exit_code == 2
        assert document["status"] == "failed"
        assert "topic" in document["error"]
        assert document.keys() >= IDENTITY_KEYS
        assert _trailer(document["trace_path"])["kind"] == "run.complete"

    def test_text_names_the_trace_once(self, home: Path, tmp_path: Path) -> None:
        result = _invoke(_write(tmp_path, "needs", _REQUIRED_INPUT))

        assert result.exit_code == 2
        assert result.stderr.count("Workflow trace saved:") == 1


def test_a_looping_gate_paused_again_has_not_completed_its_step(home: Path, tmp_path: Path) -> None:
    """The step a gate stopped has not completed — its loop-carried output says nothing about this attempt."""
    workflow = _write(tmp_path, "loop", _LOOP_GATE_WF)
    marker = tmp_path / "effects.txt"
    first = _pause(workflow, f"marker={marker}")

    result, document = _json("resume", first, "--approve", "yes")

    assert result.exit_code == 4, result.stderr
    assert marker.read_text(encoding="utf-8").splitlines() == ["effect 1"]  # iteration 1 ran, then the gate
    assert document["status"] == "paused"
    assert document["gate"]["node_id"] == "gated"
    assert document["execution"]["steps"][0]["node_id"] == "gated"
    assert document["execution"]["steps"][0]["status"] == "not_executed"
    assert document["execution"]["nodes_executed"] == 0


class TestADenialRendersNoAnswer:
    """P2-T9: a human's no is final — no gate preview, no answer command, no bulk hint after it."""

    @pytest.mark.parametrize("flags", [(), ("-p",)], ids=["text", "print"])
    def test_denied_looping_gate(self, home: Path, tmp_path: Path, flags: tuple[str, ...]) -> None:
        workflow = _write(tmp_path, "loop", _LOOP_GATE_WF)
        marker = tmp_path / "effects.txt"
        first = _pause(workflow, f"marker={marker}")
        second = _invoke("resume", first, "--approve", "yes")
        assert second.exit_code == 4, second.stderr
        token = _TOKEN_RE.search(second.stdout)
        assert token
        # Presence half: the paused run printed all three.
        assert "   Loop iteration 2 of up to 3" in second.stderr.splitlines()
        assert "To answer:" in second.stderr
        assert "To approve this and every remaining iteration" in second.stderr

        denied = _invoke("resume", token.group(1), "--approve", "no", *flags)

        assert denied.exit_code == 3, denied.stderr
        # The loop's carried iteration-1 output is not this attempt completing the step.
        assert "✗ Denied at gate 'gated'. Workflow stopped cleanly before the step ran. Steps completed: 0 of 1." in (
            denied.stderr
        )
        assert f"  ⤷ Resumed from {token.group(1)} at 'gated' (iteration 2)" in denied.stderr
        assert "To answer:" not in denied.stderr
        assert "To approve this and every remaining iteration" not in denied.stderr
        assert "Loop iteration" not in denied.stderr
        assert marker.read_text(encoding="utf-8").splitlines() == ["effect 1"]


# The issue's repro (#815): a step that prints a verdict and exits 3.
_EXIT_3 = """# Exit 3

A step that reports a failure and exits 3.

## Steps

### check

Report and fail.

- type: shell

```shell command
echo '{"ok": false}'; echo "the reason" >&2; exit 3
```
"""

_CHILD_NEEDS_A_NUMBER = """# Child

Needs a number.

## Inputs

### n

A number.

- type: number
- required: true

## Steps

### show

Show it.

- type: shell
- env: { N: "${n}" }

```shell command
echo "$N"
```
"""

# The child's input check fails at RUN time (the value comes from a step): a validation-category
# error inside a run that started.
_PARENT_PASSES_TEXT = """# Parent

Passes text where the child wants a number.

## Steps

### make

Emit text.

- type: shell

```shell command
echo not-a-number
```

### call

Call the child.

- type: workflow
- workflow: {child}
- inputs: {{ n: "${{make.stdout}}" }}
"""


class TestTheExitCodeSaysWhetherTheRunStarted:
    """#815: a wrong call exits 2 and a failed job exits 1 — decided by phase, never by category."""

    def test_a_failed_step_exits_1_and_a_missing_input_exits_2_with_the_same_document_shape(
        self, home: Path, tmp_path: Path
    ) -> None:
        failed, failed_doc = _json(_write(tmp_path, "exit3", _EXIT_3))
        refused, refused_doc = _json(_write(tmp_path, "needs", _REQUIRED_INPUT))

        assert failed.exit_code == 1, failed.stderr
        assert refused.exit_code == 2, refused.stderr
        assert failed_doc["status"] == refused_doc["status"] == "failed"
        assert failed_doc["success"] is refused_doc["success"] is False

    def test_a_validation_error_raised_while_the_run_is_going_is_a_run_failure(
        self, home: Path, tmp_path: Path
    ) -> None:
        child = _write(tmp_path, "child", _CHILD_NEEDS_A_NUMBER)
        parent = _write(tmp_path, "parent", _PARENT_PASSES_TEXT.format(child=child))

        result, document = _json(parent)

        assert result.exit_code == 1, result.stderr
        assert document["errors"][0]["context"]["category"] == "validation"
        assert [(step["node_id"], step["status"]) for step in document["execution"]["steps"]] == [
            ("make", "completed"),
            ("call", "failed"),
        ]

    def test_an_unknown_only_target_is_a_wrong_call(self, home: Path, tmp_path: Path) -> None:
        workflow = _write(tmp_path, "ok", _OK)
        assert _invoke(workflow).exit_code == 0

        result = _invoke("--only", "nosuch", workflow)
        _, document = _json("--only", "nosuch", workflow)

        assert result.exit_code == 2
        assert "Node 'nosuch' not found" in result.stderr
        # Refused before the engine, its trace still says it was an --only attempt — so the snapshot,
        # overlay and analyze-cache readers never take it for a full run.
        meta = json.loads(Path(document["trace_path"]).read_text(encoding="utf-8").splitlines()[0])
        assert meta["kind"] == "meta"
        assert meta["only_node"] == "nosuch"

    def test_only_without_a_snapshot_is_a_run_failure(self, home: Path, tmp_path: Path) -> None:
        """The snapshot is loaded inside the engine, so this stays exit 1 (documented in the table)."""
        result = _invoke("--only", "two", _write(tmp_path, "never-ran", _OK))

        assert result.exit_code == 1
        assert "needs a prior full run" in result.stderr


class TestTheTraceNameAndThePausedMarker:
    """Task 185: the filename carries the run's id, its ``--only`` and lineage tags; a durable pause has a
    ``.paused`` marker beside its trace, written BEFORE the trailer — so a marker that cannot be written
    leaves no durable pause on any surface, and a trailer fault after it leaves nothing listed."""

    @staticmethod
    def _traces(home: Path) -> list[Path]:
        return sorted((home / ".pflow" / "debug").glob("workflow-trace-*.json"))

    def test_a_durable_pause_has_its_marker_and_its_id_in_the_name(self, home: Path, tmp_path: Path) -> None:
        from pflow.core.trace_dir import paused_marker

        token = _pause(_gate(tmp_path))
        [trace] = self._traces(home)
        assert f".{token}-" in trace.name
        assert paused_marker(trace).exists()

    def test_a_marker_write_fault_leaves_a_non_durable_pause_everywhere(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        from pflow.core.trace_dir import parse_trace_filename
        from pflow.runtime.resume_source import list_paused_runs, load_resume_source

        real_open = builtins.open

        def no_marker(file: Any, *args: Any, **kwargs: Any) -> Any:
            if str(file).endswith(".paused"):
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_open(file, *args, **kwargs)

        workflow = _gate(tmp_path)
        with monkeypatch.context() as patched:
            patched.setattr(builtins, "open", no_marker)
            result, document = _json(workflow)

        # The CLI never hands out a token it cannot honour: the pause is reported failed, with no identity.
        assert result.exit_code == 1
        assert document["status"] == "failed"
        assert not (IDENTITY_KEYS & document.keys())
        # On disk: a trace with no trailer (it reads `incomplete`) and no marker.
        [trace] = self._traces(home)
        assert not any('"run.complete"' in line for line in trace.read_text(encoding="utf-8").splitlines())
        assert not trace.with_name(trace.name + ".paused").exists()
        # Every surface agrees it is not a pause: resume takes the interrupted (incomplete) arm — the
        # steps before the gate restored, never the gate's answer path — and `resume list` is empty.
        parsed = parse_trace_filename(trace.name)
        assert parsed is not None and parsed.execution_id
        source = load_resume_source(execution_id=parsed.execution_id)
        assert source.paused_node_id is None and source.gate_request is None
        assert (source.entry_node_id, source.last_completed_node_id) == (None, "two")
        listing = list_paused_runs()
        assert (listing.runs, listing.hidden_missing_file) == ([], [])
        from starlette.testclient import TestClient

        from pflow.ui.server import create_app

        gate = TestClient(create_app(), base_url="http://127.0.0.1").get(
            "/api/gate", params={"run": parsed.execution_id}
        )
        assert gate.status_code == 404 and "not paused" in gate.json()["error"]

    def test_a_trailer_fault_after_the_marker_leaves_nothing_listed(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pflow.core.trace_dir import paused_marker

        workflow = _gate(tmp_path)
        with monkeypatch.context() as patched:
            TestATrailerWriteFaultLeavesNoIdentity._fault_the_trailer(patched)
            result = _invoke(workflow)

        assert result.exit_code == 1, "a pause whose trailer never landed is not durable"
        [trace] = self._traces(home)
        assert paused_marker(trace).exists(), "the marker was written before the trailer"
        listed = _invoke("resume", "list")
        assert listed.stdout == "No paused runs.\n", "every marker consumer reads the trailer and ignores this one"

    def test_only_and_attempt_runs_carry_their_tags(self, home: Path, tmp_path: Path) -> None:
        workflow = _gate(tmp_path)
        token = _pause(workflow)
        answered = _invoke("resume", token, "--approve", "yes")
        assert answered.exit_code == 0, answered.stderr
        only = _invoke(workflow, "--only", "two")
        assert only.exit_code == 0, only.stderr

        names = [trace.name for trace in self._traces(home)]
        [attempt] = [name for name in names if f".from-{token[:8]}" in name]
        [only_run] = [name for name in names if ".only" in name]
        assert ".only" not in attempt and ".from-" not in only_run
        assert sum(1 for name in names if ".only" not in name and ".from-" not in name) == 1  # the source
