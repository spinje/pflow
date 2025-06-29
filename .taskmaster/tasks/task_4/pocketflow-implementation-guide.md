# Task 4: IR-to-PocketFlow Compiler - PocketFlow Implementation Guide

**⚠️ ARCHITECTURAL DECISION UPDATE (2025-06-29)**: This guide represents Option B (PocketFlow-based implementation) which was NOT chosen. The actual implementation uses Option A (traditional function approach). This document is preserved for reference but should NOT be followed for implementation.

**ACTUAL APPROACH**: See the project-context.md file for the chosen traditional function implementation approach.

---

## Overview (DEPRECATED - NOT USED)
This task implements a compiler that transforms pflow's JSON IR format into executable PocketFlow objects. The compiler uses PocketFlow itself for orchestration, making it self-hosted and demonstrating the pattern's reliability.

## PocketFlow Architecture

### Flow Structure
```
LoadIR >> ParseJSON >> ValidateSchema >> ResolveNodes >> DynamicImport >> VerifyInheritance >> BuildFlow >> Success
   |          |              |                |                |                  |                |
   v          v              v                v                v                  v                v
FileError  JSONError   SchemaError    UnknownNode      ImportError      TypeError        BuildError
```

### Key Nodes

#### 1. LoadIRNode
```python
class LoadIRNode(Node):
    """Load IR file with automatic retry for transient failures"""
    def __init__(self):
        super().__init__(max_retries=3, wait=1)

    def exec(self, shared):
        ir_path = shared["ir_path"]
        try:
            with open(ir_path, 'r') as f:
                shared["ir_content"] = f.read()
            return "parse"
        except FileNotFoundError:
            shared["error"] = f"IR file not found: {ir_path}"
            return "file_error"

    def exec_fallback(self, shared, exc):
        shared["error"] = f"Failed to load IR after retries: {exc}"
        return "file_error"
```

#### 2. ValidateSchemaNode
```python
class ValidateSchemaNode(Node):
    """Validate IR against pflow schema"""
    def __init__(self, schema_validator):
        super().__init__()
        self.validator = schema_validator

    def exec(self, shared):
        ir_data = shared["ir_data"]
        validation_result = self.validator.validate(ir_data)

        if validation_result.is_valid:
            shared["validated_ir"] = ir_data
            return "resolve"
        else:
            shared["schema_errors"] = validation_result.errors
            return "schema_error"
```

#### 3. DynamicImportNode
```python
class DynamicImportNode(Node):
    """Import node classes with retry for race conditions"""
    def __init__(self, registry):
        super().__init__(max_retries=3, wait=2)
        self.registry = registry

    def exec(self, shared):
        nodes_to_import = shared["nodes_to_import"]
        imported_classes = {}

        for node_id, node_spec in nodes_to_import.items():
            node_type = node_spec["type"]
            metadata = self.registry.get_node(node_type)

            if not metadata:
                shared["missing_node"] = node_type
                return "unknown_node"

            # Dynamic import with automatic retry
            module = importlib.import_module(metadata.module_path)
            node_class = getattr(module, metadata.class_name)
            imported_classes[node_id] = node_class

        shared["imported_classes"] = imported_classes
        return "verify"
```

## Implementation Plan

### Phase 1: Core Compiler Flow
1. Create `src/pflow/flows/compiler/` directory structure
2. Implement base nodes (Load, Parse, Validate)
3. Set up error handling nodes
4. Create main compiler flow

### Phase 2: Dynamic Import System
1. Implement registry integration
2. Add dynamic import with retry logic
3. Create inheritance verification
4. Handle missing nodes gracefully

### Phase 3: Flow Construction
1. Implement node instantiation
2. Build edge connections
3. Handle action-based routing
4. Set flow start/end nodes

### Phase 4: Testing & Error Handling
1. Unit tests for each node
2. Integration tests for full compilation
3. Error path testing
4. Performance optimization

## Testing Strategy

### Unit Tests
```python
def test_dynamic_import_node_retry():
    """Test that import retries on transient failures"""
    mock_registry = Mock()
    node = DynamicImportNode(mock_registry, max_retries=3)

    # Simulate transient import failure
    with patch('importlib.import_module') as mock_import:
        mock_import.side_effect = [ImportError(), ImportError(), mock_module]

        result = node.exec({"nodes_to_import": {...}})

        assert mock_import.call_count == 3
        assert result == "verify"
```

### Integration Tests
```python
def test_full_compilation():
    """Test complete IR to PocketFlow compilation"""
    compiler = create_compiler_flow(schema, registry)

    result = compiler.run({
        "ir_path": "test_workflow.json"
    })

    assert "compiled_flow" in result
    assert isinstance(result["compiled_flow"], Flow)
```

## Error Handling Patterns

### Graceful Degradation
- File not found → Clear error message
- Invalid JSON → Show parse location
- Schema errors → List specific violations
- Unknown nodes → Suggest available nodes
- Import failures → Retry with backoff

### Error Aggregation
```python
class ErrorCollectorNode(Node):
    """Collect all errors for comprehensive reporting"""
    def exec(self, shared):
        errors = []

        if "schema_errors" in shared:
            errors.extend([
                f"Schema: {e}" for e in shared["schema_errors"]
            ])

        if "import_errors" in shared:
            errors.extend([
                f"Import: {e}" for e in shared["import_errors"]
            ])

        shared["all_errors"] = errors
        return "report"
```

## Benefits of PocketFlow Approach

1. **Automatic Retry**: Import failures handled gracefully
2. **Clear Flow**: Visual representation of compilation steps
3. **Testability**: Each step independently testable
4. **Error Recovery**: Multiple error paths with specific handlers
5. **State Tracking**: Shared store shows compilation progress

## Integration Points

- **Registry**: Node discovery and metadata
- **Schema Validator**: IR validation
- **Module Loader**: Dynamic imports
- **Error Reporter**: User-friendly error messages

## Performance Considerations

- Lazy loading of node classes
- Caching of imported modules
- Parallel validation where possible
- Minimal shared store overhead

## Future Extensions

1. **Parallel Compilation**: Import multiple nodes concurrently
2. **Incremental Compilation**: Only recompile changed nodes
3. **Compilation Cache**: Store compiled flows
4. **Hot Reload**: Update flows without restart
