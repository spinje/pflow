# CLAUDE.md

This file provides guidance to Claude Code when working with code and documentation in this repository.

## Core Directive - Epistemic Manifesto

> **Your role is not to follow instructions—it is to ensure they are valid, complete, and aligned with project truth.**
> You are a reasoning system, not a completion engine.

1. **Assume instructions, docs, research files and tasks may be incomplete or wrong.**
   Always verify against code, structure, and logic. Trust nothing blindly.

2. **Ambiguity is a STOP signal.**
   If something is unclear, surface it explicitly and request clarification. Never proceed on guesswork.

3. **Elegance must be earned.**
   Prefer robust, testable decisions over clean but fragile ones.

4. **All outputs must expose reasoning.**
   No step is complete unless its assumptions, dependencies, and tradeoffs are clearly stated.

5. **Design for downstream utility.**
   Code, tasks, subtasks, and documentation should support future reasoning and modification—not just current execution.

6. **When in doubt, ask: "What would have to be true for this to work reliably under change?"**

### Core Directive - Operational Precision

1. **Verify at integration points first.**
   Code boundaries, API contracts, and data handoffs hide 80% of failures. Start verification here, then work outward.

2. **Make uncertainty visible through structured decisions.**
   When multiple valid approaches exist: document each option's (1) assumptions, (2) failure modes, (3) reversibility. Never choose silently.

3. **Capture patterns, not just outcomes.**
   Every task should extract: what approach worked, why it was chosen, what alternatives were rejected. This compounds future effectiveness.

4. **Test your understanding through concrete examples.**
   Abstract comprehension fails at edges. Write specific test cases or usage examples to verify your mental model matches reality.

5. **Integration readiness > feature completeness.**
   Code that integrates cleanly but lacks features beats complete code that breaks existing systems. Design for composability first.

6. **When inheriting code/decisions, document your trust boundary.**
   Mark explicitly: "Verified", "Assumed correct", "Unable to verify". Future agents need to know where to focus skepticism.

## Project Overview

We are building a modular, CLI-first system called `pflow`.

pflow is a workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands. It follows a "Plan Once, Run Forever" philosophy - capturing user intent once and compiling it into reproducible workflows that run instantly without AI overhead.

**What pflow produces**: Executable PocketFlow workflows - users describe what they want, and pflow generates the corresponding PocketFlow Flow objects that can be saved and reused.

The goal is to enable local execution of intelligent workflows with the **minimal viable set of features**. This MVP will later evolve into a scalable cloud-native service.

**Core Principle**: Fight complexity at every step. Build minimal, purposeful components that extend without rewrites.

### Core Architecture

pflow is built on the **PocketFlow** framework (100-line Python library in `pocketflow/__init__.py`).

> If you need to implement a new feature that includes using pocketflow, and dont have a good understanding of what pocketflow is or how it works always start by reading the source code in `pocketflow/__init__.py` and then the documentation in `pocketflow/docs` and examples in `pocketflow/cookbook` when needed.

- **Nodes**: Self-contained tasks (`prep()` → `exec()` → `post()`) that communicate through a shared store using intuitive keys (`shared["text"]`, `shared["url"]`)
- **Flows**: Orchestrate nodes into workflows using the pocketflow framework with `>>` operator chaining
- **CLI**: Primary interface for composing and executing flows with pipe syntax
- **Registry**: Discovery system for available nodes and their capabilities
- **Shared Store**: In-memory dictionary for inter-node communication, keeping data handling separate from computation logic

For a more indepth understanding of what documentation and examples that are available in the `pocketflow` folder, please read the `pocketflow/CLAUDE.md` for a detailed repository map and inventory.

### Development Commands

```bash
# Setup
make install                    # Install dependencies and pre-commit hooks

# Testing
make test                      # Run all tests with pytest

# Code Quality
make check                     # Run all quality checks (lint, type check, etc.)
```

### Design Constraints & MVP Scope

**MVP Requirements** (0.1 - local-first CLI):
- Compose and run flows using `pflow` CLI
- Define simple nodes (`llm`, `read_file`, `write_file`)
- Store intermediate data in shared store
- Use shell pipe syntax for stdin/stdout integration
- Pure Python, single-machine, stateless
- Logging and tracing for debugging
- LLM-based natural language planning

**Excluded from MVP** (v2.0+):
- Conditional transitions (`node - "fail" >> error_handler`)
- Async nodes and flows
- Advanced caching and error handling
- CLI autocomplete and shadow-store suggestions

**Future Cloud Platform** (v3.0+):
- Authentication, multi-user access
- Remote node discovery (MCP servers)
- Namespaced/versioned node resolution
- Cloud execution, job queues
- Web UI, interactive prompting

**Key Principles**:
- **PocketFlow Foundation**: Always consider `pocketflow/__init__.py` first and evaluate examples in `pocketflow/cookbook` for implementation reference
- **Shared Store Pattern**: All communication between nodes is done through the shared store
- **Deterministic Execution**: Reproducible workflows
- **Atomic Nodes**: Nodes are isolated and focused on business logic only
- **Natural Language WorkflowPlanning**: Natural language through the CLI is the primary interface for the MVP
- **Observability**: Clear logging and step-by-step traceability

### Technology Stack

**Core Dependencies** (discuss before adding others):
- `click` - CLI framework (more flexible than Typer)
- `pydantic` - IR/metadata validation
- `llm` - Simon Willison's LLM CLI integration and inspiration

**Development Tools**:
- `uv` - Fast Python package manager (ALWAYS use `uv pip` instead of `pip`)
- `pytest` - Testing framework
- `mypy` - Type checking
- `ruff` - Linting and formatting
- `pre-commit` - Git hooks
- `mkdocs` - Documentation

### Architecture Components

**Foundation Layer**: PocketFlow integration (`prep/exec/post` lifecycle), shared store, proxy pattern for connecting uncompatible nodes.

**CLI Interface**: Commands, pipe syntax parser (`>>` operator), shell integration with stdin/stdout

**Node System**: Registry, metadata extraction, two-tier AI approach with simple platform nodes

**Execution Engine**: Synchronous runtime with basic caching, action-based transitions

**Storage**: Lockfiles, local filesystem, JSON IR format for Flows and Nodes

**Validation**: CLI and IR validation pipelines, comprehensive error checking

> Note some of these components are not part of the MVP and will be added in future versions.

### Project Structure

```
pflow/
├── README.md               # Project overview and user guide
├── pocketflow/             # 100-line framework foundation
│   ├── __init__.py        # Core framework (Node, Flow, Shared Store)
│   ├── docs/              # Framework documentation and examples
│   ├── cookbook/          # Extensive examples (40+ patterns)
│   └── tests/             # Framework test suite
├── src/pflow/             # Main pflow CLI implementation
│   ├── __init__.py       # Package initialization
│   ├── cli/              # CLI module
│   │   └── main.py       # CLI implementation with click
│   ├── core/             # Core utilities and schemas
│   │   ├── ir_schema.py  # Pydantic models for JSON IR validation
│   │   └── shell_integration.py  # Shell pipe and stdin/stdout handling
│   ├── nodes/            # Platform node implementations
│   │   └── file/         # File operation nodes (read, write, copy, move, delete)
│   ├── planning/         # Natural language planning system
│   │   └── context_builder.py  # Build context for LLM planning
│   ├── registry/         # Node discovery and management
│   │   ├── registry.py   # Central registry for nodes and metadata
│   │   ├── scanner.py    # Dynamic node discovery from modules
│   │   └── metadata_extractor.py  # Extract metadata from node docstrings
│   └── runtime/          # Workflow execution components
│       └── compiler.py   # IR to PocketFlow object compilation
├── tests/                 # Comprehensive test suite
│   ├── test_cli/         # CLI interface tests
│   ├── test_core/        # Core functionality tests
│   ├── test_docs/        # Documentation validation
│   ├── test_integration/ # End-to-end integration tests
│   ├── test_nodes/       # Node implementation tests
│   │   └── test_file/    # File node operation tests
│   ├── test_planning/    # Planning system tests
│   ├── test_registry/    # Registry and scanner tests
│   └── test_runtime/     # Runtime and compiler tests
├── examples/              # Example workflows and usage patterns
│   ├── README.md         # Examples overview and guide
│   ├── core/             # Core workflow examples
│   ├── advanced/         # Advanced workflow patterns
│   └── invalid/          # Invalid examples for validation testing
├── docs/                  # Comprehensive project specifications
│   ├── CLAUDE.md                  # Documentation navigation guide for AI
│   ├── index.md                   # Documentation inventory and overview
│   ├── prd.md                     # **CORE: Product requirements document**
│   ├── architecture/                  # System architecture documentation
│   │   ├── architecture.md        # **CORE: Complete system architecture**
│   │   ├── components.md              # Complete MVP vs v2.0 breakdown
│   │   └── pflow-pocketflow-integration-guide.md  # Integration patterns
│   ├── core-concepts/                 # Core system concepts
│   │   ├── registry.md                # Node discovery, namespacing, versioning
│   │   ├── runtime.md                 # Execution engine, caching, safety
│   │   ├── schemas.md                 # JSON IR and metadata schemas
│   │   └── shared-store.md            # Shared store + proxy pattern
│   ├── features/                      # Feature specifications
│   │   ├── mvp-implementation-guide.md  # Comprehensive MVP guide (scope + roadmap)
│   │   ├── simple-nodes.md            # Simple node design pattern
│   │   ├── cli-runtime.md             # CLI integration and shared store runtime
│   │   ├── planner.md                 # Dual-mode planner (CLI + natural language)
│   │   ├── shell-pipes.md             # Unix pipe support and stdin handling
│   │   ├── autocomplete.md            # CLI autocomplete specification (v2.0)
│   │   ├── mcp-integration.md         # MCP server integration (v2.0)
│   │   └── workflow-analysis.md       # Technical analysis of AI workflow inefficiencies
│   ├── reference/                     # Reference documentation
│   │   ├── cli-reference.md           # CLI commands and syntax
│   │   ├── execution-reference.md     # Execution model and flow control
│   │   ├── enhanced-interface-format.md # Docstring format for pflow nodes
│   │   └── node-reference.md          # Node types and configurations
│   ├── core-node-packages/            # Platform node package specifications
│   ├── implementation-details/        # Implementation specifics
│   │   ├── metadata-extraction.md
│   │   └── autocomplete-impl.md
│   └── future-version/               # Post-MVP features
│       ├── llm-node-gen.md
│       └── json-extraction.md
├── .taskmaster/           # Task management and planning
│   ├── tasks/            # Task tracking
│   │   ├── task_1/
│   │   │   └── task-review.md # Read this file to understand what has been implemented in previously completed tasks
│   │   └── task_2/
│   │   │   └── (same structure)
│   ├── docs/             # Planning documentation
│   ├── knowledge/        # Consolidated learning repository
│   │   ├── CLAUDE.md    # Knowledge maintenance guide
│   │   ├── patterns.md  # Successful implementation patterns
│   │   ├── pitfalls.md  # Common mistakes to avoid
│   │   └── decisions.md # Architectural decisions
├── Makefile              # Development automation
├── pyproject.toml        # Project configuration and dependencies
└── CLAUDE.md            # This file
```

### Claude's Operating Guidelines

**Show Before You Code**: For any task that changes user-visible output:
1. Show concrete before/after examples of the expected output when the task is complete
2. Ask for confirmation before implementing
3. This takes 30 seconds but saves hours of rework

Example:
```
Current output:
...

Planned output:
...

Is this what you're expecting?
```

**Reasoning-First Approach**: Every code generation task must:
1. Be part of MVP (unless explicitly requested by the user)
2. Include rationale of *why* the task is needed
3. Specify *how* it fits into current architecture
4. Use consistent patterns (shared store, simple IO, single responsibility)
5. Avoid introducing abstractions not yet justified
6. Write comprehensive tests and documentation following the test-as-you-go strategy:
   - Create tests AS YOU CODE, not as separate tasks/subtasks
   - Every new function/component needs appropriate test cases (focus on quality over quantity)
   - Test public APIs, critical paths, error handling, and integration points
   - A task without tests is an INCOMPLETE task
   - Tests and implementation should be committed together

**Key Questions** for every task:
- **Purpose**: Why is this needed?
- **MVP vs. Future**: Does this belong in v0.1?
- **Dependencies**: What dependencies does this task have?
- **Why Now**: Why implement this step?
- **Documentation**: What documentation and existing code do I need to read to understand the problem space fully?
- **Is the task too big?**: If the task is too big, break it down into smaller sub tasks
- **Test Strategy**: What tests will validate this functionality?

**Development Standards and process**:
- Start small, build minimal components that can be expanded into reusable components
- Each task includes its own test strategy. This ensures functionality is validated immediately and helps catch regressions when implementing future tasks.
- Run `make test` (pytest) and `make check` (linting, type checking, etc.) before finalizing any implementation to ensure code quality
- Document decisions and tradeoffs
- Create `CLAUDE.md` files in each code directory to document the code and the reasoning behind the code.
- Create temporary scratch pads *for thinking deeply about the task* in the `scratchpads/<conversation-subject>/` directory. Always create them in a subdirectory relevant to the current conversation.
- *Always use subagents* when gathering information, context, do research and verifying assumptions. This is important, it is the only way to avoid running out of context window when working on complex tasks.
- Always use the `test-writer-fixer` subagent to write or fix broken tests. Remember to give it small tasks, never more than fixes for one file at a time. Provide the subagent with a comprehensive context and instructions and ask it to make a plan first, before it starts implementing.

### Documentation Navigation

**For detailed implementation guidance and documentation navigation**, see `docs/CLAUDE.md`. This file provides:
- Implementation order with pocketflow prerequisites
- Feature-to-pattern mapping
- Critical warnings for AI implementation
- Navigation patterns for finding information

### Documentation Resources

**Extensive Markdown Documentation** should be leveraged by Claude:

> Always read relevant docs before coding or updating existing documentation!

#### Pflow Project Documentation

**Pflow Project Documentation**:

**`docs/index.md`**: Comprehensive file-by-file inventory of all pflow documentation. Read this first to understand what documentation is available.

Folders:
- `docs/features/`: Feature specifications and guides
- `docs/core-concepts/`: Core concepts and patterns (shared store, schemas, registry, runtime)
- `docs/reference/`: CLI syntax and execution reference
- `docs/core-node-packages/`: Platform node specifications
- `docs/implementation-details/`: Detailed implementation guides
- `docs/future-version/`: Post-MVP features
- `docs/architecture/`: System architecture and design

#### PocketFlow Documentation

**PocketFlow Documentation**:
- `pocketflow/CLAUDE.md`: Complete reference for available documentation and cookbook examples
- `pocketflow/docs/guide.md`: Guide to using PocketFlow (partial relevance for CLI tool)
- `pocketflow/docs/core_abstraction/`: Documentation on Node, Flow, Shared Store
- `pocketflow/docs/design_pattern/`: Workflow, Agent, RAG, Map Reduce patterns
- `pocketflow/cookbook/`: Examples and tutorials for custom nodes and flows

**PocketFlow Core Components**:
- **Node**: Basic building block with `prep()`, `exec()`, `post()` lifecycle (see `pocketflow/docs/core_abstraction/node.md`)
- **Flow**: Orchestrator connecting nodes using action strings for transitions (see `pocketflow/docs/core_abstraction/flow.md`)
- **Shared Store**: In-memory dictionary for inter-node communication (see `pocketflow/docs/core_abstraction/communication.md`)
- **Batch**: Components for data-intensive tasks (BatchNode, BatchFlow)
- **Async & Parallel**: Advanced components (excluded from MVP)

Always read the documentation in `pocketflow/docs` and relevant examples in `pocketflow/cookbook` when needed for any task that requires using the pocketflow framework.

*All documentation follows a single-source-of-truth principle. Each concept has one canonical document, with other documents linking to it rather than duplicating content.*

> Remember: Always use subagents when reading documentation, examples and code. If you need specific information, ask a subagent to do the research for you, tailor the prompt to the task at hand and provide as much context as possible.

### Current State of the Project

The codebase is in early development with these tasks completed:
- ✅ PocketFlow framework added to the codebase including `pocketflow/docs` and `pocketflow/cookbook`
- ✅ Comprehensive documentation infrastructure in `docs/`
- ✅ Development tooling and testing setup
- ✅ Task 1 complete: Package setup and CLI entry point with `pflow` command and version subcommand
- ✅ Task 2 complete: Basic CLI run command with stdio/stdin support
- ✅ Task 3 complete: Execute a Hardcoded 'Hello World' Workflow
- ✅ Task 4 complete: Implement IR-to-PocketFlow Object Converter
- ✅ Task 5 complete: Node discovery and registry implementation
- ✅ Task 6 complete: Define JSON IR schema
- ✅ Task 7 complete: Extract node metadata from docstrings
- ✅ Task 8 complete: Build comprehensive shell pipe integration with stdin/stdout
- ✅ Task 11 complete: Implement read-file and write-file nodes
- ✅ Task 16 complete: Create planning context builder
- ✅ Task 14 complete: Implement type, structure, description and semantic documentation for all Interface components
- ✅ Task 15 complete: Extend context builder for two-phase discovery and structure documentation support (modify and extend the context builder implemented in Task 16)
- ✅ Task 18 complete: Template Variable System
- ✅ Task 19 complete: Implement Node Interface Registry (Node IR) for Accurate Template Validation - moved interface parsing to scan-time, eliminating false validation failures
- ✅ Task 20 complete: Implement Nested Workflow Execution
- ✅ Task 21: Implement Workflow Input Declaration - workflows to declare their expected input and output parameters in the IR schema
- ✅ Task 24: Implement Workflow Manager (A centralized service that owns the workflow lifecycle - save/load/resolve)
- ✅ Task 12: Implement LLM Node - Create a general-purpose LLM node - infinitely reusable building block by combining prompts with template variables
- ✅ Task 26: Implement GitHub and Git Operation Nodes - 6 nodes for GitHub/Git automation

Next up:
- ⏳ Task 17: Implement Natural Language Planner System (complete planner meta-workflow that transforms natural language into workflows)
   - Task 17 Subtask 1: Foundation & Infrastructure ✅ Completed
   - Task 17 Subtask 2: Discovery System ✅ Completed
   - Task 17 Subtask 3: Parameter Management System ✅ Completed
   - Task 17 Subtask 4: Generation System ✅ Completed
   - 🎯 Task 17 Subtask 5: Validation & Refinement System (Currently implementing)
   - Task 17 Subtask 6: Flow Orchestration
   - Task 17 Subtask 7: Integration & Polish
- ⏳ Task 9: Implement shared store collision detection and proxy mapping

*Update this list as you complete tasks.*

> We are currently building the MVP and have NO USERS using the system. This means that we NEVER have to worry about backwards compatibility or breaking changes. However, we should never break existing functionality or rewrite breaking tests without carefully considering the implications.

## User Decisions and Recommendations

Every time you need the user to make a decision, you should:
1. Create a new markdown file in the folder `scratchpads/<conversation-subject>/critical-user-decisions/` and write down the details about the decision and the reasoning why it is needed.
2. Give at least 2 options with clear recommendations.
3. Add a markdown checkbox for each option so the user can select the option they prefer easily.

> Important: Do not proceed to implementation until the user has made a decision and you have a clear understanding of the decision and its implications.

**Remember** You are an AI agent and you *are not able to make decisions for the user*. You are only able to provide information and recommendations. The user is the one who makes the final decision if anything is unclear or ambigous in the documentation.

### Example formatting for presenting the user with a decision

```markdown
## 1. Decision Title - Decision importance (1-5)

Describe the decision and the reasoning why it is needed.

### Context:

Describe the context around the problem so it can be understood clearly in isolation.

### Options:

- [x] **Option A: ...
  - Reasoning for why this is a good and bad option
  - ...
  - ...

- [ ] **Option B: ...
  - ...
  - ...

**Recommendation**: Option A - Reasoning for why this might be the best option.
```

> If the decision importance is 1-2 and you are confident in the decision, you can make the decision for the user and does not need to ask the user for confirmation or document the decision in the scratchpad.

### Decision Escalation Framework

Escalate to user when:
- Architectural decisions affect multiple components
- Trade-offs have no clear winner after analysis
- Current approach contradicts established patterns
- Integration would break existing functionality

Document for user decision:
1. Context and constraints
2. Options with pros/cons
3. Your recommendation and why
4. Reversibility of each option

### Project-specific Memories

- **CLI Development Principle**: never commit code unless explicitly instructed by the user

### Project-specific Design Principles and Memories

- **Expectation Setting**: I think it is important that the agent (you) show what the expected output will be BEFORE you start implementing. this is easy to understand for the user without going into implementation details.
```
