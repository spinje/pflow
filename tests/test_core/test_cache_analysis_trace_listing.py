"""Trace discovery tests for analyze-cache --list-traces."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pflow.core.cache_analysis.analyze import (
    _resolve_current_workflow_model_set,
    list_traces_for_workflow,
)
from pflow.core.cache_analysis.render_traces_list import render_traces_list_json, render_traces_list_text


def _write_workflow(tmp_path: Path, *, model: str = "anthropic/claude-sonnet-4-5") -> Path:
    path = tmp_path / "wf.pflow.md"
    path.write_text(
        f"""# Trace List

## Steps

### review

Review each record.

- type: llm
- model: {model}

```prompt
Summarize this.
```
""",
        encoding="utf-8",
    )
    return path


def _write_heterogeneous_workflow(tmp_path: Path) -> Path:
    path = tmp_path / "wf.pflow.md"
    path.write_text(
        """# Trace List

## Steps

### review

Review the trace subject.

- type: llm
- batch:
    items: ${items}
    as: record
    parallel: false
- model: ${record.model}

```prompt
Summarize ${record.text}.
```
""",
        encoding="utf-8",
    )
    return path


def _trace_name(workflow_path: str, suffix: str) -> str:
    wf_hash = hashlib.md5(workflow_path.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"workflow-trace-{wf_hash}-wf-{suffix}.json"


def _write_trace(
    debug_dir: Path,
    workflow_path: str,
    suffix: str,
    *,
    status: str = "success",
    models: list[str] | None = None,
) -> Path:
    trace_path = debug_dir / _trace_name(workflow_path, suffix)
    trace_path.write_text(
        json.dumps({
            "format_version": "2.3.0",
            "workflow_path": workflow_path,
            "final_status": status,
            "start_time": "2026-05-15T12:00:00",
            "duration_ms": 1234,
            "llm_summary": {
                "total_calls": 2,
                "total_cost_usd": 0.0123,
                "models_used": models or ["anthropic/claude-sonnet-4-5"],
            },
            "nodes": [],
        }),
        encoding="utf-8",
    )
    return trace_path


def test_list_traces_marks_newest_successful_autoload_choice(tmp_path: Path) -> None:
    workflow = _write_workflow(tmp_path)
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    old_success = _write_trace(debug_dir, str(workflow), "20260515-100000", status="success")
    new_failed = _write_trace(debug_dir, str(workflow), "20260515-110000", status="failed")

    entries, note = list_traces_for_workflow(str(workflow), debug_dir=debug_dir)
    text = render_traces_list_text(entries, workflow_path=str(workflow), disclosure_note=note)

    assert [entry.path for entry in entries] == [new_failed, old_success]
    assert [entry.path for entry in entries if entry.would_be_autoloaded] == [old_success]
    assert note is not None
    assert "Skipped newer trace" in note
    assert f"path: {old_success}" in text
    assert f"--from-trace {old_success}" in text


def test_list_traces_empty_directory_renders_helpful_empty_result(tmp_path: Path) -> None:
    workflow = _write_workflow(tmp_path)
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()

    entries, note = list_traces_for_workflow(str(workflow), debug_dir=debug_dir)
    text = render_traces_list_text(entries, workflow_path=str(workflow), disclosure_note=note)

    assert entries == []
    assert "No traces found" in text


def test_list_traces_skips_corrupted_trace_file(tmp_path: Path) -> None:
    workflow = _write_workflow(tmp_path)
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    (debug_dir / _trace_name(str(workflow), "20260515-100000")).write_text("{bad json", encoding="utf-8")

    entries, _note = list_traces_for_workflow(str(workflow), debug_dir=debug_dir)

    assert entries == []


def test_list_traces_json_emits_mode_and_null_drift_for_heterogeneous_workflow(tmp_path: Path) -> None:
    workflow = _write_heterogeneous_workflow(tmp_path)
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    _write_trace(debug_dir, str(workflow), "20260515-100000")
    entries, note = list_traces_for_workflow(str(workflow), debug_dir=debug_dir)

    payload = json.loads(render_traces_list_json(entries, workflow_path=str(workflow), disclosure_note=note))
    text = render_traces_list_text(entries, workflow_path=str(workflow), disclosure_note=note)

    assert payload["format_version"].startswith("5.")
    assert payload["mode"] == "list_traces"
    assert entries[0].model_drift_count is None
    assert payload["traces"][0]["model_drift_count"] is None
    assert "comparison skipped (workflow has heterogeneous-model nodes)" in text


def test_current_model_set_distinguishes_heterogeneous_from_unresolvable() -> None:
    models, has_heterogeneous = _resolve_current_workflow_model_set(
        {
            "nodes": [
                {"id": "hetero", "type": "llm", "batch": {"as": "record"}, "params": {"model": "${record.model}"}},
                {"id": "unknown", "type": "llm", "params": {"model": "${settings.model}"}},
                {"id": "static", "type": "llm", "params": {"model": "anthropic/claude-sonnet-4-5"}},
            ]
        },
        None,
    )

    assert has_heterogeneous is True
    assert models == frozenset({"anthropic/claude-sonnet-4-5"})
