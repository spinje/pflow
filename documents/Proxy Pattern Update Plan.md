# Proxy Pattern Update Plan: Making Nodes Standalone and Simple

## Overview

This plan outlines how to update both documents to reflect the new **proxy-based approach** that makes node code maximally simple and standalone by removing binding complexity from node implementations and moving it to flow orchestration where it belongs.

## Key Insight: Nodes Should Be Standalone

The fundamental insight is that **node writers shouldn't need to understand flow orchestration concepts**. They should write simple, testable business logic using natural key names, while flow designers handle mapping complexity at the orchestration level.

---

## Benefits of the Proxy Pattern

### 1. Standalone Node Development
- **Current**: Node writers must understand binding indirection (`self.params["input_bindings"]["text"]`)
- **Proxy**: Node writers use intuitive keys (`shared["text"]`)

### 2. Simplified Testing
- **Current**: Complex test setup with binding configuration
- **Proxy**: Natural test setup with direct key access

### 3. Better Separation of Concerns
- **Node level**: Pure business logic with natural interfaces
- **Flow level**: Handle mapping complexity and schema compatibility

### 4. Reduced Cognitive Load
- Node writers focus on their domain (text processing, API calls, etc.)
- Flow designers handle orchestration concerns (routing, mapping, compatibility)

### 5. More Readable Code
```python
# Current (complex)
input_key = self.params["input_bindings"]["text"]
return shared[input_key]

# Proxy (simple)
return shared["text"]
```

---

## Key Changes from Current Approach

### Before (Complex for Node Writers)
```python
class Summarize(Node):
    def prep(self, shared):
        input_key = self.params["input_bindings"]["text"]  # Binding indirection
        return shared[input_key]
    
    def exec(self, prep_res):
        temp = self.params["config"].get("temperature", 0.7)  # Nested config
        return call_llm(prep_res, temperature=temp)
    
    def post(self, shared, prep_res, exec_res):
        output_key = self.params["output_bindings"]["summary"]  # More indirection
        shared[output_key] = exec_res
```

### After (Simple for Node Writers)
```python
class Summarize(Node):
    """Summarizes text input.
    
    Expects: shared["text"] - text to summarize
    Produces: shared["summary"] - summarized text
    Config: temperature - LLM temperature (default 0.7)
    """
    def prep(self, shared):
        return shared["text"]  # Natural, direct access
    
    def exec(self, prep_res):
        temp = self.params.get("temperature", 0.7)  # Flat config
        return call_llm(prep_res, temperature=temp)
    
    def post(self, shared, prep_res, exec_res):
        shared["summary"] = exec_res  # Simple assignment
```

**Complexity moved to flow orchestration level** (where it belongs).

---

## 1. Design Pattern Document Updates

### 1.1 Update Core Philosophy Section

**New opening**: "Node Autonomy Principle"
- Nodes should be standalone, testable units
- Node writers focus on business logic, not orchestration 
- Complexity belongs at the flow level, not node level
- Natural interfaces beat binding indirection

### 1.2 Completely Rewrite Node Examples

**Remove**: All `self.params["input_bindings"]["key"]` complexity
**Add**: Simple, standalone node code examples with clear docstrings

**New Node Example**:
```python
class Summarize(Node):  # Inherits from pocketflow.Node
    """Summarizes text content using LLM.
    
    Interface:
    - Reads: shared["text"] - input text to summarize
    - Writes: shared["summary"] - generated summary
    - Config: temperature (default 0.7) - LLM creativity
    """
    def prep(self, shared):
        return shared["text"]  # Simple, natural access
    
    def exec(self, prep_res):
        temp = self.params.get("temperature", 0.7)  # Flat config
        return call_llm(prep_res, temperature=temp)
    
    def post(self, shared, prep_res, exec_res):
        shared["summary"] = exec_res  # Direct assignment
```

### 1.3 Add NodeAwareSharedStore Explanation

**New Section**: "The NodeAwareSharedStore Proxy"

**Content**:
- Enables simple node code while supporting complex flow routing
- Transparent mapping between node expectations and flow schema
- Zero overhead when no mapping needed (direct pass-through)
- Activated only when IR defines mappings for a node

### 1.4 Show Testing Benefits

**New Section**: "Node Testing Simplicity"

**Simple Testing Example**:
```python
def test_summarize_node():
    node = Summarize()
    node.set_params({"temperature": 0.5})  # Just config
    
    # Natural, intuitive shared store
    shared = {"text": "Long article content here..."}
    
    node.run(shared)
    
    assert "summary" in shared
    assert len(shared["summary"]) < len(shared["text"])
```

Compare to current complex binding setup requirements.

### 1.5 Progressive Complexity Examples

**Level 1 - Simple Flow (Direct Access)**:
```python
# No mappings needed - nodes access shared store directly
shared = {"text": "Input content"}

summarize_node = Summarize()
summarize_node.set_params({"temperature": 0.7})

flow = Flow(start=summarize_node)
flow.run(shared)  # Node accesses shared["text"] directly
```

**Level 2 - Complex Flow (Proxy Mapping)**:
```python
# Marketplace compatibility - proxy maps keys transparently
shared = {"raw_transcript": "Input content"}  # Flow schema

# Generated flow code handles proxy creation
if "mappings" in ir and summarize_node.id in ir["mappings"]:
    mappings = ir["mappings"][summarize_node.id]
    proxy = NodeAwareSharedStore(
        shared,
        input_mappings={"text": "raw_transcript"},
        output_mappings={"summary": "article_summary"}
    )
    summarize_node._run(proxy)  # Node still uses shared["text"]
else:
    summarize_node._run(shared)  # Direct access
```

### 1.6 Update IR Format Section

**New IR Example with Mappings**:
```json
{
  "nodes": [
    {
      "id": "summarize_1", 
      "name": "Summarize",
      "config": {"temperature": 0.7}
    }
  ],
  "edges": [
    {"from": "input", "to": "summarize_1"}
  ],
  "mappings": {
    "summarize_1": {
      "input_mappings": {"text": "raw_texts/doc1.txt"},
      "output_mappings": {"summary": "summaries/doc1.txt"}
    }
  }
}
```

Key change: Mappings are flow-level concern in IR, nodes just declare natural interfaces.

### 1.7 Add Developer Experience Section

**New Section**: "Developer Experience Benefits"

**Content**:
- Node development is simpler (no binding knowledge required)
- Testing is intuitive (natural shared store setup)
- Debugging is clearer (direct key access in node code)
- Documentation is self-evident (shared["key"] shows interface)

---

## 2. Canonical Spec Document Updates

### 2.1 Add Proxy Architecture Section

**New Section**: "Proxy-Based Mapping Architecture"

**Content**:
- How NodeAwareSharedStore enables simple node code
- When proxy is activated (based on IR mappings) vs direct access
- Performance: zero overhead for simple flows, mapping only when needed
- Integration approach with pocketflow (helper class used by generated code)

### 2.2 Update Node Interface Integration

**Replace complex binding examples with simple interface**:

```python
# Node class (static, pre-written) - SIMPLE AND STANDALONE
class YTTranscript(Node):
    """Fetches YouTube transcript.
    
    Interface:
    - Reads: shared["url"] - YouTube video URL
    - Writes: shared["transcript"] - extracted transcript text
    - Config: language (default "en") - transcript language
    """
    def prep(self, shared):
        return shared["url"]  # Natural interface
    
    def exec(self, url):
        language = self.params.get("language", "en")  # Simple config
        return fetch_transcript(url, language)
    
    def post(self, shared, prep_res, exec_res):
        shared["transcript"] = exec_res  # Direct write

# Generated flow code handles proxy when needed
def run_node_with_mapping(node, shared, mappings=None):
    if mappings:
        proxy = NodeAwareSharedStore(shared, **mappings)
        node._run(proxy)
    else:
        node._run(shared)  # Direct access
```

### 2.3 Update CLI Resolution Algorithm

**New Algorithm** (emphasizing simplicity):
1. Parse CLI as flat `key=value`
2. For CLI flags matching natural shared store keys: inject directly
3. For CLI flags marked as config: update node params (flat structure)
4. Generate flow code that:
   - Creates proxy if IR defines mappings for node
   - Uses direct access if no mappings defined
5. Execute flow with appropriate access pattern per node

### 2.4 Rewrite Integration Examples

**Show both scenarios with emphasis on node simplicity**:

**Simple Scenario** (no mappings):
```python
# Node uses natural keys, flow matches them
shared = {"url": "https://youtu.be/abc123"}
yt_node = YTTranscript()
yt_node.run(shared)  # Direct access
```

**Complex Scenario** (with mappings):
```python
# Node still uses natural keys, proxy handles mapping
shared = {"video_source": "https://youtu.be/abc123"}  # Flow schema
proxy = NodeAwareSharedStore(
    shared,
    input_mappings={"url": "video_source"},
    output_mappings={"transcript": "extracted_text"}
)
yt_node.run(proxy)  # Node still accesses shared["url"]
```

### 2.5 Update Full Flow Walk-through

**Emphasize node simplicity throughout**:
- Show nodes using natural key access
- Explain how proxy handles mapping transparently
- Demonstrate that same node code works in both scenarios

---

## 3. Key Philosophy Changes

### 3.1 Complexity Allocation

**Old**: Spread binding complexity across every node
**New**: Centralize mapping complexity at flow orchestration level

### 3.2 Developer Experience

**Old**: Node writers must understand flow orchestration concepts
**New**: Node writers focus purely on business logic

### 3.3 Testing Philosophy

**Old**: Complex setup with binding configuration for testing
**New**: Simple, natural shared store setup for testing

---

## 4. What to Remove

### 4.1 From Both Documents

- All `self.params["input_bindings"]["key"]` examples
- Complex binding indirection explanations
- Nested config structure (`self.params["config"]["key"]`)
- Arguments about why binding complexity is necessary

### 4.2 Replace With

- Simple, standalone node code examples
- Clear interface documentation via docstrings
- Flat config access patterns (`self.params.get("key")`)
- Proxy pattern explanation and benefits
- Progressive complexity examples

---

## 5. New Validation Checklist

After updates, both documents should:
- [ ] Show nodes as standalone units with natural interfaces
- [ ] Demonstrate simple testing without binding setup
- [ ] Explain proxy pattern clearly with zero-overhead guarantee
- [ ] Show progressive complexity (simple flows vs marketplace flows)
- [ ] Use flat config access (`self.params.get("key")`)
- [ ] Define clear IR format with flow-level mappings
- [ ] Emphasize developer experience benefits
- [ ] Remove all binding indirection from node code
- [ ] Show proxy creation in generated flow code only
- [ ] Maintain marketplace compatibility story via proxy

---

## 6. Implementation Priority

1. **Update Design Pattern Document**
   - Rewrite all node examples to be simple and standalone
   - Add proxy pattern explanation focusing on simplicity benefits
   - Show testing advantages
   - Add progressive complexity examples

2. **Update Canonical Spec Document**
   - Add proxy architecture section
   - Update CLI resolution algorithm
   - Rewrite integration examples
   - Simplify full walk-through

3. **Ensure Consistency**
   - Same simple node code examples in both docs
   - Consistent proxy explanation
   - Aligned on "complexity belongs at flow level" philosophy

---

## 7. Key Messages to Emphasize

- **Nodes are standalone** - no orchestration knowledge required
- **Testing is simple** - natural shared store setup
- [ ] Complexity is opt-in - proxy only when marketplace compatibility needed
- **Same code works everywhere** - simple and complex flows
- **Zero overhead by default** - direct access when possible
- **Clear separation** - nodes focus on logic, flows handle routing

---

## 8. Proxy Implementation Outline

```python
class NodeAwareSharedStore:
    """Transparent proxy that enables simple node code while supporting complex routing."""
    
    def __init__(self, shared_data, input_mappings=None, output_mappings=None):
        self.shared_data = shared_data
        self.input_mappings = input_mappings or {}
        self.output_mappings = output_mappings or {}
    
    def _map_key(self, key, is_input):
        mappings = self.input_mappings if is_input else self.output_mappings
        return mappings.get(key, key)  # Default to original key if no mapping

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
    
    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default
```

This proxy enables simple node code while maintaining full flexibility.