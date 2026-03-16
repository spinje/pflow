# pflow Architecture Documentation Guide

> Navigation guide for AI agents. Helps you decide WHICH files to read — not what's in them.

**Start here**: [architecture.md](./architecture.md) — current system architecture, accurately reflects the codebase.

**PocketFlow docs**: `src/pflow/pocketflow/docs/` — read these when working on pflow internals built on PocketFlow.

**Agent usage guide**: Run `pflow instructions usage` for the authoritative CLI guide for AI agents.

## Documentation Structure

```
architecture/
├── CLAUDE.md                  # This file (navigation)
├── overview.md                # Why pflow exists (conceptual, not technical)
├── architecture.md            # Current system architecture (accurate)
├── pflow-pocketflow-integration-guide.md  # For pflow developers (node authoring, internals)
├── guides/
│   ├── json-workflows.md      # ⚠️ Historical — superseded by .pflow.md format
│   └── mcp-guide.md           # MCP server integration guide
├── core-concepts/
│   ├── shared-store.md        # Node communication via shared store
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
│   ├── CLAUDE.md
│   ├── AI-Agents-Need-Hands.md
│   ├── mcp-as-extension-api.md
│   └── north-star-examples.md
├── best-practices/
│   └── testing-quick-reference.md
└── historical/                # ⚠️ Design-time docs, may be outdated
    ├── CLAUDE.md              # Index and context for all historical docs
    └── (19 documents)         # PRD, original specs, deprecated features
```

## File Guide — Non-Obvious Routing Signals

Only notes that help you decide whether to read a file. If the filename is self-explanatory, it's not listed here.

### Root-level docs

**overview.md** — The "why", not the "what". Read for design rationale and product philosophy. Does NOT describe the current system — `architecture.md` does that.

**pflow-pocketflow-integration-guide.md** — For **pflow internal developers** writing platform nodes or extending compiler/runtime internals. NOT for users building workflows. Key insight: complexity belongs in the compiler/wrapper layer, not in nodes.

### Core Concepts

**shared-store.md** — Core pattern: nodes are isolated "dumb pipes" that communicate only through the shared store. Template variables (`${var}`) create implicit node dependencies. All conditional logic at flow level, never in nodes.

**data-type-coercion.md** — Inventories all 6 auto-parse/coercion points in the system with assessments. Read when debugging "why was this value parsed/not parsed" issues. Design principle: producers store raw data, consumers declare types.

### Guides

**mcp-guide.md** — MCP tools appear as nodes with pattern `mcp-{server}-{tool}` after syncing. Supports stdio and HTTP transports.

### Features

**shell-pipes.md** — Stdin detection uses `stat.S_ISFIFO()` (not `select()`). Only one workflow input can receive stdin. CLI params override piped stdin.

**simple-nodes.md** — Design philosophy: each node does exactly one thing. The `llm` node is the intentional "smart exception" that handles ALL text processing to prevent node proliferation.

### Core Node Packages

**llm-nodes.md** vs **claude-nodes.md** — Two-tier AI architecture. `llm` = general-purpose text processing via API (Simon Willison's `llm` library). `claude-code` = agentic "super node" via Claude Code CLI with full project context and tool access. Different tools for different jobs.

### Reference

**ir-schema.md** — Two key artifacts: Flow IR (orchestration structure) and Node Metadata (interfaces from docstrings). Schema versioning: minor additions allowed, major bumps refuse to run.

### Vision and Historical

**vision/** — All vision docs describe FUTURE directions. `north-star-examples.md` uses `>>` CLI syntax that was never implemented. Read for design intent, not current behavior.

**historical/** — See `historical/CLAUDE.md` for full index. Design-time documents with valuable rationale but outdated specifics. Key paradigm shift: project moved from natural-language generation-first to primitives-first.

## Reading Paths by Goal

| Goal | Reading Path |
|------|--------------|
| **Conceptual understanding** | `overview.md` → `architecture.md` → `core-concepts/shared-store.md` |
| **System implementation** | `architecture.md` → `shared-store.md` → `pflow-pocketflow-integration-guide.md` |
| **Writing new nodes** | `pflow-pocketflow-integration-guide.md` → `features/simple-nodes.md` → `reference/enhanced-interface-format.md` |
| **Building workflows** | Run `pflow instructions usage` for the authoritative agent guide |
| **CLI development** | `pflow --help` → `features/shell-pipes.md` → `reference/template-variables.md` |
| **JSON/type debugging** | `core-concepts/data-type-coercion.md` |

## Implementation CLAUDE.md Files

These `CLAUDE.md` files in the source tree provide implementation-level guidance. They load automatically when working in those directories.

| Architecture Concept | Implementation Guide | Key Content |
|---------------------|---------------------|-------------|
| Execution pipeline | `src/pflow/execution/CLAUDE.md` | ExecutionResult, formatters, status flow |
| Compilation, wrapper chain | `src/pflow/runtime/CLAUDE.md` | Compiler stages, wrapper order |
| Node implementation | `src/pflow/nodes/CLAUDE.md` | Retry patterns, interface format |
| CLI commands | `src/pflow/cli/CLAUDE.md` | Routing, subcommands |
| Core components | `src/pflow/core/CLAUDE.md` | Workflow manager, validation, settings |
| MCP server | `src/pflow/mcp_server/CLAUDE.md` | 3-layer architecture, tools |
| PocketFlow framework | `src/pflow/pocketflow/CLAUDE.md` | Framework basics and docs |

## Important Notes

**Single source of truth**: Each concept has ONE canonical document. If you see duplication, find the canonical source.

**Prerequisites**: Node implementation docs assume you've read `pflow-pocketflow-integration-guide.md` and understand the shared store pattern. CLI docs build on the architecture overview.

**Current vs future**: Check root `CLAUDE.md` for authoritative project status. Features marked "v2.0" or "Future:" are not implemented.
