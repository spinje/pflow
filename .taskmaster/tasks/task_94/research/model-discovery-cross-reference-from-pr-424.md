# Model discovery — cross-reference from PR #424 and #421

> **Filed 2026-05-21.** Captures session findings from probing `gemini/gemini-3.5-flash`
> through pflow's LLM adapter on the day PR #424 (cost-map upstream merge) and PR #421
> (`pflow settings llm providers`) merged. These two PRs materially change Task 94's
> implementation space — both narrow its scope and create new landmines that aren't
> in the `task-94-current-state-2026-04-26.md` braindump.
>
> Read this alongside `cache-threshold-cross-reference-from-task-159.md`. That file
> still applies; this one supersedes none of it but adds upstream-merge constraints
> the cache cross-reference doesn't anticipate.

---

## Two PRs landed today that change the Task 94 surface

### PR #421 — `pflow settings llm providers` (merged earlier 2026-05-21)

Ships a static, curated listing of 27 providers under `pflow settings llm providers`
with: required env vars, OR/AND semantics, alternate-auth notes, live STATUS column
("set" / "-" / "n/a"), substring keyword filter, JSON output.

**Closes half of Task 94's original scope.** The "which providers have keys configured?"
question is answered. What remains is the **"which models within a configured provider?"**
half — which is what the rest of this doc is about.

Files touched: `src/pflow/cli/commands/settings.py`, `src/pflow/guide/nodes/llm.md`.

Implication for Task 94's open Q #1 (primary surface): the `pflow settings llm ...`
namespace is now established. A models listing should live at `pflow settings llm models`
unless there's a strong reason to diverge.

### PR #424 — cost-map upstream merge (merged 2026-05-21 ~23:16 UTC)

Adds `ensure_model_priced(model)` in `src/pflow/core/litellm_runtime.py`. On first
cost-map miss per process: fetches upstream JSON via `httpx.get`, validates, merges
via `litellm.register_model(dict)`. Threading lock + double-checked latch collapses
concurrent batch calls to one fetch. Called from `llm_client.complete()` and
`cache_analysis/cost_estimation.py::get_model_pricing()`.

**This is critical context for Task 94 enumeration logic** — see the next section.

---

## The cost-map architecture Task 94 must build against

### pflow forces `LITELLM_LOCAL_MODEL_COST_MAP=True`

The braindump doesn't state this explicitly. Confirmed via PR #424's Explanation:
pflow's `litellm_runtime.py` sets this env flag at import time to keep cost analysis
offline-deterministic. The bundled snapshot in `litellm==1.83.14` has 2,690 models
(cut 2026-04-26).

This means: **`litellm.model_cost` in a fresh pflow process contains bundled-only models.**
Anything added upstream after the snapshot date is absent until `ensure_model_priced(name)`
has been called for that specific name in this process.

### The `register_model(URL)` landmine

PR #424 documents the gotcha that anyone reaching for bulk enumeration will hit:

> `litellm.register_model(URL)` does NOT work when `LITELLM_LOCAL_MODEL_COST_MAP=True`.
> The URL path goes through `get_model_cost_map(url=...)` which short-circuits to the
> bundled backup. Verified at `litellm/litellm_core_utils/get_model_cost_map.py:258`.

The correct pattern (the one PR #424 ships):

1. `httpx.get(litellm.model_cost_map_url)` — fetch the JSON yourself.
2. Parse + validate.
3. Set `litellm.suppress_debug_info = True` before merging (silences "Provider List:"
   stderr spam from per-entry `get_model_info` calls, gated at
   `get_llm_provider_logic.py:463`).
4. `litellm.register_model(dict)` — pass the parsed dict, not the URL.

Any Task 94 enumeration that wants to display models added after the bundled snapshot
must reuse this pattern. Reference implementation lives in
`src/pflow/core/litellm_runtime.py::ensure_model_priced` (post-PR-424).

### The two-tier determinism contract

After PR #424, the contract is explicit:

- **Bundled models**: fully deterministic. Same workflow → same `cost_usd` regardless
  of when or where it runs. No network at the touch point.
- **Unbundled models**: depend on what upstream looked like the first time this process
  touched the model. Subsequent calls in the same process are cached.

Task 94's enumeration surface inherits this. Two design shapes:

| Shape | Pros | Cons |
|---|---|---|
| **Bundled-only by default** | Fast, deterministic, no network | Listing won't show models added upstream (e.g., `gemini-3.5-flash` would be invisible until someone explicitly probes it) |
| **Bulk upstream merge on every listing** | Always current | Network call per `pflow settings llm models` invocation; cross-machine non-determinism; loses the offline-determinism property the rest of pflow relies on |
| **Bundled by default + `--refresh-upstream` flag** | Best of both | Two code paths; agents need to know the flag exists |

The third shape matches the spirit of the new determinism contract: default behavior
preserves it, opt-in flag breaks it deliberately. Recommended as the starting point
unless there's evidence agents will always want the upstream view.

A separate question: should Task 94's listing trigger `ensure_model_priced()` for the
**default model** of each configured provider, so that running a workflow with that
default doesn't pay the first-touch upstream fetch cost? Worth considering — small
warming step at listing time could improve the perceived UX of "list models, then run
one of them."

---

## New evidence on the braindump's open questions

### Open Q #2 (filter LiteLLM list vs. curated regex vs. raw dump)

The braindump frames this as a maintenance-vs-noise tradeoff. PR #424's two-tier
determinism makes it more pointed: **raw dump = bundled-only** by default.

Concrete example (verified this session): `litellm/gemini-3.5-flash` is in the live
upstream registry. It is NOT in pflow's bundled backup. A naive `litellm.model_cost`
enumeration in a fresh pflow process won't show it.

This adds a third axis to the decision:

- "Raw" isn't really raw — it's "raw from whichever cost map happened to be loaded."
- A curated regex per provider sidesteps the bundled/upstream question by listing
  intent ("supported Sonnet 4.x", "supported GPT-4o family") rather than data
  ("whatever LiteLLM has right now"). Maintenance cost is real but bounded.
- Either way, the bulk-merge logic needs to use the `httpx.get` + dict pattern (PR #424)
  not `register_model(URL)`.

### Open Q #5 (lift `default_model` onto `ProviderInfo`)

New evidence: the Gemini family now has at least 4 production-tier Flash models in the
registry simultaneously:

| Model | Input $/M | Output $/M |
|---|---|---|
| `gemini/gemini-2.5-flash` | ~$0.30 (last checked) | ~$2.50 |
| `gemini/gemini-3-flash-preview` | (preview pricing) | (preview pricing) |
| `gemini/gemini-3.1-flash-*` | (preview pricing) | (preview pricing) |
| `gemini/gemini-3.5-flash` | **$1.50** | **$9.00** |

`gemini-3.5-flash` is **5× the input cost and 3.6× the output cost** of `gemini-2.5-flash`.
Additionally, `gemini-3.5-flash` uses 73+ "thinking" output tokens on a trivial probe
(see session evidence below), so the effective output cost per response is even further
inflated.

A "latest version wins" heuristic for default selection would silently 5× users' bills
when 3.5 lands as the registry's newest Flash. **This argues hard for an explicit
`default_model: str` on `ProviderInfo`** with a documented rationale for each provider's
choice. Auto-detection via version-string sort is the wrong abstraction.

### Open Q #1 (primary surface) — partial answer from PR #421

PR #421 chose the `pflow settings llm ...` namespace and proved it works as an
agent-readable surface (JSON output, keyword filter, live STATUS). Models listing
should follow the same shape:

- `pflow settings llm models [provider] [keyword]`
- `--output-format json` for agent parsing
- Live "available" status (key configured?) per row, parallel to the STATUS column in
  `pflow settings llm providers`

---

## "Thinking by default" needs to surface in the schema

Probe result from this session (`pflow probe llm model=gemini/gemini-3.5-flash prompt="Say exactly: pong"`):

```
${response}                        = "pong"           # 1 token of actual reply
${llm_usage.input_tokens}          = 5
${llm_usage.output_tokens}         = 74               # 73 of which were thinking
${llm_usage.thinking_tokens}       = 73
${llm_usage.thinking_budget}       = 0                # not explicitly set; model decided
```

So even with `thinking_budget=0`, the model emitted 73 reasoning tokens at full output
rate ($9/M). That's ~$0.000657 of hidden cost on a 1-token reply.

LiteLLM's `model_cost` entry exposes this:

```python
{
    "supports_reasoning": True,
    "output_cost_per_reasoning_token": 9e-06,
    # ...
}
```

The JSON schema in `cache-threshold-cross-reference-from-task-159.md` (lines 120-138)
has `input_cost_per_mtok` and `output_cost_per_mtok` but no reasoning signal. For
agents picking models, "this looks cheap but thinks by default" is decision-relevant.

**Recommended additions to the Task 94 schema:**

```json
{
  "supports_reasoning": true,
  "output_cost_per_reasoning_mtok": 9.0,
  "reasoning_default": "auto"  // or "off" or "configurable" — needs investigation
}
```

The cross-reference doc's filter table should add `--no-reasoning` for agents who
want to exclude thinking-by-default models when latency or per-call cost predictability
matters.

---

## `pflow probe llm` is the natural verification sibling

The braindump's surface candidates list (`pflow settings llm show`, `pflow guide`, MCP
resources, hypothetical `pflow settings llm models`) doesn't mention `pflow probe llm`.
After Task 94 tells an agent "model X is available," the agent's immediate next move
is "does my key actually work for it?" — and `pflow probe llm` answered that in ~2
seconds this session:

```bash
pflow probe llm model=gemini/gemini-3.5-flash prompt="Say exactly: pong"
# → ✓ Node executed successfully, response = "pong", 2177ms
```

**Recommendation:** Task 94's listing output should include a one-line "verify" hint
per model row:

```
gemini/gemini-3.5-flash  (available)  verify: pflow probe llm model=gemini/gemini-3.5-flash prompt="hi"
```

This matches the identifier-plus-on-demand-expansion pattern the cross-reference doc
already advocates (rustc `--explain`, ruff `rule`, etc.). The verification command
exists today; Task 94 just needs to surface it.

---

## Test patterns to reuse from PR #424

`tests/test_core/test_litellm_runtime.py` ships templates Task 94 should copy if it
implements bulk upstream merge:

- `test_ensure_model_priced_no_op_when_model_in_bundled` — bundled model, no
  `httpx.get`, no `register_model`.
- `test_ensure_model_priced_fetches_when_model_missing` — verify URL is
  `litellm.model_cost_map_url` (respects env override), verify `register_model` got a
  **dict** not a URL.
- `test_ensure_model_priced_idempotent_across_calls` — N calls → 1 fetch via latch.
- `test_ensure_model_priced_silent_on_fetch_failure` — broken upstream doesn't crash;
  latch sets; debug log fires.
- `test_ensure_model_priced_thread_safe` — concurrent calls collapse to one
  invocation.

A bulk-merge variant for Task 94 would add:

- **Schema validation test** — upstream JSON has the keys Task 94's display logic
  reads (e.g., `litellm_provider`, `input_cost_per_token`, `supports_reasoning`,
  `max_input_tokens`). Catches upstream format drift before users see broken listings.
- **Empty-merge test** — what happens if upstream returns `{}` or 200-but-empty.
- **Cache-key collision test** — what happens if a bundled entry and an upstream entry
  disagree on a model's pricing (PR #424's `ensure_model_priced` merges per-model; a
  bulk merge needs an explicit precedence rule documented).

---

## Concrete reference data from this session

### `gemini/gemini-3.5-flash` full pricing (from `litellm.model_cost`)

Standard tier (per million tokens):

| | Cost |
|---|---|
| Input (text) | $1.50 |
| Input (audio) | $1.00 |
| Output (incl. reasoning) | $9.00 |
| Cache reads | $0.15 |

Priority tier (~1.8× standard):

| | Cost |
|---|---|
| Input | $2.70 |
| Output | $16.20 |
| Cache reads | $0.27 |

Other:

- Web search grounding: $0.014/query (flat)
- Context: 1,048,576 input / 65,535 output
- Rate limits: 2,000 RPM, 800,000 TPM
- `supports_prompt_caching: True`
- `supports_reasoning: True`
- `mode: chat`
- `supported_endpoints`: `/v1/chat/completions`, `/v1/completions`, `/v1/batch`
- `supported_modalities`: text, image, audio, video (output: text only)

Source: `https://ai.google.dev/pricing/gemini-3` (per LiteLLM metadata).

### Probe call cost (post-PR-424)

```
5 input × $1.5/M    = $0.0000075
74 output × $9/M    = $0.000666
                    -----------
Total cost_usd      = $0.0006735
```

Matches `litellm.completion` response_cost field after PR #424's `ensure_model_priced`
fires.

---

## Files Task 94 will touch (updated post-PR-424)

| Path | Why |
|---|---|
| `src/pflow/cli/commands/settings.py` | Host for `pflow settings llm models` subcommand; PR #421 added `providers` here — follow the same pattern |
| `src/pflow/core/litellm_runtime.py` | Reuse `ensure_model_priced` for per-model warming; bulk-merge helper (if shape #3 chosen) lives here |
| `src/pflow/core/llm_providers.py` | `PROVIDERS` registry — likely host for `default_model` field (open Q #5) |
| `src/pflow/core/llm_config.py` | `_has_provider_key`, `get_default_workflow_model` — already built; reuse |
| `src/pflow/core/llm_capabilities.py` | Per-model cache thresholds — needed for cross-reference doc's filter extension |
| `src/pflow/core/cache_analysis/warning_catalog.py:355` | Add `pflow settings llm models --min-cache-tokens=N` suggestion to `cache.below-min-predicted` (cross-reference doc, section "Bidirectional cross-reference") |
| `src/pflow/guide/nodes/llm.md` | PR #421 added one breadcrumb; Task 94 adds the models-listing breadcrumb |
| `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` | MCP-server-mode gap |
| `tests/test_core/test_litellm_runtime.py` | Template for upstream-merge tests |
| `tests/test_cli/test_settings.py` (likely) | Template for `pflow settings llm models` CLI tests (mirror PR #421's `providers` tests) |

---

## What this doc does NOT decide

Per the original braindump's principle ("no design decisions locked in here"), this
file adds evidence but does not resolve open questions. Specifically still open after
this session:

- Whether `pflow settings llm models` enumerates from bundled-only, lives-fetched, or
  bundled+`--refresh-upstream`.
- Curated-regex-per-provider vs raw-LiteLLM-filtered.
- Where `default_model` lives (on `ProviderInfo` vs. separate constant).
- How much capability metadata each row carries (cost? cache thresholds? reasoning
  support? full LiteLLM passthrough?).
- Whether the listing should pre-warm `ensure_model_priced` for each provider's
  default model.

The user has historically pushed for minimal scope ("we only need to suggest if api
key is set for 'anthropic', 'gemini', 'openai'" — quoted in the braindump). That
constraint likely still applies; check before assuming Task 94 should grow into a
full model catalog.

---

## TL;DR for the implementing agent

1. **PR #421 closed half of Task 94** — providers listing exists at
   `pflow settings llm providers`. Build the models listing as a sibling, not a
   replacement.
2. **PR #424 forced `LITELLM_LOCAL_MODEL_COST_MAP=True`** — pflow's `litellm.model_cost`
   is bundled-only in a fresh process. Enumeration sees only bundled models unless you
   bulk-merge upstream.
3. **Do NOT use `litellm.register_model(URL)`** — it short-circuits under the flag.
   Use the `httpx.get` + parse + `register_model(dict)` pattern from
   `litellm_runtime.py::ensure_model_priced`.
4. **Set `litellm.suppress_debug_info = True`** before merging to silence stderr spam.
5. **Don't auto-pick newest as default** — gemini-3.5-flash is 5× the cost of
   gemini-2.5-flash. Explicit `default_model` on `ProviderInfo` is the safer abstraction.
6. **Surface `supports_reasoning` in the schema** — thinking-by-default models bill
   reasoning tokens at output rate, materially affecting the agent's cost intuition.
7. **`pflow probe llm` is the verification sibling** — surface it per row so agents
   can confirm "key works for this model" in one command.

---

## References

- PR #424 (cost-map upstream merge): `https://github.com/spinje/pflow/pull/424`
- PR #421 (`pflow settings llm providers`): `https://github.com/spinje/pflow/pull/421`
- LiteLLM determinism gate: `litellm/litellm_core_utils/get_model_cost_map.py:258`
- LiteLLM debug-info gate: `litellm/litellm_core_utils/get_llm_provider_logic.py:463`
- pflow upstream merge helper: `src/pflow/core/litellm_runtime.py::ensure_model_priced`
- Existing Task 94 starting context: `../starting-context/braindump-task-94-current-state-2026-04-26.md`
- Existing Task 94 research: `./cache-threshold-cross-reference-from-task-159.md`
