# Integration Test Patterns for Task 3

## Overview
Task 3 requires creating tests/test_e2e_workflow.py for end-to-end workflow testing.

## Test Location (from tests/CLAUDE.md)
- Integration tests go in: `tests/test_integration/`
- File should be: `tests/test_integration/test_e2e_workflow.py`

## Test Pattern Using CliRunner
```python
from click.testing import CliRunner
from pflow.cli import cli

def test_hello_workflow_execution():
    """Test executing a simple workflow from JSON file."""
    runner = CliRunner()

    # Create temporary workflow file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
        f.write(workflow_json)
        f.flush()

        # Run the workflow
        result = runner.invoke(cli, ['--file', f.name])

        # Verify success
        assert result.exit_code == 0
```

## Key Testing Elements (from tests/CLAUDE.md)
1. Use `click.testing.CliRunner` for CLI testing
2. Create temporary files for test data
3. Verify exit codes and output
4. Test both success and error cases
5. Clean up resources properly

## Shared Store Verification
For Task 3's requirement to "verify the final shared store contains expected values":
- Mock nodes should write to shared store
- Test should verify shared['content'] or other expected keys
- Use assertions to check final state

## Test Structure Template
```python
class TestEndToEndWorkflow:
    """Test end-to-end workflow execution."""

    def test_read_write_workflow(self):
        """Test simple read-file => write-file workflow."""
        # Arrange: Create workflow JSON
        # Act: Execute via CLI
        # Assert: Verify results
```
