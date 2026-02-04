# Fork: Task 107 — Phase 2.4 + 2.5 — MCP Integration

## Entry 1: Update resolver.py for markdown format (Phase 2.4)

Attempting: Replace JSON loading with markdown parser, implement D12 content detection, preserve G2 3-tuple return.

Result:
- ✅ Removed `json` import, added `parse_markdown` and `MarkdownParseError` from `pflow.core.markdown_parser`
- ✅ Detection order per D12: dict → direct, string with `\n` → content (parse_markdown), `.pflow.md` suffix → file path, else → library name then file path
- ✅ New `_load_from_file()` helper extracts file reading + parse_markdown into reusable function
- ✅ Preserved 3-tuple return `(workflow_ir | None, error | None, source: str)` per G2
- ✅ Added `"content"` as new source value for raw markdown content
- ✅ All JSON references removed, error messages updated to reference markdown

Files modified: `src/pflow/mcp_server/utils/resolver.py`

## Entry 2: Update execution_tools.py (Phase 2.5 - tool layer)

Attempting: Remove `description` and `generate_metadata` parameters from `workflow_save` tool, update documentation.

Result:
- ✅ `workflow_save` tool: removed `description` parameter, removed `generate_metadata` parameter
- ✅ Tool type changed from `str | dict[str, Any]` to `str` (save only accepts markdown content or file path)
- ✅ Updated tool docstring and examples to reference `.pflow.md` format
- ✅ `_sync_save()` call updated: `ExecutionService.save_workflow(workflow, name, force)`
- ✅ `workflow_execute` docstring: updated examples from `.json` to `.pflow.md`, added raw markdown content as input type
- ✅ `workflow_validate` docstring: updated "JSON structure" to "required fields, correct structure", `.json` → `.pflow.md`

Files modified: `src/pflow/mcp_server/tools/execution_tools.py`

## Entry 3: Restructure execution_service.py save flow (Phase 2.5 - G8)

Attempting: Restructure the 6-function-deep save chain to preserve original markdown content. Remove `description` and `generate_metadata` params.

Result:
- ✅ `save_workflow()` signature changed from `(workflow, name, description, force, generate_metadata)` to `(workflow: str, name: str, force: bool = False)`
- ✅ New save-specific detection (NOT using resolve_workflow which discards content):
  - String with `\n` → raw markdown content
  - String ending `.pflow.md` or existing file → read file content
  - Other → error with clear message
- ✅ Parse once: `parse_markdown(markdown_content)` → use `result.ir` for validation/display, use `markdown_content` for save
- ✅ Validation via `load_and_validate_workflow(result.ir, auto_normalize=True)`
- ✅ `_save_and_format_result()` signature changed from `(name, workflow_ir, description, force, metadata_dict)` to `(name, markdown_content, workflow_ir, force)`
- ✅ `_save_and_format_result()` calls `save_workflow_with_options(name=name, markdown_content=markdown_content, force=force)` per F3's new signature
- ✅ Removed dead code: `_load_and_validate_workflow_for_save()` and `_generate_metadata_if_requested()` — no longer called after save flow restructure

Files modified: `src/pflow/mcp_server/services/execution_service.py`

## Final Status

All 3 assigned files modified:
- `src/pflow/mcp_server/utils/resolver.py` — markdown detection + parsing (D12), 3-tuple preserved (G2)
- `src/pflow/mcp_server/tools/execution_tools.py` — removed description/generate_metadata params, .pflow.md docs
- `src/pflow/mcp_server/services/execution_service.py` — save flow restructured (G8), preserves markdown content

All JSON references in these 3 files have been removed.
Save flow correctly: parses once → IR for display, content for save → save_workflow_with_options(name, markdown_content, force=force).

Fork F4 complete.
