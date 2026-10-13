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
    workflow_path: str | None = None,
    name: str = "synthetic",
) -> Path:
    """Minimal synthetic paused trace (the builder routes non-META keys onto the trailer) plus its
    ``.paused`` marker. Its workflow file is created under the test's HOME (a pause is listed only while
    its workflow file exists) unless the test names its own ``workflow_path``."""
    from tests.shared.trace_jsonl import write_trace_file

    if workflow_path is None:
        workflow_file = debug_dir.parent.parent / "work" / "big" / "wf.pflow.md"
        workflow_file.parent.mkdir(parents=True, exist_ok=True)
        workflow_file.write_text("# wf\n", encoding="utf-8")
        workflow_path = str(workflow_file)
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
    return write_trace_file(debug_dir, data, name=name, started="20260101-000000")


def test_paused_run_appears_with_kind_correct_footer(home, gate_wf):
    token = _run_to_pause(gate_wf)
    result = _runner().invoke(cli, ["resume", "list"])
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert token in out
    assert "list_demo" in out
    assert "gated" in out
    assert "approval" in out
    assert "· iteration" not in out  # not a loop step (test_paused_cli pins the loop row)
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
    assert entry["iteration"] is None
    assert entry["max_iterations"] is None  # present and null on a non-loop row (loop rows: test_paused_cli)
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
    fields, so blob interning never shrinks it) must still be found — ``resume list``
    reads trailers through the oversized-safe ``trace_dir.read_trace_trailer`` (its full
    re-read branch is pinned in ``test_trace_dir.py``); a reader without it silently
    hides a legitimate pending gate."""
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


_APPROVAL_GATE = {
    "node_id": "gated",
    "node_type": "ShellNode",
    "kind": "action_approval",
    "preview": {},
    "question": None,
    "options": [],
    "recommendation": None,
}


def test_a_pause_whose_workflow_file_is_gone_is_hidden_counted_and_refused(home):
    """Task 185: a pause is listed only while its workflow file exists — a by-id resume re-resolves the file
    and refuses without it, so listing the row would offer a dead command. The hidden pause is COUNTED
    (never silent), and the same trace is listed again once the file is back."""
    run_id = "0b7e6a52-1c4d-4e8f-9a3b-5d6c7e8f9a0b"  # uuid-shaped: `pflow resume <id>` takes the by-id arm
    workflow_file = home / "work" / "gone.pflow.md"
    workflow_file.parent.mkdir(parents=True)
    workflow_file.write_text("# gone\n", encoding="utf-8")
    _write_paused_trace(
        home / ".pflow" / "debug",
        execution_id=run_id,
        gate_request=_APPROVAL_GATE,
        workflow_path=str(workflow_file),
    )
    assert run_id in _runner().invoke(cli, ["resume", "list"]).stdout

    workflow_file.unlink()
    text = _runner().invoke(cli, ["resume", "list"])
    assert text.stdout == "No paused runs.\n1 paused run is not listed: its workflow file no longer exists.\n"
    as_json = _runner().invoke(cli, ["resume", "list", "--output-format", "json"])
    assert json.loads(as_json.stdout) == []
    assert "1 paused run is not listed: its workflow file no longer exists." in as_json.stderr
    refused = _runner().invoke(cli, ["resume", run_id, "--approve", "yes"])
    assert refused.exit_code == 2  # the resume refuses the same pause the list hid
    assert "The workflow for this run no longer exists" in refused.stderr

    workflow_file.write_text("# gone\n", encoding="utf-8")
    assert run_id in _runner().invoke(cli, ["resume", "list"]).stdout


def test_a_pause_whose_workflow_file_cannot_be_checked_is_listed_with_a_note(home, monkeypatch):
    """A permission fault on the workflow file is "cannot tell", not "deleted": the row stays (the pause
    may still be answerable) and says so."""
    import os

    workflow_file = home / "work" / "locked.pflow.md"
    workflow_file.parent.mkdir(parents=True)
    workflow_file.write_text("# locked\n", encoding="utf-8")
    _write_paused_trace(
        home / ".pflow" / "debug",
        execution_id="unsure-pause",
        gate_request=_APPROVAL_GATE,
        workflow_path=str(workflow_file),
        name="locked",
    )
    real_stat = os.stat

    def denied_for_the_workflow(path, *args, **kwargs):
        if str(path) == str(workflow_file):
            raise PermissionError(13, "Permission denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", denied_for_the_workflow)
    result = _runner().invoke(cli, ["resume", "list"])
    assert "unsure-pause" in result.stdout
    assert "locked (workflow file unreadable)" in result.stdout
    assert "not listed" not in result.stdout
