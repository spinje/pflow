# Fork: Task 107 — Phase 2.2 + 2.2b — WorkflowManager + rich_metadata flattening

## Entry 1: Rewrite WorkflowManager for .pflow.md storage

Attempting: Complete rewrite of WorkflowManager to use .pflow.md files with YAML frontmatter.

Result:
- ✅ Added `_name_from_path()` static method handling .pflow.md double extension (G1)
- ✅ `save()` signature changed to `(name, markdown_content, metadata=None)` per D4 — receives markdown content, prepends frontmatter, writes .pflow.md
- ✅ `_build_frontmatter()` generates created_at, updated_at, version, plus any flat metadata fields
- ✅ `_serialize_with_frontmatter()` serializes frontmatter via yaml.dump + body
- ✅ `_split_frontmatter_and_body()` splits file content into (frontmatter_dict, markdown_body) for update_metadata
- ✅ `load()` returns flat structure (D8) — all metadata fields at top level, no rich_metadata wrapper
- ✅ `load_ir()` parses .pflow.md, returns result.ir
- ✅ `list_all()` globs *.pflow.md, uses _name_from_path()
- ✅ `update_metadata()` redesigned — reads file, splits frontmatter/body, updates frontmatter, reassembles, atomic write. Body NEVER modified.
- ✅ `exists()`, `delete()`, `get_path()` all use .pflow.md extension
- ✅ Removed `_create_metadata_wrapper()` — replaced by `_build_frontmatter()`
- ✅ `update_ir()` preserved but deprecated — logs warning, only caller was gated repair system
- ✅ Removed `json` import, added `yaml` and `parse_markdown` imports
- ✅ All 8 `.json` references changed to `.pflow.md`

Files modified: `src/pflow/core/workflow_manager.py`
Status: Phase 2.2 complete.

## Entry 2: Update rich_metadata callers (G9)

Attempting: Change all callers from metadata.get('rich_metadata', {}) to direct field access.

Result:
- ✅ `workflow_describe_formatter.py:56`: Removed `rich_metadata` lookup, passes flat metadata to `_format_execution_history_section()`
- ✅ `_format_execution_history_section()`: Renamed param from `rich_metadata` to `metadata`, updated docstring
- ✅ `discovery_formatter.py:102`: Changed from `"rich_metadata" in workflow` check to `workflow.get("execution_count", 0) > 0`, passes `workflow` directly to `format_execution_history()`
- ✅ `history_formatter.py:22`: Renamed parameter from `rich_metadata` to `metadata`, updated docstring. Function body already reads the right keys (`execution_count`, etc.) — no body changes needed.
- ✅ `context_builder.py:456`: `_extract_workflow_description()` simplified — no more rich_metadata fallback, reads description directly
- ✅ `context_builder.py:470`: `_format_workflow_keywords()` reads `workflow.get("search_keywords")` directly
- ✅ `context_builder.py:483`: `_format_workflow_capabilities()` reads `workflow.get("capabilities")` directly
- ✅ `context_builder.py:785`: Compact workflow listing reads `workflow.get("capabilities", [])` and `workflow.get("typical_use_cases", [])` directly
- ✅ `cli/main.py:1204` and `cli/main.py:1273`: Renamed `rich_metadata` to `flat_metadata`, removed `description` from save() call. Added `type: ignore[arg-type]` since these gated planner code paths pass IR dicts, not markdown content.
- ✅ `test_history_formatter.py:268,290`: Updated test data to use flat metadata (execution fields at top level, no rich_metadata wrapper)

Files modified:
- `src/pflow/execution/formatters/workflow_describe_formatter.py`
- `src/pflow/execution/formatters/discovery_formatter.py`
- `src/pflow/execution/formatters/history_formatter.py`
- `src/pflow/planning/context_builder.py`
- `src/pflow/cli/main.py` (only rich_metadata construction, not file loading)
- `tests/test_execution/formatters/test_history_formatter.py`

Status: Phase 2.2b complete.

## Note for main agent

`tests/test_execution/test_executor_service.py` has 13 references to `rich_metadata` that read from saved JSON workflow files on disk. These tests construct workflows via the old JSON-based WorkflowManager, save them, then read the raw JSON and check `saved_data["rich_metadata"]["last_execution_params"]`. These will fail because:
1. WorkflowManager now saves .pflow.md not .json
2. Metadata structure is flat (no rich_metadata wrapper)
3. Tests read files with json.load() instead of parsing markdown

This file is NOT in my assignment — it should be updated in Phase 3 (test migration, likely fork F12 or F13).

## Final Status

All assigned files modified:
- `src/pflow/core/workflow_manager.py` — complete rewrite for .pflow.md + frontmatter
- `src/pflow/execution/formatters/workflow_describe_formatter.py` — flat metadata access
- `src/pflow/execution/formatters/discovery_formatter.py` — flat metadata access
- `src/pflow/execution/formatters/history_formatter.py` — renamed parameter, flat metadata
- `src/pflow/planning/context_builder.py` — flat metadata access (4 locations)
- `src/pflow/cli/main.py` — flat metadata construction (2 locations, gated code paths)
- `tests/test_execution/formatters/test_history_formatter.py` — updated test data to flat structure

All 8 `.json` references in WorkflowManager are now `.pflow.md`.
All rich_metadata callers use flat access.
update_metadata() correctly splits/merges frontmatter without touching body.

Fork F2 complete.
