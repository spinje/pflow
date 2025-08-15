# Prompt Extraction Implementation Guide

## Mission
Extract the `WorkflowDiscoveryNode` prompt from inline Python code to a standalone markdown file, making it easy to review, test, and improve.

## Core Principle: SIMPLICITY
- Use plain markdown files with `{{variable}}` syntax
- No complex parsing or magic
- Keep it simple and maintainable

## File Structure to Create

```
src/pflow/planning/prompts/
├── discovery.md          # The extracted prompt
└── loader.py            # Simple loader to read the prompt
```

## Step-by-Step Implementation

### Step 1: Create the Prompt Markdown File

**File**: `src/pflow/planning/prompts/discovery.md`

```markdown
# Discovery Prompt

You are a workflow discovery system that determines if an existing workflow completely satisfies a user request.

Available workflows and nodes:
{{discovery_context}}

User request: {{user_input}}

Analyze whether any existing workflow COMPLETELY satisfies this request. A complete match means the workflow does everything the user wants without modification.

Return found=true ONLY if:
1. An existing workflow handles ALL aspects of the request
2. No additional nodes or modifications would be needed
3. The workflow's purpose directly aligns with the user's intent

If any part of the request isn't covered, return found=false to trigger workflow generation.

Be strict - partial matches should return found=false.
```

**IMPORTANT**:
- Copy the EXACT prompt text from lines 127-143 in `src/pflow/planning/nodes.py`
- Replace `{prep_res["discovery_context"]}` with `{{discovery_context}}`
- Replace `{prep_res["user_input"]}` with `{{user_input}}`
- Use double curly braces `{{variable}}` for all variables

### Step 2: Create the Simple Loader

**File**: `src/pflow/planning/prompts/loader.py`

```python
"""Simple prompt loader for markdown files."""

from pathlib import Path
from typing import Dict, Any


def load_prompt(prompt_name: str) -> str:
    """Load a prompt from a markdown file.

    Args:
        prompt_name: Name of the prompt file (without .md extension)

    Returns:
        The prompt text with {{variable}} placeholders

    Raises:
        FileNotFoundError: If the prompt file doesn't exist
    """
    prompt_dir = Path(__file__).parent
    prompt_file = prompt_dir / f"{prompt_name}.md"

    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    # Read the entire file
    content = prompt_file.read_text()

    # Skip the header line if it starts with #
    lines = content.split('\n')
    if lines and lines[0].startswith('#'):
        # Skip the first line (header) and any blank lines after it
        content = '\n'.join(lines[1:]).strip()

    return content


def format_prompt(prompt_template: str, variables: Dict[str, Any]) -> str:
    """Format a prompt template with variables.

    Args:
        prompt_template: Prompt with {{variable}} placeholders
        variables: Dictionary of variable values

    Returns:
        Formatted prompt with variables replaced

    Raises:
        KeyError: If a required variable is missing
    """
    # Simple replacement of {{variable}} with values
    formatted = prompt_template

    for var_name, var_value in variables.items():
        placeholder = f"{{{{{var_name}}}}}"
        formatted = formatted.replace(placeholder, str(var_value))

    # Check for any remaining placeholders (missing variables)
    import re
    remaining = re.findall(r'\{\{(\w+)\}\}', formatted)
    if remaining:
        raise KeyError(f"Missing required variables: {remaining}")

    return formatted
```

### Step 3: Update WorkflowDiscoveryNode

**File**: `src/pflow/planning/nodes.py`

Find the `exec` method of `WorkflowDiscoveryNode` (around line 116) and replace the hardcoded prompt with:

```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    """Execute semantic matching against existing workflows.

    Args:
        prep_res: Prepared data with user_input and discovery_context

    Returns:
        WorkflowDecision dict with found, workflow_name, confidence, reasoning
    """
    logger.debug(f"WorkflowDiscoveryNode: Matching request: {prep_res['user_input'][:100]}...")

    # Load prompt from markdown file
    from pflow.planning.prompts.loader import load_prompt, format_prompt

    prompt_template = load_prompt("discovery")

    # Format with our variables
    prompt = format_prompt(prompt_template, {
        "discovery_context": prep_res["discovery_context"],
        "user_input": prep_res["user_input"]
    })

    # Lazy-load model at execution time (PocketFlow best practice)
    model = llm.get_model(prep_res["model_name"])
    response = model.prompt(prompt, schema=WorkflowDecision, temperature=prep_res["temperature"])
    result = parse_structured_response(response, WorkflowDecision)

    logger.info(
        f"WorkflowDiscoveryNode: Decision - found={result['found']}, "
        f"workflow={result.get('workflow_name')}, confidence={result['confidence']}",
        extra={"phase": "exec", "found": result["found"], "confidence": result["confidence"]},
    )

    return result
```

**IMPORTANT**:
- Remove lines 127-143 (the hardcoded prompt)
- Replace with the loader code shown above
- Keep everything else exactly the same

### Step 4: Test the Implementation

Create a test script to verify everything works:

**File**: `test_prompt_extraction.py` (in project root)

```python
#!/usr/bin/env python3
"""Test that prompt extraction works correctly."""

import sys
sys.path.insert(0, "src")

from pflow.planning.prompts.loader import load_prompt, format_prompt


def test_prompt_loading():
    """Test that we can load and format the discovery prompt."""

    print("Testing prompt extraction...")

    # Load the prompt
    try:
        prompt_template = load_prompt("discovery")
        print("✅ Prompt loaded successfully")
        print(f"   Length: {len(prompt_template)} characters")
    except FileNotFoundError as e:
        print(f"❌ Failed to load prompt: {e}")
        return False

    # Test formatting with sample variables
    test_vars = {
        "discovery_context": "Available workflows:\n- generate-changelog\n- analyze-code",
        "user_input": "create a changelog"
    }

    try:
        formatted = format_prompt(prompt_template, test_vars)
        print("✅ Prompt formatted successfully")

        # Check that variables were replaced
        if "{{discovery_context}}" in formatted:
            print("❌ Variable discovery_context not replaced")
            return False
        if "{{user_input}}" in formatted:
            print("❌ Variable user_input not replaced")
            return False

        print("✅ All variables replaced correctly")

    except KeyError as e:
        print(f"❌ Missing variables: {e}")
        return False

    # Test with missing variable
    try:
        format_prompt(prompt_template, {"user_input": "test"})
        print("❌ Should have raised error for missing discovery_context")
        return False
    except KeyError:
        print("✅ Correctly detected missing variable")

    print("\n✅ All tests passed!")
    return True


if __name__ == "__main__":
    success = test_prompt_loading()
    sys.exit(0 if success else 1)
```

Run this test with:
```bash
python test_prompt_extraction.py
```

### Step 5: Verify with Existing Tests

Run the existing planning tests to make sure nothing broke:

```bash
# Run unit tests (should pass)
pytest tests/test_planning/unit -v

# Run integration tests (should pass)
pytest tests/test_planning/integration -v

# If you have LLM API configured, test with real LLM
RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_discovery_prompt.py -v
```

## Variables Reference

The discovery prompt uses these variables:

| Variable | Source in Code | Description |
|----------|---------------|-------------|
| `discovery_context` | `prep_res["discovery_context"]` | Built by `build_discovery_context()`, contains all available workflows and nodes |
| `user_input` | `prep_res["user_input"]` | The user's natural language request |

## Success Criteria

✅ The implementation is complete when:

1. `src/pflow/planning/prompts/discovery.md` exists with the prompt
2. `src/pflow/planning/prompts/loader.py` exists with the loader functions
3. `WorkflowDiscoveryNode.exec()` uses the loader instead of hardcoded prompt
4. `test_prompt_extraction.py` passes all tests
5. Existing planning tests still pass
6. The planner still works when running `pflow "create a changelog"`

## Testing the Full System

After implementation, test the full system:

```bash
# Test that the planner still works
pflow "create a changelog" --trace

# Check that discovery node executed successfully
cat ~/.pflow/debug/pflow-trace-*.json | jq '.node_execution[0]'
```

## Common Issues and Solutions

### Issue: FileNotFoundError
**Solution**: Make sure you created `src/pflow/planning/prompts/discovery.md`

### Issue: KeyError for missing variables
**Solution**: Check that variable names match exactly:
- In markdown: `{{discovery_context}}` and `{{user_input}}`
- In Python: `"discovery_context"` and `"user_input"` as dictionary keys

### Issue: Prompt format looks wrong
**Solution**: Check that you copied the exact prompt text from nodes.py lines 127-143

### Issue: Tests fail
**Solution**: You probably changed the prompt text accidentally. Compare with the original.

## Why This Approach?

1. **Simple** - Just markdown files and string replacement
2. **Visible** - Prompts are in plain text files, easy to review
3. **Testable** - Can test prompts without running the full planner
4. **Maintainable** - No complex parsing or magic
5. **Extensible** - Easy to add more prompts later

## Next Steps (After This Works)

Once WorkflowDiscoveryNode is working with external prompts:

1. Extract prompts for other nodes one by one
2. Add test cases to the markdown files
3. Create a prompt testing framework
4. Version the prompts for A/B testing

But for now, focus on just getting WorkflowDiscoveryNode working with the external prompt.

## Agent Instructions

Dear implementing agent,

Your task is to:
1. Create the two new files exactly as specified
2. Modify the WorkflowDiscoveryNode.exec() method as shown
3. Run the test script to verify it works
4. Run existing tests to ensure nothing broke

Keep it simple. Don't add extra features. Just make the prompt external and ensure it still works exactly the same way.

Good luck!