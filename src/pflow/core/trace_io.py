"""Trace disk encoding helpers.

Runtime trace data stays fully resolved in memory. This module only transforms
trace JSON at the disk boundary so large duplicate string leaves are stored once
while the file remains plaintext and searchable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

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
# Correlation/line keys the writer derives onto each event line; the reader strips them to restore the
# exact nested event. A producer must never emit these at an event's top level — the writer asserts this
# so a future collision (e.g. an OTel `kind` field, or a Phase D span id) fails loud at the producing
# seam, not silently on a round-trip. Task 172: `ancestor_path` (the overlay graph-join field) and
# `port` are emit-time-stamped by the run-scoped collector and stripped on read, so disk readers see the
# same nested dict as A-C (the overlay reads them off the LIVE stream, never the reconstructed dict).
_RESERVED_LINE_KEYS = frozenset({"kind", "id", "seq", "parent_id", "run_id", "ancestor_path", "port"})


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
    from a legacy single-object trace's ``blobs`` trailer) and the JSONL reader
    (``reconstruct_trace_from_lines``, map accumulated from inline first-occurrence
    ``blob`` lines). Only the ``{sentinel: real-digest}``
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


def intern_event_leaves(  # noqa: C901 — a recursive container walk (mirrors intern_blobs); one branch over
    obj: dict[str, Any],
    declared: set[str],
    emit_blob: Callable[[str, str], None],
) -> dict[str, Any]:
    """First-occurrence interning for streaming/incremental writers (Task 172 D3).

    Returns a COPY of ``obj`` with large string leaves (>= ``INTERN_MIN_BYTES``) replaced by
    ``{BLOB_SENTINEL: digest}`` refs. For each digest not already in ``declared``, calls
    ``emit_blob(digest, value)`` and records it in ``declared`` — so a blob is written exactly once,
    and (because the caller emits the blob line BEFORE the line that first references it) every ref is
    **backward-only**. That backward-only property is what makes a crash-truncated tail self-consistent
    for a forward tailer (Task 173). Skips ``__``-prefixed subtrees, mirroring :func:`intern_blobs`
    (``resolve``/``substitute_refs`` never expect a ref there). The streaming counterpart of
    ``intern_blobs``: where ``intern_blobs`` interns a whole tree into one trailer map, this interns one
    object against an accumulating ``declared`` set so per-event flushes and the whole-file writers share
    ONE representation. Pure w.r.t. ``obj`` (every container is rebuilt; ``obj`` is never mutated)."""

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
        if isinstance(value, str):
            encoded = value.encode("utf-8")
            if len(encoded) >= INTERN_MIN_BYTES:
                digest = hashlib.md5(encoded, usedforsecurity=False).hexdigest()
                if digest not in declared:
                    declared.add(digest)
                    emit_blob(digest, value)
                return {BLOB_SENTINEL: digest}
        return value

    interned = walk(obj)
    if not isinstance(interned, dict):  # obj is a dict, so walk returns a dict — guard for the type checker
        raise TypeError("event line must be a dict")
    return interned


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
    container is rebuilt — ``dict(ev)`` + ``_inline_blobs``'s deep rebuild). Line kinds, each a JSON
    object tagged with ``kind``:

    - ``meta`` (first line) — the ``pflow_trace`` transport marker + run-identity keys (``_META_KEYS``).
    - ``blob`` — an interned large string leaf (``{md5, value}``), emitted INLINE before the first line
      that references it (Task 172; backward-only refs, the same single representation a streamed trace
      produces — no ``blobs`` trailer).
    - ``event`` — one per node event in **DFS pre-order**; ``sub_workflow_events`` are promoted to
      their own ``event`` lines (recursively), while ``batch_items`` and everything nested under them
      stay INLINE in the host line. Carries derived ``id``/``seq``/``parent_id``/``run_id``; ``id`` IS
      ``seq`` (a fresh pre-order index — NEVER ``node_id``, which repeats across loop visits and
      sub-workflows).
    - ``run.complete`` (last) — every top-level key not in ``_META_KEYS`` (generic fold, so a
      conditional key like ``json_output`` is never dropped).

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

    # Inline-first-occurrence blobs across meta + events + run.complete in document order (a large
    # json_output lives in run.complete) — ONE blob representation, no trailer (Task 172).
    return _inline_blobs([meta, *events, run_complete])


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
        if run_complete:
            # ``run.complete`` is the FINAL content line — the writer closes the stream right after it.
            # Anything following it (a second run.complete, a stray event/blob) is corruption, NOT a
            # tolerable crash-tail; raise so the 3 readers skip the whole trace rather than silently
            # trust a trace with unexplained trailing content.
            raise json.JSONDecodeError("trace content after run.complete line", "", 0)
        if kind == "meta":
            meta = line
        elif kind == "event":
            event_lines.append(line)
        elif kind == "run.complete":
            run_complete = line
        elif kind == "blob":
            # Task 172 inline-first-occurrence blob (singular). The map is accumulated across ALL blob
            # lines before substitution, so file order is immaterial to the reader (it matters only to a
            # forward tailer / crash-truncation, which the writer guarantees by emitting backward-only).
            md5, value = line.get("md5"), line.get("value")
            if not (isinstance(md5, str) and isinstance(value, str)):
                # A valid-JSON blob line missing its md5/value is corruption — raise rather than skip,
                # or a later event's $pflow_blob ref would silently survive unresolved (the same
                # "corrupt = visible JSONDecodeError, never silent-wrong" rule as the unknown-kind arm).
                raise json.JSONDecodeError("blob line missing string md5/value", "", 0)
            blob_map[md5] = value
        else:
            raise json.JSONDecodeError(f"unknown trace line kind {kind!r}", "", 0)
    if meta is None:
        raise json.JSONDecodeError("trace JSONL is missing its meta line", "", 0)
    return meta, run_complete, blob_map, event_lines


def _rebuild_event_tree(event_lines: list[dict[str, Any]], *, is_incomplete: bool = False) -> list[dict[str, Any]]:
    """Rebuild the nested ``nodes`` tree from flat event lines — TWO passes (Task 172).

    One mechanism serving three Phase-D needs (dead-end re-flush, crash-tail recovery, host-after-ascend
    ordering): flush order is immaterial because we sort by ``seq`` and dedup by ``id``.

    - **Pass 1 — dedup by id, last-wins.** A re-emitted correction (``mark_last_event_failed`` re-flushes
      the same ``id`` with ``status="failed"``) replaces the original, so it appears exactly once.
    - **Pass 2 — link in ``seq`` order.** ``seq`` is reserved at host descent, so ``parent.seq <
      child.seq`` always holds → a parent is linked before its children. Strips the reserved correlation
      keys; re-nests children under their host's ``sub_workflow_events`` (omitted when empty).

    Orphan policy depends on completeness: in an **incomplete** trace (no ``run.complete`` — a crash) a
    dangling ``parent_id`` drops that child WITHOUT inserting it into ``by_id``, so its descendants dangle
    and drop too (TRANSITIVE) — recovering everything well-formed before a crash-mid-sub-workflow. In a
    **complete** trace the same dangling ``parent_id`` is corruption → ``json.JSONDecodeError`` (today's
    behavior, so the 3 readers skip rather than silently drop real data).
    """
    nodes: list[dict[str, Any]] = []
    by_id: dict[Any, dict[str, Any]] = {}
    try:
        deduped: dict[Any, dict[str, Any]] = {}
        for ev in event_lines:
            deduped[ev["id"]] = ev  # last-wins: a re-flushed correction replaces the original
        for ev in sorted(deduped.values(), key=lambda e: e["seq"]):
            clean = {key: value for key, value in ev.items() if key not in _RESERVED_LINE_KEYS}
            parent_id = ev["parent_id"]
            if parent_id is None:
                by_id[ev["id"]] = clean
                nodes.append(clean)
                continue
            parent = by_id.get(parent_id)
            if parent is not None:
                by_id[ev["id"]] = clean
                parent.setdefault("sub_workflow_events", []).append(clean)
            elif is_incomplete:
                continue  # transitive drop: NOT inserted into by_id, so descendants also dangle and drop
            else:
                raise json.JSONDecodeError(f"orphan event: parent_id {parent_id!r} not found", "", 0)
    except (KeyError, TypeError) as exc:
        raise json.JSONDecodeError(f"corrupt trace event line: {exc}", "", 0) from exc
    return nodes


def reconstruct_trace_from_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Inverse of ``flatten_trace_to_lines``: rebuild the exact nested trace dict from JSONL lines.

    Corruption raises ``json.JSONDecodeError`` so the three trace-content readers degrade/skip rather
    than surface a half-built dict (Task 133 B/C-checkpoint: "corrupt" must be a distinct, visible
    state, never silent-wrong-output). A cleanly-parsed but ``run.complete``-less line set (a crash, or a
    truncated final line dropped by ``load_trace_file``) is reconstructed with
    ``final_status="incomplete"`` — NOT defaulted to success — and its dangling sub-workflow children are
    dropped transitively (``_rebuild_event_tree(is_incomplete=True)``), so the snapshot loader and
    analyze-cache autoload reject it as non-reusable while still recovering everything well-formed.
    """
    meta, run_complete, blob_map, event_lines = _partition_trace_lines(lines)
    trace: dict[str, Any] = {key: value for key, value in meta.items() if key not in ("kind", "pflow_trace")}
    trace.update({key: value for key, value in run_complete.items() if key != "kind"})
    is_incomplete = not run_complete
    if is_incomplete:  # crash-tail: no run.complete line was written
        trace.setdefault("final_status", "incomplete")
    trace["nodes"] = _rebuild_event_tree(event_lines, is_incomplete=is_incomplete)
    return substitute_refs(trace, blob_map) if blob_map else trace


def load_trace_file(path: Path) -> Any:
    """Read, parse, and resolve a trace file from disk.

    Detects the new JSONL transport positively: if the first line is a JSON object carrying the
    ``pflow_trace`` marker, reconstruct from JSONL; otherwise fall back to the legacy single-object
    path (``resolve_blobs``). Old ``~/.pflow/debug`` traces keep working (dual-read).

    Crash-tail tolerance (Task 172 D3): a hard crash during a streamed run can leave a half-written
    FINAL line (no closing brace). Drop ONLY that truncated last line and reconstruct-as-incomplete
    (``final_status="incomplete"``) — inline-first-occurrence blobs make the trailing line an
    event/``run.complete``, and backward-only refs mean a dropped tail never strands a blob. A malformed
    line anywhere EARLIER is real corruption and still raises ``json.JSONDecodeError`` (the 3 readers
    skip the whole trace) — never a silently-dropped middle event.
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
            raw_lines = [ln for ln in stripped.splitlines() if ln.strip()]
            parsed: list[dict[str, Any]] = []
            seen_complete = False
            for index, raw in enumerate(raw_lines):
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    # Tolerate a single truncated FINAL line ONLY for a genuine crash (no run.complete
                    # yet) → reconstruct incomplete. A malformed EARLIER line — or a malformed line AFTER
                    # run.complete (the writer never writes past it) — is corruption and still raises.
                    if index == len(raw_lines) - 1 and not seen_complete:
                        break
                    raise
                parsed.append(line)
                if isinstance(line, dict) and line.get("kind") == "run.complete":
                    seen_complete = True
            return reconstruct_trace_from_lines(parsed)
    data = json.loads(text)
    if isinstance(data, dict):
        return resolve_blobs(data)
    return data
