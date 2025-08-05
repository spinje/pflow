# Task 17 Subtask 1 Review: Foundation & Infrastructure

## Executive Summary

Subtask 1 successfully created the foundational infrastructure for Task 17's Natural Language Planner. All components are built, tested, and ready for use by subsequent subtasks. The foundation includes utilities, Pydantic models, prompt templates, and comprehensive test fixtures.

## Critical Information for All Future Subtasks

### 1. LLM Response Structure (MOST IMPORTANT)

**⚠️ This WILL affect Subtasks 3, 4, 5 that use structured LLM output:**

```python
# WRONG - What you might expect:
response = model.prompt(prompt, schema=PydanticModel)
data = response.json()  # ❌ NOT your structured data!

# CORRECT - What actually happens:
response = model.prompt(prompt, schema=PydanticModel)
response_data = response.json()
structured_data = response_data['content'][0]['input']  # ✅ Data is nested here!
```

This was discovered through real API testing and is NOT documented in the llm library docs. Every node using structured output MUST extract from this nested location.

### 2. Foundation Components Available

#### Utilities (Pure I/O Only)
```python
# Workflow loading
from pflow.planning.utils.workflow_loader import load_workflow, list_all_workflows

# Registry data extraction
from pflow.planning.utils.registry_helper import (
    get_node_interface,
    get_node_outputs,
    get_node_inputs
)
```

#### Pydantic Models for Structured Output
```python
from pflow.planning.ir_models import NodeIR, EdgeIR, FlowIR

# Example: Generate workflow with LLM
response = model.prompt(generation_prompt, schema=FlowIR)
workflow_data = response.json()['content'][0]['input']  # Note the nesting!
```

#### Prompt Templates
```python
from pflow.planning.prompts.templates import (
    WORKFLOW_DISCOVERY_PROMPT,
    WORKFLOW_GENERATION_PROMPT,
    ERROR_RECOVERY_PROMPT,
    TEMPLATE_VARIABLE_PROMPT,
    COMPONENT_BROWSING_PROMPT,
    PARAMETER_DISCOVERY_PROMPT
)
```

### 3. Architectural Patterns to Follow

#### Direct Instantiation (PocketFlow Pattern)
```python
class YourNode(Node):
    def __init__(self):
        super().__init__()
        self.registry = Registry()  # Direct instantiation
        self.llm = llm.get_model("anthropic/claude-sonnet-4-0")  # Exact string
```

#### NO Thin Wrappers
- Import `context_builder` directly, don't wrap it
- Use utilities as-is, don't add abstraction layers
- LLM calls belong in nodes, NOT in utilities

#### Error Handling
- Let exceptions bubble up (PocketFlow pattern)
- Only catch what you can meaningfully handle
- Registry helpers return empty dict/list (never raise)

### 4. Test Infrastructure

#### Available Fixtures
```python
# In tests/test_planning/conftest.py:
- mock_llm: Basic LLM mock
- mock_llm_with_schema: Handles schema parameter
- test_workflow: Sample workflow with template variables
- test_registry_data: Sample registry with interfaces
- shared_store: Basic store with user_input, stdin_data, current_date
- enable_real_llm: Check for RUN_LLM_TESTS=1
```

#### Testing Pattern
```python
def test_your_node(mock_llm_with_schema, test_registry_data):
    # Mock is automatically applied
    node = YourNode()
    # Test logic
```

### 5. Shared Store Schema

Documented in `src/pflow/planning/__init__.py`:

**CLI Initializes:**
- `user_input`: Natural language request
- `stdin_data`: Optional piped data
- `current_date`: ISO timestamp

**Nodes Write:**
- `discovery_context`, `discovery_result`, `browsed_components`
- `discovered_params`, `planning_context`, `generation_attempts`
- `validation_errors`, `generated_workflow`, `found_workflow`
- `workflow_metadata`, `extracted_params`, `verified_params`
- `execution_params`, `planner_output`

### 6. Template Variables Are Sacred

All nodes MUST preserve template variable syntax:
- `$variable` - Simple variables
- `$variable.field.subfield` - Nested access

These enable workflow reusability - the core value prop of pflow.

### 7. Configuration Complete

- ✅ Pydantic installed and working
- ✅ LLM library configured with anthropic key
- ✅ Model available: `anthropic/claude-sonnet-4-0`
- ✅ llm-anthropic plugin installed
- ✅ Logging configured at module level

### 8. Known Gotchas

1. **EdgeIR uses aliases**: `{"from": "n1", "to": "n2"}` not `from_node`/`to_node`
2. **Pydantic deprecation**: Use `min_length` not `min_items` for lists
3. **WorkflowManager**: Thread-safe with atomic operations
4. **Registry**: Returns empty collections on missing data
5. **Test fixtures**: Auto-discovered by pytest

## What Was NOT Implemented

- No nodes (that's Subtask 2+)
- No flow orchestration (that's Subtask 6)
- No CLI integration
- No business logic in utilities

## Files Created

```
src/pflow/planning/
├── __init__.py                    # Module docs + logging + shared store schema
├── ir_models.py                   # NodeIR, EdgeIR, FlowIR Pydantic models
├── utils/
│   ├── __init__.py
│   ├── workflow_loader.py         # load_workflow(), list_all_workflows()
│   └── registry_helper.py         # get_node_interface/outputs/inputs()
└── prompts/
    ├── __init__.py
    └── templates.py               # 6 prompt string constants

tests/test_planning/
├── __init__.py
├── conftest.py                    # All test fixtures
├── test_ir_models.py             # 21 tests
├── test_registry_helper.py       # 16 tests
└── test_workflow_loader.py       # 10 tests
```

## Test Results

- 101 planning tests passing (47 new from this subtask)
- All code quality checks passing (ruff, mypy, deptry)
- Real LLM integration verified with structured output

## Key Success Factors

1. **Walking skeleton approach** - Started simple, added incrementally
2. **Test-driven** - Every component has comprehensive tests
3. **Real API testing** - Discovered the response nesting early
4. **Following patterns** - Adhered to PocketFlow conventions

## For Subtask Implementers

1. **Read the shared progress log** first
2. **Use the utilities** - don't reimplement
3. **Follow the patterns** - direct instantiation, no wrappers
4. **Remember the nesting** - LLM structured responses
5. **Test with mocks first** - then `RUN_LLM_TESTS=1`

The foundation is solid. Build confidently on top of it.
