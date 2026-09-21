# Formatters Module

Shared presentation for CLI and MCP. Return strings/dicts; never print or call
`click.echo` from a formatter.

## Find the owner

| Task or symptom | Owner |
|---|---|
| Wrong selected output/mode | `output_utils.py::select_output_mode` |
| Full-run fallback output vs `--only` output | `output_utils.py::find_auto_output`, `find_only_output` |
| Success summary, mode indicators, shell-stderr warnings | `success_formatter.py` |
| Failed execution and sanitized response fields | `error_formatter.py` |
| Batch error input is too large/sensitive to display | `batch_errors.py` |
| Node text/JSON/template paths | `node_output_formatter.py` |
| Validation diagnostics | `validation_formatter.py` |
| Dry-run presentation | `plan_formatter.py` |
| Missing execution history | `history_formatter.py::format_execution_history` |
| Save/describe/list, registry/discovery, field retrieval | Corresponding `workflow_*`, `registry_*`, `discovery_formatter.py`, `field_output_formatter.py` |

## Consumer contracts

Honor declared return types and guard optional metadata: MCP may pass `None`
where CLI has a dictionary. Keep external error sanitization enabled;
`error_formatter` sanitizes `raw_response` and `response_headers` by default.
Batch renderers use display-safe item summaries, never raw `errors[].item`.

When extending shared formatter inputs, update both consumers:
`cli/workflow_output.py` and `mcp_server/services/execution_service.py` (under
`src/pflow/`). A change at only one call site silently diverges CLI/MCP behavior.

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

Keep `success_formatter`'s `format_only_indicator`, `format_resume_indicator`, and
`format_stderr_warnings` shared across CLI and MCP text paths. Successful shell
stderr still affects the completion glyph and warning block.

`success_formatter._append_outputs` and `cli/workflow_output.py::safe_output`
JSON-encode non-string values with the same options and use `repr(value)` on
serialization failure. The fallback value must agree; CLI can additionally emit
a side-channel warning that MCP text cannot.

Parity coverage lives in `tests/test_execution/formatters/test_success_formatter.py`
(`TestAppendOutputsCliMcpParity`, `TestStderrWarningsCliMcpParity`). Dry-run rendering
coverage is in `test_plan_formatter.py` alongside it.
