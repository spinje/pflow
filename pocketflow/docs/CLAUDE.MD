# PocketFlow Documentation

This file (`pocketflow/docs/CLAUDE.md`) is a summary of the documentation in the `pocketflow/docs/` folder.

## Overview
PocketFlow is a 100-line Python framework for building LLM applications. The framework is the foundation for the pflow CLI tool being developed but has internal documentation as outlined in this file.

### 1. `/pocketflow/docs/guide.md`
**Summary**: "Agentic Coding" guide explaining how humans and AI agents should collaborate when building LLM systems. Provides a 7-step framework and example project structure.
**Key Concepts**:
- Human vs AI responsibilities at each development stage
- Project file structure recommendations
- Emphasis on design before implementation
- Example implementations of nodes and flows

## Core Abstraction Documentation

### 2. `/pocketflow/docs/core_abstraction/node.md`
**Summary**: Detailed documentation of the Node abstraction - the smallest building block with prep→exec→post lifecycle.
**Key Concepts**:
- Three-step lifecycle (prep, exec, post)
- Fault tolerance with retries
- Graceful fallback handling
- Separation of data storage from processing

### 4. `/pocketflow/docs/core_abstraction/flow.md`
**Summary**: Documentation of Flow orchestration - how to connect nodes using action-based transitions.
**Key Concepts**:
- Action-based transitions (default and named)
- Flow creation and execution
- Nested flows (flows as nodes)
- Branching and looping patterns

### 5. `/pocketflow/docs/core_abstraction/communication.md`
**Summary**: Explains two communication methods between nodes: Shared Store (primary) and Params (for batch operations).
**Key Concepts**:
- Shared Store as heap-like global storage
- Params as stack-like ephemeral configuration
- Best practice: use Shared Store for almost all cases
- Params mainly for identifiers in batch mode

### 6. `/pocketflow/docs/core_abstraction/batch.md`
**Summary**: Documentation for handling large inputs through BatchNode and BatchFlow.
**Key Concepts**:
- BatchNode: processes iterables item by item
- BatchFlow: runs entire flows multiple times with different params
- Important distinction: BatchFlow returns parameters, not data
- Nested batch support for multi-level processing

### 7. `/pocketflow/docs/core_abstraction/async.md`
**Summary**: Advanced async capabilities for I/O-bound operations (excluded from MVP).
**Key Concepts**:
- AsyncNode with async lifecycle methods
- Useful for file I/O, API calls, user feedback
- Must be wrapped in AsyncFlow
- Can mix async and sync nodes

### 8. `/pocketflow/docs/core_abstraction/parallel.md`
**Summary**: Advanced parallel execution for concurrent async operations (excluded from MVP).
**Key Concepts**:
- AsyncParallelBatchNode and AsyncParallelBatchFlow
- Good for I/O-bound work, not CPU-bound
- Rate limit considerations
- Independence requirement for parallel tasks

## Design Pattern Documentation

### 9. `/pocketflow/docs/design_pattern/workflow.md`
**Summary**: Task decomposition pattern for breaking complex tasks into node chains.
**Key Concepts**:
- Finding the sweet spot between coarse and granular tasks
- Sequential workflow example (article writing)
- When to consider agents for dynamic cases

### 10. `/pocketflow/docs/design_pattern/agent.md`
**Summary**: Dynamic agent pattern with context-aware action selection and branching.
**Key Concepts**:
- Context and action space management
- Graph-based implementation with loops
- Good action design principles
- Search agent example with decision loops

### 11. `/pocketflow/docs/design_pattern/rag.md`
**Summary**: Retrieval Augmented Generation pattern with offline indexing and online querying.
**Key Concepts**:
- Two-stage pipeline (offline/online)
- Chunking, embedding, and vector storage
- Query processing and retrieval
- Complete RAG implementation example

### 12. `/pocketflow/docs/design_pattern/mapreduce.md`
**Summary**: Pattern for processing large inputs or outputs through map and reduce phases.
**Key Concepts**:
- BatchNode for map phase
- Aggregation in reduce phase
- Document summarization example
- Performance tips for parallelization

### 13. `/pocketflow/docs/design_pattern/structure.md`
**Summary**: Techniques for getting structured output from LLMs.
**Key Concepts**:
- Prompting for structure
- YAML preferred over JSON
- Validation strategies
- Example use cases

### 14. `/pocketflow/docs/design_pattern/multi_agent.md`
**Summary**: Advanced pattern for multiple agents working together (not needed for MVP).
**Key Concepts**:
- Message queue communication
- AsyncIO integration
- Interactive examples (Taboo game)
- Warning about complexity

## Utility Function Documentation

### 15. `/pocketflow/docs/utility_function/llm.md`
**Summary**: Example LLM wrapper implementations for various providers.
**Key Concepts**:
- OpenAI, Claude, Google, Azure, Ollama, DeepSeek examples
- Enhancement suggestions (caching, logging, chat history)
- Caching conflict with node retries

### 16. `/pocketflow/docs/utility_function/websearch.md`
**Summary**: Web search API examples and comparisons.
**Key Concepts**:
- API comparison table (pricing, limits)
- Implementation examples for multiple providers
- Google, Bing, DuckDuckGo, Brave, SerpApi

## Key Takeaways for pflow Development

1. **Core Pattern**: The Shared Store pattern is fundamental - nodes communicate primarily through a shared dictionary, not through direct parameter passing.

2. **Node Lifecycle**: All nodes follow prep→exec→post, with exec being retry-able and focused on computation only.

3. **Flow Orchestration**: Flows connect nodes using action strings, enabling branching and looping.

4. **Batch Processing**: Two approaches - BatchNode for processing items, BatchFlow for running flows with different parameters.

5. **Design Patterns**: Multiple established patterns (Agent, RAG, MapReduce, Workflow) that can inform pflow's node design.

6. **MVP Focus**: Async and Parallel features are explicitly excluded from the MVP scope.

7. **Utility Functions**: Examples show how to wrap external services (LLMs, web search) as simple functions nodes can use.

*This file represents an inventory of all available documentation of the pocketflow framework to use as a reference when building the core features of the pflow CLI.*
