# Task 17 - Subtask 1 Implementation Plan

## Dependencies Verified

### External Dependencies
- WorkflowManager API needs verification at: `pflow.core.workflow_manager`
- Registry structure needs verification at: `pflow.registry`
- Context builder exists at: `src/pflow/planning/context_builder.py`
- LLM library needs installation: `llm-anthropic`
- Pydantic needs installation

### For Next Subtasks
- Utilities will be imported as: `from pflow.planning.utils.workflow_loader import ...`
- Test fixtures available for: mocked LLM responses, test workflows, registry data
- Pydantic models imported as: `from pflow.planning.ir_models import FlowIR`

## Shared Store Contract
Document keys in __init__.py:
- user_input: Natural language request from user
- stdin_data: Optional data from stdin pipe
- current_date: ISO timestamp for context
- discovery_context, discovery_result, browsed_components
- discovered_params, planning_context, generation_attempts
- validation_errors, generated_workflow, found_workflow
- workflow_metadata, extracted_params, verified_params
- execution_params, planner_output

## Implementation Steps

### Phase 1: Setup and Configuration
1. Install Pydantic: `uv pip install pydantic`
2. Install LLM anthropic plugin: `uv pip install llm-anthropic`
3. Configure LLM keys (requires API key)
4. Verify installation with `llm models | grep claude`

### Phase 2: Directory Structure
1. Verify utils/ directory exists in `src/pflow/planning/`
2. Verify prompts/ directory exists in `src/pflow/planning/`
3. Create all necessary `__init__.py` files
4. Configure module-level logging in main `__init__.py`
5. Document comprehensive shared store schema

### Phase 3: Implementation
1. Verify WorkflowManager API and implement workflow_loader.py
2. Verify Registry API and implement registry_helper.py
3. Create ir_models.py with Pydantic models (NodeIR, EdgeIR, FlowIR)
4. Create templates.py with string constants for prompts
5. Create conftest.py with test fixtures in tests/test_planning/

## Risk Mitigation

| Risk | Impact on Other Subtasks | Mitigation Strategy |
|------|-------------------------|-------------------|
| WorkflowManager API changes | All subtasks using workflow discovery | Verify API before implementation |
| Registry interface differences | Validation nodes need accurate data | Test extraction functions thoroughly |
| LLM configuration issues | Generator nodes can't function | Document setup process clearly |
| Pydantic model misalignment | Generation fails validation | Follow IR schema precisely |

## Validation Strategy
- Verify workflow_loader delegates properly to WorkflowManager
- Ensure registry helpers return correct empty types (dict/list)
- Test error handling for missing workflows and empty names
- Validate Pydantic models accept valid IR structure
- Ensure test fixtures work for both mock modes
