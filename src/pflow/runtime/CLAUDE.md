# CLAUDE.md - Runtime Module Documentation

## Executive Summary

The `src/pflow/runtime/` module is the **compilation and execution infrastructure** that transforms JSON IR into executable PocketFlow objects. It implements a sophisticated multi-layer wrapper architecture for template resolution, namespacing, and instrumentation while maintaining full compatibility with the PocketFlow framework.

**Core Responsibility**: Transform workflow IR → executable Flow objects with automatic template resolution, collision prevention, and comprehensive instrumentation.

## Module Architecture

```
┌─────────────────────────────────────────────┐
│         Planning System (generates IR)       │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│           compile_ir_to_flow()               │
│         (main entry point)                   │
└──────────────────┬──────────────────────────┘
                   │
    ┌──────────────┼──────────────┬───────────┐
    ▼              ▼              ▼           ▼
┌────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐
│Validate│ │Instantiate│ │  Wire   │ │ Wrap   │
│  IR    │ │  Nodes   │ │  Nodes  │ │ Nodes  │
└────────┘ └──────────┘ └──────────┘ └────────┘
    │              │              │           │
    └──────────────┴──────────────┴───────────┘
                   │
                   ▼
           Executable Flow Object
```

## File Structure

```
src/pflow/runtime/
├── __init__.py                  # Module exports (3 public functions)
├── batch_node.py               # Batch processing wrapper (sequential/parallel)
├── compiler.py                  # Main IR→Flow compiler (1042 lines)
├── instrumented_wrapper.py      # Metrics, tracing, caching (1168 lines)
├── node_wrapper.py             # Template resolution wrapper (680 lines)
├── namespaced_wrapper.py       # Collision prevention wrapper (95 lines)
├── namespaced_store.py         # Namespaced store proxy (156 lines)
├── template_resolver.py        # Template variable resolution (385 lines)
├── template_validator.py       # Template validation logic (522 lines)
├── workflow_executor.py        # Nested workflow executor node (328 lines)
├── workflow_trace.py           # Trace collection system (517 lines)
├── workflow_validator.py       # Workflow validation utilities (159 lines)
└── output_resolver.py          # Output declaration resolver (73 lines)
```

## Public API (via `__init__.py`)

- `compile_ir_to_flow()` - Main compiler function
- `import_node_class()` - Dynamic node class import
- `CompilationError` - Compilation failure exception

## Core Components

### 1. Compiler (`compiler.py`)

**Purpose**: Transforms JSON IR into executable PocketFlow Flow objects.

**Key Functions**:
- `compile_ir_to_flow()` - Main entry point (lines 929-1042) - 11 steps total
- `import_node_class()` - Registry-based node import (lines 103-237)
- `_instantiate_nodes()` - Node creation with wrapping (lines 587-645)
- `_wire_nodes()` - Edge-based flow construction (lines 647-712)
- `_inject_special_parameters()` - MCP/workflow parameter injection (lines 426-501)
- `_parse_mcp_node_type()` - Server name parsing with dash support (lines 357-423)
- `_validate_workflow()` - Consolidates 4 validation steps (lines 768-842)

**Compilation Pipeline**:
1. Parse IR (JSON string or dict)
2. Validate structure, inputs, outputs
3. Instantiate nodes with registry lookup
4. Apply wrapper chain (template → namespace → instrumentation)
5. Wire nodes using edges
6. Create Flow object with start node

**Error Handling**:
```python
class CompilationError(Exception):
    phase: str          # Where error occurred
    node_id: str       # Node being compiled
    node_type: str     # Type of node
    details: dict      # Additional context
    suggestion: str    # Helpful fix suggestion
```

### 2. Wrapper Architecture

#### 2.1 InstrumentedNodeWrapper (`instrumented_wrapper.py`)

**Purpose**: Outermost wrapper providing metrics, tracing, caching, and API error detection.

**Key Features**:
- **Checkpoint System** (lines 518-603): MD5-based configuration caching
- **API Warning Detection** (lines 737-1129): Intelligent error categorization
- **LLM Usage Capture** (lines 100-191): Token tracking and cost attribution
- **Progress Callbacks** (lines 271-321): Real-time execution feedback
- **Trace Recording** (lines 373-409): Detailed debugging information
- **Cache Hit Tracking** (Task 71 - lines 542-601): Records which nodes used cache

**Checkpoint Structure**:
```python
shared["__execution__"] = {
    "completed_nodes": [],     # Successfully executed
    "node_actions": {},       # Actions returned
    "node_hashes": {},       # MD5 config hashes
    "failed_node": None      # Where failure occurred
}

# Cache tracking (Task 71)
shared["__cache_hits__"] = []  # Nodes that hit cache (for JSON output)
```

#### 2.2 NamespacedNodeWrapper (`namespaced_wrapper.py`)

**Purpose**: Middle wrapper providing automatic collision prevention.

**Key Features**:
- Redirects writes to `shared[node_id][key]`
- Reads check both namespace and root level
- Special keys (`__*__`) bypass namespacing for framework coordination
- Transparent to nodes (they don't know about namespacing)

#### 2.3 TemplateAwareNodeWrapper (`node_wrapper.py`)

**Purpose**: Innermost wrapper resolving template variables at runtime.

**Key Features**:
- Separates template vs static parameters
- Resolves `${variable}` syntax during execution
- Preserves type for simple templates
- Recursive validation detects unresolved templates in strings/lists/dicts
- Partial resolution detection via set intersection (Task 85)
- Type validation prevents dict/list → str mismatches (uses registry metadata, shows fix suggestions)
- Strict mode (default): Template/type errors fatal (triggers repair)
- Permissive mode: Warnings only, stores errors in `__template_errors__`

#### 2.4 PflowBatchNode (`batch_node.py`)

**Purpose**: Batch processing wrapper that executes inner nodes over multiple items.

**Key Features**:
- Sequential and parallel execution modes
- Isolated item context (shallow copy of shared store per item)
- Deep copies node chain for parallel mode (thread safety)
- Per-item retry logic with configurable wait
- `fail_fast` or `continue` error handling modes

**Critical Behavior - LLM Cost Tracking**: Batch initializes `__llm_calls__` list in `prep()` and captures `llm_usage` from each item's isolated context via `_capture_item_llm_usage()`. This is called in `_exec_single` (sequential) OR `_exec_single_with_node` (parallel) - never both. Captures from both root (`item_shared["llm_usage"]`) and namespaced (`item_shared[node_id]["llm_usage"]`) locations. Without this, LLM costs would be lost when the item context is discarded.

### 3. Template System

#### 3.1 TemplateResolver (`template_resolver.py`)

**Purpose**: Core template resolution engine.

**Key Features**:
- **Path Support**: `${data.user.name}`, `${items[0].title}`
- **Type Preservation**: `${var}` preserves original type
- **Nested Resolution**: Handles templates in dicts/lists
- **Fallback**: Unresolved templates remain for debugging

**Resolution Priority**:
1. `initial_params` (from planner)
2. Shared store (runtime data)
3. Workflow inputs

#### 3.2 TemplateValidator (`template_validator.py`) (Enhanced in Task 71)

**Purpose**: Pre-execution validation of template variables with rich error suggestions.

**Key Features**:
- Validates all templates have sources
- Uses registry metadata for node outputs
- Detects unused declared inputs
- **Enhanced error messages** (Task 71 - lines 162-413):
  - `_flatten_output_structure()`: Recursively flattens nested outputs showing array access patterns
  - `_find_similar_paths()`: Substring matching for typo suggestions
  - `_format_enhanced_node_error()`: Multi-section errors with complete structure
  - Shows all available paths (limit 20) with types
  - "Did you mean X?" suggestions for typos
  - Actionable "Common fix: Change X to Y" guidance

**Error Format Example** (Task 71):
```
Node 'fetch-messages' (mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY)
does not have output 'msg'

Available outputs from this node:
  - result: dict
  - result.messages: array
  - result.messages[0]: dict
  - result.messages[0].text: string
  - result.messages[0].user: string
  ...

Did you mean one of these?
  - result.messages (array) - Contains message data

Common fix: Change ${fetch-messages.msg} to ${fetch-messages.result.messages}
```

### 4. WorkflowExecutor (`workflow_executor.py`)

**Purpose**: Runtime node for nested workflow execution.

**Key Features**:
- Loads workflows by name, path, or inline IR
- Parameter mapping with template resolution
- Storage isolation modes (mapped/isolated/scoped/shared)
- Circular dependency detection
- Registry propagation to sub-workflows

### 5. WorkflowTraceCollector (`workflow_trace.py`) (VERIFIED)

**Purpose**: Detailed execution trace collection with thread-safe LLM interception.

**Key Features**:
- **Thread-safe LLM interception**: Reference counting + thread-local collectors
- **Configurable limits**: 5 environment variables (`PFLOW_TRACE_*_MAX`)
- **Trace location**: `~/.pflow/debug/workflow-trace-*.json`
- **Format version**: `"1.2.0"` (updated for tri-state status support)
- **Multi-source prompt capture**: Interceptor → `__llm_calls__` → shared store
- **Repair tracking**: Attempt numbers, errors, workflow diffs
- **Mutation analysis**: Added/removed/modified keys tracking

### 6. Validation Utilities (`workflow_validator.py`)

**Purpose**: IR structure validation and input preparation.

**Key Functions**:
- `validate_ir_structure()` - Basic IR validation
- `prepare_inputs()` - Input validation with defaults

### 7. Output Resolver (`output_resolver.py`)

**Purpose**: Resolve workflow output declarations.

**Key Function**:
- `populate_declared_outputs()` - Map namespaced outputs to root level

## Critical Integration Points

### 1. Registry Integration

**Node Discovery**:
```python
# import_node_class() uses registry for all node lookups
nodes = registry.load()
node_metadata = nodes[node_type]
module_path = node_metadata["module"]
class_name = node_metadata["class_name"]
```

**Special Handling**:
- **Core nodes**: Standard Python imports
- **User nodes**: Direct file imports
- **MCP nodes**: Virtual nodes with server/tool injection
- **Workflow nodes**: Registry injected as parameter

### 2. Execution Module Integration

**Entry Point**: `executor_service.py` calls `compile_ir_to_flow()`

**Parameters Passed**:
- `workflow_ir` - The workflow to compile
- `registry` - Fresh instance per execution
- `initial_params` - Template resolution context
- `validate` - Template validation flag
- `metrics_collector` - Cost tracking
- `trace_collector` - Debugging traces

### 3. Planning System Integration

**Data Flow**:
```
Planner extracts parameters → initial_params
    ↓
Planner generates IR → workflow_ir
    ↓
compile_ir_to_flow(ir, params) → Flow object
    ↓
Template resolution at runtime using params
```

**Cache Chunks**: Planner context flows to repair via `__planner_cache_chunks__`

### 4. Core Module Integration

- **WorkflowManager**: Used by WorkflowExecutor for saved workflows
- **ValidationError**: From ir_schema.py for structured errors
- **validation_utils**: Shell-safe parameter validation

## Wrapper Chain Details (VERIFIED)

### Application Order

```python
# Lines 543-571, 671-689 in compiler.py
node = node_class()                              # 1. Base node
node = TemplateAwareNodeWrapper(node, ...)       # 2. Template resolution (conditional)
node = NamespacedNodeWrapper(node, ...)          # 3. Namespacing (if enabled)
node = PflowBatchNode(node, ...)                 # 4. Batch processing (if batch config)
node = InstrumentedNodeWrapper(node, ...)        # 5. Instrumentation (ALWAYS applied)
```

**Important**:
- Template wrapper only applied if params contain `${...}` templates
- Batch wrapper only applied if node has `batch` config in IR
- Batch wrapper MUST be outside namespace (injects item alias at root level)

### _run() Interception Chain

```
InstrumentedNodeWrapper._run()
  ├─ Check cache, setup callbacks
  └─ Call: inner_node._run()
       ↓
  PflowBatchNode._run() [if batch configured]
  ├─ For each item: create isolated context, execute inner node
  └─ Capture LLM usage from each item context before discarding
       ↓
  NamespacedNodeWrapper._run()
  └─ Call: inner_node._run(NamespacedSharedStore)
       ↓
  TemplateAwareNodeWrapper._run()
  ├─ Resolve templates (including ${item} from batch)
  └─ Call: inner_node._run()
       ↓
  ActualNode._run()
```

### set_params() Flow

```
InstrumentedNodeWrapper.set_params()
  └─> NamespacedNodeWrapper (delegates via __getattr__)
      └─> TemplateAwareNodeWrapper.set_params()
          ├─ Separates template/static params
          └─> ActualNode.set_params(static_only)
```

## Key Data Structures (VERIFIED)

### Special Reserved Keys (Updated in Task 71)

```python
# Execution tracking
shared["__execution__"] = {
    "completed_nodes": [],     # Successfully executed nodes
    "node_actions": {},       # Actions returned by each node
    "node_hashes": {},       # MD5 config hashes for cache validation
    "failed_node": None      # Node that caused workflow failure
}

# Other system keys
shared["__llm_calls__"] = []              # LLM usage tracking
shared["__progress_callback__"] = func    # Progress updates
shared["__non_repairable_error__"] = bool # Skip repair flag
shared["__warnings__"] = {}               # Node warnings (triggers DEGRADED status)
shared["__modified_nodes__"] = []         # Repair tracking
shared["__cache_hits__"] = []             # Cache hit tracking (Task 71)
shared["__template_errors__"] = {}        # Template/type errors in permissive mode (Task 85, Issue #100)
```

### Compilation Context

```python
{
    "workflow_ir": {...},              # JSON IR to compile (may include template_resolution_mode)
    "registry": Registry(),            # Node discovery
    "initial_params": {...},          # Template context (includes __template_resolution_mode__)
    "validate": True,                 # Template validation
    "metrics_collector": ...,         # Cost tracking
    "trace_collector": ...           # Debug traces
}
```

### Node Metadata (from Registry)

```python
{
    "module": "pflow.nodes.file.read_file",
    "class_name": "ReadFileNode",
    "type": "core",              # core/user/mcp
    "file_path": "/path/to/node.py",  # for user nodes
    "interface": {...}           # Input/output metadata
}
```

### Template Resolution Context

```python
{
    **initial_params,    # From planner (priority)
    **shared_store,      # Runtime data
    **workflow_inputs    # Declared inputs
}
```

## Critical Behaviors

### 1. Cache Invalidation

**When Cache Used**:
- Node in `completed_nodes`
- Configuration hash matches
- No error action returned

**When Cache Invalid**:
- Parameters changed (hash mismatch)
- Configuration drift detected

### 2. Error Categorization (VERIFIED)

**API Warning Detection**: 3-tier priority system with 73 validation + 20 resource patterns

**Repairable** (repair attempted):
- `validation_error` - Parameter format issues (73 patterns checked)
- `template_error` - Unresolved variables (triggers ValueError)

**Non-Repairable** (workflow stops):
- `resource_error` - Not found, forbidden (20 patterns)
- API warnings: Slack `"ok": false`, Discord errors, GraphQL `"errors": []`
- HTTP status codes: 401, 403, 404, 429

### 3. MCP Node Handling (VERIFIED)

- Node type format: `mcp-<server>-<tool>`
- Server names can contain dashes (uses greedy longest match algorithm)
- Parameters injected: `__mcp_server__`, `__mcp_tool__` (lines 488-489)
- Validation only when registry has real nodes (lines 271-299)
- Virtual path marker: `"virtual://mcp"` distinguishes from real files
- Error suggestions: 3-tier system (no tools → similar tools → available servers)

### 4. Template Resolution (VERIFIED)

- **Regex Pattern**: `r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[a-zA-Z_][\w-]*(?:\[[\d]+\])?)*)?)\}"`
- **Array Support**: `${items[0].name}`, `${data[5].users[2]}`
- **Simple templates** (`${var}`): Preserve original type (int, bool, None, dict, list)
- **Complex templates** (`"Hello ${name}"`): Always return strings
- **Type Conversion**: None→"", False→"False", True→"True", 0→"0", []→"[]", {}→"{}", dicts/lists→JSON serialized (double quotes, valid JSON)
- **Unresolved templates**: Remain for debugging visibility
- **Template errors**: Fatal ValueError triggers repair

## Performance Characteristics

### Compilation
- **Node Import**: Dynamic import overhead per unique node type
- **Wrapper Creation**: 3 wrapper objects per node
- **Validation**: O(n) with workflow size

### Runtime
- **Cache Lookup**: O(1) per node
- **MD5 Hashing**: ~1ms per node config
- **Template Resolution**: Depends on template complexity

### Memory
- **Wrapper Chain**: 3 additional objects per node
- **Checkpoint Data**: O(n) with completed nodes
- **Trace Data**: Can be large (configurable limits)

## Common Usage Patterns

### 1. Standard Compilation

```python
flow = compile_ir_to_flow(
    workflow_ir,
    registry=Registry(),
    initial_params={"repo": "pflow"},
    validate=True
)
result = flow.run(shared_store)
```

### 2. With Instrumentation

```python
flow = compile_ir_to_flow(
    workflow_ir,
    registry=Registry(),
    initial_params=params,
    metrics_collector=metrics,
    trace_collector=trace
)
```

### 3. Nested Workflow Execution

```python
# WorkflowExecutor handles this internally
params = {
    "workflow_name": "fix-issue",
    "param_mapping": {"issue": "${issue_number}"},
    "output_mapping": {"result": "fix_result"}
}
```

## Testing Considerations (VERIFIED)

### Key Mock Points
- `Registry.load()` - Node metadata (test nodes filtered by default)
- `importlib.import_module()` - Node imports (core vs user vs MCP)
- `importlib.util.spec_from_file_location()` - User node file imports
- `WorkflowManager` - Saved workflow loading
- `MCPServerManager.list_servers()` - MCP server discovery

### Node Type Testing
- **Core nodes**: Use real test nodes from `src/pflow/nodes/test_node*.py`
- **User nodes**: Mock file imports with `spec_from_file_location`
- **MCP nodes**: Mock with `"virtual://mcp"` file path
- **Test node filtering**: Enable with `PFLOW_INCLUDE_TEST_NODES=true`

### Critical Test Scenarios
1. Template resolution with array indices `${items[0].name}`
2. Cache invalidation via MD5 hash mismatch
3. API warning detection (73 validation + 20 resource patterns)
4. Circular workflow detection with execution stack
5. MCP server names with dashes (greedy longest match)
6. Wrapper chain attribute delegation (`inner_node` vs `_inner_node`)
7. Thread-safe LLM interception with reference counting

## AI Agent Guidance

### When Working in This Module

1. **Respect the Wrapper Chain**: Order matters - instrumentation must be outermost.

2. **Template Variables**: Always use `${variable}` syntax with curly braces.

3. **Error Categories**: Proper categorization determines repair strategy.

4. **Cache Integrity**: Never modify `__execution__` structure format.

5. **Registry Usage**: Always pass fresh Registry instance to compile_ir_to_flow().

6. **Special Parameters**: Don't use `__` prefixed parameter names (reserved).

### Common Pitfalls to Avoid

1. **Don't Skip Validation**: Set `validate=False` only for testing
2. **Don't Modify Cached Nodes**: Cache assumes immutability
3. **Don't Break Wrapper Chain**: Each wrapper expects specific inner behavior
4. **Don't Use Reserved Keys**: `__execution__`, `__llm_calls__`, etc.
5. **Don't Assume Node Types**: Always check registry for availability

### Integration Points to Remember

- **Execution**: Via compile_ir_to_flow() in executor_service
- **Planning**: initial_params from planner extraction
- **Registry**: Node discovery and metadata
- **Core**: ValidationError and utilities
- **Tracing**: Optional collectors for debugging

This module is the heart of pflow's compilation system, transforming static workflow definitions into dynamic, self-healing execution objects through sophisticated wrapping and validation.
