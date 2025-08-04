# Task 17: Implementation Principles (v2)

## The Core Challenge

Task 17 builds a **meta-workflow** that transforms natural language into executable workflows. It has 9 specialized nodes, two execution paths that converge, and sophisticated LLM reasoning. Getting this right requires specific principles.

## Required Reading Before Implementation

1. **.taskmaster/tasks/task_17/task-17-ambiguities.md** - Resolved design decisions (model selection, retry strategy, etc.)
2. **.taskmaster/tasks/task_17/task-17-advanced-patterns.md** - Production-proven patterns for each challenge
3. **.taskmaster/tasks/task_17/starting-context/task-17-subtask-[N]-spec.md** - Your specific subtask specification
4. **.taskmaster/tasks/task_17/task-17-pocketflow-insights.md** - Framework conventions and anti-patterns to avoid
5. **pocketflow/__init__.py** - The ACTUAL framework source (100 lines - READ IT!)

## Implementation Philosophy

Follow PocketFlow's 7-step Agentic Coding process (see task-17-pocketflow-insights.md for details).
Key for Task 17: **Start with walking skeleton WITH LOGGING** → iterate → add features.

## Three Principles That Matter Most

### 1. Start With a Walking Skeleton (WITH LOGGING)

**Walking Skeleton** = Minimal implementation that routes correctly through the entire flow.

First, configure logging at module level:
```python
import logging

# Configure at module level
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
```

For EVERY node, your first version should route correctly AND show what's happening:

```python
class WorkflowGeneratorNode(Node):
    def exec(self, prep_res):
        logger.debug(f"Generator received input: {prep_res.get('user_input', '')[:50]}...")
        # V1: Just return something valid
        result = {"workflow": {"nodes": [], "edges": []}}
        logger.debug(f"Generator returning: {len(result['workflow']['nodes'])} nodes")
        return result

    def post(self, shared, prep_res, exec_res):
        logger.debug(f"Generator routing to validation")
        shared["generated_workflow"] = exec_res["workflow"]
        return "validate"  # Routes to ValidationNode
```

Logging helps you see:
- What data is flowing through
- Which paths are taken
- Where things fail
- How long operations take (`start = time.time()` ... `logger.debug(f"Took {time.time()-start:.2f}s")`)

THEN iterate to add real logic.

### 2. The Planner's Shared Store

**→ See `task-17-standardized-conventions.md` for the complete shared store schema**

Quick reference - key data flow:
```
Input → Discovery → Generation/Found → Convergence → Output
         ↓           ↓                  ↓
    discovery_result discovered_params  extracted_params → execution_params
```

Critical points:
- ParameterMappingNode does INDEPENDENT extraction (doesn't use discovered_params)
- Track `missing_params` for routing decisions
- Use these as starting points, iterate during implementation

### 3. LLM Calls Use Structured Output

Task 17 uses `llm` library with schema support. **SETUP REQUIRED:**

```bash
# Install the Anthropic plugin first!
pip install llm-anthropic
llm keys set anthropic  # Set your API key

# Verify it works:
llm models | grep claude  # Should show anthropic/claude-sonnet-4-0
```

Then use structured output:

```python
from pydantic import BaseModel
import llm

class WorkflowDecision(BaseModel):
    found: bool
    workflow_name: str | None
    confidence: float

class WorkflowDiscoveryNode(Node):
    def exec(self, prep_res):
        model = llm.get_model("anthropic/claude-sonnet-4-0")

        # Use schema parameter for structured output
        response = model.prompt(prompt, schema=WorkflowDecision)
        result = response.json()  # Already validated by llm library!

        return result
```

No manual JSON parsing. No regex extraction. The `llm` library validates against your Pydantic schema automatically.

## Critical PocketFlow Framework Rules (MUST KNOW!)

### Rule 1: exec() CANNOT Access Shared Store
```python
# ❌ WRONG - exec() has no access to shared!
def exec(self, prep_res):
    value = shared["key"]  # NameError: shared not defined!

# ✅ CORRECT - pass everything through prep_res
def prep(self, shared):
    return {"key": shared["key"], "other": shared["other"]}

def exec(self, prep_res):
    value = prep_res["key"]  # Now accessible
```

### Rule 2: exec_fallback() Only Gets (prep_res, exc)
```python
# ❌ WRONG - exec_fallback doesn't get shared!
def exec_fallback(self, prep_res, exc):
    shared["error"] = str(exc)  # NameError!

# ✅ CORRECT - Return shared from prep() if fallback needs it
def prep(self, shared):
    # ⚠️ WARNING: This is an EXCEPTION PATTERN, not default!
    # Only do this when exec_fallback needs context for error recovery
    # See task-17-advanced-patterns.md Pattern 2 for full explanation
    return shared  # Most nodes should return specific data instead!

def exec_fallback(self, prep_res, exc):
    # prep_res is the full shared dict now
    user_input = prep_res.get("user_input", "")
    return {"fallback": True, "context": user_input}
```

### Rule 3: post() MUST Return an Action String
```python
# ❌ WRONG - forgot to return action
def post(self, shared, prep_res, exec_res):
    shared["result"] = exec_res
    # Missing return!

# ✅ CORRECT - always return action string
def post(self, shared, prep_res, exec_res):
    shared["result"] = exec_res
    return "valid" if exec_res["success"] else "invalid"
```

### Rule 4: cur_retry is Set by Framework
```python
# ❌ WRONG - don't set manually
def __init__(self):
    super().__init__(max_retries=3)
    self.cur_retry = 0  # NO! Framework sets this

# ✅ CORRECT - use during execution
def exec(self, prep_res):
    if self.cur_retry > 0:  # Framework sets this (0-indexed)
        prompt = f"Retry {self.cur_retry + 1}: {prep_res['prompt']}"
```

## The Two-Path Architecture

Task 17 has two paths that converge. Understand this deeply:

```python
# Path A: Found existing workflow
workflow_discovery - "found" >> parameter_mapping

# Path B: Generate new workflow
workflow_discovery - "not_found" >> component_browsing
component_browsing >> parameter_discovery
parameter_discovery >> workflow_generator
workflow_generator >> validator
validator - "invalid" >> workflow_generator  # Retry loop
validator - "valid" >> metadata_generation
metadata_generation >> parameter_mapping

# CONVERGENCE: Both paths meet at parameter_mapping
parameter_mapping - "complete" >> parameter_preparation >> result_preparation
parameter_mapping - "incomplete" >> result_preparation  # Missing params
```

**CRITICAL INSIGHT**: ParameterMappingNode is the **verification gate** - it:
- Extracts parameters from natural language
- Maps them to workflow requirements
- Verifies ALL required parameters exist
- Routes to "incomplete" if parameters missing (CLI will prompt user)
- This is NOT just parameter extraction - it's executability verification!

## Key Pattern: Logging Throughout Validation

See task-17-advanced-patterns.md for all patterns. Here's how to add logging to Pattern 4 (validation):

```python
class ValidationNode(Node):
    def post(self, shared, prep_res, exec_res):
        if not exec_res["valid"]:
            logger.warning(f"Validation failed: {exec_res['errors'][:3]}")
            attempts = shared.get("generation_attempts", 0)
            if attempts < 3:
                logger.info(f"Retrying generation (attempt {attempts + 1}/3)")
                shared["generation_attempts"] = attempts + 1
                shared["validation_errors"] = exec_res["errors"][:3]  # Top 3 only
                return "retry"
            logger.error(f"Generation failed after {attempts + 1} attempts")
            return "failed"
        logger.info("Validation passed")
        return "valid"
```

**Key insight**: Log at different levels (info/warning/error) to track flow through retries.

## Common Mistakes to Avoid

### Mistake 1: Importing LLM in Utilities
```python
# ❌ WRONG - utils/ is for external I/O only
# utils/llm_helper.py
import llm  # NO! LLM is core functionality

# ✅ CORRECT - LLM calls belong in nodes
# nodes.py
import llm  # Yes, LLM logic is core to nodes
```

### Mistake 2: Complex First Implementation
```python
# ❌ WRONG - too complex for first iteration
def exec(self, prep_res):
    try:
        workflow = self.generate_with_retry_and_caching_and_validation()
        # 100 lines of logic...
    except:
        # Complex error handling...

# ✅ CORRECT - start simple
def exec(self, prep_res):
    return {"workflow": {"nodes": [], "edges": []}}  # V1: Just route correctly
```

### Mistake 3: Forgetting to Return Actions
```python
# ❌ WRONG - no return in post()
def post(self, shared, prep_res, exec_res):
    shared["result"] = exec_res
    # Forgot return!

# ✅ CORRECT
def post(self, shared, prep_res, exec_res):
    shared["result"] = exec_res
    return "default"  # Or appropriate action
```

## Utilities vs Nodes

- **Utilities** (`utils/`): ONLY external I/O - load workflows, get registry data
- **Nodes**: ALL logic including LLM calls - these are core functionality, not utilities

## File Structure

```
src/pflow/planning/
├── nodes.py      # ALL nodes in ONE file (start here)
├── flow.py       # Wire nodes together
├── utils/        # External I/O only
└── prompts/      # Template strings

# When to split nodes.py:
# - When it exceeds ~1000 lines
# - Split into logical groups:
#   ├── nodes/
#   │   ├── __init__.py
#   │   ├── discovery.py  # Discovery & browsing nodes
#   │   ├── generation.py # Generator & validator nodes
#   │   └── parameters.py # Parameter-related nodes
```

## Implementation Sequence

1. **First**: Get all nodes routing correctly (walking skeletons) WITH LOGGING
2. **Second**: Add shared store updates (log what's stored)
3. **Third**: Add LLM calls with structured output (log prompts/responses)
4. **Fourth**: Add validation and retry logic (log why retrying)
5. **Last**: Add error handling (but keep logging throughout!)

## Testing Strategy (Critical!)

### Test As You Build
```python
# For each node, immediately write tests:
def test_discovery_node_routing():
    """Test that discovery node routes correctly."""
    node = WorkflowDiscoveryNode()
    shared = {"user_input": "test", "discovery_result": {"found": False}}
    action = node.run(shared)
    assert action == "not_found"

# Mock LLM for unit tests:
@patch("llm.get_model")
def test_generator_with_mock(mock_get_model):
    mock_response = Mock()
    mock_response.json.return_value = {"workflow": {...}}
    mock_model = Mock()
    mock_model.prompt.return_value = mock_response
    mock_get_model.return_value = mock_model
    # Test logic here
```

### Integration Tests
```python
# Optional real LLM tests:
@pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), reason="Set RUN_LLM_TESTS=1")
def test_real_llm_generation():
    # Test with real anthropic/claude-sonnet-4-0
    pass
```

## The Two Rules That Matter

1. **Every iteration must produce a working system that can be tested.**
   - If your change breaks end-to-end flow, it's too big.

2. **If you're not embarrassed by your first implementation, you started too complex.**
   - Start simple. Add complexity through iteration, not upfront design.

## Iteration Reality Check

From PocketFlow guide: *"Expect to repeat Steps 3–6 hundreds of times."*

For Task 17:
- Each node: 10-20 iterations
- Flow wiring: 5-10 iterations
- Integration: 20+ iterations
- Total: 100+ iterations

This is NORMAL. Plan for it. Log everything so you can see progress.

## Quick Debugging Checklist

When something doesn't work:
1. Check the logs - what path was taken?
2. Check shared store - what keys are set?
3. Check action returns - are nodes routing correctly?
4. Check prep() returns - is exec() getting the right data?
5. Check imports - are you importing from the right place?

## Which Subtask Are You Implementing?

Each subtask has specific focus areas from this document:

- **Subtask 1 (Foundation)**: Focus on shared store schema, file structure, utilities vs nodes
- **Subtask 2 (Discovery)**: Focus on walking skeleton, two-path architecture, routing
- **Subtask 3 (Generation)**: Focus on LLM structured output, graceful failure, retry patterns
- **Subtask 4 (Validation)**: Focus on validation patterns, retry context, error limits
- **Subtask 5 (Parameters)**: Focus on verification gate concept, parameter stages
- **Subtask 6 (Orchestration)**: Focus on two-path convergence, flow wiring
- **Subtask 7 (Integration)**: Focus on testing strategy, iteration expectations

## What This Document Provides

Read This Document For:
- How to start implementation (walking skeleton)
- How to debug when things go wrong
- What PocketFlow rules you MUST follow
- Common mistakes that will waste time
- Practical logging strategies

---

*These principles are curated specifically for Task 17's meta-workflow implementation. All implementers should read this document regardless of which subtask they're building.*
