"""Guard: author-content YAML must go through safe_load_preserving_templates (issue #482).

PyYAML can't see pflow's ``${...}`` templates — it reads the ``{`` in an unquoted
template as a nested flow mapping — so any raw ``yaml.safe_load`` on author content
reopens issue #482 (unquoted templates in flow style fail to parse). This test fails
if a new raw ``yaml.safe_load`` / ``yaml.load`` call appears outside the legitimate
exemptions, mirroring tests/test_import_hygiene.py. It scans the AST (not text), so
docstrings and comments mentioning ``yaml.safe_load`` don't trip it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# yaml_utils.py IS the shielding implementation — raw safe_load is its job there.
_ALLOWED_FILES = frozenset({"src/pflow/core/yaml_utils.py"})
_RAW_LOADERS = frozenset({"safe_load", "load", "full_load"})
# Frontmatter parsing carries system metadata (timestamps/exec stats), never templates.
# Both frontmatter sites call yaml.safe_load(fm_text); allowlist by that argument so a
# new author-content call (any other argument) is still caught, even in the same file.
_ALLOWED_ARGS = frozenset({"fm_text"})


def _raw_yaml_load_calls(py_file: Path, rel: str) -> list[str]:
    """Return ``rel:lineno`` for each non-exempt ``yaml.<loader>(...)`` call in the file."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        func = getattr(node, "func", None)
        if (
            isinstance(node, ast.Call)
            and isinstance(func, ast.Attribute)
            and func.attr in _RAW_LOADERS
            and isinstance(func.value, ast.Name)
            and func.value.id == "yaml"
        ):
            first_arg = node.args[0] if node.args else None
            arg_name = first_arg.id if isinstance(first_arg, ast.Name) else None
            if arg_name not in _ALLOWED_ARGS:
                hits.append(f"{rel}:{node.lineno}")
    return hits


def test_author_content_yaml_uses_shielding_helper() -> None:
    src_root = Path(__file__).resolve().parents[2] / "src" / "pflow"
    repo_root = src_root.parents[1]
    assert src_root.is_dir(), f"expected src/pflow/ at {src_root}"

    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        rel = py_file.relative_to(repo_root).as_posix()
        if rel in _ALLOWED_FILES:
            continue
        violations.extend(_raw_yaml_load_calls(py_file, rel))

    if violations:
        pytest.fail(
            "Raw yaml.safe_load/yaml.load on (possibly) author content found. Author "
            "content can carry ${...} templates that PyYAML mis-parses (issue #482).\n"
            "Use pflow.core.yaml_utils.safe_load_preserving_templates instead — or, if "
            "this parses system metadata only (e.g. frontmatter), add its argument to "
            "_ALLOWED_ARGS with a reason.\n\n" + "\n".join(violations)
        )


def _aliased_or_from_yaml_imports(py_file: Path, rel: str) -> list[str]:
    """Return ``rel:lineno`` for yaml imports the call-based guard above can't see."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        # `from yaml import safe_load` / `load` / `full_load`
        from_yaml = (
            isinstance(node, ast.ImportFrom)
            and node.module == "yaml"
            and any(alias.name in _RAW_LOADERS for alias in node.names)
        )
        # `import yaml as y`
        aliased = isinstance(node, ast.Import) and any(
            alias.name == "yaml" and alias.asname is not None for alias in node.names
        )
        if from_yaml or aliased:
            hits.append(f"{rel}:{node.lineno}")
    return hits


def test_no_aliased_or_from_yaml_imports() -> None:
    """The call-based guard keys on ``yaml.<loader>(...)`` attribute calls.

    ``from yaml import safe_load`` or ``import yaml as y`` would bypass it — exactly
    the regression it exists to prevent — so forbid those import forms entirely.
    Author-content callers must use the shielding helper; the few frontmatter
    callers use plain ``import yaml``.
    """
    src_root = Path(__file__).resolve().parents[2] / "src" / "pflow"
    repo_root = src_root.parents[1]

    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        rel = py_file.relative_to(repo_root).as_posix()
        violations.extend(_aliased_or_from_yaml_imports(py_file, rel))

    if violations:
        pytest.fail(
            "Aliased or from-imports of yaml found. These bypass the call-based "
            "yaml-shielding guard (which keys on `yaml.<loader>(...)`). Use plain "
            "`import yaml` (frontmatter) or pflow.core.yaml_utils."
            "safe_load_preserving_templates.\n\n" + "\n".join(violations)
        )
