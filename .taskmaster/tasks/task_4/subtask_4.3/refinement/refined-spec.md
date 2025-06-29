# Refined Specification for 4.3

## Clear Objective
Implement flow construction by instantiating nodes from registry, setting parameters, wiring with PocketFlow operators, and creating an executable Flow object.

## Context from Knowledge Base
- Building on: CompilationError and import_node_class() from subtasks 4.1 and 4.2
- Avoiding: Wrapper classes, code generation, template variable resolution at compile time
- Following: Direct pocketflow usage, structured logging with phases, comprehensive error handling
- **Cookbook patterns to apply**:
  - Basic flow construction from `pocketflow-flow`
  - Action-based routing from `pocketflow-agent`
  - Parameter setting patterns from `pocketflow-batch-flow`

## Technical Specification

### Inputs
- `ir_dict`: Validated IR dictionary with structure:
  ```python
  {
      "nodes": [
          {
              "id": str,           # Unique node identifier
              "type": str,         # Registry node type (e.g., "test-node")
              "params": dict       # Optional parameters (may contain $variables)
          }
      ],
      "edges": [
          {
              "source": str,       # Source node ID
              "target": str,       # Target node ID
              "action": str        # Optional action (default: "default")
          }
      ]
  }
  ```
- `registry`: Registry instance for node metadata lookup

### Outputs
- `pocketflow.Flow`: Executable flow object with all nodes wired according to edges

### Implementation Constraints
- Must use: import_node_class() for getting node classes
- Must use: Direct instantiation with `NodeClass()` (no parameters to constructor)
- Must use: node.set_params(params) if params exist
- Must use: >> operator for default connections, - operator for action routing
- Must avoid: Resolving template variables (pass $var through unchanged)
- Must avoid: Using execution config (max_retries, wait) in MVP
- Must maintain: CompilationError with phase, node_id, details, suggestion

## Success Criteria
- [ ] All nodes from IR are instantiated as pocketflow nodes
- [ ] Parameters are set via set_params() including template variables unchanged
- [ ] All edges create proper node connections (>> or - with action)
- [ ] Start node is identified (first node if not specified)
- [ ] Flow object is created with start node
- [ ] CompilationError raised for missing nodes, bad edges, etc.
- [ ] Structured logging tracks each phase
- [ ] All tests pass including edge cases
- [ ] No regressions in existing compiler functionality

## Test Strategy
- Unit tests: Mock nodes to verify instantiation, parameter setting, connections
- Edge cases: Missing node references, empty nodes array, invalid actions
- Integration test: One test with real TestNode if exists in registry
- Logging tests: Verify phase tracking with caplog
- Error tests: Verify CompilationError has proper context

## Dependencies
- Requires: import_node_class() function from subtask 4.2
- Requires: CompilationError class from subtask 4.1
- Requires: pocketflow BaseNode, Flow classes
- Impacts: Future runtime will execute the compiled Flow objects

## Decisions Made
- Use "source/target" for edges (not "from/to") - matches existing code
- Use "type" for node type (not "registry_id") - matches existing code
- Use first node as start if not specified - simple and deterministic
- Pass template variables unchanged - runtime concern, not compile time
- Skip execution config for MVP - keep it simple
- Use mocks for testing - avoid dependencies

## Implementation Steps
1. Create helper function `_instantiate_nodes(ir_dict, registry)` that:
   - Loops through nodes array
   - Uses import_node_class() to get each node class
   - Instantiates with NodeClass()
   - Calls set_params() if params exist
   - Returns dict mapping node_id -> node_instance

2. Create helper function `_wire_nodes(nodes, edges)` that:
   - Loops through edges array
   - Looks up source and target nodes
   - Uses >> for default action or - for specific actions
   - Handles missing node references with CompilationError

3. Create helper function `_get_start_node(nodes, ir_dict)` that:
   - Checks for explicit start_node field (future)
   - Falls back to first node in nodes dict
   - Raises CompilationError if no nodes

4. Update compile_ir_to_flow() to:
   - Call the three helper functions
   - Create Flow(start=start_node)
   - Return the flow object

5. Create comprehensive tests in test_flow_construction.py
