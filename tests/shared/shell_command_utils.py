"""Portable command helpers for shell-node tests."""

import shlex
import sys


def python_command(script: str) -> str:
    """Run *script* with the interpreter executing pytest.

    On Windows the shell node uses Git Bash, which needs the native executable
    path translated before it can be invoked reliably. This avoids depending
    on an activated virtualenv or on ``python``/``python3`` PATH aliases.
    """
    executable = shlex.quote(sys.executable)
    if sys.platform == "win32":
        executable = f'"$(cygpath -u {executable})"'

    return f"{executable} -c {shlex.quote(script)}"


def python_json_command(expression: str) -> str:
    """Evaluate *expression* with JSON stdin available as ``data``.

    Shell tests run under a POSIX-compatible shell on every platform. The
    expression is shell-quoted as part of the complete Python snippet.
    """
    script = f"import json,sys; data=json.load(sys.stdin); print({expression})"
    return python_command(script)
