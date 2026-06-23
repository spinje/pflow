"""Whole-file JSONL trace serializer — the fixture-side counterpart to the streaming producer.

Relocated from production (``core/trace_io.py``) by issue #531: pflow ends with ONE production trace
writer (the streaming ``WorkflowTraceCollector``), so the whole-file flatten — which derives event
correlation + promotes ``sub_workflow_events`` + inline-interns blobs in a single pass over a nested
trace dict — is now test-only. Tests use it to write JSONL trace fixtures from a nested trace dict
(e.g. ``TraceFixtureBuilder.trace(...)`` or a hand-built ``{...nodes...}`` dict) that the production
reader (``core.trace_io.load_trace_file`` / ``reconstruct_trace_from_lines``) reads back.

The shared FORMAT primitives stay in ``core/trace_io.py`` (the on-disk format definition): the
``pflow_trace`` marker, the reserved/meta key sets, ``intern_event_leaves``, and the reader. This module
only owns the inverse-of-the-reader writer. ``reconstruct_trace_from_lines(flatten_trace_to_lines(x)) ==
x`` is the round-trip oracle (``tests/test_core/test_trace_io.py::test_flatten_reconstruct_round_trip``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pflow.core.trace_io import (
    META_KEYS,
    RESERVED_LINE_KEYS,
    TRACE_JSONL_MARKER,
    intern_event_leaves,
)


def _inline_blobs(content_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Interleave first-occurrence ``{kind: blob}`` lines before the content lines that reference them.

    The whole-file counterpart to the streaming collector's per-event interning: takes the ordered
    content lines (``meta`` + ``event``s + ``run.complete``) and threads them through ONE accumulating
    ``declared`` set, so a blob shared across lines is written once, before its first ref. No trailer —
    inline ``blob`` lines are the single on-disk blob representation (Task 172), the same shape a
    crash-truncated stream produces."""
    declared: set[str] = set()
    out: list[dict[str, Any]] = []

    def emit_blob(digest: str, value: str) -> None:
        out.append({"kind": "blob", "md5": digest, "value": value})

    for line in content_lines:
        out.append(intern_event_leaves(line, declared, emit_blob))
    return out


def flatten_trace_to_lines(trace_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a nested trace dict into ordered JSONL line objects (the inverse of the production reader).

    Pure: never mutates ``trace_data`` or aliases its event dicts into the result (every container is
    rebuilt — ``dict(ev)`` + ``_inline_blobs``'s deep rebuild). Line kinds, each a JSON object tagged
    with ``kind``:

    - ``meta`` (first line) — the ``pflow_trace`` transport marker + run-identity keys (``META_KEYS``).
    - ``blob`` — an interned large string leaf (``{md5, value}``), emitted INLINE before the first line
      that references it (Task 172; backward-only refs, the same single representation a streamed trace
      produces — no ``blobs`` trailer).
    - ``event`` — one per node event in **DFS pre-order**; ``sub_workflow_events`` are promoted to
      their own ``event`` lines (recursively), while ``batch_items`` and everything nested under them
      stay INLINE in the host line. Carries derived ``id``/``seq``/``parent_id``/``run_id``; ``id`` IS
      ``seq`` (a fresh pre-order index — NEVER ``node_id``, which repeats across loop visits and
      sub-workflows).
    - ``run.complete`` (last) — every top-level key not in ``META_KEYS`` (generic fold, so a
      conditional key like ``json_output`` is never dropped).
    """
    run_id = trace_data.get("execution_id")
    events: list[dict[str, Any]] = []
    seq_counter = 0

    def walk(node_events: list[dict[str, Any]], parent_id: int | None) -> None:
        nonlocal seq_counter
        for ev in node_events:
            collision = RESERVED_LINE_KEYS.intersection(ev)
            if collision:
                # A fixture must not pre-stamp the correlation keys the writer derives + the reader
                # strips. Vanilla ValueError mirrors the (now-deleted) production guard's contract.
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
    for key in META_KEYS:
        if key in trace_data:
            meta[key] = trace_data[key]
    run_complete: dict[str, Any] = {
        key: value for key, value in trace_data.items() if key not in META_KEYS and key not in ("nodes", "blobs")
    }
    run_complete["kind"] = "run.complete"

    # Inline-first-occurrence blobs across meta + events + run.complete in document order (a large
    # json_output lives in run.complete) — ONE blob representation, no trailer (Task 172).
    return _inline_blobs([meta, *events, run_complete])


def write_trace_jsonl(path: Path, trace_data: dict[str, Any]) -> Path:
    """Serialize a nested trace dict to ``path`` as JSONL (the on-disk format ``load_trace_file`` reads).

    The single replacement for the old ``path.write_text(json.dumps(trace))`` single-object writes in
    the test suite (#531): ``load_trace_file`` reads only the Task-172 JSONL format, so fixtures must be
    written via the flatten serializer. ``default=str`` matches the streaming writer's ``json.dump`` so a
    non-JSON-native leaf (e.g. a ``datetime``) serializes the same way."""
    path.write_text("\n".join(json.dumps(line, default=str) for line in flatten_trace_to_lines(trace_data)) + "\n")
    return path
