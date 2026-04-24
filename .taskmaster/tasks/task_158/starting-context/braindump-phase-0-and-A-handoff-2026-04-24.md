# Braindump: Task 158 — Phase 0 + Phase A handoff (2026-04-24)

**Read first:** `.taskmaster/tasks/task_158/starting-context/braindump-design-complete.md` — the previous braindump captures the design discussion through 2026-04-23 and remains 90% accurate. This document captures what's changed since (the 2026-04-24 session) and what's in MY head right now that isn't in the plan, spec, or progress log.

---

## Where I Am

The session created the Phase 0 + Phase A implementation plan. User approved it via ExitPlanMode. The plan is at `.taskmaster/tasks/task_158/implementation/implementation-plan.md` (also at `~/.claude/plans/lets-create-the-plan-foamy-haven.md`).

Nothing has been implemented. The next move is the Phase 0 spike — write throwaway scripts under `scratchpads/task-158-spike/`, run them against real APIs (~$0.10), document outcomes, then start Phase A.

---

## What's Different From the Previous Braindump

The previous braindump (`braindump-design-complete.md`) was written 2026-04-22/23 after design completed. **Several things have changed since:**

1. **Auto-batch-prefix caching design pivot.** Previous spec had it ON by default with `batch_cache: false` opt-out. Current spec has it GATED on `prewarm: true`. Without prewarm, all N parallel batch calls write the cache simultaneously — no read benefit, just overhead. So it makes no sense to apply it. The user surfaced this; I didn't catch it during the original design. The `batch_cache: false` field is GONE from the spec; only `prewarm: bool` remains.

2. **Phased planning approach.** User's exact words: *"we cant write a good plan for implementing this without knowing litellm works and is functional and ready. Does this make sense?"* — This came up at the end of the session and is the single most important strategic shift. Plan Phase 0 + Phase A only. Plan Phases B–G AFTER Phase A merges, when LiteLLM behavior is known concretely.

3. **`--no-cache` flag scope clarified.** User: disables memo layer ONLY; prompt cache is always active. Two layers, fully independent. New "Cache Layer Independence" section in the spec.

4. **Algorithm depth for `analyze-cache` decided as v1a (Level 2 — pastable suggestions).** v1b (full prefix-tree optimization, cross-workflow alignment, explicit `cache apply` command) deferred. Decided to assess v1b complexity during Phase B–G plan writing.

5. **Cache reference rule generalized.** Spec now says "references that vary across calls referencing the same chunk are rejected" instead of just "`${item.X}` rejected". Aggregate batch outputs (`${batch-node.some_field}`) and indexed accesses to stable values are explicitly valid.

6. **Two findings from this session's research that contradict the original spec:**
   - **`~/.config/io.datasette.llm/keys.json` is NOT currently read by pflow.** Codebase grep confirmed. The spec's "optionally read for migrating users" was actually proposing NEW functionality, not migrating existing behavior. Plan defers direct read to v1.x; Phase A migration is env-vars-only. The previous braindump assumed pflow already read keys.json — it doesn't.
   - **Cache write multiplier is hardcoded `2.0` only.** Spec assumes 1.25× (5-min TTL) and 2× (1-hour TTL) Anthropic-style multipliers. Code at `core/llm_pricing.py:168` has only `2.0`. Becomes load-bearing in Phase E (1h TTL feature), not Phase A. Phase 0 spike should note this.

7. **Documentation drift discovered:** `core/CLAUDE.md:198` says "46+ models"; actual `MODEL_PRICING` count is 41. Fix during Phase A.10 documentation pass.

8. **Spec was trimmed of implementation details.** User's complaint: *"The task spec is currently including a bit too much implementation details. These things should ideally be in just the implementation plan when we write it and task spec is the what and why. Plan is the how."* — File paths, line numbers, exact phasing day counts removed from the spec. They live in the plan now.

---

## User's Mental Model — Things They Said This Session

Update to the previous braindump's "load-bearing phrases" list. New ones from 2026-04-24:

- *"all estimates are off. dont rely on them"* — re: implementation timelines. They explicitly removed the "5-10 engineer-day" anchor. Don't replace it with another guess.

- *"we should assume llm_pricing.py can be removed (hopefully)"* — Outcome A (delete) is the user's preferred outcome. They want the maintenance-lag problem to go away. If Phase 0 supports A, take it.

- *"if there is we change this retroactively"* — re: needing escape hatches for the order invariant. The user is comfortable iterating. Don't over-design v1; ship the minimum that works.

- *"use error if batch is bigger than 10 and prompt is larger than 2k tokens or something like that"* — gave a concrete starting threshold but added "something like that". They don't care about the exact numbers — pick something reasonable, refine if real usage shows otherwise.

- *"we could start like this, but the exact numbers are not important, we can do something simpler if easier to implement"* — same theme. **Engineering taste over precision.**

- *"How advanced will our algorithm be at identifying exactly what changes are needed for optimal prompt caching across the workflow?"* — Their interest in the optimization algorithm is strategic, not just tactical. They genuinely want pflow to be smart about caching, not just a passthrough. v1b (full prefix-tree optimization) is interesting to them; assess it seriously during Phase B–G planning.

- Their default move when unsure: *"How do we handle X?"* — they're not assigning a solution, they're testing whether I've thought it through. Match this — don't propose definite-sounding answers when you're guessing. Say "here are options" + "I'd pick Y because Z".

---

## Tacit Knowledge — Things in My Head Not in Documents

### Why I structured the plan with overlapping mock infrastructure (A.4-A.8)

The previous design instinct is "rewrite everything atomically". I rejected that. Reasons:

1. **The current `mock_llm_calls` autouse fixture is class-level** — every single test gets it. A hard cutover means every test fails simultaneously while you're mid-migration. Painful.
2. **The new `mock_llm_client` fixture coexists** during A.4–A.7. As you migrate each caller (LLMNode, then 3 discovery sites), the unmigrated ones still get the legacy mock. Tests stay green throughout.
3. **A.8 is the cleanup step** — once all callers migrated, the legacy fixture and mock classes get deleted in one commit. Atomic at the END, not the BEGINNING.

If you're tempted to skip the overlap and do a hard cutover, don't. You'll save no time and add risk.

### Why I went with thread_local + `_active_collectors` for trace_hook lookup

The current monkey-patch uses `_thread_local.current_node` and `_active_collectors[thread_id]`. I considered switching to `contextvars.ContextVar` (cleaner threading model, async-friendly). I went with thread_local for continuity:

- pflow's LLMNode is sync, runs inside ThreadPoolExecutor. thread_local is sufficient.
- contextvars would require touching every executor entry point.
- The class-level `_active_collectors` dict (mutated under `_llm_lock`) already works.

If the next agent finds a clean way to use contextvars, go for it — but it's not required for Phase A correctness. Not a hill to die on.

### Why I didn't propose deleting the `Pydantic ValidationError` catch outright

It's labeled "PATTERN EXCEPTION" with a multi-line comment about why try/except in `exec` is normally an anti-pattern. The catch was added because Pydantic Options are deterministic — retrying won't help. Under LiteLLM:

- LiteLLM has its own exception types (`BadRequestError`, etc.).
- Whether these are also deterministic-on-retry needs Phase 0 verification.
- If LiteLLM's bad-param errors don't auto-retry helpfully, an equivalent catch is needed.
- If LiteLLM cleanly raises typed exceptions that the retry logic respects, no catch needed.

**ASSUMPTION:** the catch can be removed under LiteLLM. **NEEDS VERIFICATION:** does LiteLLM raise `BadRequestError` for invalid params, and does pflow's retry loop handle it correctly? Test by deliberately passing bad params during the spike.

### What I almost forgot to plan for

- **`response_format` shape per provider.** Anthropic, OpenAI, and Gemini all accept structured output via LiteLLM but the exact key shape (`response_format={"type": "json_schema", "json_schema": {...}}` vs `response_format={"type": "json_object"}` vs Anthropic's tool-use shim) might differ. Phase 0 composition matrix should test this on each provider. The plan says this implicitly under A.3 ("Phase 0 confirms the exact key shape") but it's easy to miss.

- **Pydantic class → JSON schema for the 3 discovery callers.** Currently `registry/discovery.py:89` passes `schema=ComponentSelectionSchema` (a Pydantic class) directly to `model.prompt`. Under the adapter, must convert via `Schema.model_json_schema()`. Easy to forget; called out in A.7 but worth re-emphasizing.

- **The `model.prompt` schema parameter is positional in some cases**. Look at how the 3 discovery sites differ from the LLMNode in their schema usage — they pass it differently. The adapter API needs to accept either Pydantic class OR JSON dict, OR all callers convert before calling. I went with "callers convert" — keep the adapter accepting only dicts.

### Things I noticed but didn't write into the plan

- **`tests/shared/llm_mock.py` has a `_default_responses` mechanism** for known schemas (WorkflowDecision, ComponentSelection, etc.) — this is what makes most workflow-discovery tests "just work" without explicit setup. The new `MockLLMClient` MUST preserve this — don't delete it.

- **`registry/smart_filter.py:175-180` has model-name string sniffing for Gemini variants** to set `thinking_budget=0` on `gemini-2.5` (not `lite`) and `thinking_level="minimal"` on `gemini-3`. This is the precedent for the new `llm_reasoning_map.py` provider detection logic. Reuse the same sniffing patterns; don't reinvent.

- **`pyproject.toml:178` has `S603` ignore for `llm_config.py`** (subprocess allow-list). When you delete `_has_llm_key()` and `get_llm_cli_default_model()` from `llm_config.py`, also remove this ignore. If no subprocesses remain, the file no longer needs S603.

- **`pflow.core.llm_config.SettingsManager`** — I haven't read its full implementation but the plan assumes it pushes pflow settings into `os.environ` cleanly. **NEEDS VERIFICATION:** confirm `inject_settings_env_vars()` actually does what we need for LiteLLM (LiteLLM only reads from `os.environ`).

---

## Open Threads

### Spike scope items I'm uncertain about

- **Logger silencing knob name.** I listed `litellm.suppress_debug_info`, `litellm.set_verbose`, `litellm._turn_on_debug` as candidates. Don't know which is current. The LiteLLM docs change with versions. Find the right knob during the spike; pin it.

- **Async vs sync.** LiteLLM has both `litellm.completion` and `litellm.acompletion`. pflow uses sync. **ASSUMPTION:** sync is fine. If the spike reveals a perf benefit to async (none expected), reconsider.

- **`completion_cost()` semantics.** Does it return None for unknown models, raise, or return 0.0? Different behaviors require different fallback logic in A.10. Verify in spike.

- **Streaming.** User said no. Phase A doesn't add it. But LiteLLM defaults to non-streaming when `stream=False`, which I'm assuming. Confirm.

### What I would investigate before writing Phase B–G plan

- How LiteLLM's `messages` list translates to provider message structure (especially Gemini's `content` field shape).
- Whether `response_format` works at all on Anthropic models (Anthropic uses tool-use for structured output, not native response_format).
- Whether `prompt_cache_key` for OpenAI is best set by us (computed from cache content hash) or auto-derived by LiteLLM.
- Provider-specific minimum token thresholds in the actual LiteLLM source code (not the docs — the docs may lag).

---

## Unexplored Territory

**UNEXPLORED:** Does `pflow settings env` exist as a command? The plan suggests pointing users at it as the alternative to `llm keys set`. If it doesn't exist, the help text needs to suggest something else (raw env vars only). Verify before A.9.

**UNEXPLORED:** What does the deptry config look like? `pyproject.toml:184` has `DEP002 = ["llm-anthropic", "llm-gemini", "PyYAML"]`. After removing `llm-anthropic` and `llm-gemini`, deptry should be happy. But if there are other transitive deps from LiteLLM that look "unused but imported" (like `boto3` showing up but not directly imported), deptry might complain. Phase A.11 should run `make check` and address.

**UNEXPLORED:** Will Anthropic's model name format change under LiteLLM? Currently pflow uses `anthropic/claude-sonnet-4-5`. LiteLLM also uses provider-prefixed names. Should be a clean swap, but check during the spike that the exact same model strings work.

**CONSIDER:** The spike scripts will leave behind real API call data. If the lyrics-generator workflow is used as a smoke test, it will spend real money on each Phase A verification run. Cap the smoke test to a small workflow first; only run the full lyrics-generator end-to-end at the very end.

**MIGHT MATTER:** `claude_agent_sdk>=0.1.17` is in pyproject (Claude Code node). It's untouched by Phase A, but make sure removing the `llm` package doesn't accidentally break claude_agent_sdk's import resolution (they should be unrelated, but verify).

**MIGHT MATTER:** The `RUN_LLM_TESTS=1` env-var gate currently only enables Anthropic-key tests (`tests/test_nodes/test_llm/test_llm_integration.py:has_openai_api_key()` despite the name). Phase A's adapter should be tested against all three providers. May need new gates: `RUN_ANTHROPIC_TESTS`, `RUN_GEMINI_TESTS`, `RUN_OPENAI_TESTS`. Check existing pattern, extend cleanly.

**MIGHT MATTER:** Image attachments via base64-encoded data URLs (LiteLLM's path) can hit token limits for large images. Current `llm.Attachment(path=...)` may handle this differently. Test image-attachment behavior during A.5 with a real image.

**UNEXPLORED:** Does pflow have any code that catches `llm.UnknownModelError` or `llm.NeedsKeyException` by import (vs by class name string)? If so, those imports break when `llm` library is removed in A.11. I think the only catches are by class-name string match (per agent research), but worth a final grep before A.11.

---

## Hard-Won Knowledge

### The current monkey-patch is more complex than the spec acknowledged

The original spec called the tracing redesign "a function call replacement". Reality:
- TWO layers of interception (`llm.get_model` AND per-instance `model.prompt`)
- Reference-counted via `_llm_interception_count` for nested workflows
- Per-thread state: `_thread_local.current_node` AND `_active_collectors[thread_id]`
- Lock-protected via `_llm_lock` (class-level threading.Lock)
- Lazy install/teardown
- Sub-workflow collectors set `enable_llm_interception=False` to inherit parent's interception

The `trace_hook` parameter on the adapter is the simpler replacement, but only because we move the "is a collector active" check from the patched function to the LLMNode's own code. The `_active_collectors[thread_id]` registry is still needed and still mutated under lock. Don't try to delete it.

### `MockLLMModel` returns Mock objects — not real LLM responses

This bit me during research. `tests/shared/llm_mock.py:46` has `mock_response.text = MagicMock(return_value=json.dumps(response_data))` — so `response.text()` is callable. But `mock_response.usage = MagicMock(return_value=Mock_with_input_output_details)` — so `response.usage()` is also callable, returning a Mock with `.input`, `.output`, `.details` attributes.

The new `MockLLMClient.complete(...)` should return an `AdapterResponse` directly (a real dataclass instance, not a Mock). This is cleaner. But test files that asserted on `mock_response.text.assert_called_once()` need to switch to asserting on `MockLLMClient.call_history` instead.

About 20 sites in `test_llm.py` build `Mock()` directly with `.text.return_value = "..."`. Those tests are coupled to the llm-library mock contract. Reshape them as part of A.5 — don't try to preserve the Mock-with-callables pattern.

### `compute_node_config` is the precedent that matters most

For Phase C work later: the `batch_config` conditional inclusion at `instrumentation.py:162-169` is the canonical pattern. Verbatim:

```python
if batch_config:
    config["batch"] = {
        "items_template": batch_config.items_template,
        "item_alias": batch_config.item_alias,
        "error_handling": batch_config.error_handling,
        "max_retries": batch_config.max_retries,
    }
```

When Phase C adds `prompt_cache`, it follows EXACTLY this pattern. Conditional inclusion. Semantic-only (not tunable). The previous braindump emphasized this; I'm reinforcing it because it's the #1 silent-correctness risk for the whole task.

But Phase A doesn't touch this. Don't pre-implement Phase C work.

---

## What I'd Tell Myself

1. **Don't shortcut the Phase 0 spike.** It's $0.10 of API calls. Run all 5 concerns. The pricing investigation alone (Outcome A vs B vs C) shapes hours of A.10 work.

2. **The plan's commit sequence (A.1 → A.12) is real.** Don't try to combine commits. Each step has a specific verification checkpoint. If you skip ahead, you lose the ability to bisect when something breaks.

3. **A.6 (tracing redesign) is scary but the plan handles it.** The trace_hook parameter goes in during A.3. The check-active-collector code goes in LLMNode during A.5. ONLY DELETE the monkey-patch in A.6 once both are wired. There's a brief window where both mechanisms coexist (the monkey-patch on legacy `llm.get_model` calls plus the new trace_hook on adapter calls). That's not a bug, that's the safety net.

4. **`test_plan_drift.py` is the canary.** Run it after every significant change in Phase A. If it goes red, the change you just made affected execution semantics. Don't relax the test — fix the change.

5. **The user is comfortable with iteration.** If you hit a wall, raise it. Don't paper over it. They explicitly value 20 turns over a wrong design.

6. **Don't commit without explicit permission.** Auto-memory is clear: never `git add`/`git commit`/`git push` unless told.

7. **Watch the lyrics-generator workflow.** It's at `/Users/andfal/projects/music-generation/workflows/lyrics-generator/`. Don't modify it. It's the user's. If you need to test against it, ASK FIRST.

---

## For the Next Agent

**Start by:** reading `task-158.md` (the spec, ~640 lines), `progress-log.md` (the design journey, ~700 lines, especially section 26 from this session), and `implementation/implementation-plan.md` (the Phase 0+A plan I wrote, ~700 lines). Also read the previous braindump (`braindump-design-complete.md`) — most of it is still accurate. **In total ~2.5k lines.** Don't skip.

**Before doing anything:** confirm the user wants you to start the Phase 0 spike. The plan is approved but the user might want to do plan review (`/ultrareview` or similar) first. If unsure, say: "The Phase 0+A plan is approved. Should I start the Phase 0 spike, or do you want to review the plan further first?"

**First concrete move when authorized:** create `scratchpads/task-158-spike/` directory; write small `spike_<n>.py` scripts (one per concern: cache mechanics, composition matrix, pricing, operational, exceptions). The example spike code in the previous braindump (`braindump-design-complete.md` — search "Phase A concrete first move") is a starting point. Adapt it for the 5 spike concerns.

**The user cares most about:**
1. Phase 0 spike covers all 5 concerns thoroughly. Don't skip dep audit or pricing investigation.
2. Phase A preserves all existing behavior — every workflow runs identically.
3. `test_plan_drift.py` stays green throughout.
4. The pricing outcome (A/B/C) is honestly evidenced; don't assume A just because they want it.
5. User-facing error messages stay close to current text (muscle memory).

**Don't bother with:**
- Implementing Phases B–G features (cache parsing, rendering, analyze-cache). Out of scope until Phase B-G plan is written, after Phase A.
- Touching the lyrics-generator workflow files (user's, not ours).
- Optimizing the `_active_collectors[thread_id]` thread-local pattern (works as-is).
- Adding direct `~/.config/io.datasette.llm/keys.json` read (deferred to v1.x).
- Per-TTL cache pricing (deferred to Phase E).

**Watch for:**
- LiteLLM behavior that contradicts the plan's assumptions. If found, surface immediately and stop, don't paper over.
- Logger spam from LiteLLM in test output. Silence at module import.
- Any new exception class from LiteLLM that doesn't match `BadRequestError`/`AuthenticationError`. Add to the exception map.
- `make check` warnings about deptry — may need to add LiteLLM transitive deps to ignore lists.

**When in doubt:**
- About library behavior: run the spike, don't guess.
- About message structure: check LiteLLM's actual output on a real call (dump `response.model_dump()`).
- About user preference: ask. They prefer 20 turns over a wrong design.
- About spec contradictions: follow the plan (which already resolved them) and flag for the user.

**Your unique constraint:** the user uses worktrees aggressively. You're in `/Users/andfal/projects/pflow-feat-prompt-caching-lite-llm/` on branch `feat/prompt-caching-lite-llm`. Don't write to `/Users/andfal/projects/pflow/` (the original) — the user explicitly moved spec changes to the worktree and asked me to stop writing to the original.

---

> **Note to next agent**: Read this document fully before taking any action. Then read `task-158.md`, `progress-log.md` (especially section 26), `implementation/implementation-plan.md`, and the prior `braindump-design-complete.md`. When ready, confirm you've read and understood by summarizing the key points (especially: the prewarm-gating pivot, the phased planning approach, the two spec contradictions, and the Phase 0 spike scope), then state you're ready to proceed. Do not start coding without user authorization.
