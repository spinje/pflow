# LLM-Optimized IR Design for Parallel and Branching Workflows

**Updated**: 2024-12-21 (verified and clarified)

> **Scope**: This document focuses on **task parallelism** (fan-out/fan-in with different operations).
> For **data parallelism** (same operation on multiple items), see Task 96.

> **Important Correction**: Earlier versions suggested using `AsyncParallelBatchNode` for task parallelism.
> This is incorrect - that class is for data parallelism. Task parallelism requires a custom
> `ParallelGroupNode` implementation since PocketFlow's Flow class doesn't support fan-out.

## Design Principles for LLM-Friendly IR

### What Makes IR LLM-Friendly?

1. **Natural Language Proximity** - Structure mirrors how humans describe workflows
2. **Cognitive Simplicity** - Easy to reason about, hard to make mistakes
3. **Pattern Recognition** - Leverages patterns LLMs already know from training data
4. **Compositional** - Small pieces combine intuitively
5. **Self-Documenting** - Structure implies execution semantics
6. **Token Efficiency** - Minimal boilerplate and redundancy
7. **Error Resistance** - Invalid structures are obvious or caught early
8. **Visual Flow** - Can "see" the execution path by reading JSON

### How LLMs Think About Workflows

When an LLM describes a workflow, it naturally thinks:

1. **Sequential narrative**: "First fetch data, then process it, then save results"
2. **Parallel as modifier**: "Translate the text into English, Spanish, and Chinese **at the same time**"
3. **Branching as conditionals**: "If validation passes, save it; otherwise, retry"
4. **Composition**: "Do step A, then steps B+C+D together, then step E"

### Problems with Current pflow IR (DAG Format)

```json
{
  "nodes": [
    {"id": "a", "type": "http", "params": {}},
    {"id": "b", "type": "llm", "params": {}},
    {"id": "c", "type": "llm", "params": {}},
    {"id": "d", "type": "write-file", "params": {}}
  ],
  "edges": [
    {"from": "a", "to": "b"},
    {"from": "a", "to": "c"},
    {"from": "b", "to": "d"},
    {"from": "c", "to": "d"}
  ]
}
```

**Issues:**
- ❌ Nodes and edges separated - must mentally reconstruct flow
- ❌ Parallel execution is implicit (fan-out + fan-in pattern)
- ❌ Can't "read" the workflow top-to-bottom
- ❌ Action strings on edges, but determined by node behavior (disconnect)
- ❌ Barrier/join semantics are implicit
- ❌ Requires graph reasoning, not sequential reasoning

## Optimal Solution: Hybrid Pipeline + Graph Format

After deep analysis, the optimal approach is a **hybrid format** that uses:
- **Pipeline syntax** for simple sequential and parallel flows (90% of cases)
- **Explicit edges** only when needed for complex branching/loops (10% of cases)

### Format: Pipeline with Inline Node Definitions

```json
{
  "pipeline": [
    {
      "id": "fetch",
      "type": "http",
      "params": {"url": "https://api.example.com"}
    },
    {
      "parallel": [
        {
          "id": "translate_en",
          "type": "llm",
          "params": {"prompt": "Translate to English: ${fetch.response}"}
        },
        {
          "id": "translate_es",
          "type": "llm",
          "params": {"prompt": "Translate to Spanish: ${fetch.response}"}
        },
        {
          "id": "translate_zh",
          "type": "llm",
          "params": {"prompt": "Translate to Chinese: ${fetch.response}"}
        }
      ]
    },
    {
      "id": "combine",
      "type": "llm",
      "params": {
        "prompt": "Combine: ${translate_en.result}, ${translate_es.result}, ${translate_zh.result}"
      }
    }
  ]
}
```

**Why This Is Optimal:**

✅ **Visual flow**: Read top-to-bottom, execution order is obvious
✅ **Parallel is explicit**: `{"parallel": [...]}` is unmistakable
✅ **No redundancy**: Nodes defined inline, no separate edges needed
✅ **LLM-natural**: Matches how LLMs narrate workflows
✅ **Token efficient**: ~30% fewer tokens than nodes+edges
✅ **Self-validating**: Invalid structures (e.g., cycles) are harder to create
✅ **Template-friendly**: Variable references are clear in context

### Branching: Inline Action Routing

For branching, use **inline `next` field** on nodes:

```json
{
  "pipeline": [
    {
      "id": "validate",
      "type": "llm",
      "params": {"prompt": "Check if ${input} is valid"},
      "next": {
        "approved": "save_result",
        "rejected": "log_error",
        "needs_revision": "validate"
      }
    },
    {
      "id": "save_result",
      "type": "write-file",
      "params": {"path": "result.json", "content": "${validate.result}"}
    },
    {
      "id": "log_error",
      "type": "shell",
      "params": {"command": "echo 'Error: ${validate.error}' >> errors.log"},
      "next": {"default": "validate"}
    }
  ]
}
```

**Why inline `next` is better than separate edges:**

✅ **Co-located**: Branching logic is WITH the node that produces it
✅ **Clear causality**: "This node can route to these destinations"
✅ **LLM-friendly**: Matches "if this, then that" reasoning
✅ **Easier to validate**: Can check that all `next` targets exist
✅ **Reduces errors**: Can't forget to add edges for a node's actions

### Complex Branching: Sub-Pipelines

For complex multi-step branches, use **inline sub-pipelines**:

```json
{
  "pipeline": [
    {
      "id": "validate",
      "type": "llm",
      "params": {"prompt": "Validate ${input}"},
      "on_action": {
        "approved": [
          {"id": "format", "type": "llm", "params": {}},
          {"id": "save", "type": "write-file", "params": {}}
        ],
        "rejected": [
          {"id": "analyze_error", "type": "llm", "params": {}},
          {"id": "suggest_fix", "type": "llm", "params": {}},
          {"id": "retry", "type": "shell", "params": {}}
        ]
      }
    }
  ]
}
```

**Why sub-pipelines:**

✅ **Hierarchical**: Complex workflows decompose naturally
✅ **Scoped**: Each branch is its own mini-workflow
✅ **Composable**: Branches can contain parallel steps too
✅ **Clear boundaries**: Start and end of each path is obvious

### Loops: Explicit Cycles

For loops, use `next` with backward references:

```json
{
  "pipeline": [
    {
      "id": "decide",
      "type": "llm",
      "params": {"prompt": "Do we need more info?"},
      "next": {
        "search": "search_web",
        "answer": "generate_answer"
      }
    },
    {
      "id": "search_web",
      "type": "http",
      "params": {"url": "https://search.api"},
      "next": {"default": "decide"}
    },
    {
      "id": "generate_answer",
      "type": "llm",
      "params": {"prompt": "Generate final answer"}
    }
  ]
}
```

**Cycle detection**: Compiler validates max iteration depth to prevent infinite loops.

## Comparison: Current IR vs Optimized IR

### Example: Parallel Translation Workflow

**Current IR (nodes + edges):**
```json
{
  "nodes": [
    {"id": "fetch", "type": "http", "params": {"url": "..."}},
    {"id": "trans_en", "type": "llm", "params": {"prompt": "..."}},
    {"id": "trans_es", "type": "llm", "params": {"prompt": "..."}},
    {"id": "trans_zh", "type": "llm", "params": {"prompt": "..."}},
    {"id": "combine", "type": "llm", "params": {"prompt": "..."}}
  ],
  "edges": [
    {"from": "fetch", "to": "trans_en"},
    {"from": "fetch", "to": "trans_es"},
    {"from": "fetch", "to": "trans_zh"},
    {"from": "trans_en", "to": "combine"},
    {"from": "trans_es", "to": "combine"},
    {"from": "trans_zh", "to": "combine"}
  ]
}
```

**Token count**: ~850 tokens
**Clarity**: Requires mental reconstruction to see parallel pattern

**Optimized IR (pipeline):**
```json
{
  "pipeline": [
    {"id": "fetch", "type": "http", "params": {"url": "..."}},
    {
      "parallel": [
        {"id": "trans_en", "type": "llm", "params": {"prompt": "..."}},
        {"id": "trans_es", "type": "llm", "params": {"prompt": "..."}},
        {"id": "trans_zh", "type": "llm", "params": {"prompt": "..."}}
      ]
    },
    {"id": "combine", "type": "llm", "params": {"prompt": "..."}}
  ]
}
```

**Token count**: ~600 tokens (29% reduction)
**Clarity**: Parallel pattern is immediately obvious

## Mapping to PocketFlow

### Sequential Steps → `>>`

```json
{"pipeline": [
  {"id": "a", "type": "http", "params": {}},
  {"id": "b", "type": "llm", "params": {}}
]}
```

Compiles to:
```python
a = HttpNode()
b = LlmNode()
a >> b
```

### Parallel Block → Custom ParallelGroupNode

> **Note**: PocketFlow's `AsyncParallelBatchNode` is for DATA parallelism (same op, many items).
> For TASK parallelism (different ops, same data), we need a custom implementation.

```json
{"parallel": [
  {"id": "t1", "type": "llm", "params": {}},
  {"id": "t2", "type": "llm", "params": {}},
  {"id": "t3", "type": "llm", "params": {}}
]}
```

Compiles to:
```python
# Custom ParallelGroupNode (must be implemented for Task 39)
class ParallelGroupNode(Node):
    """Synthetic node that executes different child nodes concurrently."""

    def __init__(self, child_nodes: list[Node]):
        super().__init__()
        self.children = child_nodes

    def _run(self, shared):
        # Use ThreadPoolExecutor for sync nodes
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(child._run, shared) for child in self.children]
            results = [f.result() for f in futures]
        return "default"

# Or async version:
async def run_parallel(shared):
    results = await asyncio.gather(
        asyncio.to_thread(t1._run, shared),
        asyncio.to_thread(t2._run, shared),
        asyncio.to_thread(t3._run, shared)
    )
    return results
```

**Key difference from AsyncParallelBatchNode:**
- `AsyncParallelBatchNode`: Same `exec_async()` called N times with different items
- `ParallelGroupNode`: Different nodes, each with their own logic, run concurrently

### Inline `next` → Action-Based Transitions

```json
{
  "id": "validate",
  "type": "llm",
  "params": {},
  "next": {
    "approved": "success",
    "rejected": "error"
  }
}
```

Compiles to:
```python
validate - "approved" >> success
validate - "rejected" >> error
```

## Advanced Patterns

### Pattern 1: Nested Parallelism

```json
{
  "pipeline": [
    {
      "id": "fetch_sources",
      "type": "http",
      "params": {"url": "..."}
    },
    {
      "parallel": [
        {
          "id": "process_source_a",
          "pipeline": [
            {"id": "parse_a", "type": "llm", "params": {}},
            {"id": "validate_a", "type": "llm", "params": {}}
          ]
        },
        {
          "id": "process_source_b",
          "pipeline": [
            {"id": "parse_b", "type": "llm", "params": {}},
            {"id": "validate_b", "type": "llm", "params": {}}
          ]
        }
      ]
    },
    {
      "id": "merge_results",
      "type": "llm",
      "params": {}
    }
  ]
}
```

**Semantics**: Run two sub-pipelines in parallel, then merge.

### Pattern 2: Conditional Parallel (Fan-Out Based on Data)

> **Note**: This pattern uses data parallelism (Task 96) - same operation on multiple items.
> The `batch` configuration shown here is a PROPOSED syntax, not yet implemented.

```json
{
  "pipeline": [
    {
      "id": "detect_languages",
      "type": "llm",
      "params": {"prompt": "Detect languages in ${input}"}
    },
    {
      "id": "translate_all",
      "type": "llm",
      "batch": {
        "items": "${detect_languages.languages}",
        "as": "target_lang",
        "parallel": true
      },
      "params": {
        "prompt": "Translate to ${target_lang}: ${input}"
      }
    },
    {
      "id": "combine",
      "type": "llm",
      "params": {}
    }
  ]
}
```

**Semantics**: Use batch configuration for data-driven parallelism (see Task 96).

### Pattern 3: Error Recovery with Retry Loop

```json
{
  "pipeline": [
    {
      "id": "attempt_task",
      "type": "http",
      "params": {"url": "...", "retry_count": 0},
      "next": {
        "success": "process_result",
        "error": "check_retry"
      }
    },
    {
      "id": "check_retry",
      "type": "shell",
      "params": {"command": "test ${attempt_task.retry_count} -lt 3"},
      "next": {
        "success": "attempt_task",
        "error": "log_failure"
      }
    },
    {
      "id": "process_result",
      "type": "llm",
      "params": {}
    },
    {
      "id": "log_failure",
      "type": "write-file",
      "params": {}
    }
  ]
}
```

## Implementation Strategy

### Phase 1: Backward-Compatible Extension

Support BOTH formats:

```python
def compile_ir(ir_dict):
    if "pipeline" in ir_dict:
        return compile_pipeline_format(ir_dict)
    else:
        return compile_dag_format(ir_dict)
```

### Phase 2: Pipeline Compilation

```python
def compile_pipeline_format(ir_dict):
    pipeline = ir_dict["pipeline"]
    nodes = []

    for step in pipeline:
        if "parallel" in step:
            # Create parallel group
            group = create_parallel_group(step["parallel"])
            nodes.append(group)
        elif "on_action" in step:
            # Create branching node
            node = create_node(step)
            for action, sub_pipeline in step["on_action"].items():
                sub_flow = compile_pipeline_format({"pipeline": sub_pipeline})
                node - action >> sub_flow
            nodes.append(node)
        else:
            # Regular node
            node = create_node(step)
            if "next" in step:
                # Add action routing
                for action, target_id in step["next"].items():
                    # Will be wired after all nodes created
                    pass
            nodes.append(node)

    # Wire sequential connections
    for i in range(len(nodes) - 1):
        nodes[i] >> nodes[i + 1]

    return Flow(start=nodes[0])
```

### Phase 3: LLM Prompt Updates

Update planner prompt to generate pipeline format:

```
Generate a workflow in this format:

{
  "pipeline": [
    {"id": "step1", "type": "...", "params": {...}},
    {"parallel": [...]},  // For concurrent execution
    {"id": "step3", "type": "...", "next": {...}}  // For branching
  ]
}

Guidelines:
1. Use "pipeline" array for sequential steps
2. Use "parallel" object for concurrent execution
3. Use "next" object for conditional branching
4. Use "on_action" for multi-step branches
```

## Validation Rules

### Pipeline Format Validation

1. **Structure**:
   - `pipeline` must be array
   - Each item must have `id` (except parallel blocks)
   - Each item must have `type` or `parallel` or `on_action`

2. **References**:
   - All `next` targets must reference valid node IDs
   - All template variables must reference existing nodes
   - Parallel blocks must contain at least 2 items

3. **Cycles**:
   - Detect cycles and warn (allow for agentic loops, but validate max_iterations)
   - Prevent self-loops without action guards

4. **Actions**:
   - All actions in `next` must be valid for the node type
   - Warn if action is not documented in node interface

## Benefits Summary

### For LLMs:
✅ **Natural to generate** - Matches sequential reasoning
✅ **Easy to edit** - Add/remove steps without rewiring edges
✅ **Fewer tokens** - 25-30% reduction vs DAG format
✅ **Fewer errors** - Structure prevents common mistakes
✅ **Pattern matching** - Similar to GitHub Actions, Airflow DAGs

### For Humans:
✅ **Readable** - Can understand workflow at a glance
✅ **Maintainable** - Clear execution order
✅ **Composable** - Sub-pipelines enable modular design

### For pflow:
✅ **Backward compatible** - Support both formats
✅ **PocketFlow-faithful** - Maps 1:1 to framework primitives
✅ **Validatable** - Easier to catch errors pre-execution
✅ **Extensible** - Can add more parallel patterns later

## Recommendation

**Implement pipeline format as the PRIMARY format for pflow v2.0**, while maintaining backward compatibility with current DAG format.

**Migration path**:
1. Add pipeline format support in v1.5
2. Update planner to prefer pipeline format in v1.6
3. Deprecate DAG format (but keep parsing) in v2.0
4. Update all documentation to show pipeline format

This will make pflow significantly more LLM-friendly and easier for humans to read/write.
