# Task 5 Decomposition Plan

**File Location**: `.taskmaster/tasks/task_5/decomposition-plan.md`

*Created on: 2025-06-29*
*Purpose: Comprehensive prompt for task-master expand command*

## Task Overview
Task 5 implements the foundation of pflow's node discovery system by creating a filesystem scanner that finds all classes inheriting from `pocketflow.BaseNode`, extracts basic metadata, and stores the registry in a persistent JSON file. This creates the infrastructure that enables dynamic node loading throughout the pflow system.

## Decomposition Pattern
**Pattern**: Foundation-Integration-Polish

**Reasoning**: This pattern fits perfectly because we're building new infrastructure that requires:
1. Foundation: Core scanner logic and test node creation
2. Integration: Registry persistence and dynamic import functionality
3. Polish: Edge case handling and comprehensive testing

## Complexity Analysis
- **Complexity Score**: 4
- **Reasoning**: Moderate complexity due to dynamic imports, filesystem operations, and need for robust error handling
- **Total Subtasks**: 3

## Planned Subtasks

### Subtask 1: Create test node and implement core scanner logic
**Description**: Create the nodes directory structure with a test node inheriting from BaseNode, then implement the core scan_for_nodes() function that discovers Python files and identifies BaseNode subclasses using importlib and inspect.
**Dependencies**: None
**Estimated Hours**: 3-4
**Implementation Details**:
- Create `src/pflow/nodes/` directory structure
- Create `src/pflow/nodes/test_node.py` with a simple BaseNode subclass including Interface docstring
- Create `src/pflow/registry/scanner.py` with scan_for_nodes() function
- Use pathlib for filesystem traversal
- Use importlib.import_module() for dynamic loading
- Use inspect.isclass() and issubclass() for BaseNode detection
- Add security comment about importlib executing code

**Test Requirements**:
- Test discovery of the created test node
- Test filtering of non-BaseNode classes
- Test handling of import errors
- Mock filesystem for edge case testing

### Subtask 2: Implement metadata extraction and registry persistence
**Description**: Extract metadata from discovered nodes (module path, class name, node name via attribute or kebab-case conversion, docstring, file path) and implement JSON persistence at ~/.pflow/registry.json with proper error handling.
**Dependencies**: [5.1]
**Estimated Hours**: 2-3
**Implementation Details**:
- Implement metadata extraction logic in scanner.py
- Check for explicit 'name' class attribute first
- Implement kebab-case conversion fallback (ReadFileNode → read-file)
- Extract raw docstring without parsing
- Create ~/.pflow directory if it doesn't exist
- Implement JSON serialization with proper formatting
- Handle file permissions and I/O errors gracefully

**Test Requirements**:
- Test name extraction (both explicit and kebab-case)
- Test metadata completeness
- Test JSON persistence and loading
- Test ~/.pflow directory creation
- Test error handling for file operations

### Subtask 3: Add comprehensive tests and edge case handling
**Description**: Create a comprehensive test suite covering all scanner functionality, edge cases (no docstring, multiple inheritance, abstract classes), and integration scenarios. Ensure robust error handling throughout.
**Dependencies**: [5.2]
**Estimated Hours**: 2-3
**Implementation Details**:
- Create test fixtures with various node types
- Test scanner with real and mock node files
- Test BaseNode vs Node inheritance detection
- Test handling of __pycache__ and non-Python files
- Test circular imports and broken modules
- Add proper logging for debugging
- Document all security considerations

**Test Requirements**:
- 100% code coverage for scanner.py
- Edge cases: empty files, syntax errors, missing BaseNode
- Performance tests with many files
- Integration test with real node discovery

## Relevant pflow Documentation

### Core Documentation
- `architecture/core-concepts/registry.md` - Complete registry system design
  - Relevance: Defines the registry architecture and storage format
  - Key concepts: Metadata-only storage, dynamic imports, JSON persistence
  - Applies to subtasks: All subtasks, especially 2 for storage format

- `architecture/implementation-details/metadata-extraction.md` - Metadata extraction specifications
  - Relevance: Details what metadata to extract and how
  - Key concepts: Basic vs detailed extraction (Task 5 does basic only)
  - Applies to subtasks: Subtask 2 for extraction logic

### Architecture Documentation
- `architecture/architecture/components.md` - MVP component specifications
  - Critical for: Understanding MVP scope limitations
  - Must follow: Only scan package nodes, no user directories in MVP

## Relevant PocketFlow Documentation

### Framework Core
- `pocketflow/__init__.py` - BaseNode class definition
  - Pattern: BaseNode is the fundamental class to detect
  - Usage: Understanding the class hierarchy for proper inheritance detection
  - Critical: Must detect BaseNode, NOT Node subclasses

## Research References

### For All Subtasks:
- Apply patterns from `.taskmaster/tasks/task_5/research/pocketflow-patterns.md`
  - Specifically: Module organization pattern for efficient scanning
  - Key insight: Validate single-purpose design during discovery (future enhancement)

### For Subtask 1:
- Reference: `.taskmaster/tasks/task_5/research/implementation-specification.md`
  - Key insight: Security note about importlib executing code
  - Implementation: Add clear comment in code about security implications

### For Subtask 2:
- Reference: `.taskmaster/tasks/task_5/research/registry-location-rationale.md`
  - Key insight: Use ~/.pflow/registry.json for Unix convention compliance
  - Implementation: Create directory structure as specified

## Key Architectural Considerations
- Registry stores metadata ONLY, not class references
- Components using registry must perform their own dynamic imports
- MVP scope: Only scan src/pflow/nodes/, no user directories
- Security: importlib executes code on import - document clearly
- Future compatibility: Design for easy extension to user/system nodes

## Dependencies Between Subtasks
- Subtask 2 requires Subtask 1 because it needs the scanner function to extract metadata
- Subtask 3 requires Subtask 2 to test the complete system including persistence

## Success Criteria
- [ ] Scanner correctly identifies all BaseNode subclasses
- [ ] Test node created and discovered successfully
- [ ] Metadata extraction includes all required fields
- [ ] Registry persists to ~/.pflow/registry.json with proper format
- [ ] Comprehensive test coverage including edge cases
- [ ] Clear documentation of security considerations
- [ ] Clean integration points for downstream tasks

## Special Instructions for Expansion
- Each subtask should be self-contained but build on previous work
- Ensure subtask descriptions include specific file paths to create/modify
- Reference the research files for implementation patterns
- Include test-as-you-go approach in each subtask
- Focus on MVP scope - don't over-engineer for future features
- Make sure each subtask explicitly mentions BaseNode (not Node) inheritance

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. It contains comprehensive context including task requirements, architectural decisions, documentation references, and research insights to enable intelligent subtask generation.
