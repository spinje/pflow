# Task 34: Prompt Accuracy Tracking System

## Executive Summary

Implement a lightweight accuracy tracking system for LLM prompts that displays test accuracy directly in prompt markdown files. This developer-only tool enables rapid prompt iteration by showing current performance metrics where they're needed most - in the prompt files themselves.

## Problem Statement

Currently, developers improving prompts must:
1. Edit a prompt in `src/pflow/planning/prompts/*.md`
2. Run tests separately with `RUN_LLM_TESTS=1 pytest ...`
3. Manually track whether changes improved accuracy
4. Have no visibility of current accuracy when editing

This context switching slows prompt improvement and makes it hard to track progress.

## Solution Overview

Add minimal YAML frontmatter to prompt markdown files that displays current test accuracy. A developer tool updates this accuracy when tests are run, providing immediate visibility of prompt performance.

## Requirements

### Functional Requirements

1. **Accuracy Display**: Each prompt file shows its current test accuracy in frontmatter
2. **Automatic Updates**: Running tests updates accuracy if improved
3. **Developer-Only**: Not exposed through user-facing `pflow` CLI
4. **Simple Format**: Minimal frontmatter with only essential fields
5. **Git-Friendly**: Only commits when accuracy improves (reduces noise)

### Non-Functional Requirements

1. **Performance**: Test execution time unchanged
2. **Simplicity**: <500 lines of new code
3. **No New Dependencies**: Use existing YAML/markdown handling
4. **Backward Compatible**: Existing tests continue to work

## Technical Design

### 1. Frontmatter Schema

Each prompt markdown file will have minimal frontmatter:

```yaml
---
name: discovery
test_path: tests/test_planning/llm/prompts/test_discovery_prompt.py::TestDiscoveryPromptSensitive
accuracy: 85.0
last_tested: 2024-01-15
---

# Discovery Prompt

[Rest of prompt content...]
```

**Fields** (all required):
- `name`: Prompt identifier (matches filename without .md)
- `test_path`: Pytest path to run tests for this prompt
- `accuracy`: Current accuracy percentage (0-100)
- `last_tested`: Date of last test run (YYYY-MM-DD)

### 2. File Structure

```
src/pflow/planning/prompts/
├── discovery.md              # With frontmatter
├── component_browsing.md     # With frontmatter
├── parameter_discovery.md    # With frontmatter
├── parameter_mapping.md      # With frontmatter
├── workflow_generator.md     # With frontmatter
├── metadata_generation.md    # With frontmatter
├── loader.py                 # Existing - loads prompts
└── test_runner.py           # NEW - developer testing tool
```

### 3. Developer Tool

Create `src/pflow/planning/prompts/test_runner.py` as a standalone script:

```python
#!/usr/bin/env python3
"""Developer tool for testing and tracking prompt accuracy."""

import subprocess
import sys
from pathlib import Path
from datetime import date
import re

def run_prompt_test(prompt_name: str, update: bool = False):
    """Run tests for a prompt and optionally update accuracy."""

    # 1. Load prompt file and extract test_path
    prompt_file = Path(__file__).parent / f"{prompt_name}.md"
    content = prompt_file.read_text()

    # 2. Extract current accuracy from frontmatter
    current_accuracy = extract_accuracy(content)

    # 3. Run pytest and capture results
    test_path = extract_test_path(content)
    passed, total = run_tests(test_path)
    new_accuracy = (passed / total * 100) if total > 0 else 0

    # 4. Display results
    print(f"Test Results: {passed}/{total} = {new_accuracy:.1f}%")

    # 5. Update file if improved and update flag set
    if update and new_accuracy > current_accuracy:
        update_frontmatter(prompt_file, new_accuracy)
        print(f"✅ Updated accuracy: {current_accuracy:.1f}% → {new_accuracy:.1f}%")
    elif new_accuracy > current_accuracy:
        print(f"💡 Improvement available: Run with --update to save")
    else:
        print(f"Current best: {current_accuracy:.1f}%")

if __name__ == "__main__":
    # Simple CLI: python test_runner.py discovery [--update]
    prompt = sys.argv[1]
    update = "--update" in sys.argv
    run_prompt_test(prompt, update)
```

### 4. Usage Examples

```bash
# Test discovery prompt (read-only)
$ cd src/pflow/planning/prompts
$ python test_runner.py discovery
Running tests for discovery prompt...
Test Results: 18/20 = 90.0%
💡 Improvement available: Run with --update to save

# Test and update if improved
$ python test_runner.py discovery --update
Running tests for discovery prompt...
Test Results: 19/20 = 95.0%
✅ Updated accuracy: 90.0% → 95.0%

# Test all prompts (bash loop)
$ for prompt in discovery browsing generator; do
    python test_runner.py $prompt
  done
```

### 5. Integration with Existing Tests

Modify test files to expose accuracy metrics:

```python
# tests/test_planning/llm/prompts/test_discovery_prompt.py

class TestDiscoveryPromptSensitive:
    """Existing test class - add result tracking."""

    @classmethod
    def get_test_results(cls) -> tuple[int, int]:
        """Return (passed, total) for accuracy calculation."""
        # This method is called by test_runner.py
        # Run all test methods and count results
        passed = 0
        total = 0

        # Run each test case
        for test_case in cls.get_test_cases():
            try:
                cls.run_test_case(test_case)
                passed += 1
            except AssertionError:
                pass
            total += 1

        return passed, total
```

## Implementation Plan

### Phase 1: Core Infrastructure (2 hours)
1. Create `test_runner.py` with basic functionality
2. Add frontmatter parsing and updating logic
3. Test with one prompt file

### Phase 2: Test Integration (2 hours)
1. Modify test classes to expose accuracy metrics
2. Implement test execution and result capture
3. Handle test failures gracefully

### Phase 3: Apply to All Prompts (1 hour)
1. Add frontmatter to all 6 prompt files
2. Run initial baseline tests
3. Document current accuracy levels

### Phase 4: Developer Documentation (1 hour)
1. Add usage instructions to `src/pflow/planning/prompts/README.md`
2. Document workflow for prompt improvement
3. Add examples of successful prompt iterations

## Success Criteria

1. **Accuracy Visible**: Opening any prompt file shows current accuracy
2. **Easy Testing**: Single command to test any prompt
3. **Progress Tracking**: Git history shows accuracy improvements
4. **No User Impact**: Changes not visible in production pflow CLI
5. **Developer Adoption**: Team uses tool for prompt improvements

## Validation

### Test Cases

1. **Accuracy Improvement**: Test updates when accuracy improves
2. **No Regression**: Test doesn't update when accuracy decreases
3. **Fresh File**: Test handles prompts without frontmatter
4. **Parse Errors**: Test handles malformed frontmatter gracefully

### Acceptance Criteria

- [ ] All 6 prompt files have frontmatter with accuracy
- [ ] test_runner.py successfully tests each prompt
- [ ] Accuracy only updates on improvement
- [ ] No changes to user-facing pflow CLI
- [ ] Documentation complete for developers

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM non-determinism causes accuracy variance | Medium | Only update on significant improvement (>2%) |
| Test execution becomes slow | Low | Cache results, run single prompts |
| Frontmatter breaks prompt loading | High | Thorough testing of loader.py changes |
| Git conflicts on accuracy field | Low | Only commit improvements, round to 1 decimal |

## Out of Scope

- User-facing CLI commands
- Accuracy regression detection
- Historical tracking/charts
- CI/CD integration
- A/B testing capabilities
- Cross-prompt performance comparison

## Dependencies

- Existing test suite in `tests/test_planning/llm/prompts/`
- Prompt files in `src/pflow/planning/prompts/`
- Python YAML parser (already available)
- pytest (already used)

## Timeline

- **Day 1**: Implement core infrastructure and test with discovery prompt
- **Day 2**: Integrate with all prompts and tests
- **Day 3**: Documentation and team onboarding

Total effort: 6 hours of focused development

## Future Considerations

While out of scope for this task, future enhancements could include:
- Automated regression alerts
- Prompt version tagging
- Test case contribution tracking
- Performance benchmarking

## Conclusion

This minimal implementation provides maximum value with minimum complexity. By showing accuracy directly in prompt files, developers can iterate quickly and track progress through git history. The solution requires no new dependencies, doesn't affect end users, and can be implemented in under 500 lines of code.

The key insight: put metrics where developers need them most - in the files they're editing.