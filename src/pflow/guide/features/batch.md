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

**Text lines → JSON array:**
```shell
your-command | jq -R -s 'split("\n") | map(select(. != ""))'
```

**All outputs**: `${node.results}`, `.count`, `.success_count`, `.error_count`, `.errors`
Results contains only **successful** items. Each result contains `item` (original input) + inner node outputs, making results self-contained for downstream processing (e.g., `${node.results}` passed to LLM includes both inputs and outputs). With `error_handling: continue`, failed items are excluded from `results` — error details are in `errors`. `count` = total items attempted, `success_count` = `len(results)`, `error_count` = `len(errors)`.

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
    model: claude-opus-4-5
    effort: high
  - data: ${report}
    model: gpt-5.4
    effort: medium
parallel: true
```
````
Any `${item.field}` template works in any param — not just prompt/command.

**Dynamic indexing**: `${__index__}` gives current position (0-based). Use nested templates to correlate (requires `fail_fast` — not supported with `error_handling: continue`):
```
${previous.results[${__index__}]}     # Access by position (fail_fast only)
${previous.results[${item.idx}]}      # Access by item field (fail_fast only)
```

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
