# Task 17: Standardized Conventions - Implementation Guidelines

## Purpose
This document consolidates the **recommended conventions** for Task 17 to:
1. Resolve inconsistencies found across multiple documents
2. Reduce repetition by being the single reference point
3. Provide starting points that should evolve during implementation

Other documents now reference this file instead of repeating the same information.

## Recommended Shared Store Schema

This is a **suggested starting point** based on resolving the documentation conflicts. Expect to iterate and adjust as implementation reveals better patterns:

```python
shared = {
    # === STAGE 1: INPUT (from CLI) ===
    "user_input": str,              # Natural language input from user
    "stdin_data": Any,              # Optional stdin data
    "current_date": str,            # ISO format timestamp for temporal resolution

    # === STAGE 2: DISCOVERY (what exists?) ===
    "discovery_context": str,       # Lightweight context for initial browsing
    "discovery_result": {
        "found": bool,              # Whether complete workflow found
        "workflow": dict,           # The found workflow (if found)
        "workflows": list,          # All available workflows
    },
    "browsed_components": {
        "node_ids": list,           # Selected node types for building
        "workflow_names": list,     # Selected workflows for composition
    },

    # === STAGE 3: GENERATION (Path B only) ===
    "discovered_params": dict,      # Named params found BEFORE generation
                                   # Example: {"limit": "20", "state": "closed"}
                                   # Used to guide generator's template variable creation

    "planning_context": str,        # Detailed interface specs for selected components
    "generation_attempts": int,     # Retry counter (max 3)
    "validation_errors": list,      # Top 3 errors from previous attempt
    "generated_workflow": dict,     # The generated workflow IR

    # === STAGE 3-ALT: FOUND (Path A only) ===
    "found_workflow": dict,         # The existing workflow to reuse

    # === STAGE 4: CONVERGENCE (both paths meet) ===
    "extracted_params": dict,       # Values extracted for workflow's defined inputs
                                   # ParameterMappingNode does INDEPENDENT extraction
                                   # Example: {"issue_number": "1234", "repo": "pflow"}

    "missing_params": list,         # Required params that couldn't be extracted
                                   # Example: ["api_key", "branch_name"]
                                   # Empty list if all params found

    "execution_params": dict,       # Final params formatted for runtime
                                   # From ParameterPreparationNode
                                   # Same structure as extracted_params

    # === STAGE 5: METADATA ===
    "workflow_metadata": {
        "suggested_name": str,      # Generated name for saving
        "description": str,         # What the workflow does
        "inputs": list,            # Expected input parameters
        "outputs": list,           # What the workflow produces
    },

    # === STAGE 6: OUTPUT (to CLI) ===
    "planner_output": {
        "workflow_ir": dict,        # Final workflow (found or generated)
        "execution_params": dict,   # Parameters for execution
        "workflow_metadata": dict,  # Metadata for saving
    }
}
```

## Parameter Flow - Critical Understanding

### Path B (Generate New Workflow):
1. **ParameterDiscoveryNode** → sets `discovered_params`
   - Discovers values and ASSIGNS names: `{"limit": "20", "state": "closed"}`
   - Generator uses these names to create `$limit` and `$state` in workflow

2. **GeneratorNode** → creates workflow with inputs matching discovered param names

3. **ParameterMappingNode** → sets `extracted_params` and `missing_params`
   - INDEPENDENTLY extracts values for the workflow's defined inputs
   - Does NOT use `discovered_params` - fresh extraction
   - Verifies executability

### Path A (Reuse Existing Workflow):
1. **ParameterMappingNode** → sets `extracted_params` and `missing_params`
   - Extracts values for the existing workflow's defined inputs
   - Same independent extraction process

### Both Paths:
1. **ParameterPreparationNode** → sets `execution_params`
   - Formats extracted params for runtime (usually pass-through)

## Key Principles

### 1. NO `verified_params`
Verification is an OPERATION performed by ParameterMappingNode, not a data state. We track:
- `extracted_params` - what was successfully extracted
- `missing_params` - what couldn't be extracted

### 2. Independent Extraction
ParameterMappingNode ALWAYS does fresh extraction based on the workflow's defined inputs. It does NOT use `discovered_params` from Path B. This independence is the verification gate.

### 3. Clear Routing Logic
```python
# ParameterMappingNode post():
if missing_params:
    return "params_incomplete"  # CLI will need to prompt for missing
else:
    return "params_complete"    # Can proceed to execution
```

## Action Strings - Standardized

These are the recommended action strings for consistency:

### WorkflowDiscoveryNode:
- `"found_existing"` → Path A (reuse)
- `"not_found"` → Path B (generate)

### ValidatorNode:
- `"valid"` → proceed to metadata
- `"invalid"` → retry generation (up to 3 times)
- `"failed"` → all retries exhausted (generation failed)

### ParameterMappingNode:
- `"params_complete"` → all required params extracted
- `"params_incomplete"` → missing required params

### All other nodes:
- Use descriptive action strings that clearly indicate the next step
- Default to `"continue"` or `"done"` for linear progression

**Note**: The key is consistency within your implementation. If you find better names during implementation, use them consistently throughout.

## Model Configuration

The planner uses **`anthropic/claude-sonnet-4-0`** for all internal LLM reasoning:

```python
import llm

class AnyPlannerNode(Node):
    def exec(self, prep_res):
        model = llm.get_model("anthropic/claude-sonnet-4-0")
        # ... use model for reasoning ...
```

Setup required:
```bash
pip install llm-anthropic
llm keys set anthropic  # Set API key
```

## File Structure

```
src/pflow/planning/
├── __init__.py          # Exports: from .flow import create_planner_flow
├── flow.py              # Contains create_planner_flow() function
├── nodes.py             # All node implementations (start here)
├── ir_models.py         # Pydantic models for structured output
├── utils/               # ONLY external I/O operations
│   ├── workflow_loader.py
│   └── registry_helper.py
└── prompts/             # Prompt templates (data, not code)
```

**Note**: The CLI imports via `from pflow.planning import create_planner_flow`

## exec_fallback Pattern - EXCEPTION ONLY

**→ See `task-17-advanced-patterns.md` Pattern 2 for full explanation**

### Default Pattern (99% of nodes):
```python
def prep(self, shared):
    # Return ONLY what exec() needs
    return {
        "user_input": shared["user_input"],
        "context": shared.get("context", "")
    }
```

### Exception Pattern (when exec_fallback needs context):
```python
def prep(self, shared):
    # ⚠️ WARNING: Exception pattern - only for error recovery!
    # See advanced-patterns.md Pattern 2 before using this
    return shared  # Full context for exec_fallback error handling
```

**Rule**: Most nodes should NEVER return the full shared dict. Only use the exception pattern when exec_fallback genuinely needs context for error recovery or fallback strategies.

## Testing Conventions

### Mocked Tests (default):
```python
@patch("llm.get_model")
def test_something(mock_get_model):
    mock_model = Mock()
    mock_model.prompt.return_value = Mock(json=lambda: {...})
    mock_get_model.return_value = mock_model
```

### Real LLM Tests (optional):
```python
@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), reason="Set RUN_LLM_TESTS=1")
def test_real_llm():
    # Uses real anthropic/claude-sonnet-4-0
```

## How to Use This Document

This document provides **recommended starting points** to resolve the inconsistencies found in the documentation:

1. **Start with these conventions** - They resolve the conflicts between docs
2. **Iterate and improve** - Change them when implementation reveals better patterns
3. **Document changes** - Update this file when you discover what actually works
4. **Don't be rigid** - These are guidelines, not laws

### What This Resolves

This document addresses these specific documentation conflicts:
- Multiple conflicting shared store schemas → Suggests one consistent schema
- 5 different parameter terms → Recommends 3-4 clear terms
- Unclear parameter independence → Clarifies the separation
- Model name chaos → Suggests using `anthropic/claude-sonnet-4-0`

### What This Doesn't Lock In

Feel free to change:
- Key names if better ones emerge during implementation
- Data flow if a simpler pattern works better
- Number of parameters states if you find redundancy
- Action strings if clearer ones make sense
- Any convention that fights against the implementation

## The Spirit of These Guidelines

The goal is to **prevent confusion from inconsistent docs**, not to constrain implementation. Think of this as:
- "Here's what we think will work based on resolving conflicts"
- NOT "This is the only way it can be done"

When you find a better way during implementation, do it and update this document.

---

*Guidelines to resolve documentation inconsistencies. Expect these to evolve during implementation.*
