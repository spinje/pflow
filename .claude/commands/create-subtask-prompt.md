# Create Subtask Implementation Prompt - Meta-Prompt for AI Agents (Task 17)

This command instructs an AI agent to generate a comprehensive implementation prompt for another AI agent who will implement a subtask of Task 17 (Natural Language Planner).

## Inputs

Inputs: $ARGUMENTS

Available inputs:
- `--subtask_number`: The number of the subtask to create an implementation prompt for (1-7, required)

> If you receive only a number (e.g., "3"), assume that is the subtask_number

## Your Task as the Prompt-Generating Agent

Generate a comprehensive implementation prompt for Subtask {{subtask_number}} of Task 17.

**Key assumption**: The implementing agent has read ALL Task 17 documentation except the subtask spec.

**Your output**: Generate the prompt and save it to `.taskmaster/tasks/task_17/starting-context/task-17-subtask-{{subtask_number}}-implementation-prompt.md`

### How to Create the Implementation Prompt

1. **Focus on the subtask specification** - The file `.taskmaster/tasks/task_17/starting-context/task-17-subtask-{{subtask_number}}-spec.md` is the PRIMARY source of truth
2. **Carefully evaluate the subtask plan** - The file `.taskmaster/tasks/task_17/starting-context/task-17-subtask-plan.md` is the plan for all the subtasks, focus especially on the subtask you are implementing. This information is critical for understanding the subtask and its dependencies to other subtasks (you should not have to read it again, you should have it in your context window)
3. **Fill in the template** with specific details from the spec and your knowledge
4. **Be explicit about interfaces** - How this subtask connects to others
5. **Include implementation specifics** - Not general Task 17 info they already know

### 🛑 Decision Points: When to STOP and ASK

**Do NOT proceed with generating the prompt if:**

1. The subtask_number doesn't match any subtask you've discussed (1-7)
2. You cannot find the subtask specification in your context
3. Critical information about dependencies or interfaces is missing
4. You're unsure whether your understanding of the two-path architecture is correct

**Instead, ask the user:**
- "I cannot find the specification for Subtask {{subtask_number}} in my context. Could you provide it?"
- "I'm not certain about the interface between Subtask {{subtask_number}} and its dependencies. Could you clarify?"
- "I need to understand the two-path architecture better. Can you confirm my understanding?"

### 📝 Quality Checks Before Output

Before generating the prompt, verify:

1. **Do I understand Task 17's two-path architecture?** Path A (reuse) vs Path B (generate)
2. **Do I know this subtask's role?** Which path(s) it belongs to
3. **Are dependencies clear?** Which subtasks must be complete first
4. **Is the convergence point understood?** How both paths meet at ParameterMappingNode
5. **Are interfaces documented?** What this subtask provides to others
6. **Have I reviewed the subtask specification?** The primary source of truth

## Template to Fill

Use this exact structure and replace ALL placeholders with content from your knowledge:

---

# Task 17 - Subtask {{subtask_number}}: {{subtask_title}} - Agent Instructions

## Critical Pre-Requirement

**IMPORTANT**: This prompt assumes you have already thoroughly read and understand:
- All Task 17 documentation in `.taskmaster/tasks/task_17/`
- The epistemic manifesto
- The two-path architecture (Path A: reuse, Path B: generate)
- How subtasks interconnect and depend on each other
- The shared progress log system

If you haven't read these yet, STOP and read them first.

## The Problem You're Solving

{{problem_statement}}
<!-- Extract from your knowledge or spec. 2-3 sentences explaining what challenge this subtask addresses within Task 17's architecture -->

## Your Mission Within Task 17

{{brief_mission_statement}}
<!-- Extract from subtask spec/description. Should be 1-2 sentences explaining this subtask's specific role in the Natural Language Planner -->

## ⚠️ Critical Context: Task 17's Two-Path Architecture

Before implementing this subtask, you MUST understand the overall architecture:

**Path A (Workflow Reuse)**: Discovery → ParameterMapping → Preparation → Result
**Path B (Workflow Generation)**: Discovery → Browsing → ParamDiscovery → Generation → Validation → Metadata → ParameterMapping → Preparation → Result

**CONVERGENCE**: Both paths meet at ParameterMappingNode - the verification gate.

**This Subtask's Role**: {{subtask_role_in_architecture}}
<!-- Clearly state which path(s) this subtask belongs to and its critical responsibility -->

## Dependencies and Prerequisites

### Subtasks That Must Be Complete
{{dependency_list}}
<!-- List which subtasks (if any) must be complete before this one -->
<!-- Example:
- ✅ Subtask 1 (Foundation): Provides directory structure and utilities
- ✅ Subtask 2 (Discovery): Provides discovery nodes that route to this subtask
-->

### Files/Outputs You'll Use From Previous Subtasks
{{previous_outputs}}
<!-- List specific files or components from completed subtasks -->
<!-- Example:
- `src/pflow/planning/utils/workflow_loader.py` from Subtask 1
- `WorkflowDiscoveryNode` routing logic from Subtask 2
-->

## Required Context Review

### Primary Source: Your Subtask Specification
**File**: `.taskmaster/tasks/task_17/starting-context/task-17-subtask-{{subtask_number}}-spec.md`

**This is your PRIMARY source of truth** for requirements, interface contracts, and implementation details specific to Subtask {{subtask_number}}.

Since you've already read all Task 17 documentation, focus on:
1. How your subtask's spec relates to the overall architecture
2. Dependencies listed in the spec vs what's actually implemented
3. Interface contracts specific to your subtask
4. Success criteria unique to this subtask

**CRITICAL**: The spec defines exact behavior and interfaces. Follow it PRECISELY.

## 🔄 Shared Progress Log (CRITICAL!)

**The progress log is SHARED across ALL Task 17 subtasks!**

**Location**: `.taskmaster/tasks/task_17/implementation/progress-log.md`

**Format for your entries**:
```markdown
## [Timestamp] - Subtask {{subtask_number}} - [What You're Trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What you learned]

Code that worked:
```python
# Actual code snippet
```
```

**IMPORTANT**:
- Always prefix entries with your subtask number
- Check previous subtask entries to understand what's already implemented
- Your insights help future subtasks avoid pitfalls

## What You're Building

{{detailed_description}}
<!-- Clear explanation of what components this subtask creates -->
<!-- Include how it interfaces with other subtasks -->

Example usage within the planner:
```python
{{usage_example}}
```

## Shared Store Contract

### Keys This Subtask READS
{{shared_store_reads}}
<!-- List exact keys from shared store this subtask expects -->
<!-- Example:
- `shared["user_input"]` - Natural language input from CLI
- `shared["discovery_result"]` - Output from WorkflowDiscoveryNode
-->

### Keys This Subtask WRITES
{{shared_store_writes}}
<!-- List exact keys this subtask adds/modifies -->
<!-- Example:
- `shared["discovered_params"]` - Parameters extracted from NL
- `shared["verified_params"]` - Parameters after verification
-->

### Expected Data Formats
{{data_formats}}
<!-- Document structure of complex data -->
<!-- Example:
```python
shared["discovered_params"] = {
    "state": "closed",
    "limit": "20"
}
```
-->

## Key Outcomes You Must Achieve

### Core Deliverables
{{deliverables_list}}
<!-- List specific components/files to create -->

### Interface Requirements
{{interface_requirements}}
<!-- How this subtask's outputs are used by others -->

### Integration Points
{{integration_points}}
<!-- Where this subtask connects to the overall flow -->

## Implementation Strategy

### Phase 1: {{phase1_name}} ({{time_estimate}})
{{phase1_tasks}}
<!-- Break down into numbered steps -->

### Phase 2: {{phase2_name}} ({{time_estimate}})
{{phase2_tasks}}

### Phase 3: {{phase3_name}} ({{time_estimate}})
{{phase3_tasks}}

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### {{technical_detail_1_title}}
{{technical_detail_1_content}}
<!-- Include code snippets for clarity -->

### {{technical_detail_2_title}}
{{technical_detail_2_content}}

<!-- Add more sections as needed based on subtask complexity -->

## Critical Warnings from Task 17 Experience

### Template Variables Are Sacred
**NEVER hardcode extracted values** - workflows must be reusable. When user says "20 issues", generate `"limit": "$limit"` NOT `"limit": "20"`.

### Understanding Your Path
Know whether your subtask belongs to Path A (reuse), Path B (generate), or both (convergence).

### {{additional_warning_title}}
{{additional_warning_content}}

## Key Decisions Already Made for Task 17

{{decisions_list}}
<!-- Extract from task-17-ambiguities.md and subtask spec -->
<!-- Include decisions about LLM model, retry strategy, etc. -->

**📋 Note on Specifications**: Your subtask specification is the authoritative source. Follow it precisely - do not deviate from specified behavior, interface contracts, or implementation requirements unless you discover a critical issue (document and ask for clarification).

## Success Criteria

Your implementation is complete when:

{{success_criteria_checklist}}
<!-- Extract from subtask spec, format as checkbox list with ✅ -->
<!-- Always include:
✅ Your subtask integrates correctly with dependencies
✅ Interface contracts are satisfied
✅ Shared store keys are properly read/written
✅ make test passes (for your subtask's tests)
✅ make check passes
✅ Progress log documents your implementation journey
-->

## Common Pitfalls to Avoid

{{pitfalls_list}}
<!-- Extract from context or generate based on subtask complexity -->
<!-- Include Task 17-specific pitfalls like hardcoding values -->

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent conflicts with other subtasks.

**Location**: `.taskmaster/tasks/task_17/subtask_{{subtask_number}}/implementation-plan.md`

### Why Planning Matters for Subtasks

1. **Prevents breaking interfaces**: Other subtasks depend on your outputs
2. **Identifies integration points**: Discover how you connect to the flow
3. **Optimizes parallelization**: Know what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Previous Subtask Analysis**
   - Task: "Analyze outputs from Subtask {{previous_number}} and identify integration points"
   - Task: "Check shared store keys written by previous subtasks"

2. **Interface Discovery**
   - Task: "Identify how {{component_name}} interfaces with other nodes in the planner"
   - Task: "Analyze the flow wiring to understand routing to/from this subtask"

3. **Testing Pattern Analysis**
   - Task: "Examine tests/test_planning/ for testing patterns"
   - Task: "Identify test fixtures from previous subtasks we can reuse"

4. **Integration Requirements**
   - Task: "Check how this subtask's outputs are used by Subtask {{next_number}}"
   - Task: "Verify shared store contract matches expectations"
```

> Note: Your prompts to the subagents should be very specific and detailed, providing full Task 17 context.

### Step 2: Write Your Implementation Plan

Your plan should include:

1. **Interface verification** - Confirm what previous subtasks provide
2. **Component breakdown** - Every node/utility to create
3. **Integration strategy** - How to connect to the overall flow
4. **Risk identification** - What could break other subtasks
5. **Testing strategy** - How to verify interfaces work

### Implementation Plan Template

```markdown
# Task 17 - Subtask {{subtask_number}} Implementation Plan

## Dependencies Verified

### From Previous Subtasks
- [What Subtask X provides that you need]
- [Integration points confirmed]

### For Next Subtasks
- [What you must provide for Subtask Y]
- [Interface contracts to maintain]

## Shared Store Contract
- Reads: [Keys you expect to exist]
- Writes: [Keys you will create/modify]

## Implementation Steps

### Phase 1: Core Components
[Detailed steps specific to your subtask]

### Phase 2: Integration
[How to connect to the planner flow]

### Phase 3: Testing
[How to verify interfaces and functionality]

## Risk Mitigation

| Risk | Impact on Other Subtasks | Mitigation Strategy |
|------|-------------------------|-------------------|
| [Risk] | [Which subtasks affected] | [How to prevent] |

## Validation Strategy
- How to verify integration with previous subtasks
- How to ensure next subtasks can use your outputs
- Path-specific testing (Path A, Path B, or convergence)
```

### When to Revise Your Plan

Your plan is a living document. Update it when:
- You discover interface mismatches with other subtasks
- Integration tests reveal issues
- Better approaches become apparent

Document plan changes in the SHARED progress log with rationale.

## Your Implementation Order

### 0. Review Shared Progress Log (FIRST!)

Check what previous subtasks have implemented: `.taskmaster/tasks/task_17/implementation/progress-log.md`

### 1. Create Your Implementation Plan (SECOND!)

Location: `.taskmaster/tasks/task_17/subtask_{{subtask_number}}/implementation-plan.md`

### Implementation Steps

{{ordered_implementation_steps}}
<!-- Extract from implementation plan or generate based on phases -->
<!-- Format as numbered list with clear actions -->
<!-- Include integration testing with previous subtasks -->

## Real-Time Learning Capture in SHARED Log

**AS YOU IMPLEMENT**, continuously append to the SHARED progress log:

```markdown
## [Timestamp] - Subtask {{subtask_number}} - [What I'm trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What I learned that affects other subtasks]

Code that worked:
```python
# Actual code snippet
```
```

**Remember**: Your insights help future subtasks!

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Consider impact on other subtasks
4. Update the plan with new approach
5. Continue with new understanding

Append deviation to SHARED progress log:
```markdown
## [Time] - Subtask {{subtask_number}} - DEVIATION FROM PLAN
- Original plan: [what was planned]
- Why it failed: [specific reason]
- Impact on other subtasks: [who needs to know]
- New approach: [what you're trying instead]
- Lesson: [what this teaches us about Task 17]
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test interfaces and integration"

**Focus on**:
- Interface contracts with other subtasks
- Shared store keys read/written correctly
- Routing logic (action strings)
- Integration with previous subtask outputs
- Path-specific behavior (A, B, or convergence)

**What to test**:
- **Interface contracts**: Data formats between subtasks
- **Routing logic**: Correct action strings returned
- **Shared store**: Keys properly read/written
- **Integration points**: Connections to other subtasks
- **Path behavior**: Correct execution for your path(s)

**Progress Log - Only document testing insights**:
```markdown
## {{time}} - Subtask {{subtask_number}} - Testing revealed interface issue
Discovered that Subtask 2's output format doesn't match what we expected.
Need to coordinate on the structure of discovery_result.
```

**Remember**: Integration tests > isolated unit tests for subtasks

## What NOT to Do

{{what_not_to_do_list}}
<!-- Include subtask-specific and Task 17 general anti-patterns -->
<!-- Example:
- DON'T hardcode parameter values - use template variables
- DON'T break interface contracts with other subtasks
- DON'T modify shared store keys from other subtasks
- DON'T skip integration testing
-->

## Getting Started

{{getting_started_steps}}
<!-- Provide concrete first steps -->
<!-- Include checking previous subtask outputs -->
<!-- Include test command for your specific components -->

## Final Notes

{{final_notes}}
<!-- Subtask-specific reminders -->
<!-- Emphasize critical interfaces -->
<!-- Include warnings about affecting other subtasks -->

## Remember

{{remember_section}}
<!-- Final reinforcement of key concepts -->
<!-- Remind about two-path architecture -->
<!-- Emphasize this subtask's role in the bigger picture -->

You're implementing Subtask {{subtask_number}} of 7 for Task 17's Natural Language Planner. Your work enables pflow's "Plan Once, Run Forever" philosophy. The two-path architecture with convergence at ParameterMappingNode is the key innovation. Your subtask is a critical piece of this sophisticated meta-workflow.

{{motivational_ending}}
<!-- End with encouragement about the subtask's importance -->

---

## Example Output

Here's what your generated prompt should look like:

```markdown
# Task 17 - Subtask 3: Parameter Management System - Agent Instructions

## The Problem You're Solving

The Natural Language Planner needs sophisticated two-phase parameter handling that enables both execution paths to converge at a verification point. Parameters must be discovered early in Path B to inform generation, then ALL parameters must be verified for executability at the convergence point where both paths meet.

## Your Mission Within Task 17

Implement the parameter management nodes that create the convergence architecture - where Path A (workflow reuse) and Path B (workflow generation) meet at ParameterMappingNode. This is THE critical verification gate that ensures workflows have all required parameters before execution.

## ⚠️ Critical Context: Task 17's Two-Path Architecture

Before implementing this subtask, you MUST understand the overall architecture:

**Path A (Workflow Reuse)**: Discovery → ParameterMapping → Preparation → Result
**Path B (Workflow Generation)**: Discovery → Browsing → ParamDiscovery → Generation → Validation → Metadata → ParameterMapping → Preparation → Result

**CONVERGENCE**: Both paths meet at ParameterMappingNode - the verification gate.

**This Subtask's Role**: Creates the convergence point and two-phase parameter architecture. ParameterDiscoveryNode runs ONLY in Path B before generation. ParameterMappingNode runs in BOTH paths as the convergence point.

## Dependencies and Prerequisites

### Subtasks That Must Be Complete
- ✅ Subtask 1 (Foundation): Provides directory structure, utilities, and test infrastructure
- ✅ Subtask 2 (Discovery): Provides WorkflowDiscoveryNode that routes to our nodes

### Files/Outputs You'll Use From Previous Subtasks
- `src/pflow/planning/utils/workflow_loader.py` from Subtask 1
- `src/pflow/planning/nodes.py` with WorkflowDiscoveryNode and ComponentBrowsingNode
- Test fixtures from `tests/test_planning/conftest.py`

[... continues with all sections filled ...]

## Shared Store Contract

### Keys This Subtask READS
- `shared["user_input"]` - Natural language input from CLI
- `shared["browsed_components"]` - Selected components from ComponentBrowsingNode (Path B)
- `shared["found_workflow"]` - Existing workflow from discovery (Path A)
- `shared["generated_workflow"]` - Generated workflow from GeneratorNode (Path B)

### Keys This Subtask WRITES
- `shared["discovered_params"]` - Parameters extracted from NL (Path B only)
- `shared["extracted_params"]` - Raw parameters from any source
- `shared["verified_params"]` - Parameters after verification
- `shared["execution_params"]` - Final format for runtime

### Expected Data Formats
```python
shared["discovered_params"] = {
    "state": "closed",
    "limit": "20"
}

shared["verified_params"] = {
    "issue_number": "1234",
    "complete": True  # All required params present
}
```

[... continues with complete implementation ...]
```

> Note: This is an example showing how Task 17 context flows into the subtask prompt. Extract actual content from your knowledge.

## Critical Reminders for the Prompt-Generating Agent

1. **ALL placeholders must be replaced** - No `{{placeholder}}` should remain
2. **Shared progress log is CRITICAL** - It's shared across ALL subtasks at Task 17 level
3. **Two-path architecture must be explained** - Every implementer needs to understand it
4. **Dependencies are crucial** - Subtasks build on each other
5. **Interface contracts must be clear** - How subtasks connect
6. **Include Task 17 documents** - They provide essential context
7. **Maintain template structure** - Keep all sections in order
8. **Success criteria must include integration** - Not just isolated functionality

## What Makes a Good Subtask Implementation Prompt

Your generated prompt should:
- Open with the problem within Task 17's context
- Clearly explain the two-path architecture
- Show dependencies on previous subtasks
- Define interface contracts clearly
- Use the SHARED progress log correctly
- Provide all Task 17 context documents
- Break down work considering integration
- Warn about Task 17-specific pitfalls
- Emphasize continuous progress logging with subtask attribution
- Include specific technical details from Task 17
- Explicitly state what NOT to do
- Set clear integration-focused success criteria
- End with motivation about the subtask's role

## 📁 Output: Where to Save Your Generated Prompt

After thinking extensively and planning the prompt, write it to:

`.taskmaster/tasks/task_17/starting-context/prompts/task-17-subtask-{{subtask_number}}-implementation-prompt.md`

## 🔑 Key Principles to Remember

1. **Task 17 Context is Essential**: The two-path architecture must be understood
2. **Subtasks Are Interdependent**: They build on each other sequentially
3. **Shared Progress Log**: ALL subtasks share ONE log with attribution
4. **Interface Contracts Matter**: How subtasks connect is critical
5. **Subtask Spec is Primary**: The specification file is the source of truth
6. **Include All Context**: The implementing agent has access to all Task 17 documents
7. **Ask When Uncertain**: Better to ask than generate unhelpful prompt

Remember: The implementing agent needs to understand both their specific subtask AND how it fits into Task 17's sophisticated meta-workflow. Make the prompt comprehensive, clear, and properly contextualized within the Natural Language Planner architecture.
