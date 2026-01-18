# Pydantic vs JSONSchema Decision for pflow IR Validation

**Date**: 2025-07-15
**Context**: Task 17 - Natural Language Planner Implementation
**Decision**: Keep JSONSchema for IR validation, selectively add Pydantic for planner output

## Executive Summary

After analyzing the pflow codebase, we recommend **keeping the current JSONSchema-based validation** for IR documents while selectively introducing Pydantic only where it provides immediate value - specifically for the planner's IR generation in Task 17.

## Current Implementation Analysis

### What We Have Now

The project currently uses a well-designed JSONSchema approach in `src/pflow/core/ir_schema.py`:

```python
# Current implementation
FLOW_IR_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "ir_version": {...},
        "nodes": {...},
        "edges": {...},
        # ... other properties
    },
    "required": ["ir_version", "nodes"],
}

def validate_ir(data: Union[dict[str, Any], str]) -> None:
    """Validate workflow IR against the schema."""
    # Uses jsonschema Draft7Validator
    # Provides custom error messages with paths and suggestions
```

### Key Strengths of Current Approach

1. **Purpose-Built for JSON**: IR is fundamentally a JSON format, and JSONSchema is the industry standard for JSON validation
2. **Excellent Error Messages**: Custom `ValidationError` class provides:
   - Exact error location (e.g., `nodes[0].type`)
   - Helpful suggestions for fixes
   - Clear error messages
3. **Lightweight**: No object instantiation overhead, just validation
4. **Language Agnostic**: Schema can be shared with non-Python tools
5. **Well-Tested**: Comprehensive test suite in `tests/test_core/`

## Why Not Pydantic for IR Validation?

### 1. **Conceptual Mismatch**

IR is a **data transfer format**, not an application data model:
- It's meant to be serialized/deserialized
- It's validated at boundaries (input/output)
- It doesn't need methods or computed properties
- It's essentially a JSON document specification

### 2. **Duplication Without Benefit**

Using Pydantic would mean maintaining two representations:

```python
# Would need to duplicate the schema in Pydantic
class NodeIR(BaseModel):
    id: str
    type: str
    params: dict = {}

class FlowIR(BaseModel):
    ir_version: str
    nodes: List[NodeIR]
    edges: List[EdgeIR] = []
    # ... duplicating all the schema rules
```

This violates DRY principles without adding value.

### 3. **Performance Considerations**

Current flow:
```python
validate_ir(ir_dict)  # Direct validation
```

With Pydantic:
```python
flow_ir = FlowIR.parse_obj(ir_dict)  # Object creation
validated_dict = flow_ir.dict()      # Back to dict for compilation
```

The extra object creation/destruction adds overhead without benefit.

### 4. **Integration Complexity**

Current system is already integrated:
- CLI uses `validate_ir()` directly
- Compiler expects dict format
- Tests use dict format
- Examples are JSON files

Changing to Pydantic would require updating all these touchpoints.

## Where Pydantic DOES Make Sense

### 1. **Immediate: Planner Output Generation (Task 17)**

Add a minimal Pydantic model for the planner to generate valid IR:

```python
# src/pflow/planning/ir_models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class NodeIR(BaseModel):
    """Node representation for IR generation."""
    id: str = Field(..., pattern="^[a-zA-Z0-9_-]+$")
    type: str = Field(..., description="Node type from registry")
    params: Dict[str, Any] = Field(default_factory=dict)

class EdgeIR(BaseModel):
    """Edge representation for IR generation."""
    from_node: str = Field(..., alias="from")
    to_node: str = Field(..., alias="to")
    action: str = "default"

class FlowIR(BaseModel):
    """Flow IR for planner output generation."""
    ir_version: str = "0.1.0"
    nodes: List[NodeIR]
    edges: List[EdgeIR] = Field(default_factory=list)
    start_node: Optional[str] = None
    mappings: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dict for validation with existing schema."""
        return self.model_dump(by_alias=True, exclude_none=True)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return self.model_dump_json(by_alias=True, exclude_none=True, indent=2)
```

This helps the planner generate structurally valid IR with type hints and IDE support.

### 2. **Future: Node Metadata (Post-MVP)**

The project already plans this in `docs/future-version/typed-node-interfaces.md`:
- Node interfaces with typed inputs/outputs
- Runtime validation of node data
- Better developer experience

### 3. **Future: CLI Complex Parameters (Post-MVP)**

For complex CLI commands with many options:
```python
class PlanCommand(BaseModel):
    """Validated planning command parameters."""
    prompt: str
    max_nodes: int = 10
    allow_unsafe: bool = False
    output_format: Literal["json", "yaml"] = "json"
```

### 4. **Future: Configuration Files (Post-MVP)**

For user configuration and settings:
```python
class PflowConfig(BaseModel):
    """User configuration with validation."""
    registry_path: Path
    cache_dir: Optional[Path]
    llm_provider: str
    api_keys: Dict[str, SecretStr]
```

## Implementation Timeline

### MVP (Now)
1. **Keep JSONSchema** for IR validation - it works perfectly
2. **Add minimal Pydantic** for planner output generation only
3. **Uncomment pydantic** in `pyproject.toml` when adding planner models

### Post-MVP Phases

**Phase 1 (v1.1)** - Metadata Enhancement
- Add Pydantic for node metadata extraction
- Type-safe registry operations
- Keep JSONSchema for IR validation

**Phase 2 (v1.2)** - CLI Enhancement
- Pydantic for complex CLI commands
- Configuration file validation
- Settings management

**Phase 3 (v2.0)** - Full Type System
- Implement typed node interfaces (already planned)
- Runtime type validation for node execution
- Enhanced IDE support

## Code Examples

### Current JSONSchema Approach (Keep This)

```python
# Simple, effective validation
try:
    validate_ir(workflow_dict)
except ValidationError as e:
    print(f"Error at {e.path}: {e.message}")
    if e.suggestion:
        print(f"Suggestion: {e.suggestion}")
```

### Proposed Planner Integration (Add This)

```python
# In the planner implementation
def generate_workflow_ir(nodes: List[NodeSpec]) -> dict:
    """Generate valid IR using Pydantic for structure."""
    flow = FlowIR(
        nodes=[
            NodeIR(id=f"node_{i}", type=spec.type, params=spec.params)
            for i, spec in enumerate(nodes)
        ],
        edges=[
            EdgeIR(from_node=f"node_{i}", to_node=f"node_{i+1}")
            for i in range(len(nodes)-1)
        ]
    )

    # Convert to dict and validate with existing schema
    ir_dict = flow.to_dict()
    validate_ir(ir_dict)  # Still use JSONSchema for validation
    return ir_dict
```

## Migration Strategy

### If We Were to Switch (Not Recommended)

Here's what it would take to switch to Pydantic everywhere:

1. **Define all models** (~500 lines of code)
2. **Update validation** in 5+ files
3. **Change tests** - 50+ test cases
4. **Update examples** - All JSON examples would need companion Python
5. **Modify compiler** - Accept Pydantic models
6. **Update documentation** - Schema docs would need rewriting

**Estimated effort**: 2-3 days of work for marginal benefit

### Recommended Approach

1. **Today**: Add Pydantic models only for planner output
2. **Monitor**: See if this limited use provides value
3. **Post-MVP**: Gradually adopt where it makes sense
4. **Never**: Don't replace JSONSchema for IR validation

## Decision Rationale

### Why JSONSchema is Right for IR

1. **It's JSON validation for JSON data** - Perfect tool for the job
2. **Zero overhead** - No object creation, just validation
3. **Industry standard** - Well understood, documented
4. **Shareable** - Can be used by any language/tool
5. **Already working** - Current implementation is excellent

### Why Pydantic is Right for Other Uses

1. **Python objects** - When you need actual objects with methods
2. **Type safety** - For application logic, not data formats
3. **Developer experience** - IDE support for Python code
4. **Complex validation** - Business logic beyond structure

## Conclusion

The current JSONSchema implementation in `src/pflow/core/ir_schema.py` is well-designed and perfectly suited for its purpose. Adding Pydantic would introduce complexity without clear benefits.

However, Pydantic makes sense for:
- **Immediate**: Planner output generation (Task 17)
- **Future**: Node interfaces, CLI parameters, configuration

This selective approach gives us the best of both worlds:
- JSONSchema for what it does best (validating JSON)
- Pydantic for what it does best (Python type safety)

## References

1. Current implementation: `src/pflow/core/ir_schema.py`
2. Current tests: `tests/test_core/test_ir_schema.py`
3. Future plans: `docs/future-version/typed-node-interfaces.md`
4. Examples: `examples/core/*.json`
5. Project deps: `pyproject.toml` (pydantic commented out)

## Decision

**Keep JSONSchema for IR validation**. Add Pydantic selectively where it provides clear value, starting with planner output generation in Task 17.
