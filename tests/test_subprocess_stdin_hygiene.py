"""Ratchet: child processes pflow spawns state their stdin (issue #657).

A child started without ``stdin=`` inherits pflow's own fd 0: at a terminal it
reads the keyboard, with ``pflow wf < file`` it reads the file. pflow's own
spawns give the child its data or EOF instead. (Under ``pflow mcp serve`` fd 0
is already the null device — ``core/stdio_reservation.py:reserve_stdin`` — so
the JSON-RPC stream is safe whatever a child does.)

Catches, in ``src/pflow/**.py``: a ``subprocess.run/Popen/call/check_call/
check_output`` call with no ``stdin=``/``input=``, or whose value is the literal
``None`` or a conditional with a ``None`` branch (the shell node's original
``stdin=PIPE if data is not None else None``); and ``from subprocess import`` /
``import subprocess as``, which would hide calls from the scan.

Does not catch — this is a ratchet, not a proof: a variable that may hold
``None`` (``input=data``), an explicit inherit (``stdin=sys.stdin``,
``stdin=0``), ``**kwargs``, a module alias by assignment, or any other spawn API
(``asyncio.create_subprocess_*``, ``os.system``/``os.popen``/``os.spawn*``,
``anyio``). The scan reads the AST, so docstrings and comments don't trip it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SPAWNERS = frozenset({"run", "Popen", "call", "check_call", "check_output"})


def _can_be_none(expr: ast.expr) -> bool:
    """Whether ``expr`` is ``None`` or a conditional with a ``None`` branch."""
    if isinstance(expr, ast.IfExp):
        return _can_be_none(expr.body) or _can_be_none(expr.orelse)
    return isinstance(expr, ast.Constant) and expr.value is None


def _sets_explicit_stdin(call: ast.Call) -> bool:
    """Whether ``call`` passes a ``stdin=`` or ``input=`` that is never ``None``.

    ``subprocess.run(input=None)`` leaves stdin unset, so ``input`` gets the same check.
    """
    return any(kw.arg in {"stdin", "input"} and not _can_be_none(kw.value) for kw in call.keywords)


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
        "Child processes pflow spawns must not inherit its stdin (the terminal, a redirected "
        "file). Pass a `stdin=` or `input=` that is never None (the child's data pipe/bytes "
        "or subprocess.DEVNULL), and use plain `import subprocess` so this guard can see "
        "the call.\n\n" + "\n".join(violations)
    )


@pytest.mark.parametrize(
    ("call", "inherits"),
    [
        ("subprocess.run(argv)", True),
        ("subprocess.Popen(argv, stdin=None)", True),
        ("subprocess.Popen(argv, stdin=subprocess.PIPE if data is not None else None)", True),
        ("subprocess.run(argv, input=data if data else None)", True),
        ("subprocess.Popen(argv, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL)", False),
        ("subprocess.run(argv, stdin=subprocess.DEVNULL)", False),
        ("subprocess.run(argv, input=b'')", False),
    ],
)
def test_guard_flags_spawns_that_can_inherit_stdin(call: str, inherits: bool) -> None:
    assert bool(_stdinless_spawns(ast.parse(call), "x.py")) is inherits
