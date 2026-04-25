# Task 158 — Phase A completion plan: loose ends + deferred items

**Created:** 2026-04-25, after the 10-step typed-exception architecture implementation landed (uncommitted).
**Branch:** `feat/prompt-caching-lite-llm`
**Read first:** `.taskmaster/tasks/task_158/implementation/progress-log.md` §34 (full implementation context). The plan itself is at `.taskmaster/tasks/task_158/implementation/phase-A-completion-plan.md` (v1.0 + v1.1 revisions).

## Purpose of this document

The implementing agent (me) finished all 10 steps of the completion plan. All 5306 tests pass; `make check` is clean; the architectural seal is intact. But on honesty review I found 5 real loose ends, and 6 polish items from the original code review were deliberately deferred. This document enumerates each one with full context so the next agent can decide (with the user) what to fix vs. defer further.

**The next agent's job is NOT to fix all of these.** It's to (1) understand them, (2) discuss with the user which subset matters, (3) implement the chosen subset, (4) defer the rest with documented reasoning. Do not silently fix everything.

**Do not start fixing anything before the user agrees to a scope.** Pattern: "Here are the 11 items — I recommend fixing items A, C, D before code review and deferring B/E/F to follow-ups. Sound right?"

## Recommendation summary

| Severity | Item | Recommendation |
|---|---|---|
| Critical | LE-1: Integration test gap (end-to-end JSON contract) | **Fix now** — this is the contract the work was about; not pinned by tests |
| High | LE-2: MockLLMClient missing `warnings` knob | **Fix now** — small change, removes future test friction |
| High | LE-3: Stale adapter docstrings | **Fix now** — trivial, prevents confusion |
| High | LE-4: `tests/CLAUDE.md` mock-behavior section drift | **Fix now** — same context, two minutes |
| Medium | LE-5: `_NODE_TYPE_FAILURE_CATEGORY` missing regression test | **Fix now or defer to code-review** |
| Polish | P-12: `_extract_thinking_budget` returns 0 for categorical reasoning | Defer — need separate task scoping |
| Polish | P-13: `exec_fallback` substring `"timed out"` fragility | Defer — accepted seal-preserving trade-off |
| Polish | P-14: `_append_batch_stats` partial-cost drop | Defer — independent of typed-exception work |
| Polish | P-15: `total_cost > 0` cost-hide pattern (4 sites) | Defer — pre-existing Task 108 pattern |
| Polish | P-16: `prep` `ValueError` for missing image / `_validate_timeout` | Defer — node-error consistency follow-up |
| User decision | UD-1: CHANGELOG version label | User must decide |
| User decision | UD-2: Gemini PR #15226 fix re-verification on 1.82.6 | User must decide |

Bottom line: **fix LE-1 through LE-5 (15-30 min total), defer P-12 through P-16, ask user about UD-1 and UD-2.** Everything in LE-* is ~5 minutes each.

**Status update 2026-04-25:** LE-1 through LE-5 are now fixed in the working tree:
- LE-1/LE-5: added `WorkflowRunner` end-to-end coverage for LLM error diagnostics and `__failures__[node]["category"] == FAILURE_CATEGORY_LLM`.
- LE-2/LE-4: `MockLLMClient.set_response(..., warnings=...)` landed and `tests/CLAUDE.md` documents `response.warnings`.
- LE-3: `llm_client.py` docstrings now describe transient LiteLLM exceptions being translated to `LLMTransientError`.

---

## Loose ends from the honesty pass

### LE-1 (CRITICAL) — Integration test coverage gap

**The largest gap.** The 10-step implementation establishes a new contract:

> When an LLM call fails, the JSON output `result["errors"][0]["context"]` carries `error_class`, `model`, `reason`/`kind`, `category="llm_failure"`.

This contract is **only verified at the unit level**, not via integration test through `WorkflowRunner`. The chain that delivers the contract is:

```
LLMNode._call_llm raises LLMCallError
  → caught at boundary, builds error_dict via _error_dict_from_exception()
  → exec_res["_diagnostic_context"] = exc.to_diagnostics()[0].context
  → LLMNode.post writes shared["_diagnostic_context"] (lands in shared[node_id]["_diagnostic_context"] via NamespacedSharedStore)
  → engine step 17.5: mark_node_failed archives shared[node_id] → __failures__[id]["data"]
  → executor_service.build_error_list reads __failures__[id]
  → _enrich_error_from_node_output reads node_output["_diagnostic_context"] and merges into context
  → format_execution_errors → result["errors"][i].context
```

Each step is unit-tested in isolation but no test exercises the full chain. The `tests/CLAUDE.md` Pitfall #19 explicitly calls this out:

> **Cross-Layer Features Need End-to-End Tests Through `WorkflowRunner`** — Unit tests that mock the boundary you're testing will pass while the real pipeline breaks.

**What to test:**

1. Build an inline IR with one LLM node.
2. Monkeypatch `pflow.nodes.llm.llm.complete` to raise `UnknownModelError("Unknown model: x", model="anthropic/foo", reason="unknown_name")`.
3. Run via `WorkflowRunner().run(ir, params)`.
4. Assert `result.success is False`.
5. Assert `result.diagnostics[0].context["category"] == "llm_failure"`.
6. Assert `result.diagnostics[0].context["error_class"] == "UnknownModelError"`.
7. Assert `result.diagnostics[0].context["model"] == "anthropic/foo"`.
8. Assert `result.diagnostics[0].context["reason"] == "unknown_name"`.

Then repeat the test for `MissingApiKeyError(kind="missing_key")`, `InvalidRequestError`, and `LLMResponseParseError` (raised from the schema-mode JSON-parse path).

Plus one `__warnings__` end-to-end test:
1. Monkeypatch `complete` to return an `AdapterResponse` with a `warnings=[{"kind": "llm_empty_response_reasoning", "text": "...", "context": {...}}]`.
2. Run via `WorkflowRunner`.
3. Assert `result.status == WorkflowStatus.DEGRADED`.
4. Assert `result.warnings[0].context["type"] == "api_warning"` (or whatever runner._extract_runtime_warnings produces).
5. Assert the rendered warning message contains the expected remediation.

**File suggestion:** `tests/test_execution/test_executor_service_llm.py` (new) OR extend `tests/test_integration/test_failed_node_invariant.py`. Pattern from `tests/CLAUDE.md`: build IR dict, run through `WorkflowRunner`, assert on `result.shared_after["__failures__"]` and the structured `result.diagnostics[i].context`.

**Why this is critical:** if a future refactor breaks any link in the chain — say, `mark_node_failed` stops archiving `_diagnostic_context`, or `_enrich_error_from_node_output`'s LLM branch is accidentally removed — the unit tests still pass and the contract silently breaks. The agent UX would degrade to "prose only, no structured context" without anyone noticing until production.

**Estimate:** 30-45 min for 5-6 tests covering the full matrix.

**Files to read first:**
- `tests/test_integration/test_failed_node_invariant.py` (pattern reference)
- `src/pflow/execution/runner.py` (`WorkflowRunner.run` signature)
- `src/pflow/runtime/node_state.py` (`mark_node_failed`, `__failures__` shape)
- `src/pflow/execution/executor_service.py:251-298` (`_enrich_error_from_node_output` LLM branch)

**Recommendation:** **fix now.** This is the contract this whole branch exists to establish. Integration test is the regression guard.

---

### LE-2 (HIGH) — MockLLMClient missing `warnings` knob

**Plan ref:** R-Sug-5 in `phase-A-completion-plan.md`.

**Issue:** `tests/shared/llm_mock.py::MockLLMClient.set_response(...)` accepts `cost_usd: float | None = None` but no `warnings: list[dict] | None = None`. Test authors who want to exercise the empty-response warning path through the standard mock have no way to inject warnings — they have to monkeypatch `pflow.nodes.llm.llm.complete` directly with a hand-built `AdapterResponse(warnings=[...])`. This works but creates friction.

**What to do:**

1. Add `warnings: list[dict[str, Any]] | None = None` kwarg to `MockLLMClient.set_response(...)`.
2. Store in the response dict (parallel to how `cost_usd` is stored).
3. The `complete()` method on the mock returns `AdapterResponse(..., warnings=self._get_warnings(...))`.
4. Default empty list (matching production default).

**Files to read first:**
- `tests/shared/llm_mock.py` (specifically the `MockLLMClient` class and `set_response`/`_get_cost`/`get_response` methods)
- `tests/CLAUDE.md` "Mock behavior notes" section (which doesn't currently mention `warnings`)

**Recommendation:** **fix now.** ~5-minute change. Completes the mock contract and removes future test friction.

---

### LE-3 (HIGH) — Stale adapter docstrings

**Issue:** `src/pflow/core/llm_client.py` has two docstrings that are now wrong after Step 2 extended the catch tuple from 4 to 7 LiteLLM exception classes:

**Stale spot 1: module docstring (lines 11-13):**
```
- Translating every deterministic LiteLLM exception
  (``BadRequestError``, ``AuthenticationError``, ``NotFoundError``,
  ``PermissionDeniedError``) into a typed ``LLMCallError`` subclass so
  consumers never import ``litellm.exceptions`` to discriminate
```

**Wrong because:** we now translate transient exceptions too (`Timeout`, `RateLimitError`, `InternalServerError` → `LLMTransientError`).

**Should be:**
```
- Translating every LiteLLM exception (deterministic: BadRequestError,
  AuthenticationError, NotFoundError, PermissionDeniedError; transient:
  Timeout, RateLimitError, InternalServerError) into a typed LLMCallError
  subclass so consumers never import litellm.exceptions to discriminate
```

**Stale spot 2: `complete()` docstring (lines ~159-160):**
```
Other exceptions (timeout, network, rate limit, internal server
error) propagate unwrapped. The caller's retry loop decides.
```

**Wrong because:** `Timeout`, `RateLimitError`, `InternalServerError` are now wrapped in `LLMTransientError`. Only network errors outside that tuple propagate raw.

**Should be:**
```
Transient exceptions (Timeout, RateLimitError, InternalServerError)
are wrapped in LLMTransientError so consumers can catch the
LLMCallError umbrella. Other exceptions (network errors outside
LiteLLM's typed hierarchy) propagate unwrapped. LLMNode re-raises
LLMTransientError so the Node retry loop can retry.
```

**Files to read first:**
- `src/pflow/core/llm_client.py` (the actual current docstrings, around lines 1-23 and 141-189)

**Recommendation:** **fix now.** Two small edits, ~3 minutes.

---

### LE-4 (HIGH) — `tests/CLAUDE.md` mock-behavior section drift

**Issue:** The "Mock behavior notes" section in `tests/CLAUDE.md` documents `response.text`, `response.usage`, `call_history` truncation, and `cost_usd` defaulting to None. It does NOT mention the new `response.warnings` field added in Step 2.

A future test author writing "I returned a successful AdapterResponse but no warning surfaced — why?" will hit this without a doc note.

**What to do:** Add a bullet to the "Mock behavior notes" list:

```
- response.warnings is a list[dict] (each entry has kind/text/context).
  Defaults to empty list. To trigger empty-response warning paths in tests,
  pass warnings= to MockLLMClient.set_response (after LE-2 lands), or
  monkeypatch pflow.nodes.llm.llm.complete directly with a hand-built
  AdapterResponse.
```

**Files to read first:**
- `tests/CLAUDE.md` "Mock behavior notes" section (currently around lines 82-90)
- The new `AdapterResponse.warnings` definition in `src/pflow/core/llm_client.py:121`

**Recommendation:** **fix now together with LE-2.** Same context, two minutes.

---

### LE-5 (MEDIUM) — `_NODE_TYPE_FAILURE_CATEGORY` missing regression test

**Issue:** Step 5 added `LLMNode → FAILURE_CATEGORY_LLM` to `_NODE_TYPE_FAILURE_CATEGORY` in `src/pflow/runtime/engine/engine.py:55-60`. A future refactor that drops the entry would silently revert LLM failures to `FAILURE_CATEGORY_NODE_ERROR` (mapped to generic `"execution_failure"`) — the rich category and `_diagnostic_context` enrichment would still work via `_enrich_error_from_node_output`, but the top-level `Diagnostic.context["category"]` would silently change from `"llm_failure"` to `"execution_failure"`.

**What to do:** Add a regression test that:
1. Runs an LLM workflow that fails (mocked).
2. Inspects `__failures__[node_id]["category"]`.
3. Asserts it equals `FAILURE_CATEGORY_LLM` (the constant, not the string).

**Pattern reference:** existing tests for shell/http failure categorization probably exist somewhere — find one and mirror.

**Files to read first:**
- `src/pflow/runtime/engine/engine.py:55-60` (the dict)
- `src/pflow/runtime/engine/engine.py:493` (the consumer at step 17.5)
- Existing tests for failure categorization (search `_NODE_TYPE_FAILURE_CATEGORY` in tests)

**Recommendation:** **fix now or defer to code-review.** This could naturally fold into LE-1's integration tests — check `result.shared_after["__failures__"][node_id]["category"]` in the test that already exercises a typed `LLMCallError` failure.

---

## Polish items deferred from original code review

These were called out in the original Phase A code review (4 agents) but explicitly deferred in the plan because they're independent of the typed-exception architecture. Each is genuinely standalone — fixing them later doesn't create churn.

### P-12 — `_extract_thinking_budget` returns 0 silently for categorical reasoning

**Source:** review-silent-failures #5 + review-agent-ux #6.

**Issue:** `src/pflow/core/llm_client.py:_extract_thinking_budget` returns 0 for OpenAI's `reasoning_effort` ("low"/"medium"/"high") and Gemini-3's `thinking_level` (categorical strings, not token counts). When `thinking_tokens > 0` but `thinking_budget == 0`, the metric "thinking_utilization = thinking_tokens / thinking_budget" can't be computed cleanly. Code that uses this currently produces "0.0% utilization" or division-by-zero risk.

**What's affected:**
- `src/pflow/core/metrics.py:188-197` — computes utilization as `thinking_tokens / thinking_budget if thinking_budget > 0 else 0.0`. The `else 0.0` is misleading because for categorical models, the model DID use reasoning — just no token-level budget concept.

**Possible fixes:**
- (a) Add a sibling `reasoning_mode: "categorical" | "token_budget" | None` field to `AdapterResponse.usage`. Skip the utilization metric for `"categorical"` mode.
- (b) Return `None` (instead of 0) from `_extract_thinking_budget` for categorical models. Make consumers handle None explicitly.
- (c) Just delete the utilization metric. It's a derived stat with limited value.

**Why deferred:** This is a metrics/observability question, not a typed-exception architecture question. Needs separate scope-and-design conversation with the user. Likely a small task on its own.

**Files to read first:**
- `src/pflow/core/llm_client.py:_extract_thinking_budget`
- `src/pflow/core/metrics.py:188-197`

**Recommendation:** Defer. Not blocking PR.

---

### P-13 — `exec_fallback` substring `"timed out"` detection fragility

**Source:** review-agent-ux #4.

**Issue:** `src/pflow/nodes/llm/llm.py::exec_fallback` (and the helper `_error_dict_for_generic_failure`) does `if "timed out" in str(exc).lower()` to detect a retry-exhausted timeout. This will misclassify any non-timeout exception whose message contains "timed out" as a substring (e.g., "DNS resolution timed out" from a network error). Misleading remediation hint.

**Possible fix:** Catch `litellm.exceptions.Timeout` explicitly here. But this re-imports `litellm.exceptions` and breaks the architectural seal.

**Trade-off accepted in §32:** The seal exists to centralize *classification* (the adapter is the single translator), not to forbid all `litellm.exceptions` references. Re-introducing the import here for one targeted isinstance check is defensible — but the substring check is "good enough" because it preserves the actionable message text without coupling.

**Why deferred:** No real failure has been observed. The substring is fragile but not actively broken. If a misclassification surfaces in real usage, fix then.

**Files to read first:**
- `src/pflow/nodes/llm/llm.py:_error_dict_for_generic_failure` (the helper that does the substring check)
- `src/pflow/nodes/llm/llm.py:exec_fallback`

**Recommendation:** Defer. Revisit if a real misclassification surfaces.

---

### P-14 — `_append_batch_stats` partial-cost drop

**Source:** review-silent-failures #4.

**Issue:** `src/pflow/core/trace_report.py:1049-1052` does `total_cost = sum(c for c in costs if c is not None)` for batch-level cost rendering. When some items have `cost_usd = None` (unpriced models in batch), this silently drops them and renders "Total cost: $X.XX" understating the truth. Should mirror the tri-state from `_collect_llm_summary` (`partial_cost_usd` + `pricing_available: False` + `unavailable_models`).

**What's affected:** `pflow report --report` output for batch nodes. The CLI summary and trace JSON DO get the tri-state treatment via `_collect_llm_summary`; only the per-batch report renderer in `trace_report.py` doesn't.

**Why deferred:** Independent of the typed-exception completion. Different code path (report rendering, not error/cost metrics flow). Small scoped fix.

**Files to read first:**
- `src/pflow/core/trace_report.py:1049-1052` (the affected sum)
- `src/pflow/runtime/workflow_trace.py::_LLMSummaryAccumulator` (the tri-state pattern to mirror)

**Recommendation:** Defer to a follow-up task focused on report renderer parity.

---

### P-15 — `total_cost > 0` cost-hide pattern (4 sites)

**Source:** review-silent-failures #7.

**Issue:** Pre-existing Task 108 pattern. 4 code sites hide the cost line entirely when `total_cost == 0.0`:
- `src/pflow/execution/formatters/success_formatter.py:254`
- `src/pflow/cli/workflow_output.py:467`
- `src/pflow/core/trace_report.py:590,1051`

A workflow that legitimately costs $0 (free-tier model, fully cached, mocked) silently skips the cost line, indistinguishable from "we forgot to show cost." The `pricing_available: False` branch handles unpriced models, but `pricing_available: True AND cost == 0.0` shows nothing.

**Why deferred:** Pre-existing pattern that pre-dates this branch. Fixing it is a separate concern about cost-display consistency across all rendering paths. Not introduced by Phase A.

**Files to read first:** the 4 sites listed above.

**Recommendation:** Defer to a dedicated cost-display task.

---

### P-16 — `prep` `ValueError` for missing image / `_validate_timeout` bare `ValueError`

**Source:** review-agent-ux #9, #10.

**Issue:** Two sites in `src/pflow/nodes/llm/llm.py` raise vanilla `ValueError`:

- `prep()` line ~206: `raise ValueError(f"Image file not found: {img}\nPlease ensure the file exists at the specified path.")`. Per `nodes/CLAUDE.md`: "Prefer `PflowError` subclasses over vanilla `ValueError`/`Exception`." Also doesn't include cwd context — agent can't compute the resolved path.

- `_validate_timeout()` line ~115-117: `raise ValueError(f"Timeout must be a positive number, got {timeout!r}")`. Same anti-pattern, no node ID context.

**Possible fix:** Convert to `PflowError` subclasses. Could be `UserFriendlyError` or a new typed subclass. Add cwd context to image-not-found.

**Why deferred:** This is a node-error consistency follow-up that should happen across nodes (not just LLM). Other nodes likely have similar `ValueError` anti-patterns; fixing only LLM creates uneven contract. Worth a dedicated audit.

**Files to read first:**
- `src/pflow/nodes/llm/llm.py:prep()` (specifically the image-not-found path)
- `src/pflow/nodes/llm/llm.py:_validate_timeout()`
- `src/pflow/nodes/CLAUDE.md` (the "Prefer PflowError subclasses" rule)

**Recommendation:** Defer to a node-error-consistency task that audits all nodes.

---

## Open user-decisions (carried over from §33)

These don't block code-review or PR creation, but the user has to decide before merge.

### UD-1 — CHANGELOG version label

**Issue:** `docs/changelog.mdx` Unreleased entry is currently labeled `<Update label="April 2026" description="Unreleased" tags={["Improvements", "Breaking changes"]}>`. The convention of past entries is to use a version number (`v0.12.0`, `v0.11.0`, etc.). User has to decide:

- (a) Bump to `v0.13.0` (or appropriate semver) and merge.
- (b) Keep as `Unreleased` until Phases B-G land too, ship it all together as a bigger version.

**Why this is a user-decision:** It's a release-process call, not a technical one. The auto-memory's "generate-changelog operating prefs" mention "major bump needs explicit version_type" — this is in that territory.

**Recommendation:** Ask the user before PR.

---

### UD-2 — Gemini PR #15226 fix re-verification on 1.82.6

**Issue:** Phase 0 spike (§27) verified the Gemini double-counting cost bug fix (LiteLLM PR #15226, merged 2025-10-07) was present in `litellm==1.83.7` via a live API call. Then Phase A.1 had to downgrade to `litellm==1.82.6` (due to click 8.1.8 hard-pin issue in 1.83.x) — release-date-inferred to ALSO contain the fix, but never directly verified on 1.82.6.

**Cost to verify:** ~$0.001 spike. One Gemini API call with `cache_control`, compare LiteLLM's `response_cost` to hand-calc from raw cache tokens.

**Why this is a user-decision:** Optional audit-trail conversion. The release-date inference is sound; verifying just upgrades inference to direct evidence. If Phase B-G's analyze-cache feature ends up depending on accurate Gemini cost reporting, this becomes more important.

**Recommendation:** Ask the user before merge. The spike is cheap; if user wants the audit trail, easy to do.

---

## Non-issues (verified clean during honesty pass)

For completeness, here are the things I checked that turned out NOT to be loose ends:

- **Architectural seal:** `grep -rn 'import litellm\.exceptions' src/pflow/` returns exactly 1 match (`core/llm_client.py:35`). ✓
- **Rename radius:** All 24 `_trace_collector` → `__trace_collector__` sites updated. The load-bearing filter at `workflow_trace.py:313` is correct. The test `test_workflow_trace.py:174` asserts the renamed key is filtered. ✓
- **Discriminator-loss pattern fully closed:** Every error path in `LLMNode` now writes `_diagnostic_context` with structured fields. Tests assert on `_diagnostic_context["reason"]` / `_diagnostic_context["kind"]` directly, not on prose. ✓
- **`UnknownModelError`'s `to_diagnostics()` "your key supports X" hint:** wrapped in `contextlib.suppress(Exception)` around lazy `llm_config` import. Verified test that exercises the detected-key branch (`test_unknown_model_with_detected_key_shows_supports_tip`). ✓
- **`_propagate_error_to_shared` correctly handles all 4 error paths:** _call_llm typed-catch, FuturesTimeoutError, exec_fallback, JSON-parse failure. Each path tested. ✓
- **`__warnings__` write via `setdefault` correctly routes to root** through NamespacedSharedStore's dunder-bypass dispatch. Verified by existing `__warnings__` tests still passing post-implementation. ✓
- **`parse_structured_response` model arg threading:** all 3 callers updated (`registry/discovery.py`, `registry/smart_filter.py`, `core/workflow/discovery.py`). ✓
- **Smart_filter umbrella correctness:** `(LLMCallError, ConnectionError, OSError)` — covers every `litellm.exceptions.*` (all subclasses of `LLMCallError` post-Step-2) plus cold network errors. Programming errors propagate. ✓
- **`make check` clean:** ruff, ruff-format, mypy, deptry. ✓

---

## How to use this document

1. **Read this document fully.**
2. **Read `progress-log.md` §34** for full implementation context.
3. **Read `phase-A-completion-plan.md`** if you want the why behind any specific design choice.
4. **Discuss the recommendation table at the top with the user.** Don't fix things silently.
5. **Most likely path:** fix LE-1 through LE-5 before code-review (Task #5 in the task list); decide UD-1/UD-2 with user; defer P-12 through P-16 to follow-ups; then proceed to code-review with 3-4 agents.
6. **Less likely path:** if the user wants minimal intervention, just fix LE-1 (the integration test gap is the only true regression risk) and proceed.
7. **Update this document as items get fixed** so the history is preserved.
