# Implementation Plan for Subtask 16.1

## Objective
Create a context builder that transforms node registry metadata into LLM-optimized markdown documentation, enabling the workflow planner to discover and compose nodes with 95% success rate.

## Implementation Steps

1. [ ] Create planning directory structure
   - File: src/pflow/planning/__init__.py
   - Change: Create empty __init__.py file
   - Test: Verify module can be imported

2. [ ] Create context_builder.py with imports
   - File: src/pflow/planning/context_builder.py
   - Change: Add imports for import_node_class, PflowMetadataExtractor, logging
   - Test: Verify imports work correctly

3. [ ] Implement build_context function skeleton
   - File: src/pflow/planning/context_builder.py
   - Change: Add function signature with proper docstring
   - Test: Verify function can be called

4. [ ] Implement node processing logic
   - File: src/pflow/planning/context_builder.py
   - Change: Add loop to process registry nodes with test filtering
   - Test: Verify test nodes are skipped

5. [ ] Implement metadata extraction with error handling
   - File: src/pflow/planning/context_builder.py
   - Change: Add try/except blocks for import and extraction
   - Test: Verify graceful handling of failures

6. [ ] Implement exclusive parameter filtering
   - File: src/pflow/planning/context_builder.py
   - Change: Filter params that are also in inputs list
   - Test: Verify only configuration params are shown

7. [ ] Implement category grouping logic
   - File: src/pflow/planning/context_builder.py
   - Change: Add simple pattern matching for categories
   - Test: Verify nodes are grouped appropriately

8. [ ] Implement markdown formatting
   - File: src/pflow/planning/context_builder.py
   - Change: Format nodes into clean markdown sections
   - Test: Verify output format matches specification

9. [ ] Add comprehensive logging
   - File: src/pflow/planning/context_builder.py
   - Change: Add context-specific logging with "context:" prefix
   - Test: Verify useful debugging information is logged

10. [ ] Create comprehensive test suite
    - File: tests/test_planning/test_context_builder.py
    - Change: Add unit tests for all functionality
    - Test: Run pytest and ensure all tests pass

11. [ ] Integration testing
    - File: Manual testing script or integration test
    - Change: Test with real registry data
    - Test: Verify output is suitable for LLM consumption

## Pattern Applications

### Previous Task Patterns
- Using **Phased Implementation** from Task 7 for clear separation of processing steps
- Using **Defensive Metadata Handling** from Task 7 for graceful degradation
- Using **Dynamic Import Pattern** from Task 5 via import_node_class()
- Using **Component-Specific Logging** from Task 7 with "context:" prefix
- Avoiding **Registry Field Name Confusion** - using "docstring" not "description"

## Risk Mitigations
- **Import failures**: Wrap in try/except, log and continue
- **Missing metadata**: Check for None values before accessing
- **Test node pollution**: Filter early based on file path
- **Parameter redundancy**: Apply exclusive parameter filter consistently
- **Large output**: Monitor size and log if unusually large (>10KB or >50 nodes)
