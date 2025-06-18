# Duplicate Content Analysis: prd.md and planner.md

## Analysis Summary

After reviewing both `prd.md` and `planner.md`, I've identified several areas of duplication and content that should be removed or replaced with links to reference documents.

## prd.md - Sections to Remove/Replace

### 1. **Shared Store Pattern Details (Lines 143-217)**
- **Lines 143-217**: The entire section 3.2 "Shared Store Pattern" through 3.4 "Proxy Mapping for Complex Flows"
- **Recommendation**: Replace with brief summary and link to `shared-store.md`
- **Replacement text**:
```markdown
### 3.2 Shared Store Pattern

The **shared store** is pflow's primary innovation—a flow-scoped memory that enables natural node interfaces. For detailed information about the shared store pattern, proxy mappings, and implementation examples, see [Shared Store](./shared-store.md).

**Key Concepts:**
- Primary data flow mechanism between nodes
- Natural, intuitive key naming conventions
- Optional proxy mappings for complex flows
- Clear separation from node parameters
```

### 2. **Planning Pipeline Architecture Details (Lines 316-554)**
- **Lines 355-441**: Detailed tables and process steps in sections 4.2 and 4.3
- **Recommendation**: Keep high-level overview but remove detailed stage tables
- **Replacement**: Link to `planner.md` for implementation details
- **Keep**: The conceptual diagram and key insights

### 3. **JSON IR Schema Details (Lines 804-878)**
- **Lines 834-878**: Detailed node definitions, edge definitions, and proxy mapping schema
- **Recommendation**: Remove detailed JSON examples
- **Replacement text**:
```markdown
### 6.2 Core Schema Components

For detailed schema specifications including node definitions, edge definitions, proxy mappings, and validation rules, see [Schemas](./schemas.md).
```

### 4. **Caching Strategy Implementation (Lines 1015-1055)**
- **Lines 1017-1055**: Detailed cache key computation and behavior
- **Recommendation**: Keep high-level concept, remove implementation details
- **Replacement**: Link to `runtime.md` for detailed caching implementation

### 5. **Metadata-Driven Selection Details (Lines 422-448)**
- **Lines 422-448**: Detailed metadata extraction examples
- **Recommendation**: Keep concept explanation, remove code examples
- **Replacement**: Link to `planner.md` for metadata extraction details

## planner.md - Sections to Remove/Replace

### 1. **Caching Details (Lines 840-874)**
- **Lines 840-874**: Section 14 "Caching and Performance"
- **Recommendation**: Remove entire section
- **Replacement text**:
```markdown
## 14 · Caching and Performance

For detailed information about caching strategies, cache key computation, and performance optimizations, see [Runtime](./runtime.md#caching-strategy).

**Key Integration Points:**
- Planner generates cache-eligible metadata in IR
- Runtime handles actual cache implementation
- Trust model integration affects cache eligibility
```

### 2. **IR Schema Duplication (Lines 560-634)**
- **Lines 567-634**: Detailed JSON IR examples in section 10.1
- **Recommendation**: Keep template-driven aspects, remove duplicate schema
- **Replacement**: Link to `schemas.md` for complete IR schema
- **Keep**: Template string composition and variable flow aspects (unique to planner)

### 3. **Shared Store Integration Details (Lines 447-501)**
- **Lines 447-501**: Section 8 overlaps with shared-store.md
- **Recommendation**: Keep planner-specific integration points
- **Remove**: General shared store explanations and proxy pattern details
- **Replacement**: Reference `shared-store.md` for pattern details

### 4. **Runtime Behavior Duplication (Lines 737-791)**
- **Lines 749-791**: Section 12.2-12.4 duplicates runtime implementation
- **Recommendation**: Keep handoff process description
- **Remove**: Detailed code examples and implementation
- **Replacement**: Link to `runtime.md` and `cli-runtime.md`

## Shadow Store Conflict Status

I checked planner.md for the shadow store conflict that was previously fixed:
- **Lines 117-129**: Contains the proper v2.0 deferral notice
- **Status**: ✅ Already fixed - no action needed

## Recommended Action Order

1. **Start with prd.md** - Remove technical implementation details first
2. **Then update planner.md** - Remove runtime/caching details
3. **Verify all links** - Ensure referenced documents contain the removed content
4. **Update navigation sections** - Make sure cross-references are accurate

## Key Principle

When removing content, always ensure:
1. The authoritative source document exists and is complete
2. Keep conceptual/architectural information in prd.md
3. Move implementation details to component-specific docs
4. Maintain clear navigation and cross-references
