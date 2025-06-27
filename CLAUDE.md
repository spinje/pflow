# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Core Directive - Epistemic Manifesto

> **Your role is not to follow instructions—it is to ensure they are valid, complete, and aligned with project truth.**
> You are a reasoning system, not a completion engine.

1. **Assume instructions, docs, and tasks may be incomplete or wrong.**
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


## Project Overview

We are building a modular, CLI-first system called `pflow`.

pflow is a workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands. It follows a "Plan Once, Run Forever" philosophy - capturing user intent once and compiling it into reproducible workflows that run instantly without AI overhead.

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
- `uv` - Fast Python package manager
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
│   ├── __init__.py       # Currently empty - CLI entry point to be added
│   └── foo.py            # Placeholder - to be replaced with core modules
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
│   │   ├── mvp-scope.md               # Clear MVP boundaries
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
│   │   └── tasks.json    # Detailed task list with subtasks
│   ├── docs/             # Planning documentation
│   │   └── implementation-roadmap.md  # High-level roadmap
│   ├── workflow/         # Epistemic workflow system
│   │   ├── workflow-overview.md       # Complete workflow guide
│   │   ├── refine-task.md            # Main task workflow
│   │   ├── refine-subtask.md         # Subtask refinement workflow
│   │   ├── implement-subtask.md      # Implementation workflow
│   │   └── templates/                # Workflow artifact templates
│   ├── knowledge/        # Consolidated learning repository
│   │   ├── CLAUDE.md    # Knowledge maintenance guide
│   │   ├── patterns.md  # Successful implementation patterns
│   │   ├── pitfalls.md  # Common mistakes to avoid
│   │   └── decisions.md # Architectural decisions
│   └── reports/         # Generated reports
│       └── task-complexity-report.json  # Task decomposition history
├── tests/                 # Test suite
│   ├── test_foo.py       # Placeholder test
│   └── test_links.py     # Documentation link validation
├── Makefile              # Development automation
├── pyproject.toml        # Project configuration and dependencies
└── CLAUDE.md            # This file
```

### Claude's Operating Guidelines

**Reasoning-First Approach**: Every code generation task must:
1. Be part of MVP (unless explicitly requested by the user)
2. Include rationale of *why* the task is needed
3. Specify *how* it fits into current architecture
4. Use consistent patterns (shared store, simple IO, single responsibility)
5. Avoid introducing abstractions not yet justified
6. Write comprehensive tests and documentation before, during and after working on the task following the test-as-you-go strategy:
   - Create tests AS YOU CODE, not after implementation is complete
   - Every new function/component needs at least 3 test cases (happy path, error, edge)
   - Aim for >80% coverage of new code
   - A task without tests is an INCOMPLETE task

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
- Document decisions and tradeoffs
- Create `CLAUDE.md` files in each code directory to document the code and the reasoning behind the code.
- Create temporary scratch pads *for thinking deeply about the task* in the `scratchpads/` directory.

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

### Current State of the Project

The codebase is in early development with:
- ✅ PocketFlow framework added to the codebase including `pocketflow/docs` and `pocketflow/cookbook`
- ✅ Comprehensive documentation infrastructure in `docs/`
- ✅ Development tooling and testing setup
- ✅ Create an overview roadmap for the MVP in `.taskmaster/docs/implementation-roadmap.md`
- ✅ Create a detailed todo list with tasks and subtasks in `.taskmaster/tasks/tasks.json` based on the roadmap
- ✅ Establish epistemic workflow for task execution in `.taskmaster/workflow/`
- ⏳ Start implementing features for the MVP using the `refine-task.md` -> `refine-subtask.md` -> `implement-subtask.md` epistemic workflow.

## Task Implementation Workflow

**Use the unified epistemic workflow in `.taskmaster/workflow/`**:
- `refine-task.md` - Main task understanding, project context creation, and decomposition
- `refine-subtask.md` - Subtask refinement with knowledge loading
- `implement-subtask.md` - Implementation with real-time learning capture

**Core Principles**:
1. **Task Understanding First**: Deeply understand the current task and create project context before decomposition
2. **Natural Decomposition**: Break down tasks based on understanding, with optional reference to similar tasks
3. **Compound Learning**: Each implementation builds on previous technical learnings

The workflow ensures:
- MAIN TASKS: Understand deeply, create project context, generate logical subtasks
- ALL SUBTASKS: Read shared project context, load implementation knowledge
- NEW TASKS: Optionally review similar tasks for inspiration
- CONTINUING SUBTASKS: Read sibling reviews within current task
- ALL WORK: Capture technical discoveries in real-time for future benefit

See `.taskmaster/workflow/workflow-overview.md` for the complete system.

## User Decisions and Recommendations

Every time you need the user to make a decision, you should:
1. Create a new markdown file in the folder `scratchpads/critical-user-decisions/` and write down the details about the decision and the reasoning why it is needed.
2. Give at least 2 options with clear recommendations.
3. Add a markdown checkbox for each option so the user can select the option they prefer easily.

> Important: Do not proceed to implementation until the user has made a decision and you have a clear understanding of the decision and its implications.

**Remember** You are an AI agent and you *are not able to make decisions for the user*. You are only able to provide information and recommendations. The user is the one who makes the final decision if anything is unclear or ambigous in the documentation.

### Example formatting for presenting the user with a decision

```markdown
## 1. Decision Title - Decision importance (1-5)

Describe the decision and the reasoning why it is needed.

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
