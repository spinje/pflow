# Braindump: Task 158 — Phase A.9–A.12 handoff (2026-04-24)

**Read first (in this order):**
1. `.taskmaster/tasks/task_158/task-158.md` — the spec
2. `.taskmaster/tasks/task_158/implementation/implementation-plan.md` — the Phase 0+A plan (your contract for what to build)
3. `.taskmaster/tasks/task_158/implementation/progress-log.md` — the design history. **Sections 27-29 are the most relevant** — they cover Phase 0 outcomes, Phase A.1-A.5, and Phase A.6-A.8 respectively.
4. `.taskmaster/tasks/task_158/starting-context/braindump-design-complete.md` — design tacit knowledge (still 90% accurate)
5. `.taskmaster/tasks/task_158/starting-context/braindump-phase-0-and-A-handoff-2026-04-24.md` — pre-Phase-A handoff (still useful for context on the design pivots and user-principle phrases)
6. **This document** — the most recent handoff, Phase A.9-A.12 specific

**~3.5k lines of reading.** Don't skip. The implementation choices made in A.1-A.8 are dense and the cleanup steps depend on understanding why they were made.

---

## Where I Am (state of the world at handoff)

**Branch**: `feat/prompt-caching-lite-llm` in worktree `/Users/andfal/projects/pflow-feat-prompt-caching-lite-llm`.

**Commits on branch since `main`** (oldest → newest):
- `b8593c94` — `ready for imp a` (pre-A.1 baseline)
- `7babf9e5` — A.1: install LiteLLM 1.82.6
- `0a2eb798` — A.2+A.3: `llm_reasoning_map.py` + `llm_client.py` adapter
- `a38afa6d` — A.4+A.5: MockLLMClient, fixture, LLMNode rewire
- `40b74f8e` — A.6+A.7+A.8: tracing redesign, 3 discovery callsites, mock cleanup

**Verification at handoff:**
- `make test` → 5303 passed, 10 skipped, 0 failed
- `tests/test_execution/test_plan_drift.py` → 32 passed (sacred parity invariant intact)
- `make check` → ruff / ruff-format / mypy / deptry all green

**Production state:**
- All LLM calls flow through `pflow.core.llm_client.complete(...)` → `litellm.completion(...)`
- Zero `llm.get_model` references in production code (the `runtime/workflow_trace.py` mention is a docstring)
- Zero `from llm import` / `import llm` in production
- `MockLLMClient` is the sole autouse LLM mock in tests
- Tracing flows via `trace_hook` parameter on the adapter; the global monkey-patch is gone
- LLMNode's behavior is identical to pre-Phase A from the user's perspective (response shape, error messages, retry semantics)

**Pending steps:**
- A.9 — `llm_config.py` and `settings.py` cleanup
- A.10 — Delete `llm_pricing.py` (Outcome A from Phase 0)
- A.11 — Remove `llm` / `llm-anthropic` / `llm-gemini` from `pyproject.toml`
- A.12 — Documentation pass + CHANGELOG note

---

## The Single Real Decision Left in Phase A — A.10 mock_cost

This is the only step in A.9–A.12 with a real architectural question. **Stop and ask the user before implementing.** They explicitly value 20 turns over a wrong design.

### The setup

`tests/shared/llm_mock.py::MockLLMClient.complete(...)` currently OMITS `cost_usd` from the `usage` dict it returns. Reason (from progress-log §28):

> NOTE: cost_usd is intentionally NOT populated. The real adapter reads it from LiteLLM's `_hidden_params["response_cost"]`, which we can't reasonably mock. Letting it stay absent means `enrich_llm_usage_with_cost` computes a real cost from the MODEL_PRICING table — which is what existing tests rely on for historical-cost propagation through the memo cache.

The "computes a real cost from MODEL_PRICING" step is in `core/llm_pricing.py::enrich_llm_usage_with_cost`. **A.10 deletes that module.** When it's gone, the fallback evaporates — tests that depend on `cost_usd > 0` from token math will fail.

### Concrete tests likely affected

Searched for `cost_usd > 0` and `total_cost_usd > 0` patterns. Hits to check:

```bash
grep -rn 'cost_usd.*>\|total_cost_usd.*>' tests/ --include='*.py'
```

Last time I ran this (during A.5), the load-bearing one was `tests/test_execution/test_plan_drift.py::test_plan_cost_nested_rollup` — it asserts that an LLM node's historical cost (from a prior cached run) is `> 0` after a workflow re-plan. That cost is read from the cached output blob; the cache stored what was in `llm_usage["cost_usd"]` at write time; that came from `enrich_llm_usage_with_cost` computing `gpt-4o-mini` × tokens.

Other likely consumers (verify with grep):
- `tests/test_integration/test_metrics_integration.py::test_llm_cost_calculation` — already migrated in A.5 to inject custom `AdapterResponse` with `usage` dicts. Currently relies on the same fallback. May need to start populating `cost_usd` directly in the injected response.
- `tests/test_integration/test_metrics_integration.py::test_cost_calculation_accuracy` — calls `MetricsCollector.calculate_costs()` directly. Doesn't go through the adapter; might still depend on `MODEL_PRICING` even after A.10 (depending on what `calculate_costs` does internally — check).

Estimate: 6-10 tests affected. Could be more.

### The two options

**Option (a) — Mock returns `cost_usd: 0.0`. Tests that need real cost inject custom `AdapterResponse`.**

Pro:
- Honest. Pricing is now LiteLLM's responsibility, not pflow's. Testing pricing math in pflow's suite is testing the wrong thing.
- Sets a clean contract: "if your test needs specific cost, build the response with the cost you want."
- Pattern already exists — A.5/A.8 migrations to `test_metrics_integration.py` already monkeypatch `pflow.nodes.llm.llm.complete` and return custom `AdapterResponse` instances.

Con:
- Requires touching 6-10 tests.
- Some tests may simply not need cost assertions anymore (drop the assertion outright).

**Option (b) — Mock returns a small fake cost** like `cost_usd: input_tokens * 1e-7 + output_tokens * 1e-6`.

Pro:
- Most existing tests just keep passing without change.
- Less mechanical work.

Con:
- It's a fiction. Nothing in production produces these numbers.
- Tests that pin specific cost values would still need updating.
- Future test authors will assume the mock cost reflects reality and write tests around fake numbers.

### My recommendation

**(a).** It's more work but it's the right contract. The existing pattern is already in place — `test_metrics_integration.py` shows it works.

But this is the user's call. **Ask them before implementing.**

---

## Per-Step Execution Notes

### A.9 — `llm_config.py` and `settings.py` cleanup

**Files to touch (per the plan):**
- `src/pflow/core/llm_config.py` — main work
- `src/pflow/cli/commands/settings.py` — help-text strings (3 sites the plan flagged: lines 411, 451, 555 — verify line numbers haven't drifted)
- `pyproject.toml` — drop the `S603` ignore for `llm_config.py` if no subprocesses remain
- `src/pflow/cli/commands/run.py:718` — verify `inject_settings_env_vars` call still works (should be unchanged)
- `src/pflow/mcp_server/main.py:40` — same

**In `llm_config.py`:**

DELETE:
- `_has_llm_key()` (~46 lines, ~53-99) — the `llm keys get` subprocess call.
- `get_llm_cli_default_model()` (~40 lines, ~348-387) — the `llm models default` subprocess call.
- `LLM_COMMAND` constant (line 23) — `["llm"]`.
- `_LLM_KEYS_SUBCOMMAND` constant (line 37) — `"keys"`.

UPDATE:
- `_has_provider_key()` (~102-149) — REMOVE the third source (`_has_llm_key()` fallback). Keep env var + pflow settings via `SettingsManager`.
- `_detect_default_model()` (~152-184) — REMOVE the test-env subprocess guard at lines 164-166 (`if os.environ.get("PYTEST_CURRENT_TEST")`). No subprocess to guard now.
- `get_llm_setup_help()` (~220-237) — REPLACE `llm keys set anthropic`/etc. text with environment-variable instructions. Suggested phrasing (verified `pflow settings env set` exists per Phase 0 finding):
  ```
  Set provider API keys via environment variables:
    export ANTHROPIC_API_KEY=...
    export OPENAI_API_KEY=...
    export GEMINI_API_KEY=...
  Or configure them in pflow settings:
    pflow settings env set ANTHROPIC_API_KEY <value>
  ```
- `get_model_not_configured_help()` (~433-465) — REPLACE `llm models default` / `llm models list` references with `pflow settings llm show`.

PRESERVE (do NOT touch):
- `inject_settings_env_vars()` (~250-286) — UNCHANGED. LiteLLM reads from `os.environ` natively, so this still works.
- `ALLOWED_PROVIDERS` (~26), `PROVIDER_ENV_VARS` (~30-34) — keep.
- `SettingsManager` integration — keep.

**In `cli/commands/settings.py`:**

- The `pflow settings llm` group docstring (~lines 39-41 per plan) — remove "via Simon Willison's llm tool" reference.
- Help text at lines 411, 451, 555 (verify) — remove all "llm CLI default" / "llm cli" phrasing.
- The plan flagged a "circularity" issue: don't say "use `pflow settings llm`" — the user is already there. Point at env vars + `pflow settings env set` for inline credential storage.

**In `pyproject.toml`:**

- Remove `"src/pflow/core/llm_config.py" = ["S603"]` from `[tool.ruff.lint.per-file-ignores]` IF no `subprocess` imports remain in `llm_config.py`. Verify with `grep -n subprocess src/pflow/core/llm_config.py`.

**Tests to update:**

```bash
grep -rln "_has_llm_key\|get_llm_cli_default_model\|LLM_COMMAND\|_LLM_KEYS_SUBCOMMAND" tests/
```

Likely affected (per the plan):
- `tests/test_core/` for `llm_config` — find via grep. May test the subprocess paths directly.
- Add a test confirming env-only key resolution works (the new contract).

**Verification:**
- `uv run pytest tests/test_core/ -k 'llm_config' -v`
- `uv run pflow settings llm show` — confirm output is sensible without referencing Simon's `llm` binary.
- `make check` — green.

---

### A.10 — Delete `llm_pricing.py` (Outcome A)

**The mock_cost decision (above) gates this step.** Resolve that first.

**Files to touch:**

DELETE:
- `src/pflow/core/llm_pricing.py` (~189 lines).

REWRITE:
- `enrich_llm_usage_with_cost(llm_usage)` — currently lives in `llm_pricing.py`. After deletion, it's gone. Two options for callers:
  - **(i)** Move the function to `pflow.core.llm_client` as a tiny wrapper. Body becomes:
    ```python
    def enrich_llm_usage_with_cost(llm_usage: dict) -> None:
        """No-op when cost_usd already set; checks Claude Code SDK total_cost_usd fallback."""
        if "cost_usd" in llm_usage:
            return  # adapter already populated it from response_cost
        if "total_cost_usd" in llm_usage and llm_usage["total_cost_usd"] is not None:
            llm_usage["cost_usd"] = llm_usage["total_cost_usd"]
        else:
            llm_usage["cost_usd"] = None
    ```
    The Claude Code SDK fallback is real — `nodes/claude/claude_code.py:865-887` reads `total_cost_usd` from the SDK and stores it. Without preserving the fallback, Claude Code cost reporting breaks.
  - **(ii)** Inline the logic at each callsite. Less DRY.
  - Recommend (i).

**Find and rewire all callsites of `from pflow.core.llm_pricing import ...`:**
```bash
grep -rn "from pflow.core.llm_pricing import\|pflow.core.llm_pricing" src/pflow/ tests/ --include='*.py'
```

Known callsites (verify):
- `src/pflow/nodes/llm/llm.py` — imports `enrich_llm_usage_with_cost`. Rewire to new location.
- `src/pflow/runtime/engine/instrumentation.py` — imports `enrich_llm_usage_with_cost`. Rewire.
- `src/pflow/runtime/engine/batch_executor.py` — likely same. Rewire.
- `src/pflow/core/metrics.py` — imports `calculate_llm_cost` (or similar). May need refactoring — pricing math is gone, so cost computation moves entirely to "read what's in `llm_usage['cost_usd']`".
- `src/pflow/core/__init__.py` — remove `calculate_llm_cost`, `enrich_llm_usage_with_cost`, `MODEL_PRICING`, `MODEL_ALIASES` exports. Verify which were exported.
- `src/pflow/nodes/claude/claude_code.py` — check whether it imports or just relies on `total_cost_usd` field-name convention.

**Tests:**

```bash
grep -rn "MODEL_PRICING\|calculate_llm_cost\|llm_pricing" tests/ --include='*.py'
```

Many tests likely import `MODEL_PRICING` for assertions. After A.10:
- Tests asserting on EXACT cost values (with hand-computed expectations) need rewriting per the mock_cost decision.
- Tests asserting structure (cost is a number, cost > 0, etc.) — depends on the mock decision.

**Documentation drift to fix:**
- `src/pflow/core/CLAUDE.md:198` — "46+ models" claim. Per the plan, the actual count is 41. After A.10, the right text is to remove the entire pricing section.
- The "🐛 Broken aliases" callout for `claude-3.5-haiku` and `claude-4-opus` — gone with the table.

**Verification:**
- `uv run pytest tests/ -k 'cost or pricing or llm_usage' -v` — all green.
- `make test` — full suite green.
- Smoke test against a real workflow with API keys (RUN_LLM_TESTS) — but per user instruction, those are skipped for now.
- `grep -rn 'MODEL_PRICING\|calculate_llm_cost' src/pflow/` — zero hits expected.

---

### A.11 — Remove old `llm` dependencies

**Files to touch:**

`pyproject.toml`:
- DELETE `"llm>=0.29",` (line 29 — verify number drift).
- DELETE `"llm-anthropic==0.25",` (line 30).
- DELETE `"llm-gemini>=0.30",` (line 36).
- UPDATE `DEP002 = ["llm", "llm-anthropic", "llm-gemini", "PyYAML"]` — remove the three llm entries; keep `PyYAML`.

`uv.lock`:
- Regenerate via `uv sync`.

**Verification:**
- `uv pip list | grep -E '^(llm|llm-)'` → no matches.
- `uv pip list | grep litellm` → present.
- `make check` → green (deptry should be happy).
- `uv run pytest -q -n auto` → 5303+ passed.
- Smoke test: any small workflow runs without import errors.

**Watch for:** if any code path lazily imports `llm` (e.g., inside a function), it'll fail at runtime. The grep `grep -rn 'import llm$\|from llm' src/pflow/` should return zero. The `runtime/workflow_trace.py` docstring mention is text only — `import llm` is gone from that file's body.

---

### A.12 — Documentation pass + CHANGELOG

**Files to touch:**

- `pflow guide` content — find any LLM node docs referencing `llm keys` / `llm models` setup; rewrite to env vars. Run `pflow guide` to audit.
- `src/pflow/core/CLAUDE.md` — already partially fixed in A.10 (pricing section). Also update `llm_config.py` section to remove subprocess mentions.
- `src/pflow/nodes/llm/CLAUDE.md` — update LLM library references; point at the adapter.
- Mintlify docs:
  ```bash
  grep -rn "llm keys\|llm models\|Simon Willison" docs/
  ```
  Probably hits in `docs/reference/cli/index.mdx` and any settings/setup pages.
- CHANGELOG (or wherever pflow tracks user-facing changes — check `releases/` directory). Migration note:
  ```
  v0.X — removed Simon Willison's `llm` library dependency. pflow now uses
  LiteLLM directly for provider connectivity. API keys must be set via
  environment variables (ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY)
  or configured via `pflow settings env set <KEY_NAME> <value>`. Existing keys
  stored via `llm keys set ...` will not be picked up automatically — transfer
  them to env vars or pflow settings manually. Direct read of legacy
  keys.json is planned for a future release.
  ```

**Verification:**
- `grep -rn "llm keys\|llm models" src/pflow/ docs/ .taskmaster/` → only historical hits in `.taskmaster/tasks/task_95/` (the task that originally introduced the llm library) and progress-log historical sections. Anything in current production code/docs is a regression.

---

## Deletion Checklist (defer until end of Phase A — user explicitly asked for these to NOT be deleted during steps)

Items pending user-approved deletion. Confirm with user before deleting:

1. **`tests/test_nodes/test_llm/test_llm_reasoning.py`** (entire file) — pytest.skip'd at module level. Coverage migrated to `tests/test_core/test_llm_reasoning_map.py` + new `TestReasoningEffortValidation` / `TestReasoningKwargsForwarded` classes in `tests/test_nodes/test_llm/test_llm.py`. Body retained for user review.

2. **`MockLLMModel`, `MockGetModel`, `create_mock_get_model`** in `tests/shared/llm_mock.py` — unreferenced after A.8. The shared `_DEFAULT_RESPONSES` table and `_schema_name()` helper STAY (used by `MockLLMClient`).

3. **`setup_llm_interception` / `cleanup_llm_interception` method names** in `src/pflow/runtime/workflow_trace.py` — the methods are NOT dead (the engine still calls them for thread-local registration), but the names mislead post-A.6. Could rename to `register_for_llm_call` / `unregister_from_llm_call` in a follow-up task. **Out of Phase A scope unless user requests.**

4. **The temporary `llm` entry in `DEP002`** — drops automatically with A.11.

5. **The temporary `tests/test_nodes/test_llm/test_llm_reasoning.py` per-file ignore** in `pyproject.toml` (`F821, F401`) — drops with item 1's deletion.

6. **The `import llm` inside `tests/test_nodes/test_llm/test_llm_integration.py::has_openai_api_key()`** — already migrated in A.8 (now reads `os.getenv("OPENAI_API_KEY")` directly). Just noting it's done.

7. **The `tests/conftest.py:17` docstring mention** of `mock_llm_calls` — historical context. Could clean up if desired, but it documents the migration so leaving it is fine.

---

## Tacit Knowledge — Things in My Head Not in Documents

### Why the mock omits `cost_usd` (the one trap waiting in A.10)

Already covered in the A.10 section. But to repeat: this is THE detail that catches people. I initially had the mock pre-populate `cost_usd: 0.0`. `test_plan_cost_nested_rollup` failed because `enrich_llm_usage_with_cost` early-returns when `cost_usd` is present. Removing `cost_usd` from the mock fixed it. Now A.10 brings the question back.

### Why `_DEFAULT_RESPONSES` and `_schema_name()` must stay

`MockLLMClient` reads from these. They're shared with the legacy `MockGetModel` (which is being deleted) but the table itself is structural. Don't conflate "delete the legacy mock classes" with "delete the shared resolution table."

### The git lock incident (operational note)

During A.5, encountered a stale 0-byte `index.lock` in the worktree's `.git/worktrees/...` blocking `git restore`. ~10 concurrent claude worktrees on this machine. Confirmed no active git process owned it via `ps aux | grep git`. Removed the lock manually. If you hit this:
```bash
ls /Users/andfal/projects/pflow/.git/worktrees/pflow-feat-prompt-caching-lite-llm/index.lock
ps aux | grep -E '\bgit\b' | grep -v grep
# If the lock is old AND no git process is running, safe to rm
```

### The litellm 1.83.x click pin (resolved by downgrading to 1.82.6)

Phase 0 pinned `litellm==1.83.7`. I had to downgrade to `1.82.6` because `1.83.x` releases hard-pin `click==8.1.8`, which broke 3 stderr-separation `CliRunner` tests that assume click 8.2+'s default behavior. **Don't be tempted to bump litellm during A.9-A.12 cleanup** — surveyed 1.84.0 through 1.110.0 via PyPI, the click pin persists. If a real reason to bump emerges (e.g., a critical bug fix only in newer), be ready to fix the 3 tests with `mix_stderr=False` (deprecated in click 8.2+ but still works in 8.1.x — forward-compat hack).

### Test patches must hit the consumer's import binding, not the source module

When patching `complete`, you MUST patch where the consumer imports it:
- `pflow.nodes.llm.llm.complete` — for LLMNode tests
- `pflow.registry.discovery.complete` — for find_components tests
- `pflow.registry.smart_filter.complete` — for smart_filter tests
- `pflow.core.workflow.discovery.complete` — for find_workflow tests

NOT `pflow.core.llm_client.complete` — that patches the source binding, which doesn't help if the consumer already did `from pflow.core.llm_client import complete`. The `mock_llm_client` autouse fixture in `tests/conftest.py` patches all of them with `raising=False` to be safe.

### The `parse_structured_response` callable-or-attribute trick

`src/pflow/core/llm_utils.py:40` has:
```python
text_output = response.text() if callable(response.text) else response.text
```

This works for BOTH the legacy `llm` library shape (callable `text()`) and the new `AdapterResponse` shape (attribute `text`). Don't change this line unless you remove the only remaining callable case (none exists in production after A.7).

### The trace_hook contract

The adapter calls `trace_hook` with two events:
- `{"event": "before_call", "model": str, "prompt": str}`
- `{"event": "after_call", "model": str, "response": AdapterResponse | None, "error": str | None}`

`WorkflowTraceCollector.get_trace_hook(node_id)` returns a hook that captures `before_call.prompt` into `self.llm_prompts[node_id]`. That's IT — `after_call` is a no-op for trace capture. Future cache work might want `after_call` for response capture, but Phase A doesn't.

The hook MUST NOT raise. The adapter wraps invocation in `contextlib.suppress(Exception)` — defense in depth. If the hook does raise, it gets logged at DEBUG and the call proceeds.

### Anthropic temperature-with-thinking quirk (Phase 0 finding)

Anthropic models with `thinking={...}` enabled REQUIRE `temperature=1.0`. They reject `temperature=0.0` with `BadRequestError`. The adapter doesn't pre-validate this — LiteLLM/Anthropic enforces it server-side. If you write any A.9-A.12 test that exercises Anthropic + thinking + temperature, set temp=1.0.

---

## Open Questions (raise to user when applicable)

### A.10 mock_cost decision (CRITICAL — must decide before implementing A.10)

Already covered. **Stop and ask.**

### Should `setup_llm_interception` / `cleanup_llm_interception` be renamed?

Post-A.6 the methods do thread-local registration, not interception. The names mislead. Rename to `register_for_llm_call` / `unregister_from_llm_call`?

Out of Phase A's scope per the plan. But fast to do (3 callsites total: `engine/instrumentation.py:434`, `engine/instrumentation.py:425` `hasattr` check, `execution/runner.py:708-710`). Could be bundled into A.6 retrospectively or deferred. Ask user.

### CHANGELOG location

Plan mentions "CHANGELOG (or wherever pflow tracks user-facing changes)". Check `releases/` directory layout — last release was v0.12.0 per `.taskmaster/versions.md`. Confirm the migration note format with user before writing.

### Should the deletion checklist items be done as part of A.12 or a separate post-Phase-A commit?

User's instruction was "leave that for me as a checklist in the end". So defer to user. Don't auto-delete.

---

## Things I Suspect but Couldn't Prove

### `total_cost_usd` from Claude Code SDK might need different handling

`enrich_llm_usage_with_cost` currently has logic to fall back to `total_cost_usd` when `cost_usd` is absent. After A.10, the rewritten function preserves this. But I didn't trace through `nodes/claude/claude_code.py:865-887` end-to-end to confirm the flow is still correct post-deletion. Worth a manual check during A.10.

### Mintlify docs may have references I missed

The plan said "find any LLM node docs referencing `llm keys`/`llm models` setup". I haven't actually run that grep against `docs/`. Do it during A.12.

### `pflow settings llm show` may need its own update

If it currently displays "configured via Simon's llm CLI" or similar, that text is now wrong. Run the command, check the output. Probably needs a one-line text fix.

---

## What NOT to Touch (Anti-Patterns)

- **`tests/test_execution/test_plan_drift.py`** — 32 sacred parity tests. Run after every step, even A.9-A.12. If it goes red, your change broke planner↔runtime parity. Fix the change, never weaken the test.
- **The `runtime/workflow_trace.py` `_active_collectors` / `_thread_local` registries** — A.6 kept these. LLMNode's `_active_trace_hook()` reads them. Removing or renaming them breaks the entire tracing path silently (tests still pass — `llm_prompts` populates from a different path in tests because the mock doesn't run real adapter code).
- **`MockLLMClient`'s `_DEFAULT_RESPONSES` lookup** — load-bearing for workflow-discovery tests. Don't refactor "for cleanliness".
- **`enrich_llm_usage_with_cost`'s early-return when `cost_usd` present** — load-bearing pattern. The Claude Code SDK relies on it. Don't remove it during A.10's rewrite.
- **`inject_settings_env_vars()` in `llm_config.py`** — UNCHANGED across all of Phase A. LiteLLM reads from `os.environ` natively, so this still works. Leave alone.
- **The lyrics-generator workflow at `/Users/andfal/projects/music-generation/`** — user's project. Don't touch.

---

## Hard-Won Knowledge from A.1-A.8

### Subagents are very effective for mass test migration

Used `test-writer-fixer` twice (A.5 for `test_llm.py` 61 tests, A.7 for 5 discovery test files) — both came back with high-quality, behavior-preserving migrations. Pattern: brief them with the migration recipe explicitly, list every file, give them the "what NOT to do" list (don't weaken assertions, don't delete tests, don't touch production). Worked well.

A.10's test migration (after the mock_cost decision) is also a good subagent target.

### The 12-commit plan was right but some bundled

The plan said 12 commits, one per A.X step. Reality: I bundled to 4 commits (A.1, A.2+A.3, A.4+A.5, A.6+A.7+A.8). Each bundle was a coherent reviewable unit at a milestone. Future agent: feel free to bundle A.9+A.10 into one commit and A.11+A.12 into another, or do them separately. Doesn't matter as long as each commit passes tests + lint.

### `make check` order matters

Pre-commit hooks run on `git commit`. They include ruff, ruff-format, mypy, deptry. If you commit with broken lint, the hook fails AND modifies files (auto-fix). Then you have to `git add` again. Faster to run `make check` BEFORE every commit attempt.

### `pyproject.toml` per-file-ignores accumulate

I added two during Phase A:
- `"src/pflow/core/llm_config.py" = ["S603"]` — pre-existing, A.9 may drop.
- `"tests/test_nodes/test_llm/test_llm_reasoning.py" = ["F821", "F401"]` — A.5 added; gone if user approves deleting that file.

Audit at A.12.

---

## For You, the Next Agent

**Start by:** reading sections 27-29 of `progress-log.md` carefully. They cover Phase 0 outcomes, Phase A.1-A.5, and Phase A.6-A.8. Sections 1-26 are design history — useful but optional unless something's confusing.

**Before doing anything:** confirm the user wants you to start A.9. The plan and progress log are clear; you should be ready to proceed without further design discussion. But the A.10 mock_cost decision needs user input — flag it early in your conversation so they can think about it while you do A.9.

**First concrete move when authorized:** A.9. Start with the production rewrite (`llm_config.py`), then update help text in `cli/commands/settings.py`, then migrate or skip any tests that exercise the deleted subprocess paths. Verify with `make test` + `make check`. Commit.

**Then ask user about A.10 mock_cost** before starting A.10.

**Don't bother with:**
- Re-running Phase 0 spike scripts. The outcomes are documented.
- Touching production code outside the A.9-A.12 scope.
- Running RUN_LLM_TESTS-gated tests (user said skip for now).
- Anything in `Phases B-G` from the spec — those are separate, after this Phase A merges.

**The user cares most about:**
1. `test_plan_drift.py` stays green (32 tests, sacred parity).
2. No silent behavior changes to existing workflows.
3. Honest reporting — admit weak reasoning, surface decisions, don't paper over.
4. Don't auto-delete files — defer to checklist.
5. Don't commit/push without explicit permission (already given for A.9-A.12 by "go ahead and continue").

**Watch for:**
- `MockLLMClient.complete` cost behavior (the A.10 trap).
- `enrich_llm_usage_with_cost` callsites — there are several. Find them all.
- Subprocess paths in `llm_config.py` — make sure NONE remain after A.9.
- Mintlify docs hits in A.12 — easy to miss.

**When in doubt:**
- Ask the user. They'd rather have 20 turns than a wrong implementation.
- Re-read the relevant progress-log section. The decisions are there.
- Verify against the plan, not against your assumptions.

**Your unique constraints:**
- Worktree at `/Users/andfal/projects/pflow-feat-prompt-caching-lite-llm`. Don't write to `/Users/andfal/projects/pflow/`.
- Branch is `feat/prompt-caching-lite-llm`. Don't switch branches.
- ~10 concurrent claude worktrees on this machine — be aware of stale git locks (see "git lock incident" note above).

---

> **Note to next agent**: After reading this document, sections 27-29 of `progress-log.md`, and (skim) the plan, you should know exactly what to do for A.9. For A.10, stop and ask the user about mock_cost before implementing. For A.11 and A.12, mechanical — no decisions needed.
>
> Confirm readiness by stating: "I've read sections 27-29 of progress-log + this braindump. Ready to start A.9. Will flag the A.10 mock_cost decision when we get there." Then start.
