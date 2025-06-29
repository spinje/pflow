# pflow Documentation Navigation Guide

> **Purpose**: This guide helps AI assistants navigate the pflow documentation to quickly find the information they need. For a detailed inventory of what's in each file, see [index.md](./index.md).

## Documentation Structure

```
docs/
├── prd.md                     # Product Requirements Document
├── index.md                   # File-by-file content inventory
├── architecture/              # System design and integration
│   ├── architecture.md        # Core system design
│   ├── components.md          # MVP vs v2.0 breakdown
│   ├── pflow-pocketflow-integration-guide.md  # Critical integration patterns
│   └── adr/                   # Architectural Decision Records
│       └── 001-use-pocketflow-for-orchestration.md  # PocketFlow usage decision
├── core-concepts/             # Fundamental patterns
│   ├── registry.md            # Node discovery system
│   ├── runtime.md             # Execution engine
│   ├── schemas.md             # JSON formats
│   └── shared-store.md        # Data communication
├── features/                  # Feature specifications
│   ├── mvp-scope.md           # What's in/out of MVP
│   ├── implementation-roadmap.md  # Development phases
│   ├── cli-runtime.md         # CLI integration
│   ├── planner.md             # Natural language planning
│   ├── shell-pipes.md         # Unix pipe support
│   ├── simple-nodes.md        # Node design principles
│   ├── workflow-analysis.md   # AI workflow inefficiencies
│   ├── autocomplete.md        # CLI autocomplete (v2.0)
│   └── mcp-integration.md     # MCP protocol (v2.0)
├── reference/                 # Technical references
│   ├── cli-reference.md       # CLI syntax and commands
│   ├── node-reference.md      # Node implementation guide
│   └── execution-reference.md # Execution model
├── core-node-packages/        # Platform node specs
│   ├── llm-nodes.md           # LLM integration
│   ├── ci-nodes.md            # CI/CD nodes
│   ├── github-nodes.md        # GitHub integration
│   └── claude-nodes.md        # Claude-specific nodes
├── implementation-details/    # Deep dives
│   ├── metadata-extraction.md # Node metadata system
│   ├── autocomplete-impl.md   # Autocomplete details
│   └── simonw-llm-patterns/  # LLM CLI pattern analysis
│       ├── FINAL-ANALYSIS.md  # Pattern recommendations
│       └── IMPLEMENTATION-GUIDE.md  # Integration guide
└── future-version/            # Post-MVP features
    ├── llm-node-gen.md        # Dynamic node generation
    └── json-extraction.md     # JSON handling improvements
```

## Navigation by Purpose

### "I need to understand..."

**The overall system**
- Start with: `prd.md` (sections 1-3 for vision, skip deep technical details)
- Then read: `architecture/architecture.md`
- Key insight: Focus on shared store + proxy pattern

**What we're building in MVP**
- Start with: `features/mvp-scope.md`
- Then read: `features/implementation-roadmap.md`
- Reference: `architecture/components.md` for detailed breakdown

**How pflow uses pocketflow**
- **Must read**: `architecture/pflow-pocketflow-integration-guide.md`
- This prevents common implementation mistakes

**PocketFlow architecture decision**
- **Decision record**: `architecture/adr/001-use-pocketflow-for-orchestration.md`
- Key insight: ONLY Task 17 (Natural Language Planner) uses PocketFlow internally
- All other components use traditional Python patterns
- Focused approach: Use PocketFlow only where complex orchestration adds real value

**The data flow between nodes**
- Primary: `core-concepts/shared-store.md`
- Supporting: `core-concepts/schemas.md` (section on mappings)

**How to implement a node**
- Guide: `reference/node-reference.md`
- Principles: `features/simple-nodes.md`
- Examples: Any file in `core-node-packages/`

**The CLI syntax and behavior**
- Reference: `reference/cli-reference.md`
- Integration: `features/cli-runtime.md`
- Shell support: `features/shell-pipes.md`

**Natural language planning**
- Specification: `features/planner.md`
- Context: `features/workflow-analysis.md` (why we need it)

## Document Categories

### 🎯 Start Here (Core Understanding)
1. `prd.md` - Vision and core concepts
2. `architecture/pflow-pocketflow-integration-guide.md` - Critical patterns
3. `features/mvp-scope.md` - What we're building now

### 📐 Architecture Documents
- System design and component relationships
- How pieces fit together
- Design decisions and rationale

### 🧩 Core Concepts
- Fundamental patterns that everything builds on
- Shared store, schemas, registry, runtime
- Read these before implementing features

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
1. `prd.md` (sections 1-3)
2. `architecture/architecture.md`
3. `core-concepts/shared-store.md`
4. `architecture/pflow-pocketflow-integration-guide.md`

### For Implementing Nodes
1. `features/simple-nodes.md`
2. `reference/node-reference.md`
3. `core-concepts/shared-store.md`
4. Pick relevant `core-node-packages/*.md`

### For CLI Development
1. `reference/cli-reference.md`
2. `features/cli-runtime.md`
3. `features/shell-pipes.md`
4. `core-concepts/runtime.md`

### For Natural Language Features
1. `features/workflow-analysis.md` (context)
2. `features/planner.md`
3. `core-concepts/schemas.md`

## Key Document Relationships

```
prd.md
├─> architecture/architecture.md
│   ├─> core-concepts/shared-store.md
│   ├─> core-concepts/schemas.md
│   └─> architecture/pflow-pocketflow-integration-guide.md
├─> features/mvp-scope.md
│   └─> features/implementation-roadmap.md
└─> reference/cli-reference.md
    ├─> features/cli-runtime.md
    └─> features/shell-pipes.md
```

## Important Notes

### Single Source of Truth
Each concept has ONE canonical document. Other documents link to it rather than duplicating content. If you see the same concept explained in multiple places, find the canonical source.

### MVP vs Future
Many documents describe both MVP and future features. Look for:
- "MVP:" or "v0.1" tags for current scope
- "v2.0" or "Future:" for post-MVP features
- Check `features/mvp-scope.md` when uncertain

### Prerequisites
Some documents assume knowledge from others:
- All implementation docs assume you've read `architecture/pflow-pocketflow-integration-guide.md`
- Node docs assume you understand the shared store pattern
- CLI docs build on the architecture overview

---

**Quick Tip**: Use `index.md` to see what's IN each file. Use this guide to understand WHEN and WHY to read each file.
