# Task 52: Improve planner with "plan" and "requirements" steps - Agent Instructions

## The Problem You're Solving

The current planner pipeline sometimes fails on complex workflows because it attempts to generate workflows directly without first understanding requirements or creating a plan. This leads to poor first-attempt success rates, unhelpful error messages for impossible requirements, and unnecessary retries that could be avoided with better upfront analysis. Users get frustrated when the planner can't explain why their request is impossible or too vague.

## Your Mission

Implement Requirements Analysis and Planning nodes to enhance the planner pipeline, creating a two-step analysis phase before workflow generation. These nodes will extract WHAT needs to be done (requirements) and determine HOW to do it (planning), with Planning and Generator using a multi-turn conversation for context accumulation and learning from validation errors.

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
**File**: `.taskmaster/tasks/task_52/task-52.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. THIRD: PocketFlow Framework Foundation
**File**: `pocketflow/__init__.py`

**Purpose**: The core framework that all pflow nodes are built on. This ~100-line file contains the fundamental Node class with prep/exec/post lifecycle, Flow class for orchestration, and shared store patterns.

**Why read third**: You MUST understand the Node lifecycle and Flow routing patterns before implementing new nodes. Pay special attention to:
- How `prep()`, `exec()`, and `post()` methods work
- How Flows route between nodes using action strings
- How the shared store enables inter-node communication
- The `>>` operator for flow construction

### 4. FOURTH: Read Existing Planner Implementation IN FULL
**Files** (read both completely):
- `src/pflow/planning/nodes.py` - ALL existing planner nodes you'll be modifying and learning from
- `src/pflow/planning/flow.py` - The flow routing you'll be updating

**Purpose**: Complete understanding of the current planner implementation.

**Why read in full**: You'll be:
- Adding two new nodes following the same patterns
- Modifying the flow routing to insert these nodes
- Understanding how conversation state is passed between nodes
- Learning from existing error handling patterns

Take time to understand:
- How each existing node works (especially WorkflowDiscoveryNode, ComponentBrowsingNode, WorkflowGeneratorNode)
- How action strings route between nodes
- How the shared store is used for communication
- The retry mechanism with ValidatorNode

### 5. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_52/starting-context/`

**Files to read (in this order):**
1. `task-52-handover.md` - Critical context and design decisions from investigation phase
2. `task-52-spec.md` - The specification (FOLLOW THIS PRECISELY - source of truth for requirements)
3. `implementation-guide.md` - Comprehensive implementation patterns and examples

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-52-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

You're adding two new nodes to the planner pipeline that fundamentally change how workflows are generated:

1. **RequirementsAnalysisNode**: Extracts abstract operational requirements from templatized user input
   - Works with already-templatized input from ParameterDiscoveryNode
   - Abstracts values but keeps services explicit (e.g., "Fetch issues from GitHub" not "Fetch 20 closed issues")
   - Can fail fast if input is too vague

2. **PlanningNode**: Creates an execution blueprint using available components
   - STARTS a multi-turn conversation with `model.conversation()`
   - Outputs markdown with parseable Status and Node Chain
   - Determines feasibility: FEASIBLE/PARTIAL/IMPOSSIBLE

These work with a **multi-turn conversation** architecture where:
- Data extraction nodes (Requirements, Components) use standalone LLM calls
- Reasoning nodes (Planning, Generator) share a conversation for context accumulation
- Context caching provides ~70% cost reduction on retries

Example flow:
```python
# Standalone calls for data extraction
requirements = model.prompt(...)  # What needs to be done?
components = model.prompt(...)    # What tools available?

# Conversation for generation pipeline
conversation = model.conversation()
plan = conversation.prompt("Create plan...")
workflow = conversation.prompt("Generate workflow", schema=FlowIR)
```

## Key Outcomes You Must Achieve

### 1. Pipeline Enhancement
- Move ParameterDiscoveryNode earlier in the flow (before ComponentBrowsing)
- Add RequirementsAnalysisNode after ParameterDiscovery
- Add PlanningNode after ComponentBrowsing
- Update flow routing to connect new nodes

### 2. Core Implementation
- RequirementsAnalysisNode class with RequirementsSchema output
- PlanningNode class with markdown output and parsing
- Multi-turn conversation between Planning→Generator→Retry
- Error routing for vague/impossible requirements

### 3. Integration Updates
- ComponentBrowsingNode considers requirements in selection
- WorkflowGeneratorNode uses conversation from shared store
- Conversation preserved across retries
- Proper error messages for all failure modes

### 4. Testing & Validation
- All 25 test criteria from spec passing
- Unit tests for new nodes
- Integration tests for conversation flow
- Verify context caching benefits

## Implementation Strategy

### Phase 1: Flow Restructuring (1 hour)
1. Move ParameterDiscoveryNode earlier in flow.py
2. Add routing for new nodes
3. Add error routing paths
4. Test basic flow connectivity

### Phase 2: RequirementsAnalysisNode (2 hours)
1. Create RequirementsSchema Pydantic model
2. Implement RequirementsAnalysisNode class
3. Create requirements_analysis.md prompt
4. Add vague input detection
5. Write unit tests

### Phase 3: PlanningNode (2-3 hours)
1. Implement PlanningNode class
2. Add markdown parser for Status/Node Chain
3. Create planning.md prompt
4. Implement conversation start
5. Add feasibility assessment logic
6. Write unit tests

### Phase 4: Conversation Integration (2 hours)
1. Update WorkflowGeneratorNode to use conversation
2. Add conversation preservation on retry
3. Update ComponentBrowsingNode to consider requirements
4. Test multi-turn flow
5. Verify context caching

### Phase 5: Testing & Polish (2 hours)
1. Run all test criteria from spec
2. Add integration tests
3. Fix any issues
4. Verify no regressions

### Use Subagents effectively

Use subagents to maximize efficiency and avoid context window limitations.

> Always use @agent-pflow-codebase-searcher to gather information, context, do research and verifying assumptions. This is important!
> Always use the @agent-test-writer-fixer subagent for writing tests, fixing test failures, and debugging test issues.
> Always give subagents small isolated tasks, never more than fixes for one file at a time.
> Always deploy subagents in parallel, never sequentially. This means using ONE function call block to deploy all subagents simultaneously.

Implementation should be done by yourself! Write tests using the @agent-test-writer-fixer subagent AFTER implementation is complete.

## Critical Technical Details

### Multi-Turn Conversation Pattern
```python
# In PlanningNode.exec():
model = llm.get_model(prep_res["model_name"])
conversation = model.conversation()  # START conversation

# Store in shared for Generator
shared["planner_conversation"] = conversation

# In WorkflowGeneratorNode.prep():
conversation = shared.get("planner_conversation")

# Continue conversation for generation/retry
response = conversation.prompt(prompt, schema=FlowIR)
```

### Requirements Abstraction Rules
```python
# Input: "Get last ${issue_limit} ${issue_state} issues from GitHub"
# Output: "Fetch filtered issues from GitHub repository"

# Abstract values but keep services:
# ✅ "Fetch issues from GitHub"
# ❌ "Fetch 20 closed issues"
# ❌ "Fetch ${issue_limit} issues"
```

### Planning Output Parsing
```python
def _parse_plan_assessment(self, markdown: str) -> dict:
    import re

    status = "FEASIBLE"  # default
    node_chain = ""

    if match := re.search(r'\*\*Status\*\*:\s*(\w+)', markdown):
        status = match.group(1)

    if match := re.search(r'\*\*Node Chain\*\*:\s*([^\n]+)', markdown):
        node_chain = match.group(1).strip()

    return {"status": status, "node_chain": node_chain}
```

### Flow Routing Updates
```python
# In flow.py, update routing:
discovery_node - "not_found" >> parameter_discovery  # MOVED
parameter_discovery >> requirements_analysis         # NEW
requirements_analysis >> component_browsing
requirements_analysis - "clarification_needed" >> result_preparation  # NEW
component_browsing - "generate" >> planning         # NEW
planning >> workflow_generator
planning - "impossible_requirements" >> result_preparation  # NEW
```

### Error Detection Patterns
**Too vague input**:
- Missing action: "the deployment"
- Missing target: "process it"
- Too generic: "do the usual"

**Clear enough**:
- Has action + target: "generate changelog"
- Minimal but clear: "create github issue"

## Critical Warnings from Experience

### DON'T Put Everything in Conversation
Only Planning and Generator participate in the conversation. Requirements and Component selection are standalone LLM calls. The conversation is specifically for the generation pipeline where reasoning builds on previous context.

### DON'T Include Values in Requirements
Requirements must abstract values: "Fetch filtered issues from GitHub" not "Fetch 20 closed issues". But keep services explicit: "GitHub" not "external service".

### DON'T Forget Conversation Preservation
The conversation MUST be stored in `shared["planner_conversation"]` and passed between Planning→Generator→Retry. Without this, retries can't learn from previous attempts.

### DON'T Let Planning Suggest Any Nodes
Planning can ONLY use nodes from `browsed_components["node_ids"]`. It cannot suggest nodes that weren't selected by ComponentBrowsing.

## Key Decisions Already Made

1. **Two separate nodes** (not combined) - Single responsibility principle
2. **Requirements before Planning** - Natural WHAT→HOW progression
3. **Multi-turn conversation for Planning→Generator only** - Not all nodes
4. **Parameter Discovery moved earlier** - Provides templatization for Requirements
5. **New conversation per workflow** - Clean slate each time
6. **3 retry limit maintained** - No changes to existing retry logic
7. **Planning parses its own output** - Encapsulation of parsing logic
8. **Requirements handles mixed templatization gracefully** - Robust to partial templatization
9. **Component Browsing structure** has `node_ids`, `workflow_names`, `reasoning` (no `coverage_assessment` field)

**📋 Note on Specifications**: The specification file (`task-52-spec.md`) is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ All 25 test criteria from the spec pass
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)
- ✅ Conversation context accumulates properly across retries
- ✅ Requirements correctly abstract values while keeping services explicit
- ✅ Planning correctly parses its markdown output
- ✅ Error messages are clear for vague/impossible requirements
- ✅ Context caching provides cost reduction (verify with token usage)
- ✅ No existing planner functionality is broken

## Common Pitfalls to Avoid

1. **Don't modify Path A** - Workflow reuse path should remain unchanged
2. **Don't create new error handler nodes** - Route to existing ResultPreparationNode
3. **Don't parse planning output in Generator** - Planning parses its own output
4. **Don't include template variables in requirements** - Must be fully abstracted
5. **Don't create complex context objects** - Let conversation handle context
6. **Don't skip reading nodes.py and flow.py in full** - You need complete understanding

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

1. **Analyze Current Flow Structure**
   - Task: "Analyze src/pflow/planning/flow.py and identify exactly how ParameterDiscoveryNode is currently routed and what needs to change to move it earlier"
   - Task: "Find all action strings used in the planner and document the routing patterns"

2. **Study Existing Node Patterns**
   - Task: "Analyze WorkflowDiscoveryNode and ComponentBrowsingNode to understand the pattern for nodes that make routing decisions"
   - Task: "Study WorkflowGeneratorNode to understand how it currently handles retries and validation errors"

3. **LLM Integration Patterns**
   - Task: "Find all uses of llm.get_model() and model.prompt() in the planner to understand LLM calling patterns"
   - Task: "Search for any existing uses of model.conversation() in the codebase"

4. **Testing Patterns**
   - Task: "Analyze tests/test_planning/ structure and identify patterns for testing new nodes"
   - Task: "Find existing tests for multi-turn or conversation-based features"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_52/implementation/implementation-plan.md`

Your plan should include detailed breakdown of:
- Exact changes to flow.py routing
- RequirementsAnalysisNode implementation steps
- PlanningNode implementation with conversation handling
- Integration points with existing nodes
- Test strategy for each component

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_52/implementation/progress-log.md`

```markdown
# Task 52 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...

## [Timestamp] - Reading PocketFlow Framework
Understanding Node lifecycle and Flow routing patterns...

## [Timestamp] - Reading Planning Implementation
Reading nodes.py and flow.py in full to understand current implementation...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Create Implementation Plan (SECOND!)

Follow the instructions above to create a comprehensive plan before any coding.

### 2. Restructure the Flow

Move ParameterDiscoveryNode and add routing for new nodes in flow.py.

### 3. Implement RequirementsAnalysisNode

Create the node class, schema, and prompt following existing patterns.

### 4. Implement PlanningNode

Create the node with conversation start and markdown parsing.

### 5. Update Existing Nodes

Modify ComponentBrowsingNode and WorkflowGeneratorNode for integration.

### 6. Write Comprehensive Tests

Use test-writer-fixer subagent for all test creation.

### 7. Verify Everything Works

Run full test suite and verify all success criteria.

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - Implementing RequirementsAnalysisNode
Attempting to create the node following WorkflowDiscoveryNode pattern...

Result: Successfully created node structure
- ✅ What worked: Using existing node as template
- ❌ What failed: Initial schema was too complex
- 💡 Insight: Simpler schemas work better with structured output

Code that worked:
```python
class RequirementsAnalysisNode(Node):
    def exec(self, prep_res):
        model = llm.get_model(prep_res["model_name"])
        # Standalone call, not conversation
        response = model.prompt(prompt, schema=RequirementsSchema)
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
- Original plan: Start conversation in RequirementsAnalysisNode
- Why it failed: Requirements should be standalone for data extraction
- New approach: Only start conversation in PlanningNode
- Lesson: Conversation is for reasoning pipeline, not data extraction
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**Critical tests for this task**:
- Requirements abstraction (values removed, services kept)
- Planning markdown parsing (Status and Node Chain extraction)
- Conversation preservation across retries
- Error routing for vague/impossible inputs
- Integration between new and existing nodes

**Progress Log - Only document testing insights**:
```markdown
## 15:30 - Testing revealed conversation issue
Discovered conversation wasn't persisting because shared store
was being cleared between retries. Need to preserve
planner_conversation key explicitly.
```

## What NOT to Do

- **DON'T** modify Path A (workflow reuse) - it should remain unchanged
- **DON'T** put all nodes in conversation - only Planning and Generator
- **DON'T** create new error handler nodes - use existing ResultPreparationNode
- **DON'T** include template variables in requirements output
- **DON'T** let Planning suggest nodes outside browsed_components
- **DON'T** skip reading the full planning implementation - you need complete context
- **DON'T** add features not in spec - implement exactly what's specified

## Getting Started

1. Start by reading ALL required files in order
2. Pay special attention to PocketFlow framework patterns
3. Read nodes.py and flow.py COMPLETELY
4. Create your progress log
5. Create your implementation plan
6. Begin with flow restructuring
7. Test frequently: `pytest tests/test_planning/ -v`

## Final Notes

- The conversation architecture is the key innovation - Planning starts it, Generator continues
- Requirements abstraction is critical - no values, only operations and services
- The spec has all test criteria clearly defined - follow them precisely
- Context caching will dramatically reduce costs - verify it's working
- This enhancement will improve success rates from ~60% to >90% on complex workflows

## Remember

You're implementing a fundamental improvement to the planner that adds intelligent requirements analysis and planning before generation. The design has been thoroughly thought through and validated. Trust the architecture but verify against the spec. When faced with ambiguity, surface it rather than guessing.

The key insight: The conversation is specifically for the **generation pipeline** (Planning→Generation→Retry), not the entire planner pipeline. This focused approach keeps the conversation small and relevant while gaining the benefits of context accumulation and cost reduction.

Good luck! This enhancement will make pflow's planner significantly more intelligent and user-friendly.