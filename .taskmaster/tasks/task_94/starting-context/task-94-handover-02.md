# Task 94 Handoff Memo: Display Available LLM Models Based on Configured API Keys

## TL;DR - The Core Insight

**I just built the detection layer. Task 94 is the display layer.**

- **What I implemented**: Detect which providers have keys configured (for error message suggestions)
- **What Task 94 needs**: Display available models BEFORE execution (in `registry describe`/`discover`)
- **Key realization**: The detection functions I built (`_has_provider_key()`) are exactly what Task 94 needs

---

## Critical Foundation: We Just Built What You Need

I just implemented multi-source provider detection in `src/pflow/core/llm_config.py`. The key function you need already exists:

```python
def _has_provider_key(provider: str) -> bool:
    """Check if an LLM provider key is configured from ANY source.

    Checks in order (stops at first found):
    1. Environment variables (os.environ)
    2. pflow settings (settings.json env section)
    3. llm CLI keys (llm keys get)
    """
```

**Location**: `src/pflow/core/llm_config.py:102-147`

This is exactly what Task 94 needs to check which providers are available.

---

## User's Explicit Philosophy (Don't Over-Engineer)

The user was very clear about scope:

> "we only need to suggest if api key is set for 'anthropic', 'gemini', 'openai' or if pflow default mode or llm default model is set, but everything else should work"

Translation:
- **Model suggestions**: Only for the big 3 (Anthropic, Gemini, OpenAI)
- **Other providers** (openrouter, replicate, groq): Keys get injected and work, but no automatic model suggestions
- **Don't add more providers** to the detection list - the user pushed back when I suggested it

---

## Key Constants and Functions You'll Reuse

### 1. Provider to Env Var Mapping
```python
# src/pflow/core/llm_config.py:28-34
PROVIDER_ENV_VARS: dict[str, list[str]] = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],  # Note: Gemini accepts both
    "openai": ["OPENAI_API_KEY"],
}
```

### 2. Provider to Model Mapping
Already exists in `_detect_default_model()`:
- `anthropic` → `"anthropic/claude-sonnet-4-5"`
- `gemini` → `"gemini/gemini-3-flash-preview"`
- `openai` → `"gpt-5.2"`

### 3. Other Resolution Functions
- `get_default_workflow_model()` - checks pflow settings, llm CLI default, then auto-detect
- `get_llm_cli_default_model()` - runs `llm models default` to get user's preferred model

---

## Integration Points for Task 94

### Where to Show Available Models

1. **`pflow registry describe llm`**
   - File: `src/pflow/cli/registry.py`
   - Look at the `describe` command and how it displays node info
   - The LLM node metadata comes from `build_planning_context()` in `src/pflow/planning/context_builder.py`

2. **`pflow registry discover "..."`**
   - Same registry.py file
   - Uses `ComponentBrowsingNode` which also uses context_builder

### Suggested Approach
The cleanest place to inject available model info is probably in the context builder or when formatting the LLM node's parameter description. Check:
- `src/pflow/planning/context_builder.py` - `build_planning_context()`
- `src/pflow/registry/metadata_extractor.py` - where node metadata is extracted

---

## Testing Gotchas (Will Save You Hours)

### 1. `PYTEST_CURRENT_TEST` Blocks Detection
Both `_detect_default_model()` and `inject_settings_env_vars()` return early when `PYTEST_CURRENT_TEST` is set:

```python
if os.environ.get("PYTEST_CURRENT_TEST"):
    return None  # or return early
```

**Fix in tests**: Use `monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)`

### 2. The Developer's llm CLI Has Keys
The dev environment has an Anthropic key stored in `llm keys`. When testing other providers, you need to mock `_has_llm_key()`:

```python
import pflow.core.llm_config as llm_config
llm_config._has_llm_key = lambda provider: False  # Mock out llm CLI
```

### 3. Cache Must Be Cleared
`get_default_llm_model()` caches results. In tests, call:
```python
from pflow.core.llm_config import clear_model_cache
clear_model_cache()
```

### 4. Quality Over Quantity
User explicitly said: "make sure to only write tests that actually matter, no boilerplate. quality over quantity."

---

## Files You'll Need to Read

| File | Why |
|------|-----|
| `src/pflow/core/llm_config.py` | All detection functions live here |
| `src/pflow/cli/registry.py` | The `describe` and `discover` commands |
| `src/pflow/planning/context_builder.py` | Builds context for LLM node descriptions |
| `src/pflow/registry/metadata_extractor.py` | Extracts node interface metadata |
| `tests/test_core/test_llm_config_provider_detection.py` | Example tests I just wrote |

---

## What NOT to Do

1. **Don't try to enumerate all llm plugin models** - just show provider availability
2. **Don't add more providers** to `PROVIDER_ENV_VARS` - user explicitly didn't want this
3. **Don't cache model availability in registry metadata** - should be display-time check (keys can change)
4. **Don't call `_has_llm_key()` directly** - use `_has_provider_key()` which checks all sources

---

## Suggested Output Format

Based on the task spec and user's minimal approach:

**If keys configured:**
```
- Params: model: str  # Available: anthropic/claude-sonnet-4-5, gpt-5.2 (providers: anthropic, openai)
```

**If no keys:**
```
- Params: model: str  # No API keys configured. Run: pflow settings set-env ANTHROPIC_API_KEY "..."
```

---

## Questions to Clarify with User

1. Should `registry describe llm` show ALL available models from each provider, or just a representative one?
2. Should we show the provider name or specific model names?
3. Where exactly should this info appear - in the params description or as a separate section?

---

## ⚠️ CRITICAL: Injection Does NOT Happen for Registry Commands

**The injection I implemented only runs in `workflow_command()`.** Registry commands (`pflow registry describe`, `pflow registry discover`) are in a separate Click group and do NOT call `inject_settings_env_vars()`.

This means:
- For `pflow "do something"` → Injection happens ✅
- For `pflow registry describe llm` → Injection does NOT happen ❌

**You have two options:**

1. **Add injection to registry commands** (recommended):
   ```python
   # In src/pflow/cli/registry.py, at the start of describe/discover commands:
   from pflow.core.llm_config import inject_settings_env_vars
   inject_settings_env_vars()
   ```

2. **Or rely on `_has_provider_key()` checking settings directly**:
   - `_has_provider_key()` checks settings via `SettingsManager.get_env()` directly
   - It doesn't rely on os.environ for settings keys
   - So it will find settings keys even without injection
   - BUT: If you want llm library calls to work with settings keys, you need injection

The injection location for workflow_command is: `src/pflow/cli/main.py:3559-3561`

---

## Existing Help Text Functions (Reuse These!)

Don't write new help text - these already exist:

```python
# src/pflow/core/llm_config.py:218-235
def get_llm_setup_help() -> str:
    """Get helpful error message for LLM setup."""
    # Returns multi-line setup instructions for all providers

# src/pflow/core/llm_config.py:336-367
def get_model_not_configured_help(node_id: str) -> str:
    """Get helpful error message when no model is configured."""
    # Returns detailed setup instructions with examples
```

---

## All Functions in llm_config.py You Might Use

| Function | Purpose | Returns |
|----------|---------|---------|
| `_has_provider_key(provider)` | Check if provider has key from any source | `bool` |
| `_has_llm_key(provider)` | Check llm CLI only (don't use directly) | `bool` |
| `get_default_llm_model()` | Get best available model (cached) | `Optional[str]` |
| `get_default_workflow_model()` | 4-tier resolution for workflow nodes | `Optional[str]` |
| `get_llm_cli_default_model()` | Get user's `llm models default` | `Optional[str]` |
| `get_llm_setup_help()` | Help text for no keys | `str` |
| `get_model_not_configured_help(node_id)` | Detailed help with examples | `str` |
| `clear_model_cache()` | Reset detection cache (for tests) | `None` |

---

## The ALLOWED_PROVIDERS Constant

```python
# src/pflow/core/llm_config.py:26
ALLOWED_PROVIDERS = frozenset({"anthropic", "gemini", "openai"})
```

This is the authoritative list. Task 94 should only show availability for these three.

---

## Settings File Structure

Location: `~/.pflow/settings.json`

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-...",
    "OPENAI_API_KEY": "sk-...",
    "SOME_OTHER_KEY": "..."
  },
  "llm": {
    "default_model": "gemini-3-flash-preview"
  }
}
```

Access via:
```python
from pflow.core.settings import SettingsManager
manager = SettingsManager()
manager.get_env("ANTHROPIC_API_KEY")  # Returns value or None
manager.list_env(mask_values=False)   # Returns dict of all env vars
settings = manager.load()
settings.llm.default_model            # User's configured default
```

---

## The llm Library is Installed

The `llm` CLI is installed in the venv and works:
```bash
uv run llm models          # List available models
uv run llm models default  # Show user's default model
uv run llm keys            # List configured keys
```

This is how `_has_llm_key()` works - it runs `llm keys get <provider>`.

---

## Manual Verification Commands

Use these to test your implementation:

```bash
# Set a test key in settings
uv run pflow settings set-env OPENAI_API_KEY "test-key"

# Check detection works
uv run python -c "
from pflow.core.llm_config import _has_provider_key, clear_model_cache
clear_model_cache()
print('anthropic:', _has_provider_key('anthropic'))
print('openai:', _has_provider_key('openai'))
print('gemini:', _has_provider_key('gemini'))
"

# Clean up
uv run pflow settings unset-env OPENAI_API_KEY

# Test registry describe (after your changes)
uv run pflow registry describe llm
```

---

## Reference Documents

- **Implementation spec I worked from**: `scratchpads/robust-provider-detection/implementation-spec.md`
- **Implementation plan**: `scratchpads/robust-provider-detection/implementation-plan.md`
- **Core module docs**: `src/pflow/core/CLAUDE.md`
- **CLI module docs**: `src/pflow/cli/CLAUDE.md`

---

## Files Modified in This Work (Uncommitted)

```
src/pflow/core/llm_config.py                           # +70 lines (detection logic)
src/pflow/cli/main.py                                  # +15 lines (injection call)
src/pflow/mcp_server/main.py                           # +8 lines (injection call)
tests/test_core/test_llm_config_provider_detection.py  # NEW FILE (13 tests)
```

---

## Architectural Pattern: Detection vs Display

```
                    ┌─────────────────────────────────────────┐
                    │         What I Implemented              │
                    │         (Detection Layer)               │
                    ├─────────────────────────────────────────┤
                    │  _has_provider_key("anthropic")         │
                    │           ↓                             │
                    │  1. Check os.environ                    │
                    │  2. Check settings.json                 │
                    │  3. Check llm CLI                       │
                    │           ↓                             │
                    │  Returns: True/False                    │
                    └─────────────────────────────────────────┘
                                      │
                                      ▼
                    ┌─────────────────────────────────────────┐
                    │         What Task 94 Implements         │
                    │          (Display Layer)                │
                    ├─────────────────────────────────────────┤
                    │  For each provider in ALLOWED_PROVIDERS:│
                    │    if _has_provider_key(provider):      │
                    │      add to available_models list       │
                    │                                         │
                    │  Format and display in:                 │
                    │  - registry describe llm                │
                    │  - registry discover output             │
                    └─────────────────────────────────────────┘
```

---

## Remember

**Do NOT begin implementing yet.** Read this memo, read the task spec at `.taskmaster/tasks/task_94/task-94.md`, familiarize yourself with the codebase locations mentioned above, and confirm you're ready to begin.
