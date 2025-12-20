# Implementation Plan: Robust LLM Provider Detection

## Overview

Implement multi-source API key detection to make model suggestions work for all users, regardless of how they configured their API keys.

---

## Phase 1: Core Detection Logic

**Goal**: Add `PROVIDER_ENV_VARS` constant and `_has_provider_key()` function to `llm_config.py`

**Changes**:
1. Add `PROVIDER_ENV_VARS` constant after `ALLOWED_PROVIDERS` (around line 27)
2. Add `_has_provider_key()` function after `_has_llm_key()` (around line 93)
3. Update `_detect_default_model()` to use `_has_provider_key()` instead of `_has_llm_key()`

**Expected behavior after Phase 1**:
- Setting `ANTHROPIC_API_KEY` env var → detection finds it
- Keys in pflow settings → detection finds them
- Existing `llm keys set` workflow → still works (fallback)

**Verification**:
```bash
# Test env var detection
export ANTHROPIC_API_KEY="test-key"
uv run python -c "from pflow.core.llm_config import get_default_llm_model, clear_model_cache; clear_model_cache(); print(get_default_llm_model())"
# Expected: anthropic/claude-sonnet-4-5
unset ANTHROPIC_API_KEY

# Run existing tests (should still pass)
uv run pytest tests/test_core/test_llm_config*.py -v
```

---

## Phase 2: Environment Injection Function

**Goal**: Add `inject_settings_env_vars()` function to `llm_config.py`

**Changes**:
1. Add `inject_settings_env_vars()` function (public, exported)
2. Function injects keys from `~/.pflow/settings.json` env section into `os.environ`
3. Never overwrites existing env vars (user's environment takes priority)
4. Guarded with `PYTEST_CURRENT_TEST` check
5. Graceful error handling (settings file might not exist)

**Expected behavior after Phase 2**:
- Keys stored via `pflow settings set-env` become available in `os.environ`
- The `llm` library can find these keys for actual API calls
- Existing env vars are NOT overwritten

**Verification**:
```bash
# Store a test key in settings
uv run pflow settings set-env TEST_INJECTION_KEY "injected-value"

# Verify injection works
uv run python -c "
import os
print('Before:', os.environ.get('TEST_INJECTION_KEY'))
from pflow.core.llm_config import inject_settings_env_vars
inject_settings_env_vars()
print('After:', os.environ.get('TEST_INJECTION_KEY'))
"
# Expected: Before: None, After: injected-value

# Clean up
uv run pflow settings unset-env TEST_INJECTION_KEY
```

---

## Phase 3: CLI Integration

**Goal**: Call `inject_settings_env_vars()` early in CLI startup

**Changes**:
1. In `src/pflow/cli/main.py`, add import and call in `workflow_command()`
2. Place call BEFORE the existing `_install_anthropic_model_if_needed()` (line ~3599)
3. Add helper function `_inject_settings_env_vars_if_needed()` following existing pattern

**Expected behavior after Phase 3**:
- Running `pflow "do something"` injects settings keys before any LLM operations
- Model suggestions work for users with keys in settings
- Actual LLM calls work with settings-stored keys

**Verification**:
```bash
# Create test workflow that will fail with unknown model
cat > /tmp/test-model-fail.json << 'EOF'
{"inputs": {}, "nodes": [{"id": "test", "type": "llm", "params": {"prompt": "hi", "model": "bad-model"}}], "edges": []}
EOF

# Test with env var (should suggest anthropic model)
export ANTHROPIC_API_KEY="test-key"
uv run pflow /tmp/test-model-fail.json 2>&1 | grep -i "tip"
# Expected: Contains "Tip: Your API key supports 'anthropic/claude-sonnet-4-5'"
unset ANTHROPIC_API_KEY

# Test with settings key (should suggest openai model)
uv run pflow settings set-env OPENAI_API_KEY "test-key"
uv run pflow /tmp/test-model-fail.json 2>&1 | grep -i "tip"
# Expected: Contains "Tip: Your API key supports 'gpt-5.2'"
uv run pflow settings unset-env OPENAI_API_KEY
```

---

## Phase 4: MCP Server Integration

**Goal**: Call `inject_settings_env_vars()` at MCP server startup

**Changes**:
1. In `src/pflow/mcp_server/main.py`, add import and call in `run_server()`
2. Place call BEFORE the existing Anthropic model install (line ~37)

**Expected behavior after Phase 4**:
- MCP server startup injects settings keys
- AI agents using the MCP server can access settings-stored keys

**Verification**:
```bash
# This is harder to test manually - verify code is correct
# Then run MCP server tests
uv run pytest tests/test_mcp_server/ -v -k "not slow"
```

---

## Phase 5: Tests

**Goal**: Add comprehensive tests for new functionality

**New test file**: `tests/test_core/test_llm_config_provider_detection.py`

**Test cases**:
1. `TestProviderEnvVarDetection`
   - `test_detects_anthropic_env_var`
   - `test_detects_gemini_env_var`
   - `test_detects_google_api_key_for_gemini`
   - `test_detects_openai_env_var`
   - `test_empty_env_var_returns_false`
   - `test_whitespace_env_var_returns_false`

2. `TestProviderSettingsDetection`
   - `test_detects_key_in_settings`
   - `test_handles_missing_settings_file`
   - `test_handles_corrupt_settings_file`

3. `TestProviderKeyPriority`
   - `test_env_var_checked_before_settings`
   - `test_settings_checked_before_llm_cli`

4. `TestInjectSettingsEnvVars`
   - `test_injects_keys_from_settings`
   - `test_does_not_override_existing_env_vars`
   - `test_handles_missing_settings_gracefully`
   - `test_idempotent_multiple_calls`
   - `test_skipped_in_test_environment`

**Verification**:
```bash
# Run new tests
uv run pytest tests/test_core/test_llm_config_provider_detection.py -v

# Run all llm_config tests
uv run pytest tests/test_core/test_llm_config*.py -v

# Run full test suite
make test

# Run quality checks
make check
```

---

## Phase 6: Final Verification

**Goal**: End-to-end verification and cleanup

**Steps**:
1. Run full test suite: `make test`
2. Run quality checks: `make check`
3. Manual end-to-end test with real workflow
4. Clean up any debug code

**Manual E2E Test**:
```bash
# With real Anthropic key in settings (not committed!)
# uv run pflow settings set-env ANTHROPIC_API_KEY "real-key"
# uv run pflow "say hello"  # Should work!
```

---

## Summary of Changes

| Phase | File | Lines Changed |
|-------|------|---------------|
| 1 | `src/pflow/core/llm_config.py` | ~40 lines added |
| 2 | `src/pflow/core/llm_config.py` | ~25 lines added |
| 3 | `src/pflow/cli/main.py` | ~15 lines added |
| 4 | `src/pflow/mcp_server/main.py` | ~5 lines added |
| 5 | `tests/test_core/test_llm_config_provider_detection.py` | ~200 lines (new file) |

**Total**: ~285 lines of code across 4 files
