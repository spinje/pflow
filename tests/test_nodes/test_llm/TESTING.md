# Testing the LLM Node

## Quick Start (No Setup Required)

Just run the standard tests - they're fully mocked:
```bash
make test
# or
pytest tests/test_nodes/test_llm/test_llm.py -v
```

These tests:
- ✅ Cover all 22 specification criteria
- ✅ Run without any API keys
- ✅ Run without any LLM plugins installed
- ✅ Always run in CI/CD

## Integration Testing (Optional)

If you want to test with real LLM APIs:

### 1. Install the plugin for your provider

```bash
# For Anthropic Claude models (used in our integration tests):
uv pip install llm-anthropic

# For other providers:
# (OpenAI is built-in, no plugin needed)
uv pip install llm-gpt4all    # Local models
uv pip install llm-ollama      # Ollama
```

### 2. Configure API keys

```bash
# Option A: Using llm CLI (RECOMMENDED - persistent)
llm keys set anthropic
# Enter your key when prompted: sk-ant-...

llm keys set openai
# Enter your key when prompted: sk-...

# Option B: Environment variable (temporary - for CI/CD or testing)
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

### 3. Run integration tests

```bash
# Enable real API tests
export RUN_LLM_TESTS=1

# Run integration tests
pytest tests/test_nodes/test_llm/test_llm_integration.py -v
```

## What This Means for Development

### For pflow developers:
1. **Primary development** uses mocked tests only - no plugins needed
2. **Integration testing** is optional - install plugins only if you need them
3. **CI/CD** runs mocked tests only - fast and free

### For pflow users:
1. **Install pflow** - gets base `llm` library
2. **Install plugins** for their preferred LLM provider
3. **Use any model** from any installed plugin

### Testing different providers:

If you want to test with different models, just modify the integration test:

```python
# Test with OpenAI (no extra plugin needed)
node.set_params({"model": "gpt-4"})

# Test with local model (needs llm-gpt4all)
node.set_params({"model": "orca-mini-3b"})

# Test with Ollama (needs llm-ollama)
node.set_params({"model": "llama2:latest"})
```

## CI/CD Setup

For GitHub Actions or other CI/CD:

```yaml
# Basic tests (always run)
- name: Run tests
  run: make test

# Optional integration tests (only if you want to pay for API calls)
- name: Run LLM integration tests
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    RUN_LLM_TESTS: "1"
  run: |
    pip install llm-anthropic  # Install plugin
    pytest tests/test_nodes/test_llm/test_llm_integration.py -v
```

## Common Issues

### "Unknown model" error
- **Cause**: Plugin for that provider not installed
- **Fix**: Install the appropriate plugin (e.g., `pip install llm-anthropic`)

### "API key required" error
- **Cause**: Plugin installed but no API key configured
- **Fix**: Set the API key via environment variable or `llm keys set`

### Integration tests skipped
- **Cause**: `RUN_LLM_TESTS` not set or plugin/key missing
- **Fix**: Set `RUN_LLM_TESTS=1` and ensure plugin + key are configured

## Summary

The key insight: **Separation of concerns**
- pflow provides the LLM node infrastructure
- Users choose and install their LLM providers
- Tests work at both levels: mocked (always) and real (optional)
