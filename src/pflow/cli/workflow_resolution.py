"""Workflow resolution — file path and saved name to IR."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from pflow.core.markdown_parser import MarkdownParseError

from pflow.core.workflow.manager import WorkflowManager


def _show_markdown_parse_error(path: Path, error: MarkdownParseError) -> None:
    """Show a helpful markdown parse error message.

    Args:
        path: Path to the workflow file.
        error: The parse error with line number and suggestion.
    """
    click.echo(f"❌ Invalid workflow syntax in {path}", err=True)
    click.echo(f"  {error}", err=True)


def _is_path_like(identifier: str) -> bool:
    """Heuristic to determine if identifier looks like a file path or workflow file."""
    lower = identifier.lower()
    return (
        (os.sep in identifier)
        or (os.altsep is not None and os.altsep in identifier)
        or lower.endswith(".pflow.md")
        or lower.endswith(".json")  # Recognized as path-like for rejection error
        or lower.endswith(".md")  # Recognized as path-like for extension hint
    )


def _try_load_workflow_from_file(path: Path) -> tuple[dict | None, str | None]:
    """Attempt to load a workflow from a file path, with error reporting.

    Returns a tuple of (workflow_ir, source). On handled errors, returns (None, "parse_error").
    """
    path_str = str(path).lower()

    # Reject .json files with a clear migration message (before existence check)
    if path_str.endswith(".json"):
        click.echo(
            f"❌ JSON workflow format is no longer supported: {path}\n"
            "Workflow files use .pflow.md format.\n"
            "Example: pflow ./my-workflow.pflow.md",
            err=True,
        )
        return None, "parse_error"

    # Reject .md files that aren't .pflow.md
    if path_str.endswith(".md") and not path_str.endswith(".pflow.md"):
        suggested = str(path).rsplit(".md", 1)[0] + ".pflow.md"
        click.echo(
            f"❌ Wrong file extension: {path}\nWorkflow files use .pflow.md extension.\nRename to: {suggested}",
            err=True,
        )
        return None, "parse_error"

    if not path.exists():
        return None, None

    try:
        from pflow.core.markdown_parser import MarkdownParseError, parse_markdown

        content = path.read_text(encoding="utf-8")
        result = parse_markdown(content)
        workflow_ir = result.ir

        # Auto-normalize: add missing boilerplate fields
        from pflow.core import normalize_ir

        normalize_ir(workflow_ir)

        return workflow_ir, "file"
    except MarkdownParseError as e:
        _show_markdown_parse_error(path, e)
        return None, "parse_error"
    except PermissionError:
        click.echo(f"cli: Permission denied reading file: '{path}'. Check file permissions.", err=True)
        return None, "parse_error"
    except UnicodeDecodeError:
        click.echo(f"cli: Unable to read file: '{path}'. File must be valid UTF-8 text.", err=True)
        return None, "parse_error"


def _try_load_workflow_from_registry(identifier: str, wm: WorkflowManager) -> tuple[dict | None, str | None]:
    """Attempt to load a workflow from registry by name, including stripping file extension."""
    from pflow.core import normalize_ir

    if wm.exists(identifier):
        ir = wm.load_ir(identifier)
        normalize_ir(ir)
        return ir, "saved"
    # Strip .pflow.md extension and try again
    if identifier.lower().endswith(".pflow.md"):
        name = identifier[:-9]  # len(".pflow.md") == 9
        if wm.exists(name):
            ir = wm.load_ir(name)
            normalize_ir(ir)
            return ir, "saved"
    return None, None


def resolve_workflow(identifier: str, wm: WorkflowManager | None = None) -> tuple[dict | None, str | None]:
    """Resolve workflow from file path or saved name.

    Resolution order:
    1. File paths (contains / or ends with .pflow.md/.json)
    2. Exact saved workflow name
    3. Saved workflow without .pflow.md extension

    Returns:
        (workflow_ir, source) where source is 'file', 'saved', 'parse_error', or None
    """
    if not wm:
        wm = WorkflowManager()

    # 1. File path detection (platform separators or workflow file extension)
    if _is_path_like(identifier):
        path = Path(identifier).expanduser().resolve()
        ir, source = _try_load_workflow_from_file(path)
        if ir is not None or source == "parse_error":
            return ir, source

    # 2/3. Saved workflow (exact name or extension-stripped)
    ir, source = _try_load_workflow_from_registry(identifier, wm)
    if ir is not None:
        return ir, source

    return None, None


def find_similar_workflows(name: str, wm: WorkflowManager, max_results: int = 3) -> list[str]:
    """Find similar workflow names using substring matching."""
    all_names = [w["name"] for w in wm.list_all()]
    # Simple substring matching (existing pattern)
    matches = [n for n in all_names if name.lower() in n.lower()]
    if not matches:
        # Try reverse
        matches = [n for n in all_names if n.lower() in name.lower()]
    return matches[:max_results]


def is_likely_workflow_name(text: str, remaining_args: tuple[str, ...]) -> bool:
    """Determine if text is likely a workflow name vs natural language.

    Uses heuristics to guess if the input is a workflow name that should
    be loaded directly, rather than treated as a free-form request.

    Args:
        text: The first argument from command line
        remaining_args: Any remaining arguments

    Returns:
        True if likely a workflow name, False otherwise
    """
    # Empty string is never a workflow name
    if not text:
        return False

    # Text with spaces is never a workflow name (even with params)
    # Workflow names are single words or kebab-case
    if " " in text:
        return False

    # Detect file paths (platform separators) and workflow file extensions
    lower = text.lower()
    if (
        os.sep in text
        or (os.altsep and os.altsep in text)
        or lower.endswith(".pflow.md")
        or lower.endswith(".json")
        or lower.endswith(".md")
    ):
        return True

    # If there are parameter-like arguments following (key=value), likely a workflow name
    # But check that it's not CLI syntax (=> or --)
    if remaining_args and any("=" in arg for arg in remaining_args) and "=>" not in remaining_args:
        return True

    # Single kebab-case word is likely a workflow name
    # But exclude if followed by CLI operators or flags
    if "-" in text and not text.startswith("--"):
        # Special case: --help is allowed with workflow names
        if remaining_args and len(remaining_args) > 0 and remaining_args[0] == "--help":
            return True
        # Check if followed by other CLI syntax
        return not (
            remaining_args and ("=>" in remaining_args or any(arg.startswith("--") for arg in remaining_args[:2]))
        )

    # Don't treat single words as workflow names unless they have params
    # This prevents false positives with CLI node names like "node1", "read-file", etc.
    return False
