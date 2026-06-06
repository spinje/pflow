# Batch Processing

**Use when**: Same operation on multiple items — "each", "for every", "in parallel", "N at a time". Add `batch` to any node:

````markdown
### process-each

Analyze each file.

- type: llm
- prompt: "Analyze: ${item}"
- batch:
    items: ${source.files}

### fetch-each

Fetch each URL in parallel.

- type: shell
- batch:
    items: ${urls}
    parallel: true
    max_concurrent: 40

```shell command
curl -s '${item}'
```
````

Current item: `${item}` (or custom `as`). Index: `${__index__}` (0-based). Results: `${node.results}` (array in input order).

**Options**:
| Field | Default | Notes |
|-------|---------|-------|
| `items` | required | Template reference OR inline array (must resolve to JSON array, not newline-separated string) |
| `as` | `"item"` | Custom name: `"file"` → `${file}` |
| `parallel` | `false` | Concurrent execution |
| `max_concurrent` | `10` | 1-100; use 30-50 for LLM APIs (rate limits) |
| `error_handling` | `"fail_fast"` | `"continue"` = process all despite errors |
| `max_retries` | `1` | Batch item total attempts after an exception escapes the node (`1` = no batch retry) |
| `retry_wait` | `0` | Seconds between batch item attempts |

**`parallel: false` is the default** — items run sequentially, in order. Use sequential when items must run in a specific order, when each item depends on side effects from the previous one (e.g. reading filesystem state a prior item wrote), or when you're using batch for bounded iteration. Sequential iteration over a sub-workflow is the cleanest loop-with-disk-state pattern — see `pflow guide sub-workflows` → Bounded iteration.

````markdown
### iterate

Run the child once per index, in order — each iteration sees the previous one's
filesystem changes.

- type: workflow
- workflow: ./process-one.pflow.md
- inputs:
    iteration: ${item}
- batch:
    items: [1, 2, 3, 4, 5]
    parallel: false
````

**Text lines → JSON array:**
```shell
your-command | jq -R -s 'split("\n") | map(select(. != ""))'
```

**All outputs**: `${node.results}`, `.count`, `.success_count`, `.error_count`, `.errors`
Results contains only **successful** items. Each result contains `item` (original input) + inner node outputs, making results self-contained for downstream processing (e.g., `${node.results}` passed to LLM includes both inputs and outputs). With `error_handling: continue`, failed items are excluded from `results` — error details are in `errors`. `count` = total items attempted, `success_count` = `len(results)`, `error_count` = `len(errors)`. `.errors` is always an array — `[]` when there are no failures, never `null` — so a downstream node can safely annotate it as a `list`/`array`.

**Batching over results nests one layer per stage.** When a later node batches over `${first.results}`, each `${item}` IS one of those entries — so `${item.response}` is the first node's output for that row and `${item.item}` is its original input. A third stage batched over the second's results adds another layer: `${item.item.response}` reaches two stages back. To avoid deep `item.item.item` chains, correlate earlier stages directly — see **Correlating parallel arrays** below.

**Batch replaces the normal output structure.** `${node.response}`, `${node.llm_usage}`, `${node.stdout}`, etc. do NOT exist at the top level. Access them inside results: `${node.results[0].response}`, `${node.results[0].llm_usage}`. Note: index-based access (`results[N]`) requires `fail_fast` mode (the default). With `error_handling: continue`, use iteration (`items: ${node.results}`) instead.

**Inline array pattern** (parallel independent operations):
Batch is the way to run operations concurrently (conditional branching picks ONE path, not multiple).
````markdown
### multi-format

Reformat the report in multiple styles concurrently.

- type: llm
- prompt: "Reformat as ${item.style}:\n${item.content}"

```yaml batch
items:
  - style: executive-summary
    content: ${report.result}
  - style: technical-details
    content: ${report.result}
  - style: action-items
    content: ${report.result}
parallel: true
```
````
**Completely different operations** (each item defines its own prompt and data):
````markdown
### parallel-tasks

Run completely different operations in parallel.

- type: llm
- prompt: ${item.prompt}

```yaml batch
items:
  - prompt: |
      Summarize the following data in exactly 2 sentences.
      Focus on key findings and actionable insights.

      Data: ${data}
  - prompt: "Extract action items from: ${data}"
  - prompt: "Translate to Spanish: ${other-data}"
parallel: true
```
````
Each runs independently: `${parallel-tasks.results[0].response}`, `${parallel-tasks.results[0].item}` (original input)

**Per-item configuration** — vary node params (model, temperature, reasoning_effort) per item:
````markdown
### compare-configs

Compare quality across different settings.

- type: llm
- model: ${item.model}
- reasoning_effort: ${item.effort}
- prompt: "Analyze: ${item.data}"

```yaml batch
items:
  - data: ${report}
    model: anthropic/claude-opus-4-5
    effort: high
  - data: ${report}
    model: openai/gpt-5.4
    effort: medium
parallel: true
```
````
Any `${item.field}` template works in any param — not just prompt/command.

**Correlating parallel arrays (zip)**: when two batches ran over aligned inputs and you need each row of one alongside the matching row of the other, there are two ways — pick by how much you trust the alignment:

- **Explicit zip node** — *preferred for anything non-trivial or likely to change.* A `code` node that pairs the arrays into clean records, ideally matching on a shared key (an id both rows carry) rather than on position. It is robust to reordering and `continue` mode, inspectable on its own (`--only`, `pflow report`), and survives later edits to the pipeline.
- **Inline `${__index__}`** — *concise, for simple, fixed, fail-fast cases.* Skip the node and reach the same-position element of the other array directly: fewer nodes, but it leans on a positional alignment invariant (see caveat below).

Inline form — iterate one array, reach the other by position:

````markdown
### combine

Revise each draft using its own review — iterate the reviews, reach the
same-position draft by index.

- type: llm
- batch:
    items: ${reviews.results}
    parallel: true

```prompt
Original draft:
${drafts.results[${__index__}].response}

Review:
${item.response}

Revise the draft, applying the review.
```
````

`${__index__}` also indexes by an item field: `${drafts.results[${item.idx}]}`.

**Alignment caveat**: zipping by position assumes both arrays are in the same order with no gaps — true only under `fail_fast` (the default). `error_handling: continue` drops failed items, which misaligns the arrays, and index access is not supported there anyway. When alignment isn't guaranteed, use the explicit zip node and match on a key.

**Indexing works on a node's `.results`, not on declared inputs.** `${my_input[${__index__}]}` does not resolve — pull the per-row value from an upstream node's `.results` instead.

**Using results**:
```markdown
### report

Summarizes the batch. Reads `success_count` and the results array from
the upstream batched node — not a per-item response, since batch replaces
the normal output shape.

- type: llm
- prompt: "Summary of ${process-each.success_count} items:\n${process-each.results}"
```

**Common mistake: missing explicit prompt wiring on batch LLM.** Batch items may have `prompt:` fields in the data, but the LLM node ignores them unless you wire it explicitly: `- prompt: ${item.prompt}`. Batch provides data; the node still needs explicit parameter references.

**Retry interaction:** `batch.max_retries` and node-level `retry:` are separate loops. Node-level retry handles transient failures inside the node attempt:

````markdown
### fetch-each

Fetch each URL with node-level exponential backoff.

- type: http
- url: ${url}
- retry:
    max: 3
    wait: 0.5
    backoff: exponential
- batch:
    items: ${urls}
    as: url
    parallel: true
````

For `llm`, `shell`, `mcp`, `code`, and file nodes, an exhausted node `retry:` budget ends the item as a handled failure, and `batch.max_retries` does not start another attempt for it. For `http` and `claude-code` nodes, an exhausted `retry:` budget surfaces as a failure that `batch.max_retries` re-attempts, so the upper bound is `batch.max_retries * retry.max` attempts per item.

Parallel batch workers inherit the configured node retry budget. A `fail_fast` batch cannot interrupt a worker that is already sleeping in backoff; exponential node backoff is clamped to 60 seconds per wait.
