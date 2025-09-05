# Task 57 Implementation Guide: Critical Context and Insights

## Executive Summary

This guide provides essential context that the spec cannot capture. Task 57 is NOT just about updating test prompts - it's about fixing a fundamental test quality crisis discovered in Task 28 where 69% of workflow generator tests used non-existent mock nodes, creating dangerously false confidence. The tests were passing but testing nothing real.

## The Exact North Star Prompts (Character-Precise)

These MUST be used exactly as shown - even one word difference changes the test's validity:

### Primary: Generate Changelog
```python
# Verbose (Path B - generation)
CHANGELOG_VERBOSE = """generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."""

# Brief (Path A - reuse)
CHANGELOG_BRIEF = "generate a changelog for version 1.4"
```

### Secondary: Issue Triage Report
```python
# Verbose (Path B - generation)
TRIAGE_VERBOSE = """create a triage report for all open issues by fetching the the last 50 open issues from github, categorizing them by priority and type and then write them to triage-reports/2025-08-07-triage-report.md then commit the changes. Replace 2025-08-07 with the current date and mention the date in the commit message."""

# Brief (Path A - reuse)
TRIAGE_BRIEF = "create a triage report for all open issues"
```

### Tertiary: Simple Issue Summary
```python
# Same for both paths (too simple to vary)
ISSUE_SUMMARY = "summarize github issue 1234"
```

## Critical Task 28 Lessons (Not Just Recommendations - Hard-Won Truths)

### 1. The Context Problem That Broke Everything

Task 28 discovered the discovery prompt was failing because it had NO ACCESS to metadata. The metadata was being generated but NOT SAVED. The architectural fix was more important than any prompt improvement.

**Implication for Task 57**: Before testing, verify that:
- North star workflows are actually saved in WorkflowManager
- Metadata is accessible to discovery
- Context builder includes all necessary data

### 2. The Performance Testing Disaster

Task 28 initially had tests failing because they took >20 seconds. But this was API variance, not prompt quality! The same prompt:
- gpt-5-nano: 5-15 seconds
- Claude Sonnet: 20-40 seconds
- Network issues: 60+ seconds

**Implementation Pattern**:
```python
import time
import logging

logger = logging.getLogger(__name__)

def test_something():
    start = time.time()
    # Run your test
    result = do_test()
    duration = time.time() - start

    # NEVER DO THIS:
    # assert duration < 20.0, f"Too slow: {duration}s"

    # ALWAYS DO THIS:
    if duration > 20.0:
        logger.warning(f"Slow performance: {duration:.2f}s (model-dependent)")

    # Assert on actual results, not timing
    assert result == expected
```

### 3. The Mock Node Catastrophe

Task 28 found tests using nodes like:
- `claude-code` (doesn't exist)
- `github-list-prs` (doesn't exist)
- `slack-notify` (doesn't exist)

These tests passed but meant NOTHING because the nodes would fail in production.

**Safe Mock Pattern**:
```python
@pytest.fixture
def test_registry_with_real_nodes():
    """Only use nodes that actually exist."""
    from pflow.registry import Registry

    # Start with REAL registry
    registry = Registry()
    registry.load()  # Load actual nodes

    # Only add mock nodes if absolutely necessary and document why
    # Better: just use real nodes
    return registry
```

### 4. The Test Fidelity Problem

Tests weren't simulating the actual pipeline. They tested nodes in isolation but missed integration issues.

**Complete Pipeline Simulation**:
```python
def test_complete_north_star_flow():
    shared = {"user_input": CHANGELOG_VERBOSE}

    # 1. Discovery
    discovery = WorkflowDiscoveryNode()
    action = discovery.run(shared)
    assert action == "not_found"  # Path B

    # 2. Parameter Discovery (Path B only)
    param_discovery = ParameterDiscoveryNode()
    param_discovery.run(shared)
    assert "discovered_params" in shared
    assert shared["discovered_params"]["version"] == "1.3"

    # 3. Component Browsing (Path B only)
    browsing = ComponentBrowsingNode()
    browsing.run(shared)
    assert "browsed_components" in shared

    # 4. Generation (Path B only)
    generator = WorkflowGeneratorNode()
    action = generator.run(shared)
    assert action == "validate"

    # 5. Validation
    validator = ValidatorNode()
    action = validator.run(shared)
    # May retry if validation fails - provide multiple mocks

    # 6. Parameter Mapping (convergence point)
    mapping = ParameterMappingNode()
    action = mapping.run(shared)
    assert action in ["params_complete", "params_incomplete"]
```

## Mock Response Patterns That Actually Work

### Anthropic Format (MUST use this structure)
```python
from unittest.mock import Mock

def create_mock_response(data):
    """Create properly structured Anthropic response."""
    mock = Mock()
    mock.json.return_value = {
        "content": [{
            "input": data
        }]
    }
    # Some nodes also check usage
    mock.usage.return_value = {"input_tokens": 100, "output_tokens": 50}
    return mock
```

### Discovery Response Pattern
```python
# Path A - Found existing
discovery_found = create_mock_response({
    "found": True,
    "workflow_name": "generate-changelog",
    "confidence": 0.95,
    "reasoning": "Exact match for changelog generation"
})

# Path B - Not found
discovery_not_found = create_mock_response({
    "found": False,
    "workflow_name": None,
    "confidence": 0.3,
    "reasoning": "Too specific, needs new workflow"
})
```

### Parameter Discovery Pattern
```python
param_discovery = create_mock_response({
    "parameters": {  # Note: it's "parameters" not "params"
        "version": "1.3",
        "limit": "20",  # String, not int
        "branch": "create-changelog-version-1.3",
        "path": "versions/1.3/CHANGELOG.md"
    },
    "stdin_type": None,
    "reasoning": "Extracted from verbose description"
})
```

## The Path A vs Path B Philosophy

This is crucial to understand for testing:

### Path A (Reuse Existing)
- **Triggered by**: Brief, vague prompts
- **User mindset**: "I've done this before, just run it"
- **Example**: "generate a changelog"
- **Action string**: `"found_existing"`
- **Confidence**: Usually > 0.8

### Path B (Generate New)
- **Triggered by**: Verbose, specific prompts
- **User mindset**: "Let me explain exactly what I want"
- **Example**: The full 3-line changelog prompt
- **Action string**: `"not_found"`
- **Confidence**: Usually < 0.5

**Why This Matters**: Tests must validate that verbosity triggers generation, not just test random prompts.

## Common Implementation Pitfalls to Avoid

### 1. Don't Test Simplified Prompts
```python
# ❌ WRONG - Too simple, doesn't test real behavior
def test_changelog():
    shared = {"user_input": "make changelog"}

# ✅ CORRECT - Use exact north star prompt
def test_changelog_verbose():
    shared = {"user_input": CHANGELOG_VERBOSE}
```

### 2. Don't Skip Parameter Validation
```python
# ❌ WRONG - Vague assertion
assert "version" in str(shared["discovered_params"])

# ✅ CORRECT - Exact validation
assert shared["discovered_params"]["version"] == "1.3"
assert shared["discovered_params"]["limit"] == "20"
```

### 3. Don't Use Non-Existent Nodes
```python
# ❌ WRONG - These nodes don't exist
workflow = {
    "nodes": [
        {"type": "claude-code"},  # DOESN'T EXIST
        {"type": "github-list-prs"}  # DOESN'T EXIST
    ]
}

# ✅ CORRECT - Use real nodes
workflow = {
    "nodes": [
        {"type": "github-list-issues"},  # EXISTS
        {"type": "llm"},  # EXISTS
        {"type": "write-file"}  # EXISTS
    ]
}
```

### 4. Don't Trust Easy Tests
If all tests pass on first try, they're probably too easy. Good tests should:
- Fail initially until implementation is correct
- Test edge cases and boundaries
- Validate specific values, not just presence

## Template Validation Trap (Critical Warning)

Discovered in Task 28: Generated workflows with required inputs often FAIL validation because the validator checks if template variables have values AT GENERATION TIME, which they never do.

```python
# ❌ This will fail validation
workflow = {
    "inputs": {
        "file_path": {"required": True}  # Validator: is $file_path provided? NO!
    },
    "params": {"path": "${file_path}"}  # Template has no value yet
}

# ✅ Workarounds
# Option 1: No required inputs
"inputs": {}

# Option 2: Make optional with defaults
"inputs": {
    "file_path": {"required": False, "default": "output.md"}
}

# Option 3: Mock validation in tests
with patch("ValidatorNode.validate") as mock_validate:
    mock_validate.return_value = []  # No errors
```

## Test Organization Best Practices

### File Placement Logic
```
Is test using real LLM?
├─ NO → tests/test_planning/integration/
│       Use mocked responses, test complex flows
│
└─ YES → tests/test_planning/llm/integration/
        Requires RUN_LLM_TESTS=1, costs money
```

### Test Naming Convention
```python
# For north star tests, be explicit
def test_north_star_changelog_verbose_path_b():  # Clear what it tests
def test_north_star_changelog_brief_path_a():    # Clear what it tests
def test_north_star_triage_parameter_extraction(): # Clear what it tests
```

## The Registry Helper Pattern

Don't create complex mock registries. Use this pattern:

```python
from tests.test_planning.conftest import test_registry_data

def test_something(test_registry_data):
    """Use the existing fixture."""
    registry = test_registry_data  # Has basic nodes

    # If you need validation
    from pflow.core.workflow_validator import WorkflowValidator
    errors = WorkflowValidator.validate(
        workflow_ir=workflow,
        extracted_params=None,
        registry=registry,
        skip_node_types=False
    )
```

## Parameter Transformation (Often Missed)

The pipeline transforms user input by replacing values with parameter placeholders. Tests should simulate this:

```python
from pflow.planning.nodes import MetadataGenerationNode

# Simulate what ParameterMappingNode does
extracted_params = {
    "version": "1.3",
    "limit": "20"
}

original = "generate changelog for version 1.3 from last 20 issues"
transformed = MetadataGenerationNode._transform_user_input_with_parameters(
    original, extracted_params
)
# Result: "generate changelog for version [version] from last [limit] issues"
```

## Testing Philosophy from Task 28

### Quality Over Quantity
- 7 hard tests that find real bugs > 20 easy tests that always pass
- Each test should target a specific challenge
- If a test doesn't fail during development, it's probably too easy

### Test What Users Actually Do
- Users don't type "generate changelog"
- They type verbose specifications when creating workflows
- They type brief commands when reusing workflows
- Test the actual behavior patterns

### Validate Decisions, Not Confidence
- Don't test confidence scores (they vary by model)
- Test the decisions: Path A vs Path B
- Test the outputs: correct parameters, correct workflow structure

## Critical Success Factors

1. **Use exact north star prompts** - One word difference matters
2. **Validate specific values** - "1.3" not just "version exists"
3. **Test complete pipelines** - Not just individual nodes
4. **Use real nodes** - Mock nodes hide real issues
5. **Never fail on performance** - Log warnings instead
6. **Simulate parameter transformation** - Part of the real pipeline
7. **Test both paths** - Verbose → Path B, Brief → Path A

## Final Wisdom from Task 28

> "The best prompt can't work without data. Always verify data flow first."

> "Tests that pass easily are testing nothing important."

> "Mock nodes are technical debt disguised as tests."

> "Performance is a metric, not a pass/fail criterion."

> "Test what users do, not what's easy to test."

This guide represents hard-won knowledge from Task 28's extensive testing improvements. Following these patterns will prevent the pitfalls that created false confidence in the planner test suite.