# Proxy Pattern Update Plan: Simplifying Node Code with Optional Bindings

## Overview

This plan outlines how to update both documents to reflect the new **proxy-based binding approach** that makes node code maximally simple while providing optional mapping capabilities for complex marketplace scenarios.

---

## Key Changes from Current Approach

### Before (Complex)
```python
class Summarize(Node):
    def prep(self, shared):
        input_key = self.params["input_bindings"]["text"]  # Complex nesting
        return shared[input_key]
    
    def exec(self, prep_res):
        temp = self.params["config"].get("temperature", 0.7)  # Nested config
        return call_llm(prep_res, temperature=temp)
```

### After (Simple)
```python
class Summarize(Node):
    def prep(self, shared):
        return shared["text"]  # Simple, natural key
    
    def exec(self, prep_res):
        temp = self.params.get("temperature", 0.7)  # Flat config
        return call_llm(prep_res, temperature=temp)
```

---

## 1. Design Pattern Document Updates

### 1.1 Update Core Concepts Section

**Current Problem**: Explains complex nested binding structure
**Solution**: Explain simple node code + optional proxy magic

**New Section**: "The Proxy Pattern"
- Nodes use natural, simple keys
- Proxy handles mapping transparently when needed
- Zero overhead for simple flows
- Full power for marketplace scenarios

### 1.2 Completely Rewrite Node Examples

**Remove**: All `self.params["input_bindings"]["key"]` complexity
**Add**: Simple, clean node code examples

**New Node Example**:
```python
class Summarize(Node):  # Inherits from pocketflow.Node
    def prep(self, shared):
        return shared["text"]  # Simple access with natural key
    
    def exec(self, prep_res):
        temp = self.params.get("temperature", 0.7)  # Flat config access
        return call_llm(prep_res, temperature=temp)
    
    def post(self, shared, prep_res, exec_res):
        shared["summary"] = exec_res  # Simple write with natural key
```

### 1.3 Add Progressive Complexity Examples

**Simple Flow Example**:
```python
# Simple flow - no mappings needed
shared = {"text": "Input content", "summary": ""}

summarize_node = Summarize()
summarize_node.set_params({"temperature": 0.7})  # Just config

flow = Flow(start=summarize_node)
flow.run(shared)  # Node accesses shared["text"] directly
```

**Complex Flow Example**:
```python
# Marketplace flow - mappings enable compatibility
shared = {"raw_transcript": "Input content"}

# Proxy maps node's "text" → flow's "raw_transcript"
node_proxy = NodeAwareSharedStore(
    shared,
    input_mappings={"text": "raw_transcript"},  # Use "mappings" terminology
    output_mappings={"summary": "article_summary"}
)

summarize_node = Summarize()  # Same node code!
summarize_node.set_params({"temperature": 0.7})
summarize_node._run(node_proxy)  # Uses proxy instead of raw shared
```

### 1.4 Add NodeAwareSharedStore Explanation

**New Section**: "The NodeAwareSharedStore Proxy"

**Content**:
- How the proxy intercepts shared store access
- Transparent mapping for input/output keys
- Pass-through behavior when no mappings defined
- Implementation details, benefits, and error handling
- How it enables simple node code and marketplace compatibility

### 1.5 Update Flow vs Node Distinction

**Clarify**:
- **Nodes**: Use simple, natural keys in their code
- **Flows**: Define mappings via `input_mappings` and `output_mappings` for proxy when needed for compatibility
- **Proxy**: Handles translation transparently

### 1.6 Update IR Format Section

**Change**: Define IR for flow-level mappings

**New IR Example**:
```json
{
  "nodes": [
    {
      "id": "summarize_1", 
      "name": "Summarize",
      "config": {"temperature": 0.7}
    }
    // ... other nodes
  ],
  "edges": [
    // ... edge definitions
  ],
  "mappings": {
    "summarize_1": {
      "input_mappings": {"text": "raw_texts/doc1.txt"},
      "output_mappings": {"summary": "summaries/doc1.txt"}
    }
    // ... mappings for other nodes if needed
  }
}
```

### 1.7 Add Debugging with Proxy Section

**New Section**: "Debugging with the Proxy Pattern"

**Content**:
- How to interpret error messages from the proxy
- Techniques for inspecting proxy behavior (debug mode, tools)
- Best practices for avoiding mapping issues

---

## 2. Canonical Spec Document Updates

### 2.1 Add Proxy Architecture Section

**New Section**: "Proxy-Based Mapping Architecture"

**Content**:
- How NodeAwareSharedStore enables simple node code
- When proxy is used vs direct access (based on `mappings` in IR)
- Performance characteristics (zero overhead for simple flows)
- Integration with pocketflow (extension or helper class)

### 2.2 Update Node Interface Integration

**Remove**: Complex `self.params["input_bindings"]` examples
**Add**: Simple node interface with proxy explanation

**New Example**:
```python
# Node class (static, pre-written) - SIMPLE
class YTTranscript(Node):
    def prep(self, shared):
        return shared["url"]  # Natural key access
    
    def exec(self, url):
        language = self.params.get("language", "en")  # Flat config
        return fetch_transcript(url, language)
    
    def post(self, shared, prep_res, exec_res):
        shared["transcript"] = exec_res  # Natural key write

# Flow-level mapping (from IR's "mappings" section)
if node_id in ir["mappings"]:
    mappings = ir["mappings"][node_id]
    node_proxy = NodeAwareSharedStore(
        shared,
        input_mappings=mappings.get("input_mappings"),
        output_mappings=mappings.get("output_mappings")
    )
    node._run(node_proxy)
else:
    node._run(shared)  # Direct access for simple flows
```

### 2.3 Update CLI Resolution Algorithm

**Change**: Clarify config handling and proxy creation

**New Algorithm**:
1. Parse CLI as flat `key=value`.
2. For CLI flags matching shared store keys: inject into `shared_store[store_key] = value`.
3. For CLI flags intended as config: update the corresponding node's `params` (flat structure). (Requires mechanism to distinguish config flags, e.g., `--config:node_id:key=value` or node-specific flags).
4. For each node in flow (from IR):
   - If mappings are defined in IR for this node:
     - Create `NodeAwareSharedStore` proxy with these mappings.
     - Pass proxy to node's execution methods.
   - Else (no mappings defined):
     - Pass raw shared store to node's execution methods.
5. Execute flow.

### 2.4 Rewrite Integration Examples

**Show both scenarios**: Simple (no mappings) and Complex (with mappings from IR)

### 2.5 Update Full Flow Walk-through

**Simplify**: Remove complex binding access in node methods
**Add**: Show how proxy intercepts and maps when mappings are defined in IR

### 2.6 Clarify pocketflow Integration

**New Section**: "pocketflow Framework Integration Details"

**Content**:
- Specify if `NodeAwareSharedStore` is a pocketflow extension or a helper class used by generated flow code.
- How the flow execution logic (handling proxy vs direct) integrates with pocketflow's `Flow` class.

---

## 3. New Concepts to Introduce

### 3.1 Progressive Complexity Model

- **Level 1**: Simple flows with direct shared access (no `mappings` in IR)
- **Level 2**: Complex flows with proxy mapping (defined in IR `mappings` section)
- **Same node code works at both levels**

### 3.2 NodeAwareSharedStore

- **Purpose**: Transparent mapping layer
- **Interface**: Mimics dictionary; consider full `dict` compatibility (get, pop, keys, items, etc.)
- **Behavior**: Maps keys when mappings defined, passes through otherwise
- **Performance**: Zero overhead when no mappings
- **Error Handling**: Clear messages for missing keys or mapping issues

### 3.3 Flow-Level vs Node-Level Concerns

- **Node level**: Business logic with natural key names and flat config in `params`
- **Flow level**: Data routing and schema compatibility via `mappings` in IR
- **Clear separation of concerns**

---

## 4. What to Remove

### 4.1 From Both Documents

- All `self.params["input_bindings"]["key"]` examples
- Nested config structure (`self.params["config"]["key"]`)
- Complex three-level nesting explanations
- Terminology: Replace "bindings" with "mappings" for clarity in proxy context

### 4.2 Replace With

- Simple node code examples
- Flat config access patterns
- Progressive complexity explanation
- Clear proxy architecture description
- Standardized "mappings" terminology

---

## 5. New Validation Checklist

After updates, both documents should:
- [ ] Show nodes using natural keys (`shared["text"]`)
- [ ] Demonstrate flat config access (`self.params.get("temperature")`)
- [ ] Explain proxy pattern clearly using "mappings" terminology
- [ ] Show simple flows without mappings in IR
- [ ] Show complex flows with mappings from IR
- [ ] Clarify zero overhead for simple cases
- [ ] Maintain marketplace compatibility story
- [ ] Remove all complex nesting examples
- [ ] Define clear IR format for mappings
- [ ] Explain pocketflow integration (extension or helper)
- [ ] Provide robust CLI config override mechanism
- [ ] Include debugging guidance for proxy
- [ ] Confirm full `dict` compatibility for proxy if needed
- [ ] Detail proxy error handling

---

## 6. Implementation Priority

1. **Update Design Pattern Document**
   - Rewrite node examples to be simple
   - Add proxy pattern explanation with "mappings"
   - Show progressive complexity
   - Update IR format example
   - Add debugging section

2. **Update Canonical Spec Document**
   - Add proxy architecture section
   - Update CLI resolution algorithm
   - Rewrite integration examples
   - Simplify full walk-through
   - Clarify pocketflow integration

3. **Ensure Consistency**
   - Same node code examples in both docs
   - Consistent proxy and "mappings" explanation
   - Aligned terminology

---

## 7. Key Messages to Emphasize

- **Node code is maximally simple** - uses natural keys
- **Complexity is opt-in** - mappings only when you need marketplace compatibility
- **Same code works everywhere** - simple and complex flows
- **Zero overhead by default** - proxy only when needed
- **Clear separation** - nodes focus on logic, flows handle routing via IR mappings

---

## 8. Proxy Implementation Outline

```python
class NodeAwareSharedStore:
    def __init__(self, shared_data, input_mappings=None, output_mappings=None):
        self.shared_data = shared_data
        self.input_mappings = input_mappings or {}
        self.output_mappings = output_mappings or {}
    
    def _map_key(self, key, is_input):
        mappings = self.input_mappings if is_input else self.output_mappings
        return mappings.get(key, key) # Default to original key if no mapping

    def __getitem__(self, key):
        actual_key = self._map_key(key, is_input=True)
        try:
            return self.shared_data[actual_key]
        except KeyError:
            raise KeyError(f"Node expects '{key}' (mapped to '{actual_key}'), but '{actual_key}' not found in shared store. Available keys: {list(self.shared_data.keys())}")

    def __setitem__(self, key, value):
        actual_key = self._map_key(key, is_input=False)
        self.shared_data[actual_key] = value
    
    def __contains__(self, key):
        actual_key = self._map_key(key, is_input=True)
        return actual_key in self.shared_data
    
    # Consider adding other dict methods: get, pop, keys, items, values, __delitem__
    # for full compatibility if nodes expect them.
    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

```
This proxy enables simple node code while maintaining full flexibility.