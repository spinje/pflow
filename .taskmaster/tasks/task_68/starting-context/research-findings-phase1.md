# Task 68 Phase 1: Research Findings

## Executive Summary

Phase 1 of Task 68 requires extracting ~500 lines of execution logic from the CLI into reusable services while maintaining 100% backward compatibility. The research reveals complex interdependencies, inconsistent parameter signatures that must be preserved, and critical testing boundaries that cannot be broken.

## 1. Current CLI Execution Architecture

### Core Execution Flow (`execute_json_workflow`)
The function at lines 1391-1462 orchestrates workflow execution through these steps:

1. **Validation**: `_validate_and_load_registry()` - Validates IR and loads Registry
2. **Setup**: `_setup_workflow_collectors()` - Creates metrics/trace collectors
3. **Compilation**: `_compile_workflow_with_error_handling()` - Compiles IR to Flow
4. **Preparation**: `_prepare_shared_storage()` - Populates shared store
5. **Execution**: `_execute_workflow_and_handle_result()` - Runs workflow
6. **Cleanup**: `_cleanup_workflow_resources()` - Cleans up resources

### Critical Intermediate Function
`_execute_workflow_and_handle_result()` is a routing function that MUST be preserved:
- Routes to `_handle_workflow_success()` on success
- Routes to `_handle_workflow_error()` on error result
- Separates execution from result handling
- Has specific parameter passing patterns

### Handler Function Signatures (MUST PRESERVE EXACT ORDER)

```python
# Success handler - 8 parameters
def _handle_workflow_success(
    ctx: click.Context,
    workflow_trace: Any | None,
    shared_storage: dict[str, Any],
    output_key: str | None,
    ir_data: dict[str, Any],
    output_format: str,
    metrics_collector: Any | None,
    verbose: bool,
)

# Error handler - 6 parameters (different order!)
def _handle_workflow_error(
    ctx: click.Context,
    workflow_trace: Any | None,
    output_format: str,  # Note: different position than success
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],  # Note: different position
    verbose: bool,
)

# Exception handler - 7 parameters
def _handle_workflow_exception(
    ctx: click.Context,
    e: Exception,  # Additional parameter
    workflow_trace: Any | None,
    output_format: str,
    metrics_collector: Any | None,
    shared_storage: dict[str, Any],
    verbose: bool,
)
```

## 2. Dependencies and Interfaces

### OutputController
- **Location**: `src/pflow/core/output_controller.py`
- **Interactive Detection**: Based on 5 rules (print_flag, format, TTYs)
- **Progress Callback**: Returns callable for node progress tracking
- **Thread Safety**: Stateless, safe for concurrent use
- **Extension Needed**: Add support for "node_cached" event

### Registry
- **Auto-discovery**: First use triggers core node discovery
- **Caching**: Loads cached in `_cached_nodes`
- **Error Handling**: Returns empty dict with warnings (no exceptions)
- **validate_ir()**: Separate function in `ir_schema.py`

### MetricsCollector
- **Tracking**: Start/end times, node durations, LLM calls
- **Storage**: LLM calls in `shared["__llm_calls__"]`
- **Summary Format**: Complex nested structure with costs, tokens, durations

### Compilation Boundary
```python
def compile_ir_to_flow(
    ir_json: Union[str, dict[str, Any]],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
    validate: bool = True,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
) -> Flow
```
**Critical**: This is the primary test mocking boundary - signature CANNOT change

## 3. Testing Infrastructure Requirements

### Mock Patterns
- **Primary Mock**: `compile_ir_to_flow` - Tests mock this extensively
- **Mock Storage**: `mock._last_ir` stores IR for test inspection
- **Return Type**: Must be Flow with `.run(shared_storage)` method

### Output Testing
- **Text Format**: Plain text to stdout, warnings to stderr
- **JSON Format**: Specific field structure (success, result, workflow, metrics)
- **Exit Codes**: 0 for success, 1 for all errors

### Integration Tests
- Direct function calls bypass CLI mocking
- Real Registry and node implementations
- WorkflowExecutor interface expectations

## 4. WorkflowManager Requirements

### Current Implementation
- **Storage**: `~/.pflow/workflows/*.json` with metadata wrapper
- **Atomicity**: Uses `os.link()` for creation, temp files for updates
- **Format**: Metadata wrapper contains IR plus metadata fields

### update_metadata() Implementation Needs
- **Atomic Updates**: Use `os.replace()` with temp files
- **Special Handling**: `execution_count` increment, `updated_at` auto-update
- **Rich Metadata**: Create if missing, merge updates
- **Concurrency**: File-system level atomicity (no app locks needed)

## 5. Extraction Strategy

### What Goes Into WorkflowExecutorService
1. **Registry Loading**: Validation and loading logic
2. **Compilation**: Error handling and Flow creation
3. **Shared Store Prep**: Parameter injection, stdin handling
4. **Execution**: Flow.run() and result capture
5. **Metrics**: Start/end recording, LLM call tracking
6. **Output Extraction**: Finding output in shared store

### What Stays in CLI
1. **Click Integration**: Context, echo, exit handling
2. **Display Logic**: Verbose messages, progress display
3. **Handler Routing**: The intermediate function and handlers
4. **User Prompts**: Save workflow prompts
5. **Format Decisions**: JSON vs text output formatting

### Critical Preservation Points
1. **Handler Signatures**: EXACT parameter order must be maintained
2. **Intermediate Function**: `_execute_workflow_and_handle_result` structure
3. **Mock Interface**: `compile_ir_to_flow` signature and behavior
4. **Output Formats**: JSON structure, text patterns, exit codes
5. **System Keys**: `__double_underscore__` pattern in shared store

## 6. Implementation Risks

### Risk 1: Breaking Handler Compatibility
- **Issue**: Changing parameter order breaks existing code
- **Mitigation**: Document and preserve exact signatures

### Risk 2: Test Boundary Violations
- **Issue**: Changing `compile_ir_to_flow` breaks test mocks
- **Mitigation**: Keep interface exactly the same

### Risk 3: Output Format Changes
- **Issue**: JSON/text format changes break consumers
- **Mitigation**: Preserve exact output structure

### Risk 4: Interactive Mode Detection
- **Issue**: Changes affect progress display
- **Mitigation**: Keep OutputController logic intact

## 7. Phase 1 Deliverables

### New Files to Create
1. `src/pflow/execution/__init__.py`
2. `src/pflow/execution/output_interface.py` - Protocol definition
3. `src/pflow/execution/cli_output.py` - Click implementation
4. `src/pflow/execution/display_manager.py` - UX logic
5. `src/pflow/execution/executor_service.py` - Core execution

### Files to Modify
1. `src/pflow/cli/main.py` - Extract to thin wrapper
2. `src/pflow/core/workflow_manager.py` - Add update_metadata()

### Test Strategy
- Run all existing tests without modification
- Verify identical output in all formats
- Check exit codes match exactly
- Ensure mocks still work

## 8. Key Design Decisions

### Thin CLI Pattern
- CLI reduced from ~2000 to ~200 lines
- Only command parsing and exit handling remain
- All logic moves to services

### Display Abstraction
- OutputInterface protocol for Click-independence
- DisplayManager encapsulates UX patterns
- Enables future REPL/API interfaces

### Service Design
- ExecutionResult dataclass for structured returns
- Clean separation of concerns
- No Click dependencies in services

## 9. Success Criteria

1. **No Breaking Changes**: All existing workflows execute identically
2. **Test Compatibility**: All tests pass without modification
3. **Clean Architecture**: Clear separation between CLI and services
4. **Reusability**: Services usable outside CLI context
5. **Performance**: No measurable slowdown

## Conclusion

The research reveals a complex but achievable refactoring. The key challenges are:
1. Preserving inconsistent handler signatures
2. Maintaining test mock boundaries
3. Extracting logic while keeping exact output formats

The proposed architecture cleanly separates concerns while maintaining 100% compatibility. The thin CLI pattern enables future interfaces while the service layer provides reusable execution logic.