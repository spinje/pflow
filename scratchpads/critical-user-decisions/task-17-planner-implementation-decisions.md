# Critical User Decisions for Task 17: Natural Language Planner Implementation

## Overview

Several critical decisions need to be made before implementation can begin. These decisions will significantly impact the architecture and user experience of pflow.

---

## 1. LLM Selection and Integration - Importance: 5

The planner requires an LLM for natural language understanding and workflow generation. The choice of LLM and integration method is critical.

### Context:
- The planner needs to interpret natural language and generate structured JSON IR
- Must support template variable generation and parameter extraction
- Needs to handle both natural language and CLI-like syntax
- Target ≥95% success rate for workflow generation

### Options:

- [ ] **Option A: Use the general LLM node from Task 12**
  - Reasoning: Dogfooding - use pflow's own LLM node for planning
  - Pros: Consistent with architecture, already implemented
  - Cons: Circular dependency if LLM node not yet implemented
  - Implementation: Create planning flow using LLM node

- [ ] **Option B: Direct API integration (Claude/OpenAI)**
  - Reasoning: Simpler for MVP, no circular dependencies
  - Pros: Direct control, easier to implement initially
  - Cons: Duplicates LLM logic, harder to maintain
  - Implementation: Use requests or SDK directly

- [x] **Option C: Create an internal LLM node that uses Simon Willison's llm CLI (just like the LLM node in Task 12)**
  - Reasoning: Leverage existing tool with model management while utilizing pocketflow for internal use. Clear separation of concerns by not using "external" nodes. This node can be much simpler than the LLM node in Task 12 and be tailored to the needs of the planner.
  - Pros: Model flexibility, proven tool, simplicity, still dogfooding (but pocketflow instead of pflow directly)
  - Cons: External dependency, subprocess overhead
  - Implementation: Shell out to `llm` command

**Recommendation**: Option C - Create an internal simple LLM node for planner that uses Simon Willison's llm CLI (just like the LLM node in Task 12)

---

## 2. Template Variable Resolution Timing - Importance: 4

Template variables ($variable syntax) need to be resolved to actual shared store values. The timing and location of this resolution is ambiguous in the documentation.

### Context:
- Planner generates template strings like "Analyze issue: $issue_data"
- Variables must map to shared store values at execution time
- Documentation mentions both "planner-internal" resolution and runtime resolution

### Options:

- [ ] **Option A: Planner resolves all variables during generation**
  - Reasoning: Complete resolution before execution
  - Pros: Simpler runtime, all validation upfront
  - Cons: Less flexible, can't handle dynamic values
  - Implementation: Planner replaces $vars with shared["key"] references

- [ ] **Option B: Planner validates, Runtime resolves**
  - Reasoning: Separation of concerns, more flexible
  - Pros: Dynamic values supported, cleaner separation
  - Cons: More complex runtime, distributed validation
  - Implementation: Planner ensures variables exist, runtime substitutes values

- [ ] **Option C: Two-phase resolution**
  - Reasoning: Some variables resolved by planner, others at runtime
  - Pros: Maximum flexibility
  - Cons: Complex to understand and implement
  - Implementation: Mark variables as static vs dynamic

**Recommendation**: ???

---

## 3. Workflow Discovery Implementation - Importance: 3

The "find or build" pattern requires semantic matching of user input to existing workflows. The implementation approach needs clarification.

### Context:
- Users type variations: "analyze costs", "cost analysis", "AWS spend review"
- All should potentially match existing "aws-cost-analyzer" workflow
- Need to balance accuracy with implementation complexity

### Options:

- [ ] **Option A: LLM-based similarity matching**
  - Reasoning: Use LLM to compare descriptions
  - Pros: Highly accurate semantic matching
  - Cons: Slow, expensive for large workflow libraries
  - Implementation: Pass all workflow descriptions to LLM for ranking

- [ ] **Option B: Simple keyword/pattern matching for MVP**
  - Reasoning: Good enough for MVP, fast
  - Pros: Fast, predictable, no external dependencies
  - Cons: Less accurate, might miss semantic similarities
  - Implementation: Extract keywords, use similarity scoring

- [ ] **Option C: Embeddings-based search**
  - Reasoning: Industry standard for semantic search
  - Pros: Fast and accurate once indexed
  - Cons: Requires embedding model, vector storage
  - Implementation: Generate embeddings, use cosine similarity

**Recommendation**: ???

---

## 4. CLI Input Format and Routing - Importance: 5

How the planner receives input from the CLI needs clarification, especially given the MVP's "everything is natural language" approach.

### Context:
- MVP routes all input through natural language planner
- CLI collects raw string after 'pflow' command
- Planner must handle both quoted and unquoted input

### Options:

- [x] **Option A: CLI passes raw string directly to planner**
  - Reasoning: Simplest approach, aligns with MVP philosophy
  - Pros: No parsing needed in CLI, maximum flexibility
  - Cons: Planner must handle all syntax variations
  - Implementation: `main.py` passes entire input string to planner

- [ ] **Option B: CLI does minimal pre-processing**
  - Reasoning: Help planner by detecting obvious patterns
  - Pros: Cleaner separation, easier planner logic
  - Cons: Duplicates parsing logic, against MVP principle
  - Implementation: CLI detects quotes, operators, then passes structured data

- [ ] **Option C: CLI provides hints but passes raw string**
  - Reasoning: Best of both worlds
  - Pros: Planner gets hints but retains flexibility
  - Cons: More complex CLI logic
  - Implementation: Pass both raw string and metadata

**Recommendation**: Option A - Keep CLI simple, pass raw string. This aligns with documentation and MVP principles and will be extended in 2.0+.

---

## 5. Workflow Storage Structure - Importance: 3

The exact JSON structure for saved workflows needs to be defined, particularly how template variables and parameters are stored.

### Context:
- Workflows saved to ~/.pflow/workflows/<name>.json
- Must support parameter extraction and template variables
- Need to enable "Plan Once, Run Forever" with different parameters

### Options:

- [x] **Option A: Store complete IR with parameter placeholders**
  - Reasoning: Complete workflow definition in one place
  - Pros: Self-contained, matches IR schema
  - Cons: Larger files, some duplication
  - Example Structure:
    ```json
    {
      "name": "fix-issue",
      "description": "Fix GitHub issue",
      "parameters": ["issue_number"],
      "ir": { /* complete IR with $variables */ },
      "created": "2025-01-01T00:00:00Z"
    }
    ```

- [ ] **Option B: Store workflow metadata separately from IR**
  - Reasoning: Cleaner separation of concerns
  - Pros: Easier to query metadata, smaller files
  - Cons: Multiple files to manage
  - Structure: Metadata in JSON, IR in separate file

- [ ] **Option C: Store as executable Python code**
  - Reasoning: Direct execution without compilation
  - Pros: Fast execution, readable
  - Cons: Security concerns, harder to analyze
  - Structure: Python file with workflow definition

**Recommendation**: Option A - Self-contained JSON with complete workflow definition. Simpler to implement and manage.

---

## 6. Error Handling and Retry Strategy - Importance: 4

How the planner handles failures and retries needs clear definition.

### Context:
- Target ≥95% success rate
- LLM can fail or generate invalid workflows
- Need to balance retry attempts with user experience

### Options:

- [ ] **Option A: Fixed retry count with exponential backoff**
  - Reasoning: Standard pattern for API failures
  - Pros: Simple, predictable
  - Cons: May not adapt to different failure types
  - Implementation: 3 retries with 1s, 2s, 4s delays

- [ ] **Option B: Intelligent retry with error analysis**
  - Reasoning: Different strategies for different failures
  - Pros: Better success rate, learns from failures
  - Cons: More complex logic
  - Implementation: Analyze error, adjust prompt, retry with context

- [ ] **Option C: No automatic retry, always ask user**
  - Reasoning: User control over retries
  - Pros: No wasted API calls
  - Cons: Poor user experience for transient failures
  - Implementation: Show error, prompt for retry

**Recommendation**: ???

---

## 7. Parameter vs Static Value Detection - Importance: 5

The planner must decide which values in a workflow should become parameters (variable) vs static values (fixed).

### Context:
- Example: Should "1234" in "fix issue 1234" be parameterized?
- Affects reusability of saved workflows
- Critical for "Plan Once, Run Forever" philosophy

### Options:

- [ ] **Option A: Explicit user annotation**
  - Reasoning: User knows what should be variable
  - Pros: Most accurate
  - Cons: Poor UX, requires user understanding
  - Implementation: Ask user to mark parameters

- [x] **Option B: Heuristic-based detection**
  - Reasoning: Smart defaults based on patterns, llm decides based on what it thinks is best based on good prompt engineering
  - Pros: Good UX, usually correct
  - Cons: May guess wrong sometimes
  - Implementation: Numbers, IDs, URLs become parameters
  - Future improvements to consider: The two-phase approach can be extended to use more "phases" if the llm struggles with accuracy. For version 2.0+ (NOT MVP)the user can prompt the planner to change the parameters if not correct or to the user's preference.

- [ ] **Option C: Make everything parameters**
  - Reasoning: Maximum flexibility
  - Pros: Always reusable
  - Cons: Overwhelming, complex workflows
  - Implementation: Every string/number becomes parameter

**Recommendation**: Option B is the best option and utilizes LLM powerful capabilities for decision making and follows the planners philosophy as an LLM-powered pocketflow workflow.

---

## 8. Integration with Context Builder (Task 16) - Importance: 4

How the planner uses the context builder's output needs clarification.

### Context:
- Task 16 provides formatted node information
- Planner needs this context for LLM selection
- Format and usage pattern unclear

### Options:

- [ ] **Option A: ???**




---

## 9. User Approval Interface - Importance: 2

The approval flow for generated workflows needs specific behavior definition.

### Context:
- Users must approve generated workflows before execution
- Need to support both interactive and batch modes?? What does this mean?
- Target ≥90% approval rate

### Options:

- [ ] **Option A: CLI prompts with inline editing**
  - Reasoning: Rich interaction in terminal
  - Pros: Powerful, immediate feedback
  - Cons: Complex to implement well
  - Implementation: Show workflow, allow parameter edits, confirm

- [x] **Option B: Simple Y/N confirmation**
  - Reasoning: Minimal implementation
  - Pros: Very simple
  - Cons: No modification capability
  - Implementation: Display and confirm only
  - UX: the user can rerun the planner with clarifications and instructions of what NOT to do.

- [ ] **Option C: Save to file for external editing**
  - Reasoning: Use user's preferred editor
  - Pros: Familiar editing experience
  - Cons: Breaks flow, multiple steps
  - Implementation: Save draft, open editor, reload

**Recommendation**: Option B is the simplest to implement and fits the MVP philosophy of "everything is natural language". This can be extended in 2.0+ to support more complex user interactions.

---

## 10. Testing Strategy for LLM Components - Importance: 3

Testing LLM-based components requires special consideration.

### Context:
- LLM outputs are non-deterministic
- Need to test success rate metrics
- API calls expensive during testing

### Options:

- [ ] **Option A: Mock all LLM calls**
  - Reasoning: Fast, deterministic tests
  - Pros: Reliable, free
  - Cons: Doesn't test actual LLM behavior
  - Implementation: Fixtures with pre-recorded responses

- [ ] **Option B: Real LLM calls with test budget**
  - Reasoning: Test actual behavior
  - Pros: Real validation
  - Cons: Expensive, slow, flaky
  - Implementation: Separate test API keys with limits

- [x] **Option C: Hybrid approach**
  - Reasoning: Balance coverage and cost
  - Pros: Good coverage, manageable cost
  - Cons: More complex test setup
  - Implementation: Mock for unit tests, real for integration tests

**Recommendation**: Option C - Mock for fast feedback, real LLM for critical paths.

**Out of scope**: We will make extensive LLM evaluations for every planner LLM node in 2.0+ to ensure the planner is working as expected for a multitude of use cases.

---
