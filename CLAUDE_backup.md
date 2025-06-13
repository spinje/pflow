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
