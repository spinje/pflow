# Planner Specification Update Plan

**Date**: Current Planning Session  
**Objective**: Completely rewrite `planner-responsibility-functionality-spec.md` to be consistent with shared store specifications and integrate new architectural insights

---

## Executive Summary

The current planner specification uses incompatible terminology and architectural assumptions. This plan outlines a complete rewrite that:
- Adopts the shared store model (`params`, shared store keys, `mappings`)
- Integrates action-based flow control
- Defines the LLM-based node/flow selection process
- Establishes proper separation between planner, compiler, and runtime
- Implements validation-first approach throughout

---

## Key Architectural Changes

### 1. **Pipeline Restructure**
**Old**: `Prompt → Planner → Execution DAG`  
**New**: `Prompt → Planner (JSON IR) → Compiler (CLI + Code) → Runtime (Shared Store)`

### 2. **Terminology Migration**
- Remove: `input_bindings`, `config`, `pipe preview`, `derived snapshot`
- Add: `params`, `shared store keys`, `mappings`, `action-based transitions`, `metadata JSON`

### 3. **Validation Philosophy**
- From: Validation gates at end
- To: Validation at every step ("early and often")

### 4. **LLM Integration**
- Add: Metadata-driven node/flow selection
- Add: Thinking model approach for composition decisions

---

## Detailed Section-by-Section Update Plan

### Section 1: Purpose
**Status**: Minor updates needed  
**Changes**:
- Keep core purpose: NL prompt → validated, deterministic flow
- Update terminology: Remove "pipe" references, add "JSON IR"
- Emphasize integration with shared store pattern

### Section 2: Architectural Position  
**Status**: Complete rewrite needed  
**New Content**:
```
Prompt → LLM Selection → IR Generation → Validation → Compilation → Execution
```
- Show planner generates JSON IR, not execution code
- Show compiler as separate stage (IR → CLI syntax + Python code)
- Show runtime using shared store pattern
- Emphasize planner as pocketflow flow itself

### Section 3: Core Responsibilities
**Status**: Complete restructure needed  
**New Stages**:
1. **Node/Flow Discovery** - Extract metadata JSON from Python classes
2. **LLM Selection** - Use thinking model to choose nodes/flows from metadata
3. **Flow Structure Generation** - Create node graph with action-based transitions
4. **Structural Validation** - Lint node compatibility, action paths, reachability
5. **Shared Store Modeling** - Create shared store schema, generate mappings if needed
6. **Type/Interface Validation** - Validate shared store key compatibility
7. **IR Finalization** - Generate validated JSON IR with default params
8. **Compilation Handoff** - Pass IR to compiler for CLI syntax generation
9. **User Verification** - Show compiled CLI pipe for user approval
10. **Execution Handoff** - Save lockfile, execute via runtime

### Section 4: Node/Flow Discovery (NEW)
**Content to Add**:
- Metadata extraction from Python class docstrings/annotations
- JSON schema for node metadata (`id`, `description`, `inputs`, `outputs`, `params`, `actions`)
- Flow metadata structure (includes `sub_nodes`)
- Registry management and updates

### Section 5: LLM Selection Process (NEW)
**Content to Add**:
- Thinking model approach
- Metadata JSON in context window
- Selection criteria (exact match flows vs. composition)
- Handling sub-flow reuse
- Fallback strategies for unknown requests

### Section 6: Flow Structure Generation (REVISED)
**Replace "Generation Logic" with**:
- Action-based transition syntax (`node_a >> node_b`, `node_a - "action" >> node_b`)
- Branch/loop/multi-step flow patterns
- IR representation of transitions (omit `"action": "default"`)
- Structural validation of flow graph

### Section 7: Validation Framework (NEW)
**Content to Add**:
- "Validation at every step" principle
- Structural validation (node existence, action definitions, reachability)
- Interface validation (shared store key compatibility)
- Mapping requirement detection
- Early error detection and retry logic

### Section 8: Shared Store Integration (NEW)
**Content to Add**:
- Natural interface detection (what shared store keys nodes expect)
- Mapping generation rules (only when node keys incompatible)
- Proxy pattern integration
- Parameter defaults vs. runtime overrides

### Section 9: Parameter Resolution (REVISED)
**Replace current section with**:
- Default params embedded in IR (no resolution during planning)
- Runtime CLI flag resolution using shared store rules
- Future: Planning-time param customization (post-MVP)
- Clear separation of planner vs. runtime responsibilities

### Section 10: IR Schema and Compilation (NEW)
**Content to Add**:
- Complete JSON IR schema definition
- Integration with compiler stage
- Lockfile signature system
- Version consistency checking

### Section 11: User Experience Flow (REVISED)
**Replace current sections with**:
- CLI pipe syntax display (not IR JSON)
- User approval/modification process
- Future: Mermaid diagrams, visual frontend
- Error reporting and retry workflows

### Section 12: Integration with Runtime (NEW)
**Content to Add**:
- Handoff to shared store runtime
- pocketflow framework integration
- NodeAwareSharedStore proxy usage
- CLI flag resolution at execution time

### Section 13: Error Handling and Codes (REVISED)
**Update error taxonomy**:
- Align with shared store validation rules
- Add new error types (metadata issues, action validation, interface mismatches)
- Remove binding-related errors
- Integrate with compiler and runtime error codes

### Section 14: Caching and Performance (REVISED)
**Content Updates**:
- Flow-hash calculation (nodes + mappings + action-transitions)
- Integration with node-level caching (`@flow_safe`)
- Metadata caching for performance
- LLM response caching strategies

### Section 15: Logging and Provenance (MINOR UPDATES)
**Align with shared store approach**:
- JSON IR provenance tracking
- Integration with runtime logging
- Metadata version tracking
- LLM selection audit trail

---

## Content to Remove Completely

1. **Pipe Preview Concept** - Replaced by compiler-generated CLI syntax
2. **Binding-centric Language** - `input_bindings`, explicit parameter resolution
3. **Config vs Input_binding Separation** - Unified under params + shared store
4. **Derived Snapshots** - Runtime concern, not planner concern
5. **Direct Execution Handoff** - Planner hands off to compiler, not execution

---

## New Concepts to Introduce

1. **Metadata-Driven Selection** - How LLM chooses from available building blocks
2. **Action-Based Flow Control** - Conditional transitions and branching
3. **Validation-First Approach** - Early and frequent validation throughout process
4. **Compiler Separation** - Clear boundary between IR generation and code generation
5. **Lockfile Signature System** - Version consistency and integrity checking

---

## Integration Points with Shared Store Specs

### Terminology Alignment
- Use exact terminology from shared store specs
- Reference shared store concepts consistently
- Maintain compatibility with proxy pattern

### Validation Rule Integration
- Merge validation rules from both specs
- Establish clear ownership (planner vs. runtime)
- Ensure no conflicts or gaps

### Framework Integration
- Planner as pocketflow flow
- Nodes inherit from pocketflow.Node
- Consistent with 100-line framework philosophy

---

## Document Structure Outline

```markdown
# Planner Responsibility & Functionality Spec

## 1 · Purpose
## 2 · Architectural Position  
## 3 · Core Responsibilities
## 4 · Node/Flow Discovery & Metadata
## 5 · LLM Selection Process
## 6 · Flow Structure Generation
## 7 · Validation Framework
## 8 · Shared Store Integration
## 9 · Parameter and CLI Integration  
## 10 · IR Schema and Compilation
## 11 · User Experience Flow
## 12 · Integration with Runtime
## 13 · Error Handling and Codes
## 14 · Caching and Performance
## 15 · Logging and Provenance
## 16 · Trust Model & Security
## 17 · Metrics and Success Criteria
## 18 · Future Extensibility
## 19 · Glossary
```

---

## Quality Assurance Checklist

### Consistency Verification
- [ ] All terminology matches shared store specs exactly
- [ ] No conflicts with proxy pattern implementation
- [ ] Validation rules properly distributed between planner/runtime
- [ ] Error codes compatible across all specs

### Completeness Check
- [ ] All planner responsibilities clearly defined
- [ ] Integration points with compiler and runtime specified
- [ ] LLM selection process fully documented
- [ ] Action-based flow control completely covered

### Technical Accuracy
- [ ] JSON IR schema is implementable
- [ ] Validation approach is technically sound
- [ ] Integration with pocketflow framework is correct
- [ ] Performance implications are reasonable

### User Experience
- [ ] CLI workflow is clear and intuitive
- [ ] Error messages are helpful and actionable
- [ ] Future extensibility is preserved
- [ ] Developer experience is optimized

---

## Implementation Priority

### Phase 1 (MVP)
- Core planner pipeline (sections 1-3)
- Basic LLM selection (sections 4-5)
- Simple flow generation (section 6)
- Essential validation (section 7)

### Phase 2 (Post-MVP)
- Advanced shared store integration (section 8)
- Parameter customization (section 9)
- Enhanced user experience (section 11)
- Performance optimization (section 14)

### Phase 3 (Future)
- Visual interfaces and diagrams
- Advanced caching strategies
- Remote planner services
- Semantic vector indexing

---

## Success Criteria

1. **Specification Consistency**: Zero conflicts with shared store specs
2. **Implementation Readiness**: All sections have sufficient detail for development
3. **User Clarity**: Non-technical users can understand the planner's role
4. **Developer Productivity**: Technical details enable efficient implementation
5. **Future Flexibility**: Architecture supports planned extensions

---

*End of Update Plan* 