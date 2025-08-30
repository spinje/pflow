# Project Context for Task 1: Create package setup and CLI entry point

**File Location**: `.taskmaster/tasks/task_1/project-context.md`

*Created by sub-agents on: 2025-06-27*
*Purpose: Provide focused project understanding for ALL subtasks of this task*

## Task Domain Overview

This task establishes the foundational package structure and CLI entry point for pflow - a workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands. The package setup is critical as it defines how users will install and invoke pflow, and establishes the structure for all subsequent development.

## Relevant Components

### Package Configuration (pyproject.toml)
- **Purpose**: Define package metadata, dependencies, and build configuration
- **Responsibilities**:
  - Specify project metadata (name, version, authors)
  - Declare dependencies (click, pydantic, llm)
  - Configure CLI entry points for the `pflow` command
  - Set up development tools (pytest, mypy, ruff)
- **Key Files**: `pyproject.toml`
- **How it works**: Uses modern Python packaging standards with hatchling as the build backend

### CLI Interface Layer
- **Purpose**: Provide the primary user interface for composing and executing flows
- **Responsibilities**:
  - Parse CLI commands using click framework
  - Handle the `>>` operator for flow composition
  - Resolve flags according to "Type flags; engine decides" philosophy
  - Support both CLI pipe syntax and natural language input
- **Key Files**: To be created in `src/pflow/cli/`
- **Interactions**: Entry point connects to parser, planner, and runtime components

### Source Package Structure
- **Purpose**: Organize code following Python best practices
- **Current State**:
  - `src/pflow/__init__.py` (empty)
  - `src/pflow/foo.py` (placeholder to be replaced)
- **Target Structure**: Will house CLI, planner, runtime, registry, and node modules

## Core Concepts

### Click Framework
- **Definition**: More flexible CLI framework than Typer, used for building the pflow interface
- **Why it matters for this task**: Click will handle command parsing, flag resolution, and help generation
- **Key terminology**: Commands, groups, options, arguments, contexts

### Entry Points
- **Definition**: Python's mechanism for exposing console scripts
- **Why it matters**: Enables users to run `pflow` command after installation
- **Configuration**: Defined in pyproject.toml's `[project.scripts]` section

### "Type Flags; Engine Decides" Philosophy
- **Definition**: Single mental model where users type flags and the engine determines their purpose
- **Relevance**: Influences how the CLI parser will categorize flags into data injection, node parameters, or system flags
- **Implementation**: Will be core to the flag resolution algorithm

## Architectural Context

### Where This Fits

The package setup and CLI entry point form the outermost layer of pflow's architecture:

```
User → CLI Entry Point → CLI Parser → Planner → Runtime → Nodes
         ^
         |
    (This task)
```

This establishes the foundation that all other components build upon.

### Data Flow

1. User types `pflow` command with nodes and flags
2. Entry point invokes CLI parser (click-based)
3. Parser resolves flags and creates flow structure
4. Flow structure passed to planner for validation
5. Validated flow executed by runtime

### Dependencies
- **Upstream**: None - this is the entry point
- **Downstream**:
  - CLI parser will depend on the entry point structure
  - All other components accessed through the CLI interface
  - Test infrastructure depends on proper package setup

## Constraints and Conventions

### Technical Constraints
- **Python 3.9+**: Minimum Python version per pyproject.toml
- **Click Framework**: Must use click for CLI (not Typer)
- **Package Structure**: Must use src-layout (`src/pflow/`)
- **Build System**: Uses hatchling per existing configuration

### Project Conventions
- **Naming**:
  - Package name: `pflow`
  - CLI command: `pflow`
  - Module names: lowercase with underscores
- **Patterns**:
  - Modular structure with clear separation of concerns
  - CLI as primary interface (no GUI in MVP)
- **Style**:
  - Follow ruff configuration in pyproject.toml
  - Type hints required (mypy strict mode)

### Design Decisions
- **Click over Typer**: More flexibility for complex CLI patterns
- **src-layout**: Better testing isolation and import clarity
- **Entry point design**: Single `pflow` command with subcommands/modes

## Key Questions This Context Answers

1. **What am I building/modifying?**
   Setting up the Python package structure and creating the CLI entry point that users will invoke as `pflow`

2. **How does it fit in the system?**
   This is the foundational layer - the entry point through which all user interactions flow into the pflow system

3. **What rules must I follow?**
   - Use click framework for CLI
   - Follow src-layout structure
   - Configure entry point in pyproject.toml
   - Ensure `pip install -e .` works correctly

4. **What existing code should I study?**
   - Current pyproject.toml configuration
   - CLI architecture documentation (architecture/architecture/architecture.md)
   - Click framework documentation for patterns

## What This Document Does NOT Cover

- Detailed CLI command parsing logic (future subtask)
- Specific node implementations (separate tasks)
- Planner or runtime implementation (later tasks)
- Natural language processing details (post-MVP priority)

---

*This briefing was synthesized from project documentation to provide exactly the context needed for this task, without overwhelming detail.*

**Note**: This document is created ONCE at the task level and shared by ALL subtasks. It is created by the first subtask and read by all subsequent subtasks.
