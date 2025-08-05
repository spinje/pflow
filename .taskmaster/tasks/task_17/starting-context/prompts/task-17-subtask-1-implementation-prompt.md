# Task 17 - Subtask 1: Foundation & Infrastructure - Agent Instructions

## Critical Pre-Requirement

**IMPORTANT**: This prompt assumes you have already thoroughly read and understand:
- All Task 17 documentation in `.taskmaster/tasks/task_17/`
- The epistemic manifesto
- The two-path architecture (Path A: reuse, Path B: generate)
- How subtasks interconnect and depend on each other
- The shared progress log system

If you haven't read these yet, STOP and read them first.

## The Problem You're Solving

The Natural Language Planner needs a solid foundation for its sophisticated meta-workflow implementation. Without proper directory structure, utility functions for external I/O, LLM configuration, and test infrastructure, the subsequent 6 subtasks cannot be built. This foundation must follow PocketFlow conventions while enabling the two-path architecture that makes the planner powerful.

## Your Mission Within Task 17

Create the foundational infrastructure that enables all other subtasks to build the Natural Language Planner. This includes directory structure, pure I/O utilities (no business logic!), LLM library setup for the planner's internal use, and test fixtures that support both mocked and real LLM testing modes.

## ⚠️ Critical Context: Task 17's Two-Path Architecture

Before implementing this subtask, you MUST understand the overall architecture:

**Path A (Workflow Reuse)**: Discovery → ParameterMapping → Preparation → Result
**Path B (Workflow Generation)**: Discovery → Browsing → ParamDiscovery → Generation → Validation → Metadata → ParameterMapping → Preparation → Result

**CONVERGENCE**: Both paths meet at ParameterMappingNode - the verification gate.

**This Subtask's Role**: Creates the structural foundation that all nodes and flows will be built upon. While this subtask doesn't implement any nodes, it establishes the patterns and utilities that make the two-path architecture possible.

## Dependencies and Prerequisites

### Subtasks That Must Be Complete
None - this is the foundation layer. You can start immediately.

### Files/Outputs You'll Use From Previous Subtasks
- `src/pflow/planning/context_builder.py` already exists from Tasks 15/16
- `pflow.core.workflow_manager.WorkflowManager` already exists from Task 24
- `pflow.registry.Registry` already exists with Node IR data from Task 19
- `pflow.core.exceptions.WorkflowNotFoundError` already exists

## Required Context Review

### Primary Source: Your Subtask Specification
**File**: `.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-1-spec.md`

**This is your PRIMARY source of truth** for requirements, interface contracts, and implementation details specific to Subtask 1.

Since you've already read all Task 17 documentation, focus on:
1. The spec's clear directive that utilities are I/O ONLY (no business logic)
2. Pydantic installation requirement for structured LLM output
3. Exact directory structure to create
4. Test fixture requirements for hybrid testing approach

**CRITICAL**: The spec defines exact behavior and interfaces. Follow it PRECISELY.

## 🔄 Shared Progress Log (CRITICAL!)

**The progress log is SHARED across ALL Task 17 subtasks!**

**Location**: `.taskmaster/tasks/task_17/implementation/progress-log.md`

**Format for your entries**:
```markdown
## [Timestamp] - Subtask 1 - [What You're Trying]
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

You're creating the directory structure and foundational utilities that enable the Natural Language Planner's implementation:

1. **Directory Structure**: Extend `src/pflow/planning/` with proper subdirectories
2. **Workflow Loader**: Thin wrapper around WorkflowManager for loading workflows
3. **Registry Helpers**: Pure data extraction functions (no logic!)
4. **IR Models**: Pydantic models for structured LLM output
5. **Prompt Templates**: String constants for LLM prompts
6. **Test Infrastructure**: Fixtures supporting both mocked and real LLM testing

Example usage within the planner:
```python
# How future subtasks will use your foundation
from pflow.planning.utils.workflow_loader import load_workflow, list_all_workflows
from pflow.planning.utils.registry_helper import get_node_interface, get_node_outputs
from pflow.planning.ir_models import FlowIR, NodeIR, EdgeIR

# In a future node (not part of this subtask)
def prep(self, shared):
    # Use your workflow loader
    workflows = list_all_workflows()
    # Use your registry helpers
    node_outputs = get_node_outputs("github-get-issue", self.registry.data)
```

## Shared Store Contract

### Keys This Subtask READS
None - this subtask creates infrastructure only.

### Keys This Subtask WRITES
None - this subtask creates infrastructure only.

### Expected Data Formats
This subtask documents the expected shared store schema in `__init__.py`:
```python
# Expected shared store keys (initialized by CLI):
# - user_input: Natural language request from user
# - stdin_data: Optional data from stdin pipe
# - current_date: ISO timestamp for context

# Keys written during execution (by future subtasks):
# - discovery_context, discovery_result, browsed_components
# - discovered_params, planning_context, generation_attempts
# - validation_errors, generated_workflow, found_workflow
# - workflow_metadata, extracted_params, verified_params
# - execution_params, planner_output
```

## Key Outcomes You Must Achieve

### Core Deliverables
1. Extended directory structure at `src/pflow/planning/` with utils/ and prompts/ subdirectories
2. `workflow_loader.py` with load_workflow() and list_all_workflows() functions
3. `registry_helper.py` with get_node_interface(), get_node_outputs(), get_node_inputs()
4. `ir_models.py` with Pydantic models: NodeIR, EdgeIR, FlowIR
5. `templates.py` with prompt string constants (not functions!)
6. `conftest.py` with test fixtures for mocked LLM
7. Pydantic installed and importable
8. LLM library configured with anthropic plugin

### Interface Requirements
- All utilities must be pure I/O functions - NO business logic
- Utilities must have complete type hints and docstrings
- Registry helpers return empty dict/list on missing data (no exceptions)
- Workflow loader delegates everything to WorkflowManager

### Integration Points
- Future nodes will import utilities using relative imports: `from .utils.workflow_loader import ...`
- Test fixtures will be used by all subsequent subtask tests
- Pydantic models enable structured LLM output in generation nodes
- Shared store schema guides all node implementations

## Implementation Strategy

### Phase 1: Setup and Dependencies (15 minutes)
1. Verify Pydantic installation: `uv pip install pydantic`
2. Install LLM anthropic plugin: `uv pip install llm-anthropic`
3. Configure LLM: `llm keys set anthropic` (requires API key)
4. Verify setup: `llm models | grep claude` should show anthropic/claude-sonnet-4-0

### Phase 2: Directory Structure (30 minutes)
1. Create utils/ directory in `src/pflow/planning/`
2. Create prompts/ directory in `src/pflow/planning/`
3. Create all `__init__.py` files with proper docstrings
4. Configure module-level logging in main `__init__.py`
5. Document comprehensive shared store schema

### Phase 3: Implementation (60 minutes)
1. Implement workflow_loader.py as thin wrapper
2. Implement registry_helper.py with pure data extraction
3. Create ir_models.py with Pydantic models
4. Create templates.py with string constants
5. Create conftest.py with test fixtures

### Use Parallel Execution

Use subagents to maximize efficiency and avoid context window limitations.

> Always use subagents to gather information, context, do research and verifying assumptions. This is important!
> Always use the `test-writer-fixer` subagent for writing tests, fixing test failures, and debugging test issues. Deploy it alongside implementation, not as a separate phase.

## Critical Technical Details

### Utilities Are I/O Only
**CRITICAL**: The PocketFlow guide emphasizes that LLM calls are CORE functionality, not utilities. This means:
```python
# ❌ WRONG - LLM is core functionality
# utils/llm_helper.py
import llm  # NO! This belongs in nodes

# ✅ CORRECT - Pure I/O only
# utils/workflow_loader.py
from pflow.core.workflow_manager import WorkflowManager

def load_workflow(name: str) -> dict:
    """Thin wrapper - just delegates."""
    if not name:
        raise ValueError("Workflow name cannot be empty")
    manager = WorkflowManager()
    return manager.load(name)  # Pure I/O
```

### Pydantic Models for Structured Output
The `llm` library supports Pydantic models via the schema parameter. Your models enable this:
```python
# ir_models.py
class FlowIR(BaseModel):
    """Flow IR for planner output generation."""
    ir_version: str = Field(default="0.1.0", pattern=r'^\d+\.\d+\.\d+$')
    nodes: List[NodeIR] = Field(..., min_items=1)
    edges: List[EdgeIR] = Field(default_factory=list)
    start_node: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None  # Task 21 feature
    outputs: Optional[Dict[str, Any]] = None  # Task 21 feature
```

### Logging Configuration
Configure logging at module level in the main `__init__.py` (not every init file):
```python
# src/pflow/planning/__init__.py
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
```

## Critical Warnings from Task 17 Experience

### Template Variables Are Sacred
While this subtask doesn't generate workflows, your Pydantic models must support template variable syntax. The pattern is `^[a-zA-Z0-9_-]+$` for node IDs but params can contain `$variable` and `$variable.field.subfield`.

### Understanding Your Path
This foundation enables BOTH paths. Your utilities will be used by nodes in Path A (workflow reuse) and Path B (workflow generation).

### No Thin Wrappers That Add No Value
The workflow loader is acceptable because it provides a clean interface. But don't create wrappers around context_builder - future nodes will import it directly.

## Key Decisions Already Made for Task 17

1. **LLM Model**: anthropic/claude-sonnet-4-0 for planner's internal use
2. **No context_wrapper.py**: Violates "no thin wrapper" principle
3. **Hybrid Testing**: Mock by default, real LLM optional
4. **Single nodes.py**: All nodes in one file (future subtasks)
5. **Prompts as Data**: String constants, not functions
6. **Pydantic for Structure**: Enables `model.prompt(prompt, schema=FlowIR)`

**📋 Note on Specifications**: Your subtask specification is the authoritative source. Follow it precisely - do not deviate from specified behavior, interface contracts, or implementation requirements unless you discover a critical issue (document and ask for clarification).

## Success Criteria

Your implementation is complete when:

✅ Directory structure created: utils/ and prompts/ under src/pflow/planning/
✅ Pydantic is installed and importable (`import pydantic` works)
✅ LLM library configured with anthropic plugin (`llm models` shows claude)
✅ workflow_loader.py delegates all operations to WorkflowManager
✅ registry_helper.py provides pure data extraction functions
✅ ir_models.py contains NodeIR, EdgeIR, and FlowIR Pydantic models
✅ templates.py contains string constants for prompts
✅ conftest.py provides fixtures for both mocked and real LLM testing
✅ All utilities have type hints and docstrings
✅ No utility imports `llm` library (that's for nodes)
✅ `load_workflow("")` raises ValueError
✅ `load_workflow("nonexistent")` raises WorkflowNotFoundError
✅ Registry helpers return appropriate empty types on missing data
✅ Logging configured at module level
✅ Shared store schema documented in `__init__.py`
✅ make test passes (for your subtask's tests)
✅ make check passes
✅ Progress log documents your implementation journey

## Common Pitfalls to Avoid

1. **DON'T put business logic in utilities** - They're I/O only
2. **DON'T import `llm` in any utility** - LLM is core functionality for nodes
3. **DON'T create context_wrapper.py** - It violates the no thin wrapper principle
4. **DON'T forget to install Pydantic** - It's commented out in pyproject.toml
5. **DON'T create functions in templates.py** - Use string constants
6. **DON'T overthink registry helpers** - Just extract data, no validation
7. **DON'T skip documenting shared store keys** - Future subtasks need this

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent conflicts with other subtasks.

**Location**: `.taskmaster/tasks/task_17/subtask_1/implementation-plan.md`

### Why Planning Matters for Subtasks

1. **Prevents breaking interfaces**: Other subtasks depend on your outputs
2. **Identifies integration points**: Discover how you connect to the flow
3. **Optimizes parallelization**: Know what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Existing Structure Analysis**
   - Task: "Analyze what already exists in src/pflow/planning/"
   - Task: "Check how context_builder.py is structured"

2. **Dependency Verification**
   - Task: "Verify WorkflowManager API at pflow.core.workflow_manager"
   - Task: "Check Registry structure and available methods"

3. **Testing Pattern Analysis**
   - Task: "Examine existing test patterns in tests/"
   - Task: "Check how other modules use conftest.py fixtures"

4. **Integration Requirements**
   - Task: "Analyze how utilities will be imported by future nodes"
   - Task: "Check PocketFlow conventions for directory structure"
```

> Note: Your prompts to the subagents should be very specific and detailed, providing full Task 17 context.

### Step 2: Write Your Implementation Plan

Your plan should include:

1. **Interface verification** - Confirm WorkflowManager and Registry APIs
2. **Component breakdown** - Every file to create with purpose
3. **Integration strategy** - How future nodes will use utilities
4. **Risk identification** - What could affect other subtasks
5. **Testing strategy** - How to verify utilities work correctly

### Implementation Plan Template

```markdown
# Task 17 - Subtask 1 Implementation Plan

## Dependencies Verified

### External Dependencies
- WorkflowManager API confirmed at: [location]
- Registry structure verified: [details]
- Context builder exists at: [location]

### For Next Subtasks
- Utilities will be imported as: [pattern]
- Test fixtures available for: [list]

## Shared Store Contract
- Document keys in __init__.py: [list expected keys]

## Implementation Steps

### Phase 1: Setup and Configuration
[Detailed steps for Pydantic and LLM setup]

### Phase 2: Directory Structure
[Exact directories and files to create]

### Phase 3: Implementation
[Order of implementation with rationale]

## Risk Mitigation

| Risk | Impact on Other Subtasks | Mitigation Strategy |
|------|-------------------------|-------------------|
| [Risk] | [Which subtasks affected] | [How to prevent] |

## Validation Strategy
- How to verify utilities work correctly
- How to ensure proper I/O separation
- Testing approach for fixtures
```

### When to Revise Your Plan

Your plan is a living document. Update it when:
- You discover the existing structure differs from expectations
- API verification reveals different methods
- Better approaches become apparent

Document plan changes in the SHARED progress log with rationale.

## Your Implementation Order

### 0. Review Shared Progress Log (FIRST!)

Check what previous subtasks have implemented: `.taskmaster/tasks/task_17/implementation/progress-log.md`

### 1. Create Your Implementation Plan (SECOND!)

Location: `.taskmaster/tasks/task_17/subtask_1/implementation-plan.md`

### Implementation Steps

1. Install and configure dependencies (Pydantic, llm-anthropic)
2. Create directory structure with proper `__init__.py` files
3. Implement workflow_loader.py with thin wrapper pattern
4. Implement registry_helper.py with pure extraction functions
5. Create ir_models.py with Pydantic models for LLM output
6. Create templates.py with prompt string constants
7. Create conftest.py with mocked LLM fixtures
8. Write tests for all utilities
9. Verify `make test` and `make check` pass
10. Document insights in shared progress log

## Real-Time Learning Capture in SHARED Log

**AS YOU IMPLEMENT**, continuously append to the SHARED progress log:

```markdown
## [Timestamp] - Subtask 1 - Setting up LLM library
Attempting to configure llm with anthropic plugin...

Result: Success after discovering need for API key
- ✅ What worked: `llm keys set anthropic` with valid key
- ❌ What failed: Initial attempt without key failed silently
- 💡 Insight: Future subtasks need LLM_API_KEY environment variable

Code that worked:
```bash
uv pip install llm-anthropic
llm keys set anthropic
# Enter API key when prompted
llm models | grep claude  # Verify
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
## [Time] - Subtask 1 - DEVIATION FROM PLAN
- Original plan: Create context_wrapper.py
- Why it failed: Violates "no thin wrapper" principle from PocketFlow guide
- Impact on other subtasks: Nodes will import context_builder directly
- New approach: Document import pattern in README
- Lesson: Always verify patterns against PocketFlow principles
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test utilities work correctly"

**Focus on**:
- Workflow loader delegates to WorkflowManager
- Registry helpers return correct types
- Error handling (empty names, missing workflows)
- Test fixtures support both mock modes
- Pydantic models validate correctly

**What to test**:
- `load_workflow("")` raises ValueError
- `load_workflow("nonexistent")` raises WorkflowNotFoundError
- Registry helpers return empty dict/list appropriately
- Pydantic models accept valid IR
- Test fixtures can mock LLM responses

**Progress Log - Only document testing insights**:
```markdown
## 2024-01-30 14:00 - Subtask 1 - Test fixture discovery
Found that conftest.py fixtures are automatically available to all tests in subdirectories.
This means our fixtures will be usable by all future subtask tests.
```

**Remember**: Foundation tests ensure stability for all future work

## What NOT to Do

- DON'T implement any nodes - that's Subtask 2+
- DON'T create flow.py - that's Subtask 6
- DON'T put ANY business logic in utilities
- DON'T import `llm` library in utilities
- DON'T create complex abstractions - keep it simple
- DON'T forget to document the shared store schema
- DON'T skip installing Pydantic - it's required
- DON'T create context_wrapper.py - import directly

## Getting Started

1. Check the shared progress log for any previous attempts
2. Create your implementation plan in `.taskmaster/tasks/task_17/subtask_1/implementation-plan.md`
3. Start with dependency installation: `uv pip install pydantic llm-anthropic`
4. Configure LLM: `llm keys set anthropic` (you'll need an API key)
5. Create the directory structure incrementally
6. Implement utilities one at a time with tests
7. Run `make test` frequently to catch issues early
8. Document insights in the shared progress log

## Final Notes

This foundation layer seems simple but is critical. Every subsequent subtask depends on:
- Your directory structure being correct
- Utilities providing clean I/O interfaces
- Test fixtures enabling proper mocking
- Pydantic models supporting structured output

Take time to get this right. The two-path architecture with convergence at ParameterMappingNode requires a solid foundation.

## Remember

You're building the foundation for Task 17's Natural Language Planner - a sophisticated meta-workflow that enables pflow's "Plan Once, Run Forever" philosophy. While this subtask doesn't implement the exciting nodes and flows, it creates the structure that makes everything else possible.

Your work here determines whether future subtasks can focus on logic or fight with infrastructure. Build it right, and the two-path architecture will flow naturally from your foundation.

Let's create a rock-solid foundation for the Natural Language Planner! 🚀
