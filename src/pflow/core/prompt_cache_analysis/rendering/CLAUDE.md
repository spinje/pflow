# Cache Analysis Rendering

Read-only projections of `CacheAnalysis`.

## Task Navigation

| Task | Owner |
|---|---|
| Change report text or JSON | `text.py::render_text`, `json.py::render_json` |
| Change dry-run nudge | `summarize.py` — distinct from the report's Summary section |
| Change shared blocking/action projections | `views.py` |
| Change paste-ready cross-workflow edits | `cross_workflow_edits.py::format_grouped_body_block` |
| Change trace listings | `traces_list.py` |

## Test API

Prefer `render_text(analysis, section=...)` to test one report section; use
`section="summary"` for the Summary block, not `_render_summary`.

The following `text.py` internals are deliberately supported direct-test surfaces:
`_format_delta_parenthetical`, `_format_cost`, `_cell_calls`, and
`_indent_message`. These tests pin focused formatting behavior; renames must
update callers. `_BASELINE_LABELS` is also tested for parity with the cost-delta
producer vocabulary so new baselines do not silently lose their labels.

Other private formatter behavior should be covered through the public rendering
or section APIs.
