# Task 15 Decomposition Plan

**File Location**: `.taskmaster/tasks/task_15/decomposition-plan.md`

*Created on: 2025-07-18*
*Purpose: Comprehensive prompt for task-master expand command*

## Task Overview
Task 15 extends the existing context builder (from Task 16) to support a two-phase discovery approach for the Natural Language Planner. It splits context building into lightweight discovery and detailed planning phases, adds workflow discovery support, and implements structure documentation with combined JSON + paths format for proxy mapping generation.

## Decomposition Pattern
**Pattern**: Foundation-Integration-Polish

**Reasoning**: This pattern fits because we need to:
1. Build workflow infrastructure first (foundation for other features)
2. Integrate two-phase context functions into existing system
3. Enhance structure display for proxy mappings
4. Polish with comprehensive testing and integration

## Complexity Analysis
- **Complexity Score**: 6/10
- **Reasoning**: Moderate parser work, critical infrastructure changes, must preserve fragile regex patterns
- **Total Subtasks**: 4

## Planned Subtasks

### Subtask 1: Workflow Loading Infrastructure
**Description**: Create workflow directory utilities and implement `_load_saved_workflows()` function to load saved workflows from `~/.pflow/workflows/*.json`. This establishes the foundation for workflow discovery in the context builder.
**Dependencies**: None
**Estimated Hours**: 3-4
**Implementation Details**:
- Create directory utilities to ensure `~/.pflow/workflows/` exists
- Implement `_load_saved_workflows()` in context_builder.py
- Parse JSON files and validate essential fields (name, description, inputs, outputs, ir)
- Skip invalid files with warnings (don't crash)
- Return list of workflow metadata dictionaries
- Create 2-3 test workflows using test nodes (test_node, test_node_structured)
- Create 1-2 invalid test workflows for error testing

**Test Requirements**:
- Test directory creation when missing
- Test loading valid workflow files
- Test handling of invalid JSON
- Test handling of missing required fields
- Test that invalid files are skipped gracefully

### Subtask 2: Two-Phase Context Functions
**Description**: Implement `build_discovery_context()` and `build_planning_context()` functions to split context building into discovery (lightweight) and planning (detailed) phases. This is the core deliverable that enables the planner to avoid LLM overwhelm.
**Dependencies**: [15.1]
**Estimated Hours**: 4-5
**Implementation Details**:
- Implement `build_discovery_context(node_ids=None, workflow_names=None)`
  - Extract just names and descriptions from registry metadata
  - Include workflows from `_load_saved_workflows()`
  - Group by categories using existing `_group_nodes_by_category()`
  - Omit missing descriptions (no placeholders)
- Implement `build_planning_context(selected_node_ids, selected_workflow_names, registry_metadata, saved_workflows=None)`
  - Check for missing components first
  - Return error dict with 'error', 'missing_nodes', 'missing_workflows' keys if any missing
  - Filter to selected components only
  - Use existing `_format_node_section()` for full details
  - Apply exclusive params pattern (params in Reads filtered out)
- Reuse existing `_process_nodes()` method for metadata extraction

**Test Requirements**:
- Test discovery context with various component counts (0, 10, 100)
- Test planning context with selected components
- Test error dict return when components missing
- Test workflow inclusion in both contexts
- Test that descriptions are omitted when missing

### Subtask 3: Structure Display Enhancement
**Description**: Enhance the `_format_structure()` method to display structures using combined JSON + paths format for optimal LLM comprehension. This enables the planner to generate valid path-based proxy mappings like `issue_data.user.login`.
**Dependencies**: [15.2]
**Estimated Hours**: 3-4
**Implementation Details**:
- Enhance `_format_structure()` to produce combined format:
  - JSON representation (clean, types only, no descriptions)
  - Path list with descriptions (e.g., `issue_data.user.login (str) - Username`)
- Transform parser output from `_parse_structure()` (already works, lines 543-612)
- Create helper functions:
  - `_structure_to_json()` - Convert to clean JSON representation
  - `_structure_to_paths()` - Flatten to dot-notation paths with descriptions
- Handle arrays with proper notation (e.g., `labels[].name`)
- Preserve existing parser functionality (DO NOT modify the fragile regex)

**Test Requirements**:
- Test JSON format generation from nested structures
- Test path list generation with descriptions
- Test array notation handling
- Test combined format output
- Test with test_node_structured data

### Subtask 4: Integration and Comprehensive Testing
**Description**: Refactor `build_context()` to use the new two-phase functions and create comprehensive integration tests. Document the new docstring format for structure documentation.
**Dependencies**: [15.3]
**Estimated Hours**: 3-4
**Implementation Details**:
- Refactor `build_context()` to delegate to `build_planning_context()` for all components
  - No backward compatibility needed (only tests use it)
  - Simplify to essentially be `build_planning_context()` with all nodes/workflows
- Create comprehensive test suite:
  - Unit tests for new functions
  - Integration tests for full discovery → planning flow
  - Performance tests with realistic data
- Create test workflows that demonstrate structure usage
- Document the enhanced Interface format with structure examples
- Verify all existing tests still pass

**Test Requirements**:
- Full discovery → planning integration test
- Error recovery flow test
- Performance test with 100+ nodes
- Test workflow composition scenarios
- Verify no regressions in existing functionality

## Relevant pflow Documentation

### Core Documentation
- `architecture/core-concepts/registry.md` - Registry architecture and metadata format
  - Relevance: Understanding registry data structure for context building
  - Key concepts: Registry metadata format, node discovery
  - Applies to subtasks: 2, 4

- `architecture/features/planner.md` - Natural Language Planner requirements
  - Relevance: Understanding how planner will consume the two-phase contexts
  - Key concepts: Discovery vs planning phases, proxy mapping needs
  - Applies to subtasks: 2, 3

- `architecture/core-concepts/shared-store.md` - Shared store and proxy patterns
  - Relevance: Understanding proxy mappings and why structure paths are needed
  - Key concepts: Proxy node pattern, data flow between incompatible nodes
  - Applies to subtasks: 3

### Architecture/Feature Documentation
- `architecture/features/mvp-implementation-guide.md` - MVP scope and constraints
  - Critical for: Understanding what's in/out of scope
  - Must follow: MVP limitations, no premature optimization

- `architecture/reference/enhanced-interface-format.md` - Docstring format specification
  - Critical for: Understanding the Interface format and structure documentation
  - Must follow: Format conventions for structure documentation
  - Applies to subtasks: 3, 4

## Key Architectural Considerations
- The structure parser is FULLY IMPLEMENTED (lines 543-612) - use it, don't reimplement
- All 7 nodes already migrated to enhanced format (Task 14)
- Exclusive params pattern is critical - params in Reads are filtered out
- Parser regex patterns are fragile - DO NOT modify without extensive testing
- Context size limit is 200KB (not 50KB as some docs claim)
- No backward compatibility needed for `build_context()` (user confirmed)

## Dependencies Between Subtasks
- 15.2 requires 15.1 because it needs workflow loading functionality
- 15.3 requires 15.2 because it enhances the planning context output
- 15.4 requires 15.3 because it tests the complete integrated system

## Success Criteria
- [ ] Two-phase discovery reduces context size for initial browsing
- [ ] Workflow discovery enables reuse of saved workflows
- [ ] Combined JSON + paths format enables proxy mapping generation
- [ ] Missing components return actionable error information
- [ ] All existing tests pass without modification
- [ ] Performance acceptable with 100+ nodes

## Special Instructions for Expansion
- Reference the detailed ambiguities document at `.taskmaster/tasks/task_15/task-15-context-builder-ambiguities.md`
- Reference the technical guide at `.taskmaster/tasks/task_15/task-15-technical-implementation-guide.md`
- Each subtask should preserve existing functionality while adding new capabilities
- Focus on reusing existing methods rather than reimplementing
- Include specific line numbers from technical guide when relevant
- Emphasize test-as-you-go strategy - tests are part of implementation, not separate

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. The task has detailed analysis documents that provide specific implementation guidance, including exact line numbers for critical code sections and patterns to preserve.
