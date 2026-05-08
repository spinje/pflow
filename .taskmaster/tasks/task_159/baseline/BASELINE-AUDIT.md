# Baseline Audit — Task 159

> Findings from auditing the 63 captured outputs at
> `.taskmaster/tasks/task_159/baseline/` from the **AI-agent-user perspective**:
> *if I were debugging my workflow and got this output, would it tell me
> what's wrong, why, where, and how to fix it?*
>
> Findings already triaged: F-01 (resolved), F-03 (resolved),
> F-04 (resolved by Tier 3 heuristic deletion). Open: F-02 (TODO fixtures),
> F-05 (visualize blocks). Not re-found here.
>
> **Priority signal from user**: text output, agent UX, and correctness
> are what matter. JSON shape is lower priority. The Tier-3 / Section D
> findings below remain in the report for completeness but should be
> deferred unless they imply a real correctness issue.

## Post-live-verification update (2026-05-08)

After the initial audit was written from captured outputs alone, I
ran several commands live against the lyrics-generator workflow and
the error-case fixtures to ground each finding. Live verification
surfaced a critical context shift:

**The captured baseline runs in a clean env** (`HOME=$BASELINE_HOME`,
no `settings.default_model`, no MCP servers registered). Real users
typically have:

- `settings.default_model` set globally (Andreas has `haiku-4-5`)
- MCP servers registered (so unknown-node-type errors don't fire)

This means **some captured behavior reflects a code path that fresh
agents hit on first install but experienced agents do not**.

| Finding | Live status |
|---|---|
| **A-1** doubled blocking-error message | **CONFIRMED LIVE** in validator-08; source-verified at `render_text.py:640-642` (triage 2026-05-08) |
| **A-2** float precision artifacts | confirmed via JSON re-read |
| **A-3** `unavailable_reason: trace_coverage_partial` when `trace_coverage: none` | confirmed at `analyze.py:3963-3968` (universal "not complete" tag); JSON-only, deferred |
| **A-5** `unavailable_models` redundancy | confirmed |
| **B-1** `model=` empty everywhere | **NARROWED** — only in clean envs (fresh agents); experienced agents see resolved models. Still a valid first-time-agent UX issue. |
| **B-2 through B-8** (lyrics-generator UX) | **CONFIRMED LIVE** — every finding reproduces in the user's actual env |
| **C-1** bracketed catalog ID inconsistency | **CONFIRMED LIVE** |
| **C-2** no workflow path in errors | **NARROWED** — for single-file invocations the agent already knows the file from their command. Still relevant for nested/multi-file errors and CI pipelines. |
| **C-3** validator-02 lacks See also | **CONFIRMED LIVE** |
| **C-4** `<value>` placeholder | confirmed |
| **C-5** `src=low|medium` magic strings | confirmed |
| **C-6** JSON error envelope no suggestion | confirmed |
| **C-7** trace mode notes verbose | confirmed |
| **C-8** per-call header math when 0 visible | confirmed |
| **C-9** `evidence_kind` opaque | confirmed |

**A-3 status (post-triage 2026-05-08)**: source-verified at
`analyze.py:3963-3968` — `unavailable_reason="trace_coverage_partial"`
fires whenever `trace_coverage != "complete"`, including when it's
`"none"`. This is intentional union-vocabulary (universal "not complete"
tag) but the label names only one of the two states it covers. Real
JSON-shape wart; deferred per text-priority directive.

**A-4 removed**: count is technically correct (19 info-severity
diagnostics = 2 recommended actions + 17 cross-workflow renames). The
`_CROSS_WORKFLOW_ALIGNMENT_IDS` filter in `view_helpers.py` routes
renames to a separate section by design. Self-downgraded by author and
removed from this file 2026-05-08 as noise.

### New findings discovered live

- **A-6** (new) — same false-confidence pattern as F-04, but in the
  `tokens=` column, not `cacheable=`. See below.
- **B-9** (new) — `## Blocking errors` section header is misleading
  when surfacing non-cache validator errors under `analyze-cache`.
- **B-10** (new) — `pflow guide` on cache-using workflow puts
  caching topic at line 286 of 1224.
- **B-11** (new) — workflow-header model line awkwardly compounds
  resolved + per-batch-item-varying.

These are added to the relevant sections below.

### Limitations of this audit

- I never ran a workflow end-to-end against a real LLM. All findings
  are from `analyze-cache` static output and `pflow run` validation
  errors.
- I read 13 of 63 cases line-by-line. The other 50 were spot-read or
  skipped (especially surfaces 13/14 happy-path captures and most of
  surface 04 catalog cases beyond a few warning IDs).
- I did not test on different terminal widths, with `NO_COLOR=0`,
  or under `--format=json`/`--mcp` in a streaming consumer context.
- Section A bug claims should be cross-checked against producer code
  before locking — A-3 in particular needs source-code verification.

## How to read this report

Each finding is marked:

- **Severity** — `bug` (correctness — output is wrong/inconsistent/incomplete)
  vs `UX` (output is correct but hard for an agent to act on)
- **Triage** — `wart` (UX issue on top of correct behavior; lock as
  expected behavior + plan a fix) vs `bug` (real correctness issue;
  do NOT lock as expected behavior — fix before Task 160 starts so the
  baseline isn't a Pitfall #19 trap).

Findings are ordered roughly by tier (lyrics-generator first, then
common-path, then JSON/lower-priority).

---

## A. Bugs — output is wrong, locking these via mutation contract is dangerous

### A-1 — Blocking-error rendering duplicates the message

- **Severity**: `bug`
- **Triage**: `bug` — the renderer is emitting the same string twice
  per finding. **This case currently locks the bug as expected behavior;
  fix before Task 160.**
- **What**: In the text rendering of `## Blocking errors`, each entry
  prints: `<message>` → `<location>` → `<message again>`. Three lines
  per finding when there should be two (title + location).
- **Repro**:
  - `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:16-18`:
    ```
    1. In step 'fetch-sources' sub-workflow: Unknown node type: '...'
       fetch-youtube-mcp in fetch-source.pflow.md
       In step 'fetch-sources' sub-workflow: Unknown node type: '...'
    ```
  - `02-validator-errors/08-analyze-cache-surfaces-undeclared-name/expected-stdout.txt:17-19`:
    same shape — message, "summarize", message-again.
- **Impact**: Agent reading this thinks the analyzer surfaced two
  errors when it surfaced one. Worse, the renderer also leaks the
  fact that the body-line is recapitulating the title-line — a "did I
  miss something between these two identical lines?" moment that
  burns agent attention budget.
- **Suggestion**: in `cache_analysis/render_text.py`'s blocking-errors
  formatter, use `<title>` + `<location>` + (optional `<context-detail>`
  ONLY when it adds information — e.g. node type for invalid-on-non-llm,
  available chunks list for undeclared-chunk). For plain
  validator passthroughs that have no extra context, two lines is
  enough.

### A-2 — Float precision artifacts in JSON savings/cost numbers

- **Severity**: `bug`
- **Triage**: `wart` (JSON consumers can `round()` themselves, but
  it's gratuitously ugly for a v1 contract).
- **What**: `estimated_savings_usd` and `savings_usd` carry IEEE-754
  artifacts.
- **Repro**:
  - `04-warning-catalog/15-cache.heterogeneous-models-fragment-cache/expected-stdout.txt:105`:
    `"estimated_savings_usd": 0.004499999999999997`
  - same file line 117: `0.0015000000000000005`
  - `05-advisory-cases/04-model-fragmentation-with-write-penalty/expected-stdout.txt:211`:
    `"cache_creation_cost_usd": 0.007500000000000001`
- **Impact**: Agents quoting these numbers back to humans look
  unprofessional ("we'll save $0.004499999999999997"). LLM consumers
  may also mis-tokenize long-decimal numbers, costing tokens.
- **Suggestion**: in `cost_estimation.py`, round to 6 decimals before
  serialization. Display layer already rounds (`~$0.0045/run`) — do
  the same at the JSON contract layer.

### A-3 — `unavailable_reason: "trace_coverage_partial"` fires when `trace_coverage: "none"`

- **Severity**: `bug`
- **Triage**: `wart` likely; `bug` if a JSON consumer dispatches on
  the reason string.
- **What**: For greenfield/no-trace workflows, `summary.actual_vs_no_cache_delta.unavailable_reason`
  is consistently `"trace_coverage_partial"` even though
  `summary.trace_coverage` is `"none"`. "Partial" implies "we have
  some coverage"; the truth is we have no trace at all.
- **Repro**: every greenfield JSON capture, e.g.
  `04-warning-catalog/04-cache.shared-context-undeclared/expected-stdout.txt:42-44`,
  `13-happy-path-interactions/01-batch-cache-prewarm-happy/expected-stdout.txt:42-44`.
- **Impact**: An agent dispatching on the reason ("if reason ==
  trace_coverage_partial, suggest re-running") would suggest a
  re-run when there was never a run to begin with. Plus the labels
  drift from each other across the JSON tree.
- **Suggestion**: when `trace_coverage == "none"`, set
  `unavailable_reason` to `"no_trace"` (or null with a different
  contract). The two fields must agree.

### A-6 — `tokens=` column shows estimated number for opaque prompts (false confidence — same pattern as closed F-04)

- **Severity**: `bug`
- **Triage**: `bug` — locks the inconsistent honest-unmeasurable
  application. Same root pattern as F-04, which was closed for the
  `cacheable` column but not for `tokens`.
- **What**: Per-call rows for opaque prompts (where the prompt is
  `${var}` resolving to a code-node output) show a tiny token count
  measured from the literal template string, alongside `cacheable=
  ?` and `ratio= ?%` and `opaque-prompt` annotation. The `tokens=`
  column is dishonest where the others are honest.
- **Repro**: lyrics-generator live and captured —
  `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:127`:
  ```
  generate-chorus-options model=<varies> tokens=    3  cacheable=    ?  ratio=  ?%  src=low  opaque-prompt
  ```
  The `3` is the token count of the literal string `${item.prompt}`,
  not of the assembled prompt content (which is opaque).
- **Impact**: Agent reads "tokens=3" and concludes "this is a tiny
  prompt, no caching needed." Reality is the prompt could be 10k
  tokens — the analyzer just can't see it. The `opaque-prompt`
  annotation is the signal, but `tokens=3` is the louder column.
- **Suggestion**: when `cacheable_data_source: "unavailable"` AND
  `opaque-prompt`, render `tokens=    ?` to align with the
  honest-unmeasurable convention. The `cacheable=?` and `ratio=?%`
  fix from F-04 set the precedent; extending to `tokens=` closes
  the matched-pair gap.

### A-5 — `unavailable_models_by_workflow: {}` and `unavailable_models: []` redundancy

- **Severity**: `bug` (low-impact; signals a non-collapsed view)
- **Triage**: `wart` — JSON shape consistency.
- **What**: When no unavailable models exist, both fields render as
  empty (one as `[]`, one as `{}`). When unavailable models exist
  (`05-advisory-cases/05-cost-projection-excludes-heterogeneous-cohort/expected-stdout.txt:64-71`),
  both fields populate with the same data.
- **Impact**: JSON consumer asks "which key do I read?" Both work,
  but for different shapes (flat list vs by-workflow map). The
  duplication invites drift bugs in Task 160.
- **Suggestion**: keep `unavailable_models_by_workflow` (the
  per-workflow map is strictly more informative for multi-workflow
  trees) and drop `unavailable_models` from the contract. If
  consumers need the flat list, they can derive it.

---

## B. Real-world (lyrics-generator) — Tier 1 UX

### B-1 — `model=` empty string everywhere when default_model unresolved

- **Severity**: `UX`
- **Triage**: `wart` — output is technically correct (no model means
  no model), but the rendering is silent rather than typed.
- **What**: Per-call rows render `model=` followed by empty
  whitespace when `settings.default_model` isn't set and the node
  doesn't declare `- model:`. The header explains "no model resolved"
  once, but the per-call rows are silent.
- **Repro**: `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:118-124`:
  ```
  write-lyrics  model=  tokens= 3684  cacheable= ?  ratio= ?%  src=low
  ```
- **Impact**: Agent reading the per-call row has no in-context
  reminder that the row is unmeasurable specifically because of model
  resolution failure. The blank `model=` looks like a missing field
  rather than an explicit "unresolved" state.
- **Suggestion**: render `model=<unresolved>` (matches the existing
  `model=<varies>` typed state on `generate-chorus-options`). Mirrors
  the `PerNodeThresholdEntry.model_state="resolved"` typed
  discriminator pattern from commit `60a2eec8`.

### B-2 — Cross-workflow renames printed with full absolute path twice per row × 17 rows

- **Severity**: `UX`
- **Triage**: `wart`. Density disaster, not correctness — but at this
  density the signal disappears.
- **What**: The `## Sub-workflow boundaries` section emits 17
  entries. Each is 4 lines, with the parent and child workflows'
  full absolute paths repeated on the same long body line:
  ```
  1. Cross-workflow rename — `creative-direction.response` ↔ `creative_direction`
     song-creator → chorus-chooser  (line 97)
     <REPO_ROOT>/...song-creator.pflow.md → <REPO_ROOT>/...chorus-chooser.pflow.md: parent passes ...
  ```
- **Repro**: `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:39-111`.
- **Impact**: After entry 4 the agent stops reading. The
  detector correctly enumerates 17 renames (per-call-site, not
  per-name-pair, which is the right granularity since each site might
  need a different prose-canonicalization fix). But the rendering
  doesn't admit this — every entry is presented with equal weight.
- **Suggestion**: group by `(source_workflow, target_workflow,
  source_line)` and print each rename pair as one indented line:
  ```
  song-creator → chorus-chooser  (line 97):
      creative-direction.response → creative_direction
      song-architecture.response  → architecture
      concept_brief               → creative_brief
  song-creator → review-emotional-architecture  (line 124):
      write-lyrics.response       → lyrics
      creative-direction.response → creative_direction
  ...
  ```
  Same information, ~1/4 the lines. Path is printed once per
  boundary, not twice per rename. The data already exists in the
  JSON `cross_workflow.rename_detections[]` — this is a render-time
  grouping, not a model change.

### B-3 — Sub-workflow drill-in lists 15 absolute paths each ~200 chars

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: After the per-call report, the analyzer emits a paste-ready
  command list:
  ```
  Sub-workflow opportunities don't surface here — run analyze-cache per child:
      pflow analyze-cache <REPO_ROOT>/.taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/analyze-source/analyze-source.pflow.md
      ... 14 more ...
  ```
- **Repro**: `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:129-146`.
- **Impact**: 15 commands × ~200 chars each = ~3 KB of paste-ready
  text. Most agent terminals wrap. The signal (which child workflows
  are reachable) is buried by the path noise.
- **Suggestion**: emit one preamble setting CWD, then relative paths:
  ```
  cd <REPO_ROOT>/.taskmaster/.../lyrics-generator
  pflow analyze-cache analyze-source/analyze-source.pflow.md
  pflow analyze-cache concept-chooser/concept-chooser.pflow.md
  ...
  pflow analyze-cache song-creator/song-creator.pflow.md
  ```
  Or fold to one-per-line of relative paths inside a fenced block.

### B-4 — Notes section has 3 near-duplicate batch lines, ~250 chars each

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: For workflows with N dynamic batch nodes, the Notes
  section emits N near-identical lines, each repeating the workflow
  path and the same explanatory boilerplate.
- **Repro**: `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:148-152`:
  three lines, each ~250 chars, differing only in batch name and
  items expression.
- **Impact**: The unique part of each note is the batch name and the
  items expression (~30 chars). The other 220 chars are repetition.
- **Suggestion**: collapse to one note with a list:
  ```
  · Dynamic batches in lyrics-generator.pflow.md (sub-workflow rows
    not in per-call table, actually_paid_usd is trace-driven):
      fetch-sources    items: ${sources}
      analyze-sources  items: ${fetch-sources.results}
      create-songs     items: ${zip-concepts-with-briefs.result}
    Pass the resolved list as a CLI parameter, or use inline static
    batch items, to enable static child enumeration.
  ```

### B-5 — `## Sub-workflow drill-in` section is misnamed

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: The section title `## Sub-workflow drill-in` implies the
  section will contain drilled-in detail. The actual content is "run
  analyze-cache per child" — a list of paste-ready commands pointing
  AWAY from this output, not detail within it.
- **Repro**: `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:129-146`.
- **Impact**: Agent skimming section titles for "where do I find
  sub-workflow detail" hits this section, sees no detail, and may
  conclude "no sub-workflow opportunities exist" — when really the
  analyzer is saying "I didn't analyze the sub-workflows; here's how
  to."
- **Suggestion**: rename to `## Per-child analyze-cache commands`,
  `## Drilling into sub-workflows`, or `## Recursive analysis`.
  Match the verb of the action (run analyze-cache).

### B-6 — `Recommended actions (ordered by impact)` claim doesn't hold for greenfield

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: The section header promises "ordered by impact" but the
  body shows `savings unavailable` next to each row when no model is
  resolved. There's no impact to order by.
- **Repro**: `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:20-35`,
  `12-real-world-lyrics-generator/03-analyze-cache-song-creator-text/expected-stdout.txt:14-29`.
- **Impact**: Agent reading "ordered by impact" and seeing
  `savings unavailable` on each row may believe the analyzer is
  giving them an arbitrary order and lose trust in the ranking.
- **Suggestion**: when no items have a savings figure, render
  `## Recommended actions (impact unavailable — no model resolved)`
  or just `## Recommended actions` and drop "ordered by impact"
  conditionally.

### B-7 — `actually_paid_usd` jargon leaking into prose

- **Severity**: `UX`
- **Triage**: `wart`. JSON-internal field names appearing in human-facing
  prose.
- **What**: The Notes lines for dynamic batches end with `actually_paid_usd is
  trace-driven and reflects actual execution.` `actually_paid_usd` is
  the JSON field name, not a phrase the agent has any context to
  parse.
- **Repro**: `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:150,151,152`.
- **Impact**: An agent reading "actually_paid_usd is trace-driven"
  must guess that this is a JSON field, then infer from context what
  it means. The note's intent ("the cost number you'll see is the
  measured-from-trace value, not an estimate") is hidden by
  field-name jargon.
- **Suggestion**: rephrase as `the displayed cost is measured from
  trace events, not estimated.` Field names belong in JSON; prose
  should describe behavior.

### B-9 — `## Blocking errors (must fix before save and run)` header is misleading under `analyze-cache`

- **Severity**: `UX`
- **Triage**: `wart`. Surfaces post-validator-unification.
- **What**: When `analyze-cache` surfaces a non-cache validator
  error (e.g., unknown node type, unknown LLM param), it goes under
  `## Blocking errors (must fix before save and run)`. The header
  implies all entries block save/run — true — but doesn't signal
  that the entries may be **tangential to caching**.
- **Repro**: captured in
  `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:14-18`:
  the `Unknown node type: 'mcp-klavis-youtube-...'` error appears
  under cache analysis output. (Live verification confirmed: when
  Andreas runs analyze-cache in his actual env where the MCP server
  IS registered, this error doesn't fire — so this finding only
  reproduces in clean envs.)
- **Impact**: An agent running `analyze-cache` to optimize caching
  sees "unknown node type" as a blocking error and may waste time
  trying to fix it before realizing it's an env-config issue
  unrelated to their caching work.
- **Suggestion**: keep the section but rename to
  `## Blocking errors (workflow won't save or run)` to drop the
  cache-implied "must fix" framing, OR split the section into
  `## Cache blocking errors` and `## Other blocking errors (surfaced
  for awareness)` so an agent knows which it's looking at.

### B-10 — `pflow guide <cache-using-workflow>` puts caching topic at line 286 of 1224

- **Severity**: `UX`
- **Triage**: `wart`. F-03 fix correctly surfaces the topic, but
  ordering is sub-optimal for cache-heavy workflows.
- **What**: Live `pflow guide
  lyrics-generator/lyrics-generator.pflow.md` returns 1224 lines.
  Topic order: `# Batch Processing` (line 1), `# Conditional
  Branching`, `# Prompt Caching` (line 286), `# Song Creator`
  (workflow-specific). For an agent specifically interested in
  caching, the relevant topic is buried.
- **Repro**: live `uv run pflow guide
  .taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/lyrics-generator.pflow.md
  | grep -n '^# '` — caching is the 3rd of 4 detected topics.
- **Impact**: Agents asked "help me set up caching for this
  workflow" pull 1224 lines from `pflow guide` to read 100 lines of
  caching content. Token cost ~5× what's needed. They may also
  miss caching content if they truncate to first N lines.
- **Suggestion**: support `pflow guide <workflow> --topic caching`
  for targeted retrieval (the topic-specific form `pflow guide
  caching` already exists; add `--topic` to filter the
  workflow-detected output too). Or order detected topics by
  feature-density in the workflow (count `## Cache` blocks,
  `prompt_cache:` declarations, etc. and put caching first when
  high).

### B-12 — `pflow guide caching` content has incomplete model-min-tokens coverage

- **Severity**: `bug` (correctness — agents will trust this content)
- **Triage**: `bug` if agents read the guide and conclude the wrong
  minimum applies to their model.
- **What**: `caching.md:204` lists Anthropic min-cache thresholds:
  ```
  - Anthropic: per-model minimum cache size (1024 tokens for Sonnet 4.5;
    2048 for Sonnet 4.6 / Haiku 3.5; 4096 for Opus 4.5+, Haiku 4.5).
  ```
  But `llm_capabilities.py` registers more models in each tier:
  - 1024 tier: `sonnet-4-5`, `opus-4-1`, `opus-4`, `sonnet-4`, `sonnet-3-7`
  - 2048 tier: `sonnet-4-6`, `haiku-3-5`
  - 4096 tier: `opus-4-7`, `opus-4-6`, `opus-4-5`, `haiku-4-5`
- **Repro**:
  ```bash
  grep -A 3 "Anthropic" src/pflow/guide/features/caching.md | head -5
  grep "ModelCapability(\"anthropic\"" src/pflow/core/llm_capabilities.py
  ```
- **Impact**: An agent using Sonnet 4 (1024 tier per source) reads
  the guide as "Sonnet 4.5: 1024" and may assume Sonnet 4 is in the
  2048 tier or unknown-default 4096. They overcorrect — adding
  unnecessary padding to ## Cache. Or worse: an agent using Opus 4
  (1024 tier per source) reads "Opus 4.5+: 4096" and assumes Opus 4
  is also 4096 — wastes time on a non-issue.
- **Suggestion**: replace the inline summary with a generated table
  built from `MODEL_CAPABILITIES` in `llm_capabilities.py`. Or keep
  it static but enumerate every registered model with its min-tokens
  value. Or just say "see `llm_capabilities.py` for the canonical
  list."

### B-13 — `pflow guide caching` `--from-trace` example uses fake filename

- **Severity**: `UX`
- **Triage**: `wart`. Stale doc.
- **What**: `caching.md:71`:
  ```bash
  pflow analyze-cache workflow.pflow.md --from-trace ~/.pflow/debug/trace.json
  ```
  The actual trace filename schema is
  `workflow-trace-<wf_hash>-<safe_name>-<timestamp>.json` per
  `runtime/workflow_trace.py`. `~/.pflow/debug/trace.json` doesn't
  exist after any pflow run — ever.
- **Repro**: `ls ~/.pflow/debug/` shows hash-prefixed filenames; no
  bare `trace.json`.
- **Impact**: Agent copies the example, runs it, gets "trace not
  found" error. The error message at least suggests `pflow
  analyze-cache` without `--from-trace` (which auto-loads), but
  the agent's first impression is "the example is wrong."
- **Suggestion**: replace with the actual schema in the example, OR
  recommend the auto-load path first:
  ```bash
  pflow analyze-cache workflow.pflow.md   # auto-loads most recent matching trace
  pflow analyze-cache workflow.pflow.md --from-trace <path>  # explicit
  ```
  The auto-load path is the better UX anyway and is currently
  buried.

### B-14 — `pflow guide caching` doesn't show example trace-mode rendered output

- **Severity**: `UX`
- **Triage**: `wart`. Doc gap.
- **What**: The guide describes what `pflow analyze-cache` does
  abstractly: "per-node cache ratio, recommended actions, suggested
  ## Cache block (greenfield), warnings about misordered
  declarations, padding advisories." But shows no example output —
  agents have to run the command to see what they'll get.
- **Repro**: read `caching.md:74`.
- **Impact**: An agent learning prompt caching doesn't know what
  "per-node cache ratio" looks like in practice. They get a
  conceptual understanding but no concrete reference.
- **Suggestion**: add a fenced example output block under "Discovering
  Opportunities" showing 5-10 lines of trace-mode rendering with
  realistic numbers. Match the captured baseline shape (e.g., from
  `03-analyze-cache-modes/05-trace-from-trace/expected-stdout.txt`).

### B-16 — Notes section mixes provider-quirk content with rendering-decision content

- **Severity**: `UX`
- **Triage**: `wart`. Discovered live during surface 10 case 03
  (Gemini trace recording).
- **What**: The Notes section in trace mode renders 4 items in a
  flat list:
  1. `Suggested-blocks: ...steady-state suggestions deferred to v1.x.` (rendering decision)
  2. `Discrepancy detection: predicted-key matching unavailable...` (analyzer limitation)
  3. `Discrepancy detection: skipped attribution for 2 trace event(s)...` (analyzer limitation)
  4. `Gemini telemetry note: ...` (provider quirk — high-value)
- **Repro**: live `pflow analyze-cache --from-trace
  <gemini-trace>` produces all 4 in a flat bulleted list; see
  `10-live-recordings/03-gemini-translation/expected-stdout.txt:28-31`.
- **Impact**: The Gemini telemetry note is the most agent-actionable
  of the four (explains why `cache_creation=0` is normal for Gemini
  and the agent shouldn't worry). It's buried at the bottom under
  3 lower-value notes.
- **Suggestion**: group notes by category. Either (a) two
  sub-headers (`### Provider notes` and `### Analyzer limitations`),
  or (b) reorder so high-signal provider notes come first.

### B-17 — Notes reference internal task-management documentation (`progress log §36`)

- **Severity**: `bug` (correctness — dead-link in agent UX)
- **Triage**: `wart` to fix; `bug` if Task 160 locks this
  literal-string in a test.
- **What**: The Gemini telemetry note ends with `Spike 1
  disambiguator (progress log §36) confirmed the marker does real
  work — no caching fires without it.` Agents reading this have no
  access to "progress log §36" — that's an internal task-management
  artifact at `.taskmaster/tasks/task_159/implementation/`.
- **Repro**:
  `10-live-recordings/03-gemini-translation/expected-stdout.txt:31`,
  also reproducible live.
- **Impact**: Agent reads "progress log §36 confirmed the marker
  does real work" and has no way to verify or follow the reference.
  Sounds authoritative but is a dangling pointer for the user-facing
  surface.
- **Suggestion**: replace with `Internal verification: explicit
  cache markers are required for caching to fire on Gemini.` —
  conveys the same meaning without the internal-doc reference. OR
  drop the internal-validation claim entirely; the fact that
  cache_read works is its own verification.

### B-18 — "Workflow has no run history" wording is confusing in trace mode

- **Severity**: `UX`
- **Triage**: `wart`. Vocabulary inconsistency.
- **What**: When analyzing a freshly-recorded trace, the Notes
  section renders:
  ```
  Discrepancy detection: predicted-key matching unavailable
  (workflow has no run history). ...
  ```
  But the analyzer JUST analyzed a trace that IS the run history.
  "No run history" really means "no MEMO cache history" (the
  cross-process SQLite cache, separate from the trace).
- **Repro**:
  `10-live-recordings/03-gemini-translation/expected-stdout.txt:29`.
  Live verifies same wording.
- **Impact**: Agent reads "workflow has no run history" right after
  seeing the analyzer summarize the trace they just produced.
  Internal contradiction. They lose trust in the analyzer's
  understanding of state.
- **Suggestion**: replace "no run history" with "no memo cache
  history" everywhere it refers to the SQLite memo cache. Or
  simpler: "Predicted-key matching unavailable (memo cache
  empty)..." Mirrors the precise vocabulary the rest of the docs
  use.

### B-19 — "no predicted cache_key" message conflicts with cache_key visible in trace

- **Severity**: `UX`
- **Triage**: `wart`. Subtle "predicted" qualifier easy to miss.
- **What**: Notes line says:
  ```
  Discrepancy detection: skipped attribution for 2 trace event(s)
  with no predicted cache_key and no observable signal.
  ```
  But the trace JSON shows `cache_key: 225dd75f25bddb15fdd66038de00c45b`
  on event 0 and `cache_key: e300c4fb2323e0439ce1a91eeffb2d6c` on
  event 1 — both events DO have cache_keys. The "predicted" qualifier
  is what matters: the analyzer couldn't PREDICT a cache_key
  statically (Decision 1 from progress log) so it can't compare
  prediction-vs-actual.
- **Repro**:
  `10-live-recordings/03-gemini-translation/expected-stdout.txt:30`.
- **Impact**: Agent inspects the trace, sees cache_keys present,
  reads "no predicted cache_key" and concludes either (a) the
  analyzer is wrong OR (b) some cache_keys somehow aren't real.
  The "predicted vs actual" distinction is the analyzer's internal
  model; agents have to know that to parse the message correctly.
- **Suggestion**: replace "no predicted cache_key" with "static
  cache_key prediction unavailable" — explicit that prediction
  (not the trace's actual cache_key) is the missing piece. Or:
  "couldn't predict cache_key statically (no parameters in trace)".

### B-20 — Per-call cache report has 2 blank lines before "Hidden" line

- **Severity**: `UX`
- **Triage**: `wart`. Cosmetic — double-spacing artifact.
- **What**: When all rows are filtered, the rendering shows:
  ```
  ## Per-call cache report
    Actual cache ratios from declared `prompt_cache:` subsets.
    Showing 0 of 2 LLM nodes; all-clean rows hidden (--all-rows shows everything).


    Hidden: 2 nodes at ≥80% projected cache ratio with no warnings (rerun with --all-rows).
  ```
  Two blank lines between the header preamble and the "Hidden"
  line. Should be one (or zero if collapsed per C-8).
- **Repro**:
  `10-live-recordings/03-gemini-translation/expected-stdout.txt:21-24`,
  `03-analyze-cache-modes/05-trace-from-trace/expected-stdout.txt:21-24`.
  Confirms the captured baseline.
- **Impact**: Cosmetic. Buys negative attention from agents
  expecting clean rendering.
- **Suggestion**: the table loop probably emits a trailing blank
  line whether or not it produced rows. Strip when row count is 0.
  Folds into C-8's "collapse to one line" suggestion.

### B-15 — `cache.opportunities-available` mentioned but not explained

- **Severity**: `UX`
- **Triage**: `wart`. Doc completeness.
- **What**: `caching.md:236`:
  ```
  `cache.opportunities-available` is the dry-run nudge ID (separate
  from the catalog).
  ```
  No explanation of when it fires, what it looks like, or why it's
  separate.
- **Repro**: search caching.md for `opportunities-available` —
  one mention.
- **Impact**: An agent reading the catalog table sees 21 IDs, then
  reads "+1 separate ID" with no context. They're left to guess
  what dry-run looks like.
- **Suggestion**: 2-3 sentences: "Run `pflow run --dry-run` on a
  workflow with cache opportunities to get a one-line nudge in the
  footer pointing to `pflow analyze-cache`. Silent on optimal
  workflows. Designed to surface savings without requiring agents
  to know `analyze-cache` exists."

### B-11 — Workflow-header model line awkwardly compounds resolved + per-batch-item-varying

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: Live header on lyrics-generator:
  ```
  Workflow: 25 LLM nodes, invocation count unavailable (3 dynamic
  batch nodes) using anthropic/claude-haiku-4-5 +
  generate-chorus-options (model varies per batch item)
  ```
  The "+" syntax suggests "haiku-4-5 PLUS another model"; reality is
  "24 nodes use haiku-4-5; 1 node has per-batch-item model
  variation." The "+" is misleading.
- **Repro**: live invocation, line 3.
- **Impact**: Agent reading "haiku-4-5 + generate-chorus-options"
  may briefly parse `generate-chorus-options` as a model name. (It's
  a node id.) Two-second cost per agent reading — across thousands
  of users that's notable.
- **Suggestion**: rephrase as:
  ```
  Workflow: 25 LLM nodes (24 use anthropic/claude-haiku-4-5;
  generate-chorus-options has per-batch-item model variation).
  3 dynamic batch nodes; invocation count unavailable.
  ```

### B-8 — Per-call token column padding is inconsistent

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: `tokens= 3684` (1 space padding) vs `tokens=    3` (4
  space padding) on adjacent lines.
- **Repro**: `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:118,127`:
  ```
  write-lyrics              ... tokens= 3684 ...
  generate-chorus-options   ... tokens=    3 ...
  ```
- **Impact**: Hard to scan vertically — the digit columns don't line
  up. For a workflow with 25 LLM nodes, this matters when an agent
  is comparing token counts to decide where to optimize.
- **Suggestion**: right-align all numeric columns to a fixed width.
  The column-width logic in `render_text.py` already exists; widen
  the `tokens=` field.

---

## C. Common-path agent UX — Tier 2

### C-1 — Bracketed catalog ID is inconsistent across error sources

- **Severity**: `UX`
- **Triage**: `wart` — agent-greppability gap.
- **What**: Cache validator errors with catalog IDs render as
  `Error: Cache Failure [cache.order-mismatch]`. Parser errors
  (`empty-cache-block`, `multiple-cache-blocks`, `duplicate-chunk-id`,
  `invalid-ttl-30m`) and un-IDed validator errors (`unresolved-var`,
  `prompt-cache-undeclared-name`) render as `Error: Parse Error` or
  `Error: Validation Error` — no bracketed ID.
- **Repro**:
  - With ID: `02-validator-errors/01-prompt-cache-out-of-order/expected-stderr.txt:3`:
    `Error: Cache Failure [cache.order-mismatch]`
  - Without ID: `01-parser-errors/06-invalid-ttl-30m/expected-stderr.txt:1`:
    `Error: Parse Error`; `02-validator-errors/02-prompt-cache-undeclared-name/expected-stderr.txt:3`:
    `Error: Validation Error`.
- **Impact**: Agents triaging by `grep -E '\[[a-z.]+\]'` capture
  some errors but miss the parser/un-IDed validator class. CI
  pipelines filtering by ID can't distinguish "this was a known
  recoverable thing" from "this was novel."
- **Suggestion**: assign catalog IDs (e.g. `cache.empty-block`,
  `cache.multiple-blocks`, `cache.duplicate-chunk`, `cache.invalid-ttl`,
  `cache.unresolved-var`, `cache.undeclared-chunk`) to the parser/un-IDed
  validator errors. The progress log notes this as deferred — the
  audit confirms it's worth doing before Task 160 normalizes the
  rendering layer.

### C-2 — Error messages don't include the workflow file path

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: `Error: Parse Error\n\n<message>\n  At: line 13` — no
  workflow file. Validator errors say `At: node 'summarize',
  nodes[id=summarize].prompt_cache` — also no workflow file.
- **Repro**:
  - `01-parser-errors/01-empty-cache-block/expected-stderr.txt:4`: `At: line 13`
  - `02-validator-errors/01-prompt-cache-out-of-order/expected-stderr.txt:9`:
    `At: node 'summarize', nodes[id=summarize].prompt_cache`
- **Impact**: An agent running multiple workflows in sequence (CI,
  automation pipelines) reads the error in isolation and has to
  cross-reference its own logs to know which file the error came
  from. For a single agent invocation this is trivial; for an agent
  running a fan-out pipeline of 30 workflows, this is real overhead.
- **Suggestion**: prefix `At:` with the workflow path when known:
  `At: <workflow.pflow.md>:13` (parser) or
  `At: <workflow.pflow.md> in node 'summarize', nodes[id=summarize].prompt_cache`
  (validator). The render layer already has the path (per `analyze-cache`
  text mode header) — pull it through to the runtime error path
  too.

### C-3 — Validator-02 (undeclared-name) lacks `See also: pflow guide caching` footer

- **Severity**: `UX`
- **Triage**: `wart`. Inconsistent see-also coverage.
- **What**: `cache.order-mismatch` and `cache.invalid-on-non-llm`
  errors end with `See also: pflow guide caching`. The
  `prompt-cache-undeclared-name` error does not — it has the
  available-chunks list and a follow-on `⚠️ Warnings:` section
  for `[cache.unused-chunk]`, but no see-also.
- **Repro**:
  - `02-validator-errors/02-prompt-cache-undeclared-name/expected-stderr.txt:5-15`:
    no `See also`.
  - `02-validator-errors/01-prompt-cache-out-of-order/expected-stderr.txt:11`:
    `See also: pflow guide caching`.
- **Impact**: Agent encountering an undeclared-chunk error has no
  signposting to the caching guide. Agents that hit other cache
  errors do.
- **Suggestion**: every cache-related error should emit
  `See also: pflow guide caching`. Catalog-IDed errors get it via
  `see_also: ["caching"]` JSON field; un-IDed validator errors
  should be brought into parity (relates to C-1).

### C-4 — Suggested run command uses `<value>` instead of typed placeholder

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: `Suggested:  pflow run <path>/workflow.pflow.md
  article=<value> items=<value>` — every input renders with the
  literal placeholder `<value>`.
- **Repro**: `03-analyze-cache-modes/01-greenfield-text/expected-stdout.txt:12`:
  `Suggested:  pflow run <REPO_ROOT>/examples/core/prompt-caching.pflow.md article=<value>`,
  `13-happy-path-interactions/01-batch-cache-prewarm-happy/expected-stdout.txt:78`:
  `pflow run ... context=<value> items=<value>`.
- **Impact**: An agent that copies the suggested command and runs it
  with `<value>` literal gets an LLM call with the string `<value>`
  as the article — wastes a call, and the analyzer doesn't tell them
  what shape `<value>` should have.
- **Suggestion**: use the input declaration's `type` to emit a typed
  placeholder: `article=<string>`, `items=<json-array>`. Or use the
  input's name in angle brackets: `article=<your-article>`. The
  data is already in the IR (`inputs[].type`).

### C-5 — `src=low|medium|estimator-partial` magic strings in per-call report

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: Per-call rows annotate token confidence as `src=low`,
  `src=medium`, `src=estimator-partial`. The text output has no key
  explaining what these mean.
- **Repro**:
  - `03-analyze-cache-modes/03-steady-state-text/expected-stdout.txt:17-19`:
    `src=medium`
  - `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:118-127`:
    `src=low`
  - `02-validator-errors/07-unused-chunk/expected-stdout.txt:27`:
    `src=estimator-partial`
- **Impact**: Agent has no way to tell what makes one row's data
  more reliable than another's. The full vocabulary
  (`high_from_trace`, `medium_from_memo`, `low_no_data`) IS the
  agent-facing data-quality signal per Task 159 design — but in the
  per-call rendering it's compressed to two unlabelled tokens.
- **Suggestion**: emit a one-line key after the table header:
  ```
  src= high (trace) | medium (memo) | low (estimator/heuristic)
  ```
  And/or document `src=` in `pflow guide caching`.

### C-6 — JSON error envelope for missing workflow has no suggestion

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: `pflow analyze-cache <missing-path> --format=json` returns:
  ```json
  {
    "format_version": "4.1",
    "error": {
      "id": "analyze-cache.workflow-resolution-failed",
      "message": "Workflow '...' not found"
    }
  }
  ```
  No `suggestion` field, no advice on next steps.
- **Repro**: `03-analyze-cache-modes/07-json-error-envelope-unknown-workflow/expected-stdout.txt`.
- **Impact**: Agent that called analyze-cache with a wrong
  saved-workflow name has no path forward — no "did you mean?",
  no `pflow list` hint, no suggestion to check the path.
- **Suggestion**: add `suggestion` to the error envelope with at
  minimum `"Run 'pflow list' to see saved workflows, or check the
  path is correct."` Mirrors the existing `cache.*` warning shape
  (`message` + `suggestions[]`). Fixed this, the contract becomes
  `{format_version, error: {id, message, suggestion}}`.

### C-7 — Trace mode notes section is verbose and uses internal jargon

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: The trace-from-trace case Notes section emits two
  long, jargon-heavy lines:
  ```
  · Discrepancy detection: predicted-key matching unavailable (workflow has no run history). Observable-field attributions (TTL expiry, chunk skipped) still apply.
  · Discrepancy detection: skipped attribution for 2 trace event(s) with no predicted cache_key and no observable signal. Per-node skip reasons (above, when present) explain why prediction was unavailable for the affected nodes; this count covers events whose nodes were not in the analyzed IR (typically batch sub-workflow per-item children with runtime-only context).
  ```
- **Repro**: `03-analyze-cache-modes/05-trace-from-trace/expected-stdout.txt:29-30`.
- **Impact**: The note's intent is "I couldn't attribute 2 events
  because they were batch sub-workflow per-item children." That's
  one short sentence, not 3. An agent has to parse "predicted-key
  matching", "observable-field attributions", "TTL expiry, chunk
  skipped" — all internal jargon.
- **Suggestion**: shorten to:
  ```
  · 2 trace events from batch sub-workflow per-item children weren't attributed (their nodes aren't in the analyzed IR).
  ```
  Move the long explanation to `pflow guide caching` and link with
  `see also`.

### C-8 — Per-call report header math is confusing when 0 visible

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: When all rows are filtered (e.g., trace mode where every
  node hit ≥80% cache ratio), the report renders:
  ```
  Showing 0 of 2 LLM nodes; all-clean rows hidden (--all-rows shows everything).


    Hidden: 2 nodes at ≥80% projected cache ratio with no warnings (rerun with --all-rows).
  ```
  Two header lines saying the same thing, plus a blank table.
- **Repro**: `03-analyze-cache-modes/05-trace-from-trace/expected-stdout.txt:21-24`.
- **Impact**: Visual noise + wasted vertical space. Agents reading
  for "is anything wrong" see a section that looks like it had
  content but doesn't.
- **Suggestion**: when the visible-row count is 0, collapse to one
  line:
  ```
  ## Per-call cache report
    All 2 nodes clean (≥80% projected cache, no warnings). Run --all-rows to see them.
  ```

### C-9 — `evidence_kind: "predicted"` opaque to JSON consumers

- **Severity**: `UX` (JSON-side)
- **Triage**: `wart`.
- **What**: `cache.below-min-tokens` warning context carries
  `evidence_kind: "predicted"`. Other warnings don't carry this
  field consistently.
- **Repro**: `04-warning-catalog/09-cache.below-min-tokens/expected-stdout.txt:143`.
- **Impact**: An agent dispatching on `evidence_kind` has no
  documented enumeration. Is `"predicted"` vs `"observed"` the only
  values? What about `"trace"`?
- **Suggestion**: either document the closed set in the JSON
  contract docstring (`render_json.py` version-history) and add it
  to every cache warning context for consistency, or remove from the
  one place it appears. Inconsistent presence is the worst case.

---

## D. Tier-3 spot findings — JSON shape (lower priority per user directive)

### D-1 — `projection_exclusions[*].reason` and `unavailable_reason` use different vocabularies

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: `projection_exclusions[].reason` uses values like
  `"missing_output_tokens"`, `"unresolved_model"`, `"unpriced_model"`.
  `actual_vs_no_cache_delta.unavailable_reason` uses
  `"trace_coverage_partial"` (or null). These are sibling fields in
  the same `summary` block but use different vocabularies for
  similar concepts.
- **Repro**: `12-real-world-lyrics-generator/02-analyze-cache-json/expected-stdout.txt:42,68`,
  `05-advisory-cases/05-cost-projection-excludes-heterogeneous-cohort/expected-stdout.txt:76,42`.
- **Impact**: A JSON consumer building an "if cost is unavailable,
  why" dispatcher has to learn two enumeration sets and which field
  applies when.
- **Suggestion**: unify the vocabulary. `unresolved_model` and
  `missing_output_tokens` could subsume the partial-trace case, or
  vice versa. Document the closed enumeration in
  `render_json.py`'s version-history.

### D-2 — Top-level summary nullity carpet bombs JSON

- **Severity**: `UX` (JSON consumer load)
- **Triage**: `wart`.
- **What**: Every greenfield JSON case has 30+ fields nulled in
  `summary` before any actionable content appears.
- **Repro**: count nulls in
  `04-warning-catalog/04-cache.shared-context-undeclared/expected-stdout.txt:14-91` —
  most fields render `null` / `"unavailable"` / `false` / `[]`.
- **Impact**: Agents parsing the JSON pull large output before
  finding `recommended_actions` (line 93+). LLM-token-counted
  consumers (MCP, agent reasoning) pay tokens for null fields with
  no information.
- **Suggestion**: keep all fields present (per "honest unmeasurable"
  contract — null IS information), but consider rotating
  `recommended_actions` and `blocking_errors` to the top of the
  envelope so they're encountered first when streaming. Or add a
  `summary.headline_status: "errors_present"|"opportunities_present"|"clean"`
  one-shot field at the very top so consumers can short-circuit.

### D-3 — `see_also: ["caching"]` only surfaced in JSON, not text warnings

- **Severity**: `UX`
- **Triage**: `wart`.
- **What**: JSON warnings have `see_also: ["caching"]`. Text
  rendering of warnings (in `## Recommended actions`) doesn't surface
  the see-also; only the validator-error footer line does. An agent
  parsing text output never sees the see-also for advisory-class
  warnings.
- **Repro**:
  - JSON: `04-warning-catalog/04-cache.shared-context-undeclared/expected-stdout.txt:265-267`:
    `"see_also": ["caching"]`
  - Text equivalent for the same case: `03-analyze-cache-modes/01-greenfield-text/expected-stdout.txt`
    has no `See also` line under recommended actions.
- **Impact**: Text-mode agents miss the consistent navigation hint
  that JSON-mode agents get.
- **Suggestion**: render `→ See also: pflow guide caching` once at
  the bottom of `## Recommended actions` (not per-row, just once)
  when any rendered warning has `see_also: ["caching"]`.

---

## L. Real-trace findings — lyrics-generator end-to-end recording

> Recorded 2026-05-08 via `pflow run` on the full lyrics-generator
> workflow with `gemini/gemini-2.5-flash` as default model. 9:40 wall
> clock, $2.31, 4 songs generated, 253 LLM calls, 2M tokens. Trace
> at `_shared/fixtures/live-gemini-lyrics-generator.trace.json` (12MB
> trimmed). Captured baseline at
> `10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt`.
>
> The captured baseline runs in clean env (HOME=$BASELINE_HOME, no
> default_model set) so some findings visible only in real-env
> invocation are noted explicitly.

### L-1 — Trace mode discards observed_models when `default_model` not configured (CRITICAL)

- **Severity**: `bug` (correctness — drops trace evidence)
- **Triage**: `bug`. Locked in
  `10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt:3`.
- **What**: In clean env, the captured baseline shows:
  ```
  Workflow: 25 LLM nodes ... (no model resolved — set settings.default_model)
  ...
  Observed models: gemini/gemini-2.5-flash, gemini/gemini-2.5-flash-lite, gemini/gemini-3-flash-preview
  ...
  Cost without caching (executed):      unavailable
  Cost on rerun (executed, within TTL): unavailable
  ```
  The trace HAS rich model + cost evidence (Observed models is rendered
  one line below). But the analyzer still says "no model resolved" and
  marks projections as `unavailable`. **Trace evidence is silently
  ignored when IR resolution fails.**
- **Repro**: see captured baseline. Live with default_model set
  produces "using anthropic/claude-haiku-4-5" header and `~$4.57
  (partial)` cost projections — but those use the IR-declared model,
  not the observed models from trace.
- **Impact**: agents running analyze-cache without `default_model`
  configured (the fresh-agent code path) get a misleading "no model
  resolved" / "cost unavailable" rendering even when they have rich
  trace data. They may conclude trace mode doesn't work, give up,
  not realize the data is sitting right there in the trace.
- **Suggestion**: when `evidence_scope` includes trace data,
  use `observed_models` as the model source for cost projection
  fallback. The "no model resolved" header is correct for static
  analysis; in trace mode it should say something like "Models from
  trace: gemini/gemini-2.5-flash + 2 others" and use those for
  projections (with the typical "trace was on different model than
  IR declares" caveat).

### L-2 — Per-call rows show IR-declared model instead of observed-from-trace model (CRITICAL, real-env only)

- **Severity**: `bug` (correctness)
- **Triage**: `bug`. Live-only — captured baseline shows blank
  model column (which is honest); live invocation shows wrong model.
- **What**: In real env (default_model = haiku-4-5), per-call rows
  show:
  ```
  curate-briefs        model=anthropic/claude-haiku-4-5  tokens=54752  ...  src=high
  ```
  But the trace shows this node ran on gemini/gemini-2.5-flash
  (the run was end-to-end on Gemini). The model column reflects the
  IR's declared default, not the trace's observed.
- **Repro**: live `pflow analyze-cache --from-trace
  _shared/fixtures/live-gemini-lyrics-generator.trace.json` (with
  default_model set to anthropic/claude-haiku-4-5).
- **Impact**: agents inspect per-call rows to understand "which
  model was used and at what cost." The rendering says
  `anthropic/claude-haiku-4-5` for nodes that actually ran on
  `gemini/gemini-2.5-flash`. **Cost analysis based on the
  rendering would be wrong by ~10× since haiku and gemini-flash
  prices differ.**
- **Suggestion**: in trace mode, model column should show the
  observed model. If the IR declares X but trace shows Y, render
  `Y` (with optional `*` annotation if mismatched from IR). The
  `generate-chorus-options model=<varies>` row already handles
  per-batch-item model variation correctly with `observed_models=...`
  — extend that pattern to all rows in trace mode.

### L-3 — "First-run delta: 1%" disconnected from `actually_paid_usd` vs `cost_without_caching` (49% real savings)

- **Severity**: `bug` (correctness — misleading deltas)
- **Triage**: `bug`. Live-only — captured baseline doesn't show
  the deltas (cost is "unavailable"), so this isn't locked in
  fixtures.
- **What**: In real env, the rendered Summary shows:
  ```
  Actually paid (executed trace):       ~$2.31 (trace)
  Cost without caching (executed):      ~$4.57 (partial)
  First-run delta (executed):   saves ~$0.06/run on first run, 1% of baseline
  Rerun delta (executed):       saves ~$0.30/run on rerun, 6% of baseline
  ```
  The "1% first-run delta" is computed from a projection model
  (no-cache hypothetical vs first-run-with-cache hypothetical).
  But the actual data shows **49% savings** ($4.57 - $2.31 = $2.26).
  An agent reading "saves 1%" concludes their caching barely helps
  — but the trace says caching saved them $2.26.
- **Repro**: live invocation (cannot be reproduced in clean env
  baseline because default_model isn't set — finding only surfaces
  with model resolution).
- **Impact**: the most important number (actual savings on this
  run vs no-cache) is computable from the trace but not surfaced
  prominently. The "1%" number IS surfaced and is misleading.
- **Suggestion**: add a fourth delta line: `Actual savings (trace
  vs no-cache): saves ~$2.26/run, 49% of baseline`. Make this the
  primary number for trace mode, with first-run/rerun deltas as
  hypothetical projections labeled clearly.

### L-4 — 15 near-identical "Discrepancy detection: predicted-key matching skipped" notes

- **Severity**: `UX`
- **Triage**: `wart`. B-4-pattern repeating at scale (15× instead
  of 3×).
- **What**: For each of 15 sub-workflow files, the analyzer emits
  a separate Notes line:
  ```
  · Discrepancy detection: predicted-key matching skipped for
    <REPO_ROOT>/.../song-creator/reviews/review-rhyme.pflow.md —
    workflow declares inputs that weren't supplied or resolvable.
    Observable-field attributions still apply.
  ```
  Most variations differ only by file path. Total ~4KB of notes
  prose for what could be a single summary.
- **Repro**: live + clean-env captured baseline both show 15 of these.
  (Captured baseline at lines 86-87 shows the count summary; the
  per-workflow lines are deduplicated by the analyzer in clean env
  but appear in real-env output. Cross-check: the live invocation
  earlier in this session showed all 15 lines.)
- **Impact**: agent reading the Notes section is overwhelmed by
  repetitive lines that all say the same thing. Skim cost is high.
- **Suggestion**: collapse to one summary:
  ```
  · Discrepancy detection: predicted-key matching skipped for 15
    sub-workflows (inputs not supplied or unresolvable). Observable-
    field attributions still apply. Pass concrete `<input>=<value>`
    parameters to enable per-workflow predicted-key matching.
  ```
  And optionally an indented list of the 15 paths if the agent
  wants detail.

### L-5 — 117 trace events (46%) have no predicted cache_key — coverage limitation worth surfacing better

- **Severity**: `UX`
- **Triage**: `wart`. Limitation, not a bug.
- **What**: Notes line:
  ```
  Discrepancy detection: skipped attribution for 117 trace event(s)
  with no predicted cache_key and no observable signal. ... typically
  batch sub-workflow per-item children with runtime-only context.
  ```
  117 of 253 events (46%) skip discrepancy detection. The reason
  (batch sub-workflow per-item) is documented, but the impact isn't
  framed for the agent: they're getting per-call rows for ~136 of
  253 events; 117 events are basically invisible to the analyzer.
- **Repro**: captured baseline line 87.
- **Impact**: agents may miss that 46% of events have no cache
  attribution. They may infer from `Showing 18 executed LLM nodes`
  that this is the full picture; in reality, ~117 batch sub-workflow
  per-item executions exist but aren't separately attributed.
- **Suggestion**: surface the coverage explicitly in the Summary
  block:
  ```
  Trace coverage: 136 of 253 events attributed (54%); 117
  batch sub-workflow per-item children rolled up.
  ```
  Or in the per-call-report header.

### L-6 — Per-call rows lack output token column

- **Severity**: `UX`
- **Triage**: `wart`. Information loss.
- **What**: per-call rows show input tokens (`tokens=78866`) and
  cacheable estimate (`cacheable=63009 ratio= 80%`) but no output
  token count. Lyrics-generator generated 817K output tokens (41%
  of total 2M tokens — output is a major cost driver).
- **Repro**: every per-call row in captured baseline lines 28-60.
- **Impact**: cost analysis based on per-call rows misses 41% of the
  cost. Agents trying to find "which node generates the most output"
  to optimize generation length have no signal.
- **Suggestion**: add `output_tokens=` column to the per-call
  report. The data is in `llm_summary.total_output_tokens` and
  per-event `llm_call.output_tokens` — analyzer just needs to
  surface it.

### L-7 — Large numeric values lack thousands separator

- **Severity**: `UX`
- **Triage**: `wart`. Cosmetic.
- **What**: `tokens=266728`, `tokens=158704`, `tokens=114063` —
  hard to read at a glance vs `tokens=266,728`.
- **Repro**: captured baseline lines 52-60.
- **Impact**: agents quoting numbers back to humans, or comparing
  values mentally, slow down. Token counts of 6-figure magnitude
  are common in real workflows.
- **Suggestion**: format with `:,` (comma thousands separator) in
  the renderer. Same for cost cents in JSON (B-2 already covers
  cost precision).

### L-8 — Trace size: 53MB raw → 12MB trimmed (committable but heavy)

- **Severity**: `UX` (regression-oracle workflow)
- **Triage**: `wart`. Discovered during fixture preparation.
- **What**: A real lyrics-generator trace is 53MB. Most of that is
  duplicated text content: each LLM event stores the full prompt
  in `llm_prompt`, `node_params.prompt`, `template_resolutions.prompt.resolved`,
  AND `node_output.prompt` — same 37KB string appearing 4 times per
  event × hundreds of events.
- **Repro**: see fixture trim script in commit history; `wc -c`
  on raw trace = 53M; trimmed = 12M.
- **Impact**: traces of real workflows are too big to commit as
  baseline fixtures. `_shared/fixtures/sample-2.1.0-trace.json` is
  6KB; the lyrics-generator trace is 2000× larger. Agents recording
  their own traces for `--from-trace` analysis will face the same
  size on disk.
- **Suggestion**: deduplicate the prompt content in trace JSON.
  Store once at `event.llm_prompt`; reference from `node_params`
  and `node_output` if needed. Or strip duplicates at trace-write
  time. Could reduce real traces by 60-80%.

### L-10 — Trace mode suppresses static findings (regression of evidence) — CRITICAL ARCHITECTURAL BUG

- **Severity**: `bug` (architectural — fundamental contract violation)
- **Triage**: `bug`. Adding evidence should refine analysis, not erase
  it. This is the single most important finding from the lyrics-
  generator recording.
- **What**: The same workflow analyzed in static mode vs trace mode
  produces dramatically different findings counts:

  | Section | Static (`--no-trace-autoload`) | Trace (`--from-trace`) |
  |---|---|---|
  | Summary opportunities | `19 opportunities (0 warnings, 19 info)` | `0 opportunities (0 warnings, 0 info)` |
  | Recommended actions | 2 entries (sub-workflow cache undeclared + opaque-prompt) | section omitted |
  | Sub-workflow boundaries | 17 cross-workflow rename findings | section omitted |
  | Per-call cache report | 1 row (greenfield estimator-partial) | 18 rows (real trace data) |

  The cross-workflow rename findings are **derived from static IR
  analysis** (parent declares `concept_brief`, child renames to
  `creative_brief` — that's a fact in the workflow files,
  independent of any trace data). They are NOT trace-dependent. But
  trace mode hides them because of the gate
  `Workflow-design recommendations suppressed because the trace is
  partial`.

  Effect: agents get **less actionable output** when they have
  **more data**. The opposite of the analyzer's intended
  contract.
- **Repro**:
  ```bash
  # static — shows 19 opportunities
  pflow analyze-cache <lyrics> --no-trace-autoload sources='["..."]'
  # trace — shows 0 opportunities
  pflow analyze-cache <lyrics> --from-trace <trace> sources='["..."]'
  ```
  Captured baseline at
  `10-live-recordings/05-gemini-lyrics-generator/expected-stdout.txt:15`
  shows `0 opportunities (0 warnings, 0 info)` and the suppression
  notes at line 88. Compare to `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt:10`
  which shows `19 opportunities`.
- **Impact**: workflows that have run their first trace are exactly
  the ones agents are about to optimize. Hiding the static findings
  on those workflows defeats the purpose. Agents who ran the
  workflow once (paying $2.31 of LLM cost in our case) get an
  empty Recommended actions section and conclude the workflow has
  no cache opportunities — when it has 19.
- **Suggestion**: separate "trace-derived" from "IR-derived"
  findings in the suppression logic. Cross-workflow walker output,
  catalog warnings (shared-context-undeclared, etc.), and other
  static findings should always render. Trace-derived findings
  (cache.discrepancy, cost projections) are the only ones whose
  reliability depends on trace coverage. The current "partial trace
  → suppress all design recs" gate is too coarse.

### L-11 — "Partial trace" framing conflates expected conditional dispatch with incomplete coverage

- **Severity**: `bug` (correctness — feeds L-10's incorrect
  suppression cascade)
- **Triage**: `bug`. Captured in the lyrics-generator baseline and
  cascades into L-10.
- **What**: Header line in trace mode:
  ```
  Evidence: partial trace (18 of 25 LLM nodes executed)
  ```
  This implies "7 nodes failed to execute." They didn't. They're
  **conditional dispatches** — the workflow has a `classify` node
  that routes input to one of four fetch paths (`fetch-youtube`,
  `fetch-webpage`, `read-file`, `pass-text`) plus an on-error
  fallback (`fetch-youtube-mcp`). With raw-text input, only
  `pass-text` runs. The other 4 fetch paths are valid IR nodes
  that **shouldn't run for this input**. Adding 2 similar
  conditional dispatches in other sub-workflows = 7 IR nodes
  unreached.

  The analyzer can't distinguish:
  - **Trace stopped early** (real partial coverage)
  - **Conditional dispatch unreached** (correct behavior)
  - **Workflow completed all reachable nodes** (the case here)

  All three classify as "partial" → L-10's suppression fires.
- **Repro**: captured baseline header line 4. Workflow's
  `final_status: completed` (in trace JSON) confirms the run was
  successful end-to-end. Trace shows 253 LLM calls across 18 IR
  nodes — every reachable node executed.
- **Impact**: a successfully-completed workflow with conditional
  dispatch is mislabeled as "partial." This triggers L-10's
  suppression and yields zero opportunities for a workflow with
  19 real ones.
- **Suggestion**: split the single "partial" classification into
  three independent dimensions:
  - **Trace coverage**: `complete` (all reachable nodes executed) /
    `incomplete` (trace ended early)
  - **Static coverage**: `<reached>/<reachable>/<declared>` ratios
    where reachable filters out conditional branches not taken for
    the input
  - **Final status**: `completed` / `failed`

  Then the L-10 suppression should only fire when `final_status ==
  failed` OR `trace coverage == incomplete` — not when conditional
  branches are simply unreached.

### L-12 — Per-call rows can't show observed model even though `event.llm_call.model` is in trace (extends L-1)

- **Severity**: `bug`. Already covered by L-1; this is a sharper
  framing of the same root cause.
- **What**: every event in the trace has `llm_call.model` populated
  with the actual model used (verified by Python inspection:
  `gemini/gemini-2.5-flash` on most events,
  `gemini/gemini-2.5-flash-lite` and `gemini/gemini-3-flash-preview`
  on chorus-chooser sub-workflow events). The analyzer reads these
  to build the `Observed models:` header. It does NOT read them
  for per-call rows. The single working example is
  `generate-chorus-options model=<varies> observed_models=...` on
  line 52 — that code path exists; it just isn't extended to all
  rows in trace mode.
- **Repro**: same as L-1 + L-2.
- **Impact**: in any env (clean or with default_model set), the
  per-call model column is wrong in trace mode. Clean env shows
  blank (honest but unhelpful); real env shows IR-declared model
  (worse — misleading).
- **Suggestion**: in trace mode, per-call rows should show the
  observed model from `event.llm_call.model` (or aggregate per
  node if multiple calls hit the same node with same model — `(×N)`
  pattern; `<varies>` if multiple models for one node, with
  `observed_models=` enumeration). Treat the IR-declared model as
  fallback only.

## L-meta. Trace recording — practical lessons

- **Cost**: $2.31 (Gemini-flash) for end-to-end on lyrics-generator.
  Higher than my $0.30 estimate; would re-run only when needed.
- **Wall clock**: 9:40. Faster than my 5-15 min estimate.
- **Reliability**: zero retries needed; all 253 calls succeeded
  end-to-end. No rate-limit errors on Gemini.
- **Sub-workflow nesting**: trace correctly captured 3 levels deep
  (parent → song-creator → reviews) with batch_items at each level.
- **Models actually used**: 3 distinct (gemini-2.5-flash,
  gemini-2.5-flash-lite, gemini-3-flash-preview). The
  per-batch-item `${item.model}` field on `generate-chorus-options`
  correctly resolved per-item.

The recording was straightforward but the analyzer rendering
surfaced E-1 through E-7 as a single batch — running the real
trace was the most cost-effective way to find these bugs.

## E. Positive observations — patterns to preserve through Task 160

These aren't findings to fix; they're patterns the audit confirms
work well, worth locking via the baseline so Task 160 doesn't
regress them.

- **Parser errors all carry a `→` suggestion with proper template**
  (e.g. case `01-parser-errors/01-empty-cache-block/expected-stderr.txt`
  shows the full template the user should write). This is exactly
  the "WHAT/WHY/WHERE/HOW" pattern from the Task 159 spec.
- **`cache.heterogeneous-models-fragment-cache` rendering enumerates
  per-model groups inline** (`04-warning-catalog/15`) — the agent
  immediately sees which nodes use which models, in the message
  itself, not buried in `context`.
- **`cache.first-call-write-penalty` provides dual suggestion**
  (remove OR amortize) — agent can choose based on whether they're
  willing to add more calls. Good "two doors" pattern.
- **Validator unification (case `02-validator-errors/08-analyze-cache-surfaces-undeclared-name`)
  surfaces previously-dropped errors in analyze-cache mode** — the
  external-review fix paid off. Mutation contract here is critical.
- **Trace mode (`03-analyze-cache-modes/05-trace-from-trace`) shows
  `Confidence: high_from_trace (2 of 2 nodes)` in the header** —
  agents immediately know the data-quality tier of what they're
  reading.
- **`pflow guide caching` see-also footer on most validator errors**
  — when present, agents get clean signposting. The pattern is right;
  C-3 is just about consistency.
- **Suggested run command (UX 8 from Tier A bundle) populates
  correctly on the unavailable-cost branch with no model resolved
  and gates correctly on inline IR** — the strict-improvement audit
  noted in the progress log holds up here.

---

## F. Triage outcome (verified against source 2026-05-08)

> Source-verified by triage agent. Each merge-block finding is grounded
> at a specific file:line in `src/pflow/core/cache_analysis/`. Findings
> classified noise (pure duplicates, self-downgraded) have been removed
> from this file (L-9, A-4).

### MERGE-BLOCK — fix before Task 160 starts (8 findings)

**Coordinated batch — single fix, single re-capture of `10-live-recordings/05-gemini-lyrics-generator`**:

- **L-11** — `_trace_coverage_for_rows` (`analyze.py:4019-4039`) returns
  `"partial"` whenever any static row has `did_not_execute_in_trace`.
  No distinction between "trace truncated" / "conditional branch not
  taken" / "node never reachable for this input." Fix: split coverage
  into orthogonal axes (final_status × trace_truncation × reachability)
  so a successfully-completed workflow with conditional dispatch is not
  classified as `partial`.
- **L-10** — `_warnings_for_partial_trace` (`analyze.py:4048-4050`)
  filters to `Severity.ERROR` only, dropping every IR-derived info
  finding. Fix: filter only trace-derived findings (cache.discrepancy
  and cost projections); IR-derived findings (cross-workflow renames,
  shared-context-undeclared, etc.) must always pass through. The
  current behavior is "more evidence → less knowledge" — the opposite
  of the analyzer's contract.
- **L-12 / L-2 / L-1** — `render_text.py:1063-1066`: per-call model
  column uses `row.model` (IR-declared) and only shows `observed_models`
  when `model_is_heterogeneous OR len(observed_models) > 1`. Single-
  model rows render the IR's model even when the trace shows a different
  one. Fix: in trace mode, prefer `observed_models[0]` for the per-call
  column; fall back to `row.model` only when no observed. Same fix
  resolves L-1 (cost projection should use observed_models when IR
  resolution failed).
- **L-3** — Add a primary "Actual savings (trace vs no-cache)" delta
  line in trace mode. The data is in `actually_paid_usd` and
  `cost_without_caching` — currently the rendered delta is the
  hypothetical first-run/rerun pair, which can show "1%" while the
  actual savings are 49%.

**Independent fixes**:

- **A-1** — `render_text.py:640-642` dedup check `action.message !=
  action.headline` doesn't account for the headline-fallback at line
  658 (`title = action.headline or action.message or action.warning_id`).
  When `headline` is None, the title falls back to `message`, then the
  body re-renders the message because `None != message`. Locked in 3
  baseline cases (validator-08, lyrics-generator-static, lyrics-
  generator-trace). Fix: skip the body when message equals the rendered
  title, not just when message equals headline.
- **A-6** — Apply the F-04 honest-unmeasurable convention to the
  `tokens=` column. When `cacheable_data_source == "unavailable"` AND
  the row is `opaque-prompt`, render `tokens= ?`. Same shape as the
  existing `cacheable= ?` and `ratio= ?%` rendering.
- **B-17** — Replace the `(progress log §36)` literal in the Gemini
  telemetry note with a self-contained sentence. Internal task-doc
  references should never appear in agent-facing output.

### MERGE-BLOCK doc-correctness fix (1 item)

- **B-12 + B-13** — `pflow guide caching` content corrections, batch
  as one PR:
  - B-12: replace inline Anthropic min-tokens summary at `caching.md:204`
    with either a generated table from `MODEL_CAPABILITIES` or a complete
    enumeration. Currently omits 5+ registered models per tier (Sonnet 4,
    Sonnet 3.7, Opus 4, Opus 4.1 in 1024-tier; Opus 4.5/4.6/4.7 in
    4096-tier).
  - B-13: replace stale `~/.pflow/debug/trace.json` example at
    `caching.md:71` with the actual hash-keyed schema, or recommend the
    auto-load path first.

### DEFER to v1.x (35 findings, kept in this file)

All **B-** findings except B-17 / B-12 / B-13 — lyrics-generator UX
warts (path repetition, rendering density, vocabulary inconsistency).
Highest leverage for agent UX polish.

All **C-** findings — common-path agent UX: bracketed catalog ID
inconsistency, missing workflow path, see-also coverage gaps, magic-
string vocab. Worth normalizing alongside Task 160's renderer
restructure.

**A-2, A-3, A-5** — JSON-shape warts (float precision, semantic
inconsistency on `unavailable_reason`, redundant `unavailable_models`
field). User-deprioritized; defer with the rest of D-section.

All **D-** findings — JSON shape; user-deprioritized.

**L-4, L-5, L-6, L-7, L-8** — discrepancy-note duplication, missing
output token column, thousands-separator formatting, trace-fixture
size. None lock incorrect behavior into baselines.

### Removed as noise (not in this file anymore)

- **L-9** — pure duplicate of A-1. The mutation contract is already
  carried by A-1 across 3 baseline cases; a separate finding entry
  added no information.
- **A-4** — author downgraded in-line during live verification ("count
  is correct, the issue is rendered-structure mismatch"). Folded into
  B-section thinking; keeping as a separate "A-class bug" was
  misleading.

### Open questions for confirmation

- **A-1 design intent**: is the doubled blocking-error message
  intended (title=short summary, body=detailed message — they coincide
  here because un-IDed validator errors have no headline)? If yes,
  downgrade to wart and shorten the title for short-message cases.
- **B-9 design intent**: is surfacing non-cache validator errors under
  `## Blocking errors` in `analyze-cache` the right design? The
  validator-unification fix made this happen; question is whether a
  renamed/split section header would help agents triage.

### Recommended fix order

1. **L-10 + L-11 + L-12 + L-1 + L-2 + L-3 batch** — single coordinated
   fix touching `analyze.py` (L-11 coverage classification, L-10
   suppression filter) and `render_text.py` (L-12/L-2 per-call model,
   L-3 actual-savings delta). Single re-capture of case 05.
2. **A-1** — isolated render_text.py fix; re-capture validator-08 +
   lyrics-generator static + lyrics-generator trace.
3. **A-6** — render_text.py rendering rule for opaque-prompt tokens
   column; re-capture lyrics-generator static + song-creator cases.
4. **B-17** — single literal-string edit in cost_estimation.py or
   wherever the Gemini telemetry note is composed; re-capture case 03.
5. **B-12 + B-13** — doc PR; no baseline impact.

Estimated: 4-6 hours of focused implementation including baseline
re-captures and verification. The L-batch is the single highest-impact
piece; everything else is independent and lower-risk.

---

## G. What I didn't audit (scope cuts)

- **F-02 catalog warnings that don't trigger** (5 IDs): explicitly
  out of scope per FINDINGS.md.
- **`pflow guide` topic ordering**: case 04 shows guide content
  from the top, in batch-then-cache order. I didn't verify whether
  this ordering matters for agent UX — it might be a deliberate
  "most-relevant-first" choice the auto-detect makes.
- **JSON shape consistency across modes**: user de-prioritized;
  I noted only D-1, D-2, D-3 where the shape inconsistency could
  bite a Task 160 refactor.
- **MCP server output**: out of scope per PLAN.md §11.

---

## H. Coverage summary

- Tier 1 (lyrics-generator captures): read line-by-line, 11 findings
  (B-1 through B-11) including 3 added during live verification.
- Guide content audit: 4 findings (B-12 through B-15) from reading
  `src/pflow/guide/features/caching.md` (249 lines) and live-running
  `pflow guide caching` against `llm_capabilities.py` source.
- Live trace-mode capture (surface 10 case 03 — `live-gemini-translation`):
  5 findings (B-16 through B-20). Recording cost $0.0013, 7.7s wall
  clock. Both calls returned `cache_read_input_tokens: 6024`,
  `cache_creation_input_tokens: 0` — Gemini's `cachedContents`
  fired (likely implicit caching from prior runs). Confidence:
  `high_from_trace`, 71% rerun savings.
- Real-world trace capture (surface 10 case 05 —
  `live-gemini-lyrics-generator`): 8 retained findings (L-1 through
  L-8, L-10, L-11, L-12; L-9 removed as pure dupe of A-1).
  Recording: $2.31, 9:40 wall clock, 253 LLM calls,
  3 distinct Gemini models, 4 songs generated. Trace trimmed
  53MB → 12MB for committable size. Surfaced 3 critical bugs
  (L-1 trace discards observed_models, L-2 wrong model in per-call
  rows, L-3 misleading first-run delta) that no static analysis
  case could have found. Captured baseline locked; verify.sh
  confirms 65/65 passing.
- Tier 2 (common-path agent UX): spot-read all 4 surfaces, 9 findings
  (C-1 through C-9).
- Tier 3 (JSON shape): spot-read, 3 findings (D-1, D-2, D-3) —
  deferred per user's text-priority directive.
- Bugs surfaced across all tiers after triage cleanup (A-1, A-2, A-3,
  A-5, A-6, B-12 doc bug, B-17 dead-link bug, L-1, L-2, L-3, L-10,
  L-11, L-12). A-4 and L-9 removed as noise (see Section F).
- Findings by section after cleanup: A=5, B=20, C=9, D=3, L=11 — total
  **48 retained** (L-9 removed as pure dupe of A-1; A-4 removed as
  self-downgraded; some original counts in earlier prose were
  approximate).

Bug-class to fix before Task 160 — **8 code bugs**, source-verified
during triage (A-1, A-6, B-17, L-1, L-2, L-3, L-10, L-11, L-12 — L-12
counted with L-1/L-2 as the same root). L-10 is the most consequential:
the architectural defect where adding trace evidence reduces the
analyzer's apparent knowledge. L-11 is the proximate cause that
triggers L-10's suppression cascade for normal conditional-dispatch
workflows.

Plus **1 doc bug** (B-12, batched with B-13 stale example) that
should be fixed before merge if `pflow guide caching` is in v1 scope.

**Source verification by triage agent (2026-05-08)**:
- L-10: confirmed at `analyze.py:4048-4050` — `_warnings_for_partial_trace`
  filters to ERROR severity only.
- L-11: confirmed at `analyze.py:4019-4039` — `_trace_coverage_for_rows`
  returns "partial" if any node has `did_not_execute_in_trace`.
- L-12 / L-2: confirmed at `render_text.py:1063-1066` — single-observed-
  model rows render the IR's model.
- A-1: confirmed at `render_text.py:640-642 + 658` — title falls back
  to message when no headline, then dedup misses.
- A-3: confirmed at `analyze.py:3963-3968` — `unavailable_reason="trace_coverage_partial"`
  fires whenever `trace_coverage != "complete"`, including when it's
  "none". Real but JSON-only; deferred per text-priority directive.

**Confidence**: high on all merge-block findings (source-verified).
High on B-section / C-section findings (live verified). Medium on
remaining A-section warts (deferred to v1.x).
