# Project Context for Task 14: Implement type, structure, and semantic documentation for all Interface components

**File Location**: `.taskmaster/tasks/task_14/project-context.md`

*Created by sub-agents on: 2025-07-16*
*Purpose: Provide focused project understanding for ALL subtasks of this task*

## Task Domain Overview

Task 14 enhances pflow's metadata extraction system to make data structures visible to the planner. Currently, the planner can only see output key names like `["issue_data", "error"]` but cannot generate valid proxy mapping paths like `issue_data.user.login` because it doesn't know that `issue_data` contains nested structures. This task adds type annotations, structure documentation, and semantic descriptions to all Interface components (Reads, Writes, Params), enabling the planner to understand and utilize complex data flows.

## Relevant Components

### PflowMetadataExtractor
- **Purpose**: Extracts metadata from node docstrings for registry storage
- **Responsibilities**: Parse Interface sections, validate node classes, extract description
- **Key Files**: `src/pflow/registry/metadata_extractor.py`
- **How it works**: Uses regex patterns to parse Interface sections, extracts simple lists of keys, stores as JSON metadata

### Context Builder
- **Purpose**: Formats node metadata for LLM consumption during planning
- **Responsibilities**: Import nodes dynamically, extract metadata, group by category, format for readability
- **Key Files**: `src/pflow/planning/context_builder.py`
- **How it works**: Reads registry metadata, imports node classes, formats into markdown with 50KB output limit

### Node Registry
- **Purpose**: Manages node discovery, storage, and versioning
- **Responsibilities**: Store node files and metadata, support queries, handle versions
- **Key Files**: `src/pflow/registry/registry.py`, `src/pflow/registry/scanner.py`
- **Interactions**: Metadata extractor runs during node installation, context builder reads from registry

## Core Concepts

### Interface Section
- **Definition**: The docstring section that documents a node's inputs, outputs, parameters, and actions
- **Why it matters for this task**: This is what we're enhancing with type and structure information
- **Key terminology**: Reads (inputs from shared store), Writes (outputs to shared store), Params (configuration), Actions (transitions)

### Type Annotations
- **Definition**: Adding Python type information to Interface components (e.g., `shared["key"]: str`)
- **Why it matters for this task**: Enables the planner to understand data types for valid operations
- **Relationships**: Types enable structure documentation for complex types like dict and list

### Structure Documentation
- **Definition**: Documenting nested fields within complex types using indentation
- **Why it matters for this task**: Allows planner to generate paths like `data.user.login`
- **Example**: A dict output can document its internal structure with indented fields

### Semantic Descriptions
- **Definition**: Human-readable explanations using `# comments` to clarify meaning
- **Why it matters for this task**: Helps planner understand what fields represent, not just their types
- **Example**: `state: str # Issue state (typically "open" or "closed")`

## Architectural Context

### Where This Fits
The metadata extraction system sits between node definitions and the planning system:
1. Nodes define their interfaces in docstrings
2. Metadata extractor parses these during registry operations
3. Registry stores the extracted metadata
4. Context builder reads metadata for planner consumption
5. Planner uses this information to generate workflows with valid proxy mappings

### Data Flow
```
Node Docstring → Metadata Extractor → Registry Storage → Context Builder → Planner LLM
```

### Dependencies
- **Upstream**: Node docstring format conventions, PocketFlow BaseNode validation
- **Downstream**: Registry storage format, context builder display, planner proxy mapping generation

## Constraints and Conventions

### Technical Constraints
- **Backward Compatibility**: MUST support existing simple format without types
- **No eval()**: Cannot use eval() or ast.literal_eval() for security reasons
- **50KB Context Limit**: Structure information counts against context builder output limit
- **Startup Performance**: Parsing happens at registry scan time, must be efficient

### Project Conventions
- **Interface Format**: All nodes use single-line format: `Writes: shared["key1"], shared["key2"]`
- **Metadata Storage**: Stored as JSON alongside node files in registry
- **Error Handling**: Graceful degradation - extract what's available, log warnings
- **Testing**: Use real node imports, not mocks; test with actual codebase files

### Design Decisions
- **Writes = Outputs**: The Interface section uses "Writes:" to document outputs (verified in codebase)
- **No Separate Outputs Section**: Everything stays in the Interface section
- **Indentation-Based Parsing**: Chosen over JSON-like syntax for readability and simplicity

## Applied Knowledge from Previous Tasks

### Relevant Patterns
- **Pattern: Phased Implementation Approach** (from Task 7)
  - Why relevant: Complex parsing benefits from clear phases
  - How to apply: Break into validation → extraction → formatting phases
  - Example usage: Validate Interface format, extract types, format for storage

- **Pattern: Shared Store Inputs as Automatic Parameter Fallbacks** (from knowledge base)
  - Why relevant: Affects how we document and extract params
  - How to apply: Filter params that are already in inputs (exclusive params only)
  - Example usage: `exclusive_params = [p for p in params if p not in inputs]`

- **Pattern: Test-As-You-Go Development** (from knowledge base)
  - Why relevant: Complex parser needs immediate validation
  - How to apply: Write tests for each parser component as implemented
  - Example usage: Test type parsing, structure parsing, backward compatibility

### Known Pitfalls to Avoid
- **Pitfall: Making Assumptions About Code Structure** (from knowledge base)
  - Risk for this task: Wrong field names break registry integration
  - Mitigation strategy: Verify actual field names (it's "docstring" not "description")
  - Warning signs: Integration tests failing despite unit tests passing

- **Pitfall: Regex Complexity Explosion** (from Task 7 insights)
  - Risk for this task: Nested structure parsing with regex becomes unmaintainable
  - Mitigation strategy: Use indentation-based parsing instead of complex regex
  - Warning signs: Regex patterns becoming unreadable or requiring many edge cases

### Architectural Constraints
- **Decision: Consistent Format for Parsing** (from knowledge base)
  - Impact on this task: Interface format must be strictly defined
  - Required compliance: All nodes must follow the same enhanced format

## Decomposition Guidance
Based on accumulated knowledge:
- Consider using Foundation-Integration-Polish pattern (worked well for Tasks 7 and 16)
- Structure subtasks to build incrementally with clear dependencies
- Ensure parser handles both old and new formats from the start
- Test with real components from the codebase, not theoretical examples

## Key Documentation References

### Essential pflow Documentation
- `docs/implementation-details/metadata-extraction.md` - Comprehensive extraction infrastructure specification
- `docs/core-concepts/schemas.md` - Node metadata schema (sections 2.1-2.4)
- `docs/core-concepts/shared-store.md` - Natural interface patterns and proxy mapping needs
- `docs/core-concepts/registry.md` - Section 4.3 on metadata generation

### Task-Specific Documentation
- `.taskmaster/tasks/task_14/task-14-complete-specification.md` - Detailed requirements and format specification
- `.taskmaster/tasks/task_14/14_ambiguities.md` - All resolved design decisions
- `.taskmaster/tasks/task_14/implementation-recommendations.md` - Technical recommendations

*These references should be included in the decomposition plan to guide subtask generation.*

## Key Questions This Context Answers

1. **What am I building/modifying?** Enhancing the metadata extractor to parse types, structures, and descriptions from node Interface sections, updating all nodes to use the new format, and minimally updating the context builder to display this information.

2. **How does it fit in the system?** It bridges the gap between node documentation and planner understanding, enabling the planner to generate valid proxy mapping paths for complex data structures.

3. **What rules must I follow?** Maintain backward compatibility, use indentation-based parsing, store types directly in arrays as objects, no eval(), test with real components.

4. **What existing code should I study?** `metadata_extractor.py` (especially `_extract_list_section`), `context_builder.py` (`_format_node_section`), existing node docstrings in `src/pflow/nodes/`.

## What This Document Does NOT Cover

- Implementation details of the parser algorithm
- Specific regex patterns or parsing logic
- PocketFlow framework usage (not relevant for this task)
- Future enhancements beyond MVP scope

---

*This briefing was synthesized from project documentation to provide exactly the context needed for this task, without overwhelming detail.*

**Note**: This document is created ONCE at the task level and shared by ALL subtasks. It is created by the first subtask and read by all subsequent subtasks.
