# Fork: Task 107 — Phase 4.4 — Update CLAUDE.md files (root + architecture/)

## Entry 1: Review and fix inaccuracies

Attempting: Read both CLAUDE.md files and correct JSON→markdown migration inaccuracies.

### Root CLAUDE.md — 6 fixes

1. **Line 55**: "AI agents create JSON workflow files" → "AI agents create markdown workflow files (`.pflow.md`)"
2. **Line 142**: Added `markdown_parser.py` to `core/` file listing (critical — new file agents need to know about)
3. **Line 199**: Added `markdown_utils.py` to `tests/shared/` file listing
4. **Lines 325-327**: Planner section updated from "legacy" to "gated — Task 107" with note about pending prompt rewrite
5. **Lines 341-356**: Added Task 107 to "Recently Completed", removed from v0.9.0 planned
6. **Line 514**: `uv run pflow workflow.json` → `uv run pflow workflow.pflow.md`

### architecture/CLAUDE.md — 3 fixes

1. **Line 139**: `pflow-pocketflow-integration-guide.md` description: "JSON via CLI" → "`.pflow.md` files via CLI"
2. **Lines 221-238**: `guides/json-workflows.md` entry: marked as ⚠️ Historical (superseded by `.pflow.md` format), removed detailed content descriptions since the guide is no longer current
3. **Line 96**: overview.md key contents: "JSON workflows" → "markdown workflows"

### Not changed (no inaccuracies found)

- `reference/ir-schema.md` entry: describes the IR schema (format-agnostic), not workflow file format — still accurate
- All vision/historical document entries — these are already marked as outdated/historical
- Navigation paths and reading paths — still accurate (they reference architecture concepts, not file formats)
- Implementation references table — still accurate (points to CLAUDE.md files, not format-specific)

Files modified:
- `/Users/andfal/projects/pflow-feat-markdown-workflow-format/CLAUDE.md`
- `/Users/andfal/projects/pflow-feat-markdown-workflow-format/architecture/CLAUDE.md`

Status: Complete. Both files checked, 9 inaccuracies fixed, progress log written.
