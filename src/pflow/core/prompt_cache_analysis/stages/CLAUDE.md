# Cache Analysis Stages

Task→stage routing lives in the parent `../CLAUDE.md`. This file covers
dependencies and helper placement across stages.

## Dependency boundary

`row_builder.py` is the leaf: keep it independent of sibling stages. Multi-stage
row/warning/cross-workflow orchestration belongs in `per_call_pipeline.py`.
If a row-builder caller needs another stage's result, move that orchestration up
rather than introducing a reverse import.

Keep sibling-stage dependencies one-way: `per_call_pipeline` →
`warnings`/`cross_workflow` → `suggestions` → `row_builder`.
`partial_declarations` uses `suggestions`/`row_builder`; `fragmentation` uses
`suggestions`; `summary` imports no sibling stages. Higher stages may also
import `row_builder` directly; avoid reverse edges when moving helpers.

`row_builder.py` and `suggestions.py` both define live `_batch_aliases` and
`_is_batch_scoped_ref` helpers. Do not resolve this duplication by importing
suggestions into row_builder: suggestions already imports row_builder, creating
a cycle. This constraint does not make every possible consolidation invalid.

## Helper ownership

Shared IR helpers stay with their primary consumers; a generic helper module was
rejected because these functions had mixed responsibilities.

- `row_builder.py`: `_node_inputs`, `_total_observed_invocations`, `_static_excerpt`.
- `suggestions.py`: `_cache_items`, `_cache_item_names`.

`stages/__init__.py` stays docstring-only so importing one stage does not eagerly
load the others. Prediction/diagnosis boundaries and test surfaces live in
`discrepancy/CLAUDE.md`.
