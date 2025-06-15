# Critical User Decisions for pflow MVP Implementation

## ✅ RESOLVED DECISIONS

### 1. Node Architecture Pattern - RESOLVED
**Decision**: Individual nodes (Option A) as primary pattern
- Use `github-get-issue`, `github-create-issue`, etc. as separate nodes
- Syntactic sugar like `github get-issue` can be added in v2.0
- **Status**: ✅ CONFIRMED by user

### 2. CLI→PocketFlow Integration Mechanism - RESOLVED
**Decision**: JSON IR → Compiled to Python code (Option B with compilation)
- CLI syntax parsed into JSON IR (as specified in docs/planner.md)
- JSON IR then compiled into executable Python code using pocketflow patterns
- Enables natural language planning (LLM generates JSON)
- Supports validation, workflow storage, and debugging
- **Status**: ✅ CONFIRMED by user - matches planner.md architecture

### 3. Natural Language Planning MVP Scope - RESOLVED
**Decision**: Include NL planning in MVP but as final phase
- Natural language planning IS included in MVP scope
- Implemented as Phase 4 (last in MVP, weeks 7-8)
- Core value proposition requires this capability
- **Status**: ✅ CONFIRMED by user

### 4. Timeline Approach - RESOLVED
**Decision**: Keep current 8-week timeline unchanged
- No modifications to existing implementation plan timeline
- 4 phases, 2 weeks each as currently planned
- **Status**: ✅ CONFIRMED by user

### 5. CLI Parameter Resolution Strategy - RESOLVED
**Decision**: All CLI flags become node.set_params()
- CLI flags map directly to node parameters (not shared store)
- Shared store used for node-to-node data passing
- Conflicts handled via proxy mappings (not CLI resolution)
- Global parameters must be specified by flow and sent to nodes as params
- **Status**: ✅ CONFIRMED by user - different from shared-store.md suggestion

### 6. Error Handling Strategy - RESOLVED
**Decision**: Option A - Fail fast for MVP
- Clear error messages, no complex retry mechanisms in MVP
- Fails immediately on errors without graceful degradation
- **Status**: ✅ CONFIRMED by user

### 7. Authentication Strategy - RESOLVED
**Decision**: Option A - Environment variables only
- Use GITHUB_TOKEN, ANTHROPIC_API_KEY, etc. from environment
- No CLI auth commands or config files in MVP
- **Status**: ✅ CONFIRMED by user

## 📋 ALL DECISIONS RESOLVED ✅

**Implementation can now begin with full architectural clarity.**

## 🎯 FINAL IMPLEMENTATION GUIDANCE

**Key Patterns Confirmed**:

1. **Individual Nodes**: Each node has single purpose (`github-get-issue`, `claude-analyze`, etc.)
2. **JSON IR Pipeline**: CLI → JSON IR → Compiled Python → Execution (matches planner.md)
3. **Parameters**: All CLI flags become `node.set_params()`, shared store for data flow
4. **Fail Fast**: Clear error messages, no complex retry in MVP
5. **Environment Auth**: GITHUB_TOKEN, ANTHROPIC_API_KEY, etc.
6. **Full MVP**: Natural language planning included as Phase 4
7. **8-Week Timeline**: Unchanged from implementation plan

**Next Steps**:
1. Create missing `docs/action-nodes.md` (note: actually using individual nodes)
2. Begin Phase 1 implementation following the detailed plan
3. Use these decisions to resolve any implementation ambiguities

**Architecture is now 100% clarified for confident implementation.**
