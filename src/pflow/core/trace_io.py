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


def resolve_blobs(trace: dict[str, Any]) -> dict[str, Any]:
    """Resolve blob refs in an interned trace.

    Old traces without ``"blobs"`` are returned unchanged. Malformed blob maps
    also degrade to a no-op rather than making trace loading brittle.

    ``intern_blobs`` never mints a ref under a ``__``-prefixed key, so this walk
    deliberately does not special-case those subtrees — substitution only fires
    on the ``{sentinel: real-digest}`` shape, which they never contain.
    """
    blobs = trace.get("blobs")
    if not isinstance(blobs, dict):
        return trace
    # intern_blobs always emits a "blobs" map, even when nothing was interned.
    # An empty map means zero refs exist anywhere, so skip the full recursive
    # walk and just drop the trailer (a frequent case: traces with no >=1 KB leaf).
    if not blobs:
        return {key: value for key, value in trace.items() if key != "blobs"}

    def walk(value: Any) -> Any:
        if (
            isinstance(value, dict)
            and len(value) == 1
            and isinstance(value.get(BLOB_SENTINEL), str)
            and isinstance(blobs.get(value[BLOB_SENTINEL]), str)
        ):
            return blobs[value[BLOB_SENTINEL]]
        if isinstance(value, dict):
            return {key: walk(child) for key, child in value.items()}
        if isinstance(value, list):
            return [walk(child) for child in value]
        return value

    # Future jsonl reader: build the blob map from inline declarations instead
    # of trace["blobs"], then reuse this substitution walk.
    resolved = {key: walk(child) for key, child in trace.items() if key != "blobs"}
    if not isinstance(resolved, dict):
        raise TypeError("trace must be a dict")
    return resolved


def load_trace_file(path: Path) -> Any:
    """Read, parse, and resolve a trace file from disk."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return resolve_blobs(data)
    return data
