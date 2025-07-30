# Test Implementation Quick Reference

## Do's and Don'ts At a Glance

| Scenario | ❌ Don't | ✅ Do |
|----------|----------|------|
| Testing file operations | Mock `open()` | Use `tempfile` |
| Testing PocketFlow nodes | Mock Node class | Create simple test nodes |
| Testing time-dependent code | Use `datetime.now()` | Use `freeze_time()` |
| Testing random behavior | Let it be random | Seed or mock `random` |
| Testing CLI commands | Mock Click internals | Use `CliRunner` |
| Testing external APIs | Make real HTTP calls | Mock `requests` |
| Testing database operations | Use production DB | Use in-memory DB or mock |
| Testing error messages | Match exact strings | Check key phrases |
| Testing workflows | Mock all nodes | Use simple test nodes |
| Testing async code | Use `time.sleep()` | Use `asyncio` testing utils |

## Quick Mocking Decision

```python
def should_i_mock(component):
    if component in ["filesystem", "network", "database", "time", "random"]:
        return True  # External boundary

    if component in ["LLM", "AI model", "external API"]:
        return True  # Expensive/non-deterministic

    if component.startswith("pflow.") or component.startswith("pocketflow."):
        return False  # Never mock framework components

    if "my_code" in component:
        return False  # Never mock your own code

    return False  # When in doubt, don't mock
```

## Test Naming Formula

```
def test_<component>_<action>_<expected_outcome>():
    """When <condition>, <component> should <behavior>"""
```

Examples:
- `test_workflow_run_completes_all_nodes()`
- `test_registry_get_node_raises_error_when_not_found()`
- `test_shared_store_preserves_data_between_nodes()`

## Common Test Patterns

### Pattern 1: Testing Error Handling
```python
def test_component_handles_invalid_input():
    with pytest.raises(SpecificError) as exc_info:
        component.process(invalid_input)

    assert "meaningful phrase" in str(exc_info.value)
```

### Pattern 2: Testing File Output
```python
def test_component_writes_output_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "output.txt"

        component.process(output=output_path)

        assert output_path.exists()
        assert output_path.read_text() == "expected content"
```

### Pattern 3: Testing Node Behavior
```python
def test_node_transforms_data():
    shared = {"input": "test data"}
    node = MyNode()

    node.exec(shared)

    assert shared["output"] == "transformed test data"
```

### Pattern 4: Testing Workflows
```python
def test_workflow_completes_successfully():
    # Create test nodes
    nodes = [TestInputNode(), TestProcessNode(), TestOutputNode()]

    # Build workflow
    flow = Flow()
    for node in nodes:
        flow = flow >> node

    # Run and verify
    result = flow.run(input="test")
    assert result["status"] == "success"
```

## Red Flags in Tests

If you see these, the test needs fixing:

1. **More than 3 levels of mocking**
   ```python
   with patch(...):
       with patch(...):
           with patch(...):  # Too much!
   ```

2. **Testing mock behavior**
   ```python
   mock_obj.method.assert_called_with(...)  # Testing the mock!
   ```

3. **Hardcoded paths**
   ```python
   assert read_file("/Users/john/test.txt")  # Won't work elsewhere!
   ```

4. **Time-based assertions**
   ```python
   time.sleep(1)
   assert thing_happened()  # Flaky!
   ```

5. **Testing private methods**
   ```python
   assert obj._private_method() == "result"  # Implementation detail!
   ```

## Test Type Guidelines

| Test Type | Speed | Mocking | When to Use |
|-----------|-------|---------|-------------|
| Unit | <100ms | Minimal | Single function/class behavior |
| Integration | <1s | External only | Component interactions |
| E2E | <5s | Almost none | Complete workflows |

## Emergency Checklist

When a test is failing and you don't know why:

1. **Is it testing behavior or implementation?**
2. **Would this test break if I renamed a variable?**
3. **Can I understand what broke from the error message?**
4. **Is the test dependent on other tests?**
5. **Am I mocking something I shouldn't?**

If you answer "yes" to #2 or #4, or "no" to #1 or #3, the test needs fixing.

## Remember

> "The best test is the one that catches real bugs while surviving refactoring."

Your tests are guardians, not bureaucrats. They should protect against breaking changes, not enforce implementation details.
