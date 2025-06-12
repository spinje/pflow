# Integration Update Plan: pflow Pattern with pocketflow Framework

## Overview

This plan outlines the specific changes needed to align both documents with the actual implementation using the pocketflow framework, where node classes are static and we reuse the existing `params` system.

---

## Key Insights to Integrate

1. **pocketflow Framework**: 100-line Python framework with existing `params` system
2. **Static Node Classes**: Node implementations are pre-written, not generated from IR
3. **Generated Flow Code**: Only the flow orchestration code is generated from IR
4. **Reuse `params` System**: Populate `self.params` with bindings structure instead of adding new attributes
5. **`set_params()` Usage**: Use existing framework method to configure nodes

---

## 1. Design Pattern Document Updates

### 1.1 Update Node Implementation Examples

**Current Problem**: Shows `self.input_bindings` as attributes
**Solution**: Use `self.params["input_bindings"]` to match pocketflow framework

**New Node Example**:
```python
class Summarize(Node):  # Inherits from pocketflow.Node
    def prep(self, shared):
        # Access input binding through existing params system
        input_key = self.params["input_bindings"]["text"]  # "raw_transcript"
        return shared[input_key]

    def exec(self, prep_res):
        # Access config through existing params system
        temp = self.params["config"].get("temperature", 0.7)
        return call_llm(prep_res, temperature=temp)

    def post(self, shared, prep_res, exec_res):
        # Access output binding through existing params system
        output_key = self.params["output_bindings"]["summary"]  # "article_summary"
        shared[output_key] = exec_res
```

### 1.2 Add Framework Integration Section

**New Section**: "Integration with pocketflow Framework"

**Content**:
- Explain that nodes inherit from `pocketflow.Node`
- Show how `set_params()` populates the bindings structure
- Clarify that node classes are written once and reused
- Demonstrate the `prep()`/`exec()`/`post()` pattern from pocketflow

### 1.3 Update Flow Examples

**Change**: Replace manual node configuration with `set_params()` calls

**New Flow Example**:
```python
# Static node classes (written once)
class Summarize(Node):
    # ... implementation above

# Generated flow code (from IR)
yt_node = YTTranscript()
summarize_node = Summarize()

# Set params from IR bindings
yt_node.set_params({
    "input_bindings": {"url": "video_url"},
    "output_bindings": {"transcript": "raw_transcript"},
    "config": {"language": "en"}
})

summarize_node.set_params({
    "input_bindings": {"text": "raw_transcript"},
    "output_bindings": {"summary": "article_summary"},
    "config": {"temperature": 0.7}
})

# Wire the flow
yt_node >> summarize_node
flow = Flow(start=yt_node)
```

### 1.4 Clarify Static vs Generated Code

**New Section**: "Static Nodes vs Generated Flows"

**Content**:
- **Static**: Node class definitions (written by developers)
- **Generated**: Flow orchestration code (from IR)
- **Runtime**: CLI injection into shared store and config overrides

### 1.5 Remove `__init__` Confusion

**Change**: Remove the `__init__` method examples that showed binding attributes
**Reason**: pocketflow handles initialization, we just use `set_params()`

---

## 2. Canonical Spec Document Updates

### 2.1 Update Node Interface Integration Section

**Current Problem**: Shows node attributes being set directly
**Solution**: Show `set_params()` usage and framework integration

**New Content**:
```python
# Node class (static, pre-written)
class YTTranscript(Node):  # Inherits from pocketflow.Node
    def prep(self, shared):
        url_key = self.params["input_bindings"]["url"]  # "video_url"
        return shared[url_key]

    def exec(self, url):
        language = self.params["config"].get("language", "en")
        return fetch_transcript(url, language)

    def post(self, shared, prep_res, exec_res):
        output_key = self.params["output_bindings"]["transcript"]  # "raw_transcript"
        shared[output_key] = exec_res

# Generated flow code (from IR)
node = YTTranscript()
node.set_params({
    "input_bindings": {"url": "video_url"},
    "output_bindings": {"transcript": "raw_transcript"},
    "config": {"language": "en"}
})
```

### 2.2 Update Integration Example

**Change**: Show complete generated flow code instead of just node setup

**New Section 7.4**: "Generated Flow Code"
```python
# This code is generated from IR
def create_flow():
    # Instantiate static node classes
    fetch_node = YTTranscript()
    summarize_node = SummarizeText()

    # Configure nodes with IR bindings
    fetch_node.set_params({
        "input_bindings": {"url": "video_url"},
        "output_bindings": {"transcript": "raw_transcript"},
        "config": {"language": "en"}
    })

    summarize_node.set_params({
        "input_bindings": {"text": "raw_transcript"},
        "output_bindings": {"summary": "article_summary"},
        "config": {"temperature": 0.7}  # Will be overridden by CLI
    })

    # Wire the flow using pocketflow operators
    fetch_node >> summarize_node

    return Flow(start=fetch_node)

# CLI execution
def run_with_cli():
    shared = {"video_url": "https://youtu.be/abc123"}  # CLI injection
    flow = create_flow()

    # Handle config override (implementation detail)
    # Override temperature to 0.9 for summarize_node

    flow.run(shared)
```

### 2.3 Add Framework Context

**New Section**: "pocketflow Framework Integration"

**Content**:
- Brief explanation of pocketflow's 100-line implementation
- How our pattern leverages existing `params` and flow orchestration
- Reference to pocketflow documentation for framework details

### 2.4 Update CLI Resolution Algorithm

**Change**: Clarify that config overrides update node params

**Updated Algorithm**:
1. Parse CLI as flat `key=value`
2. For CLI flags matching `input_bindings`: inject into `shared_store[store_key] = value`
3. For CLI flags matching `config`: update the corresponding node's params via `set_params()`
4. Generate flow code with updated configurations
5. Execute flow with populated shared store

---

## 3. Cross-References Updates

### 3.1 Add pocketflow References

**Both Documents**: Add references to:
- `pocketflow/__init__.py` for framework implementation
- `pocketflow/docs/core_abstraction/communication.md` for params usage patterns

### 3.2 Framework vs Pattern

**Clarify**:
- **pocketflow**: The underlying 100-line framework
- **pflow pattern**: Our specific use of input_bindings/output_bindings/config within pocketflow's params system

---

## 4. New Validation Checklist

After updates, both documents should:
- [ ] Show node classes inheriting from `pocketflow.Node`
- [ ] Use `self.params["input_bindings"]` instead of `self.input_bindings`
- [ ] Demonstrate `set_params()` usage from IR
- [ ] Clarify static node classes vs generated flow code
- [ ] Show complete generated flow examples
- [ ] Reference pocketflow framework appropriately
- [ ] Maintain the hybrid power pattern explanation
- [ ] Show CLI integration with existing framework

---

## 5. Implementation Priority

1. **Update Design Pattern Document**
   - Fix node implementation examples
   - Add framework integration section
   - Clarify static vs generated code

2. **Update Canonical Spec Document**
   - Show generated flow code examples
   - Update CLI resolution algorithm
   - Add framework context

3. **Add Cross-References**
   - Link to pocketflow docs
   - Clarify framework vs pattern terminology

---

## 6. Key Messages to Maintain

While updating implementation details, preserve these core concepts:
- **Hybrid Power Pattern**: Bindings enable node reusability across flows
- **Three-part model**: input_bindings (routing in), output_bindings (routing out), config (tunables)
- **CLI to internal key mapping**: External names vs internal shared store keys
- **Flow-level schema definition**: Planner sets up shared store layout
- **Static nodes, dynamic flows**: Node logic is reusable, flow wiring is generated

---

## 7. Framework Benefits to Highlight

- **Minimal overhead**: Leverages existing 100-line framework
- **Backward compatibility**: Existing pocketflow code works unchanged
- **Clean separation**: Node logic vs flow orchestration vs CLI integration
- **Proven patterns**: Uses established `prep()`/`exec()`/`post()` model
- **No framework modifications**: Pure pattern implementation using existing APIs
