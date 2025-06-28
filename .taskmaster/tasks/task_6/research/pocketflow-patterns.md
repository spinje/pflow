# PocketFlow Patterns for Task 6: JSON IR Schema

## Task Context

- **Goal**: Define JSON schema for workflow intermediate representation
- **Dependencies**: None (but influences all other tasks)
- **Constraints**: Schema must enforce deterministic execution patterns

## Core Patterns from Advanced Analysis

### Pattern: Structured Output with JSON Schema
**Found in**: All repositories use structured formats (though many prefer YAML for LLM)
**Why It Applies**: IR needs strict validation for reliability

```python
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Optional, Literal

class NodeSpec(BaseModel):
    """Single node in the workflow"""
    id: str = Field(..., description="Unique node identifier")
    type: str = Field(..., description="Node type from registry")
    params: Dict[str, Any] = Field(default_factory=dict, description="Node parameters")

    @validator('id')
    def validate_id_format(cls, v):
        """Ensure valid identifier"""
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("ID must be alphanumeric with - or _")
        return v

    @validator('type')
    def validate_node_type(cls, v):
        """Ensure kebab-case for consistency"""
        if not all(c.islower() or c in "-0-9" for c in v):
            raise ValueError("Node type must be lowercase kebab-case")
        return v

class EdgeSpec(BaseModel):
    """Connection between nodes"""
    from_node: str = Field(..., alias="from", description="Source node ID")
    to_node: str = Field(..., alias="to", description="Target node ID")
    action: str = Field(default="default", description="Action for conditional routing")

    class Config:
        allow_population_by_field_name = True

class MappingSpec(BaseModel):
    """Key mappings for proxy pattern (rarely needed)"""
    input_mappings: Dict[str, str] = Field(default_factory=dict)
    output_mappings: Dict[str, str] = Field(default_factory=dict)

    @validator('input_mappings', 'output_mappings')
    def validate_no_reserved_keys(cls, v):
        """Ensure no reserved keys in mappings"""
        reserved = {"stdin", "_metadata", "_trace", "_execution_id"}
        for key in v.keys():
            if key in reserved:
                raise ValueError(f"Cannot map reserved key: {key}")
        return v

class WorkflowIR(BaseModel):
    """Complete workflow intermediate representation"""
    ir_version: Literal["0.1.0"] = Field(default="0.1.0")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    nodes: List[NodeSpec] = Field(..., min_items=1)
    edges: List[EdgeSpec] = Field(default_factory=list)
    start_node: str = Field(..., description="ID of starting node")
    mappings: Dict[str, MappingSpec] = Field(
        default_factory=dict,
        description="Node ID -> mappings (only when natural keys insufficient)"
    )

    @validator('start_node')
    def validate_start_exists(cls, v, values):
        """Ensure start node exists"""
        if 'nodes' in values:
            node_ids = {n.id for n in values['nodes']}
            if v not in node_ids:
                raise ValueError(f"Start node '{v}' not found in nodes")
        return v

    @validator('edges')
    def validate_edges_reference_nodes(cls, v, values):
        """Ensure all edges reference existing nodes"""
        if 'nodes' in values:
            node_ids = {n.id for n in values['nodes']}
            for edge in v:
                if edge.from_node not in node_ids:
                    raise ValueError(f"Edge source '{edge.from_node}' not found")
                if edge.to_node not in node_ids:
                    raise ValueError(f"Edge target '{edge.to_node}' not found")
        return v
```

### Pattern: Template Variable Markers in Schema
**Found in**: Cold Email, Website Chatbot use template variables
**Why It Applies**: IR must preserve template variables for runtime resolution

```python
class TemplateString(str):
    """String that may contain template variables"""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        """Mark strings with template variables"""
        if isinstance(v, str) and "$" in v:
            # This is a template string
            return cls(v)
        return v

    def get_variables(self) -> List[str]:
        """Extract variable names"""
        import re
        # Match $var or ${var} syntax
        return re.findall(r'\$\{?(\w+)\}?', self)

# Update NodeSpec to handle templates
class NodeSpec(BaseModel):
    params: Dict[str, Union[Any, TemplateString]] = Field(default_factory=dict)

    def get_template_variables(self) -> List[str]:
        """Get all template variables in params"""
        variables = []
        for value in self.params.values():
            if isinstance(value, TemplateString):
                variables.extend(value.get_variables())
        return variables
```

### Pattern: Natural Key Documentation in Schema
**Found in**: Analysis showed natural keys prevent collisions
**Why It Applies**: Schema should encourage/document natural key usage

```python
class NodeInterface(BaseModel):
    """Documents node's shared store interface"""
    inputs: List[str] = Field(
        default_factory=list,
        description="Keys read from shared store"
    )
    outputs: List[str] = Field(
        default_factory=list,
        description="Keys written to shared store"
    )
    natural_keys: bool = Field(
        default=True,
        description="Whether node uses natural (non-generic) key names"
    )

    @validator('outputs')
    def warn_generic_keys(cls, v):
        """Warn about generic key usage"""
        generic = {"data", "input", "output", "result", "value"}
        used_generic = set(v) & generic
        if used_generic:
            # Log warning but don't fail
            logger.warning(f"Node uses generic keys: {used_generic}")
        return v

# Extended metadata in IR
class WorkflowIR(BaseModel):
    interfaces: Dict[str, NodeInterface] = Field(
        default_factory=dict,
        description="Node ID -> interface documentation"
    )
```

### Pattern: Deterministic Execution Constraints
**Found in**: All successful repos ensure determinism
**Why It Applies**: Schema must enforce patterns that ensure reproducibility

```python
class ExecutionConfig(BaseModel):
    """Execution configuration ensuring determinism"""
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_wait: float = Field(default=1.0, ge=0.1, le=60.0)
    timeout: Optional[float] = Field(default=None, ge=1.0, le=3600.0)
    cache_enabled: bool = Field(default=True)
    deterministic: bool = Field(
        default=True,
        description="Enforce deterministic execution"
    )

    @validator('deterministic')
    def validate_deterministic_settings(cls, v, values):
        """Ensure settings support determinism"""
        if v and values.get('max_retries', 0) > 0:
            # Retries must use exponential backoff for determinism
            if 'retry_wait' in values and values['retry_wait'] < 1.0:
                raise ValueError("Deterministic execution requires retry_wait >= 1.0")
        return v

# Add to nodes
class NodeSpec(BaseModel):
    execution: Optional[ExecutionConfig] = Field(default=None)
```

## Anti-Patterns to Avoid

### Anti-Pattern: Allowing Dynamic Schema
**Found in**: Failed attempts at "flexible" workflows
**Issue**: Breaks validation and determinism
**Alternative**: Fixed schema with template variables

### Anti-Pattern: Deep Nesting in IR
**Found in**: Over-complex schema designs
**Issue**: Hard to validate and reason about
**Alternative**: Flat structure with references

### Anti-Pattern: Runtime Type Resolution
**Found in**: Dynamic typing attempts
**Issue**: Can't validate before execution
**Alternative**: All types known at IR creation

## Implementation Guidelines

1. **Use Pydantic**: Built-in validation and JSON schema generation
2. **Keep It Flat**: Avoid deep nesting in IR structure
3. **Template Support**: Preserve variables, don't resolve
4. **Natural Keys**: Document and encourage in schema
5. **Fail Fast**: Validate everything at IR creation

## JSON Schema Generation

```python
def generate_json_schema():
    """Generate JSON Schema for validation"""
    schema = WorkflowIR.schema()

    # Add examples
    schema["examples"] = [{
        "ir_version": "0.1.0",
        "metadata": {
            "description": "Fix GitHub issue workflow",
            "created": "2024-01-01T00:00:00Z"
        },
        "nodes": [
            {
                "id": "get-issue",
                "type": "github-get-issue",
                "params": {"issue_number": "$issue"}
            },
            {
                "id": "analyze",
                "type": "llm",
                "params": {
                    "prompt": "Analyze this issue: $issue_data",
                    "temperature": 0
                }
            }
        ],
        "edges": [
            {"from": "get-issue", "to": "analyze"}
        ],
        "start_node": "get-issue"
    }]

    return schema
```

## Testing Strategy

```python
def test_ir_validation():
    """Test schema validation"""

    # Valid IR
    valid_ir = {
        "nodes": [
            {"id": "n1", "type": "read-file", "params": {"path": "input.txt"}},
            {"id": "n2", "type": "write-file", "params": {"path": "output.txt"}}
        ],
        "edges": [{"from": "n1", "to": "n2"}],
        "start_node": "n1"
    }

    workflow = WorkflowIR(**valid_ir)
    assert workflow.ir_version == "0.1.0"
    assert len(workflow.nodes) == 2

    # Invalid: missing start node
    invalid_ir = {**valid_ir, "start_node": "n3"}
    with pytest.raises(ValidationError):
        WorkflowIR(**invalid_ir)

def test_template_preservation():
    """Test template variable handling"""

    ir = {
        "nodes": [{
            "id": "n1",
            "type": "llm",
            "params": {
                "prompt": "Process this: $input_data",
                "temperature": 0
            }
        }],
        "start_node": "n1"
    }

    workflow = WorkflowIR(**ir)
    node = workflow.nodes[0]

    # Template preserved
    assert "$input_data" in node.params["prompt"]

    # Variables extracted
    variables = node.get_template_variables()
    assert "input_data" in variables
```

## Integration Points

### Connection to Task 4 (IR Converter)
Schema defines what Task 4 must handle:
```python
# Task 6 defines structure
schema = WorkflowIR.schema()

# Task 4 assumes valid structure
workflow = WorkflowIR(**ir_json)  # Pre-validated
flow = compile_ir_to_flow(workflow.dict())
```

### Connection to Task 17 (Workflow Generation)
Schema guides LLM output:
```python
# Include schema in prompt
prompt = f"""
Generate workflow matching this schema:
{json.dumps(WorkflowIR.schema(), indent=2)}

Requirements:
- Use natural keys (issue_data, not data)
- Include template variables where needed
- Set temperature=0 for determinism
"""
```

### Connection to Task 9 (Shared Store)
Schema documents when mappings needed:
```python
# Rarely needed, but supported
if not node_interface.natural_keys:
    workflow.mappings[node.id] = MappingSpec(
        input_mappings={"prompt": "issue_text"}
    )
```

## Minimal Test Case

```python
# Save as test_ir_schema.py and run with pytest
import json
from pydantic import ValidationError

def test_complete_schema():
    """Test full schema with all features"""

    # Complete IR with all features
    complete_ir = {
        "ir_version": "0.1.0",
        "metadata": {
            "description": "GitHub issue fix workflow",
            "author": "pflow",
            "created": "2024-01-01T00:00:00Z"
        },
        "nodes": [
            {
                "id": "get-issue",
                "type": "github-get-issue",
                "params": {
                    "repo": "pflow/pflow",
                    "issue_number": "$issue"  # Template variable
                },
                "execution": {
                    "max_retries": 3,
                    "retry_wait": 2.0
                }
            },
            {
                "id": "analyze-issue",
                "type": "llm",
                "params": {
                    "prompt": "Analyze: $issue_data",
                    "model": "gpt-4",
                    "temperature": 0  # Deterministic
                }
            },
            {
                "id": "implement-fix",
                "type": "claude-code",
                "params": {
                    "instructions": "$implementation_plan"
                }
            }
        ],
        "edges": [
            {"from": "get-issue", "to": "analyze-issue"},
            {"from": "analyze-issue", "to": "implement-fix"}
        ],
        "start_node": "get-issue",
        "mappings": {},  # Empty - natural keys work!
        "interfaces": {
            "get-issue": {
                "inputs": ["issue_number", "repo"],
                "outputs": ["issue_data", "issue_title"],
                "natural_keys": True
            },
            "analyze-issue": {
                "inputs": ["issue_data"],
                "outputs": ["analysis", "implementation_plan"],
                "natural_keys": True
            }
        }
    }

    # Validate
    workflow = WorkflowIR(**complete_ir)

    # Check structure
    assert len(workflow.nodes) == 3
    assert len(workflow.edges) == 2
    assert workflow.mappings == {}  # No proxy needed!

    # Check templates preserved
    assert "$issue" in workflow.nodes[0].params["issue_number"]
    assert "$issue_data" in workflow.nodes[1].params["prompt"]

    # Export schema
    schema = workflow.schema()
    assert "properties" in schema
    assert "required" in schema

    print("✓ Complete schema validated")

if __name__ == "__main__":
    test_complete_schema()
```

## Summary

Task 6's IR schema establishes:

1. **Strict Validation** - Pydantic models catch errors early
2. **Template Preservation** - Variables pass through unchanged
3. **Natural Key Emphasis** - Schema encourages good patterns
4. **Determinism by Design** - Constraints ensure reproducibility
5. **Simplicity** - Flat structure, clear references

The schema is the contract between planning (Task 17) and execution (Task 4), ensuring workflows are valid before they run.
