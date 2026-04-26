# LLM Node

**Use for**: Tasks requiring judgment — summarizing, interpreting, deciding what matters. Costs tokens per workflow execution.

**Don't use LLM for**: Extracting fields from structured data (`${node.result.data.field}` does this for free), transforming/filtering data (use `code` node), or formatting with a fixed structure (use `code` node).

**The test**: Can you write a deterministic algorithm for it? YES → `code` node. NO → LLM.

Use `output_schema` for structured responses (guarantees valid JSON via constrained decoding).

**Debugging prompts**: Run with `--report` to see every LLM node's rendered prompt (templates resolved) alongside the actual response, token count, and cost. Ask the user if they want reports in the project (`--report-dir ./report/`) — useful for reviewing LLM responses together or tracking them in git.

**Iterating cheaply**: Use `--only <node>` to re-run a single LLM node (upstream cached, downstream skipped). Saves time and tokens when tuning prompts in multi-node workflows.

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

