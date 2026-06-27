"""Task 173 — ``run_node_detail`` (the detail panel's one-shot node read) + the ``/api/run-node`` handler.

Hand-written JSONL traces whose CONSUMED keys mirror the producer (meta ← ``workflow_trace._meta_fields``;
event join keys ``node_id``/``ancestor_path``/``port`` ← ``_emit_node_start``; blob lines ← ``intern_event_leaves``).
The join keys are pinned against a REAL collector in ``tests/test_runtime/test_emit_time_trace.py`` — if the
producer shape drifts there, these stay green while the panel breaks (tests/CLAUDE.md pitfall #19). Filenames
are built via the REAL ``format_trace_filename`` so the hash-scoped ``scan_traces`` glob actually matches.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from pflow.core.trace_io import INTERN_MIN_BYTES
from pflow.runtime.workflow_trace import format_trace_filename
from pflow.ui.run_node import run_node_detail
from pflow.ui.server import create_app


def _event(node_id: str, *, ancestor_path: list | None = None, port=None, seq: int = 0, eid: int = 0, **fields) -> dict:
    """One completion ``event`` line. Defaults to a shell node; ``**fields`` override / add payload
    (``node_type``, ``node_params``, ``node_output``, ``llm_call``, ``llm_prompt``, ``status``, ...)."""
    line = {
        "kind": "event",
        "node_id": node_id,
        "id": eid,
        "seq": seq,
        "parent_id": None,
        "ancestor_path": ancestor_path or [],
        "port": port,
        "status": "success",
        "node_type": "ShellNode",
        "duration_ms": 1.0,
    }
    line.update(fields)
    return line


def _write_trace(
    debug: Path, wf: str, ts: str, lines: list[dict], *, execution_id: str = "run-1", complete: bool = True
) -> Path:
    """Write a JSONL trace named EXACTLY as the producer would (real ``format_trace_filename`` → matching
    hash prefix), with ``lines`` as the body between the ``meta`` head and the ``run.complete`` trailer."""
    body: list[dict] = [
        {"kind": "meta", "pflow_trace": "jsonl/1", "workflow_path": wf, "execution_id": execution_id},
        *lines,
    ]
    if complete:
        body.append({"kind": "run.complete", "final_status": "success", "nodes_executed": len(lines)})
    path = debug / format_trace_filename(wf, "wf", ts)
    path.write_text("\n".join(json.dumps(x) for x in body) + "\n", encoding="utf-8")
    return path


def _debug(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    debug = tmp_path / ".pflow" / "debug"
    debug.mkdir(parents=True)
    return debug


# --- discovery + projection ------------------------------------------------


def test_pinned_resolves_run_id_and_projects(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(
        debug,
        wf,
        "20260101-000000-000001",
        [_event("greet", node_params={"command": "echo hi"}, node_output={"stdout": "hi", "exit_code": 0})],
        execution_id="run-a",
    )
    detail = run_node_detail(wf, "run-a", {"node_id": "greet", "ancestor_path": [], "port": None})
    assert detail is not None
    assert detail["node_type"] == "shell"  # tagged, never the raw "ShellNode"
    assert detail["status"] == "success"
    assert detail["input"] == {"command": "echo hi"}
    assert detail["output"] == {"stdout": "hi", "exit_code": 0}
    assert detail["cost_usd"] is None and detail["tokens"] is None


def test_unpinned_uses_discover_live_trace(tmp_path, monkeypatch) -> None:
    """``run_id=None`` → ``discover_live_trace`` (the newest live, else newest finished) — the same trace the
    unpinned overlay follows."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(debug, wf, "20260101-000000-000001", [_event("greet", node_output={"stdout": "hi"})])
    detail = run_node_detail(wf, None, {"node_id": "greet", "ancestor_path": [], "port": None})
    assert detail is not None and detail["node_type"] == "shell"


def test_matches_nested_subworkflow_child_by_ancestor_path(tmp_path, monkeypatch) -> None:
    """The structural ref match descends ancestor_path element-wise on ``(node_id, batch_index)`` — a child
    inside a sub-workflow (non-empty ancestor_path) is distinct from a top-level node of the same name."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    ap = [{"node_id": "call-child", "batch_index": None}]
    _write_trace(
        debug,
        wf,
        "20260101-000000-000001",
        [
            _event("inner", ancestor_path=ap, eid=1, node_output={"r": "child"}),
            _event("inner", ancestor_path=[], eid=2, node_output={"r": "toplevel"}),
        ],
    )
    nested = run_node_detail(wf, "run-1", {"node_id": "inner", "ancestor_path": ap, "port": None})
    top = run_node_detail(wf, "run-1", {"node_id": "inner", "ancestor_path": [], "port": None})
    assert nested is not None and nested["output"] == {"r": "child"}
    assert top is not None and top["output"] == {"r": "toplevel"}


def test_resolves_a_blob(tmp_path, monkeypatch) -> None:
    """A large output leaf is interned as ``{$pflow_blob: digest}`` with the value on a prior ``blob`` line;
    the read accumulates the map and ``substitute_refs`` restores it."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    big = "x" * (INTERN_MIN_BYTES + 10)
    digest = hashlib.md5(big.encode("utf-8"), usedforsecurity=False).hexdigest()
    _write_trace(
        debug,
        wf,
        "20260101-000000-000001",
        [
            {"kind": "blob", "md5": digest, "value": big},
            _event("gen", node_output={"result": {"$pflow_blob": digest}}),
        ],
    )
    detail = run_node_detail(wf, "run-1", {"node_id": "gen", "ancestor_path": [], "port": None})
    assert detail is not None and detail["output"] == {"result": big}


def test_missing_blob_line_returns_none_not_the_sentinel(tmp_path, monkeypatch) -> None:
    """A ``$pflow_blob`` ref with NO matching blob line (corrupt/truncated) survives ``substitute_refs`` →
    the payload is unresolvable → ``None``, never the raw sentinel rendered as content."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(
        debug,
        wf,
        "20260101-000000-000001",
        [_event("gen", node_output={"result": {"$pflow_blob": "deadbeefdeadbeefdeadbeefdeadbeef"}})],
    )
    assert run_node_detail(wf, "run-1", {"node_id": "gen", "ancestor_path": [], "port": None}) is None


def test_last_wins_on_reflush(tmp_path, monkeypatch) -> None:
    """A dead-end re-flush re-emits the same id with a corrected status; the read scans forward and keeps the
    LAST matching event (matching the overlay's per-ref last-wins, and a loop's latest iteration)."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(
        debug,
        wf,
        "20260101-000000-000001",
        [
            _event("n", eid=3, status="cached", node_output={"v": "first"}),
            _event("n", eid=3, status="failed", error="boom", node_output={"v": "corrected"}),
        ],
    )
    detail = run_node_detail(wf, "run-1", {"node_id": "n", "ancestor_path": [], "port": None})
    assert detail is not None
    assert detail["status"] == "failed" and detail["error"] == "boom" and detail["output"] == {"v": "corrected"}


def test_returns_none_for_missing_ref(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(debug, wf, "20260101-000000-000001", [_event("a")])
    assert run_node_detail(wf, "run-1", {"node_id": "nope", "ancestor_path": [], "port": None}) is None


def test_returns_none_for_missing_run(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(debug, wf, "20260101-000000-000001", [_event("a")], execution_id="run-1")
    assert run_node_detail(wf, "ghost", {"node_id": "a", "ancestor_path": [], "port": None}) is None


def test_returns_none_for_a_start_only_stopped_node(tmp_path, monkeypatch) -> None:
    """A crashed/stopped node has only a ``node.start`` on disk (no completion ``event``) — the read matches
    ``kind == "event"`` only, so there's nothing to project → ``None`` (the gate excludes it upstream too)."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(
        debug,
        wf,
        "20260101-000000-000001",
        [
            {
                "kind": "node.start",
                "node_id": "slow",
                "id": 0,
                "seq": 0,
                "parent_id": None,
                "ancestor_path": [],
                "port": None,
                "status": "running",
            }
        ],
        execution_id="run-1",
        complete=False,
    )
    assert run_node_detail(wf, "run-1", {"node_id": "slow", "ancestor_path": [], "port": None}) is None


# --- raw-line read robustness (the truncation-tolerance guard, both directions) ----


def test_truncated_final_line_is_tolerated(tmp_path, monkeypatch) -> None:
    """A mid-flush tail leaves a half-written FINAL line (invalid JSON); the read tolerates it and still
    projects the prior COMPLETE event. Without this, a live poll would 500 on every mid-flush read."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    meta = json.dumps({"kind": "meta", "pflow_trace": "jsonl/1", "workflow_path": wf, "execution_id": "run-1"})
    good = json.dumps(_event("greet", node_output={"stdout": "hi"}))
    truncated = '{"kind": "event", "node_id": "gr'  # half-written line, the file is mid-flush
    path = debug / format_trace_filename(wf, "wf", "20260101-000000-000001")
    path.write_text("\n".join([meta, good, truncated]) + "\n", encoding="utf-8")
    detail = run_node_detail(wf, "run-1", {"node_id": "greet", "ancestor_path": [], "port": None})
    assert detail is not None and detail["output"] == {"stdout": "hi"}


def test_malformed_earlier_line_raises_not_silently_swallowed(tmp_path, monkeypatch) -> None:
    """A malformed line that is NOT the final one is genuine corruption — it must SURFACE (a loud 500),
    never be silently skipped to project the wrong (or no) event. Guards the other direction of the
    truncation-tolerance rule."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    meta = json.dumps({"kind": "meta", "pflow_trace": "jsonl/1", "workflow_path": wf, "execution_id": "run-1"})
    corrupt = '{"kind": "event" BROKEN}'  # invalid JSON, and NOT the last line
    good = json.dumps(_event("greet", node_output={"stdout": "hi"}))
    path = debug / format_trace_filename(wf, "wf", "20260101-000000-000001")
    path.write_text("\n".join([meta, corrupt, good]) + "\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        run_node_detail(wf, "run-1", {"node_id": "greet", "ancestor_path": [], "port": None})


def test_os_error_mid_scan_returns_none(tmp_path, monkeypatch) -> None:
    """An IO error reading the resolved trace (permission / deleted mid-read) degrades to ``None`` → a 404,
    never a 500. Discovery uses ``open()`` so it still resolves; only the reader's ``read_text`` fails."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(debug, wf, "20260101-000000-000001", [_event("greet", node_output={"stdout": "hi"})])

    def _boom(self, *args, **kwargs):
        raise OSError("read failed mid-scan")

    monkeypatch.setattr(Path, "read_text", _boom)
    assert run_node_detail(wf, "run-1", {"node_id": "greet", "ancestor_path": [], "port": None}) is None


# --- secret masking (the review-C1 Critical — nested + list, both sides) ----


def test_redacts_nested_and_list_secrets_in_input_and_output(tmp_path, monkeypatch) -> None:
    """A genuinely RECURSIVE redactor on BOTH input and output: a nested ``headers.Authorization`` and a
    list-of-dicts ``api_key`` are ``<REDACTED>``, an ``access_token`` in node_output too — while a long
    ``command`` and ``model`` pass through FULL (no 100-char truncation; the panel shows the realized
    command/prompt)."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    long_cmd = "echo " + "a" * 300  # > 100 chars → proves NO truncation
    _write_trace(
        debug,
        wf,
        "20260101-000000-000001",
        [
            _event(
                "call",
                node_type="HttpNode",
                node_params={
                    "command": long_cmd,
                    "model": "claude-sonnet-4-5",
                    "headers": {"Authorization": "Bearer sk-secret", "X-Trace": "ok"},
                    "accounts": [{"api_key": "AKIA-secret", "name": "prod"}],
                },
                node_output={"access_token": "tok-secret", "ok": True},
            )
        ],
    )
    detail = run_node_detail(wf, "run-1", {"node_id": "call", "ancestor_path": [], "port": None})
    assert detail is not None
    inp = detail["input"]
    assert inp["headers"]["Authorization"] == "<REDACTED>"  # NESTED key
    assert inp["headers"]["X-Trace"] == "ok"
    assert inp["accounts"][0]["api_key"] == "<REDACTED>"  # list-of-dicts
    assert inp["accounts"][0]["name"] == "prod"
    assert inp["command"] == long_cmd  # FULL — no truncation
    assert inp["model"] == "claude-sonnet-4-5"
    assert detail["output"]["access_token"] == "<REDACTED>"  # noqa: S105 - asserting redaction output, not a secret
    assert detail["output"]["ok"] is True


def test_drops_reserved_underscore_keys_but_keeps_nested_user_keys(tmp_path, monkeypatch) -> None:
    """Reserved internal keys (single-``_`` prefix) must NOT leak to agents — the display-site convention
    (``trace_report`` / ``node_output_formatter``). A sub-workflow host's ``_pflow_child_workflow_paths`` and
    a code node's ``_source_lines`` are dropped; a NESTED user ``_id`` survives (top-level filter only)."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(
        debug,
        wf,
        "20260101-000000-000001",
        [
            _event(
                "host",
                node_type="WorkflowExecutor",
                node_params={"workflow": "./child.pflow.md", "_source_lines": [1, 2]},
                node_output={
                    "_pflow_child_workflow_paths": {"host": "/abs/child.pflow.md"},
                    "child-out": {"_id": "keep"},
                },
            )
        ],
    )
    detail = run_node_detail(wf, "run-1", {"node_id": "host", "ancestor_path": [], "port": None})
    assert detail is not None
    assert "_source_lines" not in detail["input"] and detail["input"]["workflow"] == "./child.pflow.md"
    assert "_pflow_child_workflow_paths" not in detail["output"]
    assert detail["output"]["child-out"] == {"_id": "keep"}  # nested user _id preserved (top-level filter only)


# --- node_type tagging + LLM tokens/cost/response ---------------------------


def test_node_type_is_tagged_never_raw(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(debug, wf, "20260101-000000-000001", [_event("ask", node_type="LLMNode", node_output={})])
    detail = run_node_detail(wf, "run-1", {"node_id": "ask", "ancestor_path": [], "port": None})
    assert detail is not None and detail["node_type"] == "llm"


def test_llm_tokens_cost_and_response(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(
        debug,
        wf,
        "20260101-000000-000001",
        [
            _event(
                "ask",
                node_type="LLMNode",
                llm_call={
                    "model": "m",
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cache_read_input_tokens": 800,
                    "cost_usd": 0.02,
                },
                llm_prompt="resolved prompt",
                llm_response="the answer",
                node_output={},
            )
        ],
    )
    detail = run_node_detail(wf, "run-1", {"node_id": "ask", "ancestor_path": [], "port": None})
    assert detail is not None
    assert detail["tokens"] == {"input": 1000, "output": 200, "cache_read": 800}
    assert detail["cost_usd"] == pytest.approx(0.02)
    assert detail["input"]["llm_prompt"] == "resolved prompt"
    assert detail["output"] == "the answer"  # llm_response is the headline


def test_cached_node_cost_is_zero_converged_with_chip(tmp_path, monkeypatch) -> None:
    """A cached node paid nothing this run; ``event_cost`` reports 0.0 (NOT the retained source-call cost) —
    the panel converges with the hover chip + ``pflow report``."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_trace(
        debug,
        wf,
        "20260101-000000-000001",
        [
            _event(
                "ask",
                node_type="LLMNode",
                status="cached",
                llm_call={"cost_usd": 0.42},
                llm_response="reused",
                node_output={},
            )
        ],
    )
    detail = run_node_detail(wf, "run-1", {"node_id": "ask", "ancestor_path": [], "port": None})
    assert detail is not None and detail["status"] == "cached" and detail["cost_usd"] == 0.0


# --- the /api/run-node handler ---------------------------------------------


class TestRunNodeEndpoint:
    def test_missing_workflow_param_is_400(self) -> None:
        r = TestClient(create_app()).get("/api/run-node", params={"ref": "{}"})
        assert r.status_code == 400

    def test_missing_ref_is_400(self, tmp_path, monkeypatch) -> None:
        _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        r = TestClient(create_app()).get("/api/run-node", params={"workflow": str(wf_file)})
        assert r.status_code == 400

    def test_malformed_ref_is_400(self, tmp_path, monkeypatch) -> None:
        _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        r = TestClient(create_app()).get("/api/run-node", params={"workflow": str(wf_file), "ref": "not-json"})
        assert r.status_code == 400

    def test_unknown_workflow_is_404(self) -> None:
        r = TestClient(create_app()).get("/api/run-node", params={"workflow": "does-not-exist-xyz", "ref": "{}"})
        assert r.status_code == 404

    def test_happy_path_returns_detail(self, tmp_path, monkeypatch) -> None:
        debug = _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        resolved = str(wf_file.resolve())
        _write_trace(debug, resolved, "20260101-000000-000001", [_event("greet", node_output={"stdout": "hi"})])
        ref = json.dumps({"node_id": "greet", "ancestor_path": [], "port": None})
        r = TestClient(create_app()).get("/api/run-node", params={"workflow": str(wf_file), "ref": ref})
        assert r.status_code == 200
        assert r.json()["node_type"] == "shell" and r.json()["output"] == {"stdout": "hi"}

    def test_empty_run_param_follows_newest_not_404(self, tmp_path, monkeypatch) -> None:
        """An empty ``&run=`` means "not pinned" (follow the newest run), not "match the run with id ''"."""
        debug = _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        resolved = str(wf_file.resolve())
        _write_trace(debug, resolved, "20260101-000000-000001", [_event("greet", node_output={"stdout": "hi"})])
        ref = json.dumps({"node_id": "greet", "ancestor_path": [], "port": None})
        r = TestClient(create_app()).get("/api/run-node", params={"workflow": str(wf_file), "ref": ref, "run": ""})
        assert r.status_code == 200 and r.json()["output"] == {"stdout": "hi"}

    def test_no_matching_event_is_404(self, tmp_path, monkeypatch) -> None:
        debug = _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        resolved = str(wf_file.resolve())
        _write_trace(debug, resolved, "20260101-000000-000001", [_event("greet")])
        ref = json.dumps({"node_id": "absent", "ancestor_path": [], "port": None})
        r = TestClient(create_app()).get("/api/run-node", params={"workflow": str(wf_file), "ref": ref})
        assert r.status_code == 404
