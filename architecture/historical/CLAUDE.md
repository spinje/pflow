# Historical Documentation

These are design-time documents from early planning. They contain valuable design rationale but **do not accurately reflect the current implementation**. Always verify against code before relying on specifics.

> The core design philosophy (shared store pattern, explicit over magic, validation-first) in these docs IS still valid — but implementation details, CLI syntax, and feature status are often wrong.

## Source of Truth

- **`architecture/architecture.md`** — Current system architecture
- **`CLAUDE.md` (root)** — Authoritative project status
- **`pflow guide`** — Current agent interface guide

## What Changed

| Original Plan | Current Reality |
|--------------|-----------------|
| `pflow node1 => node2` CLI syntax | `pflow workflow.pflow.md` or `pflow saved-name param=value` |
| `@flow_safe` decorator for purity | Not implemented |
| MCP integration "v2.0" | Fully implemented (stdio + http transports) |
| Natural language planner as core | Labeled "legacy" — agents use CLI primitives directly |
| Node names like `yt-transcript`, `shell-exec` | Actual: `shell`, `read-file`, `llm`, etc. |
| Anthropic-specific features (thinking tokens, prompt caching) | Provider-agnostic via LiteLLM (Task 158 — superseded the Simon Willison `llm` library wiring from Task 95). Prompt caching is being re-introduced as a first-class feature in Task 159. |

## Document Index

### Original planning docs

| Document | Context |
|----------|---------|
| prd.md | Original PRD. Contains `=>` syntax and `@flow_safe` — never implemented. |
| mvp-implementation-guide.md | Original roadmap. Scope/features changed significantly. |

### Superseded architecture and feature specs

| Document | Context |
|----------|---------|
| architecture-original.md | Outdated CLI syntax, MCP marked "v2.0" (now implemented). |
| components-original.md | Outdated node names and feature status. |
| cli-reference-original.md | Uses `=>` syntax. Current: `pflow workflow.pflow.md`. |
| cli-runtime-original.md | Superseded by current implementation. |
| autocomplete-original.md, autocomplete-impl-original.md | v2.0 feature — not yet implemented. |
| mcp-integration-original.md | Superseded. MCP is fully implemented. |
| agent-guide-pre-task71.md | Superseded by CLI primitives. Run `pflow guide`. |
| github-nodes-original.md | Deprecated — use MCP tools (e.g., `mcp-github-list_issues`). |

### Archived January 2026

| Document | Why moved | Current replacement |
|----------|-----------|-------------------|
| execution-reference-original.md | Describes 5 fictional features (`@flow_safe`, `ExecutionContext`, etc.) | `src/pflow/execution/CLAUDE.md` |
| node-reference-original.md | Outdated param fallback pattern (removed in Task 102) | `reference/enhanced-interface-format.md` |
| planner-specification.md | 40%+ describes unimplemented features | `pflow guide` |
| planner-debugging.md | Inaccurate trace format, inverted flag behavior | Trace files at `~/.pflow/debug/` |
| thinking-tokens-optimization.md | Pre-LiteLLM (Task 158) design; provider-agnostic now. | N/A |
| prompt-caching-architecture.md | Pre-LiteLLM design. Task 159 is reintroducing prompt caching — may again be relevant material. | `src/pflow/core/prompt_cache.py` (current) |
| simonw-llm-patterns/ | Pre-implementation research for Task 95 (Simon Willison `llm` library — superseded by Task 158 / LiteLLM) | `core-node-packages/llm-nodes.md` |
