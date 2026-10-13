"""``core/trace_dir`` — the trace directory is the index (Task 185, ADR-0018).

The filename grammar (one composer, one parser), the one listing, the strict/lenient reader pairs, the
writer-lock probe and the workflow-file probe. Lookups that USE the listing are pinned where they live
(``test_run_lookup_reads.py`` holds the read-set pins on the public surfaces).
"""

from __future__ import annotations

import errno
import fnmatch
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

from pflow.core.trace_dir import (
    TraceUnreadableError,
    find_trace,
    is_trace_locked,
    list_traces,
    parse_trace_filename,
    paused_marker,
    read_trace_meta,
    read_trace_meta_strict,
    read_trace_trailer,
    read_trace_trailer_strict,
    trace_filename,
    workflow_hash,
    workflow_hashes,
)

_unix_only = pytest.mark.skipif(sys.platform == "win32", reason="advisory flock is POSIX-only")

WF = "/work/project/wf.pflow.md"
STARTED = datetime(2026, 10, 13, 9, 30, 15, 123456)


def _touch(directory: Path, name: str, text: str = "") -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


# ── Grammar ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("only", "resumed_from", "tags"),
    [
        (False, None, ""),
        (True, None, ".only"),
        (False, "0b7e6a52-1c4d-4e8f-9a3b-5d6c7e8f9a0b", ".from-0b7e6a52"),
        (True, "src", ".only.from-src"),  # a short source id composes whole and parses back
    ],
)
def test_composer_and_parser_round_trip_every_tag_combination(only: bool, resumed_from: str | None, tags: str) -> None:
    name = trace_filename(WF, "My Workflow!", STARTED, "run-1", only=only, resumed_from=resumed_from)

    assert name == f"workflow-trace-{workflow_hash(WF)}-My-Workflow.run-1{tags}-20261013-093015-123456.json"
    parsed = parse_trace_filename(name)
    assert parsed is not None
    assert (parsed.workflow_hash, parsed.execution_id, parsed.only) == (workflow_hash(WF), "run-1", only)
    assert parsed.resumed_from_prefix == (resumed_from[:8] if resumed_from else None)
    assert parsed.started == "20261013-093015-123456"
    assert parsed.started_at == STARTED
    assert parsed.unknown_tags == ()


def test_the_name_segment_is_always_written() -> None:
    """A nameless or ``workflow``-named run still writes the name — the pre-185 hash glob
    ``workflow-trace-{hash}-*.json`` needs the dash after the hash."""
    assert trace_filename(None, "", STARTED, "x").startswith("workflow-trace-d41d8cd9-workflow.x-")
    assert trace_filename(None, "workflow", STARTED, "x").startswith("workflow-trace-d41d8cd9-workflow.x-")
    assert trace_filename(None, "!!!", STARTED, "x").startswith("workflow-trace-d41d8cd9-workflow.x-")


@pytest.mark.parametrize("bad_id", ["a.b", "a/b", "", "run 1"])
def test_composer_rejects_an_id_outside_the_filename_charset(bad_id: str) -> None:
    with pytest.raises(ValueError, match="filename-safe"):
        trace_filename(WF, "wf", STARTED, bad_id)
    with pytest.raises(ValueError, match="filename-safe"):
        trace_filename(WF, "wf", STARTED, "ok", resumed_from=bad_id or ".")


def test_an_unknown_future_tag_parses_as_current_and_is_carried_not_dropped() -> None:
    parsed = parse_trace_filename(
        f"workflow-trace-{workflow_hash(WF)}-wf.run-1.recording.only-20261013-093015-123456.json"
    )
    assert parsed is not None
    assert (parsed.execution_id, parsed.only, parsed.unknown_tags) == ("run-1", True, ("recording",))


def test_a_display_name_that_looks_like_a_timestamp_does_not_confuse_the_parser() -> None:
    name = trace_filename(WF, "report-20250101-000000-000000", STARTED, "abc")
    parsed = parse_trace_filename(name)
    assert parsed is not None
    assert (parsed.execution_id, parsed.started) == ("abc", "20261013-093015-123456")


@pytest.mark.parametrize(
    ("name", "started"),
    [
        ("workflow-trace-3a8ac2b2-my-wf-20260412-093015-123456.json", "20260412-093015-123456"),
        ("workflow-trace-3a8ac2b2-20260412-093015.json", "20260412-093015"),  # nameless, short timestamp
    ],
)
def test_pre_185_names_parse_as_legacy_for_their_timestamp_only(name: str, started: str) -> None:
    parsed = parse_trace_filename(name)
    assert parsed is not None
    assert parsed.legacy and parsed.execution_id is None
    assert parsed.started == started
    assert parsed.started_at.year == 2026


@pytest.mark.parametrize(
    "name",
    [
        "workflow-trace-3a8ac2b2-wf.run.9x-20260412-093015-123456.json",  # a tag the current arm rejects
        "workflow-trace-3a8ac2b2-wf.run..x-20260412-093015-123456.json",  # an empty dot segment
        "workflow-trace-aaa-wf-20260101-000000-000001.json",  # not an 8-hex hash
        "workflow-trace-my-wf-20260101-000000.json",  # pre-#378, hash-less
        "workflow-trace-3a8ac2b2-wf.run-20260412-093015-123456.json.paused",  # a sidecar
        "foo.json",
    ],
)
def test_names_outside_both_grammars_are_not_traces(name: str) -> None:
    assert parse_trace_filename(name) is None


def test_every_composed_name_is_ordered_and_found_by_a_pre_185_reader() -> None:
    """Version skew: an older pflow sharing ``~/.pflow`` sorts by its ``-{ts}.json$`` key and globs
    ``workflow-trace-{hash}-*.json`` — both must accept every name this version composes, or the older
    ``--only`` ranks every new trace oldest and restores stale upstream."""
    pre_185_recency = re.compile(r"(\d{8}-\d{6}(?:-\d+)?)\.json$")
    for workflow_path, workflow_name in ((WF, "wf"), ("/x/workflow.pflow.md", "workflow"), (None, "")):
        for only in (False, True):
            for resumed_from in (None, "src-run-id"):
                name = trace_filename(
                    workflow_path, workflow_name, STARTED, "run-1", only=only, resumed_from=resumed_from
                )
                match = pre_185_recency.search(name)
                assert match is not None and match.group(1) == "20261013-093015-123456", name
                assert fnmatch.fnmatch(name, f"workflow-trace-{workflow_hash(workflow_path)}-*.json"), name


def test_workflow_hashes_cover_the_three_path_spellings() -> None:
    assert workflow_hashes("C:\\work\\wf.pflow.md") == {
        workflow_hash("C:\\work\\wf.pflow.md"),
        workflow_hash("C:/work/wf.pflow.md"),
    }
    assert workflow_hash(WF) in workflow_hashes(WF)


# ── The listing ─────────────────────────────────────────────────────────────


def test_list_traces_orders_newest_first_by_start_time_whatever_the_name(tmp_path: Path) -> None:
    older = _touch(tmp_path, trace_filename(WF, "zzz", datetime(2026, 1, 1), "z-run"))
    newer = _touch(tmp_path, trace_filename(WF, "aaa", datetime(2026, 6, 1), "a-run"))
    middle = _touch(tmp_path, trace_filename("/other.pflow.md", "mmm", datetime(2026, 3, 1), "m-run"))

    assert [entry.path for entry in list_traces(tmp_path).traces] == [newer, middle, older]


def test_list_traces_folds_markers_and_sidecars_in_and_collects_orphan_markers(tmp_path: Path) -> None:
    paused = _touch(tmp_path, trace_filename(WF, "wf", datetime(2026, 1, 2), "paused-run"))
    plain = _touch(tmp_path, trace_filename(WF, "wf", datetime(2026, 1, 1), "plain-run"))
    paused_marker(paused).touch()
    _touch(tmp_path, plain.name + ".claim")  # a sidecar a later pflow may write
    orphan = paused_marker(tmp_path / trace_filename(WF, "wf", datetime(2026, 1, 3), "gone-run"))
    orphan.touch()

    listing = list_traces(tmp_path)

    by_id = {entry.execution_id: entry for entry in listing.traces}
    assert set(by_id) == {"paused-run", "plain-run"}, "a marker is never itself a trace (*.json only)"
    assert by_id["paused-run"].paused and not by_id["plain-run"].paused
    assert by_id["plain-run"].other_sidecars == ("claim",)
    assert by_id["paused-run"].other_sidecars == ()
    assert listing.orphan_markers == [orphan]


def test_list_traces_counts_legacy_names_and_returns_them_only_on_request(tmp_path: Path) -> None:
    current = _touch(tmp_path, trace_filename(WF, "wf", STARTED, "run-1"))
    for index in range(3):
        _touch(tmp_path, f"workflow-trace-3a8ac2b2-wf-2025010{index + 1}-000000.json")
    _touch(tmp_path, "workflow-trace-aaa-junk-20250101-000000.json")  # unrecognised: neither listed nor counted
    _touch(tmp_path, "notes.txt")

    listing = list_traces(tmp_path)
    assert [entry.path for entry in listing.traces] == [current]
    assert (listing.legacy_count, listing.legacy) == (3, [])

    with_legacy = list_traces(tmp_path, include_legacy=True)
    assert with_legacy.legacy_count == 3
    assert sorted(entry.started for entry in with_legacy.legacy) == [
        "20250101-000000",
        "20250102-000000",
        "20250103-000000",
    ]
    assert [entry.path for entry in with_legacy.traces] == [current]


def test_list_traces_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    listing = list_traces(tmp_path / "nope")
    assert (listing.traces, listing.legacy_count, listing.orphan_markers) == ([], 0, [])


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions, non-root")
def test_list_traces_of_an_unreadable_directory_raises_rather_than_reporting_no_runs(tmp_path: Path) -> None:
    locked = tmp_path / "debug"
    locked.mkdir()
    _touch(locked, trace_filename(WF, "wf", STARTED, "run-1"))
    locked.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            list_traces(locked)
    finally:
        locked.chmod(0o755)


def test_find_trace_is_exact_never_a_prefix_or_the_newest(tmp_path: Path) -> None:
    _touch(tmp_path, trace_filename(WF, "wf", datetime(2026, 1, 1), "abc"))
    _touch(tmp_path, trace_filename(WF, "wf", datetime(2026, 1, 2), "abc-2"))  # newer, shares the prefix
    entries = list_traces(tmp_path).traces

    hit = find_trace(entries, "abc")
    assert hit is not None and hit.execution_id == "abc"
    assert find_trace(entries, "ab") is None


def test_fixture_ids_sort_against_start_time() -> None:
    """The shared fixture helper's ids DESCEND as start time ascends (``tests/shared/trace_jsonl``): with the
    id before the timestamp in the name, every recency pin built on it then fails under a whole-filename
    sort. An ascending id would make those pins pass for free."""
    from tests.shared.trace_jsonl import fixture_execution_id

    earlier, later = datetime(2026, 1, 1), datetime(2026, 1, 1, 0, 0, 0, 1)
    names = [trace_filename(WF, "wf", started, fixture_execution_id(started)) for started in (earlier, later)]
    assert sorted(names, reverse=True) == names, "a name sort must rank the EARLIER start first"


# ── Readers ─────────────────────────────────────────────────────────────────


def _lines(path: Path, *lines: dict | str, terminate: bool = True) -> Path:
    text = "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines)
    path.write_text(text + ("\n" if terminate else ""), encoding="utf-8")
    return path


_META = {"kind": "meta", "pflow_trace": "jsonl/1", "execution_id": "run-1", "workflow_path": WF}
_TRAILER = {"kind": "run.complete", "final_status": "success"}


def test_meta_reader_reads_a_newline_less_first_line_as_none_never_unreadable(tmp_path: Path) -> None:
    """A write cut short (a full disk) leaves an unterminated first line: readable, no meta — so the sweep
    ages it out instead of freezing its group as unreadable."""
    assert read_trace_meta_strict(_lines(tmp_path / "cut.json", '{"kind": "me', terminate=False)) is None
    assert read_trace_meta_strict(_lines(tmp_path / "empty.json", "", terminate=False)) is None


def test_meta_reader_on_a_valid_non_meta_first_line_is_none(tmp_path: Path) -> None:
    assert read_trace_meta_strict(_lines(tmp_path / "t.json", {"kind": "event"})) is None


@pytest.mark.parametrize("first_line", [b"{not json\n", b"\xff\xfe garbage\n"])
def test_strict_meta_reader_raises_on_a_corrupt_terminated_first_line(tmp_path: Path, first_line: bytes) -> None:
    path = tmp_path / "t.json"
    path.write_bytes(first_line)
    with pytest.raises(TraceUnreadableError):
        read_trace_meta_strict(path)
    assert read_trace_meta(path) is None


def test_strict_readers_let_a_vanished_file_propagate(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_trace_meta_strict(tmp_path / "gone.json")
    with pytest.raises(FileNotFoundError):
        read_trace_trailer_strict(tmp_path / "gone.json")
    assert read_trace_meta(tmp_path / "gone.json") is None
    assert read_trace_trailer(tmp_path / "gone.json") is None


def test_strict_readers_turn_any_other_read_fault_into_unreadable(tmp_path: Path, monkeypatch) -> None:
    import builtins

    path = _lines(tmp_path / "t.json", _META, _TRAILER)
    real_open = builtins.open

    def failing_open(file, *args, **kwargs):
        if Path(file) == path:
            raise OSError(errno.EMFILE, "Too many open files")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", failing_open)
    with pytest.raises(TraceUnreadableError):
        read_trace_meta_strict(path)
    with pytest.raises(TraceUnreadableError):
        read_trace_trailer_strict(path)
    assert read_trace_meta(path) is None
    assert read_trace_trailer(path) is None


def test_trailer_readers_return_the_trailer_or_none_when_unfinished(tmp_path: Path) -> None:
    finished = _lines(tmp_path / "done.json", _META, {"kind": "event"}, _TRAILER)
    live = _lines(tmp_path / "live.json", _META, {"kind": "node.start"})
    mid_flush = _lines(tmp_path / "flush.json", _META, '{"kind": "run.compl', terminate=False)

    assert read_trace_trailer_strict(finished) == _TRAILER
    assert read_trace_trailer_strict(live) is None
    assert read_trace_trailer_strict(mid_flush) is None, "an unterminated last line is mid-flush, not corrupt"


def test_strict_trailer_reader_raises_on_a_corrupt_terminated_last_line(tmp_path: Path) -> None:
    path = _lines(tmp_path / "t.json", _META, "{corrupt trailer")
    with pytest.raises(TraceUnreadableError):
        read_trace_trailer_strict(path)
    assert read_trace_trailer(path) is None


def test_an_oversized_paused_trailer_is_read_whole(tmp_path: Path) -> None:
    """A paused trailer carries the whole gate request and can exceed the 64 KB tail window; the readers
    re-read the full file rather than miss it (a hidden pending pause / a finished run read as live)."""
    gate_request = {"node_id": "deploy", "kind": "action_approval", "preview": {"payload": "x" * 100_000}}
    trailer = {
        "kind": "run.complete",
        "final_status": "paused",
        "paused_node_id": "deploy",
        "gate_request": gate_request,
    }
    path = _lines(tmp_path / "big.json", _META, trailer)
    assert path.stat().st_size > 65536

    assert read_trace_trailer_strict(path) == trailer
    assert read_trace_trailer(path) == trailer


# ── Lock probe and workflow-file probe ──────────────────────────────────────


@_unix_only
def test_lock_probe_reports_held_free_and_gone(tmp_path: Path) -> None:
    import fcntl

    path = _lines(tmp_path / "t.json", _META)
    assert is_trace_locked(path) is False
    with open(path, encoding="utf-8") as writer:
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX)
        assert is_trace_locked(path) is True
    assert is_trace_locked(tmp_path / "gone.json") is False, "no file, no writer — never 'maybe live'"


@_unix_only
def test_lock_probe_on_a_filesystem_without_flock_is_unknown_not_locked(tmp_path: Path, monkeypatch) -> None:
    import fcntl

    path = _lines(tmp_path / "t.json", _META)

    def no_flock(_fd, _op):
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(fcntl, "flock", no_flock)
    assert is_trace_locked(path) is None


@_unix_only
def test_lock_probe_open_fault_is_unknown(tmp_path: Path, monkeypatch) -> None:
    import builtins

    path = _lines(tmp_path / "t.json", _META)
    real_open = builtins.open

    def failing_open(file, *args, **kwargs):
        if Path(file) == path:
            raise OSError(errno.EMFILE, "Too many open files")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", failing_open)
    assert is_trace_locked(path) is None
