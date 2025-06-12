# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pflow is a workflow compiler that transforms natural language into permanent, deterministic CLI commands. It follows a "Plan Once, Run Forever" philosophy - capturing user intent once and compiling it into reproducible workflows that run instantly without AI overhead.

### Core Architecture

pflow is built on the **PocketFlow** framework (100-line Python library in `pocketflow/__init__.py`) using the **Shared Store + Natural Interface Pattern**:

- **Nodes**: Self-contained tasks that communicate through a shared store using intuitive keys (`shared["text"]`, `shared["url"]`)
- **Flows**: Orchestrate nodes into workflows using the pocketflow framework
- **CLI**: Primary interface for composing and executing flows
- **Registry**: Discovery system for available nodes and their capabilities

### Development Commands

```bash
# Run tests
python -m pytest tests/

# Run specific test
python -m pytest tests/test_links.py

# Check for broken documentation links
python -m pytest tests/test_links.py::test_markdown_links_exist
```

### Key Constraints & Design Principles

**MVP First**: This is pflow v0.1 MVP focused on local-first CLI execution. Features like natural language planning, conditional transitions, async execution, and cloud deployment are explicitly deferred to post-MVP versions.

**PocketFlow Foundation**: Always consider the PocketFlow framework (`pocketflow/__init__.py`) as the primary solution before suggesting other frameworks. The CLI itself should leverage PocketFlow patterns.

**Shared Store Pattern**: Nodes communicate through a flow-scoped shared store using natural key names. This enables loose coupling and composability.

**Deterministic Execution**: Every workflow must be reproducible across environments through version pinning, lockfiles, and clear data/parameter separation.

**Observability**: All flows, nodes, and CLI interactions must have clear logging and step-by-step traceability for human debugging.

### Architecture Components

**Core Foundation**: PocketFlow integration, shared store, proxy pattern for marketplace compatibility
**CLI Interface**: Commands, pipe syntax parser, shell integration  
**Node System**: Registry, metadata extraction, built-in nodes (read_file, transform, prompt)
**Execution Engine**: Synchronous runtime with basic caching (purity-based)
**Storage**: Lockfiles, local filesystem, JSON IR format
**Validation**: CLI and IR validation pipelines

### Documentation Structure

The project uses extensive markdown documentation:

- `documents/`: Comprehensive specifications including PRD, architecture document, and implementation details
- `documents/core-nodes/`: Specifications for essential built-in nodes
- `pocketflow/docs/`: PocketFlow framework documentation and examples
- Individual `CLAUDE.md` files in each directory for component-specific guidance

### Development Guidelines

1. **Start Small**: Build minimal, purposeful components that can be extended later
2. **MVP Focus**: Only implement features required for local CLI workflow execution
3. **Test Everything**: Write comprehensive tests for each component
4. **Document Decisions**: Include rationale for architectural choices
5. **Leverage PocketFlow**: Use the framework's patterns throughout the codebase
6. **Natural Interfaces**: Use intuitive shared store keys for node communication

### Project Structure

```
pflow/
├── pocketflow/           # 100-line framework foundation
│   ├── __init__.py      # Core framework code
│   └── docs/            # Framework documentation
├── documents/           # Project specifications
├── tests/              # Test suite
└── CLAUDE.md           # This file
```

The codebase is currently in early development with the foundation (PocketFlow integration) and documentation infrastructure in place. The next phase involves implementing the core CLI interface and node registry system.