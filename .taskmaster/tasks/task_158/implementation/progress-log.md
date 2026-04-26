# Task 158 — Migration Implementation Log

**Purpose of this document:** Capture the session-by-session implementation of the LiteLLM migration — what was done, what surprised us, what code reviews surfaced, what got reshaped along the way. The task spec (`../task-158.md`) documents the final architecture. This log documents how we got there: spike findings, sub-step decisions, review iterations, perf fixes, end-to-end verification.

**Sessions:** 2026-04-24 → 2026-04-26.

**Section numbering starts at §25.** Sections §1–§24 (the original caching-feature design discussion that motivated this work — alternatives considered, syntax pivots, user principles, research methodology) live in **`../../task_159/implementation/progress-log.md`**. §25 documents the migration-flavored half of a split session — Task 159's §25 documents the caching-flavored half. The formal task split happened after Phase A landed; both logs share the §25 calendar date because that session straddled both concerns.

**Quick reference for the implementation arc:**

| § | Session | What landed |
|---|---|---|
| §25 | 2026-04-24 | Phased implementation decision — migration first |
| §26 | 2026-04-24 | Phase 0 + Phase A plan written and approved |
| §27 | 2026-04-24 | Phase 0 LiteLLM verification spike executed |
| §28 | 2026-04-24 | Phase A.1–A.5 (install + reasoning_map + adapter + mock + LLMNode rewire) |
| §29 | 2026-04-24 | Phase A.6–A.8 (tracing redesign + discovery callsites + mass test cleanup) |
| §30 | 2026-04-25 | Phase A.9–A.12 + end-of-task cleanup |
| §31 | 2026-04-25 | Phase A code review #1 + 6 follow-up commits |
| §32 | 2026-04-25 | Code-review item #6 implemented (typed-error translation) |
| §33 | 2026-04-25 | Broader deferred-findings closeout |
| §34 | 2026-04-25 | Code review #2 + completion plan + 10-step typed-exception architecture |
| §35 | 2026-04-25 | Performance regression diagnosis + two-stage fix |
| §36 | 2026-04-25 | Final loose-ends pass + focused review + follow-up issues filed |
| §37 | 2026-04-25 | Code review #3 + structural adapter seal fix |
| §38 | 2026-04-26 | End-to-end verification + 3 fixes from bare-model-name regression |

---

## 25. Session 2026-04-24 — Phased implementation decision (migration first)

The user resumed in worktree `pflow-feat-prompt-caching-lite-llm` to refine the design before implementation. Two parallel outcomes from this session: a final caching-design refinement (8 ambiguities resolved — see Task 159's progress log §25) and the phased-implementation decision documented here. The latter is what ultimately shaped this task's existence.

### Phased implementation decision

The user decided we couldn't write a credible plan for the full original-Task-158 scope (caching + library migration) without first verifying LiteLLM works for pflow's use case. Sequence:

1. Spec revision (this session — done).
2. Write a plan covering a LiteLLM verification spike + library migration.
3. Plan review.
4. Execute spike + migration. All tests green before merge.
5. After migration lands, write the implementation plan for the caching feature, informed by concrete LiteLLM behavior.
6. Plan review.
7. Execute caching feature.

Steps 2–4 became this task — Task 158, the LiteLLM migration. Steps 5–7 remain in Task 159 (the caching feature). The formal task split happened later, after Phase A landed and the migration scope had crystallized into something architecturally significant on its own (typed-exception architecture, diagnostic pipeline, tracing redesign, perf fixes — all documented in §28–§38 below).

### Spec revisions made this session (migration-flavored)

The session also revised the original Task 158 spec. Migration-relevant edits:

- Removed "5–10 engineer-day" estimate from Design Decision 1 (estimates with AI implementation are too unreliable to anchor on).
- Files to Modify section trimmed heavily — high-level pointers only; detailed file-level work moved to the forthcoming implementation plan.
- Non-Obvious Integration Points section: kept the facts, removed specific file:line numbers (those belong in the plan).
- Implementation Phasing section: split planning itself into "plan Phase 0+A first, then plan B–G after Phase A lands". Added Phase 0 spike scope detail (extended thinking + cache, structured output + cache, transitive dep audit, pricing investigation).

(Caching-related spec revisions from the same session are documented in Task 159's progress log §25.)

### Deferred decisions (intentional)

- **Phase 0 rollback criterion** — what to do if LiteLLM has a dealbreaker (direct SDKs? Stay on `llm`?). Not decided this session because the spike is cheap; cross that bridge if the spike fails. (It didn't — see §27.)

### Open assumptions to verify in Phase 0 spike

(All resolved by §27's spike; recorded here for completeness of what was asked of the spike.)

- LiteLLM passes `cache_control` cleanly to all three providers.
- LiteLLM `completion_cost()` is accurate enough to replace `llm_pricing.py` (best case) or merit primary-with-fallback (medium case). Outcome chooses spec direction for pricing module fate.
- Gemini double-counting fix (LiteLLM PR #15226, 2025-10-07) is present in the version we pin.
- Extended thinking parameters compose with `cache_control` and with `response_format`.

### Next step

Write the Phase 0 + Phase A implementation plan (which became `implementation/implementation-plan.md`). Plan-writing happens in §26.

---

## 26. Session 2026-04-24 — Phase 0 + Phase A plan written and approved

Continued in worktree `pflow-feat-prompt-caching-lite-llm` on branch `feat/prompt-caching-lite-llm`. Plan file: `.taskmaster/tasks/task_158/implementation/implementation-plan.md` (also at `~/.claude/plans/lets-create-the-plan-foamy-haven.md`). User approved the plan via ExitPlanMode at end of session.

### Research conducted before plan writing

Three pflow-codebase-searcher agents launched in parallel against the worktree to verify the codebase surface against the spec's assumptions. Two completed cleanly, one timed out and was relaunched with tighter scope. Findings consolidated into the plan; key learnings:

**Verified against current code (matches spec assumptions):**
- 4 production import sites of `llm` library: `nodes/llm/llm.py`, `registry/discovery.py`, `registry/smart_filter.py`, `core/workflow/discovery.py` (plus 2 lazy imports in `runtime/workflow_trace.py`).
- Tracing monkey-patch is more sophisticated than expected: two-layer interception (`llm.get_model` + per-instance `model.prompt`), reference-counted via `_llm_interception_count`, per-thread state via `_thread_local.current_node` and `_active_collectors[thread_id]`, lock-protected.
- `compute_node_config` `batch_config` conditional inclusion pattern is the canonical precedent for Phase C's `prompt_cache` inclusion.
- `NodeConfig` dataclass is NOT frozen — Phase B/C field additions are safe.
- 9 test files patch `llm.get_model`; 6 use the `mock_llm_calls` autouse fixture; ~20 inline `Mock()` assertions in `test_llm.py` will need shape-reshape during Phase A.
- `test_plan_drift.py` has 32 tests asserting planner ↔ runtime parity. Sacred during the tracing redesign.
- Reasoning options precedence at `nodes/llm/llm.py:53-56` (Anthropic Opus 4.5 thinking_effort BEFORE thinking_budget) is load-bearing — must preserve in the new hardcoded map.

**Two findings contradict the spec — flagged in plan:**

1. **`~/.config/io.datasette.llm/keys.json` direct read.** Spec says "optionally read for users migrating from `llm`". Codebase grep confirms pflow does NOT currently read this file — all key discovery is via `llm keys get` subprocess. So adding direct read is NEW functionality, not migration of existing behavior. Plan defers this to v1.x follow-up. Phase A migration story: env vars only; users who currently use Simon's keys.json must migrate manually.

2. **Cache-write multiplier.** Spec assumes Anthropic-style 1.25× (5-min) and 2× (1-hour) write multipliers. Current `core/llm_pricing.py:168` has hardcoded `2.0` only — no per-TTL distinction. Becomes load-bearing in Phase E (when 1h TTL becomes selectable in `## Cache` blocks), not Phase A. Note in Phase 0 spike outcome but no Phase A change needed.

**Documentation drift discovered:** `core/CLAUDE.md:198` claims "46+ models"; actual count in `MODEL_PRICING` is 41. Fix during Phase A.10 documentation pass.

### Plan structure

- **Context** — scope is Phase 0 + Phase A only; Phases B–G plan deferred until Phase A lands.
- **Phase 0** — verification spike, 5 concerns: cache mechanics, composition matrix (cache + thinking + structured output), pricing authority decision (A/B/C outcomes), operational checks (logger, threading, env-var, hidden config files, dep audit), exception detection. Deliverable: short markdown report appended to progress-log with pass/fail per concern.
- **Phase A** — 12 sub-steps (A.1 through A.12), each with files touched and verification:
  - A.1 — Install LiteLLM (don't remove old yet)
  - A.2 — `llm_reasoning_map.py` (new)
  - A.3 — `llm_client.py` adapter (new)
  - A.4 — Test infrastructure: add `MockLLMClient` and `mock_llm_client` fixture (existing fixture coexists)
  - A.5 — Rewire LLMNode to use adapter
  - A.6 — Tracing redesign (riskiest step)
  - A.7 — Update 3 other call sites (discovery × 2 + smart_filter)
  - A.8 — Mass test migration; delete legacy mock infrastructure
  - A.9 — `llm_config.py` and `settings.py` cleanup (drop subprocess paths)
  - A.10 — Pricing decision + cleanup (outcome-dependent on Phase 0)
  - A.11 — Remove `llm`/`llm-anthropic`/`llm-gemini` from `pyproject.toml`
  - A.12 — Documentation
- **Critical files** + **Existing utilities to reuse** — explicit listings.
- **Spec corrections discovered** — the two contradictions above plus the CLAUDE.md drift.
- **Verification** — separate criteria for Phase 0 and Phase A; `test_plan_drift.py` is sacred; smoke test against `lyrics-generator` end-to-end.
- **Suggested commit sequence** — 12 commits matching A.1–A.12, tests green at every step.
- **Risks and mitigations** — 7 risks called out; tracing redesign is the highest-risk single step (mitigated by overlap window where both monkey-patch and trace_hook coexist briefly).
- **Out of scope** — explicit list of everything deferred to Phases B–G.

### Notable design decisions in the plan

- **Adapter API shape:** `complete(...)` keyword-only function returning an `AdapterResponse` dataclass with `.text` (attribute, not callable), `.usage` (dict with stable keys matching what `enrich_llm_usage_with_cost` expects), `.model`, `.has_schema`. Normalizes LiteLLM's per-provider quirks at the seam — LLMNode.post() should not need changes after Phase A.
- **Trace hook replaces monkey-patch.** Adapter takes optional `trace_hook` callable. LLMNode passes `trace_hook=collector.get_trace_hook(node_id)` when a collector is active. The `_active_collectors[thread_id]` registry is preserved (consulted from LLMNode side now, not from inside a patched llm function).
- **Test infrastructure transitions overlap.** A.4 adds `MockLLMClient` and the new fixture WHILE keeping `MockLLMModel` and `mock_llm_calls` in place. Callers migrate one-by-one (A.5, A.7), then legacy infrastructure deletes in A.8. Avoids a hard cutover.
- **Pydantic ValidationError catch** (the `nodes/llm/llm.py:298-311` PATTERN EXCEPTION) — likely removed under LiteLLM since it's tied to llm-library's Options Pydantic validation. If LiteLLM has an equivalent deterministic-error pattern (e.g., `BadRequestError` for bad params), redirect there.
- **`inject_settings_env_vars()`** at `llm_config.py:250-286` is UNCHANGED. LiteLLM reads from `os.environ` natively, so the existing settings → env-var pipeline still works.
- **User-facing error messages** preserved as close to current text as possible. Users have muscle memory; the messages get adjusted for env-var setup but keep the same shape.
- **Pricing branch from Phase 0** affects only A.10. Other phases are outcome-independent.

### Next step

Phase 0 spike. Write throwaway `spike_*.py` scripts under `scratchpads/task-158-spike/`. Total expected cost: ~$0.10 of API calls. Need API keys for Anthropic, Gemini, OpenAI to fully validate. Spike deliverable is a markdown report appended below this section before Phase A starts.

If the spike finds blockers (e.g., LiteLLM can't pass `cache_control` on Gemini), pause and reassess library choice. Otherwise proceed to Phase A.1.


---

## 27. Session 2026-04-24 (cont.) — Phase 0 spike executed

Executed the five Phase 0 spike scripts from `scratchpads/task-158-spike/` against live provider APIs. LiteLLM version pinned to **`litellm==1.83.7`** (PyPI — closest-canonical match to the `v1.83.7-stable.patch.1` GitHub Docker tag, and well past the Gemini PR #15226 fix that landed 2025-10-07). Total spike spend: ~$0.04.

### Pass/fail per concern

| Concern | Status | Key finding |
|---|---|---|
| 1. Cache mechanics | PASS | `cache_control` passes cleanly; Anthropic reports via `cache_creation_input_tokens` / `cache_read_input_tokens`; Gemini/OpenAI only via `prompt_tokens_details.cached_tokens`. |
| 2. Composition matrix | PASS | cache + thinking, cache + schema, and all three together all work. Opus cache behavior with thinking needs follow-up (see below). |
| 3. Pricing authority | OUTCOME A | LiteLLM's pricing is more current and comprehensive (2678 vs 41 models); pflow has real bugs. Detail below. |
| 4. Operational | PASS | Quiet logging by default; thread-safe; no hidden config files; 56-package lean footprint. |
| 5. Exceptions | PASS | All current detection patterns map cleanly to `isinstance` on typed LiteLLM exceptions. |

### 1. Cache mechanics

Confirmed LiteLLM accepts the spec's proposed message structure:

```python
{"role": "system", "content": [
    {"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}
]}
```

Results on ~1,200–1,500-token system block:

- **Anthropic Sonnet 4.5:** call 1 `cache_creation_input_tokens=1345`, call 2 `cache_read_input_tokens=1345`. Cost: $0.0052 (write) → $0.00051 (read), matches Anthropic's 0.1× read multiplier. Content returns as `str` at `response.choices[0].message.content`.
- **Gemini 2.5 Flash:** both calls showed `prompt_tokens_details.cached_tokens=1226`. Gemini's *implicit* caching fired on the first call. `cache_creation_input_tokens` is always `None` for Gemini (Anthropic-only field). Cost: $0.00005/call (near-zero).
- **OpenAI gpt-4o-mini:** both calls had `cached_tokens=0` — auto-cache did NOT fire on a 1,173-token prompt (above the 1024 threshold). Not a blocker — spec already treats OpenAI auto-caching as best-effort.

**Finding that affects the adapter:** the `AdapterResponse.usage` dict must normalize two different paths:
- Anthropic: read `usage.cache_creation_input_tokens` / `usage.cache_read_input_tokens` directly.
- Gemini/OpenAI: read `usage.prompt_tokens_details.cached_tokens` and surface it as `cache_read_input_tokens` (no distinction between creation and read from the response alone).

### 2. Composition matrix

All four compositions worked on real calls once I fixed one rule:

- **Anthropic requires `temperature=1.0` when thinking is enabled** — both Sonnet and Opus rejected `temperature=0.0` with a `BadRequestError`. pflow must enforce this at the adapter level (or at least let it through clearly). Current pflow behavior via the `llm` library likely already hits this; worth verifying during A.5.
- Content shape stays `str` across all four compositions. `message.reasoning_content` carries thinking output separately.
- Structured output (`response_format={"type":"json_schema","json_schema":{"name":..., "schema":..., "strict":True}}`) returns valid JSON as a string — not a parsed object. Consumer parsing stays unchanged.
- **Unresolved nuance on Opus:** Opus 4.5 calls with thinking enabled showed `cache_creation_input_tokens=0, cache_read_input_tokens=0` — cache neither wrote nor read, despite ~1,380-token prompt above the Sonnet/Opus threshold. Sonnet in identical conditions did cache-hit. Hypotheses: (a) Opus 4.5 minimum threshold is higher than Sonnet's, (b) extended thinking silently disables cache_control markers, (c) something else provider-specific. Not a blocker for Phase A (the library migration works regardless), but worth flagging for Phase C when cache rendering lands — we may need a per-model-family cache-minimum check.

### 3. Pricing authority → Outcome A

Compared all 41 entries in pflow's `MODEL_PRICING` to LiteLLM's `model_cost` dict (2,678 entries). After correcting for key-format mismatch (pflow uses `anthropic/claude-sonnet-4-5`; LiteLLM keys by `claude-sonnet-4-5`), every model pflow knows about is present in LiteLLM's data. Quality comparison:

- **LiteLLM's data matches pflow on Anthropic** (cache_read = 0.1× input, confirmed per-model).
- **pflow is wrong for non-Anthropic providers' cache multipliers.** The hardcoded `0.1×` input multiplier at `llm_pricing.py:170-171` is Anthropic-specific but applied universally. LiteLLM has correct per-provider values:
  - OpenAI cache_read should be 0.5× input (pflow: 0.1× → 80% too low).
  - Gemini 2.0 Flash cache_read should be 0.25× input (pflow: 0.1× → 60% too low).
- **pflow's `gpt-4o` pricing is outdated:** pflow has `input=$5/M, output=$15/M`; LiteLLM (matching OpenAI's current published prices) has `input=$2.50/M, output=$10/M`. pflow missed OpenAI's 2024 price cut.
- **Gemini PR #15226 fix confirmed present in v1.83.7.** Live cached Gemini 2.5 Flash call: LiteLLM's `response_cost=$5.388e-5`, hand-calc via pflow pricing=$5.400e-5 → 0.22% disagreement, well within the 2% acceptance band.

**Decision: Outcome A — delete `llm_pricing.py` in Phase A.10.**

Adapter replacement strategy:
- Primary path: `litellm.completion_cost(response)` OR read `response._hidden_params["response_cost"]` directly.
- Normalize model-name translation: strip `anthropic/` prefix before lookup where needed (LiteLLM's `completion_cost()` handles this internally, so model-name translation is likely not needed at the adapter level).
- Fallback when `completion_cost()` returns `None` (unknown model): the adapter surfaces `cost_usd: None` in `AdapterResponse.usage`. Consumer code (`enrich_llm_usage_with_cost`) already handles `None` gracefully.
- Net effect: `enrich_llm_usage_with_cost` becomes a one-liner that reads `llm_usage["cost_usd"]` straight from the adapter response. The 41-model maintenance burden disappears; new-model releases show correct costs automatically.

**Spec adjustments required:**
- Design Decision 17, Requirements "Tracing and Cost Reporting" section, and A.10 in the plan all assume some form of `llm_pricing.py` retention. **Outcome A supersedes.** Will update these during Phase A.10; no Phase A.1–A.9 changes needed.

### 4. Operational

- **Logger silencing.** LiteLLM 1.83.7 produces **zero stderr** on a vanilla call — chatter is gone in this version. Still setting `litellm.suppress_debug_info = True` at adapter module import as belt-and-suspenders.
- **Thread safety.** 5 concurrent `litellm.completion()` calls via `ThreadPoolExecutor(max_workers=5)` completed in 0.79s. All 5 succeeded. No shared-state corruption, no httpx races. Mirrors pflow's LLMNode threading model.
- **Env-var key resolution.** Ran LiteLLM with `HOME=/tmp/pflow_spike_clean_home` in a subprocess. Call succeeded using only `GEMINI_API_KEY` from env. Zero non-uv files created in the clean HOME — **LiteLLM has no hidden config files.**
- **Dependency footprint.** Fresh venv install of `litellm==1.83.7` = 56 packages total. **No `boto3`, no `google-cloud-*`, no `azure-*`, no AWS.** LiteLLM doesn't even pull in the `anthropic` SDK (it calls the HTTP API directly via `httpx`). Core deps: `openai`, `httpx`, `pydantic`, `tiktoken`, `tokenizers`, `jinja2`. **No `litellm[proxy]` extras needed.**

### 5. Exception detection

Concrete mapping from pflow's current string-match patterns (`llm.py:435-452`) to LiteLLM typed exceptions, all `isinstance`-detectable:

| Current pflow pattern | LiteLLM exception | Example status_code |
|---|---|---|
| `UnknownModelError` — bad model, known provider | `litellm.exceptions.NotFoundError` | 404 |
| `UnknownModelError` — bad provider prefix | `litellm.exceptions.BadRequestError` (message contains "LLM Provider NOT provided") | 400 |
| `NeedsKeyException` — wrong key | `litellm.exceptions.AuthenticationError` | 401 |
| `NeedsKeyException` — missing key | `litellm.exceptions.AuthenticationError` | 500 (quirky but stable) |
| `Pydantic ValidationError` (PATTERN EXCEPTION, `llm.py:298-311`) | `litellm.exceptions.BadRequestError` | 400 |
| Timeout | `litellm.exceptions.Timeout` | 408 |

All exceptions carry rich attributes: `status_code: int`, `llm_provider: str`, `model: str`, `response: httpx.Response`. Useful for structured error rendering.

All LiteLLM exceptions inherit from `openai.OpenAIError` through `openai.APIError` — one umbrella catch is possible if we want it. The adapter will catch them specifically rather than with a single umbrella.

### Pattern exception decision (ambiguity #4 from session start)

The `Pydantic ValidationError` catch at `llm.py:298-311` was added because llm-library's `model.Options` are Pydantic-validated and a retry won't help. The LiteLLM equivalent is `litellm.exceptions.BadRequestError` (deterministic server-side rejection of malformed requests; retrying will produce the same error).

**Recommendation:** inside the adapter's `complete()` function, catch `litellm.exceptions.BadRequestError` and re-raise as pflow's `NonRetriableError` (or equivalent deterministic-error marker respected by the Node retry loop). That way the adapter is the single seam for both the pydantic case (removed with the llm library) and the new LiteLLM bad-param case. One attempt, clean failure. Keep the existing user-facing error messages close to current text. This is the approach I'll take in A.3 unless you want to discuss further.

### LiteLLM version rationale

**Pinned: `litellm==1.83.7`.** Rationale:
- Matches the `v1.83.7-stable.patch.1` Docker tag the user suggested (closest canonical PyPI release).
- Released ~2026-04-21, 6 months after the Gemini double-count fix (PR #15226, 2025-10-07) — fix confirmed present via live call.
- Zero chatter on stderr; stable API surface; 56-package footprint.
- If the `-stable.patch.1` tag has fixes absent from plain `1.83.7` that we need, we can switch to a git-URL pin during Phase A. No evidence we need that today.

### Confirmed message structure for cache_control across providers

Single structure works cleanly on Anthropic, Gemini, and OpenAI (no-op on OpenAI):

```python
messages=[
    {"role": "system", "content": [
        {"type": "text", "text": "<system text>",
         "cache_control": {"type": "ephemeral"}}
    ]},
    {"role": "user", "content": "<user text>"},
    # or, for attachments/images, nested content blocks as per provider docs
]
```

No need for LiteLLM's `extra_body` passthrough for the system-prompt cache case.

### Spec adjustments to apply during Phase A

1. **A.10 scope collapses** — `llm_pricing.py` deletion is a one-step drop, not a conditional branch. Consumer code (`enrich_llm_usage_with_cost` callers) rewrites to read `cost_usd` from the adapter response.
2. **A.3 adapter responsibility grows slightly** — the adapter now owns `response_cost` extraction AND normalization across providers for cached tokens.
3. **Model-name translation** between pflow's `anthropic/claude-sonnet-4-5` and LiteLLM's `claude-sonnet-4-5` keys: LiteLLM's `completion_cost()` handles this internally, so no translation layer needed at the adapter level. Confirmed by spike evidence on live calls.
4. **Temperature-with-thinking rule** is a real composition constraint; adapter may want a sanity check that raises a clearer error than Anthropic's raw "temperature may only be set to 1 when thinking is enabled". Optional — could defer to reading the error message if it's user-facing.
5. **Opus cache behavior with thinking** flagged for Phase C verification. Not Phase A scope.
6. **CLAUDE.md drift fix:** `core/CLAUDE.md:198` says "46+ models" but the actual count is 41 (and will drop to zero after A.10). Fix during A.12 documentation pass.

### Phase 0 next step

Phase 0 is complete. Requesting user confirmation of the outcome before starting Phase A.

- Outcome decisions: Outcome A (delete `llm_pricing.py`); version pin `litellm==1.83.7`; pattern exception strategy (catch `BadRequestError` in adapter and re-raise as `NonRetriableError` equivalent).
- Spike scripts and raw outputs retained under `scratchpads/task-158-spike/` for reference; not committed.

---

## 28. Session 2026-04-24 (cont.) — Phase A.1 through A.5 implemented

User authorized implementation start with: commits at milestones, skip real-API integration tests for now (RUN_LLM_TESTS-gated), use `pflow settings env` in help-text copy, status updates only at milestones. Branch: `feat/prompt-caching-lite-llm` (worktree at `/Users/andfal/projects/pflow-feat-prompt-caching-lite-llm`).

**5 production+test tasks landed across 4 commits.** All verification steps green at every commit. `tests/test_execution/test_plan_drift.py` (32 tests, sacred parity invariant) green at every step.

### A.1 — LiteLLM install (commit `7babf9e5`)

- Added `litellm` to `[project] dependencies` in `pyproject.toml` alongside `llm`/`llm-anthropic`/`llm-gemini` (do not remove old until A.11).
- **Spec deviation: pinned `litellm==1.82.6`, NOT `1.83.7` from Phase 0.** Reason: every release in the `1.83.x` series (released 2026-03-31 onward) hard-pins `click==8.1.8`, which downgraded our click from 8.3.1 and broke 3 `CliRunner`-based tests that depend on click 8.2+'s default stderr separation (`test_workflow_data_goes_to_stdout_not_stderr_gh194`, `test_shell_stderr_in_json_output`, `test_multiple_stdin_error_json_output`). Confirmed via stash-test: those 3 tests pass under click 8.3, fail under click 8.1. Surveyed 1.84.0+ via PyPI JSON API — issue persists. 1.82.6 (released 2026-03-21) leaves click unconstrained AND contains Gemini PR #15226 (2025-10-07) per release date. User instruction: "be on the lookout if things dont work that worked in phase 0, since we used this newer version when doing that."
- `make check` green (added temporary `DEP002 = ["litellm", ...]` ignore until A.3 imports it).
- `make test` green: 5240 passed, 9 skipped (baseline maintained).

### A.2 — `llm_reasoning_map.py` (commit `0a2eb798` — bundled with A.3)

- New file `src/pflow/core/llm_reasoning_map.py`. Replaces the live `model.Options.model_fields` introspection at the previous `nodes/llm/llm.py:35-114`. LiteLLM has no equivalent contract, so capabilities are detected by model-name string sniffing (mirrors `registry/smart_filter.py:178`'s pattern for Gemini variants).
- **Output shape preserves the legacy llm-library kwarg shape** (e.g. `{"thinking": True, "thinking_budget": N}`). The adapter (A.3) translates Anthropic-specific shapes to LiteLLM-native form. This separation keeps the map's contract testable and isolates LiteLLM-specific shape work to one file.
- `EFFORT_RATIOS` (5 levels: xhigh/high/medium/low/minimal) and `DEFAULT_MAX_TOKENS_BASE = 16000` moved verbatim. **Anthropic Opus 4.5 thinking_effort precedence preserved** (still checked before thinking_budget — the highest-stakes invariant per the plan).
- Capability detection per model family:
  - Opus 4.5 (matches `claude-opus-4-5` / `claude-opus-4.5`): `{thinking_effort, thinking, thinking_budget}` — thinking_effort wins.
  - Other Anthropic (Sonnet 4.x, Opus 4.0/4.1, older): `{thinking, thinking_budget}`.
  - Gemini 3: `{thinking_level}`.
  - Gemini 2.5 (non-lite): `{thinking_budget}`.
  - Gemini 2.5 lite, older Gemini: `set()` (no reasoning).
  - OpenAI gpt-5*, o1*, o3* (and `openai/o1` etc.): `{reasoning_effort, reasoning_max_tokens}`.
  - GPT-4* and unknown: `set()`.
- Tests: `tests/test_core/test_llm_reasoning_map.py` — 60 tests covering each provider/family path, the precedence invariant, edge cases, case insensitivity. All passing. No network.

### A.3 — `llm_client.py` adapter (commit `0a2eb798`)

- New file `src/pflow/core/llm_client.py`. Single seam for all pflow LLM calls. Wraps `litellm.completion`.
- Public API: `complete(*, model, prompt, system, temperature, max_tokens, attachments, schema, reasoning_kwargs, model_options, timeout, trace_hook) -> AdapterResponse`. All keyword-only.
- `AdapterResponse` dataclass: `.text` (str, NOT callable — different from llm library), `.usage` (dict with stable keys: `model`, `input_tokens`, `output_tokens`, `total_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `cost_usd`), `.model`, `.has_schema`, plus `.error` / `.status` for the PATTERN EXCEPTION case.
- `Attachment` dataclass: `kind: "image_url" | "image_path"`, `value: str`. Path attachments are base64-encoded to a `data:...;base64,...` URL at the adapter boundary.
- **PATTERN EXCEPTION moved into adapter.** `litellm.exceptions.BadRequestError` is caught and returned as an error-marked `AdapterResponse` so the Node retry loop doesn't burn 3 attempts on permanent failures. Mirrors the previous `nodes/llm/llm.py:298-311` pattern that caught Pydantic `ValidationError`. Other exceptions (Timeout, AuthenticationError, NotFoundError, RateLimitError) propagate — caller's retry loop decides.
- **Cache-token normalization** handles two provider paths into one stable dict (per Phase 0 finding):
  - Anthropic: read `usage.cache_creation_input_tokens` / `usage.cache_read_input_tokens` directly.
  - Gemini/OpenAI: fall back to `usage.prompt_tokens_details.cached_tokens`, surface as `cache_read_input_tokens` (creation stays 0 — providers don't distinguish in response).
- **Cost via Outcome A path:** read from `response._hidden_params["response_cost"]`. Eliminates the per-model `MODEL_PRICING` maintenance burden once A.10 lands.
- **Anthropic thinking translation:** `_translate_reasoning_for_litellm(model, kwargs)` converts the map's legacy `{thinking: True, thinking_budget: N}` shape into LiteLLM's standardized `{thinking: {type: "enabled", budget_tokens: N}}` (verified by Phase 0 spike spike_2_output.txt). Opus 4.5's `thinking_effort` translates to a derived budget via EFFORT_RATIOS × DEFAULT_MAX_TOKENS_BASE; Gemini and OpenAI shapes pass through unchanged.
- `trace_hook: Callable[[dict], None]` parameter — the seam that will replace the monkey-patch in A.6. Adapter invokes it with `{event: "before_call", model, prompt}` and `{event: "after_call", model, response/error}`. Hook exceptions are swallowed (tracing must never break user workflows).
- Logger silenced at module import: `litellm.suppress_debug_info = True` (belt-and-suspenders — Phase 0 confirmed 1.83.7 is quiet by default; same applies to 1.82.6).
- Tests: `tests/test_core/test_llm_client.py` — 35 tests covering text-only, system+max_tokens, schema, attachments (URL + base64-encoded file), reasoning kwargs (Anthropic translated, Gemini/OpenAI passthrough), model_options merging, timeout, BadRequestError → error-marked response, Timeout/Auth propagation, trace_hook before/after invocation, hook-exception isolation, provider-specific usage normalization (Anthropic vs Gemini vs OpenAI shape). All passing. `litellm.completion` mocked via `unittest.mock.patch`.
- Removed the temporary `litellm` deptry ignore from A.1 — adapter imports it now.

### A.4 — Mock infrastructure (commit `a38afa6d` — bundled with A.5)

- `tests/shared/llm_mock.py`: added `MockLLMClient` returning `AdapterResponse` instances (not `Mock` objects). Shares the `_DEFAULT_RESPONSES` table with the legacy `MockLLMModel` (refactored to read from the same shared dict) — both fixtures resolve identically: exact match → wildcard → schema-default → fallback. Keyed by schema NAME (Pydantic `__name__` or JSON Schema dict `title` — supports both during the migration).
- Preserved the legacy 500-char `call_history[i]["prompt"]` truncation. Added parallel `call_history_full` (untruncated) for future cache-structure tests in Phase B/C — present but not yet required.
- **`MockLLMClient` intentionally OMITS `cost_usd`** from the usage dict it returns. Reason: the real adapter populates `cost_usd` from `response._hidden_params["response_cost"]`, which we can't reasonably mock. Letting it stay absent means `enrich_llm_usage_with_cost` runs the existing pricing-from-tokens path — several tests rely on historical-cost propagation through the memo cache (notably `test_plan_cost_nested_rollup`). Initially I had the mock pre-populate `cost_usd: 0.0`, which broke `test_plan_cost_nested_rollup` because `enrich_llm_usage_with_cost` early-returns when `cost_usd` is already present.
- `tests/conftest.py`: added `mock_llm_client` autouse fixture that patches `pflow.core.llm_client.complete` AND each consumer-module's binding (`pflow.nodes.llm.llm.complete`, `pflow.registry.discovery.complete`, `pflow.registry.smart_filter.complete`, `pflow.core.workflow.discovery.complete`). `raising=False` on the consumer bindings tolerates modules that haven't migrated yet (only LLMNode is wired in A.5).
- **Coexistence retained:** `mock_llm_calls` (legacy) and `mock_llm_client` (new) BOTH active during A.4-A.7. Cleanup happens in A.8 once all callers migrated.

### A.5 — LLMNode rewrite (commit `a38afa6d`)

**Production changes:**

- `src/pflow/nodes/llm/llm.py`:
  - Removed `import llm`, `from pydantic import ValidationError`, `from pflow.core.llm_pricing import enrich_llm_usage_with_cost` is kept (until A.10).
  - Removed local `EFFORT_RATIOS`, `DEFAULT_MAX_TOKENS_BASE`, `_map_direct_budget`, `_map_effort`, `_map_reasoning_options`. Re-exports `EFFORT_RATIOS` and `DEFAULT_MAX_TOKENS_BASE` from `pflow.core.llm_reasoning_map` for backward compatibility (the constants were imported by tests).
  - `prep()` builds `Attachment(kind=..., value=...)` (the new dataclass) instead of `llm.Attachment(url=...)` / `llm.Attachment(path=...)`.
  - `_call_llm()` calls `complete(...)` with `trace_hook=_active_trace_hook()`. The `BadRequestError` PATTERN EXCEPTION is now handled inside the adapter; LLMNode reads `adapter_response.status == "error"` and constructs the same error dict shape as before.
  - `post()` simplified to a single dict-read code path. The legacy object-with-`.input`/`.output`/`.details` branch is gone (the adapter normalizes usage to a stable dict). `cost_usd` from the adapter is preserved through `enrich_llm_usage_with_cost`'s early-return guard.
  - `exec_fallback()` rewritten to use `isinstance` on LiteLLM exceptions (`Timeout`, `NotFoundError`, `AuthenticationError`, `BadRequestError`-with-"LLM Provider NOT provided"). User-facing error strings adjusted minimally to match new help paths: `'llm models'` → `'pflow settings llm show'`; `'llm keys set <provider>'` → `'pflow settings env set'`.
  - New module-level `_active_trace_hook()` helper reads `WorkflowTraceCollector._active_collectors[thread_id]` (the same registry the legacy monkey-patch maintains) and `_thread_local.current_node`, then returns `collector.get_trace_hook(node_id)`. None when no trace is active. Mirrors the "is a collector active" check the monkey-patch did from inside the patched `prompt` function — moved into LLMNode.

- `src/pflow/runtime/workflow_trace.py`: added `WorkflowTraceCollector.get_trace_hook(node_id)` returning a callable that captures `before_call.prompt` into `self.llm_prompts[node_id]` (same destination the monkey-patch wrote to; same downstream consumer in `_attach_llm_call_to_event`). The legacy `setup_llm_interception` / `cleanup_llm_interception` and the monkey-patch are RETAINED during A.5 — still active for the 3 discovery callsites that haven't migrated. Both mechanisms coexist briefly. A.6 deletes the patch.

**Test migration (delegated to test-writer-fixer subagent):**

- `tests/test_nodes/test_llm/test_llm.py` (1148 lines, 61 tests originally; now 73 with new classes) — every `with patch("pflow.nodes.llm.llm.llm.get_model")` block rewritten to use the `mock_llm_client` autouse fixture and assert against `mock_llm_client.call_history[-1]["..."]`. Tests needing specific token counts use `monkeypatch.setattr("pflow.nodes.llm.llm.complete", custom_fn)` returning hand-built `AdapterResponse`. Error-handling tests now raise the LiteLLM exception types directly (`NotFoundError` / `AuthenticationError`). Error-text assertions updated for the new help-path strings.
- Added `TestReasoningEffortValidation` and `TestReasoningKwargsForwarded` classes (12 tests) to `test_llm.py` covering prep validation and kwarg forwarding to the adapter — these replace LLMNode-specific coverage from the old `test_llm_reasoning.py`.
- `tests/test_nodes/test_llm/test_llm_images.py` (12 tests) rewritten to assert against the new `Attachment` dataclass shape (`.kind == "image_url"` / `.value == "..."` instead of `.url` / `.path` on `llm.Attachment`).
- `tests/test_nodes/test_llm/test_llm_reasoning.py` — superseded by `tests/test_core/test_llm_reasoning_map.py` (60 tests covering the mapping logic) plus the new `TestReasoningEffortValidation` / `TestReasoningKwargsForwarded` classes in `test_llm.py`. **Per user instruction, NOT deleted.** Marked with module-level `pytest.skip` so collection is clean; body retained for user review. Per-file `F821, F401` ignore added to `pyproject.toml` for the dead-code body. **Pending deletion checklist for end of Phase A.**
- `tests/test_integration/test_metrics_integration.py` — `test_llm_cost_calculation` and `test_llm_accumulation_across_nodes` rewired to monkeypatch `pflow.nodes.llm.llm.complete` with custom `AdapterResponse`-returning functions (the per-test usage-token control they need). The old bespoke `mock_llm` fixture's `configure_with_usage` helper relied on the legacy llm-library mock path and no longer applies.

**Verification at A.5 completion:**

- `make test`: 5303 passed, 10 skipped, 0 failed.
- `tests/test_execution/test_plan_drift.py`: 32 passed (sacred parity invariant intact).
- `make check`: ruff / ruff-format / mypy / deptry all green.
- Surface intact: every existing workflow runs identically; only `pyproject.toml` and on-disk implementation differ.

### Operational notes from this session

- **Git lock**: encountered a stale 0-byte `index.lock` in the worktree's `.git/worktrees/.../index.lock`, blocking `git restore` and `git add`. ~10 concurrent claude worktrees on this machine — none holding this lock. Removed manually after confirming no active git process owned it. Proceeded with normal commits.
- **No-deletes instruction**: user requested all file deletions be deferred to a post-Phase-A checklist for review. Restored an earlier `git rm tests/test_nodes/test_llm/test_llm_reasoning.py` via `git show HEAD:... > ...` (the lock prevented `git restore`). File now `pytest.skip`'d at module level.

### Deletion checklist (pending user approval)

- `tests/test_nodes/test_llm/test_llm_reasoning.py` — module-level skipped, body is dead code referencing removed APIs (`_map_reasoning_options`, `llm.get_model`, plugin Options classes from `llm_anthropic`). All coverage migrated to `tests/test_core/test_llm_reasoning_map.py` + new `test_llm.py` classes.

### Next step

Phase A.6 — tracing redesign. Delete `setup_llm_interception` / `cleanup_llm_interception` and the monkey-patch from `runtime/workflow_trace.py:520-599`. Keep `_active_collectors` and `_thread_local` (LLMNode reads them). Keep `get_trace_hook` (added in A.5). After A.6 the 3 legacy discovery callsites lose their tracing — that gap closes when A.7 migrates them to the adapter.

`tests/test_execution/test_plan_drift.py` is the canary — must stay green after A.6.

---

## 29. Session 2026-04-24 (cont.) — Phase A.6 + A.7 + A.8 implemented

User confirmed continuation: "go ahead and continue to implement a6,a7 and a8". Three steps landed in one milestone commit (`40b74f8e`). Verification clean at every step. `tests/test_execution/test_plan_drift.py` 32/32 green throughout.

### A.6 — Tracing redesign (commit `40b74f8e`)

**The riskiest single step in the plan.** Outcome: clean, sacred test untouched, no regressions.

`src/pflow/runtime/workflow_trace.py`:

- **Deleted the monkey-patch.** The previous `setup_llm_interception` body (lines 520-599 originally — see plan/braindump for the sophistication: two-layer interception of `llm.get_model` and per-instance `model.prompt`, reference-counted via `_llm_interception_count`, lazy install/teardown) was replaced wholesale.
- **Replaced with a thin per-thread registration step.** New `setup_llm_interception(node_id)` body just (1) sets `_thread_local.current_node = node_id`, (2) registers `_active_collectors[thread_id] = self` under `_llm_lock`, (3) sets `_llm_interceptor_installed = True`. That's it — no patch, no count, no global state to unwind.
- **Class-level state pruned.** Dropped `_llm_interception_count`, `_original_get_model`. Kept `_llm_lock`, `_active_collectors`, `_thread_local` — these are the bridge LLMNode's `_active_trace_hook()` (added in A.5) reads to find the right collector for its current adapter call.
- **`cleanup_llm_interception` simplified** to a thin unregister + idempotent guard. Still called by `WorkflowRunner._cleanup`; semantics preserved.
- **The monkey-patch's job** (capturing the rendered prompt into `collector.llm_prompts[node_id]`) is now done by the trace_hook plumbed through the adapter (see `WorkflowTraceCollector.get_trace_hook` added in A.5). The downstream consumer (`_attach_llm_call_to_event` at `workflow_trace.py:168`) is unchanged — same `llm_prompts` dict, same writer/reader contract.

**Coexistence window briefly violated and noted:** between A.6 (this step) and A.7, the 3 legacy discovery callsites (`registry/discovery.py`, `registry/smart_filter.py`, `core/workflow/discovery.py`) still called `llm.get_model(...).prompt(...)` and now had no tracing — the patch they relied on was gone. The plan acknowledged this gap as acceptable since these callsites don't run inside a workflow trace context anyway. Confirmed by grepping for tests asserting on smart_filter/discovery prompts in trace output: no hits.

**Sacred test verification:** `tests/test_execution/test_plan_drift.py` ran first, in isolation, after the change — 32 passed. Then full suite — 5303 passed.

### A.7 — Three discovery callsites migrated (commit `40b74f8e`)

Mechanical migration. Same pattern across 3 production files:

* `src/pflow/registry/discovery.py::find_components` — was `llm.get_model(resolved_model).prompt(formatted_prompt, schema=ComponentSelectionSchema)`. Now `complete(model=resolved_model, prompt=formatted_prompt, schema=ComponentSelectionSchema.model_json_schema())`.
* `src/pflow/registry/smart_filter.py` — same shape. Plus the Gemini thinking heuristics (the `gemini-3` → `thinking_level=minimal` and `gemini-2.5` → `thinking_budget=0` branches at lines 175-180) now flow through `model_options=` instead of being merged into kwargs at the call site. The adapter forwards `model_options` to LiteLLM verbatim — Gemini accepts these top-level kwargs.
* `src/pflow/core/workflow/discovery.py::find_workflow` — same shape with `WorkflowDecision.model_json_schema()`.

**Pydantic class → JSON Schema dict** at every call site (the adapter only accepts dicts). Used `Class.model_json_schema()` — produces a dict with `title` matching the class name, which `MockLLMClient` reads via `_schema_name()` to look up `_DEFAULT_RESPONSES`.

**`parse_structured_response` already tolerated both shapes** — its line 40 already had `text_output = response.text() if callable(response.text) else response.text`. Zero changes needed.

**21 test failures triggered after the production rewire.** Caused by tests using the legacy `mock_llm_calls.set_response(...)` to configure responses — that mock patches `llm.get_model`, which the production code no longer calls. Tests were getting the autouse `MockLLMClient`'s default response instead.

**Test migration delegated to test-writer-fixer subagent.** Subagent migrated 5 test files:

* `tests/test_registry/test_smart_filter.py` (24 tests) — bulk fixture rename `mock_llm_calls` → `mock_llm_client`. Two monkeypatch tests repointed from `llm.get_model` to `pflow.registry.smart_filter.complete`.
* `tests/test_registry/test_component_discovery.py` (5 tests) — bulk fixture rename.
* `tests/test_core/test_workflow_discovery.py` (6 tests) — bulk fixture rename.
* `tests/test_execution/formatters/test_node_output_formatter.py` (1 of 34 tests) — formatter calls smart_filter; same fixture rename.
* `tests/test_cli/test_nested_workflow_cli.py` (1 of 7 tests) — caught a silent regression-guard bug: test asserted `len(mock_llm_calls.call_history) == 0` to verify zero LLM calls, but after A.5 LLM calls go through the new mock — the assertion would have been a no-op without migration.

**Subagent reported a deptry surprise:** after A.7's production rewire, `make check` failed with `DEP002 'llm' defined as a dependency but not used in the codebase`. Confirmed pre-existing (verified by stashing test changes; deptry still failed). The `llm` package is still used by `tests/conftest.py`'s legacy `mock_llm_calls` fixture (which A.8 removes) and by `tests/test_nodes/test_llm/test_llm_integration.py`'s `has_openai_api_key()` helper (which A.8 also rewrites). Added `llm` temporarily to `DEP002` ignore list with a comment that A.11 removes both the package and the ignore.

### A.8 — Mass test cleanup (commit `40b74f8e`)

**The legacy `mock_llm_calls` autouse fixture is gone.** With every production caller migrated, nothing in production code calls `llm.get_model` anymore. The fixture became dead infrastructure.

`tests/conftest.py`:

- **Deleted `mock_llm_calls` autouse fixture** (was 25 lines patching `llm.get_model`).
- **Deleted `mock_llm_responses` helper fixture** (was a passthrough to the legacy mock — no consumers remained).
- **`mock_llm_client` is now the sole LLM mock.** Same body as before: patches `pflow.core.llm_client.complete` plus each consumer module's `complete` binding.
- Updated docstring to reflect the post-A.8 state.

`tests/shared/llm_mock.py`:

- **Module docstring updated.** `MockLLMModel` / `MockGetModel` / `create_mock_get_model` now marked OBSOLETE — they patched the now-dead `llm.get_model` seam. Per user instruction (no file/symbol deletes during Phase A), the code is retained but unreferenced. Goes on the end-of-task deletion checklist.

**Three tests still using the bespoke `mock_llm` fixture** in `tests/test_integration/test_metrics_integration.py` were migrated:

- `test_trace_captures_llm_calls` — rewritten to monkeypatch `pflow.nodes.llm.llm.complete` with a per-model `AdapterResponse`-returning function. Same structural pattern used in A.5's other `test_metrics_integration.py` migrations (`test_llm_cost_calculation`, `test_llm_accumulation_across_nodes`).
- `test_cost_calculation_accuracy` signature trimmed (it received `mock_llm` but never used it — the test calls `MetricsCollector.calculate_costs()` directly, not through any LLM mock).
- The bespoke `mock_llm` fixture itself **removed from this file** (no remaining consumers). Replaced with an explanatory docstring comment about the migration.

**Two more test files needed minor llm-import cleanup:**

- `tests/test_cli/test_dry_run.py` — line 300's `with patch("requests.request"), patch("llm.get_model")` checked that dry-run does no real LLM/HTTP calls. The `llm.get_model` half is now dead; updated to `patch("pflow.nodes.llm.llm.complete")` to verify zero invocations of the live adapter binding.
- `tests/test_nodes/test_llm/test_llm_integration.py::has_openai_api_key()` — rewritten to read `os.getenv("OPENAI_API_KEY")` directly. Was using `import llm; llm.get_model("gpt-4o-mini")` which would fail at COLLECTION time post-A.11 even though the test is `RUN_LLM_TESTS`-gated. Now resilient to the package removal.

**Final survey of `llm` package references in repo:**

- `src/pflow/runtime/workflow_trace.py` — one docstring mention of the historical `llm.get_model` patch (intentional, for context).
- `tests/shared/llm_mock.py` — the obsolete `MockLLMModel` / `MockGetModel` code retained per user instruction.
- `tests/conftest.py` — one docstring mention.
- `tests/test_registry/test_smart_filter.py` — two docstring mentions saying `llm.get_model` is "the dead seam".
- `tests/test_nodes/test_llm/test_llm_reasoning.py` — pytest.skip'd file, body has commented-out references.

Zero live production or test code references the `llm` package. A.11 can drop it cleanly.

### Verification at A.6+A.7+A.8 completion

- `make test`: 5303 passed, 10 skipped, 0 failed.
- `tests/test_execution/test_plan_drift.py`: 32 passed.
- `make check`: ruff / ruff-format / mypy / deptry all green.

### Updated deletion checklist

Items pending user-approved deletion at end of Phase A:

1. `tests/test_nodes/test_llm/test_llm_reasoning.py` (entire file) — pytest.skip'd at module level. All coverage migrated to `tests/test_core/test_llm_reasoning_map.py` + new `TestReasoningEffortValidation` / `TestReasoningKwargsForwarded` classes in `tests/test_nodes/test_llm/test_llm.py`.
2. `MockLLMModel`, `MockGetModel`, `create_mock_get_model` in `tests/shared/llm_mock.py` — unreferenced after A.8. The shared `_DEFAULT_RESPONSES` table and `_schema_name()` helper STAY (used by `MockLLMClient`).
3. `setup_llm_interception` / `cleanup_llm_interception` in `src/pflow/runtime/workflow_trace.py` — no longer dead post-A.6 (the engine still calls them for thread-local registration), but the *names* now mislead. Could rename to `register_for_llm_call` / `unregister_from_llm_call` in a follow-up task. Out of Phase A scope unless desired.
4. The temporary `DEP002 = ["llm", ...]` entry for the `llm` package — A.11 drops it along with the package itself.

### Phase A.9-A.12 sizing notes (forward-looking)

- **A.9** — `llm_config.py` cleanup. Drop `_has_llm_key()` (~46 lines, subprocess-shells `llm keys get`), `get_llm_cli_default_model()` (~40 lines), `LLM_COMMAND` and `_LLM_KEYS_SUBCOMMAND` constants. Update help text in `cli/commands/settings.py` (3 sites). Consider removing the `S603` ignore in `pyproject.toml` if no subprocesses remain in `llm_config.py`. Existing tests for the subprocess paths need to either be updated or skipped. Medium effort, low risk.
- **A.10** — Delete `llm_pricing.py`. **Carries the only remaining real decision in Phase A:** the `MockLLMClient` currently OMITS `cost_usd` from its usage dict so `enrich_llm_usage_with_cost` runs the existing pricing-from-tokens path (load-bearing for `test_plan_cost_nested_rollup` — the historical-cost propagation test). Once `llm_pricing.py` is gone, that fallback evaporates. Two options:
  - **(a, recommended)** Mock returns `cost_usd: 0.0`. Tests that asserted `cost > 0` either inject custom adapter responses (the pattern already used in A.5/A.8 for `test_metrics_integration.py`) or drop the assertion as redundant — pricing is now LiteLLM's responsibility, not pflow's. ~6-10 tests affected. Most honest.
  - **(b)** Mock returns a fake-but-nonzero cost. Keeps tests roughly working but is a fiction.
  - **User input requested before implementing.** Don't flip a coin.
- **A.11** — Drop `llm` / `llm-anthropic` / `llm-gemini` from `pyproject.toml`, drop the temporary DEP002 entries, `uv sync`. Mechanical, low risk. Verify with `uv pip list | grep -E '^(llm|llm-)'` returns nothing.
- **A.12** — Documentation pass. Update `core/CLAUDE.md` (remove the "46+ models" claim and the `llm_pricing.py` section), `nodes/llm/CLAUDE.md` (point at the adapter), grep mintlify docs for `llm keys` / `llm models` references. Pure text editing.

### Next step

Recommended handoff point. Phase A.1-A.8 finishes the structural migration; A.9-A.12 is independent cleanup that benefits from a fresh agent's focused attention on a smaller scope. The A.10 mock-cost decision benefits from clean eyes.

A handoff braindump similar to `braindump-phase-0-and-A-handoff-2026-04-24.md` would help — covering what's still pending, the A.10 decision, the deletion checklist, and the surprises from A.1-A.8 (litellm 1.83.x click pin downgrade, the `cost_usd` mock subtlety, the git lock incident).

---

## 30. Session 2026-04-25 — Phase A.9–A.12 + end-of-task cleanup landed

User authorized continuation: commits at milestones, real-API integration tests skipped (`RUN_LLM_TESTS=1`), use `pflow settings env --help` to verify the actual command name, status updates only at milestones. Per-step task tracking via `TaskCreate`/`TaskUpdate` to keep state visible across the long session. **6 commits landed across A.9–A.12 + cleanup. `tests/test_execution/test_plan_drift.py` (32 sacred parity tests) green at every step.**

### A.9 — `llm_config.py` and `settings.py` cleanup (commit `5d0e0a9b`)

- **Spec deviation discovered: the actual command is `pflow settings set-env`, NOT `pflow settings env set` as both braindumps assumed.** Verified via `pflow settings --help` before writing any help-text copy. Used the real command name throughout.
- `src/pflow/core/llm_config.py`: dropped `_has_llm_key()` (~46 lines, the `llm keys get` subprocess), `get_llm_cli_default_model()` (~40 lines, the `llm models default` subprocess), `_get_validated_llm_path()`, `LLM_COMMAND` and `_LLM_KEYS_SUBCOMMAND` constants, plus the `subprocess` and `shutil` imports. `_has_provider_key()` simplified to two sources (env + pflow settings). `_detect_default_model()` lost its `PYTEST_CURRENT_TEST` guard — the guard existed to prevent subprocess hangs and there's no subprocess to guard. `inject_settings_env_vars()` UNCHANGED (still preserves the test guard for env-pollution prevention — asymmetry intentional and documented in its docstring).
- Help text: `get_llm_setup_help()` and `get_model_not_configured_help()` rewritten to use `pflow settings set-env <KEY> <value>` and shell `export` instead of `llm keys set <provider>`. `get_default_workflow_model()` now resolves: settings → auto-detect → None (3 tiers, was 4 with the dead llm-CLI step).
- `src/pflow/cli/commands/settings.py`: settings group docstring no longer mentions Simon Willison; `_get_resolved_model()` dropped its `get_llm_cli_default_model` import; `llm_show` resolution-order text and `llm_unset` "default" message updated.
- `pyproject.toml`: dropped the `S603` per-file ignore for `llm_config.py` (no subprocess remains in the file).
- Tests: 9 dead tests removed (`TestGetLlmCliDefaultModel` class entirely; 3 `TestGetDefaultWorkflowModel` tests for the llm-CLI fallback chain; `test_pytest_environment_skips_detection`; `test_falls_back_to_llm_cli`). Two replacement tests written (`test_detection_only_uses_env_and_settings`, `test_returns_false_when_neither_env_nor_settings_have_key`). `TestGetModelNotConfiguredHelp` rewritten to expect `pflow settings` guidance and reject the removed `llm models default`/`llm keys list` text. `tests/test_runtime/test_compiler_llm_model.py` got the same help-text assertion update.
- Manual verification: `pflow settings llm show` and `pflow settings --help` produce sensible output with no llm-CLI references.

### A.10 — Delete `llm_pricing.py` (commit `8247ae2a`)

The one step in A.9-A.12 with a real architectural question. **The user pushed back on my initial framing** — "what's the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?" — and asked for the simplest end-state, not the easiest migration.

Reframed the decision. Initial options I'd offered:
- **(a)** Mock returns `cost_usd: 0.0` → tests inject custom AdapterResponse where they care
- **(b)** Mock returns fake-but-nonzero cost via formula

Both are fictions. Production never returns `0.0` for a real call, and pflow has no formula like (b). The user's framing surfaced a third option that matches what production actually does:

- **(c) Mock default is `cost_usd: None`. Tests that care set it explicitly via `set_response(..., cost_usd=...)`.** Mirrors real production behavior when LiteLLM has no pricing data (custom endpoints, brand-new models, Ollama).

User picked (c). Implementation:
- DELETE `src/pflow/core/llm_pricing.py` (188 lines: `MODEL_PRICING`, `MODEL_ALIASES`, `calculate_llm_cost`, `get_model_pricing`, the inline `enrich_llm_usage_with_cost` math).
- MOVE `enrich_llm_usage_with_cost` to `pflow.core.llm_client` as a 10-line wrapper. Single responsibility: ensure `cost_usd` key is present (preserve when set; mirror Claude Code SDK's `total_cost_usd`; otherwise None). No pricing math.
- Production callers (`metrics.py`, `nodes/llm/llm.py`, `runtime/engine/instrumentation.py`, `runtime/engine/batch_executor.py`) updated to import from the new location.
- `core/__init__.py` docstring updated.
- `MockLLMClient.set_response()` extended with optional `cost_usd=None` kwarg; `_get_cost()` lookup mirrors `get_response()`'s resolution chain. Default usage dict has `cost_usd: None`.
- 15 test failures from the production deletion, all fixed in the same commit:
  - `test_metrics.py`: rewrote 4 tests, removed `test_cost_calculation_for_different_models`
  - `test_metrics_thinking_cache.py`: removed 2 pricing-math tests, updated 1
  - `test_metrics_integration.py`: updated 2 tests, removed `test_cost_calculation_accuracy`
  - `test_unknown_model_user_experience.py::test_mixed_models_shows_partial_cost_clearly` renamed to `test_mixed_priced_unpriced_shows_partial_cost_clearly` (the relevant split is now "has cost_usd vs doesn't", not "known vs unknown model")
  - `test_instrumented_wrapper.py`: rewrote 2 tests to verify the new contract (cost preserved when set, None when not)
  - `test_plan_drift.py::test_plan_cost_nested_rollup` now takes the `mock_llm_client` fixture and pins exact cost (sharper than the prior `> 0` checks)
- `core/CLAUDE.md`: replaced the `llm_pricing.py` section with a new `llm_client.py` section that documents the cost-from-LiteLLM contract. Removed the "46+ models" / "Broken aliases" claims.
- Test pytest.skip pattern: `tests/test_core/test_llm_pricing.py` skipped at module level pending deletion (matches the A.5 `test_llm_reasoning.py` pattern).

### A.11 — Drop `llm`/`llm-anthropic`/`llm-gemini` deps (commit `4becef96`)

Mechanical. Dropped the three packages from `[project] dependencies`, removed the temporary `DEP002 = ["llm", "llm-anthropic", "llm-gemini", "PyYAML"]` ignore entries (left just `["PyYAML"]`), removed the obsolete commented-out `[project.optional-dependencies]` stub, regenerated `uv.lock` via `uv sync`. `uv pip list | grep -iE '^(llm|llm-)'` returns empty (only `litellm 1.82.6` remains). `grep -rn 'import llm$|from llm import' src/ tests/` returns zero hits.

### A.12 — Docs pass (commit `6222697f`)

Seven files touched:
- `docs/quickstart.mdx`: dropped the now-invalid "If you already have llm installed and configured" tip; replaced the "Simon Willison's llm" pointer with LiteLLM's provider list; added a tip showing the env-var path works too.
- `docs/reference/nodes/llm.mdx`: rewrote the intro and replaced the "Extending with plugins" section (which described `llm-openrouter` / `llm-ollama` plugin install) with a simpler "Other providers" section noting that LiteLLM speaks 100+ providers natively. OpenRouter and Ollama get concrete examples without plugin install.
- `docs/reference/cli/settings.mdx`: dropped the "If you use Simon Willison's llm" alternative; removed the `llm models default` step from the model-resolution chain.
- `docs/roadmap.mdx`: updated the "Unified model support" current-status line to credit LiteLLM and note 100+ provider count.
- `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` and `mcp-sandbox-agent-instructions.md`: rewrote the "For LLM providers" blocks to use `pflow settings set-env` and shell env vars; replaced `llm keys set provider` cheatsheet line with `pflow settings llm show`.
- `src/pflow/nodes/llm/README.md`: end-to-end rewrite of the installation section. Provider keys via `pflow settings set-env` or shell env vars; OpenRouter and Ollama first-class without plugin install. Token-usage example updated to show `cost_usd`.

One intentional retention documented in the commit message:
- `src/pflow/core/llm_reasoning_map.py:4` — historical context explaining *why* the file exists (the `llm` library's introspection contract LiteLLM doesn't replicate). Removing this would erase the design rationale.

### Migration: user's `llm`-stored keys into pflow settings

Outside of Phase A scope but the user asked, so we did it. Used the original `/Users/andfal/projects/pflow` worktree (where the `llm` CLI is still installed) to fetch keys via `uv run llm keys get <provider>`, piped each into shell variables, then `pflow settings set-env <KEY_NAME> "$VAR"`. Three keys migrated: `ANTHROPIC_API_KEY` (overwrote prior pflow settings entry), `GEMINI_API_KEY` (new), `OPENAI_API_KEY` (new). Used shell variables to keep secret values out of command history.

### Smoke test on real Gemini-3-flash-preview

User asked for end-to-end verification despite the "skip integration tests" guidance. Wrote a minimal `/tmp/smoke-task158.pflow.md` workflow with one LLM step that tells Gemini to reply `"SMOKE_OK"`. Total spend: ~$0.0005.

**First run uncovered a pre-existing UX issue (NOT a Phase A regression):** Gemini-3-flash-preview is a reasoning model. With `max_tokens: 16`, all 13 emitted tokens went to internal reasoning (`reasoning_tokens: 13, text_tokens: 0, finish_reason: length`) — `response.choices[0].message.content` was None and the adapter normalized it to `""`. pflow surfaced this as `result.result == ""` with no warning. The same call pre-Phase-A would have hit identical behavior — it's the model architecture, not the adapter — but the UX is poor. Worth a follow-up issue to detect "reasoning model + low max_tokens + zero text_tokens" and emit a clear warning.

Second run with `max_tokens: 1024` and `reasoning_effort: minimal` succeeded:
- Real LiteLLM call: 1.4s, $0.000483 ($0.0001 from `pflow report`)
- Response text: `'SMOKE_OK'` end-to-end through `result.result`
- `cost_usd` from LiteLLM `_hidden_params['response_cost']`: `0.0004825`
- Token counts: 23 input + 157 output (13 visible + 144 reasoning)
- Trace populated: `llm_call`, `llm_response` ('SMOKE_OK'), `node_output.response` ('SMOKE_OK'), `cost_usd` matched
- `total_cost_usd` rolled up correctly to top-level metrics
- `reasoning_effort: minimal` flowed cleanly through `llm_reasoning_map` → adapter → Gemini
- `models_used: ["gemini/gemini-3-flash-preview"]`

Phase A's adapter, tracing redesign, and cost-from-LiteLLM contract all verified end-to-end on a real provider call.

### End-of-task cleanup (commit `ac257fc6`)

User asked for the deletion checklist + rename to land before PR. All 5 items processed in one commit (1041 lines deleted, 55 added):

1. DELETED `tests/test_nodes/test_llm/test_llm_reasoning.py` — entire file. Coverage already migrated to `test_llm_reasoning_map.py` + new classes in `test_llm.py`.
2. DELETED `tests/test_core/test_llm_pricing.py` — entire file. Production module gone; nothing to test.
3. DELETED `MockLLMModel`, `MockGetModel`, `create_mock_get_model` from `tests/shared/llm_mock.py`. Kept the shared `_DEFAULT_RESPONSES` table and `_schema_name()` helper. Updated `tests/shared/README.md` to document the new state (replaced the legacy mock entries with `MockLLMClient` documentation).
4. Dropped the two `[tool.ruff.lint.per-file-ignores]` entries (F821, F401) for the deleted test files.
5. Renamed `WorkflowTraceCollector.setup_llm_interception` → `register_for_llm_call` and `cleanup_llm_interception` → `unregister_from_llm_call`. Same rename for the module-level engine wrapper in `runtime/engine/instrumentation.py`. Updated the 3 callsites: `runtime/engine/engine.py` (import + call), `execution/runner.py` (cleanup `hasattr` + call). Docstring touch-ups in `nodes/llm/llm.py::_active_trace_hook`, `runtime/workflow_trace.py::get_trace_hook`, and `runtime/engine/CLAUDE.md` (lifecycle diagram + registration entry). The renamed methods carry a docstring note explaining the prior name as historical context.

Two retained references are intentional historical context documenting *why* the current code looks the way it does:
- `runtime/workflow_trace.py:566` — the renamed method's docstring mentions `setup_llm_interception` to explain the rename.
- `tests/test_integration/test_metrics_integration.py:21` — comment referencing the obsolete `mock_llm` fixture that was removed in A.5.

### Final state at handoff

- `make test` — 5266 passed, 0 skipped, 0 failed
- `make check` — ruff, ruff-format, mypy, deptry all green
- `tests/test_execution/test_plan_drift.py` — 32 passed (sacred parity invariant intact across all 6 Phase A.9-A.12+cleanup commits)
- `uv pip list | grep -iE '^(llm|llm-)'` — empty (only `litellm 1.82.6` present)
- `grep -rn 'import llm$|from llm import' src/pflow/ tests/` — zero hits
- Real-API smoke test on Gemini-3-flash-preview confirmed end-to-end behavior matches design

### Branch summary (since `8349df88` baseline)

```
8349df88 ready for phase 0 + a    ← baseline
7babf9e5 A.1: install LiteLLM
0a2eb798 A.2 + A.3: reasoning_map + adapter
a38afa6d A.4 + A.5: mock + LLMNode rewire
40b74f8e A.6 + A.7 + A.8: tracing + discovery + cleanup
5d0e0a9b A.9: drop llm CLI subprocess paths
8247ae2a A.10: delete llm_pricing.py
4becef96 A.11: drop llm/llm-anthropic/llm-gemini deps
6222697f A.12: docs pass
ac257fc6 end-of-task cleanup     ← current HEAD
```

### Loose ends acknowledged but not blockers

1. **Memoization cache transient regression** — old cached `llm_usage` entries lacking `cost_usd` will surface as `cost_basis: upper_bound` / `estimated_cost_usd: null` in dry-run plans for ~24h post-upgrade until the cache TTL flushes. Self-healing.
2. **Gemini-3 reasoning-model UX** — `max_tokens` too small for a reasoning model silently produces empty content. Pre-existing behavior, not Phase A regression. Worth a follow-up issue.

### Next step

Phase A is feature-complete and ready for review. The next agent's job is to review this implementation before PR merge. A `braindump-phase-A-review-handoff-2026-04-25.md` covering review angles, risks to scrutinize, and verification commands is being written separately.

After review approval and PR merge, the next work is writing the `implementation/plan-phase-B-through-G.md` informed by the concrete LiteLLM behavior observed during Phase A.

---

## 31. Session 2026-04-25 (cont.) — Phase A code review + 6 follow-up commits

User invoked `/code-review` on the full Phase A branch. Six review agents deployed in parallel: `review-silent-failures`, `review-concurrency-safety`, `review-impact-completeness`, `review-test-fidelity`, `review-feature-interactions`, `review-agent-ux`. Across ~30 distinct findings, the orchestrator triaged into 12 action items (3 critical / 7 high-value / 9 medium / 8 pre-existing-or-cosmetic). Items 1–8, 10–12 implemented; **item 9 dropped after evidence; item 3 was the substantial architectural change** (its own isolation pass, its own plan + plan-review).

**Final state**: 5284 tests pass (5266 baseline + 18 new), `test_plan_drift.py` 32 sacred tests green throughout, `make check` green, real-API smoke test confirms `event["llm_prompt"]` now populates end-to-end. Six new commits since `ac257fc6` — branch ready for the user-deferred independent code review.

### The biggest finding from the review

**The `trace_hook` abstraction added in Phase A.6 was non-functional in production.** The engine registered the collector against the main thread's id (`_active_collectors[main_thread_id] = collector`) but `LLMNode._call_llm` runs inside an inner `ThreadPoolExecutor(max_workers=1)`. The worker thread's `threading.get_ident()` never matched the registered id, so `_active_trace_hook()` returned `None` for every adapter call. The adapter's `trace_hook` parameter was wired correctly but never actually invoked.

Verified by smoke test against real Gemini-3-flash-preview: trace JSON had `llm_call` ✓ and `llm_response` ✓ but `llm_prompt` ✗ for every literal-prompt LLM node. `pflow report`'s `## Prompt` section was consequently missing for those nodes (the fallback at `trace_report.py:810` only fires for template-based prompts via `template_resolutions["prompt"]["resolved"]`).

This was caught by `review-concurrency-safety` Finding 1 with empirical reproduction against pre-Phase-A code (commit `8349df88`'s `setup_llm_interception`/`intercept_prompt`) — i.e. the bug pre-dated Phase A; the Phase A.6 monkey-patch removal didn't fix it because the same thread-id mismatch was inherited. Item 3 is the genuine fix.

### The 12 action items and their disposition

Items 1, 4, 5, 6, 7, 8, 11, 12 — trivial doc/test fixes, batched into commits 1–3. Items 2, 10 — adapter contract changes, batched into commit 4. Item 3 — the trace refactor — own commit pair (5+6). Item 9 dropped after spike.

| # | Topic | Resolution |
|---|---|---|
| 1 | `pflow settings env set` typo at `nodes/llm/llm.py:348` | Fixed to `pflow settings set-env <KEY> <value>` |
| 2 | Discovery callers don't honor `AdapterResponse.status == "error"` | Option F: adapter raises `LLMCallError` instead of returning error-marked response — see "Item 2 design pivot" below |
| 3 | `trace_hook` worker-thread mismatch | Refactor to shared-store seam — see "Item 3 architecture" below |
| 4 | Missing test: Opus 4.5 effort+max_tokens precedence | Added `test_opus_45_max_tokens_takes_precedence_over_effort` in `test_llm_reasoning_map.py` |
| 5 | Missing test: `enrich_llm_usage_with_cost` `total_cost_usd` mirror branch | Added `TestEnrichLlmUsageWithCost` (5 tests) in `test_llm_client.py` |
| 6 | Missing test: smart_filter Gemini heuristics → `model_options` | Added `TestGeminiThinkingHeuristics` (5 parametrized tests) in `test_smart_filter.py` |
| 7 | Stale `tests/CLAUDE.md` + `TESTING.md` | Rewritten — see "Doc cleanup" below |
| 8 | 7 doc-drift sites referencing removed code | Fixed all (CLAUDE.md trees, settings docstring, mintlify, llm.py:58, two warning strings) |
| 9 | Anthropic temperature+thinking pre-validation | **DROPPED** after spike — see "Item 9 dropped" below |
| 10 | Empty-response warning for reasoning models | Added warning in `_normalize` when `text == "" and output_tokens > 0 and finish_reason in ("length", "max_tokens")` |
| 11 | Unknown-model error: include LiteLLM provider list URL | Added `https://docs.litellm.ai/docs/providers` in `NotFoundError` tip |
| 12 | Note on 24h memo cache transient | Captured in this progress log (loose ends section) — no docs change required |

### Item 2 design pivot — Option F (adapter raises typed exception)

The original review proposal was a `raise_for_status()` method on `AdapterResponse` called from `parse_structured_response`. User pushed back: "make sure this is the best possible solution before implementing." The simpler answer surfaced:

**Option F**: adapter raises `LLMCallError` (new in `core/exceptions.py`) on `BadRequestError` instead of returning an error-marked response. **This deletes the `error` and `status` fields from `AdapterResponse` entirely** — the dataclass becomes "successful response only". LLMNode catches `LLMCallError` at its single `_call_llm` boundary to preserve PATTERN EXCEPTION semantics (no retry burned). Discovery callers let it propagate naturally. smart_filter's existing `except Exception` still catches it (intentional graceful degradation).

**Net effect**: `AdapterResponse` has a single contract (success). One try/except in LLMNode replaces the `if adapter_response.status == "error"` check. Discovery callers get correct error handling for free with zero callsite changes. Trace hook still fires `after_call` with `error` set BEFORE the raise, so traces capture the failure.

Test impacts: deleted assertions on `response.status == "ok"`/`response.error is None` (the fields no longer exist); rewrote `test_bad_request_returns_error_marked_response` → `test_bad_request_raises_llm_call_error`; rewrote `test_invoked_after_on_bad_request` to wrap in `pytest.raises(LLMCallError)`.

### Item 3 architecture — shared-store seam

**Plan written, plan-reviewed by 3 agents, design refined, then implemented.** Plan file at `/Users/andfal/.claude/plans/magical-swinging-taco.md` (also exported above into the implementation directory if/when needed).

**Initial design used a NEW shared key `_pflow_current_node`. Plan-review C1 caught that `node.node_id` is already a compiler-set dynamic attribute** (`compilation/compiler.py:299`, documented at `compilation/CLAUDE.md:43,155`). LLMNode.prep just reads `getattr(self, "node_id", None)`. **No new shared key needed.** This is a strictly simpler final state — one less mutation site, one less key invention.

**The seam reuses the existing `_trace_collector` shared key.** Already in `_PROPAGATED_KEYS` at `workflow_executor.py:118-126`, already installed by runner at `runner.py:490`, already read by formatters (`success_formatter.py:64`, `error_formatter.py:84`, `cli/error_output.py:134`). The "dual identity" — `_PROPAGATED_KEYS` copies the parent's `_trace_collector` into child_storage, but the child engine has its own `child_trace` from its constructor — is exactly what `engine.run` save/restore resolves: the child's collector overrides the propagated parent value for the duration of the child run, then the parent's value is restored.

**Save/restore design — the `pop` discovery:**
- Initial design used `.pop()` style (mirroring `_pflow_child_only_node` at `engine.py:157`).
- Step 2 verification crashed `tests/test_runtime/test_compile_once_regression.py::test_storage_mode_shared_through_engine` with `'NamespacedSharedStore' object has no attribute 'pop'`.
- **NamespacedSharedStore (`runtime/engine/namespaced_store.py`) doesn't implement `pop`.** It implements `update`, `__setitem__`, `__getitem__`, `__contains__`, `get`, `setdefault`, `keys`, `items`, `values`, `__iter__`, `__len__` — but not `pop` or `__delitem__`. CLAUDE.md note at `runtime/engine/CLAUDE.md` (the inherited one) does call out that any new proxy subclass must override mutation methods explicitly — but `pop` was never needed before, so it wasn't added.
- **Fix**: switch to unconditional write-back (`shared["_trace_collector"] = saved_trace` in finally, even when `saved_trace is None`). All consumers use `.get()` (verified by review-impact-completeness W3 and re-verified during Step 2), so writing `None` back is indistinguishable from key absence to every reader.
- **This is a critical context point for any future shared-store-key save/restore pattern**: don't use `.pop()` on `shared` if your key might be visible to a sub-workflow's `NamespacedSharedStore`. The `_pflow_child_only_node` precedent at `engine.py:157` only works because that key is set/cleared within the parent's `_run_node_with_child_only` method, which operates on the parent's regular dict (not a child's namespaced store).

**Free behavior fixes (intentional, no regressions)** — flagged in commit message:
1. `event["llm_prompt"]` now populates in trace JSON for every non-batch LLM call. `pflow report` gains the `## Prompt` section for nodes that previously had it missing (literal prompts).
2. Sub-workflow LLM prompts now correctly land in the child collector's `llm_prompts` under the child node's id (was being captured as part of parent's WorkflowExecutor event when the trace_hook would have fired at all, which it didn't).
3. Cross-test stale-collector contamination eliminated — no class-level globals to leak across tests.

**Deletions in commit `96003f3c`** (~110 lines):
- `WorkflowTraceCollector._active_collectors`, `_thread_local`, `_llm_lock`, `_llm_interceptor_installed` class state
- `WorkflowTraceCollector.register_for_llm_call` + `unregister_from_llm_call` methods
- `WorkflowTraceCollector.enable_llm_interception` instance flag (and the line in `workflow_executor.py:343` that set it on child collectors — no longer needed because save/restore handles inheritance)
- `_active_trace_hook()` function in `nodes/llm/llm.py`
- `register_for_llm_call(...)` wrapper in `instrumentation.py` + its call site in `engine.py::_execute_node` + import
- `unregister_from_llm_call` cleanup call in `runner.py::_cleanup`
- `threading` import in `workflow_trace.py` and `nodes/llm/llm.py`; `ClassVar` import in `workflow_trace.py`

**The engine `_execute_node` step numbering keeps a gap (no step 1)** — preserved with an explanatory comment because the step numbers are referenced by `runtime/engine/CLAUDE.md` (steps 17.5, 16, etc.) and renumbering would cascade. The deleted step 1 was "LLM interception"; the comment now says: "(Step 1 — LLM trace registration — removed in Task 158 Phase A post-cleanup. The trace collector is now installed by `run()` into `shared['_trace_collector']` and resolved by `LLMNode.prep()` directly. Lifecycle step numbers below preserved for cross-reference with engine/CLAUDE.md.)"

### Item 9 dropped — what the spike showed

Reviewers (`review-feature-interactions` W1, `review-agent-ux` #6) flagged that Anthropic models with thinking enabled require `temperature=1.0` and proposed pre-validation in `LLMNode.prep`. User pushed back: "doesn't the llm library output correct error as is? can we investigate what errors we are getting from this problem right now for 3 different anthropic models including opus 4.5 and sonnet 4.5 and sonnet 4.6 or something."

**Spike: `scratchpads/task-158-spike/spike_6_temp_thinking_errors.py`** — calls `litellm.completion` with `temperature=0.0` + thinking enabled against Opus 4.5, Sonnet 4.5, Sonnet 4.6, Haiku 4.5. All four models returned IDENTICAL `BadRequestError`:

```
litellm.BadRequestError: AnthropicException - {"type":"error","error":{"type":"invalid_request_error","message":"`temperature` may only be set to 1 when thinking is enabled. Please consult our documentation at https://docs.claude.com/en/docs/build-with-claude/extended-thinking#important-considerations-when-using-extended-thinking"},"request_id":"req_..."}
```

**This message has all four ingredients of an actionable error**: WHAT broke (`temperature may only be set to 1 when thinking is enabled`), HOW to fix (set temperature to 1), WHERE to learn more (documentation link), and diagnostic context (`status_code`, `llm_provider`, `model`, `request_id`). It's identical across all 4 Anthropic models — Anthropic treats this as a single API rule, not a per-model quirk.

Pflow already handles this cleanly: PATTERN EXCEPTION catches `BadRequestError` (no retry burned) → adapter raises `LLMCallError` with the message preserved → LLMNode converts to error dict → user sees the actionable message.

**Pre-validation would have**: duplicated a server-side rule (drift risk if Anthropic relaxes it for some future model), saved one network call (~$0 cost since the request is rejected before tokens are consumed), saved zero retries (PATTERN EXCEPTION already prevents them). The cost/benefit was bad. Item dropped.

Spike script kept under `scratchpads/task-158-spike/` as runnable evidence.

### Operational gotchas an agent might hit

1. **NamespacedSharedStore lacks `pop`** — see "Save/restore design" above. Any new shared-store-key save/restore must use unconditional write-back, not `.pop()`. Documented in commit `96003f3c`'s message.

2. **`monkeypatch.setattr` on lazy-imported functions must target the SOURCE module.** `smart_filter.py:166` does `from pflow.core.llm_config import get_model_for_feature` INSIDE the function body. Patching `pflow.registry.smart_filter.get_model_for_feature` fails (`AttributeError: module has no attribute`). Must patch `pflow.core.llm_config.get_model_for_feature`. Caught during step 5 test development (item 6).

3. **`MockLLMClient` in `tests/shared/llm_mock.py:219-221, 251-253` fires `trace_hook` automatically** when one is provided. Sufficient for unit tests of the new path. The trace_hook contract (signature `Callable[[dict], None]` invoked with `{"event": "before_call", ...}` and `{"event": "after_call", ...}`) is honored by the mock.

4. **The engine `_execute_node` step numbering has an intentional gap** at step 1 (was LLM trace registration, now done by `run()` + LLMNode.prep). Don't renumber — the higher numbers (16, 17.5) are referenced from CLAUDE.md and code comments; cascading renumbering would be churn for no benefit.

5. **`_PROPAGATED_KEYS` propagation timing**: child_storage gets `_trace_collector` = parent's collector copied in by `_create_child_storage` (workflow_executor.py:681-683), THEN `engine.run` save/restore swaps in the child's own collector. The two mechanisms are sequential, not racing. Verified by review-concurrency-safety W4.

6. **Comment in `workflow_trace.py:_add_llm_data` updated** to reflect the new sub-workflow flow (each engine.run installs its own collector; child events bubble up via `sub_workflow_events`). The old comment referenced `enable_llm_interception=False` which no longer exists.

### What was NOT addressed (intentional — pre-existing or out of scope)

These were flagged by reviewers but explicitly deferred:

1. **Parallel batch LLM per-item prompt indexing** — `collector.llm_prompts[node_id]` is keyed by node_id, so parallel items share the batch wrapper id and overwrite. Pre-existing limitation (NOT introduced by item 3 refactor). Per-item indexing would require either writing prompts to `node_output` so `_capture_item_trace` picks them up, or keying `llm_prompts` by `(node_id, batch_idx)`. **Test #4 in item 3's plan was REMOVED** before implementation after both `review-concurrency-safety` W6 and `review-impact-completeness` W4 flagged this independently. The new test #4 (parallel batch of SUB-WORKFLOWS containing LLMs) tests a different, properly-isolated case.

2. **PATTERN EXCEPTION scope expansion** — adapter only catches `BadRequestError` and subclasses (`UnsupportedParamsError`, `ContentPolicyViolationError`, `ContextWindowExceededError`, `InvalidRequestError`). Other deterministic errors — `AuthenticationError`, `NotFoundError`, `JSONSchemaValidationError`, `PermissionDeniedError` — still get retried 3x by the Node loop before `exec_fallback` produces a friendly message. Pre-existing; flagged in original handoff §3 and review-silent-failures W2. Not a regression.

3. **smart_filter's `except Exception`** at `smart_filter.py:223` silently degrades to unfiltered fields on any error including the new `LLMCallError`. Intentional behavior for smart_filter (filtering is best-effort). Worth noting that with Option F (item 2), more error paths now flow through this silencer. Pre-existing pattern.

4. **Trace JSON `llm_summary.total_cost_usd` silently zeros None** — `total_cost += event["llm_call"].get("cost_usd", 0) or 0` at `workflow_trace.py:405`. Pre-existing. Made more reachable post-A.10 because LiteLLM returns `None` for unknown-pricing models more often than the deleted `MODEL_PRICING` table did. CLI summary handles it correctly via `pricing_available: False`/`partial_cost_usd`; only the trace JSON consumer divergence remains.

5. **Dead `thinking_tokens` aggregation** in `core/metrics.py:110, 156, 188-197, 250-252` — reads from `llm_usage["thinking_tokens"]` and `["thinking_budget"]`, but no production code WRITES those keys. Pre-existing dead code. Worth a separate cleanup task.

### Key file changes by commit

**`96f5f3dd` — fix(llm): correct settings command name + LiteLLM URL**:
- `src/pflow/nodes/llm/llm.py:348` — typo fix; line 326-341 — added LiteLLM provider list URL; line 58 — Interface docstring fix
- `tests/test_nodes/test_llm/test_llm.py:232,253` — test assertion updated

**`ad58d856` — test(llm): 3 missing tests**:
- `tests/test_core/test_llm_reasoning_map.py` — Opus 4.5 effort+max_tokens precedence test
- `tests/test_core/test_llm_client.py` — `TestEnrichLlmUsageWithCost` class (5 tests, all 3 branches of the cost-key contract)
- `tests/test_registry/test_smart_filter.py` — `TestGeminiThinkingHeuristics` class (5 parametrized tests)

**`3aa7ed8f` — docs(llm): purge stale references**:
- `docs/reference/cli/settings.mdx:335` — corrected `pflow settings llm show` example output
- `src/pflow/cli/workflow_output.py:464` + `src/pflow/execution/formatters/success_formatter.py:253` — "model not in pricing table" → "pricing data missing for"
- `src/pflow/core/CLAUDE.md:21` — directory tree (added `llm_client.py`, `llm_reasoning_map.py`; removed `llm_pricing.py`)
- `src/pflow/core/settings.py:67-78` — `LLMSettings` docstring resolution chain
- `src/pflow/runtime/engine/CLAUDE.md:293` — Cross-Module Dependencies updated
- `tests/CLAUDE.md` — autouse fixture + LLM mock sections rewritten
- `tests/test_nodes/test_llm/TESTING.md` — full rewrite (was telling testers to install `llm-anthropic` plugin and `llm keys set`; now covers env vars + `pflow settings set-env`)
- `tests/test_cli/test_direct_execution_helpers.py:195` — small docstring refresh

**`30918fc0` — refactor(llm): adapter contract + reasoning empty-response warning**:
- `src/pflow/core/exceptions.py` — added `LLMCallError(PflowError)`
- `src/pflow/core/llm_client.py` — DELETED `error` and `status` fields from `AdapterResponse`; `BadRequestError` handler now raises `LLMCallError` (after firing trace_hook); added empty-response warning in `_normalize` for reasoning-model trap
- `src/pflow/nodes/llm/llm.py::_call_llm` — wrapped `complete()` call in `try/except LLMCallError`; converted to error dict at the single boundary
- `tests/test_core/test_llm_client.py` — updated 3 error-path tests + added `TestNormalizeEmptyResponseWarning` class (5 tests)

**`96003f3c` — refactor(trace): shared-store seam**: 8 production files (see Deletions section above)

**`8df7ebfa` — test(trace): regression guards**:
- `tests/test_runtime/test_workflow_trace.py` — DELETED `test_enable_llm_interception_attribute` and `test_current_node_is_thread_local` + class
- `tests/test_runtime/test_trace_integration.py` — DELETED 4 setup lines (`enable_llm_interception = False`); ADDED 4 new test classes (`TestLLMTraceHookCapture`, `TestSubWorkflowTraceCollector` with 2 tests, `TestParallelBatchSubWorkflowTrace`)

### Verification chain that proves item 3 worked

1. **Sacred test**: `tests/test_execution/test_plan_drift.py` 32 passed at every step
2. **Full suite**: 5284 passed (5266 baseline + 18 new — see commit deltas)
3. **Lint**: `make check` green (ruff, ruff-format, mypy, deptry)
4. **End-to-end smoke** (real Gemini-3, $0.0002):
   ```
   uv run pflow --no-cache /tmp/smoke-trace-check.pflow.md
   # Inspect trace JSON:
   #   has llm_call:     YES
   #   has llm_prompt:   YES   ← was MISSING before
   #   has llm_response: YES
   #   llm_prompt: 'Reply with exactly OK_TRACE_PROBE.'
   ```

### Branch summary (since `8349df88` baseline — full Phase A + cleanup)

```
8349df88 ready for phase 0 + a    ← baseline (pre-Phase-A)
7babf9e5 A.1: install LiteLLM
0a2eb798 A.2 + A.3: reasoning_map + adapter
a38afa6d A.4 + A.5: mock + LLMNode rewire
40b74f8e A.6 + A.7 + A.8: tracing + discovery + cleanup
5d0e0a9b A.9: drop llm CLI subprocess paths
8247ae2a A.10: delete llm_pricing.py
4becef96 A.11: drop llm/llm-anthropic/llm-gemini deps
6222697f A.12: docs pass
ac257fc6 end-of-task cleanup     ← end of Phase A proper
c1f417c1 docs(task-158): progress log §30 + Phase A review handoff braindump
96f5f3dd fix(llm): correct settings command name and improve unknown-model error tip
ad58d856 test(llm): add Opus 4.5 precedence, cost mirror, smart_filter Gemini coverage
3aa7ed8f docs(llm): purge stale references to llm-library and pricing table
30918fc0 refactor(llm): centralize adapter error contract and warn on empty reasoning output
96003f3c refactor(trace): replace global LLM trace state with shared-store seam
8df7ebfa test(trace): add regression guards for trace_hook + sub-workflow + storage_mode    ← current HEAD
```

### Important contracts that changed in this session

**`AdapterResponse` now has a single mode (success only).** The `error: str | None` and `status: Literal["ok", "error"]` fields are GONE. Any code reading `adapter_response.status` or `adapter_response.error` will fail. Replacement: catch `LLMCallError` from `pflow.core.exceptions`. LLMNode does this; discovery callers let it propagate; smart_filter's `except Exception` catches it.

**`shared["_trace_collector"]` is now actively managed by `engine.run()` save/restore.** It is the seam LLMNode reads to find its trace collector. For sub-workflows: parent's value is preserved across the child run via try/finally; child's collector is installed for the duration of the child's `_run_inner` walk. Save/restore uses unconditional write-back (NOT `.pop()`) — see "Save/restore design" above.

**`WorkflowTraceCollector` no longer has** `_active_collectors`, `_thread_local`, `_llm_lock`, `_llm_interceptor_installed`, `register_for_llm_call`, `unregister_from_llm_call`, `enable_llm_interception`. The remaining public surface: `events`, `llm_prompts`, `record_node_execution`, `get_trace_hook(node_id)`, `save_to_file`, plus the various `_sanitize_*` and aggregation helpers.

**`LLMNode.prep` reads `self.node_id`** (a compiler-set dynamic attribute) and `shared["_trace_collector"]` to resolve `prep_res["_trace_hook"]`. **`LLMNode.exec` captures the hook from prep_res BEFORE submitting `_call_llm` to its inner `ThreadPoolExecutor`.** This is the load-bearing mechanism that survives the worker-thread boundary.

### Loose ends acknowledged (not blockers)

1. **Code review of full implementation deferred** — user said "another agent will handle that." No further commits without explicit permission.
2. **Pre-existing limitations** (carried over from previous handoff + this session's reviewers): parallel batch LLM per-item prompts (last-item-wins), PATTERN EXCEPTION scope (only `BadRequestError` caught), smart_filter silent degradation on errors, trace JSON `total_cost_usd` None coercion, dead `thinking_tokens` aggregation. None are regressions.
3. **Plan file** at `/Users/andfal/.claude/plans/magical-swinging-taco.md` documents the item 3 design + plan-review refinements. Worth referencing if questions arise about the design decisions.

### Files NOT to delete despite being unreferenced (intentional retention)

- `scratchpads/task-158-spike/spike_6_temp_thinking_errors.py` — runnable evidence of the item 9 investigation. ~$0.00 to re-run if Anthropic ever changes the error format. Not committed.
- `scratchpads/task-158-spike/spike_*.py` from §27 — Phase 0 spike scripts. Same rationale: runnable docs of pricing/exception/etc findings.

### What the next agent (code reviewer or PR opener) should know

1. **The branch is ready for review** — 6 follow-up commits + 9 Phase A commits since `8349df88` baseline. All tests green. All lint green. Sacred test green throughout.

2. **Item 3 is the highest-stakes change** — touches engine, runner, workflow_executor, instrumentation, workflow_trace, llm.py + 2 CLAUDE.md. ~110 lines of class-level globals + methods deleted; ~25 lines of straightforward shared-store reads added. The plan + plan-review (3 agents) + design refinement is documented in `/Users/andfal/.claude/plans/magical-swinging-taco.md`.

3. **Two architectural facts the reviewer must understand**:
   - `_trace_collector` is the established shared-store seam — runner installs it, propagation puts parent's into child storage, formatters read it. The new design has `engine.run` save/restore around its graph walk to make `shared["_trace_collector"]` always reflect the currently-executing engine's collector.
   - `node.node_id` is a dynamic attribute set by the compiler at `compilation/compiler.py:299` — LLMNode.prep reads its own `self.node_id`, no engine plumbing needed.

4. **The PATTERN EXCEPTION pattern moved** but didn't go away. Adapter raises `LLMCallError` (typed); LLMNode catches at `_call_llm` boundary and converts to error dict. Net effect identical to the previous return-error-marked-response design, but with a single contract on `AdapterResponse` and zero-touch error handling for discovery callers.

5. **If running a real-API smoke test**: `uv run pflow --no-cache /tmp/smoke-trace-check.pflow.md` — small literal-prompt LLM call against gemini-3-flash-preview, ~$0.0002. The check that matters: trace JSON has `event["llm_prompt"]` populated (was MISSING in real traces pre-fix). Workflow file content:

   ```markdown
   # Trace check

   ## Steps

   ### greet

   Greeting step.

   - type: llm
   - model: gemini/gemini-3-flash-preview
   - prompt: Reply with exactly OK_TRACE_PROBE.
   - max_tokens: 1024
   - reasoning_effort: minimal

   ## Outputs

   ### result

   The greeting.

   - type: string
   - source: ${greet.response}
   ```

6. **What could go wrong during PR review**:
   - Reviewer might not realize `event["llm_prompt"]` was MISSING before this work — the fix is invisible in tests because no test asserted on `llm_prompt`'s presence pre-fix. The smoke test against real API is the proof.
   - Reviewer might question the `_pflow_current_node` mention in the plan but absence in the implementation — the plan-review caught that `self.node_id` already exists, plan was refined accordingly.
   - Reviewer might worry about the `pop` → write-back change — it's documented in the commit message and the impact-completeness review verified all consumers use `.get()`.

### Next step

Code review (deferred to another agent). Then PR. After merge, write `implementation/plan-phase-B-through-G.md` for the actual prompt-caching feature work.

---

## 32. Session 2026-04-25 (cont.) — Phase A code-review item #6 implemented (typed-error translation completed)

### Context

This session implemented the final outstanding architectural item from §31's code review: **#6 — adapter as true seam, with typed exception translation for every deterministic LiteLLM error**. The deferred-findings file at `.taskmaster/tasks/task_158/starting-context/deferred-findings-from-phase-A-review-2026-04-25.md` enumerated this; the plan was approved out-of-band and pasted in at session start.

The session ran in **two passes**:

- **Pass 1** — implement the plan as written (~9 tasks). Result: working but with two real loose ends I didn't see at first.
- **Pass 2** — after the user asked me to be honest about loose ends, I admitted one (LLMNode-level test for `InvalidRequestError`'s third typed-catch branch was missing), added it. Then ran `/code-review staged --agents 3`, which surfaced **two more critical findings I had missed** (discriminator loss across the adapter→LLMNode seam) plus several worth-doing improvements. Implemented all of them. Then caught a *third* loose end myself (the new `error_class` field was dead — added to the internal dict but not surfaced to `shared`).

The two-pass shape is the lesson: even a clean-looking implementation of a clean-looking plan had subtle UX regressions that only became visible under critical review. The plan's principle "adapter raises terse exceptions; LLMNode builds friendly text" is correct, but creates a trap (next subsection).

### The discriminator-loss bug pattern (central insight)

The plan's architecture: `_classify_litellm_error` translates LiteLLM exceptions to typed pflow subclasses with terse messages; LLMNode catches each subclass and builds a rich user-facing message.

**The trap**: when `_classify_litellm_error` carefully encodes a sub-case discriminator into the *message text* (e.g. `"Unknown model: gibberish (no provider prefix)"`) and LLMNode catches `except UnknownModelError:` *without* `as e`, the discriminator gets discarded. Two structurally distinct failures collapse to identical user-facing text, sending agents down the wrong fix path.

Concrete instance caught by `review-agent-ux`:

| LiteLLM exception | Adapter message | LLMNode message (Pass 1) | Problem |
|---|---|---|---|
| `NotFoundError` (model name wrong, prefix valid: `anthropic/claude-foo-99`) | `"Unknown model: anthropic/claude-foo-99"` | `"Unknown model: ... Use a provider prefix like 'anthropic/...' ..."` | Misleading — agent already used a prefix |
| `BadRequestError("LLM Provider NOT provided")` (prefix missing: `gibberish`) | `"Unknown model: gibberish (no provider prefix)"` | `"Unknown model: ... Use a provider prefix like 'anthropic/...' ..."` | Correct, but indistinguishable from above |

Same trap on `MissingApiKeyError` — `AuthenticationError` (set a key) vs `PermissionDeniedError` (request access / change tier) need *different* remediations, but both rendered the same env-var-setup hint.

### The fix: structured discriminator at the API boundary, not substring-matching across it

Two ways to preserve the discriminator:
1. Catch `as e`, substring-match `"(no provider prefix)"` in `str(e)` to branch — fragile, couples LLMNode to the adapter's message format
2. Add a structured attribute (`reason: str`) on `UnknownModelError`, set it once at the LiteLLM boundary, branch on it in LLMNode — clean

Picked option 2. Pattern that emerged:

> **Substring detection happens *once*, at the LiteLLM boundary, inside `_classify_litellm_error`.** Past that boundary, consumers branch on structured exception attributes — never on message text. Crossing the seam loses any signal that isn't part of the typed contract.

`UnknownModelError(message, *, reason: str = "unknown_name")` was added (`core/exceptions.py:166-181`). `reason ∈ {"unknown_name", "missing_prefix"}`. The adapter sets it; LLMNode branches on `e.reason`. The two messages now lead with their respective precise diagnoses ("Model 'X' is missing a provider prefix" vs "Unknown model: X. The provider didn't recognize this model name.").

For `MissingApiKeyError`, the chosen approach was lighter: catch `as e`, append `f"Detail: {e}"` to the friendly message. Reason: the friendly remediation hint stays useful for the common case (set an env var); the appended Detail line surfaces the discriminator wording the adapter encoded ("lacks permission" vs "API key required") for the agent. No structured attribute needed because the message divergence is shallow.

**Future agents extending the typed exception system MUST follow this pattern.** If you add a new sub-case to a typed exception, don't encode it in the message text — add a structured attribute. If you catch a typed exception in LLMNode (or any other consumer), ALWAYS catch `as e` so future discriminators don't get silently discarded.

### Pass 1: implementing the plan as written

Plan was a clean spec: 6 steps + tests. Executed in order:

1. Add 3 `LLMCallError` subclasses (`UnknownModelError`, `MissingApiKeyError`, `InvalidRequestError`) — `core/exceptions.py`.
2. Expand the adapter's catch tuple from `BadRequestError` only to `(BadRequestError, AuthenticationError, NotFoundError, PermissionDeniedError)`. Add `_classify_litellm_error(exc, *, model)` helper.
3. Rewrite `LLMNode._call_llm` exception handling: typed catches for `UnknownModelError` / `MissingApiKeyError`; generic `except LLMCallError` for the catch-all (handles `InvalidRequestError` and any future subclass).
4. Shrink `exec_fallback` from 4 isinstance branches (~50 lines) to a single generic message (~10 lines) — deterministic errors are now caught at `_call_llm`.
5. Drop `import litellm.exceptions` from `nodes/llm/llm.py`. Architectural seal.
6. Update tests: rewrite the auth test to assert `MissingApiKeyError`; add tests for NotFound, no-provider-prefix, PermissionDenied; rewrite the two LLMNode error tests to raise typed pflow exceptions.

`make test` 5297 green, `make check` clean. Pass 1 done.

### What I missed (caught by my own honesty pass)

User asked "FULLY happy?" and I caught one gap: `InvalidRequestError` (the third typed-catch branch in `_call_llm`) had no LLMNode-level test — the adapter test verified the typed exception is raised, but nothing asserted that LLMNode preserves `str(e)` in `shared["error"]`. Added `test_invalid_request_error_preserves_provider_message`.

That's when 158 tests went green and I claimed "fully happy" — prematurely.

### Pass 2: code-review-driven UX fixes

Ran `/code-review staged --agents 3` with deliberately scoped subagents:

- **`review-impact-completeness`** — `LLMCallError` is the modified shared pattern; verify all `except LLMCallError` consumers handle subclasses correctly via IS-A subsumption.
- **`review-test-fidelity`** — tests were rewired to raise typed pflow exceptions instead of LiteLLM's; verify they still test production-faithful behavior.
- **`review-agent-ux`** — friendly error messages are user-facing; verify they're agent-actionable.

`review-impact-completeness` returned clean — all consumers (`parse_structured_response`, `smart_filter`'s narrowed catch, both discovery callers, LLMNode itself) handle the subclasses correctly via IS-A. Zero ad-hoc reimplementations of the LiteLLM exception ladder outside the adapter.

`review-test-fidelity` flagged the dual-coverage redundancy: my new `test_no_provider_prefix_shows_friendly_message` mocked `UnknownModelError` directly — same contract as the existing `test_unknown_model_error_handling`. The substring-detector regression itself was tested in `test_llm_client.py`. Recommended either rewriting the LLMNode test to raise the real `litellm.exceptions.BadRequestError` (closing both the redundancy and the integrated-path coverage gap) OR deleting the redundant test.

`review-agent-ux` surfaced **two critical findings** I had missed:
1. `UnknownModelError` discriminator (`(no provider prefix)`) silently discarded by LLMNode — **discriminator-loss bug pattern above**.
2. `MissingApiKeyError` collapses auth-vs-permission — same pattern.

Plus six more findings, of which I implemented:
- Restore Timeout-specific message in `exec_fallback` (was a regression — generic message after retry exhaustion was strictly less actionable than the in-thread timeout's specific hint).
- Improve no-keys tip text — was empty string, now suggests setting up a key (the empty tip silently buried the root cause when `get_default_llm_model()` returns None).
- Add `error_class` field to error dict for machine-parseable cause.
- Add docs URL to `MissingApiKeyError` branch.

Deferred (with reasons):
- `category` enum for `InvalidRequestError` sub-cases (content-policy, schema, context-window) — plan explicitly scoped out: "add finer types only when a consumer needs to discriminate them."
- Mock fidelity for `thinking_budget` — no test relies on it, would be premature.
- Defensive `try/except` around the lazy `get_default_llm_model` import — pre-existing risk, defensive coding violates "trust internal code" principle.

### The dead-field bug pattern (third loose end I caught)

Then user asked again "any loose ends?" and I caught a third:

I had added `error_class` to the internal `_error_dict` shape — but `LLMNode.post()` doesn't surface it to `shared`. The whole point of the field (per agent-ux finding #8) was so agents reading the shared store as JSON output can branch on cause without parsing prose. As shipped, the field was buried in the internal `exec_res` dict that no consumer outside the node lifecycle ever sees. Dead code.

Bug pattern worth remembering:

> **When extending an internal contract (a dict, a return shape) with a new field, trace where it gets consumed. If consumers see only a subset of the dict's keys, the new field is dead unless explicitly forwarded across the boundary.** A test that calls the internal function directly will pass; the user-facing test fails because the field isn't there.

Fix: surface `shared["error_class"] = exec_res["error_class"]` in `post()`. The test was simplified from `node.run(shared); prep_res = node.prep({}); _call_llm(prep_res)` (awkward double-call) to a clean `node.run(shared); assert shared["error_class"] == "..."`. Then `error_class` assertions were added to **all 5 error-path tests** so the contract is pinned end-to-end:

| Path | error_class | Test |
|---|---|---|
| `_call_llm` UnknownModelError catch | `"UnknownModelError"` | `test_unknown_model_surfaces_error_class` |
| `_call_llm` MissingApiKeyError catch | `"MissingApiKeyError"` | `test_needs_key_exception_handling`, `test_permission_denied_preserves_lacks_permission_detail` |
| `_call_llm` generic `LLMCallError as e` catch | `type(e).__name__` (today: `"InvalidRequestError"`) | `test_invalid_request_error_preserves_provider_message` |
| `exec()` `FuturesTimeoutError` catch | `"TimeoutError"` | `test_timeout_raises_timeout_error` |
| `exec_fallback` substring match on `"timed out"` | `"TimeoutError"` | (covered transitively by retry-exhaustion paths in suite) |
| `exec_fallback` generic | `type(exc).__name__` | `test_generic_exception_handling` |

### Testing trap: the autouse mock skip pattern is path-substring-based

I tried to write an integrated test (`test_no_provider_prefix_integrated_path`) that would raise a real `litellm.exceptions.BadRequestError`, flow through the real `_classify_litellm_error`, and verify LLMNode's catch handles it. The test failed: `action == "default"` instead of `"error"` — `complete()` returned a mock response.

Root cause: `tests/conftest.py:23-26` skips the autouse `mock_llm_client` fixture for tests under paths containing the substring `/llm/`. My test's path is `tests/test_nodes/test_llm/test_llm.py` — substring `/llm/` does *not* appear (the path has `_llm/`, not `/llm/`). So the autouse mock applied, replacing `pflow.core.llm_client.complete` with the mock, and `from pflow.core.llm_client import complete as real_complete` inside the test got the mocked function (the import happened *after* the autouse setattr).

The skip pattern was meant for tests under `tests/test_nodes/test_llm/llm/` (a hypothetical sub-dir for real-API tests) or `test_llm_integration.py` paths that DO contain `/llm/` as a substring. Files at `tests/test_nodes/test_llm/test_llm.py` are unit tests by design.

I deleted the integrated test. The coverage it would have provided is already there:
- Adapter side (`test_llm_client.py`): real LiteLLM exception → typed pflow exception with correct `reason` attribute ✓
- LLMNode side (this file): typed pflow exception → friendly message construction ✓
- Class identity across the seam: guaranteed by Python imports + mypy

A future agent wanting a true integrated test needs to either move the test to a path matching `/llm/`, add a marker + per-test opt-out in conftest, or use `importlib.reload(pflow.core.llm_client)` before the autouse mock applies (heavyweight).

### Architectural seal verification

After this work, the only `litellm.exceptions` references in `src/pflow/` are:

```
src/pflow/core/llm_client.py:35:import litellm.exceptions      ← the seam (expected)
src/pflow/nodes/llm/llm.py:449:        ... ``litellm.exceptions.Timeout`` ...   ← informational docstring (not a code dep)
```

Verification grep:

```bash
grep -rn 'import litellm\.exceptions\|from litellm\.exceptions' src/pflow/
# Expected: only `src/pflow/core/llm_client.py:35`
```

The catch tuple in `_classify_litellm_error` covers 4 LiteLLM exception classes:
- `BadRequestError` (and its subclasses: `UnsupportedParamsError`, `ContentPolicyViolationError`, `ContextWindowExceededError`, `RejectedRequestError` — verified via `issubclass()` to all flow through to `InvalidRequestError`)
- `AuthenticationError` → `MissingApiKeyError`
- `NotFoundError` → `UnknownModelError(reason="unknown_name")`
- `PermissionDeniedError` → `MissingApiKeyError`

NOT in the tuple (propagate raw to the Node retry loop):
- `Timeout` — retriable
- `RateLimitError` — retriable
- `InternalServerError` — retriable
- `JSONSchemaValidationError` (NOT a `BadRequestError` subclass — verified) — propagates to `exec_fallback` after retries
- `APIResponseValidationError` (also not a `BadRequestError` subclass) — same

The "LLM Provider NOT provided" substring fires inside the `BadRequestError` branch and produces `UnknownModelError(reason="missing_prefix")`. This substring detection is the **only** place in the seal where the message text is parsed — past `_classify_litellm_error`, consumers use structured attributes.

### What's deliberately NOT in this implementation

1. **`category` enum on `InvalidRequestError`** for content-policy / schema / context-window discrimination. Plan explicitly scoped out: "add finer types only when a consumer needs to discriminate them."
2. **`JSONSchemaValidationError` / `APIResponseValidationError` translation.** Not `BadRequestError` subclasses; rare in practice (`parse_structured_response` already handles malformed JSON). Add when a real failure surfaces.
3. **Mock fidelity for `thinking_budget`** — the `MockLLMClient` returns `thinking_budget=0` regardless of `reasoning_kwargs`. No test relies on this; would be designing for hypothetical future.
4. **Defensive `try/except` around the lazy `get_default_llm_model` import in `_call_llm`'s UnknownModelError branch.** The lazy import was already in `exec_fallback` before this work — pre-existing risk, defensive coding around it would violate "trust internal code; don't add error handling for scenarios that can't happen."
5. **Pre-validation of Anthropic temperature+thinking constraint.** Already covered in §31 item 9 — Anthropic's `BadRequestError` is exemplary; pre-validation would duplicate a server-side rule.
6. **Restoring `import litellm.exceptions` for `exec_fallback`'s timeout isinstance check.** Considered re-importing for the cleanest type check, but substring detection on `"timed out" in str(exc).lower()` preserves the architectural seal AND keeps the actionable message. Substring is fragile but doesn't introduce coupling. Trade accepted.

### Verification (after pass 2 + dead-field fix)

```bash
uv run pytest tests/test_execution/test_plan_drift.py -q              # 32 passed (sacred)
uv run pytest tests/test_core/test_llm_client.py tests/test_nodes/test_llm/ -q   # 162 passed
make test                                                              # 5301 passed
make check                                                             # ruff + ruff-format + mypy + deptry all green
grep -rn 'litellm\.exceptions' src/pflow/nodes/                       # 1 docstring mention only
```

### Production code changes summary

- **`src/pflow/core/exceptions.py`** — added `UnknownModelError` (with structured `reason` attribute), `MissingApiKeyError`, `InvalidRequestError` as subclasses of `LLMCallError`. Updated `LLMCallError` docstring.
- **`src/pflow/core/llm_client.py`** — expanded catch tuple in `complete()` from `BadRequestError` only to all 4 deterministic LiteLLM exception classes. Added `_classify_litellm_error(exc, *, model) -> LLMCallError` helper. Updated module + `complete()` docstrings.
- **`src/pflow/nodes/llm/llm.py`** — dropped `import litellm.exceptions`. Added module-level `_error_dict(model, error_class, message)` helper (deduplicates 5 inline error-dict constructions) and `_api_key_tip(detected_model)` helper. Rewrote `_call_llm` exception handling with 3 typed-catch branches (UnknownModel, MissingApiKey, generic LLMCallError); each branch builds a precise message via the helpers. Shrunk `exec_fallback` from ~50 lines to ~10 (substring-based timeout detection preserves the actionable hint). Updated `post()` to surface `shared["error_class"]`.
- **`src/pflow/core/CLAUDE.md`** — added the 3 new subclasses to the exception hierarchy diagram + a row in the "When to use which exception" table.

### Test changes summary

- **`tests/test_core/test_llm_client.py`** — flipped `test_authentication_error_propagates` → `test_authentication_error_raises_missing_api_key_error`; added 4 new translation tests (`test_not_found_raises_unknown_model_error`, `test_no_provider_prefix_raises_unknown_model_error` with `reason="missing_prefix"` assertion, `test_permission_denied_raises_missing_api_key_error` requires real `httpx.Response` for the constructor); renamed `test_bad_request_raises_llm_call_error` → `test_bad_request_raises_invalid_request_error` (asserts `IS-A LLMCallError` + `__cause__`).
- **`tests/test_nodes/test_llm/test_llm.py`** — rewrote `test_unknown_model_error_handling` to test the unknown-name branch with assertion on no-keys-detected tip variant; added `test_unknown_model_with_detected_key_shows_supports_tip` (mocks `get_default_llm_model` to verify the detected-key branch — otherwise unreachable in tests because PYTEST_CURRENT_TEST disables key detection); added `test_missing_prefix_branch_message` (no-prefix branch with assertions distinguishing it from unknown-name); rewrote `test_needs_key_exception_handling` to verify `Detail:` line + docs URL; added `test_permission_denied_preserves_lacks_permission_detail` (the discriminator that survives via the `Detail:` line); added `test_invalid_request_error_preserves_provider_message` (third typed-catch branch); added `test_unknown_model_surfaces_error_class` (the surfaced `error_class` field). Strengthened `error_class` assertions across `test_needs_key_exception_handling`, `test_permission_denied_preserves_lacks_permission_detail`, `test_invalid_request_error_preserves_provider_message`, `test_timeout_raises_timeout_error`, `test_generic_exception_handling`.

### Key files / line numbers (as of HEAD before commit)

- Adapter seam: `src/pflow/core/llm_client.py:225-251` (the 4-class catch + classify call) and `:261-282` (`_classify_litellm_error`)
- Typed exception hierarchy: `src/pflow/core/exceptions.py:148-200` (`LLMCallError` + 3 subclasses)
- LLMNode error handling: `src/pflow/nodes/llm/llm.py:33-66` (helpers), `:243-300` (typed-catch chain in `_call_llm`), `:387-419` (`exec_fallback` with substring timeout detection)
- error_class surfacing: `src/pflow/nodes/llm/llm.py:359-368` (in `post()`)

### What the next agent should know

1. **The architectural seal is complete and verifiable.** The grep `grep -rn 'import litellm\.exceptions\|from litellm\.exceptions' src/pflow/` should return exactly one line (`core/llm_client.py:35`). If a future change adds a second match in `src/pflow/nodes/`, the seal has been broken.

2. **The `reason` attribute pattern on `UnknownModelError` is the template for any future typed exception that needs sub-case discrimination.** Don't encode discriminators in message text; structured attributes survive across the seam, message text doesn't (because LLMNode catches without `as e` for terseness).

3. **`error_class` is a public field of the LLM node's error contract.** It's documented in `_error_dict`'s docstring. Any new error path in `LLMNode` MUST populate it. Today's classification for unmapped exceptions uses `type(exc).__name__` — this is the established convention.

4. **`exec_fallback` uses substring detection on `"timed out"`** to keep the timeout-specific message actionable after retry exhaustion, without re-importing `litellm.exceptions`. If a future LiteLLM Timeout subclass changes its `str()` representation, this substring breaks silently. Mitigation: the test suite has explicit assertions on the timeout message in `test_timeout_raises_timeout_error` (in-thread path); a regression in retry-exhaustion timeout messages would require manual verification of the substring contract.

5. **The autouse `mock_llm_client` fixture skip pattern is path-substring-based** (`/llm/`). Files at `tests/test_nodes/test_llm/test_llm.py` and `test_llm_images.py` get the mock because their paths don't contain `/llm/` as a substring. This is by design — those are unit tests. Tests under `tests/test_nodes/test_llm/test_llm_integration.py` ALSO get the mock applied; the file gates real LLM calls via `RUN_LLM_TESTS=1` + `pytest.mark.skipif`. If you write a test that needs the real adapter, mocking it out at the test level (as `monkeypatch.setattr("pflow.core.llm_client.litellm.completion", ...)`) doesn't work because the autouse already replaced `complete` itself. Solutions: move test path to match `/llm/`, or use `importlib.reload` (heavyweight).

6. **Five error_class paths are pinned by tests** — the table above. New error paths in LLMNode must extend the table.

After this commit lands, Phase A is fully complete (all 12 review items resolved). Next step is the actual prompt-caching feature work (Phase B–G).

---

## 33. Session 2026-04-25 (cont.) — Broader deferred-findings closeout (what §32 didn't capture)

### Context

§32 documents the implementation of #6 in detail, but the commit it describes (`5a070312`) actually bundled **eight other deferred-findings items** that were implemented earlier in the same session, before the #6 plan was written. The commit message names #8, #9, and the trace-cost propagation work (B7) but doesn't enumerate the rest. This section closes the gap so future agents can see the full closure state of `.taskmaster/tasks/task_158/starting-context/deferred-findings-from-phase-A-review-2026-04-25.md` from one read.

The session order was: read the deferred-findings doc → launch 6 parallel `pflow-codebase-searcher` agents to verify each finding's claims against current code → implement Group A + B + selected Group C items → write the #6 plan in plan mode → another agent (or a continuation) implemented #6 and bundled everything into one commit.

### Verification methodology — 6 parallel agents before any code change

Before touching anything, the 18 deferred findings were re-verified via 6 `pflow-codebase-searcher` agents in parallel (1 message, 6 tool calls). Each agent owned a slice of findings, was asked to quote current code at the cited line numbers, confirm/refute each claim, and flag related issues the original review may have missed.

**This surfaced four issues the original deferred-findings doc had missed:**

1. **`test_missing_api_key_error` was silently broken.** The test used `pytest.raises(ValueError)` but post-Phase-A `node.run()` returns the `"error"` action and stores the message in `shared["error"]` rather than raising. The test could never pass when run, but `RUN_LLM_TESTS=1` gating hid it. **Class of bug worth noting**: gated tests rot silently in proportion to the gate's restrictiveness. The fix in A2 made the test actually exercisable.

2. **The dead BadRequestError "LLM Provider NOT provided" branch in `exec_fallback`** (already removed in the earlier A16 cleanup) had a downstream consequence the review missed: a user typing a bare model name with no provider prefix saw the raw LiteLLM JSON envelope instead of the friendly "use a provider prefix" hint. This drove the design choice in #6's `_classify_litellm_error` to detect `"LLM Provider NOT provided"` at the LiteLLM boundary and raise `UnknownModelError(reason="missing_prefix")`.

3. **C4 (image-path docstring) had a deeper inconsistency than the original doc surfaced.** The test docstring claimed "Relative paths resolve against the current working directory" but production at `nodes/llm/llm.py:160-167` stored the input string verbatim — Python's `open()` later does cwd-relative resolution, but pflow itself doesn't `.resolve()`. The contract was real (cwd-relative), the documented mechanism (pflow resolution) was fictitious.

4. **B11 (parallel batch LLM per-item prompts)** was rated "L (4-6 hours)" in the deferred doc but the agent investigation found that `batch_executor._capture_item_trace` already had the mapping `("prompt", "llm_prompt")` expecting `node_output["prompt"]` to exist. The design originally assumed the prompt would be there; the implementation just never wrote it. Option A (`LLMNode.post()` writes `shared["prompt"]`) is ~3 lines + a regression test. **Estimate revised down significantly once the existing fallback contract was inspected.**

### Operational principles surfaced this session

These shaped the design decisions and are worth keeping for the next round:

1. **"Simplicity of the FINAL code, not how easy it is to get there."** The user's framing eliminated several "minimum diff" / "leave it as-is" defenses for individual items. It's the lens that drove #6 to full Option 3 (true seal) rather than a halfway expansion of the existing PATTERN EXCEPTION pattern, and that turned C8 from "narrow with a fallback comment" into "be explicit about every failure mode you handle and let everything else propagate."

2. **"What would the top 10% of codebases similar to this one implement?"** is the operational question that selects between equivalent-by-LOC alternatives. For #6 it picked the structured-attribute discriminator over message-text parsing; for C8 it picked an explicit exception tuple over a broad catch with comment; for C10 it picked surfacing real data via the adapter over deleting the dead aggregation.

3. **Mirror existing patterns when extending a data contract.** B7's trace JSON tri-state (`total_cost_usd: None` + `partial_cost_usd` + `unavailable_models` + `pricing_available: False`) deliberately copies the exact shape of `MetricsCollector.calculate_costs` rather than inventing a new one. Two consumers reading "is pricing available?" should see identical-shaped answers regardless of which path produced them.

4. **The adapter is the single source of truth for derived data.** C10's thinking-budget extraction lives in the adapter (`_extract_thinking_budget(kwargs)` reads from translated request kwargs), not in LLMNode mirroring request-side state into responses. Same principle as cost (LiteLLM populates) and reasoning_tokens (LiteLLM standardizes via `usage.completion_tokens_details.reasoning_tokens`). Consumers of `AdapterResponse.usage` get a complete picture from one read.

5. **Lint complexity limits sometimes drive useful refactors.** B7's `_collect_llm_summary` rewrite triggered ruff C901 ("too complex"); the fix extracted a `_LLMSummaryAccumulator` dataclass at module level. The accumulator is cleaner than inline nested helpers — explicit fields, two methods (`add_leaf`, `merge_sub`), one `as_dict` builder. The lint constraint surfaced an abstraction that the inline code was hiding.

### Group A — 5 doc/test cleanup items (bundled into commit `5a070312`)

| # | Site | Change |
|---|---|---|
| A1 | `tests/test_core/test_llm_config_provider_detection.py:1-7` | Module docstring updated from "env vars, settings, and llm CLI in order" to "env vars and settings (in that order)" — A.9 removed the llm-CLI tier; only the docstring lagged. |
| A2 | `tests/test_nodes/test_llm/test_llm_integration.py:27, 199-200, 210` | Skip-reason text + comment + dead `or "llm models"` OR-branch all updated to post-Phase-A reality. **Plus**: `test_missing_api_key_error` rewritten end-to-end (was using `pytest.raises(ValueError)` which never fires — see methodology surprise #1). Renamed to `test_unknown_model_produces_helpful_error` and rewritten to assert `action == "error"` + `shared["error"]` substring. |
| A3 + B9 | `src/pflow/core/llm_utils.py` | Bundled: deleted dead `callable(response.text)` branch (`AdapterResponse.text` is always a `str` attribute now); rewrote stale "the LLM library normalizes responses to have a text() method" docstring/comments; converted all 5 `ValueError` raise sites to `LLMCallError`. Discovery callers and smart_filter (post-C8) catch the typed exception cleanly. |
| A16 | `src/pflow/nodes/llm/llm.py::exec_fallback` | Consolidated NotFoundError two sub-branches; deleted the unreachable BadRequestError "LLM Provider NOT provided" branch (later superseded by #6's `_classify_litellm_error` which surfaces the same UX at the right layer). |

### Group B — 3 real bugs (B7, B11 bundled into commit `5a070312`)

**B7 — Trace JSON cost None-handling** (`runtime/workflow_trace.py`, `core/trace_report.py`):

`_collect_llm_summary` and `_compute_event_cost` previously coerced `cost_usd: None` to `0.0` via `cost or 0`, silently dropping the unpriced contribution. Trace JSON consumers (third-party tooling, future analyze-cache feature) saw `total_cost_usd: 0.0` instead of `None` with no flag for "we don't have pricing for some calls."

Fix mirrors `MetricsCollector.calculate_costs` exactly: when any leaf has `cost_usd: None`, summary returns `total_cost_usd: None`, `partial_cost_usd: <priced subset>`, `unavailable_models: [...]`, `pricing_available: False`. Same shape across three sites = consumers don't have to special-case.

`_compute_event_cost` got a parallel treatment — returns `None` (rendered as `—` by `_format_cost`) when any leaf in the subtree is unpriced, instead of a misleading partial sum.

The ruff-driven extraction (`_LLMSummaryAccumulator` dataclass + `_accumulate_call_cost` / `_accumulate_child_cost` helpers in trace_report) is the principle-5 lesson above.

**B11 — Per-item batch LLM prompt capture** (`nodes/llm/llm.py::post()`):

`WorkflowTraceCollector.llm_prompts[node_id]` is keyed by node_id alone, so parallel batch workers (which share the batch wrapper's id via deepcopy) all overwrite the same slot — last-item-wins, often missing entirely. **The fix is one line in `LLMNode.post()`**: `shared["prompt"] = prep_res["prompt"]`. Via NamespacedSharedStore this routes to `parent_shared[node_id]["prompt"]`, which `_capture_item_trace`'s existing fallback (`for src_key, dst_key in [("response", "llm_response"), ("prompt", "llm_prompt")]`) was already designed to read.

The mapping in `_capture_item_trace` had been there since the original batch implementation — it expected `node_output["prompt"]`; nothing wrote it. Adding the single write closes a documented gap that affected 4+ shipped example workflows (`release-announcements`, `generate-changelog-simple`, `vision-scraper`, `batch-file-ref`). One regression test (`TestParallelBatchOfLLMs::test_each_batch_item_llm_captures_own_rendered_prompt`) pins per-item visibility going forward.

### Group C — 3 design-decision items (C4, C8, C10 bundled into `5a070312`; C6 = §32)

**C4 — Image-path cwd-relative contract**:

Decision (user-driven): images are workflow inputs, not workflow assets. Inputs are cwd-relative; assets (code-block file refs like `code: @./helper.py`) are workflow-relative. Different layers, different conventions. Fix: production stores the input string verbatim (`Attachment(value=str(Path(img)))`); Python's `open()` resolves at file-read time. Test asserts `attachments[0].value == "relative.jpg"` (verbatim); docstring explicitly contrasts the two conventions for future maintainers.

**C8 — smart_filter narrow `except`**:

Replaced `except Exception` with `except (LLMCallError, ConnectionError, TimeoutError, OSError)`. Programming errors (`AttributeError`, `TypeError`, `KeyError`) propagate so refactor-introduced bugs surface as test failures rather than silent UX degradation. **Two existing tests had to be migrated** because they encoded the broad-catch behavior using `RuntimeError` and bare `ValueError` — fixtures that didn't reflect what the real adapter would raise post-#9. Updated to raise typed `LLMCallError` (matching the real contract). Added `test_programming_error_propagates` (regression guard) and `test_warning_logged_on_graceful_fallback` (caplog test pinning the warning emission contract).

**C10 — Thinking tokens via adapter (Option B per user direction)**:

User picked Option B (surface real data) over Option A (delete the dead `metrics.py` aggregation that was reading keys nobody wrote). Implementation:

- `_normalize` reads `usage.completion_tokens_details.reasoning_tokens` — LiteLLM's standardized field for reasoning-token counts across all providers (Anthropic extended thinking, OpenAI o1/o3, Gemini 2.5/3).
- New helper `_extract_thinking_budget(kwargs)` mirrors the request-side budget from the translated kwargs — handles both Anthropic's nested `thinking={"budget_tokens": N}` shape and Gemini's top-level `thinking_budget=N`. OpenAI's `reasoning_effort` and Gemini-3's `thinking_level` are categorical (no token budget) → returns 0 so utilization metrics simply omit the section.
- `AdapterResponse.usage` gains `thinking_tokens` and `thinking_budget` keys (stable shape).
- LLMNode passes through to `shared["llm_usage"]`.
- `MockLLMClient` default mirrors the new shape.

The previously-dead `metrics.py` aggregation (which the verification round confirmed had zero production writers) is now live. The fabricated `test_metrics_thinking_cache.py` tests now validate aggregation logic against shapes that real production data flows through.

4 new adapter tests pin the contract: zero-when-no-reasoning, extraction from `completion_tokens_details`, Anthropic budget mirroring, Gemini budget mirroring.

### Closure state of `deferred-findings-from-phase-A-review-2026-04-25.md`

| Status | Items | Notes |
|---|---|---|
| **Closed (12)** | #1, #2, #3, #4, #5, #6, #7, #8, #9, #10, #11, #16 | All bundled into commit `5a070312`. |
| **Verified-and-deferred (4)** | #12 (AdapterResponse `finish_reason`/`reasoning_content`), #13 (`_normalize` IndexError guard), #14 (`model_options` overrides reasoning_kwargs silently — documented), #15 (`LLMCallError` JSON envelope wrapping — minor UX polish) | Each deliberately scoped out as "no current consumer needs it" or "defensive code where the trade isn't worth it." Documented in §32 / this section. |
| **User decision (1)** | #18 (Gemini PR #15226 fix verification on 1.82.6 — release-date-inferred, never spike-verified) | Surface for PR prep. |

### Testing-trap addendum to §32

§32 mentions the `/llm/` autouse-mock skip pattern in the context of `test_llm_integration.py`. The broader observation worth stating: **the skip pattern is path-substring based, so it does NOT skip files at `tests/test_nodes/test_llm/test_*.py`** (the substring there is `_llm/`, not `/llm/`). Every unit test under `tests/test_nodes/test_llm/` gets the autouse `mock_llm_client` fixture applied, including `test_llm_integration.py` itself — that file gates real LLM calls via `RUN_LLM_TESTS=1` + `pytest.mark.skipif`, NOT via the conftest skip pattern.

This means: any test that wants to verify the real adapter's behavior (not the mock's) will hit the autouse-mock trap because the mock has already replaced `pflow.core.llm_client.complete` before the test's `monkeypatch.setattr` runs. Workarounds documented in §32 (move test path, `importlib.reload`, etc.) are correct. **The simpler fix** for future tests that need real-adapter behavior: monkeypatch one layer down at `pflow.core.llm_client.litellm.completion` — that's the actual LiteLLM call site, which the autouse mock doesn't touch (because it replaces the `complete` function entirely, bypassing whatever `litellm.completion` is). This was found while writing #6's adapter-translation tests in `tests/test_core/test_llm_client.py` — they all `@patch("pflow.core.llm_client.litellm.completion")` and work cleanly.

### Final state at end of §33 work

- `make test`: 5301 passed, 0 failed (pre-#6: 5293; #6 adds 8 net tests — 3 from C10 thinking-token surfacing, 2 from C8 propagation/caplog, 2 from B7 cost None-handling, 1 from B11 batch-LLM trace, plus #6's own additions documented in §32).
- Sacred `tests/test_execution/test_plan_drift.py`: 32/32 throughout every step (verified after each finding implementation, after each lint fix, after the #6 work, after the bundle commit).
- `make check`: ruff + ruff-format + mypy + deptry green.
- `grep -rn 'import litellm\.exceptions\|from litellm\.exceptions' src/pflow/`: returns exactly one match (`core/llm_client.py:35`).

### What the next agent should know about Phase A→B-G handoff

1. **Phase A is structurally and architecturally complete.** All 12 review items closed, all 18 deferred findings either closed or deliberately scoped out with documented reasoning. The branch is ready for a PR review pass.

2. **The deferred-findings doc is now mostly historical** — it described work to do; that work is done. The remaining "verified-and-deferred" items (#12-#15) are explicitly low-value or future-feature-driven; they don't block Phase B-G.

3. **One open user-decision item before merge:** the Gemini PR #15226 fix re-verification on 1.82.6 (#18, ~$0.001 spike if the user wants the audit-trail conversion).

4. **Phase B-G plan can now be written informed by concrete LiteLLM behavior.** The Phase 0 spike (§27) confirmed cache_control mechanics; Phase A confirmed the adapter shape, the typed exception hierarchy, the trace seam, and the pricing flow. Open questions for Phase B-G planning that Phase A didn't answer: how `## Cache` block parsing slots into the markdown parser (parser is line-by-line state machine, NOT a markdown library), how cache rendering interacts with `prep_res["prompt"]` (the rendered prompt today is a flat string by the time `_call_llm` sees it — cache rendering would split it into content blocks at the adapter layer), and the validation-time data-flow rules for `prompt_cache:` order checking.

5. **Two architectural patterns to keep using when extending the LLM seam**:
   - **Structured discriminators on typed exceptions, not message-text parsing across the seam.** §32's discriminator-loss insight generalizes — any new sub-case on a typed exception should be a structured attribute, never encoded in the message text.
   - **Adapter as the single source of truth for derived data.** Cost, reasoning tokens, thinking budget, future cache metadata — all extracted/mirrored at `_normalize` so consumers of `AdapterResponse.usage` get a complete picture from one read. Don't make LLMNode mirror request-side state into response-side outputs.

---

## 34. Session 2026-04-25 (cont.) — Phase A code review #2 + completion plan + 10-step typed-exception architecture

### Context

After §33 closed the deferred-findings doc, the user asked for another `/code-review` to validate the full implementation state. Four agents in parallel: `review-concurrency-safety`, `review-impact-completeness`, `review-silent-failures`, `review-agent-ux`. The chosen four targeted the highest-stakes blindspots for Phase A's specific shape: shared-pattern replacement, threading-model rewrite, null-handling shifts, rewritten error pipeline.

The four agents combined surfaced **3 critical findings + 7 high-value findings + 6 polish items**. The pattern across critical and high findings: §32 had fixed the discriminator-loss / dead-field bug at the adapter→LLMNode seam. The new findings showed **the same pattern recurring at the LLMNode→executor→JSON-output seam** (`error_class` set in shared but never reaching JSON output) and the duplication that pattern creates (rich error remediation only in `LLMNode._call_llm`, missing from every other adapter caller).

### Critical findings

1. **`error_class` is dead at the user-facing JSON boundary.** §32 fixed the field at the LLMNode boundary; agents reading JSON via `pflow --output-format json` never saw it because `executor_service._enrich_error_from_node_output` had branches for HTTP/MCP/shell/template but no LLM branch. NamespacedSharedStore's namespacing routed `shared["error_class"]` into `shared[node_id]["error_class"]`, archived to `__failures__[id]["data"]`, then ignored by `_enrich`. The dead-field pattern §32 caught — recurring one layer up.

2. **`smart_filter` narrow-except misses every LiteLLM transient exception.** Verified at runtime: `litellm.exceptions.Timeout` doesn't inherit from builtin `TimeoutError` — its MRO is `Timeout → APITimeoutError → APIConnectionError → APIError → OpenAIError → Exception`. Same for `RateLimitError` and `InternalServerError`. The catch tuple `(LLMCallError, ConnectionError, TimeoutError, OSError)` was sized to a builtin-exception ladder it can't reach. Network timeouts during smart filtering crash the discovery caller instead of degrading.

3. **`LLMNode.post()` JSON-parse error path skips `error_class`.** §32's table of 6 paths missed this 7th. Schema-mode `json.JSONDecodeError` set `shared["error"]` but never `shared["error_class"]`.

### Plan structure

Wrote `.taskmaster/tasks/task_158/implementation/phase-A-completion-plan.md` (~700 lines) framing the work as **completing the typed-exception architecture** rather than band-aiding each callsite. The architectural thesis: the exception is the source of truth — `LLMCallError.to_diagnostics()` overrides per subclass produce rich Diagnostics with structured context + remediation suggestions. Consumers branch on structured attributes, never on message text. End-state: ~80 lines of duplication (LLMNode's `_error_dict`/`_api_key_tip` helpers + the typed-catch chain) deleted, replaced with ~60 lines of `to_diagnostics()` overrides every consumer benefits from.

**3 plan-review agents in parallel** (`review-plan`, `review-impact-completeness`, `review-validation-consistency`) caught 6 critical gaps + 7 high-value gaps in the plan v1.0 before any code was written. Most important catches:
- The `_FAILURE_CATEGORY_MAP` add was implicit (would have silently downgraded `"llm_failure"` to `"execution_failure"` without an explicit map entry in `executor_service.py:29-38`).
- The `_trace_collector` rename radius was 14 production sites + 10 test sites + a load-bearing filter at `workflow_trace.py:313` — the plan listed only 8.
- **Empty-response warnings via `__warnings__` would be misclassified.** `runner._extract_runtime_warnings` (line 540-580) wraps every `__warnings__` entry without a matching `__failures__` record into a canned `api_warning` Diagnostic with "Inspect upstream inputs..." remediation. The plan's design would have produced wrong remediation for empty-response cases. Resolution: extend `__warnings__` to support both `str` (legacy) and `dict` shapes, with a `kind` discriminator.
- The string `"llm_failure"` was duplicated between override and map — extracted as `LLM_FAILURE_CATEGORY` constant in `core/diagnostic.py`.
- `parse_structured_response` raised bare `LLMCallError` with no model arg — needed signature update to thread model through to `to_diagnostics()`.
- `FuturesTimeoutError` (pflow's inner pool timeout) is semantically distinct from LiteLLM's `Timeout` and must NOT be translated to `LLMTransientError` — the orphan-thread comment explicitly says don't retry.

### Implementation — 10 commits-worth of work landed

Each step verified via `make test` and `make check` before moving to the next.

**Step 1** (`src/pflow/core/exceptions.py`, `src/pflow/core/diagnostic.py`):
- Added `LLM_FAILURE_CATEGORY = "llm_failure"` constant + `LLM_WARNING_CATEGORY = "llm_warning"` constant + corresponding `CATEGORY_TITLES` entries.
- Updated `LLMCallError.__init__(message, *, model: str | None = None)` — model is now a structured attribute on every instance.
- Added `LLMTransientError(LLMCallError)` — marker subclass for `Timeout`/`RateLimitError`/`InternalServerError`. LLMNode re-raises (so retry loop fires); smart_filter / discovery catch the umbrella.
- Added `LLMResponseParseError(LLMCallError)` — for JSON-parse failures (raised by `parse_structured_response` and the inline JSON-parse path in `LLMNode.post`).
- Updated `MissingApiKeyError` with `kind: Literal["missing_key", "lacks_permission"]` discriminator (mirrors `UnknownModelError.reason` pattern).
- Override `to_diagnostics()` on every subclass — produces Diagnostic with structured context (`category="llm_failure"`, `error_class`, `model`, `reason`/`kind`/`provider_message`) + remediation suggestions + `see_also=["llm"]` (verified valid slug).
- Added `_derive_env_var_for_model(model)` helper — derives `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` from the model prefix for `MissingApiKeyError.to_diagnostics()`'s remediation.
- The `UnknownModelError` override's "your key supports X" hint is gated behind `contextlib.suppress(Exception)` because `llm_config` import is opportunistic (the override is callable from any path including pre-import contexts).

**Step 2** (`src/pflow/core/llm_client.py`):
- Extended catch tuple in `complete()` from 4 to 7 LiteLLM exception classes. `_classify_litellm_error` now handles `Timeout`/`RateLimitError`/`InternalServerError → LLMTransientError`. Every typed exception construction passes `model=model`.
- Added `AdapterResponse.warnings: list[dict[str, Any]]` field. Populated by `_normalize` for empty-content cases. Each entry is a dict with `kind` (machine-parseable discriminator), `text` (human-readable remediation), `context` (structured fields).
- Replaced `logger.warning(...)` empty-response emission with structured `warnings_list.append(...)`. Covered the full finish_reason matrix:
  - `length`/`max_tokens` + reasoning model (`thinking_budget > 0` OR `thinking_tokens > 0`) → `"llm_empty_response_reasoning"` with **dual remediation** (max_tokens OR reasoning_effort)
  - `length`/`max_tokens` + non-reasoning → `"llm_empty_response_max_tokens"` (single max_tokens hint, no misleading reasoning_effort suggestion)
  - `content_filter` → `"llm_empty_response_content_filter"` (provider blocked output)
  - `stop` with empty content → `"llm_empty_response_stop"` (model chose to stop)
  - `None` → `"llm_empty_response_unknown"` (provider didn't report)
  - `tool_calls` → silent (expected LiteLLM shape when model wanted tools)
- Lint-driven extraction: `_normalize` complexity hit C901 (12 > 10). Extracted `_detect_empty_response_warnings(*, text, model, output_tokens, ...)` as a module-level helper. The function signature taxonomy makes the cases scannable; the original inline form was dispatched via nested if/elif.

**Step 3** (`src/pflow/nodes/llm/llm.py` — substantive rewrite):
- DELETED `_error_dict(model, error_class, message)` and `_api_key_tip(detected_model)` helpers (~50 lines).
- Replaced with three module-level helpers: `_error_dict_from_exception(exc: LLMCallError)` (reads `e.to_diagnostics()` + propagates context), `_error_dict_for_timeout(model, message)` (in-thread pool timeout — distinct from LLMTransientError, marks `kind="pool_timeout"`), `_error_dict_for_generic_failure(model, exc, attempts)` (exec_fallback path — handles retry-exhausted timeouts AND unknown deterministic exceptions).
- `_call_llm` exception block collapsed from 3 typed-catch branches (~50 lines) to one `except LLMCallError` (10 lines). The `LLMTransientError` re-raise is one line ahead of the umbrella catch:
  ```python
  except LLMTransientError:
      raise  # let retry loop handle
  except LLMCallError as e:
      return _error_dict_from_exception(e)
  ```
- New helper method `_propagate_error_to_shared(shared, exec_res, *, response_already_set, preserve_usage)` is the single seam for every error path's shared-store mutation. Writes `shared["error"]`, `shared["error_class"]`, `shared["_diagnostic_context"]`, `shared["response"]`, `shared["llm_usage"]`. The `preserve_usage=True` flag keeps usage intact for the JSON-parse path (the call succeeded; only parsing failed). The plan's R-Crit-3 said `LLMResponseParseError`'s shape via `_error_dict_from_exception` — implemented exactly that.
- `post()` reads `adapter_response.warnings` and writes the first entry to `shared.setdefault("__warnings__", {})[node_id]`. Uses `getattr(self, "node_id", None)` (compiler-set dynamic attribute, mypy-friendly). Inline comment explains the NamespacedSharedStore routing-to-root via dunder dispatch.

**Step 4** (`src/pflow/execution/executor_service.py`):
- Added `"llm_failure": "llm_failure"` to `_FAILURE_CATEGORY_MAP` (per R-Crit-1, the explicit map entry).
- Added LLM branch at the end of `_enrich_error_from_node_output`: reads `_diagnostic_context` from `node_output` and merges into `context` via `setdefault` (preserves any keys the runtime path already set, e.g. `category` from `_FAILURE_CATEGORY_MAP`).

**Step 5** (`src/pflow/runtime/node_state.py`, `src/pflow/runtime/engine/engine.py`):
- Added `FAILURE_CATEGORY_LLM = "llm_failure"` constant.
- Added `LLMNode → FAILURE_CATEGORY_LLM` to `_NODE_TYPE_FAILURE_CATEGORY` in engine.py (previously the engine fell through to `FAILURE_CATEGORY_NODE_ERROR`, mapped to generic `"execution_failure"`).

**Step 6** (`src/pflow/registry/smart_filter.py`, `src/pflow/cli/find_errors.py`):
- smart_filter umbrella narrowed to `(LLMCallError, ConnectionError, OSError)`. The bare `TimeoutError` was removed (LiteLLM's Timeout was never caught by it; cold network errors still flow through `ConnectionError`/`OSError`). Inline comment: "Umbrella catch must remain LLMCallError-narrow. Broadening to bare Exception would swallow KeyboardInterrupt, SystemExit, and programming bugs."
- `cli/find_errors.py::handle_discovery_error` now branches on `LLMCallError` (ahead of the generic `report-a-bug` fallthrough). Calls `e.to_diagnostics()[0]`, surfaces the title + message + suggestions directly. Discovery callers (find/find_workflow) get the rich UX for free without duplicating the remediation logic that lives on the exception.

**Step 7** (rename `_trace_collector` → `__trace_collector__`):
- 24 sites updated: 8 production source files + 14 test files + 2 CLAUDE.md files. Used `replace_all=true` per file. The literal-string filter at `workflow_trace.py:313` was the load-bearing site (filters trace-internal keys from saved trace output) — its tuple now contains `("__trace_collector__", "_debug_context", "_batch_trace")`.
- Renaming aligns with existing convention: `__failures__`, `__warnings__`, `__progress_callback__`, `__sub_workflow_events__`, `__memoization_cache__` — all double-dunder. `_trace_collector`'s single underscore was a footgun: `NamespacedSharedStore.__setitem__` routed it into `parent[child_namespace]["_trace_collector"]` for sub-workflows, which happened to work because reads went through the same proxy, but a future iteration over root would silently miss it. The rename routes the key to root deterministically per the proxy's `__*__` bypass rule.
- Verification grep: `grep -rn '"_trace_collector"\|\'_trace_collector\'' src/pflow/ tests/` returns zero hits.

**Step 8** (`src/pflow/execution/formatters/success_formatter.py`):
- Mirror `partial_cost_usd`, `pricing_available`, `unavailable_models` to top-level `result` keys when pricing is unavailable. Lint-driven extraction: `format_execution_success` complexity hit C901 (11 > 10). Extracted `_mirror_pricing_tri_state(result, metrics_summary)` helper.

**Step 9** (`src/pflow/core/llm_config.py`):
- Hardcoded fallback `"gpt-5.2"` → `"openai/gpt-5.2"` (per review-impact-completeness #3 — only OpenAI was unprefixed; Anthropic/Gemini already had prefixes).
- `get_model_not_configured_help` text examples prefixed accordingly.
- Existing test asserting on `"gpt-5.2"` updated; new comment about LiteLLM rejecting bare model names.

**Step 10** (doc/example sweep — 17 files):
- 4 src docs: `src/pflow/guide/features/batch.md`, `src/pflow/guide/nodes/llm.md`, `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md`, `src/pflow/mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md`.
- 7 mintlify docs: `docs/quickstart.mdx`, `docs/guides/debugging.mdx`, `docs/reference/cli/settings.mdx` (8+ examples updated), `docs/reference/configuration.mdx`, `docs/how-it-works/template-variables.mdx`, `docs/how-it-works/batch-processing.mdx`, `docs/reference/nodes/llm.mdx` (4 examples updated).
- 4 example workflows: `examples/test_llm_templates.pflow.md`, `examples/test-worktree.pflow.md`, `examples/real-workflows/release-announcements/workflow.pflow.md` (3 model refs), `examples/real-workflows/vision-scraper/workflow.pflow.md`.
- CLAUDE.md updates: `core/CLAUDE.md` exception hierarchy table refreshed (added `LLMTransientError`/`LLMResponseParseError`, structured discriminator notes); adapter section rewritten to reflect the now-translates-everything contract; "When to use which exception" table gains a row for transient.

### Lint complexity refactor

Two functions hit C901 ("too complex") after additions:

- `_normalize` was 12 (limit 10) — extracted `_detect_empty_response_warnings` as a module-level helper.
- `format_execution_success` was 11 — extracted `_mirror_pricing_tri_state` as a module-level helper.

Both extractions are net-positive for readability: the named helper makes the dispatch table scannable, and the `_normalize` body now reads as "compute tokens + cache stats + thinking, then ask the helper for warnings, then build cost + return." The lint constraint surfaced an abstraction the inline code was hiding — same lesson as §33's `_LLMSummaryAccumulator` extraction.

Test fix from the same refactor: the existing empty-response tests in `tests/test_core/test_llm_client.py` were rewritten to assert on `response.warnings` (the new structured field) instead of `caplog.text`. Added `reasoning_tokens` arg to `make_litellm_response()` callers where needed to drive the reasoning-vs-non-reasoning model branch correctly.

### Architectural insight: NamespacedSharedStore namespacing rules

While doing the rename and adding `_diagnostic_context` writes, I confirmed (and exploited) the following routing rule from `runtime/engine/namespaced_store.py:43-55`:

- Single-underscore prefix (`_x`) — namespaced. Writes go to `parent[node_id]["_x"]`. This is what we want for `_diagnostic_context`: it lands in `shared[node_id]`, which `mark_node_failed` archives to `__failures__[id]["data"]`, which `_enrich_error_from_node_output` reads.
- Double-dunder (`__x__`) — bypass namespacing, write at root. This is what we want for `__warnings__` and `__trace_collector__`. The `setdefault("__warnings__", {})[node_id] = ...` idiom works because the outer `setdefault` returns the root dict (dunder bypass), and the subscript write hits that returned root dict.
- Single-leading dunder OR single-leading underscore without trailing — namespaced. This is why `_trace_collector` was a footgun: it landed in the namespace, not at root, and the rename to `__trace_collector__` routes it to root deterministically.

Verified by the existing `__warnings__` tests (which still pass post-implementation) and the explicit test `test_workflow_trace.py:166-177` that asserts `"__trace_collector__" not in filtered_output` (renamed from `"_trace_collector"`).

### Architectural insight: The PflowError + Diagnostic + executor pipeline

The research phase (Task 1) revealed a load-bearing detail that shaped the design: **the exception object never reaches `exception_to_diagnostics` on the runtime path.** Pre-execution exceptions (from smart_filter, discovery) DO reach it (via `cli/error_output.py::_format_from_exception`). But for runtime exceptions caught inside a node, the exception is consumed at the boundary (LLMNode `_call_llm`'s `except`), converted to an error dict, archived by `mark_node_failed`, and surfaced as a Diagnostic built from scratch by `executor_service.build_error_list`.

This means: **`to_diagnostics()` overrides on `LLMCallError` are valuable for the pre-execution path, but the runtime path needs explicit field forwarding** — hence the `_diagnostic_context: dict` carried in the error dict, lifted by `_enrich_error_from_node_output`. Both paths produce a Diagnostic with the SAME context shape (because both ultimately come from `to_diagnostics()`'s context dict, just via different transport).

This dual-transport design means the override is the single source of truth for the structured fields; no consumer reimplements the remediation logic. Discovery callers, smart_filter (if it ever wanted rich rendering), find_errors, and the runtime path all read from the same `to_diagnostics()` output. The `cli/find_errors.py` LLM branch (Step 6) is the cleanest demonstration: it just calls `e.to_diagnostics()[0]` and renders title + message + suggestions — three lines of code, full UX parity with LLMNode.

### Architectural insight: Why LLM gets its own failure category

Plan-review #2 (review-validation-consistency) raised a parity question: shell, http, mcp all map to generic `"execution_failure"` in `_FAILURE_CATEGORY_MAP`. Why does LLM get its own `"llm_failure"`? Three rationales (documented in plan D9 and inline in `executor_service._FAILURE_CATEGORY_MAP`):

1. **Cost-gating, retry-gating, key-rotation policies are LLM-specific.** Agents most commonly need to filter on LLM failures (cost cap exceeded? retry budget? rotate keys?) — a dedicated category lets them filter without parsing `error_class`.
2. **Remediations are unusually structured.** "Set ANTHROPIC_API_KEY" / "use a provider prefix like openai/" / "lower reasoning_effort" are categorically different from "shell command exited with code 1" or "HTTP 500". Distinct categories let agent-side rendering specialize.
3. **The auth/permission/model-name discriminator hierarchy is unique to LLM.** Shell doesn't have a `kind="missing_key"` vs `"lacks_permission"` discrimination. HTTP doesn't have a `reason="missing_prefix"` discrimination. The structured context fields (`reason`, `kind`, `model`, `provider_message`) are all LLM-specific.

Promoting `shell_failure` / `http_failure` / `mcp_failure` to similarly-specific categories is a follow-up if the agent UX justifies it; out of scope for this work.

### Architectural insight: `_propagate_error_to_shared` as a single seam

The original `LLMNode.post()` had error-handling logic inlined in three places (`_call_llm` typed-catch error path, `exec` `FuturesTimeoutError` path, `exec_fallback`, JSON-parse failure). Extracting `_propagate_error_to_shared(shared, exec_res, *, response_already_set, preserve_usage)` as a single mutation seam paid off:

- All four error paths now produce identical shared-store shape (`error`, `error_class`, `_diagnostic_context`, `response`, `llm_usage`).
- The `preserve_usage=True` flag for the JSON-parse path is the only legitimate divergence — usage was captured before parsing failed, so we want to keep it. Test `test_malformed_json_preserves_usage` pins this.
- A future code path that needs to surface an error from `LLMNode` just builds an `_error_dict_*` and calls `_propagate_error_to_shared(shared, error_dict)` — no risk of forgetting to set `error_class` or `_diagnostic_context`.

### Operational gotchas and hard-won lessons

1. **Mock signature compatibility on monkeypatched functions.** The test `test_malformed_llm_response_returns_original` in `tests/test_registry/test_smart_filter.py` had `mock_parse_error(response, schema)` — a 2-arg mock. After Step 1 added `model: str | None = None` as a kwarg-only parameter on `parse_structured_response`, the production call (`parse_structured_response(response, schema, model=...)`) crashed the mock with `TypeError: got unexpected keyword argument 'model'`. Fix: signature now `mock_parse_error(response, schema, *, model=None)`. Generalization: when adding kwargs to a function, audit existing test mocks for the function — they may need parameter-list updates.

2. **mypy + dynamic compiler attributes.** `LLMNode.post()` reads `self.node_id` — a compiler-set dynamic attribute (`compilation/compiler.py:299`), not declared on the class. mypy flagged it (`"LLMNode" has no attribute "node_id"`). Fix: `node_id = getattr(self, "node_id", None)`. Same pattern §31 used for `_active_trace_hook`.

3. **Lazy imports for circular-dep avoidance.** `core/exceptions.py` is imported very early; `core/llm_config.py::get_default_llm_model()` calls `clear_model_cache()` and other heavy paths. The `UnknownModelError.to_diagnostics()` "your key supports X" hint is opportunistic — wrapped in `contextlib.suppress(Exception)` around a lazy import. The hint is nice-to-have, not load-bearing; if `llm_config` can't be imported (e.g. test environment, partial module load), we silently fall back.

4. **`parse_structured_response`'s typed-exception migration is shallow.** The function now takes `model: str | None = None` and raises `LLMResponseParseError(..., model=model)`. Three call sites pass model: `core/workflow/discovery.py`, `registry/discovery.py`, `registry/smart_filter.py`. The migration is shallow because `LLMResponseParseError` IS-A `LLMCallError` — every caller catching `LLMCallError` continues to work without changes. Only the structured `model` attribute is new, and it's optional.

5. **Test prose is fragile; structured assertions are robust.** Several existing tests in `tests/test_nodes/test_llm/test_llm.py` asserted on prose strings like `"didn't recognize this model name"` that came from the old hand-built messages. After the override-driven prose change, these assertions broke. Fix: tighten them to assert on `_diagnostic_context["reason"]` / `_diagnostic_context["kind"]` directly. The structured fields are the public contract; prose is rendering. The plan's design decision was right (override-driven), but the test migration has to follow.

### Final state (commit-ready)

- 5306 tests pass (no regressions).
- `tests/test_execution/test_plan_drift.py` 32/32 green throughout every step.
- `make check` clean (ruff, ruff-format, mypy, deptry).
- Architectural seal verified: `grep -rn 'import litellm\.exceptions' src/pflow/` returns exactly 1 match (`core/llm_client.py:35`).
- Diff stat: 26 source files + 11 test files + 6 doc/example files = 49 files, 1567 insertions, 378 deletions (net +1189 lines, mostly Diagnostic overrides + structured warnings + tests + docs).
- LLMNode line-count reduction: ~80 lines of helper logic deleted; replaced with ~25 lines of helper + `_propagate_error_to_shared` (~30 lines). Net ~25 lines removed; clarity significantly improved (single error-path mutation seam).

### What the next agent should know

1. **The implementation is feature-complete but has known loose ends.** See the companion document `scratchpads/task-158-phase-A-completion-loose-ends.md` for the full enumeration. The biggest is **integration test coverage** — the new contract that JSON output `errors[i].context` carries `error_class` / `model` / `reason` / `kind` is verified at unit level only, not end-to-end through `WorkflowRunner`.

2. **No commits made.** All 49 files changed live in the working tree. The user's auto-memory is explicit: never `git add` or `git commit` without permission. Diff is on branch `feat/prompt-caching-lite-llm` against last commit `5a070312`.

3. **Architectural patterns established this session that should propagate to Phase B-G:**
   - **Override `to_diagnostics()` on every typed exception subclass.** Single source of truth for prose + structured context. Consumers branch on attributes, never on text.
   - **Adapter is the single seam for ALL exception translation.** No consumer outside `core/llm_client.py` should `import litellm.exceptions`. The grep verifies the seal.
   - **Failure categories drive the JSON shape AND remediation suggestions.** New failure types (e.g. cache-rendering errors in Phase C) should follow the LLMCallError → `to_diagnostics()` override → `_FAILURE_CATEGORY_MAP` entry → `_enrich_error_from_node_output` branch chain.
   - **Use `__*__` keys for cross-cutting shared-store state.** Single-underscore-prefix keys land in NamespacedSharedStore namespaces (which is correct for per-node data like `_diagnostic_context`); double-dunder keys bypass to root (correct for cross-cutting state like `__warnings__`, `__trace_collector__`).
   - **Lint complexity warnings are signal, not noise.** Both C901 hits this session (`_normalize`, `format_execution_success`) surfaced abstractions that the inline code was hiding. Don't suppress; extract.

4. **Phase A code review #2 closure state:** all 3 critical findings + 7 high-value findings addressed; 6 polish items deliberately deferred (documented in the loose-ends doc).

5. **One open user-decision still open from §33:** Gemini PR #15226 fix re-verification on 1.82.6 (~$0.001 spike). Doesn't block Phase B-G plan writing.

### Branch summary (since `8349df88` baseline — full Phase A)

```
8349df88 ready for phase 0 + a    ← baseline
[15 commits §27-§33]
5a070312 refactor(llm): complete adapter seam — typed exception translation for all deterministic LiteLLM errors
[uncommitted: 49 files for Phase A code review #2 closure]    ← current working tree
```

---

## 35. Session 2026-04-25 (cont.) — Performance regression diagnosis + two-stage fix

### Context

User noticed `make test` had grown from ~20s on main to ~1 minute on this branch (86s sequential, 55s+ via xdist after Phase A). Asked to investigate root cause. Investigation revealed a single misplaced import dragging litellm into pflow's eager CLI startup chain — affecting **every** pflow invocation, not just LLM workflows.

### Diagnosis

Profiled `pflow --version` startup with `python -X importtime`:

- Main: 0.27s
- Branch: 1.17-1.92s — **~1s slower per CLI invocation**

The 700ms cumulative cost was traced to `litellm` being eagerly imported. Tracing back the import chain:

```
pflow.cli.main → pflow.runtime.engine → batch_executor.py:21
  from pflow.core.llm_client import enrich_llm_usage_with_cost
    → llm_client.py:35: import litellm  (700ms)
```

`batch_executor.py` is in the eager engine load path. It only needed a 10-line dict-manipulation helper (`enrich_llm_usage_with_cost`) — but importing it dragged in the entire LiteLLM machinery.

**The historical mistake:** A.10 deleted `llm_pricing.py` and moved `enrich_llm_usage_with_cost` into `llm_client.py` (its only nearby home). At the time the helper still had a real job (mirror `total_cost_usd → cost_usd` for ClaudeCodeNode). But in a subsequent (separate) change, ClaudeCodeNode (`claude_code.py:883`) was updated to write `cost_usd` directly at the producer — making the helper's mirror code path obsolete. The helper kept living in the heavy `llm_client.py` module, dragging litellm into the engine for no live behavior.

### Subprocess test multiplier

Per-CLI `pflow` startup × ~30 subprocess tests at 1-2s each = ~30-60s of pure CLI startup overhead in the test suite. Identified as the dominant cause of the 20s → 86s regression.

### Stage 1 fix: Delete the helper entirely

User pushed back on initial proposals: "we should prioritize simplicity of the FINAL code" and "what's the right solution that the top 10% of codebases similar to this one would implement?"

Reframed analysis revealed the helper was already obsolete:

1. ClaudeCodeNode writes `cost_usd` at line 883 (producer-side mirror). Reason #1 in the helper's docstring no longer applied.
2. LLMNode writes `cost_usd` from the adapter response. No mirroring needed.
3. **All consumers use `.get("cost_usd")`** (verified via grep). The helper's "defensive" branch (set `None` if absent) was duplicating what `.get()` does.

**Decision: delete `enrich_llm_usage_with_cost` entirely.** This violates a project principle (CLAUDE.md: "Don't add error handling, fallbacks, or validation for scenarios that can't happen. Trust internal code and framework guarantees").

Files changed:
- DELETED `enrich_llm_usage_with_cost` from `core/llm_client.py` (~30 lines)
- DELETED `enrich_llm_cost` wrapper from `runtime/engine/instrumentation.py` (~10 lines)
- DELETED 4 callsites + their imports: `nodes/llm/llm.py`, `runtime/engine/batch_executor.py`, `runtime/engine/instrumentation.py`, `core/metrics.py` (the latter undid a lazy-import workaround)
- DELETED 2 calls in `runtime/engine/engine.py` (steps 15 and exception path)
- DELETED `TestEnrichLlmUsageWithCost` (5 tests)
- Test fixtures updated: `test_batch_node.py:1764` rewritten to write `cost_usd` directly (matches producer convention)
- Stale comments updated in `test_metrics_integration.py`, `test_metrics_propagation.py`, `claude_code.py`
- CLAUDE.md updates: aligned `core/CLAUDE.md` and `runtime/engine/CLAUDE.md` with new contract; encoded architectural rule "engine modules MUST NOT import `llm_client.py`" (heavy-import module at leaf of dependency graph)

**Stage 1 results:**
- CLI startup: 1.17s → 0.29s ✓
- Non-LLM workflow: 1.05s → 0.27s ✓
- Test suite (sequential `pytest`): 86s → 48.7s
- Test suite (`make test` with `-n 4`): ~18-20s
- litellm in eager CLI chain: 779 hits → **0 hits**
- Tests passing: 5305 (was 5306; one helper test deleted)
- All architectural rules verified: `grep 'import litellm' src/pflow/` → 1 match (`llm_client.py:35`)

### Stage 2 question: --dry-run and analyze-cache still pay 700ms on LLM workflows

After Stage 1, paths that need litellm via LLMNode (real LLM workflows) still paid the 700ms during compilation (since `nodes/llm/llm.py` imports from `llm_client.py` which has top-level `import litellm`). User asked: "would it be any way to avoid dryrun and maybe analyze-cache when we build it to avoid this overhead?"

Investigation confirmed the goal was achievable: lazy-import litellm INSIDE `complete()` and `_classify_litellm_error()`. Module-level `llm_client.py` becomes light; only paths that actually call `complete()` pay the import cost.

### Stage 2 verification of compatibility

Before committing, audited every concern:

| Check | Result |
|---|---|
| Module-level side effects on litellm beyond import | Only `litellm.suppress_debug_info = True` — trivially moved into function body |
| Type annotations referencing litellm | Zero in production code |
| Doctests in `llm_client.py` | None |
| Other modules importing litellm | Zero — `llm_client.py` is sole importer |
| Tests patching `pflow.core.llm_client.litellm.completion` | 20 occurrences in `test_llm_client.py` — would break (the path no longer exists as a module attribute) |
| pytest-xdist worker isolation | Confirmed safe — workers are independent processes, no shared `sys.modules` |

**Migration path:** rewrite the 20 test patches: `"pflow.core.llm_client.litellm.completion"` → `"litellm.completion"`. The decorator's `_get_target` calls `importlib.import_module("litellm")`, which forces import once per worker (cached in `sys.modules`).

### Stage 2 architectural debate: per-node timing fidelity

Lazy import means the first `complete()` call in a process pays ~700ms inside the engine's per-node timing block. That 700ms gets attributed to the first LLM node's `duration_ms` in:
- `pflow report` per-node timing
- `MetricsCollector` summary
- Memo cache `__pflow_stats__["duration_ms"]`
- Future `--dry-run` duration estimates (which read from memo cache historicals)

Three options considered:

| Option | Wins | Loses |
|---|---|---|
| A: Lazy + accept distortion | Fast --dry-run, fast cached runs, fast non-LLM | First LLM node's recorded duration includes 700ms; memo cache records inflated value |
| B: Lazy + pre-warm at engine.run() | Accurate per-node timing | Cached runs pay 700ms even with no API calls (regresses iteration loop) |
| C: Lazy + subtract-via-shared-store | Accurate per-node timing AND fast cached runs | +17 lines of coordination across 3 files; new `__setup_overhead_ms__` shared key; thread-local state in adapter |

User asked: "is it worth the complexity?"

Honest answer: for a real workflow like the lyrics-generator (~181 LLM calls per run), exactly **one** call gets inflated — 0.55% of LLM nodes, below typical noise. For dry-run cost predictions, the user-visible impact is minor (cost is token-based; only duration estimates inflate by 14-30% on one node). The 17-line subtraction mechanism was technically nicer but the complexity-to-value ratio was poor.

**Decision: Option A. Lazy import + accept distortion + document explicitly.**

### Stage 2 implementation

Files changed:
- `core/llm_client.py`:
  - Removed top-level `import litellm`, `import litellm.exceptions`, `litellm.suppress_debug_info = True`
  - Added these inside `complete()` (with `litellm.suppress_debug_info = True` set every call — idempotent and cheaper than a guard check)
  - Added `import litellm.exceptions` inside `_classify_litellm_error()` body (resolves from `sys.modules`)
  - Added module-level docstring explaining the lazy-import pattern + the test-patching implication
- `tests/test_core/test_llm_client.py`: 20 patches rewritten via `sed -i '' 's|@patch("pflow\.core\.llm_client\.litellm\.completion")|@patch("litellm.completion")|g'`
- `core/CLAUDE.md`: added paragraph documenting lazy-import design, the timing distortion, and test-patching requirement

### Implementation gotcha

First implementation used `complete._litellm_silenced = True` as a one-time-init guard. This failed under the autouse `mock_llm_client` fixture: the autouse replaces `pflow.core.llm_client.complete` (the module attribute) with a bound method on `MockLLMClient`. Inside `complete()`'s body, the name `complete` resolved (via Python scoping rules) to the module attribute — which after autouse setup is the bound method. Bound methods don't have `__dict__`. AttributeError.

Lesson: **don't reference a function by name inside its own body when you might be patched.** Setting `litellm.suppress_debug_info = True` every call is idempotent and avoids the issue entirely. Cleaner anyway.

### Final measured results (using `make test` parallel — the canonical command)

| Metric | Main | Pre-fix | After both stages |
|---|---|---|---|
| `pflow --version` | 0.27s | 1.17-1.92s | **0.25-0.34s** ✓ |
| Non-LLM workflow run | 0.27s | 1.05-1.66s | **0.27-0.29s** ✓ |
| `pflow validate` | 0.26s | 1.04s | **0.28s** ✓ |
| `pflow --dry-run` (LLM workflow) | 0.30s | 1.08-1.53s | **0.26-0.30s** ✓ |
| Cached LLM workflow run | 0.29s | 1.06-1.28s | **0.28-0.31s** ✓ |
| `make test` (parallel `-n 4`) | ~24s | ~55s+ | **18-20s** ✓ (faster than main) |
| litellm in eager CLI chain | 0 hits | 779 hits | **0 hits** |
| Tests passing | 5240 | 5306 | **5305** (one helper test deleted) |
| `make check` | green | green | green |

### Architectural rules encoded

Two new rules in CLAUDE.md files prevent regression:

1. **`runtime/engine/CLAUDE.md`**: "Heavy `llm_client.py` MUST NOT be imported by the engine. Engine modules (`instrumentation.py`, `batch_executor.py`, `engine.py`) only need cost-key normalization that the producer (LLMNode/ClaudeCodeNode) handles directly. Importing `llm_client` re-introduces the 700ms litellm cost into every CLI startup."

2. **`core/CLAUDE.md` `llm_client.py` section**: "Litellm is lazy-imported inside `complete()` and `_classify_litellm_error()`. The first call in a process pays the import; subsequent calls resolve from `sys.modules`. The first LLM node's recorded duration is inflated by ~700ms. Tests must patch `litellm.completion` directly (NOT `pflow.core.llm_client.litellm.completion` — the latter no longer exists as a module attribute)."

### Side-objective note (the older 10s→20s drift on main)

User mentioned the test suite has gone from 10s to 20s over the past weeks/months on main, despite only adding ~400 tests. Not investigated as part of this work, but noted: subprocess tests (`test_progress_streaming_subprocess.py`, `test_dual_mode_*.py`) dominate the slow tail at 0.3-0.6s each. **Subprocess tests amortize CLI startup poorly**, and any pflow startup-time creep multiplies through them. Same root-cause pattern as this branch's regression — different driver.

### Commit summary

Single commit covering both stages:
- 14 files changed (5 source, 5 test, 4 docs/CLAUDE.md)
- ~92 insertions, ~210 deletions (net -118 lines)
- All `test_plan_drift.py` 32 sacred parity tests green throughout
- `grep -rn 'import litellm' src/pflow/` → 1 match (`llm_client.py:235` inside `complete()`)

### What the next agent should know

1. **The architectural seal verifications:**
   - `grep -rn 'import litellm' src/pflow/` should return exactly 2 matches: inside `complete()` and inside `_classify_litellm_error()` in `llm_client.py`.
   - `python -X importtime $(which pflow) --version 2>&1 | grep -c litellm` should return `0`.
   - Importing `pflow.nodes.llm.llm` should NOT trigger litellm load (verify with `python -X importtime -c "import pflow.nodes.llm.llm" 2>&1 | grep -c litellm` → `0`).

2. **Pre-existing limitation now documented:** first LLM call's `duration_ms` includes ~700ms of one-time framework init. For multi-call workflows this affects 1/N nodes; for single-call workflows it affects the only LLM node. Cost predictions (token-based) and total wall-clock are unaffected.

3. **Phase B-G implication:** when adding new node types with heavy lazy initialization (e.g. if `claude_code` later grows expensive imports), follow the same pattern — module-level imports for cheap types/data, function-body imports for the heavy machinery. Don't optimize timing fidelity until/unless multiple node types share the issue and a generic mechanism is justified.

### Branch summary (since `8349df88` baseline — full Phase A + perf fixes)

```
8349df88 ready for phase 0 + a    ← baseline
[15 commits §27-§33]
5a070312 refactor(llm): complete adapter seam — typed exception translation
0ce7b838 refactor(llm): complete typed-exception architecture across error pipeline
[this commit] perf(llm): make litellm lazy + delete obsolete cost-key helper
```

---

## 36. Session 2026-04-25 (cont.) — Final Phase A loose-ends pass, focused review, follow-up issues

### Context

After §34, the next agent read the full task context (`scratchpads/task-158-phase-A-completion-loose-ends.md`, prior braindump, task spec, implementation plan, and full progress log). The user then asked for a focused `/code-review` using the four best-suited review agents for the implemented Phase A branch.

Four review agents ran in parallel:

- `review-silent-failures`
- `review-impact-completeness`
- `review-agent-ux`
- `review-concurrency-safety`

Two follow-up `pflow-codebase-searcher` agents verified the two highest-impact findings before any code changes were accepted.

### Review finding triage

**Confirmed must-fix: structured LLM warning dicts in `__warnings__`.**

Phase A Step 2 introduced structured `AdapterResponse.warnings` entries (`kind` / `text` / `context`). `LLMNode.post()` wrote the full warning dict to `shared["__warnings__"][node_id]`, but all existing consumers assumed `__warnings__` values were strings:

- `WorkflowRunner._extract_runtime_warnings()` did substring checks and used the value as `Diagnostic.message`.
- `executor_service._extract_error_info()` used the value as an error message fallback.
- `WorkflowExecutor._extract_child_error()` interpolated the value into an f-string.

The silent-failure risk was real: warning output would render Python dict reprs and JSON diagnostics could carry non-string `message` values.

**Important design decision:** the narrow one-line fix (`LLMNode.post()` writes `warning["text"]`) was rejected after re-evaluating the final-code shape. Structured LLM warnings were introduced deliberately for agent parseability. Dropping `kind`/`context` would solve text rendering by discarding the new contract. The implemented fix keeps the richer contract:

- Added `core.diagnostic.normalize_runtime_warning(warning) -> (message, context)`.
- Updated all three consumers above to normalize legacy string warnings and structured dict warnings.
- `WorkflowRunner._extract_runtime_warnings()` now preserves LLM warning context (`kind`, `model`, `finish_reason`, token counts) and sets `category="llm_warning"` for structured LLM warnings while keeping `type="api_warning"` for backwards-compatible status/rendering behavior.
- `LLMNode.post()` continues writing structured warning dicts.

This is the "top 10% codebase" shape: one normalizer at the shared-store boundary, no scattered dict/string assumptions, and no loss of agent-facing structured data.

**Confirmed but deferred: bare `ValueError` / `TypeError` in `LLMNode.prep()`.**

`review-agent-ux` flagged five bare `ValueError` sites and one `TypeError` in LLM prep/config validation. Verification showed all are pre-existing relative to the branch baseline and the pattern exists across multiple node types. This is real UX debt but not a Phase A regression. It was filed as a follow-up issue instead of being fixed narrowly in LLM only.

**Low-risk branch fixes accepted:**

- Updated the missing-prompt hint from JSON-era syntax (`"prompt": "${previous_node.output}"`) to `.pflow.md` syntax (`- prompt: ${previous_node.output}`) and pinned it in the existing test.
- Cleaned live documentation drift where current docs still described Simon Willison's `llm` library or deleted pricing aliases as current architecture. Historical docs were intentionally left alone.

### Loose ends fixed from scratchpad

The five `LE-*` items from `scratchpads/task-158-phase-A-completion-loose-ends.md` are now fixed:

1. **LE-1 / LE-5 — integration coverage for the LLM JSON diagnostic contract and LLM failure category.**
   - Added `tests/test_execution/test_executor_service_llm.py`.
   - Runs through `WorkflowRunner`, not unit-only helper calls.
   - Covers `UnknownModelError(reason="unknown_name")`, `MissingApiKeyError(kind="missing_key")`, `InvalidRequestError`, and `LLMResponseParseError`.
   - Asserts `result.errors[0].context` carries `category="llm_failure"`, `error_class`, `model`, and discriminator fields.
   - Asserts `result.shared_after["__failures__"]["ask"]["category"] == FAILURE_CATEGORY_LLM`.

2. **LE-2 — `MockLLMClient` warning support.**
   - Added `MockLLMClient.set_response(..., warnings=...)`.
   - Added `_get_warnings()` mirroring `_get_cost()` resolution (exact model/schema, wildcard, default empty list).
   - `reset()` now clears warnings.

3. **LE-3 — stale adapter docstrings.**
   - `llm_client.py` module docstring now states deterministic and transient LiteLLM exceptions are translated.
   - `complete()` docstring now states transient exceptions wrap to `LLMTransientError`; only other exceptions outside LiteLLM's typed hierarchy propagate raw.

4. **LE-4 — `tests/CLAUDE.md` mock behavior drift.**
   - Documented `response.warnings` and `warnings=` in the mock section.
   - Also updated `tests/shared/README.md`.

### Follow-up GitHub issues filed

The remaining review findings were grouped into six GitHub issues rather than implemented in this branch:

- `#347` — Task 158 follow-up: standardize node prep validation diagnostics
- `#348` — Task 158 follow-up: centralize LiteLLM provider metadata for UX hints
- `#349` — Task 158 follow-up: clarify reasoning option edge cases and observability
- `#350` — Task 158 follow-up: normalize zero and partial LLM cost display
- `#351` — Task 158 follow-up: improve batch LLM trace and warning aggregation
- `#352` — Task 158 follow-up: polish secondary LLM diagnostic context

### Verification

Verification after the final fixes:

```bash
uv run pytest tests/test_execution/test_executor_service_llm.py \
  tests/test_execution/test_runner.py \
  tests/test_core/test_llm_client.py \
  tests/test_nodes/test_llm/test_llm.py -q
# 165 passed

make check
# ruff, ruff-format, mypy, deptry all green

make test
# 5311 passed
```

Also verified focused tests during the pass:

- structured warning runner regression: passed
- LLM diagnostic integration regressions: passed
- missing-prompt hint regression: passed

### Current branch state before commit

- All Phase A code-review #2 work from §34 plus final loose-ends fixes from §36 are in the working tree.
- `scratchpads/task-158-phase-A-completion-loose-ends.md` now records LE-1 through LE-5 as fixed.
- Follow-up issues #347-#352 capture the remaining non-blocking review findings.
- One user decision remains open:
  1. Optional Gemini PR #15226 fix re-verification on LiteLLM `1.82.6`.

### What the next agent should know

1. **The structured warning contract is intentionally dict-capable now.** Do not "simplify" by flattening `AdapterResponse.warnings` to strings. Normalize at consumer boundaries via `normalize_runtime_warning()`.

2. **The critical end-to-end LLM diagnostic contract is now pinned.** If a future refactor drops `_diagnostic_context`, the `LLMNode -> __failures__ -> executor_service -> ExecutionResult.errors` tests should fail.

3. **The branch has a larger changed-file set than §34 described.** That is expected: §36 adds final integration tests, warning normalization, mock warning support, and doc cleanup.

4. **The follow-up issues are deliberately grouped.** Avoid reopening them as one-off tiny fixes unless the user asks; each group has cross-cutting implications.

5. **Commit requested by user at end of this session.** Unlike §34, there is now explicit user permission to commit all changes.

---

## 37. Session 2026-04-25 (cont.) — Phase A code review #3 + structural adapter seal fix

### Context

User invoked `/evaluate-review` against `scratchpads/task-158-phase-a-code-review-20260425.md` — a fresh code review against the branch state at HEAD `a913437c`. Five findings, three of them substantive enough to require structural fixes rather than band-aids. Implemented all five via the user's framing principle: **"prioritize simplicity of the FINAL code, not how easy it is to get there."**

### The five findings and their resolutions

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | Critical | `litellm.exceptions.APIConnectionError` (and several other classes) leak raw past the adapter — the enumerative catch tuple was structurally incomplete | Catch `openai.OpenAIError` (the structural base); rewrite `_classify_litellm_error` to dispatch via the full LiteLLM/OpenAI taxonomy |
| 2 | Warning | Bare model names (`gpt-5.2`, `gemini-3-flash-preview`) in user-facing examples | Prefix every example across 8 files (CLI docstrings, README, mintlify docs, settings docstring, adapter docstring) |
| 3 | Warning | `_detect_empty_response_warnings` short-circuited on `output_tokens <= 0`, silencing `content_filter` and `stop` cases | Gate only on `text` and the `tool_calls` carve-out; delete the phantom-case test that encoded the wrong assumption |
| 4 | Suggestion | README documents a `pflow llm` CLI surface that doesn't exist | Replace with real `.pflow.md` workflow examples |
| 5 | Suggestion | Add a parametrized "no raw LiteLLM exceptions past the seam" contract test | Implemented as `TestAdapterSealContract` covering 15 LiteLLM exception classes + a synthetic unknown subclass |

### The big architectural surprise: `litellm.exceptions.OpenAIError` is a sibling, not a base

When I first tried to widen the adapter's catch from the enumerative tuple to `litellm.exceptions.OpenAIError`, every error-path test failed — the catch wasn't matching. Class introspection revealed why:

```
litellm.exceptions.BadRequestError MRO:
  litellm.exceptions.BadRequestError
  openai.BadRequestError                      ← real base
  openai.APIStatusError
  openai.APIError
  openai.OpenAIError                          ← real top
  Exception

litellm.exceptions.OpenAIError MRO:
  litellm.exceptions.OpenAIError              ← sibling class!
  openai.OpenAIError
  Exception
```

`litellm.exceptions.OpenAIError` is **not** the base of LiteLLM's other exception classes — it's a **separate class** that also inherits from `openai.OpenAIError`. Every LiteLLM exception inherits from `openai.OpenAIError` directly (via the OpenAI SDK's class hierarchy), bypassing `litellm.exceptions.OpenAIError` entirely.

Same trap one layer down: `litellm.exceptions.Timeout` does NOT inherit from `litellm.exceptions.APIConnectionError` — it inherits from `openai.APITimeoutError → openai.APIConnectionError`. So `isinstance(exc, litellm.exceptions.APIConnectionError)` returns False for a `Timeout` instance.

**The fix shape**: catch `openai.OpenAIError` in `complete()`; in `_classify_litellm_error`, dispatch via `openai.X` for OpenAI-mirrored classes (covers both raw OpenAI instances and LiteLLM's thin wrappers via inheritance) plus `litellm.exceptions.X` for litellm-only classes (`ServiceUnavailableError`, `BadGatewayError`, `LiteLLMUnknownProvider`).

This means pflow now imports `openai` directly. It was already a transitive dep via litellm, but I declared it explicitly in `pyproject.toml` — deptry's `DEP003` warning was correctly diagnosing that pflow depends on `openai.OpenAIError` as a real public API, not just incidentally.

### The phantom-case test in finding #3

The pre-existing test `test_no_warning_when_zero_tokens_and_empty` asserted that a `length`-finish-reason call with zero output tokens silently returns no warning. The docstring rationalized this as "immediate refusal" — but providers don't actually behave that way. Real refusals come back as `BadRequestError` (4xx) or `finish_reason=content_filter`. The test was encoding a defensive overcorrection.

Worse: the same `output_tokens <= 0` short-circuit silenced `content_filter` cases at zero tokens, which is the actual signal the warning system is for (provider explicit refusal). The reviewer's reproduction:

```python
# text=None, completion_tokens=0, finish_reason="content_filter"
assert complete(model="openai/gpt-4o-mini", prompt="hi").warnings == []  # silently swallowed
```

The fix gates only on `text` and the `tool_calls` carve-out. Every other empty-text case warns — including zero-token cases where the empty response IS the diagnostic.

### LLMNode model fallback: not really removed by this work

The reviewer flagged `nodes/llm/llm.py:276` (`self.params.get("model", "gemini-3-flash-preview")`) as a footgun teaching bare-name routing. Verification revealed it was unreachable in production (compiler at `compiler.py:281-292` either injects a model from settings/auto-detect or raises `CompilationError`), but reachable from ~30 unit tests that bypass compilation by calling `LLMNode()` directly.

**The deeper fix**: delete the fallback entirely; raise `ValueError` if `model` is missing. Production never hits it; tests must set model explicitly. The bulk script approach: a Python regex pass over `tests/test_nodes/test_llm/test_llm.py` and `test_llm_images.py` injecting `"model": "openai/gpt-4o-mini"` into ~60 `set_params({...})` calls that lacked it. Two multi-line dicts got mangled by the regex (double-comma syntax errors); fixed by hand.

**Caveat I'm preserving**: the new raise uses vanilla `ValueError`, not a `PflowError` subclass. CLAUDE.md says to prefer `PflowError`, but `LLMNode.prep` already raises `ValueError` in 4 other places (image not found, image type wrong, invalid reasoning_effort, missing prompt). Switching just my new raise to `InvalidRequestError` would create inconsistency. Switching all of `prep`'s raises is the scope of GH #347 ("standardize node prep validation diagnostics"). Documented; not fixed here.

### Honesty pass after declaring "fully done"

Before declaring complete, I did one more sweep for things I might have missed. Found 6 real loose ends:

1. `tests/test_execution/test_runner.py:86` — fixture warning text used the OLD format from before Step 2.
2. `src/pflow/nodes/llm/README.md:175` — "Available Models" section had bare OpenAI names.
3. Same file:236 — token-usage example JSON had bare `gpt-4o-mini`.
4. `docs/reference/nodes/llm.mdx:64` — "Model support" provider table had bare names for ALL THREE providers (worse than the reviewer flagged).
5. `docs/reference/cli/settings.mdx:422-424` — a SECOND performance comparison table I missed when fixing the one at lines 430-432 (same shape, same problem).
6. `src/pflow/core/llm_client.py:194` — `complete()` docstring used `"gpt-4o-mini"` (bare) as a model arg example.

All six fixed. Lesson: the first audit pass focused on the reviewer's named sites. The honesty pass after looking at the broader pattern caught the rest. **For future similar work, run `grep -rn '\`gpt-[0-9]\|\`gemini-[0-9]\|\`claude-' src/ docs/ | grep -v 'openai/\|anthropic/\|gemini/'` BEFORE declaring done — it surfaces every bare-name occurrence in user-facing files in one shot.**

### Architectural patterns established this session

1. **Catch the structural base, not the friendly-named one.** When dealing with vendored exception hierarchies (LiteLLM wraps OpenAI SDK), check the actual MRO before assuming the package's own `XError` class is the right catch base. `litellm.exceptions.OpenAIError` looks correct semantically but is a sibling, not a parent.

2. **Parametrized contract tests guard structural seals.** The `TestAdapterSealContract` class is the regression guard for "every classified LiteLLM exception wraps to LLMCallError." Adding a new branch to `_classify_litellm_error` requires adding a row; forgetting to add a class to the classifier surfaces as the synthetic-unknown-subclass test asserting the safe-default fallback. Both halves of the seal are pinned.

3. **Default-fallback exceptions should be deterministic, not transient.** When a future LiteLLM subclass appears that we haven't classified, the default branch wraps it as `InvalidRequestError` (deterministic, no retry). Wrong call: defaulting to `LLMTransientError` would infinite-retry an unknown server condition. The right call: fail-fast and add an explicit branch when the new class surfaces in real workloads.

4. **`output_tokens <= 0` is not a useful gate for "empty response."** Provider refusals fire with zero tokens. The right gate for "this isn't a warning" is presence of text, not presence of token consumption.

### Operational gotchas worth remembering

1. **`@patch("litellm.completion")` works regardless of how the production code imports litellm.** The autouse mock-resolution rules are documented in `tests/CLAUDE.md`; the test file's existing pattern is the path of least resistance.

2. **Bulk regex-injection into multi-line dict literals is fragile.** When updating `set_params({...})` calls that span multiple lines, the regex may grab content past a comma and produce double-comma syntax errors. Verify by running the test suite after the script; fix any syntax errors by hand.

3. **`pflow llm` does not exist as a CLI command.** Anyone documenting "how to use the LLM node" must do so via `.pflow.md` workflow snippets. The README rewrite established this pattern; future doc writers should follow.

4. **NamespacedSharedStore namespacing rules** (recap from §34): single-underscore-prefix keys land in node namespace; `__*__` double-dunder keys bypass to root. `__warnings__` and `__trace_collector__` use the dunder convention deliberately.

### Files changed in this session

**Source:**
- `src/pflow/core/llm_client.py` — module docstring + `complete()` catch + classifier rewrite + docstring example fix
- `src/pflow/nodes/llm/llm.py` — fallback removal + explicit `ValueError` raise
- `src/pflow/cli/commands/settings.py` — three CLI docstring example blocks prefixed
- `src/pflow/core/settings.py` — LLMSettings docstring examples prefixed
- `src/pflow/nodes/llm/README.md` — full Usage section rewrite + Available Models prefix + token-usage example fix

**Tests:**
- `tests/test_core/test_llm_client.py` — adapter contract test class added (16 parametrized cases + synthetic-unknown test); zero-token warning tests added; phantom-case test deleted; module docstring updated
- `tests/test_registry/test_smart_filter.py` — `APIConnectionError` graceful-degradation regression test
- `tests/test_nodes/test_llm/test_llm.py` — ~47 `set_params` calls injected with explicit model
- `tests/test_nodes/test_llm/test_llm_images.py` — ~12 `set_params` calls injected with model + 2 multi-line dict fixes
- `tests/test_execution/test_runner.py` — fixture warning text format aligned with new gate

**Docs:**
- `docs/reference/cli/settings.mdx` — auto-detect default table OpenAI fix + 2 performance comparison tables prefixed
- `docs/reference/nodes/llm.mdx` — Model support table prefixed for all three providers + intro sentence

**Dependencies:**
- `pyproject.toml` — `openai` declared as direct dep (was transitive via litellm)
- `uv.lock` — regenerated

### Verification at handoff

- `make test`: 5325 passed
- `make check`: ruff, ruff-format, mypy, deptry all green
- `tests/test_execution/test_plan_drift.py`: 32 sacred parity tests green throughout every step
- Architectural seal: `grep -rn 'litellm\.exceptions\|import openai' src/pflow/` returns matches only in `core/llm_client.py` (the seam) — no consumer outside the adapter imports either
- New tests: 16 contract cases + 1 synthetic-unknown + 4 zero-token warning + 1 smart-filter regression = 22 new test cases

### What the next agent should know

1. **The seal claim is now structurally enforced.** "No LiteLLM exception leaks past the adapter" is true via `openai.OpenAIError` catch + the parametrized contract test. Future LiteLLM additions automatically wrap as `InvalidRequestError` until classified explicitly.

2. **`LLMNode()` requires `model` in params.** Tests that construct LLMNode directly must set `"model": "..."` in `set_params({...})` — there is no silent fallback. The autouse `mock_llm_client` doesn't validate the model name, so `"openai/gpt-4o-mini"` is the conventional test default.

3. **Empty-response warnings now fire for all empty-text cases except `tool_calls`.** Previously the `output_tokens <= 0` short-circuit silenced provider refusals; now the gate is just text presence + the `tool_calls` carve-out.

4. **Sibling-vs-base class hierarchies are a real trap.** When working with libraries that wrap other libraries' exceptions (LiteLLM wraps OpenAI SDK), introspect MRO before assuming `<package>.exceptions.XError` is the catch base. The actual base may be one layer down in the wrapped library.

### Branch summary (since `8349df88` baseline — full Phase A + perf fixes + this review pass)

```
8349df88 ready for phase 0 + a    ← baseline
[15 commits §27-§33]
5a070312 refactor(llm): complete adapter seam — typed exception translation
0ce7b838 refactor(llm): complete typed-exception architecture across error pipeline
a7d8c777 braindump + progress log updates
83e90598 fix(llm): close Phase A diagnostic warning gaps
a913437c perf(llm): remove litellm from eager CLI path; lazy-import inside complete()
bb51a3cb refactor(llm): widen adapter seal to openai.OpenAIError + simplify empty-response gate
1b21b0f9 agent instructions
```

---

## 38. Session 2026-04-26 — End-to-end verification + 3 fixes from bare-model-name regression

### Context

Independent verification session against the full Phase A branch. Goal: try to break the implementation, not confirm it works. Ran 35 manual end-to-end tests across all providers (Anthropic, Gemini, OpenAI), all node types, batch, sub-workflows, error paths, `--report`, `--dry-run`, `--no-cache`, `--validate-only`, structured output, extended thinking, and pre-Phase-A trace backwards compatibility.

### Verification results (31 passing, 1 finding)

All core functionality verified working with no regressions:
- CLI startup: 0.3s (no litellm drag)
- All 3 providers: Anthropic, Gemini, OpenAI real API calls succeed
- Structured output + thinking composition works
- Batch LLM (3 items, parallel) with per-item prompt capture in traces
- Sub-workflow with LLM: cost rolls up, trace captures child LLM prompts
- `--report` across all scenarios: chain, batch, nested, error, thinking, pre-Phase-A traces
- `--dry-run`: 0.37s, no litellm import cost
- `--validate-only`: 0.5s
- Error paths: `UnknownModelError` with discriminator, `MissingApiKeyError` with actionable remediation
- `cache: false` memoization opt-out still works
- Example workflows all validate
- Guide and settings help text: no stale `llm` library references
- Architectural seal: zero `import llm` / `from llm import` in codebase; litellm only in `llm_client.py`
- `make test`: 5325 passed, `make check`: all green

### The finding: bare model names in settings → wrong provider routing

User's settings had `gemini-3-flash-preview` (bare, no prefix). LiteLLM routes bare Gemini names to Vertex AI (needs Google Cloud SDK) instead of Google AI Studio (uses `GEMINI_API_KEY`). Three symptoms:

1. **Wrong routing** — bare `gemini-3-flash-preview` → Vertex AI path → `APIConnectionError: Google Cloud SDK not found`
2. **3 retries on permanent failure** — `APIConnectionError` classified as `LLMTransientError` → retry loop burns 3 attempts on an error that will never succeed (missing SDK install)
3. **Massive stderr noise** — LiteLLM's ERROR logger dumps 3 × 40-line Vertex credential tracebacks before the adapter exception handler fires

Root cause: the adapter didn't fully abstract LiteLLM's model-naming convention from the rest of pflow. Three fixes, all in the adapter seam:

### Fix 1: Auto-prefix bare model names

**Two layers:**

- **Settings CLI** (`cli/commands/settings.py`): new `_normalize_and_warn_model()` shared by all 3 `set-*` commands. Normalizes at write time with user feedback:
  ```
  $ pflow settings llm set-default gemini-3-flash-preview
    Normalized: gemini/gemini-3-flash-preview
  ✓ Set default_model: gemini/gemini-3-flash-preview

  $ pflow settings llm set-default banana
    ⚠ 'banana' doesn't match any known provider (anthropic/, gemini/, openai/).
      If this is a custom or self-hosted model, it will be passed to LiteLLM as-is.
  ✓ Set default_model: banana

  $ pflow settings llm set-default anthropic/claude-sonnet-4-5
  ✓ Set default_model: anthropic/claude-sonnet-4-5
  ```

- **Adapter** (`core/llm_client.py`): `_normalize_model_name()` called at the top of `complete()` as a safety net for model names from workflow files. Maps `claude-*` → `anthropic/`, `gemini-*` → `gemini/`, `gpt-*`/`o1-*`/`o3-*`/`o4-*` → `openai/`. Already-prefixed names and unknown bare names pass through unchanged.

### Fix 2: Permanent `APIConnectionError` from missing SDK → no retry

In `_classify_litellm_error()`: before classifying `APIConnectionError` as `LLMTransientError`, check for `ImportError` in the `__cause__` chain via `_has_import_error_cause()`. Missing SDK installs are permanent failures — retrying won't install the package. Classified as `InvalidRequestError` with the install hint extracted by `_extract_install_hint()`.

Result: one clean error, zero retries, ~0.8s instead of ~3s.

### Fix 3: Silence LiteLLM's redundant ERROR logger

`logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)` inside `complete()`, alongside the existing `suppress_debug_info`. The adapter's typed exception system is the single error surface; the logged tracebacks are redundant noise that reaches stderr before the adapter can produce a clean message.

### Bonus: probe command missing `inject_settings_env_vars`

Pre-existing issue (confirmed on main), but trivial to fix: one lazy import + one function call in `probe.py`. Now `pflow probe llm prompt="..."` works with settings-stored API keys.

### Verification after fixes

- `make test`: 5342 passed (5325 original + 17 new `TestNormalizeModelName` tests)
- `make check`: all green
- Manual: bare model name in workflow file → auto-prefixed → works
- Manual: `vertex_ai/` model with missing SDK → one clean error, no retries, no stderr noise
- Manual: `pflow probe llm` → works with settings-stored keys
- Manual: settings normalization UX for all 3 cases (known bare, unknown bare, prefixed)

### Files changed

| File | Change |
|------|--------|
| `src/pflow/core/llm_client.py` | `_normalize_model_name()`, `_has_import_error_cause()`, `_extract_install_hint()`, LiteLLM logger → CRITICAL |
| `src/pflow/cli/commands/settings.py` | `_normalize_and_warn_model()` shared by all 3 set commands |
| `src/pflow/cli/commands/probe.py` | `inject_settings_env_vars()` call |
| `tests/test_core/test_llm_client.py` | 2 assertion fixes + 17 new normalization tests |
| `tests/test_cli/test_settings_cli.py` | 5 assertion fixes |

### Patterns worth noting for Phase B-G

1. **Normalize at the seam, not scattered.** Model-name normalization belongs in the adapter (where pflow meets LiteLLM). The settings CLI normalizes at write time for immediate user feedback, but the adapter is the safety net.

2. **Walk `__cause__` for permanent-vs-transient classification.** `APIConnectionError` from a missing `import` is permanent; from a network timeout is transient. The exception chain distinguishes them. This pattern generalizes to any wrapper exception that conflates permanent and transient causes.

3. **Own your dependency's logging surface.** LiteLLM's ERROR logger writes to stderr before exceptions reach the adapter. Setting the logger to CRITICAL lets the adapter's typed exception system be the single error surface.

---

## 39. Session 2026-04-26 — Structural review-fix pass after Task 158 code review

### Context

After the Task 158 code review, the first instinct was to apply narrow fixes: add `o4-*` in two missing places, add a warning for unknown empty responses, add a few diagnostics tests, and clean up fixtures. User pushed back with the right frame: optimize for the final code, not the easiest patch. The re-evaluation showed several review findings were symptoms of duplicated contracts:

- Provider metadata lived in three independent places:
  - `core/llm_client.py::_BARE_MODEL_PREFIX_MAP`
  - `core/llm_reasoning_map.py::_detect_capabilities`
  - `core/exceptions.py::_derive_env_var_for_model`
- Transient provider failures were structurally classified at the adapter seam, then collapsed into an untyped `LLMTransientError`.
- LLM diagnostics repeated context dictionaries by hand, so some subclasses preserved provider messages and others dropped them.
- Reasoning options had two paths: dedicated `reasoning_kwargs` and raw `model_options`, making it possible to bypass the adapter's provider-specific reasoning validation.
- `parse_structured_response()` promised typed schema failures but still returned raw invalid dicts after Pydantic validation failed.

Decision: do the structural fixes now while the adapter seam is already under review, rather than leaving future provider/model additions to rediscover the same drift.

### Decisions made

#### 1. New canonical provider registry

Added `src/pflow/core/llm_providers.py` with a dependency-free `ProviderInfo` registry:

- `name`
- `provider_prefix`
- `bare_prefixes`
- `env_var`

Current registry:

- Anthropic: `anthropic/`, bare `claude-`, env `ANTHROPIC_API_KEY`
- OpenAI: `openai/`, bare `gpt-`, `o1`, `o3`, `o4`, env `OPENAI_API_KEY`
- Gemini: `gemini/`, bare `gemini-`, env `GEMINI_API_KEY`

The registry exposes:

- `detect_provider(model)`
- `normalize_model_name(model)`
- `model_name_without_provider(model, provider)`

Trust boundary:

- **Verified**: used by model normalization, missing-key env hints, reasoning capability detection, and Anthropic reasoning translation.
- **Intentional behavior**: provider-prefixed matching is exact `startswith(provider_prefix)`. `openrouter/anthropic/claude-sonnet-4-5` is not classified as Anthropic. If pflow later supports OpenRouter/Bedrock-specific reasoning, those should become explicit provider entries or explicit routing rules rather than substring matches.

Outcome: the `o4-*` issue is fixed structurally. Adding `o5` later should be one registry-line plus any family-specific reasoning decision, not a hunt through adapter, diagnostics, and reasoning code.

#### 2. LLM diagnostic context is now a base-class invariant

Added `LLMCallError.diagnostic_context(**extra)` in `core/exceptions.py`.

Every LLM diagnostic now includes:

- `category`
- `error_class`
- `model`
- `provider_message`

Subclasses extend that base context with structured fields such as `reason`, `kind`, `env_var`, or `package`. This removes the "InvalidRequestError remembered provider_message, MissingSdkError forgot it" failure mode.

Important detail: `provider_message` is currently `str(self)`, i.e. the pflow-wrapped provider message. This is the stable message that reaches users and diagnostics. It is not a raw LiteLLM object.

#### 3. `LLMTransientError` now has `kind`

`LLMTransientError` now mirrors the established typed-discriminator pattern used by:

- `UnknownModelError(reason=...)`
- `MissingApiKeyError(kind=...)`

Transient kinds:

- `timeout`
- `rate_limit`
- `server_error`
- `connection`

`_classify_litellm_error()` maps LiteLLM/OpenAI exception classes to these kinds:

- `litellm.exceptions.Timeout` -> `timeout`
- `openai.RateLimitError` -> `rate_limit`
- `openai.InternalServerError`, `ServiceUnavailableError`, `BadGatewayError` -> `server_error`
- other `APIConnectionError` -> `connection`, unless the exception chain indicates missing SDK

`LLMTransientError.to_diagnostics()` now has targeted suggestions. `LLMNode.exec_fallback()` preserves the transient subtype after retry exhaustion as:

- `kind: retry_exhausted`
- `transient_kind: <timeout|rate_limit|server_error|connection>`

This keeps retry-loop semantics unchanged while giving downstream agents actionable cause data.

#### 4. `model_options` cannot carry reasoning keys

Rejected reasoning-shaped keys in raw `model_options` at the adapter boundary:

- `thinking`
- `thinking_budget`
- `thinking_effort`
- `reasoning_effort`
- `reasoning_max_tokens`
- `thinking_level`

Reason: pflow already has dedicated `reasoning_effort` and `reasoning_max_tokens` channels. Letting `model_options` override or bypass them makes provider-specific translation and validation ambiguous.

Decision: hard-fail with `InvalidRequestError`, not warn-and-merge.

Rationale:

- Failing fast is simpler than merging two sources with precedence rules.
- It preserves one reasoning path through `map_reasoning_options()` and `_translate_reasoning_for_litellm()`.
- It prevents silent user-intent drops, especially Anthropic `thinking=True` without a budget.

Also added an internal invariant in `_translate_reasoning_for_litellm()`: Anthropic `thinking=True` without `thinking_budget` or `thinking_effort` raises `InvalidRequestError` instead of silently returning `{}`.

#### 5. Empty response fallback now matches its own contract

`_detect_empty_response_warnings()` already documented the desired invariant:

- text present -> success, no warning
- `finish_reason == "tool_calls"` -> expected no-content shape, no warning
- every other empty-text response -> anomaly worth surfacing

The code previously returned `[]` for any future unrecognized finish reason. That was a silent empty success. Added:

- `kind: llm_empty_response_unrecognized_finish_reason`
- context with `model`, `finish_reason`, token counts, and thinking fields

This keeps the adapter future-tolerant without hiding suspicious empty responses.

#### 6. Structured response validation now fails typed

`parse_structured_response()` now raises `LLMResponseParseError` when:

- JSON parses but fails Pydantic validation for the expected schema
- JSON is valid but not an object for the expected Pydantic schema

Previous behavior logged validation failures and returned raw dicts, which let callers fail later with confusing `KeyError` or `TypeError`. The function now matches its own docstring and the exception hierarchy's promise: schema parse/validation failures are LLM response parse failures.

Discovery and smart-filter tests stayed green after this stricter behavior.

#### 7. Batch top-level prompt race was intentionally not refactored

Review noted that `WorkflowTraceCollector.llm_prompts` is keyed by `node_id`, so direct parallel batch LLM calls can only store one aggregate prompt for the batch wrapper. Per-item prompt capture is correct via each item output's `prompt` field and `batch_items[i].llm_prompt`.

Decision: do not refactor trace storage to `(node_id, item_index)` or lists in this task.

Rationale:

- The aggregate prompt is representative only.
- Per-item prompt data is the authoritative batch trace surface.
- Changing the aggregate storage shape would touch broader trace consumers for little practical value.

Added/kept an invariant test that asserts:

- every batch item has its own prompt
- aggregate `llm_prompt` is one of those prompts, not a deterministic per-item source

### Files changed in this pass

| File | Important change |
|------|------------------|
| `src/pflow/core/llm_providers.py` | New canonical provider metadata registry |
| `src/pflow/core/llm_client.py` | Uses provider registry, rejects reasoning keys in `model_options`, classifies transient kinds, warns on unknown empty `finish_reason`, warning-level trace-hook failures |
| `src/pflow/core/llm_reasoning_map.py` | Uses provider registry for provider detection; `o4-*` reasoning support now coherent |
| `src/pflow/core/exceptions.py` | Base LLM diagnostic context invariant, transient diagnostics, env-var hints from provider registry |
| `src/pflow/core/llm_utils.py` | Pydantic validation failures now raise `LLMResponseParseError` |
| `src/pflow/nodes/llm/llm.py` | Retry exhaustion preserves `LLMTransientError.kind` as `transient_kind` |
| `src/pflow/core/CLAUDE.md` | Documents `llm_providers.py` in the core module map |
| `tests/test_core/test_llm_providers.py` | New provider registry tests |
| `tests/test_core/test_llm_utils.py` | New structured-response validation tests |
| `tests/test_core/test_llm_client.py` | New diagnostics, reasoning-key validation, transient-kind, unknown-finish-reason, trace-hook logging tests |
| `tests/test_core/test_llm_reasoning_map.py` | `o4-*` and OpenRouter false-positive regression tests |
| `tests/test_nodes/test_llm/test_llm.py` | LLMTransientError retry-exhaustion regression; fixture usage shape cleanup |
| `tests/test_integration/test_metrics_integration.py` | Fixture usage shape cleanup; stale mock comment removed |
| `tests/test_runtime/test_trace_integration.py` | Batch aggregate prompt invariant documented/tested |

### Verification

Focused suites:

- `uv run pytest tests/test_core/test_llm_client.py tests/test_core/test_llm_providers.py tests/test_core/test_llm_utils.py tests/test_core/test_llm_reasoning_map.py tests/test_nodes/test_llm/test_llm.py tests/test_integration/test_metrics_integration.py tests/test_runtime/test_trace_integration.py`
- Result: 275 passed

Discovery/error related suites:

- `uv run pytest tests/test_registry/test_smart_filter.py tests/test_registry/test_component_discovery.py tests/test_execution/test_executor_service_llm.py`
- Result: 41 passed

Repository checks:

- `make check`: passed
  - ruff
  - ruff-format
  - mypy: no issues in 184 source files
  - deptry

Full suite:

- `make test`: 5361 passed

### Critical information for future agents

1. **Provider metadata now has one canonical home.** Do not add model-family prefixes directly to `llm_client.py`, `llm_reasoning_map.py`, or `exceptions.py`. Add provider facts to `llm_providers.py`, then add family-specific capability logic only where needed.

2. **Prefix matching is deliberately exact.** `openrouter/anthropic/...` is not Anthropic for pflow's purposes. Do not reintroduce `"anthropic/" in name` substring checks unless OpenRouter semantics are explicitly designed and tested.

3. **`model_options` is no longer a reasoning escape hatch.** Reasoning options must use `reasoning_effort` or `reasoning_max_tokens`. Raw provider kwargs are still allowed for non-reasoning options like `top_p`.

4. **Every LLM diagnostic should include `provider_message`.** Use `LLMCallError.diagnostic_context()` when adding subclasses. Do not hand-build LLM diagnostic context dicts unless there is a documented reason.

5. **Transient failures are typed twice.** During provider classification, `LLMTransientError.kind` captures the provider failure subtype. After LLMNode retry exhaustion, diagnostic context uses `kind="retry_exhausted"` and preserves the original subtype as `transient_kind`.

6. **Structured response validation is now strict.** Callers of `parse_structured_response()` should expect `LLMResponseParseError` when the model returns valid JSON with invalid schema shape. This is intentional.

7. **Trace-hook errors are warning-level logs.** This makes trace capture regressions visible without breaking workflows. If this becomes noisy, fix the trace hook bug rather than lowering visibility silently.

### Review findings closed by this pass

- `o4-*` prefix drift between normalization, reasoning, and diagnostics
- Missing `provider_message` in `MissingSdkError` diagnostics
- Generic `LLMTransientError` diagnostics
- `model_options` reasoning-key bypass and Anthropic `thinking=True` silent drop
- Unknown empty-response `finish_reason` silent success
- Pydantic validation swallow in `parse_structured_response()`
- Batch top-level prompt semantics documented/tested without broad trace churn
- Fixture usage shape drift (`thinking_tokens` / `thinking_budget`)
- Stale test comment about removed `mock_llm` fixture

### Follow-up dead-code deletion: `CriticalDiscoveryError`

After the structural review-fix pass, we did a focused grep/read pass for `CriticalDiscoveryError` because its remaining CLI handler looked like legacy Anthropic-specific discovery auth handling.

Findings:

- `CriticalDiscoveryError` was not raised anywhere in production code.
- Its only live production reference was an unreachable branch in `src/pflow/cli/find_errors.py`.
- LLM discovery failures now propagate through `LLMCallError` and each exception's own `to_diagnostics()` implementation, so keeping a parallel discovery-specific exception path would reintroduce duplicated remediation text and stale provider assumptions.
- Test coverage only instantiated the class to prove hierarchy membership, which was evidence of dead code rather than active behavior.

Action:

- Deleted `CriticalDiscoveryError` from `src/pflow/core/exceptions.py`.
- Removed the unreachable branch and import from `src/pflow/cli/find_errors.py`.
- Removed the class from `src/pflow/core/CLAUDE.md` and exception hierarchy tests.

Verification:

- `rg "CriticalDiscoveryError" src/pflow tests`: no matches.
- `uv run pytest tests/test_core/test_exception_hierarchy.py`: 10 passed.

---

## 40. Session 2026-04-26 — Post-§39 review caught two regressions and a half-truth

After §39 landed, an evaluation pass over the structural review-fix work surfaced three issues the §39 author hadn't caught — including one production regression that the §39 changes themselves *introduced*. Each fix is small in code but architecturally consequential.

### Issue 1: `_validate_model_options` rejected smart_filter's actual usage (production regression)

§39 added `_validate_model_options` to enforce "model_options is for non-reasoning kwargs only." The validator rejects `thinking`, `thinking_budget`, `thinking_effort`, `reasoning_effort`, `reasoning_max_tokens`, `thinking_level` keys — exactly what `src/pflow/registry/smart_filter.py` was passing to disable reasoning on Gemini-3 (`thinking_level=minimal`) and Gemini-2.5 (`thinking_budget=0`).

The autouse `mock_llm_client` fixture in `tests/conftest.py` patches `pflow.core.llm_client.complete` directly, bypassing the real `_validate_model_options`. So the existing `TestGeminiThinkingHeuristics` tests happily passed assertions against the mock while production would have crashed with `InvalidRequestError` on the first Gemini-3 / Gemini-2.5 filtering call.

**Why this matters as a class of bug**: any production validation we add inside `complete()` is invisible to tests using the autouse mock. The autouse mock is necessary (real LLM calls in unit tests = $$$ + flake), but it widens the class of "structural bugs that pass tests." Mitigation: when adding validation at the seam, also add at least one test that patches `litellm.completion` (one layer below `complete()`) to exercise the real validation pipeline. The seal-contract tests in `test_llm_client.py` already do this.

**The fix** routes smart_filter through the canonical reasoning channel — the same channel user-facing LLM nodes use:

- `src/pflow/registry/smart_filter.py`: deleted the `gemini-3` / `gemini-2.5` substring heuristic. Replaced with `reasoning_kwargs=map_reasoning_options(filtering_model, "none", None, None) or None`. The translator handles per-provider mapping; smart_filter doesn't duplicate provider detection.
- `src/pflow/core/llm_reasoning_map.py::map_reasoning_options`: extended the `effort="none"` branch to handle `thinking_level` capability (Gemini 3 has no off-switch — `"minimal"` is the lowest equivalent). This is a latent gap independently: a user passing `reasoning_effort: none` to a Gemini 3 LLM node previously got default expensive thinking, silently. Now they get `thinking_level=minimal` consistently with the disable-where-possible semantics.
- Tests rewritten: `TestGeminiThinkingHeuristics` → `TestSmartFilterMinimizesReasoning`. Assertions moved from `last_call["model_options"]` to `last_call["reasoning_kwargs"]`. Added explicit `assert last_call["model_options"] is None` regression guard in every parametrized case so a future pattern that re-introduces the bypass fails loudly. Added a new `test_disable_gemini_3` case in `test_llm_reasoning_map.py` to pin the new `effort="none" + thinking_level` mapping.

### Issue 2: `_diagnostic_context["provider_message"]` lied about its contents

§39 introduced `LLMCallError.diagnostic_context()` as a base-class invariant that includes `"provider_message": str(self)`. This was correct for the four subclasses that pass `str(exc)` as their constructor message (`MissingSdkError`, `LLMTransientError`, `LLMResponseParseError`, `InvalidRequestError`) — `str(self)` IS the raw provider text in those cases.

But two subclasses construct a pflow-wrapped message and discard the raw upstream text:

- `MissingApiKeyError("API key required for model 'X'", ...)` — `str(self)` is the wrapper, NOT the provider's "Quota exceeded" / "Invalid key" / "Account suspended" text.
- `UnknownModelError("Unknown model: X", ...)` — `str(self)` is the wrapper, NOT the provider's "model retired on Y" / "not available in your region" text.

The base-class `diagnostic_context["provider_message"]` was therefore a half-truth: agents reading it for two of six subclasses got pflow's own framing dressed up as if it were the provider's message. Real failure modes that need different remediation (quota vs invalid-key, retired-model vs typo, region-restricted vs missing) collapsed to identical generic suggestions.

**The fix** makes `provider_message` an explicit typed field on `LLMCallError`:

- `src/pflow/core/exceptions.py::LLMCallError.__init__`: new optional kwarg `provider_message: str | None = None`, stored as `self.provider_message`.
- `LLMCallError.diagnostic_context()`: surfaces `self.provider_message` honestly (no more `str(self)` masquerade). `None` when no upstream exception was present (e.g. constructed inside pflow rather than translated from LiteLLM) — an honest signal rather than a lie.
- All four wrapping subclasses (`UnknownModelError`, `MissingApiKeyError`, `LLMTransientError`, `MissingSdkError`) take and forward `provider_message` to the base. `InvalidRequestError` and `LLMResponseParseError` inherit the kwarg automatically (no `__init__` override needed).
- `src/pflow/core/llm_client.py::_classify_litellm_error`: threads `provider_message=str(exc)` to every classification branch (8 sites including the default fallback for unknown OpenAI subclasses). Captures `raw = str(exc)` once at the top of the function so every branch uses the same text.
- `src/pflow/core/CLAUDE.md`: updated the "When to use which exception" table to document `provider_message` as a structured discriminator distinct from pflow-wrapped `Diagnostic.message`.

**Pattern worth keeping**: the `Diagnostic.message` (WHAT) and `context.provider_message` (WHY) split is the right shape for typed exceptions that wrap. Don't cram both purposes into one string. The wrapped form makes the diagnostic readable; the raw form makes it actionable.

### Issue 3: parametrized seal-contract tests didn't assert `provider_message` was threaded

The §39 seal-contract test (`test_litellm_exception_wraps_to_typed_pflow_exception`) verified every classified LiteLLM exception became some `LLMCallError` subclass. It did NOT verify the seam threaded `provider_message=str(exc)` to that subclass — a regression dropping `provider_message=` on any classification branch would silently revert structured discrimination without failing any test.

**The fix**: added `test_seam_threads_provider_message_to_every_classification` to `TestAdapterSealContract`, parametrized over the same `_SEAL_CONTRACT_CASES`. Asserts `exc_info.value.provider_message == str(upstream)` AND that `to_diagnostics()[0].context["provider_message"] == str(upstream)` for every classification (auth, permission, unknown-model, missing-prefix, transient, content-policy, schema-validation, etc.). Plus the unknown-future-subclass test now asserts the same on the default branch.

### Decisions made

- **`provider_message` as optional kwarg, not positional.** Constructed-inside-pflow `LLMCallError` instances (e.g. `LLMResponseParseError` raised by `parse_structured_response`'s JSON parse failure path) correctly default to `provider_message=None` — there's no upstream exception to capture. Honest about absence.
- **Did not have suggestions consume `provider_message` text** for finer remediation. e.g. `MissingApiKeyError` with `provider_message` containing "quota" could surface a billing-review hint. That's substring-matching across the abstraction boundary — exactly what the structural pass tried to avoid. The right way to discriminate quota-vs-key is a typed sub-discriminator (`MissingApiKeyError(kind="quota_exceeded")`) detected at the seam. Out of scope; provider_message exposing the raw text already lets agents read the WHY directly.
- **Did not rename `provider_message`** to `upstream_message`. For the `LiteLLMUnknownProvider` case the message is technically LiteLLM-side rather than provider-side, but the field captures "raw upstream exception text" generally and the established naming is fine. Bikeshedding boundary.

### What this fix exposes about the autouse-mock testing pattern

The smart_filter regression slipped past §39's tests because the autouse mock at `pflow.core.llm_client.complete` replaces the function entirely. Tests asserting on `mock_llm_client.call_history[-1][...]` see the kwargs passed to the mock — the mock doesn't run validation, doesn't raise on bad inputs, and doesn't simulate the production seal.

**Mitigation pattern documented in `tests/CLAUDE.md` already** — "patch `litellm.completion` (one layer below)" gives real-adapter behavior. The seal-contract tests use this pattern. New validation added at the adapter seam should follow suit if test coverage matters for that validation.

This issue surfaces a broader question about cross-layer testing for the adapter seam — but the answer is "use the existing seal-contract test pattern", not "rebuild test infrastructure."

### Files changed in this pass

| File | Change |
|------|--------|
| `src/pflow/core/llm_reasoning_map.py` | Added `thinking_level` branch to `effort="none"` mapping |
| `src/pflow/registry/smart_filter.py` | Routed reasoning kwargs through canonical channel; deleted Gemini substring heuristics; removed unused `Any` import |
| `src/pflow/core/exceptions.py` | Added `provider_message` field on `LLMCallError`; threaded through 4 subclass `__init__` overrides; updated base `diagnostic_context()` to surface it honestly; class docstring updated |
| `src/pflow/core/llm_client.py` | `_classify_litellm_error` passes `provider_message=str(exc)` to every classification branch |
| `src/pflow/core/CLAUDE.md` | Updated typed-exception table to document `provider_message` as a structured discriminator |
| `tests/test_core/test_llm_reasoning_map.py` | Added `test_disable_gemini_3` |
| `tests/test_registry/test_smart_filter.py` | Renamed `TestGeminiThinkingHeuristics` → `TestSmartFilterMinimizesReasoning`; assertions moved to `reasoning_kwargs`; `model_options is None` regression guards added |
| `tests/test_core/test_llm_client.py` | Test fixtures now pass `provider_message=` explicitly; new `test_provider_message_carries_raw_text_when_set`, `test_provider_message_is_none_when_not_set`, `test_seam_threads_provider_message_to_every_classification` (parametrized over all seal cases); unknown-future-subclass test asserts on `provider_message` |
| `tests/test_nodes/test_llm/test_llm.py` | `LLMTransientError` retry-exhaustion test fixture passes `provider_message=`; `InvalidRequestError` test fixture passes `provider_message=` |
| `tests/test_execution/test_executor_service_llm.py` | All three parametrized error fixtures now pass realistic provider text via `provider_message=` (e.g. "Quota exceeded for free tier", "model retired on 2026-01-01", "Property 'foo' is required but missing") and assert it appears in the runtime diagnostic context |

### Verification

```bash
uv run pytest -n 4 -q     # 5379 passed, 9 skipped (was 5361 before this pass)
make check                # ruff, ruff-format, mypy, deptry — all green
```

End-to-end smoke (real production code path through `complete()`, mocking only `litellm.completion`):

- `litellm.AuthenticationError("Quota exceeded for free tier; upgrade at https://billing.example/")` →
  - `Diagnostic.message` = `"API key required for model 'openai/gpt-4o-mini'"` (pflow framing, the WHAT)
  - `context.provider_message` = `"litellm.AuthenticationError: Quota exceeded for free tier; upgrade at https://billing.example/"` (raw, the WHY)
- `litellm.NotFoundError("Model claude-2.1 was retired on 2026-01-01 — use claude-sonnet-4.5 instead")` →
  - `Diagnostic.message` = `"Unknown model: anthropic/claude-2.1"` (pflow framing)
  - `context.provider_message` = `"litellm.NotFoundError: Model claude-2.1 was retired on 2026-01-01 — use claude-sonnet-4.5 instead"` (raw)

Architectural seal: `grep -rn 'litellm\.exceptions' src/pflow/` returns 2 hits in `core/llm_client.py` only. No consumer outside the adapter imports it. Same for `openai`.

### What the next agent should know

1. **The `provider_message` field is the single source of truth for raw upstream text.** Don't reconstruct it from `str(self)` — that's the wrapped form. Don't substring-match into it from consumer code; if you need a finer discriminator, add a typed `kind`/`reason` enum on the relevant subclass and detect it at the seam.

2. **Smart_filter's reasoning channel is canonical now.** Future internal callers wanting "minimum reasoning" should call `map_reasoning_options(model, "none", None, None)` and pass the result via `reasoning_kwargs`, NOT via `model_options`. The `_validate_model_options` invariant rejects reasoning keys in `model_options` and that's intentional — it prevents two reasoning paths from drifting.

3. **The autouse-mock testing pattern has a blind spot for adapter-seam validation.** When adding validation inside `complete()`, also add a seal-contract-style test that patches `litellm.completion` (one layer below `complete()`) so the real validation runs. The seal-contract test class in `test_llm_client.py` is the template.

4. **Three review findings ago I claimed "FULLY happy"; ended up not.** Each "are you happy?" prompt from the user surfaced a real loose end. The pattern: claiming-done is a useful forcing function, but the next prompt always finds something. Build the habit of asking it twice before claiming done.

### High-value test added (the only one worth the cost)

Considered two end-to-end tests after thinking about which bug classes still aren't pinned:

**Added** — `tests/test_execution/test_executor_service_llm.py::test_real_litellm_exception_provider_message_reaches_runner_diagnostics`. Patches `litellm.completion` (one layer below the autouse mock) to raise a real `litellm.exceptions.AuthenticationError("Quota exceeded for free tier...")`. Restores the real `pflow.core.llm_client.complete` for LLMNode's binding so the actual `_classify_litellm_error` runs. Asserts the raw provider text appears end-to-end in `result.errors[0].context["provider_message"]`. Pins the full pipeline:

```
real LiteLLM exception
  -> _classify_litellm_error (sets provider_message=str(exc))
  -> typed pflow exception raised
  -> LLMNode._call_llm catch
  -> _error_dict_from_exception (preserves diagnostic.context)
  -> _propagate_error_to_shared (writes _diagnostic_context to shared)
  -> mark_node_failed (archives to __failures__)
  -> executor_service._enrich_error_from_node_output (lifts to runtime Diagnostic)
  -> ExecutionResult.errors[i].context
```

Existing seal-contract tests cover the seam-side. Existing `test_llm_call_error_context_reaches_runner_diagnostics` covers the runner-side with hand-constructed exceptions. The middle (4-5 layers of error-dict conversion + shared-store propagation + failure archiving + diagnostic enrichment) was uncovered against a *real* upstream exception. A regression dropping `provider_message` in any of those layers would now fail this test loudly.

**Considered but dropped** — smart_filter under real `_validate_model_options`. Investigation showed the regression I'd want to catch (smart_filter forwarding reasoning keys via `model_options` again) is already pinned by `assert last_call["model_options"] is None` in `TestSmartFilterMinimizesReasoning` parametrized cases. Bypassing the autouse mock in this test path is genuinely tricky (the test-file-collection-time `from pflow.core.llm_client import complete` captures whatever the binding is at that moment, which may be the mock if any prior test ran). The autouse-mock-bypass complexity wasn't worth the marginal coverage. Filed as GH #355 instead — the recurring "autouse-mock-bypass blind spot" pattern deserves codification, not a one-off test.

### Follow-up GH issues filed at the end of this session

After thinking about which review findings warrant tracking beyond this branch:

- **#353** — Typed sub-discriminators for `MissingApiKeyError` sub-cases (quota_exceeded / account_suspended / region_restricted / etc.). Today's `kind="missing_key"` collapses real distinct failure modes that need different remediations. The `provider_message` field exposes the raw text but agents would have to substring-match it — the structural pattern is typed discriminators detected at the seam.
- **#354** — Enrich LLM diagnostic suggestions from `provider_message` text. Lighter-touch UX improvement: when `provider_message` contains stable patterns (`"retired"`, `"context length"`, `"content policy"`), append targeted suggestions. Complementary to #353, not alternative.
- **#355** — Codify the autouse-mock-bypass test pattern in `tests/CLAUDE.md`. Two regressions in this branch (smart_filter validation, trace_hook thread-id mismatch) shipped past tests because the autouse mock at `pflow.core.llm_client.complete` bypassed real validation. The seal-contract tests in `test_llm_client.py` are the existing template; documenting the pattern prevents the next regression as the seam grows.
- **Comment on #348** — `llm_providers.py` substantially closes the duplication-elimination half of #348. The remaining "extend to OpenRouter / Bedrock / Azure / Vertex / Mistral / Cohere" half is gated on actual user demand. Recommended re-scoping to "add providers as needed" rather than closing entirely.

---

## 41. Session 2026-04-26 (cont.) — Independent verification pass + `inject_settings_env_vars` audit fix

Adversarial end-to-end verification pass against the full branch. Built a battery of `.pflow.md` workflows exercising real-API paths (Anthropic, Gemini, OpenAI; ~$0.0001 spend), JSON output, sub-workflows, parallel batch, and every typed exception path. Every documented design intent verified live: bare-name auto-prefix (workflow + adapter both layers), `event["llm_prompt"]` populates in trace JSON (the §31 critical fix), `cost_usd` from LiteLLM rolls up correctly, `category="llm_failure"` + `error_class` + `provider_message` reach JSON output, `_validate_model_options` rejects reasoning-key bypass attempts, sub-workflow LLM cost rollup, parallel batch per-item prompt capture (§33 B11), `pflow probe llm` with all 9 stable usage keys.

**One real bug surfaced**: `pflow find` and `pflow mcp find` were missing `inject_settings_env_vars()`. The §38 audit caught this for `probe.py` but didn't sweep other LLM-using commands. Users who stored API keys via `pflow settings set-env` (the recommended migration path per §30) couldn't use `pflow find` even though `pflow run` worked for the same env. Failure mode is louder than usual: `pflow find` is the FIRST command the help text recommends ("First Action: Check for existing workflows before building: `pflow find ...`"). `pflow find` returns exit 0 on this failure (deliberate fallback-to-alternatives design), so error monitoring wouldn't catch it either.

**Fix**: 4 lines across 2 files matching the probe.py pattern.

- `src/pflow/cli/commands/find.py` — `inject_settings_env_vars` import + call before `find_workflow`.
- `src/pflow/cli/commands/mcp.py::find_tools` — same before `find_components`.

Repro before fix:
```bash
env -i HOME="$HOME" PATH="$PATH" pflow find "github"
# Error: API Key Missing or Insufficient
# (same env: pflow workflow.pflow.md works because run.py injects)
```

After fix: same command succeeds (settings inject as designed).

**Verification**: `make test` 5380 passed, `make check` clean, 249 targeted find/probe/mcp tests green. Repro now passes.

**Pattern worth keeping**: the audit-and-fix loop missed `find.py` because §38 was looking specifically at `probe.py`'s key-resolution failure. When a CLI command joins the LLM path (current consumers: `run.py`, `probe.py`, `find.py`, `mcp.py::find_tools`), it must call `inject_settings_env_vars()` before invoking the adapter. Pre-existing `cli/CLAUDE.md` line claims "Injected into `os.environ` at CLI startup (`_inject_settings_env_vars` in `commands/run.py`)" — that's misleading; injection is per-command. Architecturally cleaner option (hoist to the `cli` group callback) is a follow-up — out of scope for this fix.

---

## End of Task 158 implementation log

This branch is feature-complete and verified end-to-end. Phase A migration plus six review-driven follow-up commits plus end-to-end verification plus the §41 verification-driven `inject_settings_env_vars` fix = the contents of this branch. Open follow-up GH issues #347–#352 (filed during Phase A reviews) and #353–#355 (filed at end of session §40) capture deferred review findings that don't block merge.

**For the prompt-caching feature work (Phase B–G) that this migration enables:** see Task 159 (`.taskmaster/tasks/task_159/`). The original Task 158 spec and design discussion are preserved in Task 159 (sections §1–§25 of `task_159/implementation/progress-log.md`); the migration was extracted into this task once Phase A's scope crystallized into something architecturally significant on its own.

The next concrete deliverable for Task 159 is the Phase B–G implementation plan, written informed by the LiteLLM behavior observed during Task 158's implementation and verified during §27's spike + §38's end-to-end verification.
