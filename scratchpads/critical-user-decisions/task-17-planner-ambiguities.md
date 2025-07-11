# Task 17: Natural Language Planner System - Critical Decisions & Ambiguities

## Executive Summary

Task 17 is the core feature that makes pflow unique - the Natural Language Planner that enables "Plan Once, Run Forever". After extensive research, I've identified several critical ambiguities and decisions that need to be made before implementation can begin.

### Key Breakthrough Insights:
1. The workflow discovery mechanism can reuse the exact same pattern as node discovery - the context builder already provides the perfect format.
2. Workflows are reusable building blocks that can be composed into other workflows, not just standalone executions.
3. Two-phase approach separates discovery (what to use) from planning (how to connect), preventing information overload.

## 1. Template Variable Resolution Mechanism - Decision importance (5)

There's a fundamental ambiguity about how template variables (`$variable`) work throughout the system.

### Context:
Template variables are the KEY to pflow's "Plan Once, Run Forever" value proposition. They enable workflow reusability by allowing parameters to change between executions while keeping the workflow structure constant.

**Workflow Lifecycle Example:**
```bash
# 1. PLANNING TIME: User provides natural language with specific value
pflow "fix github issue 1234"

# 2. PLANNER GENERATES: IR with template variables (NOT hardcoded values)
{
  "nodes": [{
    "type": "github-get-issue",
    "params": {"issue_number": "$issue"}  # Template variable preserved
  }]
}

# 3. WORKFLOW SAVED: Template variables remain in saved workflow
~/.pflow/workflows/fix-issue.json  # Contains $issue variable

# 4. RUNTIME: Different values substituted each execution
pflow fix-issue --issue=1234  # $issue → "1234"
pflow fix-issue --issue=5678  # $issue → "5678"
```

**Critical Distinction:**
- **Planning Time**: Extract parameters from natural language and create template variables
- **Runtime**: Substitute actual values into template variables from CLI flags

Without runtime resolution (Option B), each workflow would be single-use, defeating the entire purpose of workflow compilation.

### The Ambiguity:
- Documentation says template resolution is "planner-internal only"
- But examples show `$variables` in the JSON IR that gets saved and executed
- The planner.md states variables are resolved "during planning" but also mentions "runtime substitution"

### Options:

- [ ] **Option A: Planner resolves all templates during generation**
  - Planner replaces `$issue` with actual shared store references in the IR
  - JSON IR contains no `$variables`, only concrete references
  - Simpler implementation, clearer execution model
  - **Problem**: How do saved workflows handle different parameters?

- [x] **Option B: Runtime resolves template variables**
  - JSON IR contains `$variables` that get resolved during execution
  - Enables parameterized workflows (the core value prop!)
  - More complex but enables `pflow fix-issue --issue=1234` pattern
  - **Problem**: Contradicts documentation saying it's planner-only

- [ ] **Option C: Hybrid approach**
  - Some variables resolved by planner (like prompt templates)
  - Others remain as parameters for runtime (like `$issue_number`)
  - Most flexible but most complex

**Recommendation**: Option B - Runtime resolution is ESSENTIAL. Without it, pflow would just be a one-time script generator. The ability to run `pflow fix-issue --issue=ANY_NUMBER` is the entire point of workflow compilation.

**Implementation Note for Planner**: When the user says "fix github issue 1234", the planner must:
1. Recognize "1234" as a parameter value (not part of the intent)
2. Generate IR with `"issue_number": "$issue"` (NOT `"issue_number": "1234"`)
3. Store the workflow with template variables intact
4. The value "1234" is only used during the first execution, not baked into the workflow

## 2. Workflow Storage and Discovery Implementation - Decision importance (4)

The "find or build" pattern is core to pflow but implementation details are now clearer.

### Updated Understanding:
- Discovery can work exactly like node discovery - using descriptions
- The context builder already provides the pattern we need
- Workflows just need a good description field for LLM matching

### The Simplified Approach:

- [x] **Use Context Builder Pattern for Everything**
  - For nodes: Context builder generates markdown with descriptions
  - For workflows: Store with description field in same format
  - LLM sees both nodes and workflows in unified format
  - Example workflow entry:
    ```markdown
    ### fix-github-issue
    Fetches a GitHub issue, analyzes it with AI, generates a fix, and creates a PR
    ```
  - Reuses existing infrastructure perfectly

### Implementation:
1. **Node Discovery**: Already works via context builder markdown
2. **Workflow Discovery**:
   - Load saved workflows from `~/.pflow/workflows/`
   - Format them like nodes: name + description
   - Append to context builder output
   - LLM selects from both nodes and existing workflows

**Key Insight**: The description field is all we need for semantic matching. The LLM can understand "fix github issue 1234" matches a workflow described as "Fetches a GitHub issue, analyzes it with AI, generates a fix".

## 3. LLM Model Selection and Configuration - Decision importance (3)

Which LLM should the planner use and how should it be configured?

### The Ambiguity:
- Documentation mentions "thinking models" like o1-preview
- But also references Claude and GPT-4
- No clear guidance on which to use when

### Options:

- [ ] **Option A: Use o1-preview for all planning**
  - Best reasoning capability
  - Higher cost and latency
  - May be overkill for simple workflows

- [x] **Option B: Use GPT-4/Claude-3.5 for planning**
  - Good balance of capability and speed
  - Lower cost than o1
  - Sufficient for workflow generation

- [ ] **Option C: Tiered approach**
  - Simple requests → GPT-3.5
  - Complex requests → GPT-4
  - Ambiguous requests → o1-preview
  - Most complex to implement

**Recommendation**: Option B - GPT-4 or Claude-3.5 Sonnet provides the right balance for MVP.

## 4. Input Parameter Handling in Natural Language - Decision importance (5)

How does the planner extract and handle parameters from natural language?

### The Ambiguity:
- User says "fix github issue 1234" - how does planner know 1234 is the issue parameter?
- How are template variables created from natural language?
- What happens when parameters are missing?

### Options:

- [ ] **Option A: Strict parameter extraction**
  - LLM must identify all parameters in the input
  - Fail if any required parameters missing
  - More predictable but less flexible

- [x] **Option B: Smart parameter inference with prompting**
  - LLM infers parameters from context
  - Creates template variables for dynamic content
  - Prompts user for missing required inputs
  - More user-friendly

- [ ] **Option C: Two-phase approach**
  - First extract intent and parameters
  - Then generate workflow with templates
  - More structured but slower

**Recommendation**: Option B - Smart inference makes the natural language interface more intuitive.

## 5. Prompt Template Design and Management - Decision importance (4)

How should prompt templates be structured and managed?

### The Ambiguity:
- Task mentions both inline prompts and template files
- How complex should prompts be?
- How to ensure prompts generate valid JSON IR?

### Options:

- [x] **Option A: Simple Python f-strings in code**
  - Define prompts as constants in prompts.py
  - Use f-strings for variable substitution
  - Easy to implement and modify
  - Example: `WORKFLOW_PROMPT = f"Given nodes: {nodes}\nGenerate workflow for: {request}"`

- [ ] **Option B: External template files**
  - Store prompts in separate files
  - Use Jinja2 for complex templating
  - Better separation but more complex

- [ ] **Option C: Prompt chaining system**
  - Multiple specialized prompts
  - Chain them based on complexity
  - Most flexible but overengineered for MVP

**Recommendation**: Option A - Simple f-strings are sufficient for MVP prompts.

## 6. JSON IR Generation Validation - Decision importance (4)

How to ensure LLM generates valid JSON IR every time?

### The Ambiguity:
- LLMs can generate malformed JSON
- How to handle validation failures?
- How many retries are acceptable?

### Options:

- [ ] **Option A: Strict JSON schema enforcement**
  - Validate against full schema
  - Reject any deviation
  - Most reliable but may reject valid variations

- [x] **Option B: Liberal parsing with correction**
  - Try to parse and fix common issues
  - Validate essential fields only
  - Retry with error feedback to LLM
  - More forgiving and user-friendly

- [ ] **Option C: Structured output formats**
  - Use function calling or structured outputs
  - Depends on specific LLM capabilities
  - Most reliable but limits LLM choice

**Recommendation**: Option B - Liberal parsing with retry gives best user experience.

## 7. User Approval Flow Implementation - Decision importance (3)

How should the approval process work in practice?

### The Ambiguity:
- Show JSON? CLI syntax? Both?
- How to handle modifications?
- What about headless/CI environments?

### Options:

- [x] **Option A: Show CLI syntax only**
  - Display generated CLI pipe syntax
  - Simple Y/n prompt for approval
  - Save on approval, execute after
  - Clearest for users

- [ ] **Option B: Interactive modification**
  - Show CLI syntax
  - Allow inline editing
  - More powerful but complex UI

- [ ] **Option C: Multi-format display**
  - Show both CLI and visual representation
  - Toggle between views
  - Too complex for CLI interface

**Recommendation**: Option A - Simple CLI display with Y/n approval is clearest.

## 8. Error Recovery Strategy - Decision importance (4)

How should the planner handle and recover from errors?

### The Ambiguity:
- What errors are recoverable vs fatal?
- How many retries for each error type?
- How to provide useful feedback?

### Options:

- [ ] **Option A: Simple retry with backoff**
  - Retry all errors up to 3 times
  - Exponential backoff
  - Simple but may waste time on unrecoverable errors

- [x] **Option B: Error-specific recovery**
  - Different strategies for different errors
  - - Malformed JSON: retry with format hint
  - - Invalid nodes: suggest alternatives
  - - Missing params: prompt for input
  - More sophisticated and user-friendly

- [ ] **Option C: Fail fast with clear errors**
  - No retries, just clear error messages
  - Fastest but least helpful

**Recommendation**: Option B - Smart error recovery improves user experience significantly.

## 9. Integration with Existing Context Builder - Decision importance (2)

How should the planner use the context builder from Task 16?

### The Ambiguity:
- Context builder outputs markdown - is this the right format?
- Should we modify the context builder output?
- How much context is too much?

### Options:

- [x] **Option A: Use context builder as-is**
  - Take markdown output directly
  - Include in LLM prompt unchanged
  - Simplest integration

- [ ] **Option B: Post-process context**
  - Convert markdown to structured format
  - Filter based on user intent
  - More optimal but more complex

- [ ] **Option C: Replace context builder**
  - Build context inline in planner
  - More control but duplicates code

**Recommendation**: Option A - Use existing context builder to avoid duplication.

## 10. MVP Feature Boundaries - Decision importance (5)

What exactly is in scope for the MVP planner?

### Critical Clarifications Needed:
1. **Action-based transitions**: Examples show them, but they're marked as v2.0
2. **Complex workflows**: How complex can MVP workflows be?
3. **Parameter types**: Just strings or full type support?
4. **Workflow modification**: Can users edit before saving?

### Options:

- [x] **Option A: Strict MVP scope**
  - Sequential workflows only (no branching)
  - String parameters only
  - No action-based transitions
  - Basic approval only (no editing)
  - Most realistic for MVP timeline

- [ ] **Option B: Include some v2.0 features**
  - Add simple branching
  - Support basic types
  - More useful but scope creep risk

**Recommendation**: Option A - Stick to strict MVP scope to ensure delivery.

## 11. Unified Discovery Pattern - Decision importance (5)

How should the planner discover both nodes and existing workflows?

### The Key Insight:
The context builder already solved this problem! We can use the same pattern for everything.

### Critical Refinements:
1. **Workflows ARE building blocks** - Other workflows can be used inside new workflows
2. **Two different contexts needed**:
   - **Discovery context**: Just names and descriptions (for finding what to use)
   - **Planning context**: Full interface details (only for selected nodes/workflows)
3. **Separation of concerns**: Discovery vs. implementation planning

### The Two-Phase Approach:

**Phase 1: Discovery Context (for finding nodes/workflows)**
```markdown
## Available Nodes

### github-get-issue
Fetches issue details from GitHub

### llm
General-purpose language model for text processing

### read-file
Reads content from a file

## Available Workflows (can be used as building blocks)

### fix-github-issue
Analyzes a GitHub issue and creates a PR with the fix

### analyze-error-logs
Reads log files and summarizes errors with recommendations
```

**Phase 2: Planning Context (only selected nodes/workflows)**
```markdown
## Selected Components

### github-get-issue
Fetches issue details from GitHub
**Inputs**: `issue_number`, `repo`
**Outputs**: `issue_data`, `issue_title`

### llm
General-purpose language model for text processing
**Inputs**: `prompt`
**Outputs**: `response`
**Parameters**: `model`, `temperature`
```

### Benefits:
1. **Workflows as first-class citizens** - Can compose workflows from other workflows
2. **Focused contexts** - Discovery gets minimal info, planning gets full details
3. **Performance** - Don't load full interface details for 100+ nodes during discovery
4. **Clarity** - LLM isn't overwhelmed with irrelevant interface details

### Implementation:
1. **Discovery phase**:
   - Load all nodes (names + descriptions only)
   - Load all workflows (names + descriptions only)
   - LLM selects which to use
2. **Planning phase**:
   - Load full details ONLY for selected nodes/workflows
   - LLM plans the shared store layout and connections
   - Generate IR with proper mappings

### Workflow Storage Format:
```json
{
  "name": "fix-github-issue",
  "description": "Analyzes a GitHub issue and creates a PR with the fix",
  "inputs": ["issue_number"],
  "outputs": ["pr_number"],
  "ir": { ... }  // The actual workflow IR
}
```

**Key Insight**: Workflows are just reusable node compositions - they should appear alongside nodes as building blocks!

## 12. JSON IR to CLI Syntax Relationship - Decision importance (4)

There's an implicit assumption that JSON IR can be "compiled" back to CLI syntax for user display, but this isn't straightforward.

### The Ambiguity:
- The planner generates JSON IR, but users need to see CLI syntax
- How do we convert complex JSON structures back to readable CLI commands?
- What about template variables in the display?

### Options:

- [ ] **Option A: Generate both JSON IR and CLI syntax**
  - Planner creates both formats
  - Ensures consistency
  - More complex prompting

- [x] **Option B: Compile JSON IR to CLI syntax**
  - Separate compiler step converts IR to CLI
  - Single source of truth (JSON IR)
  - Need to handle all IR features in CLI syntax

- [ ] **Option C: Show simplified CLI syntax**
  - Display only basic node chain
  - Hide complex details
  - Less informative for users

**Recommendation**: Option B - A separate IR-to-CLI compiler maintains separation of concerns and single source of truth.

## Critical Next Steps

1. **Clarify template variable resolution** - This is the most critical ambiguity
2. ~~**Decide on workflow storage format**~~ - ✅ RESOLVED: Use simple JSON with name, description, inputs, outputs, and IR
3. ~~**Design discovery mechanism**~~ - ✅ RESOLVED: Two-phase approach with context builder
4. **Confirm MVP boundaries** - Especially regarding action-based transitions
5. **Design concrete prompt templates** - With examples of expected outputs
6. **Create test scenarios** - Cover all edge cases identified above
7. **Implement two context builder functions**:
   - `build_discovery_context()` - Lightweight descriptions only
   - `build_planning_context(selected)` - Full details for selected components

## Implementation Recommendations

Based on this analysis, here's the recommended approach:

1. **Use Option B for template variables** - Runtime resolution is essential for workflow reusability
2. **Use unified discovery pattern** - Context builder lists both nodes and workflows
3. **Store workflows with descriptions** - Simple JSON with name, description, and IR
4. **Use GPT-4** for planning with structured prompts
5. **Show CLI syntax only** for approval
6. **Implement smart error recovery** with specific strategies
7. **Strictly limit to sequential workflows** for MVP

**Critical Implementation Detail**: The planner must be explicitly instructed to generate template variables (`$issue`, `$file_path`, etc.) rather than hardcoding values extracted from natural language input.

### Key Implementation Simplifications:
- No separate discovery system needed - reuse context builder pattern
- Workflows are reusable building blocks alongside nodes
- Two-phase approach: discovery (descriptions only) → planning (full details)
- The LLM prompt structure:
  - Discovery: "Here are available nodes and workflows. Which should we use?"
  - Planning: "Here are the selected components' interfaces. Plan the connections."

### Context Builder Evolution:
1. **build_discovery_context()** - Names and descriptions only
2. **build_planning_context(selected_components)** - Full interface details for selected items only

This separation prevents information overload and improves LLM performance.

## Risks and Mitigations

1. **Risk**: Template variable complexity
   - **Mitigation**: Start with simple $variable substitution, enhance later

2. **Risk**: LLM generates invalid workflows
   - **Mitigation**: Strong validation with retry loop and error feedback

3. **Risk**: Discovery doesn't find relevant workflows
   - **Mitigation**: Good workflow naming and description conventions

4. **Risk**: Scope creep with "just one more feature"
   - **Mitigation**: Strict MVP checklist, defer everything else

This analysis should provide the clarity needed to begin implementation of Task 17.
