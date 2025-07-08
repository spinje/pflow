# Next Actions: pflow Documentation Fixes

**Created**: 2025-01-08
**Purpose**: Specific next steps for AI agent to complete documentation fixes

## Immediate Context

You are fixing documentation contradictions in pflow. The kickstart prompt has been created, user decisions made, and plan finalized. Now you need to execute.

## Essential Files to Have Open

1. **Source of Truth**: `.taskmaster/tasks/tasks.json`
2. **Contradictions Report**: `/Users/andfal/projects/pflow/scratchpads/documentation-contradictions-report.md`
3. **Resolution Plan**: `/Users/andfal/projects/pflow/scratchpads/documentation-resolution-plan.md`
4. **Kickstart Prompt**: `/Users/andfal/projects/pflow/scratchpads/documentation-fixes-kickstart-prompt.md`

## Phase 1: Critical Fixes (DO FIRST - 20 minutes)

### 1.1 Fix Task 17 References (5 minutes)

**Use grep first**: `grep -r "Task 17" docs/`

**Must fix**:
```bash
docs/features/mvp-implementation-guide.md:160
# Currently says: "**Shell node** (Task 17): `shell-exec` for command execution"
# Change to: Remove this line entirely (shell nodes are in Task 13)

docs/features/implementation-roadmap.md:75
# Currently says: Task 17 as shell node
# Change to: "**Natural Language Planner System** (Task 17): Transform natural language into workflows"
```

### 1.2 Add "Find or Build" Documentation (10 minutes)

**In `docs/features/planner.md`**, add new section after existing content:

```markdown
## The "Find or Build" Pattern

pflow's core innovation is semantic workflow discovery that enables the "Plan Once, Run Forever" philosophy:

### How It Works

1. **User Intent**: `pflow "analyze AWS costs for last month"`
2. **Semantic Search**: System searches existing workflows by meaning, not exact names
3. **Discovery**:
   - Finds: `aws-cost-analyzer` workflow (even though names don't match exactly)
   - Prompts: "Found similar workflow 'aws-cost-analyzer'. Use this?"
4. **Or Build**: If no match found, generates new workflow from natural language
5. **Save & Reuse**: New workflows saved for future semantic discovery

### Implementation Details

The pattern is implemented in `src/pflow/planning/discovery.py`:
- `find_similar_workflows(user_input, saved_workflows)` - semantic matching
- Uses LLM embeddings or similarity scoring
- Returns ranked list of potential matches
- Enables discovery by intent, not memorized names

### Example Flow

```bash
# First user:
pflow "check github issues and create summary"
# → No existing workflow found
# → Generates: github-list-issues >> filter-open >> create-summary
# → Saves as: 'github-issue-summary'

# Later user (different phrasing):
pflow "summarize open github tickets"
# → Finds 'github-issue-summary' by semantic similarity
# → Suggests: "Use existing 'github-issue-summary' workflow?"
# → Instant execution without regeneration
```

This pattern eliminates the need to remember exact workflow names while ensuring maximum reuse.
```

**In `docs/features/mvp-implementation-guide.md`**, add to Core Vision section (after line ~50):

```markdown
### The "Find or Build" Pattern

At the heart of pflow is semantic workflow discovery. When you type `pflow "analyze costs"`, the system:
1. Searches existing workflows by semantic meaning (not exact names)
2. If found: Suggests reuse of similar workflows
3. If not found: Builds new workflow from your description

This enables true "Plan Once, Run Forever" - workflows are discovered by intent, not memorized names.
```

### 1.3 Fix PocketFlow Misunderstanding (5 minutes)

**In `docs/CLAUDE.md`** around line 70-75:
- Remove: "Key insight: ONLY Task 17 (Natural Language Planner) uses PocketFlow internally"
- Remove: Reference to `architecture/adr/001-use-pocketflow-for-orchestration.md`
- Add: "pflow is built entirely ON the PocketFlow framework. All nodes inherit from pocketflow.BaseNode, and all workflow execution uses pocketflow.Flow objects."

**Create `docs/architecture/adr/001-use-pocketflow-for-orchestration.md`**:

```markdown
# ADR-001: Use PocketFlow for Workflow Orchestration

## Status
Accepted

## Date
2025-06-18 (Project inception)

## Context
pflow needs a robust workflow execution engine that handles:
- Node orchestration with deterministic execution
- Error handling and retry logic
- Data flow between nodes via shared store
- Action-based routing between nodes

## Decision
We will build pflow entirely ON the PocketFlow framework:
- All nodes inherit from `pocketflow.BaseNode`
- All workflow execution uses `pocketflow.Flow` objects
- The IR compiler (Task 4) produces PocketFlow Flow objects
- We use PocketFlow's `>>` operator for node chaining
- The shared store pattern aligns with PocketFlow's design

## Consequences

### Positive
- Proven workflow execution patterns
- No need to reinvent orchestration logic
- Consistent execution model throughout
- Built-in error handling and retry mechanisms
- Natural `>>` operator for workflow composition

### Negative
- Dependency on external framework
- Must follow PocketFlow's patterns
- Limited by PocketFlow's capabilities

### Clarification
This is NOT limited to Task 17. The entire pflow runtime is built on PocketFlow:
- Task 4: Compiles IR to PocketFlow objects
- Task 11: All file nodes inherit from BaseNode
- Task 13: All platform nodes inherit from BaseNode
- Task 17: Uses PocketFlow for planner implementation
- Execution: All workflows run as PocketFlow Flows
```

## Phase 2: Structural Updates (15 minutes)

### 2.1 Update Task Structure (5 minutes)

**In Both** `docs/features/mvp-implementation-guide.md` AND `docs/features/implementation-roadmap.md`:

Find Phase 3 sections. Currently they list tasks 18-21, 29-31. Change to:

```markdown
### Phase 3: Natural Language Planning (Weeks 6-7)

**Goal**: Enable workflow generation from natural language input - THE CORE FEATURE
**Tasks**: Task 17 - Comprehensive Natural Language Planner System

**Key Deliverables**:
- **Natural Language Planner System** (Task 17):
  - Workflow Generation Engine - Transform natural language → workflows
  - Template Resolution - Planner-internal variable substitution
  - Workflow Discovery - Semantic "find or build" pattern
  - Prompt Templates - Well-crafted prompts for generation
  - Approval & Storage - User verification and persistence

This single comprehensive task (formed by merging tasks 17-20) implements the core innovation that makes pflow unique.
```

### 2.2 Remove Task Counts (5 minutes)

**Search and replace** in all docs:
- "40 MVP tasks" → "multiple implementation phases"
- "31 active tasks" → "comprehensive task implementation"
- "48 total tasks" → "complete development plan"

Focus on phases and outcomes, not counts.

### 2.3 Clarify Template Variables (5 minutes)

**In `docs/features/planner.md`**, add section:

```markdown
## Template Variable Resolution

### Important: Planner-Internal Only

Template variables (like `$issue_number`, `$file_content`) are resolved ONLY by the planner during workflow generation. They are NOT a runtime feature.

**How it works**:
1. Planner generates workflows with template variables: `$issue_data`
2. During planning, these are mapped to shared store keys: `shared["issue_data"]`
3. The compiler passes template variables unchanged
4. Only the planner performs substitution

**Example**:
```yaml
# Planner generates:
nodes:
  - id: analyze
    params:
      prompt: "Analyze this issue: $issue_data"

# Planner resolves to:
nodes:
  - id: analyze
    params:
      prompt: "Analyze this issue: {shared['issue_data']}"
```

This is NOT a runtime templating engine - it's purely for planner use during workflow generation.
```

## Phase 3: User-Decided Updates (10 minutes)

### 3.1 MCP as v2.0 (2 minutes)

**In `docs/prd.md`** section 8:
- Change: `## 8. MCP Integration & Unified Registry`
- To: `## 8. MCP Integration & Unified Registry (v2.0 Feature)`
- Add after header: `> **Note**: This feature is deferred to v2.0. See MVP scope for current implementation.`

### 3.2 Two-Tier AI Architecture (5 minutes)

**In `docs/architecture/architecture.md`** after section 3.3, add:

```markdown
### 3.4 Two-Tier AI Architecture

pflow implements a two-tier AI system optimized for different use cases:

#### Tier 1: General LLM Node (`llm`)
- **Purpose**: Fast, lightweight text processing
- **Interface**: `shared['prompt']` → `shared['response']`
- **Use Cases**:
  - Commit messages
  - Text summaries
  - Simple transformations
  - Quick analysis
- **Characteristics**:
  - No project context required
  - Minimal token usage (~100-500 tokens)
  - Sub-second response times
  - No file system access
  - Stateless operation

#### Tier 2: Claude Code Super Node (`claude-code`)
- **Purpose**: Comprehensive AI-assisted development
- **Interface**: `shared['prompt']` → `shared['code_report']`
- **Use Cases**:
  - Bug fixes with code changes
  - Feature implementation
  - Complex code analysis
  - Multi-file refactoring
- **Characteristics**:
  - Full project context and file system access
  - Higher token usage (1000-5000 tokens)
  - 20-60 second execution times
  - Access to all development tools
  - Maintains conversation context

This separation allows workflows to optimize for speed (llm) or capability (claude-code) as needed. For example:
- Use `llm` for generating a commit message from changes
- Use `claude-code` for implementing the fix described in an issue
```

### 3.3 CLI Examples Update (3 minutes)

**Find all CLI examples** and update them to show both MVP and v2.0:

Template:
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

## Phase 4: Final Polish (10 minutes)

### 4.1 Standardize Node Names

**Search for** node name examples and ensure all use hyphens:
- ✅ Correct: `github-get-issue`, `read-file`, `git-commit`
- ❌ Wrong: `github_get_issue`, `read_file`, `git_commit`

### 4.2 Update Cross-References

After making changes:
1. Check internal links still work
2. Update `docs/index.md` if any file descriptions changed
3. Search for any remaining contradictions

### 4.3 Final Validation

Run through the checklist:
- [ ] All Task 17 references = "Natural Language Planner"
- [ ] "Find or Build" documented in planner.md and mvp-implementation-guide.md
- [ ] No "only Task 17 uses PocketFlow" claims
- [ ] Template variables marked as planner-internal
- [ ] All node names hyphenated
- [ ] No specific task counts
- [ ] MCP marked as v2.0
- [ ] Two-tier AI documented
- [ ] CLI examples show MVP vs v2.0
- [ ] ADR file created

## Commit Strategy

Make commits after each phase:
1. "Fix Task 17 references and document find-or-build pattern"
2. "Update task structure and clarify template variables"
3. "Add user-decided documentation updates"
4. "Polish documentation and standardize formatting"

## If You Get Stuck

1. Check `.taskmaster/tasks/tasks.json` - it's the truth
2. Read the contradictions report to understand what's wrong
3. Follow the kickstart prompt step by step
4. The comprehensive context doc has all conceptual understanding

## Time Estimate

- Phase 1: 20 minutes (critical fixes)
- Phase 2: 15 minutes (structural updates)
- Phase 3: 10 minutes (user decisions)
- Phase 4: 10 minutes (polish)
- Total: ~55 minutes

Begin with Phase 1. These are the most critical fixes that unblock understanding.
