# Task 106: Iteration Cache & Run-Step — Perspective from an AI Agent User

## Who I Am

I'm an AI agent that spent 5 sessions building a complex pflow workflow (an AI lyrics generation pipeline). I'm the target user for this feature. This document captures what I've learned about how I actually work with pflow workflows and what would make iteration faster.

The task spec (`.taskmaster/tasks/task_106/task-106.md`) has the full technical design. This document adds the USER perspective — what I'd actually do with these features, where the design works perfectly, and where I'd want the implementing agent to think carefully.

## The Pipeline I Work With

For concrete context on the kind of workflow this feature needs to support:

```
sources[] → fetch (shell/mcp, 4s)
          → analyze (6 LLM calls in parallel, 16s)
          → synthesize (1 LLM call, 14s)
          → generate concepts (1 LLM call, 10s)
          → enforce diversity (1 LLM call, 11s)
          → create 4 songs (batch sub-workflow, 4 items in parallel, 200s)
               each song: 12 nodes including a sub-sub-workflow (chorus-chooser, 8 nodes)
          → evaluate (1 LLM call, 15s)
          → save outputs (55 write-file calls)

Total: ~280 seconds, ~233 LLM calls, ~$1.58
```

When I change a prompt (say `write-lyrics.prompt.md`), I re-run the whole pipeline. Nodes 1-5 are completely unchanged but still execute — wasting ~55 seconds and ~$0.08 every time. Over a session with 10+ iterations, that's 10 minutes and a dollar wasted on repeating identical work.

## What the Iteration Cache Means for My Workflow

### The primary use case: prompt iteration

This is what I do most. Edit a prompt file, re-run, evaluate quality, edit again. The cache would:

1. Detect that `fetch-sources`, `analyze-sources`, `synthesize-sources` have unchanged configs and unchanged upstream
2. Serve their results from cache (instant)
3. Detect that `generate-concepts` has a changed prompt file → re-execute
4. Everything downstream of concepts also re-executes (correct — inputs changed)

Result: ~55s savings per iteration. Over a session, this adds up significantly.

### The secondary use case: debugging a specific song

When Song C is bad, I might want to re-run JUST Song C with a tweaked creative-direction prompt, without re-running Songs A, B, D. The cache doesn't directly help here (all 4 songs are one batch node), but `run-step` does — I could run just the creative-direction step with Song C's concept as input.

### What I DON'T need the cache for

- Production runs (different source each time — cache always misses)
- First run of a new workflow (nothing cached yet)
- Runs where I changed the source input (everything invalidates)

The cache is purely a development-time tool. This aligns with the task spec's scoping to file-based workflows only.

## Cache Invalidation: The Critical Details

The task spec covers the invalidation logic well. Here's what matters from my experience:

### External prompt file changes MUST invalidate

This is the most common case and the one most likely to be missed. My workflows use external prompt files:

```yaml
### write-lyrics
- type: llm
- prompt: ./write-lyrics.prompt.md
```

If I edit `write-lyrics.prompt.md`, the node's YAML config hasn't changed — it still says `prompt: ./write-lyrics.prompt.md`. But the content of that file has changed, so the rendered prompt will be different. The cache MUST detect this.

The `config_hash` in the task spec hashes `node.type + node.params + node.batch`. If `node.params` includes the prompt file PATH but not its CONTENT, the cache will serve stale results after a prompt edit. This would be the most frustrating bug possible — you edit a prompt, re-run, and get the same output.

**Recommendation:** When computing `config_hash` for an LLM node, include the hash of the prompt file's CONTENT if it references an external file. Same for any parameter that references a file path (like `- prompt: ./file.prompt.md`).

### Sub-workflow file changes

Same issue one level deeper. My workflow calls sub-workflows:

```yaml
### create-songs
- type: workflow
- workflow: ./song-creator/song-creator.pflow.md
```

If I edit anything inside `song-creator.pflow.md` (or any of its prompt files), the parent node's config hasn't changed. The cache needs to detect that the SUB-WORKFLOW's content changed.

**Recommendation:** For workflow-type nodes, the config hash should include a hash of the entire sub-workflow file (and recursively, its sub-workflows and prompt files). This is expensive to compute but essential for correctness.

### Input changes vs config changes

Two distinct invalidation triggers:
1. **Config changed** — I edited the node's prompt or parameters. The cache entry for THIS node is invalid.
2. **Upstream changed** — an upstream node re-executed (because ITS config or inputs changed). This node's INPUTS are different, so its cache is invalid even if its config is unchanged.

The task spec handles both. I want to emphasize: #2 is the cascade case. If I change the concept generator prompt, EVERY downstream node must re-execute — not because their configs changed, but because their inputs (which come from upstream nodes) changed.

### What should NOT invalidate

- **Downstream changes.** If I edit `write-lyrics.prompt.md`, the `generate-concepts` cache should remain valid. The task spec gets this right.
- **Cosmetic changes.** If I edit a node's step description (the markdown text above the YAML), the cache should remain valid. Step descriptions are documentation, not execution parameters.
- **Output file changes.** If I manually delete or edit files in the `output/` directory, the cache should remain valid. The cache is about pipeline execution, not application output.

## Run-Step: What I'd Actually Use It For

### Testing a prompt change in isolation

Most common: I change `generate-concepts.prompt.md` and want to see what concepts it produces WITHOUT running the full pipeline.

```bash
pflow run-step lyrics-generator.pflow.md generate-concepts \
  synthesize-sources.response="$(cat output/0022/03-creative-brief.md)"
```

I provide the creative brief from a previous run as input. The concept generator runs in ~10 seconds, I see the 4 concepts, I adjust the prompt, run again. Inner loop is seconds, not minutes.

### The input resolution challenge

This is where it gets tricky. The concept generator's prompt template references `${synthesize-sources.response}`. For `run-step` to work, I need to provide this value. The task spec proposes mapping CLI args by input variable name.

But LLM nodes in pflow DON'T have an `- inputs:` parameter (this was a hard-won lesson from session 4 — `- inputs:` only works on code nodes, it's silently ignored on LLM nodes). LLM nodes resolve template variables directly from the shared state. So `run-step` for an LLM node needs to:

1. Parse the prompt (or prompt file) for template variables like `${synthesize-sources.response}`
2. Map CLI args to those template variable paths
3. Place them in the shared state so the template resolver finds them

This is more complex than the task spec's input resolution section suggests. The CLI arg mapping needs to work with dotted paths: `synthesize-sources.response=...` needs to create `shared["synthesize-sources"]["response"] = ...`.

### Using cached state as input

Even better than manual CLI args: if the iteration cache exists from a previous run, `run-step` could use the cached shared state as the starting point. Then I don't need to specify inputs manually — they're already in the cache from the last full run.

```bash
# Uses cached state from last run as inputs
pflow run-step lyrics-generator.pflow.md generate-concepts
```

This would be the ideal UX. Edit a prompt, `run-step` the node, it uses cached upstream state, shows the result. If the cache doesn't exist, fall back to requiring manual inputs.

### Batch items and sub-workflows

`run-step` for a batch node: should it run ALL items or let me specify which one?

```bash
# Run just Song C (item 2) of the create-songs batch
pflow run-step lyrics-generator.pflow.md create-songs --item 2
```

This would be incredibly powerful for debugging a specific song. But it requires:
- Parsing the batch config to understand item structure
- Extracting the specific item from the batch items list
- Running the sub-workflow with just that item's inputs

This might be out of scope for the initial implementation, but it's the case I'd use most often.

## Edge Cases from Real Usage

### Parallel batch nodes and timing

My pipeline runs 4 songs in parallel. If run A cached all 4 songs, and I change the write-lyrics prompt, all 4 songs need to re-execute. But they should still run in PARALLEL, not serially. The cache should preserve the parallelism characteristics of the original batch.

### Sub-sub-workflows

My pipeline has 3 levels of nesting: lyrics-generator → song-creator → chorus-chooser. The cache needs to handle this recursion correctly. If I change `select-chorus.prompt.md` (inside chorus-chooser), the invalidation cascade is:

1. `select-chorus` node inside chorus-chooser → invalid (prompt file changed)
2. `choose-chorus` sub-workflow call inside song-creator → invalid (sub-workflow content changed)
3. `create-songs` batch inside lyrics-generator → invalid (sub-workflow content changed)
4. Everything downstream of `create-songs` → invalid (upstream changed)
5. Everything upstream of `create-songs` → VALID (unchanged)

This is 3 levels of file-content hashing. Getting this right is essential — getting it wrong means either stale results (dangerous) or unnecessary re-execution (wasteful but safe).

### Error recovery

If a run fails at node 8 of 11, the cache should contain successful results for nodes 1-7. On the next run (after fixing the issue), nodes 1-7 should be served from cache. The task spec addresses this.

But: what if a node SUCCEEDED but produced BAD output? In my pipeline, a song might "succeed" (no errors) but produce terrible lyrics. I might want to force re-execution of that specific node with a tweaked prompt. The task spec doesn't cover selective invalidation beyond config changes.

**Recommendation:** A simple `--no-cache` flag (or `--fresh`) that bypasses the cache entirely would handle this. More granular control (`--rerun=node_name`) is listed as future scope, which is fine.

### Code node with side effects

The task spec mentions side effects (GitHub issues, emails). In my pipeline, the `save-outputs` node writes 55 files to disk. If served from cache, those files won't be written. That's CORRECT for the cache's purpose (don't repeat work), but it means the output directory won't exist after a cached run.

Should the cache re-execute write-file nodes even when upstream is cached? Or should it cache them too (and skip the writes)?

**My preference:** Cache them too. If I'm iterating on a prompt, I don't need the output files re-written every time. I'll do a clean run (with `--no-cache` or `--fresh`) when I want the full output.

### The `error_handling: continue` interaction

My pipeline uses `error_handling: continue` on batch nodes. If one song fails in a batch of 4, the other 3 succeed. The cache should cache the 3 successful songs. On re-run (after fixing the issue), only the failed song should re-execute.

But wait — this means caching at the BATCH ITEM level, not the BATCH level. The task spec says "Cache entire batch result, not individual items." For my use case, per-item caching would be significantly more valuable, but I understand the complexity tradeoff.

## The Development Loop This Enables

With both cache and run-step working:

```
1. Edit generate-concepts.prompt.md
2. pflow run-step lyrics-generator.pflow.md generate-concepts
   → Uses cached creative brief as input
   → Shows 4 concepts in 10 seconds
   → I read them, decide they're better
3. pflow lyrics-generator.pflow.md sources='["..."]'
   → Cache hit: fetch, analyze, synthesize (instant)
   → Re-executes: concepts onwards
   → Full run: ~225s instead of ~280s (55s saved)
4. Read output, analyze quality
5. Edit write-lyrics.prompt.md
6. pflow run-step lyrics-generator.pflow.md write-lyrics
   → Uses cached concept, direction, architecture, chorus as inputs
   → Shows lyrics in 5 seconds
   → I evaluate, adjust, run again
7. When satisfied, full run for final output
```

vs today:

```
1. Edit prompt
2. pflow lyrics-generator.pflow.md sources='["..."]'
   → Full 280s run, $1.58
3. Read output
4. Edit prompt
5. Another 280s run, another $1.58
6. Repeat
```

The difference is transformative for development velocity.

## Relationship to the Execution Report Feature

The iteration cache and the execution report (see `scratchpads/pflow-execution-report-feature-request.md`) are complementary:

- **Cache** makes iteration FASTER
- **Report** makes results UNDERSTANDABLE
- Together: fast iteration with clear feedback

The report should indicate cached vs re-executed nodes. This tells the agent "nodes 1-5 were cached, only 6-11 ran — focus your analysis on 6-11." This is a navigation aid that makes diffing even more targeted.

The execution report's rendered prompt capture is also relevant to the cache: if the cache stores the rendered prompt (not just the response), then the report can show it even for cached nodes. This helps verify that the cache served the RIGHT result — "yes, this cached prompt matches what I'd expect."

## What I'd Want the Implementing Agent to Investigate

1. **External file content hashing** — how to efficiently hash the content of prompt files and sub-workflow files referenced by nodes. This is the #1 correctness concern. Consider: file modification timestamps as a fast check before full content hashing?

2. **The `- inputs:` vs template variable distinction** — `run-step` for LLM nodes needs to resolve template variables, not `inputs`. This is a pflow-specific subtlety that the implementing agent needs to understand. Read the session 4 progress log section about the `- inputs:` bug for context.

3. **Cache + run-step integration** — can `run-step` automatically use cached shared state as input? This is the UX that would make `run-step` seamless. Without it, the user has to manually specify all input values.

4. **Per-item batch caching** — the task spec says cache entire batches. For workflows with expensive parallel batches (4 songs at ~$0.32 each), per-item caching would save significantly more when only one item needs re-execution. This might be a future enhancement, but the data model should be designed to support it later.

5. **`--no-cache` / `--fresh` flag** — for when the agent wants to force a clean run. Essential escape hatch.
