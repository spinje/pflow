# Knowledge Synthesis for Subtask 6.1

## Relevant Patterns from Previous Tasks

### Pattern: Python Package Module Structure
- **From**: Task 1 - CLI package setup
- **What**: Create `__init__.py` and main module files separately
- **Why Relevant**: We're creating `src/pflow/core/__init__.py` and `ir_schema.py`
- **Application**: Follow same pattern - minimal `__init__.py` exports, implementation in `ir_schema.py`

### Pattern: Test-As-You-Go Development
- **From**: All tasks (1, 2, 5)
- **What**: Write tests alongside implementation, not as separate tasks
- **Why Relevant**: Schema validation requires extensive testing
- **Application**: Create tests in same subtask as schema implementation

### Pattern: Graceful JSON Configuration Loading
- **From**: Task 5 - Registry implementation
- **What**: Use standard JSON format with proper error handling
- **Why Relevant**: IR will be loaded from JSON files
- **Application**: Implement robust JSON loading with clear validation error messages

### Pattern: Registry Storage Without Key Duplication
- **From**: Task 5 - Registry design
- **What**: Store items as array with 'id' field, not as dictionary keys
- **Why Relevant**: Nodes have IDs that shouldn't be duplicated
- **Application**: Define nodes as array of objects with 'id' field

### Pattern: Direct Validation Without Abstraction
- **From**: Task 2 - CLI validation
- **What**: Use basic types and manual validation for custom error messages
- **Why Relevant**: JSON Schema validation needs helpful error messages
- **Application**: Wrap jsonschema validation with custom error formatting

## Known Pitfalls to Avoid

### Pitfall: Over-Engineering for Future Features
- **From**: Task 1 & 5 - Initial over-complex approaches
- **Evidence**: Task 5 started with complex fixture system, simplified to tempfile
- **How to Avoid**: Start with minimal schema per task description, add only what's needed

### Pitfall: Inconsistent Naming Conventions
- **From**: Task 5 - Registry field naming
- **Evidence**: Confusion between 'registry_id' in docs vs 'type' in task
- **How to Avoid**: Follow task example explicitly ('type' field) as decided in research

### Pitfall: Missing Error Context
- **From**: Task 2 - Click validation
- **Evidence**: Default validators gave unhelpful errors
- **How to Avoid**: Provide path to invalid field and suggestions in error messages

## Established Conventions

### Convention: JSON Format for Data Exchange
- **From**: Task 5 - Registry persistence
- **Where Decided**: Registry uses JSON for serialization
- **Must Follow**: Use standard JSON Schema Draft 7, not custom formats

### Convention: Error Message Prefixing
- **From**: Task 2 - CLI errors
- **Where Decided**: All CLI errors prefixed with "cli:"
- **Must Follow**: Consider similar prefixing for schema validation errors

### Convention: Documentation as First-Class Concern
- **From**: All tasks
- **Where Decided**: Every module has comprehensive docstrings
- **Must Follow**: Include examples in docstrings, document all functions

## Codebase Evolution Context

### Package Structure Established
- **What Changed**: `src/pflow/` structure created with CLI and now core modules
- **When**: Tasks 1-2
- **Impact**: Follow established pattern - create `src/pflow/core/` package

### CLI Foundation Complete
- **What Changed**: Basic CLI with argument collection implemented
- **When**: Task 2
- **Impact**: IR schema will be consumed by planner via CLI context

### Registry System Operational
- **What Changed**: Node discovery and registry persistence complete
- **When**: Task 5
- **Impact**: IR schema 'type' field will reference registry node names

## Key Technical Insights

### From Research Files
- **Decision Made**: Use standard JSON Schema format (not Pydantic)
- **Decision Made**: Use 'type' field for nodes (not 'registry_id')
- **Decision Made**: Make start_node optional with default behavior
- **Decision Made**: Include action field in edges with "default" as default
- **Decision Made**: Keep template variables as simple strings (no special handling)

### From Project Context
- **Key Insight**: IR is pure data format, not wrapper classes
- **Key Insight**: IR bridges planner output to pocketflow execution
- **Key Insight**: Schema must support future extensions without breaking changes
- **Key Insight**: Validation should happen at IR creation, not execution

## Implementation Approach Summary

Based on accumulated knowledge:
1. Create minimal JSON Schema using Draft 7 format
2. Include only essential fields per MVP scope
3. Implement validation with helpful error messages
4. Write tests immediately alongside implementation
5. Follow established module structure patterns
6. Keep extensibility in mind without over-engineering
