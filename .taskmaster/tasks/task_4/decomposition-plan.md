# Task 4 Decomposition Plan: IR-to-PocketFlow Compiler

## Task Overview

Task 4 implements the IR-to-PocketFlow compiler that transforms validated JSON IR into executable pocketflow.Flow objects. This compiler serves as the critical bridge between the declarative workflow representation (JSON) and the imperative execution model (pocketflow objects).

**Complexity**: 5/10 (Medium)
**Estimated Time**: 4-6 hours
**Dependencies**: Task 5 (Registry - Done), Task 6 (IR Schema - Done)

## Decomposition Pattern

Using **Foundation-Integration-Polish** pattern:
1. **Foundation**: Core compilation infrastructure and error handling
2. **Integration**: Dynamic imports and flow construction
3. **Polish**: Comprehensive error messages and testing

## Detailed Subtask Descriptions

### Subtask 4.1: Create Compiler Foundation with IR Loading
**Description**: Set up the compiler module structure and implement IR loading with basic validation
**Estimated Time**: 1-2 hours
**Dependencies**: None

Implement the foundation of `src/pflow/runtime/compiler.py`:
- Create module with main `compile_ir_to_flow(ir_json, registry)` function signature
- Implement IR loading (handle both dict and JSON string inputs)
- Add basic structure validation (ensure nodes, edges arrays exist)
- Create custom `CompilationError` exception class with rich context
- Set up logging for debugging compilation steps
- Write initial tests for IR loading and error cases

Key considerations:
- The IR has already been validated by Task 6, but verify basic structure
- Handle both pre-parsed dicts and JSON strings for flexibility
- Error messages should include context (node_id, node_type when available)

### Subtask 4.2: Implement Dynamic Node Import System
**Description**: Build the core dynamic import functionality that loads node classes from registry metadata
**Estimated Time**: 2 hours
**Dependencies**: Subtask 4.1

Implement the dynamic import system:
- Create helper function for safe dynamic imports using `importlib.import_module()`
- For each node in IR:
  - Look up metadata in registry using node type
  - Import module using registry's module path
  - Get class using `getattr(module, class_name)`
  - Verify class inherits from `pocketflow.BaseNode`
- Handle import failures gracefully:
  - ImportError: Module not found
  - AttributeError: Class not found in module
  - TypeError: Class doesn't inherit from BaseNode
- Add retry logic for flaky imports (optional but recommended)
- Create comprehensive error messages:
  - Example: "Node 'n1' (type: github-get-issue) - Cannot import module 'pflow.nodes.github.github_get_issue': No module named 'pflow.nodes.github'"

Testing approach:
- Mock importlib to test various failure scenarios
- Test with test nodes from Task 5
- Verify inheritance checking works correctly

### Subtask 4.3: Build Flow Construction and Wiring
**Description**: Implement node instantiation, parameter setting, and flow wiring using PocketFlow operators
**Estimated Time**: 1-2 hours
**Dependencies**: Subtask 4.2

Complete the flow construction:
- Instantiate node objects from imported classes
- Set parameters using `node.set_params()` if params exist
- Connect nodes based on edges:
  - Use `>>` for default connections
  - Use `-` operator for action-based routing
- Handle the start_node (use first node if not specified)
- Create and return the pocketflow.Flow object
- Add comprehensive logging for debugging

Key implementation details:
- Store nodes in a dict keyed by node ID for easy lookup
- Handle both "default" and named actions in edges
- Pass template variables ($var) unchanged - resolution happens at runtime
- Verify all edge references are valid (from/to nodes exist)

Testing:
- Test simple linear flows
- Test flows with action-based routing
- Test flows with parameters
- Test invalid edge references

### Subtask 4.4: Add Integration Tests and Polish
**Description**: Create comprehensive integration tests and improve error messages based on testing
**Estimated Time**: 1 hour
**Dependencies**: Subtasks 4.1, 4.2, 4.3

Final polish and testing:
- Create integration tests with real IR examples
- Test end-to-end compilation with mock nodes
- Improve error messages based on test scenarios
- Add performance tests (compilation should be fast)
- Write documentation and examples
- Ensure all code follows project conventions

Test scenarios:
- Valid IR from examples/
- Various error conditions with helpful messages
- Performance with large workflows
- Integration with actual registry from Task 5

## Relevant Documentation

### Essential pflow Documentation
- `architecture/architecture/pflow-pocketflow-integration-guide.md` - **Critical**: Shows the exact pattern for IR compilation (see section #7)
- `architecture/core-concepts/schemas.md` - Defines the IR structure we're compiling
- `architecture/core-concepts/registry.md` - Explains registry metadata format
- `architecture/core-concepts/runtime.md` - Shows how compiled flows will be executed

### PocketFlow Documentation
- `pocketflow/__init__.py` - Source of truth for BaseNode, Node, and Flow classes
- `pocketflow/docs/core_abstraction/flow.md` - Understanding Flow orchestration
- `pocketflow/docs/core_abstraction/node.md` - Node lifecycle and methods

### Relevant PocketFlow Examples
- `pocketflow/cookbook/Tutorial-Cursor/flow.py` - Shows programmatic flow construction
- `pocketflow/cookbook/pocketflow-supervisor/flow.py` - Demonstrates error handling patterns

## Research References

The following research files contain additional context (already incorporated above):
- `research/ir-compiler-design-decisions.md` - Design rationale
- `research/implementation-notes.md` - Technical constraints
- `research/example-implementation-skeleton.py` - Code structure reference

## Key Considerations

1. **Dynamic Import Security**: The compiler executes code on import - this is noted in comments
2. **Error Context**: All errors should include node ID and type for debugging
3. **Template Variables**: Pass $variables unchanged - runtime handles resolution
4. **No Over-Engineering**: This is object wiring, not complex compilation
5. **Direct PocketFlow Usage**: No wrapper classes - use pocketflow directly

## Success Criteria

- Compiles valid IR to executable Flow objects
- Clear error messages for all failure modes
- Fast compilation (< 100ms for typical workflows)
- Works with test nodes from Task 5
- All tests pass including integration tests
- Follows project conventions and style

## Implementation Order

1. Start with 4.1 to establish foundation
2. Move to 4.2 for the critical dynamic import logic
3. Complete flow construction in 4.3
4. Polish with tests and documentation in 4.4

This decomposition follows the epistemic principle of understanding before implementation, with each subtask building on the previous one's foundation.
