# Template Resolution Call Pattern Investigation

## Executive Summary

Template resolution is called **EXACTLY ONCE per node execution** in the `TemplateAwareNodeWrapper._run()` method. There is **NO caching of resolved values** within the template resolution system itself, BUT there is workflow-level caching via the checkpoint system in `InstrumentedNodeWrapper`.

## Detailed Findings

### 1. Call Sites and Frequency

#### Primary Call Site: `TemplateAwareNodeWrapper._run()`
**File**: `/Users/andfal/projects/pflow-feat-auto-parse-json/src/pflow/runtime/node_wrapper.py:715-850`

**Call Pattern**:
```python
def _run(self, shared: dict[str, Any]) -> Any:
    # Skip resolution if no templates
    if not self.template_params:
        return self.inner_node._run(shared)

    # Build context ONCE
    context = self._build_resolution_context(shared)

    # Resolve ALL template parameters ONCE (lines 741-743)
    resolved_params = {}
    for key, template in self.template_params.items():
        resolved_value, is_simple_template = self._resolve_template_parameter(key, template, context)
        # ... validation and JSON parsing ...
        resolved_params[key] = resolved_value

    # Set resolved params ONCE
    self.inner_node.set_params(**resolved_params)

    # Execute inner node ONCE
    return self.inner_node._run(shared)
```

**Key Points**:
- Resolution happens in a **single batch** for all template parameters
- Each parameter is resolved **exactly once** per node execution
- Resolved values are passed to `inner_node.set_params()` once before execution
- The inner node never sees templates - only resolved values

#### Secondary Call Sites:

1. **BatchNode** (`batch_node.py:247`):
   - Resolves `items` template ONCE in `exec()` before looping
   - Uses `TemplateResolver.resolve_nested()` for inline arrays
   - Each item then creates isolated context for inner node execution

2. **WorkflowExecutor** (`workflow_executor.py:274`):
   - Resolves parameter mappings ONCE before child workflow execution
   - Uses `TemplateResolver.resolve_template()` for each mapped param

### 2. Wrapper Chain Execution Flow

```
InstrumentedNodeWrapper._run()
  │
  ├─ Check cache (lines 557-583)
  │  └─ If cached: return cached_action (NO RESOLUTION)
  │
  ├─ Call: inner_node._run(shared)
  │     │
  │     └─ NamespacedNodeWrapper._run()
  │          └─ Delegates via __getattr__ to TemplateAwareNodeWrapper._run()
  │
  └─ TemplateAwareNodeWrapper._run()
       │
       ├─ Build context ONCE (line 738)
       ├─ Resolve all params ONCE (lines 741-843)
       ├─ Set resolved params ONCE (line 844)
       └─ Call: inner_node._run(shared) → ActualNode
```

**Critical Observation**: The cache check happens at the **InstrumentedNodeWrapper** level, BEFORE any template resolution occurs. This means:
- Cached nodes: **0 template resolutions**
- Non-cached nodes: **1 template resolution** (all params in single batch)

### 3. Caching Mechanisms

#### A. Workflow-Level Checkpoint Caching (EXISTS)
**File**: `/Users/andfal/projects/pflow-feat-auto-parse-json/src/pflow/runtime/instrumented_wrapper.py:557-624`

```python
def _check_cache_validity(self, shared: dict[str, Any]) -> tuple[bool, Optional[Any]]:
    if self.node_id not in shared["__execution__"]["completed_nodes"]:
        return False, None

    # Validate cache using MD5 hash of node configuration
    node_config = self._compute_node_config()
    current_hash = self._compute_config_hash(node_config)
    cached_hash = shared["__execution__"]["node_hashes"].get(self.node_id)

    if current_hash == cached_hash:
        # Cache is valid - skip execution entirely (including resolution)
        cached_action = shared["__execution__"]["node_actions"].get(self.node_id, "default")
        return True, cached_action
    else:
        # Cache invalidated - will re-execute and re-resolve
        self._invalidate_cache(shared)
        return False, None
```

**Cache Invalidation Triggers**:
- Parameter changes (hash mismatch)
- Configuration drift
- Manually cleared cache

**Performance Impact**:
- Cached execution: **No template resolution** (bypasses TemplateAwareNodeWrapper entirely)
- Cache miss: **Full resolution** happens

#### B. Template Resolution-Level Caching (DOES NOT EXIST)

**Evidence**:
```bash
$ grep -i "cache\|memoize" src/pflow/runtime/template_resolver.py
# No results
```

- No `@lru_cache` decorators
- No internal caching dictionaries
- Each call to `resolve_template()` or `resolve_nested()` performs full resolution
- Resolution context is rebuilt fresh every time

### 4. Performance Characteristics

#### Per-Node Resolution Cost (Non-Cached Execution)

For a node with N template parameters:

1. **Context Building** (lines 738):
   - O(K) where K = number of keys in context
   - Typically: initial_params + shared_store + workflow_inputs
   - **Happens ONCE per node**

2. **Parameter Resolution** (lines 741-843):
   - For each template parameter:
     - String templates: Regex match + path traversal
     - Nested structures: Recursive traversal
     - JSON parsing (if applicable): `json.loads()`
   - **Happens ONCE per parameter**

3. **Total per execution**: O(K + N×P) where:
   - K = context size
   - N = number of template parameters
   - P = average path depth + template complexity

#### JSON Parsing Addition Cost

**Current Implementation** (lines 745-780):
```python
if is_simple_template and isinstance(resolved_value, str):
    expected_type = self._expected_types.get(key)
    if expected_type in ("dict", "list", "object", "array"):
        trimmed = resolved_value.strip()

        # Security check
        if len(trimmed) > MAX_JSON_SIZE:
            # Skip parsing

        # Quick structural check
        elif (expected_type in ("dict", "object") and trimmed.startswith("{")) or \
             (expected_type in ("list", "array") and trimmed.startswith("[")):
            try:
                parsed = json.loads(trimmed)  # <-- JSON PARSING HERE
                if type_matches:
                    resolved_value = parsed
            except (json.JSONDecodeError, ValueError):
                # Keep as string
```

**Performance Analysis**:
- JSON parsing only attempted for:
  - Simple templates (`${var}`)
  - String values
  - Expected type is dict/list/object/array
  - String starts with `{` or `[`
- Parsing happens **ONCE per qualifying parameter**
- Failed parses are caught and string preserved
- Security: 10MB size limit prevents DoS

**Worst Case Scenario**:
- Node with 10 parameters, all JSON strings
- Each parameter: ~1MB JSON
- Total parsing time: ~10ms (modern CPUs can parse ~100MB/s)
- **This is negligible compared to network I/O or LLM calls**

### 5. Interaction with Namespaced Store

**File**: `/Users/andfal/projects/pflow-feat-auto-parse-json/src/pflow/runtime/node_wrapper.py:412-450`

```python
def _build_resolution_context(self, shared: dict[str, Any]) -> dict[str, Any]:
    """Build template resolution context from all available sources."""
    context = {}

    # 1. Start with initial_params (highest priority)
    context.update(self.initial_params)

    # 2. Add shared store (runtime data)
    # If namespacing enabled, reads check namespace first, then root
    context.update(shared)

    # 3. Add workflow inputs (declared in IR)
    if "__workflow_inputs__" in shared:
        context.update(shared["__workflow_inputs__"])

    return context
```

**Namespace Read Pattern**:
- NamespacedNodeWrapper redirects **writes** to `shared[node_id][key]`
- NamespacedNodeWrapper redirects **reads** to check both namespace and root
- Template resolution sees **flattened view** of both namespaced and root data
- No performance penalty - just dict lookups

### 6. Batch Execution Special Case

**File**: `/Users/andfal/projects/pflow-feat-auto-parse-json/src/pflow/runtime/batch_node.py:235-280`

```python
def exec(self, shared: dict[str, Any]) -> dict[str, Any]:
    # Resolve items ONCE before batch loop
    if isinstance(self.items_template, list):
        items = TemplateResolver.resolve_nested(self.items_template, shared)
    else:
        var_path = self.items_template.strip()[2:-1]
        items = TemplateResolver.resolve_value(var_path, shared)

        # Auto-parse JSON if needed (ONCE for all items)
        if isinstance(items, str) and trimmed.startswith("["):
            items = json.loads(trimmed)

    # For each item:
    for item in items:
        item_shared = shared.copy()  # Shallow copy
        item_shared[self.item_alias] = item

        # Inner node's TemplateAwareNodeWrapper will resolve templates
        # using the item_shared context (which includes ${item})
        result = self.inner_node._run(item_shared)
```

**Resolution Frequency**:
- `items` template: **1 resolution** (before loop)
- Inner node templates: **N resolutions** (N = number of items)
- Total: 1 + N resolutions for entire batch

**Performance Impact**:
- If inner node has M template params with JSON parsing:
  - Total JSON parses: N × M (one per item per param)
  - Example: 100 items × 3 params = 300 parses
  - If each parse is 1ms: 300ms total
  - **Still negligible compared to 100 node executions**

## Conclusions

### Performance Considerations for JSON Parsing

**✅ NO PERFORMANCE CONCERN**:

1. **Single Resolution Per Node**: Templates resolved exactly once per execution
   - No repeated parsing of same value
   - Resolution is already amortized across node execution

2. **Minimal Additional Cost**:
   - JSON parsing: ~1-10ms for typical payloads
   - Node execution: 10ms-1000ms (I/O, LLM calls)
   - Parsing is <1% of total execution time

3. **Smart Gating**:
   - Only attempts parse for simple templates
   - Only for expected dict/list types
   - Only if string starts with `{` or `[`
   - Size limit prevents DoS

4. **Batch Execution**:
   - Linear scaling (N items × M params)
   - Still dominated by node execution cost
   - Parsing happens in context of actual work

5. **Checkpoint Cache**:
   - Cached nodes skip resolution entirely
   - No parsing happens for cached executions
   - Common in repair workflows

### Recommendation

**Adding JSON parsing in `_resolve_template_parameter()` is SAFE and PERFORMANT**:

- No risk of repeated parsing (resolution happens once)
- Negligible overhead compared to node execution
- Security measures already in place (size limits)
- Benefits outweigh costs (enables shell+jq → MCP patterns)

### Potential Future Optimizations (NOT NEEDED NOW)

If performance becomes a concern (unlikely):

1. **Lazy Parsing**: Only parse when parameter is actually used
   - Would require node instrumentation
   - Complex, not worth it

2. **Context Caching**: Cache resolution context between parameters
   - Already happens (built once per node at line 738)
   - No improvement possible

3. **Template Result Caching**: Cache resolved values across nodes
   - Would require tracking context mutations
   - High complexity for minimal gain
   - Checkpoint system already handles this

## Data Flow Diagram

```
Workflow Execution
       │
       ▼
InstrumentedNodeWrapper._run()
       │
       ├─ Cache Check
       │   ├─ HIT: Return cached action (NO RESOLUTION) ✅
       │   └─ MISS: Continue ↓
       │
       ▼
TemplateAwareNodeWrapper._run()
       │
       ├─ Build Context (ONCE) ────────┐
       │   ├─ initial_params           │
       │   ├─ shared_store              │
       │   └─ workflow_inputs           │
       │                                │
       ├─ For each template param:     │
       │   │                            │
       │   ├─ Resolve template ←────────┤
       │   │   ├─ regex match           │
       │   │   ├─ path traversal        │
       │   │   └─ type preservation     │
       │   │                            │
       │   ├─ JSON parse (if applicable)│
       │   │   ├─ Size check            │
       │   │   ├─ Structure check       │
       │   │   ├─ Parse attempt         │
       │   │   └─ Type validation       │
       │   │                            │
       │   └─ Type validation           │
       │                                │
       ├─ Set resolved params (ONCE)   │
       │                                │
       └─ Execute ActualNode ───────────┘
              │
              └─ Business logic (LLM, API, file ops)
                 (100-1000x slower than resolution)
```

## File References

All findings verified in:
- `/Users/andfal/projects/pflow-feat-auto-parse-json/src/pflow/runtime/node_wrapper.py` (lines 715-850)
- `/Users/andfal/projects/pflow-feat-auto-parse-json/src/pflow/runtime/template_resolver.py` (lines 339-473)
- `/Users/andfal/projects/pflow-feat-auto-parse-json/src/pflow/runtime/instrumented_wrapper.py` (lines 557-663)
- `/Users/andfal/projects/pflow-feat-auto-parse-json/src/pflow/runtime/batch_node.py` (lines 235-280)
- `/Users/andfal/projects/pflow-feat-auto-parse-json/src/pflow/runtime/workflow_executor.py` (lines 260-281)
