# IR Format Comparison Matrix

## Real-World Example: Multi-Language Translation Pipeline

**User Request**: "Fetch article from URL, translate it into English, Spanish, and Chinese in parallel, then combine the translations into a summary"

---

## Option 1: Current DAG Format (nodes + edges)

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "fetch_article",
      "type": "http",
      "purpose": "Fetch article from URL",
      "params": {
        "url": "${workflow.url}",
        "method": "GET"
      }
    },
    {
      "id": "translate_english",
      "type": "llm",
      "purpose": "Translate to English",
      "params": {
        "prompt": "Translate the following to English:\n\n${fetch_article.response.body}",
        "model": "claude-3-5-sonnet-20241022"
      }
    },
    {
      "id": "translate_spanish",
      "type": "llm",
      "purpose": "Translate to Spanish",
      "params": {
        "prompt": "Translate the following to Spanish:\n\n${fetch_article.response.body}",
        "model": "claude-3-5-sonnet-20241022"
      }
    },
    {
      "id": "translate_chinese",
      "type": "llm",
      "purpose": "Translate to Chinese",
      "params": {
        "prompt": "Translate the following to Chinese:\n\n${fetch_article.response.body}",
        "model": "claude-3-5-sonnet-20241022"
      }
    },
    {
      "id": "combine_translations",
      "type": "llm",
      "purpose": "Summarize all translations",
      "params": {
        "prompt": "Create a summary comparing these translations:\n\nEnglish: ${translate_english.result}\nSpanish: ${translate_spanish.result}\nChinese: ${translate_chinese.result}",
        "model": "claude-3-5-sonnet-20241022"
      }
    }
  ],
  "edges": [
    {"from": "fetch_article", "to": "translate_english"},
    {"from": "fetch_article", "to": "translate_spanish"},
    {"from": "fetch_article", "to": "translate_chinese"},
    {"from": "translate_english", "to": "combine_translations"},
    {"from": "translate_spanish", "to": "combine_translations"},
    {"from": "translate_chinese", "to": "combine_translations"}
  ],
  "start_node": "fetch_article",
  "inputs": {
    "url": {"type": "string", "description": "Article URL"}
  },
  "outputs": {
    "summary": {"from": "${combine_translations.result}"}
  }
}
```

**Token Count**: ~890 tokens

**Pros**:
- ✅ Flexible for complex DAGs
- ✅ Already implemented
- ✅ Familiar to developers

**Cons**:
- ❌ Parallel execution is implicit (must infer from fan-out/fan-in pattern)
- ❌ Requires mental reconstruction of flow
- ❌ Redundant edge definitions (6 edges for simple flow)
- ❌ LLM must track node IDs separately from connections
- ❌ Easy to create invalid graphs (missing edges, dangling nodes)

---

## Option 2: Pipeline Format (RECOMMENDED)

```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "url": {"type": "string", "description": "Article URL"}
  },
  "outputs": {
    "summary": {"from": "${combine_translations.result}"}
  },
  "pipeline": [
    {
      "id": "fetch_article",
      "type": "http",
      "purpose": "Fetch article from URL",
      "params": {
        "url": "${workflow.url}",
        "method": "GET"
      }
    },
    {
      "parallel": [
        {
          "id": "translate_english",
          "type": "llm",
          "purpose": "Translate to English",
          "params": {
            "prompt": "Translate the following to English:\n\n${fetch_article.response.body}",
            "model": "claude-3-5-sonnet-20241022"
          }
        },
        {
          "id": "translate_spanish",
          "type": "llm",
          "purpose": "Translate to Spanish",
          "params": {
            "prompt": "Translate the following to Spanish:\n\n${fetch_article.response.body}",
            "model": "claude-3-5-sonnet-20241022"
          }
        },
        {
          "id": "translate_chinese",
          "type": "llm",
          "purpose": "Translate to Chinese",
          "params": {
            "prompt": "Translate the following to Chinese:\n\n${fetch_article.response.body}",
            "model": "claude-3-5-sonnet-20241022"
          }
        }
      ]
    },
    {
      "id": "combine_translations",
      "type": "llm",
      "purpose": "Summarize all translations",
      "params": {
        "prompt": "Create a summary comparing these translations:\n\nEnglish: ${translate_english.result}\nSpanish: ${translate_spanish.result}\nChinese: ${translate_chinese.result}",
        "model": "claude-3-5-sonnet-20241022"
      }
    }
  ]
}
```

**Token Count**: ~640 tokens (28% reduction)

**Pros**:
- ✅ Parallel execution is **explicit** and obvious
- ✅ Read top-to-bottom like a recipe
- ✅ No redundant edge definitions
- ✅ Matches how LLMs narrate workflows
- ✅ Harder to create invalid structures
- ✅ Self-documenting execution order
- ✅ 28% fewer tokens

**Cons**:
- ⚠️ Requires new parser (but backward compatible)
- ⚠️ Complex branching needs inline `next` field

---

## Option 3: Pipeline with Shorthand

```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "url": {"type": "string"}
  },
  "pipeline": [
    {
      "fetch_article": {
        "type": "http",
        "params": {"url": "${workflow.url}"}
      }
    },
    {
      "parallel": {
        "translate_en": {
          "type": "llm",
          "params": {"prompt": "Translate to English: ${fetch_article.response.body}"}
        },
        "translate_es": {
          "type": "llm",
          "params": {"prompt": "Translate to Spanish: ${fetch_article.response.body}"}
        },
        "translate_zh": {
          "type": "llm",
          "params": {"prompt": "Translate to Chinese: ${fetch_article.response.body}"}
        }
      }
    },
    {
      "combine": {
        "type": "llm",
        "params": {"prompt": "Summarize: ${translate_en.result}, ${translate_es.result}, ${translate_zh.result}"}
      }
    }
  ]
}
```

**Token Count**: ~485 tokens (45% reduction!)

**Pros**:
- ✅ Extremely concise
- ✅ YAML-like feel (familiar to many)
- ✅ Node ID is the key (no redundant `"id"` field)
- ✅ Even fewer tokens

**Cons**:
- ❌ Less explicit (id-as-key is less obvious)
- ❌ Can't have duplicate keys (JSON limitation)
- ❌ `purpose` field would need to be omitted or nested

---

## Option 4: Array-Based Flow Notation

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "fetch_article", "type": "http", "params": {...}},
    {"id": "translate_en", "type": "llm", "params": {...}},
    {"id": "translate_es", "type": "llm", "params": {...}},
    {"id": "translate_zh", "type": "llm", "params": {...}},
    {"id": "combine", "type": "llm", "params": {...}}
  ],
  "flow": [
    "fetch_article",
    ["translate_en", "translate_es", "translate_zh"],
    "combine"
  ]
}
```

**Token Count**: ~720 tokens

**Pros**:
- ✅ Nodes defined once with all metadata
- ✅ Flow is visual (array = parallel)
- ✅ Backward compatible (keep nodes array)
- ✅ Clear separation of definition vs execution

**Cons**:
- ⚠️ Still requires separate node definitions
- ⚠️ Less self-contained than pipeline format
- ⚠️ Branching still needs edges or inline `next`

---

## Option 5: Inline Next (for Branching)

**Example: Validation with retry loop**

```json
{
  "pipeline": [
    {
      "id": "validate_input",
      "type": "llm",
      "params": {
        "prompt": "Validate this input: ${workflow.input}"
      },
      "next": {
        "valid": "process_data",
        "invalid": "log_error",
        "retry": "validate_input"
      }
    },
    {
      "id": "process_data",
      "type": "llm",
      "params": {"prompt": "Process: ${workflow.input}"}
    },
    {
      "id": "log_error",
      "type": "write-file",
      "params": {"path": "errors.log", "content": "${validate_input.error}"}
    }
  ]
}
```

**Pros**:
- ✅ Branching co-located with node that produces actions
- ✅ Clear causality ("this node routes to these nodes")
- ✅ Supports loops (can reference earlier nodes)
- ✅ Easier to validate (check all targets exist)

**Cons**:
- ⚠️ Action strings must match node's actual behavior
- ⚠️ Complex multi-step branches need `on_action` extension

---

## Option 6: On-Action Sub-Pipelines

**Example: Complex branching with multi-step paths**

```json
{
  "pipeline": [
    {
      "id": "check_quality",
      "type": "llm",
      "params": {"prompt": "Rate quality of ${workflow.input}"},
      "on_action": {
        "excellent": [
          {"id": "publish", "type": "shell", "params": {"command": "publish.sh"}},
          {"id": "notify_success", "type": "http", "params": {"url": "..."}}
        ],
        "needs_work": [
          {"id": "analyze_issues", "type": "llm", "params": {"prompt": "..."}},
          {"id": "suggest_improvements", "type": "llm", "params": {"prompt": "..."}},
          {"id": "retry", "type": "shell", "params": {"command": "retry.sh"}}
        ],
        "rejected": [
          {"id": "log_rejection", "type": "write-file", "params": {"path": "rejected.log"}},
          {"id": "archive", "type": "shell", "params": {"command": "archive.sh"}}
        ]
      }
    }
  ]
}
```

**Pros**:
- ✅ Hierarchical structure for complex branches
- ✅ Each branch is a self-contained pipeline
- ✅ Clear scoping of conditional paths
- ✅ Can nest parallel within branches

**Cons**:
- ⚠️ More nesting (but mirrors actual complexity)
- ⚠️ Longer token count for complex workflows

---

## Scoring Matrix

| Criterion | DAG (Current) | Pipeline | Shorthand | Array Flow | Inline Next | On-Action |
|-----------|---------------|----------|-----------|------------|-------------|-----------|
| **LLM Generation** | 3/5 | 5/5 | 5/5 | 4/5 | 5/5 | 5/5 |
| **Human Readability** | 3/5 | 5/5 | 4/5 | 4/5 | 5/5 | 4/5 |
| **Token Efficiency** | 2/5 | 4/5 | 5/5 | 4/5 | 4/5 | 3/5 |
| **Explicit Parallelism** | 1/5 | 5/5 | 5/5 | 5/5 | N/A | 5/5 |
| **Explicit Branching** | 3/5 | 3/5 | 3/5 | 2/5 | 5/5 | 5/5 |
| **Error Resistance** | 3/5 | 5/5 | 4/5 | 4/5 | 5/5 | 5/5 |
| **PocketFlow Mapping** | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 4/5 |
| **Backward Compat** | 5/5 | 5/5 | 4/5 | 5/5 | 5/5 | 5/5 |
| **Validation Simplicity** | 3/5 | 5/5 | 4/5 | 4/5 | 5/5 | 4/5 |
| **Composability** | 3/5 | 5/5 | 4/5 | 4/5 | 4/5 | 5/5 |
| **TOTAL** | **31/50** | **47/50** | **43/50** | **41/50** | **43/45** | **42/45** |

**Note**: Inline Next and On-Action are not standalone formats, but extensions to Pipeline format.

---

## Recommended Hybrid Approach

**Use Pipeline as the base format**, with extensions for branching:

### For Sequential + Parallel: Use `pipeline` array

```json
{
  "pipeline": [
    {"id": "step1", "type": "...", "params": {...}},
    {"parallel": [...]},
    {"id": "step3", "type": "...", "params": {...}}
  ]
}
```

### For Simple Branching: Use inline `next`

```json
{
  "pipeline": [
    {
      "id": "validate",
      "type": "llm",
      "params": {...},
      "next": {
        "pass": "success_node",
        "fail": "error_node"
      }
    }
  ]
}
```

### For Complex Multi-Step Branches: Use `on_action`

```json
{
  "pipeline": [
    {
      "id": "check",
      "type": "llm",
      "params": {...},
      "on_action": {
        "approved": [
          {"id": "step1", "type": "...", "params": {...}},
          {"id": "step2", "type": "...", "params": {...}}
        ],
        "rejected": [...]
      }
    }
  ]
}
```

### For Legacy/Complex DAGs: Fall back to `edges`

```json
{
  "nodes": [...],
  "edges": [...]
}
```

---

## Real-World Pattern Examples

### Pattern 1: Map-Reduce

```json
{
  "pipeline": [
    {
      "id": "split_tasks",
      "type": "llm",
      "params": {"prompt": "Break down: ${workflow.input}"}
    },
    {
      "parallel": [
        {"id": "task1", "type": "llm", "params": {"prompt": "Process ${split_tasks.task1}"}},
        {"id": "task2", "type": "llm", "params": {"prompt": "Process ${split_tasks.task2}"}},
        {"id": "task3", "type": "llm", "params": {"prompt": "Process ${split_tasks.task3}"}}
      ]
    },
    {
      "id": "merge_results",
      "type": "llm",
      "params": {"prompt": "Combine: ${task1.result}, ${task2.result}, ${task3.result}"}
    }
  ]
}
```

### Pattern 2: Agentic Loop

```json
{
  "pipeline": [
    {
      "id": "decide_action",
      "type": "llm",
      "params": {"prompt": "What should I do next?"},
      "next": {
        "search": "search_web",
        "answer": "generate_answer"
      }
    },
    {
      "id": "search_web",
      "type": "http",
      "params": {"url": "https://search.api"},
      "next": {"default": "decide_action"}
    },
    {
      "id": "generate_answer",
      "type": "llm",
      "params": {"prompt": "Final answer"}
    }
  ]
}
```

### Pattern 3: Error Recovery

```json
{
  "pipeline": [
    {
      "id": "api_call",
      "type": "http",
      "params": {"url": "https://api.example.com"},
      "next": {
        "success": "process_response",
        "rate_limited": "wait_and_retry",
        "error": "log_failure"
      }
    },
    {
      "id": "wait_and_retry",
      "type": "shell",
      "params": {"command": "sleep 60"},
      "next": {"default": "api_call"}
    },
    {
      "id": "process_response",
      "type": "llm",
      "params": {"prompt": "Process: ${api_call.response}"}
    },
    {
      "id": "log_failure",
      "type": "write-file",
      "params": {"path": "errors.log", "content": "${api_call.error}"}
    }
  ]
}
```

### Pattern 4: Supervisor Pattern

```json
{
  "pipeline": [
    {
      "id": "generate_draft",
      "type": "llm",
      "params": {"prompt": "Write article about ${workflow.topic}"}
    },
    {
      "id": "review_quality",
      "type": "llm",
      "params": {"prompt": "Review this article: ${generate_draft.result}"},
      "next": {
        "approved": "publish",
        "needs_revision": "revise_draft",
        "reject": "archive"
      }
    },
    {
      "id": "revise_draft",
      "type": "llm",
      "params": {"prompt": "Revise: ${generate_draft.result} based on: ${review_quality.feedback}"},
      "next": {"default": "review_quality"}
    },
    {
      "id": "publish",
      "type": "write-file",
      "params": {"path": "article.md", "content": "${generate_draft.result}"}
    },
    {
      "id": "archive",
      "type": "shell",
      "params": {"command": "mv draft.md archive/"}
    }
  ]
}
```

---

## Implementation Complexity Estimate

| Format | Parser Complexity | Compiler Changes | Validation Logic | Backward Compat | Total Effort |
|--------|------------------|------------------|------------------|-----------------|--------------|
| DAG (current) | Simple | None | Moderate | N/A | N/A |
| Pipeline | Moderate | Moderate | Simple | Easy | 2-3 days |
| Shorthand | Moderate | Moderate | Simple | Easy | 2-3 days |
| Array Flow | Simple | Moderate | Moderate | Easy | 2 days |
| Inline Next | Simple | Simple | Simple | Easy | 1 day |
| On-Action | Moderate | Moderate | Moderate | Easy | 2 days |

**Recommended Implementation Order:**
1. **Inline `next`** (1 day) - Enables branching immediately
2. **Pipeline format** (2 days) - Core sequential + parallel
3. **On-Action** (1 day) - Complex multi-step branches
4. **Optional: Shorthand** (1 day) - Further optimization

**Total**: ~5 days for full pipeline format support

---

## Migration Strategy

### Phase 1: Add Support (v1.5)
- Implement pipeline parser
- Keep DAG parser for backward compat
- Auto-detect format based on presence of `pipeline` key
- Update planner to generate both formats (A/B test)

### Phase 2: Promote Pipeline (v1.6)
- Make pipeline the default in planner
- Update all docs to show pipeline format first
- Add converter tool: `pflow convert workflow.json --to-pipeline`

### Phase 3: Deprecate DAG (v2.0)
- Warn when loading DAG format
- Keep parser but recommend migration
- All new examples use pipeline format

### Phase 4: Remove DAG (v3.0+)
- Drop DAG parser (breaking change)
- Pure pipeline format

---

## Conclusion

**The pipeline format with inline branching (`next` and `on_action`) is the optimal solution for pflow because it:**

1. **Matches how LLMs think** - Sequential narrative with parallel and branching as modifiers
2. **Is most readable** - Top-to-bottom execution order
3. **Reduces tokens** - 25-45% fewer tokens than DAG
4. **Prevents errors** - Structure implies correctness
5. **Maps to PocketFlow** - Clean 1:1 mapping to `>>`, `-`, and async patterns
6. **Is backward compatible** - Can coexist with current DAG format
7. **Supports all patterns** - Sequential, parallel, branching, loops, composition

**Implement this in pflow v2.0 as the primary IR format.**
