# Feature: generator_node

## Objective

Generate linear workflows with template variables from browsed components.

## Requirements

- Must be named WorkflowGeneratorNode class inheriting from Node
- Must set name class attribute for registry discovery (e.g., name = "generator")
- Must call super().__init__() with optional max_retries and wait parameters
- Must receive discovered_params from shared store
- Must receive planning_context from shared store
- Must receive browsed_components from shared store
- Must use lazy model loading in exec()
- Must use _parse_structured_response() helper method (defined in class)
- Must parse Anthropic response from response_data['content'][0]['input']
- Must create workflow with inputs field defining parameter contract
- Must use template variables ($var syntax) including paths ($var.field)
- Must route to "validate" after execution
- Must implement exec_fallback for error recovery
- Must handle empty planning_context as error condition
- Must import FlowIR from pflow.planning.ir_models
- Must use logger (available at module level)
- Must emphasize template variables in LLM prompt

## Scope

- Does not validate node types exist
- Does not verify template variables resolve
- Does not create branching workflows
- Does not generate fallback workflows in exec_fallback
- Does not use registry_metadata
- Does not enforce discovered_params usage
- Does not create complex workflow patterns
- Does not support multiple nodes of same type

## Inputs

- shared["discovered_params"]: dict[str, str] - Parameter hints from ParameterDiscoveryNode (optional)
- shared["browsed_components"]: dict[str, list[str]] - Selected node_ids and workflow_names
- shared["planning_context"]: str - Detailed markdown about components (required non-empty)
- shared["user_input"]: str - Original natural language request
- shared["validation_errors"]: list[str] - Previous validation errors if retry (optional)
- shared["generation_attempts"]: int - Number of previous attempts (optional, default 0)
- self.params["model"]: str - LLM model name (optional, default "anthropic/claude-sonnet-4-0")
- self.params["temperature"]: float - LLM temperature (optional, default 0.0)

## Outputs

Returns: Action string "validate"

Side effects:
- shared["generated_workflow"]: dict - Complete workflow IR with inputs field
- shared["generation_attempts"]: int - Updated attempt count

## Structured Formats

```json
{
  "generated_workflow": {
    "ir_version": "0.1.0",
    "inputs": {
      "<param_name>": {
        "description": "string",
        "required": "boolean",
        "type": "string",
        "default": "any (optional)"
      }
    },
    "nodes": [
      {
        "id": "string",
        "type": "string",
        "params": {"<key>": "<value or $template>"}
      }
    ],
    "edges": [
      {"from": "string", "to": "string"}
    ]
  }
}
```

## State/Flow Changes

- None

## Constraints

- Maximum 3 retry attempts (PocketFlow max_retries)
- Linear workflows only (no branching edges)
- Template variables must match inputs field keys
- Node IDs must be descriptive and unique
- Planning context must be non-empty string

## Rules

1. Class must be named WorkflowGeneratorNode(Node)
2. Set name = "generator" as class attribute (not in __init__)
3. Call super().__init__() with max_retries and wait parameters
4. If planning_context is empty string then raise ValueError
5. If planning_context is not string then raise ValueError
6. Load model using llm.get_model(prep_res["model_name"]) in exec()
7. Build prompt that emphasizes "use template variables ($var) for ALL dynamic values"
8. Build prompt that emphasizes "NEVER hardcode values like '1234' - use $variable"
9. Build prompt that specifies "generate LINEAR workflow only - no branching"
10. Include planning_context and user_input in prompt
11. If generation_attempts > 0 then append validation_errors to prompt
12. If validation_errors in prompt then instruct to fix only specific errors
13. Call model.prompt(prompt, schema=FlowIR) with temperature from prep_res
14. Parse response using _parse_structured_response(response, FlowIR)
15. Extract result from response_data['content'][0]['input'] for Anthropic
16. If response_data is None then raise ValueError("LLM returned None response")
17. If response parsing fails then raise ValueError with details
18. Store workflow in shared["generated_workflow"]
19. Increment shared["generation_attempts"] by 1
20. Return action string "validate"
21. Add logging: logger.debug(f"Generating workflow for: {user_input[:100]}...")
22. Add logging: logger.debug(f"Generated {len(nodes)} nodes")
23. Template variables in params must use $ prefix
24. Template variables can include paths like $var.field.subfield
25. Each template variable must have corresponding key in inputs field
26. If discovered_params exists then use as hints for inputs field
27. Rename parameters from discovered_params for clarity when appropriate
28. Mark parameters required=True unless universally optional
29. Set default values only for universal defaults not request-specific values
30. Generate linear edges only (no action field in edges)
31. Use descriptive node IDs not sequential numbers
32. Avoid multiple nodes of same type to prevent shared store collision
33. Use workflow_name for saved workflows not workflow_ref
34. Include param_mapping when using workflow as node
35. Set storage_mode="mapped" for workflow nodes
36. Implement post() to store workflow and return "validate"

## Edge Cases

- planning_context empty string → raise ValueError("Planning context is required but was empty")
- planning_context is dict with error key → raise ValueError with error details
- LLM response is None → raise ValueError("LLM returned None response")
- LLM response missing content field → raise ValueError("Invalid LLM response structure")
- FlowIR parsing fails → raise ValueError with parse error details
- validation_errors exceeds 3 items → use only first 3 errors
- discovered_params is None → proceed without parameter hints
- browsed_components empty → generate single LLM node workflow
- cur_retry exceeds max_retries → exec_fallback called by framework
- Invalid model name → exec_fallback handles LLM exception

## Error Handling

- Planning context validation failure → raise ValueError immediately
- LLM API failure → let exception propagate to trigger exec_fallback
- Response parsing failure → raise ValueError with details
- exec_fallback returns dict with success=False, error=str(exc), workflow=None

## Non-Functional Criteria

- LLM response time < 5 seconds P95
- Temperature = 0.0 for deterministic generation
- Maximum prompt size < 8000 tokens

## Examples

### Critical: Anthropic nested response parsing
```python
# The actual response structure from Anthropic
response_data = response.json()
if response_data is None:
    raise ValueError("LLM returned None response")

# CRITICAL: Anthropic nests the actual data here
result = response_data['content'][0]['input']  # This exact path!
# result now contains the FlowIR dict
```

### Valid generation with discovered params
```python
# Input
discovered_params = {"filename": "report.csv", "limit": "20"}
planning_context = "## Selected Components\n\n### read-file..."

# Generated workflow
{
  "ir_version": "0.1.0",
  "inputs": {
    "input_file": {
      "description": "File to process",
      "required": True,
      "type": "string"
    },
    "max_items": {
      "description": "Maximum items to process",
      "required": False,
      "type": "integer",
      "default": 100
    }
  },
  "nodes": [
    {"id": "read_data", "type": "read-file", "params": {"path": "$input_file"}},
    {"id": "process", "type": "llm", "params": {"prompt": "Process up to $max_items items"}}
  ],
  "edges": [
    {"from": "read_data", "to": "process"}
  ]
}
```

### Critical implementation skeleton
```python
import logging
from typing import Any

import llm
from pocketflow import Node
from pflow.planning.ir_models import FlowIR

logger = logging.getLogger(__name__)


class WorkflowGeneratorNode(Node):
    """Generates workflows using LLM with structured output."""

    name = "generator"  # Class attribute for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared):
        # Prepare all data for exec
        return {
            "model_name": self.params.get("model", "anthropic/claude-sonnet-4-0"),
            "temperature": self.params.get("temperature", 0.0),
            "planning_context": shared.get("planning_context", ""),
            "user_input": shared.get("user_input", ""),
            "discovered_params": shared.get("discovered_params"),
            "validation_errors": shared.get("validation_errors", []),
            "generation_attempts": shared.get("generation_attempts", 0)
        }

    def exec(self, prep_res):
        # CRITICAL: Lazy load model
        model = llm.get_model(prep_res["model_name"])

        # CRITICAL: Check planning context
        if not prep_res["planning_context"]:
            raise ValueError("Planning context is required but was empty")

        # Build prompt with template emphasis
        prompt = self._build_prompt(prep_res)

        # Generate with schema
        response = model.prompt(prompt, schema=FlowIR, temperature=prep_res["temperature"])

        # CRITICAL: Parse nested Anthropic response
        result = self._parse_structured_response(response, FlowIR)

        return {"workflow": result, "attempt": prep_res["generation_attempts"] + 1}

    def _build_prompt(self, prep_res):
        prompt = f'''Generate a workflow for: {prep_res["user_input"]}

Available components:
{prep_res["planning_context"]}

CRITICAL Requirements:
1. Use template variables ($variable) for ALL dynamic values
2. NEVER hardcode values like "1234" - use $issue_number instead
3. Generate LINEAR workflow only - no branching
4. Template variables can use paths like $data.field.subfield
'''

        if prep_res["generation_attempts"] > 0 and prep_res["validation_errors"]:
            prompt += "\n\nFix ONLY these specific issues:\n"
            for error in prep_res["validation_errors"][:3]:
                prompt += f"- {error}\n"
            prompt += "Keep the rest unchanged."

        return prompt

    def _parse_structured_response(self, response: Any, expected_type: type) -> dict[str, Any]:
        """Parse structured LLM response with Anthropic's nested format."""
        try:
            response_data = response.json()
            if response_data is None:
                raise ValueError("LLM returned None response")
            # CRITICAL: Structured data is nested in content[0]['input'] for Anthropic
            content = response_data.get("content")
            if not content or not isinstance(content, list) or len(content) == 0:
                raise ValueError("Invalid LLM response structure: missing or empty content")
            result = content[0]["input"]
            # Convert Pydantic model to dict if needed
            if hasattr(result, "model_dump"):
                return result.model_dump()
            return result
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            raise ValueError(f"Response parsing failed: {e}") from e

    def post(self, shared, prep_res, exec_res):
        """Store generated workflow and route to validation."""
        logger.debug(f"Generated {len(exec_res['workflow'].get('nodes', []))} nodes")
        shared["generated_workflow"] = exec_res["workflow"]
        shared["generation_attempts"] = exec_res["attempt"]
        return "validate"  # CRITICAL: Always route to validation

    def exec_fallback(self, prep_res, exc):
        """Handle generation failure."""
        logger.error(f"GeneratorNode failed: {exc}")
        return {
            "success": False,
            "error": str(exc),
            "workflow": None  # No fallback workflow
        }
```

### Retry with validation errors
```python
# Input
validation_errors = ["Unknown node type 'read-files'", "Template variable $data not in inputs"]
generation_attempts = 1

# Prompt addition
"The previous attempt failed validation. Fix ONLY these specific issues:
- Unknown node type 'read-files'
- Template variable $data not in inputs
Keep the rest of the workflow unchanged."
```

## Test Criteria

1. Class named WorkflowGeneratorNode → inherits from Node
2. Registry name set → name = "generator" as class attribute
3. Max retries configured → super().__init__() called with parameters
4. Empty planning_context → ValueError raised with specific message
5. Dict planning_context with error key → ValueError raised with error details
6. Valid planning_context → workflow generated with inputs field
7. Prompt emphasizes template variables → contains "use template variables ($var)"
8. Prompt forbids hardcoding → contains "NEVER hardcode values"
9. Prompt specifies linear → contains "LINEAR workflow only"
10. discovered_params present → parameters renamed for clarity in inputs
11. discovered_params None → workflow generated without parameter hints
12. validation_errors present → prompt includes error fixing instructions
13. validation_errors > 3 → only first 3 included in prompt
14. LLM returns None → ValueError raised
15. Response parsed from nested structure → response_data['content'][0]['input'] accessed
16. LLM response missing content → ValueError raised
17. Generated workflow has linear edges only → no action field in edges
18. Template variables use $ prefix → all params with variables start with $
19. Template paths supported → $var.field.subfield in params
20. Template variables match inputs keys → each $var has corresponding inputs key
21. Required parameters have no default → required=True implies no default field
22. Optional parameters have universal defaults → default values not request-specific
23. Node IDs are descriptive → IDs like "fetch_data" not "n1"
24. Single node type per workflow → no duplicate types to avoid collision
25. Workflow node uses workflow_name → workflow nodes have workflow_name param
26. Workflow node has param_mapping → workflow nodes include mapping fields
27. exec_fallback returns error dict → success=False, error string, workflow=None
28. Model loaded lazily in exec → llm.get_model called inside exec not __init__
29. Logging present → logger.debug calls for workflow generation
30. FlowIR imported → from pflow.planning.ir_models import FlowIR

## Notes (Why)

- Planning context required ensures generator has component information
- Parameter renaming improves workflow clarity and maintainability
- Linear workflows simplify MVP implementation without Task 9 proxy mapping
- Universal defaults enable workflow reuse across different contexts
- Lazy model loading conserves resources in PocketFlow pattern
- Template variables enable Plan Once Run Forever philosophy
- Independent inputs specification enables verification by ParameterMappingNode

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 2                          |
| 3      | 3                          |
| 4      | 4                          |
| 5      | 5                          |
| 6      | 28                         |
| 7      | 7                          |
| 8      | 8                          |
| 9      | 9                          |
| 10     | 6                          |
| 11     | 12                         |
| 12     | 12, 13                     |
| 13     | 6                          |
| 14     | 6                          |
| 15     | 15                         |
| 16     | 14                         |
| 17     | 16                         |
| 18     | 6                          |
| 19     | 6                          |
| 20     | 6                          |
| 21     | 29                         |
| 22     | 29                         |
| 23     | 18                         |
| 24     | 19                         |
| 25     | 20                         |
| 26     | 10                         |
| 27     | 10                         |
| 28     | 21                         |
| 29     | 22                         |
| 30     | 17                         |
| 31     | 23                         |
| 32     | 24                         |
| 33     | 25                         |
| 34     | 26                         |
| 35     | 26                         |
| 36     | 6, 27                      |

## Versioning & Evolution

- v1.0.0 - Initial GeneratorNode specification for Task 17 Subtask 4

## Epistemic Appendix

### Assumptions & Unknowns

- Verified: FlowIR exists in pflow.planning.ir_models with inputs field
- Verified: _parse_structured_response() pattern exists in all nodes
- Verified: Logger configured at module level in planning/__init__.py
- Verified: Anthropic response structure at content[0]['input']
- Assumes: LLM can generate valid JSON matching FlowIR schema
- Unknown: Exact format of validation_errors from ValidatorNode (likely strings)
- Unknown: Performance characteristics of complex prompt generation
- Unknown: Whether llm library handles all error cases gracefully

### Conflicts & Resolutions

- Documentation suggests complex workflows but MVP requires linear only - Resolution: Linear workflows per clarification document
- Discovered params as hints vs requirements - Resolution: Use as hints with freedom to rename per clarification

### Decision Log / Tradeoffs

- Rename parameters for clarity vs preserve discovered names - Chose: Rename for better workflow maintainability
- Generate fallback workflow vs return error - Chose: Return error for explicit failure handling
- Validate nodes exist vs trust planning context - Chose: Trust planning context to avoid coupling

### Ripple Effects / Impact Map

- Affects ValidatorNode which validates generated workflows
- Affects ParameterMappingNode which extracts from inputs field
- Affects CLI which handles generation failures
- Requires FlowIR model in ir_models.py
- Depends on planning_context from ComponentBrowsingNode

### Residual Risks & Confidence

- Risk: LLM may generate non-linear workflows despite prompt - Mitigation: ValidatorNode catches and retries
- Risk: Template variable naming conflicts - Mitigation: ParameterMappingNode validates independently
- Risk: Planning context format changes - Mitigation: String check only, no parsing
- Confidence: High for linear generation, Medium for parameter mapping

### Epistemic Audit (Checklist Answers)

1. Assumed LLM reliably generates FlowIR JSON - Could fail with API changes
2. Wrong assumption breaks workflow generation entirely - Need exec_fallback
3. Robustness over elegance - Error explicit over fallback workflows
4. All rules mapped to tests - See compliance matrix
5. Touches workflow generation and parameter flow - Critical path component
6. Uncertainty on validation error format - Medium confidence on retry logic
