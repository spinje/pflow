# CLAUDE.md - Core Module Documentation

This file provides guidance for understanding and working with the pflow core module, which contains foundational components for workflow validation, shell integration, and error handling.

## Module Overview

The `core` module is responsible for:
- **Workflow Validation**: Defining and validating the JSON schema for pflow's Intermediate Representation (IR)
- **Shell Integration**: Handling stdin/stdout operations for CLI pipe syntax support
- **Error Handling**: Providing a structured exception hierarchy for the entire pflow system
- **Public API**: Exposing core functionality through a clean interface

## Module Structure

```
src/pflow/core/
├── __init__.py          # Public API exports - aggregates functionality from all modules
├── exceptions.py        # Custom exception hierarchy for structured error handling
├── ir_schema.py         # JSON schema definition and validation for workflow IR
├── shell_integration.py # Unix pipe and stdin/stdout handling for CLI integration
└── CLAUDE.md           # This file
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

### 4. __init__.py - Public API

Aggregates and exposes the module's functionality:

**Exported from exceptions.py**:
- `PflowError`
- `WorkflowExecutionError`
- `CircularWorkflowReferenceError`

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
from pflow.core import WorkflowExecutionError

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

### Running Tests
```bash
# Run all core module tests
pytest tests/test_core/

# Run specific test file
pytest tests/test_core/test_ir_schema.py -v
```

## Integration Points

The core module is used throughout pflow:
- **CLI** (`cli/main.py`): Uses shell integration for pipe support
- **Compiler** (`runtime/compiler.py`): Validates IR before compilation
- **Planner** (`planning/`): Generates valid IR from natural language
- **Nodes**: Use exceptions for error reporting

## Design Decisions

1. **Dual-Mode Stdin**: Supports both workflow JSON and data input via stdin
2. **Memory-Aware**: Handles large inputs without exhausting memory
3. **Helpful Errors**: ValidationError includes paths and fix suggestions
4. **Clean API**: __init__.py provides single import point for consumers
5. **Type Annotations**: Full type hints for better IDE support

## Best Practices

1. **Always validate early**: Validate IR as soon as it's loaded or generated to catch errors before execution
2. **Use helpful error messages**: Include suggestions for fixing common mistakes in ValidationError
3. **Test edge cases**: Ensure validation catches all invalid states (missing fields, wrong types, bad references)
4. **Keep examples updated**: Examples serve as both documentation and tests - maintain them carefully
5. **Building MVP**: We do not need to worry about backward compatibility for now, no migrations are needed since we dont have any users yet.
6. **Handle stdin modes explicitly**: Always check if stdin contains workflow JSON or data before processing
7. **Preserve error context**: Use WorkflowExecutionError to maintain the full error chain and workflow path

## Related Documentation

- **Shell Pipes**: `docs/features/shell-pipes.md` - Unix pipe integration details
- **Schemas**: `docs/core-concepts/schemas.md` - Conceptual schema overview
- **Examples**: `examples/` - Valid and invalid workflow examples
- **Runtime**: `src/pflow/runtime/compiler.py` - How validation fits execution

Remember: This module provides the foundation for pflow's reliability and CLI-first design. Changes here affect the entire system, so verify thoroughly against existing tests and usage patterns.
