# Testing the LLM Node

## Quick Start (No Setup Required)

The standard tests are fully mocked — no API keys, no provider setup:

```bash
make test
# or just the LLM tests:
pytest tests/test_nodes/test_llm/test_llm.py -v
```

These tests cover the full LLMNode contract (prep validation, attachment
handling, structured output, reasoning kwargs, error paths, retry
semantics) using `MockLLMClient`, which patches the adapter seam at
`pflow.core.llm_client.complete`.

## Integration Testing (Optional)

If you want to exercise real provider APIs (costs real money):

### 1. Configure API keys

Either via environment variables:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="..."
```

Or via `pflow settings set-env` (persisted in `~/.pflow/settings.json`):

```bash
pflow settings set-env ANTHROPIC_API_KEY "sk-ant-..."
pflow settings set-env OPENAI_API_KEY "sk-..."
pflow settings set-env GEMINI_API_KEY "..."
```

LiteLLM picks up env vars natively; `pflow settings` injects them into
`os.environ` at startup so both paths work the same way.

### 2. Run integration tests

```bash
export RUN_LLM_TESTS=1
pytest tests/test_nodes/test_llm/test_llm_integration.py -v
```

The `RUN_LLM_TESTS=1` gate also disables the autouse `mock_llm_client`
fixture for tests under `/llm/` — they hit the real LiteLLM call path.

## Testing different providers

LiteLLM speaks 100+ providers natively — no plugin install required. Use
the model with its provider prefix:

```python
node.set_params({"model": "anthropic/claude-sonnet-4-5"})  # Anthropic
node.set_params({"model": "openai/gpt-4o-mini"})           # OpenAI
node.set_params({"model": "gemini/gemini-2.5-flash"})      # Google Gemini
node.set_params({"model": "ollama/llama3.2"})              # Local Ollama
node.set_params({"model": "openrouter/anthropic/claude-sonnet-4-5"})
```

See [LiteLLM provider list](https://docs.litellm.ai/docs/providers) for
the full set.

## CI/CD Setup

```yaml
# Mocked tests (always run, no keys needed)
- name: Run tests
  run: make test

# Optional integration tests (real API calls; skip on PRs to keep costs down)
- name: Run LLM integration tests
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    RUN_LLM_TESTS: "1"
  run: pytest tests/test_nodes/test_llm/test_llm_integration.py -v
```

## Common Issues

### "Unknown model" error

LiteLLM rejected the model string. Either the provider prefix is missing
(use `anthropic/claude-sonnet-4-5`, not `claude-sonnet-4-5`) or the
specific model name is wrong. See
[LiteLLM provider list](https://docs.litellm.ai/docs/providers).

### "API key required" error

The provider's env var (e.g. `ANTHROPIC_API_KEY`) isn't set, and
`pflow settings set-env` doesn't have an entry for it either. Set one of
the two and rerun.

### Integration tests skipped

`RUN_LLM_TESTS` isn't set to `1`, or the required env var for the model
under test isn't configured.
