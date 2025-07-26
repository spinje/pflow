# PocketFlow Documentation

This file (`pocketflow/docs/CLAUDE.md`) is a summary of the documentation in the `pocketflow/docs/` folder.

## Overview
PocketFlow is a 100-line Python framework for building LLM applications. The framework is the foundation for the pflow CLI tool being developed but has internal documentation as outlined in this file.


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

### Advanced Full-Repository Examples
These are complete applications that demonstrate sophisticated PocketFlow patterns. These examples are included as git submodules in the repository:

> **Note**: These examples are git submodules. To access them locally, clone with `git clone --recursive` or run `git submodule init && git submodule update` after cloning.

35. **`PocketFlow-Tutorial-Website-Chatbot`**: "Set & Forget" website chatbot with live learning
    - *When to examine*: Building autonomous customer support systems
    - *Patterns*: Agent + RAG + Map-Reduce + Workflow
36. **`PocketFlow-Tutorial-Danganronpa-Simulator`**: Multi-agent social deduction game
    - *When to examine*: Complex game mechanics with AI agents
    - *Patterns*: Async + Agent + State Machine
37. **`Tutorial-Codebase-Knowledge`**: GitHub repo analyzer and tutorial generator
    - *When to examine*: Documentation generation from code
    - *Patterns*: Workflow + BatchNode + Map-Reduce
38. **`Tutorial-Cursor`**: AI coding agent with file operations
    - *When to examine*: Building code editing assistants
    - *Patterns*: Agent + Nested Flows + Tool Integration
39. **`Tutorial-AI-Paul-Graham`**: RAG system with personality mimicry
    - *When to examine*: Building domain-specific Q&A systems
    - *Patterns*: RAG + Map-Reduce + TTS
40. **`Tutorial-Youtube-Made-Simple`**: YouTube video ELI5 summarizer
    - *When to examine*: Video content processing and summarization
    - *Patterns*: Map-Reduce + Batch Processing
41. **`Tutorial-Cold-Email-Personalization`**: Personalized cold email generator
    - *When to examine*: Web research and content personalization
    - *Patterns*: Map-Reduce + Web Search + Batch Processing

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

## Documentation Details

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
