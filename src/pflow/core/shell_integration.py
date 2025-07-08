"""Shell integration utilities for pflow.

This module provides core functions for detecting, reading, and categorizing
stdin input, enabling dual-mode stdin handling in pflow workflows.

The module supports:
- Detection of piped stdin vs interactive terminal
- Reading text data from stdin with UTF-8 encoding
- Determining if stdin contains workflow JSON or data
- Populating the shared store with stdin content
"""

import json
import sys


def detect_stdin() -> bool:
    """Check if stdin is piped (not a TTY).

    Returns:
        True if stdin is piped, False if interactive terminal
    """
    return not sys.stdin.isatty()


def read_stdin() -> str | None:
    """Read all stdin content if available.

    Returns:
        Content string if stdin has data, None if no stdin or empty

    Raises:
        UnicodeDecodeError: If stdin contains invalid UTF-8
    """
    if not detect_stdin():
        return None

    # Read all content at once (no streaming in this subtask)
    content = sys.stdin.read()

    # Treat empty stdin as no input per spec
    if content == "":
        return None

    # Strip trailing newline only (not all whitespace)
    # This preserves intentional whitespace in data
    if content.endswith("\n"):
        content = content[:-1]

    return content


def determine_stdin_mode(content: str) -> str:
    """Determine if stdin contains workflow JSON or data.

    Args:
        content: The stdin content to analyze

    Returns:
        'workflow' if content is valid JSON with 'ir_version' key, 'data' otherwise
    """
    try:
        # Try to parse as JSON
        parsed = json.loads(content)

        # Check if it's a dict with ir_version key
        if isinstance(parsed, dict) and "ir_version" in parsed:
            return "workflow"

    except (json.JSONDecodeError, TypeError):
        # Not valid JSON or not the right type
        pass

    # Default to data mode
    return "data"


def populate_shared_store(shared: dict, content: str) -> None:
    """Add stdin content to shared store.

    Args:
        shared: The shared store dictionary
        content: The stdin content to store

    Side Effects:
        Sets shared['stdin'] = content
    """
    shared["stdin"] = content
