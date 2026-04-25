# Deferred Findings from Phase A Code Review (2026-04-25)

## What this document is

In the 2026-04-25 session, `/code-review` was run against the full Phase A branch with 6 specialized agents (`review-silent-failures`, `review-concurrency-safety`, `review-impact-completeness`, `review-test-fidelity`, `review-feature-interactions`, `review-agent-ux`). Plus 3 plan-review agents on item 3's design. Together these surfaced ~30 distinct findings.

Twelve findings were consolidated into action items and addressed in 6 commits — see `progress-log.md` §31 for the summary. This document captures **everything else**: findings that were either intentionally deferred, downgraded, partially fixed, or out-of-scope. The next agent (likely the one doing the follow-up code review or PR prep) decides what to fix; this document preserves the reasoning so they don't have to rediscover it.

**Read order:**
1. This document — to understand the deferred surface
2. `progress-log.md` §31 — for what was already done
3. `braindump-phase-A-review-handoff-2026-04-25.md` — for the original review angles before fixes
4. The plan file at `/Users/andfal/.claude/plans/magical-swinging-taco.md` for item 3's design rationale (if questions arise)

## Conventions

Each finding has:
- **What** — the issue
- **Where** — file:line, exact
- **Found by** — which review agent(s)
- **Why it matters** — impact and second-order consequences
- **Status** — `Not addressed` / `Pre-existing` / `Partially addressed` / `Verified clean`
- **Risk if fixed wrong** — what could break
- **Effort** — small / medium / large
- **Recommendation** — my prioritization with reasoning, but the call is yours

The order within each section is roughly highest→lowest priority by my read.

---

## Quick-scan summary

| # | Finding | Category | Effort | Priority |
|---|---|---|---|---|
| 1 | `test_llm_config_provider_detection.py` module docstring stale | Doc cleanup | XS | Quick win |
| 2 | `test_llm_integration.py` skip-reason text + dead OR-branch | Doc cleanup + minor bug | XS | Quick win |
| 3 | `parse_structured_response` dead-code branch + stale docstring | Code cleanup | XS | Quick win |
| 4 | `test_relative_file_path` weak assertion | Test improvement | XS | Quick win |
| 5 | CHANGELOG note for `pflow report ## Prompt` improvement | Doc | XS | Quick win |
| 6 | PATTERN EXCEPTION scope only catches `BadRequestError` | Adapter design | M | Worth discussing |
| 7 | Trace JSON `total_cost_usd` silently zeros None | Reporting | S | Worth fixing |
| 8 | `smart_filter` `except Exception` swallows new typed errors | Error handling | S-M | Worth discussing |
| 9 | `parse_structured_response` raises bare `ValueError` on empty response | Error typing | S | Worth fixing |
| 10 | Dead `thinking_tokens` aggregation in `core/metrics.py` | Dead code | S | Defer to focused cleanup |
| 11 | Parallel batch LLM per-item prompt indexing | Tracing limitation | L | Defer (separate task) |
| 12 | `AdapterResponse` should expose `finish_reason` + `reasoning_content` | Adapter API | M | Defer to Phase B-G |
| 13 | `_normalize` lacks IndexError guard on `raw.choices[0]` | Defensive | XS | Low value (rare) |
| 14 | `model_options` overrides `reasoning_kwargs` silently | Adapter behavior | XS | Document only |
| 15 | `LLMCallError` wraps LiteLLM error in JSON envelope | UX polish | S | Risky; defer |
| 16 | Two differently-shaped "Unknown model" branches | UX cosmetic | XS | Low value |
| 17 | CHANGELOG label "Unreleased" — version decision | User decision | — | Surface for PR |
| 18 | PR #15226 (Gemini cost-doubling fix) re-verification on `1.82.6` | Verification | XS | Defer to Phase B-G |

---

## Category 1 — Documentation cleanup (stale references that mislead future agents)

### Finding 1 — `test_llm_config_provider_detection.py` module docstring claims "llm CLI" tier

**Where**: `tests/test_core/test_llm_config_provider_detection.py:1-7`

**Found by**: `review-impact-completeness` #5, `review-test-fidelity` #9 (independently)

**What**: The module docstring says:
```
"""Provider detection checks env vars, settings, and llm CLI in order"""
```
plus "Priority is respected (env > settings > llm CLI)".

The `llm CLI` tier was REMOVED in Phase A.9 (`_has_llm_key()` deleted, no more `llm keys get` subprocess). The actual tests below correctly assert the new 2-tier behavior (env + settings only) — only the docstring is wrong.

**Why it matters**: Future test author reading the file gets a wrong mental model. They'll think provider detection has 3 sources when it has 2. May write a test that asserts behavior that no longer exists.

**Status**: Not addressed.

**Risk if fixed wrong**: None — pure docstring change.

**Effort**: XS (one-line fix, one paragraph rewrite).

**Recommendation**: Quick win. Bundle with other doc cleanups in a single commit.

---

### Finding 2 — `test_llm_integration.py` stale skip-reason text + dead OR-branch

**Where**: `tests/test_nodes/test_llm/test_llm_integration.py:27, 199-200, 210`

**Found by**: `review-impact-completeness` #7, `review-test-fidelity` #7 (independently)

**What**:
- Line 27: `pytest.mark.skipif` reason text says `"Run 'llm keys set openai'"` — the `llm keys set` command no longer affects pflow (A.9 removed the subprocess fallback).
- Lines 199-200: comment says "This test won't work if key is set via 'llm keys set'" — describes legacy behavior.
- Line 210: `assert "Unknown model" in error_msg or "llm models" in error_msg` — the `or "llm models"` branch is dead because A.9 changed the help text from `llm models` to `pflow settings llm show`. The test only passes via the first OR clause now.

**Why it matters**:
- Skip-reason text misleads anyone enabling `RUN_LLM_TESTS=1`.
- The dead OR-branch is an effective bug — a regression that changes the "Unknown model" wording would silently still pass on the stale dead branch. The test gives false confidence.

**Status**: Not addressed.

**Risk if fixed wrong**: Need to update assertion to `or "pflow settings llm show"`. If the actual error wording shifted further (it did in commit `96f5f3dd`), check current llm.py message exactly.

**Effort**: XS.

**Recommendation**: Quick win. The dead OR-branch is the bug worth fixing; the text changes are bonus.

---

### Finding 3 — `parse_structured_response` dead-code branching + stale docstring

**Where**: `src/pflow/core/llm_utils.py:17-19, 40`

**Found by**: `review-silent-failures` S1, `review-test-fidelity` #8, `review-feature-interactions` S2 (3 reviewers!)

**What**: Line 40 reads:
```python
text_output = response.text() if callable(response.text) else response.text
```
Pre-Phase-A this handled both Simon Willison's `llm` library `Response.text()` (callable) and any newer attribute-based shape. Post-Phase-A, `AdapterResponse.text` is always a `str` attribute — never callable. The `callable(response.text)` branch is unreachable.

Docstring at lines 17-19 says: "the LLM library normalizes all responses to have a text() method" — referencing the now-deleted `llm` library.

**Why it matters**:
- Dead code accumulates entropy. A future maintainer reading this might add another fallback branch thinking they're matching an existing pattern.
- Stale docstring lies about the contract. The function now operates on `AdapterResponse` (and accepts anything with `.text` as string for tests).

**Status**: Not addressed. Functionally harmless today (the `else` branch always fires).

**Risk if fixed wrong**: Need to verify no test creates a fake response with a callable `.text`. If they do, those tests need updating to use `AdapterResponse` directly. Quick grep should confirm.

**Effort**: XS (simplify to `text_output = response.text`; rewrite docstring).

**Recommendation**: Quick win. Bundle with #1, #2.

---

### Finding 4 — `test_relative_file_path` weakly asserts

**Where**: `tests/test_nodes/test_llm/test_llm_images.py:200-205`

**Found by**: `review-test-fidelity` #6

**What**: Compared to the original test (pre-Phase-A `llm.Attachment`), the new test only asserts `kind == "image_path"` without checking `value`. The relative-path resolution behavior (where prep converts a relative path to an absolute one via `Path(img)` + `str(path)`) is not explicitly verified.

**Why it matters**: A regression that drops `str(path)` and stores `"relative.jpg"` instead of resolving against cwd would not be caught. Other tests in the file DO assert on `value` for absolute paths and URLs; the gap is specifically the relative-path resolution case.

**Status**: Not addressed.

**Risk if fixed wrong**: Need to know what the resolved path SHOULD be in the test context. Use `Path(image_file).resolve()` or `str(image_file)` based on test setup.

**Effort**: XS (add 1-2 assertion lines).

**Recommendation**: Quick win. Real regression guard for a documented behavior.

---

### Finding 5 — CHANGELOG note for `pflow report ## Prompt` section improvement

**Where**: `docs/changelog.mdx` (current Unreleased entry)

**Found by**: Item 3 plan (mentioned but not implemented in this session)

**What**: Item 3's free fix (commit `96003f3c`) makes `event["llm_prompt"]` populate in trace JSON for every literal-prompt LLM call — and consequently `pflow report` gains the `## Prompt` section for those nodes. This was missing entirely before. The CHANGELOG should mention this user-visible improvement.

Proposed wording (from the plan):
> "the `## Prompt` section now appears in `pflow report` output for every LLM node (previously empty for nodes using literal prompts due to a thread-id mismatch in the trace_hook plumbing)."

**Why it matters**: User-visible improvement; users reading the changelog should know the trace data they get is more complete now.

**Status**: Not addressed. The Unreleased entry already covers the LiteLLM swap; the trace_hook fix could be appended in the same entry.

**Risk if fixed wrong**: None — pure docs.

**Effort**: XS.

**Recommendation**: Quick win. Worth doing before PR.

---

## Category 2 — Pre-existing silent-failure paths (made more reachable post-Phase-A)

### Finding 6 — PATTERN EXCEPTION scope only catches `BadRequestError`

**Where**: `src/pflow/core/llm_client.py::complete()` — the `except litellm.exceptions.BadRequestError` block

**Found by**: `review-silent-failures` W2, also flagged in original Phase A handoff §3

**What**: The adapter's PATTERN EXCEPTION conversion (raises `LLMCallError` from typed `BadRequestError`) only covers `BadRequestError` and its subclasses (`UnsupportedParamsError`, `ContentPolicyViolationError`, `ContextWindowExceededError`, `InvalidRequestError`).

Other deterministic LiteLLM exceptions are NOT caught:
- `litellm.exceptions.AuthenticationError` (wrong/missing key)
- `litellm.exceptions.NotFoundError` (unknown model)
- `litellm.exceptions.PermissionDeniedError`
- `litellm.exceptions.JSONSchemaValidationError` (subclass of `APIResponseValidationError`, NOT of `BadRequestError`)

These propagate from the adapter to LLMNode's exec → Node retry loop catches `Exception` → retries 3x → exec_fallback finally produces a friendly message.

**Why it matters**:
- **Cost**: every retry burns input tokens, time, and rate-limit pressure on a permanent failure. For a missing API key, that's 3 separate failed API calls (or 3 immediate local raises depending on where Auth fails).
- **UX**: user waits ~30+ seconds for retries to exhaust before seeing the friendly error.
- **Pre-existing**: this isn't a regression — the legacy `llm` library code had the same problem. The Phase A.5 PATTERN EXCEPTION explicitly only covered `BadRequestError` because that was the equivalent of the old `Pydantic ValidationError`.

**The expansion is now CHEAP**: Item 2's Option F design means the adapter raises `LLMCallError` for `BadRequestError`. Adding more `except` branches for other deterministic exceptions is mechanical:

```python
# in complete(), additional branches
except (
    litellm.exceptions.BadRequestError,
    litellm.exceptions.AuthenticationError,
    litellm.exceptions.NotFoundError,
    litellm.exceptions.PermissionDeniedError,
) as e:
    err_msg = f"LLM call failed for model '{model}': {e}"
    _emit_trace(...)
    raise LLMCallError(err_msg) from e
```

**Important nuance**: the friendly messages currently produced by `exec_fallback` (e.g. "Unknown model: X. Tip: ... Run 'pflow settings llm show'") would no longer fire because the exception path changes. To preserve them, either:
- Move the friendly-message construction INTO the adapter (less ideal — adapter knows about CLI commands)
- Have LLMNode's `try/except LLMCallError` introspect the original cause (`e.__cause__`) and produce the friendly message there

The second approach is cleaner. LLMNode can do:
```python
except LLMCallError as e:
    cause = e.__cause__
    if isinstance(cause, litellm.exceptions.NotFoundError):
        # ... build "Unknown model" friendly message
    elif isinstance(cause, litellm.exceptions.AuthenticationError):
        # ... build "API key required" friendly message
    else:
        error_detail = str(e)
    return {"response": "", "error": error_detail, ...}
```

**Status**: Not addressed. Pre-existing.

**Risk if fixed wrong**:
- The friendly-message preservation is the tricky part. Tests currently verify those exact strings ("Unknown model: bad-model", "API key required") in `test_llm.py`. The refactor must preserve them.
- Some `BadRequestError` cases might be transient at the proxy level (e.g. a 400 from a flaky LLM gateway). The PATTERN EXCEPTION assumes deterministic. If we expand to more exception types, we need to verify each is truly deterministic.
- `litellm.exceptions.APIError` is a parent of many of these; could over-catch.

**Effort**: M (~2-3 hours including test updates and verification).

**Recommendation**: **Worth discussing with the user before implementing.** The cost (wasted retries) is real but pre-existing. Phase A.5 explicitly scoped the catch narrowly. Decision: expand scope (cleaner UX, slightly more risk) or leave as a known limitation (matches legacy behavior). Don't silently expand the scope without aligning on the design.

---

### Finding 7 — Trace JSON `total_cost_usd` silently zeros None

**Where**:
- `src/pflow/runtime/workflow_trace.py:405, 419, 429, 440`
- `src/pflow/core/trace_report.py:181, 191`

**Found by**: `review-silent-failures` W4, `review-impact-completeness` #10 (independently)

**What**: The trace's `llm_summary` aggregation does:
```python
total_cost += event["llm_call"].get("cost_usd", 0) or 0
```
The `or 0` collapses `None` to `0.0`. So if any LLM call has `cost_usd: None` (LiteLLM doesn't price the model — Ollama, custom endpoints, brand-new models), the per-call None silently summed as 0 in the trace JSON's `total_cost_usd` field.

**Why it matters**:
- **Pre-existing pattern** — this was the case before A.10 too — but was less reachable because the deleted `MODEL_PRICING` table covered most common models. Post-A.10, LiteLLM returns `None` for any model it doesn't recognize, which is a much broader class.
- **CLI summary handles it correctly**: `MetricsCollector.calculate_costs` distinguishes None from 0.0 via `pricing_available: False` and `partial_cost_usd`. The user-visible CLI summary correctly says "Cost unavailable — pricing data missing for: ...".
- **Trace JSON consumer divergence**: anyone reading the raw trace file directly (third-party tooling, log analyzers, future analyze-cache feature) gets `total_cost_usd: 0.0` instead of `null`/`None` with no flag for "we don't have pricing for some calls". They might compute averages, percentages, etc. against a misleading zero.

**Fix shape**: Mirror `MetricsCollector.calculate_costs` semantics. When any per-call `cost_usd` is None:
```python
# in _collect_llm_summary
unavailable_models: set[str] = set()
total_cost: float = 0.0
for event in events:
    cost = event.get("llm_call", {}).get("cost_usd")
    if cost is None:
        unavailable_models.add(event["llm_call"].get("model", "unknown"))
    else:
        total_cost += cost

summary["total_cost_usd"] = total_cost if not unavailable_models else None
summary["partial_cost_usd"] = total_cost if unavailable_models else None
summary["unavailable_models"] = sorted(unavailable_models) if unavailable_models else []
```

**Status**: Not addressed. Pre-existing but more reachable.

**Risk if fixed wrong**: Trace format change. Adding new fields is safe (forward-compat); changing `total_cost_usd` from float to `null` would break consumers expecting always-numeric. Use the metrics-mirror shape (add `partial_cost_usd` + `unavailable_models`; keep `total_cost_usd` as the unambiguous "all calls priced" value).

**Effort**: S (~1 hour with tests).

**Recommendation**: **Worth fixing.** The fix shape is established (mirror metrics.py). Surfacing the divergence cleanly helps Phase B-G's analyze-cache work which will read trace data.

---

### Finding 8 — `smart_filter` `except Exception` swallows new typed errors

**Where**: `src/pflow/registry/smart_filter.py:223-229`

**Found by**: `review-silent-failures` W1, `review-feature-interactions` C1 (partially — feature-interactions noted Option F but didn't fully address smart_filter)

**What**:
```python
try:
    # ... call complete() + parse_structured_response ...
except Exception as e:
    logger.warning(
        f"Smart filter failed, returning all {len(fields)} fields unfiltered: {e}",
        extra={"error_type": type(e).__name__, "error_message": str(e)},
    )
    return fields
```

This catches ALL exceptions including:
- `LLMCallError` (NEW, from item 2's adapter pattern) — deterministic provider error like bad model name
- `litellm.exceptions.AuthenticationError` — missing key
- `litellm.exceptions.NotFoundError` — unknown model
- Network errors, parse errors, anything else

The "intentional graceful degradation" semantic was: if smart filtering fails, return all fields rather than blocking the whole workflow. That's reasonable for what smart_filter is (a best-effort optimization).

**Why it matters now**:
- Item 2's Option F means more error paths now flow through this silencer. Previously the adapter's error-marked response was a known-shape signal; now it's a typed exception.
- A user with NO API key configured AT ALL would see smart_filter silently degrade to returning all 200 fields, with only a `logger.warning` (which most users don't see) → confusing experience because they don't know LLM-based filtering failed.
- A user typing the wrong model name in smart_filter settings would get the same silent degradation.

**Pre-existing pattern** — this isn't a Phase A regression — but it's worth deciding whether to:
- Keep as-is (best-effort intentional)
- Tighten exception types (only catch `LLMCallError` + network errors; let `AuthenticationError` propagate so config issues surface loudly)
- Escalate the log level from `warning` to `error` so it appears in default CLI output

**Important context**: smart_filter is called from probe (display-only, large API responses). It's NOT in the critical path. Silent fallback IS often the right behavior for display-only operations.

**Status**: Not addressed. Pre-existing.

**Risk if fixed wrong**: Tightening the catch could surface failures that were previously silent and acceptable. Need to identify which exception types represent "config errors that user should see" vs "runtime errors that smart_filter should tolerate".

**Effort**: S (decide policy + implement) to M (if more discussion needed).

**Recommendation**: **Worth discussing with the user.** The current behavior is defensible but the silent degradation surface is wider now. At minimum, log at `error` level for `AuthenticationError` / `NotFoundError` so config issues are visible without changing the fallback.

---

### Finding 9 — `parse_structured_response` raises bare `ValueError` on empty response

**Where**: `src/pflow/core/llm_utils.py:42-43`

**Found by**: Implicit in `review-silent-failures` W1 (smart_filter context) + new context from item 10

**What**: When the LLM response has empty text (e.g. reasoning model with `max_tokens` too low — see item 10's empty-response warning), `parse_structured_response` raises:
```python
raise ValueError("Response parsing failed: LLM returned empty response")
```

This is a bare `ValueError`, not a typed `LLMCallError`. Discovery callers (`find_components` in `registry/discovery.py`, `find_workflow` in `core/workflow/discovery.py`) don't catch it specifically — it propagates as `ValueError` to the workflow runtime which surfaces as a generic execution error.

**Why it matters now**:
- Item 10 added a `logger.warning` for the reasoning-model empty-response case but the downstream parsing still raises `ValueError`. The warning + raise are independent.
- With the adapter's other deterministic errors going through `LLMCallError` (item 2 Option F), this is the inconsistent one. Discovery callers' error handling can't distinguish "LLM returned empty" from "LLM returned malformed JSON" from "schema mismatch" — all are bare ValueError.
- For Phase B-G when caching becomes a real feature, distinguishing error classes matters more.

**Fix shape**: Convert the empty-response raise to `LLMCallError`:
```python
if not text_output:
    raise LLMCallError("LLM returned empty response (likely max_tokens too low for reasoning model)")
```

Could also do the same for the JSON parse failure right below it.

**Status**: Not addressed.

**Risk if fixed wrong**: Discovery callers currently catch `Exception` (smart_filter) or let it propagate (`find_components`, `find_workflow`). Switching to `LLMCallError` doesn't change that. Tests asserting on `ValueError` would need updating — there are some in `tests/test_core/` (need to grep).

**Effort**: S (~30 min including test updates).

**Recommendation**: **Worth fixing** to keep error-typing consistent. Pairs naturally with finding #6 (PATTERN EXCEPTION expansion).

---

## Category 3 — Pre-existing dead code

### Finding 10 — Dead `thinking_tokens` aggregation in `core/metrics.py`

**Where**: `src/pflow/core/metrics.py:110, 156, 188-197, 250-252`

**Found by**: `review-impact-completeness` #11

**What**: `MetricsCollector` aggregates `thinking_tokens` and `thinking_budget` from `llm_usage` dicts:
```python
self.thinking_tokens += usage.get("thinking_tokens", 0) or 0
self.thinking_budget += usage.get("thinking_budget", 0) or 0
```
And there's a derived `thinking_performance` summary section.

But **no production code WRITES `thinking_tokens` or `thinking_budget` to `llm_usage`**:
- LLMNode's `post()` builds `llm_usage` with: `model, input_tokens, output_tokens, total_tokens, cache_creation_input_tokens, cache_read_input_tokens, cost_usd` — that's it. No thinking fields.
- ClaudeCodeNode's path also doesn't write these.
- The adapter's `_normalize` doesn't surface them (the code comment says "We do not surface it in AdapterResponse").

So the aggregation reads keys that are never present. `thinking_tokens` always sums to 0. The `metrics["thinking_performance"]` summary will never appear in real CLI output.

This is ~30+ lines of pre-existing dead code. The `test_thinking_cost_calculation` test that USED to verify pricing-math for thinking tokens was deleted in A.10 (it tested deleted pricing internals), but the aggregation it would have validated wasn't touched.

**Why it matters**:
- Maintenance burden — future maintainer reading this code thinks it's load-bearing.
- Confused signals — if someone DOES start writing `thinking_tokens` in future work, the existing aggregation would silently start working with no test coverage.

**Status**: Pre-existing dead code, not addressed.

**Risk if fixed wrong**: Need to verify the dead path conclusion by grep:
```bash
grep -rn '"thinking_tokens"\|"thinking_budget"' src/pflow/
```
If only metrics.py reads them (no writers), safe to delete the aggregation + summary section.

**Effort**: S (~30 min — focused deletion + test cleanup).

**Recommendation**: **Defer to a focused cleanup task.** Not Phase A scope. Worth its own commit so the deletion rationale is clear in history.

---

## Category 4 — Architectural / longer-term tracing concerns

### Finding 11 — Parallel batch LLM per-item prompt indexing

**Where**: `src/pflow/runtime/workflow_trace.py::WorkflowTraceCollector.llm_prompts` (the data structure) + `src/pflow/runtime/engine/batch_executor.py::_capture_item_trace` (the consumer)

**Found by**: `review-concurrency-safety` W6, `review-impact-completeness` W4 (independently — both reviewing item 3's design and finding the same gap)

**What**: `collector.llm_prompts[node_id]` keys by node_id. In a parallel batch where each item is a single LLM call:
1. Engine sets `_pflow_current_node = batch_node_id` (the batch wrapper's id)
2. Each batch worker calls `_execute_single_node` → `LLMNode.prep` → reads `node_id = self.node_id` which is the BATCH wrapper's id (same id for all items because they share the deepcopy'd node)
3. Each item's trace_hook writes to `collector.llm_prompts[batch_node_id]` — last write wins
4. `_capture_item_trace` (which builds per-item event dicts in `batch_items[]`) reads `prompt` from `node_output.get("prompt")` — but LLMNode never writes "prompt" to shared
5. Net: only one prompt visible, possibly the last one's, possibly none

**Important: this is PRE-EXISTING. Not introduced by item 3.** The original code had the same problem (worker thread mismatch was a separate bug; the keying-by-node-id bug existed regardless).

**Item 3 plan originally proposed test #4 to assert per-item capture works, but BOTH plan-review reviewers caught the assertion would fail. Test was REMOVED before implementation.**

**Why it matters**:
- For batch LLM nodes (batch of LLM calls, NOT batch of sub-workflows), per-item prompts are missing from traces.
- For batch of SUB-WORKFLOWS containing LLMs (the case we DID test in test #4), per-item prompts work correctly because each sub-workflow has its own collector + its own llm_prompts dict.
- For Phase B-G's analyze-cache feature, batch LLM call patterns are common (chorus-chooser does 34 parallel scoring calls). If we want per-item cache analysis, this matters.

**Fix shapes** (two options, NOT in scope here):

**Option A**: Write the rendered prompt to `node_output["prompt"]` from `LLMNode.post()`. Then `_capture_item_trace`'s existing fallback (`node_output.get("prompt")`) works.
- Pro: minimal collector change
- Con: changes shared-store contract (LLMNode now writes a `prompt` key); could collide with template params

**Option B**: Key `collector.llm_prompts` by `(node_id, batch_idx)` tuples. Then each item gets its own slot.
- Pro: clean abstraction
- Con: changes the collector's data structure; affects `_add_llm_data` reader; requires propagating `batch_idx` through prep_res

**Status**: Pre-existing limitation, NOT addressed by item 3, intentionally documented.

**Risk if fixed wrong**: The existing tests that work with batch LLM node traces would need updating. Some tests assert on `batch_items[i]["llm_prompt"]` being absent — would need to flip to expecting it present.

**Effort**: L (~4-6 hours including design choice + tests).

**Recommendation**: **Defer to a separate task.** Phase B-G work that needs per-item batch prompt visibility should drive this. Until then, document as a known limitation in `runtime/CLAUDE.md` or similar.

---

### Finding 12 — `AdapterResponse` should expose `finish_reason` and `reasoning_content`

**Where**: `src/pflow/core/llm_client.py::AdapterResponse` dataclass + `_normalize` function

**Found by**: `review-silent-failures` S3

**What**: `_normalize` reads `raw.choices[0].message.content` and `raw.choices[0].finish_reason` from the LiteLLM response, but the latter is only used internally for the empty-response warning (item 10). The dataclass exposes only `text`, `usage`, `model`, `has_schema`. Specifically NOT exposed:
- `finish_reason: str | None` — useful for debugging "why did the response end" (length, stop, content_filter, max_tokens, ...)
- `reasoning_content: str | None` — the model's reasoning trace (Anthropic's extended thinking, OpenAI's reasoning summary, etc.) — currently silently dropped

**Why it matters**:
- For Phase B-G's prompt caching analysis, knowing why a call terminated (e.g. content_filter cutting off mid-output) might be useful diagnostic data.
- For trace richness, surfacing `finish_reason` in trace JSON would help users debug truncation issues without re-running.
- For the reasoning-model trap (item 10), exposing `reasoning_content` would let users see WHAT the model was thinking even when it produced no visible output — potentially useful for tuning `max_tokens`.

**Constraint**: Adding fields to `AdapterResponse` is a contract change. All consumers (LLMNode, MockLLMClient, tests building inline AdapterResponse) need updating.

**Status**: Not addressed. Item 10 surfaces the reasoning-trap via `logger.warning` but doesn't expose the data structurally.

**Risk if fixed wrong**: Forward-compatible additions. Adding optional fields with defaults shouldn't break existing consumers. Trace format would gain fields (which it tolerates per `format_version.startswith("2.")` gate).

**Effort**: M (~2 hours including AdapterResponse update, MockLLMClient parity, test fixture updates, optional trace format extension).

**Recommendation**: **Defer to Phase B-G.** Phase A's contract is "successful response only" and current consumers don't need this. Adding fields preemptively is exactly the over-engineering we want to avoid. When a real Phase B-G use case materializes, add them then.

---

## Category 5 — Defensive / edge cases (low priority)

### Finding 13 — `_normalize` lacks IndexError guard on `raw.choices[0]`

**Where**: `src/pflow/core/llm_client.py::_normalize` first line

**Found by**: `review-silent-failures` S2

**What**: `msg = raw.choices[0].message` — no guard. If a provider/proxy ever returned `choices=[]` (some Azure/proxy misconfigurations can do this), this raises `IndexError` with no friendly translation. The `IndexError` propagates through Node retry loop → 3 retries → `exec_fallback` produces "LLM call failed after 3 attempts".

**Why it matters**:
- Extremely rare on direct provider calls.
- Worst case: 3 wasted retries on a permanent shape error before user sees a confusing message.

**Status**: Not addressed.

**Risk if fixed wrong**: Trivial — just guard with a clear error.

**Effort**: XS.

**Recommendation**: **Low priority.** Defensive improvement with marginal value. If we expand the PATTERN EXCEPTION scope (finding #6), this could be added as another deterministic-error case (`raise LLMCallError("Provider returned no choices")`). Until then, skip.

---

### Finding 14 — `model_options` overrides `reasoning_kwargs` silently (last-write-wins)

**Where**: `src/pflow/core/llm_client.py::complete()` — the kwargs merge order

**Found by**: `review-feature-interactions` W2

**What**: The adapter merges in this order:
```python
kwargs.update(translated_reasoning)  # from reasoning_kwargs
if model_options:
    kwargs.update(model_options)  # last write wins
```
If a caller passes BOTH `reasoning_effort: "high"` (which gets translated to `thinking_level: high` for Gemini-3) AND `model_options.thinking_level: "low"`, the `model_options` value silently wins. No warning, no error.

**Why it matters**:
- Documented in the docstring (line 154-155: "merged last so they can override anything").
- Theoretical hazard today: no caller passes both. But `smart_filter` flows `thinking_level=minimal` via `model_options` (`smart_filter.py:175-176`). If a future caller layered `reasoning_kwargs={"thinking_level": "high"}` on top, the heuristic would silently win without anyone noticing.
- For Phase B-G when more callers might use both knobs, the hazard becomes more real.

**Status**: Not addressed. Documented in docstring.

**Risk if fixed wrong**: If we add a warning for the collision case, false positives could spam logs (same key set twice for legitimate reasons).

**Effort**: XS (just add to docstring more prominently) to S (add collision detection + warning).

**Recommendation**: **Document only in CLAUDE.md, no code change.** The behavior is already documented in the function's docstring. Adding collision detection is over-engineering until we have a real case where it matters.

---

### Finding 15 — `LLMCallError` wraps LiteLLM error in JSON envelope (UX polish)

**Where**: `src/pflow/core/llm_client.py::complete()` — the BadRequestError branch raises `LLMCallError(f"Invalid request for model '{model}': {e}")`

**Found by**: Surfaced during item 9 spike investigation

**What**: When BadRequestError fires, the adapter wraps the str(exception) into `LLMCallError`. The result looks like:
```
Invalid request for model 'anthropic/claude-opus-4-5':
litellm.BadRequestError: AnthropicException - {"type":"error","error":
{"type":"invalid_request_error","message":"`temperature` may only be set to 1
when thinking is enabled. Please consult our documentation at https://...."},
"request_id":"req_..."}
```

The actionable message (`temperature may only be set to 1...`) is buried inside a JSON envelope. Could be cleaner.

**Why it matters**:
- Users see this error string in pflow's error output.
- The signal-to-noise ratio is mediocre — they have to skim past the JSON wrapper to find the WHAT/HOW.

**Fix shape**: Parse the JSON envelope and extract the `error.message` field. But:
- LiteLLM's exception message format is provider-dependent — Anthropic uses one envelope, OpenAI another, Gemini a third.
- Parsing risks breaking when LiteLLM/providers change formats.
- The existing message IS technically accessible, just noisier than ideal.

**Status**: Not addressed.

**Risk if fixed wrong**: If we parse the JSON and a provider changes the envelope shape, we silently lose the parsing and fall back to the raw string — but only if we wrap parsing in try/except. Worth the complexity? Probably not.

**Effort**: M (parsing logic + per-provider tests).

**Recommendation**: **Defer or skip.** The actionable text IS in there. Cleaning up the envelope is polish; the cost (provider-format coupling) outweighs the benefit. If users complain about specific error messages, address those individually.

---

### Finding 16 — Two differently-shaped "Unknown model" branches

**Where**: `src/pflow/nodes/llm/llm.py::exec_fallback` — the NotFoundError branch and the BadRequestError "LLM Provider NOT provided" branch

**Found by**: `review-agent-ux` #10

**What**: There are now TWO branches that handle "user typed wrong model identifier":
- `NotFoundError`: "Unknown model: X. Tip: Your API key supports 'Y'. See https://docs.litellm.ai/docs/providers..."
- `BadRequestError` with "LLM Provider NOT provided": "Unknown model/provider: X. Use a provider prefix..."

For an agent, these read as different problems but root-cause is the same: the model identifier is wrong. The user-facing distinction (NotFoundError vs BadRequestError-with-specific-substring) is opaque — it's a LiteLLM internal detail.

**Why it matters**: Cosmetic. Agent has slightly more work to recognize both branches as the same class of issue.

**Status**: Not addressed.

**Risk if fixed wrong**: Consolidating the two branches could lose the specific "use a provider prefix" hint when the issue is provider-prefix omission specifically.

**Effort**: XS-S (merge the branches with a unified message).

**Recommendation**: **Low value, skip** unless cleaning up `exec_fallback` for other reasons.

---

## Category 6 — User decisions

### Finding 17 — CHANGELOG label "Unreleased" — version decision

**Where**: `docs/changelog.mdx:8`

**Found by**: `review-agent-ux` #11, original session §30 loose end

**What**: All existing changelog entries have version numbers (`v0.12.0`, etc.). The Phase A entry is currently labeled `description="Unreleased"`. Two options:
- Phase A merges with its own version bump (`v0.13.0` or `v0.12.1`)
- Hold "Unreleased" until full Task 158 (Phases B-G) ships, then backfill the label

**Why it matters**: Convention break. Anyone reading the changelog expects version numbers.

**Status**: Pending user decision.

**Recommendation**: Surface during PR prep. The user decides.

---

### Finding 18 — PR #15226 (Gemini cost-doubling fix) re-verification on `1.82.6`

**Where**: `pyproject.toml` LiteLLM pin

**Found by**: `review-feature-interactions` W4, original Phase A handoff §5

**What**: Phase 0 spike verified Gemini PR #15226 cost-doubling fix is present in `litellm==1.83.7`. Phase A.1 had to downgrade to `1.82.6` because every release in the `1.83.x` series hard-pins `click==8.1.8` (which broke 3 CliRunner-based tests). The Gemini fix verification on `1.82.6` was NOT explicitly re-done.

The single-call smoke test against Gemini-3 (Phase A.12) confirmed that `cost_usd` populates and matches expected — but didn't test the SPECIFIC bug (two identical Gemini cached calls reporting different costs).

**Why it matters**:
- Phase B-G's analyze-cache feature will rely on accurate Gemini cost reporting. If the fix isn't actually present in 1.82.6, Phase C's cache-cost calculations would be wrong.

**Verification**: Easy — fire two identical `gemini/gemini-2.5-flash` calls with `cache_control` enabled, compare LiteLLM's `response_cost` values. If they're proportional to actual token usage (not double-counted), fix is present.

Spike script template:
```python
import litellm
litellm.suppress_debug_info = True

resp1 = litellm.completion(
    model="gemini/gemini-2.5-flash",
    messages=[
        {"role": "system", "content": [
            {"type": "text", "text": "<long stable system prompt>" * 100,
             "cache_control": {"type": "ephemeral"}},
        ]},
        {"role": "user", "content": "Reply with OK."},
    ],
    temperature=0,
)
resp2 = litellm.completion(...)  # identical

print(f"Call 1 response_cost: {resp1._hidden_params.get('response_cost')}")
print(f"Call 2 response_cost: {resp2._hidden_params.get('response_cost')}")
print(f"Cache_creation tokens (call 2): {resp2.usage.prompt_tokens_details.cached_tokens}")
# Manual calc: cached_read_tokens × $0.0375/1M (gemini cache rate) + new tokens × full rate
# Should match response_cost within rounding error.
```

**Status**: Not addressed. Documented as deferred.

**Risk if fixed wrong**: If the fix isn't present, we'd need to either (a) bump LiteLLM to a version with the fix that doesn't pin click 8.1.8 (may not exist yet), (b) keep `1.82.6` and add Gemini cost compensation in pflow, or (c) accept the bug for Gemini-cached scenarios in Phase B-G.

**Effort**: XS to verify (~10 min spike + ~$0.001 in API calls).

**Recommendation**: **Defer to Phase B-G plan writing.** This becomes load-bearing when caching feature work starts. Add a verification spike to that plan.

---

## Cross-cutting observations for Phase B-G

These aren't deferred findings per se — they're insights from the reviews that future phase work should keep in mind:

### The trace_hook is now USABLE for cache instrumentation

Pre-Phase-A-cleanup the trace_hook was non-functional (never fired). Item 3 made it actually work. Phase B-G's prompt-caching feature can now reliably:
- Capture rendered cache content via `before_call.prompt` events
- Instrument cache write/read events through the same channel
- Add structured cache metadata to trace events

The seam: `WorkflowTraceCollector.get_trace_hook(node_id)` returns a callable; the adapter invokes it with `{"event": "before_call"|"after_call", ...}` dicts. Hook exceptions are swallowed safely (`_emit_trace` in `core/llm_client.py`). Adding new event types (e.g. `cache_write`, `cache_hit`) is forward-compatible.

### `_trace_collector` shared-store seam is the established pattern

For any new runtime-service-needed-by-nodes (e.g. cache analyzer state, prefix detector state), follow the established pattern:
1. Add the service to shared at engine setup time (runner.py:490 model)
2. Or via save/restore in engine.run for per-execution-context isolation
3. Add to `_PROPAGATED_KEYS` in workflow_executor.py if children should inherit
4. Use single-underscore prefix for internal pflow services (matches `_trace_collector`, `_pflow_*`)

### `node.node_id` is the canonical way for nodes to know themselves

Set by compiler at `compiler.py:299`. Used by engine via `getattr(curr, "node_id", None)`. Now also used by LLMNode.prep to find its own id. Future nodes that need self-identification (cache key derivation, prefix sharing, etc.) should follow the same pattern: `getattr(self, "node_id", None)`.

### NamespacedSharedStore lacks `pop` — design gotcha for shared-store-key save/restore

Discovered during item 3 implementation. Sub-workflow `storage_mode: shared` uses a `NamespacedSharedStore` proxy that doesn't implement `pop` or `__delitem__`. Any save/restore pattern using `.pop()` will crash on those sub-workflows. Use unconditional write-back instead (`shared[key] = saved_value` even if `None`) — works because all consumers use `.get()`.

If a future feature genuinely needs `pop` semantics on a key visible to sub-workflows, the right fix is to add `pop` and `__delitem__` to `NamespacedSharedStore` (would be a generic improvement). Until then, write-back is the established pattern.

### PATTERN EXCEPTION pattern is reusable

The "adapter raises typed exception → consumer-in-retry-loop catches at boundary → converts to error-marked output dict" pattern (item 2 / Option F) generalizes. Future deterministic-error sources can follow the same template:
- Adapter raises typed `PflowError` subclass (add to `core/exceptions.py`)
- Consumer with retry loop wraps `try/except` at its boundary
- Consumers without retry loops let exceptions propagate naturally

---

## What was explicitly excluded from this document

To be transparent — these findings WERE flagged by review agents but I judged them stylistic, false, or irrelevant:

1. **Test consolidation suggestions** (e.g. parametrize `test_temperature_*` tests) — pure style, no correctness value. Tests work; consolidation is bloat reduction at best.

2. **`prep_res["_trace_hook"]` should use double-underscore convention** (review-concurrency-safety W2 dispute) — `__progress_callback__` is a SHARED store key (engine-internal protocol). `_trace_hook` is a function-local return value never serialized or passed cross-namespace. Single underscore is correct convention for a private dataclass-internal field.

3. **Save/restore style consistency between `_trace_collector` (write-back) and `_pflow_child_only_node` (`.pop()`)** (review-impact-completeness S1) — the inconsistency is intentional and necessary. `_trace_collector` save/restore must work on `NamespacedSharedStore` (no `pop`); `_pflow_child_only_node` save/restore only ever runs on regular dicts. Documented in the `engine.py` code comment.

4. **Engine `_execute_node` step numbering gap** (no step 1 after item 3 deletion) — preserved intentionally with an explanatory comment. Renumbering would cascade to step references in `runtime/engine/CLAUDE.md` and other comments referencing "step 17.5" / "step 16" — pure churn for no benefit.

5. **CLAUDE.md drift in 3 sites** — already addressed in commit `3aa7ed8f` and item 3's deletion commit. Not deferred.

6. **Comments mentioning `enable_llm_interception` in deleted code paths** — already cleaned up alongside the deletion.

7. **Various "Verified Safe" / "Verified Clean" observations** from the reviewers — these are confirmations that something is correct, not findings. Not action items.

---

## Recommended approach for the next agent

If you have ~30 minutes of cleanup time:
- **Do findings #1, #2, #3, #4, #5** (all "Quick win" tier in the table). These are the kind of stale-reference issues the user has explicitly called out as worth addressing. Bundle as one commit: `chore(docs): cleanup stale references flagged by Phase A code review`.

If you have ~1-2 hours and want to address real production issues:
- **Add findings #7 and #9** to the cleanup commit. Both are small with clear value.
- **Discuss finding #6 with the user before implementing** — it's a real expansion of the PATTERN EXCEPTION scope and warrants alignment.
- **Discuss finding #8 with the user** — smart_filter silent degradation is intentional but the surface is wider now.

If you're working on Phase B-G:
- **Verify finding #18 first** (Gemini cost-doubling fix on 1.82.6) — load-bearing for accurate cache cost reporting.
- **Read the "Cross-cutting observations" section** — these are the architectural patterns established by Phase A that Phase B-G should follow.
- **Finding #11** (parallel batch per-item prompts) might come up if cache analysis needs per-item visibility into batch operations.

Findings #10, #12-#16 can be deferred indefinitely — they're either pre-existing dead code (#10), forward-looking (#12), or low-value defensive/cosmetic (#13-#16).

Findings #17 (CHANGELOG version) and #18 (Gemini fix verification) need the user to weigh in.

---

## Source review reports

If you want to read the original review outputs (NOT recommended — this document covers what's actionable, the originals have a lot of "verified clean" content that's not useful for decision-making):

The 6 Phase A review agent outputs were captured inline in the conversation that produced the 12-item action plan (preserved in the working memory of session 2026-04-25, reproducible by re-invoking `/code-review` if needed).

The 3 plan-review agent outputs (for item 3) were captured similarly during the plan-mode session that produced `/Users/andfal/.claude/plans/magical-swinging-taco.md`.

For the original Phase A review handoff document that motivated the review: `.taskmaster/tasks/task_158/starting-context/braindump-phase-A-review-handoff-2026-04-25.md`.
