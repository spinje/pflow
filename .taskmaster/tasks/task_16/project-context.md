# Project Context: Task 16 - Create Planning Context Builder

## Overview

Task 16 creates a critical bridge component between the node registry/metadata system and the LLM-based workflow planner. The context builder formats node metadata into LLM-optimized text that enables natural language planning.

## Task Domain Understanding

### Core Purpose
The context builder transforms technical node metadata into human-readable documentation that LLMs can understand and use to compose workflows. It's the "available tools reference" that the planner consults when building workflows from natural language requests.

### Key Components Involved

1. **Node Registry (Task 5)** - Provides basic node information:
   ```python
   {
       "module": "pflow.nodes.file.read_file",
       "class_name": "ReadFileNode",
       "name": "read-file",
       "docstring": "...",  # Full unparsed docstring
       "file_path": "/path/to/file.py"
   }
   ```

2. **Metadata Extractor (Task 7)** - Extracts structured metadata:
   ```python
   {
       'description': 'Read content from a file',
       'inputs': ['file_path', 'encoding'],
       'outputs': ['content', 'error'],
       'params': ['file_path', 'encoding'],
       'actions': ['default', 'error']
   }
   ```

3. **Workflow Planner (Task 17)** - Consumes the formatted context to build workflows

### Critical Design Pattern: Shared Store vs Parameters

**Key Insight**: ALL shared store inputs automatically work as parameter fallbacks in pflow's design.

```python
# In every node's prep() method:
file_path = shared.get("file_path") or self.params.get("file_path")
```

This means:
- Data flows primarily through shared store (e.g., `shared["file_path"]`)
- Parameters provide fallback values when shared store keys are absent
- Configuration parameters (e.g., `append`, `overwrite`) are params-only

**Implementation Impact**: Only show configuration parameters in the context, not data parameters that duplicate inputs.

## Essential Documentation References

### Primary References
1. **`architecture/features/planner.md` Section 6.1** - Template string composition and how the planner uses node context
2. **`architecture/implementation-details/metadata-extraction.md`** - Contains example PlannerContextBuilder implementation (lines 784-860)
3. **`architecture/core-concepts/shared-store.md`** - Critical for understanding parameter classification

### PocketFlow Context
While the context builder itself is NOT a PocketFlow component, it must understand:
- How nodes use the shared store pattern for data flow
- The distinction between data inputs and configuration parameters
- How template variables enable workflow composition

## Architectural Context

### Integration Points
1. **Input**: Receives registry metadata dict from `Registry.load()`
2. **Processing**: Uses `PflowMetadataExtractor` to get detailed node metadata
3. **Output**: Returns formatted markdown text for LLM consumption

### Expected Output Format
```markdown
## File Operations

### read-file
Reads content from a file and adds line numbers for display.

**Inputs**: `file_path`, `encoding`
**Outputs**: `content` (success), `error` (failure)
**Parameters**: `max_lines`  # Only configuration params shown

### write-file
Writes content to a file.

**Inputs**: `content`, `file_path`
**Outputs**: `written` (success), `error` (failure)
**Parameters**: `append`, `create_dirs`  # Only exclusive params
```

## Applied Knowledge from Previous Tasks

### From Task 7 (Metadata Extraction)
- Use phased implementation approach
- Implement forgiving parser design - extract what's available
- Structure logging with phase tracking
- Keep output format simple for consumers

### From Task 5 (Registry)
- Registry stores node name as dict key, not in value
- Use dynamic import pattern via `import_node_class()`
- Handle import failures gracefully with logging

### From Task 11 (File Nodes)
- Truthiness-safe parameter handling for empty strings
- Clear documentation of shared store vs params distinction

### Error Handling Patterns
- Log import failures but continue processing
- Skip nodes without valid interface sections
- Use component-specific error prefixes (e.g., "context:")

## Cookbook Patterns and Examples

### Relevant Patterns Identified
1. **Phased Processing** - Load → Extract → Format → Organize
2. **Defensive Metadata Handling** - Graceful degradation for incomplete data
3. **Category-based Organization** - Group nodes by operation type

### Key Implementation Strategies
1. Include only production nodes with valid Interface sections
2. Skip nodes that fail to import (with logging)
3. Group nodes by directory/category
4. Show only configuration parameters (not data parameters)
5. Skip nodes with missing metadata entirely
6. No size limits initially - add monitoring
7. Receive pre-loaded registry dict as specified

## Critical Requirements

1. **Function Signature**: `build_context(registry_metadata: dict[str, dict[str, Any]]) -> str`
2. **Must clearly distinguish** between shared store inputs and configuration parameters
3. **LLM-optimized format** - Simple markdown, not complex JSON
4. **Defensive programming** - Handle missing/malformed metadata gracefully
5. **Enable template composition** - Support the planner's template variable system

## Key Decisions and Trade-offs

### Decision: Parameter Section Redundancy
**Choice**: Show only configuration parameters, not data parameters
**Rationale**: Reduces redundancy since ALL inputs can be params too
**Implementation**: Filter out params that are also inputs

### Decision: Node Inclusion Criteria
**Choice**: Include only production nodes with valid Interface sections
**Rationale**: Clean context for LLM, avoid test/utility nodes

### Decision: Output Format
**Choice**: Grouped markdown by category with consistent headers
**Rationale**: Logical grouping aids LLM comprehension

## Test Considerations

1. Test with real registry data from Task 5
2. Verify metadata extraction integration with Task 7
3. Test format readability for LLM consumption
4. Handle edge cases: missing metadata, import failures
5. Verify category grouping logic
6. Test parameter filtering (exclusive params only)

## Success Criteria

1. LLM can understand available nodes and their capabilities
2. Clear distinction between data flow (shared store) and configuration (params)
3. Graceful handling of incomplete or missing metadata
4. Format supports template-based workflow composition
5. Integration with existing registry and metadata systems
