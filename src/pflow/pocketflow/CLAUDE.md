# PocketFlow Repository Map & Inventory

pflow is built on the **PocketFlow** framework (~200-line Python library in `src/pflow/pocketflow/__init__.py`).

> Important to note: `pflow` is a CLI tool that extends the PocketFlow framework to allow users to build workflows and pipelines using the PocketFlow framework more easily.

The Pocketflow framework also provides extensive documentation, which Claude should leverage to understand the system and its components.

## Overview

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

In essence, PocketFlow provides a small set of simple but powerful "building blocks" (`Node`, `Flow`, `Shared Store`) that you can assemble to create sophisticated and reliable LLM-powered applications or workflows.

## Repository Structure
```
src/pflow/pocketflow/
├── __init__.py           # Core 100-line framework: **The most important file in the repository**
├── CLAUDE.md            # Guidance for Claude on using PocketFlow <-- This file
├── LICENSE              # MIT License
├── PFLOW_MODIFICATIONS.md
└── docs/                # Comprehensive documentation

tests/pocketflow/         # PocketFlow test suite
```
