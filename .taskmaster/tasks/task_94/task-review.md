# Task 94 Review: Show Available LLM Models Based on Configured API Keys

## Metadata

- Implemented 2026-09-30 on `feat/task-94-llm-models` (base `97dc33cd`, with main merged at
  `8222ffc6`). Status: PR open, not yet merged at writing time. Planned and implemented by the
  same agent: planner-implements, CP-1 accepted by the main orchestrator.
- Journey, probe evidence and every review disposition: `implementation/progress-log.md`. Accepted
  output contract and mocks: `implementation/implementation-plan.md` (Output contract + appendix).

## Read First — the load-bearing block

- **What exists now:** `pflow settings llm models [KEYWORDS…] [--output-format text|json]` lists
  the model ids an `llm` node can be given, per curated provider, read from LiteLLM's catalog.
  The catalog is fetched live, with the bundled snapshot as offline fallback. The `llm` node's
  `model` param help points at it.
- **Read these first:**
  - `src/pflow/core/llm_providers.py` — `provider_models`, `_is_llm_callable`,
    `_PRICING_ONLY_KEYS`, `_version_key`, `CuratedProvider.catalog_groups`, `CURATED_PROVIDERS`.
  - `src/pflow/cli/commands/settings.py` — `llm_models` and the `_echo_*` / `_catalog_source_line`
    / `_model_status_label` helpers beside `llm_providers`.
  - `src/pflow/core/litellm_runtime.py::try_load_upstream_catalog` — its return value IS the
    live/offline label.
  - `tests/test_core/test_llm_providers.py` (rule + bundled-catalog contract tests) and
    `tests/test_cli/test_settings_cli.py::TestLLMModelsCommand` (byte-exact output).
- **Invariants that must NOT break:**
  - **`core/llm_providers.py` stays dependency-free.** `settings.py` imports it at module scope.
    A litellm import there breaks the CLI lazy-import contract
    (`tests/test_cli/test_lazy_imports.py`, e2e-marked, so `make test` does NOT run it).
    `provider_models` takes the catalog as an argument for exactly this reason.
  - **Never call `litellm.get_llm_provider` across the catalog at runtime.** On `github_copilot/*`
    it prints a device-login prompt to stdout and blocks. Routability is pinned by tests over
    curated prefixes only.
  - **Pattern matching uses `fnmatch.fnmatchcase`, never `fnmatch.fnmatch`.** The latter
    case-folds on Windows, which would silently change grouping and pricing-key exclusion there.
  - **Guidance and empty-result messages go to stderr, exit 0, in BOTH formats.** In JSON mode
    stdout must be exactly the `{source, providers}` document. Agents pipe it into a parser.
  - **`source: "live"` only when `try_load_upstream_catalog()` returned True.** A wrong label
    tells an agent a missing model doesn't exist.
  - **Every curated row's name is its LiteLLM routing prefix.** Displayed ids are `<name>/…`.
    Adding a row whose name isn't a routing prefix (as `anyscale` had become) fails
    `test_every_curated_provider_name_is_a_litellm_routing_prefix`.

## What Was Built (actual vs. planned)

- **Built as planned** (plan D1–D17): pure `provider_models()` plus a thin CLI renderer. The table
  gained one field, `catalog_groups` (fnmatch patterns): bedrock ← `bedrock_converse`,
  vertex_ai ← `vertex_ai-*`, cohere ← `cohere_chat`.
- **No routing-prefix field.** The spec ledger's "(b) routing prefix" turned out to be `<name>/`
  for every row, so it is derived (deletion test).
- **The `anyscale` row was removed from `CURATED_PROVIDERS`.** LiteLLM 1.86.1 no longer routes
  `anyscale/…`. The table was advertising a dead provider, and this command would have listed
  12 uncallable ids. This changes `settings llm providers` output: 26 rows, plus a new footer
  line `Models per provider: …`.
- **Modes:** `chat` and `responses` count. `openai/gpt-5-pro` (responses) ran through the adapter.
  `completion` is excluded: every completion-mode model reachable here was retired by its
  provider.
- **The callable rule** (`_is_llm_callable`), one place:
  - the mode counts;
  - declared `supported_endpoints` include chat/responses (drops realtime-only);
  - declared `supported_output_modalities` include text (drops lyria/tts);
  - not past `deprecation_date`;
  - the key is not pricing-only (`ft:*`, `*/container`, `together-ai-*`, `azure/*/*`,
    `bedrock/*/*`).
- **Review-driven additions beyond the spec's first draft** (all in the accepted contract):
  - JSON entries carry `semantics` + `note` (the `providers` row fields);
  - did-you-mean for near-miss provider names in the empty-result path only
    (`find_similar_items`, substring method);
  - a `set-env` rung when a shown provider lacks its key;
  - an overview disclosure line saying the order is not a ranking;
  - the `narrow:` rung keeps the active keywords;
  - the `Full list:` rung space-joins names so it runs.
- **Off-plan fixes:**
  - `tests/test_cli/test_ui.py::TestLazyImportBoundary` now checks the import in a subprocess
    (see Gotchas).
  - The `reset_upstream_attempted` fixture moved from `test_litellm_runtime.py` to
    `tests/conftest.py`, and is shared.
- **Accepted limitations** (plan → Known limitations):
  - The order is mechanical. `_version_key`, descending, puts openai's `o4-*` before `gpt-5*`
    and gemini's `learnlm`/`gemma` before `gemini-*`.
  - The catalog lags providers: e.g. `gemini/learnlm-1.5-pro-experimental` and
    `gemini/gemini-exp-1206` are retired upstream but have no `deprecation_date`. They route and
    validate, then fail at run time with `Unknown model`. Documented in
    `docs/reference/cli/settings.mdx`.
  - Entries declaring no capabilities are trusted (old `gpt-4o-*-realtime-preview` stays listed).

## Patterns & Anti-Patterns

- **Pattern — catalog readers take the catalog as a parameter.** `provider_models(provider,
  catalog, *, today)` is pure. Tests pass tiny synthetic dicts for rule tests and
  `import_litellm().model_cost` for contract tests. `today` is injected, so deprecation tests
  don't rot with the calendar.
- **Pattern — pin data-dependent behaviour with contract tests over the real bundled catalog.**
  Routing, the validator round trip, groups and exclusions all run against the pinned LiteLLM.
  A LiteLLM bump that drops a provider, renames a group or adds a pricing-key shape fails loudly
  instead of silently changing the list.
- **Pattern — "absence + presence" in output tests.** E.g. the realtime-only `gpt-realtime` is
  asserted absent AND asserted present in the catalog, so the absence isn't free.
- **Anti-pattern (rejected) — metadata heuristics for pseudo-entries.** Context window or cost
  presence do NOT separate pricing tiers from real models: real baseten/perplexity/replicate
  entries lack them too. Use a key-pattern list, one comment per pattern.
- **Anti-pattern (rejected) — name-based curation to hide retired or realtime models.** The
  ledger defers curation to v2. The rule uses declared catalog data only.
- **Anti-pattern — `get_llm_provider(...)[1] == provider.name` as the routing assertion.**
  LiteLLM legitimately remaps: `cohere/…` → `cohere_chat`, `ai21/jamba…` → `ai21_chat`,
  `azure/command-r-plus` → the OpenAI-compatible route. Assert "routable + carries `<name>/`".

## Gotchas & Non-Obvious Coupling

- **click is pinned `<8.2`.** `CliRunner()` mixes stderr into `result.output`, so stdout/stderr
  assertions need `CliRunner(mix_stderr=False)`. `TestLLMModelsCommand` overrides the file's
  `runner` fixture for this.
- **`tests/conftest.py` presets the catalog-reader latch to "attempted + succeeded".** Any test
  of `models` reports `source: live` without a fetch unless it patches
  `pflow.core.litellm_runtime.try_load_upstream_catalog`. Patching the module attribute works
  because the command imports it at call time. For the real merge path, use the
  `reset_upstream_attempted` fixture plus a deep-copied `model_cost` plus a stubbed `httpx.get`.
- **`inject_settings_env_vars()` no-ops under pytest.** Stored keys still count in tests, because
  `_provider_status` → `resolve_provider_api_key` reads `SettingsManager` directly.
  Curated-only rows read `os.environ`.
- **`LITELLM_MODEL_COST_MAP_URL` redirects the fetch.** `http://127.0.0.1:9/none` is the
  reliable way to exercise offline on the real CLI.
- **Never re-import a module in-process to test lazy imports.** Popping `sys.modules` (even
  restored with `monkeypatch.delitem`) leaves the parent package attribute bound to the fresh
  module. Other tests on the same xdist worker then patch or compare a different module object.
  This task's new tests shifted worksteal scheduling and exposed it in `test_ui.py`. Use a
  subprocess (with `encoding="utf-8"`: `make` sets PYTHONWARNDEFAULTENCODING).
- **Docstring edits in click group help:** an inserted line with a different indent makes ruff
  re-indent the whole docstring and click then shifts the block. Now guarded by
  `test_settings_help_lists_the_command_beside_providers`.
- **The node pointer must stay one line, with no `, word:` sequence.** The interface parser
  (`registry/metadata_extractor.py`) splits params on it, and continuation lines fall back to
  `type: any`. `guide/nodes/llm.md` no longer carries a separate `providers` pointer. The
  interface block renders into `pflow guide llm`, so a second authored copy would duplicate it.
- **Validator coupling (read-only):** anthropic/openai/gemini listed ids must pass
  `WorkflowValidator._catalog_form_known_for_provider` (`core/workflow/validator.py`). The
  validator only catalog-checks those three registry providers; other providers pass it
  trivially.
- **Mutation testing warning:** restore mutated files from a backup copy, never
  `git checkout <file>`. That discards uncommitted work, and did so once here.

## Integration Points

- **Depends on:**
  - `CURATED_PROVIDERS` / `_provider_status` / `_format_env_vars` (#606);
  - `try_load_upstream_catalog` → `_merge_upstream_catalog` (#654; exact-key merge; upstream
    never overwrites bundled);
  - `import_litellm()` (sets `suppress_debug_info`);
  - `find_similar_items`.
- **Contracts changed:**
  - `settings llm providers` text/JSON: `anyscale` row gone, a new footer line; byte-exact
    oracles updated.
  - New agent-facing JSON `{source, providers: [{name, env_vars, semantics, status, note,
    models}]}`. A future cost column is a planned clean cutover (models become objects), per the
    spec's Design Decisions.
  - The `llm` node `model` help text is rendered by `mcp describe`, `guide llm`, MCP
    `registry_describe` and discovery. The registry rescans on source mtime.
- **Instruction surfaces naming the command:**
  - `settings` group help;
  - `docs/reference/cli/settings.mdx`, which now also documents `llm providers`;
  - `mcp-agent-instructions.md`, `mcp-sandbox-agent-instructions.md`;
  - `.claude/agents/pflow-codebase-searcher.md` (+ `.codex` mirror);
  - `src/pflow/core/CLAUDE.md`.
- **Task 117** (future `@output_format_option` decorator) should sweep `models` together with
  `providers`: same inline option.

## Tests That Matter

- `tests/test_core/test_llm_providers.py`:
  - `test_every_listed_model_routes_through_litellm`,
    `test_every_curated_provider_name_is_a_litellm_routing_prefix` — the LiteLLM-bump guards.
  - `test_every_listed_registry_model_passes_the_validator_catalog_lookup` — one IR, ~130 nodes
    plus one bogus node that must be the only `llm.model-not-in-catalog`.
  - `test_declared_catalog_groups_contribute_models`,
    `test_providers_without_catalog_models_list_nothing`.
  - The per-clause synthetic tests. Mutation-verified: the prefix guard, the output-modality
    clause, the `<=` deprecation boundary and the `bedrock/*/*` pattern each turn a test red.
  - `test_provider_models_matching_is_case_sensitive_on_every_platform` discriminates only on
    the `tests-windows` job.
- `tests/test_cli/test_settings_cli.py::TestLLMModelsCommand`:
  - byte-exact overview, no-keys and JSON oracles;
  - the stored-key test;
  - the runnable `Full list:` rung;
  - `test_narrow_rung_keeps_the_active_keywords`.
  - Mutation-verified: keeping unmatched providers, capping keyword views, guidance on stdout, an
    env-only status detector, and last-keyword-only filtering all fail.
- `TestLLMModelsCatalogSource` — real merge path live and offline, with `httpx` stubbed.
- `TestLLMNodeModelsHint` — pointer on all three describe surfaces; the fetch mock is
  `assert_not_called`.
- When touching this area, also run `uv run pytest tests/test_cli/test_lazy_imports.py`
  (e2e-marked).

## Follow-up candidates (observed, not built)

- The runtime `Unknown model` diagnostic (`core/exceptions.py`, ~341) could point at
  `pflow settings llm models <provider>`. The validator twin lives in Task 170's file.
- `pflow settings llm models bedrock | head -1` exits 1. This is CLI-wide SIGPIPE handling
  (`cli/main.py::_setup_signals`), not specific to this command.

---
*Distilled from the implementation context of Task 94. The chronological journey lives in
`implementation/progress-log.md` — this review is the durable forward-reference, not a
re-narration of it.*
