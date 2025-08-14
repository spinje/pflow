# LLM Node

General-purpose LLM node for text processing in pflow workflows.

## Installation

The LLM node uses Simon Willison's `llm` library, which is included with pflow. However, to use specific LLM providers, you need to install their plugins separately:

### For Anthropic Claude models:
```bash
pip install llm-anthropic
# or
uv pip install llm-anthropic

# Then set your API key:
export ANTHROPIC_API_KEY="your-key-here"
# or
llm keys set anthropic
```

### For OpenAI models (GPT-4, etc.):
```bash
# OpenAI support is built into the base llm library
# Just set your API key:
export OPENAI_API_KEY="your-key-here"
# or
llm keys set openai
```

### For local models:
```bash
pip install llm-gpt4all  # For GPT4All models
pip install llm-ollama    # For Ollama
pip install llm-mlc       # For MLC LLM
```

### Install all supported LLM providers:
```bash
pip install pflow[all-llms]
```

## Usage

### Basic usage:
```bash
pflow llm --prompt="Hello, world!"
```

### With a specific model:
```bash
pflow llm --prompt="Hello" --model="claude-4-sonnet"
pflow llm --prompt="Hello" --model="gpt-5-nano"
pflow llm --prompt="Hello" --model="llama2:latest"  # Ollama
```

### With parameters:
```bash
pflow llm \
  --prompt="Write a haiku" \
  --model="gpt-4" \
  --temperature=0.3 \
  --max_tokens=50 \
  --system="You are a poet"
```

### In a workflow:
```bash
# Read file and summarize
pflow read-file --path=document.txt >> llm --prompt="Summarize: $content"
```

## Available Models

To see all available models (based on installed plugins):
```bash
llm models
```

Common models:
- **OpenAI**: `gpt-4o-mini` (default), `gpt-4`, `gpt-3.5-turbo`
- **Anthropic**: `anthropic/claude-sonnet-4-0`, `anthropic/claude-opus-4-0`
- **Local**: Depends on installed plugins

## Parameters

- `prompt`: Text prompt to send to the model (required)
- `model`: Model to use (default: `gpt-4o-mini`)
- `temperature`: Sampling temperature 0.0-2.0 (default: 0.7)
- `system`: System prompt for behavior guidance (optional)
- `max_tokens`: Maximum response tokens (optional)

## Token Usage Tracking

The node tracks token usage in `shared["llm_usage"]`:
```json
{
  "model": "gpt-4o-mini",
  "input_tokens": 150,
  "output_tokens": 75,
  "total_tokens": 225,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 0
}
```

This enables cost analysis and optimization of workflows.

## Error Handling

The node provides helpful error messages:
- **Unknown model**: Suggests running `llm models` to see available models
- **Missing API key**: Suggests using `llm keys set <provider>` to configure
- **API failures**: Includes retry count and model information

## Philosophy

This is the ONLY LLM node in pflow - a deliberate design choice to prevent proliferation of prompt-specific nodes. Instead of having `analyze-code`, `write-content`, `explain-concept` nodes, we have one flexible LLM node that can be configured for any text processing task.
