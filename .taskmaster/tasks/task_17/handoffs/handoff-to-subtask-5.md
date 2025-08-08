# Handoff to Subtask 5: Validation & Refinement System

**⚠️ CRITICAL: Read this before starting. The generator's output has specific patterns you must validate.**

## 🎯 What Your ValidatorNode Will Receive

When you implement ValidatorNode, you'll receive workflows from GeneratorNode via:
```python
shared["generated_workflow"]  # The complete workflow IR to validate
shared["generation_attempts"]  # Number of attempts (for retry logic)
```

The workflow structure the generator produces:
```python
{
    "ir_version": "0.1.0",
    "inputs": {
        "repo_name": {
            "description": "GitHub repository",
            "required": True,
            "type": "string"
        },
        "limit": {
            "description": "Number of issues",
            "required": False,
            "type": "integer",
            "default": 50  # Universal default, NOT request-specific
        }
    },
    "nodes": [
        {"id": "fetch_issues", "type": "github-list-issues", "params": {"repo": "$repo_name", "limit": "$limit"}},
        {"id": "process", "type": "llm", "params": {"prompt": "Analyze $issues"}}
    ],
    "edges": [
        {"from": "fetch_issues", "to": "process"}  # LINEAR only, no action field
    ]
}
```

## 🚨 Critical Validation Requirements

### 1. Template Variables Are Sacred (MOST CRITICAL)
The generator MUST use template variables. Your validator MUST catch hardcoded values:
```python
# ❌ INVALID - Hardcoded discovered value
"params": {"repo": "project-x", "limit": 20}  # FAIL THIS!

# ✅ VALID - Template variables
"params": {"repo": "$repository", "limit": "$max_items"}
```

**Why this matters**: I discovered the LLM sometimes wants to be "helpful" and insert discovered values directly. The prompt emphasizes templates 3+ times, but validation is your safety net.

**CLARIFICATION**: You can't actually detect if a value "should have been" a template (no access to discovered_params). Focus on validating that all declared inputs are USED as templates (unused inputs validation).

### 2. Linear Workflows Only (MVP Constraint)
```python
# ❌ INVALID - Branching edge
{"from": "node1", "to": "node2", "action": "error"}  # Has action field

# ✅ VALID - Linear edge
{"from": "node1", "to": "node2"}  # No action field or action="default"
```

**Discovery**: The LLM understands "linear" but sometimes adds error handling edges anyway. Check for action fields != "default".

**UPDATE**: Less critical - the generator won't create branching without being prompted for it. Low priority validation.

### 3. Template Variables Must Match Inputs Keys
```python
# If workflow has "$repo_name" in params
# Then inputs MUST have "repo_name" key (not "repo" or "repository")
```

**Edge case found**: Generator renames parameters for clarity. When it uses "$input_file" in params, inputs must define "input_file", not the original "filename" from discovered_params.

## 🔧 Registry Issues You'll Hit

**CRITICAL DISCOVERY**: The registry might be incomplete!

During testing, I found ComponentBrowsingNode was only getting file nodes because the registry wasn't scanning all directories. Check that:
```python
# In your tests, verify registry has GitHub nodes
registry = Registry()
# NOTE: Registry automatically scans subdirectories using rglob("*.py")
# No manual subdirectory scanning needed!
metadata = registry.get_nodes_metadata()
assert any("github" in n for n in metadata.keys())
```

Without proper registry population, generator creates file-only workflows for GitHub requests!

## 📊 Validation Errors to Return

Your error messages go back to the generator for retry. Be SPECIFIC:
```python
validation_errors = [
    "Template variable $repo_name used but not defined in inputs field",
    "Node type 'github-list-issuez' not found (typo? did you mean 'github-list-issues'?)",
    "Edge creates branch: node1 -> node2 with action='error' (linear only)"
]
```

The generator's retry prompt includes these verbatim. Clear errors = better retry success.

## 🧪 Testing Patterns That Work

### North Star Example Principle
**Key insight from testing**:
- **Vague prompts** = User wants existing workflow (Path A)
- **Specific prompts** = User wants new workflow (Path B)

Your validator tests should use SPECIFIC prompts for Path B:
```python
# Good test prompt (specific, mentions GitHub)
"Create a changelog by fetching the last 30 closed issues from github repo pflow,
 generate markdown, write to CHANGELOG.md, commit changes"

# Bad test prompt (too vague, might trigger Path A)
"make a changelog"
```

### Real LLM Testing Is Essential
The generator has 21 real LLM tests. You MUST test with real LLM too because:
1. Structured output behavior varies between models
2. Template variable generation needs real validation
3. Retry logic depends on actual LLM responses

Test file pattern:
```python
# tests/test_planning/llm/behavior/test_validator_core.py
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"),
    reason="LLM tests disabled. Set RUN_LLM_TESTS=1"
)
```

## 🐛 Subtle Bugs and Edge Cases

### 1. Empty Inputs Field
Generator might produce `"inputs": {}` for simple workflows. Decide: is this valid or error?

### 2. Default Values Issue
Generator uses universal defaults (100, not request-specific 20). But what if workflow genuinely needs the discovered value as default? This tension is unresolved.

### 3. Node Type Validation
Generator doesn't validate node types exist (trusts planning_context). You must validate against actual registry.

### 4. Shared Store Collision
Generator avoids multiple nodes of same type to prevent collision (until Task 9). You might see workarounds like:
```python
# Generator might create read_data -> process -> read_config
# Instead of read_data + read_config in parallel
```

## 📁 Critical Files and Code

**Generator implementation**: `/Users/andfal/projects/pflow/src/pflow/planning/nodes.py:1028-1236`
- See `_build_prompt()` method for how I emphasize template variables
- See `_parse_structured_response()` for Anthropic response handling

**Test patterns that work**:
- `/Users/andfal/projects/pflow/tests/test_planning/llm/behavior/test_generator_core.py`
- See `test_template_variables_preserved_not_hardcoded` - THE critical test

**North Star examples**: `/Users/andfal/projects/pflow/docs/vision/north-star-examples.md`
- Use these for consistent testing across subtasks

**Clarifications doc**: `/Users/andfal/projects/pflow/.taskmaster/tasks/task_17/implementation/subtask-4/subtask-4-ambiguities-clarifications.md`
- Documents all design decisions about parameter handling

## 🔮 What Success Looks Like for You

Your ValidatorNode should:
1. ~~Catch hardcoded values that should be templates~~ Verify all declared inputs are USED as templates (unused inputs validation)
2. Verify all template variables have inputs definitions OR come from node outputs
3. ~~Ensure linear workflow constraint~~ (Low priority - generator won't create branching unprompted)
4. Check node types exist in registry
5. Return clear, actionable error messages (as list of strings)
6. Support up to 3 retry attempts (return "retry" for < 3, "failed" for >= 3)

## 💡 Final Critical Insight

The generator/validator pair is the quality gate for Path B. The generator is creative but imperfect. Your validator is the safety net that ensures only executable workflows reach ParameterMappingNode.

The convergence point (ParameterMappingNode) trusts that validated workflows are correct. Don't let bad workflows through!

## 🔗 Dependencies You'll Need

```python
from pflow.core import validate_ir, ValidationError  # For IR validation
from pflow.registry import Registry  # For node type validation
from pflow.runtime.template_validator import TemplateValidator  # For template validation
```

Remember: The generator produces 99% valid workflows. Your job is catching that 1% that would break at runtime.

---

*Good luck with the Validation & Refinement System! The template variable validation is the most critical piece - everything else is secondary.*