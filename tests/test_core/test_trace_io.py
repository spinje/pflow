"""Tests for trace disk interning helpers."""

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from pflow.core.trace_io import (
    BLOB_SENTINEL,
    INTERN_MIN_BYTES,
    TRACE_JSONL_MARKER,
    intern_event_leaves,
    load_trace_file,
    reconstruct_trace_from_lines,
    substitute_refs,
)
from tests.shared.trace_jsonl import flatten_trace_to_lines


def _large_text(prefix: str = "large") -> str:
    return f"{prefix}-" + ("x" * INTERN_MIN_BYTES)


def _assert_blob_ref(value: Any) -> str:
    assert isinstance(value, dict)
    assert set(value) == {BLOB_SENTINEL}
    digest = value[BLOB_SENTINEL]
    assert isinstance(digest, str)
    return digest


def _rich_event() -> dict[str, Any]:
    """A top-level event carrying the full key set ``record_node_execution`` can emit for an
    executed LLM node — locks the passthrough contract (flatten must carry every producer field
    through unchanged), guarding the tests/CLAUDE.md #19 "thin fixture" trap."""
    return {
        "node_id": "a",
        "node_type": "llm",
        "duration_ms": 12.5,
        "success": True,
        "timestamp": "2026-06-08T00:00:00",
        "node_params": {"prompt": "hi"},
        "template_resolutions": {"prompt": {"resolved": "hi"}},
        "node_output": {"response": "ok"},
        "mutations": {"added": ["a"]},
        "llm_call": {"model": "m", "cost_usd": 0.1},
        "llm_prompt": "hi",
        "llm_system": "sys",
        "llm_response": "ok",
    }


def _nested_trace_with_all_shapes(large: str) -> dict[str, Any]:
    """trace_data exercising: a rich top-level event, recursive sub-workflow nesting (grandchild),
    an event with BOTH a batch (incl. the synthetic warmup ``index:-1`` item and a batch-nested
    sub-workflow that must stay buried inline) AND its own ``sub_workflow_events``, and loop recovery
    (same node_id twice)."""
    return {
        "format_version": "2.5.0",
        "execution_id": "run-1",
        "workflow_name": "demo",
        "workflow_path": "/wf.pflow.md",
        "start_time": "T0",
        "only_node": None,  # knowable-at-start → folds into meta
        "end_time": "T1",
        "duration_ms": 5.0,
        "final_status": "success",  # aggregate → trailer
        "nodes_executed": 8,
        "nodes_failed": 0,
        "failed_node_ids": [],
        "llm_summary": {"total_calls": 1},
        "warnings": [{"id": "w"}],  # conditional top-level key (distinct from json_output)
        "json_output": {"answer": "v"},  # conditional top-level key — must survive the fold
        "nodes": [
            _rich_event(),
            {
                "node_id": "b",
                "node_type": "WorkflowExecutor",
                "success": True,
                "sub_workflow_events": [
                    {
                        "node_id": "c",
                        "node_type": "llm",
                        "success": True,
                        "node_output": {"r": large},
                        "sub_workflow_events": [{"node_id": "g", "success": True}],  # grandchild
                    },
                    {"node_id": "d", "success": True},
                ],
            },
            {
                "node_id": "e",
                "node_type": "shell",
                "success": True,
                "sub_workflow_events": [{"node_id": "f", "success": True}],  # promotes
                "batch_items": [  # stays inline
                    {"index": -1, "item": "__cache_warmup__", "success": True, "llm_call": {"is_warmup": True}},
                    {
                        "index": 0,
                        "item": "x",
                        "success": True,
                        "duration_ms": 1.0,
                        # a sub-workflow nested inside a batch item, itself deeper — stays buried inline
                        "events": [
                            {"node_id": "inner", "success": True, "sub_workflow_events": [{"node_id": "buried"}]}
                        ],
                    },
                ],
            },
            {"node_id": "a", "node_type": "shell", "success": True},  # loop-recovery revisit
        ],
    }


def test_flatten_trace_to_lines_contract() -> None:
    large = _large_text()
    trace = _nested_trace_with_all_shapes(large)
    original = copy.deepcopy(trace)
    rich = _rich_event()

    lines = flatten_trace_to_lines(trace)

    assert trace == original  # purity: input untouched

    assert lines[0]["kind"] == "meta"
    assert lines[0]["pflow_trace"] == TRACE_JSONL_MARKER
    assert lines[0]["format_version"] == "2.5.0"
    assert lines[-1]["kind"] == "run.complete"  # inline blobs → no trailer; run.complete is last

    events = [ln for ln in lines if ln["kind"] == "event"]
    run_complete = next(ln for ln in lines if ln["kind"] == "run.complete")

    # DFS pre-order: a, b, (c, (g under c), d under b), e, (f under e), a(revisit)
    assert [ev["node_id"] for ev in events] == ["a", "b", "c", "g", "d", "e", "f", "a"]
    assert [ev["seq"] for ev in events] == list(range(8))
    assert all(ev["id"] == ev["seq"] for ev in events)
    assert all(ev["run_id"] == "run-1" for ev in events)

    by_seq = {ev["seq"]: ev for ev in events}
    assert by_seq[0]["parent_id"] is None  # a (rich)
    assert by_seq[1]["parent_id"] is None  # b
    assert by_seq[2]["parent_id"] == 1  # c under b
    assert by_seq[3]["parent_id"] == 2  # g under c (recursive/deep)
    assert by_seq[4]["parent_id"] == 1  # d under b
    assert by_seq[5]["parent_id"] is None  # e
    assert by_seq[6]["parent_id"] == 5  # f under e (both-channels host)
    assert by_seq[7]["parent_id"] is None  # a revisit

    # passthrough contract: a top-level event line == its original keys + exactly the 5 derived keys
    assert set(by_seq[0]) == set(rich) | {"kind", "id", "seq", "parent_id", "run_id"}

    # loop recovery: two "a" events, distinct ids (id is seq, NEVER node_id)
    a_events = [ev for ev in events if ev["node_id"] == "a"]
    assert len(a_events) == 2 and a_events[0]["id"] != a_events[1]["id"]

    # sub_workflow_events promoted to lines → never left inline on an event line
    assert all("sub_workflow_events" not in ev for ev in events)

    # batch items stay INLINE on the host line: the warmup index:-1 item survives, and a batch-nested
    # sub-workflow (and its deeper nesting) stays buried — none promoted to top-level lines
    e_line = by_seq[5]
    assert e_line["batch_items"][0]["index"] == -1 and e_line["batch_items"][0]["llm_call"]["is_warmup"] is True
    assert e_line["batch_items"][1]["events"][0]["node_id"] == "inner"
    assert e_line["batch_items"][1]["events"][0]["sub_workflow_events"][0]["node_id"] == "buried"
    assert {"inner", "buried"} & {ev["node_id"] for ev in events} == set()

    # generic top-level fold: only_node folds into META (knowable-at-start); conditionals survive
    meta_keys = set(lines[0]) - {"kind", "pflow_trace"}
    trailer_keys = set(run_complete) - {"kind"}
    assert "only_node" in meta_keys
    assert run_complete["json_output"] == {"answer": "v"}
    assert run_complete["warnings"] == [{"id": "w"}]
    assert "final_status" in trailer_keys and "nodes" not in run_complete
    assert meta_keys | trailer_keys == set(trace) - {"nodes"}
    assert meta_keys.isdisjoint(trailer_keys)

    # interning: the large leaf in a promoted sub-workflow event → blob ref on the line, body in an
    # inline {kind:blob} line that PRECEDES the event referencing it (backward-only — crash-tail safe).
    digest = _assert_blob_ref(by_seq[2]["node_output"]["r"])
    blob_line_idx = next(i for i, ln in enumerate(lines) if ln["kind"] == "blob" and ln["md5"] == digest)
    assert lines[blob_line_idx]["value"] == large
    first_ref_idx = next(i for i, ln in enumerate(lines) if ln["kind"] == "event" and ln["seq"] == 2)
    assert blob_line_idx < first_ref_idx, "blob declaration must precede its first reference"


def test_flatten_empty_trace_yields_two_lines() -> None:
    lines = flatten_trace_to_lines({"format_version": "2.5.0", "execution_id": "r", "nodes": []})
    assert [ln["kind"] for ln in lines] == ["meta", "run.complete"]  # inline blobs → no trailer


def test_flatten_rejects_event_with_reserved_correlation_key() -> None:
    trace = {"execution_id": "r", "nodes": [{"node_id": "x", "success": True, "id": "collision"}]}
    with pytest.raises(ValueError, match="reserved correlation"):
        flatten_trace_to_lines(trace)


def test_flatten_preserves_non_json_native_leaf_and_blob_round_trips() -> None:
    # flatten must not choke on a non-JSON-native leaf (default=str coercion is the writer's
    # json.dump job, not flatten's), and the blob refs it leaves must round-trip via substitute_refs.
    large = _large_text()
    ts = datetime(2026, 6, 8)
    trace = {"execution_id": "r", "nodes": [{"node_id": "x", "success": True, "node_output": {"ts": ts, "r": large}}]}

    lines = flatten_trace_to_lines(trace)
    event = next(ln for ln in lines if ln["kind"] == "event")

    assert event["node_output"]["ts"] is ts  # preserved verbatim; stringification is json.dump's job
    blob_map = {ln["md5"]: ln["value"] for ln in lines if ln["kind"] == "blob"}
    restored = substitute_refs(event["node_output"], blob_map)
    assert restored["r"] == large


def test_intern_event_leaves_skips_dunder_subtrees() -> None:
    # #531 (PR review): restores the safety net deleted with intern_blobs's
    # test_reserved_dunder_key_values_are_not_interned. intern_event_leaves — the SURVIVING production
    # interning primitive — carries the same ``__``-prefixed-subtree skip, but the round-trip oracle can't
    # catch its removal (substitute_refs resolves a ref ANYWHERE, so resolution succeeds either way). So a
    # large value under a ``__`` key must be asserted NOT interned, and no blob emitted, directly here.
    large = _large_text()
    emitted: list[str] = []
    out = intern_event_leaves(
        {"__pflow_stats__": {"payload": large}}, set(), lambda digest, _value: emitted.append(digest)
    )
    assert out["__pflow_stats__"] == {"payload": large}  # plain content, not a {BLOB_SENTINEL: ...} ref
    assert emitted == []  # no blob line emitted for a dunder-subtree leaf


def test_flatten_reconstruct_round_trip() -> None:
    # The core invertibility proof: reconstruct(flatten(x)) == x (in-memory, no default=str coercion).
    trace = _nested_trace_with_all_shapes(_large_text())
    assert reconstruct_trace_from_lines(flatten_trace_to_lines(trace)) == trace


def test_inputs_routes_to_meta_line_not_trailer() -> None:
    # Task 175: `inputs` is in META_KEYS, so the fixture builder routes it onto the `meta` line (line 1),
    # NOT the `run.complete` trailer — matching where the real producer (`_meta_fields`) writes it. This
    # is the test-fidelity pin: a Phase-4/5 fixture built via write_trace_jsonl({..., "inputs": {...}})
    # must place `inputs` where the IO-projection readers look (the meta line), or they read the wrong line.
    trace = {
        "format_version": "2.5.0",
        "execution_id": "r",
        "inputs": {"name": "World", "count": 3},
        "nodes": [{"node_id": "a", "success": True}],
    }
    lines = flatten_trace_to_lines(trace)
    meta = lines[0]
    run_complete = next(ln for ln in lines if ln["kind"] == "run.complete")
    assert meta["kind"] == "meta"
    assert meta["inputs"] == {"name": "World", "count": 3}
    assert "inputs" not in run_complete  # NOT in the trailer
    # additive meta field round-trips back to top level
    assert reconstruct_trace_from_lines(lines)["inputs"] == {"name": "World", "count": 3}


def test_load_trace_file_round_trips_jsonl_from_disk(tmp_path: Path) -> None:
    trace = _nested_trace_with_all_shapes(_large_text())
    path = tmp_path / "workflow-trace-x.json"
    path.write_text("\n".join(json.dumps(line) for line in flatten_trace_to_lines(trace)) + "\n", encoding="utf-8")
    assert load_trace_file(path) == trace


# --- #531 safety gate: every TraceFixtureBuilder event shape survives the write_jsonl→load round trip ---
# Removing the analysis-test single-object writes makes the flatten↔reconstruct identity load-bearing for
# EVERY analysis test (they all flow dict → write_trace_jsonl → load_trace_file → analyze). This proves the
# identity holds for each builder event-factory shape the analysis fixtures use — so those tests are correct
# by construction. (Reserved correlation keys are stripped on read; hand-built fixtures never carry them.)
def _builder_event_cases() -> list[tuple[str, dict[str, Any]]]:
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder

    b = TraceFixtureBuilder()
    return [
        ("llm_event", b.llm_event("gen")),
        ("cached_llm_event_thin", b.cached_llm_event_thin("gen")),
        ("cached_llm_event_with_call", b.cached_llm_event_with_call("gen")),
        ("batch_event", b.batch_event("gen", [{"index": 0, "status": "success", "duration_ms": 1.0}])),
        ("workflow_event", b.workflow_event("call", [b.llm_event("child")], workflow_path="child.pflow.md")),
        (
            "heterogeneous_workflow_batch_event",
            b.heterogeneous_workflow_batch_event("call", [("child.pflow.md", [b.llm_event("c")])]),
        ),
        (
            "homogeneous_workflow_batch_event",
            b.homogeneous_workflow_batch_event(
                "call", workflow_path="child.pflow.md", items=[("x", [b.llm_event("c")])]
            ),
        ),
    ]


@pytest.mark.parametrize("name,event", _builder_event_cases(), ids=lambda v: v if isinstance(v, str) else "")
def test_builder_event_shape_round_trips_through_write_jsonl(name: str, event: dict[str, Any], tmp_path: Path) -> None:
    from tests.shared.trace_fixture_builder import TraceFixtureBuilder
    from tests.shared.trace_jsonl import write_trace_jsonl

    trace = TraceFixtureBuilder().trace(workflow_path="/wf.pflow.md", nodes=[event])
    path = write_trace_jsonl(tmp_path / "workflow-trace-fixture.json", trace)
    assert load_trace_file(path) == trace, f"{name} fixture shape did not round-trip through write_jsonl→load"


def test_load_trace_file_rejects_legacy_single_object_format(tmp_path: Path) -> None:
    # #531 skip-regression (review S1) — INVERTS the old dual-read test. A well-formed pre-Task-172
    # single-object trace (valid JSON, NO pflow_trace marker) must now RAISE json.JSONDecodeError, the
    # type all 3 trace readers catch to skip gracefully. This is the load_trace_file half of the central
    # correctness claim: legacy traces no longer load — they raise-then-skip, never crash, never
    # silently load. (The other two reader paths are covered by the report/explicit skip tests.)
    old = {"format_version": "2.5.0", "workflow_name": "old", "nodes": [{"node_id": "a", "node_output": {"r": "x"}}]}
    path = tmp_path / "workflow-trace-old.json"
    path.write_text(json.dumps(old, indent=2), encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_trace_file(path)


def test_reconstruct_trailer_absent_marks_incomplete() -> None:
    lines = [
        ln
        for ln in flatten_trace_to_lines({"execution_id": "r", "nodes": [{"node_id": "a", "success": True}]})
        if ln["kind"] != "run.complete"
    ]
    assert reconstruct_trace_from_lines(lines)["final_status"] == "incomplete"


def test_load_trace_file_raises_jsondecodeerror_on_corrupt_jsonl(tmp_path: Path) -> None:
    # Disk-seam corruption: a marker-bearing JSONL file with a malformed EARLIER line must raise
    # json.JSONDecodeError — the type all 3 trace readers catch to degrade/skip, so a corrupt
    # trace is a visible, distinct state, never a silent half-built dict. (A malformed FINAL line is a
    # tolerated crash-tail — see test_load_trace_file_tolerates_truncated_final_line — so the corruption
    # here is mid-file, with a valid line after it.)
    meta = json.dumps({"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER, "execution_id": "r"})
    good = json.dumps({"kind": "run.complete", "final_status": "success"})
    path = tmp_path / "workflow-trace-corrupt.json"
    path.write_text(f"{meta}\n{{ not valid json\n{good}\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_trace_file(path)


def test_load_trace_file_raises_jsondecodeerror_on_non_utf8(tmp_path: Path) -> None:
    # PR #543: a corrupt / non-UTF-8 file matching the trace glob must raise json.JSONDecodeError (the type
    # every reader catches to skip), NOT the raw UnicodeDecodeError (a ValueError ⊄ OSError) — which would
    # otherwise crash report / analyze-cache / generate_report instead of degrading gracefully.
    path = tmp_path / "workflow-trace-badutf8.json"
    path.write_bytes(b"\xff\xfe\x80\x81 not utf-8\n")
    with pytest.raises(json.JSONDecodeError):
        load_trace_file(path)


def test_reconstruct_unknown_kind_raises() -> None:
    with pytest.raises(json.JSONDecodeError, match="unknown trace line kind"):
        reconstruct_trace_from_lines([{"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER}, {"kind": "bogus"}])


# --- Task 172 step 3: streaming reader (inline blobs + two-pass reconstruct + crash-tail) ---


def _meta_line(**extra: Any) -> dict[str, Any]:
    return {"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER, "execution_id": "r", **extra}


def _event_line(node_id: str, *, eid: int, parent_id: int | None, **extra: Any) -> dict[str, Any]:
    return {"kind": "event", "id": eid, "seq": eid, "parent_id": parent_id, "run_id": "r", "node_id": node_id, **extra}


_RUN_COMPLETE = {"kind": "run.complete", "final_status": "success"}


def test_reconstruct_reads_inline_blob_line() -> None:
    # Streaming writes a singular {kind:blob} line BEFORE the event that first references it; the reader
    # accumulates the map and resolves the ref. (The plural `blobs` trailer arm is gone.)
    large = _large_text()
    digest = hashlib.md5(large.encode("utf-8"), usedforsecurity=False).hexdigest()  # the md5 the writer mints
    lines = [
        _meta_line(),
        {"kind": "blob", "md5": digest, "value": large},
        _event_line("a", eid=0, parent_id=None, node_output={"r": {BLOB_SENTINEL: digest}}),
        _RUN_COMPLETE,
    ]
    trace = reconstruct_trace_from_lines(lines)
    assert trace["nodes"][0]["node_output"]["r"] == large


def test_reconstruct_blob_line_missing_value_raises() -> None:
    # A valid-JSON {kind:blob} line missing its md5/value is corruption — it must RAISE (the last
    # corruption arm, mirroring unknown-kind/orphan). Without the guard, a later event's $pflow_blob ref
    # would never enter blob_map and would survive unresolved as a sentinel dict (silent-wrong content)
    # instead of the visible JSONDecodeError the 3 readers catch to skip.
    lines = [_meta_line(), {"kind": "blob", "md5": "deadbeef"}, _RUN_COMPLETE]  # no "value"
    with pytest.raises(json.JSONDecodeError, match="blob line missing"):
        reconstruct_trace_from_lines(lines)


def test_reconstruct_dedup_by_id_last_wins() -> None:
    # The dead-end re-flush (Piece 5.4) emits a second event line with the SAME id, now status=failed.
    # Pass 1 dedups last-wins, so the correction replaces the original — exactly once in the tree.
    lines = [
        _meta_line(),
        _event_line("x", eid=0, parent_id=None, status="success", node_output={"v": 1}),
        _event_line("x", eid=0, parent_id=None, status="failed", error="dead end"),  # re-flushed correction
        _RUN_COMPLETE,
    ]
    nodes = reconstruct_trace_from_lines(lines)["nodes"]
    assert len(nodes) == 1, "the corrected line must REPLACE the original, not duplicate it"
    assert nodes[0]["status"] == "failed" and nodes[0]["error"] == "dead end"


def test_reconstruct_incomplete_drops_dangling_subtree_and_recovers_prefix() -> None:
    # Crash mid-sub-workflow: children flush before their host's completion event, so a crash leaves them
    # referencing a never-written host. An INCOMPLETE trace (no run.complete) drops the whole dangling
    # subtree (the child, AND its grandchild transitively — the grandchild's parent_id points at the
    # never-linked child id), recovering everything well-formed before the sub-workflow. The full-structure
    # assertion is load-bearing: a `[node_id] == ["top"]` top-level-only check can't tell a clean drop
    # from a dangling node silently re-homed to top level or nested under a recovered node.
    lines = [
        _meta_line(),
        _event_line("top", eid=0, parent_id=None),  # well-formed, survives
        _event_line("child", eid=2, parent_id=1),  # host id=1 never written (crash) → drop
        _event_line("grandchild", eid=3, parent_id=2),  # parent id=2 dropped → grandchild dangles too
        # NO run.complete line → incomplete
    ]
    trace = reconstruct_trace_from_lines(lines)
    assert trace["final_status"] == "incomplete"
    # Reserved keys stripped → top recovers as exactly {"node_id": "top"}, with NO sub_workflow_events and
    # no second top-level node: the dangling subtree was neither re-homed to top level nor nested anywhere.
    assert trace["nodes"] == [{"node_id": "top"}]
    serialized = json.dumps(trace["nodes"])
    assert "child" not in serialized and "grandchild" not in serialized, "dangling subtree must not leak"


def test_reconstruct_complete_trace_orphan_still_raises() -> None:
    # The SAME dangling parent_id in a COMPLETE trace (run.complete present) is corruption, not a crash —
    # it must still raise so the 3 readers skip it rather than silently dropping real data.
    lines = [_meta_line(), _event_line("orphan", eid=0, parent_id=99), _RUN_COMPLETE]
    with pytest.raises(json.JSONDecodeError, match="orphan"):
        reconstruct_trace_from_lines(lines)


def test_load_trace_file_tolerates_truncated_final_line(tmp_path: Path) -> None:
    # D3 crash-tail (REPLACES the deleted A-C whole-trace-skip test): a crash truncating the FINAL line
    # of a streamed trace drops only that line and reconstructs-as-incomplete. With inline-first-occurrence
    # blobs the trailing line is an event/run.complete (never the blobs trailer), so the tolerance is
    # coherent — a backward-only ref means a dropped tail never strands a blob.
    meta = json.dumps(_meta_line())
    good = json.dumps(_event_line("a", eid=0, parent_id=None))
    truncated = '{"kind": "event", "id": 1, "seq": 1, "parent_id": null, "node_i'  # half-written, no newline
    path = tmp_path / "workflow-trace-truncated.json"
    path.write_text(f"{meta}\n{good}\n{truncated}", encoding="utf-8")
    trace = load_trace_file(path)
    assert trace["final_status"] == "incomplete"
    assert [n["node_id"] for n in trace["nodes"]] == ["a"], "the well-formed prefix is recovered"
    # The malformed-EARLIER-line-still-raises half of this contract is pinned by
    # test_load_trace_file_raises_jsondecodeerror_on_corrupt_jsonl (mid-file corruption).


def test_reconstruct_rejects_content_after_run_complete() -> None:
    # run.complete is the FINAL content line (the writer closes the stream right after it). A stray
    # event AFTER it is corruption, not a tolerable crash-tail — the reader must raise so the 3 readers
    # skip the whole trace rather than silently absorb the trailing content and report it complete.
    lines = [
        _meta_line(),
        _event_line("a", eid=0, parent_id=None),
        _RUN_COMPLETE,
        _event_line("late", eid=1, parent_id=None),
    ]
    with pytest.raises(json.JSONDecodeError, match=r"after run\.complete"):
        reconstruct_trace_from_lines(lines)


def test_load_trace_file_rejects_malformed_line_after_run_complete(tmp_path: Path) -> None:
    # A garbage/truncated line AFTER a valid run.complete is corruption, NOT a crash-tail: the writer
    # never writes past run.complete, so the tail tolerance must apply ONLY to a trace that has not yet
    # seen run.complete. Here load_trace_file must raise, not silently drop the tail and report success.
    meta = json.dumps({"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER, "execution_id": "r"})
    complete = json.dumps({"kind": "run.complete", "final_status": "success"})
    garbage = '{"kind": "event", "id": 1, "seq": 1, "parent_i'  # truncated final line
    path = tmp_path / "workflow-trace-after-complete.json"
    path.write_text(f"{meta}\n{complete}\n{garbage}", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_trace_file(path)
