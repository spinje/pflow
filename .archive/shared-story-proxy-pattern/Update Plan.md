# Update Plan: Aligning Design Pattern and Canonical Spec Documents

## Overview
This plan outlines the specific changes needed to align both documents with the clarified understanding of the Hybrid Power Pattern while keeping their separate focuses intact.

---

## 1. Design Pattern Document Updates

### 1.1 Terminology Updates
**Change**: Replace all `params` references with `input_bindings`/`output_bindings`/`config`

**Specific Changes**:
- Replace `self.params["input_key"]` with `self.input_bindings["text"]` (where "text" is the CLI interface name)
- Update the Node Example section to show proper binding usage
- Update the Flow Example section to use new IR format

### 1.2 Node Interface Clarification
**Change**: Update the node example to show how bindings work with `prep()`/`exec()`/`post()`

**New Node Example**:
```python
class Summarize(Node):
    def __init__(self):
        self.input_bindings = {}  # Set by IR: {"text": "raw_transcript"}
        self.output_bindings = {} # Set by IR: {"summary": "article_summary"}
        self.config = {}          # Set by IR: {"temperature": 0.7}

    def prep(self, shared):
        # Read from shared store using the bound key
        input_key = self.input_bindings["text"]  # "raw_transcript"
        return shared[input_key]

    def exec(self, text):
        temp = self.config.get("temperature", 0.7)
        return call_llm(text, temperature=temp)

    def post(self, shared, _, summary):
        # Write to shared store using the bound key
        output_key = self.output_bindings["summary"]  # "article_summary"
        shared[output_key] = summary
```

### 1.3 IR Format Update
**Change**: Update JSON IR examples to use new format

**New IR Example**:
```json
{
  "nodes": [
    {
      "id": "summarize_1",
      "name": "Summarize",
      "input_bindings": {"text": "raw_texts/doc1.txt"},
      "output_bindings": {"summary": "summaries/doc1.txt"},
      "config": {"temperature": 0.7}
    },
    {
      "id": "store_1",
      "name": "Store",
      "input_bindings": {"content": "summaries/doc1.txt"},
      "output_bindings": {},
      "config": {}
    }
  ],
  "edges": [
    {"from": "summarize_1", "to": "store_1"}
  ]
}
```

### 1.4 Add Hybrid Power Pattern Section
**New Section**: Add dedicated section explaining the pattern

**Content**:
- Why nodes don't hardcode shared store keys
- How bindings enable reusability across different flows
- How the planner acts as a "compiler" setting up the shared schema
- Examples showing same node used in different flows with different bindings

### 1.5 Shared Store Namespacing
**Change**: Add explanation of path-like keys

**Content**:
- Explain that `"raw_texts/doc1.txt"` creates nested structure
- Show how it maps to `shared["raw_texts"]["doc1.txt"]` in Python
- Explain benefits: namespacing, collision avoidance, debugging

### 1.6 Remove CLI References
**Change**: Remove or minimize CLI-related content
- Focus purely on the programming model and conceptual framework
- Add cross-reference to Canonical Spec for CLI details

---

## 2. Canonical Spec Document Updates

### 2.1 Add Node Interface Integration
**New Section**: Add section showing how `prep()`/`exec()`/`post()` methods work with bindings

**Content**:
- Show complete node class with binding attributes
- Demonstrate how CLI values flow through bindings to shared store to node methods
- Include execution flow diagram

### 2.2 Update IR Examples
**Change**: Ensure all IR examples use consistent format matching Design Pattern

**Updates**:
- Change `"type"` to `"name"`
- Remove any `"params"` references
- Ensure `input_bindings`/`output_bindings`/`config` structure is consistent

### 2.3 Clarify CLI to Binding Mapping
**Change**: Add detailed explanation of CLI interface vs internal keys

**New Content**:
```
CLI Flag: --url=https://example.com
Input Binding: {"url": "video_url"}
Result: shared["video_url"] = "https://example.com"
Node Access: self.input_bindings["url"] → "video_url" → shared["video_url"]
```

### 2.4 Add Integration Examples
**New Section**: End-to-end examples showing:
1. IR definition
2. CLI command
3. Shared store population
4. Node execution with bindings
5. Final shared store state

### 2.5 Update Mutability Rules
**Change**: Clarify what can/cannot be changed

**Updated Rules**:
- `input_bindings` keys (like "video_url") can be populated from CLI for first nodes
- `output_bindings` are immutable (cannot be changed outside IR)
- `config` values are runtime overrideable via CLI
- Bindings structure itself is immutable (part of IR)

---

## 3. Cross-References

### 3.1 Design Pattern Document
**Add**: References to Canonical Spec for:
- CLI usage details
- Runtime configuration
- Implementation specifications

### 3.2 Canonical Spec Document
**Add**: References to Design Pattern for:
- Conceptual understanding
- Architectural rationale
- Node implementation patterns

---

## 4. Validation Checklist

After updates, both documents should:
- [ ] Use identical terminology (`input_bindings`/`output_bindings`/`config`)
- [ ] Show consistent IR format
- [ ] Demonstrate same node interface pattern
- [ ] Explain the Hybrid Power Pattern clearly
- [ ] Be usable independently while cross-referencing appropriately
- [ ] Show clear distinction between CLI interface names and shared store keys
- [ ] Explain the role of edges (flow structure) vs bindings (data access)

---

## 5. Order of Updates

1. **Update Design Pattern Document first** - Establish the canonical programming model
2. **Update Canonical Spec Document second** - Align with programming model and add CLI integration
3. **Add cross-references** - Link the documents appropriately
4. **Review consistency** - Ensure no remaining inconsistencies

---

## 6. Key Messages to Reinforce

In both documents, ensure these concepts are clear:
- **Bindings enable reusability** - Same node, different flows, different shared store layouts
- **Planner as compiler** - Sets up shared schema and wires nodes via bindings
- **CLI interface vs internal keys** - External names (url) vs internal keys (video_url)
- **Three-part model** - input_bindings (routing in), output_bindings (routing out), config (local tunables)
- **Shared store as coordination bus** - Flow-global memory with flexible schema
