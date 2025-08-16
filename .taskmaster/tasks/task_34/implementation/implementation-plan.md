# Task 34 Implementation Plan: Prompt Accuracy Tracking System

## Overview
Implement a lightweight developer tool that displays test accuracy directly in prompt markdown files using YAML frontmatter. This enables rapid prompt iteration with immediate visibility of performance metrics.

## Phase 1: Context Gathering (30 minutes)

### Parallel Context Gathering Tasks

#### 1. Prompt System Analysis
**Goal**: Understand current prompt loading and structure
- Analyze `src/pflow/planning/prompts/loader.py` - how prompts are loaded
- Examine all 6 prompt files in `src/pflow/planning/prompts/*.md`
- Identify template variable patterns ({{variables}})
- Check if any other code depends on prompt file format

#### 2. Test Infrastructure Discovery
**Goal**: Understand test structure and execution patterns
- Analyze `tests/test_planning/llm/prompts/` structure
- Identify test class patterns and validation methods
- Find how to run specific test methods via pytest
- Understand how pass/fail counts can be extracted

#### 3. Integration Points Verification
**Goal**: Ensure changes won't break existing functionality
- Check how nodes use the prompt loader
- Verify no other code reads prompt files directly
- Confirm frontmatter won't affect prompt loading

## Phase 2: Core Implementation (2 hours)

### Component 1: test_runner.py (Main Script)
**File**: `src/pflow/planning/prompts/test_runner.py`

**Core Functions**:
1. `parse_frontmatter(content: str) -> tuple[dict, str]`
   - Extract YAML frontmatter and prompt content
   - Handle missing/malformed frontmatter gracefully
   - Initialize with defaults if frontmatter missing

2. `update_frontmatter(file_path: Path, new_accuracy: float, metadata: dict) -> None`
   - Add new test run to test_runs array (max 10)
   - Recalculate average_accuracy
   - Update latest_accuracy and last_tested
   - Write back to file

3. `run_tests(test_path: str) -> tuple[int, int]`
   - Execute pytest with RUN_LLM_TESTS=1
   - Parse output for passed/failed counts
   - Handle test failures gracefully

4. `detect_version_change(prompt_content: str, metadata: dict) -> bool`
   - Compare prompt content hash with stored hash
   - Return True if significant change detected
   - Prompt user to confirm version increment

5. `handle_version_increment(metadata: dict) -> dict`
   - Move average_accuracy to previous_version_accuracy
   - Clear test_runs array
   - Increment version number
   - Update prompt content hash

6. `run_prompt_test(prompt_name: str, update: bool = False) -> None`
   - Main function orchestrating the workflow
   - Load prompt, check for version changes
   - Run tests, update metrics, show results

### Component 2: Frontmatter Schema (ENHANCED)
**Format**:
```yaml
---
name: discovery
test_path: tests/test_planning/llm/prompts/test_discovery_prompt.py::TestDiscoveryPromptSensitive
version: 1.0
latest_accuracy: 87.0                # Most recent test run
test_runs: [87.0, 85.0, 84.0, 88.0] # Last 5-10 runs for this version
average_accuracy: 86.0               # Calculated from test_runs
previous_version_accuracy: 82.0      # Best average from previous version
last_tested: 2024-01-15
---
```

**Key Behaviors**:
- Store all test runs directly in frontmatter (max 10)
- Calculate average from test_runs array
- Track version and previous version's best average
- Auto-detect significant prompt changes for version increment

## Phase 3: Test Integration (1 hour)

### Task 1: Subprocess Test Execution
- Implement subprocess.run() with proper environment
- Parse pytest output for results
- Handle various failure modes

### Task 2: Accuracy Calculation
- Extract passed/total from test output
- Calculate percentage with 1 decimal precision
- Implement >2% improvement threshold

## Phase 4: Apply to All Prompts (1 hour)

### Task 1: Add Frontmatter to Each Prompt
Files to modify:
1. `discovery.md`
2. `component_browsing.md`
3. `parameter_discovery.md`
4. `parameter_mapping.md`
5. `workflow_generator.md`
6. `metadata_generation.md`

### Task 2: Run Baseline Tests
- Execute tests for each prompt
- Record initial accuracy
- Verify all tests run successfully

## Phase 5: Loader Integration (30 minutes)

### Task 1: Update loader.py
- Add frontmatter parsing
- Strip frontmatter before returning prompt
- Maintain backward compatibility

## Phase 6: Documentation & Testing (1 hour)

### Task 1: Developer Documentation
**File**: `src/pflow/planning/prompts/README.md`
- Usage instructions
- Workflow examples
- Troubleshooting guide

### Task 2: Comprehensive Testing
- Unit tests for frontmatter parsing
- Integration tests for accuracy updates
- Verify no regressions in existing tests

## Implementation Order

1. **Context Gathering** (Deploy 3 parallel subagents)
2. **Create test_runner.py** with basic structure
3. **Implement frontmatter parsing** and test with dummy data
4. **Add subprocess test execution** with result parsing
5. **Test with discovery.md** as proof of concept
6. **Apply to all 6 prompts** with initial accuracy
7. **Update loader.py** to handle frontmatter
8. **Create documentation**
9. **Run full test suite** to verify no regressions

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Tests skip without RUN_LLM_TESTS=1 | Always set in subprocess env |
| LLM variance causes constant updates | >2% improvement threshold |
| Frontmatter breaks prompt loading | Thorough testing of loader.py |
| Complex test output parsing | Use simple regex patterns |

## Success Criteria

- ✅ All 6 prompt files have frontmatter with accuracy
- ✅ test_runner.py successfully tests each prompt
- ✅ Accuracy only updates on >2% improvement
- ✅ Frontmatter parsing doesn't break existing prompt loading
- ✅ Developer can see accuracy when opening any prompt file
- ✅ Single command runs tests for any prompt
- ✅ make test passes with no regressions
- ✅ make check passes (linting, type checking)

## Key Decisions

1. **Simplicity over framework** - Single Python script
2. **Developer-only** - Not in main pflow CLI
3. **Minimal frontmatter** - Only 4 required fields
4. **Git-friendly** - Only update on improvement
5. **Round to 1 decimal** - e.g., 85.0% not 85.0371%

## Notes

- The prompts were just extracted from inline code to markdown files
- There's an orphaned templates.py file - ignore it
- Tests already work with RUN_LLM_TESTS=1
- The emotional feedback loop is the core value