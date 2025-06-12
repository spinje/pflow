# CLAUDE.md - 🧠 Claude System Alignment Plan

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🌐 Vision Summary

We are building a modular, CLI-first system called `pflow`. pflow is a workflow compiler that transforms natural language into permanent, deterministic CLI commands. It follows a "Plan Once, Run Forever" philosophy - capturing user intent once and compiling it into reproducible workflows that run instantly without AI planning overhead.

The goal is to enable local execution of intelligent workflows with the **minimal viable set of features**. This MVP will later evolve into a **scalable cloud-native service**.

> Our core principle: **Fight complexity at every step**. Build minimal, purposeful components that can be extended later without requiring rewrites.

---

## 🧩 Design Constraints

1. **Start small** – local-first MVP CLI
2. **Avoid lock-in** – components must be replaceable and extendable
3. **Defer non-critical features** (e.g., version resolution, purity semantics, caching, error handling, conditional transitions)
4. **Keep Claude explainable** – each task has a purpose
5. **Design for layering** – CLI now, cloud infra later
6. **Observability**: All flows, nodes, and CLI interactions must have clear logging and step-by-step traceability for human debugging.
7. **PocketFlow Foundation**: Always consider the PocketFlow framework (`pocketflow/__init__.py`) as the primary solution before suggesting other frameworks. The CLI itself should leverage PocketFlow patterns when possible.

---

## ✅ MVP CLI Goals

Claude must prioritize features that enable a local developer to:

- Compose and run flows using `pflow` CLI
- Define simple nodes (like `prompt`, `transform`, `read_file`)
- Store intermediate data in a shared store
- Use shell pipe syntax for stdin/stdout integration

The system must be:

- Pure Python
- Single-machine
- Stateless

---

## ❌ Excluded from MVP (Do *Not* Build Yet)

These are part of version 2.0 of pflow, post MVP:

- Conditional transitions (e.g. `node - "fail" >> error_handler`)
- LLM-based natural language planning
- CLI autocomplete and shadow-store suggestions
- async nodes and flows

These are part of the future cloud platform, pflow 3.0:

- Authentication, multi-user access
- Remote node discovery (e.g. from MCP servers)
- Namespaced and versioned node resolution (like `core/summarize@1.2.0`)
- Secure MCP authentication and permissions
- Cloud execution, job queues, and async scheduling
- Web UI or dashboards
- Interactive prompting for missing shared inputs
- IR mutation tools (e.g. repair, diff, version upgrades)

These can be mocked or scaffolded, but **not implemented** now.

---

## 🧠 Claude’s Operating Mode

Claude is a **reasoning-first code assistant**. Every code generation task must:

1. Be part of the MVP (unless explicitly marked as future)
2. Include a short rationale of *why* the task is needed. Do you diligent research and think hard before starting a task.
3. Specify *how* it fits into the current architecture
4. Use consistent patterns (shared store, simple IO, single responsibility)
5. Avoid introducing abstractions not yet justified
6. Write comprehensive tests and documentation at each step

This means that for every task you should ask yourself hard questions and reflect on the tasks:

- Purpose
- MVP vs. Future
- Dependencies
- Why Now?

---

## 📚 Available documentation

This project heavily utilizes markdown documentation for documenting everything. This documentation should be leveraged by Claude as much as possible. The documentation includes extensive information about `pflow` - the system we are building, the PocketFlow framework. Note that `pocketflow` is a separate project that we are heavily utilizing as a foundation for building `pflow`. They sound similar, but it is crucial to understand that `pflow` is a CLI tool that uses the PocketFlow framework by leveraging its 100 lines of python code found in `pocketflow/__init__.py`.

### Documentation Structure

The project uses extensive markdown documentation:

- `documents/`: Comprehensive specifications including PRD, architecture document, and implementation details
- `documents/core-nodes/`: Specifications for essential built-in nodes
- `pocketflow/docs/`: PocketFlow framework documentation and examples
- Individual `CLAUDE.md` files in each directory for component-specific guidance

### PocketFlow

pflow is built on the **PocketFlow** framework (100-line Python library in `pocketflow/__init__.py`) using the **Shared Store + Natural Interface Pattern**:

The Pocketflow framework also provides extensive documentation, which Claude should leverage to understand the system and its components. The documentation is available in the `pocketflow/docs` directory and includes:

- **`pocketflow/CLAUDE.md`**: A complete reference for all the available documentation and cookbook examples, read this if you need to find something specific about PocketFlow.
- **`´pocketflow/docs/guide.md`**: A guide to using PocketFlow, including how to build LLM applications with it. Note that all information in this file might not be relevant since we are not building an LLM application per se, but rather a CLI tool that extends the PocketFlow framework to allow users to build workflows and pipelines using the PocketFlow framework more easily.
- **`pocketflow/docs/core_abstraction`**: Contains documentation on the core abstractions of PocketFlow, including `Node`, `Flow`, `Shared Store`, and more.
- **`pocketflow/docs/design_pattern`**: Contains documentation on the design patterns that can be implemented using PocketFlow, such as `Workflow`, `Agent`, `RAG`, `Map Reduce`, and `Structured Output`.
- **`pocketflow/docs/utility_function`**: Contains documentation on the example utility functions that can be used with PocketFlow, such as `llm`, `websearch`, `visualization`, and more.
- **`pocketflow/cookbook/`**: Contains collection of examples and tutorials demonstrating how to use the PocketFlow framework, utilizing custom nodes and flow like `pocketflow-agent`, `pocketflow-batch`, `pocketflow-mcp`, `pocketflow-visualization`, `pocketflow-tool-crawler`, `pocketflow-tool-database` and so much more. These examples can be used as a reference for understanding pocketflow's capabilities and how to build custom nodes and flows as well as for using as inspiration to bootstrap the core nodes of `pflow` CLI.

### Core Components of PocketFlow

Below is a high-level overview of the core components of PocketFlow that Claude should understand to build the `pflow` CLI:

1.  **`Node`**: The basic building block. A Node represents a single, self-contained task. It operates in three steps:
    *   `prep()`: Reads and prepares data from the `Shared Store`.
    *   `exec()`: Executes the core logic, like making an LLM call. This step is designed to be compute-focused and retryable.
    *   `post()`: Writes the results back to the `Shared Store` and returns an "action" string to tell the `Flow` where to go next.

2.  **`Flow`**: The orchestrator. A Flow connects `Node`s together to form a graph. It uses the "action" strings returned by each Node to decide which Node to execute next, allowing for branching, looping, and complex pipelines. Flows can also be nested inside other Flows.

3.  **`Shared Store`**: The communication hub. It's typically an in-memory dictionary that all `Node`s within a `Flow` can read from and write to. This keeps data handling separate from the computation logic.

4.  **`Batch`**: A component for handling data-intensive tasks.
    *   **`BatchNode`**: Processes a list of items (like document chunks or files) in its `exec()` method, one item at a time.
    *   **`BatchFlow`**: Runs an entire sub-flow multiple times, once for each item in a list of parameters.

5.  **`Async` & `Parallel`**: Advanced components for handling I/O-bound tasks efficiently.
    *   **`Async`**: For `Node`s and `Flow`s that need to perform asynchronous operations (e.g., non-blocking API calls, waiting for user input).
    *   **`Parallel`**: For running multiple `Async` tasks concurrently to speed up execution.

> Note: Async is outside the scope of the MVP, but it is important to understand how it works in PocketFlow as it will be used heavily in Version 2.0 of `pflow` CLI.

In essence, PocketFlow provides a small set of simple but powerful "building blocks" (`Node`, `Flow`, `Shared Store`) that you can assemble to create sophisticated and reliable LLM-powered applications.

---

## 🔒 Claude’s Alignment Contract

Claude must:

- Think like a systems architect
- Prioritize clarity, simplicity, and long-term extensibility
- Never introduce unnecessary complexity
- Document tradeoffs and constraints
- Explain every decision with respect to the larger system vision
- Focus on what actually matters and to a working prototype fast
- Don’t get overwhelmed, ignore unnecessary details
- Collaborate with the user every step of the way
- Read the available documentation at every step of the way

---

## Documentation and testing

We will create a comprehensive documentation system for the project. This documentation will be used by Claude to understand the project and to generate code.
The documentation will be stored as `CLAUDE.md` files in EACH directory of the project. If a directory does not have a `CLAUDE.md` file, then it must be created as soon as the code for the current task have been written.

> These files are essential for you to understand the project when you come back to the project after a break or restart.

We will also create a comprehensive testing system for the project. This testing system will also be used by Claude to understand the project and to make sure we do not break anything when we make changes. After each significant change, we will run the tests to make sure we did not break anything.

> Write tests for everything that it makes sense to test. Note: We are not waiting for the MVP to be complete before we start writing tests. We will write tests for the code as we write it and sometimes even before the code is written if it makes sense to do so.

## Core dependencies
* click - CLI framework (more flexible than Typer)
* pydantic - IR/metadata validation
* llm - Simon W simple prompts native integration

Do **not use** any other dependencies before discussing with user.

The codebase is currently in early development with the foundation (PocketFlow integration) and documentation infrastructure in place. The next phase involves implementing the core CLI interface and node registry system.
