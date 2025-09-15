# Task 52: Improve planner with "plan" and "requirements" steps

## ID
52

## Title
Improve planner with "plan" and "requirements" steps

## Description
Add Requirements Analysis and Planning nodes to the planner pipeline to improve workflow generation success rates. Requirements will extract abstract operations from user input, and Planning will create an execution blueprint before generation. This two-step analysis significantly improves first-attempt success and provides better error messages for impossible requirements.

## Status
in progress

## Dependencies
- Task 17: Implement Natural Language Planner System - The base planner system must exist before we can enhance it with additional planning steps
- Task 33: Extract planner prompts to markdown files - Prompts must be externalized to add new requirements and planning prompts
- Task 35: Migrate Template Syntax from $variable to ${variable} - New nodes need to work with the current template syntax
- Task 36: Update Context Builder for Namespacing Clarity - Requirements and Planning will use the context builder

## Priority
high

## Details
The current planner pipeline sometimes fails on complex workflows because it attempts to generate workflows directly without first understanding requirements or creating a plan. This task adds two new nodes to improve the generation process:

### Requirements Analysis Node
- Extracts abstract operational requirements from templatized user input
- Identifies what needs to be done (WHAT) without implementation details
- Abstracts parameter values while keeping services explicit (e.g., "Fetch issues from GitHub" not "Fetch 20 closed issues")
- Outputs structured requirements list with complexity indicators
- Can fail fast if user input is too vague

### Planning Node
- Creates execution plan (HOW) based on requirements and available components
- Uses natural language reasoning with structured ending for parsing
- Determines feasibility (FEASIBLE/PARTIAL/IMPOSSIBLE)
- Outputs markdown plan with parseable Node Chain
- Only uses components selected by Component Browsing

### Key Design Decisions (MVP Approach)
- **Two separate nodes** rather than combined - maintains single responsibility
- **Requirements before Planning** - natural flow of WHAT before HOW
- **Multi-turn conversation** for Planning→Generator only (not all nodes)
- **Standalone LLM calls** for Requirements/Component selection (not in conversation)
- **Parameter Discovery moved earlier** to provide templatization before Requirements
- **New conversation per workflow** - clean slate each time
- **3 retry limit maintained** - no changes to existing retry logic
- **Path A unchanged** - workflow reuse path skips new nodes entirely

### Technical Implementation
The implementation leverages the `llm` library's Conversation class for automatic context accumulation:
- PlanningNode starts a conversation with requirements/components as context
- WorkflowGeneratorNode continues the conversation to generate workflow
- On retry, conversation continues with validation errors for learning
- Anthropic's context caching provides ~70% cost reduction on retries

### Pipeline Changes
**Current Path B**: Discovery → Component Browsing → Parameter Discovery → Generator → Validation → ...

**New Path B**: Discovery → Parameter Discovery → Requirements Analysis → Component Browsing → Planning → Generator → Validation → ...

### Error Handling
- Too vague input: Requirements returns `is_clear: false` with clarification message
- Impossible requirements: Planning returns `Status: IMPOSSIBLE` with alternatives
- Partial solutions: Planning indicates what can/cannot be done
- All error states route to existing ResultPreparationNode

## Test Strategy
Comprehensive testing ensures the new nodes integrate smoothly and improve generation quality:

### Unit Tests
- RequirementsAnalysisNode: Test extraction with various input complexities
- PlanningNode: Test feasibility assessment and plan generation
- Test vague input detection and error messages
- Test parsing of Planning markdown output

### Integration Tests
- Full pipeline flow with new nodes
- Conversation context preservation across Planning→Generator
- Retry behavior with accumulated context
- Requirements influence on Component Browsing

### LLM Prompt Tests
- Requirements extraction accuracy with templatized input
- Planning reasoning quality with different component sets
- Conversation continuity between Planning and Generator
- Cost tracking to verify context caching benefits

### Key Test Scenarios
- Simple linear workflows (should still work efficiently)
- Complex multi-step workflows (should have higher success rate)
- Impossible requirements (should fail gracefully with explanation)
- Vague input (should request clarification)
- Retry scenarios (should learn from previous attempts)