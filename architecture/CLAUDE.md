# pflow Architecture Documentation Guide

> **Purpose**: This guide helps AI assistants navigate pflow architecture documentation. It provides both navigation guidance (WHEN/WHY to read files) and a detailed inventory (WHAT's inside each file).

> **PocketFlow documentation**: The documentation for `pocketflow` is in the `pocketflow/docs` folder. For a complete understanding of the foundation pflow is built on, reading the relevant documentation for `pocketflow` is strongly recommended.

## Quick Start (for AI Agents)

**Start here**: [architecture.md](./architecture.md) - Current system architecture

**For using pflow as an agent**: Run `pflow instructions usage` for the authoritative agent guide. The CLI primitives (workflow discover, registry discover, registry run, etc.) are the primary interface for AI agents.

## Documentation Structure

```
architecture/
├── CLAUDE.md                  # This file (navigation + inventory)
├── overview.md                # Conceptual foundation (why pflow exists)
├── architecture.md            # Current system architecture (accurate)
├── pflow-pocketflow-integration-guide.md  # For pflow developers (node authoring, internals)
├── guides/                    # Practical how-to guides
│   ├── json-workflows.md      # Writing JSON workflows
│   └── mcp-guide.md           # MCP integration guide
├── core-concepts/             # Fundamental patterns
│   └── shared-store.md        # Data communication (only remaining core concept)
├── features/                  # Feature specifications
│   ├── shell-pipes.md         # Unix pipe support
│   ├── simple-nodes.md        # Node design principles
│   ├── api-key-management.md  # API key settings
│   └── node-filtering-system.md # Node filtering
├── reference/                 # Technical references
│   ├── ir-schema.md           # JSON IR schema
│   ├── enhanced-interface-format.md # Docstring format for pflow nodes
│   └── template-variables.md  # Template variable reference
├── core-node-packages/        # Platform node specs
│   ├── llm-nodes.md           # LLM integration
│   └── claude-nodes.md        # Claude-specific nodes
├── implementation-details/    # Deep dives
│   └── metadata-extraction.md # Node metadata system
├── vision/                    # Long-term vision and philosophy
│   ├── CLAUDE.md              # Vision overview
│   ├── AI-Agents-Need-Hands.md
│   ├── mcp-as-extension-api.md
│   └── north-star-examples.md
├── best-practices/            # Development practices
│   └── testing-quick-reference.md # Testing patterns
└── historical/                # Design-time documents (outdated)
    ├── CLAUDE.md              # Context for historical docs
    ├── prd.md                 # Original PRD
    ├── execution-reference-original.md  # v2.0 vision (fictional features)
    ├── node-reference-original.md       # Outdated param fallback pattern
    ├── planner-specification.md         # Legacy planner spec
    ├── planner-debugging.md             # Planner debugging
    ├── thinking-tokens-optimization.md  # Obsolete Anthropic features
    ├── prompt-caching-architecture.md   # Obsolete cache API
    ├── simonw-llm-patterns/             # Task 95 research
    ├── mvp-implementation-guide.md
    ├── architecture-original.md
    ├── components-original.md
    ├── cli-reference-original.md
    ├── cli-runtime-original.md
    ├── autocomplete-original.md
    ├── autocomplete-impl-original.md
    ├── mcp-integration-original.md
    ├── agent-guide-pre-task71.md
    └── github-nodes-original.md  # Deprecated (use MCP instead)
```

## Document Status Legend

- ✅ **Current/Implemented**: Accurate and up-to-date
- ✅ **MVP**: Required for v0.1 (now complete)
- ⚠️ **Historical**: Design-time document, may be outdated
- ⚠️ **Vision**: Future directions, not current implementation
- ❌ **v2.0/v3.0**: Future versions

---

## File Inventory

Each entry includes:
- **Purpose**: What questions/problems the document addresses
- **Key Contents**: Main topics and sections covered
- **Critical Insights**: Warnings, anti-patterns, or must-know information
- **When to Use**: Specific scenarios requiring this document

### Root Level

#### [overview.md](./overview.md)
**Purpose**: Conceptual foundation for understanding pflow - the "why" before the "what."

**Key Contents**:
- Problem statement (using vs. creating, tool-by-tool orchestration pain)
- Core bets (compile orchestration, structure > flexibility, deterministic by default)
- Three-layer model (Agent → Workflows → Tools)
- Design decisions (CLI-first, JSON workflows, structure-only orchestration)
- What pflow is NOT (vs. visual builders, agent frameworks, code sandboxes)
- Vision and direction (substrate vision, economic context)
- What's validated vs. what's a bet

**Critical Insights**:
- pflow provides execution capabilities, not instructions
- Designing for agents (who need first-try success) produces interfaces that work well for humans too
- Workflow lifecycle (persist, discover, compose) enables creation to compound
- Research validated the PAIN, not demand for a specific solution

**When to Use**: Understanding pflow's purpose, architectural context, design rationale discussions

**Status**: ✅ Current (Conceptual Foundation)

---

#### [architecture.md](./architecture.md)
**Purpose**: Current system architecture document reflecting the actual implemented system.

**Key Contents**:
- How it works (5-step workflow authoring process)
- Key principles (shared store, deterministic structure, atomic nodes, observability)
- Technology stack (core dependencies and development tools)
- Interface modes (CLI primitives, natural language, MCP server)
- Execution pipeline overview
- Key abstractions (shared store, wrapper chain, templates)
- Node system and registry
- MCP integration (fully implemented)

**Critical Insights**:
- Accurately reflects current codebase
- MCP integration is complete (stdio + http transports)
- Shared store uses namespaced pattern
- Wrapper chain: Instrumented → Batch → Namespaced → TemplateAware → Node

**When to Use**: Understanding current system, designing new features, technology decisions, architecture reference

**Status**: ✅ Current (Accurate)

---

#### [pflow-pocketflow-integration-guide.md](./pflow-pocketflow-integration-guide.md)
**Purpose**: Critical guide for **pflow internal developers** writing platform nodes or extending pflow internals. NOT for users building workflows (they use JSON via CLI).

**Key Contents**:
- 10 critical insights about pflow-pocketflow integration
- RIGHT vs WRONG code examples for node authors
- Clear separation of what pocketflow provides vs what pflow adds
- Guidance on where complexity belongs (compiler/wrapper layer, not nodes)

**Critical Insights**:
- **#1**: PocketFlow IS the execution engine - don't reimplement
- **#2**: Nodes inherit from `pocketflow.Node`; wrappers applied by compiler
- **#3**: Shared Store starts as dict; namespacing added by compiler
- **#7**: JSON IR compilation is object instantiation, not code generation
- **#10**: What was kept simple vs what grew complex (and why)

**When to Use**: Writing new platform nodes, extending pflow internals, understanding compiler architecture

**Status**: ✅ Critical for pflow Development

---

### Historical Documents (`/historical/`)

> **Note**: Design-time documents with valuable rationale but may not reflect current implementation. See `historical/CLAUDE.md` for context.

| Document | Purpose |
|----------|---------|
| [prd.md](./historical/prd.md) | Original Product Requirements Document |
| [mvp-implementation-guide.md](./historical/mvp-implementation-guide.md) | Original implementation roadmap |
| [architecture-original.md](./historical/architecture-original.md) | Original architecture document |
| [components-original.md](./historical/components-original.md) | Original component inventory |
| [cli-runtime-original.md](./historical/cli-runtime-original.md) | CLI runtime specification |
| [cli-reference-original.md](./historical/cli-reference-original.md) | Original CLI reference |
| [autocomplete-original.md](./historical/autocomplete-original.md) | Autocomplete feature spec (v2.0) |
| [autocomplete-impl-original.md](./historical/autocomplete-impl-original.md) | Autocomplete implementation details |
| [mcp-integration-original.md](./historical/mcp-integration-original.md) | MCP design document (superseded) |
| [agent-guide-pre-task71.md](./historical/agent-guide-pre-task71.md) | Pre-task71 agent guide |
| [github-nodes-original.md](./historical/github-nodes-original.md) | Deprecated GitHub nodes (use MCP instead) |
| [execution-reference-original.md](./historical/execution-reference-original.md) | v2.0 vision with fictional features (moved 2026-01) |
| [node-reference-original.md](./historical/node-reference-original.md) | Outdated parameter fallback pattern (moved 2026-01) |
| [planner-specification.md](./historical/planner-specification.md) | Legacy planner spec, many features never implemented (moved 2026-01) |
| [planner-debugging.md](./historical/planner-debugging.md) | Planner debugging with inaccurate details (moved 2026-01) |
| [thinking-tokens-optimization.md](./historical/thinking-tokens-optimization.md) | Obsolete Anthropic-specific features (moved 2026-01) |
| [prompt-caching-architecture.md](./historical/prompt-caching-architecture.md) | Obsolete Anthropic cache API (moved 2026-01) |
| [simonw-llm-patterns/](./historical/simonw-llm-patterns/) | Pre-implementation research for Task 95 (moved 2026-01) |

**Status**: ⚠️ All historical documents are design-time artifacts

---

### Core Concepts (`/core-concepts/`)

#### [shared-store.md](./core-concepts/shared-store.md)
**Purpose**: Defines the core architectural pattern for node communication - shared store with optional proxy layer.

**Key Contents**:
- Shared store vs params usage guidelines
- Template variable resolution (`${variable}` syntax)
- Node autonomy principle and isolation rules
- NodeAwareSharedStore proxy pattern
- Progressive complexity examples

**Critical Insights**:
- Nodes are "dumb pipes" - isolated computation units
- Shared store takes precedence over params for dynamic data
- Template variables create node dependencies
- Same node works in different flows via proxy mapping
- All conditional logic at flow level, never in nodes

**When to Use**: Designing nodes, understanding data flow, implementing proxy mappings, debugging communication

**Status**: ✅ MVP (proxy optional)

> **Note**: The Core Concepts directory now contains only `shared-store.md`. Previously included documents have been moved:
> - **schemas.md** → moved to `reference/ir-schema.md` (it's a spec, not a concept)
> - **registry.md** → merged into `architecture.md#node-naming`
> - **runtime.md** → moved to `.taskmaster/feature-dump/` (mostly unimplemented future features)

---

### Guides (`/guides/`)

#### [json-workflows.md](./guides/json-workflows.md)
**Purpose**: Practical guide for writing JSON workflow files directly.

**Key Contents**:
- Minimal valid workflow example
- Required fields (`ir_version`, `nodes`)
- Optional fields (`edges`, `metadata`, `inputs`, `outputs`, `trigger_node`)
- Common mistakes and troubleshooting
- Node types and parameter examples

**Critical Insights**:
- `ir_version: "0.1.0"` is REQUIRED - without it pflow won't recognize the file as a workflow
- Each node needs `id`, `type`, and optionally `params`
- Single-node workflows don't need `edges`

**When to Use**: Creating workflows manually, debugging workflow JSON, understanding IR structure practically

**Status**: ✅ Current

---

#### [mcp-guide.md](./guides/mcp-guide.md)
**Purpose**: Practical guide for integrating MCP servers with pflow workflows.

**Key Contents**:
- Adding MCP servers (`pflow mcp add`)
- Discovering tools (`pflow mcp sync`)
- Using MCP tools in workflows
- MCP node naming pattern (`mcp-{server}-{tool}`)
- Authentication and configuration

**Critical Insights**:
- MCP tools appear as nodes with pattern `mcp-{server}-{tool}` after syncing
- Supports both stdio and HTTP transports
- Environment variables can be passed to MCP server processes

**When to Use**: Connecting external MCP servers, using MCP tools in workflows, understanding MCP integration

**Status**: ✅ Current

---

### Features (`/features/`)

#### [simple-nodes.md](./features/simple-nodes.md)
**Purpose**: Defines simple, single-purpose node architecture reducing cognitive load with clear interfaces.

**Key Contents**:
- Architecture comparison (complex vs simple)
- Core simple nodes overview with interfaces
- LLM node as smart exception rationale
- Implementation patterns and consistency
- Real-world business scenarios

**Critical Insights**:
- Philosophy: Each node does exactly one thing with no magic
- LLM node handles ALL text processing to prevent explosion
- Future CLI grouping (v2.0) is purely syntactic sugar
- Trade-off: more names but crystal clear purpose
- Direct alignment with MCP tool mapping

**When to Use**: Implementing nodes, understanding design philosophy, explaining architecture choices

**Status**: ✅ MVP

---

#### [shell-pipes.md](./features/shell-pipes.md)
**Purpose**: Native Unix shell pipe integration for seamless command-line workflows.

**Key Contents**:
- Motivation for shell pipe support
- Workflow input `stdin: true` declaration pattern
- FIFO-only pipe detection (prevents hanging)
- CLI override behavior and workflow chaining
- Similarity to llm CLI patterns

**Critical Insights**:
- Stdin routes to workflow input marked with `"stdin": true`
- FIFO detection via `stat.S_ISFIFO()` (not `select()`)
- CLI parameters override piped stdin
- Only one input per workflow can receive stdin

**When to Use**: Implementing stdin detection, Unix integration, handling piped input

**Status**: ✅ MVP

---

### Reference (`/reference/`)

#### [ir-schema.md](./reference/ir-schema.md)
**Purpose**: JSON schema governance for Flow IR and Node Metadata artifacts.

**Key Contents**:
- Flow IR structure (nodes, edges, mappings, metadata)
- Node metadata schema from docstrings
- Interface declaration rules and types
- Proxy mapping schema for complex flows
- Schema validation and evolution rules
- Batch processing configuration

**Critical Insights**:
- Two key artifacts: Flow IR (orchestration) and Node Metadata (interfaces)
- Natural interfaces use `shared["key"]` patterns
- Mapping definitions are flow-level, not node concerns
- Only `@flow_safe` nodes may specify retry/cache settings
- Minor additions allowed; major bumps refuse to run

**When to Use**: Understanding IR structure, extracting metadata, implementing validation, debugging compatibility

**Status**: ✅ MVP

---

#### [template-variables.md](./reference/template-variables.md)
**Purpose**: Reference for template variable syntax and resolution.

**When to Use**: Understanding `${variable}` syntax, nested access patterns, type resolution

**Status**: ✅ Current

---

#### [enhanced-interface-format.md](./reference/enhanced-interface-format.md)
**Purpose**: Docstring format standard for pflow node interfaces.

**When to Use**: Writing node docstrings, understanding interface extraction

**Status**: ✅ Current

---

### Core Node Packages (`/core-node-packages/`)

#### [llm-nodes.md](./core-node-packages/llm-nodes.md)
**Purpose**: General-purpose LLM node - smart exception handling all text processing.

**Key Contents**:
- Single `llm` node specification
- Rationale for consolidation
- Interface using prompt/response
- Model and temperature parameters
- Future llm CLI integration

**Critical Insights**:
- Prevents node proliferation for text tasks
- Always consistent interface
- Temperature defaults to 0.7
- Designed for future integration without breaks
- Different from claude-code (API vs CLI)

**When to Use**: Implementing text processing, understanding two-tier AI architecture

**Status**: ✅ MVP

---

#### [claude-nodes.md](./core-node-packages/claude-nodes.md)
**Purpose**: Claude Code super node - intentional exception providing comprehensive AI development.

**Key Contents**:
- Single `claude-code` super node specification
- Template-driven instruction generation
- Claude Code CLI integration
- Example planner instructions
- Technical requirements

**Critical Insights**:
- "Super node" exception justified by comprehensive capabilities
- Planner-generated instructions with template variables
- Full project context and tool access
- Output is comprehensive `shared["code_report"]`
- Instructions combine multiple development tasks

**When to Use**: Implementing claude-code node, understanding two-tier AI architecture

**Status**: ✅ MVP

---

### Implementation Details (`/implementation-details/`)

#### [metadata-extraction.md](./implementation-details/metadata-extraction.md)
**Purpose**: Infrastructure for extracting structured metadata from node docstrings.

**Key Contents**:
- Docstring format standard
- `PflowMetadataExtractor` implementation
- `InterfaceSectionParser` for formats
- Registry integration
- CLI commands

**Critical Insights**:
- Zero runtime overhead - pre-extracted to JSON
- Supports simple and structured formats
- Code-metadata consistency validation via AST
- Performance optimized with caching
- Automatic during `pflow registry install`

**When to Use**: Implementing metadata extraction, registry commands, writing node docs

**Status**: ✅ MVP

---

### Vision (`/vision/`)

> **Warning**: These documents describe potential FUTURE directions, NOT current implementation.

#### [CLAUDE.md](./vision/CLAUDE.md)
**Purpose**: Context and caveats for vision documents.

**When to Use**: Before reading any vision document

---

#### [AI-Agents-Need-Hands.md](./vision/AI-Agents-Need-Hands.md)
**Purpose**: Marketing vision for the value proposition of pflow workflows.

**Critical Insights**: Vision document - may present implemented features as future possibilities. Useful for understanding "why pflow exists."

**Status**: ⚠️ Vision (not current implementation)

---

#### [mcp-as-extension-api.md](./vision/mcp-as-extension-api.md)
**Purpose**: Future vision for MCP-only extension philosophy.

**Critical Insights**: Current pflow uses hybrid approach (platform nodes + MCP). This vision may not be fully realized.

**Status**: ⚠️ Vision (not current implementation)

---

#### [north-star-examples.md](./vision/north-star-examples.md)
**Purpose**: Planner demonstration examples showing aspirational workflows.

**Critical Insights**: Uses `>>` CLI syntax that was never implemented. The planner is now labeled "legacy." Useful for understanding design intent.

**Status**: ⚠️ Vision (not current implementation)

---

### Best Practices (`/best-practices/`)

#### [testing-quick-reference.md](./best-practices/testing-quick-reference.md)
**Purpose**: Quick reference for testing patterns and practices in pflow.

**When to Use**: Writing tests, understanding test patterns

**Status**: ✅ Current

---

## Implementation References

For deeper implementation details (WHAT and HOW), these CLAUDE.md files provide comprehensive guidance. They are automatically loaded when working in those directories.

| Architecture Concept (WHY) | Implementation Guide (WHAT/HOW) | Key Content |
|---------------------------|--------------------------------|-------------|
| Execution pipeline, repair | `src/pflow/execution/CLAUDE.md` | ExecutionResult, checkpoint structure, repair loop |
| Compilation, wrapper chain | `src/pflow/runtime/CLAUDE.md` | Compiler stages, wrapper order, template resolution |
| Node implementation | `src/pflow/nodes/CLAUDE.md` | **Critical**: Retry patterns, interface format |
| CLI commands | `src/pflow/cli/CLAUDE.md` | Routing, subcommands, agent features |
| Core components | `src/pflow/core/CLAUDE.md` | Workflow manager, validation, settings |
| MCP server | `src/pflow/mcp_server/CLAUDE.md` | 3-layer architecture, 11 tools |
| PocketFlow framework | `pocketflow/CLAUDE.md` | Framework basics, docs/cookbook links |

**When to consult these files:**
- Implementing a new feature in that area
- Debugging issues in that subsystem
- Understanding data structures and patterns
- Finding test patterns and mock points

## Navigation Guide

### Reading Paths by Goal

| Goal | Reading Path |
|------|--------------|
| **Conceptual understanding** | `overview.md` → `architecture.md` → `core-concepts/shared-store.md` |
| **System implementation** | `architecture.md` → `shared-store.md` → `pflow-pocketflow-integration-guide.md` |
| **Writing new nodes** | `pflow-pocketflow-integration-guide.md` → `features/simple-nodes.md` → `reference/enhanced-interface-format.md` |
| **Building workflows** | Run `pflow instructions usage` for the authoritative agent guide |
| **CLI development** | `pflow --help` → `features/shell-pipes.md` → `reference/template-variables.md` |

### Quick Reference

- **Why pflow exists**: `overview.md` (problem statement, core bets, design decisions)
- **How pflow works**: `architecture.md` (shared store pattern, wrapper chain, execution pipeline)
- **Extending pflow internals**: `pflow-pocketflow-integration-guide.md` (node authoring, compiler architecture)
- **Data flow between nodes**: `core-concepts/shared-store.md` + `reference/ir-schema.md`
- **Project status**: Root `CLAUDE.md` (implemented features, planned work)
- **Historical context**: `historical/` folder (design rationale, may be outdated)

## Key Document Relationships

```
overview.md (conceptual foundation)
└─> architecture.md (current architecture)
    ├─> pflow-pocketflow-integration-guide.md
    ├─> core-concepts/shared-store.md
    └─> reference/ir-schema.md

historical/ (design-time, outdated)
├─> CLAUDE.md (context for all historical docs)
├─> prd.md, mvp-implementation-guide.md
├─> architecture-original.md, components-original.md
├─> planner-specification.md, planner-debugging.md
├─> simonw-llm-patterns/ (Task 95 research)
└─> (19 total historical documents)
```

## Important Notes

### Single Source of Truth
Each concept has ONE canonical document. Other documents link to it rather than duplicating content. If you see the same concept explained in multiple places, find the canonical source.

### Current vs Future
MVP is feature-complete. Many documents describe both current and future features. Look for:
- Features marked "Implemented" or "MVP" are complete
- "v2.0" or "Future:" for post-MVP features
- Check root `CLAUDE.md` for authoritative project status
- Check `historical/` for design-time documents (may be outdated)

### Prerequisites
Some documents assume knowledge from others:
- Node implementation docs assume you've read `pflow-pocketflow-integration-guide.md`
- Node docs assume you understand the shared store pattern
- CLI docs build on the architecture overview

### Historical Documents
Documents in `historical/` contain valuable design rationale but may not reflect current implementation:
- Use them to understand "why" decisions were made
- Always verify against current code before relying on specifics
- The CLAUDE.md in historical/ explains what changed and lists all historical documents
- Includes planner specs, obsolete API docs, and Task 95 research (simonw-llm-patterns/)
