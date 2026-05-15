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
