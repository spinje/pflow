# Project Context for Task 2: Set up basic CLI for argument collection

**File Location**: `.taskmaster/tasks/task_2/project-context.md`

*Created by sub-agents on: 2025-06-28*
*Purpose: Provide focused project understanding for ALL subtasks of this task*

## Task Domain Overview

This task focuses on creating the basic CLI argument collection layer for pflow - the entry point that accepts raw command-line input from users. This is a foundational component that will receive both natural language commands and CLI pipe syntax (e.g., `node1 --param=val >> node2`), collecting everything as raw input without parsing or interpreting the `>>` operator. The raw input will later be passed to the planner for processing.

The CLI layer serves as the user's primary interface to pflow and must handle various input patterns while remaining simple and focused on collection rather than interpretation.

## Relevant Components

### CLI Interface Layer
- **Purpose**: Accept and collect all command-line arguments from users
- **Responsibilities**:
  - Receive natural language commands (quoted strings)
  - Receive CLI pipe syntax (unquoted node chains)
  - Collect all arguments as raw list or string
  - Pass raw input to downstream components (planner)
- **Key Files**: `src/pflow/cli/main.py` (existing), `src/pflow/cli.py` (to be created)
- **How it works**: Uses click framework to handle command parsing and argument collection

### Click Framework Integration
- **Purpose**: Provides robust CLI parsing and command structure
- **Responsibilities**:
  - Handle various argument formats
  - Provide help text and error messages
  - Enable subcommand structure (already using @click.group)
- **Interactions**: Forms the foundation for all CLI operations

### Future Integration Points
- **Purpose**: Understanding where collected arguments will flow
- **Responsibilities**:
  - Planner will receive raw input for processing
  - Shell integration will detect stdin input
  - Registry will validate node names
- **Key concept**: Task 2 only collects; interpretation happens elsewhere

## Core Concepts

### Raw Argument Collection
- **Definition**: Accepting all CLI input without parsing or interpreting special operators like `>>`
- **Why it matters for this task**: Keeps the CLI layer simple and focused
- **Key terminology**: "raw input", "argument collection", "unparsed syntax"

### CLI Resolution Philosophy
- **Definition**: "Type flags; engine decides" - the CLI collects everything and lets downstream components decide what to do with it
- **Why it matters**: Simplifies the mental model for both users and implementers
- **Relationships**: Enables both natural language and CLI pipe syntax through same interface

### Entry Point Architecture
- **Definition**: The CLI serves as the single entry point for all pflow operations
- **Why it matters**: All user interactions flow through this component
- **Key principle**: Collect now, interpret later

## Architectural Context

### Where This Fits
The CLI layer sits at the very top of the pflow architecture, serving as the user interface layer. It's the first component users interact with and the gateway to all pflow functionality. The collected arguments flow from CLI → Parser → Planner → Runtime.

### Data Flow
1. User types command: `pflow read-file --path=input.txt >> llm --prompt="Summarize"`
2. CLI collects entire command as raw input
3. Raw input passed to parser/planner (future tasks)
4. Planner interprets syntax and generates workflow
5. Runtime executes the workflow

### Dependencies
- **Upstream**: User input from terminal
- **Downstream**: Parser and Planner components (future tasks)
- **Framework**: Click library for CLI functionality

## Constraints and Conventions

### Technical Constraints
- **No parsing of >> operator**: This task only collects arguments, doesn't interpret them
- **Must handle various input formats**: Quoted strings, unquoted chains, flags, etc.
- **Click framework patterns**: Must follow click conventions for commands and options

### Project Conventions
- **Naming**: CLI commands use kebab-case (e.g., `read-file`)
- **Patterns**: Modular command structure using click.group()
- **Style**: Clear help text and error messages

### Design Decisions
- **Click over alternatives**: Chosen for flexibility and robustness
- **Raw collection approach**: Simplifies implementation and enables future flexibility
- **No interpretation in CLI layer**: Keeps concerns separated

## Key Documentation References

### Essential pflow Documentation
- `docs/reference/cli-reference.md` - Comprehensive CLI syntax and design philosophy
- `docs/features/cli-runtime.md` - How CLI arguments flow through the system
- `docs/architecture/architecture.md#5.1` - CLI layer architecture and resolution algorithm
- `docs/features/mvp-scope.md` - MVP boundaries and what's included/excluded
- `docs/features/planner.md#3.2` - How the planner will process CLI input

### PocketFlow Documentation (if applicable)
- Not directly applicable for this task as we're only building the CLI collection layer

*These references should be included in the decomposition plan to guide subtask generation.*

## Key Questions This Context Answers

1. **What am I building/modifying?** A basic CLI using click that collects all command-line arguments as raw input without parsing the `>>` operator or interpreting node syntax.

2. **How does it fit in the system?** It's the entry point that collects user input and passes it to the planner. It doesn't parse or interpret - just collects.

3. **What rules must I follow?** Use click framework patterns, handle both quoted (natural language) and unquoted (CLI syntax) input, don't parse `>>` operator, pass everything as raw input.

4. **What existing code should I study?** The existing click.group() setup in `src/pflow/cli/main.py` from Task 1, which provides the foundation to build upon.

## What This Document Does NOT Cover

- How to parse the `>>` operator (that's for the planner)
- How to interpret node syntax (future task)
- How to execute workflows (runtime concern)
- Natural language processing (planner responsibility)

---

*This briefing was synthesized from project documentation to provide exactly the context needed for this task, without overwhelming detail.*

**Note**: This document is created ONCE at the task level and shared by ALL subtasks. It is created by the first subtask and read by all subsequent subtasks.
