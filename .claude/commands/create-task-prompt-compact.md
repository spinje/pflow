# Create Task Implementation Prompt - Meta-Prompt for AI Agents

This command instructs an AI agent to generate a comprehensive implementation prompt for another AI agent who will implement a pflow task.

## Inputs

Inputs: $ARGUMENTS

Available inputs:
- `--task_id`: The ID of the task to create an implementation prompt for (required)
- `--read_context`: Whether to read the context files from disk (default: false)

> If you receive only a number (e.g., "21"), assume that is the task_id with read_context=false

## 🚨 CRITICAL: File Reading Rules

**NEVER read files unless `read_context` is explicitly set to true!**
- If `read_context` is false or not specified → DO NOT read any files
- If `read_context` is true → Read the files in `.taskmaster/tasks/<task_id>/starting-context/`
- No exceptions to this rule

## Your Task as the Prompt-Generating Agent

Create a comprehensive implementation prompt for another AI agent who will implement a pflow task. Your primary source of information should be **your existing context window**.

**Your output**: Generate the prompt and save it to `.taskmaster/tasks/task_{{task_id}}/task-{{task_id}}-implementation-prompt.md`

### 🧠 Knowledge Sources

1. **Primary (ALWAYS)**: Your existing context window - task discussions, implementation details, architectural decisions, patterns discovered
2. **Secondary (ONLY if read_context=true)**: Files on disk to supplement and verify your knowledge

### Path 1: DEFAULT Behavior (read_context=false)

1. **Draw from your context window** - What do you already know about Task {{task_id}}?
2. **Use LS tool** to list files in `.taskmaster/tasks/{{task_id}}/starting-context/` (DO NOT read them)
3. **Fill the template** using existing knowledge and file list
4. **Be explicit** about what you know vs what needs verification
5. **Mark unknowns** as `{{placeholder_name - TO BE VERIFIED}}`

### Path 2: Enhanced Mode (read_context=true)

1. **Start with your existing knowledge**
2. **Use LS tool** to list files
3. **Read the files** to verify, correct, and expand understanding
4. **Merge knowledge** and fill template completely

### 🛑 Decision Points: When to STOP and ASK

**Do NOT proceed if:**
1. You have NO knowledge of the task AND read_context=false
2. The task_id doesn't match any discussed task
3. Critical information is missing that can't be marked "TO BE VERIFIED"

**Instead, ask the user:**
- "I don't have sufficient context about Task {{task_id}} in my current conversation. Should I read the context files (--read_context=true) or can you provide more information? Currently these are the ambiguous parts... go on to describe all the things you are not sure about along with a alternative options and recommendations"
- "I'm not certain about [specific aspect]. Could you clarify before I generate the prompt?"
- "Currently I have to make a lot of assumptions about the current state of the codebase. Should I deploy subagents to gather more information about [specific aspect] in the codebase?"

### 📝 Quality Checks Before Output

1. **What do I know from conversation?**
2. **What am I uncertain about?** Mark clearly
3. **Am I making assumptions?** Verify or mark
4. **Is this enough to be useful?** If not, ask

### Example Outputs

**When you KNOW the task well (read_context=false):**
```markdown
# Task 21: Implement Workflow Input Declaration - Agent Instructions

## The Problem You're Solving

Workflows currently cannot declare their expected inputs, making validation impossible and usage unclear. Users get cryptic errors when required parameters are missing. [Based on our discussion about parameter validation issues]

## Your Mission

Implement input declaration for workflows in the IR schema, enabling workflows to specify required and optional parameters with types and defaults. [As we discussed in the context of improving workflow usability]

[... continue with known information, marking uncertain areas ...]
```

**When you have LIMITED knowledge (read_context=false):**
```markdown
# Task 21: Workflow Input Enhancement - Agent Instructions

## The Problem You're Solving

Based on our discussion, this task relates to improving how workflows handle input parameters. You'll need to read the specification for the complete problem statement and requirements.

## Your Mission

Implement improvements to workflow input handling. The exact scope and requirements are detailed in the specification file in your starting-context folder.

[... continue with what you do know from the conversation ...]
```

## Template to Fill

Use this exact structure and replace ALL placeholders:

---

# Task {{task_number}}: {{task_title}} - Agent Instructions

## The Problem You're Solving

{{problem_statement}}
<!-- 2-3 sentences explaining what's broken/missing and why it matters -->

## Your Mission

{{brief_mission_statement}}
<!-- 1-2 sentences explaining the core objective -->

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development - reasoning system role, questioning assumptions, handling ambiguity, earning elegance through robustness.

**Why read first**: This mindset is critical for implementing any task correctly.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_{{task_id}}/task_{{task_id}}.md`

**Purpose**: High-level overview, objectives, and current state.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_{{task_id}}/starting-context/`

**Files to read (in this order):**
{{context_file_list}}
<!-- Use LS tool to list, format as numbered list with purpose -->

**Instructions**: Read EACH file. After each, consider what it tells you, how it relates to others, and what implementation decisions it implies.

**IMPORTANT**: The specification file (`*-spec.md`) is the source of truth for requirements.

## What You're Building

{{detailed_description}}
<!-- Clear explanation with concrete example -->

Example:
```{{language}}
{{usage_example}}
```

## Key Outcomes You Must Achieve

### {{outcome_category_1}}
{{outcome_list_1}}

### {{outcome_category_2}}
{{outcome_list_2}}

## Implementation Strategy

### Phase 1: {{phase1_name}} ({{time_estimate}})
{{phase1_tasks}}

### Phase 2: {{phase2_name}} ({{time_estimate}})
{{phase2_tasks}}

### Phase 3: {{phase3_name}} ({{time_estimate}})
{{phase3_tasks}}

### Use Parallel Execution

Always use subagents to gather information, research, verify assumptions, debug, test, and write tests to maximize efficiency and avoid context window limitations.

## Critical Technical Details

### {{technical_detail_1_title}}
{{technical_detail_1_content}}

### {{technical_detail_2_title}}
{{technical_detail_2_content}}

## Critical Warnings from Experience

### {{warning_1_title}}
{{warning_1_content}}

### {{warning_2_title}}
{{warning_2_content}}

## Key Decisions Already Made

{{decisions_list}}

**📋 Note on Specifications**: If a specification file exists, it is authoritative. Follow it precisely unless you discover a critical issue (document deviation or ask for clarification).

## Success Criteria

Your implementation is complete when:

{{success_criteria_checklist}}
<!-- Always include: ✅ make test passes, ✅ make check passes -->

## Common Pitfalls to Avoid

{{pitfalls_list}}

## 📋 Create Your Implementation Plan FIRST

Before writing code, create a comprehensive implementation plan to prevent duplicate work, identify dependencies, optimize parallelization, and surface unknowns early.

### Step 1: Context Gathering with Parallel Subagents

Deploy parallel subagents for:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Codebase Structure Analysis**
   - Task: "Analyze the structure of src/pflow/nodes/ and identify the pattern for adding new node types"
   - Task: "Find all existing node implementations and extract common patterns"

2. **Integration Points Discovery**
   - Task: "Identify how nodes are registered in the registry system"
   - Task: "Analyze how the compiler handles different node types"

3. **Testing Pattern Analysis**
   - Task: "Examine tests/test_nodes/ structure and testing patterns"
   - Task: "Identify test utilities and fixtures used for node testing"

4. **Documentation Requirements**
   - Task: "Check architecture/reference/node-reference.md structure for adding new nodes"
   - Task: "Find examples of node documentation in the codebase"
```

> Note: Be specific and detailed in subagent prompts, providing exact context and expectations. The above examples is just the descriptions of what to do not the full prompts you should use.

### Step 2: Write Your Implementation Plan

Create at: `.taskmaster/tasks/task_{{task_id}}/implementation/implementation-plan.md`

Include:
1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - Order requirements
3. **Subagent task assignments** - No conflicts, one subagent per file
4. **Risk identification** - Mitigation strategies
5. **Testing strategy** - Verification approach

### Subagent Task Scoping

**✅ GOOD Subagent Tasks:**
```markdown
- "Write a new test case for foo.py that covers the logged‑out user edge case; avoid mocks."
- "Follow the pattern in HotDogWidget.php to implement a new CalendarWidget that lets users paginate months & years (no extra libraries)."
- "Write unit tests for parameter validation in test_workflow_node_params.py. Include these test cases... [list of test cases]"
```

**❌ BAD Subagent Tasks:**
```markdown
- "Implement the entire WorkflowNode feature" (too broad)
- "Update all files related to nodes" (multiple agents will conflict)
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
# Task {{task_id}} Implementation Plan

## Context Gathered
### Codebase Patterns
[Key patterns discovered]

### Integration Points
[How feature connects to existing code]

### Dependencies
[What implementation depends on]

## Implementation Steps

### Phase 1: Core Infrastructure (Parallel Possible)
1. **Task Name** (Subagent X)
   - Files: [specific files]
   - Context: [what subagent needs]

[Continue phases with clear dependencies]

## Risk Mitigation
| Risk | Mitigation Strategy |
|------|-------------------|

## Validation Strategy
[How to verify each component]
```

### When to Revise Your Plan

Update when: context reveals new requirements, obstacles appear, dependencies change, better approaches emerge. Document changes with rationale.

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_{{task_id}}/implementation/progress-log.md`

```markdown
# Task {{task_id}} Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update AS YOU WORK** - every discovery, bug, insight!

### Implementation Steps

{{ordered_implementation_steps}}

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
```{{language}}
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
While testing extract_metadata(), discovered that nodes with
circular imports crash the scanner. Added import guard pattern.
This affects how we handle all dynamic imports.
```

## What NOT to Do

{{what_not_to_do_list}}

## Getting Started

{{getting_started_steps}}

## Final Notes

{{final_notes}}

## Remember

{{remember_section}}

{{motivational_ending}}

---

## How to Extract Information and Fill the Template

### From Context Window:
Reflect on: problem descriptions, task objectives, technical decisions, implementation strategies, warnings identified, patterns discovered

### From Context Files (if read_context=true):

1. **Problem Statement**: Look for sections explaining what's broken, missing, or needs improvement
2. **Task Number and Title**: Usually in the filename or document header
3. **Mission Statement**: First paragraph of spec or "Objective" section
4. **Primary Context File**: Look for comprehensive context documents or main spec files
5. **Key Outcomes**: Look for deliverables, components to build, or specific changes needed
6. **Detailed Description**: "What You're Building" or "Overview" sections
7. **Implementation Phases**: Break down from implementation plans or create logical phases
8. **Technical Details**: Requirements, constraints, or technical considerations sections
9. **Warnings**: Look for "gotchas", "pitfalls", or "lessons learned" sections
10. **Key Decisions**: "Decisions Made" sections or handover documents
11. **What NOT to Do**: Anti-patterns, things to avoid, or explicit "don't" statements
12. **Success Criteria**: "Success Criteria", "Test Requirements", or "Acceptance Criteria" sections
13. **Getting Started Steps**: First concrete actions from implementation plans

## Critical Reminders

1. **Replace ALL placeholders** - No `{{placeholder}}` remains
2. **Preserve progress log sections exactly**
3. **Read ALL context files when enabled**
4. **Maintain template structure**
5. **Include concrete examples**
6. **Always add make test/check to success criteria**
7. **Epistemic manifesto is always first**
8. **Extract, don't invent**

## What Makes a Good Implementation Prompt

- Opens with problem for urgency
- Clear mission statement
- Necessary context through reading list
- Manageable phases with time estimates
- Specific pitfall warnings
- Continuous progress logging emphasis
- Concrete technical details
- Explicit NOT to do list
- Measurable success criteria
- Motivational ending

## 📁 Output Location

Save to: `.taskmaster/tasks/task_{{task_id}}/task-{{task_id}}-implementation-prompt.md`

## 🔑 Key Principles

1. **Context Window First**: Your conversation knowledge is PRIMARY
2. **Never Read Without Permission**: Only if --read_context=true
3. **Never Invent**: Mark unknowns as "TO BE VERIFIED"
4. **Ask When Uncertain**: Better to clarify than generate unhelpful prompt
5. **Be Explicit**: Distinguish KNOWN vs needs verification

Remember: The implementing agent will rely entirely on your generated prompt to complete the task successfully. Make it comprehensive, clear, and actionable - using the knowledge you already have.
