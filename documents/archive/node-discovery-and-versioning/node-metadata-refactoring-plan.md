# Node Metadata Refactoring Plan

## Executive Summary

This plan outlines how to split `node-metadata-extraction.md` into two focused documents while preserving valuable technical content and fixing architectural inconsistencies.

**Target Documents**:
1. **`node-metadata-extraction.md`** - Production-ready metadata extraction infrastructure
2. **`future-llm-node-generation.md`** - Future LLM-assisted node development capabilities

**Scope**: Preserve all technical extraction infrastructure while clearly separating future LLM generation features.

---

## 1 · Document Split Strategy

### 1.1 Current Document → `node-metadata-extraction.md`

**Focus**: Metadata extraction from existing static nodes for planner integration

**Core Content to Retain**:
- Technical parsing architecture (`PflowMetadataExtractor`)
- Docstring format standards (aligned with source docs)
- Registry integration patterns
- CLI extraction commands (under `registry` namespace)
- Performance optimizations
- Schema definitions (aligned with json-schema doc)

**New Positioning**:
- Supporting infrastructure for planner metadata discovery
- Extraction from developer-written static nodes
- Integration with established registry and versioning systems

### 1.2 New Document → `future-llm-node-generation.md`

**Focus**: Future LLM-assisted node development and enhancement

**Content to Move**:
- LLM generation workflows (`LLMNodeGenerator`)
- Node enhancement capabilities
- Generation CLI commands
- LLM integration strategies
- Code generation examples

**Positioning**:
- Clearly marked as future feature
- Builds on metadata extraction foundation
- Doesn't contradict static node architecture

---

## 2 · Detailed Refactoring Steps

### Phase 1: Prepare New Future Document

#### Step 1.1: Create `future-llm-node-generation.md`

```markdown
# Future: LLM-Assisted Node Development

> **Status**: Future Feature - Not part of MVP architecture
> **Dependencies**: Requires node-metadata-extraction infrastructure

## Overview

This document outlines planned LLM-assisted capabilities for node development, building on the established metadata extraction infrastructure while preserving pflow's static node architecture.

**Key Principle**: LLM assists developers in creating better nodes and documentation, but does not replace the curated, static node ecosystem established in the core architecture.
```

#### Step 1.2: Move LLM-Related Content

**Content to Transfer**:
- Sections 1-2 ("Executive Summary", "Why This Approach Wins") → Rewrite for future context
- Section 4 ("LLM Integration Strategy") → Move entirely  
- `LLMNodeGenerator` class → Move to future doc
- CLI commands for generation/enhancement → Move to future doc
- All references to "LLM generates code + documentation"

**Content to Reframe**:
- Change all present tense ("LLM generates") to future tense ("LLM will assist")
- Add caveats about integration with static node architecture
- Position as enhancement tools, not replacement for developer-written nodes

### Phase 2: Refactor Current Document

#### Step 2.1: Update Document Title and Introduction

**New Title**: `Node Metadata Extraction Infrastructure`

**New Introduction**:
```markdown
# Node Metadata Extraction Infrastructure

## Executive Summary

**Chosen Approach**: Structured docstring parsing with hybrid extraction
**Primary Format**: Interface sections in Python docstrings  
**Parsing Strategy**: `docstring_parser` + custom regex for pflow-specific sections  
**Purpose**: Enable metadata-driven planner selection from static node library

This document defines the infrastructure for extracting structured metadata from developer-written pflow nodes to support the planner's discovery and validation capabilities.

## Why This Approach

### Integration with Static Node Architecture

**Established Reality**: Developers write static, reusable node classes
**Our Solution**: Extract rich metadata to enable intelligent planner selection
**Key Benefit**: Bridge between human-written nodes and AI-driven flow planning

### Technical Benefits

1. **Zero Runtime Overhead** - Pre-extracted JSON for fast planner access
2. **Source of Truth** - Metadata extracted from actual node code
3. **Framework Integration** - Works with established pocketflow patterns
4. **Registry Compatible** - Integrates with versioning and discovery systems
```

#### Step 2.2: Fix Schema Alignment

**Current Issue**: Schema mismatch with `json-schema-for-flows-ir-and-nodesmetadata.md`

**Required Changes**:
```json
// REMOVE (from node-metadata-extraction.md):
{
  "node": { ... },
  "metadata": {
    "interface": { ... },
    "examples": [ ... ]
  },
  "extraction": { ... }
}

// REPLACE WITH (from json-schema source):
{
  "node": { ... },
  "interface": { ... },
  "documentation": { ... },
  "extraction": { ... }
}
```

**Implementation**:
1. Update all JSON examples in section 8 ("Registry Integration")
2. Modify `PflowMetadataExtractor._normalize_metadata()` method
3. Update storage schema in section 8.1

#### Step 2.3: Fix CLI Command Namespace

**Current Issue**: Introduces `pflow metadata` namespace not in source docs

**Required Changes**:
```bash
# REMOVE:
pflow metadata extract node.py
pflow metadata validate node.py

# REPLACE WITH:
pflow registry extract-metadata node.py
pflow registry validate-metadata node.py
pflow registry refresh-metadata  # Bulk re-extraction
```

**Implementation Steps**:
1. Update section 5 ("CLI Integration") 
2. Modify all CLI examples throughout document
3. Integrate with established registry command structure from source docs
4. Remove standalone metadata command group

#### Step 2.4: Align Docstring Format

**Current Issue**: Format mismatch with `shared-store-node-proxy-architecture.md`

**Source Format** (from architecture doc):
```python
"""
Interface:
- Reads: shared["text"] - input text to summarize
- Writes: shared["summary"] - generated summary  
- Params: temperature (default 0.7) - LLM creativity
"""
```

**Current Proposal** (inconsistent):
```python
"""
Interface:
    Inputs:
        input_key (type): Description, required/optional
    Outputs:
        output_key (type): Description
    Parameters:
        param_name (type, optional): Description. Default: value
"""
```

**Resolution Strategy**:
1. **Option A**: Adopt source format and update parser
2. **Option B**: Update source docs to use structured format
3. **Option C**: Support both formats with parser flexibility

**Recommended**: Option C with parser auto-detection

#### Step 2.5: Add Source Document Integration

**Missing References**: Document doesn't reference source architecture

**Required Additions**:
```markdown
## Integration with pflow Architecture

This metadata extraction infrastructure directly supports several core pflow systems:

### Planner Discovery Integration
> **See**: [Planner Responsibility Spec](./planner-responsibility-functionality-spec.md#node-discovery)

The extraction process feeds the planner's metadata-driven selection:
- Builds registry of available nodes with natural language descriptions
- Provides interface compatibility data for validation
- Enables LLM context generation for intelligent selection

### Registry Integration  
> **See**: [Node Discovery & Versioning](./node-discovery-namespacing-and-versioning.md#registry-management)

Metadata extraction occurs during node installation:
- `pflow registry install node.py` triggers automatic metadata extraction
- Version changes invalidate cached metadata
- Registry commands use pre-extracted metadata for rich CLI experience

### Shared Store Compatibility
> **See**: [Shared Store Pattern](./shared-store-node-proxy-architecture.md#natural-interfaces)

Extracted interface data preserves natural shared store access patterns:
- Documents `shared["key"]` usage from actual node code
- Enables proxy mapping generation when needed
- Validates interface consistency across flow components
```

### Phase 3: Content Reorganization

#### Step 3.1: Restructure Sections

**New Structure for `node-metadata-extraction.md`**:

1. **Purpose & Architecture Integration** (new)
2. **Docstring Format Standard** (updated from section 3)
3. **Extraction Implementation** (updated from section 3)
4. **Registry Integration** (updated from section 6) 
5. **CLI Commands** (updated from section 5)
6. **Performance & Caching** (from section 12)
7. **Schema Definitions** (aligned with json-schema doc)
8. **Validation & Quality** (extracted from current validation sections)

**Removed Sections**:
- Executive Summary (LLM assumptions)
- Why This Approach Wins (generation focus)
- LLM Integration Strategy (entire section)
- LLM-related CLI commands

#### Step 3.2: Update All Examples

**Remove LLM Generation Examples**:
- Delete `LLMNodeGenerator` class examples
- Remove node generation workflows
- Remove enhancement workflows

**Add Extraction Examples**:
```python
# Example: Extracting from existing node
class ExistingYTTranscript(Node):
    """Fetches YouTube transcript from video URL.
    
    Interface:
    - Reads: shared["url"] - YouTube video URL  
    - Writes: shared["transcript"] - extracted transcript text
    - Params: language (default "en") - transcript language
    """
    def prep(self, shared):
        return shared["url"]
    
    def exec(self, prep_res):
        language = self.params.get("language", "en")
        return fetch_transcript(prep_res, language)
    
    def post(self, shared, prep_res, exec_res):
        shared["transcript"] = exec_res

# Extraction process
extractor = PflowMetadataExtractor() 
metadata = extractor.extract_metadata(ExistingYTTranscript)
# Result: Complete metadata JSON for planner use
```

---

## 3 · Dependencies and Migration

### 3.1 Update Source Documents

**Required Source Changes** (optional, for full consistency):

1. **`shared-store-node-proxy-architecture.md`**:
   - Add section referencing metadata extraction
   - Show how metadata supports proxy mapping generation

2. **`planner-responsibility-functionality-spec.md`**:
   - Reference specific extraction infrastructure
   - Show metadata feeding into LLM selection process

3. **`node-discovery-namespacing-and-versioning.md`**:
   - Integration with `pflow registry extract-metadata` commands
   - Metadata invalidation on version changes

### 3.2 Implementation Dependencies

**Required Infrastructure**:
- `docstring_parser` library
- Registry file structure updates
- CLI command namespace expansion
- JSON schema validation

**Optional Enhancements**:
- Code analysis for validation
- Performance monitoring
- Metadata quality scoring

---

## 4 · Validation Checklist

### 4.1 Consistency Validation

**Schema Alignment**:
- [ ] All JSON examples match `json-schema-for-flows-ir-and-nodesmetadata.md`
- [ ] Top-level structure uses `documentation` not `metadata` wrapper
- [ ] Interface fields align with established schema

**CLI Integration**:
- [ ] All commands under `pflow registry` namespace
- [ ] No standalone `pflow metadata` commands
- [ ] Integration with existing registry workflows

**Documentation Format**:
- [ ] Docstring examples align with source document format
- [ ] Parser supports established Interface section structure
- [ ] Backward compatibility with existing node documentation

### 4.2 Architectural Compliance

**Static Node Architecture**:
- [ ] No assumptions about LLM-generated nodes
- [ ] Focus on extraction from developer-written code
- [ ] Clear positioning as supporting infrastructure

**Source Document Integration**:
- [ ] Proper cross-references to planner, registry, shared store docs
- [ ] Shows integration with established workflows
- [ ] Doesn't introduce conflicting concepts

---

## 5 · Timeline and Effort

### 5.1 Effort Estimates

**Phase 1** (New Future Document): **2-3 hours**
- Create new document structure
- Move LLM-related content
- Reframe as future feature

**Phase 2** (Refactor Current Document): **4-6 hours**  
- Update introduction and positioning
- Fix schema, CLI, format inconsistencies
- Add source document integration
- Restructure sections

**Phase 3** (Validation & Polish): **2-3 hours**
- Cross-reference validation
- Example updates
- Final consistency check

**Total Effort**: **8-12 hours**

### 5.2 Priority Order

1. **High Priority**: Schema alignment, CLI namespace, philosophical positioning
2. **Medium Priority**: Source document integration, format alignment
3. **Low Priority**: Example updates, performance optimizations

---

## 6 · Success Criteria

### 6.1 Technical Success

- [ ] No contradictions with source-of-truth documents
- [ ] Clean separation between extraction (current) and generation (future)
- [ ] All technical infrastructure preserved and functional
- [ ] Schema compatibility with established JSON standards

### 6.2 Architectural Success

- [ ] Aligns with static node philosophy
- [ ] Integrates with planner discovery process
- [ ] Supports registry and versioning systems
- [ ] Enables natural interface documentation

### 6.3 User Experience Success

- [ ] Clear scope and purpose
- [ ] Actionable implementation guidance
- [ ] No confusion about current vs future capabilities
- [ ] Rich examples and integration patterns

---

## 7 · Post-Refactoring Benefits

### 7.1 Current Document Benefits

- **Clear Purpose**: Focused metadata extraction infrastructure
- **Architectural Alignment**: No contradictions with established patterns
- **Immediate Value**: Production-ready extraction capabilities
- **Integration Ready**: Supports planner and registry requirements

### 7.2 Future Document Benefits

- **Clear Roadmap**: Shows LLM enhancement vision
- **Realistic Scope**: Positioned as developer assistance, not replacement
- **Foundation Ready**: Builds on established extraction infrastructure
- **Innovation Space**: Room for advanced LLM integration experiments

---

This plan provides a clear path to resolve the philosophical contradictions while preserving all valuable technical content and establishing a solid foundation for future LLM-assisted capabilities. 