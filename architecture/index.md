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

### [prd.md](./prd.md)
**Purpose**: Master Product Requirements Document defining pflow's complete vision, architecture, and success criteria.

**Key Contents**:
- Vision & strategic positioning with differentiators
- Core concepts (pocketflow foundation, shared store pattern, natural interfaces)
- Planning pipeline architecture (dual-mode operation)
- CLI surface & parameter resolution algorithms
- JSON IR & schema governance, runtime behavior
- MVP acceptance criteria and implementation roadmap
- Comprehensive glossary in Appendix A

**Critical Insights**:
- Emphasizes "Explicit Over Magic" and "Pattern Over Framework Innovation"
- Shared store + proxy pattern is the primary innovation
- All nodes are impure by default; `@flow_safe` must be explicit
- Contains authoritative terminology definitions

**When to Use**: Understanding overall vision, making architectural decisions, ensuring design philosophy alignment, terminology consistency

---

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

## Architecture Directory (`/architecture/`)

### [architecture.md](./architecture/architecture.md)
**Purpose**: Technical architecture document defining the complete system design for pflow v0.1 MVP.

**Key Contents**:
- Executive summary with core value proposition
- High-level system architecture diagram
- Core design patterns (shared store, node autonomy, proxy)
- MVP scope definition with inclusion/exclusion boundaries
- Detailed component architecture for all layers

**Critical Insights**:
- Natural language planning built AFTER core infrastructure (not first)
- Avoid wrapper classes around pocketflow - use directly
- "Type flags; engine decides" principle for CLI resolution
- General-purpose LLM node is "smart exception" to prevent proliferation
- Template resolution enables sophisticated ${variable} workflows

**When to Use**: Starting implementation, designing components, MVP feature decisions, understanding system flow

**Status**: ✅ MVP

---

### [components.md](./architecture/components.md)
**Purpose**: Comprehensive inventory distinguishing MVP (v0.1) components from v2.0 features with implementation checklist.

**Key Contents**:
- Complete MVP component list with subsystem breakdown
- v2.0 feature inventory for future planning
- Critical MVP dependencies (10 required components)
- Implementation priority ordering (4 phases)
- Required simple nodes list

**Critical Insights**:
- Lists exact MVP nodes: GitHub, Claude Code, LLM, CI, Git, File, Shell
- Template Resolution System required for MVP
- Natural language planning depends on CLI + registry + metadata
- Action-based transitions are v2.0 (flow control, not node types)
- claude-code is "super node" for comprehensive AI development

**When to Use**: Planning tasks, checking MVP scope, understanding dependencies, prioritizing work

**Status**: ✅ MVP

---

### [pflow-pocketflow-integration-guide.md](./architecture/pflow-pocketflow-integration-guide.md)
**Purpose**: Critical implementation insights preventing common mistakes when integrating with pocketflow.

**Key Contents**:
- 10 critical insights about integration
- RIGHT vs WRONG code examples
- Clear separation of pocketflow provides vs pflow adds
- Simple patterns for complex-sounding features
- Core architecture summary

**Critical Insights**:
- **#1**: PocketFlow IS the execution engine - don't reimplement
- **#2**: No wrapper classes needed - use pocketflow directly
- **#3**: Shared Store is just a dict - don't over-engineer
- **#4**: Template resolution is simple regex substitution
- **#7**: JSON IR compilation is object instantiation, not code generation
- Lists 10 common traps to avoid

**When to Use**: Before implementing ANY component, avoiding over-engineering, compiling JSON IR, debugging integration

**Status**: ✅ MVP Critical



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

### [schemas.md](./core-concepts/schemas.md)
**Purpose**: JSON schema governance for Flow IR and Node Metadata artifacts.

**Key Contents**:
- Flow IR structure (nodes, edges, mappings, metadata)
- Node metadata schema from docstrings
- Interface declaration rules and types
- Proxy mapping schema for complex flows
- Schema validation and evolution rules

**Critical Insights**:
- Two key artifacts: Flow IR (orchestration) and Node Metadata (interfaces)
- Natural interfaces use `shared["key"]` patterns
- Mapping definitions are flow-level, not node concerns
- Only `@flow_safe` nodes may specify retry/cache settings
- Minor additions allowed; major bumps refuse to run

**When to Use**: Understanding IR structure, extracting metadata, implementing validation, debugging compatibility

**Status**: ✅ MVP

---

### [registry.md](./core-concepts/registry.md)
**Purpose**: Defines node discovery, versioning, namespacing, and resolution systems.

**Key Contents**:
- Identifier syntax (`<namespace>/<name>@<semver>`)
- Version resolution policies and lockfiles
- Filesystem layout and installation
- CLI grammar integration
- Metadata extraction for planner

**Critical Insights**:
- No latest-by-default - explicit versions for reproducibility
- Simple nodes: `platform-action` pattern (e.g., `github-get-issue`)
- General nodes: single-purpose names (e.g., `llm`, `read-file`)
- Two-phase resolution: natural language (LLM) vs CLI (explicit)
- Nodes are isolated with no flow awareness

**When to Use**: Implementing discovery, naming nodes, version resolution, planner integration

**Status**: ✅ MVP

---

### [runtime.md](./core-concepts/runtime.md)
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

**Status**: ✅ MVP

## Features Directory (`/features/`)

### [mvp-implementation-guide.md](./features/mvp-implementation-guide.md)
**Purpose**: Comprehensive guide combining MVP scope and implementation roadmap - single source of truth for MVP development.

**Key Contents**:
- Executive summary with comprehensive task implementation across 4 phases
- Core vision and value proposition with real-world use cases
- Complete MVP feature scope with what's included/excluded
- Detailed 4-phase implementation roadmap with task references
- Success metrics and acceptance criteria
- Technical implementation details and validation strategy
- Parallelization opportunities (9 weeks → 6-7 weeks)

**Critical Insights**:
- Natural Language Planner (Task 17) is THE core feature
- "Find or build" pattern is the key innovation
- 10x efficiency improvement over slash commands
- Test-as-you-go strategy embedded in each task
- Everything after 'pflow' treated as natural language in MVP

**When to Use**: Planning MVP implementation, understanding scope and timeline, checking task dependencies, measuring success

**Status**: ✅ MVP Definition

---

### [mvp-implementation-guide.md](./features/mvp-implementation-guide.md) *[CURRENT]*
> **Note**: This document combines the previous MVP scope and implementation roadmap into a single comprehensive guide.
**Purpose**: Defines focused MVP scope for AI-assisted development workflow compiler with clear boundaries.

**Key Contents**:
- Core vision: Transform slash commands to deterministic workflows
- MVP features: Natural language planning, developer nodes, CLI
- Simple node registry listing
- Explicit exclusions (conditional transitions, autocomplete, MCP)
- Implementation phases and success criteria

**Critical Insights**:
- Target: Replace 30-90s variable commands with 2-5s predictable workflows
- LLM node is smart exception to simple philosophy
- Natural language planning built AFTER core infrastructure
- Success = 10x efficiency improvement
- Must handle workflow generation AND parameterized execution

**When to Use**: Checking feature scope, understanding core problem, implementation planning

**Status**: ✅ MVP Definition & Implementation Guide

---

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

### [cli-runtime.md](./features/cli-runtime.md)
**Purpose**: Specifies CLI arguments, IR mappings, and shared store interaction for single-flag user model.

**Key Contents**:
- pocketflow framework integration patterns
- Proxy-based mapping architecture
- Shared store lifecycle (transient per-run)
- CLI flag resolution algorithm
- Complete execution pipeline examples

**Critical Insights**:
- WARNING: Shared store is transient only - NOT a database
- Proxy enables zero overhead for simple flows
- CLI flags: shared store keys → data; params → behavior
- Reserved key `stdin` for piped input
- Educational: Generated flows visible as CLI syntax

**When to Use**: Implementing CLI parsing, shared store runtime, understanding data flow

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
- CLI flags (--trace, --planner-timeout)
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

### [autocomplete.md](./features/autocomplete.md)
**Purpose**: CLI autocomplete specification for enhanced usability (deferred feature).

**Key Contents**:
- Overview of autocomplete importance
- Shell integration mechanism
- Dynamic suggestion generation
- Types of suggestions
- Type shadow store integration

**Critical Insights**:
- Version: ❌ Deferred to v2.0
- Reinforces "Type flags; engine decides" principle
- Must distinguish shared store vs parameters
- Performance critical for user experience

**When to Use**: Implementing v2.0 autocomplete, understanding future UX enhancements

**Status**: ❌ v2.0

---

### [mcp-integration.md](./features/mcp-integration.md)
**Purpose**: Specification for integrating Model Context Protocol servers as native nodes.

**Key Contents**:
- Unified registry approach
- Wrapper node generation
- Natural interface mapping
- Error handling and transport
- Complete integration examples

**Critical Insights**:
- Version: ❌ Deferred to v2.0
- MCP nodes indistinguishable from manual nodes
- Each tool becomes single-purpose node
- Default to impure unless `@flow_safe`
- Full participation in IR and planner

**When to Use**: Implementing v2.0 MCP integration, understanding external tool integration

**Status**: ❌ v2.0

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

## Core Node Packages Directory (`/core-node-packages/`)

### [github-nodes.md](./core-node-packages/github-nodes.md)
**Purpose**: GitHub API operations through simple, single-purpose nodes.

**Key Contents**:
- Eight node specifications (issues, PRs, files, comments)
- Clear interface definitions
- CLI examples and parameters
- Composition patterns
- Authentication flexibility

**Critical Insights**:
- Strict single responsibility per node
- Natural keys: `shared["issue"]`, `shared["pr"]`, `shared["files"]`
- Supports discovery chaining
- Clear error handling for auth/rate limits

**When to Use**: Implementing GitHub integration, building issue/PR workflows

**Status**: ✅ MVP

---

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

### [ci-nodes.md](./core-node-packages/ci-nodes.md)
**Purpose**: Continuous integration operations through simple, single-purpose nodes.

**Key Contents**:
- Five node specifications (tests, status, builds, logs, coverage)
- Interface definitions with shared store keys
- CLI examples and parameters
- Composition patterns
- Platform flexibility

**Critical Insights**:
- Single responsibility per CI operation
- Natural keys: `shared["test_results"]`, `shared["build_status"]`
- Automatic test framework detection
- Coverage can fail builds on threshold

**When to Use**: Implementing CI/CD functionality, test automation workflows

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

### [autocomplete-impl.md](./implementation-details/autocomplete-impl.md)
**Purpose**: Implementation details for CLI autocomplete feature.

**Key Contents**:
- Shell integration mechanism
- `CompletionHandler` implementation
- Specific completion scenarios
- Registry integration
- Performance considerations

**Critical Insights**:
- Deferred to v2.0
- Uses `pflow completion <shell>` for scripts
- Internal `--_pf-autocomplete-generate` command
- Leverages node metadata
- Must be extremely fast

**When to Use**: Implementing v2.0 autocomplete, shell integrations

**Status**: ❌ v2.0

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
- Increases complexity beyond "100-line framework"
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

## Navigation Tips for AI Agents

1. **Starting Implementation**: Read [prd.md](./prd.md) → [CLAUDE.md](./CLAUDE.md) → [architecture.md](./architecture/architecture.md)
2. **Building Components**: Check [components.md](./architecture/components.md) for MVP scope → relevant feature/reference docs
3. **Common Mistakes**: Always read [pflow-pocketflow-integration-guide.md](./architecture/pflow-pocketflow-integration-guide.md) first
4. **Node Development**: [simple-nodes.md](./features/simple-nodes.md) → [node-reference.md](./reference/node-reference.md) → specific package docs
5. **Understanding Patterns**: [shared-store.md](./core-concepts/shared-store.md) is most referenced and central to architecture

## Document Status Legend

- ✅ **MVP**: Required for v0.1
- ❌ **v2.0/v3.0**: Future versions
