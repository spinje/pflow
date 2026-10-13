"""Retention: remove traces older than the age window, never a Protected trace (ADR-0018).

Runs when a trace finishes writing (``WorkflowTraceCollector.finalize`` → ``sweep_after_write``), never on a
read. ``retention_days`` is the one reader of the setting; ``prune_traces`` is the policy.

Protected — kept whatever their age (the spec's rule numbers):
  1. a Paused Run whose token is still answerable (``resume_source.answerable_pause`` and no consuming
     Attempt, a live zero-work Attempt counting as a reservation, not consumption);
  2. the newest Success/Degraded full run of each Workflow (its Snapshot);
  3. the newest run of each Workflow, whatever its status (plus the source of that run when it is an Attempt);
     rules 1-3 only while the Workflow's file is present (an inline ``ir-hash:`` identity never qualifies);
  4. an Attempt, until the Run it resumed is gone from the directory;
  5. a trace whose writer still holds its lock.
A trace carrying a tag or sidecar this version does not know is kept too: a later pflow's "keep this".

Cost: the sweep classifies from names wherever it can and reads aged files — per Workflow group with an aged
trace, the head of its newest trace (its identity: the one read that may be of a young file), the tail+head
of the Snapshot pick, and one open (head + lock probe) per trace it is about to remove; a group's other young
traces are never read. Pre-185 (legacy) names are removed on age alone,
with no read. Every read is three-outcome and fails closed: gone is fine; a file that cannot be read is kept
(with its whole group when it could be what protects the others); a workflow file whose existence cannot be
determined keeps its group.
"""

from __future__ import annotations

import logging
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pflow.core.exceptions import ResumeSourceUnreadableError
from pflow.core.path_state import PathState, path_state
from pflow.core.settings import SettingsManager, unknown_settings_keys
from pflow.core.trace_dir import (
    TraceEntry,
    TraceListing,
    TraceUnreadableError,
    list_traces,
    paused_marker,
    read_trace_meta_and_lock_strict,
    read_trace_trailer_strict,
)
from pflow.core.trace_tree import normalize_workflow_path_key
from pflow.runtime.resume_source import _find_consuming_attempt, answerable_pause

logger = logging.getLogger(__name__)

RETENTION_ENV_VAR = "PFLOW_TRACE_RETENTION_DAYS"
_REUSABLE_STATUSES = ("success", "degraded")
# Windows refuses to unlink a file another process holds open (winerror 5 / 32): retry once, then skip.
_WINDOWS_TRANSIENT_UNLINK_ERRORS = frozenset({5, 32})
_WINDOWS_UNLINK_RETRY_DELAY = 0.05


@dataclass(frozen=True)
class SweepReport:
    """What one sweep did: how many traces it removed, and what it could not judge or remove — ``skipped``
    the traces whose removal failed (``"<path>: <cause>"``), ``unreadable`` the aged traces kept because they
    could not be read, ``unchecked_workflows`` the workflow files whose existence could not be determined
    (their traces kept)."""

    removed: int = 0
    skipped: tuple[str, ...] = ()
    unreadable: tuple[Path, ...] = ()
    unchecked_workflows: tuple[str, ...] = ()


def retention_days() -> int | None:
    """The age window in days. ``0`` keeps everything; ``None`` means "cannot tell — prune nothing", always with
    a warning. ONE resolution order, so ``pflow settings show`` and a run's sweep never disagree:

    1. ``PFLOW_TRACE_RETENTION_DAYS`` in the process environment;
    2. the settings file failed to load → ``None``;
    3. ``PFLOW_TRACE_RETENTION_DAYS`` stored in ``settings.env`` — what startup injection exports, so a run
       sees it at step 1 and ``show`` (which injects nothing) sees it here; read directly so a skipped or
       aborted injection never loses it;
    4. a misspelled override in the process (a ``PFLOW_`` variable, ``_misspelled_env_variable``) → ``None``;
    5. an opt-out spelled or placed wrong in the file — any unknown key at any level, or a ``settings.env``
       name (``_mentions_retention``, ``_misspelled_env_override``) → ``None``;
    6. ``runtime.trace_retention_days``.

    An override that is not a whole number ≥ 0 is ``None`` (``never`` must not fall through to the default and
    delete). The override is never written to the settings file."""
    raw = os.environ.get(RETENTION_ENV_VAR)
    if raw is not None:
        return _override_days(raw, RETENTION_ENV_VAR)
    manager = SettingsManager()
    settings = manager.load()
    if manager.load_error is not None:
        logger.warning(
            "trace retention skipped: %s could not be loaded (%s)", manager.settings_path, manager.load_error
        )
        return None
    stored = settings.env.get(RETENTION_ENV_VAR)
    if stored is not None:
        return _override_days(stored, f"env.{RETENTION_ENV_VAR} in {manager.settings_path}")
    misspelled = sorted(name for name in os.environ if _misspelled_env_variable(name))
    if misspelled:
        # One warning: a settings.env typo reaches here too (startup copies settings.env into os.environ), so
        # the settings check below never reports it a second time.
        logger.warning(
            "trace retention skipped: the environment sets %s (directly or through settings.env), which pflow "
            "does not read — the variable is %s, spelled exactly (0 keeps every trace)",
            ", ".join(misspelled),
            RETENTION_ENV_VAR,
        )
        return None
    suspects = [
        ".".join(path) for path, value in unknown_settings_keys(settings) if _mentions_retention(path[-1], value)
    ]
    suspects += [f"env.{name}" for name in settings.env if _misspelled_env_override(name)]
    if suspects:
        logger.warning(
            "trace retention skipped: %s sets %s, which pflow does not read — the setting is "
            "runtime.trace_retention_days, or %s in env, spelled exactly (0 keeps every trace)",
            manager.settings_path,
            ", ".join(sorted(suspects)),
            RETENTION_ENV_VAR,
        )
        return None
    return settings.runtime.trace_retention_days


def _override_days(raw: str, source: str) -> int | None:
    """The override's value: a whole number ≥ 0, else ``None`` with a warning naming where it came from."""
    try:
        days = int(raw)
    except ValueError:
        days = -1
    if days >= 0:
        return days
    logger.warning("trace retention skipped: %s=%r is not a whole number of days (0 keeps every trace)", source, raw)
    return None


# Stems, not the whole word: a typo inside it (``retension``, ``retenton``, ``retain``) must still switch
# retention off rather than leave deletion on.
_RETENTION_STEMS = ("reten", "retain")


def _looks_like_retention(name: str) -> bool:
    lower = name.lower()
    return any(stem in lower for stem in _RETENTION_STEMS)


def _mentions_retention(key: str, value: Any) -> bool:
    """Whether an unknown settings key — or any key nested in its value, through objects and arrays — looks like
    the retention setting."""
    if _looks_like_retention(key):
        return True
    children = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    return any(_mentions_retention(str(k), v) for k, v in children)


def _misspelled_env_override(name: str) -> bool:
    """Whether a ``settings.env`` name looks like the override but is not it (``PFLOW_TRACE_RETENSION_DAYS``).
    ``settings.env`` also carries the user's own variables, so the name must also say ``trace`` or start with
    ``PFLOW_`` — ``S3_RETENTION_DAYS`` leaves retention on."""
    lower = name.lower()
    return (
        name != RETENTION_ENV_VAR and _looks_like_retention(name) and ("trace" in lower or lower.startswith("pflow_"))
    )


def _misspelled_env_variable(name: str) -> bool:
    """Whether a process environment name looks like the override but is not it (``PFLOW_TRACE_RETENTON_DAYS``).
    Only pflow's own ``PFLOW_`` namespace counts: other tools' variables (``OTEL_…_RETENTION``) never switch
    pflow's retention off."""
    return name != RETENTION_ENV_VAR and name.upper().startswith("PFLOW_") and _looks_like_retention(name)


def sweep_after_write(directory: Path) -> None:
    """Apply Retention to ``directory`` after a trace was written there. Never raises: a fault is a warning,
    and a run's outcome never depends on its sweep."""
    try:
        days = retention_days()
        if not days:
            return
        report = prune_traces(directory, keep_days=days)
        if report.skipped or report.unreadable or report.unchecked_workflows:
            logger.warning("trace retention %s", _problems(report))
    except Exception as exc:
        logger.warning("trace retention failed, no further traces removed: %s", exc)


def _problems(report: SweepReport) -> str:
    """The one warning's body: what this sweep could not judge or remove, naming the first three of each and
    what to check — a fault that outlives the next run's retry is a permission or filesystem problem."""

    def first_three(items: tuple[Any, ...]) -> str:
        more = f", and {len(items) - 3} more" if len(items) > 3 else ""
        return f" ({'; '.join(str(item) for item in items[:3])}{more})"

    parts = []
    if report.unreadable:
        parts.append(
            f"kept {len(report.unreadable)} unreadable trace(s){first_three(report.unreadable)} — "
            "check those files (their permissions, or whether they are corrupt)"
        )
    if report.unchecked_workflows:
        parts.append(
            f"kept the traces of {len(report.unchecked_workflows)} workflow(s) whose file could not be checked"
            f"{first_three(report.unchecked_workflows)}"
        )
    if report.skipped:
        parts.append(
            f"could not remove {len(report.skipped)} trace(s){first_three(report.skipped)} — the next run "
            "retries; if this repeats, check the permissions of the trace directory and those files"
        )
    return "; ".join(parts)


def prune_traces(directory: Path, *, keep_days: int, now: datetime | None = None) -> SweepReport:
    """Remove every trace in ``directory`` started more than ``keep_days`` ago, except the Protected traces
    (module docstring). ``keep_days <= 0`` removes nothing. A directory that cannot be listed raises."""
    if keep_days <= 0:
        return SweepReport()
    try:
        cutoff = (now or datetime.now()) - timedelta(days=keep_days)
    except OverflowError:  # a window longer than the calendar: nothing is old enough
        return SweepReport()
    return _Sweep(list_traces(directory, include_legacy=True), cutoff).run()


def _is_aged(entry: TraceEntry, cutoff: datetime) -> bool:
    try:
        return entry.started_at < cutoff
    except ValueError:  # a name whose digits are not a real date: never a candidate
        return False


def _workflow_path(meta: dict[str, Any] | None) -> str | None:
    path = meta.get("workflow_path") if meta is not None else None
    return path if isinstance(path, str) and path else None


def _is_snapshot_trailer(trailer: dict[str, Any] | None) -> bool:
    """A trailer that can back a Snapshot: success/degraded over at least one executed step (the loader skips
    a run with no events; ``nodes_executed`` counts the executed top-level events)."""
    if trailer is None or str(trailer.get("final_status") or "success") not in _REUSABLE_STATUSES:
        return False
    executed = trailer.get("nodes_executed")
    return not (isinstance(executed, int) and executed <= 0)


def _unknown_facts(entry: TraceEntry) -> bool:
    return bool(entry.unknown_tags or entry.other_sidecars)


@dataclass
class _Group:
    """The traces of one workflow hash, newest-first, and what the sweep learned about them."""

    entries: list[TraceEntry]
    aged: list[TraceEntry]
    identity: str | None = None
    snapshot: TraceEntry | None = None
    kept: bool = False


class _Sweep:
    """One sweep's state: the listing, the per-file and per-path read caches, and the protected set."""

    def __init__(self, listing: TraceListing, cutoff: datetime) -> None:
        self.listing = listing
        self.cutoff = cutoff
        self.protected: set[Path] = set()
        self.unreadable: dict[Path, None] = {}  # insertion-ordered set
        self.skipped: dict[Path, str] = {}  # removals that failed, with their cause
        self._heads: dict[Path, tuple[dict[str, Any] | None, bool | None]] = {}
        self._states: dict[str, PathState] = {}
        # Traces a classification read found unfinished (no trailer): their writer may finalize before the
        # unlink, so the removal re-reads them (``_still_removable``).
        self._unfinished: set[Path] = set()
        self._rules_applied: set[str] = set()  # workflows whose rules 2-3 ran (normalized paths)

    def run(self) -> SweepReport:
        groups: dict[str, list[TraceEntry]] = {}
        for entry in self.listing.traces:  # newest-first, so every group is too
            groups.setdefault(entry.workflow_hash, []).append(entry)
        examined: list[_Group] = []
        for entries in groups.values():
            aged = [entry for entry in entries if _is_aged(entry, self.cutoff)]
            if aged:
                group = _Group(entries=entries, aged=aged)
                self._classify(group)
                examined.append(group)
        candidates = [entry for group in examined for entry in self._removal_candidates(group)]
        # A later group's rules can protect an earlier candidate (an Attempt's source is matched across groups).
        candidates = [entry for entry in candidates if entry.path not in self.protected]
        for entry in self.listing.legacy:  # pre-185 names: age alone, zero reads
            if _is_aged(entry, self.cutoff):
                if _unknown_facts(entry):
                    self.protected.add(entry.path)
                else:
                    candidates.append(entry)
        removed = self._remove_in_waves(candidates)
        self._remove_orphan_markers()
        return SweepReport(
            removed=removed,
            skipped=tuple(f"{path}: {cause}" for path, cause in self.skipped.items()),
            unreadable=tuple(self.unreadable),
            unchecked_workflows=tuple(path for path, state in self._states.items() if state == "unknown"),
        )

    # --- reads (cached; FileNotFoundError and TraceUnreadableError propagate) ---

    def _head(self, entry: TraceEntry) -> tuple[dict[str, Any] | None, bool | None]:
        """The meta line and the lock verdict, through one open per file per sweep."""
        if entry.path not in self._heads:
            self._heads[entry.path] = read_trace_meta_and_lock_strict(entry.path)
        return self._heads[entry.path]

    def _trailer(self, entry: TraceEntry) -> dict[str, Any] | None:
        """``read_trace_trailer_strict``, remembering a trace read while unfinished."""
        trailer = read_trace_trailer_strict(entry.path)
        if trailer is None:
            self._unfinished.add(entry.path)
        return trailer

    def _file_state(self, workflow_path: str) -> PathState:
        """Rules 1-3 apply only while this is ``present`` (one stat per path per sweep); an inline
        ``ir-hash:`` identity has no file."""
        if workflow_path not in self._states:
            self._states[workflow_path] = (
                "absent" if workflow_path.startswith("ir-hash:") else path_state(workflow_path)
            )
        return self._states[workflow_path]

    def _note_unreadable(self, entry: TraceEntry) -> None:
        self.unreadable[entry.path] = None
        self.protected.add(entry.path)

    def _keep_group(self, group: _Group) -> None:
        group.kept = True
        self.protected.update(entry.path for entry in group.aged)

    # --- classification ---

    def _classify(self, group: _Group) -> None:
        """Apply the name-only rules and rules 1-3 to one group."""
        for entry in group.aged:
            if _unknown_facts(entry):
                self.protected.add(entry.path)
        identity_entry = self._find_identity(group)
        if group.kept:
            return
        if group.identity is not None:
            self._rules_applied.add(normalize_workflow_path_key(group.identity))
            state = self._file_state(group.identity)
            if state == "unknown":
                self._keep_group(group)
                return
            if state == "present":
                self._apply_newest_run_rule(group, identity_entry)
                if not all(entry.path in self.protected for entry in group.aged if not entry.only):
                    group.snapshot = self._protect_snapshot(group, group.identity)
                if group.kept:
                    return
        self._apply_pending_pause_rule(group)

    def _find_identity(self, group: _Group) -> TraceEntry | None:
        """The group's newest run: the newest trace whose head names its workflow — the group's identity.
        Walks back past head-less files (a run whose meta line never landed: the disk-full run this sweep
        follows leaves exactly that, young, as the newest name); usually one read, of the newest trace. A
        head that cannot be read keeps the group (it is newer than anything the rules would pick)."""
        for entry in group.entries:
            try:
                meta, _locked = self._head(entry)
            except FileNotFoundError:
                continue
            except TraceUnreadableError:
                self._note_unreadable(entry)
                self._keep_group(group)
                return None
            path = _workflow_path(meta)
            if path is not None:
                group.identity = path
                return entry
        return None

    def _apply_newest_run_rule(self, group: _Group, newest_run: TraceEntry | None) -> None:
        """Rule 3: the group's newest run (its identity entry). An Attempt as the newest run — or as the newest
        name, by its tag alone — protects its source too: a dead zero-work Attempt must not move "the newest
        run" off a resumable source."""
        if newest_run is not None:
            self.protected.add(newest_run.path)
        for entry in (group.entries[0], newest_run):
            if entry is not None and entry.resumed_from_prefix is not None:
                self._protect_source(entry)

    def _protect_source(self, attempt: TraceEntry) -> None:
        """Protect the Run an Attempt resumed — by its id prefix, across the whole listing (an Attempt may be
        filed under another spelling's hash)."""
        prefix = attempt.resumed_from_prefix
        for entry in self.listing.traces:
            if entry is not attempt and entry.execution_id is not None and entry.execution_id[:8] == prefix:
                self.protected.add(entry.path)

    def _protect_snapshot(self, group: _Group, workflow_path: str) -> TraceEntry | None:
        """Rule 2 for one workflow of the group: the newest aged full run with a Snapshot trailer whose head
        names that workflow. Walks aged traces only — a workflow's young runs are never read, so an aged pick
        may be kept beside a younger Snapshot. Another workflow's success met on the way (an md5[:8] collision)
        is passed over here and judged by the removal probe; an unreadable trace met before the pick could be
        the real Snapshot and keeps the group."""
        walked_unreadable = False
        for entry in group.aged:
            if entry.only:
                continue
            try:
                if not _is_snapshot_trailer(self._trailer(entry)):
                    continue
                path = _workflow_path(self._head(entry)[0])
            except FileNotFoundError:
                continue
            except TraceUnreadableError:
                self._note_unreadable(entry)
                walked_unreadable = True
                continue
            if path is None:
                continue
            if _same_workflow(path, workflow_path):
                self.protected.add(entry.path)
                if walked_unreadable:
                    self._keep_group(group)
                return entry
        return None

    def _apply_pending_pause_rule(self, group: _Group) -> None:
        """Rule 1: a marked aged trace that is an answerable pause no Attempt has consumed."""
        for entry in group.aged:
            if not entry.paused:
                continue
            try:
                meta = self._head(entry)[0]
                trailer = self._trailer(entry)
            except FileNotFoundError:
                continue
            except TraceUnreadableError:  # a marked trace could be a pending pause: keep the group
                self._note_unreadable(entry)
                self._keep_group(group)
                return
            path = _workflow_path(meta)
            verdict = answerable_pause(entry, meta, trailer, self._file_state(path) if path else "absent")
            if verdict == "unknown":
                self._keep_group(group)
                return
            if verdict == "no" or path is None or meta is None:
                continue
            execution_id = str(meta.get("execution_id") or entry.execution_id)
            try:
                consumer = _find_consuming_attempt(path, execution_id, entries=self.listing.traces, count_live=False)
            except ResumeSourceUnreadableError as exc:  # an Attempt we cannot read might not have consumed it
                logger.debug("Keeping %s: an attempt of it could not be read (%s)", entry.path, exc)
                self.unreadable[Path(exc.trace_path) if exc.trace_path else entry.path] = None
                consumer = None
            if consumer is None:
                self.protected.add(entry.path)

    def _apply_collider_rules(self, group: _Group, workflow_path: str) -> None:
        """Rules 3 and 2 for a workflow that shares the group's hash but is not its identity (an md5[:8]
        collision): its newest run — found by walking the group's heads, young ones included (collisions are
        rare) — and its Snapshot. Once per workflow per sweep."""
        key = normalize_workflow_path_key(workflow_path)
        if key in self._rules_applied:
            return
        self._rules_applied.add(key)
        state = self._file_state(workflow_path)
        if state == "unknown":
            self._keep_group(group)
        if state != "present":
            return
        for entry in group.entries:
            try:
                path = _workflow_path(self._head(entry)[0])
            except FileNotFoundError:
                continue
            except TraceUnreadableError:
                self._note_unreadable(entry)
                self._keep_group(group)
                return
            if _same_workflow(path, workflow_path):
                self.protected.add(entry.path)
                if entry.resumed_from_prefix is not None:
                    self._protect_source(entry)
                break
        self._protect_snapshot(group, workflow_path)

    def _removal_candidates(self, group: _Group) -> list[TraceEntry]:
        """The group's aged traces no rule protects, each confirmed through one open (head + lock probe): a
        live writer keeps it (rule 5); a head naming another workflow re-applies rules 2-3 for that workflow;
        an unreadable one is kept, with the group when it is marked, an Attempt, or newer than the Snapshot."""
        candidates: list[TraceEntry] = []
        for entry in group.aged:
            if group.kept:
                return []
            if entry.path in self.protected:
                continue
            try:
                meta, locked = self._head(entry)
            except FileNotFoundError:
                continue
            except TraceUnreadableError:
                self._note_unreadable(entry)
                newer_than_snapshot = group.snapshot is not None and (entry.started, entry.path.name) > (
                    group.snapshot.started,
                    group.snapshot.path.name,
                )
                if entry.paused or entry.resumed_from_prefix is not None or newer_than_snapshot:
                    self._keep_group(group)
                continue
            if locked is True:
                self.protected.add(entry.path)
                continue
            path = _workflow_path(meta)
            if path is not None and group.identity is not None and not _same_workflow(path, group.identity):
                self._apply_collider_rules(group, path)
                if entry.path in self.protected:
                    continue
            candidates.append(entry)
        return [] if group.kept else candidates

    # --- removal ---

    def _remove_in_waves(self, candidates: list[TraceEntry]) -> int:
        """Rule 4: an Attempt goes only once its source is gone. Wave 1 removes every candidate that is not an
        Attempt and the Attempts whose source is already absent; each later wave the Attempts whose source the
        previous wave removed. A source that could not be removed keeps its Attempts. Returns how many traces
        were removed."""
        present = Counter(entry.execution_id[:8] for entry in self.listing.traces if entry.execution_id)
        removed = 0
        pending = candidates
        while pending:
            wave = [entry for entry in pending if not _source_present(entry, present)]
            if not wave:
                break
            in_wave = {entry.path for entry in wave}
            pending = [entry for entry in pending if entry.path not in in_wave]
            for entry in wave:
                if self._remove(entry):
                    removed += 1
                    if entry.execution_id:
                        present[entry.execution_id[:8]] -= 1
        return removed

    def _remove(self, entry: TraceEntry) -> bool:
        """Unlink a trace, then its marker (never the marker first: a pause must not lose its index entry while
        its trace stays) — re-checking before each attempt that the trace did not finalize since it was judged.
        ``False``: kept — it finalized meanwhile, or its removal failed (recorded in ``skipped``, retried next
        sweep)."""
        for attempt in (1, 2):
            if not self._still_removable(entry):
                return False
            try:
                entry.path.unlink(missing_ok=True)
                break
            except PermissionError as exc:
                transient = getattr(exc, "winerror", None) in _WINDOWS_TRANSIENT_UNLINK_ERRORS
                if attempt == 2 or not transient:
                    self.skipped[entry.path] = exc.strerror or str(exc)
                    return False
                time.sleep(_WINDOWS_UNLINK_RETRY_DELAY)  # Windows: another process holds it open
            except OSError as exc:
                self.skipped[entry.path] = exc.strerror or str(exc)
                return False
        if entry.paused:
            try:
                paused_marker(entry.path).unlink(missing_ok=True)
            except OSError:  # an orphan marker; the next sweep removes it
                logger.debug("Could not remove marker of %s", entry.path, exc_info=True)
        return True

    def _still_removable(self, entry: TraceEntry) -> bool:
        """The facts a judgment rested on still hold. A writer finishing between the listing and the unlink
        (it held its lock while the sweep listed and classified) can add the ``.paused`` marker or the trailer
        that would have protected the trace — so after its lock was seen free, a marker that appeared or a
        trailer that landed on a trace judged unfinished keeps it this sweep. Legacy names are never written."""
        if entry.legacy:
            return True
        if not entry.paused:
            try:
                os.lstat(paused_marker(entry.path))
                return False  # finalized Paused since the listing
            except FileNotFoundError:
                pass
            except OSError:
                self.unreadable[entry.path] = None  # cannot tell: keep it, and say so
                return False
        if entry.path in self._unfinished:
            try:
                return read_trace_trailer_strict(entry.path) is None
            except FileNotFoundError:
                return True  # already gone: the unlink is a no-op
            except TraceUnreadableError:
                self.unreadable[entry.path] = None
                return False
        return True

    def _remove_orphan_markers(self) -> None:
        """A ``.paused`` marker whose trace is gone — removed only after a stat proves the trace absent (a
        listing racing concurrent unlinks may skip a live name)."""
        for marker in self.listing.orphan_markers:
            try:
                os.lstat(marker.with_name(marker.name.removesuffix(".paused")))
            except FileNotFoundError:
                try:
                    marker.unlink(missing_ok=True)
                except OSError:
                    logger.debug("Could not remove orphan marker %s", marker, exc_info=True)
            except OSError:
                continue


def _same_workflow(path: str | None, other: str) -> bool:
    return path is not None and normalize_workflow_path_key(path) == normalize_workflow_path_key(other)


def _source_present(entry: TraceEntry, present: Counter[str]) -> bool:
    """Whether the Run this Attempt resumed is still in the directory (never for a non-Attempt)."""
    prefix = entry.resumed_from_prefix
    if prefix is None:
        return False
    own = 1 if entry.execution_id is not None and entry.execution_id[:8] == prefix else 0
    return present[prefix] - own > 0
