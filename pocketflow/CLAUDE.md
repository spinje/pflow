# PocketFlow Repository Map & Inventory

pflow is built on the **PocketFlow** framework (100-line Python library in `pocketflow/__init__.py`).

> Important to note: `pflow` is a CLI tool that extends the PocketFlow framework to allow users to build workflows and pipelines using the PocketFlow framework more easily. It is not an LLM application, but rather a CLI tool that extends the PocketFlow framework to allow users to build workflows and pipelines using the PocketFlow framework more easily.

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
pocketflow/
├── __init__.py           # Core 100-line framework: **The most important file in the repository**
├── CLAUDE.md            # Guidance for Claude on using PocketFlow <-- This file
├── docs/                # Comprehensive documentation
├── cookbook/            # 30+ example implementations
└── tests/              # Test suite
```

## Documentation Inventory

### Core Documentation Files

#### 1. Framework Overview
- **`CLAUDE.md`**: **This file**: Entry point explaining PocketFlow components and documentation structure
- **`docs/guide.md`**: "Agentic Coding" methodology for human-AI collaboration with a focus on teaching AI coding assistants and agents to use pocketflow.

#### 2. Core Abstractions (`docs/core_abstraction/`)
- **`node.md`**: Node abstraction with prep→exec→post lifecycle
  - *Key for pflow*: Foundation for all pflow nodes
- **`flow.md`**: Flow orchestration with action-based transitions
  - *Key for pflow*: How to chain nodes with `>>` operator
- **`communication.md`**: Shared Store (primary) and Params patterns
  - *Key for pflow*: Critical for understanding data flow between nodes
- **`batch.md`**: BatchNode and BatchFlow for large-scale processing
  - *Key for pflow*: Handling multiple inputs efficiently
- **`async.md`**: Async capabilities (excluded from MVP)
- **`parallel.md`**: Parallel execution (excluded from MVP)

#### 3. Design Patterns (`docs/design_pattern/`)
- **`workflow.md`**: Task decomposition into sequential nodes
- **`agent.md`**: Dynamic agent with decision-making loops
- **`rag.md`**: Retrieval Augmented Generation implementation
- **`mapreduce.md`**: Processing large inputs/outputs
- **`structure.md`**: Structured output from LLMs
- **`multi_agent.md`**: Multi-agent systems (post-MVP)

#### 4. Utility Functions (`docs/utility_function/`)
- **`llm.md`**: LLM wrapper examples (OpenAI, Claude, etc.)
- **`websearch.md`**: Web search API implementations

## Cookbook Examples Inventory

### Basic Examples (Foundation)
1. **`pocketflow-hello-world`**: Minimal PocketFlow setup
   - *When to examine*: Starting first PocketFlow project
2. **`pocketflow-node`**: Core Node patterns with error handling
   - *When to examine*: Learning Node lifecycle and retry mechanisms
3. **`pocketflow-flow`**: Interactive flow with branching
   - *When to examine*: Implementing menu-driven workflows
4. **`pocketflow-communication`**: Shared Store pattern demonstration
   - *When to examine*: Understanding inter-node communication

### Chat & Conversation Patterns
5. **`pocketflow-chat`**: Simple chat with conversation history
   - *When to examine*: Basic conversational interface
6. **`pocketflow-chat-memory`**: Chat with vector-based memory retrieval
   - *When to examine*: Implementing context-aware conversations
7. **`pocketflow-chat-guardrail`**: Chat with input validation
   - *When to examine*: Adding content moderation/filtering

### Batch Processing Patterns
8. **`pocketflow-batch`**: Parallel document translation
   - *When to examine*: Multi-target processing tasks
9. **`pocketflow-batch-node`**: Chunk-based file processing
   - *When to examine*: Memory-efficient large file handling
10. **`pocketflow-batch-flow`**: Running flows with different parameters
    - *When to examine*: Applying same workflow to multiple inputs
11. **`pocketflow-nested-batch`**: Hierarchical batch processing
    - *When to examine*: Processing nested data structures

### Advanced Processing Patterns
12. **`pocketflow-map-reduce`**: Resume evaluation with aggregation
    - *When to examine*: Document analysis and summarization
13. **`pocketflow-rag`**: Complete RAG with FAISS vector search
    - *When to examine*: Building knowledge-based Q&A systems
14. **`pocketflow-structured-output`**: YAML-based data extraction
    - *When to examine*: Extracting structured data from text

### Agent & Decision-Making Patterns
15. **`pocketflow-agent`**: Research agent with web search
    - *When to examine*: Building autonomous research tools
16. **`pocketflow-supervisor`**: Quality control with retry loops
    - *When to examine*: Ensuring output quality
17. **`pocketflow-thinking`**: Chain-of-Thought reasoning
    - *When to examine*: Complex reasoning tasks
18. **`pocketflow-majority-vote`**: Consensus-based problem solving
    - *When to examine*: Improving reliability of LLM outputs

### Tool Integration Examples
19. **`pocketflow-tool-crawler`**: Web crawling with analysis
    - *When to examine*: Web data extraction
20. **`pocketflow-tool-database`**: SQLite integration
    - *When to examine*: Database operations in workflows
21. **`pocketflow-tool-embeddings`**: OpenAI embeddings API
    - *When to examine*: Semantic similarity tasks
22. **`pocketflow-tool-pdf-vision`**: PDF processing with OCR
    - *When to examine*: Document extraction workflows
23. **`pocketflow-tool-search`**: Web search integration
    - *When to examine*: Information gathering from web
24. **`pocketflow-text2sql`**: Natural language to SQL
    - *When to examine*: Database query interfaces

### Async & Performance Patterns
25. **`pocketflow-async-basic`**: Async operations introduction
    - *When to examine*: Non-blocking I/O operations
26. **`pocketflow-parallel-batch`**: 5x speedup with async
    - *When to examine*: Performance optimization
27. **`pocketflow-parallel-batch-flow`**: 8x speedup for images
    - *When to examine*: Concurrent file processing
28. **`pocketflow-llm-streaming`**: Real-time streaming responses
    - *When to examine*: Interactive LLM interfaces

### Advanced Integration Patterns
29. **`pocketflow-multi-agent`**: Async multi-agent game
    - *When to examine*: Complex agent coordination
30. **`pocketflow-a2a`**: Agent-to-Agent protocol server
    - *When to examine*: Exposing agents as services
31. **`pocketflow-mcp`**: Model Context Protocol integration
    - *When to examine*: MCP server connections
32. **`pocketflow-web-hitl`**: Human-in-the-loop web UI
    - *When to examine*: Interactive web workflows
33. **`pocketflow-visualization`**: D3.js workflow visualization
    - *When to examine*: Debugging complex flows
34. **`pocketflow-workflow`**: Multi-stage content generation
    - *When to examine*: Complex content pipelines

## Key Patterns for pflow MVP

### Essential Patterns to Study
1. **Shared Store Pattern** (`communication.md`, `pocketflow-communication`)
   - Foundation for all node communication in pflow
2. **Node Lifecycle** (`node.md`, `pocketflow-node`)
   - prep→exec→post pattern all pflow nodes must follow
3. **Flow Composition** (`flow.md`, `pocketflow-flow`)
   - How to chain nodes with `>>` operator
4. **Batch Processing** (`batch.md`, various batch examples)
   - Efficient handling of multiple inputs

### Implementation References
1. **For LLM Integration**: See `pocketflow-chat`, `llm.md`
2. **For File Operations**: See `pocketflow-batch-node`
3. **For Error Handling**: See `pocketflow-node`, `pocketflow-supervisor`
4. **For CLI Integration**: See `pocketflow-flow` interactive menu

### Advanced Patterns (Post-MVP)
1. **Async Operations**: `async.md`, async examples
2. **Parallel Processing**: `parallel.md`, parallel batch examples
3. **Agent Patterns**: `agent.md`, `pocketflow-agent`
4. **MCP Integration**: `pocketflow-mcp`

## Usage Recommendations

### For pflow Development
1. **Start with**: `hello-world`, `node`, `communication` examples
2. **Core patterns**: Study shared store, node lifecycle, flow composition
3. **For specific features**:
   - File I/O: `batch-node`, `tool-database`
   - LLM calls: `chat`, `structured-output`
   - Error handling: `supervisor`, `node`
   - CLI interface: `flow`, `web-hitl`

### Documentation Reading Order for `pocketflow/`
1. `__init__.py` - **ALWAYS READ THE SOURCE CODE FIRST**: Since this is just 100 lines of code, this is a super efficient way to understand the core components of PocketFlow.
2. `core_abstraction/node.md` - Foundation
3. `core_abstraction/communication.md` - Data flow
4. `core_abstraction/flow.md` - Orchestration
5. `design_pattern/workflow.md` - Task decomposition
6. Specific patterns as needed

This inventory provides a complete map of PocketFlow's documentation and examples, organized to support efficient learning and implementation of the pflow MVP.
