# Testing Instructions for pflow Implementation

**MANDATORY READING**: These are not suggestions. They are requirements for every line of code you write.

## ⚠️ Your Testing Obligations

**YOU MUST FOLLOW THESE RULES - NO EXCEPTIONS:**

1. **NO CODE WITHOUT TESTS** - Every feature, every bug fix, every refactor MUST have tests
2. **TEST AS YOU GO** - Write tests alongside implementation, not after
3. **TDD IS DEFAULT** - Write tests first when possible
4. **BROKEN TESTS = BROKEN CODE** - A failing test is as critical as broken implementation
5. **NO PR WITHOUT TESTS** - Untested code will not be merged

**Why This Matters for AI Agents:**
- Tests are your safety net - they catch mistakes immediately
- Tests enable confident refactoring - change code without fear
- Tests document behavior - they show what the code should do
- Tests prevent cascading failures - one bug doesn't break everything

**Consequences of Skipping Tests:**
- ❌ Your code WILL break in production
- ❌ Other agents WILL break your code
- ❌ Debugging WILL take 10x longer
- ❌ Your PR WILL be rejected

## 📋 When to Write Tests (Not Optional!)

### Write Tests FIRST (TDD) When:
- Implementing new features with clear requirements
- Fixing bugs (write test that reproduces bug first)
- Refactoring existing code (tests ensure behavior preserved)
- Requirements are well-defined

### Write Tests DURING Implementation When:
- Exploring implementation approaches
- Requirements are evolving
- Integrating with external systems
- Building experimental features

### NEVER Write Tests:
- After all implementation is done ❌
- "When you have time" ❌
- Only for "important" code ❌
- As an afterthought ❌
- That tests

**REMEMBER**: If you're writing code, you're writing tests. Period.

## 🔴🟢🔵 Test-Driven Development (TDD) - Your Default Approach

**USE TDD BY DEFAULT** - This is not a suggestion, it's the standard way to write code.

### The TDD Cycle (MANDATORY for new features)

```
1. 🔴 RED: Write a failing test FIRST
   - Define what success looks like
   - Run test - it MUST fail (no implementation yet)

2. 🟢 GREEN: Write minimal code to pass
   - Implement ONLY enough to make test pass
   - No extra features, no optimization

3. 🔵 REFACTOR: Improve code with confidence
   - Clean up implementation
   - Tests ensure behavior unchanged
```

### TDD Example - FOLLOW THIS PATTERN

```python
# STEP 1: Write test first (RED)
def test_validator_rejects_empty_email():
    """Email validator should reject empty strings."""
    with pytest.raises(ValueError) as exc:
        validate_email("")
    assert "empty" in str(exc.value).lower()

# Run test - FAILS (validate_email doesn't exist)

# STEP 2: Minimal implementation (GREEN)
def validate_email(email: str) -> bool:
    if not email:
        raise ValueError("Email cannot be empty")
    return True

# Run test - PASSES

# STEP 3: Refactor and add more tests (BLUE)
def test_validator_rejects_invalid_format():
    """Email validator should reject invalid formats."""
    with pytest.raises(ValueError):
        validate_email("not-an-email")

def validate_email(email: str) -> bool:
    """Validate email format."""
    if not email:
        raise ValueError("Email cannot be empty")
    if "@" not in email:
        raise ValueError("Invalid email format")
    return True
```

**When TDD is MANDATORY:**
- Bug fixes (reproduce bug with test first)
- New features with clear requirements
- Refactoring existing code
- API endpoints or interfaces

**When TDD is OPTIONAL (but test-as-you-go is NOT):**
- Exploratory prototypes
- UI experimentation
- Integration with poorly documented APIs
- Unclear requirements (Why are you even reading this document? You should be gathering context or asking questions to the user or the agent that asked you to implement this. This is a STOP SIGNAL 🔴)

## 🚀 Quick Start Templates (REQUIRED for every implementation)

### Testing a New Node (THIS TEST IS REQUIRED)

```python
def test_my_node_transforms_data():
    """Test that MyNode correctly processes input."""
    # Arrange
    shared = {"input_data": "test value"}
    node = MyNode()

    # Act
    node.exec(shared, param="value")

    # Assert
    assert shared["output_data"] == "expected result"
    assert "error" not in shared  # No errors occurred
```

**NO NODE WITHOUT TESTS** - If you implement a node without tests, your code is incomplete.

### Testing a CLI Command

```python
def test_cli_command_success():
    """Test successful command execution."""
    runner = CliRunner()

    # Create test data
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
        json.dump({"test": "data"}, f)
        f.flush()

        # Run command
        result = runner.invoke(cli, ['process', f.name])

    # Verify
    assert result.exit_code == 0
    assert "Success" in result.output
```

### Testing Error Handling

```python
def test_node_handles_missing_input():
    """Test node fails gracefully with missing data."""
    shared = {}  # Missing required input
    node = MyNode()

    # Should raise clear error
    with pytest.raises(ValueError) as exc_info:
        node.exec(shared)

    assert "Missing required 'input_data'" in str(exc_info.value)
```

### Testing Workflow Integration

```python
def test_nodes_work_together_in_workflow():
    """Test nodes communicate via shared store."""
    # Build workflow IR and compile
    ir = {"nodes": [...], "edges": [...]}
    workflow = compile_workflow(ir, registry)
    shared = {"initial_data": "test"}
    shared.update(workflow.resolved_defaults)
    engine = WorkflowEngine()
    engine.run(workflow, shared)

    # Verify end result
    assert shared["consumer"]["final_output"] == "processed: test"
```

## 📝 Test Patterns by Implementation Type

### When You're Writing a Node

#### Basic Functionality Test
```python
def test_node_basic_execution():
    shared = {"required_input": "data"}
    node = YourNode()
    node.exec(shared, optional_param="value")

    assert shared["expected_output"] == "result"
```

#### Testing Parameter vs Shared Store Fallback
```python
def test_node_uses_parameter_over_shared():
    shared = {"config": "shared_value"}
    node = YourNode()

    # Parameter should take precedence
    node.exec(shared, config="param_value")
    assert shared["result"] == "used: param_value"
```

#### Testing Error Conditions
```python
def test_node_validates_input():
    shared = {"invalid_data": None}
    node = YourNode()

    # Let exception bubble up (Node retry mechanism will handle it)
    with pytest.raises(ValueError):
        node.exec(shared)
```

#### ⚠️ NEVER Test Retry Behavior
```python
# ❌ DON'T DO THIS - Node retry mechanism handles retries
def test_node_retries_on_failure():
    # Don't test the framework!

# ✅ DO THIS - Test your error handling
def test_node_exec_fallback():
    node = YourNode()
    error = RuntimeError("Network timeout")
    shared = {}

    node.exec_fallback(shared, error)
    assert shared["error"] == "Failed after retries: Network timeout"
```

### When You're Writing a CLI Command

#### Success Case
```python
def test_command_processes_file():
    runner = CliRunner()

    with runner.isolated_filesystem():
        # Setup test file
        Path("input.txt").write_text("data")

        # Run command
        result = runner.invoke(cli, ['process', 'input.txt'])

        # Check success
        assert result.exit_code == 0
        assert Path("output.txt").exists()
```

#### Error Handling
```python
def test_command_handles_missing_file():
    runner = CliRunner()

    result = runner.invoke(cli, ['process', 'nonexistent.txt'])

    assert result.exit_code != 0
    assert "File not found" in result.output
```

#### Testing Options
```python
def test_command_with_options():
    runner = CliRunner()

    result = runner.invoke(cli, [
        'export',
        'workflow-name',
        '--format', 'yaml',
        '--output', 'result.yaml'
    ])

    assert result.exit_code == 0
    assert Path("result.yaml").exists()
```

### When You're Writing Registry/Runtime Code

#### Testing Registration
```python
def test_registry_registers_node():
    registry = Registry()
    registry.register_node(MyNode)

    # Verify registration
    node_class = registry.get_node("my_node")
    assert node_class is MyNode
```

#### Testing Discovery
```python
def test_registry_discovers_nodes_in_module():
    registry = Registry()
    registry.scan_module(my_nodes_module)

    # Should find all nodes
    assert "node1" in registry.list_nodes()
    assert "node2" in registry.list_nodes()
```

#### Testing Compilation
```python
def test_compiler_creates_executable_workflow():
    workflow_ir = {
        "nodes": [{"id": "n1", "type": "test_node"}],
        "edges": []
    }

    compiled = compile_workflow(workflow_ir, registry)
    result = compiled.run()

    assert result["status"] == "success"
```

### When You're Writing Utilities

#### Pure Functions
```python
def test_utility_transforms_data():
    input_data = {"key": "value"}
    result = transform_data(input_data)

    assert result == {"key": "VALUE"}
```

#### File Operations
```python
def test_reads_json_file():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
        json.dump({"test": "data"}, f)
        f.flush()

        result = read_json_file(f.name)

    assert result == {"test": "data"}
```

## 🔄 Test-As-You-Go Workflow (MANDATORY PROCESS)

**THIS IS NOT OPTIONAL** - You MUST follow this workflow for every implementation.

### The Process (FOLLOW EXACTLY)

1. **Write Function Signature** → **Write Test Skeleton**
   ```python
   def process_data(input: str) -> dict:
       pass

   def test_process_data_returns_dict():
       # TODO: Implement test
       pass
   ```

2. **Implement Basic Functionality** → **Write Happy Path Test**
   ```python
   def test_process_data_handles_valid_input():
       result = process_data("valid")
       assert result == {"status": "ok"}
   ```

3. **Add Error Handling** → **Write Error Tests**
   ```python
   def test_process_data_rejects_empty_input():
       with pytest.raises(ValueError):
           process_data("")
   ```

4. **Handle Edge Cases** → **Write Edge Case Tests**
   ```python
   def test_process_data_handles_unicode():
       result = process_data("🚀")
       assert result["status"] == "ok"
   ```

### Red-Green-Refactor

```
1. 🔴 RED: Write test first (it fails)
   - Write test_user_auth_validates_token()
   - Run it - FAILS (function doesn't exist)

2. 🟢 GREEN: Write minimal code to pass
   - Implement validate_token() with basic logic
   - Run test - PASSES

3. 🔵 REFACTOR: Improve code (tests still pass)
   - Extract validation logic
   - Add better error messages
   - Run tests - STILL PASSES
```

## 🐛 Debugging Test Failures - Quick Checklist

### Step 1: Run Only the Failing Test
```bash
# Run specific test with verbose output
pytest path/to/test.py::test_name -v

# With print statements visible
pytest path/to/test.py::test_name -v -s

# Drop into debugger on failure
pytest path/to/test.py::test_name --pdb
```

### Step 2: Quick Diagnosis

**Is the test wrong or the code wrong?**
- [ ] Read test name - does it describe what's being tested?
- [ ] Check test expectations - do they match requirements?
- [ ] Verify code behavior - what does it actually do?
- [ ] Recent changes - what changed and why?

### Step 3: Common Failure Causes

| Symptom | Likely Cause | Quick Fix |
|---------|--------------|-----------|
| `KeyError: 'output'` | Shared store key mismatch | Check exact key names |
| `AssertionError: None != 'expected'` | Missing test setup | Ensure input data is set |
| `TypeError: 'NoneType'` | Uninitialized data | Add proper defaults |
| Test passes alone, fails in suite | Test isolation issue | Check shared state |
| Works locally, fails in CI | Environment difference | Check paths, env vars |

### Step 4: Debug Strategies

```python
# Add debug output
def test_failing_test():
    shared = {"input": "test"}
    print(f"Before: {shared}")  # Debug

    node.exec(shared)
    print(f"After: {shared}")   # Debug

    assert shared["output"] == "expected"

# Simplify to isolate issue
def test_minimal_reproduction():
    # Remove everything except what's needed
    # to reproduce the failure
```

## ⚠️ No Cheating - Write HONEST Tests

**YOUR TESTS MUST ACTUALLY TEST SOMETHING**

### Signs You're Cheating (NEVER DO THESE)

```python
# ❌ CHEATING: Tests that can't fail
def test_feature():
    try:
        result = my_function()
        assert True  # This tests nothing!
    except:
        assert True  # Really?

# ❌ CHEATING: Adjusting tests to match bugs
def test_calculator():
    result = calc.add(2, 2)
    assert result == 5  # Your calc is broken, not the test!

# ❌ CHEATING: Mocking to avoid complexity
def test_node():
    with patch('everything'):
        assert True  # You're testing mocks, not code

# ❌ CHEATING: Weakening assertions
def test_validation():
    # Was: assert error == "Invalid email: test@"
    # Became: assert "invalid" in error.lower()  # Too weak!
```

### Write Tests That Can FAIL

```python
# ✅ HONEST: Test specific behavior
def test_email_validator_rejects_missing_domain():
    with pytest.raises(ValueError) as exc:
        validate_email("user@")
    assert "missing domain" in str(exc.value)

# ✅ HONEST: Test actual functionality
def test_node_transforms_data():
    shared = {"input": "test"}
    node = TransformNode()
    node.exec(shared)
    assert shared["output"] == "TEST"  # Specific expectation

# ✅ HONEST: Test edge cases that might fail
def test_handles_empty_input():
    with pytest.raises(ValueError):
        process_data("")  # This might actually fail!
```

**Remember**: The point of tests is to CATCH BUGS, not hide them. A test that always passes is worse than no test.

## 🔒 pflow-Specific Testing Rules (VIOLATE THESE AND YOUR CODE BREAKS)

### The Sacred Rules - NEVER VIOLATE THESE

1. **Never Mock Node Primitives**
   ```python
   # ❌ NEVER DO THIS
   with patch('pflow.core.node.Node'):
       # This breaks everything!

   # ✅ Create simple test nodes
   class TestNode(Node):
       def exec(self, shared, **kwargs):
           shared["test"] = "data"
   ```

2. **Never Catch Exceptions in node.exec()**
   ```python
   # ❌ BREAKS RETRY MECHANISM
   def exec(self, shared, **kwargs):
       try:
           risky_operation()
       except Exception:
           pass  # Node retry mechanism can't retry!

   # ✅ LET EXCEPTIONS BUBBLE UP
   def exec(self, shared, **kwargs):
       risky_operation()  # Node retry mechanism handles retries
   ```

3. **Use Descriptive Shared Store Keys**
   ```python
   # ❌ Bad
   shared["data"] = processed
   shared["result"] = output

   # ✅ Good
   shared["user_input"] = processed
   shared["validation_result"] = output
   ```

4. **Test Behavior, Not Structure**
   ```python
   # ❌ Testing IR structure
   assert workflow_ir["nodes"][0]["type"] == "reader"

   # ✅ Testing behavior
   result = run_workflow(workflow_ir)
   assert Path(result["output_file"]).exists()
   ```

## 🎯 Common Test Scenarios

### File Operations
```python
# Always use tempfile
with tempfile.TemporaryDirectory() as tmpdir:
    file_path = Path(tmpdir) / "test.txt"
    file_path.write_text("content")

    result = process_file(str(file_path))
    assert result == "CONTENT"
```

### External APIs
```python
# Mock only the HTTP layer
with patch('requests.get') as mock_get:
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"status": "ok"}

    result = check_api_health()
    assert result == "healthy"
```

### Time-Dependent Code
```python
from freezegun import freeze_time

# Control time explicitly
with freeze_time("2024-01-01 12:00:00"):
    result = create_timestamp()
    assert result == "2024-01-01T12:00:00"
```

### Random Behavior
```python
# Seed for determinism
random.seed(42)
result = generate_id()
assert result == "expected_with_seed_42"

# Or mock
with patch('random.randint', return_value=5):
    result = roll_dice()
    assert result == 5
```

## 📛 Test Naming Cheat Sheet

```
def test_<component>_<action>_<expected_outcome>():
    """When <condition>, <component> should <behavior>"""
```

### Examples:
- `test_file_reader_loads_content_into_shared_store()`
- `test_validator_raises_error_for_invalid_email()`
- `test_workflow_executes_nodes_in_order()`
- `test_cli_export_creates_yaml_file()`
- `test_registry_finds_all_nodes_in_module()`

## 🎯 Mocking Decision Tree

```
Should I mock this?
│
├─ Is it an external system?
│  ├─ File system → Yes (use tempfile)
│  ├─ Network → Yes (mock requests)
│  ├─ Database → Yes (mock connection)
│  └─ Time → Yes (use freezegun)
│
├─ Is it a Node/engine component?
│  ├─ Node → NO! Never mock
│  ├─ WorkflowEngine → NO! Never mock
│  └─ Shared store → NO! Never mock
│
├─ Is it your own code?
│  └─ NO! Use the real implementation
│
├─ Is it expensive/slow?
│  ├─ LLM/AI call → Yes (mock response)
│  └─ Heavy computation → Maybe (consider test double)
│
└─ Is it non-deterministic?
   ├─ Random → Yes (seed or mock)
   └─ UUID → Yes (mock if testing specific value)
```

## 🚩 Red Flags - When to Revise Your Test

If ANY of these are true, revise your test:

- [ ] More than 5 lines of mock setup
- [ ] Test breaks when you rename a private variable
- [ ] Test passes but the feature doesn't work
- [ ] Test requires other tests to run first
- [ ] Test takes more than 1 second
- [ ] Can't understand test purpose from its name
- [ ] More than 3 assertions testing different things
- [ ] Using `time.sleep()` anywhere
- [ ] Mocking Node primitives (BaseNode, Node)
- [ ] Catching exceptions in node tests

## ✅ MANDATORY Quality Checklist

**YOU MUST VERIFY ALL ITEMS** - No exceptions. Every checkbox MUST be checked:

Before considering code as done, verify:

- [ ] **Test name** clearly describes behavior?
- [ ] **Single concept** tested (one assertion group)?
- [ ] **Independent** - runs alone successfully?
- [ ] **Real components** used where possible?
- [ ] **Clear failure** - obvious what broke?
- [ ] **No sleep** - no time.sleep() calls?
- [ ] **Shared store** keys are descriptive?
- [ ] **Exceptions flow** - not caught in exec()?
- [ ] **Examples work** - docstring examples are valid?
- [ ] **Tests verify the correct behavior** - do they verify the correct behavior specified in the requirements?

## 💡 Pro Tips

1. **Write the test name first** - It clarifies what you're building
2. **One logical assertion** - Multiple asserts OK if testing one concept
3. **Test the interface** - Not the implementation details
4. **Real > Mocked** - Use real components whenever possible
5. **Descriptive failures** - Future you will thank present you

---

## ⛔ FINAL WARNING

- Untested code is BROKEN code
- Untested code will NOT be accepted
- Untested code WILL cause failures
- Testing the wrong thing is worse than no tests at all

**Your Implementation Checklist:**
1. ✅ Read requirements
2. ✅ Write test (TDD)
3. ✅ Implement feature
4. ✅ Verify tests pass
5. ✅ Run quality checklist

Remember: Tests are not optional. They are PART of your implementation. A feature without tests is an incomplete feature.

**YOU HAVE BEEN WARNED. FOLLOW THESE INSTRUCTIONS.**
