# Task 94 — Implementation Plan: `pflow settings llm models`

Spec: `../task-94.md` (current truth; its Decision ledger is settled). Progress log:
`progress-log.md` (probe evidence and the plan self-review dispositions live there, not here).
Base: `97dc33cd` (main at planning time).

## Shape in one paragraph

One pure function in `core/llm_providers.py` — `provider_models(provider, catalog, *, today)` —
turns LiteLLM's catalog into the display-ready, callable, ordered model ids for one curated
provider. `CuratedProvider` gains one field, `catalog_groups`, and three rows use it. The CLI
command `llm models` in `cli/commands/settings.py` is a thin renderer over that function, reusing
`_provider_status` / `_format_env_vars` and `try_load_upstream_catalog()` (live/offline). The `llm`
node's `model` param help gets one static pointer line; `guide/nodes/llm.md:25` folds into it.
No engine, trace, validator, or template contact.

## Cross-task scan (`./scripts/tasks`, 2026-09-30)

- **Reusable substrate (verified against code):** #606/PR #661 (`CURATED_PROVIDERS`,
  `_provider_status` = runtime truth, byte-exact `providers` oracles in
  `tests/test_cli/test_settings_cli.py:839-1003`); #654/PR #662 (`_merge_upstream_catalog`
  exact-key merge; `import_litellm()` sets `suppress_debug_info`); Task 158 adapter seal.
- **Collision risk:** Task 170 (in flight) owns `core/workflow/validator.py`,
  `runtime/template_*`, `runtime/engine/`. This task only *reads* the validator (a test calls
  `WorkflowValidator.validate`); nothing edits it. #652 merged `core/stdout_reservation.py`, which
  wraps user-code execution only; settings commands run no user code, so they keep plain
  `click.echo(json.dumps(...))`. #643/#657 disjoint. Task 117 (unbuilt) will sweep every
  `--output-format` option into one decorator; `models` copies `providers`' inline option exactly,
  so it joins that sweep with no second shape.
- Open #660 (settings warnings repeat per `SettingsManager`) applies to `models` exactly as to
  `providers`; not ours.

## Resolved decisions

All ≤2/5 unless marked; evidence in the progress log.

- **D1 — Modes (applies the ledger rule):** `chat` + `responses`. A `responses` model
  (`openai/gpt-5-pro`) ran through the adapter. `completion` is excluded: every completion-mode
  model reachable through the adapter was rejected by its provider as deprecated.
- **D2 — The callable rule** (`_is_llm_callable(key, entry, today)`, private, ONE place). An entry
  counts iff:
  1. `mode` ∈ {chat, responses};
  2. `supported_endpoints`, *when declared as a list*, intersects {`/v1/chat/completions`,
     `/v1/responses`} (drops 18 realtime-only entries);
  3. `supported_output_modalities`, *when declared as a list*, contains `"text"` (drops
     audio-only lyria/tts entries);
  4. `deprecation_date`, when an ISO date, is **after** `today` (unparseable → keep; the catalog
     has a `sample_spec` placeholder string);
  5. the key matches none of `_PRICING_ONLY_KEYS` (fnmatch**case**): `ft:*` (fine-tune templates),
     `*/container` (code-interpreter sessions), `together-ai-*` (size-tier pricing), `azure/*/*`
     (data-zone pricing; deployment names cannot contain `/`), `bedrock/*/*` (region/commitment
     pricing, incl. `bedrock/*/1-month-commitment/…`; address `bedrock/<model-id>` and pick the
     region with `AWS_REGION_NAME`). One comment per pattern, at the tuple.
  Use `fnmatch.fnmatchcase`, never `fnmatch.fnmatch` — the latter case-folds on Windows
  (`tests-windows`).
- **D3 — Grouping:** an entry belongs to a provider iff its `litellm_provider` matches
  (fnmatchcase) `provider.name` or one of `provider.catalog_groups`. Rows: `bedrock` ←
  `("bedrock_converse",)`, `vertex_ai` ← `("vertex_ai-*",)`, `cohere` ← `("cohere_chat",)`.
  Everything else defaults to `()`. Deliberately NOT grouped: `azure_ai` (separate LiteLLM provider,
  different env vars), `bedrock_mantle` (its keys carry their own `bedrock_mantle/` prefix),
  `vertex_ai-anthropic_models` under anthropic (it routes `vertex_ai/…`), `text-completion-openai`
  / `azure_text` (completion only).
- **D4 — Displayed id; no routing-prefix field:** `key if "/" in key else f"{name}/{key}"`, kept
  only if it starts with `f"{name}/"`, then deduped (set). Every curated row's routing prefix is
  its own name — verified for all 26 surviving rows — so the ledger's "(b) routing prefix" is
  derived, not a field (deletion test; spec Dependencies line updated). The prefix guard drops
  catalog typos (`replicateopenai/gpt-oss-20b`).
- **D5 — Order:** version-aware name order, higher first:
  `sorted(ids, key=_version_key, reverse=True)` with
  `_version_key(s) = ([int(t) if i % 2 else t for i, t in enumerate(re.split(r"(\d+)", s.lower()))], s)`.
  Digit runs always sit at odd positions of `re.split` with one capture group, so element types
  align and never compare int with str; the trailing `s` makes ties deterministic. Known weakness,
  shown in the checkpoint and disclosed in the overview's second line: families that do not share
  a name stem interleave by letter (openai's `o4-*` before `gpt-5*`; gemini's `learnlm`/`gemma`
  before `gemini-*`). No mechanical signal fixes that without curation, which the ledger defers to
  v2. Docs describe the order as mechanical, never as "newest first" or a ranking.
- **D6 — Cap:** `_MODELS_OVERVIEW_CAP = 10` (overview only). The same constant is the "narrow:"
  threshold in keyword views (a provider showing more than 10). One constant, two uses.
- **D7 — Keywords:** lowercased. A keyword equal to a curated name selects that provider (several
  names select several). Every other keyword is a *model keyword*: a substring filter on the
  lowercased displayed id, AND-combined. Scope = named providers if any, else providers whose
  status is `set`. **A model keyword drops providers it matches nothing in** (named or not — so
  every no-match case is the one empty-result path and JSON `providers: []`); without a model
  keyword every scoped provider is kept, including ones with zero catalog models (they render
  guidance). Output order is always `(semantics == "local", name)` — the `providers` order —
  never argument order. `{kw}` anywhere in output = the model keywords, lowercased, space-joined.
- **D8 — Local (`n/a`) providers:** not in the overview; listed when named; the no-keys guidance
  names ollama. Label `(local — no key needed)`; a local block with models adds
  `  (catalog ids — your server runs only the models it has pulled)`.
- **D9 — Notes:** a row's `note` prints (indented, in parentheses) only under a missing-key label
  (status `-`): bedrock/vertex IAM, together's "not TOGETHER_API_KEY". JSON always carries `note`.
- **D10 — Streams:** results + footer → stdout. No-keys guidance and empty-result messages →
  stderr, exit 0, in BOTH formats (JSON mode prints the `{source, providers: []}` document on
  stdout and the same guidance on stderr — one code path, stdout stays pure JSON).
- **D11 — Source:** `"live" if try_load_upstream_catalog() else "offline"`, called right after
  `import_litellm()` on every run (one linear path; the JSON shape needs `source` even with no
  keys — the rare no-keys-and-offline text run pays the 5 s fetch timeout, accepted). Text lines:
  `Source: live LiteLLM catalog` / `Source: offline snapshot (LiteLLM <version>; live catalog
  unreachable) — may omit models released after it` (`importlib.metadata.version("litellm")`).
  Printed first in result views and in the empty-result message; not in the no-keys guidance (no
  catalog shown).
- **D12 — `anyscale` row removed from `CURATED_PROVIDERS`** (spec "Unchanged" updated). LiteLLM
  1.86.1 raises "LLM Provider NOT provided" for `anyscale/<anything>`; it is the only curated name
  that does not route. Listing its 12 catalog ids would extend a live defect (`providers`
  advertises a dead provider) to a new surface — the "gap your change widens" rule. Changes
  `providers` output by one row (`Showing 26 curated provider(s).`). **Flagged in the handback.**
- **D13 — `providers` footer:** add `Models per provider: pflow settings llm models <provider>`
  immediately after the `Set a key:` line. Update both byte-exact oracles.
- **D14 — The pointer line** (exact; one line; no `, word:` sequence — the interface parser splits
  params on it; a continuation line breaks parsing; the text below was run through
  `PflowMetadataExtractor` and parses as one param):
  `- Params: model: str  # Model to use (optional - always use smart default unless user requests specific model). List usable models: pflow settings llm models · API key env vars: pflow settings llm providers`
  (the ledger's example wording, with "no key?" made explicit so the fold loses nothing). Delete
  `guide/nodes/llm.md:25` and one adjacent blank line: `pflow guide llm` appends the interface
  block, so the pointer still renders there, once.
- **D15 — JSON:** `{"source", "providers": [{"name", "env_vars", "semantics", "status", "note",
  "models"}]}`, `indent=2`, key order exactly as written (the `providers` row plus `models`, so
  OR/AND auth and the IAM note survive in JSON); `env_vars` a list; `note` null when absent;
  models complete (never capped). A future cost column turns `models` items into objects — a
  planned clean cutover (spec Design Decisions), not a reason to ship objects now.
- **D16 — Shared test fixture:** move `reset_upstream_attempted` from
  `tests/test_core/test_litellm_runtime.py:230-257` to `tests/conftest.py` (non-autouse), with
  `import_litellm` imported INSIDE the fixture (conftest stays cheap), and update the
  `_block_upstream_cost_map_fetch` docstring (`tests/conftest.py:38-41`) that calls it "local".
- **D17 — Near-miss provider names:** in the empty-result path only, for each model keyword where
  `find_similar_items(kw, sorted(curated names), max_results=1)` (`core/suggestion_utils.py`,
  substring method) returns a name, add `"{kw}" is not a provider name — did you mean: pflow
  settings llm models {name}`. (`vertex`→`vertex_ai`, `fireworks`→`fireworks_ai`,
  `together`→`together_ai`.)

**Rejected at self-review (logged):** keeping named-but-unmatched provider blocks (would split the
no-match path and contradict the spec's `providers: []`); fetching only when needed (a second code
path for a rare offline case); per-row vllm/hosted_vllm hints (new table data; the zero-model line
links LiteLLM's provider docs instead).

## Output contract (exact strings)

Status labels: `set` → `(configured)`; `-` → `(no key — set {_format_env_vars(p)})`; `n/a` →
`(local — no key needed)`.

Result view (stdout): the source line (D11); in the overview only, a second line
`Up to 10 per provider, ordered by name (higher versions first) — not a ranking.`; a blank line;
then per provider a block — header `{name} ({label})`; `  ({note})` (D9); the local line (D8);
zero models → `  No usable models in LiteLLM's catalog — pass the id your provider serves as
{name}/<model> (setup: https://docs.litellm.ai/docs/providers)`; model lines `  {id}`; overview cap
→ `  see all {N}: pflow settings llm models {name}`; keyword view with more than 10 →
`  narrow: pflow settings llm models {name}{" " + kw if model keywords} <keyword>`; blank line.
Then the footer: `Next steps:` and rungs rendered `f"  {command:<41}  {description}"`:

| command | description | when |
|---|---|---|
| `pflow settings set-env <ENV_VAR> "<key>"` | `store a missing key` | only if a shown provider's status is `-` |
| `pflow settings llm models <provider>` | `a provider's full list, even without its key` | always |
| `pflow settings llm models <keyword>` | `filter your providers' models by name (e.g. opus)` | always |
| `pflow settings llm providers` | `every provider and the env var it needs` | always |
| `pflow settings llm show` | `the default model pflow resolves` | always |

and last the escape hatch (shared by the empty-result message):
`Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).`

No keys (scope empty; stderr); `{kws}` = `" " + kw` when model keywords were given, else empty:
```text
No LLM provider keys configured.
Set one:             pflow settings set-env ANTHROPIC_API_KEY "<key>"   (every provider: pflow settings llm providers)
Browse without one:  pflow settings llm models <provider>{kws}   (e.g. anthropic, or ollama for local models)
```

Empty result (scope non-empty, every provider dropped by the model keywords; stderr): source line;
blank; `No models match "{kw}" in your configured providers ({a, b, c}).` (nothing named) or
`No models match "{kw}" in {a, b}.` (named); the D17 lines; then `Search a provider without its
key:  pflow settings llm models <provider> {kw}` (nothing named) or `Full list:  pflow settings llm
models {a b}` (named — SPACE-joined so the printed command runs); the escape hatch. Commas only in
prose.

The no-keys and empty-result messages carry only the rungs that apply there (setting a key,
searching a provider, the escape hatch) — not the full footer; spec Requirements say so.

The appendix mocks are the acceptance target; the implementer reproduces them on the real
surface (content varies with the live catalog; the format must not).

## ⚑ USER CHECKPOINT CP-1 — show before code (BLOCKING, before Phase 1)

The planner hands back here. The main orchestrator shows the user the appendix mocks M1–M13 plus
D5 (order), D6 (cap 10), D12 (anyscale removal), D13 (`providers` footer), D14 (pointer wording).
The user's ruling goes into the progress log; any change to strings/order lands in this plan
before Phase 1 starts. No other embedded checkpoint.

## Phases

No engine contact, no trace-format change (Task-159 baseline not required — its
`04-guide-auto-detect` case already diffs on base, so it cannot gate the guide change), no
platform-sensitive code beyond D2's `fnmatchcase`. **No phase triggers a mid-task review.**

**Agent assignment:** ONE Opus `task-phase-implementer`, effort `medium`, Phases 1+2 bundled
(same tier, consecutive; the Phase-1 gate cannot change Phase-2's instructions — Phase 2 consumes
`provider_models` exactly as specified). The task orchestrator (or the planner, if resumed to
implement) runs Phase 3 itself. Test baseline on base: `make test` = 9313 passed.

### Phase 1 — core listing + table

- **Goal:** `provider_models` and the table change exist, pinned by tests against synthetic AND
  real bundled catalogs.
- **Files:** `src/pflow/core/llm_providers.py`; `tests/test_core/test_llm_providers.py`;
  `tests/test_cli/test_settings_cli.py` (providers oracles: drop anyscale; count 26 — the D13
  footer line lands in Phase 2 with its code).
- **Decisions:** D1–D5, D12. Signature:
  `def provider_models(provider: CuratedProvider, catalog: Mapping[str, object], *, today: date) -> list[str]`.
  `catalog_groups: tuple[str, ...] = ()` is the LAST `CuratedProvider` field (after `note`); the
  three rows pass it by keyword. Document it in the class docstring ("`litellm_provider` values,
  as fnmatch patterns, whose catalog entries this provider also serves besides `name`").
  Registry-derived rows need no change (positional 3-arg construction still works). Module stays
  dependency-free (stdlib `re`, `fnmatch`, `datetime`, `collections.abc` only) — `settings.py`
  imports it at module scope and `tests/test_cli/test_lazy_imports.py` forbids litellm there.
  Update the module docstring's table description in one clause; no other restatement.
- **Tests (the interface is `provider_models`; no testing of private helpers):**
  - Synthetic catalogs (tiny dicts), one behaviour each: embedding/image/completion dropped, chat +
    responses kept; realtime-only endpoints dropped, undeclared endpoints kept; audio-only output
    dropped; each `_PRICING_ONLY_KEYS` pattern dropped (parametrized) beside a kept sibling in the
    same catalog; past and same-day `deprecation_date` dropped, future kept, junk string kept;
    foreign group dropped, `catalog_groups` pattern matched (`vertex_ai-language-models`,
    `cohere_chat`), `vertex_ai-anthropic_models` NOT under anthropic; bare key prefixed, slashed
    key as-is, foreign-prefix slashed key dropped, `deepseek-chat` + `deepseek/deepseek-chat` →
    one id; non-dict entry and missing `litellm_provider` ignored; order `x-4-10` before `x-4-9`
    before `x-4`, identical across two calls.
  - Real bundled catalog (`import_litellm().model_cost`, fixed `today=date(2026, 9, 30)`):
    1. **Routing:** for every curated provider, every listed id → `litellm.get_llm_provider(id)`
       does not raise AND id starts with `f"{p.name}/"`. (Only curated prefixes reach this call, so
       the `github_copilot/*` device-login hazard cannot trigger.)
    2. **Every curated name routes:** `get_llm_provider(f"{p.name}/pflow-probe")` succeeds for
       every row (the guard that would have caught anyscale).
    3. **Validator round trip:** one IR with an `llm` node per listed anthropic/openai/gemini id
       plus one `openai/pflow-no-such-model` node → `WorkflowValidator.validate(ir,
       skip_node_types=True)` → exactly one `llm.model-not-in-catalog` diagnostic, on the bogus
       node (presence), none on listed ids. Fake keys come from the autouse fixture (path has no
       `/llm/`). Precedent: `tests/test_core/test_workflow_validator_llm_model.py:50-66`.
       Prototyped: 132 nodes validate in 0.04 s with exactly that one diagnostic.
    4. **Spec-named exclusions:** openai has no id containing `dall-e`, `embedding`, `ft:`,
       `realtime`, `container`, AND contains an id whose entry has no `deprecation_date`
       (assert that too, so the test cannot rot with the calendar); together_ai has no
       `together_ai/together-ai-` id AND has ≥1 id.
    5. **Groups:** for (bedrock, bedrock_converse), (vertex_ai, a `vertex_ai-*` group), (cohere,
       cohere_chat): ≥1 listed id derives from an entry of that extra group. (Also the guard if a
       row is ever promoted into `PROVIDERS`: its derived row would lose `catalog_groups`.)
    6. `vllm`, `hosted_vllm`, `huggingface`, `voyage` → `[]` (documents the guidance path).
  - `test_curated_provider_names_are_unique` still passes; `providers` oracles updated.
- **Failure scenarios the tests must catch:** a DALL-E/embedding/realtime/lyria id listed as a chat
  model; `ft:gpt-4o` offered; `together-ai-4.1b-8b` offered; a bedrock region pricing key offered;
  vertex's bare `gemini-2.0-flash` shown as `gemini/…` (wrong provider) or dropped; bedrock missing
  its Converse models; cohere empty; a replicate typo key shown; a LiteLLM bump that drops a
  provider (anyscale class) or stops routing a listed id; `gpt-4-10` sorted below `gpt-4-9`; a
  listed openai id the validator warns about; Windows case-folding (`fnmatch`).
- **Handoff:** `make check` + `make test` green; `provider_models` returns the D4/D5 shape; the
  providers oracles pass with 26 rows.

### Phase 2 — CLI command + describe hint + instruction surfaces

- **Goal:** `pflow settings llm models` produces the appendix outputs; the pointer renders in all
  describe surfaces with zero network; every instruction surface names the command once.
- **Files:** `src/pflow/cli/commands/settings.py`; `src/pflow/core/litellm_runtime.py` (docstrings
  only); `src/pflow/nodes/llm/llm.py` (line 1026 only); `src/pflow/guide/nodes/llm.md`;
  `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` (+1 line after
  `pflow settings llm show`: `pflow settings llm models                           # Models your
  keys can use (keywords filter)`); `…/mcp-sandbox-agent-instructions.md` (+1 bullet: ``-
  `pflow settings llm models` — List models the configured keys can use``);
  `docs/reference/cli/settings.mdx`; `.claude/agents/pflow-codebase-searcher.md` + `make
  sync-claude-assets`; `src/pflow/core/CLAUDE.md` (one routing-table row);
  `tests/conftest.py` + `tests/test_core/test_litellm_runtime.py` (D16 move);
  `tests/test_cli/test_settings_cli.py`.
- **Decisions:** D6–D11, D13–D17 and the Output contract. Command skeleton:
  `@llm.command(name="models")`, `@click.argument("keywords", nargs=-1)`, the same
  `--output-format` option as `providers` (`click.Choice(["text", "json"])`, default `text`).
  Body order: `inject_settings_env_vars()` → `import_litellm()` → source (D11) → scope (D7) →
  listings via `provider_models(p, litellm.model_cost, today=date.today())` → JSON (if json) →
  empty/no-keys guidance to stderr and return → text render. All litellm/core imports inside the
  body. Compute each scoped provider's `_provider_status` once. Split rendering into small private
  helpers beside `llm_providers` (label, block, footer, no-models message); no new module.
  Docstring: one-line purpose + keyword semantics + three examples (like `providers`). Also: add
  `pflow settings llm models                    # Models you can use with your keys` under the
  `providers` line in the `settings` group help (`test_main.py:30-32` pins only line 1); delete
  the orphaned comment `settings.py:467-470` (its table moved to core in #661).
  `litellm_runtime.py`: `try_load_upstream_catalog` docstring + the `# Validator-side latch`
  comment + the module docstring's "(validator membership)" become "catalog readers (validator
  membership, `settings llm models`)" — say it once per site, no new prose.
  `settings.mdx`: add `llm providers` and `llm models` rows to the Commands table and a
  `### pflow settings llm models` section after `### pflow settings llm show` (usage, keyword
  semantics, source label, JSON shape, order described as mechanical, one example).
  `pflow-codebase-searcher.md`: one routing row naming `provider_models` / `CURATED_PROVIDERS` in
  `src/pflow/core/llm_providers.py` and the command in `src/pflow/cli/commands/settings.py`
  (`tests/test_docs/test_agent_references.py` checks every backticked token exists).
- **Tests** — new class `TestLLMModelsCommand` in `tests/test_cli/test_settings_cli.py`, runner
  **`CliRunner(mix_stderr=False)`** (click is pinned 8.1: the file's default `runner` fixture mixes
  stderr into `result.output`, so stdout/stderr assertions would be meaningless — precedent
  `tests/test_integration/test_metrics_integration.py:154`); env scrub = every var in
  `CURATED_PROVIDERS`, derived from the table, plus `isolated_settings`; a synthetic catalog via
  `monkeypatch.setattr(import_litellm(), "model_cost", SYNTH)`; source via patching
  `pflow.core.litellm_runtime.try_load_upstream_catalog` (the body imports it at call time, so
  the module-attribute patch takes; without it the conftest latch preset reports `live` with no
  fetch). Synthetic catalog: 12 anthropic chat entries (cap), openai 2 chat + 1 embedding + 1 `ft:`
  (excluded), groq 2, one `cohere_chat`, one `bedrock_converse`, an `openrouter/anthropic/…` and a
  bedrock `anthropic.claude-…` entry, no vllm.
  1. Overview byte-exact on stdout (ANTHROPIC + OPENAI set): disclosure line, cap 10, `see all 12`,
     groq absent (presence pair: anthropic present), footer without the set-env rung, stderr empty.
  2. The see-all rung does not dead-end: `models anthropic` → 12 ids, no `see all`, `narrow:`
     present.
  3. Exact selection: OPENROUTER + AWS keys set → `models anthropic` shows only the anthropic
     block although other providers' ids contain "anthropic".
  4. Labels: `models groq` (no key) → `(no key — set GROQ_API_KEY)` + the set-env rung; `models
     gemini` → `… GEMINI_API_KEY or GOOGLE_API_KEY`; `models bedrock` → AND form + note line;
     `models vllm` → zero-model line; `models ollama` → `(local — no key needed)` + the pulled
     line, no note line.
  5. **Stored key:** `ANTHROPIC_API_KEY` stored via `SettingsManager(settings_path=isolated_settings)
     .set_env(...)`, env var scrubbed → overview shows `anthropic (configured)` (status comes from
     `_provider_status` → `resolve_provider_api_key`, which reads settings even though injection
     no-ops under pytest; precedent `test_settings_cli.py:981-1003`).
  6. Model keyword: `models OPUS` (case-insensitive) → only matching ids; a configured provider
     with no match is omitted (presence pair: the matching provider shown); its `narrow:` rung
     carries `opus`.
  7. `models anthropic opus` narrows within the provider.
  8. No keys: stdout empty, stderr = the guidance, exit 0; with `opus` the browse line carries it;
     JSON: stdout == `json.dumps({"source": "live", "providers": []}, indent=2) + "\n"`, stderr =
     the guidance.
  9. Empty result: `models xyzzy` → stderr names the configured providers, stdout empty; `models
     vertex` → the D17 line names `vertex_ai`; `models anthropic openai xyzzy` → `Full list:
     pflow settings llm models anthropic openai`, and invoking exactly that printed command returns
     a non-empty result; JSON `providers: []`.
  10. JSON byte-exact for a small case (D15 key order); the overview in JSON carries all 12
      anthropic ids (no cap).
  11. Offline label (patched `False`) contains the installed litellm version string.
  12. **Live path, real code:** `reset_upstream_attempted` + deep-copied real `model_cost` +
      `httpx.get` stubbed to return a payload holding an upstream-only anthropic chat entry → it
      appears in `models anthropic`, source `live`, a chosen bundled entry is identical before and
      after.
  13. **Fallback, real code:** same fixture, `httpx.get` raising → offline label, bundled ids
      listed, exit 0, no traceback.
  14. `providers` footer oracle includes the D13 line.
  15. **Describe hint, no network:** with `try_load_upstream_catalog` patched to a `Mock`: `mcp
      describe llm` (CliRunner on `pflow.cli.commands.mcp.mcp`), `guide llm` (`compose_guide(["llm"])`
      or CliRunner on `guide_cmd`), `RegistryService.describe_nodes(["llm"])` each contain
      `List usable models: pflow settings llm models`; the mock `assert_not_called()`; and
      `pflow settings llm providers` occurs exactly once in `guide llm` (the fold — never two
      authored copies).
- **Failure scenarios the tests must catch:** overview capping a keyword view or JSON; `see all`
  pointing at a view that is itself capped; `narrow:`/`Full list:` rungs that drop the active
  keywords or print an unrunnable command; `models anthropic` pulling in openrouter/bedrock blocks;
  a no-keys run printing an empty table or exiting non-zero; guidance leaking onto stdout in JSON
  mode (breaks parsing); `source: live` reported when the fetch failed (and the converse); an
  unconfigured provider labelled `(configured)`, or a key stored in settings ignored; the describe
  path importing/fetching the catalog; the pointer duplicated in `guide llm`; litellm imported at
  CLI import time.
- **Handoff:** `make check` + `make test` green; **plus `uv run pytest
  tests/test_cli/test_lazy_imports.py`** (marked e2e — `make test` skips it); `make
  sync-claude-assets` leaves no diff.

### Phase 3 — real-surface verification (task orchestrator / planner-implementer)

Record each command and its observed output in the progress log.
- `uv run pflow settings llm models` (real keys: anthropic, gemini, openai are set on this machine)
  → M1 format; `… anthropic`, `… bedrock`, `… openai`, `… vllm`, `… opus`, `… vertex`,
  `… xyzzy`, `… --output-format json | python -m json.tool`.
- Offline: `LITELLM_MODEL_COST_MAP_URL=http://127.0.0.1:9/none uv run pflow settings llm models
  anthropic` → offline label, exit 0, clean stderr.
- Stored keys (injection no-ops under pytest; this is the only end-to-end check):
  `HOME=$(mktemp -d)` with `pflow settings set-env GROQ_API_KEY x` and the real exported keys unset
  (`env -u …`) → `groq (configured)` in the overview; same HOME with nothing stored → M7 on stderr.
- `uv run pflow mcp describe llm` and `uv run pflow guide llm` show the pointer once.
- One listed id per registry provider runs: `uv run pflow probe llm model=<id> prompt="Say
  exactly: pong"` with a cheap listed model each for anthropic, gemini, openai.
- `uv run pflow settings llm providers` → 26 rows + the new footer line.
- Completion: `make test-all-local`.

## Completion gate (task orchestrator)

Code-mode `deep-review`, lenses per the rubric; expected set: `review-agent-ux` (all new output),
`review-silent-failures` (fallback, empty paths), `review-test-fidelity` (oracles, synthetic
catalogs), then `review-falsifier` last (the spec's Verification bullets are testable promises).
`review-simplicity` / `review-spec-conformance` only if the rubric's tier calls for them — never
mid-task.

## Known limitations (accepted, stated so nobody re-derives them)

- D5 ordering is mechanical; openai/gemini samples in the overview lead with the alphabetically
  later families. v2 curation is the fix.
- Enumeration still lists models that need extra setup to call (`*-deep-research` needs a tool;
  Azure ids are callable only if the user's deployment carries that name; bedrock needs model
  access; `ollama/*-cloud` needs an Ollama sign-in). The provider's error names the cause.
- `vllm/` runs vLLM in-process (needs the `vllm` package); a vLLM *server* is `hosted_vllm/` with
  `HOSTED_VLLM_API_BASE`. The zero-model line links LiteLLM's provider docs rather than encoding
  per-row hints.
- "live" = bundled + upstream-only keys; a model removed upstream still shows (per spec).
- IAM/credential-file bedrock/vertex users read `(no key — …)` — same as `providers` (#661 notes).

## Follow-up candidate (not this task)

The runtime unknown-model diagnostic (`src/pflow/core/exceptions.py` ~341) points at `llm show`
and LiteLLM's docs; it could point at `pflow settings llm models <provider>` — the moment an agent
most needs the list. The validator's twin belongs to Task 170's file.

## Appendix — checkpoint mocks (CP-1)

Rendered 2026-09-30 by a scratch prototype of this plan against the real catalog (live upstream
merged, LiteLLM 1.86.1), keys: anthropic, gemini, openai. Model lists are real data; strings and
layout are the contract.

#### M1 — overview (no keyword; anthropic + gemini + openai keys configured)
```text
$ pflow settings llm models
--- stdout ---
Source: live LiteLLM catalog
Up to 10 per provider, ordered by name (higher versions first) — not a ranking.

anthropic (configured)
  anthropic/claude-sonnet-5-5
  anthropic/claude-sonnet-5
  anthropic/claude-sonnet-4-6
  anthropic/claude-sonnet-4-5-20250929
  anthropic/claude-sonnet-4-5
  anthropic/claude-opus-5-5
  anthropic/claude-opus-5
  anthropic/claude-opus-4-8
  anthropic/claude-opus-4-7-20260416
  anthropic/claude-opus-4-7
  see all 24: pflow settings llm models anthropic

gemini (configured)
  gemini/learnlm-1.5-pro-experimental
  gemini/gemma-4-31b-it
  gemini/gemma-4-26b-a4b-it
  gemini/gemma-3-27b-it
  gemini/gemini-robotics-er-2-preview
  gemini/gemini-robotics-er-1.5-preview
  gemini/gemini-pro-latest
  gemini/gemini-gemma-2-27b-it
  gemini/gemini-gemma-2-9b-it
  gemini/gemini-flash-lite-latest
  see all 31: pflow settings llm models gemini

openai (configured)
  openai/o4-mini-deep-research-2025-06-26
  openai/o4-mini-deep-research
  openai/o4-mini-2025-04-16
  openai/o4-mini
  openai/o3-pro-2025-06-10
  openai/o3-pro
  openai/o3-mini-2025-01-31
  openai/o3-mini
  openai/o3-deep-research-2025-06-26
  openai/o3-deep-research
  see all 112: pflow settings llm models openai

Next steps:
  pflow settings llm models <provider>       a provider's full list, even without its key
  pflow settings llm models <keyword>        filter your providers' models by name (e.g. opus)
  pflow settings llm providers               every provider and the env var it needs
  pflow settings llm show                    the default model pflow resolves
Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).
(exit 0)
```

#### M2 — provider view (complete, uncapped)
```text
$ pflow settings llm models anthropic
--- stdout ---
Source: live LiteLLM catalog

anthropic (configured)
  anthropic/claude-sonnet-5-5
  anthropic/claude-sonnet-5
  anthropic/claude-sonnet-4-6
  anthropic/claude-sonnet-4-5-20250929
  anthropic/claude-sonnet-4-5
  anthropic/claude-opus-5-5
  anthropic/claude-opus-5
  anthropic/claude-opus-4-8
  anthropic/claude-opus-4-7-20260416
  anthropic/claude-opus-4-7
  anthropic/claude-opus-4-6-20260205
  anthropic/claude-opus-4-6
  anthropic/claude-opus-4-5-20251101
  anthropic/claude-opus-4-5
  anthropic/claude-opus-4-1
  anthropic/claude-mythos-5-1
  anthropic/claude-mythos-5
  anthropic/claude-haiku-4-5-20251001
  anthropic/claude-haiku-4-5
  anthropic/claude-fable-5-1
  anthropic/claude-fable-5
  anthropic/claude-4-sonnet-20250514
  anthropic/claude-4-opus-20250514
  anthropic/claude-3-haiku-20240307
  narrow: pflow settings llm models anthropic <keyword>

Next steps:
  pflow settings llm models <provider>       a provider's full list, even without its key
  pflow settings llm models <keyword>        filter your providers' models by name (e.g. opus)
  pflow settings llm providers               every provider and the env var it needs
  pflow settings llm show                    the default model pflow resolves
Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).
(exit 0)
```

#### M3 — unconfigured provider + keyword (AND label, IAM note, set-env rung)
```text
$ pflow settings llm models bedrock claude-sonnet-4
--- stdout ---
Source: live LiteLLM catalog

bedrock (no key — set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)
  (Or use AWS IAM role / ~/.aws/credentials)
  bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0
  bedrock/us.anthropic.claude-sonnet-4-6
  bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
  bedrock/us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0
  bedrock/jp.anthropic.claude-sonnet-4-6
  bedrock/jp.anthropic.claude-sonnet-4-5-20250929-v1:0
  bedrock/global.anthropic.claude-sonnet-4-20250514-v1:0
  bedrock/global.anthropic.claude-sonnet-4-6
  bedrock/global.anthropic.claude-sonnet-4-5-20250929-v1:0
  bedrock/eu.anthropic.claude-sonnet-4-20250514-v1:0
  bedrock/eu.anthropic.claude-sonnet-4-6
  bedrock/eu.anthropic.claude-sonnet-4-5-20250929-v1:0
  bedrock/claude-sonnet-4-5-20250929-v1:0
  bedrock/au.anthropic.claude-sonnet-4-6
  bedrock/au.anthropic.claude-sonnet-4-5-20250929-v1:0
  bedrock/apac.anthropic.claude-sonnet-4-20250514-v1:0
  bedrock/apac.anthropic.claude-sonnet-4-6
  bedrock/anthropic.claude-sonnet-4-20250514-v1:0
  bedrock/anthropic.claude-sonnet-4-6
  bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0
  narrow: pflow settings llm models bedrock claude-sonnet-4 <keyword>

Next steps:
  pflow settings set-env <ENV_VAR> "<key>"   store a missing key
  pflow settings llm models <provider>       a provider's full list, even without its key
  pflow settings llm models <keyword>        filter your providers' models by name (e.g. opus)
  pflow settings llm providers               every provider and the env var it needs
  pflow settings llm show                    the default model pflow resolves
Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).
(exit 0)
```

#### M4 — model keyword across configured providers
```text
$ pflow settings llm models opus
--- stdout ---
Source: live LiteLLM catalog

anthropic (configured)
  anthropic/claude-opus-5-5
  anthropic/claude-opus-5
  anthropic/claude-opus-4-8
  anthropic/claude-opus-4-7-20260416
  anthropic/claude-opus-4-7
  anthropic/claude-opus-4-6-20260205
  anthropic/claude-opus-4-6
  anthropic/claude-opus-4-5-20251101
  anthropic/claude-opus-4-5
  anthropic/claude-opus-4-1
  anthropic/claude-4-opus-20250514
  narrow: pflow settings llm models anthropic opus <keyword>

Next steps:
  pflow settings llm models <provider>       a provider's full list, even without its key
  pflow settings llm models <keyword>        filter your providers' models by name (e.g. opus)
  pflow settings llm providers               every provider and the env var it needs
  pflow settings llm show                    the default model pflow resolves
Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).
(exit 0)
```

#### M5 — provider + keyword, network down (offline label)
```text
$ pflow settings llm models fireworks_ai llama  (network down)
--- stdout ---
Source: offline snapshot (LiteLLM 1.86.1; live catalog unreachable) — may omit models released after it

fireworks_ai (no key — set FIREWORKS_AI_API_KEY)
  fireworks_ai/accounts/fireworks/models/phind-code-llama-34b-v2
  fireworks_ai/accounts/fireworks/models/phind-code-llama-34b-v1
  fireworks_ai/accounts/fireworks/models/phind-code-llama-34b-python-v1
  fireworks_ai/accounts/fireworks/models/nous-hermes-llama2-70b
  fireworks_ai/accounts/fireworks/models/nous-hermes-llama2-13b
  fireworks_ai/accounts/fireworks/models/nous-hermes-llama2-7b
  fireworks_ai/accounts/fireworks/models/llamaguard-7b
  fireworks_ai/accounts/fireworks/models/llama-v3p3-70b-instruct
  fireworks_ai/accounts/fireworks/models/llama-v3p2-90b-vision-instruct
  … (44 more model lines in the real output)
  fireworks_ai/accounts/fireworks/models/code-llama-7b
  narrow: pflow settings llm models fireworks_ai llama <keyword>

Next steps:
  pflow settings set-env <ENV_VAR> "<key>"   store a missing key
  pflow settings llm models <provider>       a provider's full list, even without its key
  pflow settings llm models <keyword>        filter your providers' models by name (e.g. opus)
  pflow settings llm providers               every provider and the env var it needs
  pflow settings llm show                    the default model pflow resolves
Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).
(exit 0)
```

#### M6 — local provider + zero-model provider
```text
$ pflow settings llm models ollama vllm
--- stdout ---
Source: live LiteLLM catalog

ollama (local — no key needed)
  (catalog ids — your server runs only the models it has pulled)
  ollama/qwen3-coder:480b-cloud
  ollama/mixtral-8x22B-Instruct-v0.1
  ollama/mixtral-8x7B-Instruct-v0.1
  ollama/mistral-large-instruct-2407
  ollama/mistral-7B-Instruct-v0.2
  ollama/mistral-7B-Instruct-v0.1
  ollama/llama3:70b
  ollama/llama3:8b
  ollama/llama3.1
  ollama/llama3
  ollama/llama2:70b
  ollama/llama2:13b
  ollama/llama2:7b
  ollama/llama2
  ollama/internlm2_5-20b-chat
  ollama/gpt-oss:120b-cloud
  ollama/gpt-oss:20b-cloud
  ollama/deepseek-v3.1:671b-cloud
  ollama/deepseek-coder-v2-lite-instruct
  ollama/deepseek-coder-v2-instruct
  ollama/codegeex4
  narrow: pflow settings llm models ollama <keyword>

vllm (local — no key needed)
  No usable models in LiteLLM's catalog — pass the id your provider serves as vllm/<model> (setup: https://docs.litellm.ai/docs/providers)

Next steps:
  pflow settings llm models <provider>       a provider's full list, even without its key
  pflow settings llm models <keyword>        filter your providers' models by name (e.g. opus)
  pflow settings llm providers               every provider and the env var it needs
  pflow settings llm show                    the default model pflow resolves
Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).
(exit 0)
```

#### M7 — no keys configured
```text
$ pflow settings llm models   (no keys configured)
--- stderr ---
No LLM provider keys configured.
Set one:             pflow settings set-env ANTHROPIC_API_KEY "<key>"   (every provider: pflow settings llm providers)
Browse without one:  pflow settings llm models <provider>   (e.g. anthropic, or ollama for local models)
(exit 0)
```

#### M8 — no keys configured, keyword given
```text
$ pflow settings llm models opus   (no keys configured)
--- stderr ---
No LLM provider keys configured.
Set one:             pflow settings set-env ANTHROPIC_API_KEY "<key>"   (every provider: pflow settings llm providers)
Browse without one:  pflow settings llm models <provider> opus   (e.g. anthropic, or ollama for local models)
(exit 0)
```

#### M9 — empty keyword result
```text
$ pflow settings llm models xyzzy
--- stderr ---
Source: live LiteLLM catalog

No models match "xyzzy" in your configured providers (anthropic, gemini, openai).
Search a provider without its key:  pflow settings llm models <provider> xyzzy
Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).
(exit 0)
```

#### M10 — near-miss provider name (did-you-mean)
```text
$ pflow settings llm models vertex
--- stderr ---
Source: live LiteLLM catalog

No models match "vertex" in your configured providers (anthropic, gemini, openai).
"vertex" is not a provider name — did you mean: pflow settings llm models vertex_ai
Search a provider without its key:  pflow settings llm models <provider> vertex
Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).
(exit 0)
```

#### M11 — named providers, keyword matches nothing
```text
$ pflow settings llm models anthropic openai xyzzy
--- stderr ---
Source: live LiteLLM catalog

No models match "xyzzy" in anthropic, openai.
Full list:  pflow settings llm models anthropic openai
Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).
(exit 0)
```

#### M12 — JSON (named provider without key)
```text
$ pflow settings llm models groq --output-format json
--- stdout ---
{
  "source": "live",
  "providers": [
    {
      "name": "groq",
      "env_vars": [
        "GROQ_API_KEY"
      ],
      "semantics": "single",
      "status": "-",
      "note": null,
      "models": [
        "groq/qwen/qwen3.8-27b",
        "groq/qwen/qwen3-32b",
        "groq/openai/gpt-oss-safeguard-20b",
        "groq/openai/gpt-oss-120b",
        "groq/openai/gpt-oss-20b",
        "groq/moonshotai/kimi-k2-instruct-0905",
        "groq/meta-llama/llama-prompt-guard-2-86m",
        "groq/meta-llama/llama-prompt-guard-2-22m",
        "groq/meta-llama/llama-guard-4-12b",
        "groq/meta-llama/llama-4-scout-17b-16e-instruct",
        "groq/meta-llama/llama-4-maverick-17b-128e-instruct",
        "groq/llama-3.3-70b-versatile",
        "groq/llama-3.1-8b-instant",
        "groq/gemma-7b-it"
      ]
    }
  ]
}
(exit 0)
```

#### M13 — JSON, no keys (shape kept; guidance on stderr)
```text
$ pflow settings llm models --output-format json   (no keys configured)
--- stdout ---
{
  "source": "live",
  "providers": []
}
--- stderr ---
No LLM provider keys configured.
Set one:             pflow settings set-env ANTHROPIC_API_KEY "<key>"   (every provider: pflow settings llm providers)
Browse without one:  pflow settings llm models <provider>   (e.g. anthropic, or ollama for local models)
(exit 0)
```

