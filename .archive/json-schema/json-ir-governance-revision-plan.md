# JSON IR Governance Revision Plan

## Overview

This plan outlines the comprehensive revision needed for the JSON IR Governance document to align with pflow's established architecture while maintaining its unique focus on IR schema definition, validation, and evolution.

---

## Core Revision Principles

### 1. Scope Refinement
**Focus**: JSON IR schema structure, validation rules, and evolution governance
**Avoid**: Duplicating architectural concepts covered in other specifications
**Reference**: Link to authoritative documents rather than restating their content

### 2. Architectural Alignment
**Ensure**: All IR examples use natural interfaces and established patterns
**Integrate**: Proxy mappings, action-based transitions, and pocketflow compatibility
**Maintain**: Consistency with planner, runtime, and CLI specifications

### 3. Schema Standardization
**Standardize**: Field naming to match established IR schema from planner spec
**Validate**: All examples work with actual pflow implementation
**Document**: Extension points for future IR evolution

---

## Section-by-Section Revision Plan

### Section 1: Document Envelope ✅ (Minor Updates)
**Current Status**: Generally aligned
**Required Changes**:
- Update `locked_nodes` structure to match versioning spec format
- Add reference to registry integration from node discovery doc
- Clarify relationship to execution lockfiles vs version lockfiles

**Example Revision**:
```json
{
  "$schema": "https://pflow.dev/schemas/flow-0.1.json",
  "ir_version": "0.1.0",
  "metadata": {
    "created": "2025-05-27T16:00:15Z",
    "description": "weather → summary flow",
    "planner_version": "1.0.0",
    "locked_nodes": {
      "core/fetch_url": "1.2.4",
      "mcp/weather.get": "0.3.2"
    }
  }
}
```

### Section 2: Node Object 🔄 (Major Revision Required)
**Current Status**: Field naming inconsistencies and architectural contradictions
**Required Changes**:

#### 2.1 Field Standardization
**Problem**: Inconsistent field names throughout
**Solution**: Align with planner specification schema

**Before**:
```json
{
  "id": "a1",
  "type": "mcp/weather.get@0.3.2",
  "exec": {
    "retries": 2,
    "use_cache": true
  }
}
```

**After**:
```json
{
  "id": "weather-fetch",
  "version": "0.3.2",
  "params": {
    "city": "Stockholm",
    "api_key": null
  },
  "execution": {
    "max_retries": 2,
    "use_cache": true
  }
}
```

#### 2.2 Natural Interface Documentation
**Add**: Reference to natural interface pattern from shared store docs
**Include**: How nodes use `shared["key"]` directly, not through params
**Clarify**: Distinction between params (behavior) and shared store keys (data flow)

### Section 3: Edge Object ✅ (Add Action-Based Transitions)
**Current Status**: Basic edges only
**Required Changes**:
- Add action-based transition support
- Include conditional flow control examples
- Reference planner spec for flow structure details

**Enhanced Schema**:
```json
[
  {"from": "validator", "to": "processor"},
  {"from": "validator", "to": "error_handler", "action": "fail"},
  {"from": "processor", "to": "validator", "action": "continue"},
  {"from": "processor", "to": "finalizer"}
]
```

### Section 4: Shared-Store Bindings 🚫 (Complete Rewrite Required)
**Current Status**: Fundamentally contradicts architecture
**Problem**: Claims nodes declare keys via params
**Solution**: Complete rewrite to align with natural interface pattern

#### 4.1 New Focus: Proxy Mappings
**Replace**: Parameterized key system
**With**: Flow-level mapping system for complex routing

**New Content Structure**:
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

#### 4.2 Natural Interface Reference
**Add**: Clear reference to shared store architecture document
**Explain**: How IR mappings integrate with `NodeAwareSharedStore` proxy
**Clarify**: Mappings are optional - nodes use natural interfaces by default

### Section 5: Side-Effect Model 🔄 (Align with Runtime Spec)
**Current Status**: Mentions purity but incomplete
**Required Changes**:
- Reference runtime behavior specification for complete model
- Focus on IR representation of `@flow_safe` status
- Remove redundant content covered in runtime spec

**Revised Content**:
```markdown
### Side-Effect Model

Node purity status is determined by `@flow_safe` decorator (see [Runtime Behavior Specification](./runtime-behavior-specification.md)). IR reflects this through execution configuration eligibility:

- Only `@flow_safe` nodes may specify `max_retries > 0`
- Only `@flow_safe` nodes may specify `use_cache: true`
- IR validation enforces these constraints during planner validation phase
```

### Section 6: Failure Semantics ✅ (Minor Updates)
**Current Status**: Generally aligned
**Required Changes**:
- Update field name from `retries` to `max_retries`
- Reference runtime spec for complete failure handling
- Clarify integration with pocketflow framework

### Section 7: Caching Contract 🔄 (Reference Runtime Spec)
**Current Status**: Duplicates runtime specification content
**Required Changes**:
- Reduce to IR-specific concerns only
- Reference runtime spec for implementation details
- Focus on IR validation of cache eligibility

**Simplified Content**:
```markdown
### Caching Contract

IR enables caching through `execution.use_cache` field. Validation rules:
- Only `@flow_safe` nodes may specify `use_cache: true`
- Cache eligibility determined at runtime (see [Runtime Behavior Specification](./runtime-behavior-specification.md))
- IR validation occurs during planner pipeline
```

### Section 8: Validation Pipeline ✅ (Expand Integration)
**Current Status**: Good foundation
**Required Changes**:
- Add planner integration details
- Include proxy mapping validation
- Add action-based transition validation
- Reference framework compatibility checks

**Enhanced Validation Steps**:
1. JSON parse → strict no-comments
2. `$schema` + `ir_version` check
3. Node identifier resolution against registry
4. Cycle detection in `edges` including action-based paths
5. Natural interface compatibility validation
6. Proxy mapping validation (when present)
7. `@flow_safe` constraint validation for execution config
8. pocketflow framework compatibility check

### Section 9: Evolution Rules ✅ (Maintain)
**Current Status**: Well-defined
**Required Changes**: Minor updates for consistency

### Section 10: Extension Points ✅ (Expand)
**Current Status**: Basic framework
**Required Changes**:
- Add mappings extension for complex routing
- Add action-based transition extensions
- Add planner integration extensions

### Section 11: Minimal Example Flow ✅ (Major Revision)
**Current Status**: Uses contradictory architecture
**Required Changes**: Complete rewrite using natural interfaces

**Revised Example**:
```json
{
  "$schema": "https://pflow.dev/schemas/flow-0.1.json",
  "ir_version": "0.1.0",
  "metadata": {
    "description": "YouTube video summary pipeline",
    "planner_version": "1.0.0",
    "locked_nodes": {
      "core/yt-transcript": "1.0.0",
      "core/summarize-text": "2.1.0"
    }
  },
  "nodes": [
    {
      "id": "fetch-transcript",
      "version": "1.0.0",
      "params": {"language": "en"},
      "execution": {"max_retries": 2}
    },
    {
      "id": "create-summary",
      "version": "2.1.0",
      "params": {"temperature": 0.7},
      "execution": {"use_cache": true}
    }
  ],
  "edges": [
    {"from": "fetch-transcript", "to": "create-summary"}
  ]
}
```

---

## New Sections to Add

### Add: Proxy Mapping Schema
**Purpose**: Document optional mapping system for complex flows
**Content**: Schema for `mappings` section, validation rules, proxy integration
**Reference**: Shared store architecture document for conceptual background

### Add: Action-Based Transitions
**Purpose**: Document conditional flow control in IR
**Content**: Action syntax, validation rules, flow graph implications
**Reference**: Planner specification for flow structure generation

### Add: Framework Integration
**Purpose**: Document pocketflow compatibility requirements
**Content**: Execution pattern expectations, node inheritance requirements
**Reference**: Shared store documents for implementation details

### Add: CLI Integration Points
**Purpose**: Document how IR supports CLI parameter resolution
**Content**: Natural interface CLI mapping, param override support
**Reference**: CLI runtime specification for complete resolution algorithm

---

## Content to Remove

### Remove: Redundant Architecture Descriptions
**Rationale**: Covered comprehensively in other specifications
**Examples**:
- Node interface patterns (defer to shared store docs)
- Planner operation details (defer to planner spec)
- Runtime behavior details (defer to runtime spec)

### Remove: Contradictory Examples
**Remove**: All examples using parameterized key system
**Replace**: Examples using natural interfaces with optional mappings

### Remove: Implementation Details
**Remove**: Specific implementation algorithms
**Keep**: IR schema and validation rules only
**Reference**: Other documents for implementation specifics

---

## Quality Assurance Checklist

### Architectural Consistency
- [ ] All examples use natural interfaces (`shared["key"]`)
- [ ] Proxy mappings documented as optional flow-level concern
- [ ] No contradiction with established shared store pattern
- [ ] Field naming consistent with planner specification

### Framework Integration
- [ ] pocketflow execution patterns referenced appropriately
- [ ] Node inheritance requirements documented
- [ ] Execution configuration aligns with framework capabilities

### Specification Harmony
- [ ] No duplication of content from other documents
- [ ] Appropriate cross-references to authoritative sources
- [ ] Clear scope boundaries maintained

### Validation Completeness
- [ ] All IR schema elements validated
- [ ] Action-based transitions included in validation
- [ ] Proxy mapping validation documented
- [ ] Framework compatibility checks included

---

## Implementation Priority

### Phase 1: Critical Fixes (Immediate)
1. Rewrite Section 4 (Shared-Store Bindings)
2. Fix field naming inconsistencies throughout
3. Update minimal example to use natural interfaces
4. Add proxy mapping documentation

### Phase 2: Integration Enhancement (Short-term)
1. Add action-based transition support
2. Enhance validation pipeline with planner integration
3. Add framework compatibility requirements
4. Clean up redundant content with proper references

### Phase 3: Polish and Extension (Medium-term)
1. Add comprehensive extension points
2. Enhance error handling documentation
3. Add advanced validation scenarios
4. Create comprehensive cross-reference index

---

## Success Criteria

The revised JSON IR Governance document will be considered successful when:

1. **Zero Contradictions**: No content contradicts other pflow specifications
2. **Clear Scope**: Focuses on IR-specific concerns without duplication
3. **Complete Schema**: All IR elements properly documented and validated
4. **Implementation Ready**: Examples work with actual pflow implementation
5. **Future Proof**: Extension points support planned architectural evolution

---

This revision plan ensures the JSON IR Governance document becomes a focused, non-contradictory specification that properly integrates with pflow's established architecture while maintaining its unique role in IR schema governance.
