"""Task 171 — the PAUSED CLI surface: exit 4, token emission, gate content, JSON document.

The paused display contract (plan 1d): the resume token is the paused run's DATA
(stdout, even under ``-p``); the gate content + the exact answer command ride
stderr so an agent can compose the answer without a blind resume round-trip.
``--no-trace`` keeps the pre-171 hard failure (exit 1) with the updated message
naming the flag as the removable blocker.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from pflow.cli.main import cli

pytestmark = pytest.mark.trace_files

_TOKEN_RE = re.compile(r"Paused at 'gated'\. Resume token: (\S+) \(exit 4\)")

_GATE_WF = """# Paused Demo

A workflow whose second step needs a human approval.

## Steps

### g1

Upstream value.

- type: shell
- next: gated

```shell command
echo "g1-value"
```

### gated

Requires a human approval decision before running.

- type: shell
- env: { API_KEY: sk-super-secret }
- approval: required

```shell command
echo "gated action"
```
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".pflow" / "debug").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def gate_wf(tmp_path):
    path = tmp_path / "paused_demo.pflow.md"
    path.write_text(_GATE_WF)
    return path


def _runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def test_paused_run_exits_4_with_token_and_gate_content(home, gate_wf):
    result = _runner().invoke(cli, [str(gate_wf)])
    assert result.exit_code == 4, result.stderr
    # ONE parseable stdout line — the token resolves against a real trace file.
    match = _TOKEN_RE.search(result.stdout)
    assert match, f"stdout must carry the token line; stdout:\n{result.stdout}"
    token = match.group(1)
    traces = list((home / ".pflow" / "debug").glob("workflow-trace-*.json"))
    assert len(traces) == 1
    assert token in traces[0].read_text(encoding="utf-8")
    # stderr renders the gate CONTENT (the approval preview, secret-masked) and
    # the exact answer command.
    assert "command:" in result.stderr
    assert "gated action" in result.stderr
    assert "<REDACTED>" in result.stderr
    assert "sk-super-secret" not in result.stderr
    assert f"To answer: pflow resume {token} --approve yes|no" in result.stderr
    # The pre-flight warning speaks the post-171 outcome (pause, not fail —
    # "fail" stays only for --no-trace, pinned in test_approval_gate_cli).
    assert "will pause at approval gate(s) [gated]" in result.stderr


def test_paused_token_survives_print_mode(home, gate_wf):
    result = _runner().invoke(cli, [str(gate_wf), "-p"])
    assert result.exit_code == 4
    assert _TOKEN_RE.search(result.stdout)
    # The answer hint rides stderr, which -p does not silence for pauses.
    assert "--approve yes|no" in result.stderr


def test_paused_json_document_shape(home, gate_wf):
    result = _runner().invoke(cli, [str(gate_wf), "--output-format", "json"])
    assert result.exit_code == 4, result.stderr
    document = json.loads(result.stdout)
    assert document["success"] is False
    assert document["status"] == "paused"
    assert document["paused_node_id"] == "gated"
    assert document["resume_command"] == f"pflow resume {document['execution_id']} --approve yes|no"
    # REQUIRED keys for generic success:false handlers — present and empty.
    assert document["errors"] == []
    assert document["diagnostics"] == []
    # The gate payload is self-contained but secret-masked (same policy as the
    # denied document's gate payload).
    gate = document["gate_request"]
    assert gate["kind"] == "action_approval"
    assert gate["preview"]["env"]["API_KEY"] == "<REDACTED>"
    assert "gated action" in gate["preview"]["command"]


def test_no_trace_gate_keeps_hard_failure_with_updated_message(home, gate_wf):
    """--no-trace stays an explicit opt-out whose gates keep the hard error —
    and the error must NAME --no-trace as the removable blocker (plan 1f)."""
    result = _runner().invoke(cli, ["--no-trace", str(gate_wf)])
    assert result.exit_code == 1, result.stderr
    assert "Resume token" not in result.stdout
    assert "--no-trace" in result.stderr
    assert "pause durably" in result.stderr.lower() or "Gates pause durably" in result.stderr


def test_stream_fault_pause_falls_through_to_failed(home, gate_wf, monkeypatch):
    """Mid-run disk fault (plan 1d fall-through): the trailer never reached disk,
    so no token may print and the exit-1 error document must NOT claim "paused" —
    the status is normalized to failed. This is the ONE case the display's
    `_stream_failed` check defends (the runner's trace_enabled gate covers
    --no-trace)."""
    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    def _fail_open(self):
        self._disable_streaming(OSError("disk full"))

    monkeypatch.setattr(WorkflowTraceCollector, "_open_stream", _fail_open)
    result = _runner().invoke(cli, [str(gate_wf), "--output-format", "json"])
    assert result.exit_code == 1, result.stderr
    document = json.loads(result.stdout)
    assert document["status"] == "failed"
    assert "Resume token" not in result.stdout
    # No dead-end affordance either: there is no file to resume from, so the
    # error document must not advertise a resume_command the loader would refuse.
    assert "resume_command" not in document
