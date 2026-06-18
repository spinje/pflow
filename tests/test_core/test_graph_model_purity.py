"""Meta-test: the graph model substrate carries no render syntax (Task 155 / 168).

``graph/CLAUDE.md`` states the invariant in prose: ``model.py`` and ``build.py``
are renderer-agnostic — they carry structure, never render syntax. Layout
(``elk`` / ``position``), Mermaid directives (``classDef`` / ``:::``), and React
Flow's ``parentNode`` field belong in the renderers and the frontend, not the
model. This test mechanizes that prose so a future edit that leaks a render token
fails loudly instead of silently coupling the model to one renderer.

It also pins renderer import-purity (H12 in the Task 168 plan): ``react_flow.py``
imports only the model and its ``scope`` helpers — never the sibling ``mermaid``
renderer. Renderers consume the GraphModel and its derived views; they must not
reach across to each other or grow shared render helpers.
"""

from __future__ import annotations

import ast
import inspect
import re

from pflow.core.workflow.graph import build, model
from pflow.core.workflow.graph.renderers import react_flow

# Render-syntax tokens that must never appear in the renderer-agnostic model.
# Each is (token, word_boundary): alphanumeric tokens match on word boundaries so
# ``position`` does not flag ``decomposition``; punctuation tokens (``:::``) have
# no word boundary and match as a substring. Matching is case-insensitive.
_RENDER_TOKENS: list[tuple[str, bool]] = [
    ("elk", True),  # ELK layout engine
    ("position", True),  # x/y coordinates — layout, not structure
    ("classDef", True),  # Mermaid class definition
    ("parentNode", True),  # React Flow parent-pointer field name
    (":::", False),  # Mermaid class-attach syntax
]

# The renderer-agnostic substrate ("no render syntax in the model").
_MODEL_MODULES = [model, build]

_GRAPH_PKG = "pflow.core.workflow.graph"
# react_flow.py may import only these from inside the graph package.
_ALLOWED_GRAPH_IMPORTS = {f"{_GRAPH_PKG}.model", f"{_GRAPH_PKG}.scope"}


def _token_lines(source: str, token: str, word_boundary: bool) -> list[int]:
    """1-based line numbers where ``token`` appears in ``source``."""
    pattern = re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE) if word_boundary else None
    return [
        lineno
        for lineno, line in enumerate(source.splitlines(), start=1)
        if (pattern.search(line) is not None if pattern else token in line)
    ]


def _graph_imports(tree: ast.AST) -> list[str]:
    """Module names imported from inside the graph package."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None and _is_graph_module(node.module):
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names if _is_graph_module(alias.name))
    return names


def _is_graph_module(name: str) -> bool:
    return name == _GRAPH_PKG or name.startswith(_GRAPH_PKG + ".")


def test_model_carries_no_render_syntax():
    """``model.py`` / ``build.py`` contain no Mermaid/React-Flow/ELK render tokens."""
    violations: list[str] = []
    for module in _MODEL_MODULES:
        source = inspect.getsource(module)
        for token, word_boundary in _RENDER_TOKENS:
            for lineno in _token_lines(source, token, word_boundary):
                violations.append(f"  {module.__name__}:{lineno} contains render token {token!r}")
    if violations:
        raise AssertionError(
            "Render syntax leaked into the renderer-agnostic graph model "
            "(see graph/CLAUDE.md 'no render syntax in the model'):\n\n"
            + "\n".join(violations)
            + "\n\nLayout/render tokens belong in a renderer or the frontend, not the model."
        )


def test_react_flow_renderer_imports_only_model_and_scope():
    """``react_flow.py`` imports only model + scope from the graph package, never mermaid."""
    imports = _graph_imports(ast.parse(inspect.getsource(react_flow)))

    assert imports, "expected react_flow.py to import from the graph package"
    assert all("mermaid" not in mod for mod in imports), (
        f"react_flow.py must not import the sibling mermaid renderer; got {imports}"
    )
    disallowed = sorted(set(imports) - _ALLOWED_GRAPH_IMPORTS)
    assert not disallowed, (
        f"react_flow.py may import only {sorted(_ALLOWED_GRAPH_IMPORTS)} from the graph "
        f"package, but also imports {disallowed} — renderers must not drift into shared helpers."
    )
