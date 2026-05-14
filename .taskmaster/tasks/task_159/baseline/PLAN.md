# Task 159 Baseline — Verification & Refactor-Oracle Plan

> **Audience**: the agent executing this plan. Read end-to-end before starting.
> **Caller**: human (Andreas) reviews the captured outputs once for UX, then keeps them as the regression oracle for Task 160 (the cache_analysis architectural refactor).
> **Posture**: verification specialist. Your job is to *try to break* the implementation, not confirm it works. Tests passing is context, not evidence — the ~6,342 unit tests are heavy on mocks and circular assertions; the real proof is what comes out of `pflow analyze-cache` on a real `.pflow.md` file at the integration seam.

---

## 1. Goal & success contract

Produce a `baseline/` folder under `.taskmaster/tasks/task_159/` containing — for every critical case and important edge case in Task 159's scope — the **exact byte-stable expected outputs** of running specific pflow commands against specific inputs.

Two consumers:

1. **Task 160's implementing agent** runs `verify.sh` after each refactor step. Drift = either a real regression OR an intentional behavior change requiring the user's sign-off. Either way, drift is a STOP signal, not silently merged.
2. **Andreas (human)** reads the captured outputs once now to verify text UX (rendering, ordering, tone), agent UX (JSON shape, warning IDs, error envelopes, file:line in error messages), and end-to-end correctness against expectations.

**Success means**:

- Every case in §6 has its folder populated.
- `verify.sh` re-runs every case, normalizes outputs, and produces zero diffs against the committed `expected-*` files.
- The captured outputs make sense to a human (no crashes, no error spew, formatting holds).
- The plan's adversarial cases (§6 marked `ADV`) all produce the documented failure mode — they DO break the system in the documented way; they don't silently succeed.
- Re-recording the 4 live API cases is documented in `RECORDING.md` (see §5) and reproducible.

**Failure means** any of:

- A baseline case produces output that differs from what this plan documents.
- A baseline case crashes or hangs.
- An adversarial case unexpectedly *succeeds* (silent failure — the worst class of bug).
- Normalization fails to capture some non-determinism, making the baseline non-reproducible.

---

## 2. The two failure patterns this plan defends against

You (the executing agent) will be tempted to:

### Pattern 1: Verification avoidance
"All my unit tests pass, so the system works." **No.** The unit tests have been heavy on mocks throughout this branch. The external review at commit `2f4e0d5e` found 3 critical correctness bugs that 7 specialized review agents missed because the upstream "already-fixed" exclusion list was wrong. Tests passing means *the test passes*, not *the user-visible output is correct*. The baseline is the integration-seam check.

When in doubt: open the `expected-stdout.txt` and read it. Does it look right? Does it crash? Does the JSON parse? Are file paths sensible? Are error messages actionable for an AI agent reading them?

### Pattern 2: Seduced by the first 80%
The happy paths (greenfield, steady-state, simple validator errors) will work on first try. That's not where the bugs live. The bugs live in:

- Edge cases at the boundary (empty cache block, zero-batch, N=1 batch, `prompt_cache: []`)
- Cross-feature interactions (cache × batch × sub-workflow × storage_mode=shared)
- Format-version transitions (2.0.0 traces under auto-load, drift-rejected traces, partial traces)
- Failure modes (workflow not found, unparseable, all-unpriced models, missing API key)
- Adversarial inputs (CRLF, unicode in prose, very long prose, dotted-path collisions)
- Behaviors that are *supposed to be silent* (savings_ratio < 5%, optimal workflows, --no-cache without prompt_cache)

**Your value is in the last 20%.** When you finish the easy cases first and feel relief, that's your signal you have not yet started the real work.

---

## 3. Folder layout

```
.taskmaster/tasks/task_159/baseline/
├── PLAN.md                              # this file (do not modify; a derivative of it is read by Task 160)
├── README.md                            # generated index — every case linked, regenerable
├── RECORDING.md                         # how to (re)record the 4 live cases
├── normalize.py                         # redaction script (committed)
├── regenerate.sh                        # full pipeline: run every case, capture, normalize, write expected-*
├── verify.sh                            # full pipeline: run every case, capture, normalize, diff vs expected-*
├── _shared/                             # shared workflow fragments and trace fixtures
│   ├── fixtures/
│   │   ├── trace-2.0.0-sample.json      # for 2.0.0-backcompat cases
│   │   ├── live-anthropic-basic.trace.json   # recorded once, committed
│   │   ├── live-anthropic-1h-ttl.trace.json
│   │   ├── live-gemini-translation.trace.json
│   │   └── live-anthropic-prewarm-batch.trace.json
│   └── workflows/
│       └── (ad-hoc shared snippets if any)
├── 01-parser-errors/
│   ├── 01-empty-cache-block/
│   │   ├── README.md                    # 1-paragraph: what triggers, expected behavior, mutation contract
│   │   ├── workflow.pflow.md
│   │   ├── command.sh
│   │   ├── expected-stdout.txt
│   │   ├── expected-stderr.txt
│   │   └── expected-exit-code.txt
│   └── 02-multiple-cache-blocks/...
├── 02-validator-errors/...
├── 03-analyze-cache-modes/...
├── 04-warning-catalog/                  # one folder per warning ID (20 IDs)
├── 05-advisory-cases/...
├── 06-dry-run-nudge/...
├── 07-hash-invariants/...
├── 08-no-cache-flag/...
├── 09-help-and-guide/...
├── 10-live-recordings/                  # 4 cases backed by committed trace fixtures
└── 11-end-to-end-ux/                    # 5 cases against examples/core/prompt-caching.pflow.md
```

### Per-case folder contract

Every leaf case folder contains exactly these files (no others):

| File | Purpose | Generated? |
|---|---|---|
| `README.md` | One paragraph: what triggers this case, what the expected behavior is, what mutation in production code would cause this case to start failing. **You write this.** | manual |
| `workflow.pflow.md` (or `fixture/`) | Input under test. For most cases a tiny hand-crafted file. For end-to-end cases, references `examples/core/prompt-caching.pflow.md` directly. | manual |
| `command.sh` | One executable shell line. Uses `$BASELINE_HOME` and `$BASELINE_CASE_DIR` env vars set by the runner. | manual |
| `expected-stdout.txt` | Normalized stdout. **Written by `regenerate.sh`; checked by `verify.sh`.** | generated |
| `expected-stderr.txt` | Normalized stderr. | generated |
| `expected-exit-code.txt` | Single integer. | generated |
| `expected-files/` *(optional)* | Any file pflow generates that we want to lock (e.g. saved workflow file, trace file path component). Tree of normalized files. | generated |

**The `README.md` is required for every case.** Form:

```markdown
# 01 — Empty cache block

**Surface**: 01-parser-errors

**Triggers**: A `## Cache` section with an empty ```cache code block (no prose,
no `${var}`).

**Expected behavior**: `pflow run` exits non-zero with a structured diagnostic.
The error text mentions `Cache` and `at least one`. The error includes
`workflow.pflow.md:N` source line.

**Mutation contract**: if the parser silently accepts an empty cache block (e.g.
the `len(items) >= 1` check is removed), this case fails because the workflow
proceeds past validation and hits a different error (or runs to completion).
```

The mutation contract is what separates this baseline from "captured the output once and forgot why." If you cannot articulate the mutation contract for a case, the case is not pulling its weight — drop it or rewrite it.

---

## 4. Runner & isolation

### Environment

`regenerate.sh` and `verify.sh` both wrap each case run in a controlled environment:

```bash
# Set per-case
export BASELINE_CASE_DIR="<absolute path to case folder>"
export BASELINE_HOME="$BASELINE_CASE_DIR/.run-home"

# Wipe and re-create
rm -rf "$BASELINE_HOME"
mkdir -p "$BASELINE_HOME/.pflow/debug" "$BASELINE_HOME/.pflow/cache"

# Seed any fixtures the case needs (handled by command.sh itself, see below)

# Run with isolated HOME (verified: pflow uses Path.home() consistently)
HOME="$BASELINE_HOME" \
  PFLOW_NO_COLOR=1 \
  NO_COLOR=1 \
  PYTHONHASHSEED=0 \
  TZ=UTC \
  bash "$BASELINE_CASE_DIR/command.sh" \
  > "$BASELINE_CASE_DIR/.raw-stdout" \
  2> "$BASELINE_CASE_DIR/.raw-stderr"
echo $? > "$BASELINE_CASE_DIR/.raw-exit-code"

# Normalize
python "$BASELINE_DIR/normalize.py" "$BASELINE_CASE_DIR/.raw-stdout" > "$BASELINE_CASE_DIR/expected-stdout.txt"
python "$BASELINE_DIR/normalize.py" "$BASELINE_CASE_DIR/.raw-stderr" > "$BASELINE_CASE_DIR/expected-stderr.txt"
mv "$BASELINE_CASE_DIR/.raw-exit-code" "$BASELINE_CASE_DIR/expected-exit-code.txt"
rm -f "$BASELINE_CASE_DIR/.raw-stdout" "$BASELINE_CASE_DIR/.raw-stderr"
```

- `HOME=$BASELINE_HOME` redirects `Path.home()` to the case-local sandbox. Verified: every pflow path that reads home does so through `Path.home()` or `expanduser`, no `PFLOW_*` env override exists. Setting `HOME` is enough.
- `PFLOW_NO_COLOR=1` and `NO_COLOR=1` disable ANSI codes (some renderers may add them).
- `PYTHONHASHSEED=0` defends against any dict-ordering randomness leaking through.
- `TZ=UTC` defends against timestamp variance.
- `LANG=C.UTF-8` if any case shows locale-dependent output (add if needed).

### `command.sh` shape

A typical command file:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$BASELINE_CASE_DIR"

uv run pflow analyze-cache workflow.pflow.md --no-trace
```

Some cases need fixture seeding before running:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$BASELINE_CASE_DIR"

# Seed a recorded trace into HOME's debug dir
cp "$BASELINE_DIR/_shared/fixtures/live-anthropic-basic.trace.json" \
   "$BASELINE_HOME/.pflow/debug/"

uv run pflow analyze-cache workflow.pflow.md --format=json
```

Cases needing memo-cache state seed `$BASELINE_HOME/.pflow/cache/cache.db` from a fixture sqlite the same way (only `07-hash-invariants/` needs this).

### Verification mode

`verify.sh` runs the same pipeline but compares normalized output against the committed `expected-*.txt` instead of overwriting them. Any diff fails verify. Output is a per-case PASS/FAIL line plus a summary of failed cases with their diffs.

---

## 5. Normalization

`normalize.py` applies these substitutions in order:

| Pattern | Replacement | Rationale |
|---|---|---|
| `$BASELINE_HOME` (resolved abs path) | `<BASELINE_HOME>` | per-machine differs |
| `$BASELINE_CASE_DIR` (resolved abs path) | `<BASELINE_CASE_DIR>` | per-machine differs |
| `/Users/[a-zA-Z0-9_-]+/` (fallback for any other home leak) | `<HOME>/` | catches leftover absolute paths |
| `\d{8}-\d{6}` (in trace filenames) | `<TIMESTAMP>` | run-time |
| `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}` (ISO timestamps) | `<TIMESTAMP>` | run-time |
| `[a-f0-9]{32}` (MD5) | `<HASH:32>` | per-content but not relevant to UX |
| `[a-f0-9]{12,16}` (truncated hashes in filenames) | `<HASH:N>` | run-time |
| `~\$\d+\.\d{2,4}` (cost dollars: `~$0.84`) | `~$<COST>` | jittery on token estimation; only normalize when followed by `(partial`, otherwise keep — see below |
| `cache_age_sec":\s*\d+` (in JSON traces) | `cache_age_sec": <AGE>` | live-recording playback artifact |
| `Python \d+\.\d+\.\d+` | `Python <VERSION>` | runtime |
| `pflow\s+v?\d+\.\d+\.\d+` | `pflow <VERSION>` | self-reported |

**Cost dollars carve-out**: small dollar amounts in test workflows are deterministic given fixed prompts + LiteLLM token_counter. Do NOT blanket-normalize `\$\d+\.\d+` — it would mask actual cost-calc regressions in Task 160. Only normalize when:
- The cost is annotated `(partial — N of M nodes use unpriced models)` (the partial number is not the focus).
- The cost is in a per-call live-trace echo where token counts vary by ±5%.

For each case, if a normalization rule is needed beyond the above, document it inline in the case's `command.sh` as a comment AND add it to a per-case `normalize.txt` that `regenerate.sh` reads (not committed; only the normalized output is committed).

`normalize.py` itself is a single-file ~80-line Python script: `if __name__ == "__main__": text = sys.stdin.read(); print(apply_rules(text))`. Keep it boring.

### What you (executing agent) should NOT normalize away

- Warning IDs (`cache.shared-context-undeclared` etc.) — these are the contract.
- Section ordering in text output — drift here is a UX bug.
- JSON key ordering — `format_version` must be the first key.
- Severity levels (`error`, `warning`, `info`) — drift here is a contract bug.
- File:line citations in error messages — these are agent-actionable.
- Confidence labels (`high_from_trace`, `medium_from_memo`, `low_no_data`) — these are the agent-facing data-quality signal.
- Per-call `data_source` (`trace`, `memo`, `estimator`, `heuristic`) — same.
- Token counts (input_tokens, cache_creation_input_tokens, cache_read_input_tokens) — under deterministic mock or recorded trace these ARE deterministic.

---

## 6. Live recordings — `RECORDING.md` contract

`RECORDING.md` (you write it once, alongside the live cases) documents:

1. The 4 live API cases (§6.J).
2. Required env vars (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`).
3. The exact recording command per case.
4. Expected behavior (tokens range, cache_creation/cache_read shape).
5. Where to commit the resulting trace JSON files.
6. **A note that re-recording is a one-time operation; subsequent `verify.sh` runs use the committed traces, not the live API**. Re-record when Task 160 changes the trace format, or when a case is verified manually as a quarterly drift check.

Recording flow:

```bash
export ANTHROPIC_API_KEY=...
export BASELINE_CASE_DIR=/abs/path/.taskmaster/tasks/task_159/baseline/10-live-recordings/01-anthropic-basic
export BASELINE_HOME=$BASELINE_CASE_DIR/.run-home
rm -rf $BASELINE_HOME && mkdir -p $BASELINE_HOME/.pflow/debug

HOME=$BASELINE_HOME uv run pflow run \
  $BASELINE_CASE_DIR/workflow.pflow.md \
  article="$(cat $BASELINE_CASE_DIR/_input-article.txt)"

# Locate the produced trace file and copy to fixtures
trace=$(ls -1t $BASELINE_HOME/.pflow/debug/*.json | head -1)
cp $trace $BASELINE_DIR/_shared/fixtures/live-anthropic-basic.trace.json
```

Then the case's `command.sh` runs `pflow analyze-cache --from-trace _shared/fixtures/live-anthropic-basic.trace.json` against the workflow and captures its output — that's the regression oracle. The trace file IS committed; the live re-record is the one-time operation.

---

## 7. Case enumeration

Naming convention: each case folder is `NN-short-kebab-name`. Each surface gets a 2-digit prefix; cases inside get a 2-digit prefix.

Adversarial cases (the ones the executing agent might miss without the explicit list) are marked `ADV`. **Implement these. They are the 80→100% delta.**

### 6.A — `01-parser-errors/` (10 cases)

Workflow under test always exits non-zero on `pflow run`. Use `pflow run` (not `pflow validate-only` — verify the actual user surface).

| # | Name | Triggers | Mutation contract |
|---|---|---|---|
| 01 | `empty-cache-block` | `## Cache` with ```cache``` containing only whitespace | Parser silently accepts → would-be-error becomes runtime KeyError |
| 02 | `multiple-cache-blocks` | Two ```cache fenced blocks under one `## Cache` | Parser concatenates silently → bytes shipped to LLM not what user expected |
| 03 | `two-vars-in-chunk` | Single chunk with `${a} text ${b}` | Identifier ambiguous → silent ID collision |
| 04 | `duplicate-chunk-id` | `${concept}` appears twice in the same `## Cache` | Same-name collision → undefined which wins |
| 05 | `batch-scoped-ref` `ADV` | Cache references `${item.field}` (only valid inside batch prompt) | Item value differs per call → defeats caching premise; must reject |
| 06 | `invalid-ttl-30m` | `- ttl: 30m` (only `5m` and `1h` valid) | Parser passes through → adapter sends garbage to provider |
| 07 | `unresolved-var` | `${nonexistent}` in cache | Reference resolution miss → KeyError at render time |
| 08 | `prose-only-no-vars` | ```cache``` block with text but no `${var}` | Empty IR → marker placement undefined |
| 09 | `prompt-body-shadows-cache` `ADV` | Same `${var}` in `## Cache` AND in `prompt:` body | Renders twice → bytes diverge from author's mental model; warning IDs `cache.prompt-body-shadows-cache` and `cache.prompt-body-duplicates-cache` differentiate |
| 10 | `crlf-line-endings` `ADV` | Otherwise-valid workflow with `\r\n` line terminators | Regex parsers may mis-tokenize → silent cache-content drift across platforms |

### 6.B — `02-validator-errors/` (8 cases)

These run through `pflow run` validation (structural; fast path per DD#36) and produce `Severity.ERROR` diagnostics.

| # | Name | Triggers | Mutation contract |
|---|---|---|---|
| 01 | `prompt-cache-out-of-order` | `## Cache: [a, b, c]` + node has `prompt_cache: [b, a, c]` | Order check removed → silent cache-prefix drift between calls |
| 02 | `prompt-cache-undeclared-name` | Node has `prompt_cache: [typo]` not in `## Cache` | Reference resolution dropped → silent no-op rendering |
| 03 | `prompt-cache-on-shell-node` | `type: shell` with `prompt_cache: [x]` | Field validation skipped → silent ignore at runtime |
| 04 | `prompt-cache-empty-list` | `prompt_cache: []` (valid, equivalent to absence) | Reject by mistake → breaks intentional opt-out pattern |
| 05 | `subworkflow-references-parent-chunk` `ADV` | Sub-workflow's node has `prompt_cache: [parent_chunk]` (parent declared, child didn't) | Cross-workflow reference accepted → false belief that cache shares; must reject (each workflow's prompt_cache scopes to its own ## Cache) |
| 06 | `cache-content-below-min-predicted` | Cache prose totals < 1024 tokens for sonnet model | Warning suppressed → silent provider no-op, debugged for hours |
| 07 | `unused-chunk` | `## Cache: [a, b]` but no node references `b` | Warning dropped → dead cache code accumulates |
| 08 | `analyze-cache-surfaces-undeclared-name` `ADV` | Same as 02 but verified via `pflow analyze-cache` (after the external review fix in commit `2f4e0d5e`); analyze-cache must surface this as a blocking error, not silently filter | If catalog-ID filter is reintroduced → analyze-cache reports "all clear" on a workflow `pflow run` would reject |

### 6.C — `03-analyze-cache-modes/` (16 cases)

Each mode in both text and JSON. JSON cases assert `format_version: "4.0"` is the first key.

| # | Name | Mode | Format | Notes |
|---|---|---|---|---|
| 01 | `greenfield-text` | greenfield | text | Workflow has shared `${var}` in 3 prompts but no `## Cache`. Expect `cache.shared-context-undeclared` info + suggested ## Cache block with `<DESCRIBE...>` placeholder. |
| 02 | `greenfield-json` | greenfield | json | Same workflow; assert `format_version: "4.0"` first key, suggested_blocks shape, recommended_actions shape. |
| 03 | `steady-state-text` | steady-state | text | Workflow has `## Cache` declared, all nodes opt in correctly. Expect compact "all good" rendering. |
| 04 | `steady-state-json` | steady-state | json | Same workflow; assert no recommended_actions, no suggested_blocks. |
| 05 | `already-optimal-text` | already-optimal | text | Optimal small workflow. Single-line output. |
| 06 | `already-optimal-json` | already-optimal | json | Empty arrays present per JSON contract (not omitted). |
| 07 | `trace-auto-loaded-text` | trace | text | Seeds a 2.1.0 trace into `~/.pflow/debug/`; auto-load matches by `workflow_path`. Confidence: `high_from_trace`. |
| 08 | `trace-auto-loaded-json` | trace | json | Same; assert per-call `data_source: "trace"`. |
| 09 | `trace-explicit-from-trace` | trace | text | `--from-trace _shared/fixtures/live-anthropic-basic.trace.json`. |
| 10 | `trace-no-trace-flag` | trace-disabled | text | `--no-trace` opts out even when matching trace exists. Confidence: `low_no_data`. |
| 11 | `trace-2-0-0-auto-load-skipped` `ADV` | trace | text | Seeds a 2.0.0 trace (no `workflow_path` field) into `~/.pflow/debug/`; auto-load must skip with note. Then explicit `--from-trace path/to/2.0.0.json` works. |
| 12 | `partial-trace-suppresses-recs` `ADV` | partial-trace | text | Trace is from a `--only` partial run. Recommendations and suggested_blocks must be suppressed; cost lines labeled `(executed trace)`. |
| 13 | `all-rows-flag` | steady-state | text | `--all-rows` shows every node, sorted by token volume. |
| 14 | `multi-workflow-text` | greenfield | text | Workflow with sub-workflows; suggested_blocks emitted per target file. |
| 15 | `required-input-absent-info-note` | greenfield | text | Workflow has `required: true` input; analyze-cache called without it. Single info note, not error. Confidence degrades, no crash. |
| 16 | `unknown-workflow-json-error-envelope` `ADV` | error | json | `pflow analyze-cache /nonexistent.pflow.md --format=json`. Stdout must contain `{format_version, error: {id, message, suggestion?}}`. Stderr has human-readable line. Pre-fix this was empty stdout — agent JSON parser would fail. |
| 17 | `drift-rejected-trace-note` `ADV` | trace | text | Trace whose IR hash mismatches the workflow file (drift after edit). Per Task 159 #16 (commit `e373bef9`), this surfaces as a *note*, not silently. |

### 6.D — `04-warning-catalog/` (20 cases — one per ID)

For each of the 20 catalog IDs, a minimal workflow that triggers exactly that ID. The case captures `pflow analyze-cache --format=json` and asserts:

1. The target ID appears in `warnings[]` exactly once.
2. The diagnostic's `severity`, `source`, `id`, `message` template render, and `context` keys all match the catalog spec.
3. (For IDs in `RECOMMENDED_ACTION_PRIORITY`) a corresponding `recommended_actions[]` entry exists.

**Enumerate by name** (do not skip any):

| # | ID | Severity | Triggering shape |
|---|---|---|---|
| 01 | `cache.order-mismatch` | error | Two-chunk `## Cache`; node lists `prompt_cache:` reversed |
| 02 | `cache.unused-chunk` | warning | `## Cache: [a, b]`; only `a` referenced by any node |
| 03 | `cache.invalid-on-non-llm` | error | `prompt_cache: [x]` on `type: shell` node |
| 04 | `cache.shared-context-undeclared` | info | 3 LLM nodes share `${article}` in prompts; no `## Cache` |
| 05 | `cache.sub-workflow-cache-undeclared` | info | Parent passes `${shared}` into child; child has 2+ LLM nodes reusing it but no `## Cache` |
| 06 | `cache.batch-prewarm-recommended` | warning | Batch with size 8, ~2k-token static prefix, no `prewarm:` decl, savings_ratio ≥ 5% |
| 07 | `cache.dynamic-before-static` | warning | Node prompt has `${dynamic_var}` at top, ~2k-token stable rubric below |
| 08 | `cache.padding-advisory` | info | Node `prompt_cache: [b]` when master order is `[a, b, c]`; padding to `[a, b]` net-positive |
| 09 | `cache.below-min-predicted` | warning | `## Cache` declares small chunk (~200 tokens); declared and referenced by sonnet node (1024 min) |
| 10 | `cache.cross-workflow-prose-mismatch` | info | Parent and child both declare chunk `${shared}` but different prose-before |
| 11 | `cache.cross-workflow-rename-detected` | info | Parent passes `concept_brief` → child input named `creative_brief` |
| 12 | `cache.discrepancy` | info | Trace mode; predicted ratio 80% but actual 0% (TTL expired or content drift) |
| 13 | `cache.prewarm-no-prefix` | warning | `prewarm: true` on a batch whose prompt has no static prefix (first batch-scoped ref at position 1) |
| 14 | `cache.consolidate-to-root-recommended` | info | `## Cache` references `${concept.title}` and `${concept.body}`, each below min-tokens but `${concept}` would clear it |
| 15 | `cache.heterogeneous-models-fragment-cache` | warning | 2 nodes share `prompt_cache: [x]` but use different models (sonnet vs haiku) |
| 16 | `cache.first-call-write-penalty` | info | One node uses `prompt_cache: [x]` exactly once (single call, no amortization) |
| 17 | `cache.opaque-prompt` | info | Cache prose is `${var}` literally, no surrounding prose; no agent-readable label |
| 18 | `cache.prompt-body-duplicates-cache` | warning | Node prompt body literally embeds `${concept}` AND has `prompt_cache: [concept]` |
| 19 | `cache.prompt-body-shadows-cache` | warning | Same identifier-name in cache AND in prompt body via different binding |
| 20 | `llm.thinking-temperature-mismatch` | warning | LLM node sets `thinking_effort` but `temperature` differs from required value |

For each: capture text output too if the rendering differs meaningfully (most do). One JSON capture is the regression oracle; one text capture is the human-eyeball UX check.

### 6.E — `05-advisory-cases/` (5 cases)

Cases where multiple warnings interact OR where a behavior is intentionally silent.

| # | Name | What |
|---|---|---|
| 01 | `prewarm-savings-below-5pct-silent` `ADV` | Batch with savings_ratio 3% — explicitly verify NO `cache.batch-prewarm-recommended` warning fires (silent skip per DD#33). If a warning appears here, the threshold logic is broken. |
| 02 | `prewarm-explicit-false-suppresses-warning` | Batch with savings_ratio 50% but `prewarm: false` declared — no warning (decision already made). |
| 03 | `prewarm-explicit-true-no-warning` | Batch with `prewarm: true` and adequate prefix — no warning; auto-prefix marker present in rendered output (verify via trace if available). |
| 04 | `model-fragmentation-and-write-penalty-co-emit` | 2 nodes sharing `prompt_cache: [x]` but different models AND one of them is a single-call → both `cache.heterogeneous-models-fragment-cache` and `cache.first-call-write-penalty` fire. |
| 05 | `cost-projection-excludes-heterogeneous-cohort` `ADV` | Two nodes; one priced model, one unpriced. Verify `summary.actual_vs_no_cache_delta.unavailable_reason` populated, projection_exclusions present, cost rendered as `(projected subset)` not as a misleading delta. |

### 6.F — `06-dry-run-nudge/` (3 cases)

| # | Name | Behavior |
|---|---|---|
| 01 | `dry-run-emits-nudge-when-actionable` | Workflow with `cache.shared-context-undeclared` opportunity → `pflow run --dry-run` footer contains `cache.opportunities-available` info line. |
| 02 | `dry-run-silent-when-optimal` `ADV` | Optimal workflow → `--dry-run` footer has NO cache nudge. If a nudge appears for an optimal workflow, the `summarize() → None` contract is broken. |
| 03 | `dry-run-blocks-on-structural-error` | Workflow with `cache.order-mismatch` → `--dry-run` exits non-zero before any analytical output (DD#36 structural-blocks-runtime contract). |

### 6.G — `07-hash-invariants/` (3 cases)

These use a small Python driver script (one per case) that calls `compute_node_config` directly and prints the resulting hash. Not via CLI because the hash isn't user-visible at the CLI surface — but it IS the contract Task 160 will most likely break, and it's load-bearing for cache correctness (DD#19). The driver scripts go in each case folder.

| # | Name | What |
|---|---|---|
| 01 | `no-prompt-cache-hash-stable` | Workflow without `prompt_cache:` produces hash X consistently across two invocations. The byte-stable hash IS committed. If Task 160 changes how non-cache nodes are hashed, this test fails — meaning existing memo entries would silently miss. |
| 02 | `distinct-cache-content-distinct-hash` `ADV` | Two workflows identical except for one cache chunk's content → distinct hashes. Documents that pre-DD#19, this would have been a silent stale-result bug. |
| 03 | `dict-key-ordering-deterministic` `ADV` | Two cache values that are dict objects with different Python insertion order → same rendered JSON → same hash. (DD#13: deterministic JSON serialization.) |

### 6.H — `08-no-cache-flag/` (2 cases)

| # | Name | Behavior |
|---|---|---|
| 01 | `no-cache-disables-memo-only` | Workflow with cache_control + memo. Run twice with `--no-cache`; both invocations should produce trace events with `cache_control` markers (provider caching active), but `cache_source` should not appear (memo bypassed). Verify trace JSON shape, NOT just runtime output. |
| 02 | `analyze-cache-no-cache-flag-no-effect` | `pflow analyze-cache --no-cache` produces same output as without flag (per DD: --no-cache scope is memo-only). |

### 6.I — `09-help-and-guide/` (5 cases)

| # | Name | Captures |
|---|---|---|
| 01 | `analyze-cache-help` | `pflow analyze-cache --help` |
| 02 | `run-help-mentions-no-cache-and-dry-run` | `pflow run --help` — verify `--no-cache` scope text and `--dry-run` cache-nudge mention |
| 03 | `guide-caching-full` | `pflow guide caching` (full text) — agent-facing reference; full content captured for human review |
| 04 | `guide-top-level-mentions-caching` | `pflow guide` — verify caching feature is listed and points to `pflow guide caching` |
| 05 | `analyze-cache-no-args-help-on-error` | `pflow analyze-cache` with no args — agent-actionable error message, exit non-zero |

### 6.J — `10-live-recordings/` (4 cases)

These require API keys; documented in `RECORDING.md`. **The recording is one-time; subsequent verify runs use the committed trace fixture.**

| # | Name | Recording flow | What baseline captures |
|---|---|---|---|
| 01 | `live-anthropic-basic` | `examples/core/prompt-caching.pflow.md` with article fixture; record trace with default 5m TTL | `analyze-cache --from-trace <recorded>.json` text + JSON output. Verifies: per-call `data_source: trace`, cache_creation/cache_read populated, ratio computed, no spurious warnings. |
| 02 | `live-anthropic-1h-ttl` | Same workflow + `- ttl: 1h` in `## Cache`; record one run, then RECORD A SECOND RUN within 1h | Two-run trace seq verifies that cache_read fires on the 2nd run; analyze-cache `--from-trace` on the 2nd-run trace reports cache_read tokens. |
| 03 | `live-gemini-translation` | Same workflow shape; model `gemini/gemini-2.5-flash`; record trace | Verifies LiteLLM `cache_control` → `cachedContents` translation produced a real provider hit (cache_read > 0 on call 2+). |
| 04 | `live-anthropic-prewarm-batch` | Batch workflow with `prewarm: true`, batch size 4 | Verifies serialize-first-then-fan-out: trace shows call 1 has cache_creation, calls 2-4 have cache_read. analyze-cache reports realized savings. |

For each: commit the trace JSON to `_shared/fixtures/`, write the workflow + command + expected outputs in the case folder.

### 6.K — `11-end-to-end-ux/` (5 cases)

The reference workflow is `examples/core/prompt-caching.pflow.md` (the committed Task 159 example). These cases use it directly (the case folder's `command.sh` references the path; no `workflow.pflow.md` in the case folder). They exist for human-readable UX review.

| # | Name | What |
|---|---|---|
| 01 | `e2e-greenfield-text` | `pflow analyze-cache examples/core/prompt-caching.pflow.md --no-trace` — text mode |
| 02 | `e2e-greenfield-json` | Same with `--format=json` |
| 03 | `e2e-with-fixture-trace` | Seed `live-anthropic-basic.trace.json` into HOME's debug; analyze-cache picks it up via auto-load |
| 04 | `e2e-dry-run-footer` | `pflow run --dry-run examples/core/prompt-caching.pflow.md article=...` — verify `cache.opportunities-available` nudge in footer |
| 05 | `e2e-all-rows` | Same as 01 + `--all-rows` |

---

## 7. Top-level scripts

### `regenerate.sh`

```bash
#!/usr/bin/env bash
# Re-runs every case, captures output, normalizes, writes expected-* files.
# Use after intentional behavior changes have been reviewed and accepted.
# Usage: ./regenerate.sh [case-glob]

set -euo pipefail
BASELINE_DIR="$(cd "$(dirname "$0")" && pwd)"
cases=$(find "$BASELINE_DIR" -name 'command.sh' | sort)
[[ -n "${1:-}" ]] && cases=$(echo "$cases" | grep "$1")

for cmd in $cases; do
  case_dir=$(dirname "$cmd")
  echo ">>> $(basename "$(dirname "$case_dir")")/$(basename "$case_dir")"
  # ... (per §4 environment setup)
done
```

### `verify.sh`

```bash
#!/usr/bin/env bash
# Re-runs every case and diffs against the committed expected-* files.
# Drift = a regression OR an intentional behavior change. Either way: STOP.
# Usage: ./verify.sh [case-glob]
# Exit code: 0 if all pass, 1 if any drift, 2 if any case crashes.

set -uo pipefail
# ... (similar to regenerate.sh but with diff instead of overwrite)
```

### `normalize.py`

~80 lines. One regex-substitution pass per rule. Reads stdin, writes stdout. No CLI args except input file path.

---

## 8. What gets committed

```
baseline/
├── PLAN.md                      ✅ commit
├── README.md                    ✅ commit (auto-generated index)
├── RECORDING.md                 ✅ commit
├── normalize.py                 ✅ commit
├── regenerate.sh                ✅ commit
├── verify.sh                    ✅ commit
├── _shared/fixtures/*.json      ✅ commit (live trace recordings)
├── _shared/workflows/*.pflow.md ✅ commit
├── 01-...11-*/*/README.md       ✅ commit
├── 01-...11-*/*/workflow.pflow.md  ✅ commit
├── 01-...11-*/*/command.sh      ✅ commit
├── 01-...11-*/*/expected-*.txt  ✅ commit (the regression oracle)
├── 01-...11-*/*/.run-home/      ❌ gitignore
└── 01-...11-*/*/.raw-*          ❌ gitignore (intermediate)
```

Add `.gitignore` to `baseline/`:

```
**/.run-home/
**/.raw-*
```

---

## 9. Acceptance — what the executing agent must produce

You are done when ALL of these hold:

1. Every case in §6 (A–K) has a populated folder per the §3 contract.
2. Every case folder has a `README.md` with the mutation contract spelled out (not boilerplate).
3. Every adversarial case marked `ADV` produces the documented failure mode (it actually breaks the system in the documented way; if any silently succeed, that is a finding to report — see §10).
4. `regenerate.sh` from a clean checkout produces exactly the committed `expected-*` files (zero diff against itself).
5. `verify.sh` from a clean checkout exits 0.
6. `_shared/fixtures/` has the 4 live trace recordings.
7. `RECORDING.md` documents how to re-record from scratch with required env.
8. The top-level `README.md` is a generated index linking every case with a one-line description.
9. Total case count is approximately as enumerated (76 cases by my count; ±5 for any I miscounted is fine; if you find you need to drop or add a case, document why in `README.md`).
10. **You have personally read at least 10 randomly chosen `expected-stdout.txt` files and confirmed they look right (text formatting holds, JSON parses, error messages are agent-actionable). Note this in `README.md`.**

---

## 10. Findings register

If during execution you discover that an adversarial case unexpectedly *succeeds* (i.e., the system silently does something wrong instead of erroring), or any other "the implementation appears to be wrong here" observation: do NOT silently accept the output as the baseline. Instead:

1. Capture the unexpected behavior in `expected-*.txt` as-is (this is what the system currently does).
2. Add an entry to `baseline/FINDINGS.md` with:
   - Case name
   - What you expected (per spec / per this plan)
   - What actually happened
   - Mutation contract: would your test catch this if it changed?
   - Severity guess (correctness bug? UX wart? doc drift?)
3. Continue. Do not block on the finding; the baseline still serves Task 160 even when it captures a bug. Andreas will triage `FINDINGS.md` after.

This is the verification specialist's most important contribution: cases where the system *should* fail but doesn't are the silent failures that 7 review agents missed earlier in this branch.

---

## 11. What this plan does NOT cover

- MCP server output cases (Andreas decided CLI `--format=json` is enough; trust the parity tests). If task 160 changes MCP behavior, that's a separate baseline.
- The `pflow report` command's cache-related sections — orthogonal to task 159 scope; report rendering is task 108 territory.
- Memoization-cache SQLite shape — per DD#19 the field shape was added cleanly, full DB schema baseline is overkill for this scope.
- Performance benchmarks (token-counter cost, analyze-cache wall-clock).
- Migration/upgrade scenarios (no users in production yet per CLAUDE.md "we have NO USERS yet" note).

---

## 12. Sequencing for the executing agent

Do this in this strict order. Each phase has a verification gate.

**Phase 0 — Infrastructure**
1. Create the folder layout per §3.
2. Write `normalize.py` per §5; unit-test it on 3 hand-crafted inputs.
3. Write `regenerate.sh` and `verify.sh` skeletons per §7.
4. Create `.gitignore`.

**Gate**: A trivial test case (e.g., `pflow --version` → captures output → normalizes version → verify roundtrips) passes verify.sh end-to-end.

**Phase 1 — High-confidence cases first** (build trust in the harness)
5. Implement §6.I (help and guide) — 5 cases. These are stable, easy, show the harness works.
6. Implement §6.A (parser errors) — 10 cases. Each one a structural validation; small fixtures.

**Gate**: 15 cases pass verify.sh; you've personally read ≥3 expected-stdout.txt files and they look right.

**Phase 2 — Catalog coverage** (the most-likely-to-regress surface)
7. Implement §6.D (warning catalog) — 20 cases, one per ID. This is the biggest single batch and the most load-bearing for Task 160.

**Gate**: All 20 IDs emit; for each, the JSON `warnings[].id` contains the target ID exactly once.

**Phase 3 — Validation and analyze-cache modes**
8. Implement §6.B (validator errors) — 8 cases.
9. Implement §6.C (analyze-cache modes) — 16 cases (the trace-related ones use 2.0.0 + 2.1.0 fixture traces; create those fixtures first).

**Gate**: Mode-specific rendering renders correctly; `format_version: "4.0"` is the first JSON key in every JSON capture.

**Phase 4 — Advisory and dry-run**
10. §6.E (advisory) — 5 cases.
11. §6.F (dry-run nudge) — 3 cases.

**Gate**: Silent cases really are silent; loud cases really are loud.

**Phase 5 — Harder corners**
12. §6.G (hash invariants) — 3 cases. Driver scripts.
13. §6.H (--no-cache flag) — 2 cases.

**Gate**: Hash invariants hold; --no-cache scope is memo-only.

**Phase 6 — Live recording one-time** (requires API keys; coordinate with Andreas)
14. §6.J (live recordings) — 4 cases. Record once, commit traces, write case folders.

**Gate**: All 4 traces in `_shared/fixtures/` are 2.1.0 with populated cache_creation/cache_read.

**Phase 7 — End-to-end UX**
15. §6.K (end-to-end UX) — 5 cases against `examples/core/prompt-caching.pflow.md`.

**Gate**: Andreas can read the captured outputs and see what an agent or human user sees.

**Phase 8 — Final**
16. Generate `README.md` index linking every case.
17. Run full `verify.sh` from clean checkout. Zero diff. Report passing case count + any FINDINGS.md entries to Andreas.

---

## 13. Tacit knowledge worth surfacing

These are pitfalls the executing agent will hit if not warned:

1. **`HOME` redirect is necessary AND sufficient**. pflow uses `Path.home()` consistently. Do not also try `XDG_CACHE_HOME` etc. — they do nothing here.
2. **`pflow run --validate-only` does NOT exist** as a separate command surface. Validation runs at the start of `pflow run`. Capture parser/validator errors via `pflow run` (will exit non-zero before LLM calls).
3. **`uv run pflow` is the canonical CLI invocation** in this repo (per CLAUDE.md). Always use it, not bare `pflow`.
4. **The 20-vs-21 catalog count drift**: there's an unmerged plan at `.taskmaster/tasks/task_159/implementation/fix-plans/system-prompts-fragment-cache-warning-plan.md` that would add a 21st ID (`cache.system-prompts-fragment-cache`). At the time of this baseline write, the catalog is 20. If that plan lands during your work, update §6.D to add the 21st case; otherwise stay at 20.
5. **`format_version: "4.0"` is the first key invariant** for `analyze-cache --format=json`. Some test outputs may not have it; assert its position via `head -c 50` of the JSON output (or `python -c "import json,sys; d=json.load(sys.stdin); print(next(iter(d)))"`).
6. **Tracing 2.0.0 has no `workflow_path`**; auto-load must SKIP these. Capture this case with a hand-crafted 2.0.0 trace (look at `_shared/fixtures/trace-2.0.0-sample.json` for shape; can be built by reading any 2.1.0 trace and stripping the new fields).
7. **Drift-rejected traces** are new in commit `e373bef9` — they surface as a *note* now (per Task 159 #16), not silently dropped. The `expected-stdout.txt` for case `03-analyze-cache-modes/17-drift-rejected-trace-note` should contain that note; if it's missing, the fix regressed.
8. **The external review at commit `2f4e0d5e` fixed a critical bug** where `analyze-cache` silently filtered un-IDed validator diagnostics. Case `02-validator-errors/08-analyze-cache-surfaces-undeclared-name` is the regression gate for this. If it fails, the catalog-membership filter has been reintroduced.
9. **Cost normalization is partial, not blanket**. See §5. If you blanket-normalize `\$\d+\.\d+` you mask cost-calc regressions in Task 160 and defeat the baseline's purpose. Be surgical.
10. **The mutation contract per case is what makes this a real test**. If you cannot articulate it, the case is decorative. Drop it.
