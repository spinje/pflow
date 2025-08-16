# Prompt Accuracy Tracking System

This directory contains the LLM prompts used by the pflow planner, along with a developer tool for tracking and improving prompt accuracy.

## Overview

Each prompt markdown file includes YAML frontmatter that tracks test accuracy across multiple runs. This helps developers systematically improve prompts by providing immediate visibility of performance metrics.

## Quick Start

Test a prompt and update accuracy (default behavior):
```bash
uv run python tools/test_prompt_accuracy.py discovery
```

Test without updating (dry run):
```bash
uv run python tools/test_prompt_accuracy.py discovery --dry-run
```

Test all prompts:
```bash
for prompt in discovery component_browsing parameter_discovery parameter_mapping workflow_generator; do
    uv run python tools/test_prompt_accuracy.py $prompt
done
```

## How It Works

### Frontmatter Structure

Each prompt file contains frontmatter tracking accuracy metrics:

```yaml
---
name: discovery
test_path: tests/test_planning/llm/prompts/test_discovery_prompt.py::TestDiscoveryPromptSensitive
test_command: uv run python tools/test_prompt_accuracy.py discovery
version: 1.0
latest_accuracy: 87.0        # Most recent test run
test_runs: [87.0, 85.0, 84.0]  # Last 10 runs for this version
average_accuracy: 85.3       # Average of test_runs
test_count: 20              # Total number of test cases
previous_version_accuracy: 82.0  # Best average from previous version
last_tested: 2025-01-15
prompt_hash: a3f2b1c4       # Hash of prompt content for version detection
---
```

### Accuracy Tracking

The system addresses LLM response variance (2-3% between runs) by:
- Storing multiple test runs (up to 10)
- Calculating average accuracy
- Only updating when improvement is significant
- Tracking version history

### Test Count Context

The `test_count` field provides important context for accuracy metrics:
- **Identifies testing gaps**: A prompt with 3 tests vs 30 tests
- **Contextualizes accuracy**: 100% on 3 tests ≠ 100% on 30 tests
- **Automatically updated**: Reflects current test suite size
- **Prioritizes effort**: Focus on prompts with low test counts

This helps developers understand both the accuracy AND robustness of testing.

### Version Management

When you significantly modify a prompt:
1. The tool detects content changes via hash
2. Prompts to increment version
3. Moves current average to `previous_version_accuracy`
4. Resets `test_runs` for fresh tracking

## Developer Workflow

### 1. Check Current Accuracy

Open any prompt file to see its current accuracy in the frontmatter:
```bash
cat discovery.md | head -15
```

### 2. Improve the Prompt

Edit the prompt content to improve accuracy. The tool will detect changes and offer to increment the version if significant.

### 3. Test Your Changes

Run tests (automatically saves results):
```bash
uv run python tools/test_prompt_accuracy.py discovery
```

Output shows:
- Latest test result
- Running average
- Comparison to previous version

### 4. Update Accuracy

To test without saving:
```bash
uv run python tools/test_prompt_accuracy.py discovery --dry-run
```

This shows what would change without updating files.

### 5. Commit Progress

Git commits show accuracy improvements:
```bash
git diff discovery.md  # Shows accuracy: 85.0 → 90.0
git commit -m "Improved discovery prompt accuracy: 85% → 90%"
```

## Available Prompts

| Prompt | Purpose | Test Coverage | Test Command Field |
|--------|---------|---------------|--------------------|
| `discovery` | Determines if existing workflow matches request | ✅ TestDiscoveryPromptSensitive | Yes |
| `component_browsing` | Selects nodes/workflows for generation | ✅ TestBrowsingPromptSensitive | Yes |
| `parameter_discovery` | Extracts parameters from user input | ✅ TestParameterDiscoveryPromptSensitive | Yes |
| `parameter_mapping` | Maps parameters to workflow inputs | ✅ TestParameterMappingPromptSensitive | Yes |
| `workflow_generator` | Generates workflow IR from components | ✅ TestGeneratorPromptEffectiveness | Yes |
| `metadata_generation` | Creates searchable workflow metadata | ❌ No tests yet | Yes |

The `test_command` field in each prompt's frontmatter shows how to run tests using the test_runner.py tool.

## Important Notes

### Environment Variable Required

Tests require the `RUN_LLM_TESTS=1` environment variable to make real LLM API calls. The test_runner.py script sets this automatically.

You can run tests for any prompt using the `test_command` from its frontmatter:
```bash
# Copy the test_command from any prompt file
uv run python tools/test_prompt_accuracy.py discovery
```

Or run the underlying pytest directly:
```bash
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_discovery_prompt.py::TestDiscoveryPromptSensitive -v
```

### LLM API Keys

If LLM API keys are not configured, you can set them using the llm CLI:
```bash
llm keys set anthropic  # For Claude models
llm keys set openai     # For GPT models
```

> You can assume that the llm CLI is installed and configured.

### Test Execution Time

LLM tests can take 30-60 seconds per prompt due to API calls. The test runner has a 5-minute timeout per prompt.

### Accuracy Goals

Target accuracy levels:
- **85%+** - Good baseline
- **90%+** - Production ready
- **95%+** - Excellent
- **100%** - Perfect (but may overfit to test cases)

## Troubleshooting

### Tests Skip Silently

If tests show 0% accuracy with no errors, check:
1. `RUN_LLM_TESTS=1` is set
2. LLM API keys are configured
3. Test path in frontmatter is correct

### Version Won't Increment

The tool only prompts for version increment when:
1. Prompt content has changed significantly
2. You respond 'y' to the increment prompt

### Accuracy Varies Between Runs

LLM responses have natural variance (2-3%). The averaging system smooths this out. Focus on the average, not individual runs.

### Missing Test Files

The `metadata_generation` prompt lacks tests. Its `test_path` is set to "none" and the tool will skip testing.

## Best Practices

1. **Test frequently** - Run tests after each prompt edit
2. **Track progress** - Use git commits to document improvements
3. **Focus on average** - Don't chase single good runs
4. **Version major changes** - Increment version for significant rewrites
5. **Document patterns** - Note what improvements worked in commit messages

## Implementation Details

The system consists of:
- **test_runner.py** - Standalone developer tool (~300 lines)
- **Frontmatter** - YAML metadata in each prompt file
- **loader.py** - Updated to skip frontmatter when loading prompts

This is a developer-only tool, not exposed through the main pflow CLI. It's designed for rapid iteration during prompt improvement sessions.

## Future Enhancements

While out of scope for the current implementation, potential improvements include:
- Automated regression detection
- Historical accuracy graphs
- Cross-prompt performance comparison
- Integration with CI/CD pipelines

For now, the focus is on providing immediate, actionable feedback to developers improving prompts.