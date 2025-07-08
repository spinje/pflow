# Knowledge Synthesis for Subtask 3.1

## Relevant Patterns from Previous Tasks

### CLI Architecture Patterns
- **Direct Command Pattern**: Task 2 established that `pflow workflow` is more intuitive than subcommands
- **Three Input Methods Pattern**: Prioritization (file > stdin > args) prevents ambiguity - Task 2
- **Click Context Pattern**: `ctx.obj` provides clean data sharing between commands - Task 1 & 2
- **Where it's relevant**: The CLI already implements these patterns in `main.py`

### Error Handling Patterns
- **Clear Error Messages**: All tasks emphasized helpful, actionable error messages with suggestions
- **Fail-Fast Philosophy**: Validate inputs early with clear error messages
- **Phased Error Handling**: Each phase has distinct error context (Task 4)
- **Where it's relevant**: Review error messages in execute_json_workflow() for completeness

### Integration Patterns
- **Integration Points First**: Test integration points early (all tasks)
- **Real Integration Tests Beat Mocks**: Use real files/imports when safe (Task 11)
- **Registry Without Key Duplication**: Store node name as dict key, not in value (Task 5)
- **Where it's relevant**: The e2e tests already use real components; review for coverage

### PocketFlow Integration
- **Dynamic Import Pattern**: Use importlib.import_module() + getattr() (Task 4)
- **PocketFlow Parameter Handling**: _orch() creates copies and calls set_params() (Task 4)
- **Shared Store Communication**: All nodes communicate through shared dictionary (all tasks)
- **Where it's relevant**: The compiler and execution already handle these correctly

## Known Pitfalls to Avoid

### From Task Implementation Experience
- **PocketFlow Modification**: Task 3 modified pocketflow/__init__.py (lines 101-107) - this is temporary but necessary
- **Registry Must Exist**: No registry = nothing works. Need clear error message (Task 5)
- **Empty Parameters**: Empty parameters dict won't trigger set_params() (Task 4)
- **Line Number Addition**: ReadFileNode adds line numbers by design - affects content flow (Task 11)

### From CLI Development
- **Click Validators**: Run during parsing phase, preventing custom error messages (Task 2)
- **Virtual Environment Commands**: Commands in .venv/bin/ when using venv (Task 1)
- **Shell Operator Conflicts**: Already avoided by choosing => operator (Task 2)

## Established Conventions

### Code Style Conventions
- **Natural Interface Patterns**: Intuitive key names in shared store (file_path, content)
- **Structured Node Interface**: Consistent docstring format with Interface section (Task 11)
- **Two-Tier Node Naming**: Check explicit name attribute first, then kebab-case (Task 5)
- **Must follow**: These conventions are established across all nodes

### Testing Conventions
- **Test-Driven Development**: Write tests alongside implementation (all tasks)
- **Progressive Complexity**: Organize examples from minimal to advanced (Task 6)
- **Invalid Examples as Teaching Tools**: Show what doesn't work with expected errors (Task 6)
- **Must follow**: Comprehensive tests are critical for integration tasks

### Documentation Conventions
- **Documentation-Driven Examples**: Create explanatory markdown alongside examples (Task 6)
- **Document Decisions**: Record why choices were made, not just what (all tasks)
- **Layered Documentation**: Separate structural from business logic (Task 6)
- **Must follow**: Clear documentation essential for first integration milestone

## Codebase Evolution Context

### What Has Changed Since Task Decomposition
- **Task 3 Implemented**: Commit dff02c3 implemented the core functionality
- **PocketFlow Modified**: Temporary change to preserve node parameters
- **Registry Population**: Scripts added for temporary registry population
- **E2E Tests Added**: Basic test coverage already exists

### Current State vs Original Plan
- **Original Plan**: Implement CLI integration from scratch
- **Current Reality**: Integration already works; focus on review and polish
- **Shift in Focus**: From implementation to validation and enhancement
- **Impact**: Need to verify completeness rather than build from scratch

### Integration Points Proven
- All 6 dependency tasks integrate correctly ✓
- The shared store pattern works end-to-end ✓
- PocketFlow can be wrapped successfully by pflow ✓
- The architecture is sound for the MVP ✓

## Key Insights for Review Focus

1. **Error Message Quality**: Review all error paths for clarity and helpfulness
2. **Result Handling**: Current implementation just shows "success" - could be more informative
3. **Edge Cases**: Check handling of empty files, missing permissions, large files
4. **Test Coverage**: Verify all integration points have appropriate tests
5. **Documentation**: Ensure examples and user guidance are complete
6. **Registry UX**: The temporary populate script needs clear documentation until Task 10
