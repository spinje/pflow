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

3. ``runtime/`` never imports ``ui/`` (any scope). ``ui/`` depends ON
   ``runtime`` and pulls Starlette + the web server, so a ``runtime → ui``
   edge inverts the layering AND drags the web stack into every execution
   path (MCP, CLI, headless). The rule is absolute — ``_is_trace_locked``
   is DUPLICATED in ``runtime/resume_source.py`` rather than imported from
   ``ui.run_tailer`` for exactly this reason (Task 164/171). Nothing else
   catches a violation: it imports fine under the test env's full deps and
   breaks only a minimal install, which no other test simulates.

4. ``core/`` never imports the template-language shim ``pflow.runtime.template_resolver``
   (any scope). The language lives in ``pflow.core.templates``; a ``core → runtime``
   edge through the shim re-inverts the layering Task 170 fixed (the old module dragged
   ~29 runtime modules into every core importer). Vacuous once phase 5 deletes the
   shim; the durable guarantee is ``test_core/test_templates_module.py``'s subprocess pin.

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
# runtime/ must not import ui/ (layering)
# ---------------------------------------------------------------------------


def test_runtime_does_not_import_ui() -> None:
    """``src/pflow/runtime/`` must never import ``pflow.ui`` — at ANY scope.

    Walks every ``.py`` under ``src/pflow/runtime/`` and fails on any
    ``import pflow.ui[.…]`` / ``from pflow.ui[.…] import …`` — module-level,
    lazy inside a function, or under ``TYPE_CHECKING``. ``ui/`` depends on
    ``runtime`` and imports Starlette; the reverse edge inverts the layering
    and drags the web stack into MCP/CLI/headless execution. When ``runtime``
    needs a scrap of ``ui`` logic it is DUPLICATED (see
    ``resume_source._is_trace_locked`` ← ``ui.run_tailer.is_trace_locked``),
    never imported. Matches absolute ``pflow.ui`` imports — the repo's
    enforced style (rule 1 bans ``src.``; nothing uses cross-package relative
    imports).
    """
    repo_root = _find_repo_root()
    runtime_root = repo_root / "src" / "pflow" / "runtime"
    assert runtime_root.is_dir(), f"expected src/pflow/runtime/ at {runtime_root}"

    violations: list[str] = []
    for py_file in sorted(runtime_root.rglob("*.py")):
        rel_path = py_file.relative_to(repo_root).as_posix()
        source = py_file.read_text(encoding="utf-8")
        if "pflow.ui" not in source:  # prefilter; AST below is the authority
            continue
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError as exc:
            pytest.fail(f"{rel_path}: failed to parse — {exc}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.extend(
                    f"  {rel_path}:{node.lineno}: import {alias.name}"
                    for alias in node.names
                    if _is_ui_module(alias.name)
                )
            elif isinstance(node, ast.ImportFrom) and _is_ui_module(node.module or ""):
                names = ", ".join(a.name for a in node.names)
                violations.append(f"  {rel_path}:{node.lineno}: from {node.module} import {names}")

    if violations:
        violations_block = "\n".join(violations)
        pytest.fail(
            "runtime/ imports ui/ — a layering inversion. ui/ depends on "
            "runtime and pulls Starlette + the web server, so the reverse "
            "edge drags the web stack into MCP/CLI/headless execution — and "
            "no other test catches it (ui deps are installed in the test "
            "env). Duplicate the needed helper into runtime/ instead, as "
            "resume_source._is_trace_locked duplicates ui.run_tailer.\n\n"
            f"Offending sites:\n{violations_block}"
        )


def _is_ui_module(name: str) -> bool:
    return name == "pflow.ui" or name.startswith("pflow.ui.")


# ---------------------------------------------------------------------------
# core/ must not import the runtime template shim (layering)
# ---------------------------------------------------------------------------

_TEMPLATE_SHIM = "pflow.runtime.template_resolver"


def test_core_does_not_import_the_template_shim() -> None:
    """``src/pflow/core/`` imports the template language from ``pflow.core.templates`` —
    never through ``pflow.runtime.template_resolver``, at ANY scope (lazy imports too)."""
    repo_root = _find_repo_root()
    core_root = repo_root / "src" / "pflow" / "core"
    assert core_root.is_dir(), f"expected src/pflow/core/ at {core_root}"

    violations = [
        f"  {rel_path}:{lineno}: {statement}"
        for py_file in sorted(core_root.rglob("*.py"))
        if "template_resolver" in (source := py_file.read_text(encoding="utf-8"))  # prefilter; AST decides
        for rel_path in [py_file.relative_to(repo_root).as_posix()]
        for lineno, statement in _template_shim_imports(ast.parse(source, filename=str(py_file)))
    ]
    assert not violations, (
        "core/ imports the runtime template shim — import pflow.core.templates instead:\n" + "\n".join(violations)
    )


def _template_shim_imports(tree: ast.Module) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _TEMPLATE_SHIM or alias.name.startswith(f"{_TEMPLATE_SHIM}."):
                    yield node.lineno, f"import {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported = {f"{node.module}.{alias.name}" for alias in node.names} | {node.module}
            if _TEMPLATE_SHIM in imported:
                yield node.lineno, f"from {node.module} import {', '.join(a.name for a in node.names)}"


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
