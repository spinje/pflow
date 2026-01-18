# Typed Node Interfaces for AI Agent Authorship (v2.0+)

## Executive Summary

**Purpose**: Replace docstring-based metadata extraction with typed interfaces for nodes
**Primary Audience**: AI agents writing pflow nodes
**Key Benefit**: Type safety, validation, and better tooling support for automated node generation

As pflow evolves toward AI-driven development, nodes will increasingly be authored by AI agents rather than humans. This shift requires a more structured, type-safe approach to defining node interfaces that can be validated at development time and provide clear contracts for automated systems.

---

## Why Typed Interfaces for AI Agents

### Current Challenges with Docstring Parsing

1. **No Development-Time Validation** - AI agents can't verify interface correctness until runtime
2. **Regex Fragility** - Small formatting errors break metadata extraction
3. **Lack of Type Information** - No way to specify or validate data types
4. **Duplication** - Interface defined in both docstring and code
5. **Limited Tooling** - No IDE support, autocomplete, or static analysis

### Benefits for AI Agent Development

1. **Immediate Validation** - Type checkers catch errors during code generation
2. **Clear Contracts** - Unambiguous interface definitions
3. **Better Error Messages** - Type violations provide specific feedback
4. **Code Generation** - Can generate boilerplate from type definitions
5. **Self-Documenting** - Types serve as executable documentation

---

## Design Approaches

### Approach 1: TypedDict with Metadata (Recommended)

```python
from typing import TypedDict, Optional, Literal
from typing_extensions import Annotated, NotRequired
from pocketflow import Node

class ReadFileNode(Node):
    """Read content from a file and add line numbers."""

    class Interface:
        class Inputs(TypedDict):
            file_path: Annotated[str, "Path to file to read"]
            encoding: Annotated[NotRequired[str], "File encoding (default: utf-8)"]

        class Outputs(TypedDict):
            content: Annotated[NotRequired[str], "File content with line numbers"]
            error: Annotated[NotRequired[str], "Error message if read fails"]

        params_fallback = ["file_path", "encoding"]
        actions = Literal["default", "error"]

    def prep(self, shared: dict) -> tuple[str, str]:
        # Type-safe access with IDE support
        inputs = self.Interface.Inputs(**{k: v for k, v in shared.items() if k in self.Interface.Inputs.__annotations__})
        file_path = inputs.get("file_path") or self.params.get("file_path")
        if not file_path:
            raise ValueError("Missing required 'file_path'")
        return (file_path, inputs.get("encoding", "utf-8"))
```

### Approach 2: Pydantic Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from pocketflow import Node

class ReadFileNode(Node):
    """Read content from a file."""

    class InputModel(BaseModel):
        file_path: str = Field(description="Path to file to read")
        encoding: str = Field(default="utf-8", description="File encoding")

    class OutputModel(BaseModel):
        content: Optional[str] = Field(None, description="File content")
        error: Optional[str] = Field(None, description="Error message")

    actions = Literal["default", "error"]

    def prep(self, shared: dict) -> InputModel:
        # Pydantic handles validation automatically
        return self.InputModel(**shared)
```

### Approach 3: Protocol-Based Interfaces

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@runtime_checkable
class FileReaderInterface(Protocol):
    """Protocol defining file reader contract."""

    @dataclass
    class Config:
        input_keys = ["file_path", "encoding"]
        output_keys = ["content", "error"]
        required_inputs = ["file_path"]
        actions = ["default", "error"]
```

---

## Implementation Design

### Base Class with Type Support

```python
from typing import TypeVar, Generic, Type, get_type_hints
from pocketflow import Node as PocketflowNode

T_Input = TypeVar('T_Input', bound=TypedDict)
T_Output = TypeVar('T_Output', bound=TypedDict)

class TypedNode(PocketflowNode, Generic[T_Input, T_Output]):
    """Base class for nodes with typed interfaces."""

    # Class-level type definitions (to be overridden)
    InputType: Type[T_Input]
    OutputType: Type[T_Output]

    def __init__(self):
        super().__init__()
        self._validate_interface()

    def _validate_interface(self):
        """Validate that interface types are properly defined."""
        if not hasattr(self, 'InputType') or not hasattr(self, 'OutputType'):
            raise TypeError(f"{self.__class__.__name__} must define InputType and OutputType")

    def validate_inputs(self, shared: dict) -> T_Input:
        """Validate and extract typed inputs from shared store."""
        input_hints = get_type_hints(self.InputType)
        validated = {}

        for key, type_hint in input_hints.items():
            if key in shared:
                # Basic type validation (can be extended)
                if not isinstance(shared[key], type_hint):
                    raise TypeError(f"Expected {key} to be {type_hint}, got {type(shared[key])}")
                validated[key] = shared[key]
            elif not getattr(type_hint, '__origin__', None) == NotRequired:
                # Use param fallback if available
                if key in self.params:
                    validated[key] = self.params[key]
                else:
                    raise ValueError(f"Missing required input: {key}")

        return validated  # type: ignore

    def set_outputs(self, shared: dict, **outputs: Any) -> None:
        """Type-safe output setting."""
        output_hints = get_type_hints(self.OutputType)

        for key, value in outputs.items():
            if key not in output_hints:
                raise ValueError(f"Unknown output key: {key}")
            shared[key] = value
```

### Concrete Implementation Example

```python
class TransformTextNode(TypedNode):
    """Transform text with various operations."""

    class InputType(TypedDict):
        text: Annotated[str, "Input text to transform"]
        operation: Annotated[Literal["uppercase", "lowercase", "reverse"], "Transformation to apply"]
        strip_whitespace: Annotated[NotRequired[bool], "Strip leading/trailing whitespace"]

    class OutputType(TypedDict):
        result: Annotated[str, "Transformed text"]
        original_length: Annotated[int, "Length of original text"]

    actions = ["default"]

    def prep(self, shared: dict) -> InputType:
        return self.validate_inputs(shared)

    def exec(self, inputs: InputType) -> dict:
        text = inputs["text"]
        if inputs.get("strip_whitespace", False):
            text = text.strip()

        operations = {
            "uppercase": text.upper,
            "lowercase": text.lower,
            "reverse": lambda t: t[::-1]
        }

        result = operations[inputs["operation"]](text)

        return {
            "result": result,
            "original_length": len(inputs["text"])
        }

    def post(self, shared: dict, prep_res: InputType, exec_res: dict) -> str:
        self.set_outputs(shared, **exec_res)
        return "default"
```

---

## Metadata Extraction from Types

### Automatic Schema Generation

```python
from typing import get_type_hints, get_origin, get_args
import inspect

class TypedMetadataExtractor:
    """Extract metadata from typed node interfaces."""

    def extract_metadata(self, node_class: Type[TypedNode]) -> dict:
        """Extract complete metadata from typed node."""

        # Get type annotations
        input_type = getattr(node_class, 'InputType', None)
        output_type = getattr(node_class, 'OutputType', None)

        if not input_type or not output_type:
            raise ValueError(f"{node_class.__name__} missing type definitions")

        # Extract interface metadata
        interface = {
            "inputs": self._extract_typed_fields(input_type),
            "outputs": self._extract_typed_fields(output_type),
            "actions": self._extract_actions(node_class),
            "params": self._extract_params(node_class)
        }

        # Build complete metadata
        return {
            "node": {
                "id": self._generate_node_id(node_class.__name__),
                "class_name": node_class.__name__,
                "type_system": "typed_interface"
            },
            "interface": interface,
            "documentation": {
                "description": inspect.getdoc(node_class) or "No description",
                "generated_from_types": True
            },
            "validation": {
                "input_schema": self._generate_json_schema(input_type),
                "output_schema": self._generate_json_schema(output_type)
            }
        }

    def _extract_typed_fields(self, typed_dict: Type[TypedDict]) -> dict:
        """Extract field information from TypedDict."""
        hints = get_type_hints(typed_dict, include_extras=True)
        fields = {}

        for field_name, field_type in hints.items():
            # Extract metadata from Annotated types
            metadata = {}
            if hasattr(field_type, '__metadata__'):
                metadata['description'] = field_type.__metadata__[0]

            # Check if field is required
            origin = get_origin(field_type)
            if origin is Annotated:
                field_type = get_args(field_type)[0]
                origin = get_origin(field_type)

            metadata['required'] = origin is not NotRequired
            metadata['type'] = self._type_to_string(field_type)

            fields[field_name] = metadata

        return fields

    def _generate_json_schema(self, typed_dict: Type[TypedDict]) -> dict:
        """Generate JSON Schema from TypedDict."""
        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }

        hints = get_type_hints(typed_dict, include_extras=True)

        for field_name, field_type in hints.items():
            # Determine if required
            if get_origin(field_type) is not NotRequired:
                schema["required"].append(field_name)

            # Add property schema
            schema["properties"][field_name] = self._type_to_json_schema(field_type)

        return schema
```

---

## AI Agent Integration

### Code Generation Template for AI Agents

```python
# Template for AI agents to generate typed nodes
NODE_TEMPLATE = '''
from typing import TypedDict, Optional, Literal
from typing_extensions import Annotated, NotRequired
from pocketflow_typed import TypedNode

class {class_name}(TypedNode):
    """{description}"""

    class InputType(TypedDict):
{input_fields}

    class OutputType(TypedDict):
{output_fields}

    actions = {actions}

    def prep(self, shared: dict) -> InputType:
        """Validate and prepare inputs."""
        return self.validate_inputs(shared)

    def exec(self, inputs: InputType) -> dict:
        """Execute main logic."""
        # TODO: Implement logic here
        pass

    def post(self, shared: dict, prep_res: InputType, exec_res: dict) -> str:
        """Store outputs and return action."""
        self.set_outputs(shared, **exec_res)
        return "default"
'''

def generate_node_code(spec: dict) -> str:
    """Generate typed node code from specification."""
    # Format input fields
    input_fields = []
    for name, info in spec['inputs'].items():
        type_str = info['type']
        if not info.get('required', True):
            type_str = f"NotRequired[{type_str}]"
        desc = info.get('description', '')
        input_fields.append(f'        {name}: Annotated[{type_str}, "{desc}"]')

    # Format output fields
    output_fields = []
    for name, info in spec['outputs'].items():
        type_str = f"NotRequired[{info['type']}]"  # Outputs typically optional
        desc = info.get('description', '')
        output_fields.append(f'        {name}: Annotated[{type_str}, "{desc}"]')

    return NODE_TEMPLATE.format(
        class_name=spec['class_name'],
        description=spec['description'],
        input_fields='\n'.join(input_fields),
        output_fields='\n'.join(output_fields),
        actions=repr(spec.get('actions', ['default']))
    )
```

### AI Agent Prompt Enhancement

```markdown
When creating pflow nodes, use the typed interface pattern:

1. Define InputType as a TypedDict with all inputs
2. Define OutputType as a TypedDict with all outputs
3. Use Annotated[type, "description"] for documentation
4. Mark optional fields with NotRequired[]
5. Implement validate_inputs() in prep()
6. Use set_outputs() in post() for type safety

Example structure:
- InputType: Define what the node reads from shared store
- OutputType: Define what the node writes to shared store
- actions: List possible return values from post()
```

---

## Migration Strategy

### Phase 1: Dual Support (v2.0)

```python
class HybridNode(TypedNode):
    """Node supporting both docstring and typed metadata."""

    # Typed interface (primary)
    class InputType(TypedDict):
        url: str

    class OutputType(TypedDict):
        content: str

    # Docstring interface (backward compatibility)
    """
    Interface:
    - Reads: shared["url"]: str  # URL to fetch content from
    - Writes: shared["content"]: str  # Fetched content
    """
```

### Phase 2: Migration Tools (v2.1)

```python
def migrate_docstring_to_typed(node_class: Type[Node]) -> str:
    """Convert docstring-based node to typed interface."""
    # Extract existing metadata
    extractor = PflowMetadataExtractor()
    metadata = extractor.extract_metadata(node_class)

    # Generate typed interface code
    spec = {
        'class_name': node_class.__name__,
        'description': metadata['description'],
        'inputs': metadata['inputs'],
        'outputs': metadata['outputs'],
        'actions': metadata['actions']
    }

    return generate_node_code(spec)
```

### Phase 3: Full Typed System (v3.0)

- Deprecate docstring parsing
- Require typed interfaces for all nodes
- Enhanced validation and tooling

---

## Runtime Benefits

### Type-Safe Shared Store Access

```python
# Current approach - no type safety
file_path = shared.get("file_path")  # Could be anything

# Typed approach - with validation
inputs = self.validate_inputs(shared)
file_path = inputs["file_path"]  # Guaranteed to be str
```

### Better Error Messages

```python
# Current approach
"Missing required 'file_path' in shared store or params"

# Typed approach
"ValidationError: Missing required input 'file_path' (type: str, description: Path to file to read)"
```

### Automatic Documentation

```python
def describe_node(node_class: Type[TypedNode]) -> str:
    """Generate documentation from types."""
    inputs = get_type_hints(node_class.InputType, include_extras=True)
    outputs = get_type_hints(node_class.OutputType, include_extras=True)

    doc = f"# {node_class.__name__}\n\n"
    doc += f"{inspect.getdoc(node_class)}\n\n"

    doc += "## Inputs\n"
    for name, type_info in inputs.items():
        doc += f"- **{name}**: {type_info}\n"

    doc += "\n## Outputs\n"
    for name, type_info in outputs.items():
        doc += f"- **{name}**: {type_info}\n"

    return doc
```

---

## Performance Considerations

### Overhead Analysis

1. **Development Time**: One-time type checking cost
2. **Runtime Validation**: ~5-10μs per validation (acceptable)
3. **Memory**: Minimal - type objects are shared
4. **Import Time**: Slightly higher due to type imports

### Optimization Strategies

```python
# Cache validated types
class OptimizedTypedNode(TypedNode):
    _input_schema_cache = {}
    _output_schema_cache = {}

    def validate_inputs(self, shared: dict) -> dict:
        # Cache schema compilation
        cache_key = self.__class__.__name__
        if cache_key not in self._input_schema_cache:
            self._input_schema_cache[cache_key] = self._compile_schema()

        return self._validate_with_schema(
            shared,
            self._input_schema_cache[cache_key]
        )
```

---

## Integration Points

### Registry Integration

```python
# Enhanced registry with type support
class TypeAwareRegistry(Registry):
    def register_typed_node(self, node_class: Type[TypedNode]):
        """Register node with automatic type extraction."""
        extractor = TypedMetadataExtractor()
        metadata = extractor.extract_metadata(node_class)

        # Validate type consistency
        self._validate_types(node_class)

        # Store with enhanced metadata
        self.nodes[metadata['node']['id']] = {
            **metadata,
            'implementation_class': node_class,
            'type_system': 'typed_interface'
        }
```

### Planner Integration

```python
# Type-aware planner context
def build_typed_context(registry: TypeAwareRegistry) -> str:
    """Build planner context with type information."""
    context = ["Available typed nodes:\n"]

    for node_id, node_info in registry.nodes.items():
        if node_info.get('type_system') != 'typed_interface':
            continue

        schema = node_info['validation']['input_schema']
        context.append(f"{node_id}:")
        context.append(f"  Inputs: {json.dumps(schema['properties'], indent=4)}")
        context.append(f"  Required: {schema['required']}")
        context.append("")

    return "\n".join(context)
```

---

## Conclusion

Typed node interfaces represent a natural evolution for pflow as it moves toward AI-driven development. By providing:

1. **Type Safety** - Catch errors during development
2. **Clear Contracts** - Unambiguous interface definitions
3. **Better Tooling** - IDE support and static analysis
4. **AI-Friendly** - Structured format for code generation
5. **Runtime Validation** - Ensure data consistency

This approach maintains pflow's philosophy of simplicity while adding the structure needed for reliable AI agent authorship.

## See Also

- [Advanced Metadata Extraction](./advanced-metadata-extraction.md) - Current approach
- [Architecture](../architecture.md#node-naming) - Node naming conventions
- [IR Schema](../reference/ir-schema.md) - Schema definitions
