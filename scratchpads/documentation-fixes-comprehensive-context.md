# Comprehensive Context: pflow Documentation Fixes

**Created**: 2025-01-08
**Purpose**: Complete context dump for AI agent to continue documentation contradiction fixes

## What We Were Doing

We were fixing critical documentation contradictions in the pflow project. The documentation had become out of sync with the authoritative source of truth (`.taskmaster/tasks/tasks.json`) due to a task reorganization that wasn't propagated to all docs.

## Why This Is Critically Important

1. **Developer Confusion**: The docs say Task 17 is "shell-exec" in some places and "Natural Language Planner" in others. This is the CORE FEATURE of pflow - getting this wrong blocks understanding.

2. **Architectural Misunderstanding**: Docs claim "only Task 17 uses PocketFlow" when actually the ENTIRE system is built on PocketFlow. This fundamental misunderstanding could lead to terrible implementation decisions.

3. **Missing Core Innovation**: The "find or build" pattern - pflow's killer feature - is mentioned but never explained. Without understanding this, implementers miss the entire point.

## The Journey So Far

### 1. Documentation Merge (Completed)
- **What**: Merged `mvp-scope.md` and `implementation-roadmap.md` into `mvp-implementation-guide.md`
- **Result**: Single source of truth for MVP implementation
- **Commit**: fe5d12d "Merge MVP scope and implementation roadmap into unified guide"

### 2. Contradiction Discovery
- **Process**: Searched docs for inconsistencies with tasks.json
- **Found**: 8 major contradictions + missing documentation
- **Created**: `/Users/andfal/projects/pflow/scratchpads/documentation-contradictions-report.md`

### 3. Resolution Planning
- **Created**: `/Users/andfal/projects/pflow/scratchpads/documentation-resolution-plan.md`
- **Identified**: 4 decisions needed from user
- **Got Decisions**:
  - MCP Integration: Option A (mark as v2.0 in PRD)
  - Task Counts: Option C (remove specific numbers)
  - Two-Tier AI: Option A (document in architecture.md)
  - CLI Examples: Option C (show both MVP and v2.0)

### 4. Kickstart Prompt Creation
- **Created**: `/Users/andfal/projects/pflow/scratchpads/documentation-fixes-kickstart-prompt.md`
- **Purpose**: Guide AI agent through fixing all contradictions

## Critical Understanding: What is pflow?

**pflow** is a workflow compiler that transforms natural language into permanent, deterministic CLI commands. It solves the problem of AI agents re-reasoning through the same tasks repeatedly.

### The Problem It Solves
```markdown
# Current inefficiency with Claude Code slash commands
/project:fix-github-issue 1234
# Takes 50-90 seconds, 1000-2000 tokens, $0.10-2.00 EVERY TIME

# pflow solution
pflow "fix github issue 1234"  # First time: generates workflow
pflow fix-issue --issue=1234    # Forever after: 2s execution, minimal tokens
```

### The "Find or Build" Pattern (CRITICAL - NOT DOCUMENTED!)
This is THE core innovation that makes pflow unique:

1. User types: `pflow "analyze costs"`
2. System searches for existing workflows by SEMANTIC MEANING
3. If found: "Use existing 'aws-cost-analyzer' workflow?"
4. If not found: Generates new workflow
5. This is "find" (by meaning) or "build" (new workflow)

Without this, pflow is just another workflow tool. WITH this, it's revolutionary.

## Key Files and Their Purpose

### Source of Truth
- `.taskmaster/tasks/tasks.json` - THE authoritative task list and status

### Documentation Files Needing Fixes
- `docs/features/mvp-implementation-guide.md` - Has Task 17 contradictions
- `docs/features/implementation-roadmap.md` - Has Task 17 contradictions
- `docs/CLAUDE.md` - Wrong PocketFlow usage claims
- `docs/prd.md` - MCP section needs v2.0 marking
- `docs/architecture/architecture.md` - Needs two-tier AI section
- `docs/features/planner.md` - Needs "find or build" documentation
- `docs/core-concepts/shared-store.md` - Needs template variable clarification
- `docs/index.md` - Needs updated descriptions

### Files That Need Creation
- `docs/architecture/adr/001-use-pocketflow-for-orchestration.md` - Missing ADR

### Reference Documents Created
- `/Users/andfal/projects/pflow/scratchpads/pflow-knowledge-braindump.md` - Original context
- `/Users/andfal/projects/pflow/scratchpads/documentation-contradictions-report.md` - All contradictions
- `/Users/andfal/projects/pflow/scratchpads/documentation-resolution-plan.md` - Fix plan with decisions
- `/Users/andfal/projects/pflow/scratchpads/documentation-fixes-kickstart-prompt.md` - Implementation guide

## Critical Facts from tasks.json

### Task 17 - THE Core Feature
```json
"id": 17,
"title": "Implement Natural Language Planner System",
"priority": "critical",
"status": "pending"
```
This includes:
1. Workflow Generation Engine
2. Prompt Templates
3. Template Resolution (planner-internal only!)
4. **Workflow Discovery** (the "find or build" pattern)
5. Approval and Storage

### Task Reorganization History
From tasks.json metadata:
> "Reorganized to prioritize Natural Language Planner as core feature. Merged tasks 17-20 into comprehensive planner system."

This explains why docs are confused - tasks 17-20 were merged but docs weren't updated.

### What's Really Built
- Tasks 1, 2, 4, 5, 6, 11: DONE (infrastructure complete)
- Task 3: "pending" but "substantially implemented"
- Task 17: "pending" and "critical" (the Natural Language Planner)
- Shell nodes are in Task 13 (NOT Task 17)

### PocketFlow Usage Truth
- ALL nodes inherit from `pocketflow.BaseNode`
- Task 4 compiles to `pocketflow.Flow` objects
- The entire execution engine uses PocketFlow
- NOT just Task 17 - this is a fundamental misunderstanding

### Template Variables Truth
- Planner-internal ONLY
- NOT a runtime feature
- Simple regex substitution during planning
- Compiler passes them unchanged

## Conceptual Insights Hard to Re-Derive

### 1. Why Task 17 Confusion Matters
Task 17 is the Natural Language Planner - THE feature that makes pflow unique. If developers think it's just "shell-exec", they'll completely miss the point. The planner enables:
- Natural language → workflow transformation
- Semantic workflow discovery ("find or build")
- Template variable generation
- The entire value proposition

### 2. The Two-Tier AI Architecture Logic
Not documented but critical:
- **llm node**: Fast, lightweight, no context (commit messages, summaries)
- **claude-code node**: Heavyweight, full context (bug fixes, implementations)

This isn't arbitrary - it's optimization for different use cases.

### 3. MVP Simplification Insight
Everything after 'pflow' goes to LLM as natural language in MVP. Direct CLI parsing is v2.0. This massive simplification enabled faster MVP delivery but docs still show complex parsing examples.

### 4. Why "Find or Build" Is Revolutionary
Current tools require exact workflow names. pflow finds by MEANING:
- `pflow "check AWS costs"` finds `aws-cost-analyzer`
- `pflow "analyze cloud spending"` finds the SAME workflow
- No memorization needed - semantic discovery

### 5. The Overthinking Problem
From braindump: Developer spent 6-8 weeks on perfect infrastructure but avoided the core planner. 350+ tests for 15% of features. Classic paralysis - this context helps understand why Task 17 (the hard part) is still pending.

## User's Specific Decisions

These were hard-won decisions that must be preserved:

1. **MCP Integration**: Option A - Update PRD header to "v2.0 Feature"
2. **Task Counts**: Option C - Stop mentioning specific numbers
3. **Two-Tier AI**: Option A - Add section to architecture.md
4. **CLI Examples**: Option C - Show both MVP and v2.0 with labels

## What Makes This Hard to Conceptualize

1. **The Contradiction Web**: Task 17 being wrong cascades through multiple docs
2. **Hidden Patterns**: "Find or build" is mentioned but never explained
3. **Historical Context**: Task reorganization happened but wasn't documented
4. **Philosophical Shifts**: MVP simplification (everything is natural language) contradicts examples
5. **Fundamental Misunderstandings**: PocketFlow usage, template variables

## Next Actions Required

See companion document: `documentation-fixes-next-actions.md`

## Success Validation

You'll know the fixes are complete when:
1. Searching for "Task 17" only shows "Natural Language Planner"
2. "Find or build" pattern is clearly explained in 2+ places
3. No claims about "only Task 17 uses PocketFlow"
4. Template variables marked as planner-internal everywhere
5. All node names use hyphenated format
6. No specific task counts mentioned
7. MCP clearly marked as v2.0
8. Two-tier AI architecture documented
9. CLI examples show MVP vs v2.0 distinction
10. ADR file exists explaining PocketFlow usage

## Critical Warning

DO NOT trust the documentation over tasks.json. The tasks.json file is the source of truth. When in doubt, check there. The documentation is what we're fixing because it's wrong.
