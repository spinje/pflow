# PocketFlow Cookbook Examples

This file (`pocketflow/cookbook/CLAUDE.md`) is a summary of the documentation in the `pocketflow/cookbook/` folder.

## Overview
PocketFlow is a 100-line Python framework for building applications represented as workflows. The framework is the foundation for the pflow CLI tool being developed but has internal documentation as outlined in this file.

## Examples available in the `pocketflow/cookbook/` folder

### 1. pocketflow-a2a
**Path**: `pocketflow/cookbook/pocketflow-a2a/`
**Pattern**: Agent-to-Agent Protocol implementation
**Purpose**: Shows how to expose a PocketFlow agent via the Agent-to-Agent (A2A) communication protocol
**When to examine**:
- Building agents that need to communicate with other agents
- Implementing server/client architectures
- Integrating with Google's A2A protocol
- Creating distributed AI systems
**Key features**:
- A2A protocol implementation
- JSON-RPC communication
- ASGI/Uvicorn server setup
- Pydantic models for validation
- Client/server architecture

### 2. pocketflow-agent
**Path**: `pocketflow/cookbook/pocketflow-agent/`
**Pattern**: Autonomous research agent with decision loops
**Purpose**: LLM-powered research agent using decide → search → answer pattern with web search
**When to examine**:
- Building autonomous research tools
- Implementing decision-making loops
- Web search integration with analysis
- Agent architecture patterns
**Key features**:
- Graph-based agent architecture
- Decision-making loops (decide → search → answer)
- Web search integration
- Context management
- Autonomous research capabilities

### 3. pocketflow-async-basic
**Path**: `pocketflow/cookbook/pocketflow-async-basic/`
**Pattern**: Async operations using AsyncNode
**Purpose**: Demonstrates async operations for non-blocking I/O operations
**When to examine**:
- Implementing async workflows with API calls
- LLM interactions without blocking
- User input handling in async contexts
- Non-blocking I/O operations
**Key features**:
- AsyncNode with async lifecycle methods
- Python async/await patterns
- Non-blocking API calls
- Async flow orchestration
- prep_async, exec_async, post_async methods

### 4. pocketflow-batch-flow
**Path**: `pocketflow/cookbook/pocketflow-batch-flow/`
**Pattern**: Running flows with different parameters
**Purpose**: Using BatchFlow to apply same workflow (image filters) to multiple inputs
**When to examine**:
- Applying same workflow to multiple inputs
- Parameter-driven batch processing
- Image processing workflows
- Performance optimization for repeated operations
**Key features**:
- BatchFlow for parameter management
- Image processing with PIL (blur, grayscale, sepia)
- Multiple filter application
- Parameter inheritance
- Output organization

### 5. pocketflow-batch-node
**Path**: `pocketflow/cookbook/pocketflow-batch-node/`
**Pattern**: Chunk-based processing for large inputs
**Purpose**: Using BatchNode to process large files in manageable chunks for memory efficiency
**When to examine**:
- Handling large files or datasets
- Memory-efficient processing patterns
- Chunk-based data processing
- Aggregation of batch results
**Key features**:
- BatchNode with prep/exec/post lifecycle
- Chunking strategy for large inputs
- Processing in manageable pieces
- Result aggregation
- Memory management for large datasets

### 6. pocketflow-batch
**Path**: `pocketflow/cookbook/pocketflow-batch/`
**Pattern**: Parallel batch processing for multi-target operations
**Purpose**: Batch processing for parallel translation of documents into multiple languages
**When to examine**:
- Implementing parallel processing of multiple related tasks
- Multi-language translation workflows
- Batch operations with shared inputs
- Performance optimization for similar tasks
**Key features**:
- Anthropic API integration
- Parallel batch processing
- Multi-language translation
- Markdown content preservation
- Performance comparison metrics

### 7. pocketflow-chat-guardrail
**Path**: `pocketflow/cookbook/pocketflow-chat-guardrail/`
**Pattern**: Chat with input validation and content filtering
**Purpose**: Chat application with topic-specific guardrails to ensure only valid queries are processed
**When to examine**:
- Adding content moderation to chat systems
- Implementing input validation with LLMs
- Building topic-specific filters
- Creating retry logic for invalid inputs
**Key features**:
- LLM-based input validation
- Topic filtering and guardrails
- Retry mechanisms for invalid queries
- Flow control with validation loops
- Content moderation patterns

### 8. pocketflow-chat-memory
**Path**: `pocketflow/cookbook/pocketflow-chat-memory/`
**Pattern**: Chat with retrieval-based memory
**Purpose**: Advanced chat with sliding window memory and vector-based retrieval of relevant conversations
**When to examine**:
- Implementing context-aware conversations
- Building memory systems for chatbots
- Vector similarity search integration
- Managing conversation context
**Key features**:
- Sliding window memory management
- OpenAI embeddings for conversation vectors
- Vector similarity search for context retrieval
- Relevant context injection into prompts
- Memory persistence across sessions

### 9. pocketflow-chat
**Path**: `pocketflow/cookbook/pocketflow-chat/`
**Pattern**: Simple conversational interface
**Purpose**: Basic chat application with conversation history using self-looping node
**When to examine**:
- Building basic conversational interfaces
- Understanding self-loop patterns
- Implementing chat history management
- Simple LLM chat integration
**Key features**:
- Self-looping node pattern
- Conversation history management
- OpenAI GPT-4o integration
- Simple chat interface
- Exit condition handling

### 10. pocketflow-communication
**Path**: `pocketflow/cookbook/pocketflow-communication/`
**Pattern**: Shared Store pattern demonstration
**Purpose**: Shows how nodes communicate through shared store for state persistence
**When to examine**:
- Understanding inter-node communication
- Learning shared store usage patterns
- Managing state across multiple node executions
- Implementing stateful workflows
**Key features**:
- Multiple nodes sharing state via shared store
- State persistence across node transitions
- Natural key naming conventions
- Data flow between nodes
- State management patterns

### 11. pocketflow-flow
**Path**: `pocketflow/cookbook/pocketflow-flow/`
**Pattern**: Interactive flow with branching control
**Purpose**: Text transformation tool with user-driven menu and action-based transitions
**When to examine**:
- Building interactive CLI tools
- Implementing menu-driven workflows
- Understanding action-based flow transitions
- Creating user-controlled loops
**Key features**:
- Interactive CLI interface with menus
- Action-based transitions ("continue", "exit")
- Flow with branching logic
- Continuous loop processing
- User input handling

### 12. pocketflow-hello-world
**Path**: `pocketflow/cookbook/pocketflow-hello-world/`
**Pattern**: Minimal PocketFlow application setup
**Purpose**: Simplest possible PocketFlow implementation to demonstrate basic project structure
**When to examine**:
- Starting your first PocketFlow project
- Understanding minimal requirements and dependencies
- Learning basic project organization
- Reference for simplest possible implementation
**Key features**:
- Basic Node class implementation
- Simple Flow creation and execution
- Minimal dependencies
- Clean project structure with utils/
- Basic LLM integration example

### 13. pocketflow-llm-streaming
**Path**: `pocketflow/cookbook/pocketflow-llm-streaming/`
**Pattern**: Real-time LLM response streaming
**Purpose**: Streaming LLM responses with user interrupt capability and real-time display
**When to examine**:
- Building interactive LLM applications
- Implementing streaming responses
- Adding user interrupt features
- Real-time response display
**Key features**:
- OpenAI streaming API integration
- Threading for interrupt handling
- Real-time response display
- User interrupt capability
- Fake streaming for testing

### 14. pocketflow-majority-vote
**Path**: `pocketflow/cookbook/pocketflow-majority-vote/`
**Pattern**: Consensus-based reasoning
**Purpose**: Multiple LLM attempts with majority vote aggregation for improved accuracy
**When to examine**:
- Solving complex reasoning problems
- Improving reliability of LLM outputs
- Implementing consensus mechanisms
- Statistical validation of AI responses
**Key features**:
- Multiple LLM query execution
- Majority vote consensus algorithm
- Anthropic Claude API integration
- Structured output parsing
- Statistical reliability improvement

### 15. pocketflow-map-reduce
**Path**: `pocketflow/cookbook/pocketflow-map-reduce/`
**Pattern**: Classic Map-Reduce implementation
**Purpose**: Resume evaluation using map phase (read files), batch processing (evaluate), reduce phase (aggregate)
**When to examine**:
- Processing multiple files with LLM evaluation
- Implementing data aggregation workflows
- Document analysis and summarization
- Batch evaluation patterns
**Key features**:
- Classic Map-Reduce pattern implementation
- BatchNode for map phase processing
- Structured YAML output from LLMs
- File processing and aggregation
- Resume evaluation and ranking

### 16. pocketflow-mcp
**Path**: `pocketflow/cookbook/pocketflow-mcp/`
**Pattern**: Model Context Protocol (MCP) integration
**Purpose**: Toggle between MCP and local functions for tool discovery and execution
**When to examine**:
- Integrating external tools via MCP
- Comparing MCP with traditional function calling
- Dynamic tool discovery
- Protocol switching mechanisms
**Key features**:
- MCP server integration
- Tool discovery through MCP protocol
- Dynamic tool execution
- Local vs remote function calling
- Protocol abstraction layer

### 17. pocketflow-multi-agent
**Path**: `pocketflow/cookbook/pocketflow-multi-agent/`
**Pattern**: Asynchronous multi-agent coordination
**Purpose**: Multiple agents communicating via message queues in a Taboo word game
**When to examine**:
- Building multi-agent systems
- Implementing async communication patterns
- Game mechanics with AI agents
- Agent coordination and turn management
**Key features**:
- AsyncNode implementation
- Message queue communication
- Multi-agent coordination
- Turn-based game mechanics
- Asyncio integration

### 18. pocketflow-nested-batch
**Path**: `pocketflow/cookbook/pocketflow-nested-batch/`
**Pattern**: Hierarchical batch processing
**Purpose**: BatchFlow within BatchFlow for processing nested data structures (school/class/student)
**When to examine**:
- Processing hierarchical data structures
- Implementing nested iterations
- Multi-level batch processing
- Parameter inheritance in nested contexts
**Key features**:
- Nested BatchFlow implementation
- Hierarchical data processing
- Parameter inheritance between batch levels
- Multi-level iteration
- Structured data organization

### 19. pocketflow-node
**Path**: `pocketflow/cookbook/pocketflow-node/`
**Pattern**: Robust Node implementation with error handling
**Purpose**: Text summarization with comprehensive retry mechanisms and fallback handling
**When to examine**:
- Learning core Node patterns and lifecycle
- Implementing error handling and retries
- Understanding prep/exec/post separation
- Building robust LLM integrations
**Key features**:
- Full Node lifecycle (prep/exec/post) implementation
- Retry configuration and mechanisms
- Fallback handling for failed operations
- LLM integration with error recovery
- Shared store usage patterns

### 20. pocketflow-parallel-batch-flow
**Path**: `pocketflow/cookbook/pocketflow-parallel-batch-flow/`
**Pattern**: Parallel flow execution for file processing
**Purpose**: Concurrent image processing showing 8x speedup for filter application
**When to examine**:
- Concurrent file processing workflows
- Image processing optimization
- Parallel execution of complete flows
- Performance optimization for batch operations
**Key features**:
- AsyncParallelBatchFlow implementation
- Image processing with multiple filters
- 8x performance improvement
- Concurrent flow execution
- Resource optimization with semaphores

## Advanced Examples (21-34)

### 21. pocketflow-parallel-batch
**Path**: `pocketflow/cookbook/pocketflow-parallel-batch/`
**Pattern**: Async and parallel processing with `AsyncFlow` and `AsyncParallelBatchNode`
**Purpose**: Demonstrates parallel translation of documents into multiple languages concurrently
**When to examine**:
- When implementing parallel API calls
- For I/O-bound operations that benefit from concurrency
- When comparing sequential vs parallel execution times
**Key features**:
- `AsyncParallelBatchNode` for concurrent processing
- Asyncio integration
- Performance comparison (1136s sequential vs 209s parallel)
- Batch preparation and concurrent execution

### 22. pocketflow-rag
**Path**: `pocketflow/cookbook/pocketflow-rag/`
**Pattern**: Retrieval Augmented Generation (RAG) system
**Purpose**: Document chunking, vector embeddings, and FAISS-based retrieval with LLM generation
**When to examine**:
- Building RAG systems from scratch
- Understanding vector search with FAISS
- Implementing document chunking strategies
- Combining retrieval with generation
**Key features**:
- Two-phase pipeline (offline indexing + online retrieval)
- FAISS vector index creation
- Document chunking for better retrieval
- Query embedding and similarity search

### 23. pocketflow-structured-output
**Path**: `pocketflow/cookbook/pocketflow-structured-output/`
**Pattern**: Structured data extraction using prompt engineering
**Purpose**: Extract structured data from unstructured text (resume parsing) using YAML formatting
**When to examine**:
- Extracting structured data without JSON mode
- Using YAML for structured output (more reliable than JSON)
- Resume/document parsing
- Validating LLM outputs
**Key features**:
- YAML-based structured output
- Index-based skill extraction
- Single node for parsing
- Output validation

### 24. pocketflow-supervisor
**Path**: `pocketflow/cookbook/pocketflow-supervisor/`
**Pattern**: Supervisor pattern for quality control
**Purpose**: Oversees an unreliable agent, rejecting bad answers and requesting retries
**When to examine**:
- Implementing quality control loops
- Building reliable systems with unreliable components
- Human-in-the-loop patterns
- Retry logic with validation
**Key features**:
- Supervisor node that validates outputs
- Retry mechanism for rejected answers
- Simulated unreliable agent (50% failure rate)
- Quality evaluation logic

### 25. pocketflow-text2sql
**Path**: `pocketflow/cookbook/pocketflow-text2sql/`
**Pattern**: Natural language to SQL with debugging loop
**Purpose**: Convert natural language questions to executable SQL with automatic error correction
**When to examine**:
- Building text-to-SQL systems
- Implementing self-correcting workflows
- Database schema awareness
- Error handling and retry logic
**Key features**:
- Schema extraction from SQLite
- LLM-powered SQL generation
- Automated debugging loop for failed queries
- YAML structured output for SQL
- Max retry limits

### 26. pocketflow-thinking
**Path**: `pocketflow/cookbook/pocketflow-thinking/`
**Pattern**: Chain-of-Thought reasoning orchestration
**Purpose**: External orchestration of step-by-step reasoning for complex problems
**When to examine**:
- Implementing Chain-of-Thought reasoning
- Building external thinking orchestrators
- Solving complex reasoning problems
- Managing multi-step planning
**Key features**:
- Self-looping node for iterative thinking
- Plan management and execution tracking
- Step evaluation and refinement
- External control of reasoning process
- Comparison with native thinking modes

### 27. pocketflow-tool-crawler
**Path**: `pocketflow/cookbook/pocketflow-tool-crawler/`
**Pattern**: Web crawling with content analysis
**Purpose**: Crawl websites and analyze content using LLM for summaries and classification
**When to examine**:
- Building web crawlers
- Content analysis pipelines
- Batch processing web pages
- Domain-bounded crawling
**Key features**:
- Respects domain boundaries
- BeautifulSoup HTML parsing
- GPT-4 content analysis
- Batch processing for efficiency
- Report generation

### 28. pocketflow-tool-database
**Path**: `pocketflow/cookbook/pocketflow-tool-database/`
**Pattern**: Database operations with clean separation of concerns
**Purpose**: SQLite integration with proper connection management and SQL injection prevention
**When to examine**:
- Database integration patterns
- Clean code organization
- SQL injection prevention
- Resource management
**Key features**:
- Separation of tools and nodes
- Parameterized queries
- Connection management
- Schema management
- Task management example

### 29. pocketflow-tool-embeddings
**Path**: `pocketflow/cookbook/pocketflow-tool-embeddings/`
**Pattern**: OpenAI embeddings API integration
**Purpose**: Generate text embeddings with proper API key management and code organization
**When to examine**:
- Working with embeddings APIs
- API key management patterns
- Environment configuration
- Clean project structure
**Key features**:
- Environment variable handling
- .env file support
- Centralized OpenAI client
- Modular code organization

### 30. pocketflow-tool-pdf-vision
**Path**: `pocketflow/cookbook/pocketflow-tool-pdf-vision/`
**Pattern**: PDF processing with Vision API
**Purpose**: Extract text from PDF documents using GPT-4 Vision for OCR
**When to examine**:
- PDF to image conversion
- OCR with Vision APIs
- Batch processing PDFs
- Handling scanned documents
**Key features**:
- PDF to image conversion with size limits
- Vision API for text extraction
- Page order maintenance
- Custom extraction prompts
- Batch directory processing

### 31. pocketflow-tool-search
**Path**: `pocketflow/cookbook/pocketflow-tool-search/`
**Pattern**: Web search with analysis
**Purpose**: Search using SerpAPI and analyze results with LLM
**When to examine**:
- Integrating search APIs
- Search result analysis
- Multi-API workflows
- Structured search insights
**Key features**:
- SerpAPI Google search
- GPT-4 result analysis
- Summary generation
- Follow-up query suggestions
- Clean CLI interface

### 32. pocketflow-visualization
**Path**: `pocketflow/cookbook/pocketflow-visualization/`
**Pattern**: Flow visualization with D3.js
**Purpose**: Create interactive visualizations of PocketFlow graphs
**When to examine**:
- Visualizing complex workflows
- Understanding flow relationships
- Debugging flow connections
- Creating documentation diagrams
**Key features**:
- Interactive D3.js graphs
- Group visualization for flows
- Draggable nodes
- Force-directed layout
- Mermaid diagram generation
- Inter-flow connections

### 33. pocketflow-web-hitl
**Path**: `pocketflow/cookbook/pocketflow-web-hitl/`
**Pattern**: Web-based Human-in-the-Loop with Server-Sent Events
**Purpose**: FastAPI web app for human review and approval workflows
**When to examine**:
- Building HITL web interfaces
- Real-time updates with SSE
- Async workflow integration
- Human approval patterns
**Key features**:
- FastAPI backend
- Server-Sent Events for real-time updates
- Async review node with event waiting
- Background task scheduling
- Approve/reject UI

### 34. pocketflow-workflow
**Path**: `pocketflow/cookbook/pocketflow-workflow/`
**Pattern**: Multi-stage content generation workflow
**Purpose**: Article writing workflow with outline, content, and style phases
**When to examine**:
- Multi-stage content generation
- Sequential LLM workflows
- Style transformation
- Structured content creation
**Key features**:
- Three-phase workflow (outline → content → style)
- YAML structured outlines
- Section-based content generation
- Style application
- Word count constraints

*This file represents an inventory of all available examples to use as a reference for building pflow nodes, flows and other components.*
