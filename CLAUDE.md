# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

**Node System**: Registry, metadata extraction, two-tier AI approach with simple platform nodes

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
│   ├── **prd.md**                     # **CORE: Product requirements document**
│   ├── **architecture.md**            # **CORE: Complete system architecture**
│   ├── **mvp-scope.md**               # **CORE: Clear MVP boundaries**
│   ├── **simple-nodes.md**           # Simple node design pattern
│   ├── shared-store.md               # Shared store + proxy pattern
│   ├── cli-runtime.md                # CLI integration and shared store runtime
│   ├── schemas.md                    # JSON IR and metadata schemas
│   ├── planner.md                    # Dual-mode planner (CLI + natural language)
│   ├── runtime.md                    # Execution engine, caching, safety
│   ├── registry.md                   # Node discovery, namespacing, versioning
│   ├── components.md                 # Complete MVP vs v2.0 breakdown
│   ├── shell-pipes.md                # Unix pipe support and stdin handling
│   ├── autocomplete.md               # CLI autocomplete specification (v2.0)
│   ├── mcp-integration.md            # MCP server integration (v2.0)
│   ├── workflow-analysis.md          # Technical analysis of AI workflow inefficiencies
│   ├── core-node-packages/           # Platform node package specifications
│   │   ├── github-nodes.md           # GitHub platform nodes (github-get-issue, github-create-pr, etc.)
│   │   ├── claude-nodes.md           # Claude Code CLI nodes (claude-analyze, claude-implement, etc.)
│   │   ├── ci-nodes.md               # CI platform nodes (ci-run-tests, ci-get-status, etc.)
│   │   └── llm-nodes.md              # General LLM node for text processing
│   ├── implementation-details/       # Implementation specifics
│   │   ├── metadata-extraction.md
│   │   └── autocomplete-impl.md
│   └── future-version/              # Post-MVP features
│       ├── llm-node-gen.md
│       └── json-extraction.md
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
- `docs/prd.md`: Master product requirements and complete architectural vision
- `docs/architecture.md`: MVP-focused architecture document
- `docs/mvp-scope.md`: Clear MVP boundaries - what to build vs. exclude

**Core Patterns**:
- `docs/shared-store.md`: Fundamental shared store + proxy pattern
- `docs/cli-runtime.md`: CLI integration and shared store management
- `docs/schemas.md`: JSON IR and metadata schemas

**Implementation Specs**:
- `docs/planner.md`: Dual-mode planner (CLI + natural language)
- `docs/runtime.md`: Execution engine, caching, error handling
- `docs/registry.md`: Registry system and version management
- `docs/components.md`: Complete MVP vs v2.0 component breakdown

**Node Packages** (Two-Tier AI Architecture):
- `docs/core-node-packages/claude-nodes.md`: - Claude Code CLI nodes for development tasks (claude-analyze, claude-implement, claude-review)
- `docs/core-node-packages/llm-nodes.md`: - General LLM node for text processing and prompt generation
- `docs/core-node-packages/github-nodes.md`: GitHub platform nodes (github-get-issue, github-create-pr, etc.)
- `docs/core-node-packages/ci-nodes.md`: CI platform nodes (ci-run-tests, ci-get-status, etc.)
- `docs/implementation-details/metadata-extraction.md`: Metadata extraction system

**Shell Integration**:
- `docs/shell-pipes.md`: Unix pipe support and stdin handling
- `docs/workflow-analysis.md`: Technical analysis of AI workflow inefficiencies and detailed breakdown of the `project:fix-github-issue` slash command to pflow vision.

**Future Features**:
- `docs/autocomplete.md`: CLI autocomplete specification (v2.0)
- `docs/implementation-details/autocomplete-impl.md`: Detailed CLI autocomplete implementation (v2.0)
- `docs/mcp-integration.md`: MCP server integration (v2.0)
- `docs/future-version/llm-node-gen.md`: LLM-assisted node development (v3.0)
- `docs/future-version/json-extraction.md`: Advanced JSON field extraction (v3.0)


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
- ✅ PocketFlow framework added to the codebase
- ✅ Comprehensive documentation infrastructure in `docs/`
- ✅ Development tooling and testing setup
- ✅ Create an overview roadmap for the MVP in `todo/implementation-roadmap.md`
- ✅ Create a detailed todo list with tasks and subtasks in `todo/tasks.json` based on the roadmap
- ⏳ Carefully review the list of tasks to make sure every task is complete, accurate and that we are doing the right things in the right order (<- We are here)
- ⏳ Start implementing features for the MVP using the todo list one by one

### Current Development Phase

Focus on refining the tasks for the MVP by doing the following:
1. Ensure that the tasks are based on product requirements and architecture docs for the pflow project.
2. Ensure that the tasks dependent on pocketflow (the 100 lines of code in `pocketflow/__init__.py`) are using the pocketflow framework correctly by carefully reading the documentation in `pocketflow/docs` and examples in `pocketflow\cookbook` when needed.
3. Ensure that every tasks considers the dependencies and the order of implementation. The `todo/tasks.json` will need to be updated continously as you discover new information and discuss the user.
4. Ensure that every task is easy to understand and has a clear success criteria and test strategy.


## End goal and Vision for the MVP

The goal is a working MVP that can execute the core workflows:

**Start simple** (general text processing):
```bash
# Transform: Repeatedly asking AI "analyze these logs"
# Into: pflow analyze-logs --input=error.log (instant)
pflow read-file --path=error.log >> llm --prompt="extract error patterns and suggest fixes" >> write-file --path=analysis.md
```

**And move on to more complex workflows**:
LLM Agent like Claude Code executing all steps, reasoning between each step:

```markdown
# Transform: /project:fix-github-issue 1234 (Claude code slash command, 50-90s, heavy tokens)
# This is a Claude Code slash command (prompt shortcut) that was used as an example in an Anthropic blog post as a good example of how to efficiently use Claude Code.
Please analyze and fix the GitHub issue: $ARGUMENTS.

Follow these steps:

1. Use `gh issue view` to get the issue details
2. Understand the problem described in the issue
3. Search the codebase for relevant files
4. Implement the necessary changes to fix the issue
5. Write and run tests to verify the fix
6. Ensure code passes linting and type checking
7. Create a descriptive commit message
8. Push and create a PR

Remember to use the GitHub CLI (`gh`) for all GitHub-related tasks.
```

```bash
# Into: pflow fix-issue --issue=1234 (20-50s, minimal tokens)
github-get-issue --issue=1234 >> \
claude-code --prompt="<instructions>
                        1. Understand the problem described in the issue
                        2. Search the codebase for relevant files
                        3. Implement the necessary changes to fix the issue
                        4. Write and run tests to verify the fix
                        5. Return a report of what you have done as output
                      </instructions>
                      This is the issue: $issue" >> \
llm --prompt="Write a descriptive commit message for these changes: $code_report" >> \
git-commit --message="$commit_message" >> \
git-push >> \
github-create-pr --title="Fix: $issue_title" --body="$code_report"
```

> Note that in this core example we are still needing to use the `claude-code` node to execute parts of the workflow. For many use cases, using LLM as Agents will not be necessary and in these cases the speedup will be much greater and can potentially reach 10x or more by reducing the intermittent reasoning between each step that needs to happen in Agentic workflows.

But first, we need to create a detailed task list for the MVP.

## User Decisions during this process

Every time you need the user to make a decision, you should:
Create a `scratchpads/critical-user-decisions.md` file and write down the decision and the reasoning. Give at least 2 options with clear recommendations. Add a markdown checkbox for each option so the user can select the option they prefer easily.
