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
