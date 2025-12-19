# Task 95 Review: Unify LLM Usage via Simon Willison's llm Library

## Metadata
- **Implementation Date**: 2025-12-19
- **Branch**: `feat/llm-usage`
- **Pull Request**: https://github.com/spinje/pflow/pull/2
- **Commits**: `044f412` (main implementation), `f995279` (PR review fixes)

## Executive Summary

Fixed a critical bug where ALL Claude models were silently redirected to a hardcoded model (`claude-sonnet-4-20250514`), ignoring user's model choice. Migrated discovery commands and smart filtering to use configurable models via Simon Willison's `llm` library. Added settings-based model configuration with a clear resolution chain.

## Implementation Overview

### What Was Built

1. **Bug Fix (Phase 1)**: Moved the Anthropic monkey-patch from workflow entry point to planner-only path
2. **Discovery Migration (Phase 2)**: Replaced `install_anthropic_model()` with `get_model_for_feature("discovery")` in registry/workflow discover commands
3. **Smart Filter Migration (Phase 3)**: Replaced hardcoded Haiku model with configurable model
4. **Settings Configuration (Phase 4)**: Added `LLMSettings` with `default_model`, `discovery_model`, `filtering_model`
5. **Compiler Model Injection**: LLM nodes now require explicit model configuration with helpful error messages

### Deviation from Original Spec

- **Combined Phase 3+4**: Implemented settings alongside smart filter migration for cleaner single-pass implementation
- **Added compiler-time model injection**: Not in original spec but necessary for "fail early with helpful message" UX
- **PR review fixes**: Removed CI debug prints, moved imports to top-level (not in original implementation)

### Implementation Approach

The key insight was understanding **two distinct execution paths**:
1. **File/Saved workflows**: Should use standard `llm` library (user's model choice)
2. **Natural language planner**: Needs Anthropic SDK features (caching, thinking tokens)

The bug occurred because the monkey-patch was installed for ALL workflows, not just the planner path.

## Files Modified/Created

### Core Changes

| File | Change | Impact |
|------|--------|--------|
| `src/pflow/cli/main.py:3550→3587` | Moved `_install_anthropic_model_if_needed()` to after file/saved workflow branch | **Critical bug fix** - user model now respected |
| `src/pflow/core/llm_config.py` | Added `get_model_for_feature()`, `get_default_workflow_model()`, `get_llm_cli_default_model()`, `get_model_not_configured_help()` | Central model resolution functions |
| `src/pflow/core/settings.py` | Added `LLMSettings` class with 3 model fields | Persistent configuration |
| `src/pflow/runtime/compiler.py:604-629` | Inject default model for LLM nodes at compile time | Fail-early with helpful errors |
| `src/pflow/cli/registry.py:639-651` | Use `get_model_for_feature("discovery")` | Discovery works with any provider |
| `src/pflow/cli/commands/workflow.py:130-155,253-270` | Use `get_model_for_feature("discovery")` | Discover/metadata generation configurable |
| `src/pflow/core/smart_filter.py:164-167` | Use `get_model_for_feature("filtering")` | Smart filter uses configured model |
| `src/pflow/core/workflow_save_service.py:300-332` | Accept optional `model_name` parameter | Pass model to metadata generation |
| `src/pflow/core/llm_pricing.py` | Added GPT-5.2, Gemini 3 Flash pricing | Cost tracking for new models |
| `src/pflow/cli/commands/settings.py` | Added `llm` subgroup with show/set-*/unset commands | CLI management for LLM settings |

### Test Files

| File | Purpose | Critical? |
|------|---------|-----------|
| `tests/test_core/test_llm_config_workflow_model.py` | Tests resolution chain (settings → llm CLI → None) | **Yes** - validates fallback logic |
| `tests/test_runtime/test_compiler_llm_model.py` | Tests compiler model injection and error messages | **Yes** - validates fail-early behavior |
| `tests/shared/llm_mock.py` | Added wildcard model support (`"*"`) | Utility - enables flexible test mocking |

## Integration Points & Dependencies

### Incoming Dependencies

```
compiler._create_single_node() → get_default_workflow_model()
registry.discover_nodes() → get_model_for_feature("discovery")
workflow.discover_workflows() → get_model_for_feature("discovery")
workflow._generate_metadata_if_requested() → get_model_for_feature("discovery")
smart_filter.filter_fields_with_llm() → get_model_for_feature("filtering")
```

### Outgoing Dependencies

```
llm_config → SettingsManager (for model configuration)
llm_config → subprocess (for llm CLI default detection)
compiler → llm_config (for model resolution)
```

### Shared Store Keys

- `shared["model_name"]` - Used by planning nodes to select LLM model (any provider)

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative Considered |
|----------|-----------|----------------------|
| Scope monkey-patch to planner only | Planner needs Anthropic SDK features (caching, thinking); regular workflows don't | Remove monkey-patch entirely (would break planner) |
| Require explicit model configuration | Fail-early with helpful message > silent runtime failure | Auto-detect and use (confusing if user has multiple keys) |
| Settings → llm CLI → error resolution | Respects user's explicit choice, falls back to llm ecosystem | Auto-detect from API keys (too magical) |
| Top-level imports in compiler/llm_config | Avoids repeated import overhead; no circular import exists | Keep inline imports (review feedback said change) |
| Unified `default_model` fallback | Name implies shared behavior; simpler UX (set once, applies everywhere) | Separate settings per feature (more configuration burden) |

### Technical Debt Incurred

1. **Monkey-patch still exists for planner**: The `AnthropicLLMModel` wrapper is still needed for planner's caching/thinking features. Will be removed when Task 92 replaces planner with Agent Node.

2. **Global state caching in llm_config**: `_cached_default_model` uses module-level state. Works for single-threaded CLI but not thread-safe. Acceptable for MVP.

## Testing Implementation

### Test Strategy Applied

- **Unit tests for resolution chain**: Each step of settings → llm CLI → None tested independently
- **Compiler integration tests**: Verify model injection happens at compile time
- **Mocking strategy**: Patch at point of use (`pflow.runtime.compiler.get_default_workflow_model`) not definition

### Critical Test Cases

| Test | What It Validates |
|------|-------------------|
| `test_returns_settings_default_model` | Settings takes priority over everything |
| `test_falls_back_to_llm_cli_default` | llm CLI default works when settings empty |
| `test_fails_when_no_model_configured` | Error raised with helpful message |
| `test_does_not_mutate_original_ir` | IR immutability preserved |

## Unexpected Discoveries

### Gotchas Encountered

1. **"Circular import" was false**: The comment `# Import here to avoid circular imports` in original code was WRONG. `settings.py` does NOT import from `llm_config.py`. Verified and moved to top-level.

2. **CI debug prints were production code**: The `[DEBUG CI]` print statements were left in from debugging CI subprocess hangs. Should have been removed earlier.

3. **Patch location matters**: When imports move to top-level, test patches must use `pflow.runtime.compiler.get_default_workflow_model` not `pflow.core.llm_config.get_default_workflow_model`.

### Edge Cases Found

- Empty `llm models default` output (no default set) vs command failure
- Settings file doesn't exist vs exists but `llm.default_model` is None
- `PYTEST_CURRENT_TEST` environment variable must skip subprocess calls

## Patterns Established

### Reusable Patterns

**Model Resolution Chain** (unified for ALL LLM usage):
```python
# For workflow LLM nodes (get_default_workflow_model):
# 1. settings.llm.default_model
# 2. llm CLI default (llm models default)
# 3. Auto-detect from API keys
# 4. None → CompilationError with helpful message

# For discovery/filtering (get_model_for_feature):
# 1. Feature-specific setting (discovery_model, filtering_model)
# 2. Shared default_model
# 3. Auto-detect from API keys
# 4. Hardcoded fallback (anthropic/claude-sonnet-4-5)
```

**Key insight**: Both paths now include auto-detect, so users just need an API key configured.

**Helpful Error Messages**:
```python
raise CompilationError(
    message=f"No model configured for LLM node '{node_id}'",
    phase="node_instantiation",
    node_id=node_id,
    suggestion=get_model_not_configured_help(node_id),  # Multi-line setup instructions
)
```

### Anti-Patterns to Avoid

1. **Don't install monkey-patch at workflow entry**: Must be scoped to specific execution paths
2. **Don't assume circular imports**: Verify before adding inline imports
3. **Don't leave debug prints**: Use `logger.debug()` instead of conditional print statements

## Breaking Changes

### Behavioral Changes

| Before | After |
|--------|-------|
| Invalid Claude model names silently "worked" | Now properly error with llm library validation |
| `registry run` and file workflows behaved differently | Now consistent behavior |
| Discovery auto-detected, workflows didn't | All LLM usage now auto-detects from API keys |

### Error Message (only shown when no API keys configured)

```
No model specified for LLM node 'my-llm' and no default could be detected.

pflow tried to auto-detect a model but no API keys were found.

Configure using one of these methods:
  1. Set an API key (pflow will auto-detect the model):
     pflow settings set-env OPENAI_API_KEY "sk-..."
  2. Specify model in workflow (per-node)
  3. Set pflow default: pflow settings llm set-default gpt-5.2
  4. Set llm library default: llm models default gpt-5.2
```

## Future Considerations

### Extension Points

- **Task 92**: When planner is replaced with Agent Node + MCP tools, the monkey-patch can be removed entirely
- **Task 94**: Model listing based on configured API keys will use `get_default_llm_model()` detection logic

### Scalability Concerns

- Global model cache is not thread-safe (acceptable for CLI, would need locking for server mode)
- Subprocess calls for `llm keys get` could be slow if called frequently (mitigated by caching)

## AI Agent Guidance

### Quick Start for Related Tasks

1. **Read first**: `src/pflow/core/llm_config.py` - contains all model resolution logic
2. **Understand the two paths**: File/saved workflows vs natural language planner
3. **Test pattern**: Patch at point of use, not point of definition

### Common Pitfalls

1. **Don't move monkey-patch earlier in main.py** - will restore the original bug
2. **Don't add inline imports "to avoid circular imports"** - verify first, probably not needed
3. **When mocking**: Use `pflow.runtime.compiler.get_default_workflow_model` not `pflow.core.llm_config.get_default_workflow_model`

### Test-First Recommendations

When modifying model resolution:
1. Run `pytest tests/test_core/test_llm_config_workflow_model.py -v`
2. Run `pytest tests/test_runtime/test_compiler_llm_model.py -v`
3. Manual test: Create workflow without model, verify helpful error appears

---

*Generated from implementation context of Task 95*
