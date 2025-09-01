# Test Strategy for Named Workflow Execution

## Philosophy: Test User Behavior, Not Implementation

We test what users **see** and **experience**, not internal state or code paths. Every test should answer: "Does this work the way a user expects?"

## Critical Behaviors to Test

### 1. Workflow Resolution Behavior

**What Users Care About**: Can I run my workflow using natural, intuitive commands?

#### Test: Multiple ways to reference workflows work
```python
def test_workflow_resolution_methods():
    """User can run workflows using various natural patterns."""
    # Setup: Save a workflow named "analyze-code"

    # All these should work:
    assert run("pflow analyze-code").success
    assert run("pflow analyze-code.json").success  # With extension
    assert run("pflow ./analyze-code.json").success  # Local file
    assert run("pflow --file analyze-code.json").success  # Explicit file

    # Verify they all produce the same output
```

#### Test: Clear error when workflow doesn't exist
```python
def test_workflow_not_found_message():
    """User gets helpful guidance when workflow isn't found."""
    result = run("pflow unknown-workflow")

    # User should see:
    assert "Workflow 'unknown-workflow' not found" in result.output
    assert "pflow workflow list" in result.output  # Guidance
    assert result.exit_code == 1
```

#### Test: Suggestions for similar names
```python
def test_similar_workflow_suggestions():
    """User gets suggestions for typos."""
    # Setup: Save workflows "analyze-code", "analyze-text"

    result = run("pflow analyze-data")
    assert "Did you mean" in result.output
    assert "analyze-code" in result.output
    assert "analyze-text" in result.output
```

### 2. Parameter Handling Behavior

**What Users Care About**: Can I pass data to my workflows easily?

#### Test: Parameters work correctly
```python
def test_workflow_with_parameters():
    """User can pass parameters and they're used correctly."""
    # Workflow expects: input_file (required), format (optional, default="json")

    # Test required param
    result = run("pflow process-data input_file=data.csv")
    assert result.success
    assert "data.csv" in read_output_file()  # Verify param was used

    # Test optional uses default
    assert "json" in read_output_file()  # Default was applied
```

#### Test: Missing required parameters show helpful error
```python
def test_missing_required_parameters():
    """User sees what parameters are needed."""
    result = run("pflow process-data")

    # User should see:
    assert "❌ Workflow 'process-data' requires parameters:" in result.output
    assert "input_file:" in result.output  # Show param name
    assert "Path to input data file" in result.output  # Show description
    assert "Usage: pflow process-data input_file=<value>" in result.output
    assert result.exit_code == 1
```

#### Test: Type conversion works
```python
def test_parameter_type_conversion():
    """Parameters are converted to correct types."""
    # Workflow expects: count (int), threshold (float), verbose (bool)

    result = run("pflow analyze count=5 threshold=0.95 verbose=true")
    assert result.success

    # Verify types were converted (check output or side effects)
    output = read_json_output()
    assert output["processed_count"] == 5  # Not "5"
    assert output["threshold_used"] == 0.95  # Not "0.95"
```

### 3. Discovery Commands Behavior

**What Users Care About**: How do I know what workflows are available?

#### Test: List shows all workflows with descriptions
```python
def test_workflow_list_command():
    """User can see all available workflows."""
    # Setup: Save several workflows

    result = run("pflow workflow list")
    assert "analyze-code" in result.output
    assert "Analyze Python code for quality" in result.output  # Description
    assert "Total: 3 workflows" in result.output
```

#### Test: Describe shows workflow interface
```python
def test_workflow_describe_command():
    """User can see what a workflow needs and does."""
    result = run("pflow workflow describe analyze-code")

    # User should see:
    assert "Workflow: analyze-code" in result.output
    assert "Description:" in result.output
    assert "Inputs:" in result.output
    assert "code_path: string" in result.output  # Param details
    assert "Outputs:" in result.output
    assert "Example Usage:" in result.output
    assert "pflow analyze-code code_path=" in result.output
```

#### Test: Empty list shows helpful guidance
```python
def test_empty_workflow_list():
    """User gets help when no workflows exist."""
    # Clear all workflows

    result = run("pflow workflow list")
    assert "No workflows saved yet" in result.output
    assert "To save a workflow:" in result.output
    assert 'pflow "your task here"' in result.output
```

### 4. Integration Behavior

**What Users Care About**: Does everything work together smoothly?

#### Test: File and saved workflows work the same
```python
def test_file_vs_saved_workflow_parity():
    """Both methods produce identical results."""
    # Create identical workflow as file and saved

    file_result = run("pflow --file workflow.json input=test")
    saved_result = run("pflow my-workflow input=test")

    assert file_result.output == saved_result.output
    assert file_result.exit_code == saved_result.exit_code
```

#### Test: Stdin works with named workflows
```python
def test_stdin_with_named_workflow():
    """User can pipe data to named workflows."""
    result = run("echo 'test data' | pflow process-text")
    assert result.success
    assert "test data" in read_workflow_output()
```

### 5. Error Recovery Behavior

**What Users Care About**: When things go wrong, can I understand and fix it?

#### Test: Invalid JSON shows where the error is
```python
def test_invalid_json_file_error():
    """User sees exactly where JSON is broken."""
    # Create malformed JSON file

    result = run("pflow --file broken.json")
    assert "Invalid JSON syntax" in result.output
    assert "Error at line" in result.output
    assert "column" in result.output
```

#### Test: Graceful fallback to planner
```python
def test_fallback_to_planner():
    """Ambiguous input falls back to natural language."""
    # "analyze" could be workflow or natural language

    result = run("pflow analyze this text", expect_planner=True)
    # Should attempt planner, not error
    assert "workflow-discovery" in result.output  # Planner ran
```

## Test Implementation Patterns

### Use Click's CliRunner
```python
from click.testing import CliRunner

def run(command: str) -> Result:
    """Helper to run CLI commands in tests."""
    runner = CliRunner()
    args = command.replace("pflow ", "").split()
    return runner.invoke(main, args)
```

### Use Isolated Filesystem
```python
def test_with_files():
    runner = CliRunner()
    with runner.isolated_filesystem():
        # Create test files
        Path("workflow.json").write_text(workflow_content)

        # Run test
        result = runner.invoke(main, ["--file", "workflow.json"])

        # Verify outputs
        assert Path("output.txt").exists()
```

### Test Output, Not Implementation
```python
# ❌ Bad: Testing implementation
assert workflow_manager.exists("my-workflow") == True
assert compiler.compile(ir) is not None

# ✅ Good: Testing user experience
assert "Workflow executed successfully" in result.output
assert Path("expected-output.txt").exists()
```

## What NOT to Test

1. **Internal state** - Don't check private variables or internal data structures
2. **Implementation details** - Don't test HOW it works, test THAT it works
3. **Code coverage metrics** - 100% coverage doesn't mean good tests
4. **Every possible input** - Focus on realistic user scenarios
5. **Performance** - Unless it affects user experience (e.g., noticeable delays)

## Test File Organization

```
tests/test_cli/
├── test_named_workflow_execution.py  # Main feature tests
├── test_workflow_resolution.py       # Resolution logic tests
├── test_workflow_parameters.py       # Parameter handling tests
├── test_workflow_discovery.py        # List/describe command tests
└── fixtures/
    ├── sample_workflows.py           # Test workflow definitions
    └── test_data/                    # Test input files
```

## Success Criteria

Tests pass when:
1. Users can run workflows using intuitive commands
2. Error messages guide users to solutions
3. Parameters work as documented
4. Discovery commands show helpful information
5. The system behaves predictably and consistently

## Key Testing Principles

1. **Test the contract, not the implementation**
2. **Every test should fail if user experience breaks**
3. **Error messages are part of the API**
4. **Examples in tests serve as documentation**
5. **If a test doesn't prevent a real bug, delete it**