## 2026-05-14 — Runtime pre-dispatch strip for below-min cache markers

Closes the Gemini hard-failure footgun (`Cached content is too small. total_token_count=1135, min_total_token_count=2048`) reported in `scratchpads/pflow-caching-agent-ux-notes.md` issue #3 / GH #393.

### Problem

When `prompt_cache:` or `prewarm: true` is declared on an LLM node, the resolved cache content depends on dynamic data (CLI params, upstream LLM output, batch items). When the rendered content is below the provider's minimum, three bad things happened:

- **Gemini** rejected the call hard — workflow died after $-cost upstream work.
- **Anthropic** silently no-op'd the marker; user only learned post-call via 0/0 cache telemetry.
- The existing `_emit_observed_below_min_cache_warning` fires in `LLMNode.post()` *after* `exec()` returns — but `exec_res["status"] == "error"` triggers an early return before the warning point, so on the Gemini failure case the warning **never fired**.

### What was implemented

A pre-dispatch token check at the single seam `_assemble_cache_prep` (`src/pflow/nodes/llm/llm.py:507`). When cumulative tokens through any `cache_control`-bearing block are below `get_min_cache_tokens(model)`, the marker is stripped (`del block["cache_control"]`), the call goes out uncached, and a catalog-backed `cache.below-min-predicted` Diagnostic is emitted with new `evidence_kind="pre-send"`.

**~80 LOC across 2 production files**:
- `src/pflow/nodes/llm/llm.py` — 3 helpers (`_count_text_tokens`, `_strip_below_min_cache_markers`, `_emit_pre-send_below_min_warning`) + 9-line call into `_assemble_cache_prep`.
- `src/pflow/core/cache_analysis/warning_catalog.py` — new `_BELOW_MIN_TOKENS_MESSAGE_PRE_DISPATCH` template + entry in `_BELOW_MIN_TOKENS_DISPATCH`. No new catalog ID — extended existing `cache.below-min-predicted` with a third evidence tier.

### Why this shape

Verified by 4 parallel `pflow-codebase-searcher` runs before writing code:

1. **Thresholds are 100% hardcoded** in `llm_capabilities.py:68-91` — and they must stay that way. Empirically confirmed `litellm.model_cost` has no `min_cache_tokens` field; only `min`-containing keys are `supports_minimal_reasoning_effort` and `supports_native_streaming` (unrelated). Anthropic/Gemini don't expose minimums via SDK either. Hardcoded table is the top-10% pattern (mypy/ruff/rustc do the same for provider quirks that change quarterly).

2. **Single dispatch seam.** `_assemble_cache_prep` has exactly one production caller (`LLMNode.prep:797`). Both block-builders (system + user_message_blocks for batch prewarm) converge there. Model, provider, resolved bytes, shared store, and node_id are all in scope. No new architecture needed.

3. **DD#19 byte-identity preserved.** The memo hash (`compute_node_config(prompt_cache_content=...)`) runs in `plan_node._render_cache_for_hash` BEFORE dispatch. The strip mutates only the `cache_control` key on rendered blocks — text bytes are untouched, so memo cache_key is identical whether strip fires or not. Verified by `test_pre-send_strip_does_not_mutate_text_bytes`.

4. **Observed-tier doesn't double-emit.** After strip, the provider sees no `cache_control` markers → returns no cache telemetry fields → `has_cache_telemetry=False` at `llm.py:193` → existing observed-tier emission correctly suppresses itself. Zero coordination logic needed.

### Edge cases handled

- **Per-batch-item**: `_assemble_cache_prep` is called per-call; heterogeneous batches (some items above min, some below) get correct per-item decisions with zero coupling.
- **Multiple markers** (system + user_prefix): cumulative-token walk evaluates each marker independently. Each provider cache scope is checked against the min.
- **Unknown model**: `get_min_cache_tokens` returns `CONSERVATIVE_FLOOR=4096`. Strips aggressively for unknown models — the right default.
- **`litellm.token_counter` raises**: falls back to `len(text) // 4`. The heuristic biases toward false-strip over false-keep (Gemini rejection), the cheaper error.
- **OpenAI**: `cache_control` is already a no-op there; stripping is also a no-op. `prompt_cache_key` kwargs stay (harmless).

### Testing

- **8 new production-shape tests** at `tests/test_nodes/test_llm/test_prompt_cache_below_min_runtime.py`: below-min strips, above-min keeps, exact-threshold boundary, Gemini 4096, unknown-model floor, observed-tier no-double-emit, heuristic fallback.
- **1 new catalog test** at `test_cache_analysis_warnings.py` for the `pre-send` message template.
- **1 new hash-invariance test** at `test_prompt_cache_hash.py` proving the strip doesn't touch text bytes.
- **5 existing tests adjusted**: `test_prompt_cache_rendering.py`, `test_batch_cache_prefix.py`, `test_runner.py`, `test_no_cache_flag.py`, `test_trace_integration.py` got a one-line strip-bypass — their fixtures intentionally use tiny content for shape testing. Each adjustment documented inline pointing at the dedicated strip test file.

`make test` 6766 pass / 1 skip. `make check` clean (ruff, mypy 207 files, deptry).

### Baseline regeneration

All 82 baseline cases under `.taskmaster/tasks/task_159/baseline/` regenerated with **zero byte drift**. Structurally correct: every baseline case exercises `analyze-cache` / `report` / `visualize` / `guide` (static analysis or recorded traces) — none reach the runtime dispatch seam.

Added a `pre-send` deferral note to the baseline README. A baseline case for the strip tier is the natural v1.x addition once trace 2.3.0 records `cache_skipped_reason` (the field that would let an `analyze-cache --from-trace` case observe the event).

### Key insights / learnings

1. **The dispatch seam matters more than provider abstraction.** Originally weighed a per-provider adapter pattern; rejected after the searcher confirmed all paths converge at `_assemble_cache_prep`. One seam means one check, no Provider/Capability protocol class, no new module — the change is additive within the existing data model.

2. **Hardcoded provider tables are not technical debt — they're the right shape for rare-change capability data.** The instinct to make it "dynamic" was wrong here: litellm doesn't expose the field, providers don't either, and "configurable via settings.json" would shift the bug from "we hardcoded the wrong value" to "the user hardcoded the wrong value."

3. **The catalog-as-SSoT pattern paid off.** Adding a third evidence_kind was a 3-line catalog change (template + dispatch entry). Zero new shared-store keys, zero new module, zero new catalog ID. The existing `make_diagnostic("cache.below-min-predicted", evidence_kind=...)` factory already validates required context at construction.

4. **Fail-open token counter, fail-closed threshold check.** When `litellm.token_counter` raises, fall back to chars/4 heuristic — that's fail-open for measurement. But the threshold comparison stays strict: below min → strip. The asymmetry is intentional: false-strip loses savings (cheap), false-keep produces a Gemini rejection (expensive).

5. **Pitfall #19 confirmed.** First test pass had a false negative: `test_above_min_keeps_cache_control_no_warning` failed because `MockLLMClient` default `cache_creation/read=0` made `has_cache_telemetry=True` fire the *observed* tier even when our strip didn't fire. Fixed by staging realistic telemetry. The bug-shaped-fixture trap is real even for tests testing my own new code.

### Closes / unblocks

- **Closes**: Scratchpad #3 (runtime prewarm hard-fail), GH #393 (runtime defense).
- **Unblocks**: Followups #4 (analyzer recommendation symmetry) — orthogonal but complementary fix; Scratchpad #19 (conditional warmup suggestion) — needs trace 2.3.0 field which is the natural next step now that the runtime detection exists.

### Files touched

Production:
- `src/pflow/nodes/llm/llm.py`
- `src/pflow/core/cache_analysis/warning_catalog.py`

Tests:
- `tests/test_nodes/test_llm/test_prompt_cache_below_min_runtime.py` (new)
- `tests/test_core/test_cache_analysis_warnings.py`
- `tests/test_runtime/test_prompt_cache_hash.py`
- `tests/test_nodes/test_llm/test_prompt_cache_rendering.py`
- `tests/test_nodes/test_llm/test_batch_cache_prefix.py`
- `tests/test_execution/test_runner.py`
- `tests/test_integration/test_no_cache_flag.py`
- `tests/test_runtime/test_trace_integration.py`

Docs:
- `.taskmaster/tasks/task_159/baseline/README.md` (`pre-send` deferral note)

## 2026-05-14 — Follow-ups 2 start: separate provider prompt-cache evidence from local pflow memo reuse

Implemented the trace-analysis split between provider LLM calls and pflow-local cache hits. The analyzer now keeps two LLM-call views from trace data: a historical view that may descend into cached subtrees for token/cost estimation, and a provider-current-run view that does not treat cached memo/in-process events as provider calls. Summary telemetry now records provider call count, provider cache read/write tokens, local memo hits, local in-process hits, and historical input tokens skipped by local reuse.

Critical learning: cached trace events can preserve historical `llm_call` payloads, including `cache_read_input_tokens`, but those payloads are not proof that provider prompt caching happened in the current run. A resumed pflow run may skip the LLM call before the provider sees anything. Any user-facing "provider cache" number must come from current provider events only; historical cached-event payloads are valid for estimates, not for current provider-cache evidence.

Renderer changes make that distinction explicit in text and JSON. Text output now labels actual deltas as including local cache reuse when applicable, adds a "Local pflow cache reuse" line, reports "Provider cache in this run" separately, and tells agents to rerun with `--no-cache` when they need a clean provider prompt-cache measurement.

Tests added coverage for memo-hit traces that previously would have counted historical provider cache reads, plus renderer/JSON shape coverage for the new summary fields. Regenerated staged baselines for `03-analyze-cache-modes/07-autoload-prefers-success`, `08-autoload-failed-only`, and `09-autoload-rejected-names-file`; each was verified individually with `verify.sh`.

## 2026-05-14 — Follow-ups 2 Stage 2: split below-min IDs and wire trace-visible runtime evidence

Implemented the Stage 2 plan. The old single below-min catalog row is now distinct IDs for predicted, observed, rendered-strip, prewarm-disabled, and conditional-warmup findings. The runtime now records `cache_skipped_reason` and `prewarm_disabled_reason` in `llm_usage`/trace 2.3.0, and `build_cache_render_dict(workflow, shared)` performs the workflow-entry pre-flight check that disables below-min batch prewarm before serialization can happen.

Key integration learning: `engine.py` cannot import cache-analysis helpers at module import time without closing a runtime/analyzer cycle. The pre-flight check uses lazy imports inside `_should_disable_below_min_prewarm`; that is intentional and narrower than introducing a new shared module just to avoid one cold-path import.

`analyze-cache --from-trace` now rehydrates catalog-backed runtime warnings from trace-level `warnings[]`. This is the right source for rendered/observed/prewarm-disabled evidence because those diagnostics already contain measured runtime context; deriving them only from per-event marker fields would lose token counts.

Deliberate semantic change: `is_below_min_cache(model, tokens)` returns false when the model is unknown or unresolved. This removed dynamic-before-static recommendations whose only threshold proof came from the conservative unknown-model floor. The real-world lyrics-generator baselines were regenerated to reflect that: unresolved-model rows no longer claim below-min-dependent dynamic warnings until the model is known.

Verification notes:
- Focused regression set: 905 passed.
- Near-full sandbox pytest: 6791 passed, 19 skipped, excluding seven subprocess tests that invoke Homebrew `uv` and panic in this sandbox before Python starts.
- Full baseline oracle: 86 passed, 0 drifted, 0 harness errors. Used a temporary `/private/tmp/pflow-uv-shim/uv` because the baseline harness invokes `uv run`.
- Targeted ruff on touched files passed. Full `ruff check .` still fails on unrelated pre-existing RUF043/RUF059 issues in tests outside this change set.
- Grep gates for the legacy below-min ID and directory slug are clean across `src`, `tests`, `docs`, and `.taskmaster`; the dead-code gates for the removed catalog dispatch symbols are clean in `src`.

## 2026-05-14 — Stage 2 post-review fixes

Code review caught one real bug and two cleanups in the Stage 2 work above.

### `_per_node_warnings` early-return swallowed conditional-warmup detector

`elif first is not None and first > 0 and not row.declared_prompt_cache` had `return diagnostics` when `tokenize_prompt_region` returned None (unresolved `${var}` refs in the static prefix). The conditional-warmup detector lives further down the same function and was unreachable for any batch node with unresolvable prefix refs — the exact scenario it was designed for.

Fix: replaced the early return with a `if prefix_tokens is not None:` wrap so the `cache.batch-prewarm-below-min` emit is skipped but execution falls through to the trace-driven conditional-warmup branch. Regression test in `test_cache_analysis_per_id_emission.py::test_conditional_warmup_recommended_fires_when_static_prefix_has_unresolvable_refs` drives a workflow with `${upstream-data.summary}` in the static prefix plus a trace fixture with mixed `cache_skipped_reason` and asserts the diagnostic fires. Mutation-tested.

### `cache.dynamic-before-static` false positive for heterogeneous-batch prompts

Baseline `10-live-recordings/05-gemini-lyrics-generator` and `12-real-world-lyrics-generator/01-analyze-cache-text` were emitting a contradictory recommendation for `generate-chorus-options`, `analyze`, and `generate-concepts`: "move `${item.prompt}` after stable content; appears before ~0 stable tokens; Projected cache ratio after fix: 0%". Move 0 tokens for 0% improvement.

Root cause is shape-level: `is_below_min_cache(model, tokens)` returns False when the model is empty (heterogeneous-batch rows carry `model=""`) so the threshold-based suppression in `_find_batch_static_tail_after_dynamic` failed to fire even at `stable_tail_tokens=0`. The predicate is fine for CLAIM-type diagnostics (don't assert below-min without a model) but wrong at recommendation-SUPPRESSION gates.

Fix: added an explicit zero-payoff guard at the single producing site (`_find_batch_static_tail_after_dynamic`, ~line 3097) — `if stable_tail_tokens is None or stable_tail_tokens <= 0: return None`. Narrow scope: only suppresses the provably-meaningless "move 0 stable tokens" case; legitimate recommendations with substantial stable tails (e.g. `write-lyrics` ~1002 tokens) still fire. Regression test in `test_dynamic_before_static_silent_for_heterogeneous_batch_with_no_stable_tail`. Mutation-tested.

Open shape issue worth flagging: `is_below_min_cache` is overloaded across claim-type and suppression-type call sites. Three other suppression-gate sites (`analyze.py:2928, 2957, 3049`) still use the predicate; if false positives surface there too, the right fix is a sibling predicate (e.g. `is_likely_below_min_cache` using `get_min_cache_tokens`'s `CONSERVATIVE_FLOOR` fallback). Out of scope for this fix — none of those sites emit visibly-broken output in current baselines.

### Cleanup

- Removed dead-stub `_select_message_template` in `warning_catalog.py` (7-LOC pass-through with 4 unused kwargs left over from the catalog ID split); inlined the trivial `spec.message_template.format(**format_dict)` at the call site.

### Verification

- 589 cache-analysis tests pass (+1 from before). Full default suite 6775 pass / 10 skipped.
- Touched-file `ruff` + `mypy` clean.
- `verify.sh`: 85 pass / 1 drift (`15-run-flag-interactions/03-report-with-only` — pre-existing `/dev/fd/62: Operation not permitted` sandbox issue, unrelated).
- Regenerated 6 baselines whose `cache.dynamic-before-static` items were the false-positive shape: `10-live-recordings/05-gemini-lyrics-generator`, `12-real-world-lyrics-generator/{01-text,02-json,03-song-creator-text,04-guide}`, plus the dedicated `04-warning-catalog/07-cache.dynamic-before-static` (which was always empty — workflow has neither `prompt_cache` nor `batch`, no emission path fires; the directory is an orphan stub).

## 2026-05-14 — Batch large-item failure UX bounded summaries

Implemented the batch-error large-item UX plan. Failed batch records now keep the full original `errors[].item` for runtime/template use and add a bounded summary companion at every batch error creation path: action/error-output failures, retry-exhausted exceptions, and parallel executor-level exceptions. The fail-fast no-exception raise now names the node/index/root cause plus compact item identity instead of `repr(item)`.

User-facing boundaries now render the compact shape: shared batch-error text formatter for CLI/MCP success/degraded summaries, hard-failure CLI text, MCP failure text, CLI JSON/API failure output, degraded success JSON/stdout output, and generated trace reports. Reports now detect batch aggregate outputs and render `## Batch Errors` while suppressing raw aggregate keys from the catch-all `## Output` block.

Key deviation from the scratchpad plan: I also compacted `format_execution_success(...)` execution steps and auto-detected batch aggregate workflow output for degraded successful runs. The plan explicitly covered error JSON, but the stated contract was broader: CLI JSON/API output and text output must not become second unbounded payload surfaces. Leaving degraded success output raw would have preserved the leak for `error_handling: continue`.

Validation:
- Focused regression set: 464 passed.
- Targeted ruff on touched Python files passed.
- Targeted mypy on touched source files passed.
- Manual repro `scratchpads/pflow-cache-repros/repro-08-batch-error-large-item.pflow.md --no-cache --report` fails as intended; stderr and generated report contain compact item summaries and no `PAYLOAD-START`, `PAYLOAD-END`, or `token199`.
- Near-full sandbox-safe pytest: 6813 passed, 19 skipped, excluding seven subprocess tests that invoke Homebrew `uv` and panic in this sandbox before Python starts. An unfiltered near-full run failed only on four of those uv-subprocess tests with the known `Tokio executor failed` panic.

Learning: the raw payload leak was not one renderer bug. The clean fix is to preserve full-fidelity runtime data at the batch executor boundary, then make every public formatter cross the same compact-item boundary. The important extra check was degraded success output: summaries were safe, but auto-detected workflow output still needed the same display/API boundary treatment.

## 2026-05-14 — Batch large-item failure UX post-review polish

Post-implementation review found the payload was bounded but the real code-node repro still had noisy structure: the item summary was appended to the last suggestion line in the primary diagnostic, and compact batch sections repeated multi-line diagnostic details before truncating mid-message.

Fixes:
- Fail-fast no-exception batch errors now split the root-cause headline from diagnostic details and render the compact item identity on its own line.
- Shared batch-error formatting now uses a single root-cause headline for compact text/JSON/report sections, so Location/Source/Suggestions stay in the primary diagnostic instead of being duplicated in the batch summary.
- Generated reports suppress empty `results: []` aggregate output for failed batch nodes, removing the leftover empty `## Output` block.
- Added a code-node CLI regression matching the spend-free repro shape, plus formatter/report assertions for the cleaned structure.

Verification:
- Focused batch UX regression set: 466 passed.
- Manual repro `scratchpads/pflow-cache-repros/repro-08-batch-error-large-item.pflow.md --no-cache --report`: stderr, JSON, and generated report contain compact item summaries and no `PAYLOAD-START`, `PAYLOAD-END`, or `token199`.
- Task 159 baseline oracle with sandbox-safe `uv` shim: 86 passed, 0 drifted, 0 harness errors.
- Targeted ruff and mypy on touched source/test files passed.

## 2026-05-14 — PerCallRow token fields normalized to per-call

Implemented F#3 / GH #394. `_aggregate_trace_llm_calls` is now the single producer-side normalization point for token integer fields: trace input/output/cache creation/cache read tokens are summed then divided by observed calls. Removed the old static-batch and repeated-non-batch compensators from `analyze.py` and `token_estimation.py`. `PerCallRow.cost_usd` intentionally remains cohort because it flows through `TraceTree` cost walkers, not the token aggregator.

Consolidated row-to-cohort multiplication into `invocation_count_for(row)` and routed summary totals, cost projections, cross-workflow/grouped savings, dynamic-before-static savings, padding advisories, shared-context savings, and total invocation estimates through that contract. The code-review checkpoint caught three local multiplier bypasses plus `_estimate_total_invocations`; those were real misses and were fixed before baseline regeneration.

JSON output is bumped to `format_version: "4.3"` and docs/MCP schema text now state the per-call token contract plus the `cost_usd` asymmetry. Baselines were regenerated after audit: most drift was the version bump; the load-bearing numeric drift is `10-live-recordings/05-gemini-lyrics-generator`, where previously cohort-looking rows now render per-call values and sort accordingly.

Verification:
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_cache_analysis_*.py -q` → 727 passed.
- Baseline oracle `verify.sh` with sandbox-safe PATH → 86 passed, 0 drifted, 0 harness errors.
- Targeted `ruff`, source-file `mypy`, and `deptry src` clean.
- Near-full sandbox run → 6820 passed, 19 skipped after excluding seven `/opt/homebrew/bin/uv` subprocess tests that panic in this sandbox before Python starts.

Deviation: I updated `_estimate_total_invocations` and advisory savings paths beyond the literal producer/test edits because leaving them on hand-rolled static-only multipliers would have preserved wrong cohort values after the row contract changed. This is not optional cleanup; it is required for the new unit boundary to be coherent.

Behavior-change call-out for reviewers: `_estimate_total_invocations` now contributes `observed_call_count` for dynamic-batch and non-batch-repeated rows that have observations, where it previously fell through to "invocation count unavailable" whenever any dynamic batch was present. User-visible effect: the `Workflow: N LLM nodes, ~X invocations` header line in `pflow analyze-cache` now reports a real total on traces that previously showed "invocation count unavailable". The lyrics-generator baseline regen captures this: `~253 invocations` replaces the prior `invocation count unavailable (3 dynamic batch nodes)`. Reviewers should expect this line to change on any workflow with dynamic batches; treat it as a correction, not a regression.

## 2026-05-14 — Per-call unit contract review polish

Code review against the rev-2 plan caught one orphan-field nit: `_aggregate_trace_llm_calls` was still summing `cost_usd` across calls into `aggregate["cost_usd"]`, but no downstream code in the package reads cost from that aggregate dict (`row.cost_usd` flows through `AnalysisContext.cost_usd_for_node` / `TraceTree.total_cost` instead). Verified by grep across `src/pflow/core/cache_analysis/`: zero consumers read `aggregate["cost_usd"]` or `trace_llm_call["cost_usd"]` or `provider_trace_llm_call["cost_usd"]`. Raw per-event lists (`trace_llm_calls`, `provider_trace_llm_calls`) are only consumed for `model`, `cache_skipped_reason`, and `len()` counts.

Fix: dropped the `cost_usd` sum entirely and added `aggregate.pop("cost_usd", None)` so calls[0]'s cost value can't be silently re-introduced as a row-level total by a future consumer. Updated the docstring to call out the asymmetry explicitly. 404 cache-analysis tests still pass.

## 2026-05-14 — Bundle 1: shadow/duplicates warning reframing + summary block UX (closes F#1 + F#20)

Bundle 1 from the F#1 deep-dive. The followups doc's F#1 — "summary
uses inflated baseline when prompt body shadows the cached value" — was
investigated and determined to be **misframed**, not a math bug. The
summary's `input_tokens_estimated × rate` baseline correctly answers
counterfactual #1 ("same prompt, no cache discount"); the followups doc
assumed it should answer counterfactual #2 ("no cache declaration at
all"), which is the local recommendation's job. Detail in
`open-bugs-and-ux-followups.md` section 1 (now marked CLOSED).

The real friction was twofold and fixed in Bundle 1:

### 1. Shadow + duplicates warning text overclaimed

`cache.prompt-body-shadows-cache` asserted *"the rest is sent to the
model but unused by your prompt"* (unprovable — the cached object's
unreferenced fields might be intentional implicit context) and *"a
different baseline than your body actually uses"* (the hedge that
conceded a bug we no longer believe exists).

Reframed both warnings around a duplication question:

- shadows: `"may be sending the same value twice in each call — cached
  chunks and prompt-body ${var} references overlap on a sub-path"`
- duplicates: `"sends the same value twice in each call — once as a
  cached chunk AND inline in the prompt body"` (mechanism explanation
  preserved as parenthetical)

Suggestion templates now offer two clear directions matching the two
possible intents (narrow the cached chunk vs. remove the body
reference). Dropped two prose lines from
`_format_shadow_cache_cost_comparison` in `render_text.py`; kept the
per-call cost disclosure (`Removing prompt_cache: ... would drop
per-call cost from X to Y`) which is honest action evidence.

### 2. Summary block had 5 strings for one baseline concept + redundant deltas

Old trace-mode summary rendered 5 lines: 3 cost lines (`Actually
paid`, `Cost without caching`, `Cost on rerun (within TTL)`) plus 2
delta lines (`Actual cost delta (this run): saves ~$X/run vs no-cache,
N% of no-cache cost`, `Rerun delta (projected): saves ~$X/run on
rerun, N% of no-cache cost`). The deltas were derivable arithmetic on
the cost lines; only the percentages carried unique signal. Worse: the
no-cache baseline was labelled inconsistently across lines (`"Cost
without caching"`, `"no-cache cost"`, `"vs no-cache"`, `"no_cache
hypothetical"`, `"Cost without caching (executed)"`).

Candidate A collapse: each cost line carries its own parenthetical:

```
Actually paid:               ~$0.0087 (from trace)  (saves 26% vs cost without caching)
Cost without caching:        ~$0.01
Cost on rerun (within TTL):  ~$0.0031  (saves 73% vs cost without caching)
```

- Dollar deltas dropped (derivable); percentages preserved (load-bearing).
- Verb-encoded direction: `saves`/`adds`/`no meaningful cost change`.
- Single unified phrase `"cost without caching"` across all references.
- `(incl. local cache reuse)` qualifier moves into the `Actually paid`
  parenthetical so local-cache attribution stays visible.
- Closes F#20 (sign confusion) — the verb carries direction, no separate
  "Savings" label that flips meaning under sign change.

Greenfield Mode B and truncated trace Mode A' get the same parenthetical
treatment; greenfield no-cache (Mode C) is unchanged (already a single
collapsed line).

### Implementation notes

- New helpers in `render_text.py`: `_format_delta_parenthetical(delta,
  *, local_cache_reuse=False)` and `_append_parenthetical(line,
  parenthetical)`. Old `_format_delta`, `_render_summary_deltas`,
  `_render_trace_deltas`, `_render_greenfield_deltas` deleted.
- `_BASELINE_LABELS` map renamed `"no-cache cost"` → `"cost without
  caching"`.
- No JSON shape change. `CostDelta` keys (`amount_usd`, `pct_of_baseline`,
  `kind`, `baseline`, `compared_to`, `unavailable_reason`,
  `excluded_nodes`) preserved on all three deltas. `format_version` stays
  at 4.3 — text-only changes are not a minor bump per the documented
  additive policy. MCP `analyze_cache` returns JSON only; consumers see
  the new `warnings[].message` text but no key/type changes.

### Testing

- 5 new `_format_delta_parenthetical` unit tests cover translation,
  drop-dollar-and-excluded, unavailable → empty, break_even neutral
  phrase, and local-cache-reuse suffix.
- 9 integration tests in renderers + analyze updated for the new
  parenthetical shape; legacy `Actual cost delta` / `First-run delta` /
  `Rerun delta` line labels are now negative assertions
  (mutation-protective).
- 2 new catalog regression tests
  (`test_shadow_warning_message_uses_duplication_framing`,
  `test_duplicates_warning_message_uses_duplication_framing`) lock the
  new wording.
- Negative assertions added that "unused by your prompt" and "different
  baseline than your body" do NOT appear anywhere in rendered text.

`tests/test_core/` near-full pytest: **2647 passed, 4 deselected**.
Full sandbox-safe pytest (excluding e2e + integration): **6588 passed,
10 skipped, 42 deselected**.

### Baseline regeneration

10 baselines regenerated (1 pre-existing sandbox-only drift remains —
`15-run-flag-interactions/03-report-with-only`, the `/dev/fd/62`
issue documented in the prior progress log entry):

- Summary block shape: `03-analyze-cache-modes/{05,07,08}`,
  `04-warning-catalog/12`, `10-live-recordings/{03,05}`,
  `15-run-flag-interactions/01`.
- Warning text shape: `01-parser-errors/09`,
  `04-warning-catalog/{18,19}`.

`verify.sh` with sandbox-safe `uv` shim: **85 pass / 1 drift / 0
harness errors** (same state as prior progress log entry).

### Key insights / learnings

1. **The "shadow" detection is structurally honest, not a bug.** The
   cache chunks ARE part of the prompt the model sees. The analyzer
   cannot distinguish "user over-cached by mistake" from "user
   intentionally provides rich context, focuses prompt narrowly." Both
   are legitimate. Reframing the warning as a question (rather than an
   assertion) respects that.

2. **The followups doc had it wrong, and it took deep counterfactual
   analysis to see why.** Documenting WHY F#1 is closed (the two-
   counterfactual mapping) protects future contributors from reopening
   it on the same misreading. The closeout note is the highest-
   leverage docs change.

3. **Label fragmentation is its own UX bug, distinct from any math
   bug.** Five strings for one baseline concept forces agents to map
   between vocabularies. Unifying to `"cost without caching"`
   everywhere is purely terminology hygiene — no behavior change — but
   the agent-readability gain is real.

4. **Deltas can be parenthetical, not lines.** The arithmetic was
   derivable from cost lines; only the percentage was load-bearing.
   Folding into parentheticals removes the third number that has to
   stay in sync, and keeps cohesion (each cost line carries its own
   comparison signal).

### Files touched

Production:
- `src/pflow/core/cache_analysis/warning_catalog.py` (shadow + duplicates message + suggestion templates)
- `src/pflow/core/cache_analysis/render_text.py` (parenthetical builder, summary cost composition, removed deltas section)

Tests:
- `tests/test_core/test_cache_analysis_renderers.py` (test helper baseline-value fix, 7 integration tests updated, 5 new unit tests for parenthetical builder)
- `tests/test_core/test_cache_analysis_analyze.py` (2 shadow + heterogeneous-exclusion tests updated)
- `tests/test_core/test_cache_analysis_warnings.py` (2 new catalog regression tests)

Docs:
- `.taskmaster/tasks/task_159/implementation/reports/open-bugs-and-ux-followups.md` (F#1 closeout + reasoning; F#20 closeout)

Baselines:
- 10 expected-stdout.txt regenerated under `.taskmaster/tasks/task_159/baseline/`

### Closes

- F#1 (full shadowed-cache summary math) — closed as misframed
- F#20 (negative savings wording) — closed by verb-encoded parenthetical

## 2026-05-14 — Bundle 4: trust polish (closes S#4, S#9, F#17 minimal, S#14)

Four independent agent-UX wins that don't touch the analyzer's data model — surgical fixes batched together so the cache-ready-opportunity refactor (the next big sprint) starts on a cleaner foundation. Each item shipped as its own small commit-sized scope; parallel implementation across the four items (two via `code-implementer` subagents) cut wall-clock time roughly in half without introducing file conflicts.

### Items

**S#4 — `__validation_placeholder__` internal sentinel leak.** Running `pflow analyze-cache --from-trace` on a workflow with non-string declared inputs (`integer`/`number`/`boolean`) leaked `WARNING: Cannot coerce '__validation_placeholder__' to integer` to stderr — an internal sentinel injected by `generate_dummy_parameters()` flowing through the type coercers. Fixed at the single entry point (`coerce_workflow_input`, `param_coercion.py:227`) with a one-line short-circuit rather than five duplicated guards across `_coerce_to_*` helpers. Extracted the string literal to a `VALIDATION_PLACEHOLDER: Final[str]` constant in `validation_utils.py` and routed every comparison site (existing `engine.py:147` short-circuit, new `param_coercion.py` guard, and the two `MetricsCollector` / `_LLMSummaryAccumulator` filters added by F#17 below) through that constant. Added a parametrized regression test covering all seven declared types (`string`, `integer`, `number`, `boolean`, `object`, `array`, `any`) asserting no warning fires and the sentinel passes through unchanged. Mutation-verified: removing the entry-point guard reproduces the original `Cannot coerce` warning on `integer`/`number`/`boolean`.

**S#9 — Parent-trace vs child-workflow redirect hint.** Running `pflow analyze-cache <child.pflow.md> --from-trace <parent-trace>` rendered the generic scope-mismatch note even when the child clearly ran as a sub-workflow inside the parent, with the user-visible "0 of N LLM nodes executed" line giving no actionable next step. Added `_workflow_appears_as_child(trace_data, lookup_path, trace_root)` near `_resolve_trace_scope` (`analyze.py:1213`) that walks the existing `TraceTree.walk()` primitive and matches `WalkEvent.workflow_path` against `lookup_path`. When a match is found, `_resolve_trace_scope` emits a redirect note (`` `{lookup_path}` appears as a sub-workflow inside the trace `{trace_root}`. To see full attribution for this run, analyze the trace root instead: `pflow analyze-cache {trace_root} --from-trace <trace-path>`. ``) instead of the generic disclosure. Extended `test_actually_paid_scopes_to_analyzed_workflow_when_trace_is_parent` (already covered the appears-as-child fixture) with redirect-note assertions; added `test_scope_mismatch_emits_generic_note_when_analyzed_workflow_absent_from_trace` to lock the negative branch (mutation: returning `True` unconditionally trips this test). No new catalog ID — the Notes channel already carries comparable advisories (`_format_rejection_note` precedent).

**F#17 minimal — Name the model in cost summaries.** Paid runs with an unpriced model rendered `pricing unavailable for: unknown` with no actionable next step. The string `"unknown"` was a producer-side sentinel in both parallel data producers (`MetricsCollector.calculate_costs:60` and `_LLMSummaryAccumulator.add_leaf:75`) that masked both genuine model names and the `VALIDATION_PLACEHOLDER` sentinel from S#4 leaks. Top-10% reshape: drop the `"unknown"` literal at both producers; track real model names in `unavailable_models: set[str]` and genuinely-unrecorded calls in `unavailable_models_unnamed_count: int` (additive JSON field; consumers gating on `format_version.startswith("4.")` continue to work). New module-level helper `format_unavailable_models_phrase(unavailable_models, unnamed_count) -> str` in `metrics.py` consumed by all three renderer sites (`workflow_output.py`, `success_formatter.py`, `trace_report.py`) — single source of truth for the wording, no per-site string concatenation drift surface. Rendered output now reads `pricing unavailable for: gemini/gemini-3-flash-preview; 2 calls without recorded model` instead of `pricing unavailable for: unknown` — agent can both name the model and know how many unrecorded calls exist. Per-model call counts (the followups doc's optional second half — `(3 of 237 calls)`) deferred to a separate additive follow-up; minimal scope chosen to keep the bundle small. Both producers also filter `VALIDATION_PLACEHOLDER` so any future upstream propagation gap doesn't leak the sentinel through this path either.

**S#14 — Warm-trace rerun-within-TTL relabel.** The `Cost on rerun (within TTL)` line in `analyze-cache --from-trace` output rendered identically regardless of whether the trace was a cold-cache or warm-cache run. When the trace already showed provider cache reads, the "rerun" projection answers "what would a *future* warm-prefix run cost" — close to actually-paid but conceptually a different scenario from the trace itself, easy to misread as a future-state contrast. Added `_rerun_label(summary, *, context)` helper (`render_text.py:420`) returning the appropriate label given `AnalysisSummary.trace_provider_cache_read_input_tokens` (signal already on the summary, no new aggregation). When the trace is warm, the helper appends `, modeled rerun vs warm-cache trace` to clarify the comparison. Four render sites in `render_text.py` (truncated, complete-folded, complete-fallback, greenfield) now call the helper — single source of truth for the label string. Greenfield context never gets the warm-trace suffix (defensive: greenfield by definition has no trace, but the gate is explicit). Six baselines re-baked (`03-analyze-cache-modes/{05,07,08}`, `10-live-recordings/{03,05}`, `15-run-flag-interactions/01`); all drifts confirmed to be exactly the warm-trace suffix addition, nothing else. Three new tests: warm-trace suffix on complete-trace context, on truncated-trace context, and the negative greenfield-never-suffix branch.

### Why this shape (top-10% simplicity)

Each item chose the same pattern: **single source of truth at the producer/seam, structured data flowing to consumers, no per-site duplicated logic.**

- **S#4**: one short-circuit at the coercion entry point, not five at each coercer. One `VALIDATION_PLACEHOLDER` constant, not five inline string literals.
- **S#9**: one helper using existing `TraceTree.walk` primitive, not a new traversal abstraction. Note channel precedent reused, not a new catalog ID.
- **F#17**: one `format_unavailable_models_phrase` helper consumed by three renderers, not three sites of string concatenation. Two structured fields (`unavailable_models` + `unavailable_models_unnamed_count`) consumed downstream, not a pre-baked string that drifts across sites.
- **S#14**: one `_rerun_label` helper consumed by four sites, not four inline label conditionals. Existing signal (`trace_provider_cache_read_input_tokens`) reused, not a new aggregation.

The wins compound: when the next sprint (cache-ready-opportunity plan) extends the projection model, it operates against a cleaner producer-side surface — `VALIDATION_PLACEHOLDER` short-circuit, named-model truth, scope-redirect note, and label-helper machinery all already in place.

### Verification

- **Full default pytest** (`tests/test_core/` + `tests/test_execution/` + `tests/test_cli/` + `tests/test_runtime/`, excluding the unrelated `test_dry_run_subprocess.py` sandbox flake): **5504 passed, 1 skipped**.
- **Targeted regression sets** (per item) all green: 7 new parametrized S#4 tests, 3 S#9 tests, ~10 new F#17 tests across 4 files, 3 new S#14 tests.
- **`make check` equivalent**: `.venv/bin/ruff check src/` + all touched test files clean; `.venv/bin/mypy src/pflow/` clean on 209 source files.
- **Baseline `verify.sh`**: 85 pass / 1 pre-existing sandbox drift (`15-run-flag-interactions/03-report-with-only`, the documented `/dev/fd/62: Operation not permitted` issue from prior progress log entries — confirmed unchanged by my work via `git diff`).
- **Baseline drift surface**: 6 expected-stdout.txt files, every diff is exactly the warm-trace suffix addition. 4 unrelated `trace.json` newline-stripping side-effects from `regenerate.sh` were reverted (cosmetic only, no semantic change).

### Implementation efficiency

S#4 and S#9 were implemented serially in the parent agent. F#17 and S#14 were delegated to two parallel `code-implementer` subagents with comprehensive context (file:line refs, decision rationale, definition of done, out-of-scope list). Both subagents shipped clean implementations matching the brief; trust-but-verify code reads confirmed they did what they claimed (helper exists, renderers call it, tests assert real shape, baselines drifted only on expected lines). The parallel approach cut wall-clock time roughly in half — about 35–40 min of subagent runtime instead of 60+ min serial — without introducing file conflicts because the four items touch fully disjoint surface.

### Files touched

Production (10 files):
- `src/pflow/core/validation_utils.py` (`VALIDATION_PLACEHOLDER` constant, `generate_dummy_parameters` cleanup)
- `src/pflow/core/param_coercion.py` (entry-point short-circuit)
- `src/pflow/runtime/engine/engine.py` (constant import, comparison site update)
- `src/pflow/core/cache_analysis/analyze.py` (`_workflow_appears_as_child` helper, redirect-note branch)
- `src/pflow/core/metrics.py` (`format_unavailable_models_phrase` helper, named/unnamed tracking)
- `src/pflow/runtime/workflow_trace.py` (`_LLMSummaryAccumulator` named/unnamed tracking)
- `src/pflow/cli/workflow_output.py` (helper consumption)
- `src/pflow/execution/formatters/success_formatter.py` (helper consumption, top-level lift)
- `src/pflow/core/trace_report.py` (helper consumption)
- `src/pflow/core/cache_analysis/render_text.py` (`_rerun_label` helper, 4 call site replacements)

Tests (7 files):
- `tests/test_core/test_param_coercion.py` (7 new parametrized cases)
- `tests/test_core/test_cache_analysis_analyze.py` (1 updated + 1 new test)
- `tests/test_core/test_metrics.py` (1 updated + 2 new test classes)
- `tests/test_core/test_unknown_model_user_experience.py` (1 new regression)
- `tests/test_execution/formatters/test_success_formatter.py` (extended existing class with 2 new cases)
- `tests/test_cli/test_direct_execution_helpers.py` (extended existing class with 2 new cases)
- `tests/test_core/test_cache_analysis_renderers.py` (3 new tests)

Baselines (6 files): expected-stdout.txt warm-trace suffix re-bake under `.taskmaster/tasks/task_159/baseline/{03-analyze-cache-modes/05,07,08, 10-live-recordings/03,05, 15-run-flag-interactions/01}/`.

### Closes

- S#4 (placeholder sentinel leak)
- S#9 (parent-trace child-workflow redirect)
- F#17 (pricing unavailable wording) — minimal scope; per-model counts deferred as additive follow-up
- S#14 (rerun-within-TTL warm-trace relabel)

### What's next

Bundle 5 (`is_below_min_cache` predicate split for claim-vs-suppression contexts at `analyze.py:2928, 2957, 3049` — ~0.5 day) before the cache-ready-opportunity plan starts, so the projection model uses the cleaner predicate from day one.

## 2026-05-15 — Bundle 5: predicate split (sibling `is_likely_below_min_cache` for SUPPRESSION sites)

Added the sibling predicate that the post-review entry of the per-call unit contract work anticipated. The new predicate uses `CONSERVATIVE_FLOOR` (4096) when model is None or empty; the existing `is_below_min_cache` retains its "honest unmeasurable" semantics (returns False for unknown model). The split unblocks the cache-ready-opportunity plan's component model — projection components that need a "conservative gate" semantics now have a primitive to call.

### The architectural decision (Option B)

A scan of the 8 `is_below_min_cache` call sites in `analyze.py` found 6 SUPPRESSION-shape uses and 2 CLAIM-shape uses. An initial implementation swapped all 6 SUPPRESSION sites to the new predicate. **Baseline verify caught a real UX regression in the lyrics-generator showcase**: 4 of the 6 documented recommendations on the unresolved-model workflow disappeared, dropping the recommendation count from 6 → 2. The suppressed recommendations were `cache.dynamic-before-static` and `cache.batch-prewarm-*` rows carrying `"savings unavailable"` (honest about dollar uncertainty) + `"projected cache ratio after fix: N%"` (structural insight).

The trade-off: under the conservative predicate, unresolved-model workflows lose structural recommendations entirely until a model is set. Under the honest-unmeasurable predicate at user-visible recommendation gates, the recommendations emit with the existing uncertainty annotation.

**Decision (Option B):** restrict the new predicate to internal cost-math gates where empty-model already short-circuits elsewhere. User-visible recommendation gates stay on the existing predicate.

Final distribution after Bundle 5:

- `is_likely_below_min_cache` (SUPPRESSION, conservative-floor for unknown model):
  - `analyze.py:4148` — `_compute_cross_workflow_consolidation_costs` (cost map; empty model already short-circuits via `pricing = get_model_pricing(...)` returning None, so this switch is behavior-preserving code-clarity)
  - `analyze.py:4215` — `_single_call_write_penalty` (similar: empty model already None-propagates via pricing/rate)
- `is_below_min_cache` (CLAIM/honest-unmeasurable, returns False for unknown model):
  - `analyze.py:2953` — `cache.batch-prewarm-lower-bound-recommended` gate
  - `analyze.py:2982` — `cache.batch-prewarm-recommended` gate
  - `analyze.py:3074` — `cache.dynamic-before-static` non-batch branch
  - `analyze.py:3127` — `cache.dynamic-before-static` batch branch (zero-payoff guard at line 3124 still owns the `tokens=0` case)
  - `analyze.py:4487` — `cache.prompt-cache-incomplete` below-threshold flag (mixed CLAIM+SUPPRESSION; secondary filter at 4537 still applies)
  - `analyze.py:4537` — `_below_threshold_clause_for_findings` (pure CLAIM — generates user-facing "below X-token min" text)
  - `below_min_tokens_detector.py:125` — `detect()` for `cache.below-min-predicted` (pure CLAIM)
  - `below_min_tokens_detector.py:153` — `detect_batch_prewarm_below_min()` for `cache.batch-prewarm-below-min` (pure CLAIM)

`engine.py:175` (runtime pre-flight `_should_disable_below_min_prewarm`) intentionally untouched — runtime defense lives there, and the post-review work already validated that path.

### Why Option B preserves better agent UX

Each of the suppressed-under-Option-A recommendations was emitting with the shape:

```text
Dynamic ref blocks caching on write-lyrics — move `${choose-chorus.chorus_guide}` after stable content   savings unavailable
  write-lyrics: dynamic `${choose-chorus.chorus_guide}` reference at line 68 appears before ~1002 stable tokens; move stable instructions before dynamic content so prefix caching can fire for 1 calls per run
  → Projected cache ratio after fix: ?%.
```

That shape is structurally useful: the agent learns about a real pattern in the workflow and can act on it the moment a model is resolved. The `"savings unavailable"` already discharges the analyzer's responsibility to be honest about dollar uncertainty. Suppressing entirely would force the agent to either (a) set a model just to re-discover the structural insight, or (b) miss the pattern altogether. The cache-ready-opportunity plan will subsume this distinction via the component model anyway — `meets_provider_min=False` will be a per-component property, not a hard suppression gate.

### Setup for the cache-ready-opportunity plan

The sibling predicate is the primitive Phase 1 of the projection plan will use to populate `CacheProjectionComponent.meets_provider_min`. Specifically:

- Configured prewarm component: `meets_provider_min = not is_likely_below_min_cache(model, prefix_tokens)` (conservative — treat unknown model as below floor for the "would runtime emit a marker?" question).
- Declared chunk component: same primitive at the per-component level.
- Cross-workflow and candidate components: same primitive.

The `affects_cost_projection: bool` flag is the projection model's replacement for SUPPRESSION-gate logic — components with `meets_provider_min=False` AND the cost-projection responsibility set to false won't affect `cache_active.tokens_estimated`. The structural visibility (table `upside` column, `cache_opportunity`) remains intact.

This Bundle 5 work therefore unblocks the projection refactor *cleanly*: there's a single, well-documented primitive that says "is this likely below the provider's minimum, conservatively." The projection model uses it at component construction; analyze.py's user-visible recommendation gates continue to use the honest-unmeasurable predicate until the refactor swaps them out entirely.

### Tests

- 7 new unit tests in `tests/test_core/test_below_min_tokens_detector.py` lock both predicate behaviors and the asymmetry (only-disagree-on-empty-model-branch). The asymmetry test is mutation-protective: changing either branch breaks the lock.
- 1 docstring update on the existing `test_dynamic_before_static_silent_for_heterogeneous_batch_with_no_stable_tail` test, since the zero-payoff guard (not the predicate split) owns that scenario.
- No new integration test was added — the lyrics-generator baselines + the existing per-id tests cover the user-visible behavior, which is unchanged at recommendation gates under Option B.

### Verification

- `tests/test_core/test_below_min_tokens_detector.py`: **25 passed**.
- `tests/test_core/test_cache_analysis_*.py`: **735 passed** (+1 from this work's new asymmetry test, 6 new tests offset by the removed Option-A regression test).
- `tests/test_core/` + `tests/test_runtime/`: **4343 passed, 1 skipped**.
- Targeted `ruff check` on touched files + full `mypy` on `src/pflow/core/cache_analysis/`: clean (13 files).
- `verify.sh` with sandbox-safe `uv` shim: **85 pass, 1 drift** (pre-existing sandbox `/dev/fd/62` issue documented in prior progress log entries — confirmed unchanged via `git diff`).

### Files touched

Production (2 files):
- `src/pflow/core/cache_analysis/below_min_tokens_detector.py` — added `is_likely_below_min_cache`; updated `is_below_min_cache` docstring to point at the sibling for SUPPRESSION contexts.
- `src/pflow/core/cache_analysis/analyze.py` — added import; switched 2 internal-cost sites (4148, 4215).

Tests (2 files):
- `tests/test_core/test_below_min_tokens_detector.py` — 7 new unit tests + sibling import.
- `tests/test_core/test_cache_analysis_per_id_emission.py` — docstring update on existing test.

### Key insights / learnings

1. **The "post-review observation" was directionally right but scope-needed-narrowing.** The post-review entry flagged 3 suppression sites (`2928, 2957, 3049`) as candidates for the sibling predicate "if false positives surface." The full predicate split at all suppression sites turns out to over-correct: the sites that emit user-visible recommendations carry an `"savings unavailable"` annotation that already discharges the honesty responsibility. Restricting the new predicate to *internal* suppression-gates preserves the educational value of structural recommendations.

2. **Baselines caught the UX regression that unit tests would not have.** No unit test asserts "the lyrics-generator shows 6 recommendations." But the baseline diff made the regression visible immediately. This reinforces the "baselines as output-oracle" pattern: they catch composition-level UX regressions that targeted assertions miss.

3. **The empty-string model marker carries semantic weight.** `row.model = ""` means "heterogeneous batch" (per-item model varies, can't aggregate to a single threshold). The two predicates encode opposite policies for this case: `is_below_min_cache` returns False (no claim without proof); `is_likely_below_min_cache` returns conservatively True (no marker likely to fire). Both are correct for their context; making them coexist named-and-documented is the win.

4. **Internal SUPPRESSION sites where the empty-model case short-circuits elsewhere are pure code-clarity wins.** Sites 4148 and 4215 don't user-visibly change behavior because `get_model_pricing("")` already returns None upstream of the predicate check. The predicate switch at those sites is documentation-by-code: "this gate is suppression-shape; reads as conservative."

5. **The cache-ready-opportunity plan absorbs this distinction cleanly.** Once `CacheProjectionComponent.meets_provider_min` lands as a per-component property and `affects_cost_projection` gates aggregation, the SUPPRESSION-vs-CLAIM tension dissolves: structural opportunities stay visible with explicit blocker fields, and cost math respects the provider minimum without hard-suppressing the row.

### Closes

- Bundle 5 (predicate split) — closed, Option B scope.

### What's next

Per user instruction: stop after Bundle 5. The cache-ready-opportunity plan (`scratchpads/cache-ready-opportunity-plan/implementation-plan.md`) is the next major work and will subsume the remaining predicate-overload questions via the component projection model. Bundle 3 (F#21 validation-time provider constraints) is independent and can run in parallel with or after the refactor.

## 2026-05-15 — Bundle 3: F#21 validation-time provider constraints — close for the verified case, tighten the gaps

Five parallel `pflow-codebase-searcher` agents investigating F#21 surfaced the surprise of this sprint: **the most-cited case is already shipped**. The followups doc framed F#21 as "Validation-time provider constraints are not caught" — implying an open gap. Investigation showed the GH #385 case (Anthropic + extended thinking + non-1 temperature) is fully wired end-to-end. The right scope for Bundle 3 was therefore not "build new validation" but "lock the existing behavior against regression + close the followups item with documented reasoning."

### The investigation surprise

Concrete state of the existing implementation:

- **Catalog**: `llm.thinking-temperature-mismatch` at `warning_catalog.py:916-939` (severity ERROR, source `"validator"`, category `LLM_VALIDATION_CATEGORY`).
- **Validator**: `_extract_thinking_temp_violation` (`data_flow.py:1103-1141`) + `_validate_thinking_temperature_compatibility` (`:1144-1181`). Triggers on Anthropic + `reasoning_effort ∈ {xhigh, high, medium, low, minimal}` + literal `temperature ≠ 1.0`. Skips templated values; defers to runtime when model is `${...}`.
- **Wired into**: `WorkflowValidator.validate()` step 4 (`_validate_data_flow`); blocks `pflow run` via `WorkflowRunner._validate()`; surfaces in `pflow analyze-cache` "Blocking errors" via the `_is_cache_focused_for_advisory` predicate that hard-codes this ID; listed in the MCP tool docstring at `execution_tools.py:526`.
- **Provenance**: empirically verified across Opus 4.1/4.5/4.7, Sonnet 4.5/4.6, Haiku 4.5 — see the maintainer note at `data_flow.py:1154-1156` quoting the verbatim provider error.
- **Tested**: 8 negative tests in `test_prompt_cache_validation.py`, per-id sample at `test_cache_analysis_per_id_coverage.py:363-371`, real-emission test at `:1423-1447`, baseline case at `04-warning-catalog/20-llm.thinking-temperature-mismatch/`.

The followups doc had said *"This item remains broader than both [#385, #368]"* — the broader sub-cases turned out to be either unspecified (GH #368 referenced by issue number only with no constraint shape in-repo) or speculative (OpenAI reasoning rejecting `temperature` is industry knowledge but has zero documentation/tests/examples in this codebase; `tests/test_core/test_prompt_cache_validation.py:1144` explicitly notes Gemini accepts non-1 temperature with no symmetric OpenAI note). Adding constraints without empirical verification across model versions — the bar GH #385 met — would risk false positives.

### The architectural decision (Option A)

Three options presented:
- **A**: close F#21 as substantially shipped; tighten gaps with regression-locking tests + baseline + doc fixes. ~2.5h, zero risk.
- **B**: speculatively add OpenAI/Opus 4.7 constraints. ~1 day, false-positive risk without empirical verification.
- **C**: build a constraint-registry refactor without new constraints. ~0.5d, speculative infrastructure (Bundle 5 Option B precedent rejected this shape).

Selected **A**. Reasoning: this is the same pattern Bundle 1 (F#1 closeout as misframed) and Bundle 5 (Option B scope narrowing) followed — when investigation reveals the issue is already substantially done, the highest-leverage action is locking what works against regression while documenting the closeout reasoning so future contributors don't reopen on the same misframing.

### What the bad shape and rendered error look like

This is the empirically-verified failure mode the validator catches today, end-to-end:

```markdown
- id: deep-think
  type: llm
  params:
    model: anthropic/claude-opus-4-7
    reasoning_effort: high          ← turns on Anthropic extended thinking
    temperature: 0.3                ← but Anthropic REQUIRES temp=1.0 when thinking is enabled
  prompt: "Think deeply about: ${article}"
```

`pflow workflow.pflow.md ...` halts at validation, **before any node dispatches**:

```
Error: Cache validation failed
  [llm.thinking-temperature-mismatch] Node 'deep-think': temperature 0.3 conflicts
  with reasoning_effort 'high' on model anthropic/claude-opus-4-7 — Anthropic
  requires temperature=1.0 when extended thinking is enabled.
  → Set temperature: 1.0 in this node's params.

(no nodes executed; no money spent)
```

For sub-workflows, the diagnostic propagates with a step-pointer prefix via `_add_child_provenance`:

```
[llm.thinking-temperature-mismatch] In step 'invoke-child' sub-workflow:
  Node 'deep-think': temperature 0.3 conflicts with reasoning_effort 'high'
  on model anthropic/claude-opus-4-7 — Anthropic requires temperature=1.0
  when extended thinking is enabled.
```

Structured JSON shape additionally carries `sub_workflow_step` and `sub_workflow_path` context fields for agent consumption.

### What Bundle 3 tightened

Four independent items shipped — three in parallel via `code-implementer` subagents, one inline. Each guards a specific regression class:

1. **CLI integration test for pre-dispatch blocking** (`tests/test_cli/test_validation_before_execution.py:119-170`, `test_thinking_temperature_mismatch_blocks_before_any_execution`). Mirrors the canonical `test_unknown_node_caught_before_any_execution` pattern at `:75-117` — proof-file marker that the shell node would create *if executed*, asserted absent after `pflow run` fails. **Guards**: a future refactor of `WorkflowRunner` (parallelizing init, reordering pre-flight, etc.) that accidentally lets a node dispatch before validation halts. Unit tests at the validator level cannot catch this. No real LLM call — the validator halts before any LLM dispatch, which is the contract being tested. Mutation-protective: if `_validate_thinking_temperature_compatibility` returned no diagnostics, the workflow would proceed to dispatch the shell node and create `proof_file`, failing the third assertion.

2. **Sub-workflow propagation baseline** (`.taskmaster/tasks/task_159/baseline/04-warning-catalog/20b-llm.thinking-temperature-mismatch-subworkflow/`). Parent workflow invokes a child workflow whose LLM node has the bad shape. Locks the rendered `"In step 'invoke-child' sub-workflow:"` prefix in `blocking_errors[].message` AND the structured `sub_workflow_step`/`sub_workflow_path` context fields. **Guards**: a future refactor of child-IR resolution (cache_render walker, sub-workflow boundary contract, `_add_child_provenance` machinery) that silently loses propagation for this specific catalog ID. Generic sub-workflow propagation tests for OTHER IDs (`cache.invalid-on-non-llm`, `cache.sub-workflow-cache-undeclared`) would not catch an ID-specific regression. Generated by `regenerate.sh` (not handcrafted) so it goes through the same harness `verify.sh` diffs against, byte-identical to canonical output.

3. **Stale CLAUDE.md catalog count** (`src/pflow/core/cache_analysis/CLAUDE.md`). Two locations claimed 26 entries; code has 30 (`EXPECTED_CATALOG_COUNT = len(CACHE_WARNING_CATALOG)` at `warning_catalog.py:945`). Replaced hand-counted numbers with a reference to the auto-derived constant + removed the enumerated catalog list that was guaranteed to drift. **Guards**: documentation honesty. Wrong counts erode trust in everything else the doc claims — same hygiene argument that drove Bundle 1's unified `"cost without caching"` terminology.

4. **F#21 closeout in followups doc** (`.taskmaster/tasks/task_159/implementation/reports/open-bugs-and-ux-followups.md`). Moved F#21 from "open backlog" framing to documented closeout with: what shipped (catalog + validator + wiring + tests + baseline + empirical verification), what Bundle 3 tightened (the four items above), why broader sub-cases stay open-but-scoped (GH #368 unspecified, OpenAI reasoning unverified, Gemini permissive, `max_tokens` unmodeled), and explicit reopen criteria (concrete failure mode + verbatim provider error + reproducible `.pflow.md` + multi-model verification). **Guards**: a future contributor reopening F#21 on the same misframing — the precedent Bundle 1 set with F#1's closeout.

### Why no scratchpads repro

The original Option A plan included a `scratchpads/pflow-cache-repros/repro-10-thinking-temperature-mismatch.pflow.md` for agent UX. User pointed out scratchpads are throwaway — gitignored by convention, evaporates at PR merge. The lasting artifact is this progress log entry. The "what the bad shape looks like + rendered error" demonstration above replaces what the scratchpad would have provided, in a location that persists to the merged history.

### Verification

- **Focused CLI tests**: `tests/test_cli/test_validation_before_execution.py` → **6 passed in 0.35s** (5 pre-existing + 1 new).
- **Broader test surface**: `tests/test_cli/` + `tests/test_core/` (excluding subprocess flakes) → **3389 passed in 26.41s**.
- **`verify.sh` with sandbox-safe `uv` shim**: **86 pass, 1 pre-existing drift** (the documented `/dev/fd/62` sandbox issue at `15-run-flag-interactions/03-report-with-only`; baseline count increased by 1 from the new `20b-...` case).
- **`ruff check`** on touched files: clean.
- **Trace.json drift sanity check**: 4 trace.json files showed cosmetic newline-strip side-effects from `regenerate.sh` (same pattern Bundle 4 observed). Reverted via `git checkout` — not Bundle 3's work, no semantic change.

### Files touched

Production (1 file):
- `src/pflow/core/cache_analysis/CLAUDE.md` (stale count → auto-derived reference)

Tests (1 file):
- `tests/test_cli/test_validation_before_execution.py` (+52 lines for new test)

Baselines (1 new directory, 7 files):
- `.taskmaster/tasks/task_159/baseline/04-warning-catalog/20b-llm.thinking-temperature-mismatch-subworkflow/` (workflow.pflow.md, sub/child.pflow.md, command.sh, README.md, expected-stdout.txt, expected-stderr.txt, expected-exit-code.txt)

Docs (1 file):
- `.taskmaster/tasks/task_159/implementation/reports/open-bugs-and-ux-followups.md` (F#21 closeout + Priority Map update + Closed list update)

### Key insights / learnings

1. **Followups doc framing can outlive its scope.** F#21 was filed before `llm.thinking-temperature-mismatch` shipped; the entry then sat in the doc as if still open. This is the second sprint where investigation revealed an item was already substantially done (Bundle 1's F#1 was the first). The pattern: when picking up a followups item, investigate the actual state of the code BEFORE planning the fix. The followups doc is a snapshot, not a live spec.

2. **Empirical-verification-required is its own design discipline.** The Anthropic constraint was shipped after testing across 6 model versions. The "remaining" F#21 sub-cases lack this verification. Adding speculative provider constraints would erode trust in every analyzer diagnostic — agents would have to second-guess whether a "blocking error" is real or a false positive. Setting the reopen criteria explicitly (concrete failure mode + verbatim provider error + reproducible workflow + multi-model verification) protects this trust boundary.

3. **Regression-locking tests are real implementation work, not "just testing."** The CLI integration test and sub-workflow baseline don't add new behavior, but they make existing behavior contracts machine-verifiable end-to-end. The shell-node proof-file pattern proves "zero spend on blocked workflows" as a structural property; the baseline locks "child diagnostic gets a step-pointer prefix" for this specific ID. Both close gaps that unit tests can't see.

4. **The scratchpad/lasting-artifact distinction.** The original Option A plan included a scratchpads repro for agent UX. User correctly observed scratchpads are throwaway. Inlining the bad-shape demonstration into the progress log itself gives a lasting reference that survives PR merge — the same shift that made Bundle 1's F#1 closeout durable (closeout reasoning lives in the followups doc, not in scratch notes).

5. **Parallel `code-implementer` dispatch with comprehensive briefs continues to compound.** Same pattern Bundle 4 used. Three of the four Bundle 3 items were parallelizable; brief construction took ~10 minutes per subagent; subagent execution ran concurrently with my work on the followups doc closeout. Wall-clock time was dominated by investigation (the searcher findings), not implementation.

### Closes

- **F#21 (validation-time provider constraints, GH #385 case)** — closed in this codebase; the verified case is shipped and now regression-locked end-to-end.

### What's next

Per the cache-ready-opportunity-plan handoff: the projection-model refactor (`scratchpads/cache-ready-opportunity-plan/implementation-plan.md`) is the next major work. It subsumes F#2 (combined `prewarm: true` + `prompt_cache` additive evidence) via Phase 1's component model and F#11 (dynamic-before-static late tail scanning) via Phase 4. Bundle 5's sibling predicate `is_likely_below_min_cache` is the primitive Phase 1's `CacheProjectionComponent.meets_provider_min` consumes.

## 2026-05-15 — Cache ready/opportunity Phase 1-2 checkpoint

Added the explicit row projection model (`cache_configured`, `cache_active`, `cache_ready`, `cache_opportunity`) and moved JSON/cost/text consumers off the public legacy `cacheable_*` fields. The legacy row fields still exist internally as a bridge for older helper paths/tests, but final JSON is now `5.0` and no longer emits them.

Important model fixes landed with the projection scaffolding: declared `prompt_cache:` and `prewarm: true` are now treated as additive mechanisms, `_estimate_batch_prefix_cacheable_tokens` no longer suppresses combined declared+prewarm rows, and `cache.batch-prewarm-below-min` is no longer gated off by `row.declared_prompt_cache`.

Cost math now reads only `row.cache_active.tokens_estimated`; `cache_ready` and `cache_opportunity` are display/actionability signals and must not reduce `first_run_with_cache_hypothetical_usd` or `rerun_within_ttl_hypothetical_usd`. The no-cache baseline still anchors on `row.input_tokens_estimated`.

Unverified at this checkpoint: tests and baselines have not run yet. Next agents should trust the direction of the data model, not the exact renderer polish, until the Phase 3 trace-output test and focused cache-analysis suite are green.

## 2026-05-15 — Cache ready/opportunity Phase 3 checkpoint

Trace indexing now collects non-empty `event["node_output"]` into `TraceExecutionIndex.outputs_by_key`, and `AnalysisContext.resolve_ref_value_for_projection()` resolves parameters/memo first, then workflow-scoped trace outputs. Projection tokenization uses this resolver without changing the older `resolve_ref_value()` contract.

The mandatory dual-producer regression test exists and passes: `test_build_trace_execution_index_collects_top_level_and_batch_node_outputs` loads the live Gemini lyrics-generator trace and proves both a top-level `WorkflowTraceCollector` output (`fetch-sources`) and a batch-item `_capture_item_trace` output (`build-scoring-items.result.genre_only` / `narrator_info`) are index-visible.

Key learning: without resolved cross-workflow edges, nested batch child outputs in the live fixture are scoped as `(None, node_id)`. The projection resolver intentionally falls back to `(None, root)` after `(workflow_path, root)` so these observed batch outputs can still unlock prefix measurement.

Verified: the new dual-producer test passes standalone. Not yet verified: the full `score-choruses` table value and baseline drift.

## 2026-05-15 — Cache ready/opportunity Phases 4-5 checkpoint

Dynamic-before-static evidence now feeds `cache_opportunity` as a structural-edit component while keeping the existing diagnostic path gated for provider-effective recommendations. Below-min structural upside remains visible on the row with `blocked_reason="below_provider_min"` instead of disappearing before the renderer can explain it.

Repeated non-batch stable refs now have a separate detector instead of loosening `_detect_candidate_subsets()` from `>=2` to `>=1`. This preserves the old noise guard for one-shot prompts while allowing repeated rows to surface direct `declare_prompt_cache` opportunities.

The real lyrics-generator canary test has been updated to the new intended behavior: `score-choruses` resolves trace-captured `build-scoring-items.result.*` values and reports a `batch_prefix` ready/opportunity value above 500 tokens, `action="add_prewarm"`, below provider min, and no cost-projection effect.

Verified: `tests/test_core/test_cache_analysis_analyze.py` passes (`180 passed`). Still unverified: renderer snapshots, JSON/MCP schema tests, broader cache-analysis family, and baselines.

## 2026-05-15 — Cache ready/opportunity docs/schema checkpoint

Stopped here for review per user request. JSON schema is bumped to `5.0`; `render_json` emits `cached_now_tokens_estimated`, `cache_configured`, `cache_active`, `cache_ready`, and `cache_opportunity`, and no longer emits public legacy `cacheable_tokens_estimated`, `cacheable_data_source`, or `cache_ratio_pct`.

Docs/schema text updated in:
- `src/pflow/core/cache_analysis/__init__.py`
- `src/pflow/mcp_server/tools/execution_tools.py`
- `src/pflow/core/cache_analysis/CLAUDE.md`
- `docs/reference/cli/analyze-cache.mdx`
- `docs/how-it-works/prompt-caching.mdx`
- `examples/core/prompt-caching.pflow.md`

Important doc correction: Gemini explicit cached-content minimum is documented as 4,096 tokens, matching `llm_capabilities.py`; the old "Gemini Flash 1024" line was wrong for the explicit provider-cache path pflow marks.

Verification state at stop:
- `tests/test_core/test_cache_analysis_analyze.py` passes (`180 passed`).
- Mandatory trace-output dual-producer test passes standalone.
- `tests/test_core/test_cache_analysis_renderers.py` is not yet green. After partial renderer-test migration, latest run had 13 failures, mostly tests still asserting old `could_cache` columns / legacy JSON field placement plus a few synthetic-builder default fields. These are expected migration work, not evidence that the core projection model failed.

Known review focus before continuing:
- Renderer/test migration is incomplete and should be the next phase before baselines.
- Synthetic direct `PerCallRow` test constructors use the compatibility bridge in `PerCallRow.__post_init__`; production rows are populated explicitly in `_build_per_call_row`.
- Re-check text UX after tests are migrated; current renderer is mechanically switched to `ready`/`upside` but not yet baseline-polished.

## 2026-05-15 — Cache ready/opportunity final implementation checkpoint

Completed renderer/test migration, baseline regeneration, and final verification. Text now uses `cached_now` / `ready` / `upside`; JSON remains `5.0` and omits public legacy `cacheable_*` fields. The all-rows/default visibility pass preserves the old low-signal hiding rule for already-good active rows while keeping edit-required opportunities visible.

Two implementation fixes after the docs checkpoint were load-bearing:
- Projection component confidence had a name collision with the analysis-summary `_aggregate_confidence()` helper, which leaked `(confidence, coverage)` tuples into JSON. Renamed the component helper so MCP/JSON round-trips stay pure JSON.
- `_build_cache_projection_components()` was split into component-builder helpers instead of suppressing ruff complexity. This keeps declared-cache, configured-prewarm, candidate, prewarm-opportunity, and dynamic-tail logic independently reviewable.

Baseline drift was classified as intended: schema/additive JSON 5.0 fields, text column rename, no public legacy JSON fields, and behavioral token changes from deeper evidence. The live Gemini lyrics canary now shows `score-choruses` as an `add prewarm` ready/upside row around 1,129 tokens, below Gemini's 4,096-token provider minimum and excluded from cost projection.

Verification:
- Focused cache-analysis/CLI/MCP suite: `773 passed`.
- Baselines: `87 passed, 0 drifted, 0 harness errors`.
- Ruff on touched Python files: clean.
- Near-full sandbox suite with uv-subprocess sandbox failures excluded: `6859 passed, 19 skipped`.

Known sandbox limitation: the unfiltered near-full suite still has 4 `/opt/homebrew/bin/uv` subprocess panics before pflow code starts (`test_importing_helper_module_does_not_import_litellm`, two `pflow save` subprocess validation tests, and `test_analyze_cache_does_not_attempt_remote_model_cost_map`). These match the sandbox failure mode documented by `pflow-sandbox-testing`; they were excluded only for the final broad application run.

## 2026-05-15 — Cache ready/opportunity post-review fixes (B1, P2, P3, U2)

Post-implementation code review of the projection-model work surfaced one blocker-class regression and three smaller hygiene items. All four are fixed here.

### B1 — Test fixtures restored to true optimality

Two baselines silently lost their test intent when the new measurement model exposed that their fixtures weren't actually optimal:

- `06-dry-run-nudge/02-optimal-workflow-silent` — README mutation contract said "an already-optimal workflow stays quiet" but the regenerated baseline started emitting `cache.opportunities-available` from the new analyzer.
- `13-happy-path-interactions/01-batch-cache-prewarm-happy` — README enumerated "NO `cache.batch-prewarm-recommended`, NO `cache.prewarm-no-prefix`, NO `cache.below-min-predicted`" but the regenerated baseline started emitting `cache.batch-prewarm-below-min` (a structurally-similar ID the README didn't enumerate).

The new analyzer was right: both workflows had `prompt_cache: [context]` AND `prewarm: true` but only the system-block cache (`${context}`) was substantial. The user-message prefix before `${item.text}` was the tiny literal "Score this item using the reference document: " (~9 tokens), well below the 1024-token Sonnet 4.5 min. Per DD#11 the two markers are additive (distinct provider breakpoints, system + user-message), so `prewarm: true` needs its own substantial prefix to be effective.

Fix: added `_shared/long-stable-rubric.txt` (~1600 tokens of scoring instructions) and gave both fixtures a `rubric` input referenced in the prompt body before `${item.text}`. `${rubric}` is NOT in `## Cache`, so there's no shadowing with the declared `${context}` chunk. Both fixtures now have meaningful content in both cache scopes, both clear the provider min, both stay silent. READMEs rewritten to explain the additive-mechanism model and the new mutation contract.

### P3 — Placeholder explainer is conditional

Initial fix added `— means the column does not apply to this row.` and `? means the column applies but the token count can't be measured yet (run the workflow once to populate).` to the `How to read each row:` bullets. User caught a UX regression: those lines printed even when no row in the table used those placeholders, adding noise instead of clarity.

Final fix: new `_per_call_placeholder_usage(rows, visible_columns)` helper walks visible cells and reports `(any_em_dash, any_question)`. The explainer only emits each placeholder line when at least one visible cell would render that placeholder. Verified:

- Greenfield baseline (no placeholders): no extra lines.
- Gemini canary (some `—`): `—` line only.
- Steady-state-text-hidden mode (would show `?`): explainer suppressed entirely because per-call section is hidden anyway.

### U2 — Doc prose vocabulary cleaned

`docs/how-it-works/prompt-caching.mdx` and `examples/core/prompt-caching.pflow.md` both said "ready/cache-active tokens" — mixing the CLI column name (`ready`) with the JSON field name (`cache_active`) in one phrase. Replaced with `ready`/`upside` column-name-only prose. The CLI text doesn't expose `cache_active` as a column; only JSON consumers see that key.

### P2 — diagnostic_ids match the actually-emitted diagnostic

`_declared_projection_component` hardcoded `cache.below-min-predicted` as the diagnostic ID for blocked declared chunks. But when trace evidence (`cache_skipped_reason == "below_min"`) is the source of the block, the actually-emitted diagnostic at `analyze-cache --from-trace` is `cache.below-min-rendered` — a different catalog ID. JSON consumers following `cache_configured.components[].diagnostic_ids` looked up `cache.below-min-predicted` and didn't find it in `analysis.warnings[]`. Same pattern for `_configured_prewarm_projection_component`: hardcoded `cache.batch-prewarm-below-min` when runtime trace evidence would have emitted `cache.prewarm-disabled-below-min`.

Fix: both builders now pick the diagnostic ID by evidence source — runtime-blocked from trace → rendered/disabled IDs; static prediction → predicted/recommended IDs. Verified in `09c-cache.below-min-rendered`: `diagnostic_ids` now reads `["cache.below-min-rendered"]`, matching the emitted `warnings[0].id`.

### Verification

- Cache-analysis/CLI/MCP focused suite: 556 passed.
- Baselines: 87 passed, 0 drifted, 0 harness errors.
- `make check`: clean (ruff, ruff-format, mypy on 209 source files, deptry).
- `make test`: 6837 passed, 4 pre-existing failures unrelated to cache_analysis (`test_routing_failure_in_sub_workflow_propagates_to_parent_trace` and three `test_prep_error_action` tests — verified failing on the base commit before any of this work).
- Pre-commit `pretty-format-json` auto-fix touched 4 baseline `trace.json` files (formatting only, semantic-equivalent); baselines still verify clean.

### Files touched

Production (2 files):
- `src/pflow/core/cache_analysis/analyze.py` — P2 fix (two diagnostic-ID selectors).
- `src/pflow/core/cache_analysis/render_text.py` — P3 fix (conditional placeholder explainer + new `_per_call_placeholder_usage` helper).

Docs/examples (2 files):
- `docs/how-it-works/prompt-caching.mdx` — U2 prose cleanup.
- `examples/core/prompt-caching.pflow.md` — U2 prose cleanup.

Fixtures (1 new, 6 edited):
- New: `.taskmaster/tasks/task_159/baseline/_shared/long-stable-rubric.txt`.
- Edited: `06-dry-run-nudge/02-optimal-workflow-silent/{workflow.pflow.md,command.sh,README.md}`, `13-happy-path-interactions/01-batch-cache-prewarm-happy/{workflow.pflow.md,command.sh,README.md}`.

Baselines: all `expected-stdout.txt` files regenerated (drift was the conditional `?`/`—` explainer lines and the P2-corrected `diagnostic_ids` arrays). 4 `trace.json` files auto-formatted by pre-commit (semantic-equivalent).

### Closes (from the post-review)

- B1 (test fixtures silently rewritten without updating intent) — closed.
- P3 (explainer omits `?`/`—` placeholders) — closed, gated on actual usage.
- U2 (doc prose leaks `cache-active` JSON field name) — closed.
- P2 (diagnostic_ids hardcoded predicted ID for rendered case) — closed for both declared and prewarm components.

## 2026-05-15 — Bundle 7: three diagnostic-quality wins (closes F#17 deferred, F#22, F#19)

Three independent agent-UX wins shipped as one bundle. Each item investigated in
parallel (`pflow-codebase-searcher`) before deciding scope; two of the three
were implemented in parallel `code-implementer` subagents on disjoint file
surfaces. The third (F#19) turned out to be misframed on investigation — same
pattern as Bundle 1's F#1 closeout and Bundle 3's F#21 closeout. Total
wall-clock: ~1.5h dispatch + verification.

### Items

**F#17 deferred — Per-model call counts + `Total LLM calls: N` sibling line.**
Bundle 4 surfaced model names and unnamed-call counts but the followups doc's
deferred half was per-model call counts. User picked **D+b** wording: each
unpriced model gets `(N calls)` inline; CLI cost summary and success_formatter
get a new `   Total LLM calls: N` sibling line for parity with the trace
report's existing `- LLM calls: N` line.

Shape changes are producer-side consistent: `unavailable_models: set[str]` →
`Counter[str]` at both producers (`MetricsCollector.calculate_costs` and
`_LLMSummaryAccumulator.add_leaf`); JSON shape additively bumped to
`list[{"name": str, "calls": int}]` (still within `format_version` 4.x —
consumers gating on `format_version.startswith("4.")` continue to work);
`metrics.total.total_calls` field added so consumers don't have to traverse
the per-call list. Single shared normalizer `unavailable_models_to_counts`
in `metrics.py` handles the legacy `list[str]` shape for forward-compat with
older traces (legacy entries get `count=0` which renders as the bare model
name with no parenthetical).

Singular/plural rule applied throughout: `(1 call)` vs `(3 calls)`. Sibling
line suppressed when `total_calls == 0` (workflow never made an LLM call) —
same "honest unmeasurable" precedent as `format_dry_run_nudge`.

**F#22 — MCP unknown-node-type suggests `pflow mcp sync`.** When the validator
emits `Unknown node type: 'mcp-{server}-{tool}'` and the server IS registered
in `MCPServerManager().list_servers()` but has zero synced tools, the
suggestion text now reads `Run 'pflow mcp sync {server}' to discover tools
for the '{server}' MCP server.` instead of the generic fuzzy-match. Helper
`_mcp_sync_hint_for_unknown_node_type` lazy-imports from
`runtime/compilation/mcp_resolution`, `mcp/manager`, and `mcp/registrar` to
keep the `core/validator` → `runtime/`/`mcp/` boundary clean. Broad
`except Exception` around the MCP infrastructure check so config corruption
can never crash the validator — falls back to fuzzy-match gracefully.

Critical invariant preserved: the `Diagnostic.message` string format
(`Unknown node type: '{node_type}'`) is unchanged. Seven pre-existing tests
across `test_cache_analysis_*.py`, `test_workflow_executor_comprehensive.py`,
and `test_validation_before_execution.py` pin this string. Only `suggestions`
and `context` change. Two new context fields (`mcp_server`, `mcp_sync_required`)
let JSON consumers route on the structured truth; the prose-only consumer
gets the suggestion text.

**F#19 — Closed as misframed.** Investigation showed two reasons the original
"Blocking errors can include fallback/error-path nodes" framing no longer
applies: (1) the cache-vs-other split already exists — Task 159's analyzer
JSON already exposes `blocking_errors[]` (cache-domain ERRORs) and
`other_blocking_errors[]` (non-cache ERRORs surfaced for awareness) as
distinct arrays; an unknown-MCP-fallback-node diagnostic already lands in
the second array, and the text renderer adapts its section header
accordingly. (2) "Conditional path" understates the real risk: an unsynced
MCP fallback node IS genuinely blocking for `pflow save` (validator rejects)
AND `pflow run` (compilation will fail when the error edge is exercised).
Once F#22 lands, the diagnostic suggestion text is itself actionable —
the underlying agent UX concern is resolved at the suggestion layer, not
by reclassifying severity.

Same pattern as Bundle 1's F#1 closeout and Bundle 3's F#21 closeout: when
investigation reveals the followups doc framing predates shipped infrastructure
or misreads severity semantics, the highest-leverage action is documenting
the closeout reasoning + recording reopen criteria so future contributors
don't reopen on the same misframing.

### Why this shape (top-10% simplicity)

Each item followed the same pattern shipped throughout follow-ups-2: **single
source of truth at the producer/seam, structured data flowing to consumers,
no per-site duplicated logic.**

- **F#17**: one `format_unavailable_models_phrase` helper consumed by three
  renderer sites (CLI workflow_output, success_formatter text, trace_report
  markdown); one `unavailable_models_to_counts` normalizer for legacy fallback
  at all three consumer translation points.
- **F#22**: one `_mcp_sync_hint_for_unknown_node_type` helper, one branch in
  the validator emission site. No new module, no new catalog ID, no
  refactor of the surrounding pipeline.
- **F#19**: one closeout doc entry + Priority Map update. No production code
  change required.

### Verification

- **Focused tests**: 254 passed across `test_metrics.py`,
  `test_unknown_model_user_experience.py`, `test_workflow_validator.py`,
  `test_success_formatter.py`, `test_direct_execution_helpers.py`,
  `test_workflow_trace.py`, `test_trace_integration.py`.
- **Pre-existing message-pinning tests**: 7 passed across `test_cache_analysis_analyze.py`,
  `test_cache_analysis_renderers.py`, `test_workflow_executor_comprehensive.py`,
  `test_validation_before_execution.py` — confirms F#22's "Unknown node type"
  message string contract preserved end-to-end.
- **Broader sandbox-safe sweep**: 5534 passed, 1 pre-existing sandbox failure
  (`test_dry_run_subprocess.py` — `error: Failed to spawn pflow` is the
  environmental `uv subprocess` issue documented in prior bundles, reproduced
  on stashed-clean working tree to confirm not introduced by Bundle 7).
- **Full default suite** (implementer): 6862 passed, 1 skipped.
- **Baseline oracle**: `verify.sh` with sandbox-safe `uv` shim — 87 passed,
  0 drifted, 0 harness errors.
- **Targeted `ruff check`** on all 12 touched files: clean.
- **Full `mypy` on `src/pflow/`**: clean (209 source files).
- **Mutation verification**: F#17 — mutating `format_unavailable_models_phrase`
  to always emit `(0 calls)` failed 11 tests across all three render layers
  (mutation reverted). F#22 — forcing `_mcp_sync_hint_for_unknown_node_type`
  to return `None` unconditionally failed the registered-zero-tools test;
  mutating the suggestion text failed the exact-string assertion.

### Fresh-agent cold read (Principle 3 applied)

Per `cli/CLAUDE.md`'s "no internals leak" and "read raw output as fresh agent"
discipline, the rendered output was read cold post-implementation. All three
F#17 scenarios + F#22 diagnostic pass: no JSON field names in prose, no
internal symbols, math is coherent across all three F#17 surfaces (3 + 2 = 5
unpriced; `Total LLM calls: 7` anchors the denominator). The 3-space indent
on the `Total LLM calls` sibling line aligns roughly under "Cost:" — reads
as a continuation, not a stray line.

Borderline phrase noted but left in place: `"without recorded model"` is
pre-existing wording (Bundle 4 introduced it). Slightly opaque to a fresh
agent — could mean "API didn't return it" or "pflow failed to record it" —
but reads as plain English and changing it is scope creep for Bundle 7.

### Files touched

Production (6 files):
- `src/pflow/core/metrics.py` (+50) — helper signature widened to
  `Mapping[str, int]`; `unavailable_models_to_counts` normalizer; `Counter`
  shape at producer; JSON shape upgrade; `total_calls` added to
  `metrics.total`.
- `src/pflow/runtime/workflow_trace.py` (+10) — `_LLMSummaryAccumulator`
  Counter shape + `as_dict()` JSON emission.
- `src/pflow/cli/workflow_output.py` (+25) — `_display_cost_summary`
  consumer: integrate `N calls` into priced cost line; add
  `   Total LLM calls: N` sibling line for unpriced cases.
- `src/pflow/execution/formatters/success_formatter.py` (+15) — same
  pattern (CLI/MCP parity contract).
- `src/pflow/core/trace_report.py` (+2) — translator-only update (consumes
  new helper signature; the `- LLM calls: N` line was already there).
- `src/pflow/core/workflow/validator.py` (+64 / −1) — module-level
  `_mcp_sync_hint_for_unknown_node_type` helper (47 lines); 16 modified
  lines in `_validate_node_types` emission site for branch order.

Tests (6 files):
- `tests/test_core/test_metrics.py` — new `TestCalculateCostsCounterShape`
  class; rewrote `TestFormatUnavailableModelsPhrase` for new signature.
- `tests/test_core/test_unknown_model_user_experience.py` — assertions
  migrated; new `test_rendered_phrase_includes_per_model_call_count`.
- `tests/test_execution/formatters/test_success_formatter.py` — fixture
  builder accepts new shape; 4 new tests for sibling line.
- `tests/test_cli/test_direct_execution_helpers.py` — symmetric CLI updates.
- `tests/test_runtime/test_workflow_trace.py` — new
  `test_llm_summary_unavailable_models_per_model_call_counts` + existing
  assertions migrated.
- `tests/test_core/test_workflow_validator.py` (+205) — new
  `TestUnknownMcpNodeSyncHint` class with 7 tests covering: registered
  server with zero tools, registered with synced tools (falls through to
  fuzzy), unregistered server, non-MCP node type, unparseable name, MCP
  infrastructure exception, and message-string preservation.

Docs (1 file):
- `.taskmaster/tasks/task_159/implementation/reports/open-bugs-and-ux-followups.md`
  — F#19 closeout with reasoning + reopen criteria; Priority Map updated;
  F#17 marked closed.

### Implementation efficiency

Investigation: three parallel `pflow-codebase-searcher` agents reported in
~70 seconds wall-clock per item (concurrent). Implementation: F#17 and F#22
in parallel `code-implementer` subagents on disjoint file surfaces (zero
conflict risk); F#19 handled inline by the parent agent while implementers
ran (docs-only). Wall-clock dominated by F#17 (~16min — the broader file
surface) rather than dispatch overhead. F#22 finished in ~7min.

### Key insights / learnings

1. **The "is X open?" question requires reading current code, not the
   followups doc.** F#19 is the third item this sprint that turned out to
   be misframed once the current state of shipped infrastructure was
   inspected (F#1 in Bundle 1, F#21 in Bundle 3). The followups doc is a
   snapshot artifact, not a live spec; entries can lag behind shipped work
   for months. When picking up a followups item, investigate the actual
   current state of the code before scoping the fix.

2. **Fresh-agent cold reading catches what unit tests miss.** Unit tests
   pin assertion-level behavior; they don't catch "this rendered phrase
   sounds like pflow internals to a fresh agent." Principle 3 (read raw
   output as fresh agent before classifying) flagged that `"without
   recorded model"` is borderline-opaque — out of scope for Bundle 7 but
   worth flagging for the next sweep.

3. **Producer-side single source of truth compounds across bundles.**
   Bundle 4 established `format_unavailable_models_phrase` as the one
   helper for the pricing-unavailable phrase. Bundle 7 extended its
   signature in a single place; all three consumer sites consumed the
   change with a one-line translator update. If the wording had been
   inlined at each consumer, Bundle 7 would have been 3× the diff and a
   real drift surface.

4. **Lazy imports are the right shape for optional infrastructure.** F#22's
   helper lazy-imports MCPServerManager, MCPRegistrar, and
   `_parse_mcp_node_type` so validators in environments without MCP
   configured don't pay the import cost. The broad `except Exception`
   around the infrastructure check completes the defensive picture:
   validation never crashes because of an MCP-side issue.

### Closes

- **F#17 deferred** (per-model call counts) — closed by D+b implementation.
- **F#22** (MCP sync hint in unknown-node-type) — closed.
- **F#19** ("Blocking errors" can include fallback/error-path nodes) — closed
  as misframed; reopen criteria recorded.

### What's next

Per the cache-ready-opportunity-plan handoff: another agent is taking Bundle 6
(staleness signals + `--list-traces`) in parallel. Remaining followups from
the original triage that still have open status: F#11 (dynamic-before-static
late-tail scanning — partially shipped via Phases 4-5), F#5/F#6 (provider TTL
expiry detection — needs design), F#7 (`--list-traces` — Bundle 6 will close),
F#8 (iteration diff view), F#10 (greenfield cost gating audit), F#22's
sibling cross-workflow consumer detection (S#15+S#17+S#20 — its own task).

## 2026-05-15 — Cache ready/opportunity closeout: rationale (lifting WHY into the durable artifact)

The implementation plan at `scratchpads/cache-ready-opportunity-plan/implementation-plan.md` is being removed (scratchpads are throwaway per Bundle 3's lesson — the progress log is the lasting artifact). The six prior checkpoint entries trace WHAT shipped phase-by-phase, but the load-bearing WHY lives only in the plan. This entry lifts the rationale before deletion so future contributors (Task 160 architectural refactor, projection-model extensions, anyone wondering why four projection fields exist) read it in the durable artifact.

### The motivating problem

`PerCallRow.cacheable_tokens_estimated` was overloaded. It tried to answer two distinct agent questions with one number:

- **"Where should I spend optimization effort?"** — agents triaging a workflow want maximum unrealized upside.
- **"What's already cached or one-edit-away?"** — agents validating a fix want to confirm caching is in place.

A single scalar can't answer both. Worse, the old detector's `>=2 shared-ref` rule reported only what could be proven safely from the narrowest evidence — literal stable text and trace-resolved code-node outputs were invisible to it. Result: agents reading `could_cache: 41` on a row with ~900 tokens of provably-cacheable stable prefix would either (a) declare the workflow already-optimized when ~860 tokens of upside remained, or (b) chase the 41-token figure as if it represented total opportunity.

### The two-question split — `cache_ready` vs `cache_opportunity`

The core UX insight that the four-projection model encodes:

- **`cache_ready`**: "Can an agent unlock these tokens with a **direct cache configuration edit**, without moving prompt content?" High when the prompt is already in cache-friendly order (stable content before dynamic refs) and the only missing piece is the cache declaration itself (`prompt_cache:` or `prewarm: true`).

- **`cache_opportunity`**: "What's the **maximum provable unrealized upside** after whatever edit the note names?" Equal to `cache_ready` when the direct edit also yields the maximum upside (stable prefix already first). Higher than `cache_ready` when prompt reordering unlocks more (dynamic ref currently appears before stable content).

The contrast that made this distinction load-bearing:

```text
Prompt already cache-friendly:                          ready ~= opportunity (both high, add_prewarm)
                                                          → "add prewarm: true; that's all you need"

Dynamic ref before stable content:                      ready ~= 0,  opportunity high
                                                          → "move the dynamic ref after stable content"
```

Both are actionable, but the actions are categorically different. One number can't carry that.

### Measurement-depth shift, not a refactor

`cache_opportunity` is a **fundamentally new measurement**, not a renamed `cacheable_tokens_estimated`. The depth shift across dimensions:

| Evidence source | Old `cacheable_tokens_estimated` | New `cache_opportunity` |
|---|---|---|
| Literal stable text before first per-item ref | NOT tokenized | Tokenized via Phase 3 prefix tokenizer |
| Code-node outputs as stable refs (`${build-X.result.Y}`) | NOT resolvable (old `resolve_ref_value()` didn't read trace event outputs) | Resolved via Phase 3 `trace_outputs_by_key` |
| Refs used by exactly one LLM node | EXCLUDED by `_detect_candidate_subsets` `>=2` rule | Included via prefix tokenization OR Phase 5 non-batch detector |
| Post-refactor upside (move dynamic ref later) | NOT modeled | Modeled via `action="move_dynamic_ref_after_stable_prefix"` |
| Below-provider-min cases | Suppressed at several gates | Always visible with `meets_provider_min=False`, `affects_cost_projection=False` |
| Aggregation across multiple components per row | Winner-take-all over one scalar | Components collected + aggregated; each carries its own `actionability` |

The `score-choruses` canary captures this concretely. The row went from `could_cache: 41` (old) → `ready ~1,129 / upside ~1,129` (new). The 41 figure wasn't wrong — it was the only thing the narrow candidate detector could prove. The new measurement is wider because it draws on evidence sources the old detector didn't consult. **The shift is intentional measurement deepening, not a bug fix.**

### Wrong-model sites fixed by the additive declared-vs-prewarm decision

Three sites in `analyze.py` encoded a false assumption: that declared `prompt_cache:` and `prewarm: true` were mutually exclusive mechanisms competing for the same cacheable bytes. Runtime evidence is unambiguous — they're disjoint provider breakpoints (DD#11): declared chunks render via `_build_system_blocks` (system role); prewarm prefix renders via `_build_user_message_blocks` (user role). Two separate `cache_control` markers per call, additive.

The three sites and their fixes:

| Site | Old (wrong) shape | Fix |
|---|---|---|
| `_per_node_warnings(...)` comment above `cache.batch-prewarm-below-min` | `"when ## Cache is declared, prewarm writes that chunk once via the serialized first call — the prompt-body prefix is irrelevant"` | Deleted. Phase 1's Configured prewarm component directly contradicted it. |
| `_estimate_batch_prefix_cacheable_tokens(...)` walker guard | `if declared_subset or not isinstance(batch, dict): return None` | Lifted the `declared_subset` portion. Walker now runs for combined nodes so the prewarm component has tokens to claim. |
| `cache.batch-prewarm-below-min` gate | `... and not row.declared_prompt_cache` | Removed the `not row.declared_prompt_cache` clause. Component-level `meets_provider_min=False` is structured; the catalog warning must still fire so agents learn prewarm won't serve at the provider regardless of declared cache state. |

These were closed bugs, not new features. Future contributors must not re-introduce the wrong mental model.

### Cost-math invariant preserved

Only `cache_active` feeds cost projections. `cache_ready` and `cache_opportunity` are UX prioritization values — they may not reduce `first_run_with_cache_hypothetical_usd` or `rerun_within_ttl_hypothetical_usd`. The no-cache baseline still anchors on `input_tokens_estimated` per Bundle 1's F#1 closeout (counterfactual #1: "same prompt, no discount" — not "delete cache declaration entirely"). Post-review P2 fix verified `diagnostic_ids` match the actually-emitted diagnostic, locking Phase 6's rule that recommended actions reuse catalog IDs rather than synthesizing from row fields.

### Phase coverage audit

All 7 plan phases shipped. Mapping for the audit trail:

| Plan phase | Where it shipped |
|---|---|
| Phase 1 — Add component projection model without new detection | 2026-05-15 Phase 1-2 checkpoint |
| Phase 2 — Move consumers to explicit fields | 2026-05-15 Phase 1-2 checkpoint |
| Phase 3 — Exact stable-prefix opportunity resolver (dual-producer trace index) | 2026-05-15 Phase 3 checkpoint |
| Phase 4 — Model reorder opportunities as opportunity, not ready | 2026-05-15 Phases 4-5 checkpoint |
| Phase 5 — Repeated non-batch stable refs (separate detector, not `>=1` loosening) | 2026-05-15 Phases 4-5 checkpoint |
| Phase 6 — Recommended actions reuse catalog IDs, never synthesized from row fields | Verified by post-review P2 fix (matched `diagnostic_ids` to actually-emitted diagnostics) |
| Phase 7 — JSON 5.0, docs, baselines | 2026-05-15 docs/schema checkpoint + final checkpoint |

### Completion criteria verified

The plan's completion checklist, audited against the shipped state:

- ✓ `PerCallRow` has explicit `cache_active`, `cache_ready`, `cache_opportunity` projections.
- ✓ Text output no longer uses `could_cache` — column renamed to `cached_now` / `ready` / `upside`.
- ✓ Default row ordering prioritizes opportunity; opportunity does not corrupt cost math.
- ✓ Recommended actions diagnostic-driven (P2 post-review locked this).
- ✓ `score-choruses` canary: `ready ~1,129` / `upside ~1,129`, `action="add_prewarm"`, `meets_provider_min=False`, `blocked_reason="below_provider_min"`, `affects_cost_projection=False`, rendered note mentions "add prewarm" + "below Gemini 4,096 min" (final checkpoint).
- ✓ No regressions in `12-real-world-lyrics-generator/*` outside intended drift; every drift classified before regeneration per the canary protocol.
- ✓ Cost-math counterfactual preserved: `no_cache_hypothetical_usd` computes from `input_tokens_estimated × rate × invocations`.
- ✓ Three wrong-model sites fixed (enumerated above).
- ✓ Dual-producer test exists and passes (Phase 3 checkpoint names it: `test_build_trace_execution_index_collects_top_level_and_batch_node_outputs`).
- ✓ JSON/MCP docs describe new fields + JSON 5.0 legacy removal (docs/schema checkpoint).
- ✓ Baselines verify cleanly: 87 pass / 0 drifted / 0 harness errors (final checkpoint).
- ✓ Progress log documents learnings + deviations.

### What this closeout does NOT capture

Anyone needing the full implementer pre-flight briefing (trace-output dual-producer audit specifics, dangerous shortcuts list, parallel subagent dispatch protocol) should consult Bundles 3 / 4 / 5 progress log entries for the patterns and the cache-analysis CLAUDE.md sections for the current-state semantics:

- `src/pflow/core/cache_analysis/CLAUDE.md` § Projection model
- `src/pflow/core/cache_analysis/CLAUDE.md` § Per-call Unit Contract
- `src/pflow/core/cache_analysis/CLAUDE.md` § token_estimation.py (4-tier hierarchy + symmetric fall-through)

### Files removed

- `scratchpads/cache-ready-opportunity-plan/implementation-plan.md` (1,344 lines) — rationale lifted to this entry; scratchpad deleted.

### Backlog report sync

- `.taskmaster/tasks/task_159/implementation/reports/open-bugs-and-ux-followups.md` now marks the combined `prewarm: true` + `prompt_cache` additive-evidence item closed. The closeout would otherwise contradict the priority map by saying Phase 1 shipped while the durable backlog still listed that same work as the top open item.

### Closes

- Cache ready/opportunity plan — closed; rationale durable in this entry, scratchpad removed.

## 2026-05-15 — Bundle 6 phases 1-3 checkpoint: staleness signals + trace discovery

Implemented the core Bundle 6 surfaces through Phase 3.

Phase 1: trace staleness is now typed on `AnalysisSummary.trace_workflow_relationship` with `trace_model_drift_count`, and text renders non-fresh trace state as an indented continuation under the `Trace:` header. `_resolve_trace_scope` now exposes `appears_as_child`; `_detect_per_node_model_drift` returns `(note, count)`. JSON emits the new summary fields.

Phase 2: `MemoizationCache.get_latest_for_node_with_cache_key()` is additive; the existing 2-tuple `get_latest_for_node()` remains unchanged and is locked by tests. `AnalysisContext` carries `predicted_cache_keys`, prediction notes, and the two accumulator sets. Memo token/value resolution now compares stored memo `cache_key` against predicted keys when available: missing prediction trusts memo, `_PREDICTION_SKIPPED` consumes memo and increments uncheckable, mismatch skips memo and falls through. `_predict_one_workflow` now writes `_PREDICTION_SKIPPED` at the two deliberate skip sites. The pre-existing test expecting skipped nodes to be absent from the map was updated because absence now specifically means "not predicted at all"; attempted-but-skipped is a sentinel.

Phase 3: `list_traces_for_workflow()` reuses the hash-scoped trace collector and shares `_autoload_selection_with_disclosure()` with autoload, so the would-be-autoloaded marker and disclosure note cannot drift. Added `render_traces_list.py` and `pflow analyze-cache --list-traces` in text/JSON modes. Empty trace listings exit 0 per the rev-2 plan; the plan's later edge-case table said exit 1, but that conflicts with the explicit design rationale and was not followed. Model-drift listing distinguishes heterogeneous-model sentinel `""` from unresolvable `None`.

Deviation / missing context: the requested `.taskmaster/tasks/task_126/implementation/progress-log.md` file does not exist in this worktree. I verified the task_126 directory and read the available `task-126.md` plus the starting-context braindump instead. No Bundle 6 implementation decision depended on Task 126.

Verification so far:
- `tests/test_core/test_cache_analysis_*.py tests/test_runtime/test_cache.py tests/test_cli/test_analyze_cache.py`: 803 passed.
- Targeted `ruff check` on touched files: clean.
- Targeted `mypy` on `src/pflow/core/cache_analysis`, `src/pflow/runtime/cache.py`, and `src/pflow/cli/commands/analyze_cache.py`: clean.

Hard parts / next-agent notes:
- The prediction sentinel is intentionally a map value, not a missing key. Missing key preserves legacy trust; sentinel is coverage-honesty.
- The mutable sets on frozen `AnalysisContext` are documented accumulator exceptions. Do not add more mutable context fields without the same explicit pattern.
- `--list-traces` uses `resolve_workflow()` only for current-model comparison. If the workflow cannot be loaded, listing still works and omits drift annotation rather than failing discovery.

## 2026-05-15 — Bundle 6 context-window handoff

Current state: Bundle 6 implementation is functionally complete through docs, tests, and baseline regeneration. New code covers staleness summary fields, memo freshness via predicted cache keys, `_PREDICTION_SKIPPED`, trace listing, `pflow analyze-cache --list-traces`, JSON/text renderers, docs, MCP docstrings, and focused tests.

Verification completed: cache-analysis family + runtime cache + analyze-cache CLI targeted run passed (`803 passed`); all cache-analysis `*_test` files passed separately (`741 passed`); targeted `ruff` and `mypy` were clean. Baseline verify passed except the known sandbox `/dev/fd` drift in `15-run-flag-interactions/03-report-with-only` (`86 passed, 1 drifted, 0 harness errors`). A broader near-full pytest run had `6890 passed, 19 skipped, 4 failed`; all four failures were subprocess tests invoking Homebrew `uv` and failing before pflow code with the known sandbox Tokio/system-configuration panic class.

Remaining cleanup before final response: update the stale `_resolve_ir_static_model_for_node` docstring to reflect that `""` now means declared heterogeneous batch model and `None` means unresolvable/missing; optionally rerun targeted `ruff`/`mypy` after that doc-only patch. No known source-level failing tests remain. Plan deviations to disclose: task_126 progress log path was missing; `--list-traces` empty result exits 0 because rev-2 design contradicted the later edge-case table; the plan's subagent/code-review checkpoint was not run because the active tool instructions only allow spawning subagents when explicitly requested by the user.

## 2026-05-15 — Bundle 6 closeout after continuation pass

Continuation audit found one missed plan site: `_resolve_value_in_workflow_memo()` still called legacy `get_latest_for_node()` directly. It now reuses `context._latest_memo_for_freshness_check()`, so cross-workflow memo value resolution gets the same three-state behavior as token estimation and `AnalysisContext.resolve_ref_value`: missing prediction trusts memo, `_PREDICTION_SKIPPED` consumes memo and counts uncheckable, cache-key mismatch skips memo and counts stale. This was not a cosmetic fix; it closes the explicit plan item for the analyze.py cross-workflow memo resolver and avoids a divergent stale-memo path.

Also updated `_resolve_ir_static_model_for_node()` docs to match the implemented contract: concrete string = resolved model, `""` = declared heterogeneous batch model, `None` = unresolvable/missing model. This matters because `--list-traces` skips drift only for the heterogeneous sentinel, not for every unresolved template.

Verification after the continuation fix:
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_cache_analysis_*.py tests/test_runtime/test_cache.py tests/test_cli/test_analyze_cache.py -q` → `803 passed`.
- Targeted `ruff check` on touched source/tests → clean.
- Targeted `mypy src/pflow/core/cache_analysis src/pflow/runtime/cache.py src/pflow/cli/commands/analyze_cache.py` → clean.
- Baseline `verify.sh` with sandbox-safe `uv` shim → `86 passed, 1 drifted, 0 harness errors`; the only drift is the known sandbox `/dev/fd` case `15-run-flag-interactions/03-report-with-only`.

Plan deviations with reasons: empty `--list-traces` exits 0 because the rev-2 design and Phase 3d explicitly require that despite the later edge-case table saying exit 1; no MCP `list_traces` exposure because the plan marked it out of scope; no subagent `/code-review` checkpoint was run because active tool instructions require explicit user authorization before spawning subagents. The missing Task 126 progress-log path remains a context deviation from the original preflight, already documented above.

## 2026-05-15 — Bundle 6 review-fix closeout

Post-implementation review found real gaps; fixed them rather than accepting the first green run.

Critical fixes:
- Per-workflow `AnalysisContext.build()` calls in `_build_per_call_rows_and_warnings()` and `_emit_partial_declaration_findings()` now preserve `predicted_cache_keys`, prediction notes, and the shared `stale_memo_*` accumulator sets. Before this, the main per-call token path could silently trust stale memo even though predictions existed on the root context.
- Prediction-attempted failure paths now write `_PREDICTION_SKIPPED`: scaffold build failure marks all LLM nodes in that workflow; per-node planner/template skip reasons mark that node. Total prediction outage marks all known LLM nodes. Missing key again means “not predicted,” not “attempted but failed.”
- `_build_parameters_by_workflow()` still allows memo-backed parent values to seed child params because removing that regressed existing cross-workflow projections, but those pre-prediction memo roots are now counted in `stale_memo_uncheckable`. This preserves useful projections while exposing the trust boundary.
- `--list-traces` model detection now honors real `batch.as` aliases (legacy `item_alias` kept only as fallback) and walks nested workflows when building the current model set, avoiding false drift for parent/child model combinations.

Test/doc fixes:
- Added behavior tests for stale LLM memo skipping through `analyze()`, cross-workflow memo value skipping, public-path heterogeneous `--list-traces`, trace-header relationship text, stale-memo footer text, concrete trace paths in list output, and all `--list-traces` mutual-exclusion flags.
- Documented emitted `summary.trace_model_drift_count` in JSON version history, cache-analysis CLAUDE, and MCP docs.
- Added `--list-traces` to CLI docs and the prompt-caching guide; regenerated only the affected guide baseline.

Verification after review fixes:
- `HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_cache_analysis_*.py tests/test_runtime/test_cache.py tests/test_cli/test_analyze_cache.py -q` → `810 passed`.
- Targeted `ruff check` on changed Python source/tests → clean.
- Targeted `mypy src/pflow/core/cache_analysis src/pflow/runtime/cache.py src/pflow/cli/commands/analyze_cache.py` → clean.
- Baseline `verify.sh` with sandbox-safe `uv` shim → `86 passed, 1 drifted, 0 harness errors`; the remaining drift is the known sandbox `/dev/fd` case `15-run-flag-interactions/03-report-with-only`.

Review notes not implemented: richer `--list-traces` drift status enums and structured stale-memo node arrays are valid future UX improvements, but they expand the public JSON schema beyond the plan's additive fields. Current Bundle 6 contract remains counts + typed trace relationship + per-trace drift count/null, with tests covering non-default behavior.

## 2026-05-15 — Bundle 6 multi-agent review pass + four pre-merge fixes

Three review agents (`review-plan`, `review-silent-failures`, `review-feature-interactions`) ran in parallel against the staged Bundle 6 changes, plus an independent reviewer pass. Reviews surfaced four merge-quality items that fit cleanly inside the bundle's contract; richer JSON schema expansions were noted but deferred.

### Fixes applied

**1. Confidence-footer wording: drop pflow-internal vocabulary.** Per CLAUDE.md Priority #4 ("no pflow internals exposed in agent-facing output"), the two new confidence-footer lines used "estimator-tier" and "couldn't predict cache_key" — both leak analyzer-internal symbols. Rewrote `_per_call_confidence_footer` in `render_text.py:2291-2302`:
- `"... using estimator-tier instead"` → `"... using fresh estimates instead"`
- `"... analyzer couldn't predict cache_key for this node"` → `"... freshness could not be verified for this node"`
Added negative assertions to `tests/test_core/test_cache_analysis_renderers.py` so neither `"estimator-tier"` nor `"cache_key"` can regress into rendered text — mutation-protective per the same priority directive.

**2. Timestamp formatting consistency.** The `--list-traces` text renderer printed raw ISO timestamps (`2026-05-15T12:00:00.123456`), while the existing `Trace:` header uses `_format_recorded_timestamp` to produce `2026-05-15 12:00`. `render_traces_list.py` now imports and uses the same helper so the trace listing matches the header. Same minute precision, same source, no double-formatter drift surface.

**3. Structural test locking `_resolve_trace_scope` 3-tuple shape.** Bundle 6 expanded the return tuple from `(root, scope_mismatch)` to `(root, scope_mismatch, appears_as_child)`. `_derive_trace_workflow_relationship` depends on the third element; if a future refactor drops it back to a 2-tuple, the relationship enum silently regresses to `different_workflow` for every parent-redirect case. Added `test_resolve_trace_scope_returns_three_tuple_with_appears_as_child` in `test_cache_analysis_analyze.py` — asserts `len(result) == 3` and unpacks all three elements for both the no-trace and same-workflow paths. The test fails noisily on shape regression rather than silently producing wrong typed signals.

**4. Dry-run latency smoke check.** The hoist runs prediction unconditionally on every `analyze()` call, including the dry-run path. Measured stable warm-run cost on the real lyrics-generator (25 LLM nodes across parent + sub-workflows) via direct `analyze()` invocations: ~330ms after litellm import warm-up; first process pays ~570ms total (litellm + prediction + analysis). Within the plan's documented ~700ms acceptance budget. No regression vs the planned target.

### Verification after fixes

- Cache-analysis + cache + analyze-cache CLI focused suite → `811 passed` (+1 from new structural test).
- `verify.sh` with sandbox-safe `uv` shim → `87 passed, 0 drifted, 0 harness errors` (previously documented sandbox `/dev/fd` drift for `15-run-flag-interactions/03-report-with-only` did not fire on this run).
- Targeted `ruff check` on the 4 changed files → clean.
- Targeted `mypy` on `render_text.py` + `render_traces_list.py` → clean.

### Deferred (non-blocking)

- DRY the two `_*_memo_for_freshness_check` helpers between `context.py` and `token_estimation.py`. The three-state logic duplicates; token-estimation's variant could call the context variant and discard `created_at`. Not a correctness bug.
- Remove `hasattr(memo_cache, "get_latest_for_node_with_cache_key")` and `ctx is None` fallbacks once all test mocks implement the new method. Currently load-bearing for legacy fixtures.
- Update `open-bugs-and-ux-followups.md` to mark S#1, S#16, F#7, F#9 as closed.
- Richer `--list-traces` drift status enums and structured stale-memo node arrays were proposed but expand the public JSON schema beyond Bundle 6's additive contract; defer until a real consumer needs them.

### Files touched

Production (2 files):
- `src/pflow/core/cache_analysis/render_text.py` — confidence-footer wording fix.
- `src/pflow/core/cache_analysis/render_traces_list.py` — timestamp formatter reuse.

Tests (2 files):
- `tests/test_core/test_cache_analysis_analyze.py` — new structural test for `_resolve_trace_scope`.
- `tests/test_core/test_cache_analysis_renderers.py` — updated existing wording assertion + negative assertions blocking the pflow-internal regression.

### Closes

- Final pre-merge polish for Bundle 6. Implementation is merge-ready.
