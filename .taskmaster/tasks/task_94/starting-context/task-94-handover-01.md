# Task 94 Handover Memo

**From**: Agent completing Task 95 (Unify LLM Usage via Simon Willison's llm Library)
**To**: Agent implementing Task 94 (Display Available LLM Models Based on Configured API Keys)
**Date**: 2025-12-19

---

## Critical Context: Task 95 Changed Everything

**The task description for Task 94 is now outdated.** Task 95 fundamentally changed how LLM models work in pflow. Here's what changed:

### Before Task 95
```
- Params: model: str  # Model to use (default: gemini-2.5-flash)
```

### After Task 95
```
- Params: model: str  # Model to use (REQUIRED - no default, must be configured)
```

**The LLM node no longer has a hardcoded default model.** If no model is specified, the compiler fails with a helpful error message showing three configuration methods.

This means Task 94's approach should shift from "show available models as alternatives to the default" to "show available models so the agent knows what to configure."

---

## Key Detection Infrastructure Already Exists

Task 95 added key detection functions to `src/pflow/core/llm_config.py` that you can reuse or extend:

### `_has_llm_key(provider: str) -> bool` (lines 43-104)
Checks if an API key exists for a provider using `llm keys get <provider>`.

```python
# Already works for: "anthropic", "gemini", "openai"
from pflow.core.llm_config import _has_llm_key
has_anthropic = _has_llm_key("anthropic")  # True/False
```

**Caveats**:
- Uses subprocess with 1-second timeout (prevents hanging)
- Validates provider against `ALLOWED_PROVIDERS` allowlist
- Skips detection in test environment (`PYTEST_CURRENT_TEST`)

### `ALLOWED_PROVIDERS` constant (line 24)
```python
ALLOWED_PROVIDERS = frozenset({"anthropic", "gemini", "openai"})
```

### `get_default_llm_model() -> Optional[str]` (lines 151-181)
Returns the auto-detected model based on API keys, with priority: Anthropic > Gemini > OpenAI.

---

## Two Places to Check for API Keys

**This is important and easy to miss.** There are TWO places where API keys can be stored:

### 1. pflow Settings (`~/.pflow/settings.json`)
```json
{
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-...",
    "OPENAI_API_KEY": "sk-..."
  }
}
```

Access via:
```python
from pflow.core.settings import SettingsManager
manager = SettingsManager()
key = manager.get_env("ANTHROPIC_API_KEY")  # Returns value or None
all_keys = manager.list_env(mask_values=True)  # {"ANTHROPIC_API_KEY": "sk-***", ...}
```

### 2. llm Library Key Storage
Simon Willison's llm library has its own key storage:
```bash
llm keys list        # Shows: anthropic, gemini, openai (provider names only)
llm keys get anthropic  # Returns the actual key (or empty if not set)
```

**The `_has_llm_key()` function checks the llm library's storage, NOT pflow settings.**

For Task 94, you may want to check BOTH sources and merge results.

---

## Useful llm CLI Commands

The `llm` library has CLI commands you can leverage:

```bash
llm keys list          # Lists configured provider names (one per line)
llm keys get <provider> # Gets the key value (empty if not set)
llm models list        # Lists ALL available models (from all installed plugins)
llm models default     # Shows current default model (if set)
llm models default <model>  # Sets default model
```

**Example output of `llm keys list`**:
```
anthropic
gemini
openai
```

**Example output of `llm models list`** (truncated):
```
OpenAI Chat: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo, ...
Anthropic: claude-sonnet-4-5, claude-haiku-4-5, ...
Gemini: gemini-2.0-flash, gemini-2.5-flash-lite, ...
```

---

## Model-to-Provider Mapping

You'll need to map providers to their models. Here's the current mapping in Task 95:

| Provider | API Key Env Var | Example Models |
|----------|-----------------|----------------|
| anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-4-5`, `claude-haiku-4-5`, `anthropic/claude-sonnet-4-5` |
| gemini | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | `gemini-2.5-flash-lite`, `gemini-3-flash-preview` |
| openai | `OPENAI_API_KEY` | `gpt-4o`, `gpt-4o-mini`, `gpt-5.2` |

**Note**: The llm library uses plugin-based model detection. `llm models list` shows all available models from installed plugins.

---

## Files You'll Need to Modify

### Primary Target: `src/pflow/cli/registry.py`

The `describe` command is at lines ~837-870. This is where you'll add the available models display for the LLM node.

### Discovery Context: `src/pflow/planning/nodes.py`

The `ComponentBrowsingNode` builds context that gets shown to agents during discovery. This is where discovery results are formatted.

### Metadata Source: `src/pflow/registry/metadata_extractor.py`

This extracts node metadata from docstrings. The LLM node's interface is defined in `src/pflow/nodes/llm/llm.py`.

### Key Detection: `src/pflow/core/llm_config.py`

Extend or reuse the existing functions here. Consider adding:
- `get_configured_providers() -> list[str]` - Return list of providers with keys
- `get_available_models_for_display() -> str` - Format models for CLI display

---

## The New Settings Structure

Task 95 added `LLMSettings` to `src/pflow/core/settings.py`:

```python
class LLMSettings(BaseModel):
    default_model: Optional[str] = None      # User's default for workflows
    discovery_model: Optional[str] = None    # Model for discovery commands
    filtering_model: Optional[str] = None    # Model for smart filtering
```

This is accessed via:
```python
settings = SettingsManager().load()
default = settings.llm.default_model  # None if not set
```

---

## Display Time vs Cache Time

The task description correctly notes: "This should happen at display time, not stored in registry metadata."

**Why**: API keys can change between runs. The registry is scanned once at startup, but keys might be added/removed during a session.

**How**: Add the key check in the `describe` command's display logic, not in the metadata extractor.

---

## Suggested Approach

1. **Create a helper function** in `llm_config.py`:
   ```python
   def get_available_models_info() -> dict:
       """Get info about available models for display.

       Returns:
           {
               "has_keys": bool,
               "providers": ["anthropic", "gemini"],  # Providers with keys
               "suggested_models": ["claude-sonnet-4-5", "gemini-2.5-flash-lite"],
               "setup_hint": "pflow settings set-env ANTHROPIC_API_KEY ..."
           }
       """
   ```

2. **Modify registry describe** to check for LLM node and enhance display

3. **Consider discovery output** - The planning context builder might need similar enhancement

---

## Edge Cases to Handle

1. **No keys configured**: Show helpful setup instructions
2. **Only one provider**: Show that provider's models
3. **Multiple providers**: Show all available, maybe highlight default
4. **Keys in settings but not llm**: Check both sources
5. **Invalid/expired keys**: Can't detect this without making API calls (out of scope)

---

## Test Considerations

Task 95 added a test utility in `tests/shared/llm_mock.py` with wildcard model support (`"*"`). This allows mocking responses for any model name, which may be useful for your tests.

The existing tests mock at the LLM library level, not at the subprocess level. For testing key detection, you'll need to mock the subprocess calls or the `_has_llm_key()` function.

---

## What I Would Do Differently

If I were implementing Task 94, I would:

1. **Start with `llm_config.py`** - Add a clean helper function that consolidates key detection from both sources
2. **Keep it simple** - Show provider names and 1-2 recommended models per provider, not a full model list
3. **Make it fast** - Cache the result for the duration of the CLI command (not persistent)
4. **Test without subprocess** - Mock `_has_llm_key()` rather than mocking subprocess calls

---

## Questions to Clarify with User

1. Should we check pflow settings.env, llm keys, or both?
2. Should we show specific models or just provider names?
3. Should discovery (`pflow registry discover`) also show this info?

---

## Quick Reference Links

- LLM config: `src/pflow/core/llm_config.py`
- Settings: `src/pflow/core/settings.py`
- Registry CLI: `src/pflow/cli/registry.py`
- LLM node: `src/pflow/nodes/llm/llm.py`
- Metadata extractor: `src/pflow/registry/metadata_extractor.py`
- Task 95 progress log: `.taskmaster/tasks/task_95/implementation/progress-log.md`

---

## Final Note

**Do not begin implementing yet.** Read this document, review the task spec, and confirm you're ready to begin. The key insight is that Task 95 changed the LLM node behavior significantly - the approach in the task description may need adjustment.

When you're ready, say "I have reviewed the handover and am ready to begin Task 94."
