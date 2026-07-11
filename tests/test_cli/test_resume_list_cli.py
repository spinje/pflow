"""``pflow resume list`` — pending paused runs (Task 171, Phase 3e).

A status query over the debug dir: real paused runs appear (token + workflow +
gated step + kind + kind-correct answer footer); answered/superseded tokens and
non-paused traces never do; the JSON shape is a plain array with a per-entry
``resume_command``. The ★oversized-trailer pin covers the one silent-skip
hazard: a paused ``run.complete`` line larger than the 64 KB tail window (the
``gate_request`` rides the trailer) must still be found via the full re-read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from pflow.cli.main import cli

pytestmark = pytest.mark.trace_files

_TOKEN_RE = re.compile(r"Resume token: (\S+)")

_GATE_WF = """# List Demo

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
- approval: required

```shell command
echo "gated action"
```
"""

_FAIL_WF = """# Fail Demo

A workflow whose only step fails.

## Steps

### boom

Always fails.

- type: shell

```shell command
exit 1
```
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".pflow" / "debug").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def gate_wf(tmp_path):
    path = tmp_path / "list_demo.pflow.md"
    path.write_text(_GATE_WF, encoding="utf-8")
    return path


def _runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def _run_to_pause(wf: Path) -> str:
    result = _runner().invoke(cli, [str(wf)])
    assert result.exit_code == 4, result.stderr
    match = _TOKEN_RE.search(result.stdout)
    assert match, f"paused run must print the token; stdout:\n{result.stdout}"
    return match.group(1)


def _write_paused_trace(
    debug_dir: Path,
    *,
    execution_id: str,
    gate_request: dict[str, Any],
    paused_node_id: str = "gated",
    workflow_path: str = "/work/big/wf.pflow.md",
    name: str = "synthetic",
) -> Path:
    """Minimal synthetic paused trace (the builder routes non-META keys onto the trailer)."""
    from pflow.runtime.workflow_trace import format_trace_filename
    from tests.shared.trace_jsonl import write_trace_jsonl

    data: dict[str, Any] = {
        "format_version": "2.7.0",
        "execution_id": execution_id,
        "workflow_name": name,
        "workflow_path": workflow_path,
        "only_node": None,
        "content_hash": "h1",
        "inputs": None,
        "final_status": "paused",
        "end_time": "2026-07-05T00:00:00",
        "nodes": [{"node_id": "prep", "node_type": "ShellNode", "status": "success", "node_output": {"stdout": "x"}}],
        "paused_node_id": paused_node_id,
        "gate_request": gate_request,
    }
    path = debug_dir / format_trace_filename(workflow_path, name, "20260101-000000")
    write_trace_jsonl(path, data)
    return path


def test_paused_run_appears_with_kind_correct_footer(home, gate_wf):
    token = _run_to_pause(gate_wf)
    result = _runner().invoke(cli, ["resume", "list"])
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert token in out
    assert "list_demo" in out
    assert "gated" in out
    assert "approval" in out
    assert "TOKEN" in out and "AGE" in out  # the column header row
    assert "To answer: pflow resume <TOKEN> --approve yes|no" in out
    # No escalation rows → no --choose template line.
    assert "--choose" not in out


def test_answered_run_disappears_from_list(home, gate_wf):
    token = _run_to_pause(gate_wf)
    answered = _runner().invoke(cli, ["resume", token, "--approve", "yes"])
    assert answered.exit_code == 0, answered.stderr
    result = _runner().invoke(cli, ["resume", "list"])
    assert result.exit_code == 0, result.stderr
    assert "No paused runs." in result.stdout
    assert token not in result.stdout


def test_json_shape_and_empty_state(home, gate_wf):
    # Empty state first: the literal empty array, parseable.
    empty = _runner().invoke(cli, ["resume", "list", "--output-format", "json"])
    assert empty.exit_code == 0, empty.stderr
    assert json.loads(empty.stdout) == []

    token = _run_to_pause(gate_wf)
    result = _runner().invoke(cli, ["resume", "list", "--output-format", "json"])
    assert result.exit_code == 0, result.stderr
    document = json.loads(result.stdout)
    assert len(document) == 1
    entry = document[0]
    assert entry["execution_id"] == token
    assert entry["paused_node_id"] == "gated"
    assert entry["gate_kind"] == "action_approval"
    assert entry["workflow_name"] == "list_demo"
    assert entry["resume_command"] == f"pflow resume {token} --approve yes|no"
    assert entry["paused_at"]  # the trailer end_time made it through
    assert Path(entry["path"]).exists()


def test_failed_run_is_not_listed(home, tmp_path):
    wf = tmp_path / "fail_demo.pflow.md"
    wf.write_text(_FAIL_WF, encoding="utf-8")
    failed = _runner().invoke(cli, [str(wf)])
    assert failed.exit_code == 1
    result = _runner().invoke(cli, ["resume", "list"])
    assert result.exit_code == 0
    assert "No paused runs." in result.stdout


def test_oversized_trailer_is_still_listed(home):
    """★ A paused trailer larger than the 64 KB tail window (many sub-1KB preview
    fields, so blob interning never shrinks it) must still be found — pins the
    full re-read branch in ``_read_trailer_line``; without it ``resume list``
    silently hides a legitimate pending gate."""
    preview = {f"field_{i}": "v" * 900 for i in range(100)}  # ~90 KB of un-internable leaves
    gate_request = {
        "node_id": "gated",
        "node_type": "ShellNode",
        "kind": "action_approval",
        "preview": preview,
        "question": None,
        "options": [],
        "recommendation": None,
    }
    path = _write_paused_trace(home / ".pflow" / "debug", execution_id="big-run", gate_request=gate_request)
    # Precondition: the trailer line really exceeds the tail window.
    trailer_line = path.read_text(encoding="utf-8").splitlines()[-1]
    assert len(trailer_line.encode()) > 65536, "fixture must exceed the 64 KB window to pin the re-read"

    result = _runner().invoke(cli, ["resume", "list"])
    assert result.exit_code == 0, result.stderr
    assert "big-run" in result.stdout


def test_escalation_entry_renders_choose_footer(home):
    gate_request = {
        "node_id": "esc",
        "node_type": "EscalatingNode",
        "kind": "decision_escalation",
        "preview": {},
        "question": "which db?",
        "options": [{"label": "keep"}, {"label": "drop"}],
        "recommendation": "keep",
    }
    _write_paused_trace(
        home / ".pflow" / "debug", execution_id="esc-run", gate_request=gate_request, paused_node_id="esc"
    )
    result = _runner().invoke(cli, ["resume", "list"])
    assert result.exit_code == 0, result.stderr
    assert "escalation" in result.stdout
    assert 'To answer: pflow resume <TOKEN> --choose "<answer or option number>"' in result.stdout
