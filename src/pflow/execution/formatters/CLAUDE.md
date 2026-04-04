# Formatters Module

Single-source-of-truth formatters ensuring CLI and MCP return identical output. **Golden Rule: return (str/dict), never print.**

## Formatter Index

| Formatter | Purpose | Returns |
|-----------|---------|---------|
| `success_formatter` | Successful execution + metrics | dict |
| `error_formatter` | Failed execution + sanitized errors | dict |
| `validation_formatter` | Validation success/failure | str |
| `node_output_formatter` | Node execution (text/json/structure) | str or dict |
| `workflow_save_formatter` | Save success + execution hints | str |
| `workflow_describe_formatter` | Workflow interface display | str |
| `workflow_list_formatter` | Saved workflow listings | str |
| `discovery_formatter` | LLM workflow discovery results | str |
| `registry_list_formatter` | All nodes grouped by package | str |
| `registry_search_formatter` | Node search results | str |
| `history_formatter` | Execution history (compact/detailed) | str or None |
| `field_output_formatter` | Field retrieval results (read-fields) | str or dict |
| `output_utils` | Unified output auto-detection (shared by CLI + JSON/MCP) | tuple |

## Rules (all enforced by tests)

1. **Return, never print** — no `click.echo()` or `print()`. Breaks MCP.
2. **Honor type contracts** — return type must match signature. MCP crashes on violations.
3. **Sanitize security data** — `error_formatter` sanitizes by default (`sanitize=True`). Never disable for external output.
4. **Handle None for optional params** — MCP passes `None` where CLI passes data. Always guard: `metadata.get("x") if metadata else default`.

## Non-Obvious Behaviors

**node_output_formatter** has two layers of mode selection:
- `format_type`: `text` (human), `json` (structured dict), `structure` (template paths like `${node.field}`)
- `output_mode` (structure format only): `smart` (values + LLM filtering via `smart_filter_fields_cached`), `structure` (paths only), `full` (all values, no truncation)
- MCPNode error detection: checks BOTH `action == "error"` AND `"error"` key in outputs/shared_store — because `MCPNode.post()` returns "default" action even on errors (workaround for missing error edges in workflows)
- JSON string auto-parsing: `flatten_runtime_value()` tries to parse strings as JSON via `core.json_utils.try_parse_json`. If a string looks like JSON, it's recursively flattened as structure. This is critical for MCP nodes that return JSON strings as output values.
- Deduplication: `get_value_hash()` detects when MCP nodes return identical data under different keys (e.g., both `result` and `server_TOOL_result`). Shows a warning and skips duplicates.

**error_formatter** uses lazy import of `mcp_server.utils.errors.sanitize_parameters` to avoid circular deps. Sanitizes `raw_response` and `response_headers` fields.

**history_formatter** expects FLAT metadata dicts with execution fields at top level (`execution_count`, `last_execution_timestamp`, etc.) — NOT wrapped in `rich_metadata`. Silently returns `None` if fields aren't found, which can be hard to debug.

**success_formatter** auto-detects output when no declared outputs via `find_auto_output()` in `output_utils.py` (shared with CLI text path). Priority: `result > response > output > text > data > stdout`. Root first, then namespaces (last occurrence wins — most downstream node). Skips `_`/`__` prefixed keys and invalid values (None, empty strings). Last-key fallback for non-standard keys. When `--only` is active: skips declared outputs (downstream nodes didn't execute), relies on auto-detection. JSON `execution` dict includes `cache_hits`, `only_node`, `nodes_skipped` fields when applicable. MCP text output filters `not_executed` steps and shows `⤷ Stopped after 'X' (--only)` summary.

## Dependencies

| Formatter | Depends On | Why |
|-----------|-----------|-----|
| `success_formatter`, `error_formatter` | `execution_state.build_execution_steps()` | Per-node step details |
| `success_formatter`, `error_formatter` | `MetricsCollector` | LLM usage/cost metrics |
| `node_output_formatter` | `Registry` | Metadata for template path extraction |
| `node_output_formatter` | `TemplateResolver`, `template_validation` | Path resolution and flattening |
| `node_output_formatter` | `smart_filter_fields_cached` (registry) | LLM-based field filtering in smart mode |
| `error_formatter` | `sanitize_parameters` (mcp_server.utils) | Security sanitization (lazy import) |

## Hard-Won: Update BOTH Call Sites

When adding parameters to a formatter, update BOTH consumers or CLI/MCP parity breaks:
1. CLI call site (`cli/main.py`)
2. MCP call site (`mcp_server/services/execution_service.py`)

**Task 85 bug**: Added `status`/`warnings` to `format_execution_success()`, forgot MCP call site. CLI showed warnings, MCP didn't.
