# Discovery System Test Reorganization Summary

## Overview
Successfully reorganized 56 tests from 4 monolithic files (including North Star tests) into a clear hierarchical structure that separates unit tests from LLM tests.

## Previous Structure (4 files, 56 tests)
```
tests/test_planning/
├── test_discovery.py                      # 28 tests (mostly mocked) - DELETED
├── test_discovery_llm_integration.py      # 5 tests (real LLM) - DELETED
├── test_discovery_happy_path.py           # 11 tests (mixed mocked/real) - DELETED
└── test_discovery_north_star.py           # 12 tests (North Star workflows) - DELETED
```

## New Structure (10 files, 57 tests)
```
tests/test_planning/
├── unit/                                   # ALL MOCKED - Fast, always run (44 tests)
│   ├── test_discovery_routing.py          # 5 tests - action strings, paths
│   ├── test_discovery_error_handling.py   # 9 tests - exec_fallback, edge cases
│   ├── test_browsing_selection.py         # 9 tests - component selection logic + North Star browsing
│   ├── test_shared_store_contracts.py     # 8 tests - data flow
│   └── test_happy_path_mocked.py          # 13 tests - Path A scenarios + North Star workflows
│
└── llm/                                    # REAL LLM - Expensive, selective run (13 tests)
    ├── prompts/                            # PROMPT-SENSITIVE tests
    │   ├── test_discovery_prompt.py       # 3 tests - discovery prompt structure
    │   └── test_browsing_prompt.py        # 1 test - browsing prompt structure
    │
    ├── behavior/                           # BEHAVIOR tests (prompt-resilient)
    │   ├── test_path_a_reuse.py          # 4 tests - workflow reuse + North Star real LLM
    │   └── test_confidence_thresholds.py  # 4 tests - confidence routing
    │
    └── integration/                        # END-TO-END with real LLM
        └── test_discovery_to_browsing.py  # 1 test - full discovery flow
```

## Key Improvements

### 1. Clear Separation of Concerns
- **Unit tests** run fast with mocks, always included in CI
- **LLM tests** require `RUN_LLM_TESTS=1`, separated by sensitivity:
  - Prompt-sensitive tests break when prompts change
  - Behavior tests verify functionality regardless of prompt format
  - Integration tests verify end-to-end flow

### 2. North Star Tests Preserved
- **Critical value tests** for pflow's flagship workflows (changelog, triage, release notes)
- Moved to appropriate locations based on mocking vs real LLM
- Maintained complete test coverage for Path A workflow reuse

### 2. Better Test Organization
- Tests grouped by what they verify, not by original file
- Each file has a clear purpose documented in its header
- File names immediately convey what's being tested

### 3. Improved Maintainability
- Easy to find tests for specific functionality
- Clear when to run each test category
- Obvious where to add new tests

## Running the Tests

### Run all unit tests (fast, no LLM needed):
```bash
pytest tests/test_planning/unit -v
```

### Run specific unit test categories:
```bash
pytest tests/test_planning/unit/test_discovery_routing.py -v
pytest tests/test_planning/unit/test_browsing_selection.py -v
```

### Run LLM tests (requires API key):
```bash
# All LLM tests
RUN_LLM_TESTS=1 pytest tests/test_planning/llm -v

# Just prompt-sensitive tests
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts -v

# Just behavior tests
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior -v
```

## Test Coverage
- **Unit tests**: 44 tests covering all mocked scenarios including North Star workflows
- **LLM tests**: 13 tests covering real LLM interactions including North Star validation
- **Total**: 57 tests (preserving all original tests plus organizational improvements)

## Files Deleted
1. `/tests/test_planning/test_discovery.py`
2. `/tests/test_planning/test_discovery_llm_integration.py`
3. `/tests/test_planning/test_discovery_happy_path.py`
4. `/tests/test_planning/test_discovery_north_star.py`

## Verification
All tests pass successfully:
- Unit tests: ✅ 44 passed (including North Star)
- LLM tests: ⏸️ 13 skipped (no RUN_LLM_TESTS env var)
- Total: 934 passed, 24 skipped, 1 warning in 5.81s

## North Star Test Distribution

### Moved to `unit/test_happy_path_mocked.py`:
- 9 mocked North Star workflow tests (changelog, triage, release notes, etc.)
- Test various phrasings and confidence thresholds
- Validate workflow value proposition

### Moved to `unit/test_browsing_selection.py`:
- 2 component browsing tests for North Star workflows
- Test workflows as building blocks for new workflows

### Moved to `llm/behavior/test_path_a_reuse.py`:
- 1 real LLM test for North Star workflow discovery
- Validates real LLM can recognize flagship workflows
