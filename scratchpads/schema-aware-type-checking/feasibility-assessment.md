# Schema-Aware Type Checking for Template Resolution - Feasibility Assessment

**Date**: 2025-10-20
**Context**: Evaluating the feasibility of adding runtime type validation for template variable resolution

## Executive Summary

**Verdict**: **MEDIUM COMPLEXITY** - Infrastructure exists, but requires careful integration and handling of edge cases.

**Key Findings**:
- ✅ Rich type information already available at runtime via registry metadata
- ✅ Template validator already validates paths and existence
- ⚠️ Type information varies in detail (some nodes have full schemas, others just `any`)
- ⚠️ MCP nodes have dynamic schemas that may not be available at compile time
- ⚠️ Need to balance compile-time vs runtime validation approaches

**Recommended Approach**: Extend existing `TemplateValidator` with type-aware path validation using registry metadata, with graceful degradation for `any` types.

---

## 1. Existing Schema/Type Information Infrastructure

### 1.1 Node Parameter Type Definitions

**Location**: Registry metadata extracted from node docstrings

**Source Files**:
- `src/pflow/registry/metadata_extractor.py` (lines 348-480)
- `src/pflow/registry/registry.py` (lines 243-273)

**Type Information Available**:

Nodes define their interfaces in docstrings using the Enhanced Interface Format:

```python
"""
Interface:
- Reads: shared["prompt"]: str  # Text prompt to send to model
- Writes: shared["response"]: any  # Model's response (auto-parsed JSON or string)
- Writes: shared["llm_usage"]: dict  # Token usage metrics
    - model: str  # Model identifier used
    - input_tokens: int  # Number of input tokens consumed
    - output_tokens: int  # Number of output tokens generated
- Params: model: str  # Model to use (default: gemini-2.5-flash)
"""
```

**Extracted Metadata Structure**:
```python
{
    "interface": {
        "outputs": [
            {
                "key": "response",
                "type": "any",
                "description": "Model's response"
            },
            {
                "key": "llm_usage",
                "type": "dict",
                "description": "Token usage metrics",
                "structure": {
                    "model": {"type": "str", "description": "Model identifier"},
                    "input_tokens": {"type": "int", "description": "..."},
                    ...
                }
            }
        ],
        "params": [
            {
                "key": "model",
                "type": "str",
                "description": "Model to use"
            }
        ]
    }
}
```

### 1.2 Type Detail Levels

**Highly Detailed** (HTTP node example):
```python
- Writes: shared["response"]: dict|str  # Response data
- Writes: shared["status_code"]: int  # HTTP status code
- Writes: shared["response_headers"]: dict  # Response headers
```

**Generic Types** (LLM node example):
```python
- Writes: shared["response"]: any  # Could be string OR dict
```

**Nested Structures** (supported):
```python
- Writes: shared["issue_data"]: dict
    - number: int
    - title: str
    - user: dict
      - login: str
      - id: int
```

### 1.3 Runtime Availability

**Registry Loading**: `src/pflow/registry/registry.py` (lines 43-82)
- Registry loads at startup
- Metadata cached in memory (`_cached_nodes`)
- Available to all components via `registry.load()`

**Compile-Time Access**: `src/pflow/runtime/compiler.py`
- Registry passed to `compile_ir_to_flow()` (line 929)
- Used for node instantiation (lines 103-237)
- Available during template validation (line 811)

**Template Validator Access**: `src/pflow/runtime/template_validator.py`
- Already receives `Registry` parameter (line 88)
- Already uses registry metadata for error messages (lines 456-516)
- Extracts node outputs with structure (lines 656-714)

---

## 2. Template Validator Capabilities

### 2.1 Current Validation (lines 87-173)

**What it does**:
- ✅ Validates template variables have sources
- ✅ Validates paths exist in node output structures
- ✅ Detects unused declared inputs
- ✅ Provides enhanced error messages with suggestions

**Example validation**:
```python
# Template: ${fetch-messages.msg}
# Node output: {"result": {"messages": [...]}}

# Current behavior:
# - Validates "fetch-messages" is a valid node ID
# - Validates "msg" exists in node outputs (it doesn't)
# - Suggests "result.messages" as alternative
```

### 2.2 Structure Flattening (lines 237-336)

**Function**: `_flatten_output_structure()`

Recursively flattens nested outputs into all accessible paths:

```python
# Input structure:
{
    "messages": {
        "type": "array",
        "items": {
            "type": "dict",
            "structure": {
                "text": {"type": "string"},
                "user": {"type": "string"}
            }
        }
    }
}

# Flattened paths:
[
    ("result", "dict"),
    ("result.messages", "array"),
    ("result.messages[0]", "dict"),
    ("result.messages[0].text", "string"),
    ("result.messages[0].user", "string")
]
```

**Key Capabilities**:
- Array index support (`[0]` notation)
- Nested structure traversal
- Depth limiting (MAX_FLATTEN_DEPTH = 5)
- Type preservation at each level

### 2.3 Path Validation (lines 716-788)

**Function**: `_validate_template_path()`

Current validation logic:
1. Check if base variable exists in `initial_params`
2. Check if it's a node ID (when namespacing enabled)
3. Validate nested path exists in structure
4. Return `(is_valid, optional_warning)`

**What's Missing**: Type checking!

```python
# Current: Only checks existence
if node_output_key in node_outputs:
    if len(parts) == 2:
        return (True, None)  # Valid path

# What we need: Also check type compatibility
if node_output_key in node_outputs:
    output_type = node_outputs[node_output_key]["type"]
    expected_type = get_parameter_type(node_id, param_key)
    if not types_compatible(output_type, expected_type):
        return (False, type_mismatch_warning)
```

### 2.4 Schema Access

**Already has it!** (lines 656-714)

```python
def _extract_node_outputs(workflow_ir, registry):
    """Extract full output structures from nodes using interface metadata."""
    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        nodes_metadata = registry.get_nodes_metadata([node_type])
        interface = nodes_metadata[node_type]["interface"]

        for output in interface["outputs"]:
            output_info = {
                "type": output.get("type", "any"),
                "structure": output.get("structure", {}),
                "node_id": node_id,
                "node_type": node_type
            }
```

**This gives us**:
- Output key name
- Output type (str, int, dict, list, any, etc.)
- Nested structure (for dicts/lists)
- Source node information

---

## 3. Node Interface System

### 3.1 Parameter Type Storage

**Where**: Registry JSON file (`~/.pflow/registry.json`)

**Example entry**:
```json
{
  "llm": {
    "module": "pflow.nodes.llm.llm",
    "class_name": "LLMNode",
    "type": "core",
    "interface": {
      "description": "General-purpose LLM node",
      "outputs": [
        {
          "key": "response",
          "type": "any",
          "description": "Model's response"
        },
        {
          "key": "llm_usage",
          "type": "dict",
          "description": "Token usage metrics",
          "structure": {
            "model": {"type": "str", "description": "..."},
            "input_tokens": {"type": "int", "description": "..."}
          }
        }
      ],
      "params": [
        {
          "key": "model",
          "type": "str",
          "description": "Model to use"
        }
      ]
    }
  }
}
```

### 3.2 Runtime vs Compile Time

**Compile Time** (when `compile_ir_to_flow()` is called):
- Registry loaded and cached
- All core nodes have metadata
- User nodes scanned and registered
- MCP nodes **may or may not** be registered (see section 4)

**Runtime** (during workflow execution):
- Registry reference passed to wrapped nodes
- Template resolution uses cached metadata
- No additional I/O needed

### 3.3 Lookup Pattern

**Getting parameter types for a node**:

```python
# 1. Get node metadata from registry
nodes_metadata = registry.get_nodes_metadata([node_type])
if node_type not in nodes_metadata:
    # Unknown node type
    return None

# 2. Extract interface
interface = nodes_metadata[node_type]["interface"]

# 3. Get parameter type
for param in interface["params"]:
    if param["key"] == param_name:
        return param["type"]
```

**Getting output types for a node**:

```python
# Already implemented in template_validator.py!
for output in interface["outputs"]:
    if output["key"] == output_name:
        return output["type"], output.get("structure", {})
```

---

## 4. MCP Node Complications

### 4.1 Dynamic Schema Discovery

**Problem**: MCP nodes have schemas that come from external servers

**Current Behavior** (`src/pflow/runtime/compiler.py` lines 271-299):
```python
def _validate_node_types(workflow_ir, registry):
    """Skip validation if registry has no real nodes (likely only MCP)."""
    nodes_data = registry.load()
    has_real_nodes = any(
        metadata.get("file_path") != "virtual://mcp"
        for metadata in nodes_data.values()
    )

    if not has_real_nodes:
        return  # Skip validation entirely
```

**This means**: MCP-only workflows bypass node type validation!

### 4.2 MCP Metadata Structure

**MCP nodes in registry**:
```json
{
  "mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY": {
    "module": "pflow.nodes.mcp.node",
    "class_name": "MCPNode",
    "type": "mcp",
    "file_path": "virtual://mcp",
    "interface": {
      "outputs": [
        {
          "key": "result",
          "type": "any",  // ⚠️ Often generic!
          "description": "Tool execution result"
        }
      ],
      "params": [...]
    }
  }
}
```

**Key Issues**:
1. Output types often `any` (tool responses vary)
2. Schemas fetched from MCP server at runtime
3. Registry may not have full schema at compile time
4. `virtual://mcp` marker indicates dynamic node

### 4.3 Handling Strategy

**Option A**: Skip type checking for MCP nodes (current approach)
- Simple to implement
- Matches current validation pattern
- Misses type errors in MCP workflows

**Option B**: Runtime validation for MCP nodes
- Check types during template resolution
- Emit warnings instead of errors
- More robust but adds runtime overhead

**Option C**: Best-effort validation
- Use schema if available in registry
- Fall back to runtime validation if `type: any`
- Emit `ValidationWarning` for runtime-validated paths

**Recommended**: Option C (matches existing `ValidationWarning` system)

---

## 5. Integration Points

### 5.1 Where Type Checking Fits

**Three potential locations**:

#### 5.1.1 Template Validation (Compile Time)

**File**: `src/pflow/runtime/template_validator.py`
**Function**: `validate_workflow_templates()` (line 87)

**Advantages**:
- ✅ Catch type mismatches before execution
- ✅ Can provide fix suggestions in error messages
- ✅ Already has registry access
- ✅ Already validates paths and existence

**Disadvantages**:
- ⚠️ Can't validate templates with runtime-dependent values
- ⚠️ MCP nodes may not have full schemas yet

**Example Enhancement**:
```python
def _validate_template_path(template, initial_params, node_outputs, workflow_ir, registry):
    # Existing path validation...
    is_valid, warning = _validate_path_exists(...)

    if is_valid:
        # NEW: Type checking
        type_warning = _check_type_compatibility(
            template=template,
            source_type=node_outputs[key]["type"],
            target_node=consuming_node,
            target_param=param_name,
            registry=registry
        )
        if type_warning:
            warnings.append(type_warning)

    return (is_valid, warnings)
```

#### 5.1.2 Template Resolution (Runtime)

**File**: `src/pflow/runtime/template_resolver.py`
**Function**: `resolve_nested()` (line 362)

**Advantages**:
- ✅ Can validate actual resolved values
- ✅ Catches type issues at resolution time
- ✅ Could do type coercion if desired

**Disadvantages**:
- ❌ Errors occur during execution (too late)
- ❌ No registry access (resolver is standalone)
- ❌ Would need significant refactoring

**Not recommended**: Resolver should stay simple

#### 5.1.3 Node Wrapper (Runtime)

**File**: `src/pflow/runtime/node_wrapper.py`
**Function**: `_run()` (line 171)

**Advantages**:
- ✅ Can validate resolved values before passing to node
- ✅ Has access to node's parameter schema
- ✅ Could emit warnings without breaking flow

**Disadvantages**:
- ⚠️ Per-node overhead
- ⚠️ Errors during execution (repair system would handle)
- ⚠️ Need to pass registry reference to wrapper

**Possible**: Could complement compile-time validation

### 5.2 Recommended Integration Strategy

**Two-Phase Approach**:

**Phase 1 - Compile Time (Primary)**:
- Extend `TemplateValidator._validate_template_path()`
- Add type checking after path validation
- Use registry metadata for source and target types
- Emit `ValidationWarning` for `any` types
- Fail with clear errors for definite mismatches

**Phase 2 - Runtime (Safety Net)**:
- Optional runtime validation in `TemplateAwareNodeWrapper`
- Only for templates with `any` types
- Log warnings, don't fail execution
- Could be enabled via flag

---

## 6. Specific Challenges & Blockers

### 6.1 Type System Complexity

**Challenge**: Python's type system is complex

**Type Compatibility Rules Needed**:
```python
def types_compatible(source_type: str, target_type: str) -> bool:
    # Exact match
    if source_type == target_type:
        return True

    # 'any' is compatible with anything
    if source_type == "any" or target_type == "any":
        return True  # But emit warning

    # Union types (e.g., "dict|str")
    source_types = set(source_type.split("|"))
    target_types = set(target_type.split("|"))
    if source_types & target_types:
        return True  # Overlap

    # Subtype relationships
    # - int can go to float?
    # - list can go to any?
    # - dict keys subset matching?

    # Type coercion
    # - Can we convert?

    return False
```

**Complexity Level**: Medium
- Start with simple exact matching
- Add union type support
- Consider coercion rules later

### 6.2 Nested Structure Validation

**Challenge**: Validating `${node.result.messages[0].text}` requires:

1. Resolve `node.result` → type `dict`
2. Check `messages` exists in structure → type `array`
3. Check array item type → `dict`
4. Check `text` exists in item structure → type `str`
5. Compare `str` with target parameter's expected type

**Current Infrastructure**:
- ✅ Path traversal exists (`_flatten_output_structure`)
- ✅ Type at each level tracked
- ⚠️ Need to integrate with parameter expectations

**Implementation**:
```python
def _validate_nested_path_types(
    path_parts: list[str],
    output_info: dict,
    target_param_type: str
) -> tuple[bool, Optional[TypeMismatchWarning]]:
    """Validate types along a nested path."""
    current_type = output_info.get("type")
    current_structure = output_info.get("structure", {})

    # Traverse path, tracking type at each step
    for i, part in enumerate(path_parts[:-1]):
        # Navigate structure
        # Update current_type
        # Check traversability

    # Final type check
    final_type = current_type
    if not types_compatible(final_type, target_param_type):
        return (False, TypeMismatchWarning(...))

    return (True, None)
```

### 6.3 Getting Target Parameter Type

**Challenge**: Where does `${llm.response}` go?

**Need to**:
1. Find which node uses this template
2. Find which parameter contains the template
3. Look up that parameter's expected type

**Current State**: Template validator doesn't track this!

**Required Enhancement**:
```python
def _build_template_usage_map(workflow_ir: dict) -> dict:
    """Build map of template → (node_id, param_key) usages."""
    usage_map = {}

    for node in workflow_ir["nodes"]:
        node_id = node["id"]
        for param_key, param_value in node.get("params", {}).items():
            templates = extract_templates(param_value)
            for template in templates:
                if template not in usage_map:
                    usage_map[template] = []
                usage_map[template].append((node_id, param_key))

    return usage_map
```

Then:
```python
def _validate_template_type(template, workflow_ir, registry):
    # 1. Find where template is used
    usages = usage_map.get(template, [])

    # 2. For each usage, get expected type
    for node_id, param_key in usages:
        node_type = get_node_type(workflow_ir, node_id)
        expected_type = get_param_type(registry, node_type, param_key)

        # 3. Get source type
        source_type = get_template_source_type(template, node_outputs)

        # 4. Check compatibility
        if not types_compatible(source_type, expected_type):
            emit_error(...)
```

**Complexity**: Medium (requires new mapping structure)

### 6.4 MCP Dynamic Schemas

**Challenge**: MCP tool schemas from external servers

**Current Handling** (`src/pflow/mcp/registrar.py`):
```python
def sync_mcp_tools(server_name: str, registry: Registry):
    """Fetch tool schemas from MCP server and register as nodes."""
    # Connect to server
    # Fetch tool list
    # Extract input/output schemas
    # Register in registry
```

**Schemas Available**: Yes, but at registry time (not necessarily at workflow build time)

**Type Information Quality**:
- ✅ Input parameters: Usually well-typed (from JSON schema)
- ⚠️ Output types: Often `any` or generic `object`
- ⚠️ Nested structures: May not be documented

**Strategy**:
```python
def _validate_mcp_template(template, node_type, registry):
    if node_type.startswith("mcp-"):
        # Check if we have schema
        metadata = registry.get_nodes_metadata([node_type])
        if not metadata:
            return (True, MCP_SCHEMA_UNAVAILABLE_WARNING)

        output_type = metadata["interface"]["outputs"][0]["type"]
        if output_type == "any":
            return (True, MCP_ANY_TYPE_WARNING)

        # Proceed with normal validation
```

---

## 7. Estimated Implementation Complexity

### 7.1 Simple Version (MVP)

**Scope**: Exact type matching, no nested paths, warnings for `any`

**Changes Required**:
1. Add `types_compatible()` function to `template_validator.py`
2. Add `_build_template_usage_map()` to track where templates are used
3. Modify `_validate_template_path()` to check types
4. Add new error class `TypeMismatchError`

**Effort**: 2-3 days
**Risk**: Low
**Value**: Medium (catches obvious type mismatches)

**Example errors caught**:
```python
# Template: ${llm.response} (type: any)
# Parameter: api_key (type: str)
# → WARNING: Runtime type check needed (type is 'any')

# Template: ${http.status_code} (type: int)
# Parameter: url (type: str)
# → ERROR: Type mismatch - cannot use int where str is expected
```

### 7.2 Medium Version (Recommended)

**Scope**: Union types, nested path validation, MCP handling

**Additional Changes**:
5. Add union type parsing (`dict|str` → `{"dict", "str"}`)
6. Enhance `_validate_nested_path()` with type tracking
7. Add MCP-specific handling
8. Enhanced error messages with suggestions

**Effort**: 5-7 days
**Risk**: Medium
**Value**: High

**Example errors caught**:
```python
# Template: ${fetch-messages.result.messages} (type: array)
# Parameter: message_text (type: str)
# → ERROR: Type mismatch - template resolves to array but parameter expects str
# → SUGGESTION: Did you mean ${fetch-messages.result.messages[0].text}?

# Template: ${http.response} (type: dict|str)
# Parameter: body (type: dict)
# → WARNING: Template type is union (dict|str), runtime value may be incompatible
```

### 7.3 Full Version

**Scope**: Type coercion, structure matching, runtime fallback

**Additional Changes**:
9. Add type coercion rules (int → str, etc.)
10. Add dict structure matching (subset checking)
11. Runtime validation in `TemplateAwareNodeWrapper`
12. Comprehensive test suite

**Effort**: 10-14 days
**Risk**: High
**Value**: Very High

**Example behaviors**:
```python
# Template: ${http.status_code} (type: int)
# Parameter: log_message (type: str)
# → OK (with coercion): int can be converted to str

# Template: ${issue.data} (type: dict, structure: {number, title, user})
# Parameter: issue_info (type: dict, structure: {number, title})
# → OK: Source has all required fields (superset)

# Template: ${mcp_tool.result} (type: any)
# → Runtime validation: Check type when value is actually resolved
```

---

## 8. Recommended Approach

### 8.1 Phased Implementation

**Phase 1: Foundation (Week 1)**

Add basic type checking to existing validator:

```python
# In template_validator.py

@dataclass
class TypeMismatchWarning:
    """Warning about type incompatibility."""
    template: str
    source_type: str
    target_node: str
    target_param: str
    expected_type: str
    suggestion: str

def types_compatible(source: str, target: str) -> bool:
    """Check if source type can be used where target type is expected."""
    if source == target:
        return True
    if source == "any" or target == "any":
        return True  # Allow but warn
    # Union types
    if "|" in source or "|" in target:
        source_set = set(source.split("|"))
        target_set = set(target.split("|"))
        return bool(source_set & target_set)
    return False

def _build_template_usage_map(workflow_ir):
    """Map templates to their usage sites."""
    # Implementation above
    pass

def _validate_template_types(workflow_ir, node_outputs, registry):
    """Validate types of all templates."""
    errors = []
    warnings = []

    usage_map = _build_template_usage_map(workflow_ir)

    for template, usages in usage_map.items():
        source_type = get_template_source_type(template, node_outputs)

        for node_id, param_key in usages:
            expected_type = get_param_expected_type(
                workflow_ir, node_id, param_key, registry
            )

            if not types_compatible(source_type, expected_type):
                if source_type == "any" or expected_type == "any":
                    warnings.append(TypeMismatchWarning(...))
                else:
                    errors.append(f"Type mismatch: {template} ...")

    return errors, warnings
```

**Phase 2: Error Messages (Week 2)**

Enhance error formatting:

```python
def _format_type_mismatch_error(
    template: str,
    source_type: str,
    source_node: str,
    target_node: str,
    target_param: str,
    expected_type: str
) -> str:
    """Create actionable type mismatch error."""
    lines = [
        f"Type mismatch in template ${{{template}}}",
        "",
        f"Source: {source_node} outputs type '{source_type}'",
        f"Target: {target_node}.{target_param} expects type '{expected_type}'",
    ]

    # Add suggestions
    if suggestion := find_compatible_path(source_node, expected_type):
        lines.append("")
        lines.append(f"Suggestion: Use ${{{suggestion}}} instead")

    return "\n".join(lines)
```

**Phase 3: Testing & Refinement (Week 3)**

- Comprehensive test suite
- Real-world workflow testing
- Documentation updates
- Performance optimization

### 8.2 Success Criteria

**Must Have**:
- ✅ Detects definite type mismatches (int → str, etc.)
- ✅ Warns on `any` types (runtime validation needed)
- ✅ Clear error messages with fix suggestions
- ✅ No false positives on valid workflows
- ✅ Handles MCP nodes gracefully

**Nice to Have**:
- Union type support
- Nested structure validation
- Type coercion suggestions
- Runtime fallback validation

### 8.3 Testing Strategy

**Unit Tests**:
```python
def test_type_validation_exact_match():
    """int → int should pass."""
    # Setup workflow with matching types
    errors, warnings = validate_workflow_templates(...)
    assert len(errors) == 0

def test_type_validation_mismatch():
    """int → str should fail."""
    # Setup workflow with mismatched types
    errors, warnings = validate_workflow_templates(...)
    assert len(errors) == 1
    assert "Type mismatch" in errors[0]

def test_type_validation_any_warns():
    """any → str should warn."""
    # Setup workflow with any type
    errors, warnings = validate_workflow_templates(...)
    assert len(errors) == 0
    assert len(warnings) == 1
    assert warnings[0].reason == "Runtime type check needed"

def test_type_validation_mcp_nodes():
    """MCP nodes with any type should warn."""
    # ...
```

**Integration Tests**:
```python
def test_e2e_type_mismatch_detection():
    """Real workflow with type error."""
    workflow_ir = {
        "nodes": [
            {"id": "http", "type": "http", ...},
            {"id": "llm", "type": "llm", "params": {
                "model": "${http.status_code}"  # int used as str
            }}
        ]
    }

    with pytest.raises(ValidationError) as exc:
        validate_workflow_templates(workflow_ir, ...)

    assert "Type mismatch" in str(exc.value)
```

---

## 9. Final Assessment

### 9.1 Infrastructure Readiness

| Component | Status | Notes |
|-----------|--------|-------|
| Type metadata in registry | ✅ Ready | Rich format with types & structures |
| Template path validation | ✅ Ready | Already validates existence |
| Registry access at validation | ✅ Ready | Registry passed to validator |
| Error message system | ✅ Ready | Enhanced errors with suggestions |
| Node parameter schemas | ⚠️ Partial | Some nodes use `any`, MCP nodes vary |
| Template usage tracking | ❌ Missing | Need to build usage map |
| Type compatibility logic | ❌ Missing | Need to implement |
| Runtime fallback | ❌ Missing | Optional future enhancement |

### 9.2 Risk Assessment

**Low Risk**:
- Infrastructure exists
- Isolated to validator module
- Can start with warnings only
- Easy to test

**Medium Risk**:
- Type system complexity
- MCP node handling
- False positive potential
- Performance overhead

**High Risk**:
- Breaking existing workflows (if too strict)
- Incomplete type information in nodes
- Edge cases in type compatibility

**Mitigation**:
- Start with opt-in warnings
- Gradual rollout (warnings → soft errors → hard errors)
- Comprehensive testing
- Clear error messages with escape hatches

### 9.3 Estimated Timeline

**Minimum Viable (MVP)**:
- **Week 1**: Basic implementation (exact matching, usage map, warnings)
- **Week 2**: Error messages and testing
- **Total**: 2 weeks

**Recommended Complete**:
- **Week 1**: Foundation (exact matching + unions + MCP handling)
- **Week 2**: Nested paths + error messages
- **Week 3**: Testing, refinement, documentation
- **Total**: 3 weeks

**Full Featured**:
- **Week 1-3**: Above
- **Week 4**: Type coercion + structure matching
- **Week 5**: Runtime validation + performance optimization
- **Total**: 5 weeks

### 9.4 Recommendation

**Implement the Recommended Complete version (3 weeks)**

**Rationale**:
1. Infrastructure exists - not starting from scratch
2. Medium complexity - challenging but tractable
3. High value - catches real bugs early
4. Natural extension of existing validation
5. Gradual rollout possible (warnings first)

**Key Success Factors**:
1. Build template usage map early
2. Start with warnings, not errors
3. Comprehensive test coverage
4. Clear error messages with suggestions
5. Handle `any` types gracefully
6. MCP node special casing

**Alternatives**:
- **Start with MVP (2 weeks)**: Get basic value quickly, iterate
- **Full implementation (5 weeks)**: Wait for clearer type requirements
- **Skip entirely**: Focus on runtime repair instead

---

## 10. Example Implementation Sketch

### 10.1 Core Type Checking Logic

```python
# In src/pflow/runtime/template_validator.py

from dataclasses import dataclass
from typing import Optional

@dataclass
class TypeMismatchError:
    """Type mismatch detected in template."""
    template: str
    source_node: str
    source_output: str
    source_type: str
    target_node: str
    target_param: str
    expected_type: str
    suggestion: Optional[str] = None

class TypeChecker:
    """Type compatibility checking for templates."""

    @staticmethod
    def parse_type(type_str: str) -> set[str]:
        """Parse type string into set of types."""
        return set(type_str.split("|"))

    @staticmethod
    def is_compatible(source_type: str, target_type: str) -> tuple[bool, Optional[str]]:
        """Check if source type can be used where target type is expected.

        Returns:
            (is_compatible, warning_reason)
        """
        source_types = TypeChecker.parse_type(source_type)
        target_types = TypeChecker.parse_type(target_type)

        # Exact match
        if source_type == target_type:
            return (True, None)

        # Any type requires runtime validation
        if "any" in source_types or "any" in target_types:
            return (True, "Runtime type validation needed (type is 'any')")

        # Union type overlap
        if source_types & target_types:
            if len(source_types) > 1 or len(target_types) > 1:
                return (True, f"Union type - runtime value may vary ({source_type})")
            return (True, None)

        # No compatibility
        return (False, None)

def _build_template_usage_map(workflow_ir: dict) -> dict[str, list[tuple[str, str]]]:
    """Build mapping of template variables to their usage sites.

    Returns:
        Dict mapping template_var -> [(node_id, param_key), ...]
    """
    usage_map = {}

    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id")
        params = node.get("params", {})

        # Extract templates from all param values
        for param_key, param_value in params.items():
            templates = _extract_templates_from_value(param_value)
            for template in templates:
                if template not in usage_map:
                    usage_map[template] = []
                usage_map[template].append((node_id, param_key))

    return usage_map

def _extract_templates_from_value(value: Any) -> set[str]:
    """Recursively extract template variables from a value."""
    templates = set()

    if isinstance(value, str):
        matches = TemplateValidator._PERMISSIVE_PATTERN.findall(value)
        templates.update(matches)
    elif isinstance(value, dict):
        for v in value.values():
            templates.update(_extract_templates_from_value(v))
    elif isinstance(value, list):
        for item in value:
            templates.update(_extract_templates_from_value(item))

    return templates

def _get_param_expected_type(
    workflow_ir: dict,
    node_id: str,
    param_key: str,
    registry: Registry
) -> Optional[str]:
    """Get the expected type for a node parameter."""
    # Find node in workflow
    node = next((n for n in workflow_ir["nodes"] if n["id"] == node_id), None)
    if not node:
        return None

    node_type = node.get("type")
    if not node_type:
        return None

    # Get node metadata
    nodes_metadata = registry.get_nodes_metadata([node_type])
    if node_type not in nodes_metadata:
        return None

    interface = nodes_metadata[node_type]["interface"]

    # Search in params
    for param in interface.get("params", []):
        if param["key"] == param_key:
            return param.get("type", "any")

    return "any"  # Unknown param, assume any

def _validate_template_types(
    workflow_ir: dict,
    node_outputs: dict[str, Any],
    registry: Registry
) -> tuple[list[str], list[TypeMismatchError]]:
    """Validate types of all template variables.

    Returns:
        (errors, warnings)
    """
    errors = []
    warnings = []

    usage_map = _build_template_usage_map(workflow_ir)

    for template, usages in usage_map.items():
        # Get source type
        source_info = _get_template_source_info(template, node_outputs, workflow_ir)
        if not source_info:
            continue  # Path validation will catch this

        source_type = source_info.get("type", "any")
        source_node = source_info.get("node_id", "unknown")

        # Check each usage
        for target_node_id, target_param_key in usages:
            expected_type = _get_param_expected_type(
                workflow_ir, target_node_id, target_param_key, registry
            )

            if not expected_type:
                continue

            # Type check
            is_compatible, warning_reason = TypeChecker.is_compatible(
                source_type, expected_type
            )

            if not is_compatible:
                # Create error
                error_msg = _format_type_mismatch_error(
                    template=template,
                    source_type=source_type,
                    source_node=source_node,
                    target_node=target_node_id,
                    target_param=target_param_key,
                    expected_type=expected_type
                )
                errors.append(error_msg)
            elif warning_reason:
                # Create warning
                warnings.append(TypeMismatchError(
                    template=template,
                    source_node=source_node,
                    source_output=template.split(".")[1] if "." in template else template,
                    source_type=source_type,
                    target_node=target_node_id,
                    target_param=target_param_key,
                    expected_type=expected_type,
                    suggestion=warning_reason
                ))

    return errors, warnings

def _format_type_mismatch_error(
    template: str,
    source_type: str,
    source_node: str,
    target_node: str,
    target_param: str,
    expected_type: str
) -> str:
    """Format a type mismatch error with suggestions."""
    lines = [
        f"Type mismatch for template ${{{template}}}",
        "",
        f"  Source: {source_node} outputs type '{source_type}'",
        f"  Target: {target_node}.{target_param} expects type '{expected_type}'",
    ]

    # TODO: Add suggestions for compatible alternative paths

    return "\n".join(lines)

# Integrate into existing validation function
def validate_workflow_templates(
    workflow_ir: dict[str, Any],
    available_params: dict[str, Any],
    registry: Registry
) -> tuple[list[str], list[ValidationWarning]]:
    """Validates all template variables in a workflow."""
    errors: list[str] = []
    warnings: list[ValidationWarning] = []

    # ... existing validation ...

    # NEW: Type checking
    type_errors, type_warnings = _validate_template_types(
        workflow_ir, node_outputs, registry
    )
    errors.extend(type_errors)
    # warnings.extend(type_warnings)  # Could convert to ValidationWarning

    return (errors, warnings)
```

### 10.2 Testing Example

```python
# In tests/test_runtime/test_template_validator_types.py

def test_type_validation_exact_match():
    """Should pass when types match exactly."""
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "http", "type": "http"},
            {"id": "process", "type": "llm", "params": {
                "prompt": "${http.response}"  # str or dict -> str (OK via coercion)
            }}
        ]
    }

    registry = setup_test_registry()
    errors, warnings = validate_workflow_templates(workflow_ir, {}, registry)

    assert len(errors) == 0

def test_type_validation_mismatch():
    """Should error when types are incompatible."""
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "http", "type": "http"},
            {"id": "llm", "type": "llm", "params": {
                "model": "${http.status_code}"  # int -> str (ERROR)
            }}
        ]
    }

    registry = setup_test_registry()
    errors, warnings = validate_workflow_templates(workflow_ir, {}, registry)

    assert len(errors) == 1
    assert "Type mismatch" in errors[0]
    assert "status_code" in errors[0]
    assert "int" in errors[0]
    assert "str" in errors[0]

def test_type_validation_any_type_warning():
    """Should warn when source or target is 'any'."""
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "llm", "type": "llm"},
            {"id": "http", "type": "http", "params": {
                "url": "${llm.response}"  # any -> str (WARNING)
            }}
        ]
    }

    registry = setup_test_registry()
    errors, warnings = validate_workflow_templates(workflow_ir, {}, registry)

    assert len(errors) == 0
    assert len(warnings) == 1
    assert "Runtime type validation needed" in warnings[0].suggestion
```

---

## Conclusion

**Schema-aware type checking is FEASIBLE with MEDIUM complexity.**

The infrastructure exists, the integration point is clear, and the value is high. I recommend implementing the **3-week Recommended Complete version** with:

1. Basic type compatibility checking
2. Union type support
3. MCP node handling
4. Enhanced error messages
5. Comprehensive testing

Start with warnings-only mode, then graduate to errors after validating against real workflows.
