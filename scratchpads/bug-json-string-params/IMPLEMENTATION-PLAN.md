# Implementation Plan: Fix JSON Auto-Parsing for String-Typed Parameters

## Problem Summary

When an MCP tool (or any node) declares a parameter as `str` but expects JSON content inside, pflow incorrectly passes Python dicts/lists instead of JSON strings. This breaks MCP tools like Discord's `execute_action` that expect `path_params: str` containing `'{"channel_id": "123"}'`.

**Two affected paths:**
1. **CLI `registry run`**: `infer_type()` parses JSON → dict before we know the target type
2. **Workflow execution**: JSON objects in workflow files become dicts, never serialized back

---

## Solution Overview

Create a shared utility for type-aware coercion and use it in both paths:
- `src/pflow/core/param_coercion.py` - New shared utility
- `src/pflow/runtime/node_wrapper.py` - Add reverse coercion (dict→str)
- `src/pflow/cli/registry_run.py` - Add coercion before node.set_params()

---

## Implementation Steps

### Step 1: Create Shared Utility (`src/pflow/core/param_coercion.py`)

**New file with single function:**

```python
"""Parameter type coercion utilities.

Provides bidirectional coercion between Python types and declared parameter types:
- str → dict/list: Parse JSON when expected type is dict/list
- dict/list → str: Serialize to JSON when expected type is str
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def coerce_to_declared_type(
    value: Any,
    expected_type: str | None,
) -> Any:
    """Coerce a value to match its declared parameter type.

    Handles bidirectional conversion:
    - dict/list → str: Serialize to JSON when expected_type is "str"/"string"
    - Already correct type: Return unchanged
    - No expected_type: Return unchanged

    This enables MCP tools that declare `param: str` but expect JSON content
    to receive properly serialized JSON strings instead of Python dicts.

    Args:
        value: The value to potentially coerce
        expected_type: Declared type from node interface ("str", "dict", etc.)

    Returns:
        Coerced value if conversion needed, otherwise original value

    Examples:
        >>> coerce_to_declared_type({"key": "value"}, "str")
        '{"key": "value"}'
        >>> coerce_to_declared_type([1, 2, 3], "str")
        '[1, 2, 3]'
        >>> coerce_to_declared_type("hello", "str")
        'hello'
        >>> coerce_to_declared_type({"key": "value"}, "dict")
        {'key': 'value'}
    """
    if expected_type is None:
        return value

    # Normalize type aliases
    normalized_type = expected_type.lower()

    # dict/list → str: Serialize to JSON
    if normalized_type in ("str", "string"):
        if isinstance(value, (dict, list)):
            serialized = json.dumps(value)
            logger.debug(
                f"Coerced {type(value).__name__} to JSON string for str-typed parameter",
                extra={"original_type": type(value).__name__, "target_type": "str"},
            )
            return serialized

    # Value already matches or no conversion needed
    return value
```

**Key design decisions:**
- Single function, single responsibility
- Only handles dict/list → str direction (str → dict already exists in `json_utils.py`)
- Returns original value if no coercion needed (safe fallback)
- Debug logging for visibility

---

### Step 2: Integrate into `node_wrapper.py` (Workflow Execution Path)

**Location:** `src/pflow/runtime/node_wrapper.py`, lines 817-832

**Current code (str → dict/list):**
```python
# Auto-parse JSON strings for structured parameters (only simple templates)
if is_simple_template and isinstance(resolved_value, str):
    expected_type = self._expected_types.get(key)
    if expected_type in ("dict", "list", "object", "array"):
        success, parsed = try_parse_json(resolved_value)
        # ... parsing logic
```

**Add AFTER the existing block (around line 832):**
```python
            # REVERSE: Serialize dict/list → str when expected type is str
            # This enables MCP tools that declare `param: str` but expect JSON
            if is_simple_template and isinstance(resolved_value, (dict, list)):
                expected_type = self._expected_types.get(key)
                resolved_value = coerce_to_declared_type(resolved_value, expected_type)
```

**Import at top of file:**
```python
from pflow.core.param_coercion import coerce_to_declared_type
```

---

### Step 3: Integrate into `registry_run.py` (CLI `registry run` Path)

**Location:** `src/pflow/cli/registry_run.py`, function `_prepare_node_execution()` around line 160

**Current code:**
```python
# Inject special parameters (for MCP and workflow nodes)
enhanced_params = _inject_special_parameters(...)

# Set parameters on node
if enhanced_params:
    node.set_params(enhanced_params)
```

**Add coercion BEFORE `node.set_params()`:**
```python
# Inject special parameters (for MCP and workflow nodes)
enhanced_params = _inject_special_parameters(...)

# Coerce parameters to declared types (dict/list → str for str-typed params)
if enhanced_params:
    enhanced_params = _coerce_params_for_node(enhanced_params, resolved_node, registry)
    node.set_params(enhanced_params)
```

**Add helper function:**
```python
def _coerce_params_for_node(
    params: dict[str, Any],
    node_id: str,
    registry: Registry,
) -> dict[str, Any]:
    """Coerce parameter types based on node interface declaration.

    When a parameter is declared as 'str' but the value is dict/list,
    serialize it to a JSON string.

    Args:
        params: Parameters to coerce
        node_id: Node ID for registry lookup
        registry: Registry instance

    Returns:
        Parameters with coerced types
    """
    from pflow.core.param_coercion import coerce_to_declared_type

    # Get node interface metadata
    nodes = registry.load()
    node_info = nodes.get(node_id, {})
    interface = node_info.get("interface", {})
    param_schemas = interface.get("params", [])

    # Build type lookup
    param_types = {}
    for param in param_schemas:
        if isinstance(param, dict):
            key = param.get("key")
            param_type = param.get("type")
            if key and param_type:
                param_types[key] = param_type

    # Coerce each parameter
    coerced = {}
    for key, value in params.items():
        expected_type = param_types.get(key)
        coerced[key] = coerce_to_declared_type(value, expected_type)

    return coerced
```

---

### Step 4: Add Tests

#### 4.1 Unit tests for `param_coercion.py`

**New file:** `tests/test_core/test_param_coercion.py`

```python
"""Tests for parameter type coercion utilities."""

import pytest
from pflow.core.param_coercion import coerce_to_declared_type


class TestCoerceToDeclaredType:
    """Test coerce_to_declared_type function."""

    def test_dict_to_str(self):
        """Dict coerced to JSON string when expected type is str."""
        result = coerce_to_declared_type({"key": "value"}, "str")
        assert result == '{"key": "value"}'
        assert isinstance(result, str)

    def test_list_to_str(self):
        """List coerced to JSON string when expected type is str."""
        result = coerce_to_declared_type([1, 2, 3], "str")
        assert result == "[1, 2, 3]"
        assert isinstance(result, str)

    def test_nested_dict_to_str(self):
        """Nested dict serialized correctly."""
        result = coerce_to_declared_type(
            {"outer": {"inner": "value"}}, "str"
        )
        assert result == '{"outer": {"inner": "value"}}'

    def test_empty_dict_to_str(self):
        """Empty dict becomes '{}'."""
        result = coerce_to_declared_type({}, "str")
        assert result == "{}"

    def test_empty_list_to_str(self):
        """Empty list becomes '[]'."""
        result = coerce_to_declared_type([], "str")
        assert result == "[]"

    def test_str_unchanged_when_expected_str(self):
        """String passes through unchanged."""
        result = coerce_to_declared_type("hello", "str")
        assert result == "hello"

    def test_dict_unchanged_when_expected_dict(self):
        """Dict unchanged when expected type is dict."""
        original = {"key": "value"}
        result = coerce_to_declared_type(original, "dict")
        assert result == original
        assert isinstance(result, dict)

    def test_dict_unchanged_when_expected_object(self):
        """Dict unchanged when expected type is object."""
        original = {"key": "value"}
        result = coerce_to_declared_type(original, "object")
        assert result == original

    def test_list_unchanged_when_expected_list(self):
        """List unchanged when expected type is list."""
        original = [1, 2, 3]
        result = coerce_to_declared_type(original, "list")
        assert result == original

    def test_no_expected_type_unchanged(self):
        """Value unchanged when no expected type provided."""
        original = {"key": "value"}
        result = coerce_to_declared_type(original, None)
        assert result == original

    def test_string_type_alias(self):
        """'string' alias works same as 'str'."""
        result = coerce_to_declared_type({"a": 1}, "string")
        assert result == '{"a": 1}'

    def test_case_insensitive_type(self):
        """Type matching is case-insensitive."""
        result = coerce_to_declared_type({"a": 1}, "STR")
        assert result == '{"a": 1}'

    def test_none_value_unchanged(self):
        """None passes through unchanged."""
        result = coerce_to_declared_type(None, "str")
        assert result is None

    def test_int_unchanged_for_str_type(self):
        """Int not coerced (only dict/list)."""
        result = coerce_to_declared_type(42, "str")
        assert result == 42
```

#### 4.2 Integration tests for node_wrapper

**Add to:** `tests/test_runtime/test_node_wrapper_json_parsing.py`

```python
class TestReverseJsonCoercion:
    """Test dict/list → str coercion when expected type is str."""

    def test_dict_to_str_coercion(self, simple_node):
        """Dict coerced to JSON string when param type is str."""
        interface_metadata = {
            "params": [
                {"key": "json_param", "type": "str", "description": "JSON string param"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"json_param": "${data}"})
        shared = {"data": {"channel_id": "123"}}  # Dict value
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["json_param"], str)
        assert result["json_param"] == '{"channel_id": "123"}'

    def test_list_to_str_coercion(self, simple_node):
        """List coerced to JSON string when param type is str."""
        interface_metadata = {
            "params": [
                {"key": "items", "type": "str", "description": "JSON string"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        wrapper.set_params({"items": "${data}"})
        shared = {"data": [1, 2, 3]}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["items"], str)
        assert result["items"] == "[1, 2, 3]"

    def test_dict_preserved_when_type_is_dict(self, simple_node, interface_metadata):
        """Dict NOT coerced when param type is dict."""
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,  # Has dict_param: dict
        )

        wrapper.set_params({"dict_param": "${data}"})
        shared = {"data": {"key": "value"}}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["dict_param"], dict)
        assert result["dict_param"] == {"key": "value"}

    def test_workflow_json_object_becomes_string(self, simple_node):
        """Inline JSON object in workflow params becomes string for str-typed param."""
        interface_metadata = {
            "params": [
                {"key": "path_params", "type": "str"},
            ]
        }
        wrapper = TemplateAwareNodeWrapper(
            inner_node=simple_node,
            node_id="test",
            initial_params={},
            interface_metadata=interface_metadata,
        )

        # Simulate workflow JSON with inline object containing template
        wrapper.set_params({"path_params": {"channel_id": "${channel_id}"}})
        shared = {"channel_id": "123"}
        wrapper._run(shared)

        result = shared["result"]
        assert isinstance(result["path_params"], str)
        # Should be valid JSON string
        import json
        parsed = json.loads(result["path_params"])
        assert parsed == {"channel_id": "123"}
```

#### 4.3 Integration test for registry_run

**Add to:** `tests/test_cli/test_registry_run.py` (or create if doesn't exist)

```python
"""Tests for registry run command parameter coercion."""

import pytest
from unittest.mock import MagicMock, patch

from pflow.cli.registry_run import _coerce_params_for_node


class TestParamCoercionForNode:
    """Test parameter coercion in registry run."""

    def test_dict_coerced_to_str_for_str_typed_param(self):
        """Dict becomes JSON string when param declared as str."""
        mock_registry = MagicMock()
        mock_registry.load.return_value = {
            "test-node": {
                "interface": {
                    "params": [
                        {"key": "path_params", "type": "str"},
                    ]
                }
            }
        }

        params = {"path_params": {"channel_id": "123"}}
        result = _coerce_params_for_node(params, "test-node", mock_registry)

        assert result["path_params"] == '{"channel_id": "123"}'

    def test_dict_preserved_for_dict_typed_param(self):
        """Dict stays dict when param declared as dict."""
        mock_registry = MagicMock()
        mock_registry.load.return_value = {
            "test-node": {
                "interface": {
                    "params": [
                        {"key": "config", "type": "dict"},
                    ]
                }
            }
        }

        params = {"config": {"key": "value"}}
        result = _coerce_params_for_node(params, "test-node", mock_registry)

        assert result["config"] == {"key": "value"}
        assert isinstance(result["config"], dict)

    def test_unknown_params_pass_through(self):
        """Params not in schema pass through unchanged."""
        mock_registry = MagicMock()
        mock_registry.load.return_value = {
            "test-node": {
                "interface": {
                    "params": [
                        {"key": "known", "type": "str"},
                    ]
                }
            }
        }

        params = {"unknown": {"some": "value"}}
        result = _coerce_params_for_node(params, "test-node", mock_registry)

        # Unknown params NOT coerced (we don't know their type)
        assert result["unknown"] == {"some": "value"}
```

---

### Step 5: Update Exports

**File:** `src/pflow/core/__init__.py`

Add export for the new utility:
```python
from pflow.core.param_coercion import coerce_to_declared_type
```

---

## Verification Checklist

After implementation, verify:

- [ ] `make test` passes (all existing tests)
- [ ] `make check` passes (linting, type checking)
- [ ] Test workflow from scratchpad works:
  ```bash
  uv run pflow scratchpads/bug-json-string-params/test-workflow-fails.json \
    channel_id="1458059302022549698" \
    message="test from workflow"
  ```
- [ ] CLI registry run works without leading space hack:
  ```bash
  uv run pflow registry run mcp-discord-execute_action \
    server_name=discord \
    category_name=DISCORD_CHANNELS_MESSAGES \
    action_name=create_message \
    path_params='{"channel_id":"1458059302022549698"}' \
    body_schema='{"content":"test message"}'
  ```
- [ ] Existing dict-typed params still work (no regression)
- [ ] New tests all pass

---

## Risk Assessment

**Low risk:**
- Coercion only happens when expected_type is explicitly "str" and value is dict/list
- Unknown params pass through unchanged
- Existing str→dict coercion unaffected

**Edge cases handled:**
- None values pass through
- Empty dict/list serialize correctly
- Nested structures serialize correctly
- No expected type = no coercion

---

## Files Changed Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `src/pflow/core/param_coercion.py` | NEW | Shared coercion utility |
| `src/pflow/core/__init__.py` | MODIFY | Add export |
| `src/pflow/runtime/node_wrapper.py` | MODIFY | Add reverse coercion |
| `src/pflow/cli/registry_run.py` | MODIFY | Add coercion helper |
| `tests/test_core/test_param_coercion.py` | NEW | Unit tests |
| `tests/test_runtime/test_node_wrapper_json_parsing.py` | MODIFY | Integration tests |
| `tests/test_cli/test_registry_run.py` | NEW/MODIFY | CLI tests |

---

## Implementation Order

1. Create `param_coercion.py` with tests (isolated, testable)
2. Integrate into `node_wrapper.py` with tests (workflow path)
3. Integrate into `registry_run.py` with tests (CLI path)
4. Manual verification with real Discord MCP
5. Clean up scratchpad test files (optional)
