# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

We are building a modular, CLI-first system called `pflow`.

pflow is a workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands. It follows a "Plan Once, Run Forever" philosophy - capturing user intent once and compiling it into reproducible workflows that run instantly without AI overhead.

The goal is to enable local execution of intelligent workflows with the **minimal viable set of features**. This MVP will later evolve into a scalable cloud-native service.

**Core Principle**: Fight complexity at every step. Build minimal, purposeful components that extend without rewrites.

### Core Architecture

pflow is built on the **PocketFlow** framework (100-line Python library in `pocketflow/__init__.py`) using the **Shared Store + Natural Interface Pattern**:

- **Nodes**: Self-contained tasks (`prep()` → `exec()` → `post()`) that communicate through a shared store using intuitive keys (`shared["text"]`, `shared["url"]`)
- **Flows**: Orchestrate nodes into workflows using the pocketflow framework with `>>` operator chaining
- **CLI**: Primary interface for composing and executing flows with pipe syntax
- **Registry**: Discovery system for available nodes and their capabilities
- **Shared Store**: In-memory dictionary for inter-node communication, keeping data handling separate from computation logic

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
- Define simple nodes (`prompt`, `transform`, `read_file`)
- Store intermediate data in shared store
- Use shell pipe syntax for stdin/stdout integration
- Pure Python, single-machine, stateless
- Logging and tracing for debugging

**MVP Features** (1.0 - Natural language user input):
- LLM-based natural language planning
- CLI autocomplete and shadow-store suggestions

**Excluded from MVP** (v2.0+):
- Conditional transitions (`node - "fail" >> error_handler`)
- Async nodes and flows
- Advanced caching and error handling

**Future Cloud Platform** (v3.0+):
- Authentication, multi-user access
- Remote node discovery (MCP servers)
- Namespaced/versioned node resolution
- Cloud execution, job queues
- Web UI, interactive prompting

**Key Principles**:
- **PocketFlow Foundation**: Always consider `pocketflow/__init__.py` first
- **Shared Store Pattern**: Natural key names enable loose coupling
- **Deterministic Execution**: Reproducible via lockfiles and version pinning
- **Zero Boilerplate**: Nodes focus on business logic only
- **Observability**: Clear logging and step-by-step traceability

### Technology Stack

**Core Dependencies** (discuss before adding others):
- `click` - CLI framework (more flexible than Typer)
- `pydantic` - IR/metadata validation
- `llm` - Simon Willison's LLM CLI integration

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

**Node System**: Registry, metadata extraction, built-in nodes (read_file, transform, prompt)

**Execution Engine**: Synchronous runtime with basic caching, action-based transitions

**Storage**: Lockfiles, local filesystem, JSON IR format

**Validation**: CLI and IR validation pipelines, comprehensive error checking

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
│   ├── **PRD-pflow.md**                      # **CORE: Product requirements document**
│   ├── **architecture-document.md**          # **CORE: Complete system architecture**
│   ├── **mvp-scope.md**                      # **CORE: Clear MVP boundaries**
│   ├── **action-based-node-architecture.md** # **CORE: Action-based node design**
│   ├── shared-store-node-proxy-architecture.md # Shared store + proxy pattern
│   ├── shared-store-cli-runtime-specification.md # CLI integration and runtime
│   ├── json-schema-for-flows-ir-and-nodesmetadata.md # JSON IR and metadata schemas
│   ├── planner-responsibility-functionality-spec.md # Dual-mode planner (CLI + NL)
│   ├── runtime-behavior-specification.md # Execution engine and caching
│   ├── node-discovery-namespacing-and-versioning.md # Registry system
│   ├── component-inventory.md # Complete MVP vs v2.0 breakdown
│   ├── shell-pipe-native-integration.md # Unix pipe support
│   ├── cli-autocomplete-spec.md # CLI autocomplete (v2.0)
│   ├── mcp-server-integrationa-and-security-model.md # MCP integration (v2.0)
│   ├── core-nodes/        # Platform node specifications
│   │   ├── github-platform-node-spec.md
│   │   ├── claude-platform-node-spec.md
│   │   ├── ci-platform-node-spec.md
│   │   └── llm-prompt-core-node-spec.md
│   ├── implementation-details/ # Implementation specifics
│   │   ├── node-metadata-extraction.md
│   │   └── cli-auto-complete-feature-implementation-details.md
│   └── future-version/    # Post-MVP features
│       ├── future-llm-node-generation.md
│       └── json-field-extraction-specification.md
├── todo/                  # Implementation planning
│   ├── implementation-roadmap.md  # High-level roadmap
│   └── mvp-implementation-plan.md # Detailed task breakdown
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
6. Write comprehensive tests and documentation before, during and after working on the task.

**Key Questions** for every task:
- **Purpose**: Why is this needed?
- **MVP vs. Future**: Does this belong in v0.1?
- **Dependencies**: What does this require?
- **Why Now**: Why implement this step?
- **Documentation**: What documentation and existing code do I need to read to understand the problem space fully?

**Development Standards**:
- Start small, build minimal components
- Test everything that makes sense to test
- Document decisions and tradeoffs
- Run `make check` before committing
- Create `CLAUDE.md` files in each directory
- Create temporary scratch pads *for thinking deeply about the task* in the `scratchpads/` directory.

### Documentation Resources

**Extensive Markdown Documentation** should be leveraged by Claude:

**Project Documentation** (always read relevant docs before coding):

**Core Architecture**:
- `docs/PRD-pflow.md`: Master product requirements and complete architectural vision
- `docs/architecture-document.md`: MVP-focused architecture document
- `docs/mvp-scope.md`: Clear MVP boundaries - what to build vs. exclude

**Core Patterns**:
- `docs/shared-store-node-proxy-architecture.md`: Fundamental shared store + proxy pattern
- `docs/shared-store-cli-runtime-specification.md`: CLI integration and shared store management
- `docs/json-schema-for-flows-ir-and-nodesmetadata.md`: JSON IR and metadata schemas

**Implementation Specs**:
- `docs/planner-responsibility-functionality-spec.md`: Dual-mode planner (CLI + natural language)
- `docs/runtime-behavior-specification.md`: Execution engine, caching, error handling
- `docs/node-discovery-namespacing-and-versioning.md`: Registry system and version management
- `docs/component-inventory.md`: Complete MVP vs v2.0 component breakdown

**Core Nodes**:
- `docs/core-nodes/llm-prompt-core-node-spec.md`: LLM/prompt node specification
- `docs/core-nodes/claude-code-core-node-spec.md`: Claude Code integration specification
- `docs/implementation-details/node-metadata-extraction.md`: Metadata extraction system


**Shell Integration**:
- `docs/shell-pipe-native-integration.md`: Unix pipe support and stdin handling
- `docs/user_stories_and_node_design.md`: Real-world usage patterns

**Future Features**:
- `docs/cli-autocomplete-spec.md`: CLI autocomplete specification (v2.0)
- `docs/implementation-details/cli-auto-complete-feature-implementation-details.md`: Detailed CLI autocomplete implementation (v2.0)
- `docs/mcp-server-integrationa-and-security-model.md`: MCP server integration (v2.0)
- `docs/future-version/future-llm-node-generation.md`: LLM-assisted node development (v3.0)
- `docs/future-version/json-field-extraction-specification.md`: Advanced JSON field extraction (v3.0)


**PocketFlow Documentation**:
- `pocketflow/CLAUDE.md`: Complete reference for available documentation and cookbook examples
- `pocketflow/docs/guide.md`: Guide to using PocketFlow (partial relevance for CLI tool)
- `pocketflow/docs/core_abstraction/`: Documentation on Node, Flow, Shared Store
- `pocketflow/docs/design_pattern/`: Workflow, Agent, RAG, Map Reduce patterns
- `pocketflow/cookbook/`: Examples and tutorials for custom nodes and flows

**PocketFlow Core Components**:
- **Node**: Basic building block with `prep()`, `exec()`, `post()` lifecycle
- **Flow**: Orchestrator connecting nodes using action strings for transitions
- **Shared Store**: In-memory dictionary for inter-node communication
- **Batch**: Components for data-intensive tasks (BatchNode, BatchFlow)
- **Async & Parallel**: Advanced components (excluded from MVP)

### Current State

The codebase is in early development with:
- ✅ PocketFlow framework integrated
- ✅ Comprehensive documentation infrastructure
- ✅ Development tooling and testing setup
- ✅ Create an overview roadmap for the MVP in `todo/implementation-roadmap.md`
- ✅ Create a detailed todo list with tasks and subtasks in `todo/mvp-implementation-plan.md` based on the roadmap
- ⏳ Carefully review the implementation plan and make sure it is complete and accurate (<- We are here)
- ⏳ Start implementing features for the MVP using the todo list one by one

### Next Development Phase

Focus on creating the detailed plan for the MVP by doing the following:
1. Identify the core features that are needed for the MVP
2. Evaluate if they have any pre-requisites that need to be implemented first
3. Create a prioritized implementation roadmap with clear milestones
4. Break down each feature into specific, testable tasks
5. Define success criteria and validation steps for each component


The goal is a working MVP that can execute simple flows like:
```bash
pflow read_file data.txt >> transform --format=json >> prompt "summarize this data"
```

But first, we need to create a detailed plan for the MVP.
