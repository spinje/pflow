# Duplication Analysis Report

## Executive Summary

After comprehensive analysis of the pflow documentation, I've identified significant content duplication across 5 major categories. Approximately 30-40% of technical content appears in multiple locations with varying levels of detail, creating maintenance burden and potential for inconsistency.

## Major Areas of Duplication

### 1. Node Lifecycle and Patterns (~35% duplication)

**Concept**: Node lifecycle (prep/exec/post) and implementation patterns
**Primary appearances**:
- `shared-store.md` - Lines 220-229, 266-292
- `runtime.md` - Lines 34-47
- `architecture.md` - Lines 93-96, 347-368
- `pflow-pocketflow-integration-guide.md` - Lines 35-47
- `simple-nodes.md` - Lines 70-95

**Issues**:
- Same LLMNode example appears 3 times with minor variations
- "What pocketflow provides" list duplicated verbatim in 2 files
- Node lifecycle explanation repeated 4+ times

### 2. CLI Syntax and Operators (~25% duplication)

**Concept**: CLI pipe syntax, `>>` operator, command structure
**Primary appearances**:
- `cli-runtime.md` - Throughout, especially lines 18-19, 258, 282
- `architecture.md` - Lines 13, 28, 171, 247, 256
- `registry.md` - Lines 214, 222, 225, 228
- `shell-pipes.md` - Entire document
- `workflow-analysis.md` - Multiple examples

**Issues**:
- Basic command structure explained 4+ times
- `>>` operator purpose described in 7+ files
- Shell pipe integration has dedicated doc plus 3+ other explanations

### 3. JSON IR Schemas (~40% duplication)

**Concept**: Flow IR structure, node metadata, validation schemas
**Primary appearances**:
- `schemas.md` - Complete definitions (lines 14-401)
- `planner.md` - Lines 560-600 (Flow IR)
- `cli-runtime.md` - Multiple examples (lines 163-186, 239-317)
- `registry.md` - Lines 146-154, 334-342
- `implementation-details/metadata-extraction.md` - Lines 226-254

**Issues**:
- Node metadata schema appears 5+ times
- Flow IR envelope structure in 3+ files
- Edge and mapping schemas duplicated with variations

### 4. Execution Model (~30% duplication)

**Concept**: Runtime behavior, caching, error handling, validation
**Primary appearances**:
- `runtime.md` - Primary definition (lines 1-309)
- `architecture.md` - Lines 413-454, 574-588
- `components.md` - Lines 163-196
- `planner.md` - Lines 802-874
- `schemas.md` - Lines 346-368

**Issues**:
- Cache key formula appears identically in 4 files
- Failure semantics in runtime.md and schemas.md
- Error handling strategies repeated 3+ times

### 5. Shared Store Pattern (~20% duplication)

**Concept**: Inter-node communication, template variables, key patterns
**Primary appearances**:
- `shared-store.md` - Canonical source
- `architecture.md` - Overview and examples
- `cli-runtime.md` - Runtime behavior
- Various node package docs - Implementation examples

**Issues**:
- "Check shared first, then params" pattern repeated 5+ times
- Template variable system explained in multiple contexts

## Cross-Cutting Duplications

### Example Workflows
The GitHub issue fix workflow appears in:
- `workflow-analysis.md` - Complete analysis
- `architecture.md` - Simplified version
- `prd.md` - Conceptual overview
- `cli-runtime.md` - Implementation example

### PocketFlow Integration
Explanations of what pocketflow provides and how pflow uses it:
- `pflow-pocketflow-integration-guide.md` - Dedicated guide
- `runtime.md` - Integration aspects
- `architecture.md` - Overview
- `shared-store.md` - Pattern integration

## Impact Analysis

### Maintenance Burden
- **High**: JSON schemas need updates in 5+ places
- **Medium**: CLI syntax changes affect 7+ files
- **Medium**: Runtime behavior updates needed in 4+ files

### Confusion Risk
- Readers find different explanations for same concepts
- Version conflicts (e.g., shadow store MVP vs v2.0)
- Incomplete information in secondary sources

### Documentation Debt
- ~1,500-2,000 lines of duplicated content
- 30-40% of technical content appears multiple times
- Inconsistent detail levels across duplications

## Recommendations

1. **Create dedicated reference documents**:
   - `node-reference.md` - Canonical node patterns
   - `cli-reference.md` - Complete CLI syntax guide
   - `execution-reference.md` - Runtime behavior spec

2. **Enforce single-source principle**:
   - JSON schemas only in `schemas.md`
   - Runtime behavior only in `runtime.md`
   - CLI syntax only in new `cli-reference.md`

3. **Convert duplications to cross-references**:
   - Replace inline examples with links
   - Use brief summaries + "See [doc] for details"
   - Maintain only essential context in each doc

4. **Extract standalone concepts**:
   - Template variables → own section in shared-store.md
   - Cache key computation → runtime.md only
   - Node lifecycle → node-reference.md

## Priority Order

1. **Highest**: JSON IR schemas (most duplicated)
2. **High**: CLI syntax and operators
3. **High**: Node lifecycle patterns
4. **Medium**: Execution model details
5. **Medium**: Example workflows
