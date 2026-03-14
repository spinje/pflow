# Braindump: Structured Output from an AI Sales OS Consumer Perspective

**Date**: 2026-03-13
**Context**: Building AI Sales OS — a 7-workflow project that heavily depends on LLM nodes returning well-structured JSON. 4 workflows built, 3 remaining. Every workflow with an LLM node would benefit from structured output.

## What We're Building

AI Sales OS is a set of pflow workflows that process sales call transcripts, generate prospect intelligence, and produce coaching outputs. Every workflow follows the same pattern: read context → LLM generates structured JSON → validate → save JSON → format HTML email → save HTML → send email.

The LLM's JSON output is the core of every workflow. Everything downstream — validation, file saving, HTML formatting, email — depends on it being correctly shaped.

## The Problems We're Hitting Today

### 1. Code fence wrapping (unpredictable)

Claude sometimes wraps JSON responses in ```json code fences. This prevents pflow's auto-parsing — the response stays as a string instead of becoming a dict.

**When it happens:** Unpredictably. The simpler extract-discovery prompt (single extraction schema) returns clean JSON every time. The more complex pitch-prep prompt (5 nested sections) triggered code fences on the first run. Same model (claude-sonnet-4-5), same temperature (0), same "Return ONLY valid JSON" instruction.

**Our workaround:** Every validate step now accepts `object` type instead of `dict` and manually strips code fences:

```python
pitch_prep: object  # Not dict — accepts both parsed and unparsed

if isinstance(pitch_prep, str):
    text = pitch_prep.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
        text = text.rsplit('```', 1)[0]
    pitch_prep = json.loads(text)
```

This is in every workflow's validate step. It's boilerplate that structured output would eliminate entirely.

### 2. Schema drift (Claude returns different shapes for the same prompt)

Even with explicit schema instructions in the prompt, Claude varies the output structure between runs:

**Run 1:** `talking_points` is a list of dicts `[{"sequence": 1, "topic": "Opening", "talking_points": [...]}]`
**Run 2:** `talking_points` is a list of strings `["Open with audit findings", "Reference their $8K/mo spend"]`

Both are valid responses to the prompt. Neither is wrong. But the HTML formatter downstream needs to handle both shapes, which leads to defensive code like:

```python
for t in talking:
    if isinstance(t, dict):
        topic = t.get('topic', t.get('sequence', ''))
        points = t.get('talking_points', t.get('points', []))
        # ... render with sub-headings
    else:
        # ... render as plain string
```

Similarly, `total_estimate` sometimes comes back as a string `"$15K-18K"` and sometimes as a dict `{"low_end": "$15K", "mid_range": "$16.5K", "high_end": "$18K"}`.

**Our workaround:** A generic `to_str()` fallback that recursively converts any nested structure to readable text:

```python
def to_str(val):
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return ', '.join(to_str(v) for v in val)
    if isinstance(val, dict):
        parts = [f'{k.replace("_", " ").title()}: {to_str(v)}' for k, v in val.items()]
        return '; '.join(parts)
    return str(val)
```

With structured output enforcing a schema, the format-email code could assume a fixed structure — no `isinstance()` checks, no fallbacks, no `to_str()`.

### 3. Prompt bloat from schema instructions

Because we can't enforce schema at the API level, we burn prompt tokens telling Claude what shape to use:

```
Keep output concise and actionable. Talking points should be plain strings
(not objects). Strategy document recommended_services should each have:
service, rationale, approach (all strings). Expected outcomes should be
plain strings. Objection handling should have: objection, response, framing
(all strings). Total estimate should be a single string.
```

This is ~60 tokens of prompt just telling Claude the shape. With structured output, this would be a JSON schema parameter on the node — zero prompt tokens, enforced by the API, not by Claude's compliance.

## Where Structured Output Would Help (By Workflow)

| Workflow | LLM Calls | Schema Complexity | Impact |
|----------|-----------|-------------------|--------|
| **score-call** | 1 | Medium (3 dimensions, nested scores/observations) | Moderate — already works well, but schema enforcement would remove the validate step |
| **extract-discovery** | 1 | Medium (10 top-level fields, some nested) | Moderate — Claude handles this consistently today |
| **pitch-prep** | 1 | High (5 sections, deeply nested strategy + recommendations) | **High** — this is where code fences and schema drift hit hardest |
| **handoff-briefs** | 2 (1 single + 1 batch) | Medium per brief, but batch means N calls | **High** — batch amplifies any inconsistency across briefs |
| **gather-intel** | 3 (chain) | Varies per chain | Moderate — Chain 1 and 2 return JSON well, Chain 3 returns markdown (not JSON) |
| **weekly-summary** | 1 | N/A (returns HTML directly) | None — no JSON schema needed |
| **coaching-nudge** | 1 | N/A (returns HTML directly) | None — no JSON schema needed |

The highest-impact workflows are **pitch-prep** and **handoff-briefs**.

## What We'd Want from Structured Output

### The minimum viable feature

A `response_schema` parameter on the `llm` node that:
1. Tells the LLM API to use structured output / JSON mode
2. Guarantees `${node.response}` is always a parsed dict (never a string, never code-fenced)
3. Validates the response matches the schema before storing in shared state

### Example of how we'd use it

Current pitch-prep workflow:
```markdown
### generate-pitch-prep

- type: llm
- model: anthropic/claude-sonnet-4-5
- temperature: 0
- system: ${read-prompts.result}
```

With structured output:
```markdown
### generate-pitch-prep

- type: llm
- model: anthropic/claude-sonnet-4-5
- temperature: 0
- system: ${read-prompts.result}
- response_format: json
- response_schema:
    pitch_day_refresher: list
    talking_points: list
    strategy_document:
        executive_summary: str
        recommended_services: list
        expected_outcomes: list
    service_recommendations:
        recommended: list
        bundling_notes: str
        margin_notes: str
        total_estimate: str
        priority_order: list
    objection_handling: list
```

### What this would eliminate from our code

1. **Every validate step's code-fence stripping** — the `isinstance(str)` + startswith('```') block
2. **Every validate step's `object` type annotation** — could go back to `dict`
3. **Schema shape instructions in prompts** — the 60-token prompt telling Claude the structure
4. **Most `isinstance()` checks in format-email** — could assume fixed structure
5. **The `to_str()` fallback** — wouldn't need a generic handler for unknown nesting

### What it would NOT eliminate

- **Validate steps themselves** — we'd still want to check that specific required fields exist and have reasonable values (e.g. budget is not empty, decision_makers is not an empty list). Schema validation checks structure, not content quality.
- **The format-email code node** — still needed to convert data to HTML. Just simpler because the input shape is guaranteed.

## API-Level Support

Both Anthropic and OpenAI support structured output / JSON mode at the API level:

**Anthropic:** The `tool_use` pattern — define a tool with a JSON schema, Claude is forced to call it with conforming arguments. Alternatively, newer models support a `response_format` parameter.

**OpenAI:** `response_format: { type: "json_schema", json_schema: { ... } }` — enforced structured output.

The pflow implementation would need to map the `response_schema` parameter to the right API mechanism depending on the provider.

## Interaction with the Auto-Parse Bug Fix

The existing braindump (`braindump-json-parse-design-audit.md`) recommends removing the LLM node's auto-parse (`parse_json_response`). Structured output is the proper replacement:

1. **Remove auto-parse** (the bug fix) — LLM responses are raw strings by default
2. **Add structured output** (Task 66) — when `response_schema` is set, responses are guaranteed parsed dicts

These can be done together or sequentially. If done sequentially: after removing auto-parse, existing workflows that rely on `${llm.response}` being a dict would break until they either add `response_schema` or add manual parsing in a downstream code node. For AI Sales OS, we already have the manual parsing workaround, so we'd just swap it for `response_schema` when available.

## One More Thing: Batch Consistency

handoff-briefs uses batch to generate one expert brief per service. Each batch item hits the LLM independently. Without structured output, each brief could have a slightly different schema — one might nest `timeline` as a dict, another as a string. The format-email code would need to handle all variants across all briefs in the same HTML.

With structured output on batch LLM nodes, every brief in the batch would conform to the same schema. The save-all code node could assume consistent structure across all `${generate-briefs.results}` items.
