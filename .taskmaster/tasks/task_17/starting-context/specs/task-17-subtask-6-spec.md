# Feature: flow_orchestration

## Objective

Wire all planner nodes into complete meta-workflow with branching.

## Requirements

* Must create ResultPreparationNode class in nodes.py
* Must create flow.py file with create_planner_flow() function
* Must handle two-path convergence at ParameterMappingNode
* Must define retry loop edges with 3-attempt limit
* Must store planner_output dict in shared store

## Scope

* Tests full flow execution using test WorkflowManager for isolation
* Does not modify existing node implementations
* Does not handle CLI integration

## Inputs

* `shared`: dict - PocketFlow shared store containing:
  * `user_input`: str - Natural language request
  * `workflow_manager`: Optional[WorkflowManager] - For workflow discovery
  * `stdin_data`: Optional[str] - Command stdin for parameter fallback

## Outputs

Returns: None - Final action from ResultPreparationNode

Side effects:
* `shared["planner_output"]`: dict containing:
  * `success`: bool - Whether workflow is ready for execution
  * `workflow_ir`: Optional[dict] - Found or generated workflow IR
  * `execution_params`: Optional[dict] - Parameters for runtime
  * `missing_params`: Optional[list[str]] - Required but missing parameters
  * `error`: Optional[str] - Error message if failed
  * `workflow_metadata`: Optional[dict] - Workflow metadata

## Structured Formats

```python
{
    "planner_output": {
        "success": bool,
        "workflow_ir": Optional[dict],
        "execution_params": Optional[dict],
        "missing_params": Optional[list[str]],
        "error": Optional[str],
        "workflow_metadata": Optional[dict]
    }
}
```

## State/Flow Changes

- None

## Constraints

* ResultPreparationNode must handle 3 entry points
* Must use exact action strings from existing nodes
* Must follow PocketFlow Flow API patterns
* Empty string action means simple continuation

## Rules

1. ResultPreparationNode must be added to src/pflow/planning/nodes.py
2. ResultPreparationNode must return None to end flow
3. ResultPreparationNode must handle success path from ParameterPreparationNode
4. ResultPreparationNode must handle params_incomplete from ParameterMappingNode
5. ResultPreparationNode must handle failed from ValidatorNode
6. src/pflow/planning/flow.py must be created with create_planner_flow() function
7. create_planner_flow() must be exported in src/pflow/planning/__init__.py
8. create_planner_flow() must use Flow(start=discovery_node)
9. Path A must connect found_existing to ParameterMappingNode
10. Path B must connect not_found to ComponentBrowsingNode
11. ComponentBrowsingNode must connect generate to ParameterDiscoveryNode
12. ParameterDiscoveryNode must connect empty string to WorkflowGeneratorNode
13. WorkflowGeneratorNode must connect validate to ValidatorNode
14. ValidatorNode must connect retry to WorkflowGeneratorNode
15. ValidatorNode must connect metadata_generation to MetadataGenerationNode
16. ValidatorNode must connect failed to ResultPreparationNode
17. MetadataGenerationNode must connect empty string to ParameterMappingNode
18. ParameterMappingNode must connect params_complete to ParameterPreparationNode
19. ParameterMappingNode must connect params_incomplete to ResultPreparationNode
20. ParameterPreparationNode must connect empty string to ResultPreparationNode
21. ResultPreparationNode must determine success based on workflow_ir and execution_params presence
22. ResultPreparationNode must build error message from missing_params or validation_errors
23. Flow must document retry mechanism behavior in comments

## Edge Cases

* workflow_ir is None → success=False, error="Failed to find or generate workflow"
* execution_params is None but workflow exists → success=False, error includes missing_params
* validation_errors present → success=False, error includes first 3 errors
* generation_attempts >= 3 → routes to failed
* empty browsed_components → poor generation context but continues
* LLM failures in any node → exec_fallback provides graceful degradation

## Error Handling

* Missing user_input → ValueError in prep() for Discovery, Browsing, ParameterDiscovery, ParameterMapping nodes
* ParameterPreparationNode missing extracted_params → ValueError at line 887 (flow crashes)
* 7 of 8 nodes have exec_fallback (ParameterPreparationNode lacks it)
* Empty planning context → WorkflowGeneratorNode raises ValueError in exec() at line 990

## Non-Functional Criteria

- None

## Examples

```python
# Path A - Workflow Reuse
shared = {"user_input": "generate changelog", "workflow_manager": wm}
flow.run(shared)
# Routes: discovery -> found_existing -> param_mapping -> params_complete -> param_prep -> result
# shared["planner_output"]["success"] = True

# Path B - Workflow Generation
shared = {"user_input": "create bug triage report"}
flow.run(shared)
# Routes: discovery -> not_found -> browsing -> generate -> param_discovery -> generator -> validate -> validator -> metadata_generation -> param_mapping -> params_complete -> param_prep -> result
# shared["planner_output"]["success"] = True

# Missing Parameters
shared = {"user_input": "analyze issue"}
flow.run(shared)
# Routes end at param_mapping -> params_incomplete -> result
# shared["planner_output"]["success"] = False
# shared["planner_output"]["error"] = "Missing required parameters: issue_number"
```

## Test Criteria

1. ResultPreparationNode class exists in nodes.py
2. ResultPreparationNode returns None
3. ResultPreparationNode handles success path correctly
4. ResultPreparationNode handles params_incomplete path correctly
5. ResultPreparationNode handles failed path correctly
6. flow.py file exists with create_planner_flow() function
7. create_planner_flow() exported in __init__.py
8. create_planner_flow() creates Flow with discovery as start
9. Path A edges defined correctly
10. Path B edges defined correctly
11. Retry loop edge defined from validator to generator
12. Empty string actions continue to next node
13. Named actions route conditionally
14. ResultPreparationNode sets success=True when workflow_ir and execution_params present
15. ResultPreparationNode sets success=False when missing_params present
16. ResultPreparationNode sets success=False when validation_errors present
17. ResultPreparationNode includes error message when success=False
18. Retry mechanism behavior documented in code comments
19. All 3 entry points to ResultPreparationNode wired
20. Convergence at ParameterMappingNode from both paths
21. Flow structure can be inspected without execution
22. Node instances created correctly
23. Action strings match exactly verified values
24. Full planner execution works with test WorkflowManager
25. Retry mechanism executes correctly with 3-attempt limit

## Notes (Why)

* ResultPreparationNode returns None following PocketFlow's standard final node pattern
* Retry loop will execute correctly with 3-attempt limit preventing infinite loops
* Three entry points to ResultPreparationNode handle all failure modes
* Empty string actions used for simple continuation per PocketFlow conventions
* Convergence at ParameterMappingNode enables parameter verification for both paths

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 2                          |
| 3      | 3                          |
| 4      | 4                          |
| 5      | 5                          |
| 6      | 6                          |
| 7      | 7                          |
| 8      | 8                          |
| 9      | 9                          |
| 10     | 10                         |
| 11     | 10                         |
| 12     | 10, 12                     |
| 13     | 10                         |
| 14     | 11                         |
| 15     | 10                         |
| 16     | 10, 5                      |
| 17     | 10, 12                     |
| 18     | 9, 10                      |
| 19     | 9, 10, 4                   |
| 20     | 9, 10, 12                  |
| 21     | 14, 15, 16                 |
| 22     | 17                         |
| 23     | 18                         |

## Versioning & Evolution

* v1.0.0 - Initial specification for Task 17 Subtask 6

## Epistemic Appendix

### Assumptions & Unknowns

* Verified: All 8 existing nodes are implemented in src/pflow/planning/nodes.py (ResultPreparationNode does not exist)
* Verified: Action strings are exactly as documented (checked actual return statements)
* Verified: WorkflowGeneratorNode.exec_fallback() returns compatible structure at lines 1041-1070
* Verified: 7 of 8 nodes have exec_fallback (ParameterPreparationNode lacks it)
* Verified: ParameterPreparationNode raises ValueError at line 887 if extracted_params missing
* Unknown: Whether CLI will check flow return value or only read shared["planner_output"]

### Conflicts & Resolutions

* Implementation guide shows "Returns complete" but PocketFlow pattern is return None - Resolution: Use None per standard pattern
* Handoff warns loops don't work but PocketFlow tests show they do - Resolution: Loops work correctly; previous test issues were due to poor test setup, not framework limitation

### Decision Log / Tradeoffs

* Chose to return None from ResultPreparationNode over "complete" for consistency with PocketFlow patterns (verified in cookbook examples)
* Chose to define and test retry loop as it works correctly in both testing and production
* Chose to handle all error paths in ResultPreparationNode rather than letting exceptions propagate
* Verified all action strings from actual code rather than relying on documentation
* Chose to use test WorkflowManager via shared store for deterministic integration testing

### Ripple Effects / Impact Map

* CLI must read from shared["planner_output"] not flow return value
* Retry functionality works correctly with 3-attempt limit
* Test strategy can verify full execution using test WorkflowManager for isolation

### Residual Risks & Confidence

* Risk: ParameterPreparationNode lacks exec_fallback and raises ValueError at line 887 if extracted_params missing. Mitigation: ParameterMappingNode always writes extracted_params. Confidence: High
* Risk: Multiple nodes raise ValueError if user_input missing. Mitigation: CLI must always provide user_input. Confidence: Medium

### Epistemic Audit (Checklist Answers)

1. Verified all 8 nodes exist via code inspection; only assumption is CLI reads shared store not return value
2. Wrong CLI assumption would require minor adjustment to return planner_output instead of None
3. Prioritized robustness (handling all error paths) over elegance
4. All 22 rules have corresponding test criteria
5. Affects CLI integration pattern and future retry mechanism activation
6. Remaining uncertainty only on CLI integration detail; Confidence: High for all verified implementation details