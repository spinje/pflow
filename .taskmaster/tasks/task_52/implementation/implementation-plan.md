# Task 52: Comprehensive Implementation Plan

## Overview
Implement Requirements Analysis and Planning nodes to enhance the planner pipeline with intelligent pre-generation analysis and multi-turn conversation for context accumulation.

## Critical Dependencies to Verify First
- [ ] Confirm `llm` library has `model.conversation()` method
- [ ] Verify ParameterDiscoveryNode creates `templatized_input`
- [ ] Check current flow routing in flow.py
- [ ] Understand ResultPreparationNode entry points

## Phase 1: Flow Restructuring (30 minutes)

### 1.1 Update flow.py routing
**File**: `src/pflow/planning/flow.py`

**Current routing to change**:
```python
# Lines ~97-106
discovery_node - "not_found" >> component_browsing
component_browsing - "generate" >> parameter_discovery
parameter_discovery >> workflow_generator
```

**New routing**:
```python
# Move parameter discovery earlier
discovery_node - "not_found" >> parameter_discovery  # MOVED
parameter_discovery >> requirements_analysis          # NEW
requirements_analysis >> component_browsing          # NEW
requirements_analysis - "clarification_needed" >> result_preparation  # NEW ERROR ROUTE
component_browsing - "generate" >> planning          # CHANGED from parameter_discovery
planning >> workflow_generator                       # NEW
planning - "impossible_requirements" >> result_preparation  # NEW ERROR ROUTE
planning - "partial_solution" >> workflow_generator  # NEW PARTIAL ROUTE
```

### 1.2 Import new nodes
Add imports at top of flow.py:
```python
from pflow.planning.nodes import (
    # ... existing imports ...
    RequirementsAnalysisNode,  # NEW
    PlanningNode,              # NEW
)
```

### 1.3 Create node instances
In `create_planner_flow()` function:
```python
requirements_analysis: Node = RequirementsAnalysisNode()  # NEW
planning: Node = PlanningNode()                          # NEW
```

### 1.4 Add debug wrapping if needed
```python
if debug_context:
    requirements_analysis = DebugWrapper(requirements_analysis, debug_context)
    planning = DebugWrapper(planning, debug_context)
```

## Phase 2: RequirementsAnalysisNode Implementation (45 minutes)

### 2.1 Create Pydantic Schema
**File**: `src/pflow/planning/nodes.py` (add near top with other schemas ~line 40)

```python
class RequirementsSchema(BaseModel):
    """Schema for requirements analysis output."""

    is_clear: bool = Field(description="True if requirements can be extracted")
    clarification_needed: Optional[str] = Field(None, description="Message if input too vague")
    steps: list[str] = Field(default_factory=list, description="Abstract operational requirements")
    estimated_nodes: int = Field(0, description="Estimated number of nodes needed")
    required_capabilities: list[str] = Field(default_factory=list, description="Services/capabilities needed")
    complexity_indicators: dict[str, Any] = Field(default_factory=dict, description="Complexity analysis")
```

### 2.2 Implement RequirementsAnalysisNode class
**File**: `src/pflow/planning/nodes.py` (add after ParameterDiscoveryNode ~line 665)

```python
class RequirementsAnalysisNode(Node):
    """Extract abstract operational requirements from templatized input.

    Takes templatized input and extracts WHAT needs to be done without
    implementation details. Abstracts values but keeps services explicit.

    Interface:
    - Reads: templatized_input (str), user_input (str fallback)
    - Writes: requirements_result (dict)
    - Actions: "" (success) or "clarification_needed"
    """

    name = "requirements-analysis"

    def __init__(self, max_retries: int = 2, wait: float = 1.0) -> None:
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        # Get templatized input from ParameterDiscoveryNode
        # Fallback to user_input if not available
        # Get model configuration

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        # Load prompt from markdown
        # Make STANDALONE LLM call (not conversation)
        # Parse response with RequirementsSchema
        # Return structured result

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        # Store requirements_result in shared
        # Check is_clear flag
        # Return "" for success or "clarification_needed" for vague input

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        # Handle LLM failures with safe defaults
```

### 2.3 Create prompt template
**File**: `src/pflow/planning/prompts/requirements_analysis.md` (NEW FILE)

Content should:
- Instruct to extract abstract operations
- Emphasize removing values but keeping services
- Detect if input is too vague
- Output RequirementsSchema structure

## Phase 3: PlanningNode Implementation (1 hour)

### 3.1 Implement PlanningNode class
**File**: `src/pflow/planning/nodes.py` (add after RequirementsAnalysisNode)

```python
class PlanningNode(Node):
    """Create execution plan using available components.

    STARTS a multi-turn conversation that will be continued by WorkflowGenerator.
    Outputs markdown with parseable Status and Node Chain.

    Interface:
    - Reads: requirements_result, browsed_components, planning_context
    - Writes: planning_result, planner_conversation (CRITICAL!)
    - Actions: "" (continue), "impossible_requirements", "partial_solution"
    """

    name = "planning"

    def __init__(self, max_retries: int = 2, wait: float = 1.0) -> None:
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        # Get requirements_result
        # Get browsed_components (node_ids list)
        # Get planning_context
        # Get model configuration

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        # Get model
        # START CONVERSATION: conversation = model.conversation()
        # Build prompt with requirements and components
        # Get markdown response from conversation
        # Parse markdown to extract Status and Node Chain
        # Store conversation in prep_res for post()
        # Return plan_markdown, status, node_chain, conversation

    def _parse_plan_assessment(self, markdown: str) -> dict[str, Any]:
        # Use regex to extract:
        # - **Status**: FEASIBLE/PARTIAL/IMPOSSIBLE
        # - **Node Chain**: node1 >> node2 >> node3
        # Return with defaults if not found

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        # Store planning_result in shared
        # CRITICAL: Store planner_conversation in shared
        # Route based on status:
        #   IMPOSSIBLE -> "impossible_requirements"
        #   PARTIAL -> "partial_solution"
        #   FEASIBLE -> "" (continue)

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        # Raise CriticalPlanningError - planning is critical
```

### 3.2 Create planning prompt
**File**: `src/pflow/planning/prompts/planning.md` (NEW FILE)

Content should:
- Take requirements and available components
- Reason about feasibility
- Create execution plan
- End with parseable Feasibility Assessment section

## Phase 4: Update Existing Nodes (45 minutes)

### 4.1 Update ComponentBrowsingNode
**File**: `src/pflow/planning/nodes.py` (~line 242 in prep method)

Add requirements consideration:
```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    # ... existing code ...

    # NEW: Get requirements if available
    requirements_result = shared.get("requirements_result", {})

    return {
        # ... existing fields ...
        "requirements_result": requirements_result,  # NEW
    }
```

Update prompt building to include requirements context.

### 4.2 Update WorkflowGeneratorNode
**File**: `src/pflow/planning/nodes.py` (~line 1010)

Major changes for conversation support:

```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    return {
        # ... existing fields ...
        "planner_conversation": shared.get("planner_conversation"),  # NEW
        "planning_result": shared.get("planning_result"),  # NEW
    }

def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    # Get conversation from prep_res
    conversation = prep_res.get("planner_conversation")

    if not conversation:
        # Shouldn't happen, but create new as fallback
        model = llm.get_model(prep_res["model_name"])
        conversation = model.conversation()
        logger.warning("No conversation found, creating new one")

    # Determine prompt based on retry status
    if prep_res.get("validation_errors") and prep_res.get("generation_attempts", 0) > 0:
        # RETRY - conversation already has context
        prompt = self._build_retry_prompt(prep_res)
    else:
        # FIRST ATTEMPT - conversation has plan
        prompt = "Now generate the JSON workflow based on the plan."

    # Use conversation.prompt instead of model.prompt
    from pflow.planning.ir_models import FlowIR
    response = conversation.prompt(prompt, schema=FlowIR, temperature=prep_res["temperature"])

    # ... rest of method ...

def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    # ... existing code ...

    # CRITICAL: Preserve conversation for retry
    if prep_res.get("planner_conversation"):
        shared["planner_conversation"] = prep_res["planner_conversation"]

    return "validate"
```

## Phase 5: Testing Strategy (1.5 hours)

### 5.1 Unit Tests for RequirementsAnalysisNode
**File**: `tests/test_planning/unit/test_requirements_analysis_node.py` (NEW)

Test cases:
1. Clear input produces is_clear=true
2. Vague input produces is_clear=false
3. Values are abstracted ("20 issues" -> "filtered issues")
4. Services remain explicit (keeps "GitHub")
5. No template variables in output
6. Returns clarification_needed action when vague

### 5.2 Unit Tests for PlanningNode
**File**: `tests/test_planning/unit/test_planning_node.py` (NEW)

Test cases:
1. Creates new conversation object
2. Includes requirements in prompt
3. Outputs valid Status values
4. Outputs valid node chain format
5. Uses only browsed components
6. Parses markdown correctly
7. Stores conversation in shared

### 5.3 Integration Tests
**File**: `tests/test_planning/integration/test_conversation_flow.py` (NEW)

Test cases:
1. Conversation persists from Planning to Generator
2. Conversation persists across retries
3. Context accumulates properly
4. Cost reduction from caching (mock and verify)

### 5.4 Update existing tests
Files that may need updates:
- `tests/test_planning/integration/test_planner_flow.py`
- `tests/test_planning/unit/test_workflow_generator_node.py`

## Phase 6: Prompt Creation (30 minutes)

### 6.1 Requirements Analysis Prompt
**File**: `src/pflow/planning/prompts/requirements_analysis.md`

### 6.2 Planning Prompt
**File**: `src/pflow/planning/prompts/planning.md`

### 6.3 Update Component Browsing Prompt
**File**: `src/pflow/planning/prompts/component_browsing.md`
- Add section for considering requirements

### 6.4 Update Workflow Generator Prompt
**File**: `src/pflow/planning/prompts/workflow_generator.md`
- Adjust for conversation context

## Phase 7: Verification (30 minutes)

### 7.1 Run all tests
```bash
pytest tests/test_planning/ -v
```

### 7.2 Test all 25 criteria from spec
Create checklist and verify each one

### 7.3 Manual testing scenarios
1. Simple workflow (read file, process)
2. Complex workflow (GitHub changelog)
3. Vague input ("process data")
4. Impossible requirements (Kubernetes)
5. Retry with validation errors

### 7.4 Performance verification
- Measure Requirements extraction time (< 2 seconds)
- Measure Planning time (< 3 seconds)
- Verify conversation memory (< 100KB)
- Check context caching reduction

## File Modification Summary

**Files to Modify**:
1. `src/pflow/planning/flow.py` - Update routing
2. `src/pflow/planning/nodes.py` - Add new nodes, update existing
3. `src/pflow/planning/prompts/component_browsing.md` - Add requirements context
4. `src/pflow/planning/prompts/workflow_generator.md` - Adjust for conversation

**Files to Create**:
1. `src/pflow/planning/prompts/requirements_analysis.md`
2. `src/pflow/planning/prompts/planning.md`
3. `tests/test_planning/unit/test_requirements_analysis_node.py`
4. `tests/test_planning/unit/test_planning_node.py`
5. `tests/test_planning/integration/test_conversation_flow.py`

## Risk Mitigation

**Risk 1**: Conversation class doesn't exist
- Mitigation: Check first, have fallback to regular prompts

**Risk 2**: Breaking existing functionality
- Mitigation: Run full test suite after each phase

**Risk 3**: Performance degradation
- Mitigation: Add timing logs, monitor closely

**Risk 4**: Complex regex parsing fails
- Mitigation: Use simple patterns with good defaults

## Success Criteria Checklist

- [ ] All 25 test criteria from spec pass
- [ ] `make test` passes with no regressions
- [ ] `make check` passes (linting, type checking)
- [ ] Conversation context accumulates properly
- [ ] Requirements correctly abstract values
- [ ] Planning correctly parses markdown
- [ ] Error messages are clear for vague/impossible
- [ ] Context caching provides cost reduction
- [ ] No existing functionality is broken

## Estimated Timeline

- Phase 1 (Flow): 30 minutes
- Phase 2 (Requirements): 45 minutes
- Phase 3 (Planning): 60 minutes
- Phase 4 (Updates): 45 minutes
- Phase 5 (Testing): 90 minutes
- Phase 6 (Prompts): 30 minutes
- Phase 7 (Verification): 30 minutes

**Total: ~5.5 hours**

## Notes

- START with conversation verification - it's critical
- Test frequently - after each phase if possible
- Keep conversation focused - only Planning/Generator
- Remember Parameter Discovery MUST move first
- Planning can ONLY use browsed components
- Requirements must NOT have template variables
- Preserve conversation across retries