# pflow Documentation Guide for AI Assistants

> **Purpose**: This guide helps AI assistants navigate pflow documentation and understand the implementation order. For detailed file descriptions, see [index.md](./index.md).

## Quick Start for Implementation

1. **Read Foundation** (5 mins):
   - `pocketflow/__init__.py` - The entire 100-line framework
   - Understanding this file is **mandatory** before any implementation

2. **Read Integration Guide** (10 mins):
   - `docs/architecture/pflow-pocketflow-integration-guide.md` - Critical insights
   - This prevents common mistakes and clarifies the pflow-pocketflow relationship

3. **Follow Implementation Order** below

## Repository Structure for Implementation

```
pflow/
├── pocketflow/              # Foundation framework (DO NOT MODIFY)
│   ├── __init__.py         # ⭐ 100-line framework - READ FIRST
│   ├── CLAUDE.md           # Complete pocketflow documentation inventory
│   ├── docs/               # Conceptual documentation
│   └── cookbook/           # 40+ examples to reference
│
├── src/pflow/              # Main implementation directory
│   └── [TO BE BUILT]       # Your implementation goes here
│
├── docs/                   # pflow documentation
│   ├── CLAUDE.md           # This file - AI navigation guide
│   ├── index.md            # Detailed file inventory
│   ├── reference/          # Authoritative specifications
│   ├── core-concepts/      # Fundamental patterns
│   ├── architecture/       # System design documents
│   ├── features/           # Feature specifications
│   └── core-node-packages/ # Platform node specifications
│
├── tests/                  # Test suite
├── CLAUDE.md              # Root-level AI guidance
└── pyproject.toml         # Dependencies and configuration
```

## Implementation Order & Prerequisites Examples

This is a suggested implementation order with examples on how to think when considering documentation to read before implementing or extending a feature. For a more detailed implementation order with a complete list of tasks, see `todo/tasks.json`.

### Phase 1: Foundation Components

#### 1.1 Shared Store Extensions
- **Prerequisites**:
  - `pocketflow/__init__.py` - Understand the base SharedStore class
  - `pocketflow/docs/core_abstraction/communication.md` - Communication patterns
- **pflow Specifications**:
  - `docs/core-concepts/shared-store.md` - Natural interfaces and proxy pattern
  - `docs/reference/execution-reference.md` - Runtime behavior
- **Key Examples**:
  - `pocketflow/cookbook/basic/01_hello_world.py` - Basic shared store usage
  - `pocketflow/cookbook/advanced/flow_in_flow.py` - Nested contexts
- **Implementation Note**: Extend pocketflow's SharedStore, don't replace it

#### 1.2 Basic Node System
- **Prerequisites**:
  - `pocketflow/docs/core_abstraction/computation.md` - Node lifecycle
  - `pocketflow/docs/guide.md` - Agentic coding patterns
- **pflow Specifications**:
  - `docs/reference/node-reference.md` - Complete implementation guide
  - `docs/features/simple-nodes.md` - Design philosophy
- **Key Examples**:
  - `pocketflow/cookbook/basic/03_share_data.py` - Data sharing patterns
  - `pocketflow/cookbook/building_blocks/custom_node.py` - Custom node creation

### Phase 2: CLI & Parser

#### 2.1 CLI Command Structure
- **Prerequisites**:
  - Understanding of Click framework (see pyproject.toml)
  - `pocketflow/cookbook/basic/02_chain_flow.py` - Flow chaining
- **pflow Specifications**:
  - `docs/reference/cli-reference.md` - Complete syntax specification
  - `docs/features/cli-runtime.md` - Runtime integration
- **Implementation Note**: CLI should parse to pocketflow Flow objects

#### 2.2 Pipe Syntax Parser
- **Prerequisites**:
  - `pocketflow/docs/core_abstraction/orchestration.md` - Flow patterns
- **pflow Specifications**:
  - `docs/features/shell-pipes.md` - Unix pipe integration
  - `docs/core-concepts/schemas.md` - JSON IR format
- **Key Pattern**: Transform CLI syntax → JSON IR → pocketflow Flow

### Phase 3: Registry & Discovery

#### 3.1 Node Registry
- **Prerequisites**:
  - `pocketflow/cookbook/building_blocks/` - Various node patterns
- **pflow Specifications**:
  - `docs/core-concepts/registry.md` - Discovery and versioning
  - `docs/implementation-details/metadata-extraction.md` - Metadata system
- **Implementation Note**: Registry wraps pocketflow nodes with metadata

### Phase 4: Core Nodes (Week 4)

#### 4.1 Platform Nodes
- **Prerequisites**:
  - All Phase 1-3 components working
  - `pocketflow/cookbook/llm_powered/` - LLM integration patterns
- **pflow Specifications**:
  - `docs/core-node-packages/llm-nodes.md` - Text processing
  - `docs/core-node-packages/github-nodes.md` - GitHub integration
  - `docs/core-node-packages/claude-nodes.md` - Claude CLI wrapper
  - `docs/core-node-packages/ci-nodes.md` - CI/CD integration

### Phase 5: Planner

#### 5.1 Natural Language Compilation
- **Prerequisites**:
  - `pocketflow/docs/design_pattern/agent.md` - Agent patterns
  - `pocketflow/cookbook/llm_powered/03_llm_agent.py` - LLM agent example
- **pflow Specifications**:
  - `docs/features/planner.md` - Dual-mode planner
  - `docs/features/workflow-analysis.md` - Use case analysis

## Feature-to-Pattern Mapping

| pflow Feature | pocketflow Foundation | Key Pattern | Example |
|--------------|---------------------|-------------|---------|
| Shared Store | `SharedStore` class | Extend with natural keys | `pocketflow/cookbook/basic/03_share_data.py` |
| Simple Nodes | `Node` class | Single-purpose wrapper | `pocketflow/cookbook/building_blocks/custom_node.py` |
| Flow Execution | `Flow` class | Direct usage | `pocketflow/cookbook/basic/02_chain_flow.py` |
| CLI Parsing | - | Parse to Flow objects | Create new |
| Node Registry | - | Metadata wrapper | Create new |
| Planner | Agent pattern | LLM-powered planning | `pocketflow/cookbook/llm_powered/03_llm_agent.py` |
| Batch Processing | `BatchNode/BatchFlow` | Direct usage | `pocketflow/cookbook/advanced/batch.py` |

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
