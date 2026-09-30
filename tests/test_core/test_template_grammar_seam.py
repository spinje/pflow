"""Grammar uniqueness: ``pflow.core.templates`` is the only place a ``${…}`` grammar is written.

Two rules over every ``.py`` under ``src/pflow/``:

- **Rule A (literal):** no string constant (f-/rf-string fragments, module constants and
  ``BinOp`` operands included) contains ``\\$\\{`` or ``\\${`` outside the allowlist.
- **Rule B (by symbol):** no ``re.<fn>(...)`` call builds its pattern from a name imported from
  ``pflow.core.templates`` or from a ``TemplateResolver`` attribute. Calling ``.search`` /
  ``.finditer`` / ``.sub`` ON a public compiled pattern is not a ``re.*`` call and is allowed.

A failure is a missed site: migrate it to ``parse()`` / the facade, never allowlist it. Only a
genuinely different language belongs on the allowlist, with its reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Repo-relative path → why it may write a `${` pattern of its own.
ALLOWLIST: dict[str, str] = {
    "src/pflow/core/templates.py": "the seam: the one home of the template grammar",
    "src/pflow/mcp/auth_utils.py": "`${VAR:-default}` MCP-config env expansion is a different language",
    "src/pflow/core/yaml_utils.py": (
        "a lexical YAML mask (one nested `{}` level, deliberately no `$$` handling; over-capture is "
        "harmless because mask/restore is verbatim); the canonical pattern would break flow-style YAML "
        "for `$${y}` and `${a[${i}].x}` — own guard in test_yaml_shielding_hygiene.py and pin rows in "
        "test_yaml_utils.py::TestBraceAwareTemplates"
    ),
    "src/pflow/core/ir_schema.py": (
        "jsonschema `pattern` strings (`^\\$\\{.+\\}$`) are schema shape checks compiled by jsonschema, "
        "not pflow's grammar"
    ),
}

_TEMPLATES_MODULE = "pflow.core.templates"
_GRAMMAR_OPENERS = ("\\$\\{", "\\${")


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError(f"could not locate repo root (no pyproject.toml above {here})")


def scan(source: str, rel_path: str) -> list[str]:
    """Rule A and Rule B violations in one file's source, as ``path:line: rule: detail``."""
    # Text prefilter: Rule B violations contain no `$`, hence the two symbol spellings.
    if "$" not in source and "TemplateResolver" not in source and "templates" not in source:
        return []
    tree = ast.parse(source, filename=rel_path)
    found = [
        f"{rel_path}:{node.lineno}: A: {node.value[:60]!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and any(opener in node.value for opener in _GRAMMAR_OPENERS)
    ]
    found.extend(f"{rel_path}:{line}: B: {detail}" for line, detail in _by_symbol_patterns(tree))
    return found


def _bound_names(tree: ast.Module) -> tuple[set[str], set[str], set[str]]:
    """Local names bound to the ``re`` module, to ``re`` functions, and to the grammar."""
    re_modules, re_functions, grammar_names = {"re"}, set(), {"TemplateResolver"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "re":
                    re_modules.add(alias.asname or "re")
                elif alias.name == _TEMPLATES_MODULE and alias.asname:
                    grammar_names.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.module == "re":
                    re_functions.add(alias.asname or alias.name)
                elif node.module == _TEMPLATES_MODULE or (node.module == "pflow.core" and alias.name == "templates"):
                    grammar_names.add(alias.asname or alias.name)
    return re_modules, re_functions, grammar_names


def _by_symbol_patterns(tree: ast.Module) -> list[tuple[int, str]]:
    re_modules, re_functions, grammar_names = _bound_names(tree)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_re_call = (
            isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in re_modules
        ) or (isinstance(func, ast.Name) and func.id in re_functions)
        pattern = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "pattern"), None)
        if not is_re_call or pattern is None:
            continue
        used = sorted({n.id for n in ast.walk(pattern) if isinstance(n, ast.Name) and n.id in grammar_names})
        if _TEMPLATES_MODULE in ast.unparse(pattern):  # the unaliased `pflow.core.templates.X` chain
            used.append(_TEMPLATES_MODULE)
        if used:
            hits.append((node.lineno, f"re.* pattern built from {', '.join(used)}"))
    return hits


def test_no_template_grammar_outside_the_seam() -> None:
    root = _repo_root()
    violations = [
        hit
        for path in sorted((root / "src" / "pflow").rglob("*.py"))
        if (rel := path.relative_to(root).as_posix()) not in ALLOWLIST
        for hit in scan(path.read_text(encoding="utf-8"), rel)
    ]
    assert not violations, (
        "A `${…}` grammar is written outside pflow.core.templates. Use parse() / the TemplateResolver "
        "facade (or call .search/.finditer on its public patterns) instead:\n" + "\n".join(violations)
    )


@pytest.mark.parametrize("rel_path", sorted(ALLOWLIST))
def test_every_allowlisted_file_still_writes_a_grammar(rel_path: str) -> None:
    """A stale allowlist entry is noticed: each entry must still produce a Rule-A hit."""
    source = (_repo_root() / rel_path).read_text(encoding="utf-8")
    assert any(": A: " in hit for hit in scan(source, rel_path)), f"{rel_path} no longer needs its allowlist entry"


_PLANTED = {
    "raw": 'import re\nP = re.compile(r"\\$\\{(\\w+)\\}")\n',
    "escaped-literal": 'import re\nP = re.compile("\\\\${x}")\n',
    "rf-fragment": 'import re\nX = "a"\nP = re.compile(rf"(?<!\\$)\\$\\{{({X})\\}}")\n',
    "binop-operand": 'import re\nX = "a"\nP = re.compile(r"\\$\\{" + X)\n',
    "module-constant": '_OPEN = r"\\$\\{"\n',
    "resolver-attribute": (
        "import re\nfrom pflow.core.templates import TemplateResolver\n"
        'P = re.compile(f"{TemplateResolver.TEMPLATE_PATTERN.pattern}")\n'
    ),
    "module-alias": "import re\nfrom pflow.core import templates as t\nP = re.compile(t.X)\n",
    "import-as-alias": "import re\nimport pflow.core.templates as tpl\nP = re.fullmatch(tpl.X, 's')\n",
    "imported-name": "import re\nfrom pflow.core.templates import _PATH as P\nM = re.fullmatch(P, 's')\n",
    "re-function-import": "from re import compile as c\nfrom pflow.core.templates import _PATH\nP = c(_PATH)\n",
    "re-module-alias": "import re as regex\nfrom pflow.core.templates import _PATH\nP = regex.compile(pattern=_PATH)\n",
    "qualified-module": (
        "import re\nimport pflow.core.templates\n"
        "P = re.compile(pflow.core.templates.TemplateResolver.TEMPLATE_PATTERN.pattern)\n"
    ),
}


@pytest.mark.parametrize("spelling", sorted(_PLANTED))
def test_scan_flags_every_planted_spelling(spelling: str) -> None:
    assert scan(_PLANTED[spelling], f"planted/{spelling}.py"), f"the scan missed the {spelling!r} spelling"


def test_scan_allows_the_public_interface() -> None:
    """Using the compiled public patterns and unrelated regexes is not a second grammar."""
    source = (
        "import re\nfrom pflow.core.templates import TemplateResolver, parse\n"
        "m = TemplateResolver.TEMPLATE_PATTERN.search(s)\n"
        "n = [e.raw for e in parse(s).expressions]\n"
        'd = re.compile(r"\\d+\\.\\d+")\n'
        "k = re.sub(r'\\s+', ' ', TemplateResolver.resolve_template(s, {}))\n"
    )
    assert scan(source, "planted/clean.py") == []
