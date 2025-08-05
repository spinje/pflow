# Feature: task_17_subtask_3_generation

## Objective

Create generator, validator, and metadata nodes for workflow generation.

## Requirements

- Must implement WorkflowGeneratorNode with LLM-based workflow generation
- Must implement ValidatorNode with two-phase validation (structure and template)
- Must implement MetadataGenerationNode for workflow metadata extraction
- Must use Pydantic models for structured LLM output
- Must implement retry loop between generator and validator
- Must handle both ValidationError and template error list formats
- Must use progressive prompt enhancement on retries
- Must log all generation attempts and validation results

## Scope

- Does not implement discovery nodes (subtask 2)
- Does not implement parameter extraction nodes (subtask 4/5)
- Does not wire nodes into complete flow (subtask 6)
- Does not integrate with CLI
- Does not implement ParameterDiscoveryNode

## Inputs

- shared: dict - PocketFlow shared store containing:
  - user_input: str - Natural language request from user
  - planning_context: str - Markdown context from ComponentBrowsingNode
  - discovered_params: dict - Parameters extracted from natural language (empty initially)
  - generation_attempts: int - Counter for retry tracking
  - validation_errors: list[str] - Previous validation errors for retry context
  - validation_error: dict - Structure validation error (path, message, suggestion)

## Outputs

Returns: Action string for PocketFlow routing

Side effects:
- WorkflowGeneratorNode writes to shared:
  - generated_workflow: dict - Complete JSON IR workflow
  - generation_attempts: int - Updated attempt counter
- ValidatorNode writes to shared:
  - validation_errors: list[str] - Template validation errors for retry
  - validation_error: dict - Structure validation error details
- MetadataGenerationNode writes to shared:
  - workflow_metadata: dict - Extracted metadata (name, description, inputs, outputs)

## Structured Formats

```python
# Pydantic models imported from ir_models.py (created in subtask 1)
from pflow.planning.ir_models import NodeIR, EdgeIR, FlowIR

# MetadataGenerationNode output structure
from pydantic import BaseModel
from typing import List

class WorkflowMetadata(BaseModel):
    suggested_name: str  # kebab-case identifier
    description: str  # Natural language description
    inputs: List[str]  # Parameter names required
    outputs: List[str]  # Variables produced
```

## State/Flow Changes

```
WorkflowGeneratorNode:
  shared["planning_context"] + retries → LLM generation → "validate"

ValidatorNode:
  shared["generated_workflow"] → validation → "valid" | "invalid" | "failed"

MetadataGenerationNode:
  shared["generated_workflow"] → metadata extraction → "continue"
```

## Constraints

- LLM model must be "anthropic/claude-sonnet-4-0"
- Maximum 3 generation attempts before failure
- Node IDs must follow PocketFlow naming conventions
- Template variables must use $ prefix

## Rules

1. WorkflowGeneratorNode must use llm.get_model("anthropic/claude-sonnet-4-0")
2. WorkflowGeneratorNode must set max_retries=3 in __init__
3. WorkflowGeneratorNode must increment generation_attempts in exec
4. WorkflowGeneratorNode must use FlowIR schema parameter for structured output
5. WorkflowGeneratorNode must parse response with json.loads(response.text())
6. WorkflowGeneratorNode must return dict with "workflow" key from exec
7. WorkflowGeneratorNode must always return "validate" from post
8. WorkflowGeneratorNode must add validation_errors to prompt on retry attempts
9. WorkflowGeneratorNode must use temperature=0 for deterministic output
10. ValidatorNode must call validate_ir() first
11. ValidatorNode must catch ValidationError and access .path, .message, .suggestion attributes
12. ValidatorNode must call TemplateValidator.validate_workflow_templates() second
13. ValidatorNode must instantiate Registry() in __init__
14. ValidatorNode must return "invalid" when validation fails and attempts < 3
15. ValidatorNode must return "failed" when validation fails and attempts >= 3
16. ValidatorNode must return "valid" when all validation passes
17. ValidatorNode must store template errors in validation_errors (list)
18. ValidatorNode must store structure error in validation_error (dict)
19. MetadataGenerationNode must extract suggested_name in kebab-case
20. MetadataGenerationNode must extract inputs as parameter names list
21. MetadataGenerationNode must return "continue" from post
22. All nodes must use logger = logging.getLogger(__name__)
23. All nodes must log entry and exit with data summaries
24. discovered_params must default to empty dict when missing
25. WorkflowGeneratorNode exec_fallback must return dict with empty workflow

## Edge Cases

Empty planning_context → Generator uses minimal prompt
Invalid JSON from LLM → Pydantic validation error caught in exec
Template variable missing $ → Template validation fails
Max retries exceeded → Validator returns "failed"
Empty discovered_params → Template validation uses empty dict
Registry load failure → ValidatorNode continues with warning
validate_ir raises non-ValidationError → Validator logs and returns "failed"
generation_attempts missing → Defaults to 0
Malformed workflow structure → validate_ir catches and returns error
No nodes in generated workflow → validate_ir fails with specific error

## Error Handling

- LLM API errors → WorkflowGeneratorNode exec_fallback returns empty workflow dict
- Pydantic validation errors → Caught in exec, logged, returns empty workflow
- ValidationError → Extract fields and store in validation_error dict
- Template validation errors → Store list in validation_errors
- Missing shared keys → Use defaults with warning logs

## Non-Functional Criteria

- Generation completes within 5 seconds P95
- Validation completes within 100ms P95
- Retry attempts logged with full context
- Memory usage under 100MB per workflow

## Examples

```python
# Required imports
import json
import logging
from pocketflow import Node
import llm
from pflow.core.ir_schema import validate_ir, ValidationError
from pflow.registry import Registry
from pflow.runtime.template_validator import TemplateValidator
from pflow.planning.ir_models import NodeIR, EdgeIR, FlowIR

logger = logging.getLogger(__name__)
# Note: Module-level logging config is in planning/__init__.py (from subtask 1)

# WorkflowGeneratorNode implementation excerpt
class WorkflowGeneratorNode(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=1.0)
        self.model = llm.get_model("anthropic/claude-sonnet-4-0")

    def prep(self, shared):
        return {
            "user_input": shared.get("user_input", ""),
            "planning_context": shared.get("planning_context", ""),
            "generation_attempts": shared.get("generation_attempts", 0),
            "validation_errors": shared.get("validation_errors", [])
        }

    def exec(self, prep_res):
        attempt = prep_res["generation_attempts"]
        prompt = self._build_prompt(prep_res, attempt)

        try:
            response = self.model.prompt(
                prompt,
                schema=FlowIR,
                temperature=0
            )
            workflow_dict = json.loads(response.text())
            return {
                "workflow": workflow_dict,
                "attempt": attempt + 1
            }
        except Exception as e:
            logger.error(f"Generation error: {e}")
            return {
                "workflow": {"ir_version": "0.1.0", "nodes": [], "edges": []},
                "attempt": attempt + 1
            }

    def post(self, shared, prep_res, exec_res):
        shared["generated_workflow"] = exec_res["workflow"]
        shared["generation_attempts"] = exec_res["attempt"]
        logger.debug(f"Generated workflow with {len(exec_res['workflow'].get('nodes', []))} nodes")
        return "validate"

# ValidatorNode excerpt showing two-phase validation
class ValidatorNode(Node):
    def __init__(self):
        super().__init__()
        self.registry = Registry()

    def prep(self, shared):
        """Extract data needed for validation from shared store."""
        return {
            "workflow": shared.get("generated_workflow", {}),
            "discovered_params": shared.get("discovered_params", {}),
            "generation_attempts": shared.get("generation_attempts", 0)
        }

    def exec(self, prep_res):
        workflow = prep_res["workflow"]
        params = prep_res["discovered_params"]

        # Phase 1: Structure validation
        try:
            validate_ir(workflow)
        except ValidationError as e:
            return {
                "is_valid": False,
                "structure_error": {  # Internal exec() return key
                    "path": e.path,
                    "message": e.message,
                    "suggestion": e.suggestion
                }
            }

        # Phase 2: Template validation
        errors = TemplateValidator.validate_workflow_templates(
            workflow, params, self.registry
        )

        if errors:
            return {
                "is_valid": False,
                "template_errors": errors  # Internal exec() return key
            }

        return {"is_valid": True}

    def post(self, shared, prep_res, exec_res):
        """Store validation results and route based on retry count."""
        if not exec_res["is_valid"]:
            attempts = prep_res["generation_attempts"]

            # Store errors in shared store with consistent key names
            if "template_errors" in exec_res:
                shared["validation_errors"] = exec_res["template_errors"]
            elif "structure_error" in exec_res:
                shared["validation_error"] = exec_res["structure_error"]

            # Route based on retry attempts
            if attempts < 3:
                return "invalid"  # Retry generation
            else:
                return "failed"   # Max retries exceeded

        return "valid"
```

## Test Criteria

1. WorkflowGeneratorNode with claude-sonnet-4-0 → model initialized correctly
2. WorkflowGeneratorNode init → max_retries=3 set
3. WorkflowGeneratorNode exec with attempts=0 → returns attempt=1
4. WorkflowGeneratorNode prompt call → uses schema=FlowIR
5. WorkflowGeneratorNode response → parsed with json.loads(response.text())
6. WorkflowGeneratorNode exec → returns dict with "workflow" key
7. WorkflowGeneratorNode post → always returns "validate"
8. WorkflowGeneratorNode with validation_errors → includes in prompt
9. WorkflowGeneratorNode prompt → temperature=0 used
10. ValidatorNode exec → calls validate_ir() before template validation
11. ValidatorNode with ValidationError → accesses .path, .message, .suggestion attributes
12. ValidatorNode exec → calls TemplateValidator.validate_workflow_templates()
13. ValidatorNode init → Registry() instantiated
14. ValidatorNode with errors and attempts=2 → returns "invalid"
15. ValidatorNode with errors and attempts=3 → returns "failed"
16. ValidatorNode with no errors → returns "valid"
17. ValidatorNode with template errors → stores in validation_errors
18. ValidatorNode with structure error → stores in validation_error
19. MetadataGenerationNode → extracts kebab-case suggested_name
20. MetadataGenerationNode → extracts inputs list
21. MetadataGenerationNode post → returns "continue"
22. All nodes → logger configured with __name__
23. All nodes → log entry/exit with summaries
24. Missing discovered_params → defaults to {}
25. WorkflowGeneratorNode exec_fallback → returns workflow dict
26. Empty planning_context → generator continues with minimal prompt
27. Invalid JSON from LLM → caught and empty workflow returned
28. Template without $ → validation fails with specific error
29. generation_attempts=3 and error → "failed" returned
30. Empty discovered_params → template validation proceeds
31. Registry load failure → validator logs warning and continues
32. Non-ValidationError in validate_ir → caught and "failed" returned
33. Missing generation_attempts → defaults to 0
34. Workflow with no nodes → validate_ir fails
35. Empty nodes list → validation error with path "nodes"

## Notes (Why)

- Progressive retry enhancement improves generation success rate
- Two-phase validation separates structural from semantic errors
- Bounded retries prevent infinite loops
- Structured output via Pydantic ensures type safety
- Template validation with Registry enables accurate variable checking
- Metadata extraction enables workflow discovery and reuse

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
| 11     | 11                         |
| 12     | 12                         |
| 13     | 13                         |
| 14     | 14                         |
| 15     | 15                         |
| 16     | 16                         |
| 17     | 17                         |
| 18     | 18                         |
| 19     | 19                         |
| 20     | 20                         |
| 21     | 21                         |
| 22     | 22                         |
| 23     | 23                         |
| 24     | 24                         |
| 25     | 25                         |

## Versioning & Evolution

- v1.0.0 — Initial specification for Task 17 Subtask 3

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes discovered_params will be empty dict initially (ParameterDiscoveryNode implemented in subtask 4/5)
- Assumes Registry contains populated node metadata from Task 19
- Verified: validate_ir imported from pflow.core.ir_schema
- Verified: TemplateValidator imported from pflow.runtime.template_validator
- Verified: ValidationError has .path, .message, .suggestion attributes
- Assumes llm library configured with anthropic plugin and API key
- Unknown: Optimal prompt structure for workflow generation

### Conflicts & Resolutions

- Documentation suggests complex metadata extraction vs simple passthrough — Resolution: Start with simple extraction of basic fields per walking skeleton principle
- Error format differences between ValidationError and template errors — Resolution: Handle separately with different shared store keys

### Decision Log / Tradeoffs

- Chose max_retries=3 as balance between success rate and bounded execution time
- Chose to handle discovered_params as empty dict initially over waiting for parameter nodes
- Chose separate error storage (validation_error vs validation_errors) for clarity
- Chose temperature=0 for deterministic LLM output over creative variation
- Chose simple metadata extraction over LLM-based analysis for initial implementation (walking skeleton principle)
- ValidatorNode uses internal exec() return keys that map to standardized shared store keys in post()

### Ripple Effects / Impact Map

- All downstream subtasks depend on generated_workflow format
- Parameter mapping nodes (subtask 5) will consume workflow_metadata
- Flow orchestration (subtask 6) depends on action strings
- Integration tests (subtask 7) require all three nodes functioning

### Residual Risks & Confidence

- Risk: LLM prompt effectiveness unknown until tested (mitigation: progressive enhancement)
- Risk: Template validation accuracy depends on Registry completeness (mitigation: graceful degradation)
- Risk: Metadata extraction may need enhancement for complex workflows
- Confidence: Very High for structure and flow (based on existing patterns)
- Confidence: High for implementation approach (follows PocketFlow conventions)
- Confidence: Medium for LLM prompt effectiveness (requires iteration)

### Epistemic Audit (Checklist Answers)

1. Assumed empty discovered_params initially; assumed ValidationError structure
2. Wrong assumptions would cause KeyError or AttributeError at runtime
3. Prioritized robustness (error handling, defaults) over elegant abstraction
4. All rules mapped to test criteria; all edge cases covered
5. Affects all downstream workflow processing; critical path component
6. LLM prompt optimization remains uncertain; Confidence: High for structure, Medium for prompts
