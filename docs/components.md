# pflow Component Inventory: MVP vs v2.0

This document provides a comprehensive inventory of all components and subsystems required for pflow, clearly distinguishing between MVP (v0.1) requirements and v2.0 features.

## MVP (v0.1) Components

### 1. Core Foundation

#### 1.1 pocketflow Framework Integration

- **Purpose**: Base execution engine (100-line Python framework)
- **Components**:
  - `Node` base class with `prep()`, `exec()`, `post()` lifecycle
  - `Flow` class for orchestration
  - `>>` operator for flow composition
  - Built-in retry mechanism (`max_retries`, `wait` parameters)
  - `set_params()` method for node configuration

#### 1.2 Shared Store System

- **Purpose**: Flow-scoped memory for inter-node communication
- **Components**:
  - Simple dictionary implementation
  - Natural key conventions (e.g., `shared["text"]`, `shared["url"]`)
  - Reserved key: `shared["stdin"]` for piped input
  - Transient per-run lifecycle management
  - Direct access pattern (no persistence)

#### 1.3 NodeAwareSharedStore Proxy

- **Purpose**: Optional transparent key mapping for complex flows
- **Components**:
  - Proxy class implementation
  - Input/output mapping support
  - Zero-overhead pass-through when no mappings defined
  - Integration with flow execution

### 2. CLI Interface Layer

#### 2.1 CLI Parser

- **Purpose**: Parse and interpret command-line input
- **Components**:
  - Pipe syntax parser (`node1 >> node2`)
  - Flag parser for `--key=value` format
  - "Type flags; engine decides" resolution algorithm
  - Shell pipe detection (stdin handling)
  - Error reporting with suggestions

#### 2.2 CLI Commands (Basic Set)

- **Purpose**: Core command interface
- **Commands**:
  - `pflow <node> [--flags] >> <node> [--flags]` - Execute flow
  - `pflow registry list` - Show available nodes
  - `pflow registry describe <node>` - Show node details
  - `pflow trace <run-id>` - Inspect execution details
  - `pflow validate <flow.json>` - Validate flow IR

#### 2.3 Shell Integration

- **Purpose**: Unix pipe compatibility
- **Components**:
  - Non-TTY stdin detection
  - Content injection to `shared["stdin"]`
  - Pipe content hashing for traces
  - Integration with standard Unix tools

### 3. Node System

#### 3.1 Node Registry

- **Purpose**: Discover and manage available nodes
- **Components**:
  - Filesystem-based registry structure
  - Node discovery mechanism
  - Metadata extraction from docstrings
  - Index file for fast lookups
  - Registry commands (list, describe, validate)

#### 3.2 Node Metadata System

- **Purpose**: Structured interface definitions for action-based nodes
- **Components**:
  - Docstring parser for interface extraction
  - JSON metadata schema with action definitions
  - Input/output key definitions per action
  - Action-specific parameter specifications with defaults
  - Purity annotations (`@flow_safe`)
  - Action discovery and validation

#### 3.3 Built-in Platform Nodes (MVP Set)

- **Purpose**: Action-based platform functionality
- **Required Platform Nodes**:
  - `github` - actions: `get-issue`, `create-issue`, `list-prs`, `create-pr`, `get-files`, `merge-pr`
  - `claude` - actions: `analyze`, `implement`, `review`, `explain`, `refactor`
  - `ci` - actions: `run-tests`, `get-status`, `trigger-build`, `get-logs`
  - `git` - actions: `commit`, `push`, `create-branch`, `merge`, `status`
  - `file` - actions: `read`, `write`, `copy`, `move`, `delete`
  - `shell` - actions: `exec`, `pipe`, `background`

### 4. Planning & Validation

#### 4.1 CLI Path Planner (MVP Focus)

- **Purpose**: Validate and compile CLI syntax to IR
- **Components**:
  - CLI syntax parser
  - Node existence validation
  - Interface compatibility checking
  - Basic mapping generation
  - IR assembly
  - Direct execution path (no user confirmation)

#### 4.2 Validation Framework

- **Purpose**: Ensure flow correctness
- **Components**:
  - JSON schema validation
  - Node interface compatibility
  - DAG structure validation (no cycles)
  - Parameter type checking
  - Execution config validation
  - Comprehensive error reporting

#### 4.3 JSON IR System

- **Purpose**: Machine-readable flow representation
- **Components**:
  - IR schema definition (v0.1.0)
  - Node specifications
  - Edge definitions
  - Mapping definitions
  - Metadata structure
  - Schema validation

### 5. Execution Engine

#### 5.1 Runtime Core

- **Purpose**: Execute validated flows
- **Components**:
  - IR loader and parser
  - Node instantiation from registry
  - Parameter configuration
  - Flow wiring based on edges
  - Proxy setup when mappings defined
  - Sequential execution (MVP is synchronous)

#### 5.2 Caching System (Basic)

- **Purpose**: Performance optimization for pure nodes
- **Components**:
  - Cache key computation
  - Local filesystem cache (~/.pflow/cache/)
  - `@flow_safe` eligibility checking
  - Cache hit/miss handling
  - Basic cache invalidation

#### 5.3 Error Handling

- **Purpose**: Graceful failure management
- **Components**:
  - Try-catch wrapping
  - Error context capture
  - Shared store snapshot on failure
  - Fail-fast behavior (default)
  - Retry logic for `@flow_safe` nodes

### 6. Observability

#### 6.1 Tracing System

- **Purpose**: Execution visibility
- **Components**:
  - Execution timeline tracking
  - Node input/output capture
  - Parameter resolution logging
  - Cache hit/miss tracking
  - Error and retry logging
  - Trace file generation

#### 6.2 Run Logs

- **Purpose**: Persistent execution records
- **Components**:
  - Run ID generation
  - Timestamp tracking
  - Status recording (SUCCESS/FAILED)
  - Shared store evolution
  - Performance metrics

### 7. Storage & Persistence

#### 7.1 Lockfile System

- **Purpose**: Reproducible execution
- **Components**:
  - `flow.lock.json` generation
  - IR hash computation
  - Node version pinning
  - Signature validation
  - Lockfile loading

#### 7.2 Local Storage

- **Purpose**: System data persistence
- **Structure**:

  ```
  ~/.pflow/
  ├── registry/     # Node registry
  ├── cache/        # Execution cache
  ├── traces/       # Execution traces
  └── logs/         # Run logs
  ```

### 8. Testing Infrastructure

#### 8.1 Node Testing Framework

- **Purpose**: Ensure node correctness
- **Components**:
  - Simple test harness
  - Shared store test utilities
  - Assertion helpers
  - Mock/stub support

#### 8.2 Flow Testing Support

- **Purpose**: End-to-end validation
- **Components**:
  - Flow execution testing
  - IR validation testing
  - CLI command testing

### 9. Documentation & Help

#### 9.1 Built-in Help System

- **Purpose**: User assistance
- **Components**:
  - `--help` for all commands
  - Node interface documentation
  - Error message suggestions
  - Example flows

## Version 2.0 Components

### 1. Natural Language Planning

#### 1.1 LLM Integration

- **Purpose**: Convert natural language to flows
- **Components**:
  - LLM model integration (Claude/GPT)
  - Prompt engineering system
  - Context window management
  - Token usage tracking

#### 1.2 Full Planner Implementation

- **Purpose**: Intelligent flow generation
- **Components**:
  - Metadata context loader
  - Semantic node selection
  - Flow structure generation
  - Retry with feedback loop
  - User approval workflow
  - CLI preview generation

#### 1.3 Retrieval System

- **Purpose**: Reuse existing flows
- **Components**:
  - Flow description indexing
  - Semantic similarity search
  - Flow library management
  - Sub-flow composition

### 2. Advanced Flow Control

#### 2.1 Action-Based Transitions

- **Purpose**: Conditional execution paths
- **Components**:
  - `node - "action" >> handler` syntax
  - Action string returns from `post()`
  - Multiple transition paths
  - Action validation

#### 2.2 Error Recovery Patterns

- **Purpose**: Sophisticated failure handling
- **Components**:
  - Branching error handlers
  - Retry with different strategies
  - Fallback flows
  - Partial failure recovery

### 3. MCP Integration

#### 3.1 MCP Wrapper Generation

- **Purpose**: Integrate external tools
- **Components**:
  - MCP manifest parser
  - Node class generator
  - Natural interface mapping
  - Error action mapping

#### 3.2 MCP Transport Support

- **Purpose**: Connect to MCP servers
- **Components**:
  - stdio transport
  - SSE (Server-Sent Events)
  - Unix domain sockets
  - Named pipes (Windows)

#### 3.3 MCP Security

- **Purpose**: Secure tool integration
- **Components**:
  - Authentication handling
  - TLS/HTTPS enforcement
  - Token management
  - Scope validation

### 4. CLI Enhancements

#### 4.1 CLI Autocomplete

- **Purpose**: Interactive command completion
- **Components**:
  - Shell completion scripts
  - Dynamic suggestion engine
  - Context-aware completions
  - Node/flag discovery
  - Type shadow store hints

#### 4.2 Interactive Mode

- **Purpose**: Missing data prompts
- **Components**:
  - TTY detection
  - User input prompts
  - Default value suggestions
  - Validation feedback

### 5. Advanced Node Features

#### 5.1 Async Node Support

- **Purpose**: Concurrent execution
- **Components**:
  - `AsyncNode` base class
  - `async`/`await` lifecycle
  - `AsyncFlow` orchestration
  - Parallel batch processing

#### 5.2 Namespace & Versioning

- **Purpose**: Node organization
- **Components**:
  - Namespace syntax (`core/node@1.0.0`)
  - Semantic versioning
  - Version resolution
  - Dependency management

### 6. Enhanced Validation

#### 6.1 Type Shadow Store

- **Purpose**: Real-time compatibility feedback
- **Components**:
  - Type accumulation during composition
  - Compatibility checking
  - Advisory feedback
  - Autocomplete integration

#### 6.2 Advanced Validation

- **Purpose**: Comprehensive correctness
- **Components**:
  - Type-based validation
  - Resource constraint checking
  - Security policy validation
  - Performance prediction

### 7. Performance Optimizations

#### 7.1 Advanced Caching

- **Purpose**: Sophisticated optimization
- **Components**:
  - Distributed cache support
  - Cache warming strategies
  - Partial result caching
  - Cache eviction policies

#### 7.2 Parallel Execution

- **Purpose**: Performance improvement
- **Components**:
  - DAG analysis for parallelism
  - Worker pool management
  - Result synchronization
  - Resource management

### 8. Developer Experience

#### 8.1 Flow Debugging

- **Purpose**: Enhanced troubleshooting
- **Components**:
  - Step-through debugging
  - Breakpoint support
  - State inspection
  - Flow visualization

#### 8.2 Testing Enhancements

- **Purpose**: Comprehensive testing
- **Components**:
  - Integration test framework
  - Performance benchmarking
  - Fuzzing support
  - Coverage tracking

### 9. Ecosystem Features

#### 9.1 Flow Marketplace

- **Purpose**: Share and discover flows
- **Components**:
  - Flow publishing system
  - Discovery interface
  - Rating/feedback system
  - Version management

#### 9.2 Plugin System

- **Purpose**: Extensibility
- **Components**:
  - Plugin API
  - Loading mechanism
  - Dependency resolution
  - Security sandboxing

## Critical MVP Dependencies

These components are **absolutely required** for MVP to fulfill core promises:

1. **pocketflow framework** - The entire execution model depends on this
2. **Shared store with natural interfaces** - Core innovation
3. **CLI pipe syntax parsing** - Primary user interface
4. **Node registry with metadata** - Required for discovery
5. **JSON IR generation** - Enables reproducibility
6. **Basic validation** - Ensures correctness
7. **Execution tracing** - Required for debugging
8. **Shell pipe integration** - Key usability feature
9. **Error reporting** - User experience requirement
10. **Lockfile generation** - Reproducibility guarantee

## Implementation Priority

### Priority 1: Foundation

1. pocketflow integration
2. Basic shared store
3. Simple CLI parser
4. Core node structure

### Priority 2: Node System

1. Registry implementation
2. Metadata extraction
3. Basic built-in nodes
4. Node discovery

### Priority 3: Execution

1. Runtime engine
2. CLI resolution algorithm
3. Basic caching
4. Error handling

### Priority 4: Polish

1. Advanced Tracing system
2. Performance optimization

This inventory ensures that pflow MVP delivers on its core promise of turning CLI commands into permanent, fast, reproducible workflows while maintaining a clear path to v2.0 enhancements.
