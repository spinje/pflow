# Task #6: Define JSON IR Schema - Project Context Briefing

## Executive Summary

Task #6 involves creating JSON schema definitions for workflow intermediate representation (IR) in `src/pflow/core/ir_schema.py`. This schema is the foundational data structure that enables pflow to represent workflows in a standardized, validated format that can be converted to executable pocketflow.Flow objects.

## Task Overview

**Task ID**: 6
**Title**: Define JSON IR schema
**Status**: pending
**Dependencies**: None (can start immediately)
**Priority**: high

**Description**: Create src/pflow/core/ir_schema.py with JSON Schema definitions. Define minimal IR structure: nodes[] with id, type, params; edges[] with from, to, action (default 'default'); start_node id; optional mappings{} for NodeAwareSharedStore proxy. Keep it simple - just enough to represent a workflow graph. Use standard JSON Schema for validation. Don't overengineer - we can extend later.

**Test Strategy**: Test schema validation with valid and invalid IR examples, verify all required fields, test edge cases. Write schema validation tests.

## Core Requirements

### 1. Minimal IR Structure

The IR must represent:
- **nodes[]**: Array of node objects with:
  - `id`: Unique identifier within the flow (e.g., "n1", "fetch-transcript")
  - `type`: Node type that maps to registry (e.g., "read-file", "llm")
  - `params`: Parameters for node behavior (NOT shared store keys)

- **edges[]**: Array of edge objects with:
  - `from`: Source node id
  - `to`: Target node id
  - `action`: Action string (default: "default") for conditional routing

- **start_node**: ID of the first node to execute

- **mappings** (optional): Proxy mappings for NodeAwareSharedStore
  - Used when nodes have incompatible interfaces
  - Maps node inputs/outputs to different shared store keys

### 2. Schema Governance

From `architecture/core-concepts/schemas.md`, the IR must include:

**Document Envelope**:
```json
{
  "$schema": "https://pflow.dev/schemas/flow-0.1.json",
  "ir_version": "0.1.0",
  "metadata": {
    "created": "2025-01-01T12:00:00Z",
    "description": "YouTube video summary pipeline",
    "planner_version": "1.0.0",
    "locked_nodes": {
      "core/yt-transcript": "1.0.0",
      "core/llm": "1.0.0"
    }
  },
  "nodes": [...],
  "edges": [...],
  "mappings": {...}
}
```

### 3. Node Object Schema

From the documentation, each node in the IR should follow:
```json
{
  "id": "fetch-transcript",
  "registry_id": "core/yt-transcript",  // Note: docs show this instead of "type"
  "version": "1.0.0",
  "params": {
    "language": "en",
    "timeout": 30
  },
  "execution": {
    "max_retries": 2,
    "use_cache": true,
    "wait": 1.0
  }
}
```

**Important Notes**:
- The task description mentions `type` but docs show `registry_id`
- `params` NEVER contains shared store keys or execution directives
- `execution` config is optional and only for `@flow_safe` nodes (post-MVP)
- Node version tracking might be deferred (Task 45 is deferred to v2.0)

### 4. Edge Schema

Edges support both simple sequential flow and action-based routing:
```json
// Simple sequential
{"from": "fetch-transcript", "to": "process-text"}

// Action-based
{"from": "fetch-transcript", "to": "error-handler", "action": "error"}
```

### 5. Mappings Schema (Optional)

For proxy pattern support:
```json
{
  "mappings": {
    "llm": {
      "input_mappings": {"prompt": "formatted_prompt"},
      "output_mappings": {"response": "article_summary"}
    }
  }
}
```

## Architectural Context

### How IR Fits in pflow Architecture

1. **Planner generates IR** (Task 17):
   - Takes natural language or CLI syntax
   - Produces JSON IR with template variables
   - References nodes by registry ID

2. **IR-to-Flow Converter** (Task 4) consumes IR:
   - Validates against schema
   - Resolves node references from registry
   - Creates pocketflow.Flow objects
   - Handles template variable resolution

3. **Execution Flow**:
   ```
   User Input → Planner → JSON IR → Validator → Converter → pocketflow.Flow → Execution
   ```

### Integration Points

1. **Registry Integration** (Task 5):
   - IR references nodes by registry ID
   - Registry provides metadata for validation
   - Node versions locked in IR for determinism

2. **Shared Store Pattern**:
   - IR doesn't directly reference shared store keys
   - Natural interfaces preserved through node metadata
   - Proxy mappings handle incompatibilities

3. **Template Variables** (from planner.md):
   - IR supports `$variable` placeholders
   - Runtime resolution from shared store
   - Enables dynamic workflow composition

## PocketFlow Relevance

While pocketflow provides the execution framework, the IR schema is purely a pflow concern:

1. **pocketflow provides**:
   - `BaseNode` and `Node` classes
   - `Flow` orchestration
   - Action-based routing (`-` operator)
   - Node chaining (`>>` operator)

2. **IR schema enables**:
   - Serializable workflow representation
   - Validation before execution
   - Version locking and determinism
   - Template-driven workflows

3. **Key Insight**: IR is the bridge between planner output and pocketflow execution. It's NOT a wrapper around pocketflow, but a data format that gets compiled TO pocketflow objects.

## Implementation Considerations

### 1. MVP Scope

For MVP, keep the schema minimal:
- Basic node/edge/start_node structure
- Simple parameter handling
- Optional mappings for proxy pattern
- Skip advanced features like execution config

### 2. Validation Strategy

Use Python's `jsonschema` library:
- Define schemas using JSON Schema Draft 7
- Validate IR during compilation
- Clear error messages for invalid IR
- Test with both valid and invalid examples

### 3. Extensibility

Design for future additions:
- Version field allows schema evolution
- Optional fields for v2.0 features
- Backward compatibility considerations

### 4. Key Design Decisions

Based on documentation analysis:

1. **Use `type` vs `registry_id`**: The task says `type` but docs show `registry_id`. Need to decide which to use for MVP.

2. **Version tracking**: Task 45 (node version tracking) is deferred to v2.0, so MVP might use simpler approach.

3. **Execution config**: Runtime features like retry/cache are post-MVP, so execution block might be optional.

4. **Schema location**: Task specifies `src/pflow/core/ir_schema.py` which aligns with creating a core module.

## Critical Documentation References

1. **Primary References**:
   - `architecture/core-concepts/schemas.md` - Complete schema specification
   - `architecture/features/planner.md#10.1` - Template-driven IR details
   - `architecture/architecture/pflow-pocketflow-integration-guide.md` - Integration patterns

2. **Supporting Documents**:
   - `architecture/core-concepts/shared-store.md` - Proxy pattern and mappings
   - `architecture/core-concepts/runtime.md` - Execution configuration (post-MVP)
   - `architecture/features/workflow-analysis.md` - Example workflows

3. **Implementation References**:
   - `architecture/implementation-details/metadata-extraction.md` - Node metadata format
   - `architecture/core-concepts/registry.md` - Registry structure and versioning

## Success Criteria

1. **Schema Definition**: Complete JSON Schema for workflow IR
2. **Validation**: Functions to validate IR against schema
3. **Examples**: Valid and invalid IR examples
4. **Tests**: Comprehensive test coverage
5. **Documentation**: Clear docstrings and comments
6. **Extensibility**: Design allows future enhancements

## Next Steps for Decomposition

When decomposing this task, consider:

1. **Schema Definition Phase**: Create the JSON Schema definitions
2. **Validation Implementation**: Build validation functions
3. **Example Creation**: Develop comprehensive examples
4. **Test Suite**: Write thorough tests
5. **Integration Preparation**: Ensure schema works with Task 4 (converter)

## Applied Knowledge from Previous Tasks

Based on the knowledge base analysis, these patterns and decisions should influence the IR schema implementation:

### Relevant Patterns

1. **Pattern: Graceful JSON Configuration Loading** (from patterns.md)
   - **Relevance**: IR will be loaded from JSON files
   - **Application**: Implement robust JSON loading with clear error messages for validation failures
   - **Impact**: Add comprehensive error handling in validation functions

2. **Pattern: Test-As-You-Go Development** (from patterns.md)
   - **Relevance**: Schema validation requires extensive testing
   - **Application**: Write tests alongside schema implementation, not as separate subtasks
   - **Impact**: Each implementation step includes immediate test coverage

3. **Pattern: Registry Storage Without Key Duplication** (from patterns.md)
   - **Relevance**: Nodes have IDs that shouldn't be duplicated
   - **Application**: Store nodes as array with 'id' field, not as dictionary keys
   - **Impact**: Allows ordered node lists and easier duplicate detection

### Architectural Decisions

1. **Decision: Integrated Testing Instead of Separate Test Tasks** (from decisions.md)
   - **Impact**: No separate testing subtask - validation tests are part of schema implementation
   - **Application**: Write schema tests in the same file/subtask as implementation

### Lessons from Similar Tasks

From Task 5 (Registry Implementation):
- Used standard JSON format (not custom serialization)
- Included minimal metadata for future compatibility
- Clear error messages for validation failures
- Started simple, then expanded based on needs

## Key Insights

1. **IR is Data, Not Code**: The schema defines a data format, not classes or execution logic
2. **Bridge Between Worlds**: IR connects natural language planning to deterministic execution
3. **Template Support Critical**: Must support `$variable` placeholders for dynamic workflows
4. **Keep It Simple**: MVP schema should be minimal but extensible
5. **Validation is Key**: Good error messages will save debugging time later
6. **Test Integration**: Tests should be written alongside implementation, not separately
7. **Error Clarity**: Validation errors should be user-friendly with clear guidance
