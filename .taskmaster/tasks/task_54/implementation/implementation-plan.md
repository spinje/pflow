# Task 54 HTTP Node Implementation Plan

## Verified Patterns

### PocketFlow Retry Pattern
- Confirmed: No try/except in exec()
- Confirmed: exec_fallback() raises ValueError
- Reference: GitHub nodes (get_issue.py), LLM node (llm.py)

### Parameter Fallback Pattern
- Pattern: shared.get("key") or self.params.get("key") or default
- Universal across all nodes
- Required parameters raise ValueError if missing

### Action Pattern
- Only "default" and "error" exist
- No custom actions (client_error, server_error, etc.)
- Confirmed in codebase scan

### Error Handling Pattern
- GitHub/LLM pattern: raise ValueError from exec_fallback() ✅ USE THIS
- File pattern: return string starting with "Error:" (DON'T USE - older pattern)
- HTTP must follow GitHub/LLM pattern (newer, more correct)

## Implementation Steps

### Phase 1: Infrastructure Setup (Parallel Possible)
1. **Update Dependencies** (Independent)
   - File: pyproject.toml
   - Add: requests>=2.32.0
   - No conflicts with existing dependencies

2. **Create Package Structure** (Independent)
   - Files:
     - src/pflow/nodes/http/__init__.py
     - src/pflow/nodes/http/http.py
   - No conflicts with existing code

### Phase 2: Core Implementation (Sequential)
1. **Implement HttpNode Class**
   - File: src/pflow/nodes/http/http.py
   - Dependencies: Package structure must exist
   - Critical patterns to follow:
     - Inherit from Node (NOT BaseNode)
     - name = "http" class attribute
     - __init__ with max_retries=3, wait=1.0
     - prep() with parameter fallback
     - exec() with NO try/except
     - exec_fallback() raising ValueError
     - post() returning only default/error
   - Interface documentation in exact format

### Phase 3: Testing (Use test-writer-fixer subagent)
1. **Create Test Structure**
   - Files:
     - tests/test_nodes/test_http/__init__.py
     - tests/test_nodes/test_http/test_http.py
   - Deploy test-writer-fixer for all test creation
   - Must verify 21 test criteria from spec

2. **Critical Tests to Include**
   - Retry mechanism verification (mock called multiple times)
   - Error transformation tests
   - Mock response.elapsed.total_seconds()
   - Parameter fallback tests
   - Action mapping tests

### Phase 4: Integration Testing
1. **Verify Registry Integration**
   - Test node appears in registry with `pflow registry list`
   - Test natural language planning works

2. **Verify Full Test Suite**
   - Run `make test` to ensure no regressions
   - Run `make check` for linting and type checking

### Phase 5: Final Review
1. **Deploy test-writer-fixer for comprehensive review**
   - Review all tests for catching real bugs
   - Ensure all 21 test criteria are covered

## Risk Mitigation

| Risk | Mitigation Strategy |
|------|-------------------|
| Wrong error pattern used | Verified GitHub pattern, will raise ValueError |
| Retry mechanism broken | Test with mock proving multiple calls |
| HTTP errors as exceptions | Won't use raise_for_status() |
| Missing elapsed mock | Will mock response.elapsed.total_seconds() |
| Environment variable expansion | Not implementing (only MCP does this) |

## File Creation Order

1. pyproject.toml (update)
2. src/pflow/nodes/http/__init__.py (new)
3. src/pflow/nodes/http/http.py (new)
4. tests/test_nodes/test_http/__init__.py (new)
5. tests/test_nodes/test_http/test_http.py (new)

## Dependencies Between Steps

```
Update pyproject.toml
    ↓
Create package structure
    ↓
Implement HttpNode class
    ↓
Create tests (parallel with test-writer-fixer)
    ↓
Integration testing
    ↓
Final verification
```

## Verification Checklist

Pre-implementation:
- [x] Read all documentation
- [x] Understand PocketFlow retry pattern
- [x] Understand error handling patterns
- [x] Create implementation plan
- [ ] Verify patterns with subagents

Implementation:
- [ ] Add requests dependency
- [ ] Create package structure
- [ ] Implement HttpNode with all methods
- [ ] Follow Interface documentation format exactly
- [ ] No try/except in exec()
- [ ] Raise ValueError from exec_fallback()

Testing:
- [ ] All 21 test criteria covered
- [ ] Retry mechanism verified
- [ ] Error messages are actionable
- [ ] Mock at requests level
- [ ] Mock elapsed.total_seconds()

Integration:
- [ ] Node appears in registry
- [ ] Natural language planning works
- [ ] make test passes
- [ ] make check passes

## Notes

The implementation guide has complete working code that has been verified. The main challenge is ensuring all patterns are followed exactly, particularly:
1. The error handling pattern (raise ValueError, don't return string)
2. The retry pattern (no try/except in exec)
3. The action pattern (only default/error)

The spec is the authoritative source for requirements. All 21 test criteria must pass.