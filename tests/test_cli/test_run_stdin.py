"""Tests for CLI stdin reader routing."""

import io
import types

from pflow.cli.commands import run as run_module


def _fake_binary_stdin(data: bytes):
    return types.SimpleNamespace(buffer=io.BytesIO(data))


def test_win32_binary_stdin_preserves_invalid_utf8_bytes(monkeypatch):
    """Invalid UTF-8 should be consumed once by the binary-aware reader on win32."""
    data = b"\xff\xfeinvalid utf8"
    monkeypatch.setattr(run_module.sys, "platform", "win32")
    monkeypatch.setattr(
        "pflow.core.shell_integration.stdin_has_data",
        lambda: True,
    )
    monkeypatch.setattr(run_module.sys, "stdin", _fake_binary_stdin(data))

    stdin_content, enhanced = run_module._read_stdin_data()

    assert stdin_content is None
    assert enhanced is not None
    assert enhanced.is_binary is True
    assert enhanced.binary_data == data


def test_win32_text_stdin_normalizes_crlf_from_real_buffer(monkeypatch):
    """The enhanced-first win32 path keeps the text semantics of read_stdin()."""
    monkeypatch.setattr(run_module.sys, "platform", "win32")
    monkeypatch.setattr(
        "pflow.core.shell_integration.stdin_has_data",
        lambda: True,
    )
    monkeypatch.setattr(run_module.sys, "stdin", _fake_binary_stdin(b"line1\r\nline2\r\n"))

    assert run_module._read_stdin_data() == ("line1\nline2", None)


def test_win32_empty_pipe_preserves_empty_string(monkeypatch):
    """Empty piped content is valid input, not equivalent to no stdin."""
    monkeypatch.setattr(run_module.sys, "platform", "win32")
    monkeypatch.setattr(
        "pflow.core.shell_integration.stdin_has_data",
        lambda: True,
    )
    monkeypatch.setattr(run_module.sys, "stdin", _fake_binary_stdin(b""))

    assert run_module._read_stdin_data() == ("", None)
