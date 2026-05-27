# Cache Analysis Stages

Each file is one analytical concern with a single entry point, called from
`analyze()` or from `per_call_pipeline`. Per-file responsibility and the
"where do I add X?" routing live in the parent `../CLAUDE.md`; this file only
covers what spans the stages and is easy to get wrong.

## Import DAG -- the one rule that matters

Stages import downward only. `row_builder.py` is the leaf.

    per_call_pipeline    ─▶ row_builder, cross_workflow, warnings   (orchestrator)
    warnings             ─▶ row_builder, suggestions
    cross_workflow       ─▶ row_builder, suggestions
    partial_declarations ─▶ row_builder, suggestions
    fragmentation        ─▶ suggestions
    suggestions          ─▶ row_builder
    row_builder          ─▶ (nothing)   ← leaf; NEVER import a sibling here
    summary              ─▶ (nothing)

**Never make `row_builder` import a sibling stage.** Almost everything imports
its row/IR primitives, so a back-edge is an instant cycle. This is exactly why
the multi-stage row + warning + cross-workflow orchestrator lives in
`per_call_pipeline.py` (which may import all three) and not in `row_builder.py`.
If you find yourself wanting a sibling's logic from inside `row_builder`, move
the *caller* up to `per_call_pipeline` — don't pull the helper down.

## Why `_batch_aliases` / `_is_batch_scoped_ref` exist in two files

Both `row_builder.py` and `suggestions.py` define them, and both copies are live.
This is deliberate, not drift: `row_builder` (the leaf) needs them but cannot
import them from `suggestions` without creating the cycle above, so it keeps its
own copy. Do NOT consolidate them — same forced-duplication pattern as the copies
in `core/cache_overlap.py`.

## Where the shared IR helpers live

They sit with their primary consumer (one `_ir_helpers.py` was considered and
rejected — heterogeneous, low leverage):

- `row_builder.py`: `_node_inputs`, `_total_observed_invocations`, `_static_excerpt`
- `suggestions.py`: `_cache_items`, `_cache_item_names`

`stages/__init__.py` is intentionally docstring-only so importing one stage never
eagerly loads the others. `discrepancy/` is a sub-package with its own `CLAUDE.md`.
