"""The clean cutover (Task 185, ADR-0018): a trace under the pre-185 filename is invisible to every lookup —
and every lookup that finds nothing SAYS how many such traces it did not search.

The pre-185 traces here are RENAMED COPIES of traces first shown to be found under their current names, so
each miss is the cutover and nothing else. The paired test runs the same surfaces over an empty directory
and asserts the clause is absent (a clause that always prints would pass the presence test for free).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from pflow.cli.main import cli
from pflow.core.trace_dir import list_traces, paused_marker, workflow_hash
from pflow.runtime.resume_source import load_resume_source
from tests.shared.trace_jsonl import write_trace_file

_WF = """# Demo

Two steps.

## Steps

### one

First.

- type: shell

```shell command
echo one
```

### two

Second.

- type: shell

```shell command
echo two
```
"""

_CLAUSE = "3 traces written by an earlier pflow version are not searched"


def _invoke(*args: str) -> Result:
    return CliRunner(mix_stderr=False).invoke(cli, list(args))


def _event(node_id: str, status: str = "success") -> dict[str, Any]:
    return {"node_id": node_id, "node_type": "ShellNode", "status": status, "node_output": {"stdout": node_id}}


@pytest.fixture
def workflow(tmp_path: Path) -> Path:
    path = tmp_path / "flows" / "demo.pflow.md"
    path.parent.mkdir(parents=True)
    path.write_text(_WF, encoding="utf-8")
    return path


def _write_runs(debug: Path, workflow_path: str) -> dict[str, Path]:
    base = {"format_version": "2.10.0", "workflow_name": "demo", "workflow_path": workflow_path, "only_node": None}
    runs = {
        "success": {**base, "final_status": "success", "nodes": [_event("one"), _event("two")]},
        "failed": {**base, "final_status": "failed", "nodes": [_event("one"), _event("two", "failed")]},
        "paused": {
            **base,
            "final_status": "paused",
            "nodes": [_event("one")],
            "paused_node_id": "two",
            "gate_request": {"node_id": "two", "node_type": "ShellNode", "kind": "action_approval", "preview": {}},
        },
    }
    return {
        status: write_trace_file(
            debug, {**data, "execution_id": str(uuid.uuid4())}, name="demo", started=datetime(2026, 1, 1 + index)
        )
        for index, (status, data) in enumerate(runs.items())
    }


def _id_of(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])["execution_id"]


def _to_pre_185_name(path: Path, workflow_path: str) -> None:
    """Rename a trace to the filename an earlier pflow wrote for it (no id field, no tags)."""
    started = path.name.rsplit("-", 3)[-3:]
    paused_marker(path).unlink(missing_ok=True)
    path.rename(path.with_name(f"workflow-trace-{workflow_hash(workflow_path)}-demo-{'-'.join(started)}"))


def _surfaces(workflow: Path, run_id: str) -> dict[str, str]:
    """Every lookup surface's combined output for a lookup that finds nothing."""
    outputs: dict[str, str] = {}
    for label, args in {
        "report": ["report"],
        "resume <id>": ["resume", run_id],
        "resume <workflow>": ["resume", str(workflow)],
        "resume list": ["resume", "list"],
        "--only": [str(workflow), "--only", "two"],
        "analyze-cache --list-traces": ["analyze-cache", str(workflow), "--list-traces"],
    }.items():
        result = _invoke(*args)
        outputs[label] = result.stdout + result.stderr
    json_list = _invoke("resume", "list", "--output-format", "json")
    assert json.loads(json_list.stdout) == [], "the JSON form stays a bare array"
    outputs["resume list --output-format json (stderr)"] = json_list.stderr
    return outputs


def test_every_lookup_names_the_pre_185_traces_it_did_not_search(workflow: Path) -> None:
    debug = Path.home() / ".pflow" / "debug"
    workflow_path = str(workflow.resolve())
    runs = _write_runs(debug, workflow_path)
    paused_id = _id_of(runs["paused"])

    # Found under the current names first: the data is good, so what follows is the cutover alone.
    listed = _invoke("resume", "list")
    assert paused_id in listed.stdout, listed.stdout
    assert "Using latest trace" in _invoke("report").stderr
    assert _invoke(str(workflow), "--only", "two").exit_code == 0
    failed_id = _id_of(runs["failed"])
    assert load_resume_source(execution_id=failed_id).execution_id == failed_id
    newest = load_resume_source(workflow_path=workflow_path, gate_answer={"approve": True})
    assert newest.execution_id == paused_id

    for path in runs.values():
        _to_pre_185_name(path, workflow_path)
    listing = list_traces(debug)
    assert (listing.traces, listing.legacy_count) == ([], 3)

    for label, output in _surfaces(workflow, paused_id).items():
        assert _CLAUSE in output, f"{label} does not say what it did not search:\n{output}"
    # Every by-id miss also names Retention as a cause — through the preflight re-raise, and for a trace
    # path printed before the file went away.
    by_id = _invoke("resume", paused_id)
    assert "aged out of `runtime.trace_retention_days`" in by_id.stderr, by_id.stderr
    by_path = _invoke("report", str(runs["paused"]))
    assert by_path.exit_code == 1
    assert "Trace file not found" in by_path.stderr
    assert "aged out of `runtime.trace_retention_days`" in by_path.stderr
    assert paused_id not in _invoke("resume", "list").stdout


def test_no_clause_when_there_is_nothing_unsearched(workflow: Path) -> None:
    (Path.home() / ".pflow" / "debug").mkdir(parents=True, exist_ok=True)
    for label, output in _surfaces(workflow, str(uuid.uuid4())).items():
        assert "earlier pflow version" not in output, f"{label} names unsearched traces that do not exist"
