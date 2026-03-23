# Execution Report Feature — Perspective from an AI Agent User

## Who I Am

I'm an AI agent that spent 5 sessions building a complex pflow workflow. I'm the target user for this feature. The feature request (`scratchpads/pflow-execution-report-feature-request.md`) has the full spec. This document adds the tacit knowledge — how I actually work, why certain design decisions matter more than others, what I learned the hard way, and what I'd want the implementing agent to think carefully about.

## How I Actually Work (Be Honest With You)

I was pushed hard by the user to be honest about what I actually do vs what I think I need. Here's the truth:

**I read output files.** That's my primary analysis tool. When a song is bad, I open the final lyrics, then trace upstream: concepts → diversity assignments → creative direction → chorus selection → reviews. I read individual files in sequence.

**I never opened a trace file.** Across 5 sessions, ~20 runs, I never once read the 2.7MB trace JSON. It's too dense, too large, and not designed for quality analysis. The trace has useful data (per-node cost, timing, model info) but the format makes it inaccessible.

**I reconstruct rendered prompts mentally.** When I need to know what an LLM saw, I read the prompt template file and mentally substitute the upstream outputs. For most prompts this works. For dynamically-built prompts (constructed in code nodes with f-strings), I can't reconstruct — I have to read the Python code, trace the variable values, and imagine the result.

**I built a custom output system and took it for granted.** The team wrote ~80 lines of Python to save every pipeline stage as numbered files in organized directories. This became my ONLY analysis tool. When the user asked "is the output format system not important to you?" I initially said no. Then I realized: it's the MOST important thing. I just didn't recognize it because I built it myself.

## What the Feature Request Gets Right

The spec accurately captures what I need. Let me highlight the parts that matter most:

### The rendered prompt is the centerpiece

This is genuine. When an LLM produces bad output, the first thing I want to see is what it received. For 80% of cases I can reconstruct this from templates + upstream files. For the remaining 20% (dynamically-built prompts), I cannot. That 20% includes:

- **Chorus generation prompts** — built in a Python code node that constructs f-strings with lens descriptions, song context, and model assignments. 12 different prompts per song, none of which exist as template files.
- **Chorus scoring prompts** — also built dynamically. 34 per song, each with the specific chorus text embedded.
- **Any future dynamic prompts** — as pipelines get more sophisticated, more prompts will be built dynamically.

For the other 80%, having the rendered prompt IS still valuable because it eliminates the mental reconstruction step. But the implementing agent should understand: the dynamic prompt case is where this feature provides genuinely NEW information that doesn't exist anywhere else.

### One file per node with consistent filenames

This is critical for two reasons the spec mentions but I want to emphasize:

1. **Git diff between runs.** When I change a prompt and re-run, I want to diff JUST the affected node's output between runs. With ~233 LLM calls and stochastic outputs, a full-report diff is thousands of lines of noise. Targeted diffs require separate files.

2. **Stochastic outputs mean most files change every run.** Even with identical prompts, LLM outputs differ between runs. So between any two runs, almost every file will show a diff. The value isn't "what changed" (everything changed) — it's "did my SPECIFIC prompt change produce the INTENDED effect at the SPECIFIC node I changed?" You need separate files to answer this.

### Metadata inline, not separate

When I'm reading an LLM node's output and see bad lyrics, my next question is often "which model produced this?" Having to open a separate metadata file or parse JSON kills the flow. The metadata header (5-6 lines at the top) answers this instantly.

## What the Feature Request Doesn't Capture Well

### The "I already have this" problem

The user caught me asking for things I already had. The implementing agent should be aware of this tension: pflow workflows can ALREADY save outputs via `write-file` nodes. Many workflows already produce readable output files. The execution report must be valuable ON TOP OF whatever custom output the workflow already produces.

The key differentiators vs custom output:
1. **Rendered prompts** — custom output saves responses, not prompts
2. **Automatic** — no custom code needed
3. **Consistent structure** — every workflow uses the same layout
4. **Metadata** — model, cost, timing per node
5. **Sub-workflow visibility** — custom output is usually flat; the report is hierarchical

If the report only provides what custom output already provides (just the responses), it's not valuable enough to justify the feature.

### The summary table's "Item Key" column

The spec shows batch summary tables with an "Item Key" column that uses meaningful labels. For example:

```
| # | Item Key | Model | ...
| 0 | emotional | gemini-3-flash | ...
| 1 | sensory | gemini-3-flash | ...
```

Where does "emotional" come from? It's the `focus` field in the batch item config. But different workflows use different field names. The `label_field` proposal in the spec addresses this, but it's a UX detail that needs careful thought. Options:

- Explicit `label_field` in batch config (requires workflow author to opt in)
- Heuristic: use the first string field in the batch item (fragile)
- Use the batch item's index plus whatever fields exist (verbose but safe)
- Let the report generator inspect the item and pick the most "label-like" field

I don't have a strong opinion on which, but the implementing agent should consider this.

### Report location and the "latest" concept

The spec mentions both timestamped and "latest" report locations. For my workflow, I always want "latest" — I diff the latest report against the previous one. Timestamped archives are nice but secondary.

The question: what happens to the previous "latest" when a new run overwrites it? If it's just overwritten, I lose the diff baseline. If it's moved to a timestamped archive, I have both.

The git-based approach is cleaner: if the report is in a git-tracked directory, each run overwrites the same files, and `git diff` shows what changed. This is what the user suggested ("how would the delta be different than just git diffing if the run was written into the same folder?").

## Things I Learned the Hard Way

### LLM nodes don't use `- inputs:`

This is the biggest pflow subtlety the implementing agent needs to understand. In pflow:

- **Code nodes** use `- inputs:` to map values from shared state to named Python variables
- **LLM nodes** do NOT use `- inputs:`. They resolve `${template_variables}` directly from the shared state during prompt rendering.

If you try `- inputs:` on an LLM node, it's silently ignored. The prompt template references like `${synthesize-sources.response}` are resolved by the template engine looking up `shared["synthesize-sources"]["response"]`.

This matters for the report because:
- For code nodes, the report can show "Inputs" (from the `- inputs:` config)
- For LLM nodes, the "inputs" are implicitly whatever template variables appear in the rendered prompt. The report can't easily show a clean "Inputs" table — but the rendered prompt itself shows everything the LLM received.

### Template validation errors in sub-workflows are silent

When a sub-workflow has a template validation error and is called from a batch with `error_handling: continue`, the error is swallowed. The batch item counts as "succeeded" with empty output. The workflow reports success with all-empty data.

This was a costly lesson (an entire run produced empty songs that "succeeded"). The execution report could help catch this: if a node's response is empty or suspiciously short, the report could flag it as a warning.

### The trace file structure

I explored the trace file during this session. Key findings for the implementing agent:

```python
trace["nodes"]  # array of 11 node objects (top-level only)
trace["nodes"][i]["shared_after"]  # full shared state after node execution
trace["nodes"][i]["shared_after"]["__llm_calls__"]  # array of ALL LLM calls (233 entries)
trace["nodes"][i]["shared_after"][node_id]["response"]  # the LLM response text
trace["nodes"][i]["shared_after"][node_id]["llm_usage"]  # model, tokens, cost
trace["llm_summary"]  # total_calls, total_tokens, models_used
```

Each `__llm_calls__` entry has: `model`, `input_tokens`, `output_tokens`, `total_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `cost_usd`, `node_id`, `batch_item_index`.

The rendered prompt is NOT in the trace. Adding it to the trace would be the foundation for both the execution report and any future analysis tooling.

Sub-workflow nodes (like `create-songs`) appear as single `WorkflowExecutor` entries in the parent trace. Their internal nodes are NOT visible. The report generator needs to find and parse sub-workflow traces (if they exist) or the trace format needs to embed sub-workflow details.

## What I'd Actually Use First

If the implementing agent needs to prioritize, here's my ranking of what I'd use most:

1. **Rendered prompt capture** (in the trace AND in report files) — this is the one thing I genuinely can't get today
2. **Summary file** with per-node cost/timing table — quick scan of what happened
3. **Individual LLM node files** with prompt + response + metadata — targeted investigation
4. **Sub-workflow expansion** — seeing inside batch sub-workflows without hunting for separate traces
5. **Batch summary tables** — overview of batch operations before drilling into items

I'd use #1 and #2 every run. I'd use #3 when debugging. I'd use #4-5 occasionally for specific investigations.

## Potential Gotchas for Implementation

### Prompt rendering happens at different levels

For a simple LLM node like `synthesize-sources`, the prompt is rendered once from a template file. Easy to capture.

For a batch LLM node like `score-choruses`, each batch item has its own prompt (from `prompt: ${item.prompt}` where `item.prompt` was constructed by an upstream code node). The rendered prompt is different per item. The report needs to capture per-item prompts in the individual item files.

For a batch workflow node like `create-songs`, each item triggers a full sub-workflow execution. The "prompt" concept doesn't apply at the batch level — it applies to each LLM node INSIDE each sub-workflow item. The report handles this through hierarchical folders.

### File size

The rendered prompt for `write-lyrics` includes the full creative brief, creative direction, architecture, easter eggs, chorus, and runner-up choruses. This can be 5,000+ words. The report file for a single write-lyrics node might be 10,000+ words (prompt + response).

Multiply by 4 songs = 40,000+ words just for the write-lyrics files. The full report for our pipeline could be 200,000+ words across all files. This is fine for an AI agent (we read targeted files, not the whole report) but the implementing agent should be aware of the scale.

### Non-LLM nodes that matter

The report spec focuses heavily on LLM nodes, but some code nodes produce critically important output that I analyze frequently:

- `build-grouped-items` (code node that constructs chorus generation items) — its output determines what lenses and models are used
- `rank-choruses` (code node that sorts scored choruses) — its output determines which choruses the judge sees
- `extract-lyrics` (code node that splits deliberation from lyrics) — if this parses wrong, the final lyrics are broken

These code nodes should have equally detailed report files. The spec addresses this but the implementing agent should know: code node files are just as important as LLM node files for debugging.

### The `output_schema` interaction

Some LLM nodes use `output_schema` for structured JSON output (like `generate-concepts` and `enforce-diversity`). When `output_schema` is set:
- The LLM response is JSON, not prose
- The JSON might be pretty-printed or compact
- If JSON parsing fails, the raw response is still valuable

The report should show the PARSED result (the structured object) for readability, with the raw response available if parsing failed.

## Questions I'd Want Answered

1. **Does pflow already capture sub-workflow traces?** If `create-songs` (a batch workflow node) produces trace files for each song-creator execution, the report generator can find them. If not, the trace format needs to be extended to embed sub-workflow execution data.

2. **Where does template rendering happen in the codebase?** The rendered prompt needs to be captured at the point where templates are resolved. This is probably in the LLM node's `prep()` or `exec()` method. The implementing agent should trace the code path from prompt template → template resolution → API call to find the right capture point.

3. **Can the report be generated from the trace alone, or does it need to hook into live execution?** If the trace captures rendered prompts and sub-workflow details, a post-processing report generator works. If not, the report needs to hook into live execution to capture data that the trace doesn't store.

4. **How do batch items map to sub-workflow traces?** When a batch of 4 sub-workflows runs in parallel, how are the resulting traces identified and associated with their batch index? This mapping is essential for building the hierarchical report structure.
