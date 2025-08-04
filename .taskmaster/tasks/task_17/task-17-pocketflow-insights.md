# Task 17: PocketFlow Implementation Insights

## Critical Distinction: Two Contexts

There are TWO different contexts where PocketFlow principles apply:

### Context 1: The AI Agent IMPLEMENTING the Planner
The AI agent (Claude or another) who writes the code for the planner should follow the Agentic Coding principles:
- Humans define requirements and high-level design
- AI implements the nodes and flow
- Start simple, fail fast, iterate frequently
- Follow the 7-step process from the guide

### Context 2: The Planner Itself
The planner is NOT an agent - it's a **fixed workflow** that generates other workflows:
- Deterministic execution with predefined branching
- No dynamic tool selection or open-ended decisions
- Follows the "Workflow" pattern, not the "Agent" pattern
- LLM calls are embedded in specific nodes, not available as tools

## What the Planner Actually Is

The planner implements the **Workflow Pattern** with elements of **Supervisor Pattern**:
- **Fixed task decomposition** into sequential nodes
- **Predetermined branching** based on discovery results
- **Validation loops** with bounded retries
- **NO agent-like tool selection** or dynamic decision space

## File Structure (PocketFlow Convention)

Based on the PocketFlow guide, the planner should follow this exact structure:

```
src/pflow/planning/
├── flow.py           # Contains create_planner_flow() function
├── nodes.py          # ALL node definitions in one file
├── utils/            # ONLY external interactions
│   ├── __init__.py
│   ├── workflow_loader.py    # Load workflows from disk
│   ├── registry_helper.py    # Registry access utilities
│   └── context_wrapper.py    # Wrapper for context builder calls
├── prompts/          # Prompt templates (data, not code)
│   ├── __init__.py
│   └── templates.py  # All prompt strings
└── ir_models.py      # Pydantic models for IR generation
```

## What DOESN'T Apply to the Planner

Since the planner is a fixed workflow, NOT an agent, these aspects don't apply:

### 1. Dynamic Tool Selection
- The planner can't choose which tools to use at runtime
- All "tool usage" is hardcoded in node implementations
- No exploration or trial-and-error with different approaches

### 2. Open Action Space
- No unbounded set of possible actions
- Fixed edges in the flow graph
- Predetermined branching conditions

### 3. Agent-Style Utilities
- The `utils/` folder is for code organization, not dynamic tools
- Helper functions are called deterministically within nodes
- No "body" of utilities the planner chooses from

### 4. Interactive Decision Making
- No back-and-forth with users during execution
- No asking for clarification mid-flow
- All decisions based on initial input and discovered data

## Critical Design Principles from PocketFlow

### 1. Utilities vs Nodes Distinction (Adapted for Fixed Workflow)

**Utilities** (`utils/` folder) - External I/O ONLY:
```python
# utils/workflow_loader.py
def load_workflow(name: str) -> dict:
    """Load workflow from disk - pure I/O operation."""
    workflow_manager = WorkflowManager()
    return workflow_manager.load(name)

# utils/registry_helper.py
def get_node_metadata(registry: Registry, node_type: str) -> dict:
    """Extract metadata from registry - data access only."""
    return registry.get(node_type, {})
```

**Nodes** (`nodes.py`) - Core Logic and LLM Reasoning:
```python
# ALL LLM reasoning is CORE functionality, not utility
class WorkflowGeneratorNode(Node):
    def exec(self, prep_res):
        # LLM reasoning is CORE - happens in node, not utility
        model = llm.get_model("anthropic/claude-sonnet-4-0")
        return model.prompt(prompt, schema=FlowIR)
```

### 2. Shared Store Design (CRITICAL)

The shared store is the communication backbone. Design it BEFORE implementation.

**→ See `task-17-standardized-conventions.md` for the complete recommended schema**

Key principles:
- Group data by stages (Input → Discovery → Generation → Parameters → Output)
- ParameterMappingNode does independent extraction (doesn't reuse discovered_params)
- Track both successful extractions and missing params for routing
- This is a starting point - iterate as needed during implementation

### 3. Node Design Pattern

Each node follows the prep→exec→post lifecycle with CLEAR responsibilities:

```python
class ComponentBrowsingNode(Node):
    """Browse for building blocks - single responsibility."""

    def prep(self, shared):
        """Extract what we need from shared store."""
        return {
            "user_input": shared["user_input"],
            "discovery_context": shared.get("discovery_context", "")
        }

    def exec(self, prep_res):
        """Pure computation - browsing logic with LLM."""
        # NO shared store access here
        # NO side effects
        # ONLY computation
        model = llm.get_model("anthropic/claude-sonnet-4-0")
        # ... browsing logic ...
        return {"node_ids": [...], "workflow_names": [...]}

    def post(self, shared, prep_res, exec_res):
        """Update shared store and return action."""
        shared["browsed_components"] = exec_res
        return "found" if exec_res["node_ids"] else "not_found"
```

### 4. Flow Orchestration Pattern

The flow wiring should be EXPLICIT and VISUAL:

```python
# flow.py
def create_planner_flow():
    """Wire the complete planner meta-workflow."""

    # Create all nodes
    discovery = WorkflowDiscoveryNode()
    browse = ComponentBrowsingNode()
    param_disc = ParameterDiscoveryNode()
    generator = WorkflowGeneratorNode()
    validator = ValidationNode()
    metadata = MetadataGenerationNode()
    param_map = ParameterMappingNode()
    param_prep = ParameterPreparationNode()
    result = ResultPreparationNode()

    # Path A: Found existing workflow
    discovery - "found" >> param_map

    # Path B: Generate new workflow
    discovery - "not_found" >> browse
    browse >> param_disc
    param_disc >> generator
    generator >> validator
    validator - "invalid" >> generator  # Retry loop (max 3)
    validator - "valid" >> metadata
    validator - "failed" >> result  # Max retries exceeded
    metadata >> param_map

    # Convergence point
    param_map - "params_complete" >> param_prep
    param_map - "params_incomplete" >> result  # Missing params

    param_prep >> result

    return Flow(start=discovery)
```

### 5. Implementation Philosophy

**"Keep it simple, stupid!"**
- Start with the simplest possible implementation
- NO premature optimization
- NO complex error handling initially
- Let errors bubble up for debugging

**"FAIL FAST!"**
```python
def exec(self, prep_res):
    # NO try/except - let it fail for debugging
    response = model.prompt(prompt, schema=FlowIR)
    return response.json()  # Will fail if invalid - GOOD!
```

**Logging Everywhere**
```python
def post(self, shared, prep_res, exec_res):
    logger.debug(f"Generator produced workflow with {len(exec_res['nodes'])} nodes")
    shared["generated_workflow"] = exec_res
    return "validate"
```

### 6. Testing Strategy (Hybrid Approach)

**Unit Tests** (mock LLM, real flow):
```python
@patch("llm.get_model")
def test_generation_path(mock_get_model):
    # Mock at the LLM library level
    mock_model = Mock()
    mock_model.prompt.return_value = Mock(json=lambda: {...})
    mock_get_model.return_value = mock_model

    # Run REAL flow
    flow = create_planner_flow()
    shared = {"user_input": "test"}
    flow.run(shared)

    # Verify complete execution
    assert "planner_output" in shared
```

**Integration Tests** (real LLM when needed):
```python
@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"),
                    reason="Set RUN_LLM_TESTS=1")
def test_real_generation():
    # Real LLM call with anthropic/claude-sonnet-4-0
    flow = create_planner_flow()
    # ...
```

## Patterns the Planner Implements

The planner primarily follows these PocketFlow patterns:

1. **Workflow Pattern** (PRIMARY): Fixed sequential task decomposition with predetermined paths
2. **Supervisor Pattern**: Validation with bounded retry loops
3. **Structure Pattern**: Generating structured JSON output via Pydantic
4. **NOT Agent Pattern**: No dynamic decision-making or tool selection

### Relevant PocketFlow Examples to Study

For implementing the planner, focus on these examples:
- `pocketflow-workflow`: Multi-stage sequential processing
- `pocketflow-supervisor`: Quality control with retries
- `pocketflow-structured-output`: JSON/YAML generation
- `pocketflow-flow`: Branching and routing

AVOID studying these (not applicable):
- `pocketflow-agent`: Dynamic tool selection
- `pocketflow-multi-agent`: Agent coordination
- Agent-to-agent protocols

## Key Implementation Order

Based on PocketFlow principles:

1. **Design shared store first** (before any code)
2. **Create utilities for external I/O** (simple functions)
3. **Implement nodes one by one** (single responsibility each)
4. **Wire the flow last** (after all nodes work)
5. **Test incrementally** (each node, then paths, then full flow)

## Common Pitfalls to Avoid

1. **DON'T** put LLM calls in utilities - they're core functionality
2. **DON'T** access shared store in exec() - only in prep() and post()
3. **DON'T** hide errors with try/except initially
4. **DON'T** optimize prematurely - simple first, optimize later
5. **DON'T** mix concerns - each node does ONE thing

## Iteration Expectation

The PocketFlow guide warns: *"You'll likely iterate a lot! Expect to repeat Steps 3–6 hundreds of times."*

This validates our subtask approach - we WILL refine repeatedly. The key is to:
- Start simple
- Test early
- Iterate based on results
- Add complexity gradually

## Guidance for the Implementing Agent

The AI agent who implements the planner should follow these Agentic Coding steps:

### 1. Requirements (Human-led)
- Humans have defined: Natural language → workflow generation
- Success metrics: ≥95% valid workflows, ≥90% user approval
- Two-path architecture with convergence

### 2. Flow Design (Human-AI collaboration)
- Humans provided: High-level meta-workflow design
- Agent refines: Node boundaries and data flow
- Visual diagram created and validated

### 3. Utilities (Human provides, AI implements)
- Humans identified: Context builder, WorkflowManager, Registry
- Agent implements: Simple wrappers for these services
- NO complex logic in utilities

### 4. Node Design (AI-led with human review)
- Agent designs: Shared store structure
- Agent defines: Each node's prep/exec/post
- Human reviews: Validates design before implementation

### 5. Implementation (AI-led)
- **START SIMPLE**: Minimal viable nodes first
- **FAIL FAST**: No error hiding
- **LOG EVERYTHING**: Debug visibility
- **ITERATE**: Expect many refinements
- **READ EXAMPLES**: Study workflow/supervisor patterns, not agent patterns

### 6. Optimization (Human-AI collaboration)
- Human evaluates: Does it work correctly?
- AI refines: Prompts, retry logic, validation
- Both iterate: Until success metrics met

### 7. Reliability (AI-led)
- AI writes: Comprehensive tests
- AI handles: Edge cases and error scenarios
- AI documents: Decisions and tradeoffs

## What This Means for Subtasks

Each subtask should follow this pattern:
1. **Human defines WHAT** (requirements, success criteria)
2. **AI implements HOW** (code, tests, documentation)
3. **Human validates** (does it meet requirements?)
4. **Both iterate** (refine until correct)

## Summary

Building the planner "the PocketFlow way" means:

**For the Implementing Agent**:
- Follow the 7-step Agentic Coding process
- Start simple, fail fast, iterate frequently
- Clear human-AI responsibility separation
- Expect hundreds of iterations

**For the Planner Structure**:
- Fixed workflow pattern, not agent pattern
- Predetermined paths with bounded branching
- Careful shared store design upfront
- Simple, focused nodes with single responsibilities

This dual understanding ensures both the implementation process AND the resulting system follow PocketFlow best practices.
