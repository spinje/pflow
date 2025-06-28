# PocketFlow Cookbook Inventory

## Overview

This document provides a comprehensive catalog of PocketFlow cookbook examples, categorized by pattern type and MVP compatibility for the pflow project.

## Compatibility Legend

- ✅ **Direct**: Can be used as-is for pflow MVP
- ⚠️ **Needs Adaptation**: Valuable patterns but requires modification
- ❌ **Not Compatible**: Uses features not in pflow MVP (async, conditionals, etc.)

## Example Categories

### 1. Core Building Blocks (Foundation Patterns)

#### pocketflow-hello-world
- **Pattern**: Minimal PocketFlow setup
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Basic Node implementation
  - Simple Flow creation
  - Minimal dependencies
- **Use for pflow**: Foundation for all node implementations

#### pocketflow-node
- **Pattern**: Robust Node with error handling
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Full prep/exec/post lifecycle
  - Retry mechanisms
  - Fallback handling
- **Use for pflow**: Template for all platform nodes

#### pocketflow-flow
- **Pattern**: Interactive flow with branching
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Action-based transitions
  - User interaction
  - Menu-driven flow
- **Use for pflow**: Flow orchestration patterns

#### pocketflow-communication
- **Pattern**: Shared Store communication
- **Compatibility**: ✅ Direct
- **Key Features**:
  - State persistence
  - Inter-node data flow
  - Natural key naming
- **Use for pflow**: Shared store patterns

### 2. LLM Integration Patterns

#### pocketflow-chat
- **Pattern**: Simple LLM chat
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Conversation history
  - Self-looping node
  - Exit conditions
- **Use for pflow**: LLM node implementation

#### pocketflow-structured-output
- **Pattern**: YAML-based extraction
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Structured data extraction
  - YAML formatting (more reliable than JSON)
  - Output validation
- **Use for pflow**: Structured output from LLMs

#### pocketflow-llm-streaming
- **Pattern**: Real-time streaming
- **Compatibility**: ❌ Not Compatible
- **Issues**: Uses async/threading
- **Alternative**: Use synchronous LLM calls in MVP

#### pocketflow-chat-memory
- **Pattern**: Vector-based memory
- **Compatibility**: ⚠️ Needs Adaptation
- **Key Features**:
  - Embeddings integration
  - Context retrieval
- **Adaptation**: Simplify to basic history without vectors

#### pocketflow-chat-guardrail
- **Pattern**: Input validation
- **Compatibility**: ⚠️ Needs Adaptation
- **Key Features**:
  - Topic filtering
  - Retry loops
- **Adaptation**: Simplify retry mechanism, remove complex loops

### 3. Batch Processing Patterns

#### pocketflow-batch-node
- **Pattern**: Chunk-based processing
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Memory-efficient processing
  - Result aggregation
  - Large file handling
- **Use for pflow**: File processing nodes

#### pocketflow-map-reduce
- **Pattern**: Classic Map-Reduce
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Document processing
  - Result aggregation
  - YAML structured output
- **Use for pflow**: Multi-file workflows

#### pocketflow-batch-flow
- **Pattern**: Parameter batching
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Multiple parameter sets
  - Same workflow, different inputs
- **Use for pflow**: Batch execution patterns

#### pocketflow-nested-batch
- **Pattern**: Hierarchical batching
- **Compatibility**: ⚠️ Needs Adaptation
- **Issues**: Complex nesting might be overkill
- **Adaptation**: Flatten to single-level batching

#### pocketflow-parallel-batch
- **Pattern**: Async parallel processing
- **Compatibility**: ❌ Not Compatible
- **Issues**: Uses AsyncParallelBatchNode
- **Alternative**: Use sequential processing in MVP

#### pocketflow-parallel-batch-flow
- **Pattern**: Concurrent flows
- **Compatibility**: ❌ Not Compatible
- **Issues**: Uses AsyncParallelBatchFlow
- **Alternative**: Sequential execution only

### 4. Tool Integration Patterns

#### pocketflow-tool-database
- **Pattern**: SQLite integration
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Clean separation of concerns
  - Parameterized queries
  - Connection management
- **Use for pflow**: Database nodes

#### pocketflow-tool-search
- **Pattern**: Web search API
- **Compatibility**: ✅ Direct
- **Key Features**:
  - API integration
  - Result analysis
- **Use for pflow**: Search nodes

#### pocketflow-tool-pdf-vision
- **Pattern**: PDF processing
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Vision API usage
  - Batch processing
- **Use for pflow**: Document processing

#### pocketflow-tool-embeddings
- **Pattern**: Embeddings API
- **Compatibility**: ✅ Direct
- **Key Features**:
  - API key management
  - Environment variables
- **Use for pflow**: When adding embeddings later

#### pocketflow-tool-crawler
- **Pattern**: Web crawling
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Domain boundaries
  - Content analysis
- **Use for pflow**: Web scraping nodes

### 5. Agent & Decision Patterns

#### pocketflow-agent
- **Pattern**: Decision loops
- **Compatibility**: ⚠️ Needs Adaptation
- **Issues**: Complex decision loops, dynamic parameters
- **Adaptation**: Simplify to linear flow with predefined decisions

#### pocketflow-supervisor
- **Pattern**: Quality control
- **Compatibility**: ⚠️ Needs Adaptation
- **Issues**: Complex retry loops
- **Adaptation**: Fixed retry count, simpler validation

#### pocketflow-thinking
- **Pattern**: Chain-of-Thought
- **Compatibility**: ⚠️ Needs Adaptation
- **Issues**: Self-looping complexity
- **Adaptation**: Linear thinking steps

#### pocketflow-majority-vote
- **Pattern**: Consensus voting
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Multiple LLM calls
  - Result aggregation
- **Use for pflow**: Reliability patterns

### 6. Workflow Patterns

#### pocketflow-workflow
- **Pattern**: Multi-stage pipeline
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Sequential stages
  - Content generation
  - Style application
- **Use for pflow**: Complex workflows

#### pocketflow-text2sql
- **Pattern**: SQL generation
- **Compatibility**: ⚠️ Needs Adaptation
- **Issues**: Complex debugging loop
- **Adaptation**: Simplify error handling

#### pocketflow-rag
- **Pattern**: RAG implementation
- **Compatibility**: ✅ Direct
- **Key Features**:
  - Vector search
  - Document chunking
  - Two-phase pipeline
- **Use for pflow**: RAG patterns (post-MVP)

### 7. Advanced Patterns (Not MVP Compatible)

#### pocketflow-async-basic
- **Pattern**: AsyncNode
- **Compatibility**: ❌ Not Compatible
- **Issues**: Async operations not in MVP

#### pocketflow-multi-agent
- **Pattern**: Multi-agent coordination
- **Compatibility**: ❌ Not Compatible
- **Issues**: Async + message queues

#### pocketflow-a2a
- **Pattern**: Agent-to-Agent protocol
- **Compatibility**: ❌ Not Compatible
- **Issues**: Server architecture

#### pocketflow-mcp
- **Pattern**: Model Context Protocol
- **Compatibility**: ❌ Not Compatible
- **Issues**: MCP is v2.0 feature

#### pocketflow-web-hitl
- **Pattern**: Web UI integration
- **Compatibility**: ❌ Not Compatible
- **Issues**: Complex state management

#### pocketflow-visualization
- **Pattern**: Flow visualization
- **Compatibility**: ❌ Not Compatible
- **Issues**: UI component, not core functionality

### 8. Full Application Examples

The following are complete repositories demonstrating advanced patterns:

1. **PocketFlow-Tutorial-Website-Chatbot** - Agent + RAG + Map-Reduce
2. **PocketFlow-Tutorial-Danganronpa-Simulator** - Multi-agent game
3. **Tutorial-Codebase-Knowledge** - Documentation generator
4. **Tutorial-Cursor** - Coding assistant
5. **Tutorial-AI-Paul-Graham** - Personality RAG
6. **Tutorial-Youtube-Made-Simple** - Video summarizer
7. **Tutorial-Cold-Email-Personalization** - Email personalization

These are too complex for direct pattern extraction but provide architectural guidance.

## Summary Statistics

- **Total Examples**: 41 (34 simple + 7 full apps)
- **MVP Compatible**: 17 (50%)
- **Need Adaptation**: 8 (23.5%)
- **Not Compatible**: 9 (26.5%)
- **Full Apps**: 7 (reference only)

## Priority Examples for pflow Tasks

### High Priority (Study First)
1. `pocketflow-node` - Node implementation template
2. `pocketflow-communication` - Shared store patterns
3. `pocketflow-flow` - Flow orchestration
4. `pocketflow-batch-node` - File processing
5. `pocketflow-chat` - LLM integration

### Medium Priority (Task-Specific)
1. `pocketflow-tool-database` - Database nodes
2. `pocketflow-tool-search` - API integration
3. `pocketflow-map-reduce` - Batch workflows
4. `pocketflow-workflow` - Multi-stage flows
5. `pocketflow-structured-output` - Data extraction

### Low Priority (Reference Only)
- All async/parallel examples
- Advanced agent patterns
- Full application examples

## Key Adaptation Patterns

### 1. Dynamic Parameters → Proxy Pattern
```python
# PocketFlow (incompatible)
node = MyNode()
node.set_params({"temperature": 0.7})

# pflow (adapted)
proxy = ProxyNode(MyNode(), param_mapping={
    "temp": "temperature"
})
```

### 2. Conditional Flows → Linear with Actions
```python
# PocketFlow (incompatible)
flow = decide_node - "search" >> search_node - "done" >> end_node
                   - "think" >> think_node

# pflow (adapted)
flow = decide_node >> router_node >> end_node
# Router uses action strings to skip nodes
```

### 3. Async Operations → Sync
```python
# PocketFlow (incompatible)
async def exec_async(self, shared):
    result = await llm_call()

# pflow (adapted)
def exec(self, shared):
    result = llm_call()  # Blocking call
```

### 4. Complex State → Simple Store
```python
# PocketFlow (complex)
self.memory.add_embedding(text, vector)
relevant = self.memory.search(query)

# pflow (adapted)
shared["history"] = shared.get("history", [])
shared["history"].append(text)
```

## Next Steps

1. Deep dive into HIGH priority examples for node patterns
2. Extract specific code patterns for each pflow task
3. Create adaptation guides for complex patterns
4. Generate pocketflow-patterns.md files for relevant tasks
