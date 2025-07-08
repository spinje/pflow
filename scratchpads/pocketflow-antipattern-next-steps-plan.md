# PocketFlow Anti-Pattern Refactoring - Next Steps Plan

## Immediate Priority: Fix Breaking Issues

### Step 1: Fix Linting Errors (5 minutes)

1. **Fix missing errno import in delete_file.py**:
   - Add `import errno` at the top of `/src/pflow/nodes/file/delete_file.py`

2. **Fix import order in __init__.py**:
   Two options:
   - Option A: Move NonRetriableError to separate file `exceptions.py`
   - Option B: Reorder to put class definition at bottom with `# noqa: E402`
   
   Recommend Option A for cleaner architecture:
   ```python
   # /src/pflow/nodes/file/exceptions.py
   """File operation exceptions."""
   
   class NonRetriableError(Exception):
       """Exception for errors that should not be retried."""
       pass
   ```

3. **Fix TRY300/TRY301 warnings** (optional but quick):
   - Move return statements into else blocks
   - Or add `# noqa` comments if intentional

### Step 2: Update Breaking Tests (30-45 minutes)

For each of the 8 failing tests, apply one of these patterns:

#### Pattern A: For Error Testing (Use pytest.raises)
```python
# OLD
def test_missing_file(self):
    exec_res = node.exec(prep_res)
    assert exec_res[1] == False

# NEW
def test_missing_file(self):
    with pytest.raises(FileNotFoundError):
        node.exec(prep_res)
```

#### Pattern B: For Success Testing (No change needed)
```python
# These should still work
exec_res = node.exec(prep_res)
action = node.post(shared, prep_res, exec_res)
assert action == "default"
```

#### Pattern C: For Integration Testing (Use node.run())
```python
# OLD
prep_res = node.prep(shared)
exec_res = node.exec(prep_res)
action = node.post(shared, prep_res, exec_res)

# NEW  
action = node.run(shared)
assert action == "error"  # or "default"
assert "error" in shared  # for error cases
```

#### Specific Test Fixes:

1. **test_missing_file**:
   - Use Pattern A with `pytest.raises(FileNotFoundError)`
   - Or Pattern C with `node.run(shared)`

2. **test_encoding_error**:
   - Use Pattern A with `pytest.raises(UnicodeDecodeError)`

3. **test_error_propagation**:
   - Use Pattern C - this tests integration behavior

4. **test_copy_overwrite_protection**:
   - Use Pattern A with `pytest.raises(NonRetriableError)`

5. **test_copy_source_not_found**:
   - Use Pattern A with `pytest.raises(FileNotFoundError)`

6. **test_move_overwrite_protection**:
   - Use Pattern A with `pytest.raises(NonRetriableError)`

7. **test_move_source_not_found**:
   - Use Pattern A with `pytest.raises(FileNotFoundError)`

8. **test_delete_without_confirmation**:
   - Use Pattern A with `pytest.raises(NonRetriableError)`

### Step 3: Add New Test Coverage (45-60 minutes)

Create new test file or add to existing: `test_file_nodes_retry.py`

#### Test Structure:
```python
import pytest
from unittest.mock import patch, mock_open, MagicMock
from src.pflow.nodes.file import ReadFileNode, NonRetriableError

class TestFileNodeRetryBehavior:
    """Test retry behavior and error handling."""
```

#### Critical Tests to Add:

1. **Test Retry Success**:
```python
def test_read_file_retry_succeeds_on_third_attempt(self):
    """Test that transient errors are retried and eventually succeed."""
    node = ReadFileNode()  # Has max_retries=3
    shared = {"file_path": "/test/file.txt"}
    
    # Mock open to fail twice then succeed
    mock_file = mock_open(read_data="content")
    with patch("builtins.open") as mock_open_func:
        mock_open_func.side_effect = [
            PermissionError("Locked"),
            PermissionError("Still locked"),
            mock_file.return_value
        ]
        
        action = node.run(shared)
        
        assert action == "default"
        assert "content" in shared["content"]
        assert mock_open_func.call_count == 3
```

2. **Test Non-Retriable Error**:
```python
def test_validation_error_no_retry(self):
    """Test that NonRetriableError fails immediately without retry."""
    node = DeleteFileNode()
    shared = {"file_path": "/test/file.txt", "confirm_delete": False}
    
    with patch("os.path.exists", return_value=True):
        action = node.run(shared)
        
    assert action == "error"
    assert "not confirmed" in shared["error"]
    # Verify exec was only called once (no retries)
```

3. **Test Fallback Messages**:
```python
def test_exec_fallback_messages(self):
    """Test that exec_fallback provides appropriate error messages."""
    node = ReadFileNode()
    
    # Test each exception type
    test_cases = [
        (FileNotFoundError("test"), "does not exist"),
        (PermissionError("test"), "Permission denied"),
        (UnicodeDecodeError("utf-8", b"", 0, 1, "test"), "encoding"),
        (Exception("generic"), "Could not read")
    ]
    
    for exc, expected_text in test_cases:
        result = node.exec_fallback(("/path", "utf-8"), exc)
        assert expected_text in result
        assert result.startswith("Error:")
```

4. **Test Full Lifecycle**:
```python
def test_full_lifecycle_with_retry_mechanism(self):
    """Test complete node lifecycle including retry mechanism."""
    # This tests that node.run() properly orchestrates everything
```

5. **Test Wait Between Retries**:
```python
def test_wait_between_retries(self):
    """Test that wait parameter delays retries."""
    # Mock time.sleep and verify it's called
```

#### Edge Cases to Test:

1. **Race Conditions**:
   - File deleted between exists check and read
   - File created between not-exists check and write

2. **Cross-Device Move**:
   - Test the special case where copy succeeds but delete fails

3. **Disk Space**:
   - Test disk space check raises appropriate errors

4. **Encoding Issues**:
   - Test various encoding errors get proper messages

### Step 4: Run Full Test Suite (5 minutes)

```bash
# Run just file node tests first
pytest tests/test_file_nodes.py -xvs

# If those pass, run full suite
make test

# Run linting
make check
```

### Step 5: Optional Improvements

1. **Add Type Hints**:
   - Update method signatures with proper types
   - Run mypy to verify

2. **Add Logging**:
   - Log retry attempts for debugging
   - Log which attempt succeeded

3. **Documentation**:
   - Update node docstrings to mention retry behavior
   - Document which errors are retriable

## Important Reminders

1. **Don't Forget Imports**:
   - `import errno` in delete_file.py
   - `from . import NonRetriableError` in nodes that use it

2. **Test Both Paths**:
   - Test direct method calls (unit tests)
   - Test full lifecycle with node.run() (integration tests)

3. **Check Edge Cases**:
   - Empty files
   - Unicode in filenames
   - Very large files
   - Permission edge cases

4. **Verify Retry Behavior**:
   - Actually mock failures and verify retries happen
   - Test that max_retries is respected

## Success Criteria

✅ All linting errors fixed (`make check` passes)
✅ All existing tests updated and passing
✅ New retry behavior tests added and passing
✅ Full test suite passes (`make test`)
✅ Documentation updated if needed

## Time Estimate

- Fix linting: 5 minutes
- Update failing tests: 30-45 minutes  
- Add new tests: 45-60 minutes
- Testing/debugging: 15-30 minutes
- **Total: 2-2.5 hours**

## Final Checklist

- [ ] errno imported in delete_file.py
- [ ] Import order fixed in __init__.py
- [ ] All 8 failing tests updated
- [ ] Retry success test added
- [ ] NonRetriableError test added
- [ ] Fallback message tests added
- [ ] Full lifecycle test added
- [ ] make check passes
- [ ] make test passes
- [ ] Consider commit message: "refactor: Fix PocketFlow anti-pattern in file nodes for proper retry support"

## If You Get Stuck

1. Check `/Users/andfal/projects/pflow/pocketflow/tests/test_fall_back.py` for examples
2. Read `/Users/andfal/projects/pflow/pocketflow/docs/core_abstraction/node.md` 
3. Remember: Let exceptions bubble up in exec(), handle in exec_fallback()
4. The pattern is about separating success path from error handling

Good luck! This refactoring makes pflow significantly more reliable.