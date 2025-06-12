# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pflow is a workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands. It follows a "Plan Once, Run Forever" philosophy - capturing user intent once and compiling it into reproducible workflows that run instantly without AI overhead.

### Core Architecture

pflow is built on the **PocketFlow** framework (100-line Python library in `pocketflow/__init__.py`) using the **Shared Store + Natural Interface Pattern**:

- **Nodes**: Self-contained tasks (`prep()` → `exec()` → `post()`) that communicate through a shared store using intuitive keys (`shared["text"]`, `shared["url"]`)
- **Flows**: Orchestrate nodes into workflows using the pocketflow framework with `>>` operator chaining. This syntax will be used both for the python code and the CLI.
- **CLI**: Primary interface for composing and executing flows with pipe syntax or natural language.
- **Registry**: Discovery system for available nodes and their capabilities. Used by both the CLI through auto-completion and the LLM planner.
- **Planner**: LLM-based planner for parsing natural language and creating a flow from it.

### Development Commands

```bash
# Setup
make install                    # Install dependencies and pre-commit hooks

# Testing
make test                      # Run all tests with pytest

# Code Quality
make check                     # Run all quality checks (lint, type check, etc.)
```

### Key Constraints & Design Principles

**MVP First**: This is pflow v0.1 MVP focused on local-first CLI execution. Features like natural language planning, conditional transitions, async execution, and cloud deployment are explicitly deferred to post-MVP versions.

**PocketFlow Foundation**: Always consider the PocketFlow framework (`pocketflow/__init__.py`) as the primary solution before suggesting other frameworks. The CLI itself should leverage PocketFlow patterns when possible.

**Shared Store Pattern**: Nodes communicate through a flow-scoped shared store using natural key names (`shared["text"]`, `shared["data"]`). This enables loose coupling and composability.

**Deterministic Execution**: Every workflow must be reproducible across environments through version pinning, lockfiles, and clear data/parameter separation.

**Zero Boilerplate Philosophy**: Nodes focus purely on business logic; orchestration complexity handled by the framework.

### Technology Stack

**Core Dependencies**:
- `click` - CLI framework (more flexible than Typer)
- `pydantic` - IR/metadata validation
- `llm` - Simon Willison's LLM CLI integration

**Development Tools**:
- `uv` - Fast Python package manager
- `pytest` - Testing framework
- `mypy` - Type checking
- `ruff` - Linting and formatting

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

### Development Guidelines

1. **Start Small**: Build minimal, purposeful components that can be extended later
2. **MVP Focus**: Only implement features required for local CLI workflow execution
3. **Test Everything**: Write comprehensive tests for each component (`make test`)
4. **Document Decisions**: Include rationale for architectural choices
5. **Leverage PocketFlow**: Use the framework's patterns throughout the codebase
6. **Natural Interfaces**: Use intuitive shared store keys for node communication
7. **Follow Code Quality**: Run `make check` before committing

### Key Design Patterns

**Shared Store + Proxy Pattern**: The central innovation enabling both simple direct access and complex routed scenarios

**Dual-Mode Planning**: CLI pipe syntax (`pflow node1 >> node2`) and natural language planning (post-MVP)

**Progressive Complexity**: Same node code works in both simple and complex orchestration scenarios

**Opt-In Purity Model**: Default impure nodes with `@flow_safe` decorator for cacheable pure nodes

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
