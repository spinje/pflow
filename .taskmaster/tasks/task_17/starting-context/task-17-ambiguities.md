# Task 17: Natural Language Planner System - Critical Decisions & Ambiguities

## Executive Summary

Task 17 implements the Natural Language Planner - a meta-workflow that orchestrates the entire lifecycle of finding or creating workflows based on user intent. While the high-level architecture is well-defined (two paths that converge at parameter verification), several implementation details require decisions that will significantly impact the planner's effectiveness, maintainability, and user experience.

**Key Ambiguities Identified**:
1. LLM Model Selection and Configuration - ✅ Resolved through investigation
2. Retry Strategy for Validation Failures - ✅ Resolved with structured approach
3. Workflow Discovery Matching Threshold - ✅ Resolved with clear criteria
4. Parameter Discovery Architecture - ✅ Resolved with two-phase approach
5. Prep Method Return Pattern for exec_fallback - ✅ Resolved with best practices
6. Testing Strategy for Meta-Workflow - ✅ Resolved with hybrid approach
7. Error Feedback Granularity - ⚠️ Needs user input on verbosity
8. Workflow Storage Integration - ✅ Resolved with clear separation

**Information Sources Used**:
- Context window: Detailed task documentation (architecture, implementation guide, core concepts)
- 5 parallel subagents: Investigated LLM patterns, validation, PocketFlow usage, context builder, WorkflowManager, testing
- Remaining unknowns: Optimal error message verbosity for LLM consumption

## Background Context

The Natural Language Planner is the core innovation that enables pflow's "Plan Once, Run Forever" philosophy. It's a sophisticated orchestration system implemented as a PocketFlow meta-workflow that:
- Takes natural language input from users
- Either discovers existing workflows (Path A) or generates new ones (Path B)
- Extracts and maps parameters intelligently
- Validates workflow structure and template variables
- Returns workflow IR + execution parameters to the CLI for execution

The planner is unique in the pflow architecture as it's the ONLY component that uses PocketFlow for internal orchestration, justified by its complex branching logic, retry strategies, and state accumulation needs.

## Current Implementation Status

Based on subagent investigations:
- **LLM Node**: Fully implemented with Simon Willison's `llm` library, uses `gpt-4o-mini` by default
- **Validation System**: Three-tier validation (syntax, semantic, template) with structured error messages
- **Context Builder**: Two-phase implementation complete (discovery vs planning contexts)
- **WorkflowManager**: Full lifecycle management with atomic saves and nested workflow support
- **Template System**: Runtime resolution with path support (`$data.field.subfield`) implemented
- **Testing Infrastructure**: Comprehensive patterns for mocking LLM calls and testing flows

## Ambiguities and Resolutions

### 1. LLM Model Selection for Planning - Decision importance (4)

**Status**: ✅ Resolved

The planner needs to use an LLM for workflow generation, but which model should it use?

**Investigation Results**:
- Current LLM node uses `gpt-4o-mini` as default (cost-effective)
- Documentation mentions `claude-sonnet-4-20250514` for planning
- `llm` library supports model switching via `llm.get_model(model_name)`
- Integration tests use `gpt-4o-mini` for cost efficiency

#### Context:
The planner makes sophisticated decisions requiring strong reasoning capabilities, but also needs to be cost-effective for repeated use. Model selection impacts both quality and operational costs.

**Critical Distinction**: This is for the planner's INTERNAL reasoning nodes (WorkflowGeneratorNode, ValidationNode, etc.), NOT for the LLM node that appears in generated workflows. The planner uses LLM internally but doesn't reference Task 12's LLM node in its own implementation.

#### Options:

- [ ] **Option A: Use gpt-4o-mini consistently**
  - **Benefits**: Cost-effective ($0.15/$0.60 per 1M tokens), fast, already default
  - **Drawbacks**: May struggle with complex workflow generation
  - **Example**: `self.model = llm.get_model("gpt-4o-mini")`
  - **Precedent**: Used in LLM node and all integration tests

- [x] **Option B: Use anthropic/claude-sonnet-4-0** ✓ **SELECTED**
  - **Benefits**: Superior reasoning for complex planning, better structured output, proven reliability
  - **Drawbacks**: Higher cost but acceptable for planning quality
  - **Example**: `self.model = llm.get_model("anthropic/claude-sonnet-4-0")`
  - **Precedent**: Standard alias format for llm library's Anthropic integration

- [ ] **Option C: Configurable model with smart defaults**
  - **Benefits**: Flexibility for different use cases
  - **Drawbacks**: Added complexity for MVP
  - **Example**: `model_name = os.getenv("PFLOW_PLANNER_MODEL", "anthropic/claude-sonnet-4-0")`

**Recommendation**: Option B - Use `anthropic/claude-sonnet-4-0` (the llm library's alias) for ALL planner internal reasoning. This ensures consistent, high-quality workflow generation.

**Implementation Note**:
- Install requirement: `llm-anthropic` plugin must be installed
- The planner's internal nodes will use: `self.model = llm.get_model("anthropic/claude-sonnet-4-0")`
- This is separate from Task 12's LLM node which users can configure independently

**Subagent Findings**:
- LLM node implementation shows clean model switching pattern
- `llm` library handles provider-specific configurations automatically
- Error handling transforms provider exceptions to helpful messages

### 2. Retry Strategy for Validation Failures - Decision importance (3)

**Status**: ✅ Resolved

How should the planner handle validation failures and retry with improved prompts?

**Investigation Results**:
- PocketFlow supports `max_retries` at node level (typically 3)
- Validation provides structured errors with paths and suggestions
- Current patterns show progressive prompt enhancement

#### Context:
Validation failures need intelligent retry strategies to guide the LLM toward correct workflow generation without infinite loops.

#### Options:

- [ ] **Option A: Simple retry with error appending**
  - **Benefits**: Simple implementation
  - **Drawbacks**: May repeat same mistakes
  - **Example**: Append errors to prompt and retry

- [x] **Option B: Progressive enhancement with categorized feedback** ✓ **SELECTED**
  - **Benefits**: Targeted improvements based on error type
  - **Drawbacks**: More complex implementation
  - **Example**: Different strategies for structure vs template errors
  - **Precedent**: Error categorization pattern found in validation system

- [ ] **Option C: No retries - fail fast**
  - **Benefits**: Predictable behavior
  - **Drawbacks**: Poor user experience

**Recommendation**: Option B - Use progressive enhancement that categorizes errors and provides increasingly specific guidance on each retry attempt.

**Subagent Findings**:
- Validation system provides error paths like `"nodes[0].type"` for precise feedback
- Template validator distinguishes between missing inputs vs unknown variables
- Error suggestions are already LLM-friendly

### 3. Workflow Discovery Matching Threshold - Decision importance (5)

**Status**: ✅ Resolved

What constitutes a "complete" workflow match in WorkflowDiscoveryNode?

**Investigation Results**:
- Context builder provides workflow descriptions for semantic matching
- WorkflowManager stores workflows with name and description metadata
- Two distinct discovery nodes serve different purposes

#### Context:
WorkflowDiscoveryNode must decide if an existing workflow completely satisfies the user's request, determining whether to use Path A (reuse) or Path B (generate).

#### Options:

- [ ] **Option A: Partial intent matching**
  - **Benefits**: More workflow reuse
  - **Drawbacks**: May not fully satisfy user needs
  - **Example**: "generate changelog" matches even if user wants "and create PR"

- [x] **Option B: Complete intent satisfaction required** ✓ **SELECTED**
  - **Benefits**: Ensures user gets exactly what they need
  - **Drawbacks**: Less reuse, more generation
  - **Example**: Only return "found_existing" if workflow does EVERYTHING requested
  - **Precedent**: Documentation emphasizes complete satisfaction

- [ ] **Option C: Similarity score threshold**
  - **Benefits**: Flexible matching
  - **Drawbacks**: Complex to implement and tune

**Recommendation**: Option B - Require complete intent satisfaction. ComponentBrowsingNode can still select partial workflows as building blocks.

**Subagent Findings**:
- ComponentBrowsingNode can select existing workflows as sub-workflows
- This enables composition without compromising completeness requirement
- WorkflowManager supports nested workflow execution

### 4. Parameter Discovery Architecture - Decision importance (5)

**Status**: ✅ Resolved

How should the two-phase parameter handling work between discovery and mapping?

**Investigation Results**:
- Documentation shows ParameterDiscoveryNode before generation (Path B only)
- ParameterMappingNode is the convergence point for both paths
- Discovery provides context for generation

#### Context:
Parameters need to be discovered early for Path B (to inform generation) but also mapped/verified for both paths at convergence.

#### Options:

- [ ] **Option A: Single parameter extraction node**
  - **Benefits**: Simpler flow
  - **Drawbacks**: Can't inform generation with discovered params
  - **Example**: Only ParameterMappingNode at convergence

- [x] **Option B: Two-phase with discovery then mapping** ✓ **SELECTED**
  - **Benefits**: Generator knows available parameters, full validation possible
  - **Drawbacks**: More complex flow
  - **Example**: ParameterDiscoveryNode → GeneratorNode → ... → ParameterMappingNode
  - **Precedent**: Architecture document shows this pattern clearly

- [ ] **Option C: Merge discovery into generator**
  - **Benefits**: Fewer nodes
  - **Drawbacks**: Violates single responsibility

**Recommendation**: Option B - Implement two-phase parameter handling as documented, with early discovery for Path B and convergent mapping for both paths.

**Subagent Findings**:
- Context builder provides planning context after component selection
- Validator can use discovered_params for template validation
- This architecture enables context-aware generation

### 5. Prep Method Return Pattern for exec_fallback - Decision importance (2)

**Status**: ✅ Resolved

What should prep() methods return when exec_fallback needs shared store access?

**Investigation Results**:
- PocketFlow pattern shows prep() extracting specific data
- exec_fallback only receives prep_res and exception
- Some nodes return entire shared dict when needed

#### Context:
The prep() method should extract specific data, but exec_fallback sometimes needs shared store access for error enrichment.

#### Options:

- [ ] **Option A: Always return specific data**
  - **Benefits**: Clean separation, predictable
  - **Drawbacks**: exec_fallback can't enrich errors with context
  - **Example**: `return shared["user_input"], shared["context"]`

- [x] **Option B: Return shared ONLY when exec_fallback needs it** ✓ **SELECTED**
  - **⚠️ WARNING**: This is an EXCEPTION PATTERN, not default behavior
  - **Benefits**: Flexibility for error handling and recovery
  - **Drawbacks**: Violates normal prep() isolation principle
  - **When to use**: ONLY when exec_fallback genuinely needs context for error recovery
  - **Example**: `return shared  # EXCEPTION: exec_fallback needs full context`
  - **See**: task-17-advanced-patterns.md Pattern 2 for detailed explanation

- [ ] **Option C: Pass shared to exec_fallback directly**
  - **Benefits**: Would be cleaner
  - **Drawbacks**: Requires framework modification

**Recommendation**: Option B - Return shared dict ONLY when exec_fallback genuinely needs it for error recovery. Always include clear comments marking this as an exception pattern. Most nodes should return specific data from prep().

**Subagent Findings**:
- Pattern is documented as valid exception in architecture
- Used for error context enrichment and recovery operations
- Should include comment explaining the need

### 6. Testing Strategy for Meta-Workflow - Decision importance (3)

**Status**: ✅ Resolved

How should the complex planner meta-workflow be tested?

**Investigation Results**:
- Testing patterns show mocking at `llm.get_model()` level
- Integration tests use `RUN_LLM_TESTS=1` flag
- Flow testing uses real node instances

#### Context:
The planner has complex branching logic, multiple paths, and LLM interactions that need comprehensive testing without excessive API costs.

#### Options:

- [ ] **Option A: Full mocking of all components**
  - **Benefits**: Fast, no API costs
  - **Drawbacks**: May not catch integration issues
  - **Example**: Mock every node in the flow

- [x] **Option B: Hybrid - mock LLM, real flow execution** ✓ **SELECTED**
  - **Benefits**: Tests real flow logic, no API costs
  - **Drawbacks**: More complex test setup
  - **Example**: Mock LLM responses, execute real PocketFlow
  - **Precedent**: Current testing patterns in codebase

- [ ] **Option C: Only integration tests with real LLM**
  - **Benefits**: Most realistic
  - **Drawbacks**: Expensive, slow, non-deterministic

**Recommendation**: Option B - Use hybrid approach with BOTH mocked and real LLM tests for comprehensive coverage.

**Testing Implementation**:
- **Unit Tests**: Mock `llm.get_model("anthropic/claude-sonnet-4-0")` with realistic responses
- **Integration Tests**: Optional real API tests with `RUN_LLM_TESTS=1` environment flag
- **Model Consistency**: Use `anthropic/claude-sonnet-4-0` in both mocked and real tests to ensure test validity

**Subagent Findings**:
- Existing pattern patches at `llm.get_model()` level
- Can test complete execution paths through flow
- Separate optional integration tests for real API validation

### 7. Error Feedback Granularity - Decision importance (2)

**Status**: ⚠️ Needs User Input

How verbose should validation error feedback be for LLM consumption?

**Investigation Results**:
- Validation system provides detailed errors with paths
- Template validator gives specific missing variable information
- Current patterns show 3-error limit in prompts

#### Context:
Too much error detail might confuse the LLM, but too little might not guide corrections effectively.

#### Options:

- [ ] **Option A: Single primary error only**
  - **Benefits**: Focused correction
  - **Drawbacks**: May need multiple retries for multiple issues
  - **Example**: Only show first/most important error

- [x] **Option B: Up to 3 most important errors** ✓ **SELECTED**
  - **Benefits**: Balance between focus and comprehensive feedback
  - **Drawbacks**: Need to prioritize errors
  - **Example**: `"; ".join(errors[:3])`
  - **Precedent**: Found in existing examples

- [ ] **Option C: All errors with categorization**
  - **Benefits**: Complete information
  - **Drawbacks**: May overwhelm LLM with details

**Recommendation**: Option B - Provide up to 3 most important errors to balance comprehensive feedback with focus.

**Subagent Findings**:
- Error summarization pattern found: `"; ".join(errors[:3])`
- Validation errors are already prompt-ready strings
- Priority: structure errors > node errors > template errors

### 8. Workflow Storage Integration - Decision importance (3)

**Status**: ✅ Resolved

When and how should the planner integrate with WorkflowManager for saving?

**Investigation Results**:
- WorkflowManager has atomic save with duplicate protection
- CLI handles save prompts after execution
- Planner returns results, CLI manages storage

#### Context:
Generated workflows need to be saved for reuse, but the timing and responsibility need clarification.

#### Options:

- [ ] **Option A: Planner saves automatically**
  - **Benefits**: Guaranteed persistence
  - **Drawbacks**: No user control
  - **Example**: Save in ResultPreparationNode

- [x] **Option B: CLI handles after approval** ✓ **SELECTED**
  - **Benefits**: User control, clear separation
  - **Drawbacks**: CLI needs save logic
  - **Example**: Planner returns IR, CLI prompts and saves
  - **Precedent**: Current CLI patterns show post-execution saves

- [ ] **Option C: Optional save node in planner**
  - **Benefits**: Flexibility
  - **Drawbacks**: Blurs responsibilities

**Recommendation**: Option B - Planner returns results, CLI handles user approval and saving.

**Subagent Findings**:
- CLI already has save prompt logic for interactive mode
- WorkflowManager provides clean save interface
- Separation maintains single responsibility

## Implementation Guidance Based on Resolutions

Based on the resolved ambiguities:

1. **Use `anthropic/claude-sonnet-4-0`** for ALL planner internal reasoning nodes
   - This is the llm library's standard alias for Claude Sonnet
   - Applies to WorkflowGeneratorNode, ComponentBrowsingNode, etc.
   - Planner uses LLM internally but doesn't reference Task 12's LLM node
   - Requires `llm-anthropic` plugin installation

2. **Implement progressive retry enhancement** with error categorization
   - Different strategies for structure vs template errors
   - Use validation error paths for targeted feedback

3. **Require complete workflow matches** in WorkflowDiscoveryNode
   - Only return "found_existing" for complete intent satisfaction
   - ComponentBrowsingNode can still select partial workflows as building blocks

4. **Use two-phase parameter handling** with early discovery for Path B
   - ParameterDiscoveryNode before generation provides context
   - ParameterMappingNode at convergence verifies executability

5. **Return shared dict in prep()** when exec_fallback needs it
   - Only when genuinely needed for error context
   - Include clear comments explaining why

6. **Test with hybrid approach** - both mocked and real LLM tests
   - Mock `llm.get_model("anthropic/claude-sonnet-4-0")` for unit tests
   - Real API integration tests with `RUN_LLM_TESTS=1` flag
   - Ensure model consistency across test types

7. **Provide up to 3 errors** in retry feedback
   - Balance comprehensive feedback with focus
   - Prioritize structure > node > template errors

8. **Let CLI handle workflow saving** after user approval
   - Clear separation of concerns
   - User maintains control over persistence

## Key Architectural Insights

### Separation of Planner LLM vs User-Facing LLM Node

An important architectural distinction emerged during resolution:

1. **Planner's Internal LLM Usage**:
   - The planner uses `anthropic/claude-sonnet-4-0` directly via `llm` library
   - This is for the planner's own reasoning (discovery, generation, validation)
   - Implemented within planner nodes using PocketFlow patterns
   - Not exposed to users or configurable

2. **User-Facing LLM Node (Task 12)**:
   - Available in the registry for users to include in their workflows
   - Can be configured with any model the user prefers
   - Generated workflows may include `{"type": "llm", "params": {...}}`
   - Completely separate from planner's internal LLM usage

This separation ensures:
- **Consistency**: Planner always uses the same high-quality model for reasoning
- **Flexibility**: Users can choose any LLM model for their workflows
- **Clarity**: No confusion between infrastructure (planner) and user features (LLM node)

## Remaining Uncertainties

1. **Error Verbosity Preference**: The optimal level of error detail for LLM consumption may need tuning based on actual performance
2. **Model Cost vs Quality Tradeoff**: May need adjustment based on usage patterns and budget
3. **Retry Count Optimization**: The 3-retry default may need tuning based on success rates

## Appendix: Investigation Details

### Subagent Reports Summary
- **LLM Node**: Found complete implementation with `gpt-4o-mini` default, clean model switching (do not use this node for the planner internals only for for user facing workflows (workflows that the planner GENERATES))
- **Validation System**: Three-tier validation with structured, LLM-friendly error messages
- **PocketFlow Patterns**: Clear prep/exec/post patterns with retry support
- **Context Builder**: Two-phase implementation complete with structure documentation
- **WorkflowManager**: Full lifecycle management with atomic operations
- **Testing Patterns**: Hybrid approach with LLM mocking at library level

### Key Patterns Discovered
- Universal parameter fallback pattern in all nodes
- Progressive error enhancement for retries
- Template resolution with path support
- Atomic workflow saving with duplicate protection
- Two-phase context building (discovery vs planning)

### Files and Components Analyzed
- `/src/pflow/nodes/llm/llm.py` - LLM node implementation
- `/src/pflow/runtime/template_validator.py` - Template validation
- `/src/pflow/planning/context_builder.py` - Context generation
- `/src/pflow/core/workflow_manager.py` - Workflow storage
- `/tests/test_nodes/test_llm/` - LLM testing patterns
- `/tests/test_runtime/` - Flow testing approaches
