# 05 — `pflow visualize` mermaid output on song-creator

**Surface**: 12-real-world-lyrics-generator

**Triggers**: `pflow visualize` on the song-creator sub-workflow (LLM-only,
no MCP dependencies).

**Note**: `pflow visualize` validates before rendering. The parent
lyrics-generator depends on user-configured MCP servers
(`mcp-klavis-youtube-...`), so visualize on the parent fails with
"Unknown node type" before ever rendering. This case targets song-creator
to exercise visualize-with-cache cleanly.

**Expected**: a Mermaid flowchart. Per task-review.md: *"Cache section is
invisible to mermaid (correct — graph topology unchanged)."* The diagram
should NOT include any `## Cache` artifacts.

**Mutation contract**: locks the song-creator mermaid output. If a future
refactor surfaces `## Cache` as a node in the graph, the diff catches it.

**Side-finding**: validate-before-visualize means a workflow with any
unknown-node-type sub-workflow can't be visualized at all, even though
visualize is read-only and could render unknown nodes as opaque shapes.
Documented as F-05 in FINDINGS.md.
