# Evaluation for Subtask 6.1

## Ambiguities Found

### 1. Schema File Structure vs Python Module - Severity: 3/5

**Description**: The task mentions creating `ir_schema.py` as a Python module, but the documentation shows JSON Schema format. Should we create Python code that contains JSON Schema definitions, or actual .json schema files?

**Why this matters**: Affects how the schema is distributed, validated, and used by other components.

**Options**:
- [x] **Option A**: Python module containing schema as dict/JSON string
  - Pros: Single file as specified, easier to import and use
  - Cons: Less standard than separate .json files
  - Similar to: Task 5 Registry stores JSON in Python code

- [ ] **Option B**: Separate .json schema files
  - Pros: Standard approach, can be validated by tools
  - Cons: Not what task specifies
  - Risk: Would require changing task specification

**Recommendation**: Option A - Create `ir_schema.py` containing schema definitions as Python dictionaries, following the task specification and similar to how Registry was implemented.

### 2. Minimal Envelope vs Full Metadata - Severity: 2/5

**Description**: Task says "minimal IR structure" but documentation shows extensive metadata envelope. How minimal should we be?

**Why this matters**: Affects complexity and future extensibility.

**Options**:
- [x] **Option A**: Minimal envelope with just version
  - Include: `ir_version`, `nodes`, `edges`, optional `start_node`, optional `mappings`
  - Pros: Follows "don't overengineer" directive
  - Cons: Less metadata than docs show
  - Similar to: Registry's minimal metadata approach

- [ ] **Option B**: Full envelope from documentation
  - Include: `$schema`, `ir_version`, `metadata` object, etc.
  - Pros: Matches documentation exactly
  - Cons: More complex than MVP needs
  - Risk: Over-engineering for current needs

**Recommendation**: Option A - Minimal envelope per research decisions. Can extend later.

### 3. jsonschema Dependency Addition - Severity: 1/5

**Description**: jsonschema library is not in current dependencies but is needed for validation.

**Why this matters**: Need to add dependency to pyproject.toml.

**Options**:
- [x] **Option A**: Add jsonschema to dependencies
  - Pros: Standard library for JSON Schema validation
  - Cons: New dependency
  - Implementation: Add to pyproject.toml

**Recommendation**: Option A - Add jsonschema as it's the standard tool for this purpose.

## Conflicts with Existing Code/Decisions

### 1. No Conflicts Found

The codebase has an empty `src/pflow/core/` directory ready for our implementation. No existing schema code to conflict with.

## Implementation Approaches Considered

### Approach 1: Research-suggested minimal schema (from task-6-ir-schema-decisions.md)
- Description: Use decisions from research file - standard JSON Schema, 'type' field, optional start_node
- Pros: Decisions already analyzed and made
- Cons: None identified
- Decision: **Selected** - Research provides clear, reasoned decisions

### Approach 2: PocketFlow-inspired Pydantic models (from cookbook examples)
- Description: Use Pydantic models like in pocketflow-a2a example
- Pros: Type safety, automatic validation
- Cons: Not JSON Schema format, adds complexity
- Decision: **Rejected** - Research already decided on standard JSON Schema

### Approach 3: Direct JSON Schema in separate files
- Description: Create .json files with schemas
- Pros: Most standard approach
- Cons: Not what task specifies
- Decision: **Rejected** - Task clearly wants Python module

## Test Strategy Decisions

Based on patterns from previous tasks:

1. **Unit Tests**: Test schema validation with valid/invalid examples
2. **Integration Tests**: Test loading IR from JSON strings
3. **Error Message Tests**: Verify helpful validation errors
4. **Edge Cases**: Empty nodes, self-referential edges, missing IDs

## No User Decisions Required

All ambiguities have clear recommendations based on:
- Task specification
- Research decisions already made
- Established patterns from previous tasks
- MVP scope constraints

The implementation path is clear and can proceed without user input.
