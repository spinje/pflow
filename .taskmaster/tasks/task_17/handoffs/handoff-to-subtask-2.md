# Handoff to Subtask 2: Discovery System

**⚠️ CRITICAL: Read this entire memo before starting. When done, confirm you're ready to begin - do NOT start implementing immediately.**

## 🎯 Core Outcomes You're Building On

### Foundation Layer Complete
- **Directory**: `src/pflow/planning/` with utils/ and prompts/ subdirectories
- **Utilities**: Pure I/O functions in utils/ - NO business logic
- **Models**: Pydantic models in `ir_models.py` ready for structured LLM output
- **Test Fixtures**: Comprehensive mocks in `tests/test_planning/conftest.py`

### What Actually Works
- `workflow_loader.load_workflow(name)` - delegates to WorkflowManager
- `registry_helper.get_node_interface/outputs/inputs()` - pure data extraction
- LLM configured: `anthropic/claude-sonnet-4-0` (exact string)
- Test fixtures: `mock_llm`, `mock_llm_with_schema`, `test_workflow`, `test_registry_data`

## 🚨 Critical Discovery: LLM Response Structure

**THIS WILL BITE YOU**: When using structured output with Pydantic schemas, the response is NESTED:

```python
# What you might expect (WRONG):
response = model.prompt(prompt, schema=SomeModel)
data = response.json()  # ❌ This is NOT your structured data!

# What actually happens (CORRECT):
response = model.prompt(prompt, schema=SomeModel)
response_data = response.json()
structured_data = response_data['content'][0]['input']  # ✅ Your data is HERE
```

I discovered this through real API testing. The structured data is buried in `content[0]['input']`. This affects EVERY node that uses structured output.

## 🏗️ Architectural Decisions Made

### NO context_wrapper.py
I did NOT create `context_wrapper.py` - it violates the "no thin wrapper" principle from PocketFlow. Your nodes should import context_builder directly:

```python
from pflow.planning.context_builder import build_discovery_context, build_planning_context
```

### Direct Instantiation Pattern
Follow PocketFlow conventions - nodes instantiate dependencies directly:
```python
class WorkflowDiscoveryNode(Node):
    def __init__(self):
        super().__init__()
        self.registry = Registry()  # Direct instantiation
        # NOT dependency injection
```

### Template Variables Are Sacred
The Pydantic models support template syntax (`$var`, `$var.field.subfield`). Your discovery logic must preserve these - they enable workflow reusability.

## 🔍 What I Learned About the APIs

### WorkflowManager
- Thread-safe with atomic operations
- Returns full metadata wrapper from `load()` method
- Gracefully handles missing workflows with `WorkflowNotFoundError`

### Registry
- Returns empty dict/list on missing data (no exceptions)
- Node metadata has `interface` key with `inputs`/`outputs`/`params`
- Structure data is nested under outputs (see `test_registry_data` fixture)

### LLM Library
- Requires `import llm` and `llm.get_model("anthropic/claude-sonnet-4-0")`
- The anthropic plugin is installed (`llm-anthropic`)
- API key is already configured

## 📁 Files You'll Need

### To Import From
- `/Users/andfal/projects/pflow/src/pflow/planning/utils/workflow_loader.py`
- `/Users/andfal/projects/pflow/src/pflow/planning/utils/registry_helper.py`
- `/Users/andfal/projects/pflow/src/pflow/planning/prompts/templates.py`
- `/Users/andfal/projects/pflow/src/pflow/planning/ir_models.py`

### To Read for Context
- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_17/implementation/progress-log.md` - Critical insights
- `/Users/andfal/projects/pflow/src/pflow/planning/__init__.py` - Shared store schema
- `/Users/andfal/projects/pflow/tests/test_planning/conftest.py` - Test fixtures

### Your Spec
- `/Users/andfal/projects/pflow/.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-2-spec.md`

## ⚡ Patterns to Follow

### Logging Pattern
Already configured at module level. Just use:
```python
import logging
logger = logging.getLogger(__name__)
```

### Test Pattern
Use the fixtures - they handle both mock and real LLM modes:
```python
def test_discovery(mock_llm, test_workflow, test_registry_data):
    # mock_llm automatically patches llm.get_model()
```

### Error Handling
Let exceptions bubble up (PocketFlow pattern). Only catch what you can meaningfully handle.

## ⚠️ Warnings and Gotchas

1. **EdgeIR Aliases**: Use `{"from": "n1", "to": "n2"}` not `from_node`/`to_node`
2. **Prompt Templates**: Are string constants with f-string placeholders, NOT functions
3. **Test Discovery**: All fixtures in conftest.py are auto-discovered
4. **Shared Store**: Schema is documented but CLI initializes it, not you
5. **No Proxy Mappings**: MVP doesn't support these - use template variables instead

## 🎭 Your Role in the Two-Path Architecture

You're implementing the ENTRY POINT to both paths:
- **WorkflowDiscoveryNode**: Routes to Path A (reuse) or Path B (generate)
- **ComponentBrowsingNode**: First step of Path B only

Remember: Both paths converge at ParameterMappingNode. Your discovery determines which path the flow takes.

## 💡 Hard-Won Insights

1. The shared progress log is SHARED across all subtasks - prefix your entries with "Subtask 2"
2. Registry data can be incomplete - always use the helper functions that return safe defaults
3. The walking skeleton approach works - start simple, add logging, iterate
4. Mock first, real LLM later - the test fixtures make this easy

## 🚀 Quick Start Checklist

1. [ ] Read your spec at `.taskmaster/tasks/task_17/starting-context/specs/task-17-subtask-2-spec.md`
2. [ ] Check the shared progress log for any Subtask 2 attempts
3. [ ] Import directly from utils/ and context_builder (no wrappers)
4. [ ] Remember the LLM response nesting when implementing discovery logic
5. [ ] Use template constants from `prompts/templates.py`
6. [ ] Test with fixtures first, real LLM with `RUN_LLM_TESTS=1`

---

**Remember**: The foundation is solid. Everything you need is built and tested. Focus on implementing the discovery logic that routes between the two paths. And don't forget - structured LLM responses are nested in `content[0]['input']`!

Good luck with the Discovery System! 🎯
