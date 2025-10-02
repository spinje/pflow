# Task 71: Extend CLI Commands with tools for agentic workflow building - Agent Instructions

## The Problem You're Solving

AI agents currently cannot effectively build and debug pflow workflows because they lack discovery capabilities and get almost no error context when things fail. Agents receive generic "Workflow execution failed" messages instead of actionable error details, making autonomous workflow development impossible.

## Your Mission

Expose the planner's internal discovery capabilities as CLI commands, add pre-flight validation, and enhance error output to show rich context. This enables AI agents to discover, build, validate, and debug workflows autonomously using the same intelligent discovery approach the planner uses internally.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_71/task-71.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_71/starting-context/`

**Files to read (in this order):**
1. `COMPLETE_RESEARCH_FINDINGS.md` - Comprehensive research showing direct node reuse pattern
2. `ERROR_FLOW_ANALYSIS.md` - Deep dive on error handling and what needs to be exposed
3. `task-71-spec.md` - The specification (FOLLOW THIS PRECISELY)
4. `IMPLEMENTATION_REFERENCE.md` - Step-by-step implementation with exact code snippets
5. `CLI_COMMANDS_SPEC.md` - Detailed command specifications
6. `IMPLEMENTATION_GUIDE.md` - Quick implementation guide with patterns
7. `technical-implementation-reference.md` - Additional technical details
8. `research-findings.md` - Historical research context

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-71-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

You're adding CLI commands that enable AI agents to discover pflow capabilities through intelligent, LLM-powered discovery - the same way the planner works internally. Plus critical enhancements for validation and error visibility.

Example workflow for agents:
```bash
# Discover components
pflow workflow discover "analyze GitHub PRs"
pflow registry discover "fetch GitHub data and process it"

# Get details
pflow registry describe github-get-pr llm

# Validate before execution
pflow --validate-only draft.json repo=owner/repo pr_number=123

# Execute with rich error output
pflow --no-repair draft.json repo=owner/repo

# Save for reuse
pflow workflow save draft.json my-workflow "Description"
```

## Key Outcomes You Must Achieve

### Discovery Commands
- `pflow workflow discover` - LLM-powered workflow discovery using WorkflowDiscoveryNode
- `pflow registry discover` - LLM-powered node selection using ComponentBrowsingNode
- `pflow registry describe` - Full node specifications using build_planning_context()
- All using direct node reuse pattern: `node.run(shared)`

### Validation & Execution
- `--validate-only` flag - Pre-flight validation using ValidatorNode
- Enhanced error output showing raw API responses and template context
- `pflow workflow save` - Save workflows to global library with metadata

### Documentation
- Complete AGENT_INSTRUCTIONS.md showing discovery-first workflow
- All commands fully documented with examples

## Implementation Strategy

### Phase 1: workflow discover Command (30 min)
1. Open `src/pflow/cli/commands/workflow.py`
2. Add WorkflowDiscoveryNode import
3. Implement discover_workflows command using node.run(shared) pattern
4. Format and display results with confidence scores

### Phase 2: registry discover Command (30 min)
1. Open `src/pflow/cli/commands/registry.py`
2. Add ComponentBrowsingNode import
3. Implement discover_nodes command using node.run(shared) pattern
4. Display planning_context output directly

### Phase 3: registry describe Command (30 min)
1. Stay in `src/pflow/cli/commands/registry.py`
2. Add build_planning_context import
3. Implement describe_nodes command accepting multiple node IDs
4. Validate node IDs exist before calling context builder

### Phase 4: --validate-only Flag (45 min)
1. Open `src/pflow/cli/main.py`
2. Add flag around line 2792 with other CLI options
3. Add validation logic after workflow loading using ValidatorNode
4. Display 4-layer validation results and exit without execution

### Phase 5: workflow save Command (30 min)
1. Return to `src/pflow/cli/commands/workflow.py`
2. Implement save_workflow using WorkflowManager.save() directly
3. Add --generate-metadata option using MetadataGenerationNode
4. Include --delete-draft and --force options

### Phase 6: Enhanced Error Output (30 min)
1. Back to `src/pflow/cli/main.py`
2. Update _handle_workflow_error to accept ExecutionResult parameter
3. Display rich error context from result.errors
4. Show raw API responses, template context, available fields

### Phase 7: Create AGENT_INSTRUCTIONS.md (45 min)
1. Create comprehensive guide in `docs/AGENT_INSTRUCTIONS.md`
2. Show complete discovery → validation → execution workflow
3. Include error handling examples and troubleshooting

### Use Subagents effectively

Use subagents to maximize efficiency and avoid context window limitations.

> Always use @agent-pflow-codebase-searcher to gather information, context, do research and verifying assumptions. This is important!
> Always use the @agent-test-writer-fixer subagent for writing tests, fixing test failures, and debugging test issues.
> Always give subagents small isolated tasks, never more than fixes for one file at a time.
> Always deploy subagents in parallel, never sequentially. This means using ONE function call block to deploy all subagents simultaneously.

Implementation should be done by yourself! Write tests using the @agent-test-writer-fixer subagent AFTER implementation is complete.

## Critical Technical Details

### Direct Node Reuse Pattern
The key discovery: planner nodes work standalone without a Flow:
```python
node = WorkflowDiscoveryNode()
shared = {"user_input": query, "workflow_manager": WorkflowManager()}
action = node.run(shared)
# Results in shared["discovery_result"] and shared["found_workflow"]
```

### Error Information Flow
Nodes capture rich error data but CLI doesn't show it:
```python
# Nodes store full responses:
shared["response"] = full_api_response  # Rich error details
shared["error"] = "HTTP 422"  # But only generic message propagated

# Fix: Pass ExecutionResult to error handler
def _handle_workflow_error(ctx, result, ...):  # Add result parameter
    # Display result.errors with full context
```

### CLI Parameter Syntax
Remember pflow's actual syntax (no "execute" subcommand):
```bash
# Correct:
pflow --no-repair workflow.json param1=value param2=value

# Wrong:
pflow execute workflow.json --param param1=value
```

### LLM Integration Already Solved
Nodes handle all LLM calls internally - just run them:
- Error handling built in
- Structured output with Pydantic
- Prompt caching configured
- No additional LLM logic needed

## Critical Warnings from Experience

### Don't Extract Logic from Nodes
The research proved nodes can run standalone. DO NOT create wrapper functions or extract logic. Use nodes directly with `node.run(shared)`. The test suite has 350+ examples proving this works.

### Error Context Already Exists
The error information is already captured in shared store and ExecutionResult.errors. You're not creating new error capture - just displaying what's already there but hidden.

### Validation Must Not Execute
The --validate-only flag must perform pure validation with NO side effects. Use ValidatorNode's 4-layer validation but exit before any execution.

## Key Decisions Already Made

1. **Direct node reuse without extraction** - Just `node.run(shared)`
2. **Commands go under existing groups** - `workflow discover`, not `discover-workflows`
3. **--validate-only is a flag, not a command** - Added to main CLI
4. **Enhanced errors for all users** - Not just agents with --no-repair
5. **No new error capture needed** - Just display existing ExecutionResult.errors
6. **Use existing context builders** - They already return markdown ready for display

**📋 Note on Specifications**: The specification file (`task-71-spec.md`) is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ `pflow workflow discover` returns matching workflows with metadata
- ✅ `pflow registry discover` returns relevant nodes with full interfaces
- ✅ `pflow registry describe` shows complete node specifications
- ✅ `pflow --validate-only` performs 4-layer validation without execution
- ✅ `pflow workflow save` saves to library with optional metadata generation
- ✅ Enhanced error output shows raw API responses and template context
- ✅ AGENT_INSTRUCTIONS.md provides complete agent workflow guide
- ✅ All test criteria from spec pass
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)

## Common Pitfalls to Avoid

1. **Creating wrapper functions** - Use nodes directly with `node.run(shared)`
2. **Extracting node logic** - The nodes are designed for standalone use
3. **Skipping validation in --validate-only** - Must validate without any execution
4. **Using wrong CLI syntax** - No "execute" subcommand, no --param prefix
5. **Inventing error capture** - The data exists, just needs display
6. **Modifying node code** - Only modify CLI layer, not nodes themselves
7. **Adding features not in spec** - Stick to the 6 commands/enhancements listed

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple subagents won't edit the same files
2. **Identifies dependencies**: Discover what needs to be built in what order
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Command Structure Analysis**
   - Task: "Analyze how existing commands in src/pflow/cli/commands/workflow.py are structured and find the pattern for adding new commands"
   - Task: "Examine src/pflow/cli/commands/registry.py to understand the registry command group structure"

2. **Node Integration Discovery**
   - Task: "Find how WorkflowDiscoveryNode and ComponentBrowsingNode are imported and used in the planner"
   - Task: "Analyze how ValidatorNode performs its 4-layer validation"

3. **Error Handling Analysis**
   - Task: "Trace how ExecutionResult and its errors are currently handled in src/pflow/cli/main.py"
   - Task: "Find _handle_workflow_error function and understand its current implementation"

4. **Testing Pattern Analysis**
   - Task: "Examine tests/test_cli/ structure for CLI command testing patterns"
   - Task: "Find existing tests for workflow and registry commands"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_71/implementation/implementation-plan.md`

Include all phases, dependencies, and specific subagent assignments following the template format.

### When to Revise Your Plan

Update your plan when context gathering reveals new requirements or implementation hits obstacles. Document changes with rationale.

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_71/implementation/progress-log.md`

```markdown
# Task 71 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Create Implementation Plan (SECOND!)

Follow the planning instructions to create a comprehensive plan before any coding.

### 2. Implement discovery commands
Add workflow discover and registry discover commands using direct node reuse

### 3. Add registry describe command
Implement node detail viewing using build_planning_context()

### 4. Implement --validate-only flag
Add pre-flight validation capability to main CLI

### 5. Add workflow save command
Enable saving workflows to global library with metadata

### 6. Enhance error output
Update error handling to show rich context

### 7. Create agent documentation
Write comprehensive AGENT_INSTRUCTIONS.md

### 8. Write and run tests
Deploy test-writer-fixer for comprehensive test coverage

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to add workflow discover command...

Result: WorkflowDiscoveryNode runs perfectly standalone
- ✅ What worked: node.run(shared) pattern works exactly as documented
- ❌ What failed: Initially forgot to import WorkflowManager
- 💡 Insight: The nodes really are designed for CLI reuse

Code that worked:
```python
node = WorkflowDiscoveryNode()
shared = {"user_input": query, "workflow_manager": WorkflowManager()}
action = node.run(shared)
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: Create new error extraction logic
- Why it failed: ExecutionResult.errors already has everything
- New approach: Just pass result to error handler and display
- Lesson: Always check what data structures already exist
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test that discovery commands return relevant results
- Test validation catches errors without execution
- Test error output includes raw responses
- Test save command validates and stores correctly

**What to test**:
- **Discovery accuracy**: Commands return relevant components
- **Validation layers**: All 4 layers work independently
- **Error display**: Rich context is shown
- **Save functionality**: Workflows saved to correct location

**What NOT to test**:
- Internal node logic (already tested)
- Context builder functions (already tested)
- LLM responses (mock them)

**Progress Log - Only document testing insights**:
```markdown
## 15:30 - Testing revealed validation gap
--validate-only was still connecting to LLMs. Added early exit
to prevent any external calls during validation-only mode.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** extract logic from planner nodes - Use them directly
- **DON'T** create wrapper functions - `node.run(shared)` is sufficient
- **DON'T** modify node implementations - Only touch CLI layer
- **DON'T** add features not in spec - No caching, no extra commands
- **DON'T** use wrong CLI syntax - No "execute" subcommand
- **DON'T** invent new error capture - Display what already exists
- **DON'T** skip the --validate-only implementation - It's critical

## Getting Started

1. Read the epistemic manifesto to understand the approach
2. Read all context files in order, especially IMPLEMENTATION_REFERENCE.md
3. Create your progress log and implementation plan
4. Start with Phase 1: workflow discover command
5. Test frequently: `pytest tests/test_cli/ -v -k discover`

## Final Notes

- The research proved direct node reuse works - trust it
- Error information already exists - just needs display
- IMPLEMENTATION_REFERENCE.md has exact code snippets - use them
- Focus on exposing existing capabilities, not creating new ones
- This enables the entire agent workflow ecosystem

## Remember

You're exposing the planner's proven discovery approach to agents, enabling them to build workflows autonomously. The infrastructure already exists - you're just making it accessible via CLI. The research has proven every aspect of this approach works.

The key insight: agents need the same discovery and error visibility that human developers need. By exposing what the planner uses internally and showing the rich error context that's already captured, you're enabling true autonomous workflow development.

Good luck! This feature will transform how AI agents interact with pflow, making them first-class citizens in the workflow development process.