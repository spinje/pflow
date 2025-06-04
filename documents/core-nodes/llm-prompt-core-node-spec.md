# 📄 `Prompt` Node Specification – MVP (pflow)

## Overview

This document defines the design, behavior, and rationale of the initial `Prompt` node in `pflow`, enabling LLM prompt execution with full support for caching, backend flexibility, and planner clarity. It represents the only LLM-integrated node to be included in the MVP.

---

## ✅ Purpose

The `Prompt` node runs a single-turn text prompt through a chosen large language model (LLM) and stores the result. It provides:

* **Backend-agnostic LLM invocation**
* **Support for OpenAI, Anthropic, and local models** via [Simon Willison’s `llm`](https://github.com/simonw/llm)
* **Stable, cacheable interface** with strong purity guarantees
* **Extendability** toward future nodes like `Embed`, `ToolCall`, and `Chat`

---

## 🔧 Inputs and Outputs

| Interface  | Type  | Key in Shared Store | Description                          |
| ---------- | ----- | ------------------- | ------------------------------------ |
| **Input**  | `str` | `prompt`            | The prompt text to send to the model |
| **Output** | `str` | `response`          | The model-generated output text      |

---

## 🔐 Parameters

| Param         | Type    | Default    | Description                                                    |
| ------------- | ------- | ---------- | -------------------------------------------------------------- |
| `backend`     | `str`   | `"llm"`    | Which backend to use: `"llm"`, `"openai"`, `"anthropic"`, etc. |
| `model`       | `str`   | `"gpt-4o"` | Model name used by the backend                                 |
| `temperature` | `float` | `0.0`      | Sampling temperature — defaulting to deterministic output      |
| `max_tokens`  | `int`   | `1024`     | Output cap — varies per model backend                          |
| `system`      | `str?`  | `None`     | Optional system prompt, used by some chat-style models         |
| `api_key`     | `str?`  | `None`     | Optional direct override of env var or backend default         |

---

## ⚙️ Backend Resolution Logic

```python
if backend == "llm":
    import llm
    model = llm.get_model(self.params["model"])
    return model.prompt(prompt, ...)
elif backend == "openai":
    import openai
    ...
elif backend == "anthropic":
    ...
else:
    raise ValueError("Unsupported backend")
```

*Lazy import is used.*
If the selected backend is not installed or configured, a clear error will point to how to resolve it (`pip install llm` or set API keys).

---

## 🧠 Backend Strategy: Leveraging `llm` (Simon Willison)

The default backend for the `Prompt` node is [`llm`](https://github.com/simonw/llm) by Simon Willison, an open-source CLI and Python toolkit that supports:

* **Multi-provider access** (OpenAI, Anthropic, Gemini, Ollama, Groq, etc.)
* **Built-in prompt templating and fragments**
* **Simple config via `.llm` file or environment variables**
* **Rich plugin ecosystem for embeddings, PDF, GitHub docs, etc.**

### Why we use it

We chose to build the `Prompt` node on `llm` for three reasons:

1. It provides a consistent, stable interface across model providers.
2. It removes the need for users to manage SDKs, headers, auth, and formatting.
3. It evolves rapidly with the LLM ecosystem — adding tools, context features, and integrations faster than we could track ourselves.

### What we expose in pflow

For the MVP, we only expose a **deterministic, single-turn prompt interface**, even though `llm` supports chat, fragments, tools, and more.

| `llm` Feature              | Exposed in `Prompt`? | Notes                                                   |
| -------------------------- | -------------------- | ------------------------------------------------------- |
| Multi-model support        | ✅                    | Exposed via `model` and `backend` params                |
| Prompt execution           | ✅                    | Core feature                                            |
| Prompt templates/fragments | ❌ (yet)              | May be integrated later                                 |
| Tool-calling               | ❌                    | Deferred to `ToolCall` node                             |
| Embedding                  | ❌                    | Will be part of `Embed` node                            |
| Plugins                    | ❌                    | Not exposed directly — but used internally if installed |

### Optional overrides

Users can override `llm` by setting `backend="openai"` or similar. In that case, pflow will use direct SDKs (e.g. `openai`, `anthropic`) instead.

---

## 🔁 Purity & Caching

The `Prompt` node is declared as **pure** and **cacheable** under the following contract:

* `temperature` must default to or be explicitly set to `0.0`
* All parameters (`prompt`, `model`, `backend`, etc.) are part of the **cache key**
* If `llm` is used under the hood, its version **does not affect the cache key** unless pflow explicitly chooses to include `llm.__version__`

```python
@flow_safe  # Eligible for automatic caching
class Prompt(Node):
    ...
```

This enables reproducible runs and cost-effective reuse.

---

## 🔍 Planner Expectations

* The planner will include `Prompt` as a default response-generation node
* Autocomplete will be minimal due to narrow param surface
* If `llm` is not installed and user hasn't specified `backend`, planner will raise a clear validation error with two recovery paths:

  1. Install `llm`: `pip install llm`
  2. Switch backend: `--backend=openai` and provide key

---

## 🧪 Example Flow

```bash
pflow prompt --prompt "Summarize the article" --model "gpt-4o"
```

Or via natural language:

```bash
pflow "Summarize the article and write it to output.md"
```

...which compiles to:

```json
[
  {
    "type": "Prompt",
    "input": {"prompt": "Summarize the article"},
    "params": {"model": "gpt-4o"}
  },
  {
    "type": "WriteFile",
    "input": {"content": "response"},
    "params": {"filename": "output.md"}
  }
]
```

---

## 📦 Future Extension Points

| Node               | Timeline          | Notes                                            |
| ------------------ | ----------------- | ------------------------------------------------ |
| `Embed`            | Post-MVP          | Vector store output                              |
| `ToolCall`         | Post-MVP          | Use `llm`'s new function calling API             |
| `Chat`             | Possibly post-MVP | Multi-turn context handling, statefulness needed |
| `FragmentTemplate` | Deferred          | For long-context assembly from multiple inputs   |

---

## 🧱 Rationale Summary

| Design Area         | Decision                                                   |
| ------------------- | ---------------------------------------------------------- |
| Backend abstraction | Use `llm` by default, fallback to direct SDKs              |
| Node purity         | Treat `Prompt` as pure with proper cache keys              |
| Install behavior    | Do not install `llm` automatically — lazy-import and raise |
| Param surface       | Keep minimal to enable clean planner integration           |
| Output location     | Always writes `response` to shared store                   |
| Backend flexibility | Users can override `llm` with any supported SDK            |

