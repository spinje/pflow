# Implementation Plan for Subtask 5.1

## Objective
Create test nodes and implement the core filesystem scanner that discovers all classes inheriting from pocketflow.BaseNode and extracts basic metadata.

## Implementation Steps

1. [ ] Create directory structure
   - File: src/pflow/registry/__init__.py
   - Change: Create empty __init__.py for package
   - Test: Verify package can be imported

2. [ ] Create test node with BaseNode inheritance
   - File: src/pflow/nodes/test_node.py
   - Change: Create TestNode class inheriting from BaseNode with Interface docstring
   - Test: Manually verify it follows pocketflow patterns

3. [ ] Create test node with Node inheritance
   - File: src/pflow/nodes/test_node_retry.py
   - Change: Create TestNodeRetry class inheriting from Node
   - Test: Verify it has retry capabilities

4. [ ] Implement core scanner function
   - File: src/pflow/registry/scanner.py
   - Change: Implement scan_for_nodes() with security warning
   - Test: Basic functionality with test nodes

5. [ ] Add sys.path management
   - File: src/pflow/registry/scanner.py
   - Change: Add context manager for temporary sys.path modifications
   - Test: Verify imports work correctly

6. [ ] Implement metadata extraction
   - File: src/pflow/registry/scanner.py
   - Change: Extract 5 required fields (module, class_name, name, docstring, file_path)
   - Test: Verify all fields extracted correctly

7. [ ] Add error handling
   - File: src/pflow/registry/scanner.py
   - Change: Handle import errors gracefully with logging
   - Test: Mock import failures

8. [ ] Write comprehensive tests
   - File: tests/test_scanner.py
   - Change: Create full test suite
   - Test: Run all tests with coverage

## Pattern Applications

### Cookbook Patterns
- **Minimal Node Pattern**: Apply to test_node.py
  - Specific code/approach: Simple prep/exec/post with shared store access
  - Modifications needed: Add Interface docstring for metadata testing

- **Node with Retry Pattern**: Apply to test_node_retry.py
  - Specific code/approach: Inherit from Node instead of BaseNode
  - Modifications needed: Include retry-specific documentation

### Previous Task Patterns
- Using Test-As-You-Go from Task 1 for immediate test creation
- Using Module Organization from Task 1 for clean package structure
- Avoiding Direct task-master Updates by using progress-log.md

## Risk Mitigations
- Import path issues: Use context manager for sys.path to ensure clean state
- Security concerns: Add explicit warning comment about code execution
- Edge cases: Create comprehensive test suite including mocks
- BaseNode vs Node confusion: Clear documentation and explicit checks
