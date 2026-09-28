"""CLI workflow routing heuristic.

Determines whether a CLI argument is likely a workflow name (to be resolved
and executed) vs natural language or a subcommand.

Note: Actual workflow resolution (file, library, markdown, dict → IR) lives
in execution/workflow_resolver.py. This module is CLI-only routing logic.
"""

from __future__ import annotations

import os
import re

# A CLI parameter token: a non-empty key, then "=" (see param_parsing.parse_workflow_params).
# Keys stay permissive (hyphens, dots, leading digits, and "--key=value" typos that the
# undeclared-input validator reports), so only an empty key is rejected here.
_PARAM_ARG = re.compile(r"[^=\s]+=")


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

    # Arbitrary text with spaces is never a workflow name (even with params).
    # Path-like arguments were handled above because valid file paths may contain spaces.
    if " " in text:
        return False

    # key=value arguments following the name mark it as a workflow invocation
    if any(_PARAM_ARG.match(arg) for arg in remaining_args):
        return True

    # Single kebab-case word is likely a workflow name, unless followed by flags
    if "-" in text and not text.startswith("--"):
        # Special case: --help is allowed with workflow names
        if remaining_args[:1] == ("--help",):
            return True
        return not any(arg.startswith("--") for arg in remaining_args[:2])

    # Don't treat single words as workflow names unless they have params
    # This prevents false positives with CLI node names like "node1", "read-file", etc.
    return False
