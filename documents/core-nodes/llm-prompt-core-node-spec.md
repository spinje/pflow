Excellent — treating the `Prompt` node as **pure** (cacheable) is fully reasonable *if* we make two key assumptions explicit:

1. **The prompt input fully determines the output.**
   No hidden randomness (e.g. sampling with `temperature > 0`) unless explicitly included in the cache key.

2. **The backend and model name are part of the effective input.**
   Because calling the same prompt on `gpt-4o` vs `claude-3-opus` can give wildly different results.

---

Here’s the full, consolidated document:

---

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

---

Let me know if you'd like a markdown, JSON schema, or Mermaid diagram version of this.
