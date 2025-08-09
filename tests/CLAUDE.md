# CLAUDE.md - Test Navigation and Guidelines

This file provides comprehensive guidance for working with tests in the pflow project. It serves as a reference for both human developers and AI assistants when adding, modifying, or debugging tests.

## Test Structure Overview

The test suite follows a hierarchical structure that mirrors the source code organization:

```
tests/
├── test_cli/              # CLI command tests
├── test_core/             # Core functionality (IR, schemas)
├── test_docs/             # Documentation validation
├── test_integration/      # End-to-end integration tests
├── test_nodes/            # Node implementation tests
│   └── test_file/         # File node specific tests
├── test_planning/         # Workflow planning tests
├── test_registry/         # Registry and scanner tests
└── test_runtime/          # Runtime, compiler, flow tests
```

### Mapping Convention
- Source: `src/pflow/X/Y/module.py`
- Tests: `tests/test_X/test_Y/test_module.py`

## Running Tests

### Run All Tests
```bash
make test                          # Using Makefile (recommended)
uv run pytest                      # Direct pytest
uv run pytest -v                   # Verbose output
uv run pytest -vv                  # Very verbose (shows full diffs)
```

### Run Specific Test Categories
```bash
# Run only file node tests
uv run pytest tests/test_nodes/test_file/

# Run only CLI tests
uv run pytest tests/test_cli/

# Run only integration tests
uv run pytest tests/test_integration/
```

### Run Specific Test Files
```bash
# Run a single test file
uv run pytest tests/test_nodes/test_file/test_read_file.py

# Run with specific test method
uv run pytest tests/test_nodes/test_file/test_read_file.py::TestReadFileNode::test_successful_read
```

### Useful Test Flags
```bash
# Show local variables in tracebacks
uv run pytest -l

# Stop on first failure
uv run pytest -x

# Run last failed tests
uv run pytest --lf

# Run tests matching expression
uv run pytest -k "test_read"

# Show test coverage
uv run pytest --cov=src/pflow

# Generate coverage report
uv run pytest --cov=src/pflow --cov-report=html
```

## Test Categories and Purposes

### 1. CLI Tests (`test_cli/`)
- **test_cli.py**: Basic CLI functionality and commands
- **test_main.py**: Main entry point, argument parsing, stdin/file input handling

**Key Patterns**:
```python
from click.testing import CliRunner
runner = CliRunner()
result = runner.invoke(cli, ['command', 'args'])
assert result.exit_code == 0
```

### 2. Core Tests (`test_core/`)
- **test_ir_schema.py**: JSON IR schema validation
- **test_ir_examples.py**: Real-world IR examples and edge cases

**Key Focus**: Schema compliance, validation errors, edge cases

### 3. Node Tests (`test_nodes/`)
Currently contains file nodes, structured for future node types:
- **test_file/**: All file manipulation node tests
  - Individual node tests (read, write, copy, move, delete)
  - Integration tests between nodes
  - Retry behavior tests

**Test Structure for Nodes**:
1. Successful operation tests
2. Error handling tests
3. Edge cases (empty files, encoding issues)
4. Parameter validation
5. Integration with shared store

### 4. Registry Tests (`test_registry/`)
- **test_registry.py**: Node registration and lookup
- **test_scanner.py**: Node discovery and metadata extraction

**Key Areas**: Dynamic imports, metadata validation, error handling

### 5. Runtime Tests (`test_runtime/`)
- **test_compiler_basic.py**: Basic compilation functionality
- **test_compiler_integration.py**: Complex compilation scenarios
- **test_dynamic_imports.py**: Dynamic node loading
- **test_flow_construction.py**: Flow building and execution

**Focus**: IR to Flow compilation, error messages, performance

### 6. Integration Tests (`test_integration/`)
- **test_e2e_workflow.py**: Complete end-to-end workflows

**Purpose**: Validate full system behavior from CLI to execution

## Critical Testing Rules

### Retry Testing
**ALWAYS use `wait=0`** when testing retries to ensure fast execution:
```python
node = SomeNode(max_retries=2, wait=0)  # ✅ Fast
# If not in constructor: node.wait = 0
```

### Workflow Planning Tests
**Critical insight**: Prompt specificity determines whether pflow creates new workflows or reuses existing ones.

#### Testing Workflow Generation (Path B - Create New)
Use **specific, detailed prompts** when testing workflow generation:
```python
# ✅ CORRECT - Specific prompt triggers generation
"Create an issue triage report by fetching the last 30 open bug issues
from github project-x repository, categorize them by priority,
then write the report to reports/bug-triage.md"

# ❌ WRONG - Too vague, would trigger reuse instead
"Create an issue triage report"
```

#### Testing Workflow Reuse (Path A - Find Existing)
Use **vague, minimal prompts** when testing workflow discovery:
```python
# ✅ CORRECT - Vague prompt triggers reuse
"generate a changelog"

# ❌ WRONG - Too specific, would trigger generation
"generate a changelog from last 20 closed github issues and write to CHANGELOG.md"
```

**Why this matters**: Users provide detailed instructions when creating new workflows but use brief commands when running existing ones.

#### Use North Star Examples
Always reference `docs/vision/north-star-examples.md` for realistic test scenarios:
- **Primary (Complex)**: Generate changelog - Full GitHub → LLM → Git pipeline 🌟
- **Secondary (Medium)**: Issue triage report - Simpler analysis workflow
- **Tertiary (Simple)**: Summarize single issue - Minimal but useful

These examples represent real developer workflows that provide actual value, not toy examples.

## Writing New Tests

### Where to Place New Tests - Decision Tree

```
Is it testing a CLI command?
├─ YES → tests/test_cli/
│
├─ NO → Is it testing a node implementation?
   ├─ YES → Is it a file operation node?
   │   ├─ YES → tests/test_nodes/test_file/
   │   └─ NO → tests/test_nodes/test_<node_type>/
   │
   └─ NO → Is it testing core functionality (IR, schemas)?
      ├─ YES → tests/test_core/
      │
      └─ NO → Is it testing the registry or scanner?
         ├─ YES → tests/test_registry/
         │
         └─ NO → Is it testing runtime/compiler?
            ├─ YES → tests/test_runtime/
            │
            └─ NO → Is it an end-to-end workflow test?
               ├─ YES → tests/test_integration/
               └─ NO → tests/test_docs/ (or create new category)
```

### 1. Test File Naming
- Test files must start with `test_`
- Match source file names: `read_file.py` → `test_read_file.py`
- Use descriptive names for integration tests

### 2. Test Class Structure
```python
class TestNodeName:
    """Test NodeName functionality."""

    def test_successful_operation(self):
        """Test successful case with clear description."""
        # Arrange
        node = NodeName()
        shared = {"required": "data"}

        # Act
        result = node.run(shared)

        # Assert
        assert result == "expected"
        assert "output" in shared
```

### 3. Common Test Patterns

#### Testing Node Lifecycle
```python
# Full lifecycle test
prep_res = node.prep(shared)
exec_res = node.exec(prep_res)
action = node.post(shared, prep_res, exec_res)

# Using run() for complete execution
action = node.run(shared)
```

#### Testing Error Conditions
```python
# Method 1: Test specific exception in exec
with pytest.raises(SpecificError):
    node.exec(prep_res)

# Method 2: Test full lifecycle error handling
action = node.run(shared)
assert action == "error"
assert "error" in shared
assert "expected message" in shared["error"]
```

#### Using Temporary Files
```python
# For single file
with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
    f.write("content")
    temp_path = f.name
try:
    # test code
finally:
    os.unlink(temp_path)

# For directories
with tempfile.TemporaryDirectory() as tmpdir:
    file_path = os.path.join(tmpdir, "test.txt")
    # test code - cleanup is automatic
```

### 4. Fixtures and Utilities

#### Common Fixtures (in conftest.py files)
- `tests/conftest.py`: Root-level fixtures for all tests
- `tests/test_nodes/conftest.py`: Node-specific fixtures (currently empty)
- `tests/test_nodes/test_file/conftest.py`: File node fixtures (currently empty)

#### Current Fixture Locations
The project currently defines fixtures inline within test files. Future refactoring could move common fixtures to the appropriate conftest.py files:

```python
# Example: tests/test_nodes/test_file/conftest.py (future)
import pytest
import tempfile
import os

@pytest.fixture
def temp_file():
    """Create a temporary file with content."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("Test content")
        temp_path = f.name
    yield temp_path
    os.unlink(temp_path)

@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir

@pytest.fixture
def file_nodes_shared():
    """Common shared store setup for file nodes."""
    return {
        "encoding": "utf-8",
        "overwrite": False,
    }
```

#### Creating Test Fixtures
```python
@pytest.fixture
def sample_file(tmp_path):
    """Create a sample file for testing."""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("Sample content")
    return str(file_path)

@pytest.fixture
def mock_registry():
    """Create a mock registry with test nodes."""
    from pflow.registry import Registry
    registry = Registry()
    # Add mock nodes
    return registry
```

### 5. Test Organization Best Practices

1. **Group related tests in classes**
   ```python
   class TestReadFileNode:
       def test_successful_read(self): ...
       def test_missing_file(self): ...
       def test_encoding_error(self): ...
   ```

2. **Use descriptive test names**
   - Good: `test_copy_fails_when_destination_exists_without_overwrite`
   - Bad: `test_copy_fail`

3. **Test both success and failure paths**
   - Happy path (normal operation)
   - Error conditions
   - Edge cases
   - Parameter validation

4. **Keep tests focused**
   - One logical assertion per test
   - Use multiple tests rather than complex single tests

## Debugging Tests

### 1. Verbose Output
```bash
# See print statements and full diffs
uv run pytest -vv -s tests/test_file.py

# -v: verbose
# -vv: very verbose
# -s: no capture (shows print statements)
```

### 2. Debugging Failed Tests
```bash
# Drop into debugger on failure
uv run pytest --pdb

# Use breakpoint() in test code
def test_something():
    result = function()
    breakpoint()  # Drops into pdb
    assert result == expected
```

### 3. Test Isolation Issues
- Each test should be independent
- Use fixtures for setup/teardown
- Don't rely on test execution order
- Clean up resources (files, connections)

## Coverage Guidelines

### Running Coverage
```bash
# Simple coverage report
uv run pytest --cov=src/pflow

# Detailed HTML report
uv run pytest --cov=src/pflow --cov-report=html
# Open htmlcov/index.html

# Show missing lines
uv run pytest --cov=src/pflow --cov-report=term-missing
```

### Coverage Standards
- Aim for >80% coverage on new code
- Focus on critical paths and error handling
- Don't test for the sake of coverage
- Some code (like CLI output) may be harder to test

## Common Pitfalls and Solutions

### 1. Testing Framework Behavior Instead of Your Code
**Problem**: Creating PocketFlow flows with loops to test retry logic
**Solution**: Test node outputs and action strings, not flow execution
```python
# ❌ WRONG: Testing PocketFlow's loop execution
flow = Flow(start=generator)
validator - "retry" >> generator  # Don't create actual loops!

# ✅ RIGHT: Test that nodes return correct action strings
action = validator.run(shared)
assert action == "retry"  # PocketFlow handles the routing
```

### 2. Import Errors
**Problem**: `ModuleNotFoundError: No module named 'src'`
**Solution**: Run tests from project root, ensure PYTHONPATH is correct

### 3. File System Tests
**Problem**: Tests fail due to file permissions or existing files
**Solution**: Always use temporary directories, clean up in finally blocks

### 4. Shared State Between Tests
**Problem**: Tests pass individually but fail when run together
**Solution**: Ensure proper test isolation, don't modify global state

### 5. Platform-Specific Issues
**Problem**: Tests fail on different OS (Windows vs Unix)
**Solution**: Use `os.path.join()`, handle line endings, use `pathlib`

### 6. Async Test Issues
**Problem**: Async tests not running or hanging
**Solution**: Use `pytest-asyncio`, mark async tests with `@pytest.mark.asyncio`

### 7. Test Node Type Confusion
**Problem**: `CompilationError: Node type 'basic-node' not found in registry`
**Solution**: Use actual registered names: `test-node`, `test-node-retry`. Common aliases like `basic-node`, `transform-node` are conventions but not registered.

### 8. Test Node Interface Inconsistency
**Problem**: `KeyError: 'test_output'` when using wrong test node
**Solution**: `ExampleNode` uses `test_input`/`test_output`, `RetryExampleNode` uses `retry_input`/`retry_output`. Check node interfaces before use.

### 9. Click Interactive Testing Limitation
**Problem**: Can't test interactive prompts (workflow save dialog) with CliRunner
**Solution**: CliRunner always returns False for `isatty()`. Test components separately - execution and save functionality independently.

### 10. Mock Pollution Between Test Files
**Problem**: Mocks from one test file persist and break other tests (e.g., performance tests mocking `_process_nodes`)
**Solution**: Use `@pytest.fixture(autouse=True)` with `patch.stopall()` and `importlib.reload()` for modules with persistent mocks.

### 11. Test Registry Must Point to Real Modules
**Problem**: `CompilationError: Node type 'basic-node' not found` when registry has fake modules like `"test.module"`
**Solution**: Registry entries must point to importable modules. Use actual test file paths:
```python
# DON'T: {"module": "test.module", "class_name": "ExampleNode"}  # Module doesn't exist
# DO: {"module": "tests.test_runtime.test_compiler_integration", "class_name": "ExampleNode"}
# OR: {"module": "pflow.nodes.test_node", "class_name": "ExampleNode"}  # Real project nodes
```

### 11. Global State in context_builder Requires Isolation
**Problem**: 14 planning tests fail due to `_workflow_manager` global persisting between tests
**Solution**: Always patch when testing context builder:
```python
with patch("pflow.planning.context_builder._workflow_manager", None):
    context = build_discovery_context(registry_metadata=metadata)
```

## Test Maintenance

### When to Update Tests
1. **Adding new features**: Write tests first (TDD) or immediately after
2. **Fixing bugs**: Add test that reproduces bug before fixing
3. **Refactoring**: Ensure tests still pass, update if behavior changes
4. **Deprecating features**: Update or remove relevant tests

### Test Review Checklist
- [ ] Tests follow naming conventions
- [ ] Both success and error cases covered
- [ ] Resources properly cleaned up
- [ ] No hardcoded paths or values
- [ ] Tests are deterministic (not flaky)
- [ ] Clear test descriptions
- [ ] Appropriate use of fixtures
- [ ] No unnecessary complexity

## Integration with CI/CD

### GitHub Actions
Tests run automatically on:
- Pull requests
- Pushes to main branch
- Release tags

### Local CI Simulation
```bash
# Run same checks as CI
make check  # Includes linting, type checking
make test   # Run all tests
```

## Quick Reference

### Most Common Commands
```bash
# Run all tests
make test

# Run specific directory
uv run pytest tests/test_nodes/test_file/

# Run with coverage
uv run pytest --cov=src/pflow

# Run last failed
uv run pytest --lf

# Run tests matching pattern
uv run pytest -k "read_file"

# Debug test failures
uv run pytest --pdb -x
```

### Test File Structure Template
```python
"""Test module_name functionality."""

import pytest
from src.pflow.module import ClassName


class TestClassName:
    """Test ClassName behavior."""

    def test_successful_case(self):
        """Test successful operation."""
        # Arrange
        obj = ClassName()

        # Act
        result = obj.method()

        # Assert
        assert result == expected

    def test_error_case(self):
        """Test error handling."""
        obj = ClassName()

        with pytest.raises(ExpectedError):
            obj.method_that_fails()
```

## Performance Testing

For performance-sensitive code:

```python
def test_performance(benchmark):
    """Test operation performance."""
    result = benchmark(function_to_test, arg1, arg2)
    assert result == expected
```

Run with: `uv run pytest --benchmark-only`

## Test Data Management

### Small Test Data
- Inline in test files for readability
- Use fixtures for reusable data

### Large Test Data
- Store in `tests/data/` directory
- Load using fixtures
- Document data format and purpose

## Adding Tests for New Node Types

When adding a new node type to pflow, follow this structured approach:

### 1. Create Test Directory Structure
```bash
# For a new node type (e.g., llm nodes)
mkdir -p tests/test_nodes/test_llm
touch tests/test_nodes/test_llm/__init__.py
touch tests/test_nodes/test_llm/conftest.py
```

### 2. Standard Test Template for New Nodes

```python
# tests/test_nodes/test_llm/test_chat_node.py
"""Test ChatNode functionality."""

import pytest
from src.pflow.nodes.llm import ChatNode


class TestChatNode:
    """Test ChatNode behavior."""

    def test_successful_completion(self):
        """Test successful LLM response."""
        node = ChatNode()
        shared = {
            "prompt": "Hello",
            "model": "test-model"
        }

        # Mock the LLM response if needed
        with mock.patch('llm_library.complete') as mock_llm:
            mock_llm.return_value = "Hello! How can I help?"

            action = node.run(shared)

            assert action == "default"
            assert "response" in shared
            assert shared["response"] == "Hello! How can I help?"

    def test_missing_prompt(self):
        """Test error when prompt is missing."""
        node = ChatNode()
        shared = {"model": "test-model"}

        with pytest.raises(ValueError, match="Missing required 'prompt'"):
            node.prep(shared)

    def test_api_error_handling(self):
        """Test handling of API errors."""
        node = ChatNode()
        shared = {"prompt": "Hello", "model": "test-model"}

        with mock.patch('llm_library.complete') as mock_llm:
            mock_llm.side_effect = APIError("Rate limit exceeded")

            action = node.run(shared)

            assert action == "error"
            assert "error" in shared
            assert "Rate limit" in shared["error"]
```

### 3. Node-Specific Test Patterns

#### For I/O Nodes (files, network, etc.)
- Test successful operations
- Test missing resources
- Test permission errors
- Test resource cleanup

#### For Transform Nodes (data processing)
- Test valid transformations
- Test edge cases (empty input, null values)
- Test malformed data handling
- Test performance with large data

#### For API/Service Nodes
- Mock external services
- Test timeout handling
- Test retry logic
- Test authentication errors

#### For LLM/AI Nodes
- Mock model responses
- Test prompt injection protection
- Test token limit handling
- Test model fallback logic

### 4. Integration Test Template

```python
# tests/test_integration/test_llm_workflow.py
def test_llm_with_file_workflow():
    """Test workflow combining file reading and LLM processing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create input file
        input_file = os.path.join(tmpdir, "prompt.txt")
        with open(input_file, "w") as f:
            f.write("Summarize this text...")

        # Create workflow
        shared = {}

        # Read file
        read_node = ReadFileNode()
        shared["file_path"] = input_file
        read_node.run(shared)

        # Process with LLM
        llm_node = ChatNode()
        shared["prompt"] = shared["content"]
        with mock.patch('llm_library.complete') as mock_llm:
            mock_llm.return_value = "Summary: ..."
            llm_node.run(shared)

        # Write result
        write_node = WriteFileNode()
        shared["content"] = shared["response"]
        shared["file_path"] = os.path.join(tmpdir, "summary.txt")
        write_node.run(shared)

        # Verify
        assert os.path.exists(shared["file_path"])
```

## Future Considerations

### Planned Test Expansions
1. **LLM Node Tests** (`test_nodes/test_llm/`)
   - Mock LLM responses
   - Test prompt handling
   - Error scenarios
   - Token counting
   - Model fallback

2. **Transform Node Tests** (`test_nodes/test_transform/`)
   - JSON manipulation
   - Text processing
   - Data validation
   - Format conversion

3. **MCP Integration Tests**
   - Server communication
   - Protocol compliance
   - Error recovery
   - Connection pooling

4. **Performance Benchmarks**
   - Compilation speed
   - Memory usage
   - Large workflow handling
   - Concurrent execution

### Test Infrastructure Improvements
- Parallel test execution with pytest-xdist
- Test result caching
- Mutation testing with mutmut
- Property-based testing with hypothesis
- Snapshot testing for complex outputs
- Test performance monitoring

## Getting Help

1. **Run test with maximum verbosity**: `uv run pytest -vv`
2. **Check test output**: Look for actual vs expected values
3. **Review similar tests**: Find patterns in existing tests
4. **Use debugger**: Add `breakpoint()` or use `--pdb`
5. **Check CI logs**: Compare local vs CI environment

Remember: Good tests are as important as good code. They document behavior, prevent regressions, and enable confident refactoring.

## Project-Specific Test Patterns

### 1. Node Testing Pattern (PocketFlow nodes)
All nodes in pflow follow the PocketFlow pattern with prep/exec/post lifecycle:

```python
# Standard node test pattern
def test_node_operation(self):
    # 1. Create node instance
    node = SomeNode()

    # 2. Set up shared store
    shared = {"input_key": "input_value"}

    # 3. Test full lifecycle
    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    action = node.post(shared, prep_res, exec_res)

    # 4. Verify results
    assert action == "default"  # or "error", "retry", etc.
    assert "output_key" in shared
```

### 2. Error Testing Pattern
Two approaches for testing errors in nodes:

```python
# Approach 1: Test specific method
def test_error_in_exec(self):
    node = SomeNode()
    shared = {"bad": "input"}
    prep_res = node.prep(shared)

    with pytest.raises(SpecificError):
        node.exec(prep_res)

# Approach 2: Test full lifecycle with error handling
def test_error_handling(self):
    node = SomeNode()
    shared = {"bad": "input"}

    action = node.run(shared)  # run() handles exceptions
    assert action == "error"
    assert "error" in shared
    assert "Expected error message" in shared["error"]
```

### 3. File Node Specific Patterns

```python
# Pattern for testing file operations
def test_file_operation(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = os.path.join(tmpdir, "test.txt")

        # Create test file if needed
        with open(file_path, "w") as f:
            f.write("test content")

        # Test the node
        node = FileNode()
        shared = {"file_path": file_path, ...}
        action = node.run(shared)

        # Verify file state
        assert os.path.exists(file_path)  # or not, depending on operation
```

### 4. Registry and Import Testing

```python
# Pattern for testing dynamic imports
def test_import_node(self):
    from pflow.runtime.compiler import import_node_class
    from pflow.registry import Registry

    registry = Registry()
    node_class = import_node_class("node-type", registry)

    assert issubclass(node_class, BaseNode)
    assert hasattr(node_class, 'metadata')
```

### 5. CLI Testing Pattern

```python
# Pattern for CLI tests
def test_cli_command(self):
    from click.testing import CliRunner
    from pflow.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ['command', '--option', 'value'])

    assert result.exit_code == 0
    assert "expected output" in result.output
```

## Test Execution Cheatsheet

### Quick Commands (Copy & Paste)

```bash
# === RUNNING TESTS ===
make test                                    # Run all tests
uv run pytest -x                            # Stop on first failure
uv run pytest --lf                          # Run last failed
uv run pytest -k "test_name"                # Run matching tests
uv run pytest path/to/test.py::TestClass    # Run specific class
uv run pytest --pdb                         # Debug on failure

# === COVERAGE ===
uv run pytest --cov=src/pflow                        # Basic coverage
uv run pytest --cov=src/pflow --cov-report=html      # HTML report
uv run pytest --cov=src/pflow --cov-report=term-missing  # Show missing

# === SPECIFIC TEST SUITES ===
uv run pytest tests/test_cli/               # CLI tests only
uv run pytest tests/test_nodes/test_file/   # File node tests only
uv run pytest tests/test_integration/       # Integration tests only

# === DEBUGGING ===
uv run pytest -vv -s                        # Verbose with print statements
uv run pytest --tb=short                    # Shorter tracebacks
uv run pytest --tb=long                     # Longer tracebacks
```

## Current Test Statistics

As of the last reorganization:
- **Total test files**: 29
- **Total test functions**: ~350
- **Test categories**: 7 main categories
- **Largest test suite**: File nodes (46 tests across 7 files)
- **Test execution time**: ~4.5 seconds (all tests)

## Node Test Coverage by Type

Current node implementations with tests:
1. **File Nodes** (Complete coverage)
   - ReadFileNode: 8 tests
   - WriteFileNode: 9 tests
   - CopyFileNode: 5 tests
   - MoveFileNode: 4 tests
   - DeleteFileNode: 5 tests
   - Integration: 5 tests
   - Retry behavior: 10 tests

2. **Future Node Types** (Planned)
   - LLM nodes: TBD
   - Transform nodes: TBD
   - API nodes: TBD

## Test Quality Indicators

Look for these quality markers in tests:
- ✅ Clear test names that describe behavior
- ✅ Proper resource cleanup (files, connections)
- ✅ Both positive and negative test cases
- ✅ Edge case handling
- ✅ Deterministic (not flaky)
- ✅ Fast execution (< 100ms per test)
- ✅ Meaningful assertions
- ✅ Good error messages on failure

## Troubleshooting Test Failures

### Common Issues and Solutions

1. **Import errors**: Ensure running from project root
2. **File not found**: Check working directory, use absolute paths
3. **Permission errors**: Use temp directories, check file ownership
4. **Encoding errors**: Specify encoding explicitly
5. **Platform differences**: Use `os.path.join()`, handle line endings
6. **Timing issues**: Avoid sleep(), use proper synchronization
7. **Test pollution**: Ensure cleanup, don't share state

### Emergency Test Fixes

```bash
# Clean everything and start fresh
git clean -fdx tests/__pycache__
rm -rf .pytest_cache
uv sync
make test

# Run single test in isolation
uv run pytest -vv -s -x path/to/specific_test.py::test_function

# Maximum debugging info
uv run pytest -vv -s --tb=long --capture=no
```
