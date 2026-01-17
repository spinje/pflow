# Task 39: Support Task Parallelism in Workflows

## Description
Enable pflow to represent and execute workflows where multiple DIFFERENT operations run concurrently on the same data. This is "task parallelism" - running analyze AND visualize AND summarize at the same time, then combining their results.

This is distinct from Task 96 (batch/data parallelism) which runs the SAME operation on multiple items.

## Status
not started

## Dependencies
- Task 96: Support Batch Processing in Workflows (recommended to complete first - teaches async patterns, lower risk)

## Priority
medium

## Details

### The Problem

LLMs naturally generate parallel patterns when users say things like:
- "Analyze the data AND create visualizations"
- "Fetch from GitHub AND fetch from Jira, then combine"
- "Generate an outline, introduction, and conclusion for this article"

These translate to fan-out/fan-in patterns:
```
fetch → [analyze, visualize, summarize] → combine
        └─── run these concurrently ────┘
```

But PocketFlow's Flow class fundamentally doesn't support this:
```python
def next(self, node, action="default"):
    self.successors[action] = node  # Only ONE successor per action!
```

When pflow tries to wire `fetch >> analyze` and `fetch >> visualize`, the second overwrites the first. Only one path survives.

### Types of Parallelism (Clarification)

| Type | Pattern | Task | PocketFlow Support |
|------|---------|------|-------------------|
| **Data Parallelism** | Same op × N items | Task 96 | ✅ BatchNode exists |
| **Task Parallelism** | N different ops × same data | Task 39 (this) | ❌ Must build |

```
DATA PARALLELISM (Task 96):
files[] → [process(f1), process(f2), process(f3)] → results[]
          └──────── SAME operation ──────────────┘

TASK PARALLELISM (Task 39):
fetch → [analyze, visualize, summarize] → combine
        └──── DIFFERENT operations ─────┘
```

### Evidence from Task 28

Task 28's workflow generator testing revealed:
- LLMs generate parallel fan-out patterns in ~40% of complex workflows
- These patterns currently FAIL validation (multiple edges from same node)
- The LLM's instinct is correct - parallel IS more efficient
- We're fighting natural LLM behavior instead of supporting it

### Proposed IR Syntax

#### Option A: Pipeline Format (Recommended for New Workflows)

Explicit parallel blocks make intent crystal clear:

```json
{
  "ir_version": "0.2.0",
  "pipeline": [
    {
      "id": "fetch_data",
      "type": "http",
      "params": {"url": "${workflow.url}"}
    },
    {
      "parallel": [
        {
          "id": "analyze",
          "type": "llm",
          "params": {"prompt": "Analyze: ${fetch_data.response}"}
        },
        {
          "id": "visualize",
          "type": "llm",
          "params": {"prompt": "Create visualization for: ${fetch_data.response}"}
        },
        {
          "id": "summarize",
          "type": "llm",
          "params": {"prompt": "Summarize: ${fetch_data.response}"}
        }
      ]
    },
    {
      "id": "combine_results",
      "type": "llm",
      "params": {
        "prompt": "Combine these:\nAnalysis: ${analyze.result}\nVisualization: ${visualize.result}\nSummary: ${summarize.result}"
      }
    }
  ]
}
```

**Advantages:**
- Execution order is visually obvious (top to bottom)
- Parallel sections are explicit (`{"parallel": [...]}`)
- No graph analysis needed to detect patterns
- LLM-friendly format (matches natural language structure)
- Self-validating (structure implies correctness)

#### Option B: Edge-Based Detection (Backward Compatible)

Infer parallelism from existing edge format:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "fetch", "type": "http", "params": {...}},
    {"id": "analyze", "type": "llm", "params": {...}},
    {"id": "visualize", "type": "llm", "params": {...}},
    {"id": "combine", "type": "llm", "params": {...}}
  ],
  "edges": [
    {"from": "fetch", "to": "analyze"},
    {"from": "fetch", "to": "visualize"},
    {"from": "analyze", "to": "combine"},
    {"from": "visualize", "to": "combine"}
  ]
}
```

Compiler detects:
- "fetch" has 2 outgoing edges → fan-out point
- "combine" has 2 incoming edges → fan-in (join) point
- Nodes between fan-out and fan-in form a parallel group

**Advantages:**
- Works with existing IR format
- Backward compatible
- No new syntax to learn

**Disadvantages:**
- Requires graph analysis
- Implicit (harder to validate)
- Can't distinguish intentional parallelism from errors

### Recommended Approach: Support Both

```python
def compile_ir(ir_dict):
    if "pipeline" in ir_dict:
        return compile_pipeline_format(ir_dict)  # Explicit parallel blocks
    else:
        return compile_dag_format(ir_dict)  # Infer from edges
```

### Technical Implementation

#### Phase 1: Representation + Sequential Execution

**Goal**: LLM-generated parallel workflows stop failing, execute correctly (but sequentially)

1. **Add pipeline format to IR schema**
   - New `pipeline` array with ordered steps
   - `parallel` blocks containing concurrent nodes
   - Validation for parallel block structure

2. **Update compiler to handle parallel patterns**
   - Parse pipeline format OR detect fan-out in edges
   - Flatten to sequential execution order (topological sort)
   - All nodes execute, just not concurrently

3. **Update planner**
   - Remove "linear only" constraints
   - Add examples of parallel patterns
   - Let LLM generate natural parallel workflows

**Outcome**: Workflows work correctly, just not optimally fast.

#### Phase 2: Actual Concurrent Execution

**Goal**: Parallel nodes actually run concurrently for performance gains

1. **Create ParallelGroupNode**

   A synthetic node that wraps parallel children:
   ```python
   class ParallelGroupNode(Node):
       """Executes child nodes concurrently."""

       def __init__(self, child_nodes: list[Node]):
           super().__init__()
           self.children = child_nodes

       def _run(self, shared):
           # Option A: ThreadPoolExecutor for sync nodes
           with ThreadPoolExecutor() as executor:
               futures = [executor.submit(child._run, shared) for child in self.children]
               results = [f.result() for f in futures]

           # Option B: asyncio for async-compatible nodes
           # results = asyncio.run(self._run_async(shared))

           return "default"
   ```

2. **Thread safety via namespacing**

   pflow already has automatic namespacing:
   ```python
   # Node "analyze" writes to shared["analyze"]["result"]
   # Node "visualize" writes to shared["visualize"]["result"]
   ```

   Parallel nodes write to DIFFERENT namespaces, so no write conflicts!

3. **Compiler generates parallel structure**
   ```
   Before: fetch → analyze → visualize → combine
   After:  fetch → ParallelGroupNode([analyze, visualize]) → combine
   ```

### Execution Semantics

#### Parallel Block Behavior

1. All nodes in a `parallel` block start simultaneously
2. Block completes when ALL nodes finish (implicit barrier)
3. Next step waits for entire parallel block
4. Each node writes to its own namespace
5. Following nodes can read from all parallel node outputs

#### Error Handling

```json
{
  "parallel": [...],
  "on_error": "fail_fast"  // or "continue" or "rollback"
}
```

- `fail_fast`: Any failure stops all parallel nodes (default)
- `continue`: Run all nodes, collect errors at end
- `rollback`: On failure, attempt to undo completed nodes

### Relationship to Other Tasks

| Task | Type | What It Does |
|------|------|--------------|
| Task 38 | Conditional Branching | `validate → (success OR error)` - one path executes |
| Task 39 | Task Parallelism | `fetch → (analyze AND visualize)` - multiple paths execute |
| Task 96 | Data Parallelism | `files[] → process(each)` - same op on many items |

These are complementary and can be composed:
```json
{
  "pipeline": [
    {"id": "fetch", ...},
    {
      "parallel": [
        {
          "id": "analyze_all",
          "batch": {"items": "${fetch.files}", "parallel": true},  // Task 96
          ...
        },
        {"id": "generate_summary", ...}
      ]
    },
    {
      "id": "review",
      "next": {"approved": "publish", "rejected": "archive"}  // Task 38
    }
  ]
}
```

### PocketFlow Considerations

#### Why Not Use AsyncParallelBatchFlow?

The research documents suggested using PocketFlow's batch classes. However:

- `BatchNode`/`BatchFlow`: Same operation on multiple items (data parallelism)
- `AsyncParallelBatchFlow`: Same FLOW multiple times with different params

Neither supports running DIFFERENT nodes concurrently. We must build task parallelism ourselves.

#### The Parameter Passing Modification

pflow modified `Flow._orch()` to preserve compile-time parameters. Key findings:

- The modification only affects sync `Flow._orch()`, not async `_orch_async()`
- `AsyncParallelBatchFlow` uses unmodified async path
- For task parallelism, we'll likely use ThreadPoolExecutor anyway
- **Not a blocker** for this task

### Success Criteria

#### Phase 1 (Representation)
- [ ] Pipeline format added to IR schema
- [ ] Compiler parses parallel blocks
- [ ] Sequential execution works correctly
- [ ] Planner generates parallel patterns
- [ ] Existing edge-based format still works

#### Phase 2 (Execution)
- [ ] Parallel nodes execute concurrently
- [ ] Measurable speedup (2-5x for typical patterns)
- [ ] Thread safety via namespacing works
- [ ] Error handling modes implemented
- [ ] No race conditions or deadlocks

## Test Strategy

### Unit Tests
- Pipeline format parsing
- Parallel block validation
- Fan-out/fan-in detection in edges
- ParallelGroupNode execution
- Namespace isolation in parallel execution

### Integration Tests
- End-to-end parallel workflow
- Mixed sequential + parallel pipeline
- Nested parallel blocks
- Error propagation in parallel nodes
- Template resolution across parallel nodes

### Planner Tests
- LLM generates parallel patterns for appropriate requests
- Parallel workflows pass validation
- Generated workflows execute correctly

### Performance Tests
- Measure speedup: sequential vs parallel execution
- Verify concurrent execution (timing analysis)
- Thread pool overhead measurement

## Limitations

- Python GIL limits CPU-bound parallelism (I/O-bound benefits most)
- Shared store reads during parallel writes need care
- Debugging parallel execution is more complex
- Maximum useful parallelism limited by rate limits, resources

## Notes

### Key Insight

The original task description conflated data parallelism (BatchNode) with task parallelism (fan-out/fan-in). These are different problems:

- **Data parallelism** (Task 96): Leverage existing PocketFlow BatchNode
- **Task parallelism** (Task 39): Build custom parallel execution

### Research Documents

The research in `.taskmaster/tasks/task_39/research/` contains:
- ✅ Correct analysis of the fan-out/fan-in problem
- ✅ Good proposals for pipeline format
- ❌ Incorrect suggestion to use BatchFlow (that's for data parallelism)
- ❌ Overstated concerns about parameter passing (not a blocker)

### Why Pipeline Format?

The research showed pipeline format is:
- 25-45% more token-efficient than DAG format
- Matches natural language workflow descriptions
- Self-documenting (execution order is visual)
- Validated against industry standards (GitHub Actions, Airflow)

### Phased Delivery

Phase 1 delivers value quickly (LLM workflows stop failing) while Phase 2 adds performance. This reduces risk and allows learning from real usage before committing to concurrent execution strategy.
