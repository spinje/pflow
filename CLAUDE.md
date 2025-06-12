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
├── pocketflow/              # 100-line framework foundation
│   ├── __init__.py         # Core framework (Node, Flow, Shared Store)
│   └── docs/               # Framework documentation and examples
├── src/pflow/              # Main pflow CLI implementation
│   ├── __init__.py        # Currently empty - CLI entry point to be added
│   └── foo.py             # Placeholder - to be replaced with core modules
├── docs/                   # Comprehensive project specifications
│   ├── PRD-pflow.md       # Product requirements document
│   ├── architecture-document.md  # Complete system architecture
│   └── [other specs]      # Implementation details and design docs
├── tests/                  # Test suite
│   ├── test_foo.py        # Placeholder test
│   └── test_links.py      # Documentation link validation
├── Makefile               # Development automation
├── pyproject.toml         # Project configuration and dependencies
└── CLAUDE.md             # This file
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

**Project Documentation**:
- `docs/`: Comprehensive specifications (PRD, architecture, implementation details)
- `docs/core-nodes/`: Specifications for essential built-in nodes
- Individual `CLAUDE.md` files in each directory for component-specific guidance

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
- ⏳ Core CLI interface implementation (next phase)
- ⏳ Node registry system (next phase)

### Next Development Phase

Focus on implementing:
1. CLI interface with pipe syntax parsing
2. Node registry with metadata extraction
3. Basic built-in nodes (read_file, transform, prompt)
4. JSON IR generation and validation
5. Shell integration with stdin/stdout

The goal is a working MVP that can execute simple flows like:
```bash
pflow read_file data.txt >> transform --format=json >> prompt "summarize this data"
```
