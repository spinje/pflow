# pflow Documentation Repository Map & Inventory

## Overview
The pflow documentation consists of **26 markdown files** totaling approximately **13,900 lines** of comprehensive specifications, architecture documents, and implementation guides.

## Directory Structure
```
docs/
├── core-node-packages/          # Platform-specific node specifications (4 files)
├── implementation-details/      # Technical implementation guides (2 files)
├── future-version/             # Post-MVP feature specifications (2 files)
└── [root level docs]           # Core architecture and patterns (16 files)
```

## Documentation Categories

### 1. Core Architecture Documents (3 files, ~3,175 lines)

#### **prd.md** - Product Requirements Document (Master Edition)
- **Size**: ~2,100 lines
- **Purpose**: Master product vision, strategic positioning, complete architecture
- **Key Content**:
  - Vision & strategic positioning
  - Core concepts (shared store, natural interfaces, proxy mapping)
  - Dual-mode planning architecture
  - Complete glossary and diagrams
  - Implementation roadmap through v3.0
- **Status**: Foundational reference document

#### **architecture.md** - MVP-Focused Architecture
- **Size**: ~800 lines
- **Purpose**: Technical architecture for v0.1 MVP implementation
- **Key Content**:
  - System overview & component architecture
  - Template resolution system
  - CLI resolution algorithm
  - Security & trust model
  - Technical decisions & rationale
- **Status**: Primary implementation guide

#### **mvp-scope.md** - MVP Boundaries & Vision
- **Size**: ~275 lines
- **Purpose**: Clear MVP scope definition and success criteria
- **Key Content**:
  - "Plan Once, Run Forever" philosophy
  - Slash command inefficiency problem
  - 8 critical MVP dependencies
  - 4-phase implementation plan
  - Success metrics (10x efficiency target)
- **Status**: Scope control document

### 2. Core Pattern Documents (3 files, ~1,607 lines)

#### **shared-store.md**
- **Size**: ~575 lines
- **Purpose**: Core architectural pattern for node communication
- **Key Content**:
  - Shared store & NodeAwareSharedStore proxy
  - Node autonomy principle
  - Template variables system
  - Progressive complexity examples
- **Status**: Critical pattern specification

#### **simple-nodes.md**
- **Size**: ~333 lines
- **Purpose**: Simple, single-purpose node architecture
- **Key Content**:
  - Single-purpose node philosophy
  - Smart exception (general llm node)
  - Comprehensive node inventory table
  - MCP alignment strategy
- **Status**: Node design pattern

#### **cli-runtime.md**
- **Size**: ~699 lines
- **Purpose**: Runtime specification for CLI execution
- **Key Content**:
  - "Type flags; engine decides" principle
  - Complete execution pipeline (7 steps)
  - CLI scenarios with examples
  - Validation rules and best practices
- **Status**: Execution specification

### 3. System Component Documents (6 files, ~2,879 lines)

#### **planner.md**
- **Size**: ~1,069 lines
- **Purpose**: Dual-mode planner specification
- **Key Content**:
  - Natural language & CLI pipe paths
  - Template string composition
  - Type shadow store
  - LLM integration patterns
- **Status**: Core component specification

#### **runtime.md**
- **Size**: ~300 lines
- **Purpose**: Execution safety and optimization
- **Key Content**:
  - @flow_safe decorator
  - Caching strategy
  - Error handling
  - Testing framework
- **Status**: Runtime behavior specification

#### **registry.md**
- **Size**: ~410 lines
- **Purpose**: Node discovery and versioning
- **Key Content**:
  - Identifier syntax & naming conventions
  - Version resolution policies
  - File system layout
  - Lockfile types
- **Status**: Registry system specification

#### **components.md**
- **Size**: ~489 lines
- **Purpose**: Complete component inventory
- **Key Content**:
  - MVP vs v2.0 component breakdown
  - Built-in simple nodes list (30+ nodes)
  - Implementation priorities
  - Critical dependencies
- **Status**: Component reference

#### **schemas.md**
- **Size**: ~599 lines
- **Purpose**: JSON schema governance
- **Key Content**:
  - Flow IR schema
  - Node metadata schema
  - Validation pipeline
  - Schema evolution strategy
- **Status**: Data format specification

### 4. Node Package Specifications (4 files, ~1,580 lines)

#### **claude-nodes.md**
- **Size**: ~300 lines
- **Purpose**: Claude Code AI development super node
- **Key Content**: Single comprehensive development node with template-driven prompts
- **Status**: High priority implementation

#### **github-nodes.md**
- **Size**: ~550 lines
- **Purpose**: GitHub platform integration nodes
- **Key Content**: 8 simple nodes for issues, PRs, and repository operations
- **Status**: High priority implementation

#### **ci-nodes.md**
- **Size**: ~450 lines
- **Purpose**: CI/CD platform integration
- **Key Content**: 5 nodes with multi-platform support and auto-detection
- **Status**: Medium priority implementation

#### **llm-nodes.md**
- **Size**: ~280 lines
- **Purpose**: General text processing node
- **Key Content**: Smart exception to simple nodes pattern
- **Status**: High priority implementation

### 5. Integration & Analysis Documents (4 files, ~1,347 lines)

#### **workflow-analysis.md**
- **Size**: ~244 lines
- **Purpose**: Technical analysis of AI workflow inefficiencies
- **Key Content**: Comparison of slash commands vs pflow workflows
- **Status**: Foundational analysis

#### **shell-pipes.md**
- **Size**: ~79 lines
- **Purpose**: Unix pipe integration specification
- **Key Content**: stdin support and shared["stdin"] reserved key
- **Status**: MVP feature

#### **mcp-integration.md**
- **Size**: ~769 lines
- **Purpose**: Model Context Protocol integration
- **Key Content**: MCP wrapper nodes and unified registry
- **Status**: v2.0 feature

#### **pflow-pocketflow-integration-guide.md**
- **Size**: ~255 lines
- **Purpose**: Critical integration guidance
- **Key Content**: What NOT to build, direct pocketflow usage
- **Status**: Critical implementation guide

### 6. `docs/implementation-details` (2 files, ~1,486 lines)

#### **metadata-extraction.md**
- **Size**: ~1,136 lines
- **Purpose**: Node metadata extraction infrastructure
- **Key Content**: Docstring parsing, registry integration, validation
- **Status**: MVP infrastructure

#### **autocomplete-impl.md**
- **Size**: ~350 lines
- **Purpose**: CLI autocomplete implementation
- **Key Content**: Shell integration, context-aware suggestions
- **Status**: v2.0 enhancement

### 7. `docs/future-version` (2 files, ~1,044 lines)

#### **json-extraction.md**
- **Size**: ~665 lines
- **Purpose**: Advanced JSON transformation
- **Key Content**: JSON path syntax, automatic extraction
- **Status**: v3.0 feature (with concerns)

#### **llm-node-gen.md**
- **Size**: ~379 lines
- **Purpose**: AI-assisted node development
- **Key Content**: LLM generates code + documentation
- **Status**: v3.0+ developer tooling

## Documentation Statistics

### By Priority
- **MVP Critical**: 11 files (~7,450 lines)
  - Core architecture (3), patterns (3), critical components (3), integration guides (2)
- **MVP Supporting**: 7 files (~3,950 lines)
  - Node packages (4), component docs (3)
- **Post-MVP**: 6 files (~2,200 lines)
  - v2.0 features (3), v3.0+ features (3)

### By Content Type
- **Architecture & Design**: 6 files (~4,782 lines)
- **Component Specifications**: 6 files (~2,879 lines)
- **Node Packages**: 4 files (~1,580 lines)
- **Implementation Guides**: 5 files (~2,833 lines)
- **Feature Specifications**: 4 files (~1,838 lines)

### Key Documentation Themes

1. **Shared Store Pattern**: Central to 8+ documents
2. **Simple Nodes Philosophy**: Drives node package design
3. **Template System**: Integrated across planner and runtime
4. **MVP Focus**: Clear boundaries in 12+ documents
5. **PocketFlow Integration**: Referenced in 15+ documents
6. **Natural Interfaces**: Consistent pattern across all nodes
7. **Deterministic Execution**: Core principle throughout

## Documentation Quality Assessment

### Excellent Coverage
- Core architecture and patterns
- Node package specifications
- Integration patterns
- MVP scope and boundaries

### Good Coverage
- System components
- Implementation details
- Future version planning

### Needs Attention
- Cross-document linking could be improved

## Recommended Reading Order

### For Understanding pflow
1. workflow-analysis.md - Problem statement
2. mvp-scope.md - Solution vision
3. prd.md - Complete architecture
4. architecture.md - Technical implementation

### For Implementation
1. pflow-pocketflow-integration-guide.md - Critical guidance
2. shared-store.md - Core pattern
3. simple-nodes.md - Node design
4. cli-runtime.md - Execution model
5. components.md - What to build

### For Specific Components
- **Planner**: planner.md + schemas.md
- **Registry**: registry.md + metadata-extraction.md
- **Nodes**: core-node-packages/* + simple-nodes.md
- **Runtime**: runtime.md + cli-runtime.md

This comprehensive documentation provides a solid foundation for implementing pflow's MVP while maintaining clear vision for future expansion.
