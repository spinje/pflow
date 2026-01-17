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

7. **Solve observed problems, not theorized ones.**
   Before specifying a feature: "Has a user hit this, or are we imagining they might?"

### Core Directive - Operational Precision

1. **Verify at integration points first.**
   Code boundaries, API contracts, and data handoffs hide 80% of failures. Start verification here, then work outward.

2. **Make uncertainty visible through structured decisions.**
   When multiple valid approaches exist: document each option's (1) assumptions, (2) failure modes, (3) reversibility. Never choose silently.

3. **Capture patterns, not just outcomes.**
   Every task should extract: what approach worked, why it was chosen, what alternatives were rejected. This compounds future effectiveness.

4. **Test your understanding through concrete examples.**
   Abstract comprehension fails at edges. Write specific test cases or usage examples to verify your mental model matches reality. Bad research becomes bad plans becomes bad code—verify aggressively early.

5. **Integration readiness > feature completeness.**
   Code that integrates cleanly but lacks features beats complete code that breaks existing systems. Design for composability first.

6. **When inheriting code/decisions, document your trust boundary.**
   Mark explicitly: "Verified", "Assumed correct", "Unable to verify". Future agents need to know where to focus skepticism.

7. **Prefer reversible decisions.**
   Users will prove you wrong. Help the user design for course correction, not commitment. Over-constrained specs create brittleness—leave room to navigate.

## Project Overview

We are building a modular, CLI-first system called `pflow`.

pflow is a CLI tool that runs workflows defined in JSON config files. AI agents (Claude Code, Cursor, etc.) can create these workflow files by calling pflow CLI commands, then run them later with `pflow my-workflow param1=value1 param2=value2`.

**How it works mechanically (simplified):**
1. AI agent (or legacy planner) generates a temporaryworkflow JSON file
2. Can run it with `pflow ./my-workflow.json param1=value1` while iterating on the workflow
3. When user is satisfied with the workflow, the Agent saves it with `pflow workflow save ./my-workflow.json --name my-workflow --description "Description of what it does"`
4. `pflow my-workflow` runs the saved workflow
5. Workflows are sequences of nodes: `shell`, `http`, `llm`, `file`, and dynamically loaded MCP tools

**Interfaces:**
- **Primary:** AI agents invoke pflow via CLI commands
- **Experimental:** AI agents can also use pflow via MCP server (`src/pflow/mcp_server/`)
- **Legacy:** Built-in planner for natural language → workflow (being phased out since most workflows needs to be iterated on rather than created in a one-shot prompt)

The goal is to enable local execution of intelligent workflows with the **minimal viable set of features**. This MVP will later evolve into a scalable cloud-native service.

**Core Principle**: Fight complexity at every step. Build minimal, purposeful components that extend without rewrites.

### Core Architecture

pflow is built on the **PocketFlow** framework (~150-line Python library in `pocketflow/__init__.py`).

> If you need to implement a new feature that includes using pocketflow, and dont have a good understanding of what pocketflow is or how it works always start by reading the source code in `pocketflow/__init__.py` and then the documentation in `pocketflow/docs` and examples in `pocketflow/cookbook` when needed.

- **Nodes**: Self-contained tasks (`prep()` → `exec()` → `post()`) that communicate through a shared store using intuitive keys (`shared["text"]`, `shared["url"]`)
- **Flows**: Orchestrate nodes into workflows (PocketFlow uses `>>` operator internally)
- **CLI**: Execute workflows, discover and test nodes, manage saved workflows and settings
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

**MVP Requirements** (0.6.0 - local-first CLI):
- Compose and run flows using `pflow` CLI
- Core nodes: `shell`, `http`, `llm`, `file` operations, MCP tools
- Store intermediate data in shared store
- Use shell pipe syntax for stdin/stdout integration
- Pure Python, single-machine, stateless
- Logging and tracing for debugging
- AI agents can create/run workflows via CLI


**Key Principles**:
- **PocketFlow Foundation**: Always consider `pocketflow/__init__.py` first and evaluate examples in `pocketflow/cookbook` for implementation reference
- **Shared Store Pattern**: All communication between nodes is done through the shared store
- **Deterministic Structure**: Workflow execution order is fixed; individual node outputs (especially `llm`) may vary
- **Atomic Nodes**: Nodes are isolated and focused on business logic only
- **Agent-Friendly CLI**: CLI commands are the primary interface for AI agents to discover, create and run workflows
- **Observability**: Clear logging and step-by-step traceability

### Technology Stack

**Core Dependencies** (discuss before adding others):
- `Python 3.10+` - Modern Python
- `click` - CLI framework (more flexible than Typer)
- `pydantic` - IR/metadata validation
- `llm` - Simon Willison's LLM CLI integration and inspiration

**Development Tools**:
- `uv` - Fast Python package manager (ALWAYS use `uv pip` instead of `pip`, `uv python -m pytest` instead of `python -m pytest` etc.)
- `pytest` - Testing framework
- `mypy` - Type checking
- `ruff` - Linting and formatting
- `pre-commit` - Git hooks
- `Mintlify` - Documentation (user-facing, in `docs/`)
- `make` - Development automation

### Architecture Components

pflow is built on PocketFlow and extends it for CLI-based workflow execution.

**PocketFlow Foundation** (see `pocketflow/__init__.py`):
- Node lifecycle: `prep()` → `exec()` → `post()`
- Flow orchestration with action-based transitions
- Shared store pattern for inter-node data
- `>>` operator for node chaining (used internally by compiler)

**pflow Extensions:**
- **CLI Layer**: Commands, stdin/stdout pipes, workflow save/load
- **IR Compiler**: JSON workflow → PocketFlow Flow/Node objects
- **Wrapper Chain**: Template resolution, namespacing, batch processing, instrumentation
- **Platform Nodes**: shell, http, llm, file, git, github, mcp, claude-code
- **Validation**: 6-layer pipeline (structure, data flow, templates, types, outputs)
- **Observability**: Metrics, tracing, MD5-based caching

### Project Structure

```
pflow/
├── README.md               # Project overview and user guide
├── Makefile                # Development automation
├── pyproject.toml          # Project configuration and dependencies
├── uv.lock                 # Dependency lockfile for uv
├── docs/                   # User-facing documentation (mintlify)
├── architecture/           # Architecture and design specifications
├── examples/               # Example workflows and usage patterns
├── scripts/                # Development and debugging scripts
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
│   │   ├── repair_service.py    # Validation-driven auto-repair flow (may be deprecated soon)
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
│   ├── planning/            # Natural language planner system (may be deprecated soon)
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
│   ├── test_planning/       # Planner tests (behavior, prompts, integration)
│   ├── test_registry/       # Registry/scanner tests
│   └── test_runtime/        # Runtime/compiler/executor tests
├── .taskmaster/             # Task management and planning
│   └──  tasks/              # Task implementation files for all tasks
│       └── task_<task-number>/         # Task <task-number> implementation files
│           ├── task-review.md # Task review
│           ├── task-<task-number>.md # Task specification
│           └── implementation/
│               └── progress-log.md # Progress tracking during development
│               └── implementation-plan.md # Implementation plan
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
- **Is the task too big?**: If the task is too big, break it down into phases
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

> Always read relevant docs before coding!

- **pflow docs**: `architecture/index.md` (inventory), `architecture/CLAUDE.md` (navigation)
- **PocketFlow docs**: `pocketflow/CLAUDE.md` (framework docs and cookbook)

> Proactively use `pflow-codebase-searcher` subagents in PARALLEL when reading documentation, examples and searching for code. If you need specific information, ask a subagent or multiple subagents to do the research for you, tailor the prompt to the task at hand and provide as much context as possible.

### Project Status

MVP feature-complete (65 tasks). Next milestone: v0.8.0 (PyPI release).

**Implemented Capabilities:**

**CLI & Execution:**
Run workflows by name or file, shell pipe integration, named workflow save/load, batch processing, registry CLI (list/search/describe), workflow input/output declarations
→ Tasks 8, 10, 21, 22, 24, 96

**Nodes:**
shell, http, llm (via llm library), file (read/write/copy/move/delete), git, github, mcp, claude-code
→ Tasks 11, 12, 26, 41, 42, 54, 95

**Templates & Data Flow:**
${var} syntax, schema-aware type checking, auto JSON parsing, shared store with namespacing
→ Tasks 9, 18, 84, 85, 103, 105

**Workflow Validation:**
Unified validation pipeline, pre-execution risk assessment for shell commands
→ Tasks 40, 63

**MCP Integration:**
MCP server support, http transport, pflow-as-MCP-server for agents
→ Tasks 43, 47, 67, 72

**Planner (legacy):**
Natural language → workflow, runtime validation feedback, debugging/tracing
→ Tasks 17, 27, 52, 56

**Settings & Security:**
Node filtering, API key management, binary data support, security audit complete
→ Tasks 50, 63, 80, 82, 83

**Observability:**
Metrics/tracing system, rerun command display, interactive/non-interactive output, user-friendly error messages
→ Tasks 32, 37, 53, 55

**Agent Support:**
CLI commands for agents, registry execute for node testing, LLM-powered discovery
→ Tasks 71, 76, 89

**Recently Completed:**
- Task 105: Auto-Parse JSON Strings During Nested Template Access
- Task 103: Preserve Inline Object Type in Template Resolution
- Task 102: Remove Parameter Fallback Pattern
- Task 96: Support Batch Processing in Workflows
- Task 95: Unify LLM Usage via Simon Willison's llm Library

**Planned:**

**v0.8.0 - PyPI & Authoring:**
- Task 49: Publish to PyPI
- Task 104: Python Code Node
- Task 107: Markdown Workflow Format
- Task 108: Smart Trace Debug Output

**v0.9.0 - Workflow Expressiveness:**
- Task 38: Conditional Branching
- Task 59: Nested Workflows

**v0.10.0 - Extended Features:**
- Task 46: Workflow Export to Zero-Dependency Code
- Task 75: Execution Preview in Validation
- Task 94: Display Available LLM Models
- Task 99: Expose Nodes as MCP Tools
- Task 111: Batch Limit for Iteration

**v0.11.0 - Performance:**
- Task 39: Parallel Execution
- Task 78: Save User Request History
- Task 88: MCPMark Benchmarking
- Task 106: Workflow Iteration Cache

**v1.0.0 - Security & Sandboxing:**
- Task 66: Structured Output for LLM Node
- Task 87: Sandboxed Execution Runtime
- Task 91: Export as MCP Server Packages
- Task 97: OAuth for Remote MCP Servers
- Task 109: Sandbox Bypass Controls

**v1.1.0 - MCP Ecosystem:**
- Task 65: MCP Gateway Integration
- Task 77: Improve Agent Instructions
- Task 81: Find/Install Remote MCP Servers
- Task 86: MCP Server Discovery Automation

**Later:**
- Task 45: Evaluate n8n integration
- Task 51: Refactor CLI main.py
- Task 62: Route stdin to Workflow Inputs
- Task 64: MCP Orchestration (long-running servers)
- Task 74: Knowledge base system
- Task 79: Tool definitions as JSON
- Task 90: Workflows as Remote HTTP MCP Servers
- Task 92: Replace Planner with Agent + MCP
- Task 98: First-Class IR Execution
- Task 100: Reduce/Fold for Batch
- Task 101: Shell Node File Input
- Task 110: PIPESTATUS Pipeline Detection
- Task 112: Pre-execution Type Validation
- Task 113: TypeScript Code Node
- Task 114: Lightweight Custom Nodes

> **Task commands:**
> ```bash
> ./scripts/tasks              # View summary
> ./scripts/tasks 104          # View specific task (or multiple: 104 103 110)
> ./scripts/tasks --search X   # Find tasks
> ```
>
> **Task files:** `.taskmaster/tasks/task_N/`
> **Version history:** `.taskmaster/versions.md`

> We are currently building the MVP and have NO USERS using the system. This means that we NEVER have to worry about backwards compatibility or breaking changes. However, we should never break existing functionality or rewrite breaking tests without carefully considering the implications.

## User Decisions and Recommendations

You are only able to provide information and recommendations—you cannot make decisions for the user.

**When you encounter a decision point:**

1. **Explain why a decision is needed.** What's the context? What's at stake? Frame it so it can be understood in isolation.

2. **Present at least 2 options with tradeoffs.** For each option: what's good about it, what's bad about it, and how reversible is it?

3. **Make a clear recommendation.** State which option you'd suggest and why.

4. **Gauge importance (1-5).** For low-stakes decisions (1-2) where you're confident, you may proceed. For anything higher, STOP—do not proceed to implementation until the user has decided and you clearly understand the decision and its implications.

If anything is unclear or ambiguous in the documentation, the user makes the call.

**Escalate when:**
- Architectural decisions affect multiple components
- Trade-offs have no clear winner after analysis
- Current approach contradicts established patterns
- Integration would break existing functionality

### Implementation Guidelines

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
# Workflow traces are saved automatically to ~/.pflow/debug/workflow-trace-[name-]YYYYMMDD-HHMMSS.json
uv run pflow my-workflow
```

```bash
# When you need full context for understanding how an AI agents should use pflow (only read this if you really need to)
uv run pflow instructions usage
```
