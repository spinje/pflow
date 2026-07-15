# Task 94: Show Available LLM Models Based on Configured API Keys

> **Spec refreshed 2026-07-15 against main (session-06).** The original January spec is SUPERSEDED
> — it targeted `pflow registry describe llm` (that whole surface was removed in Task 151), assumed
> "no key detection exists" (false — `pflow settings llm providers` shipped in PR #421), and built
> on Simon Willison's `llm` library (replaced by LiteLLM in Task 158). This version was designed
> from ground-truth verification + a full design discussion; see Design Decisions for what changed
> and why. The `research/` files predate the design lock — treat them as evidence (models data,
> LiteLLM landmines), not as the design.

## Description

Give AI agents (and users) a way to discover which LLM models they can actually use, based on the
API keys they have configured. A new `pflow settings llm models` command lists models per provider;
the `llm` node's agent-facing description points at it. This is discovery only — no change to how
the `llm` node runs.

## Status

not started

## Priority

medium

## Problem

When an agent looks at the `llm` node it sees a bare `model: str` parameter — no list of models, no
sense of what exists or what a user's keys allow. So when a user asks their agent "which model
should I use?", the agent can't answer: it either guesses a model name or silently takes the smart
default, and cannot advise on alternatives.

The smart default (auto-detect a configured provider) already prevents *crashes* from an unset key.
The unmet need is **choice-support**: an agent cannot see the menu, so it cannot help the user pick.
Note what already exists and is NOT the gap: `pflow settings llm providers` (PR #421) answers "which
*providers* have keys?" — this task answers the unbuilt other half, "which *models* can I use?"

## Solution

A `pflow settings llm models` command, built as a sibling to `pflow settings llm providers`, that
enumerates models per provider from LiteLLM data, conditioned on configured keys, with graceful
degradation and self-guiding output.

Command surface:
```
pflow settings llm models [KEYWORDS…] [--output-format text|json]
```

- **No keyword** → the providers you have keys configured for, each with its models. Multi-provider
  views cap each provider's list and point to the full list.
- **Keyword(s)** → substring(s) matched across provider names AND model names (AND-combined,
  `nargs=-1` like `list`/`mcp list`). `models anthropic` scopes to that provider (even without a
  key); `models opus` finds matching models; `models fireworks_ai llama` narrows within a provider.
- **Network-first, offline fallback:** fetch the current LiteLLM model data over the network; if
  that fails, fall back to the bundled snapshot. Always label the source.
- **Self-guiding:** every view tells the reader how to go further (see all of a provider, inspect an
  unconfigured provider, see providers+keys, or use an unlisted model directly).

Plus a small altered surface: the `llm` node's agent-facing description (`pflow mcp describe llm` /
`pflow guide` node topic) gains a **network-free** pointer to `pflow settings llm models` (or, when
no keys are set, the setup hint).

## Design Decisions

Locked with the user during the session-06 design discussion:

- **Choice-support, not crash-avoidance.** The task's live purpose is helping an agent *choose* a
  model, which the smart default does not address. Reframed from the original "stop agents picking
  unavailable models."
- **Enumeration, NOT curation, in v1.** No hand-written "use X for Y" guidance. Pure enumeration of
  real, valid model strings. Rejected curation for v1 because it needs manual upkeep and doesn't
  scale past the big-3; a curated guidance layer is a possible v2.
- **Completeness by pointing, not enumerating everything.** For providers we can't say anything
  useful about, we don't hide them and we don't dump a full ranked catalog — we surface valid model
  strings + an escape hatch ("any LiteLLM model works, pass `provider/model`"). The two jobs are
  distinct: *guidance* can't be auto-generated (deferred), *reachability* is mechanical (this task).
- **Network by default, offline-bundled fallback** (user ruling, overriding an initial
  offline-default proposal). Rationale: a model absent from the bundled snapshot still *runs* fine
  (the cost map is pricing metadata, not an allowlist — you just lose cost telemetry until pricing
  backfills), so an offline-only list would under-report usable models. Network-first gets current
  data; fallback preserves the command when the feed is down; the source label keeps it honest.
  This is a deliberate, scoped network call in an explicit command — NOT in any passive/hot path.
- **No network in the passive node-describe.** The inline hint is a network-free pointer to the
  command; the network enumeration lives ONLY in the explicit `models` command. Keeps
  `mcp describe llm` / guide rendering fast.
- **Chat-mode filtering is mandatory.** Raw `litellm.models_by_provider` mixes chat with
  image/embedding/audio/rerank/pricing-pseudo entries (e.g. openai raw 213 → chat 92; a naive list
  would offer DALL-E as a chat model). Filter to `mode == "chat"`.
- **Single-provider views are complete; only multi-provider views cap.** Drilling into one provider
  IS the "see all" — it shows the full list (long ones like fireworks' ~270 are then narrowed with
  a keyword). This resolves the dead-end where a capped hint pointed at a command that also capped.
- **Command shape mirrors `pflow settings llm providers`** — positional keyword(s) + `--output-format`,
  no invented flags. Explicitly REJECTED: a `--filter` flag (no such flag exists anywhere in the CLI
  — filtering is always positional) and an `--all` flag (naming a provider already inspects
  unconfigured ones; "dump every provider's models" is thousands of lines and not a useful view).
- **Status label reads as a state, not a command:** `(configured)` / `(no key — set <VAR>)`. The
  env var name appears only where you'd act on it (key missing). Rejected `(ANTHROPIC_API_KEY: set)`
  (cramped) and `key set` (reads as an imperative).
- **Cost column: out of v1.** It's data, not curation, and genuinely aids choosing — but deferred to
  keep v1 minimal. A possible v2 addition.

## Dependencies

- **Task 80** (API key management via `pflow settings set-env`/`list-env`): DONE — the env-key
  store this reads is in place (`settings.py`, `llm_config.inject_settings_env_vars`).
- **PR #421** (`pflow settings llm providers` + the `_LLM_PROVIDERS` table): MERGED — the sibling to
  mirror and the provider→env-var/status source to reuse.
- **PR #424** (`ensure_model_priced` upstream-fetch pattern): MERGED — the reference for the
  network fetch (see Implementation Notes).

No blocking work remains; this is buildable now.

## Requirements

### Command surface
- `pflow settings llm models [KEYWORDS…] [--output-format text|json]` exists under the
  `settings llm` group, registered like `providers`.
- `KEYWORDS` is `nargs=-1`; each is a case-insensitive substring; multiple keywords AND-combine; a
  keyword matches if it is contained in a provider name OR a model id.
- With no keyword, output is scoped to providers whose keys are configured (per the same detection
  `settings llm providers` uses).
- Naming a provider (a keyword that matches a provider name) shows that provider's models **even if
  its key is not configured**, marked `(no key — set <VAR>)`.
- When zero providers are configured and no keyword is given, output is the no-keys guidance (how to
  set a key + pointer to `providers`), not an empty list or error.

### Enumeration & filtering
- Models come from LiteLLM (`models_by_provider` / `model_cost`), filtered to `mode == "chat"`.
- Non-chat entries (image/embedding/audio/rerank/pricing-tier pseudo-models) never appear.
- Model ids are the strings a user would pass to the `llm` node's `model` param (provider-prefixed
  where LiteLLM uses that form, e.g. `groq/llama-3.3-70b-versatile`).

### Network + fallback
- Default behavior fetches current LiteLLM model data over the network within a bounded timeout.
- On any fetch failure (timeout, non-200, parse error), fall back to the bundled snapshot WITHOUT
  raising — the command still returns a usable list.
- Output labels the source: live vs. offline-snapshot; the offline label states it may omit models
  newer than the bundled LiteLLM version.
- The network fetch does NOT run in `pflow mcp describe llm`, `pflow guide`, or any non-`models`
  path.

### Capping & guidance (self-guiding output)
- In a **multi-provider** view, each provider's model list is capped at a fixed N; a capped provider
  shows the true total and points to its full list: `see all <N>: pflow settings llm models <provider>`.
- A **single-provider** view (result scoped to one provider) shows the complete list, uncapped.
- A long single-provider view guides narrowing: `narrow: pflow settings llm models <provider> <keyword>`.
- Every view offers the next steps: inspect a not-yet-configured provider (`models <name>`), see
  providers+keys (`pflow settings llm providers`), and the escape hatch that any LiteLLM model works
  via `provider/model` even if unlisted.

### JSON output
- `--output-format json` emits: `source` (`"live"`/`"offline"`) and a `providers` array; each entry
  carries `name`, `env_vars`, `status` (`"set"`/`"-"`), `model_count`, and `models` (the filtered
  ids). Capping is a text-presentation concern only — JSON lists all matched models.

### Altered: `llm` node description
- The `llm` node's agent-facing interface text (source of `pflow mcp describe llm` / guide node
  topic) replaces the bare `model: str` help with a network-free hint: when keys are configured,
  name the configured providers and point to `pflow settings llm models`; when none are, give the
  `set-env` setup hint and point to `pflow settings llm providers`.

### Unchanged (must not regress)
- `settings set-env` / `unset-env` / `list-env`, `settings llm show`, `settings llm providers`, the
  `llm` node's runtime model resolution, and smart-default selection are untouched.
- Optional: a single `see models: pflow settings llm models` cross-reference line may be added to
  the `providers` footer (nice-to-have, not required).

## Implementation Notes

- **Sibling to copy:** `llm_providers` in `src/pflow/cli/commands/settings.py` (the `_LLM_PROVIDERS`
  table, `_provider_status`, `_format_env_vars`, the `inject_settings_env_vars()` call before status
  checks, text+JSON branches). Mirror its structure.
- **Provider→env-var/status** comes from the existing `_LLM_PROVIDERS` table + `_provider_status`;
  do not build a second detector. Canonical runtime provider metadata is `PROVIDERS` /
  `detect_provider()` in `src/pflow/core/llm_providers.py`.
- **Network fetch LANDMINE (from `research/model-discovery-cross-reference-from-pr-424.md`):** pflow
  forces `LITELLM_LOCAL_MODEL_COST_MAP=True`, so `litellm.register_model(URL)` short-circuits to the
  bundled backup and does nothing. The working pattern (shipped in
  `src/pflow/core/litellm_runtime.py::ensure_model_priced`, PR #424) is: `httpx.get(
  litellm.model_cost_map_url)` → parse/validate → set `litellm.suppress_debug_info = True` →
  `litellm.register_model(dict)`. Reuse that pattern for the bulk fetch; then read models_by_provider
  / model_cost. On failure, use the already-loaded bundled data.
- **Chat filter:** for each candidate model, its mode is `litellm.model_cost.get(model, {}).get("mode")`
  (fall back to the bare-name key for prefixed ids). Keep only `"chat"`.
- **Verified data shape (offline probe, session-06):** `litellm.models_by_provider` is a dict of
  provider → **set** of model ids (89 providers bundled). Sort for display. Chat-filter counts seen:
  anthropic 23, groq 11, openai 92, fireworks_ai 270 — so the cap + single-provider-uncapped rule is
  load-bearing for the aggregators.
- **Node-describe source:** the `model: str` help text lives in the `LLMNode` docstring Interface
  block (`src/pflow/nodes/llm/llm.py`, ~L948); that text feeds `mcp describe llm` / guide via the
  registry context builder. Keep the hint static (no key lookup that hits the network).

## Verification

- **No keys:** with no configured providers, `models` prints the setup guidance (not empty/no error);
  exit 0.
- **Configured providers:** with one/multiple keys set, `models` lists those providers' chat models,
  each labeled `(configured)`; multi-provider view caps and shows `see all N: … <provider>`.
- **Single provider full list:** `models anthropic` shows all anthropic chat models uncapped;
  `models fireworks_ai` shows the long list and a narrow hint; `models fireworks_ai llama` narrows.
- **Unconfigured inspect:** `models openai` with no OpenAI key shows its models marked
  `(no key — set OPENAI_API_KEY)`.
- **Keyword across fields:** `models opus` returns matching models across configured providers;
  `models` with a nonsense keyword returns an empty-but-guided result, not a crash.
- **Chat filter:** output for `openai` contains no image/embedding entries (e.g. no `dall-e`,
  no `…/embedding…`).
- **Network fallback:** with the fetch forced to fail (patched/timeout), the command still returns
  the bundled list and labels the source as offline; no exception surfaces to the user.
- **No network in describe:** `pflow mcp describe llm` and `pflow guide <llm-topic>` render the hint
  without making a network call (assert no fetch in that path).
- **JSON:** `--output-format json` parses; carries `source`, and per-provider `status`, `env_vars`,
  `model_count`, `models`; lists all matched models (no cap in JSON).
- **Real-surface (Definition of done):** run the actual CLI — `uv run pflow settings llm models`,
  `… models anthropic`, `… models openai`, `… --output-format json` — and `uv run pflow mcp describe
  llm` — and confirm the outputs and guidance rungs match this spec.
- **No regression:** `settings llm providers` / `show`, `set-env`/`list-env`, and `llm` node runtime
  behavior unchanged.

## References

- Sibling command + provider table/status: `src/pflow/cli/commands/settings.py` (`llm_providers`,
  `_LLM_PROVIDERS`, `_provider_status`, `_format_env_vars`).
- Runtime provider metadata: `src/pflow/core/llm_providers.py` (`PROVIDERS`, `detect_provider`).
- Network-fetch pattern + landmine: `src/pflow/core/litellm_runtime.py` (`ensure_model_priced`);
  `research/model-discovery-cross-reference-from-pr-424.md` (evidence, not design).
- Node-describe text: `src/pflow/nodes/llm/llm.py` (LLMNode Interface docstring, model param).
- Model resolution chain / key injection: `src/pflow/core/llm_config.py`.
- CLI JSON-flag convergence (why `--output-format`, not `--json`): issue #528.
- In-task prior context (pre-lock): `starting-context/`, `research/`.
