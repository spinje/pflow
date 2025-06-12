# Consistency Analysis: Planner vs Shared Store Specifications

**Date**: Current Analysis
**Documents Analyzed**:
- `planner-responsibility-functionality-spec.md`
- `shared-store-cli-runtime-specification.md`
- `shared-store-node-proxy-architecture.md`

---

## Executive Summary

This analysis identifies **critical inconsistencies** between the planner specification and the shared store specifications that need resolution before implementation. The primary issues center around **terminology conflicts**, **different data structure assumptions**, and **misaligned parameter handling approaches**.

---

## Critical Inconsistencies Found

### 1. **CRITICAL: Terminology Conflict - `config` vs `params`**

**Issue**: Fundamental mismatch in parameter terminology and structure.

**Planner Spec Uses**:
- `input_bindings` - for required data values
- `config` - for node behavior settings
- Treats these as separate concepts with different validation rules

**Shared Store Specs Use**:
- `params` - for all node behavior settings (flat structure)
- `mappings` - for key translation in proxy pattern
- Shared store keys - for data flow between nodes

**Impact**: **BLOCKING** - These represent completely different mental models for how node parameters work.

**Examples**:
```
Planner: "config value unspecified" → "Node knob undefined & no default"
Shared Store: self.params.get("temperature", 0.7) → flat params access
```

---

### 2. **CRITICAL: Parameter Resolution Model Mismatch**

**Issue**: Conflicting approaches to parameter handling and CLI integration.

**Planner Model**:
- Separates `input_bindings` (data) from `config` (behavior)
- `input_bindings` missing → blocks execution
- `config` changes never alter DAG hash
- Uses "derived snapshot" for runtime overrides

**Shared Store Model**:
- Uses flat `params` structure via `self.params.get()`
- CLI flags auto-resolve to shared store data OR params overrides
- Params changes don't affect graph hash but create new cache entries
- No concept of "input_bindings" separate from shared store keys

**Impact**: **BLOCKING** - Cannot implement both approaches simultaneously.

---

### 3. **MAJOR: IR Structure and Compilation Assumptions**

**Issue**: Different assumptions about what IR contains and how it's processed.

**Planner Assumes**:
- IR contains "bindings, purity flags, semver pins"
- Pipe→IR compilation as separate step (3.5)
- IR validation gates as final step (3.6)
- Lock file stores "pipe/IR only"

**Shared Store IR Example**:
```json
{
  "nodes": [{"id": "yt-transcript", "params": {"language": "en"}}],
  "edges": [{"from": "yt-transcript", "to": "summarise-text"}],
  "mappings": {"yt-transcript": {"input_mappings": {"url": "video_source"}}}
}
```

**Gap**: Planner spec doesn't mention `mappings` structure, which is central to shared store proxy pattern.

---

### 4. **MAJOR: CLI Flag Resolution Logic Conflict**

**Issue**: Incompatible approaches to CLI flag interpretation.

**Planner Logic**:
1. Parameter resolution happens during planning phase
2. "User-supplied CLI flag collides with planner value" → "CLI flag overrides"
3. Override recorded in "derived snapshot"

**Shared Store Logic**:
1. CLI resolution happens at runtime
2. "Flags that match any node's natural interface are data injections"
3. "All others are params overrides"
4. Single-rule resolution: "Type flags; engine decides"

**Impact**: These are mutually incompatible resolution strategies.

---

### 5. **MODERATE: Flow Execution Integration Gap**

**Issue**: Planner spec doesn't account for proxy pattern execution model.

**Missing in Planner**:
- How planner-generated IR integrates with NodeAwareSharedStore proxy
- Whether planner needs to generate mapping definitions
- How planner validates proxy mapping compatibility

**Shared Store Reality**:
- Generated flow code may need proxy setup per node
- Mappings are flow-level concern requiring orchestration
- Natural interface validation needs proxy awareness

---

### 6. **MODERATE: Validation Rules Overlap and Conflicts**

**Issue**: Some validation rules conflict between specifications.

**Planner Validation Rules**:
1. Shadow type check (bindings only)
2. Pipe→IR compiler must succeed
3. IR lint (schema, syntax)
4. Purity / side-effect compliance
5. Namespace & semver resolution
6. Optional dry-run if `--dry`

**Shared Store Validation Rules**:
1. IR immutability — CLI cannot alter mappings or node set
2. Unknown CLI flag → Abort
3. Missing required data in shared store → Abort
4. `params` always overrideable via `set_params()`
5. `stdin` key reserved; node must handle naturally
6. Mapping targets unique flow-wide
7. Natural interface names should be intuitive
8. Node classes must inherit from `pocketflow.Node`

**Conflicts**:
- Planner allows `config` changes; shared store says `params` always overrideable
- Different error handling for missing parameters
- Overlapping but inconsistent purity/namespace checks

---

### 7. **MODERATE: Framework Integration Mismatch**

**Issue**: Different assumptions about pocketflow framework usage.

**Planner Spec**:
- "The planner is implemented as a normal PocketFlow flow"
- Treats pocketflow as execution environment for planner itself

**Shared Store Specs**:
- "leverages the lightweight pocketflow framework (100 lines of Python)"
- "Node classes inherit from `pocketflow.Node`"
- Uses pocketflow for node execution and flow orchestration

**Gap**: Unclear how planner (as pocketflow flow) generates and validates other pocketflow flows.

---

## Minor Inconsistencies

### 8. Error Code Terminology
- Planner: `MISSING_INPUT`, `MISSING_CONFIG`, `FAIL_VALIDATION`, `AMBIGUOUS_MATCH`
- Shared Store: Generic "Abort" actions
- **Need**: Unified error taxonomy

### 9. Caching Model Details
- Planner: Cache eligibility based on trust level and `@flow_safe`
- Shared Store: Cache key = node-hash ⊕ params ⊕ input data SHA-256
- **Need**: Consistent caching strategy integration

### 10. Logging and Provenance
- Planner: `planner_log.json` with detailed provenance
- Shared Store: No specific logging requirements mentioned
- **Need**: Align logging strategies

---

## Architectural Implications

### The Core Problem
The planner spec assumes a **binding-centric model** where parameters are explicitly declared and resolved during planning. The shared store specs assume a **convention-based model** where nodes use natural interfaces and resolution happens at runtime.

### Resolution Strategy Needed
1. **Choose One Model**: Either binding-centric OR convention-based
2. **Hybrid Approach**: Define clear boundaries between planner concerns and runtime concerns
3. **Unified Terminology**: Establish consistent parameter/data vocabulary

---

## Recommendations

### Immediate Actions Required

1. **Resolve `config` vs `params` terminology** - Choose one term and structure
2. **Align parameter resolution timing** - Planning-time vs runtime resolution
3. **Define IR schema compatibility** - Ensure planner can generate shared store compatible IR
4. **Unify CLI flag resolution** - Single consistent algorithm
5. **Clarify validation rule ownership** - Which rules belong to planner vs runtime

### Strategic Design Questions

1. **Should planner generate mappings?** If so, how does it determine mapping requirements?
2. **How does planner validate proxy compatibility?** Natural interface names vs mapping targets?
3. **What level of pocketflow integration?** Planner as pocketflow flow vs separate tool?

---

## Impact Assessment

**CRITICAL** issues prevent implementation and require design decisions.
**MAJOR** issues cause user confusion and implementation complexity.
**MODERATE** issues create technical debt and maintenance burden.

**Overall Assessment**: Specifications are **NOT READY** for implementation without resolving critical inconsistencies.

---

## Next Steps

1. **Architecture Review Meeting** - Align on parameter model (binding vs convention)
2. **Terminology Standardization** - Update one spec to match the other
3. **Integration Design** - Define planner ↔ shared store interface clearly
4. **Validation Rule Ownership** - Separate planning vs runtime concerns
5. **Update Documentation** - Ensure all three specs use consistent terminology and models

---

*End of Analysis*
