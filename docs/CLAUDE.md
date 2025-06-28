# pflow Documentation Guide for AI Assistants

> **Purpose**: This guide helps AI assistants navigate pflow documentation and understand where to find information about key concepts. For detailed file descriptions to discover specific information, see [index.md](./index.md).

## Quick Start for Implementation

1. **Read Foundation**:
   - `pocketflow/__init__.py` - The entire 100-line framework
   - Understanding this file is **mandatory** before any implementation

2. **Read Integration Guide**:
   - `docs/architecture/pflow-pocketflow-integration-guide.md` - Critical insights
   - This prevents common mistakes and clarifies the pflow-pocketflow relationship

3. **See Implementation Examples** below for where to find information about key concepts for different features.

## Repository Structure for Implementation

```
pflow/
├── docs/                   # pflow documentation
│   ├── CLAUDE.md           # This file - AI navigation guide
│   ├── index.md            # Detailed file inventory
│   ├── prd.md              # Product Requirements Document
│   ├── reference/          # Authoritative specifications
│   ├── core-concepts/      # Fundamental patterns
│   ├── architecture/       # System design documents
│   ├── features/           # Feature specifications
│   │   └── implementation-roadmap.md  # Development phases
│   ├── core-node-packages/ # Platform node specifications
│   ├── implementation-details/  # Detailed implementation guides
│   └── future-version/     # Post-MVP features
```

## Critical Warnings for AI Implementation

### ⚠️ DO NOT:
1. **Reimplement pocketflow functionality** - Use it as a library
2. **Modify pocketflow source code** - It's a dependency
3. **Create new orchestration patterns** - Use pocketflow's Flow
4. **Build custom retry/error handling** - pocketflow handles this
5. **Implement async in MVP** - Explicitly excluded from scope

### ✅ DO:
1. **Read pocketflow source first** - It's only 100 lines
2. **Check pocketflow cookbook** - 40+ examples available
3. **Extend pocketflow classes** - Don't wrap unnecessarily
4. **Follow simple node principle** - One node, one purpose
5. **Use shared store pattern** - All communication through store

## Navigation Patterns

### When You Need To:

**Understand a Concept**:
1. Check if pocketflow has documentation for it
2. Read pflow's extension/specification of that concept
3. Look for examples in pocketflow cookbook
4. Review accumulated knowledge in `.taskmaster/knowledge/`

**Implement a Feature**:
1. Find it in the implementation order above
2. Read all prerequisites first
3. Check feature-to-pattern mapping
4. Read pflow specifications
5. Reference pocketflow examples

**Debug an Issue**:
1. Check if it's a pocketflow pattern issue
2. Review integration guide for common mistakes
3. Ensure you're extending, not reimplementing

## Key Documents by Purpose

### Architecture & Design:
- `docs/prd.md` - Product vision (skip technical details)
- `docs/architecture/architecture.md` - System architecture
- `docs/architecture/pflow-pocketflow-integration-guide.md` - **Critical**

### Implementation Specs:
- `docs/reference/node-reference.md` - Node implementation
- `docs/reference/cli-reference.md` - CLI syntax
- `docs/reference/execution-reference.md` - Runtime behavior

### Core Patterns:
- `docs/core-concepts/shared-store.md` - Communication
- `docs/features/simple-nodes.md` - Node design
- `docs/core-concepts/schemas.md` - Data formats

### Feature Specs:
- `docs/features/planner.md` - Natural language
- `docs/features/cli-runtime.md` - CLI integration
- `docs/features/mvp-scope.md` - What's in/out of scope

## Next Steps

1. **Start with Phase 1** - Foundation is critical
2. **Read pocketflow examples** - Learn patterns by example
3. **Implement incrementally** - Each phase builds on previous
4. **Test with pocketflow patterns** - Reuse their test approaches
5. **Ask for clarification** - When pflow extends pocketflow in unclear ways

---

For detailed documentation about each file's contents and purpose, see [index.md](./index.md).

For the complete pocketflow documentation inventory, see `pocketflow/CLAUDE.md`.

*When extending this documentation, always follow the single-source-of-truth principle. Each concept has one canonical document, with other documents linking to it rather than duplicating content.*
