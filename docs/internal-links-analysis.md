# Internal Links Analysis for docs/ Directory

## Summary
Total files with internal links: 28
Total internal links found: 353

## Detailed Analysis by File

### 1. `/docs/index.md` (48 links)
**High-level index file with references to all major documents**
- [Workflow Analysis](./workflow-analysis.md) - 2 occurrences
- [MVP Scope](./mvp-scope.md) - 4 occurrences
- [Architecture](./architecture.md) - 3 occurrences
- [PRD](./prd.md) - 2 occurrences
- [Shared Store](./shared-store.md) - 4 occurrences
- [Simple Nodes](./simple-nodes.md) - 3 occurrences
- [CLI Runtime](./cli-runtime.md) - 2 occurrences
- [Planner](./planner.md) - 2 occurrences
- [Runtime](./runtime.md) - 2 occurrences
- [Registry](./registry.md) - 2 occurrences
- [Components](./components.md) - 2 occurrences
- [Schemas](./schemas.md) - 2 occurrences
- [GitHub](./core-node-packages/github-nodes.md)
- [Claude](./core-node-packages/claude-nodes.md)
- [CI](./core-node-packages/ci-nodes.md)
- [LLM](./core-node-packages/llm-nodes.md)
- [PocketFlow Integration](./pflow-pocketflow-integration-guide.md) - 2 occurrences
- [Shell Pipes](./shell-pipes.md) - 2 occurrences
- [Metadata Extraction](./implementation-details/metadata-extraction.md)
- [MCP Integration](./mcp-integration.md)
- [CLI Autocomplete](./implementation-details/autocomplete-impl.md)
- [JSON Extraction](./future-version/json-extraction.md)
- [LLM Node Gen](./future-version/llm-node-gen.md)
- Links with anchors: 5 (e.g., [shared-store.md#template-variable-resolution])
- [template](./mvp-scope.md#version-header-template)

### 2. `/docs/prd.md` (37 links)
**Product Requirements Document with extensive cross-references**
- [Architecture](./architecture.md) - 2 occurrences
- [MVP Scope](./mvp-scope.md) - 3 occurrences
- [Shared Store](./shared-store.md) - 5 occurrences
- [Simple Nodes](./simple-nodes.md)
- [CLI Runtime](./cli-runtime.md) - 2 occurrences
- [Planner](./planner.md) - 3 occurrences
- [Runtime](./runtime.md) - 3 occurrences
- [Registry](./registry.md) - 3 occurrences
- [Components](./components.md) - 2 occurrences
- [PocketFlow Integration](./pflow-pocketflow-integration-guide.md) - 2 occurrences
- [Workflow Analysis](./workflow-analysis.md)
- [Shared Store](./shared-store.md#proxy-pattern)
- [Planner Specification](planner.md)
- [CLI Reference](cli-reference.md)
- [Schemas](schemas.md#node-metadata-schema)
- [Metadata Extraction](implementation-details/metadata-extraction.md)
- [Schemas](./schemas.md)
- [Execution Reference](execution-reference.md#validation-pipeline)
- [Schemas](schemas.md#schema-validation-requirements)
- [Execution Reference](execution-reference.md#retry-mechanisms)
- [MCP Integration](./mcp-integration.md) - 2 occurrences

### 3. `/docs/planner.md` (25 links)
**Planner specification with many template and schema references**
- [MVP Scope](./mvp-scope.md) - 2 occurrences
- [Shared Store](./shared-store.md) - 2 occurrences
- [Template Variables](./shared-store.md#template-variable-resolution) - 3 occurrences
- [Architecture](./architecture.md)
- [PRD](./prd.md)
- [Runtime](./runtime.md) - 2 occurrences
- [Registry](./registry.md) - 2 occurrences
- [Schemas](./schemas.md) - 3 occurrences
- [CLI Runtime](./cli-runtime.md)
- [Components](./components.md)
- [Shared Store Pattern](./shared-store.md)
- [MVP Scope](./mvp-scope.md#explicitly-excluded-from-mvp)
- [Schemas](schemas.md#document-envelope-flow-ir)
- [Workflow Analysis](workflow-analysis.md)
- [Runtime](runtime.md#caching-strategy)
- [Execution Reference](execution-reference.md#performance-considerations)
- [Shared Store + Proxy Pattern](./shared-store.md)
- [JSON IR & Metadata Schemas](./schemas.md)
- [Runtime Behavior](./runtime.md)
- [Registry System](./registry.md)

### 4. `/docs/shared-store.md` (21 links)
**Core shared store pattern documentation**
- [PRD](./prd.md)
- [Architecture](./architecture.md)
- [MVP Scope](./mvp-scope.md)
- [Planner](./planner.md) - 2 occurrences
- [Runtime](./runtime.md) - 2 occurrences
- [CLI Runtime](./cli-runtime.md) - 2 occurrences
- [Simple Nodes](./simple-nodes.md)
- [PocketFlow Integration](./pflow-pocketflow-integration-guide.md)
- [Node Reference](node-reference.md#shared-store-access)
- [Node Reference](node-reference.md#base-node-class)
- [Node Reference](node-reference.md#common-node-templates)
- [Node Reference](node-reference.md#testing-nodes)
- [GitHub Nodes](./core-node-packages/github-nodes.md)
- [Claude Nodes](./core-node-packages/claude-nodes.md)
- [CI Nodes](./core-node-packages/ci-nodes.md)
- [LLM Node](./core-node-packages/llm-nodes.md)
- [registry.md](./registry.md)
- [Shared-Store & Proxy Model — CLI Runtime Specification](./shared-store-cli-runtime-specification.md)

### 5. `/docs/architecture.md` (21 links)
**System architecture with cross-references to all major components**
- [PRD](./prd.md)
- [MVP Scope](./mvp-scope.md)
- [Shared Store](./shared-store.md) - 2 occurrences
- [Simple Nodes](./simple-nodes.md)
- [CLI Runtime](./cli-runtime.md)
- [Planner](./planner.md) - 2 occurrences
- [Runtime](./runtime.md)
- [Registry](./registry.md)
- [Schemas](./schemas.md)
- [PocketFlow Integration](./pflow-pocketflow-integration-guide.md)
- [Components](./components.md) - 2 occurrences
- [Node Reference](node-reference.md#node-lifecycle)
- [NodeAwareSharedStore Proxy](./shared-store.md#nodeawaresharedstore-proxy)
- [Template Variable Resolution](./shared-store.md#template-variable-resolution)
- [Node Implementation Examples](node-reference.md#common-node-templates)
- [Execution Reference](execution-reference.md)
- [CLI Runtime Specification](./cli-runtime.md)
- [Caching and Safety](runtime.md#caching-strategy)

### 6. `/docs/schemas.md` (20 links)
**JSON schema definitions with many broken links**
- [Node Metadata Strategy](implementation-details/node-metadata-extraction.md)
- [Shared Store Pattern](./shared-store-node-proxy-architecture.md) - 3 occurrences (BROKEN LINK)
- [version lockfile](./node-discovery-namespacing-and-versioning.md) (BROKEN LINK)
- [Node Metadata](implementation-details/node-metadata-extraction.md)
- [planner validation](./planner-responsibility-functionality-spec.md) - 3 occurrences (BROKEN LINK)
- [Runtime Behavior](./runtime-behavior-specification.md) - 2 occurrences (BROKEN LINK)
- [Execution Reference](execution-reference.md) - 2 occurrences
- [CLI Reference](cli-reference.md)
- [Registry](registry.md)
- [Shared Store + Proxy Pattern](./shared-store.md) - 2 occurrences
- [Planner Specification](./planner.md)
- [Registry System](./registry.md)
- [Metadata Extraction](./implementation-details/metadata-extraction.md)
- [Runtime Behavior](./runtime.md)

### 7. `/docs/simple-nodes.md` (17 links)
**Simple node pattern with references to all node packages**
- Multiple references to specific nodes in core-node-packages:
  - [github-get-issue](./core-node-packages/github-nodes.md#github-get-issue)
  - [github-create-issue](./core-node-packages/github-nodes.md#github-create-issue)
  - [github-list-prs](./core-node-packages/github-nodes.md#github-list-prs)
  - [llm](./core-node-packages/llm-nodes.md)
  - [run-tests](./core-node-packages/ci-nodes.md#run-tests)
- [metadata schema](./schemas.md#node-metadata-schema) - 2 occurrences
- [shared store pattern](./shared-store.md) - 2 occurrences
- [shared store design](./shared-store.md#natural-interfaces)
- [GitHub Nodes](./core-node-packages/github-nodes.md)
- [Claude Nodes](./core-node-packages/claude-nodes.md)
- [CI Nodes](./core-node-packages/ci-nodes.md)
- [LLM Node](./core-node-packages/llm-nodes.md)
- [Registry System](./registry.md)
- [CLI Runtime](./cli-runtime.md)

### 8. `/docs/cli-runtime.md` (17 links)
**CLI runtime specification with many pattern references**
- [Shared Store + Proxy Design Pattern](./shared-store.md) - 2 occurrences
- [communication patterns](../pocketflow/docs/core_abstraction/communication.md) (outside docs/)
- [shared store pattern](./shared-store.md#proxy-pattern)
- [Schemas](schemas.md#complete-example-flow)
- [CLI Reference](cli-reference.md#flag-resolution)
- [Execution Reference](execution-reference.md#execution-flow)
- [IR schema](./schemas.md#intermediate-representation-ir)
- [CLI Autocomplete](./autocomplete.md) - 2 occurrences
- [Shell Pipes](./shell-pipes.md)
- [Planner](./planner.md)
- [Runtime](./runtime.md)
- [Simple Nodes](./simple-nodes.md)
- [Node Metadata Schema](./schemas.md#node-metadata-schema)
- [Registry System](./registry.md)
- [MCP Integration](./mcp-integration.md)

### 9-12. Core Node Packages (8-11 links each)
All node packages have similar cross-reference patterns:
- `/docs/core-node-packages/claude-nodes.md` (11 links)
- `/docs/core-node-packages/llm-nodes.md` (10 links)
- `/docs/core-node-packages/github-nodes.md` (8 links)
- `/docs/core-node-packages/ci-nodes.md` (8 links)

Each references:
- [Node Implementation Reference](../node-reference.md)
- [Simple Nodes Pattern](../simple-nodes.md)
- [Node Metadata Schema](../schemas.md#node-metadata-schema)
- [Shared Store Pattern](../shared-store.md)
- [Registry System](../registry.md)
- Links to other node packages

### 13. Other Important Files

**`/docs/runtime.md`** (10 links)
- References to execution, shared store, node reference, schemas

**`/docs/node-reference.md`** (10 links)
- References to simple nodes, shared store, schemas, all node packages

**`/docs/mcp-integration.md`** (10 links)
- Many broken links to non-existent files:
  - [Shared Store + Proxy Design Pattern](./shared-store-node-proxy-architecture.md) (BROKEN)
  - [Planner Responsibility & Functionality Spec](./planner-responsibility-functionality-spec.md) (BROKEN)

**`/docs/registry.md`** (8 links)
- References to MVP scope, simple nodes, schemas, planner
- Broken link: [MCP Server Integration](./mcp-server-integrationa-and-security-model.md)

**`/docs/components.md`** (8 links)
- References to MVP scope, architecture, planner, runtime, registry
- Link to todo: [Implementation Roadmap](../todo/implementation-roadmap.md)

**`/docs/mvp-scope.md`** (8 links)
- References to PRD, architecture, shared store, simple nodes, components

**`/docs/pflow-pocketflow-integration-guide.md`** (8 links)
- References to MVP scope, architecture, shared store, runtime, etc.
- External reference: [pocketflow Docs](../pocketflow/CLAUDE.md)

### Implementation Details Directory
- `/docs/implementation-details/metadata-extraction.md` (9 links)
- `/docs/implementation-details/autocomplete-impl.md` (8 links)

### Future Version Directory
- `/docs/future-version/llm-node-gen.md` (8 links)
- `/docs/future-version/json-extraction.md` (7 links)

### Other Files
- `/docs/workflow-analysis.md` (6 links)
- `/docs/shell-pipes.md` (6 links)
- `/docs/execution-reference.md` (6 links)
- `/docs/cli-reference.md` (6 links)
- `/docs/autocomplete.md` (1 link)

## Key Findings

### Most Referenced Documents
1. `shared-store.md` - Referenced by almost every document
2. `mvp-scope.md` - Critical for scope boundaries
3. `schemas.md` - Central to validation and structure
4. `planner.md` - Core component referenced widely
5. `architecture.md` - High-level reference point

### Broken Links Identified
1. `./shared-store-node-proxy-architecture.md` - Referenced in schemas.md and mcp-integration.md
2. `./planner-responsibility-functionality-spec.md` - Referenced multiple times in schemas.md
3. `./runtime-behavior-specification.md` - Referenced in schemas.md
4. `./node-discovery-namespacing-and-versioning.md` - Referenced in schemas.md
5. `./mcp-server-integrationa-and-security-model.md` - Referenced in registry.md (typo in filename)
6. `./shared-store-cli-runtime-specification.md` - Referenced in shared-store.md
7. `implementation-details/cli-auto-complete-feature-implementation-details.md` - Referenced in autocomplete.md

### Cross-Directory References
- Several files reference `../pocketflow/` directory
- One reference to `../todo/implementation-roadmap.md`
- Core node packages frequently reference parent directory (`../`)

### Anchor Links
Many documents use anchor links (e.g., `#node-metadata-schema`) which require careful handling during reorganization.
