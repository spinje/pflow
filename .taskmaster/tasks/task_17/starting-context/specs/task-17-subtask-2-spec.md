# Feature: task_17_subtask_2_discovery

## Objective

Create discovery nodes that route between workflow reuse and generation paths.

## Requirements

- Must create `src/pflow/planning/nodes.py` with two PocketFlow nodes
- Must implement WorkflowDiscoveryNode as planner entry point
- Must implement ComponentBrowsingNode for Path B building block selection
- Must follow PocketFlow prep/exec/post lifecycle
- Must use existing context_builder from Tasks 15/16
- Must integrate with Simon Willison's llm library
- Must handle both Path A (found_existing) and Path B (not_found) routing
- Must implement exec_fallback for LLM failure recovery
- Must log all routing decisions and data flow

## Scope

- Does not implement parameter extraction nodes
- Does not implement workflow generation nodes
- Does not implement validation nodes
- Does not wire nodes into complete flow
- Does not integrate with CLI

## Inputs

- shared: dict - PocketFlow shared store containing:
  - user_input: str - Natural language request from user
  - stdin_data: Any - Optional data from stdin pipe
  - current_date: str - ISO timestamp for context

## Outputs

Returns: Action string for PocketFlow routing

Side effects:
- WorkflowDiscoveryNode writes to shared:
  - discovery_context: str - Markdown from build_discovery_context()
  - discovery_result: dict - LLM decision result
  - found_workflow: dict - Full workflow metadata from WorkflowManager.load()
- ComponentBrowsingNode writes to shared:
  - browsed_components: dict - Selected nodes and workflows
  - planning_context: str | dict - Markdown context (str) or error dict with "error" key (dict)
  - registry_metadata: dict - Full registry metadata for downstream nodes

## Structured Formats

```python
# WorkflowDiscoveryNode decision structure
class WorkflowDecision(BaseModel):
    found: bool  # True if complete workflow match exists
    workflow_name: Optional[str]  # Name of matched workflow (if found)
    confidence: float  # Match confidence 0.0-1.0
    reasoning: str  # LLM reasoning for decision

# ComponentBrowsingNode selection structure
class ComponentSelection(BaseModel):
    node_ids: List[str]  # Selected node type identifiers
    workflow_names: List[str]  # Selected workflow names as building blocks
    reasoning: str  # Selection rationale
```

## State/Flow Changes

```
WorkflowDiscoveryNode:
  shared["user_input"] → LLM semantic matching → "found_existing" | "not_found"

ComponentBrowsingNode (Path B only):
  shared["user_input"] → Component browsing → "generate"
```

## Constraints

- Node IDs must follow kebab-case convention
- LLM model must be "anthropic/claude-sonnet-4-0"
- Context builder imports must use absolute imports (from pflow.planning.context_builder)
- Registry imports must be direct instantiation pattern

## Rules

1. WorkflowDiscoveryNode must be first node in planner flow
2. WorkflowDiscoveryNode must return "found_existing" when complete workflow match exists
3. WorkflowDiscoveryNode must return "not_found" when no complete workflow match exists
4. WorkflowDiscoveryNode must call build_discovery_context() with optional parameters
5. WorkflowDiscoveryNode must implement exec_fallback returning safe default on LLM failure
6. ComponentBrowsingNode must run only on Path B (after "not_found")
7. ComponentBrowsingNode must select multiple potentially useful components
8. ComponentBrowsingNode must prefer over-inclusive selection to missing components
9. ComponentBrowsingNode must call build_discovery_context() for initial browsing
10. ComponentBrowsingNode must call build_planning_context() with registry_metadata parameter
11. ComponentBrowsingNode must treat workflows as potential building blocks
12. ComponentBrowsingNode must always return "generate" action (routes to ParameterDiscoveryNode)
13. Both nodes must use logger = logging.getLogger(__name__) for logging
14. Both nodes must instantiate Registry() when needed (not singleton)
15. Both nodes must import from pflow.planning.context_builder using absolute imports
16. Both nodes must extract structured data from LLM response using response_data['content'][0]['input']
17. WorkflowManager must be instantiated when loading workflows
18. nodes.py must contain both node classes in single file

## Edge Cases

Empty workflow directory → WorkflowDiscoveryNode returns "not_found"
LLM timeout → exec_fallback returns "not_found"
Multiple partial matches → WorkflowDiscoveryNode returns "not_found"
No relevant components found → ComponentBrowsingNode returns empty lists
Context builder failure → exec_fallback logs error and returns safe default
Invalid user_input → LLM processes best effort
Malformed workflow metadata → Skip workflow in matching
Registry load failure → Return empty component lists

## Error Handling

- LLM API errors → exec_fallback returns "not_found" with logged error
- Context builder exceptions → exec_fallback returns safe defaults
- Missing shared keys → Use default values with warning log
- Pydantic validation errors → Log and use fallback response

## Non-Functional Criteria

- Discovery decision completes within 2 seconds P95
- Component browsing completes within 3 seconds P95
- Logging provides full traceability of routing decisions

## Examples

```python
# Module-level setup
import logging
import json
import llm
from pflow.core.workflow_manager import WorkflowManager
from pflow.core.exceptions import WorkflowNotFoundError
from pflow.planning.context_builder import build_discovery_context, build_planning_context
from pflow.registry import Registry
from pocketflow import Node
from pydantic import BaseModel
from typing import List, Optional

logger = logging.getLogger(__name__)

# Pydantic models for structured output
class WorkflowDecision(BaseModel):
    found: bool
    workflow_name: Optional[str] = None
    confidence: float
    reasoning: str

class ComponentSelection(BaseModel):
    node_ids: List[str]
    workflow_names: List[str]
    reasoning: str

# WorkflowDiscoveryNode implementation
class WorkflowDiscoveryNode(Node):
    def __init__(self):
        super().__init__(max_retries=1, wait=0)
        self.model = llm.get_model("anthropic/claude-sonnet-4-0")

    def prep(self, shared):
        # Load discovery context with all nodes and workflows
        discovery_context = build_discovery_context(
            node_ids=None,  # All nodes
            workflow_names=None,  # All workflows
            registry_metadata=None  # Will load from default registry
        )
        return {
            "user_input": shared.get("user_input", ""),
            "discovery_context": discovery_context
        }

    def exec(self, prep_res):
        prompt = f"""Match this request to existing workflows.

Available workflows:
{prep_res['discovery_context']}

User request: {prep_res['user_input']}

Return found=true ONLY if a workflow completely satisfies the request."""

        response = self.model.prompt(prompt, schema=WorkflowDecision, temperature=0)
        response_data = response.json()
        # CRITICAL: Structured data is nested in content[0]['input'] for Anthropic
        return response_data['content'][0]['input']

    def post(self, shared, prep_res, exec_res):
        shared["discovery_result"] = exec_res
        shared["discovery_context"] = prep_res["discovery_context"]

        if exec_res["found"] and exec_res.get("workflow_name"):
            workflow_manager = WorkflowManager()
            try:
                # load() returns full metadata wrapper with keys: name, description, ir, created_at, updated_at, version
                shared["found_workflow"] = workflow_manager.load(exec_res["workflow_name"])
                logger.debug(f"Found workflow: {exec_res['workflow_name']}")
                return "found_existing"
            except WorkflowNotFoundError:
                logger.warning(f"Workflow {exec_res['workflow_name']} not found")

        logger.debug("No complete workflow match found")
        return "not_found"

    def exec_fallback(self, prep_res, exc):
        logger.error(f"Discovery failed: {exc}")
        return {"found": False, "reasoning": str(exc), "confidence": 0.0}

# ComponentBrowsingNode implementation
class ComponentBrowsingNode(Node):
    def __init__(self):
        super().__init__(max_retries=1, wait=0)
        self.model = llm.get_model("anthropic/claude-sonnet-4-0")

    def prep(self, shared):
        # Get discovery context for browsing
        from pflow.registry import Registry
        registry = Registry()
        registry_metadata = registry.load()

        discovery_context = build_discovery_context(
            node_ids=None,
            workflow_names=None,
            registry_metadata=registry_metadata
        )

        return {
            "user_input": shared.get("user_input", ""),
            "discovery_context": discovery_context,
            "registry_metadata": registry_metadata
        }

    def exec(self, prep_res):
        prompt = f"""Select ALL nodes and workflows that could help build this request.

Available components:
{prep_res['discovery_context']}

User request: {prep_res['user_input']}

Be over-inclusive - include anything potentially useful."""

        response = self.model.prompt(prompt, schema=ComponentSelection, temperature=0)
        response_data = response.json()
        # CRITICAL: Structured data is nested in content[0]['input'] for Anthropic
        return response_data['content'][0]['input']

    def post(self, shared, prep_res, exec_res):
        logger.debug(f"Selected {len(exec_res['node_ids'])} nodes, {len(exec_res['workflow_names'])} workflows")

        # Get detailed planning context for selected components
        planning_context = build_planning_context(
            selected_node_ids=exec_res["node_ids"],
            selected_workflow_names=exec_res["workflow_names"],
            registry_metadata=prep_res["registry_metadata"],
            saved_workflows=None  # Will load automatically
        )

        # Store results in shared
        shared["browsed_components"] = exec_res
        shared["registry_metadata"] = prep_res["registry_metadata"]

        # Check if planning_context is error dict
        if isinstance(planning_context, dict) and "error" in planning_context:
            logger.warning(f"Planning context error: {planning_context['error']}")
            shared["planning_context"] = ""  # Empty context on error
        else:
            shared["planning_context"] = planning_context

        return "generate"  # Always return "generate" - continues Path B to ParameterDiscoveryNode

    def exec_fallback(self, prep_res, exc):
        logger.error(f"Component browsing failed: {exc}")
        return {"node_ids": [], "workflow_names": [], "reasoning": str(exc)}
```

## Test Criteria

1. WorkflowDiscoveryNode with exact match → returns "found_existing"
2. WorkflowDiscoveryNode with no match → returns "not_found"
3. WorkflowDiscoveryNode with partial match → returns "not_found"
4. WorkflowDiscoveryNode calls build_discovery_context() with None parameters
5. WorkflowDiscoveryNode exec_fallback returns dict with found=False
6. ComponentBrowsingNode executes only after "not_found" routing
7. ComponentBrowsingNode selects multiple nodes → node_ids list populated
8. ComponentBrowsingNode includes extra components → over-inclusive selection verified
9. ComponentBrowsingNode calls build_discovery_context() with registry_metadata
10. ComponentBrowsingNode calls build_planning_context() with all required parameters
11. ComponentBrowsingNode includes workflow as building block → workflow_names populated
12. ComponentBrowsingNode always returns "generate" → action string verified
13. Both nodes use logger = logging.getLogger(__name__)
14. Registry() instantiated in ComponentBrowsingNode prep
15. context_builder functions imported at module or method level
16. response_data['content'][0]['input'] used for structured data extraction
17. WorkflowManager() instantiated when loading workflows
18. Single nodes.py file contains both classes → file structure verified
19. Empty workflow directory → "not_found" returned
20. LLM timeout triggers exec_fallback → safe dict returned
21. Multiple partial matches → "not_found" returned
22. No components found → empty lists returned
23. planning_context error dict → empty string stored
24. Invalid user_input → processing attempted
25. WorkflowNotFoundError caught → "not_found" returned
26. Registry.load() returns empty dict → discovery continues

## Notes (Why)

- Single entry point ensures consistent routing logic
- Binary discovery decision simplifies Path A vs Path B branching
- Over-inclusive browsing prevents missing critical components
- Two-phase context loading optimizes LLM token usage
- Direct imports follow PocketFlow node autonomy principle
- exec_fallback ensures planner never crashes on LLM failures

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1, 2                       |
| 2      | 1                          |
| 3      | 2, 3                       |
| 4      | 4                          |
| 5      | 5, 20                      |
| 6      | 6                          |
| 7      | 7                          |
| 8      | 8                          |
| 9      | 9                          |
| 10     | 10                         |
| 11     | 11                         |
| 12     | 12                         |
| 13     | 13                         |
| 14     | 14                         |
| 15     | 15                         |
| 16     | 16                         |
| 17     | 17                         |
| 18     | 18                         |

## Versioning & Evolution

- v1.0.0 — Initial specification for Task 17 Subtask 2

## Epistemic Appendix

### Assumptions & Unknowns

- Verified: build_discovery_context(node_ids, workflow_names, registry_metadata) returns markdown string
- Verified: build_planning_context(selected_node_ids, selected_workflow_names, registry_metadata, saved_workflows) returns str or error dict
- Verified: WorkflowManager.load() returns full metadata wrapper, load_ir() returns just IR
- Verified: Registry() must be instantiated (no singleton)
- Verified: Node methods have signatures prep(shared), exec(prep_res), post(shared, prep_res, exec_res), exec_fallback(prep_res, exc)
- Verified: Structured data is nested in response_data['content'][0]['input'] for Anthropic models
- Assumes: llm library is configured with anthropic plugin and API key
- Unknown: Exact prompt formatting for optimal LLM matching performance
- Unknown: Optimal confidence threshold for workflow matching

### Conflicts & Resolutions

- Documentation suggests semantic matching complexity — Resolution: Start with simple prompt-based matching
- Multiple potential workflow matches ambiguity — Resolution: Require complete match or return "not_found"

### Decision Log / Tradeoffs

- Chose single nodes.py file over split files for initial simplicity
- Chose "not_found" as exec_fallback default over error propagation for robustness
- Chose over-inclusive browsing over precise selection to avoid missing components
- Chose structured output with Pydantic over free-form JSON for type safety

### Ripple Effects / Impact Map

- All subsequent subtasks depend on shared store keys written by these nodes
- Parameter extraction nodes (Subtask 3) depend on planning_context
- Generation nodes (Subtask 4) depend on browsed_components
- Flow orchestration (Subtask 6) depends on action strings

### Residual Risks & Confidence

- Risk: LLM matching accuracy may require prompt refinement (mitigated by exec_fallback)
- Risk: Over-inclusive browsing may include irrelevant components (by design for robustness)
- Risk: planning_context error dict handling may need refinement
- Confidence: Very High for structure and routing logic (all details verified)
- Confidence: High for implementation patterns (based on existing code)
- Confidence: Medium for LLM prompt effectiveness (requires iteration)

### Epistemic Audit (Checklist Answers)

1. Verified all critical implementation details through codebase investigation; only LLM setup remains assumed
2. Wrong assumptions would cause import errors (llm library) or API key errors
3. Prioritized robustness (exec_fallback, error dict handling) over elegance
4. All rules mapped to test criteria (see Compliance Matrix)
5. Affects all downstream subtasks through shared store keys and registry_metadata
6. LLM prompt optimization remains uncertain; Confidence: Very High for structure (verified), Medium for prompts (untested)
