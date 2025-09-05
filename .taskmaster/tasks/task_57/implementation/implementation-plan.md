# Task 57 Implementation Plan

## Executive Summary

Update planner tests to use realistic north star examples that validate actual user behavior. Replace simplified prompts with exact verbose examples from architecture docs, ensuring tests catch real bugs instead of creating false confidence.

## Current State Assessment

### Existing Test Files

1. **test_happy_path_mocked.py** (Path A - discovery/reuse)
   - ✅ Has 4 north star workflows defined
   - ❌ Uses simplified prompts instead of verbose
   - ❌ Missing parameter extraction validation
   - ❌ One performance assertion to convert (line 874)

2. **test_generator_north_star.py** (Path B - generation)
   - ✅ Tests changelog and triage workflows
   - ❌ Missing tertiary example (issue summary)
   - ❌ Not using exact verbose prompts
   - ❌ Generic parameter validation

3. **test_north_star_realistic_e2e.py**
   - ❌ Doesn't exist - needs creation

### Key Discoveries

- `github-list-prs` IS REAL (not mock as some tests claim)
- discovered_params uses STRING values: {"version": "1.3", "limit": "20"}
- Standard performance warning pattern exists
- test_registry_data fixture available

## Implementation Tasks

### Phase 1: Update test_happy_path_mocked.py (2 hours)

#### Task 1.1: Replace Simplified Prompts
**Current:**
```python
"generate a changelog from the last 20 closed issues"
```

**Replace with exact verbose:**
```python
CHANGELOG_VERBOSE = """generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."""
```

**Dependencies:** None
**Risk:** Tests may fail initially if discovery logic expects simplified prompts
**Mitigation:** Update mock responses to handle verbose prompts

#### Task 1.2: Add Parameter Extraction Tests
**Add new test methods:**
- `test_parameter_extraction_changelog` - Validates "1.3", "20", branch name
- `test_parameter_extraction_triage` - Validates "50", date pattern
- `test_parameter_mapping_convergence` - Tests complete pipeline

**Dependencies:** Task 1.1 (need verbose prompts first)
**Risk:** Parameter extraction might not work with current mocks
**Mitigation:** Add parameter discovery mocks

#### Task 1.3: Convert Performance Assertion
**Location:** Line 874
**Change:**
```python
# FROM:
assert path_a_time < 1.0

# TO:
if path_a_time > 1.0:
    logger.warning(f"Path A slower than expected: {path_a_time:.2f}s (model-dependent)")
```

**Dependencies:** None
**Risk:** None
**Mitigation:** N/A

### Phase 2: Update test_generator_north_star.py (1.5 hours)

#### Task 2.1: Update Existing Prompts
**Replace all test prompts with exact north star examples:**
- Changelog test → exact verbose prompt
- Triage test → exact verbose prompt (with double "the")
- Update parameter assertions to check specific values

**Dependencies:** None
**Risk:** Generated workflows might change structure
**Mitigation:** Update expected workflow structures

#### Task 2.2: Add Tertiary Example Test
**Create new test:**
```python
def test_summarize_issue_simple_workflow(self):
    """Test Path B flow for simple issue summary North Star example."""
    shared = {
        "user_input": "summarize github issue 1234"
    }
    # Complete Path B flow implementation
```

**Dependencies:** Understanding of existing test structure
**Risk:** Simple prompt might trigger Path A instead of Path B
**Mitigation:** Adjust mock confidence scores

### Phase 3: Create test_north_star_realistic_e2e.py (2 hours)

#### Task 3.1: Create File Structure
**Location:** `tests/test_planning/llm/integration/test_north_star_realistic_e2e.py`
**Contents:**
- Import necessary testing utilities
- Define north star prompts as constants
- Create test class `TestNorthStarRealisticE2E`

**Dependencies:** None
**Risk:** File placement confusion
**Mitigation:** Follow existing llm/integration pattern

#### Task 3.2: Implement Complete Pipeline Tests
**Test methods:**
- `test_changelog_verbose_complete_pipeline` - Full Path B flow
- `test_changelog_brief_reuse` - Path A flow
- `test_triage_verbose_complete_pipeline` - Full Path B flow
- `test_issue_summary_simple` - Minimal workflow

**Dependencies:** Task 3.1
**Risk:** Complex mocking requirements
**Mitigation:** Reuse patterns from existing tests

#### Task 3.3: Add Path Selection Validation
**Ensure tests validate:**
- Verbose prompts → action="not_found" (Path B)
- Brief prompts → action="found_existing" (Path A)
- Confidence thresholds work correctly

**Dependencies:** Task 3.2
**Risk:** Path selection logic might be fragile
**Mitigation:** Test multiple prompt variations

### Phase 4: Validation & Documentation (0.5 hours)

#### Task 4.1: Run Test Suite
```bash
pytest tests/test_planning/ -v
make test
make check
```

**Dependencies:** All previous tasks
**Risk:** Regressions in other tests
**Mitigation:** Fix issues iteratively

#### Task 4.2: Document Patterns
**Create/Update:**
- Test README with north star approach
- Comments in test files explaining patterns
- Update progress log with lessons learned

**Dependencies:** Task 4.1
**Risk:** None
**Mitigation:** N/A

## Risk Analysis

### High Risk Items
1. **Exact prompt matching** - One character difference could break tests
   - Mitigation: Copy prompts directly from architecture docs

2. **Mock node confusion** - Using non-existent nodes
   - Mitigation: Verified all required nodes exist

### Medium Risk Items
1. **Parameter type assumptions** - String vs int confusion
   - Mitigation: Always use strings for parameter values

2. **Performance variance** - Tests failing on slow API
   - Mitigation: Convert all timing to warnings

### Low Risk Items
1. **Test organization** - File placement
   - Mitigation: Follow existing patterns

## Dependencies Map

```
Task 1.1 (prompts) → Task 1.2 (parameters)
                  ↘
                    Task 4.1 (validation) → Task 4.2 (docs)
                  ↗
Task 2.1 (prompts) → Task 2.2 (tertiary)
         ↘
           Task 3.1 (file) → Task 3.2 (pipeline) → Task 3.3 (paths)

Task 1.3 (performance) - Independent
```

## Testing Strategy

### Unit Tests (Mocked)
- Focus: Path selection logic
- Coverage: All 3 north star examples
- Validation: Specific parameter values

### Integration Tests (Real LLM)
- Focus: Complete pipeline flow
- Coverage: Primary & secondary examples
- Validation: Workflow structure & validity

### Regression Testing
- Ensure no existing tests break
- Validate performance improvements
- Check parameter extraction accuracy

## Success Criteria

- [ ] All 3 north star tiers tested with exact prompts
- [ ] Parameter extraction validates "1.3" and "20" exactly
- [ ] Path A triggers on brief prompts (action="found_existing")
- [ ] Path B triggers on verbose prompts (action="not_found")
- [ ] Performance checks produce warnings, not failures
- [ ] Production WorkflowValidator used
- [ ] No mock nodes when real available
- [ ] make test passes
- [ ] make check passes

## Time Estimate

- Phase 1: 2 hours
- Phase 2: 1.5 hours
- Phase 3: 2 hours
- Phase 4: 0.5 hours
- **Total: 6 hours**

## Next Steps

1. Start with Task 1.1 - Update prompts in test_happy_path_mocked.py
2. Run tests frequently to catch issues early
3. Document discoveries in progress log
4. Use test-writer-fixer agent for complex test creation