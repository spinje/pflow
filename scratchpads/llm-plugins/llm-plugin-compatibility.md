# LLM Plugin Compatibility with pflow

This document captures findings about how pflow integrates with Simon Willison's `llm` library and how users can extend it with plugins for additional providers and local models.

## How pflow Uses the `llm` Library

pflow delegates all LLM interactions to the `llm` library. The key integration points:

### 1. LLM Node (`src/pflow/nodes/llm/llm.py`)

```python
import llm

# In exec() method:
model = llm.get_model(prep_res["model"])  # Line 151
response = model.prompt(prep_res["prompt"], **kwargs)  # Line 166
```

pflow simply calls `llm.get_model(model_name)` - it doesn't maintain its own model registry. Any model that the `llm` library knows about becomes available to pflow.

### 2. Model Detection (`src/pflow/core/llm_config.py`)

For auto-detecting available models, pflow checks API keys via the `llm` CLI:

```python
# Checks: llm keys get <provider>
ALLOWED_PROVIDERS = frozenset({"anthropic", "gemini", "openai"})
```

**Current limitation**: Auto-detection only checks three providers. Other providers (OpenRouter, local models) won't be auto-detected but can still be used explicitly.

## What's Bundled Out of the Box

pflow ships with these LLM plugins as production dependencies:

| Package | Version | What it provides |
|---------|---------|------------------|
| `llm` | >=0.27.1 | Base library (includes OpenAI built-in) |
| `llm-anthropic` | 0.20 | Anthropic Claude models |
| `llm-gemini` | >=0.25 | Google Gemini models (free tier) |
| `anthropic` | >=0.40.0 | Direct SDK for advanced features |

### What Works for End Users Without Extra Plugins

| Provider | Works? | Why |
|----------|--------|-----|
| **Anthropic Claude** | ✅ Yes | `llm-anthropic` bundled |
| **OpenAI GPT** | ✅ Yes | Built into base `llm` library |
| **Google Gemini** | ✅ Yes | `llm-gemini` bundled |
| **Ollama/Local** | ❌ No | Requires `llm-ollama` plugin |
| **OpenRouter** | ❌ No | Requires `llm-openrouter` plugin |

All three providers detected by `llm_config.py` (anthropic, gemini, openai) work out of the box.

## Plugin Compatibility: The Environment Question

**Key insight**: Whether plugins work depends entirely on Python environment isolation.

### Same Environment = Plugins Work

If pflow and `llm` share the same Python environment, any plugin the user installs is immediately available:

```bash
# User's environment
pip install pflow-cli
pip install llm
llm install llm-openrouter  # Installs into same environment

# pflow can now use openrouter models ✓
uv run pflow "summarize this" --param model=openrouter/anthropic/claude-3.5-sonnet
```

### Isolated Environments = Plugins NOT Shared

If pflow is installed in an isolated environment (pipx, uv tool), it has its own `llm` copy:

```bash
# Isolated pflow installation
pipx install pflow-cli  # Has its own llm copy
# OR
uv tool install pflow-cli  # Also isolated

# User installs plugin to their llm
llm install llm-openrouter  # Goes to user's llm, NOT pflow's

# pflow CANNOT see the plugin ✗
```

### Installation Method Comparison

| Installation Method | Plugin Visibility | Inject Support |
|---------------------|-------------------|----------------|
| `pip install pflow-cli` | Shared - plugins work | N/A (same env) |
| `pipx install pflow-cli` | Isolated - NOT shared | `pipx inject pflow-cli llm-openrouter` |
| `uv tool install pflow-cli` | Isolated - NOT shared | **No inject yet** (see below) |

## uv Tool Limitations

As of late 2025, `uv` does not have an equivalent to `pipx inject`. There's an [open GitHub issue (#14746)](https://github.com/astral-sh/uv/issues/14746) requesting `uv tool install --in` to add packages to existing tool environments.

### Workarounds for uv Users

**1. Install with extras upfront:**
```bash
uv tool install --with llm-openrouter pflow-cli
uv tool install --with llm-ollama pflow-cli
```

**2. Reinstall with plugins:**
```bash
uv tool uninstall pflow-cli
uv tool install --with llm-openrouter --with llm-ollama pflow-cli
```

**3. Use pipxu** (pipx reimplemented with uv - [GitHub](https://github.com/bulletmark/pipxu)):
```bash
pipxu install pflow-cli
pipxu inject pflow-cli llm-openrouter
```

## Local Model Options

Users can run models locally using various `llm` plugins. All follow the same pattern: install the plugin, set up the backend, use the model.

### Option 1: Ollama (Recommended for Ease of Use)

Ollama provides the simplest setup with a good model ecosystem.

```bash
# 1. Install Ollama (https://ollama.ai)
# macOS:
brew install ollama
# Linux: curl -fsSL https://ollama.com/install.sh | sh

# 2. Start the Ollama server
ollama serve

# 3. Pull a model
ollama pull llama3.2:latest
ollama pull qwen3:4b          # Tiny 2.6GB model
ollama pull llama3.2-vision   # Vision model (7.9GB)

# 4. Install the llm plugin
llm install llm-ollama

# 5. Test it
llm -m llama3.2:latest "What is the capital of France?"
```

**Features**:
- Supports vision/multi-modal models
- Supports tool calling (as of llm-ollama 0.11+)
- Easy model management with `ollama pull/rm/list`

**In pflow workflows**:
```json
{
  "type": "llm",
  "params": {
    "model": "llama3.2:latest",
    "prompt": "Summarize this text"
  }
}
```

### Option 2: llama.cpp / GGUF Models

Direct access to GGUF format models from HuggingFace.

```bash
# 1. Install llama.cpp
brew install llama.cpp  # macOS

# 2. Install the plugin
llm install llm-gguf

# 3. Use any GGUF model
llm -m gguf/path/to/model.gguf "Hello"

# Or with llama-server for tool support
brew install llama.cpp
llama-server --jinja -hf unsloth/gemma-3-4b-it-GGUF:Q4_K_XL
llm install llm-llama-server
llm -m llama-server "Hello"
```

### Option 3: MLX (Mac Apple Silicon - Best Performance)

For Mac users with Apple Silicon, MLX provides the fastest local inference.

```bash
# Install the plugin
llm install llm-mlx

# Use MLX-optimized models from HuggingFace
llm -m mlx-community/Meta-Llama-3-8B-Instruct-4bit "Hello"
```

### All Local Model Plugins

From the [LLM plugin directory](https://llm.datasette.io/en/stable/plugins/directory.html):

| Plugin | Install Command | Description |
|--------|-----------------|-------------|
| `llm-ollama` | `llm install llm-ollama` | Models via Ollama server |
| `llm-gguf` | `llm install llm-gguf` | Direct GGUF model files via llama.cpp |
| `llm-mlx` | `llm install llm-mlx` | Apple MLX framework (Mac only, fastest) |
| `llm-llama-server` | `llm install llm-llama-server` | llama.cpp server with tool support |
| `llm-llamafile` | `llm install llm-llamafile` | Single-file model executables |
| `llm-gpt4all` | `llm install llm-gpt4all` | GPT4All optimized models |
| `llm-mlc` | `llm install llm-mlc` | MLC project models with GPU accel |

## Cloud Provider Plugins

Beyond the built-in providers (Anthropic, OpenAI, Gemini), users can add:

| Plugin | Install Command | Use Case |
|--------|-----------------|----------|
| `llm-openrouter` | `llm install llm-openrouter` | Access many models via OpenRouter |
| `llm-mistral` | `llm install llm-mistral` | Mistral AI models |
| `llm-bedrock` | `llm install llm-bedrock` | AWS Bedrock models |
| `llm-replicate` | `llm install llm-replicate` | Replicate hosted models |

## Recommendations for pflow Documentation

### For Users Who Want Plugin Flexibility

**Recommend `pip install` in a shared environment:**

```bash
# Create/use a Python environment
python -m venv ~/.pflow-env
source ~/.pflow-env/bin/activate

# Install pflow and llm together
pip install pflow-cli llm

# Now any plugin installed here works with pflow
llm install llm-openrouter
llm install llm-ollama
```

### For Users Who Prefer Isolation

**Document the `--with` pattern for uv:**

```bash
# Install pflow with all desired plugins upfront
uv tool install \
  --with llm-openrouter \
  --with llm-ollama \
  pflow-cli
```

### For the Mintlify Docs

Consider adding a "Using Custom Models" or "LLM Plugins" guide covering:

1. How pflow uses the `llm` library (delegation model)
2. Environment considerations (isolation vs shared)
3. Popular plugins for cloud providers
4. Local model setup (Ollama walkthrough)
5. Troubleshooting "model not found" errors

## Open Questions

1. **Should pflow auto-detect more providers?** Currently `llm_config.py` only checks anthropic/gemini/openai. Could extend to check for ollama, openrouter, etc.

2. ~~**Should pflow bundle common plugins?**~~ **RESOLVED**: Bundled `llm-gemini` in production dependencies. All three auto-detected providers now work out of the box. Local models (ollama) left as user-installed plugins since they require additional setup anyway.

3. **Documentation priority**: This is important for v0.1.0 - users will hit this when trying to use their preferred models.

## Sources

- [LLM Plugin Directory](https://llm.datasette.io/en/stable/plugins/directory.html)
- [llm-ollama GitHub](https://github.com/taketwo/llm-ollama)
- [uv tool inject issue #14746](https://github.com/astral-sh/uv/issues/14746)
- [pipxu - pipx with uv](https://github.com/bulletmark/pipxu)
- [Simon Willison's LLM announcements](https://simonwillison.net/tags/llm/)
