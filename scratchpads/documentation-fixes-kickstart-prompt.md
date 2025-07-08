# Kickstart Prompt: Fix pflow Documentation Contradictions

## Your Mission

You need to fix critical documentation contradictions in the pflow project. The authoritative source of truth is `.taskmaster/tasks/tasks.json`. All documentation must align with this file.

## Context Files to Read First

1. **Read the contradictions report**: `/Users/andfal/projects/pflow/scratchpads/documentation-contradictions-report.md`
2. **Read the resolution plan**: `/Users/andfal/projects/pflow/scratchpads/documentation-resolution-plan.md`
3. **Reference the source of truth**: `/Users/andfal/projects/pflow/.taskmaster/tasks/tasks.json`

## Critical Facts You Must Know

- **Task 17 IS the Natural Language Planner System** (NOT shell-exec)
- Shell nodes are part of Task 13
- ALL nodes inherit from `pocketflow.BaseNode` (not just Task 17)
- Template variables ($var) are planner-internal only, NOT runtime
- "Find or Build" pattern is THE core innovation but not documented
- Tasks 17-20 were merged into one comprehensive planner task

## Phase 1: Critical Fixes (Do These First)

### 1. Fix Task 17 References

**Files to fix**:
- `docs/features/mvp-implementation-guide.md` line 160 - says "Shell node (Task 17)" - WRONG
- `docs/features/implementation-roadmap.md` line 75 - lists Task 17 as shell - WRONG

**Action**: Change all Task 17 references to "Natural Language Planner System"

### 2. Document the "Find or Build" Pattern

**Add this content** to `docs/features/planner.md` (new section):

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

**Also add** a shorter version to `docs/features/mvp-implementation-guide.md` in the Core Vision section.

### 3. Fix PocketFlow Usage Misunderstanding

**Update** `docs/CLAUDE.md`:
- Remove the line about "ONLY Task 17 uses PocketFlow internally"
- Remove reference to missing ADR file
- Add: "pflow is built ON the PocketFlow framework throughout. All nodes inherit from pocketflow.BaseNode."

**Create** `docs/architecture/adr/001-use-pocketflow-for-orchestration.md`:

```markdown
# ADR-001: Use PocketFlow for Workflow Orchestration

## Status
Accepted

## Context
pflow needs a robust workflow execution engine that handles node orchestration, error handling, and data flow.

## Decision
We will build pflow ON the PocketFlow framework:
- All nodes inherit from `pocketflow.BaseNode`
- All workflow execution uses `pocketflow.Flow` objects
- The IR compiler produces PocketFlow objects
- We use PocketFlow's `>>` operator for node chaining

## Consequences
- Proven workflow patterns from PocketFlow
- No need to reinvent orchestration logic
- Entire system built on consistent foundation
- Not just Task 17 - the whole runtime uses PocketFlow
```

## Phase 2: Structural Updates

### 4. Update Task Structure

**In** `docs/features/mvp-implementation-guide.md` and `docs/features/implementation-roadmap.md`:
- Phase 3 should show only Task 17 (not tasks 18-21, 29-31)
- Update the phase description to mention the comprehensive planner

### 5. Remove Specific Task Counts

**Search and replace**:
- "40 MVP tasks" → "multiple implementation phases"
- "31 active tasks" → "comprehensive task list"
- Focus on phases, not numbers

### 6. Standardize Node Names

**Ensure all examples use hyphenated format**:
- ✅ `github-get-issue`, `read-file`, `git-commit`
- ❌ `read_file`, `github_get_issue`

## Phase 3: User-Decided Updates

### 7. Mark MCP as v2.0 in PRD

**In** `docs/prd.md` section 8:
- Change header to: "## 8. MCP Integration & Unified Registry (v2.0 Feature)"
- Add note: "> **Note**: This feature is deferred to v2.0. See MVP scope for current implementation."

### 8. Add Two-Tier AI Documentation

**In** `docs/architecture/architecture.md` after section 3.3, add:

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

### 9. Update CLI Examples

**Pattern to use everywhere**:

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

## Phase 4: Polish

### 10. Clarify Template Variables

**In** `docs/features/planner.md`, add:
- "Template variables like $var are resolved by the planner during workflow generation"
- "They are NOT a runtime feature - the compiler passes them unchanged"
- "Only the planner performs substitution"

### 11. Update Cross-References

- Check all internal links still work
- Update `docs/index.md` descriptions for changed files
- Search for any remaining contradictions

## Validation Checklist

After completing all changes:
- [ ] All Task 17 references say "Natural Language Planner"
- [ ] "Find or Build" pattern is documented in at least 2 places
- [ ] No claims about "only Task 17 uses PocketFlow"
- [ ] Template variables clearly marked as planner-internal
- [ ] All node names use hyphenated format
- [ ] No specific task counts mentioned
- [ ] MCP marked as v2.0 feature
- [ ] Two-tier AI architecture documented
- [ ] CLI examples show MVP vs v2.0 approaches
- [ ] ADR file created for PocketFlow usage

## Important Notes

1. **Use grep** to find all instances before changing
2. **Test internal links** after updates
3. **Preserve context** - don't delete historical information, just clarify
4. **Reference tasks.json** when in doubt - it's the source of truth

## Success Criteria

When you're done:
- Documentation accurately reflects the current state from tasks.json
- No more contradictions between files
- Core "Find or Build" pattern is clearly explained
- Readers understand what's MVP vs v2.0
- PocketFlow usage is correctly documented throughout

Begin with Phase 1 critical fixes, then proceed systematically through all phases.
