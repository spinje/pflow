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

5. **Build for the next agent's reasoning, not just this execution.**
   Code, tasks, subtasks, and documentation should stay re-reasonable and modifiable by whoever inherits them — design for the downstream reader, not just the current run.

6. **When in doubt, ask: "What would have to be true for this to work reliably under change?"**

7. **Solve observed problems, not theorized ones.**
   Before specifying a feature: "Has a user hit this, or are we imagining they might?"

### Core Directive - Operational Precision

1. **Verify at seams first.**
   Integration points — code boundaries, API contracts, data handoffs — hide 80% of failures. Start verification at your seams, then work outward.

2. **Make uncertainty visible through structured decisions.**
   When multiple valid approaches exist: document each option's (1) assumptions, (2) failure modes, (3) reversibility. Never choose silently.

3. **Capture patterns, not just outcomes.**
   Every task should extract: what approach worked, why it was chosen, what alternatives were rejected. This compounds future effectiveness.

4. **Test your understanding through concrete examples.**
   Abstract comprehension fails at edges. Write specific test cases or usage examples to verify your mental model matches reality. Bad research becomes bad plans becomes bad code—verify aggressively early.

5. **Integration readiness > feature completeness.**
   Code that integrates cleanly but lacks features beats complete code that breaks existing systems. Design for composability first — favor depth over feature surface.

6. **When inheriting code/decisions, document your trust boundary.**
   Mark each claim "Verified" — and name the evidence (file:line, the command you ran, the artifact you read) — "Assumed correct" — and name what would confirm it — or "Unable to verify". Future agents need to know where to focus skepticism.

7. **Prefer reversible decisions.**
   Users will prove you wrong. Help the user design for course correction, not commitment. Over-constrained specs create brittleness—leave room to navigate.

## Project Overview

**pflow** is a CLI-first workflow execution system. AI agents create markdown workflow files (`.pflow.md`), iterate on them via CLI, then save them for reuse. Workflows chain nodes (`shell`, `http`, `llm`, `file`, `mcp`, `python`, `claude-code`) that communicate through a shared store.

> **For conceptual understanding** (why pflow exists, core bets, design decisions): See `architecture/overview.md`
> **For technical architecture** (execution pipeline, abstractions, components): See `architecture/architecture.md`

**Core Principle**: Fight complexity at every step. Build minimal, purposeful components that extend without rewrites.

### Node Lifecycle Primitives

pflow's node system is built on `BaseNode` and `Node` (~90 lines in `src/pflow/core/node.py`). These provide the lifecycle (prep/exec/post), retry logic, and graph wiring operators (`>>`, `-`). The `WorkflowEngine` (in `src/pflow/runtime/engine/`) handles graph traversal and all runtime concerns.

> When implementing features that use nodes, start by reading `src/pflow/core/node.py`, then `src/pflow/nodes/CLAUDE.md` for node implementation patterns.

### Development Commands

```bash
make install                    # Install dependencies and pre-commit hooks
make test                      # Run all tests with pytest
make test-e2e                  # Run e2e tests with pytest
make check                     # Run all quality checks (lint, type check, etc.)
```

### Key Principles

- **Shared Store Pattern**: All node communication through shared store
- **Atomic Nodes**: Isolated, focused on business logic only
- **Agent-Friendly CLI**: Primary interface for AI agents
- **Structured Errors**: Raise `PflowError` subclasses from `src/pflow/core/exceptions.py`, never vanilla `ValueError`/`Exception`. In nodes, just raise — the engine handles retries. See `src/pflow/core/exceptions.py` for the hierarchy; `src/pflow/core/CLAUDE.md` → `exceptions.py` section for the usage table.

### Technology Stack

**Core**: Python 3.10+, click, pydantic, LiteLLM via pflow's `llm_client` adapter

**Development** (ALWAYS use `uv` instead of `pip`):
- `uv` - Package manager (`uv pip`, `uv run pytest`)
- `pytest`, `mypy`, `ruff`, `pre-commit`, `make`

### Project Structure

> Every directory below has its own CLAUDE.md with file-level details.

```
pflow/
├── README.md                # Project overview and user guide
├── Makefile                 # Development automation
├── pyproject.toml           # Project configuration and dependencies
├── uv.lock                  # Dependency lockfile
├── docs/                    # User-facing documentation (mintlify)
├── architecture/            # Architecture and design specs
├── examples/                # Example workflows and usage patterns
├── scripts/                 # Development and debugging scripts
├── src/pflow/
│   ├── cli/                 # CLI entrypoints and subcommands
│   ├── core/                # Schemas, settings, validation, utilities, LLM/prompt utils
│   │   ├── workflow/        # Workflow lifecycle (manager, validator, save, skills, discovery)
│   │   └── prompt_cache_analysis/  # Prompt-cache cost & discrepancy analysis
│   ├── execution/           # Execution UX, formatters
│   ├── runtime/             # Compilation, engine, tracing
│   ├── nodes/               # Platform node implementations
│   │   └── (shell, http, llm, file, mcp, python, claude)
│   ├── mcp/                 # MCP client integration (for MCP nodes in workflows)
│   ├── mcp_server/          # pflow-as-MCP-server for AI agents
│   ├── registry/            # Node registry, scanning, context building, discovery
│   └── guide/               # `pflow guide` content — agent instructions (core/nodes/features)
├── tests/                   # Test suite
│   ├── fixtures/            # Shared test fixtures (e.g. cache_analysis workflows)
│   ├── shared/              # Shared utilities (llm_mock, markdown_utils, registry_utils)
│   ├── test_cli/            # CLI tests
│   ├── test_core/           # Core module tests
│   ├── test_docs/           # Docs/link validation
│   ├── test_execution/      # Execution tests (includes formatters/)
│   ├── test_integration/    # End-to-end workflow tests
│   ├── test_mcp/            # MCP client integration tests
│   ├── test_mcp_server/     # MCP server tests
│   ├── test_nodes/          # Node implementation tests
│   ├── test_registry/       # Registry/scanner/discovery tests
│   └── test_runtime/        # Runtime/compiler/executor tests
└── .taskmaster/             # Task management and planning
    └── tasks/task_N/        # Per-task specs, reviews, and progress logs
```

### Claude's Operating Guidelines

**Show Before You Code**: For any task that changes user-visible output, show concrete before/after examples and ask for confirmation before implementing. This takes 30 seconds but saves hours of rework.

**Reasoning-First Approach**: Every code generation task must:
1. Include rationale of *why* the task is needed and *how* it fits current architecture
2. Use consistent patterns (shared store, simple IO, single responsibility)
3. Avoid abstractions that don't pass the **deletion test** (see Code Quality)
4. Write tests AS YOU CODE (test-as-you-go):
   - Every new function/component needs test cases (quality over quantity)
   - Test public APIs, critical paths, error handling, and integration points
   - A task without tests is an INCOMPLETE task
   - NEVER mock what you can test directly

**Key Questions** for every task:
- **Purpose**: Why is this needed?
- **Dependencies**: What does this task depend on?
- **Documentation**: What docs and existing code do I need to read first?
- **Is the task too big?**: If so, break it down into phases
- **Test Strategy**: What tests will validate this?

**Development Standards**:
- Start small, build minimal components that can be expanded
- Capture the test baseline before you change code — which tests pass and which fail, by name — then re-run `make test` and `make check` before finalizing and report the delta. "No regressions" means nothing without a baseline you captured to diff against.
- Document decisions and tradeoffs
- Create `CLAUDE.md` files in each code directory to document code and reasoning
- Create scratch pads in `scratchpads/<conversation-subject>/` for deep thinking

**Utilizing subagents**:
- Use `pflow-codebase-searcher` for gathering information, research, and verifying assumptions (avoids exhausting context window). **Never use the `Explore` or general-purpose agents.**
- Subagents gather and cite; **you** own the conclusions. `pflow-codebase-searcher` is same-model and file-grounded — trust its citations, but check its conclusions follow from them, and confirm directly before anything irreversible or outward-facing.
- Read files directly with the `Read` tool when the path is known or when the user explicitly asks you to read something.
- Use `test-writer-fixer` for writing/fixing tests (small tasks, one file at a time, comprehensive context)
- Use `code-implementer` for small, isolated features/fixes that need no deep codebase knowledge
- Deploy subagents in **parallel** (one function call block), never sequentially

### Documentation

> Always read relevant docs before coding!

- **Architecture & navigation**: `architecture/CLAUDE.md` — documentation index, reading paths, implementation CLAUDE.md table
- **Node lifecycle primitives**: `src/pflow/core/node.py` — BaseNode, Node, wiring operators
- **Agent usage guide**: Run `pflow guide`

Proactively use `pflow-codebase-searcher` subagents in PARALLEL when reading documentation and searching for code.

### Project Status

MVP feature-complete. Published to PyPI (initial release v0.8.0; current version per `pyproject.toml`).

**What's implemented**: shell/http/llm/mcp/`code` (Python)/claude-code nodes plus five file-op nodes (read/write/copy/move/delete-file) — registry names, not directory names; template system (`${var}` with nested path access), batch processing, MCP integration (client + server), metrics/tracing, settings/security, CLI with Unix pipe support, workflow save/load, registry, skills publishing.

**Recently Completed:**
- ✅ Task 105: Auto-Parse JSON Strings During Nested Template Access
- ✅ Task 103: Preserve Inline Object Type in Template Resolution
- ✅ Task 96: Support Batch Processing in Workflows
- ✅ Task 115: Automatic Stdin Routing for Unix-First Piping
- ✅ Task 104: Python Code Node
- ✅ Task 107: Markdown Workflow Format (.pflow.md replaces JSON)
- ✅ Task 38: Conditional Branching in Workflows
- ✅ Task 59: Nested Workflows
- ✅ Task 128: Branch Convergence for Conditional Workflows
- ✅ Task 92: Remove Planning Module and Repair System
- ✅ Task 108: Smart Trace Debug Output
- ✅ Task 106: Workflow Iteration Cache
- ✅ Task 136: Recursive Sub-Workflow Validation at Parse Time
- ✅ Task 137: Unified CLI Output Pipeline
- ✅ Task 134: Output Detection Unification
- ✅ Task 138: Shared Execution Pipeline
- ✅ Task 135: Execution Core Compile-Once Redesign
- ✅ Task 141: Consolidate Exception Hierarchy
- ✅ Task 143: Unified Diagnostic System
- ✅ Task 144: Display Consolidation — Diagnostic Rendering Redesign
- ✅ Task 145 + 146: Mermaid Workflow Visualization
- ✅ Task 147: Validator Produces Diagnostics Natively
- ✅ Task 148: Template Error UX Consolidation
- ✅ Task 149: Fix Non-Interactive Output Routing + Output Pipeline Consolidation
- ✅ Task 150: Wire WorkflowValidator into Save Path
- ✅ Task 151: CLI Surface Restructure
- ✅ Task 77: Pflow Guide — tailored agent instructions
- ✅ Task 153: Reject Undeclared Sub-Workflow Inputs
- ✅ Task 154: Type Vocabulary Coherence
- ✅ Task 156: Add `--dry-run` flag with cache plan and cost/duration estimates
- ✅ Task 157: Fix Dry-Run Batch Sub-Workflow Recursion
- ✅ Task 158: Replace `llm` Library with LiteLLM
- ✅ Task 126: Structured Output for Claude Code Node
- ✅ Task 159: Prompt Caching
- ✅ Task 160: Cache Analysis Architectural Refactor
- ✅ Task 161: Safer Cache Defaults
- ✅ Task 162: Loop Config — Condition-Terminated Iteration
- ✅ Task 163: Agentic Coding Workflow Harness example
- ✅ Task 165: Shrink Trace Interning
- ✅ Task 166: Declarative Stateful Loop Primitive
- ✅ Task 155: Workflow Graph Model for Multi-Renderer Support
- ✅ Task 168: Workflow Visualization Web UI
- ✅ Task 133: Trace/Cache Storage Architecture
- ✅ Task 169: Agent↔Browser Interaction Channel
- ✅ Task 172: Streamable trace
- ✅ Task 173: Live execution overlay
- ✅ Task 175: Run workflows from the UI
- ✅ Task 125: Human-in-the-Loop Approval Gates
- ✅ Task 164: Resume Workflow From a Failed Node
- ✅ Task 174: Agent Voice Narration — "Point & Say"

### Planned Features (in order of priority)

**Next?** (in build order)
- Task 171: Durable Resume Tokens & Non-TTY Gates
- Task 176: Web-UI Approval Bridge

**v0.14.0**
- Task 142: Explore Function-Based Code Node Syntax
- Task 46: Workflow Export to Zero-Dependency Code
- Task 94: Display Available LLM Models
- Task 99: Expose pflow Tools to Claude Code Node
- Task 111: Batch Limit for Iteration
- Task 118: Code and Shell Linting
- Task 121: Workflow Testability

**v0.15.0 - Performance:**

- Task 78: Save User Request History
- Task 88: MCPMark Benchmarking

**v1.0.0 - Security & Sandboxing:**
- Task 87: Sandboxed Execution Runtime
- Task 91: Export as MCP Server Packages
- Task 97: OAuth for Remote MCP Servers
- Task 109: Sandbox Bypass Controls

**v1.1.0 - MCP Ecosystem:**
- Task 65: MCP Gateway Integration
- Task 81: Find/Install Remote MCP Servers
- Task 86: MCP Server Discovery Automation
- Task 123: OAuth Authentication for MCP HTTP Servers
- Task 152: MCP Server Cli surface Parity

**Refactors:**
- Task 117: Subcommand JSON Error Output
- Task 120: Strict Input Type Validation
- Task 170: One Template Language

**Later:**
- Task 124: Code Node Dependency Management
- Task 45: Evaluate n8n integration
- Task 62: Route stdin to Workflow Inputs
- Task 64: MCP Orchestration (long-running servers)
- Task 74: Knowledge base system
- Task 79: Tool definitions as JSON
- Task 90: Workflows as Remote HTTP MCP Servers
- Task 98: First-Class IR Execution
- Task 100: Reduce/Fold for Batch
- Task 101: Shell Node File Input
- Task 110: PIPESTATUS Pipeline Detection
- Task 112: Pre-execution Type Validation
- Task 113: TypeScript Code Node
- Task 114: Lightweight Custom Nodes
- Task 116: Windows Compatibility
- Task 167: LSP Support for `.pflow.md`

> **Task commands:**
> ```bash
> ./scripts/tasks              # View summary and roadmap
> ./scripts/tasks 104          # View specific task (or multiple: 104 103 110)
> ./scripts/tasks --search X   # Find tasks
> ```
>
> **Task files:** `.taskmaster/tasks/task_N/`

> We have NO USERS yet — no *external* compatibility to preserve, so refactor formats and APIs is cheap. But the system's own behavior and its test suite are the contract: don't break existing functionality or rewrite tests without carefully considering the implications.

## User Decisions and Recommendations

You own recommendations and low-stakes, reversible calls; the user owns the decisions that are genuinely impactful and hard to reverse. The steps below are how to tell the two apart.

**When you encounter a decision point:**

1. **Explain why a decision is needed.** What's the context? What's at stake?
2. **Present at least 2 options with tradeoffs.** For each: what's good, what's bad, how reversible?
3. **Make a clear recommendation.** State which option you'd suggest and why.
4. **Gauge importance (1-5).** For low-stakes (1-2) where you're confident, proceed. For anything higher, STOP and wait for the user's decision.

If anything is unclear or ambiguous in the documentation, the user makes the call.

**Escalate when:**
- Architectural decisions affect multiple components
- Trade-offs have no clear winner after analysis
- Current approach contradicts established patterns
- Integration would break existing functionality

### Implementation Guidelines

Write modern, typed, safe Python — full type hints (no leaked `Any`, explicit `Optional[T]`), lowercase builtins, f-strings, comprehensions, simple control flow (no needless nesting), no mutable default args, `subprocess` over `os.system`, no shadowing builtins; suppress lints sparingly and always with a code (`# type: ignore[...]`, `# noqa: CODE`). mypy + ruff enforce these; they're named here to prime, not to teach (see *Why this matters* below).

Why this matters: These guidelines aren't about passing linters—they're about you filtering your training data (as an LLM). By specifying "modern Python patterns," you naturally select from well-maintained, professional codebases rather than the vast sea of outdated tutorials and quick fixes. This selection bias toward quality code automatically prevents security issues, maintenance problems, and outdated practices.

*You should actively and proactively think about selecting from the RIGHT part of your training distribution. The code and architectural patterns you know in your gut are a good fit for this project.*

#### Code Quality

The codebase has been through a sustained consolidation pass — diagnostics, output routing, execution core, exception hierarchy, and validation were each folded behind a smaller interface.  Hold that bar: new code *folds complexity away* rather than adding layers.

- Write code optimized for change: small focused functions with single responsibilities, clear names that explain intent not implementation, and comprehensive tests that document expected behavior
- Structure code as isolated, testable components that can be understood and changed independently — the only meaningful measure of code quality is how safely and easily it can be modified
- Prefer boring and obvious: write code a tired developer can understand at 3am.

**Reason about structure in this vocabulary — and apply it when writing code, not just when refactoring:**
- **Deep modules over shallow** — maximize behavior behind a *small interface* (leverage); if a module's interface is nearly as complex as its implementation, it's shallow — fold it away. (A deep module can still be small functions inside.)
- **Place seams deliberately** — a seam is where behavior can change without editing in place; add one only where something actually varies (*one adapter = hypothetical seam, two = real*).
- **Locality** — make change, bugs, and tests concentrate in one place, not spread across callers.
- **The interface is the test surface** — test through the interface, not past it.
- **Deletion test** — before keeping an abstraction, ask: would deleting it *concentrate* complexity (keep it) or just *move* it (drop it)?

**More architecture is not more depth** — depth comes from *consolidating* behavior behind a smaller interface, not from adding layers or seams; the simplest structure that yields real depth wins.

Full definitions and rejected framings: `.claude/skills/improve-codebase-architecture/LANGUAGE.md` (canonical). Project domain nouns: `context/CONTEXT.md`.

*Mirror the top 10% of well-written CLI tools and small libraries, not enterprise frameworks.*

### Project-specific Memories

- **NEVER** `git add`, `git commit` or `git push` code unless explicitly instructed by the user
- Show expected output BEFORE implementing — easy to understand without implementation details

## Running pflow

```bash
# Run a workflow file
uv run pflow workflow.pflow.md

# Traces saved to ~/.pflow/debug/workflow-trace-<hash>-[name-]YYYYMMDD-HHMMSS.json
uv run pflow my-workflow

# Full agent usage context (only read if needed)
uv run pflow guide
```
