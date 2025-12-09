# Task 95: Unify LLM Usage via Simon Willison's llm Library

## ID
95

## Title
Unify LLM Usage via Simon Willison's llm Library

## Description
Replace hardcoded Anthropic SDK usage in discovery features and structure-only smart filtering with Simon Willison's `llm` library. This allows users to choose their preferred LLM provider for all pflow features, simplifies API key configuration, and potentially removes the `anthropic` SDK as a direct dependency.

## Status
not started

## Dependencies
- Task 92: Replace Planner with Agent Node + Pflow MCP Tools - If the planner is replaced, the `anthropic` SDK dependency can be fully removed. However, Task 95 can be implemented independently; it just means the anthropic SDK would still be needed for the planner until Task 92 is complete.

## Priority
medium

## Details
Currently, pflow has inconsistent LLM usage:

### Current State
1. **LLM Node** (in workflows): Uses `llm` library - supports any provider (Anthropic, OpenAI, Gemini, local models, etc.)
2. **Discovery features** (`registry discover`, `workflow discover`): Hardcoded to Anthropic via `install_anthropic_model()` in `src/pflow/planning/utils/anthropic_llm_model.py`
3. **Structure-only smart filtering** (31+ fields): Hardcoded to Anthropic Haiku

### Problems This Causes
- Users must configure Anthropic API key for discovery, even if they use other providers for everything else
- Inconsistent documentation ("use any provider" vs "Anthropic required for discovery")
- Extra dependency on `anthropic` SDK beyond what `llm` library provides
- Users can't use cheaper/faster models for discovery (e.g., Gemini Flash)

### Proposed Changes

#### 1. Discovery Commands
Files to modify:
- `src/pflow/cli/registry.py` (lines ~645-647) - `registry discover`
- `src/pflow/cli/commands/workflow.py` (lines ~140-142, ~262-264) - `workflow discover`

Replace:
```python
from pflow.planning.utils.anthropic_llm_model import install_anthropic_model
install_anthropic_model()
```

With `llm` library usage, similar to how `LLMNode` works in `src/pflow/nodes/llm/llm.py`.

#### 2. Structure-Only Smart Filtering
File to modify:
- `src/pflow/core/smart_filter.py`

Replace hardcoded Haiku calls with `llm` library, allowing users to configure which model handles field filtering.

#### 3. Configuration
- Add a pflow setting for default discovery model (e.g., `pflow settings set discovery-model gemini-2.5-flash`)
- Fall back to a sensible default (current behavior uses Claude, could default to Gemini Flash for cost efficiency)

### Design Decisions

1. **Model selection**: Allow configuration but provide good defaults
2. **Backwards compatibility**: If `ANTHROPIC_API_KEY` is set, it should still work (via `llm` library's Anthropic support)
3. **No prompt changes**: The prompts for discovery/filtering don't need to change, just the LLM call mechanism

### Files Likely Affected
- `src/pflow/cli/registry.py`
- `src/pflow/cli/commands/workflow.py`
- `src/pflow/core/smart_filter.py`
- `src/pflow/planning/utils/anthropic_llm_model.py` (may be removed or reduced)
- `src/pflow/planning/utils/anthropic_structured_client.py` (may be removed or reduced)
- `pyproject.toml` (potentially remove `anthropic` from dependencies if Task 92 is also done)

### Benefits
- Single LLM configuration path for users
- Any provider works for all features
- Simpler dependency tree (if combined with Task 92)
- Consistent with pflow's philosophy of using `llm` library
- Users can optimize cost/speed by choosing appropriate models

## Test Strategy

### Unit Tests
- Test discovery commands work with different `llm` models
- Test smart filtering works with different models
- Test fallback behavior when no model is configured
- Test that existing Anthropic key configuration still works

### Integration Tests
- End-to-end test of `pflow registry discover` with non-Anthropic model
- End-to-end test of `pflow workflow discover` with non-Anthropic model
- Test structure-only filtering with large responses using configured model

### Configuration Tests
- Test `pflow settings set discovery-model` works
- Test default model behavior
- Test error messages when model/key is not configured

### Regression Tests
- Ensure discovery quality doesn't degrade with different models
- Benchmark discovery speed/cost across providers
