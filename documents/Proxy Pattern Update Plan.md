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
# Simple flow - no bindings needed
shared = {"text": "Input content", "summary": ""}

summarize_node = Summarize()
summarize_node.set_params({"temperature": 0.7})  # Just config

flow = Flow(start=summarize_node)
flow.run(shared)  # Node accesses shared["text"] directly
```

**Complex Flow Example**:
```python
# Marketplace flow - bindings enable compatibility
shared = {"raw_transcript": "Input content"}

# Proxy maps node's "text" → flow's "raw_transcript"
node_proxy = NodeAwareSharedStore(
    shared,
    input_bindings={"text": "raw_transcript"},
    output_bindings={"summary": "article_summary"}
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
- Pass-through behavior when no bindings defined
- Implementation details and benefits

### 1.5 Update Flow vs Node Distinction

**Clarify**:
- **Nodes**: Use simple, natural keys in their code
- **Flows**: Define mappings via bindings when needed for compatibility
- **Proxy**: Handles translation transparently

### 1.6 Remove Complex IR Examples

**Replace**: Complex nested binding examples
**With**: Simple node code + flow-level binding configuration

---

## 2. Canonical Spec Document Updates

### 2.1 Add Proxy Architecture Section

**New Section**: "Proxy-Based Binding Architecture"

**Content**:
- How NodeAwareSharedStore enables simple node code
- When proxy is used vs direct access
- Performance characteristics (zero overhead for simple flows)

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

# Flow-level binding (when needed)
if bindings_needed:
    node_proxy = NodeAwareSharedStore(
        shared,
        input_bindings={"url": "video_url"},
        output_bindings={"transcript": "raw_transcript"}
    )
    node._run(node_proxy)
else:
    node._run(shared)  # Direct access for simple flows
```

### 2.3 Update CLI Resolution Algorithm

**Change**: Clarify that config is flat, not nested

**New Algorithm**:
1. Parse CLI as flat `key=value`
2. For CLI flags matching flow's `input_bindings`: inject into shared store
3. For other CLI flags: set directly in node params (flat structure)
4. Create proxy if bindings defined, otherwise use direct shared access
5. Execute flow

### 2.4 Rewrite Integration Examples

**Show both scenarios**:

**Simple Scenario**:
```python
# No bindings needed - direct access
shared = {"url": "https://youtu.be/abc123"}
node.set_params({"language": "en"})
node._run(shared)  # Direct access
```

**Complex Scenario**:
```python
# Bindings needed for compatibility
shared = {"video_url": "https://youtu.be/abc123"}
node_proxy = NodeAwareSharedStore(
    shared,
    input_bindings={"url": "video_url"},
    output_bindings={"transcript": "raw_transcript"}
)
node.set_params({"language": "en"})
node._run(node_proxy)  # Proxy access
```

### 2.5 Update Full Flow Walk-through

**Simplify**: Remove all the complex binding access in node methods
**Add**: Show how proxy intercepts and maps when bindings are defined

---

## 3. New Concepts to Introduce

### 3.1 Progressive Complexity Model

- **Level 1**: Simple flows with direct shared access
- **Level 2**: Complex flows with proxy mapping
- **Same node code works at both levels**

### 3.2 NodeAwareSharedStore

- **Purpose**: Transparent mapping layer
- **Interface**: Looks like normal dictionary to nodes
- **Behavior**: Maps keys when bindings defined, passes through otherwise
- **Performance**: Zero overhead when no bindings

### 3.3 Flow-Level vs Node-Level Concerns

- **Node level**: Business logic with natural key names
- **Flow level**: Data routing and schema compatibility
- **Clear separation of concerns**

---

## 4. What to Remove

### 4.1 From Both Documents

- All `self.params["input_bindings"]["key"]` examples
- Nested config structure (`self.params["config"]["key"]`)
- Complex three-level nesting explanations
- Arguments about binding complexity vs benefits

### 4.2 Replace With

- Simple node code examples
- Flat config access patterns
- Progressive complexity explanation
- Clear proxy architecture description

---

## 5. New Validation Checklist

After updates, both documents should:
- [ ] Show nodes using natural keys (`shared["text"]`)
- [ ] Demonstrate flat config access (`self.params.get("temperature")`)
- [ ] Explain proxy pattern clearly
- [ ] Show simple flows without bindings
- [ ] Show complex flows with bindings
- [ ] Clarify zero overhead for simple cases
- [ ] Maintain marketplace compatibility story
- [ ] Remove all complex nesting examples

---

## 6. Implementation Priority

1. **Update Design Pattern Document**
   - Rewrite node examples to be simple
   - Add proxy pattern explanation
   - Show progressive complexity
   - Remove complex binding examples

2. **Update Canonical Spec Document**
   - Add proxy architecture section
   - Update CLI resolution algorithm
   - Rewrite integration examples
   - Simplify full walk-through

3. **Ensure Consistency**
   - Same node code examples in both docs
   - Consistent proxy explanation
   - Aligned terminology

---

## 7. Key Messages to Emphasize

- **Node code is maximally simple** - uses natural keys
- **Complexity is opt-in** - only when you need marketplace compatibility
- **Same code works everywhere** - simple and complex flows
- **Zero overhead by default** - proxy only when needed
- **Clear separation** - nodes focus on logic, flows handle routing

---

## 8. Proxy Implementation Outline

```python
class NodeAwareSharedStore:
    def __init__(self, shared_data, input_bindings=None, output_bindings=None):
        self.shared_data = shared_data
        self.input_bindings = input_bindings or {}
        self.output_bindings = output_bindings or {}
    
    def __getitem__(self, key):
        # Map input key if binding exists
        actual_key = self.input_bindings.get(key, key)
        return self.shared_data[actual_key]
    
    def __setitem__(self, key, value):
        # Map output key if binding exists
        actual_key = self.output_bindings.get(key, key)
        self.shared_data[actual_key] = value
    
    def __contains__(self, key):
        actual_key = self.input_bindings.get(key, key)
        return actual_key in self.shared_data
```

This proxy enables the simple node code while maintaining full flexibility for complex scenarios. 