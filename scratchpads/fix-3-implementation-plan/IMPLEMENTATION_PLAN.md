# Fix 3: Schema-Aware Type Checking - Comprehensive Implementation Plan

**Date**: 2025-10-20
**Author**: Claude (Sonnet 4.5)
**Status**: Ready for Implementation
**Complexity**: Medium (3-5 days)
**Risk**: Low

---

## Executive Summary

### Problem Statement

When template variables resolve to types incompatible with their target parameters, pflow currently:
1. **Fails at runtime** (during MCP validation) instead of compile-time
2. **Shows cryptic errors** like "Input should be a valid string [type=string_type, input_value=dict]"
3. **Cascades into repair attempts** that send literal template strings to external APIs

**Example**:
```json
{
  "nodes": [
    {"id": "llm", "type": "llm", "params": {"prompt": "Return JSON"}},
    {"id": "slack", "type": "mcp-slack-SEND_MESSAGE", "params": {
      "markdown_text": "${llm.response}"  // ❌ dict → str type mismatch
    }}
  ]
}
```

### Proposed Solution

Implement **compile-time type checking** that:
- Validates template variable types match expected parameter types
- Detects mismatches BEFORE workflow execution
- Provides clear, actionable error messages with suggestions
- Leverages existing type metadata from Enhanced Interface Format

**After Fix**:
```
❌ Type mismatch in node 'slack' parameter 'markdown_text':
   Template ${llm.response} has type 'dict'
   But parameter 'markdown_text' expects type 'str'

💡 Suggestion: Access a specific field instead:
   - ${llm.response.message}
   - ${llm.response.text}
   Or serialize to JSON string
```

### Success Metrics

- ✅ **90%+ detection rate** - Catch type mismatches at compile-time
- ✅ **Zero false positives** - Valid workflows still pass
- ✅ **Clear errors** - Users understand what's wrong and how to fix it
- ✅ **<100ms overhead** - Validation remains fast

### Implementation Overview

**What Already Exists** (Foundation):
- Type metadata in registry (Enhanced Interface Format)
- Template validation infrastructure
- Nested structure support
- Union type handling

**What We're Building** (~400 lines):
- Type compatibility logic
- Template type inference engine
- Parameter type lookup
- Enhanced error messages

**Integration Point**: `src/pflow/runtime/template_validator.py` (existing validation pipeline)

---

## Architecture Design

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Workflow Compilation                         │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ↓
         ┌────────────────────────────┐
         │  Template Validator        │
         │  (existing infrastructure) │
         └────────┬───────────────────┘
                  │
       ┌──────────┼──────────┐
       │          │          │
       ↓          ↓          ↓
  ┌────────┐ ┌────────┐ ┌──────────┐
  │ Syntax │ │  Path  │ │   Type   │ ← NEW
  │ Check  │ │ Check  │ │  Check   │
  └────────┘ └────────┘ └──────────┘
                              │
              ┌───────────────┼───────────────┐
              ↓               ↓               ↓
         ┌────────┐   ┌──────────┐   ┌──────────┐
         │  Type  │   │ Template │   │Parameter │
         │ Compat │   │   Type   │   │   Type   │
         │ Logic  │   │Inference │   │  Lookup  │
         └────────┘   └──────────┘   └──────────┘
              │               │               │
              └───────────────┴───────────────┘
                              │
                              ↓
                    ┌──────────────────┐
                    │  Type Mismatch   │
                    │     Errors       │
                    └──────────────────┘
```

### Component Responsibilities

#### 1. Type Compatibility Logic (`is_type_compatible()`)
**Purpose**: Determine if source type can be used where target type is expected

**Rules**:
- Exact match: `str` → `str` ✅
- Widening: `int` → `float` ✅
- Universal: `any` → anything ✅
- Rejection: `str` → `int` ❌

**Union Types**:
- Source union: ALL types must be compatible
- Target union: At least ONE type must be compatible

#### 2. Template Type Inference (`infer_template_type()`)
**Purpose**: Determine the type of a template variable path

**Capabilities**:
- Simple variables: `${url}` → lookup in inputs/outputs
- Nested paths: `${data.field}` → traverse structure metadata
- Array access: `${items[0].name}` → handle array indices
- Namespaced: `${node.output.field}` → node-specific lookup

**Output**: Type string (`str`, `int`, `dict|str`, etc.) or `None` if cannot infer

#### 3. Parameter Type Lookup (`get_parameter_type()`)
**Purpose**: Find expected type for a node parameter

**Data Source**: Registry metadata (interface.params)

**Output**: Expected type string or `None` if parameter not found

#### 4. Type Checking Validator (`validate_template_types()`)
**Purpose**: Orchestrate type checking across entire workflow

**Process**:
1. Extract node outputs (build type context)
2. Iterate through all nodes
3. For each parameter containing templates:
   - Infer template type
   - Look up expected parameter type
   - Check compatibility
   - Generate errors if mismatch

---

## Implementation Phases

### Phase 1: Core Type Logic (2 days)

**Deliverables**: New file `src/pflow/runtime/type_checker.py` with:
- `is_type_compatible(source: str, target: str) -> bool`
- `infer_template_type(template: str, ...) -> Optional[str]`
- `get_parameter_type(node_type: str, param: str, ...) -> Optional[str]`
- Supporting utilities

#### Task 1.1: Type Compatibility Matrix (4 hours)

**File**: `src/pflow/runtime/type_checker.py`

**Implementation**:
```python
"""Type checking utilities for template variable validation."""

from typing import Optional, Any
from pflow.registry.registry import Registry

# Type compatibility rules
TYPE_COMPATIBILITY_MATRIX = {
    "any": ["any", "str", "int", "float", "bool", "dict", "list"],
    "str": ["any", "str"],
    "int": ["any", "int", "float"],  # int can widen to float
    "float": ["any", "float"],
    "bool": ["any", "bool", "str"],  # bool can stringify
    "dict": ["any", "dict"],
    "list": ["any", "list"],
}

def is_type_compatible(source_type: str, target_type: str) -> bool:
    """Check if source_type can be used where target_type is expected.

    Args:
        source_type: Type of the value being provided
        target_type: Type expected by the parameter

    Returns:
        True if compatible, False otherwise

    Examples:
        >>> is_type_compatible("int", "float")
        True
        >>> is_type_compatible("str", "int")
        False
        >>> is_type_compatible("dict|str", "str")
        True  # Union contains str
    """
    # Exact match
    if source_type == target_type:
        return True

    # Handle union types in source (ALL must be compatible)
    if "|" in source_type:
        source_types = [t.strip() for t in source_type.split("|")]
        return all(is_type_compatible(st, target_type) for st in source_types)

    # Handle union types in target (ANY must be compatible)
    if "|" in target_type:
        target_types = [t.strip() for t in target_type.split("|")]
        return any(is_type_compatible(source_type, tt) for tt in target_types)

    # Check compatibility matrix
    return target_type in TYPE_COMPATIBILITY_MATRIX.get(source_type, [])
```

**Tests** (`tests/test_runtime/test_type_checker.py`):
```python
def test_exact_match():
    assert is_type_compatible("str", "str") == True

def test_int_to_float():
    assert is_type_compatible("int", "float") == True

def test_str_to_int_incompatible():
    assert is_type_compatible("str", "int") == False

def test_any_compatible():
    assert is_type_compatible("any", "str") == True
    assert is_type_compatible("any", "int") == True

def test_union_source_all_must_match():
    # dict|str → str: BOTH dict and str must be compatible with str
    # dict is NOT compatible with str, so False
    assert is_type_compatible("dict|str", "str") == False

    # str|any → str: str→str ✓, any→str ✓
    assert is_type_compatible("str|any", "str") == True

def test_union_target_any_must_match():
    # str → str|int: str matches str in union
    assert is_type_compatible("str", "str|int") == True

    # dict → str|int: dict matches neither
    assert is_type_compatible("dict", "str|int") == False
```

#### Task 1.2: Template Type Inference (6 hours)

**Implementation** (in `type_checker.py`):
```python
import re
from typing import Optional, Any

def infer_template_type(
    template: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any]
) -> Optional[str]:
    """Infer the type of a template variable path.

    Args:
        template: Template variable without ${} (e.g., "node.response.data")
        workflow_ir: Workflow IR for context
        node_outputs: Node output metadata from registry

    Returns:
        Inferred type string or None if cannot infer

    Examples:
        >>> infer_template_type("node.result", workflow_ir, outputs)
        "dict"
        >>> infer_template_type("node.result.count", workflow_ir, outputs)
        "int"
    """
    parts = template.split(".")
    base_var = parts[0]
    enable_namespacing = workflow_ir.get("enable_namespacing", True)

    # Check workflow inputs first
    workflow_inputs = workflow_ir.get("inputs", {})
    if base_var in workflow_inputs:
        input_def = workflow_inputs[base_var]
        if isinstance(input_def, dict) and "type" in input_def:
            if len(parts) == 1:
                return input_def["type"]
            # No nested structure for inputs (simple types)
            return None

    # Check if base_var is a node ID (when namespacing enabled)
    if enable_namespacing:
        node_ids = {n.get("id") for n in workflow_ir.get("nodes", [])}
        if base_var in node_ids:
            # Namespaced: node.output_key.nested.path
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

    # Direct output lookup (no namespacing or workflow input)
    if base_var in node_outputs:
        output_info = node_outputs[base_var]

        if len(parts) == 1:
            return output_info.get("type", "any")

        return _infer_nested_type(parts[1:], output_info)

    # Cannot infer
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

    # No structure - check if base type allows traversal
    if not structure:
        base_type = output_info.get("type", "any")
        types_in_union = [t.strip() for t in base_type.split("|")]
        if any(t in ["dict", "object", "any"] for t in types_in_union):
            return "any"  # Unknown nested type
        return None

    # Traverse structure
    current = structure
    for i, part in enumerate(path_parts):
        # Remove array indices for field lookup: items[0] → items
        field_name = re.sub(r"\[\d+\]", "", part)

        if field_name not in current:
            return None

        field_info = current[field_name]

        if isinstance(field_info, dict) and "type" in field_info:
            # This is a typed field
            if i == len(path_parts) - 1:
                # Final field - return its type
                return field_info["type"]
            else:
                # More to traverse
                current = field_info.get("structure", {})
                if not current:
                    # No more structure info
                    field_type = field_info["type"]
                    if field_type in ["dict", "object", "any"]:
                        return "any"
                    return None
        else:
            return None

    return None
```

**Tests**:
```python
def test_infer_simple_output():
    workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "n1"}]}
    node_outputs = {
        "n1.result": {"type": "dict", "node_id": "n1"}
    }

    assert infer_template_type("n1.result", workflow_ir, node_outputs) == "dict"

def test_infer_nested_field():
    workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "n1"}]}
    node_outputs = {
        "n1.data": {
            "type": "dict",
            "structure": {
                "count": {"type": "int", "description": "Count"}
            }
        }
    }

    assert infer_template_type("n1.data.count", workflow_ir, node_outputs) == "int"

def test_infer_unknown_field():
    workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "n1"}]}
    node_outputs = {"n1.result": {"type": "dict"}}

    # Unknown field in structure
    assert infer_template_type("n1.result.unknown", workflow_ir, node_outputs) == None

def test_infer_with_any_type():
    workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "mcp"}]}
    node_outputs = {"mcp.result": {"type": "any"}}

    # any type allows traversal but returns "any"
    assert infer_template_type("mcp.result.field", workflow_ir, node_outputs) == "any"
```

#### Task 1.3: Parameter Type Lookup (2 hours)

**Implementation** (in `type_checker.py`):
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

**Tests**:
```python
def test_get_parameter_type(registry):
    # Assuming registry has http node with timeout: int
    param_type = get_parameter_type("http", "timeout", registry)
    assert param_type == "int"

def test_get_parameter_type_not_found(registry):
    param_type = get_parameter_type("http", "nonexistent", registry)
    assert param_type is None

def test_get_parameter_type_invalid_node(registry):
    param_type = get_parameter_type("invalid-node", "param", registry)
    assert param_type is None
```

---

### Phase 2: Integration (1 day)

**Deliverables**: Modify `src/pflow/runtime/template_validator.py` to integrate type checking

#### Task 2.1: Type Validation Function (4 hours)

**Add to `template_validator.py`**:
```python
from pflow.runtime.type_checker import (
    infer_template_type,
    get_parameter_type,
    is_type_compatible
)

@staticmethod
def _validate_template_types(
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    registry: Registry
) -> list[str]:
    """Validate template variable types match parameter expectations.

    Args:
        workflow_ir: Workflow IR
        node_outputs: Node output metadata
        registry: Registry instance

    Returns:
        List of type mismatch errors
    """
    errors = []

    for node in workflow_ir.get("nodes", []):
        node_type = node.get("type")
        node_id = node.get("id")
        params = node.get("params", {})

        for param_name, param_value in params.items():
            # Skip non-template parameters
            if not TemplateResolver.has_templates(param_value):
                continue

            # Get expected type for this parameter
            expected_type = get_parameter_type(node_type, param_name, registry)
            if not expected_type or expected_type == "any":
                # No type constraint or accepts any type
                continue

            # Extract templates from parameter value
            if isinstance(param_value, str):
                templates = TemplateResolver.extract_variables(param_value)

                for template in templates:
                    # Infer template type
                    inferred_type = infer_template_type(
                        template,
                        workflow_ir,
                        node_outputs
                    )

                    # Skip if cannot infer (will be caught by path validation)
                    if not inferred_type:
                        continue

                    # Check compatibility
                    if not is_type_compatible(inferred_type, expected_type):
                        error_msg = (
                            f"Type mismatch in node '{node_id}' parameter '{param_name}': "
                            f"template ${{{template}}} has type '{inferred_type}' "
                            f"but parameter expects '{expected_type}'"
                        )

                        # Add suggestion for dict → str
                        if inferred_type in ["dict", "list"] and expected_type == "str":
                            error_msg += (
                                f"\n  💡 Suggestion: Access a specific field instead "
                                f"(e.g., ${{{template}.message}}) or serialize to JSON"
                            )

                        errors.append(error_msg)

    return errors
```

#### Task 2.2: Wire Into Validation Pipeline (2 hours)

**Modify `validate_workflow_templates()` in `template_validator.py`**:
```python
@staticmethod
def validate_workflow_templates(
    workflow_ir: dict[str, Any],
    available_params: dict[str, Any],
    registry: Registry
) -> tuple[list[str], list[ValidationWarning]]:
    """Validates all template variables in a workflow.

    Returns:
        Tuple of (errors, warnings)
    """
    errors: list[str] = []
    warnings: list[ValidationWarning] = []

    # 1. Syntax validation
    malformed_errors = TemplateValidator._validate_malformed_templates(workflow_ir)
    errors.extend(malformed_errors)
    if malformed_errors:
        return (errors, warnings)

    # 2. Extract templates
    all_templates = TemplateValidator._extract_all_templates(workflow_ir)

    # 3. Unused inputs
    unused_errors = TemplateValidator._validate_unused_inputs(workflow_ir, all_templates)
    errors.extend(unused_errors)

    # 4. Get node outputs
    node_outputs = TemplateValidator._extract_node_outputs(workflow_ir, registry)

    # 5. Path validation (existing)
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

    # 6. NEW: Type validation
    type_errors = TemplateValidator._validate_template_types(
        workflow_ir,
        node_outputs,
        registry
    )
    errors.extend(type_errors)

    return (errors, warnings)
```

**Tests** (`tests/test_runtime/test_template_validator_types.py`):
```python
def test_type_mismatch_detected(registry):
    workflow_ir = {
        "enable_namespacing": True,
        "nodes": [
            {"id": "producer", "type": "string-producer", "params": {}},
            {"id": "consumer", "type": "int-consumer", "params": {
                "count": "${producer.result}"  # str → int mismatch
            }}
        ]
    }

    errors, warnings = TemplateValidator.validate_workflow_templates(
        workflow_ir, {}, registry
    )

    type_errors = [e for e in errors if "Type mismatch" in e]
    assert len(type_errors) == 1
    assert "count" in type_errors[0]
    assert "str" in type_errors[0]
    assert "int" in type_errors[0]

def test_compatible_types_pass(registry):
    workflow_ir = {
        "enable_namespacing": True,
        "nodes": [
            {"id": "producer", "type": "int-producer", "params": {}},
            {"id": "consumer", "type": "int-consumer", "params": {
                "count": "${producer.result}"  # int → int OK
            }}
        ]
    }

    errors, warnings = TemplateValidator.validate_workflow_templates(
        workflow_ir, {}, registry
    )

    type_errors = [e for e in errors if "Type mismatch" in e]
    assert len(type_errors) == 0
```

---

### Phase 3: Testing & Refinement (1-2 days)

#### Task 3.1: Comprehensive Test Suite (1 day)

**Test Files**:
- `tests/test_runtime/test_type_checker.py` (unit tests for type logic)
- `tests/test_runtime/test_template_validator_types.py` (integration tests)
- `tests/test_integration/test_type_checking_workflows.py` (end-to-end)

**Coverage Goals**:
- Type compatibility: 100% (small matrix)
- Type inference: 90%+ (many edge cases)
- Integration: 85%+ (real workflows)

**Test Categories**:
1. **Basic type compatibility**
2. **Union type handling**
3. **Nested structure traversal**
4. **Array access type inference**
5. **MCP nodes with `any` outputs**
6. **Error message formatting**
7. **Performance (large workflows)**

#### Task 3.2: Real-World Validation (0.5 days)

**Test Against Existing Workflows**:
```bash
# Run validation on example workflows
uv run pflow validate examples/github-pr-analyzer.json
uv run pflow validate examples/slack-notification.json
```

**Verify**:
- No false positives on valid workflows
- Catches known type issues
- Error messages are clear

#### Task 3.3: Error Message Refinement (0.5 days)

**Enhance Error Messages**:
```python
def _format_type_mismatch_error(
    node_id: str,
    param_name: str,
    template: str,
    inferred_type: str,
    expected_type: str,
    node_outputs: dict
) -> str:
    """Format a clear type mismatch error with suggestions."""
    error = (
        f"❌ Type mismatch in node '{node_id}' parameter '{param_name}':\n"
        f"   Template ${{{template}}} has type '{inferred_type}'\n"
        f"   But parameter '{param_name}' expects type '{expected_type}'\n"
    )

    # Add context-specific suggestions
    if inferred_type == "dict" and expected_type == "str":
        # Try to suggest available fields
        suggestions = _suggest_dict_fields(template, node_outputs)
        if suggestions:
            error += f"\n💡 Suggestion: Access a specific field:\n"
            for field in suggestions[:3]:  # Top 3
                error += f"   - ${{{template}.{field}}}\n"
        else:
            error += (
                f"\n💡 Suggestion: Access a specific field like "
                f"${{{template}.message}} or serialize to JSON\n"
            )
    elif inferred_type == "int" and expected_type == "str":
        error += f"\n💡 Note: Integer will be automatically converted to string\n"

    return error
```

---

## Code Structure

### New File: `src/pflow/runtime/type_checker.py`

```python
"""Type checking utilities for template variable validation.

This module provides compile-time type checking for template variables,
ensuring that resolved values match expected parameter types.
"""

from typing import Optional, Any
import re
from pflow.registry.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver


# Type compatibility rules
TYPE_COMPATIBILITY_MATRIX = {...}

def is_type_compatible(source_type: str, target_type: str) -> bool:
    """Check if source type can be used where target type is expected."""
    ...

def infer_template_type(
    template: str,
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any]
) -> Optional[str]:
    """Infer the type of a template variable path."""
    ...

def _infer_nested_type(
    path_parts: list[str],
    output_info: dict[str, Any]
) -> Optional[str]:
    """Infer type by traversing nested structure."""
    ...

def get_parameter_type(
    node_type: str,
    param_name: str,
    registry: Registry
) -> Optional[str]:
    """Get expected type for a node parameter."""
    ...
```

**Size**: ~300 lines (including docstrings and comments)

### Modified File: `src/pflow/runtime/template_validator.py`

**Changes**:
- Import from `type_checker`
- Add `_validate_template_types()` static method
- Call it from `validate_workflow_templates()`

**Size**: +100 lines

---

## Integration Strategy

### Step-by-Step Integration

1. **Create `type_checker.py`** with type compatibility logic
2. **Write unit tests** for type checking functions
3. **Import in `template_validator.py`**
4. **Add `_validate_template_types()` method**
5. **Wire into `validate_workflow_templates()`**
6. **Run full test suite** to ensure no regressions
7. **Test against real workflows**
8. **Refine error messages** based on feedback

### Backwards Compatibility

**Guaranteed**:
- Existing workflows continue to work (only adds validation)
- No changes to runtime behavior
- No changes to registry format
- No changes to IR schema

**New Behavior**:
- Compile-time type errors for previously undetected issues
- Users may need to fix workflows that have latent bugs

**Migration Path**:
- Phase 1: Warnings only (don't block execution)
- Phase 2: Errors for obvious mismatches
- Phase 3: Strict mode (all mismatches are errors)

---

## Testing Strategy

### Unit Tests

**File**: `tests/test_runtime/test_type_checker.py`

**Coverage**:
- Type compatibility matrix (15 tests)
- Union type handling (8 tests)
- Template type inference (20 tests)
- Parameter type lookup (5 tests)

**Total**: ~50 unit tests

### Integration Tests

**File**: `tests/test_runtime/test_template_validator_types.py`

**Scenarios**:
- Simple type mismatches
- Complex nested structures
- Union types
- MCP nodes
- Error message formatting

**Total**: ~20 integration tests

### End-to-End Tests

**File**: `tests/test_integration/test_type_checking_workflows.py`

**Workflows**:
- GitHub PR analyzer (dict traversal)
- Slack notifications (str parameters)
- HTTP API chaining (mixed types)
- LLM workflows (JSON responses)

**Total**: ~10 E2E tests

### Performance Tests

**Goal**: <100ms overhead for type checking

**Benchmark**:
```python
def test_type_checking_performance():
    # Large workflow (50 nodes, 200 templates)
    large_workflow = generate_large_workflow(50, 200)

    start = time.time()
    errors, warnings = TemplateValidator.validate_workflow_templates(
        large_workflow, {}, registry
    )
    duration = time.time() - start

    assert duration < 0.1  # <100ms
```

---

## Risk Mitigation

### Risk 1: False Positives

**Problem**: Type checking incorrectly flags valid workflows

**Mitigation**:
- Start with warnings, not errors
- Extensive testing on real workflows
- Escape hatch: `type: any` for unknown types
- User feedback loop

**Validation**:
- Run against all example workflows
- Zero false positives required before enabling

### Risk 2: Union Type Complexity

**Problem**: Complex union type rules cause confusion

**Mitigation**:
- Clear documentation of compatibility rules
- Examples in error messages
- Conservative approach (allow if any type matches)

### Risk 3: MCP Node Dynamic Schemas

**Problem**: MCP nodes have `any` outputs

**Mitigation**:
- Detect `any` type and emit warnings, not errors
- Allow runtime validation for dynamic types
- Document MCP node behavior

### Risk 4: Performance Overhead

**Problem**: Type checking slows down validation

**Mitigation**:
- Cache node metadata lookups
- Early termination on missing type info
- Benchmark against large workflows
- Target <100ms overhead

---

## Timeline & Dependencies

### Dependencies

**Internal**:
- Registry system (✅ exists)
- Template resolver (✅ exists)
- Template validator (✅ exists)
- Enhanced Interface Format (✅ documented)

**External**: None

### Timeline Estimate

**Day 1-2: Core Type Logic**
- ✅ Hour 1-4: Type compatibility matrix + tests
- ✅ Hour 5-10: Template type inference + tests
- ✅ Hour 11-12: Parameter type lookup + tests

**Day 3: Integration**
- ✅ Hour 1-4: Add type validation function
- ✅ Hour 5-6: Wire into validation pipeline
- ✅ Hour 7-8: Integration tests

**Day 4: Testing**
- ✅ Hour 1-4: Comprehensive unit tests
- ✅ Hour 5-8: Real-world validation

**Day 5: Refinement**
- ✅ Hour 1-4: Error message enhancement
- ✅ Hour 5-8: Documentation + examples

**Total**: 3-5 days (depending on testing scope)

---

## Success Criteria

### Functional Requirements

✅ **Type mismatch detection**
- Detects `str` → `int` mismatches
- Detects `dict` → `str` mismatches
- Detects `list` → `int` mismatches

✅ **Union type handling**
- Correctly evaluates `dict|str` compatibility
- Handles `any` type properly
- Source and target unions work correctly

✅ **Nested structure support**
- Infers types for `${node.data.field}`
- Handles array access `${items[0].name}`
- Traverses 5 levels deep

✅ **Clear error messages**
- Shows template variable
- Shows inferred type
- Shows expected type
- Provides actionable suggestions

### Non-Functional Requirements

✅ **Performance**
- <100ms overhead for type checking
- Minimal memory footprint
- Scales to 100+ node workflows

✅ **Backwards compatibility**
- No changes to existing workflows
- No changes to runtime behavior
- Additive only (validation errors)

✅ **Maintainability**
- Well-documented code
- Comprehensive tests (>85% coverage)
- Clear architecture

---

## Examples

### Example 1: Simple Type Mismatch

**Workflow**:
```json
{
  "nodes": [
    {"id": "fetch", "type": "http", "params": {"url": "https://api.example.com"}},
    {"id": "llm", "type": "llm", "params": {
      "max_tokens": "${fetch.status_code}"  // int → int OK
    }}
  ]
}
```

**Result**: ✅ Passes (int compatible with int)

**Workflow**:
```json
{
  "nodes": [
    {"id": "fetch", "type": "http", "params": {"url": "https://api.example.com"}},
    {"id": "process", "type": "some-node", "params": {
      "timeout": "${fetch.response.message}"  // str → int mismatch
    }}
  ]
}
```

**Result**: ❌ Error
```
❌ Type mismatch in node 'process' parameter 'timeout':
   Template ${fetch.response.message} has type 'str'
   But parameter 'timeout' expects type 'int'
```

### Example 2: Dict to String Mismatch (The Original Bug!)

**Workflow**:
```json
{
  "nodes": [
    {"id": "llm", "type": "llm", "params": {"prompt": "Return JSON"}},
    {"id": "slack", "type": "mcp-slack-SEND_MESSAGE", "params": {
      "markdown_text": "${llm.response}"  // dict → str mismatch
    }}
  ]
}
```

**Result**: ❌ Error
```
❌ Type mismatch in node 'slack' parameter 'markdown_text':
   Template ${llm.response} has type 'dict'
   But parameter 'markdown_text' expects type 'str'

💡 Suggestion: Access a specific field instead:
   - ${llm.response.message}
   - ${llm.response.text}
   Or serialize to JSON
```

### Example 3: Union Type Compatibility

**Workflow**:
```json
{
  "nodes": [
    {"id": "mcp", "type": "mcp-api-call", "params": {}},
    {"id": "llm", "type": "llm", "params": {
      "prompt": "Analyze: ${mcp.result}"  // dict|str → str
    }}
  ]
}
```

**Result**: ✅ Passes (union contains str, so compatible)

---

## Next Steps

1. **Review this plan** with team/user
2. **Create implementation task** in `.taskmaster/tasks/`
3. **Begin Phase 1** (Core Type Logic)
4. **Iterate based on testing**
5. **Deploy and gather feedback**

---

**Ready to implement!** 🚀
