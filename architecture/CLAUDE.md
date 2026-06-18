# pflow Architecture Documentation Guide

> Navigation guide for AI agents. Helps you decide WHICH files to read — not what's in them.

**Start here**: [architecture.md](./architecture.md) — current system architecture, accurately reflects the codebase.

**Node lifecycle primitives**: `src/pflow/core/node.py` — BaseNode, Node, wiring operators. Read when working on pflow node internals.

**Agent usage guide**: Run `pflow guide` for the authoritative CLI guide for AI agents.

## Documentation Structure

```
architecture/
├── CLAUDE.md                  # This file (navigation)
├── overview.md                # Why pflow exists (conceptual, not technical)
├── architecture.md            # Current system architecture (accurate)
├── guides/
│   └── mcp-guide.md           # MCP server integration guide
├── core-concepts/
│   └── data-type-coercion.md  # JSON auto-parsing and type coercion
├── features/
│   ├── shell-pipes.md         # Unix pipe/stdin support
│   ├── simple-nodes.md        # Node design philosophy
│   ├── api-key-management.md  # API key settings
│   └── node-filtering-system.md # Node allow/deny filtering
├── reference/
│   ├── ir-schema.md           # Flow IR and node metadata JSON schemas
│   ├── enhanced-interface-format.md # Node docstring format standard
│   └── template-variables.md  # ${variable} syntax reference
├── core-node-packages/
│   ├── llm-nodes.md           # LLM node spec
│   └── claude-nodes.md        # Claude Code node spec
├── implementation-details/
│   └── metadata-extraction.md # Node metadata extraction system
├── vision/                    # ⚠️ Future directions, NOT current implementation
├── best-practices/
│   └── testing-quick-reference.md
└── historical/                # ⚠️ Design-time docs, may be outdated
```

## File Guide — Non-Obvious Routing Signals

Only notes that help you decide whether to read a file. If the filename is self-explanatory, it's not listed here.

### Root-level docs

**overview.md** — The "why", not the "what". Read for design rationale and product philosophy. Does NOT describe the current system — `architecture.md` does that.

**Node authoring**: `src/pflow/nodes/CLAUDE.md` — how to write platform nodes. **Engine internals**: `src/pflow/runtime/CLAUDE.md` — compiler, engine, template resolution, batch. Key insight: complexity belongs in the compiler/engine layer, not in nodes.

### Core Concepts

**data-type-coercion.md** — Inventories all 6 auto-parse/coercion points in the system with assessments. Read when debugging "why was this value parsed/not parsed" issues. Design principle: producers store raw data, consumers declare types.

**Shared store pattern** — Documented in `src/pflow/runtime/CLAUDE.md` (reserved keys, canonical reference) and `src/pflow/nodes/CLAUDE.md` (shared store vs params guidelines). Nodes are isolated "dumb pipes" that communicate only through the shared store.

### Guides

**mcp-guide.md** — MCP tools appear as nodes with pattern `mcp-{server}-{tool}` after syncing. Both stdio and HTTP transports are implemented; stdio is the recommended/default transport, HTTP (`type: "http"`, via `streamablehttp_client`) is newer — read the guide before relying on it.

### Features

**shell-pipes.md** — Stdin detection uses `stat.S_ISFIFO()` (not `select()`). Only one workflow input can receive stdin. CLI params override piped stdin.

**simple-nodes.md** — Design philosophy: each node does exactly one thing. The `llm` node is the intentional "smart exception" that handles ALL text processing to prevent node proliferation.

### Core Node Packages

**llm-nodes.md** vs **claude-nodes.md** — Two-tier AI architecture. `llm` = general-purpose text processing via API through pflow's LiteLLM adapter. `claude-code` = agentic "super node" via Claude Code CLI with full project context and tool access. Different tools for different jobs.

### Reference

**ir-schema.md** — Two key artifacts: Flow IR (orchestration structure) and Node Metadata (interfaces from docstrings). Schema versioning: minor additions allowed, major bumps refuse to run.

### Vision and Historical

**vision/** — All vision docs describe FUTURE directions. `north-star-examples.md` uses `>>` CLI syntax that was never implemented. Read for design intent, not current behavior.

**historical/** — See `historical/CLAUDE.md` for full index. Design-time documents with valuable rationale but outdated specifics. Key paradigm shift: project moved from natural-language generation-first to primitives-first.

## Reading Paths by Goal

| Goal | Reading Path |
|------|--------------|
| **Conceptual understanding** | `overview.md` → `architecture.md` |
| **System implementation** | `architecture.md` → `src/pflow/runtime/CLAUDE.md` |
| **Writing new nodes** | `src/pflow/nodes/CLAUDE.md` → `features/simple-nodes.md` → `reference/enhanced-interface-format.md` |
| **Building workflows** | Run `pflow guide` for the authoritative agent guide |
| **CLI development** | `pflow --help` → `features/shell-pipes.md` → `reference/template-variables.md` |
| **JSON/type debugging** | `core-concepts/data-type-coercion.md` |

## Implementation CLAUDE.md Files

These `CLAUDE.md` files in the source tree provide implementation-level guidance. They load automatically when working in those directories.

| Architecture Concept | Implementation Guide | Key Content |
|---------------------|---------------------|-------------|
| Execution pipeline | `src/pflow/execution/CLAUDE.md` | ExecutionResult, formatters, status flow |
| Compilation, engine | `src/pflow/runtime/CLAUDE.md` | Compiler stages, engine architecture |
| Node implementation | `src/pflow/nodes/CLAUDE.md` | Retry patterns, interface format |
| CLI commands | `src/pflow/cli/CLAUDE.md` | Routing, subcommands |
| Core components | `src/pflow/core/CLAUDE.md` | Workflow manager, validation, settings |
| MCP server | `src/pflow/mcp_server/CLAUDE.md` | 3-layer architecture, tools |
| Node lifecycle primitives | `src/pflow/core/node.py` | BaseNode, Node, wiring operators |

## Important Notes

**Single source of truth**: Each concept has ONE canonical document. If you see duplication, find the canonical source.

**Prerequisites**: Node implementation docs assume you've read `src/pflow/nodes/CLAUDE.md` and understand the shared store pattern (see "Shared Store vs Params" section there). CLI docs build on the architecture overview.

**Current vs future**: Check root `CLAUDE.md` for authoritative project status. Features marked "v2.0" or "Future:" are not implemented.
