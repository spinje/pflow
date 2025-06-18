# JSON Field Extraction & Structured Data Routing

> **Version**: v3.0
> **MVP Status**: ⏳ Future (v3.0)
> For complete MVP boundaries, see [MVP Scope](../features/mvp-scope.md)

*A comprehensive specification for pflow's built-in JSON field extraction capability that eliminates the need for external tools like jq while preserving natural node interfaces.*

---

## 1 · Overview & Value Proposition

pflow's **JSON field extraction** capability enables sophisticated data routing between nodes without requiring external tools or complex node implementations. This system leverages the existing proxy mapping architecture to provide automatic field extraction, type-aware data handling, and intelligent path routing.

**Key Benefits:**

- **Eliminates jq dependency**: Complex JSON transformations handled natively
- **Preserves natural interfaces**: Nodes continue using simple `shared["text"]` patterns
- **Planner intelligence**: Automatic detection and mapping of JSON field compatibility
- **Type safety**: Structured data validation and conversion
- **Performance optimization**: No subprocess overhead for data transformation

**Core Principle**: Complex JSON structures should be transparently routable to simple, natural node interfaces through intelligent mapping.

---

## 2 · Architectural Integration

### 2.1 Integration with Existing Systems

JSON field extraction builds on pflow's established architecture without requiring changes to the core shared store pattern or node interfaces.

**Key Insight**: JSON field extraction extends the proxy mapping system without requiring changes to node interfaces or the shared store pattern.

### 2.2 Relationship to Existing Documentation

| Existing Component | Enhancement |
|---|---|
| **Proxy Mapping** | Extended with JSON path syntax and extraction rules |
| **Planner Interface Analysis** | Enhanced to detect JSON structure compatibility |
| **JSON IR Schema** | New mapping syntax for field extraction |
| **Natural Interfaces** | Preserved while enabling complex data routing |

---

## 3 · JSON Path Syntax & Mapping Extensions

### 3.1 Enhanced Mapping Syntax

**Current Proxy Mapping:**
```json
{
  "mappings": {
    "summarize-text": {
      "input_mappings": {"text": "raw_content"}
    }
  }
}
```

**Enhanced with JSON Path Extraction:**
```json
{
  "mappings": {
    "summarize-text": {
      "input_mappings": {
        "text": "api_response.data.content",
        "title": "api_response.metadata.title"
      }
    }
  }
}
```

### 3.2 JSON Path Specification

**Supported Path Syntax:**

| Pattern | Example | Description |
|---|---|---|
| **Simple field** | `"user.name"` | Extract `name` field from `user` object |
| **Array index** | `"results[0].text"` | First element of `results` array |
| **Array slice** | `"items[0:3]"` | First three elements |
| **Array wildcard** | `"data[*].title"` | All `title` fields from array elements |
| **Conditional** | `"users[?status=active].email"` | Filter and extract from matching elements |
| **Default values** | `"config.timeout\|30"` | Use 30 if `timeout` missing |

### 3.3 Type-Aware Extraction

**Automatic Type Conversion:**

```json
{
  "input_mappings": {
    "text": "response.content",
    "count": "response.metadata.total",
    "active": "response.config.enabled",
    "items": "response.data[*]"
  }
}
```

**Type Validation:**
- Extracted values validated against target node's expected types
- Automatic conversion when safe (string → number, etc.)
- Clear error messages for incompatible extractions

---

## 4 · Planner Integration & Automatic Detection

### 4.1 Enhanced Interface Analysis

**Automatic JSON Structure Detection:**

```python
# Example node metadata with JSON output schema
{
  "id": "fetch-github-repo",
  "outputs": {
    "repo_data": {
      "type": "object",
      "schema": {
        "name": "string",
        "description": "string",
        "topics": "array",
        "language": "string",
        "stats": {
          "stars": "number",
          "forks": "number"
        }
      }
    }
  }
}
```

**Planner Compatibility Matching:**

The planner detects that fetch-github-repo outputs complex JSON but summarize-text needs simple text input, then automatically generates appropriate mapping.

### 4.2 Intelligent Path Selection

**Planner Heuristics:**

1. **Semantic matching**: Field names matched to target input semantics
2. **Type compatibility**: Data types validated for conversion safety
3. **Content analysis**: LLM evaluates field relevance for target node purpose
4. **Fallback chains**: Multiple extraction paths for robustness

**Example Automatic Selection:**

```bash
User: "summarize the GitHub repository description"
↓
Planner detects:
- fetch-github-repo outputs: {name, description, topics, language, stats}
- summarize-text expects: text input
↓
Auto-generates mapping: shared["text"] ← shared["repo_data.description"]
```

### 4.3 Validation & Error Handling

**Extraction Validation:**

- **Path existence**: Verify JSON paths exist in source data
- **Type compatibility**: Ensure extracted values match target expectations
- **Required vs optional**: Handle missing fields gracefully
- **Schema validation**: Validate against declared node interfaces

**Error Recovery:**

```json
{
  "input_mappings": {
    "text": "content.body|content.summary|content.title",
    "author": "metadata.author.name|metadata.user|unknown"
  }
}
```

---

## 5 · User Experience & CLI Integration

### 5.1 Natural Language Planning

**Transparent JSON Handling:**

```bash
$ pflow "get GitHub repo info for microsoft/vscode and summarize it"

🔍 Planning...
   → fetch-github-repo (gets repository data)
   → summarize-text (creates summary)
   → Auto-mapping: repo.description → summary input

📋 Generated CLI:
   pflow fetch-github-repo --repo=microsoft/vscode >> summarize-text

💡 Data flow: repo_data.description → shared["text"]

Execute? [Y/n]:
```

### 5.2 Explicit CLI Syntax (Future)

**Advanced users could specify extractions explicitly:**

```bash
# Extract specific field
pflow fetch-api --url=X >> summarize-text --extract="response.content"

# Multiple field extraction
pflow fetch-user-data --id=123 >> \
      process-profile --extract="user.name,user.email,user.preferences"

# Complex extraction with fallbacks
pflow fetch-article --url=X >> \
      summarize-text --extract="content.body|content.summary"
```

### 5.3 Debugging & Inspection

**Enhanced Tracing:**

```bash
$ pflow trace run_2024-01-01_abc123 --show-extractions

Node: fetch-github-repo
├─ Output: shared["repo_data"] = {name: "vscode", description: "Code editor...", ...}
├─ Extraction: repo_data.description → "Code editor redefined for cloud"
└─ Mapped to: shared["text"]

Node: summarize-text
├─ Input: shared["text"] = "Code editor redefined for cloud"
└─ Output: shared["summary"] = "Microsoft VSCode is a modern..."
```

---

## 6 · Implementation Specifications

### 6.1 NodeAwareSharedStore Enhancement

**Extended Proxy Capabilities:**

```python
class NodeAwareSharedStore:
    def __init__(self, shared, input_mappings=None, output_mappings=None):
        self.shared = shared
        self.input_mappings = input_mappings or {}
        self.output_mappings = output_mappings or {}
        self.json_extractor = JsonPathExtractor()

    def __getitem__(self, key):
        if key in self.input_mappings:
            path = self.input_mappings[key]
            if self._is_json_path(path):
                return self.json_extractor.extract(self.shared, path)
            else:
                return self.shared[path]
        return self.shared[key]

    def _is_json_path(self, path):
        return '.' in path or '[' in path or '|' in path
```

### 6.2 JSON Path Extractor

**Core Extraction Engine:**

```python
class JsonPathExtractor:
    def extract(self, data, path):
        """Extract value using JSON path with fallbacks and type conversion."""
        # Handle fallback chains (path1|path2|default)
        paths = path.split('|')

        for json_path in paths:
            try:
                result = self._extract_single_path(data, json_path.strip())
                if result is not None:
                    return result
            except (KeyError, IndexError, TypeError):
                continue

        # All paths failed, return None or default
        return paths[-1] if len(paths) > 1 else None

    def _extract_single_path(self, data, path):
        """Extract single JSON path: obj.field[0].subfield"""
        # Implementation for dot notation, array indexing, etc.
        pass
```

### 6.3 Schema Integration

**Enhanced Node Metadata:**

```json
{
  "id": "fetch-api-data",
  "outputs": {
    "api_response": {
      "type": "object",
      "extractable_fields": {
        "content": "data.content",
        "title": "metadata.title",
        "author": "author.name",
        "tags": "tags[*]"
      }
    }
  }
}
```

---

## 7 · Performance & Optimization

### 7.1 Extraction Caching

**Path Resolution Caching:**

- Compiled JSON paths cached for reuse
- Extraction results cached when appropriate
- Schema validation cached per node version

### 7.2 Lazy Extraction

**On-Demand Processing:**

- JSON paths only evaluated when target field accessed
- Large objects not fully traversed unless needed
- Memory-efficient processing for large API responses

### 7.3 Error Performance

**Fast Failure Detection:**

- Path validation before execution when possible
- Type checking at mapping generation time
- Clear error messages with suggested corrections

---

## 8 · Security & Safety Considerations

### 8.1 Path Injection Prevention

**Safe Path Parsing:**

- No dynamic code execution in path evaluation
- Whitelist of allowed path syntax elements
- Input validation for user-provided extraction paths

### 8.2 Data Exposure Controls

**Extraction Boundaries:**

- Nodes can only extract from their declared input fields
- Cross-node data access still controlled by shared store permissions
- Sensitive field filtering when configured

---

## 9 · Integration Roadmap

### 9.1 Documentation Updates Required

**Enhanced Existing Documents:**

1. **shared-store-node-proxy-architecture.md**
   - Add JSON path syntax to proxy mapping examples
   - Include extraction performance considerations
   - Show integration with natural interfaces

2. **planner-responsibility-functionality-spec.md**
   - Enhanced interface analysis for JSON structure detection
   - Automatic mapping generation for complex data types
   - LLM context enhancement with extractable field information

3. **json-schema-for-flows-ir-and-nodesmetadata.md**
   - Extended mapping syntax specification
   - JSON path validation rules
   - Node metadata schema for output structure declaration

4. **PRD-pflow.md**
   - Add JSON field extraction to core value propositions
   - Include examples in user journey progression
   - Update competitive advantages vs external tools

### 9.2 New Documentation Sections

**CLI Reference Enhancement:**

```markdown
## JSON Field Extraction

### Automatic Extraction
pflow automatically extracts JSON fields when nodes have compatible interfaces:

```bash
pflow fetch-api-data >> summarize-text
# Auto-maps: api_response.content → shared["text"]
```

### Manual Extraction (Advanced)
```bash
pflow fetch-complex-data >> process-text --extract="data.articles[0].body"
```

### Debugging Extractions
```bash
pflow trace run_id --show-extractions
```
```

### 9.3 Example Integration Points

**New Examples for Existing Docs:**

```bash
# Replace this jq pattern (currently not documented):
# pflow fetch-api | jq '.results[0].text' | pflow summarize

# With this pflow pattern (newly documented):
pflow fetch-api >> summarize-text
# (automatic extraction: results[0].text → shared["text"])
```

**Enhanced User Journey:**

```bash
# Exploration phase
pflow "get weather for Stockholm and summarize the conditions"
# Learns: API JSON → natural text extraction

# Learning phase
pflow weather-api --city=Stockholm >> summarize-text
# Sees: automatic field mapping in trace

# Advanced phase
pflow weather-api --city=Stockholm >> \
      extract-temperature --field="current.temp" >> \
      check-comfort-level
```

---

## 10 · Testing & Validation Framework

### 10.1 Extraction Testing

**Node Interface Tests:**

```python
def test_json_extraction():
    shared = {
        "api_response": {
            "data": {"content": "test content"},
            "metadata": {"title": "Test"}
        }
    }

    proxy = NodeAwareSharedStore(
        shared,
        input_mappings={"text": "api_response.data.content"}
    )

    assert proxy["text"] == "test content"
```

### 10.2 Planner Integration Tests

**Automatic Mapping Generation:**

```python
def test_planner_json_mapping():
    # Mock API node with complex output
    api_node_metadata = {
        "outputs": {"response": {"schema": {"data": {"content": "string"}}}}
    }

    # Mock text processing node with simple input
    text_node_metadata = {
        "inputs": {"text": {"type": "string"}}
    }

    mappings = planner.generate_mappings(api_node_metadata, text_node_metadata)
    assert mappings["input_mappings"]["text"] == "response.data.content"
```

---

## 11 · Migration Strategy

### 11.1 Backward Compatibility

**Existing Flows Unchanged:**

- Current proxy mappings continue working without modification
- Simple key-to-key mappings remain the default
- JSON path syntax is additive, not breaking

### 11.2 Gradual Enhancement

**Phase 1**: Basic JSON path support in proxy mappings
**Phase 2**: Planner integration for automatic detection
**Phase 3**: Advanced CLI syntax and debugging tools
**Phase 4**: Performance optimization and caching

---

## 12 · Conclusion

JSON field extraction positions pflow as a **comprehensive data processing platform** that eliminates the need for external tools while preserving the simplicity of natural node interfaces.

**Key Value Delivery:**

- **Developer Experience**: Nodes remain simple, complex routing handled transparently
- **User Experience**: Natural language planning works with any JSON API
- **Performance**: No subprocess overhead for data transformation
- **Reliability**: Type-safe extraction with clear error handling
- **Ecosystem Growth**: Enables rich API integration without node complexity

This capability transforms pflow from a node orchestration tool into a **complete data processing pipeline** that competes directly with complex shell scripting + jq workflows while maintaining superior transparency, type safety, and reproducibility.

**Next Steps:**

1. Implement basic JSON path extraction in NodeAwareSharedStore
2. Enhance planner with automatic mapping detection
3. Update documentation across all referenced files
4. Add comprehensive testing framework
5. Integrate with CLI tracing and debugging tools

This enhancement aligns perfectly with pflow's core philosophy: **complex capabilities through simple interfaces**.

## 13 · Critical Analysis & Alternative Approaches

> **IMPORTANT**: This section captures critical concerns raised during design review. These insights should inform the final decision on whether to proceed with automatic JSON field extraction.

### 13.1 Fundamental Concerns

**Complexity Creep & Philosophy Drift:**

The automatic JSON field extraction feature introduces several concerns that may violate pflow's core design principles:

1. **"100-line framework" philosophy violation**: Adding a mini JSON query language significantly increases complexity beyond the minimal framework ideal
2. **Scope expansion**: JSON processing isn't pflow's core mission (node orchestration is)
3. **Magic vs. explicit behavior**: Moves from "explicit over magic" toward automatic, potentially opaque transformations
4. **Implementation complexity**: Non-trivial parsing, validation, error handling, and debugging overhead

**Architectural Misalignment:**

- **Pattern vs. framework innovation**: This adds framework complexity rather than focusing on orchestration patterns
- **Natural interface compromise**: Complex path syntax may reduce the intuitive nature of shared store keys
- **Debugging complexity**: JSON path failures could be harder to diagnose than explicit node mismatches

### 13.2 Alternative Approaches

**Option 1: Dedicated JSON Processing Nodes**

Instead of automatic extraction, provide explicit JSON manipulation nodes:

```bash
# Explicit approach - clear data flow
pflow fetch-api-data >> extract-json-field --path="data.articles[0].content" --output-key="text" >> summarize-text

# Multiple extractions
pflow fetch-github-repo >> extract-json-field --path="description" --output-key="text" >> summarize-text
```

**Benefits:**
- **Explicit data flow**: Clear what transformations are happening
- **Debuggable**: Easy to inspect intermediate JSON extraction results
- **Reusable**: JSON extraction nodes can be used in any flow
- **Simple**: No new syntax or mapping complexity

**Option 2: Enhanced Node Metadata for Better Mapping**

Improve the planner's ability to suggest mappings without automatic extraction:

```python
# Enhanced node metadata with semantic hints
class SummarizeText(Node):
    """
    Interface:
    - Reads: shared["text"] - content to summarize
    - Semantic hints: content, description, body, message, article
    """
```

**Benefits:**
- **Planner intelligence**: Better automatic mapping suggestions
- **No syntax complexity**: Uses existing proxy mapping system
- **Explicit user control**: User sees and approves all mappings
- **Backward compatible**: No schema changes required

**Option 3: External Tool Integration**

Seamless integration with existing JSON processing tools:

```bash
# jq integration (future)
pflow fetch-api-data >> jq --path=".data.articles[0].content" >> summarize-text

# Or dedicated JSON transformer nodes
pflow fetch-api-data >> json-transform --extract="data.articles[0].content" >> summarize-text
```

**Benefits:**
- **Leverages existing tools**: jq is battle-tested and well-understood
- **No reinvention**: Don't build what already exists
- **Power user friendly**: jq syntax is already known by many developers
- **Separation of concerns**: JSON processing vs. flow orchestration

### 13.3 Risk Assessment

**Implementation Risks:**

| Risk | Automatic Extraction | Explicit Nodes | Enhanced Metadata |
|------|---------------------|-----------------|-------------------|
| **Complexity creep** | High | Low | Low |
| **Debugging difficulty** | Medium-High | Low | Low |
| **User confusion** | Medium | Low | Low |
| **Maintenance burden** | High | Medium | Low |
| **Philosophy violation** | High | Low | Low |

**User Experience Trade-offs:**

- **Automatic**: Convenient but potentially magical and hard to debug
- **Explicit**: More verbose but clear and debuggable
- **Enhanced metadata**: Best of both worlds - intelligent suggestions with user control

### 13.4 Recommendation Reconsideration

Based on this critical analysis, the automatic JSON field extraction approach may not align with pflow's core principles:

**Core Philosophy Violations:**
- **Explicit over magic**: Automatic extraction is inherently magical
- **Simple nodes**: Adds complexity to the mapping system
- **Minimal framework**: Expands beyond the 100-line ideal

**Better Alternatives:**
1. **Explicit JSON processing nodes** that follow natural interface patterns
2. **Enhanced planner intelligence** for better mapping suggestions
3. **External tool integration** leveraging existing JSON processing solutions

**Decision Framework:**
- If **simplicity and explicitness** are paramount → Choose explicit nodes
- If **user convenience** is critical → Enhance planner suggestions
- If **power and flexibility** are needed → Integrate external tools

### 13.5 Questions for Final Decision

1. **Philosophy**: Does automatic JSON extraction align with pflow's "explicit over magic" principle?
2. **Complexity**: Is the implementation and maintenance burden justified by user convenience?
3. **Alternatives**: Would explicit JSON processing nodes provide better long-term value?
4. **User base**: Do target users prefer convenience or explicitness?
5. **Scope**: Should pflow focus on orchestration or expand into data transformation?

**Recommendation**: Consider abandoning automatic JSON extraction in favor of explicit JSON processing nodes that maintain pflow's core philosophy while providing clear, debuggable data transformation capabilities.

---

This governance document ensures both Flow IR and Node Metadata schemas align with pflow's established architecture while providing focused schema definitions for JSON validation, evolution, and metadata-driven planning capabilities. The critical analysis section preserves important design considerations for informed decision-making.

## See Also

- **Architecture**: [Shared Store + Proxy Pattern](../core-concepts/shared-store.md) - Foundation for JSON path extraction
- **Architecture**: [MVP Scope](../features/mvp-scope.md) - Why JSON extraction is deferred to v3.0
- **Components**: [JSON Schemas](../core-concepts/schemas.md) - Enhanced mapping syntax for extraction
- **Components**: [Planner](../features/planner.md) - Automatic JSON structure detection
- **Patterns**: [Simple Nodes](../features/simple-nodes.md) - Maintaining simple interfaces despite complex data
- **Alternative**: [Shell Pipes](../features/shell-pipes.md) - Using Unix tools like jq instead
- **Critical Analysis**: Section 13 of this document - Important design trade-offs
