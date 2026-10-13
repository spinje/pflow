"""Read-set pins on the public run lookups (Task 185 — "a run is found, not scanned for").

Each lookup lists the trace directory ONCE and opens only the files that belong to its answer. These
tests build one directory mixing the target workflow's runs (paused, attempts, failures, ``--only``, an
unfinished one), other workflows' runs and pauses, and pre-185 names — then record every file each public
lookup opens (every open spelling, ``tests/shared/open_hooks``) and every
``os.scandir`` call. A count on the lister alone would be a tautology (``find_trace`` is a filter); the
set opened by the SURFACE is what the spec bounds.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from pflow.cli.main import main
from pflow.runtime.resume_source import list_paused_runs, load_resume_source
from pflow.runtime.workflow_trace import load_full_run_events
from tests.shared.open_hooks import hook_opens
from tests.shared.trace_jsonl import flatten_trace_to_lines, trace_path_for, write_trace_file

_GATE = {"node_id": "deploy", "node_type": "ShellNode", "kind": "action_approval", "preview": {}}


def _event(node_id: str, status: str = "success") -> dict[str, Any]:
    return {"node_id": node_id, "node_type": "ShellNode", "status": status, "node_output": {"stdout": node_id}}


class _Dir:
    """The mixed directory and the paths the tests name."""

    def __init__(self, home: Path) -> None:
        self.debug = home / ".pflow" / "debug"
        self.debug.mkdir(parents=True)
        self.wf = str(_workflow_file(home, "w"))
        self.paused = self._write("w-paused", self.wf, "20260102-000000", final_status="paused", paused=True)
        self.dead_attempt = self._write(
            "w-dead-attempt", self.wf, "20260103-000000", final_status="failed", nodes=[], resumed_from="w-paused"
        )
        self.success = self._write("w-success", self.wf, "20260104-000000")
        self.older_success = self._write("w-old-success", self.wf, "20260101-000000")
        self.failed_1 = self._write("w-failed-1", self.wf, "20260105-000000", final_status="failed")
        self.failed_2 = self._write("w-failed-2", self.wf, "20260106-000000", final_status="failed")
        self.only = self._write("w-only", self.wf, "20260107-000000", only_node="b")
        self.unfinished = self._unfinished("w-unfinished", self.wf, "20260108-000000")
        self.others: list[Path] = []
        for index in range(5):
            other = str(_workflow_file(home, f"x{index}"))
            self.others.append(self._write(f"x{index}-success", other, f"2025010{index + 1}-000000"))
        self.other_paused = self._write(
            "x0-paused", str(_workflow_file(home, "x0")), "20250110-000000", final_status="paused", paused=True
        )
        # The newest trace of all belongs to ANOTHER workflow: a lookup that ignored the workflow hash would
        # reach it first.
        self.other_unfinished = self._unfinished("x9-unfinished", str(_workflow_file(home, "x9")), "20260110-000000")
        self.legacy = [
            self._legacy("workflow-trace-3a8ac2b2-wf-20260109-000000-000000.json"),
            self._legacy("workflow-trace-3a8ac2b2-20260109-000001.json"),
        ]

    def _write(
        self,
        execution_id: str,
        workflow_path: str,
        started: str,
        *,
        final_status: str = "success",
        nodes: list[dict[str, Any]] | None = None,
        only_node: str | None = None,
        resumed_from: str | None = None,
        paused: bool = False,
    ) -> Path:
        data: dict[str, Any] = {
            "format_version": "2.10.0",
            "execution_id": execution_id,
            "workflow_name": "wf",
            "workflow_path": workflow_path,
            "only_node": only_node,
            "resumed_from": resumed_from,
            "final_status": final_status,
            "nodes": nodes
            if nodes is not None
            else [_event("a"), _event("b", "failed" if final_status == "failed" else "success")],
        }
        if paused:
            data["nodes"] = [_event("a")]
            data["paused_node_id"] = "deploy"
            data["gate_request"] = _GATE
        return write_trace_file(self.debug, data, started=started)

    def _unfinished(self, execution_id: str, workflow_path: str, started: str) -> Path:
        data = {"format_version": "2.10.0", "execution_id": execution_id, "workflow_path": workflow_path, "nodes": []}
        path, data = trace_path_for(self.debug, data, started=started)
        lines = [line for line in flatten_trace_to_lines(data) if line["kind"] != "run.complete"]
        path.write_text("\n".join(map(json.dumps, lines)) + "\n", encoding="utf-8")
        return path

    def _legacy(self, name: str) -> Path:
        path = self.debug / name
        path.write_bytes(self.success.read_bytes())  # readable content: only the name keeps it unsearched
        return path


def _workflow_file(home: Path, stem: str) -> Path:
    path = home / "flows" / f"{stem}.pflow.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {stem}\n", encoding="utf-8")
    return path


@contextmanager
def _recording(monkeypatch: pytest.MonkeyPatch, debug: Path) -> Iterator[tuple[list[tuple[str, str]], list[int]]]:
    """Record ``(trace name, mode)`` for every open of a file in ``debug``, and every ``os.scandir`` of it."""
    opened: list[tuple[str, str]] = []
    scans: list[int] = []
    real_scandir = os.scandir

    def spy(real_open: Callable[..., Any], file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, (str, os.PathLike)) and Path(file).parent == debug:
            opened.append((Path(file).name, mode))
        return real_open(file, mode, *args, **kwargs)

    def scandir_spy(path: Any = ".") -> Any:
        if Path(path) == debug:
            scans.append(1)
        return real_scandir(path)

    with monkeypatch.context() as patched:
        hook_opens(patched, spy)
        patched.setattr(os, "scandir", scandir_spy)
        yield opened, scans


def _names(*paths: Path) -> set[str]:
    return {path.name for path in paths}


@pytest.fixture
def mixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Dir:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    return _Dir(tmp_path)


def test_resume_by_id_reads_the_run_and_its_attempts_only(mixed: _Dir, monkeypatch: pytest.MonkeyPatch) -> None:
    with _recording(monkeypatch, mixed.debug) as (opened, scans):
        source = load_resume_source(execution_id="w-paused", gate_answer={"approve": True})

    assert source.execution_id == "w-paused"
    assert {name for name, _ in opened} == _names(mixed.paused, mixed.dead_attempt)
    assert len(scans) == 1


def test_resume_by_workflow_reads_only_that_workflows_full_runs(mixed: _Dir, monkeypatch: pytest.MonkeyPatch) -> None:
    with _recording(monkeypatch, mixed.debug) as (opened, scans):
        source = load_resume_source(workflow_path=mixed.wf)

    # The unfinished run did no work (a dead zero-work trace): skipped for the newest failed run.
    assert source.execution_id == "w-failed-2"
    assert {name for name, _ in opened} == _names(mixed.unfinished, mixed.failed_2)
    assert len(scans) == 1


def test_resume_list_reads_the_marked_traces_and_their_attempts_only(
    mixed: _Dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _recording(monkeypatch, mixed.debug) as (opened, scans):
        listing = list_paused_runs()

    assert {run.execution_id for run in listing.runs} == {"w-paused", "x0-paused"}
    assert listing.legacy_count == 2
    assert {name for name, _ in opened} == _names(mixed.paused, mixed.other_paused, mixed.dead_attempt)
    assert len(scans) == 1


def test_only_snapshot_tail_reads_until_the_newest_success_and_fully_loads_only_it(
    mixed: _Dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _recording(monkeypatch, mixed.debug) as (opened, scans):
        loaded = load_full_run_events(mixed.wf)

    assert loaded is not None
    assert [event["node_id"] for event in loaded[0]] == ["a", "b"]
    assert {name for name, _ in opened} == _names(mixed.unfinished, mixed.failed_2, mixed.failed_1, mixed.success)
    fully_loaded = {name for name, mode in opened if "b" not in mode}
    assert fully_loaded == _names(mixed.success), "newer failed / unfinished runs cost a tail read, never a load"
    assert len(scans) == 1


def test_only_snapshot_miss_lists_once_and_names_what_it_did_not_search(
    mixed: _Dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The miss path is a lookup too: one enumeration serves the search AND the "not searched" count."""
    from pflow.core.exceptions import OnlySnapshotMissingError
    from pflow.runtime.workflow_trace import load_snapshot_or_raise

    x9 = str(Path(mixed.other_unfinished).parent.parent.parent / "flows" / "x9.pflow.md")
    with _recording(monkeypatch, mixed.debug) as (opened, scans), pytest.raises(OnlySnapshotMissingError) as miss:
        load_snapshot_or_raise(x9, "two")

    assert "2 traces written by an earlier pflow version are not searched" in miss.value.suggestion
    assert {name for name, _ in opened} == _names(mixed.other_unfinished)  # its one (unfinished) trace, tail only
    assert len(scans) == 1


def test_report_auto_select_reads_newest_first_until_the_newest_complete(
    mixed: _Dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _recording(monkeypatch, mixed.debug) as (opened, scans):
        result = CliRunner(mix_stderr=False).invoke(main, ["report"])

    assert result.exit_code == 0, result.stderr
    assert f"Using latest trace: {mixed.only}" in result.stderr
    assert {name for name, _ in opened} == _names(mixed.other_unfinished, mixed.unfinished, mixed.only)
    assert all(name == mixed.only.name for name, mode in opened if "b" not in mode), "tail only for the unfinished"
    assert len(scans) == 1


def test_the_fixture_directory_is_what_the_pins_assume(mixed: _Dir) -> None:
    """Guard against fixture theater: every name parses as intended, so each pin above can fail."""
    from pflow.core.trace_dir import list_traces

    listing = list_traces(mixed.debug)
    assert listing.legacy_count == 2
    by_id = {entry.execution_id: entry for entry in listing.traces}
    assert by_id["w-paused"].paused and by_id["x0-paused"].paused
    assert by_id["w-only"].only
    assert by_id["w-dead-attempt"].resumed_from_prefix == "w-paused"
    assert len(listing.traces) == 8 + 7
    assert listing.traces[0].execution_id == "x9-unfinished"
    assert datetime.strptime(listing.traces[1].started, "%Y%m%d-%H%M%S-%f") == datetime(2026, 1, 8)
