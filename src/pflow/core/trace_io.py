"""Trace disk encoding helpers.

Runtime trace data stays fully resolved in memory. This module only transforms
trace JSON at the disk boundary so large duplicate string leaves are stored once
while the file remains plaintext and searchable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

INTERN_MIN_BYTES = 1024
BLOB_SENTINEL = "$pflow_blob"

# Task 133: JSONL transport. The `meta` line carries this marker so the reader detects the new
# format positively (not by inferring from a whole-file JSON parse). Versioned independently of the
# content `format_version` (which stays "2.x" — the reconstructed dict is unchanged).
TRACE_JSONL_MARKER = "jsonl/1"
# Top-level trace keys knowable at run start → the JSONL `meta` line. EVERY other top-level key
# (aggregates like final_status/llm_summary, and conditional ones like json_output) folds into the
# `run.complete` trailer generically, so a conditional key is never silently dropped on round-trip.
# `only_node` is here because it is stamped at run start AND is a snapshot-source filter key
# (`_iter_workflow_traces`), so a future head-only reader can reject `--only` traces without reading
# to the trailer. `final_status` is NOT here — it is an end-of-run aggregate.
_META_KEYS = ("format_version", "execution_id", "workflow_name", "workflow_path", "start_time", "only_node")
# Correlation/line keys the flatten writer derives onto each event line; the reader strips them to
# restore the exact nested event. A producer must never emit these at an event's top level — the
# writer asserts this so a future collision (e.g. an OTel `kind` field, or a Phase D span id) fails
# loud at the producing seam, not silently on a round-trip.
_RESERVED_LINE_KEYS = frozenset({"kind", "id", "seq", "parent_id", "run_id"})


def intern_blobs(trace: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``trace`` with large string leaves replaced by blob refs.

    The returned dict always has a trailing ``"blobs"`` map. This function is
    pure: every dict/list container is rebuilt, and the input trace is never
    mutated or aliased into the output. Rebuilding means a transient ~2x memory
    peak at dump time (live tree + interned copy + blob map) — a once-per-run,
    save-time cost. Do NOT "optimize" this into in-place mutation: ``save_to_file``
    aliases the live event dicts into the dump tree, so mutating would corrupt
    them and break the in-memory-is-always-plain invariant (guarded by
    ``test_intern_blobs_does_not_mutate_or_alias_input_containers``).
    """
    blobs: dict[str, str] = {}

    def copy_without_interning(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: copy_without_interning(child) for key, child in value.items()}
        if isinstance(value, list):
            return [copy_without_interning(child) for child in value]
        return value

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: copy_without_interning(child) if isinstance(key, str) and key.startswith("__") else walk(child)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [walk(child) for child in value]
        # String-only is load-bearing: resolve substitutes one immutable object
        # into every ref. Do not extend this to containers without revisiting that.
        if isinstance(value, str):
            encoded = value.encode("utf-8")
            if len(encoded) >= INTERN_MIN_BYTES:
                digest = hashlib.md5(encoded, usedforsecurity=False).hexdigest()
                blobs.setdefault(digest, value)
                return {BLOB_SENTINEL: digest}
        return value

    interned = walk(trace)
    if not isinstance(interned, dict):
        raise TypeError("trace must be a dict")

    interned.pop("blobs", None)
    interned["blobs"] = blobs
    return interned


def substitute_refs(obj: Any, blob_map: dict[str, str]) -> Any:
    """Replace ``{BLOB_SENTINEL: digest}`` refs in ``obj`` with their blob text.

    ``blob_map`` maps digest -> original string. Shared by ``resolve_blobs`` (map
    from the trace's ``blobs`` trailer) and the future JSONL reader (map accumulated
    from inline first-occurrence declarations). Only the ``{sentinel: real-digest}``
    shape is substituted; every other container is rebuilt structurally. ``__``-keyed
    subtrees need no special-casing: ``intern_blobs`` never mints a ref under them, so
    the sentinel shape never appears there.
    """
    if (
        isinstance(obj, dict)
        and len(obj) == 1
        and isinstance(obj.get(BLOB_SENTINEL), str)
        and isinstance(blob_map.get(obj[BLOB_SENTINEL]), str)
    ):
        return blob_map[obj[BLOB_SENTINEL]]
    if isinstance(obj, dict):
        return {key: substitute_refs(child, blob_map) for key, child in obj.items()}
    if isinstance(obj, list):
        return [substitute_refs(child, blob_map) for child in obj]
    return obj


def resolve_blobs(trace: dict[str, Any]) -> dict[str, Any]:
    """Resolve blob refs in an interned trace.

    Old traces without ``"blobs"`` are returned unchanged. Malformed blob maps
    also degrade to a no-op rather than making trace loading brittle.
    """
    blobs = trace.get("blobs")
    if not isinstance(blobs, dict):
        return trace
    # intern_blobs always emits a "blobs" map, even when nothing was interned.
    # An empty map means zero refs exist anywhere, so skip the full recursive
    # walk and just drop the trailer (a frequent case: traces with no >=1 KB leaf).
    if not blobs:
        return {key: value for key, value in trace.items() if key != "blobs"}
    resolved = {key: substitute_refs(child, blobs) for key, child in trace.items() if key != "blobs"}
    if not isinstance(resolved, dict):
        raise TypeError("trace must be a dict")
    return resolved


def flatten_trace_to_lines(trace_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a nested trace dict into ordered JSONL line objects (Task 133 Phase B).

    Pure: never mutates ``trace_data`` or aliases its live event dicts into the result (every
    container is rebuilt — ``dict(ev)`` + ``intern_blobs``'s deep rebuild). Line kinds, each a JSON
    object tagged with ``kind``:

    - ``meta`` (first line) — the ``pflow_trace`` transport marker + run-identity keys (``_META_KEYS``).
    - ``event`` — one per node event in **DFS pre-order**; ``sub_workflow_events`` are promoted to
      their own ``event`` lines (recursively), while ``batch_items`` and everything nested under them
      stay INLINE in the host line. Carries derived ``id``/``seq``/``parent_id``/``run_id``; ``id`` IS
      ``seq`` (a fresh pre-order index — NEVER ``node_id``, which repeats across loop visits and
      sub-workflows).
    - ``run.complete`` (trailer) — every top-level key not in ``_META_KEYS`` (generic fold, so a
      conditional key like ``json_output`` is never dropped).
    - ``blobs`` (trailer) — the interned blob map (possibly empty).

    Correlation is derived from the existing nesting at save time, single-threaded; spike #2's
    no-lock concern is a Phase D (emit-time) matter and does not apply here.
    """
    run_id = trace_data.get("execution_id")
    events: list[dict[str, Any]] = []
    seq_counter = 0

    def walk(node_events: list[dict[str, Any]], parent_id: int | None) -> None:
        nonlocal seq_counter
        for ev in node_events:
            collision = _RESERVED_LINE_KEYS.intersection(ev)
            if collision:
                # Intentional vanilla ValueError, NOT a PflowError: an internal programmer-error guard
                # for a future producer bug (an event emitting a reserved correlation key), caught
                # fail-loud at run.py:148 → trace_file=None. It is unreachable from user/runtime input,
                # so it deliberately stays out of the agent-facing diagnostic pipeline a PflowError
                # would route it into.
                raise ValueError(
                    f"trace event {ev.get('node_id')!r} already carries reserved correlation "
                    f"key(s) {sorted(collision)}; the flatten writer derives these and the reader "
                    "strips them, so a producer must not emit them at the event top level."
                )
            seq = seq_counter
            seq_counter += 1
            line = dict(ev)  # shallow copy — never mutate the live event dict
            children = line.pop("sub_workflow_events", None)
            line.update(kind="event", id=seq, seq=seq, parent_id=parent_id, run_id=run_id)
            events.append(line)
            if isinstance(children, list) and children:
                walk(children, seq)

    nodes = trace_data.get("nodes")
    if isinstance(nodes, list):
        walk(nodes, None)

    meta: dict[str, Any] = {"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER}
    for key in _META_KEYS:
        if key in trace_data:
            meta[key] = trace_data[key]
    run_complete: dict[str, Any] = {
        key: value for key, value in trace_data.items() if key not in _META_KEYS and key not in ("nodes", "blobs")
    }
    run_complete["kind"] = "run.complete"

    # Intern across meta + events + trailer in one pass (a large json_output lives in the trailer),
    # then split back into lines. intern_blobs is shape-agnostic and emits a "blobs" trailer.
    interned = intern_blobs({"meta": meta, "events": events, "run_complete": run_complete})
    blob_map = interned.pop("blobs")
    return [
        interned["meta"],
        *interned["events"],
        interned["run_complete"],
        {"kind": "blobs", "blobs": blob_map},
    ]


def emit_flat_events_to_lines(trace_data: dict[str, Any]) -> list[dict[str, Any]]:
    """JSONL lines for a trace whose ``nodes`` are ALREADY flat + correlation-stamped.

    The Task 172 emit-time counterpart to :func:`flatten_trace_to_lines`. Where ``flatten`` walks a
    NESTED tree at save time — deriving ``id``/``seq``/``parent_id``/``run_id`` and promoting
    ``sub_workflow_events`` to child lines — this takes events the run-scoped collector already stamped
    at emit and writes them VERBATIM as ``event`` lines (only adding ``kind``). Sequential sub-workflow
    children are already flat with their own ``parent_id``; ``batch_items`` stay inline (v1 does not
    promote them). Same ``meta`` + ``run.complete`` + ``blobs`` trailer shape, so ``load_trace_file``
    reconstructs identically. Pure: copies each event, never mutates ``trace_data`` or aliases its dicts.
    """
    meta: dict[str, Any] = {"kind": "meta", "pflow_trace": TRACE_JSONL_MARKER}
    for key in _META_KEYS:
        if key in trace_data:
            meta[key] = trace_data[key]
    events = [{**dict(ev), "kind": "event"} for ev in trace_data.get("nodes", []) if isinstance(ev, dict)]
    run_complete: dict[str, Any] = {
        key: value for key, value in trace_data.items() if key not in _META_KEYS and key not in ("nodes", "blobs")
    }
    run_complete["kind"] = "run.complete"

    interned = intern_blobs({"meta": meta, "events": events, "run_complete": run_complete})
    blob_map = interned.pop("blobs")
    return [
        interned["meta"],
        *interned["events"],
        interned["run_complete"],
        {"kind": "blobs", "blobs": blob_map},
    ]


def _partition_trace_lines(
    lines: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], list[dict[str, Any]]]:
    """Bucket JSONL lines by ``kind`` → ``(meta, run_complete, blob_map, event_lines)``.

    An unknown ``kind`` or a missing ``meta`` line is corruption → ``json.JSONDecodeError`` (so the
    three trace-content readers, which catch ``(JSONDecodeError, OSError)``, degrade/skip).
    """
    meta: dict[str, Any] | None = None
    run_complete: dict[str, Any] = {}
    blob_map: dict[str, str] = {}
    event_lines: list[dict[str, Any]] = []
    for line in lines:
        kind = line.get("kind") if isinstance(line, dict) else None
        if kind == "meta":
            meta = line
        elif kind == "event":
            event_lines.append(line)
        elif kind == "run.complete":
            run_complete = line
        elif kind == "blobs":
            blobs = line.get("blobs")
            blob_map = blobs if isinstance(blobs, dict) else {}
        else:
            raise json.JSONDecodeError(f"unknown trace line kind {kind!r}", "", 0)
    if meta is None:
        raise json.JSONDecodeError("trace JSONL is missing its meta line", "", 0)
    return meta, run_complete, blob_map, event_lines


def _rebuild_event_tree(event_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild the nested ``nodes`` tree from flat event lines via ``(id, parent_id)`` + ``seq`` order.

    Strips the five derived correlation keys; re-nests children under their host's
    ``sub_workflow_events`` (omitted when empty). An orphan ``parent_id`` or a line missing its
    correlation fields is corruption → ``json.JSONDecodeError``.
    """
    nodes: list[dict[str, Any]] = []
    by_id: dict[Any, dict[str, Any]] = {}
    try:
        for ev in sorted(event_lines, key=lambda e: e["seq"]):
            clean = {key: value for key, value in ev.items() if key not in _RESERVED_LINE_KEYS}
            by_id[ev["id"]] = clean
            parent_id = ev["parent_id"]
            if parent_id is None:
                nodes.append(clean)
                continue
            parent = by_id.get(parent_id)
            if parent is None:
                raise json.JSONDecodeError(f"orphan event: parent_id {parent_id!r} not found", "", 0)
            parent.setdefault("sub_workflow_events", []).append(clean)
    except (KeyError, TypeError) as exc:
        raise json.JSONDecodeError(f"corrupt trace event line: {exc}", "", 0) from exc
    return nodes


def reconstruct_trace_from_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Inverse of ``flatten_trace_to_lines``: rebuild the exact nested trace dict from JSONL lines.

    Corruption raises ``json.JSONDecodeError`` so the three trace-content readers degrade/skip rather
    than surface a half-built dict (Task 133 B/C-checkpoint: "corrupt" must be a distinct, visible
    state, never silent-wrong-output). A cleanly-parsed but trailer-less line set (the ``run.complete``
    line is absent) is reconstructed with ``final_status="incomplete"`` — NOT defaulted to success — so
    the snapshot loader and analyze-cache autoload reject it instead of treating it as a reusable run.

    Scope (A-C): this operates on already-parsed lines. At the byte layer ``load_trace_file`` parses
    every line eagerly, so a crash that truncates the *final* line raises ``JSONDecodeError`` and the
    whole trace is skipped rather than reconstructed-as-incomplete — and today's all-at-once
    ``save_to_file`` writes the trailer in the same end-of-run flush, so trailer-less files are rare.
    Robust crash-tail tolerance (drop only a truncated final line) lands with Phase D streaming +
    inline-first-occurrence blobs (Task 172), where the trailing line is an event/``run.complete`` and
    crash-tails become the common case.
    """
    meta, run_complete, blob_map, event_lines = _partition_trace_lines(lines)
    trace: dict[str, Any] = {key: value for key, value in meta.items() if key not in ("kind", "pflow_trace")}
    trace.update({key: value for key, value in run_complete.items() if key != "kind"})
    if not run_complete:  # crash-tail: no trailer was written
        trace.setdefault("final_status", "incomplete")
    trace["nodes"] = _rebuild_event_tree(event_lines)
    return substitute_refs(trace, blob_map) if blob_map else trace


def load_trace_file(path: Path) -> Any:
    """Read, parse, and resolve a trace file from disk.

    Detects the new JSONL transport positively: if the first line is a JSON object carrying the
    ``pflow_trace`` marker, reconstruct from JSONL; otherwise fall back to the legacy single-object
    path (``resolve_blobs``). Old ``~/.pflow/debug`` traces keep working (dual-read).
    """
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        first_line = stripped.split("\n", 1)[0]
        try:
            head = json.loads(first_line)
        except json.JSONDecodeError:
            head = None
        if isinstance(head, dict) and head.get("pflow_trace"):
            return reconstruct_trace_from_lines([json.loads(ln) for ln in stripped.splitlines() if ln.strip()])
    data = json.loads(text)
    if isinstance(data, dict):
        return resolve_blobs(data)
    return data
