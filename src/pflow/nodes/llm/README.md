# LLM Node

General-purpose LLM node for text processing in pflow workflows.

## Provider support

The LLM node calls AI models through [LiteLLM](https://docs.litellm.ai/), which is bundled with pflow. LiteLLM speaks to 100+ providers natively (OpenAI, Anthropic, Google, OpenRouter, Ollama, Mistral, Bedrock, Azure OpenAI, vLLM, ...) — no plugin install required.

### Set provider API keys

```bash
# Stored in ~/.pflow/settings.json
pflow settings set-env ANTHROPIC_API_KEY "sk-ant-..."
pflow settings set-env OPENAI_API_KEY "sk-..."
pflow settings set-env GEMINI_API_KEY "..."
pflow settings set-env OPENROUTER_API_KEY "sk-or-..."
```

Or as plain shell environment variables (LiteLLM picks them up directly):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

### Local models via Ollama

```bash
brew install ollama
ollama serve
ollama pull llama3.2
```

Then reference Ollama models with the `ollama/` prefix in your workflow:

```yaml
- type: llm
- model: ollama/llama3.2
```

## Usage

LLM nodes are declared inside `.pflow.md` workflow files. There is no
standalone `pflow llm` CLI — you write the workflow, then run it with
`pflow <workflow.pflow.md>`.

### Basic LLM node

````markdown
### greet

Greet the user.

- type: llm
- prompt: Hello, world!
````

### With a specific model

````markdown
### summarize

Summarize the document.

- type: llm
- model: anthropic/claude-sonnet-4-5
- prompt: Summarize this in three sentences:\n\n${read.content}
````

Provider prefixes the LLM node accepts:

- `openai/gpt-5.2`, `openai/gpt-4o-mini`
- `anthropic/claude-sonnet-4-5`, `anthropic/claude-opus-4-5`
- `gemini/gemini-3-flash-preview`, `gemini/gemini-2.5-pro`
- `ollama/<model-name>` (local Ollama)
- See https://docs.litellm.ai/docs/providers for the full list.

### With more parameters

````markdown
### haiku

Write a haiku about pflow.

- type: llm
- model: openai/gpt-4o-mini
- system: You are a haiku poet. Reply in 5-7-5 syllables.
- temperature: 0.3
- max_tokens: 50
- prompt: Write a haiku about workflow automation.
````

### Reading from another node

The shared store flows naturally between steps via `${node.field}`:

````markdown
### read

Read the source file.

- type: file
- path: document.txt

### summarize

Summarize what was read.

- type: llm
- prompt: Summarize this in three sentences:\n\n${read.content}
````

## Image Support

The LLM node supports multimodal models by accepting images via URLs or
file paths. Images are passed to models that support vision capabilities
(GPT-4o, Claude 3.5+ Sonnet, Gemini Flash, etc.).

### Single URL image

````markdown
### describe

Describe the image.

- type: llm
- model: openai/gpt-4o-mini
- prompt: Describe this image.
- images: https://example.com/cat.jpg
````

### Multiple images (mixed URLs and local paths)

````markdown
### compare

Compare two images.

- type: llm
- model: openai/gpt-4o-mini
- prompt: Compare these two images.
- images:
  - ./local-image.jpg
  - https://example.com/remote.png
````

Local paths are resolved against the working directory at run time.

### Supported formats

LiteLLM forwards these image formats to vision-capable models:

- **JPEG/JPG** (image/jpeg)
- **PNG** (image/png)
- **GIF** (image/gif)
- **WebP** (image/webp)
- **PDF** (application/pdf)

### Notes

- Images are optional — the node works with text-only prompts.
- You can mix URLs and file paths in the same call.
- URL images are fetched at runtime (network errors trigger retries).
- Local file paths are validated before execution (missing files fail immediately).
- Not all models support images — check the [LiteLLM provider list](https://docs.litellm.ai/docs/providers) for vision-capable models.

## Available Models

To see pflow's configured models and resolution order:
```bash
pflow settings llm show
```

Common models (always include the provider prefix — bare names route via Vertex/etc. or fail):
- **OpenAI**: `openai/gpt-4o-mini`, `openai/gpt-5.2`, `openai/gpt-4o`
- **Anthropic**: `anthropic/claude-sonnet-4-5`, `anthropic/claude-opus-4-5`, `anthropic/claude-haiku-4-5`
- **Google**: `gemini/gemini-3-flash-preview`, `gemini/gemini-2.5-pro`
- **OpenRouter**: `openrouter/<provider>/<model>` — see https://openrouter.ai/models
- **Ollama (local)**: `ollama/<model-name>` — depends on what you've pulled

## Parameters

- `prompt`: Text prompt to send to the model (required)
- `model`: Model to use (default: auto-detected from configured keys)
- `temperature`: Sampling temperature 0.0-2.0 (default: 1.0)
- `system`: System prompt for behavior guidance (optional)
- `max_tokens`: Maximum response tokens (optional)
- `images`: Image URLs or file paths (optional, can be repeated for multiple images)
- `output_schema`: JSON Schema dict for structured output (optional) — see below

## Structured Output

Use `output_schema` to get guaranteed JSON responses matching a JSON Schema. The schema is passed to the model's constrained decoding API (supported by Anthropic, Google, OpenAI).

### In a workflow (.pflow.md):

````markdown
### extract

Extract named entities from the document.

- type: llm
- prompt: Extract all people and places from: ${read.content}
- temperature: 0

```yaml output_schema
type: object
properties:
  people:
    type: array
    items:
      type: string
  places:
    type: array
    items:
      type: string
required:
  - people
  - places
```
````

When `output_schema` is set:
- The response is guaranteed valid JSON matching the schema
- `shared["response"]` is a `dict` (not a string)
- Downstream templates access fields directly: `${extract.response.people}`
- Code block stripping is skipped (the API returns clean JSON)

Without `output_schema`, behavior is unchanged — `shared["response"]` is always a string.

## Token Usage Tracking

The node tracks token usage in `shared["llm_usage"]`:
```json
{
  "model": "openai/gpt-4o-mini",
  "input_tokens": 150,
  "output_tokens": 75,
  "total_tokens": 225,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 0,
  "cost_usd": 0.000115
}
```

Cost is populated from LiteLLM's `response_cost` (`None` for models LiteLLM doesn't have pricing for, e.g. custom endpoints or new releases). This enables cost analysis and optimization of workflows.

## Error Handling

The node provides helpful error messages:
- **Unknown model**: Suggests checking the [LiteLLM provider list](https://docs.litellm.ai/docs/providers) and running `pflow settings llm show`
- **Missing API key**: Suggests `pflow settings set-env <PROVIDER>_API_KEY <value>` or `export <PROVIDER>_API_KEY=...`
- **API failures**: Includes retry count and model information

## Philosophy

This is the ONLY LLM node in pflow - a deliberate design choice to prevent proliferation of prompt-specific nodes. Instead of having `analyze-code`, `write-content`, `explain-concept` nodes, we have one flexible LLM node that can be configured for any text processing task.
