# Implementation Plan for Subtask 4.2

## Objective
Create a helper function import_node_class(node_type: str, registry: Registry) -> Type[BaseNode] that dynamically imports node classes from registry metadata with comprehensive error handling.

## Implementation Steps

1. [ ] Add import_node_class function to compiler.py
   - File: src/pflow/runtime/compiler.py
   - Change: Add function after the existing helper functions
   - Test: Function signature and basic structure

2. [ ] Implement registry lookup with error handling
   - File: src/pflow/runtime/compiler.py
   - Change: Load registry, check if node_type exists, build helpful error if missing
   - Test: Test with missing node type

3. [ ] Implement dynamic module import
   - File: src/pflow/runtime/compiler.py
   - Change: Use importlib.import_module() with ImportError handling
   - Test: Mock import failures

4. [ ] Implement class extraction with getattr
   - File: src/pflow/runtime/compiler.py
   - Change: Use getattr() to get class from module with AttributeError handling
   - Test: Mock missing class scenarios

5. [ ] Implement BaseNode inheritance validation
   - File: src/pflow/runtime/compiler.py
   - Change: Use issubclass() to verify inheritance, handle non-class objects
   - Test: Mock invalid inheritance cases

6. [ ] Add structured logging throughout
   - File: src/pflow/runtime/compiler.py
   - Change: Add debug logs with phase tracking at each step
   - Test: Verify logs in tests

7. [ ] Create comprehensive test suite
   - File: tests/test_compiler_dynamic_imports.py
   - Change: Create new test file with all scenarios
   - Test: Run pytest to ensure all pass

8. [ ] Add integration test with real node
   - File: tests/test_compiler_dynamic_imports.py
   - Change: Add test using actual TestNode from src/pflow/nodes/test_node.py
   - Test: Verify real-world import works

## Pattern Applications

### Cookbook Patterns
- **Dynamic Import Pattern from pocketflow-visualization**: Direct application of importlib + getattr pattern
  - Specific code/approach: `module = importlib.import_module(module_path); cls = getattr(module, class_name)`
  - Modifications needed: Add inheritance validation after getting class

### Previous Task Patterns
- Using CompilationError with rich context from Task 4.1 for all error cases
- Using structured logging with phases from Task 4.1 for debugging
- Avoiding broad exception catching from Task 5 learnings
- Using specific mocking strategies from Task 5 for testing imports

## Risk Mitigations
- **Risk**: Circular imports when loading nodes
  - **Mitigation**: Use importlib which handles this gracefully
- **Risk**: Security issues from arbitrary code execution
  - **Mitigation**: Document this is for trusted nodes only (MVP scope)
- **Risk**: Performance with many imports
  - **Mitigation**: Python caches imported modules automatically
