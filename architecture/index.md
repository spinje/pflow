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
- Wrapper chain: Instrumented → Namespaced → TemplateAware → Node

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

### [runtime-components.md](./runtime-components.md)
**Purpose**: Explains the distinction between user-facing nodes and internal runtime components.

**Key Contents**:
- User-facing nodes vs runtime components
- WorkflowExecutor as example runtime component
- Design principles for separation
- Guidelines for adding new components

**Critical Insights**:
- Users work with nodes; runtime makes them work
- Runtime components have special privileges
- Clear boundaries: nodes in `nodes/`, runtime in `runtime/`

**When to Use**: Understanding internal architecture, adding new runtime features

**Status**: ✅ Current

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
> - **runtime.md** → moved to `future-version/flow-safe-caching.md` (mostly unimplemented)

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

### [planner.md](./features/planner.md)
**Purpose**: Central validation and IR generation engine for both natural language and CLI inputs.

**Key Contents**:
- Dual-mode operation (NL with LLM vs CLI validation-only)
- Template string composition and variable flow
- **"Find or Build" pattern for semantic workflow discovery**
- Metadata extraction from docstrings
- Validation framework with "early and often" principle
- Integration with shared store and proxy

**Critical Insights**:
- Template-driven approach: LLM generates `${variable}` placeholders
- Planner is normal pocketflow flow, not hard-coded
- Both paths use same infrastructure
- Critical stages: Intent → Template → Selection → Validation
- Type shadow store deferred to v2.0

**When to Use**: Implementing natural language planning, CLI validation, understanding compilation

**Status**: ✅ MVP (built after core)

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

---

### [workflow-analysis.md](./features/workflow-analysis.md)
**Purpose**: Technical analysis comparing inefficient AI slash commands with deterministic workflows.

**Key Contents**:
- Analysis of Anthropic's slash command pattern
- Hidden costs of repeated reasoning
- Detailed fix-github-issue transformation
- Token usage and execution comparisons
- When to use each approach

**Critical Insights**:
- Core: AI intelligence better for tasks than orchestration
- claude-code receives comprehensive planner instructions
- 10x improvement possible (1000-2000 tokens → minimal)
- Template-driven preserves context without overhead
- Middle ground: Start with slash commands, codify patterns

**When to Use**: Understanding value proposition, seeing workflow examples, explaining benefits

**Status**: ✅ MVP

---

### [debugging.md](./features/debugging.md)
**Purpose**: Comprehensive guide to planner debugging capabilities including progress indicators, trace files, and troubleshooting.

**Key Contents**:
- Real-time progress indicators
- Trace file structure and analysis
- CLI flags (--no-trace, --planner-timeout)
- LLM call capture and inspection
- Common debugging scenarios
- Troubleshooting guide

**Critical Insights**:
- Progress indicators always displayed during planning
- Traces automatically saved on failure
- All LLM prompts/responses captured
- Path A (reuse) vs Path B (generate) tracking
- Timeout detection with automatic trace saving

**When to Use**: Debugging failed workflow generation, optimizing prompts, performance analysis, understanding planner decisions

**Status**: ✅ MVP

---

### [mcp-integration.md](./features/mcp-integration.md)
**Purpose**: Specification for Model Context Protocol integration (now implemented).

**Key Contents**:
- Unified registry approach
- Wrapper node generation
- Natural interface mapping
- Error handling and transport
- Complete integration examples

**Critical Insights**:
- MCP is FULLY IMPLEMENTED (stdio + http transports)
- MCPNode executes any MCP tool in workflows
- pflow-as-MCP-server exposes 11 tools for AI agents
- Supports authentication for http transport

**When to Use**: Understanding MCP integration, using MCP tools in workflows, exposing pflow to AI agents

**Status**: ✅ Implemented

## Reference Directory (`/reference/`)

### [cli-reference.md](./reference/cli-reference.md)
**Purpose**: Authoritative CLI interface reference with syntax, operators, and composition.

**Key Contents**:
- Basic syntax and grammar definition
- `>>` operator vs shell pipes (`|`)
- Flag resolution algorithm
- Template variables and resolution
- Shell pipe integration

**Critical Insights**:
- "Type flags; engine decides" philosophy
- Nodes should check `stdin` as fallback
- `>>` passes structured data, not text streams
- Flows are fail-fast by default
- Template variables check shared store first

**When to Use**: Implementing CLI parsing, flag handling, shell integration, user interaction

**Status**: ✅ MVP

---

### [execution-reference.md](./reference/execution-reference.md)
**Purpose**: Authoritative execution model and runtime behavior reference.

**Key Contents**:
- Static execution model (immutable flows)
- 7-step execution pipeline
- Node safety model with `@flow_safe`
- Error categorization by namespace
- Retry mechanisms

**Critical Insights**:
- Opt-in purity model - explicit `@flow_safe` for caching
- Flows completely static - no dynamic topology
- Only transient errors retryable
- Multiple validation levels
- Execution context provides debugging hooks

**When to Use**: Implementing runtime engine, error handling, caching, execution flow

**Status**: ✅ MVP

---

### [node-reference.md](./reference/node-reference.md)
**Purpose**: Common patterns and best practices for node implementation consistency.

**Key Contents**:
- Check shared store first pattern
- Node lifecycle implementation
- Error handling guidelines
- Testing patterns
- Documentation requirements

**Critical Insights**:
- Shared store priority over params for dynamic data
- Clear interface documentation required
- All nodes inherit from `pocketflow.Node`
- Comprehensive tests verify functionality and priority
- Specific error messages for missing values

**When to Use**: Before implementing ANY node, ensuring consistency, following patterns

**Status**: ✅ MVP

---

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

---

### [simonw-llm-patterns/FINAL-ANALYSIS.md](./implementation-details/simonw-llm-patterns/FINAL-ANALYSIS.md)
**Purpose**: Analysis of Simon Willison's llm library patterns and their alignment with pflow architecture.

**Key Contents**:
- Core architecture alignment with pocketflow lifecycle
- Eight specific pattern recommendations from llm library
- Integration architecture (wrapper pattern)
- Benefits of adoption (CLI polish, plugins, proven patterns)
- Implementation priority recommendations

**Critical Insights**:
- `llm` library fits perfectly in exec() phase of nodes
- Wrapper pattern preserves pocketflow architecture
- Default command pattern ideal for pflow CLI
- Plugin ecosystem provides immediate value
- All patterns respect prep/exec/post separation

**When to Use**: Understanding llm library integration, implementing LLM nodes, CLI design decisions

**Status**: ✅ MVP

---

### [simonw-llm-patterns/IMPLEMENTATION-GUIDE.md](./implementation-details/simonw-llm-patterns/IMPLEMENTATION-GUIDE.md)
**Purpose**: Concrete implementation guide for integrating llm library patterns into pflow tasks.

**Key Contents**:
- Quick start checklist with dependencies
- Task-specific implementations for each pflow task
- LLMNode wrapper implementation example
- Template system integration
- Database and plugin configuration

**Critical Insights**:
- Provides task-by-task integration examples
- Shows how to wrap llm library in pocketflow nodes
- Demonstrates respecting architectural boundaries
- Includes testing approaches
- Maps llm features to pflow requirements

**When to Use**: Implementing LLM functionality, following integration patterns, task implementation

**Status**: ✅ MVP

## Future Version Directory (`/future-version/`)

### [flow-safe-caching.md](./future-version/flow-safe-caching.md)
**Purpose**: Defines caching strategy and node safety model with `@flow_safe` decorator.

**Key Contents**:
- Side-effect declaration and node safety
- Node classification (impure default vs pure)
- Caching strategy and eligibility
- Cache key computation and storage
- Retry mechanisms and safety

**Critical Insights**:
- Opt-in purity model - all nodes impure unless `@flow_safe`
- Only `@flow_safe` nodes can be cached or retried
- Cache key: node hash + params + input data hash
- No need to enumerate side effects - only certify purity
- Caching respects proxy mappings

**When to Use**: Implementing caching, designing retryable nodes, using `@flow_safe`, debugging cache behavior

**Status**: ❌ v2.0+ (Not implemented)

---

### [json-extraction.md](./future-version/json-extraction.md)
**Purpose**: v3.0 feature for automatic JSON field extraction (with critical concerns).

**Key Contents**:
- JSON path syntax and mapping extensions
- Planner integration for structure detection
- Enhanced proxy implementation
- Performance optimization
- **Section 13: Critical Analysis**

**Critical Insights**:
- WARNING: Section 13 questions feature alignment with philosophy
- Would violate "explicit over magic" principle
- Increases complexity beyond the minimal framework ideal
- Recommendation: Use explicit JSON nodes instead

**When to Use**: Evaluating JSON processing approaches, understanding design trade-offs

**Status**: ❌ v3.0 (May be abandoned)

---

### [llm-node-gen.md](./future-version/llm-node-gen.md)
**Purpose**: v3.0 capability for LLM-assisted node development enhancing productivity.

**Key Contents**:
- LLM-assisted generation workflows
- Future CLI commands
- Metadata infrastructure integration
- Quality assurance processes
- System prompts

**Critical Insights**:
- LLM assists but does NOT replace static ecosystem
- All generated nodes require human review
- Builds on metadata infrastructure
- Emphasizes code + documentation consistency
- Static nodes remain foundation

**When to Use**: Planning developer tooling, understanding AI-enhanced development

**Status**: ❌ v3.0

---

### [registry-versioning.md](./future-version/registry-versioning.md)
**Purpose**: Planned node namespacing and versioning system for future registry evolution.

**Key Contents**:
- Namespace + name + semver syntax (`<namespace>/<name>@<semver>`)
- Version resolution strategies
- Migration path from current simple naming
- Compatibility considerations

**When to Use**: Planning future registry enhancements, understanding namespacing design

**Status**: ❌ v2.0+ (Not implemented)

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
3. **Writing New Nodes**: Read [pflow-pocketflow-integration-guide.md](./pflow-pocketflow-integration-guide.md) → [simple-nodes.md](./features/simple-nodes.md) → [node-reference.md](./reference/node-reference.md)
4. **Building Workflows** (users/agents): Use JSON workflows via CLI - see `pflow instructions usage`
5. **Understanding Patterns**: [shared-store.md](./core-concepts/shared-store.md) is most referenced and central to architecture
6. **Historical Context**: [historical/](./historical/) contains design-time documents - valuable for "why" but may be outdated

## Document Status Legend

- ✅ **Current/Implemented**: Accurate and up-to-date
- ✅ **MVP**: Required for v0.1 (now complete)
- ⚠️ **Historical**: Design-time document, may be outdated
- ❌ **v2.0/v3.0**: Future versions
