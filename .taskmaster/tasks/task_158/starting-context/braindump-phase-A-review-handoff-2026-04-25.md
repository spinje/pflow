# Braindump: Task 158 — Phase A review handoff (2026-04-25)

**Read first (in this order):**
1. `.taskmaster/tasks/task_158/task-158.md` — the spec (what + why)
2. `.taskmaster/tasks/task_158/implementation/implementation-plan.md` — the Phase 0+A plan (the contract this implementation followed)
3. `.taskmaster/tasks/task_158/implementation/progress-log.md` — design history + per-step implementation notes. **Sections 27, 28, 29, 30 are the substantive Phase A coverage** (Phase 0 outcomes, A.1-A.5, A.6-A.8, A.9-A.12+cleanup). Earlier sections are design discussion.
4. `.taskmaster/tasks/task_158/starting-context/braindump-design-complete.md` — design tacit knowledge from before implementation started; still mostly accurate. Useful for understanding *why* certain things were designed the way they were.
5. `.taskmaster/tasks/task_158/starting-context/braindump-phase-0-and-A-handoff-2026-04-24.md` — pre-implementation handoff. Has the user's load-bearing principles and Phase 0 spike scope.
6. **This document** — your specific brief.

**Total reading: ~3.5k lines.** Don't skip — design rationale matters for review judgment.

---

## Your role

**Phase A is feature-complete on branch `feat/prompt-caching-lite-llm`.** Your job is to review the implementation before it merges to `main`. The user values 20 turns over a wrong design — be thorough, surface concerns directly, don't paper over.

You are NOT implementing anything. You are NOT writing the Phases B-G plan (that comes after Phase A merges). You are reviewing what's been built.

---

## What "Phase A" is and is not

**Phase A is a library migration with zero new user-facing features.** Replaces Simon Willison's `llm` library with a pflow-owned adapter wrapping LiteLLM. Every existing workflow runs identically. The only observable differences:

- `pyproject.toml` lists `litellm==1.82.6` instead of `llm`/`llm-anthropic`/`llm-gemini`
- API keys must be set via `pflow settings set-env` or shell env vars (the `llm keys set ...` subprocess path is gone)
- Cost reporting (`cost_usd` in traces) comes from LiteLLM's pricing data instead of pflow's `MODEL_PRICING` table

**Phase A does NOT include any of the prompt-caching features.** No `## Cache` block parsing, no `prompt_cache:` field, no `cache_control` markers, no `analyze-cache` command. Those land in Phases B-G after this PR merges.

**Branch summary** (10 commits since `8349df88`):
```
8349df88 ready for phase 0 + a    ← baseline
7babf9e5 A.1: install LiteLLM
0a2eb798 A.2 + A.3: reasoning_map + adapter
a38afa6d A.4 + A.5: mock + LLMNode rewire
40b74f8e A.6 + A.7 + A.8: tracing + discovery + cleanup
5d0e0a9b A.9: drop llm CLI subprocess paths
8247ae2a A.10: delete llm_pricing.py
4becef96 A.11: drop llm/llm-anthropic/llm-gemini deps
6222697f A.12: docs pass + CHANGELOG
ac257fc6 end-of-task cleanup     ← current HEAD
```

---

## Quick verification commands (run these first)

```bash
# Sacred parity test — must be green
uv run pytest tests/test_execution/test_plan_drift.py -q

# Full suite — should be 5266 passed, 0 skipped, 0 failed
make test

# Lint, type, deps — all green
make check

# Confirm no llm-library imports remain anywhere
grep -rn 'import llm$\|from llm import' src/pflow/ tests/

# Confirm only litellm is installed (no llm trio)
uv pip list | grep -iE '^(llm|llm-)'

# Manual spot-check: settings CLI output is sensible
uv run pflow settings llm show
uv run pflow settings --help
```

If any of these fails or shows unexpected output, that's where you start digging.

---

## High-leverage review angles (where bugs and design questions hide)

These are the places I, the implementing agent, would scrutinize hardest. Listed in roughly descending order of risk.

### 1. The `MockLLMClient` cost contract (the user-flagged design choice)

**Where:** `tests/shared/llm_mock.py::MockLLMClient`

**The story:** The user explicitly pushed back on my initial framing of the cost-mock decision and asked "what's the right solution that the top 10% of codebases similar to this one would implement, have we considered it yet?" The result was option (c): default `cost_usd: None`, tests that care set it explicitly via `set_response(..., cost_usd=...)`.

**What to scrutinize:**
- Does `_get_cost()` resolution mirror `get_response()` resolution exactly? (exact match → wildcard → default → None) — both are model:schema-keyed. Easy place for asymmetry to hide.
- Are there any tests that *should* set `cost_usd` but don't? Look for tests that previously expected non-zero costs but were changed to drop the assertion or pin to a specific value. Did I miss one that should genuinely have been kept?
- The contract: tests now SOMETIMES inject explicit `cost_usd`, sometimes don't. Is this discoverable for future test authors? Should there be a docstring example or a single canonical test demonstrating the pattern?

**Where I worry:** if a future test author writes a workflow-discovery test and asserts on cost, they'll get None instead of computed-from-tokens — and may not understand why. The `_DEFAULT_RESPONSES` table doesn't carry costs.

### 2. The `enrich_llm_usage_with_cost` location

**Where:** `src/pflow/core/llm_client.py` (the function, ~10 lines at the bottom)

**The decision:** I put the wrapper in `llm_client.py` rather than `metrics.py` or a new file. Rationale: it documents the cost contract next to the adapter that establishes it. Counter-argument: it's used by `metrics.py`, `nodes/llm/llm.py`, `runtime/engine/instrumentation.py`, `runtime/engine/batch_executor.py` — most of those are runtime, not adapter code. Could argue it belongs in `metrics.py` or a new `cost_utils.py`.

**What to scrutinize:** does the location obscure that this function preserves the Claude Code SDK fallback (`total_cost_usd` mirroring)? The Claude Code path doesn't go through `llm_client.py` at all — it runs through `nodes/claude/claude_code.py:865-887`. A reviewer might reasonably ask "why is this function in `llm_client.py` if it's also used by Claude Code?"

### 3. The Pattern Exception handling

**Where:** `src/pflow/core/llm_client.py::complete()` (~lines 311-334), `src/pflow/nodes/llm/llm.py::_call_llm` (handles `adapter_response.status == "error"`)

**The story:** Pre-Phase-A had a `try/except ValidationError` block at `nodes/llm/llm.py:298-311` labeled "PATTERN EXCEPTION" — local catch-and-return for deterministic errors so the Node retry loop wouldn't burn 3 attempts. The catch was tied to the `llm` library's Pydantic Options validation. Under LiteLLM the equivalent is `BadRequestError`.

The implementation moved this catch INTO the adapter (catches `BadRequestError`, returns an error-marked `AdapterResponse` with `status="error"`). LLMNode unpacks the error and constructs the same error dict shape as before. The Node retry loop never sees the exception, so no wasted retries.

**What to scrutinize:**
- The PATTERN EXCEPTION still exists, just in a different place. Is the new location obvious to a future reader? The adapter's `complete()` docstring explains it (lines 252-264) — is that enough?
- Are there other LiteLLM exception types that should also be deterministic? E.g., `litellm.exceptions.UnsupportedParamsError`? Currently only `BadRequestError` is caught. The plan mentioned this might need expansion.
- LiteLLM's `BadRequestError` might fire for transient issues we'd want to retry (rare, but possible — e.g., a 400 from a flaky proxy). The PATTERN EXCEPTION assumes BadRequestError = deterministic. Verify by checking LiteLLM's error class docs.

### 4. The tracing redesign (A.6 + post-A.6 rename)

**Where:** `src/pflow/runtime/workflow_trace.py::WorkflowTraceCollector`, specifically `register_for_llm_call` / `unregister_from_llm_call` / `get_trace_hook`

**The story:** A.6 collapsed the prior global `llm.get_model` / `model.prompt` monkey-patch (with reference-counted lazy install/teardown) into a thin per-thread registration step. The end-of-task cleanup renamed `setup_llm_interception` → `register_for_llm_call` and `cleanup_llm_interception` → `unregister_from_llm_call` because the "interception" name no longer described what the methods do.

**What to scrutinize:**
- The class-level state (`_active_collectors`, `_thread_local`, `_llm_lock`, `_llm_interceptor_installed`, `enable_llm_interception` flag) is a tangled set of names. Could be clearer. Worth a refactor pass?
- The `enable_llm_interception=False` for sub-workflow collectors is the inheritance mechanism. Is this still correct post-A.6? (Run nested-workflow tests with `--verbose` to check the trace JSON has the right `llm_prompt` placement.)
- The `_active_trace_hook()` function in `nodes/llm/llm.py:372` is the consumer. It reads the thread-local registry and asks the active collector for its hook. Concurrency: if two LLMNodes run on the same thread (sequentially), they re-register and the second overwrites the first — that's fine. If they run on different threads (parallel batch), each thread has its own registration — that's also fine. But: are there code paths where the LLMNode runs on a thread that DIDN'T register? E.g., if a code node spawns a thread that calls into the adapter?

**Sacred test:** `tests/test_execution/test_plan_drift.py` (32 tests). Green throughout Phase A. Run after any change you make during review.

### 5. The pinned `litellm==1.82.6`

**Where:** `pyproject.toml:33`

**The story:** Phase 0 spike pinned `1.83.7` (Phase 0 outcome). A.1 had to downgrade to `1.82.6` because every release in the `1.83.x` series hard-pins `click==8.1.8`, which broke 3 `CliRunner`-based tests that depend on click 8.2+'s default stderr separation.

**What to scrutinize:**
- Confirm the Gemini PR #15226 fix (closed 2025-10-07) is present in 1.82.6. Phase 0 verified this for 1.83.7 — did the regression test get re-run on 1.82.6? Spot-check via:
  ```python
  import litellm
  print(litellm.__version__)  # should be 1.82.6
  # Check changelog or release notes
  ```
- The 3 `CliRunner` stderr tests (`test_workflow_data_goes_to_stdout_not_stderr_gh194`, `test_shell_stderr_in_json_output`, `test_multiple_stdin_error_json_output`) — verify they pass under 1.82.6.
- Future maintenance: when does it become safe to bump? When click 8.3+ becomes the LiteLLM minimum. May need to track upstream.

### 6. The intentional retentions in A.12

**Where:** `src/pflow/core/llm_reasoning_map.py:4` (docstring), `docs/changelog.mdx:907` (historical entry)

**The story:** Both reference Simon Willison's `llm` library. The `llm_reasoning_map.py` reference is in the module docstring explaining *why* the file exists (LiteLLM doesn't replicate the `llm` library's `Options` introspection contract). The changelog reference is historical — describing what was true at a past release.

**What to scrutinize:**
- Is the design rationale in `llm_reasoning_map.py:4` sufficient context for a future agent who's never used Simon's library? Or does it need a "for historical context, this used to..." prefix?
- The changelog historical entry — is this actually safe to leave, or does it confuse users reading top-to-bottom?

### 7. The Gemini-3 reasoning-model silent empty-response

**Where:** Production path, surfaced during smoke testing (progress log §30)

**The story:** Smoke test on `gemini-3-flash-preview` with `max_tokens: 16` returned `result.result == ""` because all 13 tokens went to internal reasoning before any visible text could be emitted. `finish_reason: length`, `text_tokens: 0`, `reasoning_tokens: 13`. The adapter normalized `content: None` to `""` and pflow surfaced it with no warning.

**This is NOT a Phase A regression** — pre-Phase-A behavior was identical. But it's a real UX issue we now have visibility into.

**What to scrutinize:**
- Should the adapter detect `text_tokens: 0` + `reasoning_tokens > 0` + `finish_reason: length` and emit a warning? Worth a follow-up issue.
- Are there other reasoning-model edge cases the adapter should detect? `finish_reason: content_filter`? Truncated structured output?

### 8. The CHANGELOG entry's `description="Unreleased"`

**Where:** `docs/changelog.mdx` top entry

**The story:** Existing changelog entries all have version numbers. Phase A by itself doesn't ship a version — Phases B-G are coming. I labeled it "Unreleased" as a placeholder. User to decide whether (a) Phase A merges with its own version bump, (b) the entry stays "Unreleased" until Phase G ships, or (c) something else.

**Ask the user.** This is a process decision, not a technical one.

### 9. The memo cache transient regression

**Where:** `runtime/engine/instrumentation.py::compute_node_config` and `MemoizationCache`

**The story:** Pre-A.10, an old cached `llm_usage` dict without `cost_usd` got cost computed from `MODEL_PRICING` when read. Post-A.10, the same dict gets `cost_usd: None`. So `pflow --dry-run` against a workflow that hits cached nodes will show `cost_basis: upper_bound` and `estimated_cost_usd: null` for entries written before the upgrade — until the cache's 24h TTL flushes them.

**What to scrutinize:**
- Self-healing within 24h. Acceptable degradation? User accepted this in conversation.
- Should the CHANGELOG entry mention this? Currently doesn't.

### 10. Pyproject's `DEP002 = ["PyYAML"]` ignore

**Where:** `pyproject.toml:188`

**The story:** PyYAML is loaded via lazy import in the markdown parser, so deptry can't detect it statically. This entry was there pre-Phase-A and is still needed — A.11 just trimmed the temp llm-trio entries off.

**What to scrutinize:** verify by `grep -rn 'import yaml\|from yaml' src/pflow/`. If it's a regular module-level import somewhere, the ignore is wrong.

---

## Process the user cares about

From the design braindumps and observed behavior across this work:

1. **Honesty over defensiveness.** When you're uncertain, say so. Don't rationalize after the fact. The user has explicitly called this out as a load-bearing preference (see auto-memory `feedback_honesty_over_defensiveness.md`).

2. **20 turns > wrong design.** The user prefers a slow, well-discussed answer over a fast wrong one. If a review concern is real, raise it — even if it costs implementation time.

3. **Discuss before implementing.** Don't suggest changes during review and immediately implement them. Surface findings, recommend, get approval, then execute (auto-memory `feedback_discuss_before_implement.md`).

4. **No commit/push without explicit permission** (auto-memory `feedback_commit_push_permission.md`).

5. **Top-10% codebase aesthetics.** Boring, obvious code. No premature abstractions. Production code should be readable by a tired engineer at 3am.

6. **Test bloat is real waste** — high-value tests, mutation-test regression guards, causal streaming tests. Tests that test the wrong thing are worse than no tests (auto-memory `feedback_quality_gates.md`).

---

## What to verify yourself (concrete review checklist)

### Code review (the changes)

- [ ] `src/pflow/core/llm_client.py` — adapter contract clean, error handling matches the design
- [ ] `src/pflow/core/llm_reasoning_map.py` — Anthropic Opus 4.5 thinking_effort precedence preserved (search for explicit test in `tests/test_core/test_llm_reasoning_map.py`)
- [ ] `src/pflow/core/llm_config.py` — env-only key resolution, no subprocess paths, `inject_settings_env_vars` UNCHANGED
- [ ] `src/pflow/nodes/llm/llm.py` — `_call_llm` uses `complete(...)`, error-marked response handled, `post()` simplified to single dict path
- [ ] `src/pflow/runtime/workflow_trace.py` — renamed methods correct, `_active_collectors` registry intact
- [ ] `src/pflow/runtime/engine/instrumentation.py` — `register_for_llm_call(...)` wrapper does the right detection
- [ ] `src/pflow/execution/runner.py` — `unregister_from_llm_call` cleanup correct
- [ ] `src/pflow/registry/discovery.py`, `src/pflow/registry/smart_filter.py`, `src/pflow/core/workflow/discovery.py` — all 3 use the adapter, all pass `Class.model_json_schema()` for schema

### Test review

- [ ] `tests/shared/llm_mock.py` — `MockLLMClient` clean, no leftover references to deleted classes
- [ ] `tests/conftest.py` — `mock_llm_client` autouse fixture only (no `mock_llm_calls`)
- [ ] `tests/test_core/test_llm_reasoning_map.py` — 60 tests covering all reasoning kwarg paths, Opus 4.5 precedence
- [ ] `tests/test_core/test_llm_client.py` — adapter unit tests cover text-only, system, schema, attachments, reasoning, errors, trace_hook
- [ ] `tests/test_nodes/test_llm/test_llm.py` — LLMNode tests use the new mock; reshape from old `Mock()` to `MockLLMClient.call_history`
- [ ] `tests/test_execution/test_plan_drift.py` — 32 tests, including `test_plan_cost_nested_rollup` with the explicit cost injection

### Documentation review

- [ ] `docs/quickstart.mdx` — env-var path, no `llm keys set` references
- [ ] `docs/reference/nodes/llm.mdx` — LiteLLM intro, OpenRouter/Ollama as native (no plugin install)
- [ ] `docs/reference/cli/settings.mdx` — model resolution chain has 4 tiers (was 5 with the dead llm-CLI step)
- [ ] `docs/changelog.mdx` — top entry is the migration; existing entries untouched
- [ ] `src/pflow/nodes/llm/README.md` — installation section rewritten end-to-end
- [ ] `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` and `mcp-sandbox-agent-instructions.md` — `For LLM providers` blocks updated, cheatsheet updated
- [ ] `src/pflow/core/CLAUDE.md` — `llm_client.py` section replaces `llm_pricing.py` section

### Smoke test

- [ ] Real-API call against any provider you have a key for. Cheapest is `gemini/gemini-3-flash-preview` at ~$0.0005/call. Use `reasoning_effort: minimal` and `max_tokens: 1024+` to avoid the reasoning-model trap from §7. Verify the trace JSON has `llm_call`, `llm_prompt`, `llm_response`, and `cost_usd` populated correctly.

---

## What I'm NOT confident about (admitted weak reasoning)

1. **The cost-mock contract change is "right" but might trip future test authors.** The discoverability concern in §1 is real. I don't have a great answer.

2. **The `enrich_llm_usage_with_cost` location in `llm_client.py` is defensible but not obviously right.** I argued for it from the "documents the contract" angle. A reviewer could argue equally well for putting it in `metrics.py` or a new `cost_utils.py`.

3. **The renamed methods (`register_for_llm_call` / `unregister_from_llm_call`) are clearer but I could be wrong.** Bikeshed risk. If you (the reviewer) think the rename was unnecessary or the new names are worse, that's worth surfacing.

4. **The Pattern Exception scope.** I caught `BadRequestError` only. Other LiteLLM exception types might also be deterministic-on-retry. Phase 0 didn't explicitly verify the full exception taxonomy.

5. **The smoke test was minimal.** Single LLM call, no batch, no nested workflows, no structured output, no attachments. Phase A's adapter handles all of those, but only the unit-test paths verified them. A real-API multi-feature workflow would catch composition bugs the unit tests miss.

---

## Things deferred to later phases (NOT review concerns)

These are explicitly out of Phase A scope per the spec:

- `## Cache` block parsing and rendering
- `prompt_cache:` and `prewarm:` per-node fields
- `cache_control` markers on system messages
- Auto batch-prefix caching
- Trace format 2.1.0 (new `cache_key`, `cache_source`, `cache_age_sec` fields)
- `pflow analyze-cache` command
- MCP `analyze_cache` tool
- `--dry-run` cache nudge
- `compute_node_config` conditional `prompt_cache` inclusion
- `NodeConfig` field additions (`prompt_cache_items`, `prewarm`)
- Direct read of `~/.config/io.datasette.llm/keys.json` (deferred to v1.x)
- Per-TTL cache-write pricing (deferred until 1h TTL feature lands)
- ClaudeCodeNode caching (out of scope per spec)
- Opus 4.5 cache+thinking behavior verification (Phase 0 finding, deferred to Phase C)

If you find yourself reviewing one of these and finding it missing, that's expected — it's not Phase A's job.

---

## After your review

If you find blockers, surface them. The user will decide what to fix and what to defer.

If review passes:
1. User decides on the CHANGELOG label/version (see §8 above).
2. User opens PR.
3. Optional: one cheap real-API smoke test before merge (~$0.0005 against Gemini).
4. After merge, the next work is `implementation/plan-phase-B-through-G.md` — but that's a fresh task.

---

## Final notes

- **Don't commit anything during review** without explicit permission. Keep findings local in this conversation.
- **Don't run `pflow lyrics-generator` or any user-project workflow** — that's their money and their files.
- **Don't try to bump LiteLLM** — see §5 for why we're pinned at 1.82.6.
- **Don't touch the spike scripts in `scratchpads/task-158-spike/`** — they're useful as runnable docs of Phase 0 findings; not committed.

The user is comfortable with iteration. If anything in this implementation surprises you, raise it — even if it's small.

> **Summary for the next agent:** Phase A is feature-complete on `feat/prompt-caching-lite-llm`. 5266 tests pass, 32 sacred plan-drift tests green, lint clean, real-API smoke test verified end-to-end on Gemini. Your job is to review before merge. The 10 review angles above are where I'd scrutinize hardest.
