# Robust LLM Provider Detection

## Task Overview

Enhance pflow's LLM provider detection to check multiple sources for API keys, not just the `llm` CLI. This makes the "model suggestion" feature in error messages work reliably for all users regardless of how they configured their API keys.

---

## Problem Statement

### Current Behavior

When an LLM node fails with an unknown model error, pflow now suggests a working model:

```
Unknown model: bad-model. Tip: Your API key supports 'anthropic/claude-sonnet-4-5'. Run 'llm models' to see all available models.
```

This uses `get_default_llm_model()` which relies on `_has_llm_key()` to detect configured providers.

### The Gap

`_has_llm_key()` ONLY checks keys stored via Simon Willison's `llm` CLI:
```bash
llm keys set anthropic  # Stores key in llm's internal storage
```

It does NOT detect:
1. **Environment variables**: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`
2. **pflow settings**: Keys stored in `~/.pflow/settings.json` under the `env` section

### User Impact

Users who configure API keys via environment variables (common practice) or pflow's settings system won't see the helpful model suggestion - they'll just get:
```
Unknown model: bad-model. Run 'llm models' to see available models.
```

---

## Required Reading

Before implementing, read these files thoroughly:

### Core Files to Understand

| File | What to Learn | Key Lines |
|------|---------------|-----------|
| `src/pflow/core/llm_config.py` | Current detection logic, caching, resolution chains | Full file (~370 lines) |
| `src/pflow/core/settings.py` | Settings structure, `LLMSettings`, env storage | `LLMSettings` class, `get_env()`, `set_env()` |
| `src/pflow/nodes/llm/llm.py` | Where detection is called in error handling | Lines 245-275 (`exec_fallback`) |

### Context Files

| File | Why Read It |
|------|-------------|
| `.taskmaster/tasks/task_95/implementation/progress-log.md` | Full context on LLM unification, model resolution chains |
| `.taskmaster/tasks/task_95/task-review.md` | Architectural decisions, patterns established |
| `src/pflow/core/CLAUDE.md` | Settings system documentation, security considerations |

### Test Files to Understand

| File | Purpose |
|------|---------|
| `tests/test_core/test_llm_config_workflow_model.py` | Existing resolution chain tests |
| `tests/test_core/test_settings.py` | Settings env tests |

---

## Current Implementation Analysis

### `_has_llm_key()` in `llm_config.py` (Lines 45-91)

```python
def _has_llm_key(provider: str) -> bool:
    """Check if an LLM provider key is configured.

    Uses Simon Willison's llm CLI to check for configured keys.
    """
    # Security: Validate provider against allowlist
    if provider not in ALLOWED_PROVIDERS:
        return False

    llm_path = _get_validated_llm_path()
    if not llm_path:
        return False

    # Runs: llm keys get <provider>
    command = [llm_path, *_LLM_KEYS_SUBCOMMAND, provider]
    result = subprocess.run(command, ...)
    return result.returncode == 0 and bool(result.stdout.strip())
```

**Limitation**: Only checks `llm` CLI storage, not environment variables or pflow settings.

### `_detect_default_model()` in `llm_config.py` (Lines 94-126)

```python
def _detect_default_model() -> Optional[str]:
    """Detect best available LLM model based on configured API keys."""
    # Priority: Anthropic > Gemini > OpenAI
    if _has_llm_key("anthropic"):
        return "anthropic/claude-sonnet-4-5"
    if _has_llm_key("gemini"):
        return "gemini/gemini-3-flash-preview"
    if _has_llm_key("openai"):
        return "gpt-5.2"
    return None
```

**This is what needs enhancement** - should check multiple sources.

### Settings `env` Section (from Task 80)

Users can store API keys in `~/.pflow/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-...",
    "OPENAI_API_KEY": "sk-...",
    "GEMINI_API_KEY": "..."
  }
}
```

Accessed via:
```python
from pflow.core.settings import SettingsManager
manager = SettingsManager()
key = manager.get_env("ANTHROPIC_API_KEY")
```

---

## Proposed Solution

### New Function: `_has_provider_key()`

Create a comprehensive key detection function that checks multiple sources:

```python
# Provider to environment variable mapping
PROVIDER_ENV_VARS = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
}

def _has_provider_key(provider: str) -> bool:
    """Check if an LLM provider key is configured from ANY source.

    Checks in order (stops at first found):
    1. Environment variables (os.environ)
    2. pflow settings (settings.json env section)
    3. llm CLI keys (llm keys get)

    Args:
        provider: Provider name ("anthropic", "gemini", "openai")

    Returns:
        True if key is configured in any source
    """
    if provider not in ALLOWED_PROVIDERS:
        return False

    # 1. Check environment variables directly
    env_vars = PROVIDER_ENV_VARS.get(provider, [])
    for var in env_vars:
        if os.environ.get(var):
            logger.debug(f"Found {provider} key in environment variable {var}")
            return True

    # 2. Check pflow settings
    try:
        from pflow.core.settings import SettingsManager
        manager = SettingsManager()
        for var in env_vars:
            if manager.get_env(var):
                logger.debug(f"Found {provider} key in pflow settings ({var})")
                return True
    except Exception as e:
        logger.debug(f"Failed to check pflow settings: {e}")

    # 3. Fall back to llm CLI check
    return _has_llm_key(provider)
```

### Update `_detect_default_model()`

Replace `_has_llm_key()` calls with `_has_provider_key()`:

```python
def _detect_default_model() -> Optional[str]:
    """Detect best available LLM model based on configured API keys."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None

    if _has_provider_key("anthropic"):
        return "anthropic/claude-sonnet-4-5"
    if _has_provider_key("gemini"):
        return "gemini/gemini-3-flash-preview"
    if _has_provider_key("openai"):
        return "gpt-5.2"
    return None
```

---

## Implementation Plan

### Step 0: Add Environment Injection Function

**Critical prerequisite**: The `llm` library needs API keys in `os.environ` to make calls. Keys stored only in pflow settings won't work unless we inject them.

Add to `src/pflow/core/llm_config.py`:

```python
def inject_settings_env_vars() -> None:
    """Inject env vars from pflow settings into os.environ.

    This allows the llm library (and other tools) to find API keys
    stored in pflow settings. Only injects if the key isn't already
    set in os.environ (user's actual environment takes priority).

    Should be called early in CLI/MCP server startup, before any LLM operations.

    Note:
        This is idempotent - safe to call multiple times.
        Failures are logged but don't raise (graceful degradation).
    """
    try:
        from pflow.core.settings import SettingsManager
        manager = SettingsManager()
        env_vars = manager.list_env(mask_values=False)

        for key, value in env_vars.items():
            if key not in os.environ:  # Don't override user's environment
                os.environ[key] = value
                logger.debug(f"Injected {key} from pflow settings into environment")
            else:
                logger.debug(f"Skipped {key} - already set in environment")
    except Exception as e:
        # Settings file might not exist or be corrupt - that's fine
        logger.debug(f"Failed to inject settings env vars: {e}")
```

**Call this function in two places:**

1. **CLI startup** - `src/pflow/cli/main.py` in `workflow_command()` early, before any LLM operations:
   ```python
   # Near the top of workflow_command(), after imports
   from pflow.core.llm_config import inject_settings_env_vars
   inject_settings_env_vars()
   ```

2. **MCP server startup** - `src/pflow/mcp_server/main.py` in the startup sequence:
   ```python
   # In main() or server initialization
   from pflow.core.llm_config import inject_settings_env_vars
   inject_settings_env_vars()
   ```

### Step 1: Add Provider Environment Variable Mapping

Add constant at top of `llm_config.py`:

```python
# Provider to environment variable mapping
# Some providers accept multiple variable names
PROVIDER_ENV_VARS: dict[str, list[str]] = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
}
```

### Step 2: Create `_has_provider_key()` Function

Add after `_has_llm_key()` (around line 92):

- Check environment variables first (fastest)
- Check pflow settings second
- Fall back to `_has_llm_key()` for llm CLI storage
- Use lazy import for SettingsManager to avoid circular imports
- Handle exceptions gracefully (settings file might not exist)

### Step 3: Update `_detect_default_model()`

Replace `_has_llm_key()` with `_has_provider_key()` in the detection chain.

### Step 4: Update `get_model_for_feature()` (Optional)

If it also uses `_has_llm_key()`, update to use `_has_provider_key()`.

### Step 5: Add Tests

Create new test file or add to existing:

```python
# tests/test_core/test_llm_config_provider_detection.py

class TestProviderKeyDetection:
    def test_detects_env_var_anthropic(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert _has_provider_key("anthropic") is True

    def test_detects_settings_anthropic(self, tmp_path, monkeypatch):
        # Set up isolated settings with key
        ...

    def test_priority_order(self):
        # Verify env vars checked before settings
        ...

    def test_returns_false_when_no_key(self):
        # Clean environment, no settings
        ...
```

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/pflow/core/llm_config.py` | Add `inject_settings_env_vars()`, `PROVIDER_ENV_VARS`, `_has_provider_key()`, update `_detect_default_model()` |
| `src/pflow/cli/main.py` | Call `inject_settings_env_vars()` early in `workflow_command()` |
| `src/pflow/mcp_server/main.py` | Call `inject_settings_env_vars()` at startup |
| `tests/test_core/test_llm_config_provider_detection.py` | New test file for provider detection and env injection |

---

## Testing Strategy

### Unit Tests

1. **Environment injection (`inject_settings_env_vars()`)**
   - Injects keys from settings into os.environ
   - Does NOT override existing os.environ keys (priority)
   - Gracefully handles missing settings file
   - Gracefully handles corrupt settings file
   - Idempotent (safe to call multiple times)

2. **Environment variable detection**
   - Each provider with correct env var set
   - Multiple env vars for same provider (e.g., GEMINI_API_KEY vs GOOGLE_API_KEY)
   - Empty string env var (should return False)

3. **Settings detection**
   - Key in settings.json
   - Settings file doesn't exist (graceful handling)
   - Settings file exists but no env section

4. **llm CLI fallback**
   - Mock `_has_llm_key()` to verify it's called when other sources fail

5. **Priority order**
   - Env var takes precedence over settings
   - Settings takes precedence over llm CLI

### Integration Tests

1. **Model suggestion in error message**
   - Set env var, trigger unknown model error, verify suggestion appears

### Manual Verification

```bash
# Create test workflow
cat > /tmp/test-llm-fail.json << 'EOF'
{"inputs": {}, "nodes": [{"id": "test", "type": "llm", "params": {"prompt": "hi", "model": "bad-model"}}], "edges": []}
EOF

# Test 1: Direct environment variable
export ANTHROPIC_API_KEY="sk-ant-test"
uv run pflow /tmp/test-llm-fail.json 2>&1 | grep "Tip:"
# Should show: "Tip: Your API key supports 'anthropic/claude-sonnet-4-5'"
unset ANTHROPIC_API_KEY

# Test 2: Key in pflow settings (injection test)
uv run pflow settings set-env OPENAI_API_KEY "sk-test-key"
uv run pflow /tmp/test-llm-fail.json 2>&1 | grep "Tip:"
# Should show: "Tip: Your API key supports 'gpt-5.2'"

# Test 3: Priority - env var should override settings
export ANTHROPIC_API_KEY="sk-ant-priority"
uv run pflow /tmp/test-llm-fail.json 2>&1 | grep "Tip:"
# Should show: "Tip: Your API key supports 'anthropic/claude-sonnet-4-5'" (NOT gpt-5.2)
unset ANTHROPIC_API_KEY

# Test 4: Verify injection works for actual LLM calls (with real key)
# uv run pflow settings set-env ANTHROPIC_API_KEY "real-key-here"
# uv run pflow "say hello"  # Should work without setting env var directly

# Cleanup
uv run pflow settings unset-env OPENAI_API_KEY
```

---

## Acceptance Criteria

1. **Environment injection works**: Keys from `settings.json` are injected into `os.environ` at startup
2. **Injection respects priority**: User's actual env vars are NOT overwritten
3. **Environment variables detected**: Setting `ANTHROPIC_API_KEY` env var triggers detection
4. **pflow settings detected**: Keys in `settings.json` env section are found
5. **llm library can use settings keys**: After injection, `llm` library finds the API keys
6. **llm CLI still works**: Existing `llm keys set` workflow unchanged
7. **Priority respected**: env vars > settings > llm CLI
8. **Graceful degradation**: Missing settings file doesn't cause errors
9. **All existing tests pass**: No regressions
10. **New tests added**: Coverage for injection and detection logic
11. **`make check` passes**: Linting, type checking, etc.

---

## Security Considerations

1. **Don't log key values**: Only log that a key was found, not its value
2. **Validate provider names**: Use existing `ALLOWED_PROVIDERS` allowlist
3. **Handle exceptions safely**: Don't expose settings file contents in errors
4. **Injection priority**: Never override user's actual environment variables (they take priority)
5. **Settings file permissions**: Settings file should be 600 (already enforced by SettingsManager)

---

## Edge Cases to Handle

### Detection Edge Cases
1. **Empty string keys**: `ANTHROPIC_API_KEY=""` should return False
2. **Whitespace-only keys**: `ANTHROPIC_API_KEY="  "` should return False
3. **Settings file missing**: Should not raise, just continue to next source
4. **Settings file corrupt**: Should not raise, just continue to next source
5. **Circular import**: Use lazy import for SettingsManager
6. **Test environment**: Skip detection if `PYTEST_CURRENT_TEST` is set

### Injection Edge Cases
7. **Injection before detection**: `inject_settings_env_vars()` must be called before `_detect_default_model()` for settings keys to be found
8. **Multiple calls to inject**: Should be idempotent (safe to call twice)
9. **Existing env var**: Should NOT override - user's env takes priority
10. **Empty settings env section**: Should handle gracefully (no-op)
11. **Non-string values in settings**: Should handle or skip gracefully

---

## Example Implementation

Here's a complete implementation for reference:

```python
# Add after line 29 in llm_config.py

# Provider to environment variable mapping
# Some providers accept multiple variable names
PROVIDER_ENV_VARS: dict[str, list[str]] = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
}


def _has_provider_key(provider: str) -> bool:
    """Check if an LLM provider key is configured from ANY source.

    Checks in order (stops at first found):
    1. Environment variables (os.environ)
    2. pflow settings (settings.json env section)
    3. llm CLI keys (llm keys get)

    Args:
        provider: Provider name ("anthropic", "gemini", "openai")

    Returns:
        True if key is configured in any source

    Note:
        This function is intentionally lenient - it checks multiple sources
        to maximize the chance of finding a configured key and providing
        helpful model suggestions in error messages.
    """
    if provider not in ALLOWED_PROVIDERS:
        logger.debug(f"Provider {provider} not in allowed list")
        return False

    env_vars = PROVIDER_ENV_VARS.get(provider, [])

    # 1. Check environment variables directly (fastest)
    for var in env_vars:
        value = os.environ.get(var, "").strip()
        if value:
            logger.debug(f"Found {provider} key in environment variable {var}")
            return True

    # 2. Check pflow settings (lazy import to avoid circular imports)
    try:
        from pflow.core.settings import SettingsManager
        manager = SettingsManager()
        for var in env_vars:
            value = manager.get_env(var)
            if value and value.strip():
                logger.debug(f"Found {provider} key in pflow settings ({var})")
                return True
    except Exception as e:
        # Settings might not exist or be corrupt - continue to next source
        logger.debug(f"Failed to check pflow settings for {provider}: {e}")

    # 3. Fall back to llm CLI check
    return _has_llm_key(provider)
```

Then update `_detect_default_model()` to use `_has_provider_key()` instead of `_has_llm_key()`.

---

## Related Files Reference

```
src/pflow/core/
├── llm_config.py          # Main file to modify - add inject + detection
├── settings.py            # SettingsManager, get_env(), list_env()
├── CLAUDE.md              # Documentation for core module

src/pflow/cli/
├── main.py                # Call inject_settings_env_vars() in workflow_command()

src/pflow/mcp_server/
├── main.py                # Call inject_settings_env_vars() at startup

tests/test_core/
├── test_llm_config_workflow_model.py    # Existing resolution tests
├── test_settings.py                      # Settings tests (reference for env operations)
├── test_llm_config_provider_detection.py # NEW - injection + provider detection tests

.taskmaster/tasks/task_95/
├── implementation/progress-log.md        # Context on LLM unification
├── task-review.md                         # Architectural decisions
```

---

## Verification Commands

After implementation:

```bash
# Run new tests
uv run pytest tests/test_core/test_llm_config_provider_detection.py -v

# Run all LLM config tests
uv run pytest tests/test_core/test_llm_config*.py -v

# Run settings tests (to ensure no regressions)
uv run pytest tests/test_core/test_settings.py -v

# Run full test suite
make test

# Run quality checks
make check

# Manual verification - Test 1: Direct env var
export ANTHROPIC_API_KEY="test-key"
uv run pflow /tmp/test-llm-fail.json 2>&1 | grep "Tip:"
unset ANTHROPIC_API_KEY

# Manual verification - Test 2: Settings injection
uv run pflow settings set-env OPENAI_API_KEY "test-key"
uv run pflow /tmp/test-llm-fail.json 2>&1 | grep "Tip:"
uv run pflow settings unset-env OPENAI_API_KEY
```

---

## Summary

This enhancement makes pflow's model suggestion feature AND actual LLM calls work for all users by:

### Environment Injection (Step 0)
- Injects API keys from `~/.pflow/settings.json` into `os.environ` at startup
- Allows the `llm` library to find keys stored via `pflow settings set-env`
- Respects priority: user's actual env vars are never overwritten

### Multi-Source Detection (Steps 1-4)
- Checks environment variables first (fastest)
- Checks pflow settings second
- Falls back to llm CLI keys last

### Benefits
- Users can store API keys in pflow settings (more secure than shell history)
- Model suggestions work regardless of how keys are configured
- Actual LLM calls work with settings-stored keys (not just detection)
- Backwards compatible with existing workflows

The implementation is backwards compatible and gracefully handles missing sources.
