A previous agent tried to execute the following and failed.

now ALOT of tests are failing, and your context window is running out. We need to decide what changes the agents made (they are the UNSTAGED changes in git) we should keep. it feels its somewhat of a mess? There has been changes to nodes.py, start with verifying it these changes really makes sense?

What we are trying to fix:



## Fix Mock Structures in Integration Tests

Fix Mock Structures in Integration Tests

  Fix the failing integration tests for Task 17's Natural Language Planner
  by correcting mock response structures.

  ## Context
  The planner flow implementation is CORRECT and working. The tests are
  failing because they use wrong mock structures that don't match the
  Pydantic models the nodes expect.

  ## Root Cause
  Tests mock LLM responses with incorrect field names and structures. Each
  node expects specific Pydantic model structures defined in
  src/pflow/planning/nodes.py.

  ## Your Task
  Fix ALL mock response structures in these files:
  1. tests/test_planning/integration/test_planner_integration.py (9 tests)
  2. tests/test_planning/integration/test_planner_smoke.py (3 tests)

  ## Specific Fixes Required

  ### 1. ParameterMappingNode Mock Structure
  WRONG:
  ```python
  "content": [{"input": {
      "parameters": {  # ❌ Wrong field
          "repo": {"value": "x", "source": "user_input", "confidence": 0.9}
    # ❌ Wrong structure
      }
  }}]

  CORRECT (matches ParameterExtraction model):
  "content": [{"input": {
      "extracted": {  # ✅ Correct field per line 461 of nodes.py
          "repo": "anthropics/pflow",  # ✅ Direct values, not nested
          "limit": "50"
      },
      "missing": [],  # List of missing required params
      "confidence": 0.95,
      "reasoning": "Extracted all parameters"
  }}]

  2. ComponentBrowsingNode Mock Structure

  WRONG:
  "content": [{"input": {
      "selected_components": ["llm", "read-file"]  # ❌ Wrong field
  }}]

  CORRECT (matches ComponentSelection model):
  "content": [{"input": {
      "node_ids": ["llm", "read-file", "write-file"],  # ✅ Correct field
      "workflow_names": [],
      "reasoning": "Selected relevant components"
  }}]

  3. Registry Mock Structure (for ComponentBrowsingNode)

  When mocking Registry.load(), ensure each node has interface field:
  with patch("pflow.registry.registry.Registry") as MockRegistry:
      mock_instance = Mock()
      mock_instance.load.return_value = {
          'llm': {
              'interface': {'inputs': [], 'outputs': []},  # ✅ Required
  field
              'description': 'LLM node'
          }
      }
      MockRegistry.return_value = mock_instance

  4. Fix Assertions

  WRONG:
  assert output["workflow_ir"]["name"] == "test"  # ❌ IR doesn't have name
   field

  CORRECT:
  assert output["workflow_ir"]["start_node"] == "fetch"  # ✅ Check IR
  structure
  assert len(output["workflow_ir"]["nodes"]) == 3

  5. Correct Mock Sequence

  Path A needs 2 LLM calls:
  1. WorkflowDiscoveryNode (WorkflowDecision)
  2. ParameterMappingNode (ParameterExtraction)

  Path B needs 7+ LLM calls:
  1. WorkflowDiscoveryNode (WorkflowDecision)
  2. ComponentBrowsingNode (ComponentSelection)
  3. ParameterDiscoveryNode (ParameterDiscovery)
  4. WorkflowGeneratorNode (generates FlowIR)
  5. ValidatorNode (may retry back to generator)
  6. MetadataGenerationNode (WorkflowMetadata)
  7. ParameterMappingNode (ParameterExtraction)

  Reference Implementation

  See tests/test_planning/integration/test_planner_working.py for 2 WORKING
   examples with correct mock structures.

  Validation

  After fixing, ensure:
  - All mocks match their Pydantic model definitions in nodes.py
  - Mock sequences match the path being tested
  - Assertions check actual data structures, not assumed ones
  - Tests use WorkflowManager via shared["workflow_manager"] for isolation

  DO NOT

  - Change the flow implementation (it's correct)
  - Add new test logic (just fix mocks)
  - Skip any tests (fix them all)

  ---


IMPORTANT INSTRUCTIONS:
- **Only use subagents to gather context MAKE THE UPDATES TO THE TESTS YOURSELF.**
- **ONLY FIX ONE TEST FILE AT A TIME.** Then STOP and write a short summary of what you did. I need to verify every file.