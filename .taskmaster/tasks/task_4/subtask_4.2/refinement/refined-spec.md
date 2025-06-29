# Refined Specification for Subtask 4.2

## Clear Objective
Create a helper function import_node_class(node_type: str, registry: Registry) -> Type[BaseNode] that dynamically imports node classes from registry metadata with comprehensive error handling.

## Context from Knowledge Base
- Building on: CompilationError with rich context from Task 4.1, structured logging pattern with phases
- Avoiding: Broad exception catching, assuming registry has class references, missing inheritance validation
- Following: Error namespace convention ("compiler:" prefix), direct pocketflow imports, test with mocks
- **Cookbook patterns to apply**: Dynamic import pattern from pocketflow-visualization example

## Technical Specification

### Inputs
- `node_type`: String identifier for the node (e.g., "read-file", "llm")
- `registry`: Registry instance containing node metadata

### Outputs
- Returns: The node class (Type[BaseNode]) ready for instantiation
- Note: Returns the class itself, NOT an instance

### Implementation Constraints
- Must use: importlib.import_module() for dynamic imports
- Must use: getattr() to extract class from module
- Must use: issubclass() to verify BaseNode inheritance
- Must avoid: Instantiating the class (return class only)
- Must maintain: Structured logging with phase tracking

## Success Criteria
- [ ] Function handles all 4 error types with proper CompilationError
- [ ] Each error includes complete context (phase, node_id, node_type, details, suggestion)
- [ ] Structured logging at each major step with phase information
- [ ] Returns class reference, not instance
- [ ] All tests pass including real import test with test_node.py
- [ ] No broad exception catching (only ImportError, AttributeError)

## Test Strategy
- Unit tests: Mock importlib.import_module for various scenarios
  - Success case with valid mock node class
  - Registry miss with helpful suggestions
  - ImportError with module path details
  - AttributeError with class name details
  - Invalid inheritance with actual base classes listed
- Integration tests: Real import of TestNode from src/pflow/nodes/test_node.py
- Manual verification: Error messages are helpful and actionable

## Dependencies
- Requires: Registry instance with load() method returning dict[str, dict]
- Requires: CompilationError class from compiler module
- Requires: BaseNode from pocketflow package
- Impacts: Subtask 4.3 will use this to instantiate nodes from IR

## Decisions Made
- Check for BaseNode inheritance (not just Node): Matches registry behavior and provides maximum flexibility
- Return class without instantiation test: Follows specification, defers instantiation to usage point
- Use specific exception handling: Better debugging than catch-all
- Follow importlib + getattr pattern: Standard Python approach used in PocketFlow cookbook
