# Task 94 starting context (post-Task-158)

**Date**: 2026-04-26. **Last updated**: 2026-05-21 (post-PR-421, post-PR-424 — see "Update 2026-05-21" annotations inline and the companion research file `../research/model-discovery-cross-reference-from-pr-424.md` for the deep dive on those PRs' implications). **Supersedes**: the two prior handover memos (`task-94-handover-01.md` and `task-94-handover-02.md`), which described an architectural state that no longer exists. Both were written in the `llm`-library era; Task 158 replaced that library with LiteLLM via a pflow-owned adapter, which deletes most of the assumptions those memos relied on.

This document is **starting context for whoever picks up Task 94**, not a design spec. The premise is sound; the implementation needs re-thinking against the current architecture. No design decisions are locked in here — open questions are flagged explicitly at the bottom.

---

## The premise of the task is still valid

Agents writing workflows shouldn't fly blind on which models are configured. The fix shape is unchanged:

- If keys configured → list available models so the agent can pick a working one.
- If no keys configured → tell the agent how to ask the user to set one up.

The original task example said "Available models: claude-sonnet-4-0, claude-haiku, gpt-4o, gemini-2.5-flash (default)" — **plural per provider**. That detail matters: the agent should be able to see multiple models per configured provider, not just one recommended default. This is the core question Task 94 is asking.

---

## What changed since the prior handovers

### Gone

- **The `llm` library** — uninstalled by Task 158. `llm keys`, `llm models`, `llm models default`, the `_has_llm_key()` subprocess function, the "two-source key check (env + settings + llm CLI)" pattern — all dead.
- **`pflow registry describe llm`** — Task 151 removed it (`cli/main.py:27` — deprecated-commands map points users at `pflow probe`, `pflow mcp list`, `pflow mcp find`).
- **`pflow registry discover`** — same deprecation; folded into `pflow mcp find`.
- **The hardcoded `gemini-2.5-flash` default** — Task 95 removed hardcoded defaults; resolution is now `get_default_workflow_model()` (3-tier: env/settings → auto-detect → error).

### New / built since the originals

- **`PROVIDERS` registry** in `src/pflow/core/llm_providers.py` — single source of truth for the 3 canonical providers (Anthropic, OpenAI, Gemini) with structured `bare_prefixes` and `env_vars` (canonical-first tuple, including aliases like Gemini's `GOOGLE_API_KEY`).
- **`_has_provider_key(provider)`** — pure (env + settings, no subprocess). Lives in `core/llm_config.py`.
- **`_likely_env_var_for_unknown_provider(model)`** — heuristic for providers absent from the registry; returns `<PREFIX>_API_KEY`. Caller frames as "likely candidate" not authoritative.
- **`MissingApiKeyError.to_diagnostics()`** — already produces structured remediation prose for the "no key set" case (different branches for known/unknown providers post-PR-356-review).
- **`pflow settings llm show`** — exists, shows the resolution chain. Natural sibling for whatever Task 94 builds.
- **Bare-name auto-prefix** in settings CLI + adapter (`gpt-4o-mini` → `openai/gpt-4o-mini`). Whatever models Task 94 displays should be in the canonical prefixed form.
- **The lazy-import contract** — `litellm` must NOT enter `sys.modules` when `pflow.cli.main` is imported. Pinned by `tests/test_cli/test_lazy_imports.py`. Any model enumeration that imports `litellm` (e.g., to read `litellm.model_cost`) must do so inside a function body, not at module top.

### Shipped 2026-05-21 (after this braindump was written)

- **`pflow settings llm providers`** (PR #421) — curated static listing of 27 providers with env vars, OR/AND semantics, alternate-auth notes, live STATUS column, keyword filter, JSON output. Lives in `src/pflow/cli/commands/settings.py`. **This closes the "which providers have keys configured?" half of Task 94's original scope.** What remains is the "which models within a provider?" half. Treat any new listing as a sibling command (`pflow settings llm models` is the natural next slot) and mirror PR #421's shape — JSON output, keyword filter, live availability column.
- **`ensure_model_priced(model)`** in `src/pflow/core/litellm_runtime.py` (PR #424) — lazy upstream cost-map merge for models added to LiteLLM after the bundled snapshot. **Important constraint this exposes:** pflow forces `LITELLM_LOCAL_MODEL_COST_MAP=True`, so `litellm.model_cost` in a fresh pflow process is **bundled-only** (2,690 models cut 2026-04-26). Models added upstream after that date are invisible until `ensure_model_priced(name)` has been called for them. Any Task 94 enumeration that wants to surface newer models must either reuse this helper per model or bulk-merge using the same `httpx.get` + `register_model(dict)` pattern — `register_model(URL)` does NOT work under the flag (short-circuits to bundled). See `../research/model-discovery-cross-reference-from-pr-424.md` for the full landmine writeup and the three enumeration shapes (bundled-only / live / bundled+`--refresh-upstream`).

### Recently shipped that's relevant context

- The `MissingApiKeyError` UX got rebuilt: known providers get precise canonical + alias suggestions; unknown providers get a heuristic with a "likely candidate" disclaimer plus a `likely_env_var` field in `Diagnostic.context`. Task 94's "no keys configured" output should reuse the same prose pattern (or call into the same helper) — agents already filter on `category="llm_failure"`, and consistency across surfaces matters.

---

## Key insights from the prior handovers that still apply

These were the load-bearing parts of the originals; the rest was implementation detail tied to the dead architecture.

1. **Display-time check, not registry metadata cache.** API keys can change between runs — keys discovery has to happen at command time, not be baked into the registry scan. Still right.

2. **Don't enumerate all 100+ LiteLLM providers.** Show availability for the 3 in `PROVIDERS`. Other providers work (LiteLLM passes the model through), but no automatic suggestions for them. The user explicitly pushed back on registry sprawl in the original sessions and that constraint hasn't softened.

3. **The user's "don't over-engineer" framing.** From the originals: *"we only need to suggest if api key is set for 'anthropic', 'gemini', 'openai' or if pflow default model or llm default model is set, but everything else should work."* Translation: keep it minimal. Show what's available, don't try to be a model catalog.

4. **`PYTEST_CURRENT_TEST` short-circuits detection.** `_detect_default_model()` and `inject_settings_env_vars()` early-return when this env var is set (test isolation). Tests that need to exercise detection must `monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)`. **Still true** post-Task-158.

5. **The detection vs. display split** is the right architectural shape. Detection (`_has_provider_key`) is built. Display is what Task 94 adds.

---

## What the original task spec needs re-framing for

### Targets that no longer exist

The spec named `pflow registry describe llm` and `pflow registry discover`. Those are gone. Real candidates today:

| Surface | What it is | How agents read it |
|---|---|---|
| `pflow settings llm show` | CLI command, dynamic | Human-facing primarily; agents may invoke it |
| `pflow settings llm providers` | CLI command, dynamic JSON (PR #421, 2026-05-21) | Agents and humans; closes the "providers" half of Task 94 |
| `pflow guide` (`src/pflow/guide/nodes/llm.md`) | Static markdown | Loaded into agent prompts at session start |
| `pflow mcp list` / `pflow mcp find` | CLI commands, dynamic JSON | Agents calling pflow programmatically |
| MCP server resources (`src/pflow/mcp_server/resources/instructions/`) | Static markdown | Agents using pflow as MCP server |
| Hypothetical `pflow settings llm models` | Doesn't exist; would be new — natural sibling to `providers` | Both |

The "where does the model list live" question is the heart of the remaining design space and is **not fully decided** (the namespace is settled by PR #421; the listing shape is not). See open questions below.

### The model-enumeration question (new)

The original spec assumed something like `llm models list` could enumerate models per provider. With LiteLLM, the analog is `litellm.model_cost` — a dict with `litellm_provider` keys. Mechanically you can filter to `litellm_provider == "anthropic"` and get the full Anthropic list. **The question is what to do with that list.**

LiteLLM's data includes legacy generations (`claude-2.1`, `claude-instant-1.2`, `text-davinci-002`, etc.). Showing all of it as "available" is noisy and would mislead agents toward deprecated models. Three shapes worth weighing:

- **Raw LiteLLM dump per provider** — zero pflow maintenance, max noise.
- **Curated regex per provider in registry** (e.g., `r"^claude-(sonnet|opus|haiku)-4-\d+"`) — maintenance burden when generations launch, but clean output. The pattern would naturally live next to `bare_prefixes` on `ProviderInfo`.
- **Hybrid: LiteLLM list + LiteLLM's own deprecation flags** — relies on those flags being reliable; spotty in practice.

This is the most consequential design choice for Task 94 and **shouldn't be made without thinking through what an agent does with the output**.

> **Update 2026-05-21:** PR #424 forced `LITELLM_LOCAL_MODEL_COST_MAP=True` which adds a fourth axis on top of the three shapes above: "raw" enumeration of `litellm.model_cost` is **bundled-only by default** in a fresh process, not "whatever upstream has now." This means a naïve `litellm.model_cost.items()` listing silently omits any model added upstream after the bundled snapshot date (verified: `gemini/gemini-3.5-flash` is in upstream, not in bundled). The companion research file (`../research/model-discovery-cross-reference-from-pr-424.md`) works through the bundled-vs-upstream tradeoff in depth, including how a bulk-merge variant would need to be built and why `register_model(URL)` is a non-starter. Read it before locking the enumeration shape.

### Reuse over rebuild

Most of what Task 94 originally proposed building (key detection, multi-source resolution, helpful "no keys" prose) is already built. The remaining work is genuinely "wire existing detection into existing display surfaces" — a much smaller scope than the original spec implied.

> **Update 2026-05-21:** PR #421 shipped the providers half of this directly (`pflow settings llm providers`). Scope shrunk further. What's left is the models-listing sibling plus the capability metadata schema (cost, cache thresholds, reasoning support) — see the cross-reference docs in `../research/` for the schema-shape discussion.

---

## Settled patterns to follow

These follow from the current architecture and don't need re-deciding:

1. **Iterate `PROVIDERS`, call `_has_provider_key(p.name)` per entry.** Pure, fast, no subprocess. (PR #421 follows this pattern.)
2. **Models displayed in canonical prefixed form** (`anthropic/claude-sonnet-4-5`, not `claude-sonnet-4-5`). LiteLLM expects the prefix; bare names auto-prefix only at write-time.
3. **Lazy-import `litellm`** if you read `litellm.model_cost` for enumeration. The lazy-import contract test will fail if you import at module top.
4. **Fresh detection every command run.** `_has_provider_key` is microseconds; no caching needed.
5. **Reuse `MissingApiKeyError.to_diagnostics()`'s remediation patterns** for the "no keys" case so output is consistent across surfaces. Or extract a shared helper.
6. **Use `ensure_model_priced(model)` (PR #424) — not `litellm.register_model(URL)`** — for any path that touches cost data for upstream-only models. The URL form is silently a no-op under `LITELLM_LOCAL_MODEL_COST_MAP=True`; the helper does the `httpx.get` + dict merge correctly. Reference: `src/pflow/core/litellm_runtime.py::ensure_model_priced`.
7. **Mirror PR #421's CLI shape** for any new `pflow settings llm ...` subcommand: keyword-substring filter, `--output-format json`, live status column from `inject_settings_env_vars()` (so keys stored via `pflow settings set-env` reflect without a shell `export`).

---

## Open design questions (do not resolve until ready to implement)

1. **What's the primary surface?** Namespace is settled by PR #421 (`pflow settings llm ...`). The remaining sub-question is the shape of the models listing: `pflow settings llm models [provider]`? An extension of `pflow settings llm show`? Some combination? PR #421's `providers` subcommand is the natural template — same option set, mirror the JSON schema patterns. MCP-server-mode surface is still separate (Q #4).

2. **Filter LiteLLM's per-provider list (curated regex) vs. dump it raw?** This is the maintenance-vs-noise tradeoff. The curation case argues that pflow already updates the registry when a new generation launches; the raw case argues "let LiteLLM be the source." **Update 2026-05-21:** PR #424's forced `LITELLM_LOCAL_MODEL_COST_MAP=True` adds a "raw from where?" axis (bundled snapshot vs. live upstream). See `../research/model-discovery-cross-reference-from-pr-424.md` for the bundled-vs-upstream tradeoff. The three shapes worth weighing now are: bundled-only / live-fetch-per-listing / bundled-default + `--refresh-upstream` flag.

3. **Should `pflow guide` go dynamic, or stay static?** Currently `src/pflow/guide/nodes/llm.md` is static markdown loaded into every agent session. Baking model lists in is bad (prompt bloat, stale). Pointing at a runnable command is good. PR #421 took the pointer approach (added a one-line breadcrumb to `pflow settings llm providers`); whether the models-listing analog gets the same treatment is the open piece.

4. **MCP server exposure — separate tool, expanded node metadata, or static instructions?** Agents in MCP-server mode can't always shell out, so a runnable command alone isn't enough.

5. **Lift `default_model` (and possibly `current_model_patterns`) onto `ProviderInfo`?** Currently the per-provider recommended default is hardcoded inside `_detect_default_model()`. Lifting consolidates registry knowledge; alternative is a separate constant alongside `PROVIDERS`. Both defensible. **Update 2026-05-21:** new concrete evidence for "lift to `ProviderInfo` with an explicit value, not a heuristic" — the Gemini family now has 4+ Flash generations live in the registry simultaneously, with `gemini-3.5-flash` priced at 5× the input cost and 3.6× the output cost of `gemini-2.5-flash`. A "latest version wins" heuristic would silently inflate users' bills. See the research file for the comparison table.

6. **Show legacy generations behind a `--all` flag, or hide them entirely?** Tied to the filter question.

7. **(New, 2026-05-21) What capability metadata does each row carry?** PR #421's `providers` listing carries env-var info only. Models listing has many more candidate columns: cost (input/output/cache-read), context window, cache thresholds, `supports_prompt_caching`, `supports_reasoning` (load-bearing for the new "thinking by default" generation — see research file), `supports_tool_choice`, etc. Inclusion criterion = "decision-relevant for an agent picking a model." Cross-reference doc `cache-threshold-cross-reference-from-task-159.md` proposes one schema shape; the PR-424 cross-reference adds a `supports_reasoning` recommendation.

The user has previously declined to widen the registry beyond Anthropic/OpenAI/Gemini for "anything LiteLLM speaks." That constraint is likely still in force; check before assuming otherwise.

---

## Test traps worth knowing

- **`PYTEST_CURRENT_TEST` short-circuits `_detect_default_model()` and `inject_settings_env_vars()`.** `monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)` is the workaround.
- **The autouse `mock_llm_client` fixture in `tests/conftest.py`** patches `pflow.core.llm_client.complete` for any test whose path doesn't contain `/llm/` (it's a substring skip). Files at `tests/test_nodes/test_llm/test_*.py` *do* get the mock applied. If a Task 94 test needs the real adapter for some reason, patch `litellm.completion` one layer below — see `TestAdapterSealContract` for the pattern.
- **The dev environment has real keys configured.** When testing "no keys" behavior, you must mock `_has_provider_key()` or set `PROVIDER_ENV_VARS` to empty.
- **`get_default_llm_model()` caches.** Call `clear_model_cache()` between tests that change key state.

---

## Files that actually matter today

| Path | Why |
|---|---|
| `src/pflow/core/llm_providers.py` | The registry — `PROVIDERS`, `ProviderInfo`, `detect_provider`, `extract_provider_prefix` |
| `src/pflow/core/llm_config.py` | `_has_provider_key`, `get_default_workflow_model`, `inject_settings_env_vars`, `get_llm_setup_help` |
| `src/pflow/core/litellm_runtime.py` | (PR #424) `ensure_model_priced(model)` + the upstream-merge contract. Reuse for any cost-data path; bulk-merge variant for Task 94 lives here if shape #3 is chosen |
| `src/pflow/core/exceptions.py` | `MissingApiKeyError` + `_likely_env_var_for_unknown_provider` (reuse the prose patterns) |
| `src/pflow/cli/commands/settings.py` | `pflow settings llm show` and `pflow settings llm providers` (PR #421) live here — host for new `models` subcommand. Read the `providers` impl as a template |
| `src/pflow/guide/nodes/llm.md` | The agent-facing static guide for the LLM node — has the PR #421 breadcrumb to `pflow settings llm providers`; models-listing breadcrumb is the symmetric add |
| `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` | MCP-server-mode agent instructions — same gap |
| `src/pflow/cli/commands/mcp.py` (`list`/`find`) | Programmatic node discovery |
| `tests/test_core/test_llm_config_provider_detection.py` | Existing key-detection tests; template for new ones |
| `tests/test_core/test_llm_providers.py` | Registry contract tests |
| `tests/test_core/test_litellm_runtime.py` | (PR #424) Templates for upstream-merge tests — no-op-on-bundled, fetch-on-miss, idempotency, silent-failure, thread-safety |

---

## Manual verification commands (still useful as written)

```bash
# Set a test key in settings
uv run pflow settings set-env OPENAI_API_KEY "test-key"

# Check detection works
uv run python -c "
from pflow.core.llm_config import _has_provider_key, clear_model_cache
clear_model_cache()
print('anthropic:', _has_provider_key('anthropic'))
print('openai:', _has_provider_key('openai'))
print('gemini:', _has_provider_key('gemini'))
"

# Clean up
uv run pflow settings unset-env OPENAI_API_KEY

# Current resolution-chain display (sibling for whatever Task 94 builds)
uv run pflow settings llm show

# (2026-05-21) Providers listing — read the impl as a template for the models sibling
uv run pflow settings llm providers
uv run pflow settings llm providers --output-format json
uv run pflow settings llm providers ai  # keyword filter

# (2026-05-21) End-to-end model probe — natural verification sibling once Task 94 lists models
uv run pflow probe llm model=gemini/gemini-2.5-flash prompt="say pong"
```

---

## What to do first when starting Task 94

1. **Re-read `task-94.md` with the current architecture in mind.** The "Affected Commands" section needs updating before implementation; the "Implementation Considerations" bullets reference dead infrastructure.
2. **Read the two research files** before locking design choices:
   - `../research/cache-threshold-cross-reference-from-task-159.md` — proposed schema, filter set, and the bidirectional cross-reference Task 159 wants from Task 94.
   - `../research/model-discovery-cross-reference-from-pr-424.md` — the bundled-vs-upstream architecture, the `register_model(URL)` landmine, the `supports_reasoning` schema gap, and updated open-question evidence.
3. **Reach an answer on open question #2 (filter vs raw, now with bundled-vs-upstream as a third axis) and #7 (capability metadata columns)** before writing any code. These shape the schema and the implementation surface.
4. **Confirm the user's appetite for adding to `ProviderInfo`** (open question #5) — small change but it commits the registry to growing. The 2026-05-21 evidence on Gemini Flash generations is a strong argument for explicit `default_model` over auto-detection.
5. **Update `task-94.md` to the locked-in design, then implement.** Mirror PR #421's `pflow settings llm providers` shape for the new `models` subcommand (same options, same JSON schema patterns, same status-column UX).

The work is small (~50–120 lines of production code now that PR #421 closed the providers half) once the design is settled. The hard part is settling the design — and that's exactly where the original task's framing has aged out.
