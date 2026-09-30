"""reserve_stdout / reserve_stdin unwinding and closed-stream behavior, at the descriptor level.

The surface-level contract (stray writes never reach machine output) is pinned by
real subprocesses in tests/test_integration/test_stdio_reserved_e2e.py.
"""

import os
import sys
from collections.abc import Iterator

import pytest

from pflow.core.stdio_reservation import reserve_stdin, reserve_stdout


def test_fd1_is_restored_after_an_exception_escapes(capfd: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(RuntimeError), reserve_stdout() as reserved:
        os.write(1, b"STRAY\n")
        reserved.write(b"MACHINE\n")
        raise RuntimeError("boom")
    os.write(1, b"AFTER\n")

    captured = capfd.readouterr()
    assert captured.out == "MACHINE\nAFTER\n"
    assert captured.err == "STRAY\n"


def test_closed_stdout_runs_unreserved(monkeypatch: pytest.MonkeyPatch) -> None:
    # Python sets sys.stdout to None when fd 1 is closed at startup (`pflow wf >&-`).
    monkeypatch.setattr(sys, "stdout", None)
    with reserve_stdout() as reserved:
        reserved.write(b"discarded")


@pytest.fixture
def stdin_pipe() -> Iterator[int]:
    """Point fd 0 at a pipe holding b"PROTOCOL\\n" (pytest leaves it on /dev/null); yield the write end."""
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"PROTOCOL\n")
    saved = os.dup(0)
    os.dup2(read_fd, 0)
    os.close(read_fd)
    try:
        yield write_fd
    finally:
        os.dup2(saved, 0)
        os.close(saved)
        os.close(write_fd)


def test_fd0_reads_eof_inside_and_the_real_stdin_after_an_exception(stdin_pipe: int) -> None:
    with pytest.raises(RuntimeError), reserve_stdin() as reserved:
        assert os.read(0, 64) == b""  # what workflow code and inheriting children see
        assert reserved.readline() == b"PROTOCOL\n"
        raise RuntimeError("boom")
    os.write(stdin_pipe, b"AFTER\n")
    assert os.read(0, 64) == b"AFTER\n"


def test_closed_stdin_runs_unreserved(monkeypatch: pytest.MonkeyPatch) -> None:
    # Python sets sys.stdin to None when fd 0 is closed at startup (`pflow mcp serve <&-`).
    monkeypatch.setattr(sys, "stdin", None)
    with reserve_stdin() as reserved:
        assert reserved.read() == b""
