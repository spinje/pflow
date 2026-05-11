# pflow Framework Fundamentals

> **Purpose**: Enable AI agents to build reusable workflows by transforming user-specific examples into general-purpose tools with precision and clarity.

### Core Mission
You help users build **reusable workflows** - automated sequences that transform data reliably.
- Users describe their need with ONE specific example
- You build a tool that works for ANY similar case
- Every specific value becomes a configurable input
- The workflow runs deterministically every time

### Primary Decision Rule + Quick Wins

**THE fundamental decision:**
Data transformation → `code` node · External tools/side effects → `shell` node · Interpretation/judgment → `llm` node

**Quick wins (memorize these):**
- **Step order = execution order** → No wiring needed, steps run top to bottom
- **Templates reach any previous step** → No need for pass-through nodes
- **Same operation per item?** → `batch` config (Batch Processing pattern)
- **Need different paths?** → `on-error:` or code node with `next` (Conditional Branching pattern)
- **Keep it simple** → Don't invent requirements or add unnecessary nodes.

### Core Philosophy - Understanding the WHY

**Why pflow exists**: Workflows are executable documentation. You write a `.pflow.md` file that reads like a runbook — prose explains intent, parameters define behavior, code blocks execute. Once built, the workflow runs deterministically forever without AI overhead: same inputs, same outputs, every time.

**Why step order vs templates matter**: Step order defines WHEN nodes run (top to bottom in `## Steps`). Templates define WHAT DATA each node sees (any previous node's output). This separation lets you build complex data flows within simple linear execution.

**Why code/shell over LLM for structured data**: Structured operations should be deterministic. Using LLM for JSON extraction costs tokens, adds latency, and risks hallucination. Code nodes are free, instant, and operate on native objects. Reserve LLM for tasks requiring understanding, not extraction.

**Why simple over thorough**: Don't add steps "just in case." If you're passing `${node.result}` wholesale to the next node, you don't need to know its structure. Only investigate when you need specific nested paths.

**Why general over specific**: Users show you their immediate problem, but they'll have similar problems tomorrow with different data. Making values configurable transforms single-use scripts into reusable tools. Exception: when users explicitly say "for MY repository" or "only for this specific file" - then they might want a specific tool, not a general one.

### Two Fundamental Concepts - Step Order vs Templates

**This distinction causes 80% of workflow rebuilding. Understand it completely.**

#### Concept 1: Execution Order (Step Order)
**Step order defines WHEN nodes run** - strictly sequential, one after another.

```
fetch-data → process-data → save-results
```

**What this means precisely:**
- `process-data` starts ONLY after `fetch-data` completely finishes
- `save-results` starts ONLY after `process-data` completely finishes
- No node can start until its predecessor completes
- By default each node has one successor (next in document order), but conditional branching can override this (see Conditional Branching pattern)
- No parallel execution (use `batch` with `parallel: true` for concurrent operations)

#### Concept 2: Data Access (Templates)
**Templates define WHAT DATA nodes can see** - any node can access any PREVIOUS node's output.

**Critical example showing the difference:**
`````markdown
## Steps

### step1-fetch

Fetches the source feed. Downstream assumes `response.items` exists.

- type: http
- url: ${api_url}

### step2-timestamp

Captures run time. `cache: false` — this node reads live clock state.

- type: shell
- cache: false

```shell command
date +%Y-%m-%d
```

### step3-transform

Drops incomplete items and flattens each to `{id, name}` for downstream
consumers.

- type: code
- inputs:
    items: ${step1-fetch.response.items}

```python code
items: list

result: list = [{'id': i['id'], 'name': i['title']} for i in items]
```

### step4-analyze

Summarizes the transformed records — one LLM pass over the whole batch.

- type: llm

```prompt
Analyze this data from ${step3-transform.result} fetched at ${step2-timestamp.stdout}
```

### step5-report

Assembles the final report. Reads from every upstream step:

* `step1-fetch.response` — raw counts for the footer
* `step3-transform.result` — cleaned records
* `step4-analyze.response` — narrative summary
* `step2-timestamp.stdout` — run time

- type: llm

```prompt
Create report:
Raw: ${step1-fetch.response}
Items: ${step3-transform.result}
Analysis: ${step4-analyze.response}
Time: ${step2-timestamp.stdout}
```
`````

**Key insights from this example:**
- `step3-transform` accesses `step1-fetch.response.items` directly (skipping step2)
- `step5-report` accesses ALL previous outputs (step1, step2, step3, step4)
- Edges (step order) only control execution sequence, NOT data availability
- Think of it as: step order creates a timeline, templates access history
- In `.pflow.md`, edges are implicit — steps execute top to bottom in document order

**Data availability at each step:**
| Execution Order | Data Available to This Node |
|-----------------|------------------------------|
| step1-fetch | (none) |
| step2-timestamp | step1-fetch |
| step3-transform | step1-fetch, step2-timestamp |
| step4-analyze | step1-fetch, step2-timestamp, step3-transform |
| step5-report | ALL previous nodes |

This accumulation pattern is fundamental - each node adds to the available data pool.

### Common Misunderstandings About Step Order vs Templates

❌ **Wrong**: "If I put steps A→B→C, then C can only see B's output"
✅ **Right**: C can access A, B, or both. Step order doesn't restrict data access.

❌ **Wrong**: "I have to design steps so each one only uses the previous one's data"
✅ **Right**: Design steps for their purpose. Then in templates, pull data from wherever you need.

❌ **Wrong**: "Templates must follow the step order"
✅ **Right**: Templates can jump over steps. Step order just defines execution sequence.

### What Workflows CANNOT Do (Hard Limits)

**Recognize these immediately and offer alternatives:**

#### ❌ No Loops or Iteration
**User wants**: "Process each file in a directory differently based on its type"
**Why impossible**: Workflows can't create dynamic numbers of operations
**Alternative**: "I'll create a workflow that processes ALL files in one batch operation, applying the same logic to each"
**→ Solution**: `batch` config enables this. See Batch Processing pattern.

#### ✅ Conditional Branching (Supported)
**User wants**: "If the API returns error, handle it; else process data"
**How**: Use `- on-error:` for error routing, or a `code` node with `next: str = "target"` for data-driven decisions. See Conditional Branching pattern below.

#### ❌ No State or Memory
**User wants**: "Track which records we've already processed and skip them"
**Why impossible**: Each workflow run is completely independent
**Alternative**: "The workflow will process all current records. You could maintain a processed list externally"

#### ❌ No User Interaction During Execution
**User wants**: "Ask me to confirm before deleting files"
**Why impossible**: Workflows run to completion without pausing
**Alternative**: "I'll create a workflow that lists files to delete, then a separate one that performs deletion after your review"

#### ❌ No Parallel Paths
Conditional branching picks ONE path (not multiple simultaneously). Batch processing handles concurrent operations on multiple items.

### One Workflow or Multiple? (Critical Decision)

**This decision shapes the entire implementation:**

#### Build ONE Workflow When:
- Steps are always done together as a unit
- Data flows between all steps
- User wants a single command to run everything
- The operations are logically coupled

**Example**: "Fetch API data, validate it, transform it, and store it"
→ ONE workflow (always done as complete sequence)

#### Build MULTIPLE Workflows When:
- Steps might be run independently
- Different scheduling/triggers needed
- Operations serve different purposes
- User might want partial execution

**Example**: "Monitor GitHub PRs, monitor issues, and monitor commits"
→ THREE workflows (each monitoring task is independent)

#### Compose with Sub-Workflows When:
Reusable sub-tasks needed across workflows, or 30+ nodes benefit from decomposition. See `pflow guide sub-workflows`.

#### The Litmus Test
Ask yourself: "Would a user ever want to run step X without step Y?"
- If YES → Separate workflows
- If NO → Single workflow, or nested workflows if sub-tasks are reusable

**When unsure, ask the user directly**:
"Should this be one workflow that does everything, or separate workflows you can run independently?"

### Common Workflow Shapes

Most workflows fit one of these patterns:
- **Fetch → Transform → Store** — get data, reshape it, save/send (most common)
- **Fetch → Decide → Branch** — get data, classify, route to different handlers
- **Iterate → Collect → Aggregate** — same operation on N items, combine results (batch)
- **Multi-service coordination** — Service A → Transform → Service B → Service C

### Node Type Selection

**Which pflow node to use:**
- Data transformation (filter, reshape, compute) → `code`
- External tools & side effects (git, curl, docker) → `shell`
- Unstructured data / interpretation → `llm`
- JSON REST APIs → `http`
- Binary/streaming data → `shell` with curl
- Service-specific APIs (Slack, GitHub, Postgres) → `mcp`
- Reuse existing workflow → `workflow`

Run `pflow guide <node-type>` for details on any node.

### Before You Build

**Identify**: Inputs needed · Processing steps · Output format · Credentials

**Design**: Map execution order (which steps run when) and data dependencies (which templates reference which nodes) before writing.

**Plan**: Requirements unclear? → Present 2-3 options with tradeoffs. Requirements clear? → State plan and confirm before building.

**Clarify vague requirements** — map ambiguous user language to pflow concepts:
- "recent messages" → add a `limit` input with `- default: 10`
- "handle errors" → use `- on-error: handler-node` to route failures
- "process the data" → ask: "What's the data source? What processing?"
- "send notification" → ask: "Where? (email, Slack, etc.)" → determines which MCP node

### Finding Building Blocks

```bash
pflow mcp find "[complete description of ALL operations needed]"
```

**Effective task descriptions:**
```bash
# ❌ Too vague
pflow mcp find "process data"

# ✅ Complete and specific
pflow mcp find "fetch JSON from REST API, extract specific fields, validate data completeness, transform to CSV format, upload to S3 bucket"
```

### Building the Workflow

**Build incrementally** — start with the core data path (2-3 nodes), get it working, then add complexity. Caching makes re-runs fast (see Running and Iterating below).

**Development Format**

Workflows are `.pflow.md` files using standard markdown structure:

`````markdown
# Workflow Title

Description of the workflow. This becomes the description shown in `pflow list`.

## Inputs

### source_url

URL of the feed to pull records from.

- type: string
- required: true

## Steps

### fetch-records

Fetches the feed and hands the raw response to downstream nodes.

- type: http
- url: ${source_url}

## Outputs

### records

Parsed record array from the fetch response.

- source: ${fetch-records.response.items}
`````

**Input fields**: `type` (string|number|integer|boolean|array|object|any), `required` (true|false), `default` (only when required: false), `stdin` (true|false — only one input can have this), description as prose.

**Output fields**: `source` (template expression like `${node.key}`), `type` (optional hint), `stdout` (true|false — at most one output may set this; marks the output that streams to stdout in text mode), description as prose.

**Node fields**: `type` (required), all other params as `- key: value`. Code/prompts/batch go in tagged code blocks.

**Execution order**: Top to bottom in `## Steps`. No explicit edges.

**Outputs**: Optional — skip for automation workflows (send, post, update).

**Key rules:**
- `## Inputs` and `## Outputs` are optional. `## Steps` is required (at least one node).
- Every entity (`###` heading) must have a prose description that adds information not derivable from the name, type, or params — the role in the flow, a contract, a constraint, or a rationale.
- Use `-` for parameters, `*` for documentation bullets.
- Code blocks require a tag: `shell command`, `python code`, `prompt`, `yaml batch`, `yaml output_schema`
- Batch config: inline `- batch:` for simple cases, `yaml batch` code block for complex arrays
- Any code block parameter can reference an external file instead: `- prompt: ./prompts/system.md`, `- code: ./scripts/transform.py`. Paths are relative to the workflow file. Use for long prompts or reusable scripts.

**Description shapes** — match the shape to the content:
- **One-liner** — role is obvious, one contract sentence is enough.
- **Two-to-three sentences** — stakes, failure modes, or a downstream contract to surface.
- **Bulleted enumeration** — input accepts multiple shapes, or output has multiple fields worth naming.
- **Bolded sub-headings** — multiple design decisions to call out on one entity.
- **Prose + callout bullet** — operational detail (timeout, error handling, cache) worth pulling out of the paragraph.

**Nesting backticks:** Use 4+ backticks when content contains ```:

````prompt
Return data in this format:
```json
{"status": "ok"}
```
````

Save this as `my-workflow.pflow.md` — it's ready to run from the file path.

#### Input Declaration - Complete Rules

**Decision process for EVERY value:**

```
Is this value in the user's request?
├─ YES → Is it marked with "always" or "only"?
│        ├─ YES → Hardcode it
│        └─ NO → Make it an input
└─ NO → Is it implementation detail (prompt, Python code, shell command)?
         ├─ YES → Hardcode it (users don't customize implementation)
         └─ NO → Is it a system constraint?
                  ├─ YES → Hardcode it
                  └─ NO → Would users want to configure this?
                           ├─ YES → Make it an input with default
                           └─ NO → Hardcode it
```

**Key insight**: LLM prompts, Python code, and shell commands are HOW the workflow works, not WHAT it processes. These stay hardcoded unless the user specifically asks to customize them.

**Input examples with rationale:**
```markdown
## Inputs

### api_endpoint

API URL to fetch data from. User-specified value — always an input.

- type: string
- required: true

### limit

Maximum items to process. User mentioned but with sensible default.

- type: number
- required: false
- default: 10

```

### Running and Iterating

```bash
pflow ./workflow.pflow.md param1=value1 param2=value2
```

Errors include fix suggestions — read them carefully and apply the recommended fix.

Caching is automatic — unchanged nodes return instantly on re-run. Use this:

- Edit a prompt or parameter → re-run → only changed nodes re-execute
- `--dry-run` — preview plan + historical cost/duration without executing (expensive LLM runs, verifying what an edit invalidated)
- `--only <node>` — run just that node (upstream from cache, downstream skipped)
- `--no-cache` — bypass pflow memo-cache reads; provider prompt caching may still apply
- `cache: false` on a node — permanently opt out for nodes reading runtime state (date, git branch, env vars)
- `pflow report` — when errors aren't enough, inspect per-node resolved inputs and outputs

Provider prompt caching: if many LLM calls reuse the same long context, run
`pflow analyze-cache workflow.pflow.md`, then follow `pflow guide prompt-caching`.

```bash
# Re-run just one node (upstream cached, downstream skipped)
pflow ./workflow.pflow.md --only node-name

# Bypass pflow memo-cache reads; provider prompt caching may still apply
pflow ./workflow.pflow.md --no-cache
```

`--no-cache` still writes memo results for later runs. It does not disable LLM
provider prompt/context caching declared with `## Cache` / `prompt_cache:`, OpenAI
automatic prompt caching, or Gemini implicit caching.

### Saving (Optional)

Your workflow works from a file path — saving is optional. Save to the library when you want name-based execution from anywhere:

```bash
pflow save /path/to/workflow.pflow.md --name workflow-name
```

See `pflow save --help` for details.

### Template Variable Complete Reference

#### Resolution Order (This Matters)
1. Check workflow `inputs` first
2. Then check previous node outputs (in execution order)
3. Error if not found

#### Critical: Automatic JSON Parsing for Simple Templates

**Simple templates (`${var}`) automatically parse JSON strings.** This enables direct data access without intermediate extraction steps.

**Two contexts where auto-parsing occurs:**

1. **Path traversal**: `${node.stdout.field}` parses JSON to access nested properties
2. **Inline objects**: `{"data": "${node.stdout}"}` parses JSON for structured data composition

**What gets parsed:**
- All JSON types: objects `{}`, arrays `[]`, numbers, booleans, strings, null
- Shell **stdout** with trailing `\n` is automatically stripped (disable with `strip_newline: false`). stderr is never modified.
- Plain text and invalid JSON gracefully stay as strings

**Concrete examples** (inline object context):
| Template | Source value | After resolution |
|----------|--------------|------------------|
| `{"data": "${shell.stdout}"}` | `'{"items": [1,2,3]}\n'` | `{"data": {"items": [1,2,3]}}` |
| `{"items": "${mcp-node.result}"}` | `'[{"id": 1}, {"id": 2}]'` | `{"items": [{"id": 1}, {"id": 2}]}` |
| `{"count": "${shell-node.stdout}"}` | `'42\n'` | `{"count": 42}` |
| `{"valid": "${check.stdout}"}` | `'true'` | `{"valid": true}` |
| `{"text": "${any.output}"}` | `'plain text'` | `{"text": "plain text"}` |

**Escape Hatch** (force raw string):
Complex templates bypass parsing:
```yaml
# Auto-parsed (simple template):
- data: ${json_var}

# NOT parsed (complex templates):
- data: "${json_var} "        # Trailing space
- data: "'${json_var}'"       # Wrapped in quotes
- data: "raw: ${json_var}"    # Has prefix
```

#### Automatic JSON Serialization for String-Typed Parameters

Objects in `str`-typed params auto-serialize to JSON strings with proper escaping. Always use object syntax—never manually construct JSON strings.

```yaml
# ✅ Object syntax - auto-serializes with proper escaping
- request_body:
    query: ${user_input}
    limit: 10
# Result: '{"query": "Hello \"world\"\\nLine 2", "limit": 10}'

# ❌ String syntax - breaks on quotes/newlines
- request_body: '{"query": "${user_input}"}'
```

Works with or without template variables. Handles nested objects and arrays.

#### Extraction vs Transformation

**First rule: check if you need to extract at all.** If passing `${node.result}` wholesale to the next node, skip extraction entirely — no intermediate step needed.

**Extraction (getting data) → Templates**
**Transformation (changing data) → code node**
**Interpretation (creative decisions) → LLM**

```
Need data at specific path? → ${node.result.data.items[0].name}
Need to compute/transform?  → code node
Need to combine/append?     → code node or templates
Need to interpret meaning?  → LLM
```

**The LLM test**: Can you write a deterministic algorithm for it?
- **YES** (fixed structure, no creative decisions) → code/shell/templates, NOT LLM
- **NO** (requires judgment: what to emphasize, summarize, what matters) → LLM

| Task | Deterministic? | Use |
|------|----------------|-----|
| "Append section X to document" | YES - fixed structure | code node |
| "Combine A and B into report" | YES - concatenation | code node |
| "Create summary of this data" | NO - deciding importance | LLM |
| "Format for human readability" | DEPENDS - see below | ? |

**"Format" is ambiguous** — ask: is the output structure fixed?
- "Add markdown headers and bullet points" → YES, deterministic → code node
- "Format as professional report" → NO, requires judgment → LLM

**Concrete examples:**

**❌ WRONG — Using LLM for structured extraction:**
```markdown
### extract-price

Wrong approach — LLM for deterministic JSON field extraction.

- type: llm
- prompt: "Extract the price from this JSON: ${data}"
```

**❌ WRONG — Using jq for simple path extraction:**
```markdown
### extract-price

Wrong approach — shell pipeline for a single nested field.

- type: shell
- stdin: ${data}
- command: jq -r '.items[0].pricing.amount'
```

**✅ RIGHT — Using template variables:**
```yaml
# Direct path, no intermediate node needed:
- amount: ${data.items[0].pricing.amount}
```

**✅ RIGHT — Code node for computation (not extraction):**
````markdown
### calculate-total

Compute sum of all pricing amounts.

- type: code
- inputs:
    items: ${data.items}

```python code
items: list

result: float = sum(i['pricing']['amount'] for i in items)
```
````

**Before adding processing steps:** Can the source produce cleaner output? (LLM: use `output_schema`, HTTP: check for `format=json` param.) Fix at source instead of adding nodes.

**The golden rule:** Every transformation step must solve a verified problem, not prevent a hypothetical one.

#### All Template Patterns

Templates work in any param value — inline `- key:` or code blocks:

```markdown
### example-node

Demonstrates the template forms that work in any parameter value.

- basic_input: ${username}
- basic_output: ${fetch.response}
- nested: ${fetch.data.user.email}
- first_item: ${fetch.items[0]}
- specific_field: ${fetch.items[0].name}
- combined: "User ${username} data: ${fetch.response}"
- deep: ${fetch.result.data.users[0].profile.settings.email}
```

**Structured objects** — inline nesting or code block:

```markdown
### fetch-with-auth

Authenticated POST against the API using the caller's bearer token.

- type: http
- url: ${api_url}
- method: POST
- headers:
    Authorization: Bearer ${api_token}
    Content-Type: application/json
- body:
    query: ${search_query}
    limit: ${limit}
```

**When nesting gets deep** (objects within objects), use a `yaml param_name` code block for clarity:

````markdown
### update-record

Posts a structured update with a multi-line description and nested filter shape.

- type: http
- url: ${api_url}
- method: POST

```yaml body
query: ${search_query}
description: |
  Search across all active items
  filtered by tag and source.
filters:
  status: active
  tags:
    - ${primary_tag}
    - ${secondary_tag}
  metadata:
    source: ${source_name}
    priority: high
```
````

**Guideline**: Inline `- key: value` for flat params and simple nesting. `yaml param_name` code block for deep nesting, multiline values (`|`), or batch config. Both produce identical results.

**`- inputs:` works on ANY node type** (not just code nodes). It maps named variables into the template context so other params (prompt, command, etc.) can reference them by name. This is especially useful for reusing external prompt files with different data sources:

````markdown
### review

Review each item using an external prompt that expects specific variable names.

- type: llm
- prompt: ./specialist-review.prompt.md
- inputs:
    concept_brief: ${item.concept_brief}
    creative_direction: ${item.creative_direction}
- batch:
    items: ${load-data.results}
````

The prompt file uses `${concept_brief}` and `${creative_direction}` — resolved from the `inputs` mapping, not from the shared store. In production (where upstream node names already match the prompt's variables), `inputs` is optional.

### Parameter Types - Complete Guide

### Type Vocabulary - Two Surfaces

Workflow `## Inputs` / `## Outputs` use canonical JSON-Schema-style names. Python code blocks use Python annotations. Same meaning, different spelling.

| Workflow `type:` | Python annotation | Notes |
|---|---|---|
| `string` | `str` | |
| `integer` | `int` | Rejects floats |
| `number` | `int \| float` or `float` | |
| `boolean` | `bool` | |
| `array` | `list` | |
| `object` | `dict` | Dict only, not wildcard |
| `any` | `Any` | `Any` is auto-injected in code blocks |

Code blocks follow modern Python syntax — use lowercase generics (`list[T]`, `dict[K, V]`) and pipe unions (`int | str`), not `List[T]` / `Union[A, B]`. See `pflow guide code` for the full type annotation syntax table.

```markdown
## Inputs

### text_input

Any text value. String is the most common type.

- type: string
- required: true

### count

Whole number only.

- type: integer
- required: false
- default: 10

### ratio

Numeric value — integers or floats.

- type: number
- required: false
- default: 0.5

### verbose

Enable verbose output. Boolean — true/false.

- type: boolean
- required: false
- default: false

### tags

List of tags. Array input.

- type: array
- required: false
- default: ["default-tag"]

### config

Configuration object. Must be a dict.

- type: object
- required: false
- default: {"key": "value"}

### payload

Explicit wildcard. Use when the value can be any shape, including `null`.

- type: any
- required: false

### data

Data from stdin or CLI. Receives piped input (e.g., `cat data.json | pflow ./workflow.pflow.md`).

- type: string
- required: true
- stdin: true
```

### Pattern: Multi-Stage Data Pipeline

**Use case**: Fetch → Validate → Transform → Enrich → Deliver

`````markdown
## Steps

### fetch-raw

Get raw data from API.

- type: http
- url: ${source_url}

### validate-structure

Ensure data has required fields.

- type: code
- inputs:
    data: ${fetch-raw.response}

```python code
data: dict
if 'items' not in data: raise ValueError('Missing items')
result: dict = data
```

### transform-data

Reshape API items to our internal format.

- type: code
- inputs:
    items: ${validate-structure.result.items}

```python code
items: list

result: list = [
    {'id': i['id'], 'name': i['title'], 'value': i['metrics']['current']}
    for i in items
]
```

### enrich-with-analysis

Add insights to each item using LLM batch processing.

- type: llm
- batch:
    items: ${transform-data.result}
    max_concurrent: 50
    parallel: true

```prompt
Analyze this metric and add insights:
${item}

Provide: trend, risk_level, recommendation
```

### format-for-delivery

Shapes the analysis results into a markdown report for the writer.

- type: llm
- prompt: "Format as markdown report with summary and recommendations:\n${enrich-with-analysis.results}"

### deliver

Write the final report to disk.

- type: write-file
- file_path: ${output_path}
- content: ${format-for-delivery.response}
`````

### Common Mistakes

#### Over-specifying parameters
**Impact**: Brittle workflows
**Fix**: Only set what user specified or is required
**Example**: Don't set llm `temperature` unless user mentioned it

#### Missing format step
**Impact**: Raw JSON in user-facing outputs
**Fix**: Add formatting node before delivery — but choose the right tool:
- **Fixed structure** (headers, bullets, tables with known columns) → code node
- **Requires judgment** (what to emphasize, summarize, professional tone) → LLM

### Workflow Smells (Code Smells for Workflows)

**Red flags indicating poor design:**

| Smell | Problem | Fix |
|-------|---------|-----|
| No inputs | Not reusable | Extract all values as inputs |
| No descriptions | Hard to understand | Add description prose to every node |
| 30+ nodes | Too complex | Break into sub-workflows or multiple workflows |
| Repetitive nodes | Inefficient | Use batch with inline array |
| No output formatting | Poor UX | Add format step |
| Generic names | Hard to discover | Use descriptive names (see naming convention below) |

### Workflow Naming Convention

Format: `verb-noun-qualifier`
- Examples: `fetch-api-data`, `process-csv-files`, `analyze-slack-messages`
- Max 30 chars, lowercase, hyphens only
- Specific enough to find, generic enough to reuse
