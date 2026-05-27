# Cache Analysis Rendering

Read-only projections of `CacheAnalysis`. Nothing in this directory
performs analysis -- these modules format already-derived state for
downstream consumers (text terminal, JSON, dry-run nudge).

## Files

- `text.py` -- markdown-formatted text report. Single public entry point
  `render_text(analysis, *, all_rows=False, section="all")`. The
  `section` keyword exists so tests can assert on one section in
  isolation without crossing the public/private boundary; the set of
  named sections is intentionally narrow.
- `json.py` -- JSON projection. `render_json(analysis)`.
- `summarize.py` -- one-line dry-run nudge `Diagnostic`. Distinct from
  the `## Summary` markdown section emitted by `text._render_summary`
  (and surfaced via `render_text(..., section="summary")`).
- `cross_workflow_edits.py` -- paste-ready cache-block edit text for
  cross-workflow recommendations. Single entry point
  `format_grouped_body_block`.
- `views.py` -- blocking-error and recommended-action projections used
  by both `text.py` and `json.py`.
- `traces_list.py` -- `--list-traces` output.

## Test API -- substrate formatters

These underscore-prefixed symbols in `text.py` are stable direct-test surfaces:
pure functions over typed inputs (`CostDelta`, `PerCallRow`, ...) with no
observable shape through `render_text(analysis)` alone. Tests may import them
directly; a refactor may rename them but must update the tests in the same change.

- `_render_summary` -- the `## Summary` markdown section. New code/tests should
  use `render_text(analysis, section="summary")`; this helper is the implementation.
- `_format_delta_parenthetical` -- formats a `CostDelta` (tests pin exact strings).
- `_format_cost` -- the summary cost cell (singular vs plural unpriced-model grammar).
- `_cell_calls` -- per-row cell renderer for the per-call table.
- `_indent_message` -- pure indentation helper.
- `_BASELINE_LABELS` -- producer→label parity map; tests assert every
  `CostDelta.baseline` value has a label entry, so deleting one side without the
  other breaks rendering.

Other private symbols in `text.py` are implementation details -- cover them
through `render_text` or one of the surfaces above, not directly.
