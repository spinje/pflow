# Architecture documentation guide

Use this file to choose what to read. Paths below are repository-relative.

## Reading paths by goal

| Goal | Start here |
|------|------------|
| Product rationale | `architecture/overview.md` |
| System architecture | `architecture/architecture.md`, then the implementation owner below |
| Node lifecycle and authoring | `src/pflow/core/node.py` → `src/pflow/nodes/CLAUDE.md`; interface standard: `architecture/reference/enhanced-interface-format.md` |
| Compiler, engine, templates, batch, shared store | `src/pflow/runtime/CLAUDE.md` |
| Execution pipeline and results | `src/pflow/execution/CLAUDE.md` |
| CLI commands and stdin/stdout | `src/pflow/cli/CLAUDE.md`; design context: `architecture/features/shell-pipes.md` |
| Unexpected JSON parsing or type conversion | `architecture/core-concepts/data-type-coercion.md`, then the cited implementation |
| Workflow IR and node metadata | `architecture/reference/ir-schema.md`; current schema: `src/pflow/core/ir_schema.py`; metadata extraction: `src/pflow/registry/CLAUDE.md` |
| Template syntax | `architecture/reference/template-variables.md` |
| LLM versus autonomous agent nodes | `architecture/core-node-packages/llm-nodes.md` and `architecture/core-node-packages/agent-nodes.md` |
| MCP tools used by workflows | `src/pflow/mcp/CLAUDE.md` |
| Exposing pflow as an MCP server | `src/pflow/mcp_server/CLAUDE.md` |
| Settings, parsing, diagnostics | `src/pflow/core/CLAUDE.md` |
| Building workflows | Run `pflow guide` for agent usage instructions |

## Authority and historical context

Architecture documents explain design and rationale; verify behavior against the implementation owner before relying on commands, schema promises, or feature status. For example, `architecture/guides/mcp-guide.md` still contains old natural-language and direct-node CLI examples.

- `architecture/vision/` is aspirational design context, not an implementation inventory. Some features described there have since shipped.
- `architecture/historical/CLAUDE.md` routes to early and superseded designs. The natural-language planner and arrow-based CLI examples are historical, not current entrypoints.
- Keep one canonical explanation per concept. Link to its owner instead of duplicating implementation details here.
