# Task 11 Decomposition Plan

**File Location**: `.taskmaster/tasks/task_11/decomposition-plan.md`

*Created on: 2025-06-29*
*Purpose: Comprehensive prompt for task-master expand command*

## Task Overview
Implement five basic file I/O nodes for the pflow system (read-file, write-file, copy-file, move-file, delete-file) that enable file manipulation through the PocketFlow framework. These nodes will serve as fundamental building blocks for file-based workflows, following the simple node architecture pattern with natural shared store interfaces.

## Decomposition Pattern
**Pattern**: Foundation-Integration-Polish

**Reasoning**: This pattern works well for implementing multiple related components. We'll start with the foundational read/write operations, then integrate the more complex file manipulation operations (copy/move/delete), and finally polish with comprehensive error handling and edge case testing.

## Complexity Analysis
- **Complexity Score**: 4/10
- **Reasoning**: While conceptually simple (basic file I/O), implementing 5 nodes with proper error handling, safety checks, and comprehensive tests requires moderate effort
- **Total Subtasks**: 3

## Planned Subtasks

### Subtask 1: Implement foundational read-file and write-file nodes
**Description**: Create the core file I/O nodes (read-file and write-file) in src/pflow/nodes/file/, establishing the patterns and conventions that will be used by all file nodes. These foundational nodes will handle the most common file operations and set the standard for error handling and interface design.

**Dependencies**: None
**Estimated Hours**: 2-3

**Implementation Details**:
- Create `src/pflow/nodes/file/` directory structure
- Implement `read_file.py` with ReadFileNode class inheriting from pocketflow.Node
  - Use `shared["file_path"]` as input, write to `shared["content"]`
  - Support encoding parameter (default UTF-8)
  - Add line numbers when displaying content (following Tutorial-Cursor pattern)
  - Graceful handling of missing files
- Implement `write_file.py` with WriteFileNode class
  - Read from `shared["content"]` and `shared["file_path"]`
  - Create directories automatically with `os.makedirs(exist_ok=True)`
  - Support append mode via params
  - Validate content before writing
- Follow node lifecycle: prep (validate inputs) → exec (file operation) → post (update shared store)
- Use the error handling pattern: return tuples (result, success) from exec
- Create `__init__.py` to expose nodes for registry discovery

**Test Requirements**:
- Test successful read/write operations
- Test missing file handling for read
- Test directory creation for write
- Test various encodings
- Test empty files
- Test fail-fast behavior on missing inputs
- Test integration with shared store

### Subtask 2: Implement file manipulation nodes (copy, move, delete)
**Description**: Build on the foundation from subtask 1 to implement the remaining file manipulation nodes (copy-file, move-file, delete-file), following established patterns and adding appropriate safety checks for destructive operations.

**Dependencies**: [11.1]
**Estimated Hours**: 2-3

**Implementation Details**:
- Implement `copy_file.py` with CopyFileNode class
  - Use `shared["source_path"]` and `shared["dest_path"]`
  - Verify source exists before operation
  - Create destination directory if needed
  - Preserve file attributes using shutil
- Implement `move_file.py` with MoveFileNode class
  - Use same interface as copy
  - Prefer atomic operation when possible (os.rename)
  - Fallback to copy+delete for cross-filesystem moves
  - Add safety check for overwriting existing files
- Implement `delete_file.py` with DeleteFileNode class
  - Use `shared["file_path"]` input
  - Add safety parameter to prevent accidental deletions
  - Clear error messages for missing files
  - Log destructive operations
- All nodes follow the same lifecycle pattern established in subtask 1
- Consistent error handling and shared store conventions

**Test Requirements**:
- Test successful copy/move/delete operations
- Test safety checks and confirmations
- Test cross-filesystem operations
- Test permission errors
- Test operations on non-existent files
- Test preservation of file attributes
- Test atomic vs non-atomic move operations

### Subtask 3: Polish with comprehensive error handling and edge cases
**Description**: Enhance all file nodes with robust error handling, comprehensive edge case coverage, and polished user experience. Add any missing tests and ensure all nodes handle permission errors, special characters, and large files gracefully.

**Dependencies**: [11.2]
**Estimated Hours**: 2

**Implementation Details**:
- Add comprehensive error handling across all nodes:
  - Permission denied errors with helpful messages
  - Disk space errors
  - Invalid path characters
  - Symbolic link handling
  - Network drive considerations
- Enhance logging with structured metadata:
  - Use phase tracking (reading, writing, validating)
  - Include file sizes and paths
  - Avoid reserved field names (use "file_path" not "filename")
- Add performance considerations:
  - Handle large files efficiently
  - Add progress indicators for long operations
  - Implement reasonable timeouts
- Polish user experience:
  - Clear, actionable error messages
  - Consistent action returns ("default" for success, "error" for failures)
  - Helpful docstrings with examples
- Create integration tests demonstrating node chaining
- Document all nodes in module docstrings

**Test Requirements**:
- Test permission error scenarios
- Test with special characters in filenames
- Test symbolic links
- Test large file handling
- Test timeout scenarios
- Test full workflow integration
- Achieve comprehensive test coverage

## Relevant pflow Documentation

### Core Documentation
- `docs/features/simple-nodes.md` - Simple node architecture pattern
  - Relevance: Defines the single-responsibility pattern all nodes must follow
  - Key concepts: No internal routing, predictable interfaces, fail-fast behavior
  - Applies to subtasks: All subtasks must follow these patterns

- `docs/core-concepts/shared-store.md` - Shared store conventions and patterns
  - Relevance: Defines how nodes communicate through shared dictionary
  - Key concepts: Natural key naming, check shared first then params, template variables
  - Applies to subtasks: All subtasks for consistent interfaces

### Architecture Documentation
- `docs/architecture/components.md` - MVP component specifications
  - Critical for: Understanding which features belong in MVP vs future versions
  - Must follow: Synchronous execution only, no async/parallel features

## Relevant PocketFlow Documentation

### Framework Core
- `pocketflow/__init__.py` - BaseNode and Node class definitions
  - Pattern: Three-phase lifecycle (prep/exec/post)
  - Usage: All file nodes inherit from Node class for retry capabilities

- `pocketflow/docs/core_abstraction/node.md` - Detailed node lifecycle documentation
  - Pattern: Separation of data access (prep/post) from computation (exec)
  - Usage: All subtasks must implement proper lifecycle methods

### Communication Pattern
- `pocketflow/docs/core_abstraction/communication.md` - Inter-node communication
  - Pattern: All communication through shared store dictionary
  - Usage: Consistent key naming and data passing conventions

## Relevant PocketFlow Examples

### Cookbook Patterns
- `pocketflow/cookbook/Tutorial-Cursor/utils/` - Production-ready file utilities
  - Adaptation needed: Convert standalone functions to node lifecycle methods
  - Applies to: Subtask 1 for read/write patterns, Subtask 2 for file operations

- `pocketflow/cookbook/pocketflow-node/` - Basic node implementation pattern
  - Adaptation: Follow the structure for all file nodes
  - Applies to: All subtasks for consistent node structure

## Key Architectural Considerations
- All nodes must be discoverable by the registry scanner (comprehensive docstrings)
- Follow kebab-case naming convention (auto-converted from class names)
- Nodes are isolated units with no awareness of other nodes
- Use traditional Python file operations, not PocketFlow internally
- All conditional logic belongs at the flow level, not within nodes
- Include tests as part of implementation tasks, not separately

## Dependencies Between Subtasks
- 11.2 requires 11.1 because it builds on established patterns and conventions
- 11.3 requires 11.2 because it polishes all five implemented nodes

## Success Criteria
- [ ] All 5 file nodes implemented and functional
- [ ] Comprehensive error handling for all edge cases
- [ ] Natural shared store interfaces following conventions
- [ ] Complete test coverage with unit and integration tests
- [ ] Nodes discoverable by registry scanner
- [ ] Clear documentation and examples

## Special Instructions for Expansion
- Each subtask should create working, tested code - not just prototypes
- Follow the test-as-you-go pattern from previous tasks
- Reference specific documentation sections in implementation details
- Ensure safety checks are prominent for destructive operations
- Focus on user-friendly error messages and graceful failures
- All nodes should feel consistent and predictable to use

---

**Note**: This file will be passed directly to `task-master expand` as the prompt. Ensure it contains ALL context needed for intelligent subtask generation, including explicit references to project documentation, framework docs, and examples.
