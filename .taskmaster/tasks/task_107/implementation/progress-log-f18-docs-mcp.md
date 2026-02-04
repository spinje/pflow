# Fork: Task 107 — Phase 4.4 — Update CLAUDE.md files in src/pflow/mcp_server/ tree

## Entry 1: Review and fix all 4 CLAUDE.md files

Attempting: Read all 4 CLAUDE.md files in the mcp_server tree and correct JSON→markdown inaccuracies.

Result:
- ✅ `src/pflow/mcp_server/CLAUDE.md` — 3 fixes:
  1. `workflow_save` tool parameter list: removed `description` and `generate_metadata` params (line 92)
  2. Resolver summary: updated from `dict → library name → file path` to include markdown content detection (line 234)
  3. Workflow resolution order section: expanded from 4 steps to 5, now includes markdown content detection and `.pflow.md` file path detection (lines 383-387)
- ✅ `src/pflow/mcp_server/services/CLAUDE.md` — no inaccuracies found. Service patterns and code examples are format-agnostic, no references to `.json` workflow files.
- ✅ `src/pflow/mcp_server/tools/CLAUDE.md` — no inaccuracies found. Docstring guidance is format-agnostic.
- ✅ `src/pflow/mcp_server/utils/CLAUDE.md` — 2 fixes:
  1. Resolver input type examples: changed from 3 types to 4 (added markdown content), updated file path example from `.json` to `.pflow.md` (lines 16-30)
  2. Pitfall 1 code example: changed `json.loads(path.read_text())` to `parse_markdown(path.read_text())` (line 179)

Files modified:
- `src/pflow/mcp_server/CLAUDE.md`
- `src/pflow/mcp_server/utils/CLAUDE.md`

Status: Assignment complete. All 4 files checked, 5 inaccuracies fixed across 2 files, 2 files needed no changes.
