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
