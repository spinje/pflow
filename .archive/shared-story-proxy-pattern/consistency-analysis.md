# Consistency Analysis: Shared Store Documentation

## Overview

This document identifies inconsistencies, gaps, and potential conflicts between:
- `shared-store-cli-runtime-specification.md` (Runtime Spec)
- `shared-store-node-proxy-architecture.md` (Architecture Doc)

## Critical Inconsistencies

### 1. Node Method Signatures - `exec()` Parameter Naming

**Inconsistency**: The `exec()` method signature differs between documents.

**Runtime Spec** (`shared-store-cli-runtime-specification.md`):
```python
def exec(self, url):  # Named parameter matching prep() return
    language = self.params.get("language", "en")
    return fetch_transcript(url, language)
```

**Architecture Doc** (`shared-store-node-proxy-architecture.md`):
```python
def exec(self, prep_res):  # Generic prep_res parameter
    temp = self.params.get("temperature", 0.7)
    return call_llm(prep_res, temperature=temp)
```

**Impact**: This creates confusion about the actual method signature that nodes should implement.

**Recommendation**: Standardize on `prep_res` as the parameter name to maintain consistency with the `post()` method signature.

## Documentation Gaps

### 2. Feature Coverage Asymmetry

**Runtime Spec includes, Architecture Doc missing**:
- Detailed CLI resolution algorithm (Section 7)
- Comprehensive validation rules (Section 11) 
- Flow identity, caching & purity mechanisms (Section 10)
- Edge cases and error handling (Section 13)
- Complete end-to-end execution walkthrough (Section 14)

**Architecture Doc includes, Runtime Spec missing**:
- Path-like shared store keys (`"raw_texts/doc1.txt"`)
- Shared store namespacing patterns
- Progressive complexity examples (Level 1/Level 2)
- Developer experience benefits discussion
- Alternative approaches and design rationale

### 3. Namespacing Pattern Inconsistency

**Architecture Doc** introduces nested path-like keys:
```python
shared = {
    "raw_texts": {
        "doc1.txt": "Some input content"
    }
}
```

**Runtime Spec** only shows flat key structure:
```python
shared = {
    "url": "https://youtu.be/abc123",
    "transcript": "Video transcript content..."
}
```

**Impact**: Unclear when to use flat vs nested key structures.

## Minor Inconsistencies

### 4. Proxy Creation Code Variations

**Runtime Spec** (more generic):
```python
proxy = NodeAwareSharedStore(
    shared,
    input_mappings=mappings.get("input_mappings"),
    output_mappings=mappings.get("output_mappings")
)
```

**Architecture Doc** (hardcoded example):
```python
proxy = NodeAwareSharedStore(
    shared,
    input_mappings={"text": "raw_transcript"},
    output_mappings={"summary": "article_summary"}
)
```

**Note**: Not technically inconsistent, just different levels of abstraction.

### 5. IR Node Naming Conventions

**Runtime Spec**: Uses kebab-case node names (`"yt-transcript"`, `"summarise-text"`)

**Architecture Doc**: Uses PascalCase node names (`"Summarize"`, `"Store"`)

**Impact**: Unclear which naming convention should be used in IR.

## Terminology Variations

### 6. Interface Naming

Both documents use consistent core terminology but with slight variations:
- "natural interface" vs "natural interfaces" vs "natural keys"
- Generally consistent, just minor plural/singular differences

## Recommendations for Resolution

### High Priority
1. **Standardize `exec()` method signature** - Use `prep_res` parameter consistently
2. **Clarify namespacing rules** - When to use flat vs nested shared store keys
3. **Standardize IR node naming** - Choose kebab-case or PascalCase consistently

### Medium Priority
4. **Cross-reference coverage** - Ensure both docs reference each other's unique sections
5. **Align code examples** - Use consistent variable naming and structure
6. **Merge validation rules** - Include basic validation principles in architecture doc

### Low Priority
7. **Terminology audit** - Minor cleanup of plural/singular variations
8. **Example harmonization** - Ensure proxy creation examples use same patterns

## Impact Assessment

**Critical**: Method signature inconsistency could break implementations
**Moderate**: Namespacing and naming conventions affect developer experience
**Low**: Documentation gaps reduce completeness but don't break functionality

## Suggested Actions

1. Update Architecture Doc to use `prep_res` in `exec()` method examples
2. Add namespacing section to Runtime Spec or clarify when each pattern applies
3. Create cross-reference table showing which document covers which aspects
4. Standardize on single IR node naming convention across both documents 