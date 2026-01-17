# Task 95: Unify LLM Usage via Simon Willison's llm Library

## Description
Replace hardcoded Anthropic SDK usage in discovery features, structure-only smart filtering, and **fix the global monkey-patch that causes inconsistent model handling** with Simon Willison's `llm` library. This allows users to choose their preferred LLM provider for all pflow features, simplifies API key configuration, and fixes critical bugs with model name validation.

## Status
done

## Completed
2025-12-19

## Dependencies
- Task 92: Replace Planner with Agent Node + Pflow MCP Tools - If the planner is replaced, the `anthropic` SDK dependency can be fully removed. However, Task 95 can be implemented independently; it just means the anthropic SDK would still be needed for the planner until Task 92 is complete.

## Priority
high (upgraded from medium due to bug fix)

## Details

### Bug Report: Inconsistent LLM Model Name Handling

This task now includes fixing a critical bug discovered during investigation:

**Root Cause Identified:**

1. **Global monkey-patch at `main.py:3550`**: `_install_anthropic_model_if_needed()` is called for ALL workflow executions, not just planner. This patches `llm.get_model()` globally.

2. **User's model parameter is ignored**: `AnthropicStructuredClient` (line 67) hardcodes `self.model = "claude-sonnet-4-20250514"` regardless of what model the user specified.

3. **Different code paths**: `pflow registry run` doesn't install the monkey-patch, so it uses the original `llm` library with strict model validation. Workflows use the patched version.

**Symptoms:**
- Invalid model names silently "work" in workflows (because user's model is ignored)
- Valid Claude models fail in `registry run` but work in workflows
- Token usage is reported but responses can be empty for certain inputs
- Users can't actually choose which Claude model to use

### Current State
1. **LLM Node** (in workflows): Uses `llm` library BUT monkey-patch intercepts all Claude models
2. **Discovery features** (`registry discover`, `workflow discover`): Hardcoded to Anthropic via `install_anthropic_model()`
3. **Structure-only smart filtering** (31+ fields): Hardcoded to Anthropic Haiku
4. **Workflow execution** (`main.py:3550`): Installs monkey-patch for ALL workflows, not just planner

### Problems This Causes
- Users must configure Anthropic API key for discovery, even if they use other providers for everything else
- Inconsistent documentation ("use any provider" vs "Anthropic required for discovery")
- Extra dependency on `anthropic` SDK beyond what `llm` library provides
- Users can't use cheaper/faster models for discovery (e.g., Gemini Flash)
- **BUG**: Invalid model names silently fail in workflows
- **BUG**: Valid Claude models fail in `registry run` but work in workflows
- **BUG**: User's model choice is ignored for Claude models

### Proposed Changes

#### 1. Remove Global Monkey-Patch from Workflow Execution (BUG FIX)

File to modify:
- `src/pflow/cli/main.py` (lines 3549-3550)

**Current behavior**: `_install_anthropic_model_if_needed()` called for ALL workflow executions

**Proposed**: Only call it when the planner is actually used (natural language input), NOT for file/saved workflow execution. This ensures:
- `pflow workflow.json` uses original `llm` library (consistent with `registry run`)
- `pflow "natural language"` still gets Anthropic features for planning
- Invalid model names are properly rejected for user workflows
- Users can actually choose their Claude model variant

**Implementation approach**:
```python
# In main.py workflow_command(), move the monkey-patch installation
# to ONLY the natural language planning path, not file/saved workflow execution

# Before (current - broken):
_install_anthropic_model_if_needed(verbose)  # Called for ALL workflows

# After (fixed):
# Only install when entering planning path (natural language input)
# File and saved workflows should use unmodified llm library
```

#### 2. Discovery Commands

Files to modify:
- `src/pflow/cli/registry.py` (lines ~645-647) - `registry discover`
- `src/pflow/cli/commands/workflow.py` (lines ~140-142, ~262-264) - `workflow discover`

Replace:
```python
from pflow.planning.utils.anthropic_llm_model import install_anthropic_model
install_anthropic_model()
```

With `llm` library usage, similar to how `LLMNode` works in `src/pflow/nodes/llm/llm.py`.

#### 3. Structure-Only Smart Filtering

File to modify:
- `src/pflow/core/smart_filter.py`

Replace hardcoded Haiku calls with `llm` library, allowing users to configure which model handles field filtering.

#### 4. Configuration

- Add a pflow setting for default discovery model (e.g., `pflow settings set discovery-model gemini-2.5-flash`)
- Fall back to a sensible default (current behavior uses Claude, could default to Gemini Flash for cost efficiency)

### Design Decisions

1. **Model selection**: Allow configuration but provide good defaults
2. **Backwards compatibility**: If `ANTHROPIC_API_KEY` is set, it should still work (via `llm` library's Anthropic support)
3. **No prompt changes**: The prompts for discovery/filtering don't need to change, just the LLM call mechanism
4. **Planner isolation**: The monkey-patch should ONLY affect the planner path, not user workflows
5. **Consistent validation**: All LLM calls should go through the same validation path

### Files Affected

**Bug Fix (Priority 1):**
- `src/pflow/cli/main.py` - Remove/scope monkey-patch at line 3550

**Discovery/Filtering (Priority 2):**
- `src/pflow/cli/registry.py` - Remove `install_anthropic_model()` from discover command
- `src/pflow/cli/commands/workflow.py` - Remove `install_anthropic_model()` from discover commands
- `src/pflow/core/smart_filter.py` - Replace hardcoded Anthropic with `llm` library

**Cleanup (Priority 3, after Task 92):**
- `src/pflow/planning/utils/anthropic_llm_model.py` - May be removed or reduced to planner-only
- `src/pflow/planning/utils/anthropic_structured_client.py` - May be removed or reduced
- `pyproject.toml` - Potentially remove `anthropic` from dependencies if Task 92 is also done

### Benefits
- Single LLM configuration path for users
- Any provider works for all features
- Simpler dependency tree (if combined with Task 92)
- Consistent with pflow's philosophy of using `llm` library
- Users can optimize cost/speed by choosing appropriate models
- **Fixes model validation bug** - invalid models properly rejected
- **Fixes model selection bug** - user's model choice is respected
- **Consistent behavior** between `registry run` and workflow execution

## Test Strategy

### Bug Fix Tests (Priority 1)
- Test that `pflow workflow.json` with invalid Claude model name returns proper error
- Test that `pflow workflow.json` with valid Claude model uses the specified model (not hardcoded)
- Test that `pflow registry run llm` and `pflow workflow.json` behave consistently for same model
- Test that natural language planner path still works with Anthropic features

### Unit Tests
- Test discovery commands work with different `llm` models
- Test smart filtering works with different models
- Test fallback behavior when no model is configured
- Test that existing Anthropic key configuration still works
- Test monkey-patch is NOT installed for file/saved workflow execution
- Test monkey-patch IS installed for natural language planner path

### Integration Tests
- End-to-end test of `pflow registry discover` with non-Anthropic model
- End-to-end test of `pflow workflow discover` with non-Anthropic model
- Test structure-only filtering with large responses using configured model
- Test workflow with `model="claude-sonnet-4.5"` actually uses that model

### Configuration Tests
- Test `pflow settings set discovery-model` works
- Test default model behavior
- Test error messages when model/key is not configured

### Regression Tests
- Ensure discovery quality doesn't degrade with different models
- Benchmark discovery speed/cost across providers
- Ensure planner still works correctly after changes

## Implementation Order

1. **Phase 1 - Bug Fix** (can be done immediately):
   - Scope the monkey-patch in `main.py` to only planner path
   - Add tests for consistent behavior between `registry run` and workflows

2. **Phase 2 - Discovery Migration**:
   - Migrate `registry discover` to use `llm` library
   - Migrate `workflow discover` to use `llm` library
   - Add configuration setting for discovery model

3. **Phase 3 - Smart Filtering**:
   - Migrate `smart_filter.py` to use `llm` library
   - Add configuration for filtering model

4. **Phase 4 - Cleanup** (after Task 92):
   - Remove unused Anthropic wrapper code
   - Update dependencies
