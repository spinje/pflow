# pflow Architecture Documentation Navigation Guide

> **Purpose**: This guide helps AI assistants navigate the pflow architecture documentation to quickly find the information they need. For a detailed inventory of what's in each file, see [index.md](./index.md).

## 🚀 AI Agents Implementing Features?

**Start here**: [architecture.md](./architecture.md) - Current system architecture

**For using pflow as an agent**: Run `pflow instructions usage` for the authoritative agent guide. The CLI primitives (workflow discover, registry discover, registry run, etc.) are the primary interface for AI agents.

## Documentation Structure

```
architecture/
├── index.md                   # File-by-file content inventory
├── architecture.md            # Current system architecture (accurate)
├── pflow-pocketflow-integration-guide.md  # For pflow developers (node authoring, internals)
├── runtime-components.md      # Runtime vs user-facing components
├── core-concepts/             # Fundamental patterns
│   └── shared-store.md        # Data communication (only remaining core concept)
├── features/                  # Feature specifications
│   ├── planner.md             # Natural language planning (legacy)
│   ├── shell-pipes.md         # Unix pipe support
│   ├── simple-nodes.md        # Node design principles
│   ├── workflow-analysis.md   # AI workflow inefficiencies
│   └── mcp-integration.md     # MCP protocol (implemented)
├── reference/                 # Technical references
│   ├── cli-reference.md       # CLI syntax and commands
│   ├── node-reference.md      # Node implementation guide
│   ├── ir-schema.md           # JSON IR schema (moved from core-concepts/schemas.md)
│   ├── enhanced-interface-format.md # Docstring format for pflow nodes
│   └── execution-reference.md # Execution model
├── core-node-packages/        # Platform node specs
│   ├── llm-nodes.md           # LLM integration
│   └── claude-nodes.md        # Claude-specific nodes
├── implementation-details/    # Deep dives
│   ├── metadata-extraction.md # Node metadata system
│   └── simonw-llm-patterns/   # LLM CLI pattern analysis
│       ├── FINAL-ANALYSIS.md  # Pattern recommendations
│       └── IMPLEMENTATION-GUIDE.md  # Integration guide
├── future-version/            # Post-MVP features
│   ├── flow-safe-caching.md   # @flow_safe and caching (moved from core-concepts/runtime.md)
│   ├── llm-node-gen.md        # Dynamic node generation
│   └── json-extraction.md     # JSON handling improvements
├── vision/                    # Long-term vision and philosophy
│   ├── CLAUDE.md              # Vision overview
│   ├── AI-Agents-Need-Hands.md
│   ├── mcp-as-extension-api.md
│   └── north-star-examples.md
└── historical/                # Design-time documents (outdated)
    ├── CLAUDE.md              # Context for historical docs
    ├── prd.md                 # Original PRD
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

## Implementation References

For deeper implementation details (WHAT and HOW), these CLAUDE.md files provide comprehensive guidance.
They are automatically loaded when working in those directories.

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

## Navigation by Purpose

### "I need to understand..."

**The overall system**
- Start with: `architecture.md` (current, accurate architecture)
- Key insight: Focus on shared store pattern and wrapper chain

**What we've built (MVP complete)**
- Start with: `architecture.md` for current system overview
- Reference: Root `CLAUDE.md` for project status and implemented features

**How to extend pflow (writing nodes, internal development)**
- **Must read**: `pflow-pocketflow-integration-guide.md`
- This is for pflow developers, not users building workflows
- Covers: node authoring, compiler architecture, what complexity to avoid


**The data flow between nodes**
- Primary: `core-concepts/shared-store.md`
- Supporting: `reference/ir-schema.md` (section on mappings)

**How to implement a node**
- Guide: `reference/node-reference.md`
- Principles: `features/simple-nodes.md`
- Examples: Any file in `core-node-packages/`

**The CLI syntax and behavior**
- Reference: `reference/cli-reference.md`
- Shell support: `features/shell-pipes.md`

**Natural language planning**
- Specification: `features/planner.md`
- Context: `features/workflow-analysis.md` (why we need it)

## Document Categories

### 🎯 Start Here (Core Understanding)
1. `architecture.md` - Current system architecture (accurate)
2. `pflow-pocketflow-integration-guide.md` - For pflow developers extending the system
3. Root `CLAUDE.md` - Project status and implemented features

### 📐 Architecture Documents
- System design and component relationships
- How pieces fit together
- Design decisions and rationale

### 🧩 Core Concepts
- Fundamental patterns that everything builds on
- Shared store is the only true "core concept"
- Read before implementing features

### ⚙️ Feature Specifications
- Detailed specs for each major feature
- Implementation requirements
- User-facing behavior

### 📖 Reference Guides
- Technical specifications
- Implementation patterns
- "How to" guides

### 📦 Node Package Specs
- Platform-specific node documentation
- Interface definitions
- Usage examples

## Suggested Reading Paths

### For Understanding the System
1. `architecture.md` (current, accurate)
2. `core-concepts/shared-store.md`
3. `runtime-components.md`
4. `pflow-pocketflow-integration-guide.md` (if extending pflow)

### For Implementing Nodes
1. `features/simple-nodes.md`
2. `reference/node-reference.md`
3. `core-concepts/shared-store.md`
4. Pick relevant `core-node-packages/*.md`

### For CLI Development
1. `reference/cli-reference.md`
2. `features/shell-pipes.md`
3. `reference/execution-reference.md`

### For Natural Language Features
1. `features/workflow-analysis.md` (context)
2. `features/planner.md`
3. `reference/ir-schema.md`

## Key Document Relationships

```
architecture.md (current architecture)
├─> pflow-pocketflow-integration-guide.md
├─> runtime-components.md
├─> core-concepts/shared-store.md
└─> reference/ir-schema.md

reference/cli-reference.md
└─> features/shell-pipes.md

historical/ (design-time, outdated)
├─> CLAUDE.md (context for all historical docs)
├─> prd.md, mvp-implementation-guide.md
├─> architecture-original.md, components-original.md
└─> (11 total historical documents)
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
- The CLAUDE.md in historical/ explains what changed and lists all 11 documents

---

**Quick Tip**: Use `index.md` to see what's IN each file. Use this guide to understand WHEN and WHY to read each file.
