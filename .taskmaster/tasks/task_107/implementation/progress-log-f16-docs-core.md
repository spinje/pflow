# Fork: Task 107 — Phase 4.4 — Update src/pflow/core/CLAUDE.md

## Entry 1: Audit and fix inaccuracies

Attempting: Read core/CLAUDE.md and fix all inaccuracies from the JSON→markdown migration.

Result:
- ✅ Added `markdown_parser.py` to module structure listing
- ✅ Added full section (### 3) for `markdown_parser.py` — critical for agents working in core/
- ✅ Fixed WorkflowManager section: `save()` signature, storage format (JSON wrapper → YAML frontmatter + markdown), storage location (`*.json` → `*.pflow.md`), `update_ir()` marked as dead code
- ✅ Fixed `workflow_save_service.py` section: `save_workflow_with_options()` signature, `generate_workflow_metadata()` marked as gated
- ✅ Fixed `ir_schema.py` section: removed "JSON string input" from validate_ir description, removed JSON-path error reporting
- ✅ Fixed all example file references: 5 valid examples `.json` → `.pflow.md`, replaced 4 old invalid examples with 8 new markdown-specific ones
- ✅ Fixed WorkflowManager usage pattern: old `save(name, ir, description)` → new `save(name, markdown_content)`
- ✅ Fixed Design Decisions: "Dual-Mode Stdin" → "Stdin Routing", "Format Bridging" → "Markdown Storage"
- ✅ Fixed Key Lessons: "Format Bridging is Critical" → "Content Preservation is Critical"
- ✅ Fixed best practices: removed JSON-specific guidance
- ✅ Fixed exception example paths: `.json` → `.pflow.md`
- ✅ Added `test_markdown_parser.py` to testing section
- ✅ Added workflow parsing to module overview responsibilities

Files modified:
- `src/pflow/core/CLAUDE.md`
- `.taskmaster/tasks/task_107/implementation/progress-log-f16-docs-core.md` (this file)

Status: **Complete.** All inaccuracies fixed, `markdown_parser.py` entry added. No other files in scope.
