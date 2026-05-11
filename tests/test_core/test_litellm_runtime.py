"""Tests for ``pflow.core.litellm_runtime`` — the single LiteLLM import seam.

Covers:
- ``configure_litellm_defaults`` sets ``LITELLM_LOCAL_MODEL_COST_MAP=True``
  when unset.
- ``configure_litellm_defaults`` respects a user-provided value (no overwrite).
- ``import_litellm`` and ``import_litellm_exceptions`` set the env var before
  returning the module.
- Importing the helper module itself does not pull ``litellm`` into
  ``sys.modules`` (lazy-import contract).
- **Meta-test**: no production module under ``src/pflow/`` directly imports
  ``litellm`` or ``litellm.*`` — every site must route through this seam.

The CLI-level lazy-import contract (``pflow.cli.main`` import doesn't load
litellm) is covered separately in ``tests/test_cli/test_lazy_imports.py``.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

ENV_VAR = "LITELLM_LOCAL_MODEL_COST_MAP"


def test_configure_sets_env_var_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)

    from pflow.core.litellm_runtime import configure_litellm_defaults

    configure_litellm_defaults()

    assert os.environ.get(ENV_VAR) == "True"


def test_configure_respects_user_provided_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # User opts back into remote pricing — pflow must not override.
    monkeypatch.setenv(ENV_VAR, "False")

    from pflow.core.litellm_runtime import configure_litellm_defaults

    configure_litellm_defaults()

    assert os.environ.get(ENV_VAR) == "False"


def test_configure_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)

    from pflow.core.litellm_runtime import configure_litellm_defaults

    configure_litellm_defaults()
    configure_litellm_defaults()
    configure_litellm_defaults()

    assert os.environ.get(ENV_VAR) == "True"


def test_import_litellm_sets_env_var_and_returns_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)

    from pflow.core.litellm_runtime import import_litellm

    litellm = import_litellm()

    assert os.environ.get(ENV_VAR) == "True"
    # Returned module is the real litellm package
    assert litellm.__name__ == "litellm"
    # Sanity: model_cost was populated at import time
    assert isinstance(getattr(litellm, "model_cost", None), dict)


def test_import_litellm_exceptions_returns_exceptions_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)

    from pflow.core.litellm_runtime import import_litellm_exceptions

    exc_mod = import_litellm_exceptions()

    assert os.environ.get(ENV_VAR) == "True"
    assert exc_mod.__name__ == "litellm.exceptions"
    # Sanity: a known exception class exists
    assert hasattr(exc_mod, "AuthenticationError")


@pytest.mark.e2e
def test_importing_helper_module_does_not_import_litellm(
    uv_exe: str,
    prepared_subprocess_env: dict[str, str],
) -> None:
    """The helper itself must stay lightweight — only ``importlib.import_module``
    inside helper functions touches litellm, never module-scope import.

    Subprocess test to guarantee a clean ``sys.modules`` baseline regardless
    of what the parent test process has already imported. Uses the same
    ``uv run python -c ...`` pattern as ``tests/test_cli/test_lazy_imports.py``
    so both lazy-import contracts (helper-level here, CLI-level there) run
    under identical isolation.
    """
    code = (
        "import sys\n"
        "import pflow.core.litellm_runtime  # noqa: F401\n"
        "leaked = [k for k in sys.modules if k == 'litellm' or k.startswith('litellm.')]\n"
        "assert not leaked, f'litellm leaked into sys.modules via helper import: {leaked}'\n"
    )
    result = subprocess.run(  # noqa: S603 — fixture-controlled args, mirrors test_lazy_imports.py
        [uv_exe, "run", "python", "-c", code],
        env=prepared_subprocess_env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"


# ---------------------------------------------------------------------------
# Meta-test: enforce the single-seam contract via AST scan.
# ---------------------------------------------------------------------------

# Modules under src/pflow/ allowed to mention ``litellm`` in their imports.
# This is the seam itself — and even there the import is via
# ``importlib.import_module(...)``, which is a function call (not an Import
# node) so the AST scan ignores it. Keeping the path in the allowlist makes
# the intent explicit and survives a future refactor that adds a direct
# import inside the helper.
_ALLOWED_DIRECT_LITELLM_IMPORTERS: frozenset[str] = frozenset({
    "src/pflow/core/litellm_runtime.py",
})


def test_no_direct_litellm_imports_in_production_code() -> None:
    """All production litellm imports must route through ``litellm_runtime``.

    Walks every ``.py`` file under ``src/pflow/`` and AST-parses it to find
    ``import litellm`` / ``import litellm.X`` / ``from litellm import ...`` /
    ``from litellm.X import ...`` statements (top-level OR inside function
    bodies). Any hit outside the allowlist fails the test with a fix hint.

    This blocks regressions of the issue-#384 fix: a future change that adds
    a bare ``import litellm`` somewhere bypasses ``configure_litellm_defaults``
    and re-introduces the network-fetch determinism bug.

    Caught: ``import litellm``, ``import litellm.exceptions``,
            ``from litellm import X``, ``from litellm.X import Y``.
    Allowed: ``importlib.import_module("litellm")`` (function call, not Import
            node — the helper's escape hatch).
    """
    repo_root = _find_repo_root()
    src_root = repo_root / "src" / "pflow"
    assert src_root.is_dir(), f"expected src/pflow/ at {src_root}"

    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        rel_path = py_file.relative_to(repo_root).as_posix()
        if rel_path in _ALLOWED_DIRECT_LITELLM_IMPORTERS:
            continue
        violations.extend(_scan_one_file(py_file, rel_path))

    if violations:
        violations_block = "\n".join(violations)
        pytest.fail(
            "Direct litellm imports found in production code. Route them through "
            "pflow.core.litellm_runtime instead:\n\n"
            "  from pflow.core.litellm_runtime import import_litellm  # or import_litellm_exceptions\n"
            "  litellm = import_litellm()\n\n"
            "This applies the LITELLM_LOCAL_MODEL_COST_MAP=True default so the "
            "model-pricing map loads deterministically offline (see GH #384).\n\n"
            f"Offending sites:\n{violations_block}"
        )


def _scan_one_file(py_file: Path, rel_path: str) -> list[str]:
    """Return any direct-litellm-import violations found in ``py_file``."""
    source = py_file.read_text(encoding="utf-8")
    # Text prefilter: AST parsing is ~1ms per file but most pflow files
    # never mention litellm. The substring check is ~1µs per file and
    # cuts the scan from ~250ms to ~50ms. Conservative — matches any
    # mention (comments/strings/identifiers), then the AST scan filters
    # those out by structure.
    if "litellm" not in source:
        return []
    try:
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError as exc:
        pytest.fail(f"{rel_path}: failed to parse — {exc}")

    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_litellm_module(alias.name):
                    found.append(f"  {rel_path}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and _is_litellm_module(node.module or ""):
            names = ", ".join(a.name for a in node.names)
            found.append(f"  {rel_path}:{node.lineno}: from {node.module} import {names}")
    return found


def _is_litellm_module(name: str) -> bool:
    return name == "litellm" or name.startswith("litellm.")


def _find_repo_root() -> Path:
    """Walk up from this file until we find ``pyproject.toml`` — the repo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError(f"could not locate repo root (no pyproject.toml above {here})")
