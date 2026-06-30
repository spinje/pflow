"""Workflow-IR identifier helpers (pure utilities, no runtime dependencies).

Lives in ``core/`` because both the runtime (``execution/runner.py``,
``runtime/cache.py``'s scoping convention) and the analyzer
(``core/prompt_cache_analysis/analyze.py``'s autoload) need the same canonical
identifier for inline (file-less) workflows. Putting it here keeps both
consumers honest about the contract: the inline ID is a pure deterministic
function of the parsed IR, no side effects, no filesystem.

The function was originally private at ``execution/runner.py``; it moved
here when ``analyze.py`` autoload had to derive the same ID at trace-lookup
time and the layer policy (``core/`` cannot import from ``execution/``)
forced relocation. ``execution/runner.py`` now imports from this module
and re-exports an underscore alias for in-tree backward compatibility.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_ir_digest(ir: dict[str, Any]) -> str:
    """The order-insensitive content fingerprint of a (resolved) workflow IR.

    Canonical JSON (``sort_keys`` neutralizes dict order; ``default=str``
    keeps it total over JSON-native + stringifiable leaves) hashed with MD5.
    Deterministic and pure — the same IR always yields the same digest, and
    two structurally-equal IRs (any key order) collapse to one digest. No
    security boundary (see the collision note on
    ``synthesize_inline_workflow_id``); it is a content partition, nothing more.

    Direct consumer: the inline-run id (``synthesize_inline_workflow_id`` →
    ``ir-hash:<digest>``). The Task 173 replay fingerprint wraps it via
    ``workflow_content_hash`` (same digest, with source-line provenance stripped
    first), so it is layout-insensitive. Both hash the *resolved* IR (post
    file-reference resolution) via the same ``resolve_workflow`` path, so an
    unedited file round-trips to an identical digest on every side.
    """
    canonical = json.dumps(ir, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.md5(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


# Source-LOCATION provenance keys (editor-click metadata: where each node/output/file-ref was authored).
# They never affect how the graph renders or executes, so they are stripped from the replay version
# fingerprint — a comment/whitespace edit that only shifts line numbers must NOT read as "a different
# version". `_routes_to_end` is deliberately NOT here: it is semantic (it shapes the graph), so it stays.
_SOURCE_PROVENANCE_KEYS = frozenset({"_source_line", "_source_lines", "_source_files"})


def _strip_source_provenance(obj: Any) -> Any:
    """Return ``obj`` with every ``_source_*`` location key removed, recursively. Pure — rebuilds new
    containers, never mutates the input (the runner reuses ``resolved.ir`` downstream)."""
    if isinstance(obj, dict):
        return {k: _strip_source_provenance(v) for k, v in obj.items() if k not in _SOURCE_PROVENANCE_KEYS}
    if isinstance(obj, list):
        return [_strip_source_provenance(item) for item in obj]
    return obj


def workflow_content_hash(ir: dict[str, Any]) -> str:
    """The Task 173 replay version fingerprint: ``canonical_ir_digest`` of the resolved IR with source-LOCATION
    provenance stripped — the LOGICAL workflow, not its byte layout. So a whitespace/comment edit that only
    shifts line numbers round-trips to the same digest (the overlay renders identically → not "a different
    version"), while a node rename/add/remove/re-nest changes it, and a referenced-file CONTENT change changes
    it too (the content is inlined into params, not provenance). Producer stamp + replay compare BOTH use this,
    so an unedited file is stable on both sides."""
    return canonical_ir_digest(_strip_source_provenance(ir))


def synthesize_inline_workflow_id(ir: dict[str, Any]) -> str:
    """Produce a stable synthetic ``_pflow_workflow_file`` for inline runs.

    SQL ``WHERE workflow_path = NULL`` matches zero rows (NULL semantics),
    so writing NULL falls back to the unscoped read path — pooling cache
    history across unrelated inline workflows. A content hash gives each
    distinct inline IR its own scope without requiring a real filesystem
    path. Same identifier is used by the trace writer
    (``WorkflowTraceCollector.workflow_path``) so ``analyze-cache`` autoload
    can correlate inline-workflow traces with their analyzer invocations.

    Hashes the RESOLVED IR (the ``ResolvedWorkflow.ir`` every caller already
    passes — post file-reference resolution). The original docstring claimed
    "RAW parsed IR (pre file-ref resolution)", but no caller has passed raw IR
    since the resolver boundary was unified; the resolved IR is what both the
    cache scope AND the Task 173 replay fingerprint depend on (see
    ``canonical_ir_digest``), so the contract is the resolved stage on every side.

    MD5 collision class: the same inline IR submitted twice produces the
    same id by contract (that's the whole point — scope reuse across
    repeated submissions). Collisions across distinct IRs are not
    adversarially defended — there is no security boundary here, only a
    cache-scoping partition. If two distinct IRs ever hash-collide, the
    consequence is shared memo cache scope between them; the cache-key
    layer's own hashing prevents incorrect output reuse.
    """
    return f"ir-hash:{canonical_ir_digest(ir)}"


__all__ = ["canonical_ir_digest", "synthesize_inline_workflow_id", "workflow_content_hash"]
