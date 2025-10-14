# CLAUDE.md - Execution Module Documentation

## Executive Summary

The `src/pflow/execution/` module is the **unified execution and repair system** for pflow workflows. It provides a clean abstraction layer between CLI/UI concerns and runtime execution, implementing self-healing workflows through checkpoint-based resume and LLM-powered repair.

**Core Innovation**: Resume-based repair that avoids duplicate execution by checkpointing successful nodes and resuming from failure points after repair.

## Module Architecture

```
┌─────────────────────────────────────────────┐
│              CLI/UI Layer                    │
│         (uses OutputInterface)               │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│         workflow_execution.py                │
│     THE unified execution function           │
│    (orchestrates validation→repair→resume)   │
└──────────────────┬──────────────────────────┘
                   │
    ┌──────────────┼──────────────┬───────────┐
    ▼              ▼              ▼           ▼
┌────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐
│Executor│ │ Display  │ │ Repair   │ │ Diff   │
│Service │ │ Manager  │ │ Service  │ │ Utils  │
└────────┘ └──────────┘ └──────────┘ └────────┘
    │
    ▼
Runtime Layer (compiler, validator, instrumentation)
```

## File Structure

```
src/pflow/execution/
├── __init__.py                 # Module exports (4 public classes)
├── CLAUDE.md                   # This file (AI agent documentation)
├── output_interface.py         # Protocol for display abstraction
├── display_manager.py          # UX logic encapsulation
├── executor_service.py         # Core execution service
├── workflow_execution.py       # Unified execution with repair orchestration
├── repair_service.py           # LLM-based workflow repair
├── null_output.py             # Silent output implementation
├── workflow_diff.py           # Workflow modification tracking
├── execution_state.py         # Execution state building (shared CLI/MCP)
└── formatters/                # Shared output formatters (Task 72)
    ├── error_formatter.py     # Error formatting (CLI/MCP parity)
    ├── success_formatter.py   # Success formatting
    ├── node_output_formatter.py
    ├── validation_formatter.py
    ├── workflow_save_formatter.py
    ├── workflow_describe_formatter.py
    └── ... (10 formatters total)
```

## Public API (via `__init__.py`)

- `OutputInterface` - Protocol for display implementations
- `DisplayManager` - UX logic for workflow execution display
- `ExecutionResult` - Dataclass for execution results
- `WorkflowExecutorService` - Core execution service

## Internal Functions (require direct import)

- `execute_workflow()` - Main execution function (from workflow_execution)
- `repair_workflow()` - LLM repair function (from repair_service)
- `repair_workflow_with_validation()` - Repair with validation loop (from repair_service)
- `compute_workflow_diff()` - Workflow comparison (from workflow_diff)

## Core Components

### 1. OutputInterface Protocol (`output_interface.py`)

**Purpose**: Abstract interface enabling different frontends (CLI, web, REPL) to provide their own display logic.

**Key Methods**:
- `show_progress(message, is_error)` - Progress messages
- `show_result(data)` - Final output data
- `show_error(title, details)` - Error display
- `show_success(message)` - Success messages
- `create_node_callback()` - Node execution progress tracking
- `is_interactive()` - Interactive mode detection

**Integration Point**: CLI implements this via `CliOutput` class in `cli/cli_output.py`

### 2. DisplayManager (`display_manager.py`)

**Purpose**: Encapsulates all UX logic for workflow execution display, using OutputInterface to remain backend-agnostic.

**Key Features**:
- Context-aware messages (execution vs repair vs resume)
- Node progress tracking with status indicators
- Repair progress display with issue details
- Delegates actual output to OutputInterface

**Usage Pattern**:
```python
display = DisplayManager(output=cli_output)
display.show_execution_start(node_count=5, context="resume")
display.show_node_progress(node_id="fetch", status="cached", duration=0.1)
```

### 3. WorkflowExecutorService (`executor_service.py`)

**Purpose**: Core execution service extracted from CLI (Task 68 Phase 1), handles all execution logic.

**Key Responsibilities**:
- Registry creation and management
- Workflow compilation via `compile_ir_to_flow()`
- Shared store initialization and lifecycle
- Error extraction and categorization
- Metadata updates via WorkflowManager
- Output data extraction strategies

**ExecutionResult Structure**:
```python
@dataclass
class ExecutionResult:
    success: bool
    shared_after: dict[str, Any]      # Final shared store state
    errors: list[dict[str, Any]]      # Structured error data
    action_result: Optional[str]       # Flow action (e.g., "error")
    node_count: int                    # Number of nodes executed
    duration: float                    # Total execution time
    output_data: Optional[str]         # Extracted output
    metrics_summary: Optional[dict]    # LLM usage metrics
    repaired_workflow_ir: Optional[dict]  # Repaired workflow if applicable
```

**Error Structure for Repair** (Enhanced in Task 71):
```python
{
    "source": "runtime",              # Where error originated
    "category": "api_validation",     # Error type for repair strategy
    "message": "Field 'title' required",  # Human-readable description
    "node_id": "create-issue",        # Which node failed
    "fixable": True,                  # Whether repair should attempt

    # Rich error data (extracted from shared store - Task 71)
    "status_code": 400,               # HTTP node: status code
    "raw_response": {...},            # HTTP node: full response body
    "response_headers": {...},        # HTTP node: response headers
    "response_time": 1.234,           # HTTP node: request duration
    "mcp_error_details": {...},       # MCP node: error details
    "mcp_error": {...},               # MCP node: result.error object
    "available_fields": [...]         # Template errors: available keys (max 20)
}
```

**Two-Layer Error Enhancement** (Task 71):
- **Data Layer** (executor_service.py lines 240-277): Extracts rich context from `shared_store[node_id]`
- **Display Layer** (cli/main.py): Formats errors for text/JSON output with context

### 4. Unified Execution Function (`workflow_execution.py`)

**Purpose**: THE execution function that orchestrates validation, execution, repair, and resume.

**Key Innovation**: Single `execute_workflow()` function where repair is just a boolean flag, not a separate code path.

**Default Execution Flow** (without `--auto-repair`):
1. **Upfront Validation**: Quick validation before execution
2. **Direct Execution**: Execute workflow immediately after validation
3. **Fail Fast**: Return error on first failure (no repair attempts)

**Execution Flow with Repair Enabled** (with `--auto-repair` flag):
1. **Validation Phase**: Validate workflow, repair if needed
2. **Execution Phase**: Execute workflow with checkpoint tracking
3. **Repair Loop**: On failure, repair and resume from checkpoint
4. **Result**: Return ExecutionResult with repaired workflow if applicable


**Critical Functions**:
- `_handle_validation_phase()` - Validation with repair attempts
- `_prepare_shared_store()` - Initialize/resume shared store
- `_execute_with_repair_loop()` - Runtime execution with repair
- `_attempt_repair()` - Individual repair attempt
- `_get_error_signature()` - Loop detection via error signatures
- `_normalize_error_message()` - Remove dynamic parts for comparison

**Checkpoint Resume Pattern**:
```python
# Checkpoint stored in shared store
shared["__execution__"] = {
    "completed_nodes": ["fetch", "analyze"],  # Successfully executed
    "node_actions": {                         # Actions returned
        "fetch": "default",
        "analyze": "default"
    },
    "node_hashes": {                          # Config hashes for validation
        "fetch": "a1b2c3d4...",
        "analyze": "e5f6g7h8..."
    },
    "failed_node": "send"                     # Where failure occurred
}

# Cache hit tracking (Task 71 - added in instrumented_wrapper.py lines 598-601)
shared["__cache_hits__"] = ["fetch", "analyze"]  # Nodes that used cache
```

### 5. Repair Service (`repair_service.py`)

**Purpose**: LLM-based workflow repair using Claude Sonnet 4.0 model with planner context.

**Key Features**:
- Uses `anthropic/claude-sonnet-4-0` model
- Leverages planner cache chunks for context continuity
- Validates repairs before returning
- Implements flow-centric repair philosophy

**Core Principle**: "The error occurred at one node, but the fix might be in a different node"

**Error Categories**:
- `api_validation` - Parameter format issues
- `template_error` - Unresolved template variables
- `execution_failure` - Runtime failures
- `static_validation` - Workflow structure issues

**Cache Integration**: Uses planner cache chunks from `execution_params["__planner_cache_chunks__"]` for context continuity with FlowIR schema.

### 6. Workflow Diff Utilities (`workflow_diff.py`)

**Purpose**: Track modifications between original and repaired workflows.

**Key Functions**:
- `compute_workflow_diff()` - Compare two workflow IRs
- Returns dict mapping `node_id` → list of changes
- Used for visual feedback showing `[repaired]` indicator

**Change Types Detected**:
- Parameter additions (e.g., `ignore_errors`)
- Command modifications
- Prompt updates
- Node additions/removals
- Type changes

### 7. Null Output (`null_output.py`)

**Purpose**: Silent output implementation for non-interactive execution.

**Usage**: Default when no OutputInterface provided to `execute_workflow()`.

## Critical Integration Points

### 1. CLI Integration

**Entry Point**: `cli/main.py` function `execute_json_workflow()` calls `execute_workflow()`

**Key Parameters Passed**:
- `workflow_ir`: The workflow to execute
- `execution_params`: Template parameters with special keys like `__planner_cache_chunks__`
- `enable_repair`: Controlled by `--auto-repair` flag (defaults to False)
- `output`: CliOutput instance implementing OutputInterface
- `workflow_manager`: For saved workflow metadata updates
- `stdin_data`: Piped input data
- `metrics_collector`: Tracks execution metrics
- `trace_collector`: Records execution trace

**CliOutput**: Implements OutputInterface using Click for terminal output

**MCP Server**: `mcp_server/services/execution_service.py` calls `execute_workflow()` with NullOutput for silent execution, uses shared formatters for parity

### 2. Runtime Integration

**Compiler**: WorkflowExecutorService calls `compile_ir_to_flow()` from `runtime/compiler.py`

**InstrumentedNodeWrapper** (`runtime/instrumented_wrapper.py`):
- Implements checkpoint tracking via `shared["__execution__"]`
- Validates cache using MD5 hash of node configuration
- Detects API warnings to prevent futile repair attempts
- Records node execution for tracing

**WorkflowValidator** (`core/workflow_validator.py`):
- Called during validation phase if repair enabled
- Returns list of validation error strings
- Validates: structure, data flow, templates, node types

### 3. Planner Cache Chunks Flow

**Data Flow Path**:
```
PlanningNode → shared["planner_extended_blocks"]
    ↓
CLI extracts with priority (accumulated > extended > base)
    ↓
enhanced_params["__planner_cache_chunks__"]
    ↓
RepairService uses as cache_blocks for LLM
```

**Benefits**:
- Context continuity between planning and repair
- Cache efficiency (10x faster, 0.1x cost)
- Better repair quality with full context

### 4. Registry and WorkflowManager

**Registry Usage**:
- Fresh instance per execution
- Node discovery and validation
- MCP node verification
- Propagated to nested workflows

**WorkflowManager Integration**:
- `update_metadata()` - Track execution history
- `update_ir()` - Save repaired workflows preserving metadata
- `load_ir()` - Load saved workflows by name

### 5. Tracing and Metrics

**Trace Flow**: CLI → execute_workflow → InstrumentedNodeWrapper → repair_service

**Trace Events Recorded**:
- Node execution (timing, shared store mutations)
- Repair attempts (errors, modifications)
- LLM calls (prompts, responses)

**Metrics Tracked**:
- Execution timing per phase
- LLM token usage and costs
- Cache performance

**Progress Display** (OutputController):
- ✓ success, ❌ error, ⚠️ warning, ↻ cached, [repaired] modified

## Key Data Structures

### Checkpoint Data (`shared["__execution__"]`)

```python
{
    "completed_nodes": ["node1", "node2"],     # Successfully executed nodes
    "node_actions": {                          # Action each node returned
        "node1": "default",
        "node2": "success"
    },
    "node_hashes": {                           # Configuration hashes
        "node1": "md5hash1",
        "node2": "md5hash2"
    },
    "failed_node": "node3"                     # Node that caused failure
}

# Cache tracking (Task 71)
shared["__cache_hits__"] = ["node1"]           # Nodes that hit cache
```

### Repair Control Flags

```python
shared["__non_repairable_error__"] = True     # Skip repair for API errors
shared["__warnings__"] = {"node": "msg"}      # API warning messages
shared["__modified_nodes__"] = ["node1"]      # Nodes modified by repair
```

### Error Structure for Repair (Enhanced in Task 71)

```python
{
    "source": "runtime",                       # Error origin
    "category": "template_error",              # Error classification
    "message": "Template ${data.field} not found",
    "node_id": "process",                      # Failed node
    "fixable": True,                           # Repair eligibility
    "repair_attempted": True,                  # Repair was tried
    "repair_reason": "Could not fix",          # Why repair failed

    # Rich context (Task 71 - extracted from shared store)
    "status_code": 400,                        # HTTP errors
    "raw_response": {...},                     # Full response body
    "mcp_error_details": {...},                # MCP error context
    "available_fields": ["result", "status"]   # Template error hints
}
```

## Critical Behaviors and Edge Cases

### 1. Cache Invalidation Logic

**When Cache is Used**:
- Node ID in `completed_nodes`
- Configuration hash matches stored hash
- No error action was returned

**When Cache is Invalidated**:
- Node parameters changed (hash mismatch)
- Previous execution returned error
- Manual invalidation requested

### 2. Loop Detection

**Error Signature Comparison**:
- Normalizes error messages (removes timestamps, IDs)
- Compares signatures between repair attempts
- Stops repair if same error persists

**Maximum Attempts Without Loop Detection**:
- Validation phase: up to 3 attempts (via `repair_workflow_with_validation`)
- Runtime phase: up to 3 runtime loops × 3 internal attempts = 9 attempts
- Loop detection reduces this to 1-2 attempts when same error repeats

### 3. API Warning Detection

**Non-Repairable Patterns** (skip repair):
- Slack/Discord: `"ok": false`
- Generic: `"success": false`
- GraphQL: `"errors": [...]`
- HTTP status codes in body

**Repair vs Warning Decision**:
- Validation errors → Always repair
- Template errors → Always repair
- API business errors → Warning only
- Resource errors → Warning only

### 4. Repair Save Behavior

**Default Behavior** (changed in Task 68):
- File workflows: Overwrite original with `.backup`
- Saved workflows: Update via `WorkflowManager.update_ir()`
- Planner workflows: Save as `workflow-repaired-TIMESTAMP.json`

**`--no-update` Flag**:
- File workflows: Create `.repaired.json`
- Saved workflows: Save to `~/.pflow/workflows/repaired/`

## Performance Characteristics

### Checkpoint System
- **MD5 Hashing**: Fast configuration change detection
- **Cache Hit**: Immediate return, no execution
- **Resume Speed**: O(1) lookup per node

### Repair System
- **Repair Latency**: 10-30s per attempt (Sonnet LLM)
- **Cache Chunks**: Reduces latency and cost through context reuse
- **Loop Detection**: Prevents up to 12 redundant attempts

### Memory Usage
- **Checkpoint Data**: O(n) with workflow size
- **Trace Data**: Can grow large, filtered for sensitive data

## Common Usage Patterns

### 1. Standard Execution with Auto-Repair

```python
result = execute_workflow(
    workflow_ir=workflow,
    execution_params=params,
    enable_repair=True  # Default
)
if result.repaired_workflow_ir:
    # Workflow was repaired and succeeded
    save_repaired_workflow(result.repaired_workflow_ir)
```

### 2. Resume from Checkpoint

```python
# Checkpoint data in shared_store
resume_state = previous_result.shared_after
result = execute_workflow(
    workflow_ir=repaired_workflow,
    execution_params=params,
    resume_state=resume_state  # Resume from checkpoint
)
```

### 3. Disable Repair for Debugging

```python
result = execute_workflow(
    workflow_ir=workflow,
    execution_params=params,
    enable_repair=False  # --auto-repair flag
)
# Fails immediately on first error
```

## Testing Considerations

### Key Test Boundaries
- **OutputInterface**: Mock for display testing
- **compile_ir_to_flow()**: Main mock point for execution tests
- **LLM calls**: Mock at model.prompt() level
- **Registry/WorkflowManager**: Mock for isolation

### Critical Test Scenarios
1. Successful execution (no repair needed)
2. Validation repair → success
3. Runtime repair → resume → success
4. Loop detection (same error twice)
5. API warning detection (skip repair)
6. Cache invalidation on parameter change
7. Checkpoint data persistence

## Future Extensions

This architecture enables:
- **Persistent checkpoints** across sessions
- **Partial execution** from specific nodes
- **Workflow debugging** with checkpoint inspection
- **Distributed execution** using checkpoints
- **Time-travel debugging** with multiple checkpoints

## AI Agent Guidance

### When Working in This Module

1. **Respect the Architecture**: Execution module is display-agnostic. Never import Click or add CLI concerns here.

2. **Maintain Checkpoint Integrity**: The `__execution__` structure is critical for resume. Always preserve it correctly.

3. **Error Categories Matter**: Proper error categorization determines repair strategy. Use existing categories.

4. **Cache Invalidation is Critical**: Nodes that fail must not be cached. Configuration changes must invalidate cache.

5. **Test Boundaries**: Mock at `compile_ir_to_flow()` for execution tests, not individual components.

6. **Repair Philosophy**: Remember repairs might need to fix upstream nodes, not just the failing node.

7. **Loop Detection is Essential**: Without it, repair can attempt 27 times. Always check error signatures.

### Common Pitfalls to Avoid

1. **Don't Cache Errors**: Never cache nodes that return "error" action
2. **Don't Skip Validation**: Validation phase enables repair, skipping it breaks repair
3. **Don't Modify Checkpoint During Resume**: Checkpoint is read-only during resume
4. **Don't Ignore API Warnings**: They indicate non-repairable business errors
5. **Don't Forget Modified Nodes**: Track all nodes changed during repair for UI feedback

### Integration Points to Remember

- **CLI**: Via OutputInterface and ExecutionResult
- **Runtime**: Via compile_ir_to_flow and InstrumentedNodeWrapper
- **Planner**: Via cache chunks in execution_params
- **Registry**: Fresh instance per execution
- **WorkflowManager**: For saved workflow operations
- **Tracing**: Via trace_collector parameter
- **Metrics**: Via metrics_collector parameter

This module is the heart of pflow's self-healing workflow system, transforming workflows from brittle scripts into resilient, self-correcting automation.

---

## Task 71 Enhancements (Agent Enablement)

### Rich Error Context Extraction

**Location**: `executor_service.py` lines 240-277

**Purpose**: Extract detailed error context from shared store for better repair and debugging.

**Data Extracted**:
- **HTTP nodes**: `status_code`, `raw_response`, `response_headers`, `response_time`
- **MCP nodes**: `mcp_error_details`, `mcp_error` (from result.error)
- **Template errors**: `available_fields` (first 20 keys from failed node output)

**Integration**: Extracted once in `_format_errors_for_result()`, available in:
- CLI error display (text mode)
- JSON output (structured errors)
- Repair service (better context for LLM)
- Trace files (complete debugging info)

### Cache Hit Tracking

**Location**: `instrumented_wrapper.py` lines 542-601

**Purpose**: Track which nodes used cached results for execution visibility.

**Implementation**:
```python
# Initialize in _initialize_execution_tracking
shared["__cache_hits__"] = []

# Record in _use_cached_result
shared["__cache_hits__"].append(self.node_id)
```

**Usage**:
- JSON output: `execution.steps[].cached` field
- CLI display: ↻ indicator for cached nodes
- Metrics: Cache performance tracking
- Debugging: Identify cache behavior

### Impact on Agent Workflows

**Before Task 71**:
- Generic error messages: "Node failed"
- No visibility into execution state
- No cache information
- Limited repair context

**After Task 71**:
- Rich error context: HTTP codes, response bodies, available fields
- Complete execution state: which nodes ran, which cached, which failed
- Repair-friendly errors: LLM gets full context for fixing issues
- JSON output: Agents can programmatically inspect execution

**AI Agent Benefits**:
1. **Intelligent Repair**: Access to full error context enables better repair decisions
2. **Execution Visibility**: Can see exactly what happened (completed/cached/failed)
3. **Performance Understanding**: Cache metrics show workflow efficiency
4. **Debugging Support**: Complete state for troubleshooting failed workflows

---

## Shared Formatters

**Location**: `formatters/` directory

**Pattern**: Formatters return strings or dicts, never print. Consumers handle display.

**Key Functions**:
- `format_execution_errors()` - Error formatting with sanitization (used by CLI JSON, MCP)
- `format_execution_success()` - Success results with metrics
- `build_execution_steps()` - Per-node execution state (in `execution_state.py`)

**MCP Usage**: Returns text/structured data matching CLI output modes for parity