# LLM Node

**Use for**: Tasks requiring judgment — summarizing, interpreting, deciding what matters. Costs tokens per workflow execution.

**Don't use LLM for**: Extracting fields from structured data (`${node.result.data.field}` does this for free), transforming/filtering data (use `code` node), or formatting with a fixed structure (use `code` node).

**The test**: Can you write a deterministic algorithm for it? YES → `code` node. NO → LLM.

Use `output_schema` for structured responses (guarantees valid JSON via constrained decoding).

**Debugging prompts**: Run with `--report` to see every LLM node's rendered prompt (templates resolved) alongside the actual response, token count, and cost. Ask the user if they want reports in the project (`--report-dir ./report/`) — useful for reviewing LLM responses together or tracking them in git.

**Iterating cheaply**: Use `--only <node>` to re-run a single LLM node — downstream is skipped, and unchanged `llm` upstream is reused from cache. Saves time and tokens when tuning prompts in multi-node workflows. Note: non-`llm` upstream (shell/code/http/file/mcp) re-executes on each `--only` run since those don't cache by default, so watch for side-effecting upstream nodes re-firing.

**Prompt caching**: When several LLM nodes or batch items reuse the same long
context, rubric, instructions, source text, or parent value, run
`pflow analyze-cache workflow.pflow.md` before editing cache fields. The
analyzer tells you when to add a workflow-level `## Cache`, add
`prompt_cache: [...]` to LLM nodes, add `prewarm: true` for batch LLM nodes, or
move stable prompt text before per-item data. Load `pflow guide prompt-caching`
for the full rules and examples.

**API keys**: see `pflow settings llm providers` for the list of LiteLLM provider names and their required env vars.

### Node Creation Pattern

`````markdown
### structured-analysis

Analyze data with specific criteria.

- type: llm
- temperature: 0.7
- model: openai/gpt-4

```yaml output_schema
type: object
properties:
  findings:
    type: array
    items:
      type: string
  risk_level:
    type: string
  recommendation:
    type: string
required:
  - findings
  - risk_level
  - recommendation
```

```prompt
Analyze this data according to these criteria:

Data:
${filter-and-reshape.result}

Criteria:
1. Identify patterns
2. Find anomalies
3. Suggest improvements
```
`````

Optional cache fields for LLM nodes:

- `prompt_cache: [chunk_name]` uses chunks declared in the workflow's `## Cache` block.
- `prewarm: true` lets parallel batch LLM nodes write a shared prefix once,
  then fan out as cache reads.
