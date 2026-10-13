"""The trace directory: where traces live, what their filenames say, and how to list them (ADR-0018).

A Run is found by its filename, not by opening files: the name carries every fact a lookup filters on,
so a lookup is ONE ``os.scandir`` (``list_traces``) plus reads of only the files in its answer.

    workflow-trace-{hash8}-{name}.{execution_id}[.only][.from-{src8}][.{tag}…]-{started}.json
    {trace filename}.paused        an empty sidecar: the Run finalized Paused (written before its trailer)

``trace_filename`` is the one composer and ``parse_trace_filename`` the one parser; they share the field
patterns below, and the composer refuses a name its own parser would not read back. The start timestamp
stays LAST so a pre-185 pflow sharing the directory still orders and finds these traces. A name in the
pre-185 grammar parses as LEGACY (its timestamp only — the sweep ages it out; no lookup returns it); a
name matching neither grammar is not a trace. Mechanism only — retention policy lives in
``runtime/trace_retention.py``, resume policy in ``runtime/resume_source.py``.

The readers come in pairs. The STRICT ones distinguish "gone" (``FileNotFoundError`` propagates) from
"could not read" (``TraceUnreadableError``) from "readable, no such line" (``None``) — what a deleter must
know. The lenient twins fold every fault into ``None`` — what a display needs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Literal

from pflow.core.exceptions import PflowError
from pflow.core.trace_tree import normalize_workflow_path_key

TRACE_PREFIX = "workflow-trace-"
PAUSED_SUFFIX = ".paused"
_STARTED_FORMAT = "%Y%m%d-%H%M%S-%f"
# Bytes read from a trace's end to find its trailer; an oversized trailer is re-read whole.
_TAIL_WINDOW = 65536

# The field patterns the composer and the parser share — one grammar.
_HASH = r"[0-9a-f]{8}"
_NAME = r"[A-Za-z0-9_-]+"
_ID = r"[A-Za-z0-9_-]+"
_TAG = r"[a-z][A-Za-z0-9_-]*"
_STARTED = r"\d{8}-\d{6}-\d{6}"

_CURRENT_RE = re.compile(rf"^{TRACE_PREFIX}({_HASH})-({_NAME}?)\.({_ID}?)((?:\.{_TAG})*)-({_STARTED})\.json$")
# The pre-185 grammar. Its name group admits no dot (the old sanitizer never wrote one), so a dotted
# name the current pattern rejects is unrecognised, never legacy.
_LEGACY_RE = re.compile(rf"^{TRACE_PREFIX}({_HASH})(?:-({_NAME}))?-(\d{{8}}-\d{{6}}(?:-\d+)?)\.json$")
_ID_RE = re.compile(rf"^{_ID}$")
_FROM_TAG_RE = re.compile(r"^from-([A-Za-z0-9_-]{1,8})$")


class TraceUnreadableError(PflowError):
    """A trace file exists but could not be read or parsed — raised by the strict readers only.

    Distinct from ``FileNotFoundError`` (the file is gone) and from ``None`` (readable, but the asked-for
    line is not there yet). A deleter keeps what it cannot read."""


@dataclass(frozen=True, slots=True)
class ParsedTraceName:
    """The facts a trace filename carries. ``execution_id is None`` marks a legacy (pre-185) name."""

    workflow_hash: str
    started: str
    execution_id: str | None
    only: bool = False
    resumed_from_prefix: str | None = None
    unknown_tags: tuple[str, ...] = ()

    @property
    def legacy(self) -> bool:
        return self.execution_id is None

    @property
    def started_at(self) -> datetime:
        """The start time the name records — both timestamp widths (legacy names may lack microseconds)."""
        stamp, _, fraction = self.started[:15], self.started[15:16], self.started[16:]
        base = datetime.strptime(stamp, "%Y%m%d-%H%M%S")
        return base.replace(microsecond=int(fraction[:6].ljust(6, "0"))) if fraction else base


@dataclass(frozen=True, slots=True, kw_only=True)
class TraceEntry(ParsedTraceName):
    """One trace in a listing: its parsed name, its path, and the sidecars beside it."""

    path: Path
    paused: bool = False
    # Sidecars this version does not know (``{trace}.json.{x}``, ``x != "paused"``) — a later pflow's fact.
    other_sidecars: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TraceListing:
    """What one directory listing knows. ``traces`` is current-grammar, newest-first by (started, name)."""

    traces: list[TraceEntry]
    legacy_count: int = 0
    # Filled only with ``include_legacy=True`` — the retention sweep is the one caller.
    legacy: list[TraceEntry] = field(default_factory=list)
    # ``.paused`` sidecars whose trace name is absent from the same listing (any grammar).
    orphan_markers: list[Path] = field(default_factory=list)


def debug_dir() -> Path:
    """The trace directory, evaluated per call (tests patch ``Path.home``)."""
    return Path.home() / ".pflow" / "debug"


def workflow_hash(workflow_path: str | None) -> str:
    """The filename's 8-char workflow field: ``md5(workflow_path or "")[:8]`` (``d41d8cd9`` for none)."""
    return hashlib.md5((workflow_path or "").encode("utf-8"), usedforsecurity=False).hexdigest()[:8]


def workflow_hashes(workflow_path: str) -> frozenset[str]:
    """The hashes a workflow's traces may carry: its path as given, normalized, and backslash-separated."""
    normalized = normalize_workflow_path_key(workflow_path)
    return frozenset(workflow_hash(spelling) for spelling in (workflow_path, normalized, normalized.replace("/", "\\")))


def trace_filename(
    workflow_path: str | None,
    workflow_name: str,
    started: datetime,
    execution_id: str,
    *,
    only: bool = False,
    resumed_from: str | None = None,
) -> str:
    """Compose a trace filename — the one producer of the grammar (module docstring).

    Raises ``ValueError`` when ``execution_id`` or ``resumed_from`` is outside the id charset — an internal
    contract violation (the collector validates both at construction), never a user error."""
    if not is_filename_safe_id(execution_id):
        raise ValueError(f"execution_id must be filename-safe ([A-Za-z0-9_-]+): {execution_id!r}")
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "-", workflow_name)[:30]
    safe_name = re.sub(r"-+", "-", safe_name).strip("-") or "workflow"
    tags = ".only" if only else ""
    if resumed_from is not None:
        if not is_filename_safe_id(resumed_from):
            raise ValueError(f"resumed_from must be filename-safe ([A-Za-z0-9_-]+): {resumed_from!r}")
        tags += f".from-{resumed_from[:8]}"
    name = (
        f"{TRACE_PREFIX}{workflow_hash(workflow_path)}-{safe_name}.{execution_id}{tags}"
        f"-{started.strftime(_STARTED_FORMAT)}.json"
    )
    parsed = parse_trace_filename(name)
    if parsed is None or parsed.execution_id != execution_id or parsed.only != only:
        raise ValueError(f"composed trace filename does not parse back: {name!r}")
    return name


def is_filename_safe_id(value: str) -> bool:
    """Whether ``value`` fits the filename's id field (``[A-Za-z0-9_-]+``)."""
    return bool(_ID_RE.match(value))


def parse_trace_filename(name: str) -> ParsedTraceName | None:
    """Parse a trace filename: current grammar first, then legacy; ``None`` when it is not a trace name."""
    match = _CURRENT_RE.match(name)
    if match is not None:
        hash8, _name, execution_id, raw_tags, started = match.groups()
        only = False
        resumed_from_prefix: str | None = None
        unknown: list[str] = []
        for tag in raw_tags.split(".")[1:]:
            from_match = _FROM_TAG_RE.match(tag)
            if tag == "only":
                only = True
            elif from_match is not None and resumed_from_prefix is None:
                resumed_from_prefix = from_match.group(1)
            else:
                unknown.append(tag)
        return ParsedTraceName(
            workflow_hash=hash8,
            started=started,
            execution_id=execution_id,
            only=only,
            resumed_from_prefix=resumed_from_prefix,
            unknown_tags=tuple(unknown),
        )
    legacy = _LEGACY_RE.match(name)
    if legacy is not None:
        return ParsedTraceName(workflow_hash=legacy.group(1), started=legacy.group(3), execution_id=None)
    return None


def recency_key(name: str) -> tuple[str, str]:
    """The one recency rule (newest-first under ``reverse=True``): the start time the name records, then
    the name as a deterministic tiebreak. A name that does not parse sorts oldest."""
    parsed = parse_trace_filename(name)
    return (parsed.started if parsed is not None else "", name)


def paused_marker(trace_path: Path) -> Path:
    """The ``.paused`` sidecar beside ``trace_path``."""
    return trace_path.with_name(trace_path.name + PAUSED_SUFFIX)


def list_traces(directory: Path | None = None, *, include_legacy: bool = False) -> TraceListing:
    """ONE ``os.scandir`` of the trace directory → its current-grammar traces, newest-first.

    A missing directory is an empty listing. Any other ``OSError`` on the directory propagates: a lookup
    must never report "no runs" because the directory could not be read. Legacy names are always counted
    and returned only with ``include_legacy``; unrecognised names are ignored."""
    directory = directory if directory is not None else debug_dir()
    try:
        with os.scandir(directory) as scan:
            names = [entry.name for entry in scan]
    except FileNotFoundError:
        return TraceListing(traces=[])
    present = set(names)
    sidecars: dict[str, list[str]] = {}
    for name in names:
        base, sep, suffix = name.rpartition(".json.")
        if sep and suffix:
            sidecars.setdefault(base + ".json", []).append(suffix)
    traces: list[TraceEntry] = []
    legacy: list[TraceEntry] = []
    legacy_count = 0
    for name in names:
        if not name.endswith(".json"):
            continue
        parsed = parse_trace_filename(name)
        if parsed is None:
            continue
        beside = sidecars.get(name, [])
        entry = TraceEntry(
            workflow_hash=parsed.workflow_hash,
            started=parsed.started,
            execution_id=parsed.execution_id,
            only=parsed.only,
            resumed_from_prefix=parsed.resumed_from_prefix,
            unknown_tags=parsed.unknown_tags,
            path=directory / name,
            paused="paused" in beside,
            other_sidecars=tuple(sorted(suffix for suffix in beside if suffix != "paused")),
        )
        if parsed.legacy:
            legacy_count += 1
            if include_legacy:
                legacy.append(entry)
        else:
            traces.append(entry)
    traces.sort(key=lambda entry: (entry.started, entry.path.name), reverse=True)
    orphans = [
        directory / name
        for name in names
        if name.endswith(".json" + PAUSED_SUFFIX) and name[: -len(PAUSED_SUFFIX)] not in present
    ]
    return TraceListing(traces=traces, legacy_count=legacy_count, legacy=legacy, orphan_markers=orphans)


def find_trace(entries: Iterable[TraceEntry], execution_id: str) -> TraceEntry | None:
    """The entry whose name carries exactly ``execution_id`` (the newest on a duplicate), else ``None`` —
    zero reads. Callers apply their own ``--only`` policy to the hit."""
    return next((entry for entry in entries if entry.execution_id == execution_id), None)


def legacy_note(count: int) -> str | None:
    """The clause every lookup that finds nothing adds when the directory holds pre-185 traces."""
    if count <= 0:
        return None
    noun, verb = ("trace", "is") if count == 1 else ("traces", "are")
    return f"{count} {noun} written by an earlier pflow version {verb} not searched"


# The hint every by-id miss carries: the run may have existed and been removed by Retention.
AGED_OUT_HINT = "its trace may have aged out of `runtime.trace_retention_days`"


def read_trace_meta_strict(path: Path) -> dict[str, Any] | None:
    """The trace's ``meta`` line, or ``None`` when the file is readable but has none — including a first
    line with no terminating newline (a write cut short; such a file ages out rather than reads as
    corrupt). ``FileNotFoundError`` propagates; any other read fault or a corrupt, newline-terminated first
    line raises ``TraceUnreadableError``."""
    try:
        with open(path, "rb") as handle:
            first = handle.readline()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise TraceUnreadableError(f"could not read trace {path}: {exc}") from exc
    return _meta_from_first_line(first, path)


def read_trace_meta_and_lock_strict(path: Path) -> tuple[dict[str, Any] | None, bool | None]:
    """``read_trace_meta_strict`` and ``is_trace_locked(strict=True)`` through ONE open — what a deleter
    needs of a file it is about to remove. Same outcomes as the two: ``FileNotFoundError`` propagates, a read
    or open fault raises ``TraceUnreadableError``."""
    try:
        with open(path, "rb") as handle:
            first = handle.readline()
            locked = _probe_lock(handle)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise TraceUnreadableError(f"could not read trace {path}: {exc}") from exc
    return _meta_from_first_line(first, path), locked


def _meta_from_first_line(first: bytes, path: Path) -> dict[str, Any] | None:
    if not first.endswith(b"\n"):
        return None
    try:
        line = json.loads(first)
    except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError
        raise TraceUnreadableError(f"corrupt meta line in trace {path}") from exc
    if isinstance(line, dict) and line.get("kind") == "meta":
        return line
    return None


def _last_line(data: bytes) -> tuple[dict[str, Any] | None, bool]:
    """``(trailer, parsed)`` for the LAST non-empty line of ``data``: the ``run.complete`` dict, or
    ``None`` when the last line is something else (or there is none); ``parsed`` is False when that line
    is not valid JSON."""
    for raw in reversed(data.split(b"\n")):
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except ValueError:
            return None, False
        if isinstance(line, dict) and line.get("kind") == "run.complete":
            return line, True
        return None, True
    return None, True


def read_trace_trailer_strict(path: Path) -> dict[str, Any] | None:
    """The ``run.complete`` trailer, or ``None`` when the file is readable but not (yet) finalized.

    Reads a bounded tail; a trailer larger than the window (a paused trailer carries the whole gate
    request) is re-read from the full file when the file ends in a newline. A last line that does not
    parse is mid-flush when unterminated (``None``) and corruption when terminated
    (``TraceUnreadableError``). ``FileNotFoundError`` propagates."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _TAIL_WINDOW))
            tail = handle.read()
            trailer, parsed = _last_line(tail)
            if not parsed and tail.endswith(b"\n") and size > _TAIL_WINDOW:
                handle.seek(0)
                trailer, parsed = _last_line(handle.read())
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise TraceUnreadableError(f"could not read trace {path}: {exc}") from exc
    if not parsed and tail.endswith(b"\n"):
        raise TraceUnreadableError(f"corrupt last line in trace {path}")
    return trailer


def read_trace_meta(path: Path) -> dict[str, Any] | None:
    """Lenient ``read_trace_meta_strict``: any fault reads as ``None``."""
    try:
        return read_trace_meta_strict(path)
    except (OSError, TraceUnreadableError):
        return None


def read_trace_trailer(path: Path) -> dict[str, Any] | None:
    """Lenient ``read_trace_trailer_strict``: any fault reads as ``None``."""
    try:
        return read_trace_trailer_strict(path)
    except (OSError, TraceUnreadableError):
        return None


def is_trace_locked(path: Path, *, strict: bool = False) -> bool | None:
    """Is a live writer holding this trace? ``True`` held / ``False`` free or gone / ``None`` unknown.

    The writer holds an exclusive ``flock`` for the run's life and the kernel releases it on any exit, so
    this detects death, not hang. The probe takes a SHARED non-blocking lock on a separate fd (two
    consumers probing a free file never contend) and releases it at once. ``None`` when liveness cannot be
    determined: no ``fcntl`` (Windows), a filesystem without ``flock``, or an open fault — which raises
    ``TraceUnreadableError`` instead under ``strict``. A vanished file has no writer: ``False``."""
    if sys.platform == "win32":
        return None
    try:
        handle = open(path, "rb")  # noqa: SIM115 — closed by the with-block below
    except FileNotFoundError:
        return False
    except OSError as exc:
        if strict:
            raise TraceUnreadableError(f"could not open trace {path} to probe its lock: {exc}") from exc
        return None
    with handle:
        return _probe_lock(handle)


def _probe_lock(handle: BinaryIO) -> bool | None:
    """The lock verdict on an open handle (``is_trace_locked``'s contract); ``None`` without ``flock``."""
    if sys.platform == "win32":
        return None
    try:
        import fcntl
    except ImportError:
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        return None
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False


def workflow_file_state(path: str) -> Literal["present", "absent", "unknown"]:
    """Whether a recorded workflow file exists — three outcomes, from one ``os.stat``.

    Not ``Path.is_file()``: it raises ``PermissionError`` on Python 3.10-3.13 and returns ``False`` on
    3.14, so "cannot tell" would read as either a crash or "deleted". ``absent`` means no directory entry
    at the path: a symlink whose target is unavailable (an unmounted volume) is ``unknown``, not deleted."""
    try:
        os.stat(path)
    except ValueError:
        return "absent"
    except (FileNotFoundError, NotADirectoryError):
        return "absent" if _no_entry(path) else "unknown"
    except OSError:
        return "unknown"
    return "present"


def _no_entry(path: str) -> bool:
    """Whether nothing at all is at ``path`` — not even a dangling symlink."""
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return False
    return False
