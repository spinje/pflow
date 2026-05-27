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

These private (underscore-prefixed) symbols in `text.py` are documented
as stable test surfaces. They are pure functions over typed inputs
(`CostDelta`, `PerCallRow`, etc.) with no observable shape via the
public `render_text(analysis)` call alone. Tests may import them
directly; refactors are free to rename them but must update tests
in the same change.

- `_render_summary(analysis: CacheAnalysis) -> str` -- markdown summary
  section. Prefer `render_text(analysis, section="summary")` from new
  code; the underscored helper remains as the implementation. Five
  legacy test sites have migrated to the public form.
- `_format_delta_parenthetical(cost_delta: CostDelta, *, local_cache_reuse: bool = False) -> str`
  -- pure formatter for `CostDelta` objects. Five direct-test sites in
  `test_cache_analysis_renderers.py` pin exact strings.
- `_format_cost(value: float | None, *, partial: bool, unavailable_models: tuple[str, ...]) -> str`
  -- pure formatter for the summary cost cell. Two sites in
  `test_cache_analysis_analyze.py` assert grammar variants (singular vs
  plural unpriced models).
- `_cell_calls(row: PerCallRow, *, static_mode: bool = False) -> str`
  -- per-row cell renderer used by the per-call table. One direct-test
  site in `test_cache_analysis_renderers.py`.
- `_indent_message(message: str, *, prefix: str) -> list[str]` -- pure
  indentation helper. One direct-test site.
- `_BASELINE_LABELS: dict[str, str]` -- producer-to-label parity map.
  Tests assert that every value emitted by `CostDelta.baseline` has a
  label entry; deleting either side without the other breaks rendering.

Other private symbols in `text.py` are implementation details. Do not
test them directly; cover their behavior through `render_text` or one
of the documented surfaces above.
