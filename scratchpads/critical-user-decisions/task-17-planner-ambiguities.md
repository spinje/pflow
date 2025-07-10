# Task 17: Natural Language Planner System - Critical Decisions & Ambiguities

## Executive Summary

Task 17 is the core feature that makes pflow unique - the Natural Language Planner that enables "Plan Once, Run Forever". After extensive research, I've identified several critical ambiguities and decisions that need to be made before implementation can begin.

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

## 2. Workflow Storage and Discovery Implementation - Decision importance (4)

The "find or build" pattern is core to pflow but implementation details are vague.

### The Ambiguity:
- How exactly are workflows stored and indexed for semantic search?
- What metadata is saved with workflows to enable discovery?
- How does similarity matching work in practice?

### Options:

- [x] **Option A: Simple JSON files with metadata**
  - Store in `~/.pflow/workflows/<name>.json`
  - Include description field for basic text search
  - Use LLM for similarity matching on descriptions
  - Simple to implement, good enough for MVP

- [ ] **Option B: Embeddings-based similarity**
  - Generate embeddings for workflow descriptions
  - Store in vector database for semantic search
  - More accurate discovery but complex for MVP
  - Requires additional dependencies

- [ ] **Option C: Structured metadata with tags**
  - Workflows tagged with categories, inputs, outputs
  - Structured search plus LLM fallback
  - Middle ground complexity

**Recommendation**: Option A - Start simple with JSON files and LLM-based matching. Can upgrade to embeddings later.

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

## 11. JSON IR to CLI Syntax Relationship - Decision importance (4)

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
2. **Decide on workflow storage format** - Needed for discovery implementation
3. **Confirm MVP boundaries** - Especially regarding action-based transitions
4. **Design concrete prompt templates** - With examples of expected outputs
5. **Create test scenarios** - Cover all edge cases identified above

## Implementation Recommendations

Based on this analysis, here's the recommended approach:

1. **Start with Option B for template variables** - Runtime resolution is essential
2. **Use simple JSON storage** with LLM-based discovery
3. **Use GPT-4** for planning with structured prompts
4. **Show CLI syntax only** for approval
5. **Implement smart error recovery** with specific strategies
6. **Strictly limit to sequential workflows** for MVP

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
