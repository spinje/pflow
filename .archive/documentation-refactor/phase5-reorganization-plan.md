# Phase 5: Documentation Reorganization Plan

## Overview

This plan will reorganize 26 documentation files into a logical folder structure and update 353+ internal cross-references to maintain navigability.

## Current Issues to Address

1. **Flat structure** - All 26 docs in single directory
2. **353 internal links** - Need path updates
3. **Broken links** - Several references to non-existent files
4. **Inconsistent paths** - Mix of relative and absolute references

## Step-by-Step Execution Plan

### Step 1: Create Folder Structure

```bash
docs/
├── reference/                    # Technical references (3 files)
├── core-concepts/               # Core patterns (4 files)
├── architecture/                # High-level design (3 files)
├── features/                    # Feature specs (7 files)
├── node-packages/              # Already exists (4 files)
├── implementation-details/     # Already exists (2 files)
├── future-version/            # Already exists (2 files)
└── (root files)               # Index and overview (2 files)
```

### Step 2: File Movement Plan

#### To `reference/` (3 files)
- `node-reference.md` → `reference/node-reference.md`
- `cli-reference.md` → `reference/cli-reference.md`
- `execution-reference.md` → `reference/execution-reference.md`

#### To `core-concepts/` (4 files)
- `schemas.md` → `core-concepts/schemas.md`
- `shared-store.md` → `core-concepts/shared-store.md`
- `runtime.md` → `core-concepts/runtime.md`
- `registry.md` → `core-concepts/registry.md`

#### To `architecture/` (3 files)
- `architecture.md` → `architecture/architecture.md`
- `components.md` → `architecture/components.md`
- `pflow-pocketflow-integration-guide.md` → `architecture/pflow-pocketflow-integration-guide.md`

#### To `features/` (7 files)
- `planner.md` → `features/planner.md`
- `cli-runtime.md` → `features/cli-runtime.md`
- `shell-pipes.md` → `features/shell-pipes.md`
- `mcp-integration.md` → `features/mcp-integration.md`
- `simple-nodes.md` → `features/simple-nodes.md`
- `mvp-scope.md` → `features/mvp-scope.md`
- `workflow-analysis.md` → `features/workflow-analysis.md`

#### Remain in root (2 files)
- `index.md` (navigation hub)
- `prd.md` (product overview)

#### Already organized (keep as-is)
- `core-node-packages/` (4 files)
- `implementation-details/` (2 files)
- `future-version/` (2 files)

### Step 3: Path Update Rules

#### From root files (index.md, prd.md):
- `shared-store.md` → `core-concepts/shared-store.md`
- `planner.md` → `features/planner.md`
- `architecture.md` → `architecture/architecture.md`

#### From files moving to `reference/`:
- `shared-store.md` → `../core-concepts/shared-store.md`
- `schemas.md` → `../core-concepts/schemas.md`
- `runtime.md` → `../core-concepts/runtime.md`

#### From files moving to `core-concepts/`:
- `node-reference.md` → `../reference/node-reference.md`
- `planner.md` → `../features/planner.md`
- `architecture.md` → `../architecture/architecture.md`

#### From files in `core-node-packages/`:
- `../node-reference.md` → `../reference/node-reference.md`
- `../shared-store.md` → `../core-concepts/shared-store.md`
- `../schemas.md` → `../core-concepts/schemas.md`

### Step 4: Fix Broken Links

These non-existent files are referenced and need resolution:

1. `shared-store-node-proxy-architecture.md` → Should be `shared-store.md`
2. `planner-responsibility-functionality-spec.md` → Should be `planner.md`
3. `runtime-behavior-specification.md` → Should be `runtime.md`
4. `node-discovery-namespacing-and-versioning.md` → Should be `registry.md`
5. `mcp-server-integrationa-and-security-model.md` → Should be `mcp-integration.md`
6. `shared-store-cli-runtime-specification.md` → Should be `cli-runtime.md`

### Step 5: Update index.md Navigation

Update the main navigation to reflect new structure:

```markdown
## Documentation Structure

### 📚 Reference Guides
- [Node Reference](reference/node-reference.md) - Node implementation guide
- [CLI Reference](reference/cli-reference.md) - Command-line usage
- [Execution Reference](reference/execution-reference.md) - Runtime behavior

### 🎯 Core Concepts
- [Shared Store Pattern](core-concepts/shared-store.md)
- [JSON Schemas](core-concepts/schemas.md)
- [Runtime & Caching](core-concepts/runtime.md)
- [Registry System](core-concepts/registry.md)

### 🏗️ Architecture
- [System Architecture](architecture/architecture.md)
- [Components Overview](architecture/components.md)
- [PocketFlow Integration](architecture/pflow-pocketflow-integration-guide.md)

### ⚡ Features
- [Planner System](features/planner.md)
- [CLI Runtime](features/cli-runtime.md)
- [Shell Pipes](features/shell-pipes.md)
- [Simple Nodes](features/simple-nodes.md)
```

## Execution Order

1. **Create folders** - Set up new directory structure
2. **Move files** - Relocate files to appropriate folders
3. **Fix broken links** - Update references to non-existent files
4. **Update paths** - Systematically update all 353 cross-references
5. **Update index.md** - Revise navigation for new structure
6. **Verify links** - Test all cross-references work correctly

## Automation Strategy

Use multi-file search and replace for common patterns:
- `](shared-store.md)` → `](core-concepts/shared-store.md)`
- `](../shared-store.md)` → `](../core-concepts/shared-store.md)`
- Apply similar patterns for all frequently referenced files

## Success Criteria

- ✅ All files in appropriate folders
- ✅ All 353 internal links updated
- ✅ All broken links fixed
- ✅ Navigation in index.md reflects new structure
- ✅ No broken cross-references
- ✅ Documentation remains fully navigable
