"""reserve_stdout unwinding and closed-stdout behavior, at the descriptor level.

The surface-level contract (stray writes never reach machine output) is pinned by
real subprocesses in tests/test_integration/test_stdout_reserved_e2e.py.
"""

import os
import sys

import pytest

from pflow.core.stdout_reservation import reserve_stdout


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
