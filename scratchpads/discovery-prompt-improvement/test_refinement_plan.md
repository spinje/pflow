# Test Case Refinement Plan

## Current State: 19 Tests with Issues
- 52.6% accuracy (but was testing wrong things)
- Too many redundant tests
- Focus on confidence scores instead of decisions

## Goal: ~10-12 High-Quality Tests

### Essential Test Categories

#### 1. **Core Matches** (3 tests)
Must correctly identify clear matches:
- `exact_match`: "read a file" → finds simple-read
- `semantic_match`: "triage github issues" → finds issue-triage
- `with_parameters`: "generate changelog for v2.0" → finds changelog

#### 2. **Core Rejections** (3 tests)
Must reject requests for missing capabilities:
- `wrong_domain`: "send email" → no email capability
- `missing_capability`: "changelog and send to slack" → no Slack
- `vague_request`: "analyze data" → too ambiguous

#### 3. **Data Distinctions** (3 tests)
Must distinguish data sources/formats:
- `wrong_source`: "changelog from PRs" → uses issues not PRs
- `wrong_format`: "analyze JSON" → only CSV exists
- `different_operation`: "summarize single issue" → different from triage

#### 4. **Language Handling** (2 tests)
Must handle natural variations:
- `synonym_handling`: "triage bugs" → "bugs" = "issues"
- `single_word`: "changelog" → unambiguous match

#### 5. **Performance** (1 test)
Just one representative test for speed

### Tests to Remove

**Remove completely:**
1. `perf_analyze` - redundant performance test
2. `perf_triage` - redundant performance test
3. `perf_deploy` - redundant performance test
4. `perf_read` - redundant performance test
5. `partial_name` - redundant with single_word
6. `different_function` - too ambiguous
7. `ambiguous_github` - unclear test
8. `overly_specific` - redundant with parameter test

**Keep but rename/clarify:**
- `no_match` → `wrong_domain`
- `additional_steps` → `missing_capability`
- `different_source` → `wrong_source`
- `wrong_file_type` → `wrong_format`
- `vague_request` → keep as `vague_request`
- `synonym_pr` + `synonym_issues` → merge into `synonym_handling`

### Final Test Count: 12 Essential Tests

This gives us:
- Better coverage of important scenarios
- No redundancy
- Clear rationale for each test
- Focus on decision correctness

## Implementation Steps

1. Update test cases in test_discovery_prompt.py
2. Ensure each test has clear rationale
3. Remove confidence level requirements
4. Focus on decision correctness
5. Run tests to establish new baseline