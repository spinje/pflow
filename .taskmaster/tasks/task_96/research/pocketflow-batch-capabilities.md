# PocketFlow Batch Processing Capabilities

**Purpose**: Document PocketFlow's existing batch/data parallelism primitives that Task 96 will expose in pflow's IR.

**Verified**: 2024-12-21 - All class signatures verified against `pocketflow/__init__.py`

**Key Decision**: Task 96 extends the **current DAG format** (nodes + edges) with a `batch` configuration on nodes. No new IR format or parser is required.

---

## Overview

PocketFlow provides production-ready batch processing primitives. These enable **data parallelism** - applying the same operation to multiple items, optionally in parallel.

```
DATA PARALLELISM:
items[] → [process(item1), process(item2), ...] → results[]
          └────────── SAME operation ──────────┘
```

---

## Class Hierarchy

```
BaseNode
    └── Node (with retry logic)
            ├── BatchNode (sequential batch)
            └── AsyncNode (async operations)
                    ├── AsyncBatchNode (sequential async batch)
                    └── AsyncParallelBatchNode (concurrent batch)
```

---

## BatchNode (Sequential)

**Location**: `pocketflow/__init__.py:78-80`

```python
class BatchNode(Node):
    def _exec(self, items):
        return [super(BatchNode, self)._exec(i) for i in (items or [])]
```

**Behavior**:
- `prep()` returns an iterable of items
- `_exec()` processes each item sequentially via parent's `_exec()` (which calls `exec()`)
- `post()` receives list of all results

**Use Case**: Process multiple items with retry logic, memory-efficient (one at a time)

**Example**:
```python
class SummarizeFiles(BatchNode):
    def prep(self, shared):
        return shared["files"]  # List of file paths

    def exec(self, file_path):
        content = read_file(file_path)
        return summarize(content)

    def post(self, shared, prep_res, exec_res):
        shared["summaries"] = exec_res
        return "default"
```

---

## AsyncParallelBatchNode (Concurrent)

**Location**: `pocketflow/__init__.py:169-171`

```python
class AsyncParallelBatchNode(AsyncNode, BatchNode):
    async def _exec(self, items):
        return await asyncio.gather(*(super(AsyncParallelBatchNode, self)._exec(i) for i in items))
```

**Behavior**:
- Inherits from both `AsyncNode` and `BatchNode`
- Uses `asyncio.gather()` to process ALL items concurrently
- Each item goes through `AsyncNode`'s retry logic

**Use Case**: Maximum throughput for I/O-bound operations (API calls, file I/O)

**Performance**:
- From PocketFlow cookbook: 5.4x speedup (1136s → 209s for document translation)
- Best for I/O-bound tasks (network, disk)
- Limited benefit for CPU-bound tasks (Python GIL)

**Example**:
```python
class ParallelAPIFetcher(AsyncParallelBatchNode):
    async def prep_async(self, shared):
        return shared["urls"]

    async def exec_async(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return await response.json()

    async def post_async(self, shared, prep_res, exec_res):
        shared["responses"] = exec_res
        return "default"
```

---

## AsyncBatchNode (Sequential Async)

**Location**: `pocketflow/__init__.py:164-166`

```python
class AsyncBatchNode(AsyncNode, BatchNode):
    async def _exec(self, items):
        return [await super(AsyncBatchNode, self)._exec(i) for i in items]
```

**Behavior**:
- Async but sequential (one item at a time)
- Useful when you need async I/O but can't parallelize (rate limits, dependencies)

---

## BatchFlow (Multiple Flow Runs)

**Location**: `pocketflow/__init__.py:119-124`

```python
class BatchFlow(Flow):
    def _run(self, shared):
        pr = self.prep(shared) or []
        for bp in pr:
            self._orch(shared, {**self.params, **bp})
        return self.post(shared, pr, None)
```

**Behavior**:
- `prep()` returns list of parameter dictionaries
- Runs the ENTIRE flow once per parameter dict
- Each run gets merged params: `{**self.params, **bp}`

**Use Case**: Run same workflow with different configurations

---

## AsyncParallelBatchFlow (Concurrent Flow Runs)

**Location**: `pocketflow/__init__.py:200-204`

```python
class AsyncParallelBatchFlow(AsyncFlow, BatchFlow):
    async def _run_async(self, shared):
        pr = await self.prep_async(shared) or []
        await asyncio.gather(*(self._orch_async(shared, {**self.params, **bp}) for bp in pr))
        return await self.post_async(shared, pr, None)
```

**Behavior**:
- Runs entire flow multiple times CONCURRENTLY
- Uses `asyncio.gather()` for parallelism

**Performance**:
- From PocketFlow cookbook: 8x speedup (13.76s → 1.71s for image processing)

---

## How pflow Will Use These

### Current State
- pflow nodes are synchronous
- No batch syntax in IR schema
- No way to express "process each item in this list"

### Task 96 Implementation

1. **Add `batch` config to IR schema**:
```json
{
  "id": "summarize_files",
  "type": "llm",
  "batch": {
    "items": "${fetch.files}",
    "as": "file",
    "parallel": true,
    "max_concurrent": 10
  },
  "params": {
    "prompt": "Summarize: ${file.content}"
  }
}
```

2. **Create wrapper that uses these primitives**:
```python
class AsyncBatchNodeWrapper(AsyncParallelBatchNode):
    """Wraps any pflow node for batch processing."""

    def __init__(self, inner_node, items_template, item_alias, max_concurrent):
        self.inner_node = inner_node
        self.items_template = items_template
        self.item_alias = item_alias
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def prep_async(self, shared):
        return resolve_template(self.items_template, shared)

    async def exec_async(self, item):
        async with self.semaphore:
            item_context = {self.item_alias: item}
            return await asyncio.to_thread(
                self.inner_node._run,
                {**shared, **item_context}
            )
```

3. **Use `asyncio.to_thread()` for sync nodes**:
   - pflow nodes are sync, but we can run them in thread pool
   - Each node gets its own thread, I/O parallelism achieved
   - Namespacing prevents shared store conflicts

---

## Key Considerations

### Rate Limiting
```python
self.semaphore = asyncio.Semaphore(max_concurrent)

async def exec_async(self, item):
    async with self.semaphore:  # Limits concurrent operations
        return await self.process(item)
```

### Error Handling
- `fail_fast`: Stop all on first error
- `continue`: Process all, collect errors
- PocketFlow's retry logic still applies per-item

### Memory
- Sequential batch: O(1) memory per item
- Parallel batch: O(n) memory (all items in flight)
- Consider batch size for large datasets

---

## References

- `pocketflow/__init__.py` - Source code
- `pocketflow/docs/core_abstraction/batch.md` - Batch documentation
- `pocketflow/docs/core_abstraction/parallel.md` - Parallel documentation
- `pocketflow/cookbook/pocketflow-parallel-batch/` - Working example
- `pocketflow/cookbook/pocketflow-parallel-batch-flow/` - Flow example
