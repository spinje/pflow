"""Guide content helpers for the pflow CLI."""

from __future__ import annotations

from pathlib import Path


def render_entry_content() -> str:
    """Return the shared entry content for ``pflow --help`` and ``pflow guide``."""
    entry_path = Path(__file__).parent / "entry.md"
    try:
        if entry_path.exists():
            content = entry_path.read_text(encoding="utf-8")
            if content.strip():
                return content
    except (OSError, UnicodeDecodeError):
        pass
    return _placeholder_entry_content()


def _placeholder_entry_content() -> str:
    return """\
pflow runs workflows — sequences of nodes (http, shell, llm, code, file, mcp) that chain together through a shared data store.

Quick start:
  pflow <workflow-file>       Run a workflow file
  pflow <saved-name>          Run a saved workflow
  pflow list                  List saved workflows
  pflow find "description"    Search workflows by intent (LLM-powered)
  pflow guide                 Learn how to build workflows
  pflow mcp list              List available MCP tools

Use 'pflow <command> --help' for details on any command.
"""
