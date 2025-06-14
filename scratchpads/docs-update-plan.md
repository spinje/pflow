# Documentation Update Plan: Simple Nodes Architecture

This document outlines the detailed plan for updating pflow documentation to align with the simple nodes architecture decisions from `simple-nodes-final-architecture.md`.

## Important Context

This plan must be executed alongside the implementation plans:
- **Implementation Roadmap**: See `todo/implementation-roadmap.md` for high-level phases
- **MVP Implementation Plan**: See `todo/mvp-implementation-plan.md` for detailed tasks
- **Simple Nodes Architecture**: Based on decisions in `scratchpads/simple-nodes-final-architecture.md`

**Key Architectural Insight**: We shifted from action-based nodes to simple, single-purpose nodes with a general-purpose `llm` node as a smart exception to prevent node proliferation.

**CRITICAL DISTINCTION**:
- **REMOVE**: Action-based NODES (nodes that take `--action` as input parameter, e.g., `pflow github --action=get-issue`)
- **KEEP**: Action-based OUTPUTS (nodes returning action strings for flow control, e.g., `node - "error" >> error_handler`)

## Overview

We need to update documentation to reflect:
1. Simple, single-purpose nodes (with smart exceptions like `llm`)
2. Clear shared store vs params guidelines
3. No action-based nodes (no `--action` parameter) but keep action-based outputs for flow control
4. General `llm` node replacing many prompt-specific nodes
5. Simplified CLI with `--prompt` instead of templates for MVP
6. Future v2.0: CLI grouping syntax (e.g., `pflow github get-issue`) as pure CLI sugar, not node architecture

## Files to Update

### 1. **docs/action-nodes.md**
**Status**: MAJOR REVISION NEEDED → Rename to `simple-nodes.md`
**Current**: Describes action-based platform nodes with dynamic APIs
**Changes Needed**:
- Remove all references to action-based nodes (nodes with `--action` parameter)
- Replace with simple node philosophy
- Show how platform functionality is achieved through multiple simple nodes
- Update examples to use individual nodes (github-get-issue, github-create-issue)
- **KEEP**: Action-based outputs for flow control (`node - "error" >> handler`)
- Add "Future CLI Grouping" section showing v2.0 syntax like `pflow github get-issue`

### 2. **docs/architecture.md**
**Status**: MODERATE REVISION
**Current**: High-level architecture overview
**Changes Needed**:
- Update node design section to emphasize simplicity
- Remove action-based routing mentions (but keep action-based outputs for flow control)
- Add section on general-purpose nodes (llm) as exceptions
- Update examples to show simple node composition

### 3. **docs/core-nodes/llm-node.md**
**Status**: COMPLETE REWRITE
**Current**: Describes prompt node with template system
**Changes Needed**:
- Rename from "prompt" to "llm" node
- Simplify interface: just reads shared["prompt"], writes shared["response"]
- Remove template complexity for MVP
- Add note about future Simon Willison llm integration
- Show how it replaces many specific nodes

### 4. **docs/core-nodes/github-node.md**
**Status**: COMPLETE REWRITE
**Current**: Single action-based GitHub node
**Changes Needed**:
- Split into multiple simple nodes:
  - github-get-issue
  - github-create-issue
  - github-search-code
  - github-list-prs
- Each with clear, single purpose
- Remove action dispatch logic (but keep action-based outputs for flow control)

### 5. **docs/core-nodes/claude-node.md**
**Status**: EVALUATE FOR REMOVAL
**Current**: Claude-specific node
**Changes Needed**:
- Consider removing in favor of general `llm` node
- If kept, ensure it's for Claude-specific features only
- Otherwise, show how `llm --model=claude-3` achieves same result

### 6. **docs/mvp-scope.md**
**Status**: MINOR UPDATES
**Current**: Defines MVP boundaries
**Changes Needed**:
- Clarify that action-based nodes (with `--action` parameter) are OUT of MVP
- Emphasize simple nodes approach
- Update examples to use new patterns

### 7. **docs/shared-store.md**
**Status**: MINOR UPDATES
**Current**: Explains shared store pattern
**Changes Needed**:
- Add clear guidelines on shared store vs params
- Include best practice: check both, shared store precedence
- Update examples with new node patterns

### 8. **docs/cli-runtime.md**
**Status**: MODERATE REVISION
**Current**: Describes CLI and runtime
**Changes Needed**:
- Update examples to use simple `--prompt` instead of `--prompt_template`
- Show how multiple simple nodes compose
- Remove action-based routing examples (nodes with `--action` parameter)
- Add section on future v2.0 CLI grouping: `pflow <platform> <operation>` syntax
- Clarify this is CLI convenience, nodes remain simple

### 9. **docs/registry.md**
**Status**: MODERATE REVISION
**Current**: Registry and discovery system
**Changes Needed**:
- Update to show simple node organization
- Show naming conventions (github-*, slack-*, etc.)
- Remove action metadata from examples

### 10. **docs/planner.md**
**Status**: MODERATE REVISION
**Current**: Natural language planning
**Changes Needed**:
- Update to show how planner selects simple nodes
- Remove action-based selection logic (nodes with `--action` parameter)
- Show how `llm` node is preferred for text tasks

### 11. **docs/schemas.md**
**Status**: MINOR UPDATES
**Current**: JSON IR schemas
**Changes Needed**:
- Remove action-based fields from node schemas (but keep action outputs for flow control)
- Simplify to match simple node pattern
- Update examples

### 12. **docs/components.md**
**Status**: MINOR UPDATES
**Current**: MVP vs v2.0 features
**Changes Needed**:
- Clarify action-based nodes (with `--action` parameter) are completely out (not just v2.0)
- Update node examples

### 13. **docs/mcp-integration.md**
**Status**: MINOR UPDATES
**Current**: MCP server integration
**Changes Needed**:
- Show how MCP tools become simple nodes
- Each MCP tool = one simple node
- Remove action dispatch from MCP wrappers (but keep action-based outputs for flow control)
- Note: MCP naming naturally aligns with future CLI grouping (mcp-github-search)

### 14. **docs/prd.md**
**Status**: SIGNIFICANT UPDATES
**Current**: Master requirements document
**Changes Needed**:
- Update all action-based node references (remove `--action` parameter usage)
- Revise examples throughout
- Update architectural principles
- Clarify llm node strategy

## Update Strategy

### Phase 1: Core Concept Updates
1. Update `action-nodes.md` → rename to `simple-nodes.md`
2. Update `architecture.md` with simple node philosophy
3. Update `shared-store.md` with clear guidelines

### Phase 2: Node Documentation
1. Rewrite `core-nodes/llm-node.md`
2. Split and rewrite `core-nodes/github-node.md`
3. Evaluate/update other core nodes

### Phase 3: System Documentation
1. Update `planner.md` for simple node selection
2. Update `registry.md` for new organization
3. Update `schemas.md` to remove action fields

### Phase 4: Integration and PRD
1. Update `mcp-integration.md`
2. Update `cli-runtime.md`
3. Comprehensive `prd.md` revision

### Phase 5: Cleanup
1. Update all examples and code snippets
2. Ensure consistency across all docs
3. Update `mvp-scope.md` and `components.md`

## Key Messages to Reinforce

Throughout all updates, emphasize:

1. **Simplicity First**: One node, one purpose
2. **Smart Exceptions**: General `llm` node to prevent proliferation
3. **Clear Interfaces**: Every node documents Reads/Writes/Params
4. **Natural Composition**: Simple nodes compose into complex flows
5. **No Magic**: No action dispatch in nodes (no `--action` parameter), no dynamic APIs
6. **Future CLI Sugar**: v2.0 grouping syntax is purely CLI convenience, not node architecture

## Examples to Use Consistently

### Good Examples (MVP):
```bash
# Simple, focused nodes
pflow github-get-issue --repo=owner/repo --issue=123
pflow yt-transcript --url=https://youtu.be/abc123
pflow llm --prompt="Analyze this data and find patterns"

# Composition
pflow read-file data.csv >> llm --prompt="Summarize this data" >> write-file summary.md

# Action-based outputs for flow control (KEEP THIS)
pflow validate-input >> process-data
validate-input - "error" >> error-handler
```

### Future v2.0 CLI Grouping (mention where appropriate):
```bash
# v2.0 CLI sugar - same simple nodes underneath
pflow github get-issue --repo=owner/repo --issue=123
pflow github create-issue --title="Bug" --body="Description"
pflow mcp github search-code --query="test"

# This is purely CLI convenience, not node architecture!
# Internally maps to: github-get-issue, github-create-issue, mcp-github-search
```

### Anti-patterns to Remove:
```bash
# No action-based nodes (nodes with --action parameter)
pflow github --action=get-issue  # ❌ Not our pattern

# No complex templates in MVP
pflow prompt --template="..."     # ❌ Use llm --prompt instead
```

### What to KEEP:
```bash
# Action-based outputs for flow control (KEEP THIS)
node - "error" >> error_handler   # ✅ Still supported but not a focus for the MVP
node - "retry" >> retry_handler   # ✅ Still supported but not a focus for the MVP
```

## Success Criteria

Documentation update is complete when:
1. No references to action-based nodes remain (except historical context)
2. All examples use simple node patterns
3. `llm` node is clearly positioned as the general text processing solution
4. Shared store vs params guidelines are consistent everywhere
5. The architecture feels simpler and more approachable
6. Future v2.0 CLI grouping is presented as optional syntax sugar, not core architecture

## Additional Notes on v2.0 CLI Grouping

Where it makes sense to mention:
- The v2.0 CLI grouping (e.g., `pflow github get-issue`) is **purely syntactic sugar**
- It provides a unified interface that naturally aligns with MCP tool naming
- Internally, it still maps to simple, individual nodes (github-get-issue)
- This approach ensures consistency between native nodes and MCP wrapper nodes
- The nodes themselves remain simple and single-purpose
- This is similar to how git commands work: `git commit` is sugar for `git-commit`

## Implementation Progress Checklist

Track progress as we execute both documentation updates and implementation:

### Phase 1: Core Concept Updates
- [x] **docs/action-nodes.md → simple-nodes.md** (MAJOR REVISION)
  - [x] Remove all action-based node references
  - [x] Add simple node philosophy
  - [x] Update examples to individual nodes (github-get-issue, etc.)
  - [x] Add "Future CLI Grouping" section for v2.0
- [x] **docs/architecture.md** (MODERATE REVISION)
  - [x] Update node design section for simplicity
  - [x] Remove action-based routing mentions
  - [x] Add general-purpose nodes section (llm)
  - [x] Update examples for simple node composition
- [x] **docs/shared-store.md** (MINOR UPDATES)
  - [x] Add shared store vs params guidelines
  - [x] Include best practice: check both, shared store precedence
  - [x] Update examples with new node patterns

### Phase 2: Node Documentation
- [x] **docs/core-nodes/llm-node.md** (COMPLETE REWRITE)
  - [x] Rename from "prompt" to "llm" node
  - [x] Simplify interface: shared["prompt"] → shared["response"]
  - [x] Remove template complexity for MVP
  - [x] Add Simon Willison llm integration note
  - [x] Show how it replaces many specific nodes
- [x] **docs/core-nodes/github-node.md** (COMPLETE REWRITE)
  - [x] Split into multiple simple nodes documentation
  - [x] Document github-get-issue, github-create-issue, etc.
  - [x] Remove action dispatch logic
  - [x] Clear single-purpose interfaces
- [x] **docs/core-nodes/claude-node.md** (EVALUATE/REMOVE)
  - [x] Decide: remove in favor of general llm node
  - [x] If kept: Claude-specific features only
  - [x] Document llm --model=claude-3 alternative

### Phase 3: System Documentation
- [x] **docs/planner.md** (MODERATE REVISION)
  - [x] Update for simple node selection
  - [x] Remove action-based selection logic
  - [x] Show llm node preference for text tasks
- [x] **docs/registry.md** (MODERATE REVISION)
  - [x] Update for simple node organization
  - [x] Show naming conventions (github-*, slack-*, etc.)
  - [x] Remove action metadata from examples
- [x] **docs/schemas.md** (MINOR UPDATES)
  - [x] Remove action-based fields from schemas
  - [x] Simplify to match simple node pattern
  - [x] Update all examples

### Phase 4: Integration and PRD
- [x] **docs/mcp-integration.md** (MINOR UPDATES)
  - [x] Show MCP tools as simple nodes
  - [x] Each MCP tool = one simple node
  - [x] Remove action dispatch from MCP wrappers
  - [x] Note MCP naming aligns with future CLI grouping
- [x] **docs/cli-runtime.md** (MODERATE REVISION)
  - [x] Update examples: --prompt instead of --prompt_template
  - [x] Show multiple simple nodes composition
  - [x] Remove action-based routing examples
  - [x] Add simple node composition patterns
- [x] **docs/prd.md** (SIGNIFICANT UPDATES)
  - [x] Update all action-based node references
  - [x] Revise examples throughout
  - [x] Update architectural principles
  - [x] Clarify llm node strategy

### Phase 5: Cleanup
- [x] **docs/mvp-scope.md** (MINOR UPDATES)
  - [x] Clarify action-based nodes are OUT of MVP
  - [x] Emphasize simple nodes approach
  - [x] Update examples to new patterns
- [x] **docs/components.md** (MINOR UPDATES)
  - [x] Clarify action-based nodes completely out
  - [x] Update node examples
- [x] **Final consistency pass**
  - [x] Update all remaining examples and code snippets
  - [x] Ensure consistency across all docs
  - [x] Verify no action-based node references remain (except historical context)

### Implementation Alignment (Track in Parallel)
- [ ] **Phase 1: Core Infrastructure** (Weeks 1-2)
  - [ ] CLI runtime with simple flag parsing
  - [ ] Shared store implementation
  - [ ] Basic node registry
  - [ ] pocketflow integration
- [ ] **Phase 2: Metadata & Registry** (Weeks 3-4)
  - [ ] Metadata extraction system
  - [ ] Registry CLI commands
  - [ ] Interface compatibility system
- [ ] **Phase 3: Simple Platform Nodes** (Weeks 5-6)
  - [ ] Individual GitHub nodes (github-get-issue, etc.)
  - [ ] General LLM node implementation
  - [ ] File and shell nodes
- [ ] **Phase 4: Natural Language Planning** (Weeks 7-8)
  - [ ] LLM integration infrastructure
  - [ ] Simple node selection engine
  - [ ] User approval & workflow storage

### Additional Files Requiring Updates
- [x] **README.md** (MAJOR UPDATES)
  - [x] Update all action-based examples (lines 49, 65, 198)
  - [x] Change `github --action=list-prs` to `github-list-prs`
  - [x] Change `aws --action=get-costs` to `aws-get-costs`
  - [x] Change `file --action=read` to `read-file`
  - [x] Update description to reflect simple nodes approach
- [x] **todo/implementation-roadmap.md** (MAJOR UPDATES)
  - [x] Change "Action-Based Platform Nodes" to "Simple Platform Nodes"
  - [x] Update all CLI examples to use simple node syntax
  - [x] Remove action dispatch references
  - [x] Update node descriptions throughout
- [x] **todo/mvp-implementation-plan.md** (MAJOR UPDATES)
  - [x] Update all action-based CLI examples
  - [x] Change node implementation descriptions
  - [x] Remove action dispatch pattern references
  - [x] Update acceptance criteria examples

### Success Validation Checklist
- [x] No action-based node references remain (except historical context in deprecated files)
- [x] All examples use simple node patterns
- [x] `llm` node clearly positioned as general text solution
- [x] Shared store vs params guidelines consistent everywhere
- [x] Architecture feels simpler and more approachable
- [x] v2.0 CLI grouping presented as syntax sugar only
- [x] Action-based outputs for flow control properly preserved and distinguished from action-based nodes
- [ ] Documentation aligns with implementation progress (pending actual implementation)
- [ ] All scratchpad insights properly incorporated
