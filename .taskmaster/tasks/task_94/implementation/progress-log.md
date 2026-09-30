# Task 94 — Progress Log

## [2026-09-30] task-planner — investigation + plan

- Did: verified base `c5506d6c` == origin/main, `make install`; read spec, deps (Task 80/158
  reviews, PR #661/#662 bodies), issues #348/#528/#652; ran the verify-at-start probes; wrote the
  plan; corrected the spec in place (mode resolution, local providers, callable rule, order/cap,
  routing-test wording, anyscale, stale cites).
- Verified (EXECUTED, real keys for anthropic/gemini/openai on this machine):
  - `responses` mode runs through the adapter: `uv run pflow probe --output-format json llm
    model=openai/gpt-5-pro prompt="Say exactly: pong"` → success, `pong`, $0.018.
    `openai/gpt-5.1-codex-mini`, `gpt-5-codex`, `gpt-5.1-codex` → provider `model_not_found`
    (account access), not a routing failure.
  - `completion` mode: `openai/gpt-3.5-turbo-instruct`, `openai/davinci-002`,
    `openai/babbage-002` → provider says "has been deprecated". The remaining completion-mode
    entries in curated groups are retired families (ai21 `j2-*`, cohere `command`, vertex
    `text-unicorn`, azure instruct) plus 8 `ollama/*` base models. Ollama is not installed here —
    local-provider callability not executable.
  - Catalog shape (bundled 1.86.1, 2,716 keys; live merge 4,693): 18 chat/responses entries declare
    `supported_endpoints` of `/v1/realtime` only; 4 declare audio-only output (lyria, tts);
    pricing-only keys: 14 `ft:*`, `openai/container` + `azure/container`, 8 `together-ai-*`,
    48 `azure/{us,eu,global,global-standard}/…`, 147 `bedrock/<region>/…` + 28 `bedrock/*/…
    commitment`. `deprecation_date` values are ISO strings except the `sample_spec` placeholder.
    No metadata field (context window, cost) separates pseudo-entries from real ones (baseten,
    perplexity, replicate real entries lack them too) — hence the key-pattern clause.
  - Routing (prototype of the plan's rule over every curated provider, bundled AND live):
    `litellm.get_llm_provider` raises only for `anyscale/*` (12 ids) — LiteLLM 1.86.1 no longer has
    the provider; `get_llm_provider("anyscale/some-model")` raises, every other curated
    `<name>/some-model` resolves to `<name>`. Resolved-provider mismatches that are legitimate
    LiteLLM remaps: `cohere/…` → `cohere_chat`, `ai21/jamba…` → `ai21_chat`, `azure/command-r-plus`
    & `azure/mistral-large-*` → `openai` (LiteLLM's deliberate Azure-AI-Studio route,
    `get_llm_provider_logic.py` `_is_non_openai_azure_model`). Catalog typo
    `replicateopenai/gpt-oss-20b` is dropped by the prefix guard.
  - Validator round trip: every listed anthropic/openai/gemini id passes
    `WorkflowValidator._catalog_form_known_for_provider` (0 misses, bundled and live).
  - Bedrock region keys: LiteLLM's Converse handler strips an embedded region
    (`converse_handler.py` ~285), so some are technically callable; still excluded as pricing
    keys (plan D2) — region belongs in `AWS_REGION_NAME`.
  - Describe surfaces are network-free today (searcher: no litellm import on the describe/guide/
    registry paths; one-process check left `sys.modules` litellm-free). Docstring rescan is
    mtime-driven (`registry.py` `_source_newer_than_scan`), no version bump needed.
  - Task-159 baseline case `12-…/04-guide-auto-detect` already diffs on base (guide content moved
    since) — it cannot gate this task's guide change.
- Assumed: live-catalog contents vary daily; mock model lists are a 2026-09-30 snapshot.
- Deviations/surprises: spec's "every listed id routes to its provider" is too strict (LiteLLM
  remaps above) → reworded to routable + prefix. anyscale row removal (plan D12) changes
  `providers` output — decided under the "gap your change widens" rule, flagged for the checkpoint.
- Self-checks: plan self-review battery — see next entry.
- Next: CP-1 user checkpoint (mocks in the plan appendix) before Phase 1.

## [2026-09-30] task-planner — plan self-review (plan-mode battery: review-plan, review-agent-ux, review-architecture-fit; Opus, direct launch)
- Did: ran 3 lenses on the plan; verified the load-bearing findings; folded fixes into plan + spec;
  re-rendered every mock from the updated prototype.
- Verified: click is pinned `>=8.1,<8.2` (8.1.8 installed) → the default `CliRunner()` mixes
  stderr; new tests must use `CliRunner(mix_stderr=False)`. `find_similar_items` (substring)
  maps vertex/fireworks/together → the curated names (EXECUTED). Revised pointer wording parses as
  one param (EXECUTED through `PflowMetadataExtractor`). `make test` on base: 9313 passed.
  main moved `c5506d6c` → `97dc33cd` (#652, #643, #658 — none on this task's surface);
  fast-forwarded before committing.
- Dispositions — FIXED: plan-W1 (`Full list:` rung space-joins names so it runs), W2 (mix_stderr),
  W3 (indent=2 oracle), W4 (stored-settings key test), W5 (no-keys/empty messages carry only the
  rungs that apply — spec line rescoped), W6 (lazy-import test added to the Phase-2 gate),
  S1 (spec Dependencies: no routing-prefix field), S2 (#652 note), S4 (fixture docstring + inner
  import), S5 (`{kw}` defined); ux-W1 (`narrow:` keeps active keywords), W2 (zero-model line links
  LiteLLM provider docs instead of implying `vllm/` works for a server), W3 (local "only pulled
  models run" line), W4 (JSON gains `semantics` + `note`, the `providers` row fields), W5
  (did-you-mean for near-miss provider names), W6 (set-env rung when a shown provider lacks its
  key), S1 (overview discloses the order is not a ranking), S2 (offline label says why), S5
  (pointer "no key?" → "API key env vars:"), S6 (escape hatch notes the validator may warn);
  arch-S1 (spec prices the v2 cost column's JSON cutover; docs describe order as mechanical).
- Dispositions — REJECTED: plan-S3 (fetch only when needed — a second path for a rare offline
  no-keys run); ux-S3 (keep named-but-unmatched blocks — splits the one no-match path and
  contradicts spec `providers: []`); per-row vllm/hosted_vllm hints (new table data). plan-S6
  (runtime unknown-model diagnostic → point at `models`) recorded as a follow-up candidate.
- Deviations/surprises: none beyond the above.
- Self-checks: clean — no Critical from any lens; all three lenses verified D4/D12 routing claims
  independently.
- Next: CP-1.

## [2026-09-30] task-planner — PARKED at CP-1 (user checkpoint, show-before-code)
- State: plan + spec corrections + this log committed on `feat/task-94-llm-models`. No source
  code changed. Scratch prototype that rendered the mocks lives outside the repo (session
  scratchpad) — not needed to resume; the plan's Output contract is the spec for the strings.
- Awaiting: the user's ruling on the appendix mocks M1–M13 and on D5 (order), D6 (cap 10), D12
  (anyscale removal from `providers`), D13 (`providers` footer line), D14 (pointer wording).
- Resume point: record the ruling here; fold any string/order change into the plan's Output
  contract + mocks; then Phase 1 (by the planner if resumed to implement, else an Opus
  task-orchestrator from this plan).

## [2026-09-30] task-planner — CP-1 RULING + resumed to implement
- [RULING] main orchestrator (under the user's session grant): CP-1 ACCEPTED — M1–M13 and D5, D6,
  D12, D13, D14 as planned; planner-implements ACCEPTED (~356k used). User wording objections, if
  any, arrive later as string changes.
- Next: Phase 1.

## [2026-09-30] task-planner (implementing) — Phase 1 complete (`7f866921`)
- Did: `provider_models()` + `_is_llm_callable` + `_version_key` in `core/llm_providers.py`;
  `CuratedProvider.catalog_groups` on bedrock/vertex_ai/cohere; anyscale row removed; providers
  oracles → 26 rows; 23 new tests in `tests/test_core/test_llm_providers.py`.
- Verified: `make check` green; `make test` 9342 passed. Mutation spot checks (EXECUTED, each
  reverted): dropping the prefix guard, the output-modality clause, `<=` → `<` on deprecation, or
  the `bedrock/*/*` pattern each turns ≥1 test red.
- Deviations/surprises: the plan's openai test asserted no id contains "realtime"; older
  `gpt-4o-*-realtime-preview` entries declare no capabilities (only `mode: chat`) and pass the
  data-driven rule. Kept the rule (no name-based curation); test now pins the declared
  realtime-only `gpt-realtime` instead; limitation added to the plan.
- Self-checks: fully happy; test-reflect: tests are behaviour-per-clause + real-catalog contract;
  mutation checks above are the reflection — nothing shallow found.
- Next: Phase 2.

## [2026-09-30] task-planner (implementing) — Phase 2 complete
- Did: `llm models` command + rendering helpers in `cli/commands/settings.py`; `providers` footer
  line; settings-group help line; orphaned table comment removed; llm node pointer (D14);
  `guide/nodes/llm.md` fold; MCP instruction lines; `settings.mdx` rows + section; searcher row
  (+ `make sync-claude-assets` → `.codex/agents/pflow-codebase-searcher.toml`); `core/CLAUDE.md`
  row; `litellm_runtime` docstrings; `reset_upstream_attempted` moved to `tests/conftest.py`;
  24 new CLI/describe tests.
- Verified: `make check` green; `make test` 9366 passed; `test_lazy_imports.py` 1 passed.
  Mutation spot checks (EXECUTED, restored from a backup copy): keeping unmatched providers,
  capping keyword views, guidance to stdout, and an env-only status detector each turn tests red.
- Deviations/surprises: a mutation loop restored `settings.py` with `git checkout`, which dropped
  the uncommitted Phase-2 edits; re-applied from the same script and re-verified (96 tests), then
  ran mutations against a backup copy. No lasting effect.
- Self-checks: fully happy; test-reflect: the byte-exact overview/no-keys/JSON oracles plus
  mutation checks cover the contract; no shallow tests found.
- Next: Phase 3 real-surface runs.

## [2026-09-30] task-planner (implementing) — Phase 3 real surface + completion tests
- Verified (EXECUTED, real CLI, this machine's keys — anthropic/openai stored via set-env,
  GEMINI exported):
  - `settings llm models` → M1 layout, live, anthropic 24 / gemini 31 / openai 112 (JSON parses,
    same counts); `anthropic` complete 24 + narrow; `bedrock` 5 `bedrock/amazon.nova*` (Converse
    group) + IAM note; `vertex_ai` 63 `vertex_ai/gemini-|claude-` ids; `cohere` lists
    `cohere/command-r*`; `openai` has no dall-e/embedding/ft:/whisper/tts ids; `vllm` guidance;
    `vertex` → did-you-mean `vertex_ai` on stderr, exit 0; `xyzzy` → stderr, exit 0.
  - Offline: `LITELLM_MODEL_COST_MAP_URL=http://127.0.0.1:9/none … models anthropic` → offline
    label with LiteLLM 1.86.1, 15 bundled ids, empty stderr, exit 0.
  - Isolated HOME, provider env vars unset → M7 guidance on stderr, stdout empty; after
    `set-env GROQ_API_KEY` in that HOME → `groq (configured)` in the overview (stored-key path).
  - `mcp describe llm` and `guide llm` show the pointer once; `providers` → 26 rows, no anyscale,
    new footer line.
  - Listed ids run: `probe llm` with `anthropic/claude-haiku-4-5`, `openai/gpt-4o-mini`,
    `gemini/gemini-flash-lite-latest` → all success, "pong".
  - `make test-all-local`: first two runs 5 failures in `tests/test_cli/test_ui.py` (not on base).
    Cause: `TestLazyImportBoundary` pops `pflow.ui.server` from `sys.modules` without restoring;
    when xdist schedules it before the endpoint tests on the same worker, their
    `patch("pflow.ui.server.…")` hits a fresh module the app never uses. The new tests shifted
    worksteal scheduling. Reproduced on base code by ordering the two classes (2 failed); fixed
    with `monkeypatch.delitem` (restores at teardown) → 16 passed in that order; full
    `make test-all-local` 9416 passed, 2 skipped.
- Deviations/surprises: the test_ui.py fix is outside the plan — a latent order-dependent leak
  this diff's new tests exposed; test-only, 3 lines, revertible.
- Next: completion gate (code-mode deep-review).

## [2026-09-30] task-planner (implementing) — completion gate: reading battery
- Did: pflow fan-out (codex, cross-model), 6 lenses: spec-conformance, agent-ux, silent-failures,
  test-fidelity, impact-completeness, simplicity. Coverage 6/6; report
  `scratchpads/task-94/review-report.md` (local).
- Dispositions:
  - test-fidelity "C1" (multi-keyword test passed with only the last keyword applied) — FIXED:
    `anthropic sonnet 4-6` must yield exactly `claude-sonnet-4-6`; mutation (last-keyword-only
    filter) now fails it (EXECUTED). Severity is a test gap, not a product defect.
  - spec-conformance W1 (no case-sensitivity regression test) — FIXED: public-API test with a
    `Anthropic` group and an `FT:` key; discriminates only on Windows, where `fnmatch` folds case
    (the tests-windows job).
  - spec-conformance S1 (no successful model-keyword real run recorded) — FIXED: `uv run pflow
    settings llm models opus` → `anthropic (configured)` with only `anthropic/claude-opus-*` ids,
    exit 0 (EXECUTED; it had run in Phase 3 but went unrecorded).
  - test-fidelity S1 (dataclass-default test is shallow) — FIXED: deleted.
  - agent-ux doc S (JSON empty-case wording) + impact doc S (page intro told agents not to run
    these) — FIXED in `settings.mdx`.
  - Integration note: main gained stdin-isolation commits; merged before the falsifier.
- Verified clean per lenses: silent-failures, simplicity, agent-ux (no C/W).
- Next: merge origin/main, re-gate, falsifier.

## [2026-09-30] task-planner (implementing) — merged origin/main (`8222ffc6`), re-gate
- Did: merged main (#657 stdin isolation, Task 178 docs; no overlap). `make check` green.
- Deviation: the earlier `monkeypatch.delitem` fix for the UI lazy-import test only swapped the
  leak — the fresh import still rebinds the `pflow.cli.commands.ui` package attribute, so
  `TestUiCommand::test_default_path_wires_the_readiness_thread` compared two module objects
  (1 failure in the merged full run). Replaced with a subprocess check (fresh interpreter, no
  shared state; explicit `encoding="utf-8"` for PYTHONWARNDEFAULTENCODING). Verified it still
  detects the regression it guards (appending `import pflow.ui.server` to `ui.py` → red,
  EXECUTED, reverted).
- Verified: `make test-all-local` 9430 passed, 2 skipped — twice.
- Next: falsifier result, then close-out.

## [2026-09-30] task-planner (implementing) — completion gate: falsifier (direct, Opus, run last on the merged state)
- Result: 14 of 16 promises HELD (keywords, streams/exit codes text+JSON, live/offline label across
  ten upstream states incl. timeout, cap-only-overview + every printed rung runs, 2,076 listed ids
  route with their prefix, validator accepts live-listed ids, pointer on all three describe
  surfaces with zero catalog requests incl. a real `pflow mcp serve`, `providers` diff = intended
  only, show/set-env/list-env unchanged vs main, status labels, local/zero-model guidance, groups,
  no network elsewhere).
- Dispositions:
  - W2 `pflow settings --help` misaligned (my help-line insert had the wrong indent; ruff then
    re-indented the whole docstring) — FIXED: main's docstring restored + the line at the
    `providers` depth; regression test asserts the two lines align (fails on the pre-fix file,
    EXECUTED).
  - W1 listed gemini ids fail at run time (`learnlm-1.5-pro-experimental`, `gemini-gemma-2-27b-it`,
    `gemini-exp-1206` — retired upstream, still in the catalog with no `deprecation_date`) —
    ACCEPTED as a named limitation: no catalog signal separates them; filtering by name is
    curation. Documented in `settings.mdx` and the plan's Known limitations; the failure is loud
    and pflow's error names a working id. Reported in the handback.
  - S1 `… | head -1` exits 1 — CLI-wide SIGPIPE handling (`main.py:_setup_signals`), not this
    diff; follow-up candidate.
  - S2 did-you-mean misses typos / can mislead on short words; S3 an exact provider name always
    selects (spec rule) — SKIPPED (take-or-leave; spec-settled).
- Next: final gates, spec Status, task review, PR.
