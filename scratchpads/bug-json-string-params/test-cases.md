# Test Cases for JSON String Parameter Fix

## Unit Tests to Add

### 1. CLI Parameter Coercion Tests

Location: `tests/test_cli/test_registry_run.py` (may need to create)

```python
def test_json_dict_coerced_to_string_when_param_type_is_str():
    """When param type is 'str' and value is dict, serialize to JSON string."""
    params = {"path_params": {"channel_id": "123"}}
    param_schema = [{"key": "path_params", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    assert coerced["path_params"] == '{"channel_id": "123"}'
    assert isinstance(coerced["path_params"], str)


def test_json_list_coerced_to_string_when_param_type_is_str():
    """When param type is 'str' and value is list, serialize to JSON string."""
    params = {"items": ["a", "b", "c"]}
    param_schema = [{"key": "items", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    assert coerced["items"] == '["a", "b", "c"]'


def test_dict_preserved_when_param_type_is_dict():
    """When param type is dict/object, don't serialize - keep as dict."""
    params = {"config": {"key": "value"}}
    param_schema = [{"key": "config", "type": "dict"}]

    coerced = coerce_params_to_schema(params, param_schema)

    assert coerced["config"] == {"key": "value"}
    assert isinstance(coerced["config"], dict)


def test_dict_preserved_when_param_type_is_object():
    """When param type is 'object', don't serialize."""
    params = {"data": {"nested": True}}
    param_schema = [{"key": "data", "type": "object"}]

    coerced = coerce_params_to_schema(params, param_schema)

    assert isinstance(coerced["data"], dict)


def test_string_unchanged_when_param_type_is_str():
    """Normal strings should pass through unchanged."""
    params = {"name": "hello world"}
    param_schema = [{"key": "name", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    assert coerced["name"] == "hello world"


def test_unknown_param_passes_through():
    """Parameters not in schema should pass through unchanged."""
    params = {"unknown": {"some": "value"}}
    param_schema = [{"key": "known", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    # Unknown params should NOT be coerced (we don't know their type)
    assert coerced["unknown"] == {"some": "value"}


def test_template_in_dict_preserved_before_resolution():
    """Dicts with templates should be serialized before template resolution."""
    params = {"path_params": {"channel_id": "${channel_id}"}}
    param_schema = [{"key": "path_params", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    # The template should be inside the JSON string
    assert '${channel_id}' in coerced["path_params"]
    assert isinstance(coerced["path_params"], str)
```

### 2. Integration Tests

Location: `tests/test_integration/test_mcp_json_params.py` (new file)

```python
@pytest.fixture
def mock_discord_registry():
    """Mock registry with Discord MCP node schema."""
    return {
        "mcp-discord-execute_action": {
            "interface": {
                "params": [
                    {"key": "server_name", "type": "str"},
                    {"key": "category_name", "type": "str"},
                    {"key": "action_name", "type": "str"},
                    {"key": "path_params", "type": "str"},
                    {"key": "body_schema", "type": "str"},
                ]
            }
        }
    }


def test_workflow_with_json_object_params(mock_discord_registry):
    """Workflow with JSON objects in str-typed params should work."""
    workflow = {
        "inputs": {"channel_id": {"type": "string"}},
        "nodes": [{
            "id": "test",
            "type": "mcp-discord-execute_action",
            "params": {
                "server_name": "discord",
                "path_params": {"channel_id": "${channel_id}"}  # Object, not string
            }
        }],
        "edges": []
    }

    # Should not raise, should auto-coerce
    # ... test implementation


def test_cli_registry_run_with_json_params(mock_discord_registry):
    """CLI registry run with JSON params should auto-coerce."""
    # Test that:
    # pflow registry run mcp-discord-execute_action path_params='{"key":"value"}'
    # Works without the leading space hack
    pass
```

### 3. Edge Cases to Test

```python
def test_empty_dict_coerced():
    """Empty dict should become '{}'."""
    params = {"data": {}}
    param_schema = [{"key": "data", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    assert coerced["data"] == "{}"


def test_empty_list_coerced():
    """Empty list should become '[]'."""
    params = {"items": []}
    param_schema = [{"key": "items", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    assert coerced["items"] == "[]"


def test_nested_dict_coerced():
    """Deeply nested dict should serialize correctly."""
    params = {"data": {"level1": {"level2": {"value": 123}}}}
    param_schema = [{"key": "data", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    assert '"level2"' in coerced["data"]
    assert '"value": 123' in coerced["data"]


def test_list_of_dicts_coerced():
    """List of dicts should serialize to JSON array."""
    params = {"items": [{"id": 1}, {"id": 2}]}
    param_schema = [{"key": "items", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    assert coerced["items"] == '[{"id": 1}, {"id": 2}]'


def test_null_value_not_coerced():
    """None/null should pass through (not become 'null' string)."""
    params = {"data": None}
    param_schema = [{"key": "data", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    # This is debatable - should None become "null" or stay None?
    # Recommend: keep as None, let downstream handle it
    assert coerced["data"] is None


def test_already_string_json_not_double_encoded():
    """If user passes a JSON string, don't double-encode it."""
    params = {"data": '{"already": "json"}'}
    param_schema = [{"key": "data", "type": "str"}]

    coerced = coerce_params_to_schema(params, param_schema)

    # Should stay as-is, not become '"{\"already\": \"json\"}"'
    assert coerced["data"] == '{"already": "json"}'
```

## Manual Testing Commands

### Test CLI Registry Run (After Fix)

```bash
# Should work without leading space hack
uv run pflow registry run mcp-discord-execute_action \
  server_name=discord \
  category_name=DISCORD_CHANNELS_MESSAGES \
  action_name=create_message \
  path_params='{"channel_id":"1458059302022549698"}' \
  body_schema='{"content":"test message from CLI"}'
```

### Test Workflow Execution (After Fix)

```bash
# Should work with test-workflow-fails.json
uv run pflow scratchpads/bug-json-string-params/test-workflow-fails.json \
  channel_id="1458059302022549698" \
  message="test message from workflow"
```

### Verify No Regression

```bash
# Normal string params should still work
uv run pflow registry run mcp-composio-slack-SLACK_SEND_MESSAGE \
  channel="test" \
  markdown_text="hello world"

# Dict params for nodes that expect dicts should still work
uv run pflow registry run http \
  url="https://httpbin.org/post" \
  method="POST" \
  body='{"key": "value"}'  # http node might expect this as dict
```

## Acceptance Criteria

1. [ ] `test-workflow-fails.json` works without modification
2. [ ] CLI `registry run` works without leading space hack
3. [ ] Existing workflows don't break
4. [ ] Nodes that expect actual dicts still receive dicts
5. [ ] All new unit tests pass
6. [ ] No performance regression (coercion is fast)
