# Developer Tools

This directory contains developer tools that are NOT part of the pflow package distribution.

## test_prompt_accuracy.py

A tool for testing and tracking the accuracy of LLM prompts used by the pflow planner.

### Usage

```bash
# Test a prompt and update metrics (default behavior)
uv run python tools/test_prompt_accuracy.py discovery

# Test without updating (dry run)
uv run python tools/test_prompt_accuracy.py discovery --dry-run

# Test all prompts
for prompt in discovery component_browsing parameter_discovery parameter_mapping workflow_generator; do
    uv run python tools/test_prompt_accuracy.py $prompt
done
```

### Features

- Tracks test accuracy over multiple runs
- Handles LLM response variance through averaging
- Automatic version management when prompts change
- Stores all metrics in prompt file frontmatter
- Shows test count for context

### Requirements

This tool requires dev dependencies to be installed:
```bash
uv sync  # Installs all dependencies including dev
```

The tool specifically needs:
- PyYAML (for frontmatter parsing)
- pytest (for running tests)
- LLM API keys configured

See `src/pflow/planning/prompts/README.md` for detailed documentation about the prompt accuracy tracking system.