# Consistency Resolution Plan

## Overview

This document outlines a detailed plan to resolve inconsistencies between the two specification documents based on the following decisions:

1. **Standardize on `prep_res`** parameter in `exec()` methods
2. **Keep current feature coverage** asymmetry (each doc has unique value)
3. **MVP uses flat keys**, document nested keys as future proxy feature
4. **Use explicit proxy pattern** (not generic `.get()` approach)
5. **kebab-case for JSON/CLI**, **PascalCase for Python**, **simplify IR to use only `id`**
6. **Minor terminology cleanup** where it adds clarity

## File-by-File Update Plan

### A. Updates to `shared-store-cli-runtime-specification.md`

#### A1. Critical Fixes

**Location**: Section 5 "Node Interface Integration" (lines ~35-65)
**Change**: Update `exec()` method signature
```python
# BEFORE:
def exec(self, url):
    language = self.params.get("language", "en")
    return fetch_transcript(url, language)

# AFTER:
def exec(self, prep_res):  # prep_res contains the URL
    language = self.params.get("language", "en")
    return fetch_transcript(prep_res, language)
```

**Location**: Section 14 "Appendix — full flow walk-through" (lines ~470-525)
**Change**: Update exec() examples to use `prep_res`

#### A2. Proxy Pattern Standardization

**Location**: Section 5.1 "CLI to Shared Store Flow" (lines ~65-85)
**Change**: Replace generic proxy creation with explicit pattern
```python
# BEFORE:
proxy = NodeAwareSharedStore(
    shared,
    input_mappings=mappings.get("input_mappings"),
    output_mappings=mappings.get("output_mappings")
)

# AFTER:
proxy = NodeAwareSharedStore(
    shared,
    input_mappings={"url": "video_source"},
    output_mappings={"transcript": "raw_transcript"}
)
```

#### A3. IR Simplification

**Location**: Section 6 "Canonical IR fragment" (lines ~95-115)
**Change**: Remove `name` field, keep only `id` with kebab-case
```json
# BEFORE:
{
  "id": "fetch",
  "name": "yt-transcript",
  "params": { "language": "en" }
}

# AFTER:
{
  "id": "yt-transcript",
  "params": { "language": "en" }
}
```

#### A4. Future Features Note

**Location**: Add new subsection after Section 4 "Concepts & Terminology"
**Change**: Add section "4.2 Future Namespacing Support"
```markdown
#### 4.2 Future Namespacing Support

**MVP Implementation**: Flat key structure for shared store simplicity
```python
shared = {
    "url": "https://youtu.be/abc123",
    "transcript": "Video content..."
}
```

**Future Feature**: Nested path-like keys for complex flows
```python
shared = {
    "inputs/video_url": "https://youtu.be/abc123",
    "outputs/transcript": "Video content..."
}
```

The proxy pattern will support nested key translation when this feature is implemented.
```

### B. Updates to `shared-store-node-proxy-architecture.md`

#### B1. Critical Fixes

**Location**: Section "Static Nodes vs Generated Flows" (lines ~85-110)
**Change**: Update `exec()` method signature in Summarize example
```python
# BEFORE:
def exec(self, prep_res):
    temp = self.params.get("temperature", 0.7)
    return call_llm(prep_res, temperature=temp)

# AFTER: (already correct, keep as-is)
def exec(self, prep_res):
    temp = self.params.get("temperature", 0.7)
    return call_llm(prep_res, temperature=temp)
```

#### B2. IR Naming Convention Update

**Location**: Section "Intermediate Representation (IR)" (lines ~210-250)
**Change**: Update IR example to use kebab-case ids only
```json
# BEFORE:
{
  "id": "summarize_1",
  "name": "Summarize",
  "params": {"temperature": 0.7}
}

# AFTER:
{
  "id": "summarize-text",
  "params": {"temperature": 0.7}
}
```

#### B3. Cross-Reference Addition

**Location**: End of document
**Change**: Add reference to runtime specification
```markdown
## See Also

> **For complete CLI usage, validation rules, and runtime parameter details**, see [Shared-Store & Proxy Model — CLI Runtime Specification](./shared-store-cli-runtime-specification.md)
```

#### B4. Namespacing Clarification

**Location**: Section "Shared Store Namespacing" (lines ~170-195)
**Change**: Add MVP vs future note
```markdown
## Shared Store Namespacing

**Future Feature**: Path-like keys enable organized, collision-free shared store layouts:

**Key**: `"raw_texts/doc1.txt"`
**Maps to**:
```python
shared = {
    "raw_texts": {
        "doc1.txt": "Some input content"
    }
}
```

> **Note**: MVP implementation focuses on flat key structure. Nested namespacing will be supported in future versions through the proxy pattern.
```

### C. Terminology Standardization

#### C1. Consistent Interface Naming

**Both files**: Replace variations with standard terms
- "natural interface" → "natural interface" (singular, consistent)
- "natural interfaces" → "natural interfaces" (plural, when referring to multiple)
- "natural keys" → "natural interface keys" (for clarity)

#### C2. Method Reference Consistency

**Both files**: Ensure method references use consistent format
- `prep()` method (with parentheses)
- `exec()` method
- `post()` method

## Implementation Sequence

### Phase 1: Critical Fixes (High Priority)
1. Update all `exec()` method signatures to use `prep_res`
2. Standardize proxy creation pattern to explicit mappings
3. Update IR examples to remove `name` field

### Phase 2: Clarifications (Medium Priority)
4. Add MVP/future notes for namespacing
5. Add cross-references between documents
6. Update flow examples to match new IR format

### Phase 3: Polish (Low Priority)
7. Terminology audit and cleanup
8. Ensure consistent code formatting
9. Verify all examples use same variable naming

## Validation Checklist

After updates, verify:
- [ ] All `exec(self, prep_res)` signatures consistent
- [ ] All proxy examples use explicit mapping dictionaries
- [ ] All IR examples use kebab-case `id` fields only
- [ ] MVP/future distinction clear for namespacing
- [ ] Cross-references work between documents
- [ ] No conflicting code examples remain
- [ ] Terminology is consistent within each document

## Expected Outcomes

**Immediate Benefits**:
- Developers can implement nodes without signature confusion
- Clear proxy pattern for all generated flow code
- Simplified IR structure for tooling and agents

**Documentation Quality**:
- Each document maintains its unique value proposition
- Clear progression from MVP to advanced features
- Consistent terminology and examples throughout

**Future Compatibility**:
- MVP flat keys work with current implementation
- Nested namespacing path clearly defined
- IR structure ready for tooling ecosystem
