# Documentation Resolution Plan

**Created**: 2025-01-08
**Purpose**: Detailed plan to resolve all documentation contradictions identified in documentation-contradictions-report.md
**Principle**: `.taskmaster/tasks/tasks.json` is the authoritative source of truth

## Executive Summary

This plan addresses all documentation contradictions found between pflow docs and tasks.json. Items are categorized by confidence level and ordered by implementation priority. User decisions are clearly marked where needed.

## 1. High-Confidence Fixes (No User Input Needed)

These can be resolved directly based on tasks.json:

### 1.1 Fix Task 17 Identity Crisis
**Action**: Update all references to Task 17 to correctly identify it as "Natural Language Planner System"

**Files to Update**:
- `docs/features/mvp-implementation-guide.md` - Line 160 (remove shell-exec reference)
- `docs/features/implementation-roadmap.md` - Line 75 (fix shell node reference)
- Any other files mentioning Task 17

**Correct Information**:
- Task 17: "Implement Natural Language Planner System" (critical priority)
- Shell nodes are part of Task 13: "Implement core platform nodes"

### 1.2 Add "Find or Build" Pattern Documentation
**Action**: Create clear documentation of this core pattern based on Task 17 details

**Add to**:
- `docs/features/mvp-implementation-guide.md` - In the Core Vision section
- `docs/features/planner.md` - As a dedicated section
- `docs/index.md` - Update the planner.md description

**Content to Include** (from tasks.json):
```markdown
## The "Find or Build" Pattern

pflow's core innovation is semantic workflow discovery:

1. User types: `pflow "analyze costs"`
2. System searches existing workflows by semantic meaning using `find_similar_workflows()`
3. If found: Suggests reuse (e.g., "Use existing 'aws-cost-analyzer' workflow?")
4. If not found: Generates new workflow using Natural Language Planner
5. Saves for future reuse

This enables "Plan Once, Run Forever" - workflows are discovered by intent, not memorized names.

Example:
- First time: `pflow "analyze error logs"` → Creates new workflow
- Later: `pflow "check server logs"` → Finds and suggests existing workflow
```

### 1.3 Update Task Structure Documentation
**Action**: Update all task listings to reflect the reorganization

**Files to Update**:
- `docs/features/mvp-implementation-guide.md` - Phase 3 task lists
- `docs/features/implementation-roadmap.md` - Phase 3 task lists

**Correct Structure**:
- Phase 3 should show Task 17 as the comprehensive planner (not tasks 18-21, 29-31)
- Total MVP tasks: 31 active + Task 32 (v2.0 deferred)
- Remove references to old task numbers that were merged

### 1.4 Correct PocketFlow Usage Documentation
**Action**: Fix the fundamental misunderstanding about PocketFlow usage

**Files to Update**:
- `docs/CLAUDE.md` - Remove incorrect ADR reference and statement
- Create `docs/architecture/adr/001-use-pocketflow-for-orchestration.md`

**Correct Information**:
- pflow is built ON the PocketFlow framework
- ALL nodes inherit from `pocketflow.BaseNode`
- ALL workflow execution uses PocketFlow Flow objects
- The entire runtime is PocketFlow-based

### 1.5 Clarify Template Variables
**Action**: Document that template variables are planner-internal only

**Files to Update**:
- `docs/features/planner.md` - Add explicit section on template resolution
- `docs/core-concepts/shared-store.md` - Clarify template vs runtime behavior

**Key Points**:
- Template variables ($var) are resolved by the planner during workflow generation
- They are NOT a runtime feature
- The compiler passes them unchanged
- Only the planner does substitution

### 1.6 Update Node Naming Convention
**Action**: Standardize on hyphenated format throughout

**Files to Update**:
- All documentation showing node names
- Examples should use: `github-get-issue`, `read-file`, `git-commit`

**Pattern**: `platform-action` for specific nodes, single word for general nodes

### 1.7 Move Lockfiles to v2.0
**Action**: Clarify that lockfiles are deferred

**Files to Update**:
- Any mentions of lockfiles in MVP sections
- Ensure Task 21 is marked as "deferred" in documentation

### 1.8 Fix Task Status Discrepancies
**Action**: Update Task 3 status to reflect reality

**Clarification**:
- Task 3 is "pending" but "substantially implemented"
- Focus is on "review, polish, and ensuring completeness"
- Update docs to reflect this nuanced status

## 2. Items Requiring User Decision

### 2.1 ✅ MCP Integration Scope - DECIDED
**Decision**: Option A - Update PRD to clearly mark MCP section as "v2.0 Feature"

**Implementation**:
- Add header to MCP section in PRD: "## 8. MCP Integration & Unified Registry (v2.0 Feature)"
- Add note at beginning of section: "> **Note**: This feature is deferred to v2.0. See MVP scope for current implementation."

### 2.2 ✅ MVP Task Count Clarity - DECIDED
**Decision**: Option C - Stop mentioning specific task counts

**Implementation**:
- Replace "40 MVP tasks" with "multiple implementation phases"
- Remove specific counts from executive summaries
- Focus on phases and outcomes rather than task numbers

### 2.3 ✅ Two-Tier AI Architecture Documentation - DECIDED
**Decision**: Option A - Add dedicated section in `docs/architecture/architecture.md`

**Implementation**:
Add new section after "3.3 Node System":

```markdown
### 3.4 Two-Tier AI Architecture

pflow implements a two-tier AI system optimized for different use cases:

#### Tier 1: General LLM Node (`llm`)
- **Purpose**: Fast, lightweight text processing
- **Interface**: `shared['prompt']` → `shared['response']`
- **Use Cases**: Commit messages, summaries, simple transformations
- **Characteristics**:
  - No project context required
  - Minimal token usage (~100-500 tokens)
  - Sub-second response times
  - No file system access

#### Tier 2: Claude Code Super Node (`claude-code`)
- **Purpose**: Comprehensive AI-assisted development
- **Interface**: `shared['prompt']` → `shared['code_report']`
- **Use Cases**: Bug fixes, feature implementation, code analysis
- **Characteristics**:
  - Full project context and file system access
  - Higher token usage (1000-5000 tokens)
  - 20-60 second execution times
  - Access to all development tools

This separation allows workflows to optimize for speed (llm) or capability (claude-code) as needed.
```

### 2.4 ✅ CLI Parsing Strategy Documentation - DECIDED
**Decision**: Option C - Show both with clear "MVP" vs "Future" labels

**Implementation template**:
```markdown
## CLI Usage

### MVP Implementation (Natural Language)
```bash
# Everything after 'pflow' is sent to the LLM as natural language
pflow "analyze github issue 123 and create a fix"
pflow "read error.log, extract patterns, write report"
```

### Future v2.0 (Direct CLI Parsing)
```bash
# Direct parsing without LLM interpretation (optimization)
pflow github-get-issue --issue=123 >> analyze >> create-fix
pflow read-file --path=error.log >> extract-patterns >> write-file --path=report.md
```

> **Note**: In MVP, all input is processed as natural language. Direct CLI parsing is a v2.0 optimization.
```

**Example of Option C**:
```markdown
## CLI Usage

### MVP (Natural Language Only)
```bash
pflow "analyze github issue 123 and create a fix"
# Everything after 'pflow' sent to LLM as-is
```

### Future v2.0 (Direct Parsing)
```bash
pflow github-get-issue --issue=123 >> analyze >> create-fix
# Direct parsing without LLM (minor optimization)
```
```

## 3. Implementation Order

### Phase 1: Critical Fixes (Do First)
1. Fix Task 17 references (prevents further confusion)
2. Add "Find or Build" documentation (core value prop)
3. Correct PocketFlow usage (fundamental architecture)

### Phase 2: Structural Updates
4. Update task structure/counts
5. Clarify template variables
6. Standardize node naming

### Phase 3: User Decision Items
7. Get user decisions on MCP, task counts, two-tier AI, CLI parsing
8. Implement chosen approaches

### Phase 4: Polish
9. Update all examples to be consistent
10. Create missing ADR file
11. Add cross-references between related docs
12. Update `docs/index.md` descriptions

## 4. Validation Checklist

After implementation:
- [ ] All Task 17 references show "Natural Language Planner"
- [ ] "Find or Build" pattern explained in at least 2 places
- [ ] No claims about "only Task 17 uses PocketFlow"
- [ ] Template variables clearly marked as planner-internal
- [ ] All node names use hyphenated format
- [ ] Task counts are accurate
- [ ] No MVP features listed as deferred
- [ ] All user decisions documented

## 5. Future Considerations

### Documentation Maintenance Process
**Recommendation**: Establish a process to keep docs in sync with tasks.json:
1. Any task updates should trigger doc review
2. Consider auto-generating some docs from tasks.json
3. Add CI check for common contradictions

### Version Control for Decisions
**Recommendation**: Create `docs/decisions/` directory for recording:
- Architecture decisions
- Scope changes
- Task reorganizations

## 6. Risks and Mitigation

### Risk: Missing Hidden Dependencies
**Mitigation**: Search for indirect references before making changes

### Risk: Breaking External Links
**Mitigation**: Add redirects or "moved to" notes when relocating content

### Risk: Losing Historical Context
**Mitigation**: Preserve reorganization history in metadata or decision logs

## Next Steps

1. ✅ **User Review**: Complete - All decisions made
2. **Create Backup**: Before implementing, backup current docs
3. **Systematic Implementation**: Follow the phases in order
4. **Validate**: Use the checklist to ensure completeness

## Final Implementation Plan

With all user decisions made, here's the consolidated plan:

### Phase Order
1. **Critical Fixes** (Task 17, Find or Build, PocketFlow usage)
2. **Structural Updates** (Task structure, templates, node naming)
3. **User-Decided Updates** (MCP, task counts, two-tier AI, CLI examples)
4. **Polish and Validation** (cross-references, ADR, minor fixes)

### Key Decisions Made
- MCP: Mark as v2.0 feature in PRD
- Task Counts: Remove specific numbers, use "multiple phases"
- Two-Tier AI: Document in architecture.md
- CLI Examples: Show both MVP and v2.0 with clear labels

---

**Note**: This plan is ready for implementation. A detailed kickstart prompt has been created in `scratchpads/documentation-fixes-kickstart-prompt.md` to guide an AI coding agent through the execution.
