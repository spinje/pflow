# Task 57 Handoff Memo: Critical Knowledge Transfer

## ⚠️ STOP - Read This First

**DO NOT BEGIN IMPLEMENTING** until you've read this entire document. At the end, acknowledge that you're ready to begin.

## The Real Mission (Not What It Seems)

Task 57 appears to be about "updating planner tests with north star examples." What it's ACTUALLY about: **fixing a catastrophic test quality crisis where 69% of workflow generator tests were using non-existent mock nodes**, creating false confidence that hid critical bugs. Task 28 spent weeks discovering this. You're inheriting their hard-won knowledge.

## The North Star Prompts Are Sacred

These prompts are CHARACTER-EXACT from `architecture/vision/north-star-examples.md`. Change even ONE WORD and you invalidate the entire test philosophy:

```python
# Primary - Changelog (MEMORIZE THIS)
CHANGELOG_VERBOSE = """generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."""

CHANGELOG_BRIEF = "generate a changelog for version 1.4"

# Secondary - Triage (NOTE THE DOUBLE "the" - it's correct!)
TRIAGE_VERBOSE = """create a triage report for all open issues by fetching the the last 50 open issues from github, categorizing them by priority and type and then write them to triage-reports/2025-08-07-triage-report.md then commit the changes. Replace 2025-08-07 with the current date and mention the date in the commit message."""
```

## Task 28's Shocking Discoveries You Must Know

### 1. The Metadata Disaster
Discovery prompt was failing because metadata was being generated but **NOT SAVED**. The fix wasn't better prompts - it was architectural. Check `test_happy_path_mocked.py` - it already has north star workflows but may not have proper metadata.

### 2. The Performance Testing Catastrophe
Tests were failing because they took >20 seconds. But this was API variance! Same prompt:
- gpt-5-nano: 5-15 seconds
- Claude: 20-40 seconds
- Network issues: 60+ seconds

**NEVER fail on performance. ALWAYS convert to warnings:**
```python
if duration > 20.0:
    logger.warning(f"Slow: {duration:.2f}s (model-dependent)")
    # DO NOT raise AssertionError
```

### 3. The Mock Node Lie
These nodes DON'T EXIST but were in tests:
- `claude-code` ❌
- `github-list-prs` ❌
- `slack-notify` ❌

Use ONLY real nodes from registry. Check with:
```python
from pflow.registry import Registry
registry = Registry()
registry.load()
print(registry.get_nodes_metadata())  # See what actually exists
```

## Verified Implementation Details (I Did The Research)

These are EXACT from codebase - use them precisely:

```python
# Action strings
"found_existing"  # Path A (reuse)
"not_found"      # Path B (generation)

# Shared store keys
shared["discovered_params"]["version"]  # Will be "1.3"
shared["discovered_params"]["limit"]    # Will be "20"
shared["found_workflow"]["name"]        # Will be "generate-changelog"

# Validation (it's static!)
from pflow.core.workflow_validator import WorkflowValidator
errors = WorkflowValidator.validate(workflow_ir, extracted_params, registry)

# Parameter transformation
from pflow.planning.nodes import MetadataGenerationNode
transformed = MetadataGenerationNode._transform_user_input_with_parameters(input, params)
```

## The Mock Response Format That Actually Works

Anthropic format is VERY specific:
```python
mock_response.json.return_value = {
    "content": [{
        "input": {
            "found": True,
            "workflow_name": "generate-changelog",
            "confidence": 0.95
        }
    }]
}
```

## Path A vs Path B Philosophy (Critical to Understand)

**Path A (Reuse)**: Brief prompts like "generate changelog"
- User has done this before
- Action: `"found_existing"`
- Confidence > 0.8

**Path B (Generation)**: Verbose 3-line prompts
- User explaining new workflow
- Action: `"not_found"`
- Confidence < 0.5

The VERBOSITY triggers the path, not keywords!

## The Template Validation Trap

Generated workflows with required inputs FAIL validation because validator checks if `${variable}` has a value at generation time (it never does).

```python
# This WILL fail
"inputs": {"file_path": {"required": True}}

# Use this instead
"inputs": {"file_path": {"required": False, "default": "output.md"}}
```

## Test File Placement

- Mocked tests → `tests/test_planning/integration/`
- Real LLM tests → `tests/test_planning/llm/integration/`
- New e2e test → `tests/test_planning/llm/integration/test_north_star_realistic_e2e.py`

## Files That Already Exist (Don't Recreate)

- `tests/test_planning/integration/test_happy_path_mocked.py` - HAS north star workflows!
- `tests/test_planning/llm/integration/test_generator_north_star.py` - Needs tertiary example
- `tests/test_planning/conftest.py` - Has `test_registry_data` fixture

## The Complete Pipeline Pattern

Tests must simulate the FULL flow, not isolated nodes:
```python
def test_complete_flow():
    # 1. Discovery → 2. Parameter Discovery → 3. Browsing
    # → 4. Generation → 5. Validation → 6. Parameter Mapping
```

## Critical Success Validations

```python
# These MUST be exact string matches
assert shared["discovered_params"]["version"] == "1.3"  # NOT "v1.3" or 1.3
assert shared["discovered_params"]["limit"] == "20"     # NOT 20 (int)

# This can be substring
assert "create-changelog-version-1.3" in str(shared["discovered_params"].values())
```

## What Task 28 Learned (Saves You Weeks)

1. **Context Over Prompts**: Best prompt can't work without data
2. **Quality Over Quantity**: 7 hard tests > 20 easy tests
3. **Mock Nodes = Technical Debt**: They hide real issues
4. **Performance ≠ Quality**: API speed varies 10x
5. **Test What Users Do**: Not what's easy to test

## Subtle Gotchas

- Parameter discovery uses `"parameters"` key, not `"params"`
- WorkflowValidator is static - don't instantiate
- The double "the" in triage prompt is intentional
- `discovered_params` values are strings, not ints
- Tests in `llm/` need `RUN_LLM_TESTS=1` environment variable

## Your TODO List (Already Prepared)

1. Update test_happy_path_mocked.py with exact verbose north star prompts
2. Add parameter extraction validation to test_happy_path_mocked.py
3. Update test_generator_north_star.py with exact prompts and tertiary example
4. Create test_north_star_realistic_e2e.py with complete pipeline simulation
5. Remove performance-based test failures and convert to warnings
6. Validate all tests pass with production WorkflowValidator

## Files to Reference

- `/Users/andfal/projects/pflow-test-planner-north-star-examples/.taskmaster/tasks/task_28/implementation/progress-log.md` - Task 28's journey
- `/Users/andfal/projects/pflow-test-planner-north-star-examples/architecture/vision/north-star-examples.md` - The sacred prompts
- `/Users/andfal/projects/pflow-test-planner-north-star-examples/tests/test_planning/integration/test_happy_path_mocked.py` - Already has workflows!

## The One Thing to Remember

**This isn't about updating test prompts. It's about fixing tests that were lying to us.** The tests passed but tested nothing real. Your mission is to make them test ACTUAL user behavior with EXACT prompts that reveal REAL bugs.

---

**IMPORTANT**: Reply acknowledging you've read this handoff and are ready to begin implementation. Do not start implementing until you've absorbed this critical context.