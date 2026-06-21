"""Tests for trace disk interning helpers."""

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from pflow.core.trace_io import (
    BLOB_SENTINEL,
    INTERN_MIN_BYTES,
    TRACE_JSONL_MARKER,
    flatten_trace_to_lines,
    intern_blobs,
    load_trace_file,
    reconstruct_trace_from_lines,
    resolve_blobs,
    substitute_refs,
)


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
    assert lines[-1]["kind"] == "blobs"

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

    # interning: the large leaf in a promoted sub-workflow event → blob ref on the line, body in trailer
    digest = _assert_blob_ref(by_seq[2]["node_output"]["r"])
    assert lines[-1]["blobs"][digest] == large


def test_flatten_empty_trace_yields_three_lines() -> None:
    lines = flatten_trace_to_lines({"format_version": "2.5.0", "execution_id": "r", "nodes": []})
    assert [ln["kind"] for ln in lines] == ["meta", "run.complete", "blobs"]
    assert lines[-1]["blobs"] == {}


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
    restored = substitute_refs(event["node_output"], lines[-1]["blobs"])
    assert restored["r"] == large


def test_flatten_reconstruct_round_trip() -> None:
    # The core invertibility proof: reconstruct(flatten(x)) == x (in-memory, no default=str coercion).
    trace = _nested_trace_with_all_shapes(_large_text())
    assert reconstruct_trace_from_lines(flatten_trace_to_lines(trace)) == trace


def test_load_trace_file_round_trips_jsonl_from_disk(tmp_path: Path) -> None:
    trace = _nested_trace_with_all_shapes(_large_text())
    path = tmp_path / "workflow-trace-x.json"
    path.write_text("\n".join(json.dumps(line) for line in flatten_trace_to_lines(trace)) + "\n")
    assert load_trace_file(path) == trace


def test_load_trace_file_still_reads_old_nested_format(tmp_path: Path) -> None:
    # Dual-read: a legacy single-object (interned) trace must still load after the JSONL switch.
    large = _large_text()
    old = {"format_version": "2.5.0", "workflow_name": "old", "nodes": [{"node_id": "a", "node_output": {"r": large}}]}
    path = tmp_path / "workflow-trace-old.json"
    path.write_text(json.dumps(intern_blobs(old), indent=2))
    assert load_trace_file(path) == old


def test_reconstruct_trailer_absent_marks_incomplete() -> None:
    lines = [
        ln
        for ln in flatten_trace_to_lines({"execution_id": "r", "nodes": [{"node_id": "a", "success": True}]})
        if ln["kind"] != "run.complete"
    ]
    assert reconstruct_trace_from_lines(lines)["final_status"] == "incomplete"


def test_reconstruct_orphan_parent_raises() -> None:
    lines = [
        {"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER, "execution_id": "r"},
        {"kind": "event", "id": 0, "seq": 0, "parent_id": 99, "run_id": "r", "node_id": "orphan"},
        {"kind": "blobs", "blobs": {}},
    ]
    with pytest.raises(json.JSONDecodeError, match="orphan"):
        reconstruct_trace_from_lines(lines)


def test_load_trace_file_raises_jsondecodeerror_on_corrupt_jsonl(tmp_path: Path) -> None:
    # Disk-seam corruption: a marker-bearing JSONL file with a malformed line must raise
    # json.JSONDecodeError — the type all 3 trace readers catch to degrade/skip, so a corrupt
    # trace is a visible, distinct state, never a silent half-built dict.
    path = tmp_path / "workflow-trace-corrupt.json"
    path.write_text(
        json.dumps({"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER, "execution_id": "r"}) + "\n{ not valid json\n"
    )
    with pytest.raises(json.JSONDecodeError):
        load_trace_file(path)


def test_load_trace_file_skips_truncated_tail_line(tmp_path: Path) -> None:
    # Crash-tail scope (A-C, PR #525 review): a crash that truncates the FINAL line of a JSONL trace
    # (a half-written event — no closing brace, no trailing newline) makes load_trace_file raise
    # json.JSONDecodeError, so the 3 readers skip the whole trace; it is NOT reconstructed as
    # final_status="incomplete". save_to_file writes the entire file (incl. trailers) in one end-of-run
    # flush, so trailer-less files are rare and this window is narrow today. Robust trailing-line
    # tolerance (drop only the truncated last line → incomplete) is deferred to Phase D / Task 172,
    # where D3 inline blobs make the trailing line an event/run.complete rather than the `blobs` trailer.
    meta = json.dumps({"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER, "execution_id": "r"})
    good_event = json.dumps({"kind": "event", "id": 0, "seq": 0, "parent_id": None, "run_id": "r", "node_id": "a"})
    truncated = '{"kind": "event", "id": 1, "seq": 1, "parent_id": null, "node_i'  # half-written, no newline
    path = tmp_path / "workflow-trace-truncated.json"
    path.write_text(f"{meta}\n{good_event}\n{truncated}")
    with pytest.raises(json.JSONDecodeError):
        load_trace_file(path)


def test_reconstruct_unknown_kind_raises() -> None:
    with pytest.raises(json.JSONDecodeError, match="unknown trace line kind"):
        reconstruct_trace_from_lines([{"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER}, {"kind": "bogus"}])


def test_round_trip_identity_for_nested_trace_shapes() -> None:
    large = _large_text()
    trace = {
        "format_version": "2.4.0",
        "workflow_name": "demo",
        "nodes": [
            {
                "node_id": "parent",
                "node_output": {"result": large},
                "batch_items": [
                    {
                        "item_index": 0,
                        "events": [
                            {
                                "node_id": "item-node",
                                "node_output": {"value": large},
                            }
                        ],
                    }
                ],
                "sub_workflow_events": [
                    {
                        "node_id": "child",
                        "llm_prompt": [
                            {
                                "type": "text",
                                "text": large,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                ],
            }
        ],
        "__pflow_stats__": {"debug": large},
    }

    assert resolve_blobs(intern_blobs(trace)) == trace


def test_threshold_interns_only_strings_at_or_above_min_bytes() -> None:
    small = "s" * (INTERN_MIN_BYTES - 1)
    exact = "e" * INTERN_MIN_BYTES

    encoded = intern_blobs({"small": small, "exact": exact})

    assert encoded["small"] == small
    digest = _assert_blob_ref(encoded["exact"])
    assert encoded["blobs"] == {digest: exact}


def test_reserved_dunder_key_values_are_not_interned() -> None:
    large = _large_text()

    encoded = intern_blobs({"__pflow_stats__": {"payload": large}})

    assert encoded["__pflow_stats__"] == {"payload": large}
    assert encoded["blobs"] == {}


def test_identical_large_leaves_share_one_blob() -> None:
    large = _large_text()

    encoded = intern_blobs({"left": large, "right": {"nested": large}})

    left_digest = _assert_blob_ref(encoded["left"])
    right_digest = _assert_blob_ref(encoded["right"]["nested"])
    assert left_digest == right_digest
    assert encoded["blobs"] == {left_digest: large}


def test_block_text_leaf_is_interned_without_touching_siblings() -> None:
    large = _large_text()
    trace = {
        "messages": [
            {
                "type": "text",
                "text": large,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    }

    encoded = intern_blobs(trace)

    digest = _assert_blob_ref(encoded["messages"][0]["text"])
    assert encoded["blobs"] == {digest: large}
    assert encoded["messages"][0]["cache_control"] == {"type": "ephemeral"}
    assert resolve_blobs(encoded) == trace


def test_resolve_and_load_are_noop_for_old_uninterned_traces(tmp_path: Path) -> None:
    trace = {"format_version": "2.4.0", "nodes": [{"node_output": {"result": "small"}}]}
    trace_path = tmp_path / "workflow-trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    assert resolve_blobs(trace) == trace
    assert load_trace_file(trace_path) == trace


def test_malformed_blob_map_degrades_to_noop() -> None:
    trace = {"nodes": [{"value": {BLOB_SENTINEL: "missing"}}], "blobs": "not-a-map"}

    assert resolve_blobs(trace) is trace


def test_resolve_removes_only_top_level_blob_trailer() -> None:
    trace = {
        "nodes": [{"node_output": {"blobs": {"user": "value"}}}],
        "blobs": {},
    }

    assert resolve_blobs(trace) == {"nodes": [{"node_output": {"blobs": {"user": "value"}}}]}


def test_empty_blobs_map_drops_trailer_without_resolving_ref_shaped_user_data() -> None:
    # An empty blobs map means intern_blobs minted zero refs, so the fast path
    # returns content verbatim (minus the trailer) and must NOT resolve a user
    # dict that merely happens to look like a {sentinel: ...} ref.
    trace = {"nodes": [{"value": {BLOB_SENTINEL: "deadbeef"}}], "blobs": {}}

    assert resolve_blobs(trace) == {"nodes": [{"value": {BLOB_SENTINEL: "deadbeef"}}]}


def test_dumped_trace_keeps_blobs_as_searchable_trailer(tmp_path: Path) -> None:
    large = _large_text("searchable")
    encoded = intern_blobs({"format_version": "2.4.0", "nodes": [{"a": large}, {"b": large}]})
    trace_path = tmp_path / "workflow-trace.json"
    trace_path.write_text(json.dumps(encoded, indent=2), encoding="utf-8")
    dumped = trace_path.read_text(encoding="utf-8")

    parsed = json.loads(dumped)
    assert list(parsed.keys())[-1] == "blobs"
    assert dumped.count(large) == 1


def test_intern_blobs_does_not_mutate_or_alias_input_containers() -> None:
    trace = {
        "format_version": "2.4.0",
        "nodes": [{"node_output": {"small": "inline"}}],
        "metadata": {"tags": ["a", "b"]},
    }
    original = copy.deepcopy(trace)

    encoded = intern_blobs(trace)

    assert trace == original
    assert encoded is not trace
    assert encoded["nodes"] is not trace["nodes"]
    assert encoded["nodes"][0] is not trace["nodes"][0]
    assert encoded["nodes"][0]["node_output"] is not trace["nodes"][0]["node_output"]
    assert encoded["metadata"] is not trace["metadata"]
    assert encoded["metadata"]["tags"] is not trace["metadata"]["tags"]
