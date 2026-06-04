"""Tests for trace disk interning helpers."""

import copy
import json
from pathlib import Path
from typing import Any

from pflow.core.trace_io import BLOB_SENTINEL, INTERN_MIN_BYTES, intern_blobs, load_trace_file, resolve_blobs


def _large_text(prefix: str = "large") -> str:
    return f"{prefix}-" + ("x" * INTERN_MIN_BYTES)


def _assert_blob_ref(value: Any) -> str:
    assert isinstance(value, dict)
    assert set(value) == {BLOB_SENTINEL}
    digest = value[BLOB_SENTINEL]
    assert isinstance(digest, str)
    return digest


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
