# MVP Scope Consolidation Analysis

## 1. Authoritative MVP Definition

**Primary Source**: `docs/mvp-scope.md` appears to be the canonical MVP definition document. It provides:
- Clear vision and core features
- Explicit inclusion/exclusion lists
- Success criteria and metrics
- Implementation phases
- Detailed acceptance criteria

## 2. MVP Boundary Descriptions Across Documents

### 2.1 docs/mvp-scope.md (Canonical)
**Core MVP Features:**
1. Natural Language Planning Engine (built after core infrastructure)
2. Developer-Focused Node Registry with simple nodes
3. CLI Execution & Workflow Management
4. Foundation Infrastructure (pocketflow, JSON IR, validation)

**Explicitly Excluded:**
- Conditional transitions (v2.0)
- CLI autocomplete (v2.0)
- Shadow store (v2.0)
- Interactive prompts (v2.0)
- MCP node integration (v2.0)
- Multi-user auth (v3.0)
- Web UI (v3.0)
- Distributed execution (v3.0)

### 2.2 docs/prd.md (Master Edition)
**MVP Approach:**
- Section 2: "Out-of-Scope for MVP" lists exclusions
- Sections throughout reference "post-MVP" features
- Appendix includes glossary defining MVP boundaries

**Duplications with mvp-scope.md:**
- Auto-generating node code (excluded)
- GUI authoring (excluded)
- Mid-run user interaction (excluded)
- CLI flow search (excluded)

**Unique MVP Content:**
- Detailed technical implementation specs
- Performance targets
- Trust model specifics

### 2.3 docs/architecture.md
**MVP Focus Statement:**
"This document describes the architecture for pflow v0.1 MVP, which prioritizes:
- Local-first CLI execution
- Manual node composition via CLI pipe syntax
- Simple shared store pattern implementation
- Deterministic, reproducible execution"

**Clear Delineation:**
- Section 4: "MVP Scope Definition" with included/excluded lists
- Notes that NL planning is "included in MVP but built after core infrastructure"

**Duplications:**
- Lists same v2.0 exclusions (conditional transitions, async, autocomplete)
- Lists same v3.0 exclusions (cloud, auth, web UI)

### 2.4 docs/components.md
**Purpose:** Component inventory clearly distinguishing MVP vs v2.0

**Structure:**
- "MVP (v0.1) Components" section
- Each component marked with purpose and subcomponents
- Clear separation from v2.0 features

**Unique Value:**
- Detailed component breakdown not found elsewhere
- Clear implementation checklist format

### 2.5 docs/registry.md
**MVP References:**
- Pre-release versions "not supported in MVP"
- Version resolution policies for MVP
- Simple node naming conventions for MVP

**Overlap:**
- References same simple node philosophy as mvp-scope.md

### 2.6 docs/planner.md
**MVP Context:**
- Describes planner as core MVP component
- References template-driven workflows as MVP feature
- Shadow store mentioned as "CLI Path Enhancement"

**Potential Conflict:**
- Shadow store mentioned here but excluded in mvp-scope.md

### 2.7 docs/mcp-integration.md
**Clear Statement:**
- Title indicates this is for MCP integration
- No explicit MVP/v2.0 labeling in header
- Content suggests this is post-MVP

**Needs Clarification:**
- Should be clearly marked as v2.0 feature

### 2.8 docs/future-version/*.md
**Clear Labeling:**
- All files properly marked as "Future Feature - Not part of MVP"
- Consistent exclusion from MVP scope

## 3. Conflicts and Inconsistencies

### 3.1 Shadow Store Confusion
- **mvp-scope.md**: Explicitly excludes shadow store (v2.0)
- **planner.md**: Describes "Type Shadow Store Prevalidation" as CLI enhancement
- **Resolution Needed**: Clarify if shadow store is MVP or v2.0

### 3.2 MCP Integration Ambiguity
- **mvp-scope.md**: Clearly states MCP is v2.0
- **mcp-integration.md**: No clear version labeling
- **Resolution Needed**: Add version headers to mcp-integration.md

### 3.3 Natural Language Planning Timeline
- **mvp-scope.md**: "Built After Core Infrastructure"
- **architecture.md**: "included in MVP but built after core infrastructure"
- **Consistent but needs emphasis**: Both agree but could be clearer

## 4. Consolidation Strategy

### 4.1 Immediate Actions

1. **Centralize MVP Definition**:
   - Keep `mvp-scope.md` as the single source of truth
   - Add clear references from other docs: "For MVP boundaries, see mvp-scope.md"

2. **Add Version Headers**:
   ```markdown
   # Component Name

   > **Version**: MVP | v2.0 | v3.0
   > **Status**: Included in MVP | Deferred to v2.0 | Future Enhancement
   ```

3. **Create MVP Checklist**:
   - Extract all MVP components from docs
   - Create single checklist in mvp-scope.md
   - Reference from implementation docs

### 4.2 Document Updates Needed

1. **prd.md**:
   - Add reference to mvp-scope.md in Section 2
   - Move detailed MVP boundaries to reference canonical doc

2. **architecture.md**:
   - Replace Section 4 content with reference to mvp-scope.md
   - Keep architecture-specific MVP notes only

3. **planner.md**:
   - Clarify shadow store status (likely needs to be v2.0)
   - Add version header

4. **mcp-integration.md**:
   - Add clear "Version: v2.0" header
   - Note dependencies on MVP completion

5. **components.md**:
   - Already well-structured
   - Add reference to mvp-scope.md for authoritative list

### 4.3 Recommended Structure

```
mvp-scope.md (Canonical MVP Definition)
├── Vision & Goals
├── Core Features (MVP)
├── Deferred Features (v2.0)
├── Future Features (v3.0)
├── Implementation Phases
├── Success Criteria
└── Component Checklist (NEW)

Other Docs:
- Reference mvp-scope.md for boundaries
- Focus on their specific domain
- Use consistent version headers
```

## 5. Key Findings

1. **mvp-scope.md is the authoritative source** and should be referenced by all other documents

2. **Most documents are consistent** but use different levels of detail

3. **Main conflicts**:
   - Shadow store status needs clarification
   - MCP documents need version headers
   - Some duplication could be reduced

4. **Recommendation**:
   - Centralize all MVP boundary definitions in mvp-scope.md
   - Other docs should reference it rather than duplicate
   - Use consistent version headers across all docs
   - Create a single MVP component checklist

## 6. Proposed Next Steps

1. Update mvp-scope.md with complete component checklist
2. Add version headers to all component docs
3. Replace duplicate MVP listings with references
4. Clarify shadow store and MCP status
5. Create a simple visual/diagram showing MVP vs v2.0 vs v3.0 boundaries
