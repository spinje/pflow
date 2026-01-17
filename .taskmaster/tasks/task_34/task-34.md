# Task 34: Prompt Accuracy Tracking System

## Description
Implement a lightweight developer tool that displays LLM prompt test accuracy directly in prompt markdown files using YAML frontmatter. This enables rapid prompt iteration by showing current performance metrics where developers need them most - in the files they're editing. The system will help developers systematically improve each prompt to 100% accuracy.

## Status
done

## Completed
2025-08-17

## Dependencies
- Task 33: Extract planner prompts to markdown files - The prompts must be in separate markdown files before we can add accuracy tracking to them

## Priority
medium

## Details
Currently, developers improving LLM prompts must run tests separately, manually track whether changes improved accuracy, and have no visibility of current performance when editing prompt files. This context switching slows prompt improvement and makes it difficult to track progress toward accuracy goals.

### Solution Design (MVP Approach)
The system will add minimal YAML frontmatter to each prompt markdown file showing current test accuracy. A standalone Python script will run existing tests and update accuracy when improved. Key design decisions:

- **Developer-only tool**: Not exposed through user-facing pflow CLI
- **Single Python script**: `test_runner.py` in the prompts directory (~200 lines)
- **Minimal frontmatter**: Only 4 required fields (name, test_path, accuracy, last_tested)
- **Git-friendly updates**: Only commits when accuracy improves, reducing noise
- **Simple workflow**: `python test_runner.py discovery --update`

### Technical Implementation
The tool will:
1. Parse YAML frontmatter from prompt markdown files
2. Execute existing pytest tests with `RUN_LLM_TESTS=1` environment variable
3. Calculate accuracy from test results (passed/total)
4. Update frontmatter only when accuracy improves by >2% (handles LLM variance)
5. Preserve existing prompt loading functionality in `loader.py`

### Files to Modify
- Add frontmatter to 6 prompt files: `src/pflow/planning/prompts/*.md`
- Create new file: `src/pflow/planning/prompts/test_runner.py`
- Update existing: `src/pflow/planning/prompts/loader.py` (to handle frontmatter)
- Add documentation: `src/pflow/planning/prompts/README.md`

### Developer Experience
The core value is the emotional feedback loop of seeing accuracy improve:
1. Developer opens prompt file, sees "accuracy: 85.0%"
2. Thinks "I can beat that"
3. Edits prompt
4. Runs test
5. Sees "accuracy: 90.0%"
6. Feels satisfaction
7. Commits "Improved discovery: 85% → 90%"

## Test Strategy
Testing will ensure the tool works reliably without breaking existing functionality:

### Unit Tests
- Frontmatter parsing with various formats (valid, invalid, missing)
- Accuracy calculation from different test result patterns
- Update logic ensuring only improvements are saved
- Edge cases (empty files, malformed YAML, no frontmatter)

### Integration Tests
- Verify prompt loading still works with frontmatter added
- Test runner executes actual pytest tests correctly
- Environment variable `RUN_LLM_TESTS=1` is properly set
- Accuracy updates are reflected in files

### Key Test Scenarios
- Running tests for each of the 6 prompts
- Handling test failures gracefully
- Verifying 2-3% LLM variance doesn't trigger constant updates
- Ensuring backward compatibility with existing prompt usage
- Testing the complete workflow: edit → test → update → commit
