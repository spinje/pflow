"""Task 175 — Producer: the eager ``meta`` line records the run's resolved inputs (the keystone).

The Runner stamps ``trace_collector.inputs`` on the ROOT collector AFTER the defaults merge and BEFORE
``engine.run()`` (which calls ``start_streaming()`` and flushes the meta line at t=0). These tests drive a
REAL workflow through ``WorkflowRunner`` and read the on-disk streamed trace's FIRST line — so they prove
the value correctness AND the load-bearing write-ordering (a meta line written at stream-open already
carries ``inputs`` ⟹ the stamp ran before streaming). Marked ``trace_files`` so streaming actually writes;
``Path.home`` is redirected to ``tmp_path`` so the debug dir is isolated.

Why read the meta line raw (not ``load_trace_file``): the keystone is the EAGER meta line placement, and
later phases (4/5) read ``meta.inputs`` off that line — so the test pins the exact wire the consumers read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pflow.execution import WorkflowRunner
from pflow.execution.result import RunnerConfig


def _read_meta_line(debug_dir: Path) -> dict:
    """Return the first (``meta``) line of the single streamed trace in ``debug_dir``."""
    traces = list(debug_dir.glob("*.json"))
    assert len(traces) == 1, f"expected exactly one streamed trace, found {traces}"
    first = traces[0].read_text(encoding="utf-8").splitlines()[0]
    return json.loads(first)


def _read_lines(debug_dir: Path) -> list[dict]:
    traces = list(debug_dir.glob("*.json"))
    assert len(traces) == 1, f"expected exactly one streamed trace, found {traces}"
    return [json.loads(ln) for ln in traces[0].read_text(encoding="utf-8").splitlines() if ln.strip()]


@pytest.mark.trace_files
def test_meta_inputs_records_user_and_default_values(tmp_path, monkeypatch):
    """A user-provided input AND a default-sourced input both land in ``meta.inputs``, RAW (typed)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    wf = tmp_path / "greet.pflow.md"
    wf.write_text(
        "# Greet\n\nGreets someone.\n\n## Inputs\n\n"
        "### name\n\nWho to greet.\n\n- type: string\n- default: World\n\n"
        "### count\n\nHow many times.\n\n- type: integer\n- default: 3\n\n"
        '## Steps\n\n### greet\n\nEchoes a greeting.\n\n- type: shell\n- command: echo "hi ${name} ${count}"\n',
        encoding="utf-8",
    )

    result = WorkflowRunner().run(str(wf), {"name": "Alice"}, config=RunnerConfig())
    assert result.success

    meta = _read_meta_line(tmp_path / ".pflow" / "debug")
    # user value overrides default; the untouched input falls back to its default — both recorded.
    assert meta["inputs"] == {"name": "Alice", "count": 3}
    # RAW, not stringified: integer stays an int (the re-run faithfulness contract depends on this).
    assert isinstance(meta["inputs"]["count"], int)


@pytest.mark.trace_files
def test_meta_inputs_empty_for_no_input_workflow(tmp_path, monkeypatch):
    """A workflow with no declared inputs records ``meta.inputs == {}`` (never missing, never None)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    wf = tmp_path / "noinput.pflow.md"
    wf.write_text(
        "# NoInput\n\nNo declared inputs.\n\n## Steps\n\n"
        "### hello\n\nSays hello.\n\n- type: shell\n- command: echo hi\n",
        encoding="utf-8",
    )

    result = WorkflowRunner().run(str(wf), {}, config=RunnerConfig())
    assert result.success

    meta = _read_meta_line(tmp_path / ".pflow" / "debug")
    assert meta["inputs"] == {}


@pytest.mark.trace_files
def test_meta_inputs_present_for_inline_content_run(tmp_path, monkeypatch):
    """An inline content-string run (synthetic ``ir-hash:`` workflow_path) records ``meta.inputs`` too —
    the stamp is IR-driven, so it is independent of how the workflow was resolved (path/library/inline)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    content = (
        "# Inline\n\nInline workflow.\n\n## Inputs\n\n"
        "### topic\n\nThe topic.\n\n- type: string\n- default: cats\n\n"
        '## Steps\n\n### echo\n\nEchoes the topic.\n\n- type: shell\n- command: echo "${topic}"\n'
    )

    result = WorkflowRunner().run(content, {"topic": "dogs"}, config=RunnerConfig())
    assert result.success

    meta = _read_meta_line(tmp_path / ".pflow" / "debug")
    assert meta["inputs"] == {"topic": "dogs"}


@pytest.mark.trace_files
def test_meta_inputs_records_required_input_value_not_placeholder(tmp_path, monkeypatch):
    """A required input (no default) is filled with a validation PLACEHOLDER by `_fill_declared_defaults`,
    then stripped by `_strip_placeholders` BEFORE the shared store is seeded — so its USER value (not the
    `__pflow_declared_*` placeholder) reaches `meta.inputs`. Guards the strip-before-seed ordering: a
    refactor that seeded the store before stripping would silently record a fake placeholder value."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    wf = tmp_path / "required.pflow.md"
    wf.write_text(
        "# Required\n\nHas a required input.\n\n## Inputs\n\n"
        "### subject\n\nThe subject (required, no default).\n\n- type: string\n\n"
        '## Steps\n\n### greet\n\nGreets the subject.\n\n- type: shell\n- command: echo "hi ${subject}"\n',
        encoding="utf-8",
    )

    result = WorkflowRunner().run(str(wf), {"subject": "Alice"}, config=RunnerConfig())
    assert result.success

    meta = _read_meta_line(tmp_path / ".pflow" / "debug")
    assert meta["inputs"] == {"subject": "Alice"}
    # no validation placeholder leaked into the record
    assert not any(isinstance(v, str) and v.startswith("__pflow_declared_") for v in meta["inputs"].values())


@pytest.mark.trace_files
def test_meta_inputs_on_eager_meta_line_before_node_events(tmp_path, monkeypatch):
    """Write-ordering pin (LOAD-BEARING): the FIRST line is the ``meta`` line carrying populated
    ``inputs``, and the node-execution event lines follow it. The meta line is flushed by
    ``start_streaming()`` at run start (t=0), so its carrying ``inputs`` proves the Runner's stamp ran
    BEFORE streaming. A future refactor moving the stamp past the first flush (e.g. into the engine after
    node 1) would leave ``inputs: null`` on this already-written line — this test would catch it."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    wf = tmp_path / "ordered.pflow.md"
    wf.write_text(
        "# Ordered\n\nOne input, one node.\n\n## Inputs\n\n"
        "### who\n\nThe subject.\n\n- type: string\n- default: world\n\n"
        '## Steps\n\n### greet\n\nGreets the subject.\n\n- type: shell\n- command: echo "hi ${who}"\n',
        encoding="utf-8",
    )

    result = WorkflowRunner().run(str(wf), {"who": "team"}, config=RunnerConfig())
    assert result.success

    lines = _read_lines(tmp_path / ".pflow" / "debug")
    assert lines[0]["kind"] == "meta"
    assert lines[0]["inputs"] == {"who": "team"}  # populated on the eager (line-1) meta line
    # the first node actually executed — at least one event line follows the meta line.
    assert any(ln.get("kind") == "event" for ln in lines[1:])
