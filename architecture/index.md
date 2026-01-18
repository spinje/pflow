# pflow Documentation Inventory for AI Agents

> **Purpose**: This document (`architecture/index.md`) provides a comprehensive file-by-file inventory of all `pflow` documentation.

> **Other documentation**: Note that the documentation for `pocketflow` is in the `pocketflow/docs` folder. For a complete understanding of the foundation `pflow` should be built on, reading the relevant documentation for `pocketflow` is strongly recommended.

## How to Use This Inventory

This inventory describes **what's inside each documentation file** to help AI agents quickly locate specific information. Each entry includes:
- **Purpose**: What questions/problems the document addresses
- **Key Contents**: Main topics and sections covered
- **Critical Insights**: Warnings, anti-patterns, or must-know information
- **When to Use**: Specific scenarios requiring this document
- **Status**: MVP/v2.0/v3.0 indicator where applicable

> If you are an AI agent, you can use this inventory to see what documentation is available and use that to determine what to read next. Remember, only read the documentation that is relevant to the task at hand to not overwhelm yourself and your context window.

## Root Documentation Files

### [CLAUDE.md](./CLAUDE.md)
**Purpose**: Documentation navigation guide helping AI assistants quickly find the information they need within the docs directory.

**Key Contents**:
- Complete documentation structure map
- Navigation by purpose ("I need to understand...")
- Document categories with visual indicators
- Suggested reading paths for different goals
- Key document relationships diagram
- Prerequisites and single source of truth notes

**Critical Insights**:
- Complements index.md - CLAUDE.md shows WHEN/WHY to read files
- Groups documentation by use case and purpose
- Provides reading sequences for common tasks
- Highlights MVP vs future version distinctions

**When to Use**: Finding relevant documentation, understanding reading order, navigating by task/purpose

---

### index.md
**Purpose**: This file - comprehensive inventory of all documentation files for AI agents.

**When to Use**: Finding specific documentation topics, understanding file contents, navigating documentation structure

## Architecture Directory (Root Level)

### [architecture.md](./architecture.md)
**Purpose**: Current system architecture document reflecting the actual implemented system.

**Key Contents**:
- Execution pipeline overview
- Key abstractions (shared store, wrapper chain, templates)
- Node system and registry
- MCP integration (fully implemented)
- Self-healing workflows
- CLI interface and configuration

**Critical Insights**:
- Accurately reflects current codebase
- MCP integration is complete (stdio + http transports)
- Shared store uses namespaced pattern
- Wrapper chain: Instrumented → Batch → Namespaced → TemplateAware → Node

**When to Use**: Understanding current system, designing new features, accurate architecture reference

**Status**: ✅ Current (Accurate)

---

### [pflow-pocketflow-integration-guide.md](./pflow-pocketflow-integration-guide.md)
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

## Historical Documents (`/historical/`)

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

## Core Concepts Directory (`/core-concepts/`)

### [shared-store.md](./core-concepts/shared-store.md)
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

---

> **Note**: The Core Concepts directory now contains only `shared-store.md`. Previously included documents have been moved:
> - **schemas.md** → moved to `reference/ir-schema.md` (it's a spec, not a concept)
> - **registry.md** → merged into `architecture.md#node-naming`
> - **runtime.md** → moved to `.taskmaster/feature-dump/` (mostly unimplemented future features)

## Features Directory (`/features/`)

### [simple-nodes.md](./features/simple-nodes.md)
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

### [shell-pipes.md](./features/shell-pipes.md)
**Purpose**: Native Unix shell pipe integration for seamless command-line workflows.

**Key Contents**:
- Motivation for shell pipe support
- How piped content populates `shared["stdin"]`
- Integration with CLI and natural language flows
- Similarity to llm CLI patterns
- Trace and cache handling

**Critical Insights**:
- Reserved key `shared["stdin"]` for all piped input
- Nodes check stdin as fallback or planner creates mapping
- Piped content hashed for reproducibility
- Preserves all pflow guarantees

**When to Use**: Implementing stdin detection, Unix integration, handling piped input

**Status**: ✅ MVP

## Reference Directory (`/reference/`)

### [ir-schema.md](./reference/ir-schema.md)
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

## Core Node Packages Directory (`/core-node-packages/`)

### [claude-nodes.md](./core-node-packages/claude-nodes.md)
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

### [llm-nodes.md](./core-node-packages/llm-nodes.md)
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

## Implementation Details Directory (`/implementation-details/`)

### [metadata-extraction.md](./implementation-details/metadata-extraction.md)
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

## Vision Directory (`/vision/`)

> **Warning**: These documents describe potential FUTURE directions, NOT current implementation.

### [README.md](./vision/README.md)
**Purpose**: Context and caveats for vision documents.

**Key Contents**:
- Document overview table
- Key reality checks for AI agents
- Links to authoritative current documentation

**When to Use**: Before reading any vision document

---

### [AI-Agents-Need-Hands.md](./vision/AI-Agents-Need-Hands.md)
**Purpose**: Marketing vision for the value proposition of pflow workflows.

**Critical Insights**:
- Vision document - may present implemented features as future possibilities
- Useful for understanding "why pflow exists"

**Status**: ⚠️ Vision (not current implementation)

---

### [mcp-as-extension-api.md](./vision/mcp-as-extension-api.md)
**Purpose**: Future vision for MCP-only extension philosophy.

**Critical Insights**:
- Current pflow uses hybrid approach (platform nodes + MCP)
- This vision may not be fully realized

**Status**: ⚠️ Vision (not current implementation)

---

### [north-star-examples.md](./vision/north-star-examples.md)
**Purpose**: Planner demonstration examples showing aspirational workflows.

**Critical Insights**:
- Uses `>>` CLI syntax that was never implemented
- The planner is now labeled "legacy"
- Useful for understanding design intent

**Status**: ⚠️ Vision (not current implementation)

## Best Practices Directory (`/best-practices/`)

### [testing-quick-reference.md](./best-practices/testing-quick-reference.md)
**Purpose**: Quick reference for testing patterns and practices in pflow.

**When to Use**: Writing tests, understanding test patterns

**Status**: ✅ Current

## Navigation Tips for AI Agents

1. **Starting Implementation** (pflow development): Read [architecture.md](./architecture.md) → [pflow-pocketflow-integration-guide.md](./pflow-pocketflow-integration-guide.md)
2. **Understanding Project Status**: Check root `CLAUDE.md` for authoritative project status
3. **Writing New Nodes**: Read [pflow-pocketflow-integration-guide.md](./pflow-pocketflow-integration-guide.md) → [simple-nodes.md](./features/simple-nodes.md) → [enhanced-interface-format.md](./reference/enhanced-interface-format.md)
4. **Building Workflows** (users/agents): Use JSON workflows via CLI - see `pflow instructions usage`
5. **Understanding Patterns**: [shared-store.md](./core-concepts/shared-store.md) is most referenced and central to architecture
6. **Historical Context**: [historical/](./historical/) contains design-time documents - valuable for "why" but may be outdated

## Document Status Legend

- ✅ **Current/Implemented**: Accurate and up-to-date
- ✅ **MVP**: Required for v0.1 (now complete)
- ⚠️ **Historical**: Design-time document, may be outdated
- ❌ **v2.0/v3.0**: Future versions
