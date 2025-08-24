# CLAUDE.md - Core Module Documentation

This file provides guidance for understanding and working with the pflow core module, which contains foundational components for workflow validation, shell integration, error handling, and workflow management.

## Module Overview

The `core` module is responsible for:
- **Workflow Management**: Centralized lifecycle management (save/load/list/delete) with format bridging
- **Workflow Validation**: Defining and validating the JSON schema for pflow's Intermediate Representation (IR)
- **Shell Integration**: Handling stdin/stdout operations for CLI pipe syntax support
- **Error Handling**: Providing a structured exception hierarchy for the entire pflow system
- **Public API**: Exposing core functionality through a clean interface

## Module Structure

```
src/pflow/core/
├── __init__.py              # Public API exports - aggregates functionality from all modules
├── exceptions.py            # Custom exception hierarchy for structured error handling
├── ir_schema.py             # JSON schema definition and validation for workflow IR
├── shell_integration.py     # Unix pipe and stdin/stdout handling for CLI integration
├── workflow_manager.py      # Workflow lifecycle management with format transformation
├── workflow_validator.py    # Unified workflow validation orchestrator (NEW)
├── workflow_data_flow.py    # Data flow and execution order validation (NEW)
└── CLAUDE.md               # This file
```

## Key Components

### 1. exceptions.py - Error Handling Infrastructure

Defines the exception hierarchy used throughout pflow:

**Exception Classes**:
- **`PflowError`**: Base exception for all pflow-specific errors
- **`WorkflowExecutionError`**: Tracks execution failures with workflow path chain
  - Preserves original error details
  - Shows execution hierarchy (e.g., "main.json → sub-workflow.json → failing-node")
- **`CircularWorkflowReferenceError`**: Detects and reports circular workflow references
- **`WorkflowExistsError`**: Raised when attempting to save a workflow with existing name
- **`WorkflowNotFoundError`**: Raised when requested workflow doesn't exist
- **`WorkflowValidationError`**: Raised when workflow structure or name is invalid

**Usage Pattern**:
```python
raise WorkflowExecutionError(
    "Node execution failed",
    workflow_path="workflows/data-pipeline.json",
    original_error=original_exception
)
```

### 2. ir_schema.py - Workflow Definition and Validation

The heart of workflow representation in pflow:

**Core Components**:
- **`FLOW_IR_SCHEMA`**: JSON Schema (Draft 7) enforcing workflow structure
- **`ValidationError`**: Custom exception with helpful error messages and suggestions
- **`validate_ir()`**: Main validation function supporting dict or JSON string input

**Schema Structure**:
```python
{
    "ir_version": "0.1.0",      # Required - semantic versioning
    "nodes": [...],             # Required - at least one node
    "edges": [...],             # Optional - defines connections
    "start_node": "node-id",    # Optional - defaults to first node
    "mappings": {...},          # Optional - proxy mappings
    "inputs": {...},            # Optional - workflow input declarations
    "outputs": {...}            # Optional - workflow output declarations
}
```

**Node Structure**:
```python
{
    "id": "unique-id",          # Required - unique within flow
    "type": "node-type",        # Required - references registry
    "params": {...}             # Optional - node configuration
}
```

**Input/Output Declarations** (for workflows):
```python
"inputs": {
    "api_key": {
        "type": "string",
        "description": "API authentication key",
        "required": true
    }
}
```

**Validation Features**:
- JSON Schema structural validation
- Business logic checks (node reference integrity, duplicate ID detection)
- Helpful error messages with fix suggestions
- Path-specific error reporting (e.g., "nodes[2].type is required")

### 3. shell_integration.py - CLI and Unix Pipe Support

Enables pflow to work seamlessly in Unix pipelines:

**Key Classes**:
- **`StdinData`**: Container for different stdin content types
  - `text_data`: UTF-8 text (under memory limit)
  - `binary_data`: Binary content (under memory limit)
  - `temp_path`: Path to temp file (for large content)

**Core Functions**:
- **`detect_stdin()`**: Checks if stdin is piped (not TTY)
- **`determine_stdin_mode()`**: Identifies stdin content (workflow JSON vs data)
- **`read_stdin_enhanced()`**: Reads stdin with binary/size handling
- **`populate_shared_store()`**: Adds stdin content to workflow shared store

**Memory Management**:
- Default limit: 10MB (configurable via `PFLOW_STDIN_MEMORY_LIMIT`)
- Automatic temp file creation for large inputs
- Binary detection using null byte sampling

**Dual-Mode Operation**:
```bash
# Mode 1: Workflow from stdin
echo '{"ir_version": "0.1.0", ...}' | pflow run

# Mode 2: Data from stdin (workflow from file)
cat data.txt | pflow run workflow.json
```

### 4. workflow_manager.py - Workflow Lifecycle Management

Centralizes all workflow operations and bridges the format gap between components:

**Key Features**:
- **Format Bridging**: Handles transformation between metadata wrapper and raw IR
- **Atomic Operations**: Thread-safe file operations prevent race conditions
- **Name-Based References**: Workflows referenced by kebab-case names (e.g., "fix-issue")
- **Storage Location**: `~/.pflow/workflows/*.json`

**Core Methods**:
- **`save(name, workflow_ir, description)`**: Wraps IR in metadata, saves atomically
- **`load(name)`**: Returns full metadata wrapper (for Context Builder)
- **`load_ir(name)`**: Returns just the IR (for WorkflowExecutor)
- **`list_all()`**: Lists all saved workflows with metadata
- **`exists(name)`**: Checks if workflow exists
- **`delete(name)`**: Removes workflow
- **`get_path(name)`**: Returns absolute file path

**Storage Format**:
```json
{
  "name": "fix-issue",
  "description": "Fixes GitHub issues",
  "ir": { /* actual workflow IR */ },
  "created_at": "2025-01-29T10:00:00+00:00",
  "updated_at": "2025-01-29T10:00:00+00:00",
  "version": "1.0.0"
}
```

### 5. workflow_validator.py - Unified Validation System (NEW)

Provides a single source of truth for all workflow validation:

**Key Class**:
- **`WorkflowValidator`**: Orchestrates all validation checks

**Core Method**:
```python
@staticmethod
def validate(
    workflow_ir: dict[str, Any],
    extracted_params: Optional[dict[str, Any]] = None,
    registry: Optional[Registry] = None,
    skip_node_types: bool = False
) -> list[str]
```

**Validation Types**:
1. **Structural validation**: IR schema compliance (via `validate_ir`)
2. **Data flow validation**: Execution order and dependencies (via `workflow_data_flow`)
3. **Template validation**: Variable resolution (via `TemplateValidator`)
4. **Node type validation**: Registry verification

**Critical Design Decision**: This replaces scattered validation logic that existed in multiple places (ValidatorNode, tests) with a unified system. Previously, tests had data flow validation that production lacked!

### 6. workflow_data_flow.py - Execution Order Validation (NEW)

Ensures workflows will execute correctly at runtime:

**Key Functions**:
- **`build_execution_order(workflow_ir)`**: Creates topological sort of nodes
- **`validate_data_flow(workflow_ir)`**: Validates all data dependencies

**What It Catches**:
- Forward references (node referencing future node's output)
- Circular dependencies
- References to non-existent nodes
- Undefined input parameters

**Critical Addition**: This validation was previously only in tests, not production. This could lead to workflows passing validation but failing at runtime.

**Algorithm**: Uses Kahn's algorithm for topological sort to determine valid execution order.

### 7. __init__.py - Public API

Aggregates and exposes the module's functionality:

**Exported from exceptions.py**:
- `PflowError`
- `WorkflowExecutionError`
- `CircularWorkflowReferenceError`
- `WorkflowExistsError`
- `WorkflowNotFoundError`
- `WorkflowValidationError`

**Exported from ir_schema.py**:
- `FLOW_IR_SCHEMA`
- `ValidationError`
- `validate_ir`

**Exported from shell_integration.py**:
- `StdinData`
- `detect_stdin`
- `determine_stdin_mode`
- `read_stdin`
- `read_stdin_enhanced`
- `populate_shared_store`

**Exported from workflow_manager.py**:
- `WorkflowManager`

**Exported from workflow_validator.py**:
- `WorkflowValidator`

**Exported from workflow_data_flow.py**:
- `CycleError`
- `build_execution_order`
- `validate_data_flow`

## Connection to Examples

The `examples/` directory contains real-world usage of the IR schema:

### Valid Examples (tested by test_ir_examples.py)
- **`examples/core/minimal.json`** - Demonstrates minimum requirements (single node workflow)
- **`examples/core/simple-pipeline.json`** - Shows basic edge connections (read → copy → write)
- **`examples/core/template-variables.json`** - Uses `$variable` substitution throughout workflow
- **`examples/core/error-handling.json`** - Action-based routing with error and retry paths
- **`examples/core/proxy-mappings.json`** - Interface adaptation using mappings section

### Invalid Examples (demonstrate validation errors)
- **`examples/invalid/missing-version.json`** - Missing required ir_version field
- **`examples/invalid/bad-edge-ref.json`** - Edge references non-existent node
- **`examples/invalid/duplicate-ids.json`** - Duplicate node ID enforcement
- **`examples/invalid/wrong-types.json`** - Type validation (string vs array vs object)

## Common Usage Patterns

### Managing Workflow Lifecycle
```python
from pflow.core import WorkflowManager, WorkflowExistsError

workflow_manager = WorkflowManager()

# Save a workflow
try:
    path = workflow_manager.save("data-pipeline", workflow_ir, "Processes daily data")
    print(f"Saved to: {path}")
except WorkflowExistsError:
    print("Workflow already exists!")

# Load for different purposes
metadata = workflow_manager.load("data-pipeline")  # Full metadata for display
workflow_ir = workflow_manager.load_ir("data-pipeline")  # Just IR for execution

# List all workflows
for wf in workflow_manager.list_all():
    print(f"{wf['name']}: {wf['description']}")
```

### Validating Workflow IR
```python
from pflow.core import validate_ir, ValidationError

try:
    validated_ir = validate_ir(workflow_dict)
except ValidationError as e:
    print(f"Validation failed: {e}")
    # Error includes path and suggestions
```

### Handling Stdin in CLI
```python
from pflow.core import detect_stdin, read_stdin_enhanced

if detect_stdin():
    stdin_data = read_stdin_enhanced()
    if stdin_data.text_data:
        # Handle text input
    elif stdin_data.binary_data:
        # Handle binary input
    elif stdin_data.temp_path:
        # Handle large file
```

### Structured Error Handling
```python
from pflow.core import WorkflowExecutionError, WorkflowNotFoundError

try:
    workflow_ir = workflow_manager.load_ir("missing-workflow")
except WorkflowNotFoundError as e:
    print(f"Workflow not found: {e}")

try:
    # Execute workflow
except Exception as e:
    raise WorkflowExecutionError(
        "Failed to execute node",
        workflow_path=current_workflow_path,
        original_error=e
    )
```

## Extending the Schema

When adding new features to the IR format:

1. **Update ir_schema.py**:
   - Add new fields to FLOW_IR_SCHEMA
   - Mark new fields as optional for backward compatibility
   - Add validation logic if needed beyond JSON schema

2. **Update Documentation**:
   - Update `docs/core-concepts/schemas.md` with new fields
   - Add examples showing the new feature
   - Update version compatibility notes

3. **Add Tests**:
   - Add test cases to `tests/test_core/test_ir_schema.py`
   - Create example files demonstrating the feature
   - Test both valid and invalid usage

## Testing

Each component has comprehensive test coverage:
- `tests/test_core/test_exceptions.py` - Exception behavior and formatting
- `tests/test_core/test_ir_schema.py` - Schema validation edge cases
- `tests/test_core/test_shell_integration.py` - Stdin handling scenarios
- `tests/test_core/test_ir_examples.py` - Real-world example validation
- `tests/test_core/test_workflow_validator.py` - Unified validation system tests
- `tests/test_core/test_workflow_data_flow.py` - Execution order and dependency validation

### Running Tests
```bash
# Run all core module tests
pytest tests/test_core/

# Run specific test file
pytest tests/test_core/test_ir_schema.py -v
```

## Integration Points

The core module is used throughout pflow:
- **CLI** (`cli/main.py`):
  - Uses shell integration for pipe support
  - Uses WorkflowManager for saving workflows after execution
  - Handles workflow exceptions during execution
- **Compiler** (`runtime/compiler.py`): Validates IR before compilation
- **Context Builder** (`planning/context_builder.py`): Uses WorkflowManager.list_all() for workflow discovery
- **WorkflowExecutor** (`runtime/workflow_executor.py`): Uses WorkflowManager.load_ir() for name-based workflow loading
- **ValidatorNode** (`planning/nodes.py`): Now uses WorkflowValidator for all validation
- **Tests** (`tests/test_planning/llm/prompts/`): Now use WorkflowValidator for production-consistent validation
- **Planner** (`planning/`): Will generate valid IR and use WorkflowManager to save workflows
- **Nodes**: Use exceptions for error reporting

## Design Decisions

1. **Dual-Mode Stdin**: Supports both workflow JSON and data input via stdin
2. **Memory-Aware**: Handles large inputs without exhausting memory
3. **Helpful Errors**: ValidationError includes paths and fix suggestions
4. **Clean API**: __init__.py provides single import point for consumers
5. **Type Annotations**: Full type hints for better IDE support
6. **Format Bridging**: WorkflowManager handles metadata wrapper vs raw IR transformation transparently
7. **Atomic Operations**: WorkflowManager uses atomic file operations to prevent race conditions
8. **Kebab-Case Names**: Workflow names use kebab-case for CLI friendliness (e.g., "fix-issue")
9. **Unified Validation**: WorkflowValidator provides single source of truth for all validation, eliminating duplication and ensuring consistency between production and tests
10. **Data Flow Validation**: Critical addition that ensures workflows will execute correctly at runtime by validating execution order and dependencies

## Best Practices

1. **Always validate early**: Validate IR as soon as it's loaded or generated to catch errors before execution
2. **Use helpful error messages**: Include suggestions for fixing common mistakes in ValidationError
3. **Test edge cases**: Ensure validation catches all invalid states (missing fields, wrong types, bad references)
4. **Keep examples updated**: Examples serve as both documentation and tests - maintain them carefully
5. **Building MVP**: We do not need to worry about backward compatibility for now, no migrations are needed since we dont have any users yet.
6. **Handle stdin modes explicitly**: Always check if stdin contains workflow JSON or data before processing
7. **Preserve error context**: Use WorkflowExecutionError to maintain the full error chain and workflow path
8. **Use WorkflowManager for all workflow operations**: Don't implement custom file loading/saving for workflows
9. **Test concurrent access**: Always test with real threads when dealing with file operations
10. **Handle format differences**: Use load() for metadata needs, load_ir() for execution needs

## Related Documentation

- **Shell Pipes**: `docs/features/shell-pipes.md` - Unix pipe integration details
- **Schemas**: `docs/core-concepts/schemas.md` - Conceptual schema overview
- **Examples**: `examples/` - Valid and invalid workflow examples
- **Runtime**: `src/pflow/runtime/compiler.py` - How validation fits execution
- **Task 24 Review**: `.taskmaster/tasks/task_24/task-review.md` - Comprehensive WorkflowManager implementation details
- **Workflow Management**: All workflow lifecycle operations should use WorkflowManager

## Key Lessons from Task 24

1. **The Race Condition Discovery**: Initial tests were too shallow. Only when proper concurrent tests were written was a critical race condition discovered in WorkflowManager.save(). This was fixed using atomic file operations with os.link().

2. **Format Bridging is Critical**: The system has a fundamental format mismatch - Context Builder expects metadata wrapper while WorkflowExecutor expects raw IR. WorkflowManager transparently handles this transformation.

3. **Test Quality Matters**: Always write real tests with actual threading, file I/O, and error conditions. Mocking too much can hide real bugs.

Remember: This module provides the foundation for pflow's reliability and CLI-first design. Changes here affect the entire system, so verify thoroughly against existing tests and usage patterns.
