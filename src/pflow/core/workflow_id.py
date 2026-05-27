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


def synthesize_inline_workflow_id(ir: dict[str, Any]) -> str:
    """Produce a stable synthetic ``_pflow_workflow_file`` for inline runs.

    SQL ``WHERE workflow_path = NULL`` matches zero rows (NULL semantics),
    so writing NULL falls back to the unscoped read path — pooling cache
    history across unrelated inline workflows. A content hash gives each
    distinct inline IR its own scope without requiring a real filesystem
    path. Same identifier is used by the trace writer
    (``WorkflowTraceCollector.workflow_path``) so ``analyze-cache`` autoload
    can correlate inline-workflow traces with their analyzer invocations.

    Hashes the RAW parsed IR (pre file-reference resolution, pre defaults
    fill) so the identifier represents what the caller submitted, not what
    the runner derived. Cache-key invalidation already handles file-content
    changes via ``resolved_params`` hashing; the ``workflow_path`` scope
    just needs to partition across distinct inline submissions.

    MD5 collision class: the same inline IR submitted twice produces the
    same id by contract (that's the whole point — scope reuse across
    repeated submissions). Collisions across distinct IRs are not
    adversarially defended — there is no security boundary here, only a
    cache-scoping partition. If two distinct IRs ever hash-collide, the
    consequence is shared memo cache scope between them; the cache-key
    layer's own hashing prevents incorrect output reuse.
    """
    canonical = json.dumps(ir, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.md5(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"ir-hash:{digest}"


__all__ = ["synthesize_inline_workflow_id"]
