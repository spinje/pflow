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
- `Python 3.9+` - Modern Python
- `click` - CLI framework (more flexible than Typer)
- `pydantic` - IR/metadata validation
- `llm` - Simon Willison's LLM CLI integration and inspiration

**Development Tools**:
- `uv` - Fast Python package manager (ALWAYS use `uv pip` instead of `pip`, `uv python -m pytest` instead of `python -m pytest` etc.)
- `pytest` - Testing framework
- `mypy` - Type checking
- `ruff` - Linting and formatting
- `pre-commit` - Git hooks
- `mkdocs` - Documentation
- `make` - Development automation

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
├── Makefile                # Development automation
├── pyproject.toml          # Project configuration and dependencies
├── uv.lock                 # Dependency lockfile for uv
├── docs/                   # User-facing documentation (mkdocs)
├── architecture/           # Architecture and design specifications
├── examples/               # Example workflows and usage patterns
├── scripts/                # Development and debugging scripts
├── tools/                  # Developer tools and test utilities
├── pocketflow/             # Embedded PocketFlow framework
│   ├── __init__.py         # Core PocketFlow classes (Node, Flow, Shared Store)
│   ├── docs/               # PocketFlow documentation
│   ├── cookbook/           # PocketFlow example flows and patterns
│   ├── research/           # PocketFlow research notes
│   ├── tests/              # PocketFlow test suite
│   └── PFLOW_MODIFICATIONS.md # Notes on PocketFlow changes for pflow
├── src/pflow/              # Main pflow implementation
│   ├── cli/                # CLI entrypoints and subcommands
│   │   ├── main.py         # Primary CLI (run workflows, I/O handling, validation)
│   │   ├── main_wrapper.py # Routes first arg to mcp/registry/workflow/settings groups
│   │   ├── mcp.py          # MCP server/tool management commands
│   │   ├── registry.py     # Registry commands (list/search/describe/scan/run/discover)
│   │   ├── registry_run.py # Execute a single node from registry with params
│   │   ├── discovery_errors.py # Shared error handling for LLM discovery flows
│   │   ├── rerun_display.py    # Builds safe rerun commands, masking secrets
│   │   ├── repair_save_handlers.py # Save repaired workflows (saved/file/planner sources)
│   │   ├── cli_output.py    # Click-based OutputInterface adapter
│   │   └── commands/        # CLI command groups
│   │       ├── settings.py  # Settings management (allow/deny, show, reset, check)
│   │       └── workflow.py  # Manage saved workflows (list/describe)
│   ├── core/                # Core schemas, settings, validation, and utilities
│   │   ├── exceptions.py    # Exception types (planner/runtime/validation)
│   │   ├── ir_schema.py     # Workflow IR schema and validation helpers
│   │   ├── llm_config.py    # Default LLM detection via llm CLI and env
│   │   ├── llm_pricing.py   # Centralized pricing and LLM cost calculations
│   │   ├── metrics.py       # MetricsCollector for durations, tokens, costs
│   │   ├── output_controller.py # Interactive vs non-interactive output routing
│   │   ├── security_utils.py    # Sensitive parameter detection and masking
│   │   ├── settings.py      # PflowSettings manager with allow/deny filters
│   │   ├── shell_integration.py # Robust stdin handling (text/binary/large)
│   │   ├── suggestion_utils.py  # "Did you mean" suggestions for workflow/node names
│   │   ├── user_errors.py   # User-friendly CLI error types and formatting
│   │   ├── validation_utils.py # Parameter name validation helpers
│   │   ├── workflow_data_flow.py # Data-flow validation and execution order
│   │   ├── workflow_manager.py   # Saved workflow storage and metadata
│   │   ├── workflow_save_service.py # Shared workflow save functions (CLI/MCP)
│   │   └── workflow_validator.py # Unified workflow validation pipeline
│   ├── execution/           # Execution UX and reusable services
│   │   ├── display_manager.py   # UX display coordination via OutputInterface
│   │   ├── execution_state.py   # Per-node execution state building
│   │   ├── executor_service.py  # Reusable workflow execution service (IR -> run)
│   │   ├── null_output.py       # No-op OutputInterface implementation
│   │   ├── output_interface.py  # Output interface/protocol for display backends
│   │   ├── repair_service.py    # Validation-driven auto-repair flow
│   │   ├── workflow_diff.py     # Compute diffs between original and repaired IR
│   │   ├── workflow_execution.py # Orchestrates validate/repair/execute cycle
│   │   └── formatters/      # Shared formatters for CLI/MCP parity (return, never print)
│   ├── mcp/                 # Model Context Protocol integration for MCP nodes in workflows
│   │   ├── auth_utils.py    # Auth/config helpers for MCP servers
│   │   ├── discovery.py     # Server discovery and config utilities
│   │   ├── manager.py       # Manage MCP server configurations
│   │   ├── registrar.py     # Register/sync MCP tools into pflow registry
│   │   ├── types.py         # Typed structures for MCP configs and tools
│   │   └── utils.py         # Parsing and utility helpers (server/tool IDs)
│   ├── mcp_server/          # MCP server exposing pflow as programmatic tools for AI agents
│   │   ├── main.py          # Server startup, Anthropic model install, signal handling
│   │   ├── server.py        # FastMCP instance and tool registration
│   │   ├── resources/       # MCP resources (prompts, instructions)
│   │   ├── tools/           # MCP tool implementations (async layer)
│   │   ├── services/        # Business logic layer (sync, stateless)
│   │   └── utils/           # MCP-specific utilities
│   │       ├── errors.py            # Error sanitization for LLM safety
│   │       ├── resolver.py          # Workflow resolution (dict/name/path)
│   │       └── validation.py        # Path/parameter security validation
│   ├── nodes/               # Platform node implementations
│   │   ├── claude/          # Claude Code integration nodes
│   │   ├── file/            # Local filesystem operations (read/write/copy/move/delete)
│   │   ├── git/             # Git operations (status/commit/push/checkout/log/tag)
│   │   ├── github/          # GitHub API nodes (issues/PRs/listing)
│   │   ├── http/            # HTTP request node
│   │   ├── llm/             # General-purpose LLM node
│   │   ├── mcp/             # MCP tool bridge node
│   │   ├── shell/           # Shell command execution node
│   │   └── test/            # Internal test/demo nodes
│   ├── planning/            # Natural language planner system
│   │   ├── context_blocks.py    # Reusable blocks for planner context strings
│   │   ├── context_builder.py   # Builds planning context, two-phase discovery
│   │   ├── flow.py              # Planner meta-workflow orchestration
│   │   ├── nodes.py             # Planner node orchestration and selection logic
│   │   ├── ir_models.py         # Pydantic models for planner IR/intermediate outputs
│   │   ├── debug.py             # Planner debugging helpers and pretty output
│   │   ├── error_handler.py     # Structured error handling for planner failures
│   │   ├── utils/               # Helper modules for planner
│   │   │   ├── anthropic_llm_model.py   # Install/patch Anthropic model for planner/tests
│   │   │   ├── anthropic_structured_client.py # Client helpers for Anthropic
│   │   │   ├── llm_helpers.py           # Common LLM call wrappers and schema helpers
│   │   │   ├── prompt_cache_helper.py   # Prompt caching utilities
│   │   │   ├── registry_helper.py       # Registry querying and normalization
│   │   │   └── workflow_loader.py       # Load workflows for planner context
│   │   └── prompts/         # Prompt definitions (markdown + loaders)
│   │       └── archive/     # Archived/legacy prompt variants
│   ├── registry/            # Node registry and scanning
│   │   ├── metadata_extractor.py # Docstring/interface metadata extraction
│   │   ├── registry.py      # Central registry load/save/filter/search
│   │   └── scanner.py       # Discover nodes from modules and folders
│   └── runtime/             # Runtime compilation, validation, and tracing
│       ├── compiler.py          # Compile IR to PocketFlow Flow/Nodes
│       ├── instrumented_wrapper.py # Instrument nodes for metrics/tracing
│       ├── namespaced_store.py  # Namespaced shared store with collision safety
│       ├── namespaced_wrapper.py # Namespacing wrapper for nodes
│       ├── node_wrapper.py      # General node wrapper utilities
│       ├── output_resolver.py   # Resolve output routing and keys
│       ├── template_resolver.py # Resolve ${var} with inputs/shared store
│       ├── template_validator.py # Validate template paths using node interfaces
│       ├── workflow_executor.py # Workflow execution orchestration
│       ├── workflow_trace.py    # Structured execution trace and metrics
│       └── workflow_validator.py # Runtime validation used by compiler/executor
├── tests/                   # Test suite organized by area
│   ├── shared/              # Shared test utilities and fixtures
│   │   ├── README.md        # Usage docs for shared testing utilities
│   │   ├── llm_mock.py      # LLM-level mock preventing real API calls
│   │   ├── planner_block.py # Fixture to block planner import for fallback tests
│   │   └── registry_utils.py # Ensure a test registry from core nodes
│   ├── test_cli/            # CLI tests
│   ├── test_core/           # Core modules tests
│   ├── test_docs/           # Docs/link validation tests
│   ├── test_execution/      # Execution/repair service tests
│   │   └── formatters/      # Formatter tests (CLI/MCP parity, security)
│   ├── test_integration/    # End-to-end workflow tests
│   ├── test_mcp/            # MCP integration tests (client-side MCP node/server integration)
│   ├── test_mcp_server/     # MCP server tests (pflow-as-MCP-server)
│   ├── test_nodes/          # Node implementation tests
│   │   ├── test_claude/     # Claude nodes
│   │   ├── test_file/       # File nodes
│   │   ├── test_git/        # Git nodes
│   │   ├── test_github/     # GitHub nodes
│   │   ├── test_http/       # HTTP node
│   │   ├── test_llm/        # LLM node
│   │   ├── test_mcp/        # MCP node
│   │   └── test_shell/      # Shell node
│   ├── test_planning/       # Planner tests (behavior, prompts, integration)
│   ├── test_registry/       # Registry/scanner tests
│   └── test_runtime/        # Runtime/compiler/executor tests
├── .taskmaster/             # Task management and planning
└── CLAUDE.md                # This guide for agents working in the repo
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

**Utilizing subagents**:
- Always use `pflow-codebase-searcher` when gathering information, context, do research and verifying assumptions if the check is not a trivial check. This is important, it is the only way to avoid running out of context window when working on complex tasks.
- Always use the `test-writer-fixer` subagent to write or fix broken tests. Remember to give it small tasks, never more than fixes for one file at a time. Provide the subagent with a comprehensive context and instructions and ask it to make a plan first, before it starts implementing.
- Consider using the `code-implementer` subagent when implementing new features or fixing bugs. This agent should only be used for tasks that require no special knowledge of the codebase and specific implementation details, and only for tasks that are small and isolated.

> Important: When utilizing subagents, you should always deploy them in parallel, never sequentially. This means using ONE function call block to deploy all neeeded subagents simultaneously.

### Documentation Navigation

**For detailed implementation guidance and documentation navigation**, see `architecture/CLAUDE.md`. This file provides:
- Implementation order with pocketflow prerequisites
- Feature-to-pattern mapping
- Critical warnings for AI implementation
- Navigation patterns for finding information

### Documentation Resources

**Extensive Markdown Documentation** should be leveraged by Claude:

> Always read relevant docs before coding or updating existing documentation!

#### Pflow Project Documentation

**Pflow Project Documentation**:

**`architecture/index.md`**: Comprehensive file-by-file inventory of all pflow documentation. Read this first to understand what documentation is available.

Folders:
- `architecture/features/`: Feature specifications and guides
- `architecture/core-concepts/`: Core concepts and patterns (shared store, schemas, registry, runtime)
- `architecture/reference/`: CLI syntax and execution reference
- `architecture/core-node-packages/`: Platform node specifications
- `architecture/implementation-details/`: Detailed implementation guides
- `architecture/future-version/`: Post-MVP features
- `architecture/architecture/`: System architecture and design

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

> Remember: Proactively use subagents when reading documentation, examples and codeexcept for small lookups. If you need specific information, ask a subagent to do the research for you, tailor the prompt to the task at hand and provide as much context as possible.

### Current State of the Project

The codebase is in early development with these tasks completed:
- ✅ PocketFlow framework added to the codebase including `pocketflow/docs` and `pocketflow/cookbook`
- ✅ Comprehensive documentation infrastructure in `architecture/`
- ✅ Development tooling and testing setup
- ✅ Task 1: Package setup and CLI entry point with `pflow` command and version subcommand
- ✅ Task 2: Basic CLI run command with stdio/stdin support
- ✅ Task 3: Execute a Hardcoded 'Hello World' Workflow
- ✅ Task 4: Implement IR-to-PocketFlow Object Converter
- ✅ Task 5: Node discovery and registry implementation
- ✅ Task 6: Define JSON IR schema
- ✅ Task 7: Extract node metadata from docstrings
- ✅ Task 8: Build comprehensive shell pipe integration with stdin/stdout
- ✅ Task 11: Implement read-file and write-file nodes
- ✅ Task 16: Create planning context builder
- ✅ Task 14: Implement type, structure, description and semantic documentation for all Interface components
- ✅ Task 15: Extend context builder for two-phase discovery and structure documentation support (modify and extend the context builder implemented in Task 16)
- ✅ Task 18: Template Variable System
- ✅ Task 19: Implement Node Interface Registry (Node IR) for Accurate Template Validation - moved interface parsing to scan-time, eliminating false validation failures
- ✅ Task 20: Implement Nested Workflow Execution
- ✅ Task 21: Implement Workflow Input Declaration - workflows to declare their expected input and output parameters in the IR schema
- ✅ Task 24: Implement Workflow Manager (A centralized service that owns the workflow lifecycle - save/load/resolve)
- ✅ Task 12: Implement LLM Node - Create a general-purpose LLM node - infinitely reusable building block by combining prompts with template variables
- ✅ Task 26: Implement GitHub and Git Operation Nodes - 9 nodes for GitHub/Git automation
- ✅ Task 17: Implement Natural Language Planner System (complete planner meta-workflow that transforms natural language into workflows)
- ✅ Task 30: Refactor Validation Functions from compiler.py
- ✅ Task 31: Refactor Test Infrastructure - Mock at LLM Level
- ✅ Task 27: Implement intuitive debugging capabilities and tracing system for the planner
- ✅ Task 9: Implement shared store collision detection using automatic namespacing
- ✅ Task 33: Extract planner prompts to markdown files in `src/pflow/planning/prompts/` and improve/create test cases for each prompt in `tests/test_planning/llm/prompts/`
- ✅ Task 34: Prompt Accuracy Tracking System for planner prompts
- ✅ Task 35: Migrate Template Syntax from $variable to ${variable}
- ✅ Task 36: Update Context Builder for Namespacing Clarity
- ✅ Task 37: Implement API Error Handling with User-Friendly Messages
- ✅ Task 40: Improve Workflow Validation and Consolidate into Unified System
- ✅ Task 41: Implement Shell Node
- ✅ Task 28: Improve performance of planner by modifying prompts (Discovery, Component Browsing, Metadata Generation, Parameter Prompts, Workflow Generator)
- ✅ Task 43: MCP Server support
- ✅ Task 32: Unified Metrics and Tracing System for User Workflow Execution
- ✅ Task 10: Create registry CLI
- ✅ Task 50: Node Filtering System with Settings Management json file
- ✅ Task 22: Named workflow execution
- ✅ Task 53: Add Rerun Command Display
- ✅ Task 55: Fix Output Control for Interactive vs Non-Interactive Execution
- ✅ Task 54: Implement HTTP
- ✅ Task 57: Update planner integration-tests to use better test cases with real world north star examples
- ✅ Task 58: Update workflow generator prompt-tests to use better real world test cases
- ✅ Task 63: Implement Pre-Execution Risk Assessment System for shell nodes
- ✅ Task 52: Improve planner with "plan" and "requirements" steps + prompt caching + thinking
- ✅ Task 47: Implement MCP http transport
- ✅ Task 67: Use MCP Standard Format
- ✅ Task 56: Implement Runtime Validation and Error Feedback Loop for planner
- ✅ Task 68: Separate RuntimeValidation from planner and refactor Workflow Execution
- ✅ Task 70: Design and Validate MCP-Based Agent Infrastructure Architecture
- ✅ Task 71: Extend CLI Commands with tools for agentic workflow building
- ✅ Task 76: Implement Registry Execute Command for Independent Node Testing by agents
- ✅ Task 80: Implement API Key Management via Settings
- ✅ Task 82: Implement System-Wide Binary Data Support
- ✅ Task 72: Implement MCP Server for pflow (expose pflow commands as MCP tools to AI agents)
- ✅ Task 84: Implement Schema-Aware Type Checking for Template Variables
- ✅ Task 85: Runtime Template Resolution Hardening
- ✅ Task 89: Implement Structure-Only Mode and Selective Data Retrieval
- ✅ Task 83: Pre-Release Security and Code Quality Audit

Next up:
To be determined...

Next version (post-MVP/post-Launch):
- ⏳ Task 49: Prepare and Publish `pflow-cli` to PyPI
- ⏳ Task 88: Benchmarking pflow with MCPMark Evaluation
- ⏳ Task 86: MCP Server Discovery and Installation Automation
- ⏳ Task 46: Workflow Export to Zero-Dependency Code
- ⏳ Task 91: Export Workflows as Self-Hosted MCP Server Packages
- ⏳ Task 59: Add support for nested workflows
- ⏳ Task 38: Support conditional Branching in Generated Workflows
- ⏳ Task 39: Support Parallel Execution in Workflows
- ⏳ Task 73: Implement Checkpoint Persistence for External Agent Repair ans workflow iteration
- ⏳ Task 81: Expose tools that lets users/agents find and install existing remote mcp servers
- ⏳ Task 78: Save User Request History in Workflow Metadata
- ⏳ Task 75: Execution Preview in Validation
- ⏳ Task 74: Create knowledge base system
- ⏳ Task 77: Improve Agent Instructions
- ⏳ Task 65: MCP Gateway Integration Support

Later:
- ⏳ Task 51: Refactor CLI main.py
- ⏳ Task 44: Build caching system
- ⏳ Task 45: Evaluate if wrapping or integrating n8n is worth the effort
- ⏳ Task 92: Replace Planner with Agent Node + Pflow MCP Tools
- ⏳ Task 62: Enhance Parameter Discovery to Route stdin to Workflow Inputs
- ⏳ Task 87: Implement sandbox runtime for Shell Node
- ⏳ Task 64: MCP Orchestration with long running servers
- ⏳ Task 79: Show tool definitions as structured JSON
- ⏳ Task 66: Support structured output for LLM node
- ⏳ Task 69: Refactor Internal Repair system to use Pocketflow
- ⏳ Task 61: Implement Fast Mode for Planner
- ⏳ Task 60: Support Gemini models for planner


Cloud Platform:
- ⏳ Task 90: Expose Individual Workflows as Remote HTTP MCP Servers

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

### Implementation Guidelines and

Enforced by `mypy` and `ruff`:

#### Type Hints

- Always type all function parameters and returns
```python
   def process(data: list[str], count: int = 10) -> dict[str, int]:
```
- Use Optional[T] for nullable arguments
```python
   from typing import Optional
   def fetch(url: str, timeout: Optional[int] = None) -> dict:
```
- Use lowercase built-in types (Python 3.9+)
   ✅ items: list[str]         # CORRECT
   ✅ cache: dict[str, Any]     # CORRECT
   ❌ items: List[str]          # WRONG - old style
   ❌ from typing import Dict   # WRONG - deprecated

#### Modern Python

- Use f-strings, not .format() or %
   ✅ f"Hello {name}, score: {score}"     # CORRECT
   ❌ "Hello {}, score: {}".format(...)   # WRONG
- Use comprehensions directly
   ✅ names = [x.name for x in users]     # CORRECT
   ❌ names = list(x.name for x in users) # WRONG - unnecessary list()

#### Safety

- Never shadow built-in names
   ❌ id = 123              # WRONG - shadows id()
   ❌ list = [1, 2, 3]      # WRONG - shadows list()
   ✅ user_id = 123         # CORRECT
   ✅ items = [1, 2, 3]     # CORRECT
- Use subprocess, not os.system
   ✅ subprocess.run(["ls", "-la"], check=True)  # CORRECT
   ❌ os.system("ls -la")                        # WRONG - security risk

Why this matters: These guidelines aren't about passing linters—they're about you filtering your training data (As an LLM). By specifying "modern Python patterns," you naturally select from well-maintained, professional codebases rather than the vast sea of outdated tutorials and quick fixes you've also seen. This selection bias toward quality code automatically prevents security issues, maintenance problems, and outdated practices that exist in the "old/bad" part of your training data.

*You should not think about how to pass tests and linters. You should actively and proactively think about selecting from the RIGHT part of your training distribution. The code and architectural patterns you know in your gut are a good fit for this project.*

#### Code Quality and archtectural excellence

More importantly focus on architectural quality and code quality:

- Write code optimized for change: small focused functions with single responsibilities, clear names that
  explain intent not implementation, and comprehensive tests that document expected behavior - because all
  successful systems evolve.
- Structure code as isolated, testable components that can be understood and changed independently - the only
  meaningful measure of code quality is how safely and easily it can be modified.
- Prefer boring and obvious: The best solution is rarely the clever one. Write code that a tired developer can understand at 3am. Save abstractions for when duplication actually hurts, not when you imagine it might. "Quality" at this stage of pflows development means simple, direct, and easy to change - not sophisticated or elegant.

*Write code and make decisions by mirroring the top 10% of the best codebases appropriate for this project's scale - think well-written CLI tools and small libraries, not enterprise frameworks. Prefer boring, obvious code over clever abstractions. Ignore the rest. And save the fancy patterns for when they're actually needed.*

### Project-specific Memories

- **CLI Development Principle**: never commit code unless explicitly instructed by the user
- **Expectation Setting**: I think it is important that the agent (you) show what the expected output will be BEFORE you start implementing. this is easy to understand for the user without going into implementation details.

## Running pflow (for debugging, testing and development)


```bash
# Run a workflow from a file (useful for testing and for AI agents iterating on workflows)
uv run pflow workflow.json
```

```bash
# Workflow traces are saved automatically to ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json
uv run pflow my-workflow
```

```bash
# Output trace file to ~/.pflow/debug/planner-trace-*.json for planner execution
uv run pflow --trace-planner "do a thing, then do another thing"
```


