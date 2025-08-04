# Feature: task_17_subtask_1_foundation

## Objective

Create foundation infrastructure for natural language planner.

## Requirements

- Must extend existing `src/pflow/planning/` directory structure
- Must follow PocketFlow file organization conventions
- Must design comprehensive shared store schema
- Must implement utilities for external I/O only
- Must extend test infrastructure with fixtures

## Scope

- Does not implement any planner nodes
- Does not include LLM client setup in utilities
- Does not implement flow orchestration
- Does not integrate with CLI

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
    "src/pflow/planning/": {
        "__init__.py": "# Natural Language Planner",
        "utils/": {
            "__init__.py": "# Utility functions for external I/O",
            "workflow_loader.py": "Load workflows from disk",
            "registry_helper.py": "Registry access utilities",
            "context_wrapper.py": "Context builder wrapper"
        },
        "prompts/": {
            "__init__.py": "# Prompt templates",
            "templates.py": "String templates for LLM prompts"
        }
    },
    "tests/test_planning/": {
        "conftest.py": "Test fixtures",
        "__init__.py": "# Test suite"
    }
}

# Shared store schema
shared_store_schema = {
    # Input stage
    "user_input": "str",
    "stdin_data": "Any | None",
    "current_date": "str",
    
    # Discovery stage
    "discovery_context": "str",
    "discovery_result": "dict",
    "browsed_components": "dict",
    
    # Generation stage
    "discovered_params": "dict",
    "planning_context": "str",
    "generation_attempts": "int",
    "validation_errors": "list[dict]",
    
    # Workflow stage
    "generated_workflow": "dict | None",
    "found_workflow": "dict | None",
    "workflow_metadata": "dict",
    
    # Parameter stage
    "extracted_params": "dict",
    "verified_params": "dict",
    "execution_params": "dict",
    
    # Output stage
    "planner_output": "dict"
}
```

## State/Flow Changes

- None

## Constraints

- Directory names must follow Python package conventions
- Utilities must not contain business logic
- All utilities must be pure functions
- Test fixtures must be reusable across subtasks

## Rules

1. Create subdirectory `prompts/` in existing `src/pflow/planning/` directory
2. Create `__init__.py` files in new directories to make them Python packages
3. Implement `workflow_loader.py` with function `load_workflow(name: str) -> dict | None`
4. Implement `registry_helper.py` with function `get_all_nodes_metadata() -> dict[str, dict]`
5. Implement `context_wrapper.py` with wrapper functions for existing context builder
6. Create `templates.py` with empty string constants for prompt templates
7. Create `tests/test_planning/conftest.py` with pytest fixtures
8. Document shared store schema in `src/pflow/planning/shared_store_schema.md`
9. All utility functions must have type hints
10. All utility functions must have docstrings
11. Test fixtures must include mock registry and mock workflow manager
12. No utility function may import `llm` library

## Edge Cases

Empty workflow name → `load_workflow()` raises ValueError
Non-existent workflow → `load_workflow()` raises WorkflowNotFoundError
Registry load fails → `get_all_nodes_metadata()` returns empty dict
Context builder not available → wrapper functions raise ImportError

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

def load_workflow(name: str) -> dict | None:
    """Load workflow metadata from disk by name.
    
    Args:
        name: Workflow name
        
    Returns:
        Full workflow metadata dict including ir, or None
        
    Raises:
        ValueError: If name is empty
        WorkflowNotFoundError: If workflow doesn't exist
    """
    if not name:
        raise ValueError("Workflow name cannot be empty")
    
    manager = WorkflowManager()
    try:
        return manager.load(name)
    except WorkflowNotFoundError:
        raise

# registry_helper.py
from pflow.registry import Registry

def get_all_nodes_metadata() -> dict[str, dict]:
    """Get metadata for all registered nodes.
    
    Returns:
        Dict mapping node names to metadata
    """
    registry = Registry()
    return registry.load()

# context_wrapper.py  
from pflow.planning.context_builder import (
    build_discovery_context,
    build_planning_context
)

def get_discovery_context(node_ids: list[str] | None = None,
                         workflow_names: list[str] | None = None) -> str:
    """Wrapper for discovery context generation."""
    registry = Registry()
    return build_discovery_context(
        node_ids=node_ids,
        workflow_names=workflow_names,
        registry_metadata=registry.load()
    )
```

## Test Criteria

1. Directory `src/pflow/planning/prompts/` exists after execution
2. File `src/pflow/planning/utils/workflow_loader.py` exists
3. File `src/pflow/planning/utils/registry_helper.py` exists
4. File `src/pflow/planning/utils/context_wrapper.py` exists
5. File `src/pflow/planning/prompts/templates.py` exists
6. File `tests/test_planning/conftest.py` exists
7. `load_workflow("")` raises ValueError
8. `load_workflow("nonexistent")` raises WorkflowNotFoundError
9. `get_all_nodes_metadata()` returns dict
10. `get_discovery_context()` returns string
11. All utility functions have type hints
12. No utility imports `llm` library
13. Mock registry fixture is importable
14. Mock workflow manager fixture is importable
15. Shared store schema document exists at `src/pflow/planning/shared_store_schema.md`

## Notes (Why)

- Separating utilities from nodes ensures clear architectural boundaries
- Following PocketFlow conventions maintains consistency with framework patterns
- Designing shared store upfront prevents data flow issues later
- Test fixtures enable parallel development of other subtasks

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 1, 5                       |
| 3      | 2, 7, 8                    |
| 4      | 3, 9                       |
| 5      | 4, 10                      |
| 6      | 5                          |
| 7      | 6, 13, 14                  |
| 8      | 15                         |
| 9      | 11                         |
| 10     | 11                         |
| 11     | 13, 14                     |
| 12     | 12                         |

## Versioning & Evolution

- v1.0.0 — Initial foundation specification for Task 17 Subtask 1

## Epistemic Appendix

### Assumptions & Unknowns

- Verified: WorkflowManager at `pflow.core.workflow_manager`
- Verified: Registry at `pflow.registry.registry` 
- Verified: Context builder exists at `pflow.planning.context_builder`
- Verified: Planning directory already exists with context_builder.py
- Unknown whether additional utilities will be needed for later subtasks

### Conflicts & Resolutions

- PocketFlow guide suggests LLM calls in nodes vs potential utility — Resolution: LLM calls strictly in nodes per PocketFlow pattern

### Decision Log / Tradeoffs

- Chose minimal utility set over comprehensive helpers to avoid premature abstraction
- Chose Mock objects over full test implementations for speed
- Chose separate schema document over inline comments for visibility

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