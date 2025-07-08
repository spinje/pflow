# AI Agent Prompt: Test Structure Reorganization

## Task Overview
Reorganize the pflow project's test structure from a flat directory layout to a hierarchical structure that mirrors the source code organization. This will improve test maintainability and discoverability.

## Key Context
- The project currently has 300+ tests all passing
- The main issue is `test_file_nodes.py` with 859 lines that needs splitting
- All changes should be made in a new git branch `test-reorganization`
- Follow the detailed plan in `test-restructuring-plan.md`

## Your Mission

1. **Read the full plan** at `scratchpads/test-reorganization/test-restructuring-plan.md` before starting
2. **Create the git branch**: `git checkout -b test-reorganization`
3. **Follow the phases exactly**:
   - Phase 1-2: Setup and directory creation
   - Phase 3: Migrate simple test files
   - Phase 4: Split the large test_file_nodes.py
   - Phase 5-6: Update imports and configuration

## Critical Requirements

1. **Test count preservation**: Run `pytest --collect-only | grep -c "test_"` before starting and after each phase. The count must remain the same.

2. **Incremental verification**: After moving each file:
   ```bash
   pytest -v [moved_file_path]  # Test the moved file
   pytest -v                    # Test everything still works
   ```

3. **Git discipline**:
   - Use `git mv` for moving files to preserve history
   - Commit after each successful phase with descriptive message
   - Example: `git commit -m "test: Reorganize - Phase 3 complete, moved non-file tests"`

4. **When splitting test_file_nodes.py**:
   - Extract each test class to its own file
   - Update all imports at the top of each new file
   - Move shared fixtures to `test_nodes/test_file/conftest.py`
   - Only delete the original file after verifying all tests pass

## Expected Outcome

By the end, running `pytest tests/test_nodes/test_file/` should run only file node tests, and the structure should match:
```
tests/test_X/test_Y/ maps to src/pflow/X/Y/
```

## Safety Measures

1. **Never proceed if tests fail** - Stop and investigate
2. **Keep the original test count** - We should end with the same number of tests
3. **Preserve test coverage** - Run `pytest --cov=src/pflow` before and after
4. **Work methodically** - Better to be slow and correct than fast and broken

## How to Start

1. First, read the full plan to understand all phases
2. Verify current tests pass: `pytest -v`
3. Count current tests: `pytest --collect-only | grep -c "test_"`
4. Create the branch and begin Phase 1

## Success Criteria

- [ ] All 300+ tests still pass (run make test to verify)
- [ ] Make check still works (run make check to verify)
- [ ] `test_file_nodes.py` is split into 6 smaller files
- [ ] Can run file tests with `pytest tests/test_nodes/test_file/`
- [ ] Clear directory structure mirroring source code
- [ ] No test code lost (verify with git diff)
- [ ] CI/CD still works (run `make test`)

Remember: Take your time, verify each step, and commit often. The plan has all the details you need.
