# Implementation Plan: `pflow settings models` Command

## Overview

Add a `pflow settings models` command that wraps `llm` functionality to show users what LLM models are available based on their configured API keys from all sources.

---

## Command Structure

```bash
pflow settings models          # Default action: list
pflow settings models list     # Explicit list command
```

---

## Expected Output

```
╭─ Configured API Keys ─────────────────────────────────────────╮
│ ✓ anthropic    (from pflow settings)                         │
│ ✓ openai       (from environment variable)                   │
│ ✓ openrouter   (from llm keys)                               │
│ ✗ gemini       (not configured)                              │
╰───────────────────────────────────────────────────────────────╯

╭─ Default Models ──────────────────────────────────────────────╮
│ pflow default: anthropic/claude-sonnet-4-5                    │
│ llm default:   gpt-4o                                         │
╰───────────────────────────────────────────────────────────────╯

╭─ Available Models ────────────────────────────────────────────╮
│                                                               │
│ Anthropic (3 models):                                         │
│   claude-sonnet-4-5                                           │
│   claude-opus-4                                               │
│   claude-haiku                                                │
│                                                               │
│ OpenAI (5 models):                                            │
│   gpt-4o                                                      │
│   gpt-4-turbo                                                 │
│   gpt-3.5-turbo                                               │
│   ...                                                         │
│                                                               │
│ OpenRouter (via llm-openrouter plugin):                       │
│   Run 'llm models' to see all OpenRouter models               │
│                                                               │
╰───────────────────────────────────────────────────────────────╯

Tip: Set default with 'pflow settings llm set-default <model>'
```

---

## Implementation Steps

### Step 1: Add Detection Function to `llm_config.py`

Add `get_configured_providers()` function that returns which providers have keys and from what source:

```python
def get_configured_providers() -> dict[str, str]:
    """Get configured LLM providers and their key sources.

    Returns:
        Dict mapping provider name to source:
        - "environment" - from os.environ
        - "settings" - from pflow settings.json
        - "llm_keys" - from llm CLI key storage
        - None if not configured

    Example:
        {"anthropic": "environment", "openai": "settings", "gemini": None}
    """
```

This function checks the 3 sources in order and returns where each key was found.

### Step 2: Add Models Query Function to `llm_config.py`

Add `get_available_models()` function that queries `llm models`:

```python
def get_available_models() -> dict[str, list[str]]:
    """Get available models from llm library, grouped by provider.

    Runs `llm models` and parses output to group models by provider.

    Returns:
        Dict mapping provider to list of model names.

    Example:
        {
            "Anthropic": ["claude-sonnet-4-5", "claude-opus-4"],
            "OpenAI": ["gpt-4o", "gpt-4-turbo"],
            "OpenRouter": ["openrouter/..."],
        }
    """
```

### Step 3: Add CLI Command Group

In `src/pflow/cli/commands/settings.py`, add:

```python
@settings.group(name="models", invoke_without_command=True)
@click.pass_context
def models(ctx: click.Context) -> None:
    """Show available LLM models based on configured API keys."""
    if ctx.invoked_subcommand is None:
        # Default to list
        ctx.invoke(models_list)


@models.command(name="list")
def models_list() -> None:
    """List available LLM models and configured providers."""
    # 1. Get configured providers
    # 2. Get available models
    # 3. Get default models (pflow + llm)
    # 4. Display formatted output
```

### Step 4: Parse `llm models` Output

The `llm models` command outputs something like:
```
OpenAI Chat: gpt-4o (aliases: 4o), gpt-4o-mini, gpt-4-turbo, ...
Anthropic: claude-sonnet-4-5 (aliases: claude-3-sonnet), ...
```

We need to parse this to extract:
- Provider name
- Model names
- Aliases

```python
def _parse_llm_models_output(output: str) -> dict[str, list[str]]:
    """Parse llm models output into provider -> models dict."""
    result = {}
    for line in output.strip().split('\n'):
        if ':' in line:
            provider, models_str = line.split(':', 1)
            # Parse model names from models_str
            # Handle aliases in parentheses
            ...
    return result
```

### Step 5: Display Formatting

Create display helper functions:

```python
def _display_configured_providers(providers: dict[str, str | None]) -> None:
    """Display configured providers with sources."""

def _display_default_models(pflow_default: str | None, llm_default: str | None) -> None:
    """Display default model configuration."""

def _display_available_models(
    models: dict[str, list[str]],
    configured: dict[str, str | None]
) -> None:
    """Display available models, highlighting configured providers."""
```

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/pflow/core/llm_config.py` | Add `get_configured_providers()`, `get_available_models()` |
| `src/pflow/cli/commands/settings.py` | Add `models` group with `list` command |
| `tests/test_core/test_llm_config_provider_detection.py` | Add tests for new functions |
| `tests/test_cli/test_settings_models.py` | New test file for CLI command |

---

## Detailed Function Specifications

### `get_configured_providers()`

```python
# In src/pflow/core/llm_config.py

def get_configured_providers() -> dict[str, dict[str, Any]]:
    """Get configured LLM providers with their key sources.

    Checks all 3 sources in priority order:
    1. Environment variables (os.environ)
    2. pflow settings (settings.json env section)
    3. llm CLI keys (llm keys get)

    Returns:
        Dict mapping provider to info dict:
        {
            "anthropic": {
                "configured": True,
                "source": "environment",  # or "settings" or "llm_keys"
                "env_var": "ANTHROPIC_API_KEY"
            },
            "gemini": {
                "configured": False,
                "source": None,
                "env_var": "GEMINI_API_KEY"
            }
        }

    Note:
        Only checks the big 3 providers (anthropic, gemini, openai).
        Other providers are discovered via llm models output.
    """
```

### `get_available_models()`

```python
def get_available_models() -> tuple[dict[str, list[str]], list[str]]:
    """Get available models from llm library.

    Runs `llm models` command and parses output.

    Returns:
        Tuple of:
        - Dict mapping provider name to list of model names
        - List of any plugins that have additional models (for "run llm models" hint)

    Example:
        (
            {
                "Anthropic": ["claude-sonnet-4-5", "claude-opus-4"],
                "OpenAI Chat": ["gpt-4o", "gpt-4-turbo"],
            },
            ["OpenRouter"]  # Plugins with many models
        )
    """
```

### CLI Command

```python
@models.command(name="list")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def models_list(output_json: bool) -> None:
    """List available LLM models and configured providers.

    Shows:
    - Which API keys are configured and from what source
    - Default models (pflow and llm)
    - Available models grouped by provider

    Examples:
        pflow settings models
        pflow settings models list
        pflow settings models list --json
    """
```

---

## Edge Cases

1. **No llm installed**: Handle gracefully, show error message
2. **No API keys configured**: Show helpful setup instructions
3. **llm models fails**: Catch exception, show partial info
4. **Plugin with many models** (e.g., OpenRouter): Don't list all, show "run llm models"
5. **Empty output**: Handle gracefully

---

## Testing Strategy

### Unit Tests (`test_llm_config_provider_detection.py`)

```python
class TestGetConfiguredProviders:
    def test_detects_anthropic_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        result = get_configured_providers()
        assert result["anthropic"]["configured"] is True
        assert result["anthropic"]["source"] == "environment"

    def test_detects_openai_from_settings(self, ...):
        ...

    def test_detects_gemini_from_llm_keys(self, ...):
        ...

    def test_shows_not_configured_when_missing(self, ...):
        ...


class TestGetAvailableModels:
    def test_parses_llm_models_output(self, ...):
        ...

    def test_handles_llm_not_installed(self, ...):
        ...

    def test_groups_by_provider(self, ...):
        ...
```

### CLI Tests (`test_settings_models.py`)

```python
class TestSettingsModelsCommand:
    def test_models_shows_configured_providers(self, ...):
        ...

    def test_models_list_same_as_models(self, ...):
        ...

    def test_json_output_format(self, ...):
        ...

    def test_shows_defaults(self, ...):
        ...
```

---

## Implementation Order

1. **Add `get_configured_providers()`** to `llm_config.py`
2. **Add `get_available_models()`** to `llm_config.py`
3. **Add `models` CLI group** to `settings.py`
4. **Add display formatting** helpers
5. **Add tests** for new functions
6. **Add CLI tests** for command
7. **Manual verification**

---

## Verification

```bash
# Test with different configurations
pflow settings models

# With API key in env
ANTHROPIC_API_KEY=test pflow settings models

# With API key in settings
pflow settings set-env OPENAI_API_KEY test
pflow settings models

# JSON output for programmatic use
pflow settings models list --json
```
