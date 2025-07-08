# Implementation Plan for 4.3

## Objective
Implement flow construction by instantiating nodes from registry, setting parameters, wiring with PocketFlow operators, and creating an executable Flow object.

## Implementation Steps
1. [ ] Create `_instantiate_nodes()` helper function
   - File: src/pflow/runtime/compiler.py
   - Change: Add function to instantiate nodes from IR
   - Test: Verify node instantiation, parameter setting

2. [ ] Create `_wire_nodes()` helper function
   - File: src/pflow/runtime/compiler.py
   - Change: Add function to connect nodes using edges
   - Test: Verify >> and - operators work correctly

3. [ ] Create `_get_start_node()` helper function
   - File: src/pflow/runtime/compiler.py
   - Change: Add function to identify start node
   - Test: Verify start node detection logic

4. [ ] Update `compile_ir_to_flow()` to orchestrate
   - File: src/pflow/runtime/compiler.py
   - Change: Replace NotImplementedError with actual compilation
   - Test: Verify end-to-end flow creation

5. [ ] Create comprehensive test suite
   - File: tests/test_flow_construction.py
   - Change: Add unit tests for all functions
   - Test: Run pytest to verify all tests pass

6. [ ] Run quality checks
   - File: N/A
   - Change: Run `make test` and `make check`
   - Test: Ensure all checks pass

## Pattern Applications

### Cookbook Patterns
- **pocketflow-flow basic pattern**: Direct node instantiation and >> operator usage
  - Specific code/approach: `node_a >> node_b` for default connections
  - Modifications needed: None, direct application

- **pocketflow-agent action routing**: Using - operator for conditional paths
  - Specific code/approach: `node - "action" >> target` for action-based routing
  - Modifications needed: None, direct application

- **pocketflow-batch-flow params**: Parameter setting via set_params()
  - Specific code/approach: `node.set_params(params)` after instantiation
  - Modifications needed: None, direct application

### Previous Task Patterns
- Using CompilationError from Task 4.1 for rich error context
- Using import_node_class from Task 4.2 for dynamic imports
- Avoiding logging reserved field names from Task 4.2

## Risk Mitigations
- **Risk**: Circular references in edges
  - **Mitigation**: Not a problem - PocketFlow supports loops naturally

- **Risk**: Missing node references in edges
  - **Mitigation**: Clear CompilationError with available nodes listed

- **Risk**: Template variable resolution
  - **Mitigation**: Pass through unchanged, no processing needed
