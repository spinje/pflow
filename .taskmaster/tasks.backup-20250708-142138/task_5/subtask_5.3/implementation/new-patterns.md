# Patterns Discovered

## Pattern: Tempfile-Based Dynamic Test Data
**Context**: When you need to test file-based operations with various edge cases
**Solution**: Create test files dynamically in each test using tempfile
**Why it works**: Eliminates complex fixture management, each test is isolated
**When to use**: Testing file scanners, parsers, or any file-based operations
**Example**:
```python
def test_edge_case(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.py"
        test_file.write_text('''
# Test content here
class TestNode:
    pass
''')
        results = scan_files([Path(tmpdir)])
        assert len(results) == expected
```

## Pattern: Document Security Risks Through Tests
**Context**: When code has inherent security risks that can't be fixed in MVP
**Solution**: Write tests that demonstrate and document the risk
**Why it works**: Makes risks explicit and provides evidence for future fixes
**When to use**: MVP implementations with known security implications
**Example**:
```python
def test_code_execution_risk(self):
    """Test that code is executed during import (documenting the security risk)."""
    # Test demonstrates the risk exists
    # Comment explains this is intentional documentation
```
