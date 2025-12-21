# Task 96: Support Batch Processing in Workflows

## ID
96

## Title
Support Batch Processing in Workflows (Data Parallelism)

## Description
Expose PocketFlow's existing `BatchNode` and `AsyncParallelBatchNode` capabilities in pflow's IR schema, enabling workflows to process multiple items with the same operation concurrently. This is "data parallelism" - applying the same transformation to many items in parallel.

**Key Decision**: This task extends the **current DAG format** (nodes + edges). No new IR format or parser is required.

## Status
not started

## Dependencies
- None (uses existing PocketFlow infrastructure)

## Priority
high

## Details

### The Opportunity

PocketFlow already has production-ready batch processing primitives that we haven't exposed:

```python
# Already exists in pocketflow/__init__.py
class BatchNode(Node):
    """Processes items sequentially"""
    def _exec(self, items):
        return [super()._exec(i) for i in items]

class AsyncParallelBatchNode(AsyncNode, BatchNode):
    """Processes items concurrently via asyncio.gather()"""
    async def _exec(self, items):
        return await asyncio.gather(*(super()._exec(i) for i in items))
```

These provide **10-100x speedups** for bulk operations with minimal implementation effort.

### Use Cases

1. **Bulk file processing**: Read/analyze 100 files in parallel
2. **Batch LLM calls**: Summarize 50 documents concurrently
3. **API batching**: Fetch data from 20 endpoints simultaneously
4. **Translation**: Translate document into 10 languages at once

### Performance Impact

```
Sequential (current):  100 LLM calls × 2s = 200 seconds
Parallel (with batch): 100 LLM calls ÷ 10 concurrent = ~20 seconds
                       ─────────────────────────────────────────
                       10x speedup (limited by rate limits)
```

---

## IR Syntax (Extending Current DAG Format)

Add a `batch` configuration property to any node:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "list_files",
      "type": "shell",
      "params": {"command": "ls *.txt"}
    },
    {
      "id": "summarize_files",
      "type": "llm",
      "batch": {
        "items": "${list_files.files}",
        "as": "file",
        "parallel": true,
        "max_concurrent": 10
      },
      "params": {
        "prompt": "Summarize this file: ${file}"
      }
    },
    {
      "id": "combine",
      "type": "llm",
      "params": {
        "prompt": "Merge these summaries into a report: ${summarize_files.results}"
      }
    }
  ],
  "edges": [
    {"from": "list_files", "to": "summarize_files"},
    {"from": "summarize_files", "to": "combine"}
  ]
}
```

### Batch Configuration Schema

```json
{
  "batch": {
    "items": "${node_id.array_field}",  // Required: template to array of items
    "as": "item",                        // Optional: variable name (default: "item")
    "parallel": true,                    // Optional: concurrent execution (default: false)
    "max_concurrent": 10,                // Optional: rate limit (default: 10)
    "error_handling": "fail_fast"        // Optional: "fail_fast" or "continue" (default: "fail_fast")
  }
}
```

### How It Works

1. **Before execution**: Resolve `items` template to get array (e.g., `["file1.txt", "file2.txt", "file3.txt"]`)
2. **During execution**: Run the node once per item, with `${file}` bound to current item
3. **After execution**: Collect all results into `${node_id.results}` array

---

## Output Structure

When a batch node processes N items, outputs are structured as:

```python
shared["summarize_files"] = {
    "results": [                    # Array of results (same order as input items)
        "Summary of file1...",
        "Summary of file2...",
        "Summary of file3..."
    ],
    "count": 3,                     # Total items processed
    "success_count": 3,             # Successful
    "error_count": 0                # Failed (if error_handling="continue")
}
```

### Accessing Results

```json
// In subsequent node params:
"${summarize_files.results}"        // Entire array
"${summarize_files.results[0]}"     // First result
"${summarize_files.count}"          // Number of items
```

### Error Handling

With `"error_handling": "continue"`:

```python
shared["summarize_files"] = {
    "results": [
        "Summary of file1...",
        null,                       # Failed item (or error object)
        "Summary of file3..."
    ],
    "errors": [
        {"index": 1, "item": "file2.txt", "error": "File not found"}
    ],
    "count": 3,
    "success_count": 2,
    "error_count": 1
}
```

---

## Technical Approach

### Phase 1: Sequential Batch (Foundation)

1. Add `batch` configuration to IR schema
2. Create `BatchNodeWrapper` that wraps any node for batch processing
3. Compiler detects batch config and applies wrapper
4. Execute items sequentially (safe, correct baseline)

### Phase 2: Parallel Batch (Performance)

1. Create `AsyncBatchNodeWrapper` using `asyncio.gather()`
2. Wrap sync nodes with `asyncio.to_thread()` for async compatibility
3. Add `max_concurrent` rate limiting via `asyncio.Semaphore`
4. Handle errors per-item (continue vs fail-fast modes)

---

## Implementation Details

### BatchNodeWrapper (Phase 1)

```python
class BatchNodeWrapper(Node):
    """Wraps any node to process multiple items sequentially."""

    def __init__(self, inner_node: Node, node_id: str, items_template: str, item_alias: str):
        super().__init__()
        self.inner_node = inner_node
        self.node_id = node_id
        self.items_template = items_template
        self.item_alias = item_alias

    def prep(self, shared):
        # Resolve items from shared store
        items = resolve_template(self.items_template, shared)
        if not isinstance(items, list):
            raise ValueError(f"Batch items must be array, got {type(items)}")
        return items

    def exec(self, items):
        results = []
        for item in items:
            # Create context with current item bound to alias
            # The inner node's template resolution will pick this up
            result = self._run_single_item(item)
            results.append(result)
        return results

    def _run_single_item(self, item):
        # Temporarily bind item to alias for template resolution
        # Implementation depends on how we integrate with TemplateAwareNodeWrapper
        pass

    def post(self, shared, prep_res, exec_res):
        shared[self.node_id] = {
            "results": exec_res,
            "count": len(exec_res),
            "success_count": len([r for r in exec_res if r is not None]),
            "error_count": len([r for r in exec_res if r is None])
        }
        return "default"
```

### AsyncBatchNodeWrapper (Phase 2)

```python
class AsyncBatchNodeWrapper(AsyncNode):
    """Wraps any node for concurrent batch processing."""

    def __init__(self, inner_node: Node, node_id: str, items_template: str,
                 item_alias: str, max_concurrent: int = 10):
        super().__init__()
        self.inner_node = inner_node
        self.node_id = node_id
        self.items_template = items_template
        self.item_alias = item_alias
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def prep_async(self, shared):
        items = resolve_template(self.items_template, shared)
        if not isinstance(items, list):
            raise ValueError(f"Batch items must be array, got {type(items)}")
        return items

    async def exec_async(self, items):
        async def process_item(item):
            async with self.semaphore:
                # Run sync node in thread pool
                return await asyncio.to_thread(self._run_single_item, item)

        return await asyncio.gather(*[process_item(i) for i in items],
                                     return_exceptions=True)

    async def post_async(self, shared, prep_res, exec_res):
        # Separate successes from exceptions
        results = []
        errors = []
        for i, result in enumerate(exec_res):
            if isinstance(result, Exception):
                results.append(None)
                errors.append({"index": i, "error": str(result)})
            else:
                results.append(result)

        shared[self.node_id] = {
            "results": results,
            "errors": errors if errors else None,
            "count": len(results),
            "success_count": len(results) - len(errors),
            "error_count": len(errors)
        }
        return "default"
```

---

## IR Schema Changes

Add to `ir_schema.py`:

```python
BATCH_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "string",
            "description": "Template reference to array of items to process",
            "pattern": r"^\$\{.+\}$"  # Must be a template
        },
        "as": {
            "type": "string",
            "description": "Variable name for current item in templates",
            "default": "item",
            "pattern": r"^[a-zA-Z_][a-zA-Z0-9_]*$"  # Valid identifier
        },
        "parallel": {
            "type": "boolean",
            "description": "Whether to process items concurrently",
            "default": False
        },
        "max_concurrent": {
            "type": "integer",
            "description": "Maximum concurrent operations (when parallel=true)",
            "default": 10,
            "minimum": 1,
            "maximum": 100
        },
        "error_handling": {
            "type": "string",
            "enum": ["fail_fast", "continue"],
            "description": "How to handle per-item errors",
            "default": "fail_fast"
        }
    },
    "required": ["items"]
}

# Add to NODE_SCHEMA properties:
"batch": BATCH_CONFIG_SCHEMA
```

---

## Compiler Changes

In `_create_single_node()`:

```python
def _create_single_node(...):
    # ... existing node creation ...

    # Check for batch configuration (BEFORE other wrappers)
    batch_config = node_ir.get("batch")
    if batch_config:
        items_template = batch_config["items"]
        item_alias = batch_config.get("as", "item")
        parallel = batch_config.get("parallel", False)
        max_concurrent = batch_config.get("max_concurrent", 10)
        error_handling = batch_config.get("error_handling", "fail_fast")

        if parallel:
            node_instance = AsyncBatchNodeWrapper(
                node_instance, node_id, items_template, item_alias, max_concurrent
            )
        else:
            node_instance = BatchNodeWrapper(
                node_instance, node_id, items_template, item_alias
            )

    # ... continue with existing wrapper chain (Template, Namespace, Instrumented) ...
```

### Wrapper Chain Order

```
ActualNode
    ↓
BatchNodeWrapper (NEW - if batch config present)
    ↓
TemplateAwareNodeWrapper (handles ${item.x} resolution)
    ↓
NamespacedNodeWrapper
    ↓
InstrumentedNodeWrapper
```

**Key insight**: The batch wrapper runs the inner node multiple times. Each run goes through the full wrapper chain, so template resolution (including `${item}`) works naturally.

---

## Template Resolution for Batch Items

The `${item}` (or custom alias) variable needs to be available during template resolution. Two approaches:

### Approach A: Inject into shared store temporarily

```python
def _run_single_item(self, item, shared):
    # Temporarily inject item into shared for template resolution
    shared[self.item_alias] = item
    try:
        result = self.inner_node._run(shared)
    finally:
        del shared[self.item_alias]
    return result
```

### Approach B: Pass as initial_params

```python
def _run_single_item(self, item, shared):
    # Create per-item context
    item_params = {self.item_alias: item}
    # TemplateAwareNodeWrapper uses initial_params for resolution
    self.inner_node.set_item_context(item_params)
    return self.inner_node._run(shared)
```

**Recommendation**: Approach A is simpler and works with existing code.

---

## Planner Integration

Update workflow generator prompt to recognize batch patterns:

```
When the user wants to process multiple items with the same operation:
- Add a "batch" configuration to the node
- Set "items" to a template referencing an array (e.g., "${list_files.files}")
- Set "as" to name the current item variable (e.g., "file")
- Set "parallel": true for concurrent processing
- Use ${<alias>} or ${<alias>.property} in params to access current item
- Results are available as ${node_id.results} (array)

Example request: "Summarize all files in the folder"

Example workflow:
{
  "nodes": [
    {"id": "list_files", "type": "shell", "params": {"command": "ls *.txt"}},
    {
      "id": "summarize",
      "type": "llm",
      "batch": {
        "items": "${list_files.files}",
        "as": "file",
        "parallel": true
      },
      "params": {"prompt": "Summarize: ${file}"}
    },
    {"id": "combine", "type": "llm", "params": {"prompt": "Combine: ${summarize.results}"}}
  ],
  "edges": [
    {"from": "list_files", "to": "summarize"},
    {"from": "summarize", "to": "combine"}
  ]
}
```

---

## Success Criteria

1. ✅ `batch` configuration added to IR schema
2. ✅ Sequential batch execution works correctly
3. ✅ Parallel batch execution provides measurable speedup
4. ✅ Rate limiting (`max_concurrent`) prevents API throttling
5. ✅ Per-item errors handled gracefully (`fail_fast` vs `continue`)
6. ✅ Template resolution works with item alias (`${file}`, `${item.name}`)
7. ✅ Results accessible as `${node_id.results}` array
8. ✅ Planner generates batch patterns for bulk operations

---

## Test Strategy

### Unit Tests
- BatchNodeWrapper processes items sequentially
- AsyncBatchNodeWrapper processes items concurrently
- Template resolution works with item alias
- Rate limiting respects max_concurrent
- Error handling modes work correctly (fail_fast, continue)
- Output structure is correct (results, count, errors)

### Integration Tests
- End-to-end batch workflow with real nodes
- Batch with LLM nodes (mock API)
- Batch with file operations
- Template resolution in nested object paths (`${item.data.name}`)
- Subsequent node accesses `${batch_node.results}`

### Performance Tests
- Measure speedup: sequential vs parallel
- Verify max_concurrent is respected (timing analysis)
- Memory usage with large batches

### Planner Tests
- LLM generates batch patterns for bulk operation requests
- Correct items/as/parallel configuration
- Valid template references

---

## Limitations

- `max_concurrent` should respect external API rate limits (user responsibility)
- Large batches may consume significant memory (all results held until completion)
- With `error_handling: continue`, caller must check for nulls in results
- Nested batch (batch within batch) is complex - defer to future enhancement

---

## Relationship to Task 39

**Task 96 (this task)**: Data parallelism - same operation on multiple items
- Extends current DAG format with `batch` config
- Uses PocketFlow's existing BatchNode/AsyncParallelBatchNode
- No new IR format needed

**Task 39**: Task parallelism - different operations running concurrently
- May extend DAG format with `parallel_group` OR introduce pipeline format
- Decision deferred until Task 39 implementation
- Requires custom ParallelGroupNode (PocketFlow doesn't support fan-out)

Both are complementary and can be composed:
```json
{
  "id": "analyze_all",
  "type": "llm",
  "batch": {"items": "${files}", "parallel": true},  // Task 96: batch each file
  "params": {...}
}
// Inside a parallel group with other nodes            // Task 39: run alongside other ops
```

---

## Notes

This task leverages PocketFlow's existing parallel infrastructure rather than building custom parallelism. The `AsyncParallelBatchNode` pattern using `asyncio.gather()` is proven and production-ready.

**Key insight**: We're not implementing parallelism from scratch - we're wrapping existing nodes to use PocketFlow's batch patterns.

**Why this should be done before Task 39**:
1. Higher value (10-100x vs 2-5x speedups)
2. Lower effort (uses existing PocketFlow code, no new IR format)
3. Teaches async patterns useful for Task 39
