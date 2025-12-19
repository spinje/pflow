# Task 95: Implementation Plan

## Executive Summary

This plan addresses the critical bug where ALL Claude models are silently redirected to a hardcoded model (`claude-sonnet-4-20250514`), ignoring user's model choice. The fix involves scoping the monkey-patch to the planner-only path and migrating discovery/filtering features to use the standard `llm` library.

---

## Current State Analysis

### The Bug (Root Cause)

**Location**: `src/pflow/cli/main.py:3550`

```python
def workflow_command(...):
    # ... initialization ...
    _install_anthropic_model_if_needed(verbose)  # Called for ALL workflows

    # Later: workflow type determined here
    if _try_execute_named_workflow(...):  # File/saved workflow
        return
    # ...
    _execute_with_planner(...)  # Natural language only
```

**Problem**: The monkey-patch is installed at line 3550, BEFORE workflow type is determined (line 3577). This means:
- File workflows (`pflow workflow.json`) get the patch
- Saved workflows (`pflow my-workflow`) get the patch
- Natural language (`pflow "do something"`) gets the patch (correct)

### Impact Chain

```
User specifies: model="claude-sonnet-4.5"
    ↓
AnthropicLLMModel stores: self.model_name = "claude-sonnet-4.5" (IGNORED)
    ↓
AnthropicStructuredClient hardcodes: self.model = "claude-sonnet-4-20250514"
    ↓
API call uses: "claude-sonnet-4-20250514" (ALWAYS)
```

### Current LLM Usage Locations

| Location | Uses | Should Use | Notes |
|----------|------|------------|-------|
| `main.py:3550` | Monkey-patch (ALL) | Monkey-patch (planner only) | **BUG FIX** |
| `registry.py:645` | `install_anthropic_model()` | `llm.get_model()` | Discovery |
| `workflow.py:142,264` | `install_anthropic_model()` | `llm.get_model()` | Discovery |
| `smart_filter.py:165` | Hardcoded Haiku | `llm.get_model()` | Filtering |
| `planning/nodes.py` | `llm.get_model()` (patched) | Keep as-is | Planner needs features |

---

## Implementation Plan

### Phase 1: Bug Fix (Critical Priority)

**Goal**: Scope monkey-patch to only the natural language planner path.

**File**: `src/pflow/cli/main.py`

**Current Code** (lines 3549-3591):
```python
def workflow_command(...):
    # ...
    _install_anthropic_model_if_needed(verbose)  # Line 3550 - TOO EARLY

    # ...
    if _try_execute_named_workflow(ctx, workflow, stdin_data, output_key, output_format, verbose):
        return  # File/saved workflow - exits here

    if not _is_valid_natural_language_input(workflow):
        _handle_invalid_planner_input(ctx, workflow)
        return

    # Natural language path - planner invoked here
    _execute_with_planner(ctx, raw_input, ...)
```

**Proposed Fix**:
```python
def workflow_command(...):
    # ... initialization ...
    # REMOVED: _install_anthropic_model_if_needed(verbose)

    # ...
    if _try_execute_named_workflow(ctx, workflow, stdin_data, output_key, output_format, verbose):
        return  # File/saved workflow - NO PATCH

    if not _is_valid_natural_language_input(workflow):
        _handle_invalid_planner_input(ctx, workflow)
        return

    # Natural language path - install patch ONLY HERE
    _install_anthropic_model_if_needed(verbose)

    _execute_with_planner(ctx, raw_input, ...)
```

**Why This Works**:
- File workflows exit at line 3577-3578 before patch is installed
- Saved workflows exit at line 3577-3578 before patch is installed
- Natural language continues past line 3580 and gets the patch
- Planner has the Anthropic SDK features it needs (caching, thinking)

**Tests to Add**:
1. Test that invalid Claude model name returns proper error for file workflows
2. Test that valid Claude model uses specified model (not hardcoded) for file workflows
3. Test that `registry run` and file workflow behave consistently
4. Test that natural language planner still works correctly

---

### Phase 2: Discovery Commands Migration

**Goal**: Replace hardcoded Anthropic with configurable `llm` library usage.

#### 2A: Registry Discover (`src/pflow/cli/registry.py:643-647`)

**Current Code**:
```python
# Install Anthropic monkey patch for LLM calls (required for planning nodes)
if not os.environ.get("PYTEST_CURRENT_TEST"):
    from pflow.planning.utils.anthropic_llm_model import install_anthropic_model
    install_anthropic_model()
```

**Proposed Change**:
The `ComponentBrowsingNode` in `planning/nodes.py` uses `llm.get_model()` internally. Without the monkey-patch, it will use the standard llm library which:
- Works with any provider (Anthropic, Gemini, OpenAI)
- Validates model names properly
- Uses `get_default_llm_model()` for auto-detection

**Action**: Simply remove the monkey-patch installation. The node will use standard llm library.

**But wait**: `ComponentBrowsingNode` uses `schema=` parameter for structured output, which requires special handling. Let me investigate...

After reviewing `planning/nodes.py`, the `ComponentBrowsingNode.exec()` method:
1. Uses `llm.get_model(prep_res["model_name"])` at line ~350
2. Calls `model.prompt(prompt, schema=BrowsedComponents, ...)`

The `schema=` parameter works with the standard llm library via `llm.models.structured()`. We need to verify this works without the monkey-patch.

**Option A (Safe)**: Keep monkey-patch but use configurable model
**Option B (Clean)**: Verify llm library structured output works, remove patch

**Recommendation**: Option B - Test first, then remove.

#### 2B: Workflow Discover (`src/pflow/cli/commands/workflow.py:140-144`)

**Current Code**:
```python
if not os.environ.get("PYTEST_CURRENT_TEST"):
    from pflow.planning.utils.anthropic_llm_model import install_anthropic_model
    install_anthropic_model()
```

**Same approach as 2A**: Remove the monkey-patch installation.

#### 2C: Metadata Generation (`src/pflow/cli/commands/workflow.py:261-266`)

**Current Code**:
```python
if not os.environ.get("PYTEST_CURRENT_TEST"):
    from pflow.planning.utils.anthropic_llm_model import install_anthropic_model
    install_anthropic_model()
```

**Same approach**: Remove the monkey-patch installation.

---

### Phase 3: Smart Filter Migration

**Goal**: Replace hardcoded Anthropic Haiku with configurable model.

**File**: `src/pflow/core/smart_filter.py`

**Current Code** (line 165):
```python
model = llm.get_model("anthropic/claude-haiku-4-5-20251001")
```

**Proposed Change**:
```python
from pflow.core.llm_config import get_default_llm_model

# Use configured model or sensible default for filtering
filtering_model = get_default_llm_model() or "gemini-2.5-flash-lite"
model = llm.get_model(filtering_model)
```

**Alternative**: Add a setting for filtering model specifically:
```python
from pflow.core.settings import SettingsManager

settings = SettingsManager().load()
filtering_model = getattr(settings, 'filtering_model', None) or get_default_llm_model() or "gemini-2.5-flash-lite"
```

**Recommendation**: Use `get_default_llm_model()` as the primary source, with `gemini-2.5-flash-lite` as fallback (cheap, fast, good for filtering).

---

### Phase 4: Configuration (Optional Enhancement)

**Goal**: Allow users to configure models for discovery and filtering.

**Option A: Use Existing Settings Structure**

Add to `src/pflow/core/settings.py`:

```python
class LLMSettings(BaseModel):
    """LLM model configuration."""
    discovery_model: Optional[str] = None  # Auto-detect if None
    filtering_model: Optional[str] = None  # Auto-detect if None

class PflowSettings(BaseModel):
    version: str = Field(default="1.0.0")
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    env: dict[str, str] = Field(default_factory=dict)
    llm: LLMSettings = Field(default_factory=LLMSettings)  # NEW
```

**CLI Commands**:
```bash
pflow settings set llm.discovery_model gemini-2.5-flash
pflow settings set llm.filtering_model gemini-2.5-flash-lite
```

**Option B: Use Environment Variables Only**

```bash
export PFLOW_DISCOVERY_MODEL=gemini-2.5-flash
export PFLOW_FILTERING_MODEL=gemini-2.5-flash-lite
```

**Recommendation**: Option A (settings file) for persistence, with environment variable override support.

---

## Verification Plan

### Before Implementation

Run current tests to establish baseline:
```bash
make test
make check
```

### After Phase 1 (Bug Fix)

**Manual Tests**:
```bash
# Test 1: Invalid model should error (not silently fail)
cat > /tmp/invalid-model.json << 'EOF'
{"ir_version": "0.1.0", "nodes": [{"id": "t", "type": "llm", "params": {"prompt": "Hi", "model": "totally-fake-claude"}}]}
EOF
pflow /tmp/invalid-model.json
# Expected: Error from llm library about unknown model

# Test 2: Valid model should be used (not hardcoded)
cat > /tmp/valid-model.json << 'EOF'
{"ir_version": "0.1.0", "nodes": [{"id": "t", "type": "llm", "params": {"prompt": "Say hi", "model": "claude-sonnet-4.5"}}]}
EOF
pflow /tmp/valid-model.json
# Check trace: should show claude-sonnet-4.5, not claude-sonnet-4-20250514

# Test 3: Consistency between registry run and workflow
pflow registry run llm prompt="Hi" model="claude-sonnet-4.5"
# Should behave same as workflow with same model

# Test 4: Natural language still works
pflow "write a haiku about testing"
# Should succeed using planner with Anthropic features
```

**Automated Tests to Add** (`tests/test_cli/test_llm_model_handling.py`):
```python
def test_file_workflow_invalid_model_returns_error():
    """Invalid Claude model in file workflow should error, not silently fail."""

def test_file_workflow_uses_specified_model():
    """File workflow should use user's specified model, not hardcoded."""

def test_registry_run_file_workflow_consistency():
    """registry run and file workflow should behave identically for same model."""

def test_planner_still_works_after_fix():
    """Natural language input should still invoke planner successfully."""
```

### After Phase 2 (Discovery Migration)

```bash
# Test with non-Anthropic model
export ANTHROPIC_API_KEY=""  # Clear Anthropic key
export GEMINI_API_KEY="your-key"  # Ensure Gemini available

pflow registry discover "I need to read files"
# Should work with Gemini

pflow workflow discover "analyze GitHub issues"
# Should work with Gemini
```

### After Phase 3 (Smart Filter Migration)

```bash
# Test filtering with non-Anthropic model
pflow registry run http url="https://api.github.com/repos/anthropics/claude-code/issues" --output-format json
# Should filter 31+ fields using configured model
```

---

## Risk Assessment

### Low Risk
- Phase 1 bug fix: Clear code movement, well-defined branching point
- Phase 3 smart filter: Simple model string replacement

### Medium Risk
- Phase 2 discovery: Need to verify structured output works without monkey-patch
- Phase 4 configuration: Adds new settings structure

### Mitigations
1. Run full test suite after each phase
2. Manual verification with real API calls
3. Keep changes minimal and focused
4. Add tests for each changed behavior

---

## Files to Modify (Summary)

| Phase | File | Lines | Change |
|-------|------|-------|--------|
| 1 | `src/pflow/cli/main.py` | 3549-3590 | Move monkey-patch to planner path |
| 2 | `src/pflow/cli/registry.py` | 643-647 | Remove monkey-patch |
| 2 | `src/pflow/cli/commands/workflow.py` | 140-144, 261-266 | Remove monkey-patch |
| 3 | `src/pflow/core/smart_filter.py` | 165 | Use `get_default_llm_model()` |
| 4 | `src/pflow/core/settings.py` | New | Add LLMSettings class |
| All | `tests/test_cli/` | New | Add model handling tests |

---

## Implementation Order

1. **Phase 1** - Fix the bug (CRITICAL, do first)
   - Estimated: 30 minutes
   - Risk: Low

2. **Phase 3** - Smart filter migration (simple)
   - Estimated: 15 minutes
   - Risk: Low

3. **Phase 2** - Discovery commands (needs verification)
   - Estimated: 1 hour (includes testing structured output)
   - Risk: Medium

4. **Phase 4** - Configuration (optional, deferred)
   - Estimated: 45 minutes
   - Risk: Medium

---

## Questions for User Decision

### Decision 1: Discovery Node Structured Output (Importance: 3/5)

The discovery commands use planning nodes (`ComponentBrowsingNode`, `WorkflowDiscoveryNode`) that rely on structured output via `schema=` parameter.

**Context**: These nodes call `model.prompt(..., schema=SomeModel)`. With the monkey-patch, this goes to `AnthropicLLMModel`. Without it, it goes to standard `llm` library.

**Options**:

- [ ] **Option A: Test and verify** - Verify that standard `llm` library handles `schema=` correctly for non-Anthropic models, then remove monkey-patch
  - Pro: Cleaner code, provider-agnostic
  - Con: Need to test thoroughly

- [x] **Option B: Keep monkey-patch for discovery only** - Keep the patch but document it's for structured output
  - Pro: Known working, less risk
  - Con: Still requires Anthropic key for discovery

**Recommendation**: Option A - The llm library supports structured output via plugins. Let's verify and use the cleaner approach.

### Decision 2: Smart Filter Default Model (Importance: 2/5)

When user has no model configured, what should smart filter use?

**Options**:

- [x] **Option A: Use `get_default_llm_model()` with fallback to `gemini-2.5-flash-lite`**
  - Pro: Respects user's API key setup
  - Con: May use expensive model for simple filtering

- [ ] **Option B: Always use cheapest available model**
  - Pro: Cost-optimized for simple task
  - Con: May not have that provider configured

**Recommendation**: Option A - Respect user's configuration, with cheap fallback.

### Decision 3: Configuration System (Importance: 2/5)

Should we add configuration for discovery/filtering models?

**Options**:

- [ ] **Option A: Implement settings now**
  - Pro: User control, complete solution
  - Con: More code to add/test

- [x] **Option B: Defer to later task**
  - Pro: Faster delivery of bug fix
  - Con: Users can't customize yet

**Recommendation**: Option B - Focus on bug fix first, add configuration in follow-up task.

---

## Expected Output (Before/After)

### Before (Current Buggy Behavior)

```bash
$ pflow /tmp/workflow.json  # with model="claude-sonnet-4.5"
# Trace shows: model="claude-sonnet-4-20250514" (WRONG - hardcoded)

$ pflow registry run llm prompt="Hi" model="claude-sonnet-4.5"
# Error: Unknown model 'claude-sonnet-4.5' (WRONG - inconsistent)
```

### After (Fixed Behavior)

```bash
$ pflow /tmp/workflow.json  # with model="claude-sonnet-4.5"
# Trace shows: model="claude-sonnet-4.5" (CORRECT - user's choice)

$ pflow registry run llm prompt="Hi" model="claude-sonnet-4.5"
# Success with claude-sonnet-4.5 (CORRECT - consistent)

$ pflow "write a haiku"
# Success using planner with Anthropic features (CORRECT - still works)
```

---

## Ready for Review

Please review this plan and let me know:
1. Any concerns about the approach
2. Your decisions on the three questions above
3. Whether to proceed with implementation

I've pre-selected the recommended options with [x], but please feel free to change these.
