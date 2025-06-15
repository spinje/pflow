# Documentation Consistency Review

## Mission
Go through ALL documentation in docs/ folder and verify consistency across documents. Identify contradictions, fix clear issues, and note ambiguous conflicts for user decision.

## Scope
- Review all .md files in docs/ and subdirectories
- Check for contradictory information about architecture, features, scopes
- Verify alignment between different specs
- Ensure MVP vs future version boundaries are consistent
- Check technical details for conflicts

## Progress Tracking

### Document Inventory
- [x] docs/prd.md ✓ REVIEWED
- [x] docs/architecture.md ✓ REVIEWED
- [x] docs/mvp-scope.md ✓ REVIEWED
- [x] docs/action-nodes.md ✓ REVIEWED
- [x] docs/shared-store.md ✓ REVIEWED
- [x] docs/cli-runtime.md ✓ REVIEWED
- [x] docs/schemas.md ✓ REVIEWED
- [x] docs/planner.md ✓ REVIEWED
- [x] docs/runtime.md ✓ REVIEWED
- [x] docs/registry.md ✓ REVIEWED
- [x] docs/components.md ✓ REVIEWED
- [x] docs/shell-pipes.md ✓ REVIEWED
- [x] docs/autocomplete.md ✓ REVIEWED
- [x] docs/mcp-integration.md ✓ REVIEWED
- [x] docs/workflow-analysis.md ✓ REVIEWED
- [x] docs/modules.md ✓ REVIEWED (empty)
- [x] docs/core-nodes/github-node.md ✓ REVIEWED
- [x] docs/core-nodes/claude-node.md ✓ REVIEWED
- [x] docs/core-nodes/ci-node.md ✓ REVIEWED
- [x] docs/core-nodes/llm-node.md ✓ REVIEWED
- [x] docs/implementation-details/metadata-extraction.md ✓ REVIEWED
- [x] docs/implementation-details/autocomplete-impl.md ✓ REVIEWED
- [x] docs/future-version/llm-node-gen.md ✓ REVIEWED
- [x] docs/future-version/json-extraction.md ✓ REVIEWED

## REVIEW COMPLETE: All documents reviewed ✅

## Consistency Issues Found

### CONTRADICTIONS (require user decision)

1. **NATURAL LANGUAGE PLANNING IN MVP SCOPE**
   - **PRD**: Describes dual-mode planning (NL + CLI), with NL being a core feature
   - **Architecture**: States MVP focuses on CLI path, NL is "Post-MVP"
   - **MVP-Scope**: Lists "Natural Language Planning Engine" as #1 MVP core feature
   - **Planner**: Describes comprehensive dual-mode planner for MVP
   - **Components**: Lists "CLI Path Planner (MVP Focus)" but puts "Natural Language Planning" in v2.0
   - **Decision needed**: Is natural language planning in MVP or not?

2. **MCP INTEGRATION SCOPE**
   - **PRD**: Comprehensive MCP integration described as core architectural feature
   - **Architecture**: MCP listed as "Post-MVP Foundation"
   - **MVP-Scope**: MCP deferred to v2.0
   - **Components**: Lists MCP integration as v2.0 feature
   - **MCP-Integration**: Very comprehensive spec treating MCP as core feature, not v2.0
   - **Decision needed**: What level of MCP integration belongs in MVP?

3. **NODE ARCHITECTURE APPROACH**
   - **PRD/Architecture**: Describes individual function nodes (yt-transcript, summarize-text)
   - **MVP-Scope**: Describes action-based platform nodes (github with actions: get-issue, create-pr)
   - **Action-Nodes**: Strongly advocates for action-based platform nodes with extensive rationale
   - **Components**: Clearly lists action-based platform nodes for MVP (github, claude, ci, git, file, shell)
   - **Decision needed**: Are we building specific function nodes or action-based platform nodes?

### CLEAR FIXES MADE

**1. Natural Language Planning Scope - RESOLVED**
- Updated `docs/architecture.md`: Clarified NL planning is in MVP but built after core infrastructure dependencies
- Updated `docs/components.md`: Moved NL planning from v2.0 to MVP with clear build order (CLI first, then NL)
- Updated `docs/mvp-scope.md`: Added build dependencies and implementation order for NL planning

**2. MCP Integration Scope - RESOLVED**
- Updated `docs/prd.md`: Changed from "wrap MCP tools" to "future MCP integration"
- Updated `docs/components.md`: Moved all MCP integration components to v2.0 section
- Updated `docs/mvp-scope.md`: Moved MCP node integration to v2.0 explicitly

**3. Node Architecture Approach - RESOLVED**
- Updated `docs/components.md`: Enhanced node metadata system to support action-specific parameter mapping
- Updated `docs/mvp-scope.md`: Added clarification about action-specific parameters with some global parameters
- Updated `docs/action-nodes.md`: Added parameter availability mapping and enhanced metadata schema examples
- Clarified that some parameters (e.g., extra prompts for claude node) are available for all actions within a node

### NOTES AND OBSERVATIONS

- All documents agree on pocketflow foundation and shared store pattern
- JSON IR approach is consistent across documents
- CLI flag resolution ("Type flags; engine decides") is consistently described
- Performance targets are aligned where specified
- Shared-store.md and cli-runtime.md are highly detailed and consistent with each other
- Action-nodes.md provides strong rationale for platform nodes vs function nodes
- All documents agree on natural interface pattern and proxy mapping when needed
- Schemas.md, planner.md, and runtime.md are internally consistent and align with shared store pattern
- Planner.md describes comprehensive dual-mode approach (NL + CLI) - seems to support MVP including NL planning
