"""Meta-tests pinning repo-wide import rules that nothing else enforces.

1. No ``src.pflow`` imports anywhere. With ``pythonpath = ["."]`` in
   pyproject.toml, ``src.pflow.X`` and ``pflow.X`` are BOTH importable — as
   two distinct module objects. A test importing
   ``from src.pflow.nodes.file import ReadFileNode`` gets a different class
   object than production's ``pflow.nodes.file.ReadFileNode``:
   isinstance/issubclass checks fail across the boundary, module-level
   state doesn't cross, and the autouse ``mock_llm_client`` (which patches
   ``pflow.core.llm_client.complete``) is silently bypassed by the other
   module identity's import chain.

2. Module-level ``llm_client`` imports are allowlisted. The documented
   dependency map (``runtime/engine/CLAUDE.md`` → Cross-Module
   Dependencies) says only ``nodes/llm/llm.py`` and the discovery
   callsites import the adapter at module level; everything else —
   notably the engine — must import it lazily inside the function that
   needs it. The CLI-startup subprocess test
   (``test_cli/test_lazy_imports.py``) can't catch a violation here
   because ``llm_client`` lazy-imports litellm itself, so this rule would
   otherwise rot silently.

Same pattern as ``test_core/test_litellm_runtime.py::
test_no_direct_litellm_imports_in_production_code``: text prefilter, then
AST scan so comments/strings/docstrings (e.g. a path like ``src/pflow``)
never false-positive.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

_SCANNED_DIRS = ("src", "tests", "scripts")


def test_no_src_package_imports() -> None:
    """Every import of pflow code must use the ``pflow`` package name.

    Walks every ``.py`` file under src/, tests/, and scripts/ and fails on
    ``import src...`` / ``from src... import ...`` (top-level OR inside
    function bodies).
    """
    repo_root = _find_repo_root()

    violations: list[str] = []
    for dir_name in _SCANNED_DIRS:
        for py_file in sorted((repo_root / dir_name).rglob("*.py")):
            rel_path = py_file.relative_to(repo_root).as_posix()
            violations.extend(_scan_one_file(py_file, rel_path))

    if violations:
        violations_block = "\n".join(violations)
        pytest.fail(
            "Imports via the 'src.' module identity found. Use the 'pflow' "
            "package name instead (e.g. 'from pflow.nodes.file import ...'). "
            "Both identities are importable under pythonpath=['.'], but they "
            "produce DISTINCT module/class objects — breaking isinstance "
            "checks and bypassing the autouse LLM mock.\n\n"
            f"Offending sites:\n{violations_block}"
        )


def _scan_one_file(py_file: Path, rel_path: str) -> list[str]:
    """Return any src.*-import violations found in ``py_file``."""
    source = py_file.read_text(encoding="utf-8")
    # Cheap prefilter — both statement forms start with one of these.
    if "import src" not in source and "from src" not in source:
        return []
    try:
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError as exc:
        pytest.fail(f"{rel_path}: failed to parse — {exc}")

    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_src_module(alias.name):
                    found.append(f"  {rel_path}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and _is_src_module(node.module or ""):
            names = ", ".join(a.name for a in node.names)
            found.append(f"  {rel_path}:{node.lineno}: from {node.module} import {names}")
    return found


def _is_src_module(name: str) -> bool:
    return name == "src" or name.startswith("src.")


# ---------------------------------------------------------------------------
# llm_client module-level import allowlist
# ---------------------------------------------------------------------------

# The full set of modules allowed to import pflow.core.llm_client at module
# level. Everything else must lazy-import inside the function that needs it.
# Adding a module here means accepting that its entire import chain pays
# llm_client's import cost — fine for LLM-only paths, wrong for anything the
# CLI loads at startup.
_ALLOWED_MODULE_LEVEL_LLM_CLIENT_IMPORTERS: frozenset[str] = frozenset({
    "src/pflow/nodes/llm/llm.py",
    "src/pflow/core/workflow/discovery.py",
    "src/pflow/registry/discovery.py",
    "src/pflow/registry/smart_filter.py",
})


def test_module_level_llm_client_imports_are_allowlisted() -> None:
    """Outside the allowlist, ``llm_client`` may only be imported lazily.

    Walks every ``.py`` file under ``src/pflow/`` and flags imports of
    ``pflow.core.llm_client`` that execute at module-import time. Imports
    inside function bodies (lazy) and ``if TYPE_CHECKING:`` blocks (no
    runtime cost) are allowed everywhere.

    This enforces the engine layering rule in
    ``runtime/engine/CLAUDE.md`` → Cross-Module Dependencies. The rule's
    point: ``llm_client`` is light today only because litellm is lazy
    inside ``complete()``; a future heavy top-level dependency in the
    adapter must not silently drag every engine import (and CLI startup)
    with it.
    """
    repo_root = _find_repo_root()
    src_root = repo_root / "src" / "pflow"
    assert src_root.is_dir(), f"expected src/pflow/ at {src_root}"

    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        rel_path = py_file.relative_to(repo_root).as_posix()
        if rel_path in _ALLOWED_MODULE_LEVEL_LLM_CLIENT_IMPORTERS:
            continue
        source = py_file.read_text(encoding="utf-8")
        if "llm_client" not in source:
            continue
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError as exc:
            pytest.fail(f"{rel_path}: failed to parse — {exc}")
        for node in _import_time_imports(tree):
            if _references_llm_client(node):
                violations.append(f"  {rel_path}:{node.lineno}: {ast.unparse(node)}")

    if violations:
        violations_block = "\n".join(violations)
        pytest.fail(
            "Module-level llm_client imports found outside the allowlist. "
            "Move the import inside the function that needs it (lazy), like "
            "batch_executor.py's cache-warmup helper does — or, for a "
            "genuinely LLM-only module, add it to "
            "_ALLOWED_MODULE_LEVEL_LLM_CLIENT_IMPORTERS with a reason.\n\n"
            f"Offending sites:\n{violations_block}"
        )


def _import_time_imports(tree: ast.Module) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield imports that execute when the module is imported.

    Top-level if/try/class bodies run at import time, so imports there
    count. Imports inside function bodies (lazy) or ``if TYPE_CHECKING:``
    body blocks (never executed at runtime) are excluded — by line range,
    which is simpler and more complete than walking every statement
    container shape (try handlers, with blocks, match cases, ...).
    """
    excluded_ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or (
            isinstance(node, ast.If) and _is_type_checking_test(node.test)
        ):
            start = node.body[0].lineno
            end = node.body[-1].end_lineno or node.body[-1].lineno
            excluded_ranges.append((start, end))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not any(
            start <= node.lineno <= end for start, end in excluded_ranges
        ):
            yield node


def _is_type_checking_test(test: ast.expr) -> bool:
    # Compound tests (`if TYPE_CHECKING and x:`) are NOT recognized — they
    # fail toward a false POSITIVE with a clear message, the safe direction
    # for a guard test. If one ever appears legitimately, extend this.
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _references_llm_client(node: ast.Import | ast.ImportFrom) -> bool:
    """True if the import statement pulls in the ``llm_client`` module.

    Matches on the final dotted component, which catches absolute
    (``from pflow.core.llm_client import X``, ``import pflow.core.llm_client``),
    relative (``from .llm_client import X``), and attribute
    (``from pflow.core import llm_client``) forms. No other module named
    ``llm_client`` exists in the repo; if one ever does, the failure
    message makes the needed test adjustment obvious.
    """
    if isinstance(node, ast.Import):
        return any(_last_component(a.name) == "llm_client" for a in node.names)
    if _last_component(node.module or "") == "llm_client":
        return True
    return any(a.name == "llm_client" for a in node.names)


def _last_component(dotted: str) -> str:
    return dotted.rsplit(".", maxsplit=1)[-1]


def _find_repo_root() -> Path:
    """Walk up from this file until we find ``pyproject.toml`` — the repo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise AssertionError("pyproject.toml not found above test file")
