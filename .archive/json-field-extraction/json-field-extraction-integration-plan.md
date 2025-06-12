# JSON Field Extraction Integration Plan

*Minimal documentation updates to integrate JSON field extraction as a first-class pflow capability while preserving existing schemas and architecture.*

---

## 1 · Integration Principles

**Minimal Change Strategy:**
- Leverage existing proxy mapping architecture (no schema changes)
- Extend current JSON path syntax (already supported in mappings)
- Enhance planner without modifying core validation pipeline
- Add capabilities through existing extension points

**Consistency Requirements:**
- Maintain current JSON IR schema format
- Preserve existing node metadata structure
- Keep natural interface patterns unchanged
- Follow established CLI resolution rules

---

## 2 · Existing Architecture Compatibility

### 2.1 Current Proxy Mapping Support

**Already Supported in JSON IR Schema:**
```json
{
  "mappings": {
    "summarize-text": {
      "input_mappings": {"text": "raw_transcript"},
      "output_mappings": {"summary": "article_summary"}
    }
  }
}
```

**Enhancement (No Schema Change):**
```json
{
  "mappings": {
    "summarize-text": {
      "input_mappings": {"text": "api_response.data.content"},
      "output_mappings": {"summary": "processed_results.summary"}
    }
  }
}
```

### 2.2 NodeAwareSharedStore Extension

**Current Implementation (from shared-store-node-proxy-architecture.md):**
- Already supports arbitrary key mapping
- Proxy pattern established and working
- Natural interface preservation confirmed

**Required Enhancement:**
- Add JSON path parsing to existing `__getitem__` method
- No interface changes to nodes or shared store
- Backward compatible with simple key mappings

---

## 3 · Documentation Updates Required

### 3.1 shared-store-node-proxy-architecture.md

**Section to Add (after existing proxy examples):**

```markdown
### Advanced Mapping: JSON Path Extraction

The proxy mapping system supports JSON path syntax for extracting fields from complex data structures:

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

**Supported JSON Path Patterns:**
- **Dot notation**: `"user.profile.name"`
- **Array indexing**: `"results[0].text"`
- **Fallback chains**: `"content.body|content.summary|title"`

**Implementation Note:** JSON paths are detected automatically when mapping values contain `.` or `[` characters. Simple key mappings continue to work unchanged.
```

**Estimated Addition:** ~15 lines

### 3.2 planner-responsibility-functionality-spec.md

**Section to Add (in "Shared Store Integration" section):**

```markdown
### 8.5 Automatic JSON Field Mapping

**Enhanced Interface Detection:**

When the planner detects nodes with complex JSON outputs connecting to nodes expecting simple inputs, it automatically generates JSON path mappings:

```python
# Node A outputs: {"api_response": {"data": {"content": "text"}, "metadata": {...}}}
# Node B expects: shared["text"]
# Planner generates: {"text": "api_response.data.content"}
```

**Mapping Generation Rules:**
- Semantic field name matching (content → text, title → title)
- Type compatibility validation (string fields to string inputs)
- Fallback path generation for robustness
- User confirmation of generated mappings in preview

This enhancement uses existing proxy mapping infrastructure without requiring schema changes.
```

**Estimated Addition:** ~12 lines

### 3.3 json-schema-for-flows-ir-and-nodesmetadata.md

**Section to Add (in "Proxy Mapping Schema" section):**

```markdown
### 5.5 JSON Path Mapping Syntax

**Extended Mapping Values:**

Mapping values support JSON path syntax for field extraction:

```json
{
  "mappings": {
    "node-id": {
      "input_mappings": {
        "simple_key": "source_key",                    // Simple mapping (existing)
        "extracted_field": "complex_data.field.value", // JSON path (new)
        "with_fallback": "primary.field|backup.field|default_value"
      }
    }
  }
}
```

**Path Syntax Rules:**
- Dot notation for nested objects: `"obj.field.subfield"`
- Array indexing: `"array[0]"` or `"array[*]"` for all elements
- Fallback chains: `"path1|path2|default"` (tries paths left to right)

**Validation:** JSON paths validated during IR validation phase. Invalid paths cause flow validation failure with clear error messages.

**Backward Compatibility:** Simple string mappings continue to work unchanged. JSON path detection is automatic based on syntax.
```

**Estimated Addition:** ~18 lines

### 3.4 PRD-pflow.md

**Section to Add (in "Core Concepts" section, after "Proxy Mapping"):**

```markdown
### 2.5 JSON Field Extraction

pflow automatically handles **complex JSON data routing** through enhanced proxy mappings:

```bash
# API returns: {"data": {"articles": [{"title": "...", "content": "..."}]}}
# Node expects: shared["text"]
# pflow automatically maps: data.articles[0].content → shared["text"]

pflow fetch-api-data >> summarize-text
# Planner generates transparent JSON field extraction
```

**Benefits:**
- **No jq required**: Complex JSON transformations handled natively
- **Automatic detection**: Planner generates mappings based on data structure analysis
- **Type safety**: Extracted values validated against target node expectations
- **Natural interfaces preserved**: Nodes continue using simple `shared["text"]` patterns

**Example Flow:**
```bash
pflow "get GitHub repo info and summarize the description"
# Auto-generates: fetch-github-repo >> summarize-text
# With mapping: repo_data.description → shared["text"]
```
```

**Estimated Addition:** ~20 lines

### 3.5 shared-store-cli-runtime-specification.md

**Section to Add (in debugging/tracing section):**

```markdown
### Enhanced Tracing for JSON Extraction

**Extraction Visibility:**

```bash
pflow trace run_id --show-mappings

Node: fetch-api-data
├─ Output: shared["api_response"] = {data: {content: "..."}, metadata: {...}}
└─ Mappings: api_response.data.content → shared["text"]

Node: summarize-text
├─ Input: shared["text"] = "extracted content"
└─ Source: Mapped from api_response.data.content
```

**Debugging Failed Extractions:**

```bash
pflow trace run_id --mapping-errors
# Shows: Path 'api_response.missing_field' not found, used fallback 'api_response.title'
```
```

**Estimated Addition:** ~12 lines

---

## 4 · Implementation Sequence

### Phase 1: Core Enhancement (Week 1)
1. **NodeAwareSharedStore JSON path support**
   - Add JSON path detection (`'.' in path or '[' in path`)
   - Implement basic dot notation and array indexing
   - Add fallback chain support (`path1|path2|default`)

2. **Testing framework**
   - Unit tests for JSON path extraction
   - Integration tests with existing proxy mapping

### Phase 2: Planner Integration (Week 2)
1. **Automatic mapping detection**
   - Enhance interface analysis to detect JSON structure mismatches
   - Generate JSON path mappings for compatible field names
   - Add mapping validation to existing validation pipeline

2. **User experience**
   - Show generated mappings in CLI preview
   - Add mapping explanations to trace output

### Phase 3: Documentation (Week 3)
1. **Update existing docs** (5 files, ~77 total lines added)
2. **Add examples** to existing sections
3. **Update CLI help** with JSON path syntax

---

## 5 · Validation & Testing

### 5.1 Backward Compatibility Tests

**Existing Functionality Preserved:**
- All current proxy mappings continue working
- Simple key-to-key mappings unchanged
- No changes to node interfaces or shared store behavior
- JSON IR schema remains identical

### 5.2 Integration Tests

**New Capability Validation:**
- JSON path extraction accuracy
- Fallback chain behavior
- Type conversion and validation
- Planner mapping generation
- CLI tracing enhancements

---

## 6 · Risk Mitigation

### 6.1 Schema Stability

**No Breaking Changes:**
- JSON IR schema unchanged (uses existing mapping structure)
- Node metadata format unchanged
- CLI parameter resolution unchanged
- Shared store pattern unchanged

### 6.2 Performance Impact

**Minimal Overhead:**
- JSON path detection only when mapping contains special characters
- Lazy evaluation (paths only parsed when accessed)
- Caching of compiled paths for reuse
- No impact on simple mappings or direct shared store access

### 6.3 Error Handling

**Graceful Degradation:**
- Invalid JSON paths fail during validation (not runtime)
- Clear error messages with suggested corrections
- Fallback chains prevent extraction failures
- Existing error handling patterns preserved

---

## 7 · Success Metrics

### 7.1 Integration Success

- **Zero breaking changes** to existing flows
- **All existing tests pass** without modification
- **Documentation updates** under 100 total lines across all files
- **Implementation** completed in 3 weeks

### 7.2 Capability Success

- **Automatic mapping generation** for 90%+ of JSON structure mismatches
- **User approval rate** ≥95% for generated JSON path mappings
- **Performance overhead** <5% for flows using JSON extraction
- **Error rate** <1% for valid JSON path expressions

---

## 8 · Conclusion

This integration plan delivers **powerful JSON field extraction** capabilities while:

- **Preserving all existing functionality** and schemas
- **Requiring minimal documentation changes** (~77 lines total)
- **Leveraging established architecture** (proxy mapping, planner validation)
- **Maintaining backward compatibility** for all current flows

The enhancement transforms pflow into a **complete data processing platform** that eliminates jq dependency while preserving the simplicity and transparency that defines pflow's user experience.

**Next Action:** Begin Phase 1 implementation with NodeAwareSharedStore enhancement and comprehensive testing framework. 