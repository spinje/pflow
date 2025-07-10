# Task 16 Decomposition Plan

**File Location**: `.taskmaster/tasks/task_16/decomposition-plan.md`

*Created on: 2025-01-10*
*Purpose: Comprehensive prompt for task-master expand command*

## Task Overview
Task 16 creates a planning context builder that formats node metadata for LLM-based workflow planning. This component bridges the gap between the technical node registry/metadata system and the natural language planner, transforming structured metadata into LLM-optimized text that clearly shows available nodes and their interfaces.

## Decomposition Pattern
**Pattern**: Foundation-Integration-Polish

**Reasoning**: This pattern fits perfectly because we need to:
1. Build the core formatting logic first (Foundation)
2. Integrate with registry and metadata extractor (Integration)
3. Optimize the output format and handle edge cases (Polish)

## Complexity Analysis
- **Complexity Score**: 4/10
- **Reasoning**: Moderate complexity - clear inputs/outputs, but requires careful formatting and defensive programming
- **Total Subtasks**: 3

## Planned Subtasks

### Subtask 1: Create core context builder with basic formatting
**Description**: Create the initial `src/pflow/planning/context_builder.py` module with the `build_context()` function. Implement basic node formatting that transforms metadata into markdown text. Focus on the core transformation logic without worrying about categories or optimization.
**Dependencies**: None
**Estimated Hours**: 3-4
**Implementation Details**:
- Create the planning directory and context_builder.py file
- Implement `build_context(registry_metadata: dict[str, dict[str, Any]]) -> str`
- Format individual nodes into markdown sections
- Apply the "exclusive parameters" pattern - filter out params that are also inputs
- Use simple, consistent formatting for each node

**Test Requirements**:
- Test basic formatting with sample metadata
- Test parameter filtering (exclusive params only)
- Test output format consistency
- Test with minimal metadata (just description)

### Subtask 2: Integrate registry loading and metadata extraction
**Description**: Integrate the context builder with Task 5's registry and Task 7's metadata extractor. Add dynamic node class importing, handle import failures gracefully, and implement the production node filtering logic.
**Dependencies**: [16.1]
**Estimated Hours**: 3-4
**Implementation Details**:
- Import and use `PflowMetadataExtractor` from Task 7
- Use `import_node_class()` from runtime.compiler for dynamic imports
- Handle import failures with logging (skip failed nodes)
- Filter to include only production nodes with valid Interface sections
- Skip nodes without metadata entirely
- Add structured logging with phase tracking

**Test Requirements**:
- Test integration with real registry data
- Test import failure handling
- Test filtering of test nodes vs production nodes
- Test with nodes that have no Interface section
- Verify logging for skipped nodes

### Subtask 3: Add category organization and format optimization
**Description**: Enhance the output format by organizing nodes into logical categories (File Operations, Git Operations, etc.). Optimize the markdown format for LLM comprehension and add monitoring for context size.
**Dependencies**: [16.2]
**Estimated Hours**: 2-3
**Implementation Details**:
- Implement category detection based on node paths/names
- Group nodes by category in the output
- Add section headers for better organization
- Implement size monitoring (log warnings for large contexts)
- Polish the markdown format based on planner.md examples
- Ensure clear distinction between shared store and configuration params

**Test Requirements**:
- Test category grouping logic
- Test output format matches examples in documentation
- Test size monitoring warnings
- Integration test with multiple node types
- Verify LLM-friendly formatting

## Relevant pflow Documentation

### Core Documentation
- `docs/features/planner.md` - Section 6.1 on template string composition
  - Relevance: Shows how the planner will consume our context output
  - Key concepts: Template variables, node references in workflows
  - Applies to subtasks: All (defines target format)

- `docs/implementation-details/metadata-extraction.md` - Lines 784-860
  - Relevance: Contains example PlannerContextBuilder implementation
  - Key concepts: Optimization strategies, caching approaches
  - Applies to subtasks: 2 and 3

- `docs/core-concepts/shared-store.md` - Shared store patterns
  - Relevance: Critical for understanding parameter classification
  - Key concepts: Data flow vs configuration parameters
  - Applies to subtasks: 1 (parameter filtering)

### Architecture Documentation
- `docs/architecture/architecture.md` - System overview
  - Critical for: Understanding where context builder fits
  - Must follow: Component isolation principles

## Research References

### For Subtask 1:
- Apply formatting patterns from `.taskmaster/tasks/task_16/research/context-builder-braindump.md`
- Specifically: Text-based markdown format, interface-first design
- Adaptation needed: Simplify - no caching or token management initially

### For Subtask 2:
- Reference: `.taskmaster/tasks/task_16/research/edge-cases-examples.md`
- Key insight: Defensive handling of missing/malformed metadata
- Use the "mixed registry" example for testing

### For Subtask 3:
- Apply category organization from `.taskmaster/tasks/task_16/research/quick-reference.md`
- Key insight: Simple pattern matching for categories
- Adaptation: Make category detection flexible, not brittle

## Key Architectural Considerations
- The context builder is NOT a PocketFlow node - it's a simple utility function
- Must handle registry metadata format exactly as provided by Task 5
- Must use Task 7's metadata extractor for Interface details
- Output format must support the planner's template variable system
- Apply the "shared store inputs as automatic parameter fallbacks" pattern

## Dependencies Between Subtasks
- 16.2 requires 16.1 because it builds on the core formatting logic
- 16.3 requires 16.2 because it needs the full integration to organize output

## Success Criteria
- [ ] LLM can understand available nodes from the output
- [ ] Clear distinction between shared store inputs and configuration parameters
- [ ] Graceful handling of missing metadata and import failures
- [ ] Output organized by logical categories
- [ ] All subtasks have clear implementation paths
- [ ] Test coverage for all new functionality

## Special Instructions for Expansion
- Focus on defensive programming throughout all subtasks
- Ensure each subtask references the specific documentation sections mentioned
- Include error handling for all external dependencies (registry, imports)
- Each subtask should produce working, testable code
- Remember the key insight: ALL shared store inputs are automatic parameter fallbacks

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. Ensure it contains ALL context needed for intelligent subtask generation, including explicit references to project documentation, framework docs, and examples.
