"""Guard: every child process pflow spawns gets an explicit stdin (issue #657).

A child started without ``stdin=`` inherits pflow's own fd 0. Under
``pflow mcp serve`` that is the JSON-RPC input stream, so a child that reads
stdin eats protocol bytes and blocks the server; the shell node did exactly
that. Each spawn must pass ``input=`` or a ``stdin=`` that can never be
``None`` (the child's data pipe, or ``subprocess.DEVNULL``) — the shell node's
bug was ``stdin=PIPE if data is not None else None``, so a ``None`` result in
a conditional counts as inheriting. The test scans the AST, so
docstrings and comments naming ``subprocess.run`` don't trip it.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SPAWNERS = frozenset({"run", "Popen", "call", "check_call", "check_output"})


def _can_be_none(expr: ast.expr) -> bool:
    """Whether ``expr`` is ``None`` or a conditional with a ``None`` branch."""
    if isinstance(expr, ast.IfExp):
        return _can_be_none(expr.body) or _can_be_none(expr.orelse)
    return isinstance(expr, ast.Constant) and expr.value is None


def _sets_explicit_stdin(call: ast.Call) -> bool:
    """Whether ``call`` passes ``input=``, or a ``stdin=`` that is never ``None``."""
    for kw in call.keywords:
        if kw.arg == "input":
            return True
        if kw.arg == "stdin":
            return not _can_be_none(kw.value)
    return False


def _stdinless_spawns(tree: ast.AST, rel: str) -> list[str]:
    """Return ``rel:lineno`` for each ``subprocess.<spawner>(...)`` call that can inherit stdin."""
    hits: list[str] = []
    for node in ast.walk(tree):
        func = getattr(node, "func", None)
        if (
            isinstance(node, ast.Call)
            and isinstance(func, ast.Attribute)
            and func.attr in _SPAWNERS
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
            and not _sets_explicit_stdin(node)
        ):
            hits.append(f"{rel}:{node.lineno}")
    return hits


def _subprocess_bypass_imports(tree: ast.AST, rel: str) -> list[str]:
    """Return ``rel:lineno`` for imports the call-based guard above can't see."""
    hits: list[str] = []
    for node in ast.walk(tree):
        from_subprocess = isinstance(node, ast.ImportFrom) and node.module == "subprocess"
        aliased = isinstance(node, ast.Import) and any(
            alias.name == "subprocess" and alias.asname is not None for alias in node.names
        )
        if from_subprocess or aliased:
            hits.append(f"{rel}:{node.lineno}")
    return hits


def test_every_spawn_passes_explicit_stdin() -> None:
    src_root = Path(__file__).resolve().parents[1] / "src" / "pflow"
    repo_root = src_root.parents[1]
    assert src_root.is_dir(), f"expected src/pflow/ at {src_root}"

    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        rel = py_file.relative_to(repo_root).as_posix()
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        violations.extend(_stdinless_spawns(tree, rel))
        violations.extend(_subprocess_bypass_imports(tree, rel))

    assert not violations, (
        "Child processes must not inherit pflow's stdin (under `pflow mcp serve` it is the "
        "JSON-RPC stream). Pass `input=`, or a `stdin=` that is never None (the child's data "
        "pipe or subprocess.DEVNULL), "
        "and use plain `import subprocess` so this guard can see the call.\n\n" + "\n".join(violations)
    )
