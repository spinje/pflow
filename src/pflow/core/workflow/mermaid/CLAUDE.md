# Mermaid Compatibility Package

This package is now a compatibility shim. Its only public symbol is
`generate_mermaid()`, preserved for existing callers such as
`pflow mermaid`, golden tests, and older imports.

## Public API

```python
from pflow.core.workflow.mermaid import generate_mermaid
```

`generate_mermaid(ir, resolve_child, base_path, source_file, max_depth,
direction, descriptions)` delegates to:

1. `pflow.core.workflow.graph.build_graph()` for the IR walk and structural
   model construction.
2. `pflow.core.workflow.graph.render_mermaid()` for Mermaid syntax emission.

## File Map

```
mermaid/
├── __init__.py    # Compatibility shim; exports only generate_mermaid
└── CLAUDE.md
```

The old private modules (`_context.py`, `_edges.py`, `_io.py`, `_render.py`,
`_scope.py`) were removed in Task 155 Phase 6. Do not reintroduce package-local
IR walking or Mermaid routing maps here.

## Where New Work Goes

- Structural facts, identity, edge inference, sub-workflow expansion, batch
  expansion, END edges, and derived helpers belong in `workflow/graph/`.
- Mermaid-specific syntax, labels, shapes, class definitions, flat IDs, and
  render-only truncation belong in `workflow/graph/renderers/mermaid.py`.
- Tests that assert graph structure belong in `tests/test_core/test_graph_build.py`.
- Tests that assert Mermaid syntax belong in `tests/test_core/test_mermaid.py`,
  `tests/test_core/test_graph_mermaid_renderer.py`, or golden tests.

## Invariants

- Keep this shim small. It should not read IR fields except to pass the IR into
  `build_graph()`.
- Keep `__all__ == ["generate_mermaid"]`. Private helper exports were removed
  deliberately so tests and callers use the graph/model interfaces.
- Preserve the public `generate_mermaid()` signature unless every external
  caller is migrated intentionally.
