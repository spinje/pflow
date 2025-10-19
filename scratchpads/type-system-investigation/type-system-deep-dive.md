# pflow Type System Deep Dive: Schema-Aware Type Checking Investigation

**Date**: 2025-10-20
**Purpose**: Complete technical analysis of pflow's type system to plan compile-time type checking for template variables
**Status**: Investigation Complete ✅

---

## Executive Summary

pflow has a **comprehensive type system** already in place with:
- Rich type annotations in Enhanced Interface Format (EIF)
- Full parsing and storage of type metadata in registry
- Nested structure support for complex types (dict, list)
- Template path validation using registry metadata
- Union type support (`dict|str`, `any|int`)

**Key Finding**: The foundation for schema-aware type checking exists. What's missing is **type compatibility logic** to match template variable types against expected parameter types.

---

## 1. Enhanced Interface Format (EIF) - Type Definitions

**Location**: `architecture/reference/enhanced-interface-format.md`

### 1.1 Supported Type Annotations

```python
# Basic Types (lines 33-41)
str      # String values
int      # Integer numbers
float    # Floating-point numbers
bool     # Boolean values (true/false)
dict     # Dictionary/object structures
list     # List/array structures
any      # Any type (default when not specified)
```

### 1.2 Union Types (lines 43-72)

**Syntax**: `type1|type2|type3`

```python
# Examples from documentation
- Writes: shared["response"]: dict|str  # Response data (parsed JSON or raw text)
- Writes: shared["result"]: dict|str|int  # Result value (varies by mode)
- Writes: shared["data"]: any|str  # Data of unknown structure or string
```

**Validation Behavior**:
- If ANY type in union supports nested access (`dict`, `object`, `any`), nested template access allowed
- Example: `dict|str` allows `${node.response.field}` because dict supports it
- Example: `str|int` rejects `${node.value.field}` - neither supports nesting
- Unions with `any` generate validation warnings

**Naming Convention**:
- Lowercase: `dict|str` ✅
- No spaces: `dict|str` ✅ (though `dict | str` also works)

### 1.3 Nested Structure Documentation (lines 149-250)

**Syntax**: Indentation-based structure definitions

```python
Interface:
- Writes: shared["issue_data"]: dict  # GitHub issue information
    - number: int  # Issue number
    - title: str  # Issue title
    - user: dict  # Author information
      - login: str  # GitHub username
      - id: int  # User ID
    - labels: list  # Array of labels
      - name: str  # Label text
      - color: str  # Hex color code
```

**Parsed Output** (dual representation in planning context):

```json
{
  "issue_data": {
    "number": "int",
    "title": "str",
    "user": {
      "login": "str",
      "id": "int"
    },
    "labels": [
      {
        "name": "str",
        "color": "str"
      }
    ]
  }
}
```

**Available paths**:
- `issue_data.number` (int)
- `issue_data.title` (str)
- `issue_data.user.login` (str)
- `issue_data.user.id` (int)
- `issue_data.labels[0].name` (str)
- `issue_data.labels[0].color` (str)

### 1.4 Structure Rules (lines 202-209)

1. **Indentation**: 2 or 4 spaces consistently
2. **Format**: `- field_name: type  # Description`
3. **Nesting**: Child fields indented under parent
4. **Lists**: Document item structure underneath
5. **Max depth**: 5 levels (prevents infinite recursion)

### 1.5 Parser Limitations (lines 368-425)

**Critical**:
- ❌ Single quotes not supported: Use `shared["key"]` not `shared['key']`
- ❌ Empty components break parser
- ❌ Commas in descriptions can break parsing

**Minor**:
- Very long lines (>1000 chars) hit regex limits
- Indentation must be consistent
- Max 5 levels of nesting

---

## 2. Metadata Extraction - Type Parsing

**Location**: `src/pflow/registry/metadata_extractor.py`

### 2.1 Type Extraction Process

**Format Detection** (lines 286-319):
```python
def _detect_interface_format(self, content: str, component_type: str) -> bool:
    """Detect if content uses enhanced format with type annotations."""
    if component_type in ("inputs", "outputs"):
        # Check for: shared["key"]: type
        if re.search(r'shared\["[^"]+"\]\s*:', content):
            return True
    elif component_type == "params":
        # Check for: param_name: type (not "default: 10")
        content_no_parens = re.sub(r"\([^)]+\)", "", content)
        if re.search(r"\b\w+\s*:\s*\w+", content_no_parens):
            return True
    return False
```

**Enhanced Shared Keys Extraction** (lines 348-426):
```python
def _extract_enhanced_shared_keys(self, content: str) -> list[dict[str, Any]]:
    """Extract shared store keys with type annotations and descriptions.

    Returns:
        List of dicts with key, type, description, and optional structure
    """
    results = []

    # Pattern: shared["key"]: type  # description
    item_pattern = r'shared\["([^"]+)"\]\s*:\s*([^\s#]+)(?:\s*#\s*(.*))?'
    match = re.match(item_pattern, segment)

    if match:
        key = match.group(1)
        type_str = match.group(2).strip()
        description = match.group(3).strip() if match.group(3) else ""

        result = {"key": key, "type": type_str, "description": description}

        # Check for complex types with structure
        if type_str in ("dict", "list", "list[dict]"):
            result["_has_structure"] = True  # Parsed separately

        results.append(result)

    return results
```

**Enhanced Params Extraction** (lines 428-480):
```python
def _extract_enhanced_params(self, content: str) -> list[dict[str, Any]]:
    """Extract parameters with type annotations and descriptions.

    Returns:
        List of dicts with key, type, and description
    """
    results = []

    # Pattern: param_name: type  # description
    param_pattern = r"(\w+)\s*:\s*([^#\n]+)(?:\s*#\s*(.*))?$"
    match = re.match(param_pattern, segment)

    if match:
        key = match.group(1)
        type_str = match.group(2).strip()
        description = match.group(3).strip() if match.group(3) else ""

        results.append({"key": key, "type": type_str, "description": description})

    return results
```

### 2.2 Structure Parsing (lines 507-606)

**Recursive Structure Parser**:
```python
def _parse_structure(self, lines: list[str], start_idx: int) -> tuple[dict[str, Any], int]:
    """Parse indentation-based structure starting at start_idx.

    Returns:
        Tuple of (structure_dict, next_line_idx)
    """
    structure = {}
    base_indent = None
    idx = start_idx

    while idx < len(lines):
        line = lines[idx]
        current_indent = self._get_indentation(line)

        if base_indent is None:
            base_indent = current_indent

        if current_indent < base_indent:
            break  # Returned to parent level

        if current_indent == base_indent:
            # Parse field: "- field: type  # description"
            field_match = re.match(r"\s*-\s*(\w+)\s*:\s*([^#\n]+)(?:\s*#\s*(.*))?", line)
            if field_match:
                field_name = field_match.group(1)
                field_type = field_match.group(2).strip()
                field_desc = field_match.group(3).strip() if field_match.group(3) else ""

                field_info = {"type": field_type, "description": field_desc}

                # Check for nested structure
                if field_type in ("dict", "list", "list[dict]") and idx + 1 < len(lines):
                    next_line = lines[idx + 1]
                    if self._get_indentation(next_line) > current_indent:
                        nested_structure, new_idx = self._parse_structure(lines, idx + 1)
                        if nested_structure:
                            field_info["structure"] = nested_structure
                            idx = new_idx - 1

                structure[field_name] = field_info

        idx += 1

    return structure, idx
```

**Key Features**:
- Recursive descent parsing
- Indentation-aware
- Handles nested dicts and lists
- Max depth protection (5 levels)
- Preserves type and description at each level

### 2.3 Data Structure Output

**Registry Storage Format** (from metadata_extractor.py lines 108-114):
```python
result = {
    "description": description,
    "inputs": self._normalize_to_rich_format(interface_data.get("inputs", [])),
    "outputs": self._normalize_to_rich_format(interface_data.get("outputs", [])),
    "params": self._normalize_to_rich_format(interface_data.get("params", [])),
    "actions": interface_data.get("actions", []),  # Simple list
}
```

**Rich Format Structure** (lines 482-501):
```python
# For inputs/outputs/params:
[
    {
        "key": "file_path",
        "type": "str",
        "description": "Path to the file",
        "structure": {}  # Optional, for complex types
    },
    {
        "key": "response",
        "type": "dict|str",
        "description": "API response data",
        "structure": {
            "data": {"type": "dict", "description": "Response data"},
            "status": {"type": "int", "description": "HTTP status"}
        }
    }
]

# For actions (simple strings):
["default", "error"]
```

---

## 3. Registry Storage Format

**Location**: `src/pflow/registry/registry.py`

### 3.1 Registry File Structure

**Example from ~/.pflow/registry.json**:

```json
{
  "__metadata__": {
    "mcp_last_sync_time": 1760133032.80953,
    "mcp_servers_hash": "1401ea3a29e6aaa89643ed6b3956bb6e392a912e616713bccc4e2ca702426c4d"
  },
  "claude-code": {
    "class_name": "ClaudeCodeNode",
    "file_path": "/Users/andfal/projects/pflow/src/pflow/nodes/claude/claude_code.py",
    "interface": {
      "description": "Claude Code agentic super node",
      "inputs": [
        {
          "key": "task",
          "type": "str",
          "description": "Development task description (required)"
        },
        {
          "key": "output_schema",
          "type": "dict",
          "description": "Schema for structured outputs"
        }
      ],
      "outputs": [
        {
          "key": "result",
          "type": "any",
          "description": "Response - string without schema, dict with schema"
        },
        {
          "key": "_claude_metadata",
          "type": "dict",
          "description": "Execution metadata",
          "structure": {
            "duration_ms": {
              "type": "int",
              "description": "Execution time in milliseconds"
            },
            "total_cost_usd": {
              "type": "float",
              "description": "Total cost in USD"
            },
            "usage": {
              "type": "dict",
              "description": "Token usage information",
              "structure": {
                "input_tokens": {"type": "int", "description": "..."},
                "output_tokens": {"type": "int", "description": "..."}
              }
            }
          }
        }
      ],
      "params": [
        {
          "key": "model",
          "type": "str",
          "description": "Claude model identifier"
        },
        {
          "key": "max_turns",
          "type": "int",
          "description": "Maximum conversation turns"
        }
      ],
      "actions": []
    }
  }
}
```

### 3.2 Type Access Pattern

**Getting Node Type Info** (registry.py lines 243-273):
```python
def get_nodes_metadata(self, node_types: Collection[str]) -> dict[str, dict[str, Any]]:
    """Get metadata for specific node types.

    Returns:
        Dict mapping node type names to their metadata.
        Only includes node types that exist in registry.
    """
    registry_data = self.load()

    result = {}
    for node_type in node_types:
        if node_type in registry_data:
            result[node_type] = registry_data[node_type]

    return result
```

**Type Access Example**:
```python
registry = Registry()
nodes_metadata = registry.get_nodes_metadata(["claude-code"])

# Access type info:
interface = nodes_metadata["claude-code"]["interface"]
outputs = interface["outputs"]
for output in outputs:
    key = output["key"]
    output_type = output["type"]
    structure = output.get("structure", {})
```

### 3.3 Registry Filtering

**Load with Filtering** (lines 43-82):
```python
def load(self, include_filtered: bool = False) -> dict[str, dict[str, Any]]:
    """Load registry with optional filtering.

    Args:
        include_filtered: If True, return ALL nodes.
                         If False, apply settings filters.
    """
    nodes = self._load_from_file()

    if not include_filtered:
        filtered_nodes = {}
        for node_name, node_data in nodes.items():
            module_path = node_data.get("module_path") or node_data.get("file_path")
            if self.settings_manager.should_include_node(node_name, module_path):
                filtered_nodes[node_name] = node_data
        return filtered_nodes

    return nodes
```

---

## 4. MCP Node Type Handling

**Location**: `src/pflow/mcp/types.py`, `src/pflow/nodes/mcp/node.py`

### 4.1 MCP Type Definitions

**From mcp/types.py**:
```python
class ParamSchema(TypedDict, total=False):
    """Parameter schema for pflow registry."""
    key: str
    type: str
    required: bool
    description: Optional[str]
    default: Any
    enum: Optional[list[Any]]

class InterfaceSchema(TypedDict, total=False):
    """Interface schema for registry entries."""
    description: str
    inputs: list[Any]
    params: list[ParamSchema]
    outputs: list[dict[str, Any]]
    actions: list[str]
    mcp_metadata: dict[str, Any]

class RegistryEntry(TypedDict):
    """Registry entry for MCP nodes."""
    class_name: str
    module: str
    file_path: str
    interface: InterfaceSchema
```

### 4.2 MCP Schema Extraction

**From mcp/registrar.py** (inferred from types):

MCP tools are discovered dynamically and their JSON Schema converted to pflow types:

```python
# MCP JSON Schema → pflow type mapping
{
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "object": "dict",
    "array": "list",
    "null": "any"
}
```

**Union Types in JSON Schema**:
```python
# JSON Schema union: {"type": ["string", "null"]}
# Converts to pflow: "str|any"
```

### 4.3 MCP outputSchema Support

**From nodes/mcp/node.py lines 745-782**:

```python
def _extract_result(self, mcp_result: Any) -> Any:
    """Extract usable result from MCP tool response.

    Priority order:
    1. structuredContent: Typed JSON matching outputSchema (preferred)
    2. isError flag: Tool execution failed
    3. content blocks: Text, image, resource (fallback)
    """
    # Priority 1: Structured content (validated against outputSchema)
    if hasattr(mcp_result, "structuredContent") and mcp_result.structuredContent is not None:
        return mcp_result.structuredContent

    # Priority 2: Error flag
    if hasattr(mcp_result, "isError") and mcp_result.isError:
        error_msg = self._extract_error_message(mcp_result)
        return {"error": error_msg, "is_tool_error": True}

    # Priority 3: Legacy content blocks
    if hasattr(mcp_result, "content"):
        return self._process_content_blocks(mcp_result)

    return str(mcp_result)
```

**Key Insight**: MCP nodes can return structured data with known schemas, making type checking highly valuable.

---

## 5. Template System - Type Context

**Location**: `src/pflow/runtime/template_resolver.py`

### 5.1 Template Variable Detection

**Pattern** (line 26-28):
```python
# Supports: ${var}, ${var.field}, ${var[0]}, ${var.field[0].subfield}
TEMPLATE_PATTERN = re.compile(
    r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[a-zA-Z_][\w-]*(?:\[[\d]+\])?)*)?)\}"
)
```

**Examples**:
- `${url}` - Simple variable
- `${data.field}` - Nested field
- `${items[0].name}` - Array access with field
- `${node.response.data[5].users[2].login}` - Deep nesting

### 5.2 Path Resolution (lines 173-240)

```python
def resolve_value(var_name: str, context: dict[str, Any]) -> Optional[Any]:
    """Resolve variable with path and array index support.

    Examples:
        'url' → context['url']
        'data.field' → context['data']['field']
        'items[0]' → context['items'][0]
        'items[0].name' → context['items'][0]['name']
    """
    if "." in var_name or "[" in var_name:
        parts = re.split(r"\.(?![^\[]*\])", var_name)
        value = context

        for part in parts:
            # Handle array indices: name[0] or name[0][1]
            array_match = re.match(r"^([^[]+)((?:\[\d+\])+)$", part)

            if array_match:
                base_name = array_match.group(1)
                indices_str = array_match.group(2)

                if isinstance(value, dict) and base_name in value:
                    value = value[base_name]
                else:
                    return None

                # Apply indices
                indices = re.findall(r"\[(\d+)\]", indices_str)
                for index_str in indices:
                    index = int(index_str)
                    if isinstance(value, list) and 0 <= index < len(value):
                        value = value[index]
                    else:
                        return None
            else:
                # Regular property access
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return None

        return value
    else:
        return context.get(var_name)
```

### 5.3 Type Conversion (lines 242-284)

```python
def _convert_to_string(value: Any) -> str:
    """Convert any value to string.

    Rules:
    - None → ""
    - False → "False"
    - True → "True"
    - 0 → "0"
    - [] → "[]"
    - {} → "{}"
    - dict/list → JSON serialized
    - Everything else → str(value)
    """
    if value is None or value == "":
        return ""
    elif value is False:
        return "False"
    elif value is True:
        return "True"
    elif value == 0:
        return "0"
    elif value == []:
        return "[]"
    elif value == {}:
        return "{}"
    elif isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    else:
        return str(value)
```

**Key Insight**: Type is preserved for simple templates (`${var}`), converted to string for complex templates (`"Hello ${name}"`).

---

## 6. Template Validation - Existing Type Checks

**Location**: `src/pflow/runtime/template_validator.py`

### 6.1 Current Validation Capabilities

**Main Validation Function** (lines 87-173):
```python
def validate_workflow_templates(
    workflow_ir: dict[str, Any],
    available_params: dict[str, Any],
    registry: Registry
) -> tuple[list[str], list[ValidationWarning]]:
    """Validates all template variables in a workflow.

    Returns:
        Tuple of (errors, warnings)
        - errors: Prevent execution
        - warnings: ValidationWarning for runtime-validated templates
    """
    errors: list[str] = []
    warnings: list[ValidationWarning] = []

    # 1. Check malformed syntax
    malformed_errors = TemplateValidator._validate_malformed_templates(workflow_ir)
    errors.extend(malformed_errors)

    if malformed_errors:
        return (errors, warnings)

    # 2. Extract all templates
    all_templates = TemplateValidator._extract_all_templates(workflow_ir)

    # 3. Check unused inputs
    unused_input_errors = TemplateValidator._validate_unused_inputs(workflow_ir, all_templates)
    errors.extend(unused_input_errors)

    # 4. Get node outputs from registry
    node_outputs = TemplateValidator._extract_node_outputs(workflow_ir, registry)

    # 5. Validate each template path
    for template in sorted(all_templates):
        is_valid, warning = TemplateValidator._validate_template_path(
            template, available_params, node_outputs, workflow_ir, registry
        )

        if warning:
            warnings.append(warning)

        if not is_valid:
            error = TemplateValidator._create_template_error(
                template, available_params, workflow_ir, node_outputs, registry
            )
            errors.append(error)

    return (errors, warnings)
```

### 6.2 ValidationWarning - Runtime Type Checking

**Definition** (lines 16-32):
```python
@dataclass
class ValidationWarning:
    """Warning about runtime-validated template access.

    Emitted when static validation cannot verify a template path
    (e.g., accessing nested fields on outputs with type 'any').
    """
    template: str          # Full template with ${}
    node_id: str           # Node producing the output
    node_type: str         # Node type (often MCP)
    output_key: str        # Output key being accessed
    output_type: str       # Type causing runtime validation
    reason: str            # Human-readable explanation
    nested_path: str       # Nested portion: "data.field[0]"
```

### 6.3 Node Output Extraction (lines 656-714)

```python
def _extract_node_outputs(workflow_ir: dict[str, Any], registry: Registry) -> dict[str, Any]:
    """Extract full output structures from nodes using interface metadata.

    Returns:
        Dict mapping variable names to their full structure/type info
    """
    node_outputs = {}
    enable_namespacing = workflow_ir.get("enable_namespacing", True)

    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id")
        node_type = node.get("type")

        # Get metadata from registry
        nodes_metadata = registry.get_nodes_metadata([node_type])
        interface = nodes_metadata[node_type]["interface"]

        # Extract outputs with structure
        for output in interface["outputs"]:
            if isinstance(output, str):
                # Simple format
                output_info = {
                    "type": "any",
                    "node_id": node_id,
                    "node_type": node_type
                }
            else:
                # Rich format
                output_info = {
                    "type": output.get("type", "any"),
                    "structure": output.get("structure", {}),
                    "node_id": node_id,
                    "node_type": node_type
                }

            # Store under both keys (backward compat + namespacing)
            node_outputs[output["key"]] = output_info
            if enable_namespacing:
                namespaced_key = f"{node_id}.{output['key']}"
                node_outputs[namespaced_key] = output_info

    return node_outputs
```

### 6.4 Nested Path Validation (lines 790-865)

```python
def _validate_nested_path(
    path_parts: list[str],
    output_info: dict[str, Any],
    full_template: str = "",
    output_key: str = ""
) -> tuple[bool, Optional[ValidationWarning]]:
    """Validate nested path exists in output structure.

    Returns:
        Tuple of (is_valid, optional_warning)
    """
    current_structure = output_info.get("structure", {})

    # No structure info - check if type allows traversal
    if not current_structure:
        output_type = output_info.get("type", "any")

        # Parse union types: "dict|str" → ["dict", "str"]
        types_in_union = [t.strip().lower() for t in output_type.split("|")]

        # Check if ANY type allows traversal
        traversable_types = [t for t in types_in_union if t in ["dict", "object", "any"]]

        if not traversable_types:
            return (False, None)  # None of the types allow nested access

        # At least one type allows traversal
        warning = None
        if "any" in traversable_types and len(path_parts) > 0:
            # Generate warning for runtime validation
            warning = ValidationWarning(
                template=full_template,
                node_id=output_info.get("node_id", "unknown"),
                node_type=output_info.get("node_type", "unknown"),
                output_key=output_key,
                output_type=output_type,
                reason=f"Output type '{output_type}' - structure cannot be verified statically",
                nested_path=".".join(path_parts)
            )

        return (True, warning)

    # Traverse structure
    for i, part in enumerate(path_parts):
        if part not in current_structure:
            return (False, None)

        next_item = current_structure[part]
        if isinstance(next_item, dict):
            if "type" in next_item:
                if i < len(path_parts) - 1:
                    # More parts to traverse
                    current_structure = next_item.get("structure", {})
                    if not current_structure:
                        # Can't traverse further
                        return (next_item.get("type") in ["dict", "object", "any"], None)
                else:
                    return (True, None)
            else:
                current_structure = next_item
        else:
            return (i == len(path_parts) - 1, None)

    return (True, None)
```

### 6.5 Union Type Handling

**Key Code** (lines 810-837):
```python
# Parse union types
types_in_union = [t.strip().lower() for t in output_type.split("|")]

# Check if ANY type in union allows traversal
traversable_types = [t for t in types_in_union if t in ["dict", "object", "any"]]

if not traversable_types:
    # None allow nested access
    return (False, None)

# At least one allows traversal - check for warnings
warning = None
if "any" in traversable_types and len(path_parts) > 0:
    warning = ValidationWarning(
        template=full_template,
        node_id=output_info.get("node_id"),
        node_type=output_info.get("node_type"),
        output_key=output_key,
        output_type=output_type,
        reason=f"Output type '{output_type}' - cannot verify statically",
        nested_path=".".join(path_parts)
    )

return (True, warning)
```

---

## 7. Gap Analysis: What's Missing for Type Checking

### 7.1 ✅ What We Have

1. **Type Definitions**:
   - Full EIF support (str, int, float, bool, dict, list, any)
   - Union types (`dict|str`)
   - Nested structures
   - Type metadata in registry

2. **Type Storage**:
   - Registry stores complete type info
   - Accessible via `get_nodes_metadata()`
   - Includes structure for nested paths

3. **Template Path Validation**:
   - Validates paths exist
   - Checks if types allow traversal
   - Generates warnings for `any` types

4. **Template Resolution**:
   - Path parsing with array indices
   - Type preservation for simple templates
   - Runtime value extraction

### 7.2 ❌ What's Missing

**1. Type Compatibility Logic**

Currently missing:
```python
def is_type_compatible(source_type: str, target_type: str) -> bool:
    """Check if source_type can be used where target_type is expected."""
    # Not implemented!
```

**2. Type Inference for Template Paths**

Need to determine:
```python
# Given: ${node.response.data[0].field}
# Infer: What is the type of this path?
def infer_template_type(
    template: str,
    workflow_ir: dict,
    registry: Registry
) -> Optional[str]:
    """Infer the type of a template variable path."""
    # Not implemented!
```

**3. Parameter Type Lookup**

Need to find expected type:
```python
# Given: node="http-request", param="timeout"
# Find: Expected type is "int"
def get_parameter_type(
    node_type: str,
    param_name: str,
    registry: Registry
) -> Optional[str]:
    """Get expected type for a node parameter."""
    # Not implemented!
```

**4. Type Mismatch Error Generation**

Need better errors:
```python
# Current: "Template variable ${x} has no valid source"
# Needed: "Type mismatch: ${node.status} is 'str' but parameter 'count' expects 'int'"
```

---

## 8. Type Compatibility Implementation Plan

### 8.1 Type Compatibility Matrix

```python
# Basic compatibility rules
TYPE_COMPATIBILITY_MATRIX = {
    # source → allowed targets
    "any": ["any", "str", "int", "float", "bool", "dict", "list"],  # any compatible with all
    "str": ["any", "str"],
    "int": ["any", "int", "float"],  # int can be used as float
    "float": ["any", "float"],
    "bool": ["any", "bool", "str"],  # bool can be stringified
    "dict": ["any", "dict"],
    "list": ["any", "list"],
}

def is_type_compatible(source_type: str, target_type: str) -> bool:
    """Check if source_type can be used where target_type is expected.

    Args:
        source_type: Type of the value being provided
        target_type: Type expected by the parameter

    Returns:
        True if compatible

    Examples:
        >>> is_type_compatible("int", "float")
        True  # int can be used as float
        >>> is_type_compatible("str", "int")
        False  # str cannot be used as int
        >>> is_type_compatible("any", "str")
        True  # any is compatible with everything
    """
    # Exact match
    if source_type == target_type:
        return True

    # Handle union types in source
    if "|" in source_type:
        source_types = [t.strip() for t in source_type.split("|")]
        # All source types must be compatible with target
        return all(is_type_compatible(st, target_type) for st in source_types)

    # Handle union types in target
    if "|" in target_type:
        target_types = [t.strip() for t in target_type.split("|")]
        # Source must be compatible with at least one target type
        return any(is_type_compatible(source_type, tt) for tt in target_types)

    # Check matrix
    return target_type in TYPE_COMPATIBILITY_MATRIX.get(source_type, [])
```

### 8.2 Template Type Inference

```python
def infer_template_type(
    template: str,
    workflow_ir: dict,
    node_outputs: dict[str, Any]
) -> Optional[str]:
    """Infer the type of a template variable path.

    Args:
        template: Template variable (e.g., "node.response.data[0].field")
        workflow_ir: Workflow IR for namespacing context
        node_outputs: Node output metadata from registry

    Returns:
        Inferred type string or None if cannot infer

    Examples:
        >>> # ${node.result} where result: dict
        >>> infer_template_type("node.result", workflow_ir, node_outputs)
        "dict"

        >>> # ${node.result.count} where result has structure
        >>> infer_template_type("node.result.count", workflow_ir, node_outputs)
        "int"
    """
    parts = template.split(".")
    base_var = parts[0]
    enable_namespacing = workflow_ir.get("enable_namespacing", True)

    # Check if base_var is a node ID (when namespacing enabled)
    if enable_namespacing:
        node_ids = {n.get("id") for n in workflow_ir.get("nodes", [])}
        if base_var in node_ids:
            # Namespaced node output: node.output_key.nested.path
            if len(parts) < 2:
                return None  # Invalid: just node ID

            node_output_key = f"{base_var}.{parts[1]}"
            if node_output_key not in node_outputs:
                return None

            output_info = node_outputs[node_output_key]

            # No nested path - return base type
            if len(parts) == 2:
                return output_info.get("type", "any")

            # Nested path - traverse structure
            return _infer_nested_type(parts[2:], output_info)

    # Not a node reference - check direct outputs
    if base_var in node_outputs:
        output_info = node_outputs[base_var]

        if len(parts) == 1:
            return output_info.get("type", "any")

        return _infer_nested_type(parts[1:], output_info)

    # Cannot infer (input parameter, etc.)
    return None

def _infer_nested_type(
    path_parts: list[str],
    output_info: dict[str, Any]
) -> Optional[str]:
    """Infer type by traversing nested structure.

    Args:
        path_parts: Remaining path parts to traverse
        output_info: Output metadata with structure

    Returns:
        Inferred type or None
    """
    structure = output_info.get("structure", {})

    # No structure - return base type if allows traversal
    if not structure:
        base_type = output_info.get("type", "any")
        if base_type in ["dict", "object", "any"]:
            return "any"  # Unknown nested type
        return None

    # Traverse structure
    current = structure
    for part in path_parts:
        # Remove array indices for lookup
        field_name = re.sub(r"\[\d+\]", "", part)

        if field_name not in current:
            return None

        field_info = current[field_name]

        if isinstance(field_info, dict) and "type" in field_info:
            # Reached a typed field
            if part == path_parts[-1]:
                # This is the final field
                return field_info["type"]
            else:
                # More to traverse
                current = field_info.get("structure", {})
                if not current:
                    # No more structure info
                    return "any"
        else:
            return None

    return None
```

### 8.3 Parameter Type Lookup

```python
def get_parameter_type(
    node_type: str,
    param_name: str,
    registry: Registry
) -> Optional[str]:
    """Get expected type for a node parameter.

    Args:
        node_type: Node type name
        param_name: Parameter name
        registry: Registry instance

    Returns:
        Expected type string or None if not found
    """
    nodes_metadata = registry.get_nodes_metadata([node_type])

    if node_type not in nodes_metadata:
        return None

    interface = nodes_metadata[node_type]["interface"]
    params = interface.get("params", [])

    for param in params:
        if isinstance(param, dict) and param.get("key") == param_name:
            return param.get("type", "any")

    return None
```

### 8.4 Type Checking Integration Point

**Add to template_validator.py**:

```python
def validate_template_types(
    workflow_ir: dict[str, Any],
    available_params: dict[str, Any],
    registry: Registry
) -> list[str]:
    """Validate template variable types match parameter expectations.

    Args:
        workflow_ir: Workflow IR
        available_params: Available parameters
        registry: Registry instance

    Returns:
        List of type mismatch errors
    """
    errors = []

    # Extract node outputs for type inference
    node_outputs = TemplateValidator._extract_node_outputs(workflow_ir, registry)

    # Check each node's parameters
    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        node_id = node.get("id")
        params = node.get("params", {})

        for param_name, param_value in params.items():
            # Check if parameter contains templates
            if not TemplateResolver.has_templates(param_value):
                continue

            # Get expected type for this parameter
            expected_type = get_parameter_type(node_type, param_name, registry)
            if not expected_type:
                continue

            # Extract templates from parameter value
            if isinstance(param_value, str):
                templates = TemplateResolver.extract_variables(param_value)

                # Check each template
                for template in templates:
                    # Infer template type
                    inferred_type = infer_template_type(template, workflow_ir, node_outputs)

                    if inferred_type and not is_type_compatible(inferred_type, expected_type):
                        errors.append(
                            f"Type mismatch in node '{node_id}' parameter '{param_name}': "
                            f"template ${{{template}}} has type '{inferred_type}' "
                            f"but parameter expects '{expected_type}'"
                        )

    return errors
```

---

## 9. Recommendations

### 9.1 High Priority

1. **Implement Type Compatibility Logic** (8.1)
   - Create `is_type_compatible()` function
   - Use type compatibility matrix
   - Handle union types properly

2. **Add Template Type Inference** (8.2)
   - Create `infer_template_type()` function
   - Support nested structure traversal
   - Handle namespaced node outputs

3. **Create Type Checking Validator** (8.4)
   - Integrate into existing validation pipeline
   - Generate clear error messages
   - Show both inferred and expected types

### 9.2 Medium Priority

4. **Enhance Error Messages**
   - Show type compatibility rules
   - Suggest type conversions where possible
   - Link to documentation

5. **Add Type Coercion Hints**
   - Suggest using string interpolation for str params
   - Recommend int() cast for numeric strings
   - Warn about precision loss (int → float)

### 9.3 Low Priority

6. **Type System Documentation**
   - Document type compatibility rules
   - Provide examples of valid/invalid type usage
   - Create migration guide for existing workflows

7. **Future Enhancements**
   - Generic types: `list[str]`, `dict[str, int]`
   - Custom type definitions
   - Type aliases for common patterns

---

## 10. Integration Points Summary

### 10.1 Existing Code to Leverage

**Registry Access**:
- `Registry.get_nodes_metadata()` - Get type info for nodes
- Registry stores complete interface metadata
- Full structure support already present

**Template System**:
- `TemplateResolver.extract_variables()` - Find templates in params
- `TemplateResolver.has_templates()` - Check if value contains templates
- Path parsing already handles arrays and nesting

**Validation Pipeline**:
- `TemplateValidator.validate_workflow_templates()` - Current entry point
- `_extract_node_outputs()` - Build type context
- `_validate_nested_path()` - Structure traversal logic

### 10.2 New Code to Add

**Type Logic** (new file: `src/pflow/runtime/type_checker.py`):
```python
- is_type_compatible()
- infer_template_type()
- _infer_nested_type()
- get_parameter_type()
- validate_template_types()
```

**Integration** (modify: `src/pflow/runtime/template_validator.py`):
```python
def validate_workflow_templates(...) -> tuple[list[str], list[ValidationWarning]]:
    # ... existing validation ...

    # ADD: Type checking
    type_errors = validate_template_types(workflow_ir, available_params, registry)
    errors.extend(type_errors)

    return (errors, warnings)
```

---

## 11. Example Type Checking Scenarios

### Scenario 1: Simple Type Mismatch

**Workflow**:
```json
{
  "nodes": [
    {
      "id": "fetch-data",
      "type": "http-request",
      "params": {"url": "https://api.example.com"}
    },
    {
      "id": "process",
      "type": "some-processor",
      "params": {
        "timeout": "${fetch-data.response.message}"  // Type mismatch!
      }
    }
  ]
}
```

**Type Analysis**:
- Template: `fetch-data.response.message`
- Inferred type: `str` (from http-request response structure)
- Expected type: `int` (from some-processor timeout param)
- Compatible: ❌ NO

**Error**:
```
Type mismatch in node 'process' parameter 'timeout':
template ${fetch-data.response.message} has type 'str' but parameter expects 'int'

Suggestion: Convert to integer or use a different field
```

### Scenario 2: Union Type Compatibility

**Workflow**:
```json
{
  "nodes": [
    {
      "id": "fetch",
      "type": "mcp-api-fetch",
      "params": {}
    },
    {
      "id": "display",
      "type": "llm",
      "params": {
        "prompt": "Analyze: ${fetch.result}"  // Union type dict|str
      }
    }
  ]
}
```

**Type Analysis**:
- Template: `fetch.result`
- Inferred type: `dict|str` (from MCP node outputSchema)
- Expected type: `str` (prompt parameter)
- Compatible: ✅ YES (dict|str contains str)

**Result**: No error (passes type checking)

### Scenario 3: Nested Structure Type Inference

**Workflow**:
```json
{
  "nodes": [
    {
      "id": "get-issue",
      "type": "github-get-issue",
      "params": {"issue_number": 123}
    },
    {
      "id": "process",
      "type": "some-node",
      "params": {
        "user_id": "${get-issue.issue_data.user.id}",  // Should be int
        "username": "${get-issue.issue_data.user.login}"  // Should be str
      }
    }
  ]
}
```

**Type Analysis**:
- Template 1: `get-issue.issue_data.user.id`
  - Traverse: issue_data (dict) → user (dict) → id (int)
  - Inferred type: `int`
  - Expected type: `int`
  - Compatible: ✅ YES

- Template 2: `get-issue.issue_data.user.login`
  - Traverse: issue_data (dict) → user (dict) → login (str)
  - Inferred type: `str`
  - Expected type: `str`
  - Compatible: ✅ YES

**Result**: No errors (all types match)

---

## 12. Testing Strategy

### Unit Tests

**test_type_compatibility.py**:
```python
def test_exact_type_match():
    assert is_type_compatible("str", "str") == True

def test_int_to_float_compatible():
    assert is_type_compatible("int", "float") == True

def test_str_to_int_incompatible():
    assert is_type_compatible("str", "int") == False

def test_any_compatible_with_all():
    assert is_type_compatible("any", "str") == True
    assert is_type_compatible("any", "int") == True

def test_union_type_source():
    # dict|str is compatible with str (contains str)
    assert is_type_compatible("dict|str", "str") == True
    # dict|str is not compatible with int (no int in union)
    assert is_type_compatible("dict|str", "int") == False

def test_union_type_target():
    # str is compatible with str|int (str is in target union)
    assert is_type_compatible("str", "str|int") == True
```

**test_template_type_inference.py**:
```python
def test_infer_simple_output_type(workflow_ir, node_outputs):
    # ${node.result} where result: dict
    inferred = infer_template_type("node.result", workflow_ir, node_outputs)
    assert inferred == "dict"

def test_infer_nested_field_type(workflow_ir, node_outputs):
    # ${node.data.count} where count: int
    inferred = infer_template_type("node.data.count", workflow_ir, node_outputs)
    assert inferred == "int"

def test_infer_array_access_type(workflow_ir, node_outputs):
    # ${node.items[0].name} where name: str
    inferred = infer_template_type("node.items[0].name", workflow_ir, node_outputs)
    assert inferred == "str"
```

### Integration Tests

**test_type_checking_integration.py**:
```python
def test_type_mismatch_detected():
    workflow_ir = {
        "nodes": [
            {"id": "n1", "type": "string-producer", "params": {}},
            {"id": "n2", "type": "int-consumer", "params": {
                "count": "${n1.result}"  # str → int mismatch
            }}
        ]
    }

    errors, warnings = validate_workflow_templates(workflow_ir, {}, registry)

    assert len(errors) > 0
    assert "Type mismatch" in errors[0]
    assert "count" in errors[0]

def test_compatible_types_pass():
    workflow_ir = {
        "nodes": [
            {"id": "n1", "type": "int-producer", "params": {}},
            {"id": "n2", "type": "int-consumer", "params": {
                "count": "${n1.result}"  # int → int match
            }}
        ]
    }

    errors, warnings = validate_workflow_templates(workflow_ir, {}, registry)

    # Filter out non-type errors
    type_errors = [e for e in errors if "Type mismatch" in e]
    assert len(type_errors) == 0
```

---

## 13. Conclusion

**Key Findings**:

1. ✅ **Type system foundation is solid**
   - Enhanced Interface Format supports all needed types
   - Registry stores complete type metadata
   - Nested structures fully supported

2. ✅ **Template system is ready**
   - Path parsing handles complex cases
   - Validation infrastructure exists
   - Integration points are clear

3. ❌ **Missing: Type compatibility logic**
   - Need `is_type_compatible()` function
   - Need `infer_template_type()` function
   - Need integration into validation pipeline

**Implementation Complexity**: **Low to Medium**

- Core logic is straightforward (type compatibility matrix)
- Integration point is well-defined (template_validator.py)
- Most infrastructure already exists
- ~300-500 lines of new code estimated

**Recommendation**: ✅ **Proceed with implementation**

The type system investigation reveals that pflow has all the necessary infrastructure for schema-aware type checking. The missing pieces are localized and well-scoped. This is a high-value, low-risk enhancement that will significantly improve workflow reliability.

**Next Steps**:
1. Create `type_checker.py` with core functions
2. Integrate into `template_validator.py`
3. Add comprehensive tests
4. Update error messages
5. Document type compatibility rules
