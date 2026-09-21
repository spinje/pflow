# Historical documentation

These documents preserve design rationale, not current implementation contracts. Verify CLI syntax, feature status, and code patterns against current source before applying them. Do not treat a historical proposal as evidence that a feature exists.

Start with `architecture/architecture.md` for the system overview and `pflow guide` for current agent usage. Paths in the first column are relative to this directory; current-owner paths are repository-relative.

| Historical material | Where to check current behavior |
|---------------------|---------------------------------|
| `prd.md`, `mvp-implementation-guide.md`, `architecture-original.md`, `components-original.md` | `architecture/architecture.md`, then the relevant source-directory CLAUDE.md |
| `cli-reference-original.md`, `cli-runtime-original.md`, `autocomplete-original.md`, `autocomplete-impl-original.md` | `src/pflow/cli/CLAUDE.md` |
| `planner-specification.md`, `planner-debugging.md`, `agent-guide-pre-task71.md` | `pflow guide`; the built-in natural-language planner was removed |
| `json-workflows-original.md` | `pflow guide` for authored `.pflow.md`; `src/pflow/core/markdown_parser.py` for parsing |
| `node-reference-original.md`, `shared-store-original.md` | `src/pflow/nodes/CLAUDE.md`, `src/pflow/runtime/CLAUDE.md`; interface standard: `architecture/reference/enhanced-interface-format.md` |
| `execution-reference-original.md` | `src/pflow/execution/CLAUDE.md` |
| `mcp-integration-original.md`, `github-nodes-original.md` | `src/pflow/mcp/CLAUDE.md` for client integration; `src/pflow/mcp_server/CLAUDE.md` for pflow's server |
| `simonw-llm-patterns/`, `thinking-tokens-optimization.md` | `src/pflow/core/llm_client.py`, `architecture/core-node-packages/llm-nodes.md` |
| `prompt-caching-architecture.md` | `src/pflow/core/prompt_cache.py` |

Old arrow-based CLI syntax and the proposed `@flow_safe` model are design context. Current workflow entrypoints are `pflow workflow.pflow.md` and `pflow saved-name param=value`; shared-store and node-boundary rationale remains useful, but its implementation has changed.
