"""One-shot node-detail read for the live-overlay detail panel (Task 173, ADR-0008).

The interactive single-node counterpart of ``pflow report``: given a workflow, an optional pinned
``run_id``, and a structural node ref, resolve THAT node's runtime record off its trace — the realized
input (post-``${...}`` resolution), the resolved output, cost, tokens, and the error — with blobs
resolved and secrets redacted.

Distinct from ``run_tailer.py``: that POLLS the growing file and ships a deliberately-stripped wire (no
payloads — they may be large/blobbed); this does a single request/response read of ONE event with the
FULL blob-resolved payload, on demand. It REUSES ``run_tailer``'s discovery (``scan_traces`` /
``discover_live_trace``) — never reaching into ``RunTailer`` internals — and ``trace_io.substitute_refs``
for blob resolution. It does NOT use ``load_trace_file`` (which STRIPS ``ancestor_path``/``port``, the
exact keys the panel joins on — the #1 tailer trap); it reads RAW lines and matches the structural ref
the same way the frontend ``sameRef`` does.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pflow.core.llm_usage import input_token_total
from pflow.core.node_type_display import node_type_tag
from pflow.core.security_utils import is_sensitive_parameter
from pflow.core.trace_io import BLOB_SENTINEL, substitute_refs
from pflow.core.trace_tree import event_cost
from pflow.ui.run_tailer import discover_live_trace, scan_traces

logger = logging.getLogger(__name__)


def run_node_detail(workflow_key: str, run_id: str | None, ref: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve one node's runtime record for the detail panel, or ``None`` (the handler → 404).

    ``run_id`` set → the pinned run (matched by ``meta.execution_id``); ``None`` → the newest LIVE trace
    (the unpinned overlay's own discovery). ``ref`` is the structural ``RFRef`` the canvas joins on
    (``node_id`` + ``ancestor_path`` + ``port``). Returns ``None`` when no trace / run / matching event is
    found, or when a blob can't be resolved (a corrupt/missing blob line) — never a half-rendered payload.
    """
    trace_path = _resolve_trace(workflow_key, run_id)
    if trace_path is None:
        return None
    event = _read_matching_event(trace_path, ref)
    if event is None:
        return None
    return _project(event)


def _resolve_trace(workflow_key: str, run_id: str | None) -> Path | None:
    """The trace file for this ``(workflow, run)`` — reusing ``run_tailer``'s discovery (the ``--only`` /
    prefer-live policy lives there, DR-3). Pinned: match ``meta.execution_id`` over ``scan_traces`` (the
    same match ``RunTailer._resolve_pinned`` does). Unpinned: ``discover_live_trace`` (the newest live, else
    newest finished — what the unpinned overlay itself follows)."""
    if run_id is not None:
        for candidate in scan_traces(workflow_key):
            if candidate["meta"].get("execution_id") == run_id:
                return candidate["path"]
        return None
    return discover_live_trace(workflow_key)


def _read_matching_event(path: Path, ref: dict[str, Any]) -> dict[str, Any] | None:
    """Forward-scan the RAW JSONL lines for the LAST ``event`` whose ref matches, with blobs resolved.

    RAW lines, never ``load_trace_file`` (it strips ``ancestor_path``/``port`` — the join keys). Accumulate
    the blob map from ``blob`` lines; track the last matching ``kind == "event"`` line — NOT ``node.start``:
    the terminal ``event`` is emitted after its start (so last-wins picks the completion), and a
    ``node.start`` carries no output to show. Last-wins also matches the overlay's per-ref semantics (a
    loop's latest iteration; a dead-end re-flush correction). A single truncated FINAL line is a normal
    mid-flush tail (skip, like ``load_trace_file``); a malformed EARLIER line is real corruption (raise —
    "corrupt" must be visible, never silent-wrong). At EOF resolve blobs once (backward-only refs → one
    forward pass is always correct); if a ``$pflow_blob`` sentinel survives (a missing/corrupt blob line)
    the payload is unresolvable → ``None``, never the raw sentinel. A read error (deleted/permission/
    transient IO on the file discovery resolved) also degrades to ``None`` (debug-logged).

    Reads the whole file (like ``load_trace_file`` / ``generate_report``) rather than streaming: this is a
    one-shot, on-demand read of ONE node — finding the LAST match needs a full scan anyway, and a trace is
    modest. Don't reach for the tailer's incremental machinery here; the simplicity is the point."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # The file resolved via discovery but couldn't be read back (permission / deleted mid-read /
        # transient IO), or it's corrupt / non-UTF-8 bytes (UnicodeDecodeError ⊄ OSError — PR #543 review).
        # Degrade to "no detail" (→ 404), but leave a breadcrumb so this isn't silently
        # indistinguishable from "this node didn't run" if a user reports a missing panel.
        logger.debug("run_node_detail: could not read trace %s (%s) — treating as no detail", path, exc)
        return None
    blob_map: dict[str, str] = {}
    matched: dict[str, Any] | None = None
    for line in _iter_trace_lines([ln for ln in text.splitlines() if ln.strip()]):
        kind = line.get("kind")
        if kind == "blob":
            md5, value = line.get("md5"), line.get("value")
            if isinstance(md5, str) and isinstance(value, str):
                blob_map[md5] = value
        elif kind == "event" and _ref_matches(line, ref):
            matched = line  # last-wins
    if matched is None:
        return None
    resolved = substitute_refs(matched, blob_map)
    if not isinstance(resolved, dict) or _contains_blob_sentinel(resolved):
        return None
    return resolved


def _iter_trace_lines(raw_lines: list[str]) -> Iterator[dict[str, Any]]:
    """Yield each non-empty JSONL line as a dict. Tolerate a single truncated FINAL line (the file may be
    mid-flush — stop), but RAISE on a malformed EARLIER line (real corruption, never silent-wrong); a
    non-dict line is skipped."""
    for index, raw in enumerate(raw_lines):
        try:
            line = json.loads(raw)
        except ValueError:
            if index == len(raw_lines) - 1:
                return  # a truncated final line — the file is mid-flush; tolerate it
            raise
        if isinstance(line, dict):
            yield line


def _ref_matches(line: dict[str, Any], ref: dict[str, Any]) -> bool:
    """Structural ref equality, identical to the frontend ``sameRef``: same ``node_id``, same ``port``, and
    element-wise-equal ancestor paths on ``(node_id, batch_index)`` — no ``refKey`` string grammar."""
    if line.get("node_id") != ref.get("node_id"):
        return False
    if line.get("port") != ref.get("port"):
        return False
    return _ancestor_paths_equal(line.get("ancestor_path") or [], ref.get("ancestor_path") or [])


def _ancestor_paths_equal(a: list[Any], b: list[Any]) -> bool:
    if len(a) != len(b):
        return False
    return all(
        isinstance(pa, dict)
        and isinstance(pb, dict)
        and pa.get("node_id") == pb.get("node_id")
        and pa.get("batch_index") == pb.get("batch_index")
        for pa, pb in zip(a, b)
    )


def _project(event: dict[str, Any]) -> dict[str, Any]:
    """Project a blob-resolved event to the ``RunNodeDetail`` allowlist (DR-4 — a PROJECTION, never the raw
    event). Drops the raw ``node_type`` (a Python class name) for ``node_type_tag``; cost via the shared
    ``event_cost`` (so the panel agrees with the chip + ``pflow report``); ``input``/``output`` are
    recursively redacted."""
    llm_call = event.get("llm_call")
    input_payload: dict[str, Any] = _public_top_level(event.get("node_params") or {})
    if event.get("llm_prompt") is not None:
        input_payload["llm_prompt"] = event["llm_prompt"]
    if event.get("llm_system") is not None:
        input_payload["llm_system"] = event["llm_system"]
    return {
        "node_type": node_type_tag(str(event.get("node_type", ""))),
        "status": event.get("status"),
        "duration_ms": event.get("duration_ms"),
        "cost_usd": event_cost(event),
        "tokens": _tokens(llm_call) if isinstance(llm_call, dict) else None,
        "error": event.get("error"),
        "input": _redact(input_payload),
        "output": _redact(_output(event)),
    }


def _output(event: dict[str, Any]) -> Any:
    """The node's resolved output — mirrors the report's Response-vs-output rule: an LLM/agent node's text
    ``llm_response`` is the headline, every other node shows its ``node_output`` (reserved ``_``-keys
    dropped). ``None`` when neither carries anything to show."""
    llm_response = event.get("llm_response")
    if llm_response is not None:
        return llm_response
    node_output = event.get("node_output")
    if isinstance(node_output, dict):
        return _public_top_level(node_output) or None
    return node_output if node_output else None


def _public_top_level(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop reserved internal keys (single-``_`` prefix) from a top-level payload — the display-site
    convention every other agent-facing surface follows (``trace_report`` / ``node_output_formatter``): a
    sub-workflow host's ``node_output`` carries ``_pflow_child_workflow_paths``, a code node's
    ``node_params`` carries ``_source_line``/``_source_lines`` — neither is something an agent authored or
    can act on. Top-level only, matching the report (a nested user key like ``_id`` is preserved)."""
    return {key: value for key, value in payload.items() if not (isinstance(key, str) and key.startswith("_"))}


def _tokens(llm_call: dict[str, Any]) -> dict[str, int]:
    """``{input, output, cache_read}`` for an LLM event. ``input``/``cache_read`` via the shared
    ``input_token_total`` (cache-inclusive); ``output`` read separately, keeping the ``completion_tokens``
    fallback for older traces."""
    total_in, cache_read = input_token_total(llm_call)
    tokens_out = llm_call.get("output_tokens", llm_call.get("completion_tokens", 0)) or 0
    return {"input": total_in, "output": tokens_out, "cache_read": cache_read}


def _redact(obj: Any) -> Any:
    """Recursively redact secrets by KEY name (``is_sensitive_parameter``), descending every nested dict and
    list — so a nested ``headers.Authorization`` or a list-of-dicts secret is caught, not just a top-level
    key. The trace stores RAW resolved secrets (review-C1 Critical), so this is the panel's only redaction.
    Unlike ``security_utils.sanitize_parameters`` it does NOT truncate long strings — the panel must show the
    full realized command/prompt. Residual (accepted, Option 1): a secret embedded inside a free-text STRING
    leaf (``llm_prompt`` / a string ``node_output`` — no key to match) — the same boundary as ``pflow
    report`` + the on-disk trace, over loopback to the user's own data."""
    if isinstance(obj, dict):
        return {
            key: "<REDACTED>" if isinstance(key, str) and is_sensitive_parameter(key) else _redact(value)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


def _contains_blob_sentinel(obj: Any) -> bool:
    """True if any unresolved ``{$pflow_blob: <digest>}`` ref survives in ``obj`` (a missing/corrupt blob
    line). Mirrors ``substitute_refs``'s own one-key shape check so a user dict that merely contains the key
    among others isn't a false positive."""
    if isinstance(obj, dict):
        if len(obj) == 1 and isinstance(obj.get(BLOB_SENTINEL), str):
            return True
        return any(_contains_blob_sentinel(value) for value in obj.values())
    if isinstance(obj, list):
        return any(_contains_blob_sentinel(item) for item in obj)
    return False
