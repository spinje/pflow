# CLI and Compiler Integration for Task 3

## CLI --file Flag Requirement
Task 3 requires "Adding a basic 'pflow --file <file.json>' command to the CLI".

### Current CLI Structure (from Task 2)
- CLI is in `src/pflow/cli/main.py`
- Uses click framework
- Has a 'run' subcommand that collects arguments

### Adding --file Option
The --file option should:
1. Load JSON from the specified file
2. Pass it to the IR compiler
3. Execute the resulting flow

## Compiler Integration (from Task 4)
The compiler is in `src/pflow/runtime/compiler.py` with function:
```python
compile_ir_to_flow(ir_json, registry)
```

Key points:
- Takes IR JSON (dict or string) and registry
- Returns executable pocketflow.Flow object
- Uses dynamic imports to load node classes
- Validates nodes inherit from pocketflow.BaseNode

## Execution Flow for Task 3
1. CLI loads JSON file
2. Pass to `validate_ir()` from `pflow.core`
3. Get registry from Task 5 (`pflow.registry.Registry`)
4. Call `compile_ir_to_flow(ir_json, registry)`
5. Initialize shared store: `shared = {}`
6. Run flow: `flow.run(shared)`

## Node Requirements (from Task 11)
- Nodes must inherit from `pocketflow.BaseNode`
- Use natural interface pattern:
  - read-file: `shared['file_path']` → `shared['content']`
  - write-file: `shared['content']` + `shared['file_path']`

## Error Handling
From compiler details:
- Handle missing nodes in registry
- Handle import failures
- Provide clear error messages
