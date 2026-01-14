# Feature Request: Dynamic Batch Indexing [IMPLEMENTED]

## Problem

When processing multiple items through parallel batch stages, there's no way to correlate results from one batch with items in a subsequent batch. The template syntax `${node.results[${item.index}]}` doesn't work because pflow doesn't resolve nested templates.

## Context: What I Was Trying to Build

A release announcement workflow that:
1. **Draft stage**: Generate 3 platform-specific drafts (Slack, Discord, X) in parallel using Gemini
2. **Critique stage**: Critique each draft in parallel using GPT
3. **Improve stage**: Improve each draft based on its critique in parallel using Claude

The key requirement: in the improve stage, each item needs to access its *corresponding* draft and critique by index.

## What I Tried (Doesn't Work)

```json
{
  "id": "draft-all",
  "type": "llm",
  "batch": {
    "items": [
      {"platform": "slack", "instructions": "..."},
      {"platform": "discord", "instructions": "..."},
      {"platform": "x", "instructions": "..."}
    ],
    "parallel": true
  },
  "params": {
    "model": "gemini-3-flash-preview",
    "prompt": "Write ${item.platform} announcement:\n${item.instructions}"
  }
},
{
  "id": "critique-all",
  "type": "llm",
  "batch": {
    "items": [
      {"platform": "slack", "index": 0},
      {"platform": "discord", "index": 1},
      {"platform": "x", "index": 2}
    ],
    "parallel": true
  },
  "params": {
    "model": "gpt-5.2",
    "prompt": "Critique this ${item.platform} draft:\n${draft-all.results[${item.index}].response}"
  }
}
```

**Error**: `Malformed template syntax` - the `${item.index}` inside array brackets isn't resolved.

## Workaround I Had to Use

Instead of 3 parallel batch nodes (9 LLM calls across 3 parallel batches), I had to create 9 sequential nodes:

```json
{"id": "draft-slack", "type": "llm", "params": {...}},
{"id": "draft-discord", "type": "llm", "params": {...}},
{"id": "draft-x", "type": "llm", "params": {...}},
{"id": "critique-slack", "type": "llm", "params": {...}},
{"id": "critique-discord", "type": "llm", "params": {...}},
{"id": "critique-x", "type": "llm", "params": {...}},
{"id": "improve-slack", "type": "llm", "params": {...}},
{"id": "improve-discord", "type": "llm", "params": {...}},
{"id": "improve-x", "type": "llm", "params": {...}}
```

This loses all parallelism benefits and makes the workflow verbose and harder to maintain.

## Proposed Solution

Support dynamic indexing in templates where `${item.field}` can be used as an array index:

```json
${draft-all.results[${item.index}].response}
```

Should resolve to `${draft-all.results[0].response}`, `${draft-all.results[1].response}`, etc. based on the current batch item's `index` field.

## Simple Example: What Should Work

```json
{
  "nodes": [
    {
      "id": "fetch-users",
      "type": "http",
      "batch": {
        "items": ["alice", "bob", "charlie"],
        "parallel": true
      },
      "params": {
        "url": "https://api.example.com/users/${item}"
      }
    },
    {
      "id": "enrich-users",
      "type": "llm",
      "batch": {
        "items": [
          {"name": "alice", "index": 0, "extra": "VIP customer"},
          {"name": "bob", "index": 1, "extra": "New signup"},
          {"name": "charlie", "index": 2, "extra": "Enterprise"}
        ],
        "parallel": true
      },
      "params": {
        "prompt": "Summarize user ${item.name}:\nData: ${fetch-users.results[${item.index}].response}\nContext: ${item.extra}"
      }
    }
  ],
  "edges": [
    {"from": "fetch-users", "to": "enrich-users"}
  ]
}
```

In `enrich-users`:
- Item 0 (`alice`) accesses `${fetch-users.results[0].response}`
- Item 1 (`bob`) accesses `${fetch-users.results[1].response}`
- Item 2 (`charlie`) accesses `${fetch-users.results[2].response}`

## Why This Matters

1. **Performance**: Multi-stage parallel pipelines are common. Without this, you lose parallelism or have to manually unroll batches into N separate nodes.

2. **Maintainability**: A 3-platform × 3-stage workflow goes from 3 batch nodes to 9 individual nodes. For 5 platforms × 4 stages, that's 4 batch nodes vs 20 individual nodes.

3. **Expressiveness**: This pattern (process items in parallel, then process results in parallel with correlation) is fundamental to data pipelines.

## Workaround: Inline Items with Static Indices

You can embed the static index directly in each batch item's template references:

```json
{
  "id": "improve-all",
  "type": "llm",
  "batch": {
    "items": [
      {"platform": "slack", "draft": "${draft-all.results[0].response}", "critique": "${critique-all.results[0].response}"},
      {"platform": "discord", "draft": "${draft-all.results[1].response}", "critique": "${critique-all.results[1].response}"},
      {"platform": "x", "draft": "${draft-all.results[2].response}", "critique": "${critique-all.results[2].response}"}
    ],
    "parallel": true
  },
  "params": {
    "prompt": "Improve ${item.platform}:\n${item.draft}\n\nCritique:\n${item.critique}"
  }
}
```

This works but is verbose and error-prone - you have to manually keep indices in sync. Dynamic indexing (`${results[${item.index}]}`) would be cleaner and less brittle.

## Implementation Notes

The template resolution would need two passes:
1. First pass: resolve `${item.field}` references to get the index value
2. Second pass: resolve the full template with the computed index

Or alternatively, detect the pattern `[${...}]` and handle it as a special case during resolution.

---

## Implementation (Completed 2026-01-14)

Two features were implemented:

### 1. Auto-injected `__index__` System Variable

During batch iteration, `__index__` (0-based) is automatically available:

```json
{
  "batch": {"items": ["alice", "bob", "charlie"]},
  "params": {"prompt": "Processing item ${__index__}: ${item}"}
}
```

### 2. Nested Template Resolution

Templates like `${results[${__index__}]}` now resolve correctly:

```json
{
  "batch": {"items": [{"label": "First"}, {"label": "Second"}]},
  "params": {
    "prompt": "${item.label}: ${previous-batch.results[${__index__}].response}"
  }
}
```

### Files Modified

- `src/pflow/runtime/batch_node.py` - Inject `__index__` at lines 388, 744
- `src/pflow/runtime/template_resolver.py` - Add `NESTED_INDEX_PATTERN` and `resolve_nested_index_templates()`
- `src/pflow/runtime/template_validator.py` - Register `__index__` as available variable

### Example Workflow

See `examples/test-nested-index.json` for a working example.
