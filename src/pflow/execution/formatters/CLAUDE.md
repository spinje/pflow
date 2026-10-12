# Formatters Module

Shared presentation for CLI and MCP. Return strings/dicts; never print or call
`click.echo` from a formatter.

## Find the owner

| Task or symptom | Owner |
|---|---|
| Wrong selected output/mode | `output_utils.py::select_output_mode` |
| Full-run fallback output vs `--only` output | `output_utils.py::find_auto_output`, `find_only_output` |
| How a run ended — the JSON document, CLI stderr summary, MCP text (every status) | `run_outcome.py` (`build_run_outcome` → `RunOutcome`; `render_cli_stderr`, `render_mcp_text`) |
| Probe failure text (CLI `probe` stderr, MCP `registry_run`) | `run_outcome.py::format_error_text` |
| Batch error input is too large/sensitive to display | `batch_errors.py` |
| Node text/JSON/template paths | `node_output_formatter.py` |
| Validation diagnostics | `validation_formatter.py` |
| Dry-run presentation | `plan_formatter.py` |
| Missing execution history | `history_formatter.py::format_execution_history` |
| Save/describe/list, registry/discovery, field retrieval | Corresponding `workflow_*`, `registry_*`, `discovery_formatter.py`, `field_output_formatter.py` |

## Consumer contracts

Honor declared return types and guard optional metadata: MCP may pass `None`
where CLI has a dictionary. A diagnostic in any JSON document is
`Diagnostic.to_output_dict()` (redacted; see its docstring), never the raw `to_dict()`/`to_display_dict()`.
Batch renderers use display-safe item summaries, never raw `errors[].item`.
A printer compacts a batch error with `compact_batch_error_detail` / `compact_batch_output_value`
(redacted); `archive_batch_output_value` keeps values raw and is the runtime's form only.

A run's ending has one builder: `build_run_outcome` turns the `ExecutionResult` into the
document CLI JSON emits; `render_cli_stderr` (CLI) and `render_mcp_text` (MCP) render it
from the same section functions. Add a field once, in the builder, and render it in a
section function both renderers compose — never assemble a run-ending dict elsewhere.
The document's optional keys are absent, never `null`; a producer's `null` (the cost
tri-state, a `?? null` output, the gate payload) stays.
The document cuts every long string in a diagnostic or a step to a head+tail excerpt
(`_printed`, #843; a gate's request, `context.gate`, is never cut); text sections preview from the whole
values — `RunOutcome.errors`/`.steps`, never the document's excerpted copies.

## Easy-to-confuse behavior

`node_output_formatter` has separate selectors: `format_type` chooses
text/JSON/structure; `output_mode` applies only to structure formatting and chooses
smart-filtered values, paths, or full values. `flatten_runtime_value` recursively
parses JSON-looking strings, which matters for MCP payloads returned as strings.
Error detection checks action names starting with `error` and error keys in
outputs/shared storage; direct-node paths may not preserve the returned action.

`history_formatter` expects flat execution metadata. A wrapper such as
`rich_metadata` silently produces no history; absent/zero execution count returns
`None`.

Use `select_output_mode` for output policy rather than copying its precedence.
Without an explicit output key, `--only` skips full-run declared outputs and uses
`find_only_output`; full-run auto-detection uses `find_auto_output`. Snapshot data
must not make restored nodes appear newly executed in summaries.

## CLI/MCP parity seams

The section functions in `run_outcome.py` (`completion_line`, `mode_lines`,
`errors_block`, `diagnostic_sections`, `gate_lines`, `answer_lines`,
`format_stderr_warnings`, `format_cost_summary_lines`, …) are the shared seam; the two
renderers differ only in tiering (the CLI's `-p`/JSON-mode table) and MCP's identity
lines and advisory filter. Shell stderr from a step that exited 0 still upgrades the
completion glyph and renders its block.

`run_outcome._append_outputs` and `cli/workflow_output.py::safe_output`
JSON-encode non-string values with the same options and use `repr(value)` on
serialization failure. The fallback value must agree; CLI can additionally emit
a side-channel warning that MCP text cannot.

Coverage: `tests/test_execution/formatters/test_run_outcome.py` (the builder, the
sections, both renderers on built outcomes), `tests/test_cli/test_run_outcome_cli.py`
(the CLI adapter on real runs), `tests/test_integration/test_cli_mcp_parity.py` (the
same run through both channels). Dry-run rendering coverage is in
`test_plan_formatter.py`.
