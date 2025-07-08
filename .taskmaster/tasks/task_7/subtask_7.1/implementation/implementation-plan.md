# Implementation Plan for Subtask 7.1

## Objective
Implement a core metadata extractor that validates node classes and extracts basic metadata from their docstrings, focusing on description extraction and structure setup.

## Implementation Steps

1. [ ] Create the metadata extractor module
   - File: `/src/pflow/registry/metadata_extractor.py`
   - Change: Create `PflowMetadataExtractor` class with `extract_metadata` method
   - Test: Unit test with sample node class

2. [ ] Implement node validation logic
   - File: `/src/pflow/registry/metadata_extractor.py`
   - Change: Add validation for class type and BaseNode inheritance
   - Test: Test with valid nodes, instances, non-nodes, None

3. [ ] Implement description extraction
   - File: `/src/pflow/registry/metadata_extractor.py`
   - Change: Extract first line of docstring with fallback to "No description"
   - Test: Test with various docstring formats

4. [ ] Create comprehensive test suite
   - File: `/tests/test_registry/test_metadata_extractor.py`
   - Change: Create tests for all edge cases and real nodes
   - Test: Run pytest to ensure all tests pass

5. [ ] Import validation with real nodes
   - File: `/tests/test_registry/test_metadata_extractor.py`
   - Change: Add tests using actual file nodes from the codebase
   - Test: Verify works with production nodes

6. [ ] Run quality checks
   - File: All modified files
   - Change: Run `make test` and `make check`
   - Test: Ensure all checks pass

## Pattern Applications

### Cookbook Patterns
- **Node Inheritance Validation**: Using `issubclass(cls, pocketflow.BaseNode)`
  - Specific code/approach: Safe inheritance checking with try/except
  - Modifications needed: None, pattern fits perfectly

### Previous Task Patterns
- Using **Phased Error Handling** from Task 4 for clear error contexts
- Using **Error Namespace Convention** from Task 2 for consistent error messages
- Avoiding **Over-engineering** pitfall from Task 5 - keep it simple
- Using **Direct Testing Pattern** from Task 3 for unit tests

## Risk Mitigations
- **Import errors**: Use try/except around pocketflow import
- **AttributeError on docstring**: Use `inspect.getdoc()` for safe extraction
- **Type confusion**: Validate input is a class before processing
- **Missing docstrings**: Always provide default "No description"
