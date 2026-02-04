# Fork: Task 107 — Architecture Docs — Fork D: architecture.md + mcp-guide.md

## Entry 1: Read and plan changes

Attempting: Read both files to identify all stale references.

Result:
- ✅ Read architecture.md (518 lines) and mcp-guide.md (371 lines)
- Identified 7 changes needed in architecture.md, 2 in mcp-guide.md

Status: Planning complete, starting edits.

## Entry 2: architecture.md updates

Attempting: Apply all 7 changes to architecture.md.

Result:
- ✅ **Validation pipeline**: Updated from "5 layers" to "6 layers", added layer 6 "Unknown Params: Warns on unrecognized node params"
- ✅ **Markdown parser docs**: Added new "Markdown Parser" section in Key Abstractions, documenting `markdown_parser.py`, `MarkdownParseResult`, `MarkdownParseError`, `parse_markdown()`, state machine architecture, and the pipeline diagram
- ✅ **Repair system gating**: Replaced "pending markdown format migration" with explicit "⚠️ GATED (Task 107 Decision 26)" language, noting code preserved but unreachable, `--auto-repair` disabled, re-enable requires prompt rewrite
- ✅ **MCP workflow_save**: Updated tool description to note it accepts raw `.pflow.md` content or file path
- ✅ **MCP client example**: Replaced JSON IR example with `.pflow.md` markdown format showing an MCP node
- ✅ **Template system example**: Replaced JSON IR example with inline `.pflow.md` param syntax
- ✅ **Metadata format**: Added frontmatter example and explanation below Storage Locations — flat YAML, body never modified by metadata updates

Files modified: `architecture/architecture.md`
Status: architecture.md complete. Moving to mcp-guide.md.

## Entry 3: mcp-guide.md updates

Attempting: Update two JSON workflow examples to .pflow.md format.

Result:
- ✅ **Line 43-52 (simple example)**: Replaced JSON IR workflow with `.pflow.md` format showing `## Steps` / `### read` pattern
- ✅ **Lines 222-255 (complex example)**: Replaced 3-node JSON workflow (list-issues → analyze → save-report) with full `.pflow.md` format including H1 title, description, `## Steps`, prose descriptions, code block for prompt
- ✅ Did NOT change any `.mcp.json` config references — those are MCP server configuration, not workflow format

Files modified: `architecture/guides/mcp-guide.md`
Status: All changes complete.

## Final Summary

Files modified:
- `architecture/architecture.md` (7 edits: parser docs, validation layers, repair gating, MCP save tool, MCP client example, template example, metadata format)
- `architecture/guides/mcp-guide.md` (2 edits: simple and complex workflow examples)

All changes are concise and accurate. No files outside the assignment were modified.
