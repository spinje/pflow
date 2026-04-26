# Task 94 starting context (post-Task-158)

**Date**: 2026-04-26. **Supersedes**: the two prior handover memos (`task-94-handover-01.md` and `task-94-handover-02.md`), which described an architectural state that no longer exists. Both were written in the `llm`-library era; Task 158 replaced that library with LiteLLM via a pflow-owned adapter, which deletes most of the assumptions those memos relied on.

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
| `pflow guide` (`src/pflow/guide/nodes/llm.md`) | Static markdown | Loaded into agent prompts at session start |
| `pflow mcp list` / `pflow mcp find` | CLI commands, dynamic JSON | Agents calling pflow programmatically |
| MCP server resources (`src/pflow/mcp_server/resources/instructions/`) | Static markdown | Agents using pflow as MCP server |
| Hypothetical `pflow settings llm models` | Doesn't exist; would be new | Both |

The "where does the model list live" question is the heart of the design space and is **not decided**. See open questions below.

### The model-enumeration question (new)

The original spec assumed something like `llm models list` could enumerate models per provider. With LiteLLM, the analog is `litellm.model_cost` — a dict of 2,678 entries with `litellm_provider` keys. Mechanically you can filter to `litellm_provider == "anthropic"` and get the full Anthropic list. **The question is what to do with that list.**

LiteLLM's data includes legacy generations (`claude-2.1`, `claude-instant-1.2`, `text-davinci-002`, etc.). Showing all of it as "available" is noisy and would mislead agents toward deprecated models. Three shapes worth weighing:

- **Raw LiteLLM dump per provider** — zero pflow maintenance, max noise.
- **Curated regex per provider in registry** (e.g., `r"^claude-(sonnet|opus|haiku)-4-\d+"`) — maintenance burden when generations launch, but clean output. The pattern would naturally live next to `bare_prefixes` on `ProviderInfo`.
- **Hybrid: LiteLLM list + LiteLLM's own deprecation flags** — relies on those flags being reliable; spotty in practice.

This is the most consequential design choice for Task 94 and **shouldn't be made without thinking through what an agent does with the output**.

### Reuse over rebuild

Most of what Task 94 originally proposed building (key detection, multi-source resolution, helpful "no keys" prose) is already built. The remaining work is genuinely "wire existing detection into existing display surfaces" — a much smaller scope than the original spec implied.

---

## Settled patterns to follow

These follow from the current architecture and don't need re-deciding:

1. **Iterate `PROVIDERS`, call `_has_provider_key(p.name)` per entry.** Pure, fast, no subprocess.
2. **Models displayed in canonical prefixed form** (`anthropic/claude-sonnet-4-5`, not `claude-sonnet-4-5`). LiteLLM expects the prefix; bare names auto-prefix only at write-time.
3. **Lazy-import `litellm`** if you read `litellm.model_cost` for enumeration. The lazy-import contract test will fail if you import at module top.
4. **Fresh detection every command run.** `_has_provider_key` is microseconds; no caching needed.
5. **Reuse `MissingApiKeyError.to_diagnostics()`'s remediation patterns** for the "no keys" case so output is consistent across surfaces. Or extract a shared helper.

---

## Open design questions (do not resolve until ready to implement)

1. **What's the primary surface?** A new `pflow settings llm models [provider]` subcommand? An extension of `pflow settings llm show`? A standalone `pflow models`? An MCP-tool-only thing? A static `pflow guide` section? Some combination?

2. **Filter LiteLLM's per-provider list (curated regex) vs. dump it raw?** This is the maintenance-vs-noise tradeoff. The curation case argues that pflow already updates the registry when a new generation launches; the raw case argues "let LiteLLM be the source."

3. **Should `pflow guide` go dynamic, or stay static?** Currently `src/pflow/guide/nodes/llm.md` is static markdown loaded into every agent session. Baking model lists in is bad (prompt bloat, stale). Pointing at a runnable command is good. But that means the guide tells the agent to *run* `pflow settings llm models` — is that the agent UX you want?

4. **MCP server exposure — separate tool, expanded node metadata, or static instructions?** Agents in MCP-server mode can't always shell out, so a runnable command alone isn't enough.

5. **Lift `default_model` (and possibly `current_model_patterns`) onto `ProviderInfo`?** Currently the per-provider recommended default is hardcoded inside `_detect_default_model()`. Lifting consolidates registry knowledge; alternative is a separate constant alongside `PROVIDERS`. Both defensible.

6. **Show legacy generations behind a `--all` flag, or hide them entirely?** Tied to the filter question.

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
| `src/pflow/core/exceptions.py` | `MissingApiKeyError` + `_likely_env_var_for_unknown_provider` (reuse the prose patterns) |
| `src/pflow/cli/commands/settings.py` | `pflow settings llm show` lives here — likely the host for new `models` subcommand if that's the chosen surface |
| `src/pflow/guide/nodes/llm.md` | The agent-facing static guide for the LLM node — currently has zero info on key/model availability |
| `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` | MCP-server-mode agent instructions — same gap |
| `src/pflow/cli/commands/mcp.py` (`list`/`find`) | Programmatic node discovery |
| `tests/test_core/test_llm_config_provider_detection.py` | Existing key-detection tests; template for new ones |
| `tests/test_core/test_llm_providers.py` | Registry contract tests |

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
```

---

## What to do first when starting Task 94

1. **Re-read `task-94.md` with the current architecture in mind.** The "Affected Commands" section needs updating before implementation; the "Implementation Considerations" bullets reference dead infrastructure.
2. **Reach an answer on open question #1 (primary surface) and #2 (filter vs raw)** before writing any code. These are coupled and they shape everything else.
3. **Confirm the user's appetite for adding to `ProviderInfo`** (open question #5) — this is a small change but it commits the registry to growing.
4. **Update `task-94.md` to the locked-in design, then implement.**

The work is small (~80–150 lines of production code) once the design is settled. The hard part is settling the design — and that's exactly where the original task's framing has aged out.
