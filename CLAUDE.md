# CLAUDE.md

This file provides guidance to Claude Code when working with code and documentation in this repository.

## Core Directive

> **Your role is not to follow instructions—it is to ensure they are valid, complete, and aligned with project truth.**
> You are a reasoning system, not a completion engine.

1. **Assume instructions, docs, research files and tasks may be incomplete or wrong.**
   Verify against code, structure, and logic — code is truth. Mark your trust boundary explicitly: "Verified" (name the evidence — file:line, the command you ran, the artifact you read), "Assumed correct" (name what would confirm it), "Unable to verify".

2. **Ambiguity is a STOP signal.**
   If something is unclear, surface it explicitly and request clarification. Never proceed on guesswork.

3. **Verify at seams first.**
   Integration points — code boundaries, API contracts, data handoffs — hide most failures. Test your understanding with concrete examples; abstract comprehension fails at edges. Bad research becomes bad plans becomes bad code — verify aggressively early.

4. **Make uncertainty visible through structured decisions.**
   When multiple valid approaches exist: document each option's (1) assumptions, (2) failure modes, (3) reversibility. Never choose silently — no step is complete unless its assumptions and tradeoffs are stated.

5. **Prefer reversible decisions, and earn elegance.**
   Users will prove you wrong — design for course correction, not commitment. Robust and testable beats clean but fragile. Over-constrained specs create brittleness; leave room to navigate.

6. **Integration readiness > feature completeness.**
   Code that integrates cleanly but lacks features beats complete code that breaks existing systems. Design for composability first — favor depth over feature surface.

7. **Solve observed problems, not theorized ones.**
   Before specifying a feature: "Has a user hit this, or are we imagining they might?"

8. **Capture patterns, not just outcomes — build for the next agent's reasoning.**
   Record what worked, why, and what was rejected. Code, tasks, and docs should stay re-reasonable and modifiable by whoever inherits them, not just support the current run.

When in doubt, ask: *"What would have to be true for this to work reliably under change?"*

## Project Overview

**pflow** is a CLI-first workflow execution system. AI agents create markdown workflow files (`.pflow.md`), iterate on them via CLI, then save them for reuse. Workflows chain nodes (`shell`, `http`, `llm`, `file`, `mcp`, `code`, `agent`) that communicate through a shared store.

> **For conceptual understanding** (why pflow exists, core bets, design decisions): See `architecture/overview.md`
> **For technical architecture** (execution pipeline, abstractions, components): See `architecture/architecture.md`

**Core Principle**: Fight complexity at every step. Build minimal, purposeful components that extend without rewrites.

### Core Value

An agent describes a job once as a `.pflow.md` file, runs it with one command, reads a trace that says exactly what happened, and saves it so the next agent runs the same job without re-deriving it. Everything user-facing — errors, results, traces — exists to make that loop tight for an AI agent.

### Node Lifecycle Primitives

pflow's node system is built on `BaseNode` and `Node` (in `src/pflow/core/node.py`). These provide the lifecycle (prep/exec/post), retry logic, and graph wiring operators (`>>`, `-`). The `WorkflowEngine` (in `src/pflow/runtime/engine/`) handles graph traversal and all runtime concerns.

> When implementing features that use nodes, start by reading `src/pflow/core/node.py`, then `src/pflow/nodes/CLAUDE.md` for node implementation patterns.

### Key Principles

- **Shared Store Pattern**: All node communication through shared store
- **Atomic Nodes**: Isolated, focused on business logic only
- **Agent-Friendly CLI**: Primary interface for AI agents
- **Structured Errors**: Raise `PflowError` subclasses from `src/pflow/core/exceptions.py`, never vanilla `ValueError`/`Exception`. For node retry and error-routing contracts, see `src/pflow/nodes/CLAUDE.md`. See `src/pflow/core/exceptions.py` for the hierarchy; `src/pflow/core/CLAUDE.md` → `exceptions.py` section for diagnostic guidance.

### Tech Stack

- **Core:** Python 3.10+, click, pydantic, LiteLLM via pflow's `llm_client` adapter
- **Web UI:** `web/` (frontend source) served by `src/pflow/ui/`
- **Dev tooling:** `uv` (ALWAYS, never `pip`), pytest, mypy, ruff, pre-commit, Makefile

### Project Structure

> Read the relevant directory's CLAUDE.md for local navigation and gotchas.

```
pflow/
├── README.md                # Project overview and user guide
├── Makefile                 # Development automation
├── pyproject.toml, uv.lock  # Project configuration, dependencies, lockfile
├── docs/                    # User-facing documentation (mintlify)
├── architecture/            # Architecture and design specs (index: architecture/CLAUDE.md)
├── examples/                # Example workflows and usage patterns
├── workflows/               # pflow workflows the process itself runs (review fan-out, searcher offload)
├── scripts/                 # tasks board, worktree tooling, Claude→Codex asset sync
├── web/                     # Web UI frontend source and build configuration
├── context/
│   ├── CONTEXT.md, CONTEXT-FORMAT.md   # Canonical domain language and editing format
│   └── adr/                            # Architecture decision records + ADR-FORMAT.md
├── src/pflow/
│   ├── cli/                 # CLI entrypoints and subcommands
│   ├── core/                # Schemas, settings, validation, utilities, LLM/prompt utils
│   │   ├── workflow/        # Workflow lifecycle (manager, validator, save, skills, discovery)
│   │   └── prompt_cache_analysis/  # Prompt-cache cost & discrepancy analysis
│   ├── execution/           # Execution UX, formatters
│   ├── runtime/             # Compilation, engine, tracing
│   ├── nodes/               # Platform node implementations
│   │   └── (shell, http, llm, file, mcp, python, agent)
│   ├── mcp/                 # MCP client integration (for MCP nodes in workflows)
│   ├── mcp_server/          # pflow-as-MCP-server for AI agents
│   ├── registry/            # Node registry, scanning, context building, discovery
│   ├── ui/                  # Python web UI server and trace streaming
│   └── guide/               # `pflow guide` content — agent instructions (core/nodes/features)
├── tests/                   # Test suite (mirrors src/: test_cli, test_core, test_runtime, test_nodes, …)
│   ├── fixtures/            # Shared test fixtures (e.g. cache_analysis workflows)
│   ├── shared/              # Shared utilities (llm_mock, markdown_utils, registry_utils)
│   ├── test_docs/           # Docs/link validation + agent-file reference checks
│   ├── test_integration/    # End-to-end workflow tests
│   └── test_scripts/        # scripts/ behaviour (asset sync, worktree)
└── .taskmaster/
    ├── orchestration/       # Programme state, decisions, standing knowledge, recurrence, session logs + index
    └── tasks/task_{N}/      # One directory per task; see "Task artifacts" below
        ├── task-{N}.md              # Spec: current what + why, edited in place (Status, Priority, Roadmap)
        ├── task-review.md           # Post-implementation durable forward-reference
        ├── starting-context/        # briefs/braindumps, newest last (tacit layer; the spec is the truth)
        └── implementation/
            ├── implementation-plan.md   # Phases, decisions, tests — written by the task planner
            └── progress-log.md          # Dated decisions/discoveries/deviations (append-only)
```

**Task artifacts — one job each (labelled in the tree above); never repeat a fact across them.** A fact lives in **one** artifact (the others link). The **spec states current truth → edit in place**; the **logs append history → dated** (like code vs. git history). Smell test: "verified 2026-06-30 / delta #N / the searcher found…" is a *log* entry, not spec — the spec reads as if written by someone who already knew the answer. *Critical considerations* stay in the spec, but state the durable **constraint** ("this touches the trace format"), not the **discovery** ("found via a searcher 2026-06-30").

### Dev Environment

All commands run from the repo root. This project uses `uv`, not bare `python`/`pip`.

```bash
make install                    # Install dependencies (and pre-commit hooks in the main checkout)
make test                       # Run non-e2e tests, excluding paid LLM tests
make test-e2e                   # Run e2e tests, excluding paid LLM tests
make test-all-local             # Run the full non-paid suite, including e2e
make check                      # Run all quality checks (lock, asset sync, lint, pre-commit, mypy, deptry)
make sync-claude-assets         # Regenerate .agents/ and .codex/ after any canonical .claude/ change
./scripts/tasks [N | --search X | --check | --boot]   # Task board, one task, search, validation, boot-set size
./scripts/worktree new|rm|list  # Parallel worktrees for task/issue lanes
```

**Ad-hoc commands:**
- `uv run pflow workflow.pflow.md` — run a workflow file (traces land under `~/.pflow/debug/`)
- `uv run pflow my-workflow` — run a saved workflow
- `uv run pytest tests/test_core/test_x.py::test_y` — a single test
- `uv run pflow guide` — full agent usage context (only read if needed)

### Codebase Search Agents

- Use `pflow-codebase-searcher` for gathering information, research, and verifying assumptions (avoids exhausting the context window). **Never use the `Explore` or general-purpose agents.**
- Subagents gather and cite; **you** own the conclusions. `pflow-codebase-searcher` is same-model and file-grounded — trust its citations, but check its conclusions follow from them, and confirm directly before anything irreversible or outward-facing.
- Read files directly with the `Read` tool when the path is known or when the user explicitly asks you to read something.
- Deploy subagents in **parallel** (one function call block), never sequentially.
- Deploy the review battery via the `/deep-review` skill (more than one lens), or launch one `review-*` agent directly when you suspect a specific issue class.
- Use `code-implementer` for small, isolated features/fixes — or test-only briefs — that need no deep codebase knowledge; it is a leaf, never a judgment seat.

### Claude's Operating Guidelines

**Show Before You Code**: For any task that changes user-visible output, show concrete before/after examples and ask for confirmation before implementing. This takes 30 seconds but saves hours of rework.

**Reasoning-First Approach**: Every code generation task must:
1. Include rationale of *why* the task is needed and *how* it fits current architecture
2. Read the relevant docs and existing code first — check how a neighbouring node/module implements the same concern before building new
3. Use consistent patterns (shared store, simple IO, single responsibility)
4. Avoid abstractions that don't pass the **deletion test** (see Code Quality)
5. Write tests AS YOU CODE (test-as-you-go):
   - Every new function/component needs test cases (quality over quantity)
   - Test public APIs, critical paths, error handling, and integration points
   - A task without tests is an INCOMPLETE task
   - NEVER mock what you can test directly
6. Run `make check` (and `make test`) when finalizing a task or a task phase — every lint, type and test error is resolved before the work counts as done

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
- Keep `CLAUDE.md` files focused on code navigation, verified gotchas, and durable rationale; avoid duplicating implementation details
- Create scratch pads in `scratchpads/<conversation-subject>/` for deep thinking
- **NEVER** `git add`, `git commit` or `git push` unless explicitly instructed by the user
- Show expected output BEFORE implementing — easy to understand without implementation details

**Domain language & decisions**:
- Use the canonical terms from `context/CONTEXT.md` in code, CLI output, and docs; don't mint a second name for an existing noun.
- When a decision is hard to reverse, surprising without context, and the result of a real trade-off, offer to record an ADR (`context/adr/ADR-FORMAT.md`). When new domain terms crystallize, add them to `context/CONTEXT.md`.
- When a task adds a node/command/surface or changes a documented pattern, update the affected CLAUDE.md files, `pflow guide` content, and `.claude/agents/pflow-codebase-searcher.md` as part of the task — stale instruction files have caused real errors.

### Documentation

> Always read relevant docs before coding!

- **Architecture & navigation**: `architecture/CLAUDE.md` — documentation index, reading paths, implementation CLAUDE.md table
- **Node lifecycle primitives**: `src/pflow/core/node.py` — BaseNode, Node, wiring operators
- **Agent usage guide**: Run `pflow guide`

Proactively use `pflow-codebase-searcher` subagents in PARALLEL when reading documentation and searching for code.

### Project Status

MVP feature-complete. Published to PyPI (initial release v0.8.0; current version per `pyproject.toml`). Shipped: shell/http/llm/mcp/`code`/`agent` nodes plus five file-op nodes, the `.pflow.md` format, templates, batch, loops, nested and conditional workflows, MCP client + server, tracing/metrics, resume and approval gates, the web UI, and skills publishing.

To view the roadmap, run `./scripts/tasks` — pending tasks are grouped by the `## Roadmap` slot in their specs (next / then / later); `./scripts/tasks --check` enforces it.

> We have NO USERS yet — no *external* compatibility to preserve, so refactoring formats and APIs is cheap. But the system's own behavior and its test suite are the contract: don't break existing functionality or rewrite tests without carefully considering the implications.

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

The codebase has been through a sustained consolidation pass — diagnostics, output routing, execution core, exception hierarchy, and validation were each folded behind a smaller interface. Hold that bar: new code *folds complexity away* rather than adding layers.

**The governing lens — the user's words, applied to every design, fix, plan, review disposition, and process choice:**

> *"We should prioritize simplicity of the FINAL code, not how easy it is to get there. When in doubt we should ask ourselves whats the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet? What this doesnt mean is overfitting to "top 10% of codebases" and overengineering, this is about more simple code that is optimized for AI agents to understand and add features to."*

- Write code optimized for change: small focused functions with single responsibilities, clear names that explain intent not implementation, and comprehensive tests that document expected behavior
- Structure code as isolated, testable components that can be understood and changed independently — the only meaningful measure of code quality is how safely and easily it can be modified
- Prefer boring and obvious: write code a tired developer can understand at 3am.
- **Before you commit a substantive comment or docstring, grep its distinctive phrase across `src/pflow/` and the CLAUDE.md files.** A hit usually means the invariant already has a home — and a restatement is not maintained: when the invariant changes only one copy gets edited, so the rest become confidently wrong. Decide which site is authoritative (the code the constraint binds, or the CLAUDE.md that owns the rule), leave the statement there, and reference it or write nothing. Only state constraints the code cannot show.

**Reason about structure in this vocabulary — and apply it when writing code, not just when refactoring:**
- **Deep modules over shallow** — maximize behavior behind a *small interface* (leverage); if a module's interface is nearly as complex as its implementation, it's shallow — fold it away. (A deep module can still be small functions inside.)
- **Place seams deliberately** — a seam is where behavior can change without editing in place; add one only where something actually varies (*one adapter = hypothetical seam, two = real*).
- **Locality** — make change, bugs, and tests concentrate in one place, not spread across callers.
- **The interface is the test surface** — test through the interface, not past it.
- **Deletion test** — before keeping an abstraction, ask: would deleting it *concentrate* complexity (keep it) or just *move* it (drop it)?
- **Category names make claims** — a name that groups (`…metadata`, `…utils`) asserts its members behave alike; enumerate them and check. False for one member means the *abstraction* is wrong, not the name.

**More architecture is not more depth** — depth comes from *consolidating* behavior behind a smaller interface, not from adding layers or seams; the simplest structure that yields real depth wins.

Full definitions and rejected framings: `.claude/skills/improve-codebase-architecture/LANGUAGE.md` (canonical). Project domain nouns: `context/CONTEXT.md`; recorded decisions: `context/adr/`.

*Mirror the top 10% of well-written CLI tools and small libraries, not enterprise frameworks.*
