# Historical Documentation

This folder contains design-time and planning documents that were written before or during early implementation. While they contain valuable design rationale and thinking, **they do not accurately reflect the current implementation**.

## Why These Are Here

### Original Planning Documents
- **prd.md** - Original Product Requirements Document with early vision. Contains concepts like `=>` CLI syntax and `@flow_safe` that were either never implemented or implemented differently.
- **mvp-implementation-guide.md** - Original implementation roadmap. Useful for understanding the project's evolution but scope/features have changed.

### Superseded Architecture Documents
- **architecture-original.md** - Early architecture document with outdated CLI syntax and unimplemented features (e.g., MCP marked as "v2.0" when it's now fully implemented).
- **components-original.md** - Component inventory with outdated node names and feature status.

### Superseded Feature Specifications
- **cli-reference-original.md** - Original CLI reference with `=>` syntax that was never implemented. Current CLI uses `pflow workflow.json` or `pflow saved-name param=value`.
- **cli-runtime-original.md** - Original CLI runtime specification superseded by current implementation.
- **autocomplete-original.md** - Autocomplete feature specification (v2.0 - not yet implemented).
- **autocomplete-impl-original.md** - Autocomplete implementation details (v2.0 - not yet implemented).
- **mcp-integration-original.md** - Original MCP design document. MCP is now fully implemented - see `features/mcp-integration.md` for current status.
- **agent-guide-pre-task71.md** - Pre-task71 agent guide, superseded by CLI primitives approach. Run `pflow instructions usage` for current agent guide.

### Deprecated Node Specifications
- **github-nodes-original.md** - GitHub nodes specification. These nodes are deprecated - use MCP tools for GitHub integration instead (e.g., `mcp-github-list_issues`).

### Recently Archived (2026-01)

These documents were moved to historical/ during the January 2026 documentation cleanup:

| Document | Reason | Replacement |
|----------|--------|-------------|
| **execution-reference-original.md** | Describes 5 fictional features: `@flow_safe` decorator, `ExecutionContext` class, 7-step pipeline, error namespacing, `pflow.testing` module | `src/pflow/execution/CLAUDE.md` |
| **node-reference-original.md** | Uses outdated parameter fallback pattern removed in Task 102 | `reference/enhanced-interface-format.md` |
| **planner-specification.md** | Legacy planner spec; 40%+ describes unimplemented features (`=>` CLI syntax never built) | CLI primitives via `pflow instructions usage` |
| **planner-debugging.md** | Planner debugging guide with inaccurate trace format, inverted flag behavior | Trace files at `~/.pflow/debug/` |
| **thinking-tokens-optimization.md** | Anthropic-specific thinking tokens - obsolete after Task 95 (llm library) | N/A (provider-agnostic now) |
| **prompt-caching-architecture.md** | Anthropic cache API - obsolete after Task 95 (llm library) | N/A (provider-agnostic now) |
| **simonw-llm-patterns/** | Pre-implementation research for Task 95 (completed 2025-12-19) | `core-node-packages/llm-nodes.md` |

### Why These Were Moved

**Execution Reference**: Documented an aspirational v2.0 execution model that was never implemented. Features like `@flow_safe`, `ExecutionContext`, and structured error namespacing were design ideas, not reality.

**Node Reference**: Documented the "check shared store first, then params" fallback pattern that was explicitly removed in Task 102. Nodes now use params exclusively for inputs.

**Planner Docs**: The planner is labeled "legacy" in root CLAUDE.md. Many documented features (CLI pipe syntax `=>`, lockfile signatures, type shadow store) were never built.

**Anthropic-Specific Docs**: Task 95 switched all LLM usage to Simon Willison's `llm` library, making Anthropic-specific features (thinking tokens, prompt caching) inaccessible through pflow's abstraction layer.

**LLM Patterns Research**: Pre-implementation research that informed Task 95. Now that the task is complete, the research is historical context only.

## Source of Truth

For accurate, current documentation:
- **`architecture/architecture.md`** - Current system architecture
- **`CLAUDE.md` (root)** - Authoritative project overview and status
- **`pocketflow/CLAUDE.md`** - PocketFlow framework documentation

## What These Documents Got Right

Despite inaccuracies, these documents contain valuable insights:
- The shared store pattern design rationale
- The "explicit over magic" philosophy
- The importance of natural interfaces
- The template variable concept (implemented as `${var}`)
- The validation-first approach

## What Changed

| Original Plan | Current Reality |
|--------------|-----------------|
| `pflow node1 => node2` CLI syntax | `pflow workflow.json` or `pflow saved-name param=value` |
| `@flow_safe` decorator for purity | Not implemented (post-MVP) |
| MCP integration "v2.0" | Fully implemented (stdio + http transports) |
| Natural language planner as core | Labeled "legacy", being phased out |
| Node names like `yt-transcript`, `shell-exec` | Actual: `shell`, `read-file`, `llm`, etc. |

## Paradigm Shift: Planner-First to Primitives-First

The original PRD envisioned natural language as the primary interface, with the planner generating workflows from user descriptions. This approach was partially realized but proved less reliable than direct JSON creation for AI agents.

**Current approach:**
- AI agents use CLI primitives directly (discovery, run, save commands)
- Agents write JSON workflows manually with iteration
- The planner remains for human users but is labeled "legacy"
- The MCP server provides experimental programmatic access

This shift acknowledges that AI agents are capable of structured workflow creation and benefit more from precise primitives than fuzzy natural language interfaces.

**Authoritative source:** For the current agent interface, run `pflow instructions usage` to see the complete agent guide.
