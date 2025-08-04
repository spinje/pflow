# Feature: task_17_subtask_1_foundation

## Objective

Create foundation infrastructure for natural language planner by extending the existing `src/pflow/planning/` directory with utilities, models, and test fixtures.

## Requirements

- Must extend existing `src/pflow/planning/` directory structure (already contains context_builder.py)
- Must follow PocketFlow file organization conventions
- Must document comprehensive shared store schema in code
- Must implement utilities for external I/O only (NO business logic or LLM calls)
- Must set up LLM library with anthropic/claude-sonnet-4-0 model
- Must ensure Pydantic is installed for structured LLM output (currently commented out in pyproject.toml)
- Must configure module-level logging for visibility
- Must create Pydantic models for structured LLM output
- Must extend test infrastructure with fixtures

## Scope

- Does not implement any planner nodes (nodes.py comes in subtask 2)
- Does not implement flow orchestration (flow.py comes in subtask 6)
- Does not integrate with CLI
- LLM calls belong in nodes, NOT in utilities (utilities are I/O only)

## Inputs

- None

## Outputs

Returns: Created filesystem structure with utilities and test fixtures

Side effects:
- Directory structure created at `src/pflow/planning/`
- Utility modules created in `src/pflow/planning/utils/`
- Test fixtures created in `tests/test_planning/conftest.py`
- Shared store schema documented

## Structured Formats

```python
# Directory structure to create
structure = {
    "src/pflow/planning/": {  # Directory already exists with context_builder.py
        "__init__.py": """Natural Language Planner.

        This module implements a meta-workflow that transforms natural language
        into executable pflow workflows. It follows PocketFlow patterns where
        the shared store is initialized by the caller (CLI) at runtime.

        Expected shared store keys (initialized by CLI):
        - user_input: Natural language request from user
        - stdin_data: Optional data from stdin pipe
        - current_date: ISO timestamp for context

        Keys written during execution:
        - discovery_context, discovery_result, browsed_components
        - discovered_params, planning_context, generation_attempts
        - validation_errors, generated_workflow, found_workflow
        - workflow_metadata, extracted_params, verified_params
        - execution_params, planner_output

        See individual node docstrings for detailed key usage.
        """,
        "ir_models.py": "Pydantic models for structured LLM output",
        "utils/": {
            "__init__.py": "# Utility functions for external I/O only",
            "workflow_loader.py": "Thin wrapper for WorkflowManager",
            "registry_helper.py": "Registry data extraction utilities"
        },
        "prompts/": {
            "__init__.py": "# Prompt templates as data",
            "templates.py": "String constants for LLM prompts"
        }
    },
    "tests/test_planning/": {
        "conftest.py": "Test fixtures",
        "__init__.py": "# Test suite"
    }
}

# Dependencies and LLM setup verification
dependency_setup = [
    "uv pip install pydantic",  # Required for structured LLM output
    "uv pip install llm-anthropic",  # Anthropic plugin for LLM
]

llm_config_commands = [
    "llm keys set anthropic",  # User must provide API key
    "llm models | grep claude"  # Should show anthropic/claude-sonnet-4-0
]
```

## State/Flow Changes

- None

## Constraints

- Directory names must follow Python package conventions
- Utilities must not contain business logic
- All utilities must be pure functions
- Test fixtures must be reusable across subtasks

## Rules

1. Extend existing `src/pflow/planning/` directory (already has context_builder.py)
2. Install Pydantic if not present: `uv pip install pydantic` (required for structured LLM output)
3. Create `__init__.py` files in new directories with proper module-level logging config
4. Create `ir_models.py` with Pydantic models (NodeIR, EdgeIR, FlowIR) for structured output
5. Implement `workflow_loader.py` as thin wrapper delegating to WorkflowManager
6. Implement `registry_helper.py` with data extraction functions (get_node_interface, get_node_outputs, get_node_inputs)
7. Create `templates.py` with string constants for prompt templates (data not code - use Python f-strings in nodes for substitution)
8. Create `tests/test_planning/conftest.py` with pytest fixtures for mocked LLM
9. Document expected shared store keys in `__init__.py` docstring (following PocketFlow pattern)
10. All utility functions must have type hints and docstrings
11. No utility function may import `llm` library (LLM is core functionality, belongs in nodes)
12. Test fixtures must support both mocked and real LLM testing modes
13. Verify LLM library setup with anthropic plugin installed and configured
14. Configure logging at module level in main `src/pflow/planning/__init__.py`: `logging.basicConfig(level=logging.DEBUG)`
15. All utilities must be pure I/O functions without business logic

## Edge Cases

Empty workflow name → `load_workflow()` raises ValueError
Non-existent workflow → `load_workflow()` raises WorkflowNotFoundError
Registry load fails → registry helper functions return empty dict/list
LLM not configured → Test fixture detects and provides helpful error message

## Error Handling

- None

## Non-Functional Criteria

- Utility functions complete in < 10ms
- Test fixtures initialize in < 100ms
- All code follows PEP 8 style guide

## Examples

```python
# workflow_loader.py
from pflow.core.workflow_manager import WorkflowManager
from pflow.core.exceptions import WorkflowNotFoundError

def load_workflow(name: str) -> dict:
    """Load workflow metadata from disk by name.

    Thin wrapper around WorkflowManager - delegates all functionality.

    Args:
        name: Workflow name (kebab-case)

    Returns:
        Full workflow metadata dict including ir

    Raises:
        ValueError: If name is empty
        WorkflowNotFoundError: If workflow doesn't exist
    """
    if not name:
        raise ValueError("Workflow name cannot be empty")

    manager = WorkflowManager()
    return manager.load(name)  # Raises WorkflowNotFoundError if not found

def list_all_workflows() -> list[dict]:
    """List all available workflows.

    Returns:
        List of workflow metadata dicts
    """
    manager = WorkflowManager()
    return manager.list_all()

# registry_helper.py
from typing import Any
from pflow.registry import Registry

def get_node_interface(node_type: str, registry_data: dict[str, Any]) -> dict:
    """Get the interface data for a specific node type.

    Pure data extraction - no logic.
    """
    if node_type in registry_data:
        return registry_data[node_type].get("interface", {})
    return {}

def get_node_outputs(node_type: str, registry_data: dict[str, Any]) -> list[dict]:
    """Get list of outputs a node writes to shared store.

    Pure data extraction - no validation.
    """
    interface = get_node_interface(node_type, registry_data)
    return interface.get("outputs", [])

def get_node_inputs(node_type: str, registry_data: dict[str, Any]) -> list[dict]:
    """Get list of inputs a node reads from shared store.

    Pure data extraction - no validation.
    """
    interface = get_node_interface(node_type, registry_data)
    return interface.get("inputs", [])

# ir_models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class NodeIR(BaseModel):
    """Node representation for IR generation."""
    id: str = Field(..., pattern="^[a-zA-Z0-9_-]+$")
    type: str = Field(..., description="Node type from registry")
    params: Dict[str, Any] = Field(default_factory=dict)

class EdgeIR(BaseModel):
    """Edge representation for IR generation."""
    from_node: str = Field(..., alias="from")
    to_node: str = Field(..., alias="to")
    action: str = Field(default="default")

class FlowIR(BaseModel):
    """Flow IR for planner output generation."""
    ir_version: str = Field(default="0.1.0", pattern=r'^\d+\.\d+\.\d+$')
    nodes: List[NodeIR] = Field(..., min_items=1)
    edges: List[EdgeIR] = Field(default_factory=list)
    start_node: Optional[str] = None
    # Task 21 fields: workflows can declare their expected inputs/outputs
    inputs: Optional[Dict[str, Any]] = None
    outputs: Optional[Dict[str, Any]] = None
```

## Test Criteria

1. Directory `src/pflow/planning/prompts/` exists after execution
2. File `src/pflow/planning/utils/workflow_loader.py` exists and delegates to WorkflowManager
3. File `src/pflow/planning/utils/registry_helper.py` exists with data extraction functions
4. File `src/pflow/planning/ir_models.py` exists with Pydantic models
5. File `src/pflow/planning/prompts/templates.py` exists with string constants
6. File `tests/test_planning/conftest.py` exists with LLM mock fixtures
7. `load_workflow("")` raises ValueError
8. `load_workflow("nonexistent")` raises WorkflowNotFoundError
9. Registry helper functions return appropriate types (dict/list)
10. Expected shared store keys documented in `__init__.py` docstring
11. All utility functions have type hints and docstrings
12. No utility imports `llm` library (belongs in nodes)
13. Mock LLM fixtures support both mocked and real modes
14. LLM library configured with anthropic plugin (`llm models` shows claude)
15. Pydantic installed for structured output (`import pydantic` works)
16. Logging configured at module level in main `__init__.py`
17. Pydantic models validate template variable syntax ($var)

## Notes (Why)

- Separating utilities from nodes ensures clear architectural boundaries
- Following PocketFlow conventions maintains consistency with framework patterns
- Designing shared store upfront prevents data flow issues later
- Test fixtures enable parallel development of other subtasks

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 15                         |
| 3      | 1, 5, 16                   |
| 4      | 4, 17                      |
| 5      | 2, 7, 8                    |
| 6      | 3, 9                       |
| 7      | 5                          |
| 8      | 6, 13                      |
| 9      | 10                         |
| 10     | 11                         |
| 11     | 12                         |
| 12     | 13                         |
| 13     | 14                         |
| 14     | 16                         |
| 15     | 2, 3, 9                    |

## Versioning & Evolution

- v1.0.0 — Initial foundation specification for Task 17 Subtask 1

## Epistemic Appendix

### Assumptions & Unknowns

- Verified: WorkflowManager at `pflow.core.workflow_manager` with atomic save operations
- Verified: Registry at `pflow.registry.Registry` with load() method
- Verified: Context builder exists at `src/pflow/planning/context_builder.py` (Tasks 15/16)
- Verified: Planning directory already exists with context_builder.py
- Verified: WorkflowNotFoundError exists in `pflow.core.exceptions`
- Verified: LLM library requires anthropic plugin for claude-sonnet-4-0
- Verified: LLM library supports Pydantic models via schema parameter (per llm.datasette.io docs)
- Note: Pydantic is commented out in pyproject.toml but required for Task 17
- Note: No thin wrappers - import context_builder directly in nodes

### Conflicts & Resolutions

- PocketFlow guide emphasizes LLM calls are core functionality — Resolution: LLM calls strictly in nodes, never in utilities
- Thin wrapper anti-pattern vs helper functions — Resolution: Direct imports in nodes, utilities only for pure I/O

### Decision Log / Tradeoffs

- Chose minimal utility set over comprehensive helpers to avoid premature abstraction
- Chose hybrid testing approach: mocked LLM by default, real LLM optional (costs money)
- Chose docstring for schema over separate file (keeps everything in code)
- Chose Pydantic models for structured LLM output (llm library's schema parameter supports Pydantic per official docs)
- Requires uncommenting Pydantic in pyproject.toml or manual installation
- Chose to remove context_wrapper.py entirely (violates no thin wrapper principle)

### Ripple Effects / Impact Map

- All subsequent subtasks depend on this directory structure
- Shared store schema affects every node implementation
- Test fixtures will be used by all subtask tests

### Residual Risks & Confidence

- Risk: Shared store schema may need revision as nodes are implemented
- Risk: Additional utilities may be discovered during implementation
- Confidence: High - all technical details verified

### Epistemic Audit (Checklist Answers)

1. All import paths and class methods verified through codebase investigation
2. Wrong assumptions eliminated through verification - all details confirmed
3. Prioritized simplicity over comprehensive utility coverage
4. All rules map to test criteria
5. Creates foundation that all other subtasks depend on
6. Uncertainty remains only on additional utility needs; Confidence: High
