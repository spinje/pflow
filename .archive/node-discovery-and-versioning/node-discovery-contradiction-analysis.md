# Node Discovery Documentation - Contradiction Analysis

**Date**: Current Analysis  
**Source Documents**: `shared-store-node-proxy-architecture.md`, `planner-responsibility-functionality-spec.md`, `shared-store-cli-runtime-specification.md`  
**Target Document**: `node-discovery-namespacing-and-versioning.md`

---

## Executive Summary

The node discovery document contains **several significant contradictions** with the established source documents, particularly around IR schema structure, node identification, and CLI integration patterns. These contradictions would prevent proper integration between the discovery/versioning system and the core planner/runtime architecture.

---

## Critical Contradictions Found

### 1. **IR Schema Conflict** - CRITICAL

**Source Documents**:
```json
{
  "nodes": [
    {"id": "yt-transcript", "params": {"language": "en"}},
    {"id": "summarize-text", "params": {"temperature": 0.7"}}
  ]
}
```

**Node Discovery Document**:
```json
{
  "nodes": [
    {"id": "a", "type": "core/summarize@0.9.1", "params": {...}},
    {"id": "b", "type": "core/save_file@1.0.0", "params": {...}}
  ]
}
```

**Impact**: Fundamental incompatibility in IR structure. Source documents use `id` as the node type identifier, while node discovery introduces separate `id` (instance) and `type` (qualified name) fields.

**Resolution Required**: Choose one consistent schema throughout all documents.

### 2. **Node Naming Convention Conflict** - HIGH

**Source Documents**: 
- Use kebab-case: `yt-transcript`, `summarize-text`, `store-markdown`
- CLI examples: `pflow yt-transcript --url=X >> summarize-text`

**Node Discovery Document**:
- Uses snake_case: `fetch_url`, `summarize`, `save_file`  
- CLI examples: `pflow fetch_url --url https://example.com >> summarize >> save_file`

**Impact**: Inconsistent naming makes examples non-functional and creates confusion about the canonical format.

### 3. **CLI Resolution vs Planner Integration** - HIGH

**Source Documents**:
- Planner performs node discovery and validation
- Two entry points: Natural Language → Planner selection, CLI Pipe → Planner validation
- Node registry used by planner for metadata-driven selection

**Node Discovery Document**:
- Implies CLI resolution happens independently before planning
- Resolution algorithm operates on CLI syntax directly
- No mention of planner integration for node validation

**Impact**: Unclear where version resolution fits in the planner → compiler → runtime pipeline.

### 4. **Metadata Schema Integration Gap** - MEDIUM

**Source Documents**:
```json
{
  "id": "yt-transcript",
  "description": "Fetches YouTube transcript from video URL",
  "inputs": ["url"],
  "outputs": ["transcript"],
  "params": {"language": "en"},
  "version": "1.0.0"
}
```

**Node Discovery Document**:
- Defines namespaced identifiers: `core/fetch_url@1.0.0`
- No specification of how metadata extraction works with namespaced nodes
- Missing integration with planner's metadata-driven selection process

**Impact**: Cannot connect the versioning system to the planner's LLM selection capabilities.

### 5. **Lockfile Purpose Confusion** - MEDIUM

**Source Documents**:
- Focus on execution lockfiles containing validated IR with signatures
- Lockfiles ensure reproducible execution of planned flows
- Generated after planner validation completes

**Node Discovery Document**:
- Focus on version resolution lockfiles: `{"core/fetch_url": "1.2.4"}`
- Lockfiles used for CLI disambiguation and version pinning
- Generated via `pflow lock` command independently

**Impact**: Two different lockfile concepts serving different purposes without clear relationship.

---

## Minor Inconsistencies

### 6. **Framework Integration Omission** - LOW

**Source Documents**: Consistently specify that nodes must inherit from `pocketflow.Node`

**Node Discovery Document**: No mention of framework inheritance requirements or integration patterns.

### 7. **Natural Interface Pattern Missing** - LOW

**Source Documents**: Emphasize natural interfaces (`shared["text"]`) as core to the standalone node pattern

**Node Discovery Document**: No mention of natural interface expectations or shared store integration.

---

## Integration Architecture Issues

### 8. **Planner Pipeline Integration Unclear**

The source documents establish a clear pipeline:
```
Prompt → Planner (Node Selection) → IR Generation → Compiler → Runtime
```

The node discovery document doesn't specify:
- Where version resolution occurs in this pipeline
- How namespaced identifiers integrate with planner metadata
- Whether resolution happens before or after planner validation

### 9. **Registry vs Discovery Relationship**

**Source Documents**: Reference a "node registry" used by the planner for metadata-driven selection

**Node Discovery Document**: Describes file-system based discovery and installation but doesn't connect to the registry concept.

---

## Recommendations for Resolution

### High Priority Fixes

1. **Standardize IR Schema**: Choose either `id`-only or `id`+`type` pattern consistently
2. **Align Naming Conventions**: Use either kebab-case or snake_case throughout
3. **Integrate with Planner Pipeline**: Specify where version resolution occurs in planner → compiler → runtime flow
4. **Connect Metadata Systems**: Show how namespaced nodes integrate with planner metadata extraction

### Medium Priority Fixes

1. **Clarify Lockfile Types**: Distinguish version lockfiles from execution lockfiles
2. **Specify Framework Requirements**: Document pocketflow integration requirements
3. **Add Natural Interface Requirements**: Specify shared store expectations for discovered nodes

### Architecture Decisions Needed

1. **Version Resolution Timing**: Before planner (affects selection) or after planner (affects compilation)?
2. **Registry Implementation**: File-system discovery vs. in-memory registry vs. hybrid?
3. **CLI Shorthand Support**: How do simplified node names work with the planner's validation requirements?

---

## Specific Integration Conflicts

### Conflict A: Node Selection Process

**Source Documents**: LLM selects from metadata JSON loaded into context
**Node Discovery**: CLI resolution chooses nodes via filesystem lookup

**Question**: How does the planner's LLM selection work with versioned, namespaced nodes? Does it see all versions or just one?

### Conflict B: Validation Timing

**Source Documents**: Planner validates node compatibility and generates mappings
**Node Discovery**: Resolution algorithm validates version availability

**Question**: If version resolution fails, does it abort before planner runs, or does planner handle version conflicts?

### Conflict C: Natural Language Path

**Source Documents**: Natural language → planner selects appropriate nodes
**Node Discovery**: No mention of how natural language requests map to namespaced identifiers

**Question**: When user says "summarize video", how does the system select `core/summarize@1.0.0` vs `mcp/openai.summarize@2.1.0`?

---

## Conclusion

The node discovery document introduces valuable versioning and namespacing concepts but requires significant integration work to align with the established planner/runtime architecture. The IR schema conflict is particularly critical and must be resolved before implementation can proceed.

The documents appear to have been written independently without cross-referencing, resulting in incompatible assumptions about system architecture and data flow.

**Recommendation**: Update the node discovery document to integrate with the planner pipeline and resolve IR schema conflicts before proceeding with implementation. 