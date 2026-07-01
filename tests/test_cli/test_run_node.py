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
from pflow.ui.run_node import read_run_inputs, run_node_detail
from pflow.ui.server import create_app


def _local(*args: object, **kwargs: object) -> TestClient:
    """A TestClient with a loopback Host — the ``_LoopbackOnly`` guard 403s TestClient's default
    ``testserver`` Host (a real browser/CLI on the loopback server always sends a loopback Host)."""
    kwargs.setdefault("base_url", "http://127.0.0.1")
    return TestClient(*args, **kwargs)  # type: ignore[arg-type]


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


def test_returns_none_for_a_trace_corrupt_after_its_meta_line(tmp_path, monkeypatch) -> None:
    # PR #543: a trace with a valid (discoverable) meta line but invalid UTF-8 bytes later must degrade to
    # None (→ 404), not crash the handler — `_read_matching_event`'s whole-file `read_text` would otherwise
    # raise UnicodeDecodeError (⊄ OSError). (A fully-non-UTF-8 file is skipped earlier, at discovery.)
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    meta = {"kind": "meta", "pflow_trace": "jsonl/1", "workflow_path": wf, "execution_id": "run-1"}
    path = debug / format_trace_filename(wf, "wf", "20260101-000000-000001")
    path.write_bytes((json.dumps(meta) + "\n").encode("utf-8") + b"\xff\xfe garbage \x80\n")
    assert run_node_detail(wf, "run-1", {"node_id": "a", "ancestor_path": [], "port": None}) is None


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


# --- Task 175: IO-node projection (input → meta.inputs, output → json_output.result) -------


def _write_io_trace(
    debug: Path,
    wf: str,
    ts: str,
    *,
    inputs: dict | None = None,
    json_output: dict | None = None,
    execution_id: str = "run-1",
) -> Path:
    """A JSONL trace whose ``meta`` carries ``inputs`` (the Task-175 keystone) and whose ``run.complete``
    carries ``json_output`` — the two lines the IO projection reads (IO nodes have no event line)."""
    meta: dict = {"kind": "meta", "pflow_trace": "jsonl/1", "workflow_path": wf, "execution_id": execution_id}
    if inputs is not None:
        meta["inputs"] = inputs
    trailer: dict = {"kind": "run.complete", "final_status": "success", "nodes_executed": 0}
    if json_output is not None:
        trailer["json_output"] = json_output
    path = debug / format_trace_filename(wf, "wf", ts)
    path.write_text("\n".join(json.dumps(x) for x in (meta, trailer)) + "\n", encoding="utf-8")
    return path


def test_io_input_projects_meta_inputs_value_in_valid_shape(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(debug, wf, "20260101-000000-000010", inputs={"name": "World", "count": 3})
    detail = run_node_detail(wf, "run-1", {"node_id": "name", "ancestor_path": [], "port": "in"})
    assert detail is not None
    # isRunNodeDetail-valid: string node_type + string status + input/output keys (the frontend guard)
    assert isinstance(detail["node_type"], str) and isinstance(detail["status"], str)
    assert "input" in detail and "output" in detail
    assert detail["node_type"] == "input"
    assert detail["input"] == {"name": "World"}  # keyed by the input name; value RAW (not stringified)
    assert detail["output"] is None
    assert detail["duration_ms"] is None and detail["tokens"] is None  # an IO node has no execution metrics


def test_io_input_secret_named_is_redacted(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(debug, wf, "20260101-000000-000010", inputs={"api_key": "sk-secret-123"})
    detail = run_node_detail(wf, "run-1", {"node_id": "api_key", "ancestor_path": [], "port": "in"})
    # redaction matches on the PORT NAME (api_key) — the trace stores the raw secret (redacted on read).
    assert detail is not None and detail["input"] == {"api_key": "<REDACTED>"}


def test_io_output_projects_json_output_result(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(debug, wf, "20260101-000000-000010", json_output={"result": {"greeting": "Hello World"}})
    detail = run_node_detail(wf, "run-1", {"node_id": "greeting", "ancestor_path": [], "port": "out"})
    assert detail is not None
    assert detail["node_type"] == "output"
    assert detail["output"] == "Hello World"
    assert detail["input"] == {}


def test_io_subworkflow_ref_sharing_a_name_returns_none_not_toplevel(tmp_path, monkeypatch) -> None:
    """The collision guard (load-bearing): meta.inputs / json_output.result are bare-name-keyed TOP-LEVEL
    values, so a SUB-workflow IO node named like a top-level one (non-empty ancestor_path) must return None,
    NOT borrow the top-level value."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(debug, wf, "20260101-000000-000010", inputs={"name": "World"})
    ap = [{"node_id": "child", "batch_index": None}]
    assert run_node_detail(wf, "run-1", {"node_id": "name", "ancestor_path": ap, "port": "in"}) is None


def test_io_missing_input_returns_none(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(debug, wf, "20260101-000000-000010", inputs={"other": "x"})
    assert run_node_detail(wf, "run-1", {"node_id": "name", "ancestor_path": [], "port": "in"}) is None


def test_io_output_with_no_json_output_returns_none(tmp_path, monkeypatch) -> None:
    """A text-mode or failed run records no json_output → an output ref degrades to None (the panel shows
    "no recorded value"), never a crash."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(debug, wf, "20260101-000000-000010", inputs={"name": "World"})  # no json_output
    assert run_node_detail(wf, "run-1", {"node_id": "greeting", "ancestor_path": [], "port": "out"}) is None


# --- Task 175: re-run prefill (read_run_inputs → /api/run-inputs token strings) -------


def test_read_run_inputs_tokens_round_trip_faithfully_through_the_cli_parser(tmp_path, monkeypatch) -> None:
    """Re-run FAITHFULNESS — the feature's core promise (load a past run → submit → reproduce it).

    Two assertions, one dense test:
    1. FORWARD: read_run_inputs renders each value via format_param_value (str as-is, numbers→str,
       bool→lowercase, list/dict→COMPACT JSON) — the token shape the form controls consume. Catches a
       wrong-formatter regression (e.g. str()/repr() → ``['a', 'b']`` that infer_type can't re-parse).
    2. ROUND-TRIP: those tokens, submitted as the server's ``name=value`` argv (one element per input, no
       shell — exactly ``server.run``'s construction), re-type to the ORIGINAL typed values through the REAL
       ``parse_workflow_params`` the spawned run uses. THIS is the faithfulness the whole re-run rides on;
       it catches an ``infer_type`` regression (which the forward assertion alone misses) on the LIVE path.
       (The only other round-trip pin is coupled to the orphaned ``rerun_display`` module and goes via
       ``shlex`` — a different transport that dies with that module.)"""
    from pflow.cli.param_parsing import parse_workflow_params

    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    # Representative resolved-value types meta.inputs holds. (A string that LOOKS numeric is deliberately
    # excluded: meta.inputs stores the RESOLVED value and declared-type coercion — not parse_workflow_params
    # alone — restores it on re-run; that channel-A interplay is a separate, pre-existing CLI concern.)
    original = {"name": "World", "count": 3, "flag": True, "tags": ["a", "b"], "cfg": {"k": 1}}
    _write_io_trace(debug, wf, "20260101-000000-000020", inputs=original)

    tokens = read_run_inputs(wf, "run-1")
    assert tokens == {"name": "World", "count": "3", "flag": "true", "tags": '["a","b"]', "cfg": '{"k":1}'}
    reparsed = parse_workflow_params(tuple(f"{name}={value}" for name, value in tokens.items()))
    assert reparsed == original, "a re-run must reconstruct the exact typed values it loaded"


def test_read_run_inputs_omits_sensitive_named_keys(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(debug, wf, "20260101-000000-000020", inputs={"topic": "cats", "api_key": "sk-secret"})
    # a past run's resolved secret never reaches the browser — OMITTED (not redacted-in-place); it
    # re-resolves from settings/env by name at run time, or the user types an override.
    assert read_run_inputs(wf, "run-1") == {"topic": "cats"}


def test_read_run_inputs_omits_inputs_with_a_nested_secret(tmp_path, monkeypatch) -> None:
    """F1 (Codex P1): an object/list input whose TOP-LEVEL name isn't sensitive but that carries a nested
    sensitive key (``config.api_key``, a list-of-dict ``token``) must be OMITTED whole — else
    format_param_value would JSON-encode the resolved secret into a prefill token the browser sees. The
    top-level-name check alone leaks it; the recursive ``_redact`` (the same one ``_io_detail`` uses) catches
    it, matching the display path's redaction."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(
        debug,
        wf,
        "20260101-000000-000020",
        inputs={"topic": "cats", "config": {"region": "us", "api_key": "sk-secret"}, "creds": [{"token": "t"}]},
    )
    # config (nested api_key) and creds (list-of-dict token) are omitted; only the clean topic survives.
    assert read_run_inputs(wf, "run-1") == {"topic": "cats"}


def test_read_run_inputs_none_for_unknown_run(tmp_path, monkeypatch) -> None:
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(debug, wf, "20260101-000000-000020", inputs={"topic": "cats"})
    assert read_run_inputs(wf, "ghost-run") is None


def test_read_run_inputs_empty_for_trace_predating_meta_inputs(tmp_path, monkeypatch) -> None:
    """An older trace with no ``meta.inputs`` → ``{}`` (the run exists; the picker shows it with nothing to
    prefill), distinct from ``None`` (no such run → 404)."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(debug, wf, "20260101-000000-000020")  # no inputs= → meta carries no "inputs" key
    assert read_run_inputs(wf, "run-1") == {}


def test_read_run_inputs_omits_none_valued_keys(tmp_path, monkeypatch) -> None:
    """A None-valued input (e.g. an authored ``default: null``) is OMITTED, not rendered as the literal
    token ``"None"`` — which ``infer_type`` would re-type to the STRING ``"None"`` on re-run (a silent
    null→"None" change). Omitting it lets it re-resolve to its default, like the form's blank-omission."""
    debug = _debug(tmp_path, monkeypatch)
    wf = str(tmp_path / "wf.pflow.md")
    _write_io_trace(debug, wf, "20260101-000000-000020", inputs={"topic": "cats", "opt": None})
    assert read_run_inputs(wf, "run-1") == {"topic": "cats"}


@pytest.mark.trace_files
def test_cli_json_run_records_json_output_result_on_run_complete(tmp_path, monkeypatch) -> None:
    """The output-port projection (``_io_detail`` port ``"out"``) reads ``run.complete.json_output["result"]
    [name]``. That trailer is populated only if the CLI's ``set_json_output`` runs BEFORE ``finalize()`` —
    the ordering the fixture-based IO tests assume. Pin it end-to-end through the REAL CLI json path (the
    output-side twin of ``test_meta_inputs``'s write-ordering pin): a refactor finalizing before
    ``set_json_output`` would silently blank every output panel while the fixture tests stay green."""
    from click.testing import CliRunner

    from pflow.cli.main import main

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    wf = tmp_path / "outwf.pflow.md"
    wf.write_text(
        "# OutWf\n\nEchoes a greeting.\n\n## Inputs\n\n### name\n\nWho to greet.\n\n- type: string\n- default: World\n\n"
        '## Steps\n\n### greet\n\nGreets.\n\n- type: shell\n- cache: false\n- command: echo "Hello ${name}"\n\n'
        "## Outputs\n\n### greeting\n\nThe greeting.\n\n- source: ${greet.stdout}\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(main, [str(wf), "--output-format", "json", "name=Alice"])
    assert result.exit_code == 0, result.output

    traces = list((tmp_path / ".pflow" / "debug").glob("*.json"))
    assert len(traces) == 1, traces
    lines = [json.loads(ln) for ln in traces[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    trailer = next(ln for ln in lines if ln.get("kind") == "run.complete")
    assert trailer["json_output"]["result"]["greeting"].strip() == "Hello Alice"


class TestRunInputsEndpoint:
    def test_missing_workflow_is_400(self) -> None:
        r = _local(create_app()).get("/api/run-inputs", params={"run": "x"})
        assert r.status_code == 400

    def test_unknown_workflow_is_404(self) -> None:
        r = _local(create_app()).get("/api/run-inputs", params={"workflow": "no-such-workflow-xyz", "run": "x"})
        assert r.status_code == 404

    def test_happy_path_returns_tokens_without_secrets(self, tmp_path, monkeypatch) -> None:
        debug = _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        resolved = str(wf_file.resolve())
        _write_io_trace(debug, resolved, "20260101-000000-000020", inputs={"name": "World", "api_key": "sk-secret"})
        r = _local(create_app()).get("/api/run-inputs", params={"workflow": str(wf_file), "run": "run-1"})
        assert r.status_code == 200
        assert r.json() == {"name": "World"}

    def test_unknown_run_is_404(self, tmp_path, monkeypatch) -> None:
        debug = _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        resolved = str(wf_file.resolve())
        _write_io_trace(debug, resolved, "20260101-000000-000020", inputs={"name": "World"})
        r = _local(create_app()).get("/api/run-inputs", params={"workflow": str(wf_file), "run": "ghost"})
        assert r.status_code == 404


# --- the /api/run-node handler ---------------------------------------------


class TestRunNodeEndpoint:
    def test_missing_workflow_param_is_400(self) -> None:
        r = _local(create_app()).get("/api/run-node", params={"ref": "{}"})
        assert r.status_code == 400

    def test_missing_ref_is_400(self, tmp_path, monkeypatch) -> None:
        _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        r = _local(create_app()).get("/api/run-node", params={"workflow": str(wf_file)})
        assert r.status_code == 400

    def test_malformed_ref_is_400(self, tmp_path, monkeypatch) -> None:
        _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        r = _local(create_app()).get("/api/run-node", params={"workflow": str(wf_file), "ref": "not-json"})
        assert r.status_code == 400

    def test_unknown_workflow_is_404(self) -> None:
        r = _local(create_app()).get("/api/run-node", params={"workflow": "does-not-exist-xyz", "ref": "{}"})
        assert r.status_code == 404

    def test_happy_path_returns_detail(self, tmp_path, monkeypatch) -> None:
        debug = _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        resolved = str(wf_file.resolve())
        _write_trace(debug, resolved, "20260101-000000-000001", [_event("greet", node_output={"stdout": "hi"})])
        ref = json.dumps({"node_id": "greet", "ancestor_path": [], "port": None})
        r = _local(create_app()).get("/api/run-node", params={"workflow": str(wf_file), "ref": ref})
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
        r = _local(create_app()).get("/api/run-node", params={"workflow": str(wf_file), "ref": ref, "run": ""})
        assert r.status_code == 200 and r.json()["output"] == {"stdout": "hi"}

    def test_no_matching_event_is_404(self, tmp_path, monkeypatch) -> None:
        debug = _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        resolved = str(wf_file.resolve())
        _write_trace(debug, resolved, "20260101-000000-000001", [_event("greet")])
        ref = json.dumps({"node_id": "absent", "ancestor_path": [], "port": None})
        r = _local(create_app()).get("/api/run-node", params={"workflow": str(wf_file), "ref": ref})
        assert r.status_code == 404

    def test_io_input_ref_returns_200_with_projected_value(self, tmp_path, monkeypatch) -> None:
        # End-to-end through the handler: an IO ref (port "in") projects meta.inputs, no event needed.
        debug = _debug(tmp_path, monkeypatch)
        wf_file = tmp_path / "wf.pflow.md"
        wf_file.write_text("# x")
        resolved = str(wf_file.resolve())
        _write_io_trace(debug, resolved, "20260101-000000-000010", inputs={"name": "World"})
        ref = json.dumps({"node_id": "name", "ancestor_path": [], "port": "in"})
        r = _local(create_app()).get("/api/run-node", params={"workflow": str(wf_file), "ref": ref})
        assert r.status_code == 200
        assert r.json()["node_type"] == "input" and r.json()["input"] == {"name": "World"}
