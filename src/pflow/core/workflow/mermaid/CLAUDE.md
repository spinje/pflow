# Mermaid Compatibility Package

`__init__.py::generate_mermaid()` is the compatibility entry point. Preserve its
public signature and sole export; keep this package a pass-through to graph
building and rendering, not another IR walker.

- Structural changes → `../graph/build.py` and `../graph/model.py`.
- Mermaid syntax, labels, and styling → `../graph/renderers/mermaid.py`.
- Graph contracts → `../graph/CLAUDE.md`.
- Structural tests → `tests/test_core/test_graph_build.py`.
- Syntax tests → `tests/test_core/test_mermaid.py`,
  `tests/test_core/test_graph_mermaid_renderer.py`, and Mermaid goldens.
