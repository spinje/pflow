# Task 24: Implement Workflow Manager - Agent Instructions

## The Problem You're Solving

Currently, workflow management is scattered across the codebase with no central authority - there are 4 different implementations of workflow loading, no save functionality exists (critical gap for "Plan Once, Run Forever"), and a format mismatch between components where the Context Builder expects workflows wrapped in metadata while WorkflowExecutor expects raw IR. This fragmentation blocks the Natural Language Planner (Task 17) from generating workflow references and prevents users from saving generated workflows.

## Your Mission

Implement a centralized WorkflowManager service that owns the entire workflow lifecycle - saving, loading, listing, and resolving workflow names to paths - while bridging the format gap between storage (metadata wrapper) and execution (raw IR).

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development - reasoning system role, questioning assumptions, handling ambiguity, earning elegance through robustness.

**Why read first**: This mindset is critical for implementing any task correctly.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_24/task-24.md`

**Purpose**: High-level overview, objectives, and current state.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_24/starting-context/`

**Files to read (in this order):**
1. `task-24-handover.md` - Comprehensive context from Task 17 investigation
2. `task-24-spec.md` - Detailed specification and requirements

**Instructions**: Read EACH file. After each, consider what it tells you, how it relates to others, and what implementation decisions it implies.

**IMPORTANT**: The specification file (`task-24-spec.md`) is the source of truth for requirements.

## What You're Building

A centralized workflow management service that provides a clean API for all workflow operations while handling the format mismatch between how workflows are stored (with metadata wrapper) versus how they're executed (raw IR only). This enables name-based workflow references throughout the system.

Example:
```python
# Save a workflow after user approval
workflow_manager = WorkflowManager()
workflow_manager.save("fix-issue", workflow_ir)  # IR contains inputs/outputs from Task 21

# Load for discovery/display
workflow = workflow_manager.load("fix-issue")  # Returns full metadata format

# Load for execution
workflow_ir = workflow_manager.load_ir("fix-issue")  # Returns just the IR

# Enable workflow composition
if "workflow_name" in params:
    params["workflow_ir"] = workflow_manager.load_ir(params["workflow_name"])
```

## Key Outcomes You Must Achieve

### Core Functionality
- ✅ Implement save/load/list/delete operations for workflows
- ✅ Handle format transformation between metadata wrapper and raw IR
- ✅ Provide name-to-path resolution for WorkflowExecutor
- ✅ Support Task 21's new format with embedded inputs/outputs
- ✅ Replace scattered workflow loading implementations

### Integration Points
- ✅ CLI can save workflows after planner generates them
- ✅ Context Builder uses WorkflowManager instead of direct file loading
- ✅ WorkflowExecutor can resolve workflow names to paths or IR
- ✅ Natural Language Planner can use workflow names in generated IR

## Implementation Strategy

### Phase 1: Core WorkflowManager Implementation (2-3 hours)
- Create `src/pflow/core/workflow_manager.py` with basic operations
- Implement storage format with metadata wrapper
- Add format transformation methods (load vs load_ir)
- Handle file I/O with proper error handling
- Implement workflow validation

### Phase 2: Integration and Migration (2-3 hours)
- Update Context Builder to use WorkflowManager
- Add workflow saving to CLI after planner approval
- Enhance WorkflowExecutor to support workflow names
- Update any other workflow loading code
- Ensure backward compatibility if needed

### Phase 3: Testing and Documentation (1-2 hours)
- Write comprehensive unit tests for all operations
- Test format transformations
- Integration tests with Context Builder and WorkflowExecutor
- Document the new workflow lifecycle
- Update relevant documentation

### Use Parallel Execution

Always use subagents to gather information, research, verify assumptions, debug, test, and write tests to maximize efficiency and avoid context window limitations.

## Critical Technical Details

### Storage Format (Metadata Wrapper)
Workflows are stored in `~/.pflow/workflows/{name}.json` with this structure:
```json
{
  "name": "fix-issue",
  "description": "Fixes a GitHub issue and creates PR",
  "ir": {
    "ir_version": "0.1.0",
    "inputs": {
      "issue_number": {
        "description": "GitHub issue number",
        "required": true,
        "type": "string"
      }
    },
    "outputs": {
      "pr_url": {
        "description": "Created pull request URL",
        "type": "string"
      }
    },
    "nodes": [...],
    "edges": [...]
  },
  "created_at": "2025-07-29T10:00:00Z",
  "version": "1.0.0"
}
```

### Format Bridging Requirements
- `load()` returns the full format with metadata wrapper
- `load_ir()` returns just the IR for execution
- WorkflowExecutor needs raw IR (no wrapper)
- Context Builder expects metadata wrapper format

## Critical Warnings from Experience

### Format Mismatch is Real
The investigation revealed that WorkflowExecutor expects raw IR (`{"nodes": [...]}`) while Context Builder expects wrapped format (`{"name": "...", "ir": {...}}`). Your WorkflowManager MUST handle this transformation correctly or workflows won't execute.

### Task 21 Changed the Format
Task 21 moved inputs/outputs declarations into the IR itself (no longer in metadata). The Context Builder has already been updated to expect this new format. Do NOT support the old format with separate metadata-level inputs/outputs arrays.

## Key Decisions Already Made

- ✅ Use metadata wrapper for storage (preserves identity and allows future metadata)
- ✅ WorkflowManager goes in `src/pflow/core/workflow_manager.py`
- ✅ Start with minimal API, make it extensible for future features
- ✅ No backward compatibility needed for old format (MVP has no users)
- ✅ WorkflowExecutor should support both workflow_ref (path) and workflow_name

**📋 Note on Specifications**: If a specification file exists, it is authoritative. Follow it precisely unless you discover a critical issue (document deviation or ask for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ WorkflowManager can save, load, list, and delete workflows
- ✅ Format transformation works correctly (load vs load_ir)
- ✅ Context Builder uses WorkflowManager instead of direct file loading
- ✅ CLI can save workflows after planner generates them
- ✅ WorkflowExecutor can use workflow names instead of just paths
- ✅ All existing tests still pass
- ✅ New comprehensive tests for WorkflowManager
- ✅ `make test` passes
- ✅ `make check` passes

## Common Pitfalls to Avoid

- Don't forget to handle the format mismatch - this is critical!
- Don't support the old metadata format with separate inputs/outputs arrays
- Don't use relative paths in WorkflowExecutor - use WorkflowManager's methods
- Don't forget to validate workflow names (no special characters, conflicts)
- Don't implement complex features like versioning - keep it minimal
- Don't break existing Context Builder functionality

## 📋 Create Your Implementation Plan FIRST

Before writing code, create a comprehensive implementation plan to prevent duplicate work, identify dependencies, optimize parallelization, and surface unknowns early.

### Step 1: Context Gathering with Parallel Subagents

Deploy parallel subagents for:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Workflow Loading Analysis**
   - Task: "Analyze all existing workflow loading implementations in the codebase, including _load_saved_workflows in context_builder.py, _load_workflow_file in WorkflowExecutor, and any others. Document their differences and requirements."
   - Task: "Examine the workflow validation logic in _validate_workflow_fields and understand what fields are required vs optional"

2. **Integration Points Discovery**
   - Task: "Find all places in the codebase that load or reference workflows, including CLI, Context Builder, and WorkflowExecutor"
   - Task: "Analyze how the CLI handles workflow execution and where workflow saving should be integrated"

3. **Format Analysis**
   - Task: "Compare the expected formats between Context Builder (metadata wrapper) and WorkflowExecutor (raw IR) to understand the exact transformation needed"
   - Task: "Check if there are any existing workflow files in ~/.pflow/workflows/ to understand the current format"

4. **Testing Pattern Analysis**
   - Task: "Examine existing tests for workflow loading in test_planning/test_workflow_loading.py to understand test patterns"
   - Task: "Find test utilities for creating test workflows and understand the test data format"
```

> Note: Be specific and detailed in subagent prompts, providing exact context and expectations. The above examples is just the descriptions of what to do not the full prompts you should use.

### Step 2: STOP AND DISCUSS WITH USER

**🛑 IMPORTANT: After completing context gathering with subagents, you MUST stop and discuss the findings with the user before creating your implementation plan.**

Create a discussion document at: `.taskmaster/tasks/task_24/implementation/context-discussion.md`

Include in your discussion:
1. **Key Findings** - What you discovered during context gathering
2. **Clarifying Questions** - Any ambiguities or uncertainties you need resolved
3. **Design Decisions** - Major architectural or implementation choices that need user input
4. **Potential Risks** - Issues or challenges you've identified
5. **Recommended Approach** - Your suggested path forward based on findings

Present options with checkboxes for user selection when appropriate:
```markdown
## Design Decision: Storage Location
- [ ] Option A: Store in ~/.pflow/workflows/ (current approach)
- [ ] Option B: Store in project-specific .pflow/ directory
- [ ] Option C: Support both with configuration

**Recommendation**: Option A - maintains consistency with existing patterns
```

**Wait for user confirmation and decisions before proceeding to Step 3.**

### Step 3: Write Your Implementation Plan

Create at: `.taskmaster/tasks/task_24/implementation/implementation-plan.md`

Include:
1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - Order requirements
3. **Subagent task assignments** - No conflicts, one subagent per file
4. **Risk identification** - Mitigation strategies
5. **Testing strategy** - Verification approach

### Step 4: Subagent Task Scoping

**✅ GOOD Subagent Tasks:**
```markdown
- "Implement the save() method in workflow_manager.py that validates the workflow name, adds metadata fields (created_at, version), and saves to ~/.pflow/workflows/{name}.json"
- "Update _load_saved_workflows() in context_builder.py to use WorkflowManager.list_all() instead of direct file loading"
- "Write unit tests for WorkflowManager.load_ir() method that verify it correctly extracts just the IR from the metadata wrapper"
```

**❌ BAD Subagent Tasks:**
```markdown
- "Implement the entire WorkflowManager" (too broad)
- "Update all workflow loading code" (multiple files, conflicts likely)
- "Fix any issues you find" (too vague)
```

**Key Rules:**
- One subagent per file
- Specific, bounded edits when modifying existing files
- Include full context about what the subagent needs to know
- Never assign overlapping file modifications
- Always use subagents to fix bugs, test, and write tests
- Always use subagents to gather information from the codebase or docs
- Parallelise only when subtasks are independent and with explicit bounds
- Subagents are your best weapon against unverified assumptions
- Always define termination criteria for subagents

### Implementation Plan Template

```markdown
# Task 24 Implementation Plan

## Context Gathered
### Workflow Loading Patterns
[Document different loading implementations found]

### Format Differences
[Exact differences between Context Builder and WorkflowExecutor formats]

### Integration Points
[All places that need WorkflowManager integration]

## Implementation Steps

### Phase 1: Core WorkflowManager (Parallel Possible)
1. **Create WorkflowManager class** (Subagent A)
   - Files: src/pflow/core/workflow_manager.py
   - Methods: save, load, load_ir, list_all, exists, delete, get_path

2. **Create WorkflowManager tests** (Subagent B)
   - Files: tests/test_core/test_workflow_manager.py
   - Test all methods, format transformation, error cases

### Phase 2: Integration (Sequential)
[Continue with integration tasks]

## Risk Mitigation
| Risk | Mitigation Strategy |
|------|-------------------|
| Format mismatch bugs | Comprehensive tests for load vs load_ir |
| Breaking Context Builder | Test Context Builder after migration |

## Validation Strategy
[How to verify each component works correctly]
```

### When to Revise Your Plan

Update when: context reveals new requirements, obstacles appear, dependencies change, better approaches emerge. Document changes with rationale.

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_24/implementation/progress-log.md`

```markdown
# Task 24 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update AS YOU WORK** - every discovery, bug, insight!

### Implementation Steps

1. **Understand the format mismatch thoroughly** - This is the core challenge
2. **Create WorkflowManager with core methods** - Start with save/load/load_ir
3. **Write comprehensive tests** - Especially for format transformation
4. **Integrate with Context Builder** - Replace _load_saved_workflows usage
5. **Add workflow saving to CLI** - After planner generates workflows
6. **Enhance WorkflowExecutor** - Support workflow_name parameter
7. **Run all tests** - Ensure nothing is broken
8. **Document the changes** - Update relevant docs

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, append to progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What I learned]

Code that worked:
```python
# Actual code snippet
```
```

## Handle Discoveries and Deviations

When plan needs adjustment:
1. Document why original failed
2. Capture learning
3. Update plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: [what was planned]
- Why it failed: [specific reason]
- New approach: [what you're trying instead]
- Lesson: [what this teaches us]
```

## Test Creation Guidelines

**Core Principle**: "Test what matters" - Focus on quality over quantity

**Test:** Critical paths, public APIs, error handling, integration points
**Skip:** Simple getters/setters, configuration, framework code, trivial helpers

**Progress Log - Only document testing insights:**
```markdown
## 14:50 - Testing revealed edge case
While testing load_ir(), discovered that workflows without 'ir' key
crash with KeyError. Added validation to ensure 'ir' exists before
extracting. This affects error messages for corrupted files.
```

## What NOT to Do

- Don't implement workflow versioning or complex features - keep it minimal
- Don't support the old metadata format with separate inputs/outputs arrays
- Don't forget about the format mismatch - it's the core challenge
- Don't modify WorkflowExecutor's file loading logic - use WorkflowManager
- Don't implement a complex registry - simple file-based storage is sufficient
- Don't break existing functionality - ensure backward compatibility

## Getting Started

1. Read the epistemic manifesto to understand the approach
2. Read all context files to understand requirements
3. Deploy subagents to analyze existing workflow loading code
4. Create your implementation plan
5. Start progress log and update continuously
6. Begin with WorkflowManager core implementation
7. Test format transformation thoroughly

## Final Notes

- The format mismatch between Context Builder and WorkflowExecutor is real and must be handled
- Task 21 already updated the format - inputs/outputs are in the IR now
- This is critical infrastructure that unblocks the Natural Language Planner
- Keep the API minimal but extensible for future enhancements
- Focus on correctness over features

## Remember

- You're building the bridge between scattered implementations
- Format transformation is the key challenge
- Every workflow operation should go through WorkflowManager
- Test the format mismatch handling extensively
- Document your discoveries in the progress log

You're implementing a critical piece of infrastructure that will unify workflow management across the entire pflow system. Make it robust, make it clean, and make it the single source of truth for workflows!
