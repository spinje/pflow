# Task 94: Show Available LLM Models Based on Configured API Keys

> **Spec refreshed 2026-07-15 against main (session-06).** The original January spec is SUPERSEDED
> — it targeted `pflow registry describe llm` (that whole surface was removed in Task 151), assumed
> "no key detection exists" (false — `pflow settings llm providers` shipped in PR #421), and built
> on Simon Willison's `llm` library (replaced by LiteLLM in Task 158). This version was designed
> from ground-truth verification + a full design discussion; see Design Decisions for what changed
> and why. The `research/` files predate the design lock — treat them as evidence (models data,
> LiteLLM landmines), not as the design.
>
> **Refreshed 2026-09-29 against main `848cc7c8` (session-09 freshness check — litellm 1.86.1,
> one live upstream fetch).** Citations corrected in place (sibling arity, catalog counts, the
> enumeration mechanism, `llm.py` line, the three describe renderers, the `n/a` status); design
> gaps the check found are stated below as **RESOLVE AT START** constraints; the user's rulings are
> in the Decision ledger.
>
> **SPEC battery folded 2026-09-30** (four Opus lenses — architecture-fit, review-plan, agent-ux,
> silent-failures; ledger `scratchpads/session-09/task-94-spec-battery.md`, local): provider universe
> (user ruling A), keyword semantics, callable-string rule, JSON shape, test-harness traps,
> verification rewritten so every bullet can fail. Dependencies #606 and #654 added.

## Description

Give AI agents (and users) a way to discover which LLM models they can actually use, based on the
API keys they have configured. A new `pflow settings llm models` command lists models per provider;
the `llm` node's agent-facing description points at it. This is discovery only — no change to how
the `llm` node runs.

## Status

done

## Completed

2026-09-30

## Priority

medium

## Roadmap

next

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

- **No keyword** → an overview of the providers you have keys configured for, each with its
  models — the ONLY capped view; each capped provider points to its complete list.
- **Keyword(s)** (AND-combined, `nargs=-1` like `list`/`mcp list`) → a keyword that exactly equals a
  provider name selects that provider (even without a key); every other keyword filters model ids
  (substring), within the selected provider or, when none is named, within configured providers.
  `models anthropic` = anthropic's complete list; `models opus` = matching models across your
  configured providers; `models fireworks_ai llama` narrows within a provider. Keyword views are
  never capped.
- **Network-first, offline fallback:** fetch the current LiteLLM model data over the network; if
  that fails, fall back to the bundled snapshot. Always label the source.
- **Self-guiding:** every view tells the reader how to go further (see all of a provider, inspect an
  unconfigured provider, see providers+keys, see the default pflow resolves, or use an unlisted
  model directly).

Plus a small altered surface: the `llm` node's `model` param help (rendered by `pflow mcp describe
llm`, `pflow guide llm` and the MCP-server `registry_describe` tool) gains ONE static,
network-free pointer line (Decision ledger).

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
- **Mode filtering is mandatory, and the list only offers callable strings.** The LiteLLM catalog
  mixes chat with image/embedding/audio/rerank entries (openai on bundled 1.86.1: 212 catalog
  entries → 98 `mode == "chat"`; a naive list would offer DALL-E as a chat model), and some
  chat-mode entries are pricing keys, not model strings (`ft:*` fine-tune templates, pricing-tier
  pseudo-entries such as `together-ai-4.1b-8b`, `openai/container`). Which modes count: Decision
  ledger.
- **Only the no-keyword overview caps; every keyword view is complete** (refreshed 2026-09-29 —
  same intent as the session-06 lock "drilling into one provider IS the see-all", corrected because
  substring-matching provider names made `models anthropic` a multi-provider, capped view whose
  "see all" pointed back at itself; the `mcp list` precedent: overview = sample, keyword = full).
  Long provider lists (fireworks ~244 chat bundled, ~311 upstream) are narrowed with a keyword.
- **Command shape follows the CLI's filter conventions** — positional keywords (`nargs=-1`, the
  `list` / `mcp list` shape; `providers` itself takes ONE optional keyword) + `--output-format`
  like `providers`, no invented flags. JSON is an object (`{source, providers}`) rather than
  `providers`' bare array, because it must carry `source`. Explicitly REJECTED: a `--filter` flag (no such flag exists anywhere in the CLI
  — filtering is always positional) and an `--all` flag (naming a provider already inspects
  unconfigured ones; "dump every provider's models" is thousands of lines and not a useful view).
- **Status label reads as a state, not a command:** `(configured)` / `(no key — set <VAR>)`. The
  env var name appears only where you'd act on it (key missing). Rejected `(ANTHROPIC_API_KEY: set)`
  (cramped) and `key set` (reads as an imperative).
- **Cost column: out of v1.** It's data, not curation, and genuinely aids choosing — but deferred to
  keep v1 minimal. A possible v2 addition; it would turn the JSON `models` items from strings into
  objects — a planned clean cutover of the JSON oracles and docs, not a reason to ship objects now.

## Decision ledger (session-09 rulings)

User's governing lens, verbatim: *"We should prioritize simplicity of the FINAL code, not how easy
it is to get there. When in doubt we should ask ourselves whats the right solution that the top 10%
of codebases similar to this one would implement, have we considered it yet? What this doesnt mean
is overfitting to "top 10% of codebases" and overengineering, this is about more simple code that is
optimized for AI agents to understand and add features to."*

- **DECIDED 2026-09-29 (user) — the `llm` node hint is ONE static line**, identical in all three
  describe surfaces, e.g. `List usable models: pflow settings llm models · no key? pflow settings
  llm providers`. No key-conditional text, no render-time injection. Supersedes the key-conditional
  wording under "Altered: llm node description".
- **DECIDED 2026-09-29 (user) — no default-model special case.** The list is a plain catalog view;
  pflow's resolved default is NOT injected into it. One of the self-guiding rungs points at `pflow
  settings llm show`, which already prints the resolved default (`settings.py` `llm show`).
- **DECIDED 2026-09-29 (main orchestrator, 2/5) — which modes count:** a mode counts iff the `llm`
  node can actually call a model of that mode (the list's contract is "strings you can pass to
  `model`"). `chat` counts. VERIFY AT START: probe one `mode == "responses"` model (e.g.
  `gpt-5-pro`) through pflow's adapter; include `responses` iff it runs, else leave it out and say
  so in the escape-hatch line.
  **RESOLVED 2026-09-30 (planner, applying this rule):** `chat` and `responses` count — a
  `responses` model runs through pflow's adapter. `completion` does not: no completion-mode model
  reachable through the adapter still runs (the providers retired them), so it cannot be shown to be
  callable.

- **DECIDED 2026-09-30 (user, option A of the SPEC battery's convergent finding) — the provider
  universe is the curated provider table** (the ONE table #606 consolidates). The catalog has three
  namespaces that do not line up — table names (27), catalog `litellm_provider` groups (109
  bundled; e.g. `vertex_ai-language-models`, `bedrock_converse`, `cohere_chat`), and the routing
  prefix LiteLLM actually accepts — so each table row declares (a) the catalog groups it covers
  (e.g. `bedrock ← bedrock, bedrock_converse`; `vertex_ai ← vertex_ai, vertex_ai-*`; `cohere ←
  cohere_chat`) and (b) the routing prefix used to build the displayed id. Providers outside the
  table are reachable only through the escape-hatch line. A test asserts every listed id routes to
  its provider (`litellm.get_llm_provider` — in TESTS only: on `github_copilot/*` it prints a
  device-login prompt to stdout and blocks, so it never runs across the catalog at runtime).
  Rejected: B — exact-name matching with the gaps stated (vertex 8 of ~115, cohere none, bedrock
  missing its 120 Converse models).
- **DECIDED 2026-09-30 (main orchestrator, 2/5, SPEC-battery fold) — keyword semantics:** exact
  provider name selects; other keywords filter model ids within the selection (else within
  configured providers); only the no-keyword overview caps (Design Decisions).

## Dependencies

- **Task 80** (API key management via `pflow settings set-env`/`list-env`): DONE — the env-key
  store this reads is in place (`settings.py`, `llm_config.inject_settings_env_vars`).
- **PR #421** (`pflow settings llm providers`): MERGED — the sibling to mirror (its table is now
  `CURATED_PROVIDERS`, see #606).
- **PR #424** (`ensure_model_priced` upstream-fetch pattern): MERGED — the reference for the
  network fetch (see Implementation Notes).

- **#606** (dual provider tables → one): MERGED 2026-09-30 (PR #661) — the table is now
  `CURATED_PROVIDERS` (frozen `CuratedProvider` rows) in `core/llm_providers.py`, registry rows
  derived from `PROVIDERS`; status follows the runtime resolver; byte-exact `providers` snapshot
  tests exist. This task adds a `catalog_groups` field to `CuratedProvider`; the routing prefix is
  `<name>/` for every row, so it is derived, not a field.
- **#654** (upstream catalog merge re-keyed entries): MERGED 2026-09-30 (PR #662) — both upstream
  paths now go through `_merge_upstream_catalog` (`core/litellm_runtime.py`): exact-key writes into
  `model_cost`, LiteLLM's lookup caches invalidated, `add_known_models` for routing; bundled entries
  never change; `import_litellm()` sets `suppress_debug_info`. "live" = bundled + upstream-only
  entries under their exact keys.

Buildable once both merge and the planner's verify-at-start probes are done.

## Requirements

### Command surface
- `pflow settings llm models [KEYWORDS…] [--output-format text|json]` exists under the
  `settings llm` group, registered like `providers`.
- `KEYWORDS` is `nargs=-1`, case-insensitive, AND-combined. A keyword that exactly equals a
  provider name (curated table) selects that provider; every other keyword is a substring filter on
  model ids, applied within the selected provider or, when none is named, within configured
  providers.
- With no keyword, output is scoped to providers whose keys are configured (per the same detection
  `settings llm providers` uses). Local (`n/a`) providers are not in this view — there is no key to
  detect, and a catalog list says nothing about which models a local server has pulled; they are
  listed by name (`models ollama`), and the no-keys guidance points there.
- Naming a provider shows its complete list **even if its key is not configured**, marked with the
  missing-key label.
- When zero providers are configured and no keyword is given, output is the no-keys guidance (how to
  set a key + pointer to `providers`), not an empty list or error. An empty keyword result says what
  was searched ("configured providers only — name a provider to search it"). Both go to stderr with
  exit 0 (the `providers` / `list` / `mcp list` precedent); JSON keeps its shape (`providers: []`).

### Enumeration & filtering
- Models come from the catalog entries (`litellm.model_cost`), NOT `litellm.models_by_provider`
  (built at import time; `register_model(dict)` updates only a hardcoded subset of its lists, so a
  live merge would silently show the offline list for openai/gemini/groq/fireworks — measured:
  `gpt-5.6-luna` lands in `model_cost` but not `models_by_provider["openai"]`).
- Each entry is assigned to a curated provider through that provider's declared catalog groups
  (Decision ledger); entries in no declared group are not listed.
- One named rule decides whether a catalog entry is a string the `llm` node can call: its mode
  counts (Decision ledger); its declared capabilities, where it declares them, include a
  chat/responses endpoint and text output (drops realtime-only and audio-only entries); it is not
  past its `deprecation_date`; and its key is not a pricing-only key (`ft:*` fine-tune templates,
  `*/container` sessions, together's `together-ai-*` size tiers, Azure data-zone `azure/*/*` and
  Bedrock region/commitment `bedrock/*/*` pricing). Tested on openai and together_ai.
- Displayed ids use ONE rule: an id that already contains `/` is shown as-is; otherwise it gets its
  provider's routing prefix (`<name>/` for every curated row). An id that does not then start with
  its provider's prefix is dropped (a catalog typo such as `replicateopenai/…`). Then dedupe.
  (Bundled 1.86.1 keys anthropic/openai bare, groq/fireworks prefixed, and the bare
  `gemini-2.0-flash` belongs to `vertex_ai-language-models` — so grouping, not the key's shape,
  decides the prefix.) Consistent with the settings CLI's normalization warning
  (`settings.py` `_normalize_and_warn_model`) and with the validator's forward catalog lookup
  (`validator.py` `_catalog_form_known_for_provider`): every listed id passes that lookup — one
  test, both directions.
- Order within a provider: version-aware name order, higher versions first (`…-4-10` before
  `…-4-9`). No curation — a mechanical stand-in for newest-first, since the catalog carries no
  release date.

### Network + fallback
- Default behavior fetches current LiteLLM model data over the network within a bounded timeout.
- On any fetch failure (timeout, non-200, parse error), fall back to the bundled snapshot WITHOUT
  raising — the command still returns a usable list.
- Output labels the source: live vs. offline-snapshot; the offline label states it may omit models
  newer than the bundled LiteLLM version.
- The network fetch does NOT run in `pflow mcp describe llm`, `pflow guide`, or any non-`models`
  path.

### Capping & guidance (self-guiding output)
- Only the no-keyword overview caps: each configured provider's list is capped at 10; a capped
  provider shows the true total and points to its complete list: `see all <N>: pflow settings llm
  models <provider>`.
- Every keyword view is complete; a provider showing more than 10 guides narrowing: `narrow: pflow
  settings llm models <provider> <keyword>`.
- Every result view offers the next steps: inspect a not-yet-configured provider (`models
  <name>`), see providers+keys (`pflow settings llm providers`), see the default pflow resolves
  (`pflow settings llm show`), store a missing key (`pflow settings set-env`, when a shown provider
  lacks one), and the escape hatch that any LiteLLM model works via `provider/model` even if
  unlisted. The no-keys and empty-result messages carry the rungs that apply there (set a key,
  search a provider, did-you-mean for a near-miss provider name, the escape hatch).
- Missing-key labels generalize beyond one env var: reuse `_format_env_vars` (gemini is OR,
  bedrock/azure/vertex are AND) and show the table's note under a missing-key label where one
  exists (credential-file / IAM setups); local (`n/a`) providers read `(local — no key needed)`.
  Curated providers with zero callable catalog entries (`vllm`, `hosted_vllm`, `huggingface`,
  `voyage`) get guidance text, never an empty list.

### JSON output
- `--output-format json` emits an object `{source, providers}` (not `providers`' bare array — it
  must carry `source`): `source` is `"live"`/`"offline"`; each provider entry carries the
  `providers` row fields — `name`, `env_vars`, `semantics`, `status` (`"set"`/`"-"`/`"n/a"`, per
  `_provider_status`), `note` — plus `models` (the complete matched ids). No `model_count` (it would equal `len(models)`). Capping is text-only. The
  no-keys and no-match cases emit the same shape with `providers: []`.

### Altered: `llm` node description
- The `llm` node's agent-facing interface text (the `LLMNode` docstring — rendered by all three
  describe surfaces) APPENDS one static, network-free pointer to the existing `model` help —
  the "always use smart default unless user requests specific model" instruction stays — e.g.
  `… List usable models: pflow settings llm models · API key env vars: pflow settings llm
  providers` (Decision ledger). `guide/nodes/llm.md:25` already points at `providers`: fold it into the
  same pointer, never two authored copies.

### Unchanged (must not regress)
- `settings set-env` / `unset-env` / `list-env`, `settings llm show`, the `llm` node's runtime
  model resolution, and smart-default selection are untouched.
- `settings llm providers` is unchanged except: (a) the `anyscale` row is removed — LiteLLM 1.86.1
  no longer routes `anyscale/…`, so the table advertised a provider pflow cannot call and this
  command would list its ids as usable; (b) one footer line points at `models`.

## Implementation Notes

- **After #606 and #654:** re-read the consolidated provider table and the fixed merge before
  planning; re-point the references below if their shape changed. (#606 also adds the
  `providers` characterization tests this command's shared helpers need.)
- **One pure core function, the CLI renders it:** catalog → provider-grouped, filtered, normalized,
  deduped ids lives beside `normalize_model_name` (`core/llm_providers.py`), not in
  `cli/commands/settings.py` — testable without the CLI, one home for both lookup directions.
  `import_litellm()` is called inside the command body (`tests/test_cli/test_lazy_imports.py`
  asserts the CLI imports without litellm).
- **Sibling to copy:** `llm_providers` in `src/pflow/cli/commands/settings.py` (`_provider_status`,
  `_format_env_vars`, the `inject_settings_env_vars()` call before status checks, text+JSON
  branches) over `CURATED_PROVIDERS` in `src/pflow/core/llm_providers.py`. Mirror its structure.
- **Provider→env-var/status** comes from `CURATED_PROVIDERS` + `_provider_status` ("status = what
  the runtime would actually use": registry rows ask `resolve_provider_api_key()`, curated-only
  rows read `os.environ` after injection); do not build a second detector.
- **Network fetch LANDMINE (from `research/model-discovery-cross-reference-from-pr-424.md`):** pflow
  forces `LITELLM_LOCAL_MODEL_COST_MAP=True`, so `litellm.register_model(URL)` short-circuits to the
  bundled backup and does nothing. The working pattern is `_merge_upstream_catalog`
  (`src/pflow/core/litellm_runtime.py`): `httpx.get(litellm.model_cost_map_url)` → shape-filter →
  exact-key insert of the keys bundled lacks. The BULK entry point already exists: `try_load_upstream_catalog`
  (`litellm_runtime.py`) returns a success bool (→ the `live`/`offline` label) and carries the
  shape filter (`_filter_well_formed_upstream_entries`) and the never-overwrite-bundled rule — reuse
  it (after #654's fix) rather than re-deriving the recipe; update its "Validator-side" docstring
  once the CLI also calls it. Semantics to preserve and label honestly: "live" = bundled +
  upstream-only additions (models removed upstream still show); the attempt latch is per-process.
  On failure, use the already-loaded bundled data. Stderr hygiene: import via `import_litellm()`
  (a bare `import litellm` prints botocore warnings; precedent #359).
- **Mode:** each catalog entry carries its own `mode` — no bare-name fallback lookup (it could read
  a different provider's entry). pflow calls `litellm.completion`, which bridges
  `mode == "responses"` models; `chat` + `responses` count (Decision ledger).
- **Test harness traps:** `tests/conftest.py:52-54` presets the upstream latch to
  attempted+succeeded for every test — a test that does not reset both flags AND patch `httpx.get`
  gets `source: "live"` with no fetch. The autouse `_inject_fake_llm_api_keys` sets fake
  anthropic/openai/gemini keys; the no-keys test needs `no_fake_llm_keys` AND must clear every env
  var in the provider table (a developer's real `GROQ_API_KEY` leaks otherwise).
  `inject_settings_env_vars()` no-ops under pytest (`llm_config.py:226`), so keys stored via
  `set-env` are verified only on the real surface.
- **Status truth:** already true after #606 (PR #661) — reuse `_provider_status` as-is.
- **Verified data shape (bundled litellm 1.86.1, 2026-09-29):** `model_cost` has 2,716 entries
  (upstream 4,435); `models_by_provider` covers 89 providers. `mode == "chat"` counts: anthropic 20,
  groq 11, openai 98 (grouped by `litellm_provider`), fireworks_ai 244; 2,082 chat + 80
  `responses` entries overall.
- **Node-describe source:** the `model: str` help text lives in the `LLMNode` docstring Interface
  block (`src/pflow/nodes/llm/llm.py:1026`). It is scanned once into `~/.pflow/registry.json` and
  rendered by THREE surfaces: `pflow mcp describe` (`MCPRegistrar.get_tool_info`,
  `mcp/registrar.py:402`), `pflow guide llm` (`guide/__init__.py` `_get_node_interface`), and the
  MCP-server `registry_describe` tool (`mcp_server/services/registry_service.py`, via the context
  builder). "No network in describe" covers all three.
- **Instruction-file touchpoints:** `guide/nodes/llm.md:25` (fold, above); the MCP instruction
  files that list `settings llm show` (`mcp-agent-instructions.md`, `mcp-sandbox-agent-instructions.md`);
  `.claude/agents/pflow-codebase-searcher.md` (a new command — root CLAUDE.md rule).

## Verification

- **No keys:** with no configured providers (fake-key fixture off, every table env var cleared),
  `models` prints the setup guidance to stderr, exit 0; JSON is `{"source": …, "providers": []}`.
- **Configured providers (overview):** with one/multiple keys set, `models` lists those providers'
  models, each labeled `(configured)`; a provider over N is capped and shows `see all N: …
  <provider>` — and running that command shows the complete list (the rung does not dead-end).
- **Provider selection:** `models anthropic` shows exactly one provider, complete — even with
  bedrock/openrouter keys configured whose model ids contain "anthropic"; `models fireworks_ai`
  shows the long list and a narrow hint; `models fireworks_ai llama` narrows.
- **Catalog groups:** `models bedrock` includes `bedrock_converse` models; `models cohere` lists
  cohere's chat models (catalog group `cohere_chat`); `models vertex_ai` includes the `vertex_ai-*`
  groups.
- **Every listed id runs:** a test asserts every id listed for every curated provider is routable
  (`litellm.get_llm_provider` resolves it) and starts with its provider's `<name>/` prefix, and
  that every anthropic/openai/gemini id passes the validator's catalog lookup. (The provider LiteLLM
  resolves may legitimately differ from the curated name — `cohere/…` → `cohere_chat`, `ai21/…` →
  `ai21_chat`, `azure/command-r-plus` → its OpenAI-compatible route — so the prefix, not the
  resolved name, pins the provider.) A second test asserts every curated provider name is itself a
  LiteLLM routing prefix.
- **Unconfigured inspect:** `models openai` with no OpenAI key shows its models with the
  missing-key label; `models gemini` shows the OR form; `models vllm` shows guidance, not an empty
  list.
- **Model keyword:** `models opus` returns matching models across configured providers; a nonsense
  keyword returns an empty result that says what was searched, not a crash.
- **Callable strings only:** `openai` output has no `dall-e`, embedding or `ft:*` entries;
  `together_ai` has no pricing-tier pseudo-entries.
- **Live path:** with the latch reset and `httpx.get` patched to return a payload holding an
  upstream-only chat model, that model appears and the source reads `live`; no bundled entry changes.
- **Network fallback:** with the latch reset and the fetch forced to fail, the command returns the
  bundled list labelled offline; no exception surfaces.
- **No network in describe:** with `try_load_upstream_catalog` patched, `pflow mcp describe llm`,
  `pflow guide llm` and the MCP-server `registry_describe` render the hint and it is
  `assert_not_called()` (a bare `httpx` patch passes for free under the preset latch).
- **JSON:** `--output-format json` parses; carries `source` and per-provider `name`, `status`,
  `env_vars`, `models`; lists all matched models (no cap in JSON).
- **Real-surface (Definition of done):** run the actual CLI — `uv run pflow settings llm models`,
  `… models anthropic`, `… models bedrock`, `… models openai`, `… --output-format json` — and
  `uv run pflow mcp describe llm` / `uv run pflow guide llm`, and confirm outputs and guidance rungs
  match this spec (keys stored via `set-env` are only checkable here).
- **No regression:** `settings llm providers` / `show`, `set-env`/`list-env`, and `llm` node runtime
  behavior unchanged.

## References

- Sibling command + provider table/status: `src/pflow/cli/commands/settings.py` (`llm_providers`,
  `_provider_status`, `_format_env_vars`); the table: `core/llm_providers.py` (`CURATED_PROVIDERS`).
- Overlapping issues: #606 (merged, PR #661), #348 (provider metadata for
  non-core providers — the `set <VAR>` label depends on it), #359 (stderr hygiene precedent).
- Runtime provider metadata: `src/pflow/core/llm_providers.py` (`PROVIDERS`, `detect_provider`).
- Network-fetch pattern + landmine: `src/pflow/core/litellm_runtime.py` (`ensure_model_priced`);
  `research/model-discovery-cross-reference-from-pr-424.md` (evidence, not design).
- Node-describe text: `src/pflow/nodes/llm/llm.py` (LLMNode Interface docstring, model param).
- Model resolution chain / key injection: `src/pflow/core/llm_config.py`.
- CLI JSON-flag convergence (why `--output-format`, not `--json`): issue #528.
- In-task prior context (pre-lock): `starting-context/`, `research/`.
