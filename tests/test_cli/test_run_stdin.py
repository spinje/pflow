"""Tests for CLI stdin reader routing."""

from pflow.cli.commands import run as run_module
from pflow.core import StdinData


def test_win32_binary_stdin_uses_enhanced_reader_without_text_probe(monkeypatch):
    """Invalid UTF-8 should be consumed once by the binary-aware reader on win32."""
    data = StdinData(binary_data=b"\xff\xfe\x00binary")
    monkeypatch.setattr(run_module.sys, "platform", "win32")
    monkeypatch.setattr(run_module, "read_stdin_enhanced", lambda: data)
    monkeypatch.setattr(
        run_module,
        "read_stdin_content",
        lambda: (_ for _ in ()).throw(AssertionError("text probe should not run")),
    )

    assert run_module._read_stdin_data() == (None, data)


def test_win32_text_stdin_from_enhanced_reader_normalizes_crlf(monkeypatch):
    """The enhanced-first win32 path keeps the text semantics of read_stdin()."""
    monkeypatch.setattr(run_module.sys, "platform", "win32")
    monkeypatch.setattr(run_module, "read_stdin_enhanced", lambda: StdinData(text_data="line1\r\nline2\r"))

    assert run_module._read_stdin_data() == ("line1\nline2", None)


def test_win32_empty_pipe_preserves_empty_string(monkeypatch):
    """Empty piped content is valid input, not equivalent to no stdin."""
    monkeypatch.setattr(run_module.sys, "platform", "win32")
    monkeypatch.setattr(run_module, "read_stdin_enhanced", lambda: None)
    monkeypatch.setattr(run_module, "read_stdin_content", lambda: "")

    assert run_module._read_stdin_data() == ("", None)
