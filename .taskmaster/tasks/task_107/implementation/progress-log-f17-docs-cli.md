# Fork: Task 107 — Phase 4.4 — Update CLAUDE.md in src/pflow/cli/

## Entry 1: Review and fix CLI CLAUDE.md inaccuracies

Attempting: Read src/pflow/cli/CLAUDE.md and correct all inaccuracies from JSON→markdown migration.

Result:
- ✅ Fixed 15 inaccuracies across the file:
  1. `--auto-repair` and `--no-update` flags marked as GATED
  2. Workflow resolution step 3 (natural language) marked as GATED
  3. `execute_json_workflow` renamed to `execute_workflow` (2 occurrences)
  4. Repair save handlers section marked as GATED, removed `.json` references
  5. File-based execution examples: `workflow.json` → `workflow.pflow.md`, removed `--auto-repair`
  6. Stdin routing example: JSON input format → markdown format
  7. Workflow save: removed `description` param, marked `--generate-metadata` as GATED
  8. Save function signature updated (removed `description`, `generate_metadata`)
  9. Metadata generation sections marked as GATED (2 occurrences)
  10. Workflow resolution priority: added `.pflow.md` and `.json` rejection
  11. Natural language flow diagram marked as GATED
  12. File/saved workflow flow diagram updated to show `parse_markdown()`
  13. Natural language execution examples replaced with GATED note
  14. Save service API: `save_workflow_with_options` signature updated
  15. Schema validation description: "JSON structure" → "IR structure"

- ❌ Did NOT change: line numbers (may have drifted but verifying would require reading production code), Task 71 enhancement descriptions (still accurate), MCP/registry/settings sections (unaffected by migration)

Files modified:
- `src/pflow/cli/CLAUDE.md`

Status: Assignment complete. All JSON→markdown inaccuracies in CLI CLAUDE.md corrected.
