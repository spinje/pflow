"""Windows stdin pipe detection and UTF-8 decode (Task 116).

These tests run on Linux by faking the win32 seams the production code uses:
`sys.platform`, a `msvcrt` module injected into `sys.modules`, and a
`ctypes.windll` attribute (absent on non-Windows ctypes). The real-Windows
ground truth is the inverse-skip e2e test in
tests/test_cli/test_dual_mode_stdin.py — without it a wrong GetFileType
constant here would return False forever and stay green.
"""

import ctypes
import io
import sys
import types
from unittest.mock import patch

import pytest

from pflow.core.shell_integration import _stdin_is_pipe_windows, read_stdin, stdin_has_data

FILE_TYPE_UNKNOWN = 0
FILE_TYPE_DISK = 1
FILE_TYPE_CHAR = 2
FILE_TYPE_PIPE = 3


def _install_fake_win32_api(monkeypatch, file_type=FILE_TYPE_PIPE, get_osfhandle_exc=None):
    """Inject fake msvcrt + ctypes.windll so the win32 detector runs on Linux."""
    fake_msvcrt = types.ModuleType("msvcrt")

    def get_osfhandle(fd):
        if get_osfhandle_exc is not None:
            raise get_osfhandle_exc
        return 1234  # arbitrary fake OS handle

    fake_msvcrt.get_osfhandle = get_osfhandle  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    fake_kernel32 = types.SimpleNamespace(GetFileType=lambda handle: file_type)
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=fake_kernel32), raising=False)


class _FakeStdin:
    """Minimal stdin stand-in that survives stdin_has_data's guard chain."""

    closed = False
    name = "<fake-stdin>"

    def isatty(self):
        return False

    def fileno(self):
        return 0


class TestStdinIsPipeWindows:
    """Behavior table for the GetFileType-based detector."""

    def test_pipe_returns_true(self, monkeypatch):
        _install_fake_win32_api(monkeypatch, file_type=FILE_TYPE_PIPE)
        assert _stdin_is_pipe_windows(0) is True

    def test_console_returns_false(self, monkeypatch):
        _install_fake_win32_api(monkeypatch, file_type=FILE_TYPE_CHAR)
        assert _stdin_is_pipe_windows(0) is False

    def test_disk_redirect_returns_false(self, monkeypatch):
        """File redirects (pflow < file) are not pipes — mirrors Unix S_ISFIFO."""
        _install_fake_win32_api(monkeypatch, file_type=FILE_TYPE_DISK)
        assert _stdin_is_pipe_windows(0) is False

    def test_unknown_type_returns_false(self, monkeypatch):
        _install_fake_win32_api(monkeypatch, file_type=FILE_TYPE_UNKNOWN)
        assert _stdin_is_pipe_windows(0) is False

    def test_get_osfhandle_failure_returns_false(self, monkeypatch):
        """A bad/closed fd degrades to False, matching the module's defensive style."""
        _install_fake_win32_api(monkeypatch, get_osfhandle_exc=OSError("bad fd"))
        assert _stdin_is_pipe_windows(0) is False

    @pytest.mark.skipif(sys.platform == "win32", reason="on real Windows the API exists; this tests its absence")
    def test_missing_win32_api_returns_false(self):
        """Without fakes (i.e. on a real non-Windows box) the broad except catches
        the missing msvcrt/windll and returns False instead of crashing."""
        assert _stdin_is_pipe_windows(0) is False


class TestStdinHasDataWindowsRouting:
    """stdin_has_data() must route through the win32 detector on win32."""

    def test_pipe_detected_on_win32(self, monkeypatch):
        _install_fake_win32_api(monkeypatch, file_type=FILE_TYPE_PIPE)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "stdin", _FakeStdin())
        assert stdin_has_data() is True

    def test_console_skipped_on_win32(self, monkeypatch):
        _install_fake_win32_api(monkeypatch, file_type=FILE_TYPE_CHAR)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "stdin", _FakeStdin())
        assert stdin_has_data() is False

    def test_non_win32_still_uses_fifo_path(self, monkeypatch):
        """On Unix the S_ISFIFO path is untouched: a regular fd is not a FIFO."""
        monkeypatch.setattr(sys, "stdin", _FakeStdin())  # fd 0 in pytest: not a FIFO
        assert stdin_has_data() is False


class TestReadStdinWindowsDecode:
    """read_stdin() must decode UTF-8 bytes on win32, not the locale code page."""

    def test_utf8_bytes_decode_correctly(self, monkeypatch):
        fake_stdin = types.SimpleNamespace(buffer=io.BytesIO("café ☕ naïve\n".encode()))
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        with patch("pflow.core.shell_integration.stdin_has_data", return_value=True):
            assert read_stdin() == "café ☕ naïve"

    def test_crlf_translated_like_unix_text_read(self, monkeypatch):
        """Native Windows producers (cmd.exe echo, type, PowerShell) emit \\r\\n.
        The win32 read must apply the same universal-newline translation the
        Unix text-mode read does, or `echo x| pflow` routes "x\\r" into the
        input — a per-platform meaning change ADR-0013 exists to prevent."""
        fake_stdin = types.SimpleNamespace(buffer=io.BytesIO(b"line1\r\nline2\r\n"))
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        with patch("pflow.core.shell_integration.stdin_has_data", return_value=True):
            assert read_stdin() == "line1\nline2"

    def test_invalid_utf8_returns_none_without_closing_stdin(self, monkeypatch):
        """Binary/undecodable input degrades to None (enhanced reading handles it),
        same contract as the Unix path — and the wrapper must detach rather than
        close the underlying buffer, or the read_stdin_enhanced fallback would
        find stdin already closed."""
        buffer = io.BytesIO(b"\xff\xfe\x00binary")
        fake_stdin = types.SimpleNamespace(buffer=buffer)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        with patch("pflow.core.shell_integration.stdin_has_data", return_value=True):
            assert read_stdin() is None
        assert not buffer.closed

    def test_empty_pipe_returns_empty_string(self, monkeypatch):
        """`echo -n "" | pflow`: empty content is valid content (Unix contract),
        the win32 branch must not turn it into None."""
        fake_stdin = types.SimpleNamespace(buffer=io.BytesIO(b""))
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        with patch("pflow.core.shell_integration.stdin_has_data", return_value=True):
            assert read_stdin() == ""

    def test_unix_path_unchanged(self):
        """Non-win32 read_stdin still reads the text stream (StringIO has no
        .buffer — this would crash if the win32 branch leaked)."""
        with (
            patch("sys.stdin", io.StringIO("plain text")),
            patch("pflow.core.shell_integration.stdin_has_data", return_value=True),
        ):
            assert read_stdin() == "plain text"
