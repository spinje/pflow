# Fork: Task 107 — Fix stale .json workflow references in MCP resources

## Entry 1: Fix server.py and instruction_resources.py

Attempting: Update all stale .json workflow references in MCP server instruction strings.

Result:
- ✅ `server.py:20`: Changed `.json workflow file` → `.pflow.md workflow file` in FastMCP instructions string
- ✅ `instruction_resources.py:201-204`: Updated 4 CLI examples in regular fallback (`workflow.json` → `workflow.pflow.md`, save command syntax updated)
- ✅ `instruction_resources.py:267-321`: Replaced entire JSON workflow example in sandbox fallback with equivalent `.pflow.md` markdown format example
- ✅ `instruction_resources.py:318,321`: CLI run examples updated to `.pflow.md`
- ✅ `instruction_resources.py:135,157,255`: Updated "workflow IR object" references to "workflow markdown content" (3 occurrences — resource description, docstring, fallback message)
- ✅ ruff: all checks passed on both files

Files modified:
- `src/pflow/mcp_server/server.py`
- `src/pflow/mcp_server/resources/instruction_resources.py`

Status: Complete. Both files fixed, ruff clean.
