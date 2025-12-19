# LLM Usage Research Findings - Complete Documentation

## Executive Summary

The pflow codebase uses LLMs through **two distinct approaches**:

1. **Simon Willison's `llm` library** - Used by user workflows via the LLM node
2. **Direct Anthropic SDK** - Used by planner and discovery features via monkey-patching

**Critical Bug Discovered**: The global monkey-patch at `main.py:3550` intercepts ALL workflow executions (not just planner), causing inconsistent model handling and validation failures.

---

## 1. All Usages of `install_anthropic_model()`

### What It Does
Located at `src/pflow/planning/utils/anthropic_llm_model.py:272-299`

Monkey-patches `llm.get_model()` globally to:
- Intercept ALL Anthropic model requests (any model with "claude" or "anthropic/" in the name)
- Return `AnthropicLLMModel` wrapper instead of the original `llm` library's model
- Provides: prompt caching, thinking tokens, structured output via Anthropic SDK

### Where It's Called

#### A. Main CLI Entry Point (PROBLEMATIC)
**File**: `src/pflow/cli/main.py:3285-3295, 3550`

```python
def _install_anthropic_model_if_needed(verbose: bool) -> None:
    """Install Anthropic model wrapper for planning models unless in tests."""
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        from pflow.planning.utils.anthropic_llm_model import install_anthropic_model
        install_anthropic_model()

# Called at line 3550 for ALL workflow executions
_install_anthropic_model_if_needed(verbose)
```

**Problem**: This is called for ALL workflows (file, saved, natural language), not just when the planner is used.

**Impact**:
- User workflows with Claude models use the monkey-patched version
- `pflow registry run llm` does NOT use the monkey-patch (inconsistent behavior)
- Invalid model names silently "work" because user's model is ignored
- User can't actually choose which Claude model variant to use

#### B. Discovery Commands
**Files**:
- `src/pflow/cli/registry.py:645-647` - `registry discover` command
- `src/pflow/cli/commands/workflow.py:142-144` - `workflow discover` command
- `src/pflow/cli/commands/workflow.py:264-266` - Another discover path

```python
# Pattern used in all discovery commands
if not os.environ.get("PYTEST_CURRENT_TEST"):
    from pflow.planning.utils.anthropic_llm_model import install_anthropic_model
    install_anthropic_model()
```

**Why**: Discovery commands use planning nodes (WorkflowDiscoveryNode, ComponentBrowsingNode) which require Anthropic SDK features (caching, thinking).

#### C. MCP Server
**File**: `src/pflow/mcp_server/main.py:41-43`

```python
# Called during server startup
from pflow.planning.utils.anthropic_llm_model import install_anthropic_model
install_anthropic_model()
```

**Why**: MCP server exposes discovery tools that use planning nodes.

#### D. Test Suite (Conditional)
**Files**: Multiple test files in `tests/test_planning/llm/`

Only called when `RUN_LLM_TESTS=1` environment variable is set:
- `tests/test_planning/llm/integration/test_production_planner_flow.py:27-29`
- `tests/test_planning/llm/integration/test_path_b_generation_north_star.py:28-30`
- `tests/test_planning/llm/integration/test_path_a_metadata_discovery.py:30-32`
- `tests/test_planning/llm/prompts/test_workflow_generator_context_prompt.py:38-40`

**Why**: These tests verify the actual Anthropic SDK integration with real API calls.

### Summary Table

| Location | Purpose | When Called | Skips Tests? |
|----------|---------|-------------|--------------|
| `main.py:3550` | **ALL workflows** | Every workflow execution | Yes |
| `registry.py:645` | Node discovery | `registry discover` command | Yes |
| `workflow.py:142` | Workflow discovery | `workflow discover` command | Yes |
| `workflow.py:264` | Workflow discovery | Another discover path | Yes |
| `mcp_server/main.py:41` | MCP server | Server startup | Yes |
| Test files | LLM integration tests | Only when `RUN_LLM_TESTS=1` | N/A |

**Idempotency**: The monkey-patch checks if already installed (stores original function), so multiple calls are safe but unnecessary.

---

## 2. All Direct Uses of Anthropic SDK

### A. Anthropic SDK Import Locations

**Production Code** (1 file):
- `src/pflow/planning/utils/anthropic_structured_client.py:37`
  ```python
  from anthropic import Anthropic
  ```
  Used by `AnthropicStructuredClient` for structured output with caching.

**PocketFlow Examples** (Not part of pflow production):
- `pocketflow/docs/utility_function/llm.md:33` - Documentation example
- `pocketflow/cookbook/pocketflow-thinking/utils.py:1` - Example code
- `pocketflow/cookbook/pocketflow-batch/utils.py:1` - Example code
- `pocketflow/cookbook/pocketflow-majority-vote/utils.py:1` - Example code
- `pocketflow/cookbook/pocketflow-parallel-batch/utils.py:3` - Example code (AsyncAnthropic)

**Task Documentation**:
- Various `.taskmaster/tasks/` files referencing Anthropic in examples

### B. AnthropicStructuredClient Usage

**File**: `src/pflow/planning/utils/anthropic_structured_client.py`

**Purpose**: Wrapper around Anthropic SDK providing:
- Structured output via tool calling
- Prompt caching (90% cost reduction on retries)
- Thinking tokens for better reasoning
- Consistent error handling

**Used By**: `AnthropicLLMModel` (the monkey-patch wrapper)

**Key Methods**:
- `generate_with_schema_text_mode()` - Main generation method
- Handles both text and structured output
- Manages cache blocks and thinking budget
- Returns (result, usage) tuple

**API Key Fallback Chain**:
1. Constructor parameter
2. `ANTHROPIC_API_KEY` environment variable
3. `llm.get_key("", "anthropic", "ANTHROPIC_API_KEY")` - Uses llm library's key storage

---

## 3. LLM Node Usage (`src/pflow/nodes/llm/llm.py`)

### How It Uses the `llm` Library

**Direct Usage** at line 151:
```python
model = llm.get_model(prep_res["model"])
```

**Default Model**: `gemini-2.5-flash-lite` (configurable via `model` parameter)

**What It Does**:
1. Gets model via `llm.get_model()` - **Intercepted by monkey-patch if Anthropic model**
2. Calls `model.prompt()` with text/images
3. Parses JSON responses automatically
4. Tracks token usage

### Why Monkey-Patch Approach Was Chosen

From `src/pflow/planning/utils/anthropic_llm_model.py:1-5`:
```python
"""Anthropic SDK wrapper that implements the llm library Model interface.

This allows us to use Anthropic SDK features (caching, thinking) while maintaining
compatibility with the existing llm.get_model() pattern used throughout the codebase.
"""
```

**Reason**: Planning pipeline needs:
- Prompt caching (reduces cost by 90% on retries)
- Thinking tokens (improves reasoning quality)
- Structured output (ensures valid JSON)

The `llm` library didn't support these features at the time (and may still not support caching/thinking).

**Trade-off**: Consistency across codebase vs. advanced Anthropic features for planner.

---

## 4. Smart Filter LLM Usage (`src/pflow/core/smart_filter.py`)

### What It Does

**Purpose**: Reduces large API response fields (200+ fields) to 8-15 business-relevant fields using LLM intelligence.

**Trigger**: When field count exceeds `SMART_FILTER_THRESHOLD = 30`

**Model Used**: Hardcoded at line 165:
```python
model = llm.get_model("anthropic/claude-haiku-4-5-20251001")
```

**Caching**: Uses `@lru_cache(maxsize=100)` for filtering decisions (not prompt caching)

### Why It Matters

**Context**: Used by `registry run` with structure-only mode:
```bash
pflow registry run http url=... --read-fields="result[0]"
```

When result has 200+ fields, smart filter reduces to ~12 relevant fields using Haiku.

**Cost**: ~$0.003 per cache miss, instant on cache hit (66% cost reduction with caching)

### Current Issues

1. **Hardcoded to Anthropic**: Users must have Anthropic API key even if they use other providers
2. **No model choice**: Can't use cheaper alternatives (Gemini Flash)
3. **Inconsistent with rest of pflow**: Most features use `llm` library flexibly

---

## 5. Discovery Commands LLM Usage

### A. Registry Discover (`pflow registry discover`)

**File**: `src/pflow/cli/registry.py:643-692`

**Flow**:
1. Installs `install_anthropic_model()` monkey-patch
2. Creates `ComponentBrowsingNode` instance
3. Runs node with shared store context:
   ```python
   shared = {
       "user_input": query,
       "workflow_manager": WorkflowManager(),
       "current_date": datetime.now().strftime("%Y-%m-%d"),
       "cache_planner": False
   }
   ```
4. Displays `shared["planning_context"]` (markdown formatted node list)

**Model**: Uses whatever `ComponentBrowsingNode` is configured for (typically Claude Sonnet 4)

**Why Anthropic**: Node uses structured output and caching features

### B. Workflow Discover (`pflow workflow discover`)

**File**: `src/pflow/cli/commands/workflow.py:234-376`

**Flow**:
1. Installs `install_anthropic_model()` monkey-patch
2. Creates `WorkflowDiscoveryNode` instance
3. Runs node with user query
4. Displays discovery results (metadata, flow, inputs, outputs, confidence)

**Model**: Uses whatever `WorkflowDiscoveryNode` is configured for

**Output**: Formatted with helper functions:
- `_display_workflow_metadata()` - Metadata section
- `_display_workflow_flow()` - Node flow visualization
- `_display_workflow_inputs_outputs()` - I/O specs

---

## 6. Planning Nodes LLM Usage (`src/pflow/planning/nodes.py`)

### Overview

The planning pipeline has **11 nodes**, each making LLM calls via `llm.get_model()`:

1. `WorkflowDiscoveryNode` (line 350)
2. `RequirementsAnalysisNode` (line 646)
3. `ComponentBrowsingNode` (line 887)
4. `ParameterDiscoveryNode` (line 1094)
5. `ParameterMappingNode` (line 1477)
6. `PlanningNode` (line 1815)
7. `WorkflowGeneratorNode` (line 2239)
8. `ValidatorNode` (line 2771)
9. `MetadataGenerationNode` - Not shown in snippet
10. `ParameterPreparationNode` - Not shown in snippet
11. `ResultPreparationNode` - Not shown in snippet

### Pattern Used

**Standard Pattern** (lines 350, 646, 887, etc.):
```python
model = llm.get_model(prep_res["model_name"])
response = model.prompt(
    prompt=prompt,
    schema=SchemaClass,  # For structured output
    temperature=0.0,
    cache_blocks=cache_blocks if cache_planner else None,
    thinking_budget=thinking_budget  # For thinking tokens
)
```

### Why Direct `llm.get_model()` Works

**Answer**: Because `install_anthropic_model()` monkey-patches `llm.get_model()` globally!

When planning nodes call `llm.get_model("anthropic/claude-sonnet-4-0")`:
1. Monkey-patch intercepts the call
2. Returns `AnthropicLLMModel` instance instead of original llm model
3. `AnthropicLLMModel.prompt()` delegates to `AnthropicStructuredClient`
4. Gets Anthropic SDK features (caching, thinking, structured output)

**This is the "clever" part** - planning nodes use standard `llm` library API, but get Anthropic SDK features transparently.

### Cache Block Patterns

**Three different patterns** (intentionally separate, as noted in `CLAUDE.md`):

1. **Standard**: `build_cached_prompt()` - Used by most nodes
2. **Special Context**: Custom `_build_cache_blocks()` - Discovery, Browsing nodes
3. **Planning**: `PlannerContextBuilder` - Planning, Generator nodes

**Why separate?**: Different context needs - don't unify them (documented rule).

---

## 7. Repair Service LLM Usage (`src/pflow/execution/repair_service.py`)

### Single LLM Call

**Location**: Line 94
```python
model = llm.get_model(repair_model)
```

**Purpose**: Validate and repair broken workflows using LLM analysis

**Model Source**: `repair_model` parameter (configurable, defaults to auto-detect)

**Why It Matters**:
- This is used DURING workflow execution (not planning)
- Gets intercepted by monkey-patch if Anthropic model
- Should use standard `llm` library validation (but doesn't due to monkey-patch bug)

**Current Behavior**:
- If user workflow uses repair → monkey-patch is already installed
- Invalid model names may be silently ignored
- User's model choice may be overridden to hardcoded model

---

## 8. Key Findings Summary

### Model Name Handling Bug

**Root Cause**: `AnthropicStructuredClient.__init__()` hardcodes model:
```python
# Line 67 in anthropic_structured_client.py
self.model = "claude-sonnet-4-20250514"  # User's model_name ignored!
```

**Impact**:
1. User specifies `model="claude-opus-4"` in workflow
2. Monkey-patch intercepts, creates `AnthropicLLMModel("claude-opus-4")`
3. `AnthropicLLMModel` creates `AnthropicStructuredClient`
4. Client **ignores** the model name, hardcodes to Sonnet 4
5. User gets wrong model silently

### Validation Inconsistency

**`pflow registry run llm`**:
- Does NOT install monkey-patch
- Uses original `llm` library
- Validates model names strictly
- Returns errors for invalid models

**`pflow workflow.json`**:
- DOES install monkey-patch (line 3550)
- Intercepts Claude models
- Ignores user's model name
- May return empty responses for certain inputs

**Result**: Same model name behaves differently in different contexts.

### Provider Lock-in

**Anthropic Required For**:
1. Natural language planning (understandable - uses advanced features)
2. Discovery commands (could use any provider)
3. Smart filtering (could use any provider)
4. User workflows with Claude models (BUG - should be user's choice)

**User Experience**:
- Must configure Anthropic API key even if they prefer other providers
- Can't use cheaper models for discovery (Gemini Flash costs 40x less than Haiku)
- Documentation says "use any provider" but discovery needs Anthropic

---

## 9. Files Requiring Changes for Task 95

### Priority 1: Bug Fixes (Critical)

**`src/pflow/cli/main.py`**:
- **Lines 3549-3550**: Move `_install_anthropic_model_if_needed()` to planner-only path
- **Current**: Called for ALL workflows
- **Fix**: Only call when entering natural language planning, not for file/saved workflows

### Priority 2: Provider Unification (High)

**`src/pflow/cli/registry.py`**:
- **Lines 645-647**: Remove `install_anthropic_model()` from `discover` command
- **Change**: Use `llm` library directly with configurable model

**`src/pflow/cli/commands/workflow.py`**:
- **Lines 142-144**: Remove `install_anthropic_model()` from first discover path
- **Lines 264-266**: Remove `install_anthropic_model()` from second discover path
- **Change**: Use `llm` library directly

**`src/pflow/core/smart_filter.py`**:
- **Line 165**: Replace hardcoded `llm.get_model("anthropic/claude-haiku-4-5-20251001")`
- **Change**: Use configurable model from settings or default

### Priority 3: Planner Isolation (After Task 92)

**`src/pflow/planning/utils/anthropic_llm_model.py`**:
- May be removed entirely if planner is replaced with agent
- Or scoped to planner-only usage

**`src/pflow/planning/utils/anthropic_structured_client.py`**:
- May be removed entirely
- Or kept for planner but not used by user workflows

### Configuration Changes

**New Settings** (add to `settings.py`):
```python
{
    "llm": {
        "discovery_model": "gemini-2.5-flash",  # Default for discovery
        "filter_model": "gemini-2.5-flash",     # Default for smart filtering
        "repair_model": "auto"                   # Auto-detect from workflow
    }
}
```

---

## 10. Design Recommendations

### Approach A: Minimal Fix (Recommended for Task 95)

**Goal**: Fix the bug, unify provider usage, maintain planner features

**Changes**:
1. Move monkey-patch to planner-only path (fixes validation bug)
2. Make discovery/filter use `llm` library with configurable models
3. Keep `install_anthropic_model()` for planner (until Task 92)
4. Add settings for model configuration

**Benefits**:
- Fixes critical bug immediately
- Allows provider flexibility for discovery/filtering
- Doesn't break planner (still needs Anthropic features)
- Clear migration path to Task 92

### Approach B: Full Anthropic Removal (Wait for Task 92)

**Goal**: Remove all Anthropic SDK usage entirely

**Requires**:
1. Replace planner with agent node + pflow MCP tools (Task 92)
2. Remove `install_anthropic_model()` completely
3. Remove `anthropic_llm_model.py` and `anthropic_structured_client.py`
4. Remove `anthropic` from dependencies

**Benefits**:
- Complete provider flexibility
- Simpler architecture
- One LLM integration path

**Risk**:
- Lose prompt caching (unless `llm` library adds support)
- Lose thinking tokens (unless `llm` library adds support)
- May need to implement structured output differently

### Recommendation

**Do Approach A for Task 95**, then Approach B becomes natural when Task 92 is completed.

---

## 11. Testing Implications

### Bug Fix Tests (Must Add)

```python
def test_workflow_with_invalid_claude_model_raises_error():
    """Invalid Claude model should raise error, not silently fail."""
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "n1", "type": "llm", "params": {"model": "claude-invalid-999"}}]
    }
    # Should raise error, not silently use hardcoded model

def test_workflow_uses_specified_claude_model():
    """User's Claude model choice should be respected."""
    # Verify actual model used matches user's parameter

def test_registry_run_and_workflow_consistent():
    """Same model name should behave identically."""
    # Compare registry run vs workflow execution for same model
```

### Provider Tests (Should Add)

```python
def test_discovery_with_gemini():
    """Discovery should work with non-Anthropic models."""

def test_smart_filter_with_configurable_model():
    """Smart filter should use configured model, not hardcoded Haiku."""
```

### Backward Compatibility Tests

```python
def test_anthropic_still_works_for_planner():
    """Planner should still use Anthropic SDK features."""

def test_existing_workflows_unchanged():
    """Existing user workflows should work without changes."""
```

---

## 12. Migration Path

### Phase 1: Fix the Bug (Task 95.1)
1. Move monkey-patch from `main.py:3550` to planner entry point
2. Test that file/saved workflows use unmodified `llm` library
3. Test that natural language planning still works
4. Deploy with documentation update

### Phase 2: Unify Discovery (Task 95.2)
1. Add model configuration to settings
2. Update discovery commands to use `llm` library
3. Update smart filter to use configured model
4. Test with multiple providers
5. Deploy with migration guide

### Phase 3: Remove Anthropic SDK (Task 92 + Task 95.3)
1. Replace planner with agent approach
2. Remove monkey-patch completely
3. Remove Anthropic SDK files
4. Remove `anthropic` dependency
5. Celebrate unified architecture

---

## Conclusion

The pflow codebase has evolved two parallel LLM integration paths:

1. **User Path**: `llm` library (flexible, provider-agnostic)
2. **Planner Path**: Anthropic SDK (advanced features, provider-locked)

A bug in the implementation causes these paths to bleed together, creating inconsistent behavior. Task 95 should fix this bug and unify the user path, while keeping the planner path separate until Task 92 replaces it entirely.

The research shows that the monkey-patch was a pragmatic solution to get Anthropic features while maintaining `llm` library compatibility, but it was applied too broadly, affecting user workflows when it should only affect the planner.
