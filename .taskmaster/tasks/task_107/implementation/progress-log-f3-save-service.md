# Fork: Task 107 — Phase 2.3 — Workflow Save Service Update

## Entry 1: Update workflow_save_service.py for markdown format

Attempting: Replace JSON loading with markdown parser, update save signature to accept markdown_content instead of workflow_ir + description, update error messages.

Result:
- ✅ Replaced `json` import with `parse_markdown` and `MarkdownParseError` from `pflow.core.markdown_parser`
- ✅ `_load_from_file()`: Replaced `json.load()` + `data.get("ir", data)` with `parse_markdown(content)` → `result.ir`. Error handling updated: `MarkdownParseError` replaces `json.JSONDecodeError`.
- ✅ `save_workflow_with_options()` signature changed from `(name, workflow_ir, description, *, force, metadata)` to `(name, markdown_content, *, force, metadata)`. Removed `description` parameter entirely — it's embedded in the markdown content. `description` was a positional arg, now it's gone and `force`/`metadata` remain keyword-only.
- ✅ `save_workflow_with_options()` now calls `manager.save(name, markdown_content, metadata)` matching the new WorkflowManager.save() signature from F2.
- ✅ Updated docstrings: `_load_from_file` references `.pflow.md`, `load_and_validate_workflow` references `.pflow.md` instead of JSON, `_load_from_dict` updated comment to "legacy compatibility"
- ✅ mypy: no errors on `workflow_save_service.py`
- ✅ ruff: all checks passed

Files modified: `src/pflow/core/workflow_save_service.py`

## Notes for main agent

Two callers need updating to match the new `save_workflow_with_options()` signature:

1. **`cli/commands/workflow.py:331`** — Currently calls with old keyword args `workflow_ir=markdown_content` and `description=""` with `type: ignore`. The F1 fork left a `TODO(Task 107 F3)` comment for this. Now that the signature is updated, the caller should change to:
   ```python
   saved_path = save_workflow_with_options(
       name=name,
       markdown_content=markdown_content,
       force=force,
       metadata=metadata,
   )
   ```
   And remove the TODO comment and `type: ignore`.

2. **`mcp_server/services/execution_service.py:487`** — Currently calls with `workflow_ir=workflow_ir, description=description`. F4 (MCP integration) should update this to pass `markdown_content` instead. This is part of the G8 save chain restructure assigned to F4.

## Final Status

All changes to `workflow_save_service.py` complete:
- `_load_from_file()` uses `parse_markdown()` instead of `json.load()`
- `save_workflow_with_options()` accepts `markdown_content: str` instead of `workflow_ir: dict + description: str`
- All JSON references removed, error messages updated
- mypy and ruff clean

Fork F3 complete.
