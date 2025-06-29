# PocketFlow Cookbook Patterns for Subtask 6.1

## Relevant Patterns Identified

### 1. pocketflow-a2a - Pydantic Validation Patterns
**Location**: `pocketflow/cookbook/pocketflow-a2a/common/types.py`

**What it demonstrates**:
- Comprehensive data validation using Pydantic BaseModel
- Cross-field validation with @model_validator
- Discriminated unions for polymorphic types
- Custom serialization with @field_serializer

**Why NOT applicable for our task**:
- We've decided to use JSON Schema, not Pydantic models
- This example is too complex for MVP scope
- Research decisions explicitly chose standard JSON Schema over Pydantic

### 2. pocketflow-structured-output - Simple Validation Pattern
**Location**: `pocketflow/cookbook/pocketflow-structured-output/main.py`

**What it demonstrates**:
- Safe YAML/JSON parsing with yaml.safe_load()
- Basic assertion-based validation
- Clear error messages for validation failures
- Type checking after parsing

**Partially applicable patterns**:
- Safe parsing approach (we'll use json.loads)
- Clear error messaging pattern
- Simple validation flow

## Patterns to Apply from PocketFlow Core

### From pocketflow/__init__.py
1. **Parameter Access Pattern**:
   - Nodes access params via `self.params` dictionary
   - This informs our schema: params should be an object/dict type

2. **Action-Based Routing**:
   - Nodes can return action strings for conditional flow
   - This confirms our edge 'action' field design

3. **Node Connection Pattern**:
   - Nodes connect via operators in code
   - In IR, this translates to edges array

## Validation Pattern to Implement

Based on the analysis, we should NOT directly copy any cookbook examples but instead:

1. **Use standard jsonschema library** (as decided in research)
2. **Follow Registry's JSON handling pattern** from Task 5
3. **Implement clear error messages** inspired by structured-output example
4. **Keep it simple** - no complex validation frameworks for MVP

## Key Takeaway

The cookbook examples show sophisticated validation approaches, but our task requires a simpler, standard JSON Schema approach. The main value from cookbook analysis is understanding:
- How nodes use parameters (as dict/object)
- How flows connect nodes (edges with actions)
- The importance of clear error messages

We'll implement validation using jsonschema library with custom error formatting, not Pydantic or complex patterns from the cookbook.
