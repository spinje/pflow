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
# to the trailer. `final_status` is NOT here — it is an end-of-run aggregate. `content_hash` is the
# Task 173 replay version fingerprint (`workflow_content_hash` of the resolved IR — `canonical_ir_digest`
# with source provenance stripped), knowable at run start. `inputs` (Task 175) is the run's resolved
# top-level input dict, stamped on the collector before run start. Production reconstruct round-trips
# meta keys generically, but the test-fixture builder (`tests/shared/trace_jsonl.py`) iterates META_KEYS
# to route a trace-dict's keys onto the meta line vs. the `run.complete` trailer — so `inputs` MUST be
# here, or fixtures built via `write_trace_jsonl({..., "inputs": {...}})` misplace it in the trailer.
META_KEYS = (
    "format_version",
    "execution_id",
    "workflow_name",
    "workflow_path",
    "start_time",
    "only_node",
    "content_hash",
    "inputs",
)
# Correlation/line keys the writer derives onto each event line; the reader strips them to restore the
# exact nested event. A producer must never emit these at an event's top level — the writer asserts this
# so a future collision (e.g. an OTel `kind` field, or a Phase D span id) fails loud at the producing
# seam, not silently on a round-trip. Task 172: `ancestor_path` (the overlay graph-join field) and
# `port` are emit-time-stamped by the run-scoped collector and stripped on read, so disk readers see the
# same nested dict as A-C (the overlay reads them off the LIVE stream, never the reconstructed dict).
RESERVED_LINE_KEYS = frozenset({"kind", "id", "seq", "parent_id", "run_id", "ancestor_path", "port"})


def substitute_refs(obj: Any, blob_map: dict[str, str]) -> Any:
    """Replace ``{BLOB_SENTINEL: digest}`` refs in ``obj`` with their blob text.

    ``blob_map`` maps digest -> original string. Used by the JSONL reader
    (``reconstruct_trace_from_lines``, map accumulated from inline first-occurrence
    ``blob`` lines). Only the ``{sentinel: real-digest}``
    shape is substituted; every other container is rebuilt structurally. ``__``-keyed
    subtrees need no special-casing: the writer (``intern_event_leaves``) never mints a
    ref under them, so the sentinel shape never appears there.
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


def intern_event_leaves(  # noqa: C901 — a recursive container walk; one branch over container/leaf kinds
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
    for a forward tailer (Task 173). Skips ``__``-prefixed subtrees (``substitute_refs`` never expects a
    ref there). It interns ONE object against an accumulating ``declared`` set so the streaming
    per-event flush (``WorkflowTraceCollector._flush_line``) and the test whole-file writer
    (``tests/shared/trace_jsonl.flatten_trace_to_lines``) share ONE on-disk representation. Pure w.r.t.
    ``obj`` (every container is rebuilt; ``obj`` is never mutated)."""

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
        elif kind == "node.start":
            # Task 173: a LIVE-ONLY in-flight marker the overlay tailer consumes (a node has BEGUN but
            # not completed). It carries no completion data and is deliberately DROPPED from the
            # reconstructed trace — the matching `event` line (which reuses its seq) is the source of
            # truth. Known-but-ignored here, NOT unknown-kind corruption: skip without bucketing.
            continue
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
            clean = {key: value for key, value in ev.items() if key not in RESERVED_LINE_KEYS}
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


def load_trace_file(path: Path) -> dict[str, Any]:
    """Read, parse, and reconstruct a Task-172 JSONL trace file from disk (the ONLY supported format).

    Detects the JSONL transport positively: the first line must be a JSON object carrying the
    ``pflow_trace`` marker. Anything else — including a well-formed pre-Task-172 single-object trace —
    raises ``json.JSONDecodeError`` (the legacy single-object/`blobs`-trailer reader was removed in #531
    under the no-backward-compat-with-old-traces decision); a corrupt / non-UTF-8 file likewise raises
    ``json.JSONDecodeError`` (not the raw ``UnicodeDecodeError``), so the same catch covers it. The 3 trace-content readers
    (``_iter_workflow_traces``, ``prompt_cache_analysis.trace_loading._load_trace_explicit``,
    ``trace_report.generate_report``) all catch ``(JSONDecodeError, OSError)``, so an old/unreadable trace
    skips gracefully rather than crashing.

    Crash-tail tolerance (Task 172 D3): a hard crash during a streamed run can leave a half-written
    FINAL line (no closing brace). Drop ONLY that truncated last line and reconstruct-as-incomplete
    (``final_status="incomplete"``) — inline-first-occurrence blobs make the trailing line an
    event/``run.complete``, and backward-only refs mean a dropped tail never strands a blob. A malformed
    line anywhere EARLIER is real corruption and still raises ``json.JSONDecodeError`` — never a
    silently-dropped middle event.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # A corrupt / non-UTF-8 file that matched the trace glob is not a valid pflow trace. Raise the same
        # json.JSONDecodeError every caller already catches (PR #543 review), so the documented
        # "(JSONDecodeError, OSError) suffices" contract actually holds — without this, the raw
        # UnicodeDecodeError (⊄ OSError) escapes and crashes report / analyze-cache / generate_report.
        raise json.JSONDecodeError(f"Trace file is not valid UTF-8: {exc}", str(path), 0) from exc
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
    raise json.JSONDecodeError(
        "Not a pflow JSONL trace (missing pflow_trace marker); "
        "legacy single-object trace format is no longer supported.",
        text,
        0,
    )
