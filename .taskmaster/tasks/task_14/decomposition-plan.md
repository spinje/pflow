# Task 14 Decomposition Plan

**File Location**: `.taskmaster/tasks/task_14/decomposition-plan.md`

*Created on: 2025-07-16*
*Purpose: Comprehensive prompt for task-master expand command*

## Task Overview
Task 14 enhances pflow's metadata extraction system to support type annotations, structure documentation, and semantic descriptions for all Interface components (Reads, Writes, Params). This enables the planner to generate valid proxy mapping paths like `issue_data.user.login` by making data structures visible. The enhancement maintains full backward compatibility while adding crucial type information that the planner needs.

## Decomposition Pattern
**Pattern**: Foundation-Integration-Polish

**Reasoning**: This pattern worked successfully for Tasks 7 and 16 (similar metadata/parsing tasks). It allows building the core parser first, then integrating with existing systems, and finally polishing with comprehensive node migration and testing.

## Complexity Analysis
- **Complexity Score**: 7/10
- **Reasoning**: Complex indentation-based parsing, backward compatibility requirements, extensive node migration scope, but clear specifications and examples
- **Total Subtasks**: 4

## Planned Subtasks

### Subtask 1: Implement Enhanced Interface Parser with Type Support
**Description**: Create the core parsing functionality to extract types, structures, and descriptions from the enhanced Interface format while maintaining backward compatibility with the existing simple format. This parser will handle indentation-based structure parsing and inline comment extraction.
**Dependencies**: None
**Estimated Hours**: 4-5
**Implementation Details**:
- Extend parsing logic in `src/pflow/registry/metadata_extractor.py`
- Implement detection logic for old vs new format based on colon presence
- Create indentation-based parser for nested structures (not complex regex)
- Add comment parsing for semantic descriptions using # syntax
- Ensure graceful fallback for malformed structures
- Focus on the `_extract_list_section()` method as the extension point

**Test Requirements**:
- Test both old format (`Writes: shared["key1"], shared["key2"]`) and new format with types
- Test nested structure parsing with various indentation levels
- Test comment extraction and handling
- Test error cases and graceful degradation
- Test with real node docstrings from the codebase

### Subtask 2: Integrate Enhanced Parser with Metadata System
**Description**: Update the metadata extractor to use the enhanced parser and modify the storage format to include type, description, and structure information. Update the context builder with minimal changes to display the new type information effectively for the planner.
**Dependencies**: [14.1]
**Estimated Hours**: 3-4
**Implementation Details**:
- Modify `extract_metadata()` to store types directly in outputs/inputs/params arrays as objects
- Update storage format from simple lists to objects with key, type, description, structure fields
- Update `context_builder.py` with minimal changes to `_format_node_section()`
- Ensure backward compatibility - nodes without types still work
- Apply the "exclusive params" pattern (filter params that are inputs)
- Consider the 50KB context limit when formatting structures

**Test Requirements**:
- Test metadata extraction produces correct enhanced format
- Test context builder displays type information correctly
- Test backward compatibility with existing nodes
- Verify integration with registry storage
- Test that exclusive params filtering works correctly

### Subtask 3: Migrate All Nodes to Enhanced Interface Format
**Description**: Update ALL nodes in `src/pflow/nodes/` to use the enhanced Interface format with types, structures, and semantic descriptions. Also update all examples in the `examples/` folder to demonstrate the new typed interfaces and proxy mapping capabilities.
**Dependencies**: [14.2]
**Estimated Hours**: 5-6
**Implementation Details**:
- Start with priority nodes: github-get-issue (most complex), github-list-prs (arrays)
- Add types to all Interface components (Reads, Writes, Params)
- Document nested structures for API response nodes
- Add semantic descriptions using # comments for clarity
- Update file operation nodes with metadata structure documentation
- Update all workflow examples to use typed nodes
- Follow consistent format established in subtasks 1-2

**Test Requirements**:
- Verify each migrated node's metadata extracts correctly
- Test that examples work with the new format
- Ensure no regression in node functionality
- Test complex proxy mappings work with documented structures

### Subtask 4: Comprehensive Testing and Documentation
**Description**: Create comprehensive test coverage for the enhanced metadata system, including unit tests, integration tests, and end-to-end validation. Update documentation to guide developers on using the new Interface format.
**Dependencies**: [14.3]
**Estimated Hours**: 3-4
**Implementation Details**:
- Extend tests in `test_metadata_extractor.py` for all new functionality
- Create integration tests with mock planner scenarios
- Add end-to-end test with github-get-issue proxy mapping example
- Write migration guide for developers
- Document the enhanced Interface format specification
- Update any affected documentation in `docs/`

**Test Requirements**:
- 100% coverage of new parser functionality
- Integration tests covering all format variations
- Performance tests for parsing overhead
- Documentation validates against actual implementation

## Relevant pflow Documentation
[ALWAYS include - Reference key project documentation that guides this task]

### Core Documentation
- `architecture/implementation-details/metadata-extraction.md` - Comprehensive extraction infrastructure
  - Relevance: Defines the metadata extraction architecture and extension points
  - Key concepts: Extraction phases, registry integration, error handling patterns
  - Applies to subtasks: 1, 2, and 4

- `architecture/core-concepts/schemas.md` - Sections 2.1-2.4 on Node Metadata Schema
  - Relevance: Defines the storage format for node metadata
  - Key concepts: Metadata structure, validation requirements
  - Applies to subtasks: 2 (storage format changes)

- `architecture/core-concepts/shared-store.md` - Natural interface patterns and proxy mappings
  - Relevance: Explains why structure visibility is crucial for proxy mappings
  - Key concepts: Path-based access, proxy mapping patterns
  - Applies to subtasks: 3 (when documenting structures)

### Architecture/Feature Documentation
- `architecture/core-concepts/registry.md` - Section 4.3 on metadata generation
  - Critical for: Understanding how metadata integrates with registry
  - Must follow: Registry storage conventions and format
  - Applies to subtasks: 2 (integration)

## Relevant PocketFlow Documentation
[Not applicable for this task - Task 14 focuses on pflow's internal metadata system]

## Relevant PocketFlow Examples
[Not applicable for this task]

## Research References
[Research files exist and have been critically reviewed]

### For All Subtasks:
- Reference insights from `.taskmaster/tasks/task_14/14_ambiguities.md`
- Specifically: Format decisions, storage approach, backward compatibility strategy
- Critical: "Writes = Outputs" understanding, no separate Outputs section

### For Subtask 1:
- Apply indentation-based parsing recommendation from `.taskmaster/tasks/task_14/implementation-recommendations.md`
- Key insight: Avoid regex complexity explosion, use simple indentation parsing

### For Subtask 3:
- Reference `.taskmaster/tasks/task_14/task-14-descriptions-analysis.md`
- Key insight: Semantic descriptions may be more valuable than types alone
- Focus on making descriptions clear and helpful for the planner

## Key Architectural Considerations
- Backward compatibility is non-negotiable - existing nodes must continue working
- Types are stored directly in outputs/inputs/params arrays as objects, not separate dictionaries
- The Interface section uses "Writes:" for outputs (verified in codebase)
- Context builder changes must be minimal - no major redesigns
- Security constraint: Cannot use eval() or ast.literal_eval() for parsing

## Dependencies Between Subtasks
- 14.2 requires 14.1 because it needs the enhanced parser implementation
- 14.3 requires 14.2 because nodes need the updated system to test against
- 14.4 requires 14.3 to test the complete system with migrated nodes

## Success Criteria
- [ ] Planner can generate valid proxy paths like `issue_data.user.login` on first attempt
- [ ] All existing nodes continue working without modification (backward compatibility)
- [ ] All nodes in `src/pflow/nodes/` have type annotations
- [ ] Context builder displays type and structure information clearly
- [ ] Comprehensive test coverage for parser and integration
- [ ] Developer documentation for using enhanced Interface format

## Special Instructions for Expansion
- Each subtask should emphasize test-as-you-go development
- Include specific references to the established Interface format pattern
- Ensure subtask 1 creates a robust foundation that subtasks 2-4 can build upon
- Subtask 3 should be thorough - every node and example must be migrated
- Consider the critical insights about "exclusive params" pattern from knowledge base
- Reference the specific ambiguity resolutions in task documentation

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. Ensure it contains ALL context needed for intelligent subtask generation, including explicit references to project documentation, framework docs, and examples.
