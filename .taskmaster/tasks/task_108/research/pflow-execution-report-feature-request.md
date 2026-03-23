# Feature Request: Automatic Execution Report for pflow Workflows

## Summary

pflow should automatically generate a structured, human/AI-readable execution report for every workflow run. The report is a directory of markdown files mirroring the workflow's node structure, with one file per node containing metadata, the rendered prompt (for LLM nodes), and the response. Every pflow workflow gets pipeline visibility for free — no custom code needed.

This is the developer/agent-facing complement to application-level output. Application output is the deliverable ("here are your 4 songs"). The execution report is the development tool ("here's what happened at every step to produce those songs").

## Origin & Context

This request comes from 5 sessions of building a multi-stage AI lyrics generation pipeline in pflow. The pipeline has 11 orchestrator nodes, sub-workflows called in batch (4 songs in parallel, each with 12+ nodes), sub-sub-workflows (chorus-chooser with 8 nodes per song), ~233 LLM calls per run, runs in ~280 seconds, costs ~$1.58, and produces 55 output files per run.

The development team (an AI agent and a human) built a custom 80-line Python code node (`build-file-list`) to save every pipeline stage as a numbered, readable markdown file organized in directories. This custom output system became the ONLY way the AI agent analyzes and debugs pipeline quality. The 2.7MB trace JSON file was never opened once across 5 sessions — it's too dense and not designed for quality analysis.

The realization: the manually-built output file system IS the debugging/analysis tool. The team didn't recognize this until explicitly reflecting on it — they took it for granted because they built it by hand. If pflow provided this automatically, every workflow would get pipeline visibility for free.

## What the AI Agent Actually Does

These are the real workflows an agent performs against pipeline output. The report must support all of them efficiently.

### 1. Quick scan — "did it work?"

Reads a single summary to see status, timing, cost, and any errors. Takes 30 seconds. Currently uses the console output (lost after the terminal scrolls) or manually reads metadata.json.

### 2. Targeted investigation — "why did Song C fail?"

Traces backward through the pipeline by reading individual stage files. For example: final lyrics → chorus selection → creative direction → concept. Goes straight to the specific song's files without reading the other 3 songs. Currently navigates 12 files per song in the custom output directory.

### 3. Comparison between runs — "did my prompt change help?"

Diffs specific node output files between two runs. For example: changed the concept generator prompt, wants to see if concepts improved. Diffs JUST the concepts file between run A and run B. Doesn't care that everything downstream also changed (of course it did — the inputs changed).

Key insight from discussion: git diff on a full run is useless because almost all LLM outputs change between runs (they're stochastic). The value is in TARGETED diffs of specific nodes. This requires separate files per node with consistent filenames.

### 4. Debugging — "what did the LLM see?"

Needs the rendered prompt (after template variable substitution) alongside the response. This is the ONE piece of data that doesn't exist anywhere today. The agent can reconstruct it from template files + upstream outputs for template-based prompts, but CANNOT reconstruct it for dynamically-built prompts (code nodes that construct prompt strings with f-strings).

### 5. Cost analysis — "where's the money going?"

Needs per-node cost breakdowns. Currently this requires parsing the trace JSON. For our pipeline, this analysis revealed that chorus scoring is ~38% of total cost — actionable information that was invisible without manual JSON parsing.

## What Exists Today in pflow

### Trace files

Location: `~/.pflow/debug/workflow-trace-{name}-{timestamp}.json`

Contains:
- Top-level metadata: `format_version`, `execution_id`, `workflow_name`, `start`/`end` time, `duration`, `status`, `nodes_executed`, `nodes_failed`
- `nodes` array: each with `node_id`, `node_type`, `duration_ms`, `success`, `shared_before`, `shared_after`, `mutations`
- `llm_summary`: `total_calls`, `total_tokens`, `models_used`
- `__llm_calls__` array: each with `model`, `input_tokens`, `output_tokens`, `total_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `cost_usd`, `node_id`, `batch_item_index`
- LLM responses in `shared_after` under node keys (e.g., `shared_after["synthesize-sources"]["response"]`)

What's NOT in trace files:
- **The rendered prompt** — the actual text sent to each LLM after template substitution
- **Sub-workflow internal nodes** — sub-workflows show as single WorkflowExecutor nodes; internal nodes are not individually visible
- **Readable format** — it's a JSON blob designed for pflow internals

### What the team built manually

A `build-file-list` code node (~80 lines Python) + `save-outputs` batch write-file that:
- Formats batch results into readable markdown (analyst outputs into sections with headers)
- Organizes per-song outputs into labeled subdirectories (song-A/, song-B/)
- Numbers files in pipeline order (01-creative-direction.md through 12-suno-prompt.md)
- Generates metadata.json
- Saves 55 files total

This is a hand-built execution report. Every pflow workflow wanting this visibility must build it from scratch.

## Proposed Report Structure

### Directory layout

The report mirrors the workflow's node structure. Each node gets its own file. Sub-workflows get folders. Batch items get numbered folders or named files.

```
report/
  summary.md                          # Pipeline overview
  01-fetch-sources/                   # Batch sub-workflow
    summary.md                        # Batch overview table
    item-0.md                         # Individual fetch result
  02-analyze-sources/                 # Batch sub-workflow
    summary.md
    item-0/                           # Per-source analysis
      emotional.md                    # Named by batch item field
      sensory.md
      themes.md
      narrative.md
      musicality.md
      voice-tone.md
  03-synthesize-sources.md            # Single LLM node
  04-generate-concepts.md             # Single LLM node
  05-enforce-diversity.md             # Single LLM node
  06-create-songs/                    # Batch sub-workflow
    summary.md
    item-0/                           # Song A's full pipeline
      01-creative-direction.md
      02-song-architecture.md
      03-easter-eggs.md
      04-choose-chorus/               # Nested sub-workflow
        summary.md
        01-generate-options/
          summary.md
          item-0.md through item-7.md # Each generation group
        02-score-choruses/
          summary.md                  # Score table for all items
        03-rank-choruses.md
        04-select-chorus.md
        05-extract-winners.md
      05-write-lyrics.md
      06-specialist-reviews/
        summary.md
        ai-tells.md
        cliche.md
        narrative.md
        imagery.md
        genre.md
      07-consolidate-reviews.md
      08-rewrite.md
      09-extract-lyrics.md
      10-verify-revision.md
      11-generate-suno-prompt.md
    item-1/                           # Song B (same structure)
    item-2/                           # Song C
    item-3/                           # Song D
  07-prepare-evaluation.md
  08-evaluate-songs.md
```

### File format: LLM node

Three sections — metadata, what it saw, what it produced:

```markdown
# synthesize-sources

- Type: llm
- Model: gemini-3-flash-preview
- Tokens: 9,610 in / 2,130 out
- Cost: $0.011
- Time: 13.8s
- Status: success

## Prompt

[The RENDERED prompt — all ${template_variables} filled in with actual
values from upstream nodes. This is exactly what the LLM received.
Full content, never truncated.]

## Response

[The LLM's complete response. Untruncated.]
```

### File format: Code node

```markdown
# compute-output-dir

- Type: code (python)
- Time: 0.2ms
- Status: success

## Inputs

| Variable | Value |
|----------|-------|
| output_base | ./output |

## Result

./output/0022-20260322-2358
```

### File format: Shell node

```markdown
# fetch-youtube

- Type: shell
- Time: 3.7s
- Exit code: 0
- Status: success

## Command (rendered)

[The actual shell command after variable substitution]

## stdout

[Output]

## stderr

[If any]
```

### File format: Batch summary

```markdown
# analyze-sources (batch)

- Items: 6
- Parallel: true
- Succeeded: 6/6
- Total cost: $0.04
- Total time: 16.0s

## Items

| # | Item Key | Model | Tokens In | Tokens Out | Cost | Time | Status |
|---|----------|-------|-----------|------------|------|------|--------|
| 0 | emotional | gemini-3-flash | 2,677 | 1,930 | $0.007 | 2.1s | ok |
| 1 | sensory | gemini-3-flash | 2,412 | 1,654 | $0.006 | 1.8s | ok |
| ... |

See individual item files for full prompts and responses.
```

### File format: Sub-workflow batch summary

```markdown
# create-songs (batch workflow)

- Sub-workflow: ./song-creator/song-creator.pflow.md
- Items: 4
- Parallel: true
- Succeeded: 4/4
- Total cost: $1.28
- Total time: 202.8s

## Items

| # | Concept Title | Nodes | Cost | Time | Status |
|---|---------------|-------|------|------|--------|
| 0 | The Canopy Umbrella | 13/13 | $0.32 | 198s | ok |
| 1 | The Underworld Kickback | 13/13 | $0.31 | 195s | ok |
| 2 | Six Thousand Tons of Breath | 13/13 | $0.33 | 201s | ok |
| 3 | Pebbles in a Jar | 13/13 | $0.32 | 197s | ok |

See item folders for full pipeline details.
```

### File format: Top-level summary

```markdown
# Execution Report

- Workflow: lyrics-generator
- Status: success
- Time: 281s
- Cost: $1.59
- LLM calls: 233
- Models: gemini-3-flash-preview, gemini-2.5-flash-lite
- Generated: 2026-03-22 23:00:18

## Pipeline

| # | Node | Type | Time | Cost | Status |
|---|------|------|------|------|--------|
| 1 | fetch-sources | workflow (1 item) | 3.8s | — | ok |
| 2 | analyze-sources | workflow (6 items) | 16.0s | $0.04 | ok |
| 3 | synthesize-sources | llm | 13.8s | $0.01 | ok |
| 4 | generate-concepts | llm | 9.7s | $0.01 | ok |
| 5 | enforce-diversity | llm | 10.9s | $0.01 | ok |
| 6 | create-songs | workflow (4 items) | 202.8s | $1.28 | ok |
| 7 | prepare-evaluation | code | 0.0s | — | ok |
| 8 | evaluate-songs | llm | 19.7s | $0.02 | ok |

## Errors / Warnings

[Any errors, warnings, or degraded nodes. Empty if clean run.]
```

## Design Principles & Rationale

### One file per node, not one big file

- **Targeted reading** — go straight to the node you care about without searching
- **Git diffing** — diff one node between runs, not the entire report. With ~233 LLM calls and stochastic outputs, a full-report diff is useless noise
- **AI agent efficiency** — read one small file instead of scanning a massive document

### Rendered prompts are the centerpiece

This is the single most valuable feature. The rendered prompt is the ONE piece of data that doesn't exist anywhere today.

- When an LLM produces bad output, the first question is "what did it see?"
- For template-based prompts (`- prompt: ./file.prompt.md`), the rendered version is the file content after all `${template_variables}` are substituted
- For batch items with per-item prompts (`prompt: ${item.prompt}`), each item has its own rendered prompt
- For dynamically-built prompts (code nodes that output prompt strings consumed by downstream LLM nodes), the rendered prompt is whatever string arrives at the LLM node — reconstruction from other artifacts is impossible
- Having the prompt RIGHT NEXT TO the response shows cause and effect together
- When diffing between runs, the prompt diff shows what you changed, the response diff shows the effect — in one diff

### Hierarchical folders mirror workflow structure

- Sub-workflows become sub-folders, batch items become numbered folders
- The file path IS the navigation: `create-songs/item-2/creative-direction.md` = Song C's creative direction
- Flat structures fail for nested workflows — 233 files in one directory is unusable

### Numbered prefixes for execution order

- Files sort in execution order — `01-creative-direction.md` before `02-song-architecture.md`
- Reading files in order tells the pipeline's story
- Consistent across runs for reliable diffing

### Metadata inline

- Model, cost, time appear at the top of each file — no context switching to a separate metadata file
- The metadata header is 5-6 lines; the prompt and response are the bulk of each file
- When reading an LLM node's output, you immediately know which model produced it and at what cost

### Summaries at every level

- Every folder (batch, sub-workflow) has a `summary.md` with a table overview
- The agent reads summaries to navigate, opens specific files to investigate
- Natural zoom: summary → batch table → individual item

### Untruncated content

- Rendered prompts and responses are never truncated in individual files
- They may be long (a rendered write-lyrics prompt with full context is thousands of lines)
- Truncation belongs in summary tables, not in detail files
- The full content is the point — that's what the agent needs for debugging

## Batch Item Labeling

Batch items should use meaningful labels when available, not just numeric indices.

The specialist review batch has items with a `focus` field: `ai-tells`, `cliche`, `narrative`, `imagery`, `genre`. The report should use these as filenames (`ai-tells.md`, `cliche.md`) rather than `item-0.md`, `item-1.md`.

Proposal: use a heuristic to find the best label field from the batch item data, or allow the workflow author to specify it:

```yaml
batch:
  items: ${analysts}
  parallel: true
  label_field: focus    # Use item.focus as filename in report
```

If no label is determinable, fall back to `item-0`, `item-1`, etc.

## Real-World Examples

### Example 1: Debugging a bad song

Agent notices Song C is inaccessible. Opens `create-songs/item-2/01-creative-direction.md`. Reads the Prompt section — sees the concept "factory work of leaves" with narrator "collective consciousness of stomata." The problem is immediately clear: the concept has no human analog.

Without the report: read `output/song-C/01-creative-direction.md` (same response but no prompt, no metadata), then `04-concepts.md`, then `05-diversity-assignments.md`. Same conclusion, 3× the file navigation, no visibility into what the creative-direction LLM actually received.

### Example 2: Prompt engineering iteration

Developer changes `generate-concepts.prompt.md` to emphasize human experiences over intellectual interest. Runs the pipeline twice.

```bash
diff report-before/04-generate-concepts.md report-after/04-generate-concepts.md
```

The diff shows:
- **Prompt section**: the new instruction about human experiences appears
- **Response section**: concepts shifted from "factory work of leaves" to "the loneliness of outgrowing what nourished you"
- Cause and effect in one diff

Without the report: diff the prompt template (sees the change) + diff `output/04-concepts.md` between runs (sees the output change). Two separate diffs the agent must mentally connect.

### Example 3: Cost optimization

Agent opens `summary.md` → sees `create-songs: $1.28 / $1.59 total`. Opens `create-songs/item-0/04-choose-chorus/02-score-choruses/summary.md` → sees 34 scoring calls at $0.005 each = $0.17 per song, $0.68 total = 43% of pipeline cost.

Actionable: scoring could use a cheaper model. Without the report, this requires parsing the 2.7MB trace JSON.

### Example 4: Verifying template substitution

After a workflow change, agent suspects a template variable isn't resolving. Opens the node's report file, reads the Prompt section, immediately sees whether `${concept.title}` was replaced with the actual title or left as a template string.

Without the report: read the template file, find all upstream outputs, mentally substitute — error-prone for complex multi-variable templates.

### Example 5: Understanding dynamically-built prompts

The chorus generation node builds prompts dynamically in a Python code node — f-strings with lens descriptions, song context, model assignments. These prompts don't exist as template files. Without the report, the agent must read the Python code, trace the variable values through the shared state, and mentally assemble the prompt.

With the report: open `generate-options/item-3.md`, read the Prompt section. Done.

## Relationship to Other Planned Features

### Iteration cache (Task 106)

Complementary. The cache makes re-runs faster; the report makes results understandable. When a cached node is served from cache, the report should show "Status: cached" with the original execution's data. The cache also signals which nodes to focus analysis on — cached nodes didn't change, re-executed nodes did.

### run-step (Task 106)

When `pflow run-step` executes a single node, it should produce a single report file in the same format. Consistent formatting whether running the full pipeline or testing one node.

### Trace files

The report is a READABLE VIEW of trace data, not a replacement. Trace files continue to exist for programmatic access and pflow internals. The main NEW data is the rendered prompt — this should be captured in the trace file too (it's currently missing from traces), then the report generator formats it for reading.

## Implementation Considerations

### Rendered prompt capture

Requires hooking into the template resolution step to capture the final prompt string before it's sent to the LLM provider. This is the most important implementation detail.

- For template-based prompts: capture after `${variable}` substitution
- For batch items with per-item prompts: capture each item's rendered prompt separately
- For prompts built by upstream code nodes: the prompt arrives at the LLM node already rendered — just capture what the node receives
- Store in the trace file alongside the response
- If the LLM call fails, the rendered prompt is STILL valuable for debugging — capture it before the call, not after

### Sub-workflow trace expansion

The parent trace shows sub-workflows as single nodes. The report needs internal visibility.

Options:
- Sub-workflows produce their own trace files — the report generator finds and nests them
- The parent trace embeds sub-workflow traces inline (increases trace size)
- Report generator approach is cleaner: read parent trace, for each sub-workflow node, find the corresponding sub-trace

### Report generation timing

**Incremental (preferred):** Each node writes its report file on completion. If the workflow crashes mid-execution, the report contains everything up to the crash — invaluable for debugging failures.

**Post-processing alternative:** Generate from the trace file after completion. Simpler but produces nothing on failure.

### Report location

```bash
# Explicit path
pflow workflow.pflow.md --report ./report/

# Default location (always generated)
# ~/.pflow/reports/{workflow-name}/latest/   (overwritten each run — enables git diff)
# ~/.pflow/reports/{workflow-name}/{timestamp}/  (preserved for history)
```

Consider always generating to default location — the overhead is minimal and developers who discover they need it will be glad it's there.

### Handling failures

- Failed nodes still get report files (with error info and the rendered prompt that caused the failure)
- Status clearly marked: "Status: error — [error message]"
- Downstream nodes that never executed: no report files (absence = never ran)
- Summary table clearly marks failed nodes

### Performance

Report generation should not significantly slow execution. Individual node report files are small (the prompt + response + a few lines of metadata). Writing them incrementally adds negligible I/O compared to the LLM call duration.

### Large batches

For batches with many items (e.g., 34 chorus scoring calls), the summary table is the primary view. Individual item files exist for drill-down. Consider a configurable threshold: above N items, individual files are opt-in rather than automatic.

## What This Eliminates for Workflow Authors

In our lyrics pipeline, this feature would eliminate or dramatically simplify:
- The `build-file-list` code node (~80 lines of Python formatting and organizing output)
- The `save-outputs` batch write-file node (55 files)
- All manual logic for numbering files, organizing directories, formatting batch results

That's ~100 lines of workflow-specific code that exists purely to give the development team visibility into the pipeline. Every workflow wanting this visibility currently builds it from scratch.

The workflow would still keep a small custom output step for the APPLICATION deliverables (the final songs in a user-friendly format), but the pipeline visibility would come from pflow automatically.