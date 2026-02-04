# Fork: Task 107 — Phase 4.4 — Update CLAUDE.md in execution/, runtime/, planning/

## Entry 1: Review and fix all 4 CLAUDE.md files

Attempting: Read all 4 CLAUDE.md files, identify inaccuracies from JSON→markdown migration, fix them.

### Files assessed

**`src/pflow/execution/CLAUDE.md`** — 3 fixes:
1. Line 250: Removed `execute_json_workflow()` function name reference (stale/misleading). Changed to generic "CLI calls `execute_workflow()`".
2. Lines 307-309: Removed `update_ir()` from WorkflowManager integration list (method is gated, only caller was repair). Updated `update_metadata()` description to mention YAML frontmatter. Updated `load_ir()` to mention `.pflow.md`.
3. Lines 424-430: Replaced "Repair Save Behavior" section (described `.repaired.json`, `.backup` files, `--no-update` flag) with gating notice. The entire repair system is gated per Task 107 Decision 26.

**`src/pflow/execution/formatters/CLAUDE.md`** — No changes needed. No references to JSON workflow format, no changed API signatures. All content is format-agnostic (describes formatter patterns, not workflow file handling).

**`src/pflow/runtime/CLAUDE.md`** — 4 fixes:
1. Executive summary: "JSON IR" → "workflow IR"
2. Compiler purpose: "JSON IR" → "workflow IR (dict)"
3. Compilation pipeline step 1: "Parse IR (JSON string or dict)" → "Parse IR (dict)" — the string path is unused in production.
4. Compilation context comment: "JSON IR to compile" → "Workflow IR dict to compile"
5. WorkflowExecutor: Added `.pflow.md` to describe file format for path-based loading.

**`src/pflow/planning/CLAUDE.md`** — 1 fix:
1. Added gating notice at top: "GATED (Task 107)" callout explaining the planner is gated pending markdown format migration, with note that all code is preserved but entry points are guarded.

Files modified:
- `src/pflow/execution/CLAUDE.md`
- `src/pflow/runtime/CLAUDE.md`
- `src/pflow/planning/CLAUDE.md`

Files unchanged (no inaccuracies found):
- `src/pflow/execution/formatters/CLAUDE.md`

Status: Assignment complete. All 4 files checked, 3 modified with targeted fixes, 1 left unchanged.
