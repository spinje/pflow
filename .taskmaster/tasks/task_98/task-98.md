# Task 98: Architectural Refactor - First-Class IR Execution

## ID
98

## Title
Evaluate and Design First-Class IR Execution Architecture

## Status
not started

## Priority
low (post-v1.0)

## Description

During Task 96 (Batch Processing) implementation, we discovered significant accidental complexity in pflow's wrapper-based architecture. This task captures those insights and explores a cleaner architectural approach for future versions.

**This is NOT a rewrite proposal.** It's documentation of architectural debt and exploration of alternatives.

---

## Background: How We Got Here

### PocketFlow: The Foundation

PocketFlow is a minimal (~100 lines) Python framework for workflows:

```python
class Node:
    def _run(self, shared):
        p = self.prep(shared)
        e = self._exec(p)
        return self.post(shared, p, e)

    def prep(self, shared): pass      # Prepare data
    def exec(self, prep_res): pass    # Do work
    def post(self, shared, p, e): pass # Store results
```

**Key design**: Python developers subclass `Node`, implement methods, access `shared` dict directly.

### pflow: IR Layer on Top

pflow adds an IR (Intermediate Representation) layer so users write JSON, not Python:

```json
{
  "id": "summarize",
  "type": "llm",
  "params": {"prompt": "Summarize: ${input.text}"}
}
```

**The challenge**: IR can't express Python method parameters. Users write `${var}` templates instead.

### The Wrapper Solution

To bridge IR to PocketFlow, pflow wraps nodes:

```
User IR
   ↓ compile
PocketFlow Node
   ↓ wrap
TemplateAwareNodeWrapper    → Resolves ${var} templates
   ↓ wrap
NamespacedNodeWrapper       → Prevents shared store key collisions
   ↓ wrap
InstrumentedNodeWrapper     → Adds metrics, tracing, caching
   ↓ wrap
BatchNodeWrapper            → Iterates over items (Task 96)
```

Each wrapper intercepts `_run()` and adds behavior before/after delegating to the inner node.

---

## The Problems Discovered

### 1. Wrapper Chain Order is Fragile

During Task 96, we spent significant time determining where `BatchNodeWrapper` should go:

```
Option A: Instrumented → Namespace → Batch → Template → Actual
Option B: Instrumented → Batch → Namespace → Template → Actual
```

**The debate**:
- If Batch is INSIDE Namespace, item injection goes to `shared[namespace]["item"]`
- Template resolution wouldn't see `${item}` at root level
- Requires understanding how each wrapper transforms `shared`

**This is a sign of tight coupling** - wrappers implicitly depend on each other's behavior.

### 2. Shared Store Causes Collisions

PocketFlow uses a single `shared` dict for all inter-node communication:

```python
# Node A writes
shared["output"] = "result"

# Node B also writes
shared["output"] = "different"  # Collision!
```

**pflow's solution**: `NamespacedNodeWrapper` routes writes to `shared[node_id]["key"]`.

**The problem**: This is a workaround, not a design. It adds complexity and creates edge cases (special `__keys__` bypass namespacing, proxy objects, etc.).

### 3. Template Resolution is Stringly-Typed

```python
# IR specifies
"prompt": "Hello ${user.name}"

# At runtime, TemplateAwareNodeWrapper:
# 1. Parses string to find ${...} patterns
# 2. Extracts variable paths
# 3. Resolves from shared store
# 4. String-replaces back
```

**Problems**:
- No compile-time validation of variable references
- Runtime errors if variable doesn't exist
- Type information lost (everything becomes string in interpolation)
- Complex resolution logic for paths like `${node.output[0].field}`

### 4. Batch Required Workarounds

For Task 96, we couldn't use PocketFlow's `BatchNode` because:

```python
# PocketFlow's BatchNode
class BatchNode(Node):
    def _exec(self, items):
        return [self.exec(item) for item in items]
        #            ↑ item is parameter to exec()

# But pflow nodes read from params/shared, not parameters:
class LLMNode(Node):
    def exec(self, prep_res):
        prompt = self.params["prompt"]  # Not from parameter!
```

**Our solution**: Create `BatchNodeWrapper` that:
1. Iterates outside `_run()` (not inside `_exec()`)
2. Creates isolated `dict(shared)` copies per item
3. Injects item at root level for template resolution
4. Captures results from isolated copy's namespace

**This works but is complex** - shallow copies, fresh namespaces, careful ordering.

### 5. Execution Flow is Hard to Trace

With 4 wrapper layers, tracing execution requires understanding:

```
InstrumentedNodeWrapper._run(shared)
  → metrics setup
  → BatchNodeWrapper._run(shared)
    → for item in items:
      → item_shared = dict(shared)
      → item_shared["item"] = item
      → NamespacedNodeWrapper._run(item_shared)
        → namespaced = NamespacedSharedStore(item_shared, node_id)
        → TemplateAwareNodeWrapper._run(namespaced)
          → context = dict(namespaced)  # Captures root + namespace
          → resolve templates
          → ActualNode._run(namespaced)
            → prep() → exec() → post()
```

**Cognitive load is high** for debugging and feature development.

---

## What Elegant Would Look Like

### Option A: First-Class IR Executor

Instead of wrapping PocketFlow nodes, build a dedicated IR executor:

```python
class IRExecutor:
    def execute_node(self, node_ir: dict, context: ExecutionContext):
        # 1. Resolve inputs from context
        inputs = self.resolve_inputs(node_ir["inputs"], context)

        # 2. Execute node with explicit inputs
        node_impl = self.registry.get(node_ir["type"])
        outputs = node_impl.execute(inputs)

        # 3. Store outputs in context with node_id prefix
        context.store_outputs(node_ir["id"], outputs)

        return outputs
```

**Benefits**:
- No wrappers needed
- Explicit data flow (inputs → outputs)
- Template resolution built into executor
- Batch is just a loop in the executor, not a wrapper

### Option B: Explicit Node Interfaces

Define nodes with typed inputs/outputs:

```python
@node
class SummarizeNode:
    class Inputs:
        text: str
        max_length: int = 100

    class Outputs:
        summary: str
        word_count: int

    def execute(self, inputs: Inputs) -> Outputs:
        summary = llm(f"Summarize in {inputs.max_length} words: {inputs.text}")
        return self.Outputs(summary=summary, word_count=len(summary.split()))
```

IR references these explicitly:

```json
{
  "id": "summarize",
  "type": "summarize",
  "inputs": {
    "text": "${fetch.content}",
    "max_length": 50
  }
}
```

**Benefits**:
- Type safety at compile time
- Clear data flow in IR
- No shared store collisions (each node has isolated I/O)
- IDE support possible

### Option C: Dataflow Architecture

Model workflows as dataflow graphs:

```
[fetch] --content--> [summarize] --summary--> [translate]
                          ↑
                     max_length=50
```

Each node:
- Declares input ports and output ports
- Receives data on input ports
- Emits data on output ports
- No shared mutable state

**Benefits**:
- Natural parallelization (independent branches run concurrently)
- Clear dependencies
- Batch is just "fan-out then fan-in"
- Similar to Apache Beam, Luigi, Prefect

---

## Comparison Matrix

| Aspect | Current (Wrappers) | First-Class IR | Explicit Interfaces | Dataflow |
|--------|-------------------|----------------|--------------------| ---------|
| Complexity location | Wrapper chain | Executor | Node definitions | Graph engine |
| Data flow | Implicit (shared) | Explicit (context) | Explicit (I/O) | Explicit (ports) |
| Type safety | None | Partial | Full | Full |
| Debugging | Hard (4 layers) | Medium | Easy | Easy |
| PocketFlow dependency | Heavy | Light | None | None |
| Migration effort | N/A | Medium | High | Very High |
| Batch support | Wrapper | Executor loop | Map operation | Fan-out/fan-in |
| Parallel support | Complex | Medium | Natural | Natural |

---

## Specific Pain Points to Address

### From Task 96 Analysis

1. **Wrapper insertion point debates** - Should not require deep analysis
2. **Shallow copy for isolation** - Should not be necessary
3. **Namespace clearing between iterations** - Should not be necessary
4. **"Which output key to capture"** - Should be explicit in node interface
5. **Special keys (__llm_calls__) bypass namespacing** - Should have explicit side-channel

### From General Development

1. **Template validation happens at runtime** - Should be compile-time
2. **Shared store mutations hard to track** - Should be immutable or scoped
3. **Adding features requires new wrappers** - Should be executor capabilities
4. **Testing requires mocking wrapper chain** - Should be simpler

---

## Recommended Exploration Path

### Phase 1: Document and Measure (This Task)
- [x] Document current architecture and problems
- [ ] Measure complexity metrics (cyclomatic complexity of wrappers)
- [ ] Count wrapper-related bugs in issue tracker
- [ ] Survey similar tools (Prefect, Dagster, n8n) for patterns

### Phase 2: Prototype Alternatives
- [ ] Prototype First-Class IR Executor for simple workflow
- [ ] Prototype Explicit Interfaces for 2-3 node types
- [ ] Compare: lines of code, test coverage needed, debugging experience

### Phase 3: Migration Strategy
- [ ] If alternative is better, design incremental migration
- [ ] Identify which components can be migrated first
- [ ] Ensure backward compatibility with existing IR

---

## Questions for Future Agent

1. **Is the wrapper complexity justified?** Measure actual bugs/issues caused by it.

2. **Would users benefit from explicit interfaces?** They'd need to understand I/O contracts.

3. **Is PocketFlow still the right foundation?** It was chosen for simplicity, but pflow has outgrown simple.

4. **What's the migration cost?** Existing nodes, tests, IR schemas would need updates.

5. **Are there hybrid approaches?** Keep wrappers for some things, add explicit I/O for others.

---

## References

### Files to Study

- `pocketflow/__init__.py` - Core PocketFlow (100 lines)
- `src/pflow/runtime/compiler.py` - Wrapper chain construction
- `src/pflow/runtime/node_wrapper.py` - TemplateAwareNodeWrapper
- `src/pflow/runtime/namespaced_wrapper.py` - NamespacedNodeWrapper
- `src/pflow/runtime/namespaced_store.py` - Namespace proxy
- `src/pflow/runtime/instrumented_wrapper.py` - InstrumentedNodeWrapper
- `src/pflow/runtime/batch_wrapper.py` - BatchNodeWrapper (Task 96)

### Related Tasks

- Task 96: Batch Processing - Where these insights originated
- Task 39: Parallel Execution - Will face similar wrapper challenges
- Task 92: Replace Planner with Agent Node - Related architectural considerations

### External References

- Prefect: https://www.prefect.io/ - Python dataflow orchestration
- Dagster: https://dagster.io/ - Software-defined assets
- n8n: https://n8n.io/ - Visual workflow automation
- Apache Beam: https://beam.apache.org/ - Unified batch/stream processing

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2024-12-22 | Document as future task, not immediate refactor | MVP needs to ship; architecture works; refactor is significant effort |
| 2024-12-22 | Proceed with wrapper-based batch (Task 96) | Consistent with existing architecture; isolated contexts work |

---

## Notes

This task emerged from Task 96 implementation discussions. The wrapper-based architecture is **functional but not elegant**. It's the result of incremental development on top of PocketFlow.

**The architecture is acceptable for MVP.** Users don't see wrapper complexity - they write IR and it works. But for long-term maintainability and feature development, a cleaner design should be explored.

**Key insight**: The fundamental tension is between PocketFlow's Python-first design (parameters, method calls) and pflow's IR-first design (templates, JSON). The wrappers bridge this gap, but at the cost of complexity.
